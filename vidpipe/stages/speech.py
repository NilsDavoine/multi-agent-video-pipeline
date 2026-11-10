"""Local speech models: Kokoro (text to speech) and faster-whisper (speech to text).

Both are open-weight and run on CPU. Models load once per process.
"""
from __future__ import annotations

import math
import os
import threading
from pathlib import Path

import numpy as np
import soundfile as sf

from .. import config
from ..contracts import Cue, Line, Word
from ..qc.text import align, normalize

SR = 24000
_lock = threading.Lock()
_tts = None
_asr = None


def tts():
    global _tts
    with _lock:
        if _tts is None:
            from kokoro_onnx import Kokoro
            _tts = Kokoro(str(config.KOKORO_MODEL), str(config.KOKORO_VOICES))
        return _tts


def asr():
    global _asr
    with _lock:
        if _asr is None:
            from faster_whisper import WhisperModel
            _asr = WhisperModel(config.WHISPER_MODEL, device="cpu", compute_type="int8",
                                cpu_threads=min(4, os.cpu_count() or 1))
        return _asr


def transcribe(path: Path, prompt: str | None = None) -> list[Word]:
    """Timed words heard in an audio or video file. No hint from the script unless `prompt`."""
    segments, _ = asr().transcribe(str(path), language="en", word_timestamps=True,
                                   beam_size=5, vad_filter=False, initial_prompt=prompt,
                                   condition_on_previous_text=False)
    return [Word(text=w.word.strip(), start=round(w.start, 3), end=round(w.end, 3))
            for seg in segments for w in seg.words]


def synthesize(lines: list[Line], wav: Path, fps: int) -> float:
    """Speak the lines one after the other; pad the scene to a whole number of frames."""
    parts = [np.zeros(int(config.LEAD_IN_S * SR), dtype=np.float32)]
    for i, line in enumerate(lines):
        voice, speed = config.VOICES[line.speaker]
        samples, sr = tts().create(line.text, voice=voice, speed=speed, lang="en-us")
        assert sr == SR, sr
        if i:
            parts.append(np.zeros(int(config.GAP_S * SR), dtype=np.float32))
        parts.append(np.asarray(samples, dtype=np.float32))
    parts.append(np.zeros(int(config.TAIL_S * SR), dtype=np.float32))
    audio = np.concatenate(parts)
    frames = math.ceil(len(audio) / SR * fps)
    target = round(frames * SR / fps)
    audio = np.pad(audio, (0, target - len(audio)))
    wav.parent.mkdir(parents=True, exist_ok=True)
    sf.write(wav, audio, SR, subtype="PCM_16")
    return frames / fps


def time_script_words(lines: list[Line], heard: list[Word], max_words: int = 6) -> tuple[list[Word], list[Cue]]:
    """Give each script word the time it was heard, then group words into subtitle cues.

    Display words keep the script's spelling; timing comes from the transcript.
    Words the transcript missed get times interpolated from their neighbours.
    """
    display: list[tuple[int, str]] = []          # (line index, word as written)
    ref: list[str] = []
    ref_owner: list[int] = []                    # ref token -> display word index
    for li, line in enumerate(lines):
        for word in line.text.split():
            display.append((li, word))
            for tok in normalize(word):
                ref.append(tok)
                ref_owner.append(len(display) - 1)
    hyp: list[str] = []
    hyp_owner: list[int] = []
    for hi, w in enumerate(heard):
        for tok in normalize(w.text):
            hyp.append(tok)
            hyp_owner.append(hi)
    starts: list[float | None] = [None] * len(display)
    ends: list[float | None] = [None] * len(display)
    for ri, hi in enumerate(align(ref, hyp)):
        if hi is None:
            continue
        d, w = ref_owner[ri], heard[hyp_owner[hi]]
        starts[d] = w.start if starts[d] is None else min(starts[d], w.start)
        ends[d] = w.end if ends[d] is None else max(ends[d], w.end)
    _interpolate(starts, ends)
    words = [Word(text=t, start=s, end=e) for (_, t), s, e in zip(display, starts, ends)]

    cues: list[Cue] = []
    chunk: list[int] = []
    for i, (li, _) in enumerate(display):
        chunk.append(i)
        last_of_line = i + 1 == len(display) or display[i + 1][0] != li
        if len(chunk) == max_words or last_of_line:
            cues.append(Cue(text=" ".join(display[j][1] for j in chunk),
                            start=words[chunk[0]].start, end=words[chunk[-1]].end))
            chunk = []
    for a, b in zip(cues, cues[1:]):  # hold a cue on screen until the next one, if close
        if b.start - a.end < 0.5:
            a.end = b.start
    return words, cues


def _interpolate(starts: list[float | None], ends: list[float | None]) -> None:
    known = [i for i, s in enumerate(starts) if s is not None]
    if not known:
        raise ValueError("transcript matches no script word: cannot time subtitles")
    for i in range(len(starts)):
        if starts[i] is not None:
            continue
        before = max((k for k in known if k < i), default=None)
        after = min((k for k in known if k > i), default=None)
        lo = ends[before] if before is not None else max(0.0, starts[after] - 0.3)
        hi = starts[after] if after is not None else ends[before] + 0.3
        starts[i], ends[i] = lo, hi
