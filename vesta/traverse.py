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


def where(graph: Graph, mapped: Map, phrase: str, limit: int = 12) -> List[Attachment]:
    """Where an idea lives in this codebase. Concept → code.

    Matched against the ontology's own labels rather than against the code, so
    a caller can ask in the vocabulary of the domain and be answered in the
    vocabulary of the repository — which is the crossing this exists for.
    """
    wanted = {
        word
        for word in re.findall(r"[a-z0-9]+", phrase.lower())
        if len(word) > 2 and word not in EVERYWHERE
    }
    if not wanted:
        return []

    scored: List[Tuple[float, Attachment]] = []
    for attachment in mapped.attachments:
        label = {
            word
            for word in re.findall(r"[a-z0-9]+", attachment.label.lower())
            if len(word) > 2 and word not in EVERYWHERE
        }
        if not label:
            continue
        overlap = len(wanted & label) / len(wanted)
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


class Reading(BaseModel):
    """What a definition is about, as something that read it decided."""

    does: str = Field(
        default="",
        description="What this definition does, in one plain sentence.",
    )
    terms: List[str] = Field(
        default_factory=list,
        description=(
            "Labels from the offered vocabulary that name what this does. Only "
            "ones that genuinely apply — most definitions are about one thing "
            "or two, and a definition attached to eight terms has been attached "
            "to none of them."
        ),
    )


READING = """This is a definition from a codebase, with what it says about itself:

    {name}  ({where})
{body}

The work this codebase performs has been named as follows:

{vocabulary}

Which of those name what this definition does? Choose only labels that genuinely
apply — usually one or two, sometimes none. A definition that resolves symbols
is not "repository auditing" merely because it is in a tool that audits.

Names are not evidence. `corpus_id` returning a knowledge base identifier is
about knowledge bases whatever it is called, and a function called `build` is
about whatever it builds. Read what it says it does.
"""


def _body_of(node: Node, root: Path, lines: int = 26) -> str:
    """A definition's own words: its signature and its docstring."""
    path = root / node.path
    try:
        text = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ""
    return "\n".join(f"    {line}" for line in text[node.line : node.line + lines])


def read_in(
    graph: Graph,
    terms: Sequence[Term],
    root: Path | str,
    only: Optional[Sequence[str]] = None,
    model: Optional[str] = None,
    limit: int = 120,
) -> Map:
    """Attach definitions to terms by reading them.

    **Not by string overlap.** Matching names against labels attached
    `_resolve_with` to "resolve symbol references" because the token appears in
    both, and would have missed it entirely had it been called `harvest`. It
    also attached `Coverage` — which is about which files a language server
    read — to "create extended covering arrays", at full confidence. Three
    attempts at tuning that produced 89 attachments, then 2, then 19, none of
    them for a reason anything understood.

    What a definition says about itself is the evidence, and reading it is the
    only way to use that. Costs a call per definition, so it is bounded and
    cached.
    """
    import asyncio

    from .structure import _ensure_data_dir

    root = Path(root).expanduser().resolve()
    found = Map(ontology="read")
    _ensure_data_dir()

    try:
        from pragmatos import llm

        extract = llm.build_extractor(model=model)
    except Exception as exc:  # noqa: BLE001
        logger.info("no model available to read definitions: %s", exc)
        return found

    vocabulary = "\n".join(f"    {term.label}" for term in terms)
    by_label = {term.label.lower(): term for term in terms}

    # Public definitions first: a private helper is about whatever its caller
    # is about, and reading every one of them is most of the cost for least of
    # the meaning.
    wanted = [
        node
        for node in graph.nodes.values()
        if (only is None or node.id in only)
        and not node.name.startswith("_")
        and "test" not in node.path
    ]
    wanted.sort(key=lambda n: -len(graph.referenced_by(n.id)))
    wanted = wanted[:limit]

    async def read(node: Node):
        body = _body_of(node, root)
        if not body.strip():
            return node, None
        prompt = (
            READING.replace("{name}", node.qualified)
            .replace("{where}", f"{node.path}:{node.line + 1}")
            .replace("{body}", body)
            .replace("{vocabulary}", vocabulary)
        )
        try:
            return node, await extract(Reading, prompt)
        except Exception:  # noqa: BLE001 - one unread definition is not a failure
            return node, None

    async def run():
        return await asyncio.gather(*(read(node) for node in wanted))

    try:
        readings = asyncio.run(run())
    except Exception as exc:  # noqa: BLE001
        logger.info("could not read definitions: %s", exc)
        return found

    attached: Set[str] = set()
    already: Set[Tuple[str, str]] = set()
    for node, reading in readings:
        if reading is None:
            continue
        for label in reading.terms[:3]:
            term = by_label.get(label.strip().lower())
            if term is None:
                continue
            # One definition, one term, once. A model naming the same label
            # twice in a list is emphasis, not two attachments.
            if (node.id, term.id) in already:
                continue
            already.add((node.id, term.id))
            found.attachments.append(
                Attachment(
                    node=node.id,
                    term=term.id,
                    label=term.label,
                    kind=term.kind,
                    strength=1.0,
                    how="read",
                )
            )
            attached.add(term.id)

    found.unattached = [t.label for t in terms if t.id not in attached]
    return found


def keep(mapped: Map, repo: Path | str) -> Path:
    """Write a map, because reading a repository costs a call per definition."""
    import hashlib

    from .structure import VESTA_HOME

    root = Path(repo).expanduser().resolve()
    where_at = VESTA_HOME / "maps"
    where_at.mkdir(parents=True, exist_ok=True)
    path = where_at / f"{root.name}-{hashlib.sha256(str(root).encode()).hexdigest()[:12]}.json"
    path.write_text(mapped.model_dump_json(), encoding="utf-8")
    return path


def recall(repo: Path | str) -> Optional[Map]:
    """The map already read for this repository, if there is one."""
    import hashlib

    from .structure import VESTA_HOME

    root = Path(repo).expanduser().resolve()
    path = (
        VESTA_HOME / "maps"
        / f"{root.name}-{hashlib.sha256(str(root).encode()).hexdigest()[:12]}.json"
    )
    if not path.is_file():
        return None
    try:
        return Map.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
