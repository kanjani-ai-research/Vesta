"""Named functions over a project, and the one primitive a model performs.

A procedure says what order the work goes in; the ontology says what the work
is called; neither says *how any of it is done*. Day to day, a project's work
is done by a handful of things somebody runs — a build, a migration, a check,
and increasingly a step that only a model can take: "summarise the failing
tests", "draft the release note", "decide whether this change needs a
migration". Each is done the same way every time, by somebody who remembers
how, and the memory lives nowhere. A function is that memory, written down
under a name the project can call it by.

**Two kinds, and the one a model performs is the point.** A `command` is a
shell line — nothing new, kept here only so it can be named, listed, and given
a place in a procedure. An `ask` is the primitive this module exists for: a
model named by role (haiku, sonnet, opus), a system prompt written by the agent
that defined the function rather than by the user who calls it, a user prompt
template with declared inputs, and success criteria stated before the model is
run. It is defined once, deliberately, and called many times, cheaply.

**Vesta does not run the model.** `derive.py` says why and it holds here: the
judging moved to where the model already is, no key is held, and
`tests/test_conformance.py` asserts that no tool reaches one. So an `ask` is a
*brief*, and the host agent performs it — `brief()` renders what to run, the
agent runs it on its own inference, and `done()` takes the output back. The
seam is the same shape as every other one in this project: the agent decides,
Vesta writes the decision down and checks what it can.

**Criteria are a closed set, and the ones nothing can check say so.** A
criterion is `matches` (a pattern over the output), `contains` (a substring),
`nonempty`, `tests` (the project's own suite passes afterwards), or `asserted`
— the model's output meets it or does not and nothing here can tell. The last
is recorded as asserted, never dressed up as checked, the discipline the
contract names outright. A `matches` or `contains` criterion without a pattern
is refused when written, for the reason `procedure.py` refuses a branch
without a condition: it looks like a check and is not.

**A role that names no step is no role.** A function may say which step of
which procedure it performs. That claim is checked against the procedures
actually recorded when the function is added, and refused if it points
nowhere — a pipeline position nobody can follow back to a pipeline is noise
dressed as structure.

**Feedback is a ledger, and reinforcement is the smallest honest use of it.**
Every run is kept: what was given, a digest of what came back, which criteria
held, which were asserted. A person can then say a run was good or bad and
why. What that changes today is exactly one thing: the next brief for the
same function carries the reasons recent runs were judged bad, so the model
is told what went wrong last time rather than left to repeat it. That is a
placeholder for reinforcement, named as one. Rewriting the system prompt from
feedback is a judgement, and judgement is the agent's — this module hands it
the ledger and nothing more.
"""

from __future__ import annotations

import hashlib
import re
import time
from pathlib import Path
from typing import Dict, List, Optional

from pydantic import BaseModel, Field, model_validator

from .home import kept_at

# The models a brief may name — by role, as the plugin's agents declare them
# in frontmatter, because the host resolves the role to whatever it runs. A
# full model id here would be a fact about one provider in a tool that holds
# no provider's key.
MODELS = ("haiku", "sonnet", "opus")

# The closed set of what a criterion can be. Small on purpose, and each
# member is something `check()` can actually do — except the last, which is
# here so that what nothing can check is written down as that.
MATCHES = "matches"
CONTAINS = "contains"
NONEMPTY = "nonempty"
TESTS = "tests"
ASSERTED = "asserted"

CHECKS = (MATCHES, CONTAINS, NONEMPTY, TESTS, ASSERTED)

# Checks that mean nothing without something to check against.
NEEDS_PATTERN = (MATCHES, CONTAINS)

# A function's name, so it can be typed and so it can appear in a template
# without quoting.
NAME = re.compile(r"^[a-z][a-z0-9_-]*$")

# `{input}` in a prompt or a command line.
PLACEHOLDER = re.compile(r"\{([a-z][a-z0-9_]*)\}")

# How many runs are kept per project, trimmed on write the way
# `driving.readings` is. Enough to see a function's recent history; not a log.
RUNS_KEPT = 200

# How many recent bad judgements the next brief carries.
LESSONS = 3


