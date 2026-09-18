# 国内期货 / 期权数据源全景：商品期货、股指期货、商品期权、股指期权、ETF 期权

- 调研日期：2026-09-18；探测节点：美国（出口 IP 134.56.13.103），**未使用代理，未注册任何账号**
- 探针脚本：`docs/research/probes/akshare_cn_futures.py`（17 项检查，15 通过）、`exchange_sites_cn.py`（期货交易所 6 项，3 通过）；汇总 `probes/results.md`
- 维度编号同 [data-sources-cn-equity.md](data-sources-cn-equity.md)：① 覆盖 ② 频率 ③ 深度 ④ 价格 ⑤ 限流 ⑥ 认证 ⑦ 许可 ⑧ 访问 ⑨ 维护 ⑩ ADR-0002 适配 ⑪ 可达性
- 总索引见 [data-sources-index.md](data-sources-index.md)

## 0. 结论速览

| 结论 | 依据 |
|---|---|
| **免费、权威、最贴合 append-only 的日线主干是交易所官网每日行情文件**：SHFE / INE / CZCE / CFFEX / GFEX 从美国节点直连可拉（经 AKShare `get_futures_daily` 实测 305/67/238/28/48 行），**DCE 被 WAF 412 拦截**（本节点不可达） | §1.4、§7 表 A/B |
| 期权日线：SHFE 期权文件 776 行含 `德尔塔`；新浪单合约日线可拉（au2612C1000 93 行、50ETF 10010974 155 行、mo2610C7500 44 行）但**只有合约寿命内**，无跨合约拼接；SSE 官方每日期权统计 5 行 | §7 表 A |
| 免费实时/分钟/tick 只能靠 TqSdk 免费版（需快期账号）或 CTP 行情（SimNow/openctp，需注册），本次按约束均未注册 | §1.1、§1.5 |
| 付费一站式：RQData（价格不公开）、TqSdk 专业版（¥14888/年，价格透明）、Tushare（2000 积分 ≈ ¥200/年，分钟另购） | §1.3、§1.6 |
| 海外源 Databento / Kaiko / Yahoo **均不覆盖**中国期货交易所 | §1.12 |
| append-only 最大风险：**主力连续合约定义各家不同**（TqSdk 持仓+成交双最大、RQData 1.1 倍持仓、新浪/东财黑箱）→ 建议自算主力映射落 `dominant_map` 表；结算价以交易所文件为唯一真相 | §1.1/§1.2/§1.6 ⑩ |

## 1. 逐源评估

### 1.1 天勤 TqSdk（信易科技；tqsdk 3.10.2，2026-08-18）— 需快期账号，未实测

1. ① SHFE/DCE/CZCE/CFFEX/INE/GFEX 期货 + 商品期权 + 中金所期权；`KQ.m@` 主连、`KQ.i@` 指数；SSE/SZSE ETF 期权仅专业版。quote 含 `settlement/pre_settlement/open_interest/upper_limit/lower_limit`、5 档盘口；`query_option_greeks()` 为 SDK **本地计算**（默认 r=0.025）。来源：<https://doc.shinnytech.com/tqsdk/latest/usage/mddatas.html> 、<https://doc.shinnytech.com/tqsdk/latest/reference/tqsdk.api.html> 、<https://doc.shinnytech.com/tqsdk/latest/profession.html>
2. ② tick、任意秒级 K 线至日线，WebSocket 实时推送。
3. ③ 免费版 `get_kline_serial/get_tick_serial` 每序列上限：api reference 写 **10000 根**，mddatas 页写 **8000 根**（**文档自相矛盾，见 §6**）；专业版 `get_kline_data_series/DataDownloader`：期货 tick 2016 起、股票 2018 起。来源：<https://www.shinnytech.com/tqsdk-buy/>
4. ④ 免费版 ¥0（限指定期货公司、3 账户）；专业版 ¥14888/年（划线 19888；另有 ¥1988 月付）；企业版 ¥30000/年（划线 50000；¥6000 月付）；15 天试用。来源：同上
5. ⑤ 序列上限 8000/10000；无公开 QPS（**未验证**）。
6. ⑥ 快期账号（account.shinnytech.com，手机号/邮箱+密码），行情无需期货账户；是否要求大陆手机号 **未验证**。来源：<https://doc.shinnytech.com/tqsdk/latest/quickstart.html>
7. ⑦ SDK Apache-2.0；**行情数据落库/商用/再分发条款未找到官方页（未验证）**。
8. ⑧ Python SDK（WebSocket 长连接）；`vnpy_tqsdk` 封装。
9. ⑨ GitHub shinnytech/tqsdk-python 5035★，最近 push 2026-08-18；持续维护。
10. ⑩ 合约代码 `EXCHANGE.code` 稳定；主连切换规则公开（持仓量与成交量均最大→次日开盘切换），指数为昨持仓加权；`KQ.m@` 不复权，回放需自存映射；结算价盘后更新 → 落库应以交易所文件校验。
11. ⑪ 文档/官网美国可访问；行情服务器海外连通 **未验证**。

