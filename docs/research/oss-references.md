# 各一级模块可参考的开源项目：业务逻辑参考与许可证审查（QNT-25）

- 调研日期：2026-09-20；**数据重采日期：2026-09-21**（凭据来源整改，见下"采集认证口径与 provenance"）；基线 `main` @ `d4b447e`
- **本文只做"业务逻辑参考"的可行性判定与许可证审查，不引入任何依赖、不建议任何代码复制。**是否引入某个库作为依赖由各落地卡（QNT-27～QNT-33）在 ADR 中单独裁决。
- 事实采集脚本：`docs/research/probes/oss_probe.py`（37 个仓库；GitHub REST + PyPI JSON；**stdlib `urllib`，无第三方依赖、不依赖 `gh` CLI**；运行入口 `scripts/run_probe.sh`（凭据失败即 exit 1，不回落本机凭据）；`python docs/research/probes/oss_probe.py > results.json` 一键复现），本次结果 git 追踪于 `docs/research/probes/oss-results.json`（`probed_at=2026-09-21T05:20:50Z`）
- **采集认证口径与 provenance（2026-09-21 第二次整改）**：脚本默认走**匿名**路径；匿名配额 60 req/h，37 仓库需 ~110 次请求，实测会在第 ~20 个仓库耗尽（脚本按 `X-RateLimit-Remaining=0` 识别为 rate-limit、逐条打印并以非 0 退出，**不会把失败写成"仓库不存在"**）。因此本版数据由 **1Password 注入的 fine-grained PAT** 采集：
  - **凭据来源**：`op run --env-file=docs/research/probes/probe.env.tpl`，模板内仅含引用 `"op://quant-dev/GitHub Personal Access Token/token"`（item 名含空格、字段名为 `token`，引用须加引号），读入后 `.strip()` 注入为 `GITHUB_TOKEN`。**凭据值不打印、不写文件、不入 JSON**；仓库内只有 `*.tpl` 与本文出现引用字面量。`op read` 失败即 exit 1 报"凭据不可用"，**不回落任何本机凭据路径**（禁用 `gh auth token` / `gh api` / `~/.netrc`）。
  - **凭据权限（owner 2026-09-21 声明 + 本次实测）**：fine-grained PAT，**Public repositories only、零额外 permission（无任何 repository / account permission 勾选）**，有效期 **90 天**。实测佐证：带该 token 请求 `GET /rate_limit` 与 `GET /repos/{owner}/{repo}` 均 200、`X-RateLimit-Limit=5000`（已认证额度），且响应**不返回 `X-OAuth-Scopes` 头**——该头仅 classic PAT / OAuth token 才有，其缺失即 fine-grained 凭据的特征。**到期日未能从接口取得**：本次响应未返回 `github-authentication-token-expiration` 头（GitHub 仅对部分请求路径返回），vault 条目的非机密字段也为空，故有效期一项按 **owner 声明的 90 天**记载（条目创建于 2026-09-21T05:16:58Z，据此约 2026-12-20 到期，**未经接口核实**）。
  - **本版数据**：`probed_at=2026-09-21T05:20:50Z`，37/37 采集成功、`failures=[]`，`auth_mode=token(op://quant-dev/GitHub Personal Access Token)`。
  - **历史说明一（保留，不得抹去）**：第一版数据（commit `7dbd996`–`5843a84`，`probed_at` 2026-09-20T04:28:49Z / 05:58:39Z）由**本机 `gh auth token` 采集**，凭据来源不符合 AGENTS.md「凭据只来自 vault 经 op 注入」条款，经 verify-b 两次 REJECT、owner 2026-09-21 裁决后**整体弃用**。弃用原因是**凭据来源不合规**，与数据数值本身是否准确无关。
  - **历史说明二（保留，不得抹去）**：第二版数据（commit `a8d7307`，`probed_at` 2026-09-21T05:04:05Z）虽已走 op 注入，但所用条目 `op://quant-dev/GitHub - PAT/credential` 实为 **classic PAT**，实测 `X-OAuth-Scopes = delete:packages, repo, workflow, write:packages`——**含写权限**，与 owner 采纳的"public 只读、零额外 scope"不符，且当时 `:6` 写作"只读 PAT"属**错误声明**。经 verify-b REJECT、owner 裁决后该 classic PAT **已 revoke**、旧 vault 条目**已删除**，数据由本版**整体替换**。`oss-results.json` 每次整改均为整体重建，不保留任何一版旧文件的行。
- 校验脚本：`docs/research/probes/test_oss_probe.py`（19 项失败分类自检，离线）、`docs/research/probes/check_doc_consistency.py`（事实表 37 行 ↔ JSON 一致性，离线）
- **活跃度口径**：`commits_1y` = `GET /repos/{r}/commits?since=<今日-365d>` 分页计数（默认分支）；`pushed_at` / `latest_release` 取仓库与 `releases/latest`。计数含 merge commit，跨仓库不可直接比大小，只用于判断"是否仍在维护"。
- **许可证口径**：SPDX 取 GitHub License API `license.spdx_id`；返回 `NOASSERTION` 的四个仓库（OpenBB / vectorbt / MinerU / Zotero）已逐个读取许可证正文，结论见 §7。**SPDX 字段不是法律意见**；§7 标红项在后续卡中不得引入其代码。
- 技术栈契合点对照基线：Python ≥3.14 / uv / DuckDB+Parquet / numpy / FastAPI / React+TS + Lightweight Charts（planner 2026-09-20 04:00 派发评论）。**"Python 3.14 可用"一律以 PyPI `requires_python` + classifier + 是否有 cp314 wheel 判定**，未实际安装验证 → 标"未实测"。

> 编者说明（QNT-49，2026-09-23）：owner 2026-09-23 裁决——许可口径见 ADR-0003 §9.6 编者说明：本项目为个人研究、不分发，GPL/AGPL/Commons Clause 均可使用；本文 §7 排除口径不再作为后续卡约束。§7 正文不改。

## 0. 结论速览

