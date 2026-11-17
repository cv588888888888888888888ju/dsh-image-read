"""Generate self-contained synthetic fixtures (no third-party data).

Run: python3 acceptance/make_fixtures.py
"""
import json
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent / "fixtures"


def make_slide():
    out = ROOT / "slide"
    out.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(7)
    bg = rng.integers(35, 225, (480, 960, 3), dtype=np.uint8)
    bg = cv2.GaussianBlur(bg, (0, 0), 3)
    gradient = np.linspace(-25, 25, 960, dtype=np.float32)[None, :, None]
    bg = np.clip(bg.astype(np.float32) + gradient, 0, 255).astype(np.uint8)

    size = 120
    sprite = np.zeros((size, size, 4), np.uint8)
    color = (70, 110, 170, 255)
    cv2.rectangle(sprite, (16, 22), (size - 17, size - 17), color, -1)
    cv2.circle(sprite, (size // 2, 22), 14, color, -1)
    cv2.circle(sprite, (size // 2, size - 17), 14, (0, 0, 0, 0), -1)

    x0, y0 = 417, 120
    patch = bg[y0 : y0 + size, x0 : x0 + size]
    inside = sprite[:, :, 3] > 0
    sprite[:, :, :3][inside] = patch[inside]
    cv2.imwrite(str(out / "synthetic_slider.png"), sprite)

    mask = (sprite[:, :, 3].astype(np.float32) / 255.0)[..., None]
    h, w = mask.shape[:2]
    hole = bg.copy()
    region = hole[y0 : y0 + h, x0 : x0 + w].astype(np.float32)
    fill = patch.astype(np.float32) * 0.5 + 255.0 * 0.5
    hole[y0 : y0 + h, x0 : x0 + w] = (region * (1 - mask) + fill * mask).astype(np.uint8)
    cv2.imwrite(str(out / "synthetic_bg.png"), hole)
    ys, xs = np.where(sprite[:, :, 3] > 0)
    json.dump(
        {"x0": x0 + int(xs.min()), "y0": y0 + int(ys.min()), "sprite_x": int(xs.min()), "sprite_y": int(ys.min())},
        open(out / "synthetic_truth.json", "w"),
    )


def make_curve():
    out = ROOT / "curve"
    out.mkdir(parents=True, exist_ok=True)
    width, height = 800, 400
    image = np.full((height, width, 3), 255, np.uint8)
    xs = np.arange(20, 781)
    ys = (200 + 80 * np.sin(xs / 60.0)).round().astype(int)
    points = np.stack([xs, ys], axis=1).reshape(-1, 1, 2)
    cv2.polylines(image, [points], False, (0, 0, 0), 3, cv2.LINE_AA)
    cv2.imwrite(str(out / "synthetic_curve.png"), image)
    length = float(np.hypot(np.diff(xs), np.diff(ys.astype(float))).sum())
    json.dump(
        {"endpoints": [[int(xs[0]), int(ys[0])], [int(xs[-1]), int(ys[-1])]], "length_px": round(length, 2)},
        open(out / "synthetic_truth.json", "w"),
    )
    cv2.imwrite(str(out / "blank.png"), np.full((200, 200, 3), 255, np.uint8))


def make_rotate():
    out = ROOT / "rotate"
    out.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(11)
    width, height = 600, 535
    image = np.full((height, width, 3), 235, np.uint8)
    for _ in range(18):
        x, y = int(rng.integers(0, width - 60)), int(rng.integers(0, height - 60))
        w, h = int(rng.integers(20, 90)), int(rng.integers(20, 90))
        color = tuple(int(v) for v in rng.integers(20, 210, 3))
        cv2.rectangle(image, (x, y), (x + w, y + h), color, -1)
        cv2.circle(image, (x + w // 2, y + h // 2), max(5, min(w, h) // 3), (30, 30, 30), 2)
    cv2.putText(image, "UP", (40, 480), cv2.FONT_HERSHEY_SIMPLEX, 3.0, (0, 0, 0), 6, cv2.LINE_AA)
    cv2.line(image, (0, 300), (width, 260), (90, 90, 90), 4)
    cv2.imwrite(str(out / "synthetic_ref.png"), image)

    truth = {}
    for angle in [45, 90, 135, 180, 225, 270, 315]:
        h, w = image.shape[:2]
        matrix = cv2.getRotationMatrix2D((w / 2.0, h / 2.0), -angle, 1.0)
        cos, sin = abs(matrix[0, 0]), abs(matrix[0, 1])
        new_w, new_h = int(h * sin + w * cos), int(h * cos + w * sin)
        matrix[0, 2] += new_w / 2.0 - w / 2.0
        matrix[1, 2] += new_h / 2.0 - h / 2.0
        rotated = cv2.warpAffine(image, matrix, (new_w, new_h), borderValue=(0, 0, 0))
        name = "synthetic_" + str(angle) + ".png"
        cv2.imwrite(str(out / name), rotated)
        truth[name] = angle
    json.dump(truth, open(out / "synthetic_truth.json", "w"))


if __name__ == "__main__":
    make_slide()
    make_curve()
    make_rotate()
    print("fixtures written to", ROOT)
