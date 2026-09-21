#!/usr/bin/env bash
# QNT-25 probe runner. Credentials come from 1Password (vault quant-dev) ONLY.
#
# Fails closed: if the vault read fails, the script exits 1 with "凭据不可用"
# and never falls back to a local credential store (no `gh auth token`, no
# `gh api`, no ~/.netrc). Run with --anonymous to deliberately skip the vault.
#
#   scripts/run_probe.sh              # op-injected token
#   scripts/run_probe.sh --anonymous  # no credential at all (quota-limited)
set -Eeuo pipefail

cd "$(dirname "$0")/.."
TPL="docs/research/probes/probe.env.tpl"
OUT="docs/research/probes/oss-results.json"
# The vault reference lives ONLY in the template, so the repo has a single
# source of truth for it. The item name contains a space, hence the quoting.
REF="$(sed -n 's/^GITHUB_TOKEN="\(.*\)"$/\1/p' "$TPL")"
[[ -n "$REF" ]] || { echo "凭据不可用：${TPL} 内未找到 GITHUB_TOKEN 引用" >&2; exit 1; }

if [[ "${1:-}" == "--anonymous" ]]; then
  echo "running ANONYMOUS (no credential); expect rate-limit failures and exit 1" >&2
  exec env -u GITHUB_TOKEN -u GITHUB_TOKEN_SOURCE python3 docs/research/probes/oss_probe.py > "$OUT"
fi

command -v op >/dev/null 2>&1 || { echo "凭据不可用：未找到 1Password CLI (op)" >&2; exit 1; }

# Probe the reference first so an unreadable vault fails here, loudly, rather
# than silently degrading to an anonymous run. The value is never printed.
if ! op read "$REF" >/dev/null 2>&1; then
  echo "凭据不可用：无法读取 ${REF}（vault quant-dev 不可访问或条目缺失）" >&2
  exit 1
fi

echo "credential source: ${REF} (value never printed)" >&2
op run --env-file="$TPL" -- python3 docs/research/probes/oss_probe.py > "$OUT"
