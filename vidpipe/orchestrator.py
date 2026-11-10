"""The pipeline: brief -> idea -> script -> scene plan -> designs (parallel) -> voice
-> scene pages -> render (parallel) -> assembly -> quality gates.

Every step goes through StageStore, so a re-run only redoes what changed or failed.
Nothing is ever published: a run ends with `status: publishable` or `status: blocked`
in qc.json, and a human decides.
"""
from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import config
from .agents import get_provider
from .agents import roles
from .contracts import (Brief, Clip, Cue, Idea, QCReport, RenderOutput, SceneAudio, SceneDesign, ScenePlan,
                        SceneSlot, Script, Timeline)
from .stages import html as html_stage
from .stages import render as render_stage
from .stages import speech
from .store import StageStore, digest

log = logging.getLogger("vidpipe")
STAGES = ["idea", "script", "plan", "design", "voice", "page", "render", "assemble", "qc"]
WORDS_PER_SECOND = 2.4  # budget for the writer, from the voices' measured pace


def run(brief_path: Path, run_dir: Path | None = None, force: set[str] | None = None,
        workers: int = 3, strict_replay: bool = False, provider=None) -> tuple[QCReport, StageStore]:
    brief = Brief.model_validate_json(brief_path.read_text())
    run_dir = run_dir or config.RUNS / brief.slug
    store = StageStore(run_dir, force=_downstream(force or set()))
    provider = provider or get_provider(config.RECORDINGS / brief.slug, strict_replay=strict_replay)
    idea, script, plan, designs = run_agents(brief, store, provider, workers)

    def scene_text(spec) -> str:
        return " ".join(script.lines[i].text for i in spec.line_indices)

    # 5. Voice + word timing, per scene (local models, one load).
    def voice(spec) -> SceneAudio:
        lines = [script.lines[i] for i in spec.line_indices]

        def make() -> SceneAudio:
            wav = run_dir / "audio" / f"{spec.id}.wav"
            dur = speech.synthesize(lines, wav, brief.fps)
            heard = speech.transcribe(wav, prompt=scene_text(spec))
            words, cues = speech.time_script_words(lines, heard)
            return SceneAudio(scene_id=spec.id, wav=str(wav), duration=dur, words=words, cues=cues,
                              text=scene_text(spec))
        return store.run(f"voice/{spec.id}", SceneAudio,
                         digest([l.model_dump() for l in lines], config.VOICES, brief.fps, config.WHISPER_MODEL),
                         make, files=lambda a: [a.wav])

    with config.heavy_lock():  # one lock for the whole stage: models load once
        audios = [voice(s) for s in plan.scenes]

    # 6. Scene pages from the fixed template.
    pages: dict[str, str] = {}
    for spec, d, a in zip(plan.scenes, designs, audios):
        lead_words = sum(len(script.lines[i].text.split()) for i in spec.line_indices
                         if script.lines[i].speaker == "lead")
        page = html_stage.build_scene(d, a.words, a.cues, a.duration, idea.lead_name, lead_words,
                                      brief.width, brief.height)
        path = run_dir / "pages" / f"{spec.id}.html"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(page)
        pages[spec.id] = str(path)

    # 7. Render scenes in parallel (each in its own headless browser).
    def clip(spec, audio: SceneAudio) -> Path:
        out = run_dir / "clips" / f"{spec.id}.mp4"
        rec = store.run(f"render/{spec.id}", Clip, digest(Path(pages[spec.id]), audio.duration, brief),
                        lambda: Clip(path=str(render_stage.render_scene(
                            Path(pages[spec.id]), out, audio.duration, brief.fps, brief.width, brief.height))),
                        files=lambda c: [c.path])
        return Path(rec.path)

    with config.heavy_lock(), ThreadPoolExecutor(min(workers, 2)) as pool:
        clips = list(pool.map(clip, plan.scenes, audios))

    # 8. Timeline + assembly.
    slots, t = [], 0.0
    for spec, a in zip(plan.scenes, audios):
        slots.append(SceneSlot(scene_id=spec.id, start=round(t, 4), duration=a.duration, text=a.text,
                               cues=[Cue(text=c.text, start=round(c.start + t, 3), end=round(c.end + t, 3))
                                     for c in a.cues]))
        t += a.duration
    timeline = Timeline(fps=brief.fps, width=brief.width, height=brief.height, scenes=slots)
    final = run_dir / "final.mp4"
    render_out = store.run(
        "assemble", RenderOutput, digest([str(c) for c in clips], [Path(c) for c in clips],
                                         [Path(a.wav) for a in audios]),
        lambda: RenderOutput(video=str(render_stage.assemble(clips, [Path(a.wav) for a in audios], final)),
                             html=pages, timeline=timeline),
        files=lambda r: [r.video])
    (run_dir / "timeline.json").write_text(timeline.model_dump_json(indent=2))
    (run_dir / "script.json").write_text(script.model_dump_json(indent=2))

    # 9. Quality gates on the finished file.
    from .qc.measure import run_qc
    report, raw = run_qc(render_out, script)
    write_qc(run_dir, report, raw)
    stale = getattr(provider, "stale", [])
    (run_dir / "run.json").write_text(json.dumps(
        {"provider": provider.name, "stale_recordings": stale, "events": store.events}, indent=2))
    return report, store


