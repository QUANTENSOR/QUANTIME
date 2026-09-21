# 其他市场特征与免费数据源许可调研（A股 / 国内期货 / 公募基金 / 港股 / 美股）

- 调研日期：2026-09-20；调研节点：美国 LXC，**纯只读网页调研**：未注册任何账号、未申请任何 token、未接触任何券商/交易所账号、未落任何凭据
- 范围裁决：owner 2026-09-19 裁决 **2B + 3A**——产品定义维持"美股 + 美股期权 + 加密"，其他市场**只调研不实现**；国内源只列许可明确允许的公开源。本文**不含任何摄取代码**，不改变 `AGENTS.md §1` 的产品定义
- 与 QNT-22 的关系：QNT-22（impl-d，分支 `agent/impl-d/777ad112ec0e`，**尚未并入 main**）已产出 `docs/research/data-sources-{index,cn-equity,cn-futures,cn-funds,hk,us}.md`，含 145 项探针实测与逐源 11 维评估。**本文不重复其数据源逐源评估**，只做两件它没做的事：① 五类市场的**交易机制事实表**（时段/tick/涨跌停/乘数/复权/延迟）；② 面向 ADR-0003 的**三张表字段建议**。§2 的源清单只保留"许可明确允许研究使用"的那一档，并在冲突处标注与 QNT-22 的一致性
- 许可三态定义：**允许研究使用** = 条款原文明示非商业/学术/个人研究可用，或公共领域；**不明确** = 无可达条款原文，或条款未覆盖本用途；**禁止** = 条款原文明示禁止本用途（自动化抓取 / 入库 / 再分发）
- 凭据三态之外另有一档：**不可用（quant-dev 无条目）** = 需注册、登录或 token，按 ADR-0001 凭据边界，本卡不申请、不实测
- 本文每条结论附可达来源链接；无来源的不写。标 **未验证** 的是查到二手转述但未取到一手原文的项

## 0. 结论速览

