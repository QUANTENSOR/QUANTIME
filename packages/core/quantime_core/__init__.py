"""quantime 横切层（ADR-0003 §3.1「横切」行）。

本包只含纯数据与纯函数：路径规范、id 生成、host allowlist、确定性 Parquet writer。
不得 import 任何网络客户端（ADR-0003 §3.3，由 import-linter 守卫）。
"""

__all__ = ["allowlist", "ids", "parquet_io", "paths"]
