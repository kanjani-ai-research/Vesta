"""Scoring a battery of runs across both arms.

Three briefs, two arms, one standard. What is measured is time, quality and
cost — not token count, which says nothing on its own about either what a run
cost or what it produced.

**Cost is money, not tokens.** A run is priced at the published rates for the
model that did the work, so a cheaper model doing more work can cost less than
a dearer one doing less. Token counts are kept because they are the evidence,
but the number that matters is dollars.

**Quality is what a stranger could check.** Whether the tests pass, whether the
thing runs, what is wrong with the code by the crudest possible reading — bare
excepts, swallowed failures, dead code. Nothing here uses Vesta: scoring the
arm that ships Vesta with Vesta's own measurements would show only that a tool
agrees with itself.

**Time is wall clock, from the transcript.** Not a stopwatch anybody had to
watch, and not the model's estimate of its own effort.
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

    transcripts = sorted(holding.glob("*.jsonl"), key=lambda p: -p.stat().st_mtime)
    if not transcripts:
        return {"error": f"no transcript for {where}"}

    by_model: Dict[str, Dict[str, int]] = {}
    turns = 0
    tools = 0
    first = last = None

    for line in transcripts[0].read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            record = json.loads(line)
        except ValueError:
            continue

        stamp = _when(record.get("timestamp", ""))
        if stamp:
            first = first or stamp
            last = stamp

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

    return {
        "seconds": round((last - first).total_seconds(), 1) if first and last else 0,
        "turns": turns,
        "tool_calls": tools,
        "dollars": round(dollars, 4),
        "by_model": {
            model: {"out": held["out"], "in": held["in"]}
            for model, held in by_model.items()
        },
    }


def quality(where: Path) -> Dict:
    """What was produced, judged by anything but Vesta."""
    from score import counted, defects, tests_pass  # noqa: E402

    return {
        "built": counted(where),
        "defects": defects(where),
        "tests_pass": tests_pass(where),
    }


def one(where: Path) -> Dict:
    return {"where": where.name, "cost": spent(where), "quality": quality(where)}


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
