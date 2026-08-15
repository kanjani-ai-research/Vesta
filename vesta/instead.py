"""Refusing a search the graph already answers, and answering it instead.

**Telling an agent that better tools exist does not make it use them.** Six
offers in the prompt hook describe Vesta at length; nothing measured whether a
single one changed what the agent then did. A paragraph is a suggestion, and a
suggestion loses to habit — the habit being `grep -n "def graph_for"`.

`PreToolUse` is not a suggestion. Returning `permissionDecision: "deny"`
**prevents the tool call**, and `permissionDecisionReason` is delivered to
Claude. So a search for a definition is refused, and the refusal carries the
resolved answer: the agent does not get to grep, and does not need to, because
what it wanted is already in front of it.

**Only where the graph is strictly better, and never otherwise.** A grep for
`TODO`, for a string literal, for a comment, for anything Vesta does not hold —
allowed, untouched, because a tool that blocks work it cannot do is a tool
somebody uninstalls within the hour. What is refused is the narrow case where a
search is a worse version of a lookup Vesta can do exactly: finding where a
definition the graph holds lives and what refers to it.

The difference matters and it is not a preference. A grep for `describe` finds
every spelling of the word — a comment, a docstring, four unrelated methods. A
resolved lookup finds *the* definition and the references that actually reach
it. The grep answer is a superset containing the truth; the graph answer is the
truth.
"""

from __future__ import annotations

import json
import logging
import re
import sys
from pathlib import Path
from typing import List, Optional, Tuple

logger = logging.getLogger("vesta.instead")

# What a search for a definition looks like.
#
# Deliberately narrow. Each of these is a pattern whose whole purpose is to
# find where something is defined — which is the one question a resolved graph
# answers strictly better. Anything else is somebody's own search and is left
# alone.
LOOKING_FOR_A_DEFINITION = (
    # `def foo`, `class Foo`, `func foo`, `fn foo`, `function foo`
    re.compile(r"^\s*\\?b?\s*(?:def|class|func|fn|function|type|struct|impl)\s+"
               r"\\?b?\s*([A-Za-z_]\w*)", re.I),
    # `foo\s*\(` — a call site hunt
    re.compile(r"^\s*([A-Za-z_]\w{2,})\s*\\?\\?\(\s*$"),
    # a bare identifier, nothing else: `graph_for`, `Graph.referenced_by`
    re.compile(r"^\s*([A-Za-z_]\w{2,}(?:\.\w+)?)\s*$"),
)

# A search that is plainly not about a definition, whatever else it looks like.
# Checked first, because "def" appearing inside a prose search should not make
# it a definition hunt.
NOT_A_DEFINITION = re.compile(
    r"(TODO|FIXME|XXX|HACK|NOTE:|import |from |#|//|\"\"\"|'''|"
    r"http|www\.|\.md\b|\.txt\b|\.json\b|\.ya?ml\b)",
    re.I,
)


def what_it_wants(pattern: str) -> Optional[str]:
    """The definition a search is hunting for, if that is what it is doing."""
    if not pattern or len(pattern) > 80:
        return None
    if NOT_A_DEFINITION.search(pattern):
        return None
    for shape in LOOKING_FOR_A_DEFINITION:
        found = shape.match(pattern)
        if found:
            return found.group(1)
    return None


