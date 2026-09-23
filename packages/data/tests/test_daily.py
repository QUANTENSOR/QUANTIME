"""每日运行编排（QNT-45 第 1–4 项）的离线集成测试——全程走录制 fixture，不出网。

覆盖卡验收：
* `--since-last` 区间推算；空增量不写 batch 但写运行记录；
* 失败退避重试 → 成功；重试用尽 → 非零退出 + 运行记录；无半写文件；
* 按报告补采：`kind='rerun'` + `rerun_of` 的**新** batch，被补的 batch 一个字节不动，
  补后重核 `partial → complete`；白名单里的上游缺失不重试；
* 报告 JSON 与 Markdown 同源、发布路径只 insert。

变异点 (c)「补采写成覆盖而非新批次」必须在这里变红。
"""

from __future__ import annotations

import datetime as dt
import json

import pytest
from fixture_source import (
    FUNDING_SPEC,
    NOW,
    OI_SPEC,
    SPOT_KLINE_SPEC,
    FixtureFetcher,
    snapshot,
    spot_1d,
)
from quantime_core.ids import new_run_id
from quantime_core.parquet_io import AlreadyPublishedError
from quantime_data import backfill, batches, cli, daily, report, runlog
from quantime_data.retry import RetryPolicy
from quantime_data.sources import binance_public as bp
from quantime_data.transport import RateLimitedError
from quantime_data.upstream_missing import load_upstream_missing

AUG_URL = bp.kline_url("spot", "BTCUSDT", "1d", "2026-08")
SEP_URL = bp.kline_url("spot", "BTCUSDT", "1d", "2026-09")


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


def _batch_rows(root):
    t = batches.read_ingestion_batch(root)
    return [
        dict(zip(t.column_names, row, strict=True))
        for row in zip(*t.to_pydict().values(), strict=True)
    ]


# ---- 第 1 项：增量 ----


def test_first_since_last_run_takes_the_whole_range(root, clock):
    out = _run(root, [SPOT_KLINE_SPEC], FixtureFetcher(), clock, since_last=True)
    assert out.exit_code == 0
    assert out.results[0].committed.row_count == 31
    assert "首次全量" in out.increments[0]


def test_since_last_only_fetches_and_commits_the_new_days(root, clock):
    _run(root, [spot_1d(dt.date(2026, 8, 1), dt.date(2026, 8, 20))], FixtureFetcher(), clock)
    out = _run(root, [SPOT_KLINE_SPEC], FixtureFetcher(), clock, since_last=True)
    (result,) = out.results
    assert (result.spec.start, result.spec.end) == (dt.date(2026, 8, 21), dt.date(2026, 8, 31))
    assert result.committed.row_count == 11
    assert out.report.total_rows == 11
    assert "增量 2026-08-21..2026-08-31" in out.increments[0]


def test_an_empty_increment_writes_a_run_record_but_no_batch(root, clock):
    _run(root, [SPOT_KLINE_SPEC], FixtureFetcher(), clock)
    before = len(_batch_rows(root))
    fetch = FixtureFetcher()
    out = _run(root, [SPOT_KLINE_SPEC], fetch, clock, since_last=True)
    assert fetch.urls == []  # 连一次请求都没发
    assert len(_batch_rows(root)) == before
    assert out.exit_code == 0
    assert out.log.skipped_count == 1
    rec = runlog.read_run_log(root, out.run_id)
    assert rec["totals"]["skipped_empty_increment"] == 1
    assert rec["series"][0]["action"] == "skipped_empty_increment"
    assert rec["series"][0]["batch_id"] is None


def test_each_since_last_run_is_its_own_insert_only_batch(root, clock):
    _run(root, [spot_1d(dt.date(2026, 8, 1), dt.date(2026, 8, 10))], FixtureFetcher(), clock)
    first = snapshot(root)
    _run(root, [SPOT_KLINE_SPEC], FixtureFetcher(), clock, since_last=True)
    after = snapshot(root)
    assert {k: after[k] for k in first} == first
    kinds = [r["kind"] for r in _batch_rows(root)]
    assert kinds == ["ingest", "ingest"]


# ---- 第 2 项：重试 ----


def test_a_rate_limited_archive_is_retried_with_backoff_then_committed(root, clock):
    fetch = FixtureFetcher(
        fail_urls={AUG_URL: [RateLimitedError("429 (1)"), RateLimitedError("429 (2)")]}
    )
    out = _run(root, [SPOT_KLINE_SPEC], fetch, clock, retry_policy=RetryPolicy(base_delay=1.0))
    assert out.exit_code == 0
    assert clock.slept == [1.0, 2.0]
    assert out.log.total_retries == 2
    assert out.report.series[0].retries == 2
    assert len(out.retry_log) == 2 and "退避 1s" in out.retry_log[0]


