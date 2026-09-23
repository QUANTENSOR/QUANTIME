"""Host allowlist：纯数据 + 纯函数（ADR-0003 §3.3；owner 5A 已批准 §9.10 迁移）。

本文件是**唯一**允许出现 `public_readonly=True` host 字面量的文件，且不得 import 任何
网络客户端（import-linter 守卫）。`.claude/rules/crypto-boundaries.md` ①② 的路径与字段名
回写由 QNT-39 单独 PR 完成（owner 5A 裁决：与 ADR「同一 PR」表述的偏离已建卡）。

字段名沿用 rules 原文 `public_readonly=true/false`，不引入 `kind` 枚举（§3.3）。
`public_readonly=False` **且** `credentialed_readonly=False` 的条目才是 ADR-0001 D1.7 交易
host 集合；`credentialed_readonly=True` 是 QNT-48 加的第三类——需 token 的只读数据源
（Tushare Pro），三个 `assert_*_host` 互不放行。

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

    `credentialed_readonly=True` 标出**第三类** host：需要凭据、但只提供只读行情/参考数据，
    既不是 `public_readonly=True` 的无 key 公共源，也不属于 ADR-0001 D1.7 的交易 host 集合
    （QNT-48 / Tushare Pro）。原字段只有 `public_readonly` 一个布尔，`False` 等同「交易 host」；
    若照此把需 key 的数据源登记成 `public_readonly=False`，`assert_trading_host` 就会把它
    当成合法下单出口——所以这一维是**独立**的，且 `assert_trading_host` 显式拒绝它。
    `exchange` 对数据源读作「数据源标识」（Tushare 不是交易所）。
    """

    host: str
    public_readonly: bool
    exchange: str
    doc_url: str
    demo_marker: DemoMarker | None = None
    credentialed_readonly: bool = False

    def __post_init__(self) -> None:
        if self.public_readonly and self.credentialed_readonly:
            raise ValueError(
                f"{self.host}: public_readonly 与 credentialed_readonly 互斥"
                "（无 key 的公共源不需要凭据）"
            )


# 第一版只含公共只读归档/镜像 host（ADR-0003 §7、§9.5）。刻意不收 api.binance.com /
# fapi.binance.com：本机所在美国节点访问二者返回 451（§9.5 原始裁决，QNT-28 2026-09-21
# 复测仍为 451）。交易 host（`public_readonly=False`）条目由 QNT-33 paper 交易卡加入。

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

#: Tushare Pro HTTP API（QNT-48）——A 股日线 / 复权因子 / 每日指标 / 交易日历 / 股票列表。
#: 需 token（POST body，`op://quant-dev/Tushare/credential` 注入），故 `public_readonly=False`；
#: 但它只提供只读数据、无任何下单/账户/资金端点，所以 `credentialed_readonly=True`，
#: `assert_trading_host` 对它 fail-closed。
TUSHARE_PRO_API = HostEntry(
    host="api.tushare.pro",
    public_readonly=False,
    exchange="tushare",
    doc_url="https://tushare.pro/document/1?doc_id=130",
    credentialed_readonly=True,
)

ALLOWLIST: tuple[HostEntry, ...] = (
    BINANCE_VISION_ARCHIVE,
    BINANCE_VISION_SPOT_MIRROR,
    TUSHARE_PRO_API,
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
        raise HostNotAllowedError(
            f"host {host!r} 是交易 host（public_readonly=False），不得用于公共只读摄取"
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
            f"host {host!r} 是需凭据的**只读数据源**（credentialed_readonly=True），"
            "不得用于交易/账户/资金请求"
        )
    return entry


def assert_credentialed_readonly_host(host: str) -> HostEntry:
    """只放行 `credentialed_readonly=True` 条目（需 token 的只读数据源，QNT-48）。

    与另外两个断言同样**互不放行**：公共只读 host 与交易 host 传进来都必须失败，
    否则「带凭据的出口」就能被复用去打无 key 源或下单 host。
    """
    entry = _BY_HOST.get(host)
    if entry is None:
        raise HostNotAllowedError(
            f"host 不在 allowlist: {host!r}（新增 host 须先走 crypto-boundaries ①）"
        )
    if not entry.credentialed_readonly:
        raise HostNotAllowedError(
            f"host {host!r} 不是需凭据的只读数据源（credentialed_readonly=False），"
            "不得用于带 token 的数据请求"
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
