"""The join: from a definition to what it is *about*, and back.

A code graph says `Session.references` is called by `_resolve_with`. It cannot
say that both are *resolving symbols*, that resolution is what the propagation
claim rests on, or that there is a literature about it. An ontology says what
the activities in a domain are and how they relate. Neither alone is traversable
in the sense that matters: you can walk the code and learn structure, or walk
the ontology and learn vocabulary, and never cross between them.

This crosses. A definition is attached to the ontology terms its name and
context match, so a question can start at a concept and arrive at code, or start
at code and arrive at the theory about it.

**Attachment is evidence, not truth.** A name is a weak signal about meaning —
`build` appears in every codebase and means something different in each — so an
attachment carries how it was made and how strongly, and a caller can discount
it. The alternative, asserting that a definition *is* an activity because two
strings overlap, is how a domain model comes to label code confidently and
wrongly. That failure is on record: a broad ontology labelled `class Collection:`
as "check for code duplication" at 0.70 confidence.

**Nothing is attached without a threshold being cleared.** An ontology that
attaches to everything partitions nothing, and a map where every road leads
everywhere is not a map.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

from pydantic import BaseModel, Field

from .graph import Graph, Node

logger = logging.getLogger("vesta.traverse")

# How much of a term's vocabulary a definition must show. Names are short, so
# this is looser than document relevance — but a single shared common word must
# never be enough, which is what the floor enforces.
ENOUGH = 0.5

# Words that appear in every codebase and say nothing about what a definition
# is for. Matching on these is how `build` in one project gets attached to
# "build a covering array" in another.
EVERYWHERE = {
    "get", "set", "add", "put", "run", "call", "make", "new", "init", "main",
    "data", "value", "values", "item", "items", "list", "dict", "map", "type",
    "name", "id", "key", "index", "count", "size", "text", "file", "path",
    "test", "check", "handle", "process", "update", "create", "delete", "read",
    "write", "load", "save", "open", "close", "start", "stop", "self", "cls",
    "the", "and", "for", "with", "from", "into", "when", "that", "this",
}


class Term(BaseModel):
    """One thing an ontology names."""

    id: str
    kind: str = Field(description="domain, activity, role, or whatever the ontology uses")
    label: str

    @property
    def words(self) -> Set[str]:
        return {
            word
            for word in re.findall(r"[a-z0-9]+", self.label.lower())
            if len(word) > 2 and word not in EVERYWHERE
        }


class Attachment(BaseModel):
    """A definition and a term it appears to be about."""

    node: str
    term: str
    label: str
    kind: str
    strength: float
    # How it was made. Recorded because a caller weighing an attachment needs to
    # know whether a name matched or a whole file did.
    how: str = "name"

    def describe(self, graph: Graph) -> str:
        node = graph.nodes.get(self.node)
        where = node.describe() if node else self.node
        return f"{where} — {self.label} ({self.kind}, {self.strength:.2f})"


class Map(BaseModel):
    """A repository's code, seen through an ontology.

    Both directions are held, because the two questions are opposites: what is
    this code about, and where in this codebase is that idea.
    """

    ontology: str = ""
    attachments: List[Attachment] = Field(default_factory=list)
    # Terms that matched nothing. Kept because they are the more interesting
    # half: an ontology term with no code is either something the project has
    # not built or something it calls by another name, and both are worth
    # seeing.
    unattached: List[str] = Field(default_factory=list)

    def for_node(self, node_id: str) -> List[Attachment]:
        return [a for a in self.attachments if a.node == node_id]

    def for_term(self, term_id: str) -> List[Attachment]:
        return [a for a in self.attachments if a.term == term_id]

    @property
    def covered(self) -> Set[str]:
        return {a.node for a in self.attachments}

    def describe(self, graph: Optional[Graph] = None) -> str:
        parts = [f"{len(self.attachments)} attachment(s)"]
        if graph:
            parts.append(f"{len(self.covered)} of {len(graph.nodes)} definitions")
        if self.unattached:
            parts.append(f"{len(self.unattached)} term(s) matched nothing")
        return ", ".join(parts)


def read_ontology(path: Path | str) -> List[Term]:
    """The terms in an ontology, whatever else it carries."""
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    graph = payload.get("graph") or payload
    return [
        Term(id=n["id"], kind=n.get("kind", ""), label=n.get("label", ""))
        for n in graph.get("nodes", [])
        if n.get("label")
    ]


def _words_of(node: Node) -> Set[str]:
    """What a definition's name says about it.

    Identifiers are compound: `build_extractor`, `SessionReferences`, `t_way`.
    Split on case and separators, because the parts carry the meaning and the
    whole matches nothing.
    """
    spelled = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", f"{node.container} {node.name}")
    return {
        word
        for word in re.findall(r"[a-z0-9]+", spelled.lower())
        if len(word) > 2 and word not in EVERYWHERE
    }


def attach(
    graph: Graph,
    terms: Sequence[Term],
    floor: float = ENOUGH,
    ontology: str = "",
) -> Map:
    """Attach definitions to the terms they appear to be about.

    Matched on the words a name is made of rather than the whole string, since
    an identifier is a compressed phrase. The strength is the share of the
    term's own vocabulary that the definition uses, so a long specific term
    needs more overlap than a short one to clear the same floor.
    """
    found = Map(ontology=ontology)
    matched: Set[str] = set()

    by_node = {node.id: _words_of(node) for node in graph.nodes.values()}

    # How often each word appears across the repository's own identifiers. A
    # word used by many definitions cannot distinguish one of them.
    common: Dict[str, int] = {}
    for spoken in by_node.values():
        for word in spoken:
            common[word] = common.get(word, 0) + 1
    spread = max(3, len(by_node) // 100)

    for term in terms:
        wanted = term.words
        if not wanted:
            continue
        hit = False
        for node_id, spoken in by_node.items():
            if not spoken:
                continue
            shared = wanted & spoken
            if not shared:
                continue
            # Scored both ways, and the stronger direction wins.
            #
            # Share of the *term* alone was wrong: a five-word activity can
            # never be matched by a two-word identifier, so "resolve symbol
            # references across a codebase" attached to nothing in a repository
            # whose `_resolve_with` and `Session.references` are exactly that.
            # An identifier is a compressed phrase — when every word of it
            # appears in the term, that is strong evidence regardless of how
            # many words the term adds.
            # One shared word can carry an attachment, but only if that word is
            # rare in this repository. Scoring by name-share alone let a
            # one-word identifier match anything containing it at full
            # confidence: `Coverage`, about which files a language server
            # resolved, attached to "create extended covering arrays" at 1.00.
            # Requiring two words instead killed the true matches, because
            # `_resolve_with` really is "resolve symbol references".
            #
            # What separates them is how much the word narrows *this* codebase:
            # "coverage" is everywhere here, "resolve" is not.
            if len(shared) < 2:
                only = next(iter(shared))
                if common.get(only, 0) > spread:
                    continue
            strength = max(len(shared) / len(wanted), len(shared) / len(spoken))
            if strength < floor:
                continue
            found.attachments.append(
                Attachment(
                    node=node_id,
                    term=term.id,
                    label=term.label,
                    kind=term.kind,
                    strength=round(strength, 2),
                )
            )
            hit = True
        if not hit:
            found.unattached.append(term.label)

    found.attachments.sort(key=lambda a: -a.strength)
    return found


def about(graph: Graph, mapped: Map, node_id: str) -> List[Attachment]:
    """What a definition is about. Code → concept."""
    return sorted(mapped.for_node(node_id), key=lambda a: -a.strength)


def _bag(text: str) -> Set[str]:
    """The words in a phrase that carry any meaning."""
    return {
        word
        for word in re.findall(r"[a-z0-9]+", text.lower())
        if len(word) > 2 and word not in EVERYWHERE
    }


def where(
    graph: Graph, mapped: Map, phrase: str, limit: int = 12
) -> List[Attachment]:
    """Where an idea lives in this codebase. Concept → code.

    Matched against the ontology's own labels rather than against the code, so
    a caller can ask in the vocabulary of the domain and be answered in the
    vocabulary of the repository — which is the crossing this exists for.

    **A label is not the only way the work is named.** An ontology says a
    definition *scores how closely two texts overlap*; the definition is called
    `closeness` and sits in `search.py`. Someone asking about "fuzzy search"
    shares no word with the label and two with the code. Both surfaces are
    matched, the label counting for more, because the label is what something
    decided the definition does and the name is what somebody typed.

    What this still cannot do is cross a synonym neither surface contains.
    Nothing here guesses at one: a word-overlap score that starts inventing
    relations is a score that starts being wrong quietly. Where the vocabulary
    genuinely differs, the asking agent knows both phrasings and can ask again.
    """
    wanted = _bag(phrase)
    if not wanted:
        return []

    scored: List[Tuple[float, Attachment]] = []
    for attachment in mapped.attachments:
        label = _bag(attachment.label)
        overlap = len(wanted & label) / len(wanted) if label else 0.0

        # The definition's own name and file, which name the same work in the
        # vocabulary of whoever wrote it. Worth less than the label: a file
        # called `search.py` holds a dozen definitions and says something
        # weaker about each than a sentence written about one.
        node = graph.nodes.get(attachment.node)
        if node is not None:
            in_code = _bag(node.name) | _bag(node.path.replace("/", " "))
            spoken = len(wanted & in_code) / len(wanted)
            overlap = max(overlap, spoken * 0.6)

        if overlap:
            scored.append((overlap * attachment.strength, attachment))

    scored.sort(key=lambda pair: -pair[0])
    return [attachment for _, attachment in scored[:limit]]


def neighbours(graph: Graph, mapped: Map, node_id: str, limit: int = 10) -> List[Node]:
    """Definitions that share a concept with this one.

    The traversal the code graph cannot do: two functions that never call each
    other, in different files, doing the same kind of work. A reference graph
    says they are unrelated; the ontology says they are the same activity.
    """
    terms = {a.term for a in mapped.for_node(node_id)}
    if not terms:
        return []

    kin: Dict[str, float] = {}
    for attachment in mapped.attachments:
        if attachment.term in terms and attachment.node != node_id:
            kin[attachment.node] = max(kin.get(attachment.node, 0.0), attachment.strength)

    ordered = sorted(kin.items(), key=lambda pair: -pair[1])
    return [graph.nodes[n] for n, _ in ordered[:limit] if n in graph.nodes]


# ── Attaching by reading, not by matching ────────────────────────────────




def _body_of(node: Node, root: Path, lines: int = 26) -> str:
    """A definition's own words: its signature and its docstring."""
    path = root / node.path
    try:
        text = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ""
    return "\n".join(f"    {line}" for line in text[node.line : node.line + lines])


def keep(mapped: Map, repo: Path | str) -> Path:
    """Write a map, because reading a repository costs a call per definition."""
    import hashlib

    from .home import home

    from .home import kept_at

    path = kept_at(repo, "maps")
    path.write_text(mapped.model_dump_json(), encoding="utf-8")
    return path


def recall(repo: Path | str) -> Optional[Map]:
    """The map already read for this repository, if there is one."""
    import hashlib

    from .home import home

    from .home import kept_at

    path = kept_at(repo, "maps")
    if not path.is_file():
        return None
    try:
        return Map.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
