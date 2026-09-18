# 港股数据源全景：股票 / ETF

- 调研日期：2026-09-18；探测节点：美国（出口 IP 134.56.13.103），**未使用代理，未注册任何账号**
- 探针脚本：`docs/research/probes/yfinance_cn_hk_equity.py`（HK 4 项，4 通过）、`tencent_cn_equity.py`（HK 3 项，3 通过）、`sina_cn_equity.py`（HK 2 项，2 通过）、`eastmoney_cn_equity.py`（HK 3 项，0 通过）、`stooq_cn_hk_us.py`（HK 2 项，0 通过）、`exchange_sites_cn.py`（HKEX 2 项，2 通过）；汇总 `probes/results.md`
- 范围：港股股票 + ETF 日线。窝轮/牛熊证一句话：HKEX 每日报价文件与 Futu/LongPort/Tiger 均覆盖，但流动性与到期机制不适合日线研究，建议一期排除。
- 维度编号同 [data-sources-cn-equity.md](data-sources-cn-equity.md)；总索引见 [data-sources-index.md](data-sources-index.md)

## 0. 结论速览

| 结论 | 依据 |
|---|---|
| **HKEX 官网 Daily Quotations（`/eng/stat/smstat/dayquot/dYYMMDDe.htm`）美国节点可下载**（2026-09-16 文件 200，3.5s），含全部主板股票/ETF 收/买/卖/高/低/量/额；但**仅保留约 2 个月**（上一轮：08-17 → 200，07-16 → 404），且 Terms of Use **禁止自动抓取、禁止入库到联网服务器、禁止再分发** → 历史回填必须走付费 Data Marketplace 或第三方 | §1.1、§7 |
| 免费源中**历史最深且最快**：Yahoo（0005.HK 自 2000-01-31 含 92 条分红事件；本次 0700.HK/2800.HK 5y 各 1227/1225 行，0.1s），但条款仅限个人用途 | §1.5、§7 |
| **腾讯 `hkfqkline` 与新浪 HK 接口美国节点可达**（腾讯 0700/2800 1406 行 2021→，含除权事件文本）；**东财 push2his（AKShare `stock_hk_hist` 上游）不可达** 3/3 失败 | §1.3、§1.4、§7 |
| 券商 API：LongPort 开通即含 HK BMP（15 分钟延迟），日线自 2004-06-01；Futu 全球用户 HK LV1 免费但需常驻 OpenD 网关且历史 K 线配额 100–2000 只/7 天；均需开户（KYC），按硬边界本次未接触任何券商账号 | §1.6、§1.7 |
| Tushare 港股**不在积分体系内**：`hk_daily` 单独 1000 元/年、`hk_mins` 2000 元/年；`hk_daily_adj` 提供独立 `adj_factor` | §1.9 |

## 1. 逐源评估

### 1.1 HKEX 官网 Daily Quotations / Data Marketplace — 已实测可达性

- ① 全部主板/GEM 证券：收盘/买/卖/高/低/成交量/成交额/停牌标记；市场概览、卖空统计。② 日（收盘后）。③ **约 2 个月滚动**（上一轮实测）。④ 免费。⑤ 无技术限流但 ToS 禁爬。⑥ 无。
- ⑦ Terms of Use：禁止使用自动化程序访问、禁止将内容存入联网服务器/数据库、禁止再分发（**逐条原文见链接，本次已读**）。→ **不可作自动化落库源**，除非取得 HKEX 书面许可。来源：<https://www.hkex.com.hk/Global/Exchange/Terms-of-Use?sc_lang=en>
- ⑧ HTML `<pre>` 固定宽度文本。⑨ 官方，稳定。
- ⑩ 若合规获取：官方一手、不回改、最适合 append-only；需自建复权（HKEX 文件无复权）。
- ⑪ 美国→`www.hkex.com.hk` ✅ 200（3.5s，两项）。国内→HKEX：通（**未验证**）。
- **HKEX Data Marketplace**（付费）：Historical Full Book（tick）、Securities Attribute Daily Files、CCASS 历史；价格未公示（联系 datamarketplace@hkex.com.hk）；商业授权、内部使用；SFTP/云下载。来源：<https://www.hkex.com.hk/Services/Market-Data-Services/Historical-Data-Services/HKEX-Data-Marketplace?sc_lang=en>
- **CCASS 持股**：官网仅 12 个月，7 年历史需邮件申请；ToS 禁止程序化访问；港股通南向持股自 2017-03-17 起；上一轮美国可达（12s 慢）。来源：<https://www3.hkexnews.hk/sdw/search/searchsdw.aspx>

