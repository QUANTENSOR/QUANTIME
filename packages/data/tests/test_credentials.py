"""凭据注入：fail-closed、不回落、不回显（QNT-48 关键路径）。

不需要真实 token：所有用例用注入的假 env。
"""

from __future__ import annotations

import pytest
from quantime_data.credentials import (
    TUSHARE_TOKEN_ENV,
    TUSHARE_TOKEN_REF,
    load_tushare_token,
    tushare_token_available,
)
from quantime_data.transport import CredentialUnavailableError, SecretValue

FAKE_TOKEN = "tk_SECRET_do_not_log_0123456789abcdef"


def test_token_is_loaded_and_wrapped():
    secret = load_tushare_token({TUSHARE_TOKEN_ENV: FAKE_TOKEN})
    assert isinstance(secret, SecretValue)
    assert secret.reveal() == FAKE_TOKEN


def test_value_is_stripped_per_agents_md():
    """AGENTS.md §3：`op` 注入的值读取时 `.strip()`（尾随换行会让上游判 token 无效）。"""
    assert load_tushare_token({TUSHARE_TOKEN_ENV: f"\n {FAKE_TOKEN}  \n"}).reveal() == FAKE_TOKEN


def test_missing_variable_fails_closed_and_names_the_op_reference():
    with pytest.raises(CredentialUnavailableError) as excinfo:
        load_tushare_token({})
    message = str(excinfo.value)
    assert "凭据不可用" in message
    assert TUSHARE_TOKEN_REF in message, "报错要直接告诉运维去取哪一条"


def test_blank_variable_fails_closed():
    with pytest.raises(CredentialUnavailableError, match="为空"):
        load_tushare_token({TUSHARE_TOKEN_ENV: "   \n"})


def test_error_text_never_echoes_the_value():
    """哪怕值"看起来"无效也不回显——回显一次就进了日志。"""
    with pytest.raises(CredentialUnavailableError) as excinfo:
        load_tushare_token({TUSHARE_TOKEN_ENV: "  "})
    assert str(excinfo.value) != "  "
    for probe in ("tk_", FAKE_TOKEN):
        with pytest.raises(CredentialUnavailableError) as e2:
            load_tushare_token({TUSHARE_TOKEN_ENV: ""})
        assert probe not in str(e2.value)


def test_op_reference_points_at_the_quant_dev_vault():
    """AGENTS.md §3：交易所/数据源等业务凭据只来自 vault `quant-dev`。"""
    assert TUSHARE_TOKEN_REF.startswith("op://quant-dev/")


def test_availability_probe_is_false_without_a_token():
    """CI 离线且无 key —— 真实接口测试据此 skip 并明示。"""
    assert tushare_token_available({}) is False
    assert tushare_token_available({TUSHARE_TOKEN_ENV: FAKE_TOKEN}) is True


def test_no_fallback_path_exists():
    """不回落：缺 key 时没有任何「降级为公共只读」的分支可走。

    静默降级会让一次"成功"的摄取实际上什么都没取到，而调用方看不出区别。
    """
    import inspect

    from quantime_data import credentials

    src = inspect.getsource(credentials)
    for banned in ("default=", 'or ""', "fallback", "except Exception"):
        assert banned not in src, f"credentials.py 出现疑似回落路径: {banned!r}"
