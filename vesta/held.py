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
from typing import Dict, List, Optional, Tuple

from .graph import Graph, build
from .home import NOT_THE_PROJECT as IGNORED
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
# more than the check is worth on a large tree. `IGNORED` is shared, so what the
# graph calls its shape and what the resolver walks cannot disagree.


_SHAPES: Dict[str, Tuple[str, float]] = {}

# How long a fingerprint is reused within one process.
#
# Two seconds was chosen when walking the tree cost 3.6 seconds and several
# callers each paid it within one prompt. The walk now costs eight
# milliseconds, so the saving is nothing and the cost is real: a file written
# and a question asked inside the same two seconds — an agent editing and then
# asking, which is the ordinary rhythm of a session — was answered from the
# graph as it stood before the edit.
#
# A fifth of a second still collapses the several callers of one prompt, and
# is shorter than anybody can type.
_SHAPE_TTL = 0.2


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
    # One walk, shared with everything else that reads a repository, so what
    # the fingerprint covers and what the resolver reads cannot drift apart.
    # It prunes as it descends: `rglob` visited 66,010 paths to fingerprint 77
    # source files, which took 3.6 seconds — and that cost is what forced
    # callers to accept a graph up to five minutes stale. It now takes 13ms,
    # so nothing has to guess.
    from .home import walk

    # Nanoseconds, not whole seconds.
    #
    # `int(st.st_mtime)` has one-second resolution, so an edit that changed a
    # file without changing its length — `x = 1` to `x = 2`, a fix somebody
    # makes in a second — moved nothing, and the graph went on describing code
    # that no longer existed. That is the precise case an active session
    # produces most: small, fast, same-length corrections.
    marks = []
    for path in walk(root):
        try:
            stat = path.stat()
        except OSError:
            continue
        marks.append(f"{path}:{stat.st_size}:{stat.st_mtime_ns}")
    found = hashlib.sha256("\n".join(marks).encode("utf-8")).hexdigest()[:16]
    _SHAPES[str(root)] = (found, time.time())
    return found


def _where(root: Path) -> Path:
    name = hashlib.sha256(str(root).encode("utf-8")).hexdigest()[:12]
    return GRAPH_DIR() / f"{root.name}-{name}.json"


# Held in memory as well as on disk: a sidecar answers many questions about one
# repository, and parsing 141KB of JSON per question is waste that shows.
_HELD: Dict[str, Tuple[str, Graph]] = {}


def _parts(root: Path) -> List[Path]:
    """The projects inside this directory, if it holds several."""
    from .compose import parts_of

    try:
        return parts_of(root)
    except OSError as exc:  # noqa: BLE001 - a directory that cannot be read
        logger.info("could not look inside %s: %s", root, exc)
        return []


def _composed_for(
    root: Path, parts: List[Path], rebuild: bool, never_build: bool
) -> Graph:
    """One graph for a directory, from the graphs of the projects in it.

    Each part is fetched the ordinary way, so each is independently current or
    independently rebuilt. Nothing here decides staleness — that stays with the
    graph it belongs to, which is the whole point: one project's edit is one
    project's rebuild.
    """
    from .compose import composed

    of: Dict[str, Graph] = {}
    for part in parts:
        try:
            of[str(part)] = graph_for(
                part, rebuild=rebuild, never_build=never_build
            )
        except Exception as exc:  # noqa: BLE001 - one bad part is not the whole
            logger.info("could not read the graph for %s: %s", part, exc)
    return composed(root, parts, of)


def graph_for(
    repo: Path | str,
    rebuild: bool = False,
    trust_for: float = 0.0,
    never_build: bool = False,
) -> Graph:
    """The repository's graph, built if there is not a current one.

    `trust_for` no longer buys a stale answer. The fingerprint it existed to
    avoid costs 8ms rather than 3.6 seconds, so the tree is checked on every
    call — every sidecar tool asked for `trust_for=300`, and during an active
    session that meant answers drawn from a graph a hundred edits behind, which
    looks exactly like a fresh one.

    `never_build` is for callers that must not wait: a hook answering a prompt.
    It returns the graph on disk however stale, having started a rebuild
    elsewhere. **The rebuild is all or nothing**, and on a directory of
    thirteen projects that is 73 seconds to catch up with one edited file —
    measured, inside a prompt, taking a hook past two minutes. A slightly old
    answer that says so beats a session that stops whenever somebody saves.
    """
    root = Path(repo).expanduser().resolve()

    # A directory of projects is answered by composing the graphs beneath it,
    # so that editing one project invalidates one graph. Built as a single
    # tree, a workspace of thirteen repositories was 73 seconds to rebuild
    # because one file in one of them changed.
    parts = _parts(root)
    if parts:
        return _composed_for(root, parts, rebuild=rebuild, never_build=never_build)

    if never_build:
        cached = _where(root)
        try:
            if cached.is_file():
                payload = json.loads(cached.read_text(encoding="utf-8"))
                found = Graph.model_validate(payload["graph"])
                _HELD[str(root)] = (payload.get("shape", ""), found)
                return found
        except (OSError, ValueError, KeyError):
            pass
        return Graph(root=str(root))

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
