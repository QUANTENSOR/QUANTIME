"""Massive Flat Files 只读闸、凭据、重试与归一化（QNT-47 阶段 2）。

全部离线：boto3 客户端是**真的**（dummy 凭据），但在闸之后再挂一个 `before-send` 钩子
抛哨兵异常——请求能走到哨兵，说明它过了只读闸；被闸拒绝的请求根本到不了哨兵。
没有任何字节离开本机。
"""

from __future__ import annotations

import datetime as dt
import gzip
from pathlib import Path

import pytest
from quantime_data import cli
from quantime_data import flatfiles as ff
from quantime_data.keyed_transport import CredentialUnavailableError
from quantime_data.transport import TransportBoundaryError

RECORDED = Path(__file__).resolve().parents[3] / "fixtures" / "massive_recorded"
HEAD100 = RECORDED / "day-aggs-2026-08-03-head100.csv"
DAY_KEY = "us_stocks_sip/day_aggs_v1/2026/08/2026-08-03.csv.gz"
DUMMY_ID = "dummy-access-key-id-not-real"
DUMMY_SECRET = "dummy-secret-not-a-real-credential"


class ReachedSend(Exception):
    """哨兵：请求已过闸、即将发出。"""


def _env(**over: str) -> dict[str, str]:
    env = {
        ff.ACCESS_KEY_ID_ENV: DUMMY_ID,
        ff.SECRET_KEY_ENV: DUMMY_SECRET,
        ff.ENDPOINT_ENV: ff.FLATFILES_ENDPOINT,
        ff.BUCKET_ENV: ff.FLATFILES_BUCKET,
    }
    env.update(over)
    return env


@pytest.fixture
def client():
    """真 boto3 客户端 + 只读闸（`cli._flatfiles_client`）+ 闸后的哨兵。"""
    c = cli._flatfiles_client(ff.read_flatfiles_credentials(_env()))
    seen: list[tuple[str, str]] = []

    def sentinel(request, **_):
        seen.append((request.method, request.url))
        raise ReachedSend(request.url)

    c.meta.events.register("before-send.s3", sentinel)
    c.seen = seen
    return c


# ---- 放行：只读两操作 ----


def test_get_object_on_a_day_aggs_key_reaches_the_wire_signed(client):
    with pytest.raises(ReachedSend):
        client.get_object(Bucket="flatfiles", Key=DAY_KEY)
    method, url = client.seen[0]
    assert method == "GET"
    assert url == f"https://files.massive.com/flatfiles/{DAY_KEY}"


def test_list_objects_v2_on_a_month_prefix_reaches_the_wire(client):
    with pytest.raises(ReachedSend):
        client.list_objects_v2(Bucket="flatfiles", Prefix="us_stocks_sip/day_aggs_v1/2026/08/")
    assert client.seen and client.seen[0][0] == "GET"


# ---- 拒绝：写 / 删 / 他桶 / 他前缀（请求到不了哨兵） ----


@pytest.mark.parametrize(
    ("op", "kwargs"),
    [
        ("put_object", {"Bucket": "flatfiles", "Key": DAY_KEY, "Body": b"x"}),
        ("delete_object", {"Bucket": "flatfiles", "Key": DAY_KEY}),
        (
            "delete_objects",
            {"Bucket": "flatfiles", "Delete": {"Objects": [{"Key": DAY_KEY}]}},
        ),
        (
            "copy_object",
            {"Bucket": "flatfiles", "Key": DAY_KEY, "CopySource": "flatfiles/" + DAY_KEY},
        ),
        ("create_multipart_upload", {"Bucket": "flatfiles", "Key": DAY_KEY}),
        ("put_object_acl", {"Bucket": "flatfiles", "Key": DAY_KEY, "ACL": "public-read"}),
        ("delete_bucket", {"Bucket": "flatfiles"}),
        ("list_buckets", {}),
        ("head_object", {"Bucket": "flatfiles", "Key": DAY_KEY}),
    ],
)
def test_write_delete_and_other_operations_never_leave_the_process(client, op, kwargs):
    with pytest.raises(TransportBoundaryError, match="只读白名单"):
        getattr(client, op)(**kwargs)
    assert client.seen == []


@pytest.mark.parametrize("bucket", ["flatfiles-other", "otherbucket", "FLATFILES"])
def test_another_bucket_is_rejected_for_get_and_list(client, bucket):
    with pytest.raises(TransportBoundaryError, match="bucket"):
        client.get_object(Bucket=bucket, Key=DAY_KEY)
    with pytest.raises(TransportBoundaryError, match="bucket"):
        client.list_objects_v2(Bucket=bucket, Prefix="us_stocks_sip/day_aggs_v1/")
    assert client.seen == []


