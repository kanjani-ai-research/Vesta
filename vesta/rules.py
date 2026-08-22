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

from .home import home

logger = logging.getLogger("vesta.rules")

# Where derived rules are kept, per repository.
RULES = home() / "rules"


def trimmed(text: str, limit: int) -> str:
    """A display string cut to a length, marked when it was cut.

    A bare `text[:limit]` severs mid-word and reads as complete — "deps
    should" looked like the whole rule until the file it came from was read
    directly, and it was actually "deps should — needs no known check", cut
    partway through a sentence with nothing to say so. Cutting back to the
    last space and appending an ellipsis is the difference between a summary
    and a corruption of the text.
    """
    if len(text) <= limit:
        return text
    marker = "…"
    room = limit - len(marker)
    if room <= 0:
        return marker
    cut = text[:room]
    boundary = cut.rfind(" ")
    # Only back off to the last space when it does not throw away most of the
    # budget — a single implausibly long word should still be cut at the
    # limit rather than collapse to just the marker.
    if boundary > room * 0.4:
        cut = cut[:boundary]
    return cut.rstrip() + marker

# How a user states a constraint rather than asks for something. Deliberately
# generous: a missed correction is a rule nobody gets, and a false one is
# filtered by whether anything observable follows from it.
CONSTRAINS = re.compile(
    r"\b(don'?t|do not|never|always|must|should (?:be|not|always|never)|"
    r"there should be|instead of|rather than|avoid|stop|no need to|"
    r"make sure|ensure|only ever|not one .* for each)\b",
    re.I,
)

# A rule stated as a definition rather than an instruction. People say what
# something *is* at least as often as what to do about it: "non-full auto is a
# companion, no consent" is a constraint on the code as binding as "never ask
# for consent in companion mode", and matching only imperatives threw away
# every rule its author stated this way.
#
# Found the hard way: four rules about which mode may do what were all stated
# declaratively, none was captured, and the constraint they described was then
# violated with nothing to notice.
DEFINES = re.compile(
    r"\b("
    r"(?:is|are) (?:a |an |the )?[a-z-]+, (?:no|not|never|without)\b|"
    r"(?:only|just) (?:for|in|applies to|belongs to)\b|"
    r"(?:does|do) not (?:apply|belong|extend) to\b|"
    r"(?:none|nothing) of .{0,60}(?:applies|belongs|apply|belong)\b|"
    r"(?:is|are|was|were|weren'?t|wasn'?t) not (?:supposed|meant|intended) to\b|"
    r"not supposed to\b|"
    r"belongs? (?:only )?(?:to|in)\b"
    r")",
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
    r"(\bdo you (agree|think)\b|\bwhat do you think\b|"
    r"\bi think\b.*\b(should|could|might|would)\b|"
    r"\b(thoughts|your take|makes sense|sound right|y or n|y o n)\b|"
    r"\bi (hope|wonder|suspect|wish)\b|\bmaybe\b|\bperhaps\b)",
    re.I,
)

# Somebody saying outright that they do not know.
#
# Separate from DELIBERATES because it is a different act: deliberating is
# floating a proposal, and this is stating a constraint while disclaiming the
# knowledge to state it. Both produce a sentence containing "should", and
# CONSTRAINS matches on "should".
#
# Found in live data. "it should be conditional, I don't know whether your
# assertion holds" reached the adjudication queue as a rule awaiting the
# user's confirmation — a sentence in which they had already said they could
# not confirm it. A queue full of those teaches somebody the feature is noise,
# and they stop looking at the ones that are real.
UNSURE = re.compile(
    r"\b(i (don'?t|do not) know\b|"
    r"i'?m not (sure|certain)\b|"
    r"not sure (if|whether|that)\b|"
    r"i can'?t tell\b|"
    r"no idea\b|"
    r"who knows\b)",
    re.I,
)

