"""框线与刻度检测。语义见 INTERFACE.md §3.2、§3.3。

本模块不写任何可调数值，全部从 cfg 读（值见 config.json）。
"""
from __future__ import annotations

import numpy as np


def luminance(rgb):
    """RGB uint8 图 → 浮点亮度图。"""
    return (rgb[..., 0].astype(np.float64) * 0.299
            + rgb[..., 1].astype(np.float64) * 0.587
            + rgb[..., 2].astype(np.float64) * 0.114)


def estimate_background(rgb, cfg):
    """四角小块中位色当背景。语义见 INTERFACE.md §3.1。"""
    h, w = rgb.shape[:2]
    f = float(cfg["background"]["corner_frac"])
    ch = max(1, int(round(h * f)))
    cw = max(1, int(round(w * f)))
    patches = [rgb[:ch, :cw], rgb[:ch, -cw:], rgb[-ch:, :cw], rgb[-ch:, -cw:]]
    px = np.concatenate([p.reshape(-1, 3) for p in patches], axis=0)
    return np.median(px.astype(np.float64), axis=0)


def background_luminance(bg):
    return float(bg[0] * 0.299 + bg[1] * 0.587 + bg[2] * 0.114)


class FrameNotFound(Exception):
    pass


def strong_ink(rgb, cfg):
    """强墨掩码（框线/刻度/深色曲线）。语义见 INTERFACE.md §3.1。"""
    lum = luminance(rgb)
    bg = estimate_background(rgb, cfg)
    bg_lum = background_luminance(bg)
    thr = bg_lum - float(cfg["frame"]["ink_delta"])
    return lum < thr, lum, bg_lum


def detect_frame(rgb, cfg):
    """返回 {left, top, right, bottom}（像素，含框线）。语义见 INTERFACE.md §3.2。"""
    ink, _, _ = strong_ink(rgb, cfg)
    h, w = ink.shape
    ratio = float(cfg["frame"]["line_ratio"])
    min_len = float(cfg["frame"]["min_line_len_px"])
    row_need = max(min_len, ratio * w)
    col_need = max(min_len, ratio * h)
    rows = np.flatnonzero(ink.sum(axis=1) >= row_need)
    cols = np.flatnonzero(ink.sum(axis=0) >= col_need)
    if rows.size < 2 or cols.size < 2:
        raise FrameNotFound("未检出绘图框，请用 --calib 显式给标定或换图")
    return {
        "left": int(cols.min()),
        "top": int(rows.min()),
        "right": int(cols.max()),
        "bottom": int(rows.max()),
    }


def _groups(positions, gap):
    positions = [int(p) for p in positions]
    if not positions:
        return []
    out = [[positions[0]]]
    for p in positions[1:]:
        if p - out[-1][-1] <= gap:
            out[-1].append(p)
        else:
            out.append([p])
    return [(g[0], g[-1]) for g in out]


def _x_band(ink, frame, direction, cfg):
    band = int(cfg["ticks"]["band_px"])
    min_count = int(cfg["ticks"]["min_count_px"])
    min_extent = int(cfg["ticks"]["min_extent_px"])
    gap = int(cfg["ticks"]["group_gap_px"])
    h, w = ink.shape
    base = frame["bottom"]
    if direction == "out":
        r0, r1 = base + 1, min(h, base + 1 + band)
        touch = slice(0, 2)
    else:
        r0, r1 = max(0, base - band), base
        touch = slice(-2, None)
    if r1 <= r0:
        return []
    sub = ink[r0:r1, :]
    counts = sub.sum(axis=0)
    ticks = []
    for a, b in _groups(np.flatnonzero(counts >= min_count), gap):
        seg = sub[:, a:b + 1]
        if not bool(seg[touch, :].any()):
            continue  # 不从轴线上长出来的多半是刻度数字
        extent = int(seg.any(axis=1).sum())
        if extent >= min_extent:
            ticks.append((a + b) / 2.0)
    lo, hi = frame["left"] - 2, frame["right"] + 2
    return [t for t in ticks if lo <= t <= hi]


def _y_band(ink, frame, direction, cfg):
    band = int(cfg["ticks"]["band_px"])
    min_count = int(cfg["ticks"]["min_count_px"])
    min_extent = int(cfg["ticks"]["min_extent_px"])
    gap = int(cfg["ticks"]["group_gap_px"])
    h, w = ink.shape
    base = frame["left"]
    if direction == "out":
        c0, c1 = max(0, base - band), base
        touch = slice(-2, None)
    else:
        c0, c1 = base + 1, min(w, base + 1 + band)
        touch = slice(0, 2)
    if c1 <= c0:
        return []
    sub = ink[:, c0:c1]
    counts = sub.sum(axis=1)
    ticks = []
    for a, b in _groups(np.flatnonzero(counts >= min_count), gap):
        seg = sub[a:b + 1, :]
        if not bool(seg[:, touch].any()):
            continue
        extent = int(seg.any(axis=0).sum())
        if extent >= min_extent:
            ticks.append((a + b) / 2.0)
    lo, hi = frame["top"] - 2, frame["bottom"] + 2
    return [t for t in ticks if lo <= t <= hi]


def detect_ticks(ink, frame, cfg):
    """返回 {'x': [...], 'y': [...]} 刻度像素位置；框外优先，退化到框内。"""
    res = {}
    for axis, fn in (("x", _x_band), ("y", _y_band)):
        out = fn(ink, frame, "out", cfg)
        inn = fn(ink, frame, "in", cfg)
        best = out if len(out) >= 2 else inn
        if len(out) >= 2 and len(inn) > len(out):
            best = inn
        res[axis] = best[: int(cfg["ticks"]["max_ticks"])]
    return res
