# 1Password env template for the Massive (ex-Polygon.io) market-data API — QNT-47.
# Holds only an op:// REFERENCE — never a secret value. Safe to commit
# (AGENTS.md §3: the repo tracks *.tpl only; every real .env* stays ignored).
#
#   op run --env-file=docs/ops/massive.env.tpl -- \
#       uv run --package quantime-data --extra ingest quantime-ingest-us --root "$HOME/quantime" reference
#
# Tests need NO key: they run offline against fixtures/massive/ (synthetic) and
# fixtures/massive_recorded/ (sanitized recordings). Phase 2 (owner ruling
# 2026-09-23) points at the item "Massive Quantime API" — the item name has spaces,
# so the whole reference is double-quoted.
#
# The key is read once, .strip()'d, and injected into the Authorization: Bearer
# header. It never enters a URL, a log line, or a file (keyed_transport.py).
# If the variable is missing or empty, ingestion exits 1 with 「凭据不可用」 —
# there is no anonymous fallback.
MASSIVE_API_KEY="op://quant-dev/Massive Quantime API/credential"
# Non-secret provenance label. NOT an op:// reference (op run would try to
# resolve it) — a plain pointer string, mirrored by massive.CREDENTIAL_POINTER.
MASSIVE_API_KEY_SOURCE="op:quant-dev/Massive Quantime API/credential"
