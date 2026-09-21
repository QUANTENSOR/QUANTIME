# 1Password env template for the QNT-25 probe (op run --env-file=...).
# Holds only op:// REFERENCES — never a secret value. Safe to commit.
#
#   op run --env-file=docs/research/probes/probe.env.tpl -- \
#       python docs/research/probes/oss_probe.py > docs/research/probes/oss-results.json
#
# The item name contains a space, so the reference must stay quoted.
GITHUB_TOKEN="op://quant-dev/GitHub - PAT/credential"
# Non-secret provenance label recorded in the output's auth_mode field.
# NOT an op:// reference (op run would try to resolve it) — a plain pointer string.
GITHUB_TOKEN_SOURCE="op:quant-dev/GitHub - PAT"
