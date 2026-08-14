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
from .home import NOT_THE_PROJECT
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


def _decorated(root: Path) -> Set[Tuple[str, str]]:
    """Definitions a decorator registers, as `(path, name)`.

    **A decorator is a reference.** `@app.get("/health")` hands the function to
    something that will call it later, which is exactly why nothing calls it by
    name — and a resolver following call edges sees a definition nobody
    mentions.

    Found on a real codebase: sixteen FastAPI routes in one file reported as
    "nothing refers to this", every one of them live and serving. Sixteen of
    seventeen findings for that component were this single blind spot, which
    is how a survey teaches somebody to skim past it.

    Bare `@property` and `@staticmethod` are not registrations — they modify a
    definition that is still reached the ordinary way — so they do not exempt
    anything. What counts is a decorator that *takes* the function somewhere:
    an attribute call like `@app.get(...)`, or a name the module imported.
    """
    import ast

    found: Set[Tuple[str, str]] = set()
    plain = {"property", "staticmethod", "classmethod", "abstractmethod",
             "cached_property", "override", "dataclass"}

    for path, relative in _sources(root):
        try:
            tree = ast.parse("\n".join(_lines(path)))
        except (SyntaxError, ValueError):
            continue
        for node in ast.walk(tree):
            if not isinstance(
                node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
            ):
                continue
            for mark in node.decorator_list:
                said = mark.func if isinstance(mark, ast.Call) else mark
                if isinstance(said, ast.Attribute):
                    found.add((relative, node.name))  # @app.get(...)
                elif isinstance(said, ast.Name) and said.id not in plain:
                    found.add((relative, node.name))  # @register, @tool
    return found


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
    registered = _decorated(root)
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
        if (node.path, node.name) in registered:
            continue  # a decorator registered it; that *is* the reference
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


def _module_files(
    root: Path, module: str, near: Optional[Path] = None, level: int = 1
) -> List[Path]:
    """The file a relative import names, resolved the way Python resolves it.

    Two things this has to get right, and each was wrong in its own way.

    **A module is a `<module>.py` or a package** — a directory holding an
    `__init__.py`. Matching only file stems meant every package looked deleted:
    on a codebase built as a façade, nine `from ..core import …` lines were
    reported as "no such module" while `core/__init__.py` sat there exporting
    every name. That is the most alarming thing this survey says — "raises the
    moment the line runs" — and it was wrong about all nine.

    **And `from .base import X` means the sibling `base`, not any `base`.**
    Two files called `base.py` in different packages made resolution return
    whichever was found first, so imports from one were checked against the
    other's contents. `near` and `level` say where the import was written and
    how many dots it used, which is the only thing that makes the answer
    unambiguous.

    Without `near` this falls back to matching anywhere, which is what callers
    that have no importing file can ask for.
    """
    candidates = []
    for path, _ in _sources(root):
        if path.stem == module and path.name != "__init__.py":
            candidates.append(path)
        elif path.name == "__init__.py" and path.parent.name == module:
            candidates.append(path)

    if near is None or len(candidates) < 2:
        return candidates

    # `.x` is a sibling of the importing file; `..x` a sibling of its parent,
    # and so on. Anything else in the tree with the same name is a different
    # module that happens to share a name.
    where = near.parent
    for _ in range(max(level - 1, 0)):
        where = where.parent

    exact = [p for p in candidates if p.parent == where or p.parent.parent == where]
    return exact or candidates


