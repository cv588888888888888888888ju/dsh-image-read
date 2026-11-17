"""标定：像素位置 ↔ 数据值。语义见 INTERFACE.md §3.4、§4、§5。"""
from __future__ import annotations

import numpy as np


class CalibError(Exception):
    pass


class AxisCalibration:
    def __init__(self, scale, a, b, pixels, values, mode):
        self.scale = scale
        self.a = float(a)
        self.b = float(b)
        self.pixels = [float(p) for p in pixels]
        self.values = [float(v) for v in values]
        self.mode = mode

    def to_data(self, pixels):
        arr = np.asarray(pixels, dtype=np.float64)
        if self.scale == "log":
            return 10.0 ** (self.a * arr + self.b)
        return self.a * arr + self.b

    def to_dict(self):
        return {
            "scale": self.scale,
            "pixels": self.pixels,
            "values": self.values,
            "mode": self.mode,
        }


def pixel_axis(lo, hi, axis):
    """无标定模式：x 向右、y 向上翻转。语义见 INTERFACE.md §3.4-3。"""
    lo, hi = float(lo), float(hi)
    if axis == "x":
        return AxisCalibration("linear", 1.0, 0.0, [lo, hi], [lo, hi], "pixel")
    return AxisCalibration("linear", -1.0, hi, [lo, hi], [hi - lo, 0.0], "pixel")


def build_axis(axis_cfg, auto_pixels, mode_hint=None):
    """按 §3.4 构造一个轴的标定。"""
    scale = str(axis_cfg.get("scale") or "linear").lower()
    if scale not in ("linear", "log"):
        raise CalibError(f"未知 scale: {scale}")

    pixels = axis_cfg.get("pixels")
    values = axis_cfg.get("values")
    vrange = axis_cfg.get("values_range")

    if pixels is None:
        pixels = auto_pixels
        mode = "auto"
        if not pixels or len(pixels) < 2:
            raise CalibError("自动检出的刻度不足 2 个，无法标定；请显式给 pixels")
    else:
        pixels = list(pixels)
        mode = "explicit"
    if mode_hint:
        mode = mode_hint

    if values is None:
        if not vrange or len(vrange) != 2:
            raise CalibError("标定缺少 values 或 values_range")
        lo, hi = float(vrange[0]), float(vrange[1])
        n = len(pixels)
        if n < 2:
            raise CalibError("pixels 少于 2 个")
        if scale == "log":
            values = np.logspace(np.log10(lo), np.log10(hi), n).tolist()
        else:
            values = np.linspace(lo, hi, n).tolist()
        mode = mode + "+range"

    if len(pixels) != len(values):
        raise CalibError(
            f"pixels 与 values 数量不一致: {len(pixels)} vs {len(values)}")

    px = np.asarray(pixels, dtype=np.float64)
    val = np.asarray(values, dtype=np.float64)
    if scale == "log":
        if np.any(val <= 0):
            raise CalibError("log 轴出现非正数")
        a, b = np.polyfit(px, np.log10(val), 1)
    else:
        a, b = np.polyfit(px, val, 1)
    return AxisCalibration(scale, float(a), float(b), pixels, values, mode)
