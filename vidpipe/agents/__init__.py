from __future__ import annotations

import logging
import os
from pathlib import Path

from .base import Agent, AgentError, Provider
from .replay import ReplayProvider

log = logging.getLogger("vidpipe")


def get_provider(recordings: Path, strict_replay: bool = False) -> Provider:
    """Claude if a key is provided, otherwise replay recorded outputs."""
    if os.environ.get("ANTHROPIC_API_KEY"):
        from .claude import ClaudeProvider
        log.info("agents: Claude (live)")
        return ClaudeProvider(record_root=recordings)
    log.info("agents: replay of %s (no ANTHROPIC_API_KEY)", recordings)
    return ReplayProvider(recordings, strict=strict_replay)


__all__ = ["Agent", "AgentError", "Provider", "ReplayProvider", "get_provider"]
