"""Massive 阶段 2 摄取：Flat Files 逐日 batch、REST 参考 meta batch、报告、CLI 凭据出口。

全部离线。Flat Files 用内存假客户端（同样装只读闸——闸的真 boto3 覆盖在 test_flatfiles.py）；
REST 用 `KeyedTransport` + 假 opener，响应取自 `fixtures/massive_recorded/`（真实录制、脱敏）
与按文档手写的最小页。
"""

from __future__ import annotations

import datetime as dt
import gzip
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pyarrow as pa
import pyarrow.parquet
import pytest
from quantime_core.paths import MetaTable, meta_batch_dir
from quantime_data import batches, cli
from quantime_data import flatfiles as ff
from quantime_data import massive_ingest as mi
from quantime_data.keyed_transport import (
    CredentialUnavailableError,
    KeyedTransport,
    assert_bearer_headers,
    assert_keyed_readonly_path,
    check_keyed_outgoing,
)
from quantime_data.sources import massive
from quantime_data.transport import Response, TransportBoundaryError

RECORDED = Path(__file__).resolve().parents[3] / "fixtures" / "massive_recorded"
NY = ZoneInfo("America/New_York")
RUN = "01M36EW8D0YQVDYABEHC09K84H"
NOW = dt.datetime(2026, 9, 23, 12, 0, tzinfo=dt.UTC)
FAKE_KEY = "test-key-not-a-real-credential"


# =========================================================================== Flat Files


def _day_csv(day: dt.date, tickers=("AAA", "BBB", "CCC"), close=10.0) -> bytes:
    ws = int(dt.datetime.combine(day, dt.time.min, tzinfo=NY).timestamp()) * 1_000_000_000
    lines = [",".join(ff.DAY_AGGS_HEADER)]
    for t in tickers:
        lines.append(f"{t},1000,9.5,{close},10.5,9.0,{ws},42")
    return gzip.compress(("\n".join(lines) + "\n").encode(), mtime=0)


def _key(day: dt.date) -> str:
    return f"{ff.DAY_AGGS_PREFIX}{day:%Y/%m}/{day.isoformat()}.csv.gz"


class FakeS3:
    """内存 S3：`objects[key] = (etag, payload)`。每次调用都先过 `check_call`（同真钩子）。"""

    def __init__(self, objects: dict[str, tuple[str, bytes]]) -> None:
        self.objects = objects
        self.calls: list[tuple[str, dict]] = []
        self.fail: dict[str, Exception] = {}
        self.meta = SimpleNamespace(
            region_name=ff.FLATFILES_REGION,
            endpoint_url=ff.FLATFILES_ENDPOINT,
            events=SimpleNamespace(register_first=lambda *_a, **_k: None),
        )

    def list_objects_v2(self, **kw):
        ff.check_call("ListObjectsV2", kw)
        self.calls.append(("list", kw))
        contents = [
            {"Key": k, "ETag": f'"{e}"', "Size": len(p), "LastModified": NOW}
            for k, (e, p) in sorted(self.objects.items())
            if k.startswith(kw["Prefix"])
        ]
        return {"Contents": contents, "IsTruncated": False}

    def get_object(self, **kw):
        ff.check_call("GetObject", kw)
        self.calls.append(("get", kw))
        if kw["Key"] in self.fail:
            raise self.fail[kw["Key"]]
        etag, payload = self.objects[kw["Key"]]
        assert kw["IfMatch"] == f'"{etag}"'
        return {"Body": SimpleNamespace(read=lambda: payload), "ETag": f'"{etag}"'}


def _bucket(objects) -> tuple[ff.DayAggsBucket, FakeS3]:
    s3 = FakeS3(objects)
    return ff.DayAggsBucket(s3, sleep=lambda _s: None, monotonic=lambda: 0.0), s3


DAYS = [dt.date(2026, 8, 3), dt.date(2026, 8, 4), dt.date(2026, 8, 5)]


def _objects(days=DAYS, etag="e1"):
    return {_key(d): (f"{etag}-{d.day}", _day_csv(d)) for d in days}


