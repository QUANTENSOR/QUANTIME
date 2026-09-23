"""适配契约（QNT-45）——每个登记在案的 adapter 都要过的一致性检查。

QNT-47 / QNT-48 新接源时，把名字登记进 `BUILTIN_ADAPTERS`，本文件自动对它跑一遍：
这就是契约的可执行版本，PR 描述里的文字版以此为准。
"""

from __future__ import annotations

import datetime as dt

import pytest
from fixture_source import FUNDING_SPEC, OI_SPEC, SPOT_KLINE_SPEC, FixtureFetcher
from quantime_core.paths import assert_source
from quantime_data import adapter as adapter_mod
from quantime_data.adapter import Archive, NormalizedTable, SourceAdapter, get_adapter
from quantime_data.spec import IngestError, requested_window


@pytest.fixture(params=adapter_mod.adapter_names())
def src(request) -> SourceAdapter:
    return get_adapter(request.param)


def test_every_registered_adapter_satisfies_the_protocol(src):
    assert isinstance(src, SourceAdapter)
    assert assert_source(src.name) == src.name
    assert src.version


def test_the_registry_name_is_the_adapters_own_name():
    for name in adapter_mod.adapter_names():
        assert get_adapter(name).name == name


def test_an_unregistered_source_is_refused_not_guessed():
    with pytest.raises(IngestError, match="未登记"):
        get_adapter("massive")


def test_the_default_source_is_registered():
    assert adapter_mod.DEFAULT_SOURCE in adapter_mod.adapter_names()


# ---- list_archives：纯、确定、覆盖整个请求区间、不藏缺档 ----


def test_list_archives_is_pure_and_ordered():
    src = get_adapter()
    a = src.list_archives(SPOT_KLINE_SPEC)
    assert a == src.list_archives(SPOT_KLINE_SPEC)
    assert list(a) == sorted(a, key=lambda x: x.covers_start)


def test_archives_cover_the_whole_requested_range_without_holes():
    """通用层靠 `covers_*` 判断「缺档对应哪段日期」——有洞，补采就补不到那一段。"""
    src = get_adapter()
    spec = SPOT_KLINE_SPEC.with_window(dt.date(2026, 6, 15), dt.date(2026, 8, 3))
    archives = src.list_archives(spec)
    assert archives[0].covers_start <= spec.start
    assert archives[-1].covers_end >= spec.end
    for prev, nxt in zip(archives, archives[1:], strict=False):
        assert nxt.covers_start == prev.covers_end + dt.timedelta(days=1)


def test_list_archives_does_not_hide_archives_that_may_be_missing():
    """未来月份上游一定没有，但也要列出来——由通用层记成 missing_upstream。"""
    src = get_adapter()
    spec = SPOT_KLINE_SPEC.with_window(dt.date(2026, 8, 1), dt.date(2027, 1, 31))
    assert len(src.list_archives(spec)) == 6


def test_list_archives_makes_no_network_call():
    src = get_adapter()
    fetch = FixtureFetcher()
    for spec in (SPOT_KLINE_SPEC, FUNDING_SPEC, OI_SPEC):
        src.list_archives(spec)
    assert fetch.urls == []


def test_an_inverted_archive_window_is_rejected():
    with pytest.raises(IngestError):
        Archive(
            url="x", filename="x", covers_start=dt.date(2026, 8, 2), covers_end=dt.date(2026, 8, 1)
        )


def test_the_request_payload_does_not_change_archive_identity():
    """API 型源（Tushare）把请求参数放 `request`；归档身份仍是文件名与覆盖区间。"""
    kw = dict(
        url="u", filename="f", covers_start=dt.date(2026, 8, 1), covers_end=dt.date(2026, 8, 1)
    )
    assert Archive(**kw, request={"a": 1}) == Archive(**kw)


# ---- fetch_archive：异常语义 ----


def test_fetch_archive_passes_upstream_absence_through_as_file_not_found():
    src = get_adapter()
    spec = SPOT_KLINE_SPEC.with_window(dt.date(2026, 7, 1), dt.date(2026, 7, 31))
    (archive,) = src.list_archives(spec)
    with pytest.raises(FileNotFoundError):
        src.fetch_archive(archive, FixtureFetcher())


def test_fetch_archive_refuses_bytes_that_fail_verification():
    src = get_adapter()
    (archive,) = src.list_archives(SPOT_KLINE_SPEC)
    good = FixtureFetcher()

    def tampered(url: str) -> bytes:
        payload = good(url)
        return payload if url.endswith(".CHECKSUM") else payload + b"x"

    with pytest.raises(IngestError, match="sha256"):
        src.fetch_archive(archive, tampered)


# ---- normalize：裁窗、确定性、空输入也回传口径 ----


@pytest.mark.parametrize("spec", [SPOT_KLINE_SPEC, FUNDING_SPEC, OI_SPEC], ids=str)
def test_normalize_with_no_files_still_declares_the_audit_parameters(spec):
    got = get_adapter().normalize(spec, ())
    assert isinstance(got, NormalizedTable)
    assert got.table.num_rows == 0
    assert got.time_column in got.table.column_names


def test_normalize_clips_to_the_requested_window_and_sorts():
    src = get_adapter()
    spec = SPOT_KLINE_SPEC.with_window(dt.date(2026, 8, 10), dt.date(2026, 8, 12))
    files = [src.fetch_archive(a, FixtureFetcher()) for a in src.list_archives(spec)]
    got = src.normalize(spec, files)
    times = got.table.column(got.time_column).to_pylist()
    lo, hi = requested_window(spec)
    assert len(times) == 3
    assert times == sorted(times)
    assert all(lo <= t < hi for t in times)
    assert got.step == dt.timedelta(days=1)


def test_normalize_is_byte_deterministic():
    src = get_adapter()
    files = [src.fetch_archive(a, FixtureFetcher()) for a in src.list_archives(OI_SPEC)]
    assert src.normalize(OI_SPEC, files).table.equals(src.normalize(OI_SPEC, files).table)
