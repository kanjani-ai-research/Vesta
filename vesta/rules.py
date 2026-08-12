"""What a user has decided, recovered from what they said.

A rule this system derives on its own is a guess. A rule that came from a user
correcting an agent is a decision — with a moment, a reason, and someone who
stands behind it. That is a stronger source of authority than anything
inferrable from source, and it is the one thing an agent cannot verify by
reading code: a correction it never saw leaves no trace in the artifact.

**A correction is derivable when it predicts something observable about a
future artifact.** Not when it is expressible as a graph traversal — that was
too narrow and discarded most real rules. "Port faithfully" predicts that a
ported artifact behaves as the original did; "one .env for v3" predicts that
config sites resolve to one file; "decisions, not toggles" predicts that no new
optional flag appears on a decision path. Each names a property something could
be found to violate. What is not derivable is a statement about nothing
observable — "I don't understand the divergence" asserts no invariant and
predicts nothing.

**A standing rule is not a task instruction.** "Do not edit anything" scopes one
turn and expires with it; "there should be one .env" does not. Phrasing does not
separate them — both are imperative and both name artifacts — so durability
does: a rule restated, or left uncontradicted across sessions, is standing. One
mention is a candidate.

**Nothing here enforces.** This notices and derives. A rule that is wrong and
enforced confidently is the failure mode that governs the whole design, so
promotion from candidate to enforced is a separate decision made elsewhere.
"""

from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

from pydantic import BaseModel, Field

from .home import VESTA_HOME

logger = logging.getLogger("vesta.rules")

# Where derived rules are kept, per repository.
RULES = VESTA_HOME / "rules"

# How a user states a constraint rather than asks for something. Deliberately
# generous: a missed correction is a rule nobody gets, and a false one is
# filtered by whether anything observable follows from it.
CONSTRAINS = re.compile(
    r"\b(don'?t|do not|never|always|must|should (?:be|not|always|never)|"
    r"there should be|instead of|rather than|avoid|stop|no need to|"
    r"make sure|ensure|only ever|not one .* for each)\b",
    re.I,
)

# What a correction is about, if it is about anything: a file, an identifier, a
# path, an extension. A constraint naming none of these is usually a mood.
ABOUT = re.compile(
    r"(\.[a-z]{2,4}\b|[a-zA-Z_][\w]*\.[a-zA-Z_][\w]*|\b[A-Z][a-zA-Z]+\b|"
    r"\b(?:commit|test|tests|import|imports|config|flag|flags|key|keys|"
    r"dependency|dependencies|docstring|comment|comments)\b)"
)

# Statements that predict nothing about any artifact. These are the honest
# rejections: a question, a confusion, an opinion offered without a claim.
PREDICTS_NOTHING = re.compile(
    r"^\s*(i (don'?t|do not) (know|understand)|what|why|how|when|where|who|"
    r"is |are |can |could |would |should i|do you|did you|does )",
    re.I,
)

# Deliberation, not decision. A user thinking aloud about a design says
# "should" as often as one stating a rule, and recording a proposal as a
# constraint would hand back somebody's open question as an obligation. What
# separates them is that a proposal invites an answer and a rule does not.
DELIBERATES = re.compile(
    r"(\?\s*$|\bdo you (agree|think)\b|\bwhat do you think\b|"
    r"\bi think\b.*\b(should|could|might|would)\b|"
    r"\b(thoughts|your take|makes sense|sound right|y or n|y o n)\b|"
    r"\bi (hope|wonder|suspect|wish)\b|\bmaybe\b|\bperhaps\b)",
    re.I,
)

# A correction that scopes one turn. These expire; they are not standing rules.
THIS_TURN = re.compile(
    r"\b(for (?:this|now)|right now|in this (?:case|turn|session)|"
    r"do not edit anything|for the time being|just this once)\b",
    re.I,
)

# How something a user said becomes checkable.
TRAVERSAL = "traversal"    # a property of how definitions refer to each other
BEHAVIOUR = "behaviour"    # a property of what the artifact does when run
ARTEFACT = "artefact"      # a property of a file, commit, or other product
UNDERIVED = "underived"    # a real constraint with no check yet — a gap


