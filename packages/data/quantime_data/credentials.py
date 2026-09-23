"""凭据注入（AGENTS.md §3「一律 `op read` / `op run` 注入子进程，读取时 `.strip()`」）。

本模块**只从环境变量读**，且只读一次、立刻包成 `SecretValue`。它刻意**不**调用 `op`：
`op` 由外层 `op run --env-file=...` 负责，仓库里不出现任何调用秘钥管理器的代码路径，
也就不可能有「代码里能拿到明文并落盘」的形态。

fail-closed：变量缺失或为空 → `CredentialUnavailableError`，CLI 据此 exit 1 报「凭据不可用」。
**不回落**到任何无 key 路径——静默降级会让一次"成功"的摄取实际上什么都没取到。
"""

from __future__ import annotations

import os

from .transport import CredentialUnavailableError, SecretValue

#: Tushare token 的环境变量名。值由 `op run --env-file=ops/tushare.env.tpl` 注入，
#: 模板里只有 `op://quant-dev/Tushare/credential` 这个**引用**，从无明文。
TUSHARE_TOKEN_ENV = "TUSHARE_TOKEN"

#: 该变量对应的 1Password 引用——写在这里是为了让报错能直接告诉运维去取哪一条。
#: 它是**引用**不是秘钥，可以安全出现在源码与日志里。
TUSHARE_TOKEN_REF = "op://quant-dev/Tushare/credential"


def load_tushare_token(env: dict[str, str] | None = None) -> SecretValue:
    """从环境读 Tushare token 并包成 `SecretValue`（`.strip()` 在包装器里做）。

    缺失/空白一律抛 `CredentialUnavailableError`——错误文本只提变量名与 `op://` 引用，
    永远不回显取到的值（哪怕它"看起来"是空的）。
    """
    source = os.environ if env is None else env
    raw = source.get(TUSHARE_TOKEN_ENV)
    if raw is None:
        raise CredentialUnavailableError(
            f"凭据不可用：环境变量 {TUSHARE_TOKEN_ENV} 未设置"
            f"（应经 `op run --env-file=...` 注入 {TUSHARE_TOKEN_REF}）"
        )
    try:
        return SecretValue(raw)
    except CredentialUnavailableError:
        raise CredentialUnavailableError(
            f"凭据不可用：{TUSHARE_TOKEN_ENV} 为空（`op` 解析 {TUSHARE_TOKEN_REF} 失败？）"
        ) from None


def tushare_token_available(env: dict[str, str] | None = None) -> bool:
    """是否具备跑真实接口测试的条件——供 `pytest.mark.skipif` 使用（离线 CI 必为 False）。"""
    try:
        load_tushare_token(env)
    except CredentialUnavailableError:
        return False
    return True