### 1.2 AKShare 期货/期权模块（1.18.96）— 已实测

1. ① `get_futures_daily`（上游 6 所官网文件，含 `settle/pre_settle/open_interest/turnover`）；`futures_main_sina`（新浪主连 RB0/IF0 等）；`futures_zh_daily_sina`（新浪单合约）；`futures_zh_spot`（新浪实时快照）；`futures_hist_em`（东财"主连"，2014 起；本节点东财不通）；`futures_zh_minute_sina` 1/5/15/30/60 分；`futures_fees_info/futures_comm_info/futures_rule`（保证金/手续费）。期权：`option_hist_shfe/dce/czce/gfex`（交易所文件，含 Delta/IV）、`option_daily_stats_sse`（SSE 官方每日统计）、`option_sse_codes_sina`+`option_sse_daily_sina`（ETF 期权单合约日线）、`option_cffex_zz1000_*_sina`（股指期权）、`option_commodity_contract_table_sina`+`option_commodity_hist_sina`（商品期权 T 型报价 + 单合约日线）、`option_risk_indicator_sse`（SSE 官方 Greeks/IV）。来源：<https://akshare.akfamily.xyz/data/futures/futures.html> 、<https://akshare.akfamily.xyz/data/option/option.html>
2. ② 日线、分钟（新浪）、实时快照；无 tick。
3. ③ 新浪 RB0 自 2009-03-27（上一轮实测 4246 行）；交易所日线随交易所（SHFE 2002 起）；AKShare 文档注明 20040625/20070604/20081226/20090119 原网页缺失。期权单合约日线仅合约寿命内（实测 44–155 行）。
4. ④ 免费。
5. ⑤ 无官方数字；受上游反爬（新浪 JSONP、交易所 WAF）影响；本次 `option_hist_shfe` 单日 10.9s。
6. ⑥ 无。
7. ⑦ 库 MIT；数据受上游（新浪/东财/交易所）条款约束，AKShare 不授予再分发权。见 §1.4 ⑦。
8. ⑧ Python 爬虫封装。
9. ⑨ 几乎日更；接口随上游改版频繁失效（本次即遇 `option_daily_stats_sse` 参数名为 `date`、股指期权需完整合约码等文档与实现差异）。
10. ⑩ 新浪 `RB0` 主连规则黑箱、历史可被上游回改 → 不宜作主连真相；`get_futures_daily` 返回交易所原生合约代码（CZCE 3 位年月如 `SR609` 需规范化为 4 位）；`settle` 来自交易所文件，可作结算价真相。**注意** `futures_main_sina` 返回列名 `动态结算价`（非交易所结算价）。
11. ⑪ 美国→新浪 200；→SHFE/INE/CZCE/CFFEX/GFEX 200；→DCE 412（`JSONDecodeError` 因 WAF 返回 HTML）；→东财 push2his 不通。
- 实测：§7 表 A。

### 1.3 Tushare Pro 期货/期权 — 需 owner 提供 token，未实测

