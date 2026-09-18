"""Probe: 加密 DEX / 链上 / 聚合器 免费公开端点 — CoinGecko(免 key) / DefiLlama / GeckoTerminal / DEX Screener / CoinPaprika / Uniswap 子图(公开网关需 key→不测).

Pure GET. No key. Run: python onchain_dex_crypto.py
"""
from __future__ import annotations

import pandas as pd
import requests

from _common import UA, df_summary, main_guard, run_check

S = requests.Session()
S.headers["User-Agent"] = UA


def coingecko_market_chart(days):
    r = S.get("https://api.coingecko.com/api/v3/coins/bitcoin/market_chart", params={"vs_currency": "usd", "days": days, "interval": "daily"}, timeout=20)
    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code}: {r.text[:200]}")
    df = pd.DataFrame(r.json()["prices"], columns=["ts", "price"])
    df["date"] = pd.to_datetime(df["ts"], unit="ms")
    out = df_summary(df, "date")
    out["note"] = f"days={days} (免 key Demo 层：daily 仅 365 天；>365 需付费 — 见 error/rows)"
    return out


def coingecko_ohlc():
    r = S.get("https://api.coingecko.com/api/v3/coins/bitcoin/ohlc", params={"vs_currency": "usd", "days": 365}, timeout=20)
    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code}: {r.text[:200]}")
    df = pd.DataFrame(r.json(), columns=["ts", "o", "h", "l", "c"])
    df["date"] = pd.to_datetime(df["ts"], unit="ms")
    out = df_summary(df, "date")
    out["note"] = "days=365 时粒度为 4 天 (官方文档)；ratelimit-remaining=" + str(r.headers.get("x-ratelimit-remaining"))
    return out


def coingecko_simple_price():
    r = S.get("https://api.coingecko.com/api/v3/simple/price", params={"ids": "bitcoin,ethereum", "vs_currencies": "usd", "include_last_updated_at": "true"}, timeout=20)
    r.raise_for_status()
    d = r.json()
    return {"rows": len(d), "columns": list(d["bitcoin"].keys()), "note": f"btc={d['bitcoin']['usd']}"}


def defillama_protocol_tvl():
    r = S.get("https://api.llama.fi/v2/historicalChainTvl/Ethereum", timeout=60)
    r.raise_for_status()
    df = pd.DataFrame(r.json())
    df["date"] = pd.to_datetime(df["date"], unit="s")
    out = df_summary(df, "date")
    out["note"] = "Ethereum 链 TVL 日序列 (/protocol/uniswap 全量 JSON 30s 超时，改用链级端点)"
    return out


def defillama_dex_volume():
    r = S.get("https://api.llama.fi/summary/dexs/uniswap", params={"excludeTotalDataChart": "false", "excludeTotalDataChartBreakdown": "true", "dataType": "dailyVolume"}, timeout=30)
    r.raise_for_status()
    df = pd.DataFrame(r.json()["totalDataChart"], columns=["ts", "vol"])
    df["date"] = pd.to_datetime(df["ts"], unit="s")
    out = df_summary(df, "date")
    out["note"] = "Uniswap 日成交量 (DEX 现货)"
    return out


def defillama_derivatives():
    r = S.get("https://api.llama.fi/summary/derivatives/hyperliquid", params={"dataType": "dailyVolume"}, timeout=30)
    r.raise_for_status()
    df = pd.DataFrame(r.json()["totalDataChart"], columns=["ts", "vol"])
    df["date"] = pd.to_datetime(df["ts"], unit="s")
    out = df_summary(df, "date")
    out["note"] = "Hyperliquid 永续 日成交量 (DeFiLlama derivatives)"
    return out


def defillama_prices():
    import time
    pts = []
    start = int(time.time()) - 4 * 365 * 86400
    for _ in range(3):  # 每次最多 500 点（实测 800 → 400 "exceeds the maximum of 500"）
        r = S.get("https://coins.llama.fi/chart/coingecko:bitcoin", params={"start": start, "span": 500, "period": "1d"}, timeout=30)
        r.raise_for_status()
        page = r.json()["coins"]["coingecko:bitcoin"]["prices"]
        if not page:
            break
        pts += page
        start = page[-1]["timestamp"] + 1
    df = pd.DataFrame(pts)
    df["date"] = pd.to_datetime(df["timestamp"], unit="s")
    out = df_summary(df, "date")
    out["note"] = "coins.llama.fi 日价格，span≤500/次 分页"
    return out


