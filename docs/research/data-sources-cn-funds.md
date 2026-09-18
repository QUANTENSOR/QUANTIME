# 国内公募基金数据源全景：净值 / 持仓 / 分红 / 费率

- 调研日期：2026-09-18；探测节点：美国（出口 IP 134.56.13.103），**未使用代理，未注册任何账号**
- 探针脚本：`docs/research/probes/eastmoney_cn_funds.py`（7 项检查，5 通过；标的 110011 易方达优质精选混合(QDII)）；汇总 `probes/results.md`
- 维度编号同 [data-sources-cn-equity.md](data-sources-cn-equity.md)；场内 ETF/LOF 行情部分在该文档已覆盖，此处只讨论场外净值类数据
- 总索引见 [data-sources-index.md](data-sources-index.md)

## 0. 结论速览

| 结论 | 依据 |
|---|---|
| **东方财富（天天基金）是几乎所有免费方案的唯一上游**：AKShare `fund_*_em`、efinance、天天基金 JS/JSON 三者同源，只是解析方式不同；冗余要靠 Tushare / 蛋卷 / 巨潮公告，而不是换库 | §1.1–§1.4 |
| **美国节点可达性分裂**：`fund.eastmoney.com/pingzhongdata`、`api.fund.eastmoney.com/f10/lsjz`、`fundf10.eastmoney.com` 可访问（0.5–2.4s，200）；`push2/push2his`（场内 ETF/LOF K 线）不可达。即：**场外净值可从美国拉，场内行情不行** | §7；[data-sources-cn-equity.md §1.5](data-sources-cn-equity.md) |
| `pingzhongdata/<code>.js` 单次返回**全历史**（110011：4402 个净值点自 2008-06-18；上一轮 000001 华夏成长 6009 点自 2001-12-18），并含累计净值、分红、费率（原/现）、经理、持有人结构、资产配置、持仓代码等 20+ 变量 | §7 |
| `fundgz.1234567.com.cn/js/<code>.js` 盘中估值端点本次返回空（`gsz=None`），上一轮返回"页面未找到"HTML → **疑似下线，标未验证** | §7 |
| 唯一提供 `ann_date`/`nav_date` 双日期 + 独立复权因子表（`fund_adj`）的源是 Tushare Pro（需 token，未实测）；免费源的复权净值需自算 | §1.5 |
| AMAC 公开站为**私募**公示，公募层面仅机构名录，不能作数据源 | §1.11 |

## 1. 逐源评估

### 1.1 AKShare `fund_*_em`（1.18.96）— 已实测

- ① `fund_open_fund_info_em(symbol, indicator="单位净值走势"/"累计净值走势"/"分红送配详情"/"拆分详情"…)`、`fund_portfolio_hold_em`（季报重仓股，按年）、`fund_portfolio_bond_hold_em`、`fund_portfolio_industry_allocation_em`、`fund_fee_em`（费率）、`fund_purchase_em`（申赎状态）、`fund_manager_em`、`fund_rating_*`、`fund_fh_em`（全市场分红）、`fund_name_em`（代码表）；场内 `fund_etf_hist_em`/`fund_etf_spot_em`/`fund_lof_hist_em`（东财 push2，本节点不通）。来源：<https://akshare.akfamily.xyz/data/fund/fund_public.html>
- ② 日（东财净值 16:00–23:00 陆续更新）；持仓季报；分红事件驱动。
- ③ 全历史（同上游；实测 110011 4402 行自 2008-06-19）。
- ④ 免费。⑤ 无自身限流；受东财反爬约束（`fund_fh_em` 全表本次 50.5s）。⑥ 无。
- ⑦ MIT；"仅供学术研究"；数据许可继承东财（无明示，见 §1.2 ⑦）。
- ⑧ Python（爬虫封装）。
- ⑨ 近乎日更；东财 F10 页面改版会导致函数失效（本次 `fund_fee_em(indicator="认购费率")` 返回 0 行，属实现/页面不一致）。
- ⑩ 返回 DataFrame 无 source 字段，需自打 `source=eastmoney/akshare`；净值回改由上游决定（见 §1.2 ⑩）。
- ⑪ 美国→东财基金域名 ✅；→push2 ❌。国内：✅（**未验证**）。
- 实测：§7。

