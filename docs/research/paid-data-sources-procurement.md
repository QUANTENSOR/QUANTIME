# 付费数据源采购清单（只列不买）

- 调研日期 / 访问日期（凡未另注）：**2026-09-23**
- 节点：本任务工作区（美国出口）。**未使用代理、未注册任何账号、未付费、未申请 trial、未生成任何 key。** 只做公开 GET。
- 任务：QNT-46；基线 `main` ≥ `11006e3`（本工作树 `cddb1b0`）。
- 性质：采购候选清单。owner 采购完成后凭据入 vault `quant-dev`，再由后续卡接入。本文**不裁、不买**。
- 边界：ADR-0001（paper / 不持实盘凭据）· ADR-0002（append-only；许可驱动删除走 tombstone）· ADR-0003 §4.1（`data/raw` + `data/lake` 双份）。
- 缺官方原文处写 **未找到官方资料**，不推测。许可结论只引用本轮 GET 到的条款句子 + URL + 章节号。

## 来源说明（PR #1 / QNT-5 五项 REJECT 的处置）

PR #1（`agent/impl-d/777ad112ec0e`，HEAD `6d8039c`，7 篇 `data-sources-*.md` + 13 探针）verify-c 于 2026-09-18 REJECT 五项，作者 agent 已归档。本卡**不返修、不合并 PR #1**；只把与三块相关的免费源事实当「免费 fallback」栏参考，且每条重新对官方来源。lead 将 QNT-5 标 cancelled；PR 关闭由 owner 执行。

| # | verify-c REJECT（2026-09-18） | 本卡处置 |
|---|---|---|
| 1 | GET-only 约束不成立：探针含 Hyperliquid POST `/info`、BaoStock TCP/SDK，与「全部只做公共 GET」声明不符 | **不涉及**本卡探针。本卡零探针、零 POST、零 SDK 登录。不沿用 PR #1 的「145/107」通过数。 |
| 2 | Binance Vision zip 被写成「不可变」；官方 README Updates 写 archived files may be updated | **修正**。免费 fallback 引用 Vision 时区分「远端可修订」与「本地按 batch 哈希冻结」。官方：<https://github.com/binance/binance-public-data> 「Updates」：「Archived files may be updated at a later date as a result of recently discovered issues.»（访问 2026-09-23，`raw.githubusercontent.com/.../README.md`）。 |
| 3 | CoinGecko 写成全面禁止长期存储，忽略 “if you must cache or store Data” 条件句；Tardis「允许转售 ≥10 分钟聚合」缺 §9.2/§9.5/§23（Coinbase Data 不适用该例外） | **修正，不沿用** PR #1 许可简化。CoinGecko 不作付费推荐；条款见下「不推荐」段。Tardis 许可按 §9.1–9.5 + §23 全文条件写。 |
| 4 | `probes/run_all.py` 超时路径把 `TimeoutExpired.stdout` 当 str，bytes 时 TypeError | **不涉及**。本卡不提交探针代码。 |
| 5 | 探针 `rows > 0` 即 ok；垃圾列/1970 日期仍通过；通过数不能当验收覆盖 | **不涉及**。本卡无探针验收数字。 |

**不沿用** PR #1 的：CoinGecko「禁止长期存储」简化句、Tardis「允许转售 ≥10 分钟聚合」无条件句、Vision zip「文件不可变」作为重放底座的远端路径说法、任何「仅 docs / 全部 GET」的交付声明。

CoinGecko（本轮重核，**不列入三块推荐/备选**）：

- Data Caching and Storage（<https://www.coingecko.com/en/api_terms>，2026-09-23）：「We do not encourage caching or storage of Data. However, if you must cache or store Data:- You should refresh the cache at least every 24 hours; … In the event that CoinGecko terminates your access … you agree to promptly and permanently delete all Data … without keeping any copy thereof unless required by applicable law.」
- 美国居民：同页要求声明非 OFAC 名单、非 Excluded Countries 常住（<https://landing.coingecko.com/excluded-countries/>）。**未在本轮打开该 landing 页逐国核对美国是否在排除表** → 美国是否可开通标 **未验证（排除表未读）**。

---

## 字段口径

每个候选五栏：

1. **月费**（个人/研究档，USD 或页面原币）+ 价格页 URL + 访问日期 + 限流。
2. **美国居民能否开通**：国家限制、KYC、支付；官方原文。找不到则「未找到官方资料」。
3. **许可可否本地落库**：下载长期保存 / 派生 / 终止后是否须删。内部研究 vs 再分发分开。原文 + URL + 章节。
4. **覆盖 / 历史 / 交付 / 官方 Python SDK**（PyPI 版本本轮 `pypi.org/pypi/<pkg>/json` GET）。
5. **接入建议**：只写 `op://quant-dev/<Vendor>/<field>` 名字；预估月数据量；映射 ADR-0003 `source=` 一句话。

「推荐」= 在**本轮能核到的公开条款**下，对「美国居民个人研究 + 日线落库」阻力相对最小的一档，**不是采购决定**。

---