class Criterion(BaseModel):
    """One thing a run must satisfy, and whether anything here can tell."""

    says: str = Field(description="What success is, in words")
    check: str = ASSERTED
    pattern: str = Field(default="", description="What `matches` or `contains` looks for")

    @model_validator(mode="after")
    def _a_check_says_what_it_checks(self) -> "Criterion":
        if self.check not in CHECKS:
            raise ValueError(f"not a known check: {self.check!r}")
        if self.check in NEEDS_PATTERN and not self.pattern:
            raise ValueError(
                f"a {self.check!r} criterion must say what it looks for — "
                "a check with nothing to check against is not a check"
            )
        if self.check == MATCHES:
            try:
                re.compile(self.pattern)
            except re.error as exc:
                raise ValueError(f"not a valid pattern: {exc}") from exc
        return self

    def describe(self) -> str:
        how = self.check if self.check != ASSERTED else "asserted — nothing here can check it"
        return f"{self.says} [{how}]"


class Ask(BaseModel):
    """The step a model performs: who, told what, asked what."""

    model: str = "sonnet"
    system: str = Field(description="The system prompt — written by whoever defined the function")
    prompt: str = Field(description="The user prompt, with {input} placeholders")

    @model_validator(mode="after")
    def _a_known_model(self) -> "Ask":
        if self.model not in MODELS:
            raise ValueError(f"not a model the host resolves: {self.model!r} (one of {', '.join(MODELS)})")
        if not self.system.strip():
            raise ValueError("an ask without a system prompt is a question with no role")
        if not self.prompt.strip():
            raise ValueError("an ask without a prompt asks nothing")
        return self


class Command(BaseModel):
    """A shell line, with the same placeholders."""

    run: str

    @model_validator(mode="after")
    def _runs_something(self) -> "Command":
        if not self.run.strip():
            raise ValueError("a command that runs nothing is not a command")
        return self


class Role(BaseModel):
    """Which step of which procedure this function performs."""

    procedure: str
    step: str

    def describe(self) -> str:
        return f"{self.procedure}/{self.step}"


class Function(BaseModel):
    """One named thing done to this project, the same way each time."""

    name: str
    about: str = Field(default="", description="What it is for, in one line")
    inputs: List[str] = Field(default_factory=list)
    ask: Optional[Ask] = None
    command: Optional[Command] = None
    criteria: List[Criterion] = Field(default_factory=list)
    role: Optional[Role] = None

    @model_validator(mode="after")
    def _one_kind_and_every_input_declared(self) -> "Function":
        if not NAME.match(self.name):
            raise ValueError(
                f"not a function name: {self.name!r} — lowercase, digits, _ and -, "
                "starting with a letter"
            )
        if (self.ask is None) == (self.command is None):
            raise ValueError("a function is exactly one of an ask or a command")
        for given in self.inputs:
            if not PLACEHOLDER.fullmatch("{" + given + "}"):
                raise ValueError(f"not an input name: {given!r}")
        used = set(PLACEHOLDER.findall(self.template()))
        undeclared = sorted(used - set(self.inputs))
        if undeclared:
            raise ValueError(
                f"the template uses {', '.join('{' + u + '}' for u in undeclared)}, "
                "which the function does not declare as an input"
            )
        return self

    @property
    def kind(self) -> str:
        return "ask" if self.ask is not None else "command"

    def template(self) -> str:
        """The text the placeholders are filled into."""
        if self.ask is not None:
            return self.ask.prompt
        return self.command.run  # type: ignore[union-attr]

    def describe(self) -> str:
        what = f" — {self.about}" if self.about else ""
        takes = f" ({', '.join(self.inputs)})" if self.inputs else ""
        where = f" performs {self.role.describe()}" if self.role else ""
        model = f" on {self.ask.model}" if self.ask else ""
        return f"{self.name}{takes} [{self.kind}{model}]{what}{where}"


class Verdict(BaseModel):
    """What one criterion said about one run.

    `held` is three-valued on purpose: a criterion nothing can check is not
    one that failed, and reporting it either way would be a claim nothing
    supports.
    """

    says: str
    check: str
    held: Optional[bool] = None
    note: str = ""

    def describe(self) -> str:
        mark = "✓" if self.held else ("✗" if self.held is False else "?")
        note = f" — {self.note}" if self.note else ""
        return f"{mark} {self.says}{note}"


