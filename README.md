# 云仓 AI Agent（本地模拟项目）

这是一个独立的本地练习项目，库存样例全部为自造数据，不连接公司 WMS、UAT、生产环境或真实数据库。

## 本地启动模拟库存数据

确保 Docker Compose 中的本地 PostgreSQL 已启动，然后从项目根目录运行：

```powershell
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m app.seed
```

种子命令可重复运行：它会按固定的 `DEMO-*` 业务编码新增或恢复这组模拟记录的预设值，不会清空表或删除其他记录。仅用于本项目本地开发数据库。

## 大型虚构演示数据

批量数据生成器会构造一个固定的新版本批次，共 48,050 行：50 个中英双语海外仓、2,000 个多品类 SKU、500 个库位、10,000 条库存余额、2,000 条在途库存、10,000 笔订单、15,000 条订单明细、8,000 条物流轨迹和 500 条异常。商品包含结构化危险品与大件标记；订单号以仓库业务编码开头。仓库地址、坐标、电话号码、订单、商品及物流事件均为虚构演示数据，不代表真实设施、联系人、货物合规结论或实际运输记录。危险品分类/UN 编号只用于演示，不是法规或操作指导。

普通命令不删除任何数据；若旧批次仍存在会拒绝写入。只有用户明确选择的旧批次替换流程会执行精确校验、先制作并检查本地 PostgreSQL 备份，再在单一事务中替换完全匹配的旧 `DEMO-BULK-V1-` 批次：

```powershell
.\.venv\Scripts\python.exe -m app.seed_bulk
.\.venv\Scripts\python.exe -m app.seed_bulk --replace-v1
```

替换流程严格限制在 `127.0.0.1:5433/yuncang`，不会按宽泛前缀删除；发现旧数据内容不匹配、额外外键依赖或非批次记录变化时会中止。完成后新版批次应为 48,050 行，连同原有 16 条记录共 48,066 行。请勿在公司 UAT、生产或真实 WMS 环境运行。

截至 2026-10-13，新版数据已加载至本机数据库并完成精确校验：各表共 48,050 条新版记录，加原有 16 条共 48,066 条。旧批次已全部替换，原有 16 条记录快照哈希未变化。备份文件位于 `backups/yuncang-before-showcase-20261013-163203.dump`。

`GET /data/warehouses` 返回 50 个双语演示仓库；`GET /data/inventory` 提供 SKU 品类、危险品/大件属性及适用库位信息；`GET /data/orders/{order_no}` 返回仓库、SKU 订单行和订单状态/轨迹。以上查询接口只读。聊天 Agent 还可通过中文或英文仓库名、城市和商品名在模拟展示批次中发现仓库与商品；此能力不会更改现有 HTTP 查询 API。

## 查询库存

启动 API 后，可用仓库和 SKU 编码进行只读查询：

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

打开 `http://127.0.0.1:8000/docs`，或直接请求：

```text
GET http://127.0.0.1:8000/data/inventory?warehouse_code=DEMO-WH-01&sku_code=DEMO-SKU-001
```

响应提供仓库/SKU、各库位良品数量/分配/冻结/可用数量，以及仓库/SKU 汇总和在途数量。模拟可用量按“良品数量 − 分配数量 − 冻结数量”计算；在途量独立展示，不计入可用量。未知仓库或 SKU 返回 404；已知仓库和 SKU 但无库存记录时返回 200、零数量、空库位列表和 `has_inventory_record: false`。

## DeepSeek 配置与自然语言查询

`POST /chat` 可用自然语言查询模拟库存。复制 `.env.example` 时，可在本地 `.env` 中配置 `DEEPSEEK_API_KEY`；不要提交或分享密钥。默认服务地址为 `https://api.deepseek.com`，模型为 `deepseek-chat`。请求示例：

```json
{"message":"DEMO-WH-01 仓库的 DEMO-SKU-001 有多少可用库存？"}
```

```text
POST http://127.0.0.1:8000/chat
Content-Type: application/json
```

`POST /chat` 支持基于模拟库存数据的自然语言查询。除使用编码查询外，也可以用中文仓库名、城市或商品名询问，例如“有哪些仓库？”“洛杉矶仓库有什么商品？”“蓝牙降噪耳机（曜石黑）在哪些仓库有库存？”。Agent 通过固定只读工具列出展示仓库、按仓库查有库存记录的商品、按商品查所在仓库；匹配不唯一时会返回候选供澄清。查询结果最多每页 5 条（仓库目录最多 10 条），返回总数和是否还有后续页；库存商品中的现货/可用量与在途量分开显示，不能把在途商品说成已在库位。

需要查询一个商品在指定仓库的详细可用/占用/冻结、在途和库位数据时，仍可通过既有 `query_inventory` Tool 按仓库与 SKU 编码查询。当前不支持订单自然语言查询，也不会修改任何业务数据。请求缺少 API key 返回 503，提供商或 Agent 调用失败返回不含内部细节的 502。自动化测试使用模拟模型，不会调用真实 DeepSeek API。

打开 `http://127.0.0.1:8000/` 可继续使用旧版单文件 HTML 页面。Next.js 前端的流式问答启动步骤见下文“Next.js 流式聊天前端”。真实回答需要在 API 项目根目录 `.env` 配置有效的 `DEEPSEEK_API_KEY`。


```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```


## Next.js 流式聊天前端

前端位于 `frontend/`，使用 Next.js App Router、React、TypeScript、Tailwind CSS v4，并配置了 shadcn/ui 风格的本地组件。Next.js 通过服务端 `/api/chat` Route Handler 转发到 FastAPI，不将 DeepSeek Key 暴露给浏览器。

先启动 PostgreSQL 和 FastAPI，再打开另一个终端：

```powershell
cd frontend
Copy-Item .env.example .env.local
npm install
npm run dev
```

浏览器访问 `http://localhost:3000`。默认上游地址是 `http://127.0.0.1:8000`，若 FastAPI 在其他地址，将 `BACKEND_API_URL` 配在 `frontend/.env.local`。该变量只在 Next.js 服务端使用；DeepSeek 凭据仍只放在项目根目录的 API `.env` 中。

聊天使用 `POST /chat/stream`，SSE 正常事件依次由一个或多个 `delta` 和一个 `done` 组成；流开始后的错误通过安全 `error` 事件传递。前端使用 fetch 流式读取，允许中止当前请求。API/Agent 的详细契约和修改检查点见 [`docs/API_AGENT_GUIDE.md`](docs/API_AGENT_GUIDE.md)。

前端常用验证命令：

```powershell
npm run typecheck
npm run lint
npm test
npm run build
```

旧页面仍可从 FastAPI 的 `http://127.0.0.1:8000/` 访问，作为 Next.js 页面迁移期间的 fallback。前后端聊天均支持只读中文仓库/商品发现和库存问答；订单自然语言查询、登录、会话历史和写操作仍未实现。


订单接口返回模拟数据中记录的状态、异常和物流轨迹；不会从状态或轨迹推断未出库根因。

```text
GET http://127.0.0.1:8000/data/orders/DEMO-ORDER-1001
```

样例订单：
- `DEMO-ORDER-1001`：有两条按 UTC 时间排序的模拟物流事件。
- `DEMO-ORDER-1002`：有一条明确记录的地址核对异常；接口只报告该异常记录，不进一步推断。
- `DEMO-ORDER-1003`：已知订单，但没有异常或轨迹记录，接口返回空列表。

未知订单号返回 404。时间以 UTC 格式返回。
