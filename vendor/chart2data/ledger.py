"""「见过没」账本：图像指纹与检索。语义见 INTERFACE.md §6。"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
from PIL import Image


def sha256_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def dhash(rgb):
    """64-bit 差分哈希，16 个十六进制字符。"""
    img = Image.fromarray(rgb).convert("L").resize((9, 8), Image.LANCZOS)
    arr = np.asarray(img, dtype=np.int16)
    bits = (arr[:, 1:] > arr[:, :-1]).reshape(-1)
    value = 0
    for bit in bits:
        value = (value << 1) | int(bit)
    return f"{value:016x}"


def hamming(a, b):
    return bin(int(a, 16) ^ int(b, 16)).count("1")


def load(path):
    p = Path(path)
    if not p.exists():
        return []
    entries = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return entries


def append(path, entry):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")


def find(entries, sha, dh, max_dist):
    hits = []
    for e in entries:
        if e.get("sha256") == sha:
            dist = 0
        elif e.get("dhash"):
            dist = hamming(dh, e["dhash"])
            if dist > max_dist:
                continue
        else:
            continue
        hits.append({
            "distance": dist,
            "sha256": e.get("sha256"),
            "ts": e.get("ts"),
            "path": e.get("path"),
            "series": e.get("series"),
        })
    hits.sort(key=lambda h: h["distance"])
    return hits
