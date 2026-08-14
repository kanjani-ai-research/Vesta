"""A graph per path, and larger graphs made from smaller ones.

**A directory holding several projects is not one project.** Vesta built one
graph for whatever root it was given, so a workspace of thirteen repositories
was 6,309 definitions in a single artifact that took 73 seconds to produce —
and touching one file in one of them made the whole thing stale. The next
question then paid all 73 seconds to rebuild twelve projects that had not
changed. Measured inside a prompt, that took a hook past two minutes.

The shape that fixes it is the one the tree already has. Each project gets its
own graph, keyed by its own path, and a question about the directory above is
answered by composing the graphs beneath it. Editing `nike` invalidates
`nike`, which rebuilds in seconds; every other graph stays current and the
composed answer is assembled from parts that are individually fresh.

**Composition is not a merge of opinions.** These graphs do not disagree —
each is a faithful description of a disjoint subtree — so joining them is
mechanical: rebase every path onto the shared root, re-derive every node id
from the rebased path, and rewrite the edges to match. Nothing is judged and
nothing is reconciled, which is why this can be trusted.

**What composing does not recover is a reference between two projects.** If
`mercury` imports from `metis`, that edge exists in neither graph, because
neither resolver was shown the other's files. The composed graph says so
rather than implying completeness: the crossing edges are counted as holes.
For a workspace of independent components that is usually the truth anyway —
and where it is not, the honest report is better than a silent omission.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from .graph import Edge, Graph, Hole, Node, _node_id
from .home import NOT_THE_PROJECT

logger = logging.getLogger("vesta.compose")

# What marks a directory as a project in its own right rather than a folder
# inside one. Any of these is enough: a repository, a package manifest, or the
# conventional layout of a source tree.
A_PROJECT = (
    ".git",
    "pyproject.toml", "setup.py", "setup.cfg",
    "package.json", "deno.json",
    "Cargo.toml", "go.mod", "pom.xml", "build.gradle", "build.gradle.kts",
    "Gemfile", "composer.json", "mix.exs", "CMakeLists.txt", "Makefile",
)


def parts_of(root: Path | str, depth: int = 2) -> List[Path]:
    """The projects inside a directory, or nothing if it is one itself.

    Shallow on purpose. A workspace holds its components one or two levels
    down, and looking deeper would find every package inside every project and
    call each one a project — which is how a sensible idea becomes thousands of
    graphs.

    A directory that is itself a project is never split, however many projects
    sit beneath it: somebody working in a repository that vendors another has
    one project, and the graph they want spans both.
    """
    root = Path(root).expanduser().resolve()
    if not root.is_dir():
        return []
    if _is_a_project(root):
        return []

    found: List[Path] = []
    _gather(root, depth, found)
    return sorted(found)


def _is_a_project(where: Path) -> bool:
    return any((where / mark).exists() for mark in A_PROJECT)


def _gather(where: Path, depth: int, found: List[Path]) -> None:
    if depth <= 0:
        return
    try:
        entries = sorted(where.iterdir())
    except OSError:
        return
    for entry in entries:
        if entry.name.startswith(".") or entry.name in NOT_THE_PROJECT:
            continue
        if not entry.is_dir():
            continue
        if _is_a_project(entry):
            found.append(entry)
        else:
            _gather(entry, depth - 1, found)


def rebase(graph: Graph, under: Path, root: Path) -> Graph:
    """One project's graph, expressed as part of a larger tree.

    Every path is prefixed with where the project sits under the shared root,
    and every node id is re-derived from the new path — ids are
    `sha256(path, line, name)`, so a node has a different id in its own graph
    than in a composed one, and the edges have to be rewritten to match. Doing
    that wrongly would silently break every reference in the composed result,
    so it is done in one place and tested.
    """
    try:
        prefix = under.relative_to(root)
    except ValueError:
        return graph

    moved = Graph(root=str(root))
    renamed: Dict[str, str] = {}

    for node in graph.nodes.values():
        path = str(prefix / node.path)
        fresh = _node_id(path, node.line, node.name)
        renamed[node.id] = fresh
        moved.nodes[fresh] = Node(
            id=fresh,
            name=node.name,
            path=path,
            line=node.line,
            kind=node.kind,
            container=node.container,
        )

    for edge in graph.edges:
        source = renamed.get(edge.source)
        target = renamed.get(edge.target)
        if source is None or target is None:
            continue
        at = edge.at
        if at:
            at = str(prefix / at) if not at.startswith("/") else at
        moved.edges.append(
            Edge(source=source, target=target, kind=edge.kind, at=at)
        )

    for hole in graph.holes:
        moved.holes.append(
            Hole(path=str(prefix / hole.path), what=hole.what, why=hole.why)
        )

    moved.built_in = graph.built_in
    return moved


def composed(root: Path | str, parts: Sequence[Path], of: Dict[str, Graph]) -> Graph:
    """One graph for a directory, assembled from the graphs of its projects.

    `of` maps each project's path to its own graph; a project absent from it is
    one whose graph is not built yet, and is reported as a hole rather than
    silently omitted. A composed graph that quietly covers half a workspace is
    worse than one that says which half.
    """
    root = Path(root).expanduser().resolve()
    whole = Graph(root=str(root))

    for part in parts:
        graph = of.get(str(part))
        if graph is None:
            whole.holes.append(
                Hole(
                    path=str(part.relative_to(root)) if part != root else ".",
                    what="a project in this directory",
                    why="its graph is not built yet",
                )
            )
            continue
        moved = rebase(graph, part, root)
        whole.nodes.update(moved.nodes)
        whole.edges.extend(moved.edges)
        whole.holes.extend(moved.holes)
        whole.built_in += moved.built_in

    # References that cross from one project into another exist in neither
    # graph, because neither resolver was shown the other's files. Said plainly
    # rather than left to look like an absence of references.
    if len(parts) > 1:
        whole.holes.append(
            Hole(
                path=".",
                what=f"references between the {len(parts)} projects here",
                why=(
                    "each project was resolved on its own, so a reference from "
                    "one into another is not in either graph"
                ),
            )
        )
    return whole