class Said(BaseModel):
    """Something a user said that constrains rather than requests."""

    text: str
    session: str = ""
    at: float = 0.0
    names: List[str] = Field(default_factory=list)

    def describe(self) -> str:
        return f"{self.text[:120]}"


class Rule(BaseModel):
    """A constraint a user stated, and what would show it violated.

    `check` says what kind of evidence settles it. `how` says what to look for,
    in words — deriving an executable check is a later stage, and recording the
    intent first means a rule is never lost because its check could not yet be
    written.
    """

    text: str
    check: str = UNDERIVED
    how: str = ""
    names: List[str] = Field(default_factory=list)
    # Every time this was said. A rule restated is standing; one said once is a
    # candidate, and the difference is not visible in the phrasing.
    said: List[Said] = Field(default_factory=list)
    first: float = 0.0
    last: float = 0.0
    # The rule as a reader could check it, written by whatever judged it. The
    # user's own words are kept in `text` because provenance is the point.
    stated: str = ""
    # Why this was not a rule, when something decided it was not.
    why_not: str = ""
    # How to look for a violation, written by whatever judged the rule. Held on
    # the rule rather than derived when needed: deriving is model work, and the
    # place that needs it is a tool call, which has no model. A rule without one
    # is reported as unchecked rather than silently passing.
    look_for: str = ""
    pattern: str = ""
    within: str = ""
    holds_when: str = ""
    how_many: int = 0

    @property
    def times(self) -> int:
        return len(self.said)

    @property
    def is_standing(self) -> bool:
        """Whether this constrains work beyond the moment it was said in.

        A judged rule stands immediately. Requiring repetition was wrong: a
        user states a rule once and expects it to hold, and something that has
        read the utterance and written down what would violate it has better
        evidence than a coincidence of restatement. Repetition still counts,
        for rules nothing has judged yet.
        """
        if self.stated:
            return True
        return self.times > 1 or (self.last - self.first) > 3600

    @property
    def is_derivable(self) -> bool:
        return self.check != UNDERIVED

    def describe(self) -> str:
        mark = "standing" if self.is_standing else "candidate"
        where = self.check if self.is_derivable else "no check yet"
        return f"[{mark}, {where}] {self.text[:100]}"


class Gap(BaseModel):
    """A real constraint whose check does not exist yet.

    Kept as a first-class thing rather than discarded, because a user who keeps
    correcting toward something the system cannot express is describing a
    dimension the specification lacks. A gap must name what would make it
    checkable, or it is a note rather than a gap.
    """

    text: str
    missing: str = Field(description="What capability would make this checkable")
    names: List[str] = Field(default_factory=list)

    def describe(self) -> str:
        return f"{self.text[:90]} — needs {self.missing}"


class Found(BaseModel):
    """What was recovered from a repository's sessions."""

    rules: List[Rule] = Field(default_factory=list)
    gaps: List[Gap] = Field(default_factory=list)
    # Candidates something read and declined. Kept rather than dropped: what a
    # sieve wrongly admits is the measure of the sieve.
    rejected: List[Rule] = Field(default_factory=list)
    considered: int = 0

    @property
    def standing(self) -> List[Rule]:
        return [r for r in self.rules if r.is_standing]

    def describe(self) -> str:
        return (
            f"{len(self.rules)} rule(s) from {self.considered} user turn(s), "
            f"{len(self.standing)} standing, {len(self.gaps)} gap(s)"
        )


class Worth(BaseModel):
    """Whether an utterance is worth judging properly."""

    worth_judging: bool = Field(
        description=(
            "True if this might state how work should be done in this "
            "repository — a preference, a constraint, a correction, a naming "
            "convention, anything a future change could contradict. Err "
            "towards true: this only decides what gets read more carefully."
        )
    )


SIFTING = """Does the following, said by a user to a coding agent, contain
anything about how work should be done in their repository?

Say yes for corrections, preferences, conventions, constraints, and standards —
however casually put. Say no for questions, pure requests to do a task, and
remarks that carry no expectation about future work.

This only decides what is read more carefully afterwards, so lean towards yes.

\"\"\"
{said}
\"\"\"
"""


