"""按上游发布节奏选归档（QNT-45 R2）——`list_archives` 只列截至请求日**已发布**的归档。

调研 §4.5：日档次日发布；月档次月第一个周一发布。旧实现不看日期，永远列月档：9 月下旬
跑 9 月，请求的是一个还不存在的 `2026-09.zip`，404 被记成「上游整档缺失」，覆盖天天是
`partial`——而那几天的数据其实早就以日档的形式在上游了。

funding 没有日档（2026-09-23 对一个 daily fundingRate URL 做了一次 allowlist 内 GET，404），
所以月档发布前的那段是 `pending_upstream`：不是缺失、不是失败、不进覆盖率分母——但整体
覆盖是 `pending` 而不是 `complete`（R7）。它的起点记进运行记录 `pending_since`，月档发布后
的 `--since-last` 从那里取回（没有水位线的首跑也一样，见 `test_first_run_pending.py`）。

全部离线：日档用测试内合成的 zip（`fixture_source.synthetic_daily_kline`）。
"""

from __future__ import annotations

import datetime as dt

import pytest
from fixture_source import (
    FUNDING_SPEC,
    ScriptedFetcher,
    spot_1d,
    synthetic_daily_kline,
)
from quantime_core.ids import new_run_id
from quantime_core.paths import AssetClass, DataType, Freq
from quantime_data import daily, report
from quantime_data.sources import binance_public as bp
from quantime_data.spec import IngestSpec, first_monday

ADAPTER = bp.ADAPTER
D = dt.date


def _days(archives) -> list[dt.date]:
    out: list[dt.date] = []
    for a in archives:
        out.extend(bp.days_between(a.covers_start, a.covers_end))
    return out


def _names(archives) -> list[str]:
    return [a.filename for a in archives]


def perp(datatype: DataType, freq: Freq, start: dt.date, end: dt.date) -> IngestSpec:
    return IngestSpec(
        datatype=datatype,
        asset_class=AssetClass.PERP,
        symbol="BTCUSDT",
        freq=freq,
        start=start,
        end=end,
    )


# ---- 日历 ----


def test_first_monday_matches_the_calendar():
    assert first_monday(2026, 9) == D(2026, 9, 7)
    assert first_monday(2026, 6) == D(2026, 6, 1)  # 1 号本身就是周一
    assert first_monday(2026, 11) == D(2026, 11, 2)


def test_a_monthly_archive_counts_as_published_from_the_first_monday_of_the_next_month():
    assert not bp.monthly_published("2026-08", D(2026, 9, 6))
    assert bp.monthly_published("2026-08", D(2026, 9, 7))
    assert not bp.daily_published(D(2026, 9, 21), D(2026, 9, 21))  # 当天的日档还没有
    assert bp.daily_published(D(2026, 9, 21), D(2026, 9, 22))


# ---- K 线：月档已发布用月档，否则用日档 ----


def test_on_2026_09_22_september_is_listed_as_daily_archives_never_as_the_monthly_zip():
    """R2 验收：请求日 2026-09-22 → 列表里没有 `2026-09.zip`。"""
    spec = spot_1d(D(2026, 9, 1), D(2026, 9, 21)).requested_on(D(2026, 9, 22))
    archives = ADAPTER.list_archives(spec)
    assert "BTCUSDT-1d-2026-09.zip" not in _names(archives)
    assert _names(archives) == [f"BTCUSDT-1d-2026-09-{d:02d}.zip" for d in range(1, 22)]
    assert all("/daily/klines/" in a.url for a in archives)
    assert ADAPTER.pending_windows(spec) == ()


def test_on_2026_08_31_august_uses_daily_archives():
    """R2 验收：请求日 2026-08-31 → 8 月用日档（8-31 当天的日档还没发布 → pending）。"""
    spec = spot_1d(D(2026, 8, 1), D(2026, 8, 31)).requested_on(D(2026, 8, 31))
    archives = ADAPTER.list_archives(spec)
    assert "BTCUSDT-1d-2026-08.zip" not in _names(archives)
    assert _days(archives) == list(bp.days_between(D(2026, 8, 1), D(2026, 8, 30)))
    assert ADAPTER.pending_windows(spec) == ((D(2026, 8, 31), D(2026, 8, 31)),)


def test_once_the_monthly_archive_is_published_it_replaces_the_daily_ones():
    spec = spot_1d(D(2026, 8, 1), D(2026, 8, 31))
    assert _names(ADAPTER.list_archives(spec.requested_on(D(2026, 9, 6))))[0].endswith("-08-01.zip")
    assert _names(ADAPTER.list_archives(spec.requested_on(D(2026, 9, 7)))) == [
        "BTCUSDT-1d-2026-08.zip"
    ]


@pytest.mark.parametrize(
    "as_of",
    [D(2026, 8, 31), D(2026, 9, 1), D(2026, 9, 6), D(2026, 9, 7), D(2026, 9, 22), D(2026, 10, 5)],
)
@pytest.mark.parametrize("freq", [Freq.D1, Freq.H4])
def test_no_day_is_ever_covered_by_two_archives_and_every_day_is_listed_or_pending(as_of, freq):
    spec = IngestSpec(
        datatype=DataType.KLINE,
        asset_class=AssetClass.PERP,
        symbol="BTCUSDT",
        freq=freq,
        start=D(2026, 7, 15),
        end=D(2026, 9, 30),
        as_of=as_of,
    )
    archives = ADAPTER.list_archives(spec)
    covered = _days(archives)
    assert len(covered) == len(set(covered)), "同一天被两个归档覆盖——行会重复入湖"
    pending = [d for a, b in ADAPTER.pending_windows(spec) for d in bp.days_between(a, b)]
    assert not set(pending) & set(covered)
    in_window = {d for d in covered if spec.start <= d <= spec.end}
    assert in_window | set(pending) == set(bp.days_between(spec.start, spec.end))
    assert all(d < as_of for d in in_window), "列出了尚未发布的日子"