class Run(BaseModel):
    """One performance of a function, and what was made of it."""

    at: float = 0.0
    function: str
    inputs: Dict[str, str] = Field(default_factory=dict)
    # A digest and a size, not the output: a run's output can be a file's
    # worth of prose, and a ledger that keeps every one is a ledger that
    # grows until nobody keeps it. Enough to tell two runs apart.
    output_digest: str = ""
    output_chars: int = 0
    verdicts: List[Verdict] = Field(default_factory=list)
    # The feedback. Empty until somebody says; "good" or "bad" after.
    judged: str = ""
    why: str = ""

    @property
    def met(self) -> bool:
        """Every criterion that could be checked, held."""
        return all(v.held for v in self.verdicts if v.held is not None)

    @property
    def asserted(self) -> int:
        return sum(1 for v in self.verdicts if v.held is None)

    def describe(self) -> str:
        when = time.strftime("%Y-%m-%d %H:%M", time.localtime(self.at)) if self.at else "?"
        checked = [v for v in self.verdicts if v.held is not None]
        held = sum(1 for v in checked if v.held)
        state = f"{held}/{len(checked)} checked criteria held" if checked else "nothing checkable"
        if self.asserted:
            state += f", {self.asserted} asserted"
        judged = f"; judged {self.judged}" + (f": {self.why}" if self.why else "") if self.judged else ""
        return f"{when} {self.function} — {state}{judged}"


class Functions(BaseModel):
    """Every function kept for a repository, and every run of them."""

    functions: List[Function] = Field(default_factory=list)
    runs: List[Run] = Field(default_factory=list)

    def get(self, name: str) -> Optional[Function]:
        for one in self.functions:
            if one.name == name:
                return one
        return None

    def runs_of(self, name: str) -> List[Run]:
        return [r for r in self.runs if r.function == name]

    def performing(self, procedure: str, step: str) -> List[Function]:
        """The functions that say they perform this step."""
        return [
            f for f in self.functions
            if f.role and f.role.procedure == procedure and f.role.step == step
        ]

    def describe(self) -> str:
        if not self.functions:
            return "no functions recorded"
        return f"{len(self.functions)} function(s): " + ", ".join(f.name for f in self.functions)


# ── Defining ─────────────────────────────────────────────────────────────────


def _where(repo: Path | str) -> Path:
    return kept_at(repo, "functions")


def recall(repo: Path | str) -> Functions:
    path = _where(repo)
    if not path.is_file():
        return Functions()
    try:
        return Functions.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return Functions()


def keep(kept: Functions, repo: Path | str) -> Path:
    path = _where(repo)
    path.parent.mkdir(parents=True, exist_ok=True)
    if len(kept.runs) > RUNS_KEPT:
        kept.runs = kept.runs[-RUNS_KEPT:]
    path.write_text(kept.model_dump_json(), encoding="utf-8")
    return path


def add(repo: Path | str, defined: Function) -> Functions:
    """Record a function, replacing one of the same name.

    The role is checked here rather than in the model because only here is
    there a repository to check it against.
    """
    if defined.role is not None:
        from . import procedure

        kept_procedures = procedure.recall(repo)
        found = kept_procedures.get(defined.role.procedure)
        if found is None:
            raise ValueError(
                f"no procedure {defined.role.procedure!r} is recorded here — "
                "a role must name a step somebody can follow back"
            )
        if not any(s.id == defined.role.step for s in found.steps):
            raise ValueError(
                f"procedure {defined.role.procedure!r} has no step {defined.role.step!r}"
            )

    kept = recall(repo)
    kept.functions = [f for f in kept.functions if f.name != defined.name] + [defined]
    keep(kept, repo)
    return kept


def remove(repo: Path | str, name: str) -> bool:
    """Forget a function. Its runs stay: a ledger is not rewritten."""
    kept = recall(repo)
    before = len(kept.functions)
    kept.functions = [f for f in kept.functions if f.name != name]
    if len(kept.functions) == before:
        return False
    keep(kept, repo)
    return True


# ── Performing ───────────────────────────────────────────────────────────────


def fill(defined: Function, inputs: Dict[str, str]) -> str:
    """The template with every input in place, or a refusal naming what is missing."""
    missing = [name for name in defined.inputs if name not in inputs]
    if missing:
        raise ValueError(f"{defined.name} needs {', '.join(missing)}")
    text = defined.template()
    for name in defined.inputs:
        text = text.replace("{" + name + "}", inputs[name])
    return text


