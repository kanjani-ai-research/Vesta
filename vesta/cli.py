"""Vesta from a terminal.

The same things the library does: build a graph of a codebase, ask what a
change touches, ask whether Vesta can answer here yet, report what the user has
decided and whether the code honours it, and report what is worth fixing.

**Nothing here judges.** Deciding whether a correction is a rule, or what a
definition is about, needs a model — and Vesta's model is the host's, reached
through a plugin agent rather than an API key the user has to hold. These
commands read what was decided and check what can be checked mechanically.

**Every command reports what it could not establish.** A propagation set over a
graph with holes, a rule nothing can check, a file the resolver could not read:
each is printed, because a result that looks complete and is not is the failure
mode this whole project is shaped against.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import List, Optional, Sequence

from .graph import build
from .propagate import from_files
from .home import _slug


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


def _used(args: argparse.Namespace) -> int:
    """What the sidecar was actually asked, and when.

    Exists so a measurement does not depend on somebody watching a terminal.
    """
    import json
    import time

    from .home import home

    log = home() / "used.jsonl"
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


def _rules(args: argparse.Namespace) -> int:
    """What this repository's user has decided, and whether the code honours it.

    Reachable because a survey found `enforce.against` referred to by nothing —
    an entry point nobody could call is a feature nobody has.

    Reads what has already been decided; it does not judge. Deciding whether a
    correction is a rule needs a model, and Vesta's models are the host's — the
    `vesta-rules` agent does that and writes the answer down, and this reports
    what it wrote. A CLI that judged would need a key the user should not need.
    """
    from .enforce import against
    from .held import graph_for
    from .rules import from_sessions

    where = Path(args.root).expanduser().resolve()
    found = from_sessions(where)
    _say(found.describe())

    if not args.check:
        for rule in found.standing[: args.show]:
            _say(f"  {rule.describe()[:110]}")
        if found.gaps:
            _say("")
            _say(f"{len(found.gaps)} rule(s) nothing can check yet:")
            for gap in found.gaps[:5]:
                _say(f"  {gap.describe()[:110]}")
        return 0

    verdict = against(found, graph_for(where), where)
    _say("")
    _say(verdict.describe())
    for finding in verdict.broken:
        _say("")
        _say(f"✗ {finding.rule[:100]}")
        _say(f"   you said: {finding.said[:90]}")
        for site in finding.sites[: args.show]:
            _say(f"      {site.describe()[:96]}")
    return 0


def _patterns(args: argparse.Namespace) -> int:
    """Things worth fixing, found without being asked."""
    from .held import graph_for
    from .patterns import survey

    where = Path(args.root).expanduser().resolve()
    found = survey(graph_for(where), where)
    _say(found.describe())

    for name, items in found.by_pattern().items():
        _say("")
        _say(f"{name} ({len(items)})")
        _say(f"  {items[0].why}")
        for entry in items[: args.show]:
            at = f"{entry.where}:{entry.line}" if entry.line else entry.where
            _say(f"    {at}  {entry.what[:70]}")
        if len(items) > args.show:
            _say(f"    … and {len(items) - args.show} more")
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="vesta",
        description="What a change touches, what the work is called, what you have decided.",
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

    status = sub.add_parser("status", help="whether vesta can help here yet")
    status.add_argument("root", nargs="?", default=".")
    status.add_argument("--prepare", action="store_true", help="start building if nothing is built")
    status.set_defaults(run=_status)

    rules = sub.add_parser("rules", help="what you have decided, and whether the code honours it")
    rules.add_argument("root", nargs="?", default=".")
    rules.add_argument("--check", action="store_true", help="check the code against them")
    rules.add_argument("--show", type=int, default=6)
    rules.set_defaults(run=_rules)

    patterns = sub.add_parser("patterns", help="things worth fixing, found unasked")
    patterns.add_argument("root", nargs="?", default=".")
    patterns.add_argument("--show", type=int, default=5)
    patterns.set_defaults(run=_patterns)

    used = sub.add_parser("used", help="what the sidecar was asked, and when")
    used.add_argument("--since", type=float, default=0, help="minutes to look back")
    used.add_argument("--each", type=int, default=0, help="show the last N calls")
    used.set_defaults(run=_used)

    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(name)s: %(message)s",
    )
    return int(args.run(args) or 0)


if __name__ == "__main__":
    raise SystemExit(main())
