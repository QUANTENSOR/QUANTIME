"""数据源适配层（ADR-0003 §3.2 `data/sources/`）。

每个实现声明 `HOSTS`，并且只经 `transport` 的出口出网：无 key 源走 `PublicTransport`，
需 token 的只读源走 `CredentialedTransport`（两者互不放行）。
"""

__all__ = ["binance_public", "tushare"]
