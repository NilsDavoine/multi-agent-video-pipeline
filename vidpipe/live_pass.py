"""A live pass of the agents with Claude, instead of the replayed answers.

    python -m vidpipe claude [BRIEF] [--yes] [--agents-only]

1. Estimates the cost offline, from the prompts the agents send on the example
   (replayed, so no call and no key), and waits for a yes.
2. Runs the four agents on Claude (default claude-haiku-5-5, VIDPIPE_CLAUDE_MODEL to
   change), into runs/<slug>-claude/, recording every answer to recordings/<slug>-claude/.
   The hand-written recordings of the published example are left untouched.
3. Unless --agents-only, continues with the local stages (voice, render, quality gates)
   on what Claude wrote, exactly as `vidpipe run` does.
4. Writes results/claude_pass.json and the "Live agent pass" section of results.md
   and README.md.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import tempfile
from pathlib import Path

from . import config
from .agents import AgentError, ReplayProvider
from .agents.claude import MAX_TOKENS, PRICES, ClaudeProvider
from .contracts import Brief
from .store import StageStore

log = logging.getLogger("vidpipe")
EXAMPLE = config.ROOT / "examples" / "how-to-read-an-invoice" / "brief.json"
PASS_JSON = config.ROOT / "results" / "claude_pass.json"
CHARS_PER_TOKEN = 3.0        # deliberately low: JSON schemas tokenise densely, over-estimates
THINKING_ALLOWANCE = 500     # output tokens per call on top of the answer, at effort "low"
START, END = "<!-- claude:start -->", "<!-- claude:end -->"


class _Measuring(ReplayProvider):
    """Replays the example and notes the size of every prompt and answer."""

    def __init__(self, root: Path):
        super().__init__(root)
        self.sizes: list[tuple[int, int]] = []

    def complete(self, role, key, system, prompt):
        out = super().complete(role, key, system, prompt)
        self.sizes.append((len(system) + len(prompt), len(out)))
        return out


def estimate(model: str) -> dict:
    """Offline: replays the example's agents and prices their prompts. No network."""
    brief = Brief.model_validate_json(EXAMPLE.read_text())
    from .orchestrator import run_agents
    probe = _Measuring(config.RECORDINGS / brief.slug)
    with tempfile.TemporaryDirectory() as tmp:
        run_agents(brief, StageStore(Path(tmp)), probe)
    price_in, price_out = PRICES.get(model, (0.0, 0.0))
    tok_in = sum(i for i, _ in probe.sizes) / CHARS_PER_TOKEN
    tok_out = sum(o / CHARS_PER_TOKEN + THINKING_ALLOWANCE for _, o in probe.sizes)
    calls = len(probe.sizes)
    # Worst case: every agent breaks its contract once (the retry re-sends a longer
    # prompt) and every answer runs to max_tokens.
    worst_in, worst_out = 2.2 * tok_in, 2 * calls * MAX_TOKENS
    usd = lambda i, o: (i * price_in + o * price_out) / 1e6
    return {"model": model, "calls": calls, "tokens_in": tok_in, "tokens_out": tok_out,
            "expected_usd": usd(tok_in, tok_out), "worst_in": worst_in, "worst_out": worst_out,
            "worst_usd": usd(worst_in, worst_out), "price_in": price_in, "price_out": price_out}


def print_estimate(e: dict) -> None:
    print(f"Cost estimate, {e['calls']} agent calls on {e['model']} "
          f"(${e['price_in']:.2f} / ${e['price_out']:.2f} per 1M input / output tokens), "
          f"measured on the example's prompts:\n"
          f"  expected  : {e['tokens_in']:,.0f} in + {e['tokens_out']:,.0f} out  ~ ${e['expected_usd']:.3f}\n"
          f"  worst case: {e['worst_in']:,.0f} in + {e['worst_out']:,.0f} out  ~ ${e['worst_usd']:.3f}"
          f"  (one retry per agent, every answer at max_tokens)\n"
          f"Voice, rendering and quality gates run locally and cost nothing.", flush=True)