## A. 美股 + 美股期权

目标：股票日线 + 复权 + 市值/基本面最小集；期权 EOD 链快照（Greeks/IV）与历史回溯年限。

### A 推荐：Sharadar Personal Use · Prices Full History（股票/ETF 日线 + 退市）

| 栏 | 本轮事实 |
|---|---|
| 1 月费 / 限流 | Prices Full History **$39 / 月**（年付 $299）；Bundle 全历史 **$69 / 月**（$499 / 年，含 fundamentals）。5 年档 Prices $9 / 月。页面：「Personal Use License … USD. Guest checkout allowed.」来源：<https://sharadar.com/subscribe>（2026-09-23）。限流：**未找到官方资料**（无公开 rpm 数字）。 |
| 2 美国居民 | Personal Use License Terms 适用于「natural person acting in an individual capacity」。**未找到**按国籍/居住国禁止美国居民的句子。支付：§9「The credit card which you provide will automatically and immediately be billed」「All currency references are in US dollars」「Subscriptions … may not be purchased or paid for as a shared institutional or corporate resource.」KYC：未写政府证件；账户为个人、不可转让（§3）。来源：<https://sharadar.com/terms> §2、§3、§9（2026-09-23）。**结论：公开条款未排除美国自然人个人开户；专业/实体用途被排除。** |
| 3 许可落库 | **内部研究（个人非专业）期间：允许使用 Services Data；未写禁止本机保存。终止后须删源数据，可保留不能复原表的研究产出。再分发：禁止。** §2：「This License is granted solely to natural persons for personal use. You may not use the Services or the Services Data (or any derivation of the Services Data) for professional, commercial, institutional, or organizational purposes of any kind」；禁止项含「professional research」。§4：「you may not … re-distribute or share the Services Data, or any part thereof, or any derivative data that allows reverse engineering」。§6：公开展示数据本身须署名；「Attribution is not required for research outputs, backtest results, models, summary statistics, trade logs, and similar derived works that do not display the Services Data itself.」§10：「Upon termination, you will immediately stop using the Services and the Services Data. Within thirty (30) days of termination, delete from all computer systems you own or operate all copies of the Services Data (including downloads, bulk files, caches, and extracts), all data sets that contain, substantially copy, or could reproduce the Services Data or Sharadar tables … You may keep research outputs, backtest results, models, summary statistics, trade logs, and similar derived works that do not contain and cannot reproduce the Services Data or Sharadar tables.」来源：<https://sharadar.com/terms> §2/§4/§6/§10（2026-09-23）。 |
| 4 覆盖 | 页面表：Prices 全历史含 descriptions/tickers/actions/sp500/stocks/funds/metrics。期权链 / Greeks：**未找到** Sharadar 期权产品。交付：页面列 Query / Bulk / Docs（REST/bulk 细节本轮未打开独立 API 手册）。官方 Python SDK：**未找到**以 Sharadar 为名的 PyPI 包本轮未查到独立包名。 |
| 5 接入 | `op://quant-dev/Sharadar/api_key`（只写名字）。日线研究宇宙量级见 §6（股票日线 GB 以下）。映射：`source=sharadar` → `data/lake/us/equity/kline/1d/` 与 `data/meta/adjust_factor/`（若表含 action）。**期权不在此源。** |

### A 备选 1：Alpaca Trading API Basic（$0）— 股票日线 fallback + Paper Only

| 栏 | 本轮事实 |
|---|---|
| 1 月费 / 限流 | Basic **Free**。Equities：历史自 2016；Historical API **200 / min**；WS 30 symbols；「Historical data limitation\* latest 15 minutes」（相对 SIP 的 15 分钟限制，不是「只有 15 分钟历史」）。Algo Trader Plus **$99 / 月**（全交易所 + 10,000 / min）。Options Basic：Indicative feed；同样 200 / min、15 分钟限制。来源：<https://docs.alpaca.markets/us/docs/about-market-data-api.md>（updatedAt 2026-07-16；GET 2026-09-23）。 |
| 2 美国居民 | Paper Trading 文档 Callout：「Anyone globally can create an Alpaca **Paper Only Account**! All you need to do is sign up with your email address.」Paper Only「only entitled to receive and make use of IEX market data」。来源：<https://docs.alpaca.markets/us/docs/paper-trading.md>（updatedAt 2026-07-07；GET 2026-09-23）。Live 经纪账户的国籍/KYC：**本轮未打开客户协议 PDF** → live 美股账户能否由美国居民开 **未在本文件用客户协议原文核完**（Paper Only 路径有官方全球邮箱注册句）。支付：Basic $0。 |
| 3 许可落库 | **未找到**独立 Market Data Agreement 正文：`https://alpaca.markets/legal/market-data-agreement` 本轮 GET **404**。因此「订阅期内可否把行情长期写入 `data/`、退订是否须删」**未找到官方资料**。Paper 文档只定义模拟撮合，不定义数据版权。再分发：**未找到官方资料**。 |
| 4 覆盖 | 股票/ETF 自 2016；期权历史深度官方表未给「自 20xx」的 EOD 链年限（QNT-2 曾写 2024-02，**本卡未复测、不沿用为已核**）。交付：HTTP + WebSocket。官方 Python：`alpaca-py` **0.44.0**（PyPI，Apache-2.0，2026-09-23）。 |
| 5 接入 | Paper：`op://quant-dev/Alpaca-paper/api_key_id`、`op://quant-dev/Alpaca-paper/api_secret`（只写名字；ADR-0001 禁止 live key）。映射：`source=alpaca`。 |

