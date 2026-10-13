# 云仓 AI Agent 项目计划（无日期版）

> 这是独立练习项目的路线图，只定义阶段顺序和完成标准，不排具体日期。每阶段通过验收后再进入下一阶段。业务数据全部自造；公司 WMS 只作为理解业务概念的参考，不复制源码、真实数据或凭据。

## 项目目标

开发一个云仓运营助手，先服务两类用户，以只读方式回答问题：

1. **仓库主管查库存**：查询某仓库、某 SKU 的可用、占用/分配、在途数量和库位。
2. **客服查订单**：查询订单进度，并在数据有依据时解释未出库卡点、显示异常或最新轨迹。

先完成库存场景，再完成订单场景。Agent 不编造数据，也不直接修改库存或订单。

## 阶段路线

| 阶段 | 目标 | 主要工作 | 完成标准 | 状态 |
|---|---|---|---|---|
| **V0 模拟数据层** | 建成可运行的“假云仓” | 项目骨架；PostgreSQL 16 + pgvector；Alembic 数据迁移；自造 seed 数据；Repository 与单测；FastAPI 只读 `/data/*` 接口 | 一条命令启动并灌入模拟数据；Swagger 可查 SKU、库存、订单；库存明细与汇总可核对 | 库存和订单模拟 schema、种子数据、只读 Repository/API 已实现；订单 migration 升级、订单样例运行、全量测试和一致性检查已完成；downgrade/re-upgrade 因降级会删除现有订单数据而暂缓，后续仅在可丢弃数据库验证 |
| **V1 单 Agent** | 自然语言完成首批两个查询场景 | `query_inventory` Tool 和测试；手写 Agent loop；`query_order` Tool 和测试；`/chat`；记录 Tool 调用；建立小型评测集 | 两场景均能基于模拟数据回答；无数据不编造；Tool 选择和参数能用评测用例验证 | 已完成库存 Tool、DeepSeek client、bounded inventory loop 和只读 `POST /chat`；当前 `/chat` 只支持库存场景，订单自然语言 Tool、调用记录和评测集未开始；全量 51 项测试通过；未执行真实 API 请求 |
| **V2 LangGraph + RAG** | 增加可控流程与 SOP 知识问答 | 将 loop 迁移到 LangGraph；SOP 切片与检索；库存预警/异常汇总；流式响应和基础前端 | 知识回答带来源；混合问题的数据与文档引用清楚；多轮指代通过测试 | 未开始；流式 SSE 接口和独立 Next.js 库存聊天界面已在 V1 前端补充工作中实现/验证，尚未开始 LangGraph 或 RAG |
| **V3 受控写操作** | 练习人工审批闭环 | 身份与数据范围；生成操作申请；审批中断与恢复；确定性业务服务；审计与幂等 | 未经批准不执行；批准后可追溯；重复请求不重复执行；越权测试全部拒绝 | 未开始；V1/V2 前不做写操作 |
| **V4 评测与可观测** | 衡量质量、成本和故障 | 扩充评测集；运行对比报告；记录调用轨迹、Token、延迟和失败；必要时增加限流 | 改模型或 Prompt 后能比较质量；关键运行数据可查看 | 未开始 |
| **V5 真实系统只读对接（可选）** | 将模拟 Repository 换成受控真实数据源 | 定义 DataSource 抽象；对齐字段与状态；通过批准的只读 API 接入 | 先获得公司明确授权和独立只读账号；无写调用；真实数据测试通过 | 未授权前不做 |
| **V6 多 Agent（可选）** | 仅在单 Agent 有证据不足时拆分 | 根据评测结果探索 Supervisor 或领域子 Agent | 对比数据证明成功率、质量或成本有改善，否则不引入 | 未开始 |

## 核心边界与临时假设

- **模拟数据优先**：V0–V4 不连接公司 UAT、生产环境或真实数据库。
- **库存口径**：可用库存暂按“库位良品数量 − 已分配数量 − 冻结数量”作为模拟项目假设；这是待测试和调整的本项目定义，不代表公司系统规则。
- **订单解释**：状态、异常和轨迹分别作为证据；若缺少状态字典或足够证据，只报告查询到的字段，不推断根因。
- **权限边界**：后续 Agent Tool 的客户/仓库范围由后端控制，不允许模型自行扩大查询范围。
- **技术路线**：Python 3.10（当前本机版本；后续视依赖兼容性再评估升级）+ FastAPI + SQLAlchemy + Alembic + PostgreSQL 16/pgvector；V1 手写工具调用循环，V2 再迁移 LangGraph；默认 LLM 为 DeepSeek `deepseek-chat`。
- **渐进开发**：先让确定性数据接口正确，再连接 Tool 和 Agent；Agent 不拼 SQL、不直连数据库。

