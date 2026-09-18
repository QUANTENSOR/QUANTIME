"""Probe: Stooq — CSV 日线下载 (A股 .cn / 港股 .hk / 美股 .us).

Public CSV endpoint, no token. Stooq enforces an undocumented daily download
quota per IP (returns "Exceeded the daily hits limit").
Run: python stooq_cn_hk_us.py
"""
from __future__ import annotations

import io

import pandas as pd
import requests

from _common import UA, df_summary, main_guard, run_check

S = requests.Session()
S.headers["User-Agent"] = UA


def hist(symbol: str):
    r = S.get(f"https://stooq.com/q/d/l/?s={symbol}&i=d", timeout=30)
    r.raise_for_status()
    text = r.text
    if "Exceeded" in text or "No data" in text:
        raise RuntimeError(text.strip()[:200])
    if text.lstrip().startswith("<"):
        # Stooq now fronts CSV downloads with a JavaScript browser-verification page
        raise RuntimeError("HTML instead of CSV (JS browser verification): " + text.strip()[:160].replace("\n", " "))
    df = pd.read_csv(io.StringIO(text))
    out = df_summary(df, "Date")
    out["note"] = f"symbol={symbol}; 仅有(调整后)收盘，无复权因子/成交额"
    return out


def latest(symbol: str):
    r = S.get(f"https://stooq.com/q/l/?s={symbol}&f=sd2t2ohlcv&h&e=csv", timeout=30)
    r.raise_for_status()
    df = pd.read_csv(io.StringIO(r.text))
    out = df_summary(df, "Date")
    out["note"] = r.text.strip().splitlines()[-1][:120]
    return out


def main():
    for sym, mk in [("600519.cn", "cn_equity_stock"), ("510300.cn", "cn_equity_etf"),
                    ("0700.hk", "hk_equity"), ("2800.hk", "hk_etf"), ("spy.us", "us_etf")]:
        run_check("stooq", mk, "daily_history", lambda s=sym: hist(s))
        # latest_quote endpoint (/q/l/) returns 404 from this node; skipped
        # run_check("stooq", mk, "latest_quote", lambda s=sym: latest(s))


if __name__ == "__main__":
    main_guard(main)
