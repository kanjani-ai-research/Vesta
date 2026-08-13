"""Whether the hard part of each brief was actually handled.

A todo list, a pomodoro timer and a markdown outliner are shapes a model has
seen ten thousand times. A battery of them measures recall: both arms produce
something fluent, and the comparison says nothing about method.

So each brief ends with a requirement that cannot be pattern-matched from the
familiar shape — and this checks whether it was met. Not by reading the code,
which would be a judgement, but by asking whether the thing the requirement
describes is anywhere in it.

**Crude on purpose.** Each check is a handful of signals that a competent
implementation would leave behind and a plausible-but-wrong one would not. It
can be fooled by somebody writing the words without the behaviour, which is
why what it reports is *evidence*, not a verdict — a reader still has to look.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Dict, List, Optional

# What each curveball asks for, and what handling it leaves behind.
WANTED: Dict[str, Dict[str, List[str]]] = {
    "pomodoro": {
        "asks": "a session resumes in real elapsed time, not where it was left",
        "signals": ["elapsed", "monotonic", "time()", "started_at", "now()"],
        "against": ["remaining", "paused"],
    },
    "markdown": {
        "asks": "code fences and block quotes are not headings; GitHub anchors",
        "signals": ["fence", "```", "in_code", "code_block", "blockquote", "> "],
        "against": ["slug", "anchor", "lower()"],
    },
    "ledger": {
        "asks": "one blank posting is inferred; balance is per currency",
        "signals": ["blank", "None", "infer", "elided", "missing"],
        "against": ["currency", "per_currency", "rate"],
    },
}


def _source(where: Path) -> str:
    text = []
    for path in sorted(where.rglob("*.py")):
        if any(p in (".venv", "__pycache__", ".git") for p in path.parts):
            continue
        try:
            text.append(path.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            continue
    return "\n".join(text)


def check(where: Path) -> Dict:
    """What evidence there is that the curveball was handled."""
    which = next((k for k in WANTED if k in where.name), "")
    if not which:
        return {"error": f"no curveball known for {where.name}"}

    wanted = WANTED[which]
    source = _source(where)
    found = [s for s in wanted["signals"] if s in source]
    also = [s for s in wanted["against"] if s in source]

    return {
        "asks": wanted["asks"],
        "signals_present": found,
        "second_half_present": also,
        # Evidence, not a verdict. Both halves showing is what a competent
        # implementation looks like from outside; neither is a good sign.
        "looks_handled": bool(found) and bool(also),
    }


def main(argv: Optional[List[str]] = None) -> int:
    argv = list(argv or sys.argv[1:])
    if not argv:
        print("usage: curveball.py <directory> [directory...]")
        return 1
    # Keyed by the whole path: two arms run the same brief, so the directory
    # name alone collides and one arm silently overwrites the other.
    print(json.dumps(
        {
            str(Path(a).expanduser().resolve()): check(Path(a).expanduser().resolve())
            for a in argv
        },
        indent=2,
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