# A correction that scopes one turn. These expire; they are not standing rules.
#
# Widened after a live test recorded "don't edit anything yet, just tell me
# what you would change" as a standing rule — the most turn-scoped sentence
# imaginable, admitted because none of the old phrases matched it. What marks
# these is a constraint on *what to do next*, not on what the code must be:
# "yet", "for now", "just tell me", "hold off".
THIS_TURN = re.compile(
    r"\b(for (?:this|now)|right now|in this (?:case|turn|session)|"
    r"do (?:not|n'?t) edit anything|for the time being|just this once|"
    r"(?:do)?n'?t .{0,30}\byet\b|\byet,? just\b|just tell me|"
    r"hold off|wait (?:on|before)|before you (?:start|begin|do))\b",
    re.I,
)

# A rule that happens to be asked about in the same breath. "every module must
# open with a docstring — does resolve.py follow that?" states a constraint and
# then asks a question about it; the question is not what makes it uncertain.
# So a trailing question mark disqualifies a statement only when the constraint
# itself is what is being questioned.
ASKS_ABOUT_IT = re.compile(
    r"^\s*(should|must|do|does|is|are|can|could|would|why|what|how|when)\b",
    re.I,
)

# A turn that ends by asking something, whatever it opened with.
#
# `ASKS_ABOUT_IT` anchors at the start, so it only catches a turn that *begins*
# as a question. It missed "address the extraction now instead of shifting it
# in the document, or are you saying it's not worth doing?" — which opens with
# an imperative, matches CONSTRAINS on it, and is a question about what to do
# next rather than a rule about the code.
#
# The last clause is what decides, because that is where a turn says what it
# actually wants. Somebody who states a constraint and then asks whether the
# code honours it has stated a constraint; somebody whose closing clause is
# itself the question has asked one.
ASKS_AT_THE_END = re.compile(
    r"(^|[,;]\s*|\.\s+)"
    r"(or\s+)?"
    r"(are|is|do|does|did|can|could|should|would|will|shall|have|has|am)\s+"
    r"(you|we|i|it|that|this|they|there)\b"
    r"[^.?]*\?\s*$",
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
        return trimmed(self.text, 120)


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
        return f"[{mark}, {where}] {trimmed(self.text, 100)}"


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
        return f"{trimmed(self.text, 90)} — needs {self.missing}"


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




def _names_in(text: str) -> List[str]:
    found = {
        m[0] if isinstance(m, tuple) else m
        for m in ABOUT.findall(text)
    }
    return sorted(n for n in found if n and len(n) > 2)[:6]


# What a terminal produced, quoted back into a prompt. A user pasting an error
# is showing something, not deciding something — and a rule recovered from
# Vesta's own output is Vesta recording its own words as the user's.
QUOTED_OUTPUT = re.compile(
    r"(?:^|\n)\s*(?:"
    r"Traceback \(most recent|File \"[^\"]+\", line \d|"
    r"[A-Za-z]*Error: |warning: |ERROR: |"
    r"\$ |> |❯ |⎿|✘|✔ |pip install |npm install |brew install "
    r")"
)


# Vesta's own words, coming back around. A slash command puts its output and
# its instructions into the prompt, the transcript records that, and the next
# harvest reads it as something the user decided. The result is Vesta recording
# its own sentences as its user's rules — and those sentences are imperative,
# so they pass every test for a constraint.
OUR_OWN = re.compile(
    r"(Show (?:the guide|this|these) [a-z ]*verbatim|"
    r"Do not summarise it or add to it|"
    r"vesta (?:learn|decided|defects|does|shape|status|guide|elsewhere) |"
    r"Vesta (?:is not installed|could not start|knows this project)|"
    r"the project under works stays authoritative|"
    r"pip install vesta)",
    re.I,
)


# Source code, in a turn where somebody was showing or editing it.
#
# Found the worst way. `in this project every module must open with a docstring
# saying what it is for` was sitting in the candidate queue as a rule the user
# had stated — and it exists nowhere except as **fixture data inside
# `tests/test_seams.py`**, where it was written to exercise the harvester. It
# reached the transcript when the file was read or written, and the harvester
# read it back as somebody's decision.
#
# That is the same failure as inventing a finding: the tool asserting the user
# said something they did not. A sentence lifted out of a string literal is not
# a decision about the code, whatever it says.
IS_CODE = re.compile(
    r"(^|\n)\s*(def |class |import |from \w+ import|return |assert |@\w|"
    r"[\w.]+\s*=\s*[\[{(\"']|"
    r"\"\"\"|'''|```)",
)

# What a Python string literal looks like when it has been wrapped across lines
# by a formatter: a line ending in a quote, or beginning with one, mid-sentence.
WRAPPED_LITERAL = re.compile(r"(\"\s*\n\s*\"|'\s*\n\s*')")


def _is_code(said: str) -> bool:
    """Whether this is source rather than something somebody decided."""
    return bool(IS_CODE.search(said) or WRAPPED_LITERAL.search(said))


def _is_vestas_own(said: str) -> bool:
    """Whether this is something Vesta said, not something a user said."""
    return bool(OUR_OWN.search(said))


def _is_mostly_output(said: str) -> bool:
    """Whether something said is a paste rather than a statement.

    Not merely whether it *contains* output: a user quoting one line and then
    saying what to do about it has stated a rule, and the quote is the context
    that makes it legible. What disqualifies a candidate is the paste being the
    substance of it — a traceback, an install message, a block of shell.

    So the test is proportion, not presence. Half a dozen lines of terminal
    with a sentence attached is a paste; a sentence with a phrase in quotes is
    a statement.
    """
    lines = [line for line in said.splitlines() if line.strip()]
    if not lines:
        return False
    pasted = sum(1 for line in lines if QUOTED_OUTPUT.search("\n" + line))
    if not pasted:
        return False

    # Half or more of it is terminal output. A two-line paste — a message and
    # the command it suggests — is as much a paste as a twenty-line traceback,
    # so proportion decides rather than a count.
    if pasted >= len(lines) / 2:
        return True

    # Or it opens with output and never becomes a sentence about the code: a
    # user who pastes first and instructs after is stating a rule, and one who
    # only pastes is not.
    return pasted >= 2


def constrains(text: str) -> bool:
    """Whether something said states a constraint rather than asks for work."""
    said = text.strip()
    if len(said) < 20 or len(said) > 600:
        return False
    if _is_mostly_output(said) or _is_vestas_own(said) or _is_code(said):
        # Output pasted in to be looked at, or source being shown or edited —
        # not a decision about the code.
        return False
    if PREDICTS_NOTHING.match(said):
        return False
    if THIS_TURN.search(said):
        # Scoped to a turn: real, and expiring. Not a standing rule.
        return False
    if said.endswith("?") and ASKS_AT_THE_END.search(said):
        # It closes by asking something. What a turn wants is in its last
        # clause, and this one wants an answer rather than a constraint kept.
        return False
    if said.endswith("?") and ASKS_ABOUT_IT.match(said):
        # The constraint itself is the question, not a statement followed by
        # one. "must every module have a docstring?" asks; "every module must
        # have a docstring — does this one?" states and then asks.
        return False
    if DELIBERATES.search(said):
        # A proposal or a question. Recording it would return a user's own open
        # question to them as an obligation, which is worse than missing it.
        return False
    if UNSURE.search(said):
        # They said they do not know. Asking them to confirm it as a standing
        # rule asks them to settle something they have just said they cannot.
        return False
    if DEFINES.search(said):
        # Stated as a definition rather than an instruction. Still a rule.
        return True
    return bool(CONSTRAINS.search(said))


# A turn recorded as the user's that is not the user speaking.
#
# Found by asking where a rule came from. `in this project every module must
# open with a docstring saying what it is for` was sitting in the candidate
# queue as something the user had decided, and it exists nowhere but as fixture
# data inside `tests/test_seams.py`. It reached the queue three separate ways,
# and all three are recorded in the transcript with `role: user`:
#
# - **a compaction summary**, which replays an entire conversation as one turn.
#   Every rule-shaped sentence in a digest gets re-harvested as though it were
#   freshly stated, and there were 53 of these in this project's transcripts.
# - **an assistant turn**, echoed back with its `⏺` marker. 24 of those.
# - a genuine turn where somebody pasted the fixture to talk about it.
#
# The first two are not the user at any remove, so they are dropped here rather
# than filtered later — a summary is not a weaker signal of intent, it is a
# different speaker.
NOT_THE_USER = re.compile(
    r"^(⏺|"
    r"This session is being continued from a previous conversation|"
    r"Caveat: The messages below were generated|"
    r"\[Request interrupted)",
)

# The same, but anywhere in the opening rather than at the very start: a
# summary sometimes carries a preamble before it says what it is.
SUMMARISED = re.compile(
    r"(conversation that ran out of context|"
    r"The summary below covers the earlier portion|"
    r"Continue the conversation from where it left off)",
    re.I,
)


def _not_the_user(said: str) -> bool:
    """Whether a turn recorded as the user's was somebody else."""
    return bool(NOT_THE_USER.match(said) or SUMMARISED.search(said[:1500]))


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
        if said and not said.startswith("<") and not _not_the_user(said):
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
) -> Found:
    """Recover what a user has decided, from what they said in this project.

    Turns are admitted by pattern. Patterns are brittle and miss real rules,
    and the alternative — reading every turn — needs a model, which Vesta does
    not call. The `vesta-rules` agent reads on the host's inference and writes
    what it decided; this recovers the candidates that need no judgement.
    """
    root = Path(repo).expanduser().resolve()
    found = Found()

    if transcripts is None:
        from .harvest import _sessions_for

        transcripts = _sessions_for(root)

    by_text: Dict[str, Rule] = {}

    for path in transcripts:
        for said, stamp in _turns(path):
            found.considered += 1
            if not constrains(said):
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
#
# **Except they were the decision, and that was the defect.** `from_sessions`
# drops anything `constrains` rejects, so on this repository the model saw 42
# of 446 turns — 9.4%. Everything in the other 404 was invisible, and no prompt
# could recover it, because nothing was ever asked. Among them: "it shouldn't
# be configurable, commit or change main/active should write to FS-", which is
# a standing architectural decision phrased in a way no pattern anticipated.
#
# `for_reading` is the honest shape. Every turn goes to the thing that can
# judge it, and the patterns survive as a *score* that decides reading order
# rather than membership. The corpus is 150k characters and is read once per
# repository, so the cost of being thorough is small and the cost of being
# wrong is a rule the user has to state twice.


