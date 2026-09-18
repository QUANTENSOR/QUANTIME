"""Probe: 美股免费公开源 — yfinance / Stooq / Cboe CDN / Nasdaq Trader 目录 / SEC EDGAR / FRED(无 key CSV) / Nasdaq.com 非官方.

补 QNT-2/QNT-3 未实测的免费源。需 token 的 (Alpha Vantage / Polygon-Massive / Tiingo / Alpaca / FRED API key)
不注册、不探测，只在文档中标 "需 owner 提供 token，未实测"。
Run: python free_public_us.py
"""
from __future__ import annotations

import io

import pandas as pd
import requests

from _common import UA, df_summary, main_guard, run_check

S = requests.Session()
S.headers["User-Agent"] = UA


def yf_history(sym: str):
    import yfinance as yf

    df = yf.Ticker(sym).history(period="5y", auto_adjust=False)
    out = df_summary(df.reset_index(), "Date")
    out["note"] = f"{sym} period=5y auto_adjust=False (含 Dividends/Stock Splits 列)"
    return out


def yf_quote(sym: str):
    import yfinance as yf

    t = yf.Ticker(sym)
    fi = t.fast_info
    last = t.history(period="5d").tail(1)
    return {"rows": int(len(last)), "columns": list(fi.keys())[:12],
            "last_date": str(last.index[-1].date()) if len(last) else None,
            "note": f"{sym} fast_info.last_price={fi.get('last_price')} history(5d).close={float(last['Close'].iloc[-1]) if len(last) else None}"}


def yf_options(sym: str):
    import yfinance as yf

    t = yf.Ticker(sym)
    exps = t.options
    ch = t.option_chain(exps[0])
    df = pd.concat([ch.calls.assign(cp="C"), ch.puts.assign(cp="P")])
    out = df_summary(df)
    out["note"] = f"{sym} 当前到期日数={len(exps)} first_exp={exps[0]}；仅当前链快照，无历史"
    return out


def stooq_us():
    r = S.get("https://stooq.com/q/d/l/", params={"s": "spy.us", "i": "d"}, timeout=20)
    if r.text.lstrip().startswith("<"):
        raise RuntimeError(f"HTML instead of CSV (JS browser verification / access denied): {r.text[:120]!r}")
    df = pd.read_csv(io.StringIO(r.text))
    return df_summary(df, "Date")


def cboe_vix_history():
    r = S.get("https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv", timeout=20)
    r.raise_for_status()
    df = pd.read_csv(io.StringIO(r.text))
    out = df_summary(df, "DATE")
    out["note"] = "Cboe CDN 官方 VIX 日 OHLC 全历史 CSV"
    return out


def cboe_pc_ratio():
    r = S.get("https://cdn.cboe.com/resources/options/volume_and_call_put_ratios/totalpc.csv", timeout=20)
    r.raise_for_status()
    df = pd.read_csv(io.StringIO(r.text), skiprows=2)
    out = df_summary(df, df.columns[0])
    out["note"] = "Cboe 全市场 put/call 比率 历史 CSV"
    return out


def cboe_delayed_options(sym: str):
    r = S.get(f"https://cdn.cboe.com/api/global/delayed_quotes/options/{sym}.json", timeout=20)
    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code}: {r.text[:150]}")
    js = r.json()
    opts = js.get("data", {}).get("options", [])
    df = pd.DataFrame(opts)
    out = df_summary(df)
    out["note"] = f"{sym} 延迟期权链快照 (bid/ask/iv/greeks/OI)，非正式接口；timestamp={js.get('timestamp')}"
    return out


def nasdaq_trader_symdir(name: str):
    r = S.get(f"https://www.nasdaqtrader.com/dynamic/SymDir/{name}", timeout=20)
    r.raise_for_status()
    lines = r.text.strip().splitlines()
    df = pd.read_csv(io.StringIO("\n".join(lines[:-1])), sep="|")
    out = df_summary(df)
    out["note"] = f"{name} 尾行={lines[-1][:60]!r}（当前快照，无历史）"
    return out


