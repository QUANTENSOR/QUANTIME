"""原子发布的并发/中断回归（QNT-27 返修 R2，verify-a 第二轮 P1）。

「独占创建」不等于「原子发布」：在最终路径上 `O_CREAT|O_EXCL` 之后再写 payload，
创建与写入之间该路径以 size=0 可见，并发读侧会把在途文件当成已提交内容登记进 manifest，
待写入落定后旧 run 的 R3/R5 校验就被打破——不需要任何人篡改文件。

本模块用 `threading.Event` 在**确定的程序点**（tmp 写完、`os.link` 之前）暂停发布线程，
不靠 sleep 赌时序：主线程不放行，发布线程就一直停在那里。
"""

from __future__ import annotations

import threading

import pytest
from conftest import LAKE_KW, build_table
from quantime_core import parquet_io
from quantime_core.ids import new_batch_id
from quantime_data import batches
from quantime_data import replay as replay_mod
from quantime_data.batches import BatchWriteError

#: 单个 Event 的等待上限。到点即视为「发布线程没走到预期程序点」——测试失败，不是放行。
TIMEOUT = 30


class _PublishGate:
    """在 `_link_exclusive`（tmp 已完整落盘并 close，尚未发布）处闸住指定的最终路径。

    只控制时序：payload、返回值、异常一律原样透传。
    """

    def __init__(self, monkeypatch, *, match: str):
        self.match = match
        self.reached = threading.Event()
        self.release = threading.Event()
        self.tmp_path: str | None = None
        real = parquet_io._link_exclusive

        def gated(tmp, target):
            if self.match in str(target):
                self.tmp_path = str(tmp)
                self.reached.set()
                assert self.release.wait(TIMEOUT), "闸门未被放行"
            return real(tmp, target)

        monkeypatch.setattr(parquet_io, "_link_exclusive", gated)

    def wait_until_paused(self) -> None:
        assert self.reached.wait(TIMEOUT), f"发布线程未走到 {self.match} 的发布点"


def _commit_in_thread(root, run_id, batch_id, errors):
    table = build_table(source="synthetic_bench", batch_id=batch_id, run_id=run_id)

    def _run():
        try:
            batches.commit_batch(
                root,
                table,
                source="synthetic_bench",
                source_version="v1",
                run_id=run_id,
                batch_id=batch_id,
                **LAKE_KW,
            )
        except BaseException as exc:  # 交回主线程断言，不在子线程里吞掉
            errors.append(exc)

    t = threading.Thread(target=_run, name="committer")
    t.start()
    return t


def test_in_flight_batch_is_invisible_to_readers_until_publish_lands(root, run_id, monkeypatch):
    """发布前：读侧看不到在途 batch，最终路径不存在（更不会是 size=0）。

    闸在 `ingestion_batch` 行的发布点——湖 Parquet 与提交清单此时都已落定，只差最后
    这一步 insert。旧实现在这里已经能让 `committed_batch_files` 返回一个 size=0 的文件。
    """
    bid = new_batch_id()
    errors: list[BaseException] = []
    gate = _PublishGate(monkeypatch, match="ingestion_batch")
    t = _commit_in_thread(root, run_id, bid, errors)
    try:
        gate.wait_until_paused()

        meta_dir = root / "data" / "meta" / "ingestion_batch" / f"batch={bid}"
        final = meta_dir / "part-0000.parquet"
        assert not final.exists(), "最终路径在发布前已可见（旧实现是 size=0 的半成品）"
        assert batches.committed_batch_files(root) == [], "在途 batch 已被枚举为已提交"
        # 在途 tmp 也不得落在最终目录里——否则它会被 `_verify_record` 的目录扫描
        # 当成「多出未登记文件」，把正常并发提交变成 R4 失败。
        assert not (meta_dir.exists() and any(meta_dir.iterdir())), (
            f"最终目录里出现在途文件: {sorted(p.name for p in meta_dir.iterdir())}"
        )

        manifest = replay_mod.build_manifest(
            root, run_id, {}, config_hash="cfg-v1", git_commit="dd97896"
        )
        assert manifest.tables["ingestion_batch"] == (), "在途 batch 进了 manifest"
        replay_mod.verify_manifest(root, manifest)

        # tmp 确实已经写完整了，只是还在枚举范围之外。
        assert gate.tmp_path is not None
        assert "_staging" in gate.tmp_path
    finally:
        gate.release.set()
        t.join(TIMEOUT)
    assert not t.is_alive()
    assert errors == []
    assert len(batches.committed_batch_files(root)) == 1


