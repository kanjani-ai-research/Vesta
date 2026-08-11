"""Patterns nobody wrote by hand.

Four hand-written patterns is four defects one person happened to think of, and
a fifth kind of defect goes unfound forever. That ceiling is the flaw: a survey
that only ever reports what its author already knew is a checklist, and a
checklist does not learn.

**The material is already on record, but not in single sentences.** Every
hand-written pattern here came from this project's own history — "the tool
can't be specific to Python repos" became the hardcoded-language-list finder.
But that defect was not stated in one turn. It took three: the user said it,
an agent built a list of markers, and the user rejected the list as "wholly
insufficient, this would be disastrous". No sentence in that exchange is a
defect statement on its own.

**So the unit is an exchange, not an utterance.** What the agent did, and what
the user said back. A first attempt classified turns one at a time and found
nothing at all from eighteen of them, because it was asking for something that
only exists across several. The position is structural — a user turn following
agent work — so finding candidates costs no model at all, and only judging them
does.

**A derived pattern must earn its place the same way a hand-written one does.**
It states why the thing is a defect, what it deliberately does not report, and
it is checked against the repository before anyone sees it: a pattern that
matches nothing is a guess, and one that matches almost everything is a
tautology. Both are dropped without being shown.

**Nothing here decides that code is wrong.** It proposes a finder, the finder
runs mechanically, and what it finds is a work item a reader accepts or
dismisses. The judgement stays where it can be checked.

**A new project has no history, and that is handled by not depending on one.**
The hand-written patterns in `patterns` work from the first minute and need
nothing to have happened; these are what a project has *in addition*, once
somebody has corrected something. So the sequence is: the floor works
immediately, derived patterns arrive as a project accumulates exchanges, and a
project that never corrects anything keeps the floor forever — which is a
worse outcome than the alternative only if the floor is bad.

**The examples that calibrate this came from one project, and that is stated
rather than hidden.** They are the four defects confirmed here, which is a
seeded prior: a stranger's first derivations are shaped by what was noticed in
this codebase. That is better than no prior and worse than their own, and it
should decay as their own confirmed cases accumulate.

**Whether a pattern was worth showing is answered the same way.** A user shown
a finding says something next, and assent and rejection are as recoverable as
the correction that produced the pattern in the first place. A pattern whose
findings get dismissed stops being shown; one nobody objects to keeps its
place. Without this the set only grows, and a survey that reports seventy-three
things is a survey nobody reads.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from pydantic import BaseModel, Field

from .graph import Graph
from .patterns import CLEAR, LIKELY, WORTH_A_LOOK, Found, Site, _lines, _sources
from .structure import VESTA_HOME

logger = logging.getLogger("vesta.learned")

# Where derived patterns are kept, per repository.
LEARNED = VESTA_HOME / "patterns"

# A finder matching more than this share of a repository's files is describing
# the language, not a defect. `except` appears everywhere; `except: pass` does
# not.
TOO_COMMON = 0.35

# And one matching nothing has not been shown to describe anything here.
TOO_RARE = 1  # sites

# A defect showing this many times is not a defect, it is the codebase. The
# file-share gate misses these when they concentrate: a finder matching
# eighty-one lines across four files passes "few files" and is still something
# nobody can act on. A work item a reader cannot finish is not a work item.
TOO_MANY = 25  # sites

# Writing a finder is the sensitive step and is worth a stronger model. The
# cheap one produced `git|GIT|subprocess\..*git`, which matches any line
# mentioning git, and `(?:regex|pattern|match)\s*[=:]`, which matches most of
# this codebase — both passed the "does it match" gate and neither describes a
# defect. Judging *whether* an exchange named a defect is cheap; writing the
# expression that finds it is not.
SHARPER = "anthropic/claude-sonnet-4-5"


class Pattern(BaseModel):
    """A defect worth looking for, and how to look for it."""

    name: str = Field(description="Short name for the defect, three or four words")
    why: str = Field(
        description=(
            "Why this is a defect rather than a curiosity — what goes wrong for "
            "somebody because of it. Concrete, not a style preference."
        )
    )
    pattern: str = Field(
        description=(
            "A regular expression matching a line where the defect shows. It "
            "must match the defect, not the ordinary case: `except` matches "
            "every error handler, `except[^\\\\n]*:\\\\s*$` followed by pass "
            "matches the ones that discard."
        )
    )
    not_reported: str = Field(
        default="",
        description=(
            "What this deliberately does not report, and why that case is fine. "
            "A pattern whose exclusions are not written down will report them."
        ),
    )
    within: str = Field(
        default=r"\.py$", description="Which files to read, as a regular expression."
    )
    exclude: str = Field(
        default="",
        description=(
            "A regular expression for lines to skip — the known-good case, such "
            "as a test fixture that names a language on purpose."
        ),
    )
    # Where it came from, so a reader can weigh it.
    said: str = ""
    at: float = 0.0
    # Whether this is one of the built-in cases or was derived from a project's
    # own history. A stranger should be able to see which of their findings
    # come from their code and which from somebody else's priors.
    origin: str = "derived"
    # How this pattern has fared when its findings were shown. A pattern is not
    # good because it matches; it is good because what it surfaces is worth
    # somebody's attention, and only they can say.
    accepted: int = 0
    dismissed: int = 0

    @property
    def is_welcome(self) -> bool:
        """Whether this has earned its place.

        Silence counts as neither. A pattern is dropped only once it has been
        dismissed more than it has been accepted and dismissed at least twice —
        one rejection is a mood, two is a signal.
        """
        return not (self.dismissed >= 2 and self.dismissed > self.accepted)

    def find(self, root: Path) -> List[Found]:
        """Run this pattern over a repository."""
        try:
            marker = re.compile(self.pattern)
            skip = re.compile(self.exclude) if self.exclude else None
            which = re.compile(self.within, re.I)
        except re.error as exc:
            logger.info("pattern %s is malformed: %s", self.name, exc)
            return []

        by_file: Dict[str, List[Site]] = {}
        for path, relative in _sources(root):
            if not which.search(relative):
                continue
            for number, line in enumerate(_lines(path), start=1):
                if skip and skip.search(line):
                    continue
                if marker.search(line):
                    by_file.setdefault(relative, []).append(
                        Site(where=relative, line=number, what=line.strip()[:80])
                    )

        return [
            Found(pattern=self.name, why=self.why, confidence=LIKELY, sites=sites)
            for sites in by_file.values()
        ]


class Learned(BaseModel):
    """Patterns derived from a project's own history."""

    patterns: List[Pattern] = Field(default_factory=list)
    considered: int = 0
    # Proposals dropped before anyone saw them, and why. Kept because what a
    # derivation proposes badly is the measure of the derivation.
    dropped: List[str] = Field(default_factory=list)

    def describe(self) -> str:
        said = f"{len(self.patterns)} pattern(s) from {self.considered} exchange(s)"
        return f"{said}, {len(self.dropped)} dropped" if self.dropped else said


