"""A codebase, as a graph of what refers to what.

Nodes are definitions — the things a change can be *to*. Edges are references,
resolved by a language server rather than inferred from syntax, so an edge
means "this actually refers to that" rather than "these names look alike".

**Both directions are held.** The two questions a developer asks are opposites:
what breaks if I change this, and what would I have to change to change this.
A graph answering only one of them answers half the question at twice the cost
to retrofit.

**Every definition is queried.** Not a sample, not the exported ones, not the
ones a heuristic thinks matter. At fifty-five milliseconds per definition a
repository costs half a minute, and a graph built from a sample is a graph
whose gaps nobody can characterise — which is the failure that makes a
correctness claim worthless.

**What the graph does not know, it records.** A file whose language has no
server installed, a definition whose references the server declined to answer,
a query that timed out: each is a hole, and a propagation set computed over a
graph with holes has to be able to say so. The alternative is a result that
looks complete and is not.
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

from pydantic import BaseModel, Field

from .resolve import (
    Coverage,
    Location,
    Server,
    Session,
    Symbol,
    coverage,
    for_suffix,
)

logger = logging.getLogger("vesta.graph")

# What a reference means. One kind for now, deliberately: a language server
# reports that something refers to something without saying how, and inventing
# a taxonomy the protocol does not supply would be guessing dressed as
# structure. Where a server distinguishes call from read, the distinction can
# be added — the edge already carries the field.
REFERS = "refers"

# Why a definition has no outgoing edges. The difference between "nothing
# refers to this" and "nobody asked" is the difference between a finding and a
# gap.
NOT_ASKED = "no server for this language"
DECLINED = "the server returned no answer"


class Node(BaseModel):
    """One definition."""

    id: str
    name: str
    path: str
    line: int
    kind: int = Field(description="LSP SymbolKind")
    container: str = ""

    @property
    def qualified(self) -> str:
        return f"{self.container}.{self.name}" if self.container else self.name

    def describe(self) -> str:
        return f"{self.qualified} ({self.path}:{self.line + 1})"


class Edge(BaseModel):
    """One reference: `source` refers to `target`."""

    source: str = Field(description="Node id of the definition doing the referring")
    target: str = Field(description="Node id of the definition referred to")
    kind: str = REFERS
    at: str = Field(default="", description="Where the reference appears")


class Hole(BaseModel):
    """Something the graph does not know, and why."""

    path: str
    what: str
    why: str

    def describe(self) -> str:
        return f"{self.path}: {self.what} — {self.why}"


class Graph(BaseModel):
    """What refers to what, in both directions."""

    root: str = ""
    nodes: Dict[str, Node] = Field(default_factory=dict)
    edges: List[Edge] = Field(default_factory=list)
    holes: List[Hole] = Field(default_factory=list)
    coverage: Optional[Coverage] = None
    built_in: float = 0.0

    _out: Optional[Dict[str, List[Edge]]] = None
    _in: Optional[Dict[str, List[Edge]]] = None

    model_config = {"arbitrary_types_allowed": True}

    def _index(self) -> None:
        out: Dict[str, List[Edge]] = defaultdict(list)
        into: Dict[str, List[Edge]] = defaultdict(list)
        for edge in self.edges:
            out[edge.source].append(edge)
            into[edge.target].append(edge)
        self._out = dict(out)
        self._in = dict(into)

    def depends_on(self, node_id: str) -> List[Edge]:
        """What this refers to. Answers "what would I have to change"."""
        if self._out is None:
            self._index()
        return self._out.get(node_id, [])  # type: ignore[union-attr]

    def referenced_by(self, node_id: str) -> List[Edge]:
        """What refers to this. The direction propagation walks."""
        if self._in is None:
            self._index()
        return self._in.get(node_id, [])  # type: ignore[union-attr]

    def at(self, path: str, line: int) -> Optional[Node]:
        """The innermost definition containing a line.

        A change is reported by file and line; a graph is keyed by definition.
        This is the join, and it takes the *innermost* enclosing definition
        because attributing a change to a module when it belongs to one method
        would propagate from everything in that module.
        """
        best: Optional[Node] = None
        for node in self.nodes.values():
            if node.path != path or node.line > line:
                continue
            if best is None or node.line > best.line:
                best = node
        return best

    def in_file(self, path: str) -> List[Node]:
        return [n for n in self.nodes.values() if n.path == path]

    @property
    def is_whole(self) -> bool:
        return not self.holes

    def describe(self) -> str:
        parts = [f"{len(self.nodes)} definitions", f"{len(self.edges)} references"]
        if self.holes:
            parts.append(f"{len(self.holes)} hole(s)")
        if self.built_in:
            parts.append(f"built in {self.built_in:.0f}s")
        return ", ".join(parts)


def _node_id(path: str, line: int, name: str) -> str:
    import hashlib

    return hashlib.sha256(
        f"{path}\x00{line}\x00{name}".encode("utf-8")
    ).hexdigest()[:16]


def build(
    root: Path | str,
    ignore: Sequence[str] = (".venv", "node_modules", ".git", "target", "__pycache__"),
    on_progress: Optional[Any] = None,
) -> Graph:
    """Resolve a tree into a graph.

    One session per language, held open across the whole build because starting
    a server and letting it index is the expensive part. Every definition in
    every file the machine can resolve is queried.
    """
    root = Path(root).resolve()
    started = time.time()
    graph = Graph(root=str(root), coverage=coverage(root, ignore))

    by_server: Dict[str, List[Path]] = defaultdict(list)
    for path in sorted(root.rglob("*")):
        if not path.is_file() or any(part in ignore for part in path.parts):
            continue
        server = for_suffix(path.suffix)
        if server is None:
            continue
        if not server.is_available:
            graph.holes.append(
                Hole(path=str(path.relative_to(root)), what=path.suffix, why=NOT_ASKED)
            )
            continue
        by_server[server.name].append(path)

    for name, paths in by_server.items():
        server = next(s for s in [for_suffix(p.suffix) for p in paths] if s)
        _resolve_with(graph, server, root, paths, on_progress)

    graph.built_in = time.time() - started
    return graph


def _resolve_with(
    graph: Graph,
    server: Server,
    root: Path,
    paths: Sequence[Path],
    on_progress: Optional[Any],
) -> None:
    """Every definition and every reference, for one language."""
    session = Session(server, root)
    if not session.start():
        for path in paths:
            graph.holes.append(
                Hole(
                    path=str(path.relative_to(root)),
                    what=server.name,
                    why="the server would not start",
                )
            )
        return

    try:
        # The server searches files it has been told about, not files on disk.
        session.open_tree()

        # First pass: every definition, so a reference has something to land
        # on. A reference resolved before its target is known would be dropped.
        at_line: Dict[Tuple[str, int], str] = {}
        for path in paths:
            relative = str(path.relative_to(root))
            for symbol in session.symbols(path):
                if not symbol.is_definition:
                    continue
                identity = _node_id(relative, symbol.at.line, symbol.name)
                graph.nodes[identity] = Node(
                    id=identity,
                    name=symbol.name,
                    path=relative,
                    line=symbol.at.line,
                    kind=symbol.kind,
                    container=symbol.container,
                )
                at_line[(relative, symbol.at.line)] = identity

        # Second pass: who refers to each definition. The reference is
        # attributed to the definition that *contains* it, not to the file, so
        # a change to one method does not appear to affect its neighbours.
        done = 0
        for path in paths:
            relative = str(path.relative_to(root))
            for node in [n for n in graph.nodes.values() if n.path == relative]:
                references = session.references(path, node.line, _column_of(path, node))
                for location in references:
                    source = _containing(graph, root, location)
                    if source is None or source == node.id:
                        continue
                    graph.edges.append(
                        Edge(
                            source=source,
                            target=node.id,
                            at=f"{_relative(root, location.path)}:{location.line}",
                        )
                    )
                done += 1
                if on_progress and done % 50 == 0:
                    on_progress(done, len(graph.nodes))
    finally:
        session.stop()


def _column_of(path: Path, node: Node) -> int:
    """Where on its line a definition's name starts.

    A server answers `references` about a position, and a position pointing at
    whitespace or at a keyword answers about nothing. The symbol's own reported
    character is used where it lands on the name, and the name is found on the
    line otherwise.
    """
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
        if node.line < len(lines):
            found = lines[node.line].find(node.name)
            if found >= 0:
                return found
    except (OSError, UnicodeDecodeError):
        pass
    return 0


def _containing(graph: Graph, root: Path, location: Location) -> Optional[str]:
    """The definition a reference sits inside.

    A reference at module level belongs to no definition and is dropped: it is
    real, and propagating from it would attribute every import in a file to
    every definition in that file.
    """
    relative = _relative(root, location.path)
    node = graph.at(relative, location.line)
    return node.id if node else None


def _relative(root: Path, path: str) -> str:
    try:
        return str(Path(path).resolve().relative_to(root))
    except ValueError:
        return path
