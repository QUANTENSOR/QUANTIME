---
id: ADR-0003
title: 系统架构：技术栈、模块分层、Parquet/DuckDB 数据分区、前后端边界、多市场抽象
status: PROPOSED
date: 2026-09-20
deciders: WitnessJ (pending)
depends_on: [ADR-0001, ADR-0002]
research:
  - docs/research/crypto-market-and-binance-public-api.md（QNT-24，PR #5，verify-b 返修中）
  - docs/research/oss-references.md（QNT-25，PR #6，verify-b 审中）
  - docs/research/other-markets-survey.md（QNT-26，PR #4，verify-b 审中）
task: QNT-23（父 QNT-34；任务描述原文见 QNT-34 卡面，来源分支 ai_task_describe @ 9976805）
---

# ADR-0003 系统架构（PROPOSED）

> 本 ADR 回答任务描述【描述1】"先设计好整个项目的架构"。任务描述只是任务描述，不是规则：凡与 ADR-0001 / ADR-0002 / AGENTS.md 冲突之处，以后者为准，冲突逐条列于 §9「未决项与冲突」。技术栈选项已由 owner 在 QNT-34 清单裁决（2026-09-19：7A–12A），本文直接采用，不再列为待选。三份调研（QNT-24/25/26）尚未合入 main，本文引用其分支版本；调研返修不改变本文决策，只可能修正 §9 的事实项。

## 1. Context

- 产品定义（AGENTS.md §1，owner 2B）：**美股 + 美股期权 + 加密（CEX 现货/USDT 永续）**、日线为主的量化研究系统；第一阶段 research / 回测，第二阶段 paper 交易。任务描述列出的 A股 / 国内期货 / 公募基金 / 港股只做接口预留（QNT-26 调研）不实现；DEX 不做（6A）。
- 六个一级模块（任务描述）：行情看板、数据中心、研报资料、因子宫殿、策略工厂、~~实盘交易~~ → **paper 交易**（ADR-0001 D1.3）。
- 硬约束：ADR-0001（agent 永不持有实盘凭据；实盘路径只到"订单意图 → 人工确认"）、ADR-0002（append-only、每行带 provenance、按 `ingestion_batch` 重放）、`.claude/rules/crypto-boundaries.md`（allowlist、下单类代码禁主网 host 字面量、perp 回测黄金用例）。
- 运行环境：单机 LXC（owner 常驻检出 `/home/workspace/quantime` 只读）；数据是许可受限资产，`data/` 永不入库；仓库只放**小样本**合成/公开数据。
- 任务描述要求"计算高性能"与"DuckDB + Parquet 按 市场/品种/数据类型/周期 分目录存储"，两者与 ADR-0002 D2.6/D2.7 同向。

## 2. Decision — 技术栈（owner 2026-09-19 裁决，直接采用）

| 层 | 选型 | 备注 |
|---|---|---|
| 语言 / 版本 | Python `>=3.14`（取当前最新补丁；`requires-python = ">=3.14"`） | 任务描述写 3.14.5，该补丁号存在性未验证（矛盾 #21），故写下界不写精确号 |
| 包管理 | `uv`（workspace 模式，单 `uv.lock`） | 8A |
| 存储 | Parquet 文件 + DuckDB（**只作查询/视图层**，不持久化业务表） | ADR-0002 D2.6；见 §4 |
| 计算 | DuckDB SQL + numpy 为主；polars 可选（只允许出现在 `packages/factors` 与 `packages/backtest` 的显式适配层） | 9A；numba 不作基线依赖，若引入需单独 ADR 修订 |
| 后端 API | FastAPI（OpenAPI 3.1 自动契约） | 10A |
| 前端 | React + TypeScript + TradingView Lightweight Charts（Apache-2.0）；深色主题参考 TradingView Dark（图表区）+ Linear 中性灰阶（导航/表格/表单），只参考色阶与密度，不复制 UI 资产 | 11 |
| 仓库形态 | monorepo：`packages/*`（Python，uv workspace members）+ `apps/web`（pnpm 单包） | 12A |
| 调度 / 常驻 | systemd user unit（沿用 QNT-17 的 `op` 注入模式）；不引入消息队列、不引入独立数据库服务 | 单机第一阶段够用；Revisit 见 §10 |

不选的（记录以免重议）：pandas 作为**内部计算**基线（保留为 I/O 与展示适配，因子/回测热路径不用 pandas 对象）；SQLite/Postgres 作业务库（第一阶段无多写者，DuckDB 视图层 + Parquet 满足 ADR-0002；Postgres 估算 1.4–2.1 TB 见 ADR-0002 修订）；Vue（前端参考项目 frequi 是 Vue，已排除）。

