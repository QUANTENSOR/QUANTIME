# 美国居民合规加密合约执行场所对比（Coinbase CFM / IBKR CME / Kraken Derivatives US）

- 调研日期：2026-09-22；节点：本任务工作区（美国出口，**未使用代理、未注册任何账户、未生成任何 API key、未下任何订单（含 sandbox）**）
- 性质：只读官方文档 / 官方产品页 / 监管公开页索引。**不写代码、不申请账号、不调用需鉴权端点。** 本文件不是下单实测报告。
- 任务：QNT-44；基线 `main` @ `d45ec3b`。QNT-33 在本卡裁决前不开工；QNT-28 继续用 Binance Vision 公开归档，不受本卡影响。
- 边界：ADR-0001（paper/testnet only；美国居民实盘候选仅 CFTC 路径 D1.9）· ADR-0002（append-only）· owner 2026-09-22 裁决：只列不裁。
- 每条结论附官方 URL + 访问日期；缺资料写 **未找到官方资料**，不推测。二手来源不作依据。
- 公开只读行情 GET（无 key）仅用于核合约列表字段；**未 POST、未带鉴权头。**

## 0. 结论速览

| # | 结论 | 依据 |
|---|---|---|
| 0.1 | 三家都有「美国居民可走 CFTC 路径」的**产品层**叙事：A = Coinbase Financial Markets（CFM）清算的 CDE 期货 / perpetual-style；B = IBKR 通道上的 CME 加密期货；C = NinjaTrader Clearing d/b/a Kraken Derivatives US 上的 Bitnomial 永续。这不等于三家都有**可给 QNT-33 用的 paper 下单 API**。 | §1 对比表；§2 |
| 0.2 | **唯一在官方文档里同时写清「可下单 API + 官方 Python + 覆盖期货品种的 paper 账户」的是 B（IBKR）**。其 paper 明确要求 live 账户已批准并入金；这与 ADR-0001 正文「IBKR paper REJECT 作为默认」张力仍在，本卡不裁。 | §2.B；ADR-0001 Alternatives |
| 0.3 | A 的 Advanced Trade REST **能下 US futures 单**，有官方 Python SDK；其 sandbox 是**静态 mock**，文档未写覆盖 CFM perpetual-style 的真实撮合。按 ADR-0001「无 paper 路径不能进 QNT-33」字面，A 的 sandbox **不能算合格 paper**。 | §2.A.1–2 |
| 0.4 | C 必须拆成两套 API，不得混写：**C-US** = Bitnomial / Kraken Pro 美国永续；**C-non-US** = `futures.kraken.com` + `PF_` + `demo-futures.kraken.com`。后者有完整 REST 下单与自助 demo，**不能记到美国实体头上**。 | §2.C |
| 0.5 | C-US：Bitnomial 官方公开 REST 做行情 / 资金费 / 订单**查询**；下单走 DMA 二进制 BTP 或 FIX，需向交易所登记。Kraken 开发者文档**未**把 Bitnomial 永续接到 `api.kraken.com` 或 `futures.kraken.com`。C-US **未找到** sandbox/paper。 | §2.C-US |
| 0.6 | 推荐只排序不裁决，见 §3。待 owner 裁决。 | §3 |

## 1. 三候选 × 六项对比表

访问日期一律 **2026-09-22**。格内「来源」指向 §4 编号。空缺只写「未找到官方资料」。

