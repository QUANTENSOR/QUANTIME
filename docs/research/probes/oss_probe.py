"""QNT-25 probe: collect license / activity facts for candidate OSS repos.

Read-only. Talks to the public GitHub REST API and PyPI over anonymous HTTP
(stdlib urllib only, no third-party deps, no `gh` CLI).

Auth policy
-----------
The default path is ANONYMOUS. The anonymous GitHub quota is 60 req/h, which is
not enough for 37 repos x commit pagination, so the script optionally reads a
token from the GITHUB_TOKEN environment variable. This script never resolves a
secret reference itself, has no default token, and never falls back to a local
credential store (no `gh auth token`, no `gh api`, no ~/.netrc, no git creds) --
if the injected variable is absent the run is anonymous, nothing else is tried.

Inject the token from 1Password only, via the committed template:

    op run --env-file=docs/research/probes/probe.env.tpl -- \
        python docs/research/probes/oss_probe.py > oss-results.json

or use `scripts/run_probe.sh`, which fails closed with "凭据不可用" when the
vault read fails. GITHUB_TOKEN_SOURCE carries a NON-SECRET provenance label
(the op reference, not the value) into the output's `auth_mode` field; the
secret itself is never printed, written to a file, or placed in the JSON.

Failure policy
--------------
Every failure is classified and printed to stderr: 404 (really absent), 401
(bad credentials), 403 (forbidden / rate-limited, distinguished via the
x-ratelimit-remaining header), other HTTP status, or a network error. A non-404
failure is NEVER recorded as "repo not found". Any failure makes the process
exit non-zero.

Usage
-----
    python docs/research/probes/oss_probe.py > oss-results.json
"""

from __future__ import annotations

import datetime
import json
import os
import sys
import urllib.error
import urllib.request

API = "https://api.github.com"
PYPI = "https://pypi.org/pypi/{}/json"
UA = "quantime-qnt25-probe (+https://github.com/QUANTENSOR/QUANTIME)"

SINCE = (datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=365)).strftime(
    "%Y-%m-%dT%H:%M:%SZ"
)

REPOS = [
    "tradingview/lightweight-charts",
    "klinecharts/KLineChart",
    "perspective-dev/perspective",
    "freqtrade/frequi",
    "OpenBB-finance/OpenBB",
    "ranaroussi/yfinance",
    "databento/databento-python",
    "gerrymanoim/exchange_calendars",
    "dlt-hub/dlt",
    "ccxt/ccxt",
    "docling-project/docling",
    "Unstructured-IO/unstructured",
    "opendatalab/MinerU",
    "chroma-core/chroma",
    "zotero/zotero",
    "paperless-ngx/paperless-ngx",
    "microsoft/qlib",
    "stefan-jansen/alphalens-reloaded",
    "TA-Lib/ta-lib-python",
    "xgboosted/pandas-ta-classic",
    "bukosabino/ta",
    "polakowo/vectorbt",
    "stefan-jansen/zipline-reloaded",
    "QuantConnect/Lean",
    "nautechsystems/nautilus_trader",
    "kernc/backtesting.py",
    "pmorissette/bt",
    "PyPortfolio/PyPortfolioOpt",
    "dcajasn/Riskfolio-Lib",
    "skfolio/skfolio",
    "ranaroussi/quantstats",
    "alpacahq/alpaca-py",
    "hummingbot/hummingbot",
    "freqtrade/freqtrade",
    "jesse-ai/jesse",
    "ib-api-reloaded/ib_async",
    "stefan-jansen/machine-learning-for-trading",
]


class ProbeError(Exception):
    """A classified, non-404 failure. Never means 'the repo does not exist'."""


class NotFound(Exception):
    """HTTP 404 — the resource really is absent."""


FAILURES: list[str] = []


def _token() -> str | None:
    """Optional token from the environment.

    No default, no secret-reference resolution, and deliberately no fallback to
    any local credential store: the only accepted source is an already-injected
    GITHUB_TOKEN (see the module docstring for the op run invocation).
    """
    raw = os.environ.get("GITHUB_TOKEN")
    if raw is None:
        return None
    tok = raw.strip()
    return tok or None


def _token_source() -> str:
    """Non-secret provenance label for the injected token.

    Set by the env template to the op reference (a pointer, never the value).
    Kept out of this file so the repository holds the reference literal only in
    `*.tpl` and documentation.

    The template stores the label with a single-colon `op:` prefix because
    `op run` would otherwise try to resolve a full `op://...` value as a secret
    and abort; it is normalised back to `op://` here purely for display.
    """
    src = (os.environ.get("GITHUB_TOKEN_SOURCE") or "").strip()
    if not src:
        return "unspecified-source"
    if src.startswith("op:") and not src.startswith("op://"):
        src = "op://" + src[len("op:") :]
    return src