def run_agents(brief: Brief, store: StageStore, provider, workers: int = 3
               ) -> tuple[Idea, Script, ScenePlan, list[SceneDesign]]:
    """Steps 1-4, the agents only: idea, script, scene plan, one design per scene."""
    # 1-3. Sequential roles: each one needs the previous contract.
    idea = store.run("idea", Idea, digest(brief, provider.name),
                     lambda: roles.producer(provider).run("idea", brief.model_dump()))
    script = store.run("script", Script, digest(idea, provider.name), lambda: roles.writer(provider).run(
        "script", {"idea": idea.model_dump(), "max_words": int(brief.max_seconds * WORDS_PER_SECOND * 0.85)}))
    plan = store.run("plan", ScenePlan, digest(script, provider.name),
                     lambda: roles.director(provider).run("plan", script.model_dump()))
    plan.check_against(script)

    def scene_text(spec) -> str:
        return " ".join(script.lines[i].text for i in spec.line_indices)

    # 4. One designer agent per scene, in parallel.
    def design(spec) -> SceneDesign:
        payload = {"scene": spec.model_dump(), "spoken_text": scene_text(spec),
                   "speakers": [script.lines[i].speaker for i in spec.line_indices], "lead_name": idea.lead_name}

        def make() -> SceneDesign:
            d = roles.designer(provider).run(spec.id, payload)
            if d.scene_id != spec.id:
                raise ValueError(f"designer answered for {d.scene_id}, asked {spec.id}")
            d.check_against(scene_text(spec))
            return d
        return store.run(f"design/{spec.id}", SceneDesign, digest(payload, provider.name), make)

    with ThreadPoolExecutor(workers) as pool:
        designs = list(pool.map(design, plan.scenes))
    return idea, script, plan, designs


def write_qc(run_dir: Path, report: QCReport, raw: dict) -> None:
    status = "publishable" if report.passed else "blocked"
    (run_dir / "qc.json").write_text(json.dumps(
        {"status": status, **report.model_dump(mode="json")}, indent=2))
    (run_dir / "qc_measurements.json").write_text(json.dumps(raw, indent=1))
    for c in report.checks:
        log.info("%s %-28s value=%-8s threshold=%-6s %s", "PASS" if c.passed else "FAIL",
                 c.name, c.value, c.threshold, c.detail)
    log.info("status: %s", status.upper())


def _downstream(force: set[str]) -> set[str]:
    """Forcing a stage also forces every stage after it."""
    if not force:
        return set()
    first = min(STAGES.index(f) for f in force)
    return set(STAGES[first:])
