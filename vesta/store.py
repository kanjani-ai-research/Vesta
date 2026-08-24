"""A repository's graph as rows, so a question reads only what it asks about.

A graph kept as one JSON document has to be parsed whole before anything can be
answered. That is free at four hundred definitions and ruinous at forty
thousand: a nineteen-megabyte document takes about nine seconds to parse, and a
hook is a fresh process every time, so it pays that on every prompt. Meanwhile a
typical question touches eight to forty percent of the graph — `uses` looks at
one definition and its neighbours, `touches` walks three hops.

**Edges are rows with indexed pointers, which is what makes traversal cheap.**
`source` and `target` are node ids with an index on each, so "what refers to
this" is an index seek rather than a scan, and a hop is another seek. Measured
against the same graph scaled to forty-six thousand definitions: 0.2
milliseconds to open the file, find a definition by name, and read its callers,
against nine seconds to parse the equivalent document.

**JSON stays for what is small and read whole.** An ontology is a few hundred
terms and every one of them is needed to answer anything; rules are a dozen.
Only the graph is both large and touched sparsely, so only the graph moves.

**A store is derived, never authoritative.** It can be deleted and rebuilt from
the repository at any time, which is why it carries the same fingerprint the
JSON did: a store whose repository has changed is stale in exactly the way the
document was, and is rebuilt rather than migrated.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from .graph import Edge, Graph, Hole, Node
from .resolve import MODULE
from .home import kept_at

logger = logging.getLogger("vesta.store")

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- One definition. `id` is what edges point at, so it is the primary key and
-- everything else hangs off it. end_line is nullable: a server that never
-- reports a body range (only a start position) leaves it NULL, and Graph.at
-- falls back to its weaker next-node heuristic for exactly those rows.
CREATE TABLE IF NOT EXISTS nodes (
    id        TEXT PRIMARY KEY,
    name      TEXT NOT NULL,
    path      TEXT NOT NULL,
    line      INTEGER NOT NULL,
    kind      INTEGER NOT NULL DEFAULT 0,
    container TEXT NOT NULL DEFAULT '',
    end_line  INTEGER
);

-- A reference, as a pointer in each direction. Both columns are indexed
-- because both questions are asked: what refers to this, and what does this
-- refer to. Without the second index a propagation walk degrades to a scan per
-- hop, which is the whole cost this exists to avoid.
CREATE TABLE IF NOT EXISTS edges (
    source TEXT NOT NULL,
    target TEXT NOT NULL,
    kind   TEXT NOT NULL DEFAULT 'refers',
    at     TEXT NOT NULL DEFAULT ''
);

-- What the resolver could not read. Kept with the graph because a propagation
-- claim is only as complete as the resolution behind it.
CREATE TABLE IF NOT EXISTS holes (
    path TEXT NOT NULL,
    what TEXT NOT NULL DEFAULT '',
    why  TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_nodes_name ON nodes(name);
CREATE INDEX IF NOT EXISTS idx_nodes_path ON nodes(path, line);
CREATE INDEX IF NOT EXISTS idx_edges_target ON edges(target);
CREATE INDEX IF NOT EXISTS idx_edges_source ON edges(source);
"""


def _at(repo: Path | str) -> Path:
    return kept_at(repo, "graphs").with_suffix(".db")


def write(graph: Graph, repo: Path | str, shape: str = "") -> Path:
    """Put a graph in a store, replacing whatever was there.

    Replaced rather than updated: a graph is derived from a repository in one
    pass, and reconciling a partial rebuild against old rows is how a store
    comes to hold edges for definitions that no longer exist.
    """
    path = _at(repo)
    connection = sqlite3.connect(path)
    try:
        # DROP first: an existing store on disk from before end_line existed
        # has the old 6-column nodes table, and `CREATE TABLE IF NOT EXISTS`
        # does not add a column to a table that is already there. Safe here
        # specifically because every write() call already replaces every row
        # unconditionally (see DELETE FROM below) — there is no data an
        # incremental ALTER TABLE would need to preserve that a full rebuild
        # does not already recreate.
        connection.execute("DROP TABLE IF EXISTS nodes")
        connection.executescript(SCHEMA)
        with connection:
            connection.execute("DELETE FROM edges")
            connection.execute("DELETE FROM holes")
            connection.executemany(
                "INSERT INTO nodes VALUES (?,?,?,?,?,?,?)",
                [
                    (n.id, n.name, n.path, n.line, n.kind, n.container, n.end_line)
                    for n in graph.nodes.values()
                ],
            )
            connection.executemany(
                "INSERT INTO edges VALUES (?,?,?,?)",
                [(e.source, e.target, e.kind, e.at) for e in graph.edges],
            )
            connection.executemany(
                "INSERT INTO holes VALUES (?,?,?)",
                [(h.path, h.what, h.why) for h in graph.holes],
            )
            connection.execute(
                "INSERT OR REPLACE INTO meta VALUES ('shape', ?)", (shape,)
            )
            connection.execute(
                "INSERT OR REPLACE INTO meta VALUES ('root', ?)", (graph.root,)
            )
    finally:
        connection.close()
    return path