## 当前进度与下一步

- 已完成：独立项目目录、项目说明、首批两类用户及只读场景。
- 已完成：数据库 Compose 配置（PostgreSQL 16 + pgvector）、本地 `.env`、`.env.example` 和 `.gitignore`；Compose 配置语法校验通过。
- 已完成：PostgreSQL 容器启动并通过 healthcheck；因本机 5432 端口不可绑定，项目映射到 `127.0.0.1:5433`；已创建并验证 `vector` 扩展（0.8.7）。
- 已完成：Python 3.10 虚拟环境、FastAPI `/health`、数据库配置加载和 SQLAlchemy 连接（`127.0.0.1:5433`）；`/health/ready` 执行 `SELECT 1`，测试覆盖健康检查、就绪成功和错误信息脱敏（3 项通过）。
- 已完成：Alembic 配置及首个库存 schema 迁移，包含仓库、SKU、库位、库位库存余额和仓库/SKU 在途数量；本机 PostgreSQL 已升级至该版本，降级/重升与 `alembic check` 均通过；ORM 约束测试及现有测试共 6 项通过。
- 已完成：可重复运行的合成库存种子命令；连续执行两次后本地样例数量稳定为仓库 1、SKU 2、库位 2、库存余额 3、在途记录 2；包含重置样例值、不影响其他业务记录的隔离测试与回滚测试。全套测试 10 项通过，`alembic check` 通过。
- 已完成：只读库存 Repository/API，支持按仓库与 SKU 编码查询汇总及库位明细；独立查询在途量，避免聚合重复；未知编码返回 404，无库存记录返回零结果。API 测试覆盖正常、未知及空数据场景；全套测试 14 项通过。
- 已完成：订单模拟迁移、重复执行安全的种子数据，以及只读 `GET /data/orders/{order_no}`；输出存储的状态、异常和按 UTC 时间排序的轨迹证据，不推断原因。订单 API/seed 测试已通过；当前全套测试 20 项通过，`alembic check` 通过。
- 待验证：订单 migration downgrade/re-upgrade；本地数据库订单 migration 已升级且订单 seed 命令已连续运行两次。降级会删除订单表和数据，因此当前数据予以保留；仅在可丢弃数据库中验证。
- 已完成 V1 第一项：新增只读 `query_inventory` Tool adapter，输入限制为仓库/SKU 编码并复用现有 Repository；测试覆盖参数 schema、结果、未知/空/仅在途数据、JSON 序列化和无写入，全套 26 项通过。
- 已完成 V1 Agent loop 第一版：增加 bounded inventory tool-call loop，使用固定 allowlist，只派发 `query_inventory`，保留 assistant tool-call 消息并按 call ID 回传 JSON 工具结果；最多 3 轮、每轮 4 个调用，限制工具结果长度并对异常脱敏。测试覆盖 final response、单/多工具调用、schema 转换、坏参数/未知工具、缺失数据、无效 ID、轮数/调用数上限、结果长度限制和错误脱敏。Loop focused 测试 10 项通过；全套测试 42 项通过（1 个已有弃用警告）。全程使用模拟模型与 SQLite 测试数据，没有真实网络调用。
- 已完成 V1 `/chat` 路由：`POST /chat` 接收 1–2000 字符 `message`，按请求创建并清理 DeepSeek client，复用库存 Agent loop，返回 `answer`；未配置 API key 返回 503，提供商或 Agent loop 失败返回安全的 502。新增测试覆盖成功文本、库存 Tool 调用、校验、错误脱敏和 client 清理；测试不调用真实 DeepSeek API。
- 已完成流式库存问答基础垂直切片：修复异步 Agent streaming loop 与 SSE 帧分隔，新增 `POST /chat/stream`（JSON POST + `text/event-stream`，delta/done/error 事件）；请求级依赖通过 `aclose()` 清理异步 client。流式 Agent/API mock 测试通过；端点开始返回后错误使用固定安全事件。流式 Agent 会立即 yield 文本，工具调用仍在完整接收并校验后执行。
- 已搭建独立 `frontend/` Next.js 16 + React 19 + TypeScript + Tailwind v4 App Router 聊天页、shadcn/ui 风格本地组件及 Next 服务端 `/api/chat` 代理。Next UI 用 fetch/ReadableStream 消费自定义 SSE，不接触 DeepSeek key；项目根目录 FastAPI HTML 页暂留作 fallback。lint、前端测试、类型检查和 production build 均已通过。双服务本地 smoke 确认页面 HTTP 200，代理在临时禁用模型凭据时返回预期 503；真实 delta 由 mock 测试覆盖，未执行真实模型请求。本轮未做浏览器驱动的视觉验收。
- 已为 API 路由添加 OpenAPI 描述与主要字段契约；为 Agent、Tool、DeepSeek 客户端、库存/订单 Repository 补关键 docstring，新增 `docs/API_AGENT_GUIDE.md`，说明 HTTP/SSE 契约、循环限制、allowlist、错误脱敏和资源生命周期。文档不逐行解释显然代码，自动化测试继续作为行为契约。
- 已完成 V1 同源聊天 UI：FastAPI `GET /` 返回原生页面，`POST /chat` 支持库存自然语言提问；当前没有配置 DeepSeek API key，因此未做真实模型联调。
- 已创建并验证新版展示数据生成器和只读查询结构：计划批次 48,050 行，包括 50 个中英双语海外仓、2,000 个多品类 SKU、500 个库位、10,000 条库存余额、2,000 条在途、10,000 笔订单、15,000 条订单明细、8,000 条物流轨迹、500 条异常。新增危险品/大件结构属性、订单仓库关联和订单行。仓库联系方式、地址、坐标及所有业务记录都是虚构演示信息；危险品分类/UN 编号不构成法规或操作指导。
- 已完成本地兼容性迁移并只读核对旧 V1 数据；本地备份已制作且 `pg_restore --list` 验证。替换程序只接受精确匹配的旧批次、会保护原始 16 行，并要求 `--replace-v1` 显式替换。为确保最后一刻仍保护批次外数据，已新增替换插入后的保留行快照复核，并将 `order_items` 纳入备份清单。替换动作已在用户明确确认后完成，具体数据计数、备份与校验见下方最终结果。
- 批次已在本机 `127.0.0.1:5433/yuncang` 完成精确替换：将完全校验一致的 `DEMO-BULK-V1-` 替换为 `SHOWCASE-V2-20261013`；旧批次各表均为 0，新批次各表行数为 50/2,000/500/10,000/2,000/10,000/15,000/8,000/500，合计 48,050，加保留原始 16 行共 48,066。替换前备份 `backups/yuncang-before-showcase-20261013-163203.dump` 已通过 `pg_restore --list` 检查，SHA-256 为 `b7571c02b8c99927723f7df7e588a6a3dd03d3ce2d13027a3fbcc815bd600c0c`。完整批次内容校验通过，原先 16 条记录的所有表快照哈希保持一致。
- API smoke 验证通过：`/data/warehouses` 返回 50 条中英双语记录；库存 API 返回危险品等级/UN 编号和大件尺寸；订单 `AEDXB-20260701-000001` 归属 `AEDXB` 且返回 2 条订单行。完整新版种子再次运行已幂等跳过，没有改动记录。
- 已完成流式/前端切片及文档：后端全量 pytest 75 项通过（1 个已有 Starlette/httpx 弃用警告）；前端 lint、2 项 Vitest、typecheck、Next production build 全部通过。无真实模型联调：本地请求在显式清空 `DEEPSEEK_API_KEY` 的进程中于响应头前返回 503；Next 页面返回 200。此前那次意外真实 API 请求仍按历史事实记录在上方，不作为本轮验证结果。

- 下一步：做一次不触发模型的浏览器视觉检查；之后再决定是否移除 FastAPI 旧 HTML 页面。若需验证真实模型回答，须由用户在本地明确授权可能产生的 API 费用后另行执行。订单自然语言 Tool、评测集和 LangGraph/RAG 仍按阶段顺序推进。公司环境不连接。


- 后续每推进一步：更新这里的阶段状态和下一步；做出新决定时，同时同步更新项目说明 `CLAUDE.md`。

## 参考资料边界

初版产品/架构建议由 `docs/warehouse-mvp/07–12` 整理而来。该原始目录位于公司项目工作区；本计划只保留经改写的个人项目路线，不要求开发时访问公司仓库。静态源码观察只能帮助列出待核对字段，不能替代完整数据库定义、业务状态字典或授权的 UAT 验证。
