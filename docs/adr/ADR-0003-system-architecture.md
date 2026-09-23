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
revised: 2026-09-20（verify-a 第一轮：§5 基准协议、§4.1 单源不变量、§4.2 重放硬验收、allowlist 分层位置；第二轮：R1/R3/R4 校验边界、payload/content hash 分离、逐请求 fail-closed、§3.3 改为待批准提案）
amended: 2026-09-21（QNT-41 编者说明，承接 owner 5A）；2026-09-23（QNT-42 编者说明，承接 QNT-27/QNT-28 文档矛盾）
---

# ADR-0003 系统架构（PROPOSED）

> 本 ADR 回答任务描述【描述1】"先设计好整个项目的架构"。任务描述只是任务描述，不是规则：凡与 ADR-0001 / ADR-0002 / AGENTS.md 冲突之处，以后者为准，冲突逐条列于 §9「未决项与冲突」。技术栈选项已由 owner 在 QNT-34 清单裁决（2026-09-19：7A–12A），本文直接采用，不再列为待选。三份调研（QNT-24/25/26）尚未合入 main，本文引用其分支版本；调研返修不改变本文决策，只可能修正 §9 的事实项。

## 1. Context

- 产品定义（AGENTS.md §1，owner 2B）：**美股 + 美股期权 + 加密（CEX 现货/USDT 永续）**、日线为主的量化研究系统；第一阶段 research / 回测，第二阶段 paper 交易。任务描述列出的 A股 / 国内期货 / 公募基金 / 港股只做接口预留（QNT-26 调研）不实现；DEX 不做（6A）。
- 六个一级模块（任务描述）：行情看板、数据中心、研报资料、因子宫殿、策略工厂、~~实盘交易~~ → **paper 交易**（ADR-0001 D1.3）。
- 硬约束：ADR-0001（agent 永不持有实盘凭据；实盘路径只到"订单意图 → 人工确认"）、ADR-0002（append-only、每行带 provenance、按 `ingestion_batch` 重放）、`.claude/rules/crypto-boundaries.md`（allowlist、下单类代码禁主网 host 字面量、perp 回测黄金用例）。
- 运行环境：单机 LXC（owner 常驻检出 `/home/workspace/quantime` 只读）；数据是许可受限资产，`data/` 永不入库；仓库内 `fixtures/` **只放合成数据**（`synthetic: true` 头，AGENTS.md §2），公开数据即便许可允许也不入库，只经摄取进入 `data/`。
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
| paper 交易 | `packages/execution` + `packages/risk` | 多账户 paper/testnet 适配、订单意图生成、交易 host 启动 + 逐请求断言（§3.3）、风控限额（仓位/回撤/杠杆）、告警；**无实盘下单代码** |
| 行情看板 / 研报资料（后端） | `packages/api` | FastAPI 应用：行情/因子/回测/资料索引只读 API；写操作仅限研报元数据与用户笔记 |
| 行情看板 / 研报资料（前端） | `apps/web` | React 单页：K 线（Lightweight Charts）、因子面板、回测报告、资料索引与检索 |
| 横切 | `packages/core` | `Market` / `Instrument` / `Calendar` / `DataSource` 抽象、Parquet 路径规范、`run_id`/`batch_id` 生成、**host allowlist 数据与校验函数**（§3.3）、配置与 `op` 注入读取、日志 |

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
  core/       quantime_core/       {markets.py, instruments.py, calendar.py, datasource.py, paths.py, ids.py, config.py,
                                    allowlist.py}   # allowlist：host 表 + 校验函数（§3.3 提案，批准后才建）
  data/       quantime_data/       {sources/{base.py, binance_public.py}, ingest.py, batches.py, checks.py, views.py}
  factors/    quantime_factors/    {expr/{parser.py, ops.py}, compute.py, evaluate.py, registry.py}
  backtest/   quantime_backtest/   {engine.py, costs.py, funding.py, lookahead.py, report.py, crosscheck/{vectorbt_ref.py, bt_ref.py}}
  portfolio/  quantime_portfolio/  {equal.py, risk_parity.py, mean_variance.py}
  execution/  quantime_execution/  {startup.py, intents.py, paper/{base.py, binance_testnet.py}}   # startup：启动断言；paper/base.py：PaperTransport 逐请求断言（§3.3）
  risk/       quantime_risk/       {limits.py, monitor.py, alerts.py}
  api/        quantime_api/        {main.py, routers/{market.py, factors.py, backtests.py, library.py}}
