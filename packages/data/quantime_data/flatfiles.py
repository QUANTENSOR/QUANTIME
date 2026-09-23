"""Massive Flat Files（S3 兼容）只读出口与 `day_aggs_v1` 归一化（QNT-47 阶段 2）。

**客户端选型：boto3**（非 aiobotocore）。摄取是逐文件串行的日终批处理，异步不带来
任何吞吐以外的好处，反而多一层事件循环；boto3 的 SigV4 签名、分页与事件钩子都由 SDK
提供，本模块一行签名代码都不写。

本模块**不 import boto3/botocore**（出网收敛守卫：网络客户端只许出现在 `cli.py`）。
客户端在 `cli._flatfiles_client()` 里构造后注入；这里只做三件事：

1. **只读闸**（`install_readonly_guard`）：在客户端的事件链最前面挂两道钩子，
   任一不过就在请求**发出之前**抛 `TransportBoundaryError`：

   - `before-parameter-build.s3`：操作名必须在 `ALLOWED_OPERATIONS`（只有
     ListObjectsV2 / GetObject）；`Bucket` 必须等于 `FLATFILES_BUCKET`；GetObject 的
     `Key` / ListObjectsV2 的 `Prefix` 必须落在 `day_aggs_v1` 前缀下且逐段合规。
     写、改名、删、ACL、multipart 等一切其它操作都不在白名单里——白名单而非黑名单。
   - `before-send.s3`：对 SDK **实际要发出的**请求再验一遍：方法 GET、https、host 等于
     allowlist 条目 `MASSIVE_FLATFILES.host`（path-style，所以 host 里不出现 bucket）、
     路径落在 `/flatfiles/us_stocks_sip/day_aggs_v1/…` 或是桶根的列举请求、且带 SigV4
     `Authorization`。与 `cli._http_opener` 的「校验的 ≠ 发送的」同一条推理。

   region 必须是 `us-east-1`、endpoint 必须是 allowlist 条目，装闸时即校验。

2. **凭据**（`read_flatfiles_credentials`）：四个字段全部来自 `op run` 注入的环境变量，
   逐个 `.strip()`；缺任何一个即 `CredentialUnavailableError`，没有回退。endpoint 与
   bucket 虽不是秘钥，也从 1Password 取（owner 裁决的 item 里就有），但注入值必须与
   allowlist / 本模块常量逐字一致——vault 里的值被改成别处，出口不跟着走。
   `FlatFilesCredentials` 的 `repr` 不回显任何字段值。

3. **归一化**（`normalize_day_aggs`）：`<YYYY-MM-DD>.csv.gz` → Arrow 表（未复权日线）。

> **待并入 QNT-45 通用层**：重试（`retry_call`）按 QNT-45 PR #23 `retry.py` 的语义在本地
> 实现（`max_attempts=4`、`1s × 2^n`、单次 ≤60s、总预算 300s；`FileNotFoundError` 与
> 边界错误永不重试）。QNT-45 合入后换成 `quantime_data.retry.retry_call`，语义不变。

文档：<https://massive.com/docs/flat-files/stocks/day-aggregates>、
<https://massive.com/docs/flat-files/quickstart>（访问日期 2026-09-23）。
"""

from __future__ import annotations

import csv
import datetime as dt
import gzip
import io
import os
import re
import time
import zoneinfo
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qsl, urlsplit

import pyarrow as pa
from quantime_core.allowlist import MASSIVE_FLATFILES, assert_credentialed_readonly_host

from .keyed_transport import CredentialUnavailableError
from .transport import TransportBoundaryError, path_digest

#: `source` 列取值（湖 `source=` 分区、`data/raw/<source>/`）。与 REST 的 `massive_rest`
#: 分开：两条链路的口径、凭据、失败模式都不同，混在一个 source 里无法按源 drop。
SOURCE = "massive_flatfiles"

#: 解析口径版本。上游对象的版本由 ETag 记录在 raw 旁注里，不混进这一个字段。
SOURCE_VERSION = "massive-flatfiles-day-aggs-v1-2026-09-23"

FLATFILES_BUCKET = "flatfiles"
FLATFILES_REGION = "us-east-1"
FLATFILES_ENDPOINT = f"https://{MASSIVE_FLATFILES.host}"

#: 本卡只取日线聚合。分钟线（`minute_aggs_v1`）、逐笔、报价一律不在前缀内（owner 裁决 3）。
DAY_AGGS_PREFIX = "us_stocks_sip/day_aggs_v1/"