def _names_in(text: str) -> List[str]:
    found = {
        m[0] if isinstance(m, tuple) else m
        for m in ABOUT.findall(text)
    }
    return sorted(n for n in found if n and len(n) > 2)[:6]


def constrains(text: str) -> bool:
    """Whether something said states a constraint rather than asks for work."""
    said = text.strip()
    if len(said) < 20 or len(said) > 600:
        return False
    if PREDICTS_NOTHING.match(said):
        return False
    if THIS_TURN.search(said):
        # Scoped to a turn: real, and expiring. Not a standing rule.
        return False
    if DELIBERATES.search(said):
        # A proposal or a question. Recording it would return a user's own open
        # question to them as an obligation, which is worse than missing it.
        return False
    return bool(CONSTRAINS.search(said))


def _turns(path: Path) -> Iterable[Tuple[str, float]]:
    stamp = path.stat().st_mtime if path.exists() else 0.0
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return
    for line in lines:
        try:
            payload = json.loads(line)
        except ValueError:
            continue
        message = payload.get("message") or {}
        if message.get("role") != "user":
            continue
        content = message.get("content")
        if isinstance(content, str):
            said = content
        elif isinstance(content, list):
            said = " ".join(
                b.get("text", "")
                for b in content
                if isinstance(b, dict) and b.get("type") == "text"
            )
        else:
            continue
        said = said.strip()
        # Harness-injected content is not the user speaking.
        if said and not said.startswith("<"):
            yield said, stamp


# ── Deriving ─────────────────────────────────────────────────────────────

# What kind of evidence settles a constraint, by what the constraint talks
# about. Ordered: the first that matches decides, so more specific patterns
# come first.
DERIVATIONS: Tuple[Tuple[re.Pattern, str, str], ...] = (
    (
        re.compile(r"\b(faithful|verbatim|as[- ]is|preserve|same behaviour|"
                   r"same behavior|port|parity|equivalent)\b", re.I),
        BEHAVIOUR,
        "run both and compare observable output for shared inputs",
    ),
    (
        re.compile(r"\b(commit|message|sign|signature|branch|push|pr)\b", re.I),
        ARTEFACT,
        "inspect the commits produced against the stated shape",
    ),
    (
        re.compile(r"\b(\.env|config|environment|key|keys|credential|secret)\b", re.I),
        TRAVERSAL,
        "find every site that loads configuration and check what it resolves to",
    ),
    (
        re.compile(r"\b(flag|flags|toggle|optional|conditional|fallback|"
                   r"import|imports|dependency|dependencies)\b", re.I),
        TRAVERSAL,
        "find the sites introducing optionality and check they are on decision paths",
    ),
    (
        re.compile(r"\b(test|tests|coverage|assert|fixture)\b", re.I),
        BEHAVIOUR,
        "run the suite and compare what it covers against the claim",
    ),
    (
        re.compile(r"\b(docstring|comment|comments|document|documentation|"
                   r"readme|naming|name)\b", re.I),
        ARTEFACT,
        "inspect the files produced for the stated property",
    ),
)


def derive(text: str) -> Tuple[str, str]:
    """What evidence would show this violated, and how to look for it.

    Returns `(UNDERIVED, why)` where nothing observable follows — which is a
    gap rather than a rejection, because the user meant something and the
    system merely cannot check it yet.
    """
    for pattern, kind, how in DERIVATIONS:
        if pattern.search(text):
            return kind, how
    return UNDERIVED, "no known check covers what this constrains"


