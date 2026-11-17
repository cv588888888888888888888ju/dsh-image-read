"""曲线像素提取与采样。语义见 INTERFACE.md §3.5。"""
from __future__ import annotations

import numpy as np

from .detect import estimate_background, luminance


def _kmeans(pix, k, iters, rng):
    n = pix.shape[0]
    k = int(min(k, n))
    if k <= 0:
        return np.zeros((0, 3))
    centers = pix[rng.choice(n, size=k, replace=False)].copy()
    for _ in range(int(iters)):
        d = ((pix[:, None, :] - centers[None, :, :]) ** 2).sum(axis=2)
        assign = d.argmin(axis=1)
        new = centers.copy()
        for j in range(k):
            mask = assign == j
            if bool(mask.any()):
                new[j] = pix[mask].mean(axis=0)
        if np.allclose(new, centers, atol=0.5):
            return new
        centers = new
    return centers


def _grid_mask(sub, bg, cfg):
    """识别网格色并剔除。语义见 INTERFACE.md §3.5-网格。"""
    ex = cfg["extract"]
    total = sub.shape[0] * sub.shape[1]
    if total == 0:
        return np.zeros(sub.shape[:2], bool)
    q = sub.astype(np.int32) // 16
    key = q[..., 0] * 1024 + q[..., 1] * 32 + q[..., 2]
    vals, counts = np.unique(key, return_counts=True)
    order = np.argsort(-counts)
    bg_key = (int(bg[0]) // 16) * 1024 + (int(bg[1]) // 16) * 32 + (int(bg[2]) // 16)
    tol = float(ex["grid_gray_tol"])
    min_frac = float(ex["grid_min_frac"])
    for idx in order[:16]:
        kk = int(vals[idx])
        cnt = int(counts[idx])
        if kk == bg_key:
            continue
        r, g, b = kk // 1024, (kk % 1024) // 32, kk % 32
        target = np.array([r * 16 + 8, g * 16 + 8, b * 16 + 8], dtype=np.float64)
        if np.abs(target - bg).sum() < 60:
            continue  # 离背景太近
        if int(target.max() - target.min()) > 2 * tol:
            continue  # 非灰色（彩色的多半是曲线）
        if cnt / total < min_frac:
            continue
        dist = np.sqrt(((sub.astype(np.float64) - target) ** 2).sum(axis=2))
        return dist <= 2.0 * tol
    return np.zeros(sub.shape[:2], bool)


def extract_series(rgb, frame, cfg):
    """返回 (series_list, (row_off, col_off), grid_mask)。

    series_list 元素：{"mask": bool HxW(ROI), "color": (r,g,b)}。
    语义见 INTERFACE.md §3.5。
    """
    ex = cfg["extract"]
    h, w = rgb.shape[:2]
    margin = int(ex["margin_px"])
    r0 = max(0, frame["top"] + margin)
    c0 = max(0, frame["left"] + margin)
    r1 = min(h, frame["bottom"] - margin + 1)
    c1 = min(w, frame["right"] - margin + 1)
    sub = rgb[r0:r1, c0:c1]
    if sub.size == 0:
        return [], (r0, c0), np.zeros((0, 0), bool)

    subl = luminance(sub)
    bg = estimate_background(rgb, cfg)
    grid = _grid_mask(sub, bg, cfg)

    bg_lum = float(luminance(np.asarray(bg, dtype=np.float64).reshape(1, 1, 3))[0, 0])
    ink = subl <= bg_lum - float(ex["ink_min_delta"])
    diff = sub.max(axis=2).astype(np.int32) - sub.min(axis=2).astype(np.int32)
    colored = (diff >= int(ex["sat_diff"])) & ink & (~grid)
    dark = (subl < float(ex["dark_thresh"])) & ink & (~grid) & (~colored)

    series = []
    if bool(colored.any()):
        pix = sub[colored].astype(np.float64)
        rng = np.random.default_rng(0)
        if pix.shape[0] > 50000:
            pix = pix[rng.choice(pix.shape[0], 50000, replace=False)]
        centers = _kmeans(pix, int(ex["kmeans_k"]), int(ex["kmeans_iters"]), rng)
        merged = []
        md = float(ex["merge_center_dist"])
        for c in centers:
            if not any(np.linalg.norm(c - q) < md for q in merged):
                merged.append(c)
        for c in merged:
            dist = np.sqrt(((sub.astype(np.float64) - c) ** 2).sum(axis=2))
            mask = colored & (dist <= float(ex["close_dist"]))
            if int(mask.sum()) >= int(ex["min_pixels"]):
                series.append({
                    "mask": mask,
                    "color": tuple(int(round(float(v))) for v in c),
                })
        series.sort(key=lambda s: -int(s["mask"].sum()))
        series = series[: int(ex["max_series"])]

    if int(dark.sum()) >= int(ex["min_pixels"]):
        series.append({"mask": dark, "color": (0, 0, 0)})

    return series, (r0, c0), grid


def sample_points(mask, row_off, col_off, stride):
    """按列取中位 y。返回 (xs_px, ys_px, ymin_px, ymax_px)。语义见 INTERFACE.md §3.5。"""
    h, w = mask.shape
    stride = max(1, int(stride))
    xs, ys, ymin, ymax = [], [], [], []
    for c in range(0, w, stride):
        rows = np.flatnonzero(mask[:, c])
        if rows.size == 0:
            continue
        xs.append(float(c + col_off))
        ys.append(float(np.median(rows) + row_off))
        ymin.append(float(rows.min() + row_off))
        ymax.append(float(rows.max() + row_off))
    return xs, ys, ymin, ymax
