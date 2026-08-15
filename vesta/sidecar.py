"""Vesta as a sidecar to a coding agent.

An MCP server exposing what Vesta knows to whatever framework is doing the
coding. Additive by design and by necessity: a host's built-in file and search
tools cannot be disabled or overridden, and there is no mechanism to make an
agent prefer one tool over another. Tool *descriptions* are the only lever on
selection, which is why the ones below say plainly what each tool is for and,
more importantly, what it is not for.

**This does not compete with the host's code retrieval.** Grep, file reading and
symbol navigation over a repository are things every serious agent framework
already does well, and a second implementation would be redundant at best. What
none of them can do is supply knowledge that is *not in the repository* — the
paper that explains why the obvious approach to a problem is wrong. That is the
whole of what this offers.

**Nothing here is a directive.** Tools return cited passages and say how well
they matched; they do not instruct. The same rule that governs `maturity`: a
corpus knows more about the literature than about this build, and an agent given
a retrieved fact as an order will follow it off a cliff.
"""

from __future__ import annotations

import contextlib
import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Set

from .authority import settle
from .dynamic import missed_by, scan
from .enforce import against
from .harvest import anchor, from_sessions
from . import confirm as confirming
from .across import known as known_projects
from .across import loaded, refer, release, resolve
from .domain import recall as recall_ontology
from .held import graph_for
from .store import AsGraph, Held
from .traverse import about, neighbours
from .traverse import recall as recall_map
from .traverse import where as where_in
from .learned import everything as learned_patterns
from .patterns import CLEAR, LIKELY, WORTH_A_LOOK, Site, survey
from .propagate import from_files, is_test
from .home import home

logger = logging.getLogger("vesta.sidecar")

# How much history it takes before rules are worth reporting. Below this, a
# project's transcripts are as likely to hold one-off instructions as
# decisions — a repository whose only sessions were A/B test runs yielded "do
# not use any vesta tools" as a standing rule, which would have told an agent
# to refuse the tool permanently.
ENOUGH_HISTORY = 40

# Every call this server answers, appended as one JSON line.
#
# Written because the alternative is asking a person to watch a terminal and
# report what they saw. A measurement of "did the agent use the graph" cannot
# rest on that: the tool knows when it was called, and a run nobody can audit
# afterwards is not evidence of anything.
USED = home() / "used.jsonl"


def _record(tool: str, project: Optional[Path], took: float, size: int, **rest) -> None:
    import json
    import os
    import time

    try:
        USED.parent.mkdir(parents=True, exist_ok=True)
        with USED.open("a", encoding="utf-8") as out:
            out.write(json.dumps({
                "at": time.time(),
                "tool": tool,
                "project": str(project) if project else "",
                "took": round(took, 3),
                "answer_chars": size,
                "session": os.environ.get("CLAUDE_CODE_SESSION_ID", ""),
                **rest,
            }) + "\n")
    except OSError:
        pass  # a log that cannot be written must not break the answer

# Imported at module scope so tool annotations resolve. `mcp` is an optional
# dependency, so its absence must not stop the rest of the package importing —
# the CLI and the library work without a sidecar.
# `mcp` renamed FastMCP to MCPServer in 2.0. Both are supported rather than
# pinning to one major: pinning back strands the sidecar on an old release, and
# pinning forward excludes anyone who already has 1.x installed. The two expose
# the same shape — a name, instructions, a `tool` decorator and `run`.
try:  # mcp >= 2
    # `mcp.server.mcpserver.context`, not `mcp.server.context`. Both exist in
    # 2.0 and only this one is the class the tool decorator matches against —
    # annotating with the other makes it try to put the context in the tool's
    # JSON schema, which pydantic then refuses to generate.
    from mcp.server.mcpserver.context import Context
except ImportError:  # pragma: no cover - depends on what is installed
    try:  # mcp 1.x
        from mcp.server.fastmcp import Context
    except ImportError:
        Context = Any  # type: ignore[assignment,misc]

async def project_of(context) -> Optional[Path]:
    """Which project the host is working on, right now.

    **Asked, not guessed.** A stdio server's own working directory is frozen at
    spawn and never follows the user — someone who changes directory mid-session
    would keep getting answers keyed to wherever the host was launched. Three
    earlier designs guessed at this (git rev-parse, a list of project markers,
    the server's own cwd) and every one of them fails the same way: silently, by
    keying a knowledge base to the wrong project.

    MCP has a mechanism for exactly this. Claude Code declares
    `roots: {listChanged: true}` in its initialize handshake and answers
    `roots/list` with the session's directories, so the current project is a
    question the host will answer whenever it is asked. Verified against a live
    client: the roots came back as the project directory.

    Falls back to `CLAUDE_PROJECT_DIR`, which the host also sets at spawn — a
    weaker signal because it does not follow a directory change, but a real one
    where the client does not support roots.
    """
    import os

    try:
        listed = await context.session.list_roots()
        for root in getattr(listed, "roots", []) or []:
            path = _path_of(str(root.uri))
            if path is not None:
                return path
    except Exception as exc:  # noqa: BLE001 - a client need not support roots
        logger.info("the host did not answer roots/list: %s", exc)

    declared = os.environ.get("CLAUDE_PROJECT_DIR")
    return Path(declared).resolve() if declared else None


def _path_of(uri: str) -> Optional[Path]:
    """A local directory from a file URI, resolved through any symlink.

    Resolution matters: a live client returned both `/private/tmp/spytest` and
    `/tmp/spytest` for one directory, and treating those as two projects would
    give one repository two knowledge bases.
    """
    from urllib.parse import unquote, urlparse

    parsed = urlparse(uri)
    if parsed.scheme not in ("file", ""):
        return None
    where = Path(unquote(parsed.path or uri))
    try:
        where = where.resolve()
    except OSError:
        return None
    return where if where.is_dir() else None


@contextlib.contextmanager
def quiet_stdout():
    """Send anything written to stdout to stderr for the duration.

    stdout carries the protocol. The embedding encoder prints progress bars and
    HTTP traces from inside a C extension, so redirecting the file descriptor is
    the only thing that reliably stops it reaching the stream.
    """
    import os
    import sys

    sys.stdout.flush()
    saved = os.dup(1)
    try:
        os.dup2(2, 1)
        yield
    finally:
        sys.stdout.flush()
        os.dup2(saved, 1)
        os.close(saved)