| 结论 | 依据 |
|---|---|
| **五类市场中，本次均未证实存在"日线免费可得 + 权利人一手许可覆盖研究落库 + 无需凭据"的合格源——美股股票/ETF 也不例外**。不作任何市场"满足"的排他判断：美股股票/ETF 的候选要么需 key（Alpaca / Massive / Nasdaq Data Link / Tiingo），要么只有第三方转述而无权利人授权（Yahoo 经 yfinance），要么授权过窄（Cboe 单份个人拷贝）；唯一取到一手许可且无需凭据的 IEX HIST 是**单一交易所 pcap 逐笔**，不是合并市场日线。详见 §4 | §2.5、§4 |
| **HKEX 官网是五类市场里唯一"明文禁止"的一档**：Terms of Use §5 禁止 robot/spider/scraper 访问、禁止存入联网服务器/数据库、禁止再分发与文本数据挖掘 | [HKEX Terms of Use](https://www.hkex.com.hk/Global/Exchange/Terms-of-Use?sc_lang=en) |
| **上交所、深交所官网各自"允许研究使用（非商业浏览/下载，只及于本网站）"**：两份声明第三条措辞同构——"可基于非商业目的浏览、下载**本网站**的内容"，且"不得以向他人出售牟利为目的"使用。两份授权**各自只及于自己的网站，互不推及**，引用时必须分别举证 | [上交所法律声明](https://www.sse.com.cn/home/legal/)（访问日期 2026-09-20）、[深交所法律声明](https://www.szse.cn/application/laws/index.html)（访问日期 2026-09-20） |
| **交易日历不能用"周一到周五减节假日"近似**：A股/港股有午休（11:30–13:00 / 12:00–13:00），国内期货有跨日夜盘（21:00 起，贵金属至次日 02:30），美股有 13:00 提前收盘日，且哪一天早收、哪一天全休**逐年摆动**（2026-07-03 全休、2028-07-03 早收）。三者都必须落成**显式会话表**而非规则推导 | §1 各节 + §3.1 |
| **"复权"在五类市场是五种不同语义**：A股=除权除息因子；期货=换月价差拼接（非复权）；公募=分红再投资复权净值；港股=同A股；美股=split + 分红调整 + **OCC 期权合约调整**。ADR-0003 的复权因子表必须带 `adjust_kind` 区分，不能只存一个 factor 列 | §3.3 |
| **期权合约乘数是"每合约标的数量"，不是"价格乘数"，且会被公司行为改写**：美股期权标准 100 股但 OCC 调整后 deliverable 可变；50ETF期权 10000 份；股指期权按点×100/200 元。品种元数据表必须把 `multiplier` 做成**带生效区间的版本化字段** | §3.2 |

## 1. 五类市场交易机制

### 1.1 A股（股票 / ETF / 可转债 / ETF期权）

| 维度 | 事实 | 来源 |
|---|---|---|
| 交易时段 | 开盘集合竞价 9:15–9:25；连续竞价 9:30–11:30、13:00–14:57；收盘集合竞价 14:57–15:00。**有午休 11:30–13:00** | [上交所修订发布交易规则](https://www.sse.com.cn/aboutus/mediacenter/hotandd/c/c_20260424_10816474.shtml)、[北交所时段（同构）](https://www.cls.cn/detail/867097) |
| 规则版本 | 《上海证券交易所交易规则（2026年修订）》2026-04-24 发布、**2026-07-06 施行**；要点：盘后固定价格交易由科创板扩至全部A股与ETF；基金收盘改集合竞价；主板风险警示股涨跌幅 5%→10% | [上交所 2026 修订公告](https://www.sse.com.cn/aboutus/mediacenter/hotandd/c/c_20260424_10816474.shtml)、[规则页](https://www.sse.com.cn/lawandrules/sselawsrules2025/trade/universal/c/c_20260424_10816492.shtml) |
| tick | A股申报价格最小变动单位 0.01 元 | [上交所交易规则（2023修订）页](http://www.sse.com.cn/lawandrules/sselawsrules2025/stocks/exchange/c/c_20250519_10779396.shtml)（条文原文经二手转述，**条文号未验证**） |
| 申报数量 | 主板买入 100 股及其整数倍；科创板可 1 股递增 —— **未验证**（未取到一手条文） | 同上 |
| 涨跌停 | 主板 ±10%；创业板/科创板 ±20%；北交所 ±30%（且 30%/60% 两档临停各 10 分钟）；主板风险警示股 2026-07-06 起 ±10% | [创业板特别规定](http://docs.static.szse.cn/www/disclosure/notice/general/W020200612831351578076.pdf)、[北交所规则](https://www.cls.cn/detail/864908)、[上交所 2026 修订](https://www.sse.com.cn/aboutus/mediacenter/hotandd/c/c_20260424_10816474.shtml) |
| 可转债 | 申报最小变动 0.01 元；1000 元面值为一交易单位、每百元面额计价；上市首日 -43.3%~+57.3%，次日起 ±20%，盘中 20%/30% 两档临停 | [上交所可转债交易实施细则（2025年3月修订）](https://www.sse.com.cn/lawandrules/sselawsrules2025/bond/trading/currency/c/c_20250606_10781040.shtml) |
| 交收 | 股票 T+1（T日买入 T+1 可卖）；卖出资金当日可用、T+1 可取 | [T+1 制度](https://baike.eastmoney.com/item/T+1%E4%BA%A4%E6%98%93%E5%88%B6%E5%BA%A6)（二手，**监管原文未验证**） |
| ETF期权（50ETF 为例） | 合约单位 **10000 份**；最小报价单位 **0.0001 元**；时段同股票（9:15–9:25 集合竞价，14:57–15:00 收盘集合竞价）；**欧式**、到期日行权；实物交割；到期月份为当月/下月/随后两个季月 | [上证50ETF期权合约基本条款](https://www.sse.com.cn/assortment/options/contract/c/c_20230303_5717359.shtml) |
| 期权涨跌幅 | 非固定百分比，按公式算：认购最大涨幅 = max{标的前收盘×0.5%, min[(2×标的前收盘−行权价), 标的前收盘]×10%}；认购最大跌幅 = 标的前收盘×10% | 同上 |
| 复权与分红 | 权益登记日次一交易日做除权除息处理，**除权除息日行情中的"前收盘价"即除权参考价**；研究需自建前/后复权因子 | [上交所热线问答·除权除息](https://www.95363.com/main/a/20230329/112381.shtml)（**交易所条文原文未验证**） |
| 数据频率与延迟 | 官方网站为收盘后日频快照；实时行情需券商/行情商授权。免费公开源普遍为日线 | §2.1 |

### 1.2 国内期货（商品 / 股指 / 期权）

| 维度 | 事实 | 来源 |
|---|---|---|
| 日盘时段 | 商品期货 9:00–11:30（含 10:15–10:30 小节休息，**各所细则未逐一验证**）、13:30–15:00；股指期货 9:30–11:30、13:00–15:00 | [SHFE 黄金合约](https://www.shfe.com.cn/products/futures/metal/ferrousandpreciousmetal/au_f/standard_au_f/202312/t20231205_316957.html)、[CFFEX IF 解读](https://www.shinnytech.com/articles/business-rules/products/cffex.if) |
| 夜盘 | 有夜盘品种：20:55–20:59 申报、20:59–21:00 撮合，21:00 开盘；郑商所/大商所多数至 23:00，上期所贵金属至**次日 02:30**。法定节假日前第一个交易日不开夜盘 | [各所时段汇总](https://futures.hnchasing.com/cx-website/sys/common/static/temp/FBD861E6F465D0D967E12800B9723E11.pdf)（券商汇总，**交易所原文未逐所验证**） |
| 合约乘数 | 期货以"交易单位（吨/手、克/手）"表达而非乘数：SHFE 黄金 **1000 克/手**；股指期货用点值：IF **每点 300 元**、IM **每点 200 元** | [SHFE 黄金合约](https://www.shfe.com.cn/products/futures/metal/ferrousandpreciousmetal/au_f/standard_au_f/202312/t20231205_316957.html)、[CFFEX IM 合约 PDF](http://www.cffex.com.cn/u/cms/www/202207/18190308vxpv.pdf) |
| tick | SHFE 黄金 0.02 元/克；CFFEX 股指期货 0.2 指数点；CFFEX 股指期权 0.2 点 | 同上 + [CFFEX 中证1000股指期权合约 PDF](http://www.cffex.com.cn/u/cms/www/202207/18190352jh7v.pdf) |
| 涨跌停 | 按品种与合约动态调整：SHFE 黄金合约文本为上一交易日结算价 ±3%，但交易所按风险状况公告调整（2026 年内多次调至 15%–17%）；IF 为上一交易日结算价 ±10%，交割月最后交易日 ±20% | [SHFE 黄金合约](https://www.shfe.com.cn/products/futures/metal/ferrousandpreciousmetal/au_f/standard_au_f/202312/t20231205_316957.html)、[SHFE 调整公告报道](https://finance.sina.com.cn/jjxw/2026-04-14/doc-inhunicx8995369.shtml)、[CFFEX IF 解读](https://www.shinnytech.com/articles/business-rules/products/cffex.if) |
| 股指期权乘数 | CFFEX 沪深300股指期权（IO）**每点 100 元**；中证1000股指期权（MO）每点 100 元；时段 9:30–11:30、13:00–14:57 + 14:57–15:00 收盘集合竞价 | [CFFEX IO 解读](https://www.shinnytech.com/articles/business-rules/products/cffex.io)、[CFFEX MO 合约 PDF](http://www.cffex.com.cn/u/cms/www/202207/18190352jh7v.pdf) |
| "复权" | 期货**无分红除权概念**；连续合约的价格跳空来自换月价差（资金成本/仓储/便利收益）。拼接方法为等差复权 / 等比复权，回测普遍建议**后复权**（前复权可能出现负价）；不同方法结果不同，部分平台因此不提供"复权主力" | [换月与复权方法讨论](https://zhuanlan.zhihu.com/p/663025937)、[信易论坛](https://forum.shinnytech.com/question/26492/)（社区来源，**交易所无官方定义**） |
| 数据频率与延迟 | 交易所日报（结算价、持仓、成交）为收盘后发布，是结算价的唯一权威；tick/分钟需 CTP 或商业源 | QNT-22 `data-sources-cn-futures.md` §1 |

### 1.3 国内公募基金

| 维度 | 事实 | 来源 |
|---|---|---|
| "交易时段" | 场外基金**无连续交易**：以 15:00 为申赎申请的 T 日切分点，按当日收盘后净值成交，T+1 确认份额 | [开放式基金业务规则](https://www.rosefinchfund.com/service/xinshou/%E5%BC%80%E6%94%BE%E5%BC%8F%E5%9F%BA%E9%87%91%E4%B8%9A%E5%8A%A1%E8%A7%84%E5%88%99/index.html)（销售机构口径，**监管原文未验证**） |
| 净值披露时限 | 《公开募集证券投资基金信息披露管理办法》**第十四条**：开放式基金"在不晚于每个开放日的次日"披露开放日的基金份额净值与累计净值；封闭式基金"至少每周…披露一次" | [CSRC 信息披露管理办法](http://www.csrc.gov.cn/csrc/c106256/c1653985/content.shtml) |
| 频率与延迟 | 日频，**T+1 才可得**——这是与股票日线最大的结构差异：净值序列天然滞后一日，回测的信息集边界必须按披露日而非净值日 | 同上 |
| 三种净值 | **单位净值**（不含分红）/ **累计净值**（单位净值 + 历史分红，分红不再投资）/ **复权净值**（分红按红利再投资复利）。基金公司与评价机构计算业绩回报统一用**复权净值增长率**，不用累计净值增长率 | [净值概念对比](https://zhuanlan.zhihu.com/p/130476734)（社区，**监管原文未验证**） |
| 场内 ETF/LOF | 走交易所连续竞价，规则同 §1.1；IOPV/份额由交易所日频发布 | §1.1 |
| 涨跌停 | 场外无；场内 ETF 按标的类别适用交易所涨跌幅 | §1.1 |

### 1.4 港股（股票 / ETF）

| 维度 | 事实 | 来源 |
|---|---|---|
| 交易时段 | 开市前时段 9:00–9:30；早市 9:30–12:00；**延续早市（午休）12:00–13:00**；午市 13:00–16:00；收市竞价 16:00 起至 **16:08–16:10 之间随机收市** | [HKEX 证券市场交易时间](https://www.hkex.com.hk/Services/Trading-hours-and-Severe-Weather-Arrangements/Trading-Hours/Securities-Market?sc_lang=en) |
| 半日市 | 圣诞前夕/新年前夕/农历新年前夕：收市竞价 12:00 起至 12:08–12:10 随机收市，无延续早市与午市 | 同上 |
| 港股通 | 北向交易时间对齐沪深，报单 9:10–15:00 | 同上 |
| tick（价位表） | 按价格分档，HK$0.001 至 HK$5.00。**两阶段收窄**（官网"Final implementation model"表）：**第一阶段 2025-08-04**——$10–20 档 $0.02→$0.01（−50%）、$20–50 档 $0.05→$0.02（−60%）；**第二阶段 2026-08-03**——**仅** $0.5–10 档 $0.01→$0.005（−50%）。适用范围两阶段相同："Equities, Real Estate Investment Trusts (REITs), equity warrants and other Applicable Securities"，**排除** ETP、债务证券、股票期权（ETO）与结构性产品 | [HKEX 收窄最低上落价位](https://www.hkex.com.hk/Services/Trading/Securities/Overview/Trading-Mechanism/Reduction-of-Minimum-Spreads?sc_lang=en) |
| 每手股数 | 无统一标准，10 股至 100,000 股不等，按个别证券设定；**不支持碎股自动对盘** | [HKEX 交易机制](https://www.hkex.com.hk/Services/Trading/Securities/Overview/Trading-Mechanism?sc_lang=en) |
| 涨跌停 | **无涨跌停板**；代之以市场波动调节机制（VCM）：适用恒生综合指数成分股及部分 ETF，触发区间 ±5%~±50%（参考 5 分钟前最后成交价），触发后 5 分钟冷静期内限价带交易。另有"不得偏离上次成交价 9 倍或以上"的报价限制 | 同上 |
| 收盘价 | 非 CAS 证券取连续交易最后一分钟内 15 秒间隔 5 个按盘价快照的**中位数**（抗单笔成交操纵）；CAS 证券由收市竞价产生 | 同上 |
| 复权与分红 | 同 A 股逻辑：除净日调整，研究需独立复权因子；免费源（Yahoo）的 `Adj Close` 会随后续分红**整列回改** | QNT-22 `data-sources-hk.md` §1.5 |
| 数据频率与延迟 | 官网 Daily Quotations 为收盘后日频且**仅滚动保留约 2 个月**；但其 ToS 禁自动化（见 §2.4） | QNT-22 `data-sources-hk.md` §1.1 |

### 1.5 美股（股票 / ETF / 期权）

| 维度 | 事实 | 来源 |
|---|---|---|
| 交易时段 | 核心 9:30–16:00 ET；9:30 Core Open Auction，15:50–16:00 收盘失衡期，16:00 收盘竞价。**无午休** | [NYSE hours & calendars](https://www.nyse.com/markets/hours-calendars) |
| 提前收盘 | 13:00 收盘（合资格期权 13:15）：**2026 年仅两天**——2026-11-27（感恩节次日）、2026-12-24。官方表以脚注形式给出早收日，正文表格行一律是全日休市日 | 同上 |
| 2026 全日休市 | 01-01 元旦、01-19 MLK、02-16 华盛顿诞辰、04-03 Good Friday、05-25 阵亡将士、06-19 六月节、**07-03（Independence Day observed，全日休市，非早收）**、09-07 劳工节、11-26 感恩节、12-25 圣诞 | 同上 |
| 跨年对照（防同类错误） | 2027：07-05 Independence Day observed、12-24 Christmas Day observed 均为**全日休市**；早收仅 11-26。2028：07-04 休市而 **07-03 为 13:00 早收**（脚注 \*\*）、11-24 早收。即"独立日前后那一天"逐年在休市/早收之间摆动，**必须逐年查表，不可按规则推导** | 同上 |
| tick（股票） | Reg NMS Rule 612：≥$1.00 的 NMS 股票原为 $0.01；2024-09 修订新增 **$0.005** 档，**2025-11-03 生效**，由上市交易所按三个月评估期的时间加权平均报价价差分配、每六个月重定 | [SEC 新闻稿 2024-137](https://www.sec.gov/newsroom/press-releases/2024-137)、[Davis Polk 解读](https://www.davispolk.com/insights/client-update/reg-nms-resized-sec-adjusts-tick-sizes-lowers-access-fees-and-accelerates) |
| tick（期权） | 非 Penny 类：<$3 为 $0.05，其余 $0.10；Penny 类：<$3 为 $0.01，≥$3 为 $0.05 | [Cboe 股票期权规格](https://www.cboe.com/exchange_traded_stock/equity_options_spec) |
| 个股熔断 | LULD：Tier 1（S&P500/Russell1000/部分ETF）>$3 为 ±5%，Tier 2 >$3 为 ±10%；开盘 15 分钟与收盘前 25 分钟**加倍**；越界 15 秒未回则暂停 5 分钟 | [Nasdaq LULD FAQ](https://nasdaqtrader.com/content/MarketRegulation/LULD_FAQ.pdf)、[LULD Plan](https://www.luldplan.com/) |
| 全市场熔断 | MWCB（NYSE Rule 7.12）按标普500 较前收跌幅：L1 7% / L2 13%（9:30–15:25 可触发，各停 15 分钟）/ L3 20%（全天可触发，停市至收盘） | [NYSE MWCB FAQ](https://www.nyse.com/publicdocs/nyse/NYSE_MWCB_FAQ.pdf)、[Investor.gov](https://www.investor.gov/introduction-investing/investing-basics/glossary/stock-market-circuit-breakers) |
| 期权乘数 | 标准 100 股/合约；**会被公司行为改写**——OCC 按个案调整 deliverable 与行权价（例：3-for-2 拆股后 deliverable 150 股、行权价 $50→$33.33）；现金分红只有**每合约 ≥$12.50 且非"常规"**才调整，季度等常规分红不调整 | [OCC 现金分红调整指引（Federal Register）](https://www.federalregister.gov/documents/2024/03/06/2024-04698/self-regulatory-organizations-the-options-clearing-corporation-notice-of-filing-and-immediate)、[OIC 拆股/合并/分拆](https://www.optionseducation.org/referencelibrary/faq/splits-mergers-spinoffs-bankruptcies) |
| 期权到期与行权 | 标准到期为到期月第三个星期五；美式为主 | [Cboe 股票期权规格](https://www.cboe.com/exchange_traded_stock/equity_options_spec) |
| 数据延迟 | SIP 延迟档：CTA 为发布后 15 分钟，UTP 为当日结束后 15 分钟；实时 SIP 为付费 | [Alpaca 市场数据说明](https://docs.alpaca.markets/us/docs/about-market-data-api)（厂商转述，**CTA/UTP plan 原文未验证**） |

## 2. 免费/公开数据源清单（许可三态）

> 只列本卡实际取到条款原文或明确许可声明的源。逐源 11 维评估、限流实测、历史深度见 QNT-22 的 `data-sources-*.md`（同仓 `docs/research/`，分支 `agent/impl-d/777ad112ec0e`，尚未并入 main）。

### 2.1 A股

| 源 | 许可条款链接 | 三态 | 依据原文要点 |
|---|---|---|---|
| 上交所官网 | [法律声明](https://www.sse.com.cn/home/legal/)（访问日期 2026-09-20） | **允许研究使用** | "可基于非商业目的浏览、下载本网站的内容"；"未经…书面许可，任何机构或者个人不得以向他人出售牟利为目的，使用本网站的任何内容" → 非商业研究可，商用/再分发禁止 |
| 深交所官网 | [法律声明](https://www.szse.cn/application/laws/index.html)（访问日期 2026-09-20） | **允许研究使用（非商业浏览/下载，只及于本网站）** | 第三条："任何机构或者个人可基于非商业目的浏览、下载本网站的内容。未经深圳证券交易所书面许可，任何机构或者个人不得以向他人出售牟利为目的，使用本网站的任何内容…"。**该授权只及于深交所本网站**，与上交所声明互不推及，各自独立举证。定级依据：impl-b 取证 + verify-b 独立复现（3×HTTP 200 / 10063 bytes），lead 2026-09-20 裁定升级；抓取记录见 §5.1 |
| AKShare（库） | [MIT LICENSE](https://raw.githubusercontent.com/akfamily/akshare/main/LICENSE) | **允许研究使用（仅限库本身）** | 库为 MIT。但[项目概览](https://akshare.akfamily.xyz/introduction.html)声明"数据接口和相关数据仅供学术研究使用…商业风险自负" → **数据许可继承上游站点，不因 MIT 而变** |
| Tushare Pro | [服务协议](https://tushare.pro/document/1?doc_id=405) | **不可用（quant-dev 无条目）** | 需 token。条款为"个人、不可转让、非商业使用…仅可用作个人查看使用"，禁止账号共享 |
| BaoStock | [官网](http://baostock.com/) | **不明确** | 旧站称免费开源、无需注册 token；但官网本次抓取无实质内容，**条款原文未验证**。QNT-22 另记 2026-09 新版站点出现注册/实名/付费模块 |
| 新浪 / 腾讯 / 东方财富接口 | 无公开 API 条款 | **不明确** | 非公开接口、无授权声明。按 3A 裁决**不列入可用清单** |
| 中证指数 | [指数方法学 PDF](https://oss-ch.csindex.com.cn/static/html/csindex/public/uploads/indices/detail/files/zh_CN/000510_Index_Methodology_cn.pdf) | **不明确** | 文件含商标与免责声明，未见数据使用授权条款，**使用条款原文未验证** |

### 2.2 国内期货

| 源 | 许可条款链接 | 三态 | 依据原文要点 |
|---|---|---|---|
| SHFE 合约与日报 | [SHFE 合约页](https://www.shfe.com.cn/products/futures/metal/ferrousandpreciousmetal/au_f/standard_au_f/202312/t20231205_316957.html) | **不明确** | 合约文本公开可读；网站法律声明本次未取到原文（QNT-22 记 legalnotice 页 404）→ **自用研究应可，商用/再分发未验证** |
| CFFEX 合约与细则 | [CFFEX 官网](http://www.cffex.com.cn/) | **不明确** | 合约 PDF 公开；使用条款原文**未验证** |
| DCE 交易规则 | [DCE 交易规则](http://www.dce.com.cn/dalianshangpin/fgfz/6142914/6142918/6146499/index.html) | **不明确** | 规则公开；使用条款**未验证**。QNT-22 另记美国节点直连 412 |
| TqSdk | Apache-2.0（SDK） | **不可用（quant-dev 无条目）** | 需快期账号；行情数据条款 QNT-22 记为未找到官方页 |
| SimNow / openctp | — | **不可用（quant-dev 无条目）** | 需注册 |

### 2.3 公募基金

| 源 | 许可条款链接 | 三态 | 依据原文要点 |
|---|---|---|---|
| CSRC 规章原文 | [信息披露管理办法](http://www.csrc.gov.cn/csrc/c106256/c1653985/content.shtml) | **允许研究使用** | 政府公开规章，规则事实来源（非行情数据源） |
| 上交所 ETF 列表/PCF | [上交所法律声明](https://www.sse.com.cn/home/legal/)（访问日期 2026-09-20） | **允许研究使用（非商业浏览/下载）** | 同 §2.1 上交所行；授权只及于上交所网站，不得据此覆盖深交所内容 |
| 深交所 ETF 列表/PCF | [深交所法律声明](https://www.szse.cn/application/laws/index.html)（访问日期 2026-09-20） | **允许研究使用（非商业浏览/下载，只及于本网站）** | 深交所 ETF 列表/PCF 发布于 `www.szse.cn`，属声明所称"本网站的内容"，故适用其第三条授权（lead 2026-09-20 裁定）。**独立举证，不依赖上交所声明** |
| 天天基金 `f10/lsjz` 等 | 无公开 API 条款 | **不明确** | 非公开接口、无授权声明。按 3A 裁决不列入可用清单 |
| Tushare `fund_nav`/`fund_adj` | [服务协议](https://tushare.pro/document/1?doc_id=405) | **不可用（quant-dev 无条目）** | 需 token |

### 2.4 港股

| 源 | 许可条款链接 | 三态 | 依据原文要点 |
|---|---|---|---|
| HKEX 官网（含 Daily Quotations、CCASS） | [Terms of Use](https://www.hkex.com.hk/Global/Exchange/Terms-of-Use?sc_lang=en) | **禁止** | §5 禁止 "any 'robot', 'bot', 'spider', 'scraper' or other automated device…to access, obtain, copy, monitor or republish"；禁止文本/数据挖掘与网页抓取；只可存于磁盘 "but not on any server or other storage device connected to a network"；未经书面许可禁止分发。**不可作自动化落库源** |
| HKEX 规则/说明页（交易时段、价位表） | 同上 | **禁止（自动化）/ 人工查阅可** | 本文引用的时段与价位表为**人工单次查阅**所得规则事实，非批量抓取 |
| Yahoo Finance / yfinance | [Yahoo API 条款](https://legal.yahoo.com/us/en/yahoo/terms/product-atos/apiforydn/index.html)、[yfinance README](https://github.com/ranaroussi/yfinance) | **不明确（偏禁止商用）** | yfinance 为 Apache-2.0 且明示"not affiliated…with Yahoo"；README 称 "the Yahoo! finance API is intended for personal use only"；Yahoo 条款禁止出售/转租/分租 API 及以其获利 → 个人研究可，商用/再分发不可 |
| LongPort / Futu OpenAPI | 券商条款 | **不可用（quant-dev 无条目）** | 需开户 KYC 与 token |

### 2.5 美股（含期权）

| 源 | 许可条款链接 | 三态 | 依据原文要点 |
|---|---|---|---|
| SEC EDGAR | [Webmaster FAQ / 访问条款](https://www.sec.gov/os/webmaster-faq) | **允许研究使用（公共领域）** | "All Government-created content on sec.gov and EDGAR public filing content are free to access and reuse"；要求声明 User-Agent 且 ≤10 请求/秒 |
| FRED | [FRED Terms of Use](https://fred.stlouisfed.org/legal/) | **允许研究使用（个人/非商业，逐序列看版权）** | 免费供个人使用；**禁止** "data mining, mirroring, robots, scraping"，禁止整库再分发；API 需注册 key（→ 该路径为**不可用（quant-dev 无条目）**，但无 key 的 CSV 导出不需要）。各序列分公共领域/需署名/需事先许可三档 |
| NYSE 日历页 | [hours-calendars](https://www.nyse.com/markets/hours-calendars) | **不明确** | 规则事实来源；网站条款原文**未验证**（本文用途为人工查阅规则） |
| Cboe 网站（规格页 / 日频统计） | [Cboe Terms and Conditions](https://www.cboe.com/terms)（Last Updated 2022-11-16）；[规格页](https://www.cboe.com/exchange_traded_stock/equity_options_spec) | **不明确（授权过窄，不足以落库）** | **本次已取到一手条款原文**，§2："You may view, print and download **one copy** of the Materials for your **personal non-commercial use in connection with products and services offered by Cboe**" → 个人非商业单份拷贝，**未授权构建日线库或再分发**。更正本文上一版转述：Cboe 条款中**没有** robot/spider/scraper 条款，§3 的自动化相关禁止项只有"interfere with or disrupt the Website"与"collect or harvest any data about **other users**"，与抓取行情数据不是同一条 |
| Nasdaq Trader 符号目录 | [nasdaqtrader.com](https://www.nasdaqtrader.com/) | **不明确** | 参考数据一般可内部使用；再分发条款**未验证**（QNT-22 同结论） |
| Alpaca 免费层 | [市场数据说明](https://docs.alpaca.markets/us/docs/about-market-data-api) | **不可用（quant-dev 无条目）** | 需 API key；免费层为 IEX 或 15 分钟延迟 SIP，期权为 indicative |
| Massive（原 Polygon）免费层 | [pricing](https://massive.com/pricing) | **不可用（quant-dev 无条目）** | 需 API key；免费层 5 calls/min、2 年历史、仅 EOD |
| Nasdaq Data Link 免费集 | [data.nasdaq.com](https://data.nasdaq.com/) | **不可用（quant-dev 无条目）** | 免费集需注册 key（匿名限 20 次/10 分钟） |
| Tiingo 免费层 | [tiingo.com](https://www.tiingo.com/) | **不可用（quant-dev 无条目）** | 需注册 API key；**本卡未实测、未注册**，仅作为 §4 凭据路径候选列出 |
| Stooq | 无可达条款页 | **不明确** | 条款页**未验证**；QNT-22 实测本节点被 JS PoW 拦截，批量 zip 需 Basic Auth |
| IEX HIST（历史数据下载） | [IEX Historical Data Terms of Use](https://iextrading.com/iex-historical-data-terms/) | **允许研究使用（权利人一手条款，无需凭据）** | 本次实测无 key 可下载；条款明示 "Data provided for free by IEX"，再分发需署名。**但数据是 TOPS/DEEP 的 pcap 逐笔、且只含 IEX 一家成交，不是合并市场日线**——许可合格而形态不符，见 §4.1 |
| exchange_calendars（日历库，非数据源） | [Apache-2.0](https://github.com/gerrymanoim/exchange_calendars) | **允许研究使用** | 50+ 交易所会话/午休/提前收盘；含 XNYS、XHKG、XSHG。**可作交易日历表的初始化来源与交叉校验** |

## 3. 对 ADR-0003（QNT-23）的多市场抽象接口建议

> 建议针对 ADR-0003 §5「`Market` / `Instrument` / `Calendar` / `DataSource` 接口，加密先实现，其他市场只留接口」。以下三张表都遵循 ADR-0002：只 insert、每行带 `source` / `source_version` / `ingested_at` / `run_id` / `batch_id`，修订用新行表达。

### 3.1 交易日历表 `trading_calendar`

A股/港股的午休、国内期货的跨日夜盘、美股的 13:00 提前收盘，都无法由"工作日减假日"推导 → 必须落**显式会话行**。一个交易日可有多段会话，故主键含 `session_seq`。

| 字段 | 类型 | 说明 |
|---|---|---|
| `calendar_id` | text | 交易日历标识，建议用 MIC：`XSHG`/`XSHE`/`XHKG`/`XNYS`/`XSHF`/`CCFX`。与 `exchange_calendars` 对齐便于交叉校验 |
| `session_date` | date | **交易日（结算归属日）**，非自然日。国内期货夜盘 21:00 属于**次一交易日**，这是夜盘的关键陷阱 |
| `session_seq` | smallint | 同一交易日内第几段：A股 1=上午 2=下午；期货 0=夜盘 1=上午 2=下午 |
| `session_kind` | text | `pre_auction` / `continuous` / `closing_auction` / `after_hours_fixed_price` / `night` |
| `open_utc` / `close_utc` | timestamptz | **UTC 存储**，跨日夜盘因此天然无歧义 |
| `local_tz` | text | `Asia/Shanghai` / `Asia/Hong_Kong` / `America/New_York`，用于还原本地时间 |
| `is_half_day` | bool | 港股三个前夕、美股 13:00 提前收盘日 |
| `random_close_window_s` | int | 港股 CAS 随机收市 0–120 秒；无则 0 |
| `source` / `source_version` / `ingested_at` / `run_id` / `batch_id` | — | ADR-0002 必带列 |

要点：① 提前收盘日必须是**数据行**而非代码常量（每年不同）；② 港股价位表与收市机制有生效日切换（2025-08-04 / 2026-08-03），日历表只管时间，价位规则归品种元数据的版本化字段。

### 3.2 品种元数据表 `instrument_meta`

乘数、tick、涨跌停都**随时间变更**（美股 tick 2025-11-03 新增半美分档；港股价位表两阶段收窄；期货涨跌停按公告调整；OCC 调整改写期权 deliverable）。因此本表必须是**带生效区间的版本化表**，而不是当前值快照。

| 字段 | 类型 | 说明 |
|---|---|---|
| `instrument_id` | text | 内部主键，稳定且不复用 |
| `market` / `asset_class` | text | `us`/`cn`/`hk` × `equity`/`etf`/`option`/`future`/`fund`/`convertible` |
| `symbol` / `symbol_kind` | text | 外部代码及其命名体系（`ticker`/`occ_osi`/`ths`/`hkex_code`），一个 instrument 可有多个代码行 |
| `effective_from` / `effective_to` | date | **版本区间**。规则变更 = 新行，不 update（ADR-0002 D2.1） |
| `multiplier` | numeric | 每合约标的数量/点值：美股期权 100（**可被 OCC 调整**）、50ETF期权 10000、IF 300、IO 100、SHFE 黄金 1000 |
| `multiplier_unit` | text | `shares` / `cny_per_point` / `grams` / `tons` — 没有这列，300 和 1000 无法比较 |
| `tick_size` / `tick_rule_ref` | numeric / text | 单值 tick，或指向分档价位表（港股 spread table、美股期权 penny/非 penny）的规则 id |
| `price_limit_kind` | text | `pct`（A股 ±10%/±20%/±30%）/ `formula`（ETF期权公式）/ `none_vcm`（港股）/ `luld`（美股）/ `dynamic_notice`（期货按公告） |
| `price_limit_params` | jsonb | 对应参数；`formula` 类存公式标识而非硬编码数字 |
| `settlement_kind` | text | `physical` / `cash`；`t_plus` 交收档（A股 T+1） |
| `exercise_style` / `expiry_rule` | text | `european`（50ETF期权）/ `american`（美股期权）；`third_friday` / `fourth_wednesday` 等 |
| `underlying_id` | text | 期权/期货指向标的 instrument |
| `calendar_id` | text | 外键 → `trading_calendar` |
| `source` / `source_version` / `ingested_at` / `run_id` / `batch_id` | — | ADR-0002 必带列 |

要点：① `multiplier_unit` 与 `price_limit_kind` 是把五类市场塞进一张表的关键——缺了它们就只能每市场一张表；② 美股期权的 OCC 调整应写成新版本行并记 `adjustment_memo_ref`，旧合约行保持不变（可重放）。

### 3.3 复权因子表 `adjust_factor`

"复权"在五类市场是五种语义，单一 factor 列会静默混淆。建议用 `adjust_kind` 区分，且**只存因子、不存复权价**——复权价随后续事件整列回改，与 ADR-0002 D2.1 只 insert 直接冲突（QNT-22 对 Yahoo `Adj Close`、东财 `fqt` 的结论同此）。

| 字段 | 类型 | 说明 |
|---|---|---|
| `instrument_id` | text | 外键 |
| `ex_date` | date | 除权除息日 / 换月日 / 分红再投资日 |
| `adjust_kind` | text | `cash_dividend` / `stock_dividend` / `split` / `rights_issue`（A股配股）/ `fund_distribution`（公募分红再投资）/ `futures_roll`（换月拼接）/ `occ_option_adjust`（期权合约调整） |
| `factor_kind` | text | `ratio`（等比）/ `spread`（等差，期货换月专用）—— 期货两种方法结果不同且**无官方定义**，必须显式记录用的是哪种 |
| `factor_value` | numeric | 因子值本身 |
| `cash_amount` / `share_ratio` | numeric | 原始事件量（每股现金分红、送股比例），保留以便重算 |
| `direction` | text | `forward`（前复权）/ `backward`（后复权）—— 期货回测建议 backward（前复权可能出现负价） |
| `nav_kind` | text | 仅公募：`unit`（单位净值）/ `cumulative`（累计净值）/ `adjusted`（复权净值）。三者语义不同，业绩口径用 `adjusted` |
| `disclosure_date` | date | **仅公募必填**：净值 T+1 披露 → 回测信息集边界按此列，而非 `ex_date` |
| `adjustment_memo_ref` | text | 仅美股期权：OCC info memo 编号，供可解释性追溯 |
| `source` / `source_version` / `ingested_at` / `run_id` / `batch_id` | — | ADR-0002 必带列 |

要点：① `futures_roll` 严格说不是复权而是**拼接**，放进同一张表是为了让回测取价路径统一，但必须靠 `adjust_kind` + `factor_kind` 自证；② `disclosure_date` 是公募唯一不能省的列——没有它，基金回测会系统性地用到未来信息。

### 3.4 给 ADR-0003 的三条落地建议

1. **接口留而不实现，但表结构现在就定版本化**。按 owner 2B 裁决其他市场不实现；然而 `effective_from/to` 与 `multiplier_unit` 这类字段若一期不留，二期加就是 schema 迁移（关键路径）。建议 ADR-0003 直接采用上述字段，加密先只填 `market='crypto'` 的行。
2. **交易日历不要依赖库的运行期推导**。`exchange_calendars`（Apache-2.0）可作初始化与交叉校验来源，但会话行必须落库并带 `source`，否则升级库版本会静默改变历史回测的会话边界——违反 ADR-0002 D2.4 可重放。
3. **复权只存因子不存复权价**，取价在查询层（DuckDB 视图）合成。这与 ADR-0003 §2「DuckDB 只作查询/视图层」一致。

## 4. 美股日线免费源逐源判定：股票/ETF 与期权均未证实合格

本卡对"合格"的判据（三项全中才算）：**① 无需凭据**（不注册、不申请 key——ADR-0001 边界内本卡不可能验证凭据源）；**② 取到权利人一手许可原文**（第三方库的 README 不算，它无权代权利人授权）；**③ 该许可覆盖研究用途的存储/落库**（只允许"浏览"或"单份个人拷贝"的不算）。

§0 上一版写"只有美股股票/ETF 满足"，按此判据复核**不成立**——股票/ETF 与期权都没有合格源，区别只在失败原因不同。逐源判定（均以本次取到的一手条款为准）：

### 4.1 股票 / ETF 日线

| 候选 | 无需凭据 | 权利人一手许可 | 覆盖研究落库 | 结论 |
|---|---|---|---|---|
| Yahoo Finance（经 yfinance） | 是 | **否** —— [Yahoo API 条款](https://legal.yahoo.com/us/en/yahoo/terms/product-atos/apiforydn/index.html) 针对的是其官方 API 产品，未授权非官方端点；[yfinance README](https://github.com/ranaroussi/yfinance) 自述 "not affiliated…with Yahoo"，其"personal use only"是**第三方声明，不能替代权利人授权** | 未证实 | **不合格**（§2.5 亦评"不明确"） |
| IEX HIST（历史数据下载） | **是** —— 本次实测 `https://iextrading.com/api/1.0/hist` 返回 JSON 清单，逐日文件走 Google Storage 直链，Range 请求 HTTP 206，**全程无 key、无登录** | **是** —— [IEX Historical Data Terms of Use](https://iextrading.com/iex-historical-data-terms/) 为权利人 IEX 自身条款，明示 "Data provided for free by IEX"，再分发只要求署名 | 许可上可以，**但数据形态不符** | **不合格（形态不符，非许可问题）**：提供的是 TOPS/DEEP 的 **pcap 逐笔二进制**，且只含 IEX 一家交易所成交（条款自述 "does not reflect trading activity on markets other than IEX…a reference point only"），**不是合并市场日线** |
| Stooq | 是（网页） | **否** —— 条款页 `https://stooq.com/terms/` 本次 HTTP 404，无可达条款 | 未证实 | **不合格** |
| Tiingo / Alpaca / Massive / Nasdaq Data Link | **否**，均需注册 key | 不适用 | 不适用 | **不可用（quant-dev 无条目）** |
| SEC EDGAR | 是 | 是 —— [Webmaster FAQ](https://www.sec.gov/os/webmaster-faq)，公共领域 | 是 | **不适用**：只有申报文件，**不含行情日线** |
| FRED | 无 key 的 CSV 导出可 | 是 —— [Terms](https://fred.stlouisfed.org/legal/) | 部分（禁 scraping/mirroring） | **不适用**：宏观序列，**不含个股日线** |

**小结：股票/ETF 日线本次同样未证实合格源。** 最接近的 IEX HIST 卡在数据形态（单所逐笔 pcap）而非许可，理论上可自行聚合为 IEX 单所日线，但那与"美股合并市场日线"不是一回事，本卡不据此宣称满足。

### 4.2 期权日线

| 候选 | 是否提供期权日线 | 许可判定 | 结论 |
|---|---|---|---|
| Cboe 网站（Daily Market Statistics / 规格页） | 有日频统计 | [Terms §2](https://www.cboe.com/terms) 仅授权"one copy…personal non-commercial use in connection with products and services offered by Cboe" | **不合格**：授权过窄，未涵盖构建日线库 |
| Alpaca 期权数据 | 有 | [文档](https://docs.alpaca.markets/us/docs/about-market-data-api) 需 API key | **不可用（quant-dev 无条目）** |
| Massive（原 Polygon） | 有 | [pricing](https://massive.com/pricing) 需 API key | **不可用（quant-dev 无条目）** |
| Nasdaq Data Link 免费集 | 部分 | [data.nasdaq.com](https://data.nasdaq.com/) 需注册 key | **不可用（quant-dev 无条目）** |
| SEC EDGAR | **不提供**期权行情 | [Webmaster FAQ](https://www.sec.gov/os/webmaster-faq) 公共领域 | 不适用 |
| FRED | **不提供**期权行情 | [Terms](https://fred.stlouisfed.org/legal/) | 不适用 |
| OCC 网站（成交量/未平仓报告） | 有日频聚合量，**无逐合约 OHLC** | 本次访问返回 403（Cloudflare JS 挑战），**条款未取到** | **未验证**，且即使可达也非逐合约日线 |

**小结：期权日线无合格免费源。** 未为凑结论补任何来源——探过的 optionsDX（[terms 页](https://www.optionsdx.com/terms/) 实质内容仅退款条款）、DoltHub `post-no-preference/options`（文档页无许可声明）均因取不到明确许可原文而不列入上表作为合格项。

### 4.3 总结论

**美股股票/ETF 与期权日线，本次均未证实存在合格免费源**（判据见 §4 开头三项）。这不等于"一定不存在"——只等于本卡在 ADR-0001 凭据边界内、不注册不申请 key 的前提下没能证实。

这对 QNT-23 的直接影响：美股日线（股票/ETF 与期权都一样）**不应按"免费可得"排期**。可行路径有三条——**走 quant-dev 立项凭据**（股票/ETF 可选 Tiingo/Alpaca/Massive，期权可选 Alpaca/Massive，届时按 ADR-0001 D1.5 经 `op` 注入）；**向权利人书面申请许可**（Cboe 等）；或**接受 IEX HIST 的单所口径**并自行从 pcap 聚合（许可干净且无需凭据，代价是只有 IEX 一家的成交，不能当合并市场行情用）。

## 5. 本卡未验证项清单

按"无来源不写"原则，以下项本卡查到二手转述但**未取到一手原文**，不应被下游当作既定事实：A股申报数量单位条文；上交所/深交所交易规则条文号与 tick 条文原文；A股 T+1 的监管原文；各期货交易所法律声明；商品期货日盘小节休息时段；夜盘时段的交易所一手公告；公募 T 日切分与 T+1 确认的监管原文；基金三种净值的监管定义；CTA/UTP 延迟的 plan 原文；NYSE/Nasdaq Trader 网站条款；中证指数使用条款；Stooq 条款；BaoStock 现行条款；OCC 网站条款（403 Cloudflare 挑战）。

### 5.1 已复核（保留作定级依据）：深交所法律声明

状态：impl-b 取证 → verify-b 独立复现一致 → lead 2026-09-20 裁定，深交所定级为"允许研究使用（非商业浏览/下载，只及于本网站）"。本节保留抓取记录供后续复核，**不再是未验证项**。

抓取记录（可原样重跑）：URL `https://www.szse.cn/application/laws/index.html`，2026-09-20 连续 3 次均 HTTP 200 / 10063 bytes；裸路径 `http://www.szse.cn/application/laws/` 连接被重置（`curl: (56) Recv failure`），是上一版误记"抓取无输出"的原因。取回文本第三条：

> 在遵守中国有关法律与本声明的前提下，任何机构或者个人可基于非商业目的浏览、下载本网站的内容。未经深圳证券交易所书面许可，任何机构或者个人不得以向他人出售牟利为目的，使用本网站的任何内容，此种使用包括但不限于拷贝、下载、存贮、通过硬拷贝或电子抓取系统、发送、转换、出租、演示、转载、复制、修改、销售、传播、出版或任何其它形式的散发。

verify-b 已独立重跑同一 URL 并确认 3×HTTP 200 / 10063 bytes、第三条引文一致。该文本**现为深交所定级的一手依据**（§0、§2.1、§2.3 三处一致）。注意其授权边界与上交所同构：只及于本网站、只限非商业浏览/下载，不覆盖商用或再分发。
