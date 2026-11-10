"""Quality gates as pure functions of measurements. Each returns QCCheck(s).

Measurements are taken from the finished file in qc/measure.py; keeping the
decisions here, separate and pure, is what makes each gate unit-testable.
"""
from __future__ import annotations

from ..config import QC
from ..contracts import QCCheck, SceneSlot, Script, Word
from .text import align, normalize, wer


def _scene_of(t: float, slots: list[SceneSlot]) -> str | None:
    for s in slots:
        if s.start <= t < s.start + s.duration:
            return s.scene_id
    return None


def check_transcript(slots: list[SceneSlot], heard: list[Word]) -> list[QCCheck]:
    """What the final file says, transcribed locally, against what the script says."""
    ref_all = [t for s in slots for t in normalize(s.text)]
    hyp_all = [t for w in heard for t in normalize(w.text)]
    total = wer(ref_all, hyp_all)
    per_scene: dict[str, float] = {}
    for s in slots:
        hyp = [t for w in heard if _scene_of((w.start + w.end) / 2, slots) == s.scene_id
               for t in normalize(w.text)]
        per_scene[s.scene_id] = wer(normalize(s.text), hyp)
    worst = max(per_scene, key=per_scene.get)
    return [
        QCCheck(name="transcript_wer_total", passed=total <= QC["wer_total_max"], value=round(total, 4),
                threshold=QC["wer_total_max"], detail=f"{len(ref_all)} script words, {len(hyp_all)} heard"),
        QCCheck(name="transcript_wer_worst_scene", passed=per_scene[worst] <= QC["wer_scene_max"],
                value=round(per_scene[worst], 4), threshold=QC["wer_scene_max"],
                detail=f"worst scene {worst}; " + ", ".join(f"{k}={v:.2f}" for k, v in per_scene.items())),
    ]


def check_durations(slots: list[SceneSlot], video_s: float, audio_s: float) -> list[QCCheck]:
    durs = {s.scene_id: s.duration for s in slots}
    bad = [k for k, d in durs.items() if not QC["scene_min_s"] <= d <= QC["scene_max_s"]]
    drift = abs(video_s - audio_s)
    planned = sum(durs.values())
    return [
        QCCheck(name="scene_durations", passed=not bad, value=float(len(bad)), threshold=0,
                detail=f"allowed {QC['scene_min_s']}-{QC['scene_max_s']} s; "
                       + ", ".join(f"{k}={v:.2f}" for k, v in durs.items())),
        QCCheck(name="video_length", passed=video_s <= QC["video_max_s"] and abs(video_s - planned) <= 0.1,
                value=round(video_s, 3), threshold=QC["video_max_s"], detail=f"planned {planned:.3f} s"),
        QCCheck(name="audio_video_drift", passed=drift <= QC["av_drift_max_s"], value=round(drift, 3),
                threshold=QC["av_drift_max_s"], detail=f"video {video_s:.3f} s, audio {audio_s:.3f} s"),
    ]


def check_legibility(samples: list[dict]) -> list[QCCheck]:
    """samples: one dict per visible text element per sampled instant, measured in the browser
    (keys: scene, text, font_px, contrast, in_frame, opacity)."""
    if not samples:
        return [QCCheck(name="text_present", passed=False, value=0, threshold=1, detail="no text measured")]
    small = min(samples, key=lambda s: s["font_px"])
    low = min(samples, key=lambda s: s["contrast"])
    clipped = [s for s in samples if not s["in_frame"]]
    faded = [s for s in samples if s.get("at_rest", True) and 0.05 < s["opacity"] < 0.99]
    hidden = [s for s in samples if s.get("occluded")]
    return [
        QCCheck(name="text_min_font_px", passed=small["font_px"] >= QC["font_min_px_at_360p"],
                value=small["font_px"], threshold=QC["font_min_px_at_360p"],
                detail=f"{len(samples)} text boxes; smallest {small['text'][:30]!r} in {small['scene']}"),
        QCCheck(name="text_min_contrast", passed=low["contrast"] >= QC["contrast_min"],
                value=round(low["contrast"], 2), threshold=QC["contrast_min"],
                detail=f"lowest {low['text'][:30]!r} in {low['scene']}"),
        QCCheck(name="text_fully_visible", passed=not clipped and not faded and not hidden,
                value=float(len(clipped) + len(faded) + len(hidden)), threshold=0,
                detail=f"{len(clipped)} out of frame, {len(faded)} half-faded at rest, "
                       f"{len(hidden)} covered by another element"
                       + (f" (first: {hidden[0]['text'][:20]!r} in {hidden[0]['scene']})" if hidden else "")),
    ]


def check_nonempty(frame_std: dict[str, float], text_boxes: dict[str, int], black_s: float) -> list[QCCheck]:
    empty = [k for k in frame_std if frame_std[k] < QC["frame_std_min"] or text_boxes.get(k, 0) == 0]
    return [
        QCCheck(name="no_empty_scene", passed=not empty, value=float(len(empty)), threshold=0,
                detail=", ".join(f"{k}: std={frame_std[k]:.1f} text={text_boxes.get(k, 0)}" for k in frame_std)),
        QCCheck(name="no_black_frames", passed=black_s <= QC["black_max_s"], value=round(black_s, 3),
                threshold=QC["black_max_s"], detail="ffmpeg blackdetect d=0.3 pix_th=0.10"),
    ]


def check_sync(slots: list[SceneSlot], heard: list[Word]) -> QCCheck:
    """Each subtitle cue must start when its first word is actually heard in the final file."""
    ref, owner, cues = [], [], []
    for s in slots:
        for c in s.cues:
            for tok in normalize(c.text):
                ref.append(tok)
                owner.append(len(cues))
            cues.append(c)
    hyp, hyp_word = [], []
    for i, w in enumerate(heard):
        for tok in normalize(w.text):
            hyp.append(tok)
            hyp_word.append(i)
    first: dict[int, float] = {}
    matched = [0] * len(cues)
    total = [0] * len(cues)
    for ri, hi in enumerate(align(ref, hyp)):
        total[owner[ri]] += 1
        if hi is not None:
            matched[owner[ri]] += 1
            first.setdefault(owner[ri], heard[hyp_word[hi]].start)
    offsets, unverified = [], 0
    for k, c in enumerate(cues):
        if k not in first or matched[k] < total[k] / 2:
            unverified += 1
            continue
        offsets.append(abs(c.start - first[k]))
    worst = max(offsets, default=float("inf"))
    return QCCheck(name="subtitle_sync", passed=unverified == 0 and worst <= QC["sync_offset_max_s"],
                   value=round(worst, 3), threshold=QC["sync_offset_max_s"],
                   detail=f"{len(cues)} cues, {unverified} not found in the audio")


def check_sources(script: Script) -> QCCheck:
    facts = [l for l in script.lines if l.kind == "fact"]
    ids = {s.id for s in script.sources}
    ok = [l for l in facts if l.source_ids and set(l.source_ids) <= ids]
    return QCCheck(name="facts_sourced", passed=len(ok) == len(facts), value=float(len(facts) - len(ok)),
                   threshold=0, detail=f"{len(facts)} factual lines, {len(script.sources)} sources")
