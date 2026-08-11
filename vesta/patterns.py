"""Things in a codebase that are wrong on their own terms.

A rule needs a user to state it. An anti-pattern does not: it is a property of
the code that is a problem whether or not anybody has complained, and the graph
can find it unasked. That makes this the half of the system with no dependency
on anyone having said anything — the checker in `enforce` answers "does this
honour what you decided", and this answers "here is something worth fixing".

**Unusual is not wrong.** The first naive attempt reported ninety-two
definitions nothing refers to, and almost all were tests — nothing *should*
refer to a test. A finder that surfaces every oddity buries the real ones and
teaches a reader to skim past the whole channel. So every pattern here carries
the reason it is a defect and the case it deliberately excludes, and a pattern
that cannot state its exclusions does not belong.

**A finding is a work item, not a verdict.** It says where, what, and why it
matters, so a reader can act or dismiss it in one pass. Where the evidence is
weaker the finding says so rather than being suppressed — a maybe that explains
itself is more useful than a silence.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Set, Tuple

from pydantic import BaseModel, Field

from .dynamic import Blindspot, scan
from .graph import Graph, Node
from .propagate import is_test

logger = logging.getLogger("vesta.patterns")

# How much a finding is worth acting on. Not a probability — a statement about
# how much the evidence supports the claim, so a reader knows where to spend
# attention.
CLEAR = "clear"        # the defect is visible in the structure itself
LIKELY = "likely"      # the structure is strong evidence, with known exceptions
WORTH_A_LOOK = "worth a look"  # a signal, not a conclusion


class Site(BaseModel):
    """One place a defect shows."""

    where: str
    line: int = 0
    what: str = ""

    def describe(self) -> str:
        at = f"{self.where}:{self.line}" if self.line else self.where
        return f"{at}  {self.what}" if self.what else at


class Found(BaseModel):
    """One thing worth fixing, and everywhere it shows.

    **One defect is one event, however many lines it touches.** A hardcoded
    language table reported eight times is one decision reported eight times,
    and a reader handed eight items has to work out for themselves that they
    are the same item. The sites are nested under the finding because fixing
    the finding fixes all of them.
    """

    pattern: str
    why: str = Field(description="Why this is a defect rather than a curiosity")
    confidence: str = LIKELY
    sites: List[Site] = Field(default_factory=list)

    @property
    def where(self) -> str:
        return self.sites[0].where if self.sites else ""

    @property
    def line(self) -> int:
        return self.sites[0].line if self.sites else 0

    def describe(self) -> str:
        first = self.sites[0].describe() if self.sites else "(nowhere)"
        more = f" (+{len(self.sites) - 1} more)" if len(self.sites) > 1 else ""
        return f"[{self.confidence}] {self.pattern} — {first}{more}"


class Survey(BaseModel):
    """What a repository shows, unasked."""

    found: List[Found] = Field(default_factory=list)
    looked_for: List[str] = Field(default_factory=list)

    def by_pattern(self) -> Dict[str, List[Found]]:
        out: Dict[str, List[Found]] = {}
        for entry in self.found:
            out.setdefault(entry.pattern, []).append(entry)
        return out

    def describe(self) -> str:
        if not self.found:
            return f"nothing found, looking for {len(self.looked_for)} pattern(s)"
        counts = ", ".join(
            f"{len(v)} {k}" for k, v in sorted(
                self.by_pattern().items(), key=lambda kv: -len(kv[1])
            )
        )
        return f"{len(self.found)} finding(s): {counts}"


# ── The patterns ─────────────────────────────────────────────────────────
#
# Each is a function from a repository to findings. The docstring of each says
# what makes it a defect and what it deliberately does not report, because a
# pattern whose exclusions are not written down will eventually report them.


def hardcoded_language_lists(graph: Graph, root: Path, blind: Blindspot) -> List[Found]:
    """A tool that names the languages it supports cannot support another.

    A defect because the list is a ceiling: every language absent from it is one
    the tool silently cannot handle, and nothing announces the limit. This
    repository's own `SERVERS` table is the case that motivated it — a user
    said "the tool can't be specific to Python repos" and the table is exactly
    how it was.

    Not reported: a list of languages used for *display*, or a test fixture
    naming a language on purpose.
    """
    marker = re.compile(
        r"\b(languages?|suffixes?|extensions?|file_types?)\s*[=:]\s*[\[\(]",
        re.I,
    )
    # Grouped per file: eight entries in one table are one decision to enumerate
    # languages, not eight decisions.
    by_file: Dict[str, List[Site]] = {}
    for path, relative in _sources(root):
        if "test" in relative:
            continue  # a fixture naming a language is naming it on purpose
        for number, line in enumerate(_lines(path), start=1):
            if marker.search(line):
                by_file.setdefault(relative, []).append(
                    Site(where=relative, line=number, what=line.strip()[:80])
                )

    return [
        Found(
            pattern="hardcoded language list",
            why=(
                "every language not in this list is one the tool cannot handle, "
                "and nothing says so"
            ),
            confidence=LIKELY,
            sites=sites,
        )
        for sites in by_file.values()
    ]


def swallowed_failures(graph: Graph, root: Path, blind: Blindspot) -> List[Found]:
    """An error caught and discarded leaves no trace of having happened.

    A defect because the caller cannot distinguish "this did not apply" from
    "this failed" — the difference between a result and a silence. This whole
    project has hit it repeatedly: a failed preparation that cleared its own
    mark, an extraction failure that surfaced as "no check could be derived".

    Not reported: a handler that logs, re-raises, records the failure, or
    returns something naming it. Only the ones that vanish.
    """
    sites: List[Site] = []
    for path, relative in _sources(root):
        lines = list(_lines(path))
        for number, line in enumerate(lines, start=1):
            if not re.search(r"^\s*except\b", line):
                continue
            # What the handler does, up to the next dedent.
            body = []
            indent = len(line) - len(line.lstrip())
            for following in lines[number : number + 6]:
                if following.strip() and (len(following) - len(following.lstrip())) <= indent:
                    break
                body.append(following.strip())
            said = " ".join(body).lower()
            if not said:
                continue
            if any(
                word in said
                for word in ("log", "raise", "warn", "print", "record", "report",
                             "return", "append", "= ", "error", "why", "failed")
            ):
                continue
            if said in ("pass", "continue", "pass  # noqa", "..."):
                sites.append(
                    Site(where=relative, line=number, what=line.strip()[:70])
                )

    # One finding per file: a module that discards errors in four places has
    # one habit, and a reader fixes the habit.
    by_file: Dict[str, List[Site]] = {}
    for site in sites:
        by_file.setdefault(site.where, []).append(site)
    return [
        Found(
            pattern="swallowed failure",
            why=(
                "the caller cannot tell this from success; a failure that "
                "leaves no trace is indistinguishable from the case never "
                "arising"
            ),
            confidence=LIKELY,
            sites=group,
        )
        for group in by_file.values()
    ]


def unresolvable_reach(graph: Graph, root: Path, blind: Blindspot) -> List[Found]:
    """Code reached by name, which no resolver can follow.

    A defect not because dynamic access is wrong, but because it makes every
    structural claim about the code short: a propagation set, a rename, an
    impact analysis all miss these. An agent editing on the strength of a graph
    that cannot see them will miss consumers.

    Not reported: dynamic access inside tests, where it is usually the subject
    rather than an accident.
    """
    # Grouped by the name reached: five call sites reaching `why_not` are one
    # fact about `why_not`, and the reader wants the name, not five lines.
    by_name: Dict[str, List[Site]] = {}
    known: Dict[str, int] = {}
    for entry in blind.found:
        if "test" in entry.path:
            continue
        by_name.setdefault(entry.name, []).append(
            Site(where=entry.path, line=entry.line, what=entry.name)
        )
        known[entry.name] = max(known.get(entry.name, 0), len(entry.candidates))

    return [
        Found(
            pattern="reached by name only",
            why=(
                f"no resolver follows this, so every structural answer about "
                f"{name!r} is missing {len(sites)} call site(s)"
            ),
            confidence=CLEAR if known.get(name) else WORTH_A_LOOK,
            sites=sites,
        )
        for name, sites in by_name.items()
    ]


def unreachable_definitions(graph: Graph, root: Path, blind: Blindspot) -> List[Found]:
    """Code nothing refers to, which nothing will notice breaking.

    A defect because it is carried, read, and maintained while contributing
    nothing — and because it is the first place a wrong change hides, since no
    test reaches it either.

    Deliberately narrow. A first attempt reported ninety-two definitions and
    almost all were tests, which nothing *should* refer to. Entry points,
    private helpers, and anything a dynamic reference could reach are excluded
    too, so what remains is genuinely unreferenced.
    """
    reachable_by_name = {entry.name for entry in blind.found}
    by_file: Dict[str, List[Site]] = {}
    for node in graph.nodes.values():
        if graph.referenced_by(node.id):
            continue
        if is_test(node) or "test" in node.path:
            continue  # nothing refers to a test, by design
        if node.name.startswith("_") or node.name in ("main", "__init__"):
            continue  # private helpers and entry points
        if node.name in reachable_by_name:
            continue  # something reaches it by name; the graph just cannot see
        if node.container:
            continue  # a method may be reached through its class
        by_file.setdefault(node.path, []).append(
            Site(where=node.path, line=node.line + 1, what=node.qualified)
        )

    return [
        Found(
            pattern="nothing refers to this",
            why=(
                "carried and maintained while contributing nothing, and no test "
                "reaches it, so a wrong change here is invisible"
            ),
            confidence=WORTH_A_LOOK,
            sites=sites,
        )
        for sites in by_file.values()
    ]


PATTERNS: Tuple[Tuple[str, Callable], ...] = (
    ("hardcoded language list", hardcoded_language_lists),
    ("swallowed failure", swallowed_failures),
    ("reached by name only", unresolvable_reach),
    ("nothing refers to this", unreachable_definitions),
)


def _sources(root: Path) -> Iterable[Tuple[Path, str]]:
    for path in sorted(root.rglob("*.py")):
        if any(p in (".venv", ".git", "__pycache__", ".vesta") for p in path.parts):
            continue
        yield path, str(path.relative_to(root))


def _lines(path: Path) -> List[str]:
    try:
        return path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []


def survey(graph: Graph, root: Path | str, only: Optional[Sequence[str]] = None) -> Survey:
    """Look for everything worth fixing, without being asked."""
    root = Path(root).expanduser().resolve()
    blind = scan(root, graph)
    found = Survey()

    for name, look in PATTERNS:
        if only and name not in only:
            continue
        found.looked_for.append(name)
        try:
            found.found.extend(look(graph, root, blind))
        except Exception as exc:  # noqa: BLE001 - one bad pattern is not a survey
            logger.warning("pattern %s failed: %s", name, exc)

    order = {CLEAR: 0, LIKELY: 1, WORTH_A_LOOK: 2}
    found.found.sort(key=lambda f: (order.get(f.confidence, 3), f.where, f.line))
    return found
