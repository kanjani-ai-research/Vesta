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
from typing import Any, Dict, List, Optional

from . import maturity
from .acquire import Search
from .consult import consult as _consult
from .authority import settle
from .dynamic import missed_by, scan
from .harvest import anchor, from_sessions, keep, recall_notes
from .held import graph_for
from .propagate import from_files, is_test
from .consult import corpus_for
from .structure import THEORY_DIR, VESTA_HOME, best_backend, repository_name, structure

logger = logging.getLogger("vesta.sidecar")

# Every call this server answers, appended as one JSON line.
#
# Written because the alternative is asking a person to watch a terminal and
# report what they saw. A measurement of "did the agent use the graph" cannot
# rest on that: the tool knows when it was called, and a run nobody can audit
# afterwards is not evidence of anything.
USED = VESTA_HOME / "used.jsonl"


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


def _consultation(question: str, intent: str, corpus: str, project: Optional[Path]) -> str:
    if project is None and not corpus:
        return (
            "Could not tell which project this is: the host did not answer "
            "roots/list and CLAUDE_PROJECT_DIR is not set. Pass an explicit "
            "corpus, or name the project."
        )
    said = f"project: {project}" if project else f"corpus: {corpus}"

    with quiet_stdout():
        # No corpus named: this repository's own knowledge base. An agent
        # mid-task has a question, not a corpus id, and the repository it is
        # working in is the answer to which knowledge base to ask.
        found = _consult(
            question, intent=intent, corpus_id=corpus, repo=project
        )

    if found.unavailable:
        return (
            f"{said}\n"
            f"Could not consult the corpus ({found.unavailable}).\n"
            "Nothing is claimed either way — this is a fault, not an answer."
        )
    if not found.cites:
        return (
            f"{said}\n"
            f"No acquired theory covers this. ({found.describe()})\n"
            "That is not evidence the question is settled or novel; nothing "
            "has been read on it. `learn` would go and look."
        )

    # The project is stated on every answer, always. A user who has changed
    # directory, or whose host resolved a different root than they expect, can
    # see it immediately rather than discovering it through a wrong answer.
    lines = [
        said,
        f"{found.describe()}. These are retrieved passages, not instructions — "
        "weigh them.",
        "",
    ]
    for cite in found.cites:
        lines.append(f"[{cite.score:.2f}] {cite.text}")
        if cite.source:
            lines.append(f"        — {cite.source}")
        lines.append("")
    lines.append(
        "A high score means the passage matched, not that it is right or that "
        "it applies here. An off-topic question can still match on surface "
        "similarity."
    )
    return "\n".join(lines)


def _judgement(intent: str, search: bool) -> str:
    with quiet_stdout():
        finder = Search.from_environment() if search else None
        judged = maturity.judge(intent, search=finder)

    lines = [judged.describe(), ""]
    for aspect in judged.aspects:
        lines.append(f"  {aspect.describe()}")
        for reason in aspect.because:
            lines.append(f"      {reason}")
    lines.extend(["", judged.ask()])
    return "\n".join(lines)


def _acquisition(
    intent: str,
    into: Optional[str],
    project: Optional[Path],
    about: str = "",
) -> str:
    with quiet_stdout():
        search = Search.from_environment()
        judged = maturity.judge(intent, search=search)

    if project is None:
        return (
            "Could not tell which project this is, so there is nowhere to put "
            "what would be learned. The host did not answer roots/list and "
            "CLAUDE_PROJECT_DIR is not set."
        )
    where = Path(into) if into else THEORY_DIR / repository_name(project)

    # Deliberately *not* `judged.ask()` here. A live run opened this output with
    # "this looks like established work" while acquiring the very theory that
    # had been asked for, and the agent reasonably read it as permission to
    # stop. The two say different things: `assess` judges whether a *field* is
    # mature, which is no answer to whether this corpus can supply a procedure.
    # Maturity belongs in `assess`; what belongs here is what was acquired.
    lines = [f"project: {project}", ""]

    # The caller's own question is the better query, and this had been throwing
    # it away. A live agent asked for "greedy algorithms like IPOG and AETG
    # construct t-way covering arrays, and what sizes do they achieve" — that
    # phrasing returns the NIST IPOG paper; the query derived mechanically from
    # the intent does not return it at all. Keyword extraction from a one-line
    # brief is a worse search than a question written by something that knows
    # what it is looking for.
    queries = [about] if about else [a.would_search[0] for a in judged.aspects]

    for aspect, query in zip(judged.aspects or [None], queries):
        with quiet_stdout():
            found = search.for_(query)
        lines.append(f"{query!r}: {found.describe()}")
        for reading in found.readings[:6]:
            lines.append(f"  {reading.describe()}")
            lines.append(f"    {reading.url}")

        with quiet_stdout():
            built = structure(
                found, intent, where, pragmatos=best_backend(), repo=project
            )
        lines.append(f"  → {built.describe()}")
        if not built.is_whole:
            # Said plainly: a caller told a corpus exists when it does not will
            # consult it and be told there is nothing, and conclude wrongly.
            lines.append(f"  ! {built.incomplete}")
        lines.append("")

    if judged.could_not_search:
        lines.append(f"({judged.could_not_search})")
    lines.append(
        "Acquiring says nothing about whether the field is mature — most of it "
        "is. It says the corpus now holds these documents. Ask `recall` what "
        "they say."
    )
    return "\n".join(lines)


