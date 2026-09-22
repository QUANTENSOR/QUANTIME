"""Binance 归档解析（QNT-28）——全部离线，读 `fixtures/binance_public/` 的录制字节。"""

from __future__ import annotations

import datetime as dt
import hashlib
import io
import zipfile
from pathlib import Path

import pytest
from quantime_data.sources import binance_public as bp

FIXTURES = Path(__file__).resolve().parents[3] / "fixtures" / "binance_public"

SPOT_KLINE = FIXTURES / "spot-BTCUSDT-1d-2026-08.zip"
PERP_KLINE = FIXTURES / "um-BTCUSDT-4h-2026-08.zip"
FUNDING = FIXTURES / "um-BTCUSDT-fundingRate-2026-08.zip"
METRICS = FIXTURES / "um-BTCUSDT-metrics-2026-09-15.zip"


def read(path: Path) -> bytes:
    return path.read_bytes()


def csv_body(payload: bytes) -> list[list[str]]:
    """解出 zip 内 CSV 的**数据行**（自动跳过表头）。

    Vision 的归档并不统一：实测同月的现货 K 线**无表头**、USD-M K 线**有表头**。
    测试不能假定其一，否则断言的是 fixture 的偶然形态而不是解析行为。
    """
    with zipfile.ZipFile(io.BytesIO(payload)) as zf:
        rows = zf.read(zf.namelist()[0]).decode().splitlines()
    cells = [r.split(",") for r in rows if r.strip()]
    return cells[1:] if not cells[0][0].lstrip("-").isdigit() else cells


# ---- URL 构造 ----


def test_hosts_all_come_from_the_allowlist():
    """本源的 host 必须逐个是 allowlist 里 `public_readonly=True` 的条目。"""
    from quantime_core.allowlist import assert_public_readonly_host

    for host in bp.HOSTS:
        assert assert_public_readonly_host(host).public_readonly is True


def test_no_mainnet_host_is_reachable_from_this_source():
    """Binance 主 host 不得出现在本源的任何 URL 里（ADR-0003 §9.5：美国节点 451）。"""
    urls = [
        bp.kline_url("spot", "BTCUSDT", "1d", "2026-08"),
        bp.kline_url("perp", "BTCUSDT", "4h", "2026-08"),
        bp.funding_url("BTCUSDT", "2026-08"),
        bp.metrics_url("BTCUSDT", dt.date(2026, 9, 15)),
    ]
    for url in urls:
        assert "//api.binance.com" not in url
        assert "//fapi.binance.com" not in url
        assert url.startswith("https://")


def test_spot_and_perp_klines_use_different_archive_prefixes():
    assert "/data/spot/monthly/klines/" in bp.kline_url("spot", "BTCUSDT", "1d", "2026-08")
    assert "/data/futures/um/monthly/klines/" in bp.kline_url("perp", "BTCUSDT", "1d", "2026-08")


def test_unsupported_freq_is_rejected():
    with pytest.raises(ValueError, match="本卡范围"):
        bp.kline_url("spot", "BTCUSDT", "1m", "2026-08")


def test_unsupported_asset_class_is_rejected():
    with pytest.raises(ValueError, match="只覆盖"):
        bp.kline_url("equity", "BTCUSDT", "1d", "2026-08")


def test_checksum_url_and_parsing():
    url = bp.kline_url("spot", "BTCUSDT", "1d", "2026-08")
    assert bp.checksum_url(url) == url + ".CHECKSUM"
    digest = bp.parse_checksum(read(FIXTURES / "spot-BTCUSDT-1d-2026-08.zip.CHECKSUM"))
    assert digest == hashlib.sha256(read(SPOT_KLINE)).hexdigest()


def test_malformed_checksum_is_rejected():
    with pytest.raises(bp.SourceFormatError):
        bp.parse_checksum(b"not-a-sha  file.zip")
    with pytest.raises(bp.SourceFormatError):
        bp.parse_checksum(b"")


# ---- K 线归一化 ----


def test_spot_klines_normalize_to_the_declared_schema():
    table = bp.normalize_klines(read(SPOT_KLINE), symbol="BTCUSDT")
    assert table.schema == bp.KLINE_SCHEMA
    assert table.num_rows == len(csv_body(read(SPOT_KLINE)))
    assert set(table.column("symbol").to_pylist()) == {"BTCUSDT"}


