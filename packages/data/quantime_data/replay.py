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

from .batches import CommittedBatch, FileEntry, committed_batch_files

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
    """把一次提交登记为 BatchRecord：文件集合取 batch 目录下**实际全部**文件。"""
    return BatchRecord(
        batch_id=batch.batch_id,
        batch_dir=batch.batch_dir,
        files=tuple(_scan_dir(root, Path(root) / batch.batch_dir)),
    )


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


def _ingestion_batch_records(root: Path) -> tuple[BatchRecord, ...]:
    """R5：把 `ingestion_batch` 自身的每个 batch 目录登记进清单。"""
    records: list[BatchRecord] = []
    for f in committed_batch_files(root):
        batch_dir = f.parent
        records.append(
            BatchRecord(
                batch_id=batch_dir.name.removeprefix("batch="),
                batch_dir=batch_dir.relative_to(root).as_posix(),
                files=tuple(_scan_dir(root, batch_dir)),
            )
        )
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
    path = Path(root) / run_manifest_path(manifest.run_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(manifest.as_dict(), indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return path


def read_manifest(root: str | os.PathLike[str], run_id: str) -> Manifest:
    path = Path(root) / run_manifest_path(run_id)
    if not path.is_file():
        raise ReplayIntegrityError(f"run {run_id} 无 manifest: {path}")
    return Manifest.from_dict(json.loads(path.read_text(encoding="utf-8")))


def verify_manifest(root: str | os.PathLike[str], manifest: Manifest) -> None:
    """R1 + R4：对清单内每个 batch 目录执行「恰好等于」校验。

    缺文件 / sha 或 size 不符 / 目录内多出未登记文件 → `ReplayIntegrityError`，
    不降级、不跳过。清单外目录一概不看（R3）。
    """
    root = Path(root)
    for record in manifest.all_batches():
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
                raise ReplayIntegrityError(
                    f"{path} sha256 不符: 期望 {want.sha256}，实际 {got.sha256}"
                )


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
    """把 run 结果确定性写到 `data/runs/<run_id>/results/`，回传路径与 sha256。"""
    results = Path(root) / run_results_dir(run_id)
    results.mkdir(parents=True, exist_ok=True)
    target = results / name
    sha = parquet_io.write_table(table, target, columns)
    return target, sha
