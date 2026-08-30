"""Letting go of what is no longer about anything.

Everything Vesta derives is keyed by repository, and nothing was ever deleted.
A thousand files accumulated here in a few days of use — graphs for directories
that no longer exist, stamps for notes about code that has moved, a record for
every temporary repository ever pointed at. None of it is large, and that is
exactly why it went unnoticed: the cost is not disk, it is that a store nobody
prunes stops being a description of anything.

**What goes is what has lost its subject.** A record for a repository that is
no longer on disk describes nothing. That is a fact about the filesystem, not a
judgement, so it is safe to act on without asking.

**What stays is anything that could still be right.** A record for a repository
that exists is kept however old it is, because age is not staleness — the
authority mechanism already decides whether a claim still holds, by hashing the
region it was made about. Deleting on age would throw away claims that are
still true.

**Nothing here is destructive in a way that costs anything.** Every artifact is
derived and can be rebuilt from the repository it describes. The worst outcome
of pruning too eagerly is a rebuild; the worst outcome of never pruning is a
store that grows without bound.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from pydantic import BaseModel, Field

from .home import home

logger = logging.getLogger("vesta.tidy")

# Everything Vesta keeps, and whether a file there names the repository it is
# about. All of them do, by construction — `kept_at` builds every name the same
# way — which is what makes this possible at all.
KINDS = (
    "graphs",
    "maps",
    "ontologies",
    "notes",
    "rules",
    "patterns",
    "harvests",
    "sessions",
    "prepared",
    "converging",
)

# Holdings kept as a directory per project rather than a single file, so the
# file walk above steps straight past them. Named separately rather than making
# the walk recursive: recursing would also descend into anything else that ever
# gains a subdirectory, and a reclaim that removes more than it was asked to is
# the one mistake this must not make.
NESTED = ("bundles",)

# How long a preparation mark is believed before it is treated as abandoned.
# Longer than a build takes, short enough that a crashed process does not block
# a repository forever.
ABANDONED = 3600.0


class Swept(BaseModel):
    """What was let go, and what was kept."""

    removed: List[str] = Field(default_factory=list)
    kept: int = 0
    freed: int = 0

    def describe(self) -> str:
        if not self.removed:
            return f"nothing to let go; {self.kept} file(s) still describe something"
        return (
            f"{len(self.removed)} file(s) removed, {self.freed // 1024}KB freed; "
            f"{self.kept} kept"
        )


def _repositories() -> Dict[str, Path]:
    """Every repository Vesta holds anything about, by the key in its filenames.

    Recovered from the records themselves rather than from a list, because a
    list would be another thing to keep in step. A graph store carries the root
    it was built from; the rest carry the name in the filename.
    """
    found: Dict[str, Path] = {}

    for path in (home() / "graphs").glob("*.db"):
        try:
            import sqlite3

            connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
            row = connection.execute(
                "SELECT value FROM meta WHERE key='root'"
            ).fetchone()
            connection.close()
            if row and row[0]:
                found[path.stem] = Path(row[0])
        except Exception:  # noqa: BLE001 - an unreadable store is one to sweep
            continue

    for path in (home() / "graphs").glob("*.json"):
        if path.stem in found:
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            root = payload.get("graph", {}).get("root", "")
            if root:
                found[path.stem] = Path(root)
        except (OSError, ValueError):
            continue

    return found


def _key_of(path: Path) -> str:
    """The repository key a filename carries.

    Names are `<repository>-<hash>.<ext>`, sometimes with a prefix like
    `scan-`. The hash is what identifies the repository, so it is what is
    matched on.
    """
    stem = path.stem
    for prefix in ("scan-",):
        if stem.startswith(prefix):
            stem = stem[len(prefix) :]
    return stem.replace("-stamps", "")


def _project_of(holding: Path) -> Optional[Path]:
    """The repository a nested holding says it belongs to, if it says.

    Read from the holding rather than inferred from its name, because a name
    carries a hash of a path and a hash cannot be reversed into one. A bundle
    records its project outright, so the question has a real answer here that
    it does not have for a graph file — and an answer beats a key lookup that
    treats "not mentioned anywhere else" as "deleted".
    """
    for path in sorted(holding.glob("*.json"))[-1:]:
        try:
            said = json.loads(path.read_text(encoding="utf-8")).get("project", "")
        except (OSError, ValueError):
            return None
        if said:
            return Path(said)
    return None


def sweep(dry: bool = False) -> Swept:
    """Let go of records whose repository is gone.

    `dry` reports what would go without removing it, because a first run
    against a store nobody has pruned should be inspectable.
    """
    swept = Swept()
    known = _repositories()

    # A key is alive when the repository it names still exists on disk. Keys
    # nothing claims — a stamp file whose graph was already removed — are
    # treated as gone, since nothing can rebuild what they belong to.
    alive = {key for key, root in known.items() if root.is_dir()}

    for kind in KINDS:
        directory = home() / kind
        if not directory.is_dir():
            continue
        for path in sorted(directory.iterdir()):
            if not path.is_file():
                continue

            key = _key_of(path)
            gone = key not in alive

            # A preparation mark left by a process that died. Not tied to a
            # repository being absent: it is a lock nobody released.
            if kind == "prepared" and not gone:
                try:
                    started = json.loads(path.read_text(encoding="utf-8")).get("since", 0)
                    gone = time.time() - started > ABANDONED
                except (OSError, ValueError):
                    gone = True

            if not gone:
                swept.kept += 1
                continue

            size = path.stat().st_size
            swept.removed.append(f"{kind}/{path.name}")
            swept.freed += size
            if not dry:
                try:
                    path.unlink()
                except OSError as exc:
                    logger.info("could not remove %s: %s", path, exc)

    for kind in NESTED:
        directory = home() / kind
        if not directory.is_dir():
            continue
        for holding in sorted(directory.iterdir()):
            if not holding.is_dir():
                continue

            # Which repository this belongs to, asked of the holding itself
            # before falling back to what the graphs claim.
            #
            # `alive` is built only from graph files, so a project holding
            # bundles and no graph is unknown to it — and "unknown" would then
            # mean "gone", which would reclaim a live repository's history. A
            # bundle records its own project, so it can answer for itself; only
            # when it cannot is the graph key used, and a holding nothing can
            # place is kept rather than removed. Gone must mean gone.
            root = _project_of(holding)
            if root is not None:
                if root.is_dir():
                    swept.kept += 1
                    continue
            elif _key_of(holding) in alive or not alive:
                swept.kept += 1
                continue

            inside = [p for p in holding.rglob("*") if p.is_file()]
            swept.removed.append(f"{kind}/{holding.name}")
            swept.freed += sum(p.stat().st_size for p in inside)
            if not dry:
                try:
                    for p in inside:
                        p.unlink()
                    holding.rmdir()
                except OSError as exc:
                    logger.info("could not remove %s: %s", holding, exc)

    return swept


def forget(repo: Path | str, dry: bool = False) -> Swept:
    """Let go of everything about one repository.

    For a user who wants a project's records gone whether or not the project
    is: one file per kind, so this is a delete rather than a migration.
    """
    from .home import kept_at

    swept = Swept()
    root = Path(repo).expanduser().resolve()
    key = kept_at(root, "graphs").stem

    for kind in KINDS:
        directory = home() / kind
        if not directory.is_dir():
            continue
        for path in sorted(directory.iterdir()):
            if not path.is_file():
                continue
            if _key_of(path) != key:
                swept.kept += 1
                continue
            swept.removed.append(f"{kind}/{path.name}")
            swept.freed += path.stat().st_size
            if not dry:
                try:
                    path.unlink()
                except OSError:
                    pass
    return swept
