"""Probe: 加密 CEX 公共行情端点直连 (无 key) — 现货 + 永续 日线历史 ≥3 年 + 最新 ticker.

Exchanges: Binance (api + data.binance.vision), OKX, Bybit, Bitget, Coinbase Exchange,
Kraken spot + futures, Deribit, Hyperliquid, dYdX v4 Indexer, Gate.
Also funding-rate / open-interest history endpoints where public.
Pure GET/POST-read; nothing signed. Run: python cex_public_crypto.py
"""
from __future__ import annotations

import datetime as dt
import io
import time
import zipfile

import pandas as pd
import requests

from _common import UA, df_summary, main_guard, run_check

S = requests.Session()
S.headers["User-Agent"] = UA
NOW_MS = int(time.time() * 1000)
THREE_Y_MS = NOW_MS - 3 * 365 * 86400 * 1000


def _ts_df(rows, ts_idx=0, unit="ms", cols=None):
    df = pd.DataFrame(rows)
    if cols:
        df.columns = cols[: df.shape[1]] + list(df.columns[len(cols):])
    df["date"] = pd.to_datetime(pd.to_numeric(df.iloc[:, ts_idx]), unit=unit)
    return df


def _paginate_desc(fetch, max_pages=8):
    """fetch(before_ms) -> list rows ; concatenates pages walking backwards."""
    out = []
    cursor = None
    for _ in range(max_pages):
        page = fetch(cursor)
        if not page:
            break
        out += page
        cursor = min(int(r[0]) for r in page) - 1
        if cursor < THREE_Y_MS:
            break
    return out


# ---------------- Binance ----------------
def binance_rest(host: str, path: str):
    r = S.get(f"https://{host}{path}", params={"symbol": "BTCUSDT", "interval": "1d", "limit": 1000}, timeout=15)
    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code}: {r.text[:200]}")
    df = _ts_df(r.json(), cols=["open_time", "open", "high", "low", "close", "volume", "close_time", "quote_vol", "trades", "tb_base", "tb_quote", "ignore"])
    return df_summary(df, "date")


def binance_vision_monthly(kind: str):
    # 月度 zip：spot / um 永续 日线
    ym = (dt.date.today().replace(day=1) - dt.timedelta(days=1)).strftime("%Y-%m")
    base = "https://data.binance.vision/data/"
    path = {"spot": f"spot/monthly/klines/BTCUSDT/1d/BTCUSDT-1d-{ym}.zip",
            "um": f"futures/um/monthly/klines/BTCUSDT/1d/BTCUSDT-1d-{ym}.zip",
            "um_funding": f"futures/um/monthly/fundingRate/BTCUSDT/BTCUSDT-fundingRate-{ym}.zip",
            "um_metrics": f"futures/um/daily/metrics/BTCUSDT/BTCUSDT-metrics-{(dt.date.today()-dt.timedelta(days=2)).isoformat()}.zip"}[kind]
    r = S.get(base + path, timeout=30)
    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code} for {path}")
    z = zipfile.ZipFile(io.BytesIO(r.content))
    name = z.namelist()[0]
    df = pd.read_csv(z.open(name), header=None)
    first = str(df.iloc[0, 0])
    if first.replace(".", "").isalpha() or "time" in first.lower():
        df = pd.read_csv(z.open(name))
    out = {"rows": int(len(df)), "columns": [str(c) for c in df.columns][:12], "note": f"{path} ({len(r.content)} bytes)"}
    return out


def binance_vision_index():
    r = S.get("https://s3-ap-northeast-1.amazonaws.com/data.binance.vision", params={"delimiter": "/", "prefix": "data/futures/um/monthly/klines/BTCUSDT/1d/"}, timeout=30)
    r.raise_for_status()
    keys = [k.split("<Key>")[1].split("</Key>")[0] for k in r.text.split("<Contents>")[1:]]
    zips = [k for k in keys if k.endswith(".zip")]
    return {"rows": len(zips), "columns": ["S3 ListObjects keys"], "first_date": zips[0].rsplit("-", 2)[-2] if zips else None,
            "last_date": zips[-1].rsplit("-", 2)[-2] if zips else None, "note": f"first={zips[0] if zips else None}"}


