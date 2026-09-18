# 探针汇总（自动生成，勿手改）

- run_at: 2026-09-18T03:59:48+00:00 UTC
- python: 3.13.5 / Linux-7.0.14-11-pve-x86_64-with-glibc2.41
- 探针文件 13 个，检查项 145 个，通过 107 个
- 节点：美国（探测出口 IP 见各文档），未使用代理；ok=❌ 含“本节点不可达 / 需 token / 上游限制”三类，详见 error 列

## akshare_cn_equity.py

rc=0 stderr_tail= 60%|██████    | 3/5 [00:01<00:01,  1.97it/s] |  80%|████████  | 4/5 [00:01<00:00,  2.07it/s] | 100%|██████████| 5/5 [00:02<00:00,  2.15it/s]

| source | market | check | ok | elapsed_s | rows | first | last | ≥3y | token | error / note |
|---|---|---|---|---|---|---|---|---|---|---|
| akshare | cn_equity_stock | daily_history | ❌ | 1.674 |  |  |  |  |  | ConnectionError: ('Connection aborted.', RemoteDisconnected('Remote end closed connection without response')) |
| akshare | cn_equity_stock | latest_quote | ❌ | 8.977 |  |  |  |  |  | ConnectionError: ('Connection aborted.', RemoteDisconnected('Remote end closed connection without response')) |
| akshare | cn_equity_etf | daily_history | ❌ | 0.729 |  |  |  |  |  | ConnectionError: ('Connection aborted.', RemoteDisconnected('Remote end closed connection without response')) |
| akshare | cn_equity_etf | latest_quote | ✅ | 38.243 | 1 |  |  |  |  | etf spot rows total=1621 |
| akshare | cn_equity_stock | daily_history_sina | ✅ | 3.225 | 970 | 2022-09-19 | 2026-09-17 | ✅ |  |  |
| akshare | cn_equity_stock | daily_history_tx | ✅ | 6.952 | 970 | 2022-09-19 | 2026-09-17 | ✅ |  |  |
| akshare | cn_equity_etf | daily_history_sina | ✅ | 0.168 | 3480 | 2012-05-28 | 2026-09-17 | ✅ |  |  |
| akshare | cn_convertible_bond | daily_history | ✅ | 0.448 | 978 | 2021-07-01 | 2025-07-14 | ✅ |  |  |
| akshare | cn_convertible_bond | latest_quote | ✅ | 3.263 | 329 |  |  |  |  | 可转债实时全表（新浪） |

## akshare_cn_futures.py

rc=0

| source | market | check | ok | elapsed_s | rows | first | last | ≥3y | token | error / note |
|---|---|---|---|---|---|---|---|---|---|---|
| akshare | cn_futures_commodity | daily_history | ✅ | 1.538 | 1385 | 2021-01-04 | 2026-09-17 | ✅ |  |  |
| akshare | cn_futures_commodity | daily_history_contract | ✅ | 1.747 | 242 | 2025-01-16 | 2026-01-15 | ❌ |  |  |
| akshare | cn_futures_commodity | latest_quote | ✅ | 1.072 | 1 | 2000-11-30 | 2000-11-30 | ❌ |  | 新浪实时（期货 level-1 快照） |
| akshare | cn_futures_index | daily_history | ✅ | 1.164 | 1385 | 2021-01-04 | 2026-09-17 | ✅ |  |  |
| akshare | cn_futures_exchange_SHFE | daily_exchange_site | ✅ | 1.842 | 305 | 2026-09-15 | 2026-09-15 | ❌ |  | 交易所官网日行情 SHFE 2026-09-15 |
| akshare | cn_futures_exchange_DCE | daily_exchange_site | ❌ | 0.909 |  |  |  |  |  | JSONDecodeError: Expecting value: line 1 column 1 (char 0) |
| akshare | cn_futures_exchange_CZCE | daily_exchange_site | ✅ | 2.349 | 238 | 1970-01-01 | 1970-01-01 | ❌ |  | 交易所官网日行情 CZCE 2026-09-15 |
| akshare | cn_futures_exchange_CFFEX | daily_exchange_site | ✅ | 1.33 | 28 | 2026-09-15 | 2026-09-15 | ❌ |  | 交易所官网日行情 CFFEX 2026-09-15 |
| akshare | cn_futures_exchange_GFEX | daily_exchange_site | ✅ | 0.481 | 48 | 2026-09-15 | 2026-09-15 | ❌ |  | 交易所官网日行情 GFEX 2026-09-15 |
| akshare | cn_futures_exchange_INE | daily_exchange_site | ✅ | 1.402 | 67 | 2026-09-15 | 2026-09-15 | ❌ |  | 交易所官网日行情 INE 2026-09-15 |
| akshare | cn_option_index | daily_history | ✅ | 2.225 | 44 | 2026-07-20 | 2026-09-17 | ❌ |  | contract=mo2610C7500 (单合约日线，仅合约寿命内) |
| akshare | cn_option_etf | daily_stats | ✅ | 0.636 | 5 |  |  |  |  |  |
| akshare | cn_option_etf | daily_history_contract | ✅ | 1.527 | 155 | 2026-01-29 | 2026-09-17 | ❌ |  | contract=10010974 |
| akshare | cn_option_commodity | latest_quote | ✅ | 1.464 | 88 |  |  |  |  | 新浪商品期权 T 型报价（当前快照） |
| akshare | cn_option_commodity | daily_history_contract | ✅ | 2.142 | 93 | 2026-03-27 | 2026-09-17 | ❌ |  | contract=au2612C1000 |
| akshare | cn_option_commodity | daily_exchange_site | ❌ | 0.909 |  |  |  |  |  | JSONDecodeError: Expecting value: line 1 column 1 (char 0) |
| akshare | cn_option_commodity | daily_exchange_site_shfe | ✅ | 10.893 | 776 |  |  |  |  |  |

