"""重放硬验收 R1–R5（ADR-0003 §4.2）。"""

from __future__ import annotations

import pyarrow as pa
import pytest
from quantime_core import parquet_io
from quantime_core.ids import new_batch_id, new_run_id
from quantime_data import batches
from quantime_data import replay as replay_mod
from quantime_data.replay import ReplayIntegrityError, build_manifest, replay, write_manifest

RESULT_COLUMNS = ("symbol", "total")


def _compute(file_lists: dict[str, list[str]]) -> pa.Table:
    """确定性聚合：只读 manifest 给出的显式文件列表。"""
    files = sorted(file_lists["kline"])
    tables = [parquet_io.read_table(f) for f in files]
    if not tables:
        return pa.table({"symbol": pa.array([], pa.string()), "total": pa.array([], pa.float64())})
    combined = pa.concat_tables(tables)
    grouped = combined.group_by("symbol").aggregate([("close", "sum")])
    return pa.table(
        {
            "symbol": grouped.column("symbol").cast(pa.string()),
            "total": grouped.column("close_sum").cast(pa.float64()),
        }
    ).sort_by("symbol")


def _make_run(root, run_id, committed):
    manifest = build_manifest(
        root,
        run_id,
        {"kline": committed},
        config_hash="cfg-v1",
        git_commit="dd97896",
    )
    first = _compute(
        {"kline": [str(root / f.path) for b in manifest.tables["kline"] for f in b.files]}
    )
    _, sha = replay_mod.write_result(root, run_id, first, columns=RESULT_COLUMNS)
    manifest = replay_mod.Manifest(
        run_id=manifest.run_id,
        tables=manifest.tables,
        config_hash=manifest.config_hash,
        git_commit=manifest.git_commit,
        result_sha256=sha,
    )
    write_manifest(root, manifest)
    return manifest, first


def test_r1_happy_path_replays_and_matches_result_sha(root, run_id, commit):
    b = commit()
    _, first = _make_run(root, run_id, [b])
    again = replay(root, run_id, _compute, columns=RESULT_COLUMNS)
    assert again.equals(first)


def test_r5_ingestion_batch_itself_is_in_the_manifest(root, run_id, commit):
    b = commit()
    manifest, _ = _make_run(root, run_id, [b])
    ib = manifest.tables["ingestion_batch"]
    assert [r.batch_id for r in ib] == [b.batch_id]
    assert any(f.path.startswith("data/meta/ingestion_batch/") for r in ib for f in r.files)


def test_r5_mutating_ingestion_batch_file_is_rejected(root, run_id, commit):
    b = commit()
    manifest, _ = _make_run(root, run_id, [b])
    target = root / manifest.tables["ingestion_batch"][0].files[0].path
    raw = bytearray(target.read_bytes())
    raw[-1] ^= 0xFF
    target.write_bytes(bytes(raw))
    with pytest.raises(ReplayIntegrityError):
        replay(root, run_id, _compute, columns=RESULT_COLUMNS)


