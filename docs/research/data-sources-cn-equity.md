# A 股数据源全景：股票 / ETF / 可转债

- 调研日期：2026-09-18；探测节点：美国（Florida，出口 IP 134.56.13.103），**未使用代理**
- 探针脚本：`docs/research/probes/{akshare,baostock,tencent,sina,eastmoney}_cn_equity.py`、`yfinance_cn_hk_equity.py`、`stooq_cn_hk_us.py`、`exchange_sites_cn.py`；汇总输出 `docs/research/probes/results.md`（`python run_all.py` 自动生成，可 fresh 重跑对比）
- 维度编号（全文统一）：① 覆盖/字段 ② 频率 ③ 历史深度 ④ 价格 ⑤ 限流 ⑥ 认证 ⑦ 许可（落库/商用/再分发）⑧ 访问方式 ⑨ 维护状态 ⑩ ADR-0002 适配（只 insert 不 update / 可解释 / 可重放 / source 字段）⑪ 网络可达性（美国→国内 / 国内→国外）
- 凡官方页面未能确认的事实标 **未验证**；"本节点不可达"仅指本美国节点，不代表国内不可用
- 总索引与跨品种推荐见 [data-sources-index.md](data-sources-index.md)

## 0. 结论速览

| 结论 | 依据 |
|---|---|
| 美国节点上，**新浪 / 腾讯 / BaoStock / Yahoo / 交易所官网**可直连拉 A 股日线；**东方财富 push2/push2his 全部不通**（连接被远端断开 / 502 / 20s 超时） | §7 探针 12/12 东财检查失败；新浪 7/7、腾讯 7/7、BaoStock 4/4 通过 |
| AKShare 中依赖东财的函数（`stock_zh_a_hist`、`fund_etf_hist_em`、`stock_zh_a_spot_em`）在本节点失败，改用其新浪/腾讯后端（`stock_zh_a_daily`、`stock_zh_a_hist_tx`、`fund_etf_hist_sina`、`bond_zh_hs_cov_daily`）全部通过 | §7 |
| 唯一提供**独立复权因子接口且免费**的源是 BaoStock（`query_adjust_factor`）和 AKShare 新浪后端（`qfq-factor/hfq-factor`）；Tushare Pro `adj_factor` 需 token（未实测） | §1.1/§1.3/§1.2 |
| 免费源的许可全部是"个人/学术/非商业"或无授权爬虫；**没有任何免费源明文允许商用落库+再分发** | §1 各 ⑦ |
| 可转债日线：新浪/腾讯/AKShare 可拉（113050 南银转债 978 行 2021-07-01→2025-07-14，已到期退市所以止于 2025-07）；Yahoo 不覆盖可转债 | §7 |

## 1. 免费 / 社区源（均已实测或明确标注原因）

### 1.1 AKShare（akshare 1.18.96，2026-09-17 发版）

