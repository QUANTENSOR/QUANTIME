# 加密市场数据源全景：CEX 现货+合约 / DEX 现货+永续 / 链上

- 调研日期：2026-09-18；探测节点：美国佛州（出口 IP 134.56.13.103），**未使用代理，未注册任何账号，未接触任何交易所账号**；探针只做公共 GET
- 探针脚本：`docs/research/probes/cex_public_crypto.py`（29 项，25 通过）、`onchain_dex_crypto.py`（13 项，10 通过）；汇总 `probes/results.md`
- 范围：仅市场数据。交易 API 能力（testnet/权限/美国资格）已在 [QNT-4](mention://issue/01a0adaa-9484-71a8-94c2-d1e564cae655) 覆盖，本文不重复。
- 维度编号同 [data-sources-cn-equity.md](data-sources-cn-equity.md)；总索引见 [data-sources-index.md](data-sources-index.md)

## 0. 结论速览

| 结论 | 依据 |
|---|---|
| **美国节点可达性是第一约束**：`api.binance.com` / `fapi` → **HTTP 451**（"restricted location"），`api.bybit.com` → **403 CloudFront 国别封锁**；但 **`data.binance.vision` bulk zip、`api.binance.us`、`public.bybit.com` bulk CSV 均可达**；OKX / Bitget / Gate / Coinbase / Kraken / Kraken Futures / Deribit / Hyperliquid / dYdX 公共 REST 全部 200 | §7 表 A |
| **免费且最干净的历史底座 = Binance Vision zip + OKX 官方历史文件**：Vision 月度 zip 现货 2017-08 起，U 本位 klines 2020-01 起（实测索引 80 个月）、fundingRate 月文件（实测 93 行/月）、metrics 日文件（OI + 多空比，5 分钟 288 行/日）；OKX `market-data-history` zip（1m K/资金费率/逐笔/盘口，T+2）。两者无 key、文件不可变带 CHECKSUM | §1.1、§1.2、§7 |
| **REST 回看深度差异极大**：Gate 合约 2000 根（2021-03 起）、Kraken Futures 4 年窗口 1460 行、Deribit/Hyperliquid 4 年 1461 行、OKX `history-candles` 100/次可翻页（实测 14 页 1100 行 → 2023-09，草稿另测可回到 2018-12）、Coinbase 300/次、**Kraken 现货仅最近 720 根**、Bitget `history-candles` 200/次、Binance.US 1000 根 | §7 表 A |
| **资金费率 / OI 历史免费长期源只有 Binance Vision**（fundingRate 2020-01 起、metrics 2020-09 起）；OKX REST funding 仅 3 个月、OI 1D 自 2024-01；Bitget/Gate 90/180 天 → 必须常驻采集或靠 zip 回补 | §1.1–1.5 |
| **强平历史几乎没有免费长期源**：Vision `liquidationSnapshot` 前缀为空；各所 REST 只给近几天；长期只有 Tardis（付费）或 Coinalyze（免费，日线永久保留、日内滚动） | §1.11、§2 |
| **聚合商免费层对落库不友好**：CoinGecko Demo 仅 365 天（`days=max` → 401，实测）且 ToS 要求 24h 内刷新缓存、禁止存储原始数据；CoinPaprika 免费层历史 → 402；CoinDesk Data（CryptoCompare）2026-05-21 起取消免费层 | §1.10、§7 表 B |
| **DEX/链上免费可用**：DefiLlama（ETH TVL 2017-09 起 3279 行、Uniswap 日成交量 2018-11 起 2878 行、coins.llama 日价格；衍生品成交量端点 → 402 Pro 专属）、GeckoTerminal 池级日 OHLCV（免费 30/min，历史 6 个月/365 行）、DexScreener 仅快照无 OHLCV、blockchain.com / mempool.space BTC 链上序列 | §1.12–1.14、§7 表 B |
| **许可**：交易所条款普遍"仅个人/内部使用、禁止再分发"；OKX API Agreement §9.4（2026-07-28）明写"非商业"；Coinbase Market Data Terms 最严（禁止用于构建指数/基准）；Binance.com / Bybit / OKX global / Deribit 交易端均排除美国人（数据端不检查，但合规灰区） | §1、§4 |

## 1. 逐源评估

### 1.1 Binance（binance.com REST 451；Vision zip / Binance.US 可达）— 已实测
- ① REST：现货、USDT-M/COIN-M 永续与交割、期权（eapi）、资金费率、OI 统计、mark/index/premium、盘口、逐笔、强平 WS。**Bulk zip（`data.binance.vision`）**：`spot/{daily,monthly}/{aggTrades,klines,trades}`；`futures/um`：aggTrades、bookDepth（2023-01 起）、bookTicker、indexPriceKlines、klines、markPriceKlines、**metrics**（2020-09-01 起；`sum_open_interest`、OI value、顶级/全体多空比、taker 多空量比，5 分钟）、premiumIndexKlines、trades；monthly 另有 **fundingRate**（BTCUSDT 2020-01 起）；`futures/cm` 同构；`option/` 仅 BVOLIndex + EOHSummary（**2023-10-23 停更**）；`liquidationSnapshot` 前缀**为空**。② K 线 1s–1mo；日文件次日发布、月文件每月第一个周一。③ 现货 2017-08-17 起；实测 um 1d 月文件索引 2020-01 → 2026-08 共 80 个月。④ 免费。⑤ 现货 REST IP 权重 6000/min（草稿实测 `exchangeInfo.rateLimits`）；zip 无声明。⑥ 无 key，无 KYC。⑦ ToU 禁止未经书面同意"利用 Binance 行情的数据馈送/流服务"及"对 Binance 市场数据收费或获利"；内部使用未禁止（**条款编号未验证**——binance.com 从美国不可达；引文来自 Superalgos issue #1019）。⑧ zip（CSV）+ REST + WS。⑨ 活跃；`python-binance` 1.0.37（2026-06，MIT）。⑩ **zip 天然不可变、带 `.CHECKSUM` 可作幂等键**；REST 最后一根 K 线 `x=false` 未收盘需过滤；metrics 5 分钟快照直接 append。⑪ 美国：`api.binance.com`/`fapi` **451**（原文见 §7）；Vision ✅ 5/5（≤0.7s）；`api.binance.us` ✅ 1000 根 2023-12-24→；WS `fstream/dstream` 握手 101（草稿实测）。国内：binance.com 受 GFW 干扰，Vision S3（域名指向 ap-northeast-1，**推断**）通常可达（**未验证**）。
- 来源：<https://github.com/binance/binance-public-data> 、<https://developers.binance.com/docs/binance-spot-api-docs/rest-api/limits> 、<https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/Open-Interest-Statistics> 、<https://docs.binance.us/> 、<https://github.com/Superalgos/Superalgos/issues/1019>

### 1.2 OKX — 已实测（全部 200）
- ① REST：`/market/candles`（≤300，仅最近 1440 根）、`/market/history-candles`（实测 100/次翻页；草稿另测 BTC-USDT 1D 回到 2018-12、SWAP 到 2020-01）、`history-mark-price-candles`、`history-index-candles`、`/public/funding-rate-history`（**仅 3 个月**，100/次）、`/rubik/stat/contracts/open-interest-history`（最近 1440 条，1D 自 2024-01-01）、`/market/history-trades`（3 个月）、`/public/liquidation-orders`（近期，文档注"不代表全部强平"）。**官方历史文件 `GET /api/v5/public/market-data-history`**：module 1 逐笔、2 1 分钟 K、3 资金费率、4 400 档盘口、5 5000 档盘口（2025-11 起）；SPOT/FUTURES/SWAP/OPTION；T+2；返回 `static.okx.com/cdn/okex/traderecords/...zip` 直链（草稿实测 2024-01 月 K zip 1.13 MB）；文档注"回填进行中"。② 1s–1M；WS funding 30–90s、OI 3s。③ 见 ①。④ 免费。⑤ candles 40 req/2s/IP；history-candles 20 req/2s；funding 10 req/2s/(IP+instId)；history 文件 5 req/2s。⑥ 无 key。⑦ **API Agreement §9.4（2026-07-28）**："市场数据仅供个人、非商业交易使用；禁止转售/再分发；商业/大规模需单独数据许可"。⑧ REST/WS/zip。⑨ 活跃。⑩ K 线末位 `confirm` 字段，**只落 `confirm=1`**；funding 3 个月窗口 → 常驻采集，缺口靠 zip module 3 回补。⑪ 美国 ✅ 5/5；国内 ✅（**未验证**，okx.com 通常可达）。
- 来源：<https://www.okx.com/docs-v5/en/> 、<https://www.okx.com/docs-v5/en/#public-data-rest-api-get-historical-market-data> 、<https://www.okx.com/en-us/help/okx-api-agreement>

### 1.3 Bybit（REST 403；public.bybit.com 可达）— 已实测
- ① REST v5：kline ≤1000；mark/index/premium kline ≤1000；`funding/history` ≤200；`open-interest` 5min–1d ≤200/页 cursor，"至合约上线"；限流 600 req/5s/IP。**Bulk CSV `public.bybit.com`**：`trading/`（衍生品逐笔，BTCUSDT 自 **2020-03-25**，实测索引 2368 个日文件 → 2026-09-17）、`spot/`（2022-11 起）、`premium_index/`、`spot_index/`（1 分钟，2019-10 起）、`kline_for_metatrader4/`；**无 OI/资金费率/强平文件**；无官方说明页（**未验证**）。② 见 ①。④ 免费。⑥ 无。⑦ API Terms 禁止重新包装/转售/商业利用（**原文未验证**，页面超时）。⑨ 活跃；WS `liquidation` 2025-02-20 弃用 → `allLiquidation.{symbol}`。⑩ 逐笔 CSV 需自建 K 线；文件不可变。⑪ 美国：REST **403 CloudFront**（2/2，原文见 §7）；`public.bybit.com` ✅；`stream.bybit.com` WS 101（草稿实测）。
- 来源：<https://bybit-exchange.github.io/docs/v5/market/kline> 、<https://bybit-exchange.github.io/docs/v5/rate-limit> 、<https://bybit-exchange.github.io/docs/changelog/v5> 、<https://public.bybit.com/>

### 1.4 Bitget — 已实测（200，但 ToS 列美国为禁止国）
- ① v2 现货/合约 `candles` ≤1000、`history-candles` ≤200（探针 8 页得 720 行 2024-09-20→；草稿另测 1D 可回 2020-06）；`history-fund-rate` pageSize ≤100（实测）；`open-interest` 仅当前快照；v3 `history-candles` 仅 >90 天前、单次 90 天、limit≤100；`liquidations` 最近 **3 天**。⑤ 20 req/s/IP。⑥ 无。⑦ ToS 将 United States 列为 Prohibited Country，"Platform" 含 API → **美国节点合规灰区**。⑪ 美国 ✅ 1/1。
- 来源：<https://www.bitget.com/docs/catalog/market/derivatives> 、<https://www.bitget.com/support/articles/360014944032-terms-of-use>

### 1.5 Gate.io — 已实测
- ① 现货 candlesticks ≤1000；合约 ≤**2000**（实测 2000 行 2021-03-29→2026-09-18，单次 1.27s）；`funding_rate` ≤1000 但 `from` ≥ **180 天**；`contract_stats`（OI/多空比 5m/1h/1d）同 180 天；`liq_orders` ≤1000 且 from/to ≤1 小时。⑤ **200 req/10s/endpoint/IP**（2024-01-22 起）。⑦ 未验证（文档站对 curl 403）。⑪ 美国 ✅。
- 来源：<https://www.gate.com/announcements/article/33995>

### 1.6 Coinbase（Exchange / Advanced Trade / INTX）— 已实测
- ① Exchange candles ≤**300**/次，粒度 60–86400s（实测 5 页 1500 行 2022-08-11→）；"无成交区间不产生数据"；Advanced Trade candles ≤350；INTX 永续 candles 美国无鉴权可取（草稿实测）。⑤ 公共 10 req/s/IP（burst 15）；INTX 100 req/s。⑥ 无。⑦ **Market Data Terms 最严**：禁止向组织外再分发、禁止用于构建指数/基准/估值。⑪ 美国 ✅ 2/2。
- 来源：<https://docs.cdp.coinbase.com/api-reference/exchange-api/rest-api/products/get-product-candles.md> 、<https://www.coinbase.com/legal/market_data>

### 1.7 Kraken 现货 / Kraken Futures — 已实测
- 现货 ① OHLC **只返回最近 720 根**（实测 721 行 2024-09-28→；`since` 无法翻旧）；`Trades` ≤1000/次纳秒游标，草稿实测可从 2013-10-06 第一笔翻到今天 → **全量逐笔自建 K 线**。⑤ 无 IP 数字（支持页 ~1 req/s，**未验证**）。
- Futures ① `/api/charts/v1/{spot|mark|trade}/{sym}/{res}` 单次 ≤2000（`more_candles` 翻页；实测 4 年窗口 1460 行 2022-09-20→）；`historical-funding-rates` 无分页约 1 年小时值；`executions` ≤1000/页。⑤ 公共端点无成本；`/history` 100 tokens/10min。⑪ 美国 ✅ 3/3。
- 来源：<https://docs.kraken.com/api-reference/market-data/get-ohlc-data.md> 、<https://docs.kraken.com/api-reference/market-data/get-recent-trades.md> 、<https://docs.kraken.com/exchange/guides/futures/ratelimits.md>

### 1.8 Deribit — 已实测（公共 REST 200；交易端禁止美国居民）
- ① `get_tradingview_chart_data` 1–720,1D（实测 4 年 1461 行；草稿实测单次静默截断 ~5000 点）；`get_funding_rate_history` **静默截断 ~31 天/次**；`get_book_summary_by_currency`（**全链 OI/成交量/mark_iv 快照**，实测 930 个 BTC 合约）；`get_historical_volatility` ~16 天；`get_volatility_index_data`（DVOL）1000 点 + continuation。**无官方 bulk 下载**；期权链**无历史快照端点** → 只能自采或 Tardis/Laevitas/Amberdata。⑤ 500 credits/req，池 50,000，20 req/s 持续、100 突发（按会话，匿名 IP 数字 **未验证**）。⑦ ToS："市场/衍生数据仅供个人使用；禁止聚合、转售、发布、转发"。⑩ funding 31 天窗口需分片；期权链快照每日 insert 一份即为历史。⑪ 美国 ✅ 3/3。
- 来源：<https://docs.deribit.com/api-reference/market-data/public-get_tradingview_chart_data.md> 、<https://docs.deribit.com/articles/rate-limits.md> 、<https://support.deribit.com/hc/en-us/articles/29592500256669>

### 1.9 Hyperliquid / dYdX v4（DEX 永续）— 已实测
- Hyperliquid ① `candleSnapshot` 仅最近 **5000** 根（草稿 1m 实测返回 5212 → 文档矛盾）；实测 1d 4 年 1461 行 2022-09-19→；`fundingHistory` ≤500；`metaAndAssetCtxs` 含 mark/funding/OI（实测 BTC OI=35209）。⑤ 1200 weight/min/IP。S3 `hyperliquid-archive`（l2Book / asset_ctxs 含 OI/funding/mark）**requester-pays**，约月更、不保证完整；无 K 线文件。⑪ ✅ 2/2。
- dYdX v4 Indexer ① candles 1MIN–1DAY，candles/historicalFunding/trades ≤1000（实测错误文本）；实测 1041 行 2023-11-13→（主网 2023-10 上线，历史天然 <3 年）。⑤ **100 req/10s/IP**（实测单页较慢，12 页 6.2s）。⑪ ✅ 1/1。
- 来源：<https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/rate-limits-and-user-limits.md> 、<https://hyperliquid.gitbook.io/hyperliquid-docs/historical-data> 、<https://docs.dydx.xyz/concepts/trading/limits/rate-limits>

### 1.10 聚合商（CoinGecko / CoinMarketCap / CoinDesk Data / CoinPaprika / Coin Metrics / Messari）
| 源 | ① 覆盖 | ③ 历史 | ④ 价格 | ⑤ 限流 | ⑥ 认证 | ⑦ 许可 | ⑪ 实测 |
|---|---|---|---|---|---|---|---|
| **CoinGecko** | 币级价格/市值/量；`/derivatives` 仅当前 OI/funding | **Demo 365 天**（`days=max` → 401 error 10012，实测）；Basic 2 年；Analyst+ 10 年；>90 天自动日线 | Demo 免费 10k credits/月；Basic $35；Analyst $129；Lite $499 | Demo **100/min**（旧文 30/min） | Demo 需 key（探针无 key 走公共端点） | **必须署名**；**缓存须 24h 内刷新、禁止再分发/长期存储原始数据** → 与 append-only 冲突 | 365 天 ✅ 366 行；max ❌ 401；ohlc ✅ 92 行（365 天时 4 天粒度）；price ✅ |
| CoinMarketCap | 币级 OHLCV | Basic 无历史；Builder 3 年；Startup 起全历史（**未验证**） | Basic 免费 15k credits 50/min；Builder $29；Startup $79；Growth $299 | 见左 | Key | 禁止下载/存储 Content（除授权） | 未实测（需 key） |
| CoinDesk Data（前 CryptoCompare） | 指数、现货/期货 OHLCV、funding/OI | 多年 | **2026-05-21 起取消免费层**；需销售 | — | Key | 未验证 | 草稿实测无 key → 401 |
| CoinPaprika | 币级 OHLCV | 免费层**仅当日** | 付费档未验证 | — | 无 key | 未验证 | ❌ 402 "historical OHLCV before … not allowed in this plan" |
| Coin Metrics Community | BTC 31 个资产指标（PriceUSD、HashRate…）；candles/funding/OI/liquidations 目录**为空**（Pro 专属） | 长 | 免费；Pro 报价 | 10 req/6s/IP | 无 | **CC BY-NC 4.0** | 草稿实测 |
| Messari | 资产/市场 | — | Free/Lite/Pro（≈$29，**未验证**） | 200 req/min | Key | — | 未实测 |
- 来源：<https://www.coingecko.com/en/api/pricing> 、<https://www.coingecko.com/en/api_terms> 、<https://docs.coingecko.com/reference/coins-id-market-chart> 、<https://coinmarketcap.com/api/pricing/> 、<https://data.coindesk.com/blogs/changes-to-coindesk-data-indices-api-free-tier-access> 、<https://docs.coinmetrics.io/api/v4/> 、<https://docs.messari.io/api-reference/permissions>

### 1.11 付费专业供应商（Tardis / Kaiko / CoinAPI / Amberdata / Glassnode / Coinalyze / Laevitas / Velo / Nansen）— 未实测
| 源 | 覆盖 | 历史 | 价格 | 许可 | 备注 |
|---|---|---|---|---|---|
| **Tardis.dev** | trades、L2 增量、book_snapshot、quotes、**derivative_ticker（funding/OI/mark/index）**、**liquidations**、**options_chain**；Binance 全线、Bybit、OKX、Deribit（2019-10）、BitMEX、dYdX v4、Hyperliquid（2024-10-29 起） | 月付 4 个月 / 季付 12 个月 / 年付 4 年；Business 2019-03-30 起全量 | Academic $350–650；**Solo $700–1,200**；Pro $1,000–2,200；Business $3,000–6,000/月；**每月 1 号数据免费无 key** | 禁止再分发原始数据，**允许转售 ≥10 分钟聚合**；内部落库不禁止 | 唯一强平 + 期权链长历史；`tardis-dev` 5.0.0（MPL-2.0） |
| Kaiko | 100+ 所逐笔/盘口/衍生品/强平 | 2010 起 | L1 聚合 $1,000/月起；L2 $2,500/月起 | 机构 | — |
| CoinAPI | 400+ 所、Flat Files | 632 TB | PAYG $25 免费额度；Startup $79；Streamer $249；Pro $599 | 未验证 | — |
| Amberdata | 现货/衍生品/期权/DeFi | — | 报价制 | — | — |
| Glassnode | 链上 + 衍生品指标 | Advanced 4 年；Pro 15+ 年 | Advanced $49/月（年付，**无 API**）；Professional ≈$999/月（**未验证**） | 个人非商业；禁再分发 | 600 req/min |
| **Coinalyze** | 跨所聚合 OI/funding/predicted funding/**强平**/多空比/OHLCV，1min–daily | 日内滚动 1500–2000 根；**日线不删** | 免费 | 公开使用请署名；无存储禁令 | 40 req/min/key（邮箱注册，**本次未注册**；草稿实测无 key 401） |
| Laevitas | 期权分析（Deribit/OKX/Bybit/Binance/HL） | 付费 5 年+ | Free 1 周无 API；Premium $50/席；**Enterprise $500/席含 API** | — | — |
| Velo Data | 跨所期货/期权/现货 1m CSV | 月付 3 个月；年付全量 | $199/月 | — | `velodata` 1.7.1 |
| Nansen | 链上钱包/资金流 | — | 免费 10 credits/日；Pro $49 | — | 15 rps |
- 来源：<https://tardis.dev/> 、<https://docs.tardis.dev/faq/billing-and-subscriptions> 、<https://docs.tardis.dev/legal/terms-of-service> 、<https://www.kaiko.com/products/market-data> 、<https://www.coinapi.io/products/market-data-api/pricing> 、<https://www.amberdata.io/pricing> 、<https://studio.glassnode.com/pricing> 、<https://api.coinalyze.net/v1/doc/> 、<https://www.laevitas.ch/pricing> 、<https://docs.velo.xyz/api> 、<https://www.nansen.ai/api>

### 1.12 DefiLlama — 已实测
- ① TVL（链级/协议级）、DEX 成交量、费用、代币历史价（`coins.llama.fi`）、收益、稳定币；**衍生品成交量 `summary/derivatives/*` → 402 Pro 专属**。② 日。③ ETH TVL 2017-09-27 起（3279 行）；Uniswap 日成交量 2018-11-02 起（2878 行）；coins.llama 日价格 span ≤500/次分页（实测 1463 行）。④ **免费无 key** ~500 req/min；Pro $300/月 1000 rpm。⑦ 开放数据，无明确许可（**未验证**）。⑨ `/protocol/uniswap` 全量 JSON 30s 超时（实测，改用链级端点）。⑩ 历史值可能随协议 adapter 修正而重算 → 每日 insert 快照并记 `fetched_at`。⑪ ✅ 4/5。
- 来源：<https://api-docs.defillama.com/> 、<https://docs.llama.fi/pro-api>

### 1.13 GeckoTerminal / DexScreener / Birdeye / Moralis — DEX 现货
- GeckoTerminal ① 池级 OHLCV day/hour/minute（实测 Uniswap v3 USDC/WETH 日线 365 行）；limit ≤1000、单次 ≤6 个月；免费历史 6 个月（Basic）/ 自 2021-09（Analyst+，走 CoinGecko onchain）。⑤ **30 calls/min**。⑦ "appreciate attribution"。⑪ ✅。
- DexScreener ① pairs/search/token 现价与 24h 量，**无 OHLCV 端点**（实测仅快照 `priceUsd=2478`）。⑤ 60 rpm（profiles）/300 rpm（pairs，**未验证**）。
- Birdeye（Solana+EVM OHLCV；Standard 免费 30K CU/月 1 rps；Starter $99；**未验证**，官网 403）；Moralis（EVM pair OHLCV 150 CU/次；Starter $149；免费层已下线 **未验证**）。
- 来源：<https://apiguide.geckoterminal.com/faq> 、<https://docs.coingecko.com/reference/pool-ohlcv-contract-address> 、<https://docs.dexscreener.com/api/reference> 、<https://birdeye.so/data-api/pricing> 、<https://moralis.com/pricing/>

### 1.14 链上 / 索引（The Graph / Dune / Bitquery / RPC / 协议自带 API）
- The Graph：Uniswap v3/v4 子图（pool hour/day data、swaps）；托管服务 2024-06-12 已关；免费 **100k 查询/月**，之后 **$2/100k**；需 Studio API key（**本次未注册**）。⑩ 子图可能重索引改写 → 记录 block number。
- Dune：任意 SQL；旧免费 2,500 credits/月；**2026-09-10 起 2026-07-21 前老账号变只读**（二手，**未验证**）；Analyst $65；Plus $349；API 15/40 rpm。公开内容允许商用。
- Bitquery：Personal $39（个人许可）/ Pro $79（商业）/ Scale $239。
- 原始 RPC 自建：Alchemy 免费 30M CU/月；QuickNode 免费 10M credits/月 15 RPS。
- 协议自带：GMX `arbitrum-api.gmxinfra.io/prices/candles` 1m–1d ≤10000/次免费；Curve `api.curve.finance/v1/`；Aevo 期权/永续 REST+WS；**Drift → Velocity**（2026-04-01 被盗约 $280M，07-01 更名；`data.velocity.exchange` 31 天滚动 + 2022 起归档 CSV）；**Flipside** 数据业务 2026-05-19 被 SonarX 收购，文档站失效 → 不可用。
- BTC 链上（已实测）：blockchain.com charts API hash-rate 1450 行 2022-09→；mempool.space hashrate 1096 行（自托管节点 API）。
- 来源：<https://thegraph.com/studio-pricing/> 、<https://developers.uniswap.org/docs/ecosystem/subgraphs/overview> 、<https://docs.dune.com/learning/how-tos/pricing-faqs> 、<https://docs.dune.com/api-reference/overview/rate-limits> 、<https://bitquery.io/pricing> 、<https://www.alchemy.com/pricing> 、<https://www.quicknode.com/pricing> 、<https://docs.gmx.io/docs/api/rest-api/oracle-prices/> 、<https://github.com/curvefi/curve-api> 、<https://api-docs.aevo.xyz/> 、<https://docs.velocity.exchange/historical-data/historical-data-v2> 、<https://www.sonarx.com/blog/sonarx-acquires-flipside-crypto-blockchain-data-business>

### 1.15 Python 库（PyPI，2026-09-18）
| 包 | 版本 | 上传 | 许可 | 要点 |
|---|---|---|---|---|
| ccxt | 4.5.78 | 2026-09-07 | MIT | fetchOHLCV 全所；fetchFundingRateHistory：binance/bybit/okx/deribit/krakenfutures/bitmex/hyperliquid ✓，coinbase/kraken ✗；fetchOpenInterestHistory：binance/bybit/okx ✓；fetchLiquidations：deribit/bitmex ✓；CCXT Pro（WS）已免费并入 |
| cryptofeed | 2.5.0 | 2026-08-09 | **PyPI 元数据 XFree86-1.1 vs GitHub LICENSE AGPL — 矛盾** | TRADES/L2_BOOK/FUNDING/OPEN_INTEREST/LIQUIDATIONS/CANDLES；Py≥3.12 |
| python-binance | 1.0.37 | 2026-06-08 | MIT | — |
| pycoingecko | 3.2.0 | 2024-11-13 | MIT | 近 2 年无更新 |
| tardis-dev | 5.0.0 | 2026-08-23 | MPL-2.0 | — |
| velodata | 1.7.1 | 2026-01-15 | — | — |
- 另：**BitMEX 宣布 2026-09-23 关闭**（草稿摘录，**未验证原文**）→ 不纳入。

## 2. 汇总对比表（按需求维度）

| 需求 | 免费最佳 | 付费最佳 | 美国可达 | append-only 注意 |
|---|---|---|---|---|
| 现货日线/分钟 K | Binance Vision zip（2017-08 起）；OKX zip；Kraken Trades 全量自建；Coinbase 300/次翻页 | Tardis / Kaiko | ✅（Vision）；Binance REST ❌ | 只落已收盘；zip CHECKSUM 去重 |
| 永续 K / mark / index / premium | Binance Vision um/cm（2020-01 起）；OKX history-candles + zip；Gate 2000 根；Kraken Futures 2000/次 | Tardis | ✅ | 同上 |
| 资金费率历史 | Binance Vision monthly fundingRate（2020-01 起）；OKX zip module 3；Kraken Futures ~1 年 | Tardis derivative_ticker | ✅ | OKX REST 仅 3 个月 → 常驻采集 |
| OI 历史 | Binance Vision metrics（2020-09 起，5 分钟）；Coinalyze（日线永久，需注册 key） | Tardis | ✅ | Binance REST 仅 30 天；OKX 1D 自 2024-01 |
| 强平 | Binance WS `!forceOrder@arr`；Bybit `allLiquidation` WS；OKX `liquidation-orders`；Coinalyze 聚合 | **Tardis liquidations**（唯一长期历史） | WS ✅（Bybit REST ❌） | 实时流自采自存，无法回补 |
| 期权链 / IV | Deribit `book_summary` + DVOL 定时快照（无 bulk）；Binance Vision option 已停更 | Tardis options_chain；Laevitas $500/席；Amberdata | ✅ | Deribit funding 31 天静默截断需分片 |
| 盘口深度 | Binance Vision bookDepth（2023-01 起，±5% 分档）；OKX zip 400/5000 档 | Tardis L2；Kaiko | ✅ | — |
| 逐笔 | Binance Vision trades/aggTrades；Bybit public CSV（2020-03 起）；OKX zip；Kraken 全量 | Tardis | ✅ | — |
| 币级聚合价格/市值 | DefiLlama coins.llama（无 key）；CoinGecko Demo 365 天（存储受限） | CoinGecko Analyst $129；CMC Startup $79 | ✅ | CoinGecko ToS 24h 缓存限制 |
| DEX 现货 | GeckoTerminal 池级 OHLCV（6 个月）；DefiLlama 成交量；The Graph 100k/月 | Bitquery / Dune / CoinGecko onchain | ✅ | 子图重索引 → 记 block number |
| DEX 永续 | Hyperliquid 5000 根；dYdX v4 2023-11 起；GMX 10000/次 | Tardis（HL 2024-10 起） | ✅ | HL S3 requester-pays |
| 链上 | DefiLlama TVL（2017 起）；blockchain.com / mempool.space；Coin Metrics Community（CC BY-NC） | Glassnode / Nansen / Dune | ✅ | TVL 可能重算 → 快照 + fetched_at |

## 3. 推荐组合（供 owner 裁决）

- **方案 A —— 零成本官方 bulk 底座（推荐起步）**：Binance Vision zip（现货 + um/cm：klines/fundingRate/metrics/bookDepth/aggTrades）+ OKX `market-data-history` zip（1m K/资金费率/逐笔/盘口，含 OPTION）+ OKX REST 增量（history-candles、funding-rate-history、OI history、liquidation-orders）+ Deribit REST（DVOL、book_summary 每日快照）+ 常驻 WS 强平/OI 采集（Binance fstream `!forceOrder@arr`、OKX、Bybit `allLiquidation`）。优点：全部美国可达、无 key、文件不可变利于重放。缺点：强平历史从上线日起；期权链历史缺失；许可是"内部使用"灰区；常驻 WS 进程与"常驻检出只读"纪律需裁决。
- **方案 B —— Tardis.dev Solo/Pro（$700–2,200/月）**：一站式逐笔 + derivative_ticker + **liquidations + options_chain**，2019 起（年付），ToS 允许 ≥10 分钟聚合再分发。仅当需要期权链/强平长历史时启用；可先用"每月 1 号免费数据"做质量对照。
- **方案 C —— CCXT 多所 REST（低成本广覆盖）**：ccxt 4.5.78 统一 fetchOHLCV / fetchFundingRateHistory / fetchOpenInterestHistory 跨 OKX、Bitget、Gate、Kraken Futures、Hyperliquid、dYdX、Coinbase（Binance/Bybit 在美国节点需代理或改用 Binance.US/Vision）。缺点：回看深度差异大（Kraken 720、Bitget 90 天、Gate 180 天、Binance OI 30 天）；适合作为"多所交叉校验/增量"层而非唯一历史源。
- **建议**：A 为主，C 为跨所校验，B 按需（期权/强平）。若日线为主研究粒度，A + Coinalyze（免费日线 OI/funding/强平聚合，署名即可，需 owner 注册 key）已足够。

## 4. 待裁决清单（owner 回字母）

1. 许可边界：交易所条款均"仅个人/内部使用"，OKX 明写"非商业"。**A** 接受内部研究灰区 / **B** 只用许可明确的付费源（Tardis/Kaiko）/ **C** 先咨询后定。
2. Binance 路径：**A** 只用 Vision zip + WS + Binance.US（不碰 binance.com REST）/ **B** 允许代理访问 binance.com REST（ToU 风险）。
3. Bitget（ToS 列美国为禁止国）：**A** 纳入 / **B** 排除。
4. 强平数据：**A** 仅从上线日自采 / **B** 购买 Tardis 回补。
5. 期权：**A** Deribit 快照自采 / **B** Laevitas $500/席 / **C** Tardis options_chain。
6. 付费预算（$200–1,200/月：Velo $199 / DefiLlama Pro $300 / Tardis Solo $700+）：**A** 有 / **B** 无。
7. CoinGecko（ToS 24h 缓存、禁存原始数据）：**A** 放弃作落库源，仅参考价 / **B** 购买 Analyst 并确认存储条款 / **C** 不用。
8. DEX/链上是否进入 v1：**A** 是 / **B** 推迟。
9. 常驻 WS 采集进程：**A** 允许 / **B** 不允许（仅 zip + REST 增量）。
10. 国内节点：**A** 需要（GFW 对 binance.com/bybit.com 影响未实测）/ **B** 不需要。

## 5. 信息来源

- Binance：<https://github.com/binance/binance-public-data> 、<https://developers.binance.com/docs/binance-spot-api-docs/rest-api/limits> 、<https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/Open-Interest-Statistics> 、<https://developers.binance.com/docs/binance-spot-api-docs/web-socket-streams> 、<https://docs.binance.us/> 、S3 列表 `https://s3-ap-northeast-1.amazonaws.com/data.binance.vision?delimiter=/&prefix=data/futures/um/monthly/klines/BTCUSDT/1d/`（实测）
- OKX：<https://www.okx.com/docs-v5/en/> 、<https://www.okx.com/en-us/help/okx-api-agreement>
- Bybit：<https://bybit-exchange.github.io/docs/v5/market/kline> 、<https://bybit-exchange.github.io/docs/v5/market/open-interest> 、<https://bybit-exchange.github.io/docs/v5/rate-limit> 、<https://bybit-exchange.github.io/docs/changelog/v5> 、<https://public.bybit.com/trading/BTCUSDT/>（实测）
- Bitget：<https://www.bitget.com/docs/catalog/market/derivatives> 、<https://www.bitget.com/support/articles/360014944032-terms-of-use>
- Gate：<https://www.gate.com/announcements/article/33995> 、<https://www.gate.com/docs/developers/futures/ws/en/>
- Coinbase：<https://docs.cdp.coinbase.com/api-reference/exchange-api/rest-api/products/get-product-candles.md> 、<https://docs.cdp.coinbase.com/exchange/introduction/rate-limits-overview.md> 、<https://docs.cdp.coinbase.com/international-exchange/introduction/rate-limits-overview.md> 、<https://www.coinbase.com/legal/market_data>
- Kraken：<https://docs.kraken.com/api-reference/market-data/get-ohlc-data.md> 、<https://docs.kraken.com/api-reference/market-data/get-recent-trades.md> 、<https://docs.kraken.com/exchange/guides/futures/ratelimits.md>
- Deribit：<https://docs.deribit.com/api-reference/market-data/public-get_tradingview_chart_data.md> 、<https://docs.deribit.com/articles/rate-limits.md> 、<https://support.deribit.com/hc/en-us/articles/29592500256669>
- Hyperliquid / dYdX：<https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/rate-limits-and-user-limits.md> 、<https://hyperliquid.gitbook.io/hyperliquid-docs/historical-data> 、<https://docs.dydx.xyz/concepts/trading/limits/rate-limits> 、<https://docs.dydx.xyz/indexer-client/websockets>
- 聚合商/付费：见 §1.10、§1.11 各节链接
- DEX/链上：见 §1.12–1.14 各节链接；<https://api.blockchain.info/charts/hash-rate> 、<https://mempool.space/api/v1/mining/hashrate/3y>（实测）
- PyPI：<https://pypi.org/project/ccxt/> 、<https://pypi.org/project/cryptofeed/> 、<https://pypi.org/project/python-binance/> 、<https://pypi.org/project/pycoingecko/> 、<https://pypi.org/project/tardis-dev/>

## 6. 未验证项 / 文档矛盾（只报不修）

**未验证**：Binance ToU 禁再分发条款条号与原文（美国不可达）；Bybit API Terms 原文、public.bybit.com 官方说明页；Bitget `history-mark/index-candles` limit；Coinbase Advanced Trade 公共 10 req/s；Deribit `history.deribit.com` 是否官方、匿名 IP 限流数字；Kraken 现货公共限流精确值；CMC 各档历史门槛原文；CoinDesk Data 付费价格；Glassnode Pro ≈$999、Messari Pro ≈$29、Coin Metrics Pro 价格；Dune 2026-09-10 只读政策；DexScreener 300 rpm；Birdeye/Moralis 价格；The Graph 免费层每分钟限流；DefiLlama 数据许可；GeckoTerminal 无 key 端点是否限 6 个月；BitMEX 关闭公告原文；国内节点对 binance.com / bybit.com / data.binance.vision 的可达性；Vision S3 位于 ap-northeast-1 为推断。

**文档矛盾**：
- cryptofeed：PyPI `license` 元数据 "XFree86-1.1" vs GitHub LICENSE AGPL。
- CoinGecko Demo 限流：旧支持文章 30/min vs 现行 docs/定价页 100/min。
- Binance `binance-public-data` README 仅列 aggTrades/klines/trades，S3 实际另有 bookDepth/bookTicker/metrics/fundingRate/mark/index/premium klines/option 目录；`liquidationSnapshot` 前缀存在但无文件。
- Kraken Futures 历史资金费率端点：正确路径 `historical-funding-rates`（连字符），文档旧写法 `historicalfundingrates` → 404。
- Hyperliquid 文档 candleSnapshot "最多 5000 根"，实测 1m 返回 5212。

## 7. 探针实测输出摘要（2026-09-18 03:5x UTC，美国节点）

**表 A `cex_public_crypto.py`（29 项，25 通过）**

| source | market | check | ok | 耗时 s | 行数 | 起 | 止 | 备注 / 错误原文 |
|---|---|---|---|---|---|---|---|---|
| binance | spot | `api.binance.com` klines 1d | ❌ | 0.04 | | | | `HTTP 451: {"code":0,"msg":"Service unavailable from a restricted location according to 'b. Eligibility' in https://www.binance.com/en/terms…"}` |
| binance | perp | `fapi.binance.com` klines 1d | ❌ | 0.04 | | | | 同上 451 |
| binance_us | spot | `api.binance.us` klines 1d limit=1000 | ✅ | 0.83 | 1000 | 2023-12-24 | 2026-09-18 | |
| binance_vision | spot | monthly zip `spot/monthly/klines/BTCUSDT/1d/…2026-08.zip` | ✅ | 0.23 | 31 | | | 2185 bytes |
| binance_vision | perp | monthly zip `futures/um/monthly/klines/…1d/…2026-08.zip` | ✅ | 0.19 | 31 | | | 2115 bytes |
| binance_vision | perp_funding | `futures/um/monthly/fundingRate/BTCUSDT/…2026-08.zip` | ✅ | 0.50 | 93 | | | 8h 结算 ×31 天 |
| binance_vision | perp_metrics_oi | `futures/um/daily/metrics/BTCUSDT/…2026-09-15.zip` | ✅ | 0.50 | 288 | | | 5 分钟 OI/多空比 |
| binance_vision | perp | S3 列表 `futures/um/monthly/klines/BTCUSDT/1d/` | ✅ | 0.72 | 80 | 2020-01 | 2026-08 | 80 个月文件 |
| okx | spot | `history-candles` BTC-USDT 1Dutc 100/次 ×14 页 | ✅ | 1.94 | 1100 | 2023-09-15 | 2026-09-18 | 探针页数上限，非 API 上限 |
| okx | perp | `history-candles` BTC-USDT-SWAP | ✅ | 1.93 | 1100 | 2023-09-15 | 2026-09-18 | |
| okx | perp | ticker | ✅ | 0.17 | 1 | | | `last=77347.5` |
| okx | perp_funding | `funding-rate-history` limit=100 | ✅ | 0.18 | 100 | 2026-08-16 | 2026-09-18 | 可用 `after` 翻页（≤3 个月） |
| okx | perp_oi | `rubik/stat/contracts/open-interest-history` 1D | ✅ | 0.26 | 100 | 2026-06-10 | 2026-09-17 | |
| bybit | perp | `api.bybit.com` v5 kline linear | ❌ | 0.04 | | | | `HTTP 403: { error:The Amazon CloudFront distribution is configured to block access from your country }` |
| bybit | spot | 同上 spot | ❌ | 0.01 | | | | 同上 403 |
| bybit_public | perp | `public.bybit.com/trading/BTCUSDT/` 索引 | ✅ | 0.31 | 2368 | 2020-03-25 | 2026-09-17 | 逐笔日文件 |
| bitget | perp | `history-candles` 1D limit=200 ×8 页 | ✅ | 1.51 | 720 | 2024-09-20 | 2026-09-16 | 草稿另测 1D 可回 2020-06 |
| coinbase | spot | Exchange candles 86400 300/次 ×5 | ✅ | 0.41 | 1500 | 2022-08-11 | 2026-09-18 | |
| coinbase | spot | ticker | ✅ | 0.02 | 1 | | | `price=77308.14` |
| kraken | spot | OHLC 1440 | ✅ | 0.16 | 721 | 2024-09-28 | 2026-09-18 | **最多 720 根**（官方限制） |
| kraken_futures | perp | `charts/v1/trade/PF_XBTUSD/1d` 4 年窗口 | ✅ | 0.17 | 1460 | 2022-09-20 | 2026-09-18 | |
| kraken_futures | perp | tickers | ✅ | 0.38 | 1 | | | `last=77319 fundingRate=0.779…` |
| deribit | perp | `get_tradingview_chart_data` BTC-PERPETUAL 1D 4 年 | ✅ | 0.27 | 1461 | 2022-09-18 | 2026-09-17 | |
| deribit | perp | ticker | ✅ | 0.10 | 1 | | | `last=77325 funding_8h=6.82e-06 OI=764620660` |
| deribit | option | `get_book_summary_by_currency` BTC option | ✅ | 0.11 | 930 | | | 全链 mark_iv/OI/volume 快照；**无历史链端点** |
| hyperliquid | perp_dex | `candleSnapshot` 1d 4 年 | ✅ | 0.22 | 1461 | 2022-09-19 | 2026-09-18 | 最多 5000 根 |
| hyperliquid | perp_dex | `metaAndAssetCtxs` | ✅ | 0.34 | 1 | | | `markPx=77349.1 funding=7.38e-06 OI=35209` |
| dydx_v4 | perp_dex | Indexer candles 1DAY 100/次 ×12 | ✅ | 6.20 | 1041 | 2023-11-13 | 2026-09-18 | 主网 2023-10 上线 |
| gate | perp | `futures/usdt/candlesticks` limit=2000 | ✅ | 1.27 | 2000 | 2021-03-29 | 2026-09-18 | |

**表 B `onchain_dex_crypto.py`（13 项，10 通过）**

| source | market | check | ok | 耗时 s | 行数 | 起 | 止 | 备注 / 错误原文 |
|---|---|---|---|---|---|---|---|---|
| coingecko | spot_agg | `market_chart` days=365 | ✅ | 0.09 | 366 | 2025-09-19 | 2026-09-18 | 免 key Demo 层 |
| coingecko | spot_agg | `market_chart` days=max | ❌ | 0.06 | | | | `HTTP 401: {"error":{"status":{"error_code":10012,"error_message":"Your request exceeds the allowed time range. P…` |
| coingecko | spot_agg | `ohlc` days=365 | ✅ | 0.04 | 92 | 2025-09-17 | 2026-09-16 | 4 天粒度 |
| coingecko | spot_agg | `simple/price` | ✅ | 0.05 | 2 | | | `btc=77326` |
| defillama | onchain_tvl | `v2/historicalChainTvl/Ethereum` | ✅ | 0.06 | 3279 | 2017-09-27 | 2026-09-18 | `/protocol/uniswap` 全量 30s 超时，改链级 |
| defillama | dex_spot_volume | `summary/dexs/uniswap` | ✅ | 0.02 | 2878 | 2018-11-02 | 2026-09-18 | |
| defillama | dex_perp_volume | `summary/derivatives/hyperliquid` | ❌ | 0.01 | | | | `HTTPError: 402 Client Error: Payment Required` → Pro 专属 |
| defillama | spot_agg | `coins.llama.fi/chart` span≤500 分页 | ✅ | 2.88 | 1463 | 2022-09-19 | 2026-09-18 | |
| geckoterminal | dex_spot | Uniswap v3 USDC/WETH 池 `ohlcv/day` | ✅ | 0.61 | 365 | 2025-09-19 | 2026-09-18 | limit ≤1000 |
| dexscreener | dex_spot | `pairs` 快照 | ✅ | 0.06 | 1 | | | `priceUsd=2478.08`；无历史 OHLCV |
| coinpaprika | spot_agg | `ohlcv/historical` | ❌ | 0.19 | | | | `HTTP 402: {"error":"Getting historical OHLCV data before 2026-09-17 … is not allowed in this plan…"}` |
| blockchain_com | onchain_btc | `charts/hash-rate` 4y | ✅ | 0.37 | 1450 | 2022-09-19 | 2026-09-17 | |
| mempool_space | onchain_btc | `mining/hashrate/3y` | ✅ | 0.09 | 1096 | 2023-09-19 | 2026-09-18 | |

**复现**：`cd docs/research/probes && python run_all.py cex_public_crypto onchain_dex_crypto`。探针只做公共 GET，不带任何 key，不触碰任何账户/下单端点。