def geckoterminal_pool_ohlcv():
    pool = "0x88e6a0c2ddd26feeb64f039a2c41296fcb3f5640"  # Uniswap v3 USDC/WETH 0.05% (ethereum)
    r = S.get(f"https://api.geckoterminal.com/api/v2/networks/eth/pools/{pool}/ohlcv/day", params={"limit": 1000, "currency": "usd"}, headers={"Accept": "application/json;version=20230302"}, timeout=30)
    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code}: {r.text[:200]}")
    rows = r.json()["data"]["attributes"]["ohlcv_list"]
    # 翻页：before_timestamp 取更早数据，验证免费层可回溯深度
    for _ in range(4):
        oldest = min(x[0] for x in rows)
        r2 = S.get(f"https://api.geckoterminal.com/api/v2/networks/eth/pools/{pool}/ohlcv/day", params={"limit": 1000, "currency": "usd", "before_timestamp": oldest - 1}, headers={"Accept": "application/json;version=20230302"}, timeout=30)
        if r2.status_code != 200:
            break
        more = r2.json()["data"]["attributes"]["ohlcv_list"]
        if not more:
            break
        rows += more
    df = pd.DataFrame(rows, columns=["ts", "o", "h", "l", "c", "v"])
    df["date"] = pd.to_datetime(df["ts"], unit="s")
    out = df_summary(df, "date")
    out["note"] = "Uniswap v3 USDC/WETH 池 日 OHLCV；limit 最大 1000（官方）"
    return out


def dexscreener_pair():
    r = S.get("https://api.dexscreener.com/latest/dex/pairs/ethereum/0x88e6a0c2ddd26feeb64f039a2c41296fcb3f5640", timeout=20)
    r.raise_for_status()
    p = r.json()["pairs"][0]
    return {"rows": 1, "columns": list(p.keys())[:16], "note": f"priceUsd={p.get('priceUsd')} vol24h={p.get('volume', {}).get('h24')}；仅当前快照，无历史 OHLCV 公共端点"}


def coinpaprika_ohlcv():
    r = S.get("https://api.coinpaprika.com/v1/coins/btc-bitcoin/ohlcv/historical", params={"start": "2023-09-01", "end": "2026-09-18", "interval": "1d"}, timeout=20)
    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code}: {r.text[:200]}")
    df = pd.DataFrame(r.json())
    df["date"] = pd.to_datetime(df["time_open"])
    out = df_summary(df, "date")
    out["note"] = "免费层 historical 限最近 1 年 (文档)"
    return out


def blockchain_com_charts():
    r = S.get("https://api.blockchain.info/charts/hash-rate", params={"timespan": "4years", "format": "json", "sampled": "false"}, timeout=20)
    r.raise_for_status()
    df = pd.DataFrame(r.json()["values"])
    df["date"] = pd.to_datetime(df["x"], unit="s")
    out = df_summary(df, "date")
    out["note"] = "BTC 链上 hash-rate 日序列"
    return out


def mempool_space():
    r = S.get("https://mempool.space/api/v1/mining/hashrate/3y", timeout=20)
    r.raise_for_status()
    df = pd.DataFrame(r.json()["hashrates"])
    df["date"] = pd.to_datetime(df["timestamp"], unit="s")
    out = df_summary(df, "date")
    out["note"] = "mempool.space 自托管 BTC 节点 API；hashrate 3y"
    return out


def main():
    run_check("coingecko", "crypto_spot_agg", "daily_history_365", lambda: coingecko_market_chart(365))
    run_check("coingecko", "crypto_spot_agg", "daily_history_max", lambda: coingecko_market_chart("max"))
    run_check("coingecko", "crypto_spot_agg", "ohlc", coingecko_ohlc)
    run_check("coingecko", "crypto_spot_agg", "latest_quote", coingecko_simple_price)
    run_check("defillama", "crypto_onchain_tvl", "daily_history", defillama_protocol_tvl)
    run_check("defillama", "crypto_dex_spot_volume", "daily_history", defillama_dex_volume)
    run_check("defillama", "crypto_dex_perp_volume", "daily_history", defillama_derivatives)
    run_check("defillama", "crypto_spot_agg", "daily_history", defillama_prices)
    run_check("geckoterminal", "crypto_dex_spot", "daily_history", geckoterminal_pool_ohlcv)
    run_check("dexscreener", "crypto_dex_spot", "latest_quote", dexscreener_pair)
    run_check("coinpaprika", "crypto_spot_agg", "daily_history", coinpaprika_ohlcv)
    run_check("blockchain_com", "crypto_onchain_btc", "daily_history", blockchain_com_charts)
    run_check("mempool_space", "crypto_onchain_btc", "daily_history", mempool_space)


if __name__ == "__main__":
    main_guard(main)
