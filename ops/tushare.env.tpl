# 1Password env template for Tushare Pro ingestion (QNT-48).
# Holds only an op:// REFERENCE — never a secret value. Safe to commit.
#
#   op run --env-file=ops/tushare.env.tpl -- \
#       uv run --package quantime-data --extra ingest quantime-ingest tushare plan \
#       --start 2026-01-01 --end 2026-09-23 --ts-code 000001.SZ
#
# The token is read once by quantime_data.credentials.load_tushare_token(), wrapped in
# SecretValue (masked repr/str/format), and only ever revealed inside the POST body.
# If this variable is missing or empty the CLI exits 1 with "凭据不可用" and does NOT
# fall back to any keyless path.
TUSHARE_TOKEN="op://quant-dev/Tushare/credential"
