"""A control-flow template, kept the way an expert would write one down.

The code graph has references, and the ontology has vocabulary, but neither
has *order*. `graph.py`'s edges are one kind, deliberately — "this refers to
that" — and say nothing about sequence: a language server cannot tell you that
step three follows step two, because that is not a fact about references, it
is a fact somebody asserts. A procedure is that assertion, kept as a small
graph of its own: `Step`s are what is done, `Then`s are what follows, and
which of a closed set of outcomes each `Then` is.

**An unstated branch is not a lesser claim, it is no claim.** A `Then` whose
outcome is `branches` but does not say what triggers it asserts nothing a
reader could ever find false — there is no way to look at a repository and
say the branch was taken wrongly, because nothing said when it should be
taken. That is worse than not recording the branch at all, because it looks
like structure and is not: a reader trusts it, builds on it, and there is
nothing under it. So a branch-shaped outcome with no condition is refused at
the moment it is written, not flagged later — the same discipline `rules.py`
applies to a rule quoting words nobody said, except this is authored content
rather than recovered text, so the refusal raises rather than logging and
moving on.

**The outcome vocabulary is closed, and each member earns its place.**
`continues` and `branches` are the minimal pair every sequence needs —
straight-line versus conditional. `exits` and `fails` are kept apart because
a procedure ending on purpose and a procedure ending badly are different
facts worth different things, the same distinction `contract.py` already
draws between a behaviour met and one outstanding. `retries` is not folded
into `branches`: what it points at is an earlier step, not a later one, and
"retry until X" is common enough in a software procedure — a flaky network
call, a migration, a CI step — to name on its own rather than force into a
generic conditional. `defers` hands off to another procedure entirely, so a
reader asking what a step implies can follow it rather than treat it as an
opaque leaf. Six members, and growing the set is a deliberate act, not
something one template does on its own.

**Attachment to code is not reinvented here.** `traverse.attach()` already
matches a `Term`'s words against a codebase's identifiers, and a `Step` is a
`Term` with an outcome graph wrapped around it — `as_terms` is the whole
seam, and nothing about matching changes.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional

from pydantic import BaseModel, Field, model_validator

from .home import kept_at

# The closed outcome vocabulary. Small on purpose — see the module docstring
# for why each member is here. Grown by a deliberate revision, not by one
# template inventing a seventh.
CONTINUES = "continues"
BRANCHES = "branches"
EXITS = "exits"
FAILS = "fails"
RETRIES = "retries"
DEFERS = "defers"

OUTCOMES = (CONTINUES, BRANCHES, EXITS, FAILS, RETRIES, DEFERS)

# Outcomes that only mean something if they say what triggers them. A branch
# nobody can state is a branch nobody can take; a retry nobody can state never
# stops.
BRANCH_SHAPED = (BRANCHES, RETRIES)


class Step(BaseModel):
    """One thing a procedure does."""

    id: str
    label: str = Field(description="What this step is, in the expert's own words")
    # A free string, matching traverse.Term.kind's own convention — "domain,
    # activity, role, or whatever the ontology uses". Most steps are
    # activities; a step naming a decision point or an artifact should not be
    # forced into a vocabulary this module does not own.
    kind: str = "activity"

    def describe(self) -> str:
        return f"{self.label} ({self.kind})"


class Then(BaseModel):
    """One step's consequence: what follows, and under what outcome."""

    source: str = Field(description="Step.id this follows from")
    target: str = Field(default="", description="Step.id this leads to, or \"\" for a terminal outcome")
    outcome: str = CONTINUES
    when: str = Field(
        default="",
        description="What triggers this, in words — required for a branch-shaped outcome",
    )

    @model_validator(mode="after")
    def _branch_states_its_condition(self) -> "Then":
        if self.outcome not in OUTCOMES:
            raise ValueError(f"not a known outcome: {self.outcome!r}")
        if self.outcome in BRANCH_SHAPED and not self.when.strip():
            raise ValueError(
                f"a {self.outcome!r} outcome must say what triggers it — "
                "an unconditional branch is not a branch"
            )
        return self

    def describe(self) -> str:
        arrow = f"→ {self.target}" if self.target else "(terminal)"
        when = f" when {self.when}" if self.when else ""
        return f"{self.source} --{self.outcome}{when}--> {arrow}"


class Procedure(BaseModel):
    """A named sequence of steps, and what follows each.

    Both directions are indexed, the same reason `graph.Graph` indexes both:
    "what follows this step" and "what leads to this step" are different
    questions, asked by different callers.
    """

    id: str
    label: str
    steps: List[Step] = Field(default_factory=list)
    thens: List[Then] = Field(default_factory=list)

    _out: Optional[Dict[str, List[Then]]] = None
    _in: Optional[Dict[str, List[Then]]] = None

    model_config = {"arbitrary_types_allowed": True}

    def _index(self) -> None:
        out: Dict[str, List[Then]] = {}
        into: Dict[str, List[Then]] = {}
        for then in self.thens:
            out.setdefault(then.source, []).append(then)
            if then.target:
                into.setdefault(then.target, []).append(then)
        self._out = out
        self._in = into

    def after(self, step_id: str) -> List[Then]:
        """What follows this step."""
        if self._out is None:
            self._index()
        return self._out.get(step_id, [])  # type: ignore[union-attr]

    def leads_to(self, step_id: str) -> List[Then]:
        """What leads to this step — the reverse of `after`."""
        if self._in is None:
            self._index()
        return self._in.get(step_id, [])  # type: ignore[union-attr]

    def terminal(self) -> List[Step]:
        """Steps with no outgoing continuation, or only a terminal outcome."""
        return [
            step
            for step in self.steps
            if not self.after(step.id)
            or all(t.outcome in (EXITS, FAILS) for t in self.after(step.id))
        ]

    def describe(self) -> str:
        return f"{self.label} — {len(self.steps)} step(s), {len(self.thens)} then(s)"


class Procedures(BaseModel):
    """Every procedure kept for a repository."""

    procedures: List[Procedure] = Field(default_factory=list)

    def get(self, id: str) -> Optional[Procedure]:
        for procedure in self.procedures:
            if procedure.id == id:
                return procedure
        return None

    def describe(self) -> str:
        if not self.procedures:
            return "no procedures recorded"
        return f"{len(self.procedures)} procedure(s): " + ", ".join(
            p.label for p in self.procedures
        )


def as_terms(procedure: Procedure) -> List:
    """A procedure's steps, in the shape `traverse` wants.

    The whole seam: `traverse.Term` needs only `id`, `kind`, and `label`, and a
    `Step` already has all three. Nothing about attachment is reimplemented
    here — `traverse.attach()` runs against these exactly as it runs against
    an ontology's terms.
    """
    from .traverse import Term

    return [Term(id=s.id, kind=s.kind, label=s.label) for s in procedure.steps]


def _where(repo: Path | str) -> Path:
    return kept_at(repo, "procedures").with_suffix(".json")


def recall(repo: Path | str) -> Procedures:
    """The procedures already recorded for this repository, if any."""
    path = _where(repo)
    if not path.is_file():
        return Procedures()
    try:
        return Procedures.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return Procedures()


def keep(procedures: Procedures, repo: Path | str) -> Path:
    """Write the procedures recorded for this repository."""
    path = _where(repo)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(procedures.model_dump_json(), encoding="utf-8")
    return path
