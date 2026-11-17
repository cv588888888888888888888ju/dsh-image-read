"""层 1（PDF 前端）：PDF 页 → 几何 IR（矢量路径 + 文本层）。语义见 INTERFACE.md §10.5。"""
from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np

from .detect import FrameNotFound
from .ir import IR_SCHEMA

PDF_BACKEND = "pdf-plumber-v1"


class PdfBackendError(RuntimeError):
    """PDF 前端不可用：缺依赖 / 页号越界 / 文件读不了。语义见 INTERFACE.md §10.5。"""


def _import_pdfplumber():
    try:
        import pdfplumber
    except ImportError as exc:  # pragma: no cover - 缺依赖
        raise PdfBackendError(
            "PDF 前端需要 pdfplumber（pip install pdfplumber）") from exc
    return pdfplumber


def _round(v, nd=2):
    return round(float(v), nd)


def _to255(color):
    """pdfplumber 颜色 → [r, g, b]（0-255）；无法判断返回 None。"""
    if color is None:
        return None
    if isinstance(color, (int, float)):
        v = int(round(float(color) * 255))
        return [v, v, v]
    vals = [float(v) for v in color if isinstance(v, (int, float))]
    if len(vals) >= 3:
        return [int(round(v * 255)) for v in vals[:3]]
    if len(vals) == 1:
        v = int(round(vals[0] * 255))
        return [v, v, v]
    return None


def _is_light_gray(color, cfg):
    if color is None:
        return False
    lo, hi = min(color), max(color)
    return (hi - lo) <= int(cfg["pdf"]["grid_gray_tol"] * 255) and lo >= int(
        cfg["pdf"]["grid_gray_min"] * 255)


def _num(text):
    """文本 → 数值（允许千位分隔、正负号、小数、百分号）；非数值返回 None。"""
    t = str(text).strip().replace(" ", "").replace(",", "")
    if not t:
        return None
    if t.endswith("%"):
        t = t[:-1]
    try:
        return float(t)
    except ValueError:
        return None


def _frame(page, cfg):
    """找绘图框：优先独立 rect，退化为两条长横线 + 两条长竖线围出的矩形。"""
    pcfg = cfg["pdf"]
    min_w = float(pcfg["frame_min_w_frac"]) * float(page.width)
    min_h = float(pcfg["frame_min_h_frac"]) * float(page.height)
    cands = []
    for r in page.rects:
        w = float(r["x1"] - r["x0"])
        h = float(r["bottom"] - r["top"])
        cands.append({"left": float(r["x0"]), "top": float(r["top"]),
                      "right": float(r["x1"]), "bottom": float(r["bottom"]),
                      "area": w * h, "w": w, "h": h})
    hs = [ln for ln in page.lines
          if abs(ln["y1"] - ln["y0"]) <= 1.0 and (ln["x1"] - ln["x0"]) >= min_w]
    vs = [ln for ln in page.lines
          if abs(ln["x1"] - ln["x0"]) <= 1.0 and (ln["bottom"] - ln["top"]) >= min_h]
    if len(hs) >= 2 and len(vs) >= 2:
        left = min(min(ln["x0"], ln["x1"]) for ln in vs)
        right = max(max(ln["x0"], ln["x1"]) for ln in vs)
        top = min(ln["top"] for ln in hs)
        bottom = max(ln["bottom"] for ln in hs)
        cands.append({"left": left, "top": top, "right": right, "bottom": bottom,
                      "area": (right - left) * (bottom - top),
                      "w": right - left, "h": bottom - top})
    best = None
    for c in cands:
        if c["w"] >= min_w and c["h"] >= min_h and (best is None or c["area"] > best["area"]):
            best = c
    if best is None:
        raise FrameNotFound("未检出绘图框（PDF 矢量层），请用 --calib 显式给标定或换图")
    return {"left": _round(best["left"]), "top": _round(best["top"]),
            "right": _round(best["right"]), "bottom": _round(best["bottom"])}


def _ticks(page, frame, cfg):
    """在框边找短线段：竖短线贴底边 = x 刻度，横短线贴左边 = y 刻度。"""
    pcfg = cfg["pdf"]
    max_len = float(pcfg["tick_max_len_pt"])
    attach = float(pcfg["tick_attach_pt"])
    xs, ys = [], []
    for ln in page.lines:
        left, right = min(ln["x0"], ln["x1"]), max(ln["x0"], ln["x1"])
        top, bottom = ln["top"], ln["bottom"]
        w, h = right - left, bottom - top
        if w <= 0.5 and h <= max_len and h > 0:
            near_bottom = (abs(bottom - frame["bottom"]) <= attach
                           or abs(top - frame["bottom"]) <= attach)
            if near_bottom:
                xs.append(0.5 * (left + right))
        elif h <= 0.5 and w <= max_len and w > 0:
            near_left = (abs(right - frame["left"]) <= attach
                         or abs(left - frame["left"]) <= attach)
            if near_left:
                ys.append(0.5 * (top + bottom))
    out = {}
    for axis, vals, lo, hi in (
            ("x", xs, frame["left"] - 2, frame["right"] + 2),
            ("y", ys, frame["top"] - 2, frame["bottom"] + 2)):
        vals = sorted(v for v in vals if lo <= v <= hi)
        merged = []
        for v in vals:
            if merged and abs(v - merged[-1]) <= float(pcfg["tick_merge_pt"]):
                merged[-1] = 0.5 * (merged[-1] + v)
            else:
                merged.append(v)
        out[axis] = merged[:int(pcfg["max_ticks"])]
    return out


