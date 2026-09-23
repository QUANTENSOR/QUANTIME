"""运行前 / 写入前的守卫（QNT-45 R8）——磁盘不足拒开 batch、拉代码失败留记录、数据根写法统一。

* 磁盘守卫：数据根所在文件系统剩余 < 阈值（默认 5 GB，`--min-free-gb` 可配）→ 不开新 batch，
  run_log `abort_reason=disk_low`，报告 coverage `failed` 并写明原因，退出码 1。
  `shutil.disk_usage` 用 monkeypatch 模拟，不碰真实磁盘。
* `record-abort --reason pull_failed`：systemd `ExecStopPost` 在 `git pull --ff-only` 失败时
  调它；主进程没跑过，这一笔就是当天唯一的痕迹。
* `--root`：owner 统一写法 `…/quantime/data`（数据目录本身）与旧写法（含 `data/` 的父目录）
  落到同一处，不会写出 `data/data/…`。
"""

from __future__ import annotations

import collections
import datetime as dt
import json
from pathlib import Path

import pytest
from fixture_source import NOW, FixtureFetcher, snapshot, spot_1d
from quantime_core.ids import new_run_id
from quantime_data import batches, cli, daily, diskguard, report, runlog

D = dt.date
GB = 1024**3
Usage = collections.namedtuple("Usage", "total used free")


@pytest.fixture
def disk(monkeypatch):
    """可调的「剩余空间」；记录被量的是哪条路径。"""
    state = {"free": 100 * GB, "paths": []}

    def fake_usage(path):
        state["paths"].append(Path(path))
        return Usage(total=200 * GB, used=200 * GB - state["free"], free=state["free"])

    monkeypatch.setattr(diskguard.shutil, "disk_usage", fake_usage)
    return state


def _run(root, specs, **kw):
    return daily.run_daily(
        root,
        specs,
        FixtureFetcher(),
        run_id=new_run_id(),
        sleep=lambda s: None,
        monotonic=lambda: 0.0,
        now=NOW,
        **kw,
    )


def _has_batches(root) -> bool:
    return (Path(root) / "data" / "meta" / "ingestion_batch").exists() and bool(
        batches.read_ingestion_batch(root).num_rows
    )


# ---- 磁盘守卫 ----


def test_low_disk_refuses_to_start_a_batch_and_reports_failed_with_the_reason(root, disk):
    disk["free"] = 4 * GB  # < 默认 5 GB
    (root / "data").mkdir()
    out = _run(root, [spot_1d(D(2026, 8, 1), D(2026, 8, 31))])

    assert not _has_batches(root), "磁盘不足时开了 batch"
    assert not list((root / "data").glob("raw/**/*.parquet"))
    assert out.exit_code == 1
    assert out.log.abort_reason == "disk_low"
    assert out.report.coverage == "failed"
    assert out.report.coverage_of("binance_vision") == "failed"
    (series,) = out.report.series
    assert (series.status, series.error_class) == ("failed", "disk_low")
    assert series.missing_archives, "缺档要进报告，磁盘腾出来后按报告补采"
    assert any("disk_low" in f and "4.00 GB" in f and "5.00 GB" in f for f in out.report.failures)
    log = json.loads(runlog.run_log_path(root, out.run_id).read_text(encoding="utf-8"))
    assert (log["abort_reason"], log["outcome"]) == ("disk_low", "failed")
    data = report.load_report(report.report_paths(root, out.report)[0])
    assert (data["coverage"], data["abort_reason"]) == ("failed", "disk_low")
    # 量的是数据目录（它可能是指向别的盘的软链接），不是 root。
    assert disk["paths"] and all(p == root / "data" for p in disk["paths"])


def test_enough_disk_ingests_normally(root, disk):
    disk["free"] = 6 * GB
    out = _run(root, [spot_1d(D(2026, 8, 1), D(2026, 8, 31))])
    assert out.exit_code == 0 and out.log.abort_reason is None
    assert out.report.coverage == "complete" and _has_batches(root)


def test_the_threshold_is_configurable_and_zero_disables_it(root, disk, monkeypatch, tmp_path):
    disk["free"] = 4 * GB
    assert _run(root, [spot_1d(D(2026, 8, 1), D(2026, 8, 2))], min_free_bytes=3 * GB).exit_code == 0
    fetch = FixtureFetcher()
    monkeypatch.setattr(cli, "_http_opener", lambda: None)
    monkeypatch.setattr(cli, "_fetcher", lambda transport: fetch)
    universe = tmp_path / "u.yaml"
    universe.write_text("version: 1\nspot:\n  freqs: ['1d']\n  symbols: [BTCUSDT]\n")
    base = ["--root", str(root), "--universe", str(universe), "daily", "--datatype", "kline"]

    def day(d):
        return ["--start", f"2026-08-{d:02d}", "--end", f"2026-08-{d:02d}"]

    assert cli.main([*base, *day(3)]) == 1  # 默认 5 GB
    assert cli.main([*base, *day(4), "--min-free-gb", "3"]) == 0
    assert cli.main([*base, *day(5), "--min-free-gb", "0"]) == 0


