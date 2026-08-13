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
    from . import confirm
    from .enforce import against
    from .held import graph_for
    from .rules import from_sessions

    where = Path(args.root).expanduser().resolve()
    # What the user themselves said about these, applied over what was
    # recovered — including rules they declared outright, which appear in no
    # transcript and so cannot be recovered at all.
    found = confirm.apply(from_sessions(where), where)
    _say(found.describe())

    asked = confirm.recall(where)
    if asked.waiting:
        _say(f"  {len(asked.waiting)} candidate(s) waiting on you — `vesta learn`")

    # What was recorded recently, and how it arrived. A rule an agent captured
    # on somebody's behalf is the one kind nobody explicitly confirmed, so it
    # is the one worth being able to see the same day.
    import time as _time

    lately = asked.lately(_time.time() - 86400)
    if lately:
        _say("")
        _say(f"recorded in the last day ({len(lately)}):")
        for verdict in lately[:6]:
            _say(f"  {verdict.describe()[:100]}")
        _say("")
        _say("  Wrong about one? `vesta learn <handle> lapsed`")

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
            _say(f"    {entry.describe()[:96]}")
        if len(items) > args.show:
            _say(f"    … and {len(items) - args.show} more")
    return 0


def _asked(args: argparse.Namespace) -> int:
    """The questions the sidecar answers, asked from a terminal.

    The same functions the MCP tools call, not a second implementation of them.
    A slash command runs this, so anything answerable in a session must be
    answerable here or the two surfaces drift — and the one a user typed is the
    one they will believe.
    """
    from . import sidecar

    where = Path(args.root).expanduser().resolve()
    answering = {
        "does": lambda: sidecar._does(args.phrase, where),
        "uses": lambda: sidecar._uses(args.name, where),
        "means": lambda: sidecar._means(args.name, where),
        "shape": lambda: sidecar._shape(where),
        "known": lambda: sidecar._known(args.name, where),
        "bears": lambda: sidecar._bears_on(args.paths, where)
        or "No rule you have set is in doubt for these files.",
        "elsewhere": lambda: sidecar._elsewhere(
            " ".join(args.phrase) if isinstance(args.phrase, list) else args.phrase,
            args.project,
            where,
        ),
        "projects": lambda: sidecar._projects(where),
    }
    with sidecar.quiet_stdout():
        answer = answering[args.command]()
    _say(answer)
    return 0


def _learn(args: argparse.Namespace) -> int:
    """Confirm which recovered corrections are standing rules.

    **Nobody adjudicates by pasting a sentence.** Asking a user to select a
    line out of a terminal, quote it correctly, and get it byte-identical is
    asking them not to bother. So every candidate carries a short handle and
    `vesta learn 5279 rule` is the whole interaction — positional, in the order
    somebody says it out loud.

    A terminal can only ask one thing at a time and cannot render a form, so
    this lists what is waiting and takes one verdict per invocation. In a
    session the `learn` tool asks directly. Same store, two doors.
    """
    from . import confirm
    from .rules import from_sessions

    where = Path(args.root).expanduser().resolve()

    # `vesta learn <handle> <verdict>`, which is how somebody would say it.
    if args.which:
        from .rules import from_sessions as _recovered

        text = confirm.find(where, args.which, _recovered(where))
        if args.verdict == "reopen":
            confirm.reopen(where, text)
            _say(f"back in question: {text[:70]}")
            return 0
        confirm.record(where, text, args.verdict, args.stated or "")
        _say(f"{args.verdict}: {text[:70]}")
        _say(confirm.recall(where).describe())
        return 0

    if args.declare:
        confirm.declare(where, args.declare)
        _say(f"declared: {args.declare}")
        _say(confirm.recall(where).describe())
        return 0

    if args.reopen:
        confirm.reopen(where, args.reopen)
        _say("put back into question; `vesta learn` will ask about it again")
        return 0

    if args.text:
        confirm.record(where, args.text, args.verdict, args.stated or "")
        _say(confirm.recall(where).describe())
        return 0

    found = from_sessions(where)
    waiting = confirm.worth_asking(found, where, limit=args.show)
    asked = confirm.recall(where)
    _say(asked.describe())

    # What the user saw and did not settle. Reported before anything new,
    # because a question already put to somebody is owed an answer before
    # another one is asked.
    if asked.waiting:
        _say("")
        _say(f"{len(asked.waiting)} waiting on you:")
        for verdict in asked.waiting[: args.show]:
            _say(f"  {confirm.handle(verdict.text)}  {verdict.text[:92]}")
        if len(asked.waiting) > args.show:
            _say(f"  … and {len(asked.waiting) - args.show} more")
        _say("")
        # What it costs to leave them. A list of chores nobody has a reason to
        # finish does not get finished; the reason is that these are the rules
        # agents are not being held to.
        _say(
            f"Until these are settled, {len(asked.waiting)} constraint(s) you "
            "stated are not enforced —"
        )
        _say("agents working here will not be held to them.")
        _say("")
        _say("  vesta learn --text '<the candidate>' --verdict rule|note|lapsed")

    if not waiting:
        if not asked.waiting:
            _say("Nothing new to confirm.")
        _say("")
        _say("A rule nobody ever had to correct leaves no trace to recover:")
        _say("  vesta learn --declare '<the rule, in your own words>'")
        return 0

    _say("")
    _say(f"{len(waiting)} candidate(s) worth settling:")
    for rule in waiting:
        _say("")
        _say(f"  {confirm.handle(rule.text)}  {rule.text[:140]}")
    _say("")
    _say("Say which each is, by its handle:")
    _say(f"  vesta learn {confirm.handle(waiting[0].text)} rule     binding here")
    _say(f"  vesta learn {confirm.handle(waiting[0].text)} note     said once, about one place")
    _say(f"  vesta learn {confirm.handle(waiting[0].text)} lapsed   was a rule, is not now")
    _say("")
    _say("In a session, /vesta:learn asks you directly instead.")
    _say("A rule Vesta never saw: vesta learn --declare '<the rule>'")
    return 0


