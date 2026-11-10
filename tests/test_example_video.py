"""Every gate, measured for real on the committed example video (local ASR + headless Chrome).

Run:  pytest -m example
The mutation test at the bottom proves the transcript gate blocks a video whose
voice no longer matches the script.
"""
from pathlib import Path

import pytest

from vidpipe.__main__ import load_finished
from vidpipe.config import ROOT

EXAMPLE = Path(ROOT / "examples" / "how-to-read-an-invoice")
pytestmark = pytest.mark.example


@pytest.fixture(scope="module")
def report():
    from vidpipe.qc.measure import run_qc
    render, script = load_finished(EXAMPLE)
    rep, _ = run_qc(render, script)
    return {c.name: c for c in rep.checks}


def test_transcript_matches_script(report):
    assert report["transcript_wer_total"].passed, report["transcript_wer_total"]
    assert report["transcript_wer_worst_scene"].passed, report["transcript_wer_worst_scene"]


def test_scene_and_video_durations(report):
    for name in ("scene_durations", "video_length", "audio_video_drift"):
        assert report[name].passed, report[name]


def test_text_is_legible(report):
    for name in ("text_min_font_px", "text_min_contrast", "text_fully_visible"):
        assert report[name].passed, report[name]


def test_no_empty_scene(report):
    assert report["no_empty_scene"].passed, report["no_empty_scene"]
    assert report["no_black_frames"].passed, report["no_black_frames"]


def test_subtitles_in_sync_with_voice(report):
    assert report["subtitle_sync"].passed, report["subtitle_sync"]


def test_facts_are_sourced(report):
    assert report["facts_sourced"].passed, report["facts_sourced"]


def test_off_script_voice_is_blocked(tmp_path):
    """Mutation: scene s03 now says something else. The video must be blocked."""
    import shutil

    from vidpipe.mutation import replace_scene_voice
    from vidpipe.qc.measure import run_qc

    shutil.copytree(EXAMPLE, tmp_path / "ex")
    render, script = load_finished(tmp_path / "ex")
    replace_scene_voice(Path(render.video), render.timeline, "s03", Path(render.video))
    rep, _ = run_qc(render, script)
    checks = {c.name: c for c in rep.checks}
    assert not rep.passed
    assert not checks["transcript_wer_worst_scene"].passed
    assert "worst scene s03" in checks["transcript_wer_worst_scene"].detail
    # the damage is invisible to every non-audio gate
    assert checks["scene_durations"].passed and checks["no_empty_scene"].passed
