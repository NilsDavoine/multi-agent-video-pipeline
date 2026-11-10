"""Claude provider: the agents call the live API (see `python -m vidpipe claude`).

With `record_root` (or VIDPIPE_RECORD=1) each answer is also saved as a recording,
so the run can later be replayed without a key. No temperature/top_p/top_k and no
assistant prefill are sent: current models reject both with a 400.
"""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

from .base import extract_json, prompt_hash

DEFAULT_MODEL = "claude-haiku-5-5"
MAX_TOKENS = 8000      # adaptive thinking counts against it; a design answer is ~300 tokens
# USD per million input / output tokens (Anthropic price list, prompts up to 100K tokens).
PRICES = {"claude-haiku-5-5": (0.10, 0.50), "claude-sonnet-5-5": (2.00, 10.00),
          "claude-opus-5-5": (4.00, 20.00)}


class ClaudeProvider:
    live = True

    def __init__(self, record_root: Path | None = None, client=None, model: str | None = None,
                 record: bool | None = None):
        if client is None:
            import anthropic  # imported lazily: optional dependency
            client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY itself; never logged
        self.client = client
        self.model = model or os.environ.get("VIDPIPE_CLAUDE_MODEL", DEFAULT_MODEL)
        self.name = f"claude:{self.model}"
        if record is None:
            record = os.environ.get("VIDPIPE_RECORD") == "1"
        self.record_root = record_root if record else None
        self.calls: list[dict] = []   # one entry per API call: role, key, tokens, seconds
        self._lock = threading.Lock()  # designers run in parallel

    def complete(self, role: str, key: str, system: str, prompt: str) -> str:
        t0 = time.perf_counter()
        msg = self.client.messages.create(
            model=self.model, max_tokens=MAX_TOKENS, system=system,
            messages=[{"role": "user", "content": prompt}],
            output_config={"effort": "low"},
        )
        text = "" if msg.stop_reason == "refusal" else "".join(
            b.text for b in msg.content if b.type == "text")
        with self._lock:
            self.calls.append({"role": role, "key": key, "stop_reason": msg.stop_reason,
                               "input_tokens": msg.usage.input_tokens,
                               "output_tokens": msg.usage.output_tokens,
                               "seconds": round(time.perf_counter() - t0, 2)})
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

    def cost(self) -> float:
        price_in, price_out = PRICES.get(self.model, (0.0, 0.0))
        return sum(c["input_tokens"] * price_in + c["output_tokens"] * price_out for c in self.calls) / 1e6