### A 备选 2：ThetaData Individual Options Standard — **公开条款下不可作落库主源**

列入备选是因为覆盖（期权 tick / chain / 研究档 $80）与 QNT-2 讨论过；**公开 Terms 与「本地落库」冲突**（承接 QNT-2 verify REJECT #1，本卡用现行页重核，不沿用旧 §1(a)/§8(e) 编号）。

| 栏 | 本轮事实 |
|---|---|
| 1 月费 / 限流 | Individual Options：**Value $40 / 月**（4 years、1 minute）；**Standard $80 / 月**（「Best for research」、8 years、tick、Option Chain Snapshots）；**Pro $160 / 月**（12 years）。页面：「Unlimited requests ⓘ」。来源：<https://www.thetadata.net/pricing>（2026-09-23）。并发数字本页未写。 |
| 2 美国居民 | 页面：「Individual Personal use only, no redistribution or business use」。§1.1 许可「solely for the personal, non-commercial use」；「you shall not use the Services Data in connection with any trade, business, professional or other commercial activities。」§4.1 注册须真实信息、年满 18。管辖 §13.1 纽约州；通知地址 Sea Cliff, New York。**未找到**「美国居民不得订阅」句。支付：页面 Subscribe CTA；卡种 **未找到官方资料**。 |
| 3 许可落库 | **公开条款下：不可 archive/download，故不能把「订阅期内内部落库」写成允许。** §2.1 Restrictions：「Subscriber and each Authorized User shall comply with these Terms and shall not: (i) archive, download, reproduce, distribute, modify, display, perform, publish, license, create derivative works of, or offer for sale the Services or any Content or information contained in or obtained from or through the Services; … (iv) use any robot, spider, scraper or other automated means to access the Services; … (vii) use any data mining, data gathering or extraction method」。§12.2 Effect of Termination：「Upon termination of these Terms: (i) the license granted hereunder … shall terminate and Subscriber and its Authorized Users shall immediately cease using the Services; and (ii) Subscriber shall promptly remove any and all Services from its technical and/or cloud environment, destroy any and all hard copies thereof and, within thirty (30) days of the date of termination, certify to Licensor in writing such removal and destruction.」§13.4：「These Terms do not purport to supersede any other legally binding agreements between Subscriber and Theta Data. … In the event of any inconsistency, the terms of such other agreement shall control with respect to such products or services.」来源：<https://www.thetadata.net/terms-and-conditions> §2.1 / §12.2 / §13.4（2026-09-23）。**若购买流程另有 Subscriber/market-data agreement，须 owner 取得该协议 URL/版本后再改判；本卡未注册，未读到该协议。** 再分发：Individual 页「no redistribution」。 |
| 4 覆盖 | Standard：US Index & Stocks、tick、chain snapshots、8 years（页面）。Greeks/IV 是否含在 Standard 的「7 Request types」：**本页未逐项列出，未找到官方资料**。交付：Site + Theta Terminal + API（条款前言）。官方 Python：`thetadata` **1.0.10**（PyPI，Apache-2.0，2026-09-23）。HTTP docs：<https://http-docs.thetadata.us/>（2026-09-23 首页 200）。 |
| 5 接入 | **在书面协议改判前不要采购落库。** 若 owner 取得优先协议：`op://quant-dev/ThetaData/api_key`。映射草稿：`source=thetadata`（ADR-0002 D2.2 枚举已列此名）。 |

### A 期权买断页：Historical Option Data（DeltaNeutral）— 网站 ToS 过窄

<https://historicaloptiondata.com/terms/>「Terms of Service」Last Updated: **March 28, 2026**（GET 2026-09-23）§2 Use License：「Permission is granted to temporarily download one copy of the materials … for personal, non-commercial transitory viewing only. … under this license you may not: Modifying or copying the materials; Using the materials for any commercial purpose or for any public display; … Transferring the materials to another person or “mirroring” the materials on any other server」。价格页 `/prices` 本轮 **404**。独立「购买 CSV 后的数据许可」**未找到官方资料**。美国居民限制 **未找到官方资料**。→ **不作为推荐/备选主行**；仅提示 owner 若走买断须先拿到销售合同，不能用网站浏览许可当落库依据（与 QNT-2 对 Cboe DataShop 的同样缺陷同类）。

### A 免费 fallback（重核，非 PR #1 原文）

