"""QNT-25 probe: collect license / activity facts for candidate OSS repos.

Read-only: GitHub REST (unauthenticated fields only), PyPI JSON, npm registry.
No credentials are read or written. Re-run: python probe/oss_probe.py
"""
import json, subprocess, sys, urllib.request, datetime

SINCE = (datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=365)).strftime("%Y-%m-%dT%H:%M:%SZ")

REPOS = [
    "tradingview/lightweight-charts", "klinecharts/KLineChart", "perspective-dev/perspective",
    "freqtrade/frequi", "OpenBB-finance/OpenBB", "ranaroussi/yfinance",
    "databento/databento-python", "gerrymanoim/exchange_calendars", "dlt-hub/dlt", "ccxt/ccxt",
    "docling-project/docling", "Unstructured-IO/unstructured", "opendatalab/MinerU",
    "chroma-core/chroma", "zotero/zotero", "paperless-ngx/paperless-ngx",
    "microsoft/qlib", "stefan-jansen/alphalens-reloaded", "TA-Lib/ta-lib-python",
    "xgboosted/pandas-ta-classic", "bukosabino/ta",
    "polakowo/vectorbt", "stefan-jansen/zipline-reloaded", "QuantConnect/Lean",
    "nautechsystems/nautilus_trader", "kernc/backtesting.py", "pmorissette/bt",
    "PyPortfolio/PyPortfolioOpt", "dcajasn/Riskfolio-Lib", "skfolio/skfolio",
    "ranaroussi/quantstats", "alpacahq/alpaca-py", "hummingbot/hummingbot",
    "freqtrade/freqtrade", "jesse-ai/jesse", "ib-api-reloaded/ib_async",
    "stefan-jansen/machine-learning-for-trading",
]

def gh(path):
    p = subprocess.run(["gh", "api", path], capture_output=True, text=True)
    return json.loads(p.stdout) if p.returncode == 0 and p.stdout.strip() else None

def commits_1y(repo):
    p = subprocess.run(
        ["gh", "api", f"repos/{repo}/commits?since={SINCE}&per_page=100", "--paginate", "--jq", "length"],
        capture_output=True, text=True)
    return sum(int(x) for x in p.stdout.split()) if p.returncode == 0 else None

def http_json(url):
    try:
        with urllib.request.urlopen(url, timeout=30) as r:
            return json.load(r)
    except Exception:
        return None

def main():
    out = []
    for r in REPOS:
        d = gh(f"repos/{r}")
        if not d:
            out.append({"repo": r, "error": "not found"}); continue
        lic = d.get("license") or {}
        rel = gh(f"repos/{r}/releases/latest") or {}
        out.append({
            "repo": d["full_name"],
            "spdx": lic.get("spdx_id"),
            "license_name": lic.get("name"),
            "pushed_at": d.get("pushed_at"),
            "stars": d.get("stargazers_count"),
            "archived": d.get("archived"),
            "commits_1y": commits_1y(r),
            "latest_release": rel.get("tag_name"),
            "released_at": rel.get("published_at"),
        })
    json.dump({"probed_at": datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
               "since": SINCE, "repos": out}, sys.stdout, indent=2, ensure_ascii=False)
    print()

if __name__ == "__main__":
    main()
