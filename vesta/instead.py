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


# Files a definition is never hunted for in. A grep over a changelog, a
# manifest, a document or a log is somebody reading prose or data, and the
# graph holds nothing about either — refusing it leaves them with nothing,
# which is the one failure this must never have. Observed live: searches of
# `.gitignore`, `plugin.json`, `README.md` and an agent's markdown were each
# refused because the word happened to name a definition.
NOT_CODE = (
    ".md", ".markdown", ".rst", ".txt", ".json", ".yaml", ".yml", ".toml",
    ".ini", ".cfg", ".lock", ".csv", ".tsv", ".html", ".xml", ".log", ".svg",
)

SEARCHERS = ("grep", "egrep", "fgrep", "rg", "ag", "ack")

# Flags that take the next word as their value, so it is not mistaken for the
# pattern or a file. The common ones for the four searchers; an uncommon one
# costs at worst a search being let through.
TAKES_A_VALUE = {
    "-e", "--regexp", "-f", "--file", "-A", "-B", "-C", "-m", "--max-count",
    "-g", "--glob", "-t", "--type", "-T", "--type-not", "--include", "--exclude",
    "--exclude-dir", "-d", "--color", "--colour",
}


def _split(text: str, *separators: str) -> List[str]:
    """`text` cut at any separator that is outside quotes.

    Longer separators are tried first at each position, so `||` is not read
    as two pipes. Quote-aware because a pattern may legitimately contain `;`
    or `|`, and a cut inside it would turn one search into two commands.
    """
    parts: List[str] = []
    here: List[str] = []
    quote = ""
    i = 0
    ordered = sorted(separators, key=len, reverse=True)
    while i < len(text):
        ch = text[i]
        if quote:
            here.append(ch)
            if ch == quote:
                quote = ""
            i += 1
            continue
        if ch in ("'", '"'):
            quote = ch
            here.append(ch)
            i += 1
            continue
        hit = next((s for s in ordered if text.startswith(s, i)), None)
        if hit:
            parts.append("".join(here))
            here = []
            i += len(hit)
            continue
        here.append(ch)
        i += 1
    parts.append("".join(here))
    return [p.strip() for p in parts if p.strip()]


def _is_code(target: str) -> bool:
    """Whether a search target could hold a definition.

    A dotfile, a file with a prose or data suffix, and a shell variable are
    not. A directory, a glob over source, or a file with a source suffix are.
    """
    stripped = target.rstrip("/")
    name = stripped.rsplit("/", 1)[-1]
    if name in ("", ".", "..") or target.endswith("/"):
        return True  # a directory: the tree, or part of it
    if name.startswith(".") and "." not in name[1:]:
        return False  # `.gitignore`, `.env`
    lowered = name.lower()
    return not lowered.endswith(NOT_CODE)


def _one_search(stage: str) -> Tuple[str, List[str]]:
    """The pattern and targets of a single search command, or nothing.

    Returns ("", []) for anything that is not one search command on its own:
    a stage that starts with something else is reading or filtering, not
    searching the tree.
    """
    import shlex

    try:
        words = shlex.split(stage, posix=True)
    except ValueError:
        return "", []
    # Leading environment assignments: `LC_ALL=C grep …`.
    while words and re.match(r"^[A-Za-z_]\w*=", words[0]):
        words.pop(0)
    if not words or words[0].rsplit("/", 1)[-1] not in SEARCHERS:
        return "", []

    pattern = ""
    targets: List[str] = []
    rest = words[1:]
    i = 0
    while i < len(rest):
        word = rest[i]
        if word == "--":
            targets.extend(rest[i + 1:])
            break
        if word in ("-e", "--regexp") and i + 1 < len(rest):
            pattern = pattern or rest[i + 1]
            i += 2
            continue
        if word in TAKES_A_VALUE and i + 1 < len(rest):
            i += 2
            continue
        if word.startswith("-") and len(word) > 1:
            i += 1
            continue
        if not pattern:
            pattern = word
        else:
            targets.append(word)
        i += 1
    return pattern, targets


def _searched_for(payload: dict) -> Tuple[str, List[str]]:
    """The pattern a tool call is searching for, and the files it searches.

    Empty for anything that is not plainly one search of the code:

    - a compound command (`a; b`, `a && b`) does other work beside the
      search, and refusing the whole call refuses that work too — observed
      live, a `sed` reading one file was denied because a `grep` three
      commands later named a definition;
    - a search that is not the first stage of its pipeline (`ls | grep x`,
      `sed -n 1,40p f.py | grep def`) filters output already in hand, and the
      graph is not a better version of that;
    - a search over files that are not code (`grep version plugin.json`) is
      about prose or data the graph does not hold.

    The one case left is a single search, first in its pipeline, over source
    or over the tree — which is the one case the graph answers better.
    """
    tool = payload.get("tool_name", "")
    given = payload.get("tool_input") or {}

    if tool == "Grep":
        for scope in (str(given.get("glob", "")), str(given.get("path", ""))):
            if scope and not _is_code(scope):
                return "", []
        kind = str(given.get("type", "")).lower()
        if kind and kind in ("md", "markdown", "txt", "json", "yaml", "toml", "config", "log"):
            return "", []
        return str(given.get("pattern", "")), []

    if tool == "Bash":
        said = str(given.get("command", ""))
        commands = _split(said, ";", "&&", "||", "\n")
        if len(commands) != 1:
            return "", []
        stages = _split(commands[0], "|")
        if not stages:
            return "", []
        pattern, targets = _one_search(stages[0])
        if not pattern:
            return "", []
        if targets and not all(_is_code(t) for t in targets):
            return "", []
        return pattern, targets
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

    # `CLAUDE_PROJECT_DIR`, not `payload["cwd"]`, first: the host sets this once
    # at session spawn to the actual project root, where `cwd` is the tool
    # call's working directory at the moment it fired — a shell `cd`, a
    # subprocess launched from elsewhere, or a harness that resets the working
    # directory between calls (observed live: a session's own cwd drifted to
    # an unrelated project mid-run) all move `cwd` without moving the project.
    # This is the same signal `project_of` in sidecar.py trusts as its
    # documented fallback when MCP roots aren't available; a stdio hook has no
    # session to ask roots/list on, so it is the strongest signal reachable
    # here. `cwd` remains the fallback for a host that does not set it.
    import os

    where = os.environ.get("CLAUDE_PROJECT_DIR") or payload.get("cwd") or ""
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