| 源 | 用途 | 许可要点 | URL / 访问 |
|---|---|---|---|
| SEC EDGAR companyfacts / bulk | 基本面最小集 | 采集规则「Current max request rate: 10 requests/second」+ 必填 User-Agent。版权：17 U.S.C. §105「Copyright protection under this title is not available for any work of the United States Government」（<https://www.copyright.gov/title17/92chap1.html#105>，2026-09-23）。EDGAR 页本身 **未找到**「public domain」字样。 | <https://www.sec.gov/search-filings/edgar-search-assistance/accessing-edgar-data> |
| Nasdaq Trader 符号目录 | 上市/退市快照键 | 再分发条款 **未找到官方资料**（本卡未打开 Nasdaq 网站 ToS 全文）。 | 目录说明页未在本轮重下；不沿用 PR #1 探针行数。 |
| Cboe 网站 Materials | 不作为管线源 | <https://www.cboe.com/terms/>：「You may view, print and download **one copy** of the Materials for your personal non-commercial use … You may not otherwise copy, reproduce, alter, store either in hard copy or in an electronic retrieval system … create a derivative work」。 | 2026-09-23 |

---

## B. 加密现货 + USDT 永续

目标：OHLCV 多周期、funding、OI；（可选）逐笔/深度归档；相对 Vision 免费归档的增量。

Vision 已覆盖现货 K 线、UM fundingRate 月文件、metrics（OI 等）。付费增量应是：**美国节点不可达的 REST 所**的连续序列、强平、深度、跨所对齐、以及 Vision 空前缀（如 `liquidationSnapshot`）。本卡不重测 451/403。

### B 推荐：Tardis.dev Solo · Perpetuals

| 栏 | 本轮事实 |
|---|---|
| 1 月费 / 限流 | 首页价格表 Perpetuals 计划（列顺序 Academic / Solo / Pro / Business）：**$350 / $700 / $1,000 / $3,000 per month**；Academic「quarterly or yearly billing only」。All Exchanges 计划：**$650 / $1,200 / $2,200 / $6,000 per month**。来源：<https://tardis.dev/> HTML `ct-price-amount`（2026-09-23）。计费说明：月付历史 **4 months**；季付 **12 months**；年付 Academic/Solo/Pro **4 years**；Business 年付自 **2019-03-30**。来源：<https://docs.tardis.dev/faq/billing-and-subscriptions.md>（2026-09-23）。Solo = CSV only，无 raw replay API。API 限流细节见文档 Rate Limits 页（本卡未整页摘录）。**未申请 trial**（文档称 trial 要 Account API 授权，本卡不做）。 |
| 2 美国居民 | ToS **未找到** United States / residency 排除句。支付：Paddle 为 Merchant of Record；信用卡（Mastercard/Visa/…/UnionPay）与 PayPal。来源：ToS「Payments」+ billing FAQ（2026-09-23）。KYC：checkout 用账户邮箱；政府证件 **未找到官方资料**。**结论：公开条款未写禁止美国居民；开通路径是邮箱 + Paddle 付款。** |
| 3 许可落库 | **内部研究：允许 store。终止后：已下载 Data 的 9.1(1)–(3) 许可永久，仍受 9.5/23。再分发原始 Data：禁止；≥10 分钟 OHLCV Derived Data 有条件例外，Coinbase Data 不适用。** Permitted Use：「internal business, research, educational or personal use by the Customer and Customer Users only.」§9.1(2)：「store the Data and Manipulated Data on the Customer System」。§9.2(2)：不得 redistribut/resell Data，「except for reselling or redistributing aggregated and calculated Derived Data, including OHLC or OHLCV candles, at a resolution of 10 minutes or longer, where no raw Data is exposed and the Data cannot reasonably be reconstructed, subject to Clause 9.5 and unless Clause 23 or applicable licensor terms prohibit that use. The exception in Clause 9.2(2) does not apply to Coinbase Data except to the extent permitted under Clause 23.」§9.4：「the licence granted under Clauses 9.1(1) to 9.1(3) for Data downloaded … during paid or free access … is perpetual and survives termination or expiry of this Agreement. Continued use … remains subject to … Clause 9.5.」§23.1 Coinbase Data：不得 further disseminate；Prohibited Use 含 Financial Products、向非 Customer 展示/再分发。Schedule 1(d)：不得「extract, reutilise, use, exploit, redistribute, resell, redisseminate, copy or store the Data … for any purpose not expressly permitted」。来源：<https://docs.tardis.dev/legal/terms-of-service.md> §9、§23、Schedule 1（2026-09-23）。 |
| 4 覆盖 | Perpetuals 计划含 Binance USDS-M / COIN-M perp、OKX Swap、Bybit、Deribit perp、Hyperliquid、dYdX v4 等（billing FAQ 列举）。数据类型：trades、order book、funding 等（FAQ：「all available data types」）。交付：Solo = downloadable CSV；Pro+ 才有 HTTP replay API。官方 Python：`tardis-dev` **5.0.0**（PyPI，MPL-2.0，2026-09-23）。 |
| 5 接入 | `op://quant-dev/Tardis/api_key`。相对 Vision 的增量：跨所 funding/OI/强平/深度、美国节点 REST 451 所的连续更新。日线研究若只落 1d/1h K + funding + OI，月增量见 §6；若落 trades/L2 则高一个数量级。映射：`source=tardis` → `crypto/perp/{kline,funding,open_interest,trade,book_depth}/`。 |

