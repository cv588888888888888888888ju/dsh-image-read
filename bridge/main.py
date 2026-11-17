#!/usr/bin/env python3
"""dsh-image-read 的 Python 桥：确定性几何读取。

契约（参数 / 返回 / 错误码）：见 INTERFACE.md §3。可调值：见 img.config.json。
"""
from __future__ import annotations

import json
import math
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path


def err(code: str, message: str, **extra) -> dict:
    return {"ok": False, "error": {"code": code, "message": message, **extra}}


def sanitize(value):
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, list):
        return [sanitize(item) for item in value]
    if isinstance(value, dict):
        return {key: sanitize(item) for key, item in value.items()}
    return value


def chart_read(cfg: dict, args: dict) -> dict:
    started = time.time()
    image = Path(str(args.get("image") or ""))
    if not image.is_file():
        return err("E_INPUT", f"图片不存在: {image}")

    root = Path(str(cfg.get("chart2dataRoot") or ""))
    if not (root / "__init__.py").is_file():
        return err("E_DEP", f"chart2dataRoot 不是 chart2data 包目录: {root}")

    raw_out = args.get("out")
    if raw_out:
        out_dir = Path(str(raw_out))
    else:
        out_dir = Path(str(cfg.get("workDir") or "/tmp/dsh-image-read")) / (
            f"chart-{int(time.time())}-{uuid.uuid4().hex[:6]}"
        )
    out_dir.mkdir(parents=True, exist_ok=True)

    cmd = [sys.executable, "-m", "chart2data", "extract", str(image), "-o", str(out_dir)]
    if args.get("calib"):
        calib = Path(str(args["calib"]))
        if not calib.is_file():
            return err("E_INPUT", f"标定文件不存在: {calib}")
        cmd += ["--calib", str(calib)]

    env = dict(os.environ)
    env["PYTHONPATH"] = str(root.parent)
    env["PYTHONIOENCODING"] = "utf-8"
    timeout_s = float(cfg.get("timeoutMs") or 120000) / 1000.0
    try:
        proc = subprocess.run(
            cmd, cwd=str(root.parent), env=env, capture_output=True, text=True, timeout=timeout_s
        )
    except subprocess.TimeoutExpired:
        return err("E_TIMEOUT", f"chart2data 超过 {timeout_s:.0f}s 未结束")
    if proc.returncode != 0:
        return err(
            "E_CHART2DATA",
            "chart2data 抽取失败",
            rc=proc.returncode,
            stderr=(proc.stderr or "")[-1500:],
        )

    result_path = out_dir / "result.json"
    if not result_path.is_file():
        return err("E_OUTPUT", f"chart2data 未产出 result.json: {out_dir}")
    data = json.loads(result_path.read_text("utf-8"))

    preview_n = int((cfg.get("chart") or {}).get("previewPoints") or 40)
    include_full = bool(args.get("include_points") or False)
    series = []
    for item in data.get("series") or []:
        xs = item.get("x") or []
        ys = item.get("y") or []
        step = max(1, len(xs) // preview_n) if preview_n > 0 else 1
        preview = [
            [round(float(xs[i]), 3), round(float(ys[i]), 3)]
            for i in range(0, len(xs), step)
        ][:preview_n]
        entry = {
            "name": item.get("name"),
            "color": item.get("color"),
            "n_points": item.get("n_points"),
            "fit": item.get("fit"),
            "points_preview": preview,
        }
        if include_full:
            entry["x"] = xs
            entry["y"] = ys
        series.append(entry)

    artifact_names = {
        "result_json": "result.json",
        "table_csv": "table.csv",
        "table_wide_csv": "table_wide.csv",
        "curve_svg": "curve.svg",
        "clean_svg": "clean.svg",
        "overlay_png": "overlay.png",
        "report_md": "report.md",
        "manifest_json": "manifest.json",
    }
    artifacts = {
        key: str(out_dir / name)
        for key, name in artifact_names.items()
        if (out_dir / name).is_file()
    }

    return {
        "ok": True,
        "schema": data.get("schema"),
        "image": data.get("image"),
        "frame": data.get("frame"),
        "calibration": data.get("calibration"),
        "series": series,
        "warnings": data.get("warnings") or [],
        "artifacts": artifacts,
        "elapsed_ms": int((time.time() - started) * 1000),
    }


def _load_rgba(path: Path):
    import cv2

    image = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
    if image is None:
        raise ValueError(f"读不到图片: {path}")
    if image.ndim == 2:
        image = cv2.cvtColor(image, cv2.COLOR_GRAY2BGRA)
    if image.shape[2] == 3:
        image = cv2.cvtColor(image, cv2.COLOR_BGR2BGRA)
        image[:, :, 3] = 255
    return image


def _slider_profile(slider):
    import cv2
    import numpy as np

    alpha = slider[:, :, 3]
    gray = cv2.cvtColor(slider[:, :, :3], cv2.COLOR_BGR2GRAY)
    edge = cv2.Canny(gray, 30, 90) | cv2.Canny(alpha, 30, 90)
    edge[alpha <= 40] = 0
    ys, xs = np.where(edge > 0)
    if len(xs) == 0:
        raise ValueError("滑块图边缘全空")
    return edge[ys.min() : ys.max() + 1, xs.min() : xs.max() + 1]


def captcha_slide(cfg: dict, args: dict) -> dict:
    import cv2
    import numpy as np

    started = time.time()
    bg_path = Path(str(args.get("bg") or ""))
    slider_path = Path(str(args.get("slider") or ""))
    if not bg_path.is_file():
        return err("E_INPUT", f"背景图不存在: {bg_path}")
    if not slider_path.is_file():
        return err("E_INPUT", f"拼图块不存在: {slider_path}")

    bg = cv2.imread(str(bg_path))
    if bg is None:
        return err("E_INPUT", f"背景图不可读: {bg_path}")
    try:
        slider = _load_rgba(slider_path)
        profile = _slider_profile(slider)
    except ValueError as exc:
        return err("E_SLIDE", str(exc))

    ph, pw = profile.shape
    gray = cv2.cvtColor(bg, cv2.COLOR_BGR2GRAY)
    edge = cv2.Canny(gray, 60, 160)
    edge = cv2.dilate(edge, np.ones((3, 3), np.uint8), iterations=1)
    if edge.shape[1] < pw or edge.shape[0] < ph:
        return err("E_SLIDE", "背景图小于滑块模板")

    response = cv2.matchTemplate(edge, profile, cv2.TM_CCOEFF_NORMED)
    _, max_score, _, max_loc = cv2.minMaxLoc(response)
    x, y = int(max_loc[0]), int(max_loc[1])

    fine = int((cfg.get("slide") or {}).get("fineRadius") or 12)
    if fine > 0:
        x_lo, x_hi = max(0, x - fine), min(response.shape[1] - 1, x + fine)
        y_lo, y_hi = max(0, y - fine), min(response.shape[0] - 1, y + fine)
        _, fine_score, _, fine_loc = cv2.minMaxLoc(response[y_lo : y_hi + 1, x_lo : x_hi + 1])
        if fine_score >= max_score:
            x = x_lo + int(fine_loc[0])
            y = y_lo + int(fine_loc[1])
            max_score = float(fine_score)

    raw_threshold = args.get("threshold")
    threshold = float(
        raw_threshold
        if raw_threshold is not None
        else ((cfg.get("slide") or {}).get("threshold") or 0.25)
    )
    score = round(float(max_score), 4)

    raw_out = args.get("out")
    if raw_out:
        out_dir = Path(str(raw_out))
    else:
        out_dir = Path(str(cfg.get("workDir") or "/tmp/dsh-image-read")) / (
            f"slide-{int(time.time())}-{uuid.uuid4().hex[:6]}"
        )
    out_dir.mkdir(parents=True, exist_ok=True)
    overlay = bg.copy()
    cv2.rectangle(overlay, (x, y), (x + pw, y + ph), (0, 0, 255), 2)
    overlay_path = out_dir / "overlay.png"
    cv2.imwrite(str(overlay_path), overlay)

    return {
        "ok": True,
        "x": x,
        "y": y,
        "score": score,
        "threshold": threshold,
        "trusted": bool(score >= threshold),
        "slider_w": int(pw),
        "slider_h": int(ph),
        "bg": {"width": int(bg.shape[1]), "height": int(bg.shape[0])},
        "artifacts": {"overlay_png": str(overlay_path)},
        "elapsed_ms": int((time.time() - started) * 1000),
    }


def _load_gray(path: Path):
    import cv2

    image = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError(f"读不到图片: {path}")
    return cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)


