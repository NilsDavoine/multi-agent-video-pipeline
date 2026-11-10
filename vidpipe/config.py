"""Paths, model choices and quality thresholds, in one place."""
from __future__ import annotations

import contextlib
import fcntl
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MODELS = ROOT / "models"
RECORDINGS = ROOT / "recordings"
RUNS = ROOT / "runs"

# Local, open-weight models (no paid service).
KOKORO_MODEL = MODELS / "kokoro-v1.0.int8.onnx"   # Kokoro-82M, Apache-2.0
KOKORO_VOICES = MODELS / "voices-v1.0.bin"
VOICES = {"lead": ("af_heart", 1.08), "narrator": ("am_michael", 1.0)}  # (voice, speed)
WHISPER_MODEL = "small"                            # faster-whisper, MIT, int8 on CPU

# Audio layout of a scene.
LEAD_IN_S = 0.15
GAP_S = 0.20
TAIL_S = 0.35

# Quality gates. A video that fails any of them is blocked (never marked publishable).
QC = {
    "wer_total_max": 0.10,        # word error rate, whole video
    "wer_scene_max": 0.25,        # word error rate, worst scene
    "scene_min_s": 1.5,
    "scene_max_s": 8.0,
    "video_max_s": 30.0,
    "av_drift_max_s": 0.10,       # audio stream vs video stream duration
    "font_min_px_at_360p": 16.0,  # = 48 px on a 1080p frame
    "contrast_min": 4.5,          # WCAG AA for normal text
    "frame_std_min": 12.0,        # grey-level standard deviation of a scene's middle frame
    "black_max_s": 0.0,           # total black time (blackdetect d=0.3)
    "sync_offset_max_s": 0.30,    # subtitle cue vs measured spoken word
}


@contextlib.contextmanager
def heavy_lock():
    """Serialise heavy work (model loading, rendering) with other jobs on the machine.

    Set VIDPIPE_LOCK to a lock file shared with other processes (flock semantics).
    """
    path = os.environ.get("VIDPIPE_LOCK")
    if not path:
        yield
        return
    with open(path, "a") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)