def test_r4_flipping_one_byte_is_rejected(root, run_id, commit):
    # R4 ①：翻转一字节 → ReplayIntegrityError。
    b = commit()
    _make_run(root, run_id, [b])
    target = root / b.parts[0].path
    raw = bytearray(target.read_bytes())
    raw[len(raw) // 2] ^= 0x01
    target.write_bytes(bytes(raw))
    with pytest.raises(ReplayIntegrityError, match="sha256 不符|size 不符"):
        replay(root, run_id, _compute, columns=RESULT_COLUMNS)


def test_r4_deleting_a_file_is_rejected(root, run_id, commit):
    # R4 ②：删文件 → ReplayIntegrityError。
    b = commit()
    _make_run(root, run_id, [b])
    (root / b.parts[0].path).unlink()
    with pytest.raises(ReplayIntegrityError, match="缺文件|batch 目录不存在"):
        replay(root, run_id, _compute, columns=RESULT_COLUMNS)


def test_r4_extra_unregistered_part_inside_listed_batch_dir_is_rejected(root, run_id, commit):
    # R4 ③：清单内 batch=<id>/ 目录下新增 part-0001.parquet → ReplayIntegrityError。
    b = commit()
    _make_run(root, run_id, [b])
    extra = root / b.batch_dir / "part-0001.parquet"
    extra.write_bytes((root / b.parts[0].path).read_bytes())
    with pytest.raises(ReplayIntegrityError, match="多出未登记文件"):
        replay(root, run_id, _compute, columns=RESULT_COLUMNS)


def test_r3_late_batch_outside_manifest_does_not_break_replay(
    root, run_id, commit, lake_kw, make_table
):
    """R3：batch 1 开始 → batch 2 提交 → run 建 manifest（只含 2）→ batch 1 之后提交。

    replay 通过校验（batch 1 在清单外，不扫描），结果与首跑逐字节一致且不含 batch 1 的行。
    """
    late_id = new_batch_id()  # batch 1：先分配（ULID 更小），后提交
    b2 = commit(price0=100.0)  # batch 2：先提交
    manifest, first = _make_run(root, run_id, [b2])
    assert [r.batch_id for r in manifest.tables["kline"]] == [b2.batch_id]

    late_table = make_table(
        source="synthetic_bench", batch_id=late_id, run_id=new_run_id(), price0=500.0
    )
    late = batches.commit_batch(
        root,
        late_table,
        source="synthetic_bench",
        source_version="v1",
        run_id=new_run_id(),
        batch_id=late_id,
        **lake_kw,
    )
    assert late.batch_id < b2.batch_id  # 低序号 batch 后提交（乱序提交）
    assert (root / late.batch_dir).is_dir()
    # 同分区：晚到 batch 与 batch 2 在同一 source= 目录下。
    assert (root / late.batch_dir).parent == (root / b2.batch_dir).parent

    again = replay(root, run_id, _compute, columns=RESULT_COLUMNS)
    assert again.equals(first)
    assert parquet_io.table_sha256(again, RESULT_COLUMNS) == manifest.result_sha256
    assert max(again.column("total").to_pylist()) < 500.0  # 不含 batch 1 的行


def test_r3_result_differs_if_late_batch_were_included(root, run_id, commit, lake_kw, make_table):
    """反证：若把晚到 batch 也纳入计算，结果会不同——证明 R3 的「不含」是真断言。"""
    b2 = commit(price0=100.0)
    _, first = _make_run(root, run_id, [b2])
    late_id = new_batch_id()
    late_table = make_table(
        source="synthetic_bench", batch_id=late_id, run_id=new_run_id(), price0=500.0
    )
    late = batches.commit_batch(
        root,
        late_table,
        source="synthetic_bench",
        source_version="v1",
        run_id=new_run_id(),
        batch_id=late_id,
        **lake_kw,
    )
    with_late = _compute({"kline": [str(root / b2.parts[0].path), str(root / late.parts[0].path)]})
    assert not with_late.equals(first)


def test_r2_result_sha_mismatch_is_rejected(root, run_id, commit):
    b = commit()
    manifest, _ = _make_run(root, run_id, [b])
    tampered = replay_mod.Manifest(
        run_id=manifest.run_id,
        tables=manifest.tables,
        config_hash=manifest.config_hash,
        git_commit=manifest.git_commit,
        result_sha256="0" * 64,
    )
    write_manifest(root, tampered)
    with pytest.raises(ReplayIntegrityError, match="R2"):
        replay(root, run_id, _compute, columns=RESULT_COLUMNS)


def test_manifest_rejects_uncommitted_batch(root, run_id, commit):
    b = commit()
    fake = batches.CommittedBatch(
        batch_id=new_batch_id(),
        source="synthetic_bench",
        batch_dir=b.batch_dir,
        parts=b.parts,
        raw_files=(),
        manifest_path=b.manifest_path,
        content_sha256=b.content_sha256,
        row_count=3,
        kind="ingest",
        rerun_of=None,
    )
    with pytest.raises(ReplayIntegrityError, match="未出现在 ingestion_batch"):
        build_manifest(root, run_id, {"kline": [fake]}, config_hash="c", git_commit="g")


def test_manifest_roundtrip_and_explicit_file_list(root, run_id, commit):
    b = commit()
    manifest, _ = _make_run(root, run_id, [b])
    reloaded = replay_mod.read_manifest(root, run_id)
    assert reloaded.as_dict() == manifest.as_dict()
    files = reloaded.files_of("kline")
    assert files == [b.parts[0].path]
    assert "*" not in "".join(files)  # 显式文件列表，不是 glob


def test_replay_without_manifest_raises(root):
    with pytest.raises(ReplayIntegrityError, match="无 manifest"):
        replay(root, new_run_id(), _compute, columns=RESULT_COLUMNS)
