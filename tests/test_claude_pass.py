"""The live Claude pass with a fake client: no key, no network, no cost.

The fake answers each prompt with the recorded answer made for exactly that prompt
(recordings are keyed by prompt hash), so the agents, contracts and parallel
designers run as they would live.
"""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from vidpipe import config, live_pass
from vidpipe.agents.base import prompt_hash
from vidpipe.agents.claude import ClaudeProvider

FORBIDDEN = {"temperature", "top_p", "top_k"}
RECORDED = {json.loads(p.read_text())["prompt_sha256"]: json.loads(p.read_text())["output"]
            for p in (config.RECORDINGS / "how-to-read-an-invoice").rglob("*.json")}


class FakeMessages:
    def __init__(self, break_first: int = 0):
        self.calls, self.break_first = [], break_first

    def create(self, **kw):
        self.calls.append(kw)
        if self.break_first:          # a contract violation, to exercise the retry
            self.break_first -= 1
            text = "Sure, here is the JSON you asked for."
        else:
            prompt = kw["messages"][0]["content"].split("\n\nYour previous answer was rejected:")[0]
            text = json.dumps(RECORDED[prompt_hash(kw["system"], prompt)])
        return SimpleNamespace(stop_reason="end_turn",
                               content=[SimpleNamespace(type="thinking", thinking=""),
                                        SimpleNamespace(type="text", text=text)],
                               usage=SimpleNamespace(input_tokens=600, output_tokens=250))


def fake_provider(break_first: int = 0) -> ClaudeProvider:
    return ClaudeProvider(client=SimpleNamespace(messages=FakeMessages(break_first)))


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    """Runs, results.md, README.md and claude_pass.json go to a temporary folder."""
    monkeypatch.setattr(config, "RUNS", tmp_path / "runs")
    monkeypatch.setattr(config, "ROOT", tmp_path)
    monkeypatch.setattr(live_pass, "PASS_JSON", tmp_path / "results" / "claude_pass.json")
    for name in ("results.md", "README.md"):
        (tmp_path / name).write_text(f"x\n{live_pass.START}\nold\n{live_pass.END}\ny\n")
    monkeypatch.delenv("VIDPIPE_CLAUDE_MODEL", raising=False)
    return tmp_path


def check_request(kw):
    assert not FORBIDDEN & kw.keys(), "current models reject sampling parameters"
    assert [m["role"] for m in kw["messages"]] == ["user"], "no assistant prefill"
    assert kw["model"] == "claude-haiku-5-5"


def test_estimate_is_offline_and_small():
    e = live_pass.estimate("claude-haiku-5-5")
    assert e["calls"] == 10                      # producer, writer, director, 7 designers
    assert 0 < e["expected_usd"] < e["worst_usd"] < 0.5


def test_live_agent_pass_records_the_claude_line(sandbox, capsys):
    p = fake_provider()
    assert live_pass.main(yes=True, agents_only=True, provider=p) == 0
    assert "Cost estimate, 10 agent calls on claude-haiku-5-5" in capsys.readouterr().out
    assert len(p.client.messages.calls) == 10
    for kw in p.client.messages.calls:
        check_request(kw)
    data = json.loads(live_pass.PASS_JSON.read_text())
    assert (data["agent_calls"], data["retries"], data["contracts_ok"]) == (10, 0, True)
    assert data["input_tokens"] == 6000 and data["cost_usd"] > 0
    for name in ("results.md", "README.md"):
        text = (sandbox / name).read_text()
        assert "Live pass on" in text and "`claude-haiku-5-5`" in text and "old" not in text
    assert (sandbox / "runs" / "how-to-read-an-invoice-claude" / "stages" / "design" / "s07.json").exists()


def test_a_contract_violation_is_retried_and_counted(sandbox):
    p = fake_provider(break_first=1)              # the producer's first answer is not JSON
    assert live_pass.main(yes=True, agents_only=True, provider=p) == 0
    data = json.loads(live_pass.PASS_JSON.read_text())
    assert (data["agent_calls"], data["retries"]) == (11, 1)


def test_a_broken_contract_stops_the_pass_and_is_reported(sandbox):
    p = fake_provider(break_first=2)              # the producer fails twice: no third chance
    assert live_pass.main(yes=True, agents_only=True, provider=p) == 2
    data = json.loads(live_pass.PASS_JSON.read_text())
    assert not data["contracts_ok"] and "producer/idea" in data["error"]
    assert "BROKEN" in (sandbox / "results.md").read_text()


def test_no_confirmation_sends_nothing(sandbox, monkeypatch):
    monkeypatch.setattr("builtins.input", lambda _: "n")
    p = fake_provider()
    assert live_pass.main(agents_only=True, provider=p) == 1
    assert not p.client.messages.calls and not live_pass.PASS_JSON.exists()


def test_the_published_section_says_replay_until_the_pass_is_run():
    assert "Not run yet" in live_pass.section(None)[0]
    assert "replayed" in live_pass.section(None)[0]


@pytest.mark.example
def test_full_live_pass_renders_and_gates_a_video(sandbox):
    """Slow: voice, render and quality gates on the agents' answers (local models)."""
    p = fake_provider()
    code = live_pass.main(yes=True, provider=p)
    data = json.loads(live_pass.PASS_JSON.read_text())
    assert data["video_status"] == "publishable" and code == 0
    assert Path(sandbox / "runs" / "how-to-read-an-invoice-claude" / "final.mp4").exists()
