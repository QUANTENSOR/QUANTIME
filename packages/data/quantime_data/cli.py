"""摄取 CLI（QNT-28）——**本仓库唯一出网的地方**。

网络访问被收在 `_http_opener` 一个函数里：`httpx` 只在这里 import，
其余模块（`ingest` / `sources` / `audit` / `batches`）全部拿注入的 `fetch`，
因此测试与 CI 全程离线，不需要任何网络桩。

无 key、无签名、无凭据：只 GET `core/allowlist.py` 里 `public_readonly=True` 的 host，
且路径必须在 `transport.PUBLIC_READONLY_PREFIXES` 白名单内。

子命令
------
`plan`    只打印将要请求的 URL（dry-run，不出网）
`ingest`  按 `universe.yaml` 摄取；`--rerun-of` 走 `kind='rerun'`，
          `--audit` 顺带做缺口/重复核查并把报告也经 publish 路径提交为一个 batch
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from quantime_core.ids import new_run_id
from quantime_core.paths import AssetClass, DataType, Freq

from . import audit as audit_mod
from . import ingest as ingest_mod
from .transport import PublicTransport, Response, assert_public_readonly_url
from .universe import load_universe

#: HTTP 超时（秒）。归档 zip 可以不小，给足时间但不无限等。
HTTP_TIMEOUT = 60.0

USER_AGENT = "quantime-ingest/0.0 (+https://github.com/QUANTENSOR/QUANTIME)"


def _http_opener():
    """构造默认 opener——**本仓库唯一的真实网络出口**。

    `httpx` 在函数体内 import：模块导入期不碰网络库，离线测试 import 本模块即可。
    不跟随跨 host 重定向：重定向到一个未登记的 host 会绕过 allowlist，
    所以 `follow_redirects=False`，重定向按非 200 状态处理。
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
        response = client.send(request)
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
    universe, *, datatypes: Sequence[str], start: dt.date, end: dt.date, symbols: Sequence[str]
) -> list[ingest_mod.IngestSpec]:
    """把清单展开成 spec 列表（顺序确定：腿 → symbol → datatype → freq）。"""
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
                        )
                    )
    return out


def _date(value: str) -> dt.date:
    return dt.date.fromisoformat(value)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="quantime-ingest",
        description="Binance 公开归档摄取（无 key、只读；QNT-28）",
    )
    parser.add_argument("--root", type=Path, default=Path("."), help="数据根目录（含 data/）")
    parser.add_argument("--universe", type=Path, default=None, help="标的清单 YAML")
    sub = parser.add_subparsers(dest="command", required=True)

    for name in ("plan", "ingest"):
        p = sub.add_parser(name)
        p.add_argument("--start", type=_date, required=True, help="起始日 YYYY-MM-DD")
        p.add_argument("--end", type=_date, required=True, help="结束日 YYYY-MM-DD（含）")
        p.add_argument(
            "--datatype",
            action="append",
            default=None,
            choices=["kline", "funding", "open_interest"],
            help="可重复；默认全部三类",
        )
        p.add_argument("--symbol", action="append", default=None, help="可重复；默认清单全部")
        if name == "ingest":
            p.add_argument("--run-id", default=None, help="默认新建一个 ULID")
            p.add_argument(
                "--rerun-of",
                default=None,
                help="同参数重跑：原 batch_id，写 kind='rerun' 的新 batch",
            )
            p.add_argument(
                "--no-verify-checksum",
                action="store_true",
                help="跳过 .CHECKSUM 核对（不建议）",
            )
            p.add_argument(
                "--audit",
                action="store_true",
                help="摄取后做缺口/重复核查并把报告也提交为一个 batch",
            )
    return parser


def _run_plan(args) -> int:
    universe = load_universe(args.universe)
    specs = _specs_for(
        universe,
        datatypes=args.datatype or ["kline", "funding", "open_interest"],
        start=args.start,
        end=args.end,
        symbols=args.symbol or [],
    )
    for spec in specs:
        for url, _ in ingest_mod.plan_urls(spec):
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
    )
    run_id = args.run_id or new_run_id()
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
            audits.append(ingest_mod.audit_result(args.root, result))

    if audits:
        report = ingest_mod.commit_audit_report(
            args.root,
            audits,
            run_id=run_id,
            scope="universe",
            datatype=DataType.KLINE,
            freq=Freq.D1,
            asset_class=AssetClass.SPOT,
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


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "plan":
        return _run_plan(args)
    if args.command == "ingest":
        return _run_ingest(args)
    raise AssertionError(f"未处理的子命令: {args.command}")  # pragma: no cover


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