| # | 核项 | A. Coinbase Advanced Trade / CFM（CDE） | B. IBKR · CME 加密期货 | C. Kraken Derivatives US（Bitnomial）— **仅美国实体** |
|---|---|---|---|---|
| 1 | API 能否下单；官方 Python SDK | **能下单。** `POST /api/v3/brokerage/orders`；US futures 另有 `/cfm/*` 账户/持仓/sweep。Host：`https://api.coinbase.com/api/v3/brokerage`。官方 Python：`coinbase-advanced-py`（PyPI 1.8.4，GitHub `coinbase/coinbase-advanced-py`）。TS/Go/Java 标 **sample SDK**，非官方主 SDK。CDE 机构 REST/FIX/SBE 是另一套（`api.exchange.fairx.net`），零售走 Advanced Trade。来源 A1 A2 A3 A16 | **能下单。** TWS API `placeOrder()`（需本机 TWS/IB Gateway）；官方 Python 客户端随 TWS API 安装，PyPI 包 `ibapi` 9.81.1.post1 标 “Official Interactive Brokers API”（专有许可，非 OSI）。Web API：`POST https://localhost:5000/v1/api/iserver/account/{accountId}/orders`（Client Portal Gateway）；认证 OAuth 2.0 `private_key_jwt`（机构）或 CPGW（零售）。文档给 Python 示例，**未找到**独立官方 Web API Python 包名。来源 B1 B2 B3 B4 B16 | **未找到** Kraken 把 C-US Bitnomial 永续接到公开 REST/WS 下单端点的官方说明。Bitnomial 自身：公开 REST **不能下单**（`GET /orders` 只查状态）；下单 = DMA **BTP 二进制**或 **FIX**，需联系 `help@exchange.bitnomial.com` 做 DMA 登记。官方 Python SDK：**未找到**。来源 C1 C2 C3 C16 |
| 2 | sandbox / paper 是否覆盖该合约品种（ADR-0001） | **不能视为合格 paper。** Advanced Trade sandbox host `https://api-sandbox.coinbase.com/api/v3/brokerage/{resource}`：**无需鉴权**、响应**全部静态预定义**；目前只开 Accounts/Orders（及已弃用的 INTX perpetuals 路径）。文档未写 sandbox 产品列表含 CFM/`*-CDE`，也未写与生产同一撮合。INTX perp sandbox 示例 symbol `ETH-PERP-INTX` 属**非美 Global Derivatives**，不得记到 CFM。来源 A4 A5 A17 | **有 paper，且官方写「TWS 上可用的品种几乎都能在 paper 里交易」。** 条件：常规交易账户**已批准并入金**后，在 Account Management 开 Paper Trading Account；新个人账户自动给 **USD 1,000,000** ELV。TWS paper 端口 **7947**，IB Gateway paper **4002**（live TWS 7946 / Gateway 4001）。限制：部分订单类型不支持、盘口只模拟顶层等；限制清单**未排除**期货/CME 加密。文档未逐合约保证「MBT/BRR 与 live 行为一致」。来源 B5 B6 B7 B8 | **未找到** C-US / Bitnomial 的 sandbox 或 paper。Bitnomial Environments 只列 **Production** 与 **Disaster Recovery**，无 demo。Kraken `demo-futures.kraken.com` 属于 **C-non-US**（§2.C-non-US），禁止记到本列。来源 C4 C12 |
| 3 | 合约列表、杠杆、资金费率 / 结算 | 公开 `GET /api/v3/brokerage/market/products?product_type=FUTURE`（无 key）本节点 2026-09-22 返回 **118** 条，`product_venue=FCM`，`future_product_details.venue=cde`。含 **nano Bitcoin** `BIT`（0.01 BTC，到期月合约）与 **nano BTC Perp** `BIP-20DEC30-CDE`（`contract_expiry=2089-12-30`，`funding_interval=3600s`，当日快照 `funding_rate=0.000015`）。营销页写加密合约最高 **10x**、商品期货盘中最高 **25x**；`BIP` 快照 overnight 保证金约 24.6%/30.6%（多/空）。到期期货无 `funding_interval`。CDE 另有 24x7 交易时段说明。来源 A6 A7 A8 A9 | IBKR 佣金页列出其通道上的加密期货：**CME Bitcoin (BRR)**、**Micro Bitcoin (MBT)**、**Bitcoin Friday (BFF)**、**CME Ethereum / Micro (ETH, MET)**、以及 Solana / Ripple / Chainlink / Stellar 及微型；另列 **Coinbase Nano Bitcoin (BIT/BIP) 与 Nano Ether (ET/ETP)**（这是 CDE 品种经 IBKR 通道，不是 CME）。CME 加密期货为**有到期日的期货**，官方页**未**写资金费率。杠杆 = 交易所/IBKR 保证金；**CME 加密品种具体保证金比例未找到官方资料**（CME 官网本节点 HTTP 403）。来源 B9 B10 | Kraken Pro 营销：美国居民在 Pro 上交易 Bitnomial 永续；BTC/ETH/SOL「及另外 13 个」；**无到期**；资金费 **每 8 小时**（00:00 / 08:00 / 16:00 UTC）；盘中保证金可低至 **$25**；杠杆「因合约而异」，BTC/ETH 更高档——**未找到** C-US 官方数字上限。Bitnomial 首页写保证金交易最高 **6x**（「margin rates subject to change」）；资金费公式与 8h CT 区间见交易所文档。来源 C5 C6 C7 C8 |
| 4 | 历史数据（K 线 / 成交 / 资金费 / OI） | Advanced Trade 公共：`GET /market/products/{id}/candles`（granularity 1m–1d，**默认/最大 350 根**）；`GET /market/products/{id}/ticker` 最近成交。公共 REST 缓存 1s。CDE 公开 REST spec：`GET /rest/funding-rate?symbol=`（例 `BIPZ30`）标 `security: []`；本节点对该 host 返回 **401**，故**是否真正无 key 可得标未验证**。OI 出现在产品字段 `open_interest`（快照，非历史序列）。长期 bulk 归档：**未找到**等同 Vision zip 的官方免费包。来源 A2 A10 A11 A12 | TWS API 向**行情订阅用户**提供 historical bars / Time & Sales / Histogram；有独立 historical 限制章节。Web API 有 Obtaining Market Data。免费无订阅的长期公开归档：**未找到官方资料**。资金费率：CME 到期期货通常无 funding；CDE 品种若经 IBKR 交易，资金费历史是否经 IBKR API 提供 **未找到官方资料**。来源 B11 B12 B13 | Bitnomial 公开 REST：Products、Funding Rates（无 `begin_time` 只返回最近；历史必须带 `begin_time`）、Charts（日频 OHLC + settlement；VOI 含 volume/OI，默认约 30 天）、Market Stats（24h）。限速 **200 req / 5 min**。成交逐笔：WS Trade 通道；REST 成交历史深度 **未找到官方资料**。Kraken `futures.kraken.com` 的 `/historical-funding-rates`、`/api/history/v2/` 属于 **C-non-US**。来源 C9 C10 C11 C13 |
| 5 | 费率 | Advanced Trade US Derivatives 指南：与 Advanced Trade **同一费率结构**；「introductory beta」只收 **0.05%**（当时最低档）。营销页：量价 maker 低至 **0.005%**，另加每张 **$0.15** 覆盖 exchange/NFA/clearing（脚注 3）。`GET /transaction_summary` 可按 `product_type=FUTURE`、`product_venue=FCM` 查账户档。`www.coinbase.com/advanced-fees` 与 help 费率页本节点 **403**，完整阶梯表 **未在本卡打开原文**。来源 A8 A13 A14 | IBKR 期货佣金页（USD/张，月成交量第一档 / Fixed）：CME BTC (BRR) **5.00**；MBT **0.85**；ETH **3.00**；MET **0.20**；Coinbase Nano BIT/BIP 与 ET/ETP **0.20**。另加 exchange / regulatory / overnight 等「offset」费。来源 B9 | Bitnomial Exchange 费率页：Bitcoin Complex / Crypto Complex **无** Minimum Contract Size 时，Participant **$0.07** / Non-Participant **$0.10** **per side**；有 Minimum Contract Size 时为 **$0.0007 / $0.0010 per side per Minimum Contract**；Spot Complex **2 bps per side**。含 Exchange+Clearing。Kraken Pro 写 maker/taker + 30 日量分层，**未找到** C-US 专用百分比表（`kraken.com/features/fee-schedule` 的 Futures 0.02%/0.05% 是 **C-non-US 档**，见 §2.C-non-US）。来源 C14 C15 C5 |
| 6 | 个人开户门槛 | 期货账户单独申请：`coinbase.com/futures` 或 Advanced Trade Futures 页 Apply。CFM = CFTC 注册 FCM、NFA 会员；资金在 CFM 期货账户，现货在 Coinbase Inc.（非 CFTC）。「Products and features may not be available in all regions」。**州限制清单、最低资金、适当性测试原文：help 页 403，未找到官方资料。** 来源 A8 A15 A18 | IBKR LLC：SEC + CFTC 监管，NYSE/FINRA/SIPC 会员。个人可开经纪账户。Paper：**须先有已批准并入金的 live**（TWS API 文档原句）。期货交易权限/加密期货适当性的逐条官方清单 **未找到**（只有通用期货风险披露）。来源 B5 B14 B15 | Kraken Pro：美国居民可直接交易永续；需身份验证 + Futures eligibility check（「几分钟」）；**部分州可能限制**，资格在注册时确认。FCM：NinjaTrader Clearing, LLC d/b/a Kraken Derivatives US，NFA ID **0309379**。Bitnomial：美国及海外居民均可，但期货须经 FCM 额外验证。最低资金：营销写盘中保证金可低至 $25，**不是**开户最低净资金的监管数字。来源 C5 C6 C17 |

