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
from .home import home

logger = logging.getLogger("vesta.harvest")

# Where harvested understanding is kept, beside the graphs it attaches to.
NOTES = home() / "notes"

# Where the host keeps its sessions. Read-only, and treated as a format that
# may change: anything unparseable is skipped rather than fatal.
TRANSCRIPTS = Path.home() / ".claude" / "projects"

# A citation an agent wrote: `vesta/acquire.py:464`, `acquire.py:464`.
CITATION = re.compile(r"\b([\w./-]+\.[a-zA-Z]{1,4}):(\d+)\b")

# Prose short enough to be a label rather than an account is not worth keeping;
# prose long enough to be a whole answer is not about one definition.
LEAST_USEFUL = 120
MOST_USEFUL = 4000


def anchor(text: str, graph: Graph) -> str:
    """Rewrite the citations in an account to paths this graph knows.

    An agent writes the path it was looking at, which is relative to whatever
    root its session had. Replayed in another session that root may differ, and
    a reader following `vesta/acquire.py` from inside the vesta repository lands
    at `vesta/vesta/acquire.py` and finds nothing. A live agent hit exactly
    this, said "the path was doubled", and read the file the long way.
    """
    known = {node.path for node in graph.nodes.values()}

    def fix(match: "re.Match") -> str:
        cited, line = match.group(1), match.group(2)
        if cited in known:
            return match.group(0)
        bare = cited.lstrip("./")
        for path in known:
            if path == bare or path.endswith("/" + bare) or bare.endswith("/" + path):
                return f"{path}:{line}"
        return match.group(0)

    return CITATION.sub(fix, text)


class Note(BaseModel):
    """Something an agent worked out about a definition."""

    node: str
    path: str
    line: int
    text: str
    session: str = ""
    at: float = 0.0
    # The span the claim was about, and its hash at the moment the claim was
    # made. A timestamp says when somebody looked; this says *at what*, which
    # is the only thing that makes a later check possible. A live agent
    # verified every note it was given because nothing here could tell it
    # whether the ground had moved.
    region: str = ""
    region_hash: str = ""

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


# How many times a session must name a repository before it counts as being
# about it. One mention is somebody pasting a path; a session that worked on a
# repository names it constantly.
MENTIONS_ENOUGH = 20

# How many times **the user** must name it. Counted separately and required
# alongside the total, because the total cannot tell working from discussing.
#
# Found by looking. A session spent building something else, which happened to
# run commands against `~/Research/taguchi` to test a tool, mentioned that path
# 59 times — past the threshold — in tool results and assistant output. The
# user never named it once. The whole transcript was then admitted as taguchi's
# own history, so rules stated about a different project would have been
# recovered as decisions about that one.
#
# Two mentions is enough to clear the bar of somebody pasting a path in
# passing, and low enough not to lose a genuine session where the user names
# their repository rarely because they are working *inside* it.
SAID_BY_USER = 2

# Sessions already matched to a repository, keyed by the state of the
# transcript directory. Scanning every transcript for path mentions is not
# free, and it does not change between two questions asked a second apart.
_MATCHED: Dict[str, Tuple[str, List[Path]]] = {}


def _user_named(path: Path, repo: str) -> int:
    """How many times the user themselves named a repository in a transcript.

    Only turns the user actually spoke — not tool results, not assistant
    output, not harness-injected context. Those are where a session that merely
    *ran commands against* a repository accumulates hundreds of mentions of it
    while nobody was working on it at all.
    """
    from .rules import _not_the_user

    said = 0
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return 0

    for line in lines:
        if repo not in line:
            continue
        try:
            payload = json.loads(line)
        except ValueError:
            continue
        if payload.get("type") != "user" or payload.get("toolUseResult"):
            continue

        message = payload.get("message") or {}
        content = message.get("content")
        if isinstance(content, str):
            spoken = content
        elif isinstance(content, list):
            spoken = " ".join(
                b.get("text", "")
                for b in content
                if isinstance(b, dict) and b.get("type") == "text"
            )
        else:
            continue

        if repo in spoken and not _not_the_user(spoken.strip()):
            said += 1
    return said