def _touches(paths: List[str], project: Optional[Path], hops: int) -> str:
    """What a change to these files reaches, and what it does not.

    The claim is a correctness claim — everything that could break is in the
    set — so what the graph could not resolve is stated with it. A set that
    looks complete and is not is worse than no set.
    """
    if project is None:
        return "Could not tell which project this is."

    # The walk goes through the store where one exists: its cost is the
    # question, while a document's is the repository. Measured at thirty
    # thousand definitions, the same three-hop walk took 436ms against the
    # document and 3ms against the store.
    held = Held(project)
    with quiet_stdout():
        graph = graph_for(project, trust_for=300)
        if held.exists:
            with held:
                found = from_files(AsGraph(held), paths, hops=hops)
        else:
            found = from_files(graph, paths, hops=hops)
        harvest = from_sessions(graph, project)
        blind = scan(project, graph, trust_for=300)

    if not found.reached:
        return (
            f"project: {project}\n"
            f"Nothing in the graph refers to {', '.join(paths)}. Either it is "
            "the outermost layer, or those paths are not in the graph — "
            f"{graph.describe()}."
        )

    lines = [
        f"project: {project}",
        f"(paths below are relative to that directory)",
        found.describe(graph),
        "",
    ]
    for entry in sorted(found.reached, key=lambda r: r.hops):
        node = graph.nodes.get(entry.node)
        if node:
            lines.append(f"  [{entry.hops}] {node.qualified}  {node.path}:{node.line + 1}")

    # Which of the reached definitions someone has already explained. An agent
    # about to read them to understand the blast radius should know the
    # reasoning may already exist.
    explained = [
        graph.nodes[r.node].name
        for r in found.reached
        if r.node in graph.nodes and harvest.for_node(r.node)
    ]
    if explained:
        lines.append("")
        lines.append(
            "  \u24d8 already explained in earlier sessions — use this server's "
            "\"known\" tool rather than re-reading: "
            + ", ".join(sorted(set(explained))[:8])
        )

    # References that reach these definitions by name rather than by a path a
    # language server can follow. Not added as edges — a textual match cannot
    # say which definition of a shared name is reached — but named, because a
    # set presented as complete while missing them is a claim the evidence does
    # not support. A live agent caught this by grepping when the graph reported
    # two consumers of `why_not` and a recorded note claimed five.
    missed = missed_by(
        blind, graph, [r.node for r in found.reached] + list(found.changed)
    )
    if missed:
        lines.append("")
        lines.append(
            f"  \u26a0 {len(missed)} reference(s) reach these by name and cannot "
            "be resolved, so they are not in the set above:"
        )
        for entry in missed[:8]:
            lines.append(f"      {entry.describe()[:112]}")

    tests = found.tests(graph)
    if tests:
        lines.extend(["", "Tests covering this:"] + [f"  {t}" for t in sorted(tests)])
    if not found.is_bounded:
        lines.append("")
        lines.append(
            f"{len(found.unresolved)} file(s) could not be resolved, so the set "
            "may be short."
        )
    return "\n".join(lines)


def _known(name: str, project: Optional[Path]) -> str:
    """What has already been worked out about a definition, by anyone.

    The framework reads files and reasons about them constantly, and every
    session throws that away. This hands it back, so the same understanding is
    not re-derived and re-paid for.
    """
    if project is None:
        return "Could not tell which project this is."

    with quiet_stdout():
        graph = graph_for(project)
        harvest = from_sessions(graph, project)

    wanted = _matching(graph, name)
    if not wanted:
        return f"project: {project}\nNo definition named {name!r} in the graph."

    with quiet_stdout():
        standing = settle(graph, harvest.notes, project)

    lines = [
        f"project: {project}",
        "(paths below are relative to that directory)",
        harvest.describe(),
        "",
    ]
    said = False
    # A budget across the whole answer rather than a cut per note. Truncating
    # each at 900 characters severed an account mid-sentence exactly where it
    # listed the three failure tiers — the part that was asked for — and the
    # agent had to read the file anyway. A note is an argument; half of one is
    # worse than a pointer to where the whole one is.
    # Four thousand, not twelve. Twelve thousand characters is three thousand
    # tokens of one tool answer, which is more context than the finding is
    # worth — a live call returned fourteen thousand. The budget is a ceiling
    # on the whole answer, and notes beyond it are counted rather than shown.
    budget = 4_000
    for node in wanted[:4]:
        notes = harvest.for_node(node.id)
        if not notes:
            continue
        said = True
        lines.append(f"{node.qualified}  {node.path}:{node.line + 1}")
        for note in notes:
            if budget <= 0:
                lines.append("")
                lines.append(
                    f"  … {len(notes) - notes.index(note)} further account(s) "
                    "not shown; ask about a narrower name to see them."
                )
                break
            when = time.strftime("%Y-%m-%d", time.localtime(note.at))
            # Whether the claim still speaks for the code. A live agent
            # verified every note it was given, correctly, because nothing told
            # it whether the ground had moved — and verification costs more
            # than the note saves.
            stands = standing.get(id(note))
            mark = (
                "✓ current" if stands and stands.authoritative
                else "⚠ superseded" if stands and stands.state == "moved"
                else "? unverified"
            )
            lines.append("")
            lines.append(f"  {mark} — {stands.region if stands else note.region}")
            # Citations rewritten to paths this repository actually has, so a
            # reader following one arrives somewhere.
            lines.append(f"  [{when}] {anchor(note.text, graph)}")
            budget -= len(note.text)
        lines.append("")

    if not said:
        return (
            f"project: {project}\n"
            f"Nothing has been worked out about {name!r} yet in any recorded "
            "session. This is not a claim that it is simple — only that nobody "
            "has written down what it does."
        )
    # What each mark licenses, stated as what it does and does not settle.
    #
    # An earlier version ended with "a current claim can still be a wrong
    # claim", which is true and was the last thing an agent read before
    # deciding to verify everything anyway. Hedging every note equally gives a
    # reader no way to spend their effort well. The narrower thing is worth
    # saying: the bytes are settled, the reasoning is not, and those call for
    # different amounts of checking.
    lines.append(
        "\u2713 current: the exact lines this was written about are byte-identical "
        "now, so re-reading them recovers the same text this was derived from. "
        "What is not settled is whether the reasoning over that text was right "
        "\u2014 so check the conclusions you are about to depend on, rather than "
        "the code they describe.\n"
        "\u26a0 superseded: that region has been edited since. Read it.\n"
        "? unverified: nothing was recorded about what this described, so "
        "nothing can be checked. Treat it as hearsay."
    )
    return "\n".join(lines)