def _contract(args: argparse.Namespace) -> int:
    """Write, show, or sign what was agreed to be built.

    The seam the `vesta-spec` agent calls. It decides what the behaviours are —
    that is judgement, on the host's inference — and this writes them down.
    """
    from . import contract as agreed_with

    where = Path(args.root).expanduser().resolve()

    if args.verify:
        agreed = agreed_with.recall(where)
        if agreed is None:
            _say("Nothing has been agreed for this project yet.")
            return 1
        _say(agreed.to_verify())
        return 0

    if args.sign:
        agreed = agreed_with.sign(where)
        if agreed is None:
            # Say what went wrong rather than only that something did. The
            # usual cause is a spec agent that produced a contract in chat and
            # never recorded it — the user then agrees to something that does
            # not exist, and nothing explains why.
            _say("Nothing has been agreed for this project yet.")
            _say("")
            _say(f"No contract has been recorded in {where}.")
            _say("If a list of behaviours was shown but never written down,")
            _say("the spec agent could not reach Vesta. Run it again and check")
            _say("it reports what it recorded rather than only printing it.")
            return 1
        _say("Agreed. Behaviour is fixed from here; a change to it after this")
        _say("is a different project.")
        _say(f"  {agreed.describe()}")
        return 0

    if args.note:
        agreed = agreed_with.note(where, args.note)
        if agreed is None:
            _say("There is no contract to note against.")
            return 1
        _say("Sure.")
        return 0

    if args.defer:
        agreed = agreed_with.defer(where, args.defer)
        if agreed is None:
            _say("There is no contract to defer against.")
            return 1
        _say(f"Kept for after delivery: {args.defer[:70]}")
        return 0

    if args.met:
        agreed = agreed_with.met(
            where, args.met, nodes=args.node or None, tests=args.test or None
        )
        if agreed is None:
            _say("There is no contract.")
            return 1
        _say(agreed.describe())
        return 0

    if args.does or args.goal:
        agreed = agreed_with.Contract(
            goal=args.goal,
            behaviours=[agreed_with.Behaviour(does=d) for d in args.does],
            constraints=list(args.constraint),
            inferred=list(args.inferred),
            noted=list(args.note_said),
        )
        agreed_with.keep(agreed, where)
        _say(agreed.to_verify())
        _say("")
        _say("Nothing is agreed until `vesta contract --sign`.")
        return 0

    agreed = agreed_with.recall(where)
    if agreed is None:
        _say("Nothing has been agreed for this project yet.")
        return 1
    _say(agreed.describe())
    for behaviour in agreed.behaviours:
        _say(f"  {behaviour.describe()}")
    return 0


def _drive(args: argparse.Namespace) -> int:
    """Turn driving on or off, or say what is outstanding.

    Nothing here writes code. It says whether the work is done — against the
    contract and the measurements, never against anybody's opinion of it.
    """
    from . import driving

    where = Path(args.root).expanduser().resolve()

    if args.off:
        _say(driving.stop(where).describe())
        return 0

    if args.on:
        driving.start(where)
        _say(f"Driving {where.name}. It will run until:")
        _say("  every agreed behaviour is built and reached by a test")
        _say("  the tests pass")
        _say("  the rules you set are honoured")
        _say("  nothing is outstanding that can be counted")
        _say("")
        _say("`vesta drive --off` stops it.")
        return 0

    verdict = driving.iterate(where) if args.step else driving.look(where)
    _say(driving.state(where).describe())
    _say("")
    _say(verdict.describe())
    for outstanding in verdict.outstanding[: args.show]:
        _say(f"  · {outstanding}")
    if len(verdict.outstanding) > args.show:
        _say(f"  … and {len(verdict.outstanding) - args.show} more")
    return 0


