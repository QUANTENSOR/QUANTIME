"""Shared helpers for data-source probes.

Every probe is a *read-only* GET/SDK pull against a free public endpoint:
no account registration, no order placement, no remote state written.

A probe prints one JSON line per check via `report()` so the results can be
aggregated by `run_all.py`. Fields:
  source, market, check ("daily_history" | "latest_quote"), ok, elapsed_s,
  rows, first_date, last_date, columns, needs_token, error, note
"""
from __future__ import annotations

import json
import sys
import time
import traceback
from contextlib import contextmanager
from typing import Any

MIN_HISTORY_YEARS = 3
UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0 Safari/537.36"
)


def report(**fields: Any) -> None:
    fields.setdefault("ok", False)
    fields.setdefault("needs_token", False)
    print("PROBE " + json.dumps(fields, ensure_ascii=False, default=str), flush=True)


@contextmanager
def timed():
    t0 = time.perf_counter()
    box: dict[str, float] = {}
    try:
        yield box
    finally:
        box["elapsed_s"] = round(time.perf_counter() - t0, 3)


def run_check(source: str, market: str, check: str, fn, **extra: Any) -> dict | None:
    """Run `fn()`; it must return a dict with rows/first_date/last_date/columns."""
    t0 = time.perf_counter()
    try:
        out = fn() or {}
    except Exception as exc:  # noqa: BLE001 - we want the raw error text
        elapsed = round(time.perf_counter() - t0, 3)
        err = f"{type(exc).__name__}: {exc}"
        tb = traceback.format_exc(limit=1).strip().splitlines()[-1]
        report(source=source, market=market, check=check, ok=False,
               elapsed_s=elapsed, error=err[:400], tb=tb[:200], **extra)
        return None
    elapsed = round(time.perf_counter() - t0, 3)
    ok = bool(out.get("rows", 0) > 0) and not out.get("error")
    report(source=source, market=market, check=check, ok=ok, elapsed_s=elapsed,
           **{**extra, **out})
    return out


def df_summary(df, date_col: str | None = None) -> dict:
    """Summarise a pandas DataFrame (rows, first/last date, columns)."""
    import pandas as pd  # local import keeps probes that don't need pandas light

    if df is None or len(df) == 0:
        return {"rows": 0, "columns": list(getattr(df, "columns", []))}
    cols = [str(c) for c in df.columns]
    dates = None
    if date_col and date_col in df.columns:
        dates = pd.to_datetime(df[date_col], errors="coerce")
    elif isinstance(df.index, pd.DatetimeIndex):
        dates = df.index.to_series()
    else:
        for c in df.columns:
            if str(c).lower() in ("date", "datetime", "trade_date", "day", "time", "日期", "净值日期", "timestamp"):
                dates = pd.to_datetime(df[c], errors="coerce")
                break
    out: dict[str, Any] = {"rows": int(len(df)), "columns": cols}
    if dates is not None and dates.notna().any():
        out["first_date"] = str(dates.min().date())
        out["last_date"] = str(dates.max().date())
        span_years = (dates.max() - dates.min()).days / 365.25
        out["span_years"] = round(span_years, 2)
        out["meets_3y"] = span_years >= MIN_HISTORY_YEARS
    return out


def years_ago(n: int) -> str:
    import datetime as dt

    return (dt.date.today() - dt.timedelta(days=365 * n)).strftime("%Y%m%d")


def main_guard(fn):
    try:
        fn()
    except KeyboardInterrupt:
        sys.exit(130)
