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
from quantime_data import batches, cli, daily, report, runlog

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

    monkeypatch.setattr(daily.shutil, "disk_usage", fake_usage)
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
