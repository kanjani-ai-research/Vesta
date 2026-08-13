"""What Vesta is holding, and getting rid of what is dead.

Vesta derives a graph, an ontology, a map, rules and notes for every repository
it is used in, and until now it never let go of any of it. On the machine this
was written on that came to 337M, of which **331M was one graph built for a
directory under /tmp that had not existed for weeks**.

That is not a scale problem — the largest real graph here is 684K, and twenty
projects would be about 24M. It is that nothing reports what is held and
nothing reclaims it, so the number only ever goes up, and the person who
eventually finds hundreds of megabytes in their home directory is a stranger
rather than the author.

**The signal is whether the repository still exists.** Age is the obvious
candidate and it is wrong: a project untouched for a month is exactly where a
cached understanding is worth most, because nobody has paid to rebuild it
recently. A path that has been deleted, though, is never coming back — nothing
derived from it can ever be asked about again.

**Nothing is deleted without being asked.** `held()` reports; `reclaim()` acts,
and only when a caller passes it what to remove. A tool that quietly deletes
things in a user's home directory is one nobody should install, and the whole
point of the report is that a person can disagree with it before anything goes.

**A repository that is merely unreachable is not gone.** An unmounted volume, a
detached external disk, a network share that is down — all make a path fail
`exists()` while the repository is perfectly alive. So a path that cannot be
resolved at all is reported as *unknown* rather than dead, and unknown things
are never in the default set to remove.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from pydantic import BaseModel, Field

logger = logging.getLogger("vesta.reclaim")

# Everything kept per repository, by the one naming rule `kept_at` uses:
# `<repository name>-<12 hex of a sha256 of its absolute path>.json`.
PER_REPOSITORY = (
    "graphs",
    "maps",
    "ontologies",
    "rules",
    "notes",
    "patterns",
    "confirmed",
    "driving",
    "prepared",
)

# A path under one of these is somewhere the operating system throws away by
# itself. A graph built for a temporary directory is dead the moment the tests
# that made it finished, and it is the single biggest thing held here.
#
# Written without trailing slashes and matched on the boundary, because the
# largest holding on the machine this was written on was rooted at
# `/private/tmp` *itself* — and a prefix of `/private/tmp/` does not match it,
# so the one entry worth 522M was the one that escaped.
TEMPORARY = ("/tmp", "/private/tmp", "/var/folders", "/private/var/folders")


class Holding(BaseModel):
    """Everything Vesta has derived about one repository."""

    root: str = ""
    name: str = ""
    key: str = ""

    files: List[str] = Field(default_factory=list)
    bytes: int = 0

    # Whether the repository is still there. `None` where the path could not
    # be resolved at all, which is not the same as gone.
    alive: Optional[bool] = None

    @property
    def temporary(self) -> bool:
        """Whether this was derived somewhere the system throws away.

        Matched on the path boundary rather than as a bare prefix: the root
        itself counts (`/private/tmp` is temporary) and a directory that
        merely begins with the same letters does not (`/tmpfoo` is somebody's
        project).
        """
        return any(
            self.root == where or self.root.startswith(where + "/")
            for where in TEMPORARY
        )

    @property
    def junk(self) -> bool:
        """A graph of a temp *root* itself, which should never have been built.

        Distinct from dead, and reported separately. The largest holding on
        the machine this was written on was 522M rooted at `/private/tmp` —
        the system temp directory, 418 entries of other programs' litter,
        walked as though it were a repository. It still exists, so the honest
        liveness test says keep it; it is obviously worthless, so a report
        that stayed silent about it would be useless.

        Only the root itself. `/private/tmp/my-experiment` is a real project
        somebody made on purpose, and the moment it is deleted the ordinary
        dead test catches it anyway.
        """
        return self.root in TEMPORARY

    @property
    def dead(self) -> bool:
        """Certainly not worth keeping.

        Two ways to qualify.

        A path that resolved and is not there is gone. That is the safe,
        obvious case and it needs no further judgement.

        A path under a temporary root is gone *only once it has also stopped
        existing* — because people do work in temporary directories. pytest
        puts every `tmp_path` under `/private/var/folders`, and a rule that
        called anything temporary-rooted dead would have marked a live test
        repository reclaimable. What being under a temporary root actually
        buys is nothing about liveness at all; what it buys is that once such
        a directory is gone it is certainly not coming back, and no user will
        ever want it restored.

        So the two collapse into one test — *does the repository still
        exist* — and `temporary` survives only to explain **why** something is
        dead in the report, which is a kindness to whoever reads it before
        deleting 522M.
        """
        return self.alive is False

    def describe(self) -> str:
        size = _size(self.bytes)
        if self.alive is None:
            return f"  ? {size:>8}  {self.root or self.key}  (cannot tell)"
        if self.junk:
            return f"  ✗ {size:>8}  {self.root}  (a temp directory, not a project)"
        if self.dead:
            return f"  ✗ {size:>8}  {self.root}  (gone)"
        return f"    {size:>8}  {self.root}"


class Held(BaseModel):
    """What is held in total, and what of it is dead."""

    holdings: List[Holding] = Field(default_factory=list)
    loose: int = 0
    loose_bytes: int = 0

    @property
    def bytes(self) -> int:
        return sum(h.bytes for h in self.holdings) + self.loose_bytes

    @property
    def dead(self) -> List[Holding]:
        """Everything worth removing: repositories that are gone, and graphs
        of a temp directory that were never repositories at all."""
        return [h for h in self.holdings if h.dead or h.junk]

    @property
    def reclaimable(self) -> int:
        return sum(h.bytes for h in self.dead)

    def describe(self, show: int = 12) -> str:
        if not self.holdings:
            return "Vesta is holding nothing yet."

        lines = [
            f"{_size(self.bytes)} held for {len(self.holdings)} repositor"
            f"{'y' if len(self.holdings) == 1 else 'ies'}"
        ]

        # Biggest first: the thing worth reclaiming is almost always one
        # outlier, and a list sorted by name buries it.
        for holding in sorted(self.holdings, key=lambda h: -h.bytes)[:show]:
            lines.append(holding.describe())
        if len(self.holdings) > show:
            lines.append(f"    … and {len(self.holdings) - show} more")

        if self.dead:
            gone = len([h for h in self.dead if h.dead])
            junk = len([h for h in self.dead if h.junk])
            why = []
            if gone:
                why.append(
                    f"{gone} repositor{'y' if gone == 1 else 'ies'} that no "
                    "longer exist"
                )
            if junk:
                why.append(
                    f"{junk} graph{'' if junk == 1 else 's'} of a temp "
                    "directory rather than a project"
                )

            lines.append("")
            lines.append(f"{_size(self.reclaimable)} belongs to {' and '.join(why)}.")
            lines.append("  Reclaim it with `vesta held --reclaim`.")
        return "\n".join(lines)


def _size(count: int) -> str:
    for unit in ("B", "K", "M", "G"):
        if count < 1024 or unit == "G":
            return f"{count:.0f}{unit}" if unit == "B" else f"{count:.1f}{unit}"
        count /= 1024.0
    return f"{count:.1f}G"


def _key_of(path: Path) -> str:
    """The hash `kept_at` put in a filename, which identifies the repository."""
    stem = path.stem
    return stem.rsplit("-", 1)[-1] if "-" in stem else ""


def _root_of(path: Path) -> str:
    """The repository a kept file was derived from, where it says.

    Only graphs record it. That is enough: everything else derived for the same
    repository shares the key in its filename, so one graph identifies the
    whole holding.
    """
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    graph = payload.get("graph")
    if isinstance(graph, dict):
        return str(graph.get("root", "") or "")
    return str(payload.get("root", "") or "")


def _exists(root: str) -> Optional[bool]:
    """Whether a repository is still there.

    `None` where the question cannot be answered — an unmounted volume or a
    network share that is down makes a live repository look deleted, and
    deleting somebody's cached understanding because their external disk was
    unplugged is not a mistake worth making to save a few megabytes.
    """
    if not root:
        return None
    try:
        return Path(root).is_dir()
    except OSError as exc:
        logger.info("could not tell whether %s is there: %s", root, exc)
        return None


def home() -> Path:
    """Where Vesta keeps things. Named here so a test can point it elsewhere."""
    from .home import home as _home

    return _home()


def held(where: Optional[Path] = None) -> Held:
    """Everything Vesta has derived, grouped by the repository it came from."""
    base = where or home()
    found = Held()
    if not base.is_dir():
        return found

    by_key: Dict[str, Holding] = {}

    for kind in PER_REPOSITORY:
        directory = base / kind
        if not directory.is_dir():
            continue
        for path in sorted(directory.iterdir()):
            if not path.is_file():
                continue
            key = _key_of(path)
            if not key:
                found.loose += 1
                found.loose_bytes += _weigh(path)
                continue

            holding = by_key.setdefault(
                key, Holding(key=key, name=path.stem.rsplit("-", 1)[0])
            )
            holding.files.append(str(path))
            holding.bytes += _weigh(path)

            # Only a graph knows where it came from, and both the JSON and the
            # database beside it carry the same key.
            if not holding.root and kind == "graphs" and path.suffix == ".json":
                holding.root = _root_of(path)

    for holding in by_key.values():
        holding.alive = _exists(holding.root)

    found.holdings = list(by_key.values())
    return found


def _weigh(path: Path) -> int:
    """A file's size, and only its own.

    A graph is kept twice — a JSON the whole graph is loaded from and a SQLite
    database that answers indexed lookups without loading anything — and both
    must be counted. But `held` already walks every file in the directory, so
    adding the database *beside* a JSON here counted it a second time and the
    report overstated every holding by the size of its database. Roughly
    double, on a real graph.
    """
    try:
        return path.stat().st_size
    except OSError:
        return 0


def reclaim(holdings: List[Holding]) -> Tuple[int, int, List[str]]:
    """Remove what a caller has decided is dead.

    Takes the holdings rather than finding them, so nothing is deleted that a
    caller did not look at first. Returns how many files went, how many bytes
    that freed, and anything that could not be removed.
    """
    files = 0
    freed = 0
    refused: List[str] = []

    for holding in holdings:
        for name in holding.files:
            path = Path(name)
            for target in (path, path.with_suffix(".db")):
                if not target.is_file():
                    continue
                try:
                    size = target.stat().st_size
                    target.unlink()
                    files += 1
                    freed += size
                except OSError as exc:
                    refused.append(f"{target}: {exc}")

    return files, freed, refused
