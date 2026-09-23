"""跨 CPU 确定性的逐元素数学函数（ADR-0003 §4.2 R2「同输入 → 同字节」）。

**为什么需要这个模块**：numpy 对 `exp`/`log`/`sin` 等超越函数按运行时 CPU 特性分派到不同的
SVML 向量核（`__svml_exp8` = AVX-512、`__svml_exp4` = AVX2 …）。这些核各自约 1 ULP 精度但
**结果不保证逐位相同**，于是同一份输入在 AVX-512 runner 与 AVX2 runner 上得到不同的 float64
位模式，一路传导到 Parquet 字节与 sha256（QNT-40：GitHub Actions 上 `payload_sha256` 在
Intel Xeon 8370C / 6973P-C 得 `d54e3278…`，在 AMD EPYC 7763 得 `0afd88ee…`）。
`NPY_DISABLE_CPU_FEATURES` 只能向下屏蔽，不能在无 AVX-512 的机器上复现向上的那条路径，
因此这类漂移在本地永远测不出来——只能从算法上消除。

**做法**：只用 IEEE-754 **正确舍入**的基本运算（`+ - *`、`rint`、`ldexp`）重建 `exp`。
基本运算的结果由 IEEE-754 唯一确定，与向量宽度、FMA 可用性、厂商实现无关，因此逐位可复现。
代价是比 `np.exp` 慢约一个常数倍，精度 ≤ 1 ULP（见 `packages/core/tests/test_detmath.py`）。

**注意**：这里刻意不使用 `np.fma` / 不依赖编译器把 `a*b+c` 收缩成 FMA。numpy 的每个 ufunc 是
独立的一次正确舍入运算，不存在收缩；改写成 FMA 会改变结果位模式，属于破坏性变更。
"""

from __future__ import annotations

import numpy as np

#: Cody-Waite 拆分的 ln2：`_LN2_HI` 只占 33 位尾数，使 `k * _LN2_HI` 在 |k| < 2^20 时可精确表示，
#: 从而 `x - k*_LN2_HI` 无舍入误差；余下低位由 `_LN2_LO` 补偿。
_LN2_HI = float.fromhex("0x1.62e42fefa0000p-1")
_LN2_LO = float.fromhex("0x1.cf79abc9e3b3ap-40")
_INV_LN2 = float.fromhex("0x1.71547652b82fep+0")

#: exp(r) 在 |r| ≤ ln2/2 上的 Taylor 系数 1/n!，n = 13…0（Horner 由高次向低次累乘）。
#: 13 次已使最大误差 ≤ 1 ULP —— r 的范围被 Cody-Waite 归约限制在 ±0.3466。
_TAYLOR_COEFFS: tuple[float, ...] = tuple(
    float.fromhex(c)
    for c in (
        "0x1.6124613a86d09p-33",  # 1/13!
        "0x1.1eed8eff8d898p-29",  # 1/12!
        "0x1.ae64567f544e4p-26",  # 1/11!
        "0x1.27e4fb7789f5cp-22",  # 1/10!
        "0x1.71de3a556c734p-19",  # 1/9!
        "0x1.a01a01a01a01ap-16",  # 1/8!
        "0x1.a01a01a01a01ap-13",  # 1/7!
        "0x1.6c16c16c16c17p-10",  # 1/6!
        "0x1.1111111111111p-7",  # 1/5!
        "0x1.5555555555555p-5",  # 1/4!
        "0x1.5555555555555p-3",  # 1/3!
        "0x1.0000000000000p-1",  # 1/2!
        "0x1.0000000000000p+0",  # 1/1!
        "0x1.0000000000000p+0",  # 1/0!
    )
)

#: float64 上 exp 的溢出 / 下溢边界（超出即 inf / 0.0，与 `np.exp` 语义一致）。
_OVERFLOW = 709.7827128933841
_UNDERFLOW = -745.1332191019411


def exp(x: np.ndarray | float) -> np.ndarray:
    """逐位可复现的 `np.exp`（float64）。

    与 `np.exp` 相差 ≤ 1 ULP，但在任意 x86-64 CPU（有无 AVX-512 / FMA 均可）上结果逐位相同。
    需要跨机器比较 hash 的生成路径必须用本函数，不要用 `np.exp`。

    `nan` → `nan`；`+inf` → `inf`；`-inf` → `0.0`；溢出 → `inf`；下溢 → `0.0`。
    """
    x = np.asarray(x, dtype=np.float64)

    # Cody-Waite 区间归约：x = k·ln2 + r，|r| ≤ ln2/2。
    # 归约只在有限且不溢出的区间上做，非有限值与极端值在最后一步统一覆盖，
    # 避免 inf-inf 产生 nan 污染。
    finite = np.isfinite(x)
    safe = np.where(finite, np.clip(x, _UNDERFLOW, _OVERFLOW), 0.0)

    k = np.rint(safe * _INV_LN2)
    r = (safe - k * _LN2_HI) - k * _LN2_LO

    # Horner：每一步都是一次 multiply + 一次 add，两次独立的正确舍入运算。
    acc = np.full(r.shape, _TAYLOR_COEFFS[0], dtype=np.float64)
    for coeff in _TAYLOR_COEFFS[1:]:
        acc = acc * r + coeff

    # `acc` 已归约到 [~0.7, ~1.4]，`k` 受 clip 限制在 ±1075 内，ldexp 不会溢出；
    # errstate 只防御 clip 边界上的极端情形，不改变结果。
    with np.errstate(over="ignore", under="ignore"):
        out = np.ldexp(acc, k.astype(np.int64))

    # 边界与非有限值：按 np.exp 语义覆盖。
    out = np.where(x > _OVERFLOW, np.inf, out)
    out = np.where(x < _UNDERFLOW, 0.0, out)
    out = np.where(np.isnan(x), np.nan, out)
    out = np.where(np.isposinf(x), np.inf, out)
    out = np.where(np.isneginf(x), 0.0, out)
    return out
