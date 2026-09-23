"""摄取 CLI（QNT-28）——**本仓库唯一出网的地方**。

网络访问被收在 `_http_opener` 一个函数里：`httpx` 只在这里 import，
其余模块（`ingest` / `sources` / `audit` / `batches`）全部拿注入的 `fetch`，
因此测试与 CI 全程离线，不需要任何网络桩。

无 key、无签名、无凭据：只 GET `core/allowlist.py` 里 `public_readonly=True` 的 host，
且路径必须在 `transport.PUBLIC_READONLY_PREFIXES` 白名单内。

子命令
------
`plan`      只打印将要请求的 URL（dry-run，不出网）
`ingest`    按 `universe.yaml` 摄取；`--rerun-of` 走 `kind='rerun'`，
            `--audit` 顺带做缺口/重复核查并把报告也经 publish 路径提交为一个 batch
`daily`     QNT-45 的无人值守入口：`--since-last` 增量 + 退避重试 + 每日核查报告；
            systemd timer 调的就是它，退出码非零即本次有失败
`backfill`  按一份核查报告补采缺口（新批次：有原 batch 的走 `kind='rerun'` + `rerun_of`，
            原序列当天整条失败的走 `kind='ingest'` + `from_report`；不动任何已发布文件）
`report-summary`  按 JSON 字段汇总某天的全部报告（汇总 unit 调它；不出网、不写文件）
`record-abort`    记一笔「运行在摄取前被拦下」（`pull_failed` / `disk_low`）：运行记录 +
                  报告（coverage=failed），退出码 1。摄取 unit 的 `ExecStopPost` 调它（R8）

数据根（R8）
------------
`--root`（缺省取环境变量 `QUANTIME_DATA_ROOT`，再缺省 `.`）接受两种写法，指向同一处：
**数据目录本身**（`…/quantime/data`，owner 统一的写法）或**它的父目录**
（含 `data/` 的那一层，QNT-28 以来的写法）。判定规则见 `resolve_root`。

`daily` / `backfill` 的逻辑全在 `daily.py`（源无关通用层），本模块只解析参数、
组装真实网络出口、打印结果。
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
from collections.abc import Sequence
from pathlib import Path

from quantime_core.ids import new_run_id
from quantime_core.paths import AssetClass, DataType, Freq

from . import audit as audit_mod
from . import daily as daily_mod
from . import ingest as ingest_mod
from .adapter import DEFAULT_SOURCE, adapter_names, get_adapter
from .retry import (
    DEFAULT_MAX_ATTEMPTS,
    DEFAULT_MAX_TOTAL_SECONDS,
    RetryPolicy,
)
from .runlog import ABORT_REASONS
from .transport import PublicTransport, Response, TransportIOError, assert_public_readonly_url
from .universe import load_universe

#: HTTP 超时（秒）。归档 zip 可以不小，给足时间但不无限等。
HTTP_TIMEOUT = 60.0

USER_AGENT = "quantime-ingest/0.0 (+https://github.com/QUANTENSOR/QUANTIME)"


def _http_opener():
    """构造默认 opener——**本仓库唯一的真实网络出口**。

    `httpx` 在函数体内 import：模块导入期不碰网络库，离线测试 import 本模块即可。
    不跟随跨 host 重定向：重定向到一个未登记的 host 会绕过 allowlist，
    所以 `follow_redirects=False`，重定向按非 200 状态处理。

    httpx 的异常**不越过这里**：`httpx.HTTPError`（`ConnectError` / `ReadTimeout` /
    `RemoteProtocolError` …）一律包成 `transport.TransportIOError`（`OSError` 子类），
    通用层据此退避重试（QNT-45 R1；契约表见 `transport` 模块头）。
    """
    import httpx

    client = httpx.Client(
        timeout=HTTP_TIMEOUT,
        follow_redirects=False,
        headers={"User-Agent": USER_AGENT},
    )

    def opener(url: str) -> Response:
        # 出口闸已在 `PublicTransport.get` 里过过一遍，这里再过一遍**httpx 自己解析后的
        # URL**：闸校验的是字符串，发出的是 httpx 规范化后的结果，二者若有差异就是一条
        # 绕过（verify-a R1 P1-2）。`transport.canonical_path` 已把歧义输入全部拒掉，
        # 所以正常情况下这一遍必然同样通过——它存在是为了让「校验的 ≠ 发送的」这件事
        # 一旦发生就在发请求**之前**炸掉，而不是靠远端拒绝。
        request = client.build_request("GET", url)
        assert_public_readonly_url(str(request.url))
        try:
            response = client.send(request)
        except httpx.HTTPError as exc:
            raise TransportIOError(f"网络层故障（{type(exc).__name__}）: {url}: {exc}") from exc
        retry_after = response.headers.get("Retry-After")
        return Response(
            status=response.status_code,
            content=response.content,
            retry_after=float(retry_after) if retry_after and retry_after.isdigit() else None,
        )

    return opener


def _fetcher(transport: PublicTransport):
    return transport.get


def _specs_for(
    universe,
    *,
    datatypes: Sequence[str],
    start: dt.date,
    end: dt.date,
    symbols: Sequence[str],
    as_of: dt.date | None = None,
) -> list[ingest_mod.IngestSpec]:
    """把清单展开成 spec 列表（顺序确定：腿 → symbol → datatype → freq）。

    `as_of` 是请求日：adapter 只列截至这天已发布的归档（R2）。`daily` 不传时由
    `run_daily` 取运行当天的 UTC 日期；`plan` 默认也取今天，与真实运行口径一致。
    """
    out: list[ingest_mod.IngestSpec] = []
    for leg in universe.legs:
        for symbol in leg.symbols:
            if symbols and symbol not in symbols:
                continue
            for name in datatypes:
                datatype = DataType(name)
                if datatype is DataType.KLINE:
                    for freq in leg.freqs:
                        out.append(
                            ingest_mod.IngestSpec(
                                datatype=datatype,
                                asset_class=leg.asset_class,
                                symbol=symbol,
                                freq=freq,
                                start=start,
                                end=end,
                                as_of=as_of,
                            )
                        )
                elif leg.asset_class is AssetClass.PERP:
                    # funding / open_interest 只在永续腿上存在；现货腿静默跳过。
                    out.append(
                        ingest_mod.IngestSpec(
                            datatype=datatype,
                            asset_class=leg.asset_class,
                            symbol=symbol,
                            freq=Freq.EVENT if datatype is DataType.FUNDING else Freq.M5,
                            start=start,
                            end=end,
                            as_of=as_of,
                        )
                    )
    return out


def _date(value: str) -> dt.date:
    return dt.date.fromisoformat(value)


#: 数据根的环境变量（systemd unit 用 `Environment=` 设它，不在 ExecStart 里重复写路径）。
DATA_ROOT_ENV = "QUANTIME_DATA_ROOT"


def resolve_root(value: str | os.PathLike[str]) -> Path:
    """把 `--root` 归一成「含 `data/` 的那一层」——包内全部路径都是 `root / "data/..."`。

    - 名字就叫 `data` 且里面**没有**再嵌一层 `data/` → 它是数据目录本身，取父目录。
      常驻布局里它是软链接也一样：取的是「父目录下名叫 data 的那一项」的父目录。
    - 其余 → 原样（它就是含 `data/` 的那一层，或者一个还没建过 `data/` 的新根）。

    这样 owner 统一的 `--root …/quantime/data` 不会写出 `data/data/...`。
    """
    path = Path(value)
    if path.name == "data" and not (path / "data").exists():
        return path.parent
    return path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="quantime-ingest",
        description="Binance 公开归档摄取（无 key、只读；QNT-28）",
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(os.environ.get(DATA_ROOT_ENV) or "."),
        help=f"数据目录本身（…/data）或含 data/ 的父目录；缺省取 ${DATA_ROOT_ENV}，再缺省 .",
    )
    parser.add_argument("--universe", type=Path, default=None, help="标的清单 YAML")
    parser.add_argument(
        "--source",
        default=DEFAULT_SOURCE,
        choices=list(adapter_names()),
        help=f"数据源 adapter（默认 {DEFAULT_SOURCE}）",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    for name in ("plan", "ingest", "daily"):
        p = sub.add_parser(name)
        if name == "daily":
            # R3：有水位线时起点只看水位线；`--start` 只是「从未取过」时的初始起点。
            p.add_argument(
                "--start",
                type=_date,
                default=None,
                help="初始起始日 YYYY-MM-DD——只在该序列尚无水位线时生效；缺省 = 与 --end 同一天",
            )
        else:
            p.add_argument("--start", type=_date, required=True, help="起始日 YYYY-MM-DD")
        p.add_argument("--end", type=_date, required=True, help="结束日 YYYY-MM-DD（含）")
        p.add_argument(
            "--as-of",
            type=_date,
            default=None,
            help="请求日 YYYY-MM-DD：只列截至这天上游已发布的归档（默认 UTC 今天）",
        )
        p.add_argument(
            "--datatype",
            action="append",
            default=None,
            choices=["kline", "funding", "open_interest"],
            help="可重复；默认全部三类",
        )
        p.add_argument("--symbol", action="append", default=None, help="可重复；默认清单全部")
        if name in ("ingest", "daily"):
            p.add_argument("--run-id", default=None, help="默认新建一个 ULID")
            p.add_argument(
                "--no-verify-checksum",
                action="store_true",
                help="跳过 .CHECKSUM 核对（不建议）",
            )
        if name == "ingest":
            p.add_argument(
                "--rerun-of",
                default=None,
                help="同参数重跑：原 batch_id，写 kind='rerun' 的新 batch",
            )
            p.add_argument(
                "--audit",
                action="store_true",
                help="摄取后做缺口/重复核查并把报告也提交为一个 batch",
            )
        if name == "daily":
            p.add_argument(
                "--since-last",
                action="store_true",
                help="增量：区间起点按已提交 ingestion_batch 的水位线推算",
            )
            _add_retry_flags(p)
            _add_disk_flag(p)

    bf = sub.add_parser("backfill")
    bf.add_argument(
        "--from-report",
        dest="from_report",
        type=Path,
        required=True,
        help="核查报告 JSON（data/reports/<date>/<run_id>.json）",
    )
    bf.add_argument("--run-id", default=None, help="默认新建一个 ULID")
    bf.add_argument(
        "--no-verify-checksum", action="store_true", help="跳过 .CHECKSUM 核对（不建议）"
    )
    bf.add_argument(
        "--dry-run", action="store_true", help="只打印补采计划，不取任何字节、不写任何文件"
    )
    _add_retry_flags(bf)
    _add_disk_flag(bf)

    ra = sub.add_parser("record-abort")
    ra.add_argument(
        "--reason",
        required=True,
        choices=list(ABORT_REASONS),
        help="拦下的原因（pull_failed = 运行前 git pull 失败；disk_low = 磁盘不足）",
    )
    ra.add_argument("--detail", default=None, help="写进报告的一句说明（可选）")
    ra.add_argument("--run-id", default=None, help="默认新建一个 ULID")

    rs = sub.add_parser("report-summary")
    rs.add_argument(
        "--date",
        type=_date,
        default=None,
        help="报告日期 YYYY-MM-DD（默认 UTC 今天）",
    )
    return parser


def _add_retry_flags(p: argparse.ArgumentParser) -> None:
    """重试预算——两个上限都可配（卡第 2 项「可配置次数上限与总时长」）。"""
    p.add_argument(
        "--retry-attempts",
        type=int,
        default=DEFAULT_MAX_ATTEMPTS,
        help=f"单个归档的最大尝试次数（含首次，默认 {DEFAULT_MAX_ATTEMPTS}）",
    )
    p.add_argument(
        "--retry-max-seconds",
        type=float,
        default=DEFAULT_MAX_TOTAL_SECONDS,
        help=f"本次运行的重试墙钟预算（秒，默认 {DEFAULT_MAX_TOTAL_SECONDS:g}）",
    )


def _add_disk_flag(p: argparse.ArgumentParser) -> None:
    """磁盘守卫阈值（R8）：数据根所在文件系统剩余低于它就不开新 batch。0 = 关闭。"""
    p.add_argument(
        "--min-free-gb",
        type=float,
        default=daily_mod.DEFAULT_MIN_FREE_BYTES / 1024**3,
        help="数据根所在文件系统的最低剩余空间（GB，默认 5；0 关闭守卫）",
    )


def _min_free_bytes(args) -> int | None:
    return int(args.min_free_gb * 1024**3) if args.min_free_gb > 0 else None


def _retry_policy(args) -> RetryPolicy:
    return RetryPolicy(max_attempts=args.retry_attempts, max_total_seconds=args.retry_max_seconds)


def _today() -> dt.date:
    return dt.datetime.now(dt.UTC).date()


def _run_plan(args) -> int:
    universe = load_universe(args.universe)
    specs = _specs_for(
        universe,
        datatypes=args.datatype or ["kline", "funding", "open_interest"],
        start=args.start,
        end=args.end,
        symbols=args.symbol or [],
        as_of=args.as_of or _today(),
    )
    adapter = get_adapter(getattr(args, "source", DEFAULT_SOURCE))
    for spec in specs:
        for url, _ in ingest_mod.plan_urls(spec, adapter):
            print(url)
    print(f"# {len(specs)} spec(s)", file=sys.stderr)
    return 0


def _run_ingest(args) -> int:
    universe = load_universe(args.universe)
    specs = _specs_for(
        universe,
        datatypes=args.datatype or ["kline", "funding", "open_interest"],
        start=args.start,
        end=args.end,
        symbols=args.symbol or [],
        as_of=args.as_of or _today(),
    )
    run_id = args.run_id or new_run_id()
    adapter = get_adapter(getattr(args, "source", DEFAULT_SOURCE))
    transport = PublicTransport(_http_opener())
    fetch = _fetcher(transport)

    results: list[ingest_mod.IngestResult] = []
    audits: list[audit_mod.AuditResult] = []
    failures: list[str] = []
    for spec in specs:
        try:
            result = ingest_mod.ingest_one(
                args.root,
                spec,
                fetch,
                run_id=run_id,
                kind="rerun" if args.rerun_of else "ingest",
                rerun_of=args.rerun_of,
                verify_checksum=not args.no_verify_checksum,
                adapter=adapter,
            )
        except ingest_mod.IngestError as exc:
            failures.append(f"{spec.describe()}: {exc}")
            continue
        results.append(result)
        print(
            json.dumps(
                {
                    "spec": spec.describe(),
                    "batch_id": result.committed.batch_id,
                    "rows": result.committed.row_count,
                    "content_sha256": result.committed.content_sha256,
                    "batch_dir": result.committed.batch_dir,
                    "missing_upstream": list(result.missing),
                },
                ensure_ascii=False,
            )
        )
        if args.audit:
            audits.append(ingest_mod.audit_result(args.root, result, adapter))

    if audits:
        report = ingest_mod.commit_audit_report(
            args.root,
            audits,
            run_id=run_id,
            scope="universe",
            datatype=DataType.KLINE,
            freq=Freq.D1,
            asset_class=AssetClass.SPOT,
            adapter=adapter,
        )
        print(
            json.dumps(
                {
                    "audit_report_batch_id": report.batch_id,
                    "rows": report.row_count,
                    "content_sha256": report.content_sha256,
                    "batch_dir": report.batch_dir,
                },
                ensure_ascii=False,
            )
        )

    for f in failures:
        print(f"FAILED {f}", file=sys.stderr)
    print(f"# run_id={run_id} ok={len(results)} failed={len(failures)}", file=sys.stderr)
    return 1 if failures and not results else 0


def _run_daily(args) -> int:
    """无人值守入口——systemd timer 调的就是它（unit 只给 `--end`，起点由水位线决定）。"""
    universe = load_universe(args.universe)
    specs = _specs_for(
        universe,
        datatypes=args.datatype or ["kline", "funding", "open_interest"],
        start=args.start or args.end,
        end=args.end,
        symbols=args.symbol or [],
        as_of=args.as_of,
    )
    run_id = args.run_id or new_run_id()
    adapter = get_adapter(args.source)
    fetch = _fetcher(PublicTransport(_http_opener()))
    out = daily_mod.run_daily(
        args.root,
        specs,
        fetch,
        run_id=run_id,
        adapter=adapter,
        since_last=args.since_last,
        verify_checksum=not args.no_verify_checksum,
        retry_policy=_retry_policy(args),
        min_free_bytes=_min_free_bytes(args),
    )
    _print_run(args.root, out)
    return out.exit_code


def _run_record_abort(args) -> int:
    """systemd `ExecStopPost` 调它：运行前的 `git pull --ff-only` 失败时留一笔可查的记录。"""
    out = daily_mod.record_abort(
        args.root,
        args.reason,
        run_id=args.run_id or new_run_id(),
        source=args.source,
        detail=args.detail,
    )
    _print_run(args.root, out)
    return out.exit_code


def _run_backfill(args) -> int:
    """按报告补采缺口。`--dry-run` 只列计划，不取字节、不写文件。"""
    adapter = get_adapter(args.source)
    if args.dry_run:
        from . import backfill as backfill_mod

        plan = backfill_mod.plan_backfill(args.from_report, adapter=adapter)
        for task in plan.tasks:
            print(task.describe())
        for skip in plan.skipped:
            print(f"# 跳过（上游确实缺失）: {skip.filename} —— {skip.reason}", file=sys.stderr)
        print(f"# {plan.describe()}", file=sys.stderr)
        return 0

    run_id = args.run_id or new_run_id()
    fetch = _fetcher(PublicTransport(_http_opener()))
    out = daily_mod.run_backfill_from_report(
        args.root,
        args.from_report,
        fetch,
        run_id=run_id,
        adapter=adapter,
        verify_checksum=not args.no_verify_checksum,
        retry_policy=_retry_policy(args),
        min_free_bytes=_min_free_bytes(args),
    )
    _print_run(args.root, out)
    return out.exit_code


def _print_run(root: Path, out: daily_mod.RunOutput) -> None:
    """一行 JSON 汇总到 stdout，明细到 stderr（journald 里一眼可读）。

    `report_json` 是报告文件的路径、`report_sha256` 是它的内容 hash（此前 `report_json`
    误填成了 hash，R7 端到端测试按路径读报告时暴露）。
    """
    from .report import report_paths

    published = out.report_paths is not None
    print(
        json.dumps(
            {
                "run_id": out.run_id,
                "mode": out.log.mode,
                "abort_reason": out.log.abort_reason,
                "outcome": out.log.outcome,
                "coverage": out.report.coverage,
                "series": len(out.log.series),
                "ok": out.log.ok_count,
                "failed": out.log.failed_count,
                "skipped_empty_increment": out.log.skipped_count,
                "failed_series": out.report.count("failed"),
                "pending_series": out.report.count("pending"),
                "rows": out.log.total_rows,
                "retries": out.log.total_retries,
                "report_json": str(report_paths(root, out.report)[0]) if published else None,
                "report_sha256": out.report_paths[0] if published else None,
            },
            ensure_ascii=False,
        )
    )
    for line in out.increments:
        print(f"# {line}", file=sys.stderr)
    for line in out.log.notes:
        print(f"# note {line}", file=sys.stderr)
    for line in out.retry_log:
        print(f"# retry {line}", file=sys.stderr)
    for failure in out.report.failures:
        print(f"FAILED {failure}", file=sys.stderr)


def _run_report_summary(args) -> int:
    from .report import summarize_reports

    lines, code = summarize_reports(args.root, args.date or _today())
    for line in lines:
        print(line)
    return code


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    args.root = resolve_root(args.root)
    if args.command == "report-summary":
        return _run_report_summary(args)
    if args.command == "plan":
        return _run_plan(args)
    if args.command == "ingest":
        return _run_ingest(args)
    if args.command == "daily":
        return _run_daily(args)
    if args.command == "backfill":
        return _run_backfill(args)
    if args.command == "record-abort":
        return _run_record_abort(args)
    raise AssertionError(f"未处理的子命令: {args.command}")  # pragma: no cover


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