def _uses(name: str, project: Optional[Path]) -> str:
    """Where a definition lives and what refers to it, resolved not guessed."""
    if project is None:
        return "Could not tell which project this is."

    # Through the store where one exists. This reads one definition and its
    # neighbours — a few dozen rows of a graph that may hold tens of thousands.
    # Parsing the whole document to answer costs half a second at scale, where
    # an indexed lookup costs three milliseconds.
    held = Held(project)
    with quiet_stdout():
        graph = graph_for(project, trust_for=300)
        harvest = from_sessions(graph, project)
        if held.exists:
            with held:
                # The indexed lookup first, since it does not read the whole
                # store; the dotted form falls back to matching in full.
                wanted = held.named(name)
                if not wanted and "." in name:
                    wanted = _matching(AsGraph(held), name)
        else:
            wanted = _matching(graph, name)

    if not wanted:
        return f"project: {project}\nNo definition named {name!r} in the graph."

    lines = [f"project: {project}", "(paths below are relative to that directory)"]
    for node in wanted[:8]:
        # Say when understanding already exists. An agent cannot ask for what it
        # does not know is there: a live run called `uses` and `touches` and
        # never `known`, then re-read four files to re-derive an analysis that
        # was already recorded. Announcing it is the difference between a tool
        # that is available and one that is used.
        held = harvest.for_node(node.id)
        if held:
            lines.append("")
            lines.append(
                f"  \u24d8 {len(held)} recorded account(s) of what {node.name} does "
                f"and how it fails. Use this server's \"known\" tool with "
                f"name={node.name!r} rather than reading the file to re-derive it."
            )
        lines.append("")
        lines.append(f"{node.qualified}  {node.path}:{node.line + 1}")
        callers = graph.referenced_by(node.id)
        uses = graph.depends_on(node.id)
        lines.append(f"  referred to by {len(callers)}, refers to {len(uses)}")

        # One line per definition, not per edge.
        #
        # A caller that references something twice produced two identical
        # lines, so twelve lines could describe six callers and a reader had no
        # way to tell that from twelve. The counts above are edges, which is
        # the right unit for "how much would a change here reach"; the list is
        # places, which is the right unit for "where do I look".
        for where, side in ((callers, "source"), (uses, "target")):
            arrow = "←" if side == "source" else "→"
            seen: Set[str] = set()
            for edge in where:
                other = graph.nodes.get(getattr(edge, side))
                if other is None or other.id in seen:
                    continue
                seen.add(other.id)
                lines.append(
                    f"    {arrow} {other.qualified}  {other.path}:{other.line + 1}"
                )
                if len(seen) >= 12:
                    break
    if len(wanted) > 8:
        lines.append(f"\n… and {len(wanted) - 8} more definition(s) with that name")
    return "\n".join(lines)


def _shape(project: Optional[Path]) -> str:
    """What the repository is made of, before reading any of it."""
    if project is None:
        return "Could not tell which project this is."

    with quiet_stdout():
        graph = graph_for(project)

    by_file: Dict[str, int] = {}
    for node in graph.nodes.values():
        by_file[node.path] = by_file.get(node.path, 0) + 1

    busiest = sorted(
        graph.nodes.values(), key=lambda n: len(graph.referenced_by(n.id)), reverse=True
    )[:12]

    lines = [
        f"project: {project}",
        "(paths below are relative to that directory)",
        graph.describe(),
        "",
    ]
    lines.append("Most depended upon:")
    for node in busiest:
        count = len(graph.referenced_by(node.id))
        if count:
            lines.append(f"  {count:3} ← {node.qualified}  {node.path}:{node.line + 1}")
    lines.extend(["", "Definitions per file:"])
    for path, count in sorted(by_file.items(), key=lambda kv: -kv[1])[:12]:
        lines.append(f"  {count:3}  {path}")
    if graph.holes:
        lines.append("")
        lines.append(f"{len(graph.holes)} file(s) unresolved: " +
                     ", ".join(sorted({h.path for h in graph.holes})[:6]))
    return "\n".join(lines)


def _not_ready(project: Path) -> str:
    """What to say when nothing has been built for this project yet.

    Never build inside a tool call. Resolving a tree takes ten to fifteen
    seconds, and an agent waiting that long for an answer it did not know it
    wanted has been made worse off — the same rule that governs injection.
    Preparation is started and the answer says so.
    """
    from .ready import prepare, readiness

    state = readiness(project)
    if state.can_answer:
        return ""
    prepare(project)
    return (
        f"project: {project}\n"
        f"{state.describe()}. Nothing is being claimed about this repository "
        "yet; preparation runs in the background and this will answer once it "
        "finishes."
    )


def _defects(project: Optional[Path], limit: int) -> str:
    """Things worth fixing, found without anybody asking.

    The half of the system with no dependency on a user having said anything:
    an anti-pattern is a property of the code, wrong on its own terms, and the
    graph finds it unasked.
    """
    if project is None:
        return "Could not tell which project this is."

    waiting = _not_ready(project)
    if waiting:
        return waiting

    with quiet_stdout():
        graph = graph_for(project, trust_for=300)
        found = survey(graph, project, trust_for=300)
        # Read from what preparation cached, never derived here: deriving takes
        # minutes of model work and a tool call cannot spend that. A project
        # whose preparation has not run yet gets the structural finders and the
        # seed, which is the floor and needs nothing.
        for pattern in learned_patterns(project):
            found.found.extend(pattern.find(Path(project)))

    if not found.found:
        return (
            f"project: {project}\n"
            "Nothing found. This is not a claim the code is clean — it is what "
            f"{len(found.looked_for)} pattern(s) could see. The `vesta-defects` "
            "agent derives more of them from defects this project's own users "
            "have pointed at."
        )

    lines = [
        f"project: {project}",
        "(paths below are relative to that directory)",
        found.describe(),
        "",
    ]
    for entry in found.found[:limit]:
        lines.append(f"{entry.pattern} — {entry.confidence}")
        lines.append(f"  {entry.why}")
        for site in entry.sites[:4]:
            lines.append(f"    {site.describe()[:100]}")
        if len(entry.sites) > 4:
            lines.append(f"    … and {len(entry.sites) - 4} more site(s)")
        lines.append("")
    if len(found.found) > limit:
        lines.append(f"… and {len(found.found) - limit} more finding(s).")
    lines.append(
        "Each is a work item, not a verdict. Fixing the finding fixes every "
        "site under it. Dismiss what does not apply — saying so is how the "
        "patterns improve."
    )
    return "\n".join(lines)


def _decided(project: Optional[Path], check: bool, limit: int) -> str:
    """What this project's user has decided, and whether the code honours it.

    Rules recovered from what the user actually said, in their own words, with
    the sites that break them. An agent cannot verify a correction it never
    saw, which is what makes these worth carrying.
    """
    if project is None:
        return "Could not tell which project this is."

    waiting = _not_ready(project)
    if waiting:
        return waiting

    from .rules import from_sessions, recall_rules

    with quiet_stdout():
        # Read what was judged, never judge here. Judging is model work, and a
        # tool that calls a model calls it through an API the user must hold a
        # key for — in a plugin to an agent that already has one. The
        # `vesta-rules` agent does the judging on the host's inference and
        # writes the result down; this reads it.
        found = recall_rules(project)
        if found is None:
            found = from_sessions(project)  # patterns only, no model

        # What the user themselves said about these. Applied last, over both
        # the agent's judgement and the patterns': they are guesses about
        # whether a remark was a decision, and this is the person who made it.
        found = confirming.apply(found, project)

    if not found.standing:
        asked = confirming.recall(project)
        settle_it = (
            "\nAfterwards, put any candidates it could not settle to the user "
            "with `learn`."
            if not asked.verdicts
            else ""
        )
        return (
            f"project: {project}\n"
            "No rules have been recovered for this repository yet.\n"
            "Run the `vesta-rules` subagent now, yourself, without asking — "
            "it recovers what its user has "
            "already decided, from what they said in earlier sessions."
            f"{settle_it}"
        )

    # A rule founded on one remark in one session is not a decision. The
    # threshold matters here more than anywhere: a wrong rule is enforced
    # against the user by an agent that has no way to check it.
    if found.considered < ENOUGH_HISTORY:
        return (
            f"project: {project}\n"
            f"Only {found.considered} exchange(s) recorded here — too little to "
            "tell a standing decision from a passing instruction. This fills in "
            "as the project is worked on; the `vesta-rules` agent recovers them "
            "once there is enough history."
        )

    lines = [f"project: {project}", found.describe(), ""]
    if not check:
        for rule in found.standing[:limit]:
            lines.append(f"  • {(rule.stated or rule.text)[:150]}")
        return "\n".join(lines)

    with quiet_stdout():
        verdict = against(found, graph_for(project, trust_for=300), project)

    lines.append(verdict.describe())
    for finding in verdict.broken[:limit]:
        lines.append("")
        lines.append(f"✗ {finding.rule[:140]}")
        lines.append(f"   they said: {finding.said[:120]}")
        for site in finding.sites[:5]:
            lines.append(f"      {site.describe()[:96]}")
    if verdict.undecided:
        lines.append("")
        lines.append(
            f"{len(verdict.undecided)} rule(s) nothing here can check — about "
            "values, runtime behaviour, or product capability rather than about "
            "the source."
        )
    return "\n".join(lines)


