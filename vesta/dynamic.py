"""References a language server cannot see.

`getattr(search, "why_not")` reaches a definition as surely as `search.why_not`,
and no language server resolves it: the attribute is a string literal, decided
at runtime as far as the type system is concerned. A graph built only from
resolved references is therefore *incomplete in a way it does not announce*,
which is the failure this whole project is shaped against.

**Found by a live agent, not by a test.** Asked what a change to `Search.for_`
would affect, an agent compared the graph against a harvested note, saw the
graph report two consumers of `why_not` where the note claimed five, and
grepped:

    "A getattr with a string literal is invisible to a language server, so
     those edges genuinely wouldn't appear here. Let me verify they exist
     rather than trust either source."

The note was right and the graph was short.

**These are reported as holes, not repaired as edges.** A textual match on an
attribute name is not resolution: two classes may both have `why_not`, and this
cannot say which one a call reaches. Manufacturing an edge from a guess would
put unverified structure into a graph whose value is that its edges are
verified. What it can honestly say is "there are references here that I could
not resolve, at these lines" — which is the difference between a claim that is
short and a claim that is short *and says so*.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

from pydantic import BaseModel, Field

from .graph import Graph

logger = logging.getLogger("vesta.dynamic")

# Ways a name is reached without naming it in a resolvable position. Each
# captures the attribute as a string literal, which is the only case that can
# be found textually with any confidence — a name held in a variable cannot be
# recovered without running the program.
REACHES = (
    # getattr(obj, "name") / hasattr / setattr
    re.compile(r"\b(?:get|has|set)attr\s*\(\s*[^,)]+,\s*[\"']([A-Za-z_]\w*)[\"']"),
    # obj.__dict__["name"] and friends
    re.compile(r"__dict__\s*\[\s*[\"']([A-Za-z_]\w*)[\"']\s*\]"),
    # operator.attrgetter("name")
    re.compile(r"attrgetter\s*\(\s*[\"']([A-Za-z_]\w*)[\"']"),
    # a dispatch table keyed by name: {"name": ...} is too common to include,
    # so only explicit method lookup by string is taken.
    re.compile(r"\bgetattr\s*\(\s*self\s*,\s*[\"']([A-Za-z_]\w*)[\"']"),
)

# Files not worth scanning, matching what the graph itself skips.
IGNORED = (".venv", "node_modules", ".git", "target", "__pycache__", ".vesta")

# Suffixes worth scanning. Deliberately broad: dynamic access is a property of
# many languages, and a textual scan does not need a parser.
SOURCE = (".py", ".rb", ".js", ".ts", ".php", ".lua", ".pl", ".ex", ".exs")


class Unresolved(BaseModel):
    """A reference that reaches a name without a resolvable path to it."""

    path: str
    line: int
    name: str
    how: str = "getattr"
    # Definitions in the graph that carry this name. Candidates, not an answer:
    # a textual match cannot say which one is reached.
    candidates: List[str] = Field(default_factory=list)

    def describe(self) -> str:
        where = f"{self.path}:{self.line}"
        if not self.candidates:
            return f"{where} reaches {self.name!r} — no definition of that name"
        if len(self.candidates) == 1:
            return f"{where} reaches {self.name!r} — probably {self.candidates[0]}"
        return (
            f"{where} reaches {self.name!r} — one of "
            f"{', '.join(self.candidates[:3])}"
        )


class Blindspot(BaseModel):
    """What the resolved graph could not see, for one repository."""

    found: List[Unresolved] = Field(default_factory=list)
    scanned: int = 0

    def for_name(self, name: str) -> List[Unresolved]:
        return [u for u in self.found if u.name == name]

    @property
    def is_empty(self) -> bool:
        return not self.found

    def describe(self) -> str:
        if not self.found:
            return f"no unresolvable references found in {self.scanned} file(s)"
        names = sorted({u.name for u in self.found})
        return (
            f"{len(self.found)} reference(s) the graph cannot resolve, "
            f"reaching {len(names)} name(s): {', '.join(names[:6])}"
            + (" …" if len(names) > 6 else "")
        )


# Scans already done, keyed by the state of the tree. Re-reading every source
# file took two and a half seconds on an ordinary repository, on a path that
# runs before every prompt — the one place where seconds are not available.
_SCANNED: Dict[str, Tuple[str, "Blindspot"]] = {}


def scan(
    root: Path | str, graph: Optional[Graph] = None, trust_for: float = 0.0
) -> Blindspot:
    """Find references that reach a name without a path a server can follow.

    Textual by necessity. The point is not to resolve them — that cannot be done
    honestly from source alone — but to know they exist, so a propagation claim
    can say what it may have missed.
    """
    root = Path(root).expanduser().resolve()

    from .held import GRAPH_DIR, _shape

    # On the prompt path a caller passes `trust_for`, and re-walking the tree
    # to prove the scan is current costs more than every other step combined.
    if trust_for:
        import hashlib as _h

        recent = GRAPH_DIR / f"scan-{_h.sha256(str(root).encode()).hexdigest()[:12]}.json"
        try:
            import time as _time

            if recent.is_file() and _time.time() - recent.stat().st_mtime < trust_for:
                import json as _j

                found = Blindspot.model_validate(
                    _j.loads(recent.read_text(encoding="utf-8"))["scan"]
                )
                return found
        except (OSError, ValueError, KeyError):
            pass

    state = _shape(root)
    remembered = _SCANNED.get(str(root))
    if remembered and remembered[0] == state:
        return remembered[1]

    # On disk as well as in memory. Every hook invocation is a new process, so
    # an in-memory cache is never read: the second prompt paid the full scan
    # again exactly as the first did.
    import hashlib
    import json as _json

    kept = GRAPH_DIR / f"scan-{hashlib.sha256(str(root).encode()).hexdigest()[:12]}.json"
    if kept.is_file():
        try:
            payload = _json.loads(kept.read_text(encoding="utf-8"))
            if payload.get("state") == state:
                found = Blindspot.model_validate(payload["scan"])
                _SCANNED[str(root)] = (state, found)
                return found
        except (OSError, ValueError, KeyError):
            pass

    found = Blindspot()

    by_name: Dict[str, List[str]] = {}
    if graph is not None:
        for node in graph.nodes.values():
            by_name.setdefault(node.name, []).append(
                f"{node.qualified} ({node.path}:{node.line + 1})"
            )

    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix not in SOURCE:
            continue
        if any(part in IGNORED for part in path.parts):
            continue
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue

        found.scanned += 1
        relative = str(path.relative_to(root))
        marks = ("#", "//", "*", chr(34) * 3, chr(39) * 3)
        in_prose = False
        fence = chr(34) * 3
        other = chr(39) * 3
        for number, line in enumerate(lines, start=1):
            # Prose describing dynamic access is not dynamic access. This
            # module's own docstring matched itself, which is the mildest
            # possible version of a scanner believing documentation.
            opens = line.count(fence) + line.count(other)
            if in_prose:
                if opens % 2:
                    in_prose = False
                continue
            if line.lstrip().startswith(marks):
                if opens % 2:
                    in_prose = True
                continue
            if opens % 2:
                in_prose = True
            for pattern in REACHES:
                for name in pattern.findall(line):
                    found.found.append(
                        Unresolved(
                            path=relative,
                            line=number,
                            name=name,
                            candidates=by_name.get(name, []),
                        )
                    )

    _SCANNED[str(root)] = (state, found)
    try:
        GRAPH_DIR.mkdir(parents=True, exist_ok=True)
        kept.write_text(
            _json.dumps({"state": state, "scan": found.model_dump(mode="json")}),
            encoding="utf-8",
        )
    except OSError:
        pass
    return found


def missed_by(blindspot: Blindspot, graph: Graph, node_ids: Iterable[str]) -> List[Unresolved]:
    """Unresolvable references that reach any of these definitions.

    What a propagation set may have missed. A caller told "these four tests"
    without being told "and three call sites reach this by name" has a
    correctness claim the evidence does not support.
    """
    names = {
        graph.nodes[node_id].name for node_id in node_ids if node_id in graph.nodes
    }
    return [u for u in blindspot.found if u.name in names]
