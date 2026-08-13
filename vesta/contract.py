"""What was agreed to be built, and whether it has been.

A loop needs a target that does not move. Without one, "done" is unreachable:
any late correction resets the goal and the loop runs forever, which is the
failure every autonomous coding tool has in common. So the target is agreed
once, written down, and then held to.

**Three kinds of thing, and only one of them is elicited.**

*Behaviours* are what the system does for whom — "a user can file a task",
"a reader can filter by tag". They are asked for until each can be checked
without a judgement call, and they are never inferred, because a wrong guess
about behaviour builds a coherent wrong product. They are also the only part a
user verifies: everything else is either theirs already or beneath their
interest.

*Constraints* are how it must be built — "use Postgres", "no external
services". Stated by the user, never inferred. They gate completion but are not
behaviours and carry no tests.

*Structure* is everything else: entities, glue, protocols, conventions. Inferred
freely and shown to nobody. A todo app has tasks that persist; HTTP has status
codes; a CLI has exit codes. Asking about any of it spends the user's patience
on what any competent implementer already knows.

**Once signed, behaviour does not change.** Not weighed, not scored — refused. A
change to what was agreed is a different project, and the options are to
continue, to start over, or to have it after delivery. This is strict on
purpose: a contract that follows the user's mind is not a contract, and a loop
chasing one never terminates. If the signed spec turns out not to say what
somebody meant, that is theirs to learn from, and it is cheaper to learn it once
than to build a tool that pretends specifications are provisional.

**Nothing here elicits or judges.** It holds what was agreed and reports what is
outstanding. The asking is an agent's work on the host's inference; the checking
is `enforce` and `distance`. This is the record they both refer to.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Dict, List, Optional

from pydantic import BaseModel, Field

logger = logging.getLogger("vesta.contract")

# Where the contract lives. In the repository, not in Vesta's cache: it belongs
# to the project, survives a cleared cache, and diffs like anything else. A
# contract nobody can see is not a contract.
WHERE = "VESTA.md"
BESIDE = ".vesta-contract.json"


class Behaviour(BaseModel):
    """Something the system does, for somebody, that can be checked."""

    does: str = Field(description="What it does, in the user's own words")
    # Definitions that implement it, once there are any. A behaviour nothing
    # implements is unbuilt however green the tests are — which is the usual way
    # an agent games a suite.
    nodes: List[str] = Field(default_factory=list)
    # Tests that reach it. Separate from `nodes`: a passing test over no
    # implementation and an implementation with no test are different failures.
    tests: List[str] = Field(default_factory=list)
    met_at: float = 0.0

    @property
    def met(self) -> bool:
        return bool(self.met_at)

    def describe(self) -> str:
        mark = "✓" if self.met else "·"
        return f"{mark} {self.does}"


class Contract(BaseModel):
    """What was agreed, when, and by whom."""

    goal: str = ""
    behaviours: List[Behaviour] = Field(default_factory=list)
    constraints: List[str] = Field(default_factory=list)

    # What was inferred rather than asked. Kept so a later reader can see what
    # was chosen on their behalf — never shown at verification, because the
    # point of inferring is not to spend the user's attention on it.
    inferred: List[str] = Field(default_factory=list)

    signed_at: float = 0.0
    # A change the user asked for after signing that would have altered
    # behaviour. Recorded rather than applied, so the contract shows what was
    # declined and why, and so it can be picked up after delivery.
    deferred: List[str] = Field(default_factory=list)

    @property
    def signed(self) -> bool:
        return bool(self.signed_at)

    @property
    def met(self) -> List[Behaviour]:
        return [b for b in self.behaviours if b.met]

    @property
    def outstanding(self) -> List[Behaviour]:
        return [b for b in self.behaviours if not b.met]

    @property
    def complete(self) -> bool:
        """Every agreed behaviour met. Says nothing about defects or rules —
        `distance` answers that, and both must hold before anything is done."""
        return self.signed and bool(self.behaviours) and not self.outstanding

    def describe(self) -> str:
        if not self.signed:
            return f"{len(self.behaviours)} behaviour(s), not yet agreed"
        return (
            f"{len(self.met)}/{len(self.behaviours)} behaviour(s) met"
            + (f", {len(self.constraints)} constraint(s)" if self.constraints else "")
            + (f", {len(self.deferred)} deferred" if self.deferred else "")
        )

    def to_verify(self) -> str:
        """What to put in front of the user, and nothing else.

        Behaviour, the goal, and any design they stated themselves. Not the
        inferred structure — 99% of people do not care what is under the hood,
        and showing it turns a ten-second read into a wall of text nobody
        verifies. A long spec is dismissed rather than checked, and dismissal
        looks exactly like agreement.
        """
        lines = [f"Vesta will build: {self.goal}", ""]
        lines.append("It will:")
        for behaviour in self.behaviours:
            lines.append(f"  · {behaviour.does}")
        if self.constraints:
            lines.append("")
            lines.append("You asked for: " + ", ".join(self.constraints))
        return "\n".join(lines)


def _where(repo: Path | str) -> Path:
    return Path(repo).expanduser().resolve() / BESIDE


def recall(repo: Path | str) -> Optional[Contract]:
    """The contract for this project, if there is one."""
    path = _where(repo)
    if not path.is_file():
        return None
    try:
        return Contract.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        logger.info("could not read the contract: %s", exc)
        return None


def keep(agreed: Contract, repo: Path | str) -> Path:
    """Write the contract, and the readable version beside it."""
    root = Path(repo).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)

    path = _where(root)
    path.write_text(agreed.model_dump_json(indent=2), encoding="utf-8")

    # A human-readable copy, because a contract only somebody's tooling can
    # read is one nobody will notice has drifted.
    (root / WHERE).write_text(_readable(agreed), encoding="utf-8")
    return path


def _readable(agreed: Contract) -> str:
    lines = [f"# {agreed.goal or 'This project'}", ""]
    if agreed.signed:
        when = time.strftime("%Y-%m-%d", time.localtime(agreed.signed_at))
        lines.append(f"Agreed {when}. Behaviour does not change after this.")
        lines.append("")

    lines.append("## What it does")
    lines.append("")
    for behaviour in agreed.behaviours:
        lines.append(f"- {behaviour.describe()}")

    if agreed.constraints:
        lines.extend(["", "## How it must be built", ""])
        for constraint in agreed.constraints:
            lines.append(f"- {constraint}")

    if agreed.deferred:
        lines.extend(["", "## Asked for after signing, not built", ""])
        lines.append("Changing agreed behaviour would make this a different")
        lines.append("project. These are kept for after delivery.")
        lines.append("")
        for change in agreed.deferred:
            lines.append(f"- {change}")

    if agreed.inferred:
        lines.extend(["", "## Chosen along the way", ""])
        lines.append("Not asked about, because they follow from the above.")
        lines.append("")
        for choice in agreed.inferred:
            lines.append(f"- {choice}")

    return "\n".join(lines) + "\n"


def sign(repo: Path | str, at: Optional[float] = None) -> Optional[Contract]:
    """Record that the user agreed to this. Behaviour is fixed from here."""
    agreed = recall(repo)
    if agreed is None:
        return None
    agreed.signed_at = at if at is not None else time.time()
    keep(agreed, repo)
    return agreed


def met(repo: Path | str, does: str, nodes: Optional[List[str]] = None,
        tests: Optional[List[str]] = None, at: Optional[float] = None) -> Optional[Contract]:
    """Record that a behaviour is now implemented and reached by a test."""
    agreed = recall(repo)
    if agreed is None:
        return None

    wanted = " ".join(does.lower().split())
    for behaviour in agreed.behaviours:
        if " ".join(behaviour.does.lower().split()) != wanted:
            continue
        behaviour.nodes = nodes or behaviour.nodes
        behaviour.tests = tests or behaviour.tests
        # Implemented *and* reached by a test. Either alone is a way for a loop
        # to finish over nothing: a passing test with no implementation, or an
        # implementation nothing checks.
        if behaviour.nodes and behaviour.tests:
            behaviour.met_at = at if at is not None else time.time()
        keep(agreed, repo)
        return agreed
    return agreed


def defer(repo: Path | str, change: str) -> Optional[Contract]:
    """Record a change that was asked for and declined.

    Kept rather than argued about. The user can have it after delivery, or
    start over; what cannot happen is the target moving while the loop runs.
    """
    agreed = recall(repo)
    if agreed is None:
        return None
    said = change.strip()
    if said and said not in agreed.deferred:
        agreed.deferred.append(said)
        keep(agreed, repo)
    return agreed
