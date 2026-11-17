"""运行目录：分阶段落盘 + manifest 摘要，保证过程可查。语义见 INTERFACE.md §10.3。"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

MANIFEST_SCHEMA = "chart2data/manifest@1"


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _iso():
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


class RunDir:
    def __init__(self, path, command, config):
        self.path = Path(path)
        self.path.mkdir(parents=True, exist_ok=True)
        self.command = command
        self.config = config
        self.stages = []
        self.warnings = []
        self._cur = None

    def start(self, name):
        self._cur = {"name": name, "files": [], "warnings": []}
        self.stages.append(self._cur)
        return self._cur

    def _record(self, rel):
        self._cur["files"].append({
            "path": rel,
            "sha256": _sha(self.path / rel),
            "bytes": (self.path / rel).stat().st_size,
        })

    def json(self, rel, obj):
        p = self.path / rel
        p.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n",
                     encoding="utf-8")
        self._record(rel)
        return rel

    def text(self, rel, content):
        (self.path / rel).write_text(content, encoding="utf-8")
        self._record(rel)
        return rel

    def file(self, rel):
        """把已写到本目录的文件登记进当前阶段（不重写内容）。"""
        self._record(rel)
        return rel

    def warn(self, msg):
        self.warnings.append(msg)
        if self._cur is not None:
            self._cur["warnings"].append(msg)

    def finish(self, status="ok"):
        manifest = {
            "schema": MANIFEST_SCHEMA,
            "command": self.command,
            "created": _iso(),
            "status": status,
            "config_sha256": hashlib.sha256(
                json.dumps(self.config, sort_keys=True).encode("utf-8")).hexdigest(),
            "stages": self.stages,
            "warnings": self.warnings,
        }
        (self.path / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8")
        return manifest