def _orb_relative_angle(ref_gray, img_gray, cfg: dict):
    import cv2
    import math
    import numpy as np

    rotate_cfg = cfg.get("rotate") or {}
    cv2.ocl.setUseOpenCL(False)
    orb = cv2.ORB_create(int(rotate_cfg.get("features") or 2000))
    kp1, des1 = orb.detectAndCompute(ref_gray, None)
    kp2, des2 = orb.detectAndCompute(img_gray, None)
    if des1 is None or des2 is None or len(kp1) < 8 or len(kp2) < 8:
        return None
    matcher = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True)
    matches = sorted(matcher.match(des1, des2), key=lambda m: m.distance)
    matches = matches[: int(rotate_cfg.get("maxMatches") or 300)]
    if len(matches) < 8:
        return None
    src = np.float32([kp1[m.queryIdx].pt for m in matches]).reshape(-1, 1, 2)
    dst = np.float32([kp2[m.trainIdx].pt for m in matches]).reshape(-1, 1, 2)
    matrix, inliers = cv2.estimateAffinePartial2D(src, dst, method=cv2.RANSAC, ransacReprojThreshold=3.0)
    if matrix is None:
        return None
    angle = math.degrees(math.atan2(float(matrix[1, 0]), float(matrix[0, 0])))
    angle = (angle + 180.0) % 360.0 - 180.0
    scale = math.hypot(float(matrix[0, 0]), float(matrix[1, 0]))
    count = int(inliers.sum()) if inliers is not None else 0
    return angle, scale, count, len(matches)


