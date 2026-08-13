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
import time
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from pydantic import BaseModel, Field

from .graph import Graph
from .patterns import CLEAR, LIKELY, WORTH_A_LOOK, Found, Site, _lines, _sources
from .home import home

logger = logging.getLogger("vesta.learned")

# Where derived patterns are kept, per repository.
LEARNED = home() / "patterns"

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


# ── The seam an agent calls ──────────────────────────────────────────────

FIELD = re.compile(r"^\s*(name|why|find|skip|from|within)\s*:\s*(.+?)\s*$", re.I)


def read_finders(text: str) -> List[Pattern]:
    """Parse the finders an agent wrote, one block of fields per finder."""
    found: List[Pattern] = []
    current: Dict[str, str] = {}

    def flush() -> None:
        if current.get("name") and current.get("find"):
            found.append(
                Pattern(
                    name=current["name"][:60],
                    why=current.get("why", "")[:300],
                    pattern=current["find"],
                    not_reported=current.get("skip", ""),
                    exclude=current.get("skip", ""),
                    within=current.get("within", r"\.py$"),
                    said=current.get("from", "")[:300],
                    at=time.time(),
                    origin="derived",
                )
            )
        current.clear()

    for line in text.splitlines():
        matched = FIELD.match(line.lstrip("-*• \t"))
        if not matched:
            continue
        key, value = matched.group(1).lower(), matched.group(2)
        if key == "name" and current:
            flush()
        current[key] = value
    flush()
    return found


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Hand an agent the exchanges; take back the finders it wrote."""
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        prog="vesta-defects", description="Record the finders an agent derived."
    )
    parser.add_argument("--repo", required=True)
    parser.add_argument("--exchanges", action="store_true")
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--limit", type=int, default=40)
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.WARNING, stream=sys.stderr)
    root = Path(args.repo).expanduser().resolve()

    if args.exchanges:
        from .derive import _waiting

        waiting = _waiting(root)
        if waiting:
            print(waiting, file=sys.stderr)
            return 2

        from .harvest import _sessions_for

        for did, said, _ in _exchanges(_sessions_for(root))[-args.limit :]:
            print(f"--- AGENT DID: {did[:500]}")
            print(f"    USER SAID: {said[:500]}")
        return 0

    if args.write:
        wrote = read_finders(sys.stdin.read())
        # Checked against the repository before being kept, exactly as a
        # derivation of its own would be: one that matches nothing has not been
        # shown to describe anything here, and one matching most of the tree
        # describes the language.
        kept, dropped = [], []
        total = sum(1 for _ in _sources(root))
        for pattern in wrote:
            hits = pattern.find(root)
            sites = sum(len(f.sites) for f in hits)
            if sites < TOO_RARE:
                dropped.append(f"{pattern.name}: matches nothing here")
                continue
            if sites > TOO_MANY:
                dropped.append(f"{pattern.name}: {sites} sites, too many to act on")
                continue
            if total and len(hits) / total > TOO_COMMON:
                dropped.append(f"{pattern.name}: matches most of the tree")
                continue
            kept.append(pattern)

        keep(Learned(patterns=kept, considered=len(wrote), dropped=dropped), root)
        print(f"kept {len(kept)} finder(s) for {root}")
        for why in dropped:
            print(f"  dropped: {why}")
        return 0

    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