### 1.2 东方财富天天基金直连（无官方 API 文档）— 已实测

- ① `fund.eastmoney.com/pingzhongdata/<code>.js`（`Data_netWorthTrend` 单位净值+分红 `unitMoney`、`Data_ACWorthTrend` 累计净值、`fund_Rate`/`fund_sourceRate` 费率、`Data_currentFundManager`、`Data_holderStructure`、`Data_assetAllocation`、`stockCodes`/`zqCodes`）；`api.fund.eastmoney.com/f10/lsjz?fundCode=&pageIndex=&pageSize=`（分页历史净值，字段 `FSRQ/DWJZ/LJJZ/JZZZL/SGZT/SHZT/FHSP/FHFCZ`）；`fundf10.eastmoney.com/FundArchivesDatas.aspx?type=jjcc&code=&year=`（重仓，按年）；`fund.eastmoney.com/js/fundcode_search.js`（全量代码表 ~3 MB）。
- ② 日。③ 全历史（实测 2001 起）。④ 免费。⑤ 未公开；`api.fund.eastmoney.com` 需 `Referer: fundf10.eastmoney.com`（探针已带）。⑥ 无。
- ⑦ **无公开 API 条款**；东财版权页上一轮 404 → **许可未验证**，只能视为"个人研究/灰色"；商用/再分发不可。
- ⑧ HTTP JS/JSON（需正则解析 JS 变量）。⑨ 非官方 API；字段名（拼音缩写）多年稳定。
- ⑩ 净值一般不回改，但**修正净值会静默覆盖（无版本号）**（经验，**未验证**）→ 需每日全量/增量快照 + `fetched_at` + 内容哈希去重才可重放；复权净值需自算（分红再投 + 拆分）；`unitMoney` 分红字段与 `lsjz.FHSP` 文本可作事件表。
- ⑪ 美国→`fund.eastmoney.com`/`api.fund.eastmoney.com` ✅ 200（0.5–1.8s）；`fundgz.1234567.com.cn` 返回空/404 页。
- 实测：§7。

### 1.3 fundgz.1234567.com.cn 盘中估值 — 本次失败，未验证是否下线
- ① `gsz/gszzl/gztime`（估算净值≠官方净值）。② 分钟级。③ 无历史。⑦ 同东财。⑩ 应单独表、按时间戳 insert。⑪ 本次 `gsz=None gztime=None`（返回体无 `jsonpgz`），上一轮三只基金 http/https、带/不带 Referer 均"页面未找到" → **疑似下线，标未验证**。

### 1.4 efinance `ef.fund`（0.5.9）— 未单独探针（同东财上游）
- ① `get_quote_history`（净值）、`get_invest_position`（持仓）、`get_base_info`、`get_realtime_increase_rate`（依赖 fundgz）、行业分布、PDF 报告链接。② 日。③ 全历史。④ 免费 MIT。⑦ "仅供学习交流，不得用于商业用途"。⑨ 153 open issues，发布间隔 4–8 个月。⑩⑪ 同东财。来源：<https://github.com/Micro-sheep/efinance>

### 1.5 Tushare Pro 基金接口 — 需 owner 提供 token，未实测
- ① `fund_basic`（2000 积分）、`fund_nav`（2000；`unit_nav/accum_nav/adj_nav/ann_date/nav_date/net_asset/total_netasset`）、`fund_div`（400；分红）、`fund_portfolio`（5000 起；季度持仓，`end_date`/`ann_date` 两维）、`fund_adj`（复权因子，2000；高频 5000）、`fund_manager`、`fund_share`（场内份额，2000）、`fund_daily`（ETF/LOF 日线，5000）。来源：<https://tushare.pro/document/2?doc_id=119>（fund_nav）、[120](https://tushare.pro/document/2?doc_id=120)（fund_div）、[121](https://tushare.pro/document/2?doc_id=121)（fund_portfolio）、[199](https://tushare.pro/document/2?doc_id=199)（fund_adj）、[207](https://tushare.pro/document/2?doc_id=207)（fund_share）、[127](https://tushare.pro/document/2?doc_id=127)（fund_daily）
- ② 日/季。③ 全历史（文档未标起点，**未验证**）。
- ④ 2000 分≈200 元/年、5000 分≈500 元/年、10000 分≈1000 元/年；机构 ×10。来源：<https://tushare.pro/document/1?doc_id=290>
- ⑤ 2000 分 200 次/分、10 万行/日；5000 分 500 次/分不限量；`fund_portfolio` 5000 分 200 次/分、8000 分 500 次/分；单次 2000–5000 行。
- ⑥ 注册 + token；国内手机号（推断，**未验证**）。**注册门槛**：需付费 200–500 元达标积分。
- ⑦ 个人非商业（doc_id=405）；再分发未明示 → **未验证**。
- ⑧ REST/SDK。⑨ 商业化维护，稳定。
- ⑩ **最佳**：`ann_date` 与 `nav_date` 分离、独立 `fund_adj` 因子表；文档提示"复权因子可能因分红拆分刷新，需动态更新" → 因子表也需按日快照。
- ⑪ tushare.pro 美国 ✅（仅文档）。