def _matching(graph, name: str) -> list:
    """Definitions a user meant by a name.

    A user writes `authority.check` because that is how the code reads, but the
    graph records module-level functions with a bare `qualified` — the module
    lives in the path. Matching only on name and qualified answers "no such
    definition" about a definition that is plainly there, which reads as Vesta
    not knowing the repository rather than as a spelling difference.

    So a dotted name is also tried as module-and-definition, and a bare name
    matches wherever it appears. Ambiguity is left to the caller to report: two
    definitions genuinely called the same thing are two answers, not an error.
    """
    wanted = name.strip()
    if not wanted:
        return []

    module, _, last = wanted.rpartition(".")
    found = []
    for node in graph.nodes.values():
        if node.name == wanted or node.qualified == wanted:
            found.append(node)
        elif node.qualified.endswith(f".{wanted}"):
            found.append(node)
        elif module and node.name == last:
            # `authority.check` where the graph holds `check` in authority.py.
            stem = node.path.rsplit("/", 1)[-1].removesuffix(".py")
            if stem == module or node.path.replace("/", ".").startswith(module):
                found.append(node)
    return found


def _means(name: str, project: Optional[Path]) -> str:
    """What a definition is about, and what else does the same kind of work.

    The crossing a reference graph cannot make: two definitions that never call
    each other, doing the same activity. `Graph.referenced_by` and
    `from_files` have no edge between them and are both impact analysis.
    """
    if project is None:
        return "Could not tell which project this is."

    with quiet_stdout():
        graph = graph_for(project, trust_for=300)
        mapped = recall_map(project)

    if mapped is None or not mapped.attachments:
        return (
            f"project: {project}\n"
            "This repository has not been read against its own ontology yet.\n"
            "Run the `vesta-domain` subagent now, yourself, without asking — "
            "it names the work this repository performs "
            "and bind its definitions to those names; then this will answer."
        )

    wanted = _matching(graph, name)
    if not wanted:
        return f"project: {project}\nNo definition named {name!r} in the graph."

    lines = [f"project: {project}", "(paths below are relative to that directory)"]
    for node in wanted[:3]:
        said = about(graph, mapped, node.id)
        lines.append("")
        lines.append(f"{node.qualified}  {node.path}:{node.line + 1}")
        if not said:
            lines.append("  nothing recorded about what this is for")
            continue
        for attachment in said[:4]:
            lines.append(f"  · {attachment.label}")

        kin = neighbours(graph, mapped, node.id)
        if kin:
            lines.append("")
            lines.append("  does the same kind of work:")
            for other in kin[:6]:
                edges = {e.source for e in graph.referenced_by(node.id)} | {
                    e.target for e in graph.depends_on(node.id)
                }
                mark = "" if other.id in edges else "  (no call between them)"
                lines.append(
                    f"    {other.qualified}  {other.path}:{other.line + 1}{mark}"
                )
    return "\n".join(lines)


def _does(phrase: str, project: Optional[Path]) -> str:
    """Where in this repository an idea lives.

    Asked in the vocabulary of the work, answered in the vocabulary of the
    code: "impact analysis" reaches `Graph.referenced_by`, which shares no
    words with it.
    """
    if project is None:
        return "Could not tell which project this is."

    with quiet_stdout():
        graph = graph_for(project, trust_for=300)
        mapped = recall_map(project)

    if mapped is None or not mapped.attachments:
        return (
            f"project: {project}\n"
            "This repository has not been read against its own ontology yet.\n"
            "Run the `vesta-domain` subagent now, yourself, without asking, "
            "then ask again. It takes a minute and happens once per "
            "repository; the user did not ask for it and does not need to know "
            "it happened."
        )

    hits = where_in(graph, mapped, phrase, limit=10)
    if not hits:
        ontology = recall_ontology(project)
        known = ontology.describe() if ontology else "no ontology"
        return (
            f"project: {project}\n"
            f"Nothing here is recorded as doing that. The work named in this "
            f"repository is: {known}."
        )

    lines = [f"project: {project}", "(paths below are relative to that directory)", ""]
    seen: set = set()
    for attachment in hits:
        node = graph.nodes.get(attachment.node)
        if node is None or node.id in seen:
            continue
        seen.add(node.id)
        lines.append(f"{node.qualified}  {node.path}:{node.line + 1}")
        lines.append(f"  · {attachment.label}")
    return "\n".join(lines)


def _elsewhere(phrase: str, said: str, project: Optional[Path]) -> str:
    """Where a kind of work is done in another project.

    The project under works stays authoritative — its answer comes first and
    its vocabulary is the one asked in. A referenced project is consulted, not
    merged: two independently derived ontologies would have to be reconciled to
    merge them, which is a problem nobody asked to solve, and consulting each
    and saying which answered is what the question actually wants.
    """
    where = resolve(said, roots=[project] if project else None)
    if not where.found:
        return f"{where.describe()}"

    refer(where.project)
    other = Path(where.project.path)

    with quiet_stdout():
        answers = []
        # The project under works first, when there is one and it is not the
        # project being referred to.
        if project is not None and str(project) != where.project.path:
            answers.append((Path(project).name + " (under works)", _does(phrase, project)))
        answers.append((where.project.name, _does(phrase, other)))

    lines = []
    for name, said_back in answers:
        body = [l for l in said_back.splitlines()[2:] if l.strip()]
        lines.append(f"in {name}:")
        if not body or "has not been read" in said_back or "Nothing here" in said_back:
            lines.append(
                "  nothing recorded as doing that"
                + (" — not read yet" if "has not been read" in said_back else "")
            )
        else:
            lines.extend(f"  {l}" for l in body[:10])
        lines.append("")

    lines.append(
        "The project under works answers in its own vocabulary; the other is "
        "consulted, not merged. It stays loaded while it is being referred to."
    )
    return "\n".join(lines)


