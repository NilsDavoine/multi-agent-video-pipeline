"""Command line.

  python -m vidpipe run BRIEF.json [--force STAGE] [--strict-replay]
  python -m vidpipe qc DIR              # re-measure a finished video (run dir or example dir)
  python -m vidpipe export RUN_DIR DEST # copy a run's deliverables (video, pages, QC) to DEST
  python -m vidpipe claude [BRIEF]      # live pass of the agents on Claude, cost estimate first
"""
from __future__ import annotations

import argparse
import json
import logging
import shutil
import subprocess
import sys
from pathlib import Path

from .contracts import RenderOutput, Script, Timeline


def load_finished(d: Path) -> tuple[RenderOutput, Script]:
    timeline = Timeline.model_validate_json((d / "timeline.json").read_text())
    pages = {s.scene_id: str(d / "pages" / f"{s.scene_id}.html") for s in timeline.scenes}
    render = RenderOutput(video=str(d / "final.mp4"), html=pages, timeline=timeline)
    return render, Script.model_validate_json((d / "script.json").read_text())


def contact_sheet(video: Path, timeline: Timeline, out: Path) -> None:
    """One frame from the middle of each scene, tiled."""
    times = [s.start + s.duration * 0.75 for s in timeline.scenes]
    select = "+".join(f"eq(n\\,{round(t * timeline.fps)})" for t in times)
    cols = min(4, len(times))
    rows = -(-len(times) // cols)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(video), "-vf",
                    f"select='{select}',scale=320:-1,tile={cols}x{rows}:padding=4:color=white",
                    "-frames:v", "1", "-q:v", "4", str(out)], check=True)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    ap = argparse.ArgumentParser(prog="vidpipe")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("brief", type=Path)
    r.add_argument("--force", action="append", default=[], help="re-run this stage and everything after it")
    r.add_argument("--strict-replay", action="store_true", help="refuse recordings made for another prompt")
    r.add_argument("--run-dir", type=Path)
    q = sub.add_parser("qc")
    q.add_argument("dir", type=Path)
    e = sub.add_parser("export")
    e.add_argument("run_dir", type=Path)
    e.add_argument("dest", type=Path)
    c = sub.add_parser("claude", help="live pass of the agents on Claude (needs ANTHROPIC_API_KEY)")
    c.add_argument("brief", type=Path, nargs="?")
    c.add_argument("--yes", action="store_true", help="skip the confirmation after the cost estimate")
    c.add_argument("--agents-only", action="store_true", help="stop after the agents: no voice, render or QC")
    a = ap.parse_args(argv)

    if a.cmd == "run":
        from .orchestrator import run
        report, _ = run(a.brief, run_dir=a.run_dir, force=set(a.force), strict_replay=a.strict_replay)
        return 0 if report.passed else 2
    if a.cmd == "claude":
        from .live_pass import main as live
        return live(a.brief, yes=a.yes, agents_only=a.agents_only)
    if a.cmd == "qc":
        from .orchestrator import write_qc
        from .qc.measure import run_qc
        render, script = load_finished(a.dir)
        report, raw = run_qc(render, script)
        write_qc(a.dir, report, raw)
        return 0 if report.passed else 2
    if a.cmd == "export":
        a.dest.mkdir(parents=True, exist_ok=True)
        for name in ("final.mp4", "timeline.json", "script.json", "qc.json", "run.json"):
            shutil.copy2(a.run_dir / name, a.dest / name)
        shutil.copytree(a.run_dir / "pages", a.dest / "pages", dirs_exist_ok=True)
        timeline = Timeline.model_validate_json((a.dest / "timeline.json").read_text())
        contact_sheet(a.dest / "final.mp4", timeline, a.dest / "contact_sheet.jpg")
        print(json.dumps({"exported": str(a.dest)}))
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
