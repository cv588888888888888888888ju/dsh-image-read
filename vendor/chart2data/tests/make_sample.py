"""生成一张「像真实截图」的示例图（带标题/轴标签/刻度数字/框外图例）。

用途：冒烟与演示；不参与验收判据（验收用 make_fixtures.py 的可控夹具）。
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

W, H = 1000, 700
LEFT, RIGHT, TOP, BOTTOM = 130, 940, 70, 600
XMIN, XMAX = 0.0, 14.0
YMIN, YMAX = 0.0, 1000.0
XS = list(range(0, 15, 2))
YS = list(range(0, 1001, 200))

FONT_DIR = Path("/usr/share/fonts/liberation-sans-fonts")
BG = (250, 250, 250)
GRID = (218, 218, 218)
INK = (40, 40, 40)
SERIES = [
    ("v1.8", (31, 119, 180), lambda x: 120 + 42 * x),
    ("v1.9", (255, 127, 14), lambda x: 60 + 22 * x + 2.1 * x * x),
    ("v2.0", (44, 160, 44), lambda x: 900 - 55 * x + 2.2 * x * x),
]


def mapx(x):
    return LEFT + (x - XMIN) / (XMAX - XMIN) * (RIGHT - LEFT)


def mapy(y):
    return BOTTOM - (y - YMIN) / (YMAX - YMIN) * (BOTTOM - TOP)


def _font(size):
    for name in ("LiberationSans-Regular.ttf", "DejaVuSans.ttf"):
        p = FONT_DIR / name
        if p.is_file():
            return ImageFont.truetype(str(p), size)
    return ImageFont.load_default()


def main(out_dir=None):
    out = Path(out_dir) if out_dir else Path(__file__).resolve().parent / "fixtures"
    out.mkdir(parents=True, exist_ok=True)
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    f_tick, f_label, f_title = _font(13), _font(15), _font(19)

    for xv in XS:
        d.line([(mapx(xv), BOTTOM), (mapx(xv), TOP)], fill=GRID, width=1)
    for yv in YS:
        d.line([(LEFT, mapy(yv)), (RIGHT, mapy(yv))], fill=GRID, width=1)
    d.rectangle([LEFT, TOP, RIGHT, BOTTOM], outline=INK, width=2)

    for xv in XS:
        px = mapx(xv)
        d.line([(px, BOTTOM + 1), (px, BOTTOM + 6)], fill=INK, width=1)
        txt = str(xv)
        w = d.textlength(txt, font=f_tick)
        d.text((px - w / 2, BOTTOM + 10), txt, fill=INK, font=f_tick)
    for yv in YS:
        py = mapy(yv)
        d.line([(LEFT - 6, py), (LEFT - 1, py)], fill=INK, width=1)
        txt = str(yv)
        w = d.textlength(txt, font=f_tick)
        d.text((LEFT - 12 - w, py - 7), txt, fill=INK, font=f_tick)

    title = "Daily downloads by release channel"
    tw = d.textlength(title, font=f_title)
    d.text(((LEFT + RIGHT) / 2 - tw / 2, 22), title, fill=INK, font=f_title)
    xlabel = "day"
    d.text(((LEFT + RIGHT) / 2 - d.textlength(xlabel, font=f_label) / 2, BOTTOM + 40),
           xlabel, fill=INK, font=f_label)
    ylabel = "downloads / day"
    yimg = Image.new("RGBA", (200, 24), (0, 0, 0, 0))
    yd = ImageDraw.Draw(yimg)
    yd.text((0, 0), ylabel, fill=INK, font=f_label)
    yimg = yimg.rotate(90, expand=True)
    img.paste(yimg, (30, int((TOP + BOTTOM) / 2 - yimg.height / 2)), yimg)

    xs = np.linspace(XMIN, XMAX, 600)
    for name, color, fn in SERIES:
        d.line([(float(mapx(x)), float(mapy(fn(x)))) for x in xs],
               fill=color, width=3)

    lx, ly = LEFT + 10, BOTTOM + 62
    for name, color, _ in SERIES:
        d.line([(lx, ly + 7), (lx + 26, ly + 7)], fill=color, width=3)
        d.text((lx + 32, ly), name, fill=INK, font=f_tick)
        lx += 120

    img.save(out / "sample_plot.png")
    calib = {"x": {"scale": "linear", "pixels": [mapx(v) for v in XS], "values": XS},
             "y": {"scale": "linear", "pixels": [mapy(v) for v in YS], "values": YS}}
    (out / "sample_plot.calib.json").write_text(
        json.dumps(calib, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    meta = {"frame": {"left": LEFT, "top": TOP, "right": RIGHT, "bottom": BOTTOM},
            "series": [{"name": n, "color": list(c)} for n, c, _ in SERIES],
            "x": {"pixels": [mapx(v) for v in XS], "values": XS},
            "y": {"pixels": [mapy(v) for v in YS], "values": YS}}
    (out / "sample_plot.meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"sample → {out / 'sample_plot.png'}")


if __name__ == "__main__":
    main()
