"""Putting what is known in front of an agent, before it decides anything.

The sidecar offers tools an agent may call. This does not offer — it answers a
question nobody asked yet, on the way in, because the agent cannot ask for what
it does not know exists.

**Why this is worth trying at all.** Five measured runs put the tool-based
saving at eighteen to thirty-four percent, and the mechanism explains the
ceiling: by the time an agent calls a tool it has already decided what it is
looking for, so the tool saves the *locating* and not the *deciding*. Injection
happens earlier, which is either a real improvement or a way to spend tokens on
context nobody wanted. Both are worth knowing and neither is knowable by
argument.

**It must not answer when it has nothing to say.** A hook that prepends
something to every prompt is a tax on every prompt. So the prompt is read for
what it is about, and nothing is injected unless a definition in the graph is
plainly named — no fuzzy matching, no "this might be relevant", because a
speculative injection costs the same as a useful one and teaches an agent to
skim past both.

**What is injected is bounded and cited.** A budget, because context spent here
is context unavailable later, and citations, because an agent that cannot check
a claim has to either trust it or redo it — and it will redo it.
"""

from __future__ import annotations

import json
import logging
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Set

from .authority import settle
from .dynamic import scan
from .graph import Graph
from .harvest import anchor, from_sessions
from .held import graph_for
from .propagate import from_definitions

logger = logging.getLogger("vesta.inject")

# How much of the context window this may take. Small on purpose: the point is
# to save an agent from finding things, not to pre-empt its reasoning.
BUDGET = 3000

# A prompt naming fewer than this many known definitions is not about the code
# in a way this can help with.
LEAST = 1

# How long a cached graph is used without re-checking the tree. Long enough to
# cover a working session, short enough that a rebuild is never far away.
TRUST_FOR = 300.0

# Words that are definition names in this codebase and also ordinary English.
# Matching them would inject on almost every prompt.
# Words that are ordinary English as often as they are identifiers. A prompt
# saying "tell me what you would change" names no definition, and answering it
# with everything called `Change` teaches an agent to skim past this channel —
# which costs more than the occasional real match is worth.
#
# Extended after a live session: "change", "work", "rule", "rules" and the
# other verbs below each pulled an unrelated definition into a prompt that was
# plainly not about them.
TOO_COMMON = {
    "build", "run", "read", "write", "check", "test", "tests", "main", "get",
    "set", "add", "map", "list", "text", "path", "line", "name", "type", "kind",
    "found", "where", "about", "known", "used", "keep", "note", "notes", "term",
    "graph", "node", "edge", "search", "answer", "result", "results", "session",
    "change", "changes", "changed", "work", "works", "rule", "rules", "said",
    "say", "ask", "asked", "show", "make", "made", "call", "calls", "called",
    "use", "uses", "using", "look", "find", "help", "start", "stop", "open",
    "close", "hold", "held", "move", "point", "value", "values", "data",
    "field", "fields", "item", "items", "state", "status", "context", "prompt",
}


def _named(prompt: str, graph: Graph) -> List[str]:
    """Definitions the prompt plainly names.

    Exact identifiers only. A prompt mentioning "the search" should not pull in
    `Search`, because a guess that is wrong costs the same as one that is right
    and trains an agent to ignore the whole channel.
    """
    words = set(re.findall(r"[A-Za-z_][\w.]*", prompt))
    found: List[str] = []
    for node in graph.nodes.values():
        if node.name in TOO_COMMON:
            continue
        if node.name in words or node.qualified in words:
            found.append(node.id)
    return found


