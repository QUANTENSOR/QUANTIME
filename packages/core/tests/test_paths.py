"""路径规范枚举与构造/解析（ADR-0003 §4.1）。"""

from __future__ import annotations

import pytest
from quantime_core.ids import InvalidIdError, is_valid_id, new_batch_id, new_run_id
from quantime_core.paths import (
    PROVENANCE_COLUMNS,
    AssetClass,
    DataType,
    Freq,
    Market,
    MetaTable,
    PathSpecError,
    lake_batch_dir,
    meta_batch_dir,
    parse_lake_batch_dir,
    raw_batch_dir,
    run_manifest_path,
    source_of_batch_dir,
    staging_dir,
)

BATCH = "01JBXQ8Z0000000000000000AA"


def test_freq_uses_vision_1mo_not_rest_1M():
    # §4.1：周期命名统一用 Vision 口径 1mo，不用 REST 的 1M。
    assert Freq.MO1.value == "1mo"
    assert "1M" not in {f.value for f in Freq}


def test_enum_members_match_adr_text():
    assert {m.value for m in Market} == {"crypto", "us", "cn", "hk"}
    assert {a.value for a in AssetClass} == {
        "spot",
        "perp",
        "delivery",
        "equity",
        "etf",
        "option",
        "future",
        "fund",
    }
    assert {d.value for d in DataType} == {
        "kline",
        "trade",
        "agg_trade",
        "funding",
        "open_interest",
        "mark_price",
        "book_depth",
        "nav",
        "dividend",
        "corp_action",
    }


def test_provenance_columns_are_adr_0002_five():
    assert PROVENANCE_COLUMNS == ("source", "source_version", "ingested_at", "run_id", "batch_id")


def test_lake_batch_dir_roundtrip():
    p = lake_batch_dir("crypto", "spot", "kline", "1d", "BTCUSDT", "synthetic_bench", BATCH)
    assert p.as_posix() == (
        f"data/lake/crypto/spot/kline/1d/BTCUSDT/source=synthetic_bench/batch={BATCH}"
    )
    spec = parse_lake_batch_dir(p)
    assert spec.market is Market.CRYPTO
    assert spec.source == "synthetic_bench"
    assert spec.batch_id == BATCH
    assert spec.part(0).name == "part-0000.parquet"


def test_parse_rejects_unknown_enum_value():
    bad = f"data/lake/mars/spot/kline/1d/BTCUSDT/source=s/batch={BATCH}"
    with pytest.raises(PathSpecError):
        parse_lake_batch_dir(bad)


def test_parse_rejects_missing_partition_components():
    with pytest.raises(PathSpecError):
        parse_lake_batch_dir("data/lake/crypto/spot/kline/1d/BTCUSDT/synthetic/batch=x")


def test_source_of_batch_dir():
    p = lake_batch_dir("crypto", "spot", "kline", "1d", "BTCUSDT", "synthetic_bench", BATCH)
    assert source_of_batch_dir(p) == "synthetic_bench"
    with pytest.raises(PathSpecError):
        source_of_batch_dir("data/meta/ingestion_batch/batch=" + BATCH)


def test_ingestion_batch_is_the_only_meta_table_without_source_partition():
    p = meta_batch_dir(MetaTable.INGESTION_BATCH, BATCH)
    assert p.as_posix() == f"data/meta/ingestion_batch/batch={BATCH}"
    with pytest.raises(PathSpecError, match="无 source"):
        meta_batch_dir(MetaTable.INGESTION_BATCH, BATCH, source="binance")
    with pytest.raises(PathSpecError, match="必须带 source"):
        meta_batch_dir(MetaTable.TRADING_CALENDAR, BATCH)
    assert meta_batch_dir(MetaTable.TRADING_CALENDAR, BATCH, source="binance").as_posix() == (
        f"data/meta/trading_calendar/source=binance/batch={BATCH}"
    )


def test_raw_and_staging_and_run_paths():
    assert raw_batch_dir("binance", BATCH).as_posix() == f"data/raw/binance/{BATCH}"
    assert staging_dir().as_posix() == "data/_staging"
    run = new_run_id()
    assert run_manifest_path(run).as_posix() == f"data/runs/{run}/manifest.json"


def test_invalid_source_and_id_rejected():
    with pytest.raises(PathSpecError):
        raw_batch_dir("Binance/../etc", BATCH)
    with pytest.raises(InvalidIdError):
        raw_batch_dir("binance", "not-a-ulid")


def test_generated_ids_are_valid_and_monotonic():
    ids = [new_batch_id() for _ in range(50)]
    assert all(is_valid_id(i) for i in ids)
    assert ids == sorted(ids)  # ULID 字典序单调（ADR-0002 D2.7）