### 1.6 蛋卷基金 danjuanfunds.com（雪球）— 上一轮可达，未纳入探针
- ① `djapi/fund/<code>`（基本信息、规模 `totshare`、经理、托管行）、`djapi/fund/nav/history/<code>`（净值分页）、`djapi/fund/detail/<code>`。② 日。③ 全历史（起点 **未验证**）。④ 免费。⑤ 未知。⑥ 部分接口需登录 Cookie（**未验证**）。⑦ 无公开条款 → 灰色。⑧ JSON。⑨ 非官方。⑩ 适合作东财的交叉校验第二 source。⑪ 上一轮美国 200。

### 1.7 巨潮资讯 cninfo
- ① 基金公告 PDF（定期报告 = **完整持仓**，非仅前十）；`webapi.cninfo.com.cn` 数据 API（付费 key）。② 事件驱动。③ 全。④ 网页免费，API 付费（**未验证**）。⑦ 未明示。⑩ 公告有唯一 ID + 日期，天然 append-only；需 PDF 解析。⑪ 上一轮 200。来源：<https://www.cninfo.com.cn/new/commonUrl/pageOfSearch?url=disclosure/list/search>

### 1.8 上交所 / 深交所（场内基金）
- ① ETF 列表、日度份额/规模、PCF 申赎清单、IOPV。② 日。④ 免费。⑦ 沪深法律声明"非商业目的可下载"（见 A 股文档 §1.9）。⑩ 官方一手，最适合 append-only。⑪ SSE ✅；SZSE JSON 上一轮 403 / 本次探测路径 404（需正确 Referer/参数，**未验证**）。来源：<https://www.sse.com.cn/assortment/fund/etf/list/> 、<https://www.szse.cn/market/product/list/etfList/index.html>

### 1.9 集思录（ETF/LOF 折溢价）
- 实时折溢价、规模、估值；免费 + 会员数据包（约 199 元/年，**未验证**）；声明"仅供参考"，抓取灰色；⑪ 上一轮 **20s 超时**（本节点不稳定）。

### 1.10 付费终端：Wind / Choice / JQData / RQData / 晨星 / 理杏仁 / 天相
- Wind/Choice：全覆盖（复权净值、全持仓、费率、规模历史），数万元/年起（**未验证**），需国内终端；落库允许、再分发禁止（典型条款，**未验证**）。
- JQData：`finance.FUND_*` 表；**站点拒绝非大陆 IP**（实测）。RQData：`rqdatac_fund` 模块（净值/持仓/分红/经理/份额），试用 50 MB/日；价格 **未验证**。来源：<https://www.ricequant.com/doc/rqdata/python/fund-mod.html>
- 晨星中国：评级/分类为主，底层数据为 Morningstar Direct 商业产品，不适合作主源。理杏仁开放平台有 API（基金覆盖 **未验证**）；天相为机构产品。

### 1.11 AMAC（中国证券投资基金业协会）
- `gs.amac.org.cn/amac-infodisc` 为**私募**公示；公募仅机构名录，无净值/持仓 → 不适用。来源：<https://gs.amac.org.cn/amac-infodisc/res/pof/fund/index.html>

