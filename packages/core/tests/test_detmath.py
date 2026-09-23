"""`detmath.exp` 的正确性与确定性（QNT-40：跨 runner payload_sha256 漂移根因）。

这些测试只能证明「与 np.exp 相差 ≤ 1 ULP」「同机可复现」；**跨 CPU 逐位一致无法在单机
测出**（本地 CPU 无 AVX-512 时那条分派路径根本不可达），由 CI 的 `bench-repro` 矩阵覆盖。
"""

from __future__ import annotations

import math

import numpy as np
import pytest
from quantime_core import detmath


def _max_ulp_error(x: np.ndarray) -> float:
    got = detmath.exp(x)
    ref = np.exp(x)
    finite = np.isfinite(ref) & (ref > 0)
    return float(np.max(np.abs(got[finite] - ref[finite]) / np.spacing(ref[finite])))


@pytest.mark.parametrize(
    ("name", "low", "high"),
    [("tiny", -0.5, 0.5), ("small", -5.0, 5.0), ("mid", -40.0, 40.0), ("wide", -700.0, 700.0)],
)
def test_exp_within_one_ulp_of_numpy(name, low, high):
    x = np.random.default_rng(20260920).uniform(low, high, size=200_000)
    assert _max_ulp_error(x) <= 1.0


def test_exp_matches_math_exp_on_exact_points():
    # exp(0) 必须精确等于 1.0，否则 GBM 首日价会漂。
    assert detmath.exp(np.array([0.0]))[0] == 1.0
    assert detmath.exp(np.array([-0.0]))[0] == 1.0
    for v in (1.0, -1.0, 0.5, -0.5, 10.0, -10.0, 100.0, -100.0):
        got = detmath.exp(np.array([v]))[0]
        assert abs(got - math.exp(v)) <= np.spacing(math.exp(v))


def test_exp_special_values_match_numpy_semantics():
    x = np.array([np.nan, np.inf, -np.inf, 0.0, 710.0, -746.0, 709.0])
    got = detmath.exp(x)
    with np.errstate(over="ignore"):
        ref = np.exp(x)
    assert np.isnan(got[0])
    assert got[1] == np.inf
    assert got[2] == 0.0
    assert got[3] == 1.0
    assert got[4] == np.inf  # 溢出
    assert got[5] == 0.0  # 下溢
    assert np.allclose(got[6], ref[6], rtol=1e-15)


def test_exp_is_bitwise_repeatable_in_process():
    x = np.random.default_rng(7).normal(0.0, 3.0, size=100_000)
    a = detmath.exp(x)
    b = detmath.exp(x)
    assert a.tobytes() == b.tobytes()


def test_exp_uses_only_correctly_rounded_primitives():
    """回归护栏：`detmath` 的**代码**不得调用 `np.exp`/`np.expm1`（那是 QNT-40 的漂移源）。

    用 AST 而非文本匹配——文档字符串里必须能自由讨论 `np.exp`，只有真实调用才算违规。
    """
    import ast
    from pathlib import Path

    tree = ast.parse(Path(detmath.__file__).read_text(encoding="utf-8"))
    called = {
        f"{node.func.value.id}.{node.func.attr}"
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
    }
    assert "np.exp" not in called
    assert "np.expm1" not in called


def test_exp_shape_and_dtype_preserved():
    x = np.zeros((3, 4))
    out = detmath.exp(x)
    assert out.shape == (3, 4)
    assert out.dtype == np.float64
    assert detmath.exp(np.float32(1.0)).dtype == np.float64
