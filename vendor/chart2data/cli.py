"""命令行入口与流程编排。CLI/行为/失败语义见 INTERFACE.md §2、§3、§5、§10。"""
from __future__ import annotations

import argparse
import json
import sys
import time
import traceback
from pathlib import Path

import numpy as np
from PIL import Image

from . import ledger as ledger_mod
from .calib import CalibError
from .detect import FrameNotFound
from .ir import build_ir_raster
from .pdfir import PdfBackendError, build_ir_pdf
from .render import overlay_png, render_ir_svg, render_svg
from .run import RunDir
from .semantic import build_result

PKG_DIR = Path(__file__).resolve().parent
DEFAULT_CONFIG = PKG_DIR / "config.json"


def deep_merge(base, over):
    out = dict(base)
    for key, value in over.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def load_config(path):
    cfg = json.loads(DEFAULT_CONFIG.read_text(encoding="utf-8"))
    if path:
        cfg = deep_merge(cfg, json.loads(Path(path).read_text(encoding="utf-8")))
    return cfg


def load_rgb(path):
    with Image.open(path) as im:
        return np.asarray(im.convert("RGB"), dtype=np.uint8)


def is_pdf(path):
    return Path(path).suffix.lower() == ".pdf"


def build_ir(args, cfg):
    """按扩展名选层 1 前端；返回 (ir, series_px)。语义见 INTERFACE.md §10.5。"""
    if is_pdf(args.image):
        return build_ir_pdf(args.image, int(getattr(args, "page", 1) or 1), cfg)
    return build_ir_raster(load_rgb(args.image), cfg, args.image)


def rasterize_page(path, page_number):
    """PDF 页 → RGB 位图（供叠加校验图/账本指纹）；失败返回 None。语义见 §10.5。"""
    try:
        import pdfplumber
        with pdfplumber.open(str(path)) as pdf:
            page = pdf.pages[int(page_number) - 1]
            return np.asarray(page.to_image(resolution=72).original.convert("RGB"),
                              dtype=np.uint8)
    except Exception:  # noqa: BLE001 — 叠加图是辅助产物，失败只降级不中断
        return None


def load_canvas(args, ir):
    """层 1 后端对应的位图画布：位图输入直接读，PDF 输入按页栅格化。"""
    if is_pdf(args.image):
        return rasterize_page(args.image, ir["source"].get("page", 1))
    try:
        return load_rgb(args.image)
    except Exception:  # noqa: BLE001
        return None


def _ledger_path(cfg):
    p = Path(cfg["ledger"]["path"])
    return p if p.is_absolute() else PKG_DIR / p


def _fmt_list(values):
    return "[" + ", ".join(f"{v:.4g}" for v in values) + "]"


def _out_dir(args, cfg):
    out_dir = Path(args.out or cfg["cli"]["default_out_dir"])
    return out_dir if out_dir.is_absolute() else Path.cwd() / out_dir


def _ticks(ir):
    out = {"x": [], "y": []}
    for obj in ir["objects"]:
        if obj.get("kind") == "tick" and obj.get("axis") in out:
            out[obj["axis"]].append(float(obj["geometry"]["pixel"]))
    for axis in out:
        out[axis].sort()
    return out


def _input_stage(run, args, ir):
    path = Path(args.image).resolve()
    sha = ledger_mod.sha256_file(path)
    src = ir["source"]
    entry = {
        "path": str(path),
        "sha256": sha,
        "bytes": path.stat().st_size,
        "width": src["width"],
        "height": src["height"],
        "type": src["type"],
        "backend": src["backend"],
        "mtime": time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(path.stat().st_mtime)),
    }
    if src.get("page") is not None:
        entry["page"] = src["page"]
    run.start("input")
    run.json("01_input.json", entry)
    return sha


def _write_tables(result, out_dir):
    with open(out_dir / "table.csv", "w", encoding="utf-8") as fh:
        fh.write("series,x,y,y_min,y_max\n")
        for s in result["series"]:
            for xv, yv, lo, hi in zip(s["x"], s["y"], s["y_min"], s["y_max"]):
                fh.write(f"{s['name']},{xv},{yv},{lo},{hi}\n")

    series = result["series"]
    wide_ok = bool(series)
    if wide_ok:
        x0 = series[0]["x"]
        for s in series[1:]:
            if len(s["x"]) != len(x0) or not np.allclose(s["x"], x0, atol=1e-6):
                wide_ok = False
                break
    if wide_ok:
        with open(out_dir / "table_wide.csv", "w", encoding="utf-8") as fh:
            fh.write("x," + ",".join(s["name"] for s in series) + "\n")
            for i, xv in enumerate(series[0]["x"]):
                row = ",".join(str(s["y"][i]) for s in series)
                fh.write(f"{xv},{row}\n")
    return wide_ok


