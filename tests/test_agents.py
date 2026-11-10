import json

import pytest

from vidpipe.agents import Agent, AgentError, ReplayProvider
from vidpipe.agents.base import prompt_hash
from vidpipe.contracts import SceneDesign

GOOD = {"scene_id": "s01", "layout": "title", "heading": "Hello"}


class Scripted:
    """A live provider that returns canned answers in order."""
    name, live = "scripted", True

    def __init__(self, answers):
        self.answers, self.prompts = list(answers), []

    def complete(self, role, key, system, prompt):
        self.prompts.append(prompt)
        return self.answers.pop(0)


def test_live_agent_gets_one_retry_with_the_validation_error():
    p = Scripted(['{"scene_id": "s01", "layout": "carousel", "heading": "x"}', "Sure! " + json.dumps(GOOD)])
    out = Agent("designer", SceneDesign, "sys", p).run("s01", {})
    assert out.heading == "Hello"
    assert "rejected" in p.prompts[1]


def test_live_agent_fails_after_second_violation():
    p = Scripted(["not json", "still not json"])
    with pytest.raises(AgentError):
        Agent("designer", SceneDesign, "sys", p).run("s01", {})


def _record(tmp_path, sha):
    (tmp_path / "designer").mkdir()
    (tmp_path / "designer" / "s01.json").write_text(json.dumps({"prompt_sha256": sha, "output": GOOD}))


def test_replay_returns_the_recording(tmp_path):
    _record(tmp_path, "stale")
    rp = ReplayProvider(tmp_path)
    assert Agent("designer", SceneDesign, "sys", rp).run("s01", {}).heading == "Hello"
    assert rp.stale == ["designer/s01"]


def test_strict_replay_refuses_a_recording_made_for_another_prompt(tmp_path):
    _record(tmp_path, "stale")
    with pytest.raises(AgentError, match="different prompt"):
        Agent("designer", SceneDesign, "sys", ReplayProvider(tmp_path, strict=True)).run("s01", {})


def test_strict_replay_accepts_a_matching_recording(tmp_path):
    agent = Agent("designer", SceneDesign, "sys", Scripted([json.dumps(GOOD)]))
    agent.run("s01", {})
    _record(tmp_path, prompt_hash("sys", agent.provider.prompts[0]))
    assert Agent("designer", SceneDesign, "sys", ReplayProvider(tmp_path, strict=True)).run("s01", {})


def test_missing_recording_fails_loudly(tmp_path):
    with pytest.raises(AgentError, match="no recording"):
        Agent("designer", SceneDesign, "sys", ReplayProvider(tmp_path)).run("s09", {})
