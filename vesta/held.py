"""Keeping a repository's graph, so asking about it is cheap.

Resolving a tree takes seconds — a language server has to start, index, and
answer a query per definition. That is fine once and unacceptable per question:
a sidecar that rebuilt on every call would make the graph too slow to ask, which
is the same as not having it.

**Staleness is decided by the files, not by a clock.** A cached graph is used
only while every file it was built from is unchanged, judged by size and
modification time. A time-to-live would either serve a graph that is wrong or
rebuild one that is right, and neither is a decision a caller can reason about.

**A stale graph is rebuilt, never patched.** Incremental update is where a graph
quietly diverges from the code: a rename leaves an edge behind, a deleted file
leaves a node, and nothing reports it. The cost of rebuilding is bounded and the
cost of a wrong graph is a wrong answer nobody can see.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from pathlib import Path
from typing import Dict, Optional, Tuple

from .graph import Graph, build
from .home import home

logger = logging.getLogger("vesta.held")

# Where graphs live. Beside the corpora, because they are the same kind of
# thing: something derived from a repository at a moment, worth keeping.
def GRAPH_DIR() -> Path:
    """Where graphs are kept, asked each time.

    Bound at import once, which meant pointing the store elsewhere reached
    everything except this — and a test run wrote its graphs into the user's
    home regardless. A location that can move must be read, not remembered.
    """
    return home() / "graphs"

# What counts as the repository's shape, for deciding whether a graph is stale.
# Names and sizes and modification times, not contents: hashing every file costs
# more than the check is worth on a large tree.
IGNORED = (".venv", "node_modules", ".git", "target", "__pycache__", ".vesta")


_SHAPES: Dict[str, Tuple[str, float]] = {}

# How long a fingerprint is reused within one process. Two seconds covers the
# several callers of a single prompt and expires long before anything else.
_SHAPE_TTL = 2.0


def _shape(root: Path) -> str:
    """A fingerprint of every file the graph could have been built from.

    Memoised for the life of the process. Walking the tree costs a second and a
    half on an ordinary repository, and three separate callers — the graph, the
    dynamic scan, and the readiness check — each walked it on every prompt.
    """
    # Memoised only briefly. A hook is a short-lived process and cannot see a
    # change it makes itself, but a long-lived one — the sidecar, a test — must
    # not be told the tree is unchanged forever.
    remembered = _SHAPES.get(str(root))
    if remembered and time.time() - remembered[1] < _SHAPE_TTL:
        return remembered[0]
    marks = []
    for path in sorted(root.rglob("*")):
        if any(part in IGNORED for part in path.parts):
            continue
        try:
            if path.is_file():
                stat = path.stat()
                marks.append(f"{path}:{stat.st_size}:{int(stat.st_mtime)}")
        except OSError:
            continue
    found = hashlib.sha256("\n".join(marks).encode("utf-8")).hexdigest()[:16]
    _SHAPES[str(root)] = (found, time.time())
    return found


def _where(root: Path) -> Path:
    name = hashlib.sha256(str(root).encode("utf-8")).hexdigest()[:12]
    return GRAPH_DIR() / f"{root.name}-{name}.json"


# Held in memory as well as on disk: a sidecar answers many questions about one
# repository, and parsing 141KB of JSON per question is waste that shows.
_HELD: Dict[str, Tuple[str, Graph]] = {}


def graph_for(
    repo: Path | str, rebuild: bool = False, trust_for: float = 0.0
) -> Graph:
    """The repository's graph, built if there is not a current one.

    `trust_for` lets a caller on a latency-critical path use a recently written
    graph without re-walking the tree to prove it is current. The walk is the
    expensive part by an order of magnitude, and a caller answering a prompt
    cannot spend it.
    """
    root = Path(repo).expanduser().resolve()

    if trust_for:
        cached = _where(root)
        try:
            if cached.is_file() and time.time() - cached.stat().st_mtime < trust_for:
                payload = json.loads(cached.read_text(encoding="utf-8"))
                found = Graph.model_validate(payload["graph"])
                _HELD[str(root)] = (payload.get("shape", ""), found)
                return found
        except (OSError, ValueError, KeyError):
            pass

    shape = _shape(root)

    remembered = _HELD.get(str(root))
    if remembered and remembered[0] == shape and not rebuild:
        return remembered[1]

    cached = _where(root)
    if cached.is_file() and not rebuild:
        try:
            payload = json.loads(cached.read_text(encoding="utf-8"))
            if payload.get("shape") == shape:
                found = Graph.model_validate(payload["graph"])
                _HELD[str(root)] = (shape, found)
                return found
        except (OSError, ValueError, KeyError) as exc:
            logger.info("could not read the cached graph: %s", exc)

    started = time.time()
    found = build(root)
    logger.info("built the graph for %s in %.0fs", root, time.time() - started)

    # Also as rows, one store per repository. A question touches a fraction of
    # a graph and parsing the whole document to answer it costs nine seconds at
    # forty thousand definitions — where an indexed lookup costs a fifth of a
    # millisecond. Separate files per project because a shared one would make
    # one repository's rebuild block another's read, and would make reaching
    # across projects accidental rather than asked for.
    try:
        from .store import write as write_store

        write_store(found, root, shape)
    except Exception as exc:  # noqa: BLE001 - the document is still authoritative
        logger.info("could not write the graph store for %s: %s", root, exc)

    GRAPH_DIR().mkdir(parents=True, exist_ok=True)
    try:
        cached.write_text(
            json.dumps({"shape": shape, "graph": found.model_dump(mode="json")}),
            encoding="utf-8",
        )
    except OSError as exc:
        logger.info("could not cache the graph: %s", exc)

    _HELD[str(root)] = (shape, found)
    return found


def forget(repo: Optional[Path | str] = None) -> None:
    """Drop what is held, for a caller that knows better than the fingerprint."""
    if repo is None:
        _HELD.clear()
        return
    _HELD.pop(str(Path(repo).expanduser().resolve()), None)