## 3. Decision — 模块分层与目录骨架

### 3.1 一级模块 → package 映射

| 任务描述一级模块 | package / app | 二级功能（第一版范围） |
|---|---|---|
| 数据中心 | `packages/data` | 数据源适配（`DataSource` 接口）、摄取任务、`ingestion_batch` 写入、缺口/重复核查、Parquet 落盘、DuckDB 视图注册 |
| 因子宫殿 | `packages/factors` | 因子表达式（字符串 DSL → DuckDB SQL / numpy 算子）、因子计算与缓存、IC/分层收益评估、因子库元数据 |
| 策略工厂 | `packages/backtest` + `packages/portfolio` | 向量化日线回测引擎（手续费/滑点/资金费率）、前视检测自检、组合优化（等权/风险平价/均值-方差）、绩效报告；与 vectorbt（首选）/ bt（备选）对拍 |
| paper 交易 | `packages/execution` + `packages/risk` | 多账户 paper/testnet 适配、订单意图生成、allowlist 启动断言、风控限额（仓位/回撤/杠杆）、告警；**无实盘下单代码** |
| 行情看板 / 研报资料（后端） | `packages/api` | FastAPI 应用：行情/因子/回测/资料索引只读 API；写操作仅限研报元数据与用户笔记 |
| 行情看板 / 研报资料（前端） | `apps/web` | React 单页：K 线（Lightweight Charts）、因子面板、回测报告、资料索引与检索 |
| 横切 | `packages/core` | `Market` / `Instrument` / `Calendar` 抽象、Parquet 路径规范、`run_id`/`batch_id` 生成、配置与 `op` 注入读取、日志 |

与 QNT-4 骨架提案（`packages/{core,data,backtest,research,execution,risk,monitor}`）的差异及理由：
- `research` → 拆为 `factors`（因子是独立一级模块）与 `portfolio`（组合优化与回测引擎解耦，便于对拍时只替换引擎）。
- 新增 `api`：QNT-4 未含前后端；行情看板/研报资料共用一个后端进程。
- `monitor` → 并入 `risk`（第一阶段监控对象只有 paper 账户风险与摄取健康度，不值一个包）；若第二阶段需要独立 alerting 再拆。
- 其余同名包语义不变。

### 3.2 目录骨架（**只写在文档里，不预建空目录**；每个目录在对应实现卡里随首个真实文件创建）

```
pyproject.toml            # uv workspace root
uv.lock
packages/
  core/       quantime_core/       {markets.py, instruments.py, calendar.py, paths.py, ids.py, config.py}
  data/       quantime_data/       {sources/{base.py, binance_public.py}, ingest.py, batches.py, checks.py, views.py}
  factors/    quantime_factors/    {expr/{parser.py, ops.py}, compute.py, evaluate.py, registry.py}
  backtest/   quantime_backtest/   {engine.py, costs.py, funding.py, lookahead.py, report.py, crosscheck/{vectorbt_ref.py, bt_ref.py}}
  portfolio/  quantime_portfolio/  {equal.py, risk_parity.py, mean_variance.py}
  execution/  quantime_execution/  {allowlist.py, intents.py, paper/{base.py, binance_testnet.py}}
  risk/       quantime_risk/       {limits.py, monitor.py, alerts.py}
  api/        quantime_api/        {main.py, routers/{market.py, factors.py, backtests.py, library.py}}
apps/web/                          # React + TS, Vite, Lightweight Charts
fixtures/                          # 仅合成数据，文件头 synthetic: true
data/                              # gitignored；见 §4 分区
docs/{adr,research,ops}
systemd/                           # unit 模板（*.tpl），值由 op 注入
```

命名规则：Python 包名前缀 `quantime_`；每个 package 独立 `pyproject.toml`，互相依赖只允许**向下**（`api → {factors,backtest,portfolio,execution,risk,data} → core`；`execution/risk` 不得 import `backtest`；`data` 不得 import 任何上层）。依赖方向由 CI 的 import-linter 规则守卫（实现卡 QNT-27）。

## 4. Decision — 数据层：Parquet 分区 + DuckDB 视图 + append-only 落地

### 4.1 目录规范（承接任务描述【描述2】，与 ADR-0002 D2.6/D2.7 对齐）

