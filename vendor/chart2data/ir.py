"""层 1：图 → 几何 IR。只记「看见了什么图形」，不解释数据语义。语义见 INTERFACE.md §10。"""
from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np

from .detect import detect_frame, detect_ticks, strong_ink
from .extract import extract_series, sample_points

IR_SCHEMA = "chart2data/ir@1"
LAYER1_BACKEND = "raster-v1"


def _round(v, nd=1):
    return round(float(v), nd)


def _color(item):
    return [int(v) for v in item["color"]]


def build_ir_raster(rgb, cfg, path):
    """从位图构建 IR：框、刻度、曲线（像素坐标）。语义见 INTERFACE.md §10.1。"""
    h, w = rgb.shape[:2]
    sha = hashlib.sha256(Path(path).read_bytes()).hexdigest()
    frame = detect_frame(rgb, cfg)
    ink, _, _ = strong_ink(rgb, cfg)
    ticks = detect_ticks(ink, frame, cfg)

    masks, (r0, c0), _grid = extract_series(rgb, frame, cfg)
    stride = int(cfg["extract"]["sample_stride"])

    objects = [{
        "id": "frame",
        "kind": "frame",
        "role": "plot_frame",
        "geometry": {"rect": [int(frame["left"]), int(frame["top"]),
                              int(frame["right"]), int(frame["bottom"])]},
        "style": {"color": None, "width_px": 1.0},
    }]
    for axis in ("x", "y"):
        for i, t in enumerate(ticks[axis]):
            objects.append({
                "id": f"tick_{axis}_{i}",
                "kind": "tick",
                "role": "tick",
                "axis": axis,
                "geometry": {"pixel": _round(t)},
                "style": {"color": None, "width_px": 1.0},
            })

    series_px = []
    for i, item in enumerate(masks):
        xs, ys, ymin, ymax = sample_points(item["mask"], r0, c0, stride)
        if not xs:
            continue
        name = f"c{i}"
        objects.append({
            "id": f"series_{name}",
            "kind": "curve",
            "role": "data",
            "series": name,
            "geometry": {"points_px": [[_round(x), _round(y)] for x, y in zip(xs, ys)]},
            "style": {"color": _color(item), "width_px": 2.0},
        })
        series_px.append({
            "name": name,
            "color": _color(item),
            "x_px": [float(v) for v in xs],
            "y_px": [float(v) for v in ys],
            "y_min_px": [float(v) for v in ymin],
            "y_max_px": [float(v) for v in ymax],
        })

    ir = {
        "schema": IR_SCHEMA,
        "source": {
            "type": "raster",
            "path": str(path),
            "sha256": sha,
            "width": int(w),
            "height": int(h),
            "backend": LAYER1_BACKEND,
        },
        "canvas": {"width": int(w), "height": int(h)},
        "frame": frame,
        "objects": objects,
        "labels": [],
        "notes": ["raster backend 无文本层：标题/轴标签/图例未识别，刻度值为像素位置"],
    }
    return ir, series_px
