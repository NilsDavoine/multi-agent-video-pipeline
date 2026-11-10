"""Agent = a role prompt + a typed output contract + an interchangeable provider."""
from __future__ import annotations

import hashlib
import json
import logging
from typing import Generic, Protocol, TypeVar

from pydantic import BaseModel, ValidationError

log = logging.getLogger("vidpipe")
M = TypeVar("M", bound=BaseModel)


class Provider(Protocol):
    name: str
    live: bool  # True if it can be asked again after a contract violation

    def complete(self, role: str, key: str, system: str, prompt: str) -> str:
        """Return the raw JSON text answering `prompt` for agent `role`, call `key`."""


class AgentError(RuntimeError):
    pass


def prompt_hash(system: str, prompt: str) -> str:
    return hashlib.sha256((system + "\n\n" + prompt).encode()).hexdigest()[:16]


def extract_json(text: str) -> str:
    """Models sometimes wrap JSON in prose or code fences: keep the outermost object."""
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < start:
        raise AgentError("no JSON object in agent answer")
    return text[start:end + 1]


class Agent(Generic[M]):
    def __init__(self, role: str, output: type[M], system: str, provider: Provider):
        self.role, self.output, self.system, self.provider = role, output, system, provider

    def run(self, key: str, payload: dict) -> M:
        schema = json.dumps(self.output.model_json_schema())
        prompt = (f"INPUT:\n{json.dumps(payload, indent=1)}\n\n"
                  f"Answer with one JSON object only, matching this JSON schema:\n{schema}")
        attempts = 2 if self.provider.live else 1
        last: Exception | None = None
        for _ in range(attempts):
            raw = self.provider.complete(self.role, key, self.system, prompt)
            try:
                return self.output.model_validate_json(extract_json(raw))
            except (ValidationError, AgentError) as exc:
                last = exc
                log.warning("%s/%s broke its contract: %s", self.role, key, str(exc).splitlines()[0])
                prompt += f"\n\nYour previous answer was rejected:\n{exc}\nFix it."
        raise AgentError(f"{self.role}/{key}: output does not match {self.output.__name__}: {last}")