def _upright_projection(gray, step: int = 1):
    import cv2
    import numpy as np

    height, width = gray.shape
    factor = min(1.0, 512.0 / max(height, width))
    small = gray
    if factor < 1.0:
        small = cv2.resize(gray, None, fx=factor, fy=factor, interpolation=cv2.INTER_AREA)
    edges = cv2.Canny(small, 50, 150)
    best_score, best_theta = -1.0, 0
    scores = []
    for theta in range(0, 180, step):
        matrix = cv2.getRotationMatrix2D((small.shape[1] / 2.0, small.shape[0] / 2.0), theta, 1.0)
        rotated = cv2.warpAffine(
            edges, matrix, (small.shape[1], small.shape[0]), flags=cv2.INTER_NEAREST, borderValue=0
        )
        score = float(rotated.sum(axis=1).var() + rotated.sum(axis=0).var())
        scores.append(score)
        if score > best_score:
            best_score, best_theta = score, theta
    mean = float(np.mean(scores)) if scores else 0.0
    std = float(np.std(scores)) or 1.0
    return best_theta, (best_score - mean) / std


def captcha_rotate(cfg: dict, args: dict) -> dict:
    import cv2

    started = time.time()
    image_path = Path(str(args.get("image") or ""))
    if not image_path.is_file():
        return err("E_INPUT", f"图片不存在: {image_path}")
    try:
        gray = _load_gray(image_path)
    except ValueError as exc:
        return err("E_INPUT", str(exc))

    rotate_cfg = cfg.get("rotate") or {}
    reference = args.get("reference")
    if reference:
        reference_path = Path(str(reference))
        if not reference_path.is_file():
            return err("E_INPUT", f"参考图不存在: {reference_path}")
        try:
            ref_gray = _load_gray(reference_path)
        except ValueError as exc:
            return err("E_INPUT", str(exc))
        estimated = _orb_relative_angle(ref_gray, gray, cfg)
        if estimated is None:
            return err("E_ROTATE", "ORB 匹配点不足，无法估计角度")
        angle, scale, inliers, matches = estimated
        ratio = inliers / max(1, matches)
        trusted = (
            inliers >= int(rotate_cfg.get("minInliers") or 20)
            and ratio >= float(rotate_cfg.get("minInlierRatio") or 0.25)
            and float(rotate_cfg.get("scaleMin") or 0.8) <= scale <= float(rotate_cfg.get("scaleMax") or 1.25)
        )
        result = {
            "ok": True,
            "angle": round(angle, 2),
            "correction": round(-angle, 2),
            "trusted": bool(trusted),
            "method": "reference_orb",
            "score": round(ratio, 4),
            "inliers": inliers,
            "matches": matches,
            "scale": round(scale, 4),
        }
    else:
        theta, zscore = _upright_projection(gray, int(rotate_cfg.get("coarseStep") or 1))
        angle = (-theta + 180.0) % 360.0 - 180.0
        result = {
            "ok": True,
            "angle": round(angle, 2),
            "correction": round(-angle, 2),
            "trusted": False,
            "method": "upright_projection",
            "score": round(zscore, 2),
            "inliers": 0,
            "matches": 0,
            "scale": 1.0,
            "warning": "无参考图；投影法存在 90° 歧义，结果不可信",
        }

    image = cv2.imread(str(image_path))
    raw_out = args.get("out")
    if raw_out:
        out_dir = Path(str(raw_out))
    else:
        out_dir = Path(str(cfg.get("workDir") or "/tmp/dsh-image-read")) / (
            f"rotate-{int(time.time())}-{uuid.uuid4().hex[:6]}"
        )
    out_dir.mkdir(parents=True, exist_ok=True)
    overlay = image.copy()
    cv2.putText(
        overlay,
        f"angle={result['angle']} trusted={result['trusted']}",
        (12, 34),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.8,
        (0, 0, 255),
        2,
        cv2.LINE_AA,
    )
    overlay_path = out_dir / "overlay.png"
    cv2.imwrite(str(overlay_path), overlay)
    height, width = image.shape[:2]
    matrix = cv2.getRotationMatrix2D((width / 2.0, height / 2.0), -result["correction"], 1.0)
    aligned = cv2.warpAffine(image, matrix, (width, height), borderValue=(255, 255, 255))
    aligned_path = out_dir / "aligned.png"
    cv2.imwrite(str(aligned_path), aligned)

    result["artifacts"] = {"overlay_png": str(overlay_path), "aligned_png": str(aligned_path)}
    result["elapsed_ms"] = int((time.time() - started) * 1000)
    return result


