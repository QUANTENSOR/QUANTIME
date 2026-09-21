"""确定性 Parquet writer（ADR-0003 §4.2 R2）。

固定 writer 参数（行组大小、压缩、不写时间戳型 statistics、列顺序、不写 pandas 元数据），
使「同输入 → 同字节」，重放产出的 `result_sha256` 才可比。
"""

from __future__ import annotations

import hashlib
import io
import os
import tempfile
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

#: 固定 writer 参数——改动其中任何一项都会改变既有文件的 sha，属于 ADR 修订级变更。
WRITER_VERSION = "2.6"
COMPRESSION = "zstd"
COMPRESSION_LEVEL = 3
ROW_GROUP_SIZE = 122_880
DATA_PAGE_SIZE = 1 << 20


def canonical_table(table: pa.Table, columns: tuple[str, ...] | None) -> pa.Table:
    """按显式列序取列，并剥掉 schema 元数据（pandas 元数据含随机顺序的 json）。

    这是「最终落盘的 schema」的唯一定义：写入侧的 provenance 校验必须对本函数的产物做，
    否则 `columns=` 投影会把 ADR-0002 五列悄悄投影掉（ADR-0002 D2.2）。
    """
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
    _write(canonical_table(table, columns), buf)
    return buf.getvalue()


def table_sha256(table: pa.Table, columns: tuple[str, ...] | None = None) -> str:
    """表的确定性 Parquet 序列化的 sha256（§5.1 `payload_sha256` 的算法）。"""
    return hashlib.sha256(table_to_bytes(table, columns)).hexdigest()


def write_table(
    table: pa.Table, path: str | os.PathLike[str], columns: tuple[str, ...] | None = None
) -> str:
    """确定性写盘并回传文件 sha256。父目录必须已存在（写入顺序由调用方控制）。

    仅供**可再生的中间产物**（`_staging/` 临时名、bench 生成物）使用。
    任何进入湖/清单/结果目录的最终文件一律走 `publish_bytes` / `publish_table`。
    """
    payload = table_to_bytes(table, columns)
    Path(path).write_bytes(payload)
    return hashlib.sha256(payload).hexdigest()


class AlreadyPublishedError(FileExistsError):
    """目标路径已存在——最终文件「不存在才发布」（ADR-0002 只 insert）。"""


def _write_tmp(staging_root: Path, payload: bytes) -> Path:
    """在 `staging_root` 下完整写入 `payload` 并 **close**，回传临时文件路径。

    `staging_root` 必须在**所有读侧枚举范围之外**（`data/_staging/`），且与最终路径同一
    文件系统（`os.link` 要求）。临时名带 `.tmp` 后缀与 `.publish-` 前缀，只为便于人工辨认；
    不可见性由「不在任何枚举目录内」保证，不靠命名过滤。
    """
    staging_root.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=staging_root, prefix=".publish-", suffix=".tmp")
    tmp = Path(name)
    try:
        # 用裸 fd 写：写完 fsync 再 close，close 之后临时文件才算完整。
        try:
            written = 0
            while written < len(payload):
                written += os.write(fd, payload[written:])
            os.fsync(fd)
        finally:
            os.close(fd)
        os.chmod(tmp, 0o644)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    return tmp


def _link_exclusive(tmp: Path, target: Path) -> None:
    """把**已完整落盘并关闭**的临时文件发布到最终路径——单次原子操作，且不可覆盖。

    `os.link` 目标已存在时抛 `FileExistsError` 且不触碰原文件（`os.replace` 会静默盖掉，
    故不用）。因为 link 的源已是完整内容，最终路径任何时刻要么不存在、要么是完整内容，
    读侧绝不会看到 size=0 或半写状态（verify-a R2 P1）。
    """
    try:
        os.link(tmp, target)
    except FileExistsError as exc:
        raise AlreadyPublishedError(f"目标已存在，拒绝再次发布（只 insert）: {target}") from exc


def publish_bytes(
    path: str | os.PathLike[str], payload: bytes, *, staging: str | os.PathLike[str]
) -> str:
    """原子发布一个最终文件，回传 sha256。

    两段式：先在 `staging`（最终枚举范围之外、同一文件系统）完整写入并 close，
    再 `os.link` 到最终路径，最后删掉临时名。这是所有最终文件（湖 Parquet、清单 JSON、
    `ingestion_batch` 行、run 清单、重放结果）唯一的发布路径。

    直接在最终路径上 `O_CREAT|O_EXCL` 再写 payload 是不够的：创建与写入之间该路径以
    size=0 可见，并发的读侧会把在途文件当成已提交内容登记进 manifest（verify-a R2 P1）。

    目标已存在 → `AlreadyPublishedError`，**原文件字节不变**（ADR-0002 D2.1 只 insert）。
    发布前失败（写 tmp 中途异常、进程退出）→ 最终路径不存在；`staging` 可能留下残片，
    它不在任何枚举范围内，不会被误认成已提交数据。

    `staging` 必须与 `path` 同一文件系统，否则 `os.link` 抛 `OSError(EXDEV)`。
    """
    target = Path(path)
    tmp = _write_tmp(Path(staging), payload)
    try:
        _link_exclusive(tmp, target)
    finally:
        tmp.unlink(missing_ok=True)
    return hashlib.sha256(payload).hexdigest()


def publish_text(
    path: str | os.PathLike[str], text: str, *, staging: str | os.PathLike[str]
) -> str:
    """`publish_bytes` 的 UTF-8 文本版（清单 JSON 用）。"""
    return publish_bytes(path, text.encode("utf-8"), staging=staging)


def publish_table(
    table: pa.Table,
    path: str | os.PathLike[str],
    columns: tuple[str, ...] | None = None,
    *,
    staging: str | os.PathLike[str],
) -> str:
    """确定性序列化 + 原子发布，回传 sha256。"""
    return publish_bytes(path, table_to_bytes(table, columns), staging=staging)


def file_sha256(path: str | os.PathLike[str]) -> str:
    """文件内容 sha256（分块读，供清单校验用）。"""
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        while chunk := fh.read(1 << 20):
            digest.update(chunk)
    return digest.hexdigest()


def read_table(path: str | os.PathLike[str]) -> pa.Table:
    return pq.read_table(path)
