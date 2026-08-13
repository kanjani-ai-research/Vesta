"""Scoring a battery of runs across both arms.

Three briefs, two arms, one standard. What is measured is time, quality and
cost — not token count, which says nothing on its own about either what a run
cost or what it produced.

**Cost is money, not tokens.** A run is priced at the published rates for the
model that did the work, so a cheaper model doing more work can cost less than
a dearer one doing less. Token counts are kept because they are the evidence,
but the number that matters is dollars.

**Quality is what a stranger could check.** Whether the tests pass, what is
wrong with the code by the crudest possible reading — bare excepts, swallowed
failures, dead code — and two things about the run rather than the artifact:

- *how many times the user had to say something*, because an answer that takes
  sixteen interventions is worse than the same answer taking one, whatever the
  code looks like at the end
- *how much was produced per intervention*, because volume without direction is
  not quality either

Nothing here uses Vesta: scoring the arm that ships Vesta with Vesta's own
measurements would show only that a tool agrees with itself.

**And the briefs carry a curveball each.** A todo list, a pomodoro timer and a
markdown outliner are shapes a model has seen ten thousand times, and a battery
of them measures recall rather than method — both arms produce something fluent
and the comparison says nothing. So each brief ends with a requirement that
cannot be pattern-matched from the familiar shape: a timer that must resume in
real elapsed time, an outliner that must not see headings inside code fences, a
ledger with an inferred blank posting and per-currency balancing. Each is
checkable, and each is a place a plausible implementation is wrong.

**Time is what the tool spent, not what the clock did.** The span between a
transcript's first and last record includes every pause where somebody was
reading, switching windows, or had walked away — on the first ledger run that
was 209 seconds out of 360, and reporting the span made one arm look 2.75×
faster when the real figure was 1.45×. So gaps longer than a person's attention
are excluded, and both numbers are reported: a reader can see how much of the
elapsed time was anybody working.

Every transcript for a project is read, not the most recent one. Picking one by
modification time reports whichever file happened to be touched last, which is
not the same as the run being measured.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

# Published rates, dollars per million tokens. Stated here so a reader can
# check the arithmetic rather than take a total on trust.
RATES = {
    "claude-sonnet-5": {"in": 3.00, "out": 15.00, "cache_read": 0.30, "cache_write": 3.75},
    "claude-haiku-4-5": {"in": 1.00, "out": 5.00, "cache_read": 0.10, "cache_write": 1.25},
    "claude-opus-5": {"in": 15.00, "out": 75.00, "cache_read": 1.50, "cache_write": 18.75},
}


# A pause longer than this is somebody reading rather than a tool working.
# Twenty seconds is well past any single model response and well short of the
# time it takes to read a page of output and decide what to do.
IDLE_AFTER = 20.0


def _rate(model: str) -> Dict[str, float]:
    for name, rates in RATES.items():
        if name in model:
            return rates
    return RATES["claude-sonnet-5"]


def _when(stamp: str) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


def spent(where: Path) -> Dict:
    """What a run cost, read from the session's own transcript."""
    slug = str(where.resolve()).replace("/", "-")
    holding = Path.home() / ".claude" / "projects" / slug
    if not holding.is_dir():
        return {"error": f"no session recorded for {where}"}

    transcripts = sorted(holding.glob("*.jsonl"))
    if not transcripts:
        return {"error": f"no transcript for {where}"}

    by_model: Dict[str, Dict[str, int]] = {}
    turns = 0
    tools = 0
    stamps: List[datetime] = []

    lines = []
    for transcript in transcripts:
        lines.extend(
            transcript.read_text(encoding="utf-8", errors="replace").splitlines()
        )

    for line in lines:
        try:
            record = json.loads(line)
        except ValueError:
            continue

        stamp = _when(record.get("timestamp", ""))
        if stamp:
            stamps.append(stamp)

        message = record.get("message") or {}
        if record.get("type") == "user" and not record.get("toolUseResult"):
            turns += 1

        content = message.get("content")
        if isinstance(content, list):
            tools += sum(
                1 for part in content
                if isinstance(part, dict) and part.get("type") == "tool_use"
            )

        usage = message.get("usage")
        if not usage:
            continue
        model = message.get("model", "unknown")
        held = by_model.setdefault(
            model, {"in": 0, "out": 0, "cache_read": 0, "cache_write": 0}
        )
        held["in"] += usage.get("input_tokens", 0) or 0
        held["out"] += usage.get("output_tokens", 0) or 0
        held["cache_read"] += usage.get("cache_read_input_tokens", 0) or 0
        held["cache_write"] += usage.get("cache_creation_input_tokens", 0) or 0

    dollars = 0.0
    for model, held in by_model.items():
        rate = _rate(model)
        for kind in ("in", "out", "cache_read", "cache_write"):
            dollars += held[kind] / 1_000_000 * rate[kind]

    # How long anybody was working, and how long the clock ran. A gap longer
    # than somebody's attention is a person reading, not a tool thinking.
    stamps.sort()
    span = (stamps[-1] - stamps[0]).total_seconds() if len(stamps) > 1 else 0.0
    idle = sum(
        gap
        for gap in (
            (stamps[n + 1] - stamps[n]).total_seconds() for n in range(len(stamps) - 1)
        )
        if gap > IDLE_AFTER
    )

    return {
        "seconds": round(span - idle, 1),
        "elapsed": round(span, 1),
        "idle": round(idle, 1),
        "turns": turns,
        "tool_calls": tools,
        "dollars": round(dollars, 4),
        "by_model": {
            model: {"out": held["out"], "in": held["in"]}
            for model, held in by_model.items()
        },
    }


def quality(where: Path, cost: Dict) -> Dict:
    """What was produced, judged by anything but Vesta."""
    from score import counted, defects, tests_pass  # noqa: E402

    built = counted(where)
    turns = max(cost.get("turns", 0), 1)
    return {
        "built": built,
        "defects": defects(where),
        "tests_pass": tests_pass(where),
        # What the user had to do to get it, and what each intervention bought.
        "interventions": cost.get("turns", 0),
        "lines_per_intervention": round(built["lines"] / turns, 1),
        "tests_per_intervention": round(built["tests"] / turns, 1),
    }


def one(where: Path) -> Dict:
    paid = spent(where)
    return {"where": where.name, "cost": paid, "quality": quality(where, paid)}


def main(argv: Optional[List[str]] = None) -> int:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    argv = list(argv or sys.argv[1:])
    if not argv:
        print("usage: battery.py <directory> [directory...]")
        return 1

    found = [one(Path(a).expanduser().resolve()) for a in argv]
    print(json.dumps(found, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
