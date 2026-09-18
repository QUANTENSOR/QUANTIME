"""Probe: 国内交易所官网公开数据直连 (SSE / SZSE / BSE / SHFE / INE / DCE / CZCE / GFEX / CFFEX / HKEX).

Pure GET reachability + one daily-data endpoint each. No token.
Records raw error text when the site is unreachable / WAF-blocked from this node.
Run: python exchange_sites_cn.py
"""
from __future__ import annotations

import datetime as dt

import requests

from _common import UA, main_guard, run_check

S = requests.Session()
S.headers["User-Agent"] = UA


def _last_weekday(offset_days: int = 1) -> dt.date:
    d = dt.date.today() - dt.timedelta(days=offset_days)
    while d.weekday() >= 5:
        d -= dt.timedelta(days=1)
    return d


D = _last_weekday(1)
YMD = D.strftime("%Y%m%d")


def get(url: str, **kw):
    r = S.get(url, timeout=20, **kw)
    body = r.content
    return {"rows": 1 if r.status_code == 200 and len(body) > 50 else 0,
            "columns": [f"HTTP {r.status_code}", f"{len(body)} bytes", r.headers.get("content-type", "")[:40]],
            "note": (url[:100] + (" | " + body[:120].decode("utf-8", "replace").replace("\n", " ") if r.status_code != 200 else "")),
            "error": None if r.status_code == 200 else f"HTTP {r.status_code}"}


ENDPOINTS = {
    # 上交所 ETF/股票 日行情 (JSONP)
    "sse": ("cn_equity", "https://yunhq.sse.com.cn:32042/v1/sh1/dayk/600519?begin=-30&end=-1", {"Referer": "https://www.sse.com.cn/"}),
    "szse": ("cn_equity", "https://www.szse.cn/api/market/ssjjhq/getHistory?random=0.1&cycleType=32&marketId=1&code=000001", {"Referer": "https://www.szse.cn/"}),
    "bse": ("cn_equity", "https://www.bse.cn/nqhqController/nqhq.do?xxfcbj=2&page=0&xxzqdm=920001", {"Referer": "https://www.bse.cn/"}),
    # 期货交易所 日行情文件
    "shfe": ("cn_futures", f"https://www.shfe.com.cn/data/tradedata/future/dailydata/kx{YMD}.dat", {"Referer": "https://www.shfe.com.cn/"}),
    "ine": ("cn_futures", f"https://www.ine.cn/data/dailydata/kx/kx{YMD}.dat", {"Referer": "https://www.ine.cn/"}),
    "dce": ("cn_futures", "http://www.dce.com.cn/publicweb/quotesdata/dayQuotesCh.html", {}),
    "czce": ("cn_futures", f"http://www.czce.com.cn/cn/DFSStaticFiles/Future/{D.year}/{YMD}/FutureDataDaily.htm", {}),
    "gfex": ("cn_futures", "http://www.gfex.com.cn/gfex/rihq/hqsj_tjsj.shtml", {}),
    "cffex": ("cn_futures_index", f"http://www.cffex.com.cn/sj/historysj/{D.strftime('%Y%m')}/zip/{D.strftime('%Y%m')}.zip", {}),
    # 港交所 每日报价
    "hkex_dq": ("hk_equity", f"https://www.hkex.com.hk/eng/stat/smstat/dayquot/d{D.strftime('%y%m%d')}e.htm", {}),
    "hkex_home": ("hk_equity", "https://www.hkex.com.hk/?sc_lang=en", {}),
}


def main():
    for name, (mk, url, hdrs) in ENDPOINTS.items():
        run_check(f"exchange_site_{name}", mk, "reachability", lambda u=url, h=hdrs: get(u, headers=h))


if __name__ == "__main__":
    main_guard(main)