def test_each_day_becomes_one_batch_with_raw_copy_and_object_meta(tmp_path):
    bucket, _ = _bucket(_objects())
    run = mi.ingest_flatfiles(tmp_path, bucket, start=DAYS[0], end=DAYS[-1], run_id=RUN, now=NOW)
    assert [d.status for d in run.days] == ["ok"] * 3
    assert run.gaps == []
    ib = batches.read_ingestion_batch(tmp_path)
    assert ib.num_rows == 3
    assert set(ib.column("source").to_pylist()) == {"massive_flatfiles"}
    first = run.days[0]
    manifest = json.loads((tmp_path / batches.batch_manifest_path(first.batch_id)).read_text())
    raw_names = sorted(Path(r["path"]).name for r in manifest["raw"])
    assert raw_names == ["2026-08-03.csv.gz", mi.OBJECT_META_NAME]
    meta_entry = next(r for r in manifest["raw"] if r["path"].endswith(mi.OBJECT_META_NAME))
    obj = json.loads((tmp_path / meta_entry["path"]).read_text())
    payload = _day_csv(DAYS[0])
    assert obj == {
        "bucket": "flatfiles",
        "key": _key(DAYS[0]),
        "etag": "e1-3",
        "size": len(payload),
        "last_modified": NOW.isoformat(),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }
    assert first.raw_sha256 == obj["sha256"]
    assert "raw/massive_flatfiles/" + first.batch_id in meta_entry["path"]


def test_rerun_with_same_etags_is_a_no_op(tmp_path):
    bucket, s3 = _bucket(_objects())
    mi.ingest_flatfiles(tmp_path, bucket, start=DAYS[0], end=DAYS[-1], run_id=RUN, now=NOW)
    gets_before = sum(1 for c in s3.calls if c[0] == "get")
    again = mi.ingest_flatfiles(tmp_path, bucket, start=DAYS[0], end=DAYS[-1], run_id=RUN, now=NOW)
    assert [d.status for d in again.days] == ["skipped"] * 3
    assert sum(1 for c in s3.calls if c[0] == "get") == gets_before, "幂等跳过不得下载"
    assert batches.read_ingestion_batch(tmp_path).num_rows == 3


def test_a_changed_etag_is_ingested_as_a_rerun_batch_never_an_update(tmp_path):
    bucket, s3 = _bucket(_objects())
    first = mi.ingest_flatfiles(tmp_path, bucket, start=DAYS[0], end=DAYS[-1], run_id=RUN, now=NOW)
    s3.objects[_key(DAYS[1])] = ("e2-4", _day_csv(DAYS[1], close=11.0))
    second = mi.ingest_flatfiles(tmp_path, bucket, start=DAYS[0], end=DAYS[-1], run_id=RUN, now=NOW)
    statuses = {d.date: (d.status, d.kind) for d in second.days}
    assert statuses[DAYS[1]] == ("ok", "rerun")
    assert statuses[DAYS[0]][0] == statuses[DAYS[2]][0] == "skipped"
    rerun = next(d for d in second.days if d.date == DAYS[1])
    assert rerun.rerun_of == first.days[1].batch_id
    # 旧 batch 原样还在（只 insert）
    assert batches.read_ingestion_batch(tmp_path).num_rows == 4
    # 第三次：新 ETag 已提交，再跑应跳过
    third = mi.ingest_flatfiles(tmp_path, bucket, start=DAYS[0], end=DAYS[-1], run_id=RUN, now=NOW)
    assert all(d.status == "skipped" for d in third.days)


def test_one_failing_day_does_not_stop_the_others_and_becomes_a_gap(tmp_path):
    bucket, s3 = _bucket(_objects())
    s3.fail[_key(DAYS[1])] = ff.SourceFormatError("boom")
    run = mi.ingest_flatfiles(tmp_path, bucket, start=DAYS[0], end=DAYS[-1], run_id=RUN, now=NOW)
    assert [d.status for d in run.days] == ["ok", "failed", "ok"]
    assert run.days[1].error_class == "SourceFormatError"
    assert run.gaps == [DAYS[1]]
    report = mi.build_report(run_id=RUN, report_date=NOW.date(), generated_at=NOW, flatfiles=run)
    assert report["coverage"] == "failed"
    assert report["massive"]["gaps"] == ["2026-08-04"]
    assert report["totals"]["failed_series"] == 1