```
data/
  raw/<source>/<batch_id>/...                         # 原始响应 JSONL/zip，按 batch 不可变（D2.6）
  lake/<market>/<asset_class>/<datatype>/<freq>/<symbol_or_universe>/
       batch=<batch_id>/part-0000.parquet             # 归一化数据；一个 batch 只写新文件，永不改旧文件
  meta/{trading_calendar,instrument_meta,adjust_factor,ingestion_batch,source_conflict}/
       batch=<batch_id>/part-0000.parquet
  runs/<run_id>/{manifest.json, results/*.parquet}    # 回测/研究 run 产物（D2.4 data_snapshot 落在 manifest）
```

- 路径分量取值受 `packages/core/paths.py` 的枚举约束：`market ∈ {crypto, us, cn, hk}`；`asset_class ∈ {spot, perp, delivery, equity, etf, option, future, fund}`；`datatype ∈ {kline, trade, agg_trade, funding, open_interest, mark_price, book_depth, nav, dividend, corp_action}`；`freq ∈ {1m, 5m, 15m, 1h, 4h, 1d, 1w, 1mo, tick, event}`。**周期命名统一用 Vision 文件名口径 `1mo`，不用 REST 的 `1M`**（QNT-24 矛盾项，避免大小写歧义）。
- 每个 Parquet 行必带 ADR-0002 列：`source, source_version, ingested_at, run_id, batch_id`。
- 只 insert 的落地方式：**新 batch = 新目录**；重跑同一区间写新 `batch_id`，`source_version` 不变、附 `rerun_of=<batch_id>`；"当前视图"由 DuckDB 视图 `latest_per_source` 按 `(natural key, source)` 取最大 `batch_id`。
- 上游归档（Vision zip）**可被替换**（QNT-24 verify-b 指正）：重放只依赖本地 `raw/` 副本与 `ingestion_batch.content_sha256`，永不把上游 URL 当作快照。

### 4.2 DuckDB 的角色

- 单文件 `data/quantime.duckdb` 只存**视图定义与宏**（可从仓库内 SQL 重建，`packages/data/views.py` 幂等注册）；不存业务行。丢掉该文件不丢数据。
- 查询经 `read_parquet('data/lake/.../batch=*/**.parquet', hive_partitioning=true)`；复权价、连续合约等**派生价在视图层合成**，不落盘（QNT-26 §3.4 第 3 条）。
- 重放：run 的 `manifest.json` 记录 `{tables: {name: {max_batch_id, file_list, sha256s}}, config_hash, git_commit}`；重放读 manifest 的**精确文件清单**而非 `batch_id ≤ N`（回应 ADR-0002 未决项第 2 条，见 §9.4）。

### 4.3 `ingestion_batch` 表（ADR-0002 D2.7 落地）

`batch_id`（ULID，单调）、`source`、`source_version`、`market/asset_class/datatype/freq/scope`、`range_start/range_end`、`row_count`、`content_sha256`（归一化 Parquet 的 sha）、`raw_sha256`（raw 文件 sha）、`manifest_path`、`committed_at`、`rerun_of`、`run_id`。写入顺序：先落 raw → 写归一化 Parquet 到临时名 → 计算 sha → rename 到最终路径 → 最后 insert `ingestion_batch` 行；**未出现在 `ingestion_batch` 的文件视为不存在**（视图只 join 已提交 batch）。

## 5. Decision — 性能策略与可量化验收

- 热路径（因子计算、回测撮合、绩效统计）只允许 DuckDB SQL、numpy 数组、可选 polars；禁止 Python 行级循环与 pandas `apply`。
- 因子用**字符串表达式 DSL**（借鉴 qlib `ops.py` 的 Rolling 算子族语义，QNT-25 §4.1；qlib 本身装不上 3.14，不作依赖），解析为 DuckDB 窗口函数或 numpy 算子；表达式字符串即因子定义，随结果一起存储（可解释、可 diff、可重放）。
- 指标预热期（unstable period）必须显式截断（QNT-25 §4.3）；推理期/训练期处理分离防前视泄漏（QNT-25 §4.1 ②）。
- 基准（写进 QNT-29 / QNT-30 验收，合成数据、单机 LXC 4 vCPU 口径，实现卡校准后允许 ±50% 内修订本节数字）：
  - 因子：1,000 标的 × 5 年日线（≈1.26M 行）× 20 因子，全量计算 **< 30 s**，增量一日 **< 2 s**。
  - 回测：同数据集单策略、日频再平衡，含手续费/滑点/资金费率，**< 10 s**；与 vectorbt 对拍差异在预先统一的成本模型下 equity curve 逐日相对误差 **< 1e-9**（浮点口径）。
  - 摄取：Vision 日 K 线 zip 1 个月 × 300 币对，解压+归一化+落盘 **< 60 s**。
  - API：行情看板单标的 5 年日 K 请求 p95 **< 200 ms**（DuckDB 直查 Parquet，无额外缓存层）。

