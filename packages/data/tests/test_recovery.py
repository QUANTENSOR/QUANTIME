"""断档恢复、失败序列入报告、按报告重建补采任务（QNT-45 R3 / R4 / R5）——全程离线。

* R3：`--since-last` 下起点**只**取水位线次日；`--start` 只在没有水位线时生效，被忽略时
  run_log 记一条说明。unit 因此不再传 `--start yesterday`——关机一周后 timer 只补跑一次
  （`Persistent=true` 的语义），那一次从水位线接着取，缺的每一天都回来。
* R4：失败序列也进 `report.series`（status / error_class / attempts / elapsed）；有任何失败，
  全局与分源覆盖都不是 `complete`；`totals.retries` 含失败侧；汇总按 JSON 字段读。
* R5：失败序列保留结构化 spec + 缺档（url/covers_start/covers_end）；`plan_backfill` 同时从
  失败序列与成功序列的缺档建 task；有 batch → `rerun`+`rerun_of`，
  无 batch → `ingest`+`from_report`。
"""

from __future__ import annotations

import datetime as dt
import json

import pytest
from fixture_source import (
    NOW,
    SPOT_KLINE_SPEC,
    FixtureFetcher,
    ScriptedFetcher,
    spot_1d,
    synthetic_daily_kline,
    synthetic_kline_zip,
)
from quantime_core.ids import new_run_id
from quantime_core.paths import AssetClass, DataType, Freq
from quantime_data import backfill, batches, cli, daily, report, runlog
from quantime_data.retry import RetryPolicy
from quantime_data.sources import binance_public as bp
from quantime_data.spec import IngestSpec
from quantime_data.transport import RateLimitedError

D = dt.date
H1_URL = bp.kline_url("spot", "BTCUSDT", "1h", "2026-08")
JULY_URL = bp.kline_url("spot", "BTCUSDT", "1d", "2026-07")
AUG_URL = bp.kline_url("spot", "BTCUSDT", "1d", "2026-08")
SEP15 = D(2026, 9, 15)

#: 录制外的现货 1h：它唯一的归档（8 月月档）在离线回放里 404 → 整条序列失败。
SPOT_1H_SPEC = IngestSpec(
    datatype=DataType.KLINE,
    asset_class=AssetClass.SPOT,
    symbol="BTCUSDT",
    freq=Freq.H1,
    start=D(2026, 8, 1),
    end=D(2026, 8, 31),
)
#: 只有一天、那一天的日档当时 404 的序列（R5「单日全缺」）。
ONE_DAY_SPEC = spot_1d(SEP15, SEP15)


class Clock:
    def __init__(self) -> None:
        self.now = 0.0
        self.slept: list[float] = []

    def sleep(self, s: float) -> None:
        self.slept.append(s)
        self.now += s

    def monotonic(self) -> float:
        return self.now


@pytest.fixture
def clock() -> Clock:
    return Clock()


def _run(root, specs, fetch, clock, **kw):
    kw.setdefault("now", NOW)
    return daily.run_daily(
        root,
        specs,
        fetch,
        run_id=new_run_id(),
        sleep=clock.sleep,
        monotonic=clock.monotonic,
        **kw,
    )


def _backfill(root, report_path, fetch, clock):
    return daily.run_backfill_from_report(
        root,
        report_path,
        fetch,
        run_id=new_run_id(),
        sleep=clock.sleep,
        monotonic=clock.monotonic,
        now=NOW + dt.timedelta(days=1),
    )


def _batch_rows(root):
    t = batches.read_ingestion_batch(root)
    rows = [
        dict(zip(t.column_names, row, strict=True))
        for row in zip(*t.to_pydict().values(), strict=True)
    ]
    return [r for r in rows if not r["scope"].startswith("audit__")]


def _july_zip() -> bytes:
    start = dt.datetime(2026, 7, 1, tzinfo=dt.UTC)
    return synthetic_kline_zip("BTCUSDT-1d-2026-07.csv", start, dt.timedelta(days=1), 31)


# ---- R3：从水位线恢复 ----


def test_since_last_resumes_from_the_watermark_not_from_start(root, clock):
    """R3 验收：已提交 08-01..20，之后一次 08-25 的窗口 → 实际请求 08-21..25。"""
    _run(root, [spot_1d(D(2026, 8, 1), D(2026, 8, 20))], FixtureFetcher(), clock)
    out = _run(
        root, [spot_1d(D(2026, 8, 25), D(2026, 8, 25))], FixtureFetcher(), clock, since_last=True
    )
    (result,) = out.results
    assert (result.spec.start, result.spec.end) == (D(2026, 8, 21), D(2026, 8, 25))
    assert result.committed.row_count == 5
    rec = runlog.read_run_log(root, out.run_id)
    assert any("--start 2026-08-25 被忽略" in n and "2026-08-21" in n for n in rec["notes"])