def test_the_listing_is_pure_and_as_of_does_not_change_spec_identity():
    spec = spot_1d(D(2026, 9, 1), D(2026, 9, 21))
    a, b = spec.requested_on(D(2026, 9, 22)), spec.requested_on(D(2026, 10, 5))
    assert a == b  # 请求日不参与相等：它是「什么时候问的」，不是「问的是哪条序列」
    assert ADAPTER.list_archives(a) == ADAPTER.list_archives(a)
    assert ADAPTER.list_archives(a) != ADAPTER.list_archives(b)


# ---- funding：无日档 → pending_upstream ----


def test_unpublished_funding_months_are_pending_not_listed():
    spec = perp(DataType.FUNDING, Freq.EVENT, D(2026, 9, 1), D(2026, 9, 21)).requested_on(
        D(2026, 9, 22)
    )
    assert ADAPTER.list_archives(spec) == ()
    assert ADAPTER.pending_windows(spec) == ((D(2026, 9, 1), D(2026, 9, 21)),)


def test_open_interest_lists_only_published_days():
    spec = perp(DataType.OPEN_INTEREST, Freq.M5, D(2026, 9, 20), D(2026, 9, 22)).requested_on(
        D(2026, 9, 22)
    )
    assert _days(ADAPTER.list_archives(spec)) == [D(2026, 9, 20), D(2026, 9, 21)]
    assert ADAPTER.pending_windows(spec) == ((D(2026, 9, 22), D(2026, 9, 22)),)


# ---- 端到端：pending 不是失败、不拉低覆盖率，之后由 --since-last 取回 ----


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def sleep(self, s: float) -> None:
        self.now += s

    def monotonic(self) -> float:
        return self.now


def _daily_fetcher(days) -> ScriptedFetcher:
    return ScriptedFetcher(extra=dict(synthetic_daily_kline("spot", "1d", d) for d in days))


def _run(root, specs, fetch, now, **kw):
    clock = Clock()
    return daily.run_daily(
        root,
        specs,
        fetch,
        run_id=new_run_id(),
        sleep=clock.sleep,
        monotonic=clock.monotonic,
        now=now,
        **kw,
    )


def test_a_run_before_the_monthly_release_fetches_daily_archives_and_parks_funding(root):
    """9-01 跑 8 月：K 线取 8-25..8-31 日档 → complete；funding 月档未发布 → pending。"""
    kline = spot_1d(D(2026, 8, 25), D(2026, 8, 31))
    fetch = _daily_fetcher(bp.days_between(D(2026, 8, 25), D(2026, 8, 31)))
    out = _run(root, [kline, FUNDING_SPEC], fetch, dt.datetime(2026, 9, 1, 3, tzinfo=dt.UTC))

    assert out.exit_code == 0
    assert not any("/monthly/" in u for u in fetch.urls), "请求了尚未发布的月档"
    k, f = out.report.series
    assert (k.status, k.coverage, k.rows) == ("ok", "complete", 7)
    assert (f.status, f.coverage) == ("pending", "pending")
    assert f.pending_upstream == ((D(2026, 8, 1), D(2026, 8, 31)),)
    assert out.report.coverage == "pending"  # pending 不进分母，但有未消化 pending 就不是 complete
    data = report.load_report(report.report_paths(root, out.report)[0])
    assert data["totals"]["pending_upstream_days"] == 31
    assert data["totals"]["failures"] == 0 and data["totals"]["missing_upstream"] == 0
    assert out.log.series[1].action == "pending_upstream"


def funding_requested_on(day: dt.date) -> IngestSpec:
    """CLI 的 `daily --since-last --end yesterday`（不带 `--start`）在 `day` 当天发出的请求。"""
    yesterday = day - dt.timedelta(days=1)
    return perp(DataType.FUNDING, Freq.EVENT, yesterday, yesterday)


def test_pending_days_are_picked_up_by_the_next_since_last_after_the_release(root):
    """请求跟着请求日走（R7 修正）：9-01 的请求只有 8-31，9-08 的请求只有 9-07。

    9-01 那次整段 pending，起点 8-31 记进运行记录；9-08 的 `--since-last` 从 8-31 起，
    8 月月档已发布 → 落成 batch，水位线到 8-31；9 月的日子仍 pending。
    """
    early = dt.datetime(2026, 9, 1, 3, tzinfo=dt.UTC)
    spec = funding_requested_on(early.date())
    first = _run(root, [spec], ScriptedFetcher(), early, since_last=True)
    assert first.log.pending_since[0].since == D(2026, 8, 31)
    assert first.report.coverage == "pending"
    later = dt.datetime(2026, 9, 8, 3, tzinfo=dt.UTC)  # 9-07 是 9 月第一个周一
    fetch = ScriptedFetcher()
    out = _run(root, [funding_requested_on(later.date())], fetch, later, since_last=True)
    assert any(u.endswith("BTCUSDT-fundingRate-2026-08.zip") for u in fetch.urls)
    (series,) = out.report.series
    assert series.status == "ok" and series.rows > 0 and series.batch_id
    assert series.pending_upstream == ((D(2026, 9, 1), D(2026, 9, 7)),)
    assert out.report.coverage == "pending"  # 9 月那段还没消化