def _guide(args: argparse.Namespace) -> int:
    """What Vesta is and what a user can do with it.

    Printed from a file rather than produced by a model: a user asking what a
    tool does should not have to wait for inference, or pay for it, or wonder
    whether the answer was made up.
    """
    from .guide import guide

    _say(guide(args.topic))
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

    # Named for what a user asks, and matching the tool a session sees. Two
    # names for one answer is how a user comes to believe there are two.
    rules = sub.add_parser("decided", help="what you have decided, and whether the code honours it")
    rules.add_argument("root", nargs="?", default=".")
    rules.add_argument("--check", action="store_true", help="check the code against them")
    rules.add_argument("--show", type=int, default=6)
    rules.set_defaults(run=_rules)

    patterns = sub.add_parser("defects", help="things worth fixing, found unasked")
    patterns.add_argument("root", nargs="?", default=".")
    patterns.add_argument("--show", type=int, default=5)
    patterns.set_defaults(run=_patterns)

    # The questions a session can ask, askable from a terminal. Same functions.
    does = sub.add_parser("does", help="where a kind of work is done here")
    does.add_argument("phrase", help="the work, in ordinary words")
    does.add_argument("--root", default=".")
    does.set_defaults(run=_asked)

    uses = sub.add_parser("uses", help="where a definition is and what refers to it")
    uses.add_argument("name")
    uses.add_argument("--root", default=".")
    uses.set_defaults(run=_asked)

    means = sub.add_parser("means", help="what a definition is for")
    means.add_argument("name")
    means.add_argument("--root", default=".")
    means.set_defaults(run=_asked)

    known = sub.add_parser("known", help="what has already been worked out about it")
    known.add_argument("name")
    known.add_argument("--root", default=".")
    known.set_defaults(run=_asked)

    shape = sub.add_parser("shape", help="what this repository is made of")
    shape.add_argument("--root", default=".")
    shape.set_defaults(run=_asked)

    elsewhere = sub.add_parser("elsewhere", help="where work is done in another project")
    # The project is a flag rather than a positional: a user types the work in
    # ordinary words, which contain spaces, and a shell splits them. `elsewhere
    # fuzzy search indexer` must not be read as a phrase of one word.
    elsewhere.add_argument("phrase", nargs="+", help="the work, in ordinary words")
    elsewhere.add_argument("--in", dest="project", required=True, help="by name or by path")
    elsewhere.add_argument("--root", default=".")
    elsewhere.set_defaults(run=_asked)

    projects = sub.add_parser("projects", help="what can be referred to")
    projects.add_argument("--root", default=".")
    projects.set_defaults(run=_asked)

    learn = sub.add_parser("learn", help="confirm which corrections are rules")
    # Positional, in the order somebody would say it: which one, and what it is.
    learn.add_argument("which", nargs="?", default="", help="a candidate's handle")
    learn.add_argument(
        "verdict",
        nargs="?",
        default="rule",
        choices=("rule", "note", "lapsed", "abstained", "reopen"),
        help="what it is",
    )
    learn.add_argument("--root", default=".")
    learn.add_argument("--show", type=int, default=5)
    learn.add_argument("--text", default="", help="the candidate, spelled out")
    learn.add_argument("--stated", default="", help="the rule, said cleanly")
    learn.add_argument(
        "--declare", default="", help="a rule nothing recovered, stated outright"
    )
    learn.add_argument(
        "--reopen", default="", help="put a settled candidate back into question"
    )
    learn.set_defaults(run=_learn)

    bears = sub.add_parser(
        "bears", help="whether a rule you set is in doubt for these files"
    )
    bears.add_argument("paths", nargs="+")
    bears.add_argument("--root", default=".")
    bears.set_defaults(run=_asked)

    contract = sub.add_parser(
        "contract", help="what was agreed to be built, and whether it has been"
    )
    contract.add_argument("--root", default=".")
    contract.add_argument("--goal", default="", help="what is being built, in one line")
    contract.add_argument("--does", action="append", default=[], help="a behaviour")
    contract.add_argument(
        "--constraint", action="append", default=[], help="how it must be built"
    )
    contract.add_argument(
        "--inferred", action="append", default=[], help="what was chosen unasked"
    )
    contract.add_argument("--verify", action="store_true", help="what to show the user")
    contract.add_argument("--sign", action="store_true", help="record their agreement")
    contract.add_argument("--met", default="", help="a behaviour now built")
    contract.add_argument("--node", action="append", default=[], help="what implements it")
    contract.add_argument("--test", action="append", default=[], help="what checks it")
    contract.add_argument("--defer", default="", help="a change to have after delivery")
    contract.add_argument("--note", default="", help="something said that has no effect")
    contract.add_argument(
        "--noted", dest="note_said", action="append", default=[],
        help="something said at elicitation that has no effect",
    )
    contract.set_defaults(run=_contract)

    drive = sub.add_parser(
        "drive", help="run until the agreed work is done, and know when that is"
    )
    drive.add_argument("--root", default=".")
    drive.add_argument("--on", action="store_true", help="turn driving on here")
    drive.add_argument("--off", action="store_true", help="turn it off")
    drive.add_argument("--step", action="store_true", help="record one iteration")
    drive.add_argument("--show", type=int, default=6)
    drive.set_defaults(run=_drive)

    guide = sub.add_parser("guide", help="what vesta is, and what you can do")
    guide.add_argument("topic", nargs="?", default="")
    guide.set_defaults(run=_guide)

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
