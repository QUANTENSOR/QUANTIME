"""Probe: 新浪财经 — A股/可转债/港股 实时快照 (hq.sinajs.cn, 需 Referer) + 日线历史 (money.finance.sina.com.cn).

Since 2021-10 hq.sinajs.cn returns 403 without a `Referer: https://finance.sina.com.cn` header.
No token.
Run: python sina_cn_equity.py
"""
from __future__ import annotations

import requests
import pandas as pd

from _common import UA, df_summary, main_guard, run_check

S = requests.Session()
S.headers.update({"User-Agent": UA, "Referer": "https://finance.sina.com.cn"})


def quote(symbol: str):
    r = S.get(f"https://hq.sinajs.cn/list={symbol}", timeout=15)
    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code}: {r.text[:120]}")
    txt = r.content.decode("gbk", errors="replace")
    parts = txt.split('"')[1].split(",") if '"' in txt else []
    return {"rows": 1 if len(parts) > 10 else 0,
            "columns": ["name", "open", "prev_close", "last", "high", "low", "bid", "ask", "volume", "amount", "b1v", "b1p", "...", "date", "time"],
            "last_date": parts[30] if len(parts) > 31 else None,
            "note": f"name={parts[0]} last={parts[3]} date={parts[30] if len(parts) > 31 else '?'}" if parts else txt[:120]}


def kline(symbol: str, datalen: int = 1023):
    # 新浪日线：单次最多 1023 根，无起止日期参数（只能取最近 N 根）
    url = ("https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData"
           f"?symbol={symbol}&scale=240&ma=no&datalen={datalen}")
    r = S.get(url, timeout=20)
    r.raise_for_status()
    df = pd.DataFrame(r.json())
    out = df_summary(df, "day")
    out["note"] = "单次上限 datalen=1023，无日期区间参数；复权需另取 复权因子"
    return out


def cb_kline(symbol: str):
    url = ("https://quotes.sina.cn/cn/api/json_v2.php/CN_MarketDataService.getKLineData"
           f"?symbol={symbol}&scale=240&ma=no&datalen=1023")
    r = S.get(url, timeout=20)
    r.raise_for_status()
    df = pd.DataFrame(r.json())
    return df_summary(df, "day")


def hk_kline(symbol: str):
    url = f"https://finance.sina.com.cn/stock/hkstock/{symbol}/klc_kl.js"
    r = S.get(url, timeout=20)
    r.raise_for_status()
    return {"rows": 1 if len(r.content) > 100 else 0, "columns": ["compressed js blob"],
            "note": f"bytes={len(r.content)}; 需 akshare 内置解码，未在本探针解压"}


def main():
    run_check("sina", "cn_equity_stock", "latest_quote", lambda: quote("sh600519"))
    run_check("sina", "cn_equity_stock", "daily_history", lambda: kline("sh600519"))
    run_check("sina", "cn_equity_etf", "daily_history", lambda: kline("sh510300"))
    run_check("sina", "cn_convertible_bond", "latest_quote", lambda: quote("sh113050"))
    run_check("sina", "cn_convertible_bond", "daily_history", lambda: cb_kline("sh113050"))
    run_check("sina", "hk_equity", "latest_quote", lambda: quote("rt_hk00700"))
    run_check("sina", "hk_equity", "daily_history", lambda: hk_kline("00700"))


if __name__ == "__main__":
    main_guard(main)
