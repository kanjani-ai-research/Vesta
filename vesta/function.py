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
`nonempty`, `tests` (the project's own suite passes afterwards), `exits` (a
stated command, given the output on stdin, exits zero — "parses as JSON",
"compiles", "the linter accepts it"), or `asserted` — the model's output meets
it or does not and nothing here can tell. The last
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
EXITS = "exits"
ASSERTED = "asserted"

CHECKS = (MATCHES, CONTAINS, NONEMPTY, TESTS, EXITS, ASSERTED)

# How long an `exits` command may take. A check is a check, not a build.
EXITS_WITHIN = 120

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
    # For `exits`: a shell line given the output on stdin, run in the project,
    # that holds by exiting zero. This is how "parses as JSON", "compiles",
    # and "the linter accepts it" become checks rather than assertions —
    # most of what was asserted is a command somebody could have run.
    command: str = Field(default="", description="What `exits` runs, with the output on stdin")

    @model_validator(mode="after")
    def _a_check_says_what_it_checks(self) -> "Criterion":
        if self.check not in CHECKS:
            raise ValueError(f"not a known check: {self.check!r}")
        if self.check in NEEDS_PATTERN and not self.pattern:
            raise ValueError(
                f"a {self.check!r} criterion must say what it looks for — "
                "a check with nothing to check against is not a check"
            )
        if self.check == EXITS and not self.command.strip():
            raise ValueError(
                "an 'exits' criterion must say what to run — "
                "a check that runs nothing is not a check"
            )
        if self.check == MATCHES:
            try:
                re.compile(self.pattern)
            except re.error as exc:
                raise ValueError(f"not a valid pattern: {exc}") from exc
        return self

    def describe(self) -> str:
        if self.check == ASSERTED:
            how = "asserted — nothing here can check it"
        elif self.check == EXITS:
            how = f"exits: {self.command}"
        else:
            how = self.check
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
    # Where the witness for this run was kept, so `show` can point at the
    # record `why` reads. A path, not the witness: the witness is kept where
    # every other invocation's is, and this is only how to find it.
    witness_at: str = ""
    # Which criterion should have caught it, by its `says`, when a bad run
    # got past the checks. This is the field that turns feedback into a
    # measurement: an asserted criterion named here often is one that keeps
    # letting bad runs through, and is exactly where a real check is worth
    # writing. Empty when the judgement names none.
    missed: str = ""

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
        missed = f" (missed by: {self.missed})" if self.missed else ""
        return f"{when} {self.function} — {state}{judged}{missed}"


class Leak(BaseModel):
    """A criterion that bad runs got past, and how often.

    Counted, not judged: the number of runs judged bad that named this
    criterion as the one that should have caught them. For an asserted
    criterion that count is the case for writing a check; for a checked one
    it is the case that the check is wrong.
    """

    says: str
    check: str
    times: int = 0

    def describe(self) -> str:
        how = "asserted" if self.check == ASSERTED else f"checked by {self.check}"
        advice = (
            "worth a real check" if self.check == ASSERTED else "the check is not catching it"
        )
        return f"{self.says!r} ({how}) let {self.times} bad run(s) through — {advice}"


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

    def leaks(self, name: str) -> List[Leak]:
        """The criteria of this function that judged-bad runs named, most often first."""
        defined = self.get(name)
        if defined is None:
            return []
        counted: Dict[str, int] = {}
        for run in self.runs_of(name):
            if run.judged == "bad" and run.missed:
                counted[run.missed] = counted.get(run.missed, 0) + 1
        found = [
            Leak(says=c.says, check=c.check, times=counted[c.says])
            for c in defined.criteria
            if c.says in counted
        ]
        return sorted(found, key=lambda l: (-l.times, l.says))

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


# The least a prompt must share with a function's name and purpose before the
# function is offered. Two stems, not one: "release" alone is in half the
# prompts a maintainer types, and an offer on every one of them is the tax
# `inject.py` exists to avoid. A name typed out whole counts on its own, since
# nobody types `release-note` by accident.
SHARED_WORDS = 2


def for_prompt(kept: Functions, prompt: str) -> List[Function]:
    """The functions a prompt is plainly about, most shared words first.

    Matched on name and purpose through the same bag of stems the procedure
    query and `does` use, so the crossing is the one the rest of Vesta makes.
    Nothing fuzzy: a function is offered when the prompt shares two meaningful
    words with it or spells its name out, and otherwise it is not offered.
    """
    from .traverse import _bag

    wanted = _bag(prompt)
    lowered = prompt.lower()
    scored = []
    for one in kept.functions:
        named = one.name in lowered or one.name.replace("-", " ").replace("_", " ") in lowered
        shared = len(wanted & _bag(one.name.replace("-", " ").replace("_", " ") + " " + one.about))
        if named or shared >= SHARED_WORDS:
            scored.append((0 if named else 1, -shared, one.name, one))
    return [one for _, _, _, one in sorted(scored)]


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
    """Why recent runs of this function were judged bad, newest first.

    Where the judgement named the criterion it should have failed, that is
    said too: "too long (uses no bullet lists)" tells the model which of its
    standing requirements the last run fell short of, not only that it did.
    """
    bad = [r for r in reversed(kept.runs_of(name)) if r.judged == "bad" and r.why.strip()]
    return [
        r.why.strip() + (f" (criterion: {r.missed})" if r.missed else "")
        for r in bad[:limit]
    ]


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