1. ① `fut_daily`（OHLC/settle/vol/amount/oi，6 所）、`fut_mapping`（主力/连续↔月合约映射日表）、`fut_settle`（结算参数：结算价、手续费率、交割费）、`fut_basic`、`opt_basic`、`opt_daily`（SSE/SZSE/CFFEX/DCE/SHFE/CZCE）；分钟 `ft_mins`/`opt_mins`。**无 Greeks**。来源：<https://tushare.pro/document/2?doc_id=138> 、[159](https://tushare.pro/document/2?doc_id=159) 、[189](https://tushare.pro/document/2?doc_id=189) 、[141](https://tushare.pro/document/2?doc_id=141) 、[158](https://tushare.pro/document/2?doc_id=158) 、[313](https://tushare.pro/document/2?doc_id=313)
2. ② 日线；分钟 1/5/15/30/60（独立权限）。
3. ③ 文档示例 2018；`ft_mins` 称"超过 10 年分钟数据"；日线起点 **未验证**。
4. ④ 200 元=2000 积分（1:10）；`fut_daily/opt_daily/fut_mapping/fut_settle` 需 2000 积分，`opt_basic` 需 5000；分钟线单独开权限（价格未公开）；机构价为个人 10 倍。来源：<https://tushare.pro/document/1?doc_id=290>
5. ⑤ 2000 积分 200 次/分；5000 积分 500 次/分；单次 `fut_daily` 2000 行、`opt_daily` 15000 行、`ft_mins/opt_mins` 8000 行、`fut_settle` 1600 行。
6. ⑥ 注册 + token；手机号要求 **未验证**。**注册门槛**：需注册账号并积分达 2000（付费 200 元或社区贡献）。
7. ⑦ 服务协议"非商业目的、个人查看"（同 A 股文档 §1.2）；再分发未明文。来源：<https://tushare.pro/document/1?doc_id=405>
8. ⑧ Python SDK（HTTP）。
9. ⑨ 1.4.29（2026-03-25）。
10. ⑩ `fut_mapping` 提供主力映射日表可直接 insert-only 落库，但判定规则未公开（可解释性弱）；`fut_settle` 独立于行情，可作结算价交叉校验。
11. ⑪ tushare.pro 美国 200。

### 1.4 交易所官网每日行情（免费、权威）— 已实测

| 交易所 | URL 模式 | 美国节点（本次） | 深度（上一轮抽样） | 期权字段 |
|---|---|---|---|---|
| SHFE | `https://www.shfe.com.cn/data/tradedata/future/dailydata/kxYYYYMMDD.dat`（JSON：OPEN/HIGH/LOW/CLOSE/SETTLEMENT/PRESETTLEMENT/VOLUME/OPENINTEREST/TURNOVER）；期权 `…/option/dailydata/kxYYYYMMDD.dat` | ✅ 200（1.6s）；AKShare 305 行 | 20020107 有；期权 20180921 起 | DELTA、`o_cursigma`（IV） |
| INE | `https://www.ine.cn/data/tradedata/future/dailydata/kxYYYYMMDD.dat` | AKShare ✅ 67 行；直连探针用的旧路径 `/data/dailydata/kx/` 404（路径已迁） | 20180326 起 | 同 SHFE |
| CZCE | `https://www.czce.com.cn/cn/DFSStaticFiles/Future/YYYY/YYYYMMDD/FutureDataDaily.{htm,xls,txt}`；期权 `…/Option/…/OptionDataDaily.*` | 直连探针 **412**；AKShare `get_futures_daily(market="CZCE")` ✅ 238 行（AKShare 走另一路径/头） | 2018 有；2015 该路径 404（旧路径 **未验证**） | DELTA、隐含波动率 |
| CFFEX | `http://www.cffex.com.cn/sj/hqsj/rtj/YYYYMM/DD/YYYYMMDD_1.csv`（GBK；含今结算/前结算/持仓量/Delta）；月度 zip `…/sj/historysj/YYYYMM/zip/YYYYMM.zip` | ✅ 200（2.4s）；AKShare 28 行 | 20100416 有；期权 20191223 有 | Delta |
| DCE | `http://www.dce.com.cn/publicweb/quotesdata/dayQuotesCh.html` | **❌ 412（JS-cookie WAF）**，AKShare 亦 `JSONDecodeError` → **本节点不可达** | — | AKShare 文档称有 Delta/IV（**未验证**） |
| GFEX | `POST http://www.gfex.com.cn/u/interfacesWebTiDayQuotes/loadList`（`trade_date`、`trade_type=0/1`） | ✅ 200（0.7s）；AKShare 48 行 | 20221222 起（开市日） | delta、impliedVolatility |
| SSE ETF 期权 | `query.sse.com.cn/commonQuery.do?sqlId=…`（需 Referer）；AKShare `option_daily_stats_sse` | ✅ 5 行（0.6s） | — | 官方风险指标页（Greeks/IV） |
| SZSE 期权 | `www.szse.cn/api/report/ShowReport?…CATALOGID=ysphq` | 上一轮 200 但 0 字节（参数 **未验证**） | — | — |

