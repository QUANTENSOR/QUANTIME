"""基准输入可复现（ADR-0003 §5.1；本卡不跑性能阈值）。"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
import yaml
from quantime_core import parquet_io

BENCH_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "bench"
sys.path.insert(0, str(BENCH_DIR))

import bench_gen  # noqa: E402

SMALL = dict(symbols=20, days=30)


def test_generator_is_deterministic_for_same_seed():
    a = bench_gen.generate_payload(**SMALL)
    b = bench_gen.generate_payload(**SMALL)
    assert bench_gen.payload_sha256(a) == bench_gen.payload_sha256(b)


def test_generator_differs_for_different_seed():
    a = bench_gen.payload_sha256(bench_gen.generate_payload(seed=1, **SMALL))
    b = bench_gen.payload_sha256(bench_gen.generate_payload(seed=2, **SMALL))
    assert a != b


def test_payload_columns_exclude_provenance():
    # §5.1 (a)：payload 是纯业务列，不含 ADR-0002 provenance 列。
    assert bench_gen.PAYLOAD_COLUMNS == ("symbol", "ts", "open", "high", "low", "close", "volume")
    table = bench_gen.generate_payload(**SMALL)
    assert set(table.column_names).isdisjoint(
        {"source", "source_version", "ingested_at", "run_id", "batch_id"}
    )


def test_ohlc_rules_match_adr_text():
    table = bench_gen.generate_payload(symbols=3, days=40)
    cols = {c: table.column(c).to_pylist() for c in bench_gen.PAYLOAD_COLUMNS}
    days = 40
    for s in range(3):
        for d in range(days):
            i = s * days + d
            assert cols["high"][i] >= max(cols["open"][i], cols["close"][i])
            assert cols["low"][i] <= min(cols["open"][i], cols["close"][i])
            assert cols["volume"][i] > 0
            if d > 0:
                # open = prev_close（§5.1）
                assert cols["open"][i] == pytest.approx(cols["close"][i - 1], rel=0, abs=0)
        # CRYPTO_24_7：连续自然日，无跳日。
        ts = cols["ts"][s * days : (s + 1) * days]
        assert all((ts[k + 1] - ts[k]).days == 1 for k in range(days - 1))


def test_expected_json_matches_full_bench_params_and_sha():
    expected = bench_gen.read_expected()
    assert expected["params"] == {
        "seed": 20260920,
        "symbols": 1000,
        "days": 1260,
        "start": "2021-01-04",
        "freq": "1d",
        "market": "crypto",
        "asset_class": "spot",
    }
    assert expected["row_count"] == 1000 * 1260
    table = bench_gen.generate_payload()
    assert table.num_rows == expected["row_count"]
    assert bench_gen.payload_sha256(table) == expected["payload_sha256"]


def test_cli_two_runs_give_identical_sha_matching_expected():
    """验收：bench_gen.py 两次运行 payload_sha256 相等且等于 EXPECTED.json。"""
    script = str(BENCH_DIR / "bench_gen.py")
    shas = {
        subprocess.run(
            [sys.executable, script, "--print-sha"], capture_output=True, text=True, check=True
        ).stdout.strip()
        for _ in range(2)
    }
    assert len(shas) == 1
    assert shas.pop() == bench_gen.read_expected()["payload_sha256"]


def test_cli_check_expected_exit_code():
    script = str(BENCH_DIR / "bench_gen.py")
    ok = subprocess.run(
        [sys.executable, script, "--check-expected"], capture_output=True, text=True
    )
    assert ok.returncode == 0
    bad = subprocess.run(
        [sys.executable, script, "--check-expected", "--seed", "1"], capture_output=True, text=True
    )
    assert bad.returncode == 1
    assert "MISMATCH" in bad.stdout


def test_vision_zip_is_deterministic_and_offline():
    a = bench_gen.generate_vision_zip(pairs=5, days=3)
    b = bench_gen.generate_vision_zip(pairs=5, days=3)
    assert a == b
    import io
    import zipfile

    with zipfile.ZipFile(io.BytesIO(a)) as zf:
        names = zf.namelist()
        assert len(names) == 5
        first = zf.read(names[0]).decode().strip().split("\n")
        assert len(first) == 3
        assert len(first[0].split(",")) == 12  # Vision 日 K CSV 12 列


def test_factors_yaml_lists_the_twenty_fixed_factors():
    spec = yaml.safe_load((BENCH_DIR / "factors.yaml").read_text(encoding="utf-8"))
    exprs = [f["expr"] for f in spec["factors"]]
    assert exprs == [
        "ret_1",
        "ret_5",
        "ret_20",
        "ma_5/close-1",
        "ma_20/close-1",
        "ma_60/close-1",
        "std_20(ret_1)",
        "std_60(ret_1)",
        "max_20(high)/close-1",
        "min_20(low)/close-1",
        "rsi_14",
        "ts_rank_20(close)",
        "corr_20(close, volume)",
        "skew_20(ret_1)",
        "kurt_20(ret_1)",
        "vol_ratio_5_20",
        "amihud_20",
        "macd_12_26_9",
        "bb_pos_20_2",
        "mom_reversal_20_5",
    ]
    assert len({f["name"] for f in spec["factors"]}) == 20


def test_generated_payload_writes_through_deterministic_writer(tmp_path):
    table = bench_gen.generate_payload(**SMALL)
    sha = parquet_io.write_table(table, tmp_path / "p.parquet", bench_gen.PAYLOAD_COLUMNS)
    assert sha == bench_gen.payload_sha256(table)