def context_for(prompt: str, project: Path | str, budget: int = BUDGET) -> str:
    """What is already known about whatever this prompt is about.

    Returns an empty string when nothing is plainly named, which is most of the
    time and is the point.
    """
    root = Path(project).expanduser().resolve()

    # Never build here. A graph takes eight to twelve seconds on an ordinary
    # repository, and a hook that spends that on a user's first message has
    # made the session worse whether or not it later helps. If nothing is
    # ready, start preparing and say nothing — the next prompt may be able to
    # answer, and this one was never owed an answer.
    from .ready import prepare, readiness

    state = readiness(root)
    if not state.can_answer:
        prepare(root)
        return ""

    try:
        # Trust a recently written graph without re-walking the tree to check.
        #
        # The staleness fingerprint stats every file, which costs about one and
        # three quarter seconds on an ordinary repository — an order of
        # magnitude more than everything else here combined, on the one path
        # that runs before every prompt. A graph written in the last few minutes
        # is close enough: the cost of being briefly out of date is a stale line
        # number in an injected note, and the cost of checking is a pause the
        # user feels on every message.
        graph = graph_for(root, trust_for=TRUST_FOR)
    except Exception as exc:  # noqa: BLE001 - a hook must never break a session
        logger.info("no graph for %s: %s", root, exc)
        return ""

    named = _named(prompt, graph)
    if len(named) < LEAST:
        return ""

    harvest = from_sessions(graph, root)
    standing = settle(graph, harvest.notes, root)
    blind = scan(root, graph, trust_for=TRUST_FOR)

    lines: List[str] = [
        "Vesta already holds analysis of what this prompt names. This is not a "
        "substitute for reading the code; it is what earlier sessions worked "
        "out, with the regions they were derived from.",
        "",
    ]
    spent = 0

    # One entry per name. Two definitions sharing a name produced the same
    # warning twice, which reads as two separate problems.
    said_about: Set[str] = set()
    for node_id in named[:4]:
        node = graph.nodes[node_id]
        if node.name in said_about:
            continue
        said_about.add(node.name)
        reached = from_definitions(graph, [node_id], hops=2)
        tests = reached.tests(graph)

        lines.append(f"{node.qualified} — {node.path}:{node.line + 1}")
        lines.append(
            f"  {len(graph.referenced_by(node_id))} definition(s) refer to it; "
            f"{len(reached.reached)} reached within 2 hops"
            + (f"; tests: {', '.join(sorted(tests)[:3])}" if tests else "")
        )

        # References that reach it by name. The graph cannot resolve these and
        # an agent editing without knowing about them will miss consumers.
        # Names reached by the propagation, not only the definition itself: a
        # change to `for_` affects `why_not`, and it is `why_not` that three
        # call sites reach dynamically. Warning only about the named symbol
        # would miss exactly the case that motivated this.
        touched = {node.name} | {
            graph.nodes[r.node].name
            for r in reached.reached
            if r.node in graph.nodes
        }
        unresolved = [u for u in blind.found if u.name in touched]
        if unresolved:
            lines.append(
                f"  ⚠ {len(unresolved)} reference(s) reach it dynamically and are "
                "not in the graph: "
                + ", ".join(f"{u.path}:{u.line}" for u in unresolved[:4])
            )

        for note in harvest.for_node(node_id)[:2]:
            stands = standing.get(id(note))
            if stands and stands.state == "moved":
                continue  # a superseded claim is not worth the space
            text = anchor(note.text, graph)
            if spent + len(text) > budget:
                break
            spent += len(text)
            lines.append(f"  [{stands.region if stands else node.path}] {text}")
        lines.append("")

    if spent == 0 and len(lines) <= 3:
        return ""
    return "\n".join(lines)


def main() -> int:
    """Run as a UserPromptSubmit hook.

    Reads the host's JSON on stdin and answers with additionalContext. Any
    failure is silent and empty: a hook that breaks a session is worse than one
    that contributes nothing.
    """
    try:
        payload = json.load(sys.stdin)
    except (ValueError, OSError):
        return 0

    prompt = str(payload.get("prompt") or "")
    project = payload.get("cwd") or "."

    parts = []
    try:
        parts.append(context_for(prompt, project))
    except Exception as exc:  # noqa: BLE001 - never break the session
        logger.info("could not build context: %s", exc)

    # A rule the user is stating right now, and a rule already in doubt for
    # what they are about to change. Both belong here rather than in a skill:
    # a skill loads when its description matches, and a user who states a rule
    # in the course of asking for something else does not match a description
    # about asking. Verified the hard way — in a live session the instruction
    # was never in front of the agent, so nothing was recorded.
    for offer in (
        _something_to_build(prompt, project),
        _a_rule_stated(prompt),
        _a_change_to_what_was_agreed(prompt, project),
        _a_rule_in_doubt(prompt, project),
    ):
        if offer:
            parts.append(offer)

    said = "\n\n".join(p for p in parts if p)

    if said:
        _note(prompt, project, len(said))
        json.dump(
            {"hookSpecificOutput": {
                "hookEventName": "UserPromptSubmit",
                "additionalContext": said,
            }},
            sys.stdout,
        )
    return 0


def _a_rule_stated(prompt: str) -> str:
    """What to say when the user has just stated a standing rule.

    The regex only decides whether to *mention* it. Whether the sentence really
    is a standing rule is the agent's judgement, and it has the whole prompt —
    including everything a pattern cannot see. Being wrong here costs one line
    of context; being silent costs the rule.
    """
    from .rules import constrains

    if not constrains(prompt):
        return ""

    return (
        "The user may have just stated a standing rule for this project. If "
        "they did — a constraint on the code rather than on this turn, said "
        "rather than mused — call the `declare` tool with it in their own "
        "words, say in one line that it was recorded, and carry on with what "
        "they actually asked for. If it only scopes this turn, do nothing."
    )


def _a_rule_in_doubt(prompt: str, project: str) -> str:
    """A rule the user set that the files they name no longer match.

    Raised here rather than waiting to be asked, because nobody runs a command
    to find out whether they are about to break their own rule.
    """
    import re as _re

    paths = _re.findall(r"[\w./-]+\.[a-zA-Z]{1,6}\b", prompt)
    if not paths:
        return ""

    try:
        from .sidecar import _bears_on

        return _bears_on(paths[:6], Path(project))
    except Exception as exc:  # noqa: BLE001 - never break the session
        logger.info("could not check what bears on this: %s", exc)
        return ""


