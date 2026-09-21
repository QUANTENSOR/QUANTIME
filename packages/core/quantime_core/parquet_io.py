"""确定性 Parquet writer（ADR-0003 §4.2 R2）。

固定 writer 参数（行组大小、压缩、不写时间戳型 statistics、列顺序、不写 pandas 元数据），
使「同输入 → 同字节」，重放产出的 `result_sha256` 才可比。
"""

from __future__ import annotations

import hashlib
import io
import os
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

#: 固定 writer 参数——改动其中任何一项都会改变既有文件的 sha，属于 ADR 修订级变更。
WRITER_VERSION = "2.6"
COMPRESSION = "zstd"
COMPRESSION_LEVEL = 3
ROW_GROUP_SIZE = 122_880
DATA_PAGE_SIZE = 1 << 20


def _canonical_table(table: pa.Table, columns: tuple[str, ...] | None) -> pa.Table:
    """按显式列序取列，并剥掉 schema 元数据（pandas 元数据含随机顺序的 json）。"""
    if columns is not None:
        missing = [c for c in columns if c not in table.column_names]
        if missing:
            raise KeyError(f"表缺少列: {missing}")
        table = table.select(list(columns))
    return table.replace_schema_metadata(None)


def _write(table: pa.Table, sink: io.IOBase | str) -> None:
    pq.write_table(
        table,
        sink,
        version=WRITER_VERSION,
        compression=COMPRESSION,
        compression_level=COMPRESSION_LEVEL,
        row_group_size=ROW_GROUP_SIZE,
        data_page_size=DATA_PAGE_SIZE,
        write_statistics=False,
        store_schema=True,
        write_page_index=False,
        use_dictionary=False,
        coerce_timestamps="us",
        allow_truncated_timestamps=False,
        store_decimal_as_integer=False,
        sorting_columns=None,
    )


def table_to_bytes(table: pa.Table, columns: tuple[str, ...] | None = None) -> bytes:
    """把表序列化为确定性 Parquet 字节串（不落盘）。"""
    buf = io.BytesIO()
    _write(_canonical_table(table, columns), buf)
    return buf.getvalue()


def table_sha256(table: pa.Table, columns: tuple[str, ...] | None = None) -> str:
    """表的确定性 Parquet 序列化的 sha256（§5.1 `payload_sha256` 的算法）。"""
    return hashlib.sha256(table_to_bytes(table, columns)).hexdigest()


def write_table(
    table: pa.Table, path: str | os.PathLike[str], columns: tuple[str, ...] | None = None
) -> str:
    """确定性写盘并回传文件 sha256。父目录必须已存在（写入顺序由调用方控制）。"""
    payload = table_to_bytes(table, columns)
    Path(path).write_bytes(payload)
    return hashlib.sha256(payload).hexdigest()


def file_sha256(path: str | os.PathLike[str]) -> str:
    """文件内容 sha256（分块读，供清单校验用）。"""
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        while chunk := fh.read(1 << 20):
            digest.update(chunk)
    return digest.hexdigest()


def read_table(path: str | os.PathLike[str]) -> pa.Table:
    return pq.read_table(path)