def _report(result, cfg, out_dir, stages, wide_ok):
    name = Path(result["image"]["path"]).stem
    lines = [f"# chart2data 报告 — {name}", ""]
    img = result["image"]
    lines.append(f"- 层1（几何）：`04_ir.json`、`clean.svg`（像素坐标重绘）")
    lines.append(f"- 层2（数据）：`result.json`、`table.csv`、`curve.svg`")
    lines.append(f"- 图：`{img['path']}`（{img['width']}×{img['height']}，"
                 f"sha256 `{img['sha256'][:16]}…`）")
    fr = result["frame"]
    lines.append(f"- 框：left={fr['left']} top={fr['top']} "
                 f"right={fr['right']} bottom={fr['bottom']}")
    for axis in ("x", "y"):
        c = result["calibration"][axis]
        lines.append(f"- 标定 {axis}：{c['scale']}（mode={c['mode']}），"
                     f"像素 {_fmt_list(c['pixels'])} → 值 {_fmt_list(c['values'])}")
    lines.append("")
    lines.append("## 曲线与函数")
    for s in result["series"]:
        hex_color = "#%02x%02x%02x" % tuple(s["color"])
        lines.append("")
        lines.append(f"### {s['name']}（{hex_color}）")
        lines.append(f"- 采样点：{s['n_points']}")
        if s.get("fit"):
            f = s["fit"]
            lines.append(f"- 拟合：{f['model']}；RMSE={f['rmse']:.6g}；R²={f['r2']:.6f}")
            lines.append(f"- 方程：`{f['equation']}`")
        else:
            lines.append("- 拟合：无")
    lines.append("")
    lines.append("## 表格")
    lines.append("- `table.csv`：长表（series,x,y,y_min,y_max）")
    if wide_ok:
        lines.append("- `table_wide.csv`：宽表（各系列 x 对齐时给出）")
    else:
        lines.append("- `table_wide.csv`：未生成（各系列 x 不一致）")
    lines.append("")
    lines.append("## 过程（manifest.json）")
    for st in stages:
        files = "、".join(f["path"] for f in st["files"]) or "（无文件）"
        lines.append(f"- {st['name']}：{files}")
    if result["warnings"]:
        lines.append("")
        lines.append("## 警告")
        for w in result["warnings"]:
            lines.append(f"- {w}")
    lines.append("")
    lines.append("## 产出")
    for fn in ("result.json", "table.csv", "clean.svg", "curve.svg",
               "overlay.png", "manifest.json", "report.md"):
        lines.append(f"- `{out_dir / fn}`")
    return "\n".join(lines) + "\n"


def _write_result_files(result, extras, out_dir, cfg, remember, ledger_path,
                        series_px, run):
    render_ir_svg(extras["ir"], cfg, out_dir / "clean.svg",
                  title=Path(result["image"]["path"]).stem)
    render_svg(result, cfg, out_dir / "curve.svg",
               title=Path(result["image"]["path"]).stem)
    if extras.get("rgb") is not None:
        overlay_png(result, extras, out_dir / "overlay.png")

    (out_dir / "result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    wide_ok = _write_tables(result, out_dir)
    (out_dir / "report.md").write_text(
        _report(result, cfg, out_dir, run.stages, wide_ok), encoding="utf-8")

    if remember and extras.get("rgb") is not None:
        entry = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "sha256": result["image"]["sha256"],
            "dhash": ledger_mod.dhash(extras["rgb"]),
            "path": str(Path(result["image"]["path"]).resolve()),
            "series": [
                {
                    "name": s["name"],
                    "model": (s.get("fit") or {}).get("model"),
                    "equation": (s.get("fit") or {}).get("equation"),
                }
                for s in result["series"]
            ],
            "calib": result["calibration"],
        }
        ledger_mod.append(ledger_path, entry)
    return wide_ok