@pytest.mark.parametrize(
    "key",
    [
        "us_stocks_sip/minute_aggs_v1/2026/08/2026-08-03.csv.gz",  # 分钟线：禁止
        "us_options_opra/day_aggs_v1/2026/08/2026-08-03.csv.gz",
        "us_stocks_sip/day_aggs_v1/2026/07/2026-08-03.csv.gz",  # 目录与文件名不符
        "us_stocks_sip/day_aggs_v1/2026/02/2026-02-30.csv.gz",  # 非法日期
        "us_stocks_sip/day_aggs_v1/2026/08/../08/2026-08-03.csv.gz",
    ],
)
def test_keys_outside_day_aggs_are_rejected(client, key):
    with pytest.raises(TransportBoundaryError):
        client.get_object(Bucket="flatfiles", Key=key)
    assert client.seen == []


@pytest.mark.parametrize(
    "prefix",
    ["", "us_stocks_sip/", "us_stocks_sip/minute_aggs_v1/", "us_stocks_sip/day_aggs_v1/2026/8/"],
)
def test_list_prefixes_outside_day_aggs_are_rejected(client, prefix):
    with pytest.raises(TransportBoundaryError, match="列举前缀"):
        client.list_objects_v2(Bucket="flatfiles", Prefix=prefix)
    assert client.seen == []


def test_extra_get_parameters_are_rejected(client):
    with pytest.raises(TransportBoundaryError, match="白名单外的参数"):
        client.get_object(Bucket="flatfiles", Key=DAY_KEY, VersionId="v1")


def test_list_encoding_type_is_only_accepted_as_url():
    ff.check_call("ListObjectsV2", {"Bucket": "flatfiles", "Prefix": ff.DAY_AGGS_PREFIX})
    ff.check_call(
        "ListObjectsV2",
        {"Bucket": "flatfiles", "Prefix": ff.DAY_AGGS_PREFIX, "EncodingType": "url"},
    )
    with pytest.raises(TransportBoundaryError, match="EncodingType"):
        ff.check_call(
            "ListObjectsV2",
            {"Bucket": "flatfiles", "Prefix": ff.DAY_AGGS_PREFIX, "EncodingType": "raw"},
        )


# ---- 发送闸（签名后的请求） ----

SIGNED = {"Authorization": "AWS4-HMAC-SHA256 Credential=x/y, SignedHeaders=host, Signature=z"}


def test_send_gate_accepts_a_signed_get():
    ff.check_outgoing("GET", f"https://files.massive.com/flatfiles/{DAY_KEY}", SIGNED)
    ff.check_outgoing(
        "GET",
        "https://files.massive.com/flatfiles?list-type=2&prefix=us_stocks_sip%2Fday_aggs_v1%2F2026%2F",
        SIGNED,
    )


@pytest.mark.parametrize("method", ["PUT", "POST", "DELETE", "HEAD"])
def test_send_gate_rejects_every_non_get_method(method):
    """S3 Put 须被拒（变异点）：即使参数闸被绕过，签好名的 PUT 也发不出去。"""
    with pytest.raises(TransportBoundaryError, match="只允许 GET"):
        ff.check_outgoing(method, f"https://files.massive.com/flatfiles/{DAY_KEY}", SIGNED)


@pytest.mark.parametrize(
    "url",
    [
        f"http://files.massive.com/flatfiles/{DAY_KEY}",
        f"https://files.massive.com.evil.test/flatfiles/{DAY_KEY}",
        f"https://api.massive.com/flatfiles/{DAY_KEY}",
        f"https://files.massive.com/otherbucket/{DAY_KEY}",
        f"https://files.massive.com/flatfiles/{DAY_KEY}?uploads",
        "https://files.massive.com/flatfiles?delete",
        "https://files.massive.com/flatfiles?list-type=2&prefix=us_stocks_sip%2F",
        f"https://u:p@files.massive.com/flatfiles/{DAY_KEY}",
    ],
)
def test_send_gate_rejects_urls_outside_the_readonly_shape(url):
    with pytest.raises(TransportBoundaryError):
        ff.check_outgoing("GET", url, SIGNED)


def test_send_gate_rejects_unsigned_requests():
    with pytest.raises(TransportBoundaryError, match="SigV4"):
        ff.check_outgoing("GET", f"https://files.massive.com/flatfiles/{DAY_KEY}", {})


def test_guard_refuses_a_client_pointed_elsewhere():
    import boto3

    other = boto3.client(
        "s3",
        endpoint_url="https://s3.amazonaws.com",
        region_name="us-east-1",
        aws_access_key_id=DUMMY_ID,
        aws_secret_access_key=DUMMY_SECRET,
    )
    with pytest.raises(TransportBoundaryError, match="endpoint"):
        ff.install_readonly_guard(other)


# ---- 凭据 ----


def test_credentials_are_stripped_and_redacted():
    creds = ff.read_flatfiles_credentials(
        _env(**{ff.ACCESS_KEY_ID_ENV: f"  {DUMMY_ID}\n", ff.SECRET_KEY_ENV: f"{DUMMY_SECRET} "})
    )
    assert creds.access_key_id == DUMMY_ID
    assert creds.secret_access_key == DUMMY_SECRET
    assert DUMMY_SECRET not in repr(creds) and DUMMY_ID not in str(creds)


