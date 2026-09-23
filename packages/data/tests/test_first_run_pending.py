"""首跑即遇 pending 的起点可重放（QNT-45 R7）。

真 adapter、`daily --since-last`、CLI 不带 `--start`。

verify-a 的反例：空湖、9-01 首跑，funding 8 月月档要到 9-07 才发布 → 整段 pending，没有 batch，
也就没有水位线。旧实现什么都没记，9-08 那次的请求只剩「昨天」9-07，8 月那段永远不会再被
请求。现在整段 pending 的序列把请求起点写进本次运行记录的 `pending_since`（只增）；之后的
`--since-last` 从 `min(水位线次日, 未消化的 pending 起点)` 开始；水位线越过它才算消化。

**不**用空 batch 或人工「预热」伪造水位线——湖里只有真实取回的数据。

时钟：`daily._now` 被钉到每天 03:00 UTC；`--end` 与 unit 一样取 UTC 昨日；全程离线
（funding 月档用录制 fixture，K 线日档测试内合成）。
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import pytest
from fixture_source import ScriptedFetcher, synthetic_daily_kline
from quantime_data import batches, cli, daily, runlog
from quantime_data.incremental import committed_coverage

D = dt.date
FUNDING_KEY = ("binance_vision", "perp", "funding", "event", "BTCUSDT")


def _universe(tmp_path):
    path = tmp_path / "universe.yaml"
    path.write_text(
        "version: 1\n"
        "spot:\n  freqs: ['1d']\n  symbols: [BTCUSDT]\n"
        "perp:\n  freqs: ['1d']\n  symbols: [BTCUSDT]\n",
        encoding="utf-8",
    )
    return path


@pytest.fixture
def lake(tmp_path, monkeypatch):
    """空湖 + 离线出口：8-31..9-30 的现货 / 永续日线日档都「在上游」，funding 走录制。"""
    days = [D(2026, 8, 31) + dt.timedelta(days=i) for i in range(31)]
    extra = dict(synthetic_daily_kline(ac, "1d", d) for ac in ("spot", "perp") for d in days)
    fetch = ScriptedFetcher(extra=extra)
    monkeypatch.setattr(cli, "_http_opener", lambda: None)
    monkeypatch.setattr(cli, "_fetcher", lambda transport: fetch)
    root = tmp_path / "lake"
    (root / "data").mkdir(parents=True)
    return root, _universe(tmp_path), fetch, monkeypatch


def _run_on(lake, day: dt.date, capsys) -> dict:
    """在 `day` 当天 03:00 UTC 跑一次 unit 的命令：`daily --since-last --end <昨天>`。"""
    root, universe, fetch, monkeypatch = lake
    monkeypatch.setattr(
        daily, "_now", lambda now=None: dt.datetime.combine(day, dt.time(3), tzinfo=dt.UTC)
    )
    fetch.urls.clear()
    argv = [
        "--root", str(root / "data"), "--universe", str(universe),
        "daily", "--since-last", "--datatype", "kline", "--datatype", "funding",
        "--end", (day - dt.timedelta(days=1)).isoformat(),
    ]  # fmt: skip
    code = cli.main(argv)
    summary = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    summary["exit_code"] = code
    summary["report"] = json.loads(Path(summary["report_json"]).read_text())
    return summary


def _batches(root, datatype):
    table = batches.read_ingestion_batch(root)
    rows = [
        dict(zip(table.column_names, row, strict=True))
        for row in zip(*table.to_pydict().values(), strict=True)
    ]
    return [r for r in rows if r["datatype"] == datatype and not r["scope"].startswith("audit__")]


def _series(summary, datatype):
    return [s for s in summary["report"]["series"] if s["datatype"] == datatype]


def daily_marks(root):
    return {k: v.end for k, v in committed_coverage(root).items()}


def _funding_mark(root):
    return daily_marks(root).get(FUNDING_KEY)


def test_a_first_run_pending_start_is_persisted_and_picked_up_after_the_release(lake, capsys):
    """R7 验收：9-01 空湖 → funding pending、0 batch；9-08 → 8 月月档落成 batch、水位线≥8-31。"""
    root = lake[0]

    first = _run_on(lake, D(2026, 9, 1), capsys)
    (funding,) = _series(first, "funding")
    assert funding["status"] == "pending"
    assert _batches(root, "funding") == []
    assert first["report"]["coverage"] == "pending"  # 有未消化 pending，整体不许是 complete
    assert first["report"]["sources"] == [{"source": "binance_vision", "coverage": "pending"}]
    assert runlog.read_pending_since(root)[FUNDING_KEY] == (D(2026, 8, 31),)
    # 同一次运行里 K 线照常：8-31 的现货 / 永续日档都落了 batch。
    assert [s["status"] for s in _series(first, "kline")] == ["ok", "ok"]
    assert first["exit_code"] == 0

    # 9-02..9-06：月档还没发布。9-07（首个周一，月档发布日）那天机器关着——验收口径是
    # 「9-08 请求时取回」；逐日不断档时 9-07 当天就取回，见下一条测试。
    for day in range(2, 7):
        mid = _run_on(lake, D(2026, 9, day), capsys)
        assert _series(mid, "funding")[0]["status"] == "pending"
        assert _batches(root, "funding") == []
        assert mid["report"]["coverage"] == "pending"
        assert not any("fundingRate" in u for u in lake[2].urls)

    last = _run_on(lake, D(2026, 9, 8), capsys)
    assert any(u.endswith("BTCUSDT-fundingRate-2026-08.zip") for u in lake[2].urls)
    (funding,) = _series(last, "funding")
    assert funding["status"] == "ok" and funding["rows"] > 0
    (batch,) = _batches(root, "funding")
    assert batch["batch_id"] == funding["batch_id"]
    assert _funding_mark(root).date() >= D(2026, 8, 31)
    # 9 月那段仍待月档：整体 pending，不是 complete。
    assert funding["pending_upstream"] == [{"start": "2026-09-01", "end": "2026-09-07"}]
    assert last["report"]["coverage"] == "pending"
    # K 线同一次运行正常：水位线跟到 9-07，一天不缺。
    kline = _series(last, "kline")
    assert [s["status"] for s in kline] == ["ok", "ok"]
    assert all(m.date() == D(2026, 9, 7) for k, m in daily_marks(root).items() if k[2] == "kline")
    assert last["exit_code"] == 0


def test_day_by_day_the_archive_lands_on_its_release_day(lake, capsys):
    """逐日推进不断档：9-01..9-06 pending，9-07（8 月月档发布日）当天就落 batch。"""
    root = lake[0]
    for day in range(1, 7):
        assert _series(_run_on(lake, D(2026, 9, day), capsys), "funding")[0]["status"] == "pending"
    assert _batches(root, "funding") == []
    on_release = _run_on(lake, D(2026, 9, 7), capsys)
    (funding,) = _series(on_release, "funding")
    assert funding["status"] == "ok" and funding["range_start"].startswith("2026-08-31")
    assert len(_batches(root, "funding")) == 1
    assert _funding_mark(root).date() >= D(2026, 8, 31)


def test_a_digested_pending_start_is_not_requested_again(lake, capsys):
    """消化判据：水位线越过 pending 起点后，下一次从水位线次日起，不回头重取 8 月。"""
    root = lake[0]
    for day in (1, 8):
        _run_on(lake, D(2026, 9, day), capsys)
    before = len(_batches(root, "funding"))
    again = _run_on(lake, D(2026, 9, 9), capsys)
    assert not any("fundingRate-2026-08" in u for u in lake[2].urls)
    assert len(_batches(root, "funding")) == before  # 9 月月档未发布 → 不开新 batch
    (funding,) = _series(again, "funding")
    assert funding["status"] == "pending"
    assert funding["pending_upstream"] == [{"start": "2026-09-01", "end": "2026-09-08"}]
    # 新的 pending 起点是水位线次日 9-01；8-31 那条已被水位线消化。
    assert D(2026, 9, 1) in runlog.read_pending_since(root)[FUNDING_KEY]
