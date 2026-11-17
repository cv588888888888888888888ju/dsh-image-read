"""机械验收：合成夹具 round-trip + 失败语义 + 账本。

判据值在 tests/test_config.json；语义见 INTERFACE.md §2、§5、§6、§7。
运行：python -m chart2data.tests.acceptance
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image

PKG = Path(__file__).resolve().parent.parent
ROOT = PKG.parent
FIX = PKG / "tests" / "fixtures"
CFG = json.loads((PKG / "tests" / "test_config.json").read_text(encoding="utf-8"))
META = json.loads((FIX / "meta.json").read_text(encoding="utf-8"))

FAILS = []


def ok(name, cond, detail=""):
    print(("PASS  " if cond else "FAIL  ") + name + (f"  [{detail}]" if detail else ""))
    if not cond:
        FAILS.append(name)


def run(args, cwd=ROOT):
    proc = subprocess.run([sys.executable, "-m", "chart2data", *args],
                          cwd=cwd, capture_output=True, text=True)
    return proc.returncode, proc.stdout, proc.stderr


def load_result(out_dir):
    return json.loads((Path(out_dir) / "result.json").read_text(encoding="utf-8"))


def true_value(coeffs, x):
    return np.polyval(np.asarray(coeffs, dtype=np.float64),
                      np.asarray(x, dtype=np.float64))


def match_series(result, coeffs, xmin, xmax):
    """按中点误差把提取系列配到一条真值曲线上。返回 (series | None, err)。"""
    best, best_err = None, float("inf")
    for s in result["series"]:
        if not s.get("fit"):
            continue
        xs = np.linspace(xmin, xmax, 41)
        err = float(np.max(np.abs(np.polyval(s["fit"]["coeffs"], xs)
                                  - true_value(coeffs, xs))))
        if err < best_err:
            best, best_err = s, err
    return best, best_err


def sample_err(series, coeffs):
    x = np.asarray(series["x"], dtype=np.float64)
    y = np.asarray(series["y"], dtype=np.float64)
    lo, hi = float(META["x"]["values"][0]), float(META["x"]["values"][-1])
    m = (x >= lo + 0.05) & (x <= hi - 0.05)
    return float(np.max(np.abs(y[m] - true_value(coeffs, x[m]))))


def calib_file(tmp):
    cal = {"x": {"scale": "linear", "pixels": META["x"]["pixels"],
                 "values": META["x"]["values"]},
           "y": {"scale": "linear", "pixels": META["y"]["pixels"],
                 "values": META["y"]["values"]}}
    p = Path(tmp) / "fixture.calib.json"
    p.write_text(json.dumps(cal), encoding="utf-8")
    return str(p)


def test_skeleton(tmp):
    code, out, err = run(["skeleton", str(FIX / "chart.png"),
                          "-o", str(Path(tmp) / "skel.json")])
    ok("skeleton 退出码 0", code == 0, err.strip()[-120:])
    tmpl = json.loads((Path(tmp) / "skel.json").read_text(encoding="utf-8"))
    f = tmpl["_frame"]
    exp = META["frame"]
    tol = CFG["frame_tolerance_px"]
    ok("skeleton 框位置", all(abs(f[k] - exp[k]) <= tol for k in exp),
       f"{f} vs {exp}")
    ok("skeleton 刻度数", tmpl["_detected"]["x_ticks"] >= CFG["ticks_min_each"]
       and tmpl["_detected"]["y_ticks"] >= CFG["ticks_min_each"],
       json.dumps(tmpl["_detected"]))


def test_png_roundtrip(tmp):
    out = Path(tmp) / "png"
    code, _, err = run(["extract", str(FIX / "chart.png"), "--calib", calib_file(tmp),
                        "-o", str(out)])
    ok("extract(png) 退出码 0", code == 0, err.strip()[-120:])
    r = load_result(out)
    ok("extract(png) 系列数=2", len(r["series"]) == 2, str(len(r["series"])))
    for name, spec in META["curves"].items():
        coeffs = spec["coeffs"]
        s, err_fit = match_series(r, coeffs, -5.5, 5.5)
        ok(f"{name} 拟合式误差", s is not None and err_fit <= CFG["png_max_abs_fit_err"],
           f"{err_fit:.4f}")
        if s is None:
            continue
        s_err = sample_err(s, coeffs)
        ok(f"{name} 采样点误差", s_err <= CFG["sample_max_abs_y_err"],
           f"{s_err:.4f}")
        n = len(coeffs) - 1
        c = np.asarray(s["fit"]["coeffs"], dtype=np.float64)
        ok(f"{name} 阶数={n}", s["fit"]["model"] == f"poly{n}", s["fit"]["model"])
        ok(f"{name} 系数误差", float(np.max(np.abs(c - np.asarray(coeffs))))
           <= CFG["max_abs_coeff_err"], str([round(float(v), 4) for v in c]))
    for fn in ("04_ir.json", "01_input.json", "02_frame.json", "03_ticks.json",
               "05_calibration.json", "06_series.json", "07_fit.json",
               "clean.svg", "curve.svg", "overlay.png", "report.md",
               "table.csv", "manifest.json"):
        p = out / fn
        ok(f"产出存在 {fn}", p.is_file() and p.stat().st_size > 0)
    svg = (out / "curve.svg").read_text(encoding="utf-8")
    ok("curve.svg 有折线", svg.count("<polyline") >= 2, str(svg.count("<polyline")))
    report = (out / "report.md").read_text(encoding="utf-8")
    ok("report.md 含方程", "方程" in report and "poly" in report)


def test_two_layers(tmp):
    out = Path(tmp) / "layer1"
    code, _, err = run(["ir", str(FIX / "chart.png"), "-o", str(out)])
    ok("ir 退出码 0", code == 0, err.strip()[-120:])
    man = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    ok("manifest command=ir", man.get("command") == "ir", str(man.get("command")))
    ok("manifest schema", man.get("schema") == "chart2data/manifest@1")
    ok("manifest 阶段", [st["name"] for st in man["stages"]]
       == ["input", "frame", "ticks", "ir", "render"], str([s["name"] for s in man["stages"]]))
    ok("manifest 有 config sha", isinstance(man.get("config_sha256"), str)
       and len(man["config_sha256"]) == 64)
    import hashlib
    f = man["stages"][0]["files"][0]
    ok("manifest 记录 sha256", hashlib.sha256((out / f["path"]).read_bytes()).hexdigest()
       == f["sha256"], f["path"])
    ir = json.loads((out / "04_ir.json").read_text(encoding="utf-8"))
    ok("IR schema", ir["schema"] == "chart2data/ir@1", ir["schema"])
    ok("IR source backend", ir["source"]["backend"] == "raster-v1")
    kinds = [o["kind"] for o in ir["objects"]]
    ok("IR 有框/刻度/曲线", kinds.count("frame") == 1
       and kinds.count("tick") >= 2 * CFG["ticks_min_each"]
       and kinds.count("curve") == len(META["curves"]), str({k: kinds.count(k) for k in set(kinds)}))
    ok("IR 曲线带像素点", all(o["geometry"].get("points_px") for o in ir["objects"]
                             if o["kind"] == "curve"))
    svg = (out / "clean.svg").read_text(encoding="utf-8")
    ok("clean.svg 由 IR 重绘", svg.count("<polyline") == len(META["curves"]),
       str(svg.count("<polyline")))
    ok("clean.svg 是像素空间", "层1" in svg)

    # 层2 只消费 IR：extract 的 IR 与单独 ir 的结果一致（同一图）
    out2 = Path(tmp) / "png"
    r = load_result(out2)
    ir2 = json.loads((out2 / "04_ir.json").read_text(encoding="utf-8"))
    ok("两层衔接：曲线名一致",
       [o["series"] for o in ir2["objects"] if o["kind"] == "curve"]
       == [s["name"] for s in r["series"]])


def test_pdf(tmp):
    """PDF 前端：矢量+文本层 round-trip、标签、skeleton 自动填值、页号失败语义。"""
    meta_pdf = json.loads((FIX / "meta_pdf.json").read_text(encoding="utf-8"))
    out = Path(tmp) / "pdf_ir"
    code, _, err = run(["ir", str(FIX / "chart.pdf"), "-o", str(out)])
    ok("ir(pdf) 退出码 0", code == 0, err.strip()[-160:])
    if code != 0:
        return
    ir = json.loads((out / "04_ir.json").read_text(encoding="utf-8"))
    ok("pdf IR backend", ir["source"]["backend"] == meta_pdf["backend"],
       ir["source"]["backend"])
    ok("pdf IR source type/page", ir["source"]["type"] == "pdf"
       and ir["source"].get("page") == meta_pdf["page"])
    exp = meta_pdf["frame"]
    tol = CFG["frame_tolerance_px"]
    ok("pdf 框位置", all(abs(ir["frame"][k] - exp[k]) <= tol for k in exp), str(ir["frame"]))
    kinds = [o["kind"] for o in ir["objects"]]
    ok("pdf IR 有框/刻度/曲线", kinds.count("frame") == 1
       and kinds.count("tick") == 2 * len(meta_pdf["x"]["values"])
       and kinds.count("curve") == len(meta_pdf["curves"]),
       str({k: kinds.count(k) for k in set(kinds)}))
    ticks = {"x": [], "y": []}
    for o in ir["objects"]:
        if o["kind"] == "tick":
            ticks[o["axis"]].append(o["geometry"]["pixel"])
    ok("pdf 刻度位置",
       np.allclose(ticks["x"], meta_pdf["x"]["pixels"], atol=0.5)
       and np.allclose(sorted(ticks["y"]), sorted(meta_pdf["y"]["pixels"]), atol=0.5),
       json.dumps(ticks))

    roles = {l["role"] for l in ir["labels"]}
    ok("pdf 标签角色齐全", {"title", "xlabel", "tick"} <= roles, str(roles))
    tick_vals = {round(l["value"], 6) for l in ir["labels"] if l.get("role") == "tick"}
    ok("pdf 刻度值来自文本层", set(meta_pdf["x"]["values"]) | set(meta_pdf["y"]["values"])
       <= tick_vals, str(sorted(tick_vals)))

    skel = Path(tmp) / "pdf_skel.json"
    code, _, err = run(["skeleton", str(FIX / "chart.pdf"), "-o", str(skel)])
    ok("skeleton(pdf) 退出码 0", code == 0, err.strip()[-160:])
    tmpl = json.loads(skel.read_text(encoding="utf-8"))
    def expected_values(axis):
        pix = meta_pdf[axis]["pixels"]
        vals = meta_pdf[axis]["values"]
        return {round(p, 1): v for p, v in zip(pix, vals)}
    exp_vals = {"x": expected_values("x"), "y": expected_values("y")}
    ok("pdf skeleton 自动填刻度值",
       [round(v, 6) for v in tmpl["x"]["values"]]
       == [exp_vals["x"][round(p, 1)] for p in tmpl["x"]["pixels"]]
       and [round(v, 6) for v in tmpl["y"]["values"]]
       == [exp_vals["y"][round(p, 1)] for p in tmpl["y"]["pixels"]],
       json.dumps({"x": tmpl["x"]["values"], "y": tmpl["y"]["values"]}))

    out2 = Path(tmp) / "pdf_extract"
    code, _, err = run(["extract", str(FIX / "chart.pdf"), "--calib", str(skel),
                        "-o", str(out2)])
    ok("extract(pdf) 退出码 0", code == 0, err.strip()[-160:])
    r = load_result(out2)
    ok("extract(pdf) 系列数=2", len(r["series"]) == 2, str(len(r["series"])))
    for name, spec in meta_pdf["curves"].items():
        coeffs = spec["coeffs"]
        s, fit_err = match_series(r, coeffs, -5.5, 5.5)
        ok(f"pdf {name} 拟合式误差", s is not None
           and fit_err <= CFG["pdf_max_abs_fit_err"], f"{fit_err:.5f}")
        if s is None:
            continue
        ok(f"pdf {name} 系数误差",
           float(np.max(np.abs(np.asarray(s["fit"]["coeffs"]) - np.asarray(coeffs))))
           <= CFG["pdf_max_abs_coeff_err"],
           str([round(float(v), 5) for v in s["fit"]["coeffs"]]))
    if (out2 / "overlay.png").is_file():
        ok("pdf overlay 有栅格化页面", (out2 / "overlay.png").stat().st_size > 0)
    man = json.loads((out2 / "manifest.json").read_text(encoding="utf-8"))
    ok("pdf manifest 记录 backend",
       json.loads((out2 / "01_input.json").read_text(encoding="utf-8"))["backend"]
       == "pdf-plumber-v1")

    code, _, err = run(["extract", str(FIX / "chart.pdf"), "--page", "9"])
    ok("pdf 页号越界 → 3", code == 3, str(code))
    ok("pdf 页号越界 stderr 有提示", "页号越界" in err, err.strip()[-120:])


def test_jpeg(tmp):
    out = Path(tmp) / "jpg"
    code, _, err = run(["extract", str(FIX / "chart.jpg"), "--calib", calib_file(tmp),
                        "-o", str(out)])
    ok("extract(jpg) 退出码 0", code == 0, err.strip()[-120:])
    r = load_result(out)
    ok("extract(jpg) 无多余系列", len(r["series"]) == 2, str(len(r["series"])))
    for name, spec in META["curves"].items():
        coeffs = spec["coeffs"]
        s, _ = match_series(r, coeffs, -5.5, 5.5)
        if s is None:
            ok(f"jpg {name} 找到", False)
            continue
        ok(f"jpg {name} 采样点误差", sample_err(s, coeffs) <= CFG["jpg_sample_max_abs_y_err"])


def test_black(tmp):
    out = Path(tmp) / "black"
    coeffs = META["black"]["coeffs"]
    code, _, err = run(["extract", str(FIX / "black_curve.png"),
                        "--calib", calib_file(tmp), "-o", str(out)])
    ok("extract(black) 退出码 0", code == 0, err.strip()[-120:])
    r = load_result(out)
    ok("extract(black) 系列数=1", len(r["series"]) == 1, str(len(r["series"])))
    s, err_fit = match_series(r, coeffs, -5.5, 5.5)
    ok("black 拟合式误差", s is not None and err_fit <= CFG["black_max_abs_fit_err"],
       f"{err_fit:.4f}")


def test_pixel_mode(tmp):
    out = Path(tmp) / "px"
    code, _, err = run(["extract", str(FIX / "chart.png"), "-o", str(out)])
    ok("pixel 模式退出码 0", code == 0, err.strip()[-120:])
    r = load_result(out)
    cx = r["calibration"]["x"]
    exp = META["frame"]
    ok("pixel 模式 x 用列号", cx["mode"] == "pixel"
       and cx["values"][0] == exp["left"] and cx["values"][1] == exp["right"],
       json.dumps(cx))
    s = r["series"][0]
    ok("pixel 模式 x 采样落在框内",
       all(exp["left"] + 2 <= v <= exp["right"] - 2 for v in s["x"]))
    ok("pixel 模式有未标定警告", any("未标定" in w for w in r["warnings"]))


def test_ledger(tmp):
    ledger = Path(tmp) / "ledger.jsonl"
    cfg = Path(tmp) / "ledger.cfg.json"
    cfg.write_text(json.dumps({"ledger": {"path": str(ledger)}}), encoding="utf-8")
    out = Path(tmp) / "remember"
    code, _, err = run(["extract", str(FIX / "chart.png"), "--calib", calib_file(tmp),
                        "--remember", "--config", str(cfg), "-o", str(out)])
    ok("remember 退出码 0", code == 0, err.strip()[-120:])
    ok("账本已写入", ledger.is_file() and len(ledger.read_text().strip().splitlines()) == 1)
    code, out_s, err = run(["ledger-find", str(FIX / "chart.png"), "--config", str(cfg)])
    found = json.loads(out_s)
    ok("ledger-find 退出码 0", code == 0, err.strip()[-120:])
    ok("ledger-find 命中", len(found["hits"]) >= 1, str(len(found["hits"])))
    ok("ledger-find 按 sha256 命中",
       any(h.get("sha256") == found["sha256"] for h in found["hits"]))


def test_failures(tmp):
    code, _, _ = run(["extract", str(Path(tmp) / "missing.png")])
    ok("缺文件 → 3", code == 3, str(code))

    blank = Path(tmp) / "blank.png"
    Image.new("RGB", (400, 300), (255, 255, 255)).save(blank)
    code, _, err = run(["extract", str(blank)])
    ok("无框 → 2", code == 2, str(code))
    ok("无框 stderr 有提示", "未检出绘图框" in err)

    bad = Path(tmp) / "bad.calib.json"
    bad.write_text(json.dumps({"x": {"pixels": [1, 2], "values": [1]}}),
                   encoding="utf-8")
    code, _, _ = run(["extract", str(FIX / "chart.png"), "--calib", str(bad)])
    ok("标定长度不一致 → 4", code == 4, str(code))

    bad2 = Path(tmp) / "bad2.calib.json"
    bad2.write_text(json.dumps({"x": {"scale": "bogus", "pixels": [1, 2],
                                      "values": [1, 2]}}), encoding="utf-8")
    code, _, _ = run(["extract", str(FIX / "chart.png"), "--calib", str(bad2)])
    ok("未知 scale → 4", code == 4, str(code))

    code, _, _ = run(["nope"])
    ok("未知子命令 → argparse 2", code == 2, str(code))


def test_schema(tmp):
    out = Path(tmp) / "png"
    r = load_result(out)
    ok("schema 名", r["schema"] == "chart2data/result@1", r["schema"])
    ok("image 有 sha256", isinstance(r["image"].get("sha256"), str)
       and len(r["image"]["sha256"]) == 64)
    ok("frame 四边", set(r["frame"]) >= {"left", "top", "right", "bottom"})
    s = r["series"][0]
    ok("series 字段", {"name", "color", "n_points", "x", "y", "fit"} <= set(s))
    ok("fit 字段", {"model", "coeffs", "rmse", "r2", "equation"} <= set(s["fit"]))
    ok("result 有层2标签", "层" in (out / "report.md").read_text(encoding="utf-8"))
    ok("坐标长度一致", len(s["x"]) == len(s["y"]) == s["n_points"])


def main():
    if not (FIX / "meta.json").is_file():
        print("fixtures 缺失，先跑 python -m chart2data.tests.make_fixtures")
        return 1
    tmpdir = tempfile.mkdtemp(prefix="c2d_accept_")
    test_skeleton(tmpdir)
    test_png_roundtrip(tmpdir)
    test_two_layers(tmpdir)
    test_pdf(tmpdir)
    test_jpeg(tmpdir)
    test_black(tmpdir)
    test_pixel_mode(tmpdir)
    test_ledger(tmpdir)
    test_failures(tmpdir)
    test_schema(tmpdir)
    print()
    if FAILS:
        print(f"失败 {len(FAILS)} 项：" + ", ".join(FAILS))
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
