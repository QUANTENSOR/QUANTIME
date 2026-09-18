"""Probe: yfinance — A股 (.SS/.SZ) / 港股 (.HK) 日线历史 + 最新（延迟）行情.

Unofficial Yahoo scraper; no token. Yahoo A-share/HK data is exchange-delayed.
Run: python yfinance_cn_hk_equity.py
"""
from __future__ import annotations

import yfinance as yf

from _common import df_summary, main_guard, run_check


def hist(ticker: str):
    df = yf.Ticker(ticker).history(period="5y", interval="1d", auto_adjust=False)
    out = df_summary(df)
    out["note"] = f"ticker={ticker}"
    return out


def latest(ticker: str):
    t = yf.Ticker(ticker)
    fi = t.fast_info
    px = fi.get("lastPrice") if hasattr(fi, "get") else getattr(fi, "last_price", None)
    df = t.history(period="5d", interval="1d")
    out = df_summary(df.tail(1))
    out["note"] = f"fast_info.lastPrice={px}"
    return out


def main():
    for tk, mk in [("600519.SS", "cn_equity_stock"), ("510300.SS", "cn_equity_etf"),
                   ("113050.SS", "cn_convertible_bond"),
                   ("0700.HK", "hk_equity"), ("2800.HK", "hk_etf")]:
        run_check("yfinance", mk, "daily_history", lambda tk=tk: hist(tk))
        run_check("yfinance", mk, "latest_quote", lambda tk=tk: latest(tk))


if __name__ == "__main__":
    main_guard(main)
