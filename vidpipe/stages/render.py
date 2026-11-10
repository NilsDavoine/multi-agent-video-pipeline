"""Rendering: headless Chrome takes one screenshot per frame, ffmpeg encodes."""
from __future__ import annotations

import subprocess
from pathlib import Path

import numpy as np
import soundfile as sf


def render_scene(html_path: Path, out: Path, duration: float, fps: int, width: int, height: int) -> Path:
    """Silent H.264 clip of one scene page, frame by frame through window.__seek(t)."""
    from playwright.sync_api import sync_playwright

    frames = round(duration * fps)
    out.parent.mkdir(parents=True, exist_ok=True)
    enc = subprocess.Popen(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "image2pipe", "-framerate", str(fps), "-i", "-",
         "-c:v", "libx264", "-preset", "medium", "-crf", "26", "-pix_fmt", "yuv420p",
         "-r", str(fps), str(out)], stdin=subprocess.PIPE)
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="chrome", args=["--disable-gpu", "--font-render-hinting=none"])
            page = browser.new_page(viewport={"width": width, "height": height})
            page.goto(html_path.resolve().as_uri())
            for i in range(frames):
                page.evaluate(f"window.__seek({i / fps:.5f})")
                enc.stdin.write(page.screenshot(type="png"))
            browser.close()
    finally:
        enc.stdin.close()
        if enc.wait() != 0:
            raise RuntimeError(f"ffmpeg failed encoding {out}")
    return out


def assemble(clips: list[Path], wavs: list[Path], out: Path) -> Path:
    """Concatenate scene clips and scene voices; normalise loudness; mux."""
    work = out.parent
    listing = work / "clips.txt"
    listing.write_text("".join(f"file '{c.resolve()}'\n" for c in clips))
    silent = work / "video_silent.mp4"
    _ff(["-f", "concat", "-safe", "0", "-i", str(listing), "-c", "copy", str(silent)])
    voice = work / "voice.wav"
    parts = [sf.read(w, dtype="float32") for w in wavs]
    sr = parts[0][1]
    sf.write(voice, np.concatenate([a for a, _ in parts]), sr, subtype="PCM_16")
    _ff(["-i", str(silent), "-i", str(voice), "-map", "0:v", "-map", "1:a", "-c:v", "copy",
         "-af", "loudnorm=I=-16:TP=-1.5:LRA=11", "-ar", "48000", "-ac", "2",
         "-c:a", "aac", "-b:a", "96k", "-movflags", "+faststart", str(out)])
    return out


def _ff(args: list[str]) -> None:
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *args], check=True)