NOTICING = """An agent working in a codebase did this:

\"\"\"
{did}
\"\"\"

and the user responded:

\"\"\"
{said}
\"\"\"

Was the user pointing at a defect in the code — something that is wrong on its own
terms and would be worth finding elsewhere in the repository?

Say yes only for a property of the code that could be looked for: hardcoded
lists that should be open, errors discarded silently, configuration that should
not be optional, duplicated logic that should be shared. These are things a
regular expression over source lines could find.

Say no for requests to build something, questions, praise, complaints about the
agent's conduct, and preferences about process rather than about code.

If yes, describe the finder: what to match, what not to report, and why the
thing is a defect. The pattern must match the *defect* and not the ordinary
case — a pattern matching every error handler in the repository describes
Python, not a problem.

Four defects found this way in this project, as calibration:

  the agent hardcoded a list of file suffixes and the user said it was "wholly
  insufficient, this would be disastrous" for languages not on it
  -> match `(languages?|suffixes?|extensions?)\\s*[=:]\\s*[\\[\\(]`, not
     reporting test fixtures, because every language absent from such a list is
     one the tool silently cannot handle

  an exception was caught and discarded, and a failure surfaced later as
  silence rather than as an error
  -> match a handler whose whole body is `pass`, not reporting handlers that
     log or re-raise, because the caller cannot tell failure from success

  a function was written, superseded, and left behind
  -> match nothing textual; this is a graph property, so answer is_defect false

  the user asked a question about the design
  -> is_defect false: a question is not a defect

The expression is the hard part. It must find the defect and nothing else:

  `git` matches every line mentioning git, including imports, comments, and
  the word in prose — it describes a topic, not a defect
  `(?:regex|pattern|match)\\s*[=:]` matches most assignments in a codebase that
  works with patterns at all

If you cannot write an expression that separates the defect from the ordinary
case, answer is_defect false. A finder that fires everywhere is worse than no
finder, because a reader stops reading the whole channel.
"""


class Noticed(BaseModel):
    """Whether an exchange pointed at a findable defect."""

    is_defect: bool = Field(
        description="True only if this points at a property of code worth finding elsewhere"
    )
    pattern: Optional[Pattern] = Field(
        default=None, description="The finder, when is_defect is true"
    )
    why_not: str = Field(default="", description="What this was instead")


