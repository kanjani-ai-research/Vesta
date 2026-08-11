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

from .structure import VESTA_HOME

logger = logging.getLogger("vesta.ready")

# Where a preparation records that it is running or has finished.
STATE = VESTA_HOME / "prepared"

# How long a claimed preparation is believed. A process that died mid-build
# leaves its mark behind, and without this every later session would decline to
# start one because one was apparently already running.
STALE = 900.0

NOTHING = "nothing"      # no graph, and none being built
PREPARING = "preparing"  # a build is running now
READY = "ready"          # a graph exists and can be answered from
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
    STATE.mkdir(parents=True, exist_ok=True)
    return STATE / f"{hashlib.sha256(str(root).encode()).hexdigest()[:12]}.json"


def readiness(project: Path | str) -> Readiness:
    """What Vesta can do for this project right now, without doing any of it."""
    root = Path(project).expanduser().resolve()
    from .held import _where

    cached = _where(root)
    if cached.is_file():
        try:
            payload = json.loads(cached.read_text(encoding="utf-8"))
            return Readiness(
                state=READY,
                project=str(root),
                definitions=len(payload.get("graph", {}).get("nodes", {})),
            )
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


def prepare(project: Path | str) -> Readiness:
    """Start building, without waiting for it.

    Detached on purpose. The caller is a hook answering a user's prompt, and
    the work takes ten seconds; the only acceptable amount of that to spend on
    the prompt is none.
    """
    root = Path(project).expanduser().resolve()
    current = readiness(root)
    if current.state != NOTHING:
        return current

    mark = _mark(root)
    try:
        mark.write_text(json.dumps({"since": time.time()}), encoding="utf-8")
    except OSError:
        return current

    try:
        subprocess.Popen(
            [sys.executable, "-m", "vesta.ready", "--build", str(root)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError as exc:
        logger.info("could not start preparation: %s", exc)
        try:
            mark.unlink()
        except OSError:
            pass
        return current

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

        from_sessions(held(root), root)
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