def test_exhausted_retries_exit_non_zero_with_a_run_record_and_no_half_written_files(root, clock):
    fetch = FixtureFetcher(fail_urls={AUG_URL: [RateLimitedError("429")] * 10})
    out = _run(
        root,
        [SPOT_KLINE_SPEC],
        fetch,
        clock,
        retry_policy=RetryPolicy(max_attempts=3, base_delay=1.0),
    )
    assert out.exit_code == 1
    assert out.log.outcome == runlog.OUTCOME_FAILED
    rec = runlog.read_run_log(root, out.run_id)
    assert rec["exit_code"] == 1 and rec["series"][0]["error"]
    assert _batch_rows(root) == []
    assert not list((root / "data").glob("lake/**/*.parquet"))
    staging = root / "data" / "_staging"
    assert not staging.exists() or not any(staging.iterdir())


def test_one_failing_series_does_not_stop_the_others_but_the_run_is_non_zero(root, clock):
    """部分失败退 0 的话，systemd 会把半成功的运行记成 SUCCESS。"""
    fetch = FixtureFetcher(fail_urls={AUG_URL: [RateLimitedError("429")] * 10})
    out = _run(
        root,
        [SPOT_KLINE_SPEC, FUNDING_SPEC],
        fetch,
        clock,
        retry_policy=RetryPolicy(max_attempts=2, base_delay=0.5),
    )
    assert out.log.outcome == runlog.OUTCOME_PARTIAL
    assert out.exit_code == 1
    assert len(out.results) == 1 and out.results[0].spec == FUNDING_SPEC
    assert len(out.report.failures) == 1


def test_upstream_404_is_recorded_as_missing_not_retried(root, clock):
    fetch = FixtureFetcher()
    out = _run(root, [spot_1d(dt.date(2026, 8, 1), dt.date(2026, 9, 10))], fetch, clock)
    assert clock.slept == []
    assert fetch.urls.count(SEP_URL) == 1
    (series,) = out.report.series
    assert series.coverage == "partial"
    assert series.missing_upstream == ("BTCUSDT-1d-2026-09.zip",)


# ---- 第 4 项：报告 ----


def test_the_report_is_published_as_json_and_markdown_from_one_source(root, clock):
    out = _run(root, [SPOT_KLINE_SPEC, FUNDING_SPEC, OI_SPEC], FixtureFetcher(), clock)
    json_path, md_path = report.report_paths(root, out.report)
    assert json_path.parent == root / "data" / "reports" / NOW.date().isoformat()
    data = report.load_report(json_path)
    md = md_path.read_text(encoding="utf-8")
    assert data["coverage"] == "complete"
    assert data["totals"]["series"] == 3
    assert data["totals"]["rows"] == sum(s["rows"] for s in data["series"])
    assert f"新增行数: {data['totals']['rows']}" in md
    for s in data["series"]:
        assert set(report.SERIES_FIELDS) <= set(s)
        assert s["spec"] in md
    assert [x["source"] for x in data["sources"]] == ["binance_vision"]


def test_a_report_can_never_be_published_twice_for_the_same_run(root, clock):
    out = _run(root, [SPOT_KLINE_SPEC], FixtureFetcher(), clock)
    before = snapshot(root)
    with pytest.raises(AlreadyPublishedError):
        report.publish_report(root, out.report)
    with pytest.raises(AlreadyPublishedError):
        runlog.publish_run_log(root, out.log)
    assert snapshot(root) == before


def test_a_run_that_audited_nothing_is_not_reported_complete(root, clock):
    out = _run(root, [], FixtureFetcher(), clock)
    assert out.report.coverage == "partial"


def test_the_report_loader_rejects_unknown_schema_versions(root, clock, tmp_path):
    out = _run(root, [SPOT_KLINE_SPEC], FixtureFetcher(), clock)
    json_path, _ = report.report_paths(root, out.report)
    data = json.loads(json_path.read_text(encoding="utf-8"))
    data["schema_version"] = 99
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="schema"):
        report.load_report(bad)
    del data["series"][0]["batch_id"]
    data["schema_version"] = report.REPORT_SCHEMA_VERSION
    bad.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="缺字段"):
        report.load_report(bad)


# ---- 第 3 项：补采 ----


JULY_URL = bp.kline_url("spot", "BTCUSDT", "1d", "2026-07")