def lessons(kept: Functions, name: str, limit: int = LESSONS) -> List[str]:
    """Why recent runs of this function were judged bad, newest first."""
    bad = [r for r in reversed(kept.runs_of(name)) if r.judged == "bad" and r.why.strip()]
    return [r.why.strip() for r in bad[:limit]]


def brief(defined: Function, inputs: Dict[str, str], kept: Optional[Functions] = None) -> str:
    """What the host agent is to do, rendered so it can do it.

    For an ask this is the whole call: which model, the system prompt, the
    user prompt with inputs filled, the criteria the output will be held to,
    and what went wrong the last times anyone judged. For a command it is the
    line to run. Nothing here is run.
    """
    filled = fill(defined, inputs)
    lines: List[str] = [f"function: {defined.name}" + (f" — {defined.about}" if defined.about else "")]
    if defined.role:
        lines.append(f"performs: {defined.role.describe()}")

    if defined.command is not None:
        lines.append("kind: command")
        lines.append("run:")
        lines.append(f"  {filled}")
    else:
        lines.append(f"kind: ask, on {defined.ask.model}")  # type: ignore[union-attr]
        lines.append("system:")
        lines.extend(f"  {line}" for line in defined.ask.system.splitlines())  # type: ignore[union-attr]
        lines.append("prompt:")
        lines.extend(f"  {line}" for line in filled.splitlines())

    if defined.criteria:
        lines.append("held to:")
        lines.extend(f"  · {c.describe()}" for c in defined.criteria)

    learned = lessons(kept, defined.name) if kept is not None else []
    if learned:
        lines.append("recent runs were judged bad because:")
        lines.extend(f"  · {why}" for why in learned)

    lines.append("")
    lines.append(
        f"When it has run, record it: vesta function done {defined.name} --output-file <path>"
        + "".join(f" --input {name}=…" for name in defined.inputs)
    )
    return "\n".join(lines)


def check(defined: Function, output: str, repo: Path | str) -> List[Verdict]:
    """What each criterion says about this output. Only what can be told, is."""
    found: List[Verdict] = []
    for criterion in defined.criteria:
        verdict = Verdict(says=criterion.says, check=criterion.check)
        if criterion.check == MATCHES:
            verdict.held = re.search(criterion.pattern, output, re.M) is not None
            if not verdict.held:
                verdict.note = f"nothing matched /{criterion.pattern}/"
        elif criterion.check == CONTAINS:
            verdict.held = criterion.pattern in output
            if not verdict.held:
                verdict.note = f"{criterion.pattern!r} not in the output"
        elif criterion.check == NONEMPTY:
            verdict.held = bool(output.strip())
            if not verdict.held:
                verdict.note = "the output is empty"
        elif criterion.check == TESTS:
            from .driving import PASSED, _tests_pass

            state = _tests_pass(repo)
            verdict.held = state == PASSED
            if not verdict.held:
                verdict.note = state
        else:
            verdict.held = None
            verdict.note = "asserted; nothing here can check it"
        found.append(verdict)
    return found


def done(
    repo: Path | str,
    name: str,
    inputs: Dict[str, str],
    output: str,
    at: Optional[float] = None,
) -> Run:
    """Take a performance back: check it, write it down."""
    kept = recall(repo)
    defined = kept.get(name)
    if defined is None:
        raise ValueError(f"no function {name!r} is recorded here")
    fill(defined, inputs)  # refuses on a missing input, before anything is kept
    run = Run(
        at=at if at is not None else time.time(),
        function=name,
        inputs={k: inputs[k] for k in defined.inputs},
        output_digest=hashlib.sha256(output.encode("utf-8")).hexdigest()[:16],
        output_chars=len(output),
        verdicts=check(defined, output, repo),
    )
    kept.runs.append(run)
    keep(kept, repo)
    return run


def judge(repo: Path | str, name: str, good: bool, why: str = "") -> Run:
    """Say what somebody made of the latest run. The placeholder for reinforcement."""
    kept = recall(repo)
    runs = kept.runs_of(name)
    if not runs:
        raise ValueError(f"nothing has run {name!r} yet, so there is nothing to judge")
    if not good and not why.strip():
        raise ValueError("a bad judgement must say why — that is the only thing the next run learns from")
    latest = runs[-1]
    latest.judged = "good" if good else "bad"
    latest.why = why.strip()
    keep(kept, repo)
    return latest
