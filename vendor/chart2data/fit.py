"""曲线拟合与方程输出。语义见 INTERFACE.md §3.6。"""
from __future__ import annotations

import numpy as np


def format_equation(coeffs, degree, xname="x"):
    """把从高次到低次的系数排成可读方程。"""
    terms = []
    for i, c in enumerate(coeffs):
        p = degree - i
        if p == 0:
            body = f"{abs(c):.6g}"
        elif p == 1:
            body = f"{abs(c):.6g}·{xname}"
        else:
            body = f"{abs(c):.6g}·{xname}^{p}"
        terms.append((float(c), body))
    out = "y = "
    for i, (c, body) in enumerate(terms):
        if i == 0:
            out += ("−" if c < 0 else "") + body
        else:
            out += (" − " if c < 0 else " + ") + body
    return out


def fit_points(xs, ys, cfg):
    """多项式拟合，按相对 RMSE 改善选阶。返回 (fit_dict | None, 失败原因 | None)。"""
    f = cfg["fit"]
    xs = np.asarray(xs, dtype=np.float64)
    ys = np.asarray(ys, dtype=np.float64)
    good = np.isfinite(xs) & np.isfinite(ys)
    xs, ys = xs[good], ys[good]
    if xs.size < int(f["min_points"]):
        return None, "拟合点不足"

    order = np.argsort(xs)
    x, y = xs[order], ys[order]
    ux, inv = np.unique(x, return_inverse=True)
    if ux.size < int(f["min_points"]):
        return None, "有效 x 太少"
    yy = np.array([float(np.median(y[inv == i])) for i in range(ux.size)])
    n = ux.size

    cand = []
    for d in range(1, int(f["degree_max"]) + 1):
        if d >= n:
            break
        coeffs = np.polyfit(ux, yy, d)
        resid = yy - np.polyval(coeffs, ux)
        cand.append((d, coeffs, float((resid ** 2).sum())))
    if not cand:
        return None, "拟合失败"

    tol = float(f["min_rel_improve_frac"])
    best = cand[0]
    for cur in cand[1:]:
        prev_rmse = np.sqrt(best[2] / n)
        cur_rmse = np.sqrt(cur[2] / n)
        if prev_rmse > 0 and (prev_rmse - cur_rmse) / prev_rmse < tol:
            break
        best = cur
    deg, coeffs, rss = best
    resid = yy - np.polyval(coeffs, ux)
    tss = float(((yy - yy.mean()) ** 2).sum())
    r2 = 1.0 - rss / tss if tss > 0 else 1.0
    rmse = float(np.sqrt(rss / n))

    return {
        "model": f"poly{deg}",
        "coeffs": [float(c) for c in coeffs],
        "rmse": rmse,
        "r2": float(r2),
        "equation": format_equation(coeffs, deg),
    }, None