- ① 股票：`stock_zh_a_hist`（东财，`adjust=""/qfq/hfq`）、`stock_zh_a_daily`（新浪，返回 `qfq-factor`/`hfq-factor` 单独因子）、`stock_zh_a_hist_tx`（腾讯）、`stock_zh_a_spot_em`（全市场快照）、`stock_tfp_em`（停复牌）、`stock_fhps_em`（分红送配，自 1990-12-31）。ETF：`fund_etf_hist_em`（qfq/hfq）、`fund_etf_spot_em`、`fund_etf_hist_sina`。可转债：`bond_zh_hs_cov_daily`（新浪日线）、`bond_zh_hs_cov_spot`（实时全表）、`bond_zh_cov`/`bond_cov_comparison`/`bond_zh_cov_value_analysis`（东财）、`bond_cb_jsl`（集思录，需 cookie 否则仅 30 条）、`bond_cb_redeem_jsl`（强赎）、`bond_cb_adj_logs_jsl`（转股价调整）。来源：<https://akshare.akfamily.xyz/data/stock/stock.html> 、<https://akshare.akfamily.xyz/data/bond/bond.html> 、<https://akshare.akfamily.xyz/data/fund/fund_public.html>
- ② 日/周/月；分钟 `stock_zh_a_hist_min_em`（文档："1 分钟数据只返回近 5 个交易日数据且不复权"）；快照轮询；无 WebSocket。
- ③ 取决于上游：东财/新浪/腾讯日线可到上市首日（实测 510300 新浪 3480 行自 2012-05-28）。
- ④ 免费。
- ⑤ 库本身无限流，受上游反爬：东财 IP 黑名单（[issue #6100](https://github.com/akfamily/akshare/issues/6100)，2025-04）、东财滑动验证导致 `stock_zh_a_spot_em` 报错（[issue #6239](https://github.com/akfamily/akshare/issues/6239)，2025-06）。
- ⑥ 无需注册（集思录接口除外）。
- ⑦ 库为 MIT；但文档声明"数据接口和相关数据仅供学术研究使用……商业风险自负"，数据版权归上游站点。**落库：技术上可，法律上继承上游（新浪/东财/腾讯均无明文授权）；商用/再分发：不推荐**。来源：<https://akshare.akfamily.xyz/introduction.html>
- ⑧ Python SDK（网页接口封装）；另有 AKTools 提供 HTTP 封装。
- ⑨ 极活跃（几乎每日发版）；接口频繁更名（changelog 内有"接口更名一览表"），是主要断供风险。来源：<https://github.com/akfamily/akshare/blob/main/docs/changelog.md>
- ⑩ 日线有稳定 `date`/`日期` 键，可直接作幂等主键（symbol, date, source）；新浪因子可独立存储。**风险**：东财 qfq/hfq 由上游全量重算并回改历史，只应落 `adjust=""` 原始价 + 因子表；`source` 字段需细分到后端（`akshare/sina`、`akshare/em`），否则同一函数换后端时不可解释。
- ⑪ 美国→国内：新浪/腾讯后端通；东财后端不通（见 §1.5）。国内→AKShare 各后端均为国内站，可达（**未验证**，无国内节点）。
- 实测：见 §7 表 A（`akshare_cn_equity.py` 9 项检查，6 通过；3 项失败均为东财后端）。

### 1.2 Tushare Pro（tushare 1.4.29，2026-03-25）— 需 owner 提供 token，未实测

- ① 股票 `daily`（未复权，停牌日不提供）、`adj_factor`（独立接口）、`dividend`（自 2000-01-01）、`suspend_d`（自 2000-01-03）、`stock_basic`（含 list_date/delist_date）、`index_weight`（月度）、`index_basic`；ETF `fund_daily`（文档："历史超过 10 年"）；可转债 `cb_basic`、`cb_daily`（含 bond_value/cb_value/溢价率）、`cb_issue`；转股价变动为单独付费权限。来源：<https://tushare.pro/document/2?doc_id=27>（daily）、[doc_id=28](https://tushare.pro/document/2?doc_id=28)（adj_factor）、[doc_id=103](https://tushare.pro/document/2?doc_id=103)（dividend）、[doc_id=214](https://tushare.pro/document/2?doc_id=214)（suspend_d）、[doc_id=127](https://tushare.pro/document/2?doc_id=127)（fund_daily）、[doc_id=185/186/187](https://tushare.pro/document/2?doc_id=185)（cb_*）
- ② 日线；历史分钟（1/5/15/30/60，自 2009）与实时分钟为独立付费权限。
- ③ 日线：`daily` 单次 6000 条（"相当于提取一个股票 23 年历史"）；`cb_daily` 起始年 **未验证**（示例起 2019-07-19）。
- ④ 积分制（个人价，来源：<https://tushare.pro/document/1?doc_id=290> 、<https://tushare.pro/document/1?doc_id=13>）：120 分=免费（仅未复权日线等基础接口）；2000 分=200 元/年；5000 分=500 元/年；10000 分=1000 元/年；15000 分=1500 元/年。独立权限：历史分钟 2000 元/年、实时分钟 1000 元/月、实时日线 200 元/月、可转债转股价变动 500 元/年。**机构价为个人价 10 倍**。
- ⑤ 120 分：50 次/分、8000 次/日；2000 分：200 次/分、10 万次/接口/日；5000 分及以上：500 次/分、常规接口无日上限。单次条数：`daily` 6000、`cb_daily` 2000、`fund_daily` 5000。
- ⑥ 注册 + token。**注册门槛**：注册页为 JS 渲染，是否强制国内手机号 **未验证**；积分达标需付费或社区贡献。按本 issue 约束未注册。
- ⑦ 服务协议第 3 条："仅可为非商业目的使用，并仅可用作个人查看使用"；禁止账号转让/共享；未明文禁止落库；再分发未明文。→ **个人研究可落库；若 quantime 定性为商用，需机构授权（×10）或与 Tushare 确认**。来源：<https://tushare.pro/document/1?doc_id=405>
- ⑧ REST（HTTP POST JSON）+ Python SDK。
- ⑨ Pro 接口持续维护；老版免费接口（`ts.get_k_data`/`get_h_data`）已停维护并导向 Pro（GitHub waditu/tushare 最后 push 2024-03-13，765 open issues）。来源：<https://github.com/waditu/tushare>
- ⑩ 最贴合 ADR-0002：`trade_date` 稳定主键；`adj_factor`、`suspend_d`、`dividend` 独立表；`daily` 收盘后 15–16 点入库、`adj_factor` 盘前 9:15–20 入库（官方入库时间可作 `as_of` 说明）。是否回改历史 **未验证**（文档未声明）。
- ⑪ 美国→tushare.pro：本次 HTTPS 可达（仅文档页，未调 API）。国内→无障碍（国内服务）。

### 1.3 BaoStock（baostock 0.9.3，2026-07-10）

- ① 沪深 A 股 + 指数 K 线 `query_history_k_data_plus`（`adjustflag` 1 后复权/2 前复权/3 不复权，含 `turn/pctChg/peTTM/pbMRQ/isST`）、`query_adjust_factor`（前/后复权因子）、`query_dividend_data`、`query_trade_dates`（1990 起）、hs300/zz500/sz50 成分、`query_stock_basic`（`type` 1 股票/2 指数/3 其它/4 可转债/5 ETF）。**ETF K 线实测可拉**（sh.510300 173 行，2026-01-05→），但**仅 2026 年起**（见 §7）；可转债 K 线 **未验证**。来源：官网 API 文档（旧站，最后编辑 2024-06-03）<http://baostock.com/baostock/index.php/Python_API文档>
- ② 日/周/月 + 5/15/30/60 分钟（指数无分钟）；**无实时**（`latest_quote` 实测只能拿到已收盘日线）。
- ③ 股票日线 1990-12-19 起，分钟 1999-07-26 起，指数 2006 起；日 K 当日 17:30 入库，分钟次日 11:00。实测 sh.600519 自 2022-01-04 请求 1142 行。
- ④ 免费。**注意**：2026-09-16 上线的新版官网（SPA）出现注册/登录/手机号校验/实名认证/付费文章/积分模块，商业化信号明显；新条款 **未验证**。来源：<https://www.baostock.com/>
- ⑤ 新站文案："每日 API 请求不能超过 5 万次，超过后进入黑名单控制。并且不能并发连接访问"；首次封 6 小时，"限制时长 = 本年累计限制次数 × 6 小时"。
- ⑥ 旧文档"无需注册"（`bs.login()` 匿名，本次实测匿名登录成功）；新站是否改为需账号 **未验证**。
- ⑦ 旧站"免费、开源"；无明确商用/再分发条款 → **未验证**。
- ⑧ 自有 TCP 协议 Python SDK（非 REST；需 `login/logout`，单连接串行）。
- ⑨ SDK 2026-07 更新；官网 2026-09 大改版，API 文档暂无法从新站抓取。
- ⑩ `date` 稳定键；因子独立接口，天然支持"原始价 + 因子表"两表落库；分钟 T+1 不影响日线研究。适配好。
- ⑪ 美国→baostock.com TCP 连接正常（实测 4 项全过，最长 4.5s）。
- 实测：§7 表 B。

### 1.4 efinance（0.5.9，2026-07-17）— 未单独探针（后端与 §1.5 东财相同）

- ① 东财封装：股票/ETF K 线（`klt` 1/5/15/30/60/101/102/103，`fqt` 0/1/2）、实时快照、可转债 `ef.bond.get_quote_history/get_all_base_info/get_realtime_quotes`。② 分钟到月。③ 同东财。④ 免费（MIT）。⑤ 同东财反爬。⑥ 无。⑦ README："本项目仅供学习交流使用，不得用于商业用途"。⑧ Python。⑨ 153 open issues，更新频率低于 AKShare。⑩ 同东财。⑪ 后端 push2his 在本节点不通（§1.5 已实测），故本节点 efinance 不可用。来源：<https://github.com/Micro-sheep/efinance>

### 1.5 东方财富 push2 / push2his / datacenter（无官方 API 文档）

- ① 全品种统一 `secid`（`1.600519`、`1.510300`、`1.113050`、港股 `116.00700`）；`push2his…/api/qt/stock/kline/get` 提供 `fqt=0/1/2`；`datacenter-web…RPT_BOND_CB_LIST` 可转债列表（上一轮探测 count=1053）。② 分钟/日/周/月；快照轮询。③ 上市以来。④ 免费、无授权。⑤ 无公开规则；IP 黑名单 + 2025-06 起滑动验证。⑥ 无。⑦ **无任何授权**，纯爬虫；东财网站服务条款禁止未经许可抓取（**条款原文未验证**）→ 不应作为商用落库主源。⑧ REST JSON。⑨ 参数随时变（`pz` 分页、`f51…` 字段编号）。⑩ 日线 `f51` 日期键稳定；qfq/hfq 由东财全量重算并回改历史，只应存 `fqt=0`。
- ⑪ **本节点不可达（实测 12/12 失败）**：`push2his.eastmoney.com` → `ConnectionError: ('Connection aborted.', RemoteDisconnected('Remote end closed connection without response'))`；`push2delay.eastmoney.com` 返回 0 行；`push2.eastmoney.com` → `HTTPError: 502 Server Error: Bad Gateway` 或 `ReadTimeout (read timeout=20)`。`datacenter-web.eastmoney.com` 与基金 `fund.eastmoney.com/pingzhongdata` 正常（见 [data-sources-cn-funds.md](data-sources-cn-funds.md)）。国内访问：正常（AKShare/efinance 大量国内用户，**未在本节点验证**）。
- 实测：§7 表 E。

### 1.6 新浪财经 hq.sinajs.cn / money.finance.sina.com.cn

- ① 实时快照 `hq.sinajs.cn/list=sh600519,sh113050,rt_hk00700`（GBK；股票/ETF/可转债/港股）；日线 `money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData?symbol=sh600519&scale=240&datalen=1023`；复权因子 `finance.sina.com.cn/realstock/company/sh600519/qfq.js|hfq.js`（AKShare `stock_zh_a_daily` 内部使用）。② 分钟（scale=5/15/30/60）/日；快照轮询。③ 日线**单次上限 `datalen=1023`（实测），无日期区间参数**，因此一次只能拿最近 ~4.2 年；更早历史需其他源。④ 免费。⑤ 无公开规则；2022-01-21 起 `hq.sinajs.cn` 要求 `Referer: https://finance.sina.com.cn`（无 Referer → 403，本次实测复现）。来源：<https://github.com/LeekHub/leek-fund/issues/359> ⑥ 无。⑦ 无授权（新浪版权声明禁止未经许可转载，**原文未验证**）；商用/再分发不可。⑧ REST（JSONP/JS）。⑨ 无版本概念，随时可变；2022 年 Referer 事件即一次断供。⑩ `day` 键稳定；有独立因子文件；quote 无历史。⑪ 美国→新浪：7/7 通过（最长 1.6s）。国内：正常。
- 实测：§7 表 C。

### 1.7 腾讯财经 qt.gtimg.cn / web.ifzq.gtimg.cn

- ① 快照 `qt.gtimg.cn/q=sh600519`；日线 `web.ifzq.gtimg.cn/appstock/app/fqkline/get?param=sh600519,day,2024-01-01,2026-09-18,640,qfq`（`qfq/hfq/none`；港股 `hk00700`、可转债 `sh113050` 均可）。② 日/周/月 + 分钟 `ifzq…/appstock/app/kline/mkline`。③ 实测 600000 qfq 可回溯至 2000-01-04；**单次 ≤640 根，需按日期区间分页**（探针以 2 年/页拉到 1385 行）。④ 免费。⑤ 无公开规则，无 Referer 校验（实测）。⑥ 无。⑦ 无授权；同新浪。⑧ REST JSON。⑨ 相对稳定，但无 SLA。⑩ 日期键稳定；**注意实测 600000 qfq 早期出现负价**，说明前复权基准漂移 → 只应存 `none` + 自算因子；quote 字段为位置数组，需版本化解析器（可解释性风险）。⑪ 美国→腾讯：7/7 通过（≤2.2s）。国内：正常。
- 实测：§7 表 D。

### 1.8 通达信 / pytdx / mootdx — 未实测

- pytdx：GitHub 2020-04-15 归档，作者称"代码已过时，请勿商用"，PyPI 1.72（2019-08-26）。mootdx：MIT，PyPI 0.11.7（2024-05-04），"仅供学习交流，不得商用"。协议为逆向、服务器列表非官方。① 覆盖沪深全品种 **未验证**；⑤ 单次 800 根（社区说法）**未验证**；⑪ 行情服务器为国内 IP，海外可达性 **未验证**。**未实测原因**：协议非公开接口、依赖第三方服务器列表，不满足"免费公开接口"约束。来源：<https://github.com/rainx/pytdx> 、<https://github.com/mootdx/mootdx>

### 1.9 上交所 / 深交所 / 北交所官网

- ① 名单、停复牌、公告、成交概况、基金/债券列表；上交所 `yunhq.sse.com.cn:32042/v1/sh1/dayk/600519` 提供近 N 日 K 线 JSONP（实测 200）；非行情主源。② 日。③ 名单类为当前快照。④ 免费。⑤ 无公开规则。⑥ 无。⑦ **沪深法律声明一致**："任何机构或者个人可基于非商业目的浏览、下载本网站的内容"；"未经…书面许可，任何机构或者个人不得以向他人出售牟利为目的，使用本网站的任何内容，此种使用包括但不限于拷贝、下载、存贮…"。→ 非商业落库允许，商用/再分发禁止。来源：<https://www.sse.com.cn/home/legal/> 、<http://www.szse.cn/application/laws/> ⑧ JSON/Excel 端点，无官方 API 文档。⑨ 端点路径不定期变（本次 szse `getHistory` 404，上一轮 `CATALOGID=1105` 基金列表 200）。⑩ 适合做名单/停复牌/成分的"官方校验表"。⑪ 美国→SSE 200（3.3s）、BSE 200（1.2s）、SZSE 探测路径 404（站点可达，接口路径变了）。
- 实测：§7 表 F。

### 1.10 中证指数 / 国证指数（成分股）

- 中证 `oss-ch.csindex.com.cn/static/html/csindex/public/uploads/file/autofile/cons/000300cons.xls` 与 `closeweight/000300closeweight.xls` 公开下载（上一轮 200）；仅当前成分，历史成分需每日快照归档（天然 append-only）。国证 `www.cnindex.com.cn/sample-detail/detail?indexcode=399300&dateStr=…` 返回含权重 JSON（200）。⑦ 中证法律声明 **未验证**。⑪ 美国节点均可达。

### 1.11 Yahoo Finance / yfinance（1.7.0）

- ① `600519.SS`/`510300.SS`/`000001.SZ`，含 `Adj Close`、`Dividends`、`Stock Splits`；**可转债 `113050.SS` 不覆盖**（实测 0 行，quote `KeyError: 'currentTradingPeriod'`）。② 日/周/月；分钟近 7–60 天。③ `600000.SS` 自 1999-11-10（上一轮 chart API 实测）；**`000001.SZ` range=max 仅 429 根，严重缺行**。④ 免费。⑤ 无官方数值；yfinance 社区报告 IP 级 429。⑥ 无。⑦ yfinance README："the Yahoo! finance API is intended for personal use only"；Yahoo 服务条款禁止再分发 → 不可商用/再分发。来源：<https://github.com/ranaroussi/yfinance> ⑧ Python（非官方 chart API 封装）。⑨ 活跃（1.7.0 2026-08-26），但历史上多次因 Yahoo 端变动断供（2017 关闭官方 API、2024–2025 crumb/cookie 变更）。⑩ `Adj Close` 随后续分红回改 → 存 `auto_adjust=False` 原始价 + Dividends/Splits 事件表。⑪ 美国：4/4 A 股检查通过（<0.3s）；国内→Yahoo 被阻断（**未验证**，普遍已知）。
- 实测：§7 表 G。

### 1.12 Stooq — 本节点不可达

- `https://stooq.com/q/d/l/?s=600519.cn&i=d` 等 5 项全部返回 HTML JS 验证页（`<!DOCTYPE html>…<meta name="robots" content="noindex,nofollow">`）而非 CSV → **本节点被 JS PoW 挑战拦截**。已知日配额 "Exceeded the daily hits limit"（数值 **未验证**）；`.cn` A 股覆盖 **未验证**。⑦ 条款 **未验证**。实测：§7 表 H。

### 1.13 Investing.com — 无官方 API，未实测

- T&C 页面为 JS 渲染，条款原文本次未抓到（爬虫禁止条款 **未验证**）；第三方库 investpy 已于 2022 年因站点加 Cloudflare 而停摆。不建议纳入。

### 1.14 集思录（可转债条款/指标）

- ① 转股溢价率/双低/YTM/剩余规模/强赎状态；`www.jisilu.cn/webapi/cb/list/` 本节点 200（上一轮）。⑥ 未登录仅 30 条；会员价 **未验证**。⑦ 无公开 API 授权。⑩ 仅当前快照、无历史 → 需自建每日快照表（append-only 天然契合）。⑨ 站点持续调整字段/权限。

## 2. 付费 / 需账户源（未实测，均需 owner 决策后再接入）

### 2.1 聚宽 JQData（jqdatasdk 1.9.8）
- ⑪ **官网对非中国大陆 IP 直接拒绝**（本次实测提示："当前网站暂不支持来自非中国大陆地区 IP 地址的访问"）→ 美国节点不可用。① 社区/README：股票/基金/指数/期货/期权/可转债，年–分钟–tick。④ 试用"每日 100 万条"、专业版"每日 2 亿条"（**未验证**）；价格需联系商务（**未验证**）。⑥ 注册需国内手机号（**未验证**）。⑦ **未验证**。⑧ Python SDK。来源：<https://www.joinquant.com/default/index/sdk> 、<https://github.com/joinquant/jqdatasdk>

### 2.2 米筐 RQData（rqdatac 3.7.1，2026-09-14）
- ① A 股 `get_price`（1d/1m/tick，`adjust_type` pre/post/none/pre_volume）、`get_ex_factor`、`is_suspended`、`get_dividend`、`get_split`、`index_components`（含历史）、`get_trading_dates`；ETF/LOF；可转债模块 `convertible.all_instruments/get_conversion_price/get_call_info/get_put_info/get_cash_flow/get_indicators/get_close_price`。③ A 股自 2005-01-04。⑤ 按日流量配额（试用 1 GB/日，`rqdatac.user.get_quota()` 可查）。⑥ 账号 + 许可证。④ 价格 **未验证**（社区 3000/10000/15000 元/年、14 天试用）。⑦ **未验证**。⑧ Python SDK + HTTP API。⑩ 因子/停牌/分红/成分历史全独立，适配最好。⑪ 文档站海外可达；数据服务是否限地区 **未验证**。来源：<https://www.ricequant.com/doc/rqdata/python/stock-mod.html> 、<https://www.ricequant.com/doc/rqdata/python/convertible-mod.html>

### 2.3 Wind / 东方财富 Choice
- Wind WindPy 需终端，量化接口价格 **未验证**；Choice 量化接口 `quantapi.eastmoney.com`（Python/MATLAB/R/C++/Java，"申请试用"），价格 **未验证**（社区 ≥3 万元/年）。⑦ 机构合同，落库通常允许、再分发禁止（**未验证**）。⑧ 本地 DLL/SDK，Linux 支持有限。⑪ 需国内终端。来源：<https://quantapi.eastmoney.com/>

### 2.4 掘金量化 myquant（gm 3.0.186）
- ① 股票/基金/可转债/指数/期货；`history`、`get_dividend`、`get_history_constituents`；复权 ADJUST_PREV/POST。③ 日频上市以来、分钟 2017-01-01、tick 2022-08-10（仅近 3 个月）。⑤ 分级限流（如财务 1000 次/5min、2 万次/24h）；1 分钟 bar 单次 33000 根。⑧ Python SDK 需连接 **Windows 终端**。④ 免费版实时订阅 50 标的；付费档 **未验证**。⑪ 需国内 Windows 环境。来源：<https://www.myquant.cn/docs2/faq/数据问题.html>

### 2.5 迅投 QMT / xtquant（250807.1.2）
- ① `xtdata.get_market_data_ex`（tick/1m/5m/1d，`dividend_type` none/front/back/front_ratio/back_ratio）、`download_history_data`、`get_divid_factors`、`get_stock_list_in_sector("沪深A股"/"沪深ETF"/"沪深转债")`、`subscribe_quote`。⑥ 需在合作券商开户并开通 QMT/miniQMT（资金门槛因券商而异，**未验证**）。⑧ Python 连接本机 MiniQMT 客户端（Windows）。④ 券商版数据免费、迅投版付费（**未验证**）。⑩ 因子独立、增量下载，适配好。⑪ 客户端必须在国内券商网络。来源：<https://dict.thinktrader.net/nativeApi/xtdata.html>

### 2.6 富途 Futu OpenAPI（futu-api 10.11.7108）
- ① A 股"证券类产品（含股票、ETFs）"，指数/板块不支持；可转债 **未验证**。⑥⑦ "境内认证客户：免费获取 LV1 行情；**国际客户：暂不支持**"。⑤ 快照 60 次/30s；历史 K 线额度按资产 100/300/1000/2000 只。⑧ 需运行 FutuOpenD 网关。⑩ 无独立因子接口（**未验证**）。来源：<https://openapi.futunn.com/futu-api-doc/intro/authority.html>

### 2.7 长桥 LongPort OpenAPI（longport 4.3.7）
- ① 美/港/A 股；"基础行情：美/A 股实时报价……开通 OpenAPI 后自动获得"。③ A 股日/周/月 1999-11-01 至今，分钟 2022-08-25 至今；单次 ≤1000 根，支持 `adjust_type`。⑤ 历史 K 线 60 次/30s；每月标的数按资产分级（数值页面未渲染，**未验证**）。⑥ 需长桥证券账户。⑧ REST + WS + SDK。⑩ 无独立因子（**未验证**）；A 股 ETF/可转债覆盖 **未验证**。来源：<https://open.longportapp.com/zh-CN/docs/quote/pull/history-candlestick>

### 2.8 老虎 Tiger OpenAPI（tigeropen 3.8.0）
- ① `get_bars` US/HK/CN，A 股每次 30 只、1200 条；"分钟 K 线近 10 年，日 K 全历史"。⑥⑦ "API 行情权限独立于 APP，需要单独购买"；A 股定价 **未验证**。来源：<https://quant.itigerup.com/openapi/zh/python/operation/quotation/stock.html>

## 3. 汇总对比表

| 源 | 股/ETF/转债日线 | 独立复权因子 | 分红/停复牌/成分 | 价格 | 许可（落库/商用/再分发） | 美国节点 | 稳定性 |
|---|---|---|---|---|---|---|---|
| Tushare Pro | ✔/✔(5000 分)/✔ | ✔ | ✔/✔/✔ | 200–1500 元/年，机构 ×10 | 个人非商业/需机构授权/否 | ✔（未实测） | 高 |
| BaoStock | ✔/✔(2026 起)/未验证 | ✔ | ✔/–/hs300 等 | 免费（改版中） | 未明/未明/未明 | ✔ 实测 | 中（5 万次/日、禁并发） |
| AKShare | ✔/✔/✔ | 新浪因子 | ✔/✔/部分 | 免费 | 学术/自负/否 | 部分（东财后端不通） | 低–中 |
| efinance | ✔/✔/✔ | ✘ | ✘ | 免费 | 学习交流/否/否 | ✘（东财） | 低 |
| 东财直连 | ✔ | ✘（qfq 回改） | 转债列表 ✔ | 免费 | 无授权 | ✘ 实测 | 低 |
| 新浪直连 | ✔（≤1023 根/次） | ✔（qfq.js） | ✘ | 免费 | 无授权 | ✔ 实测（需 Referer） | 低–中 |
| 腾讯直连 | ✔（≤640 根/次） | ✘ | ✘ | 免费 | 无授权 | ✔ 实测 | 低–中 |
| RQData | ✔ | ✔ | ✔（含历史成分） | 未验证 | 未验证 | 文档 ✔ | 高 |
| JQData | ✔ | 未验证 | 未验证 | 未验证 | 未验证 | **✘ 屏蔽海外 IP** | – |
| 掘金 | ✔ | ✔ | ✔ | 免费版有限 | 未验证 | ✘（Windows 终端） | 高 |
| QMT/xtquant | ✔ | ✔ | 部分 | 券商版免费 | 券商合同 | ✘ | 高 |
| Futu | 股/ETF | ✘ | ✘ | 境内客户免费 LV1 | 券商协议 | 国际客户不支持 A 股 | 高 |
| LongPort | 股（ETF 未验证） | ✘ | ✘ | 基础免费 | 券商协议 | ✔ | 高 |
| Tiger | 股 | ✘ | ✘ | 行情另购 | 券商协议 | ✔ | 高 |
| Yahoo/yfinance | 股/ETF，转债 ✘ | Adj Close | Dividends/Splits | 免费 | 个人/否/否 | ✔ 实测 | 缺行（000001.SZ） |
| Stooq | 未验证 | ✘ | ✘ | 免费 | 未验证 | ✘ JS 验证 | – |
| 交易所/指数公司 | 名单/成分 | – | 停复牌/成分 ✔ | 免费 | 非商业可下载/否/否 | ✔ 实测 | 高 |

## 4. 推荐组合（供 owner 裁决，非结论）

- **方案 A：Tushare Pro（5000 积分档，500 元/年）主源 + BaoStock 备源 + 交易所/指数公司官方文件校验。** 优点：`trade_date`/`adj_factor`/`suspend_d`/`dividend`/`cb_daily` 全部独立、字段稳定、海外可达，最贴合 append-only（存未复权价 + 因子表，永不回改）。缺点：ETF 日线需 5000 分；协议为"个人非商业"，若 quantime 定性为商用需按机构价（×10）或另行确认；需 owner 注册并注入 token（1Password quant-dev）。
- **方案 B：全免费栈：BaoStock 主源（股票/指数日线 + 因子）+ AKShare 新浪/腾讯后端补 ETF/可转债 + 集思录/中证每日快照。** 零成本、本节点全部实测可用；缺点：BaoStock 正在商业化改版且禁并发/5 万次/日、ETF 历史仅 2026 起、新浪单次 1023 根、无任何商用授权、可重放性依赖自建快照。
- **方案 C：RQData（或 JQData）付费主源 + Tushare 交叉验证。** 数据最完整（含转债条款、历史成分、tick），但价格未验证、JQData 屏蔽海外 IP、RQData 有日流量配额；适合后续升级而非首期。
- 券商 API（Futu/LongPort/Tiger/QMT）建议只作实时快照或交易侧，不作历史主源（无因子、按资产限额、A 股历史分钟极短、Futu 国际客户不支持 A 股）。

## 5. 待裁决清单（owner 回字母）

1. 数据用途定性：**A** 个人研究（Tushare 个人档可用）/ **B** 商用（需机构授权或付费源合同）。
2. 是否部署国内采集节点：**A** 是（解锁东财/聚宽/掘金/QMT）/ **B** 否（只用本节点可达源）。
3. 年预算：**A** 0 / **B** ≤1000 元 / **C** 万元级（RQData/Choice）。
4. 分钟级需求：**A** 不需要（日线研究）/ **B** 需要（Tushare 历史分钟 +2000 元/年，或 BaoStock 免费 T+1）。
5. 可转债条款数据：**A** Tushare 付费权限 / **B** RQData / **C** 每日快照集思录 + 东财 datacenter。
6. 成分股历史：**A** 自建每日快照（中证/国证公开文件）/ **B** Tushare `index_weight` / **C** RQData `index_components`。
7. BaoStock 新站条款落地后是否仍作备源：**A** 是 / **B** 否。

## 6. 未验证项汇总

Tushare 注册是否强制国内手机号、是否回改历史、`cb_daily` 起始年；BaoStock 可转债 K 线覆盖、新站是否需登录、商用条款；JQData 全部定价/额度/许可；RQData 定价、地区限制；Wind/Choice 价格；掘金付费档价格；QMT 券商资金门槛与迅投版收费；pytdx 单次 800 根与 ETF/转债支持；Stooq `.cn` 覆盖与日配额数值；Investing.com 条款原文；集思录会员价；中证指数法律声明；东财/新浪网站服务条款原文；LongPort 月度标的配额数值与 ETF/转债覆盖；Futu/LongPort/Tiger 是否有独立复权因子；Tiger A 股行情定价；国内→Yahoo 的实际可达性；所有"国内→X"可达性（本次无国内节点）。

## 7. 探针实测输出摘要（2026-09-18 03:5x UTC，美国节点）

数据来自 `probes/results.md`（自动生成）。`≥3y` = 单次探针拉到的历史是否跨 3 年；`—` 表示该检查为快照类。

**表 A `akshare_cn_equity.py`（A 股相关 9 项，6 通过）**

| check | ok | 耗时 s | 行数 | 起 | 止 | ≥3y | 错误 / 备注 |
|---|---|---|---|---|---|---|---|
| stock `stock_zh_a_hist`（东财） | ❌ | 1.67 | | | | | `ConnectionError: ('Connection aborted.', RemoteDisconnected('Remote end closed connection without response'))` |
| stock `stock_zh_a_spot_em`（东财） | ❌ | 8.98 | | | | | 同上 |
| etf `fund_etf_hist_em`（东财） | ❌ | 0.73 | | | | | 同上 |
| etf `fund_etf_spot_em` | ✅ | 38.24 | 1621 | — | — | — | 全市场 ETF 快照（东财 push2 部分路径可通，但 38s） |
| stock `stock_zh_a_daily`（新浪）600519 | ✅ | 3.23 | 970 | 2022-09-19 | 2026-09-17 | ✅ | 列含 qfq/hfq 因子 |
| stock `stock_zh_a_hist_tx`（腾讯）600519 | ✅ | 6.95 | 970 | 2022-09-19 | 2026-09-17 | ✅ | |
| etf `fund_etf_hist_sina` 510300 | ✅ | 0.17 | 3480 | 2012-05-28 | 2026-09-17 | ✅ | 全历史一次返回 |
| 可转债 `bond_zh_hs_cov_daily` sh113050 | ✅ | 0.45 | 978 | 2021-07-01 | 2025-07-14 | ✅ | 该券 2025-07 到期退市 |
| 可转债 `bond_zh_hs_cov_spot` | ✅ | 3.26 | 329 | — | — | — | 新浪可转债实时全表 |

**表 B `baostock_cn_equity.py`（4/4）**

| check | ok | 耗时 s | 行数 | 起 | 止 | ≥3y | 备注 |
|---|---|---|---|---|---|---|---|
| stock sh.600519 日线（请求 2022-01-01 起） | ✅ | 4.49 | 1142 | 2022-01-04 | 2026-09-17 | ✅ | 列 date,code,open,high,low,close,preclose,volume,amount,adjustflag,turn,tradestatus,pctChg,isST |
| stock latest | ✅ | 0.24 | 1 | 2026-09-17 | | | `last close=1266.98`；**无实时，只有已收盘日线** |
| etf sh.510300 日线（同样请求 2022-01-01 起） | ✅ | 0.39 | 173 | **2026-01-05** | 2026-09-17 | ❌ | ETF 历史仅 2026 起（上游深度限制） |
| adjust_factor sh.600519 | ✅ | 0.19 | 17 | 2015-07-17 | 2026-06-26 | ✅ | foreAdjustFactor / backAdjustFactor 独立可拉 |

**表 C `sina_cn_equity.py`（A 股 5/5，另 HK 2 项见 [data-sources-hk.md](data-sources-hk.md)）**

| check | ok | 耗时 s | 行数 | 起 | 止 | ≥3y | 备注 |
|---|---|---|---|---|---|---|---|
| stock quote sh600519 | ✅ | 0.87 | 1 | | 2026-09-18 | | `name=贵州茅台 last=1257.200`（带 Referer） |
| stock 日线 sh600519 | ✅ | 1.27 | 1023 | 2022-07-05 | 2026-09-17 | ✅ | **单次上限 datalen=1023，无日期区间参数** |
| etf 日线 sh510300 | ✅ | 0.31 | 1023 | 2022-07-05 | 2026-09-17 | ✅ | 同上 |
| 可转债 quote sh113050 | ✅ | 0.20 | 1 | | 2026-09-18 | | `name=南银转债 last=144.967` |
| 可转债 日线 sh113050 | ✅ | 1.56 | 978 | 2021-07-01 | 2025-07-14 | ✅ | |

**表 D `tencent_cn_equity.py`（A 股 4/4）**

| check | ok | 耗时 s | 行数 | 起 | 止 | ≥3y | 备注 |
|---|---|---|---|---|---|---|---|
| stock 日线 sh600519 qfq | ✅ | 2.14 | 1385 | 2021-01-04 | 2026-09-17 | ✅ | fqkline 分页 2 年/次（单次 ≤640 根） |
| stock quote sh600519 | ✅ | 0.90 | 1 | | 20260918 | | `last=1257.20 time=20260918115936` |
| etf 日线 sh510300 qfq | ✅ | 0.69 | 1385 | 2021-01-04 | 2026-09-17 | ✅ | |
| 可转债 日线 sh113050 none | ✅ | 0.69 | 978 | 2021-07-01 | 2025-07-14 | ✅ | |

**表 E `eastmoney_cn_equity.py`（0/12，本节点不可达）**

| check | ok | 耗时 s | 错误原文（截断） |
|---|---|---|---|
| stock/etf/转债/港股 `push2his…/kline/get`（4 项） | ❌ | 0.6–1.4 | `ConnectionError: ('Connection aborted.', RemoteDisconnected('Remote end closed connection without response'))` |
| 同上，`push2delay.eastmoney.com`（4 项） | ❌ | 0.3–1.1 | HTTP 200 但 0 行 |
| stock quote `push2…/stock/get` | ❌ | 20.24 | `ReadTimeout: HTTPSConnectionPool(host='push2.eastmoney.com', port=443): Read timed out. (read timeout=20)` |
| etf/转债/港股 quote（3 项） | ❌ | 0.4–1.0 | `HTTPError: 502 Server Error: Bad Gateway for url: https://push2.eastmoney.com/api/qt/stock/get?secid=1.510300&…` |

**表 F `exchange_sites_cn.py`（A 股相关 3 项，2 通过）**

| 站点 | ok | 耗时 s | 备注 |
|---|---|---|---|
| SSE `yunhq.sse.com.cn:32042/v1/sh1/dayk/600519?begin=-30&end=-1` | ✅ | 3.31 | HTTP 200（带 Referer） |
| SZSE `www.szse.cn/api/market/ssjjhq/getHistory?…code=000001` | ❌ | 0.82 | HTTP 404（站点可达，接口路径已变） |
| BSE `www.bse.cn/nqhqController/nqhq.do?…xxzqdm=920001` | ✅ | 1.25 | HTTP 200 |

**表 G `yfinance_cn_hk_equity.py`（A 股 6 项，4 通过）**

| check | ok | 耗时 s | 行数 | 起 | 止 | ≥3y | 备注 |
|---|---|---|---|---|---|---|---|
| 600519.SS 日线 5y | ✅ | 0.25 | 1211 | 2021-09-22 | 2026-09-18 | ✅ | |
| 600519.SS quote | ✅ | 0.16 | 1 | 2026-09-18 | | | `fast_info.lastPrice=1257.20` |
| 510300.SS 日线 5y | ✅ | 0.11 | 1209 | 2021-09-22 | 2026-09-18 | ✅ | |
| 510300.SS quote | ✅ | 0.13 | 1 | | | | `lastPrice=4.575` |
| 113050.SS 可转债 日线 | ❌ | 0.51 | 0 | | | | Yahoo 不覆盖可转债 |
| 113050.SS quote | ❌ | 0.17 | | | | | `KeyError: 'currentTradingPeriod'` |

**表 H `stooq_cn_hk_us.py`（0/5，本节点不可达）**

| check | ok | 耗时 s | 错误原文 |
|---|---|---|---|
| 600519.cn / 510300.cn / 0700.hk / 2800.hk / spy.us | ❌ | 0.1–0.4 | `RuntimeError: HTML instead of CSV (JS browser verification): <!DOCTYPE html><html><head><meta charset="utf-8"><meta name="robots" content="noindex,nofollow">…` |

**复现**：`cd docs/research/probes && python run_all.py akshare_cn_equity baostock_cn_equity sina_cn_equity tencent_cn_equity eastmoney_cn_equity yfinance_cn_hk_equity stooq_cn_hk_us exchange_sites_cn`（依赖：akshare、baostock、yfinance、pandas、requests；Python ≥3.11）。

## 8. 信息来源

- PyPI JSON：`https://pypi.org/pypi/{akshare,baostock,efinance,tushare,pytdx,longport,futu-api,tigeropen,xtquant,jqdatasdk,rqdatac,gm,yfinance,mootdx}/json`（2026-09-18 抓取）
- GitHub API：`https://api.github.com/repos/{akfamily/akshare,Micro-sheep/efinance,rainx/pytdx,FutunnOpen/py-futu-api,tigerfintech/openapi-python-sdk,waditu/tushare}`
- Tushare：<https://tushare.pro/document/1?doc_id=290> 、<https://tushare.pro/document/1?doc_id=13> 、<https://tushare.pro/document/1?doc_id=405> 、<https://tushare.pro/document/2?doc_id=27> 及 28/103/214/25/96/94/127/185/186/187
- AKShare：<https://akshare.akfamily.xyz/introduction.html> 、<https://akshare.akfamily.xyz/data/stock/stock.html> 、<https://akshare.akfamily.xyz/data/bond/bond.html> 、<https://github.com/akfamily/akshare/issues/6100> 、<https://github.com/akfamily/akshare/issues/6239>
- BaoStock：<https://www.baostock.com/> （新站）、<http://baostock.com/baostock/index.php/Python_API文档>（旧站）
- efinance：<https://github.com/Micro-sheep/efinance> ；pytdx：<https://github.com/rainx/pytdx> ；mootdx：<https://github.com/mootdx/mootdx>
- 新浪 Referer 变更：<https://github.com/LeekHub/leek-fund/issues/359>
- JQData：<https://www.joinquant.com/default/index/sdk> ；RQData：<https://www.ricequant.com/doc/rqdata/python/stock-mod.html> ；掘金：<https://www.myquant.cn/docs2/faq/数据问题.html> ；迅投：<https://dict.thinktrader.net/nativeApi/xtdata.html> ；Choice：<https://quantapi.eastmoney.com/>
- 交易所：<https://www.sse.com.cn/home/legal/> 、<http://www.szse.cn/application/laws/>
- Futu：<https://openapi.futunn.com/futu-api-doc/intro/authority.html> ；LongPort：<https://open.longportapp.com/zh-CN/docs/quote/pull/history-candlestick> ；Tiger：<https://quant.itigerup.com/openapi/zh/python/operation/quotation/stock.html>
- yfinance：<https://github.com/ranaroussi/yfinance>
- 本文所有"实测"均来自 `docs/research/probes/results.jsonl`（含 `run_at`、`elapsed_s`、原始错误文本）
