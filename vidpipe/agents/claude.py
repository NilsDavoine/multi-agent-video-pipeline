"""Claude provider: used only when ANTHROPIC_API_KEY is set.

With VIDPIPE_RECORD=1 each answer is also saved as a recording, so the run can
later be replayed without a key.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from .base import extract_json, prompt_hash

DEFAULT_MODEL = "claude-sonnet-5-5"


class ClaudeProvider:
    name = "claude"
    live = True

    def __init__(self, record_root: Path | None = None):
        import anthropic  # imported lazily: optional dependency

        self.client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY itself; never logged
        self.model = os.environ.get("VIDPIPE_CLAUDE_MODEL", DEFAULT_MODEL)
        self.record_root = record_root if os.environ.get("VIDPIPE_RECORD") == "1" else None

    def complete(self, role: str, key: str, system: str, prompt: str) -> str:
        msg = self.client.messages.create(
            model=self.model, max_tokens=2000, system=system,
            messages=[{"role": "user", "content": prompt}],
        )
        text = "".join(b.text for b in msg.content if b.type == "text")
        if self.record_root:
            path = self.record_root / role / f"{key}.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            try:
                output = json.loads(extract_json(text))
            except Exception:  # keep the raw answer, the contract check will reject it
                output = {"_raw": text}
            path.write_text(json.dumps({"prompt_sha256": prompt_hash(system, prompt),
                                        "model": self.model, "output": output}, indent=2))
        return text
