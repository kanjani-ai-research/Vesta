"""What an agent decided, written down.

Vesta needs judgement — what work a repository performs, which definitions do
which of it, whether a correction is a rule, whether a defect is findable. It
does not need to *perform* that judgement itself, and doing so was a mistake:
every derivation went through litellm to an API the user had to hold a key for,
in a tool the user installs as a plugin to an agent that already has a model.

**So the judging moved to where the model already is.** A plugin agent runs on
the host's inference, declares which model it wants in its frontmatter, and
costs the user nothing beyond what they are already paying.

Which model is not a preference. Analysis of text — reading a definition and
labelling it, reading a turn and classifying it — runs on haiku, because it
happens once for every definition and every turn, and a larger model at that
volume makes the approach too expensive to use at all. Synthesis somebody will
be held to, which happens once per project, runs on sonnet.
What it cannot do is persist structure, because an agent produces prose. This is
the seam: the agent decides, and calls this to write the decision down.

**Nothing here judges anything.** It parses, validates against the graph, and
writes. A term naming no definition is recorded as naming none; an attachment
pointing at a line no definition contains is refused rather than stored, because
a map that points nowhere is worse than a smaller one.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
import time
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from .domain import Ontology, _mark, _speaks, _where
from .graph import Graph, Node
from .held import graph_for
from .traverse import Attachment, Map, Term
from .traverse import keep as keep_map
from .traverse import recall as recall_map

logger = logging.getLogger("vesta.derive")

# How a term is written by an agent: `kind: label`.
TERM = re.compile(r"^\s*(domain|activity|role)\s*:\s*(.+?)\s*$", re.I)

# How an attachment is written: `path:line Name | term label`.
ATTACHMENT = re.compile(r"^\s*([^\s:]+):(\d+)\s+(\S+)\s*\|\s*(.+?)\s*$")


def read_terms(text: str) -> List[Term]:
    """Parse what an agent named, ignoring whatever else it wrote.

    Forgiving on purpose: an agent asked for a list will sometimes preface it,
    number it, or bullet it, and refusing the whole batch over a stray line
    would make the seam brittle at exactly the point where it must not be.
    """
    found: List[Term] = []
    for line in text.splitlines():
        line = line.lstrip("-*• \t")
        matched = TERM.match(line)
        if not matched:
            continue
        kind, label = matched.group(1).lower(), matched.group(2).strip()
        if len(label) < 3:
            continue
        found.append(
            Term(id=f"{kind}:{len(found)}-{abs(hash(label)) % 100000}", kind=kind, label=label)
        )
    return found


def read_attachments(text: str, graph: Graph) -> Tuple[List[Tuple[str, str]], List[str]]:
    """Parse what an agent attached, and say what could not be placed.

    Each line names a definition by path and line and the term that names what
    it does. An attachment whose definition the graph does not hold is refused:
    a map pointing at nothing is worse than a smaller map.
    """
    placed: List[Tuple[str, str]] = []
    refused: List[str] = []

    for line in text.splitlines():
        line = line.lstrip("-*• \t")
        matched = ATTACHMENT.match(line)
        if not matched:
            continue
        where, number, _name, label = matched.groups()
        node = _node_at(graph, where, int(number))
        if node is None:
            refused.append(f"{where}:{number} — no definition there")
            continue
        placed.append((node.id, label.strip()))
    return placed, refused


def _node_at(graph: Graph, where: str, line: int) -> Optional[Node]:
    """The definition an agent meant, by path and line.

    Agents cite the line a definition starts on, and a graph records the same,
    but an agent reading a file may be a line out either way — so the exact
    line is tried first and its neighbours after.
    """
    wanted = where.lstrip("./")
    for node in graph.nodes.values():
        if node.path != wanted and not node.path.endswith("/" + wanted):
            continue
        if abs((node.line + 1) - line) <= 2:
            return node
    return None


def write_terms(repo: Path | str, text: str) -> Ontology:
    """Keep what an agent named as this repository's ontology."""
    root = Path(repo).expanduser().resolve()
    terms = read_terms(text)
    said = _speaks(root)

    found = Ontology(
        project=str(root),
        purpose="named by an agent reading the repository",
        terms=[{"id": t.id, "kind": t.kind, "label": t.label} for t in terms],
        modules=_mark(root, said),
        derived_at=time.time(),
    )
    _where(root).write_text(found.model_dump_json(), encoding="utf-8")
    return found