def captcha_curve(cfg: dict, args: dict) -> dict:
    import cv2
    import numpy as np

    started = time.time()
    image_path = Path(str(args.get("image") or ""))
    if not image_path.is_file():
        return err("E_INPUT", f"图片不存在: {image_path}")
    image = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
    if image is None:
        return err("E_INPUT", f"图片不可读: {image_path}")
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

    curve_cfg = cfg.get("curve") or {}
    blur = cv2.GaussianBlur(gray, (3, 3), 0)
    _, mask = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    row_idx, col_idx = np.where(mask > 0)
    if len(col_idx) < int(curve_cfg.get("minPixels") or 200):
        return err("E_CURVE", f"暗像素不足: {len(col_idx)}")

    points = []
    previous = None
    for x in range(int(col_idx.min()), int(col_idx.max()) + 1):
        column = np.where(mask[:, x] > 0)[0]
        if len(column) == 0:
            continue
        runs = np.split(column, np.where(np.diff(column) > 1)[0] + 1)
        centers = [float(run.mean()) for run in runs]
        if previous is None:
            y = centers[int(np.argmax([len(run) for run in runs]))]
        else:
            y = centers[int(np.argmin([abs(center - previous) for center in centers]))]
        points.append((float(x), float(y)))
        previous = y
    if len(points) < 2:
        return err("E_CURVE", "曲线点不足")

    max_points = max(2, int(curve_cfg.get("maxPoints") or 80))
    indices = sorted(set(np.linspace(0, len(points) - 1, max_points).astype(int).tolist()))
    sampled = [points[i] for i in indices]
    array = np.array(sampled, dtype=np.float64)
    length = float(np.hypot(np.diff(array[:, 0]), np.diff(array[:, 1])).sum())
    x0, y0 = int(col_idx.min()), int(row_idx.min())
    x1, y1 = int(col_idx.max()), int(row_idx.max())

    raw_out = args.get("out")
    if raw_out:
        out_dir = Path(str(raw_out))
    else:
        out_dir = Path(str(cfg.get("workDir") or "/tmp/dsh-image-read")) / (
            f"curve-{int(time.time())}-{uuid.uuid4().hex[:6]}"
        )
    out_dir.mkdir(parents=True, exist_ok=True)
    overlay = image.copy()
    polyline = np.array([[int(round(x)), int(round(y))] for x, y in sampled], dtype=np.int32).reshape(-1, 1, 2)
    cv2.polylines(overlay, [polyline], False, (0, 0, 255), 2, cv2.LINE_AA)
    overlay_path = out_dir / "overlay.png"
    cv2.imwrite(str(overlay_path), overlay)

    return {
        "ok": True,
        "points": [[round(x, 1), round(y, 1)] for x, y in sampled],
        "n_points": len(sampled),
        "length_px": round(length, 2),
        "endpoints": [
            [round(sampled[0][0], 1), round(sampled[0][1], 1)],
            [round(sampled[-1][0], 1), round(sampled[-1][1], 1)],
        ],
        "bbox": [x0, y0, x1 - x0 + 1, y1 - y0 + 1],
        "method": "column_centerline",
        "artifacts": {"overlay_png": str(overlay_path)},
        "elapsed_ms": int((time.time() - started) * 1000),
    }