### 1.2 AKShare `stock_hk_*`（1.18.96）— 东财后端已实测不通，新浪后端可达
- ① `stock_hk_spot_em`/`stock_hk_hist`（东财 push2his，`secid=116.xxxxx`，`adjust=""/qfq/hfq`）、`stock_hk_daily`（新浪，`adjust="qfq/hfq/qfq-factor/hfq-factor"` 可单独取因子）、`stock_hk_spot`（新浪全市场快照）、`stock_hk_hist_min_em`、港股通成分、同花顺分红、etnet 盈利预测。来源：<https://akshare.akfamily.xyz/data/stock/stock.html#id66>
- ② 日/分钟。③ 全历史。④ 免费。⑤ 上游反爬。⑥ 无。⑦ MIT；"仅供学术研究"；数据许可继承上游（无明示）。⑧ Python。⑨ `stock_hk_daily` 历史上 ≥8 次因新浪变更 fix。
- ⑩ 新浪 `hfq-factor` 可独立落因子表（好）；东财 `fqt` 复权价整列重算（差）。
- ⑪ 东财 ❌（§7 表 D）；新浪 ✅（§7 表 C，但日线返回为压缩二进制，需 AKShare 内置解码）。

### 1.3 腾讯 `web.ifzq.gtimg.cn/appstock/app/hkfqkline/get` — 已实测
- ① qfq/hfq/none 日线 + 除权事件（`cqr`/`FHcontent` 文本）；快照 `qt.gtimg.cn/q=hk00700`（约 15 分钟延迟，**未验证延迟数值**）。② 日/周/月。③ 长（本次 2021→，分页 2 年/次，单次 ≤640 根）。④ 免费。⑤ 未公开。⑥ 无。⑦ 无明示（灰色），商用/再分发不可。⑧ JSON。⑨ 非官方。⑩ 除权事件文本可作 corporate-action 记录；只落 `none` 原始价。⑪ 美国 ✅ 3/3（≤0.7s）。
- 实测：§7 表 B。

### 1.4 新浪 HK — 已实测
- ① 快照 `hq.sinajs.cn/list=rt_hk00700`（需 Referer）；全市场 `vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHKStockData`；个股历史 + 复权因子（`finance.sina.com.cn/stock/hkstock/...`）。② 延迟/日。③ 长。④ 免费。⑦ 无明示。⑧ JSON/JSONP。⑨ 非官方；`quotes.sina.cn` openapi 已返回 "Service not valid"（上一轮）。⑪ 美国 ✅ 2/2。
- 实测：§7 表 C。

### 1.5 Yahoo Finance / yfinance（1.7.0）— 已实测
- ① `.HK` 后缀；OHLCV、`Adj Close`、分红/拆股事件；ETF（2800.HK 自 2008）。② 日/分钟。③ 2000 年起（0005.HK 上一轮实测 2000-01-31，92 条分红）。④ 免费。⑤ 非公开；yfinance 需 cookie/crumb。⑥ 无。⑦ Yahoo API 条款：**个人用途**，禁止再分发/商业获利。来源：<https://legal.yahoo.com/us/en/yahoo/terms/product-atos/apiforydn/index.html> 、<https://github.com/ranaroussi/yfinance> ⑧ REST/JSON（非官方）。⑨ Yahoo 多次变更导致 yfinance 间歇失效。⑩ `Adj Close` 整列随事件重算 → 只落原始价 + 事件表。⑪ 美国 ✅ 4/4（≤0.15s）；国内→Yahoo 阻断（**未验证**）。
- 实测：§7 表 A。

