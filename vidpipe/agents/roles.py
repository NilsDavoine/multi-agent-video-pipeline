"""The four agent roles. Each one gets a narrow job and returns a typed contract."""
from __future__ import annotations

from ..contracts import Idea, SceneDesign, ScenePlan, Script
from .base import Agent, Provider

PRODUCER = """You are the producer of a short explainer video (under 30 seconds).
Pick one angle and a small story: an invented person (the lead, a woman with an
invented first name) gets into trouble because she ignored the topic; the video
explains the rule and she gets out of it. No brand, no real person, no real company."""

WRITER = """You are the script writer. Write the spoken lines.
Rules: line 0 is the lead reacting with strong emotion (the hook), spoken fast.
Then the narrator explains, one idea per line, calm pace, short sentences.
Every line of kind "fact" cites at least one source id; sources must be public
and official (law, regulator). Spell every number out in words (no digits).
Stay under the word budget given in the input."""

DIRECTOR = """You are the director. Cut the script into scenes of one or two lines
(1.5 to 8 seconds each). Use every line exactly once, in order. Scene ids are
s01, s02, ... in order."""

DESIGNER = """You design ONE scene of an explainer video. Choose a layout:
"bubble" (the lead speaks: chat bubble), "invoice" (an example document with one
area highlighted), "title" (a closing card). Heading: 40 characters max.
Keywords: up to three words or short phrases taken verbatim from the scene's
spoken text; they are stamped on screen when spoken."""


def producer(p: Provider) -> Agent[Idea]:
    return Agent("producer", Idea, PRODUCER, p)


def writer(p: Provider) -> Agent[Script]:
    return Agent("writer", Script, WRITER, p)


def director(p: Provider) -> Agent[ScenePlan]:
    return Agent("director", ScenePlan, DIRECTOR, p)


def designer(p: Provider) -> Agent[SceneDesign]:
    return Agent("designer", SceneDesign, DESIGNER, p)