def sec_company_tickers():
    h = {"User-Agent": "quantime-research probe (research@quantime.local)"}
    r = S.get("https://www.sec.gov/files/company_tickers.json", headers=h, timeout=20)
    r.raise_for_status()
    df = pd.DataFrame(r.json()).T
    out = df_summary(df)
    out["note"] = "SEC 官方 ticker→CIK 映射；必须带公司名+邮箱 UA"
    return out


def sec_companyfacts():
    h = {"User-Agent": "quantime-research probe (research@quantime.local)"}
    r = S.get("https://data.sec.gov/api/xbrl/companyfacts/CIK0000320193.json", headers=h, timeout=30)
    r.raise_for_status()
    facts = r.json()["facts"]["us-gaap"]
    # 取 USD 单位下 fact 最多的收入类概念（Revenues 在 2018 后被 RevenueFromContract... 取代）
    cands = [k for k in facts if k in ("Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax", "Assets")]
    concept = max(cands, key=lambda k: len(facts[k]["units"].get("USD", [])))
    df = pd.DataFrame(facts[concept]["units"]["USD"])
    out = df_summary(df, "filed")
    out["note"] = f"AAPL companyfacts concept={concept}；每条 fact 含 accn/filed/frame → point-in-time 可重放"
    return out


def fred_csv(series: str):
    # 实测：浏览器 UA 会被 fred.stlouisfed.org 挂起直至超时；python-requests 默认 UA 反而 0.05s 返回
    r = requests.get("https://fred.stlouisfed.org/graph/fredgraph.csv", params={"id": series}, timeout=60)
    r.raise_for_status()
    df = pd.read_csv(io.StringIO(r.text))
    out = df_summary(df, df.columns[0])
    out["note"] = f"{series} 无 key CSV（非正式接口；正式 API 需 api_key，未注册）；浏览器 UA 超时/默认 UA 正常"
    return out


def nasdaq_com_historical(sym: str):
    h = {"Accept": "application/json", "Origin": "https://www.nasdaq.com", "Referer": "https://www.nasdaq.com/"}
    r = S.get(f"https://api.nasdaq.com/api/quote/{sym}/historical",
              params={"assetclass": "stocks", "fromdate": "2016-01-01", "limit": 9999}, headers=h, timeout=20)
    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code}: {r.text[:150]}")
    rows = r.json()["data"]["tradesTable"]["rows"]
    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"])
    out = df_summary(df, "date")
    out["note"] = "nasdaq.com 非官方 JSON（无条款授权，仅对照）"
    return out


def main():
    run_check("yfinance", "us_equity", "daily_history", lambda: yf_history("SPY"), upstream="yahoo")
    run_check("yfinance", "us_equity", "daily_history_stock", lambda: yf_history("AAPL"), upstream="yahoo")
    run_check("yfinance", "us_equity", "latest_quote", lambda: yf_quote("SPY"), upstream="yahoo")
    run_check("yfinance", "us_option", "chain_snapshot", lambda: yf_options("SPY"), upstream="yahoo")
    run_check("stooq", "us_equity", "daily_history", stooq_us)
    run_check("cboe_cdn", "us_index_vix", "daily_history", cboe_vix_history)
    run_check("cboe_cdn", "us_option_market_stats", "daily_history", cboe_pc_ratio)
    run_check("cboe_cdn", "us_option", "chain_snapshot", lambda: cboe_delayed_options("SPY"))
    run_check("nasdaq_trader", "us_reference", "symbol_directory", lambda: nasdaq_trader_symdir("nasdaqlisted.txt"))
    run_check("nasdaq_trader", "us_reference", "symbol_directory_other", lambda: nasdaq_trader_symdir("otherlisted.txt"))
    run_check("sec_edgar", "us_fundamentals", "ticker_map", sec_company_tickers)
    run_check("sec_edgar", "us_fundamentals", "companyfacts_history", sec_companyfacts)
    run_check("fred", "us_rates", "daily_history", lambda: fred_csv("DGS3MO"))
    run_check("nasdaq_com", "us_equity", "daily_history", lambda: nasdaq_com_historical("AAPL"))


if __name__ == "__main__":
    main_guard(main)
