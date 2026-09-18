"""Run every probe in this directory, collect `PROBE {json}` lines, write results.

Usage:
    python run_all.py                 # run all *_*.py probes (skips _common / run_all)
    python run_all.py cex_public_crypto akshare_cn_equity   # subset

Outputs (in this directory, git-tracked so verify-c can diff a fresh run):
    results.jsonl   — one PROBE record per line, plus run metadata
    results.md      — human-readable table grouped by probe file
Exit code 0 always; the pass/fail counts are in the summary line.
"""
from __future__ import annotations

import datetime as dt
import json
import pathlib
import platform
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
PER_FILE_TIMEOUT = 600


def discover(argv: list[str]) -> list[pathlib.Path]:
    if argv:
        return [HERE / (a if a.endswith(".py") else a + ".py") for a in argv]
    return sorted(p for p in HERE.glob("*.py") if not p.name.startswith("_") and p.name != "run_all.py")


def run_probe(path: pathlib.Path) -> tuple[list[dict], str]:
    t0 = dt.datetime.now(dt.timezone.utc)
    try:
        proc = subprocess.run([sys.executable, str(path)], capture_output=True, text=True, timeout=PER_FILE_TIMEOUT, cwd=HERE)
        stdout, stderr, rc = proc.stdout, proc.stderr, proc.returncode
    except subprocess.TimeoutExpired as exc:
        stdout, stderr, rc = (exc.stdout or ""), f"TIMEOUT after {PER_FILE_TIMEOUT}s", -1
    recs = []
    for line in stdout.splitlines():
        if line.startswith("PROBE "):
            try:
                rec = json.loads(line[6:])
            except json.JSONDecodeError:
                continue
            rec["probe_file"] = path.name
            rec["run_at"] = t0.isoformat(timespec="seconds")
            recs.append(rec)
    tail = (stderr or "").strip().splitlines()[-3:]
    status = f"rc={rc}" + (f" stderr_tail={' | '.join(tail)[:300]}" if tail else "")
    return recs, status


def md_table(recs: list[dict]) -> str:
    head = "| source | market | check | ok | elapsed_s | rows | first | last | ≥3y | token | error / note |\n|---|---|---|---|---|---|---|---|---|---|---|\n"
    rows = []
    for r in recs:
        msg = (r.get("error") or r.get("note") or "").replace("|", "\\|").replace("\n", " ")[:160]
        rows.append("| {source} | {market} | {check} | {ok} | {el} | {rows} | {f} | {l} | {y} | {tk} | {msg} |".format(
            source=r.get("source"), market=r.get("market"), check=r.get("check"), ok="✅" if r.get("ok") else "❌",
            el=r.get("elapsed_s"), rows=r.get("rows", ""), f=r.get("first_date") or "", l=r.get("last_date") or "",
            y={True: "✅", False: "❌"}.get(r.get("meets_3y"), ""), tk="需token" if r.get("needs_token") else "", msg=msg))
    return head + "\n".join(rows) + "\n"


def main():
    files = discover(sys.argv[1:])
    all_recs, statuses = [], {}
    for f in files:
        print(f"== running {f.name}", flush=True)
        recs, status = run_probe(f)
        statuses[f.name] = status
        all_recs += recs
        ok = sum(1 for r in recs if r.get("ok"))
        print(f"   {ok}/{len(recs)} ok  ({status})", flush=True)

    meta = {"run_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), "python": platform.python_version(),
            "platform": platform.platform(), "files": [f.name for f in files], "statuses": statuses,
            "total": len(all_recs), "ok": sum(1 for r in all_recs if r.get("ok"))}
    with open(HERE / "results.jsonl", "w", encoding="utf-8") as fh:
        fh.write(json.dumps({"_meta": meta}, ensure_ascii=False) + "\n")
        for r in all_recs:
            fh.write(json.dumps(r, ensure_ascii=False, default=str) + "\n")

    out = [f"# 探针汇总（自动生成，勿手改）\n\n- run_at: {meta['run_at']} UTC\n- python: {meta['python']} / {meta['platform']}\n"
           f"- 探针文件 {len(files)} 个，检查项 {meta['total']} 个，通过 {meta['ok']} 个\n"
           "- 节点：美国（探测出口 IP 见各文档），未使用代理；ok=❌ 含“本节点不可达 / 需 token / 上游限制”三类，详见 error 列\n"]
    for f in files:
        recs = [r for r in all_recs if r["probe_file"] == f.name]
        out.append(f"\n## {f.name}\n\n{statuses[f.name]}\n\n" + (md_table(recs) if recs else "_no PROBE lines_\n"))
    (HERE / "results.md").write_text("".join(out), encoding="utf-8")
    print(f"\nTOTAL {meta['ok']}/{meta['total']} ok → results.jsonl / results.md")


if __name__ == "__main__":
    main()