def test_manifest_built_before_publish_still_verifies_after_it_lands(root, run_id, monkeypatch):
    """R3：在途 batch 落定后，**此前**建的清单校验结果不变。

    这是 verify-a 复现的收尾断言：旧实现下同一个 manifest 在放行后会抛
    `size 不符: 期望 0，实际 3832`——正常并发提交打破了旧 run 的可重放性。
    """
    first = batches.commit_batch(
        root,
        build_table(source="synthetic_bench", batch_id=(b0 := new_batch_id()), run_id=run_id),
        source="synthetic_bench",
        source_version="v1",
        run_id=run_id,
        batch_id=b0,
        **LAKE_KW,
    )
    manifest = replay_mod.build_manifest(
        root, run_id, {"kline": [first]}, config_hash="cfg-v1", git_commit="dd97896"
    )
    replay_mod.verify_manifest(root, manifest)
    before = manifest.as_dict()

    late = new_batch_id()
    errors: list[BaseException] = []
    gate = _PublishGate(monkeypatch, match="ingestion_batch")
    t = _commit_in_thread(root, run_id, late, errors)
    try:
        gate.wait_until_paused()
        replay_mod.verify_manifest(root, manifest)  # 暂停中仍然成立
    finally:
        gate.release.set()
        t.join(TIMEOUT)
    assert not t.is_alive()
    assert errors == []

    # 晚到 batch 已经落定……
    assert len(batches.committed_batch_files(root)) == 2
    # ……而此前那份清单一字未变，且校验依然通过。
    assert manifest.as_dict() == before
    replay_mod.verify_manifest(root, manifest)


def test_interrupted_write_leaves_no_final_file_and_no_visible_residue(
    root, run_id, monkeypatch, lake_kw, make_table
):
    """写入中断：最终路径不存在；`_staging/` 的残片不进任何枚举；同 batch_id 仍被锁住。"""
    bid = new_batch_id()
    boom = RuntimeError("模拟写 tmp 中途进程退出")
    real_fsync = parquet_io.os.fsync

    def exploding_fsync(fd):
        real_fsync(fd)
        raise boom

    monkeypatch.setattr(parquet_io.os, "fsync", exploding_fsync)
    with pytest.raises(RuntimeError, match="模拟写 tmp"):
        batches.commit_batch(
            root,
            make_table(source="synthetic_bench", batch_id=bid, run_id=run_id),
            source="synthetic_bench",
            source_version="v1",
            run_id=run_id,
            batch_id=bid,
            **lake_kw,
        )
    monkeypatch.undo()

    part = root / "data" / "lake" / "crypto" / "spot" / "kline" / "1d" / "BTCUSDT"
    assert not any(part.rglob("*.parquet")), "中断后最终路径出现了文件"
    assert not (root / batches.batch_manifest_path(bid)).exists()
    assert batches.committed_batch_files(root) == []

    # 模拟硬退出留下的 staging 残片：它在枚举范围之外，读侧一概看不见。
    staging = batches.publish_staging(root)
    staging.mkdir(parents=True, exist_ok=True)
    (staging / ".publish-crashed.tmp").write_bytes(b"half written")
    assert batches.committed_batch_files(root) == []
    manifest = replay_mod.build_manifest(
        root, run_id, {}, config_hash="cfg-v1", git_commit="dd97896"
    )
    assert manifest.all_batches() == ()
    replay_mod.verify_manifest(root, manifest)

    # 同 batch_id 重提交的行为与 P1-1 一致：锁已被登记，直接拒绝。
    with pytest.raises(BatchWriteError, match="已被登记"):
        batches.commit_batch(
            root,
            make_table(source="synthetic_bench", batch_id=bid, run_id=run_id),
            source="synthetic_bench",
            source_version="v1",
            run_id=run_id,
            batch_id=bid,
            **lake_kw,
        )


def test_publish_writes_its_tmp_outside_every_enumerated_directory(root, run_id, monkeypatch):
    """tmp 必须落在 `data/_staging/`——不在湖 batch 目录、也不在 ingestion_batch 目录内。

    把 tmp 写进最终目录同样能做到「link 前完整」，但那份 tmp 会被 `_verify_record` 的
    目录扫描当成「多出未登记文件」，把正常并发提交变成 R4 失败。
    """
    seen: list[str] = []
    real = parquet_io._write_tmp

    def recording(staging_root, payload):
        tmp = real(staging_root, payload)
        seen.append(tmp.relative_to(root).as_posix())
        return tmp

    monkeypatch.setattr(parquet_io, "_write_tmp", recording)
    bid = new_batch_id()
    batches.commit_batch(
        root,
        build_table(source="synthetic_bench", batch_id=bid, run_id=run_id),
        source="synthetic_bench",
        source_version="v1",
        run_id=run_id,
        batch_id=bid,
        **LAKE_KW,
    )
    assert len(seen) == 3, f"最终文件应恰好三个（湖 part / 提交清单 / ingestion_batch 行）: {seen}"
    for rel in seen:
        assert rel.startswith("data/_staging/"), f"tmp 落在了枚举范围内: {rel}"
        assert "/lake/" not in rel and "ingestion_batch" not in rel