def test_klines_are_sorted_by_open_time_and_the_ignore_column_is_dropped():
    table = bp.normalize_klines(read(PERP_KLINE), symbol="BTCUSDT")
    times = table.column("open_time").to_pylist()
    assert times == sorted(times)
    assert "ignore" not in table.column_names
    assert table.num_rows == len(csv_body(read(PERP_KLINE)))


def test_kline_ohlc_values_match_the_raw_csv():
    """逐字段对拍 CSV 第一行——归一化不得悄悄改数。"""
    payload = read(SPOT_KLINE)
    body = csv_body(payload)
    first = min(body, key=lambda r: int(r[0]))
    table = bp.normalize_klines(payload, symbol="BTCUSDT")
    row = table.slice(0, 1).to_pylist()[0]
    assert row["open"] == float(first[1])
    assert row["high"] == float(first[2])
    assert row["low"] == float(first[3])
    assert row["close"] == float(first[4])
    assert row["volume"] == float(first[5])
    assert row["trade_count"] == int(first[8])
    assert row["open_time"] == bp._ms_to_utc(first[0])


def test_kline_timestamps_land_in_the_expected_month():
    table = bp.normalize_klines(read(SPOT_KLINE), symbol="BTCUSDT")
    times = table.column("open_time").to_pylist()
    assert all(t.year == 2026 and t.month == 8 for t in times), "毫秒/微秒判别若错，年份会离谱地偏"


# ---- funding ----


def test_funding_normalizes_and_is_sorted():
    table = bp.normalize_funding(read(FUNDING), symbol="BTCUSDT")
    assert table.schema == bp.FUNDING_SCHEMA
    assert table.num_rows == 93, "8h × 31 天（2026-08 录制值）"
    times = table.column("calc_time").to_pylist()
    assert times == sorted(times)
    assert all(t.year == 2026 and t.month == 8 for t in times)
    assert set(table.column("funding_interval_hours").to_pylist()) == {8}


# ---- OI（metrics）----


def test_open_interest_takes_only_the_oi_columns():
    table = bp.normalize_open_interest(read(METRICS), symbol="BTCUSDT")
    assert table.schema == bp.OPEN_INTEREST_SCHEMA
    assert table.num_rows == 288, "5m × 24h"
    assert "count_long_short_ratio" not in table.column_names


def test_open_interest_is_sorted_even_though_upstream_is_not():
    """实测上游 metrics 文件行序是乱的；不排序则确定性 writer 的字节会随上游漂移。"""
    payload = read(METRICS)
    raw_times = [r[0] for r in csv_body(payload)]
    assert raw_times != sorted(raw_times), "fixture 前提变了：上游这份文件已是有序的"

    table = bp.normalize_open_interest(payload, symbol="BTCUSDT")
    times = table.column("create_time").to_pylist()
    assert times == sorted(times)


def test_normalization_is_deterministic_byte_for_byte():
    """同输入 → 同字节（ADR-0003 §4.2 R2 的前提）。"""
    from quantime_core import parquet_io

    payload = read(METRICS)
    a = parquet_io.table_to_bytes(bp.normalize_open_interest(payload, symbol="BTCUSDT"))
    b = parquet_io.table_to_bytes(bp.normalize_open_interest(payload, symbol="BTCUSDT"))
    assert a == b


# ---- 上游布局变化 ----


def _rezip(rows: list[str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("x.csv", "\n".join(rows) + "\n")
    return buf.getvalue()


def test_wrong_column_count_is_rejected_rather_than_misparsed():
    """上游改布局时必须失败——安静地错位解析比失败危险得多。"""
    with pytest.raises(bp.SourceFormatError, match="列数"):
        bp.normalize_klines(_rezip(["1,2,3"]), symbol="BTCUSDT")


def test_headerless_legacy_csv_is_accepted():
    """老文件无表头，新文件有表头，两种都要吃下。"""
    row = "1785542400000,1,2,0.5,3,4,1785628799999,5,6,7,8,0"
    table = bp.normalize_klines(_rezip([row]), symbol="BTCUSDT")
    assert table.num_rows == 1
    assert table.column("close").to_pylist() == [3.0]


def test_zip_with_multiple_csvs_is_rejected():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("a.csv", "1\n")
        zf.writestr("b.csv", "2\n")
    with pytest.raises(bp.SourceFormatError, match="CSV 数量"):
        bp.normalize_klines(buf.getvalue(), symbol="BTCUSDT")