- ② 日线（T 日盘后发布）。④ 免费。⑥ 无。⑤ 无公开数字；DCE/CZCE 有 WAF。
- ⑦ 各所"法律声明"限制转载：SHFE legalnotice 页 404（**未验证**）；CFFEX/DCE/CZCE/GFEX 条款 **未验证** → **自用落库应可，商用/再分发需法务核实**。
- ⑧ 静态文件 GET（GFEX 为 POST JSON）。⑨ 路径不定期迁移（本次 INE 旧路径 404、SZSE 上次路径 404）。
- ⑩ **最佳**：文件按日期不可变、结算价权威；交易所偶发"更正公告"→ 应 insert 新版本行（`revision`）而非覆盖。CZCE 合约代码 3 位年月需统一映射；CZCE 文件 `date` 列为字符串 `YYYYMMDD`（本次探针误按 epoch 解析显示 1970-01-01，是探针解析瑕疵，数据本身正确）。
- ⑪ 美国→SHFE/INE/CZCE(经 AKShare)/CFFEX/GFEX/SSE 可达；→DCE 不可达。国内→全部可达（**未验证**）。
- 实测：§7 表 A/B。

### 1.5 CTP 行情 API（SimNow / openctp / 期货公司实盘）— 需注册，未实测

1. ① 6 所期货 + 商品期权 + 中金所期权 L1 tick（最新价、通常 1 档盘口、OI、结算价盘后推送、涨跌停）；**不含历史**。
2. ② 500ms 快照实时。③ 无历史（需自录）。
4. ④ SimNow 免费（上期技术运营，来源：<https://www.shfe.com.cn/services/indexopt/promotion/202108/t20210804_797695.html>）；openctp 7x24/仿真免费，VIP 仿真 ¥1000/年（<http://www.openctp.cn/Trading.html>）。
5. ⑤ 无公开；订阅合约数无硬限（**未验证**）。
6. ⑥ SimNow 网站自注册（第三方称需手机号，**未验证**；官网从美国 403）；openctp 关注微信公众号自动发号；**实盘行情前置需期货公司账户**。按硬边界不接触任何券商/期货账户。
7. ⑦ openctp 代码 BSD-3；SimNow 数据条款 **未验证**。
8. ⑧ C++ API；Python：`openctp-ctp` 6.7.11.0（2025-08-18，Py3.7–3.13）、`vnpy_ctp` 6.7.11.4（2026-03-29）。
9. ⑨ openctp 2936★，push 2026-07-29；SimNow 历史多次停服维护（**未验证**）。
10. ⑩ **openctp 7x24 为"循环回放最近一个交易日 tick"**，不可作真实数据源；SimNow 仿真行情为实盘转发。tick 录制天然 append-only；`source` 需区分 simnow/openctp/broker。
11. ⑪ 上一轮 TCP 探测：`182.254.243.31:30011`（SimNow 仿真行情）与 `trading.openctp.cn:30011` 可连；`40011`（7x24）不通；simnow.com.cn 网页 403。
- 附：**openctp 数据中心** `http://dict.openctp.cn/instruments?types=futures&markets=SHFE&products=au` 免费无注册，返回合约乘数、保证金率、手续费率、上市/到期日（上一轮美国 200）→ 保证金/手续费维度最佳免费源。来源：<http://www.openctp.cn/DataCenter.html>

