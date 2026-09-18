"""Probe: 腾讯财经 (qt.gtimg.cn / web.ifzq.gtimg.cn) — A股/港股 日线历史 + 实时快照.

Undocumented public endpoints used by many open-source libs (efinance/akshare).
No token. Realtime quote is exchange-delayed for HK, realtime for A股 (level-1).
Run: python tencent_cn_equity.py
"""
from __future__ import annotations

import requests
import pandas as pd

from _common import UA, df_summary, main_guard, run_check

S = requests.Session()
S.headers["User-Agent"] = UA


def _kline_page(symbol: str, start: str, end: str, fq: str):
    # Observed: with a date range the server caps at ~640 rows per call
    # (and up to 2001 rows when start/end are empty). Paginate by year.
    url = f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={symbol},day,{start},{end},640,{fq}"
    r = S.get(url, timeout=20)
    r.raise_for_status()
    data = r.json()["data"].get(symbol) or {}
    key = f"{fq}day" if f"{fq}day" in data else "day"
    return data.get(key) or []


def kline(symbol: str, fq: str = "qfq", start_year: int = 2021):
    import datetime as dt

    rows: list = []
    y = start_year
    this_year = dt.date.today().year
    while y <= this_year:
        rows += _kline_page(symbol, f"{y}-01-01", f"{y + 1}-12-31", fq)
        y += 2
    seen = {}
    for x in rows:
        seen[x[0]] = x
    df = pd.DataFrame([v[:6] for v in seen.values()], columns=["date", "open", "close", "high", "low", "volume"])
    out = df_summary(df, "date")
    out["note"] = f"web.ifzq.gtimg.cn fqkline, 分页 2 年/次(单次≤640 根), fq={fq or 'none'}"
    return out


def quote(symbol: str):
    r = S.get(f"https://qt.gtimg.cn/q={symbol}", timeout=15)
    r.raise_for_status()
    txt = r.content.decode("gbk", errors="replace")
    parts = txt.split("~")
    # v_sh600519="1~贵州茅台~600519~最新价~昨收~今开~成交量(手)~外盘~内盘~买一~买一量~...~时间(30)~..."
    return {"rows": 1 if len(parts) > 30 else 0,
            "columns": ["name", "code", "last", "prev_close", "open", "volume", "...", "time@30"],
            "last_date": parts[30][:8] if len(parts) > 30 else None,
            "note": f"name={parts[1]} last={parts[3]} time={parts[30]}" if len(parts) > 30 else txt[:120]}


def main():
    run_check("tencent", "cn_equity_stock", "daily_history", lambda: kline("sh600519"))
    run_check("tencent", "cn_equity_stock", "latest_quote", lambda: quote("sh600519"))
    run_check("tencent", "cn_equity_etf", "daily_history", lambda: kline("sh510300"))
    run_check("tencent", "cn_convertible_bond", "daily_history", lambda: kline("sh113050", fq=""))
    run_check("tencent", "hk_equity", "daily_history", lambda: kline("hk00700"))
    run_check("tencent", "hk_equity", "latest_quote", lambda: quote("hk00700"))
    run_check("tencent", "hk_etf", "daily_history", lambda: kline("hk02800"))


if __name__ == "__main__":
    main_guard(main)