**C-non-US（对照，禁止记入上表 C 列）** 见 §2.C-non-US：`https://futures.kraken.com` REST 可 `POST /sendorder`；demo `https://demo-futures.kraken.com`；品种前缀 `PF_` / `PI_` / `FI_` / `FF_`。

## 2. 分场所事实

### 2.A Coinbase Advanced Trade · CFM / CDE

#### 2.A.1 下单 API 与 SDK

- Advanced Trade 定位：个人交易者的 REST + WebSocket；覆盖 **Spot、US futures（CFTC）、Global Derivatives（非美永续，迁 Deribit 网关）**。US futures 与 Spot 共用 `https://api.coinbase.com/api/v3/brokerage`。来源：[Advanced Trade overview](https://docs.cdp.coinbase.com/coinbase-app/advanced-trade-apis/overview.md)（2026-09-22）、[REST introduction](https://docs.cdp.coinbase.com/api-reference/advanced-trade-api/rest-api/introduction.md)（2026-09-22）
- 下单：`POST /orders`。US futures 专用：`GET /cfm/balance_summary`、`GET /cfm/positions`、sweep、intraday margin。来源：[REST endpoints](https://docs.cdp.coinbase.com/coinbase-app/advanced-trade-apis/rest-api.md)（2026-09-22）、[Create Order](https://docs.cdp.coinbase.com/api-reference/advanced-trade-api/rest-api/orders/create-order.md)（2026-09-22）、[US Derivatives guide](https://docs.cdp.coinbase.com/coinbase-app/advanced-trade-apis/guides/futures.md)（2026-09-22）
- 官方 Python SDK：GitHub `coinbase/coinbase-advanced-py`，PyPI `coinbase-advanced-py==1.8.4`。来源：[SDK page](https://docs.cdp.coinbase.com/coinbase-app/advanced-trade-apis/sdk.md)（2026-09-22）、[README](https://raw.githubusercontent.com/coinbase/coinbase-advanced-py/master/README.md)（2026-09-22）、[PyPI JSON](https://pypi.org/pypi/coinbase-advanced-py/json)（2026-09-22）
- **不要混淆：** INTX perpetuals / `drb.coinbase.com` Global Derivatives 文档写明给 **eligible non-US clients**，且 INTX 端点在 cutover 后废弃。来源：[overview 市场表](https://docs.cdp.coinbase.com/coinbase-app/advanced-trade-apis/overview.md)、[INTX deprecated](https://docs.cdp.coinbase.com/coinbase-app/advanced-trade-apis/guides/perpetual.md)（2026-09-22）

#### 2.A.2 Sandbox（ADR-0001）

- Host：`https://api-sandbox.coinbase.com/api/v3/brokerage/{resource}`。无鉴权；格式与生产相同；**全部静态**；可用 `X-Sandbox:` 头触发预设错误。仅 Accounts/Orders（及 INTX perp 查询）在列。来源：[Advanced Trade API Sandbox](https://docs.cdp.coinbase.com/coinbase-app/advanced-trade-apis/sandbox.md)（2026-09-22）
- 结论：这是 **HTTP mock**，不是带资金与撮合的 paper。文档**没有**说 mock 覆盖 `BIP-*-CDE` / CFM。**QNT-33 若选 A，不能把该 sandbox 当 ADR-0001 合格路径**，除非 owner 另行批准「静态 mock 算 paper」或 CFM 另开 demo。

#### 2.A.3 合约 / 杠杆 / 资金费

- 公开产品列表（无 key，只读）本节点 2026-09-22：`product_type=FUTURE` 共 118 条。Perp 以远到期日（2089-12-30 或 2030-12）+ `funding_interval` 表达。`BIP`：`contract_size=0.01` BTC，`funding_interval=3600s`。到期 `BIT` 无 funding 字段。来源：`GET https://api.coinbase.com/api/v3/brokerage/market/products?product_type=FUTURE`（2026-09-22）；字段说明见 [List public products](https://docs.cdp.coinbase.com/api-reference/advanced-trade-api/rest-api/public/list-public-products.md)（2026-09-22）
- 营销合约表（节选）：nano Bitcoin / nano Bitcoin Perps 0.01 BTC、24x7、最高 10x；nano Ether 0.1 ETH、10x；商品最高 25x 盘中。另注每张 $0.15 费用。来源：[US derivatives 营销页](https://www.coinbase.com/derivatives-trading/us-derivatives)（2026-09-22）
- CDE 24x7：2025-05-09 起部分加密期货；周五 16:00–16:50 CT 维护；非 24x7 参与者周末/假日不能下单。来源：[Market Hours](https://docs.cdp.coinbase.com/derivatives/introduction/market-hours.md)（2026-09-22）
- 实体：期货与 cleared swaps 由 **Coinbase Financial Markets, Inc.** 提供，CFTC FCM、NFA 会员。来源：[US Derivatives guide](https://docs.cdp.coinbase.com/coinbase-app/advanced-trade-apis/guides/futures.md)、[营销页脚注 1](https://www.coinbase.com/derivatives-trading/us-derivatives)（2026-09-22）

#### 2.A.4 历史数据

- 公共 K 线最大 350 根。来源：[Get Public Product Candles](https://docs.cdp.coinbase.com/api-reference/advanced-trade-api/rest-api/public/get-public-product-candles.md)（2026-09-22）
- 公共成交：`GET /market/products/{id}/ticker`。来源：[Get Public Market Trades](https://docs.cdp.coinbase.com/api-reference/advanced-trade-api/rest-api/public/get-public-market-trades.md)（2026-09-22）
- CDE REST spec servers：`https://api.exchange.fairx.net`；`GET /rest/funding-rate`。来源：[cde-public-api-spec.json](https://docs.cdp.coinbase.com/derivatives/downloads/cde-public-api-spec.json)（2026-09-22）。本节点对该 URL 无 key GET → **401**，故「免费公开」未证实。
- App API 默认限流：**10,000 请求/小时/key 或 OAuth 用户**，超限 429。来源：[Rate limiting](https://docs.cdp.coinbase.com/coinbase-app/api-architecture/rate-limiting.md)（2026-09-22）

#### 2.A.5 费率

- 指南：「same fee structure」+ beta **0.05%**。来源：[US Derivatives guide · Advanced Trade Fees](https://docs.cdp.coinbase.com/coinbase-app/advanced-trade-apis/guides/futures.md)（2026-09-22）
- 营销：maker 低至 0.005% + $0.15/张。来源：[us-derivatives](https://www.coinbase.com/derivatives-trading/us-derivatives)（2026-09-22）
- 完整 Advanced 阶梯原文页 403 → 未核验。

#### 2.A.6 开户

- 申请入口官方写在 US Derivatives 指南。州清单 / 最低资金：**未找到官方资料**（help.coinbase.com 衍生品页 403/404）。

### 2.B IBKR · CME 加密期货（TWS / Web API）

#### 2.B.1 下单 API 与 SDK

- TWS API：经 TWS 或 IB Gateway 套接字；语言含 Python。`placeOrder` 示例默认连 **Gateway paper 4002**。来源：[Placing Orders](https://ibkrcampus.com/docs/tws-api/doc/quick-start/placing-orders.md)（2026-09-22）、[Introduction](https://www.interactivebrokers.com/campus/ibkr-api-page/trader-workstation-api/)（2026-09-22）
- 安装：Mac/Linux zip `twsapi_macunix.*.zip` → `~/IBJts/source/pythonclient` 再 `pip install .`。来源：[Install TWS API Mac/Linux](https://ibkrcampus.com/docs/tws-api/doc/download-the-tws-api/install-the-tws-api-on-mac-os-linux.md)（2026-09-22）
- PyPI `ibapi` 9.81.1.post1，Homepage `https://interactivebrokers.github.io/tws-api`，License **IB API Non-Commercial or Commercial**（专有）。来源：[pypi.org/pypi/ibapi/json](https://pypi.org/pypi/ibapi/json)（2026-09-22）
- Web API：零售用 Client Portal Gateway；交易 API 对所有 IBKR 客户免费。下单 `POST /v1/api/iserver/account/{accountId}/orders`。来源：[Web API Introduction](https://ibkrcampus.com/docs/web-api/introduction.md)（2026-09-22）、[Placing Orders](https://ibkrcampus.com/docs/web-api/api/web-api/placing-orders.md)（2026-09-22）、[Getting Started](https://ibkrcampus.com/docs/web-api/getting-started.md)（2026-09-22）
- 产品页：TWS API GPL 开源组件；Web API 为 REST。来源：[IBKR Trading API Solutions](https://www.interactivebrokers.com/en/index.php?f=5041)（2026-09-22）

#### 2.B.2 Paper（ADR-0001）

- TWS API：「If your regular trading account has been approved and funded, you can … open a Paper Trading Account」。来源：[Paper Trading](https://ibkrcampus.com/docs/tws-api/doc/notes-limitations/limitations/paper-trading.md)（2026-09-22）
- Client Portal 指南：新客户自动获得 paper、**USD 1,000,000** ELV；「trade all instruments available through our IBKR TWS trading platform」；不能把 paper 转成 live。限制：无 VWAP/Auction/RFQ/Pegged to Market、无深簿、部分复杂单始终模拟等——**未写排除期货**。来源：[Paper Trading Account](https://www.ibkrguides.com/clientportal/papertradingaccount.htm)（2026-09-22）、[About Paper Trading Accounts](https://www.ibkrguides.com/clientportal/aboutpapertradingaccounts.htm)（2026-09-22）
- 端口：TWS live 7946 / paper 7947；Gateway live 4001 / paper 4002。来源：[Placing Orders 代码注释](https://ibkrcampus.com/docs/tws-api/doc/quick-start/placing-orders.md)（2026-09-22）
- 与 ADR-0001：该 ADR Alternatives 写「IBKR paper（REJECT 作为默认：需入金 live 账户、Gateway 常驻 + 2FA）」。本卡只记录张力，不改 ADR。

#### 2.B.3 合约 / 杠杆 / 资金费

- 佣金页产品名即 IBKR 承认可报佣的加密期货清单（见对比表）。CME 官网本节点 403，合约乘数/到期循环以 IBKR 页名为准，细节 **未打开 CME 规格 PDF**。
- CME 加密期货 = 到期期货，**无**资金费率机制（与 Binance/Bitnomial 永续不同）。杠杆数字 **未找到官方资料**。

#### 2.B.4 历史数据

- 需 IBKR 行情订阅。来源：[Historical Market Data intro](https://ibkrcampus.com/docs/tws-api/doc/market-data-historical/introduction.md)（2026-09-22）、[limitations intro](https://ibkrcampus.com/docs/tws-api/doc/market-data-historical/historical-data-limitations/introduction.md)（2026-09-22）
- 免费深度/年限/OI/funding 端点：**未找到官方资料**。

#### 2.B.5 费率

- 见对比表；来源：[Commissions Futures](https://www.interactivebrokers.com/en/pricing/commissions-futures.php)（2026-09-22）

#### 2.B.6 开户

- IBKR LLC 受 SEC 与 CFTC 监管。来源：Client Portal 页脚（同上 ibkrguides）。期货权限细则 **未找到官方资料**。

### 2.C Kraken：必须拆开的两套系统

#### 2.C-US Kraken Derivatives US · Bitnomial 永续

**实体（营销页原文）**

> Brokerage services are provided by NinjaTrader Clearing, LLC d/b/a Kraken Derivatives US, a CFTC-registered Futures Commission Merchant and NFA Member (NFA ID: 0309379).
>
> Who provides perpetual futures on Kraken? NinjaTrader Clearing LLC dba Kraken Derivatives US trading Bitnomial Perpetual Futures.

来源：[Kraken Pro Crypto Perpetuals](https://www.kraken.com/features/derivatives)（2026-09-22）

- 美国居民可在 Kraken Pro 交易永续；KYC + Futures eligibility check；部分州可能限制。资金费 8h；盘中保证金低至 $25；与 CME 到期期货的区别写在同一 FAQ。来源：同上。
- Bitnomial：CFTC DCM + DCO + FCM；永续、期货、期权、杠杆现货、预测市场；首页杠杆最多 6x。来源：[bitnomial.com](https://bitnomial.com/)（2026-09-22）、[Exchange](https://bitnomial.com/exchange)（2026-09-22）

**公开 API（Bitnomial 交易所文档，不是 Kraken Futures API）**

- 分类：DMA（BTP 下单 + FIX drop copy，需登记）vs 公网 REST/WS（行情与账户查询）。来源：[API Overview](https://bitnomial.com/exchange/docs/api/overview/)（2026-09-22）
- REST base：`https://bitnomial.com/exchange/api/v1/prod/`。公开：Products、Block Trades、Indexes、Funding Rates、Charts、Market Stats。认证：Orders（**GET 查单**）、Fills。限速 200/5min。来源：[REST Overview](https://bitnomial.com/exchange/docs/api/rest/overview/)（2026-09-22）
- 下单：BTP Order Entry（二进制 gateway，500 msg / 3s，cancel 不受限）。来源：[BTP Order Entry](https://bitnomial.com/exchange/docs/api/btp/order-entry/)（2026-09-22）
- REST Orders：**没有 POST**。来源：[Orders](https://bitnomial.com/exchange/docs/api/rest/orders/)（2026-09-22）
- Environments：Prod + DR。**无 sandbox。** 来源：[Environments](https://bitnomial.com/exchange/docs/api/environments/)（2026-09-22）
- 资金费：8h；历史需 `begin_time`；公式 `FR = avg(P) + clamp(IR - avg(P), -0.05%, 0.05%)`，IR=0.01%。来源：[Funding Rates](https://bitnomial.com/exchange/docs/api/rest/funding-rates/)（2026-09-22）、[Digital Asset Perpetual Pricing](https://bitnomial.com/exchange/docs/market-operations/settlements/digital-asset-perpetual-pricing/)（2026-09-22）
- Charts：日频。来源：[Charts](https://bitnomial.com/exchange/docs/api/rest/charts/)（2026-09-22）
- 官方 Python SDK：**未找到**（GitHub org `bitnomial` 存在，本卡未把其仓库当 SDK 声明）。
- Kraken 开发者门户 / `docs.kraken.com` / `kraken.com/features/api`：**未出现** Bitnomial、NinjaTrader Clearing、或「US perpetuals REST」。来源：[docs.kraken.com/llms.txt](https://docs.kraken.com/llms.txt)、[Start building](https://docs.kraken.com/api.md)、[Kraken API 营销](https://www.kraken.com/features/api)（2026-09-22）

**结论（C-US 交易 API）：** 存在 **Bitnomial 公开行情 REST** 与 **DMA 下单**；**未找到**「Kraken US 面向零售的公开交易 REST/官方 Python SDK/paper」。QNT-33 不能把 `futures.kraken.com` 或 `demo-futures.kraken.com` 当作 C-US。

#### 2.C-non-US Kraken Futures（`PF_` / `futures.kraken.com` / `demo-futures`）

> 本节只作对照，**不是**美国居民合规候选。

- REST 下单：`POST https://futures.kraken.com/derivatives/api/v3/sendorder`。来源：[Send order](https://docs.kraken.com/api-reference/order-management/send-order.md)（2026-09-22）、[Derivatives REST](https://docs.kraken.com/exchange/guides/futures/rest.md)（2026-09-22）
- Demo：**自助** `https://demo-futures.kraken.com`，API 契约同生产，仅换 host；WS `wss://demo-futures.kraken.com/ws/v1`。来源：[Derivatives Introduction](https://docs.kraken.com/exchange/guides/futures.md)（2026-09-22）、[Exchange overview](https://docs.kraken.com/exchange/guides/overview.md)（2026-09-22）
- 官方 SDK 页：Go `api-go`（Spot+Derivatives）、Rust `kraken-sdk`（Spot；Derivatives Planned）。Python：**无官方包**；社区 `kraken-wsclient-py`（仅 Spot WS）。Sample implementations 指向 github.com/krakenfx。来源：[SDKs](https://docs.kraken.com/home/sdks.md)（2026-09-22）
- 公开 `GET /derivatives/api/v3/instruments`（无 key，本节点 2026-09-22）：296 条；前缀 **PF 274** / FF 10 / FI 8 / PI 4。`PF_XBTUSD` type `flexible_futures`，第一档 initialMargin **0.01**，`fundingRateCoefficient=8`，`maxRelativeFundingRate=0.005`。`countriesBanned` 空（不等于美国居民被允许用此 API）。
- 历史资金费：`GET /historical-funding-rates`。来源：[Historical funding rates](https://docs.kraken.com/api-reference/historical-funding-rates.md)（2026-09-22）
- 费率页 Futures Tier 1：maker **0.02%** / taker **0.05%**（&lt; $5M）。来源：[Fee schedule](https://www.kraken.com/features/fee-schedule)（2026-09-22）——**不要抄到 C-US 格子。**

## 3. 推荐（只列不裁，待 owner 裁决）

排序键（派发原文）：**paper 覆盖 → API 可下单 → 历史数据 → 费率 → 门槛**。不是投资建议，也不是法律意见。

| 优先级 | 候选 | 理由（按排序键） | ADR-0001 / QNT-33 含义 |
|---|---|---|---|
| 1 | **B. IBKR CME** | 唯一官方写明 paper 账户 + 期货品种经 TWS 可交易 + 官方 Python 可 `placeOrder`。历史依赖付费行情。按张佣金高于加密所百分比模型。须先开并入金 live。 | 与 ADR-0001「IBKR paper 不作默认」冲突，**是否破例由 owner 裁**。Paper host 是本机 Gateway `127.0.0.1:4002` / TWS `7947`，不是公网 demo。 |
| 2 | **A. Coinbase CFM** | REST 可下 US futures（含 perpetual-style）、官方 Python、公共产品列表与 K 线最好。Sandbox **不是**真实 paper。无 Vision 级免费长历史。 | 若坚持 ADR-0001 字面，**不能进 QNT-33**，除非 owner 接受静态 mock，或 CFM 另给 demo。 |
| 3 | **C. Kraken Derivatives US** | 美国居民产品存在（Pro UI + Bitnomial DCM）。公开 REST 有资金费与日线。下单非公网 REST、无官方 Python、**无 paper**。 | 按 ADR-0001 **不能进 QNT-33**。不要用 `demo-futures.kraken.com` 冒充。 |

**明确：本卡不替 owner 选。** QNT-33 在裁决前不开工。QNT-28 继续 Vision。

## 4. 对 QNT-33 的影响（若某候选被选中）

只写 vault **item 名**（`quant-dev`）与 allowlist **host**，不写值。`public_readonly` 按「无 key 行情 vs 签名交易」标注。

### 若选 A（Coinbase CFM）

- vault item（建议名，owner 可改）：`coinbase-advanced-sandbox-api`（**仅当 owner 接受静态 sandbox**）。禁止 `coinbase-advanced-live-api`。
- allowlist 交易：`api-sandbox.coinbase.com`（`public_readonly=false`）。**不要**把 `api.coinbase.com` 放进交易 allowlist。
- 公共只读（若 QNT-33 同时拉 CFM 行情）：`api.coinbase.com` 的 `/api/v3/brokerage/market/*`（`public_readonly=true`）；WS `advanced-trade-ws.coinbase.com`（只行情时 `public_readonly=true`）。
- CDE `api.exchange.fairx.net`：本卡测得 401，是否只读未证实 → **先不进 allowlist**，待单独核。

### 若选 B（IBKR CME paper）

- vault item：`ibkr-paper-api`（paper 用户名/密码或 Gateway 会话材料，**禁止 live**）。
- allowlist：本机 `127.0.0.1` TWS paper **7947** / Gateway paper **4002**（`public_readonly=false`）。Live 端口 7946/4001 **禁止**。Web API 若走 CPGW，同样只绑 paper 会话。
- 公网 `www.interactivebrokers.com` / `ibkrcampus.com` 仅文档，不进交易 allowlist。

### 若选 C（Kraken Derivatives US）

- **当前不建议进 QNT-33**：无 paper、无零售 REST 下单。
- 若 owner 仍要接 Bitnomial DMA：item 名草案 `bitnomial-dma-paper`——但官方 **没有 paper 环境**，与 ADR-0001 直接冲突，须 owner 书面豁免。
- **禁止**把 `demo-futures.kraken.com` / `futures.kraken.com` 标成 C-US。

### 无论选谁

- ADR-0001 D1.7 现有 allowlist 仍是 Binance demo / Bybit / Deribit test / Hyperliquid testnet / dYdX testnet / `demo-futures.kraken.com`。选 A/B/C 都要 **另改 ADR**（关键路径，本卡只点出）。
- QNT-28 Vision 路径不变。

## 5. 来源列表（本卡实际打开过，2026-09-22）

**A Coinbase**

- A1 https://docs.cdp.coinbase.com/coinbase-app/advanced-trade-apis/overview.md
- A2 https://docs.cdp.coinbase.com/coinbase-app/advanced-trade-apis/rest-api.md
- A3 https://docs.cdp.coinbase.com/api-reference/advanced-trade-api/rest-api/introduction.md
- A4 https://docs.cdp.coinbase.com/coinbase-app/advanced-trade-apis/sandbox.md
- A5 https://docs.cdp.coinbase.com/coinbase-app/advanced-trade-apis/guides/perpetual.md
- A6 https://api.coinbase.com/api/v3/brokerage/market/products?product_type=FUTURE （无 key GET）
- A7 https://docs.cdp.coinbase.com/api-reference/advanced-trade-api/rest-api/public/list-public-products.md
- A8 https://docs.cdp.coinbase.com/coinbase-app/advanced-trade-apis/guides/futures.md
- A9 https://docs.cdp.coinbase.com/derivatives/introduction/market-hours.md
- A10 https://docs.cdp.coinbase.com/api-reference/advanced-trade-api/rest-api/public/get-public-product-candles.md
- A11 https://docs.cdp.coinbase.com/api-reference/advanced-trade-api/rest-api/public/get-public-market-trades.md
- A12 https://docs.cdp.coinbase.com/derivatives/downloads/cde-public-api-spec.json
- A13 https://www.coinbase.com/derivatives-trading/us-derivatives
- A14 https://docs.cdp.coinbase.com/api-reference/advanced-trade-api/rest-api/fees/get-transaction-summary.md
- A15 https://www.coinbase.com/derivatives
- A16 https://github.com/coinbase/coinbase-advanced-py ；https://pypi.org/pypi/coinbase-advanced-py/json
- A17 https://docs.cdp.coinbase.com/coinbase-app/advanced-trade-apis/faq.md
- A18 https://docs.cdp.coinbase.com/coinbase-app/api-architecture/rate-limiting.md
- （未打开原文）help.coinbase.com 衍生品/费率、www.coinbase.com/advanced-fees → 403

**B IBKR / CME**

- B1 https://www.interactivebrokers.com/campus/ibkr-api-page/trader-workstation-api/
- B2 https://ibkrcampus.com/docs/tws-api/doc/quick-start/placing-orders.md
- B3 https://ibkrcampus.com/docs/web-api/introduction.md
- B4 https://ibkrcampus.com/docs/web-api/api/web-api/placing-orders.md
- B5 https://ibkrcampus.com/docs/tws-api/doc/notes-limitations/limitations/paper-trading.md
- B6 https://www.ibkrguides.com/clientportal/papertradingaccount.htm
- B7 https://www.ibkrguides.com/clientportal/aboutpapertradingaccounts.htm
- B8 https://ibkrcampus.com/docs/tws-api/doc/download-the-tws-api/install-the-tws-api-on-mac-os-linux.md
- B9 https://www.interactivebrokers.com/en/pricing/commissions-futures.php
- B10 https://www.interactivebrokers.com/en/index.php?f=5041
- B11 https://ibkrcampus.com/docs/tws-api/doc/market-data-historical/introduction.md
- B12 https://ibkrcampus.com/docs/tws-api/doc/market-data-historical/historical-data-limitations/introduction.md
- B13 https://ibkrcampus.com/docs/web-api/getting-started.md
- B14 Client Portal 页脚监管陈述（B6/B7 同页）
- B15 https://pypi.org/pypi/ibapi/json
- B16 https://ibkrcampus.com/docs/tws-api/doc/contracts-financial-instruments/the-contract-object.md
- （未打开原文）www.cmegroup.com → 403

**C Kraken / Bitnomial**

- C1 https://bitnomial.com/exchange/docs/api/overview/
- C2 https://bitnomial.com/exchange/docs/api/rest/overview/
- C3 https://bitnomial.com/exchange/docs/api/rest/orders/
- C4 https://bitnomial.com/exchange/docs/api/environments/
- C5 https://www.kraken.com/features/derivatives
- C6 https://bitnomial.com/
- C7 https://bitnomial.com/exchange
- C8 https://bitnomial.com/exchange/docs/market-operations/settlements/digital-asset-perpetual-pricing/
- C9 https://bitnomial.com/exchange/docs/api/rest/funding-rates/
- C10 https://bitnomial.com/exchange/docs/api/rest/charts/
- C11 https://bitnomial.com/exchange/docs/api/btp/order-entry/
- C12 https://docs.kraken.com/exchange/guides/futures.md （demo-futures = **non-US**）
- C13 https://docs.kraken.com/api-reference/historical-funding-rates.md （**non-US**）
- C14 https://bitnomial.com/exchange （费率段）
- C15 https://www.kraken.com/features/fee-schedule （Futures % = **non-US**）
- C16 https://docs.kraken.com/home/sdks.md ；https://docs.kraken.com/llms.txt
- C17 https://www.kraken.com/features/api
- C-non-US 对照：https://docs.kraken.com/exchange/guides/overview.md ；https://docs.kraken.com/api-reference/order-management/send-order.md ；https://futures.kraken.com/derivatives/api/v3/instruments （无 key GET，仅核 PF_ 前缀）

## 6. 未决 / 未找到官方资料（不推测）

- Coinbase Advanced 完整费率阶梯原文；CFM 州限制与最低资金；sandbox 是否含任何一个 `*-CDE` 产品。
- CME 官网合约规格与保证金（本节点 403）。
- IBKR 加密期货交易权限/适当性测试逐条；paper 是否对 MBT/BRR 有额外限制。
- Kraken Derivatives US 是否计划把 Bitnomial 下单暴露到 Kraken REST；C-US maker/taker %；C-US 杠杆上限数字。
- Bitnomial REST Products 的准确公开路径（文档写相对 `.../prod/`，本节点若干猜测 URL 404；**未用认证、未继续探测**）。
- NFA BASIC 公司名页为动态加载，本卡未读到 CFM / NinjaTrader 的静态 HTML 主体。

## 7. 文档矛盾（只报不修）

1. **ADR-0001 D1.6–D1.7 / D1.10** 仍把加密 paper 写成 Binance demo / Bybit / OKX demo / Deribit test / Hyperliquid testnet / `demo-futures.kraken.com`。D1.9 又把实盘候选写成 Coinbase Advanced/CDE、Kraken Derivatives US、CME via IBKR。QNT-33 若选 A/B/C-US，必须改 ADR allowlist——与「美国合规执行」同时成立。本卡不改 ADR。
2. **ADR-0001 Alternatives** 已 REJECT「IBKR paper 作为默认」，本卡排序却因 paper 覆盖把 IBKR 放第一。这是排序键执行结果，不是推翻 ADR；owner 须二选一或改 ADR。
3. **ADR-0001 D1.9** 旧文曾被 verify 指出「Kraken US API 未验证却称 Coinbase 唯一」。本卡把 C-US API 核成「行情 REST 有、零售下单 REST 未找到」，与该未决项同向。
4. **仓库 `AGENTS.md`** 产品句「美股 + 美股期权 + 加密合约」vs 既有调研同时覆盖现货数据（QNT-23 已报）。本卡不修。
5. **Kraken Pro 营销页** FAQ 两处写 “all **0** contracts” 支持盘中保证金——与同页「16 crypto perpetual markets」矛盾。当页面 bug，不以 0 为合约数。
6. **Coinbase US Derivatives 指南** beta「只收 0.05%」vs 营销页「maker 低至 0.005% + $0.15/张」。两份都是官方，并存；未取到 advanced-fees 原文裁哪份当前有效。
7. **`docs/research/` 无 README 索引**。派发写「可能的 README 索引行」；目录现无 README，本卡不新建（避免范围外文件）。

## 8. 本卡未做（硬边界）

- 未注册 Coinbase / IBKR / Kraken / Bitnomial 账户。
- 未生成 API key、未跑官方「Create an API key / Sign Up demo」流程。
- 未向任何 host POST 订单（含 sandbox `POST /orders`、IBKR `placeOrder`、Kraken `sendorder`、Bitnomial BTP）。
- 未读取 vault 中任何交易所凭据。
- 公开 GET 仅：Coinbase public products、Kraken Futures instruments（对照 C-non-US）、CDE funding-rate（401 即停）。