def cmd_ir(args, cfg):
    out_dir = _out_dir(args, cfg)
    try:
        ir, series_px = build_ir(args, cfg)
    except (PdfBackendError, FrameNotFound):
        raise
    except Exception as exc:  # noqa: BLE001 — 统一映射到退出码 3
        print(f"chart2data: 输入不可读：{exc}", file=sys.stderr)
        return 3

    run = RunDir(out_dir, "ir", cfg)
    _input_stage(run, args, ir)

    run.start("frame")
    run.json("02_frame.json", {"frame": ir["frame"]})
    run.start("ticks")
    run.json("03_ticks.json", _ticks(ir))
    run.start("ir")
    run.json("04_ir.json", ir)
    run.start("render")
    render_ir_svg(ir, cfg, out_dir / "clean.svg",
                  title=Path(args.image).stem)
    run.file("clean.svg")
    run.finish("ok")
    print(f"chart2data: 层1 IR → {out_dir / '04_ir.json'}"
          f"（backend={ir['source']['backend']}，对象 {len(ir['objects'])}，"
          f"曲线 {len(series_px)}，标签 {len(ir['labels'])}）")
    print(f"chart2data: 干净重绘 → {out_dir / 'clean.svg'}")
    return 0


def cmd_extract(args, cfg):
    out_dir = _out_dir(args, cfg)
    try:
        ir, series_px = build_ir(args, cfg)  # FrameNotFound → 退出码 2
    except (PdfBackendError, FrameNotFound):
        raise
    except Exception as exc:  # noqa: BLE001 — 统一映射到退出码 3
        print(f"chart2data: 输入不可读：{exc}", file=sys.stderr)
        return 3

    run = RunDir(out_dir, "extract", cfg)
    _input_stage(run, args, ir)

    run.start("frame")
    run.json("02_frame.json", {"frame": ir["frame"]})
    run.start("ticks")
    run.json("03_ticks.json", _ticks(ir))
    run.start("ir")
    run.json("04_ir.json", ir)

    calib_cfg = None
    if args.calib is not None:
        calib_cfg = json.loads(Path(args.calib).read_text(encoding="utf-8"))
    result = build_result(ir, series_px, calib_cfg, cfg, args.units)

    run.start("calibration")
    run.json("05_calibration.json", result["calibration"])
    run.start("series")
    run.json("06_series.json", [
        {"name": s["name"], "color": s["color"], "n_points": s["n_points"]}
        for s in result["series"]
    ])
    run.start("fit")
    run.json("07_fit.json", [
        {"name": s["name"], "fit": s.get("fit")} for s in result["series"]
    ])

    rgb = load_canvas(args, ir)
    if rgb is None:
        result["warnings"].append("位图画布不可得：overlay.png 与账本指纹跳过")
    extras = {
        "rgb": rgb,
        "ir": ir,
        "overlay_items": [
            {"xs": item["x_px"], "ys": item["y_px"], "color": item["color"]}
            for item in series_px
        ],
    }
    run.start("render")
    wide_ok = _write_result_files(result, extras, out_dir, cfg, args.remember,
                                  _ledger_path(cfg), series_px, run)
    for fn in ("clean.svg", "curve.svg"):
        run.file(fn)
    if rgb is not None:
        run.file("overlay.png")

    run.start("result")
    for fn in ("result.json", "table.csv", "report.md"):
        run.file(fn)
    if wide_ok:
        run.file("table_wide.csv")
    for wmsg in result["warnings"]:
        run.warn(wmsg)
    run.finish("ok")

    frame = result["frame"]
    print(f"chart2data: 框 left={frame['left']} top={frame['top']} "
          f"right={frame['right']} bottom={frame['bottom']}")
    print(f"chart2data: 系列 {len(result['series'])}；输出 {out_dir}")
    for wmsg in result["warnings"]:
        print(f"chart2data: 警告：{wmsg}", file=sys.stderr)
    return 0