### B 备选：CoinAPI Market Data API Startup

| 栏 | 本轮事实 |
|---|---|
| 1 月费 / 限流 | Metered 含 **$25.00 Free Credits**；**Startup $79 / month**（1k REST Credits/Day、32 GiB Tier 1 Data/Day）；Streamer $249；Pro $599。来源：<https://www.coinapi.io/products/market-data-api/pricing>（2026-09-23）。 |
| 2 美国居民 | Customer Agreement（Effective Date **2025-08-18**）英国公司 API BRICKS LTD。**未找到**美国居民排除句。§2.1 须注册 Account、支付方式。来源：<https://www.coinapi.io/legal>（2026-09-23）。 |
| 3 许可落库 | §1.2：「we grant you a non-exclusive, non-transferable, **revocable** right to access and use the Services for your **internal business purposes** only. No ownership … transferred。」§6 限制 rent/lease/sub-license 等，**未写**「禁止把行情写入本地数据库」。§7.3：「Upon the Termination Date, your rights under this Agreement immediately terminate except where explicitly stated。」**未找到**「终止后删除已下载市场数据」或「已下载副本永久」的专句。§2.3：第三方交易所许可由客户自负。再分发：未写允许。来源：同 legal 页 §1.2 / §6 / §7.3。 |
| 4 覆盖 | 营销为多所 REST/WS/Flat Files；本卡未打开每所历史起点表。官方 Python：**未在本轮核 PyPI 包名**（站点称 Helper Libraries）。 |
| 5 接入 | `op://quant-dev/CoinAPI/api_key`。映射：`source=coinapi`。适合「多所 REST 统一」；日线增量价值低于 Tardis CSV 历史。 |

### B 免费 fallback（重核）

- **Binance Vision zip**：MIT（README Licence）。远端可修订（Updates 段，见来源说明 #2）。本地落库策略：每个 zip + `.CHECKSUM` 进 `data/raw/binance_vision/<batch_id>/`，修订 = 新 batch，不覆盖。映射已有 QNT-28 `source` 路径，本卡不改代码。
- **不把 CoinGecko Demo 当 fallback 主源**（终止须永久删除副本；24h 刷新缓存与 append-only 历史冲突）。

---

## C. A 股 / 港股 / 国内期货

目标：日线 + 复权 + 基本面；期货主力连续；港股日线。产品定义仍是美股+期权+加密（QNT-26）；本块只采购清单。

### C 推荐：Tushare Pro 5000 积分档（A 股日线 + `adj_factor` + 基金/期货接口门槛）

