"""Vesta from a terminal.

Four things, matching the four things the library does: build a graph of a
codebase, ask what a change touches, ask whether a brief needs theory, and go
and get that theory.

**Every command reports what it could not establish.** A propagation set over a
graph with holes, a judgement made without a web search, a corpus built from two
sources of three: each is printed, because a result that looks complete and is
not is the failure mode this whole project is shaped against.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import List, Optional, Sequence

from . import maturity
from .acquire import Search, _load_env
from .consult import known
from .graph import build
from .propagate import from_files
from .structure import THEORY_DIR, Pragmatos, _slug, best_backend, structure


def _say(text: str = "") -> None:
    print(text, file=sys.stdout)


def _graph(args: argparse.Namespace) -> int:
    seen = {"n": 0}

    def progress(done: int, total: int) -> None:
        seen["n"] = done
        print(f"\r  {done}/{total} definitions", end="", file=sys.stderr)

    graph = build(args.root, on_progress=None if args.quiet else progress)
    if not args.quiet and seen["n"]:
        print("", file=sys.stderr)

    _say(graph.describe())
    if graph.coverage:
        _say(f"  {graph.coverage.describe()}")
    for hole in graph.holes[:10]:
        _say(f"  hole: {hole.describe()}")
    if len(graph.holes) > 10:
        _say(f"  … and {len(graph.holes) - 10} more hole(s)")
    return 0


def _touches(args: argparse.Namespace) -> int:
    graph = build(args.root)
    found = from_files(graph, args.paths, hops=args.hops)

    _say(found.describe(graph))
    for entry in sorted(found.reached, key=lambda r: r.hops):
        _say(f"  {entry.describe(graph)}")

    tests = found.tests(graph)
    if tests:
        _say("")
        _say("Tests to run:")
        for path in sorted(tests):
            _say(f"  {path}")
    if not found.is_bounded:
        # The claim is "everything that could break is in this set". A hole is
        # exactly where that claim stops holding, so it is said out loud.
        _say("")
        _say(
            f"{len(found.unresolved)} file(s) could not be resolved — "
            "the set may be short."
        )
    return 0


def _judge(args: argparse.Namespace) -> int:
    search = Search.from_environment() if args.search else None
    judged = maturity.judge(args.intent, search=search)

    _say(judged.describe())
    for aspect in judged.aspects:
        _say(f"  {aspect.describe()}")
        for reason in aspect.because:
            _say(f"      {reason}")
    _say("")
    _say(judged.ask())
    return 0


def _learn(args: argparse.Namespace) -> int:
    search = Search.from_environment()
    judged = maturity.judge(args.intent, search=search)

    _say(judged.ask())
    _say("")

    # Every aspect is kept, not only the ones judged to need theory.
    #
    # The classifier's verdict is about whether a *field* is settled; it says
    # nothing about whether the user has read it. Judging "derive ontology
    # axioms ... conservative extensions" as established work is correct — and
    # the search behind that verdict returned the conservativity survey that is
    # exactly what someone building it should read. Withholding the readings
    # because the field turned out to be mature would discard the useful half
    # of the result and keep the half that is only a label.
    aspects = judged.aspects if not args.only_novel else judged.needs_theory
    if not aspects:
        _say("Nothing to look up.")
        return 0

    # Absolute by default. A relative default wrote readings into whatever
    # directory the command happened to be run from — `/tmp/theory` on a cold
    # start — while the corpus was built under the home directory, so the two
    # halves of one run landed in different places and the corpus came out
    # empty. Acquired theory is about a subject, not about a working directory.
    into = Path(args.into).expanduser() if args.into else THEORY_DIR
    for aspect in aspects:
        query = aspect.would_search[0]
        found = search.for_(query)
        _say(f"{aspect.name}: {found.describe()} for {query!r}")
        for reading in found.readings[: args.show]:
            _say(f"    {reading.describe()}")
            _say(f"      {reading.url}")

        if args.structure:
            built = structure(
                found,
                f"{args.intent} {aspect.name}",
                into / _slug(aspect.name),
                # The library where it is importable, the service otherwise:
                # a corpus is a file, and requiring a running process to write
                # one would be a dependency the data does not have.
                pragmatos=(
                    Pragmatos(args.pragmatos)
                    if args.pragmatos_url_given
                    else best_backend()
                ),
                ontology=args.ontology,
            )
            _say(f"    → {built.describe()}")
        else:
            from .structure import write

            written = write(found, into / _slug(aspect.name), query=query)
            _say(f"    → {len(written)} file(s) in {into / _slug(aspect.name)}")
        _say("")

    if judged.could_not_search:
        _say(f"({judged.could_not_search})")
    return 0


def _knows(args: argparse.Namespace) -> int:
    """What the acquired theory already says, before anything is searched."""
    for found in known(args.questions, intent=args.intent, corpus_id=args.corpus):
        _say(f"{found.question}")
        _say(f"  {found.describe()}")
        for cite in found.cites[: args.show]:
            _say(f"    {cite.score:.2f}  {cite.text[:160]}")
        if not found.knew and not found.unavailable:
            # Nothing held is a result: it is the signal to go and acquire.
            _say("    (nothing acquired covers this — `vesta learn` would look)")
        _say("")
    return 0


def _used(args: argparse.Namespace) -> int:
    """What the sidecar was actually asked, and when.

    Exists so a measurement does not depend on somebody watching a terminal.
    """
    import json
    import time

    from .structure import VESTA_HOME

    log = VESTA_HOME / "used.jsonl"
    if not log.is_file():
        _say("The sidecar has not been called yet.")
        return 0

    calls = []
    for line in log.read_text(encoding="utf-8").splitlines():
        try:
            calls.append(json.loads(line))
        except ValueError:
            continue

    if args.since:
        cutoff = time.time() - args.since * 60
        calls = [c for c in calls if c.get("at", 0) >= cutoff]

    if not calls:
        _say("Nothing in that window.")
        return 0

    counts: dict = {}
    chars = 0
    for call in calls:
        counts[call["tool"]] = counts.get(call["tool"], 0) + 1
        chars += call.get("answer_chars", 0)

    _say(f"{len(calls)} call(s)")
    for tool, count in sorted(counts.items(), key=lambda kv: -kv[1]):
        _say(f"  {count:3}  {tool}")
    _say("")
    _say(f"{chars:,} characters returned (~{chars // 4:,} tokens)")
    if args.each:
        _say("")
        for call in calls[-args.each:]:
            when = time.strftime("%H:%M:%S", time.localtime(call.get("at", 0)))
            _say(f"  {when}  {call['tool']:8} {call.get('took', 0):5.1f}s  "
                 f"{call.get('answer_chars', 0):6,} chars")
    return 0


def _status(args: argparse.Namespace) -> int:
    """Whether vesta can contribute here yet, and what it holds.

    Exists so a user who sees nothing happening can find out why, rather than
    concluding the tool is broken.
    """
    from .harvest import from_sessions
    from .held import graph_for
    from .ready import prepare, readiness

    where = Path(args.root).expanduser().resolve()
    state = readiness(where)
    _say(f"{where}")
    _say(f"  {state.describe()}")

    if state.can_answer and state.definitions:
        graph = graph_for(where, trust_for=300)
        harvest = from_sessions(graph, where)
        _say(f"  {graph.describe()}")
        _say(f"  {harvest.describe()}")
        if graph.holes:
            _say(f"  {len(graph.holes)} file(s) the resolver could not read")
    elif state.state == "failed":
        # Say what to do about it. A user told only that something failed has
        # to guess whether it is theirs to fix.
        _say("")
        if "language server" in state.why or "server" in state.why.lower():
            _say("  No resolver for this project's languages. `vesta graph .`")
            _say("  reports which files could not be read and why.")
        _say("  Fix the cause and run `vesta status --prepare` to try again;")
        _say("  it will also retry on its own after a while.")
        if args.prepare:
            from .ready import _mark

            try:
                _mark(where).unlink()
            except OSError:
                pass
            prepare(where)
            _say("  retrying now, in the background")
    elif not state.can_answer:
        if args.prepare:
            prepare(where)
            _say("  preparation started; it runs in the background")
        else:
            _say("  run `vesta status --prepare` to start building")
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="vesta",
        description="What a change touches, and what theory a build needs.",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    graph = sub.add_parser("graph", help="resolve a tree into a graph")
    graph.add_argument("root", nargs="?", default=".")
    graph.add_argument("-q", "--quiet", action="store_true")
    graph.set_defaults(run=_graph)

    touches = sub.add_parser("touches", help="what a change to these files affects")
    touches.add_argument("paths", nargs="+")
    touches.add_argument("--root", default=".")
    touches.add_argument("--hops", type=int, default=3)
    touches.set_defaults(run=_touches)

    judge = sub.add_parser("judge", help="whether a brief needs theory")
    judge.add_argument("intent")
    judge.add_argument(
        "--no-search",
        dest="search",
        action="store_false",
        help="judge without looking anything up",
    )
    judge.set_defaults(run=_judge)

    learn = sub.add_parser("learn", help="acquire the theory a brief needs")
    learn.add_argument("intent")
    learn.add_argument(
        "--into",
        default="",
        help="where to write readings (default: ~/.vesta/theory)",
    )
    learn.add_argument("--show", type=int, default=5)
    learn.add_argument(
        "--only-novel",
        action="store_true",
        help="acquire only for aspects judged to need theory (settled fields "
        "still have literature worth reading, so this is off by default)",
    )
    learn.add_argument(
        "--structure",
        action="store_true",
        help="build a Pragmatos corpus over what was found",
    )
    learn.add_argument(
        "--pragmatos",
        default="http://localhost:8000",
        help="build through a running service instead of the library",
    )
    learn.add_argument("--ontology", default=None)
    learn.set_defaults(run=_learn)

    knows = sub.add_parser("knows", help="what acquired theory already says")
    knows.add_argument("questions", nargs="+")
    knows.add_argument("--intent", default="", help="the intent its corpus was built for")
    knows.add_argument("--corpus", default="", help="an explicit corpus id")
    knows.add_argument("--show", type=int, default=3)
    knows.set_defaults(run=_knows)

    # The project's own `.env` wins over whatever the shell happens to carry.
    # A stale ANTHROPIC_API_KEY exported months ago in another project shadows
    # the configured one under plain `setdefault`, and the failure surfaces as
    # "API key is invalid" about a key the user never chose to use.
    _load_env(override=True)

    status = sub.add_parser("status", help="whether vesta can help here yet")
    status.add_argument("root", nargs="?", default=".")
    status.add_argument("--prepare", action="store_true", help="start building if nothing is built")
    status.set_defaults(run=_status)

    used = sub.add_parser("used", help="what the sidecar was asked, and when")
    used.add_argument("--since", type=float, default=0, help="minutes to look back")
    used.add_argument("--each", type=int, default=0, help="show the last N calls")
    used.set_defaults(run=_used)

    args = parser.parse_args(argv)
    # Whether the user actually asked for the service, rather than inheriting
    # the default and getting HTTP they never chose.
    args.pragmatos_url_given = any(a.startswith("--pragmatos") for a in (argv or sys.argv[1:]))
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(name)s: %(message)s",
    )
    return int(args.run(args) or 0)


if __name__ == "__main__":
    raise SystemExit(main())
