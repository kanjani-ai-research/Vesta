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
        held = len([f for f in self.findings if f.holds])
        parts = [f"{len(self.findings)} rule(s) checked", f"{held} held"]
        if self.broken:
            parts.append(f"{len(self.broken)} broken")
        if self.undecided:
            parts.append(f"{len(self.undecided)} could not be checked")
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


DERIVING = """A user of this repository stated the following rule:

    {rule}

They originally said it like this:

    {said}

Describe a mechanical check that would find places the repository breaks this
rule, using only what a resolved graph of definitions and a file tree can
answer.

You have four ways to enumerate:
  names_matching  — definitions whose name matches a regular expression
  files_matching  — files in the tree whose path matches a regular expression
  calls_into      — definitions that refer to something matching a pattern
  not_reached_by  — definitions that nothing matching a pattern reaches

and two ways to judge what you find:
  count_at_most   — the rule is broken if more than N are found
  count_at_least  — the rule is broken if fewer than N are found

Give the check that most directly tests the rule.

If none of these can actually test it, set tests_the_rule to false and say in
`why` what would be needed instead. That is a useful answer and a common one.
Do not supply an approximation: a check that matches every source file will
report every file as a violation, and a user accused of breaking a rule
thirty-five times over will stop believing any of it.
"""


def derive_check(rule: Rule, model: Optional[str] = None) -> Optional[Check]:
    """Turn a rule's prose into something executable, or say it cannot be."""
    import asyncio

    from .structure import _ensure_data_dir

    _ensure_data_dir()
    try:
        from pragmatos import llm

        extract = llm.build_extractor(model=model)
    except Exception as exc:  # noqa: BLE001
        logger.info("no model available to derive a check: %s", exc)
        return None

    async def run():
        return await extract(
            Check, DERIVING.format(rule=rule.stated or rule.text, said=rule.text[:600])
        )

    try:
        return asyncio.run(run())
    except Exception as exc:  # noqa: BLE001
        logger.info("could not derive a check: %s", exc)
        return None


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
        pattern = re.compile(check.pattern, re.I)
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
        if len(found) < check.how_many:
            return found or [Site(path=str(root), what="nothing found")], ""
        return [], ""

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
        check = derive_check(rule, model)
        if check is None:
            finding.undecided = "no check could be derived"
        else:
            sites, why = run_check(check, graph, root)
            finding.sites = sites[:20]
            finding.undecided = why
        verdict.findings.append(finding)

    return verdict
