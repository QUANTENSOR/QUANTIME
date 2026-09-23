"""Check that every fact-table row in oss-references.md matches oss-results.json.

Offline; reads only the two committed files. Exits non-zero on any mismatch.
Run: python docs/research/probes/check_doc_consistency.py
"""

from __future__ import annotations

import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DOC = os.path.join(HERE, "..", "oss-references.md")
RESULTS = os.path.join(HERE, "oss-results.json")

ROW = re.compile(
    r"^\| [^|]+ \| \[([^\]]+)\]\(https://github\.com/[^)]+\) \| "
    r"([^|]+) \| ([^|]+) \| ([^|]+) \| ([^|]+) \| ([^|]+) \|$",
    re.M,
)


def main() -> int:
    with open(DOC, encoding="utf-8") as f:
        doc = f.read()
    with open(RESULTS, encoding="utf-8") as f:
        data = json.load(f)
    rows = {r["repo"].lower(): r for r in data["repos"]}
    table = ROW.findall(doc)
    bad: list[str] = []

    for repo, spdx, c1y, pushed, rel, _py in table:
        j = rows.get(repo.lower())
        if not j:
            bad.append(f"{repo}: not present in oss-results.json")
            continue
        if int(re.sub(r"\D", "", c1y)) != j["commits_1y"]:
            bad.append(f"{repo}: commits_1y doc={c1y.strip()} json={j['commits_1y']}")
        if pushed.strip() != j["pushed_at"][:10]:
            bad.append(f"{repo}: pushed_at doc={pushed.strip()} json={j['pushed_at'][:10]}")
        sj = j["spdx"]
        if sj and sj != "NOASSERTION" and sj.lower() not in spdx.lower():
            bad.append(f"{repo}: spdx doc={spdx.strip()} json={sj}")
        jr, dr = j.get("latest_release"), rel.strip()
        if jr:
            if jr not in dr:
                bad.append(f"{repo}: release tag doc={dr} json={jr}")
            elif j.get("released_at") and j["released_at"][:10] not in dr:
                bad.append(f"{repo}: release date doc={dr} json={j['released_at'][:10]}")
        elif dr != "—":
            bad.append(f"{repo}: doc claims release {dr} but JSON has none")

    absent = set(rows) - {r.lower() for r, *_ in table}
    if absent:
        bad.append(f"repos in JSON but missing from the table: {sorted(absent)}")
    if len(table) != len(data["repos"]):
        bad.append(f"row count {len(table)} != JSON repo count {len(data['repos'])}")
    if data.get("failures"):
        bad.append(f"JSON records {len(data['failures'])} probe failure(s) — results incomplete")
    if any(r["status"] != "ok" for r in data["repos"]):
        bad.append("JSON contains rows with status != ok")
    if f"probed_at={data['probed_at']}" not in doc:
        bad.append(f"doc does not cite probed_at={data['probed_at']}")

    for b in bad:
        print("MISMATCH " + b, file=sys.stderr)
    if bad:
        print(f"{len(bad)} mismatch(es)", file=sys.stderr)
        return 1
    print(
        f"OK: {len(table)}/{len(data['repos'])} rows consistent "
        f"(commits_1y, pushed_at, spdx, release tag + date); "
        f"auth_mode={data['auth_mode']}; no failures"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