# Somebody asking for something to be built, rather than asking about code that
# already exists. Deliberately broad: the cost of mentioning the contract on a
# prompt that did not need it is one line the agent ignores, and the cost of
# missing one is a project built with nothing agreed — which is what happened
# the first time this was run for real.
TO_BUILD = re.compile(
    r"\b(build|make|create|write|implement|add)\b.{0,60}\b("
    r"me |a |an |the |app|application|tool|script|cli|api|service|"
    r"program|site|website|server|library|package|game|bot)",
    re.I,
)

# What marks a prompt as being about code that is already there, which is the
# ordinary case and needs no contract.
# Anchored to what somebody says about code that already exists, not to bare
# words that happen to appear in a feature request. "broken down by category"
# is a thing to build; matching it on `broken` suppressed the whole contract
# flow on a brief that plainly asked for something new.
ABOUT_WHAT_EXISTS = re.compile(
    r"\b(fix|debug|refactor|rename|review)\b|"
    r"\b(why (?:is|does|did)|explain|what does|where is)\b|"
    r"\b(the bug|is failing|are failing|is broken|it broke|this file|"
    r"this function|this test|these tests)\b",
    re.I,
)


def _something_to_build(prompt: str, project: str) -> str:
    """Whether they are asking for something to be built with nothing agreed.

    **This is a hook rather than a skill for a reason that was learned the hard
    way.** The instruction lived in the skill, whose description is about
    answering questions on an existing repository — so "build me a todo list"
    in an empty directory matched nothing, the skill never loaded, and the
    agent built the whole thing with no contract, no verification and no
    consent. Everything was installed correctly and none of it was used.
    """
    try:
        from .contract import recall as recall_contract

        if recall_contract(project) is not None:
            return ""  # something is already agreed; nothing to elicit
    except Exception as exc:  # noqa: BLE001 - never break a prompt
        logger.info("could not read the contract: %s", exc)
        return ""

    if not TO_BUILD.search(prompt) or ABOUT_WHAT_EXISTS.search(prompt):
        return ""

    # A whole thing, not a piece of one. "Add a field to the form" is ordinary
    # work in something that already exists; demanding a contract for it would
    # make the tool insufferable. What marks a project is that there is nothing
    # here yet, or that they described several things they want it to do.
    from pathlib import Path as _Path

    root = _Path(project).expanduser()
    try:
        existing = [
            p for p in root.rglob("*.py")
            if not any(part.startswith(".") for part in p.parts)
        ]
    except OSError:
        existing = []

    if existing and len(prompt.split()) < 25:
        return ""

    return (
        "This asks for something to be built and nothing has been agreed for "
        "this project yet.\n\n"
        "Run the `vesta-spec` subagent now, before writing any code. It turns "
        "what they asked for into a short list of behaviours, which you show "
        "them and they agree to with `/vesta:agree`. **Do not start building "
        "until they have agreed** — the point is that they see what will be "
        "built while changing it is still free.\n\n"
        "If they would rather you just built it, they will say so."
    )


def _a_change_to_what_was_agreed(prompt: str, project: str) -> str:
    """Whether what they just asked for departs from the signed contract.

    Only where one exists and has been signed — before that nothing has been
    agreed and nothing can be departed from. Said on the way in, because a
    change arrives as ordinary conversation and an agent that notices after
    building it has already spent the work.
    """
    try:
        from .asked import REFUSED, SURE, act
        from .contract import recall as recall_contract

        agreed = recall_contract(project)
        if agreed is None or not agreed.signed:
            return ""

        # `act`, not `where_it_lands`: deciding and recording are the same
        # moment. Calling only the first meant a refused change was never
        # kept for after delivery and a "sure" was never noted — the contract
        # stayed empty and nobody found out until they read it.
        landing = act(prompt, project)
    except Exception as exc:  # noqa: BLE001 - never break a prompt
        logger.info("could not place what was asked: %s", exc)
        return ""

    if landing.verdict == REFUSED:
        return (
            "This may change what was agreed for this project. Behaviour is "
            "fixed once signed, so do not build it.\n\n"
            f"{landing.what_to_say()}\n\n"
            "Judge for yourself whether it really alters what the system does "
            "— this is a pattern, not a reading of their meaning. If it does "
            "not, carry on."
        )
    if landing.verdict == SURE:
        # Only where it plainly names nothing. Ordinary work — "add a test for
        # filing" — reaches code and is not this, and answering it with "sure"
        # would be a tool declining to do its job politely.
        return (
            "If this asks for nothing the project could have — where you "
            'cannot say what it does or who for — say "sure" and nothing '
            "else, then carry on. Do not argue with it. If it is ordinary "
            "work, just do it."
        )
    return ""


def _note(prompt: str, project: str, size: int) -> None:
    """Record what was injected, so an experiment can account for it."""
    import time

    from .home import home

    try:
        home().mkdir(parents=True, exist_ok=True)
        with (home() / "injected.jsonl").open("a", encoding="utf-8") as out:
            out.write(json.dumps({
                "at": time.time(),
                "project": str(project),
                "prompt": prompt[:120],
                "chars": size,
            }) + "\n")
    except OSError:
        pass


if __name__ == "__main__":
    raise SystemExit(main())
