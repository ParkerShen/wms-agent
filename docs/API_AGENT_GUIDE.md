# API 与 Agent 开发说明

本文说明当前可调用的 HTTP 契约、流式事件格式和库存 Agent 的执行边界。实现代码位于 `app/main.py`、`app/agents/inventory_agent.py`、`app/tools/inventory.py` 与 `app/llm/deepseek.py`；变更后请以自动化测试和 `/docs` 生成的 OpenAPI 为准。

## 本地运行与凭据

1. 在项目根目录启动本地 PostgreSQL，按 `README.md` 执行 Alembic 迁移和模拟数据初始化。
2. 在项目根目录 `.env` 中配置 `DEEPSEEK_API_KEY`。该密钥只交给 FastAPI 进程，禁止使用 `NEXT_PUBLIC_` 前缀或放入浏览器代码。
3. 在项目根目录运行 `./.venv/Scripts/python.exe -m uvicorn app.main:app --reload`。
4. Swagger UI：`http://127.0.0.1:8000/docs`；就绪探针：`GET /health/ready`。

前端开发时，在 `frontend/` 运行 Next.js，并将其服务器端环境变量 `BACKEND_API_URL` 指向 FastAPI（默认 `http://127.0.0.1:8000`）。网页只访问 Next 的 `/api/chat` 代理路由；浏览器不会知道上游地址，也不会持有模型密钥。

## HTTP 接口

### `POST /chat`

非流式兼容接口。输入 JSON：

```json
{"message":"DEMO-WH-01 仓库的 DEMO-SKU-001 有多少可用库存？"}
```

消息长度为 1–2000 字符。成功响应：

```json
{"answer":"可用库存为 ..."}
```

未配置 DeepSeek 返回 HTTP 503；提供商或 Agent 失败返回安全的 HTTP 502；请求结构/长度不符合约束返回 HTTP 422。

### `POST /chat/stream`

流式接口使用 POST JSON 请求（不是原生浏览器 `EventSource`）。响应类型为 `text/event-stream`。每个 SSE frame 是一个 `data:` 行，JSON 数据后跟一个空行：

```text
data: {"type":"delta","text":"可用库存为 "}

data: {"type":"delta","text":"42 件。"}

data: {"type":"done"}

```

事件类型：

- `delta`：一个普通 UTF-8 文本片段，字段为 `text`；客户端按顺序拼接。
- `done`：唯一的正常终止事件。
- `error`：响应开始后发生错误时发出固定安全错误消息，不再发 `done`。HTTP 状态和头部已经提交，不能再改成 502/503。

API Key 等配置错误尽量在响应开始前验证并通过 HTTP 503 返回；上游模型或 Agent 在流式过程中失败则返回安全 `error` 事件。客户端断开时应取消流并释放上游异步 HTTP client。浏览器应通过 `fetch`/ReadableStream 发送 POST 并解析 SSE，不使用只能 GET 的 EventSource。

### `GET /data/warehouses`

只返回当前虚构展示批次中的仓库列表（不是所有 Warehouse 数据）。无请求参数。

### `GET /data/inventory?warehouse_code=...&sku_code=...`

精确查询一个仓库和一个 SKU。未知仓库或 SKU 返回 404；已知实体但无库存记录返回 200、零数量、空库位，并通过 `has_inventory_record: false` 区分。

模拟项目的可用数定义为：

```text
available = good_on_hand - allocated - frozen
```

该数字是本项目的假设，不代表真实 WMS 口径。在途数量单独返回，不加到可用数中。响应含仓库/SKU 信息、汇总、库位明细及商品展示属性。

### `GET /data/orders/{order_no}`

只读返回订单存储状态、订单行、已记录异常与物流轨迹；未找到返回 404。时间统一按 UTC 返回，订单行按行号排序，异常和轨迹按发生时间及 ID 排序。缺少状态字典或证据时接口不推断未出库根因。Agent 当前尚不支持订单自然语言查询。

### 健康检查

- `GET /health`：进程存活；不检查数据库。
- `GET /health/ready`：执行只读 `SELECT 1`；数据库不可达返回 HTTP 503。

## Agent 调用链

1. `ChatRequest` 校验输入，然后 FastAPI 为请求创建 SQLAlchemy Session 和 DeepSeek client。
2. `run_inventory_agent` / `stream_inventory_agent` 将系统约束和用户问题交给模型，并提供固定的函数 Tool schemas。
3. 固定 allowlist 提供 `query_inventory`、`list_warehouses`、`list_warehouse_products` 和 `find_product_warehouses`。查询工具使用严格 Pydantic schema；目录查询只访问 `SHOWCASE-V2-20261013` 虚构展示批次，仓库与商品名称/城市匹配由后端确定性完成，不允许模型猜编码或拼 SQL。
4. 名称匹配优先完整代码、名称或城市，再匹配唯一子串。若匹配多个实体，工具返回有限候选，Agent 应请用户澄清；没有匹配时明确报告未找到。
5. 仓库商品/商品所在仓库结果只根据该展示批次的库存余额和在途库存记录，分别返回现货、模拟可用量、在途量及库位数。订单行不作为仓库有货的证据。在途不代表已经存放在仓库库位。
6. 目录列表每页最多 5 条商品/仓库反查结果（仓库目录最多 10 条），并返回总数、`has_more` 和 `next_offset`；Agent 必须如实说明结果不完整。现有详细库存查询仍可由 `query_inventory` 按确切仓库/SKU 编码调用。
7. 将结果按原始 `tool_call_id` 作为 `tool` 消息回传模型直到最终文本；绝不执行模型提供的 SQL。同步与流式路径共享注册工具、轮数/调用数/结果大小限制和安全错误处理。
8. 当前限制最多 3 轮工具调用、每轮最多 4 次调用、传回模型的序列化 Tool 结果最多 4000 字符。工具调用无效或执行失败时仅返回安全、简短的错误信息，不泄露数据库异常。

同步与流式 Agent 共享工具契约和限制。流式版本会在收到文本片段时立即发给 UI；如果模型在同一轮还返回工具调用，这些文本也可能先于工具执行结果展示。分片工具参数则会缓存到当前模型轮结束，再验证调用 ID、类型、名称、JSON 参数和轮次上限；只有完整且通过校验的调用才会执行。

## DeepSeek 客户端生命周期

`DeepSeekClient` 提供同步 `create_chat_completion` 与异步 `stream_chat_completion`。创建的同步/异步 HTTP client 由该实例拥有，并在 FastAPI dependency teardown 中通过 `aclose()` 关闭；注入的 client 归调用方管理。provider HTTP 状态、无效 JSON/SSE 和网络错误都会被转换成不包含密钥或响应体的 `DeepSeekClientError`。测试应使用 HTTP mock，不调用真实 DeepSeek 服务。

## 修改时的检查点

- 修改数据查询先更新 Repository/API 测试，再考虑 Agent 提示词；不要在 Agent 中绕过 Repository。
- 修改 Tool 名称、参数或返回值时，同步更新 `QUERY_INVENTORY_TOOL`、模型消息构造、测试与 OpenAPI/本文档。
- 修改 SSE 协议时，同步更新 Python SSE 编码、Next 代理/解析器、前端解析测试及本文档；每帧必须以空行结束。
- 涉及工具循环时保留 allowlist、轮次/调用数/结果大小上限和异常脱敏，并测试超限场景。
- 流式任务应确保 `done`/`error` 是终止事件；取消请求不能在客户端断开后继续消耗模型资源。
- `tests/` 中的自动化测试是可执行的行为契约。不要在代码注释中复制测试断言或说明显而易见的赋值。
