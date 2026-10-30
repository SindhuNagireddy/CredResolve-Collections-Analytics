import numpy as np, pandas as pd, duckdb, pathlib
ROOT = pathlib.Path(__file__).resolve().parents[1]
def connect():
    return duckdb.connect(str(ROOT/'golden'/'collections.duckdb'), read_only=True)

def mh_risk_difference(df, n1='n1', y1='y1', n0='n0', y0='y0'):
    """Mantel-Haenszel pooled risk difference across strata with Greenland-Robins variance. Returns (rd, lo, hi, p)."""
    d = df[(df[n1] > 0) & (df[n0] > 0)].copy()
    n = d[n1] + d[n0]
    w = d[n1] * d[n0] / n
    rd = (w * (d[y1] / d[n1] - d[y0] / d[n0])).sum() / w.sum()
    p1, p0 = d[y1] / d[n1], d[y0] / d[n0]
    num = (d[y1] * (d[n1] - d[y1]) * d[n0]**3 + d[y0] * (d[n0] - d[y0]) * d[n1]**3) / (d[n1] * d[n0] * n**2)  # approx
    var = (( p1 * (1 - p1) / d[n1] + p0 * (1 - p0) / d[n0]) * w**2).sum() / w.sum()**2
    se = np.sqrt(var)
    from scipy.stats import norm
    z = rd / se if se > 0 else 0
    return rd, rd - 1.96 * se, rd + 1.96 * se, 2 * (1 - norm.cdf(abs(z)))

def kitagawa(w0, r0, w1, r1):
    """Decompose change in weighted mean outcome into rate effect and mix effect (symmetric Kitagawa)."""
    w0, r0, w1, r1 = map(np.asarray, (w0, r0, w1, r1))
    total = (w1 * r1).sum() - (w0 * r0).sum()
    rate = (((w0 + w1) / 2) * (r1 - r0)).sum()
    mix = (((r0 + r1) / 2) * (w1 - w0)).sum()
    return total, rate, mix
