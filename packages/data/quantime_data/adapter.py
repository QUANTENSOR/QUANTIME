"""数据源适配契约（QNT-45）——通用层与 adapter 之间**唯一**的接缝。

QNT-28 把「拼 Binance 的 URL」和「怎么增量、怎么重试、怎么核查」焊在了一起。
QNT-47（Massive 美股 + 期权）与 QNT-48（Tushare Pro A 股）要复用后者，所以前者被收进
一个**三个必需方法 + 一个可选方法**的协议：

    list_archives(spec)                     列出截至 spec.as_of 已发布的归档 / 区间
    fetch_archive(archive, fetch, ...)      拉取（含本源自己的完整性校验）
    normalize(spec, files)                  归一化成 Arrow 表（并声明时间列与步长）
    pending_windows(spec)   （可选）         按发布节奏尚未发布的区间（pending_upstream）

增量推算、失败重试、缺口补采、每日核查、systemd 模板**全部在通用层**，adapter 一行都不写。
adapter 也不自建网络出口：出口对象由 CLI 组装后注入（公开源是 `transport.PublicTransport`
的 `url -> bytes`；需凭据的源如 QNT-48 Tushare 是 `transport.CredentialedTransport`），
通用层**原样透传、从不调用**它——只有 adapter 的 `fetch_archive` 知道它长什么样。
所以适配层在测试里天然离线，通用层也不需要知道一个源是 GET 还是 POST、有没有 token。

「实现协议」不等于「CLI 能跑这个源」。今天 CLI 的组装是写死给公开源的：
`--source` 查 `BUILTIN_ADAPTERS` 取 adapter；出口一律 `PublicTransport(_http_opener())`，
把 `transport.get` 当 `fetch` 传进通用层；spec 由 `_specs_for` 按 `universe.yaml` 的
spot / perp 腿展开，`as_of` 为请求日。接一个新源因此还要：在 `BUILTIN_ADAPTERS` 登记；
若它不是公开 GET 源，在 CLI 里按源组装它的出口（如 `CredentialedTransport`）；若它的标的
不是 spot / perp 腿，扩展清单与 `_specs_for`。这三处都在 CLI / 清单层，通用层仍不改。

契约细则见 `SourceAdapter` 的 docstring——新接一个源时那段就是验收清单。
"""

from __future__ import annotations

import datetime as dt
import importlib
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

import pyarrow as pa
from quantime_core.paths import Market

from .spec import FetchedFile, Fetcher, IngestError, IngestSpec


@dataclass(frozen=True, slots=True)
class Archive:
    """上游一个可取的归档单元（一个 zip / 一次 API 调用的产物）。

    `covers_start` / `covers_end` 是这个归档**声称覆盖**的闭区间日期。通用层靠它做两件
    事，两件都不需要知道上游长什么样：

    * 增量——水位线之后的归档才取（`covers_end < 水位` 的整档跳过）；
    * 补采——核查报告里只有文件名，靠它把文件名映射回一段日期区间。

    所以覆盖区间必须由 adapter 给出：只有它知道「月归档」还是「日归档」。
    """

    url: str
    filename: str
    covers_start: dt.date
    covers_end: dt.date
    #: adapter 自定义的请求参数（通用层不读、不改、只透传回 `fetch_archive`）。
    #: 按文件下载的源（Binance Vision）为 `None`；按 API 调用取数的源（Tushare 的
    #: `TushareRequest(api_name, params, fields)`）放在这里。不参与相等/哈希比较：
    #: 归档的身份是 `filename`，不是请求体。
    request: Any = field(default=None, compare=False, hash=False)

    def __post_init__(self) -> None:
        if self.covers_end < self.covers_start:
            raise IngestError(
                f"归档覆盖区间非法: {self.filename} {self.covers_start}..{self.covers_end}"
            )

    def overlaps(self, start: dt.date, end: dt.date) -> bool:
        return self.covers_start <= end and self.covers_end >= start


@dataclass(frozen=True, slots=True)
class NormalizedTable:
    """归一化结果 = 表 + **核查口径**。

    `time_column` 与 `step` 跟表一起回传，而不是让通用层再问 adapter 第四个问题：
    缺口检测要知道按哪一列、以多长的步长看等距。`step=None` = 该序列本就不等距
    （如 funding，间隔由上游逐行给出），通用层据此跳过等距检查而不是假设一个步长。
    """

    table: pa.Table
    time_column: str
    step: dt.timedelta | None