def test_transient_errors_are_retried_and_counted(tmp_path):
    class Flaky(Exception):
        response = {"ResponseMetadata": {"HTTPStatusCode": 503}}

    bucket, s3 = _bucket(_objects(days=DAYS[:1]))
    original = s3.get_object
    state = {"n": 0}

    def flaky_get(**kw):
        state["n"] += 1
        if state["n"] == 1:
            raise Flaky()
        return original(**kw)

    s3.get_object = flaky_get
    run = mi.ingest_flatfiles(tmp_path, bucket, start=DAYS[0], end=DAYS[0], run_id=RUN, now=NOW)
    assert run.days[0].status == "ok"
    assert run.days[0].retries == 1


def test_weekdays_missing_from_the_listing_are_reported_not_counted_as_gaps(tmp_path):
    bucket, _ = _bucket(_objects(days=[DAYS[0], DAYS[2]]))
    run = mi.ingest_flatfiles(tmp_path, bucket, start=DAYS[0], end=DAYS[-1], run_id=RUN, now=NOW)
    assert run.gaps == []
    assert run.weekdays_absent_from_listing() == [DAYS[1]]


def test_month_prefixes_cross_year_boundaries():
    assert mi.month_prefixes(dt.date(2025, 11, 30), dt.date(2026, 1, 2)) == [
        f"{ff.DAY_AGGS_PREFIX}2025/11/",
        f"{ff.DAY_AGGS_PREFIX}2025/12/",
        f"{ff.DAY_AGGS_PREFIX}2026/01/",
    ]


def test_listing_filters_to_the_requested_range(tmp_path):
    bucket, _ = _bucket(_objects())
    listed = mi.list_range(bucket, DAYS[1], DAYS[1])
    assert [i.date for i in listed] == [DAYS[1]]


def test_report_is_published_under_the_massive_report_dir(tmp_path):
    bucket, _ = _bucket(_objects())
    run = mi.ingest_flatfiles(tmp_path, bucket, start=DAYS[0], end=DAYS[-1], run_id=RUN, now=NOW)
    report = mi.build_report(run_id=RUN, report_date=NOW.date(), generated_at=NOW, flatfiles=run)
    assert report["coverage"] == "complete"
    assert report["schema_version"] == 2
    json_path, md_path = mi.publish_report(tmp_path, report)
    assert json_path == tmp_path / "data/reports/2026-09-23/massive" / f"{RUN}.json"
    assert md_path.suffix == ".md" and md_path.read_text()
    assert json.loads(json_path.read_text())["massive"]["committed_batches"] == 3


def test_an_empty_run_is_partial_not_green():
    report = mi.build_report(run_id=RUN, report_date=NOW.date(), generated_at=NOW, flatfiles=None)
    assert report["coverage"] == "partial"


# =========================================================================== REST 参考


class Opener:
    """按 URL 路由的假 opener；记录每次请求的 (url, headers)。"""

    def __init__(self, routes: dict[str, Response]) -> None:
        self.routes = routes
        self.calls: list[tuple[str, dict[str, str]]] = []

    def __call__(self, url: str, headers: dict[str, str]) -> Response:
        self.calls.append((url, dict(headers)))
        return self.routes.get(url, Response(404, b"{}"))


def _transport(routes) -> tuple[KeyedTransport, Opener]:
    opener = Opener(routes)
    clock = {"t": 0.0}

    def mono():
        clock["t"] += 1000.0
        return clock["t"]

    t = KeyedTransport(
        opener, api_key=FAKE_KEY, sleep=lambda _s: None, jitter=lambda: 0.0, monotonic=mono
    )
    return t, opener


def _page(results, next_url=None) -> bytes:
    doc = {"status": "OK", "results": results}
    if next_url:
        doc["next_url"] = next_url
    return json.dumps(doc).encode()


RECORDED_TICKERS = (RECORDED / "tickers-inactive-limit3.json").read_bytes()
RECORDED_EVENTS = (RECORDED / "events-META.json").read_bytes()


def test_recorded_inactive_tickers_normalize_with_explainable_ids():
    table = massive.normalize_tickers(RECORDED_TICKERS, active=False)
    rows = {r["symbol"]: r for r in table.to_pylist()}
    assert rows["AABA"]["instrument_id"] == "us:figi:BBG000KB2D74"
    assert rows["AABA"]["instrument_id_rule"] == "figi"
    assert rows["AABA"]["effective_to"] == dt.date(2019, 10, 7)
    assert rows["AAB.WS"]["instrument_id"] == "us:ticker:AAB.WS:delisted=2008-02-11"
    assert rows["AAB.WS"]["instrument_id_rule"] == "ticker_delisted"
    assert all(r["effective_from"] is None for r in rows.values())