def test_a_disk_low_series_is_resumed_by_since_last_once_space_is_back(root, disk):
    """被守卫拦下的首跑同样记 pending 起点：腾出空间后的 `--since-last` 从原起点续取。"""
    disk["free"] = 1 * GB
    spec = spot_1d(D(2026, 8, 20), D(2026, 8, 20))
    _run(root, [spec], since_last=True)
    disk["free"] = 50 * GB
    out = _run(root, [spot_1d(D(2026, 8, 25), D(2026, 8, 25))], since_last=True)
    (series,) = out.report.series
    assert series.status == "ok" and series.rows == 6  # 8-20..8-25


# ---- record-abort（systemd ExecStopPost 的 pull_failed）----


def test_record_abort_leaves_a_failed_report_and_run_log_without_touching_the_lake(root, capsys):
    (root / "data").mkdir()
    before = snapshot(root)
    code = cli.main(
        ["--root", str(root / "data"), "record-abort", "--reason", "pull_failed",
         "--detail", "git pull --ff-only 失败（SERVICE_RESULT=exit-code）"]
    )  # fmt: skip
    assert code == 1
    summary = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert (summary["abort_reason"], summary["coverage"]) == ("pull_failed", "failed")
    data = report.load_report(summary["report_json"])
    assert (data["mode"], data["abort_reason"], data["coverage"]) == (
        "aborted",
        "pull_failed",
        "failed",
    )
    assert data["series"] == []
    log = json.loads(runlog.run_log_path(root, summary["run_id"]).read_text(encoding="utf-8"))
    assert log["abort_reason"] == "pull_failed" and log["outcome"] == "failed"
    new = set(snapshot(root)) - set(before)
    assert all(p.startswith(("data/runs/", "data/reports/")) for p in new), new
    assert not _has_batches(root)
    # 汇总把它算成非 complete → 非零退出，owner 在报告汇总里就能看到。
    lines, rc = report.summarize_reports(root, data_date(data))
    assert rc == 1 and any("abort_reason=pull_failed" in line for line in lines)


def data_date(data) -> dt.date:
    return dt.date.fromisoformat(data["report_date"])


def test_record_abort_only_accepts_known_reasons(root):
    with pytest.raises(SystemExit):
        cli.main(["--root", str(root), "record-abort", "--reason", "whatever"])


# ---- --root 的两种写法 ----


def test_root_accepts_the_data_dir_itself_or_its_parent(tmp_path):
    parent = tmp_path / "quantime"
    (parent / "data").mkdir(parents=True)
    assert cli.resolve_root(parent / "data") == parent
    assert cli.resolve_root(parent) == parent
    # 一个真叫 data、里面又有 data/ 的父目录：它就是「含 data/ 的那一层」，原样。
    odd = tmp_path / "data"
    (odd / "data").mkdir(parents=True)
    assert cli.resolve_root(odd) == odd


def test_root_through_a_symlinked_data_dir_writes_into_the_link_target(tmp_path, capsys):
    """常驻布局：`/home/workspace/quantime/data` → 软链接到另一处。写入落在链接目标里。"""
    checkout = tmp_path / "quantime"
    checkout.mkdir()
    target = tmp_path / "quantime-data"
    target.mkdir()
    (checkout / "data").symlink_to(target)
    assert cli.main(["--root", str(checkout / "data"), "record-abort", "--reason", "disk_low"]) == 1
    capsys.readouterr()
    assert list(target.glob("runs/*/run_log.json")) and list(target.glob("reports/*/*.json"))
    assert not (target / "data").exists(), "写出了 data/data/"
    assert sorted(p.name for p in checkout.iterdir()) == ["data"]


def test_root_defaults_to_the_environment_variable(tmp_path, monkeypatch, capsys):
    data = tmp_path / "quantime" / "data"
    data.mkdir(parents=True)
    monkeypatch.setenv(cli.DATA_ROOT_ENV, str(data))
    assert cli.main(["record-abort", "--reason", "pull_failed"]) == 1
    capsys.readouterr()
    assert list(data.glob("runs/*/run_log.json"))


# ---- R9：守卫在全部写入口共用的「开 batch」边界（`ingest_one` 开头）----

INGEST_ARGS = [
    "ingest", "--datatype", "kline", "--symbol", "BTCUSDT",
    "--start", "2026-08-01", "--end", "2026-08-31", "--as-of", "2026-09-21",
]  # fmt: skip


