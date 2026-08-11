"""Whether a recorded claim still speaks for the code.

There are two accounts of a codebase and the truth sits between them. A resolved
graph knows what refers to what and cannot see a `getattr(obj, "name")`; a
harvested note knows what an agent worked out and cannot know whether the code
has moved since. Neither is authoritative on its own, and a live agent —
correctly — verified both rather than trusting either.

**Authority is a narrow window, and the window is checkable.** A claim about a
region speaks for that region while the region's bytes are the bytes it was made
about. Not while the file is unchanged, which is too coarse: an edit elsewhere
in a 900-line module says nothing about a claim concerning lines 464–536. Not
for some interval, which is not evidence of anything.

So a note records the hash of what it described. Later, the same span is hashed
again. Identical means the claim still stands on what it stood on; different
means the ground moved and the claim is a claim about something that no longer
exists. Both are facts about bytes, not judgements.

**What this cannot do is make a wrong claim right.** An agent can misread code
that has not changed since, and this will call that note current. Currency is
the weaker property — it says re-verification is unnecessary, not that the
original analysis was sound.
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from pydantic import BaseModel, Field

from .graph import Graph, Node

logger = logging.getLogger("vesta.authority")

# How far past a definition's first line a claim is taken to reach. A note about
# a function is about its body, and the graph records where definitions start
# but not where they end.
SPAN = 80

CURRENT = "current"        # the bytes are the bytes it was written about
MOVED = "moved"            # the region changed after the claim was made
UNKNOWN = "unknown"        # nothing was recorded, so nothing can be checked


class Standing(BaseModel):
    """Whether a claim still speaks for the code it described."""

    state: str = UNKNOWN
    region: str = ""
    # What the region hashed to when the claim was made, and what it hashes to
    # now. Kept so a reader can see the check rather than take its word.
    was: str = ""
    now: str = ""

    @property
    def authoritative(self) -> bool:
        return self.state == CURRENT

    def describe(self) -> str:
        if self.state == CURRENT:
            return f"still current — {self.region} is unchanged since this was written"
        if self.state == MOVED:
            return f"superseded — {self.region} has changed since this was written"
        return "unverifiable — no region was recorded when this was written"


def region_of(node: Node, root: Path, span: int = SPAN) -> Tuple[str, str]:
    """The lines a claim about a definition is about, and their hash.

    Bounded by the next definition where the graph knows one, and by a fixed
    span otherwise. A hash over the whole file would call every claim stale on
    any edit; a hash over one line would call a rewritten body unchanged.
    """
    path = root / node.path
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return "", ""

    start = max(0, node.line)
    end = min(len(lines), start + span)
    body = "\n".join(lines[start:end])
    return (
        f"{node.path}:{start + 1}-{end}",
        hashlib.sha256(body.encode("utf-8")).hexdigest()[:16],
    )


def bounded_region(graph: Graph, node: Node, root: Path) -> Tuple[str, str]:
    """The region for a definition, ending where the next one begins."""
    following = [
        other.line
        for other in graph.nodes.values()
        if other.path == node.path and other.line > node.line
    ]
    span = (min(following) - node.line) if following else SPAN
    return region_of(node, root, max(3, min(span, 400)))


def stamp(graph: Graph, node_id: str, root: Path | str) -> Tuple[str, str]:
    """What to record with a claim, so it can be checked later."""
    node = graph.nodes.get(node_id)
    if node is None:
        return "", ""
    return bounded_region(graph, node, Path(root))


def check(
    graph: Graph, node_id: str, root: Path | str, region: str, was: str
) -> Standing:
    """Whether a claim recorded against a region still speaks for it."""
    if not was:
        return Standing(state=UNKNOWN, region=region)

    node = graph.nodes.get(node_id)
    if node is None:
        # The definition is gone. A claim about something that no longer exists
        # has certainly been superseded.
        return Standing(state=MOVED, region=region, was=was)

    now_region, now = bounded_region(graph, node, Path(root))
    return Standing(
        state=CURRENT if now == was else MOVED,
        region=now_region or region,
        was=was,
        now=now,
    )


def settle(
    graph: Graph, notes: Sequence, root: Path | str
) -> Dict[str, Standing]:
    """Check a set of notes at once, sharing the file reads."""
    cached: Dict[str, Tuple[str, str]] = {}
    found: Dict[str, Standing] = {}

    for note in notes:
        key = getattr(note, "node", "")
        was = getattr(note, "region_hash", "") or ""
        region = getattr(note, "region", "") or ""
        if not was:
            found[id(note)] = Standing(state=UNKNOWN, region=region)
            continue
        if key not in cached:
            node = graph.nodes.get(key)
            cached[key] = (
                bounded_region(graph, node, Path(root)) if node else ("", "")
            )
        now_region, now = cached[key]
        found[id(note)] = Standing(
            state=CURRENT if now and now == was else MOVED,
            region=now_region or region,
            was=was,
            now=now,
        )
    return found
