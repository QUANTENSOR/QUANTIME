"""DuckDB 视图层（ADR-0003 §4.2）：幂等注册、只 join 已提交 batch、显式文件列表。"""

from __future__ import annotations

from quantime_core.ids import new_batch_id, new_run_id
from quantime_data import batches, views


def test_register_views_is_idempotent(root):
    first = views.register_views(root)
    second = views.register_views(root)
    assert first == second == sorted(views.REGISTERED_MACROS)


def test_db_file_holds_no_business_rows(root, commit):
    commit()
    views.register_views(root)
    with views.connect(root) as con:
        tables = con.execute(
            "SELECT table_name FROM duckdb_tables() WHERE database_name = 'quantime'"
        ).fetchall()
    assert tables == []  # 只存视图/宏定义，不存业务行


def test_db_file_is_rebuildable_after_deletion(root, commit):
    b = commit()
    views.register_views(root)
    views.db_path(root).unlink()
    assert views.register_views(root) == sorted(views.REGISTERED_MACROS)
    rows = views.query_committed(root, [str(root / b.parts[0].path)])
    assert len(rows) == 3  # 丢掉 DB 文件不丢数据


def test_committed_rows_only_include_registered_batches(root, run_id, commit, make_table):
    b = commit()
    # 手工造一个未登记的 batch 目录（未出现在 ingestion_batch = 视为不存在，§4.3）。
    orphan_id = new_batch_id()
    orphan_table = make_table(
        source="synthetic_bench", batch_id=orphan_id, run_id=new_run_id(), price0=900.0
    )
    orphan_dir = root / b.batch_dir.replace(f"batch={b.batch_id}", f"batch={orphan_id}")
    orphan_dir.mkdir(parents=True)
    from quantime_core import parquet_io

    parquet_io.write_table(orphan_table, orphan_dir / "part-0000.parquet")

    files = [str(root / b.parts[0].path), str(orphan_dir / "part-0000.parquet")]
    rows = views.query_committed(root, files)
    assert len(rows) == 3
    assert {r[-1] for r in rows} == {b.batch_id}


def test_latest_per_source_takes_max_batch_id(root, run_id, commit, lake_kw, make_table):
    first = commit(price0=100.0)
    second_id = new_batch_id()
    second_table = make_table(
        source="synthetic_bench", batch_id=second_id, run_id=run_id, price0=200.0
    )
    second = batches.commit_batch(
        root,
        second_table,
        source="synthetic_bench",
        source_version="v1",
        run_id=run_id,
        batch_id=second_id,
        kind="rerun",
        rerun_of=first.batch_id,
        **lake_kw,
    )
    assert second.batch_id > first.batch_id

    files = [str(root / first.parts[0].path), str(root / second.parts[0].path)]
    rows = views.query_latest_per_source(root, files, keys=["symbol", "ts"])
    assert len(rows) == 3
    assert {r[-1] for r in rows} == {second.batch_id}  # 只剩最大 batch_id 的版本


def test_license_drop_batches_are_excluded_from_committed_view(root, run_id, commit, lake_kw):
    b = commit()
    batches.append_license_drop(
        root, source="synthetic_bench", source_version="v1", run_id=run_id, **lake_kw
    )
    rows = views.query_committed(root, [str(root / b.parts[0].path)])
    assert len(rows) == 3  # ingest 行仍在；墓碑行本身不进数据视图


def test_ingestion_batch_file_list_is_explicit_not_glob(root, commit):
    commit()
    commit()
    files = views.ingestion_batch_files(root)
    assert len(files) == 2
    assert all(f.endswith(".parquet") and "*" not in f for f in files)


def test_empty_lake_returns_nothing(root):
    assert views.query_committed(root, []) == []
    assert views.query_latest_per_source(root, [], keys=["symbol"]) == []