#: 放行的 S3 操作（botocore 的操作名）。只读、且只有这两个。
ALLOWED_OPERATIONS: frozenset[str] = frozenset({"ListObjectsV2", "GetObject"})

_DAY_KEY_RE = re.compile(
    r"^us_stocks_sip/day_aggs_v1/([0-9]{4})/([0-9]{2})/([0-9]{4})-([0-9]{2})-([0-9]{2})\.csv\.gz\Z"
)
_LIST_PREFIX_RE = re.compile(r"^us_stocks_sip/day_aggs_v1/(?:[0-9]{4}/(?:[0-9]{2}/)?)?\Z")

#: 列举请求允许携带的 query 键（ListObjectsV2 的只读参数）。
_LIST_QUERY_KEYS: frozenset[str] = frozenset(
    {"list-type", "prefix", "continuation-token", "max-keys", "encoding-type", "start-after"}
)

#: 环境变量（由 `op run --env-file=docs/ops/massive-flatfiles.env.tpl` 注入）。
ACCESS_KEY_ID_ENV = "MASSIVE_FLATFILES_ACCESS_KEY_ID"
SECRET_KEY_ENV = "MASSIVE_FLATFILES_SECRET_ACCESS_KEY"
ENDPOINT_ENV = "MASSIVE_FLATFILES_ENDPOINT"
BUCKET_ENV = "MASSIVE_FLATFILES_BUCKET"

#: 凭据来源指针（不是 1Password 引用字面量；真正的引用在 tpl 里）。
CREDENTIAL_POINTER = "op:quant-dev/Massive Quantime Flat Files/{Access Key ID,credential}"

#: 上游 CSV 表头（文档 Day Aggregates 一节，按此顺序）。表头变了即拒绝，不猜列。
DAY_AGGS_HEADER: tuple[str, ...] = (
    "ticker",
    "volume",
    "open",
    "close",
    "high",
    "low",
    "window_start",
    "transactions",
)

#: 美股交易日按纽约日切：`window_start` 换算到 America/New_York 必须等于文件名日期。
_NEW_YORK = zoneinfo.ZoneInfo("America/New_York")


class SourceFormatError(ValueError):
    """上游对象布局与文档不符——拒绝猜测。"""


# --------------------------------------------------------------------------- 凭据


@dataclass(frozen=True, slots=True)
class FlatFilesCredentials:
    """已 `.strip()` 的四个字段。`repr` 只给字段名，不给值。"""

    access_key_id: str = field(repr=False)
    secret_access_key: str = field(repr=False)
    endpoint: str = field(repr=False)
    bucket: str = field(repr=False)

    def __repr__(self) -> str:
        return "FlatFilesCredentials(<redacted 4 项>)"

    __str__ = __repr__


def read_flatfiles_credentials(env: dict[str, str] | None = None) -> FlatFilesCredentials:
    """从环境读四个字段并逐个 `.strip()`。缺任何一个 → 凭据不可用，无回退。

    endpoint / bucket 不是秘钥，但必须与 allowlist / 常量逐字一致：注入值偏离即拒绝，
    且错误信息**不回显注入值**（它可能被错填成了秘钥）。
    """
    source = os.environ if env is None else env
    values: dict[str, str] = {}
    for name in (ACCESS_KEY_ID_ENV, SECRET_KEY_ENV, ENDPOINT_ENV, BUCKET_ENV):
        raw = source.get(name)
        if raw is None or not raw.strip():
            raise CredentialUnavailableError(
                f"凭据不可用：环境变量 {name} 未设置或为空。请用 "
                f"`op run --env-file=docs/ops/massive-flatfiles.env.tpl -- <命令>` 注入"
                f"（{CREDENTIAL_POINTER}）。无凭据时本出口不做任何回退。"
            )
        values[name] = raw.strip()
    if values[ENDPOINT_ENV].rstrip("/") != FLATFILES_ENDPOINT:
        raise CredentialUnavailableError(
            f"注入的 {ENDPOINT_ENV} 与 allowlist 条目 MASSIVE_FLATFILES 不一致（值不回显）"
        )
    if values[BUCKET_ENV] != FLATFILES_BUCKET:
        raise CredentialUnavailableError(
            f"注入的 {BUCKET_ENV} 不是 {FLATFILES_BUCKET!r}（值不回显）"
        )
    return FlatFilesCredentials(
        access_key_id=values[ACCESS_KEY_ID_ENV],
        secret_access_key=values[SECRET_KEY_ENV],
        endpoint=FLATFILES_ENDPOINT,
        bucket=FLATFILES_BUCKET,
    )