## 6. Decision — 前后端边界

- 后端 FastAPI 单进程（`packages/api`），REST + OpenAPI 3.1；前端类型由 OpenAPI 生成（`openapi-typescript`），契约以 `docs/api/openapi.json` 快照入库并在 CI 比对。
- 后端**只读为主**：行情、因子值、回测报告、run 清单、资料索引均为 GET；唯一写入面：研报资料的元数据/标签/笔记（`library` router，append-only 事件表）与"发起回测 run"（POST 创建 run，结果异步落 `data/runs/`）。**不存在任何下单 POST**；paper 交易的订单意图由 `packages/execution` 写入 `data/runs/<run_id>/intents.parquet`，前端只展示。
- 前端 `apps/web`：Vite + React + TS；K 线与叠加指标用 Lightweight Charts；表格/面板自建轻组件，深色主题 token 化（`--bg-0..3`、`--fg-0..2`、`--up`、`--down`；色阶参考 TradingView Dark 与 Linear，不引入其资产）。
- 鉴权：第一阶段只监听 `127.0.0.1`，无用户体系；对外暴露不在本 ADR 范围（若需要另开 ADR，且不得引入公司基础设施 Bifrost 之外的新凭据类型）。

## 7. Decision — 多市场抽象（加密先实现，其他市场只留接口）

`packages/core` 定义四个 Protocol，加密（Binance 公开只读）是第一个实现；其余市场的实现类**不在第一阶段创建**（owner 2B），但**表结构现在就版本化**（QNT-26 §3.4 第 1 条）以免二期迁移：

- `Market`：`market_id`、`asset_classes`、`default_calendar_id`、`quote_currency_rules`。
- `Instrument`：以 `instrument_meta` 表（QNT-26 §3.2）为持久形态——`instrument_id` 稳定不复用；`effective_from/to` 版本区间；`multiplier` + `multiplier_unit`；`tick_size | tick_rule_ref`；`price_limit_kind/params`；`settlement_kind`；`exercise_style/expiry_rule`；`underlying_id`；`calendar_id`。加密第一版填 `market='crypto'`、`asset_class ∈ {spot, perp}`、`multiplier_unit='contracts'`、`price_limit_kind='none'`。
- `Calendar`：以 `trading_calendar` 会话表（QNT-26 §3.1）为持久形态——`calendar_id`（MIC 或 `CRYPTO_24_7`）、`session_date`、`session_seq`、`session_kind`、`open_utc/close_utc`、`local_tz`、`is_half_day`。加密为 24/7 单会话，但**仍落库**（资金费率结算时点 00/08/16 UTC 作为 `session_kind='funding'` 行），不用代码常量。`exchange_calendars`（Apache-2.0）只作二期初始化与交叉校验来源，会话行必须带 `source` 落库（可重放）。
- `DataSource`：`fetch(scope, range) -> RawBatch`、`normalize(RawBatch) -> Arrow table`、`capabilities()`；实现类必须声明 `hosts` 并通过 `execution/allowlist.py`（公共只读端点标 `public_readonly=true`，crypto-boundaries ②）。第一实现 `BinancePublicSource`：`data.binance.vision` 归档 + `data-api.binance.vision` 无 key 镜像；**不使用** `api.binance.com` 主 host（美国节点 451，QNT-24 §0）。
- 复权 / 拼接：`adjust_factor` 表（QNT-26 §3.3）带 `adjust_kind`、`factor_kind`、`direction`、`disclosure_date`；**只存因子不存复权价**。加密第一版此表为空但 schema 已定。

## 8. Decision — paper 交易模块边界（任务描述"实盘交易"的降级）

- 模块名、包名、UI 文案统一为 **paper 交易**；仓库内不存在实盘下单端点调用（ADR-0001 D1.3）。
- 凭据：只允许 ADR-0001 D1.6 枚举的 testnet/demo key，来自 vault `quant-dev`，`op read` 注入；host 必须 ∈ D1.7 allowlist，启动断言 fail-closed。
- 实盘路径唯一形态：`intents.parquet`（append-only）+ 前端"待人工确认"只读列表；确认与执行发生在 agent 不可达环境（owner 手动）。
- 多账户 / 多策略并行 / 风控限额 / 告警按 QNT-33 验收；风控事件 append-only 记 `risk_events`。

