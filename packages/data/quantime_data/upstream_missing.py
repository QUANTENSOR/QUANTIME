"""「上游确实缺失」白名单（QNT-45 第 3 项）——版本控制的、不再重试的豁免表。

补采的默认动作是「报告里 `missing_upstream` 的都再试一次」。但有些归档上游**永远**不会
出现（标的上市前的月份、某源某段历史就是没有）。这类文件每天重试一次，代价不是流量，
是报告永远停在 `partial`——真正的缺口从此淹没在噪声里。

所以豁免必须存在，但必须是**被审过的结论**：条目在 `upstream_missing.yaml` 里，改动走 PR，
每条带人工核对依据与日期。不支持通配符——一条豁免只对一个文件生效。
"""

from __future__ import annotations

import datetime as dt
import os
from dataclasses import dataclass
from pathlib import Path

import yaml

#: 随包分发的白名单。
DEFAULT_WHITELIST_PATH = Path(__file__).with_name("upstream_missing.yaml")


class WhitelistError(ValueError):
    """白名单文件不合规范。"""


@dataclass(frozen=True, slots=True)
class MissingEntry:
    """一条豁免：某源的某个精确文件名，上游确实没有。"""

    source: str
    filename: str
    reason: str
    verified_on: dt.date

    @property
    def key(self) -> tuple[str, str]:
        return (self.source, self.filename)


@dataclass(frozen=True, slots=True)
class UpstreamMissing:
    version: int
    entries: tuple[MissingEntry, ...]

    def __contains__(self, key: object) -> bool:
        return key in {e.key for e in self.entries}

    def is_known_missing(self, source: str, filename: str) -> bool:
        """这个文件是否已被判定为上游确实缺失（因而不再重试）。"""
        return (source, filename) in self

    def reason_for(self, source: str, filename: str) -> str | None:
        for e in self.entries:
            if e.key == (source, filename):
                return e.reason
        return None


def load_upstream_missing(path: str | os.PathLike[str] | None = None) -> UpstreamMissing:
    """读白名单。字段缺失、通配符、日期不合法一律拒绝——放行表写错就是直接放行。"""
    p = Path(path) if path is not None else DEFAULT_WHITELIST_PATH
    raw = yaml.safe_load(p.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise WhitelistError(f"白名单根节点应为映射: {p}")
    try:
        version = int(raw["version"])
    except (KeyError, TypeError, ValueError) as exc:
        raise WhitelistError(f"白名单缺少合法的 version: {p}") from exc

    raw_entries = raw.get("entries") or []
    if not isinstance(raw_entries, list):
        raise WhitelistError(f"entries 应为列表: {p}")

    entries: list[MissingEntry] = []
    seen: set[tuple[str, str]] = set()
    for item in raw_entries:
        if not isinstance(item, dict):
            raise WhitelistError(f"entries 的每一项应为映射: {item!r}")
        missing = [k for k in ("source", "filename", "reason", "verified_on") if k not in item]
        if missing:
            raise WhitelistError(f"白名单条目缺字段 {missing}: {item!r}")
        source, filename = str(item["source"]), str(item["filename"])
        if "*" in filename or "?" in filename:
            raise WhitelistError(f"白名单不支持通配符（一条豁免只对一个文件生效）: {filename!r}")
        reason = str(item["reason"]).strip()
        if not reason:
            raise WhitelistError(f"白名单条目必须写明核对依据: {item!r}")
        verified = item["verified_on"]
        verified_on = (
            verified if isinstance(verified, dt.date) else dt.date.fromisoformat(str(verified))
        )
        key = (source, filename)
        if key in seen:
            raise WhitelistError(f"白名单条目重复: {key}")
        seen.add(key)
        entries.append(
            MissingEntry(source=source, filename=filename, reason=reason, verified_on=verified_on)
        )
    return UpstreamMissing(version=version, entries=tuple(entries))