@pytest.fixture
def ingest_cli(root, tmp_path, monkeypatch):
    """`cli.main` 走离线 FixtureFetcher；回传 `(跑一次, fetch)`。"""
    fetch = FixtureFetcher()
    monkeypatch.setattr(cli, "_http_opener", lambda: None)
    monkeypatch.setattr(cli, "_fetcher", lambda transport: fetch)
    universe = tmp_path / "u.yaml"
    universe.write_text("version: 1\nspot:\n  freqs: ['1d']\n  symbols: [BTCUSDT]\n")

    def run(*extra: str) -> int:
        return cli.main(["--root", str(root), "--universe", str(universe), *INGEST_ARGS, *extra])

    return run, fetch


def _assert_disk_low_abort(root, capsys, disk, fetch, code, *, batches_before: int) -> None:
    assert len(disk["paths"]) >= 1, "没有量磁盘"
    assert fetch.urls == [], "磁盘不足却发了请求"
    rows = batches.read_ingestion_batch(root).num_rows if batches_before else 0
    assert rows == batches_before, "磁盘不足却开了 batch"
    assert code != 0
    summary = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert (summary["abort_reason"], summary["coverage"]) == ("disk_low", "failed")
    log = json.loads(runlog.run_log_path(root, summary["run_id"]).read_text(encoding="utf-8"))
    assert (log["abort_reason"], log["outcome"]) == ("disk_low", "failed")
    assert any("1.00 GB" in n and "5.00 GB" in n for n in log["notes"]), log["notes"]
    data = report.load_report(summary["report_json"])
    assert (data["coverage"], data["abort_reason"]) == ("failed", "disk_low")
    assert any("1.00 GB" in f and "5.00 GB" in f for f in data["failures"])


def test_ingest_cli_refuses_to_open_a_batch_when_the_disk_is_low(root, disk, ingest_cli, capsys):
    run, fetch = ingest_cli
    disk["free"] = 1 * GB
    code = run()
    _assert_disk_low_abort(root, capsys, disk, fetch, code, batches_before=0)
    assert not _has_batches(root)


def test_ingest_rerun_of_refuses_to_open_a_batch_when_the_disk_is_low(
    root, disk, ingest_cli, capsys
):
    run, fetch = ingest_cli
    assert run() == 0  # 空间充足时先有一个可重跑的 batch
    capsys.readouterr()
    (original,) = batches.read_ingestion_batch(root).column("batch_id").to_pylist()
    before = snapshot(root)
    disk["free"] = 1 * GB
    disk["paths"].clear()
    fetch.urls.clear()
    code = run("--rerun-of", original)
    _assert_disk_low_abort(root, capsys, disk, fetch, code, batches_before=1)
    new = set(snapshot(root)) - set(before)
    assert all(p.startswith(("data/runs/", "data/reports/")) for p in new), new


def test_ingest_with_min_free_gb_zero_commits_even_when_the_disk_is_low(
    root, disk, ingest_cli, capsys
):
    """只有显式 `--min-free-gb 0` 能放行——证明上两条拦下的确实是守卫，而不是别的原因。"""
    run, fetch = ingest_cli
    disk["free"] = 1 * GB
    assert run("--min-free-gb", "0") == 0
    assert fetch.urls and _has_batches(root)
    assert not disk["paths"], "守卫关闭时不该再量磁盘"


def test_ingest_min_free_gb_defaults_to_the_environment_variable(
    root, disk, ingest_cli, monkeypatch
):
    run, _ = ingest_cli
    disk["free"] = 1 * GB
    monkeypatch.setenv(cli.MIN_FREE_GB_ENV, "0.5")
    assert run() == 0 and _has_batches(root)


def test_backfill_goes_through_the_same_guard(root, disk):
    """补采也经 `ingest_one`：按一份 disk_low 报告补采，磁盘仍不足 → 同样拦下、不开 batch。"""
    disk["free"] = 1 * GB
    first = _run(root, [spot_1d(D(2026, 8, 1), D(2026, 8, 31))])
    fetch = FixtureFetcher()
    out = daily.run_backfill_from_report(
        root,
        report.report_paths(root, first.report)[0],
        fetch,
        run_id=new_run_id(),
        sleep=lambda s: None,
        monotonic=lambda: 0.0,
        now=NOW,
    )
    assert fetch.urls == [] and not _has_batches(root)
    assert (out.exit_code, out.log.abort_reason, out.report.coverage) == (1, "disk_low", "failed")


def test_the_disk_guard_lives_in_exactly_one_place():
    """静态兜底：量磁盘只在 `diskguard`，调用守卫只在 `ingest_one`——入口不得各带一份。"""
    pkg = Path(diskguard.__file__).parent
    measures = {p.name for p in pkg.glob("*.py") if "disk_usage(" in p.read_text("utf-8")}
    callers = {p.name for p in pkg.glob("*.py") if "    check_disk(root" in p.read_text("utf-8")}
    assert measures == {"diskguard.py"}
    assert callers == {"ingest.py"}
    assert (pkg / "ingest.py").read_text("utf-8").count("    check_disk(root") == 1