### 1.6 米筐 RQData（rqdatac 3.7.1）— 付费，未实测
1. ① SHFE/DCE/CZCE/CFFEX（INE/GFEX 部分）期货 tick/分钟/日线；`futures.get_dominant`（rule 0–3，默认"其他合约持仓 > 主力 1.1 倍次日切换"）、`88/888/99` 连续（拼接/前复权/持仓加权）、`get_ex_factor`、`get_trading_parameters`（保证金/手续费/限仓）、会员排名、仓单、基差；期权 `options.get_greeks`（IV/Δ/Γ/Vega/Θ/Rho 日频，分钟仅 CFFEX 股指期权）。来源：<https://www.ricequant.com/doc/rqdata/python/futures-mod> 、<https://www.ricequant.com/doc/rqdata/python/options-mod>
2. ② tick/1m/1d。③ 2005–2013 起视交易所；50ETF 期权 2015 起。
4. ④ 官网不公开；vn.py 论坛 2021 年提及 3000→10000/15000 元档（**未验证现价**）。
5. ⑤ 流量配额，试用 1 GB/天。⑥ 手机号/license。⑦ **未验证**。⑧ Python + HTTP API；`vnpy_rqdata`。
10. ⑩ **最优**：主力规则参数化 + 复权因子可重放；888 前复权回改历史 → 只落 raw + factor。⑪ 文档美国可达；数据服务 **未验证**。

### 1.7 聚宽 JQData — 区域封锁，全部维度未验证
- 官网/文档对非中国大陆 IP 返回"当前地区暂不支持访问"。第三方转述：2005 起、四所期货、期权日线与风险指标、试用仅 15 个月前至 3 个月前数据（**未验证**）。jqdatasdk 1.9.8。

### 1.8 迅投 QMT / xtquant（250807.1.2）
- 市场码 SF/DF/ZF/IF/INE/GF；主连 `rb00.SF`、加权 `rbJQ00.SF`；SHO/SZO ETF 期权与商品期权；字段含 `settlementPrice/openInterest`；tick/1m/5m/1d；`bsm_iv/bsm_price` 本地 Greeks；**必须启动 MiniQMT 客户端**（券商开通、Windows）。价格随券商，通常免费但有资金门槛（**未验证**）。⑪ 本 LXC 无 Windows/券商环境 → 不适用。来源：<https://dict.thinktrader.net/dictionary/future.html> 、<https://dict.thinktrader.net/dictionary/option.html>

### 1.9 掘金量化 gm（3.0.186）
- 6 所合约信息、连续合约、排名、仓单；需掘金终端（Windows）；配额/价格 **未验证**。来源：<https://www.myquant.cn/docs2/docs/期货.html>

### 1.10 通达信 pytdx
- `pytdx.exhq` 扩展行情支持期货/期权；仓库 2020-04-15 归档、作者声明"老旧过时、勿商用"；非官方服务器 → **不建议**。来源：<https://github.com/rainx/pytdx>

### 1.11 Wind / Choice / vn.py datafeed
- vn.py 官方 datafeed：迅投研 XT、RQData、UData、TuShare、TQSDK、Wind、iFinD、Tinysoft（<https://www.vnpy.com/docs/cn/community/info/datafeed.html>）；Wind/Choice 价格需询价（**未验证**，机构级数万/年）。

### 1.12 海外源（均不覆盖）
- **Databento** venues 页中国仅 SSE/SZSE/BSE/CIBM/沪深港通，无任何中国期货交易所（<https://databento.com/venues>）。**Kaiko** 加密为主（<https://www.kaiko.com/>）。**Yahoo** 搜索 "SHFE rebar" 0 结果。**Investing.com** 美国 403 且无 API。

### 1.13 期权 Greeks / IV 来源
- 交易所日文件有 Delta（SHFE/CZCE/CFFEX/GFEX）与 IV（SHFE `o_cursigma`、CZCE、GFEX）；SSE 有官方风险指标页；DCE **未验证**。
- 实时/全 Greeks：TqSdk `query_option_greeks`、xtquant `bsm_*` 为本地模型计算；RQData `get_greeks` 为服务端计算。→ 建议 quantime 自算（BS/BAW，输入 settle + 无风险利率），落 `greeks_source=self:model_vX` 保证可重放；交易所 Delta/IV 作交叉校验。

## 2. 汇总对比表