def test_recorded_ticker_events_normalize_to_change_rows():
    table = massive.normalize_ticker_events(RECORDED_EVENTS, figi="BBG000MM2P62")
    assert [(r["event_date"], r["ticker"]) for r in table.to_pylist()] == [
        (dt.date(2012, 5, 18), "FB"),
        (dt.date(2022, 6, 9), "META"),
    ]
    assert set(table.column("instrument_id").to_pylist()) == {"us:figi:BBG000MM2P62"}


def test_ticker_events_reject_a_response_for_another_figi():
    with pytest.raises(massive.SourceFormatError, match="FIGI"):
        massive.normalize_ticker_events(RECORDED_EVENTS, figi="BBG000KB2D74")


def test_split_factor_is_from_over_to_and_upstream_cumulative_factor_is_kept_apart():
    page = _page(
        [
            {
                "id": "S1",
                "ticker": "NVDA",
                "execution_date": "2024-06-10",
                "split_from": 1,
                "split_to": 10,
                "adjustment_type": "forward_split",
                "historical_adjustment_factor": 0.025,
            }
        ]
    )
    row = massive.normalize_all_splits(page).to_pylist()[0]
    assert row["factor_value"] == pytest.approx(0.1)
    assert row["share_ratio"] == pytest.approx(10.0)
    assert row["upstream_historical_adjustment_factor"] == pytest.approx(0.025)
    assert row["adjust_kind"] == "split" and row["direction"] == "forward"
    assert row["instrument_id_rule"] == "ticker_unresolved"


def test_dividends_store_cash_amount_and_no_derived_factor():
    page = _page(
        [
            {
                "id": "D1",
                "ticker": "AAPL",
                "ex_dividend_date": "2026-08-11",
                "cash_amount": 0.26,
                "declaration_date": "2026-07-30",
                "distribution_type": "recurring",
            }
        ]
    )
    row = massive.normalize_all_dividends(page).to_pylist()[0]
    assert row["factor_value"] is None
    assert row["cash_amount"] == pytest.approx(0.26)
    assert row["disclosure_date"] == dt.date(2026, 7, 30)


def test_ticker_resolver_picks_the_listing_alive_on_the_event_date():
    meta = pa.table(
        {
            "symbol": ["ABC", "ABC"],
            "effective_to": pa.array([dt.date(2010, 1, 1), None], pa.date32()),
            "instrument_id": ["us:ticker:ABC:delisted=2010-01-01", "us:figi:BBG000000001"],
        }
    )
    resolve = massive.ticker_resolver(meta)
    assert resolve("ABC", dt.date(2009, 6, 1))[0] == "us:ticker:ABC:delisted=2010-01-01"
    assert resolve("ABC", dt.date(2020, 6, 1)) == ("us:figi:BBG000000001", "resolved_by_ticker")
    assert resolve("XYZ", dt.date(2020, 6, 1)) == ("us:ticker:XYZ", "ticker_unresolved")


def _ticker(t, figi=None, active=True, delisted=None):
    row = {"ticker": t, "active": active, "market": "stocks", "locale": "us", "name": t}
    if figi:
        row["composite_figi"] = figi
    if delisted:
        row["delisted_utc"] = delisted
    return row


