"""Host allowlist：纯数据 + 纯函数（ADR-0003 §3.3；owner 5A 已批准 §9.10 迁移）。

本文件是**唯一**允许出现 allowlist host 字面量的文件（`public_readonly=True` 的公共只读
host，以及 `credentialed_readonly=True` 的需 key 只读数据 host），且不得 import 任何
网络客户端（import-linter 守卫）。`.claude/rules/crypto-boundaries.md` ①② 的路径与字段名
回写由 QNT-39 单独 PR 完成（owner 5A 裁决：与 ADR「同一 PR」表述的偏离已建卡）。

字段名沿用 rules 原文 `public_readonly=true/false`，不引入 `kind` 枚举（§3.3）。
`public_readonly=False` **且** `credentialed_readonly=False` 的条目才是 ADR-0001 D1.7 交易 host
集合。需 API key 的**只读数据源**（QNT-47 Massive）同样是 `public_readonly=False`——它不是
公共可取的——但它绝不是交易出口，所以额外带 `credentialed_readonly=True`，由第三个断言
`assert_credentialed_readonly_host` 放行，`assert_trading_host` 对它 fail-closed。
三个断言两两互不放行：一个 host 只属于一类。

本文件是 host 字面量的**唯一**出处，因此其余模块不得复制 host 字符串，而应引用这里的
具名条目（如 `BINANCE_VISION_ARCHIVE.host`）。这既让静态守卫 grep 保持有效，
也保证「改 allowlist 就等于改所有调用方」，不会出现绕过 allowlist 的第二份 host 表。
"""

from __future__ import annotations

from dataclasses import dataclass


class HostNotAllowedError(ValueError):
    """host 不在 allowlist，或不属于被断言的那一类。"""


class TradingBoundaryError(RuntimeError):
    """交易边界断言失败（ADR-0001 D1.7「缺一 fail-closed」）。"""


@dataclass(frozen=True, slots=True)
class DemoMarker:
    """模拟盘标记：请求头 + 注入 key 的标签要求（§3.3 逐请求校验）。

    `header_name`/`header_value`：交易请求必须携带的头（OKX `x-simulated-trading: 1`、
    Bitget `paptrading: 1`）。`key_label_contains`：`op` 注入的 key 标签必须包含的子串
    （`.strip()` 后比较）。`None` 表示该维度无要求（如 Binance testnet 独立 host）。
    """

    header_name: str | None = None
    header_value: str | None = None
    key_label_contains: str | None = None


@dataclass(frozen=True, slots=True)
class HostEntry:
    """allowlist 条目。`doc_url` 是 crypto-boundaries ① 要求的官方文档链接。

    `credentialed_readonly`：需 API key 才能取、但**只读数据**的 host（QNT-47 Massive）。这类
    host 的 `public_readonly` 必为 `False`（它确实不是公共可取的），但它同样**不是**交易
    host——把它塞进 D1.7 集合会让一个行情 host 变成合法的下单出口。所以它自成一类。
    """

    host: str
    public_readonly: bool
    exchange: str
    doc_url: str
    demo_marker: DemoMarker | None = None
    credentialed_readonly: bool = False

    def __post_init__(self) -> None:
        if self.credentialed_readonly and self.public_readonly:
            raise ValueError(f"{self.host}: credentialed_readonly 与 public_readonly 互斥")
        if self.credentialed_readonly and self.demo_marker is not None:
            raise ValueError(f"{self.host}: 只读数据 host 不该有交易用的 demo_marker")


# 公共只读归档/镜像 host（ADR-0003 §7、§9.5）。刻意不收 api.binance.com /
# fapi.binance.com：本机所在美国节点访问二者返回 451（§9.5 原始裁决，QNT-28 2026-09-21
# 复测仍为 451）。交易 host（`public_readonly=False` 且 `credentialed_readonly=False`）条目由
# QNT-33 paper 交易卡加入——本表**目前一条都没有**。

#: Binance 公开归档（按文件下载 zip + `.CHECKSUM`）——K 线 / fundingRate / metrics 的底座。
BINANCE_VISION_ARCHIVE = HostEntry(
    host="data.binance.vision",
    public_readonly=True,
    exchange="binance",
    doc_url="https://github.com/binance/binance-public-data",
)

#: Binance 无 key 现货行情镜像（`/api/v3/*` 只读子集，不含 User Data Stream）。
BINANCE_VISION_SPOT_MIRROR = HostEntry(
    host="data-api.binance.vision",
    public_readonly=True,
    exchange="binance",
    doc_url="https://developers.binance.com/docs/binance-spot-api-docs/faqs/market_data_only",
)

# QNT-47：Massive（原 Polygon.io）美股 + 美股期权 REST。需 API key，所以 `public_readonly`
# 必为 False；但它只提供行情/参考数据，没有任何下单或账户变更端点，因此标 `credentialed_readonly`
# 而**不**进 ADR-0001 D1.7 交易 host 集合。key 只经 `op run` 注入，永不出现在 URL 里。

#: Massive REST（新域名）。凭据走 `Authorization: Bearer`，不用 `apiKey=` query（query 会
#: 落进代理/访问日志）。放行的路径逐条列在 `data/keyed_transport.py`。
MASSIVE_REST = HostEntry(
    host="api.massive.com",
    public_readonly=False,
    credentialed_readonly=True,
    exchange="massive",
    doc_url="https://massive.com/docs/rest/stocks/overview",
)