@runtime_checkable
class SourceAdapter(Protocol):
    """一个数据源要接进 quantime，需要且只需要实现的东西。

    属性
    ----
    `name`
        `source` 列与 `data/raw/<source>/` 的分量，小写 snake（`paths.assert_source`）。
    `version`
        `source_version` 列。上游没有版本号时，用「本适配器的解析口径」版本，改解析即升版。
    `market`
        本源数据所属市场（`crypto` / `us` / `cn` …）——写进 lake 路径。

    方法
    ----
    `list_archives(spec)`
        纯函数：不出网、不落盘、同样输入同样输出（顺序也相同）。区间内上游**截至
        `spec.as_of` 已发布**的归档全列出来，不要因为"可能不存在"就省略——整档缺失由
        通用层记成 `missing_upstream`，adapter 提前藏起来会让覆盖状态谎报 `complete`。
        只有「按发布节奏尚未发布」这一种理由可以不列：那段日子交给 `pending_windows`。
        同一天不得同时被两个归档覆盖（例如月档与日档重叠），否则行会重复入湖。
    `pending_windows(spec)`（可选）
        请求区间里**上游按发布节奏尚未发布**的日期段（闭区间 `(start, end)` 列表）。
        通用层把它们记成 `pending_upstream`：不是缺失、不是失败、不进覆盖率分母，
        下一次 `--since-last` 自然会补上（水位线不越过它们）。没有发布延迟的源不必实现。
    `fetch_archive(archive, fetch, *, verify_checksum=True)`
        用注入的 `fetch` 取字节并做本源的完整性校验（校验方式各源不同，故留在 adapter）。
        `fetch` 对通用层是**不透明句柄**：公开源是 `url -> bytes`，需凭据的源是持 token 的
        transport 对象（token 从不经过通用层）。回传的 `FetchedFile.payload` 必须是可落盘
        重放的字节——API 型源把响应按确定性方式序列化（如 `json.dumps(sort_keys=True)`）。
        异常语义决定通用层怎么处置，**这是契约里最容易写错的一条**（公开源的出口
        `PublicTransport` 已按此分流，见 `transport` 模块头的契约表）：

        * 上游确实没有这个归档（HTTP 404）→ `FileNotFoundError`（不是错误，是覆盖不全，
          记账、不重试）；
        * 校验不过 / 上游明确拒绝（401/403/410 等其余 4xx、参数错、配额永久用尽）→
          `IngestError`（不重试，字节不许进湖）；
        * 限流与服务端错误（418/429/5xx）→ `RateLimitedError`（通用层退避重试）；
        * 网络层故障（连接失败、超时、协议错误）→ `OSError` 子类
          （`transport.TransportIOError`；通用层退避重试）。底层 HTTP 客户端的异常类型
          **不得越过出口**——opener 负责包装（`cli._http_opener` 包 `httpx.HTTPError`）。

        transport 自己已有内层退避的源，内层用尽后抛 `RateLimitedError` 即可，外层预算照样
        生效；但**非暂时性**错误不得以 `RateLimitedError` 抛出，否则通用层会对一个注定失败
        的请求白白退避。
    `normalize(spec, files)`
        把取回的字节归一化成一张表，**并裁到 `spec` 的请求区间**（`spec.clip_to_window`）。
        行序必须确定（按时间列升序），否则确定性 writer 的字节会随上游行序漂移。
        `files` 为空时**仍须回传**该 spec 的空表 + 时间列 + 步长：通用层用
        `normalize(spec, ())` 在不取任何字节的情况下问出核查口径。
    """

    name: str
    version: str
    market: Market

    def list_archives(self, spec: IngestSpec) -> tuple[Archive, ...]: ...

    def fetch_archive(
        self, archive: Archive, fetch: Fetcher | Any, *, verify_checksum: bool = True
    ) -> FetchedFile: ...

    def normalize(self, spec: IngestSpec, files: Sequence[FetchedFile]) -> NormalizedTable: ...


#: 内置 adapter：`source` 名 → 实现模块。模块里必须有一个名为 `ADAPTER` 的实例。
#: 用「名字 → 模块路径」而不是直接 import：`adapter.py` 不依赖任何具体源，
#: 反向依赖（源 import 契约）才是单向的。
BUILTIN_ADAPTERS: dict[str, str] = {
    "binance_vision": "quantime_data.sources.binance_public",
}

#: 默认源——CLI 不指定 `--source` 时用它（QNT-45 只接了这一个源）。
DEFAULT_SOURCE = "binance_vision"


def adapter_names() -> tuple[str, ...]:
    return tuple(sorted(BUILTIN_ADAPTERS))


def get_adapter(name: str = DEFAULT_SOURCE) -> SourceAdapter:
    """按 `source` 名取 adapter 实例。未登记的名字立刻报错，不做任何猜测式回退。"""
    try:
        module_path = BUILTIN_ADAPTERS[name]
    except KeyError:
        raise IngestError(
            f"未登记的数据源 {name!r}（已登记: {', '.join(adapter_names())}）"
        ) from None
    module = importlib.import_module(module_path)
    adapter = getattr(module, "ADAPTER", None)
    if adapter is None:
        raise IngestError(f"{module_path} 没有导出 ADAPTER 实例")
    return adapter