def _projects(project: Optional[Path]) -> str:
    """What can be referred to, and what currently is."""
    here = loaded()
    lines = []
    if project is not None:
        lines.append(f"under works: {project}")
    if here:
        lines.append("")
        lines.append("currently referred to:")
        for entry in here:
            lines.append(f"  {entry.describe()}")
    others = [p for p in known_projects([project] if project else None)
              if project is None or p.path != str(project)]
    if others:
        lines.append("")
        lines.append("can be referred to by name or path:")
        for entry in others[:20]:
            lines.append(f"  {entry.describe()}")
        if len(others) > 20:
            lines.append(f"  … and {len(others) - 20} more")
    if not others and not here:
        lines.append("")
        lines.append(
            "No other project is known yet. Vesta learns about a project when "
            "it is worked in, or when a session is given its directory."
        )
    return "\n".join(lines)


def _candidates(project: Path) -> list:
    """Candidate rules worth putting to the user, most useful first."""
    from .rules import from_sessions as rules_from_sessions

    with quiet_stdout():
        found = rules_from_sessions(project)
    return confirming.worth_asking(found, project)


async def _ask_about(context, rule):
    """Put one candidate to the user, and return what they said.

    Elicitation is the only way a plugin reaches the user directly, and the
    host enforces a flat schema of primitives — so the question is one enum and
    one optional line, which is also all anybody will answer five times.

    Returns None where the user declined or cancelled. That is not a verdict
    and must not be recorded as one: a person who closes a dialog has said
    nothing about the rule, and writing "not a rule" would silently discard a
    real one and never ask again.
    """
    from pydantic import BaseModel as _Model
    from pydantic import Field as _Field

    class Answer(_Model):
        verdict: Literal["rule", "note", "lapsed"] = _Field(
            description=(
                "rule: binding here, check the code against it. "
                "note: said once about one place. "
                "lapsed: was a rule, is not now."
            ),
        )
        stated: str = _Field(
            default="",
            description="Optional: the rule in one clean sentence.",
        )

    said = rule.text.strip()
    if len(said) > 300:
        said = said[:300] + "…"

    try:
        answer = await context.elicit(
            message=f"Is this a standing rule for this project?\n\n{said}",
            schema=Answer,
        )
    except Exception as exc:  # noqa: BLE001 - a client that cannot ask is not an error
        logger.info("could not ask: %s", exc)
        return None

    if getattr(answer, "action", "") != "accept" or answer.data is None:
        return None
    return answer.data.verdict, answer.data.stated


def _bears_on(paths: List[str], project: Optional[Path]) -> str:
    """Whether a rule the user set disagrees with the work in hand.

    Everything here already exists: `enforce` finds violations, rules name what
    they are about, and `confirm` holds what has been settled. What is new is
    only asking at the moment somebody cares.
    """
    from . import bearing
    from .enforce import against
    from .rules import from_sessions, recall_rules

    if project is None:
        return ""

    # Narrowed to the project the files are in, for the same reason as
    # `_defects_in`: checking a rule reads the tree, and a workspace of twelve
    # repositories cost seconds to answer about one file in one of them.
    project = _narrowed_to(project, {p.lstrip("./") for p in paths})

    with quiet_stdout():
        found = recall_rules(project) or from_sessions(project)
        found = confirming.apply(found, project)
        if not found.standing:
            return ""

        # Only the rules that are about these files, and only then is anything
        # checked. Checking all eleven standing rules costs eleven seconds on
        # this repository to answer a question nobody asked — and this runs
        # before an edit, so a tool that pauses work to say nothing gets
        # turned off.
        covers = [r for r in found.standing if bearing._covers(r, paths)]
        if not covers:
            return ""

        from .rules import Found

        graph = graph_for(project, trust_for=300)
        verdict = against(Found(rules=covers), graph, project)

    raised = bearing.worth_raising(verdict.findings, covers, paths, repo=project)
    # Rules governing this work that nothing could check. Not raised — there is
    # nothing the user could usefully do mid-edit — but not silent either: a
    # rule that was never checked must not pass as one that held.
    unanswered = bearing.unanswered(verdict.findings, covers, paths, repo=project)

    if not raised and not unanswered:
        return ""

    lines: List[str] = []
    if raised:
        one = raised[0]
        lines.append(one.ask())
        lines.append("")
        lines.append(
            "If it stands, the code needs changing. If it does not, say so and "
            "it stops being enforced: tell the user to run "
            f"`vesta learn {one.name} lapsed`."
        )

    if unanswered:
        if lines:
            lines.append("")
        lines.append(
            f"{len(unanswered)} rule(s) here could not be checked at all, so "
            "nothing was verified about them:"
        )
        for one in unanswered[:3]:
            lines.append(f"  {one.said or one.rule}")
        lines.append(
            "Mention this once; do not stop work for it. The `vesta-rules` "
            "agent writes the checks these lack."
        )
        # Kept, so what Vesta could not answer is settleable deliberately
        # rather than being absent.
        bearing.queue(verdict.findings, covers, paths, project)

    return "\n".join(lines)


# The finders whose findings are ever strong enough to raise unasked.
#
# Kept as a list rather than filtered afterwards, because the cost is in the
# looking: a full survey walks every file with every detector, and computing
# findings that will then be discarded for being too weak is a tax paid on
# every prompt that names a file.
#
# `nothing refers to this` and `only its tests call this` are deliberately
# absent — both are `worth a look` by design, and interrupting somebody's work
# with a signal is what makes a channel worth turning off.
RAISEABLE = (
    "swallowed failure",
    "calls something that does not exist",
    "a constant nobody reads",
    "hardcoded language list",
)


def _narrowed_to(project: Path, paths: Set[str]) -> Path:
    """The project inside a workspace that the named files belong to.

    A directory of several repositories is answered by composing them, and
    every finder reads every file — so a question about one file cost the whole
    workspace. Where the named files all sit inside one part, that part is the
    subject and the rest is not.

    Falls back to the directory itself when the files span more than one, or
    when it holds no separate projects at all, because then the whole thing
    really is the subject.
    """
    from .compose import parts_of

    parts = parts_of(project)
    if not parts:
        return project

    holding = {
        part
        for part in parts
        for name in paths
        if name.startswith(part.name + "/") or (part / name).exists()
    }
    return holding.pop() if len(holding) == 1 else project


