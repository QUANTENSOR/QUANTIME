# 加密市场特征、公开研报索引、常用因子与策略思路、Binance 公开只读端点

- 调研日期：2026-09-20；节点：本任务工作区（美国出口，**未使用代理、未注册账号、未持任何交易所 key**）
- 性质：只读文献与官方文档索引。**不写代码、不下载 bulk 数据、不调用需鉴权端点**。本文件不是数据源实测报告。
- 文件名按 2026-09-20 04:00 planner 派发（`crypto-market-and-binance-public-api.md`）；issue 正文曾写 `crypto-market-primer.md`，以派发评论为准，见文末「文档矛盾」。
- 与已有调研的关系：**只引用、不重复**。
  - 交易 API / testnet / 美国资格 / 骨架： [QNT-4](mention://issue/01a0adaa-9484-71a8-94c2-d1e564cae655)
  - CEX/DEX/链上数据源全景、美国节点可达性、Vision zip 实测： [QNT-5](mention://issue/01a0b28c-569c-7b18-b938-cd41ef7ea12e) `docs/research/data-sources-crypto.md`（该文件目前在 `agent/impl-d/777ad112ec0e`，**尚未合入**本卡基线 `d4b447e`）
- 边界：ADR-0001（paper/testnet only；公共只读摄取 D1.8）· ADR-0002（append-only / `ingestion_batch`）· owner 裁决 6A：DEX 只写一段「不做的原因」，不展开 DEX 数据源。
- 每条结论附可达 URL；本节点打不开或未读到原文的标 **未验证**。

## 0. 结论速览

| 结论 | 来源 |
|---|---|
| CEX 现货是即时交割的币对买卖；USDT-M 永续用资金费率把合约价锚向现货，无到期日；交割期货有到期结算 | 永续机制综述 <https://arxiv.org/abs/2212.06888> ；定价 <https://arxiv.org/abs/2310.11771> ；资金费率设计 <https://arxiv.org/abs/2506.08573> |
| 美国节点上 `api.binance.com` / `fapi.binance.com` 曾测得 HTTP 451；同一节点 `data.binance.vision` zip 与 `api.binance.us` 可达。本卡**不重测**，沿用 QNT-5 | QNT-5 `data-sources-crypto.md` §0 / §7 |
| 免费长期历史底座仍是 Vision zip（现货 K 线自 2017-08、U 本位 fundingRate 月文件、metrics 含 OI）。REST 资金费率/OI 统计窗口短（OI hist 官方 SDK 写 latest 1 month；basis/多空比 latest 30 days） | Vision README <https://github.com/binance/binance-public-data/blob/master/README.md> ；官方 SDK docstring <https://github.com/binance/binance-connector-python/blob/master/clients/derivatives_trading_usds_futures/src/binance_sdk_derivatives_trading_usds_futures/rest_api/api/market_data_api.py> |
| 现货公共 REST 限流按 **IP weight**，超限 429、反复则 418 IP ban（2 分钟–3 天）；现货 K 线 `1s`–`1M`、单次 limit 默认 500 最大 1000、weight 2 | <https://github.com/binance/binance-spot-api-docs/blob/master/rest-api.md> |
| 无 key 的现货行情镜像：`data-api.binance.vision` / `wss://data-stream.binance.vision`（不含 User Data Stream） | <https://github.com/binance/binance-spot-api-docs/blob/master/faqs/market_data_only.md> |
| 公开量化文献索引优先 arXiv `q-fin`、NBER papers、BIS publications；本节点 SSRN 首页/摘要页 HTTP 403，不把 SSRN 当可核入口 | 见 §3 |
| DEX / 链上永续不进本卡展开：owner 6A；数据源细节已在 QNT-5 | 派发评论；QNT-5 §1.9 / §1.12–1.14 |

## 1. 市场基础特征（CEX 现货 / USDT 永续 / 资金费率 / 交割）

本节描述机制，不是「在美国节点能连上哪家」。可达性、许可、历史深度见 QNT-5。

### 1.1 现货（spot）

- 标的是币对（如 `BTCUSDT`）：买方用报价资产买基础资产，成交即交割。Binance 现货公共 REST 的市场数据路径前缀为 `/api/v3/`（无签名的 ping/time/exchangeInfo/depth/trades/aggTrades/klines/ticker 等）。来源：<https://github.com/binance/binance-spot-api-docs/blob/master/rest-api.md>
- 现货 K 线字段（REST 与 Vision zip 同源）：Open time, Open, High, Low, Close, Volume, Close time, Quote asset volume, Number of trades, Taker buy base volume, Taker buy quote volume, Ignore。来源：<https://github.com/binance/binance-public-data/blob/master/README.md>
- 2025-01-01 起 Vision **现货**时间戳改为微秒。来源：同上 README「SPOT / Note」。
- 与股票日线的主要差异（机制层，非实证）：7×24、无官方开收盘集合竞价、停牌少见、交易单位与最小变动价位由 `exchangeInfo` 过滤器给出。过滤器细节见 <https://github.com/binance/binance-spot-api-docs/blob/master/filters.md>。**「加密波动率高于美股」的数值比较未在本卡核验，标未验证。**

### 1.2 USDT 本位永续（USDT-M perpetual）

- 永续期货（perpetual futures / perpetual swap）无到期日，用定期资金费把合约价拉向现货；多头在资金费为正时付给空头，反之亦然。来源：He, Manela, Ross, von Wachter, *Fundamentals of Perpetual Futures*, <https://arxiv.org/abs/2212.06888>
- 无摩擦市场可写无套利价格；有交易成本时是区间。摘要原文：实证上，加密市场相对**这些价格**（前文无套利价格 / 有交易成本时的界）的偏离大于传统外汇市场（traditional currency markets），且跨币种共动、随时间缩小——比较对象不是「永续–现货基差 vs 外汇远期基差」。来源：同上摘要（本卡读了 arXiv 摘要，**未下载 PDF 全文**）。
- 线性 / 反向 / quanto 永续的无套利表达与「使期货价与现货重合的资金费设定」见 Ackerer, Hugonnier, Jermann, *Perpetual Futures Pricing*, <https://arxiv.org/abs/2310.11771>
- Binance USDT-M 公共行情 host 文档写作 `fapi.binance.com`，路径 `/fapi/v1/*` 与 `/futures/data/*`。来源：官方 Python SDK <https://github.com/binance/binance-connector-python/blob/master/clients/derivatives_trading_usds_futures/src/binance_sdk_derivatives_trading_usds_futures/rest_api/api/market_data_api.py> 。QNT-5 在美国节点对 `fapi.binance.com` 测得 451，**本卡不把该 host 当可摄取入口**；历史用 Vision zip（QNT-5 §1.1）。
- 标记价 / 资金费快照：`GET /fapi/v1/premiumIndex`（有 symbol weight 1，无 symbol weight 10）。来源：同上 SDK。
- 当前 OI：`GET /fapi/v1/openInterest`，weight 1。来源：同上。
- **ADL 风险评级**（非历史序列）：`GET /fapi/v1/symbolAdlRisk`，约 30 分钟更新，weight 1。来源：同上。

### 1.3 资金费率（funding rate）

- 作用：把永续价钉在目标（通常是现货指数）上；费率设计不当则基差可持续偏离。来源：Kim & Park, *Designing funding rates for perpetual futures in cryptocurrency markets*, <https://arxiv.org/abs/2506.08573>
- Binance 历史资金费：`GET /fapi/v1/fundingRate`；与 `GET /fapi/v1/fundingInfo` **共享 500 次 / 5 分钟 / IP**。未传时间则最近 200 条，升序。来源：SDK docstring（链接同上 `market_data_api.py`）。
- 调整过 cap/floor 或 `fundingIntervalHours` 的合约：`GET /fapi/v1/fundingInfo`。来源：同上。
- Vision 月度 zip：`data/futures/um/monthly/fundingRate/<SYMBOL>/`（QNT-5 实测 BTCUSDT 2026-08 文件 93 行 ≈ 8h × 31 天）。**行数是 QNT-5 探针结果，本卡未重下 zip。** 来源：QNT-5 §7；前缀惯例见 <https://github.com/binance/binance-public-data>
- Binance 支持页「How funding rate works」本节点对 `www.binance.com/en/support/faq/...` 返回 HTTP 202 空体，**条款原文未验证**。

### 1.4 交割期货（delivery / dated futures）

- 与永续的差别：有到期日，到期按规则结算，一般**没有**定期 funding；临近交割时期货价被交割机制拉向现货，而不是靠资金费。机制对比见 <https://arxiv.org/abs/2212.06888> 引言。
- Binance **USD-M** 同时列 USD-M Futures 与交割型合约；连续合约 K 线 `GET /fapi/v1/continuousKlines`（`pair` + `contract_type`）。交割结算价：`GET /futures/data/delivery-price`，SDK 写 Weight 0。来源：`market_data_api.py`
- **COIN-M**（币本位）公共前缀 `dapi.binance.com` `/dapi/v1/*`。来源：<https://github.com/binance/binance-connector-python/blob/master/clients/derivatives_trading_coin_futures/src/binance_sdk_derivatives_trading_coin_futures/rest_api/api/market_data_api.py> ；字段差（K 线 Volume 为张、另有 Base asset volume）见 Vision README FUTURES 段 <https://github.com/binance/binance-public-data/blob/master/README.md>
- QNT-5：美国节点 `dapi` 未作为独立探针行列出；Vision `futures/cm` 与 um 同构。本卡不声称本节点 `dapi` 可达。

### 1.5 基差、持仓与成交量口径

- 基差（future vs spot / index）：`GET /futures/data/basis`，**仅最近 30 天**，Weight 0。来源：SDK。
- 账户多空比：`GET /futures/data/globalLongShortAccountRatio`，最近 30 天，IP 1000/5min。来源：SDK。
- 顶级账户/持仓多空比：`topLongShortAccountRatio` / `topLongShortPositionRatio`。来源：SDK。
- Taker 买卖量：USD-M `GET /futures/data/takerlongshortRatio`（30 天）；COIN-M 路径为 `GET /futures/data/takerBuySellVol`。来源：两个 `market_data_api.py`。
- OI 与成交量不可直接互换；OI 是时点未平仓合约数，可作市场活动/情绪的下界线索。来源：Giagkiozis & Said, *Reconciling Open Interest with Traded Volume in Perpetual Swaps*, <https://arxiv.org/abs/2310.14973>
- OI 历史统计 REST：`GET /futures/data/openInterestHist`，SDK 写 **latest 1 month**，IP 1000/5min，Weight 0。更长历史见 QNT-5 的 Vision `metrics`（5 分钟 OI + 多空比）。

### 1.6 DEX：一段「不做的原因」（owner 6A）

本卡**不**建 DEX 因子库、不列 DEX 端点清单。原因：planner 派发引用 owner 裁决 6A，DEX 只保留本段；QNT-5 已覆盖 Hyperliquid / dYdX v4 / GeckoTerminal / DefiLlama 等（美国节点部分 REST 200）。链上池从 CEX 永续的资金费、标记价、保险基金、ADL 机制均不可直接平移；若未来要做 DEX，应另开卡并先引用 QNT-5 §1.9 / §1.12–1.14，而不是复制到本文。

## 2. 常用因子与策略思路（分类 + 出处；不是回测结论）

下列只作**索引**：说明文献/文档里出现过的构造，不声称在 Binance 日线上显著。回测落地属于后续卡。日线研究粒度下，优先能从 Vision zip + 公共 REST 重建的字段。

### 2.1 动量 / 反转（价）

| 思路 | 文献怎么说 | 落地字段（Binance 公共） | 来源 |
|---|---|---|---|
| 截面动量 | 加密被当作独立资产类；在 63 个特征里，**只有由既往收益构成的金融因子**与显著多空有关，作者解读为投机驱动而非基本面定价 | 现货/永续已收盘 K 线 `Close` 的过去 N 日收益 | Baybutt, *Empirical Crypto Asset Pricing*, <https://arxiv.org/abs/2405.15716>（读摘要，未下 PDF） |
| 时间序列动量 | 同上面板里「univariate financial factors」覆盖滞后收益；具体形成期/持有期本卡**未从全文核对，未验证** | 同上 | 同上 |
| 短期反转 | 高换手、7×24 市场常被用来动机化日内/隔日反转；**本卡无独立实证，标未验证** | 1h/1d Close；taker buy 占比 | — |
| NBER 加密风险收益 | 标题 *Risks and Returns of Cryptocurrency* | — | <https://www.nber.org/papers/w24877>（标题已核；作者列表本卡 HTML 未解析出，**作者未验证**） |
| NBER 加密共同因子 | 标题 *Common Risk Factors in Cryptocurrency* | — | <https://www.nber.org/papers/w25882>（同上，**作者未验证**） |

### 2.2 波动率

| 思路 | 说明 | 落地字段 | 来源 |
|---|---|---|---|
| 已实现波动 | 日线 σ（对数收益标准差）或 Parkinson（High/Low） | K 线 H/L/C | K 线字段：Vision README |
| 波动率风险溢价 | 需要期权隐含波动；Binance Vision `option/` 在 QNT-5 记为 2023-10-23 停更。本卡不展开期权 | — | QNT-5 §1.1 |
| 波动率目标仓位 | 策略层：杠杆与资金费成本叠加后，波动目标会改变 funding 拖累；**无独立出处数字，未验证** | 日 σ + funding 序列 | — |

### 2.3 资金费率 / 基差 / 展期

| 思路 | 说明 | 落地字段 | 来源 |
|---|---|---|---|
| 资金费 carry | 费率为正时空头收取、多头支付；费率是钉住机制不是「情绪指标」本身 | `fundingRate` 历史；`premiumIndex` | <https://arxiv.org/abs/2212.06888> <https://arxiv.org/abs/2506.08573> ；端点 SDK |
| 基差 / 溢价 | 标记价 vs 指数；SDK `basis` 仅 30 天，长历史用 Vision `premiumIndexKlines` / `markPriceKlines`（QNT-5 列过 S3 前缀） | `premiumIndex`、`basis`、Vision kline 变体 | SDK；QNT-5 §1.1 |
| 交割展期 | 近月 vs 远月；永续无展期，这是**交割合约**的逻辑 | `continuousKlines`、`delivery-price` | SDK |

### 2.4 持仓量（OI）与多空比

| 思路 | 说明 | 落地字段 | 来源 |
|---|---|---|---|
| OI 水平 / 变化 | OI 是未平仓合约存量，与成交量不同口径 | 当前 `openInterest`；hist `openInterestHist`（1 个月）；长历史 Vision `metrics` | SDK；<https://arxiv.org/abs/2310.14973> ；QNT-5 |
| 多空比 | 账户数比 ≠ 持仓量比 | `globalLongShortAccountRatio`、`topLongShort*` | SDK |
| 拥挤 / ADL | 清算瀑布与 ADL 评级 | `symbolAdlRisk`（快照） | SDK |

### 2.5 成交量、主动买入、微观结构

| 思路 | 说明 | 落地字段 | 来源 |
|---|---|---|---|
| 量价 | 日 Volume / Quote asset volume | K 线 | Vision README |
| Taker buy 占比 | 主买 vs 主卖 | K 线 taker buy 两列；期货 `takerlongshortRatio` | Vision README；SDK |
| 盘口 | 现货 depth weight 随 limit 升至 250；期货 depth 档位 5–1000 | `/api/v3/depth`、`/fapi/v1/depth` | spot rest-api.md；SDK |
| 强平 | REST 无长期强平历史；QNT-5：Vision `liquidationSnapshot` 前缀空，长期靠付费或自采 WS | 本卡不列 WS 强平为「历史因子源」 | QNT-5 §0 / §1.1 |

### 2.6 链上因子

本卡按 6A **不展开**。若引用，指向 QNT-5 的 DefiLlama TVL、GeckoTerminal 池 OHLCV、blockchain.com / mempool.space，并遵守「只 insert 快照 + `fetched_at`」（TVL 会重算）。

### 2.7 策略构建常见思路（仍是索引）

1. **日线截面多空（加密「股票式」）**：在可交易永续或现货宇宙上用滞后收益排序，dollar-neutral。动机：<https://arxiv.org/abs/2405.15716> 摘要。执行层需处理资金费、最小下单、美国节点不可用的 REST（QNT-5）。
2. **资金费 carry / 基差收敛**：持有收取资金费的一侧并现货对冲。定价框架：<https://arxiv.org/abs/2212.06888> <https://arxiv.org/abs/2310.11771>。容量/挤兑 **未验证**。
3. **波动率缩放趋势**：时间序列动量 × 逆波动率仓位。动量腿见 2.1；波动腿用已实现 σ。组合参数 **未验证**。
4. **交割日历 / 展期**：仅适用于有到期的合约；永续不适用。端点见 1.4。
5. **OI 确认的突破**：价格突破叠加 OI 上升。OI 口径警告：<https://arxiv.org/abs/2310.14973>。规则本身 **未验证**。

以上策略都不得在 agent 环境走主网下单（ADR-0001）。

## 3. 公开量化研报索引（只列元数据源，不下载全文）

本卡**不保存 PDF**。下面是可检索入口；列出的单篇仅当本节点 GET 200 且标题核对过。

### 3.1 索引入口

| 入口 | 用途 | 本节点 | URL |
|---|---|---|---|
| arXiv 检索 | 全文预印本；适合 perp / funding / crypto factor | 200 | <https://arxiv.org/search/?query=cryptocurrency+momentum&searchtype=all&source=header> ；分类最近 <https://arxiv.org/list/q-fin.TR/recent> ；API <https://export.arxiv.org/api/query?search_query=all:%22perpetual+futures%22> |
| NBER papers | 工作论文题录 | 200 | 检索 <https://www.nber.org/search?page=1&perPage=50&q=cryptocurrency> |
| BIS publications | 监管/宏观加密 | 200（旧 `/publ/work765.htm` 重定向到新 publications 路径） | <https://www.bis.org/publications/working-paper-765-beyond-doomsday-economics-of-proof-of-work-cryptocurrencies> |
| IDEAS/RePEc | 题录聚合 | 站点 200；`/k/cryptocurrency.html` **404** | <https://ideas.repec.org/> ；NBER 系列 <https://ideas.repec.org/s/nbr/nberwo.html> |
| SSRN | 金融预印本常用 | **403**（首页与 `abstract_id=2965436` 均失败） | 不作为本卡可核来源 |

### 3.2 已核标题的单篇（元数据）

| 标题 | 标识 | 作者（来自 arXiv API name 字段） | URL |
|---|---|---|---|
| Fundamentals of Perpetual Futures | arXiv:2212.06888 | Songrun He, Asaf Manela, Omri Ross, Victor von Wachter | <https://arxiv.org/abs/2212.06888> |
| Perpetual Futures Pricing | arXiv:2310.11771 | Damien Ackerer, Julien Hugonnier, Urban Jermann | <https://arxiv.org/abs/2310.11771> |
| Reconciling Open Interest with Traded Volume in Perpetual Swaps | arXiv:2310.14973 | Ioannis Giagkiozis, Emilio Said | <https://arxiv.org/abs/2310.14973> |
| Designing funding rates for perpetual futures in cryptocurrency markets | arXiv:2506.08573 | Jaehyun Kim, Hyungbin Park | <https://arxiv.org/abs/2506.08573> |
| Empirical Crypto Asset Pricing | arXiv:2405.15716 | Adam Baybutt | <https://arxiv.org/abs/2405.15716> |
| Risks and Returns of Cryptocurrency | NBER w24877 | **作者未验证**（页面 title 已核） | <https://www.nber.org/papers/w24877> |
| Common Risk Factors in Cryptocurrency | NBER w25882 | **作者未验证** | <https://www.nber.org/papers/w25882> |

检索备忘（2026-09-20，arXiv API）：`all:"perpetual futures"` 还返回 *Agent-Based Simulation of a Perpetual Futures Market* (2501.09404)、*Slippage-at-Risk (SaR)* (2603.09164) 等，未逐篇读摘要，不收入上表。

## 4. Binance 公开只读端点清单

约束：只列 **无需 API key** 的市场数据。交易、账户、User Data Stream、demo 下单不在此列（见 QNT-4 / ADR-0001）。权重数字来自官方 GitHub 文档或官方 SDK docstring；`developers.binance.com` HTML 本节点常 202 空体，故**不把该 SPA 当核验页**，改引 GitHub。

### 4.1 现货 REST（文档基址 `api.binance.com`；无 key 镜像 `data-api.binance.vision`）

限流（对所有 REST 路径）：

- `/api/v3/exchangeInfo` 的 `rateLimits` 含 `RAW_REQUESTS` / `REQUEST_WEIGHT` / `ORDERS`。
- 超限 HTTP 429；反复不退避 → 418 IP ban，时长 2 分钟至 3 天；418/429 带 `Retry-After`（秒）。
- 限流按 **IP 不按 key**；响应头 `X-MBX-USED-WEIGHT-(intervalNum)(intervalLetter)`。
- 来源：<https://github.com/binance/binance-spot-api-docs/blob/master/rest-api.md> 「LIMITS」。

无 key 镜像列出的路径（完整列表以 FAQ 为准）：`ping` `time` `exchangeInfo` `depth` `trades` `aggTrades` `klines` `uiKlines` `avgPrice` `ticker` `ticker/24hr` `ticker/bookTicker` `ticker/price`。来源：<https://github.com/binance/binance-spot-api-docs/blob/master/faqs/market_data_only.md> 。本卡对 `https://data-api.binance.vision/api/v3/ping` HEAD/GET **200**。

| 方法 | 路径 | weight | 周期 / limit / 字段要点 |
|---|---|---|---|
| GET | `/api/v3/ping` | 1 | 连通性 |
| GET | `/api/v3/time` | 1 | `serverTime` |
| GET | `/api/v3/exchangeInfo` | 20 | 交易规则、`rateLimits`、过滤器 |
| GET | `/api/v3/depth` | limit 1–100→5；101–500→25；501–1000→50；1001–5000→250 | 默认 100，最大 5000 |
| GET | `/api/v3/trades` | 25 | 默认 500，最大 1000 |
| GET | `/api/v3/historicalTrades` | 25 | 文档列为市场数据；FAQ 的 vision 镜像**未列入**此路径。是否可无 key：**未验证** |
| GET | `/api/v3/aggTrades` | 4 | 默认 500，最大 1000 |
| GET | `/api/v3/klines` | 2 | interval：`1s,1m,3m,5m,15m,30m,1h,2h,4h,6h,8h,12h,1d,3d,1w,1M`；limit 默认 500 最大 1000；12 字段见 §1.1；未传时间返回最近 K 线 |
| GET | `/api/v3/uiKlines` | 2 | 同 klines，面向画图 |
| GET | `/api/v3/avgPrice` | 2 | 当前均价 |
| GET | `/api/v3/ticker/24hr` | 1 个 symbol→2；省略 symbol 更重（见文档表） | 24h 滚动 |
| GET | `/api/v3/ticker/price` | 1 个 symbol→2 | 最新成交价 |
| GET | `/api/v3/ticker/bookTicker` | 见文档表 | 最优买卖 |
| GET | `/api/v3/ticker` | 见文档 | 滚动窗口统计 |

K 线未收盘：WS 载荷字段 `k.x`；REST 最后一根是否未收盘需用 close time 与服务器时间判断。WS：<https://github.com/binance/binance-spot-api-docs/blob/master/web-socket-streams.md>

QNT-5：本卡基线节点对 `api.binance.com` 现货 K 线 **451**。摄取应优先 Vision zip +（若合规）`data-api.binance.vision` / `api.binance.us`，不要假设 `api.binance.com` 可用。

### 4.2 现货 WebSocket 行情（只读）

- 主网：`wss://stream.binance.com:9443` 或 `:443`；只行情：`wss://data-stream.binance.vision`（无 User Data）。
- 单连接最多 1024 streams；控制消息 5 条/秒；**每 IP 每 5 分钟最多 300 次连接尝试**；连接约 24h 断开。
- 服务器约 20s ping，1 分钟内未 pong 断开。
- K 线 stream：`<symbol>@kline_<interval>`，interval 同 REST（`1s`–`1M`）；`1s` 更新 1000ms，其余 2000ms；`k.x` 是否收盘。
- 来源：<https://github.com/binance/binance-spot-api-docs/blob/master/web-socket-streams.md> ；vision 镜像：market_data_only FAQ。

常驻 WS 是否允许：QNT-5 待裁决清单第 9 项，本卡不裁。

### 4.3 USD-M 期货 REST（文档 host `fapi.binance.com`）

权重与窗口摘自官方 SDK docstring，commit `506e738ade8b53056db177a37189077de1004ff1`（与 verify-b 引用同一文件）。QNT-5 美国节点对该 host **451**，下表是**接口契约**不是可达性保证。

SDK 文件：<https://github.com/binance/binance-connector-python/blob/506e738ade8b53056db177a37189077de1004ff1/clients/derivatives_trading_usds_futures/src/binance_sdk_derivatives_trading_usds_futures/rest_api/api/market_data_api.py>

K 线类 weight（`klines` L683–690 / `continuousKlines` L404–411 / `indexPriceKlines` L611 / `markPriceKlines` L859 / `premiumIndexKlines` L1147，五处同一张 LIMIT 表）：

| LIMIT | weight |
|---|---|
| [1,100) | 1 |
| [100,500) | 2 |
| [500,1000] | 5 |
| >1000 | 10 |

| 方法 | 路径 | 限流 / 窗口（SDK 原文） | 用途 | SDK 锚点 |
|---|---|---|---|---|
| GET | `/fapi/v1/ping` | Weight(IP): 1 | 连通 | [L1637](https://github.com/binance/binance-connector-python/blob/506e738ade8b53056db177a37189077de1004ff1/clients/derivatives_trading_usds_futures/src/binance_sdk_derivatives_trading_usds_futures/rest_api/api/market_data_api.py#L1637) |
| GET | `/fapi/v1/time` | Weight(IP): 1 | 时间 | [L249](https://github.com/binance/binance-connector-python/blob/506e738ade8b53056db177a37189077de1004ff1/clients/derivatives_trading_usds_futures/src/binance_sdk_derivatives_trading_usds_futures/rest_api/api/market_data_api.py#L249) |
| GET | `/fapi/v1/exchangeInfo` | Weight(IP): 1 | 合约规则 | [L477](https://github.com/binance/binance-connector-python/blob/506e738ade8b53056db177a37189077de1004ff1/clients/derivatives_trading_usds_futures/src/binance_sdk_derivatives_trading_usds_futures/rest_api/api/market_data_api.py#L477) |
| GET | `/fapi/v1/depth` | Limit 5/10/20/50→2；100→5；500→10；1000→20 | 盘口 | [L1092](https://github.com/binance/binance-connector-python/blob/506e738ade8b53056db177a37189077de1004ff1/clients/derivatives_trading_usds_futures/src/binance_sdk_derivatives_trading_usds_futures/rest_api/api/market_data_api.py#L1092) |
| GET | `/fapi/v1/trades` | Weight(IP): 5 | 最近成交 | [L1342](https://github.com/binance/binance-connector-python/blob/506e738ade8b53056db177a37189077de1004ff1/clients/derivatives_trading_usds_futures/src/binance_sdk_derivatives_trading_usds_futures/rest_api/api/market_data_api.py#L1342) |
| GET | `/fapi/v1/historicalTrades` | **Weight(IP): 200** | 旧成交（是否无 key **未在本卡验证**） | [L928](https://github.com/binance/binance-connector-python/blob/506e738ade8b53056db177a37189077de1004ff1/clients/derivatives_trading_usds_futures/src/binance_sdk_derivatives_trading_usds_futures/rest_api/api/market_data_api.py#L928) |
| GET | `/fapi/v1/aggTrades` | Weight(IP): 20；仅约 48h | 聚合成交 | [L336](https://github.com/binance/binance-connector-python/blob/506e738ade8b53056db177a37189077de1004ff1/clients/derivatives_trading_usds_futures/src/binance_sdk_derivatives_trading_usds_futures/rest_api/api/market_data_api.py#L336) |
| GET | `/fapi/v1/klines` | 见上 LIMIT 表 | 成交价 K 线 | [L683](https://github.com/binance/binance-connector-python/blob/506e738ade8b53056db177a37189077de1004ff1/clients/derivatives_trading_usds_futures/src/binance_sdk_derivatives_trading_usds_futures/rest_api/api/market_data_api.py#L683) |
| GET | `/fapi/v1/continuousKlines` | 见上 LIMIT 表 | 连续合约 K 线 | [L404](https://github.com/binance/binance-connector-python/blob/506e738ade8b53056db177a37189077de1004ff1/clients/derivatives_trading_usds_futures/src/binance_sdk_derivatives_trading_usds_futures/rest_api/api/market_data_api.py#L404) |
| GET | `/fapi/v1/indexPriceKlines` | 见上 LIMIT 表 | 指数 K | [L611](https://github.com/binance/binance-connector-python/blob/506e738ade8b53056db177a37189077de1004ff1/clients/derivatives_trading_usds_futures/src/binance_sdk_derivatives_trading_usds_futures/rest_api/api/market_data_api.py#L611) |
| GET | `/fapi/v1/markPriceKlines` | 见上 LIMIT 表 | 标记价 K | [L859](https://github.com/binance/binance-connector-python/blob/506e738ade8b53056db177a37189077de1004ff1/clients/derivatives_trading_usds_futures/src/binance_sdk_derivatives_trading_usds_futures/rest_api/api/market_data_api.py#L859) |
| GET | `/fapi/v1/premiumIndexKlines` | 见上 LIMIT 表 | 溢价指数 K | [L1147](https://github.com/binance/binance-connector-python/blob/506e738ade8b53056db177a37189077de1004ff1/clients/derivatives_trading_usds_futures/src/binance_sdk_derivatives_trading_usds_futures/rest_api/api/market_data_api.py#L1147) |
| GET | `/fapi/v1/premiumIndex` | **1** with symbol, **10** without | 标记价 + 资金费快照 | [L816](https://github.com/binance/binance-connector-python/blob/506e738ade8b53056db177a37189077de1004ff1/clients/derivatives_trading_usds_futures/src/binance_sdk_derivatives_trading_usds_futures/rest_api/api/market_data_api.py#L816) |
| GET | `/fapi/v1/ticker/24hr` | 单 symbol **1**；省略 symbol **40** | 24h | [L1674](https://github.com/binance/binance-connector-python/blob/506e738ade8b53056db177a37189077de1004ff1/clients/derivatives_trading_usds_futures/src/binance_sdk_derivatives_trading_usds_futures/rest_api/api/market_data_api.py#L1674) |
| GET | `/fapi/v1/ticker/price` | 单 symbol 1；省略 2 | 最新价 | [L1487](https://github.com/binance/binance-connector-python/blob/506e738ade8b53056db177a37189077de1004ff1/clients/derivatives_trading_usds_futures/src/binance_sdk_derivatives_trading_usds_futures/rest_api/api/market_data_api.py#L1487) |
| GET | `/fapi/v2/ticker/price` | 单 symbol 1；省略 2 | 最新价 v2 | [L1529](https://github.com/binance/binance-connector-python/blob/506e738ade8b53056db177a37189077de1004ff1/clients/derivatives_trading_usds_futures/src/binance_sdk_derivatives_trading_usds_futures/rest_api/api/market_data_api.py#L1529) |
| GET | `/fapi/v1/ticker/bookTicker` | 单 symbol **2**；省略 **5** | 最优买卖 | [L1444](https://github.com/binance/binance-connector-python/blob/506e738ade8b53056db177a37189077de1004ff1/clients/derivatives_trading_usds_futures/src/binance_sdk_derivatives_trading_usds_futures/rest_api/api/market_data_api.py#L1444) |
| GET | `/fapi/v1/openInterest` | Weight(IP): 1 | 当前 OI | [L979](https://github.com/binance/binance-connector-python/blob/506e738ade8b53056db177a37189077de1004ff1/clients/derivatives_trading_usds_futures/src/binance_sdk_derivatives_trading_usds_futures/rest_api/api/market_data_api.py#L979) |
| GET | `/fapi/v1/fundingRate` | 与 fundingInfo 共享 **500/5min/IP**（未写 REQUEST_WEIGHT 数字） | 资金费历史 | [L517](https://github.com/binance/binance-connector-python/blob/506e738ade8b53056db177a37189077de1004ff1/clients/derivatives_trading_usds_futures/src/binance_sdk_derivatives_trading_usds_futures/rest_api/api/market_data_api.py#L517) |
| GET | `/fapi/v1/fundingInfo` | Weight **0**；计入上面共享额度 | cap/floor/间隔 | [L567](https://github.com/binance/binance-connector-python/blob/506e738ade8b53056db177a37189077de1004ff1/clients/derivatives_trading_usds_futures/src/binance_sdk_derivatives_trading_usds_futures/rest_api/api/market_data_api.py#L567) |
| GET | `/fapi/v1/symbolAdlRisk` | Weight(IP): 1 | ADL 评级快照 | [L99](https://github.com/binance/binance-connector-python/blob/506e738ade8b53056db177a37189077de1004ff1/clients/derivatives_trading_usds_futures/src/binance_sdk_derivatives_trading_usds_futures/rest_api/api/market_data_api.py#L99) |
| GET | `/fapi/v1/indexInfo` | Weight(IP): 1 | 指数成分说明 | [L286](https://github.com/binance/binance-connector-python/blob/506e738ade8b53056db177a37189077de1004ff1/clients/derivatives_trading_usds_futures/src/binance_sdk_derivatives_trading_usds_futures/rest_api/api/market_data_api.py#L286) |
| GET | `/fapi/v1/constituents` | Weight(IP): 2 | 指数成分 | [L1260](https://github.com/binance/binance-connector-python/blob/506e738ade8b53056db177a37189077de1004ff1/clients/derivatives_trading_usds_futures/src/binance_sdk_derivatives_trading_usds_futures/rest_api/api/market_data_api.py#L1260) |
| GET | `/fapi/v1/insuranceBalance` | Weight(IP): 1 | 保险基金快照 | [L1303](https://github.com/binance/binance-connector-python/blob/506e738ade8b53056db177a37189077de1004ff1/clients/derivatives_trading_usds_futures/src/binance_sdk_derivatives_trading_usds_futures/rest_api/api/market_data_api.py#L1303) |
| GET | `/fapi/v1/assetIndex` | 单 symbol **1**；省略 **10** | 多资产指数；SDK 注 CM-UM Integration 2026-06-30 | [L139](https://github.com/binance/binance-connector-python/blob/506e738ade8b53056db177a37189077de1004ff1/clients/derivatives_trading_usds_futures/src/binance_sdk_derivatives_trading_usds_futures/rest_api/api/market_data_api.py#L139) |
| GET | `/fapi/v1/tradingSchedule` | Weight(IP): 5 | 交易日历 | [L1875](https://github.com/binance/binance-connector-python/blob/506e738ade8b53056db177a37189077de1004ff1/clients/derivatives_trading_usds_futures/src/binance_sdk_derivatives_trading_usds_futures/rest_api/api/market_data_api.py#L1875) |
| GET | `/futures/data/openInterestHist` | Weight(IP): 0；**latest 1 month**；IP 1000/5min | OI 统计 | [L1026](https://github.com/binance/binance-connector-python/blob/506e738ade8b53056db177a37189077de1004ff1/clients/derivatives_trading_usds_futures/src/binance_sdk_derivatives_trading_usds_futures/rest_api/api/market_data_api.py#L1026) |
| GET | `/futures/data/topLongShortAccountRatio` | docstring **未写 Weight(IP)**；**30 天**；IP 1000/5min | 顶级账户多空 | [L1734](https://github.com/binance/binance-connector-python/blob/506e738ade8b53056db177a37189077de1004ff1/clients/derivatives_trading_usds_futures/src/binance_sdk_derivatives_trading_usds_futures/rest_api/api/market_data_api.py#L1734) |
| GET | `/futures/data/topLongShortPositionRatio` | Weight(IP): 0；**30 天**；IP 1000/5min | 顶级持仓多空 | [L1805](https://github.com/binance/binance-connector-python/blob/506e738ade8b53056db177a37189077de1004ff1/clients/derivatives_trading_usds_futures/src/binance_sdk_derivatives_trading_usds_futures/rest_api/api/market_data_api.py#L1805) |
| GET | `/futures/data/globalLongShortAccountRatio` | Weight(IP): 0；**30 天**；IP 1000/5min | 全局多空 | [L754](https://github.com/binance/binance-connector-python/blob/506e738ade8b53056db177a37189077de1004ff1/clients/derivatives_trading_usds_futures/src/binance_sdk_derivatives_trading_usds_futures/rest_api/api/market_data_api.py#L754) |
| GET | `/futures/data/takerlongshortRatio` | Weight(IP): 0；**30 天**；IP 1000/5min | Taker 买卖 | [L1576](https://github.com/binance/binance-connector-python/blob/506e738ade8b53056db177a37189077de1004ff1/clients/derivatives_trading_usds_futures/src/binance_sdk_derivatives_trading_usds_futures/rest_api/api/market_data_api.py#L1576) |
| GET | `/futures/data/basis` | Weight(IP): 0；**30 天** | 基差 | [L182](https://github.com/binance/binance-connector-python/blob/506e738ade8b53056db177a37189077de1004ff1/clients/derivatives_trading_usds_futures/src/binance_sdk_derivatives_trading_usds_futures/rest_api/api/market_data_api.py#L182) |
| GET | `/futures/data/delivery-price` | Weight(IP): 0 | 交割结算价 | [L1214](https://github.com/binance/binance-connector-python/blob/506e738ade8b53056db177a37189077de1004ff1/clients/derivatives_trading_usds_futures/src/binance_sdk_derivatives_trading_usds_futures/rest_api/api/market_data_api.py#L1214) |

USD-M K 线 interval 枚举以 SDK `KlineCandlestickDataIntervalEnum` 为准（本卡未把枚举文件全文展开；与现货相比期货 REST **通常无 1s**——**未在本卡打开枚举文件核实，标未验证**）。

### 4.4 COIN-M REST（文档 host `dapi.binance.com`）

与 USD-M 同构的公开路径（`/dapi/v1/ping|time|exchangeInfo|depth|trades|aggTrades|klines|continuousKlines|indexPriceKlines|markPriceKlines|premiumIndexKlines|premiumIndex|openInterest|fundingRate|fundingInfo|ticker/*`）以及 `/futures/data/*` 的 basis / OI hist / 多空比 / `takerBuySellVol`。来源：coin futures `market_data_api.py`。美国节点可达性 **未在本卡测**。

### 4.5 `data.binance.vision` 归档（无 key、按文件）

入口：<https://data.binance.vision/> （本卡 HEAD 200）  
说明与字段：<https://github.com/binance/binance-public-data/blob/master/README.md>  
许可：该仓库 LICENSE **MIT**（代码/文档仓库许可；**行情数据再分发仍受 Binance ToU 约束，ToU 条号本卡未验证**，同 QNT-5）。

发布节奏：日文件次日；月文件每月第一个周一。全部 symbol。每 zip 旁有 `.CHECKSUM`（sha256）。**上游归档可被替换**：README Updates 记录替换日期、changelog zip、以及被替换文件与替换文件的 checksum（已列 2022-04-21、2022-08-08）。Checksum 只校验某一版内容，**不保证同一 URL 永久不变**。来源：<https://github.com/binance/binance-public-data/blob/5c7f3197591c0d54d85dc43066226bc4c671d47a/README.md#updates>

README **明文**的类别：

| 市场 | 周期 | 类别 | 字段（README 表） | K 线周期 |
|---|---|---|---|---|
| SPOT | daily / monthly | `aggTrades` | agg id, price, qty, first/last trade id, timestamp, buyer maker, best match | — |
| SPOT | daily / monthly | `klines` | 与 REST klines 12 列相同 | `1s,1m,3m,5m,15m,30m,1h,2h,4h,6h,8h,12h,1d,3d,1w,1mo`（文件名用 `1mo` 而非 `1M`） |
| SPOT | daily / monthly | `trades` | id, price, qty, quoteQty, time, isBuyerMaker, isBestMatch | — |
| USD-M / COIN-M | daily / monthly | `aggTrades` | 无「best match」列 | — |
| USD-M | daily / monthly | `klines` | 同现货 12 列（来自 `/fapi/v1/klines`） | README：「All kline intervals are supported」对现货列出；期货 interval 集合 **README 未单独列表，未验证是否含 1s** |
| COIN-M | daily / monthly | `klines` | Open time… Volume（张）, Close time, Base asset volume, Number of trades, Taker buy volume, Taker buy base, Ignore | 同上 |
| USD-M / COIN-M | daily / monthly | `trades` | UM：id,price,qty,quoteQty,time,isBuyerMaker；CM：id,price,qty,baseQty,time,isBuyerMaker | — |

下载例（README，**本卡未执行 wget/curl 落盘**）：

`https://data.binance.vision/data/spot/monthly/klines/ADABKRW/1h/ADABKRW-1h-2020-08.zip`

QNT-5 在 S3 列表中**额外**见到、但 README 未列的前缀：`bookDepth`、`bookTicker`、`metrics`、`fundingRate`、`indexPriceKlines`、`markPriceKlines`、`premiumIndexKlines`、`option/`（停更）、空的 `liquidationSnapshot`。这是 QNT-5 已报的文档矛盾，本卡只引用。

Vision **无声明 REST 式 IP weight**。QNT-5 探针下载月 zip 成功（本卡不重下）。

### 4.6 对 ADR-0002 的含义（不实施，只记账）

- Vision 上游 zip **不是**不可变快照：同 URL 可被官方替换（README Updates）。重放必须依赖**自行保留的本地副本**，并在 `ingestion_batch` 记录**下载当时**的 checksum / `content_sha256`；不能把上游 URL 当固定快照。QNT-5 仍有「zip 天然不可变」旧表述，只报不改上游。
- REST 最后一根未收盘 K 线不应作为最终事实行；WS `k.x=false` 同理。
- `openInterestHist` / `basis` 等短窗口接口只能作增量，回放底座仍是**本地留存的** zip（QNT-5 方案 A），不是实时去拉 Vision URL。
- `developers.binance.com` 与 GitHub 文档并存；本卡以 GitHub 为准，因为 SPA 本节点 202 空体。

## 5. 未验证 / 文档矛盾（只报不修）

**未验证**

- Binance.com ToU 禁止再分发行情的条款号与原文（美国节点 www.binance.com 支持页 202）。
- NBER w24877 / w25882 的作者姓名（title 已核）。
- `GET /api/v3/historicalTrades`、期货 `historicalTrades` 在无 key 时是否可用。
- 期货 REST K 线是否包含 `1s`。
- `dapi.binance.com` 本节点可达性。
- `data-api.binance.vision` 是否覆盖期货（FAQ 只列现货 `/api/v3/*`）。
- 加密相对美股的波动率倍数等经验数字。
- 动量形成期/持有期的常规参数。
- SSRN 题录（本节点 403）。

**文档矛盾（发现即报，不改上游）**

1. **本卡文件名**：issue 正文 `docs/research/crypto-market-primer.md` vs 04:00 派发 `docs/research/crypto-market-and-binance-public-api.md`。按派发落盘。
2. **Vision README vs S3**：README 只写 aggTrades/klines/trades；QNT-5 在 S3 看到 fundingRate/metrics/bookDepth 等。沿用 QNT-5 §6。
3. **现货 K 线 interval 拼写**：REST/WS 用 `1M`，Vision 文件名用 `1mo`。来源：rest-api.md vs public-data README。
4. **现货时间戳单位**：Vision 称 2025-01-01 起现货微秒；spot WS 默认毫秒，微秒要 `timeUnit=MICROSECOND`。混用会错位。
5. **QNT-5 加密调研未在 main `d4b447e`**：本卡只能文字引用，无法在同分支打开该 md。
6. **AGENTS.md 产品句 vs 加密范围**：仓库 `AGENTS.md` 写「美股 + 美股期权 + 加密合约」；QNT-4/5/本卡同时覆盖现货数据。只报。
7. **`developers.binance.com` vs GitHub**：connector README 指向 developers.binance.com，本节点该域 202 空体；权重以 GitHub rest-api.md / SDK docstring 为准。
8. **ADR-0001 D1.7 allowlist vs 公共行情 host**：verify 旧意见（ADR 文末未决项）指出 demo 行情与主网 host 冲突；QNT-22 拟把「行情公共只读」从主网 host 禁令里豁免。本卡不改 ADR。

## 6. 来源表（本卡实际打开过）

- <https://github.com/binance/binance-public-data/blob/master/README.md>
- <https://data.binance.vision/>
- <https://github.com/binance/binance-spot-api-docs/blob/master/rest-api.md>
- <https://github.com/binance/binance-spot-api-docs/blob/master/faqs/market_data_only.md>
- <https://github.com/binance/binance-spot-api-docs/blob/master/web-socket-streams.md>
- <https://github.com/binance/binance-connector-python/blob/master/clients/derivatives_trading_usds_futures/src/binance_sdk_derivatives_trading_usds_futures/rest_api/api/market_data_api.py>
- <https://github.com/binance/binance-connector-python/blob/master/clients/derivatives_trading_coin_futures/src/binance_sdk_derivatives_trading_coin_futures/rest_api/api/market_data_api.py>
- <https://data-api.binance.vision/api/v3/ping>
- <https://arxiv.org/abs/2212.06888> <https://arxiv.org/abs/2310.11771> <https://arxiv.org/abs/2310.14973> <https://arxiv.org/abs/2506.08573> <https://arxiv.org/abs/2405.15716>
- <https://www.nber.org/papers/w24877> <https://www.nber.org/papers/w25882>
- <https://www.bis.org/publications/working-paper-765-beyond-doomsday-economics-of-proof-of-work-cryptocurrencies>
- QNT-5 `docs/research/data-sources-crypto.md`（其他 worktree，未合入本分支）