| # | 结论 | 依据 |
|---|---|---|
| 0.1 | **回测对拍（QNT-30）首选 `vectorbt` v1.1.0，备选 `bt` v1.2.3**；两者都是 MIT/Apache 系、都有 Python 3.14 支持、都能被"数组进-指标出"地调用，适合做交叉校验 | §5.1、§5.2 |
| 0.2 | **但 vectorbt 的许可证是 Apache-2.0 + Commons Clause，不是纯 Apache-2.0**（GitHub 显示 `NOASSERTION`，README 徽章自称 "Fair Code"）。Commons Clause 禁止"销售"其功能派生的产品/服务 → 内部研究可用，**商业化路径需 owner 裁决** | §7.2 |
| 0.3 | **参考实现的"语义权威"是 zipline-reloaded，不是首选对拍库**：`finance/` 下 slippage / commission / ledger 的建模分层是目前最完整的公开日线撮合语义（9 个滑点模型、9 个佣金模型、成交/拆股/分红/佣金分离入账）。但它 `commits_1y=4`（近乎停更）、无 3.14 classifier/cp314 wheel（`requires_python=">=3.10"` **无上界**，兼容性未验证）、且需自建 bundle → **主依赖树不引入，保留为隔离环境下的第三方对拍参照** | §5.3 |
| 0.4 | **`microsoft/qlib` 在我们的 Python 基线上装不上**：PyPI `pyqlib` 0.9.7 只有 cp38–cp312 wheel 且**无 sdist**，`commits_1y=27`、最后 release 2025-08-15 → 因子表达式引擎（`Ref/Mean/Std/Corr/Slope/Rsquare/Resi/WMA/EMA/Rank/Quantile` 等 Rolling 算子族）**只能当设计参考，不能当依赖** | §4.1 |
| 0.5 | **GPL/AGPL/LGPL 类共 7 个**（freqtrade、frequi、backtesting.py、OpenBB、Zotero、paperless-ngx、nautilus_trader），其中 freqtrade 与 backtesting.py 的业务逻辑最值得读 → 全部标"只能参考思路不可复制代码"，单列 §7 | §7.1 |
| 0.6 | **前端 Lightweight Charts 已是基线选型，本文只补两个正交项**：`KLineChart`（Apache-2.0，零依赖，内置指标与画线交互）补"技术指标 + 绘图工具"的交互语义；`perspective`（Apache-2.0）补"大表格虚拟滚动 + 透视"，**不是** K 线图替代 | §2 |
| 0.6a | **Lightweight Charts 的许可条件不止 Apache-2.0**：上游 README 额外要求**在用户可见页面保留 `NOTICE` 署名文本 + 指向 <https://www.tradingview.com/> 的链接**（默认开启的 `attributionLogo` 选项可满足链接部分，关掉则须自行补上）。这是**采用前提、不是可选项**，QNT-27 落地时须列入验收项 | §2.1 |
| 0.7 | **paper 交易模块的可参考对象少于其他模块**：真正能读的是 Hummingbot 的 `paper_trade` 撮合与 `budget_checker`、alpaca-py 的 paper/live URL 分流。**alpaca-py `TradingClient(paper=True)` 是默认值**，与 ADR-0001 D1.2 的白名单断言方向一致，可作为实现参照 | §6 |
| 0.8 | **研报资料模块（QNT-32）的成熟件集中在"文档解析"而非"研报管理"**：docling（MIT）与 unstructured（Apache-2.0）可直接读其分块语义；Zotero（AGPL）只读其条目/附件数据模型思路 | §3 |

## 1. 全量事实表（37 个候选，按模块分组）

下表所有数值来自 `probes/oss-results.json`，`probed_at=2026-09-21T05:20:50Z`。`c1y` = 近一年提交数（口径见文首）。**"3.14"列**（口径经 verify-b 2026-09-20 复审后收紧）：`Y` = PyPI classifier 含 3.14 **或**已发 cp314 wheel；`未标注` = **无 3.14 classifier / 无 cp314 wheel，兼容性未验证**——注意这**不等于"不支持"**，若其 `requires_python` 无上界且有 sdist，3.14 下仍可能正常安装，只是上游未声明、本文未实测；`N` = 有确凿证据无法在 3.14 安装（目前仅 qlib：无 sdist 且 wheel 止于 cp312，见 §4.1）；`未实测` = 未走 PyPI 分发或本文未采集；`—` = 非 Python 包。**本列不得单独作为"排除某库"的理由**。