def _request(url: str, token: str | None) -> tuple[object, object]:
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": UA,
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.load(r), r.headers
    except urllib.error.HTTPError as e:
        # NOTE: keep the HTTPMessage object. GitHub sends "X-RateLimit-Remaining"
        # capitalised and dict(...) lookups are case-SENSITIVE, which would
        # silently misclassify every rate-limit 403 as a plain "forbidden".
        hdrs = e.headers
        if e.code == 404:
            raise NotFound(url) from e
        if e.code == 401:
            raise ProbeError(f"HTTP 401 bad credentials for {url} — GITHUB_TOKEN rejected") from e
        if e.code == 403:
            remaining = hdrs.get("x-ratelimit-remaining") if hdrs else None
            reset = hdrs.get("x-ratelimit-reset") if hdrs else None
            if remaining == "0":
                when = (
                    datetime.datetime.fromtimestamp(int(reset), datetime.UTC).isoformat()
                    if reset
                    else "unknown"
                )
                raise ProbeError(
                    f"HTTP 403 rate-limited for {url} — quota exhausted, resets {when}. "
                    "Anonymous quota is 60 req/h; set GITHUB_TOKEN to raise it."
                ) from e
            raise ProbeError(f"HTTP 403 forbidden for {url} (not rate-limit)") from e
        raise ProbeError(f"HTTP {e.code} for {url}") from e
    except urllib.error.URLError as e:
        raise ProbeError(f"network error for {url}: {e.reason}") from e
    except (TimeoutError, json.JSONDecodeError) as e:
        raise ProbeError(f"transport/parse error for {url}: {e}") from e


def _parse_link_last(headers) -> int | None:
    """Extract the last page number from a Link header, if present.

    `headers` is an HTTPMessage (case-insensitive lookup), not a plain dict.
    """
    link = headers.get("Link")
    if not link:
        return None
    for part in link.split(","):
        if 'rel="last"' in part:
            seg = part.split(";")[0].strip().strip("<>")
            for kv in seg.split("?", 1)[-1].split("&"):
                if kv.startswith("page="):
                    return int(kv.split("=", 1)[1])
    return None


PER_PAGE = 100


def commits_1y(repo: str, token: str | None) -> int:
    """Exact commit count on the default branch over the last 365 days.

    Uses two requests instead of walking every page: GitHub paginates
    deterministically at per_page=100, so with `last` from the Link header the
    total is (last - 1) * 100 + len(last page). Keeps the probe inside a
    realistic request budget.
    """
    url = f"{API}/repos/{repo}/commits?since={SINCE}&per_page={PER_PAGE}&page=1"
    first, headers = _request(url, token)
    last = _parse_link_last(headers)
    if last is None or last == 1:
        return len(first)
    tail_url = f"{API}/repos/{repo}/commits?since={SINCE}&per_page={PER_PAGE}&page={last}"
    tail, _ = _request(tail_url, token)
    return (last - 1) * PER_PAGE + len(tail)


def pypi(pkg: str) -> dict | None:
    """PyPI metadata. Absent packages return None; other failures are recorded."""
    try:
        data, _ = _pypi_request(PYPI.format(pkg))
    except NotFound:
        return None
    except ProbeError as e:
        FAILURES.append(f"pypi {pkg}: {e}")
        print(f"  FAIL pypi {pkg}: {e}", file=sys.stderr)
        return None
    info = data["info"]
    version = info["version"]
    files = data["releases"].get(version, [])
    return {
        "package": pkg,
        "version": version,
        "requires_python": info.get("requires_python"),
        "python_classifiers": sorted(
            c.split("::")[-1].strip()
            for c in info.get("classifiers", [])
            if "Programming Language :: Python :: 3." in c
        ),
        "wheel_tags": sorted(
            {f["filename"].split("-")[2] for f in files if f["packagetype"] == "bdist_wheel"}
        ),
        "has_sdist": any(f["packagetype"] == "sdist" for f in files),
    }


def _pypi_request(url: str) -> tuple[dict, object]:
    req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.load(r), r.headers
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise NotFound(url) from e
        raise ProbeError(f"HTTP {e.code} for {url}") from e
    except urllib.error.URLError as e:
        raise ProbeError(f"network error for {url}: {e.reason}") from e