| 栏 | 本轮事实 |
|---|---|
| 1 月费 / 限流 | 积分是门槛、**不消耗**。「除分钟数据和特色数据外 5000 以上具有相对较高的频次。」`daily` 最低 **120** 分；`daily_basic` / 多数财务 **2000** 起。付费路径页面写：专业微信群 **1000 元** 送 **5000 积分**（「入群费用：1000元 (可获得5000积分）」）。积分「正常获取和购买的积分及单独权限都是一年有效期」。来源：<https://tushare.pro/document/1?doc_id=108> 关于权限；<https://tushare.pro/document/1?doc_id=13> 积分规则注；doc_id=270 实际渲染为「欢迎加入专业群」（导航「隐私政策」与正文不符，见下）。约 **¥1000 / 年 ≈ $140 / 年**（汇率未官方标价，USD 月费换算 **未找到官方资料**）。 |
| 2 美国居民 | **未找到**注册国家限制、美国居民可否付款的官方句子。操作手册：「首先需要注册一个 pro 账号，然后登录 … 拿到 token」。来源：<https://tushare.pro/document/1?doc_id=230>。KYC：手机号/邮箱（积分规则）。支付：权限中心「前往直付」、微信。**结论：公开页未写禁止美国居民；实际能否付人民币/微信标未验证（本卡不注册）。** |
| 3 许可落库 | 导航有「用户协议 / 隐私政策 / 服务协议 / 注销须知」，对应 `doc_id=269–272`。本轮 GET 这四个 URL **均未返回协议正文**（269 为可转债赎回字段文档、270 为微信群广告、271 债券大宗、272 大宗明细）。**用户协议原文未找到官方资料。** 踩坑文档公开示范「如何存入 MySQL / MongoDB」，不能代替许可。再分发：**未找到官方资料**。 |
| 4 覆盖 | 日线 `daily`「全部历史」；复权因子、停复牌、财务、基金净值、港股代码后缀 `.HK` 在上市公司数据页出现。期货接口本轮未逐条打开。交付：HTTP + 官方 Python `tushare` **1.4.29**（PyPI，BSD，home https://tushare.pro，2026-09-23）。 |
| 5 接入 | `op://quant-dev/Tushare/token`。映射：`source=tushare` → `cn/equity/kline/1d`、`meta/adjust_factor`、`hk/equity/kline/1d`、`cn/future/kline/1d`。港股另 ¥1000/年的说法来自 PR #1，**本卡未打开该价页，不沿用为已核**。 |

### C 备选：TqSdk 专业版（国内期货主力 / tick 历史）

| 栏 | 本轮事实 |
|---|---|
| 1 月费 / 限流 | 产品页：**专业版 年费 14888元/年**；企业版 30000元/年；免费版有指定期货公司实盘 + 模拟。专业版：「提供期货2016，股票2018年以来的tick级别和任意k线周期数据」。来源：<https://www.shinnytech.com/products/tqsdk>（2026-09-23）。限流/序列上限数字本页未写（PR #1 的 8000 vs 10000 **不沿用**）。 |
| 2 美国居民 | **未找到**国籍限制。需要「快期账户」认证（示例 `TqAuth("快期账户", "账户密码")`）。美国居民能否开快期 **未找到官方资料**。页面有「申请试用」；**本卡不点申请**。 |
| 3 许可落库 | `articles/usage-agreement` 与 `/help/terms` 本轮 **404**。**数据许可原文未找到官方资料。** 再分发：未找到。 |
| 4 覆盖 | 期货/期权/股票行情；`KQ.m@` 主力在 PR #1 出现，**本卡未在本页核到该符号规则原文**。官方 Python：`tqsdk` **3.10.2**（PyPI，2026-09-23）。 |
| 5 接入 | `op://quant-dev/TqSdk/kuaiqi_user`、`op://quant-dev/TqSdk/kuaiqi_password`（只写名字）。映射：`source=tqsdk`。ADR-0001：专业版卖点含实盘下单，接入时只允许行情，交易 key 不进 vault。 |

### C 港股官网：不可作自动化落库源

HKEX Terms of Use §5 Copyright and Permitted Use（<https://www.hkex.com.hk/Global/Exchange/Terms-of-Use?sc_lang=en>，2026-09-23）：

- 「You are permitted to download, print, store temporarily … on disk (**but not on any server or other storage device connected to a network**) for your personal use.」
- 「You are not permitted to conduct … any text or data mining or web scraping … (i) any "robot", "bot", "spider", "scraper" or other automated device …」

→ 港股免费官网路径 **禁止** 联网库落库与机器人抓取。LongPort/Futu 开户条款本轮未读到（agreement URL 404）→ **未找到官方资料**，不列推荐。

### C 免费 fallback（重核）

上交所法律声明第三条（<https://www.sse.com.cn/home/legal/>，2026-09-23）：「任何机构或者个人可基于非商业目的浏览、下载**本网站**的内容。未经上海证券交易所书面许可，任何机构或者个人不得以向他人出售牟利为目的，使用本网站的任何内容，此种使用包括但不限于拷贝、下载、存贮、通过硬拷贝或电子抓取系统获取…」。授权只及上交所网站。深交所声明本轮 GET **Connection reset** → **未找到（本轮不可达）**。BaoStock 免责页本轮返回站点壳、免责正文未抽出 → 许可 **未找到官方资料**。

---

## 三块汇总（待 owner 采购决定）

| 块 | 角色 | 源 | 月费（页面） | 美国居民开通（公开条款） | 可本地落库（公开条款） | 备注 |
|---|---|---|---|---|---|---|
| A | 推荐 | Sharadar Prices 全历史 | $39 | 未排除美国自然人；禁专业/实体 | 订阅期内个人使用；终止 30 日内删源数据；可留不可复原的研究产出；禁再分发 | 无期权 |
| A | 备选 | Alpaca Basic | $0 | Paper Only：全球邮箱即可 | 独立行情许可 **未找到**（MDA 404） | 股票自 2016；期权 EOD 年限本卡未核 |
| A | 备选（覆盖） | ThetaData Options Standard | $80 | 未排除美国；个人非商业 | **§2.1 禁 archive/download**；§12.2 终止后 30 日销毁并书面证明 | 须另约才能改判 |
| B | 推荐 | Tardis Solo Perpetuals | $700 | 未找到国籍禁令；Paddle 卡/PayPal | §9.1 可 store；§9.4 已下载永久（仍受 9.5/23）；禁再分发原始；Coinbase Data 更严 | 相对 Vision 的增量在跨所/强平/深度 |
| B | 备选 | CoinAPI Startup | $79 | 未找到国籍禁令 | 内部使用、权利可撤销；终止后副本去留 **未找到专句** | |
| B | fallback | Binance Vision | $0 | 无账号 | GitHub MIT；远端 zip 可被修订 | 不沿用「不可变」 |
| C | 推荐 | Tushare 5000 分 | ¥1000/年（微信群路径） | 未找到国籍禁令；支付能否从美国完成未验证 | **用户协议正文未找到** | 不注册本卡 |
| C | 备选 | TqSdk 专业版 | ¥14888/年 | 快期账户；美国能否开 **未找到** | **许可页 404** | 申请试用未点 |
| C | 禁止路径 | HKEX 网站 | $0 | n/a | §5 禁联网存储与 robot | |

**只列不裁。** owner 回采购字母后才写 op 条目。

---

## 6. 数据量估算（按推荐方案；1 年 / 3 年）

公式（每类）：

`raw_bytes ≈ N_symbols × rows_per_day × trading_days × bytes_per_row`

`parquet_zstd ≈ raw_bytes × compress_ratio`

落地双份（ADR-0003 `data/raw` + `data/lake`）再 × **2**。只 insert 重跑/补采冗余系数 **1.3**（假设 30% 重复 batch 因修订/失败重拉；非实测）。

**压缩比假设（未实测本卡数据，标假设）**：日线/EOD 宽表 `compress_ratio = 0.20`；5m K 线 `0.25`。行字节为未压缩列式估算。

**研究宇宙（不是全市场期权）**：美股日线 8,000 标的；期权 EOD **100** 标的 × 均 1,000 合约（QNT-2 verify 指出全市场权益期权目录远大于 500；本表不把 100 标的写成「全 universe」）。加密 50 个 USDT 永续。A 股 5,000；国内期货 200 连续合约；港股 2,500。交易日：美/港 252，A 股/期货 242，加密 365。

| 市场 × 类型 | N | 行/日 | B/行 | 1y raw | 1y parquet | 3y parquet | ×2 raw+lake | ×1.3 冗余后 3y |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| A 美股日线 OHLCV+量 | 8,000 | 1 | 80 | 0.16 GB | 0.032 GB | 0.10 GB | 0.19 GB | **0.25 GB** |
| A 美股基本面 snapshot（年 4 季 × 50 fact ≈ 0.8 行/日） | 8,000 | 0.8 | 120 | 0.19 GB | 0.039 GB | 0.12 GB | 0.23 GB | **0.30 GB** |
| A 期权 EOD 链（研究 100 标的，含 IV/Greeks 列） | 100×1,000 | 1 | 150 | 3.78 GB | 0.76 GB | 2.27 GB | 4.54 GB | **5.90 GB** |
| B 加密 1d OHLCV | 50 | 1 | 100 | 0.0018 GB | 0.0004 GB | 0.001 GB | 0.002 GB | **0.003 GB** |
| B 加密 1h OHLCV | 50 | 24 | 100 | 0.044 GB | 0.011 GB | 0.033 GB | 0.066 GB | **0.086 GB** |
| B 加密 5m OHLCV | 50 | 288 | 100 | 0.53 GB | 0.13 GB | 0.40 GB | 0.79 GB | **1.03 GB** |
| B funding（8h） | 50 | 3 | 40 | 0.002 GB | 0.0004 GB | 0.001 GB | 0.002 GB | **0.003 GB** |
| B OI（5m） | 50 | 288 | 40 | 0.21 GB | 0.053 GB | 0.16 GB | 0.32 GB | **0.41 GB** |
| C A 股日线 + 因子 | 5,000 | 1 | 100 | 0.12 GB | 0.024 GB | 0.073 GB | 0.15 GB | **0.19 GB** |
| C 国内期货日线连续 | 200 | 1 | 80 | 0.0039 GB | 0.0008 GB | 0.002 GB | 0.005 GB | **0.006 GB** |
| C 港股日线 | 2,500 | 1 | 80 | 0.050 GB | 0.010 GB | 0.030 GB | 0.061 GB | **0.079 GB** |
| **合计（上表研究档）** |  |  |  | **~5.1 GB** | **~1.0 GB** | **~3.2 GB** | **~6.4 GB** | **~8.3 GB** |

若期权改用「全权益期权目录」量级：QNT-2 verify 于 2026-09-16 从 Cboe 目录 CSV 数出 **5,333** 行标的（本卡**未重下该 CSV**，不把 5333 当本轮实测）。机械把上表 100 换成 5,333 ≈ ×53.3 → 期权 3y 冗余后约 **315 GB** parquet 双份档。tick/L2/trades **不在推荐日线方案内**；Tardis trades 一旦纳入，单所单币即可超过上表总和——上表不含逐笔。

Sharadar 推荐方案本身不含期权；上表期权行是「若 owner 另购可落库期权源」的容量上限提示。

---

## 7. 存储方案（只列不裁；改主机 / owner 执行）

本卡**未执行**任何挂载、分区、chmod、fstab、zfs 命令。下列磁盘数字来自本工作区只读观察（2026-09-23）：

- LXC 根盘：`/dev/mapper/pve-vm--102--disk--0` ext4 **124.9G**，已用 **71.9G**，可用 **46.6G**（约 58–61%），挂载 `/`
- 已存在 NFS：`192.168.0.180:/mnt/truenas/fnOS` nfs4 **33.6T** 可用约 **33.5T**，挂载 `/mnt/fnOS_share`（**这是既有挂载，不是本卡新建**）
- 块设备：`nvme0n1` 1.9T（宿主机侧；容器内 `lsblk` 可见，本卡不解释为容器可写容量）

3 年研究档冗余后 **~8 GB** ≪ 46 GB 可用；若上期权全目录或 Tardis 逐笔，本地盘不够。

### 比较表（不推荐）

| 维 | A. LXC 本地磁盘 | B. TrueNAS dataset 挂载进 LXC |
|---|---|---|
| 容量弹性 | 受 125G 根盘限制；扩容要动 PVE 盘 | dataset 配额可涨；本环境已见 34T 级 NAS |
| 性能 | 本地 ext4，Parquet 顺序读友好 | bind 近本地；NFS 增加 RTT，DuckDB 全表扫描更怕元数据往返 |
| 备份 | 需另安排（rsync/快照无 ZFS） | ZFS snapshot 适合只 append 的 `batch=` 目录 |
| 复杂度 | 低 | uid 映射、fstab、权限 |
| 单点 | 容器盘损坏即数据没 | NAS 或网络中断则扫描失败；容器仍可丢配置 |

### A. LXC 本地磁盘

- IO：日线 Parquet 以顺序读为主；46G 可用可放下 §6 研究档，放不下全市场期权或 trades。
- 备份：拷到已有 `/mnt/fnOS_share` 或外部；本卡不拷。
- 风险：单盘/单容器；迁移要带 `data/`（许可资产，永不入库）。
- 扩容：PVE 扩 `vm-102-disk-0` 后容器内 `resize2fs`。

**操作清单（改主机 / owner 执行；本卡任何 agent 不得执行）**

```text
# 0. 记录改前（owner 终端）
df -h / /home/workspace
ls -ld /home/workspace/quantime/data || true

# 1. 仅当 owner 决定 data 根在本地
mkdir -p /home/workspace/quantime/data/{raw,lake,meta,runs,_staging}
# 改前：目录可能不存在或为空
# 改后：空目录树，属主保持当前 workspace 用户（值不在此填写）

# 回滚
rmdir /home/workspace/quantime/data/_staging  # 仅空目录；有数据则停止
```

扩容（仍为改主机）：

```text
# 在 PVE 宿主机（不是本 LXC agent）
# 改前：lv 大小 = 现有 vm-102-disk-0
# 改后：lvextend + resize2fs 到 owner 选定的 GiB
# 回滚：不能安全缩已用 ext4；不要回滚已写入数据
```

### B. TrueNAS dataset 挂载进 LXC

**bind mount vs NFS**

- **bind**：PVE `mpN` 把宿主机已 mount 的 NAS 路径绑进容器。延迟接近本地 POSIX；uid 必须与容器用户一致。
- **NFS**：容器内 `mount.nfs4`。本机已有 `192.168.0.180:/mnt/truenas/fnOS` → `/mnt/fnOS_share`。DuckDB 扫描应避免对 NFS 做大量小文件 `stat`；batch 目录宜少文件大 Parquet。
- **ZFS 压缩/快照 vs 只 insert**：dataset `compression=zstd` 与 Parquet zstd **可能双重压缩**（收益未测）。snapshot 对齐 `batch_id` 发布点，便于许可删除前的只读冻结；删除源仍须按 ADR-0003 整树 `rm -r data/**/source=<s>/` 并由 owner 确认。

**操作清单（改主机 / owner 执行；本卡任何 agent 不得执行）**

B1 NFS（若 owner 选新 dataset，不要复用来路不明的共享）：

```text
# TrueNAS：创建 dataset tank/quantime-data
# 改前：无该 dataset
# 改后：NFS share 只给该 LXC IP，squash 按 owner 选定

# LXC 内（owner）
mkdir -p /mnt/quantime-data
mount -t nfs4 192.168.0.180:/mnt/truenas/quantime-data /mnt/quantime-data
# 持久化：/etc/fstab 一行 nfs4 选项 owner 自选
ln -s /mnt/quantime-data /home/workspace/quantime/data   # 仅当 data 尚不存在

# 回滚
umount /mnt/quantime-data
# 删除 fstab 行；TrueNAS 侧 disable share（dataset 保留到 owner 决定销毁）
```

B2 bind（PVE 宿主机）：

```text
# 改前：pct config 102 无 mp1
# 改后：pct set 102 -mp1 /host/path/quantime-data,mp=/home/workspace/quantime/data
# 回滚：pct set 102 -delete mp1
```

权限 / uid：容器 uid 3000 与 NFS `anonuid`/`all_squash` 不一致会导致 DuckDB 无法写 `_staging/`。owner 对照 `id` 与 TrueNAS map。**本卡不改 uid。**

---

## 文档矛盾（只报不修）

1. Tushare 导航「用户协议 / 隐私政策 / 服务协议 / 注销须知」的 `doc_id=269–272` 本轮返回的是数据接口页，不是协议正文。
2. AGENTS.md §2 仍写「代码目录尚未建立」，仓库已有 `packages/`（既有矛盾，QNT-27 后未改 AGENTS）。
3. ThetaData 定价页「Unlimited requests」与条款 §2.1 禁 automated access / extraction 并列表述，公开页未调和。
4. Databento `/legal/licensing` 与 `/pricing` 本轮为短 SPA 壳，合同原文 **未找到**（故未列入推荐表）。
