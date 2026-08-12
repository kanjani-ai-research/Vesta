"""The ontology of what a repository is for, derived from the repository.

`traverse` can cross between code and concept but has nothing to cross to: it
reads an ontology from a file and nothing produces one. This produces it, by
asking Metis what the work in this codebase actually is.

**The purpose has to be narrow, and this is the whole difficulty.** A broad
purpose labels everything and partitions nothing — an earlier measurement had a
general software-development ontology attaching "check for code duplication" to
`class Collection:` at 0.70 confidence, which is a domain model saying words
rather than knowing anything. The purpose given to Metis is therefore built from
the repository's own vocabulary: what it names, what it says it does, what its
modules are for. A purpose derived from the thing it describes cannot be broader
than the thing.

**Grounding is what the codebase says about itself.** Module docstrings are the
most reliable statement of intent a repository contains — somebody wrote them to
explain the file to a reader — and they are what a person would read first.
Passing them as grounding means the ontology names activities this project
performs, rather than activities software projects perform in general.

**An ontology is derived once and kept.** It costs real model work, and it
changes when the repository's purpose changes, not when a line moves. Rebuilt on
demand or when the modules it was derived from have changed substantially.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from pydantic import BaseModel, Field

from .graph import Graph
from .home import VESTA_HOME

logger = logging.getLogger("vesta.domain")

# Where a repository's ontology is kept.
ONTOLOGIES = VESTA_HOME / "ontologies"

# How many module docstrings to ground the analysis in. Enough to describe the
# project, few enough that the purpose stays about the project rather than
# becoming a summary of everything in it.
GROUNDING = 14

# How much of each. A docstring's opening paragraph says what a module is for;
# the rest is usually why it was built that way.
GROUNDING_CHARS = 700


class Ontology(BaseModel):
    """What a repository's work is, as named things."""

    project: str = ""
    purpose: str = ""
    terms: List[Dict[str, str]] = Field(default_factory=list)
    # What the modules looked like when this was derived. An ontology describes
    # a purpose, which changes far more slowly than the code, so this is a
    # coarse mark rather than a content hash.
    modules: str = ""
    derived_at: float = 0.0

    def describe(self) -> str:
        kinds: Dict[str, int] = {}
        for term in self.terms:
            kinds[term.get("kind", "?")] = kinds.get(term.get("kind", "?"), 0) + 1
        counted = ", ".join(f"{n} {k}" for k, n in sorted(kinds.items()))
        return f"{len(self.terms)} term(s): {counted}" if counted else "no terms"


def _speaks(root: Path, limit: int = GROUNDING) -> List[Tuple[str, str]]:
    """What this repository says about itself, module by module.

    Docstrings rather than names: a name is a label and a docstring is a
    statement of intent, and the difference is exactly what an ontology derived
    from names would miss.
    """
    said: List[Tuple[str, int, str]] = []
    for path in sorted(root.rglob("*.py")):
        if any(p in (".venv", ".git", "__pycache__", ".vesta") for p in path.parts):
            continue
        if path.name.startswith("test_") or "test" in path.parts:
            continue  # a test describes a test, not the work
        try:
            body = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        opening = re.match(r'\s*(?:"""|\'\'\')(.+?)(?:"""|\'\'\')', body, re.S)
        if not opening:
            continue
        text = " ".join(opening.group(1).split())[:GROUNDING_CHARS]
        if len(text) > 80:
            said.append((str(path.relative_to(root)), len(body), text))

    # The largest modules first: a project's purpose is carried by the files
    # that do most of the work, not by its smallest helper.
    said.sort(key=lambda item: -item[1])
    return [(where, text) for where, _, text in said[:limit]]


def _purpose_from(root: Path, said: Sequence[Tuple[str, str]]) -> str:
    """A purpose statement narrow enough to partition this repository.

    Built from the repository rather than chosen: "a tool for software
    development" would attach to everything, and an ontology attaching to
    everything separates nothing.
    """
    opening = said[0][1] if said else ""
    first = opening.split(".")[0][:200] if opening else root.name
    modules = ", ".join(where.rsplit("/", 1)[-1][:-3] for where, _ in said[:8])
    return (
        f"The work performed by the {root.name} codebase, whose own description "
        f"begins: {first}. Its modules are {modules}. Name the activities this "
        "codebase performs and the things it performs them on — not software "
        "development in general, and not activities it does not perform."
    )


def _mark(root: Path, said: Sequence[Tuple[str, str]]) -> str:
    return hashlib.sha256(
        "\n".join(f"{where}:{len(text)}" for where, text in said).encode("utf-8")
    ).hexdigest()[:16]


def _where(root: Path) -> Path:
    """Where a repository's ontology is kept.

    One naming rule, shared with maps, rules and patterns. Two of them resolved
    the path and two did not, so a repository reached by `/tmp/x` and the same
    one reached by `/private/tmp/x` kept their records in different places and
    each read back nothing.
    """
    from .home import kept_at

    return kept_at(root, "ontologies")


def recall(repo: Path | str) -> Optional[Ontology]:
    """The ontology already derived for this repository, if it still applies."""
    root = Path(repo).expanduser().resolve()
    path = _where(root)
    if not path.is_file():
        return None
    try:
        held = Ontology.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if held.modules and held.modules != _mark(root, _speaks(root)):
        logger.info("the ontology for %s predates its current modules", root)
    return held


def as_terms(ontology: Ontology) -> List:
    """The ontology as `traverse` wants it."""
    from .traverse import Term

    return [
        Term(id=t["id"], kind=t.get("kind", ""), label=t["label"])
        for t in ontology.terms
        if t.get("label")
    ]