def shape_of(repo: Path | str) -> str:
    """What the repository looked like when this store was written."""
    path = _at(repo)
    if not path.is_file():
        return ""
    try:
        connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    except sqlite3.Error:
        return ""
    try:
        row = connection.execute("SELECT value FROM meta WHERE key='shape'").fetchone()
        return row[0] if row else ""
    except sqlite3.Error:
        return ""
    finally:
        connection.close()


class Held:
    """A graph on disk, read a question at a time.

    Opened read-only and kept open for the life of a call. Everything it
    answers is an indexed lookup, so the cost is the question rather than the
    repository.
    """

    def __init__(self, repo: Path | str) -> None:
        self.path = _at(repo)
        self._db: Optional[sqlite3.Connection] = None

    @property
    def exists(self) -> bool:
        return self.path.is_file()

    def _open(self) -> sqlite3.Connection:
        if self._db is None:
            self._db = sqlite3.connect(f"file:{self.path}?mode=ro", uri=True)
            self._db.row_factory = sqlite3.Row
        return self._db

    def close(self) -> None:
        if self._db is not None:
            self._db.close()
            self._db = None

    def __enter__(self) -> "Held":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    # ── The questions a tool asks ────────────────────────────────────────

    def named(self, name: str, limit: int = 20) -> List[Node]:
        """Definitions by name, or by qualified name.

        Excludes a module's own node: it is named after its file, which
        collides with any function or class that happens to share the file's
        name (home.py's module node is named "home", same as `def home()`
        inside it) — confirmed live, uses("home") on this repository
        returned both, the module node's "callers" actually being every file
        that imports the module, shown in the same shape as a real call. An
        agent asking what uses a NAME never means the file itself (matches
        the same exclusion _matching in sidecar.py and _node_at in
        derive.py already apply for the identical reason). Filtered in
        Python against the same Node.is_module every other caller uses,
        rather than hardcoding the LSP kind integer into SQL as a second,
        driftable source of truth for what "is a module" means.
        """
        rows = self._open().execute(
            "SELECT * FROM nodes WHERE name = ? OR container || '.' || name = ? "
            "LIMIT ?",
            (name, name, limit * 2),   # over-fetch: module rows get filtered below
        ).fetchall()
        return [n for n in (_node(r) for r in rows) if not n.is_module][:limit]

    def by_id(self, node_id: str) -> Optional[Node]:
        row = self._open().execute(
            "SELECT * FROM nodes WHERE id = ?", (node_id,)
        ).fetchone()
        return _node(row) if row else None

    def referenced_by(self, node_id: str) -> List[str]:
        """What refers to this. The direction a propagation walks."""
        return [
            r[0]
            for r in self._open().execute(
                "SELECT source FROM edges WHERE target = ?", (node_id,)
            )
        ]

    def referenced_by_any(self, node_ids: Sequence[str]) -> Dict[str, List[str]]:
        """What refers to each of these, in one query.

        A propagation hop asks about a whole frontier at once. Asking per node
        turned one walk into hundreds of round trips and lost to simply parsing
        the document — the store is only faster if it is asked in the shape it
        is good at.
        """
        if not node_ids:
            return {}
        found: Dict[str, List[str]] = {n: [] for n in node_ids}
        marks = ",".join("?" * len(node_ids))
        for row in self._open().execute(
            f"SELECT target, source FROM edges WHERE target IN ({marks})",
            tuple(node_ids),
        ):
            found[row["target"]].append(row["source"])
        return found

    def by_ids(self, node_ids: Sequence[str]) -> Dict[str, Node]:
        """Several definitions in one query, for the same reason."""
        if not node_ids:
            return {}
        marks = ",".join("?" * len(node_ids))
        return {
            row["id"]: _node(row)
            for row in self._open().execute(
                f"SELECT * FROM nodes WHERE id IN ({marks})", tuple(node_ids)
            )
        }

    def depends_on(self, node_id: str) -> List[str]:
        """What this refers to."""
        return [
            r[0]
            for r in self._open().execute(
                "SELECT target FROM edges WHERE source = ?", (node_id,)
            )
        ]

    def at(self, path: str, line: int) -> Optional[Node]:
        """The innermost definition containing a line.

        A change is reported by file and line; a graph is keyed by definition.
        The index on `(path, line)` makes this a seek rather than a scan over
        every definition in the repository.

        Bounded by end_line where the server reported one — see
        Graph.at's own docstring for why an unbounded "closest preceding
        definition" silently misattributed a module-scope reference AFTER
        the last definition in a file (the `if __name__ == "__main__":
        main()` shape) to that definition instead of to the module.
        """
        # kind != MODULE: a module node commonly sits at the same line 0 as
        # the file's first real definition (or as the sole line 0 candidate
        # once nothing earlier qualifies) — letting it compete for `best`
        # made the fallback non-deterministic, silently winning over a real
        # definition's own end_line bound depending on row order. The module
        # node is a last resort ONLY, applied by callers of Held.at that
        # want it (mirroring Graph._containing), never a candidate here.
        row = self._open().execute(
            "SELECT * FROM nodes WHERE path = ? AND line <= ? AND kind != ? "
            "ORDER BY line DESC LIMIT 1",
            (path, line, MODULE),
        ).fetchone()
        if row is None:
            return None
        node = _node(row)
        if node.end_line is not None:
            return node if line <= node.end_line else None
        following = self._open().execute(
            "SELECT MIN(line) FROM nodes WHERE path = ? AND line > ? AND kind != ?",
            (path, node.line, MODULE),
        ).fetchone()[0]
        if following is not None and line >= following:
            return None
        return node

    def in_file(self, path: str) -> List[Node]:
        return [
            _node(r)
            for r in self._open().execute(
                "SELECT * FROM nodes WHERE path = ? ORDER BY line", (path,)
            )
        ]

    def busiest(self, limit: int = 12) -> List[Tuple[Node, int]]:
        """The most depended-upon definitions, without loading the rest."""
        rows = self._open().execute(
            "SELECT n.*, count(e.source) AS callers FROM nodes n "
            "LEFT JOIN edges e ON e.target = n.id "
            "GROUP BY n.id ORDER BY callers DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [(_node(r), r["callers"]) for r in rows]

    def counts(self) -> Tuple[int, int, int]:
        db = self._open()
        return (
            db.execute("SELECT count(*) FROM nodes").fetchone()[0],
            db.execute("SELECT count(*) FROM edges").fetchone()[0],
            db.execute("SELECT count(*) FROM holes").fetchone()[0],
        )

    def everything(self) -> Graph:
        """The whole graph, for the few callers that genuinely need it.

        A survey reads every definition and there is no cheaper way to do that.
        What matters is that the sparse questions no longer pay for it.
        """
        db = self._open()
        nodes = {r["id"]: _node(r) for r in db.execute("SELECT * FROM nodes")}
        edges = [
            Edge(source=r["source"], target=r["target"], kind=r["kind"], at=r["at"])
            for r in db.execute("SELECT * FROM edges")
        ]
        holes = [
            Hole(path=r["path"], what=r["what"], why=r["why"])
            for r in db.execute("SELECT * FROM holes")
        ]
        row = db.execute("SELECT value FROM meta WHERE key='root'").fetchone()
        return Graph(root=row[0] if row else "", nodes=nodes, edges=edges, holes=holes)


class AsGraph:
    """A store presented as a graph, for callers that only walk it.

    Propagation asks three things — what refers to this, what definition is
    this, and what could not be resolved — and a store answers all three by
    index. Wrapping rather than converting means `from_definitions` needs no
    change and works against either, which matters because the document is
    still what a survey reads.
    """

    def __init__(self, held: "Held") -> None:
        self._held = held
        self._holes: Optional[List[Hole]] = None

    @property
    def nodes(self) -> "_Nodes":
        return _Nodes(self._held)

    @property
    def holes(self) -> List[Hole]:
        if self._holes is None:
            self._holes = [
                Hole(path=r["path"], what=r["what"], why=r["why"])
                for r in self._held._open().execute("SELECT * FROM holes")
            ]
        return self._holes

    def referenced_by(self, node_id: str) -> List[Edge]:
        return [
            Edge(source=source, target=node_id)
            for source in self._held.referenced_by(node_id)
        ]

    def depends_on(self, node_id: str) -> List[Edge]:
        return [
            Edge(source=node_id, target=target)
            for target in self._held.depends_on(node_id)
        ]

    def referenced_by_any(self, node_ids: Sequence[str]) -> Dict[str, List[str]]:
        return self._held.referenced_by_any(node_ids)

    def by_ids(self, node_ids: Sequence[str]) -> Dict[str, Node]:
        return self._held.by_ids(node_ids)

    def at(self, path: str, line: int) -> Optional[Node]:
        return self._held.at(path, line)

    def in_file(self, path: str) -> List[Node]:
        return self._held.in_file(path)


class _Nodes:
    """The node table, addressed the way a caller addresses a dict.

    Only what propagation uses: `get`, `in`, and iteration over values where a
    caller genuinely wants every definition. Iteration is the expensive one and
    is left available rather than hidden, because a caller that needs it needs
    it.
    """

    def __init__(self, held: "Held") -> None:
        self._held = held

    def get(self, node_id: str, default: Optional[Node] = None) -> Optional[Node]:
        return self._held.by_id(node_id) or default

    def __getitem__(self, node_id: str) -> Node:
        found = self._held.by_id(node_id)
        if found is None:
            raise KeyError(node_id)
        return found

    def __contains__(self, node_id: str) -> bool:
        return self._held.by_id(node_id) is not None

    def __len__(self) -> int:
        return self._held.counts()[0]

    def values(self) -> Iterable[Node]:
        for row in self._held._open().execute("SELECT * FROM nodes"):
            yield _node(row)

    def __iter__(self) -> Iterable[str]:
        for row in self._held._open().execute("SELECT id FROM nodes"):
            yield row["id"]


def _node(row: sqlite3.Row) -> Node:
    return Node(
        id=row["id"],
        name=row["name"],
        path=row["path"],
        line=row["line"],
        kind=row["kind"],
        container=row["container"],
        end_line=row["end_line"],
    )