# --------------------------------------------------------------------------- 只读闸


def assert_day_aggs_key(key: str) -> dt.date:
    """GetObject 的 key 必须是 `us_stocks_sip/day_aggs_v1/<Y>/<M>/<Y-M-D>.csv.gz`，返回日期。"""
    m = _DAY_KEY_RE.fullmatch(key) if isinstance(key, str) else None
    if m is None:
        raise TransportBoundaryError(f"key 不在 day_aggs_v1 白名单形态内: {path_digest(str(key))}")
    year, month, y2, m2, d2 = m.groups()
    if (year, month) != (y2, m2):
        raise TransportBoundaryError(f"key 的目录年月与文件名不符: {path_digest(key)}")
    try:
        return dt.date(int(y2), int(m2), int(d2))
    except ValueError:
        raise TransportBoundaryError(f"key 的日期非法: {path_digest(key)}") from None


def assert_list_prefix(prefix: str) -> str:
    """ListObjectsV2 的 Prefix 只能是 `day_aggs_v1/`、`…/<Y>/` 或 `…/<Y>/<M>/`。"""
    if not isinstance(prefix, str) or _LIST_PREFIX_RE.fullmatch(prefix) is None:
        raise TransportBoundaryError(
            f"列举前缀不在 day_aggs_v1 白名单内: {path_digest(str(prefix))}"
        )
    return prefix


def check_call(operation: str, params: dict[str, Any]) -> None:
    """参数闸：操作名 / bucket / key 或 prefix。**纯函数**，钩子与测试共用。"""
    if operation not in ALLOWED_OPERATIONS:
        raise TransportBoundaryError(
            f"S3 操作 {operation!r} 不在只读白名单 {sorted(ALLOWED_OPERATIONS)} 内，拒绝发出请求"
        )
    bucket = params.get("Bucket")
    if bucket != FLATFILES_BUCKET:
        raise TransportBoundaryError(
            f"bucket 不是 {FLATFILES_BUCKET!r}，拒绝发出请求: {path_digest(str(bucket))}"
        )
    if operation == "GetObject":
        assert_day_aggs_key(params.get("Key", ""))
        extra = set(params) - {"Bucket", "Key", "IfMatch", "ChecksumMode"}
        if extra:
            raise TransportBoundaryError(f"GetObject 带了白名单外的参数: {sorted(extra)}")
    else:
        assert_list_prefix(params.get("Prefix", ""))
        # botocore 会自行注入 `EncodingType='url'`（列举结果 key 的编码方式，只读、不改语义）；
        # 只放行这一个取值。
        if params.get("EncodingType", "url") != "url":
            raise TransportBoundaryError("ListObjectsV2 的 EncodingType 只允许 'url'")
        allowed = {"Bucket", "Prefix", "ContinuationToken", "MaxKeys", "StartAfter", "EncodingType"}
        extra = set(params) - allowed
        if extra:
            raise TransportBoundaryError(f"ListObjectsV2 带了白名单外的参数: {sorted(extra)}")


def check_outgoing(method: str, url: str, headers: dict[str, str] | Any) -> None:
    """发送闸：对 SDK 规范化、签好名之后的请求再验一遍。**纯函数**。"""
    if method != "GET":
        raise TransportBoundaryError(f"Flat Files 出口只允许 GET，得到 {method!r}")
    parts = urlsplit(url)
    if parts.scheme != "https":
        raise TransportBoundaryError("Flat Files 出口只允许 https")
    if parts.username or parts.password or parts.fragment:
        raise TransportBoundaryError("URL 不得携带凭据或 fragment")
    host = parts.hostname or ""
    if host != MASSIVE_FLATFILES.host:
        raise TransportBoundaryError(
            f"host 不是 allowlist 条目 MASSIVE_FLATFILES，拒绝发出请求: {path_digest(host)}"
        )
    assert_credentialed_readonly_host(host)
    bucket_root = f"/{FLATFILES_BUCKET}"
    path = parts.path
    if path.startswith(bucket_root + "/"):
        assert_day_aggs_key(path.removeprefix(bucket_root + "/"))
        if parts.query:
            raise TransportBoundaryError("GetObject 请求不应带 query")
    elif path in (bucket_root, bucket_root + "/"):
        query = dict(parse_qsl(parts.query, keep_blank_values=True))
        if query.get("list-type") != "2" or set(query) - _LIST_QUERY_KEYS:
            raise TransportBoundaryError("桶根请求只允许 ListObjectsV2 的只读参数")
        assert_list_prefix(query.get("prefix", ""))
    else:
        raise TransportBoundaryError(f"路径不在 Flat Files 白名单内: {path_digest(path)}")
    auth = _header(headers, "Authorization")
    if not auth or not auth.startswith("AWS4-HMAC-SHA256 "):
        raise TransportBoundaryError(
            "请求未带 SigV4 签名（Authorization 缺失或不是 AWS4-HMAC-SHA256）"
        )