def _labels(page, frame, ticks, cfg):
    """文本层 → labels；数字且贴着刻度的词同时标注 value，供 skeleton 直接用。"""
    pcfg = cfg["pdf"]
    xtol = float(pcfg["label_x_tol_pt"])
    ytol = float(pcfg["label_y_tol_pt"])
    max_off = float(pcfg["tick_label_max_offset_pt"])
    title_gap = float(pcfg["title_gap_pt"])
    words = page.extract_words()
    labels = []
    for w in words:
        text = w["text"]
        cx = 0.5 * (w["x0"] + w["x1"])
        cy = 0.5 * (w["top"] + w["bottom"])
        entry = {"text": text,
                 "bbox": [_round(w["x0"]), _round(w["top"]),
                          _round(w["x1"]), _round(w["bottom"])]}
        value = _num(text)
        matched = None
        if value is not None:
            for t in ticks["x"]:
                if abs(cx - t) <= xtol and frame["bottom"] < w["top"] <= frame["bottom"] + max_off:
                    matched = ("x", t)
                    break
            if matched is None:
                for t in ticks["y"]:
                    if (abs(cy - t) <= ytol and w["x1"] <= frame["left"]
                            and w["x1"] >= frame["left"] - max_off):
                        matched = ("y", t)
                        break
        if matched is not None:
            axis, pixel = matched
            entry.update({"role": "tick", "axis": axis,
                          "pixel": _round(pixel), "value": value})
        elif w["bottom"] < frame["top"] - title_gap:
            entry["role"] = "title"
        elif w["top"] > frame["bottom"] + max_off:
            entry["role"] = "xlabel"
        elif w["x1"] < frame["left"] - max_off:
            entry["role"] = "ylabel"
        elif (frame["left"] <= cx <= frame["right"]
              and frame["top"] <= cy <= frame["bottom"]):
            entry["role"] = "legend"
        else:
            entry["role"] = "other"
        labels.append(entry)
    return labels


def _stroke_points(page):
    """页面所有描边元素 → (points(N,2), color[3], width, bbox)。"""
    items = []
    for c in page.curves:
        if not c.get("stroke") or not c.get("pts"):
            continue
        pts = np.asarray([p for p in c["pts"] if p is not None], dtype=float)
        if pts.shape[0] < 2:
            continue
        items.append({"pts": pts, "color": _to255(c.get("stroking_color")),
                      "width": float(c.get("linewidth") or 1.0),
                      "left": float(c["x0"]), "right": float(c["x1"]),
                      "top": float(c["top"]), "bottom": float(c["bottom"]),
                      "kind": "curve"})
    for ln in page.lines:
        if not ln.get("stroke"):
            continue
        pts = np.asarray([[ln["x0"], ln["top"]], [ln["x1"], ln["bottom"]]], dtype=float)
        items.append({"pts": pts, "color": _to255(ln.get("stroking_color")),
                      "width": float(ln.get("linewidth") or 1.0),
                      "left": float(ln["x0"]), "right": float(ln["x1"]),
                      "top": float(ln["top"]), "bottom": float(ln["bottom"]),
                      "kind": "line"})
    return items


def _is_frame_side(item, frame, tol=1.5):
    l, r, t, b = item["left"], item["right"], item["top"], item["bottom"]
    edges = (abs(t - frame["top"]) <= tol, abs(b - frame["bottom"]) <= tol,
             abs(l - frame["left"]) <= tol, abs(r - frame["right"]) <= tol)
    span_x = abs(r - l) >= abs(frame["right"] - frame["left"]) - tol
    span_y = abs(b - t) >= abs(frame["bottom"] - frame["top"]) - tol
    return (edges[0] and span_x) or (edges[1] and span_x) or \
           (edges[2] and span_y) or (edges[3] and span_y)