def summarise(provider: ClaudeProvider, agents_only: bool, error: str | None, report=None) -> dict:
    seen: dict[tuple[str, str], int] = {}
    for c in provider.calls:
        seen[(c["role"], c["key"])] = seen.get((c["role"], c["key"]), 0) + 1
    data = {
        "date": dt.date.today().isoformat(), "model": provider.model,
        "agent_calls": len(provider.calls), "agents": len(seen),
        "retries": sum(n - 1 for n in seen.values()),
        "contracts_ok": error is None,
        "error": error,
        "input_tokens": sum(c["input_tokens"] for c in provider.calls),
        "output_tokens": sum(c["output_tokens"] for c in provider.calls),
        "cost_usd": round(provider.cost(), 4),
        "agents_only": agents_only,
        "calls": provider.calls,
    }
    if report is not None:
        data["video_status"] = "publishable" if report.passed else "blocked"
        data["failed_gates"] = [c.name for c in report.checks if not c.passed]
    return data


def section(data: dict | None) -> list[str]:
    """The 'Live agent pass' lines, for results.md and README.md."""
    if not data:
        return ["**Not run yet.** The published example video was made from the replayed, hand-written "
                "agent answers in `recordings/`; no live Claude call was made for it. "
                "`python -m vidpipe claude` runs the live pass and fills this section."]
    lines = [f"Live pass on {data['date']} with `{data['model']}`: {data['agent_calls']} calls for "
             f"{data['agents']} agent tasks, {data['retries']} contract retries, "
             f"contracts {'all valid' if data['contracts_ok'] else 'BROKEN: ' + str(data['error'])}, "
             f"{data['input_tokens']:,} input + {data['output_tokens']:,} output tokens, "
             f"${data['cost_usd']:.4f}."]
    if "video_status" in data:
        failed = ", ".join(f"`{g}`" for g in data["failed_gates"]) or "none"
        lines.append(f"Video made from Claude's answers (`runs/<slug>-claude/final.mp4`, not committed): "
                     f"**{data['video_status']}**; failing gates: {failed}.")
    elif data["agents_only"]:
        lines.append("Agents only (`--agents-only`): no video was rendered from these answers.")
    lines.append("The committed example video still comes from the replayed answers.")
    return lines


def write_section(path: Path, data: dict | None) -> None:
    text = path.read_text()
    if START not in text:
        return
    head, rest = text.split(START, 1)
    _, tail = rest.split(END, 1)
    path.write_text(head + START + "\n" + "\n\n".join(section(data)) + "\n" + END + tail)


def load() -> dict | None:
    return json.loads(PASS_JSON.read_text()) if PASS_JSON.exists() else None


def main(brief_path: Path | None = None, yes: bool = False, agents_only: bool = False,
         provider: ClaudeProvider | None = None) -> int:
    brief_path = brief_path or EXAMPLE
    import os
    model = provider.model if provider else os.environ.get("VIDPIPE_CLAUDE_MODEL", "claude-haiku-5-5")
    print_estimate(estimate(model))
    if provider is None and not os.environ.get("ANTHROPIC_API_KEY"):
        print("set ANTHROPIC_API_KEY (and install anthropic) to run the live pass")
        return 1
    if not yes and input("Run it, billed to your key? [y/N] ").strip().lower() not in ("y", "yes"):
        print("Cancelled, nothing was sent.")
        return 1

    brief = Brief.model_validate_json(brief_path.read_text())
    run_dir = config.RUNS / f"{brief.slug}-claude"
    provider = provider or ClaudeProvider(record_root=config.RECORDINGS / f"{brief.slug}-claude", record=True)
    error, report = None, None
    try:
        if agents_only:
            from .orchestrator import run_agents
            run_agents(brief, StageStore(run_dir), provider)
        else:
            from .orchestrator import run
            report, _ = run(brief_path, run_dir=run_dir, provider=provider)
    except (AgentError, ValueError) as exc:   # a broken contract stops the run: reported, not hidden
        error = str(exc).splitlines()[0]
    data = summarise(provider, agents_only, error, report)
    PASS_JSON.parent.mkdir(parents=True, exist_ok=True)
    PASS_JSON.write_text(json.dumps(data, indent=2))
    for path in (config.ROOT / "results.md", config.ROOT / "README.md"):
        write_section(path, data)
    print("\n".join(section(data)))
    return 0 if error is None and (report is None or report.passed) else 2