def test_without_a_watermark_the_requested_start_still_applies(root, clock):
    out = _run(
        root, [spot_1d(D(2026, 8, 25), D(2026, 8, 31))], FixtureFetcher(), clock, since_last=True
    )
    (result,) = out.results
    assert (result.spec.start, result.committed.row_count) == (D(2026, 8, 25), 7)
    assert runlog.read_run_log(root, out.run_id)["notes"] == []


@pytest.fixture
def offline_cli(monkeypatch):
    fetch = FixtureFetcher()
    monkeypatch.setattr(cli, "_http_opener", lambda: None)
    monkeypatch.setattr(cli, "_fetcher", lambda transport: fetch)
    return fetch


def _universe(tmp_path, freqs="['1d']"):
    path = tmp_path / "universe.yaml"
    path.write_text(
        f"version: 1\nspot:\n  freqs: {freqs}\n  symbols: [BTCUSDT]\n", encoding="utf-8"
    )
    return path


def test_the_cli_daily_without_start_recovers_every_missed_day(
    root, offline_cli, capsys, tmp_path, clock
):
    """unit 的新写法：只给 `--end` + `--since-last`。停机 11 天后的那一次运行把 11 天都取回。"""
    _run(root, [spot_1d(D(2026, 8, 1), D(2026, 8, 20))], FixtureFetcher(), clock)
    argv = [
        "--root", str(root), "--universe", str(_universe(tmp_path)),
        "daily", "--end", "2026-08-31", "--since-last",
    ]  # fmt: skip
    assert cli.main(argv) == 0
    summary = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert (summary["ok"], summary["rows"]) == (1, 11)


def test_the_cli_daily_without_start_or_watermark_takes_only_the_end_day(
    root, offline_cli, capsys, tmp_path
):
    argv = [
        "--root", str(root), "--universe", str(_universe(tmp_path)),
        "daily", "--end", "2026-08-31", "--since-last",
    ]  # fmt: skip
    assert cli.main(argv) == 0
    summary = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert summary["rows"] == 1


# ---- R4：失败序列进报告，覆盖不再是 complete ----


def test_a_failed_series_is_in_the_report_and_the_run_is_never_complete(root, clock):
    """R4 验收：一成功 + 一整档 404 → exit=1、coverage≠complete、retries 含失败侧。"""
    fetch = FixtureFetcher(fail_urls={H1_URL: [RateLimitedError("429")]})  # 先限流一次再 404
    out = _run(
        root,
        [SPOT_KLINE_SPEC, SPOT_1H_SPEC],
        fetch,
        clock,
        retry_policy=RetryPolicy(max_attempts=3, base_delay=1.0),
    )
    assert out.exit_code == 1
    assert out.report.coverage != "complete"
    assert out.report.coverage == "failed"

    data = report.load_report(report.report_paths(root, out.report)[0])
    ok, failed = data["series"]
    assert (ok["status"], ok["coverage"]) == ("ok", "complete")
    assert failed["status"] == "failed" and failed["coverage"] == "failed"
    assert failed["error_class"] == "IngestError"
    assert failed["attempts"] == 2 and failed["retries"] == 1
    assert failed["elapsed_seconds"] == pytest.approx(1.0)  # 那一次 1s 的退避算在它头上
    assert failed["batch_id"] is None
    assert failed["missing_archives"] == [
        {
            "filename": "BTCUSDT-1h-2026-08.zip",
            "url": H1_URL,
            "covers_start": "2026-08-01",
            "covers_end": "2026-08-31",
        }
    ]
    assert data["totals"]["retries"] == 1  # 成功侧 0 + 失败侧 1
    assert data["totals"]["failed_series"] == 1 and data["totals"]["failures"] == 1
    (src,) = data["sources"]
    assert src["coverage"] == "failed"
    md = report.report_paths(root, out.report)[1].read_text(encoding="utf-8")
    assert "IngestError" in md and SPOT_1H_SPEC.describe() in md


def test_retry_exhaustion_is_reported_with_its_root_cause(root, clock):
    fetch = FixtureFetcher(fail_urls={H1_URL: [RateLimitedError("429")] * 10})
    out = _run(
        root, [SPOT_1H_SPEC], fetch, clock, retry_policy=RetryPolicy(max_attempts=3, base_delay=1.0)
    )
    (s,) = out.report.series
    assert (s.status, s.attempts, s.retries) == ("failed", 3, 2)
    assert s.error_class == "RetryExhaustedError(RateLimitedError)"
    assert out.report.total_retries == 2