#: Polygon 旧域名。2025-10-30 改名 Massive 后两域名并行，官方称「will continue to work for
#: an extended period」并会提前通知下线（<https://massive.com/blog/polygon-is-now-massive>）。
#: 登记它只为「旧域名也必须过同一套闸」——本卡的 URL 构造一律用 `MASSIVE_REST`，
#: 旧域名是兼容入口，不是默认值。
MASSIVE_REST_LEGACY = HostEntry(
    host="api.polygon.io",
    public_readonly=False,
    credentialed_readonly=True,
    exchange="massive",
    doc_url="https://massive.com/blog/polygon-is-now-massive",
)

#: Massive Flat Files（S3 兼容端点，SigV4，region us-east-1，bucket `flatfiles`）。QNT-47 阶段 2
#: 只读取 `us_stocks_sip/day_aggs_v1/`；客户端层只放行 ListObjectsV2 / GetObject（见
#: `data/flatfiles.py`）。凭据（Access Key ID / Secret）只经 `op run` 注入。
MASSIVE_FLATFILES = HostEntry(
    host="files.massive.com",
    public_readonly=False,
    credentialed_readonly=True,
    exchange="massive",
    doc_url="https://massive.com/docs/flat-files/stocks/day-aggregates",
)

ALLOWLIST: tuple[HostEntry, ...] = (
    BINANCE_VISION_ARCHIVE,
    BINANCE_VISION_SPOT_MIRROR,
    MASSIVE_REST,
    MASSIVE_REST_LEGACY,
    MASSIVE_FLATFILES,
)

_BY_HOST: dict[str, HostEntry] = {entry.host: entry for entry in ALLOWLIST}


def lookup(host: str) -> HostEntry | None:
    """按 host 精确查条目；不在表内返回 `None`（不做后缀匹配，避免 `evil-binance.vision`）。"""
    return _BY_HOST.get(host)


def assert_public_readonly_host(host: str) -> HostEntry:
    """只放行 `public_readonly=True` 条目（crypto-boundaries ② 公共只读例外）。

    交易 host 传进来必须失败——两个断言互不放行（§3.3）。
    """
    entry = _BY_HOST.get(host)
    if entry is None:
        raise HostNotAllowedError(
            f"host 不在 allowlist: {host!r}（新增 host 须先走 crypto-boundaries ①）"
        )
    if not entry.public_readonly:
        kind = "需 key 的只读数据 host" if entry.credentialed_readonly else "交易 host"
        raise HostNotAllowedError(
            f"host {host!r} 是{kind}（public_readonly=False），不得用于公共只读摄取"
        )
    return entry


def assert_trading_host(host: str) -> HostEntry:
    """只放行 `public_readonly=False` 条目（ADR-0001 D1.7 交易 host 集合）。

    公共只读 host 传进来必须失败，防止摄取 host 被当作下单出口复用。
    """
    entry = _BY_HOST.get(host)
    if entry is None:
        raise TradingBoundaryError(f"host 不在 allowlist: {host!r}（ADR-0001 D1.7 fail-closed）")
    if entry.public_readonly:
        raise TradingBoundaryError(
            f"host {host!r} 是公共只读 host（public_readonly=True），不得用于交易/账户/资金请求"
        )
    if entry.credentialed_readonly:
        raise TradingBoundaryError(
            f"host {host!r} 是需 key 的只读数据 host（credentialed_readonly=True），"
            "不得用于交易/账户/资金请求（QNT-47：行情 host 不是下单出口）"
        )
    return entry


def assert_credentialed_readonly_host(host: str) -> HostEntry:
    """只放行 `credentialed_readonly=True` 条目（QNT-47：需 key 的只读数据源）。

    公共只读 host 与交易 host 传进来都必须失败——三个断言互不放行，一个 host 只属于一类。
    """
    entry = _BY_HOST.get(host)
    if entry is None:
        raise HostNotAllowedError(
            f"host 不在 allowlist: {host!r}（新增 host 须先走 crypto-boundaries ①）"
        )
    if not entry.credentialed_readonly:
        raise HostNotAllowedError(
            f"host {host!r} 不是需 key 的只读数据 host（credentialed_readonly=False），"
            "不得用于带凭据的行情摄取"
        )
    return entry


def assert_demo_headers(host: str, headers: dict[str, str], key_label: str) -> HostEntry:
    """逐请求校验 `demo_marker`（§3.3 请求层 fail-closed）。

    头缺失 / 值错误 / key 标签不符任一不满足 → `TradingBoundaryError`，请求不发出。
    `headers` 名大小写不敏感；`key_label` 按 `.strip()` 后比较（AGENTS.md §3 凭据来源）。
    """
    entry = assert_trading_host(host)
    marker = entry.demo_marker
    if marker is None:
        return entry
    if marker.header_name is not None:
        lowered = {k.lower(): v for k, v in headers.items()}
        got = lowered.get(marker.header_name.lower())
        if got is None:
            raise TradingBoundaryError(f"{host}: 缺少模拟盘请求头 {marker.header_name}")
        if got.strip() != marker.header_value:
            raise TradingBoundaryError(
                f"{host}: 模拟盘请求头 {marker.header_name} 值不符（期望 {marker.header_value!r}）"
            )
    if marker.key_label_contains is not None and marker.key_label_contains not in key_label.strip():
        raise TradingBoundaryError(
            f"{host}: 注入的 key 标签不含 {marker.key_label_contains!r}，拒绝发出请求"
        )
    return entry