def _named_in(
    root: Path, module: str, near: Optional[Path] = None, level: int = 1
) -> set:
    """Every name a module of this package defines at the top level.

    For a package this reads its `__init__.py`, which is exactly where a
    façade declares its surface — and re-exports count, so `from .document
    import Document` there makes `Document` a name `from ..core import
    Document` correctly finds.

    `near` and `level` are where the import was written and how many dots it
    used, so that two modules sharing a name resolve to the right one.
    """
    import ast

    for path in _module_files(root, module, near=near, level=level):
        try:
            tree = ast.parse("\n".join(_lines(path)))
        except (SyntaxError, ValueError):
            return set()  # unparseable: claim nothing rather than claim wrongly

        found = set()
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                found.add(node.name)
            elif isinstance(node, ast.Assign):
                found.update(
                    target.id for target in node.targets if isinstance(target, ast.Name)
                )
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                found.add(node.target.id)
            elif isinstance(node, (ast.Import, ast.ImportFrom)):
                # Re-exported: `from .x import y` in a module makes `y` a name
                # that module supplies, and importing it from there is fair.
                found.update(
                    alias.asname or alias.name.split(".")[0] for alias in node.names
                )
        return found
    return set()


def calls_to_nothing(graph: Graph, root: Path, blind: Blindspot) -> List[Found]:
    """Code that calls or imports something which no longer exists.

    The inverse of `nothing refers to this`, and the one this repository kept
    suffering while the survey said it was clean. A deletion leaves the call
    behind: `_load_env` went with the theory half, `judge` and `sift` with the
    move to host inference, and each survived at its call site. The CLI and
    then the whole MCP server died on the first line, and every tool went
    missing with no message saying why.

    **A reference graph cannot see this.** An unresolvable name resolves to no
    node, so it creates no edge — it is absent from the graph rather than
    present-and-unreferenced. Nothing that reasons over edges will ever find
    it. So this reads the syntax instead, which is where the evidence is.

    Deliberately narrow, for the same reason the unreachable check is. Only
    module-level `from . import x` and calls to plain names defined nowhere in
    the file, the module, or the builtins are reported. Attributes, dynamic
    lookups and star-imports are left alone: a false "this does not exist"
    about working code would make the whole survey untrustworthy.
    """
    import ast
    import builtins

    known_builtins = set(dir(builtins))
    by_file: Dict[str, List[Site]] = {}

    # Every module this package holds, so a `from .x import y` naming a deleted
    # module is caught as surely as a call to a deleted function.
    #
    # Packages count. A stem-only set contains no directory, so every façade
    # package read as deleted — the failure that made this detector report
    # nine imports of live code as raising on the first line.
    modules = {path.stem for path, _ in _sources(root)}
    modules |= {
        path.parent.name
        for path, _ in _sources(root)
        if path.name == "__init__.py"
    }

    for path, relative in _sources(root):
        try:
            # `_sources` yields the path and its name, not its text; the lines
            # are cached separately because every pattern reads every file.
            tree = ast.parse("\n".join(_lines(path)))
        except (SyntaxError, ValueError):
            continue

        defined: set = set(known_builtins)
        imported_from: List[Tuple[str, str, int, int]] = []

        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                defined.add(node.name)
            elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
                defined.add(node.id)
            elif isinstance(node, ast.arg):
                defined.add(node.arg)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    defined.add(alias.asname or alias.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    defined.add(alias.asname or alias.name)
                # A relative import: the module must exist, and so must each
                # name taken from it. `from .rules import judge` kept `judge`
                # defined in this file long after `rules` stopped defining it,
                # which is why checking calls alone missed it.
                if node.level and node.module and "." not in node.module:
                    for alias in node.names:
                        imported_from.append(
                            (node.module, alias.name, node.lineno, node.level)
                        )
            elif isinstance(node, ast.alias):
                defined.add(node.asname or node.name.split(".")[0])

        sites: List[Site] = []

        for module, what, line, level in imported_from:
            if module not in modules:
                sites.append(
                    Site(
                        where=relative,
                        line=line,
                        what=f"from .{module} import {what} — no such module",
                    )
                )
            elif what != "*" and what not in _named_in(
                root, module, near=path, level=level
            ):
                sites.append(
                    Site(
                        where=relative,
                        line=line,
                        what=f"from .{module} import {what} — {module} has no {what}",
                    )
                )

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
                continue
            if node.func.id in defined:
                continue
            sites.append(
                Site(
                    where=relative,
                    line=node.lineno,
                    what=f"{node.func.id}() — defined nowhere in this module",
                )
            )

        if sites:
            by_file.setdefault(relative, []).extend(sites)

    return [
        Found(
            pattern="calls something that does not exist",
            why=(
                "this raises the moment the line runs, and a reference graph "
                "cannot see it: an unresolvable name makes no edge to follow"
            ),
            confidence=LIKELY,
            sites=sites,
        )
        for sites in by_file.values()
    ]


def is_test_path(relative: str) -> bool:
    """Whether a path is test code rather than something that ships."""
    low = relative.lower()
    return (
        low.startswith("test")
        or "/test" in low
        or low.endswith("_test.py")
        or "/tests/" in low
    )


def reached_only_by_tests(graph: Graph, root: Path, blind: Blindspot) -> List[Found]:
    """Code that only its tests call.

    The defect this repository kept shipping. An offer is written, a test calls
    it directly, and the one place that had to call it does not — so the tests
    are green, nothing is unreferenced, and the feature is dead in production.
    It happened twice while building the automation, and both times a live run
    found it rather than the suite.

    **The reference graph cannot see it.** `nothing refers to this` asks whether
    anything refers to a definition, and something does: the test. The question
    that matters is whether anything refers to it *from the code that ships*,
    which is a different question and needs the answer split by where the
    caller lives.

    Narrow on purpose. A test helper is reached only by tests and should be; so
    is a fixture, and so is anything a test was written to exercise before its
    caller exists. What is reported is a definition in shipped code that only
    test code calls — the shape of a feature nobody wired up.
    """
    import ast

    from .propagate import is_test

    # Names that shipped code imports, under whatever name it imports them.
    # `from .traverse import where as where_in` makes `where` used, and the
    # graph records the call against `where_in`. Without this the detector
    # reports every aliased import as dead, and a detector that is wrong more
    # often than right is one nobody reads.
    imported: set = set()
    for path, relative in _sources(root):
        if is_test_path(relative):
            continue
        try:
            tree = ast.parse("\n".join(_lines(path)))
        except (SyntaxError, ValueError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.Attribute):
                # `sidecar._does(...)` reaches `_does` without a plain call.
                imported.add(node.attr)
            elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
                # Named as a value rather than called: registered in a table,
                # passed as a callback, assigned to a name. Putting a function
                # in a dispatch table is using it, and a detector that misses
                # that reports every plugin architecture as dead code.
                imported.add(node.id)

    shipped: Dict[str, List[Site]] = {}

    for node in graph.nodes.values():
        if is_test(node) or "test" in node.path:
            continue  # a test is allowed to be called only by tests
        if node.name.startswith("_") and node.name.startswith("__"):
            continue
        if node.name in ("main", "__init__"):
            continue
        if node.container:
            continue  # a method may be reached through its class

        referring = graph.referenced_by(node.id)
        if not referring:
            continue  # that is `nothing refers to this`, not this

        callers = [graph.nodes.get(edge.source) for edge in referring]
        callers = [c for c in callers if c is not None]
        if not callers:
            continue
        if any(not (is_test(c) or "test" in c.path) for c in callers):
            continue  # something that ships calls it; nothing to say
        if node.name in imported:
            continue  # shipped code imports or reaches it by attribute

        shipped.setdefault(node.path, []).append(
            Site(
                where=node.path,
                line=node.line + 1,
                what=f"{node.qualified} — only {len(callers)} test(s) call it",
            )
        )

    return [
        Found(
            pattern="only its tests call this",
            why=(
                "the tests are green and the feature is dead: something that "
                "ships was written, tested, and never wired up"
            ),
            confidence=LIKELY,
            sites=sites,
        )
        for sites in shipped.values()
    ]


def constants_nobody_reads(graph: Graph, root: Path, blind: Blindspot) -> List[Found]:
    """A module-level constant nothing refers to.

    Invisible to everything else here. A language server reports functions and
    classes as symbols and mostly does not report assignments, so a constant
    sits outside the graph entirely — `nothing refers to this` cannot see it,
    because it is not a definition the graph holds. And `calls something that
    does not exist` looks the other way: at names used and missing, not names
    defined and unused.

    Found the hard way. `SHARPER = "anthropic/claude-sonnet-4-5"` survived the
    removal of the code that used it, sat in the module for weeks, and was
    noticed by a person reading the file rather than by any check. It was also
    a *wrong* value by then — a model choice nobody had made — which is what
    makes a stale constant worse than a stale function: it reads as a decision.
    """
    import ast

    by_file: Dict[str, List[Site]] = {}

    for path, relative in _sources(root):
        if is_test_path(relative):
            continue
        try:
            tree = ast.parse("\n".join(_lines(path)))
        except (SyntaxError, ValueError):
            continue

        # Named at module level, in the way a constant is named.
        declared: Dict[str, int] = {}
        for node in tree.body:
            targets = []
            if isinstance(node, ast.Assign):
                targets = [t for t in node.targets if isinstance(t, ast.Name)]
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                targets = [node.target]
            for target in targets:
                if target.id.isupper() and len(target.id) > 2:
                    declared[target.id] = node.lineno

        if not declared:
            continue

        # Read anywhere in this file, or named anywhere else in the tree. A
        # constant is usually imported by name, so a mention elsewhere counts
        # however it is used.
        read = {
            node.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)
        }
        elsewhere = set()
        for other, other_relative in _sources(root):
            if other == path:
                continue
            text = "\n".join(_lines(other))
            for name in declared:
                if name in text:
                    elsewhere.add(name)

        for name, line in sorted(declared.items()):
            if name in read or name in elsewhere:
                continue
            by_file.setdefault(relative, []).append(
                Site(where=relative, line=line, what=f"{name} — nothing reads it")
            )

    return [
        Found(
            pattern="a constant nobody reads",
            why=(
                "carried and maintained while deciding nothing, and a stale "
                "one reads as a decision somebody made"
            ),
            confidence=LIKELY,
            sites=sites,
        )
        for sites in by_file.values()
    ]


