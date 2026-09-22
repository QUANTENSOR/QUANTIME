"""事后复核（ADR-0003 §4.1 `checks.py` 抽样复核）。"""

from __future__ import annotations

import pytest
from quantime_core import parquet_io
from quantime_core.ids import new_batch_id, new_run_id
from quantime_data.checks import CheckError, check_batch_dir


def test_check_passes_for_well_formed_batch(root, commit):
    b = commit()
    report = check_batch_dir(root, b.batch_dir)
    assert report.files_checked == 1
    assert report.rows_checked == 3


def test_check_detects_source_mismatch_written_out_of_band(root, commit, make_table):
    """绕过写入 API 直接落盘的坏文件，复核必须抓到（写入侧断言 + 事后复核双层）。"""
    b = commit()
    bad_id = new_batch_id()
    bad_dir = root / b.batch_dir.replace(f"batch={b.batch_id}", f"batch={bad_id}")
    bad_dir.mkdir(parents=True)
    bad = make_table(
        source="other_source",
        batch_id=bad_id,
        run_id=new_run_id(),
        row_sources=["other_source"] * 3,
    )
    parquet_io.write_table(bad, bad_dir / "part-0000.parquet")
    with pytest.raises(CheckError, match="单源不变量"):
        check_batch_dir(root, bad_dir.relative_to(root))


def test_check_detects_missing_provenance_columns(root, commit, make_table):
    b = commit()
    bad_id = new_batch_id()
    bad_dir = root / b.batch_dir.replace(f"batch={b.batch_id}", f"batch={bad_id}")
    bad_dir.mkdir(parents=True)
    bad = make_table(
        source="synthetic_bench",
        batch_id=bad_id,
        run_id=new_run_id(),
        drop_columns=("ingested_at",),
    )
    parquet_io.write_table(bad, bad_dir / "part-0000.parquet")
    with pytest.raises(CheckError, match="provenance"):
        check_batch_dir(root, bad_dir.relative_to(root))


def test_check_rejects_missing_or_empty_dir(root, commit):
    b = commit()
    with pytest.raises(CheckError, match="不存在"):
        check_batch_dir(root, b.batch_dir + "-nope")