def _sessions_for(repo: Path) -> List[Path]:
    """Transcripts of work on this repository, wherever they were recorded.

    **Not only the directory named after it.** The host keys a project by where
    the agent was *launched*, not by what it worked on, so a session started one
    level up records months of work on a repository under a different name
    entirely. Vesta's own history is the case: seventeen sessions sit under its
    own name, all of them test runs, while the three thousand turns that built
    it live under the directory the agent happened to start in. Keyed by launch
    directory, a project cannot see its own past.

    So the directory named after the repository is taken, and every other
    transcript that names the repository often enough to have been working on
    it. A path mentioned once is somebody pasting it; a repository being worked
    on is named constantly.
    """
    import hashlib

    if not TRANSCRIPTS.is_dir():
        return []

    named = str(repo).replace("/", "-")
    obvious = TRANSCRIPTS / named
    found = sorted(obvious.glob("*.jsonl")) if obvious.is_dir() else []

    # What the transcript directory looks like now, so the scan is done once.
    try:
        marks = sorted(
            f"{d.name}:{int(d.stat().st_mtime)}" for d in TRANSCRIPTS.iterdir()
        )
    except OSError:
        return found
    state = hashlib.sha256("\n".join(marks).encode("utf-8")).hexdigest()[:16]

    remembered = _MATCHED.get(str(repo))
    if remembered and remembered[0] == state:
        return remembered[1]

    # On disk as well as in memory. Deciding which sessions belong to a
    # repository means reading every transcript and counting mentions — fifty
    # megabytes and a second and a half here — and a hook is a fresh process
    # every time, so an in-memory cache is never the one that is read.
    from .home import kept_at

    kept = kept_at(repo, "sessions")
    if kept.is_file():
        try:
            payload = json.loads(kept.read_text(encoding="utf-8"))
            if payload.get("state") == state:
                found = [Path(p) for p in payload["sessions"] if Path(p).is_file()]
                _MATCHED[str(repo)] = (state, found)
                return found
        except (OSError, ValueError, KeyError):
            pass

    wanted = str(repo).encode("utf-8")
    for directory in sorted(TRANSCRIPTS.iterdir()):
        if not directory.is_dir() or directory.name == named:
            continue
        for path in sorted(directory.glob("*.jsonl")):
            try:
                if path.read_bytes().count(wanted) < MENTIONS_ENOUGH:
                    continue
            except OSError:
                continue
            # Cheap count passed. Now the one that means something: a
            # transcript belongs to a repository because somebody *worked* in
            # it, and the evidence of that is the user naming it — not a tool
            # result quoting a path back, which a session testing something
            # else produces by the dozen.
            if _user_named(path, str(repo)) >= SAID_BY_USER:
                found.append(path)

    _MATCHED[str(repo)] = (state, found)
    try:
        kept.write_text(
            json.dumps({"state": state, "sessions": [str(p) for p in found]}),
            encoding="utf-8",
        )
    except OSError:
        pass
    return found


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


# Harvests already read, keyed by the repository and the state of its
# transcripts. Re-reading every session on every call cost thirteen seconds on
# the first `known` in a live run, and that grows with every session a user
# has — the opposite of the accumulation this is supposed to reward.
_HARVESTED: Dict[str, Tuple[str, "Harvest"]] = {}


def _state_of(paths: Sequence[Path]) -> str:
    """A fingerprint of the transcripts, so a new session invalidates the cache."""
    import hashlib

    marks = []
    for path in paths:
        try:
            stat = path.stat()
            marks.append(f"{path}:{stat.st_size}:{int(stat.st_mtime)}")
        except OSError:
            continue
    return hashlib.sha256("\n".join(marks).encode("utf-8")).hexdigest()[:16]


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
    paths = list(transcripts) if transcripts is not None else _sessions_for(root)

    state = _state_of(paths)
    remembered = _HARVESTED.get(str(root))
    if remembered and remembered[0] == state and not since:
        return remembered[1]

    # On disk too. Extracting notes means parsing every transcript — fifty
    # megabytes and most of a second here — and a hook is a fresh process, so
    # an in-memory cache is paid for and never read.
    from .home import kept_at

    kept = kept_at(root, "harvests")
    if not since and kept.is_file():
        try:
            payload = json.loads(kept.read_text(encoding="utf-8"))
            if payload.get("state") == state:
                found = Harvest.model_validate(payload["harvest"])
                _HARVESTED[str(root)] = (state, found)
                return found
        except (OSError, ValueError, KeyError):
            pass

    found = Harvest()
    seen: Set[Tuple[str, str]] = set()
    # Stamps already written for this repository, so a claim keeps the region
    # it was first seen against rather than being re-anchored to today's code.
    _stamped: Dict[str, Tuple[str, str]] = _load_stamps(root)

    for path in paths:
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
                        # Stamped once, at first sight, and never recomputed.
                        #
                        # Re-stamping from the current code on every read made
                        # the check circular: a note always described what the
                        # code looks like now, so nothing was ever superseded
                        # and the whole mechanism said "current" forever. What
                        # a claim was made about is a fact about the past, and
                        # the only way to hold it is to write it down the first
                        # time and leave it alone.
                        region, digest = _stamped.get(node) or ("", "")
                        if not digest:
                            from .authority import bounded_region

                            region, digest = bounded_region(
                                graph, graph.nodes[node], root
                            )
                            _stamped[node] = (region, digest)
                        found.notes.append(
                            Note(
                                node=node,
                                path=graph.nodes[node].path,
                                line=graph.nodes[node].line,
                                text=passage,
                                session=path.stem,
                                at=stamp,
                                region=region,
                                region_hash=digest,
                            )
                        )

    _save_stamps(root, _stamped)
    if not since:
        _HARVESTED[str(root)] = (state, found)
        try:
            kept.write_text(
                json.dumps({"state": state, "harvest": found.model_dump(mode="json")}),
                encoding="utf-8",
            )
        except OSError:
            pass
    return found


def _stamp_file(root: Path) -> Path:
    import hashlib

    NOTES.mkdir(parents=True, exist_ok=True)
    return NOTES / f"{root.name}-{hashlib.sha256(str(root).encode()).hexdigest()[:12]}-stamps.json"


def _load_stamps(root: Path) -> Dict[str, Tuple[str, str]]:
    path = _stamp_file(root)
    if not path.is_file():
        return {}
    try:
        return {k: tuple(v) for k, v in json.loads(path.read_text(encoding="utf-8")).items()}
    except (OSError, ValueError):
        return {}


def _save_stamps(root: Path, stamps: Dict[str, Tuple[str, str]]) -> None:
    try:
        _stamp_file(root).write_text(
            json.dumps({k: list(v) for k, v in stamps.items()}), encoding="utf-8"
        )
    except OSError:
        pass


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
