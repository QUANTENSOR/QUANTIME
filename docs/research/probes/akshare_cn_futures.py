"""Probe: AKShare 期货/期权 — 国内期货日线 (新浪 / 交易所) + 期权 (交易所 / 新浪).

No token. Exchange-site functions (get_futures_daily) hit SHFE/DCE/CZCE/CFFEX/GFEX
websites directly, which may WAF-block overseas IPs.
Run: python akshare_cn_futures.py
"""
from __future__ import annotations

import datetime as dt

import akshare as ak

from _common import df_summary, main_guard, run_check


def fut_main_sina():
    # 新浪主力连续合约日线（RB0 螺纹钢）
    df = ak.futures_main_sina(symbol="RB0", start_date="20210101", end_date="20500101")
    return df_summary(df, "日期")


def fut_zh_daily_sina():
    df = ak.futures_zh_daily_sina(symbol="RB2601")
    return df_summary(df, "date")


def fut_latest_sina():
    df = ak.futures_zh_spot(symbol="RB0", market="CF", adjust="0")
    out = df_summary(df)
    out["note"] = "新浪实时（期货 level-1 快照）"
    return out


def fut_exchange_daily(market: str):
    day = (dt.date.today() - dt.timedelta(days=2))
    while day.weekday() >= 5:
        day -= dt.timedelta(days=1)
    df = ak.get_futures_daily(start_date=day.strftime("%Y%m%d"), end_date=day.strftime("%Y%m%d"), market=market)
    out = df_summary(df, "date")
    out["note"] = f"交易所官网日行情 {market} {day}"
    return out


def index_fut_cffex_sina():
    df = ak.futures_main_sina(symbol="IF0", start_date="20210101", end_date="20500101")
    return df_summary(df, "日期")


def option_cffex_daily():
    # 先取当前挂牌合约列表，再取其中一个合约的日线（新浪）
    months = next(iter(ak.option_cffex_zz1000_list_sina().values()))
    tbl = ak.option_cffex_zz1000_spot_sina(symbol=months[0])
    code = str(tbl["看涨合约-标识"].iloc[len(tbl) // 2])
    df = ak.option_cffex_zz1000_daily_sina(symbol=code)
    out = df_summary(df, "date")
    out["note"] = f"contract={code} (单合约日线，仅合约寿命内)"
    return out


def _last_trading_day():
    day = dt.date.today() - dt.timedelta(days=2)
    while day.weekday() >= 5:
        day -= dt.timedelta(days=1)
    return day.strftime("%Y%m%d")


def option_sse_etf_daily():
    # 上交所期权 每日统计（上交所官网）
    df = ak.option_daily_stats_sse(date=_last_trading_day())
    return df_summary(df)


def option_sse_etf_contract_daily():
    # 新浪 50ETF 期权：先取当月看涨合约代码，再取单合约日线
    codes = ak.option_sse_codes_sina(symbol="看涨期权", trade_date=dt.date.today().strftime("%Y%m"), underlying="510050")
    code = codes.iloc[len(codes) // 2, -1]
    df = ak.option_sse_daily_sina(symbol=str(code))
    out = df_summary(df, "日期")
    out["note"] = f"contract={code}"
    return out


def option_commodity_sina():
    df = ak.option_commodity_contract_table_sina(symbol="黄金期权", contract="au2612")
    out = df_summary(df)
    out["note"] = "新浪商品期权 T 型报价（当前快照）"
    return out


def option_dce_daily():
    df = ak.option_hist_dce(symbol="豆粕期权", trade_date=_last_trading_day())
    return df_summary(df)


def option_shfe_daily():
    df = ak.option_hist_shfe(symbol="黄金期权", trade_date=_last_trading_day())
    return df_summary(df)


def option_commodity_hist_sina():
    tbl = ak.option_commodity_contract_table_sina(symbol="黄金期权", contract="au2612")
    code = str(tbl["看涨合约-看涨期权合约"].iloc[len(tbl) // 2]) if "看涨合约-看涨期权合约" in tbl.columns else str(tbl.iloc[len(tbl) // 2, 0])
    df = ak.option_commodity_hist_sina(symbol=code)
    out = df_summary(df, "date")
    out["note"] = f"contract={code}"
    return out


def main():
    run_check("akshare", "cn_futures_commodity", "daily_history", fut_main_sina, upstream="sina")
    run_check("akshare", "cn_futures_commodity", "daily_history_contract", fut_zh_daily_sina, upstream="sina")
    run_check("akshare", "cn_futures_commodity", "latest_quote", fut_latest_sina, upstream="sina")
    run_check("akshare", "cn_futures_index", "daily_history", index_fut_cffex_sina, upstream="sina")
    for m in ["SHFE", "DCE", "CZCE", "CFFEX", "GFEX", "INE"]:
        run_check("akshare", f"cn_futures_exchange_{m}", "daily_exchange_site", lambda m=m: fut_exchange_daily(m), upstream=m)
    run_check("akshare", "cn_option_index", "daily_history", option_cffex_daily, upstream="sina")
    run_check("akshare", "cn_option_etf", "daily_stats", option_sse_etf_daily, upstream="sse")
    run_check("akshare", "cn_option_etf", "daily_history_contract", option_sse_etf_contract_daily, upstream="sina")
    run_check("akshare", "cn_option_commodity", "latest_quote", option_commodity_sina, upstream="sina")
    run_check("akshare", "cn_option_commodity", "daily_history_contract", option_commodity_hist_sina, upstream="sina")
    run_check("akshare", "cn_option_commodity", "daily_exchange_site", option_dce_daily, upstream="DCE")
    run_check("akshare", "cn_option_commodity", "daily_exchange_site_shfe", option_shfe_daily, upstream="SHFE")


if __name__ == "__main__":
    main_guard(main)
