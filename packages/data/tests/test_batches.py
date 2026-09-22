"""append-only 写入 API（ADR-0003 §4.3；验收：覆盖拒绝 / 单源不变量 / provenance 五列）。"""

from __future__ import annotations

import pytest
from quantime_core.ids import new_batch_id
from quantime_core.paths import PROVENANCE_COLUMNS
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


def _snapshot(root):
    """root 下所有文件的 `相对路径 → bytes`（逐字节比较用）。"""
    return {
        p.relative_to(root).as_posix(): p.read_bytes()
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


def test_same_batch_id_second_commit_leaves_every_file_byte_identical(
    root, run_id, commit, lake_kw, make_table
):
    """P1-1：同 batch_id 二次提交必须在**任何落盘之前**失败。

    这里换掉 scope（第二次走另一个 lake 目录，原 batch 目录的「非空」早退检查够不着），
    全局唯一性只能由 batch_manifest 独占登记来保证。断言第一次的所有落盘文件逐字节不变，
    且 `_staging/` 无残留。
    """
    first = commit()
    before = _snapshot(root)
    assert before  # 第一次确实落了盘

    other = dict(lake_kw, scope="ETHUSDT")
    table = make_table(source="synthetic_bench", batch_id=first.batch_id, run_id=run_id, price0=9.0)
    with pytest.raises(BatchWriteError, match="已被登记"):
        batches.commit_batch(
            root,
            table,
            source="synthetic_bench",
            source_version="v1",
            run_id=run_id,
            batch_id=first.batch_id,
            **other,
        )

    assert _snapshot(root) == before, "二次提交改动了已落盘的字节（append-only 被破坏）"
    staging = root / "data" / "_staging"
    assert not staging.exists() or not any(staging.rglob("*")), "_staging/ 有残留"


def _lake_is_empty(root) -> bool:
    """湖里与 meta 下一个字节都没有——用来断言「拒绝发生在任何落盘之前」。"""
    return (
        not (root / "data" / "lake").exists()
        and not (root / "data" / "meta" / "ingestion_batch").exists()
    )


def test_claim_is_reentrant_only_for_the_holder_that_took_it(root, run_id, lake_kw, make_table):
    """`claim=` 只让**独占取到锁的那一次调用**重入。

    摄取链路要在 `commit_batch` 之前写 raw 副本，所以必须能提前取锁再把它传回来。
    这条钉住：真凭证通过，别的 batch 的凭证不通过。
    """
    bid = new_batch_id()
    claim = batches.claim_batch_id(root, bid)
    other = batches.claim_batch_id(root, new_batch_id())
    table = make_table(source="synthetic_bench", batch_id=bid, run_id=run_id)

    # 另一个 batch 的真凭证也不行——凭证绑定到具体 batch_id。
    with pytest.raises(BatchWriteError, match="不符"):
        batches.commit_batch(
            root,
            table,
            source="synthetic_bench",
            source_version="v1",
            run_id=run_id,
            batch_id=bid,
            claim=other,
            **lake_kw,
        )

    # 真正持有者可以继续提交。
    committed = batches.commit_batch(
        root,
        table,
        source="synthetic_bench",
        source_version="v1",
        run_id=run_id,
        batch_id=bid,
        claim=claim,
        **lake_kw,
    )
    assert committed.batch_id == bid


def test_a_forged_path_is_not_a_claim_even_when_the_lock_does_not_exist(
    root, run_id, lake_kw, make_table
):
    """R1 P1：没取过锁、凭 `root / batch_claim_path(bid)` 构造一个 Path 传进来 → 拒绝。

    修复前这条能过：`claim=` 只比较 Path 值，而那个值任何人都算得出来（`batch_id` 和
    `root` 都是公开信息），锁文件甚至根本不必存在。凭证必须是**独占取得**的产物。
    """
    bid = new_batch_id()
    table = make_table(source="synthetic_bench", batch_id=bid, run_id=run_id)
    forged = root / batches.batch_claim_path(bid)
    assert not forged.exists(), "前提：锁根本没被取过"

    with pytest.raises(BatchWriteError, match="不是 claim_batch_id 返回的所有权凭证"):
        batches.commit_batch(
            root,
            table,
            source="synthetic_bench",
            source_version="v1",
            run_id=run_id,
            batch_id=bid,
            claim=forged,
            **lake_kw,
        )
    assert _lake_is_empty(root), "拒绝发生在落盘之后（应在任何字节之前）"


def test_third_party_cannot_reuse_a_lock_another_holder_took(root, run_id, lake_kw, make_table):
    """R1 P1：别的 run 已经取走锁，第三方构造同一路径想蹭进去 → 拒绝。

    这是上一条的「锁存在」变体：文件在那儿、路径也对，但第三方手里没有取锁时生成的
    nonce，而锁文件只落了 nonce 的 sha256——读一遍文件也拼不出凭证。
    """
    bid = new_batch_id()
    holder = batches.claim_batch_id(root, bid)  # 「别的 run」取走了锁
    table = make_table(source="synthetic_bench", batch_id=bid, run_id=run_id)
    lock = root / batches.batch_claim_path(bid)
    assert lock.is_file()
    assert holder.nonce not in lock.read_text(encoding="ascii"), "锁文件不得泄露 nonce 本身"

    with pytest.raises(BatchWriteError, match="不是 claim_batch_id 返回的所有权凭证"):
        batches.commit_batch(
            root,
            table,
            source="synthetic_bench",
            source_version="v1",
            run_id=run_id,
            batch_id=bid,
            claim=lock,
            **lake_kw,
        )
    assert _lake_is_empty(root)


def test_a_fabricated_claim_object_with_a_guessed_nonce_is_rejected(
    root, run_id, lake_kw, make_table
):
    """R1 P1：连 `BatchClaim` 都自己造一个（类型对、路径对、nonce 猜的）→ 仍然拒绝。

    上一条挡的是「传错类型」，这条挡的是「类型也对」——校验的最后一环是锁文件里登记的
    digest 与凭证的 nonce 对不对得上，不是对象长什么样。
    """
    bid = new_batch_id()
    batches.claim_batch_id(root, bid)
    table = make_table(source="synthetic_bench", batch_id=bid, run_id=run_id)
    fabricated = batches.BatchClaim(
        batch_id=bid, path=root / batches.batch_claim_path(bid), nonce="0" * 32
    )

    with pytest.raises(BatchWriteError, match="锁已被另一次取得"):
        batches.commit_batch(
            root,
            table,
            source="synthetic_bench",
            source_version="v1",
            run_id=run_id,
            batch_id=bid,
            claim=fabricated,
            **lake_kw,
        )
    assert _lake_is_empty(root)


def test_a_claim_whose_lock_vanished_is_rejected(root, run_id, lake_kw, make_table):
    """锁文件被外力删掉后，旧凭证不再有效——它已经不是「当前这把锁」的凭证了。

    否则「删锁 → 旧持有者照样重入」就等于唯一性登记可以被绕过一次。
    """
    bid = new_batch_id()
    claim = batches.claim_batch_id(root, bid)
    (root / batches.batch_claim_path(bid)).unlink()
    table = make_table(source="synthetic_bench", batch_id=bid, run_id=run_id)

    with pytest.raises(BatchWriteError, match="唯一性登记已不存在"):
        batches.commit_batch(
            root,
            table,
            source="synthetic_bench",
            source_version="v1",
            run_id=run_id,
            batch_id=bid,
            claim=claim,
            **lake_kw,
        )
    assert _lake_is_empty(root)


def test_concurrent_contention_for_one_batch_id_leaves_exactly_one_winner(root):
    """并发争用同一个 batch_id：恰好一个线程取到锁，其余全部被拒。

    `O_CREAT|O_EXCL` 的独占性是这里唯一的仲裁者，所以直接压线程去撞它，而不是串行调两次
    （串行只能证明「第二次被拒」，证不了「同时来只过一个」）。
    """
    import threading

    bid = new_batch_id()
    barrier = threading.Barrier(8)
    won: list[batches.BatchClaim] = []
    lost: list[BatchWriteError] = []
    lock = threading.Lock()

    def attempt() -> None:
        barrier.wait()
        try:
            claim = batches.claim_batch_id(root, bid)
        except BatchWriteError as exc:
            with lock:
                lost.append(exc)
        else:
            with lock:
                won.append(claim)

    threads = [threading.Thread(target=attempt) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(won) == 1, f"{len(won)} 个线程同时取到了同一个 batch_id 的锁"
    assert len(lost) == 7
    # 赢家的凭证确实对应盘上那把锁。
    on_disk = (root / batches.batch_claim_path(bid)).read_text(encoding="ascii")
    assert won[0].digest() in on_disk


def test_a_lock_file_records_only_the_digest_never_the_nonce(root):
    """锁文件全世界可读；写进去的必须是 nonce 的 sha256，不是 nonce 本身。

    落 nonce 本身 = 任何读到文件的人都能拼出有效凭证，等于没有凭证。
    """
    bid = new_batch_id()
    claim = batches.claim_batch_id(root, bid)
    text = (root / batches.batch_claim_path(bid)).read_text(encoding="ascii")
    assert claim.nonce not in text
    assert claim.digest() in text
    assert bid in text


def test_uniqueness_claim_precedes_any_write(root, run_id, lake_kw, make_table):
    """P1-1：唯一性登记发生在任何字节落盘之前——只登记、不提交，后续提交即被拒。"""
    bid = new_batch_id()
    batches._claim_batch_id(root, bid)  # 模拟「该 batch_id 已被别的 run 取走」
    table = make_table(source="synthetic_bench", batch_id=bid, run_id=run_id)
    with pytest.raises(BatchWriteError, match="已被登记"):
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
    assert not (root / "data" / "meta" / "ingestion_batch").exists()


def test_columns_projection_dropping_provenance_is_rejected_before_any_write(
    root, run_id, lake_kw, make_table
):
    """P1-2：完整合法表 + `columns=('symbol','close')` → 拒绝，且目录无新文件。

    校验对象是**最终落盘的 schema**（投影之后）；投影掉 ADR-0002 五列即缺列。
    """
    bid = new_batch_id()
    table = make_table(source="synthetic_bench", batch_id=bid, run_id=run_id)
    assert all(c in table.column_names for c in PROVENANCE_COLUMNS)  # 入参本身合法

    with pytest.raises(BatchWriteError, match="provenance"):
        batches.commit_batch(
            root,
            table,
            source="synthetic_bench",
            source_version="v1",
            run_id=run_id,
            batch_id=bid,
            columns=("symbol", "close"),
            **lake_kw,
        )
    assert not (root / "data" / "lake").exists()
    assert not (root / "data" / "meta" / "ingestion_batch").exists()
    staging = root / "data" / "_staging"
    assert not staging.exists() or not any(staging.rglob("*"))


def test_columns_projection_keeping_provenance_is_accepted_and_shapes_the_file(
    root, run_id, lake_kw, make_table
):
    """反证：保留五列的投影仍然可用，且落盘文件确实按投影后的列序写。"""
    bid = new_batch_id()
    table = make_table(source="synthetic_bench", batch_id=bid, run_id=run_id)
    cols = ("symbol", "close", *PROVENANCE_COLUMNS)
    b = batches.commit_batch(
        root,
        table,
        source="synthetic_bench",
        source_version="v1",
        run_id=run_id,
        batch_id=bid,
        columns=cols,
        **lake_kw,
    )
    from quantime_core import parquet_io

    written = parquet_io.read_table(root / b.parts[0].path)
    assert tuple(written.column_names) == cols
    assert parquet_io.file_sha256(root / b.parts[0].path) == b.content_sha256


def test_publishing_over_an_existing_final_file_is_refused_not_overwritten(root, run_id, commit):
    """最终文件一律「不存在才发布」：带外放一个同名 part 后重发布 → 拒绝且原字节不变。"""
    from quantime_core import parquet_io

    b = commit()
    target = root / b.parts[0].path
    before = target.read_bytes()
    with pytest.raises(parquet_io.AlreadyPublishedError):
        parquet_io.publish_bytes(target, b"tampered", staging=batches.publish_staging(root))
    assert target.read_bytes() == before


def test_final_part_publish_refuses_an_existing_file_even_if_earlier_checks_pass(
    root, run_id, commit, lake_kw, make_table, monkeypatch
):
    """P1-1b：最终 Parquet 的发布本身必须是「不存在才写」。

    唯一性锁与目录非空早退是前两道闸；这条测试把它们都拆掉（模拟 TOCTOU：检查通过之后
    目标文件才出现），验证最后一道——`os.link` 独占创建——仍然拒绝，且原文件字节不变。
    换成 `os.replace` 会静默盖写。
    """
    first = commit()
    target = root / first.parts[0].path
    before = target.read_bytes()

    monkeypatch.setattr(batches, "_claim_batch_id", lambda root, batch_id, holder=None: None)
    monkeypatch.setattr(batches, "_assert_empty_target", lambda batch_dir: None)

    table = make_table(source="synthetic_bench", batch_id=first.batch_id, run_id=run_id, price0=7.0)
    with pytest.raises(BatchWriteError, match="最终文件已存在"):
        batches.commit_batch(
            root,
            table,
            source="synthetic_bench",
            source_version="v1",
            run_id=run_id,
            batch_id=first.batch_id,
            **lake_kw,
        )
    assert target.read_bytes() == before