def answer_for(name: str, project: Path) -> str:
    """What the graph says about this definition, or nothing.

    Written here rather than calling `_uses`, and the reason is latency: this
    sits in front of every search an agent makes, and `_uses` re-loads the
    graph and harvests every session to decorate its answer — 1.9 seconds,
    where the graph is already open here. A hook that adds two seconds to
    every tool call is a hook somebody disables.

    Returns "" when the graph does not hold it, which is also the signal to
    let the search run. A refusal that leaves an agent with nothing is the
    failure this must never have.
    """
    try:
        from .held import graph_for

        graph = graph_for(project, never_build=True)
    except Exception as exc:  # noqa: BLE001 - never break a tool call
        logger.info("no graph for %s: %s", project, exc)
        return ""

    bare = name.split(".")[-1]
    wanted = [
        node
        for node in graph.nodes.values()
        if node.qualified == name or node.name == bare
    ]
    if not wanted:
        return ""

    lines = [f"(paths are relative to {project})"]
    for node in wanted[:4]:
        callers = graph.referenced_by(node.id)
        uses = graph.depends_on(node.id)
        lines.append("")
        lines.append(f"{node.qualified}  {node.path}:{node.line + 1}")
        lines.append(f"  referred to by {len(callers)}, refers to {len(uses)}")

        # One line per place, not per edge: a caller referring twice is one
        # place to look, and listing it twice tells a reader nothing.
        seen: set = set()
        for edge in callers:
            other = graph.nodes.get(edge.source)
            if other is None or other.id in seen:
                continue
            seen.add(other.id)
            lines.append(f"    ← {other.qualified}  {other.path}:{other.line + 1}")
            if len(seen) >= 10:
                lines.append(f"    … and {len(callers) - len(seen)} more reference(s)")
                break

    if len(wanted) > 4:
        lines.append("")
        lines.append(f"… and {len(wanted) - 4} more definition(s) with that name")
    return "\n".join(lines)


def _searched_for(payload: dict) -> Tuple[str, List[str]]:
    """The pattern a tool call is searching for, whichever tool it is."""
    tool = payload.get("tool_name", "")
    given = payload.get("tool_input") or {}

    if tool == "Grep":
        return str(given.get("pattern", "")), []
    if tool == "Bash":
        # `grep -n "def graph_for" file.py`, `rg graph_for`
        said = str(given.get("command", ""))
        found = re.search(
            r"\b(?:grep|rg|ag|ack)\b[^|;]*?"
            r"(?:-\w+\s+)*"
            r"(['\"])(.+?)\1",
            said,
        )
        if found:
            return found.group(2), []
        found = re.search(r"\b(?:grep|rg|ag|ack)\b\s+(?:-\w+\s+)*([A-Za-z_]\w{2,})\b", said)
        if found:
            return found.group(1), []
    return "", []


def decide(payload: dict) -> Optional[dict]:
    """Whether to refuse this search, and what to say instead.

    `None` means allow — and `None` is the answer for almost everything. What
    is refused is a search for a definition the graph holds, which is the one
    case where the search is a strictly worse version of a lookup Vesta can do
    exactly.
    """
    pattern, _ = _searched_for(payload)
    if not pattern:
        return None

    name = what_it_wants(pattern)
    if not name:
        return None

    where = payload.get("cwd") or ""
    if not where:
        return None
    project = Path(where).expanduser().resolve()

    try:
        from .ready import readiness

        if not readiness(project).can_answer:
            return None  # nothing to answer with; the search is all there is
    except Exception as exc:  # noqa: BLE001
        logger.info("could not read readiness: %s", exc)
        return None

    # One graph load answers both questions: whether it is held, and what to
    # say about it.
    answer = answer_for(name, project)
    if not answer:
        return None

    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": (
                f"Not needed — Vesta holds `{name}` resolved, and the answer "
                "is below. A search finds every spelling of a word, including "
                "comments, docstrings and unrelated definitions sharing the "
                "name; this is the definition itself and the references that "
                "actually reach it.\n\n"
                f"{answer}\n\n"
                "Use this. If you need something a resolved lookup cannot "
                "give — a comment, a string, a pattern across files — search "
                "for that instead and it will run."
            ),
        }
    }


def main(argv: Optional[List[str]] = None) -> int:
    """Read the tool call, and refuse it where Vesta answers it better."""
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except (ValueError, OSError):
        return 0

    try:
        said = decide(payload)
    except Exception as exc:  # noqa: BLE001 - a hook must never break a call
        logger.debug("could not decide about this search: %s", exc)
        return 0

    if said:
        print(json.dumps(said))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
