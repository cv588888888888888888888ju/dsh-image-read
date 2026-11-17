"""干净输出：SVG 重绘图与叠加校验图。语义见 INTERFACE.md §3.7。"""
from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw


def _escape(text):
    return (str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def _log_label(v):
    if v > 0:
        e = np.log10(v)
        if abs(e - round(e)) < 1e-9:
            return f"10^{int(round(e))}"
    return f"{v:g}"


def _tick_items(cal, is_log):
    if cal.get("mode") == "pixel" or not cal.get("values"):
        return []
    items = []
    for v in cal["values"]:
        if is_log:
            if v <= 0:
                continue
            items.append((float(np.log10(v)), _log_label(v)))
        else:
            items.append((float(v), f"{v:g}"))
    return items


def _wrap_terms(text, width):
    """按项折行，避免方程在画布右侧被裁掉。"""
    lines, cur = [], ""
    for tok in text.split(" "):
        cand = tok if not cur else cur + " " + tok
        if len(cand) > width and cur:
            lines.append(cur)
            cur = tok
        else:
            cur = cand
    if cur:
        lines.append(cur)
    return lines


def render_svg(result, cfg, out_path, title=None):
    """按数据坐标重绘干净矢量图。语义见 INTERFACE.md §3.7。"""
    r = cfg["render"]
    W, H = int(r["width_px"]), int(r["height_px"])
    padfrac = float(r["padding_frac"])
    has_fit = any(s.get("fit") for s in result["series"])
    mr = 330 if has_fit else 50
    if W - 90 - mr < 220:
        mr = 50
    ml, mt, mb = 90, 60, 80

    cal_x = result["calibration"]["x"]
    cal_y = result["calibration"]["y"]
    logx = cal_x["scale"] == "log"
    logy = cal_y["scale"] == "log"
    tx = (lambda v: float(np.log10(v))) if logx else (lambda v: float(v))
    ty = (lambda v: float(np.log10(v))) if logy else (lambda v: float(v))

    xt = _tick_items(cal_x, logx)
    yt = _tick_items(cal_y, logy)

    xs_all, ys_all = [], []
    for s in result["series"]:
        for xv in s["x"]:
            xs_all.append(tx(xv))
        for yv in s["y"]:
            ys_all.append(ty(yv))
    xvals = xs_all + [t for t, _ in xt]
    yvals = ys_all + [t for t, _ in yt]
    if not xvals:
        xvals = [0.0, 1.0]
    if not yvals:
        yvals = [0.0, 1.0]
    xlo, xhi = min(xvals), max(xvals)
    ylo, yhi = min(yvals), max(yvals)
    if xhi == xlo:
        xhi = xlo + 1.0
    if yhi == ylo:
        yhi = ylo + 1.0
    padx, pady = (xhi - xlo) * padfrac, (yhi - ylo) * padfrac
    xlo, xhi = xlo - padx, xhi + padx
    ylo, yhi = ylo - pady, yhi + pady

    pw, ph = W - ml - mr, H - mt - mb

    def mx(v):
        return ml + (v - xlo) / (xhi - xlo) * pw

    def my(v):
        return H - mb - (v - ylo) / (yhi - ylo) * ph

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
        f'viewBox="0 0 {W} {H}">',
        f'<rect x="0" y="0" width="{W}" height="{H}" fill="#ffffff"/>',
    ]
    for tv, _ in xt:
        x = mx(tv)
        parts.append(f'<line x1="{x:.2f}" y1="{mt}" x2="{x:.2f}" y2="{H - mb}" '
                     f'stroke="#ececec" stroke-width="1"/>')
    for tv, _ in yt:
        y = my(tv)
        parts.append(f'<line x1="{ml}" y1="{y:.2f}" x2="{W - mr}" y2="{y:.2f}" '
                     f'stroke="#ececec" stroke-width="1"/>')
    parts.append(f'<line x1="{ml}" y1="{H - mb}" x2="{W - mr}" y2="{H - mb}" '
                 f'stroke="#333333" stroke-width="1.5"/>')
    parts.append(f'<line x1="{ml}" y1="{mt}" x2="{ml}" y2="{H - mb}" '
                 f'stroke="#333333" stroke-width="1.5"/>')

    for tv, label in xt:
        x = mx(tv)
        parts.append(f'<line x1="{x:.2f}" y1="{H - mb}" x2="{x:.2f}" y2="{H - mb + 6}" '
                     f'stroke="#333333" stroke-width="1"/>')
        parts.append(f'<text x="{x:.2f}" y="{H - mb + 22}" font-family="monospace" '
                     f'font-size="12" text-anchor="middle" fill="#333333">{_escape(label)}</text>')
    for tv, label in yt:
        y = my(tv)
        parts.append(f'<line x1="{ml - 6}" y1="{y:.2f}" x2="{ml}" y2="{y:.2f}" '
                     f'stroke="#333333" stroke-width="1"/>')
        parts.append(f'<text x="{ml - 10}" y="{y + 4:.2f}" font-family="monospace" '
                     f'font-size="12" text-anchor="end" fill="#333333">{_escape(label)}</text>')

    for s in result["series"]:
        color = "#%02x%02x%02x" % tuple(s["color"])
        pts = " ".join(
            f"{mx(tx(xv)):.2f},{my(ty(yv)):.2f}" for xv, yv in zip(s["x"], s["y"]))
        parts.append(f'<polyline fill="none" stroke="{color}" stroke-width="2" '
                     f'points="{pts}"/>')

    sx, sy = W - mr + 24, mt + 2
    for s in result["series"]:
        color = "#%02x%02x%02x" % tuple(s["color"])
        parts.append(f'<rect x="{sx}" y="{sy + 4:.2f}" width="14" height="4" fill="{color}"/>')
        parts.append(f'<text x="{sx + 22}" y="{sy + 9:.2f}" font-family="sans-serif" '
                     f'font-size="12" font-weight="600" fill="#111111">'
                     f'{_escape(s["name"])}</text>')
        sy += 17
        if s.get("fit"):
            for line in _wrap_terms(s["fit"]["equation"], 38):
                parts.append(f'<text x="{sx + 22}" y="{sy + 8:.2f}" '
                             f'font-family="monospace" font-size="11" fill="#333333">'
                             f'{_escape(line)}</text>')
                sy += 14
        sy += 12

    title_text = title if title else Path(result["image"]["path"]).name
    parts.append(f'<text x="{ml}" y="{mt - 24}" font-family="sans-serif" '
                 f'font-size="15" fill="#111111">{_escape(title_text)}</text>')
    parts.append("</svg>")
    Path(out_path).write_text("\n".join(parts) + "\n", encoding="utf-8")


