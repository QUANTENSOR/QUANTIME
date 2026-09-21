"""append-only 写入 API（ADR-0003 §4.3；验收：覆盖拒绝 / 单源不变量 / provenance 五列）。"""

from __future__ import annotations

import pytest
from quantime_core.ids import new_batch_id
from quantime_data import batches
from quantime_data.batches import BatchWriteError


def test_commit_writes_part_manifest_and_ingestion_batch_row(root, commit):
    b = commit()
    part = root / b.parts[0].path
    assert part.is_file()
    assert part.name == "part-0000.parquet"
    assert (root / b.manifest_path).is_file()

    rows = batches.read_ingestion_batch(root).to_pylist()
    assert len(rows) == 1
    row = rows[0]
    assert row["batch_id"] == b.batch_id
    assert row["source"] == "synthetic_bench"
    assert row["kind"] == "ingest"
    assert row["row_count"] == 3
    assert row["content_sha256"] == b.content_sha256
    assert row["manifest_path"] == b.manifest_path


def test_staging_dir_is_cleaned_and_outside_final_dir(root, commit):
    commit()
    staging = root / "data" / "_staging"
    assert not staging.exists() or not any(staging.iterdir())


def test_overwriting_existing_file_in_same_batch_dir_is_rejected(
    root, run_id, commit, lake_kw, make_table
):
    # 验收：覆盖同一 batch=<id>/ 目录下已有文件 → 拒绝。
    b = commit()
    table = make_table(source="synthetic_bench", batch_id=b.batch_id, run_id=run_id, price0=999.0)
    with pytest.raises(BatchWriteError, match="拒绝覆盖"):
        batches.commit_batch(
            root,
            table,
            source="synthetic_bench",
            source_version="v1",
            run_id=run_id,
            batch_id=b.batch_id,
            **lake_kw,
        )
    # 原文件未被改写。
    from quantime_core import parquet_io

    assert parquet_io.file_sha256(root / b.parts[0].path) == b.content_sha256


def test_row_source_mismatching_path_source_is_rejected(root, run_id, lake_kw, make_table):
    # 验收：行 source 列 ≠ 路径 source= 分量 → 拒绝。
    bid = new_batch_id()
    table = make_table(
        source="synthetic_bench",
        batch_id=bid,
        run_id=run_id,
        row_sources=["synthetic_bench", "other_source", "synthetic_bench"],
    )
    with pytest.raises(BatchWriteError, match="单源不变量"):
        batches.commit_batch(
            root,
            table,
            source="synthetic_bench",
            source_version="v1",
            run_id=run_id,
            batch_id=bid,
            **lake_kw,
        )
    assert not (root / "data" / "lake").exists()


@pytest.mark.parametrize(
    "missing", ["source", "source_version", "ingested_at", "run_id", "batch_id"]
)
def test_missing_any_adr_0002_column_is_rejected(root, run_id, missing, lake_kw, make_table):
    # 验收：缺 ADR-0002 五列（source, source_version, ingested_at, run_id, batch_id）→ 报错。
    bid = new_batch_id()
    table = make_table(source="s", batch_id=bid, run_id=run_id, drop_columns=(missing,))
    with pytest.raises(BatchWriteError, match="provenance"):
        batches.commit_batch(
            root,
            table,
            source="s",
            source_version="v1",
            run_id=run_id,
            batch_id=bid,
            **lake_kw,
        )


def test_row_batch_id_mismatch_is_rejected(root, run_id, lake_kw, make_table):
    table = make_table(source="s", batch_id=new_batch_id(), run_id=run_id)
    with pytest.raises(BatchWriteError, match="batch_id"):
        batches.commit_batch(
            root,
            table,
            source="s",
            source_version="v1",
            run_id=run_id,
            batch_id=new_batch_id(),
            **lake_kw,
        )


def test_empty_table_is_rejected(root, run_id, lake_kw, make_table):
    bid = new_batch_id()
    table = make_table(source="s", batch_id=bid, run_id=run_id, n=0)
    with pytest.raises(BatchWriteError, match="空表"):
        batches.commit_batch(
            root,
            table,
            source="s",
            source_version="v1",
            run_id=run_id,
            batch_id=bid,
            **lake_kw,
        )


def test_rerun_same_range_is_a_new_batch_with_rerun_of(root, run_id, commit, lake_kw, make_table):
    # §4.1：重跑同区间写新 batch_id，source_version 不变、附 rerun_of。
    first = commit()
    second_id = new_batch_id()
    table = make_table(source="synthetic_bench", batch_id=second_id, run_id=run_id, price0=101.0)
    second = batches.commit_batch(
        root,
        table,
        source="synthetic_bench",
        source_version="v1",
        run_id=run_id,
        batch_id=second_id,
        kind="rerun",
        rerun_of=first.batch_id,
        **lake_kw,
    )
    assert second.batch_dir != first.batch_dir
    assert (root / first.parts[0].path).is_file()  # 旧 batch 原地不动

    rows = {r["batch_id"]: r for r in batches.read_ingestion_batch(root).to_pylist()}
    assert rows[second_id]["kind"] == "rerun"
    assert rows[second_id]["rerun_of"] == first.batch_id
    assert rows[second_id]["source_version"] == rows[first.batch_id]["source_version"]


def test_rerun_without_rerun_of_is_rejected(root, run_id, lake_kw, make_table):
    bid = new_batch_id()
    table = make_table(source="s", batch_id=bid, run_id=run_id)
    with pytest.raises(BatchWriteError, match="rerun_of"):
        batches.commit_batch(
            root,
            table,
            source="s",
            source_version="v1",
            run_id=run_id,
            batch_id=bid,
            kind="rerun",
            **lake_kw,
        )


def test_invalid_kind_is_rejected(root, run_id, lake_kw, make_table):
    bid = new_batch_id()
    table = make_table(source="s", batch_id=bid, run_id=run_id)
    with pytest.raises(Exception, match="kind"):
        batches.commit_batch(
            root,
            table,
            source="s",
            source_version="v1",
            run_id=run_id,
            batch_id=bid,
            kind="upsert",
            **lake_kw,
        )


def test_license_drop_is_an_appended_tombstone_row(root, run_id, commit, lake_kw):
    # D2.5：许可驱动的删除 = 整源 drop + 追加 tombstone 行，永不逐行改写。
    b = commit()
    drop_id = batches.append_license_drop(
        root, source="synthetic_bench", source_version="v1", run_id=run_id, **lake_kw
    )
    rows = {r["batch_id"]: r for r in batches.read_ingestion_batch(root).to_pylist()}
    assert rows[drop_id]["kind"] == "license_drop"
    assert rows[drop_id]["row_count"] == 0
    assert rows[b.batch_id]["kind"] == "ingest"  # 原行未被改写


def test_ingestion_batch_rows_are_append_only_one_dir_per_batch(root, commit):
    commit()
    commit()
    meta = root / "data" / "meta" / "ingestion_batch"
    dirs = sorted(p.name for p in meta.iterdir())
    assert len(dirs) == 2
    assert all(d.startswith("batch=") for d in dirs)
    assert len(batches.read_ingestion_batch(root)) == 2