def write_attachments(repo: Path | str, text: str) -> Tuple[Map, List[str]]:
    """Keep what an agent attached, adding to whatever is already mapped."""
    root = Path(repo).expanduser().resolve()
    graph = graph_for(root, trust_for=600)
    placed, refused = read_attachments(text, graph)

    mapped = recall_map(root) or Map(ontology="read by an agent")
    from .domain import recall as recall_ontology

    ontology = recall_ontology(root)
    by_label = {
        t["label"].strip().lower(): t for t in (ontology.terms if ontology else [])
    }

    already = {(a.node, a.label.lower()) for a in mapped.attachments}
    for node_id, label in placed:
        if (node_id, label.lower()) in already:
            continue
        term = by_label.get(label.lower())
        mapped.attachments.append(
            Attachment(
                node=node_id,
                term=term["id"] if term else f"loose:{abs(hash(label)) % 100000}",
                label=term["label"] if term else label,
                kind=term.get("kind", "") if term else "",
                strength=1.0,
                how="read",
            )
        )
        already.add((node_id, label.lower()))

    attached = {a.label.lower() for a in mapped.attachments}
    mapped.unattached = [
        t["label"] for t in (ontology.terms if ontology else [])
        if t["label"].lower() not in attached
    ]
    keep_map(mapped, root)
    return mapped, refused


def _waiting(root: Path) -> Optional[str]:
    """What to say when the graph is not built, rather than saying nothing.

    An agent asked for definitions and got an empty list, which reads as "this
    repository has none" — a false answer that would send it away. Preparation
    is started and the caller is told, because a silence and an answer must not
    look alike.
    """
    from .ready import prepare, readiness

    state = readiness(root)
    if state.can_answer:
        return None
    prepare(root)
    return (
        f"{state.describe()}. Nothing is being claimed about this repository "
        "yet — the graph is being built in the background. Carry on; ask again "
        "in a minute and this will answer."
    )


def definitions_worth_reading(repo: Path | str, limit: int = 80) -> List[str]:
    """The definitions an agent should read, most depended upon first.

    Public and non-test: a private helper is about whatever its caller is about,
    and reading every one of them is most of the cost for least of the meaning.
    """
    root = Path(repo).expanduser().resolve()
    graph = graph_for(root, trust_for=600)
    wanted = [
        node
        for node in graph.nodes.values()
        if not node.name.startswith("_") and "test" not in node.path
    ]
    wanted.sort(key=lambda n: -len(graph.referenced_by(n.id)))
    return [
        f"{n.path}:{n.line + 1} {n.qualified}"
        for n in wanted[:limit]
    ]


def main(argv: Optional[Sequence[str]] = None) -> int:
    """The seam an agent calls. Reads its decision on stdin, writes it down."""
    parser = argparse.ArgumentParser(
        prog="vesta-domain",
        description="Record what an agent decided about a repository.",
    )
    parser.add_argument("--repo", required=True)
    parser.add_argument("--write", action="store_true", help="read terms on stdin")
    parser.add_argument("--attach", action="store_true", help="read attachments on stdin")
    parser.add_argument(
        "--definitions", action="store_true", help="list what is worth reading"
    )
    parser.add_argument("--limit", type=int, default=80)
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.WARNING, stream=sys.stderr)
    root = Path(args.repo).expanduser().resolve()

    if args.definitions:
        waiting = _waiting(root)
        if waiting:
            print(waiting, file=sys.stderr)
            return 2  # nothing to read yet, and not an error in the caller
        for line in definitions_worth_reading(root, args.limit):
            print(line)
        return 0

    if args.write:
        found = write_terms(root, sys.stdin.read())
        print(f"kept {len(found.terms)} term(s) for {root}")
        return 0

    if args.attach:
        waiting = _waiting(root)
        if waiting:
            print(waiting, file=sys.stderr)
            return 2
        mapped, refused = write_attachments(root, sys.stdin.read())
        print(f"kept {len(mapped.attachments)} attachment(s) for {root}")
        for why in refused[:8]:
            print(f"  refused: {why}")
        return 0

    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