# ---------------- OKX ----------------
def okx_candles(inst: str):
    def fetch(after):
        p = {"instId": inst, "bar": "1Dutc", "limit": 100}
        if after:
            p["after"] = after
        r = S.get("https://www.okx.com/api/v5/market/history-candles", params=p, timeout=15)
        r.raise_for_status()
        js = r.json()
        if js.get("code") != "0":
            raise RuntimeError(js)
        return js["data"]
    rows = _paginate_desc(fetch, max_pages=14)
    df = _ts_df(rows, cols=["ts", "o", "h", "l", "c", "vol", "volCcy", "volCcyQuote", "confirm"])
    out = df_summary(df, "date")
    out["note"] = f"{inst} history-candles 100/次 分页"
    return out


def okx_ticker(inst: str):
    r = S.get("https://www.okx.com/api/v5/market/ticker", params={"instId": inst}, timeout=15)
    r.raise_for_status()
    d = r.json()["data"][0]
    return {"rows": 1, "columns": list(d.keys()), "note": f"last={d['last']} ts={d['ts']}"}


def okx_funding_history():
    r = S.get("https://www.okx.com/api/v5/public/funding-rate-history", params={"instId": "BTC-USDT-SWAP", "limit": 100}, timeout=15)
    r.raise_for_status()
    df = _ts_df(r.json()["data"], ts_idx=None or 0) if False else pd.DataFrame(r.json()["data"])
    df["date"] = pd.to_datetime(pd.to_numeric(df["fundingTime"]), unit="ms")
    out = df_summary(df, "date")
    out["note"] = "100/次，可用 after 翻页"
    return out


def okx_oi_history():
    r = S.get("https://www.okx.com/api/v5/rubik/stat/contracts/open-interest-history", params={"instId": "BTC-USDT-SWAP", "period": "1D", "limit": 100}, timeout=15)
    r.raise_for_status()
    js = r.json()
    if js.get("code") != "0":
        raise RuntimeError(js)
    df = _ts_df(js["data"], cols=["ts", "oi", "oiCcy", "oiUsd"])
    return df_summary(df, "date")


# ---------------- Bybit ----------------
def bybit_kline(category: str):
    def fetch(end):
        p = {"category": category, "symbol": "BTCUSDT", "interval": "D", "limit": 1000}
        if end:
            p["end"] = end
        r = S.get("https://api.bybit.com/v5/market/kline", params=p, timeout=15)
        if r.status_code != 200:
            raise RuntimeError(f"HTTP {r.status_code}: {r.text[:200]}")
        return r.json()["result"]["list"]
    rows = _paginate_desc(fetch, max_pages=3)
    df = _ts_df(rows, cols=["ts", "o", "h", "l", "c", "vol", "turnover"])
    return df_summary(df, "date")


def bybit_public_csv_index():
    r = S.get("https://public.bybit.com/trading/BTCUSDT/", timeout=20)
    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code}: {r.text[:200]}")
    files = [x.split('"')[0] for x in r.text.split('href="')[1:] if x.startswith("BTCUSDT")]
    return {"rows": len(files), "columns": ["csv.gz files"], "first_date": files[0][8:18] if files else None,
            "last_date": files[-1][8:18] if files else None, "note": "public.bybit.com/trading/ 逐笔成交 日文件"}


# ---------------- Bitget ----------------
def bitget_candles():
    def fetch(end):
        p = {"symbol": "BTCUSDT", "productType": "USDT-FUTURES", "granularity": "1D", "limit": 200}
        if end:
            p["endTime"] = end
        r = S.get("https://api.bitget.com/api/v2/mix/market/history-candles", params=p, timeout=15)
        r.raise_for_status()
        js = r.json()
        if js.get("code") != "00000":
            raise RuntimeError(js)
        return js["data"]
    rows = _paginate_desc(fetch, max_pages=8)
    df = _ts_df(rows, cols=["ts", "o", "h", "l", "c", "baseVol", "quoteVol"])
    return df_summary(df, "date")


# ---------------- Coinbase ----------------
def coinbase_candles():
    rows = []
    end = dt.datetime.now(dt.timezone.utc)
    for _ in range(5):
        start = end - dt.timedelta(days=300)
        r = S.get("https://api.exchange.coinbase.com/products/BTC-USD/candles",
                  params={"granularity": 86400, "start": start.isoformat(), "end": end.isoformat()}, timeout=15)
        r.raise_for_status()
        rows += r.json()
        end = start
    df = _ts_df(rows, unit="s", cols=["time", "low", "high", "open", "close", "volume"])
    out = df_summary(df, "date")
    out["note"] = "300 根/次，分页"
    return out