| 源 | 期货日线 | 分钟/tick | 期权链 | Greeks | 主力/连续 | 保证金/手续费 | 价格 | 需账号 | 美国节点 | 落库风险 |
|---|---|---|---|---|---|---|---|---|---|---|
| 交易所文件 | ✔ 权威 | ✘ | ✔ | Δ/IV 部分 | ✘ | 公告 | 免费 | 无 | SHFE/INE/CZCE/CFFEX/GFEX ✔ 实测，DCE ✘ | 低 |
| AKShare | ✔ | 分钟（新浪） | ✔ 单合约 | Δ/IV 转载 | 黑箱 | ✔ | 免费 | 无 | 15/17 实测 | 高（上游改版） |
| TqSdk 免费 | ✔（≤8000–10000 根） | ✔ 实时 | ✔ | 本地算 | KQ.m@ 规则明 | 部分 | 免费 | 快期 | 文档 ✔，行情未验证 | 中 |
| TqSdk 专业 | ✔ | tick 2016 起 | ✔ + ETF | 同上 | 同上 | 同上 | ¥14888/年 | 快期 | 同上 | 中 |
| Tushare | ✔ | 另购 | ✔ | ✘ | fut_mapping | fut_settle | 2000 积分≈¥200/年 | token | ✔（未实测） | 中 |
| CTP（SimNow/openctp） | ✘ | tick 实时 | ✔ | ✘ | ✘ | dict.openctp ✔ | 免费 | 微信/手机 | 端口部分通 | 低（自录） |
| RQData | ✔ | ✔ | ✔ | ✔ 服务端 | 参数化 + 因子 | ✔ | 询价 | 手机 | 未验证 | 低 |
| JQData | 未验证 | — | — | — | — | — | — | — | ✘ 区域封锁 | — |
| xtquant | ✔ | ✔ | ✔ | 本地算 | rb00 | ✔ | 随券商 | 券商 QMT + Windows | 不适用 | — |
| Databento/Kaiko/Yahoo | ✘ | ✘ | ✘ | ✘ | — | — | — | — | — | — |

## 3. 推荐组合（供 owner 裁决）

- **A. 零成本合规主干（推荐起步）**：交易所每日文件（SHFE/INE/CZCE/CFFEX/GFEX 直连，DCE 经国内节点或 AKShare 回退）→ `bar_1d` + `option_1d`（含交易所 Δ/IV）；openctp 数据中心 → `instrument_spec`；主力映射自算（规则版本化）。成本 ¥0；缺分钟/tick。
- **B. A + TqSdk 免费版**：加实时 tick/分钟录制与 `KQ.m@` 对照校验；需 owner 注册快期账号；受序列上限约束，历史仍靠 A。成本 ¥0。
- **C. A + RQData（或 TqSdk 专业版 ¥14888/年）**：需分钟/tick 回溯与服务端 Greeks 时启用；RQData 主力规则/复权因子最利重放但价格不透明。

## 4. 待裁决清单（owner 回字母）

1. 国内拉取器（解决 DCE 412、CFFEX/GFEX 仅 http、JQData 封锁）：**A** 部署 / **B** 不部署（DCE 走 AKShare 或放弃）。
2. 主力连续合约定义：**A** TqSdk 规则（持仓+成交双最大）/ **B** RQData 规则（1.1 倍持仓）/ **C** 自定并版本化。
3. 期权 Greeks：**A** 只存交易所 Δ/IV / **B** 自算全 Greeks（需定模型与利率源）/ **C** 两者都存。
4. 是否允许 owner 注册快期账号（TqSdk）/ 微信关注 openctp：**A** 允许 / **B** 不允许。
5. 分钟/tick 是否 MVP 必需：**A** 否 / **B** 是（走方案 C，需定预算）。
6. 交易所数据再分发条款：**A** 仅自用落库 / **B** 需法务确认后再分发。

## 5. 信息来源

