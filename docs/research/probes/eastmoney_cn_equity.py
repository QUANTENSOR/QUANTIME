"""Probe: 东方财富 push2/push2his 直连 — A股/ETF/可转债/港股 日线历史 + 实时快照.

Raw undocumented endpoints (what AKShare / efinance wrap). No token.
Known issue from this US node: push2his.eastmoney.com closes the TCP connection
without response (RemoteDisconnected) — likely geo/WAF. We also try
push2delay.eastmoney.com (delayed) which does answer.
Run: python eastmoney_cn_equity.py
"""
from __future__ import annotations

import requests
import pandas as pd

from _common import UA, df_summary, main_guard, run_check

S = requests.Session()
S.headers["User-Agent"] = UA
FIELDS2 = "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61"
COLS = ["date", "open", "close", "high", "low", "volume", "amount", "amplitude", "pct_chg", "chg", "turnover"]


def kline(host: str, secid: str, beg: str = "20220101", fqt: int = 1):
    url = f"https://{host}/api/qt/stock/kline/get"
    params = {"secid": secid, "fields1": "f1,f2,f3,f4,f5,f6", "fields2": FIELDS2,
              "klt": 101, "fqt": fqt, "beg": beg, "end": "20500101"}
    r = S.get(url, params=params, timeout=20)
    r.raise_for_status()
    kl = (r.json().get("data") or {}).get("klines") or []
    df = pd.DataFrame([x.split(",") for x in kl], columns=COLS)
    out = df_summary(df, "date")
    out["note"] = f"host={host} secid={secid} fqt={fqt}"
    return out


def snapshot(secid: str):
    url = "https://push2.eastmoney.com/api/qt/stock/get"
    params = {"secid": secid, "fields": "f43,f44,f45,f46,f47,f48,f57,f58,f60,f86,f169,f170", "invt": 2, "fltt": 2}
    r = S.get(url, params=params, timeout=20)
    r.raise_for_status()
    d = r.json().get("data") or {}
    return {"rows": 1 if d else 0, "columns": list(d.keys()),
            "note": f"{d.get('f58')} last(f43)={d.get('f43')} ts(f86)={d.get('f86')}"}


def main():
    for secid, mk in [("1.600519", "cn_equity_stock"), ("1.510300", "cn_equity_etf"),
                      ("1.113050", "cn_convertible_bond"), ("116.00700", "hk_equity")]:
        run_check("eastmoney", mk, "daily_history", lambda s=secid: kline("push2his.eastmoney.com", s))
        run_check("eastmoney", mk, "daily_history_delayhost", lambda s=secid: kline("push2delay.eastmoney.com", s))
        run_check("eastmoney", mk, "latest_quote", lambda s=secid: snapshot(s))


if __name__ == "__main__":
    main_guard(main)
