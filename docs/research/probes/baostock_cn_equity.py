"""Probe: BaoStock — A股 股票 / ETF 日线（含复权因子字段）+ 最新交易日行情.

BaoStock is a free TCP service (bs.login() anonymous, no token). It does
NOT provide realtime quotes; "latest" = last completed trading day.
Run: python baostock_cn_equity.py
"""
from __future__ import annotations

import datetime as dt

import baostock as bs
import pandas as pd

from _common import df_summary, main_guard, run_check


def _query(code: str, start: str, fields: str, adjust: str = "2"):
    rs = bs.query_history_k_data_plus(code, fields, start_date=start,
                                      end_date=dt.date.today().isoformat(),
                                      frequency="d", adjustflag=adjust)
    if rs.error_code != "0":
        raise RuntimeError(f"baostock error {rs.error_code}: {rs.error_msg}")
    rows = []
    while rs.next():
        rows.append(rs.get_row_data())
    return pd.DataFrame(rows, columns=rs.fields)


def stock_hist():
    df = _query("sh.600519", "2022-01-01",
                "date,code,open,high,low,close,preclose,volume,amount,adjustflag,turn,tradestatus,pctChg,isST")
    return df_summary(df, "date")


def stock_latest():
    df = _query("sh.600519", (dt.date.today() - dt.timedelta(days=10)).isoformat(),
                "date,code,close,volume,tradestatus")
    out = df_summary(df.tail(1), "date")
    out["note"] = f"last close={df['close'].iloc[-1] if len(df) else None} (无实时，只有已收盘日线)"
    return out


def etf_hist():
    df = _query("sh.510300", "2022-01-01", "date,code,open,high,low,close,volume,amount")
    return df_summary(df, "date")


def adjust_factor():
    rs = bs.query_adjust_factor(code="sh.600519", start_date="2015-01-01", end_date="2026-12-31")
    rows = []
    while rs.error_code == "0" and rs.next():
        rows.append(rs.get_row_data())
    df = pd.DataFrame(rows, columns=rs.fields)
    out = df_summary(df, "dividOperateDate")
    out["note"] = "复权因子可单独拉取（foreAdjustFactor/backAdjustFactor）"
    return out


def main():
    lg = bs.login()
    print(f"# baostock login: {lg.error_code} {lg.error_msg}")
    try:
        run_check("baostock", "cn_equity_stock", "daily_history", stock_hist)
        run_check("baostock", "cn_equity_stock", "latest_quote", stock_latest)
        run_check("baostock", "cn_equity_etf", "daily_history", etf_hist)
        run_check("baostock", "cn_equity_stock", "adjust_factor", adjust_factor)
    finally:
        bs.logout()


if __name__ == "__main__":
    main_guard(main)