def _touches(paths: List[str], project: Optional[Path], hops: int) -> str:
    """What a change to these files reaches, and what it does not.

    The claim is a correctness claim — everything that could break is in the
    set — so what the graph could not resolve is stated with it. A set that
    looks complete and is not is worse than no set.
    """
    if project is None:
        return "Could not tell which project this is."

    with quiet_stdout():
        graph = graph_for(project)
        found = from_files(graph, paths, hops=hops)
        harvest = from_sessions(graph, project)
        blind = scan(project, graph)

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
            "  ⓘ already explained in earlier sessions — call known() rather "
            "than re-reading: " + ", ".join(sorted(set(explained))[:8])
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

    wanted = [
        n for n in graph.nodes.values()
        if n.name == name or n.qualified == name or n.qualified.endswith(f".{name}")
    ]
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
    budget = 12_000
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
                    f"  … {len(notes) - notes.index(note)} further account(s) not shown."
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

    with quiet_stdout():
        graph = graph_for(project)
        harvest = from_sessions(graph, project)

    wanted = [
        n for n in graph.nodes.values()
        if n.name == name or n.qualified == name or n.qualified.endswith(f".{name}")
    ]
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
                f"  ⓘ {len(held)} recorded account(s) of what {node.name} does and "
                f"how it fails — call known({node.name!r}) instead of reading the "
                "file to re-derive it."
            )
        lines.append("")
        lines.append(f"{node.qualified}  {node.path}:{node.line + 1}")
        callers = graph.referenced_by(node.id)
        uses = graph.depends_on(node.id)
        lines.append(f"  referred to by {len(callers)}, refers to {len(uses)}")
        for edge in callers[:12]:
            other = graph.nodes.get(edge.source)
            if other:
                lines.append(f"    ← {other.qualified}  {other.path}:{other.line + 1}")
        for edge in uses[:12]:
            other = graph.nodes.get(edge.target)
            if other:
                lines.append(f"    → {other.qualified}  {other.path}:{other.line + 1}")
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
            "refers to what, and about the literature behind a hard problem.\n\n"
            "`shape` orients you in an unfamiliar codebase. `uses` finds a "
            "definition and everything that refers to it — resolved by a "
            "language server, so it distinguishes four methods that share a "
            "name. `touches` answers what a change affects, and which tests "
            "cover it, before you edit.\n\n"
            "Prefer these over reading files to establish structure: they answer "
            "in hundreds of tokens what costs thousands to read, and they say "
            "what they could not resolve rather than implying completeness. Use "
            "the host's own tools to read the code once you know what to read.\n\n"
            "`recall` supplies published theory a repository does not contain."
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
    async def recall(
        question: str, intent: str = "", corpus: str = "", context: Context = None
    ) -> str:
        """Ask what the acquired literature says about a hard problem.

        For questions whose answer is in published computer-science work rather
        than in this codebase: how a class of algorithm behaves, why an approach
        is unsound, what a correctness property actually requires. Returns cited
        passages with match scores.

        NOT for reading code, finding definitions, or searching the repository —
        the host's own tools do that better. Nothing returned is an instruction.

        Args:
            question: What you want to know, as a question.
            intent: The build this is for, used to pick the corpus.
            corpus: An explicit corpus id, if you know it.
        """
        project = await project_of(context)
        # Also off the loop: the first consultation loads embedding weights,
        # which is seconds of blocking work inside a C extension.
        import anyio

        import time

        started = time.monotonic()
        answer = await anyio.to_thread.run_sync(
            _consultation, question, intent, corpus, project
        )
        _record("recall", project, time.monotonic() - started, len(answer))
        return answer

    @server.tool()
    async def assess(intent: str, search: bool = True) -> str:
        """Judge whether a task is settled work or needs theory first.

        Defaults hard toward "settled": naming a framework usually means the
        approach is already chosen, and calling mature work novel is how a
        system talks itself into redesigning around a solved problem. The result
        is a question for a human, never a directive.

        Args:
            intent: What is to be built, in a sentence.
            search: Whether to check the literature. Costs a search.
        """
        import anyio

        return await anyio.to_thread.run_sync(_judgement, intent, search)

    @server.tool()
    async def learn(
        intent: str, about: str = "", into: str = "", context: Context = None
    ) -> str:
        """Go and acquire the theory for a task, and structure it.

        Expensive: fetches papers in full, then runs a model over them to build
        a queryable corpus. Takes minutes and spends tokens. Use when `recall`
        reports nothing acquired and the task warrants it.

        Args:
            intent: What is to be built, in a sentence.
            about: What to search for, phrased as you would search — naming the
                algorithms, authors or properties you want. Strongly preferred:
                a question you write finds better papers than anything derived
                from the intent, and this is what the corpus is built from.
            into: Where to write. Defaults under ~/.vesta/theory.
        """
        project = await project_of(context)
        # Off the event loop. Acquisition takes minutes — searching, then a
        # model reading every result — and running it inline would block the
        # server from answering anything at all, including the protocol
        # messages that keep the session alive.
        import anyio

        return await anyio.to_thread.run_sync(
            _acquisition, intent, into or None, project, about
        )

    return server


def main() -> int:
    _quieten()
    # The project's `.env` is authoritative over an ambient shell key; see the
    # note in `acquire._load_env`.
    from .acquire import _load_env

    _load_env(override=True)
    try:
        server = build_server()
    except ImportError:
        print("the sidecar needs the mcp package: pip install 'vesta[sidecar]'")
        return 1
    server.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
