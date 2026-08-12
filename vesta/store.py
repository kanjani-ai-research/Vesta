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
from .home import kept_at

logger = logging.getLogger("vesta.store")

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- One definition. `id` is what edges point at, so it is the primary key and
-- everything else hangs off it.
CREATE TABLE IF NOT EXISTS nodes (
    id        TEXT PRIMARY KEY,
    name      TEXT NOT NULL,
    path      TEXT NOT NULL,
    line      INTEGER NOT NULL,
    kind      INTEGER NOT NULL DEFAULT 0,
    container TEXT NOT NULL DEFAULT ''
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
        connection.executescript(SCHEMA)
        with connection:
            connection.execute("DELETE FROM nodes")
            connection.execute("DELETE FROM edges")
            connection.execute("DELETE FROM holes")
            connection.executemany(
                "INSERT INTO nodes VALUES (?,?,?,?,?,?)",
                [
                    (n.id, n.name, n.path, n.line, n.kind, n.container)
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
        """Definitions by name, or by qualified name."""
        rows = self._open().execute(
            "SELECT * FROM nodes WHERE name = ? OR container || '.' || name = ? "
            "LIMIT ?",
            (name, name, limit),
        ).fetchall()
        return [_node(r) for r in rows]

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
        """
        row = self._open().execute(
            "SELECT * FROM nodes WHERE path = ? AND line <= ? "
            "ORDER BY line DESC LIMIT 1",
            (path, line),
        ).fetchone()
        return _node(row) if row else None

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


def _node(row: sqlite3.Row) -> Node:
    return Node(
        id=row["id"],
        name=row["name"],
        path=row["path"],
        line=row["line"],
        kind=row["kind"],
        container=row["container"],
    )