def test_reference_ingest_follows_next_url_through_the_gate_and_commits_meta_batches(tmp_path):
    active_1 = massive.tickers_url(active=True)
    active_2 = f"{massive.REST_BASE}/v3/reference/tickers?cursor=abc"
    inactive = massive.tickers_url(active=False)
    routes = {
        active_1: Response(200, _page([_ticker("AAA", "BBG000MM2P62")], next_url=active_2)),
        active_2: Response(200, _page([_ticker("BBB")])),
        inactive: Response(200, RECORDED_TICKERS.replace(b'"next_url"', b'"_next"')),
    }
    fetch, opener = _transport(routes)
    batch, table = mi.ingest_tickers(tmp_path, fetch.get, run_id=RUN, now=NOW)
    assert batch.rows == 5 and batch.pages == 3
    assert batch.extra == {"active": 2, "inactive": 3, "with_figi": 2}
    assert [u for u, _ in opener.calls] == [active_1, active_2, inactive]
    for _, headers in opener.calls:
        assert headers == {"Authorization": f"Bearer {FAKE_KEY}"}
    for url, _ in opener.calls:
        assert "apikey" not in url.lower()
    written = tmp_path / meta_batch_dir(
        MetaTable.INSTRUMENT_META, batch.batch_id, source="massive_rest"
    )
    assert (written / "part-0000.parquet").is_file()
    ib = batches.read_ingestion_batch(tmp_path).to_pylist()
    assert ib[0]["source"] == "massive_rest" and ib[0]["datatype"] == "instrument_meta"

    events_url = massive.ticker_events_url("BBG000MM2P62")
    fetch2, _ = _transport(
        {events_url: Response(200, RECORDED_EVENTS.replace(b"BBG000MM2P62", b"BBG000MM2P62"))}
    )
    figis = mi.figis_for_events(table)
    assert figis == ["BBG000KB2D74", "BBG000MM2P62"]
    ev = mi.ingest_ticker_events(tmp_path, fetch2.get, figis, run_id=RUN, now=NOW)
    assert ev is not None and ev.rows == 2
    assert ev.extra == {"figis_queried": 2, "figis_not_found": 1}


def test_a_next_url_to_a_non_whitelisted_path_is_refused_before_sending(tmp_path):
    first = massive.tickers_url(active=True)
    evil = f"{massive.REST_BASE}/v2/orders?cursor=abc"
    fetch, opener = _transport({first: Response(200, _page([_ticker("AAA")], next_url=evil))})
    with pytest.raises(TransportBoundaryError):
        mi.ingest_tickers(tmp_path, fetch.get, run_id=RUN, now=NOW)
    assert [u for u, _ in opener.calls] == [first]
    assert batches.read_ingestion_batch(tmp_path).num_rows == 0


def test_corporate_actions_resolve_tickers_against_the_same_run_meta(tmp_path):
    meta = massive.normalize_tickers(RECORDED_TICKERS, active=False)
    splits_url = massive.all_splits_url(start=dt.date(2019, 1, 1), end=dt.date(2019, 12, 31))
    divs_url = massive.all_dividends_url(start=dt.date(2019, 1, 1), end=dt.date(2019, 12, 31))
    split = {
        "id": "S1",
        "ticker": "AABA",
        "execution_date": "2019-06-03",
        "split_from": 2,
        "split_to": 1,
    }
    fetch, _ = _transport(
        {splits_url: Response(200, _page([split])), divs_url: Response(200, _page([]))}
    )
    out = mi.ingest_corporate_actions(
        tmp_path,
        fetch.get,
        run_id=RUN,
        instrument_meta=meta,
        start=dt.date(2019, 1, 1),
        end=dt.date(2019, 12, 31),
        now=NOW,
    )
    assert [b.name for b in out] == ["splits"], "空区间不写空 batch"
    assert out[0].extra == {"unresolved_ticker": 0}


# =========================================================================== keyed 闸


@pytest.mark.parametrize(
    "path",
    ["/v3/reference/tickers", "/vX/reference/tickers/BBG000MM2P62/events"],
)
def test_phase_two_reference_paths_are_whitelisted(path):
    assert assert_keyed_readonly_path(path) == path


@pytest.mark.parametrize(
    "path",
    [
        "/vX/reference/tickers/META/events",  # 只按 FIGI 查
        "/vX/reference/tickers/BBG000MM2P62/events/extra",
        "/vX/reference/tickers/bbg000mm2p62/events",
        "/v3/reference/tickers/AAPL",
    ],
)
def test_near_miss_reference_paths_are_rejected(path):
    with pytest.raises(TransportBoundaryError):
        assert_keyed_readonly_path(path)


def test_every_phase_two_url_passes_its_own_gate():
    for url in (
        massive.tickers_url(active=True),
        massive.tickers_url(active=False),
        massive.all_splits_url(start="2021-09-23", end="2026-09-22"),
        massive.all_dividends_url(start="2021-09-23", end="2026-09-22"),
        massive.ticker_events_url("BBG000MM2P62"),
    ):
        check_keyed_outgoing(url, {"Authorization": f"Bearer {FAKE_KEY}"})


@pytest.mark.parametrize(
    "headers",
    [{}, {"Authorization": ""}, {"Authorization": "Bearer "}, {"Authorization": "Basic abc"}],
)
def test_a_request_without_a_bearer_header_is_refused(headers):
    with pytest.raises(CredentialUnavailableError, match="Bearer"):
        assert_bearer_headers(headers)