## 9. 未决项与冲突（任务描述 vs ADR/AGENTS.md；只列不裁）

1. **市场范围**：任务描述要求 A股/国内期货/公募基金/港股/美股/数字货币（CEX、DEX、现货、合约）全做；AGENTS.md §1 与 owner 2B 限定"美股 + 美股期权 + 加密"，其他只留接口，DEX 不做（6A）。→ 本 ADR 按 2B/6A 执行；范围扩展需修订 AGENTS.md §1 与本 ADR。
2. **"实盘交易"模块**：与 ADR-0001 D1.1/D1.3 冲突 → 降级为 paper 交易（§8，owner 1A）。
3. **Python 3.14.5**：补丁号存在性未验证（矛盾 #21）→ 写 `>=3.14`。
4. **ADR-0002 未决项第 2 条（batch 乱序提交）**：本 ADR §4.2 用"manifest 记录精确文件清单 + sha"代替 `batch_id ≤ N` 水位，属于对 D2.7 的**收紧实现**而非修改决策；是否将此写回 ADR-0002 修订，待 owner 裁决。
5. **Binance 主 host 451**：任务描述以 Binance 为示例，但美国节点 `api.binance.com`/`fapi.binance.com` 不可达（QNT-5/QNT-24）；第一版数据源改用 `data.binance.vision` 归档 + `data-api.binance.vision` 镜像（现货）。**U 本位永续 REST 无无 key 镜像**，永续数据第一版只有 Vision 归档（funding/metrics 月文件，延迟 T+1）→ 行情看板的"实时"永续行情第一阶段不可达，待 owner 决定是否接受 T+1 或另选源。
6. **vectorbt 许可**：Apache-2.0 + Commons Clause（QNT-25 §7.2）；作为**对拍参照的开发依赖**（不随产品分发）内部研究可用；若 quantime 未来商业化需 owner 裁决是否换 bt（MIT）为首选。
7. **研报资料模块**：任务描述隐含抓取研报全文；owner 4A 限定为"元数据 + 链接 + 用户自有文件索引"（§6 `library` router）。
8. **公司行为与期权调整数据源**：美股期权 OCC 调整、分红拆股因子的免费公开源许可尚未逐一核到一手原文（QNT-26 §4）；`adjust_factor` schema 已定但美股填充源待 Stage 3 调研卡。
9. **ADR-0001 未决项**（D1.8 transfer 权限、Bybit demo 公共行情主网 host、D1.9 合规表述）仍未闭合；本 ADR §7 的 `public_readonly=true` allowlist 条目是对第 2 条的架构侧回应，法律/政策项不在本文范围。

## 10. Consequences / Revisit trigger

+ 单机零外部服务、全部状态在 Parquet + 仓库 SQL 里可重建；任何 run 由 manifest 精确重放；模块依赖单向，对拍只需替换引擎。
− Parquet 多版本存储放大；DuckDB 每次冷启需注册视图；无消息队列意味着摄取与回测都是 systemd timer 驱动的批处理，无实时流。
需新增（对应实现卡）：QNT-27 骨架 + 数据层基础 + import-linter + CI；QNT-28 Binance 公开摄取；QNT-29 因子 DSL 与评估；QNT-30 回测/组合/对拍（`hard`）；QNT-31 API + 前端骨架；QNT-32 研报索引；QNT-33 paper 交易（`hard`）。

Revisit：单表（单 lake 前缀）> 50 GB 或视图 p95 > 5 s；需要分钟级实时行情；出现第二个写入者（多进程摄取）；owner 决定扩展市场范围或进入实盘；polars/numba 需成为基线依赖。

## Alternatives considered

- Postgres/TimescaleDB 作业务库：第一阶段单写者、日线为主，Parquet + DuckDB 满足 ADR-0002 且零运维；估算 TB 级 Postgres（ADR-0002 修订）不值。REJECT（Revisit 见 §10）。
- 事件驱动回测（nautilus/zipline 风格）作第一版：语义最完整但工程量与我方"日线 + 向量化对拍"目标不匹配；zipline-reloaded 的 `finance/` 分层作**语义参考**（QNT-25 §5.3），引擎本体向量化。REJECT 作为第一版。
- 直接依赖 qlib 因子引擎：PyPI 无 3.13/3.14 安装路径（QNT-25 §4.1）。REJECT，只借鉴 DSL 语义。
- 每市场一套 schema：`multiplier_unit` / `price_limit_kind` / `adjust_kind` 三列即可让五类市场共表（QNT-26 §3.2/3.3），二期避免迁移。REJECT 分表。
