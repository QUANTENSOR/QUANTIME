"""确定性 Parquet writer（ADR-0003 §4.2 R2）。"""

from __future__ import annotations

import subprocess
import sys

import pyarrow as pa
import pytest
from quantime_core import parquet_io


def _table() -> pa.Table:
    return pa.table(
        {
            "symbol": pa.array(["A", "B", "A"], type=pa.string()),
            "value": pa.array([1.5, 2.5, 3.5], type=pa.float64()),
            "n": pa.array([1, 2, 3], type=pa.int64()),
        }
    )


def test_r2_same_input_same_sha_within_process():
    # R2：同输入两次写 Parquet sha256 相等。
    assert parquet_io.table_sha256(_table()) == parquet_io.table_sha256(_table())


def test_r2_same_input_same_sha_across_processes():
    code = (
        "import pyarrow as pa;from quantime_core import parquet_io;"
        "t=pa.table({'symbol':pa.array(['A','B','A'],type=pa.string()),"
        "'value':pa.array([1.5,2.5,3.5],type=pa.float64()),"
        "'n':pa.array([1,2,3],type=pa.int64())});"
        "print(parquet_io.table_sha256(t))"
    )
    shas = {
        subprocess.run(
            [sys.executable, "-c", code], capture_output=True, text=True, check=True
        ).stdout.strip()
        for _ in range(2)
    }
    assert len(shas) == 1
    assert shas.pop() == parquet_io.table_sha256(_table())


def test_different_data_gives_different_sha():
    other = _table().set_column(1, "value", pa.array([1.5, 2.5, 3.6], type=pa.float64()))
    assert parquet_io.table_sha256(other) != parquet_io.table_sha256(_table())


def test_column_order_is_pinned_by_explicit_columns():
    t = _table()
    reordered = t.select(["n", "value", "symbol"])
    cols = ("symbol", "value", "n")
    # 显式列序下两者一致；不给列序时列序差异会改变 sha。
    assert parquet_io.table_sha256(reordered, cols) == parquet_io.table_sha256(t, cols)
    assert parquet_io.table_sha256(reordered) != parquet_io.table_sha256(t)


def test_missing_column_raises():
    with pytest.raises(KeyError):
        parquet_io.table_sha256(_table(), ("symbol", "nope"))


def test_write_table_returns_file_sha_matching_content(tmp_path):
    target = tmp_path / "x.parquet"
    sha = parquet_io.write_table(_table(), target)
    assert sha == parquet_io.file_sha256(target)
    assert parquet_io.read_table(target).equals(_table())


def test_schema_metadata_is_stripped():
    t = _table().replace_schema_metadata({"pandas": "whatever"})
    assert parquet_io.table_sha256(t) == parquet_io.table_sha256(_table())


def test_writer_params_are_pinned_constants():
    # 改动任何一项都会改变既有文件 sha —— 属 ADR 修订级变更，这里钉住。
    assert parquet_io.WRITER_VERSION == "2.6"
    assert parquet_io.COMPRESSION == "zstd"
    assert parquet_io.COMPRESSION_LEVEL == 3
    assert parquet_io.ROW_GROUP_SIZE == 122_880