def coinbase_ticker():
    r = S.get("https://api.exchange.coinbase.com/products/BTC-USD/ticker", timeout=15)
    r.raise_for_status()
    d = r.json()
    return {"rows": 1, "columns": list(d.keys()), "note": f"price={d.get('price')} time={d.get('time')}"}


# ---------------- Kraken ----------------
def kraken_ohlc():
    r = S.get("https://api.kraken.com/0/public/OHLC", params={"pair": "XBTUSD", "interval": 1440, "since": 0}, timeout=15)
    r.raise_for_status()
    js = r.json()
    key = [k for k in js["result"] if k != "last"][0]
    df = _ts_df(js["result"][key], unit="s", cols=["time", "o", "h", "l", "c", "vwap", "vol", "count"])
    out = df_summary(df, "date")
    out["note"] = "Kraken OHLC 最多返回最近 720 根（官方限制），日线≈2 年"
    return out


def kraken_futures_tickers():
    r = S.get("https://futures.kraken.com/derivatives/api/v3/tickers", timeout=15)
    r.raise_for_status()
    t = [x for x in r.json()["tickers"] if x.get("symbol") == "PF_XBTUSD"]
    return {"rows": len(t), "columns": list(t[0].keys()) if t else [], "note": f"PF_XBTUSD last={t[0].get('last') if t else None} fundingRate={t[0].get('fundingRate') if t else None}"}


def kraken_futures_candles():
    to = int(time.time())
    r = S.get("https://futures.kraken.com/api/charts/v1/trade/PF_XBTUSD/1d", params={"from": to - 4 * 365 * 86400, "to": to}, timeout=15)
    r.raise_for_status()
    df = pd.DataFrame(r.json()["candles"])
    df["date"] = pd.to_datetime(pd.to_numeric(df["time"]), unit="ms")
    return df_summary(df, "date")


# ---------------- Deribit ----------------
def deribit_chart():
    end = NOW_MS
    r = S.get("https://www.deribit.com/api/v2/public/get_tradingview_chart_data",
              params={"instrument_name": "BTC-PERPETUAL", "start_timestamp": THREE_Y_MS - 365 * 86400000, "end_timestamp": end, "resolution": "1D"}, timeout=20)
    r.raise_for_status()
    res = r.json()["result"]
    df = pd.DataFrame({k: res[k] for k in ["ticks", "open", "high", "low", "close", "volume"]})
    df["date"] = pd.to_datetime(df["ticks"], unit="ms")
    return df_summary(df, "date")


def deribit_ticker():
    r = S.get("https://www.deribit.com/api/v2/public/ticker", params={"instrument_name": "BTC-PERPETUAL"}, timeout=15)
    r.raise_for_status()
    d = r.json()["result"]
    return {"rows": 1, "columns": list(d.keys()), "note": f"last={d.get('last_price')} funding_8h={d.get('funding_8h')} OI={d.get('open_interest')}"}


def deribit_option_summary():
    r = S.get("https://www.deribit.com/api/v2/public/get_book_summary_by_currency", params={"currency": "BTC", "kind": "option"}, timeout=20)
    r.raise_for_status()
    df = pd.DataFrame(r.json()["result"])
    out = df_summary(df)
    out["note"] = "当前全部 BTC 期权合约汇总（mark_iv/OI/volume），无历史链快照端点"
    return out


# ---------------- Hyperliquid ----------------
def hl_candles():
    r = S.post("https://api.hyperliquid.xyz/info", json={"type": "candleSnapshot", "req": {"coin": "BTC", "interval": "1d", "startTime": THREE_Y_MS - 365 * 86400000, "endTime": NOW_MS}}, timeout=20)
    r.raise_for_status()
    df = pd.DataFrame(r.json())
    df["date"] = pd.to_datetime(df["t"], unit="ms")
    out = df_summary(df, "date")
    out["note"] = "candleSnapshot 最多 5000 根（官方）"
    return out


def hl_meta():
    r = S.post("https://api.hyperliquid.xyz/info", json={"type": "metaAndAssetCtxs"}, timeout=20)
    r.raise_for_status()
    meta, ctxs = r.json()
    i = [k for k, u in enumerate(meta["universe"]) if u["name"] == "BTC"][0]
    d = ctxs[i]
    return {"rows": 1, "columns": list(d.keys()), "note": f"BTC markPx={d.get('markPx')} funding={d.get('funding')} OI={d.get('openInterest')}"}