def _exchanges(paths: Sequence[Path]) -> List[Tuple[str, str, float]]:
    """Moments a user answered agent work, which is where defects get named.

    Structural, so it costs nothing: a user turn immediately following an
    assistant turn. Three thousand turns in one session yield two hundred and
    fifty-five of these, and only those need a model to judge.
    """
    found: List[Tuple[str, str, float]] = []
    for path in paths:
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        when = path.stat().st_mtime if path.exists() else 0.0

        turns: List[Tuple[str, str]] = []
        for line in lines:
            try:
                payload = json.loads(line)
            except ValueError:
                continue
            message = payload.get("message") or {}
            role = message.get("role")
            if role not in ("user", "assistant"):
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
            if said and not said.startswith("<"):
                turns.append((role, said))

        for index in range(1, len(turns)):
            role, said = turns[index]
            was, did = turns[index - 1]
            if role == "user" and was == "assistant" and 30 < len(said) < 900:
                found.append((did, said, when))
    return found


def from_history(
    repo: Path | str,
    limit: int = 40,
    model: Optional[str] = None,
    graph: Optional[Graph] = None,
    transcripts: Optional[Sequence[Path]] = None,
) -> Learned:
    """Derive finders from moments somebody noticed a defect.

    Every proposal is run against the repository before it is kept. One that
    matches nothing has not been shown to describe anything here; one that
    matches most of the tree describes the language. Both are dropped.
    """
    import asyncio

    from .harvest import _sessions_for
    from .rules import _turns
    from .structure import _ensure_data_dir

    root = Path(repo).expanduser().resolve()
    found = Learned()
    _ensure_data_dir()

    try:
        from pragmatos import llm

        extract = llm.build_extractor(model=model or SHARPER)
    except Exception as exc:  # noqa: BLE001
        logger.info("no model available to derive patterns: %s", exc)
        return found

    exchanges = _exchanges(transcripts if transcripts is not None else _sessions_for(root))
    exchanges = exchanges[-limit:] if limit else exchanges
    found.considered = len(exchanges)

    async def notice(did: str, text: str) -> Optional[Noticed]:
        try:
            return await extract(
                Noticed,
                NOTICING.replace("{did}", did[:900]).replace("{said}", text[:700]),
            )
        except Exception:  # noqa: BLE001 - one bad call is not a policy
            return None

    async def run() -> List[Optional[Noticed]]:
        return list(
            await asyncio.gather(*(notice(did, text) for did, text, _ in exchanges))
        )

    try:
        noticed = asyncio.run(run())
    except Exception as exc:  # noqa: BLE001
        logger.info("could not derive patterns: %s", exc)
        return found

    total = sum(1 for _ in _sources(root))
    seen: set = set()

    for (_, text, when), verdict in zip(exchanges, noticed):
        if verdict is None or not verdict.is_defect or verdict.pattern is None:
            continue
        pattern = verdict.pattern
        pattern.said, pattern.at = text[:300], when

        # Two derivations of one defect are one defect. The same exchange
        # described twice, or two exchanges about the same thing, produced
        # "hardcoded language list" and "Language-specific hardcoded
        # dependency" — and a survey reporting both reports one problem twice.
        key = pattern.pattern
        overlap = _covers_same_ground(pattern, found.patterns, root)
        if key in seen or overlap:
            if overlap:
                found.dropped.append(
                    f"{pattern.name}: finds the same sites as {overlap}"
                )
            continue
        seen.add(key)

        # Tried against the repository before anyone sees it.
        hits = pattern.find(root)
        sites = sum(len(f.sites) for f in hits)
        files = len(hits)
        if sites < TOO_RARE:
            found.dropped.append(f"{pattern.name}: matches nothing here")
            continue
        if sites > TOO_MANY:
            found.dropped.append(
                f"{pattern.name}: {sites} sites — too many to be one work item"
            )
            continue
        if total and files / total > TOO_COMMON:
            found.dropped.append(
                f"{pattern.name}: matches {files} of {total} files — describes "
                "the language, not a defect"
            )
            continue

        found.patterns.append(pattern)

    return found


DISMISSED = re.compile(
    r"\b(not a (defect|problem|bug)|that'?s (fine|intentional|deliberate|wrong)|"
    r"false positive|noise|irrelevant|don'?t (care|report)|ignore (that|those|it)|"
    r"by design|on purpose|not an issue|stop (reporting|showing))\b",
    re.I,
)
ACCEPTED = re.compile(
    r"\b(good (catch|find|point)|fixed|fixing|you'?re right|agreed|"
    r"nice (catch|find)|correct|will fix|let'?s fix)\b",
    re.I,
)


