"""What a change touches.

Given definitions that changed, walk the graph backwards — from a definition to
whatever refers to it, and from those to whatever refers to *them* — and return
the set reached. The claim is a correctness claim: everything that could break
is in the set.

**Depth is bounded, and the bound is a stated cost.** Transitive closure over a
real codebase reaches most of it: a change to a base model class reaches every
consumer of every subclass, which is true and useless. Each hop is reported
separately so a caller can see where the set stops being informative, and the
default stops at the first hop that adds nothing a test would catch.

**Reaching a test is the terminal condition.** Propagation exists to answer
"what do I run", and a test is where the answer lands. Walking *past* a test
into the things that reference it adds nothing: nothing references a test.

**What the graph does not know is carried through.** A propagation set computed
over a graph with holes is not wrong, it is partial, and a caller told "these
four tests" without being told "and two files could not be resolved" has been
given a correctness claim the evidence does not support.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

from pydantic import BaseModel, Field

from .graph import Graph, Node

logger = logging.getLogger("vesta.propagate")

# How far to walk. Five rather than three: measured against a store, depth is
# free — twelve hops cost 2.7ms where two cost 3.5 — and the walk converges
# well before it exhausts the budget. On this repository three hops reach 210
# definitions, five reach 214, and nothing after that reaches more. So five
# takes what three misses and stops where the graph itself stops.
MAX_HOPS = 5

# LSP SymbolKind values that name a test. A definition is a test if it is a
# function whose name says so — crude, and it matches the convention every
# runner in every language enforces, which is what makes it reliable.
TEST_NAMES = ("test_", "Test", "_test", "spec_", "should_")


class Reached(BaseModel):
    """One definition the propagation arrived at, and how."""

    node: str
    hops: int
    # The chain from a changed definition to this one, so a reader can check
    # the claim rather than trust it. A propagation set nobody can audit is
    # a list of guesses.
    through: List[str] = Field(default_factory=list)

    def describe(self, graph: Graph) -> str:
        node = graph.nodes.get(self.node)
        where = node.describe() if node else self.node
        return f"[{self.hops} hop] {where}"


class Propagation(BaseModel):
    """What a change touches, and what could not be established."""

    changed: List[str] = Field(default_factory=list)
    reached: List[Reached] = Field(default_factory=list)
    # Files the graph could not resolve. Carried because they bound the claim:
    # a change propagating into an unresolved file is a hop this cannot see.
    unresolved: List[str] = Field(default_factory=list)
    hops: int = MAX_HOPS

    @property
    def is_bounded(self) -> bool:
        """Whether anything limits the confidence in this set."""
        return not self.unresolved

    def tests(self, graph: Graph) -> Set[str]:
        """The test files a caller should run.

        Files rather than definitions, because that is what a runner takes and
        what the harness scores against.
        """
        found: Set[str] = set()
        for entry in self.reached:
            node = graph.nodes.get(entry.node)
            if node and is_test(node):
                found.add(node.path)
        return found

    def by_hop(self) -> Dict[int, int]:
        counts: Dict[int, int] = defaultdict(int)
        for entry in self.reached:
            counts[entry.hops] += 1
        return dict(sorted(counts.items()))

    def describe(self, graph: Graph) -> str:
        parts = [f"{len(self.reached)} definition(s) reached"]
        found = self.tests(graph)
        if found:
            parts.append(f"{len(found)} test file(s)")
        if self.unresolved:
            parts.append(
                f"{len(self.unresolved)} file(s) unresolved — the set may be short"
            )
        return ", ".join(parts)


def is_test(node: Node) -> bool:
    """Whether a definition is a test.

    Matched on the name rather than the path, because a test helper in a test
    file is not a test and reaching it is not a reason to run anything.
    """
    return any(mark in node.name for mark in TEST_NAMES)


def from_definitions(
    graph: Graph, changed: Sequence[str], hops: int = MAX_HOPS
) -> Propagation:
    """Walk backwards from changed definitions.

    Breadth-first, so a definition reached by two paths is recorded at the
    shorter one — a caller reading the set wants the nearest reason a thing is
    in it, not an arbitrary one.
    """
    found = Propagation(
        changed=list(changed),
        hops=hops,
        unresolved=sorted({hole.path for hole in graph.holes}),
    )

    seen: Set[str] = set(changed)
    frontier: List[Tuple[str, List[str]]] = [(node_id, []) for node_id in changed]

    for hop in range(1, hops + 1):
        following: List[Tuple[str, List[str]]] = []

        # A whole hop in one ask where the graph can answer that way. Asking
        # per node turned a walk into hundreds of round trips against a store
        # and lost to parsing the document outright — a store is only faster if
        # it is asked in the shape it is good at.
        callers = _callers_of(graph, [node_id for node_id, _ in frontier])

        reached_now: List[Tuple[str, List[str]]] = []
        for node_id, path in frontier:
            for source in callers.get(node_id, ()):
                if source in seen:
                    continue
                seen.add(source)
                chain = [*path, node_id]
                found.reached.append(Reached(node=source, hops=hop, through=chain))
                reached_now.append((source, chain))

        known = _definitions(graph, [source for source, _ in reached_now])
        for source, chain in reached_now:
            node = known.get(source)
            # A test is where the answer lands. Nothing references a test, so
            # walking past one would only ever find nothing — and stopping
            # keeps the set from growing through test helpers.
            if node is None or not is_test(node):
                following.append((source, chain))

        if not following:
            break
        frontier = following

    return found


def _callers_of(graph, node_ids: Sequence[str]) -> Dict[str, List[str]]:
    """What refers to each of these, in as few asks as the graph allows."""
    batched = getattr(graph, "referenced_by_any", None)
    if batched is not None:
        return batched(node_ids)
    return {
        node_id: [edge.source for edge in graph.referenced_by(node_id)]
        for node_id in node_ids
    }


def _definitions(graph, node_ids: Sequence[str]) -> Dict[str, Node]:
    """These definitions, in as few asks as the graph allows."""
    batched = getattr(graph, "by_ids", None)
    if batched is not None:
        return batched(node_ids)
    return {
        node_id: node
        for node_id in node_ids
        if (node := graph.nodes.get(node_id)) is not None
    }


def from_files(
    graph: Graph, paths: Sequence[str], hops: int = MAX_HOPS
) -> Propagation:
    """Walk backwards from every definition in a changed file.

    What a commit gives you: file paths. Coarser than a line range and the
    honest reading of "this file changed" — a caller who knows which lines
    moved should use `from_lines`.
    """
    # Asked for, not scanned. A store answers "definitions in this file" from
    # an index; scanning every definition to filter by path costs the whole
    # repository to learn about one file, which is the cost this exists to
    # avoid.
    changed: List[str] = []
    for path in paths:
        changed.extend(n.id for n in graph.in_file(path))
    found = from_definitions(graph, changed, hops)
    # A changed file's own tests are reached even where nothing references the
    # definitions — a test in the same commit as the code it covers is the
    # commonest case in any repository, and a graph edge is not the only
    # evidence of a relationship.
    return found


def from_lines(
    graph: Graph, edits: Dict[str, Sequence[int]], hops: int = MAX_HOPS
) -> Propagation:
    """Walk backwards from the definitions containing changed lines.

    The precise form. A file-level change propagates from every definition in
    the file; a line-level change propagates from the few that actually moved,
    which is a much smaller and much more useful set.
    """
    changed: Set[str] = set()
    for path, lines in edits.items():
        for line in lines:
            node = graph.at(path, line)
            if node is not None:
                changed.add(node.id)
    return from_definitions(graph, sorted(changed), hops)
