"""Typed contracts between pipeline stages.

Every stage reads and writes one of these models. A stage output that does not
validate never reaches the next stage: agents get one retry with the error, the
replay provider fails loudly.
"""
from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


class Brief(BaseModel):
    slug: str = Field(pattern=r"^[a-z0-9-]+$")
    topic: str
    audience: str
    max_seconds: float = Field(gt=0, le=60)
    fps: int = 24
    width: int = 640
    height: int = 360


# ---- agent outputs -------------------------------------------------------

class Idea(BaseModel):
    title: str = Field(max_length=80)
    lead_name: str = Field(description="invented first name of the person the story follows")
    hook: str
    angle: str
    key_points: list[str] = Field(min_length=2, max_length=5)


class Source(BaseModel):
    id: str = Field(pattern=r"^[a-z0-9-]+$")
    title: str
    url: str = Field(pattern=r"^https://")
    supports: str = Field(description="what exactly this source backs up")


class Line(BaseModel):
    speaker: Literal["lead", "narrator"]
    kind: Literal["story", "fact", "cta"]
    text: str = Field(min_length=1, max_length=160)
    source_ids: list[str] = Field(default_factory=list)

    @field_validator("text")
    @classmethod
    def numbers_spelled_out(cls, v: str) -> str:
        # Spoken text is compared word by word with a transcript: digits are ambiguous.
        if re.search(r"\d", v):
            raise ValueError("spell numbers out in spoken text")
        return v


class Script(BaseModel):
    title: str
    lines: list[Line] = Field(min_length=2)
    sources: list[Source]

    @model_validator(mode="after")
    def facts_are_sourced(self) -> "Script":
        ids = {s.id for s in self.sources}
        for i, line in enumerate(self.lines):
            if line.kind == "fact" and not line.source_ids:
                raise ValueError(f"line {i} is a fact without a source")
            missing = set(line.source_ids) - ids
            if missing:
                raise ValueError(f"line {i} cites unknown sources {sorted(missing)}")
        if self.lines[0].speaker != "lead":
            raise ValueError("the hook (line 0) must be spoken by the lead character")
        return self

    @property
    def text(self) -> str:
        return " ".join(line.text for line in self.lines)


class SceneSpec(BaseModel):
    id: str = Field(pattern=r"^s\d\d$")
    line_indices: list[int] = Field(min_length=1)
    purpose: str


class ScenePlan(BaseModel):
    scenes: list[SceneSpec] = Field(min_length=1)

    def check_against(self, script: Script) -> None:
        """Cross-contract rule: every script line is used exactly once, in order."""
        used = [i for s in self.scenes for i in s.line_indices]
        if used != list(range(len(script.lines))):
            raise ValueError(f"scene plan covers lines {used}, expected 0..{len(script.lines) - 1} in order")
        ids = [s.id for s in self.scenes]
        if len(set(ids)) != len(ids):
            raise ValueError("duplicate scene ids")


class SceneDesign(BaseModel):
    scene_id: str = Field(pattern=r"^s\d\d$")
    layout: Literal["bubble", "invoice", "title"]
    heading: str = Field(min_length=1, max_length=40)
    keywords: list[str] = Field(default_factory=list, max_length=3)
    highlight: Literal["none", "number", "parties", "items", "vat"] = "none"
    accent: Literal["blue", "green", "orange", "red"] = "blue"

    def check_against(self, scene_text: str) -> None:
        """Keywords are stamped on screen when they are spoken, so they must be in the voice text."""
        low = scene_text.lower()
        for k in self.keywords:
            if k.lower() not in low:
                raise ValueError(f"keyword {k!r} is not spoken in scene {self.scene_id}")


# ---- media stages ----------------------------------------------------------

class Word(BaseModel):
    text: str
    start: float
    end: float


class Cue(BaseModel):
    text: str
    start: float
    end: float


class SceneAudio(BaseModel):
    scene_id: str
    wav: str
    duration: float = Field(gt=0)
    words: list[Word]  # script words, timed by local ASR alignment (scene-relative seconds)
    cues: list[Cue]    # subtitle cues (scene-relative seconds)
    text: str          # what the voice was asked to say


class SceneSlot(BaseModel):
    scene_id: str
    start: float
    duration: float
    text: str
    cues: list[Cue]  # absolute seconds in the final video


class Clip(BaseModel):
    path: str


class Timeline(BaseModel):
    fps: int
    width: int
    height: int
    scenes: list[SceneSlot]

    @property
    def duration(self) -> float:
        return round(sum(s.duration for s in self.scenes), 4)


class RenderOutput(BaseModel):
    video: str
    html: dict[str, str]  # scene_id -> html path
    timeline: Timeline


# ---- quality control -------------------------------------------------------

class QCCheck(BaseModel):
    name: str
    passed: bool
    value: float
    threshold: float
    detail: str = ""


class QCReport(BaseModel):
    video: str
    checks: list[QCCheck]

    @property
    def passed(self) -> bool:
        return all(c.passed for c in self.checks)