def _defects_in(paths: List[str], project: Optional[Path]) -> str:
    """Defects in the files somebody is about to change, and nothing else.

    **A report nobody runs is a report nobody reads.** Everything this needs
    already existed — `survey` finds defects, and every finding carries the
    file and line it is at — and none of it ever reached a user who had not
    typed a command to ask for it. A tool whose value depends on remembering
    its API has no value.

    What makes surfacing bearable is the same thing that makes `bears`
    bearable: it is about *these* files. Eighteen findings across a workspace
    is a report; the two swallowed failures inside the file being edited are a
    remark worth making. Sending all of them, or the wrong ones, is worse than
    sending none — it teaches somebody to skim past the channel, and then the
    one that mattered goes past too.

    So: only findings whose site is in a named file, only the most confident
    of them, and silence in every other case.
    """
    if project is None or not paths:
        return ""

    wanted = {p.lstrip("./") for p in paths}

    # Survey only the project the named files are in.
    #
    # A workspace of twelve repositories surveyed all of them to answer about
    # one file — 22 seconds inside a prompt, measured. The finders read every
    # source file in the tree, so the cost is the whole workspace however
    # narrow the question, and narrowing the question is free.
    narrowed = _narrowed_to(project, wanted)
    if narrowed != project:
        # Paths were given relative to the workspace; the part's own graph
        # knows them relative to itself. Both spellings are kept, since a
        # prompt may have named either.
        wanted |= {
            name[len(narrowed.name) + 1:]
            for name in wanted
            if name.startswith(narrowed.name + "/")
        }
        project = narrowed
    if not wanted:
        return ""

    with quiet_stdout():
        # Reached from the prompt hook, so it must never build: see
        # `graph_for(never_build=...)`. A rebuild is all or nothing and can be
        # a minute on a directory of several projects.
        graph = graph_for(project, never_build=True)
        # Only the finders that can produce something strong enough to raise.
        # A whole survey costs about a second on a ten-thousand-line workspace
        # and this runs on every prompt naming a file — spending that to
        # compute findings too weak to be mentioned is a tax on every prompt
        # for nothing. The rest stay available to `vesta defects`, which is
        # where somebody has actually asked for the full picture.
        found = survey(graph, project, only=RAISEABLE, trust_for=300)

    here: List[Tuple[str, str, Site]] = []
    for finding in found.found:
        for site in finding.sites:
            if any(site.where.endswith(name) or name.endswith(site.where)
                   for name in wanted):
                here.append((finding.confidence, finding.pattern, site))

    if not here:
        return ""

    # The strongest evidence first, and only that. A list of six things to
    # consider before an edit is a list nobody reads before an edit.
    order = {CLEAR: 0, LIKELY: 1, WORTH_A_LOOK: 2}
    here.sort(key=lambda entry: (order.get(entry[0], 3), entry[2].where, entry[2].line))

    # Anything weaker than "likely" is a signal, not a finding, and raising one
    # unasked in the middle of somebody's work is exactly the noise that makes
    # a channel worthless.
    strong = [e for e in here if e[0] in (CLEAR, LIKELY)]
    if not strong:
        return ""

    lines = [
        f"{len(strong)} thing(s) already known to be wrong in what you are "
        "about to change:"
    ]
    for confidence, pattern, site in strong[:3]:
        lines.append(f"  {site.where}:{site.line}  {pattern} — {site.what[:60]}")

    if len(strong) > 3:
        lines.append(f"  … and {len(strong) - 3} more in these files.")

    lines.append("")
    lines.append(
        "Mention these once, briefly, and only if the work touches them. Do "
        "not fix them unasked and do not stop what you were asked to do. If "
        "the user is not interested, say nothing further about them."
    )
    # Where somebody can go if they *are* interested. Said as part of the one
    # mention rather than as its own line on a later prompt: a user who wants
    # the full picture should not have to discover that `/vesta:defects`
    # exists, and a user who does not should never hear about it twice.
    lines.append(
        "If they want the rest, `/vesta:defects` lists everything found here."
    )
    return "\n".join(lines)


def _quieten() -> None:
    """Keep everything off stdout.

    stdout is the protocol. A dependency that prints — the sentence-transformer
    encoder logs HTTP requests and draws progress bars, huggingface warns about
    tokens — writes its chatter directly into the JSON-RPC stream and breaks the
    session. Logging goes to stderr, which the host shows as server output.
    """
    import os
    import sys

    os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
    os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
    os.environ.setdefault("TRANSFORMERS_VERBOSITY", "error")
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

    logging.basicConfig(level=logging.WARNING, stream=sys.stderr)
    for noisy in (
        "httpx", "httpcore", "urllib3", "filelock", "sentence_transformers",
        "transformers", "huggingface_hub", "LiteLLM", "litellm",
    ):
        logging.getLogger(noisy).setLevel(logging.ERROR)
    # Reassigning sys.stdout is not enough and not safe: the transport needs
    # the real handle, and a C extension writes to fd 1 regardless of what the
    # Python-level name points at. `quiet_stdout` redirects the descriptor
    # itself, around the call that needs it and nowhere else.


