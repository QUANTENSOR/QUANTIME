"""临时诊断脚本（QNT-40）——dump bench_gen 各中间量的 sha，定位跨 runner 漂移点。
不入最终 PR。"""
import hashlib, json, os, platform, sys
import numpy as np

def h(a):
    return hashlib.sha256(np.ascontiguousarray(a).tobytes()).hexdigest()[:16]

seed, symbols, days = 20260920, 1000, 1260
rng = np.random.default_rng(seed)
sigma = 0.02 / np.sqrt(252.0)
shocks = rng.normal(loc=0.0, scale=sigma, size=(symbols, days))
hi = np.abs(rng.normal(loc=0.0, scale=0.01, size=(symbols, days)))
lo = np.abs(rng.normal(loc=0.0, scale=0.01, size=(symbols, days)))
volume = rng.lognormal(mean=12.0, sigma=1.0, size=(symbols, days))
log_steps = -0.5 * sigma**2 + shocks
cs = np.cumsum(log_steps, axis=1)
ex = np.exp(cs)
close = 100.0 * ex
open_ = np.empty_like(close); open_[:, 0] = 100.0; open_[:, 1:] = close[:, :-1]
high = np.maximum(close * (1.0 + hi), np.maximum(open_, close))
low = np.minimum(close * (1.0 - lo), np.minimum(open_, close))

feats = np._core._multiarray_umath.__cpu_features__
out = {
    "mask": os.environ.get("NPY_DISABLE_CPU_FEATURES", ""),
    "cpu_model": next((l.split(":",1)[1].strip() for l in open("/proc/cpuinfo")
                       if l.startswith("model name")), "?"),
    "avx512f": feats.get("AVX512F"), "avx512_skx": feats.get("AVX512_SKX"),
    "avx2": feats.get("AVX2"), "fma3": feats.get("FMA3"),
    "numpy": np.__version__, "python": platform.python_version(),
    "steps": {n: h(a) for n, a in [
        ("1_shocks", shocks), ("2_hi_noise", hi), ("3_lo_noise", lo), ("4_volume", volume),
        ("5_log_steps", log_steps), ("6_cumsum", cs), ("7_exp", ex), ("8_close", close),
        ("9_open", open_), ("10_high", high), ("11_low", low)]},
}
print("DIAGJSON " + json.dumps(out, sort_keys=True))
