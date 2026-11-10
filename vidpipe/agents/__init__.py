from __future__ import annotations

import logging
from pathlib import Path

from .base import Agent, AgentError, Provider
from .replay import ReplayProvider

log = logging.getLogger("vidpipe")


def get_provider(recordings: Path, strict_replay: bool = False) -> Provider:
    """`vidpipe run` replays recorded outputs. A live Claude pass is a separate,
    explicit command (`python -m vidpipe claude`) that shows its cost first."""
    log.info("agents: replay of %s", recordings)
    return ReplayProvider(recordings, strict=strict_replay)


__all__ = ["Agent", "AgentError", "Provider", "ReplayProvider", "get_provider"]
