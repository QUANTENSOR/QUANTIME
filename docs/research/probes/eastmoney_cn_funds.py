"""Probe: 天天基金 (东方财富) — 公募基金 净值历史 / 实时估值 / 持仓 / 费率.

Endpoints: fund.eastmoney.com/pingzhongdata/<code>.js (全量净值 JS blob),
api.fund.eastmoney.com/f10/lsjz (分页净值, 需 Referer),
fundgz.1234567.com.cn/js/<code>.js (盘中估值), fundf10.eastmoney.com (持仓/费率 HTML).
No token. Also runs the AKShare wrappers for the same data.
Run: python eastmoney_cn_funds.py
"""
from __future__ import annotations

import json
import re

import pandas as pd
import requests

from _common import UA, df_summary, main_guard, run_check

S = requests.Session()
S.headers.update({"User-Agent": UA, "Referer": "https://fundf10.eastmoney.com/"})
CODE = "110011"  # 易方达优质精选混合(QDII)


def pingzhong_nav():
    r = S.get(f"https://fund.eastmoney.com/pingzhongdata/{CODE}.js", timeout=30)
    r.raise_for_status()
    m = re.search(r"var Data_netWorthTrend\s*=\s*(\[.*?\]);", r.text)
    if not m:
        raise RuntimeError("Data_netWorthTrend not found; bytes=%d" % len(r.content))
    arr = json.loads(m.group(1))
    df = pd.DataFrame(arr)
    df["date"] = pd.to_datetime(df["x"], unit="ms")
    out = df_summary(df, "date")
    out["columns"] = ["x(ms)", "y(单位净值)", "equityReturn", "unitMoney(分红)"]
    out["note"] = "全量单位净值 + 累计净值(Data_ACWorthTrend) + 分红在同一 JS 文件"
    return out


def lsjz_page():
    r = S.get("https://api.fund.eastmoney.com/f10/lsjz",
              params={"fundCode": CODE, "pageIndex": 1, "pageSize": 20}, timeout=30)
    r.raise_for_status()
    js = r.json()
    items = (js.get("Data") or {}).get("LSJZList") or []
    df = pd.DataFrame(items)
    out = df_summary(df, "FSRQ")
    out["note"] = f"TotalCount={js.get('TotalCount')} (分页可拉全量)"
    return out


def realtime_estimate():
    r = S.get(f"https://fundgz.1234567.com.cn/js/{CODE}.js", timeout=20)
    r.raise_for_status()
    m = re.search(r"jsonpgz\((\{.*\})\)", r.text)
    d = json.loads(m.group(1)) if m else {}
    return {"rows": 1 if d else 0, "columns": list(d.keys()),
            "last_date": d.get("jzrq"), "note": f"gsz={d.get('gsz')} gztime={d.get('gztime')} (盘中估值, 非官方净值)"}


def akshare_nav():
    import akshare as ak

    df = ak.fund_open_fund_info_em(symbol=CODE, indicator="单位净值走势")
    return df_summary(df, "净值日期")


def akshare_holdings():
    import akshare as ak

    df = ak.fund_portfolio_hold_em(symbol=CODE, date="2025")
    out = df_summary(df)
    out["note"] = "季报重仓股（东财 F10）"
    return out


def akshare_fee():
    import akshare as ak

    df = ak.fund_fee_em(symbol=CODE, indicator="认购费率")
    out = df_summary(df)
    return out


def akshare_dividend():
    import akshare as ak

    df = ak.fund_fh_em()
    out = df_summary(df)
    out["note"] = "全市场分红列表（东财）"
    return out


def main():
    run_check("eastmoney_fund", "cn_fund_nav", "daily_history", pingzhong_nav)
    run_check("eastmoney_fund", "cn_fund_nav", "daily_history_paged", lsjz_page)
    run_check("eastmoney_fund", "cn_fund_nav", "latest_quote", realtime_estimate)
    run_check("akshare", "cn_fund_nav", "daily_history", akshare_nav, upstream="eastmoney")
    run_check("akshare", "cn_fund_holdings", "snapshot", akshare_holdings, upstream="eastmoney")
    run_check("akshare", "cn_fund_fee", "snapshot", akshare_fee, upstream="eastmoney")
    run_check("akshare", "cn_fund_dividend", "snapshot", akshare_dividend, upstream="eastmoney")


if __name__ == "__main__":
    main_guard(main)