## baostock_cn_equity.py

rc=0

| source | market | check | ok | elapsed_s | rows | first | last | ≥3y | token | error / note |
|---|---|---|---|---|---|---|---|---|---|---|
| baostock | cn_equity_stock | daily_history | ✅ | 4.492 | 1142 | 2022-01-04 | 2026-09-17 | ✅ |  |  |
| baostock | cn_equity_stock | latest_quote | ✅ | 0.243 | 1 | 2026-09-17 | 2026-09-17 | ❌ |  | last close=1266.9800000000 (无实时，只有已收盘日线) |
| baostock | cn_equity_etf | daily_history | ✅ | 0.386 | 173 | 2026-01-05 | 2026-09-17 | ❌ |  |  |
| baostock | cn_equity_stock | adjust_factor | ✅ | 0.194 | 17 | 2015-07-17 | 2026-06-26 | ✅ |  | 复权因子可单独拉取（foreAdjustFactor/backAdjustFactor） |

## cex_public_crypto.py

rc=0

| source | market | check | ok | elapsed_s | rows | first | last | ≥3y | token | error / note |
|---|---|---|---|---|---|---|---|---|---|---|
| binance | crypto_spot | daily_history | ❌ | 0.035 |  |  |  |  |  | RuntimeError: HTTP 451: {   "code": 0,   "msg": "Service unavailable from a restricted location according to 'b. Eligibility' in https://www.binance.com/en/term |
| binance | crypto_perp | daily_history | ❌ | 0.043 |  |  |  |  |  | RuntimeError: HTTP 451: {   "code": 0,   "msg": "Service unavailable from a restricted location according to 'b. Eligibility' in https://www.binance.com/en/term |
| binance_us | crypto_spot | daily_history | ✅ | 0.831 | 1000 | 2023-12-24 | 2026-09-18 | ❌ |  |  |
| binance_vision | crypto_spot | monthly_zip | ✅ | 0.226 | 31 |  |  |  |  | spot/monthly/klines/BTCUSDT/1d/BTCUSDT-1d-2026-08.zip (2185 bytes) |
| binance_vision | crypto_perp | monthly_zip | ✅ | 0.187 | 31 |  |  |  |  | futures/um/monthly/klines/BTCUSDT/1d/BTCUSDT-1d-2026-08.zip (2115 bytes) |
| binance_vision | crypto_perp_funding | monthly_zip | ✅ | 0.499 | 93 |  |  |  |  | futures/um/monthly/fundingRate/BTCUSDT/BTCUSDT-fundingRate-2026-08.zip (896 bytes) |
| binance_vision | crypto_perp_metrics_oi | daily_zip | ✅ | 0.499 | 288 |  |  |  |  | futures/um/daily/metrics/BTCUSDT/BTCUSDT-metrics-2026-09-15.zip (11645 bytes) |
| binance_vision | crypto_perp | history_depth_index | ✅ | 0.716 | 80 | 2020 | 2026 |  |  | first=data/futures/um/monthly/klines/BTCUSDT/1d/BTCUSDT-1d-2020-01.zip |
| okx | crypto_spot | daily_history | ✅ | 1.944 | 1100 | 2023-09-15 | 2026-09-18 | ✅ |  | BTC-USDT history-candles 100/次 分页 |
| okx | crypto_perp | daily_history | ✅ | 1.931 | 1100 | 2023-09-15 | 2026-09-18 | ✅ |  | BTC-USDT-SWAP history-candles 100/次 分页 |
| okx | crypto_perp | latest_quote | ✅ | 0.171 | 1 |  |  |  |  | last=77347.5 ts=1789703839570 |
| okx | crypto_perp_funding | history | ✅ | 0.179 | 100 | 2026-08-16 | 2026-09-18 | ❌ |  | 100/次，可用 after 翻页 |
| okx | crypto_perp_oi | history | ✅ | 0.261 | 100 | 2026-06-10 | 2026-09-17 | ❌ |  |  |
| bybit | crypto_perp | daily_history | ❌ | 0.041 |  |  |  |  |  | RuntimeError: HTTP 403: {     error:The Amazon CloudFront distribution is configured to block access from your country } |
| bybit | crypto_spot | daily_history | ❌ | 0.005 |  |  |  |  |  | RuntimeError: HTTP 403: {     error:The Amazon CloudFront distribution is configured to block access from your country } |
| bybit_public | crypto_perp | bulk_csv_index | ✅ | 0.305 | 2368 | 020-03-25. | 026-09-17. |  |  | public.bybit.com/trading/ 逐笔成交 日文件 |
| bitget | crypto_perp | daily_history | ✅ | 1.511 | 720 | 2024-09-20 | 2026-09-16 | ❌ |  |  |
| coinbase | crypto_spot | daily_history | ✅ | 0.409 | 1500 | 2022-08-11 | 2026-09-18 | ✅ |  | 300 根/次，分页 |
| coinbase | crypto_spot | latest_quote | ✅ | 0.016 | 1 |  |  |  |  | price=77308.14 time=2026-09-18T03:57:22.292764026Z |
| kraken | crypto_spot | daily_history | ✅ | 0.161 | 721 | 2024-09-28 | 2026-09-18 | ❌ |  | Kraken OHLC 最多返回最近 720 根（官方限制），日线≈2 年 |
| kraken_futures | crypto_perp | daily_history | ✅ | 0.165 | 1460 | 2022-09-20 | 2026-09-18 | ✅ |  |  |
| kraken_futures | crypto_perp | latest_quote | ✅ | 0.383 | 1 |  |  |  |  | PF_XBTUSD last=77319 fundingRate=0.7790234260500161 |
| deribit | crypto_perp | daily_history | ✅ | 0.269 | 1461 | 2022-09-18 | 2026-09-17 | ✅ |  |  |
| deribit | crypto_perp | latest_quote | ✅ | 0.097 | 1 |  |  |  |  | last=77325.0 funding_8h=6.82e-06 OI=764620660 |
| deribit | crypto_option | chain_snapshot | ✅ | 0.114 | 930 |  |  |  |  | 当前全部 BTC 期权合约汇总（mark_iv/OI/volume），无历史链快照端点 |
| hyperliquid | crypto_perp_dex | daily_history | ✅ | 0.216 | 1461 | 2022-09-19 | 2026-09-18 | ✅ |  | candleSnapshot 最多 5000 根（官方） |
| hyperliquid | crypto_perp_dex | latest_quote | ✅ | 0.341 | 1 |  |  |  |  | BTC markPx=77349.1 funding=0.0000073847 OI=35209.4842 |
| dydx_v4 | crypto_perp_dex | daily_history | ✅ | 6.195 | 1041 | 2023-11-13 | 2026-09-18 | ❌ |  | dYdX v4 主网 2023-10 上线，历史天然 <3 年 |
| gate | crypto_perp | daily_history | ✅ | 1.268 | 2000 | 2021-03-29 | 2026-09-18 | ✅ |  |  |

## eastmoney_cn_equity.py

rc=0

| source | market | check | ok | elapsed_s | rows | first | last | ≥3y | token | error / note |
|---|---|---|---|---|---|---|---|---|---|---|
| eastmoney | cn_equity_stock | daily_history | ❌ | 0.991 |  |  |  |  |  | ConnectionError: ('Connection aborted.', RemoteDisconnected('Remote end closed connection without response')) |
| eastmoney | cn_equity_stock | daily_history_delayhost | ❌ | 1.077 | 0 |  |  |  |  | host=push2delay.eastmoney.com secid=1.600519 fqt=1 |
| eastmoney | cn_equity_stock | latest_quote | ❌ | 20.241 |  |  |  |  |  | ReadTimeout: HTTPSConnectionPool(host='push2.eastmoney.com', port=443): Read timed out. (read timeout=20) |
| eastmoney | cn_equity_etf | daily_history | ❌ | 1.375 |  |  |  |  |  | ConnectionError: ('Connection aborted.', RemoteDisconnected('Remote end closed connection without response')) |
| eastmoney | cn_equity_etf | daily_history_delayhost | ❌ | 0.286 | 0 |  |  |  |  | host=push2delay.eastmoney.com secid=1.510300 fqt=1 |
| eastmoney | cn_equity_etf | latest_quote | ❌ | 1.028 |  |  |  |  |  | HTTPError: 502 Server Error: Bad Gateway for url: https://push2.eastmoney.com/api/qt/stock/get?secid=1.510300&fields=f43%2Cf44%2Cf45%2Cf46%2Cf47%2Cf48%2Cf57%2Cf |
| eastmoney | cn_convertible_bond | daily_history | ❌ | 1.424 |  |  |  |  |  | ConnectionError: ('Connection aborted.', RemoteDisconnected('Remote end closed connection without response')) |
| eastmoney | cn_convertible_bond | daily_history_delayhost | ❌ | 0.302 | 0 |  |  |  |  | host=push2delay.eastmoney.com secid=1.113050 fqt=1 |
| eastmoney | cn_convertible_bond | latest_quote | ❌ | 0.362 |  |  |  |  |  | HTTPError: 502 Server Error: Bad Gateway for url: https://push2.eastmoney.com/api/qt/stock/get?secid=1.113050&fields=f43%2Cf44%2Cf45%2Cf46%2Cf47%2Cf48%2Cf57%2Cf |
| eastmoney | hk_equity | daily_history | ❌ | 0.631 |  |  |  |  |  | ConnectionError: ('Connection aborted.', RemoteDisconnected('Remote end closed connection without response')) |
| eastmoney | hk_equity | daily_history_delayhost | ❌ | 0.293 | 0 |  |  |  |  | host=push2delay.eastmoney.com secid=116.00700 fqt=1 |
| eastmoney | hk_equity | latest_quote | ❌ | 0.358 |  |  |  |  |  | HTTPError: 502 Server Error: Bad Gateway for url: https://push2.eastmoney.com/api/qt/stock/get?secid=116.00700&fields=f43%2Cf44%2Cf45%2Cf46%2Cf47%2Cf48%2Cf57%2C |

## eastmoney_cn_funds.py

rc=0 stderr_tail= 97%|█████████▋| 72/74 [00:48<00:01,  1.38it/s] |  99%|█████████▊| 73/74 [00:49<00:00,  1.46it/s] | 100%|██████████| 74/74 [00:49<00:00,  1.46it/s]

| source | market | check | ok | elapsed_s | rows | first | last | ≥3y | token | error / note |
|---|---|---|---|---|---|---|---|---|---|---|
| eastmoney_fund | cn_fund_nav | daily_history | ✅ | 0.544 | 4402 | 2008-06-18 | 2026-09-16 | ✅ |  | 全量单位净值 + 累计净值(Data_ACWorthTrend) + 分红在同一 JS 文件 |
| eastmoney_fund | cn_fund_nav | daily_history_paged | ✅ | 1.803 | 20 | 2026-08-21 | 2026-09-17 | ❌ |  | TotalCount=4402 (分页可拉全量) |
| eastmoney_fund | cn_fund_nav | latest_quote | ❌ | 2.638 | 0 |  |  |  |  | gsz=None gztime=None (盘中估值, 非官方净值) |
| akshare | cn_fund_nav | daily_history | ✅ | 0.449 | 4402 | 2008-06-19 | 2026-09-17 | ✅ |  |  |
| akshare | cn_fund_holdings | snapshot | ✅ | 2.404 | 123 |  |  |  |  | 季报重仓股（东财 F10） |
| akshare | cn_fund_fee | snapshot | ❌ | 2.079 | 0 |  |  |  |  |  |
| akshare | cn_fund_dividend | snapshot | ✅ | 50.516 | 7500 |  |  |  |  | 全市场分红列表（东财） |

## exchange_sites_cn.py

rc=0

| source | market | check | ok | elapsed_s | rows | first | last | ≥3y | token | error / note |
|---|---|---|---|---|---|---|---|---|---|---|
| exchange_site_sse | cn_equity | reachability | ✅ | 3.305 | 1 |  |  |  |  | https://yunhq.sse.com.cn:32042/v1/sh1/dayk/600519?begin=-30&end=-1 |
| exchange_site_szse | cn_equity | reachability | ❌ | 0.817 | 0 |  |  |  |  | HTTP 404 |
| exchange_site_bse | cn_equity | reachability | ✅ | 1.247 | 1 |  |  |  |  | https://www.bse.cn/nqhqController/nqhq.do?xxfcbj=2&page=0&xxzqdm=920001 |
| exchange_site_shfe | cn_futures | reachability | ✅ | 1.568 | 1 |  |  |  |  | https://www.shfe.com.cn/data/tradedata/future/dailydata/kx20260916.dat |
| exchange_site_ine | cn_futures | reachability | ❌ | 0.827 | 0 |  |  |  |  | HTTP 404 |
| exchange_site_dce | cn_futures | reachability | ❌ | 0.949 | 0 |  |  |  |  | HTTP 412 |
| exchange_site_czce | cn_futures | reachability | ❌ | 2.32 | 0 |  |  |  |  | HTTP 412 |
| exchange_site_gfex | cn_futures | reachability | ✅ | 0.738 | 1 |  |  |  |  | http://www.gfex.com.cn/gfex/rihq/hqsj_tjsj.shtml |
| exchange_site_cffex | cn_futures_index | reachability | ✅ | 2.372 | 1 |  |  |  |  | http://www.cffex.com.cn/sj/historysj/202609/zip/202609.zip |
| exchange_site_hkex_dq | hk_equity | reachability | ✅ | 3.501 | 1 |  |  |  |  | https://www.hkex.com.hk/eng/stat/smstat/dayquot/d260916e.htm |
| exchange_site_hkex_home | hk_equity | reachability | ✅ | 3.517 | 1 |  |  |  |  | https://www.hkex.com.hk/?sc_lang=en |

## free_public_us.py

rc=0

| source | market | check | ok | elapsed_s | rows | first | last | ≥3y | token | error / note |
|---|---|---|---|---|---|---|---|---|---|---|
| yfinance | us_equity | daily_history | ✅ | 0.365 | 1255 | 2021-09-17 | 2026-09-17 | ✅ |  | SPY period=5y auto_adjust=False (含 Dividends/Stock Splits 列) |
| yfinance | us_equity | daily_history_stock | ✅ | 0.165 | 1254 | 2021-09-20 | 2026-09-17 | ✅ |  | AAPL period=5y auto_adjust=False (含 Dividends/Stock Splits 列) |
| yfinance | us_equity | latest_quote | ✅ | 0.097 | 1 |  | 2026-09-17 |  |  | SPY fast_info.last_price=None history(5d).close=762.5999755859375 |
| yfinance | us_option | chain_snapshot | ✅ | 0.198 | 613 |  |  |  |  | SPY 当前到期日数=28 first_exp=2026-09-18；仅当前链快照，无历史 |
| stooq | us_equity | daily_history | ❌ | 0.362 |  |  |  |  |  | RuntimeError: HTML instead of CSV (JS browser verification / access denied): '<!DOCTYPE html><html><head><meta charset="utf-8"><meta name="robots" content="noin |
| cboe_cdn | us_index_vix | daily_history | ✅ | 0.168 | 9275 | 1990-01-02 | 2026-09-17 | ✅ |  | Cboe CDN 官方 VIX 日 OHLC 全历史 CSV |
| cboe_cdn | us_option_market_stats | daily_history | ✅ | 0.02 | 3253 | 2006-11-01 | 2019-10-04 | ✅ |  | Cboe 全市场 put/call 比率 历史 CSV |
| cboe_cdn | us_option | chain_snapshot | ✅ | 0.56 | 12958 |  |  |  |  | SPY 延迟期权链快照 (bid/ask/iv/greeks/OI)，非正式接口；timestamp=2026-09-18 03:44:30 |
| nasdaq_trader | us_reference | symbol_directory | ✅ | 0.18 | 5619 |  |  |  |  | nasdaqlisted.txt 尾行='File Creation Time: 0917202621:31\|\|\|\|\|\|\|'（当前快照，无历史） |
| nasdaq_trader | us_reference | symbol_directory_other | ✅ | 0.137 | 7634 |  |  |  |  | otherlisted.txt 尾行='File Creation Time: 0917202621:31\|\|\|\|\|\|'（当前快照，无历史） |
| sec_edgar | us_fundamentals | ticker_map | ✅ | 0.286 | 10422 |  |  |  |  | SEC 官方 ticker→CIK 映射；必须带公司名+邮箱 UA |
| sec_edgar | us_fundamentals | companyfacts_history | ✅ | 0.091 | 146 | 2009-07-22 | 2026-07-31 | ✅ |  | AAPL companyfacts concept=Assets；每条 fact 含 accn/filed/frame → point-in-time 可重放 |
| fred | us_rates | daily_history | ✅ | 0.068 | 11752 | 1981-09-01 | 2026-09-16 | ✅ |  | DGS3MO 无 key CSV（非正式接口；正式 API 需 api_key，未注册）；浏览器 UA 超时/默认 UA 正常 |
| nasdaq_com | us_equity | daily_history | ✅ | 2.086 | 2513 | 2016-09-19 | 2026-09-17 | ✅ |  | nasdaq.com 非官方 JSON（无条款授权，仅对照） |

## onchain_dex_crypto.py

rc=0

| source | market | check | ok | elapsed_s | rows | first | last | ≥3y | token | error / note |
|---|---|---|---|---|---|---|---|---|---|---|
| coingecko | crypto_spot_agg | daily_history_365 | ✅ | 0.091 | 366 | 2025-09-19 | 2026-09-18 | ❌ |  | days=365 (免 key Demo 层：daily 仅 365 天；>365 需付费 — 见 error/rows) |
| coingecko | crypto_spot_agg | daily_history_max | ❌ | 0.059 |  |  |  |  |  | RuntimeError: HTTP 401: {"error":{"status":{"timestamp":"2026-09-18T03:59:28.512+00:00","error_code":10012,"error_message":"Your request exceeds the allowed tim |
| coingecko | crypto_spot_agg | ohlc | ✅ | 0.039 | 92 | 2025-09-17 | 2026-09-16 | ❌ |  | days=365 时粒度为 4 天 (官方文档)；ratelimit-remaining=None |
| coingecko | crypto_spot_agg | latest_quote | ✅ | 0.048 | 2 |  |  |  |  | btc=77326 |
| defillama | crypto_onchain_tvl | daily_history | ✅ | 0.064 | 3279 | 2017-09-27 | 2026-09-18 | ✅ |  | Ethereum 链 TVL 日序列 (/protocol/uniswap 全量 JSON 30s 超时，改用链级端点) |
| defillama | crypto_dex_spot_volume | daily_history | ✅ | 0.021 | 2878 | 2018-11-02 | 2026-09-18 | ✅ |  | Uniswap 日成交量 (DEX 现货) |
| defillama | crypto_dex_perp_volume | daily_history | ❌ | 0.007 |  |  |  |  |  | HTTPError: 402 Client Error: Payment Required for url: https://api.llama.fi/summary/derivatives/hyperliquid?dataType=dailyVolume |
| defillama | crypto_spot_agg | daily_history | ✅ | 2.877 | 1463 | 2022-09-19 | 2026-09-18 | ✅ |  | coins.llama.fi 日价格，span≤500/次 分页 |
| geckoterminal | crypto_dex_spot | daily_history | ✅ | 0.613 | 365 | 2025-09-19 | 2026-09-18 | ❌ |  | Uniswap v3 USDC/WETH 池 日 OHLCV；limit 最大 1000（官方） |
| dexscreener | crypto_dex_spot | latest_quote | ✅ | 0.061 | 1 |  |  |  |  | priceUsd=2478.077 vol24h=64293846.94；仅当前快照，无历史 OHLCV 公共端点 |
| coinpaprika | crypto_spot_agg | daily_history | ❌ | 0.185 |  |  |  |  |  | RuntimeError: HTTP 402: {"error":"Getting historical OHLCV data before 2026-09-17 03:59:32.385856048 +0000 UTC is not allowed in this plan. Check plans on coinp |
| blockchain_com | crypto_onchain_btc | daily_history | ✅ | 0.374 | 1450 | 2022-09-19 | 2026-09-17 | ✅ |  | BTC 链上 hash-rate 日序列 |
| mempool_space | crypto_onchain_btc | daily_history | ✅ | 0.093 | 1096 | 2023-09-19 | 2026-09-18 | ❌ |  | mempool.space 自托管 BTC 节点 API；hashrate 3y |

## sina_cn_equity.py

rc=0

| source | market | check | ok | elapsed_s | rows | first | last | ≥3y | token | error / note |
|---|---|---|---|---|---|---|---|---|---|---|
| sina | cn_equity_stock | latest_quote | ✅ | 0.87 | 1 |  | 2026-09-18 |  |  | name=贵州茅台 last=1257.200 date=2026-09-18 |
| sina | cn_equity_stock | daily_history | ✅ | 1.267 | 1023 | 2022-07-05 | 2026-09-17 | ✅ |  | 单次上限 datalen=1023，无日期区间参数；复权需另取 复权因子 |
| sina | cn_equity_etf | daily_history | ✅ | 0.306 | 1023 | 2022-07-05 | 2026-09-17 | ✅ |  | 单次上限 datalen=1023，无日期区间参数；复权需另取 复权因子 |
| sina | cn_convertible_bond | latest_quote | ✅ | 0.203 | 1 |  | 2026-09-18 |  |  | name=南银转债 last=144.967 date=2026-09-18 |
| sina | cn_convertible_bond | daily_history | ✅ | 1.556 | 978 | 2021-07-01 | 2025-07-14 | ✅ |  |  |
| sina | hk_equity | latest_quote | ✅ | 0.205 | 1 |  |  |  |  | name=TENCENT last=426.000 date=? |
| sina | hk_equity | daily_history | ✅ | 1.112 | 1 |  |  |  |  | bytes=75476; 需 akshare 内置解码，未在本探针解压 |

## stooq_cn_hk_us.py

rc=0

| source | market | check | ok | elapsed_s | rows | first | last | ≥3y | token | error / note |
|---|---|---|---|---|---|---|---|---|---|---|
| stooq | cn_equity_stock | daily_history | ❌ | 0.368 |  |  |  |  |  | RuntimeError: HTML instead of CSV (JS browser verification): <!DOCTYPE html><html><head><meta charset="utf-8"><meta name="robots" content="noindex,nofollow"></h |
| stooq | cn_equity_etf | daily_history | ❌ | 0.12 |  |  |  |  |  | RuntimeError: HTML instead of CSV (JS browser verification): <!DOCTYPE html><html><head><meta charset="utf-8"><meta name="robots" content="noindex,nofollow"></h |
| stooq | hk_equity | daily_history | ❌ | 0.117 |  |  |  |  |  | RuntimeError: HTML instead of CSV (JS browser verification): <!DOCTYPE html><html><head><meta charset="utf-8"><meta name="robots" content="noindex,nofollow"></h |
| stooq | hk_etf | daily_history | ❌ | 0.118 |  |  |  |  |  | RuntimeError: HTML instead of CSV (JS browser verification): <!DOCTYPE html><html><head><meta charset="utf-8"><meta name="robots" content="noindex,nofollow"></h |
| stooq | us_etf | daily_history | ❌ | 0.119 |  |  |  |  |  | RuntimeError: HTML instead of CSV (JS browser verification): <!DOCTYPE html><html><head><meta charset="utf-8"><meta name="robots" content="noindex,nofollow"></h |

## tencent_cn_equity.py

rc=0

| source | market | check | ok | elapsed_s | rows | first | last | ≥3y | token | error / note |
|---|---|---|---|---|---|---|---|---|---|---|
| tencent | cn_equity_stock | daily_history | ✅ | 2.143 | 1385 | 2021-01-04 | 2026-09-17 | ✅ |  | web.ifzq.gtimg.cn fqkline, 分页 2 年/次(单次≤640 根), fq=qfq |
| tencent | cn_equity_stock | latest_quote | ✅ | 0.902 | 1 |  | 20260918 |  |  | name=贵州茅台 last=1257.20 time=20260918115936 |
| tencent | cn_equity_etf | daily_history | ✅ | 0.692 | 1385 | 2021-01-04 | 2026-09-17 | ✅ |  | web.ifzq.gtimg.cn fqkline, 分页 2 年/次(单次≤640 根), fq=qfq |
| tencent | cn_convertible_bond | daily_history | ✅ | 0.69 | 978 | 2021-07-01 | 2025-07-14 | ✅ |  | web.ifzq.gtimg.cn fqkline, 分页 2 年/次(单次≤640 根), fq=none |
| tencent | hk_equity | daily_history | ✅ | 0.707 | 1406 | 2021-01-04 | 2026-09-17 | ✅ |  | web.ifzq.gtimg.cn fqkline, 分页 2 年/次(单次≤640 根), fq=qfq |
| tencent | hk_equity | latest_quote | ✅ | 0.22 | 1 |  | 2026/09/ |  |  | name=腾讯控股 last=425.400 time=2026/09/18 11:44:32 |
| tencent | hk_etf | daily_history | ✅ | 0.701 | 1406 | 2021-01-04 | 2026-09-17 | ✅ |  | web.ifzq.gtimg.cn fqkline, 分页 2 年/次(单次≤640 根), fq=qfq |

## yfinance_cn_hk_equity.py

rc=0 stderr_tail=$113050.SS: No data found, symbol may be delisted | $113050.SS: No data found, symbol may be delisted

| source | market | check | ok | elapsed_s | rows | first | last | ≥3y | token | error / note |
|---|---|---|---|---|---|---|---|---|---|---|
| yfinance | cn_equity_stock | daily_history | ✅ | 0.249 | 1211 | 2021-09-22 | 2026-09-18 | ✅ |  | ticker=600519.SS |
| yfinance | cn_equity_stock | latest_quote | ✅ | 0.16 | 1 | 2026-09-18 | 2026-09-18 | ❌ |  | fast_info.lastPrice=1257.199951171875 |
| yfinance | cn_equity_etf | daily_history | ✅ | 0.105 | 1209 | 2021-09-22 | 2026-09-18 | ✅ |  | ticker=510300.SS |
| yfinance | cn_equity_etf | latest_quote | ✅ | 0.134 | 1 | 2026-09-18 | 2026-09-18 | ❌ |  | fast_info.lastPrice=4.574999809265137 |
| yfinance | cn_convertible_bond | daily_history | ❌ | 0.508 | 0 |  |  |  |  | ticker=113050.SS |
| yfinance | cn_convertible_bond | latest_quote | ❌ | 0.173 |  |  |  |  |  | KeyError: 'currentTradingPeriod' |
| yfinance | hk_equity | daily_history | ✅ | 0.121 | 1227 | 2021-09-20 | 2026-09-18 | ✅ |  | ticker=0700.HK |
| yfinance | hk_equity | latest_quote | ✅ | 0.141 | 1 | 2026-09-18 | 2026-09-18 | ❌ |  | fast_info.lastPrice=425.3999938964844 |
| yfinance | hk_etf | daily_history | ✅ | 0.086 | 1225 | 2021-09-20 | 2026-09-18 | ✅ |  | ticker=2800.HK |
| yfinance | hk_etf | latest_quote | ✅ | 0.137 | 1 | 2026-09-18 | 2026-09-18 | ❌ |  | fast_info.lastPrice=25.399999618530273 |