def render_ir_svg(ir, cfg, out_path, title=None):
    """层 1：按 IR 几何重绘的干净矢量图（像素坐标，不含数据语义）。语义见 INTERFACE.md §10.1。"""
    r = cfg["render"]
    W = int(r["width_px"])
    src_w = float(ir["source"]["width"])
    src_h = float(ir["source"]["height"])
    scale = W / src_w
    H = int(round(src_h * scale))
    pad = 40
    cw, ch = W + 2 * pad, H + 2 * pad

    def mx(px):
        return pad + float(px) * scale

    def my(py):
        return pad + float(py) * scale

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{cw}" height="{ch}" '
        f'viewBox="0 0 {cw} {ch}">',
        f'<rect x="0" y="0" width="{cw}" height="{ch}" fill="#ffffff"/>',
    ]
    frame = ir.get("frame")
    if frame:
        parts.append(
            f'<rect x="{mx(frame["left"]):.2f}" y="{my(frame["top"]):.2f}" '
            f'width="{(frame["right"] - frame["left"]) * scale:.2f}" '
            f'height="{(frame["bottom"] - frame["top"]) * scale:.2f}" '
            f'fill="none" stroke="#888888" stroke-width="1"/>')
    for obj in ir["objects"]:
        if obj.get("kind") == "tick" and frame:
            p = mx(obj["geometry"]["pixel"]) if obj["axis"] == "x" \
                else my(obj["geometry"]["pixel"])
            if obj["axis"] == "x":
                parts.append(f'<line x1="{p:.2f}" y1="{my(frame["bottom"]):.2f}" '
                             f'x2="{p:.2f}" y2="{my(frame["bottom"]) + 6:.2f}" '
                             f'stroke="#666666" stroke-width="1"/>')
            else:
                parts.append(f'<line x1="{mx(frame["left"]) - 6:.2f}" y1="{p:.2f}" '
                             f'x2="{mx(frame["left"]):.2f}" y2="{p:.2f}" '
                             f'stroke="#666666" stroke-width="1"/>')
    for obj in ir["objects"]:
        if obj.get("kind") == "curve":
            color = "#%02x%02x%02x" % tuple(obj["style"]["color"] or (0, 0, 0))
            pts = " ".join(f"{mx(x):.2f},{my(y):.2f}" for x, y in obj["geometry"]["points_px"])
            parts.append(f'<polyline fill="none" stroke="{color}" stroke-width="1.6" '
                         f'points="{pts}"/>')
    title_text = title or Path(ir["source"]["path"]).name
    parts.append(f'<text x="{pad}" y="22" font-family="sans-serif" font-size="14" '
                 f'fill="#111111">{_escape(title_text)}（层1：像素坐标几何）</text>')
    parts.append("</svg>")
    Path(out_path).write_text("\n".join(parts) + "\n", encoding="utf-8")


def overlay_png(result, extras, out_path):
    """原图 + 框 + 采样点，供人眼校验。语义见 INTERFACE.md §3.7。"""
    rgb = extras["rgb"].copy()
    img = Image.fromarray(rgb)
    draw = ImageDraw.Draw(img)
    fr = result["frame"]
    draw.rectangle([fr["left"], fr["top"], fr["right"], fr["bottom"]],
                   outline=(0, 190, 0), width=2)
    for item in extras["overlay_items"]:
        color = tuple(int(v) for v in item["color"])
        if color == (0, 0, 0):
            color = (255, 0, 255)  # 黑线在图上不可见，校验时换品红
        for x, y in zip(item["xs"], item["ys"]):
            draw.ellipse([x - 2, y - 2, x + 2, y + 2], fill=color)
    img.save(out_path)