def in_order(procedure) -> List:
    """A procedure's steps, in the order a reader would perform them.

    Steps nothing leads to come first; each step is followed by what its
    `Then`s point at, continuations before branches, each step once. A step
    nothing reaches and nothing starts from is still a step, and is listed
    last rather than lost. Order, not a schedule: a procedure with a real
    branch has two orders, and this shows one of them with the branch named.
    """
    from .procedure import CONTINUES

    seen: List[str] = []
    # A start is a step nothing leads to that leads somewhere. A step with
    # neither is isolated, not first, and is picked up at the end.
    starts = [
        s.id for s in procedure.steps
        if not procedure.leads_to(s.id) and procedure.after(s.id)
    ]
    queue = starts or [s.id for s in procedure.steps[:1]]
    while queue:
        here = queue.pop(0)
        if here in seen:
            continue
        seen.append(here)
        following = sorted(
            procedure.after(here),
            key=lambda t: (0 if t.outcome == CONTINUES else 1),
        )
        queue.extend(t.target for t in following if t.target and t.target not in seen)
    by_id = {s.id: s for s in procedure.steps}
    ordered = [by_id[i] for i in seen if i in by_id]
    ordered.extend(s for s in procedure.steps if s.id not in seen)
    return ordered


def pipeline(procedure, kept: Functions) -> str:
    """A procedure as the sequence of briefs that perform it.

    Procedures hold order and functions hold how; this is the one place both
    are read together. Each step is shown with the function that performs it
    — its inputs, model, and criteria, the template unfilled — or with the
    plain fact that nothing recorded performs it, which is the gap a reader
    wants to see rather than have smoothed over. The agent still fills each
    brief and performs it in turn; what it no longer does is reassemble the
    sequence by hand.
    """
    lines = [f"pipeline: {procedure.label} ({procedure.id}) — {len(procedure.steps)} step(s)"]
    unperformed = 0
    for number, step in enumerate(in_order(procedure), start=1):
        lines.append("")
        lines.append(f"{number}. {step.label} [{step.id}]")
        performing = kept.performing(procedure.id, step.id)
        if not performing:
            unperformed += 1
            lines.append("   performed by: nothing recorded")
        for one in performing:
            inputs = ", ".join(one.inputs) if one.inputs else "no inputs"
            if one.ask is not None:
                lines.append(f"   ask {one.name} on {one.ask.model} — takes {inputs}")
                lines.extend(f"     {line}" for line in one.ask.prompt.splitlines()[:3])
                if len(one.ask.prompt.splitlines()) > 3:
                    lines.append("     …")
            else:
                lines.append(f"   command {one.name} — takes {inputs}")
                lines.append(f"     {one.command.run}")  # type: ignore[union-attr]
            for criterion in one.criteria:
                lines.append(f"     · {criterion.describe()}")
            learned = lessons(kept, one.name)
            if learned:
                lines.append(f"     last judged bad: {learned[0]}")
            flags = "".join(f" --input {name}=…" for name in one.inputs)
            lines.append(f"     vesta function brief {one.name}{flags}")
        for then in procedure.after(step.id):
            when = f" when {then.when}" if then.when else ""
            target = then.target or "(ends here)"
            lines.append(f"   → {then.outcome}{when} → {target}")
    if unperformed:
        lines.append("")
        lines.append(
            f"{unperformed} step(s) nothing recorded performs. A function with "
            f'"role": {{"procedure": "{procedure.id}", "step": "<id>"}} fills one.'
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
        elif criterion.check == EXITS:
            verdict.held, verdict.note = _exits(criterion.command, output, repo)
        else:
            verdict.held = None
            verdict.note = "asserted; nothing here can check it"
        found.append(verdict)
    return found


def _exits(command: str, output: str, repo: Path | str) -> "tuple[Optional[bool], str]":
    """Whether a command accepts the output. Zero holds; anything else says why.

    A command that could not be run at all is not a failed check, it is an
    unknown one, and is reported as such rather than as the output being
    wrong — the same distinction `driving._tests_pass` draws between a suite
    that failed and a runner that did not start.
    """
    import subprocess

    try:
        ran = subprocess.run(
            command,
            shell=True,
            input=output,
            cwd=str(Path(repo).expanduser().resolve()),
            capture_output=True,
            text=True,
            timeout=EXITS_WITHIN,
        )
    except subprocess.TimeoutExpired:
        return None, f"could not check: `{command}` did not finish in {EXITS_WITHIN}s"
    except (OSError, subprocess.SubprocessError) as exc:
        return None, f"could not check: {exc}"
    if ran.returncode == 0:
        return True, ""
    said = (ran.stderr or ran.stdout).strip().splitlines()
    why = said[-1][:160] if said else ""
    return False, f"exited {ran.returncode}" + (f": {why}" if why else "")


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
    run.witness_at = _witnessed(defined, run, repo)
    kept.runs.append(run)
    keep(kept, repo)
    return run


def unperformed(repo: Path | str, since: float = 0.0) -> List[str]:
    """Role-bearing functions with no met run since `since`.

    A function that performs a step of a procedure is a claim that the step
    is done by running it. Driving checks the contract, the tests, the rules,
    and the distance, and until now could finish with such a step never
    having run — the one part of the work that is a declared sequence was
    the one part nothing counted. Only functions with a role are held to
    this: a function without one is a convenience, not a step.

    A met run is one whose checkable criteria all held; a run that did not
    meet them is a run, not a performance. `since` is the moment after which
    a run counts — the last change to the project — because a step performed
    before the code moved says nothing about the code as it stands.
    """
    kept = recall(repo)
    missing: List[str] = []
    for defined in kept.functions:
        if defined.role is None:
            continue
        if not any(r.met and r.at >= since for r in kept.runs_of(defined.name)):
            missing.append(defined.name)
    return missing


def _digest_of(defined: Function) -> str:
    """What the function said at the time, fixed.

    The function is the standard a run was held to — its criteria are what
    the output was judged against — and a standard edited afterwards must not
    make an old record read as though it had always said the new thing. The
    same reason `bundle.Witness` carries `standard_digest`.
    """
    return hashlib.sha256(
        defined.model_dump_json(exclude_defaults=True).encode("utf-8")
    ).hexdigest()[:16]


def _witnessed(defined: Function, run: Run, repo: Path | str) -> str:
    """Write the run as a witness, where every other invocation's is kept.

    A function run is a decision somebody will later ask about — what was
    asked, what came back, what it was held to, which checks held — and until
    now it lived in its own ledger where `why` could not see it. So it is
    written in the record's shape: each checkable criterion is a finding, the
    asserted ones are counted under `read` because that is what they are (a
    judgement nothing can re-run), and the function's definition is the
    standard, by name and digest.

    No trajectory, and none is invented: a run narrows nothing, so the
    narrowing fields stay empty rather than carrying a number that would read
    as a contraction. What the record claims is exactly what happened.

    A witness that cannot be written must not lose the run, so this returns
    an empty path rather than raising.
    """
    import os

    try:
        from . import bundle

        findings = [
            bundle.Finding(check=v.says, held=bool(v.held), detail=v.note)
            for v in run.verdicts
            if v.held is not None
        ]
        given = ", ".join(f"{k}={v[:40]!r}" for k, v in run.inputs.items())
        held = bundle.Witness(
            intent=f"function {defined.name}" + (f" ({given})" if given else ""),
            output=f"{run.output_chars} chars, digest {run.output_digest}",
            project=str(Path(repo).expanduser().resolve()),
            session=os.environ.get("CLAUDE_CODE_SESSION_ID", ""),
            at=run.at,
            commit=bundle._commit(repo),
            computed=len(findings),
            read=run.asserted,
            standard=f"function {defined.name}",
            standard_digest=_digest_of(defined),
            stood_by=[c.says for c in defined.criteria],
            findings=findings,
            verdict=(
                bundle.UNKNOWN
                if not findings
                else (bundle.SANE if all(f.held for f in findings) else bundle.UNSOUND)
            ),
        )
        return str(bundle.keep(held, repo))
    except Exception as exc:  # noqa: BLE001 - the run is kept whatever happens to its witness
        import logging

        logging.getLogger("vesta.function").info("could not witness the run: %s", exc)
        return ""


def judge(
    repo: Path | str, name: str, good: bool, why: str = "", missed: str = ""
) -> Run:
    """Say what somebody made of the latest run. The placeholder for reinforcement.

    `missed` names the criterion that should have caught a bad run, by what
    it says. It must be one of the function's own: a judgement naming a
    requirement the function never stated is a new requirement, which is a
    change to the function rather than feedback on a run of it.
    """
    kept = recall(repo)
    defined = kept.get(name)
    runs = kept.runs_of(name)
    if not runs:
        raise ValueError(f"nothing has run {name!r} yet, so there is nothing to judge")
    if not good and not why.strip():
        raise ValueError("a bad judgement must say why — that is the only thing the next run learns from")
    missed = missed.strip()
    if missed:
        if good:
            raise ValueError("a good run missed nothing — name a criterion only on a bad one")
        stated = [c.says for c in defined.criteria] if defined else []
        if missed not in stated:
            raise ValueError(
                f"{missed!r} is not a criterion of {name!r}"
                + (f" — it holds: {'; '.join(repr(s) for s in stated)}" if stated else "")
                + ". A requirement it never stated is a change to the function, not feedback on a run."
            )
    latest = runs[-1]
    latest.judged = "good" if good else "bad"
    latest.why = why.strip()
    latest.missed = missed
    keep(kept, repo)
    return latest