def _to_gray(image):
    import cv2

    if image.ndim == 2:
        return image
    return cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)


def _rotate_image(image, angle):
    import cv2

    degrees = float(angle) % 360.0
    if abs(degrees - 90.0) < 1e-6:
        return cv2.rotate(image, cv2.ROTATE_90_CLOCKWISE)
    if abs(degrees - 180.0) < 1e-6:
        return cv2.rotate(image, cv2.ROTATE_180)
    if abs(degrees - 270.0) < 1e-6:
        return cv2.rotate(image, cv2.ROTATE_90_COUNTERCLOCKWISE)
    height, width = image.shape[:2]
    matrix = cv2.getRotationMatrix2D((width / 2.0, height / 2.0), degrees, 1.0)
    cos, sin = abs(matrix[0, 0]), abs(matrix[0, 1])
    new_w, new_h = int(height * sin + width * cos), int(height * cos + width * sin)
    matrix[0, 2] += new_w / 2.0 - width / 2.0
    matrix[1, 2] += new_h / 2.0 - height / 2.0
    return cv2.warpAffine(image, matrix, (new_w, new_h), borderValue=(255, 255, 255))


def img_ops(cfg: dict, args: dict) -> dict:
    import cv2

    started = time.time()
    image_path = Path(str(args.get("image") or ""))
    if not image_path.is_file():
        return err("E_INPUT", f"图片不存在: {image_path}")
    image = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
    if image is None:
        return err("E_INPUT", f"图片不可读: {image_path}")
    specs = args.get("ops")
    if not isinstance(specs, list) or not specs:
        return err("E_OP", "ops 必须是非空数组")

    steps = []
    for index, spec in enumerate(specs):
        if not isinstance(spec, dict) or not spec.get("op"):
            return err("E_OP", f"第 {index} 步缺少 op")
        name = str(spec.get("op"))
        try:
            if name == "rotate":
                image = _rotate_image(image, spec.get("angle", 90))
            elif name == "crop":
                x, y = int(spec.get("x", 0)), int(spec.get("y", 0))
                w, h = int(spec.get("w", 0)), int(spec.get("h", 0))
                height, width = image.shape[:2]
                x, y = max(0, x), max(0, y)
                w, h = min(w, width - x), min(h, height - y)
                if w <= 0 or h <= 0:
                    return err("E_OP", f"第 {index} 步 crop 越界")
                image = image[y : y + h, x : x + w]
            elif name == "resize":
                w, h = int(spec.get("width", 0)), int(spec.get("height", 0))
                if w <= 0 or h <= 0:
                    return err("E_OP", f"第 {index} 步 resize 尺寸非法")
                image = cv2.resize(image, (w, h), interpolation=cv2.INTER_AREA)
            elif name == "gray":
                image = _to_gray(image)
            elif name == "threshold":
                gray = _to_gray(image)
                _, image = cv2.threshold(gray, int(spec.get("value", 127)), 255, cv2.THRESH_BINARY)
            elif name == "invert":
                image = 255 - image
            elif name == "blur":
                ksize = max(1, int(spec.get("ksize", 5)) | 1)
                image = cv2.GaussianBlur(image, (ksize, ksize), 0)
            elif name == "edges":
                image = cv2.Canny(_to_gray(image), int(spec.get("low", 50)), int(spec.get("high", 150)))
            elif name == "contours":
                gray = _to_gray(image)
                _, mask = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
                found, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                min_area = float(spec.get("minArea", 10))
                kept = [contour for contour in found if cv2.contourArea(contour) >= min_area]
                largest = max(kept, key=cv2.contourArea) if kept else None
                bbox = [int(v) for v in cv2.boundingRect(largest)] if largest is not None else [0, 0, 0, 0]
                steps.append(
                    {
                        "op": name,
                        "ok": True,
                        "count": len(kept),
                        "largest_bbox": bbox,
                        "width": int(image.shape[1]),
                        "height": int(image.shape[0]),
                        "channels": 1 if image.ndim == 2 else int(image.shape[2]),
                    }
                )
                continue
            else:
                return err("E_OP", f"第 {index} 步未知 op: {name}")
        except (ValueError, TypeError, cv2.error) as exc:
            return err("E_OP", f"第 {index} 步 {name} 失败: {exc}")
        steps.append(
            {
                "op": name,
                "ok": True,
                "width": int(image.shape[1]),
                "height": int(image.shape[0]),
                "channels": 1 if image.ndim == 2 else int(image.shape[2]),
            }
        )

    raw_out = args.get("out")
    if raw_out:
        out_dir = Path(str(raw_out))
    else:
        out_dir = Path(str(cfg.get("workDir") or "/tmp/dsh-image-read")) / (
            f"ops-{int(time.time())}-{uuid.uuid4().hex[:6]}"
        )
    out_dir.mkdir(parents=True, exist_ok=True)
    output_path = out_dir / "output.png"
    cv2.imwrite(str(output_path), image)
    height, width = image.shape[:2]
    return {
        "ok": True,
        "steps": steps,
        "output": {
            "path": str(output_path),
            "width": int(width),
            "height": int(height),
            "channels": 1 if image.ndim == 2 else int(image.shape[2]),
        },
        "artifacts": {"output_png": str(output_path)},
        "elapsed_ms": int((time.time() - started) * 1000),
    }


OPS = {
    "chart_read": chart_read,
    "captcha_slide": captcha_slide,
    "captcha_rotate": captcha_rotate,
    "captcha_curve": captcha_curve,
    "img_ops": img_ops,
}


def main() -> int:
    op = sys.argv[1] if len(sys.argv) > 1 else ""
    if op not in OPS:
        print(json.dumps(err("E_OP", f"未知 op: {op}"), ensure_ascii=False))
        return 0
    try:
        index = sys.argv.index("--config")
        cfg = json.loads(Path(sys.argv[index + 1]).read_text("utf-8"))
    except (ValueError, IndexError, OSError) as exc:
        print(json.dumps(err("E_CONFIG", f"读配置失败: {exc}"), ensure_ascii=False))
        return 0
    try:
        args = json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError as exc:
        print(json.dumps(err("E_ARGS", f"参数不是合法 JSON: {exc}"), ensure_ascii=False))
        return 0
    try:
        result = OPS[op](cfg, args)
    except Exception as exc:  # noqa: BLE001 - 桥的职责是把异常变成结构化错误
        result = err("E_INTERNAL", f"{type(exc).__name__}: {exc}")
    print(json.dumps(sanitize(result), ensure_ascii=False, allow_nan=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