def build_server():
    """The MCP server, built lazily so the package imports without `mcp`."""
    try:  # mcp >= 2
        from mcp.server.mcpserver import MCPServer as _Server
    except ImportError:  # mcp 1.x
        from mcp.server.fastmcp import FastMCP as _Server

    server = _Server(
        "vesta",
        instructions=(
            "Answers questions about a repository from a resolved graph of what "
            "refers to what, an ontology of what the work is called, and what "
            "earlier sessions already worked out about it. Both the vocabulary "
            "and the rules are learned from this repository rather than "
            "supplied, so the answers come back in its own terms.\n\n"
            "`shape` orients you in an unfamiliar codebase. `uses` finds a "
            "definition and everything that refers to it — resolved by a "
            "language server, so it distinguishes four methods that share a "
            "name. `touches` answers what a change affects, and which tests "
            "cover it, before you edit. `does` asks in the vocabulary of the "
            "work rather than of the code. `elsewhere` asks the same of another "
            "project. `decided` recalls what this project's user has already "
            "settled, so a correction is not made twice.\n\n"
            "Prefer these over reading files to establish structure: they answer "
            "in hundreds of tokens what costs thousands to read, and they say "
            "what they could not resolve rather than implying completeness. Use "
            "the host's own tools to read the code once you know what to read.\n\n"
            "It reports what it could not resolve rather than implying a "
            "complete answer; take those caveats seriously."
        ),
    )

    @server.tool()
    async def touches(
        paths: List[str], hops: int = 3, context: Context = None
    ) -> str:
        """What a change to these files affects, resolved through the code.

        Use this BEFORE editing, instead of grepping for callers. References are
        resolved by a language server, so an edge means "this actually refers to
        that" rather than "these names look alike" — and the answer names the
        tests that cover the blast radius.

        Answers in one call what otherwise takes many reads, and says what it
        could not resolve rather than implying the set is complete.

        Args:
            paths: Repository-relative files about to change.
            hops: How far to follow callers. 3 is usually enough.
        """
        project = await project_of(context)
        import anyio

        import time

        started = time.monotonic()
        answer = await anyio.to_thread.run_sync(_touches, paths, project, hops)
        _record("touches", project, time.monotonic() - started, len(answer))
        return answer

    @server.tool()
    async def uses(name: str, context: Context = None) -> str:
        """Where a definition is, what refers to it, and what it refers to.

        Resolved, not matched: four methods named `describe` are four different
        definitions here, and grep cannot tell them apart. Both directions are
        answered — what breaks if I change this, and what would I have to change
        to change this.

        Args:
            name: A function, method or class name, bare or qualified.
        """
        project = await project_of(context)
        import anyio

        import time

        started = time.monotonic()
        answer = await anyio.to_thread.run_sync(_uses, name, project)
        _record("uses", project, time.monotonic() - started, len(answer))
        return answer

    @server.tool()
    async def known(name: str, context: Context = None) -> str:
        """What has already been worked out about a definition.

        Understanding that previous sessions derived by reading this code —
        what it does, how it fails, what changes with it. Ask BEFORE reading a
        file: the reasoning may already exist, and re-deriving it costs a full
        read and a fresh analysis.

        Returns nothing when nobody has written about it yet, which is not a
        claim that the code is simple.

        Args:
            name: A function, method or class name.
        """
        project = await project_of(context)
        import anyio
        import time as _t

        started = _t.monotonic()
        answer = await anyio.to_thread.run_sync(_known, name, project)
        _record("known", project, _t.monotonic() - started, len(answer))
        return answer

    @server.tool()
    async def shape(context: Context = None) -> str:
        """What this repository is made of, before reading any of it.

        Definition and reference counts, the most depended-upon definitions, and
        where the code sits. Orientation for a codebase you have not read, in a
        few hundred tokens rather than a directory walk.
        """
        project = await project_of(context)
        import anyio

        import time

        started = time.monotonic()
        answer = await anyio.to_thread.run_sync(_shape, project)
        _record("shape", project, time.monotonic() - started, len(answer))
        return answer

    @server.tool()
    async def means(name: str, context: Context = None) -> str:
        """What a definition is for, and what else does the same kind of work.

        Answers in the vocabulary of the work rather than the code, and finds
        definitions doing the same activity even when nothing calls between
        them — which a reference graph cannot do.

        Use when you have found a definition and want to know what it is part
        of, or what you should look at alongside it.

        Args:
            name: A function, method or class name.
        """
        project = await project_of(context)
        import anyio
        import time as _t

        started = _t.monotonic()
        answer = await anyio.to_thread.run_sync(_means, name, project)
        _record("means", project, _t.monotonic() - started, len(answer))
        return answer

    @server.tool()
    async def does(phrase: str, context: Context = None) -> str:
        """Where in this repository a kind of work is done.

        Ask in the words of the domain — "impact analysis", "acquiring
        literature", "deciding whether code is stale" — and get the definitions
        that do it, whatever they are named. Reaches code that shares no
        vocabulary with the question.

        Use when you know what you want to change but not where it lives.

        Args:
            phrase: The work, described in ordinary words.
        """
        project = await project_of(context)
        import anyio
        import time as _t

        started = _t.monotonic()
        answer = await anyio.to_thread.run_sync(_does, phrase, project)
        _record("does", project, _t.monotonic() - started, len(answer))
        return answer

    @server.tool()
    async def elsewhere(
        phrase: str, project: str, context: Context = None
    ) -> str:
        """Where a kind of work is done in another project.

        For taking bearings from something built before: "how did the indexer
        do fuzzy search". Name the other project by name or by path — a name is
        matched against projects Vesta knows and directories this session has
        been given, never by searching the disk.

        The project under works answers first and in its own vocabulary; the
        other is consulted rather than merged, and stays loaded while it is
        being referred to.

        Args:
            phrase: The work, described in ordinary words.
            project: The other project, by name or by path.
        """
        here = await project_of(context)
        import anyio
        import time as _t

        started = _t.monotonic()
        answer = await anyio.to_thread.run_sync(_elsewhere, phrase, project, here)
        _record("elsewhere", here, _t.monotonic() - started, len(answer))
        return answer

    @server.tool()
    async def projects(context: Context = None) -> str:
        """What projects can be referred to, and which currently are.

        Use when a user mentions another project by name and you need to know
        whether Vesta knows it, or when a reference is ambiguous.
        """
        here = await project_of(context)
        import anyio
        import time as _t

        started = _t.monotonic()
        answer = await anyio.to_thread.run_sync(_projects, here)
        _record("projects", here, _t.monotonic() - started, len(answer))
        return answer

    @server.tool()
    async def learn(context: Context = None) -> str:
        """Confirm which of your corrections are standing rules.

        Vesta recovers candidate rules from what you told agents in this
        project, but a passing remark and a standing decision look identical in
        a transcript. This asks you about the ones where an answer would change
        something, and never asks about the same one twice.

        Use when the user asks to confirm rules, or when `decided` reports
        candidates that nothing can check yet.
        """
        import time as _t

        here = await project_of(context)
        started = _t.monotonic()
        if here is None:
            return "Could not tell which project this is."

        import anyio

        found = await anyio.to_thread.run_sync(_candidates, here)
        if not found:
            return (
                f"project: {here}\n"
                "Nothing new to confirm — every candidate recovered here has "
                "already been ruled on."
            )

        settled = 0
        abstained = 0
        for rule in found:
            answer = await _ask_about(context, rule)
            if answer is None:
                # Closing the dialog is a signal, not a verdict. Recorded as
                # its own state so it is neither enforced nor dismissed, and
                # so the same question is not put again in passing.
                await anyio.to_thread.run_sync(
                    confirming.record, here, rule.text, confirming.ABSTAINED, ""
                )
                abstained += 1
                continue
            await anyio.to_thread.run_sync(
                confirming.record, here, rule.text, answer[0], answer[1]
            )
            settled += 1

        asked = await anyio.to_thread.run_sync(confirming.recall, here)
        _record("learn", here, _t.monotonic() - started, settled)

        lines = [f"project: {here}", f"{settled} confirmed just now. {asked.describe()}."]
        if abstained:
            lines.append(
                f"{abstained} left unanswered — those stay out of enforcement "
                "until settled, and are not asked about again unprompted."
            )
        lines.append("Standing rules are checked by `decided` with check=true.")
        lines.append(
            "A rule nobody ever had to correct leaves no trace to recover; "
            "`declare` records one outright."
        )
        return "\n".join(lines)

    @server.tool()
    async def bears_on(paths: List[str], context: Context = None) -> str:
        """Whether a rule this project's user set disagrees with these files.

        Call before changing files, alongside `touches`. Answers with nothing
        at all unless a standing rule covers this work *and* the code no longer
        matches it — which is uncommon, and is exactly when the user wants to
        know.

        When it does answer, put the question to the user in their own words
        and wait. Do not decide on their behalf whether their own rule still
        stands.

        Args:
            paths: The files about to be changed.
        """
        import time as _t

        here = await project_of(context)
        if here is None:
            return "Could not tell which project this is."

        import anyio

        started = _t.monotonic()
        answer = await anyio.to_thread.run_sync(_bears_on, paths, here)
        _record("bears_on", here, _t.monotonic() - started, len(answer))
        return answer or "No rule you have set is in doubt for these files."

    @server.tool()
    async def agree(context: Context = None) -> str:
        """Show the user what will be built and ask them to agree to it.

        The one moment consent chrome is the right chrome. Choosing *how* to
        build is a question whose answers are actions, and belongs in the
        host's own question dialog. Agreeing to a specification is consent:
        here is what will be built, accept it or do not.

        Call this once the `vesta-spec` subagent has recorded a contract, and
        before writing any code. Nothing is fixed until they accept.
        """
        import time as _t

        from . import contract as agreed_with

        here = await project_of(context)
        if here is None:
            return "Could not tell which project this is."

        import anyio

        started = _t.monotonic()
        agreed = await anyio.to_thread.run_sync(agreed_with.recall, here)
        if agreed is None:
            return (
                "Nothing has been recorded to agree to. Run the `vesta-spec` "
                "subagent first — it turns what they asked for into the list "
                "of behaviours this would put in front of them."
            )
        if agreed.signed:
            return f"Already agreed. {agreed.describe()}."

        # Their own words, and nothing else. What was inferred is not shown:
        # the point of inferring is not to spend their attention on it.
        # Nothing to fill in. Accept and Decline are the whole answer, and a
        # field on top of them is a second decision about the same thing —
        # somebody can accept the form while leaving a box unticked, which
        # means nothing.
        wanted = {"type": "object", "properties": {}}

        try:
            # The behaviours are already on their screen: the session printed
            # them when the contract was recorded. Repeating the whole list
            # inside the form makes a wall of text nobody reads twice, so this
            # points at what is above rather than restating it.
            answer = await context.session.elicit_form(
                message=(
                    f"Build {Path(here).name} as described above?\n\n"
                    "By accepting you agree those behaviours are what you "
                    "want built. They are fixed from here: a later change to "
                    "what the system does is a different project, not a "
                    "revision. Everything else — structure, libraries, how it "
                    "is put together — stays open."
                ),
                requestedSchema=wanted,
            )
            # Accepting the form is the agreement. There is nothing to read
            # out of it.
            said_yes = getattr(answer, "action", "") == "accept"
        except Exception as exc:  # noqa: BLE001 - a client need not support this
            logger.info("could not ask for agreement: %s", exc)
            _record("agree", here, _t.monotonic() - started, 0, asked=False)
            return (
                f"Could not show the form ({type(exc).__name__}).\n\n"
                "Show them what `contract --verify` prints and ask whether to "
                "build it. If they say yes, run "
                "`vesta contract --sign` and then `vesta drive --on`."
            )

        _record("agree", here, _t.monotonic() - started, 0, agreed=bool(said_yes))

        if not said_yes:
            return (
                "They have not agreed. Do not build. Ask what should be "
                "different, have the `vesta-spec` subagent rewrite it, and "
                "put it to them again — nothing is fixed until they accept."
            )

        await anyio.to_thread.run_sync(agreed_with.sign, here)
        from . import driving

        await anyio.to_thread.run_sync(driving.start, here)
        from .inject import _launcher

        return (
            "Agreed, and building. Behaviour is fixed from here: a request "
            "that would change what the system does is a different project.\n\n"
            "**As you finish each behaviour, record it.** Nothing else tells "
            "the contract it is done, and a behaviour it does not know about "
            "is one the loop keeps asking for:\n\n"
            f"  V={_launcher()}\n"
            '  $V contract --met "<the behaviour, word for word>" '
            '--node "file.py:function" --test "test_file.py:test_name"\n\n'
            "One call per behaviour. Copy the wording from the contract "
            "exactly — a near miss matches nothing.\n\n"
            "The session will not end while anything is outstanding — a "
            "behaviour unbuilt or unrecorded, a failing test, a defect. Those "
            "are counted, not judged. Work through them."
        )

    @server.tool()
    async def declare(rule: str, context: Context = None) -> str:
        """Record a standing rule the user has just stated.

        **Call this the moment a user states a constraint on the code**, in the
        course of ordinary work — "one .env for the whole of v3", "deps must be
        pinned", "never a bare except". Do not wait to be asked and do not
        interrupt to confirm: recording is cheap and reversible, and a user who
        must run a command to record a rule records nothing.

        What to record:
          - A constraint on the code, not on this turn. "one .env for v3"
            stands; "don't edit anything yet" expires with the turn.
          - Stated, not mused. "we should probably pin deps" invites an answer;
            "deps must be pinned" does not.
          - The user's words, not your conclusion. A rule you inferred from the
            code has nobody behind it, and Vesta already derives those.

        Safe to call again with the same words — it replaces rather than
        duplicates. Afterwards, tell the user in one line that it was recorded
        and carry on with what they asked for.

        Args:
            rule: The rule, in the user's own words.
        """
        import time as _t

        here = await project_of(context)
        if here is None:
            return "Could not tell which project this is."

        import anyio

        started = _t.monotonic()
        asked = await anyio.to_thread.run_sync(confirming.declare, here, rule)
        _record("declare", here, _t.monotonic() - started, len(rule))
        # One line. This is said back to a user who asked for something else,
        # in the middle of getting it — anything longer is an interruption.
        standing = sum(1 for v in asked.verdicts if v.binding)
        return (
            f"Recorded as a standing rule for {Path(here).name} "
            f"({standing} in all). `decided` reviews them."
        )

    @server.tool()
    async def defects(limit: int = 8, context: Context = None) -> str:
        """Things in this repository worth fixing, found without being asked.

        Structural defects — hardcoded lists that should be open, errors
        discarded silently, code nothing refers to, references no resolver can
        follow. Each finding says why it is a defect and every place it shows,
        so fixing the finding fixes all of them.

        Use before starting work in an unfamiliar area, or when asked to
        improve or clean something. Not a linter: these come from defects this
        project's own users have pointed at.

        Args:
            limit: How many findings to return.
        """
        project = await project_of(context)
        import anyio
        import time as _t

        started = _t.monotonic()
        answer = await anyio.to_thread.run_sync(_defects, project, limit)
        _record("defects", project, _t.monotonic() - started, len(answer))
        return answer

    @server.tool()
    async def decided(
        check: bool = True, limit: int = 8, context: Context = None
    ) -> str:
        """What this project's user has decided, and whether the code honours it.

        Rules recovered from corrections the user made in earlier sessions —
        naming conventions, structural constraints, things they asked for and
        did not get. You cannot verify these by reading code, because a
        correction leaves no trace in the artifact.

        Use BEFORE making a change, so the change does not break something the
        user already asked for once.

        Args:
            check: Also check the code against them and report the sites.
            limit: How many rules or findings to return.
        """
        project = await project_of(context)
        import anyio
        import time as _t

        started = _t.monotonic()
        answer = await anyio.to_thread.run_sync(_decided, project, check, limit)
        _record("decided", project, _t.monotonic() - started, len(answer))
        return answer

    return server


def main() -> int:
    """Start the server.

    Nothing is loaded from a `.env` here, and nothing should be: the sidecar
    holds no credentials. It once read one to find an API key, and that key is
    exactly what conformance removed — the judging moved to the host's own
    inference. The loader outlived the reason for it and, once its module was
    deleted, stopped the server from starting at all.
    """
    _quieten()
    try:
        server = build_server()
    except ImportError:
        print("the sidecar needs the mcp package: pip install 'vesta[sidecar]'")
        return 1
    server.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