def test_report_summary_reads_the_json_fields_and_exits_non_zero_on_failure(root, clock, capsys):
    out = _run(root, [SPOT_KLINE_SPEC, SPOT_1H_SPEC], FixtureFetcher(), clock)
    lines, code = report.summarize_reports(root, NOW.date())
    assert code == 1
    (line,) = lines
    assert "coverage=failed" in line and "failed_series=1" in line

    date = NOW.date().isoformat()
    assert cli.main(["--root", str(root), "report-summary", "--date", date]) == 1
    assert f"{out.run_id}" in capsys.readouterr().out


def test_report_summary_is_zero_only_when_every_report_is_complete(root, clock, capsys):
    _run(root, [SPOT_KLINE_SPEC], FixtureFetcher(), clock)
    date = NOW.date().isoformat()
    assert cli.main(["--root", str(root), "report-summary", "--date", date]) == 0
    assert "coverage=complete" in capsys.readouterr().out
    assert cli.main(["--root", str(root), "report-summary", "--date", "2026-01-01"]) == 1


# ---- R5：从报告重建补采任务 ----


@pytest.fixture
def one_day_failed(root, clock):
    """09-15 当天日档 404 → 整条序列失败，报告里 `batch_id=null`，缺档 = 那一个日档。"""
    out = _run(root, [ONE_DAY_SPEC], FixtureFetcher(), clock)
    (s,) = out.report.series
    assert s.status == "failed" and s.batch_id is None
    return report.report_paths(root, out.report)[0]


def test_a_single_day_that_failed_entirely_becomes_one_ingest_task(one_day_failed):
    """R5 验收：单日全缺 → tasks=1，`kind='ingest'` + `from_report`。"""
    (task,) = backfill.plan_backfill(one_day_failed).tasks
    assert task.filename == "BTCUSDT-1d-2026-09-15.zip"
    assert (task.kind, task.rerun_of) == ("ingest", None)
    assert task.from_report == one_day_failed.as_posix()
    assert (task.spec.start, task.spec.end) == (SEP15, SEP15)


def test_backfilling_a_failed_series_writes_an_ingest_batch_that_names_its_report(
    root, clock, one_day_failed
):
    url, payload = synthetic_daily_kline("spot", "1d", SEP15)
    out = _backfill(root, one_day_failed, ScriptedFetcher(extra={url: payload}), clock)
    assert out.exit_code == 0
    assert out.report.coverage == "complete"
    (row,) = _batch_rows(root)
    assert (row["kind"], row["rerun_of"]) == ("ingest", None)
    manifest = json.loads((root / row["manifest_path"]).read_text(encoding="utf-8"))
    assert manifest["from_report"] == one_day_failed.as_posix()


def test_a_mixed_report_plans_tasks_from_both_sides(root, clock):
    """R5 验收：成功序列的缺档 + 失败序列的缺档 → tasks = 两侧之和。"""
    gap = spot_1d(D(2026, 7, 1), D(2026, 8, 31))  # 7 月在、8 月当时 404 → ok + 1 缺档
    fetch = ScriptedFetcher(extra={JULY_URL: _july_zip()}, gone={AUG_URL})
    out = _run(root, [gap, ONE_DAY_SPEC], fetch, clock)
    ok, failed = out.report.series
    assert (ok.status, failed.status) == ("ok", "failed")
    report_path = report.report_paths(root, out.report)[0]

    tasks = backfill.plan_backfill(report_path).tasks
    assert len(tasks) == len(ok.missing_archives) + len(failed.missing_archives) == 2
    by_name = {t.filename: t for t in tasks}
    assert by_name["BTCUSDT-1d-2026-08.zip"].kind == "rerun"
    assert by_name["BTCUSDT-1d-2026-08.zip"].rerun_of == ok.batch_id
    assert by_name["BTCUSDT-1d-2026-09-15.zip"].kind == "ingest"

    url, payload = synthetic_daily_kline("spot", "1d", SEP15)
    after = _backfill(
        root, report_path, ScriptedFetcher(extra={JULY_URL: _july_zip(), url: payload}), clock
    )
    assert after.exit_code == 0 and after.report.coverage == "complete"
    kinds = sorted((r["kind"], r["rerun_of"]) for r in _batch_rows(root))
    assert kinds == [("ingest", None), ("ingest", None), ("rerun", ok.batch_id)]
