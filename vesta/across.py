"""Working in one project while referring to another.

A project under works often takes its bearings from one somebody built before:
"do it the way the fuzzy search worked in the indexer". The two are separate
repositories with separate graphs and separate vocabularies, and the question
crosses between them — where does *that* project do the thing I am about to do
here.

**The project under works stays under works.** Its ontology is the one that
answers, its terms take precedence, and a referenced project is consulted
rather than merged. Merging would mean reconciling two independently derived
vocabularies, which is a large problem nobody asked to solve; consulting means
asking the same question of each and saying which answered.

**A reference by name is resolved against what is known, never by scanning.**
Two places know about projects: the framework, through the directories a
session has been given, and Vesta, through everything it has ever prepared. A
name matching one of those is that project. A name matching several needs a
path, and saying so is better than picking. A name matching nothing is not
searched for on disk — a tool that goes hunting through a filesystem for a word
will find something eventually, and it will be wrong.

**What is loaded is what is referred to.** A project mentioned goes on the
list; a project nobody has mentioned for a while comes off it. Nothing is
merged permanently, so forgetting costs nothing and remembering the wrong thing
costs one query.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from pydantic import BaseModel, Field

from .home import home, kept_at
from .tidy import _repositories

logger = logging.getLogger("vesta.across")

# How long a referenced project stays loaded without being mentioned again.
# Long enough to cover a piece of work, short enough that yesterday's reference
# does not shape today's answers.
STAYS = 3600.0


class Project(BaseModel):
    """A repository Vesta can answer about."""

    path: str
    name: str
    prepared: bool = False
    # When this was last referred to, so a project nobody mentions falls away.
    at: float = 0.0

    def describe(self) -> str:
        state = "" if self.prepared else " (not prepared)"
        return f"{self.name} — {self.path}{state}"


class Reference(BaseModel):
    """What a name or path resolved to, or why it could not."""

    project: Optional[Project] = None
    # Where more than one project answers to a name. Reported rather than
    # chosen: picking silently is how a question gets answered about the wrong
    # repository.
    ambiguous: List[Project] = Field(default_factory=list)
    unknown: str = ""

    @property
    def found(self) -> bool:
        return self.project is not None

    def describe(self) -> str:
        if self.project:
            return self.project.describe()
        if self.ambiguous:
            paths = "\n".join(f"    {p.path}" for p in self.ambiguous[:6])
            return (
                f"more than one project is called that:\n{paths}\n"
                "Say which by path."
            )
        return self.unknown or "no project by that name"


def known(roots: Optional[Sequence[Path]] = None) -> List[Project]:
    """Every project that can be referred to.

    Two sources, in order of authority: the directories the framework has given
    this session, which are what the user has actually opened, and everything
    Vesta has prepared before. Nothing else — a filesystem is not searched.
    """
    found: Dict[str, Project] = {}

    # What Vesta has prepared. Older, and still real.
    for _, root in _repositories().items():
        if not root.is_dir():
            continue
        found[str(root)] = Project(path=str(root), name=root.name, prepared=True)

    # What the framework has given this session, which supersedes: a directory
    # the user has open is a project they mean, whether or not it is prepared.
    for root in roots or ():
        root = Path(root).expanduser().resolve()
        if not root.is_dir():
            continue
        found[str(root)] = Project(
            path=str(root), name=root.name, prepared=str(root) in found
        )

    return sorted(found.values(), key=lambda p: p.name)


def resolve(
    said: str, roots: Optional[Sequence[Path]] = None, recent: Optional[Dict[str, float]] = None
) -> Reference:
    """Turn what somebody wrote into a project, or say why it is not one.

    A path is taken as a path. A name is matched against what is known, and
    where several match, the one most recently referred to wins — that is the
    project the user has been working with, and it is the answer they mean.
    Where none is more recent than another, a path is asked for.
    """
    said = said.strip()
    if not said:
        return Reference(unknown="no project was named")

    # A path is unambiguous by construction, whether or not it is prepared —
    # but only something spelled as a path is one. A bare word is a name: run
    # from a repository root, `vesta` names the project and also happens to be
    # a directory inside it, and taking the directory answers about the package
    # rather than the project.
    looks_like_a_path = "/" in said or said.startswith("~") or said.startswith(".")
    spelled = Path(said).expanduser()
    if looks_like_a_path and spelled.is_dir():
        root = spelled.resolve()
        return Reference(
            project=Project(
                path=str(root),
                name=root.name,
                prepared=str(root) in {p.path for p in known()},
            )
        )
    if "/" in said or said.startswith("~"):
        return Reference(
            unknown=f"{said} is not a directory on this machine"
        )

    matching = [p for p in known(roots) if p.name == said]
    if not matching:
        # Deliberately not a search. A tool that hunts a filesystem for a word
        # finds something eventually and it is wrong.
        near = [p for p in known(roots) if said.lower() in p.name.lower()]
        if len(near) == 1:
            return Reference(project=near[0])
        if near:
            return Reference(ambiguous=near)
        return Reference(
            unknown=(
                f"nothing known is called {said!r}. Vesta knows about projects "
                "it has prepared and directories this session has been given; "
                "it does not search the disk. Say where it is by path."
            )
        )

    if len(matching) == 1:
        return Reference(project=matching[0])

    # Several. A neighbour wins first.
    #
    # Somebody working in a directory of projects who names one of them means
    # *that* one — the sibling beside the work, not a repository of the same
    # name somewhere else on the machine. Two projects called `athena` made the
    # question ambiguous when one of them was in the very workspace being
    # asked from, which is the answer nobody would have hesitated over.
    #
    # This is the crossing a composed graph cannot make for itself: each part
    # is resolved on its own, so an import from one into another makes no edge.
    # What recovers it is asking the other project — and asking is only easy if
    # naming a sibling is unambiguous.
    # Both readings of "beside": a project inside the directory being worked
    # in, and a project sharing that directory's parent — somebody may be
    # working in the workspace or in one of its parts, and means the same
    # neighbour either way.
    #
    # The parent reading applies only where the root is *not itself* one of the
    # candidates. Given two roots that are each a project of the same name,
    # every candidate is its own sibling and this would pick whichever was
    # listed first — silently overruling recency, which is the better signal
    # when somebody has named both.
    for root in roots or []:
        root = Path(root).expanduser().resolve()
        looking = [root]
        if not any(Path(p.path) == root for p in matching):
            looking.append(root.parent)
        for where in looking:
            beside = [p for p in matching if Path(p.path).parent == where]
            if len(beside) == 1:
                return Reference(project=beside[0])

    # Then the one most recently referred to.
    when = recent or _mentions()
    ranked = sorted(matching, key=lambda p: -when.get(p.path, 0.0))
    if when.get(ranked[0].path, 0.0) > 0:
        return Reference(project=ranked[0])
    return Reference(ambiguous=matching)


# ── What is currently being referred to ──────────────────────────────────


def _where() -> Path:
    directory = home()
    directory.mkdir(parents=True, exist_ok=True)
    return directory / "referred.json"


def _mentions() -> Dict[str, float]:
    path = _where()
    if not path.is_file():
        return {}
    try:
        return {k: float(v) for k, v in json.loads(path.read_text(encoding="utf-8")).items()}
    except (OSError, ValueError):
        return {}


def refer(project: Project | str, at: Optional[float] = None) -> None:
    """Note that a project has been referred to."""
    path = project.path if isinstance(project, Project) else str(project)
    mentions = _mentions()
    mentions[path] = at if at is not None else time.time()
    try:
        _where().write_text(json.dumps(mentions), encoding="utf-8")
    except OSError:
        pass


def loaded(now: Optional[float] = None) -> List[Project]:
    """Projects currently being referred to, most recent first.

    A project nobody has mentioned for a while falls off the list. Nothing is
    merged, so this is a matter of what gets asked rather than what gets kept.
    """
    when = now if now is not None else time.time()
    mentions = _mentions()
    still = {
        path: at for path, at in mentions.items() if when - at < STAYS
    }

    if len(still) != len(mentions):
        try:
            _where().write_text(json.dumps(still), encoding="utf-8")
        except OSError:
            pass

    by_path = {p.path: p for p in known()}
    found = []
    for path, at in sorted(still.items(), key=lambda kv: -kv[1]):
        project = by_path.get(path)
        if project is None:
            root = Path(path)
            if not root.is_dir():
                continue
            project = Project(path=path, name=root.name)
        project.at = at
        found.append(project)
    return found


def release(project: Optional[Project | str] = None) -> None:
    """Stop referring to a project, or to all of them."""
    if project is None:
        try:
            _where().unlink()
        except OSError:
            pass
        return
    path = project.path if isinstance(project, Project) else str(project)
    mentions = _mentions()
    mentions.pop(path, None)
    try:
        _where().write_text(json.dumps(mentions), encoding="utf-8")
    except OSError:
        pass