## 2. 汇总对比表

| 源 | 净值 | 复权/因子 | 持仓 | 分红 | 费率 | 价格 | 许可 | 美国节点 | append-only 适配 |
|---|---|---|---|---|---|---|---|---|---|
| 东财直连 | ✔ 全历史 | ✘（自算） | 季报前十 | ✔ | ✔ | 免费 | 未验证（灰色） | ✅ 实测 | 中（静默修正） |
| AKShare（东财） | ✔ | ✘ | ✔ | ✔ | 函数不稳 | 免费 | 学术 | ✅ 实测 | 中 |
| efinance（东财） | ✔ | ✘ | ✔ | — | — | 免费 | 学习交流 | ✅（推断） | 中 |
| Tushare Pro | ✔ ann/nav 双日期 | ✔ `fund_adj` | ✔ 5000 分 | ✔ | ✘ | 200–500 元/年 | 个人非商业 | ✅ 未实测 | **高** |
| 蛋卷 | ✔ | ✘ | 部分 | — | — | 免费 | 灰色 | ✅ 上一轮 | 校验用 |
| 巨潮公告 | ✘ | ✘ | **全持仓 PDF** | ✔ 公告 | ✔ 招募书 | 免费 | 未明示 | ✅ | 高（需解析） |
| 交易所 | 场内 IOPV/份额 | ✘ | PCF | — | — | 免费 | 非商业 | SSE ✅ SZSE ❓ | 高 |
| Wind/Choice/RQData | ✔ | ✔ | ✔ 全 | ✔ | ✔ | 万元级/询价 | 合同 | 需国内/未验证 | 高 |
| JQData | ✔ | ? | ? | ? | ? | 付费 | 付费 | ❌ 区域封锁 | — |

## 3. 推荐组合（供 owner 裁决）

- **方案 A —— 零成本、东财单上游（最快落地）**：直连 `f10/lsjz`（净值，含分红标记）+ `pingzhongdata`（费率/经理/规模/资产配置）+ `FundArchivesDatas?type=jjcc`（季度重仓），不经 AKShare，自控字段与 `source`；每日快照 + `fetched_at` + 内容哈希缓解静默修正。场内 ETF/LOF 行情需国内节点或交易所文件。风险：单点、许可灰色。
- **方案 B —— Tushare 5000 积分（≈500 元/年）为主 + 东财交叉校验（推荐）**：`ann_date/nav_date` 双日期、独立 `fund_adj`、`fund_portfolio` 两维，与"可解释、可重放"最契合；东财作第二 source（净值差 > 1e-4 报警）；场内 K 线用 `fund_daily`。需 owner 注册并把 token 放入 1Password quant-dev。
- **方案 C —— 商业终端（Wind/Choice/RQData）**：覆盖最全、条款清晰；成本高、需国内终端；适合后期或需要完整持仓时。

## 4. 待裁决清单（owner 回字母）

1. 东财"无明示许可"数据落库：**A** 接受（个人研究）/ **B** 不接受（只用 Tushare/交易所/公告）。
2. Tushare 档位：**A** 2000 分（无持仓）/ **B** 5000 分（含持仓 + ETF 日线）/ **C** 不买。
3. 场内 ETF 行情路径：**A** 国内节点拉东财 / **B** 交易所官网文件 / **C** Tushare `fund_daily`。
4. 复权净值：**A** 自算（分红再投）/ **B** Tushare `adj_nav`+`fund_adj` / **C** 两者都存并对账。
5. 完整持仓（半年报/年报 PDF）：**A** 一期纳入（cninfo PDF 解析）/ **B** 二期。
6. 盘中估值 fundgz：**A** 不需要 / **B** 需要（先确认端点是否下线）。

## 5. 信息来源

