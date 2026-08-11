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
from .structure import VESTA_HOME

logger = logging.getLogger("vesta.held")

# Where graphs live. Beside the corpora, because they are the same kind of
# thing: something derived from a repository at a moment, worth keeping.
GRAPH_DIR = VESTA_HOME / "graphs"

# What counts as the repository's shape, for deciding whether a graph is stale.
# Names and sizes and modification times, not contents: hashing every file costs
# more than the check is worth on a large tree.
IGNORED = (".venv", "node_modules", ".git", "target", "__pycache__", ".vesta")


def _shape(root: Path) -> str:
    """A fingerprint of every file the graph could have been built from."""
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
    return hashlib.sha256("\n".join(marks).encode("utf-8")).hexdigest()[:16]


def _where(root: Path) -> Path:
    name = hashlib.sha256(str(root).encode("utf-8")).hexdigest()[:12]
    return GRAPH_DIR / f"{root.name}-{name}.json"


# Held in memory as well as on disk: a sidecar answers many questions about one
# repository, and parsing 141KB of JSON per question is waste that shows.
_HELD: Dict[str, Tuple[str, Graph]] = {}


def graph_for(repo: Path | str, rebuild: bool = False) -> Graph:
    """The repository's graph, built if there is not a current one."""
    root = Path(repo).expanduser().resolve()
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

    GRAPH_DIR.mkdir(parents=True, exist_ok=True)
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