### 1.6 LongPort OpenAPI（longport 4.3.7）— 需开户，未实测
- ① HK/US/CN K 线、快照、深度、资金流、财报日历。② **开通 OpenAPI 即含 HK BMP（约 15 分钟延迟，无推送）**；HK LV1 实时需在 App 行情商店购买（定价页当前显示促销免费）；HK LV2 HK$558/月。③ **港股日线自 2004-06-01**，分钟 2022-09-28 起；单次 ≤1000 根。④ 基础免费。⑤ 全局 10 次/s、5 并发；历史 K 线 60 次/30s；**月度历史 K 线配额按资产分档**（同一标的当月只计一次；各档数值页面未渲染，**未验证**）；另有未文档化的同一标的 ~57ms 冷却（[issue #827](https://github.com/longbridge/developers/issues/827)，2026-03，无官方回复）。⑥ 长桥账户 + Developer Center 取 app_key/secret/token（90 天过期）；大陆用户开户受限（**未验证现行政策**）。⑦ 券商条款（**未逐条验证**）。⑧ REST + WS + Python/Rust SDK。⑨ 活跃（openapi 核心 2026-09-16 推送）。⑩ `adjust_type` 0/1 显式；月配额 + 同标的免重复计数对回填友好。⑪ 美国 ✅（文档）。来源：<https://open.longportapp.com/en/docs/quote/overview> 、<https://open.longportapp.com/en/docs/quote/pull/history-candlestick> 、<https://open.longportapp.com/en/docs/qa/quote> 、<https://open.longbridge.com/pricing>

### 1.7 Futu OpenAPI（futu-api 10.11.7108）— 需开户，未实测
- ① HK 股票/ETF/窝轮/牛熊证/期权/期货；K 线（1m–季）、快照、盘口、经纪队列。② 实时；**全球用户 HK LV1 免费，大陆实名用户 HK LV2 免费**。③ 日线保留 20 年；≤60 分钟线 8 年。④ 见 ②。⑤ 60 次/30s；历史 K 线配额 100/300/1000/2000 只（按资产，**7 天滚动**）。⑥ 富途/moomoo 账户 + 问卷 + 首登手机验证；**需常驻 OpenD 网关**（Linux `nohup ./OpenD &`，单账号最多 10 个 OpenD）。⑦ 券商条款：个人使用、禁止再分发（**未逐条验证**）。⑧ 网关 + SDK。⑨ 月度发版；117 open issues。⑩ `autype` qfq/hfq/None；历史配额是回填瓶颈（2000 只/7 天）；常驻网关与"常驻检出只读"纪律需裁决。来源：<https://openapi.futunn.com/futu-api-doc/en/intro/authority.html> 、<https://openapi.futunn.com/futu-api-doc/en/quote/request-history-kline.html> 、<https://openapi.futunn.com/futu-api-doc/en/qa/opend.html>

### 1.8 Tiger OpenAPI（tigeropen 3.8.0）/ IBKR — 未实测
- Tiger：HK/US/SG/AU K 线、快照；实时需单独购买 API 行情（HK L2 大陆 IP 赠送）；价格、限频、历史深度 **未验证**。来源：<https://quant.itigerup.com/openapi/zh/python/permission/feePermission.html>
- IBKR：HKEX L1/L2 via TWS/Gateway；HK L1 对非大陆注册且开通港股权限账户免费，否则月费（数字 **未验证**，页面 403）；pacing 限制；需常驻 TWS/Gateway。来源：<https://www.interactivebrokers.com/campus/ibkr-api-page/market-data-subscriptions/>

### 1.9 Tushare Pro 港股 — 需 owner 提供 token，未实测
- ① `hk_basic`（2000 分）、`hk_daily`（OHLC/量/额，18:00 更新，5000 行/次）、`hk_daily_adj`（含 `adj_factor/vwap/turnover/市值`，6000 行/次）、`hk_mins`。② 日/分钟。③ **未验证**。④ **积分外单独权限**：`hk_daily` 1000 元/年、`hk_mins` 2000 元/年。⑤ 200–500 次/分。⑥ 注册 token。⑦ 个人研究。⑩ **独立 `adj_factor`**（好）；文档注明因子可刷新 → 需按日快照。⑪ ✅。来源：<https://tushare.pro/document/2?doc_id=192> 、<https://tushare.pro/document/2?doc_id=339> 、<https://tushare.pro/document/1?doc_id=290>

### 1.10 海外付费 API：EODHD / Twelve Data / Finnhub / Alpha Vantage / Massive
- EODHD：HK 3754 只 tickers，EOD + 基本面；需 All World **Extended** US$29.99/月起，商用另计；10 万次/日；个人套餐禁商用/再分发；提供 `adjusted_close` 整列（同 Yahoo 问题）。来源：<https://eodhd.com/pricing> 、<https://eodhd.com/exchange/hk>
- Twelve Data：XHKG 需 Pro/Venture 档（<https://twelvedata.com/exchanges>）。Finnhub 国际 K 线需付费（**未验证**）；Alpha Vantage 文档未明示 HK、免费 25 次/日；Massive（ex-Polygon）仅美股。→ 均不推荐作港股主源。

### 1.11 Stooq / Investing.com / aastocks / etnet
- Stooq：`0700.hk`/`2800.hk` 本节点 **JS 挑战页**（§7 表 E）；日配额 **未验证**。Investing.com/aastocks/etnet：网页延迟行情，禁抓取（条款原文 **未验证**）。

### 1.12 JQData / RQData
- RQData 有港股模块（行情、复权因子、财务、行业）；JQData **拒绝境外 IP**。价格 **未验证**。

## 2. 汇总对比表

| 源 | 日线 | 历史起点 | 复权/因子 | 事件 | 价格 | 许可 | 常驻进程 | 美国节点 |
|---|---|---|---|---|---|---|---|---|
| HKEX Daily Quotations | ✔ 官方 | ~2 个月 | ✘ | ✘ | 免费 | **禁爬/禁入库/禁再分发** | 否 | ✅ 实测 |
| HKEX Data Marketplace | ✔ tick/日 | 长 | ✘ | ✔ | 询价 | 商业授权 | 否 | — |
| Yahoo/yfinance | ✔ | 2000 | Adj Close | 分红/拆股 | 免费 | 个人 | 否 | ✅ 实测 4/4 |
| 腾讯 hkfqkline | ✔ | 长 | qfq/hfq 服务端 | 除权文本 | 免费 | 灰色 | 否 | ✅ 实测 3/3 |
| 新浪 | ✔ | 长 | hfq-factor | ✘ | 免费 | 灰色 | 否 | ✅ 实测 2/2 |
| 东财 push2his / AKShare em | ✔ | 全 | fqt 整列 | ✘ | 免费 | 无明示 | 否 | ❌ 实测 0/3 |
| LongPort | ✔ ≤1000/次 | 2004-06-01 | adjust_type | ✘ | BMP 免费 | 券商 | 否（REST） | ✅ 文档 |
| Futu | ✔ | 20 年 | autype | ✘ | LV1 免费 | 券商 | **OpenD 常驻** | 网关位置决定 |
| Tiger / IBKR | ✔ | 未验证 | 未验证 | ✘ | 另购/月费 | 券商 | Tiger 否 / IBKR 是 | ✅ 文档 |
| Tushare hk_daily(_adj) | ✔ | 未验证 | **独立 adj_factor** | ✘ | 1000 元/年 | 个人 | 否 | ✅ |
| EODHD / Twelve Data | ✔ | 长 | adjusted_close | ✔ | US$29.99+/月 | 个人禁商用 | 否 | ✅ |
| Stooq | ? | ? | 已复权 | ✘ | 免费 | 个人 | 否 | ❌ JS 挑战 |

## 3. 推荐组合（供 owner 裁决）

- **方案 A —— 券商 API 主源（LongPort 为主，Futu 备）**：LongPort 免费 BMP 足够日线研究；日线自 2004；`adjust_type=0` 落原始价，分红/拆股另建事件表（可用 Yahoo/腾讯事件交叉）；需先确认账户档位月配额能否覆盖 ~2700 只主板回填。Futu 作第二 source（LV1 免费，但 7 天 2000 只配额 + OpenD 常驻）。优点：条款清晰、实时可选、可复用于美股；缺点：需开户 KYC、凭据管理（1Password quant-dev）、大陆用户开户受限。
- **方案 B —— Tushare `hk_daily` + `hk_daily_adj`（≈1000 元/年）+ Yahoo 校验**：独立 `adj_factor` 表最匹配可重放；REST 无常驻；美国可达。缺点：历史起点未验证、许可仅个人研究。
- **方案 C —— HKEX 官方合规路径**：与 HKEX 确认自动化/入库许可或购买 Data Marketplace 历史包；成本与合同周期最长，但唯一无灰色地带。

## 4. 待裁决清单（owner 回字母）

1. 常驻网关进程（Futu OpenD / IBKR Gateway）：**A** 允许 / **B** 不允许（仅 LongPort/Tushare/HTTP 类）。
2. 开户主体所在地：**A** 大陆（Futu 享 LV2，LongPort 受限）/ **B** 非大陆（LongPort/IBKR 免费行情资格）。
3. Tushare 港股 1000 元/年：**A** 批准 / **B** 不批准。
4. HKEX 官网数据：**A** 邮件争取书面许可 / **B** 完全不用 / **C** 购买 Data Marketplace。
5. 复权策略：**A** 只存原始价 + 事件/因子表 / **B** 同时存供应商复权价快照。
6. 窝轮/牛熊证与 CCASS：**A** 一期排除 / **B** 纳入。
7. 采集节点：**A** 仅美国（放弃东财/集思录）/ **B** 加国内节点。

## 5. 信息来源

- HKEX：<https://www.hkex.com.hk/eng/stat/smstat/dayquot/qtn.asp> ；样例 `…/dayquot/d260916e.htm`（实测）；<https://www.hkex.com.hk/Global/Exchange/Terms-of-Use?sc_lang=en> ；<https://www.hkex.com.hk/Services/Market-Data-Services/Historical-Data-Services/HKEX-Data-Marketplace?sc_lang=en> ；<https://www.hkex.com.hk/Global/Exchange/FAQ/Market-Data?sc_lang=en> ；CCASS <https://www3.hkexnews.hk/sdw/search/searchsdw.aspx> 、<https://www3.hkexnews.hk/sdw/search/mutualmarket.aspx?t=hk>
- AKShare 源码 `akshare/stock_feature/stock_hist_em.py`（`stock_hk_hist`，`secid=116.`）、`akshare/stock/stock_hk_sina.py` <https://github.com/akfamily/akshare>
- Futu：<https://openapi.futunn.com/futu-api-doc/en/intro/authority.html> 、<https://openapi.futunn.com/futu-api-doc/en/quote/request-history-kline.html> 、<https://openapi.futunn.com/futu-api-doc/en/qa/opend.html>
- LongPort：<https://open.longportapp.com/en/docs/quote/overview> 、<https://open.longportapp.com/en/docs/quote/pull/history-candlestick> 、<https://open.longportapp.com/en/docs/qa/quote> 、<https://open.longbridge.com/pricing> 、<https://github.com/longbridge/developers/issues/827>
- Tiger：<https://quant.itigerup.com/openapi/zh/python/permission/feePermission.html> ；IBKR：<https://www.interactivebrokers.com/campus/ibkr-api-page/market-data-subscriptions/>
- Tushare：<https://tushare.pro/document/2?doc_id=192> 、<https://tushare.pro/document/2?doc_id=339> 、<https://tushare.pro/document/1?doc_id=290>
- Yahoo：<https://legal.yahoo.com/us/en/yahoo/terms/product-atos/apiforydn/index.html> 、<https://github.com/ranaroussi/yfinance>
- EODHD：<https://eodhd.com/pricing> 、<https://eodhd.com/exchange/hk> ；Twelve Data：<https://twelvedata.com/exchanges> ；Alpha Vantage：<https://www.alphavantage.co/premium/>
- 腾讯（实测）：`https://web.ifzq.gtimg.cn/appstock/app/hkfqkline/get?param=hk00700,day,2024-01-01,2026-09-18,640,qfq` ；新浪（上一轮）：`https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHKStockData`
- PyPI（2026-09-18）：longport 4.3.7；futu-api 10.11.7108；tigeropen 3.8.0；yfinance 1.7.0；akshare 1.18.96

## 6. 未验证项

IBKR HK L1/L2 月费；Tiger 港股行情包价格/限频/深度；LongPort 月度配额各档数值、大陆用户开户政策；Futu 未入金账户是否可取行情、HK 日线最早日期；Tushare `hk_daily` 起点、手机号要求；Stooq HK 覆盖与日配额；EODHD HK 起点；Finnhub 国际 K 线是否付费；aastocks/etnet/Investing 条款原文；HKEX Data Marketplace 价格与起点；券商数据落库/内部再利用条款细则；腾讯/新浪 HK 延迟数值；所有"国内→X"可达性。

## 7. 探针实测输出摘要（2026-09-18 03:5x UTC，美国节点）

**表 A `yfinance_cn_hk_equity.py`（HK 4 项，4 通过）**

| check | ok | 耗时 s | 行数 | 起 | 止 | ≥3y | 备注 |
|---|---|---|---|---|---|---|---|
| 0700.HK 日线 5y | ✅ | 0.12 | 1227 | 2021-09-20 | 2026-09-18 | ✅ | Open/High/Low/Close/Volume/Dividends/Stock Splits |
| 0700.HK quote | ✅ | 0.14 | 1 | 2026-09-18 | | | `fast_info.lastPrice=425.40` |
| 2800.HK（盈富基金）日线 5y | ✅ | 0.09 | 1225 | 2021-09-20 | 2026-09-18 | ✅ | |
| 2800.HK quote | ✅ | 0.14 | 1 | 2026-09-18 | | | `lastPrice=25.40` |

**表 B `tencent_cn_equity.py`（HK 3 项，3 通过）**

| check | ok | 耗时 s | 行数 | 起 | 止 | ≥3y | 备注 |
|---|---|---|---|---|---|---|---|
| hk00700 日线 qfq（2021-01-01 起，分页 2 年/次） | ✅ | 0.71 | 1406 | 2021-01-04 | 2026-09-17 | ✅ | 单次 ≤640 根 |
| hk00700 quote `qt.gtimg.cn` | ✅ | 0.22 | 1 | | 2026/09/18 | | `name=腾讯控股 last=425.400 time=2026/09/18 11:44:32` |
| hk02800 日线 qfq | ✅ | 0.70 | 1406 | 2021-01-04 | 2026-09-17 | ✅ | |

**表 C `sina_cn_equity.py`（HK 2 项，2 通过）**

| check | ok | 耗时 s | 行数 | 备注 |
|---|---|---|---|---|
| rt_hk00700 quote（带 Referer） | ✅ | 0.21 | 1 | `name=TENCENT last=426.000` |
| hk00700 日线 | ✅ | 1.11 | 1（75476 bytes） | 返回压缩二进制，需 AKShare `stock_hk_daily` 内置解码；本探针只验证可达与体积 |

**表 D `eastmoney_cn_equity.py`（HK 3 项，0 通过 → 本节点不可达）**

| check | ok | 耗时 s | 错误原文 |
|---|---|---|---|
| `push2his…/kline/get?secid=116.00700` | ❌ | 0.63 | `ConnectionError: ('Connection aborted.', RemoteDisconnected('Remote end closed connection without response'))` |
| `push2delay.eastmoney.com` 同 secid | ❌ | 0.29 | HTTP 200 但 0 行 |
| `push2…/stock/get?secid=116.00700` quote | ❌ | 0.36 | `HTTPError: 502 Server Error: Bad Gateway` |

**表 E `stooq_cn_hk_us.py`（HK 2 项，0 通过）**：`0700.hk`、`2800.hk` → `RuntimeError: HTML instead of CSV (JS browser verification): <!DOCTYPE html>…<meta name="robots" content="noindex,nofollow">…`

**表 F `exchange_sites_cn.py`（HKEX 2 项，2 通过）**

| URL | ok | 耗时 s | 备注 |
|---|---|---|---|
| `www.hkex.com.hk/eng/stat/smstat/dayquot/d260916e.htm` | ✅ | 3.50 | HTTP 200（Daily Quotations，2026-09-16） |
| `www.hkex.com.hk/?sc_lang=en` | ✅ | 3.52 | HTTP 200 |

**复现**：`cd docs/research/probes && python run_all.py yfinance_cn_hk_equity tencent_cn_equity sina_cn_equity eastmoney_cn_equity stooq_cn_hk_us exchange_sites_cn`。注意：HKEX Daily Quotations 探针仅做单次 GET 验证可达性，**未做批量抓取**，遵守其 ToS。
