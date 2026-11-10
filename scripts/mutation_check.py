"""Mutation test of the transcript guard, on the committed example itself.

1. back up the example video (a copy, with its hash)
2. damage it: scene s03's voice now says something off-script
3. the guard test (pytest -m example -k transcript) must go RED
4. restore from the backup copy (not from git) and check the hash
5. the same test must be GREEN again
Writes results/mutation.json (read by make_results.py).
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from vidpipe.__main__ import load_finished  # noqa: E402
from vidpipe.config import ROOT  # noqa: E402
from vidpipe.mutation import OFF_SCRIPT, replace_scene_voice  # noqa: E402
from vidpipe.qc.measure import run_qc  # noqa: E402
from vidpipe.store import file_digest  # noqa: E402

EX = ROOT / "examples" / "how-to-read-an-invoice"
TEST = [sys.executable, "-m", "pytest", "-q", "-m", "example", "-k", "transcript_matches_script",
        "tests/test_example_video.py"]


def guard_test() -> int:
    return subprocess.run(TEST, cwd=ROOT, capture_output=True, text=True).returncode


def main() -> int:
    video = EX / "final.mp4"
    with tempfile.TemporaryDirectory() as tmp:
        backup = Path(tmp) / "final.mp4.bak"
        shutil.copy2(video, backup)
        original = file_digest(video)
        try:
            render, script = load_finished(EX)
            replace_scene_voice(video, render.timeline, "s03", video)
            mutated = file_digest(video)
            rep, _ = run_qc(render, script)
            gate = {c.name: c.model_dump() for c in rep.checks if c.name.startswith("transcript")}
            red = guard_test()
        finally:
            shutil.copy2(backup, video)
        restored = file_digest(video)
    green = guard_test()
    out = {
        "when": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "mutation": f"scene s03 voice replaced by: {OFF_SCRIPT!r}",
        "video_sha256": {"original": original, "mutated": mutated, "restored": restored},
        "restored_identical": restored == original,
        "gate_on_mutated_video": gate,
        "status_on_mutated_video": "publishable" if rep.passed else "blocked",
        "guard_test_exit_code": {"mutated": red, "restored": green},
        "guard_works": red != 0 and green == 0 and restored == original and not rep.passed,
    }
    (ROOT / "results" / "mutation.json").write_text(json.dumps(out, indent=2))
    print(json.dumps(out, indent=2))
    return 0 if out["guard_works"] else 1


if __name__ == "__main__":
    sys.exit(main())