def _is_tick(item, frame, cfg):
    pcfg = cfg["pdf"]
    max_len = float(pcfg["tick_max_len_pt"])
    attach = float(pcfg["tick_attach_pt"])
    w = item["right"] - item["left"]
    h = item["bottom"] - item["top"]
    if w > 0.5 and h > 0.5:
        return False
    if max(w, h) > max_len:
        return False
    return (abs(item["bottom"] - frame["bottom"]) <= attach
            or abs(item["top"] - frame["bottom"]) <= attach
            or abs(item["right"] - frame["left"]) <= attach
            or abs(item["left"] - frame["left"]) <= attach
            or abs(item["top"] - frame["top"]) <= attach
            or abs(item["right"] - frame["right"]) <= attach)


def _digitize(points, stride):
    pts = np.asarray(points, dtype=float)
    cols = np.floor(pts[:, 0] / stride).astype(int)
    xs, ys, ymin, ymax = [], [], [], []
    for col in np.unique(cols):
        sel = pts[cols == col, 1]
        xs.append(float(np.mean(pts[cols == col, 0])))
        ys.append(float(np.median(sel)))
        ymin.append(float(np.min(sel)))
        ymax.append(float(np.max(sel)))
    order = np.argsort(xs)
    return ([xs[i] for i in order], [ys[i] for i in order],
            [ymin[i] for i in order], [ymax[i] for i in order])


def build_ir_pdf(path, page_number, cfg):
    """PDF 指定页 → (IR, series_px)。不读位图；换页面用 page_number。语义见 INTERFACE.md §10.5。"""
    pdfplumber = _import_pdfplumber()
    pcfg = cfg["pdf"]
    path = Path(path)
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    try:
        pdf = pdfplumber.open(str(path))
    except Exception as exc:  # noqa: BLE001 — 统一映射到退出码 3
        raise PdfBackendError(f"PDF 打不开：{exc}") from exc
    try:
        if page_number < 1 or page_number > len(pdf.pages):
            raise PdfBackendError(
                f"页号越界：PDF 共 {len(pdf.pages)} 页，请求第 {page_number} 页")
        page = pdf.pages[page_number - 1]
        width, height = float(page.width), float(page.height)
        frame = _frame(page, cfg)
        ticks = _ticks(page, frame, cfg)
        labels = _labels(page, frame, ticks, cfg)

        items = _stroke_points(page)
        frame_ids = {id(it) for it in items if _is_frame_side(it, frame)}
        tick_ids = {id(it) for it in items if _is_tick(it, frame, cfg)}
        margin = float(pcfg["frame_margin_pt"])
        stride = float(pcfg["sample_stride_pt"])
        groups = {}
        for it in items:
            if id(it) in frame_ids or id(it) in tick_ids:
                continue
            if it["color"] is None or _is_light_gray(it["color"], cfg):
                continue
            pts = it["pts"]
            inside = (pts[:, 0] >= frame["left"] + margin) & \
                     (pts[:, 0] <= frame["right"] - margin) & \
                     (pts[:, 1] >= frame["top"] + margin) & \
                     (pts[:, 1] <= frame["bottom"] - margin)
            pts = pts[inside]
            if pts.shape[0] == 0:
                continue
            key = tuple(it["color"])
            groups.setdefault(key, []).append(pts)

        series_px = []
        objects = [{
            "id": "frame",
            "kind": "frame",
            "role": "plot_frame",
            "geometry": {"rect": [frame["left"], frame["top"],
                                  frame["right"], frame["bottom"]]},
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

        min_points = int(pcfg["min_points_per_curve"])
        min_cols = int(pcfg["min_cols_per_curve"])
        for key in sorted(groups):
            pts = np.vstack(groups[key])
            if pts.shape[0] < min_points:
                continue
            xs, ys, ymin, ymax = _digitize(pts, stride)
            if len(xs) < min_cols:
                continue
            name = f"c{len(series_px)}"
            objects.append({
                "id": f"series_{name}",
                "kind": "curve",
                "role": "data",
                "series": name,
                "geometry": {"points_px": [[_round(x), _round(y)]
                                           for x, y in zip(xs, ys)]},
                "style": {"color": list(key), "width_px": 2.0},
            })
            series_px.append({
                "name": name,
                "color": list(key),
                "x_px": [float(v) for v in xs],
                "y_px": [float(v) for v in ys],
                "y_min_px": [float(v) for v in ymin],
                "y_max_px": [float(v) for v in ymax],
            })

        notes = [
            "pdf backend：用矢量路径与文本层（无 OCR），误差不再受位图采样限制",
            "曲线按描边颜色分组；同色多条曲线会合并成一条（本版限制）",
        ]
        ir = {
            "schema": IR_SCHEMA,
            "source": {
                "type": "pdf",
                "path": str(path),
                "sha256": sha,
                "width": _round(width),
                "height": _round(height),
                "backend": PDF_BACKEND,
                "page": int(page_number),
            },
            "canvas": {"width": _round(width), "height": _round(height)},
            "frame": frame,
            "objects": objects,
            "labels": labels,
            "notes": notes,
        }
        return ir, series_px
    finally:
        pdf.close()
