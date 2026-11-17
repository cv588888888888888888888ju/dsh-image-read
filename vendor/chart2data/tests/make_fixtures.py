"""合成图表夹具：已知函数 → 渲染成截图 → 供 round-trip 验收。

生成的图与真值（meta.json）只是测试数据，不是实现的一部分。
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

W, H = 900, 640
LEFT, RIGHT, TOP, BOTTOM = 120, 820, 60, 560
XMIN, XMAX = -6.0, 6.0
YMIN, YMAX = -5.0, 25.0
XS = [-6, -4, -2, 0, 2, 4, 6]
YS = [-5, 0, 5, 10, 15, 20, 25]

BG = (255, 255, 255)
GRID = (176, 176, 176)
INK = (0, 0, 0)
C0 = (31, 119, 180)
C3 = (214, 39, 40)


def mapx(x):
    return LEFT + (x - XMIN) / (XMAX - XMIN) * (RIGHT - LEFT)


def mapy(y):
    return BOTTOM - (y - YMIN) / (YMAX - YMIN) * (BOTTOM - TOP)


def _canvas():
    img = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(img)
    font = ImageFont.load_default()
    for xv in XS:
        px = int(round(mapx(xv)))
        draw.line([(px, TOP), (px, BOTTOM)], fill=GRID, width=1)
    for yv in YS:
        py = int(round(mapy(yv)))
        draw.line([(LEFT, py), (RIGHT, py)], fill=GRID, width=1)
    draw.rectangle([LEFT, TOP, RIGHT, BOTTOM], outline=INK, width=1)
    for xv in XS:
        px = int(round(mapx(xv)))
        draw.line([(px, BOTTOM + 1), (px, BOTTOM + 6)], fill=INK, width=1)
        draw.text((px - 4, BOTTOM + 12), str(xv), fill=INK, font=font)
    for yv in YS:
        py = int(round(mapy(yv)))
        draw.line([(LEFT - 6, py), (LEFT - 1, py)], fill=INK, width=1)
        label = str(yv)
        draw.text((LEFT - 20 - 6 * len(label), py - 5), label, fill=INK, font=font)
    return img, draw


def _curve(draw, fn, color, width=2, n=800):
    xs = np.linspace(XMIN, XMAX, n)
    pts = [(float(mapx(x)), float(mapy(fn(x)))) for x in xs]
    draw.line(pts, fill=color, width=width)


def _meta():
    return {
        "frame": {"left": LEFT, "top": TOP, "right": RIGHT, "bottom": BOTTOM},
        "x": {"pixels": [mapx(v) for v in XS], "values": XS},
        "y": {"pixels": [mapy(v) for v in YS], "values": YS},
        "curves": {
            "c0": {"color": list(C0), "coeffs": [0.25, 1.0, 4.0]},
            "c1": {"color": list(C3), "coeffs": [-1.5, 14.0]},
        },
        "black": {"coeffs": [0.15, 0.6, 3.0]},
    }


def _pdf_bytes():
    """同几何的矢量 PDF（框/刻度/文本层/两条彩色曲线），供 PDF 前端 round-trip。"""
    def fy(py):
        return H - py

    ops = []

    def line(x1, y1, x2, y2, rgb=(0, 0, 0), width=1.0):
        ops.append(
            f"{rgb[0] / 255:.4f} {rgb[1] / 255:.4f} {rgb[2] / 255:.4f} RG "
            f"{width} w {x1:.2f} {fy(y1):.2f} m {x2:.2f} {fy(y2):.2f} l S")

    def text(x, y, s, size=10):
        ops.append(f"0 0 0 rg BT /F1 {size} Tf {x:.2f} {fy(y):.2f} Td ({s}) Tj ET")

    line(LEFT, TOP, RIGHT, TOP)
    line(LEFT, BOTTOM, RIGHT, BOTTOM)
    line(LEFT, TOP, LEFT, BOTTOM)
    line(RIGHT, TOP, RIGHT, BOTTOM)
    for xv in XS:
        px = mapx(xv)
        line(px, BOTTOM, px, BOTTOM + 6)
        text(px - 8, BOTTOM + 18, str(xv))
    for yv in YS:
        py = mapy(yv)
        line(LEFT - 6, py, LEFT, py)
        text(LEFT - 28, py + 4, str(yv))

    xs = np.linspace(XMIN, XMAX, 400)
    for coef, color in (((0.25, 1.0, 4.0), C0), ((-1.5, 14.0), C3)):
        ys = np.polyval(coef, xs)
        pts = [(mapx(x), mapy(y)) for x, y in zip(xs, ys)]
        path = f"{color[0] / 255:.4f} {color[1] / 255:.4f} {color[2] / 255:.4f} RG "
        path += f"2.5 w {pts[0][0]:.2f} {fy(pts[0][1]):.2f} m "
        path += " ".join(f"{p[0]:.2f} {fy(p[1]):.2f} l" for p in pts[1:]) + " S"
        ops.append(path)

    text((LEFT + RIGHT) / 2 - 40, 20, "fixture chart", 14)
    text((LEFT + RIGHT) / 2 - 12, BOTTOM + 40, "time", 12)
    stream = "\n".join(ops)
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {W} {H}] "
         f"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>").encode(),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        (b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n"
         + stream.encode() + b"\nendstream"),
    ]
    out = b"%PDF-1.4\n"
    offs = []
    for i, obj in enumerate(objs, 1):
        offs.append(len(out))
        out += f"{i} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    for off in offs:
        out += f"{off:010d} 00000 n \n".encode()
    out += (f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref}\n%%EOF\n").encode()
    return out


def main(out_dir=None):
    out = Path(out_dir) if out_dir else Path(__file__).resolve().parent / "fixtures"
    out.mkdir(parents=True, exist_ok=True)

    img, draw = _canvas()
    _curve(draw, lambda x: 0.25 * x * x + 1.0 * x + 4.0, C0)
    _curve(draw, lambda x: 14.0 - 1.5 * x, C3)
    img.save(out / "chart.png")
    img.save(out / "chart.jpg", quality=88)

    img2, draw2 = _canvas()
    _curve(draw2, lambda x: 3.0 + 0.6 * x + 0.15 * x * x, INK)
    img2.save(out / "black_curve.png")

    (out / "chart.pdf").write_bytes(_pdf_bytes())

    (out / "meta.json").write_text(
        json.dumps(_meta(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (out / "meta_pdf.json").write_text(
        json.dumps({**_meta(), "backend": "pdf-plumber-v1", "page": 1},
                   ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"fixtures → {out}")
    return out


if __name__ == "__main__":
    main()
