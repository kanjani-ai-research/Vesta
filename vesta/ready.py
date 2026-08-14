"""Being useful when there is something to say, and silent otherwise.

Vesta has to survive three situations and it must behave the same way in all of
them: a brand new project with nothing in it, a mature project seen for the
first time, and a mature project somebody has been working in for months before
Vesta arrived.

**The rule is that a prompt never waits.** Building a graph takes eight to
twelve seconds on an ordinary repository — measured, not estimated — and a
hook that spends that on the user's first message has made the session worse
for everyone whether or not it eventually helps. So nothing is built on the way
in. What exists is used, what does not exist is *started*, and the answer is
whatever can be given immediately, which is often nothing.

**Nothing is the correct answer more often than not.** A new project has no
structure to describe and no history to recall. Saying so by staying quiet is
better than saying so at length, and much better than making the user wait to
be told.

**Preparation is visible but never blocking.** A caller can ask whether Vesta is
ready and get a straight answer, so a user who wonders why nothing is happening
can find out, rather than concluding the tool is broken.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, Optional

from pydantic import BaseModel

from .home import home

logger = logging.getLogger("vesta.ready")

# Where a preparation records that it is running or has finished.
#
# A function, not a constant. Bound at import this was evaluated before any
# test fixture could move the store, so every test that recorded a failure
# wrote it into the user's real `~/.vesta/prepared` — fifty stale marks saying
# "boom" and "pyright is not installed" were found there, left by the suite.
# `GRAPH_DIR` had already been fixed for exactly this and the same reasoning
# applies: a location that can move must be read, not remembered.
def STATE() -> Path:
    return home() / "prepared"

# How long a claimed preparation is believed. A process that died mid-build
# leaves its mark behind, and without this every later session would decline to
# start one because one was apparently already running.
STALE = 900.0

NOTHING = "nothing"      # no graph, and none being built
PREPARING = "preparing"  # a build is running now
READY = "ready"          # a graph exists and matches the code
MOVED_ON = "moved on"    # a graph exists, and the code has changed since
FAILED = "failed"        # a build was tried and could not finish

# How long a failure is remembered before another attempt is made. Long enough
# that a broken environment is not retried on every prompt; short enough that
# installing the missing thing takes effect within a session.
FORGET_FAILURE = 1800.0


class Readiness(BaseModel):
    """Whether Vesta can contribute to this project yet."""

    state: str = NOTHING
    project: str = ""
    since: float = 0.0
    definitions: int = 0
    # Why a preparation could not finish. A failure that leaves no trace is
    # indistinguishable from one that never happened, and a user watching
    # nothing happen has no way to tell which they are looking at.
    why: str = ""

    @property
    def can_answer(self) -> bool:
        """Whether there is a graph worth reading.

        `MOVED_ON` counts. A graph whose tree has changed is out of date, not
        useless — and every caller that reads one goes through `graph_for`,
        which rebuilds when the fingerprint has moved. Refusing here would make
        a single edit turn Vesta silent until something else rebuilt it, which
        is worse than the brief rebuild the caller was going to pay for anyway.
        """
        return self.state in (READY, MOVED_ON)

    @property
    def is_current(self) -> bool:
        """Whether the graph matches the code as it is now."""
        return self.state == READY

    def describe(self) -> str:
        if self.state == FAILED:
            return f"could not prepare — {self.why}"
        if self.state == READY and not self.definitions:
            # Built, and there was nothing to build from. A new project is not
            # broken and not preparing; it simply has no structure yet, and
            # saying "ready" about an empty graph invites a user to wonder why
            # nothing is ever offered.
            return "nothing to describe yet — this project has no definitions"
        if self.state == READY:
            return f"ready — {self.definitions} definition(s) resolved"
        if self.state == MOVED_ON:
            return (
                f"ready — {self.definitions} definition(s) resolved; the code "
                "has changed since, and the next question rebuilds"
            )
        if self.state == PREPARING:
            waited = time.time() - self.since
            return f"preparing — started {waited:.0f}s ago, nothing to offer yet"
        return "not prepared — nothing has been built for this project"


def _mark(root: Path) -> Path:
    """Where a preparation's state is written.

    Resolved first: `readiness` resolves its argument and `_record_failure` did
    not, so a failure was written under one name and looked for under another,
    and the whole mechanism silently did nothing.
    """
    import hashlib

    root = Path(root).expanduser().resolve()
    where = STATE()
    where.mkdir(parents=True, exist_ok=True)
    return where / f"{hashlib.sha256(str(root).encode()).hexdigest()[:12]}.json"


def _readiness_of_parts(root: Path, parts: list) -> Readiness:
    """How ready a directory of projects is: as ready as its least ready part.

    Definitions are summed, because that is what a composed graph holds. The
    state is the weakest, so a workspace with one project still building says
    `preparing` rather than claiming a completeness it does not have.
    """
    states = []
    total = 0
    since = 0.0
    why = ""
    for part in parts:
        found = readiness(part)
        states.append(found.state)
        total += found.definitions
        since = max(since, found.since)
        why = why or found.why

    # Worst first: nothing to answer from beats a partial answer that looks
    # whole, and a failure somebody could fix beats either.
    for state in (FAILED, NOTHING, PREPARING, MOVED_ON):
        if state in states:
            return Readiness(
                state=state,
                project=str(root),
                definitions=total,
                since=since,
                why=why,
            )
    return Readiness(state=READY, project=str(root), definitions=total)


def readiness(project: Path | str) -> Readiness:
    """What Vesta can do for this project right now, without doing any of it."""
    root = Path(project).expanduser().resolve()
    from .held import _where

    # A directory of projects has no graph of its own — it is composed from the
    # graphs beneath it — so its readiness is theirs. Reported as the weakest
    # of the parts, because a workspace where one project is still building
    # cannot answer completely about itself, and saying "ready" would promise
    # more than it holds.
    from .compose import parts_of

    parts = parts_of(root)
    if parts:
        return _readiness_of_parts(root, parts)

    cached = _where(root)
    if cached.is_file():
        try:
            payload = json.loads(cached.read_text(encoding="utf-8"))
            found = Readiness(
                state=READY,
                project=str(root),
                definitions=len(payload.get("graph", {}).get("nodes", {})),
            )
            # **Ready means current, not merely present.**
            #
            # This used to report READY whenever a graph file existed, however
            # old — so a graph built before a morning's work still answered as
            # though it described the code. Every caller then took that as
            # permission to read it, and the wrong answer looked exactly like
            # the right one.
            #
            # Checking was avoided because fingerprinting cost 3.6 seconds on
            # an ordinary repository. It now costs 13 milliseconds, because the
            # walk prunes excluded directories instead of visiting and
            # discarding them, so there is no longer anything to trade.
            from .held import _shape

            if payload.get("shape") and payload["shape"] != _shape(root):
                found.state = MOVED_ON
            return found
        except (OSError, ValueError):
            pass

    mark = _mark(root)
    if mark.is_file():
        try:
            held = json.loads(mark.read_text(encoding="utf-8"))
            started = held.get("since", 0)
            if held.get("failed"):
                # Remembered, then forgotten: a missing language server is
                # worth reporting, and worth retrying once somebody has had a
                # chance to install one.
                if time.time() - started < FORGET_FAILURE:
                    return Readiness(
                        state=FAILED,
                        project=str(root),
                        since=started,
                        why=held.get("why", "no reason recorded"),
                    )
            elif time.time() - started < STALE:
                return Readiness(state=PREPARING, project=str(root), since=started)
        except (OSError, ValueError):
            pass

    return Readiness(state=NOTHING, project=str(root))


def _start_build(root: Path) -> None:
    """Run the build in a detached process, so no prompt waits for it.

    Given a PATH wide enough to find a language server. A hook runs in a
    minimal shell and `Popen` inherits it, so a build started from one could
    not see `pyright-langserver` in `~/.n/bin` — it resolved nothing, cached an
    empty graph, and the project reported itself ready with nothing in it. The
    places a language server is installed are few and worth naming.
    """
    where = os.environ.copy()
    reachable = [where.get("PATH", "")]
    for extra in (
        Path.home() / ".n" / "bin",          # n, for node-installed servers
        Path.home() / ".local" / "bin",      # pipx, pip --user
        Path.home() / ".cargo" / "bin",      # rust-analyzer
        Path.home() / "go" / "bin",          # gopls
        Path.home() / ".bun" / "bin",
        Path("/opt/homebrew/bin"),
        Path("/usr/local/bin"),
    ):
        if extra.is_dir() and str(extra) not in reachable[0]:
            reachable.append(str(extra))
    where["PATH"] = ":".join(p for p in reachable if p)

    try:
        subprocess.Popen(
            [sys.executable, "-m", "vesta.ready", "--build", str(root)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
            env=where,
        )
    except OSError as exc:
        logger.info("could not start preparation: %s", exc)
        try:
            _mark(root).unlink()
        except OSError:
            pass


def refresh(project: Path | str) -> Readiness:
    """Rebuild a graph the code has moved past, without waiting for it.

    **The rebuild is all or nothing, and that is what makes this necessary.**
    A directory holding thirteen projects builds one graph of 6,309
    definitions in 73 seconds; touching a single file in one of them makes the
    whole thing stale, and the next question would pay all 73 seconds inside a
    prompt to rebuild twelve projects that did not change. Measured: a hook
    took over two minutes.

    So a hook that finds a stale graph starts a rebuild in the background and
    answers from the graph it has. The answer is briefly out of date and says
    so; the alternative is a session that stops for a minute every time
    somebody saves a file, which is not a tool anybody keeps installed.
    """
    root = Path(project).expanduser().resolve()

    # Only the parts that actually moved. This is what makes an edit cheap on
    # a workspace: eleven graphs are untouched and the twelfth rebuilds.
    from .compose import parts_of

    parts = parts_of(root)
    if parts:
        for part in parts:
            if readiness(part).state == MOVED_ON:
                refresh(part)
        return readiness(root)

    if readiness(root).state != MOVED_ON:
        return readiness(root)

    mark = _mark(root)
    try:
        # The same mark a first build uses, so two rebuilds cannot race and a
        # rebuild in progress is visible as `preparing`.
        if mark.is_file():
            held = json.loads(mark.read_text(encoding="utf-8"))
            if not held.get("failed") and time.time() - held.get("since", 0) < STALE:
                return readiness(root)
        mark.write_text(json.dumps({"since": time.time()}), encoding="utf-8")
    except (OSError, ValueError):
        return readiness(root)

    _start_build(root)
    return readiness(root)


def prepare(project: Path | str) -> Readiness:
    """Start building, without waiting for it.

    Detached on purpose. The caller is a hook answering a user's prompt, and
    the work takes ten seconds; the only acceptable amount of that to spend on
    the prompt is none.
    """
    root = Path(project).expanduser().resolve()

    # A directory of projects has nothing of its own to build. Preparing it is
    # preparing each part, and each carries its own mark — so one project's
    # build finishing makes that project answerable without waiting for the
    # rest, which is the whole reason the graphs are separate.
    from .compose import parts_of

    parts = parts_of(root)
    if parts:
        for part in parts:
            prepare(part)
        return readiness(root)

    current = readiness(root)
    if current.state != NOTHING:
        return current

    mark = _mark(root)
    try:
        mark.write_text(json.dumps({"since": time.time()}), encoding="utf-8")
    except OSError:
        return current

    # One place starts a build, so the PATH it is given cannot differ between
    # a first preparation and a refresh.
    _start_build(root)

    # Report the mark's own time, not now: two sessions starting together must
    # agree about when preparation began, or the second reads as a new one.
    return readiness(root)


def _build(project: str) -> int:
    """The detached half: build, then clear the mark."""
    root = Path(project)
    try:
        from .held import graph_for

        graph_for(root)
        # Harvest too, since a mature project may have months of sessions the
        # user never told Vesta about — the third of the three situations.
        from .harvest import from_sessions
        from .held import graph_for as held

        graph = held(root)
        from_sessions(graph, root)

        # Let go of records whose repository is gone, while something is
        # already running in the background. A thousand files accumulated here
        # in a few days without anyone noticing, because none of them is large
        # — a store nobody prunes stops being a description of anything.
        try:
            from .tidy import sweep

            swept = sweep()
            if swept.removed:
                logger.info("tidied: %s", swept.describe())
        except Exception as exc:  # noqa: BLE001 - tidying is never the point
            logger.info("could not tidy: %s", exc)

        # Nothing here calls a model. Deriving patterns, naming a domain and
        # reading code against it are judgement, and judgement belongs to the
        # `vesta-domain`, `vesta-rules` and `vesta-defects` agents, which run on
        # the host's inference and cost the user no API key. Preparation builds
        # what is mechanical — the graph, the harvest — so that when an agent
        # has judged, asking is a read.
    except Exception as exc:  # noqa: BLE001 - a failed preparation is not fatal
        logger.info("preparation failed for %s: %s", root, exc)
        _record_failure(root, f"{type(exc).__name__}: {exc}"[:200])
        return 0
    try:
        _mark(root).unlink()
    except OSError:
        pass
    return 0


def _record_failure(root: Path, why: str) -> None:
    """Leave the mark in place, saying what went wrong.

    Not deleted: a cleared mark reads as "never attempted", and the difference
    between that and "attempted and could not" is the whole of what a user
    needs to act.
    """
    try:
        _mark(root).write_text(
            json.dumps({"since": time.time(), "failed": True, "why": why}),
            encoding="utf-8",
        )
    except OSError:
        pass


def main() -> int:
    if len(sys.argv) >= 3 and sys.argv[1] == "--build":
        return _build(sys.argv[2])
    print(readiness(os.getcwd()).describe())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
