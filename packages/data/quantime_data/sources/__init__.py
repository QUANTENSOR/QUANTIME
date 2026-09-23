"""数据源适配层（ADR-0003 §3.2 `data/sources/`）。

每个实现声明 `HOSTS`，并且只经 `transport.PublicTransport` 出网。
"""

__all__ = ["binance_public"]