PATTERNS: Tuple[Tuple[str, Callable], ...] = (
    ("hardcoded language list", hardcoded_language_lists),
    ("swallowed failure", swallowed_failures),
    ("reached by name only", unresolvable_reach),
    ("nothing refers to this", unreachable_definitions),
    ("calls something that does not exist", calls_to_nothing),
    ("only its tests call this", reached_only_by_tests),
    ("a constant nobody reads", constants_nobody_reads),
)


# The tree, listed once. Every pattern walks it, and `rglob` over a repository
# with a virtualenv in it is not free — four patterns each paying for their own
# walk was most of the cost of a survey.
_LISTED: Dict[str, Tuple[float, List[Tuple[Path, str]]]] = {}
_LIST_TTL = 30.0


def _sources(root: Path) -> Iterable[Tuple[Path, str]]:
    import time as _time

    held = _LISTED.get(str(root))
    if held and _time.time() - held[0] < _LIST_TTL:
        return held[1]

    from .home import walk

    found = [(path, str(path.relative_to(root))) for path in walk(root, ".py")]
    _LISTED[str(root)] = (_time.time(), found)
    return found


# Files already read, keyed by path and modification time. Every pattern reads
# every file, so a survey of six patterns over forty files was two hundred and
# forty reads of the same text — five seconds where the graph itself takes a
# twentieth of one.
_READ: Dict[str, Tuple[float, List[str]]] = {}


def _lines(path: Path) -> List[str]:
    key = str(path)
    try:
        when = path.stat().st_mtime
    except OSError:
        return []

    held = _READ.get(key)
    if held and held[0] == when:
        return held[1]

    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    _READ[key] = (when, lines)
    return lines


def survey(
    graph: Graph,
    root: Path | str,
    only: Optional[Sequence[str]] = None,
    trust_for: float = 0.0,
) -> Survey:
    """Look for everything worth fixing, without being asked."""
    root = Path(root).expanduser().resolve()
    # `trust_for` on the dynamic scan too: re-walking the tree to prove the
    # scan is current cost nearly two seconds inside a call that has none.
    blind = scan(root, graph, trust_for=trust_for)
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