apps/web/                          # React + TS, Vite, Lightweight Charts
fixtures/                          # 仅合成数据，文件头 synthetic: true
data/                              # gitignored；见 §4 分区
docs/{adr,research,ops}
systemd/                           # unit 模板（*.tpl），值由 op 注入
```

> 编者说明（QNT-41，2026-09-21）：§3.3 已获 owner 2026-09-21 批准（5A），`allowlist.py` 随 QNT-27 创建。

命名规则：Python 包名前缀 `quantime_`；每个 package 独立 `pyproject.toml`，互相依赖只允许**向下**（`api → {factors,backtest,portfolio,execution,risk,data} → core`；`execution/risk` 不得 import `backtest`；`data` 不得 import 任何上层）。依赖方向由 CI 的 import-linter 规则守卫（实现卡 QNT-27）。

### 3.3 host allowlist 的装配位置（**迁移提案，批准前不实施**）

现行规则 crypto-boundaries ① 写的是 `execution/allowlist.py`，但 §3 分层要求 `data`（摄取入口）不得 import `execution`。两者冲突。本节是**提案**：本 ADR 为 PROPOSED，不能覆盖现行 rules（AGENTS.md §1：草案不是许可）；在 owner 批准 §9.10 之前，crypto-boundaries ①② 原文继续有效，任何实现卡不得按本节建 `core/allowlist.py`。批准后，迁移由 QNT-27 在**同一个 PR** 内完成两件事：建 `core/allowlist.py` + 回写 `.claude/rules/crypto-boundaries.md` ① 的路径与 ② 的字段名，使 rules 与代码同刻一致。

> 编者说明（QNT-41，2026-09-21）：owner 已于 2026-09-21 裁决 5A 批准本迁移；'批准前不实施'状态已解除。rules 回写由 QNT-39（PR #9）独立完成，`core/allowlist.py` 文件由 QNT-27 随骨架创建，两者非同一 PR；此为对本节'由 QNT-27 在同一个 PR 内完成两件事'的实施方式变更，边界语义不变。

提案内容：
- `packages/core/allowlist.py` 只含纯数据 + 纯函数，无网络、无凭据读取：`ALLOWLIST: tuple[HostEntry, ...]`，`HostEntry(host, public_readonly: bool, exchange, doc_url, demo_marker: DemoMarker | None)`。字段名**沿用 rules 原文 `public_readonly=true/false`**（不引入 `kind` 枚举，避免迁移时两套口径）；`public_readonly=False` 的条目即 ADR-0001 D1.7 交易 host 集合。`assert_trading_host(host)` 只放行 `public_readonly=False` 条目；`assert_public_readonly_host(host)` 只放行 `public_readonly=True` 条目；两者互不放行。

> 编者说明（QNT-41，2026-09-21）：§3.3 正文的 `packages/core/allowlist.py` 为简写，实际完整路径为 §3.2 骨架所示 `packages/core/quantime_core/allowlist.py`（QNT-39 rules 回写与 QNT-27 实现均按完整路径）
- `execution` 侧的 fail-closed 分两层，**启动检查不是请求边界**：
  - 启动层 `execution/startup.py`：对所有配置的交易 host 调 `assert_trading_host`，任一失败即退出（D1.7）。
  - **请求层** `execution/paper/base.py`：所有交易/账户/资金类 HTTP 与 WS 连接必须经唯一出口 `PaperTransport.send(request)`，该出口对**每个请求**重新执行 `assert_trading_host(request.host)`，并按条目的 `demo_marker` 逐请求校验：OKX 条目要求请求头 `x-simulated-trading: 1` **且** 注入的 key 标签含 `demo`（标签由 `op` 注入的字段读取，`.strip()` 后比较）；Bitget 条目要求 `paptrading: 1`。头缺失/值错误/标签不符任一不满足 → 抛 `TradingBoundaryError`，请求**不发出**（D1.7 "缺一 fail-closed" 的逐请求形态）。CI 规则：`packages/execution/**` 内除 `PaperTransport` 外不得直接 import `httpx`/`websockets`（import-linter），确保没有绕过出口的第二条路径。变异验收：删掉 OKX 头或改 key 标签，对应测试必须由绿变红。
  - 第一阶段实现范围：`BinancePaperTransport`（testnet host 无 demo 头需求）；OKX/Bitget 适配器**不在第一阶段创建**，但 `demo_marker` 字段与请求层校验逻辑现在就实现并用假 host 条目测试，以免二期补边界。
- `data/sources/base.py`：`DataSource` 实现类声明 `hosts: tuple[str, ...]`，基类 `__init__` 对每个 host 调 `assert_public_readonly_host`，且 `DataSource` 唯一 HTTP 出口 `PublicTransport.get(url)` 逐请求再次校验 host（对称于交易侧）；因此 `data.binance.vision` / `data-api.binance.vision` 必须以 `public_readonly=True` 进入 `ALLOWLIST`（crypto-boundaries ② 公共只读例外、ADR-0001 D1.8）。
- CI grep（crypto-boundaries ②）范围不变：`packages/execution/**`、`packages/risk/**` 及任何持凭据模块禁止主网 host 字面量；`core/allowlist.py` 是**唯一**允许出现 `public_readonly=True` host 字面量的文件，且该文件本身不得 import 任何网络客户端（import-linter 规则）。

> 编者说明（QNT-42，2026-09-23）：crypto-boundaries ② 写 CI grep 范围限定 `execution`/`risk`/持凭据模块（本阶段不存在）。现行 CI（QNT-27 PR #11，`.github/workflows/ci.yml`）范围为整个 `packages/` 非测试代码，严于原文。rules 原文已由 QNT-39 处理，本条不重复改、不改决策。

## 4. Decision — 数据层：Parquet 分区 + DuckDB 视图 + append-only 落地

### 4.1 目录规范（承接任务描述【描述2】，与 ADR-0002 D2.6/D2.7 对齐）

```
data/
  raw/<source>/<batch_id>/...                         # 原始响应 JSONL/zip，按 batch 不可变（D2.6）
  lake/<market>/<asset_class>/<datatype>/<freq>/<symbol_or_universe>/
       source=<source>/batch=<batch_id>/part-0000.parquet   # 归一化数据；一个 batch 只写新文件，永不改旧文件
  meta/{trading_calendar,instrument_meta,adjust_factor,source_conflict}/
       source=<source>/batch=<batch_id>/part-0000.parquet
  meta/ingestion_batch/batch=<batch_id>/part-0000.parquet   # 唯一无 source 分区的表：它本身是 source→文件清单
  runs/<run_id>/{manifest.json, results/*.parquet}    # 回测/研究 run 产物（D2.4 data_snapshot 落在 manifest）
```

- 路径分量取值受 `packages/core/paths.py` 的枚举约束：`market ∈ {crypto, us, cn, hk}`；`asset_class ∈ {spot, perp, delivery, equity, etf, option, future, fund}`；`datatype ∈ {kline, trade, agg_trade, funding, open_interest, mark_price, book_depth, nav, dividend, corp_action}`；`freq ∈ {1m, 5m, 15m, 1h, 4h, 1d, 1w, 1mo, tick, event}`。**周期命名统一用 Vision 文件名口径 `1mo`，不用 REST 的 `1M`**（QNT-24 矛盾项，避免大小写歧义）。

> 编者说明（QNT-42，2026-09-23）：§4.1 `freq` 含 `tick`/`event`，与 `datatype` 的合法组合未定义。现行实现（QNT-27 PR #11）只落枚举、不做交叉约束。交叉约束待后续卡，本条不新增决策。
- 每个 Parquet 行必带 ADR-0002 列：`source, source_version, ingested_at, run_id, batch_id`。
- **单源不变量（承接 ADR-0002 D2.5）**：一个 `batch_id` 只属于一个 `source`；一个 Parquet 文件内所有行的 `source` 列必须等于其路径的 `source=` 分量（写入侧断言，`checks.py` 抽样复核）。`raw/<source>/<batch_id>/` 天然单源。因此许可驱动的删除 = `rm -r data/raw/<source>/ data/lake/**/source=<source>/ data/meta/**/source=<source>/` + 在 `ingestion_batch` 追加 `tombstone` 行（`kind='license_drop'`，仍 append-only），逐行重写永不发生；执行前须 owner 确认并记 ADR 修订（D2.5 不变）。`source_conflict` 表按**写入方 source** 分区（冲突记录归属于发现冲突的那次摄取），删源时随之整体删除。
- source→文件清单：`SELECT source, manifest_path FROM ingestion_batch WHERE source = ?` 即得该源全部文件（每个 batch 的 `manifest_path` 列出其所有 `part-*.parquet` 与 raw 文件及 sha）；删除前用它核对实际删除范围，删除后视图因 join 不到 `ingestion_batch` 有效行而自动不再暴露该源。
- 只 insert 的落地方式：**新 batch = 新目录**；重跑同一区间写新 `batch_id`，`source_version` 不变、附 `rerun_of=<batch_id>`；"当前视图"由 DuckDB 视图 `latest_per_source` 按 `(natural key, source)` 取最大 `batch_id`。
- 上游归档（Vision zip）**可被替换**（QNT-24 verify-b 指正）：重放只依赖本地 `raw/` 副本与 `ingestion_batch.content_sha256`，永不把上游 URL 当作快照。

### 4.2 DuckDB 的角色

- 单文件 `data/quantime.duckdb` 只存**视图定义与宏**（可从仓库内 SQL 重建，`packages/data/views.py` 幂等注册）；不存业务行。丢掉该文件不丢数据。
- 查询经 `read_parquet('data/lake/.../batch=*/**.parquet', hive_partitioning=true)`；复权价、连续合约等**派生价在视图层合成**，不落盘（QNT-26 §3.4 第 3 条）。
- 重放：run 的 `manifest.json` 记录 `{tables: {name: {batch_ids: [...], files: [{path, sha256, size}]}}, config_hash, git_commit, result_sha256}`；重放读 manifest 的**精确文件清单**而非 `batch_id ≤ N`（回应 ADR-0002 未决项第 2 条，见 §9.4）。`batch_ids` 只能包含 run 开始时刻 `ingestion_batch` 中**已提交**的 batch（§4.3 提交顺序保证"已提交 ⇒ 文件完整且 sha 已知"）。

> 编者说明（QNT-42，2026-09-23）：§4.2 未规定 `build_manifest` 的取证来源。现行实现（QNT-27 PR #11）：只从提交时固定的 batch 清单取证，目录只用于核对。本条不改 R1「恰好等于」语义。

**重放硬验收（写进 QNT-27 验收，verify 须复现 + 变异）**：
校验边界（R1/R3/R4 的统一口径）：**校验单位是 manifest 内每个 `batch_id` 的目录 `.../source=<s>/batch=<batch_id>/`**。对清单内的每个 batch 目录，实际文件集合必须**恰好等于** manifest 登记的集合（不缺、不多、sha/size 一致）——batch 目录在提交后不可变（§4.3），所以任何多出的文件都是变异而非合法数据。清单外的 batch 目录（含 R3 的晚到 batch、run 之后的正常新摄取）**不扫描、不校验、不读取**。因此"多出文件"只在 batch 目录粒度判定，永不会把晚到 batch 误判为变异。

- R1 **hash 校验强制**：`replay(run_id)` 在读任何数据前，对 manifest 内每个 batch 目录执行上述"恰好等于"校验；任一 batch 目录缺文件、sha/size 不符、或**目录内**多出未登记文件 → 抛 `ReplayIntegrityError` 并**拒绝重放**，不降级、不跳过。DuckDB 读取用显式文件列表 `read_parquet([...])`，不用 glob，保证清单外文件在读取层也物理不可达。
- R2 **逐字节一致（D2.4）**：重放产出的 `results/*.parquet` 的 `sha256` 必须等于 manifest 的 `result_sha256`；写 Parquet 时固定 writer 参数（行组大小、压缩、无 statistics 时间戳、列顺序）并在 `packages/core/parquet_io.py` 集中，确保 determinism。

> 编者说明（QNT-42，2026-09-23）：§4.2 未规定 run 清单/结果文件的可覆盖性。现行实现（QNT-27 PR #11，`write_manifest` / 结果发布）：同 `run_id` 二次写入拒绝，原字节不变。
- R3 **晚到/乱序提交不影响旧 run**：测试固定序列——batch 1 开始、batch 2 开始并提交、run R 在此时刻建 manifest（只含 batch 2）、batch 1 之后提交（其目录 `batch=<1>/` 与 batch 2 同分区）；`replay(R)` **通过校验**（batch 1 目录在清单外，不扫描）、结果与首跑逐字节一致且不含 batch 1 的行。
- R4 **源文件变异被拒绝**：测试对 manifest 中任一 Parquet 翻转一个字节 / 删除一个文件 / **在清单内某个 `batch=<id>/` 目录下**新增一个未登记 `part-0001.parquet`，三种情形 `replay(R)` 均抛 `ReplayIntegrityError`（不是静默得到不同结果）。R3 与 R4 的区别只在文件落在清单内 batch 目录（拒绝）还是清单外 batch 目录（忽略）。
- R5 **`ingestion_batch` 自身也在清单内**：manifest 记录 run 所依赖的 `ingestion_batch` 文件与 sha，防止用改写的 batch 表"合法化"未登记文件。

### 4.3 `ingestion_batch` 表（ADR-0002 D2.7 落地）

`batch_id`（ULID，单调）、`source`（单值，§4.1 单源不变量）、`source_version`、`market/asset_class/datatype/freq/scope`、`range_start/range_end`、`row_count`、`content_sha256`（归一化 Parquet 的 sha）、`raw_sha256`（raw 文件 sha）、`manifest_path`（该 batch 的文件级清单：每个 part 与 raw 文件的 path/sha256/size）、`committed_at`、`rerun_of`、`run_id`、`kind ∈ {ingest, rerun, license_drop}`。写入顺序：先落 raw → 写归一化 Parquet 到临时名（`.tmp-<batch_id>`，位于最终目录外的 `data/_staging/`）→ 计算 sha → rename 到最终路径 → 最后 insert `ingestion_batch` 行；**未出现在 `ingestion_batch` 的文件视为不存在**（视图只 join 已提交 batch；§4.2 R1 保证 run 层面也读不到）。

> 编者说明（QNT-42，2026-09-23）：§4.3 未定义 `manifest_path` 的路径规范。现行实现（QNT-27 PR #11，`quantime_data.batches.batch_manifest_path`）取 `data/meta/batch_manifest/<batch_id>.json`。本条只记录路径，不改字段语义。

> 编者说明（QNT-42，2026-09-23）：§4.3 未规定 batch 全局唯一性的判定时点与介质。现行实现（QNT-27 PR #11）：manifest 侧 `.lock` 独占创建（`data/meta/batch_manifest/<batch_id>.json.lock`，任何落盘之前）+ 所有最终文件不存在才发布；`ingestion_batch` 行不是唯一性判据。

> 编者说明（QNT-42，2026-09-23）：§4.3 写入顺序表缺「取锁/唯一性登记」一步。现行顺序（QNT-27 PR #11）为「唯一性登记 → 临时名（`data/_staging/`）→ sha → 原子发布 → insert 行」。本条只记录现行顺序，不改 Decision。

> 编者说明（QNT-42，2026-09-23）：§4.3「临时名 → sha → rename」未规定临时文件必须位于所有读侧枚举目录之外、发布必须单次不可覆盖。现行实现（QNT-27 PR #11）：临时文件位于 `data/_staging/`，发布为 `os.link` 单次不可覆盖原子操作。

## 5. Decision — 性能策略与可量化验收

- 热路径（因子计算、回测撮合、绩效统计）只允许 DuckDB SQL、numpy 数组、可选 polars；禁止 Python 行级循环与 pandas `apply`。
- 因子用**字符串表达式 DSL**（借鉴 qlib `ops.py` 的 Rolling 算子族语义，QNT-25 §4.1；qlib 本身装不上 3.14，不作依赖），解析为 DuckDB 窗口函数或 numpy 算子；表达式字符串即因子定义，随结果一起存储（可解释、可 diff、可重放）。
- 指标预热期（unstable period）必须显式截断（QNT-25 §4.3）；推理期/训练期处理分离防前视泄漏（QNT-25 §4.1 ②）。
### 5.1 基准协议（固定输入 + 固定测量；写进 QNT-27/28/29/30/31 验收）

**基准输入（`fixtures/bench/` 由 QNT-27 落地，生成脚本入库，生成物不入库）**
- 合成数据：`bench_gen.py --seed 20260920 --symbols 1000 --days 1260 --start 2021-01-04`，几何布朗运动日 K（`mu=0, sigma=0.02/√252`，`open=prev_close`，`high/low = close·(1±|N(0,0.01)|)`，`volume ~ LogNormal(12, 1)`），`freq=1d`，`market=crypto/asset_class=spot`，按 `CRYPTO_24_7` 日历取**连续 1,260 个自然日**（2021-01-04 → 2024-06-16，约 3.45 年；本文一律以"1,260 日"计，不再称"5 年"）。
- **两个 hash 分离**：(a) `payload_sha256` = 生成器输出的**纯业务列** Arrow 表（`symbol, ts, open, high, low, close, volume`，固定列序与 dtype，用 `packages/core/parquet_io.py` 的确定性 writer 序列化）的 sha256，**不含** ADR-0002 provenance 列；该值由 `bench_gen.py` 打印，是所有实现必须一致的"基准输入指纹"，并作为常量写进 `fixtures/bench/EXPECTED.json` 由测试断言。(b) 随后 payload 经 §4.3 正常摄取流程写为 1 个 batch（`source='synthetic_bench'`，`source_version=<seed>`），得到的 `ingestion_batch.content_sha256` 含 `ingested_at/run_id/batch_id`，**每次运行不同，只记录不比较**；报告同时贴 (a) 与 (b)，验收只断言 (a) 相等。D2.2 provenance 列不做任何特殊化。

> 编者说明（QNT-42，2026-09-23）：ADR-0002 D2.2 的 `source` 枚举不含 `synthetic_bench`，与本节 `source='synthetic_bench'` 冲突。现行实现（QNT-27 PR #11，`quantime_core.paths.assert_source`）只校验小写 snake 格式、不硬编码枚举。枚举是否扩展属决策内容，待 owner 裁决；本卡不改 ADR-0002。

> 编者说明（QNT-42，2026-09-23）：§5.1 未规定基准输入的跨机器复现边界。已由 QNT-40（PR #13，`0fdf657`）承接：复现边界为**任意机器**（任意 x86-64 GitHub runner 与本地 LXC）逐位相等，而非仅同机两次；现行实现通过 `quantime_core.detmath.exp` 避开 CPU 分派达成；`payload_sha256` 比较为精确相等、未放宽。已证实的漂移源只有 close 路径的 `np.exp`（生成第 7 步）；`rng.lognormal`（volume）替换属防御措施，不是第二个已复现漂移源。CI `bench-repro` 矩阵是本轮证据来源（日志覆盖含原生 AVX-512 的 4 种 CPU），hosted runner 标签不保证未来每轮硬件覆盖。
- 固定 20 因子（表达式 DSL，QNT-29 按此清单实现，不许替换）：`ret_1, ret_5, ret_20, ma_5/close-1, ma_20/close-1, ma_60/close-1, std_20(ret_1), std_60(ret_1), max_20(high)/close-1, min_20(low)/close-1, rsi_14, ts_rank_20(close), corr_20(close, volume), skew_20(ret_1), kurt_20(ret_1), vol_ratio_5_20, amihud_20, macd_12_26_9, bb_pos_20_2, mom_reversal_20_5`（定义写在 `fixtures/bench/factors.yaml`，随 ADR 修订）。
- 固定策略与成本（QNT-30）：每日 `ts_rank_20(close)` 截面 top 10% 等权多头，日频再平衡，全仓；手续费 `10 bp` 单边、滑点 `5 bp` 固定比例、资金费率 `0`（现货基准；perp 黄金用例另计，crypto-boundaries ③）；初始资金 `1e6`。
- 摄取基准输入：合成 Vision 风格 zip（同 seed，`300 币对 × 1 个月日 K`，CSV 列序与 Vision 一致），由 `bench_gen.py --mode vision-zip` 生成，不走网络。
- API 基准：单标的 1,260 日 K（1,260 行）`GET /market/klines?symbol=...&freq=1d`，**1 个并发**，预热 20 次后测 200 次，取 p95；`uvicorn` 单 worker。

**测量协议**
- 机器口径：`4 vCPU / 8 GB RAM` 的 LXC，`DUCKDB_THREADS=4`、`OMP_NUM_THREADS=4`、`POLARS_MAX_THREADS=4`，单进程；基准脚本在开头打印 `os.cpu_count()`、`duckdb.execute("select current_setting('threads')")`、内存上限，并写入报告。
- **冷缓存**：每次计时前 `sync; echo 3 > /proc/sys/vm/drop_caches`（需 root 时改为：新进程 + 读取一份未被读过的 fixtures 副本，并在报告注明"warm-fs"）；DuckDB 每次新建连接（无对象缓存）。
- 计时边界：`time.perf_counter()` 包住"读 Parquet → 计算 → 写结果 Parquet 到 `data/runs/<run_id>/`"全程，**不含**进程启动与 import；增量一日 = 已有 1,259 日结果的前提下新增 1 日并落盘。
- 重复：**5 次取中位数**，同时报告 min/max；中位数达标即通过；报告格式固定为 `bench_report.json`（`{name, median_s, min_s, max_s, threads, mem_mb, payload_sha256, content_sha256, git_commit}`），贴进 PR 描述。
- 对拍精度：equity curve 逐日相对误差 `|a-b| / max(|b|, 1e-12) < 1e-9`，参照实现用 vectorbt 在**同一成本模型、同一权重序列**下计算（成本模型的 vectorbt 参数映射写入 `crosscheck/vectorbt_ref.py` 并在报告列出）。

### 5.2 阈值（中位数口径）

| 基准 | 阈值 | 归属卡 |
|---|---|---|
| 因子全量：1,000 标的 × 1,260 日 × 20 因子 | **< 30 s** | QNT-29 |
| 因子增量一日 | **< 2 s** | QNT-29 |
| 回测：固定策略 + 成本，1,000 × 1,260 | **< 10 s** | QNT-30 |
| 回测对拍 vs vectorbt | 逐日相对误差 **< 1e-9** | QNT-30 |
| 摄取：300 币对 × 1 月合成 Vision zip，解压+归一化+落盘（含 sha） | **< 60 s** | QNT-28 |
| API：单标的 1,260 日 K，1 并发 p95 | **< 200 ms** | QNT-31 |

**阈值修订规则**：实现卡不得自行放宽。若实测中位数超阈值，实现卡在四段式"偏离项"里贴 `bench_report.json` 与 profile（DuckDB `EXPLAIN ANALYZE` 或 `py-spy` 火焰图文字摘要），由 planner 提 ADR-0003 修订 PR，**owner 批准**后阈值才生效；单次修订上限 ±50%，累计放宽超过 2× 原值必须重议实现方案而非改数字。收紧阈值同样走修订，但不需 owner 批准（planner 可提，verify 复核）。

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
- `DataSource`（Protocol 定义在 `core/datasource.py`，实现在 `data/sources/`）：`fetch(scope, range) -> RawBatch`、`normalize(RawBatch) -> Arrow table`、`capabilities()`；实现类必须声明 `hosts` 并通过 `assert_public_readonly_host`（物理位置按 §3.3 提案 / §9.10 裁决；条目 `public_readonly=True`，crypto-boundaries ②、ADR-0001 D1.8），**不依赖 `execution`**。第一实现 `BinancePublicSource`：`data.binance.vision` 归档 + `data-api.binance.vision` 无 key 镜像；**不使用** `api.binance.com` 主 host（美国节点 451，QNT-24 §0）。
- 复权 / 拼接：`adjust_factor` 表（QNT-26 §3.3）带 `adjust_kind`、`factor_kind`、`direction`、`disclosure_date`；**只存因子不存复权价**。加密第一版此表为空但 schema 已定。

## 8. Decision — paper 交易模块边界（任务描述"实盘交易"的降级）

- 模块名、包名、UI 文案统一为 **paper 交易**；仓库内不存在实盘下单端点调用（ADR-0001 D1.3）。
- 凭据：只允许 ADR-0001 D1.6 枚举的 testnet/demo key，来自 vault `quant-dev`，`op read` 注入；host 必须 ∈ D1.7 allowlist（`public_readonly=False` 条目），启动断言 + **逐请求**断言双层 fail-closed（§3.3）；OKX/Bitget 的模拟头与 key 标签逐请求校验，第一阶段不创建其适配器。
- 实盘路径唯一形态：`intents.parquet`（append-only）+ 前端"待人工确认"只读列表；确认与执行发生在 agent 不可达环境（owner 手动）。
- 多账户 / 多策略并行 / 风控限额 / 告警按 QNT-33 验收；风控事件 append-only 记 `risk_events`。

## 9. 未决项与冲突（任务描述 vs ADR/AGENTS.md；只列不裁）

1. **市场范围**：任务描述要求 A股/国内期货/公募基金/港股/美股/数字货币（CEX、DEX、现货、合约）全做；AGENTS.md §1 与 owner 2B 限定"美股 + 美股期权 + 加密"，其他只留接口，DEX 不做（6A）。→ 本 ADR 按 2B/6A 执行；范围扩展需修订 AGENTS.md §1 与本 ADR。
2. **"实盘交易"模块**：与 ADR-0001 D1.1/D1.3 冲突 → 降级为 paper 交易（§8，owner 1A）。
3. **Python 3.14.5**：补丁号存在性未验证（矛盾 #21）→ 写 `>=3.14`。
4. **ADR-0002 未决项第 2 条（batch 乱序提交）**：本 ADR §4.2 用"manifest 记录精确文件清单 + sha，重放强制校验（R1–R5）"代替 `batch_id ≤ N` 水位，属于对 D2.7 的**收紧实现**而非修改决策；是否将此写回 ADR-0002 修订（同时把 D2.4 的 `max(ingested_at)` 措辞改为 manifest 文件清单），待 owner 裁决。
5. **Binance 主 host 451**：任务描述以 Binance 为示例，但美国节点 `api.binance.com`/`fapi.binance.com` 不可达（QNT-5/QNT-24）；第一版数据源改用 `data.binance.vision` 归档 + `data-api.binance.vision` 镜像（现货）。**U 本位永续 REST 无无 key 镜像**，永续数据第一版只有 Vision 归档（funding/metrics 月文件，延迟 T+1）→ 行情看板的"实时"永续行情第一阶段不可达，待 owner 决定是否接受 T+1 或另选源。
6. **vectorbt 许可**：Apache-2.0 + Commons Clause（QNT-25 §7.2）；作为**对拍参照的开发依赖**（不随产品分发）内部研究可用；若 quantime 未来商业化需 owner 裁决是否换 bt（MIT）为首选。
7. **研报资料模块**：任务描述隐含抓取研报全文；owner 4A 限定为"元数据 + 链接 + 用户自有文件索引"（§6 `library` router）。
8. **公司行为与期权调整数据源**：美股期权 OCC 调整、分红拆股因子的免费公开源许可尚未逐一核到一手原文（QNT-26 §4）；`adjust_factor` schema 已定但美股填充源待 Stage 3 调研卡。
9. **ADR-0001 未决项**（D1.8 transfer 权限、Bybit demo 公共行情主网 host、D1.9 合规表述）仍未闭合；本 ADR §3.3 的 `public_readonly=True` allowlist 条目是对第 2 条的架构侧回应，法律/政策项不在本文范围。
10. **crypto-boundaries ① 路径迁移（待批准，批准前不实施）**：rules 文件写 `execution/allowlist.py`，本 ADR §3.3 提案放到 `core/allowlist.py`（否则 `data` 必须 import `execution`，违反 §3 分层）。语义（单一 allowlist、附官方文档链接、`public_readonly=true` 例外、字段名）不变，仅物理位置不同。owner 批准后由 QNT-27 在同一 PR 内建文件 + 回写 rules ①；未批准则 QNT-27 退回把 allowlist 建在 `execution/`，并让 `data` 通过 `core` 里的一个 Protocol 注入校验函数（绕开 import 方向），边界不变但多一层装配。

> 编者说明（QNT-41，2026-09-21）：owner 已于 2026-09-21 裁决 5A 批准本迁移；'批准前不实施'状态已解除。rules 回写由 QNT-39（PR #9）独立完成，`core/allowlist.py` 文件由 QNT-27 随骨架创建，两者非同一 PR；此为对本节'由 QNT-27 在同一个 PR 内完成两件事'的实施方式变更，边界语义不变。
13. **ADR-0001 D1.7 OKX/Bitget 请求头校验层次**：D1.7 写"校验请求头"，未写在哪一层；本 ADR §3.3 明确为逐请求 fail-closed，并将 OKX/Bitget 适配器推到二期（第一阶段只有 Binance testnet transport）。是否回写 D1.7 措辞待 owner。
11. **fixtures 数据口径**：QNT-23 卡面写"仓库只放小样本合成/公开数据"，AGENTS.md §2 写"`fixtures/` 只放合成数据"；本 ADR §1 与 §3.2 按 AGENTS.md（仅合成）执行，公开数据只经摄取进入 `data/`。卡面措辞由 planner 在卡上修正。

> 编者说明（QNT-42，2026-09-23）：AGENTS.md §2「`fixtures/` 只放合成数据（`synthetic: true` 头）」与外部接入离线重放需要真实响应字节冲突。现行做法（QNT-28 偏离项 3 / verify-a 复审）：`fixtures/binance_public/` 逐目录豁免、`synthetic: false` + `MANIFEST.json`（url/sha256/size）、只落响应正文不落请求/响应头。AGENTS.md 原文待 owner 裁决；本卡不改 AGENTS.md。
12. **ADR-0002 D2.6 raw 分文件粒度**：D2.6 写 `source/quote_date`，本 ADR §4.1 用 `raw/<source>/<batch_id>/`（batch 内可再按日期分文件）；`source` 仍是第一层，D2.5 整体删源不受影响。是否回写 D2.6 措辞随第 4 条一并裁决。

## 10. Consequences / Revisit trigger

+ 单机零外部服务、全部状态在 Parquet + 仓库 SQL 里可重建；任何 run 由 manifest 精确重放；模块依赖单向，对拍只需替换引擎。
− Parquet 多版本存储放大；DuckDB 每次冷启需注册视图；无消息队列意味着摄取与回测都是 systemd timer 驱动的批处理，无实时流。
需新增（对应实现卡）：QNT-27 骨架 + 数据层基础（§4.3 提交流程、§4.2 R1–R5 重放校验、§4.1 单源断言、allowlist（位置按 §9.10 裁决）、`fixtures/bench/bench_gen.py` + `EXPECTED.json`）+ import-linter + CI；QNT-28 Binance 公开摄取；QNT-29 因子 DSL 与评估；QNT-30 回测/组合/对拍（`hard`）；QNT-31 API + 前端骨架；QNT-32 研报索引；QNT-33 paper 交易（`hard`）。

Revisit：单表（单 lake 前缀）> 50 GB 或视图 p95 > 5 s；需要分钟级实时行情；出现第二个写入者（多进程摄取）；owner 决定扩展市场范围或进入实盘；polars/numba 需成为基线依赖。

## Alternatives considered

- Postgres/TimescaleDB 作业务库：第一阶段单写者、日线为主，Parquet + DuckDB 满足 ADR-0002 且零运维；估算 TB 级 Postgres（ADR-0002 修订）不值。REJECT（Revisit 见 §10）。
- 事件驱动回测（nautilus/zipline 风格）作第一版：语义最完整但工程量与我方"日线 + 向量化对拍"目标不匹配；zipline-reloaded 的 `finance/` 分层作**语义参考**（QNT-25 §5.3），引擎本体向量化。REJECT 作为第一版。
- 直接依赖 qlib 因子引擎：PyPI 无 3.13/3.14 安装路径（QNT-25 §4.1）。REJECT，只借鉴 DSL 语义。
- 每市场一套 schema：`multiplier_unit` / `price_limit_kind` / `adjust_kind` 三列即可让五类市场共表（QNT-26 §3.2/3.3），二期避免迁移。REJECT 分表。