def probe_repo(repo: str, token: str | None) -> dict:
    try:
        meta, _ = _request(f"{API}/repos/{repo}", token)
    except NotFound:
        print(f"  ABSENT {repo}: HTTP 404 — repository does not exist", file=sys.stderr)
        return {"repo": repo, "status": "absent_404"}
    except ProbeError as e:
        FAILURES.append(f"repo {repo}: {e}")
        print(f"  FAIL {repo}: {e}", file=sys.stderr)
        return {"repo": repo, "status": "probe_failed", "error": str(e)}

    row: dict = {
        "repo": meta["full_name"],
        "status": "ok",
        "spdx": (meta.get("license") or {}).get("spdx_id"),
        "license_name": (meta.get("license") or {}).get("name"),
        "pushed_at": meta.get("pushed_at"),
        "stars": meta.get("stargazers_count"),
        "archived": meta.get("archived"),
    }

    try:
        row["commits_1y"] = commits_1y(repo, token)
    except (NotFound, ProbeError) as e:
        FAILURES.append(f"commits {repo}: {e}")
        print(f"  FAIL commits {repo}: {e}", file=sys.stderr)
        row["commits_1y"] = None
        row["commits_error"] = str(e)

    try:
        rel, _ = _request(f"{API}/repos/{repo}/releases/latest", token)
        row["latest_release"] = rel.get("tag_name")
        row["released_at"] = rel.get("published_at")
    except NotFound:
        row["latest_release"] = None
        row["released_at"] = None
    except ProbeError as e:
        FAILURES.append(f"release {repo}: {e}")
        print(f"  FAIL release {repo}: {e}", file=sys.stderr)
        row["latest_release"] = None
        row["release_error"] = str(e)

    return row


# PyPI distributions referenced by the document, keyed by repo.
PYPI_FOR_REPO = {
    "polakowo/vectorbt": "vectorbt",
    "pmorissette/bt": "bt",
    "stefan-jansen/zipline-reloaded": "zipline-reloaded",
    "nautechsystems/nautilus_trader": "nautilus_trader",
    "kernc/backtesting.py": "backtesting",
    "microsoft/qlib": "pyqlib",
    "skfolio/skfolio": "skfolio",
    "PyPortfolio/PyPortfolioOpt": "pyportfolioopt",
    "dcajasn/Riskfolio-Lib": "Riskfolio-Lib",
    "stefan-jansen/alphalens-reloaded": "alphalens-reloaded",
    "ranaroussi/quantstats": "quantstats",
    "alpacahq/alpaca-py": "alpaca-py",
    "gerrymanoim/exchange_calendars": "exchange-calendars",
    "databento/databento-python": "databento",
    "TA-Lib/ta-lib-python": "ta-lib",
    "xgboosted/pandas-ta-classic": "pandas-ta-classic",
    "bukosabino/ta": "ta",
    "dlt-hub/dlt": "dlt",
    "ccxt/ccxt": "ccxt",
    "ranaroussi/yfinance": "yfinance",
    "jesse-ai/jesse": "jesse",
}


def main() -> int:
    token = _token()
    auth_mode = f"token({_token_source()})" if token else "anonymous"
    print(f"auth_mode={auth_mode}  since={SINCE}  repos={len(REPOS)}", file=sys.stderr)
    if not token:
        print(
            "  note: anonymous GitHub quota is 60 req/h; this probe needs more. "
            "Set GITHUB_TOKEN if you hit HTTP 403 rate-limit.",
            file=sys.stderr,
        )

    rows = []
    for repo in REPOS:
        rows.append(probe_repo(repo, token))

    dists = {}
    for repo, pkg in sorted(PYPI_FOR_REPO.items()):
        meta = pypi(pkg)
        if meta:
            dists[repo] = meta

    json.dump(
        {
            "probed_at": datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "since": SINCE,
            "auth_mode": auth_mode,
            "commits_1y_method": (
                "GET /repos/{repo}/commits?since=<now-365d>&per_page=100; exact count via "
                "the Link rel=last page number plus the final page length "
                "((last-1)*100 + len(last)); default branch, merge commits included"
            ),
            "failures": FAILURES,
            "repos": rows,
            "pypi": dists,
        },
        sys.stdout,
        indent=2,
        ensure_ascii=False,
        sort_keys=False,
    )
    print()

    if FAILURES:
        print(f"\n{len(FAILURES)} failure(s); results are INCOMPLETE:", file=sys.stderr)
        for f in FAILURES:
            print(f"  - {f}", file=sys.stderr)
        return 1
    print("all probes OK", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
