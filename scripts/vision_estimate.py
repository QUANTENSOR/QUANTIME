#!/usr/bin/env python3
# ruff: noqa: E501  — 报告渲染的中文长字符串，断行只会降低可读性（QNT-55 偏离项）
"""Binance Vision 全量历史的**只读估算**（QNT-55 阶段 1）——不下载任何数据文件、不写 lake。

用法：`uv run --package quantime-data --extra ingest python scripts/vision_estimate.py`

为什么不走 S3 listing：卡面设想的 `data.binance.vision/?prefix=...` 在 CloudFront 上只回
index.html，真正的 listing 由页面 JS 去打 `s3-ap-northeast-1.amazonaws.com`——那个 host
不在 `core/allowlist.py` 里。本脚本因此只用 allowlist 现有 host：

- **现货**：`data-api.binance.vision` 的 `/api/v3/exchangeInfo`（含 `BREAK` = 已下架）给出
  全部 USDT 交易对；逐个 `/api/v3/klines?interval=1M&startTime=0` 给出首/末月——即 Vision
  monthly 1d 文件的精确月数（两条路径都在 `PUBLIC_READONLY_REST_PATHS` 里，走 `PublicTransport`）。
- **永续**：没有 allowlist 内的合约列表来源，只能对 `data.binance.vision` 的归档文件发
  **HEAD**（只取 `Content-Length`，不取正文）。候选 = exchangeInfo 全部 baseAsset ×
  {"", "1000"} + `USDT`（另补 `EXTRA_PERP_CANDIDATES`），在若干锚点月探测存在性，再二分首/末月与 metrics 首/末日。
  **只在永续侧存在、现货从未上过的币种会漏掉**——结果是下界，文档里如实标注。

每个 HEAD 的 URL 在发出前、以及 httpx 规范化之后，各过一遍 `transport.assert_public_readonly_url`
（与 `cli._http_opener` 同一道闸）；不跟随重定向。

Parquet 压缩比来自仓库里 QNT-28 已录制的真实 fixture（本地文件，不出网）。
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import random
import statistics
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "packages" / "data"))
sys.path.insert(0, str(REPO / "packages" / "core"))

from quantime_core.allowlist import BINANCE_VISION_SPOT_MIRROR  # noqa: E402
from quantime_core.parquet_io import table_to_bytes  # noqa: E402
from quantime_data.sources import binance_public as bp  # noqa: E402
from quantime_data.transport import assert_public_readonly_url  # noqa: E402
from quantime_data.universe import load_universe  # noqa: E402

SPOT_API = f"https://{BINANCE_VISION_SPOT_MIRROR.host}/api/v3"
FIXTURES = REPO / "fixtures" / "binance_public"

#: Vision 永续归档最早月份（BTCUSDT 1d 的首个 monthly 文件）。
PERP_EPOCH = "2019-09"
#: 存在性探测锚点月：相邻锚点间整段生命周期 < 间隔的已下架合约会漏检（文档标注）。
PERP_ANCHORS = (
    "2020-06",
    "2021-03",
    "2021-12",
    "2022-09",
    "2023-06",
    "2024-03",
    "2024-12",
    "2025-09",
    "2026-08",
)
PERP_PREFIXES = ("", "1000")
#: 非「baseAsset+USDT」命名、现货无同名 base 的已知永续（指数/改名合约）——手工补入候选。
EXTRA_PERP_CANDIDATES = (
    "BTCDOMUSDT",
    "DEFIUSDT",
    "LUNA2USDT",
    "FOOTBALLUSDT",
    "BLUEBIRDUSDT",
    "BTCSTUSDT",
    "USDCUSDT",
    "ETHWUSDT",
    "TRUMPUSDT",
    "1000000MOGUSDT",
    "1MBABYDOGEUSDT",
    "1000000BOBUSDT",
)
LEVERAGED_SUFFIXES = ("UP", "DOWN", "BULL", "BEAR")
SIZE_SAMPLES = 400
SPLIT_LIMIT_GB = 20.0


# ---------------------------------------------------------------- 纯函数（有单测）


def month_add(month: str, n: int) -> str:
    y, m = map(int, month.split("-"))
    idx = y * 12 + (m - 1) + n
    return f"{idx // 12:04d}-{idx % 12 + 1:02d}"


def month_diff(a: str, b: str) -> int:
    """`b - a`（月数）。"""
    ya, ma = map(int, a.split("-"))
    yb, mb = map(int, b.split("-"))
    return (yb * 12 + mb) - (ya * 12 + ma)


def months_inclusive(first: str, last: str) -> int:
    return max(month_diff(first, last) + 1, 0)


def last_complete_month(today: dt.date) -> str:
    return month_add(f"{today.year:04d}-{today.month:02d}", -1)


def is_leveraged_token(base: str, all_bases: set[str]) -> bool:
    """`BTCUP`/`ETHDOWN`/`BNBBULL`/`EOSBEAR`：去掉后缀后的词根本身也是一个 baseAsset。

    只看后缀会误伤 `JUP`、`SYRUP` 这类普通币，所以要求词根存在。
    """
    return any(base.endswith(s) and base[: -len(s)] in all_bases for s in LEVERAGED_SUFFIXES)


def is_ascii_symbol(symbol: str) -> bool:
    return symbol.isascii() and symbol.isalnum() and symbol.upper() == symbol


def first_true(lo: int, hi: int, pred) -> int | None:
    """`[lo, hi]` 上单调（F…FT…T）谓词的首个 True 下标；全 False 返回 None。"""
    if not pred(hi):
        return None
    while lo < hi:
        mid = (lo + hi) // 2
        if pred(mid):
            hi = mid
        else:
            lo = mid + 1
    return lo


def last_true(lo: int, hi: int, pred) -> int | None:
    """`[lo, hi]` 上单调（T…TF…F）谓词的末个 True 下标；全 False 返回 None。"""
    if not pred(lo):
        return None
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if pred(mid):
            lo = mid
        else:
            hi = mid - 1
    return lo


def download_hours(
    n_files: int,
    total_bytes: int,
    *,
    latency_s: float,
    mbps: float,
    concurrency: int,
    min_interval_s: float,
) -> float:
    """下载时长模型：每个数据文件 = zip + `.CHECKSUM` 两个请求。

    取「带宽上限」与「请求数上限」两者的较大者：Vision 文件多为 KB 级，请求数才是瓶颈。
    每条并发流受 `PublicTransport.MIN_REQUEST_INTERVAL` 节流（每流 ≥ min_interval_s/请求）。
    """
    requests = 2 * n_files
    per_req = max(latency_s, min_interval_s)
    by_requests = requests * per_req / concurrency
    by_bandwidth = total_bytes / (mbps * 1024 * 1024)
    return max(by_requests, by_bandwidth) / 3600


# ---------------------------------------------------------------- 网络（只 allowlist host）


class Prober:
    """HEAD / GET 出口：每个 URL 过两次闸（原串 + httpx 规范化后），不跟随重定向。"""

    def __init__(self, concurrency: int) -> None:
        import httpx

        self._client = httpx.Client(
            timeout=30.0,
            follow_redirects=False,
            headers={
                "User-Agent": "quantime-estimate/0.0 (+https://github.com/QUANTENSOR/QUANTIME)"
            },
            limits=httpx.Limits(max_connections=concurrency),
        )
        self.pool = ThreadPoolExecutor(max_workers=concurrency)
        self.lock = threading.Lock()
        self.requests = 0
        self.latencies: list[float] = []
        self.cache: dict[str, int | None] = {}

    def _send(self, method: str, url: str):
        assert_public_readonly_url(url)
        request = self._client.build_request(method, url)
        assert_public_readonly_url(str(request.url))
        for attempt in range(6):
            t0 = time.monotonic()
            response = self._client.send(request)
            with self.lock:
                self.requests += 1
                self.latencies.append(time.monotonic() - t0)
            if response.status_code in (418, 429, 500, 502, 503, 504):
                time.sleep(min(2**attempt, 30) * (1 + random.random() * 0.1))
                continue
            return response
        raise RuntimeError(f"重试用尽: {url} HTTP {response.status_code}")

    def head_size(self, url: str) -> int | None:
        """存在 → Content-Length；404 → None。"""
        if url in self.cache:
            return self.cache[url]
        response = self._send("HEAD", url)
        if response.status_code == 200:
            size = int(response.headers["content-length"])
        elif response.status_code in (403, 404):
            size = None
        else:
            raise RuntimeError(f"HEAD {url} → HTTP {response.status_code}")
        with self.lock:
            self.cache[url] = size
        return size

    def get_json(self, url: str):
        response = self._send("GET", url)
        response.raise_for_status()
        return response.json()


# ---------------------------------------------------------------- 估算步骤


def spot_leg(prober: Prober, cutoff_month: str) -> dict:
    info = prober.get_json(f"{SPOT_API}/exchangeInfo")
    all_bases = sorted({s["baseAsset"] for s in info["symbols"]})
    base_set = set(all_bases)
    usdt_all = [s for s in info["symbols"] if s["quoteAsset"] == "USDT"]
    usdt = [s for s in usdt_all if is_ascii_symbol(s["symbol"])]
    non_ascii = sorted(s["symbol"] for s in usdt_all if not is_ascii_symbol(s["symbol"]))

    def span(sym: str):
        rows = prober.get_json(f"{SPOT_API}/klines?symbol={sym}&interval=1M&startTime=0&limit=1000")
        if not rows:
            return None
        to_month = lambda ms: dt.datetime.fromtimestamp(ms / 1000, tz=dt.UTC).strftime("%Y-%m")  # noqa: E731
        return to_month(rows[0][0]), to_month(rows[-1][0])

    spans = dict(
        zip(
            [s["symbol"] for s in usdt],
            prober.pool.map(span, [s["symbol"] for s in usdt]),
            strict=True,
        )
    )
    symbols = []
    for s in usdt:
        sp = spans[s["symbol"]]
        if sp is None:
            first = last = None
            n = 0
        else:
            first, last = sp[0], min(sp[1], cutoff_month)
            n = months_inclusive(first, last)
        symbols.append(
            {
                "symbol": s["symbol"],
                "status": s["status"],
                "leveraged_token": is_leveraged_token(s["baseAsset"], base_set),
                "first_month": first,
                "last_month": last,
                "monthly_files": n,
            }
        )
    return {"symbols": symbols, "all_bases": all_bases, "non_ascii": non_ascii}


def perp_leg(
    prober: Prober, bases: list[str], cutoff_month: str, cutoff_day: dt.date
) -> list[dict]:
    # 非 ASCII baseAsset（如中文 meme 币）的 URL 会被出口闸以「百分号编码」拒绝——
    # 这是闸的正确行为，不放宽；此类候选直接排除并在 JSON 里计数。
    candidates = sorted(
        c
        for c in {f"{p}{b}USDT" for b in bases for p in PERP_PREFIXES} | set(EXTRA_PERP_CANDIDATES)
        if is_ascii_symbol(c)
    )

    def kline(sym: str, month: str) -> bool:
        return prober.head_size(bp.kline_url("perp", sym, "1d", month)) is not None

    def anchors(sym: str) -> list[str]:
        # 由新到旧，命中一个即停：二分首/末月只需区间内任一存在点。
        for a in reversed(PERP_ANCHORS):
            if kline(sym, a):
                return [a]
        return []

    hits = dict(zip(candidates, prober.pool.map(anchors, candidates), strict=True))
    found = {s: h for s, h in hits.items() if h}

    def bounds(item):
        sym, hit = item
        lo_i = month_diff(PERP_EPOCH, hit[0])
        first_i = first_true(0, lo_i, lambda i: kline(sym, month_add(PERP_EPOCH, i)))
        hi_i = month_diff(hit[-1], cutoff_month)
        last_i = last_true(0, hi_i, lambda i: kline(sym, month_add(hit[-1], i)))
        first_m = month_add(PERP_EPOCH, first_i)
        last_m = month_add(hit[-1], last_i)
        # metrics：日文件。上游 metrics 区间**不连续**（实测 FTTUSDT/SRMUSDT 在 K 线仍在时
        # metrics 已断档），不能对整段二分——先逐月探测每月 15 日，找到首/末个存在月，
        # 再只在那两个月的边缘二分首/末日；中间缺月按「存在月占比」折算文件数。
        month_list = [month_add(first_m, i) for i in range(months_inclusive(first_m, last_m) + 1)]
        mid_days = [dt.date.fromisoformat(m + "-15") for m in month_list]
        mid_days = [d for d in mid_days if d <= cutoff_day]
        # 串行：`bounds` 本身已跑在 `prober.pool` 上，再向同一池提交会死锁。
        present = [prober.head_size(bp.metrics_url(sym, d)) is not None for d in mid_days]
        m_first_day = m_last_day = None
        present_months = sum(present)
        if present_months:
            i0 = present.index(True)
            i1 = len(present) - 1 - present[::-1].index(True)
            lo0 = mid_days[i0 - 1] if i0 > 0 else dt.date.fromisoformat(month_list[0] + "-01")
            hi1 = mid_days[i1 + 1] if i1 + 1 < len(mid_days) else cutoff_day

            def metric_from(base: dt.date):
                return lambda k: (
                    prober.head_size(bp.metrics_url(sym, base + dt.timedelta(days=k))) is not None
                )

            k0 = first_true(0, (mid_days[i0] - lo0).days, metric_from(lo0))
            k1 = last_true(0, (hi1 - mid_days[i1]).days, metric_from(mid_days[i1]))
            m_first_day = lo0 + dt.timedelta(days=k0)
            m_last_day = mid_days[i1] + dt.timedelta(days=k1)
            span_months = i1 - i0 + 1
            metrics_files = round(
                ((m_last_day - m_first_day).days + 1) * present_months / span_months
            )
        else:
            metrics_files = 0
        f_first = prober.head_size(bp.funding_url(sym, first_m)) is not None
        return {
            "symbol": sym,
            "first_month": first_m,
            "last_month": last_m,
            "active": last_m == cutoff_month,
            "kline_monthly_files": months_inclusive(first_m, last_m),
            "funding_monthly_files": months_inclusive(first_m, last_m),
            "funding_first_month_present": f_first,
            "metrics_first_day": m_first_day.isoformat() if m_first_day else None,
            "metrics_last_day": m_last_day.isoformat() if m_last_day else None,
            "metrics_present_months": present_months,
            "metrics_daily_files": metrics_files,
        }

    return sorted(prober.pool.map(bounds, sorted(found.items())), key=lambda r: r["symbol"])


def sample_sizes(prober: Prober, urls: list[str], rng: random.Random) -> dict:
    picked = rng.sample(urls, min(SIZE_SAMPLES, len(urls))) if urls else []
    sizes = [s for s in prober.pool.map(prober.head_size, picked) if s is not None]
    return {
        "sampled": len(picked),
        "present": len(sizes),
        "mean_bytes": statistics.fmean(sizes) if sizes else 0.0,
        "median_bytes": statistics.median(sizes) if sizes else 0.0,
    }


def parquet_ratios() -> dict:
    """用 QNT-28 已录制的真实 fixture 算「归一化 Parquet 字节 / zip 字节」。"""
    specs = {
        "spot_1d": ("spot-BTCUSDT-1d-2026-08.zip", bp.normalize_klines),
        # 仓库无 UM 1d fixture；K 线 12 列布局与现货一致，借现货 1d 的系数。
        "perp_1d": ("spot-BTCUSDT-1d-2026-08.zip", bp.normalize_klines),
        "funding": ("um-BTCUSDT-fundingRate-2026-08.zip", bp.normalize_funding),
        "metrics": ("um-BTCUSDT-metrics-2026-09-15.zip", bp.normalize_open_interest),
    }
    out = {}
    for key, (name, fn) in specs.items():
        raw = (FIXTURES / name).read_bytes()
        pq = table_to_bytes(fn(raw, symbol="BTCUSDT"))
        out[key] = {
            "fixture": name,
            "zip_bytes": len(raw),
            "parquet_bytes": len(pq),
            "ratio": len(pq) / len(raw),
        }
    return out


# ---------------------------------------------------------------- 汇总与渲染


def build(args) -> dict:
    rng = random.Random(55)
    today = dt.date.fromisoformat(args.date)
    cutoff_month = last_complete_month(today)
    cutoff_day = today - dt.timedelta(days=2)  # Vision 日文件约滞后 1 天
    prober = Prober(args.concurrency)
    t0 = time.monotonic()

    spot = spot_leg(prober, cutoff_month)
    t_spot = time.monotonic() - t0
    perps = perp_leg(prober, spot["all_bases"], cutoff_month, cutoff_day)
    t_perp = time.monotonic() - t0 - t_spot

    spot_listed = [s for s in spot["symbols"] if s["monthly_files"] > 0]
    # 杠杆代币单列、默认不拉：不计入 spot_1d 合计，只在 `spot_leveraged_*` 里报数。
    spot_rows = [s for s in spot_listed if not s["leveraged_token"]]
    spot_lev = [s for s in spot_listed if s["leveraged_token"]]
    spot_urls = [
        bp.kline_url("spot", s["symbol"], "1d", month_add(s["first_month"], i))
        for s in spot_rows
        for i in range(s["monthly_files"])
    ]
    perp_k_urls = [
        bp.kline_url("perp", p["symbol"], "1d", month_add(p["first_month"], i))
        for p in perps
        for i in range(p["kline_monthly_files"])
    ]
    fund_urls = [
        bp.funding_url(p["symbol"], month_add(p["first_month"], i))
        for p in perps
        for i in range(p["funding_monthly_files"])
    ]
    # 抽样范围取首→末日的完整区间（含断档月），存在率抽样会把断档自然折进 `files`；
    # 因此 metrics 的 `files_expected` 是区间天数上限，`files` 才是估值。
    met_urls = [
        bp.metrics_url(p["symbol"], d0 + dt.timedelta(days=i))
        for p in perps
        if p["metrics_first_day"]
        for d0 in [dt.date.fromisoformat(p["metrics_first_day"])]
        for i in range((dt.date.fromisoformat(p["metrics_last_day"]) - d0).days + 1)
    ]

    ratios = parquet_ratios()
    legs = {}
    for key, urls, nsym in (
        ("spot_1d", spot_urls, len(spot_rows)),
        ("perp_1d", perp_k_urls, len(perps)),
        ("funding", fund_urls, len(perps)),
        ("metrics", met_urls, sum(1 for p in perps if p["metrics_daily_files"])),
    ):
        smp = sample_sizes(prober, urls, rng)
        present_rate = smp["present"] / smp["sampled"] if smp["sampled"] else 0.0
        files = round(len(urls) * present_rate)
        zbytes = files * smp["mean_bytes"]
        legs[key] = {
            "symbols": nsym,
            "files_expected": len(urls),
            "sample": smp,
            "sample_present_rate": present_rate,
            "files": files,
            "zip_bytes": round(zbytes),
            "zip_gb": zbytes / 1e9,
            "parquet_ratio": ratios[key]["ratio"],
            "parquet_gb": zbytes * ratios[key]["ratio"] / 1e9,
        }

    latency = statistics.median(prober.latencies)
    total_files = sum(v["files"] for v in legs.values())
    total_bytes = sum(v["zip_bytes"] for v in legs.values())
    timing = []
    for label, lat, mbps in (
        ("measured", latency, 20.0),
        ("20MB/s", latency, 20.0),
        ("50MB/s", latency, 50.0),
    ):
        for conc in (1, 4):
            row = {"tier": label, "concurrency": conc, "latency_s": lat, "mbps": mbps}
            if label == "measured":
                # 实测档：只用 listing 阶段的请求延迟，不设带宽上限（文件 KB 级，带宽不是瓶颈）。
                row["mbps"] = None
                row["hours"] = download_hours(
                    total_files, 0, latency_s=lat, mbps=1.0, concurrency=conc, min_interval_s=0.2
                )
            else:
                row["hours"] = download_hours(
                    total_files,
                    total_bytes,
                    latency_s=lat,
                    mbps=mbps,
                    concurrency=conc,
                    min_interval_s=0.2,
                )
            row["by_leg_hours"] = {
                k: download_hours(
                    v["files"],
                    0 if label == "measured" else v["zip_bytes"],
                    latency_s=lat,
                    mbps=row["mbps"] or 1.0,
                    concurrency=conc,
                    min_interval_s=0.2,
                )
                for k, v in legs.items()
            }
            timing.append(row)

    universe = load_universe()
    fixed_spot = set(universe.leg("spot").symbols)
    fixed_perp = set(universe.leg("perp").symbols)
    spot_set = {s["symbol"] for s in spot_rows}
    perp_set = {p["symbol"] for p in perps}

    return {
        "generated_for": args.date,
        "cutoff_month": cutoff_month,
        "cutoff_day": cutoff_day.isoformat(),
        "method": {
            "spot_symbols": "data-api.binance.vision /api/v3/exchangeInfo（quoteAsset=USDT，含 BREAK）",
            "spot_months": "/api/v3/klines interval=1M startTime=0 首/末根",
            "perp_symbols": f"HEAD 探测候选 {{'', '1000'}}×baseAsset×USDT + EXTRA_PERP_CANDIDATES，锚点月 {list(PERP_ANCHORS)}",
            "perp_bounds": "HEAD 二分 1d monthly 首/末月、metrics daily 首/末日（假设区间连续）",
            "sizes": f"每类随机 {SIZE_SAMPLES} 个文件 HEAD Content-Length 均值 × 文件数",
            "parquet_ratio": "QNT-28 fixture 经 normalize_* + table_to_bytes（zstd-3）/ zip 字节",
            "requests": prober.requests,
            "median_latency_s": latency,
            "elapsed_s": {"spot": t_spot, "perp": t_perp, "total": time.monotonic() - t0},
            "concurrency": args.concurrency,
        },
        "legs": legs,
        "totals": {
            "files": total_files,
            "zip_gb": total_bytes / 1e9,
            "parquet_gb": sum(v["parquet_gb"] for v in legs.values()),
        },
        "timing": timing,
        "parquet_ratios": ratios,
        "spot_non_ascii_excluded": spot["non_ascii"],
        "spot_leveraged_tokens": sorted(s["symbol"] for s in spot_lev),
        "spot_leveraged_monthly_files": sum(s["monthly_files"] for s in spot_lev),
        "spot_status_counts": {
            st: sum(1 for s in spot_rows if s["status"] == st)
            for st in sorted({s["status"] for s in spot_rows})
        },
        "perp_active": sum(1 for p in perps if p["active"]),
        "perp_delisted": sum(1 for p in perps if not p["active"]),
        "perp_funding_first_month_missing": sorted(
            p["symbol"] for p in perps if not p["funding_first_month_present"]
        ),
        "universe_diff": {
            "spot_fixed": len(fixed_spot),
            "spot_full_ex_leveraged": len(spot_set),
            "spot_new": len(spot_set - fixed_spot),
            "spot_fixed_missing": sorted(fixed_spot - spot_set),
            "perp_fixed": len(fixed_perp),
            "perp_full": len(perp_set),
            "perp_new": len(perp_set - fixed_perp),
            "perp_fixed_missing": sorted(fixed_perp - perp_set),
        },
        "spot_symbols": spot["symbols"],
        "perp_symbols": perps,
    }


def render_md(r: dict) -> str:
    L = r["legs"]
    m = r["method"]
    lines = [
        f"# Binance Vision 全量历史估算（{r['generated_for']}，QNT-55 阶段 1）",
        "",
        "> 只读估算：未下载任何数据文件、未写 lake。机器可读版本见同名 `.json`。",
        f"> 截止：monthly 到 `{r['cutoff_month']}`，daily 到 `{r['cutoff_day']}`。",
        f"> 产出脚本：`scripts/vision_estimate.py`（请求 {m['requests']} 次，中位延迟 "
        f"{m['median_latency_s']:.3f}s，并发 {m['concurrency']}，耗时 {m['elapsed_s']['total'] / 60:.1f} min）。",
        "",
        "## 1. 分类汇总",
        "",
        "| 类别 | symbol 数 | 文件数 | 压缩总量 (GB) | 均值/文件 (KB) | Parquet 系数 | 估算 Parquet (GB) |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for k, v in L.items():
        lines.append(
            f"| {k} | {v['symbols']} | {v['files']:,} | {v['zip_gb']:.3f} | "
            f"{v['sample']['mean_bytes'] / 1024:.2f} | {v['parquet_ratio']:.2f} | {v['parquet_gb']:.3f} |"
        )
    t = r["totals"]
    lines += [
        f"| **合计** | — | **{t['files']:,}** | **{t['zip_gb']:.3f}** | — | — | **{t['parquet_gb']:.3f}** |",
        "",
        "文件数 = 按首/末月（日）推出的期望文件数 × 抽样存在率（每类随机 "
        f"{SIZE_SAMPLES} 个 HEAD）。Parquet 系数 = QNT-28 fixture 归一化后 zstd-3 Parquet 字节 / zip 字节"
        "（单文件口径；合并成大分区后系数会更低，此处取保守值）。",
        "",
        "## 2. 下载时长（每个数据文件 = zip + `.CHECKSUM` 两个请求）",
        "",
        "| 档位 | 并发 | 总时长 (h) | spot_1d | perp_1d | funding | metrics |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for row in r["timing"]:
        b = row["by_leg_hours"]
        lines.append(
            f"| {row['tier']} | {row['concurrency']} | {row['hours']:.1f} | {b['spot_1d']:.2f} | "
            f"{b['perp_1d']:.2f} | {b['funding']:.2f} | {b['metrics']:.1f} |"
        )
    lines += [
        "",
        "模型：`max(请求数 × max(延迟, 0.2s 节流) / 并发, 字节 / 带宽)`；延迟一律用本次 listing 实测中位数；"
        "「measured」档不设带宽上限。",
        "**现有 QNT-28 `ingest` 是单线程串行**（`PublicTransport` 每请求 ≥0.2s 节流），不改代码即为「并发 1」行；"
        "4 并发需要阶段 2 在 CLI 层加并发参数（属「CLI 参数」范围，不动 adapter）。",
        "文件均为 KB 级，**瓶颈是请求数而非带宽**——20 MB/s 与 50 MB/s 两档结果几乎相同。",
        "",
        "## 3. 20 GB 拆分",
        "",
    ]
    if t["zip_gb"] <= SPLIT_LIMIT_GB:
        lines.append(
            f"压缩总量 {t['zip_gb']:.2f} GB ≤ {SPLIT_LIMIT_GB:.0f} GB，**无需拆分**，可一批全拉。"
        )
    else:
        keep = {k: v for k, v in L.items() if k != "metrics"}
        lines += [
            f"压缩总量 {t['zip_gb']:.2f} GB > {SPLIT_LIMIT_GB:.0f} GB。首批（剔除 metrics）："
            f"{sum(v['zip_gb'] for v in keep.values()):.2f} GB；剩余 metrics {L['metrics']['zip_gb']:.2f} GB 只列不拉。",
        ]
    u = r["universe_diff"]
    lines += [
        "",
        "## 4. 与 `universe.yaml` 固定清单的差集",
        "",
        "| 腿 | 固定清单 | 全量 | 新增 | 固定清单中全量缺失 |",
        "|---|---:|---:|---:|---|",
        f"| spot（不含杠杆代币） | {u['spot_fixed']} | {u['spot_full_ex_leveraged']} | {u['spot_new']} | {u['spot_fixed_missing'] or '—'} |",
        f"| perp | {u['perp_fixed']} | {u['perp_full']} | {u['perp_new']} | {u['perp_fixed_missing'] or '—'} |",
        "",
        "## 5. 标的构成",
        "",
        f"- 现货 USDT 交易对（不含杠杆代币，计入上表）：{r['universe_diff']['spot_full_ex_leveraged']}"
        f"（状态 {r['spot_status_counts']}）。",
        f"- 杠杆代币（UP/DOWN/BULL/BEAR，已全部下架）{len(r['spot_leveraged_tokens'])} 个 / "
        f"{r['spot_leveraged_monthly_files']} 个月文件，**单列、不计入合计、默认不拉**。",
        f"- 非 ASCII 现货交易对 {r['spot_non_ascii_excluded']}：URL 需百分号编码，出口闸按设计拒绝，**不拉**。",
        f"- UM 永续（探测所得）：{len(r['perp_symbols'])}，其中 {r['perp_active']} 个截至 {r['cutoff_month']} 仍有文件、"
        f"{r['perp_delisted']} 个已下架。",
        f"- 首月 fundingRate 文件缺失的合约：{len(r['perp_funding_first_month_missing'])} 个（funding 月数按 kline 区间估，偏上限）。",
        "",
        "## 6. 局限（估算偏差方向）",
        "",
        "- **永续是下界**：没有 allowlist 内的合约列表来源；只在永续上线、现货从未有过同名 baseAsset 的合约会漏检；"
        "生命周期落在两个锚点月之间（< 9 个月）的已下架合约也会漏检。",
        "- K 线 / funding 区间按连续假设（首→末之间不缺月）；metrics 已逐月探测断档，文件数 = 区间天数 × 抽样存在率。实际缺档留给阶段 2 缺口报告。",
        "- 现货月数来自 REST 1M K 线，与 Vision 目录可能差首/末月各 ±1。",
        "",
    ]
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--date", default=dt.date.today().isoformat())
    ap.add_argument("--concurrency", type=int, default=16)
    ap.add_argument("--out-dir", type=Path, default=REPO / "docs" / "ops")
    args = ap.parse_args(argv)
    result = build(args)
    stem = args.out_dir / f"vision-full-estimate-{args.date}"
    stem.with_suffix(".json").write_text(
        json.dumps(result, indent=1, ensure_ascii=False, sort_keys=True) + "\n"
    )
    stem.with_suffix(".md").write_text(render_md(result))
    print(
        f"wrote {stem}.md / .json — files={result['totals']['files']:,} "
        f"zip={result['totals']['zip_gb']:.2f}GB requests={result['method']['requests']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
