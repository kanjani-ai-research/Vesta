"""Running until the work is done, and knowing when that is.

An agent asked to build something stops when it decides it has finished. That
decision is made by the thing being judged, which is why the leading loop plugin
has to instruct its own model *"do not output false promises to escape the
loop"* — an instruction that would be unnecessary if the model were a reliable
judge of its own work.

Vesta can do better because it has something the model does not: a contract that
was agreed before any code existed, and measurements that are counts rather than
opinions. Completion is not a judgement here. It is four conditions, each of
which is a fact:

- every behaviour in the contract is implemented **and** reached by a test
- the tests pass
- the rules the user stated are honoured by the code
- nothing is outstanding that `distance` can see — no defects, no files the
  resolver could not read

**A loop needs to know it is stuck, not only that it is unfinished.** An agent
can iterate forever making changes that move nothing, and no stopping condition
based on the model's own opinion can see that. Two readings that do not differ
are a fact, and after enough of them the honest answer is to stop and say what
remains rather than to keep spending.

**Off unless somebody turned it on.** Driving is not a mode a tool should assume:
it writes code without being asked each time, which is exactly what a user wants
when they asked for it and exactly what they do not want when they did not. So
it is per project, explicit, and survives restarts — a mode that resets is not a
mode.

**Nothing here writes code.** It says whether to keep going and what is
outstanding; the work is the agent's, on the host's inference. This is the part
that cannot be talked out of.
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import List, Optional

from pydantic import BaseModel, Field

from .contract import Contract
from .contract import recall as recall_contract
from .distance import Reading, between, measure

logger = logging.getLogger("vesta.driving")

# How many readings that do not move before the loop is stuck. Three: one is
# ordinary — an iteration spent reading rather than writing moves nothing — and
# two can be a slow start. Three in a row is a pattern.
STUCK_AFTER = 3

# The most iterations before stopping regardless. Not a completion condition, a
# backstop: a loop that has run this long without finishing has a problem no
# further iteration will solve, and spending somebody's money to prove it is
# not a service.
AT_MOST = 40


class State(BaseModel):
    """Whether this project is being driven, and what has happened so far."""

    on: bool = False
    since: float = 0.0
    # Which session turned it on. The state is per project and the Stop hook
    # fires in every session open on that project, so without this a loop
    # started in one window traps every other one. The reference
    # implementation had to fix exactly this.
    session: str = ""
    iterations: int = 0
    readings: List[Reading] = Field(default_factory=list)
    # Why it stopped, if it has. Recorded so the next session can say what
    # happened rather than starting again as though nothing had.
    stopped: str = ""

    @property
    def stuck(self) -> bool:
        """Nothing measurable has changed for several iterations.

        The signal a loop needs most, and the one a model judging its own work
        cannot produce: an agent convinced it is making progress will say so
        indefinitely.
        """
        if len(self.readings) <= STUCK_AFTER:
            return False
        recent = self.readings[-(STUCK_AFTER + 1) :]
        return all(
            between(recent[n], recent[n + 1]).stalled for n in range(len(recent) - 1)
        )

    @property
    def spent(self) -> bool:
        return self.iterations >= AT_MOST

    def describe(self) -> str:
        # Why it stopped matters as much as that it did: "done" and "gave up
        # after forty iterations" are the same state and opposite outcomes.
        if self.stopped:
            return f"not being driven — {self.stopped}"
        if not self.on:
            return "not being driven"
        return f"driving, {self.iterations} iteration(s)"


class Verdict(BaseModel):
    """Whether to keep going, and what is outstanding."""

    keep_going: bool = False
    done: bool = False
    why: str = ""
    outstanding: List[str] = Field(default_factory=list)
    reading: Optional[Reading] = None

    def describe(self) -> str:
        if self.done:
            return f"done — {self.why}"
        if not self.keep_going:
            return f"stopping — {self.why}"
        return f"not done — {'; '.join(self.outstanding[:3])}"


def _where(repo: Path | str) -> Path:
    from .home import kept_at

    return kept_at(repo, "driving").with_suffix(".json")


def state(repo: Path | str) -> State:
    """Whether this project is being driven."""
    path = _where(repo)
    if not path.is_file():
        return State()
    try:
        return State.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return State()


def _keep(here: State, repo: Path | str) -> None:
    path = _where(repo)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        path.write_text(here.model_dump_json(), encoding="utf-8")
    except OSError as exc:
        logger.info("could not record driving state: %s", exc)


def start(
    repo: Path | str, at: Optional[float] = None, session: str = ""
) -> State:
    """Turn driving on for this project.

    Explicit, because writing code unasked is welcome only from somebody who
    asked. Per project, because a user wants this on a greenfield app and not
    on the repository their company runs on.
    """
    here = state(repo)
    here.on = True
    here.since = at if at is not None else time.time()
    here.session = session or os.environ.get("CLAUDE_CODE_SESSION_ID", "")
    here.stopped = ""
    _keep(here, repo)
    return here


def stop(repo: Path | str, why: str = "asked to stop") -> State:
    """Turn driving off, and say why."""
    here = state(repo)
    here.on = False
    here.stopped = why
    _keep(here, repo)
    return here


# What running the tests told us. Three answers, not two: they passed, they
# failed, or nothing was learned. The third is the one that matters — a runner
# that could not start and a suite with nothing in it must never be read as
# success, or the loop finishes over a project nobody verified.
PASSED = "passed"
FAILED = "failed"
NOTHING_TO_RUN = "no tests to run"
COULD_NOT_RUN = "the tests could not be run"


def _tests_pass(repo: Path | str) -> str:
    """Whether the project's own tests pass, or why that is unknown."""
    import subprocess
    import sys

    root = Path(repo).expanduser().resolve()
    if not any(root.rglob("test_*.py")) and not any(root.rglob("*_test.py")):
        return NOTHING_TO_RUN

    # The interpreter running Vesta, not whatever `python` happens to mean.
    # Bare `python` is frequently not on PATH at all, and the FileNotFoundError
    # was being swallowed into "no tests to run" — a runner failure reported as
    # an empty suite, which is exactly the confusion that lets a loop finish
    # over an unverified project.
    for interpreter in (sys.executable, "python3", "python"):
        try:
            done = subprocess.run(
                [interpreter, "-m", "pytest", "-q", "--no-header"],
                cwd=str(root),
                capture_output=True,
                text=True,
                timeout=900,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            logger.info("could not run the tests with %s: %s", interpreter, exc)
            continue

        # pytest exits 5 when it collected nothing, which is not a failure.
        if done.returncode == 5:
            return NOTHING_TO_RUN
        return PASSED if done.returncode == 0 else FAILED

    return COULD_NOT_RUN


def look(repo: Path | str, at: Optional[float] = None) -> Verdict:
    """Whether the work is done, and if not, what is outstanding.

    Every condition is a count or a process exit code. None of them asks
    anything to judge its own work, which is the whole reason this exists.
    """
    root = Path(repo).expanduser().resolve()
    reading = measure(root, at=at)
    verdict = Verdict(reading=reading)

    agreed = recall_contract(root)
    if agreed is None or not agreed.signed:
        verdict.why = "nothing has been agreed for this project"
        verdict.outstanding.append("no signed contract")
        return verdict

    for behaviour in agreed.outstanding:
        verdict.outstanding.append(f"not built: {behaviour.does}")

    if reading.missing:
        verdict.outstanding.extend(reading.missing)
    else:
        if reading.rules_broken:
            verdict.outstanding.append(
                f"{reading.rules_broken} rule(s) the user set are broken"
            )
        if reading.unresolved:
            verdict.outstanding.append(
                f"{reading.unresolved} file(s) the resolver could not read"
            )
        if reading.defects:
            verdict.outstanding.append(f"{reading.defects} defect(s)")

    ran = _tests_pass(root)
    if ran != PASSED:
        verdict.outstanding.append(ran)

    if verdict.outstanding:
        verdict.keep_going = True
        return verdict

    verdict.done = True
    verdict.why = (
        f"{len(agreed.behaviours)} behaviour(s) built and tested, tests pass, "
        "nothing outstanding"
    )
    return verdict


def iterate(repo: Path | str, at: Optional[float] = None) -> Verdict:
    """Take a reading, record it, and say whether to keep going.

    The reading is kept so that being stuck is detectable. An agent that
    iterates without moving will do so indefinitely, and only a record of what
    did not change can show it.
    """
    here = state(repo)
    verdict = look(repo, at=at)

    if verdict.reading is not None:
        here.readings.append(verdict.reading)
        # Enough to see a pattern, not enough to grow without bound.
        here.readings = here.readings[-(STUCK_AFTER + 2) :]
    here.iterations += 1

    if verdict.done:
        here.on = False
        here.stopped = "done"
    elif here.stuck:
        verdict.keep_going = False
        verdict.why = (
            f"nothing has changed in {STUCK_AFTER} iteration(s) — "
            "say what remains rather than continuing"
        )
        here.on = False
        here.stopped = verdict.why
    elif here.spent:
        verdict.keep_going = False
        verdict.why = f"{AT_MOST} iterations without finishing"
        here.on = False
        here.stopped = verdict.why

    _keep(here, repo)
    return verdict