# ---------------- dYdX ----------------
def dydx_candles():
    rows = []
    to = dt.datetime.now(dt.timezone.utc)
    for _ in range(12):
        r = S.get("https://indexer.dydx.trade/v4/candles/perpetualMarkets/BTC-USD", params={"resolution": "1DAY", "limit": 100, "toISO": to.isoformat()}, timeout=15)
        r.raise_for_status()
        c = r.json()["candles"]
        if not c:
            break
        rows += c
        to = dt.datetime.fromisoformat(c[-1]["startedAt"].replace("Z", "+00:00")) - dt.timedelta(seconds=1)
    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["startedAt"])
    out = df_summary(df, "date")
    out["note"] = "dYdX v4 主网 2023-10 上线，历史天然 <3 年"
    return out


# ---------------- Gate ----------------
def gate_candles():
    r = S.get("https://api.gateio.ws/api/v4/futures/usdt/candlesticks", params={"contract": "BTC_USDT", "interval": "1d", "limit": 2000}, timeout=15)
    r.raise_for_status()
    df = pd.DataFrame(r.json())
    df["date"] = pd.to_datetime(df["t"], unit="s")
    return df_summary(df, "date")


def main():
    run_check("binance", "crypto_spot", "daily_history", lambda: binance_rest("api.binance.com", "/api/v3/klines"))
    run_check("binance", "crypto_perp", "daily_history", lambda: binance_rest("fapi.binance.com", "/fapi/v1/klines"))
    run_check("binance_us", "crypto_spot", "daily_history", lambda: binance_rest("api.binance.us", "/api/v3/klines"))
    run_check("binance_vision", "crypto_spot", "monthly_zip", lambda: binance_vision_monthly("spot"))
    run_check("binance_vision", "crypto_perp", "monthly_zip", lambda: binance_vision_monthly("um"))
    run_check("binance_vision", "crypto_perp_funding", "monthly_zip", lambda: binance_vision_monthly("um_funding"))
    run_check("binance_vision", "crypto_perp_metrics_oi", "daily_zip", lambda: binance_vision_monthly("um_metrics"))
    run_check("binance_vision", "crypto_perp", "history_depth_index", binance_vision_index)
    run_check("okx", "crypto_spot", "daily_history", lambda: okx_candles("BTC-USDT"))
    run_check("okx", "crypto_perp", "daily_history", lambda: okx_candles("BTC-USDT-SWAP"))
    run_check("okx", "crypto_perp", "latest_quote", lambda: okx_ticker("BTC-USDT-SWAP"))
    run_check("okx", "crypto_perp_funding", "history", okx_funding_history)
    run_check("okx", "crypto_perp_oi", "history", okx_oi_history)
    run_check("bybit", "crypto_perp", "daily_history", lambda: bybit_kline("linear"))
    run_check("bybit", "crypto_spot", "daily_history", lambda: bybit_kline("spot"))
    run_check("bybit_public", "crypto_perp", "bulk_csv_index", bybit_public_csv_index)
    run_check("bitget", "crypto_perp", "daily_history", bitget_candles)
    run_check("coinbase", "crypto_spot", "daily_history", coinbase_candles)
    run_check("coinbase", "crypto_spot", "latest_quote", coinbase_ticker)
    run_check("kraken", "crypto_spot", "daily_history", kraken_ohlc)
    run_check("kraken_futures", "crypto_perp", "daily_history", kraken_futures_candles)
    run_check("kraken_futures", "crypto_perp", "latest_quote", kraken_futures_tickers)
    run_check("deribit", "crypto_perp", "daily_history", deribit_chart)
    run_check("deribit", "crypto_perp", "latest_quote", deribit_ticker)
    run_check("deribit", "crypto_option", "chain_snapshot", deribit_option_summary)
    run_check("hyperliquid", "crypto_perp_dex", "daily_history", hl_candles)
    run_check("hyperliquid", "crypto_perp_dex", "latest_quote", hl_meta)
    run_check("dydx_v4", "crypto_perp_dex", "daily_history", dydx_candles)
    run_check("gate", "crypto_perp", "daily_history", gate_candles)


if __name__ == "__main__":
    main_guard(main)