def _synthetic_july_zip() -> bytes:
    """合成的 2026-07 日线归档（测试内生成、不落 fixtures/）：只为让「有一档在、一档缺」成立。"""
    import io
    import zipfile

    rows = []
    for day in range(1, 32):
        t0 = int(dt.datetime(2026, 7, day, tzinfo=dt.UTC).timestamp() * 1000)
        rows.append(f"{t0},1,2,0.5,1.5,10,{t0 + 86_399_999},15,7,5,7.5,0")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("BTCUSDT-1d-2026-07.csv", "\n".join(rows) + "\n")
    return buf.getvalue()


class ScriptedFetcher(FixtureFetcher):
    """在录制之上叠一层剧本：`extra` 额外可取的 URL，`gone` 当作 404 的 URL。"""

    def __init__(self, *, extra=None, gone=(), **kw) -> None:
        super().__init__(**kw)
        self.extra = dict(extra or {})
        self.gone = set(gone)

    def __call__(self, url: str) -> bytes:
        base = url.removesuffix(".CHECKSUM")
        if base in self.gone:
            self.urls.append(url)
            raise FileNotFoundError(url)
        if base in self.extra:
            self.urls.append(url)
            if url.endswith(".CHECKSUM"):
                raise FileNotFoundError(url)  # 合成档无校验文件 = 不可核对，不是错误
            return self.extra[base]
        return super().__call__(url)


GAP_SPEC = spot_1d(dt.date(2026, 7, 1), dt.date(2026, 8, 31))


@pytest.fixture
def gappy(root, clock):
    """首跑：7 月档在、8 月档当时 404 → 报告 `partial`，缺 `BTCUSDT-1d-2026-08.zip`。

    回传 `(报告路径, 原 batch_id)`。之后 8 月档"恢复"（录制里本来就有），用来补采。
    """
    fetch = ScriptedFetcher(extra={JULY_URL: _synthetic_july_zip()}, gone={AUG_URL})
    out = _run(root, [GAP_SPEC], fetch, clock)
    (series,) = out.report.series
    assert series.coverage == "partial"
    assert series.missing_upstream == ("BTCUSDT-1d-2026-08.zip",)
    json_path, _ = report.report_paths(root, out.report)
    return json_path, series.batch_id


def _backfill(root, report_path, clock, fetch=None, **kw):
    return daily.run_backfill_from_report(
        root,
        report_path,
        fetch or ScriptedFetcher(extra={JULY_URL: _synthetic_july_zip()}),
        run_id=new_run_id(),
        sleep=clock.sleep,
        monotonic=clock.monotonic,
        now=NOW + dt.timedelta(days=1),
        **kw,
    )


def test_the_backfill_plan_targets_exactly_the_missing_archive(gappy):
    report_path, original = gappy
    plan = backfill.plan_backfill(report_path)
    (task,) = plan.tasks
    assert task.filename == "BTCUSDT-1d-2026-08.zip"
    assert (task.spec.start, task.spec.end) == (dt.date(2026, 8, 1), dt.date(2026, 8, 31))
    assert task.rerun_of == original
    assert plan.skipped == ()


def test_backfill_writes_a_new_rerun_batch_and_never_touches_the_original(root, clock, gappy):
    """变异点 (c)：把补采写成覆盖（或 `kind='ingest'` 不带 `rerun_of`），本用例变红。"""
    report_path, original = gappy
    before = snapshot(root)
    out = _backfill(root, report_path, clock)
    assert out.exit_code == 0
    after = snapshot(root)
    assert {k: after[k] for k in before} == before, "已发布文件被改动（ADR-0002）"
    rows = {r["batch_id"]: r for r in _batch_rows(root) if not r["scope"].startswith("audit__")}
    (new_id,) = set(rows) - {original}
    assert rows[new_id]["kind"] == "rerun"
    assert rows[new_id]["rerun_of"] == original
    assert rows[original]["kind"] == "ingest"


def test_after_backfill_the_re_audit_is_complete(root, clock, gappy):
    report_path, _ = gappy
    out = _backfill(root, report_path, clock)
    assert out.report.coverage == "complete"
    (series,) = out.report.series
    assert series.missing_upstream == () and series.rows == 31
    new_report = report.load_report(report.report_paths(root, out.report)[0])
    assert new_report["mode"] == "backfill"
    assert new_report["coverage"] == "complete"


def test_backfill_twice_from_the_same_report_is_still_insert_only(root, clock, gappy):
    report_path, original = gappy
    _backfill(root, report_path, clock)
    snap = snapshot(root)
    _backfill(root, report_path, clock)
    after = snapshot(root)
    assert {k: after[k] for k in snap} == snap
    reruns = [r for r in _batch_rows(root) if r["kind"] == "rerun"]
    assert len(reruns) == 2 and {r["rerun_of"] for r in reruns} == {original}


