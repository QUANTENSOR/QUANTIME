# 美股数据源全景：股票 / ETF / 期权（对 QNT-2 / QNT-3 的增量）

- 调研日期：2026-09-18；探测节点：美国（出口 IP 134.56.13.103），**未使用代理，未注册任何账号，未接触任何券商账号**
- 探针脚本：`docs/research/probes/free_public_us.py`（14 项，13 通过；含 yfinance US 4 项与 SPY 期权链快照）、`stooq_cn_hk_us.py`（US 1 项，0 通过）；汇总 `probes/results.md`
- **本文不重复 QNT-2 / QNT-3 已给出的 17 家厂商结论**（Massive/Polygon、ThetaData、Databento、ORATS、Cboe DataShop、OptionMetrics、Tiingo、EODHD、Alpha Vantage、FMP、Nasdaq Data Link、Intrinio、Alpaca、Tradier、IBKR、yfinance、dolthub）。§0.1 只给一行摘要 + 链接；§1 是本次新增/补充的来源；§0.2 列出本次实测对 QNT-2/3 结论的**唯一一处偏差**。
- 维度编号同 [data-sources-cn-equity.md](data-sources-cn-equity.md)；总索引见 [data-sources-index.md](data-sources-index.md)

## 0. 结论速览

### 0.1 QNT-2 / QNT-3 已有结论（只链接，不重复）

