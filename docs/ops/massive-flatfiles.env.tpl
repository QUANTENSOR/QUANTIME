# 1Password env template for Massive Flat Files (S3-compatible, SigV4) — QNT-47 phase 2.
# Holds only op:// REFERENCES — never a secret value. Safe to commit
# (AGENTS.md §3: the repo tracks *.tpl only; every real .env* stays ignored).
#
#   op run --env-file=docs/ops/massive-flatfiles.env.tpl -- \
#       uv run --package quantime-data --extra ingest quantime-ingest-us \
#           --root "$HOME/quantime" flatfiles --start 2026-08-01 --end 2026-08-31
#
# Item "Massive Quantime Flat Files" (vault quant-dev, owner ruling 2026-09-23). The item
# name and two field names contain spaces, so every reference is double-quoted.
# All four values are read once and .strip()'d (flatfiles.read_flatfiles_credentials).
# Endpoint and bucket are not secrets, but the injected values must equal the allowlist
# entry MASSIVE_FLATFILES and the constant "flatfiles" — otherwise ingestion exits 1.
# Any missing/empty variable → exit 1 「凭据不可用」, no fallback.
MASSIVE_FLATFILES_ACCESS_KEY_ID="op://quant-dev/Massive Quantime Flat Files/Access Key ID"
MASSIVE_FLATFILES_SECRET_ACCESS_KEY="op://quant-dev/Massive Quantime Flat Files/credential"
MASSIVE_FLATFILES_ENDPOINT="op://quant-dev/Massive Quantime Flat Files/S3 Endpoint"
MASSIVE_FLATFILES_BUCKET="op://quant-dev/Massive Quantime Flat Files/Bucket"
