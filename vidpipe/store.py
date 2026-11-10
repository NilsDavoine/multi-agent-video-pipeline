"""Stage cache: each step's validated output is saved with the hash of its inputs.

On a re-run, a step whose inputs have not changed (and whose files still exist)
is skipped. A failed step leaves no record, so the next run resumes exactly there.
Steps are cached at the finest useful grain (per scene for design, voice, render).
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
from pathlib import Path
from typing import Callable, TypeVar

from pydantic import BaseModel

log = logging.getLogger("vidpipe")
M = TypeVar("M", bound=BaseModel)


def _plain(p: object) -> object:
    """Models become dicts and file paths become content hashes, at any depth."""
    if isinstance(p, BaseModel):
        return p.model_dump(mode="json")
    if isinstance(p, Path):
        return file_digest(p)
    if isinstance(p, (list, tuple)):
        return [_plain(x) for x in p]
    if isinstance(p, dict):
        return {str(k): _plain(v) for k, v in p.items()}
    return p


def digest(*parts: object) -> str:
    h = hashlib.sha256()
    for p in parts:
        h.update(json.dumps(_plain(p), sort_keys=True, default=str).encode())
    return h.hexdigest()[:16]


def file_digest(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


class StageStore:
    def __init__(self, run_dir: Path, force: set[str] | None = None):
        self.dir = run_dir / "stages"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.force = force or set()
        self.events: list[dict] = []  # what ran, what was reused, how long it took

    def run(self, step: str, model: type[M], inputs_hash: str, fn: Callable[[], M],
            files: Callable[[M], list[str]] = lambda m: []) -> M:
        path = self.dir / f"{step}.json"
        stage = step.split("/")[0]
        if path.exists() and stage not in self.force:
            rec = json.loads(path.read_text())
            if rec["inputs"] == inputs_hash:
                out = model.model_validate(rec["output"])
                if all(Path(f).exists() for f in files(out)):
                    self.events.append({"step": step, "status": "reused", "seconds": 0.0})
                    log.info("reuse  %s", step)
                    return out
        t0 = time.perf_counter()
        log.info("run    %s", step)
        out = fn()
        out = model.model_validate(out.model_dump())  # contract check on the way out
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"inputs": inputs_hash, "output": out.model_dump(mode="json")}, indent=2))
        tmp.replace(path)  # atomic: a crash never leaves a half-written record
        self.events.append({"step": step, "status": "ran", "seconds": round(time.perf_counter() - t0, 2)})
        return out