| 来源 | QNT-2 / QNT-3 结论一行版 | 出处 |
|---|---|---|
| Massive（原 Polygon） | 数据合适（期权 per-contract 日线自 2014-06；Starter $29 起），但 Market Data ToS §2 "display use only" / §5(d) 禁 non-display / §8 终止须删 → 落库需 owner 裁定 | [QNT-2](mention://issue/01a0aca6-de88-7850-92d3-f0108d1654ec) §2.1、[QNT-3](mention://issue/01a0aca9-b19c-7d4b-b8fc-8e11d231ffc9) 分段 F |
| ThetaData | QNT-2 推荐主源（Standard $80：tick 自 2016，IV/Greeks）；Subscriber Agreement §8(e) 退订 30 天内 expunge | QNT-2 §2.3 |
| Databento | OPRA.PILLAR 自 2013-04；Standard $199/月含 13+ 年 L0；无 Greeks/IV；再分发最宽松但长期保留条款未从原文确认 | QNT-2 §2.1、QNT-3 F.1 |
| Cboe DataShop | Option EOD Summary 自 2012-01，一次性买断，"internal business purposes"，无退订删除条款 → 永久合规落库路径 | QNT-2 §2.1 |
| ORATS | EOD 链自 2007 含 Greeks/IV；个人 $99/月；历史回填 $599 一次性（搜索摘要） | QNT-3 F.1 |
| Alpaca Free | 股票 2016+（IEX）、期权历史仅 2024-02+，200 req/min；兼作 paper 券商 | QNT-2 §2.2 |
| Tiingo | 免费层 ToS §1.6(a) 禁持久化；付费可存但退订须删 | QNT-3 F.1/F.4 |
| EODHD / Alpha Vantage / FMP / Intrinio / Nasdaq Data Link / Tradier / IBKR / dolthub / OptionMetrics | 见 QNT-3 F.1 表；F.4 "不推荐"名单 | QNT-3 分段 F |
| yfinance | 非官方，personal use，退市缺失；仅 fallback/校验 | QNT-2 §2.2、QNT-3 F.4 |

### 0.2 本次实测对 QNT-2/3 的偏差

| 结论 | 依据 |
|---|---|
| **Cboe 免费延迟期权链 JSON（`cdn.cboe.com/api/global/delayed_quotes/options/SPY.json`）本节点可达**：2026-09-18 03:44 UTC 返回 200，**12,958 条合约**含 bid/ask/IV/greeks/OI（0.56s）。QNT-2 §2.2 / QNT-3 F.4 记为"禁止自动抓取、会封 IP → 不能作为管线源"。**不改变定性**（Cboe 页面条款确有禁抓取声明，本次未逐字复核 → 标"未验证"），但"技术上不可达"与本次实测不一致，建议在 index 待裁决中处理。 | §7 表 A |

### 0.3 本次新增来源的结论

| 结论 | 依据 |
|---|---|
| **免费官方结构性数据三件套均实测可用且适合 append-only**：Nasdaq Trader 符号目录（5,619 + 7,634 行，含 ETF 标志，`File Creation Time` 可作快照键）、SEC EDGAR XBRL（`company_tickers.json` 10,422；AAPL `Assets` 146 条 fact 2009-07→2026-07，每条带 `accn/filed/frame`）、FRED（DGS3MO 11,752 行 1981-09-01→2026-09-16，无 key CSV 备用路径） | §1.1–1.3、§7 |
| **Cboe CDN 免费文件**：VIX 日 OHLC 1990-01-02→2026-09-17（9,275 行）；全市场 P/C 比率 `totalpc.csv` 2006-11→2019-10（3,253 行；2019-10 后改为每日 JSON） | §1.4、§7 |
| **Stooq 本节点不可作自动化源**：`spy.us` 返回 JS PoW 挑战页（草稿另测：解 PoW 后 "Access denied"；批量 zip 401） | §1.7、§7 |
| **Finnhub 免费层已无 US 日线 K 线**（社区 issue #546，官方未回应）；Twelve Data 期权仅 Pro $229/月起；Marketstack 免费 100 次/月 → 三者对日线目的无价值 | §1.8 |
| **退市覆盖（幸存者偏差）最便宜路径**：Sharadar 直销个人价 Prices 全历史 $39/月、Bundle $69/月（$499/年），主键 (ticker,date) + `lastupdated`；但个人许可**明确排除专业/商业/组织用途** → 需裁决 | §1.5 |
| **期权 EOD 廉价补充**：Historical Option Data L2 5 年 $945 一次性 / 1 年 $315；MarketData.app Starter 年付 $144 含 5 年期权历史；两者均未在 QNT-2/3 定价 | §1.6 |
| IEX Cloud 已于 2024-08-31 关停（排除）；Norgate 仅 Windows（架构不匹配） | §1.9 |

## 1. 逐源评估（新增部分）

### 1.1 Nasdaq Trader 符号目录 — 已实测
- ① `nasdaqlisted.txt`（Nasdaq 上市）、`otherlisted.txt`（NYSE/Arca/BATS 等）、`nasdaqtraded.txt`、`options.txt`、`TradingSystemAddsDeletes.txt`；字段含 ETF 标志、Test Issue、Financial Status、Round Lot。② 每日多次更新；文件尾行 `File Creation Time`（实测 `0917202621:31`）。③ **仅当前快照**，无历史 → 自行每日归档重建增删/退市序列。④ 免费。⑤ 无声明。⑥ 无（HTTPS 与 FTP 均可）。⑦ Nasdaq 网站条款；参考数据一般可内部使用（**再分发条款未验证**）。⑧ 管道分隔文本。⑨ 官方，稳定。⑩ **推荐**：每日 insert 一份快照，键 = 文件创建时间，source=`nasdaqtrader`；可重放。⑪ 美国 ✅ 2/2（≤0.2s）；国内 **未验证**。
- 来源：<https://www.nasdaqtrader.com/trader.aspx?id=symboldirdefs> 、<https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt>

### 1.2 SEC EDGAR XBRL API（基本面）— 已实测
- ① 全部 SEC 申报人；`company_tickers.json`（ticker→CIK）、`companyfacts/CIK##########.json`、`frames/{taxonomy}/{concept}/{unit}/{period}`、`submissions`；bulk `companyfacts.zip`（草稿实测 1.41 GB，last-modified 2026-09-17）。② 随申报实时；bulk 每日约 03:00 ET 重编。③ XBRL 自 2009（大公司）。④ 全免费。⑤ **10 req/s**，超限自动封禁（官方未写时长）。⑥ 无 key，**必须** `User-Agent: 公司名 邮箱`（无 UA → 403，草稿实测）。⑦ 美国政府公共领域，可自由再分发。⑧ JSON / zip。⑨ 官方。⑩ **最佳 append-only 基本面源**：每条 fact 带 `accn/filed/frame/fy/fp`，天然 point-in-time；按日下载 zip 做全量 diff insert。⑪ 美国 ✅ 2/2；国内 **未验证**。
- Python：`edgartools` 5.58.0（2026-09-11，MIT，活跃）；`sec-edgar-api` 1.1.0（2023-09，停更）。
- 来源：<https://www.sec.gov/search-filings/edgar-application-programming-interfaces> 、<https://www.sec.gov/os/accessing-edgar-data>

### 1.3 FRED（无风险利率）— 已实测（无 key 路径）
- ① DGS1MO/DGS3MO/DTB3/DGS10/SOFR/EFFR 等。② 日更 T+1。③ DGS3MO 自 1981-09-01（实测）。④ 免费。⑤ 官方未公布数字（社区引 120 req/min，**未验证**）。⑥ 正式 API 需 `api_key`（**未注册**）；备用无 key `fred.stlouisfed.org/graph/fredgraph.csv?id=…`（非正式，实测可用）。⑦ 须展示 "This product uses the FRED® API but is not endorsed or certified by the Federal Reserve Bank of St. Louis"；国债系列为财政部数据无第三方版权。⑧ JSON/XML/CSV。⑨ 官方。⑩ 正式 API `observations` 支持 `realtime_start/realtime_end`（ALFRED vintage）→ 修订可重放，insert 时带 `realtime_start`。⑪ 美国 ✅（**注意**：浏览器 UA 超时、requests 默认 UA 正常，见 §7）。
- Python：`fredapi` 0.5.2（2024-05）；`pandas-datareader` 0.11.1（2026-06，Python ≥3.11）。来源：<https://fred.stlouisfed.org/docs/api/api_key.html> 、<https://fred.stlouisfed.org/docs/api/terms_of_use.html>

### 1.4 Cboe 免费 CDN 文件 + OCC — 已实测（Cboe）/ 草稿实测（OCC）
- Cboe ① 指数历史 `api/global/us_indices/daily_prices/{VIX,VIX9D,VIX3M,VVIX,SKEW}_History.csv`；期权市场日统计 `data/us/options/market_statistics/daily/{YYYY-MM-DD}_daily_options`（JSON：P/C、按品类成交与 OI；草稿实测 2022-06、2025-01 可用，2019-01 → 403）；旧 P/C 历史 `totalpc.csv`。② T+0 收盘后。③ VIX 1990 起；P/C 2006-11 起（分两段）。④ 免费。⑤ 无声明。⑥ 无。⑦ Cboe "Use of Content"，"不保证准确"（**再分发条款未逐字验证**）。⑧ CSV/JSON。⑨ 官方。⑩ 指数日线与市场级 P/C 可直接落 source=`cboe_cdn`。⑪ 美国 ✅ 3/3。
- 延迟期权链 JSON：见 §0.2。
- OCC（草稿实测）：`marketdata.theocc.com/series-search?symbolType=U&symbol=AAPL` 返回按合约 call/put OI 文本表；`mdapi/volume-totals` 仅近 5 日；历史统计页 Cloudflare 403；`volume-query` 参数 **未验证**。可作 OI 独立校验源（每日 insert 快照），但无公开文档。
- 来源：<https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv> 、<https://www.cboe.com/us/options/market_statistics/historical_data/> 、<https://marketdata.theocc.com/series-search?symbolType=U&symbol=AAPL>

### 1.5 Sharadar（直销 / Nasdaq Data Link）与 Norgate — 退市覆盖，未实测
- Sharadar ① SEP（EOD 价格 21,000 股票 **含退市**）、SFP（10,000 基金）、SF1 基本面、机构/内部人。② 日更 <1 天。③ 价格自 1997-12，基本面 1998。④ 仅 DJIA 30 免费样本。⑥ 直销个人价（草稿抓取 sharadar.com/subscribe）：Prices 5 年 $9/月（$99/年）、10 年 $19/月、全历史 $39/月（$299/年）；Fundamentals 全历史 $39/月（$399/年）；**Bundle 全历史 $69/月（$499/年）**。⑤ 未公布。⑥ API key / bulk。⑦ **个人许可明确排除任何专业/商业/组织用途**（sharadar.com/terms）；商业须经 Nasdaq Data Link（`SHARADAR/SEP` premium，价格页 JS 渲染 **未验证**）。⑧ CSV bulk + REST。⑩ 主键 (ticker,date) + `lastupdated` → 修订可追踪，只 insert 友好。⑪ ✅（文档）。
- Norgate ② 美股当前+退市+**历史指数成分股**；③ Platinum 至 1990、Diamond 至 1950；⑥ US Stocks 12 月：Silver $270 / Gold $360 / **Platinum $630** / Diamond $787.50（草稿抓取）；⑧ **仅 Windows** 本地库（`norgatedata` 读本地）→ LXC 需 Windows VM。
- 来源：<https://sharadar.com/subscribe> 、<https://sharadar.com/terms> 、<https://data.nasdaq.com/api/v3/datatables/SHARADAR/SEP/metadata.json> 、<https://norgatedata.com/stockmarketpackages.php>

### 1.6 期权专用补充（QNT-2/3 未定价）— 未实测
| 源 | 覆盖/深度 | 价格 | 许可/交付 | 备注 |
|---|---|---|---|---|
| **Historical Option Data** | OPRA 授权全市场 EOD CSV，5,900+ 标的，2002 至今 | 一次性：L1 24 年 $1,150 / 5 年 $615 / 1 年 $230；**L2（+Greeks/IV）24 年 $1,495 / 5 年 $945 / 1 年 $315**；订阅 L1 $585/年、L2 $615/年 | 许可细则未列（**未验证**）；CSV 下载，无 API | 买断 + 年订阅与 append-only 契合 |
| **MarketData.app** | 期权链/报价/历史 | Free 100 credits/日、1 年期权历史；**Starter $30/月（年付 $12/月）5 年期权历史**；Trader $75/月 无限历史 | 个人计划；credits 按返回行计（权重 **未验证**） | 最便宜的期权历史 API 之一 |
| optionsDX | SPY/SPX/VIX/QQQ 等热门标的 CSV，SPY 2010–2023 | SPY EOD 档免费、分钟档 ≤$50 | 条款 **未验证**；手动下载 | 单标的冒烟 |
| IVolatility | EOD 自 2005，IV 面 | Option Prices+HV $0.40/ticker/日；IVolLive $60–150/月 | 无免费全量 | 单标的贵（≈$100/标的/年） |
| Unusual Whales API | 实时 flow、日 OI、暗池 | Basic $125/月（2 年回看）、Advanced $315/月 | "strictly for personal use" | 非 EOD 主源 |
| QuantConnect Data Market | US Equity Options（AlgoSeek）2012-01 起约 4,000 标的含 OI | 1 USD = 100 QCC；每标的每文件约 $1（二手，**未验证**） | Lean 专有格式 | 交叉验证候选 |
| Barchart OnDemand | `getEquityOptionsHistory` 等 | 定制报价（**未验证**） | 企业级 | 非首选 |
- 来源：<https://www.historicaloptiondata.com/> 、<https://www.marketdata.app/pricing/> 、<https://www.optionsdx.com/product/spy-option-chains/> 、<https://www.ivolatility.com/data-download-intro/> 、<https://unusualwhales.com/public-api> 、<https://www.quantconnect.com/pricing/>

### 1.7 Stooq — 已实测（不可达）
- ① US `.us` 后缀日线 CSV、批量 zip `static.stooq.com/db/h/d_us_txt.zip`（~1.4 GB，QNT-2）。③ 自上市起，仅已复权 close。④ 名义免费；日限额 + 验证码（数字 **未验证**）。⑦ 无 API 条款，个人使用。⑪ **本节点**：`spy.us` → JS SHA-256 PoW 挑战页（草稿另测：解出 PoW 后 "Access denied"；`python-requests` UA → 404 页；批量 zip → 401 Basic Auth）。→ **不可作自动化源**；仅可人工浏览器一次性下载 zip 作历史快照（未核）。

### 1.8 Finnhub / Twelve Data / Marketstack — 免费层对日线无价值
- Finnhub：免费 60 calls/min；**免费层 `/stock/candle`（US K 线）已不可用**（GitHub issue #546 2025-04，"You don't have access to this resource"，官方无回复；定价页 JS 渲染 → 付费价 **未验证**，二手 All-In-One ≈$50/月）；期权链端点存在需 key。⑦ 免费限个人非商业。
- Twelve Data：Basic 8 credits/min、800/日；`earliest_timestamp` AAPL 自 1980-12-12；**期权端点无 key 调用返回 403 "available exclusively with pro or ultra or venture or enterprise plans"**（草稿实测）；Grow $79/月、Pro $229/月、Ultra $999/月。
- Marketstack：**Free 100 requests/月**仅 EOD、1 年历史；Basic $9.99/月 10k；无期权；文档 JS 渲染 → 限流 **未验证**。
- 来源：<https://github.com/finnhubio/Finnhub-API/issues/546> 、<https://twelvedata.com/pricing> 、<http://support.twelvedata.com/en/articles/5194820-api-credits-limits> 、<https://marketstack.com/product>

### 1.9 其他一行
- **IEX Cloud**：2024-08-31 全部关停（官方站 ECONNREFUSED）→ 排除。来源：<https://massive.com/blog/iex-cloud-migration-guide>
- **nasdaq.com 非官方 JSON**（`api.nasdaq.com/api/quote/{sym}/historical`）：实测 2,513 行 2016-09→2026-09（10 年上限，字符串带 `$`），需浏览器 UA/Origin；无条款授权 → 仅对照。
- **券商随账户免费行情**（Schwab Trader API Individual：refresh token 7 天需人工重授权；Public.com API：bars v2；Webull OpenAPI）：均为**实盘账户**附带，与 ADR-0001 边界冲突需裁决；本次未接触。来源：<https://developer.schwab.com/products/trader-api--individual> 、<https://public.com/api/docs>
- **Financial Datasets**：无免费层，$20/1,000 请求；基本面可由 EDGAR 免费替代。
- **Kaggle / HuggingFace 数据集**：静态、多为 Yahoo 抓取、许可链不清 → 仅离线测试样本。
- **OpenBB** 4.7.2：**AGPL-3.0-only**，内部研究无传染问题；对外服务需评估。

## 2. 汇总对比表（新增来源）

| 来源 | 类别 | 免费额度 | 最低付费 | 退市覆盖 | 期权 | 自动化 | 美国节点 | 备注 |
|---|---|---|---|---|---|---|---|---|
| Nasdaq Trader 目录 | 参考数据 | 无限 | — | 需自存快照 | options.txt | ✔ | ✅ 实测 | universe 首选 |
| SEC EDGAR | 基本面 | 10 req/s | — | 是（历史申报） | — | ✔ | ✅ 实测 | 公共领域 |
| FRED | 利率 | 免费 key | — | n/a | n/a | ✔ | ✅ 实测（无 key 路径） | vintage 可重放 |
| Cboe CDN | 指数/市场统计 | 无限 | — | n/a | 市场级 + 延迟链 | ✔（链条款存疑） | ✅ 实测 | VIX 族 + P/C |
| OCC | OI | 无限 | — | n/a | 是 | 半 | ✅ 草稿 | 无文档 |
| Sharadar 直销 | EOD+基本面 | DJIA30 | $9/月；Bundle $69/月 | **是** | — | ✔ | — | 个人许可限制 |
| Norgate | 本地 EOD | 否 | $630/年 | **是**+成分股 | — | Windows | — | 架构不匹配 |
| Historical Option Data | 期权 CSV | 否 | 1 年 $230 / L2 5 年 $945 | n/a | **2002+** | 下载 | — | 买断 |
| MarketData.app | 期权 API | 100/日, 1 年 | $12/月年付, 5 年 | n/a | **是** | ✔ | — | 最便宜 API |
| optionsDX / IVolatility / Unusual Whales / QuantConnect | 期权补充 | 少量 | $50 / 按量 / $125 月 / $1 文件 | n/a | 是 | 各异 | — | 补充 |
| Stooq | 免费 CSV | 名义 | — | 部分 | — | **✘ PoW** | ❌ 实测 | 状态已变 |
| Finnhub / Twelve Data / Marketstack | 通用 API | 60/min 无日线 / 800 日 / 100 月 | ~$50 / $79 / $9.99 | 否 | 付费 | ✔ | — | 免费层无用 |
| nasdaq.com JSON | 非官方 | 无限 | — | 否 | — | ✔ | ✅ 实测 | 无授权，仅对照 |
| IEX Cloud | — | 已关停 | — | — | — | — | — | 排除 |

## 3. 推荐补充（在 QNT-2 §2.3 组合之上）

- **Universe / 退市**：每日快照 `nasdaqlisted.txt` + `otherlisted.txt`（免费官方可重放）作 universe 增量层；完整退市价格若需 1998 起，Sharadar Prices 全历史 $39/月（前提：许可裁决通过）；Norgate 仅在接受 Windows VM 时考虑。
- **基本面**：SEC EDGAR `companyfacts.zip` 每日 bulk 为主（`edgartools` 解析），Sharadar Fundamentals 作标准化对照。
- **无风险利率**：FRED 正式 API（需 owner 注册 key）+ `realtime_start` 落库；无 key `fredgraph.csv` 作紧急备用。
- **期权 EOD 廉价路径**（与 QNT-2 ThetaData 主源并行的校验/回填）：Historical Option Data L2 1 年 $315 先验质量 → 5 年 $945；增量 MarketData.app Starter 年付 $144；VIX 族与市场 P/C 用 Cboe CDN 免费。
- **不推荐**：Finnhub 免费层、Marketstack Free、Stooq（自动化被拒）、Kaggle/HF、IEX Cloud、券商实盘只读行情（除非 ADR-0001 裁定放开）。

## 4. 待裁决清单（owner 回字母）

1. quantime 是否属 Sharadar "个人、非专业"许可范围：**A** 是（直销 $39–69/月）/ **B** 否（走 Nasdaq Data Link 商业价，未获取）/ **C** 不采购。
2. 实盘券商（Schwab/Public/Webull/Robinhood 无 API）的**只读行情** API：**A** 允许（凭据仍进 1Password quant-dev，agent 只读）/ **B** 禁止（严格 ADR-0001）。
3. 期权 EOD 历史补充：**A** Historical Option Data 一次性买断 / **B** MarketData.app 订阅 / **C** 两者并行交叉校验 / **D** 只用 QNT-2 已选主源。
4. Cboe 延迟链 JSON：**A** 纳入"非正式对照源"（低频、只 SPY/SPX 级） / **B** 完全不用（尊重页面禁抓声明）。
5. nasdaq.com 非官方 JSON 作对照源：**A** 允许 / **B** 不允许。
6. OpenBB（AGPL-3.0）进入依赖树：**A** 允许 / **B** 禁止。
7. Norgate Windows VM：**A** 准备 / **B** 排除。
8. FRED API key 注册（需 owner 操作）：**A** 注册 / **B** 继续用无 key CSV。

## 5. 信息来源

- QNT-2 结果评论（2026-09-16）、QNT-3 分段 F（2026-09-16）——见 §0.1 链接
- Nasdaq Trader：<https://www.nasdaqtrader.com/trader.aspx?id=symboldirdefs> 、<https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt> 、<https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt> ；nasdaq.com：<https://api.nasdaq.com/api/quote/SPY/historical>
- SEC：<https://www.sec.gov/search-filings/edgar-application-programming-interfaces> 、<https://www.sec.gov/os/accessing-edgar-data> 、<https://www.sec.gov/files/company_tickers.json> 、<https://data.sec.gov/api/xbrl/companyfacts/CIK0000320193.json>
- FRED：<https://fred.stlouisfed.org/docs/api/api_key.html> 、<https://fred.stlouisfed.org/docs/api/terms_of_use.html> 、<https://fred.stlouisfed.org/graph/fredgraph.csv?id=DGS3MO>
- Cboe：<https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv> 、<https://cdn.cboe.com/resources/options/volume_and_call_put_ratios/totalpc.csv> 、<https://cdn.cboe.com/data/us/options/market_statistics/daily/2026-09-16_daily_options> 、<https://cdn.cboe.com/api/global/delayed_quotes/options/SPY.json> 、<https://www.cboe.com/us/options/market_statistics/historical_data/>
- OCC：<https://marketdata.theocc.com/series-search?symbolType=U&symbol=AAPL> 、<https://marketdata.theocc.com/mdapi/volume-totals>
- Sharadar/Norgate：<https://sharadar.com/subscribe> 、<https://sharadar.com/terms> 、<https://data.nasdaq.com/api/v3/datatables/SHARADAR/SEP/metadata.json> 、<https://norgatedata.com/stockmarketpackages.php>
- 期权补充：<https://www.historicaloptiondata.com/> 、<https://www.marketdata.app/pricing/> 、<https://www.optionsdx.com/product/spy-option-chains/> 、<https://www.ivolatility.com/data-download-intro/> 、<https://unusualwhales.com/public-api> 、<https://www.quantconnect.com/pricing/> 、<https://www.barchart.com/ondemand/api>
- 通用 API：<https://github.com/finnhubio/Finnhub-API/issues/546> 、<https://twelvedata.com/pricing> 、<http://support.twelvedata.com/en/articles/5194820-api-credits-limits> 、<https://marketstack.com/product> 、<https://stooq.com/q/d/l/?s=spy.us&i=d>
- 券商/其他：<https://developer.schwab.com/products/trader-api--individual> 、<https://public.com/api/docs> 、<https://developer.webull.com/apis/docs/rate-limits> 、<https://massive.com/blog/iex-cloud-migration-guide> 、<https://www.financialdatasets.ai/pricing>
- PyPI（2026-09-18）：edgartools 5.58.0；fredapi 0.5.2；pandas-datareader 0.11.1；finnhub-python 2.4.29；twelvedata 1.4.0；openbb 4.7.2；yfinance 1.7.0

## 6. 未验证项

Finnhub 官方价格与"免费层移除 US 日线"的官方说法；Stooq 日限额数字与 PoW 是否针对数据中心 IP；Marketstack v2 限流/分页；FRED req/min 数值；OCC `volume-query` 参数与历史路径；Sharadar 经 Nasdaq Data Link 商业价；QuantConnect 每文件 QCC 单价与许可；Norgate 试用；MarketData.app credits 权重；optionsDX / Historical Option Data 再分发条款；Kaggle SPY 期权集正式许可；Schwab 限流与 price history 深度、Webull 期权链端点、Public.com 限流；Cboe daily_options JSON 最早日期（仅知 2019-01 → 403、2022-06 可用）；Cboe 延迟链页面"禁抓取"声明原文；Nasdaq Trader 再分发条款；所有"国内→X"可达性。

## 7. 探针实测输出摘要（2026-09-18 03:4x UTC，美国节点）

**表 A `free_public_us.py`（公开源部分 10 项，9 通过）**

| source | check | ok | 耗时 s | 行数 | 起 | 止 | ≥3y | 备注 |
|---|---|---|---|---|---|---|---|---|
| stooq | `q/d/l/?s=spy.us&i=d` | ❌ | 0.36 | | | | | `RuntimeError: HTML instead of CSV (JS browser verification / access denied): '<!DOCTYPE html>…<meta name="robots" content="noindex…'` |
| cboe_cdn | `VIX_History.csv` | ✅ | 0.17 | 9275 | 1990-01-02 | 2026-09-17 | ✅ | 官方 VIX 日 OHLC 全历史 |
| cboe_cdn | `totalpc.csv`（全市场 P/C） | ✅ | 0.02 | 3253 | 2006-11-01 | 2019-10-04 | ✅ | 2019-10 后改每日 JSON |
| cboe_cdn | `delayed_quotes/options/SPY.json` | ✅ | 0.56 | 12958 | | | | 延迟链快照 bid/ask/iv/greeks/OI；非正式接口；`timestamp=2026-09-18 03:44:30` |
| nasdaq_trader | `nasdaqlisted.txt` | ✅ | 0.18 | 5619 | | | | 尾行 `File Creation Time: 0917202621:31` |
| nasdaq_trader | `otherlisted.txt` | ✅ | 0.14 | 7634 | | | | 同上 |
| sec_edgar | `company_tickers.json` | ✅ | 0.29 | 10422 | | | | 必须带 `公司名 邮箱` UA |
| sec_edgar | `companyfacts/CIK0000320193.json` concept=Assets | ✅ | 0.09 | 146 | 2009-07-22 | 2026-07-31 | ✅ | 每条 fact 含 `accn/filed/frame` |
| fred | `fredgraph.csv?id=DGS3MO` | ✅ | 0.07 | 11752 | 1981-09-01 | 2026-09-16 | ✅ | 无 key 非正式接口；**浏览器 UA 超时、requests 默认 UA 正常**；正式 API 需 key，未注册 |
| nasdaq_com | `api/quote/SPY/historical` | ✅ | 2.09 | 2513 | 2016-09-19 | 2026-09-17 | ✅ | 非官方 JSON，仅对照 |

**表 B `free_public_us.py`（yfinance US 部分 4 项，4 通过）**

| check | ok | 耗时 s | 行数 | 起 | 止 | ≥3y | 备注 |
|---|---|---|---|---|---|---|---|---|
| SPY 日线 5y `auto_adjust=False` | ✅ | 0.37 | 1255 | 2021-09-17 | 2026-09-17 | ✅ | 含 Dividends/Stock Splits 列 |
| AAPL 日线 5y | ✅ | 0.17 | 1254 | 2021-09-20 | 2026-09-17 | ✅ | |
| SPY quote | ✅ | 0.10 | 1 | | 2026-09-17 | | `fast_info.last_price=None`；`history(5d).close=762.60`（fast_info 间歇为 None） |
| SPY 期权链快照 | ✅ | 0.20 | 613 | | | | 28 个到期日，first_exp=2026-09-18；**仅当前链，无历史** |

**表 C `stooq_cn_hk_us.py`（US 1 项，0 通过）**：`spy.us` → `RuntimeError: HTML instead of CSV (JS browser verification)`。

**复现**：`cd docs/research/probes && python run_all.py free_public_us stooq_cn_hk_us`。SEC 探针的 UA 为占位 `quantime-research probe (research@quantime.local)`（`free_public_us.py:101`），正式落库前请换成 owner 的真实联系方式（SEC 要求）。