def worth_reading(said: str) -> int:
    """How likely a turn is to carry a decision. A hint, never a gate.

    Ordering only. Everything is read whatever this returns — the number
    decides what an agent looks at first when it has a limit, so that a budget
    spent early is spent on the most promising turns rather than on whatever
    the transcript happened to record first.
    """
    if _not_the_user(said) or _is_code(said) or _is_mostly_output(said):
        return 0
    if _is_vestas_own(said):
        return 0

    score = 1
    if CONSTRAINS.search(said):
        score += 3
    if DEFINES.search(said):
        score += 2
    if UNSURE.search(said) or DELIBERATES.search(said):
        score -= 2
    if THIS_TURN.search(said):
        score -= 2
    if said.endswith("?"):
        score -= 1
    # A turn nobody could act on is unlikely to be a decision about the code,
    # but shortness alone does not disqualify: "no bare excepts" is a rule.
    if len(said) < 25:
        score -= 1
    return max(score, 1)


def for_reading(
    repo: Path | str, transcripts: Optional[Sequence[Path]] = None
) -> List[Tuple[str, float, int]]:
    """Every turn the user actually said, best candidates first.

    Ungated on purpose. What comes back is `(what they said, when, score)`,
    ordered by score, so a caller with a budget reads the promising ones first
    and a caller without one reads everything.
    """
    root = Path(repo).expanduser().resolve()
    if transcripts is None:
        from .harvest import _sessions_for

        transcripts = _sessions_for(root)

    seen: set = set()
    found: List[Tuple[str, float, int]] = []
    for path in transcripts:
        for said, stamp in _turns(path):
            key = _normalise(said)
            if key in seen:
                continue
            seen.add(key)
            score = worth_reading(said)
            if score:
                found.append((said, stamp, score))

    found.sort(key=lambda entry: (-entry[2], entry[1]))
    return found

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


