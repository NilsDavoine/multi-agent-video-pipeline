"""Each quality gate on synthetic measurements: one case that passes, one that must be blocked."""
from vidpipe.contracts import Cue, SceneSlot, Script, Word
from vidpipe.qc import checks
from vidpipe.qc.text import normalize, wer

SLOTS = [
    SceneSlot(scene_id="s01", start=0.0, duration=2.0, text="Check the number first.",
              cues=[Cue(text="Check the number first.", start=0.2, end=1.6)]),
    SceneSlot(scene_id="s02", start=2.0, duration=2.5, text="Then pay once.",
              cues=[Cue(text="Then pay once.", start=2.3, end=3.4)]),
]


def heard(words_and_starts):
    return [Word(text=w, start=t, end=t + 0.25) for w, t in words_and_starts]


GOOD_AUDIO = heard([("Check", 0.2), ("the", 0.45), ("number", 0.7), ("first.", 1.0),
                    ("Then", 2.3), ("pay", 2.6), ("once.", 2.9)])


def by_name(cs):
    return {c.name: c for c in cs}


# --- text helpers -----------------------------------------------------------

def test_normalize_spells_digits_and_drops_punctuation():
    assert normalize("VAT: 17 %, total 4.5!") == ["vat", "seventeen", "total", "four", "point", "five"]


def test_wer_counts_substitutions_insertions_deletions():
    assert wer(["a", "b", "c", "d"], ["a", "x", "c"]) == 0.5
    assert wer(["a"], ["a"]) == 0.0


# --- 1. transcript gate -------------------------------------------------------

def test_transcript_gate_passes_when_voice_matches_script():
    r = by_name(checks.check_transcript(SLOTS, GOOD_AUDIO))
    assert r["transcript_wer_total"].passed and r["transcript_wer_worst_scene"].passed
    assert r["transcript_wer_total"].value == 0


def test_transcript_gate_blocks_a_scene_whose_voice_says_something_else():
    swapped = GOOD_AUDIO[:4] + heard([("Pay", 2.3), ("it", 2.6), ("twice.", 2.9)])
    r = by_name(checks.check_transcript(SLOTS, swapped))
    assert not r["transcript_wer_worst_scene"].passed
    assert "worst scene s02" in r["transcript_wer_worst_scene"].detail


# --- 2. duration gate ---------------------------------------------------------

def test_duration_gate_passes_on_planned_lengths():
    r = by_name(checks.check_durations(SLOTS, video_s=4.5, audio_s=4.52))
    assert all(c.passed for c in r.values())


def test_duration_gate_blocks_short_scene_long_video_and_drift():
    short = [SLOTS[0].model_copy(update={"duration": 0.8}), SLOTS[1]]
    r = by_name(checks.check_durations(short, video_s=3.3, audio_s=3.3))
    assert not r["scene_durations"].passed
    r = by_name(checks.check_durations(SLOTS, video_s=4.5, audio_s=4.9))
    assert not r["audio_video_drift"].passed
    r = by_name(checks.check_durations(SLOTS, video_s=31.0, audio_s=31.0))
    assert not r["video_length"].passed


# --- 3. legibility gate -------------------------------------------------------

def sample(**kw):
    base = {"scene": "s01", "text": "Total", "font_px": 20.0, "contrast": 12.0, "in_frame": True, "opacity": 1.0,
            "occluded": False}
    return base | kw


def test_legibility_gate_passes_on_large_contrasted_text():
    assert all(c.passed for c in checks.check_legibility([sample(), sample(font_px=26, contrast=7)]))


def test_legibility_gate_blocks_small_pale_clipped_or_faded_text():
    r = by_name(checks.check_legibility([sample(), sample(font_px=12)]))
    assert not r["text_min_font_px"].passed
    r = by_name(checks.check_legibility([sample(), sample(contrast=2.1)]))
    assert not r["text_min_contrast"].passed
    r = by_name(checks.check_legibility([sample(in_frame=False)]))
    assert not r["text_fully_visible"].passed
    r = by_name(checks.check_legibility([sample(opacity=0.5)]))
    assert not r["text_fully_visible"].passed
    mid_animation = by_name(checks.check_legibility([sample(opacity=0.5, at_rest=False)]))
    assert mid_animation["text_fully_visible"].passed
    r = by_name(checks.check_legibility([sample(), sample(occluded=True)]))
    assert not r["text_fully_visible"].passed and "1 covered" in r["text_fully_visible"].detail
    assert not checks.check_legibility([])[0].passed


# --- 4. empty-scene gate ------------------------------------------------------

def test_empty_scene_gate():
    ok = by_name(checks.check_nonempty({"s01": 40.0, "s02": 35.0}, {"s01": 3, "s02": 2}, black_s=0.0))
    assert ok["no_empty_scene"].passed and ok["no_black_frames"].passed
    flat = by_name(checks.check_nonempty({"s01": 40.0, "s02": 1.2}, {"s01": 3, "s02": 2}, black_s=0.0))
    assert not flat["no_empty_scene"].passed
    no_text = by_name(checks.check_nonempty({"s01": 40.0, "s02": 35.0}, {"s01": 3, "s02": 0}, black_s=0.0))
    assert not no_text["no_empty_scene"].passed
    black = by_name(checks.check_nonempty({"s01": 40.0}, {"s01": 3}, black_s=0.5))
    assert not black["no_black_frames"].passed


# --- 5. subtitle sync gate ----------------------------------------------------

def test_sync_gate_passes_when_cues_start_with_their_words():
    c = checks.check_sync(SLOTS, GOOD_AUDIO)
    assert c.passed and c.value == 0


def test_sync_gate_blocks_late_subtitles():
    late = [w.model_copy(update={"start": w.start + 0.6, "end": w.end + 0.6}) for w in GOOD_AUDIO]
    c = checks.check_sync(SLOTS, late)
    assert not c.passed and abs(c.value - 0.6) < 1e-6


def test_sync_gate_blocks_cues_missing_from_audio():
    c = checks.check_sync(SLOTS, GOOD_AUDIO[:4])
    assert not c.passed and "1 not found" in c.detail


# --- 6. sourcing gate ---------------------------------------------------------

def test_sources_gate():
    s = Script.model_validate({"title": "t", "sources": [
        {"id": "law", "title": "A law", "url": "https://example.org", "supports": "x"}], "lines": [
        {"speaker": "lead", "kind": "story", "text": "Oh no."},
        {"speaker": "narrator", "kind": "fact", "text": "Rule.", "source_ids": ["law"]}]})
    assert checks.check_sources(s).passed