def _header(headers: Any, name: str) -> str | None:
    getter = getattr(headers, "get", None)
    if getter is None:
        return None
    value = getter(name)
    if isinstance(value, bytes):
        value = value.decode("latin-1")
    return value


def _param_hook(params: dict[str, Any], model: Any, **_: Any) -> None:
    check_call(model.name, params)


def _send_hook(request: Any, **_: Any) -> None:
    check_outgoing(request.method, request.url, request.headers)


def install_readonly_guard(client: Any) -> Any:
    """给一个 boto3 S3 客户端装只读闸并返回它。region / endpoint 不符即拒绝。

    钩子用 `register_first`：排在 SDK 自身与任何后装钩子之前，后来者无法抢先放行。
    """
    meta = client.meta
    if meta.region_name != FLATFILES_REGION:
        raise TransportBoundaryError(f"Flat Files 客户端 region 必须是 {FLATFILES_REGION}")
    if str(meta.endpoint_url).rstrip("/") != FLATFILES_ENDPOINT:
        raise TransportBoundaryError("Flat Files 客户端 endpoint 不是 allowlist 条目")
    meta.events.register_first("before-parameter-build.s3", _param_hook)
    meta.events.register_first("before-send.s3", _send_hook)
    return client


# --------------------------------------------------------------------------- 重试（待并入 QNT-45）


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    """QNT-45 `retry.RetryPolicy` 的本地同义实现（待并入 QNT-45 通用层）。"""

    max_attempts: int = 4
    base_delay: float = 1.0
    multiplier: float = 2.0
    max_delay: float = 60.0
    max_total_seconds: float = 300.0

    def delay_for(self, attempt: int) -> float:
        """第 `attempt` 次失败（从 1 起）之后的等待秒数。"""
        return min(self.base_delay * self.multiplier ** (attempt - 1), self.max_delay)


DEFAULT_RETRY = RetryPolicy()


class RetryExhaustedError(RuntimeError):
    """重试用尽或超出总预算。调用方必须让该文件失败，不得当成空结果。"""


#: 视为瞬时故障的 SDK 异常类名（本模块不 import botocore，按类名鸭子判定）。
_TRANSIENT_SDK_ERRORS: frozenset[str] = frozenset(
    {
        "EndpointConnectionError",
        "ConnectionClosedError",
        "ReadTimeoutError",
        "ConnectTimeoutError",
        "IncompleteReadError",
        "ResponseStreamingError",
    }
)
_TRANSIENT_STATUS: frozenset[int] = frozenset({429, 500, 502, 503, 504})


def http_status_of(exc: BaseException) -> int | None:
    response = getattr(exc, "response", None)
    if not isinstance(response, dict):
        return None
    status = response.get("ResponseMetadata", {}).get("HTTPStatusCode")
    return status if isinstance(status, int) else None


def is_retryable(exc: BaseException) -> bool:
    """边界错误、格式错误、404/403 永不重试；429/5xx 与连接类故障重试。"""
    if isinstance(exc, TransportBoundaryError | SourceFormatError | CredentialUnavailableError):
        return False
    if isinstance(exc, FileNotFoundError):
        return False
    status = http_status_of(exc)
    if status is not None:
        return status in _TRANSIENT_STATUS
    if type(exc).__name__ in _TRANSIENT_SDK_ERRORS:
        return True
    return isinstance(exc, OSError)