- AKShare：<https://akshare.akfamily.xyz/data/fund/fund_public.html> ；源码 `akshare/fund/fund_em.py`、`fund_portfolio_em.py` <https://github.com/akfamily/akshare>
- efinance：<https://github.com/Micro-sheep/efinance>
- Tushare：<https://tushare.pro/document/2?doc_id=119> 、120、121、199、207、127；<https://tushare.pro/document/1?doc_id=290> 、108、13、405
- 东财端点（实测）：`https://fund.eastmoney.com/pingzhongdata/110011.js`、`https://api.fund.eastmoney.com/f10/lsjz?fundCode=110011&pageIndex=1&pageSize=20`、`https://fundf10.eastmoney.com/FundArchivesDatas.aspx?type=jjcc&code=110011&topline=10&year=2025`、`https://fund.eastmoney.com/js/fundcode_search.js`、`https://fundgz.1234567.com.cn/js/110011.js`
- 蛋卷（上一轮实测）：`https://danjuanfunds.com/djapi/fund/110011`、`/djapi/fund/nav/history/110011`
- AMAC：<https://gs.amac.org.cn/amac-infodisc/res/pof/fund/index.html> ；巨潮：<https://www.cninfo.com.cn/>
- 晨星：<https://www.morningstar.cn/> ；集思录：<https://www.jisilu.cn/data/etf/>
- JQData：<https://github.com/JoinQuant/jqdatasdk> ；RQData：<https://www.ricequant.com/doc/rqdata/python/fund-mod.html>
- 交易所：<https://www.sse.com.cn/assortment/fund/etf/list/> 、<https://www.szse.cn/market/product/list/etfList/index.html>

## 6. 未验证项

fundgz 端点状态；东财数据使用条款（版权页 404）；蛋卷/集思录条款；Tushare 是否强制国内手机号、`fund_nav` 起点、再分发条款；Wind/Choice/天相/理杏仁基金模块价格与条款；JQData/RQData 基金字段与价格；SZSE JSON 正确参数；东财修正净值是否覆盖历史；巨潮 API 价格；所有"国内→X"可达性。

## 7. 探针实测输出摘要（`eastmoney_cn_funds.py`，2026-09-18 03:5x UTC，美国节点，标的 110011）

| source | check | ok | 耗时 s | 行数 | 起 | 止 | ≥3y | 字段 / 备注 |
|---|---|---|---|---|---|---|---|---|
| 东财 `pingzhongdata/110011.js` | 全量净值 | ✅ | 0.54 | 4402 | 2008-06-18 | 2026-09-16 | ✅ | `x(ms)`, `y(单位净值)`, `equityReturn`, `unitMoney(分红)`；同文件含 `Data_ACWorthTrend` 累计净值 |
| 东财 `api.fund.eastmoney.com/f10/lsjz` | 分页净值（pageSize=20） | ✅ | 1.80 | 20 | 2026-08-21 | 2026-09-17 | —（分页） | `FSRQ, DWJZ, LJJZ, SDATE, ACTUALSYI, NAVTYPE, JZZZL, SGZT, SHZT, FHFCZ, FHFCZ10, FHFCBZ, FHSP`；`TotalCount=4402` 可翻页拉全量 |
| 东财 `fundgz.1234567.com.cn/js/110011.js` | 盘中估值 | ❌ | 2.64 | 0 | | | | `gsz=None gztime=None`（返回体无 `jsonpgz(...)`）→ 疑似端点下线，未验证 |
| AKShare `fund_open_fund_info_em(110011, "单位净值走势")` | 净值 | ✅ | 0.45 | 4402 | 2008-06-19 | 2026-09-17 | ✅ | `净值日期, 单位净值, 日增长率` |
| AKShare `fund_portfolio_hold_em(110011, "2025")` | 季报重仓 | ✅ | 2.40 | 123 | — | — | — | `序号, 股票代码, 股票名称, 占净值比例, 持股数, 持仓市值, 季度`（2025 年 4 个季度 × 前十 + 补充） |
| AKShare `fund_fee_em(110011, "认购费率")` | 费率 | ❌ | 2.08 | 0 | | | | 返回空表（无异常）；费率可改从 `pingzhongdata` 的 `fund_Rate/fund_sourceRate` 取 |
| AKShare `fund_fh_em()` | 全市场分红列表 | ✅ | 50.52 | 7500 | — | — | — | `序号, 基金代码, 基金简称, 权益登记日, 除息日期, 分红, 分红发放日`（全表 50s，宜每日一次） |

**复现**：`cd docs/research/probes && python run_all.py eastmoney_cn_funds`（依赖 akshare、pandas、requests）。
