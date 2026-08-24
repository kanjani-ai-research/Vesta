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
    MODULE,
    Coverage,
    Location,
    Server,
    Session,
    Symbol,
    coverage,
    for_suffix,
    imports_in,
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


class Node(BaseModel):
    """One definition."""

    id: str
    name: str
    path: str
    line: int
    kind: int = Field(description="LSP SymbolKind")
    container: str = ""
    end_line: Optional[int] = None

    @property
    def qualified(self) -> str:
        return f"{self.container}.{self.name}" if self.container else self.name

    @property
    def is_module(self) -> bool:
        """Whether this stands for a file itself rather than something in it.

        A caller counting or matching *definitions* — a function was named
        for something, a rule fired on a class — almost never means this one
        too, since it is not a thing anybody wrote inside the file. It exists
        so a module-level import has somewhere to point.
        """
        return self.kind == MODULE

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

        Bounded by `end_line` where the server reported one (DocumentSymbol's
        `range`, not just `selectionRange` — see resolve.py's Session._flatten):
        a candidate whose body demonstrably ends before `line` is not it, full
        stop. Where a node predates that field (an older cached graph) or a
        server never reports a body range, falls back to bounding by the next
        node's own start line in the same file — weaker (assumes no gap
        between two definitions, which is usually true), but still closes the
        actual bug this exists for: a reference genuinely at module scope,
        after the LAST definition in a file (the common `if __name__ ==
        "__main__": main()` shape) has no "next node" to bound it either way,
        and without end_line it was silently attributed to that last
        definition instead of falling through to the module — which then
        made `source == target` at the call site in _resolve_with,
        indistinguishable from real self-recursion, so the edge was simply
        dropped, never reported as wrong. Confirmed live: vesta/instead.py's
        own `main()`, called from its own `__main__` guard, showed "referred
        to by 0" though the language server correctly reports that exact
        call site when asked directly.
        """
        in_file = [n for n in self.nodes.values() if n.path == path]
        # Real definitions only — the module node is always the LAST
        # resort, never a candidate that can win a tie against a real one.
        # Both commonly sit at line 0 (a module node is synthesized there;
        # the first real definition in a file often starts there too), and
        # picking whichever one iteration happened to reach first made this
        # non-deterministic — a real definition's own bound could be
        # silently skipped just because dict iteration order handed `best`
        # to the module node instead.
        candidates = [n for n in in_file if not n.is_module]

        def _ends(node: Node) -> Optional[int]:
            if node.end_line is not None:
                return node.end_line
            following = min(
                (n.line for n in candidates if n.line > node.line), default=None
            )
            return None if following is None else following - 1

        # The INNERMOST containing definition, not just the closest
        # preceding one: a nested def whose own body has ended (`return
        # does` on the line AFTER `does`'s single-line body, but still
        # inside the OUTER function `build_server`) must fall back to
        # whichever enclosing candidate's own range still covers `line` —
        # not straight past every candidate to the module. Confirmed live:
        # `build_server() { def does(...): ...; return does }` — line 3
        # (`return does`) is past `does`'s own end_line but still inside
        # `build_server`'s, and an earlier version of this fix returned
        # None for it, wrongly treating a definition nested one level
        # deeper as if it had no enclosing scope at all once ITS body
        # ended, rather than checking whether an OUTER one still applied.
        best: Optional[Node] = None
        for node in candidates:
            if node.line > line:
                continue
            end = _ends(node)
            if end is not None and line > end:
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
    # Pruned as it descends, and never into anything hidden. `rglob` visits
    # every excluded directory in full before discarding it.
    from .home import walk

    for path in walk(root):
        if any(part in ignore for part in path.parts):
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
        # on. A reference resolved before its target is known would be
        # dropped. Every file gets its own module node too, at line 0, so a
        # reference at module level — an import, a module-level constant —
        # has somewhere to land besides nowhere; without it, `_containing`
        # found no enclosing definition and the reference was simply dropped.
        #
        # Keyed by column as well as line, not just line: a server resolving
        # `import core` points at `core.py:0:0`, and where the first
        # definition in that file also starts on line 0 — the common case —
        # `(path, line)` alone cannot tell "the module" from "the first
        # definition in it". The column can: a definition's name never starts
        # at the very first character of the line a server reports it on
        # (there is always a keyword, an indent, something before it), so
        # `:0:0` is the module and nothing else.
        at_position: Dict[Tuple[str, int, int], str] = {}
        module_node: Dict[str, str] = {}
        for path in paths:
            relative = str(path.relative_to(root))
            whole = _node_id(relative, 0, relative)
            graph.nodes[whole] = Node(
                id=whole, name=Path(relative).stem, path=relative, line=0, kind=MODULE,
            )
            module_node[relative] = whole
            at_position[(relative, 0, 0)] = whole

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
                    end_line=symbol.end_line,
                )
                at_position.setdefault(
                    (relative, symbol.at.line, symbol.at.character), identity
                )

        # Second pass: who refers to each definition. The reference is
        # attributed to the definition that *contains* it, not to the file, so
        # a change to one method does not appear to affect its neighbours —
        # and now falls back to the file's module node rather than nowhere,
        # for a reference that sits at module level.
        done = 0
        for path in paths:
            relative = str(path.relative_to(root))
            for node in [n for n in graph.nodes.values() if n.path == relative and not n.is_module]:
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

        # Third pass: every import, resolved the same way everything else in
        # this graph is — through the server, not by matching names. This is
        # the one kind of reference `documentSymbol` never reports, so there
        # is nothing in the first two passes to have found it: a bare `import
        # foo` binds a name that no definition anywhere is *of*, and asking
        # `references` on `foo` would first need a position for `foo`, which
        # is exactly what neither pass has. `imports_in` supplies that
        # position from syntax; what it resolves to is decided here, by
        # asking the server and looking at what came back — a location on
        # some file's own line 0 is that file's module node, and a location
        # matching a definition already in this graph is that definition,
        # which is the difference between a module import and a symbol one.
        for path in paths:
            relative = str(path.relative_to(root))
            for binding in imports_in(path):
                source = _containing(
                    graph, root, Location(path=str(path), line=binding.at.line)
                )
                if source is None:
                    continue
                for target in session.definition(path, binding.at.line, binding.at.character):
                    target_relative = _relative(root, target.path)
                    if target_relative not in module_node:
                        continue  # outside this tree: stdlib, a dependency — not this project
                    resolved = at_position.get(
                        (target_relative, target.line, target.character),
                        module_node[target_relative],
                    )
                    if resolved == source:
                        continue
                    # The SAME import line is also picked up by the second
                    # pass above: `session.references` on the imported
                    # symbol itself includes the import site, so a plain
                    # `from x import y` produced two edges for one real
                    # reference — an ordinary 'refers' edge from pass two
                    # AND this 'imports' one, both (source, target, at) alike.
                    # Which one survived a naive display dedup then depended
                    # on the store's own row order, not anything meaningful.
                    # Upgrading the existing edge's kind in place, rather
                    # than appending a second one, keeps exactly one edge per
                    # real reference and lets THIS pass's more precise
                    # knowledge (it parsed the import syntax directly) win.
                    existing = next(
                        (e for e in graph.edges
                         if e.source == source and e.target == resolved
                         and e.at == f"{relative}:{binding.at.line}"),
                        None,
                    )
                    if existing is not None:
                        existing.kind = "imports"
                        continue
                    graph.edges.append(
                        Edge(source=source, target=resolved, kind="imports",
                             at=f"{relative}:{binding.at.line}")
                    )
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
    """The definition a reference sits inside — the file's own module node,
    if nothing narrower does.

    A reference at module level belongs to no function or class, but it does
    belong to the file: propagating from it should reach whoever imports that
    file, not attribute the reference to every definition the file happens to
    contain. Falling back to the module node is what tells the two apart —
    the earlier alternative, dropping the reference outright, could not.

    That fallback was documented here and never implemented: `graph.at`
    returning None (a reference past every definition's real end — the
    common `if __name__ == "__main__": main()` shape, once Graph.at gained
    a real upper bound instead of assuming the last definition in a file
    owns everything after it) fell straight through to returning None from
    HERE too, silently dropping the reference exactly where this docstring
    said it would not.
    """
    relative = _relative(root, location.path)
    node = graph.at(relative, location.line)
    if node is not None:
        return node.id
    whole = _node_id(relative, 0, relative)
    return whole if whole in graph.nodes else None


def _relative(root: Path, path: str) -> str:
    try:
        return str(Path(path).resolve().relative_to(root))
    except ValueError:
        return path