def retry_call[T](
    fn: Callable[[], T],
    *,
    policy: RetryPolicy = DEFAULT_RETRY,
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
    label: str = "",
    on_retry: Callable[[int, float, BaseException], None] | None = None,
) -> T:
    """按 `policy` 调用 `fn`；不可重试的异常原样抛出，重试用尽抛 `RetryExhaustedError`。"""
    started = monotonic()
    for attempt in range(1, policy.max_attempts + 1):
        try:
            return fn()
        except Exception as exc:
            if not is_retryable(exc):
                raise
            if attempt == policy.max_attempts:
                raise RetryExhaustedError(
                    f"{label}: 重试 {policy.max_attempts} 次后仍失败（{type(exc).__name__}）"
                ) from None
            delay = policy.delay_for(attempt)
            if monotonic() - started + delay > policy.max_total_seconds:
                raise RetryExhaustedError(
                    f"{label}: 超出重试总预算 {policy.max_total_seconds}s（{type(exc).__name__}）"
                ) from None
            if on_retry is not None:
                on_retry(attempt, delay, exc)
            sleep(delay)
    raise AssertionError("unreachable")  # pragma: no cover


# --------------------------------------------------------------------------- 客户端封装


@dataclass(frozen=True, slots=True)
class ObjectInfo:
    """列举得到的一个对象：key + ETag（去引号）+ 字节数 + 最后修改时间。"""

    key: str
    etag: str
    size: int
    last_modified: str

    @property
    def date(self) -> dt.date:
        return assert_day_aggs_key(self.key)


@dataclass(frozen=True, slots=True)
class FetchedObject:
    info: ObjectInfo
    payload: bytes


def _etag(raw: Any) -> str:
    return str(raw).strip('"')