@pytest.mark.parametrize(
    "name", [ff.ACCESS_KEY_ID_ENV, ff.SECRET_KEY_ENV, ff.ENDPOINT_ENV, ff.BUCKET_ENV]
)
def test_any_missing_credential_field_fails_with_no_fallback(name):
    env = _env()
    del env[name]
    with pytest.raises(CredentialUnavailableError, match=name):
        ff.read_flatfiles_credentials(env)
    with pytest.raises(CredentialUnavailableError):
        ff.read_flatfiles_credentials(_env(**{name: "   "}))


def test_endpoint_or_bucket_mismatch_is_rejected_without_echoing_the_value():
    leaked = "looks-like-a-secret-value"
    for name in (ff.ENDPOINT_ENV, ff.BUCKET_ENV):
        with pytest.raises(CredentialUnavailableError) as info:
            ff.read_flatfiles_credentials(_env(**{name: leaked}))
        assert leaked not in str(info.value)


# ---- 重试（本地语义，待并入 QNT-45 通用层） ----


class _Status(Exception):
    def __init__(self, status: int) -> None:
        self.response = {"ResponseMetadata": {"HTTPStatusCode": status}}


def _flaky(*errors: Exception, result: str = "ok"):
    queue = list(errors)
    calls = {"n": 0}

    def fn():
        calls["n"] += 1
        if queue:
            raise queue.pop(0)
        return result

    return fn, calls


def test_transient_failures_are_retried_with_exponential_backoff():
    fn, calls = _flaky(_Status(503), _Status(429), ConnectionResetError())
    sleeps: list[float] = []
    assert ff.retry_call(fn, sleep=sleeps.append, monotonic=lambda: 0.0) == "ok"
    assert calls["n"] == 4
    assert sleeps == [1.0, 2.0, 4.0]


@pytest.mark.parametrize(
    "exc",
    [
        _Status(403),
        _Status(404),
        TransportBoundaryError("x"),
        ff.SourceFormatError("x"),
        CredentialUnavailableError("x"),
    ],
)
def test_permanent_failures_are_not_retried(exc):
    fn, calls = _flaky(exc)
    with pytest.raises(type(exc)):
        ff.retry_call(fn, sleep=lambda _s: None, monotonic=lambda: 0.0)
    assert calls["n"] == 1


def test_exhausted_retries_raise_rather_than_return_empty():
    fn, calls = _flaky(*[_Status(500)] * 10)
    with pytest.raises(ff.RetryExhaustedError):
        ff.retry_call(fn, sleep=lambda _s: None, monotonic=lambda: 0.0)
    assert calls["n"] == ff.DEFAULT_RETRY.max_attempts


def test_total_budget_stops_retrying():
    fn, _ = _flaky(*[_Status(500)] * 10)
    policy = ff.RetryPolicy(
        max_attempts=10, base_delay=100.0, max_delay=500.0, max_total_seconds=150.0
    )
    with pytest.raises(ff.RetryExhaustedError, match="总预算"):
        ff.retry_call(fn, policy=policy, sleep=lambda _s: None, monotonic=lambda: 0.0)


# ---- 归一化（真实录制的前 100 行） ----


def test_recorded_head100_normalizes_to_99_sorted_rows():
    table = ff.normalize_day_aggs(HEAD100.read_bytes(), session_date=dt.date(2026, 8, 3))
    assert table.num_rows == 99
    assert table.schema == ff.DAY_AGGS_SCHEMA
    tickers = table.column("ticker").to_pylist()
    assert tickers == sorted(tickers)
    first = table.slice(0, 1).to_pylist()[0]
    assert first["ticker"] == "A"
    assert first["close"] == pytest.approx(139.80)
    assert first["transactions"] == 30358
    assert first["window_start"] == dt.datetime(2026, 8, 3, 4, 0, tzinfo=dt.UTC)


def test_gzip_and_plain_payloads_normalize_identically():
    plain = HEAD100.read_bytes()
    a = ff.normalize_day_aggs(plain, session_date=dt.date(2026, 8, 3))
    b = ff.normalize_day_aggs(gzip.compress(plain), session_date=dt.date(2026, 8, 3))
    assert a.equals(b)


def test_a_row_outside_the_session_date_is_rejected():
    with pytest.raises(ff.SourceFormatError):
        ff.normalize_day_aggs(HEAD100.read_bytes(), session_date=dt.date(2026, 8, 4))


def test_a_changed_header_is_rejected():
    lines = HEAD100.read_bytes().split(b"\n")
    lines[0] = lines[0].replace(b"transactions", b"trades")
    with pytest.raises(ff.SourceFormatError, match="表头"):
        ff.normalize_day_aggs(b"\n".join(lines), session_date=dt.date(2026, 8, 3))


def test_a_duplicate_ticker_is_rejected():
    lines = HEAD100.read_bytes().rstrip(b"\n").split(b"\n")
    payload = b"\n".join([*lines, lines[1]]) + b"\n"
    with pytest.raises(ff.SourceFormatError, match="重复"):
        ff.normalize_day_aggs(payload, session_date=dt.date(2026, 8, 3))