| 模块 | 仓库 | SPDX | c1y | 最后 push | 最新 release | 3.14 |
|---|---|---|---|---|---|---|
| 行情看板 | [tradingview/lightweight-charts](https://github.com/tradingview/lightweight-charts) | Apache-2.0 | 328 | 2026-09-18 |  v5.2.1 (2026-08-12) | — |
| 行情看板 | [klinecharts/KLineChart](https://github.com/klinecharts/KLineChart) | Apache-2.0 | 250 | 2026-09-18 |  v10.0.3 (2026-08-27) | — |
| 行情看板 | [perspective-dev/perspective](https://github.com/perspective-dev/perspective) | Apache-2.0 | 325 | 2026-09-18 |  v5.5.1 (2026-09-18) | — |
| 行情看板 | [freqtrade/frequi](https://github.com/freqtrade/frequi) | **GPL-3.0** | 1372 | 2026-09-17 |  3.1.2 (2026-08-30) | — |
| 数据中心 | [dlt-hub/dlt](https://github.com/dlt-hub/dlt) | Apache-2.0 | 613 | 2026-09-18 |  1.30.0 (2026-08-11) | Y |
| 数据中心 | [ccxt/ccxt](https://github.com/ccxt/ccxt) | MIT | 9974 |  2026-09-20 |  v4.5.81 (2026-09-19) | Y |
| 数据中心 | [gerrymanoim/exchange_calendars](https://github.com/gerrymanoim/exchange_calendars) | Apache-2.0 | 72 | 2026-09-15 |  4.13.2 (2026-03-10) | Y |
| 数据中心 | [OpenBB-finance/OpenBB](https://github.com/OpenBB-finance/OpenBB) | **AGPL-3.0**(§7.1) | 138 | 2026-09-19 |  ODP (2026-04-25) | — |
| 数据中心 | [databento/databento-python](https://github.com/databento/databento-python) | Apache-2.0 | 152 | 2026-09-17 |  v0.86.0 (2026-09-01) | Y |
| 数据中心 | [ranaroussi/yfinance](https://github.com/ranaroussi/yfinance) | Apache-2.0 | 318 | 2026-09-17 |  1.7.0 (2026-08-26) | 未标注 |
| 研报资料 | [docling-project/docling](https://github.com/docling-project/docling) | MIT | 790 |  2026-09-20 |  v2.129.0 (2026-09-18) | 未实测 |
| 研报资料 | [Unstructured-IO/unstructured](https://github.com/Unstructured-IO/unstructured) | Apache-2.0 | 155 |  2026-09-21 |  0.27.6 (2026-09-14) | 未实测 |
| 研报资料 | [opendatalab/MinerU](https://github.com/opendatalab/MinerU) | Apache-2.0+附加(§7.2) | 2871 |  2026-09-20 |  mineru-4.0.5-released (2026-09-20) | 未实测 |
| 研报资料 | [zotero/zotero](https://github.com/zotero/zotero) | **AGPL-3.0**(§7.1) | 992 | 2026-09-17 | — | — |
| 研报资料 | [paperless-ngx/paperless-ngx](https://github.com/paperless-ngx/paperless-ngx) | **GPL-3.0** | 1676 |  2026-09-21 |  v3.2.1 (2026-09-20) | — |
| 研报资料 | [chroma-core/chroma](https://github.com/chroma-core/chroma) | Apache-2.0 | 1237 | 2026-09-18 |  1.5.9 (2026-05-05) | 未实测 |
| 因子宫殿 | [microsoft/qlib](https://github.com/microsoft/qlib) | MIT | 27 | 2026-09-17 |  v0.9.7 (2025-08-15) | **N**(§4.1) |
| 因子宫殿 | [stefan-jansen/alphalens-reloaded](https://github.com/stefan-jansen/alphalens-reloaded) | Apache-2.0 | **0** | 2025-12-15 |  0.4.5 (2025-07-23) | 未标注 |
| 因子宫殿 | [TA-Lib/ta-lib-python](https://github.com/TA-Lib/ta-lib-python) | BSD-2-Clause | 44 |  2026-09-21 |  v0.8.0 (2026-09-13) | Y |
| 因子宫殿 | [xgboosted/pandas-ta-classic](https://github.com/xgboosted/pandas-ta-classic) | MIT | 659 | 2026-09-16 |  0.8.32 (2026-09-14) | Y |
| 因子宫殿 | [bukosabino/ta](https://github.com/bukosabino/ta) | MIT | **1** | 2026-03-18 | — | 未标注 |
| 策略工厂 | [polakowo/vectorbt](https://github.com/polakowo/vectorbt) | Apache-2.0+CC(§7.2) | 149 | 2026-09-17 |  v1.1.0 (2026-07-05) | Y |
| 策略工厂 | [pmorissette/bt](https://github.com/pmorissette/bt) | MIT | 191 |  2026-09-20 |  v1.2.3 (2026-09-11) | Y(wheel) |
| 策略工厂 | [stefan-jansen/zipline-reloaded](https://github.com/stefan-jansen/zipline-reloaded) | Apache-2.0 | **4** | 2026-01-06 |  3.1.1 (2025-07-23) | 未标注 |
| 策略工厂 | [QuantConnect/Lean](https://github.com/QuantConnect/Lean) | Apache-2.0 | 429 | 2026-09-18 |  v2.4.0.1 (2017-08-08) | — (C#) |
| 策略工厂 | [kernc/backtesting.py](https://github.com/kernc/backtesting.py) | **AGPL-3.0** | 33 | 2026-08-05 | — | 未标注 |
| 策略工厂 | [nautechsystems/nautilus_trader](https://github.com/nautechsystems/nautilus_trader) | **LGPL-3.0** | 5462 |  2026-09-21 |  v1.231.0 (2026-08-02) | Y |
| 策略工厂 | [PyPortfolio/PyPortfolioOpt](https://github.com/PyPortfolio/PyPortfolioOpt) | MIT | 41 | 2026-07-07 |  v1.6.0 (2026-02-26) | Y |
| 策略工厂 | [dcajasn/Riskfolio-Lib](https://github.com/dcajasn/Riskfolio-Lib) | BSD-3-Clause | 36 | 2026-08-18 | — | Y |
| 策略工厂 | [skfolio/skfolio](https://github.com/skfolio/skfolio) | BSD-3-Clause | 201 |  2026-09-20 |  v1.3.0 (2026-09-20) | Y |
| 策略工厂 | [ranaroussi/quantstats](https://github.com/ranaroussi/quantstats) | Apache-2.0 | 13 | 2026-07-20 |  v0.0.81 (2026-01-13) | 未标注 |
| paper 交易 | [alpacahq/alpaca-py](https://github.com/alpacahq/alpaca-py) | Apache-2.0 | 65 | 2026-09-18 |  v0.44.0 (2026-08-11) | Y |
| paper 交易 | [hummingbot/hummingbot](https://github.com/hummingbot/hummingbot) | Apache-2.0 | 1703 |  2026-09-20 |  v2.16.0 (2026-07-29) | 未实测 |
| paper 交易 | [freqtrade/freqtrade](https://github.com/freqtrade/freqtrade) | **GPL-3.0** | 3294 |  2026-09-21 |  2026.8 (2026-08-31) | — |
| paper 交易 | [jesse-ai/jesse](https://github.com/jesse-ai/jesse) | MIT | 445 | 2026-09-17 | — | 未实测 |
| paper 交易 | [ib-api-reloaded/ib_async](https://github.com/ib-api-reloaded/ib_async) | BSD-2-Clause | 10 | 2026-08-19 |  v2.0.1 (2025-06-22) | 未实测 |
| 跨模块 | [stefan-jansen/machine-learning-for-trading](https://github.com/stefan-jansen/machine-learning-for-trading) | MIT | 751 |  2026-09-21 |  v3.1.0-artifacts (2026-09-20) | — |

## 2. 行情看板

### 2.1 tradingview/lightweight-charts — Apache-2.0（已是基线选型，此处只记可借鉴点）
- 仓库 <https://github.com/tradingview/lightweight-charts>；c1y=328，v5.2.1 (2026-08-12)；npm `lightweight-charts@5.2.1` 声明 `license: Apache-2.0`，运行时依赖仅 `fancy-canvas@2.1.0`。
- **可借鉴的具体业务逻辑**：① `src/` 的 `model / views / renderers` 三层分离——数据模型、坐标视图、canvas 绘制各自独立，我们的指标叠加层应照此分层而不是把计算塞进绘制回调；② **Series Primitives 插件协议**（`src/plugins`，示例见 `plugin-examples/src/plugins/`：`bands-indicator`、`delta-tooltip`、`expiring-price-alerts`、`highlight-bar-crosshair`、`heatmap-series` 等）——把"指标/标注"建模为挂在 series 上的 primitive 而非另一条 series，正是我们叠加 MA/BOLL/买卖点所需的扩展点。
- **使用条件（采用前提，不是可选项）**：Apache-2.0 之外，上游 README 额外要求署名——"This license requires specifying TradingView as the product creator. You shall add the 'attribution notice' from the NOTICE file and a link to <https://www.tradingview.com/> to the page of your website or mobile application that is available to your users."（<https://github.com/tradingview/lightweight-charts/blob/master/README.md>）。即：**用户可见页面必须同时保留 `NOTICE` 的署名文本（"TradingView Lightweight Charts™ / Copyright (с) 2025 TradingView, Inc."，见 <https://github.com/tradingview/lightweight-charts/blob/master/NOTICE>）和一个指向 tradingview.com 的链接**。上游提供的 `attributionLogo` 图表选项（`LayoutOptions.attributionLogo`，默认开启）可满足链接部分；**若 UI 把它关掉，必须在页面别处自行补上署名与链接**。这是引入该库的前提条件，QNT-27 落地时须在验收项里逐条核对，不可作为"以后再说"的事项。
- **技术栈契合**：TS 原生、零框架绑定，React+TS 下用 ref + `useEffect` 挂载即可；Apache-2.0 允许直接依赖（**受上一条署名条件约束**）。

### 2.2 klinecharts/KLineChart — Apache-2.0
- 仓库 <https://github.com/klinecharts/KLineChart>；c1y=250，v10.0.3 (2026-08-27)；npm `klinecharts@10.0.3` 声明 `license: Apache-2.0`，**运行时依赖为空**。
- **可借鉴的具体业务逻辑**：内置指标计算 + **画线工具（overlay）的交互状态机**——选中/拖拽/吸附/多点绘制的状态流转，是 Lightweight Charts 不提供的部分。我们要做"技术指标 + 手绘趋势线"时，应参考其 overlay 事件模型的**语义**（不复制实现）。
- **技术栈契合**：同为 canvas + TS 零依赖；**不建议同时引入两套图表库**——建议只取其交互语义，渲染仍用基线的 Lightweight Charts。

### 2.3 perspective-dev/perspective — Apache-2.0
- 仓库 <https://github.com/perspective-dev/perspective>；c1y=325，v5.5.1 (2026-09-18)；npm `@finos/perspective@3.8.0` 声明 `license: Apache-2.0`。
- **可借鉴的具体业务逻辑**：**Arrow 列式数据 → 浏览器端虚拟滚动/透视/聚合**的那条链路。我们的盘口、成分股、因子截面都是"几千行 × 几十列"的表格，服务端 DuckDB 出 Arrow、前端增量喂给表格组件，这条链路的分工方式值得照搬**设计**。
- **技术栈契合**：与 DuckDB+Parquet 同属 Arrow 生态，服务端 `duckdb` → Arrow IPC → 前端，无需 JSON 序列化中转；**定位是表格而非 K 线**，与 §2.1 不冲突。

### 2.4 freqtrade/frequi — GPL-3.0 ⚠️（只可参考思路，见 §7.1）
- 仓库 <https://github.com/freqtrade/frequi>；c1y=1372，3.1.2 (2026-08-30)。
- **可借鉴的具体业务逻辑**：`src/` 下 `pages / components / stores / composables` 的划分，展示了"回测结果 + 实时持仓 + 策略参数"三类异构面板如何共用一套 store。**只读结构，不可复制代码**；且它是 Vue 而非 React，语义迁移成本本身就排除了照搬。

## 3. 数据中心

### 3.1 dlt-hub/dlt — Apache-2.0
- 仓库 <https://github.com/dlt-hub/dlt>；c1y=613，1.30.0 (2026-08-11)；PyPI `dlt` 1.30.0 `requires_python=<3.15,>=3.10`（含 3.14 classifier）。
- **可借鉴的具体业务逻辑（与 ADR-0002 直接对应）**：① **`_dlt_load_id` / `_dlt_loads` 血缘表**——每行带 load_id、并建立 `{table}._dlt_load_id` → `_dlt_loads.load_id` 的引用（见 `dlt/common/schema/utils.py` 中 `"Create a Reference between {table}._dlt_load_id and _dlt_loads.load_id"`），**这正是 ADR-0002 D2.7 `ingestion_batch` 想要的形状**，可直接参考其"批次表 + 每行外键"的建模；② `dlt/extract/incremental/` 的增量游标与 `lag` 处理，对应我们"供应商回补"场景；③ `write_disposition` 中 `append` 语义与 D2.1 只 insert 一致。
- **技术栈契合**：`dlt/destinations/impl/` 内置 `duckdb`、`ducklake`、`filesystem` 三个与我们直接相关的目标端 → DuckDB+Parquet 路径是它的一等公民。
- **不可照搬的原因**：它是完整 ELT 框架，自带 schema 演进与状态存储，与 ADR-0002"只 insert、批次封闭水位"的严格语义未必一致（D2.7 未决项见 ADR-0002 文末）→ **参考血缘建模，不建议整体引入**。

### 3.2 ccxt/ccxt — MIT
- 仓库 <https://github.com/ccxt/ccxt>；c1y=9974（全仓库含自动生成，跨语言），v4.5.81 (2026-09-19)；PyPI `ccxt` 4.5.81 含 3.14 classifier。
- **可借鉴的具体业务逻辑**：① `fetch_ohlcv(symbol, timeframe, since, limit)` 的**统一分页契约**（`python/ccxt/binance.py:4961`）——用 `since` 前向翻页而非页码，天然适合"按时间窗补齐 + 幂等重拉"，是我们 Binance 日线摄取的游标语义参考；② **`set_sandbox_mode(enabled)`**（`python/ccxt/base/exchange.py:3463`）把 testnet URL 切换收敛到一个开关，且当交易所无 sandbox URL 时**抛 `NotSupported` 而不是静默回落主网**——这与 ADR-0001 D1.7 的 fail-closed 要求同向，值得照此实现我们的 allowlist 断言。
- **不可照搬的原因**：Python 版由 TS 转译生成，代码风格与类型标注不适合手工改；且其统一层会**掩盖**交易所间的语义差异（如 Binance demo 与主网公共行情同源），而 ADR-0001 未决项正要求公共只读与签名交易通道分开 → 只参考契约形状。

### 3.3 gerrymanoim/exchange_calendars — Apache-2.0
- 仓库 <https://github.com/gerrymanoim/exchange_calendars>；c1y=72，4.13.2 (2026-03-10)；PyPI 4.13.2 `requires_python=<4,>=3.10` 含 3.14 classifier。
- **可借鉴的具体业务逻辑**：`exchange_calendar.py` 的 session 语义 API——`sessions_in_range` / `session_open_close` / `is_session` / `next_session` / `previous_session` / `sessions_minutes`（含 `XNYS` 日历与 `us_holidays.py`）。我们做日线"缺口核查"（QNT-28）时，**"某日该不该有数据"必须由交易日历回答而不是由数据本身推断**，否则停牌与缺采无法区分。
- **技术栈契合**：纯 Python + pandas，日线粒度开销可忽略；美股 `XNYS` 正是我们主市场。

### 3.4 OpenBB / databento-python / yfinance（补充）
- **OpenBB** <https://github.com/OpenBB-finance/OpenBB>（**AGPL-3.0**，§7.1）：可借鉴 `openbb_platform/core/.../provider/standard_models/`（`balance_sheet.py`、`bond_indices.py` 等逐 endpoint 的标准模型）+ `providers/` 下 40+ 家源适配器的**两层结构**——"标准化模型 ← 各源 transformer"。**这正是我们多源归一 + `source` 字段的形状**，但 AGPL → 只读结构，不可复制代码。
- **databento-python** <https://github.com/databento/databento-python>（Apache-2.0，c1y=152，3.14 ✅）：可借鉴其**不可变历史切片 + 本地缓存**的调用模式，与 ADR-0002 D2.6 raw payload 落盘直接对应。
- **yfinance** <https://github.com/ranaroussi/yfinance>（Apache-2.0，c1y=318）：**PyPI 1.7.0 未声明 `requires_python`，classifier 止于 3.13（无 3.14 classifier / 无 cp314 专属 wheel，但为 py3 纯 wheel、无版本上界 → 3.14 兼容性未验证，非"不支持"）**；QNT-2/QNT-3 已定性为"非官方、personal use、仅 fallback/校验"，本文不改变该结论，仅补活跃度事实。

## 4. 因子宫殿

### 4.1 microsoft/qlib — MIT，但**装不上我们的 Python 基线**
- 仓库 <https://github.com/microsoft/qlib>；c1y=**27**，最新 release v0.9.7 (2025-08-15)。**PyPI `pyqlib` 0.9.7 只提供 cp38/cp39/cp310/cp311/cp312 wheel，且无 sdist** → Python 3.13/3.14 无任何安装路径。
- **可借鉴的具体业务逻辑**：① **表达式因子引擎**（`qlib/data/ops.py`）的 Rolling 算子族——`Ref/Mean/Sum/Std/Var/Skew/Kurt/Max/IdxMax/Min/Quantile/Rank/Delta/Slope/Rsquare/Resi/WMA/EMA` 与 `PairRolling` 的 `Corr`；把因子写成可解析字符串表达式，**天然满足 ADR-0002"可解释"**（因子定义本身就是可存储、可 diff、可重放的字符串）。② **Alpha158 / Alpha360 handler**（`qlib/contrib/data/handler.py:98` / `:48`）的 `get_feature_config()` + `infer_processors` / `learn_processors` 分离——**推理期处理与训练期处理分开**，避免用全样本统计量归一化造成前视泄漏，这是 QNT-29 必须照搬的**语义**。
- **不可照搬的原因**：除安装问题外，它绑定自有二进制数据格式与 `D.features` 数据层，与我们 DuckDB+Parquet 不兼容 → **只作因子表达式与处理器分层的设计参考**。

### 4.2 stefan-jansen/alphalens-reloaded — Apache-2.0，**c1y=0（近一年零提交）**
- 仓库 <https://github.com/stefan-jansen/alphalens-reloaded>；最后 push 2025-12-15，release 0.4.5 (2025-07-23)；PyPI 0.4.6 `requires_python=">=3.10"`（**无上界**），classifier 止于 3.13，py3 纯 wheel → **无 3.14 声明，兼容性未验证**。
- **可借鉴的具体业务逻辑（因子评估的事实标准口径）**：`src/alphalens/performance.py` 中 `factor_information_coefficient`（IC）、`mean_information_coefficient`、`mean_return_by_quantile`、`compute_mean_returns_spread`（多空价差）、`quantile_turnover`（分位换手）、`factor_rank_autocorrelation`（因子秩自相关/衰减）、`factor_alpha_beta`；以及 `utils.py` 的 `get_clean_factor_and_forward_returns` / `compute_forward_returns` / `quantize_factor` / `demean_forward_returns`。**QNT-29 的因子评估指标应逐项对齐这套口径**（尤其 forward return 的对齐方式与分位数分桶的边界处理）。
- **不可照搬的原因**：已停更（c1y=0）+ 绑定 pandas/matplotlib tear-sheet；且其 `requires_dist` 含 **`pandas<3.0,>=1.5.0`** 这一**确凿上界**（<https://pypi.org/pypi/alphalens-reloaded/json>），与 vectorbt 要求的 `pandas>=3.0.3` **直接冲突**，无法共处同一环境 → **只对齐指标定义，自行用 numpy 实现**。（注意：此处的排除依据是 **pandas 依赖上界 + 停更**，**不是** Python 3.14 判定。）

### 4.3 TA-Lib/ta-lib-python — BSD-2-Clause；xgboosted/pandas-ta-classic — MIT
- **ta-lib-python** <https://github.com/TA-Lib/ta-lib-python>：c1y=44，v0.8.0 (2026-09-13)；PyPI `ta-lib` 0.8.0 **有 cp314 wheel** ✅。可借鉴：**各指标的"预热期（unstable period）"语义**——前 N 根输出不可信，必须显式截断，这是回测前视偏差的高频来源。技术栈契合：C 实现 + numpy 数组进出，与我们 numpy 基线对齐；**注意底层 C 库需单独安装**（wheel 已含则另说，未实测）。
- **pandas-ta-classic** <https://github.com/xgboosted/pandas-ta-classic>：c1y=659，0.8.32 (2026-09-14)，PyPI 含 3.14 classifier ✅。**注意：原 `twopirllc/pandas-ta` 仓库现已 404，本 fork 是当前活跃继承者**（vectorbt v1.1.0 的依赖列表中也写的是 `pandas-ta-classic`）。可借鉴：纯 Python/pandas 的指标实现可作为 ta-lib 的**对拍参照**（同一指标两套实现比对）。
- **bukosabino/ta** <https://github.com/bukosabino/ta>：c1y=**1**，PyPI classifier 仅 3.6/3.7 → **不推荐**，仅列出以说明已考察。

## 5. 策略工厂（含 QNT-30 对拍首选/备选裁决）

### 5.1 ⭐ 对拍**首选**：polakowo/vectorbt v1.1.0
- 仓库 <https://github.com/polakowo/vectorbt>；c1y=149，v1.1.0 (2026-07-05)；PyPI `vectorbt` 1.1.0 `requires_python=<3.15,>=3.11`，classifier 含 **3.14** ✅，依赖 `numpy>=2.4.6` / `pandas>=3.0.3` / `numba>=0.66`（`numba` 0.67.0 有 cp314 wheel ✅）。
- **选它作首选的理由**：① **调用形态最适合对拍**——"信号数组进、组合指标出"，无需实现 Strategy 类、无事件循环，可直接对同一份 numpy 信号跑出 equity curve 与 Sharpe/MaxDD，**与我们自研引擎的输出逐字段比对成本最低**；② 是候选中**唯一同时满足"3.14 可用 + 近一年活跃 + 向量化日线"**的库；③ 依赖链与我们基线同向（numpy/numba）。
- **可借鉴的具体业务逻辑**：其"信号 → 持仓 → 交易记录 → 组合统计"的**四段式数据结构分层**，尤其把 trade records 做成结构化数组而非对象列表，便于向量化统计。
- ⚠️ **许可证不是纯 Apache-2.0**：Apache-2.0 **+ Commons Clause**（详见 §7.2）。内部研究用途不受限；**若未来商业化，需 owner 裁决**。**作为"对拍参照物"只需其输出数字，风险面最小**；即便如此仍建议 QNT-30 在 ADR 中显式记录该条款。

### 5.2 对拍**备选**：pmorissette/bt v1.2.3
- 仓库 <https://github.com/pmorissette/bt>；c1y=191，v1.2.3 (2026-09-11)；**MIT**（许可最干净）。PyPI `bt` 1.2.3 `requires_python>=3.9`，**wheel 含 cp314** ✅（classifier 尚未更新到 3.14，但已发 cp314 wheel → 判为可用，**未实测**）。
- **选它作备选的理由**：① **MIT 无附加条款**，若 §7.2 的 Commons Clause 在商业化裁决中成为障碍，可无缝顶替首选；② 其 `bt/algos.py` 的 **Algo/AlgoStack 组合范式**（`SelectAll` → `WeighEqually` → `Rebalance` 逐级流水线）是与 vectorbt **完全不同的建模路径**——两者思路差异越大，对拍越能暴露我方引擎的隐含假设；③ 内置再平衡语义，正好覆盖组合层对拍。
- **可借鉴的具体业务逻辑**：`bt/core.py` 的 `Node/StrategyBase/SecurityBase` 树形组合结构——把"组合 → 子策略 → 标的"建成树并逐级下发权重，是我们做多策略组合时的分层参考。
- **相对首选的劣势**：面向"权重/再平衡"而非"逐笔信号"，**逐笔成交语义（滑点/部分成交）不如 vectorbt 直接**，因此定为备选而非首选。

> **QNT-30 对拍建议（供 planner/ADR 采纳）**：自研引擎为**被测方**，vectorbt 为**首选参照**，bt 为**备选参照**；对拍口径固定为同一份日线 Parquet + 同一份信号，比对 ① 逐日持仓 ② 逐笔成交价 ③ equity curve ④ Sharpe/MaxDD/换手。**差异容忍度与手续费/滑点模型必须先统一**，否则对拍无意义——这一项本身应在 QNT-30 卡里先定。

### 5.3 语义权威、对拍第三参照：stefan-jansen/zipline-reloaded
- 仓库 <https://github.com/stefan-jansen/zipline-reloaded>；**c1y=4**，最后 push 2026-01-06，release 3.1.1 (2025-07-23)。
- **Python 3.14 现状（2026-09-20 修订，verify-b 复审采纳）**：PyPI `zipline-reloaded` 3.1.1 `requires_python=">=3.10"`，**无上界**；classifier 覆盖 3.10–3.13，wheel 覆盖 cp310–cp313，有 sdist（<https://pypi.org/pypi/zipline-reloaded/json>）。→ 准确表述是**无 3.14 classifier、无 cp314 wheel，3.14 兼容性未验证**；**不能据此断定它不支持 3.14**。它含 Cython 扩展（`_finance_ext.pyx`），3.14 下需从 sdist 源码编译，能否编译通过**本文未实测**（只读调研，不装包）。前一版写的"Python 上界 3.13"是错误结论，已删除。
- **可借鉴的具体业务逻辑（这是本模块最有价值的部分）**：`src/zipline/finance/` 下的建模分层——
  - `slippage.py`：`SlippageModel` 基类 + `VolumeShareSlippage` / `FixedSlippage` / `FixedBasisPointsSlippage` / `MarketImpactBase` / `VolatilityVolumeShare` / `NoSlippage`，并用 `EquitySlippageModel` / `FutureSlippageModel` 按资产类型分流，**`LiquidityExceeded` 显式表达"成交量吃不下"**；
  - `commission.py`：`PerShare` / `PerContract` / `PerTrade` / `PerDollar` / `PerFutureTrade` 五种计费形态 + 按资产类型分流；
  - `ledger.py`：`process_transaction` / `process_splits` / `process_order` / `process_commission` / `process_dividends` / `update_portfolio` **把成交、拆股、下单、佣金、分红分别入账**——正是 ADR-0002 "账本表只 insert" 所需的事件粒度。
- **候选资格（修订）**：前一版因"上界 3.13"把它排除出候选，该依据不成立，**现恢复其候选地位**，按与 vectorbt / bt 相同的口径重评：
  - 活跃度：**c1y=4**，最后 release 2025-07-23 —— 三者中最低，近乎停更（这是**事实充分、口径一致**的减分项）；
  - 3.14：未标注、未实测（与 vectorbt 的 classifier 含 3.14、bt 的 cp314 wheel 相比，证据等级最弱）；
  - 对拍调用成本：需实现 `TradingAlgorithm` + 事件循环 + 自有 bundle 数据摄取，**远高于 vectorbt 的"信号数组进、指标出"**，这是它不作首选/备选的**主因**，与 3.14 无关。
- **重评结论**：**维持 vectorbt 首选、bt 备选不变**；zipline-reloaded 定为 **"语义权威 + 可选第三参照"**——QNT-30 若在滑点/佣金/分红入账语义上与前两者出现分歧，**可在隔离环境（独立 venv，允许降级到 3.13）单独装它做一次三方对拍裁决**，但**不进主依赖树**（理由：停更 + 需自建 bundle + 3.14 未实测，非许可证问题，Apache-2.0 本身无障碍）。

### 5.4 组合优化：PyPortfolioOpt / Riskfolio-Lib / skfolio
| 库 | SPDX | c1y | 3.14 | 可借鉴的具体业务逻辑 |
|---|---|---|---|---|
| [PyPortfolioOpt](https://github.com/PyPortfolio/PyPortfolioOpt) | MIT | 41 | ✅(cls) | `pypfopt/` 下 `expected_returns.py` / `risk_models.py` / `objective_functions.py` / `efficient_frontier/` / `black_litterman.py` / `hierarchical_portfolio.py` / `discrete_allocation.py` —— **把"预期收益估计""风险矩阵估计""目标函数"三者解耦**是最值得照搬的分层；`discrete_allocation.py` 的"连续权重 → 整数股数"离散化是实盘/paper 落地必需的一步，常被忽略 |
| [Riskfolio-Lib](https://github.com/dcajasn/Riskfolio-Lib) | BSD-3-Clause | 36 | ✅(cp314 wheel) | 风险度量谱系最全（CVaR/CDaR 等下行风险），可作为 QNT-30 组合优化的**风险指标定义参照** |
| [skfolio](https://github.com/skfolio/skfolio) | BSD-3-Clause | 201 | ✅ | **活跃度最高**（v1.3.0, 2026-09-20）。`src/skfolio/` 下 `optimization` / `moments` / `prior` / `uncertainty_set` / `model_selection` / `pre_selection` —— 采用 **scikit-learn estimator 接口**，`model_selection` 提供组合层的 **walk-forward / 交叉验证**，这是三者中唯一直面"回测期与调参期分离"的，**对防前视泄漏最有参考价值** |

### 5.5 绩效报告：ranaroussi/quantstats（Apache-2.0，**已显老**）
- 仓库 <https://github.com/ranaroussi/quantstats>；c1y=13，v0.0.81 (2026-01-13)；PyPI 0.0.81 `requires_python=">=3.10"`（**无上界**），classifier 止于 3.13，py3 纯 wheel → **无 3.14 声明，兼容性未验证**。
- **可借鉴**：`quantstats/stats.py` 的指标清单（Sharpe/Sortino/MaxDD/Calmar/VaR 等）与 `reports.py` 的报告分节结构，可作为 QNT-30 绩效报告的**指标 checklist**。**不建议引入**——依据是 **c1y=13 的低活跃 + 指标口径已可自行实现**，**不以"3.14 未声明"作为排除理由**（该项仅为未验证）。自行用 numpy 实现。

### 5.6 其他已考察但不推荐作对拍
- **QuantConnect/Lean** <https://github.com/QuantConnect/Lean>（Apache-2.0，c1y=429）：**C#**，与我们技术栈不匹配。但 `Common/Securities/Option/` 下的 `DefaultOptionAssignmentModel` / `IOptionAssignmentModel` / `OptionChainFilterUniverse` / `CurrentPriceOptionPriceModel` 等，是**美股期权建模**（行权指派、期权链筛选宇宙）少见的完整公开实现 → 对未来期权回测有**设计参考**价值，本阶段仅登记。
- **nautilus_trader**（**LGPL-3.0**，§7.1）与 **backtesting.py**（**AGPL-3.0**，§7.1）见 §7。

## 6. paper 交易

> 前置：按 **ADR-0001**，本模块全程 paper/testnet/demo 凭据，实盘下单路径只允许"生成意图 → 输出给人"。以下所有参考点均只针对 paper 侧。

### 6.1 alpacahq/alpaca-py — Apache-2.0
- 仓库 <https://github.com/alpacahq/alpaca-py>；c1y=65，v0.44.0 (2026-08-11)；PyPI `requires_python=<4.0.0,>=3.10.0`，classifier 含 **3.14** ✅。
- **可借鉴的具体业务逻辑（与 ADR-0001 D1.2 直接对应）**：`alpaca/trading/client.py:58` 的 `paper: bool = True` —— **默认值就是 paper**，且 `base_url` 由 `BaseURL.TRADING_PAPER if paper else BaseURL.TRADING_LIVE` 分流（`:79-84`），同时把 `sandbox=paper` 一并下传。**"默认安全 + URL 由开关唯一决定"正是 D1.2 白名单断言应有的形状**；我们应在此基础上**再加一层启动断言**（D1.2 要求 URL 命中白名单否则拒绝启动），因为库的默认值可被调用方覆盖。
- **技术栈契合**：`alpaca/` 分 `trading` / `data` / `broker`，与我们 `packages/{execution,data}` 的切分同构；美股主市场直接对口。

### 6.2 hummingbot/hummingbot — Apache-2.0
- 仓库 <https://github.com/hummingbot/hummingbot>；c1y=1703，v2.16.0 (2026-07-29)。
- **可借鉴的具体业务逻辑**：① `hummingbot/connector/exchange/paper_trade/`（`paper_trade_exchange.pyx` + `market_config.py`）—— **本地模拟撮合器**如何复用真实行情流做 paper 成交，是"paper 不依赖交易所 demo 端点"的一条独立路径（对 ADR-0001 未决项"公共只读 vs 签名交易通道分离"有直接参考价值）；② `hummingbot/connector/budget_checker.py` —— **下单前的资金/额度预检**，把"余额够不够"从撮合中独立出来，我们的风险监控应照此分层；③ `connector/test_support/` 下 `mock_paper_exchange` / `mock_order_tracker` 展示了**如何为撮合逻辑写可复现测试**。
- **不可照搬的原因**：Cython（`.pyx`）+ 面向做市高频，与我们日线级别研究定位相差较远 → 只取分层语义。

### 6.3 freqtrade/freqtrade — GPL-3.0 ⚠️（只可参考思路，见 §7.1）
- 仓库 <https://github.com/freqtrade/freqtrade>；c1y=3294，2026.8 (2026-08-31)。**活跃度最高的可读参考。**
- **可借鉴的具体业务逻辑（思路层面，不可复制代码）**：① `freqtrade/optimize/analysis/` 下 **`lookahead.py` + `recursive.py`** —— 用"逐步截断历史重跑并比对信号"的方式**自动化检测前视偏差与递归依赖**。这是极少数公开实现的工程化前视检测，**QNT-30 应实现同类自检**；② `optimize/backtesting.py` 的退出优先级建模——`_get_close_rate_for_stoploss` / `_get_close_rate_for_roi` 分开计算止损与止盈成交价（`:597` / `:651`），解决"同一根 K 线内止损与止盈都触发时按哪个成交"这一日线回测核心歧义；③ `data/history/datahandlers/` 的 **`parquetdatahandler.py` / `featherdatahandler.py` / `arrowdatahandler.py` / `jsondatahandler.py` 多格式可插拔**（`idatahandler.py` 定义接口）——与我们 Parquet 基线同向。
- ⚠️ **GPL-3.0：以上仅可作为设计思路，后续卡不得引入其代码。**

### 6.4 其他
- **jesse-ai/jesse** <https://github.com/jesse-ai/jesse>（MIT，c1y=445）：PyPI `jesse` 3.2.0 `requires_python>=3.10`（py3 wheel）。加密回测+paper 一体，MIT 干净，可作为 §6.3 freqtrade 思路的**可复制替代品**（若需真的复用代码，优先看它而非 GPL 的 freqtrade）。**本阶段未深读，仅登记**。
- **ib-api-reloaded/ib_async** <https://github.com/ib-api-reloaded/ib_async>（BSD-2-Clause，**c1y=10**，release v2.0.1 2025-06-22）：IBKR paper 路径参考；**低活跃**，且 ADR-0001 备选段已 REJECT IBKR paper 作默认（需入金 live 账户 + Gateway 常驻 + 2FA）→ 仅登记。

## 7. 许可证单列区

### 7.1 GPL / AGPL / LGPL —— **只能参考思路，不可复制代码**

| 仓库 | SPDX | 传染性要点（非法律意见） | 本文引用范围 |
|---|---|---|---|
| [freqtrade/freqtrade](https://github.com/freqtrade/freqtrade) | **GPL-3.0** | 衍生作品须同样 GPL 开源 | §6.3 仅读**思路**：前视检测、止损/止盈成交价优先级、数据格式可插拔 |
| [freqtrade/frequi](https://github.com/freqtrade/frequi) | **GPL-3.0** | 同上 | §2.4 仅读前端**目录结构** |
| [kernc/backtesting.py](https://github.com/kernc/backtesting.py) | **AGPL-3.0** | 网络服务提供亦触发开源义务（`setup.py` 明写 `license='AGPL-3.0'`、`python_requires='>=3.9'`） | 仅登记：其 `backtesting/lib.py` 的 `crossover` 等信号辅助函数与 `_stats.py` 指标口径可作**概念对照**；**c1y=33、PyPI 无 3.14 classifier** → 本就不适合作对拍 |
| [OpenBB-finance/OpenBB](https://github.com/OpenBB-finance/OpenBB) | **AGPL-3.0**（GitHub 显示 `NOASSERTION`，`LICENSE` 正文第 3 行写明 "All files in this repository are licensed under the GNU Affero General Public License v3.0"） | 同上 | §3.4 仅读**两层 provider 结构**的设计 |
| [zotero/zotero](https://github.com/zotero/zotero) | **AGPL-3.0**（GitHub 显示 `NOASSERTION`，`COPYING` 写明 AGPLv3） | 同上 | §8 仅读条目/附件**数据模型思路** |
| [paperless-ngx/paperless-ngx](https://github.com/paperless-ngx/paperless-ngx) | **GPL-3.0** | 衍生作品须同样 GPL 开源 | §8 仅读文档入库/标签/全文检索的**产品语义** |
| [nautechsystems/nautilus_trader](https://github.com/nautechsystems/nautilus_trader) | **LGPL-3.0** | 弱传染：动态链接/未修改使用通常不传染，**但修改其源码则须以 LGPL 发布**；且本项目为 Rust+Python 混合，"链接"边界不清晰 | 仅登记：`crates/` 下 `backtest` / `execution` / `portfolio` / `risk` / `analysis` 的**模块切分**（c1y=5462，活跃度第一；PyPI `requires_python=<3.15,>=3.12` 且有 cp314 wheel）可作分层参考。**因 LGPL 边界判定成本高，本文不建议在 QNT-30 引入** |

> **对后续卡的硬性约束**：以上 7 个仓库的**代码**一律不得复制、改写或移植进 quantime。只允许阅读后用自己的实现表达同一业务语义。

### 7.2 非标准 / 附加条款许可 —— 需 owner 裁决

| 仓库 | 实际许可 | 要点 | 影响 |
|---|---|---|---|
| [polakowo/vectorbt](https://github.com/polakowo/vectorbt) | **Apache-2.0 + Commons Clause v1.0**（`LICENSE.md` 首行即 "Commons Clause License Condition v1.0"；正文 "License: Apache 2.0 with Commons Clause"；README 徽章 "Fair Code"） | Commons Clause **剥夺"Sell"权利**：不得提供"价值实质来源于该软件功能"的收费产品/服务（明确含 hosting 与 consulting/support） | **内部研究/对拍不受影响**（§5.1 首选结论成立）；**商业化 quantime 时需重新评估** → 列入待裁决 |
| [opendatalab/MinerU](https://github.com/opendatalab/MinerU) | **Apache-2.0 + 附加条款**（`LICENSE.md`："licensed under Apache License 2.0 and is subject to the additional terms below"，含 Affiliates 定义） | 附加条款正文本文**未逐条复核** | §8 中仅作登记；**若 QNT-32 真要引入，须先逐条读完附加条款并由 owner 裁决** |

### 7.3 宽松许可（MIT / Apache-2.0 / BSD）—— 可作依赖候选
lightweight-charts、KLineChart、perspective、dlt、ccxt、exchange_calendars、databento-python、yfinance、docling、unstructured、chroma、qlib、alphalens-reloaded、ta-lib-python、pandas-ta-classic、bt、zipline-reloaded、Lean、PyPortfolioOpt、Riskfolio-Lib、skfolio、quantstats、alpaca-py、hummingbot、jesse、ib_async、machine-learning-for-trading。
**注意：许可宽松 ≠ 建议引入。** 其中 qlib 因 **无 sdist 且 wheel 止于 cp312**（§4.1）在 3.14 下确定无法安装；alphalens-reloaded / zipline-reloaded / quantstats / yfinance / bukosabino-ta 则是**近一年近乎停更**，且**未声明 3.14（兼容性未验证，非"不支持"）** —— 本文对这几个的建议是"不进主依赖树、只读语义"，**依据是活跃度与集成成本，不是 3.14 判定**。

## 8. 研报资料模块（QNT-32）补充

- **docling-project/docling** <https://github.com/docling-project/docling>（**MIT**，c1y=790，v2.129.0 2026-09-18）：可借鉴 `docling/chunking/` 暴露的 **`HierarchicalChunker` / `HybridChunker` / `DocChunk` / `DocMeta`** —— **按文档结构（章节/表格）分块而非按固定字符数切分**，研报的表格与图注正是固定切分最容易破坏的部分。`docling/datamodel/document.py` 的统一文档模型可作为"研报 → 结构化条目"的建模参考。MIT + 高活跃 → 三者中**最适合真正引入**。
- **Unstructured-IO/unstructured** <https://github.com/Unstructured-IO/unstructured>（Apache-2.0，c1y=155，0.27.6 2026-09-14）：可借鉴其 element 类型体系（Title/NarrativeText/Table/ListItem 等）——**把 PDF 解析结果建模为带类型的元素序列**，便于后续按类型过滤。
- **opendatalab/MinerU** <https://github.com/opendatalab/MinerU>（Apache-2.0 + **附加条款**，见 §7.2；c1y=2887）：PDF → 结构化的效果参考，**引入前须先读完附加条款**。
- **zotero/zotero** <https://github.com/zotero/zotero>（**AGPL-3.0**，§7.1）：仅参考**思路**——条目（item）/ 附件（attachment）/ 标签 / 集合的数据模型，以及"同一文献多份附件与多处注释"的建模方式，正对应我们"一份研报 + 多个版本 + 多处摘录"。
- **paperless-ngx** <https://github.com/paperless-ngx/paperless-ngx>（**GPL-3.0**，§7.1）：仅参考**产品语义**——文档入库、标签体系、全文检索的组织方式。
- **chroma-core/chroma** <https://github.com/chroma-core/chroma>（Apache-2.0，c1y=1237）：若 QNT-32 需要向量检索则登记为候选；**本阶段不建议引入**——研报检索是否需要向量化尚未裁决，且 DuckDB 已有全文检索扩展可先行评估。
- **跨模块**：[stefan-jansen/machine-learning-for-trading](https://github.com/stefan-jansen/machine-learning-for-trading)（MIT，c1y=751）——书籍配套代码，**不是库**，但其 `data → factor → strategy → backtest` 的章节组织可作为 QNT-29/QNT-30 的**内容 checklist**。

## 9. 待裁决清单（交 planner / owner）

| # | 事项 | 建议 |
|---|---|---|
| 9.1 | vectorbt 的 **Commons Clause** 是否可接受（§7.2） | 作"对拍参照物"建议接受；商业化前需重新评估。若 owner 希望零附加条款，则**首选降为 bt（MIT）**，vectorbt 转备选 |
| 9.2 | QNT-30 对拍的**差异容忍度**与手续费/滑点模型统一口径 | 必须在 QNT-30 开工前定，否则对拍无意义（§5.2 末） |
| 9.3 | QNT-32 是否需要向量检索 | 未裁决前不引入 chroma；先评估 DuckDB 全文检索 |
| 9.4 | MinerU 附加条款是否逐条复核 | 若 QNT-32 要用则必须复核；否则不引入 |
| 9.5 | 本文 6 个模块的候选数 | 除"研报资料"外均达成"2–4 个"；研报资料列了 6 个（含 2 个 §7.1 只读项），因该模块成熟件分散，如需收敛请指示 |
