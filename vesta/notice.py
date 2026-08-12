"""Noticing that a prompt is about somewhere else.

Vesta can answer about another project, and a user who has to be told that
first will not be. Most people never read the instructions for a tool they
installed, and a capability nobody discovers is a capability nobody has.

So the prompt is read before the agent sees it, and where it names a project
Vesta knows, that fact is offered — not the answer, the fact. This runs on
every prompt in the session, so it must be cheap and it must be quiet: no
model, no disk walk, no network, and nothing said at all unless a name in the
prompt matches a project already known.

**Naming is not enough on its own.** "vesta" appears in a prompt about the
repository under works constantly, and saying so every time is noise that
teaches the user to stop reading. So the project under works is never offered,
and a bare name is only offered when the prompt also asks something that Vesta
could answer — how a thing was done, where it lives, the way it worked.

**What is offered is a fact, not an instruction.** The agent is told the
project is known and can be consulted. Whether the question actually calls for
it is a judgement, and the agent making it has the prompt in front of it.
"""

from __future__ import annotations

import json
import logging
import re
import sys
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

logger = logging.getLogger("vesta.notice")

# Words that make a prompt a question about how something is done somewhere.
# A name on its own is usually just a name; a name next to one of these is a
# question Vesta has something to say about.
ASKING = (
    "how", "where", "like", "same as", "similar", "way", "did", "does",
    "worked", "works", "implement", "pattern", "approach", "reuse", "port",
    "copy", "mirror", "follow", "borrow", "bearings", "reference",
)

# A name shorter than this is too common a word to match on: a project called
# `db` or `api` would fire on half of everything.
SHORTEST = 4


def _mentions(prompt: str, name: str) -> bool:
    """Whether a prompt names a project, as a word rather than a fragment."""
    return re.search(rf"\b{re.escape(name.lower())}\b", prompt.lower()) is not None


def _is_asking(prompt: str) -> bool:
    low = prompt.lower()
    return any(word in low for word in ASKING)


def _projects() -> List[Tuple[str, str]]:
    """Every project Vesta knows, as name and path.

    Read straight from the graph stores rather than through `across`, which
    pulls pydantic in behind it. That import costs more than everything else
    this hook does put together, and this runs on every prompt in the session —
    a notice that nobody asked for must not be something anybody notices.
    """
    import sqlite3

    from .home import home  # cheap: no pydantic behind it

    found: List[Tuple[str, str]] = []
    where = home()

    for store in (where / "graphs").glob("*.db"):
        try:
            connection = sqlite3.connect(f"file:{store}?mode=ro", uri=True)
            row = connection.execute(
                "SELECT value FROM meta WHERE key='root'"
            ).fetchone()
            connection.close()
        except Exception:  # noqa: BLE001 - an unreadable store is one to skip
            continue
        if row and row[0] and Path(row[0]).is_dir():
            found.append((Path(row[0]).name, row[0]))
    return found


def elsewhere_in(
    prompt: str, here: Optional[Path] = None, roots: Optional[Sequence[Path]] = None
) -> List[Tuple[str, str]]:
    """Projects a prompt names, other than the one under works."""
    if not prompt.strip():
        return []

    under_works = str(Path(here).expanduser().resolve()) if here else ""
    everything = list(_projects())
    for root in roots or ():
        root = Path(root).expanduser().resolve()
        if root.is_dir():
            everything.append((root.name, str(root)))

    found = []
    seen = set()
    for name, path in everything:
        if path == under_works or len(name) < SHORTEST or path in seen:
            continue
        seen.add(path)
        if _mentions(prompt, name):
            found.append((name, path))

    if not found:
        return []

    # A name alone is usually just a name. It becomes a reference when the
    # prompt also asks something answerable, or spells out a path — which is
    # unambiguous enough to stand on its own.
    return found if _is_asking(prompt) or _has_path(prompt) else []


def _has_path(prompt: str) -> bool:
    """Whether the prompt spells out a filesystem path."""
    return bool(re.search(r"(?:^|\s)(?:~|\.{1,2})?/[\w./-]{3,}", prompt))


def say(projects: Sequence[Tuple[str, str]]) -> str:
    """What to put in front of the agent, or nothing."""
    if not projects:
        return ""
    named = "; ".join(f"{name} — {path}" for name, path in projects[:3])
    return (
        f"Vesta knows this project: {named}. "
        "If the question is about how something is done there, "
        "`elsewhere(phrase, project)` answers from its graph — the project "
        "under works stays authoritative and the other is consulted, not merged."
    )


def main(argv: Optional[Sequence[str]] = None) -> int:
    """The hook. Reads the framework's payload on stdin, offers a fact or not.

    Silent on every failure. A hook that runs on every prompt and can break one
    is worse than no hook: the cost of missing a cross-project reference is a
    tool the user calls themselves, and the cost of raising here is a session
    that stops working.
    """
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except (ValueError, OSError):
        return 0

    try:
        prompt = payload.get("prompt", "") or ""
        here = payload.get("cwd") or None
        found = elsewhere_in(prompt, Path(here) if here else None)
        offered = say(found)
        if offered:
            print(
                json.dumps(
                    {
                        "hookSpecificOutput": {
                            "hookEventName": "UserPromptSubmit",
                            "additionalContext": offered,
                        }
                    }
                )
            )
    except Exception as exc:  # noqa: BLE001 - never break a prompt
        logger.debug("noticed nothing: %s", exc)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
