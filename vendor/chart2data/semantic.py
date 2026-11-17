"""层 2：几何 IR → 数据（标定、采样换算、拟合）。语义见 INTERFACE.md §10.2。"""
from __future__ import annotations

import numpy as np

from .calib import build_axis, pixel_axis
from .fit import fit_points


def _ticks_from_ir(ir):
    out = {"x": [], "y": []}
    for obj in ir["objects"]:
        if obj.get("kind") == "tick" and obj.get("axis") in out:
            out[obj["axis"]].append(float(obj["geometry"]["pixel"]))
    for axis in out:
        out[axis].sort()
    return out


def build_result(ir, series_px, calib_cfg, cfg, units):
    """IR + 标定 → result（schema chart2data/result@1）。语义见 INTERFACE.md §10.2。"""
    frame = ir["frame"]
    warnings = []

    if units == "pixel" or calib_cfg is None:
        cal_x = pixel_axis(frame["left"], frame["right"], "x")
        cal_y = pixel_axis(frame["top"], frame["bottom"], "y")
        if units != "pixel":
            warnings.append("未标定，坐标为像素（x 向右、y 向上翻转）")
    else:
        ticks = _ticks_from_ir(ir)
        cal_x = build_axis(calib_cfg.get("x", {}), ticks["x"])
        cal_y = build_axis(calib_cfg.get("y", {}), ticks["y"])

    if not series_px:
        warnings.append("未提取到曲线")

    series_out = []
    for item in series_px:
        x = cal_x.to_data(np.asarray(item["x_px"], dtype=float))
        y = cal_y.to_data(np.asarray(item["y_px"], dtype=float))
        y1 = cal_y.to_data(np.asarray(item["y_min_px"], dtype=float))
        y2 = cal_y.to_data(np.asarray(item["y_max_px"], dtype=float))
        lo = np.minimum(y1, y2)
        hi = np.maximum(y1, y2)

        fit, why = fit_points(x.tolist(), y.tolist(), cfg)
        if fit is None:
            warnings.append(f"系列 {item['name']} 未拟合：{why}")
        else:
            span = float(np.max(y) - np.min(y)) if y.size else 0.0
            if span > 0 and fit["rmse"] > float(cfg["fit"]["rmse_warn_frac"]) * span:
                warnings.append(f"系列 {item['name']} 拟合残差偏大：RMSE={fit['rmse']:.4g}")

        series_out.append({
            "name": item["name"],
            "color": item["color"],
            "n_points": len(item["x_px"]),
            "x": [round(float(v), 6) for v in x],
            "y": [round(float(v), 6) for v in y],
            "y_min": [round(float(v), 6) for v in lo],
            "y_max": [round(float(v), 6) for v in hi],
            "fit": fit,
        })

    result = {
        "schema": "chart2data/result@1",
        "image": {
            "path": ir["source"]["path"],
            "sha256": ir["source"]["sha256"],
            "width": ir["source"]["width"],
            "height": ir["source"]["height"],
        },
        "frame": frame,
        "calibration": {"x": cal_x.to_dict(), "y": cal_y.to_dict()},
        "series": series_out,
        "warnings": warnings,
    }
    return result
