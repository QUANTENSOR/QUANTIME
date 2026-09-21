"""重放与清单校验 R1–R5（ADR-0003 §4.2「重放硬验收」）。

校验单位是 manifest 内每个 `batch_id` 的目录 `.../source=<s>/batch=<batch_id>/`：
对清单内每个 batch 目录，实际文件集合必须**恰好等于** manifest 登记的集合（不缺、不多、
sha/size 一致）。清单外的 batch 目录（R3 的晚到 batch、run 之后的正常新摄取）
**不扫描、不校验、不读取**——因此「多出文件」只在 batch 目录粒度判定。
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

import pyarrow as pa
from quantime_core import parquet_io
from quantime_core.ids import assert_valid_id
from quantime_core.paths import run_manifest_path, run_results_dir

from .batches import (
    CommittedBatch,
    FileEntry,
    batch_manifest_path,
    committed_batch_files,
    publish_staging,
)

MANIFEST_VERSION = 1


class ReplayIntegrityError(RuntimeError):
    """清单内 batch 目录与 manifest 登记不符（R1/R4）。

    三种情形：缺文件 / sha 或 size 不符 / 目录内多出未登记文件。
    """


@dataclass(frozen=True, slots=True)
class BatchRecord:
    """manifest 里一个 batch 的登记：目录 + 该目录内的完整文件集合。"""

    batch_id: str
    batch_dir: str
    files: tuple[FileEntry, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "batch_id": self.batch_id,
            "batch_dir": self.batch_dir,
            "files": [f.as_dict() for f in self.files],
        }

    @classmethod
    def from_dict(cls, raw: dict) -> BatchRecord:
        return cls(
            batch_id=str(raw["batch_id"]),
            batch_dir=str(raw["batch_dir"]),
            files=tuple(FileEntry.from_dict(f) for f in raw["files"]),
        )


@dataclass(frozen=True, slots=True)
class Manifest:
    """run 的 `manifest.json`（§4.2）。

    `tables`：表名 → 该表所依赖的 batch 登记列表；`ingestion_batch` 自身也在其中（R5），
    防止用改写的 batch 表「合法化」未登记文件。
    """

    run_id: str
    tables: dict[str, tuple[BatchRecord, ...]]
    config_hash: str
    git_commit: str
    result_sha256: str
    version: int = MANIFEST_VERSION

    def as_dict(self) -> dict[str, object]:
        return {
            "version": self.version,
            "run_id": self.run_id,
            "tables": {
                name: {
                    "batch_ids": [b.batch_id for b in batches],
                    "batches": [b.as_dict() for b in batches],
                }
                for name, batches in sorted(self.tables.items())
            },
            "config_hash": self.config_hash,
            "git_commit": self.git_commit,
            "result_sha256": self.result_sha256,
        }

    @classmethod
    def from_dict(cls, raw: dict) -> Manifest:
        return cls(
            version=int(raw.get("version", MANIFEST_VERSION)),
            run_id=str(raw["run_id"]),
            tables={
                name: tuple(BatchRecord.from_dict(b) for b in spec["batches"])
                for name, spec in raw["tables"].items()
            },
            config_hash=str(raw["config_hash"]),
            git_commit=str(raw["git_commit"]),
            result_sha256=str(raw["result_sha256"]),
        )

    def all_batches(self) -> tuple[BatchRecord, ...]:
        return tuple(b for batches in self.tables.values() for b in batches)

    def files_of(self, table: str) -> list[str]:
        """该表的显式文件列表（`read_parquet([...])` 用，不用 glob，§4.2 R1）。"""
        return [f.path for b in self.tables.get(table, ()) for f in b.files]


def _record_for_committed(root: Path, batch: CommittedBatch) -> BatchRecord:
    """把一次提交登记为 BatchRecord。

    文件列表与 sha **只来自提交时固定的 `batch_manifest/<batch_id>.json`**，绝不以目录
    现状为准（verify-a P1-3：否则建清单前塞进 batch 目录的文件会被就地合法化）。
    取证后立刻核对目录：缺文件 / sha 或 size 不符 / 多出未登记文件 → `ReplayIntegrityError`。
    """
    record = BatchRecord(
        batch_id=batch.batch_id,
        batch_dir=batch.batch_dir,
        files=_registered_files(root, batch.batch_id, batch.batch_dir),
    )
    _verify_record(root, record)
    return record


def _registered_files(root: Path, batch_id: str, batch_dir: str) -> tuple[FileEntry, ...]:
    """从提交时固定的 `batch_manifest/<batch_id>.json` 取该 batch 目录内的登记文件。"""
    manifest_abs = root / batch_manifest_path(batch_id)
    if not manifest_abs.is_file():
        raise ReplayIntegrityError(
            f"batch {batch_id} 无提交清单，不得进入 manifest: {manifest_abs}"
        )
    raw = json.loads(manifest_abs.read_text(encoding="utf-8"))
    if str(raw.get("batch_id")) != batch_id:
        raise ReplayIntegrityError(
            f"提交清单 batch_id 不符: 期望 {batch_id}，清单为 {raw.get('batch_id')!r}"
        )
    recorded_dir = str(raw.get("batch_dir", batch_dir))
    if recorded_dir != batch_dir:
        raise ReplayIntegrityError(
            f"batch {batch_id} 提交清单 batch_dir={recorded_dir!r} 与 {batch_dir!r} 不符"
        )
    prefix = batch_dir.rstrip("/") + "/"
    files = tuple(FileEntry.from_dict(e) for e in raw["parts"] if str(e["path"]).startswith(prefix))
    if not files:
        raise ReplayIntegrityError(f"batch {batch_id} 提交清单未登记任何 batch 目录内文件")
    return files


def _scan_dir(root: Path, directory: Path) -> list[FileEntry]:
    entries = [
        FileEntry(
            path=p.relative_to(root).as_posix(),
            sha256=parquet_io.file_sha256(p),
            size=p.stat().st_size,
        )
        for p in sorted(directory.rglob("*"))
        if p.is_file()
    ]
    return entries


#: `_insert_ingestion_batch_row` 每个 batch 目录只发布这一个文件——登记口径是固定结构，
#: 不是「目录里现在有什么」（verify-a P1-3 的同一条推理）。
INGESTION_BATCH_PART = "part-0000.parquet"


def _ingestion_batch_records(root: Path) -> tuple[BatchRecord, ...]:
    """R5：把 `ingestion_batch` 自身的每个 batch 目录登记进清单。

    该表由 `batches._insert_ingestion_batch_row` 独占发布，结构固定为「每 batch 目录
    恰好一个 `part-0000.parquet`」。按此固定结构取证，再核对目录：目录里多出的文件
    不会被登记，而是在 `_verify_record` 里变成 `ReplayIntegrityError`。
    """
    records: list[BatchRecord] = []
    for f in committed_batch_files(root):
        batch_dir = f.parent
        part = batch_dir / INGESTION_BATCH_PART
        if not part.is_file():
            raise ReplayIntegrityError(
                f"ingestion_batch batch 目录缺 {INGESTION_BATCH_PART}: {batch_dir}"
            )
        record = BatchRecord(
            batch_id=batch_dir.name.removeprefix("batch="),
            batch_dir=batch_dir.relative_to(root).as_posix(),
            files=(
                FileEntry(
                    path=part.relative_to(root).as_posix(),
                    sha256=parquet_io.file_sha256(part),
                    size=part.stat().st_size,
                ),
            ),
        )
        _verify_record(root, record)
        records.append(record)
    return tuple(records)


def build_manifest(
    root: str | os.PathLike[str],
    run_id: str,
    tables: dict[str, Sequence[CommittedBatch]],
    *,
    config_hash: str,
    git_commit: str,
    result_sha256: str = "",
) -> Manifest:
    """在 run 开始时刻按**已提交**的 batch 建 manifest（§4.2）。

    只有出现在 `ingestion_batch` 的 batch 才可进清单；未提交的 batch 传进来即报错。
    """
    root = Path(root)
    committed = {
        d.name.removeprefix("batch=") for f in committed_batch_files(root) for d in [f.parent]
    }
    records: dict[str, tuple[BatchRecord, ...]] = {}
    for name, batches in tables.items():
        for b in batches:
            if b.batch_id not in committed:
                raise ReplayIntegrityError(
                    f"batch {b.batch_id} 未出现在 ingestion_batch，不得进入 manifest（§4.3）"
                )
        records[name] = tuple(_record_for_committed(root, b) for b in batches)
    records["ingestion_batch"] = _ingestion_batch_records(root)
    return Manifest(
        run_id=assert_valid_id(run_id, field="run_id"),
        tables=records,
        config_hash=config_hash,
        git_commit=git_commit,
        result_sha256=result_sha256,
    )


def write_manifest(root: str | os.PathLike[str], manifest: Manifest) -> Path:
    """独占发布一个 run 的 `manifest.json`。

    同一 `run_id` 二次写入 → `ReplayIntegrityError`，**原文件字节不变**（verify-a P1-4：
    静默覆盖可以换掉重放的输入与基准 hash）。发布是原子的（staging 写完再 link），
    因此 `read_manifest` 永远读不到半个清单。
    """
    root = Path(root)
    path = root / run_manifest_path(manifest.run_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(manifest.as_dict(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    try:
        parquet_io.publish_text(path, payload, staging=publish_staging(root))
    except parquet_io.AlreadyPublishedError as exc:
        raise ReplayIntegrityError(
            f"run {manifest.run_id} 的 manifest 已发布，拒绝覆盖（请用新 run_id）: {path}"
        ) from exc
    return path


def read_manifest(root: str | os.PathLike[str], run_id: str) -> Manifest:
    path = Path(root) / run_manifest_path(run_id)
    if not path.is_file():
        raise ReplayIntegrityError(f"run {run_id} 无 manifest: {path}")
    return Manifest.from_dict(json.loads(path.read_text(encoding="utf-8")))


def _verify_record(root: Path, record: BatchRecord) -> None:
    """一个 batch 目录的「恰好等于」校验：不缺、不多、sha/size 一致。"""
    directory = root / record.batch_dir
    if not directory.is_dir():
        raise ReplayIntegrityError(f"清单内 batch 目录不存在: {record.batch_dir}")
    expected = {f.path: f for f in record.files}
    actual = {e.path: e for e in _scan_dir(root, directory)}

    missing = sorted(expected.keys() - actual.keys())
    if missing:
        raise ReplayIntegrityError(f"batch {record.batch_id} 缺文件: {missing}")
    extra = sorted(actual.keys() - expected.keys())
    if extra:
        raise ReplayIntegrityError(
            f"batch {record.batch_id} 目录内多出未登记文件（batch 目录提交后不可变）: {extra}"
        )
    for path, want in expected.items():
        got = actual[path]
        if got.size != want.size:
            raise ReplayIntegrityError(f"{path} size 不符: 期望 {want.size}，实际 {got.size}")
        if got.sha256 != want.sha256:
            raise ReplayIntegrityError(f"{path} sha256 不符: 期望 {want.sha256}，实际 {got.sha256}")


def verify_manifest(root: str | os.PathLike[str], manifest: Manifest) -> None:
    """R1 + R4：对清单内每个 batch 目录执行「恰好等于」校验。

    缺文件 / sha 或 size 不符 / 目录内多出未登记文件 → `ReplayIntegrityError`，
    不降级、不跳过。清单外目录一概不看（R3）。
    """
    root = Path(root)
    for record in manifest.all_batches():
        _verify_record(root, record)


def replay(
    root: str | os.PathLike[str],
    run_id: str,
    compute: Callable[[dict[str, list[str]]], pa.Table],
    *,
    columns: tuple[str, ...] | None = None,
) -> pa.Table:
    """重放一个 run（R1–R5）。

    先校验清单（读任何数据之前），再把**显式文件列表**交给 `compute`，最后按 R2 断言
    结果 Parquet 的 sha256 等于 manifest 的 `result_sha256`（manifest 未记则跳过比较，
    供首跑建立基准用）。
    """
    root = Path(root)
    manifest = read_manifest(root, run_id)
    verify_manifest(root, manifest)

    file_lists = {
        name: [str(root / p) for p in manifest.files_of(name)]
        for name in manifest.tables
        if name != "ingestion_batch"
    }
    result = compute(file_lists)
    actual_sha = parquet_io.table_sha256(result, columns)
    if manifest.result_sha256 and actual_sha != manifest.result_sha256:
        raise ReplayIntegrityError(
            f"R2 逐字节一致失败: result_sha256 期望 {manifest.result_sha256}，实际 {actual_sha}"
        )
    return result


def write_result(
    root: str | os.PathLike[str],
    run_id: str,
    table: pa.Table,
    *,
    name: str = "result.parquet",
    columns: tuple[str, ...] | None = None,
) -> tuple[Path, str]:
    """把 run 结果确定性写到 `data/runs/<run_id>/results/`，回传路径与 sha256。

    结果文件同样不可覆盖：同名二次写 → `ReplayIntegrityError`，原文件字节不变；
    且同样原子发布，不会出现半写的结果文件。
    """
    root = Path(root)
    results = root / run_results_dir(run_id)
    results.mkdir(parents=True, exist_ok=True)
    target = results / name
    try:
        sha = parquet_io.publish_table(table, target, columns, staging=publish_staging(root))
    except parquet_io.AlreadyPublishedError as exc:
        raise ReplayIntegrityError(
            f"run {run_id} 的结果 {name} 已发布，拒绝覆盖（请用新 run_id）: {target}"
        ) from exc
    return target, sha