def _flatten(text: str) -> str:
    """Text reduced to what a quotation and its source have in common.

    Case, punctuation and whitespace go; word order stays, because order is
    the whole evidence that one string was copied out of another.
    """
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def _grounded_in(said: str, turns: Sequence[str]) -> bool:
    """Whether these are really somebody's words, from a turn they really said.

    The discipline is borrowed from langextract, which makes a model return
    exact source text and then verifies it against the source rather than
    trusting it. The failure it prevents here is the one that matters most: a
    rule attributed to a user who never said it.

    Matched on flattened text rather than exactly, because an agent quoting a
    turn will reasonably trim it, collapse its whitespace or drop a trailing
    clause. What is not allowed is a quotation that appears in no turn at all.

    Deliberately not `_normalise`, which sorts and dedupes words to compare
    whole turns as sets — substring containment against a sorted bag of words
    is meaningless, and using it here refused every legitimate quotation.
    """
    wanted = _flatten(said)
    if len(wanted) < 12:
        # Too short to be evidence of anything. A handful of characters will
        # appear inside some turn by accident, which would ground a rule on a
        # coincidence.
        return False
    return any(wanted in _flatten(turn) for turn in turns)


def read_judged(text: str, turns: Optional[Sequence[str]] = None) -> List[Rule]:
    """Parse the rules an agent kept, ignoring whatever else it wrote.

    `turns` is what the user actually said. When given, a rule quoting words
    that appear in no turn is refused rather than recorded — an agent reading
    hundreds of turns will occasionally attribute a paraphrase, and a rule the
    user never stated is worse than a rule missed.
    """
    found: List[Rule] = []
    refused = 0
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
        if turns is not None and not _grounded_in(said.strip(), turns):
            logger.info("refused a rule nobody said: %r", said[:80])
            refused += 1
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

    if refused:
        logger.warning(
            "refused %d rule(s) quoting words that appear in no turn", refused
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
    # High enough that a normal repository is read whole. The gate used to be
    # `constrains`, which discarded 90% before anything could judge it; a limit
    # that quietly reinstated the same cut-off would be the same bug wearing a
    # different name. 150k characters of transcript is one cheap pass.
    parser.add_argument("--limit", type=int, default=500)
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.WARNING, stream=sys.stderr)
    root = Path(args.repo).expanduser().resolve()

    if args.candidates:
        # Everything the user said, most promising first. Ungated: the
        # patterns decide reading order, never membership, because a rule
        # phrased in a way no pattern anticipated is exactly the rule nothing
        # else can recover.
        for said, _, _ in for_reading(root)[: args.limit]:
            print(f"--- {said[:600]}")
        return 0

    if args.write:
        # Verified against what the user actually said. An agent that read
        # four hundred turns will occasionally attribute a paraphrase, and a
        # rule the user never stated is worse than a rule missed.
        kept = read_judged(
            sys.stdin.read(), turns=[said for said, _, _ in for_reading(root)]
        )
        found = Found(rules=kept, considered=len(kept))
        keep_rules(found, root)
        print(f"kept {len(kept)} rule(s) for {root}")
        return 0

    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
