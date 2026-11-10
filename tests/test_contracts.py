import pytest
from pydantic import ValidationError

from vidpipe.contracts import Line, SceneDesign, ScenePlan, Script

SRC = [{"id": "law", "title": "A law", "url": "https://example.org/law", "supports": "the rule"}]


def script(lines, sources=SRC):
    return Script.model_validate({"title": "t", "lines": lines, "sources": sources})


def test_fact_without_source_is_rejected():
    with pytest.raises(ValidationError, match="fact without a source"):
        script([{"speaker": "lead", "kind": "story", "text": "Oh no."},
                {"speaker": "narrator", "kind": "fact", "text": "The rule is this."}])


def test_unknown_source_is_rejected():
    with pytest.raises(ValidationError, match="unknown sources"):
        script([{"speaker": "lead", "kind": "story", "text": "Oh no."},
                {"speaker": "narrator", "kind": "fact", "text": "Rule.", "source_ids": ["nope"]}])


def test_hook_must_be_the_lead():
    with pytest.raises(ValidationError, match="hook"):
        script([{"speaker": "narrator", "kind": "story", "text": "Hello."},
                {"speaker": "lead", "kind": "story", "text": "Hi."}])


def test_digits_in_spoken_text_are_rejected():
    with pytest.raises(ValidationError, match="spell numbers out"):
        Line(speaker="narrator", kind="story", text="Pay 200 euros.")


def test_scene_plan_must_cover_every_line_in_order():
    s = script([{"speaker": "lead", "kind": "story", "text": "Oh no."},
                {"speaker": "narrator", "kind": "fact", "text": "Rule.", "source_ids": ["law"]}])
    ScenePlan.model_validate({"scenes": [{"id": "s01", "line_indices": [0, 1], "purpose": "x"}]}).check_against(s)
    bad = ScenePlan.model_validate({"scenes": [{"id": "s01", "line_indices": [1, 0], "purpose": "x"}]})
    with pytest.raises(ValueError, match="in order"):
        bad.check_against(s)


def test_design_keywords_must_be_spoken():
    d = SceneDesign(scene_id="s01", layout="title", heading="h", keywords=["total"])
    d.check_against("Check the total.")
    with pytest.raises(ValueError, match="not spoken"):
        SceneDesign(scene_id="s01", layout="title", heading="h", keywords=["discount"]).check_against("Check the total.")