def cmd_skeleton(args, cfg):
    try:
        ir, _ = build_ir(args, cfg)
    except (PdfBackendError, FrameNotFound):
        raise
    except Exception as exc:  # noqa: BLE001
        print(f"chart2data: 输入不可读：{exc}", file=sys.stderr)
        return 3
    ticks = _ticks(ir)
    auto = {"x": {}, "y": {}}
    for label in ir["labels"]:
        if label.get("role") == "tick" and label.get("value") is not None:
            auto[label["axis"]].setdefault(round(label["pixel"], 1), label["value"])
    template = {}
    for axis in ("x", "y"):
        pixels = [round(t, 1) for t in ticks[axis]]
        values = [auto[axis].get(p) for p in pixels]
        template[axis] = {
            "scale": "linear",
            "pixels": pixels,
            "values": values if all(v is not None for v in values) and values else None,
        }
    template.update({
        "_frame": ir["frame"],
        "_backend": ir["source"]["backend"],
        "_detected": {"x_ticks": len(ticks["x"]), "y_ticks": len(ticks["y"]),
                      "labels": len(ir["labels"])},
        "_hint": "values 已按文本层刻度标签尽力填好（PDF 输入可免填）；"
                 "位图或标签缺失时手动补。或删掉 pixels、改用 "
                 "values_range:[min,max] 让工具自动配刻度。log 轴改 scale。",
    })
    out = Path(args.out or f"{Path(args.image).stem}.calib.json")
    out.write_text(json.dumps(template, ensure_ascii=False, indent=2) + "\n",
                   encoding="utf-8")
    print(f"chart2data: 框 {ir['frame']}；检出刻度 x={len(ticks['x'])} "
          f"y={len(ticks['y'])}；标签 {len(ir['labels'])} → {out}")
    return 0


def cmd_ledger_find(args, cfg):
    try:
        rgb = load_rgb(args.image)
    except Exception as exc:  # noqa: BLE001
        print(f"chart2data: 输入不可读：{exc}", file=sys.stderr)
        return 3
    sha = ledger_mod.sha256_file(Path(args.image))
    dh = ledger_mod.dhash(rgb)
    ledger_path = _ledger_path(cfg)
    hits = ledger_mod.find(
        ledger_mod.load(ledger_path), sha, dh, int(cfg["ledger"]["phash_max_dist"]))
    print(json.dumps(
        {"ledger": str(ledger_path), "sha256": sha, "dhash": dh, "hits": hits},
        ensure_ascii=False, indent=2))
    return 0


def build_parser():
    parser = argparse.ArgumentParser(prog="chart2data")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_extract = sub.add_parser("extract", help="层1+层2：几何 IR → 数据/函数/表格/干净图")
    p_extract.add_argument("image")
    p_extract.add_argument("-o", "--out", default=None)
    p_extract.add_argument("--calib", default=None)
    p_extract.add_argument("--config", default=None)
    p_extract.add_argument("--remember", action="store_true")
    p_extract.add_argument("--units", choices=["pixel", "data"], default="data")
    p_extract.add_argument("--page", type=int, default=1, help="PDF 页号（默认第 1 页）")

    p_ir = sub.add_parser("ir", help="只跑层1：图 → 几何 IR + 干净重绘 SVG")
    p_ir.add_argument("image")
    p_ir.add_argument("-o", "--out", default=None)
    p_ir.add_argument("--config", default=None)
    p_ir.add_argument("--page", type=int, default=1, help="PDF 页号（默认第 1 页）")

    p_skel = sub.add_parser("skeleton", help="只检框与刻度，出标定模板")
    p_skel.add_argument("image")
    p_skel.add_argument("-o", "--out", default=None)
    p_skel.add_argument("--config", default=None)
    p_skel.add_argument("--page", type=int, default=1, help="PDF 页号（默认第 1 页）")

    p_find = sub.add_parser("ledger-find", help="在账本里找见过没")
    p_find.add_argument("image")
    p_find.add_argument("--config", default=None)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        cfg = load_config(getattr(args, "config", None))
    except Exception as exc:  # noqa: BLE001
        print(f"chart2data: 配置不可读：{exc}", file=sys.stderr)
        return 3
    try:
        if args.cmd == "extract":
            return cmd_extract(args, cfg)
        if args.cmd == "ir":
            return cmd_ir(args, cfg)
        if args.cmd == "skeleton":
            return cmd_skeleton(args, cfg)
        if args.cmd == "ledger-find":
            return cmd_ledger_find(args, cfg)
        print(f"chart2data: 未知命令 {args.cmd}", file=sys.stderr)
        return 3
    except FrameNotFound as exc:
        print(f"chart2data: {exc}", file=sys.stderr)
        return 2
    except PdfBackendError as exc:
        print(f"chart2data: {exc}", file=sys.stderr)
        return 3
    except CalibError as exc:
        print(f"chart2data: 标定非法：{exc}", file=sys.stderr)
        return 4
    except FileNotFoundError as exc:
        print(f"chart2data: 文件不存在：{exc}", file=sys.stderr)
        return 3
    except Exception as exc:  # noqa: BLE001
        print(f"chart2data: 内部错误：{type(exc).__name__}: {exc}", file=sys.stderr)
        traceback.print_exc()
        return 5