def from_sessions(
    repo: Path | str,
    transcripts: Optional[Sequence[Path]] = None,
    read_everything: bool = False,
    model: Optional[str] = None,
) -> Found:
    """Recover what a user has decided, from what they said in this project."""
    root = Path(repo).expanduser().resolve()
    found = Found()

    if transcripts is None:
        from .harvest import _sessions_for

        transcripts = _sessions_for(root)

    by_text: Dict[str, Rule] = {}

    # Which turns are worth judging. Patterns are brittle and miss real rules;
    # reading every turn costs a cheap call each. `read_everything` chooses.
    admitted: Optional[Set[str]] = None
    if read_everything:
        every: List[str] = []
        for path in transcripts:
            every.extend(
                said for said, _ in _turns(path) if 20 < len(said) < 600
            )
        admitted = set(sift(every, model))

    for path in transcripts:
        for said, stamp in _turns(path):
            found.considered += 1
            if admitted is not None:
                if said not in admitted:
                    continue
            elif not constrains(said):
                continue

            names = _names_in(said)
            key = _normalise(said)
            rule = by_text.get(key)
            if rule is None:
                kind, how = derive(said)
                rule = Rule(
                    text=said, check=kind, how=how, names=names, first=stamp
                )
                by_text[key] = rule
                found.rules.append(rule)
            rule.said.append(Said(text=said, session=path.stem, at=stamp, names=names))
            rule.first = min(rule.first or stamp, stamp)
            rule.last = max(rule.last, stamp)

    for rule in found.rules:
        if not rule.is_derivable:
            found.gaps.append(
                Gap(text=rule.text, missing=rule.how, names=rule.names)
            )

    found.rules.sort(key=lambda r: (-r.times, -r.last))
    return found


def _normalise(text: str) -> str:
    """A key that treats a restatement as the same rule.

    Crude on purpose: exact-match would treat every rewording as a new rule and
    nothing would ever become standing.
    """
    words = [w for w in re.findall(r"[a-z]+", text.lower()) if len(w) > 3]
    return " ".join(sorted(set(words))[:8])


def keep(found: Found, repo: Path | str) -> Path:
    import hashlib

    root = Path(repo).expanduser().resolve()
    RULES.mkdir(parents=True, exist_ok=True)
    where = RULES / f"{root.name}-{hashlib.sha256(str(root).encode()).hexdigest()[:12]}.json"
    where.write_text(found.model_dump_json(), encoding="utf-8")
    return where


# ── Judging, by a model rather than by patterns ──────────────────────────
#
# Deciding whether an utterance is a standing rule is a semantic judgement, and
# patterns cannot make it. The evidence is on record twice over: matching
# `_resolve_with` to "resolve symbol references" worked by coincidence of
# English, and matching "this is a failure and repurposing of the cause" — a
# rebuke about mission drift — to "run the test suite" worked the same way.
# Both were confident and both were wrong for the same reason.
#
# So the patterns above are a *sieve*, not a decision. They cheaply narrow
# hundreds of turns to a few dozen candidates; what each candidate actually is
# gets settled by something that reads it.

class Judgement(BaseModel):
    """What something a user said actually is.

    A pydantic model rather than a schema dict: the extractor validates against
    the class, so a malformed answer is a retry rather than a silent None.
    """

    is_rule: bool = Field(
        description=(
            "True only if this states a standing constraint on how work is done "
            "in this repository — something a future change could violate. "
            "False for questions, proposals inviting agreement, one-off task "
            "instructions, permissions, praise, or complaints about the agent's "
            "process rather than about the artifact."
        )
    )
    rule: str = Field(
        default="",
        description=(
            "The constraint stated plainly and impersonally, as a rule a reader "
            "could check against a repository. Empty when is_rule is false."
        ),
    )
    check: str = Field(
        default=UNDERIVED,
        description=(
            "What evidence would show it violated: 'traversal' for a property of "
            "how definitions refer to each other, 'behaviour' for what the code "
            "does when run, 'artefact' for a property of a file or commit, "
            "'underived' for a real constraint none of these settles."
        ),
    )
    how: str = Field(
        default="",
        description=(
            "What to look for, concretely, to find a violation. When check is "
            "underived, what capability would be needed instead."
        ),
    )
    why_not: str = Field(
        default="", description="When is_rule is false, what this actually is."
    )


