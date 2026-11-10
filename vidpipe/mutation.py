"""Deliberate damage for guard testing: make one scene's voice say something else.

This mimics a real failure (an edited or mis-assembled narration that no longer
matches the approved script) while keeping the picture, the durations and the
loudness unchanged, so only the transcript gate can notice.
"""
from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from .contracts import Line, Timeline

OFF_SCRIPT = "Then the colour of the logo, and the font used in the footer."


def replace_scene_voice(video: Path, timeline: Timeline, scene_id: str, out: Path,
                        text: str = OFF_SCRIPT) -> Path:
    from .stages import speech

    slot = next(s for s in timeline.scenes if s.scene_id == scene_id)
    with tempfile.TemporaryDirectory() as tmp:
        wav = Path(tmp) / "off_script.wav"
        speech.synthesize([Line(speaker="narrator", kind="story", text=text)], wav, timeline.fps)
        a, b = slot.start, slot.start + slot.duration
        graph = (f"[0:a]volume=enable='between(t,{a:.3f},{b:.3f})':volume=0[base];"
                 f"[1:a]aresample=48000,aformat=channel_layouts=stereo,atrim=0:{slot.duration:.3f},"
                 f"adelay={int(a * 1000)}|{int(a * 1000)}[new];"
                 f"[base][new]amix=inputs=2:duration=first,volume=2[mix]")
        tmp_out = Path(tmp) / "mutated.mp4"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(video), "-i", str(wav),
                        "-filter_complex", graph, "-map", "0:v", "-map", "[mix]", "-c:v", "copy",
                        "-c:a", "aac", "-b:a", "96k", str(tmp_out)], check=True)
        shutil.move(str(tmp_out), str(out))
    return out
