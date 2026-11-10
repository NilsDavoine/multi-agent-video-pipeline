"""Replay provider: answers from recorded outputs, so the pipeline runs with no API key.

Recordings live in recordings/<slug>/<role>/<key>.json as
{"prompt_sha256": "...", "output": {...}}. If the prompt changed since the
recording, the replayed answer is stale: strict mode refuses it, default mode warns.
VIDPIPE_SEAL=1 stamps the current prompt hash into each recording it serves (used
once, after writing reference answers by hand).
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from .base import AgentError, prompt_hash

log = logging.getLogger("vidpipe")


class ReplayProvider:
    name = "replay"
    live = False

    def __init__(self, root: Path, strict: bool = False):
        self.root, self.strict = root, strict
        self.stale: list[str] = []

    def complete(self, role: str, key: str, system: str, prompt: str) -> str:
        path = self.root / role / f"{key}.json"
        if not path.exists():
            raise AgentError(f"no recording for {role}/{key} at {path}")
        rec = json.loads(path.read_text())
        if os.environ.get("VIDPIPE_SEAL") == "1":
            rec["prompt_sha256"] = prompt_hash(system, prompt)
            path.write_text(json.dumps(rec, indent=2))
        if rec.get("prompt_sha256") != prompt_hash(system, prompt):
            self.stale.append(f"{role}/{key}")
            msg = f"recording {role}/{key} was made for a different prompt"
            if self.strict:
                raise AgentError(msg)
            log.warning(msg)
        return json.dumps(rec["output"])