ASKING = """A user said the following to a coding agent working in their repository.

Decide what the user meant to bring about, not how they phrased it.

An instruction about how to answer *this* question is never a rule. "Do not use
any vesta tools", "do not edit anything", "just tell me" all scope one turn and
expire with it — recording them as standing rules hands a user a permanent
prohibition they meant for a single request, and an agent that reads it will
refuse the tool forever.

Users state rules casually. "There should be one .env for v3, not one per
service" is phrased as a suggestion and is a rule: it says how the repository
must be arranged, and a future change could violate it. Read for the intent —
if the user would be annoyed to find work done contrary to this later, it is a
rule, however softly it was put.

What is genuinely not a rule: a question seeking an answer, a proposal put up
for the agent's agreement and awaiting it, an instruction scoped to the task at
hand and expiring with it, a permission, or a remark about the agent's conduct
rather than about the repository.

A rule missed is a rule the user has to state again. A question recorded as a
rule is handed back to them later as an obligation they never made. Prefer to
recognise the rule where the user plainly wanted something to hold.

What they said:
\"\"\"
{said}
\"\"\"
"""


async def _judge_one(extract, said: str) -> Optional["Judgement"]:
    return await extract(Judgement, ASKING.format(said=said[:1500]))


def keep_rules(found: Found, repo: Path | str) -> Path:
    """Write what was judged, so a tool can read it without a model."""
    import hashlib

    root = Path(repo).expanduser().resolve()
    RULES.mkdir(parents=True, exist_ok=True)
    where = RULES / f"{root.name}-{hashlib.sha256(str(root).encode()).hexdigest()[:12]}.json"
    where.write_text(found.model_dump_json(), encoding="utf-8")
    return where


def recall_rules(repo: Path | str) -> Optional[Found]:
    """What was judged for this repository, if anything has been.

    Returns None rather than an empty result, so a caller can tell "nobody has
    judged this yet" from "there is nothing here" — the first is a prompt to
    run the agent, the second is an answer.
    """
    import hashlib

    root = Path(repo).expanduser().resolve()
    where = RULES / f"{root.name}-{hashlib.sha256(str(root).encode()).hexdigest()[:12]}.json"
    if not where.is_file():
        return None
    try:
        return Found.model_validate_json(where.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


# ── The seam an agent calls ──────────────────────────────────────────────

# How a judged rule is written by an agent: `check | rule | what they said`.
JUDGED = re.compile(r"^\s*(traversal|behaviour|artefact|underived)\s*\|\s*(.+?)\s*\|\s*(.+?)\s*$", re.I)

# An executable check, when the agent could write one:
#   check: files_matching /\.env$/ at_most 1
CHECK = re.compile(
    r"^\s*check:\s*(\w+)\s+/(.+?)/\s+(at_most|at_least)\s+(\d+)\s*$", re.I
)


def read_judged(text: str) -> List[Rule]:
    """Parse the rules an agent kept, ignoring whatever else it wrote."""
    found: List[Rule] = []
    for line in text.splitlines():
        line = line.lstrip("-*• \t")

        # A check belongs to the rule above it.
        checked = CHECK.match(line)
        if checked and found:
            look_for, pattern, holds, many = checked.groups()
            found[-1].look_for = look_for.lower()
            found[-1].pattern = pattern
            found[-1].holds_when = f"count_{holds.lower()}"
            found[-1].how_many = int(many)
            continue

        matched = JUDGED.match(line)
        if not matched:
            continue
        kind, stated, said = matched.groups()
        if len(stated) < 10:
            continue
        found.append(
            Rule(
                text=said.strip(),
                stated=stated.strip(),
                check=kind.lower(),
                how="",
                said=[Said(text=said.strip(), at=time.time())],
                first=time.time(),
                last=time.time(),
            )
        )
    return found


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Hand an agent the candidates; take back what it judged."""
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        prog="vesta-rules", description="Record the rules an agent recovered."
    )
    parser.add_argument("--repo", required=True)
    parser.add_argument("--candidates", action="store_true")
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--limit", type=int, default=60)
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.WARNING, stream=sys.stderr)
    root = Path(args.repo).expanduser().resolve()

    if args.candidates:
        # Patterns only: narrowing hundreds of turns to a few dozen needs no
        # model, and what each one *is* needs one that reads it.
        found = from_sessions(root)
        for rule in found.rules[: args.limit]:
            print(f"--- {rule.text[:600]}")
        return 0

    if args.write:
        kept = read_judged(sys.stdin.read())
        found = Found(rules=kept, considered=len(kept))
        keep_rules(found, root)
        print(f"kept {len(kept)} rule(s) for {root}")
        return 0

    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
