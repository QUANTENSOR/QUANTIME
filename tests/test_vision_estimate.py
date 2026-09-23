"""QNT-55 阶段 1 估算脚本的纯函数单测（离线；不触发任何网络请求）。"""

from __future__ import annotations

import datetime as dt
import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "vision_estimate.py"
_spec = importlib.util.spec_from_file_location("vision_estimate", SCRIPT)
ve = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ve)


@pytest.mark.parametrize(
    ("month", "n", "expected"),
    [
        ("2026-08", 1, "2026-09"),
        ("2026-12", 1, "2027-01"),
        ("2020-01", -1, "2019-12"),
        ("2019-09", 83, "2026-08"),
    ],
)
def test_month_add(month, n, expected):
    assert ve.month_add(month, n) == expected


def test_months_inclusive_and_diff():
    assert ve.months_inclusive("2020-01", "2026-08") == 80
    assert ve.months_inclusive("2026-08", "2026-08") == 1
    assert ve.months_inclusive("2026-09", "2026-08") == 0
    assert ve.month_diff("2019-09", "2020-01") == 4


def test_last_complete_month():
    assert ve.last_complete_month(dt.date(2026, 9, 23)) == "2026-08"
    assert ve.last_complete_month(dt.date(2027, 1, 1)) == "2026-12"


@pytest.mark.parametrize("hi", range(0, 12))
def test_first_true_and_last_true_match_linear_scan(hi):
    for edge in range(-1, hi + 2):
        up = [i >= edge for i in range(hi + 1)]  # F…FT…T
        down = [i <= edge for i in range(hi + 1)]  # T…TF…F
        want_first = next((i for i, v in enumerate(up) if v), None)
        want_last = max((i for i, v in enumerate(down) if v), default=None)
        assert ve.first_true(0, hi, lambda i, up=up: up[i]) == want_first
        assert ve.last_true(0, hi, lambda i, down=down: down[i]) == want_last


def test_leveraged_token_requires_existing_root():
    bases = {"BTC", "ETH", "BNB", "EOS", "JUP", "SYRUP", "UP"}
    for base in ("BTCUP", "ETHDOWN", "BNBBULL", "EOSBEAR"):
        assert ve.is_leveraged_token(base, bases)
    for base in ("JUP", "SYRUP", "UP", "BTC"):
        assert not ve.is_leveraged_token(base, bases)


def test_ascii_symbol_filter():
    assert ve.is_ascii_symbol("1000PEPEUSDT")
    assert not ve.is_ascii_symbol("币安人生USDT")
    assert not ve.is_ascii_symbol("btcusdt")
    assert not ve.is_ascii_symbol("BTC/USDT")


def test_download_hours_is_request_bound_for_small_files():
    # 100 万个 1 KB 文件：2e6 请求 × 0.5s / 4 并发 = 250000s，远大于带宽项。
    h = ve.download_hours(
        1_000_000, 1_000_000 * 1024, latency_s=0.5, mbps=20, concurrency=4, min_interval_s=0.2
    )
    assert h == pytest.approx(250_000 / 3600)
    # 节流下限：延迟低于 0.2s 时按 0.2s 计。
    h2 = ve.download_hours(1000, 0, latency_s=0.05, mbps=20, concurrency=1, min_interval_s=0.2)
    assert h2 == pytest.approx(2000 * 0.2 / 3600)


def test_download_hours_is_bandwidth_bound_for_large_files():
    h = ve.download_hours(
        10, 10 * 1024**3, latency_s=0.5, mbps=20, concurrency=1, min_interval_s=0.2
    )
    assert h == pytest.approx(10 * 1024 / 20 / 3600)


def test_parquet_ratios_come_from_recorded_fixtures():
    ratios = ve.parquet_ratios()
    assert set(ratios) == {"spot_1d", "perp_1d", "funding", "metrics"}
    for v in ratios.values():
        assert v["zip_bytes"] > 0 and v["parquet_bytes"] > 0


def test_prober_gate_rejects_non_allowlist_host_before_sending():
    """HEAD 探测复用出口闸：非 allowlist host 在发请求前即被拒。"""
    from quantime_data.transport import TransportBoundaryError

    prober = ve.Prober(1)
    with pytest.raises(TransportBoundaryError):
        prober.head_size("https://s3-ap-northeast-1.amazonaws.com/data.binance.vision/data/x.zip")
    with pytest.raises(TransportBoundaryError):
        prober.head_size("https://data.binance.vision/api/v3/account")
    assert prober.requests == 0