class DayAggsBucket:
    """只读封装：列举 + 取对象。客户端必须已装闸（构造时再装一遍也无害——同一钩子幂等）。"""

    def __init__(
        self,
        client: Any,
        *,
        policy: RetryPolicy = DEFAULT_RETRY,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._client = install_readonly_guard(client)
        self._policy = policy
        self._sleep = sleep
        self._monotonic = monotonic
        #: 实际发生的重试（`(label, attempt, delay)`），供报告计数。
        self.retries: list[tuple[str, int, float]] = []

    def _retry[T](self, fn: Callable[[], T], label: str) -> T:
        return retry_call(
            fn,
            policy=self._policy,
            sleep=self._sleep,
            monotonic=self._monotonic,
            label=label,
            on_retry=lambda attempt, delay, _exc: self.retries.append((label, attempt, delay)),
        )

    def list_day_aggs(self, prefix: str = DAY_AGGS_PREFIX) -> Iterator[ObjectInfo]:
        """列出前缀下的全部 day_aggs 对象（按 ContinuationToken 翻到底）。

        列举结果里若出现白名单形态之外的 key，**跳过而不是抛**——那只是我们不取的对象
        （例如上游在同一前缀下放了说明文件），不是边界违规；取它时照样会被闸挡下。
        """
        assert_list_prefix(prefix)
        token: str | None = None
        while True:
            kwargs: dict[str, Any] = {"Bucket": FLATFILES_BUCKET, "Prefix": prefix}
            if token:
                kwargs["ContinuationToken"] = token
            page = self._retry(
                lambda kw=kwargs: self._client.list_objects_v2(**kw), f"list {prefix}"
            )
            for item in page.get("Contents", []) or []:
                key = item["Key"]
                if _DAY_KEY_RE.fullmatch(key) is None:
                    continue
                yield ObjectInfo(
                    key=key,
                    etag=_etag(item["ETag"]),
                    size=int(item["Size"]),
                    last_modified=_iso(item.get("LastModified")),
                )
            if not page.get("IsTruncated"):
                return
            token = page.get("NextContinuationToken")
            if not token:
                raise SourceFormatError("列举结果 IsTruncated 但没有 NextContinuationToken")

    def get(self, info: ObjectInfo) -> FetchedObject:
        """取一个对象。`IfMatch` 钉住列举时的 ETag：上游在列举与下载之间换了内容就 412。"""
        assert_day_aggs_key(info.key)

        def once() -> FetchedObject:
            resp = self._client.get_object(
                Bucket=FLATFILES_BUCKET, Key=info.key, IfMatch=f'"{info.etag}"'
            )
            body = resp["Body"].read()
            etag = _etag(resp.get("ETag", info.etag))
            if etag != info.etag:
                raise SourceFormatError(f"{info.key}: 下载的 ETag 与列举不符")
            if len(body) != info.size:
                raise OSError(f"{info.key}: 读到 {len(body)} 字节，列举为 {info.size}（截断）")
            return FetchedObject(info=info, payload=body)

        return self._retry(once, f"get {info.key}")


def _iso(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, dt.datetime):
        return value.astimezone(dt.UTC).isoformat()
    return str(value)


# --------------------------------------------------------------------------- 归一化

#: 美股日线（未复权，Flat Files 口径）。`session_date` 来自对象 key，是纽约交易日。
DAY_AGGS_SCHEMA = pa.schema(
    [
        pa.field("ticker", pa.string(), nullable=False),
        pa.field("session_date", pa.date32(), nullable=False),
        pa.field("window_start", pa.timestamp("us", tz="UTC"), nullable=False),
        pa.field("open", pa.float64(), nullable=False),
        pa.field("high", pa.float64(), nullable=False),
        pa.field("low", pa.float64(), nullable=False),
        pa.field("close", pa.float64(), nullable=False),
        pa.field("volume", pa.float64(), nullable=False),
        pa.field("transactions", pa.int64(), nullable=True),
    ]
)

TIME_COLUMN = "window_start"


def _ns_to_utc(value: int) -> dt.datetime:
    """纳秒 epoch → UTC（截到微秒，与 Parquet `timestamp('us')` 对齐）。"""
    seconds, ns = divmod(value, 1_000_000_000)
    return dt.datetime.fromtimestamp(seconds, tz=dt.UTC) + dt.timedelta(microseconds=ns // 1000)


def normalize_day_aggs(payload: bytes, *, session_date: dt.date) -> pa.Table:
    """`<YYYY-MM-DD>.csv.gz` → 归一化表（按 ticker 升序）。

    逐行校验：表头与文档逐列一致；数值可解析；`window_start` 落在 `session_date` 的纽约日内；
    同一 ticker 不得出现两次。任何一条不符即 `SourceFormatError`——不跳行、不猜。
    `payload` 可以是 gzip 或已解压的 CSV（fixture 存解压后的前 100 行）。
    """
    text_bytes = gzip.decompress(payload) if payload[:2] == b"\x1f\x8b" else payload
    try:
        text = text_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SourceFormatError(f"{session_date}: 不是 UTF-8 CSV: {exc}") from exc
    reader = csv.reader(io.StringIO(text, newline=""))
    try:
        header = tuple(next(reader))
    except StopIteration:
        raise SourceFormatError(f"{session_date}: 空文件") from None
    if header != DAY_AGGS_HEADER:
        raise SourceFormatError(f"{session_date}: 表头与文档不符: {header!r}")
    cols: dict[str, list[Any]] = {name: [] for name in DAY_AGGS_SCHEMA.names}
    seen: set[str] = set()
    for lineno, row in enumerate(reader, start=2):
        if not row:
            continue
        if len(row) != len(DAY_AGGS_HEADER):
            raise SourceFormatError(f"{session_date}: 第 {lineno} 行列数 {len(row)}")
        ticker, volume, open_, close, high, low, window_start, transactions = row
        if not ticker or ticker != ticker.strip():
            raise SourceFormatError(f"{session_date}: 第 {lineno} 行 ticker 为空或含空白")
        if ticker in seen:
            raise SourceFormatError(f"{session_date}: ticker {ticker!r} 重复")
        seen.add(ticker)
        try:
            ts = _ns_to_utc(int(window_start))
            values = [float(v) for v in (open_, high, low, close, volume)]
            trades = int(transactions) if transactions != "" else None
        except ValueError as exc:
            raise SourceFormatError(f"{session_date}: 第 {lineno} 行数值非法: {exc}") from None
        if ts.astimezone(_NEW_YORK).date() != session_date:
            raise SourceFormatError(
                f"{session_date}: 第 {lineno} 行 window_start 不在该纽约交易日内: {ts.isoformat()}"
            )
        cols["ticker"].append(ticker)
        cols["session_date"].append(session_date)
        cols["window_start"].append(ts)
        for name, value in zip(("open", "high", "low", "close", "volume"), values, strict=True):
            cols[name].append(value)
        cols["transactions"].append(trades)
    table = pa.Table.from_pydict(cols, schema=DAY_AGGS_SCHEMA)
    return table.sort_by("ticker")
