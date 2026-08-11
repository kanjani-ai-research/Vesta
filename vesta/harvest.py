"""Keeping the understanding a framework already produced.

An agent reads a file, works out what it does, says so, and the session ends.
The reading was paid for, the reasoning was paid for, and both are discarded.
The next session reads the same file and pays again.

**This is the semantics the rest of the project could not compute.** Attaching
code to meaning by string overlap does not work: `_resolve_with` matches
"resolve symbol references" because the token appears in both, not because
anything understood the function, and a function called `harvest` that resolved
symbols would match nothing. Meanwhile a real agent, given the same code, wrote
a three-tier account of how `Search.for_` handles failures with the line numbers
for each tier. That is semantic understanding, it already happened, and nothing
kept it.

**Attribution is by citation, not by inference.** Agents write `file.py:464`
constantly, and a graph already answers which definition contains a line. A
claim is attached where its author pointed, so a wrong attachment means the
author pointed wrongly rather than that a heuristic guessed. Prose citing
nothing is not attached to anything.

**What is harvested is a claim, not a fact.** An agent can be confidently wrong,
and its account is evidence about the code rather than the code itself. Each
carries its session and when it was written, so a reader can weigh it and a
stale one can be dropped when the file it describes has changed.
"""

from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

from pydantic import BaseModel, Field

from .graph import Graph
from .structure import VESTA_HOME

logger = logging.getLogger("vesta.harvest")

# Where harvested understanding is kept, beside the graphs it attaches to.
NOTES = VESTA_HOME / "notes"

# Where the host keeps its sessions. Read-only, and treated as a format that
# may change: anything unparseable is skipped rather than fatal.
TRANSCRIPTS = Path.home() / ".claude" / "projects"

# A citation an agent wrote: `vesta/acquire.py:464`, `acquire.py:464`.
CITATION = re.compile(r"\b([\w./-]+\.[a-zA-Z]{1,4}):(\d+)\b")

# Prose short enough to be a label rather than an account is not worth keeping;
# prose long enough to be a whole answer is not about one definition.
LEAST_USEFUL = 120
MOST_USEFUL = 4000


class Note(BaseModel):
    """Something an agent worked out about a definition."""

    node: str
    path: str
    line: int
    text: str
    session: str = ""
    at: float = 0.0

    def describe(self) -> str:
        when = time.strftime("%Y-%m-%d", time.localtime(self.at)) if self.at else ""
        return f"{self.path}:{self.line + 1} ({when}) {self.text[:160]}"


class Harvest(BaseModel):
    """What was kept from a set of sessions, and what could not be."""

    notes: List[Note] = Field(default_factory=list)
    sessions: int = 0
    # Citations pointing at a file or line the graph does not know. Kept as a
    # count rather than discarded silently: a large number means the graph and
    # the transcripts disagree about the repository.
    unplaced: int = 0

    def for_node(self, node_id: str) -> List[Note]:
        return sorted(
            [n for n in self.notes if n.node == node_id], key=lambda n: -n.at
        )

    def describe(self) -> str:
        parts = [f"{len(self.notes)} note(s) from {self.sessions} session(s)"]
        if self.unplaced:
            parts.append(f"{self.unplaced} citation(s) placed nowhere")
        return ", ".join(parts)


def _sessions_for(repo: Path) -> List[Path]:
    """Transcript files the host wrote for this repository.

    The host names a project directory after its path with separators replaced,
    which is a convention rather than a contract — so a miss returns nothing
    and the caller carries on rather than failing.
    """
    slug = str(repo).replace("/", "-")
    directory = TRANSCRIPTS / slug
    if not directory.is_dir():
        return []
    return sorted(directory.glob("*.jsonl"))


def _prose(payload: dict) -> Iterable[str]:
    """Assistant prose from one transcript line, if it holds any."""
    message = payload.get("message") or {}
    if message.get("role") != "assistant":
        return
    content = message.get("content")
    if not isinstance(content, list):
        return
    for block in content:
        if isinstance(block, dict) and block.get("type") == "text":
            said = (block.get("text") or "").strip()
            if said:
                yield said


def _passages(said: str) -> List[str]:
    """Split an answer into parts small enough to be about one definition.

    A whole answer cites many files; a paragraph usually cites one. Splitting
    keeps a claim near the citation that places it, so an account of one
    function does not get attached to every function the answer mentions.
    """
    parts = [p.strip() for p in re.split(r"\n\s*\n", said) if p.strip()]
    return [p for p in parts if LEAST_USEFUL <= len(p) <= MOST_USEFUL]


def from_sessions(
    graph: Graph,
    repo: Path | str,
    since: float = 0.0,
    transcripts: Optional[Sequence[Path]] = None,
) -> Harvest:
    """Read what agents have already worked out about this repository.

    Cheap by construction: the reading and the reasoning were paid for by
    whoever ran the session. This only picks it up.
    """
    root = Path(repo).expanduser().resolve()
    found = Harvest()
    seen: Set[Tuple[str, str]] = set()

    for path in transcripts if transcripts is not None else _sessions_for(root):
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        found.sessions += 1
        stamp = path.stat().st_mtime if path.exists() else 0.0

        for line in lines:
            try:
                payload = json.loads(line)
            except ValueError:
                continue
            if since and payload.get("timestamp", 0) and payload["timestamp"] < since:
                continue

            for said in _prose(payload):
                for passage in _passages(said):
                    for cited, where in CITATION.findall(passage):
                        node = _place(graph, cited, int(where))
                        if node is None:
                            found.unplaced += 1
                            continue
                        # One claim per definition per passage: an answer that
                        # cites the same function three times is one account of
                        # it, not three.
                        key = (node, passage[:80])
                        if key in seen:
                            continue
                        seen.add(key)
                        found.notes.append(
                            Note(
                                node=node,
                                path=graph.nodes[node].path,
                                line=graph.nodes[node].line,
                                text=passage,
                                session=path.stem,
                                at=stamp,
                            )
                        )

    return found


def _place(graph: Graph, cited: str, line: int) -> Optional[str]:
    """The definition a citation points at.

    Agents cite paths as they please — `acquire.py:464`, `vesta/acquire.py:464`,
    sometimes absolute — so a suffix match is what actually resolves them. An
    ambiguous suffix is refused rather than guessed: attaching one function's
    account to another's is worse than attaching nothing.
    """
    wanted = cited.lstrip("./")
    candidates = {
        node.path
        for node in graph.nodes.values()
        if node.path == wanted or node.path.endswith("/" + wanted)
    }
    if len(candidates) != 1:
        return None

    node = graph.at(candidates.pop(), max(0, line - 1))
    return node.id if node else None


def keep(harvest: Harvest, repo: Path | str) -> Path:
    """Write what was harvested, so it survives the session that produced it."""
    root = Path(repo).expanduser().resolve()
    NOTES.mkdir(parents=True, exist_ok=True)
    import hashlib

    where = NOTES / f"{root.name}-{hashlib.sha256(str(root).encode()).hexdigest()[:12]}.json"
    where.write_text(harvest.model_dump_json(), encoding="utf-8")
    return where


def recall_notes(repo: Path | str) -> Harvest:
    """What has been harvested for this repository so far."""
    root = Path(repo).expanduser().resolve()
    import hashlib

    where = NOTES / f"{root.name}-{hashlib.sha256(str(root).encode()).hexdigest()[:12]}.json"
    if not where.is_file():
        return Harvest()
    try:
        return Harvest.model_validate_json(where.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return Harvest()
