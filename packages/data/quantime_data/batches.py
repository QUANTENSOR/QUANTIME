"""append-only 摄取写入 API（ADR-0003 §4.3，承接 ADR-0002 D2.1/D2.7）。

写入顺序（§4.3 原文 + QNT-27 R1/R2 返修）：
    **先取 batch 全局唯一性锁**（独占创建 `batch_manifest/<id>.json.lock`，任何落盘之前）
    → 落 raw → 写归一化 Parquet 到临时名（`data/_staging/`，位于所有读侧枚举范围之外）
    → 计算 sha → **原子发布**到最终路径 → 发布清单 JSON → 最后 insert `ingestion_batch` 行

唯一性登记介质：`data/meta/batch_manifest/<batch_id>.json.lock` 的 `O_CREAT|O_EXCL` **独占
创建**即锁（planner 裁决，2026-09-21）；`ingestion_batch` 行仍是最后一步 insert。锁在任何
字节落盘之前取得，因此同 batch_id 的第二次提交在碰到任何既有文件之前就被拒绝，第一次的
落盘结果逐字节不变。取锁成功返回 `BatchClaim`（含随机 nonce，锁文件只落其 sha256），
它是**唯一**能让 `commit_batch` 重入同一把锁的凭证——凭 batch_id 重构出的路径不算持有
（verify-a R1 P1）。

所有**最终**文件（湖 Parquet、清单 JSON、`ingestion_batch` 行）只经
`parquet_io.publish_*` 发布——先在 `data/_staging/` 完整写入并 close，再 `os.link` 到最终
路径：不存在才发布，且最终路径任何时刻要么不存在、要么是完整内容。
**不在最终路径上 `O_CREAT|O_EXCL` 之后再写 payload**：那样创建与写入之间该路径以 size=0
可见，并发读侧会把在途文件当成已提交内容登记进 manifest（verify-a R2 P1）。

本模块**只新建文件、从不改写既有文件**：最终 batch 目录若已存在文件即拒绝；
重跑同区间写新 `batch_id` + `rerun_of`；许可驱动的删除是整源 drop + 追加 `license_drop`
墓碑行（D2.5），永不逐行改写。未出现在 `ingestion_batch` 的文件视为不存在。
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import secrets
from dataclasses import dataclass, field
from pathlib import Path

import pyarrow as pa
from quantime_core import parquet_io
from quantime_core.ids import assert_valid_id, new_batch_id
from quantime_core.paths import (
    PROVENANCE_COLUMNS,
    AssetClass,
    DataType,
    Freq,
    LakePath,
    Market,
    MetaTable,
    assert_batch_kind,
    assert_scope,
    assert_source,
    meta_batch_dir,
    source_of_batch_dir,
    staging_dir,
)

#: `ingestion_batch` 表 schema（§4.3 字段原文；provenance 五列一并落在行上）。
INGESTION_BATCH_SCHEMA = pa.schema(
    [
        pa.field("batch_id", pa.string(), nullable=False),
        pa.field("source", pa.string(), nullable=False),
        pa.field("source_version", pa.string(), nullable=False),
        pa.field("market", pa.string(), nullable=False),
        pa.field("asset_class", pa.string(), nullable=False),
        pa.field("datatype", pa.string(), nullable=False),
        pa.field("freq", pa.string(), nullable=False),
        pa.field("scope", pa.string(), nullable=False),
        pa.field("range_start", pa.timestamp("us", tz="UTC"), nullable=True),
        pa.field("range_end", pa.timestamp("us", tz="UTC"), nullable=True),
        pa.field("row_count", pa.int64(), nullable=False),
        pa.field("content_sha256", pa.string(), nullable=False),
        pa.field("raw_sha256", pa.string(), nullable=True),
        pa.field("manifest_path", pa.string(), nullable=False),
        pa.field("committed_at", pa.timestamp("us", tz="UTC"), nullable=False),
        pa.field("ingested_at", pa.timestamp("us", tz="UTC"), nullable=False),
        pa.field("rerun_of", pa.string(), nullable=True),
        pa.field("run_id", pa.string(), nullable=False),
        pa.field("kind", pa.string(), nullable=False),
    ]
)

_INGESTION_BATCH_COLUMNS: tuple[str, ...] = tuple(INGESTION_BATCH_SCHEMA.names)


class BatchWriteError(RuntimeError):
    """写入违反 append-only / 单源不变量 / provenance 要求。"""


@dataclass(frozen=True, slots=True)
class FileEntry:
    """清单里的一条文件记录（path 相对 `root`）。"""

    path: str
    sha256: str
    size: int

    def as_dict(self) -> dict[str, object]:
        return {"path": self.path, "sha256": self.sha256, "size": self.size}

    @classmethod
    def from_dict(cls, raw: dict[str, object]) -> FileEntry:
        return cls(path=str(raw["path"]), sha256=str(raw["sha256"]), size=int(raw["size"]))  # type: ignore[arg-type]


@dataclass(frozen=True, slots=True)
class CommittedBatch:
    """`commit_batch` 的结果。"""

    batch_id: str
    source: str
    batch_dir: str
    parts: tuple[FileEntry, ...]
    raw_files: tuple[FileEntry, ...]
    manifest_path: str
    content_sha256: str
    row_count: int
    kind: str
    rerun_of: str | None
    meta_files: tuple[FileEntry, ...] = field(default=())


def _now() -> dt.datetime:
    return dt.datetime.now(dt.UTC).replace(microsecond=0)


def _file_entry(root: Path, abs_path: Path) -> FileEntry:
    return FileEntry(
        path=abs_path.relative_to(root).as_posix(),
        sha256=parquet_io.file_sha256(abs_path),
        size=abs_path.stat().st_size,
    )


def _assert_provenance(table: pa.Table, *, source: str, batch_id: str) -> None:
    """缺 ADR-0002 五列 → 报错；行 `source` ≠ 路径 `source=` 分量 → 拒绝（§4.1 单源不变量）。

    调用方必须传**最终落盘的表**（`columns=` 投影之后）——否则投影可以把五列全部
    抹掉而校验仍看见它们（verify-a P1-2）。
    """
    missing = [c for c in PROVENANCE_COLUMNS if c not in table.column_names]
    if missing:
        raise BatchWriteError(f"缺少 ADR-0002 provenance 列: {missing}")
    if table.num_rows == 0:
        raise BatchWriteError("batch 不得为空表（空摄取不写 batch）")
    distinct_sources = set(table.column("source").to_pylist())
    if distinct_sources != {source}:
        raise BatchWriteError(
            f"单源不变量：行 source={sorted(distinct_sources)} 与路径 source={source!r} 不一致"
        )
    distinct_batches = set(table.column("batch_id").to_pylist())
    if distinct_batches != {batch_id}:
        raise BatchWriteError(
            f"行 batch_id={sorted(distinct_batches)} 与目标 batch_id={batch_id!r} 不一致"
        )


def _assert_empty_target(batch_dir: Path) -> None:
    """同一 `batch=<id>/` 目录下已有文件 → 拒绝（append-only，batch 目录提交后不可变）。

    这是**早退**检查，不是安全保证：真正的保证来自 `_claim_batch_id` 的唯一性锁与
    `parquet_io.publish_*` 的独占创建。
    """
    if batch_dir.exists() and any(batch_dir.iterdir()):
        raise BatchWriteError(
            f"batch 目录已存在文件，拒绝覆盖（append-only，"
            f"重跑请用新 batch_id + rerun_of）: {batch_dir}"
        )


def batch_manifest_path(batch_id: str) -> str:
    """该 batch 的文件级清单位置（相对 root）。"""
    return f"data/meta/batch_manifest/{assert_valid_id(batch_id, field='batch_id')}.json"


def publish_staging(root: Path) -> Path:
    """发布用临时目录（`data/_staging/`）——所有最终文件的必经中转。

    它在 `committed_batch_files` / `_scan_dir` / `_ingestion_batch_records` 的枚举范围之外，
    且与 `data/` 下的最终路径同一文件系统（`os.link` 要求）。
    """
    return root / staging_dir()


def _publish_final_bytes(root: Path, path: Path, payload: bytes) -> str:
    """原子发布一个最终文件；已存在 → 拒绝且原文件字节不变。"""
    try:
        return parquet_io.publish_bytes(path, payload, staging=publish_staging(root))
    except parquet_io.AlreadyPublishedError as exc:
        raise BatchWriteError(f"最终文件已存在，拒绝二次发布（append-only）: {path}") from exc


def _publish_final_text(root: Path, path: Path, text: str) -> None:
    """原子发布一个最终文本文件（清单 JSON）；已存在 → 拒绝且原文件字节不变。"""
    _publish_final_bytes(root, path, text.encode("utf-8"))


def batch_claim_path(batch_id: str) -> str:
    """batch_id 全局唯一性登记（相对 root）——独占创建它即取得该 batch_id。"""
    return batch_manifest_path(batch_id) + ".lock"


@dataclass(frozen=True, slots=True)
class BatchClaim:
    """**独占取得**一个 batch_id 的所有权凭证——只能由 `claim_batch_id` 成功那一次产出。

    `nonce` 是取锁时现生成的随机数，只活在返回的这个对象里；锁文件落的是它的
    **sha256**，不是它本身。两者的分工：

    - 落 digest 而不是 nonce：锁文件全世界可读，若把 nonce 本身写进去，任何第三方读一遍
      文件就能拼出一个「看起来有效」的凭证——那等于没有凭证（verify-a R1 P1 的同类漏洞）。
    - 落 digest 而不是什么都不落：凭证必须能**绑定到当前这把锁**。锁文件被删掉重建后，
      新锁是另一个 nonce，旧凭证的 digest 对不上，于是旧持有者不能凭一个陈旧对象重入。

    因此「持有凭证」= 「当初亲自独占创建了当前这个锁文件」，而不是「知道 batch_id 和 root」
    ——后者是所有调用方都有的公开信息，用它当凭证等于不校验。
    """

    batch_id: str
    path: Path
    nonce: str = field(repr=False)

    def digest(self) -> str:
        return hashlib.sha256(self.nonce.encode("ascii")).hexdigest()


def _claim_file_contents(batch_id: str, digest: str) -> bytes:
    """锁文件正文：batch_id + nonce 的 sha256（人可读，便于运维核对遗留锁）。"""
    return f"batch_id={batch_id}\nnonce_sha256={digest}\n".encode("ascii")


def _read_claim_digest(claim_path: Path) -> str | None:
    """读锁文件里登记的 nonce digest；文件不存在或格式不符 → `None`。"""
    try:
        text = claim_path.read_text(encoding="ascii")
    except OSError, UnicodeDecodeError:
        return None
    for line in text.splitlines():
        key, _, value = line.partition("=")
        if key == "nonce_sha256":
            return value
    return None


def _assert_claim_ownership(claim: BatchClaim, batch_id: str, expected_path: Path) -> None:
    """校验 `claim` 真是**当前这把锁**的所有权凭证；不是 → 拒绝（在任何字节落盘之前）。

    三条都必须成立：类型对（Path 之类的公开可构造值一律不认）、指向的就是本 batch 的锁、
    锁文件此刻记着的 digest 正是这份凭证的 nonce 的 digest。
    """
    if not isinstance(claim, BatchClaim):
        raise BatchWriteError(
            f"claim 不是 claim_batch_id 返回的所有权凭证（得到 {type(claim).__name__}）："
            f"唯一性登记不接受凭 batch_id/路径重构的值"
        )
    if claim.batch_id != batch_id or claim.path != expected_path:
        raise BatchWriteError(
            f"claim 登记的是 {claim.batch_id!r}，与本次提交的 batch_id={batch_id!r} 不符"
        )
    on_disk = _read_claim_digest(expected_path)
    if on_disk is None:
        raise BatchWriteError(f"batch_id 的唯一性登记已不存在，拒绝提交: {batch_id}")
    if on_disk != claim.digest():
        raise BatchWriteError(f"claim 与当前登记不符（锁已被另一次取得），拒绝提交: {batch_id}")


def _claim_batch_id(root: Path, batch_id: str, *, holder: BatchClaim | None = None) -> BatchClaim:
    """在**任何字节落盘之前**独占登记 batch_id；已被登记 → 拒绝。

    唯一性介质是 `data/meta/batch_manifest/<id>.json.lock` 的独占创建（`O_CREAT|O_EXCL`，
    planner 裁决 2026-09-21：manifest 目录存在性即锁，`ingestion_batch` 行仍最后 insert）。
    batch_id 是 ULID、永不复用：崩溃留下的登记不再释放，重跑请用新 batch_id + `rerun_of`。

    `holder` 是调用方**已经独占取得**的同一把锁（`claim_batch_id` 的返回值）：校验通过即
    重入，不再二次独占创建。校验见 `_assert_claim_ownership`——凭 `batch_id` 重构出来的
    路径进不来，读一遍锁文件也拼不出凭证。
    """
    claim_path = root / batch_claim_path(batch_id)
    if holder is not None:
        _assert_claim_ownership(holder, batch_id, claim_path)
        return holder
    claim_path.parent.mkdir(parents=True, exist_ok=True)
    nonce = secrets.token_hex(16)
    digest = hashlib.sha256(nonce.encode("ascii")).hexdigest()
    try:
        fd = os.open(claim_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    except FileExistsError as exc:
        raise BatchWriteError(
            f"batch_id 已被登记，拒绝二次提交（append-only，"
            f"重跑请用新 batch_id + rerun_of）: {batch_id}"
        ) from exc
    try:
        os.write(fd, _claim_file_contents(batch_id, digest))
    finally:
        os.close(fd)
    return BatchClaim(batch_id=batch_id, path=claim_path, nonce=nonce)


def claim_batch_id(root: str | os.PathLike[str], batch_id: str) -> BatchClaim:
    """公开入口：在自己写任何 batch 相关字节之前先取得唯一性登记。

    摄取链路要在 `commit_batch` 之前就把上游原始字节写进 `data/raw/<batch_id>/`，
    所以必须能提前取锁；返回的 `BatchClaim` 再作为 `commit_batch(..., claim=...)` 传回去。
    """
    return _claim_batch_id(Path(root), batch_id)


def commit_batch(
    root: str | os.PathLike[str],
    table: pa.Table,
    *,
    market: Market | str,
    asset_class: AssetClass | str,
    datatype: DataType | str,
    freq: Freq | str,
    scope: str,
    source: str,
    source_version: str,
    run_id: str,
    batch_id: str | None = None,
    kind: str = "ingest",
    rerun_of: str | None = None,
    raw_files: tuple[Path, ...] = (),
    range_start: dt.datetime | None = None,
    range_end: dt.datetime | None = None,
    columns: tuple[str, ...] | None = None,
    claim: BatchClaim | None = None,
) -> CommittedBatch:
    """把一个归一化表提交为一个新 batch。

    顺序：**先取 batch_id 唯一性锁**（任何落盘之前）→ staging 写临时名并 close → sha →
    原子发布到最终 batch 目录 → 原子发布清单 JSON → 最后 insert `ingestion_batch` 行。
    任一步失败都不会留下已登记但不完整的 batch，也**绝不改动任何既有文件的字节**；
    最终路径上从不出现半写内容，因此并发读侧只会看到「尚未提交」或「完整已提交」。

    `claim` 传的是调用方已经用 `claim_batch_id` **独占取得**的所有权凭证——摄取链路要先
    写 raw 副本，必须比这里更早取锁。不传就在这里取；传了但不是真凭证即拒绝。
    """
    root = Path(root)
    source = assert_source(source)
    kind = assert_batch_kind(kind)
    batch_id = assert_valid_id(batch_id, field="batch_id") if batch_id else new_batch_id()
    if rerun_of is not None:
        assert_valid_id(rerun_of, field="rerun_of")
    if kind == "rerun" and rerun_of is None:
        raise BatchWriteError("kind='rerun' 必须带 rerun_of=<原 batch_id>")
    assert_valid_id(run_id, field="run_id")

    # provenance 校验的对象是**最终落盘的 schema**（投影之后），否则 `columns=` 能把
    # ADR-0002 五列悄悄投影掉（verify-a P1-2）。校验发生在任何落盘之前。
    try:
        final_table = parquet_io.canonical_table(table, columns)
    except KeyError as exc:
        raise BatchWriteError(f"columns 投影失败: {exc}") from exc
    _assert_provenance(final_table, source=source, batch_id=batch_id)

    spec = LakePath(
        market=Market(market),
        asset_class=AssetClass(asset_class),
        datatype=DataType(datatype),
        freq=Freq(freq),
        scope=scope,
        source=source,
        batch_id=batch_id,
    )
    batch_dir = root / spec.batch_dir
    _assert_empty_target(batch_dir)
    if source_of_batch_dir(spec.batch_dir) != source:
        raise BatchWriteError("路径 source= 分量与 source 参数不一致")

    raw_entries = tuple(_file_entry(root, Path(p)) for p in raw_files)

    # 唯一性锁：任何字节落盘之前。之后的每一次写都是独占创建。
    _claim_batch_id(root, batch_id, holder=claim)

    payload = parquet_io.table_to_bytes(final_table)
    batch_dir.mkdir(parents=True, exist_ok=True)
    final_part = batch_dir / "part-0000.parquet"
    content_sha256 = _publish_final_bytes(root, final_part, payload)

    parts = (
        FileEntry(
            path=final_part.relative_to(root).as_posix(),
            sha256=content_sha256,
            size=len(payload),
        ),
    )
    manifest_rel = batch_manifest_path(batch_id)
    manifest_abs = root / manifest_rel
    manifest_abs.parent.mkdir(parents=True, exist_ok=True)
    _publish_final_text(
        root,
        manifest_abs,
        json.dumps(
            {
                "batch_id": batch_id,
                "source": source,
                "batch_dir": spec.batch_dir.as_posix(),
                "parts": [e.as_dict() for e in parts],
                "raw": [e.as_dict() for e in raw_entries],
            },
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
        )
        + "\n",
    )

    now = _now()
    meta_entry = _insert_ingestion_batch_row(
        root,
        {
            "batch_id": batch_id,
            "source": source,
            "source_version": source_version,
            "market": str(spec.market),
            "asset_class": str(spec.asset_class),
            "datatype": str(spec.datatype),
            "freq": str(spec.freq),
            "scope": spec.scope,
            "range_start": range_start,
            "range_end": range_end,
            "row_count": table.num_rows,
            "content_sha256": content_sha256,
            "raw_sha256": raw_entries[0].sha256 if raw_entries else None,
            "manifest_path": manifest_rel,
            "committed_at": now,
            "ingested_at": now,
            "rerun_of": rerun_of,
            "run_id": run_id,
            "kind": kind,
        },
    )
    return CommittedBatch(
        batch_id=batch_id,
        source=source,
        batch_dir=spec.batch_dir.as_posix(),
        parts=parts,
        raw_files=raw_entries,
        manifest_path=manifest_rel,
        content_sha256=content_sha256,
        row_count=table.num_rows,
        kind=kind,
        rerun_of=rerun_of,
        meta_files=(meta_entry,),
    )


def commit_meta_batch(
    root: str | os.PathLike[str],
    table: pa.Table,
    *,
    meta_table: MetaTable | str,
    market: Market | str,
    asset_class: AssetClass | str,
    scope: str,
    source: str,
    source_version: str,
    run_id: str,
    batch_id: str | None = None,
    kind: str = "ingest",
    rerun_of: str | None = None,
    raw_files: tuple[Path, ...] = (),
    range_start: dt.datetime | None = None,
    range_end: dt.datetime | None = None,
    columns: tuple[str, ...] | None = None,
    claim: BatchClaim | None = None,
) -> CommittedBatch:
    """把一个 meta 表（`instrument_meta` / `adjust_factor` / `ticker_events` …）提交为新 batch。

    与 `commit_batch` 同一套顺序与不变量（先取锁 → staging → 原子发布 → 清单 → 最后 insert
    `ingestion_batch` 行），只是落点是 `data/meta/<table>/source=<s>/batch=<id>/`
    （`paths.meta_batch_dir`）而不是湖路径。QNT-47 阶段 2 新增：此前 meta 表只有路径函数、
    没有提交入口（PR「文档矛盾」一节已报）。

    `ingestion_batch` 行的 `datatype` 记 meta 表名、`freq` 记 `event`——该表的这两列是
    自由字符串，湖路径的 `DataType` 枚举里没有「参考数据」这一类，不借用一个语义不符的
    枚举值冒充。
    """
    root = Path(root)
    table_name = MetaTable(meta_table)
    if table_name is MetaTable.INGESTION_BATCH:
        raise BatchWriteError("ingestion_batch 只由提交流程自身 insert，不得经本入口写入")
    source = assert_source(source)
    scope = assert_scope(scope)
    kind = assert_batch_kind(kind)
    batch_id = assert_valid_id(batch_id, field="batch_id") if batch_id else new_batch_id()
    if rerun_of is not None:
        assert_valid_id(rerun_of, field="rerun_of")
    if kind == "rerun" and rerun_of is None:
        raise BatchWriteError("kind='rerun' 必须带 rerun_of=<原 batch_id>")
    assert_valid_id(run_id, field="run_id")
    try:
        final_table = parquet_io.canonical_table(table, columns)
    except KeyError as exc:
        raise BatchWriteError(f"columns 投影失败: {exc}") from exc
    _assert_provenance(final_table, source=source, batch_id=batch_id)

    rel_dir = meta_batch_dir(table_name, batch_id, source=source)
    batch_dir = root / rel_dir
    _assert_empty_target(batch_dir)
    raw_entries = tuple(_file_entry(root, Path(p)) for p in raw_files)

    _claim_batch_id(root, batch_id, holder=claim)

    payload = parquet_io.table_to_bytes(final_table)
    batch_dir.mkdir(parents=True, exist_ok=True)
    final_part = batch_dir / "part-0000.parquet"
    content_sha256 = _publish_final_bytes(root, final_part, payload)
    parts = (
        FileEntry(
            path=final_part.relative_to(root).as_posix(),
            sha256=content_sha256,
            size=len(payload),
        ),
    )
    manifest_rel = batch_manifest_path(batch_id)
    manifest_abs = root / manifest_rel
    manifest_abs.parent.mkdir(parents=True, exist_ok=True)
    _publish_final_text(
        root,
        manifest_abs,
        json.dumps(
            {
                "batch_id": batch_id,
                "source": source,
                "batch_dir": rel_dir.as_posix(),
                "parts": [e.as_dict() for e in parts],
                "raw": [e.as_dict() for e in raw_entries],
            },
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
        )
        + "\n",
    )
    now = _now()
    meta_entry = _insert_ingestion_batch_row(
        root,
        {
            "batch_id": batch_id,
            "source": source,
            "source_version": source_version,
            "market": str(Market(market)),
            "asset_class": str(AssetClass(asset_class)),
            "datatype": str(table_name),
            "freq": str(Freq.EVENT),
            "scope": scope,
            "range_start": range_start,
            "range_end": range_end,
            "row_count": table.num_rows,
            "content_sha256": content_sha256,
            "raw_sha256": raw_entries[0].sha256 if raw_entries else None,
            "manifest_path": manifest_rel,
            "committed_at": now,
            "ingested_at": now,
            "rerun_of": rerun_of,
            "run_id": run_id,
            "kind": kind,
        },
    )
    return CommittedBatch(
        batch_id=batch_id,
        source=source,
        batch_dir=rel_dir.as_posix(),
        parts=parts,
        raw_files=raw_entries,
        manifest_path=manifest_rel,
        content_sha256=content_sha256,
        row_count=table.num_rows,
        kind=kind,
        rerun_of=rerun_of,
        meta_files=(meta_entry,),
    )


def _insert_ingestion_batch_row(root: Path, row: dict[str, object]) -> FileEntry:
    """insert 一行 `ingestion_batch`（新 batch 目录 = 新文件，永不改旧文件）。"""
    meta_dir = root / meta_batch_dir(MetaTable.INGESTION_BATCH, str(row["batch_id"]))
    _assert_empty_target(meta_dir)
    meta_dir.mkdir(parents=True, exist_ok=True)
    table = pa.Table.from_pylist([row], schema=INGESTION_BATCH_SCHEMA)
    target = meta_dir / "part-0000.parquet"
    payload = parquet_io.table_to_bytes(table, _INGESTION_BATCH_COLUMNS)
    try:
        sha = parquet_io.publish_bytes(target, payload, staging=publish_staging(root))
    except parquet_io.AlreadyPublishedError as exc:
        raise BatchWriteError(f"ingestion_batch 行已存在，拒绝二次 insert: {target}") from exc
    return FileEntry(path=target.relative_to(root).as_posix(), sha256=sha, size=len(payload))


def append_license_drop(
    root: str | os.PathLike[str],
    *,
    source: str,
    source_version: str,
    run_id: str,
    market: Market | str,
    asset_class: AssetClass | str,
    datatype: DataType | str,
    freq: Freq | str,
    scope: str,
) -> str:
    """追加 `kind='license_drop'` 墓碑行（D2.5；实际文件删除由 owner 确认后人工执行）。"""
    root = Path(root)
    batch_id = new_batch_id()
    _claim_batch_id(root, batch_id)
    now = _now()
    _insert_ingestion_batch_row(
        root,
        {
            "batch_id": batch_id,
            "source": assert_source(source),
            "source_version": source_version,
            "market": str(Market(market)),
            "asset_class": str(AssetClass(asset_class)),
            "datatype": str(DataType(datatype)),
            "freq": str(Freq(freq)),
            "scope": scope,
            "range_start": None,
            "range_end": None,
            "row_count": 0,
            "content_sha256": "",
            "raw_sha256": None,
            "manifest_path": "",
            "committed_at": now,
            "ingested_at": now,
            "rerun_of": None,
            "run_id": run_id,
            "kind": "license_drop",
        },
    )
    return batch_id


def committed_batch_files(root: str | os.PathLike[str]) -> list[Path]:
    """已提交的 `ingestion_batch` 分片文件列表（显式文件列表，不用 glob 读数据，§4.2）。"""
    meta_root = Path(root) / "data" / "meta" / "ingestion_batch"
    if not meta_root.is_dir():
        return []
    files: list[Path] = []
    for batch_dir in sorted(meta_root.iterdir()):
        if batch_dir.is_dir() and batch_dir.name.startswith("batch="):
            files.extend(sorted(p for p in batch_dir.iterdir() if p.suffix == ".parquet"))
    return files


def read_ingestion_batch(root: str | os.PathLike[str]) -> pa.Table:
    """读取全部已提交 `ingestion_batch` 行。"""
    files = committed_batch_files(root)
    if not files:
        return INGESTION_BATCH_SCHEMA.empty_table()
    return pa.concat_tables([parquet_io.read_table(f) for f in files]).sort_by("batch_id")