- TqSdk：<https://www.shinnytech.com/tqsdk-buy/> 、<https://doc.shinnytech.com/tqsdk/latest/usage/mddatas.html> 、<https://doc.shinnytech.com/tqsdk/latest/reference/tqsdk.api.html> 、<https://doc.shinnytech.com/tqsdk/latest/profession.html> 、<https://doc.shinnytech.com/tqsdk/latest/quickstart.html>
- AKShare：<https://akshare.akfamily.xyz/data/futures/futures.html> 、<https://akshare.akfamily.xyz/data/option/option.html>
- Tushare：<https://tushare.pro/document/2?doc_id=138> 、159、189、141、158、313；<https://tushare.pro/document/1?doc_id=290> 、405
- 交易所 URL：见 §1.4 表；SHFE CTP 页 <https://www.shfe.com.cn/services/indexopt/promotion/202108/t20210804_797695.html>
- openctp：<http://www.openctp.cn/Trading.html> 、<http://www.openctp.cn/DataCenter.html> 、<https://github.com/openctp/openctp>
- RQData：<https://www.ricequant.com/doc/rqdata/python/futures-mod> 、<https://www.ricequant.com/doc/rqdata/python/options-mod> 、<https://www.ricequant.com/doc/rqdata/python/manual>
- xtquant：<https://dict.thinktrader.net/nativeApi/start_now.html> ；掘金：<https://www.myquant.cn/docs2/docs/期货.html> ；vn.py：<https://www.vnpy.com/docs/cn/community/info/datafeed.html>
- pytdx：<https://github.com/rainx/pytdx> ；Databento：<https://databento.com/venues> ；Kaiko：<https://www.kaiko.com/>
- PyPI（2026-09-18）：tqsdk 3.10.2；openctp-ctp 6.7.11.0；vnpy_ctp 6.7.11.4；vnpy 4.4.0；akshare 1.18.96；rqdatac 3.7.1；tushare 1.4.29；xtquant 250807.1.2；gm 3.0.186；jqdatasdk 1.9.8；pytdx 1.72

## 6. 未验证项 / 文档矛盾（只报不修）

- **矛盾**：TqSdk 免费版序列上限——api reference 10000 根 vs mddatas 页 8000 根。
- **矛盾**：AKShare 文档 `option_daily_stats_sse` 参数示例与实现（实际参数名 `date`）；`option_cffex_zz1000_daily_sina` 文档示例传月份代码，实现需完整合约码（如 `mo2610C7500`）。
- 未验证：TqSdk 行情落库/商用条款、快期注册手机号要求、行情服务器海外连通、`query_symbol_info` 保证金字段；Tushare 期货日线起始年、分钟价格、再分发；SimNow 注册要求与条款；各交易所法律声明原文、CZCE 2015 前路径、DCE 文件格式与期权 Δ/IV、SZSE 期权报表参数；RQData 现价与许可；JQData 全部；掘金/xtquant 门槛；Wind/Choice 价格；openctp 实盘前置获取方式；所有"国内→X"可达性。

## 7. 探针实测输出摘要（2026-09-18 03:5x UTC，美国节点）

**表 A `akshare_cn_futures.py`（17 项，15 通过）**

