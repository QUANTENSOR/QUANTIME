# 全品种市场数据源总索引：总表 / 推荐组合 / 待裁决清单

- 调研日期：2026-09-16 → 2026-09-18；探测节点：美国佛州（出口 IP 134.56.13.103），**未使用代理、未注册任何账号、未接触任何交易所/券商账号**；国内→国外可达性均**未验证**
- 探针：`docs/research/probes/` 13 个脚本，**145 项检查，107 项通过**（`python run_all.py` 一键复现，结果 git 追踪于 `probes/results.jsonl` / `results.md`）；未通过项分三类：本节点不可达（东财 push2、DCE/CZCE 官网 412、Binance/Bybit REST、Stooq PoW）、上游限制（Kraken 720 根、CoinGecko 365 天、CoinPaprika/DefiLlama 派生 402）、需 token（Tushare、CoinGecko Pro 等未实测）
- 分市场文档：[A 股](data-sources-cn-equity.md) · [国内期货/期权](data-sources-cn-futures.md) · [公募基金](data-sources-cn-funds.md) · [港股](data-sources-hk.md) · [美股/期权](data-sources-us.md) · [加密](data-sources-crypto.md)；美股付费主源结论见 [QNT-2](mention://issue/01a0aca6-de88-7850-92d3-f0108d1654ec) / [QNT-3](mention://issue/01a0aca9-b19c-7d4b-b8fc-8e11d231ffc9)
- 11 个评估维度：① 覆盖/字段 ② 频率 ③ 历史深度 ④ 价格 ⑤ 限流 ⑥ 认证 ⑦ 许可 ⑧ 访问方式 ⑨ 维护状态 ⑩ ADR-0002 适配（只 insert / 可解释 / 可重放 / source 字段）⑪ 网络可达性

## 0. 跨市场结论

| 结论 | 影响 |
|---|---|
| **美国节点是分水岭**：东方财富 push2/push2his（A 股/ETF/港股/场内基金 K 线，AKShare `*_em` 上游）0/15 全部不通；DCE/CZCE 官网 412；Binance/Bybit REST 451/403；Stooq 全站 JS PoW；JQData 屏蔽海外 IP。反之新浪/腾讯/BaoStock/Yahoo/SSE/SZSE/BSE/HKEX/SHFE/INE/CFFEX/GFEX/OKX/Coinbase/Kraken/Deribit 等直连可用 | 国内品种若要东财/DCE/JQData 必须部署国内采集节点（待裁决 §3.1） |
| **没有任何免费源明文允许"商用落库 + 再分发"**；免费源许可分三档：无明示/爬虫灰色（新浪/腾讯/东财/nasdaq.com/Cboe 延迟链）、个人/学术/非商业（Yahoo、AKShare、CoinGecko、Coin Metrics CC BY-NC、交易所 API 条款）、公共领域（SEC EDGAR、FRED 国债系列）。HKEX 官网与 Cboe 延迟链页面**明文禁止自动化抓取** | 用途定性（个人研究 vs 商用）是所有市场的第一个待裁决项 |
| **独立复权因子 / point-in-time 字段**是 ADR-0002 可重放的关键，免费源中只有：BaoStock `query_adjust_factor`、AKShare 新浪 `hfq-factor`、SEC `accn/filed`、FRED `realtime_start`、Binance Vision 不可变 zip；Tushare（A 股 `adj_factor`、基金 `fund_adj` + `ann_date/nav_date`、港股 `hk_daily_adj`）需 token 未实测 | 复权价整列重算的源（Yahoo Adj Close、东财 fqt、EODHD adjusted_close）只落原始价 + 事件表 |
| **付费一站式性价比**：国内 Tushare 5000 积分 ≈ ¥500/年（A 股 + ETF + 基金持仓，港股另 ¥1000/年）；国内期货 TqSdk 专业版 ¥14,888/年（价格透明）或 RQData（不公开）；美股期权 ThetaData Standard $80/月（QNT-2 推荐）+ Historical Option Data L2 5 年 $945 一次性；加密 Tardis Solo $700+/月（仅期权链/强平长历史需要） | 年预算档位见 §3.3 |
| **官方文件类源天然最贴合 append-only**：国内期货交易所日报（SHFE/INE/CZCE/CFFEX/GFEX）、Binance Vision / OKX / Bybit public zip（带 CHECKSUM）、Nasdaq Trader 符号目录、SEC bulk zip、Cboe CDN CSV、HKEX Daily Quotations（但 ToS 禁自动化） | 推荐作为各市场"零成本底座" |

## 1. 全品种一张总表

表头：市场 · 源 · 类型（官方/券商/商业/社区爬虫）· ①覆盖 · ③历史起点 · ④价格 · ⑦许可 · ⑪美国节点实测 · ⑩ append-only 备注。每市场只列主要候选，全量见分市场文档 §2。

### 1.1 A 股（股票 / ETF / 可转债）

| 源 | 类型 | 覆盖 | 历史 | 价格 | 许可 | 美国实测 | append-only |
|---|---|---|---|---|---|---|---|
| Tushare Pro | 商业 | 股/ETF(5000 分)/转债/因子/分红/停复牌 | 全 | ¥200–1500/年；机构 ×10 | 个人非商业 | 需 token 未实测 | ★ 独立 adj_factor |
| BaoStock | 社区/免费 | 股/指数日线 + 因子；ETF 仅 2026 起 | 股 2006（改版中） | 免费 | 未明 | ✅ 4/4 | ★ query_adjust_factor |
| AKShare（新浪/腾讯后端） | 社区 | 股/ETF/转债 | 全 | 免费 | MIT 库；数据学术 | ✅ 6/9（东财后端 ❌） | 新浪 hfq-factor 可落 |
| 新浪 / 腾讯直连 | 爬虫 | 股/ETF/转债 | 全（新浪 ≤1023 根/次，腾讯 ≤640） | 免费 | 无明示 | ✅ 7/7、7/7 | 只落原始价 |
| 东方财富 push2/push2his | 爬虫 | 全 | 全 | 免费 | 无明示 | ❌ 0/12 | fqt 整列回改 |
| Yahoo / yfinance | 社区 | 股/ETF（转债 ✘，000001.SZ 缺行） | 2000 | 免费 | 个人 | ✅ 4/6 | Adj Close 整列 |
| RQData / JQData / 掘金 / QMT | 商业/券商 | 最全（含历史成分、转债条款） | 全 | RQData 未公开；JQData 屏蔽海外 IP；QMT 需 Windows | 合同 | 未实测 | ★ 因子/成分 |
| SSE / SZSE / BSE / 中证 / 国证官网 | 官方 | 名单/成分/停复牌 | 当前 + 部分历史 | 免费 | 非商业下载 | ✅ SSE/BSE；SZSE 路径 404 | 每日快照 |
| Stooq | 社区 | 未验证 | — | 免费 | 未验证 | ❌ JS PoW | — |

### 1.2 国内期货 / 期权

| 源 | 类型 | 覆盖 | 历史 | 价格 | 许可 | 美国实测 | append-only |
|---|---|---|---|---|---|---|---|
| 交易所日报（SHFE/INE/CZCE/CFFEX/GFEX/DCE） | 官方 | 全品种日线 + 期权（SHFE 含 Δ） | 上市起 | 免费 | 自用可；再分发未明 | ✅ 5 所 / ❌ DCE、CZCE 直连 412（AKShare 路径通） | ★ 结算价唯一真相 |
| AKShare `get_futures_daily` / 期权函数 | 社区 | 六所 + 新浪期权单合约 | 上市起 | 免费 | 学术 | ✅ 15/17 | 主力映射黑箱 |
| TqSdk 免费版 / 专业版 | 商业 | tick/分钟/日 + `KQ.m@` 主力 | 免费版序列上限 8000（文档矛盾 10000） | 免费（需快期账号）/ ¥14,888/年 | 个人 | 需注册未实测 | 主力规则透明 |
| RQData | 商业 | 全 + 因子 + 主力（1.1 倍持仓） | 全 | 不公开 | 合同 | 未实测 | ★ |
| Tushare `fut_daily`/`opt_daily` | 商业 | 日线 | 全 | 2000 分 ≈ ¥200/年 | 个人 | 需 token | ★ |
| CTP（SimNow/openctp） | 官方/社区 | 实时 tick、合约表 | 无历史 | 免费（需注册） | — | 未实测 | 实时录制 |
| Databento / Kaiko / Yahoo | 海外 | **不覆盖**中国期货 | — | — | — | — | — |

### 1.3 公募基金

| 源 | 类型 | 覆盖 | 历史 | 价格 | 许可 | 美国实测 | append-only |
|---|---|---|---|---|---|---|---|
| 天天基金 `pingzhongdata` / `f10/lsjz` | 爬虫（东财） | 净值/累计/分红/费率/经理/持仓 | 成立起（110011 4402 点自 2008） | 免费 | 无明示 | ✅ 5/7（fundgz ❌ 疑下线；fund_fee_em 0 行） | 每日快照 + 哈希 |
| AKShare `fund_*_em` / efinance | 社区（东财同源） | 同上 | 同上 | 免费 | 学术 | ✅（净值）/ ❌（场内 K 线 push2） | 同上 |
| Tushare `fund_nav`/`fund_adj`/`fund_portfolio` | 商业 | 净值 + ann_date/nav_date + 因子 + 持仓 | 全 | 2000/5000 分 | 个人 | 需 token | ★ 双日期 + 因子 |
| 蛋卷 / 集思录 / 巨潮公告 | 爬虫/官方 | 场内基金/持仓 PDF | — | 免费 | 各异 | 未全测 | 快照 |
| Wind / Choice / RQData | 商业 | 最全 | 全 | 高 | 合同 | 需国内终端 | ★ |

### 1.4 港股（股票 / ETF）

| 源 | 类型 | 覆盖 | 历史 | 价格 | 许可 | 美国实测 | append-only |
|---|---|---|---|---|---|---|---|
| HKEX Daily Quotations | 官方 | 全市场收/买/卖/高/低/量/额 | **~2 个月** | 免费 | **ToS 禁自动化/入库/再分发** | ✅ 2/2 | 官方一手，但需许可 |
| HKEX Data Marketplace | 官方付费 | tick/日/CCASS 历史 | 长 | 询价 | 商业授权 | — | ★ |
| Yahoo / yfinance | 社区 | 股/ETF + 分红拆股 | 2000 | 免费 | 个人 | ✅ 4/4 | 事件表可落 |
| 腾讯 `hkfqkline` | 爬虫 | 日线 + 除权事件文本 | 长 | 免费 | 无明示 | ✅ 3/3 | 除权文本 → 事件表 |
| 新浪 HK | 爬虫 | 快照 + 日线（压缩二进制）+ hfq-factor | 长 | 免费 | 无明示 | ✅ 2/2 | 因子可落 |
| 东财 push2his（AKShare `stock_hk_hist`） | 爬虫 | 全 | 全 | 免费 | 无明示 | ❌ 0/3 | — |
| LongPort OpenAPI | 券商 | HK/US/CN K 线；BMP 15 分钟延迟免费 | 2004-06-01 | 基础免费 | 券商条款 | 需开户未实测 | adjust_type 显式 |
| Futu OpenAPI | 券商 | HK 全品类；LV1 免费 | 20 年 | 免费（需 OpenD 常驻） | 券商条款 | 需开户未实测 | 7 天 2000 只配额 |
| Tushare `hk_daily(_adj)` | 商业 | 日线 + adj_factor | 未验证 | **¥1000/年**（积分外） | 个人 | 需 token | ★ |
| EODHD / Twelve Data / Stooq | 商业/社区 | HK | 长 | $29.99+/月 / Pro 档 / — | 个人 | — / — / ❌ PoW | adjusted 整列 |

### 1.5 美股（股票 / ETF / 期权）— 详见 QNT-2/3 + [data-sources-us.md](data-sources-us.md)

| 源 | 类型 | 覆盖 | 历史 | 价格 | 许可 | 美国实测 | append-only |
|---|---|---|---|---|---|---|---|
| ThetaData（QNT-2 推荐主源） | 商业 | 期权 EOD/tick + IV/Greeks | 2016（Standard） | $80/月 | 退订 30 天 expunge | — | 订阅期内可存 |
| Databento | 商业 | OPRA L0 13+ 年；无 Greeks | 2013-04 | $199/月 | 再分发最宽松；保留条款未验证 | — | ★ |
| Cboe DataShop | 官方付费 | Option EOD Summary | 2012-01 | 一次性买断 | internal business，无删除条款 | — | ★ 永久合规 |
| Massive（Polygon） | 商业 | 股 + 期权 | 2003 / 2014 | $29–199/月 | **display only** | — | 落库冲突 |
| Alpaca Free | 券商 | 股 2016+（IEX）、期权 2024-02+ | 短 | 免费 | personal | — | paper 券商兼用 |
| Historical Option Data / MarketData.app | 商业（本次新增） | 期权 EOD 2002+ / 5 年 | 长 | L2 5 年 $945 一次性 / $144 年付 | 未验证 / 个人 | — | 买断契合 |
| Sharadar 直销 | 商业（本次新增） | EOD 含退市 + 基本面 | 1997-12 | $39–69/月 | **个人许可排除专业用途** | — | ★ lastupdated |
| Nasdaq Trader 符号目录 | 官方 | universe/ETF 标志 | 当前快照 | 免费 | 网站条款 | ✅ 2/2 | ★ 每日快照 |
| SEC EDGAR XBRL | 官方 | 基本面 fact 带 accn/filed | 2009 | 免费 | **公共领域** | ✅ 2/2 | ★ point-in-time |
| FRED | 官方 | 无风险利率 + vintage | 1981 | 免费（正式 API 需 key） | 须署名 | ✅ 1/1（无 key CSV） | ★ realtime_start |
| Cboe CDN | 官方 | VIX 族 1990+、P/C 2006+、延迟期权链 | 长 | 免费 | 链页面禁抓（**未逐字验证**） | ✅ 3/3（链 12,958 条，与 QNT-2/3 "被封"不一致） | 指数可落 |
| yfinance | 社区 | 股/ETF + 当前链 | 全 | 免费 | personal | ✅ 4/4 | 仅校验 |
| Stooq / Finnhub 免费 / Marketstack 免费 / IEX Cloud | 社区/商业 | — | — | — | — | ❌ PoW / 无 US 日线 / 100 次月 / 已关停 | 排除 |

### 1.6 加密（CEX 现货+合约 / DEX / 链上）

| 源 | 类型 | 覆盖 | 历史 | 价格 | 许可 | 美国实测 | append-only |
|---|---|---|---|---|---|---|---|
| Binance Vision zip | 官方 bulk | 现货/永续 K、fundingRate、metrics(OI)、bookDepth、逐笔 | 现货 2017-08；um 2020-01；funding 2020-01；OI 2020-09 | 免费 | ToU 禁馈送/获利（条号未验证） | ✅ 5/5（REST 451） | ★ CHECKSUM 不可变 |
| Binance.US REST | 官方 | 现货 | 1000 根 | 免费 | — | ✅ | 过滤未收盘 |
| OKX REST + `market-data-history` zip | 官方 | 现货/永续/期权 K、funding（REST 3 月）、OI（1D 自 2024-01）、逐笔、盘口 | history-candles 2018-12 起 | 免费 | **§9.4 个人非商业** | ✅ 5/5 | ★ confirm=1 |
| Bybit public CSV | 官方 bulk | 逐笔（2020-03 起）、指数 1m | 长 | 免费 | 未验证 | ✅（REST 403） | 自建 K 线 |
| Coinbase / Kraken / Kraken Futures / Gate / Bitget | 官方 | 现货/永续 K、funding、OI | 300/次 / **720 根** / 2000 / 2000 / 200 | 免费 | Coinbase 最严；Bitget 禁美国 | ✅ 全部 | 过滤未收盘 |
| Deribit | 官方 | 永续 + 期权链快照 + DVOL | 4 年 K；funding 31 天窗口 | 免费 | 个人；禁聚合转售 | ✅ 3/3 | 链快照每日 insert |
| Hyperliquid / dYdX v4 / GMX | DEX 永续 | K/funding/OI | 5000 根 / 2023-11 / 10000 根 | 免费 | — | ✅ | HL S3 requester-pays |
| Tardis.dev | 商业 | 逐笔/L2/derivative_ticker/**liquidations/options_chain** | 2019+ | Solo $700–1200/月 | 允许 ≥10 分钟聚合再分发 | — | ★ 唯一强平/期权链长历史 |
| CoinGecko / CMC / CoinPaprika / CoinDesk Data | 聚合 | 币级价格/市值 | Demo 365 天 / 无 / 当日 / 免费层已取消 | $35–129+/月 | **CoinGecko 24h 缓存、禁存原始** | ✅ 365 天；❌ max 401；❌ 402；❌ 401 | 冲突 |
| Coinalyze | 聚合 | OI/funding/强平/多空比 | 日线永久 | 免费（需 key） | 署名 | 需注册未实测 | 日线可落 |
| DefiLlama / GeckoTerminal / DexScreener | DEX/链上 | TVL 2017+、DEX 成交量 2018+、池 OHLCV 6 月、快照 | 长 / 6 月 / 无 | 免费（衍生品 402 Pro $300） | 未明 / 署名 / 未验证 | ✅ 4/5、1/1、1/1 | 快照 + fetched_at |
| The Graph / Dune / Bitquery | 链上索引 | 子图/SQL | — | 100k 查询/月 / 15 rpm / $39+ | — | 需 key 未实测 | 记 block number |
| blockchain.com / mempool.space / Coin Metrics Community | 链上 | BTC 指标 | 长 | 免费 | — / — / CC BY-NC | ✅ 2/2 | 可落 |

## 2. 推荐组合（分市场 A/B/C，供 owner 裁决）

| 市场 | A（零成本起步） | B（低预算增强，推荐） | C（商业/合规上限） |
|---|---|---|---|
| A 股 | BaoStock 主 + AKShare 新浪/腾讯补 ETF/转债 + 交易所/指数公司快照 | **Tushare 5000 分（¥500/年）主 + BaoStock 备 + 官方文件校验** | RQData/JQData 主 + Tushare 交叉 |
| 国内期货 | **交易所日报直连（DCE 经国内节点/AKShare）+ openctp 合约表 + 自算主力映射** | A + TqSdk 免费版（需快期账号）录 tick 与 `KQ.m@` 对照 | A + RQData 或 TqSdk 专业版 ¥14,888/年 |
| 公募基金 | 东财 `lsjz`/`pingzhongdata`/`jjcc` 直连，每日快照 + 哈希 | **Tushare 5000 分（与 A 股共用）+ 东财交叉校验** | Wind/Choice/RQData |
| 港股 | Yahoo + 腾讯 hkfqkline（事件文本）+ 新浪因子，仅校验级 | **LongPort BMP（免费，2004 起）主 + Futu 备**（需开户，凭据入 1Password）或 Tushare hk_daily+adj ¥1000/年 | HKEX Data Marketplace 或书面许可 |
| 美股 | Alpaca Free + Nasdaq Trader 快照 + SEC EDGAR + FRED + Cboe CDN | **QNT-2：ThetaData Standard $80/月 主 + Alpaca/yfinance fallback**；本次补充：Historical Option Data L2 一次性 + MarketData.app 增量；Sharadar 退市（许可待裁） | Cboe DataShop 买断 + Databento Standard 日更 |
| 加密 | **Binance Vision + OKX zip 底座 + OKX/Deribit REST 增量 + WS 强平/OI 自采** | A + CCXT 多所校验 + Coinalyze 日线聚合 | A + Tardis Solo（期权链/强平长历史） |

跨市场共同建议：
1. 所有 K 线只落原始（未复权）价 + 独立事件/因子表；供应商复权价如需保留则按日快照存 `vendor_adjusted`，不覆盖。
2. 每条记录带 `source`、`fetched_at`、`source_version`（文件 CHECKSUM / API 版本 / 探针 commit）；文件类源以内容哈希为幂等键。
3. 同一市场至少两个独立上游做对账（差异阈值报警），东财系（AKShare em / efinance / 天天基金）算一个上游。
4. 主力连续合约、指数成分、universe 增删等"定义类"数据自算并版本化规则。

## 3. 待裁决总清单（owner 回字母；分市场细项见各文档 §4/§5）

### 3.1 跨市场

1. **数据用途定性**：**A** 个人研究（Tushare/Sharadar/Yahoo/交易所 API 个人档均可用）/ **B** 商用（需机构授权或付费合同；排除 Sharadar 个人、OKX 非商业、Massive display-only）。
2. **国内采集节点**：**A** 部署（解锁东财/DCE/JQData/掘金/QMT，并可验证国内→国外可达性）/ **B** 不部署（只用美国节点可达源，放弃东财系与 DCE 直连）。
3. **年预算档位**：**A** ¥0 / **B** ≤¥1500 + ≤$150/月（Tushare 5000 分 + 港股 + ThetaData Standard）/ **C** 万元级 + $500+/月（RQData/TqSdk 专业版/Tardis/Cboe DataShop 买断）。
4. **常驻进程**（Futu OpenD、IBKR Gateway、TqSdk/CTP 录制、加密 WS 强平采集）与"常驻检出只读"纪律：**A** 允许专用采集进程 / **B** 禁止（仅文件 + REST 增量）。
5. **灰色许可源落库**（新浪/腾讯/东财/nasdaq.com/Cboe 延迟链，无明示授权）：**A** 接受作校验/备源 / **B** 只作临时对照不落库 / **C** 完全不用。
6. **owner 需要亲自注册的 token/账号**（agent 不注册）：Tushare、FRED API key、Coinalyze、快期（TqSdk）、The Graph Studio、LongPort/Futu 开户：**A** 逐个批准（请勾选）/ **B** 全部暂缓。
7. **复权策略**：**A** 只存原始价 + 事件/因子表 / **B** 同时存供应商复权价每日快照。
8. **分钟/tick 是否进 MVP**：**A** 否（日线研究）/ **B** 是（影响 TqSdk/Tushare 分钟/Tardis 预算）。

### 3.2 分市场关键项（各文档待裁决清单的摘录）

| 市场 | 关键待裁决 |
|---|---|
| A 股 | Tushare 档位（2000/5000 分）；成分股历史来源（自建快照 / Tushare / RQData）；可转债条款来源；BaoStock 新站条款落地后是否仍作备源 |
| 国内期货 | 主力连续合约定义（TqSdk 双最大 / RQData 1.1 倍 / 自定）；期权 Greeks（交易所 Δ / 自算 / 两者）；是否注册快期/openctp |
| 公募基金 | 场内 ETF 行情路径（国内节点 / 交易所文件 / Tushare fund_daily）；复权净值（自算 / Tushare / 对账）；完整持仓 PDF 解析一期还是二期；fundgz 是否需要 |
| 港股 | 开户主体所在地（大陆 vs 非大陆决定 LongPort/Futu 行情资格）；HKEX 官网数据（争取许可 / 不用 / 买 Marketplace）；窝轮/CCASS 一期排除 |
| 美股 | Sharadar 个人许可是否适用；实盘券商只读行情 API 与 ADR-0001 边界；期权 EOD 补充路径（买断 / 订阅 / 并行）；Cboe 延迟链 JSON 是否纳入对照；OpenBB AGPL；Norgate Windows VM；FRED key |
| 加密 | Binance 路径（Vision+WS+US vs 代理 REST）；Bitget（ToS 禁美国）是否纳入；强平（自采 vs Tardis 回补）；期权（Deribit 快照 / Laevitas / Tardis）；CoinGecko 是否放弃作落库源；DEX/链上是否进 v1 |

## 4. 探针总览

| 探针文件 | 市场 | 通过/总数 | 未通过原因 |
|---|---|---|---|
| `akshare_cn_equity.py` | A 股 | 6/9 | 东财后端 3 项不可达 |
| `baostock_cn_equity.py` | A 股 | 4/4 | — |
| `sina_cn_equity.py` | A 股/港股 | 7/7 | — |
| `tencent_cn_equity.py` | A 股/港股 | 7/7 | — |
| `eastmoney_cn_equity.py` | A 股/港股 | 0/12 | push2/push2his 全部不可达（RemoteDisconnected / 502 / 超时） |
| `exchange_sites_cn.py` | A 股/期货/港股 | 7/11 | SZSE 路径 404、DCE/CZCE 412、INE 旧路径 404 |
| `yfinance_cn_hk_equity.py` | A 股/港股 | 8/10 | Yahoo 不覆盖可转债 113050.SS |
| `stooq_cn_hk_us.py` | A 股/港股/美股 | 0/5 | 全站 JS PoW 挑战 |
| `akshare_cn_futures.py` | 期货/期权 | 15/17 | DCE 412（JSONDecodeError）、1 项参数解析 |
| `eastmoney_cn_funds.py` | 基金 | 5/7 | fundgz 疑下线、fund_fee_em 0 行 |
| `free_public_us.py` | 美股 | 13/14 | Stooq PoW |
| `cex_public_crypto.py` | 加密 CEX | 25/29 | Binance REST 451 ×2、Bybit REST 403 ×2 |
| `onchain_dex_crypto.py` | 加密 DEX/链上 | 10/13 | CoinGecko max 401、DefiLlama derivatives 402、CoinPaprika 402 |
| **合计** | | **107/145** | |

复现：`cd docs/research/probes && python run_all.py`（Python 3.13，依赖 `akshare baostock yfinance ccxt pandas requests`；全部只做公共 GET，不带 key）。

## 5. 文档矛盾汇总（只报不修）

| # | 矛盾 | 出处 |
|---|---|---|
| 1 | TqSdk 免费版序列上限：官网 8000 vs 文档 10000 | cn-futures §6 |
| 2 | AKShare `option_daily_stats_sse` 文档参数名与实现不一致；`option_cffex_zz1000_daily_sina` 需完整合约代码而非文档示例 | cn-futures §6 |
| 3 | AKShare 文档称 `stock_zh_a_hist`/`stock_hk_hist` 等东财后端可用，本节点全部不可达（文档未提地域限制） | cn-equity §6、hk §6 |
| 4 | BaoStock 文档称仅 A 股 + 指数；ETF 实际可查但仅 2026 起 | cn-equity §6 |
| 5 | Cboe 延迟期权链：QNT-2/QNT-3 记"被封/不可达"，本次实测 200 返回 12,958 条 SPY 合约 | us §0.2 |
| 6 | ThetaData 免费层限流：页面正文 20 req/min vs 30 req/min（QNT-2 已报） | QNT-2 §2.1 |
| 7 | cryptofeed 许可：PyPI 元数据 XFree86-1.1 vs GitHub LICENSE AGPL | crypto §6 |
| 8 | CoinGecko Demo 限流：旧支持文 30/min vs 现行 100/min | crypto §6 |
| 9 | Binance `binance-public-data` README 仅列 3 类文件，S3 实际有 metrics/fundingRate/bookDepth 等；`liquidationSnapshot` 前缀存在但无文件 | crypto §6 |
| 10 | Kraken Futures 历史资金费率端点路径：`historical-funding-rates` vs 旧写法 `historicalfundingrates`（404） | crypto §6 |
| 11 | Hyperliquid 文档 candleSnapshot 最多 5000 根，实测 1m 返回 5212 | crypto §6 |
| 12 | 天天基金 `fundgz` 盘中估值端点：AKShare/社区文档仍列为可用，本次两轮返回空/404 | cn-funds §6 |
| 13 | 探针解析瑕疵（非上游矛盾，已在文档标注）：CZCE 日期列显示 1970-01-01、期货现货 `time` 显示 2000-11-30 | cn-futures §7 |
