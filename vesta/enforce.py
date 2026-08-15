"""Checking a repository against what its user decided.

A rule that nobody checks is a note. The point of recovering "one repository,
one knowledge base" from a user's own words is to be able to say, later and
without being asked, that a change has just broken it.

**A verdict cites the utterance it came from.** An agent told "this violates a
constraint" will reasonably ask whose constraint, and a finding that cannot
answer is indistinguishable from the tool having an opinion. Every finding
carries the user's words, the moment they said them, and the sites that
violate.

**The check is derived, not written by hand.** Rules arrive as prose with a
kind — traversal, behaviour, artefact — and something has to turn "each
repository must correspond to exactly one knowledge base" into a query over a
graph. That derivation is model work, because the alternative is a fixed
vocabulary of checks and a rule that does not fit one is a rule that cannot be
checked. What is *executed* is not model work: a derived check is a pattern and
a predicate over resolved structure, so a finding is reproducible and a reader
can follow it.

**Finding nothing is the common case and is reported as such.** A repository
that honours its rules should say so, because silence is indistinguishable from
a check that never ran.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

from pydantic import BaseModel, Field

from .graph import Graph, Node
from .rules import ARTEFACT, BEHAVIOUR, TRAVERSAL, UNDERIVED, Found, Rule

logger = logging.getLogger("vesta.enforce")

# What a derived check can look for. Small and closed on purpose: each is
# something the graph or the tree can answer exactly, so a verdict is a fact
# rather than an opinion. A rule needing something outside this becomes a gap,
# which is how the specification learns what it lacks.
NAMES_MATCHING = "names_matching"      # definitions whose name matches a pattern
FILES_MATCHING = "files_matching"      # files in the tree matching a pattern
CALLS_INTO = "calls_into"              # definitions referring to a named thing
NOT_REACHED_BY = "not_reached_by"      # definitions nothing named reaches
CONTENT_MATCHING = "content_matching"  # lines inside files matching a pattern
FILES_LACKING = "files_lacking"        # files that never match a pattern
COUNT_AT_MOST = "count_at_most"        # no more than N of the above
COUNT_AT_LEAST = "count_at_least"      # at least N of the above


class Site(BaseModel):
    """Somewhere a rule is broken."""

    path: str
    line: int = 0
    what: str = ""

    def describe(self) -> str:
        where = f"{self.path}:{self.line}" if self.line else self.path
        return f"{where}{'  ' + self.what if self.what else ''}"


class Finding(BaseModel):
    """A rule, and where the repository does not honour it."""

    rule: str
    said: str = Field(description="The user's own words")
    when: float = 0.0
    sites: List[Site] = Field(default_factory=list)
    # Why no verdict was reached, when none was. A check that could not run is
    # not a repository that passed.
    undecided: str = ""

    @property
    def holds(self) -> bool:
        return not self.sites and not self.undecided

    def describe(self) -> str:
        if self.undecided:
            return f"? {self.rule[:70]} — {self.undecided}"
        if not self.sites:
            return f"✓ {self.rule[:70]}"
        return f"✗ {self.rule[:70]} — {len(self.sites)} site(s)"


class Verdict(BaseModel):
    """What a repository does and does not honour."""

    findings: List[Finding] = Field(default_factory=list)

    @property
    def broken(self) -> List[Finding]:
        return [f for f in self.findings if f.sites]

    @property
    def undecided(self) -> List[Finding]:
        return [f for f in self.findings if f.undecided]

    def describe(self) -> str:
        """What was found, counting only what was actually checked.

        A rule nothing ran against was not checked, and saying "3 checked, 0
        held" when nothing ran reads as three violations. The two numbers are
        kept apart: what ran, and what could not be run at all.
        """
        ran = [f for f in self.findings if not f.undecided]
        held = len([f for f in ran if f.holds])

        if not ran:
            return (
                f"nothing could be checked — {len(self.undecided)} rule(s) "
                "carry no check that runs here"
            )

        parts = [f"{len(ran)} rule(s) checked", f"{held} held"]
        if self.broken:
            parts.append(f"{len(self.broken)} broken")
        if self.undecided:
            parts.append(f"{len(self.undecided)} not checked")
        return ", ".join(parts)


class Check(BaseModel):
    """How to look for a violation of one rule.

    Derived from the rule's prose, then executed mechanically. Keeping these
    apart is what makes a finding reproducible: the same check over the same
    tree gives the same sites, whatever produced it.
    """

    look_for: str = Field(
        default="",
        description=(
            "What to enumerate: 'names_matching' for definitions whose name "
            "matches, 'files_matching' for files in the tree, 'calls_into' for "
            "definitions that refer to something named, 'not_reached_by' for "
            "definitions nothing reaches."
        ),
    )
    pattern: str = Field(
        default="",
        description="A regular expression naming what to enumerate.",
    )
    within: str = Field(
        default=r"\.py$",
        description=(
            "For content_matching and files_lacking: a regular expression for "
            "which files to read. Defaults to Python sources."
        ),
    )
    holds_when: str = Field(
        default="",
        description=(
            "'count_at_most' or 'count_at_least' — whether the rule requires "
            "few of these or many."
        ),
    )
    how_many: int = Field(
        default=0, description="The count the rule permits or requires."
    )
    why: str = Field(
        default="",
        description="Why this check tests the rule. Empty if it cannot be derived.",
    )
    tests_the_rule: bool = Field(
        default=True,
        description=(
            "False when the enumerations available cannot actually test this "
            "rule, whatever check was written down. Say so rather than "
            "supplying an approximation."
        ),
    )


def _check_on(rule: Rule) -> Optional[Check]:
    """The executable check a rule carries, if it carries one."""
    if not getattr(rule, "look_for", "") or not getattr(rule, "pattern", ""):
        return None
    return Check(
        look_for=rule.look_for,
        pattern=rule.pattern,
        within=rule.within or r"\.py$",
        holds_when=rule.holds_when,
        how_many=rule.how_many,
        why=rule.how,
        tests_the_rule=True,
    )


def _readable(root: Path, within: str) -> Iterable[Tuple[Path, str]]:
    """Files worth reading, and their repository-relative names."""
    try:
        which = re.compile(within or r"\.py$", re.I)
    except re.error:
        which = re.compile(r"\.py$")
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if any(p in (".venv", ".git", "node_modules", "__pycache__", ".vesta")
               for p in path.parts):
            continue
        relative = str(path.relative_to(root))
        if which.search(relative):
            yield path, relative


def run_check(check: Check, graph: Graph, root: Path) -> Tuple[List[Site], str]:
    """Execute a derived check. Nothing here is model work."""
    if not check.tests_the_rule:
        # The derivation said outright that these enumerations cannot test the
        # rule. Running it anyway produced thirty-five false accusations from a
        # pattern matching every source file, alongside a `why` that admitted
        # the check was not a test of anything.
        return [], check.why or "no mechanical check covers this rule"
    if not check.look_for or not check.pattern:
        return [], check.why or "no mechanical check covers this rule"

    try:
        # DOTALL as well as IGNORECASE. A pattern written for a docstring —
        # `""".*"""` — matches nothing without it, because every real docstring
        # spans lines, and the check then reports files that plainly have one.
        # Patterns are written to describe a thing, not to be careful about a
        # flag the writer cannot see.
        pattern = re.compile(check.pattern, re.I | re.S)
    except re.error as exc:
        return [], f"the derived pattern is malformed: {exc}"

    found: List[Site] = []

    if check.look_for == NAMES_MATCHING:
        for node in graph.nodes.values():
            if pattern.search(node.name) or pattern.search(node.qualified):
                found.append(Site(path=node.path, line=node.line + 1, what=node.qualified))

    elif check.look_for == FILES_MATCHING:
        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            if any(p in (".venv", ".git", "node_modules", "__pycache__") for p in path.parts):
                continue
            relative = str(path.relative_to(root))
            if pattern.search(relative):
                found.append(Site(path=relative))

    elif check.look_for == CALLS_INTO:
        targets = {
            n.id for n in graph.nodes.values()
            if pattern.search(n.name) or pattern.search(n.qualified)
        }
        for target in targets:
            for edge in graph.referenced_by(target):
                source = graph.nodes.get(edge.source)
                if source:
                    found.append(
                        Site(path=source.path, line=source.line + 1, what=source.qualified)
                    )

    elif check.look_for == CONTENT_MATCHING:
        # Inside files, not just their names. Most real rules are about what
        # the code says — "no conditional import of langextract", "commit must
        # write to the filesystem" — and matching paths and identifiers could
        # not reach any of them.
        for path, relative in _readable(root, check.within):
            try:
                lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError:
                continue
            for number, line in enumerate(lines, start=1):
                if pattern.search(line):  # one line at a time: DOTALL is moot
                    found.append(Site(path=relative, line=number, what=line.strip()[:90]))

    elif check.look_for == FILES_LACKING:
        # The absence of something, per file. "Every source file must carry a
        # module docstring" is not expressible as a match — it is expressible
        # as the files where no match occurs.
        for path, relative in _readable(root, check.within):
            try:
                body = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if not pattern.search(body):
                found.append(Site(path=relative, what="does not contain it"))

    elif check.look_for == NOT_REACHED_BY:
        reaching = {
            n.id for n in graph.nodes.values()
            if pattern.search(n.name) or pattern.search(n.qualified)
        }
        reached: Set[str] = set()
        for node_id in reaching:
            for edge in graph.depends_on(node_id):
                reached.add(edge.target)
        for node in graph.nodes.values():
            if node.id not in reached and node.id not in reaching:
                found.append(Site(path=node.path, line=node.line + 1, what=node.qualified))

    else:
        return [], f"unknown kind of check: {check.look_for}"

    # What was found is only a violation if the rule says so. A rule requiring
    # at most one shared config is broken by two; one requiring at least one
    # test per module is broken by none.
    if check.holds_when == COUNT_AT_MOST:
        return (found if len(found) > check.how_many else []), ""
    if check.holds_when == COUNT_AT_LEAST:
        if len(found) >= check.how_many:
            return [], ""
        # `at least zero` is vacuous and always satisfied. Treating it as an
        # absent subject made "every file must have a docstring" undecidable in
        # a repository where every file has one — the check had run, found the
        # nothing it was looking for, and that was the correct answer.
        if check.how_many <= 0:
            return [], ""
        if not found:
            # `files_lacking` and `not_reached_by` already enumerate the
            # violations themselves, so finding none of them is the rule being
            # honoured — not an absent subject. "Every file must have a
            # docstring", checked as "files lacking one", was called
            # undecidable in a repository where every file has one.
            if check.look_for in (FILES_LACKING, NOT_REACHED_BY):
                return [], ""
            # For the enumerations that find *presences*, nothing at all is
            # genuinely ambiguous: a rule about langextract, in a repository
            # with no langextract anywhere, was accused of breaking it with a
            # site pointing at the repository root.
            return [], (
                "nothing matching the rule's subject exists here, so the rule "
                "is neither honoured nor broken"
            )
        return found, ""

    # No judgement stated: anything found is a violation.
    return found, ""


def against(
    found: Found, graph: Graph, root: Path | str, model: Optional[str] = None
) -> Verdict:
    """Check a repository against every standing rule its user stated."""
    root = Path(root).expanduser().resolve()
    verdict = Verdict()

    for rule in found.standing:
        finding = Finding(
            rule=rule.stated or rule.text,
            said=rule.text,
            when=rule.last,
        )
        # The check the agent wrote, never one derived here. Deriving is model
        # work and this runs inside a tool call, which has none — an earlier
        # version called a model here and, when it could not, reported every
        # rule as "could not be checked" rather than failing. Degrading to
        # useless is worse than degrading to honest.
        check = _check_on(rule)
        if check is None:
            finding.undecided = (
                "no check was written for this rule"
                if rule.check != UNDERIVED
                else "nothing here can check a rule of this kind"
            )
        else:
            sites, why = run_check(check, graph, root)
            finding.sites = sites[:20]
            finding.undecided = why
        verdict.findings.append(finding)

    return verdict