def test_whitelisted_upstream_missing_archives_are_not_retried(root, clock, gappy, tmp_path):
    report_path, _ = gappy
    wl_path = tmp_path / "wl.yaml"
    wl_path.write_text(
        "version: 1\nentries:\n"
        "  - source: binance_vision\n"
        "    filename: BTCUSDT-1d-2026-08.zip\n"
        "    reason: 测试用——人工核对 404\n"
        "    verified_on: 2026-09-23\n",
        encoding="utf-8",
    )
    fetch = ScriptedFetcher()
    before = snapshot(root)
    out = _backfill(root, report_path, clock, fetch=fetch, whitelist=load_upstream_missing(wl_path))
    assert fetch.urls == []
    assert any("上游确实缺失" in ln for ln in out.increments)
    # 没有任何 batch 写入；只多了本次的报告与运行记录。
    new = set(snapshot(root)) - set(before)
    assert all(p.startswith(("data/reports/", "data/runs/")) for p in new)


def test_backfill_refuses_a_report_from_another_source(root, clock, gappy, tmp_path):
    report_path, _ = gappy
    data = json.loads(report_path.read_text(encoding="utf-8"))
    data["series"][0]["source"] = "tushare_pro"
    other = tmp_path / "other.json"
    other.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(backfill.IngestError, match="跨源"):
        backfill.plan_backfill(other)


def test_backfill_refuses_an_entry_without_a_batch_id(gappy, tmp_path):
    report_path, _ = gappy
    data = json.loads(report_path.read_text(encoding="utf-8"))
    data["series"][0]["batch_id"] = None
    other = tmp_path / "nobatch.json"
    other.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(backfill.IngestError, match="rerun_of"):
        backfill.plan_backfill(other)


# ---- CLI 接线（不出网：网络出口被替换成录制回放） ----


@pytest.fixture
def offline_cli(monkeypatch):
    fetch = FixtureFetcher()
    monkeypatch.setattr(cli, "_http_opener", lambda: None)
    monkeypatch.setattr(cli, "_fetcher", lambda transport: fetch)
    return fetch


def test_cli_daily_since_last_runs_offline_and_exits_zero(root, offline_cli, capsys, tmp_path):
    universe = tmp_path / "universe.yaml"
    universe.write_text(
        "version: 1\nspot:\n  freqs: ['1d']\n  symbols: [BTCUSDT]\n", encoding="utf-8"
    )
    argv = [
        "--root", str(root), "--universe", str(universe),
        "daily", "--start", "2026-08-01", "--end", "2026-08-31", "--since-last",
    ]  # fmt: skip
    assert cli.main(argv) == 0
    first = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert (first["mode"], first["ok"], first["rows"]) == ("incremental", 1, 31)
    assert first["coverage"] == "complete"

    assert cli.main(argv) == 0
    second = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert (second["skipped_empty_increment"], second["rows"]) == (1, 0)


def test_cli_daily_exits_non_zero_when_a_series_fails(root, offline_cli, capsys, tmp_path):
    """清单里有录制外的 1h：该序列上游全缺 → 失败 → 退出码 1（timer 记 failed）。"""
    universe = tmp_path / "universe.yaml"
    universe.write_text(
        "version: 1\nspot:\n  freqs: ['1h', '1d']\n  symbols: [BTCUSDT]\n", encoding="utf-8"
    )
    argv = [
        "--root", str(root), "--universe", str(universe),
        "daily", "--start", "2026-08-01", "--end", "2026-08-31",
    ]  # fmt: skip
    assert cli.main(argv) == 1
    captured = capsys.readouterr()
    summary = json.loads(captured.out.strip().splitlines()[-1])
    assert (summary["outcome"], summary["ok"], summary["failed"]) == ("partial", 1, 1)
    assert "FAILED" in captured.err


def test_cli_backfill_dry_run_prints_the_plan_and_writes_nothing(root, clock, gappy, capsys):
    report_path, _ = gappy
    before = snapshot(root)
    code = cli.main(
        ["--root", str(root), "backfill", "--from-report", str(report_path), "--dry-run"]
    )
    assert code == 0
    assert "BTCUSDT" in capsys.readouterr().out
    assert snapshot(root) == before


def test_cli_retry_flags_reach_the_policy():
    args = cli.build_parser().parse_args(
        [
            "daily",
            "--start",
            "2026-08-01",
            "--end",
            "2026-08-01",
            "--retry-attempts",
            "7",
            "--retry-max-seconds",
            "12",
        ]
    )
    policy = cli._retry_policy(args)
    assert (policy.max_attempts, policy.max_total_seconds) == (7, 12.0)
