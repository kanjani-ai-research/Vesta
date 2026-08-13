"""What a live session cost, read from its own transcript.

The first version of this measured `claude -p`, which was the wrong thing to
measure: Vesta works through hooks and slash commands inside a session, and a
non-interactive run loads none of that. Measuring the product through `-p`
measures something that is not the product.

A real session writes a transcript, and the transcript carries what a run
costs: tokens on every assistant message, a timestamp on every record, and one
record per turn. So an interactive trial can be measured exactly, after the
fact, without changing how it is run.

Give it the directory the work was done in. It finds that project's most
recent session and reports what it spent.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional


def _sessions_for(where: Path) -> List[Path]:
    """Transcripts for the project at this path, newest first."""
    slug = str(where.resolve()).replace("/", "-")
    holding = Path.home() / ".claude" / "projects" / slug
    if not holding.is_dir():
        return []
    return sorted(holding.glob("*.jsonl"), key=lambda p: -p.stat().st_mtime)


def _when(stamp: str) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


def spent(transcript: Path) -> Dict:
    """What one session cost."""
    found = {
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_read": 0,
        "cache_write": 0,
        "assistant_messages": 0,
        "user_turns": 0,
        "tool_calls": 0,
    }
    first = last = None

    for line in transcript.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            record = json.loads(line)
        except ValueError:
            continue

        stamp = _when(record.get("timestamp", ""))
        if stamp:
            first = first or stamp
            last = stamp

        kind = record.get("type")
        message = record.get("message") or {}

        if kind == "user" and not record.get("toolUseResult"):
            found["user_turns"] += 1

        usage = message.get("usage")
        if usage:
            found["assistant_messages"] += 1
            found["input_tokens"] += usage.get("input_tokens", 0) or 0
            found["output_tokens"] += usage.get("output_tokens", 0) or 0
            found["cache_read"] += usage.get("cache_read_input_tokens", 0) or 0
            found["cache_write"] += usage.get("cache_creation_input_tokens", 0) or 0

        content = message.get("content")
        if isinstance(content, list):
            found["tool_calls"] += sum(
                1 for part in content if isinstance(part, dict)
                and part.get("type") == "tool_use"
            )

    if first and last:
        found["seconds"] = round((last - first).total_seconds(), 1)
    found["transcript"] = str(transcript)
    return found


def main(argv: Optional[List[str]] = None) -> int:
    argv = list(argv or sys.argv[1:])
    if not argv:
        print("usage: spent.py <the directory the work was done in>")
        return 1

    where = Path(argv[0]).expanduser().resolve()
    sessions = _sessions_for(where)
    if not sessions:
        print(json.dumps({"error": f"no session recorded for {where}"}, indent=2))
        return 1

    print(json.dumps(spent(sessions[0]), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