| market | check | ok | 耗时 s | 行数 | 起 | 止 | ≥3y | 字段（前 8）/ 备注 |
|---|---|---|---|---|---|---|---|---|
| 商品期货 | `futures_main_sina("RB0", 20210101–)` | ✅ | 1.54 | 1385 | 2021-01-04 | 2026-09-17 | ✅ | 日期,开盘价,最高价,最低价,收盘价,成交量,持仓量,动态结算价 |
| 商品期货 | `futures_zh_daily_sina("RB2601")` 单合约 | ✅ | 1.75 | 242 | 2025-01-16 | 2026-01-15 | ❌（合约寿命） | date,open,high,low,close,volume,hold,settle |
| 商品期货 | `futures_zh_spot("RB0")` 快照 | ✅ | 1.07 | 1 | — | — | — | symbol,time,open,high,low,current_price,bid_price,ask_price,…hold,volume（`time` 列为时刻字符串，探针误解析为 2000-11-30，属解析瑕疵） |
| 股指期货 | `futures_main_sina("IF0", 20210101–)` | ✅ | 1.16 | 1385 | 2021-01-04 | 2026-09-17 | ✅ | 同 RB0 |
| SHFE | `get_futures_daily(market="SHFE")` 2026-09-15 | ✅ | 1.84 | 305 | 2026-09-15 | 2026-09-15 | —（单日） | symbol,date,open,high,low,close,volume,open_interest,turnover,settle,pre_settle,variety |
| DCE | `get_futures_daily(market="DCE")` | ❌ | 0.91 | | | | | `JSONDecodeError: Expecting value: line 1 column 1 (char 0)`（WAF 412 返回 HTML）→ **本节点不可达** |
| CZCE | `get_futures_daily(market="CZCE")` | ✅ | 2.35 | 238 | 2026-09-15（探针显示 1970-01-01 为解析瑕疵） | | — | 同 SHFE 列 |
| CFFEX | `get_futures_daily(market="CFFEX")` | ✅ | 1.33 | 28 | 2026-09-15 | 2026-09-15 | — | 同上 |
| GFEX | `get_futures_daily(market="GFEX")` | ✅ | 0.48 | 48 | 2026-09-15 | 2026-09-15 | — | 同上 |
| INE | `get_futures_daily(market="INE")` | ✅ | 1.40 | 67 | 2026-09-15 | 2026-09-15 | — | 同上 |
| 股指期权 | `option_cffex_zz1000_daily_sina("mo2610C7500")` | ✅ | 2.23 | 44 | 2026-07-20 | 2026-09-17 | ❌（合约寿命） | date,open,high,low,close,volume |
| ETF 期权 | `option_daily_stats_sse(date=最近交易日)` | ✅ | 0.64 | 5 | — | — | — | 合约标的代码,合约标的名称,合约数量,总成交额,总成交量,认购成交量,认沽成交量,认沽/认购,未平仓合约总数,… |
| ETF 期权 | `option_sse_daily_sina("10010974")`（50ETF 认购） | ✅ | 1.53 | 155 | 2026-01-29 | 2026-09-17 | ❌（合约寿命） | 日期,开盘,最高,最低,收盘,成交量 |
| 商品期权 | `option_commodity_contract_table_sina("黄金期权","au2612")` T 型报价 | ✅ | 1.46 | 88 | — | — | — | 看涨合约-买量/买价/最新价/卖价/卖量/持仓量/涨跌,行权价,看跌合约-… |
| 商品期权 | `option_commodity_hist_sina("au2612C1000")` | ✅ | 2.14 | 93 | 2026-03-27 | 2026-09-17 | ❌（合约寿命） | date,open,high,low,close,volume |
| 商品期权 | `option_hist_dce("豆粕期权", 最近交易日)` | ❌ | 0.91 | | | | | `JSONDecodeError`（DCE 412）→ 本节点不可达 |
| 商品期权 | `option_hist_shfe("黄金期权", 最近交易日)` | ✅ | 10.89 | 776 | — | — | — | 合约代码,开盘价,最高价,最低价,收盘价,前结算价,结算价,涨跌1,涨跌2,成交量,持仓量,持仓量变化,成交额,**德尔塔** |

**表 B `exchange_sites_cn.py`（期货交易所直连 6 项，3 通过）**

| 站点 | URL | ok | 耗时 s | 备注 |
|---|---|---|---|---|
| SHFE | `www.shfe.com.cn/data/tradedata/future/dailydata/kx20260916.dat` | ✅ | 1.57 | HTTP 200 |
| INE | `www.ine.cn/data/dailydata/kx/kx20260916.dat` | ❌ | 0.83 | HTTP 404（旧路径；新路径 `/data/tradedata/future/dailydata/` 经 AKShare 可拉） |
| DCE | `www.dce.com.cn/publicweb/quotesdata/dayQuotesCh.html` | ❌ | 0.95 | **HTTP 412**（JS-cookie WAF）|
| CZCE | `www.czce.com.cn/cn/DFSStaticFiles/Future/2026/20260916/FutureDataDaily.htm` | ❌ | 2.32 | **HTTP 412**（AKShare 路径可拉，见表 A） |
| GFEX | `www.gfex.com.cn/gfex/rihq/hqsj_tjsj.shtml` | ✅ | 0.74 | HTTP 200 |
| CFFEX | `www.cffex.com.cn/sj/historysj/202609/zip/202609.zip` | ✅ | 2.37 | HTTP 200（月度 zip） |

**复现**：`cd docs/research/probes && python run_all.py akshare_cn_futures exchange_sites_cn`（依赖 akshare ≥1.18、pandas、requests）。注意 `get_futures_daily` 与 `option_hist_*` 取"今日-2 起最近工作日"，节假日需手动调 `_last_trading_day()`。