def test_a_transport_that_drops_the_bearer_header_never_reaches_the_opener(monkeypatch):
    """删 Bearer 头 → 请求不发出（变异点）。"""
    url = massive.tickers_url(active=True)
    fetch, opener = _transport({url: Response(200, _page([]))})
    monkeypatch.setattr(
        fetch,
        "build_request",
        lambda u: SimpleNamespace(url=u, headers={}, shown=u),
    )
    with pytest.raises(CredentialUnavailableError):
        fetch.get(url)
    assert opener.calls == []


def test_the_cli_opener_rechecks_the_bearer_header_before_sending(monkeypatch):
    """CLI 的 httpx opener 对**规范化后的请求**再验一次；缺头则 `send` 永不被调用。"""
    import httpx

    sent: list[httpx.Request] = []
    monkeypatch.setattr(
        httpx.Client, "send", lambda self, request, **_: sent.append(request) or httpx.Response(200)
    )
    opener = cli._keyed_http_opener()
    with pytest.raises(CredentialUnavailableError):
        opener(massive.tickers_url(active=True), {})
    assert sent == []
    opener(massive.tickers_url(active=True), {"Authorization": f"Bearer {FAKE_KEY}"})
    assert len(sent) == 1 and sent[0].headers["Authorization"] == f"Bearer {FAKE_KEY}"


# =========================================================================== CLI 凭据出口


@pytest.mark.parametrize(
    "command", [["flatfiles", "--start", "2026-08-03", "--end", "2026-08-03"], ["reference"]]
)
def test_main_us_exits_1_without_credentials_and_makes_no_request(tmp_path, monkeypatch, command):
    for name in (
        "MASSIVE_API_KEY",
        ff.ACCESS_KEY_ID_ENV,
        ff.SECRET_KEY_ENV,
        ff.ENDPOINT_ENV,
        ff.BUCKET_ENV,
    ):
        monkeypatch.delenv(name, raising=False)

    def boom(*_a, **_k):
        raise AssertionError("无凭据时不得构造网络客户端")

    monkeypatch.setattr(cli, "_keyed_http_opener", boom)
    monkeypatch.setattr(cli, "_flatfiles_client", boom)
    assert cli.main_us(["--root", str(tmp_path), *command]) == 1
    assert not (tmp_path / "data").exists()


# =========================================================================== commit_meta_batch


def test_commit_meta_batch_refuses_to_write_ingestion_batch(tmp_path):
    table = massive.normalize_ticker_events(RECORDED_EVENTS, figi="BBG000MM2P62")
    with pytest.raises(batches.BatchWriteError, match="ingestion_batch"):
        batches.commit_meta_batch(
            tmp_path,
            table,
            meta_table=MetaTable.INGESTION_BATCH,
            market="us",
            asset_class="equity",
            scope=mi.REFERENCE_SCOPE,
            source=massive.REST_SOURCE,
            source_version=massive.REST_SOURCE_VERSION,
            run_id=RUN,
        )


def test_the_same_reference_twice_is_two_batches_never_an_overwrite(tmp_path):
    url = massive.ticker_events_url("BBG000MM2P62")
    fetch, _ = _transport({url: Response(200, RECORDED_EVENTS)})
    a = mi.ingest_ticker_events(tmp_path, fetch.get, ["BBG000MM2P62"], run_id=RUN, now=NOW)
    b = mi.ingest_ticker_events(tmp_path, fetch.get, ["BBG000MM2P62"], run_id=RUN, now=NOW)
    assert a.batch_id != b.batch_id
    # content_sha256 是 part 文件字节的哈希，含 batch_id 列，故两 batch 必不同；可重放性看数据列。
    assert a.content_sha256 != b.content_sha256
    data_cols = list(massive.TICKER_EVENTS_SCHEMA.names)
    read = [
        pa.parquet.read_table(
            tmp_path
            / meta_batch_dir(MetaTable.TICKER_EVENTS, x.batch_id, source="massive_rest")
            / "part-0000.parquet"
        ).select(data_cols)
        for x in (a, b)
    ]
    assert read[0].equals(read[1]), "同一响应 → 同一数据（可重放）"
    assert batches.read_ingestion_batch(tmp_path).num_rows == 2