def weigh(learned: Learned, transcripts: Sequence[Path]) -> Learned:
    """Count how a project's patterns have fared when they were shown.

    Reads the same exchanges the patterns came from, looking for what a user
    said after a finding was surfaced. Crude by necessity — it cannot know
    which finding a remark was about — so a pattern is only dropped on repeated
    dismissal, and assent merely protects.
    """
    from .rules import _turns

    said: List[str] = []
    for path in transcripts:
        said.extend(text for text, _ in _turns(path))

    for pattern in learned.patterns:
        name = pattern.name.lower()
        for text in said:
            if name not in text.lower():
                continue
            if DISMISSED.search(text):
                pattern.dismissed += 1
            elif ACCEPTED.search(text):
                pattern.accepted += 1
    return learned


def everything(repo: Path | str) -> List[Pattern]:
    """Every pattern that applies to a repository: the floor plus its own.

    A project with no history gets the floor and nothing else, which is the
    answer to starting from zero. A project with history gets both, and a
    derived pattern that duplicates a seeded one supersedes it — a finder built
    from this codebase's own corrections knows more about it than a prior does.
    """
    learned = recall(repo)
    by_name = {p.name.lower(): p for p in seeded()}
    for pattern in learned.patterns:
        # Dropped once its findings have been dismissed more than welcomed. A
        # survey reporting seventy-three things is one nobody reads.
        if not pattern.is_welcome:
            continue
        by_name[pattern.name.lower()] = pattern
    return list(by_name.values())


def seeded() -> List[Pattern]:
    """The patterns that work before a project has any history.

    Not a fallback: these are the floor, and a project that never corrects
    anything keeps them. Each is a defect confirmed in the project that wrote
    them, which is why they are also the calibration examples — and why they
    are marked as somebody else's prior rather than the reader's own.
    """
    # Only what a single-line regular expression can honestly find. A seed for
    # swallowed failures was tried and removed: matching `except` alone found
    # sixty-three sites in twenty files — Python, not a defect — and narrowing
    # it to a same-line `pass` found nothing, because the body is on the next
    # line. The structural finder in `patterns` reads the body and covers it,
    # and both run, so nothing is lost by this seed staying small.
    return [
        Pattern(
            name="hardcoded language list",
            why=(
                "every language absent from the list is one the tool silently "
                "cannot handle, and nothing announces the limit"
            ),
            # Two shapes, because a language table is written both ways: as a
            # keyword argument and as a mapping keyed by language name. The
            # first version matched only the former and found nothing in a
            # project whose whole defect was `SERVERS = {"python": [".py"]}` —
            # the exact case the pattern exists for.
            pattern=(
                r"(languages?|suffixes?|extensions?|file_?types?)\s*[=:]\s*[\[\(]"
                r"""|['"](python|javascript|typescript|rust|golang|java|ruby"""
                r"""|php|swift|kotlin|scala|elixir|haskell)['"]\s*:"""
            ),
            not_reported="test fixtures, which name a language on purpose",
            exclude=r"test",
            origin="seeded",
        ),
    ]


def _covers_same_ground(
    pattern: Pattern, already: Sequence[Pattern], root: Path, share: float = 0.6
) -> str:
    """The name of an existing pattern this one mostly duplicates.

    Compared by what they *find*, not by what they say: two finders worded
    differently that land on the same lines are one finding for a reader, and
    only the sites can settle that.
    """
    mine = {
        (site.where, site.line)
        for finding in pattern.find(root)
        for site in finding.sites
    }
    if not mine:
        return ""
    for other in already:
        theirs = {
            (site.where, site.line)
            for finding in other.find(root)
            for site in finding.sites
        }
        if not theirs:
            continue
        common = len(mine & theirs)
        if common / min(len(mine), len(theirs)) >= share:
            return other.name
    return ""


def keep(learned: Learned, repo: Path | str) -> Path:
    import hashlib

    root = Path(repo).expanduser().resolve()
    LEARNED.mkdir(parents=True, exist_ok=True)
    where = LEARNED / f"{root.name}-{hashlib.sha256(str(root).encode()).hexdigest()[:12]}.json"
    where.write_text(learned.model_dump_json(), encoding="utf-8")
    return where


def recall(repo: Path | str) -> Learned:
    import hashlib

    root = Path(repo).expanduser().resolve()
    where = LEARNED / f"{root.name}-{hashlib.sha256(str(root).encode()).hexdigest()[:12]}.json"
    if not where.is_file():
        return Learned()
    try:
        return Learned.model_validate_json(where.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return Learned()
