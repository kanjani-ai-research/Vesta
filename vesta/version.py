"""One version, held in every place it is written.

A version is written in several files because several readers need it — the
package index reads `pyproject.toml`, the plugin framework reads
`plugin.json`, a program reads `__version__`, a person reads the changelog —
and nothing held them together. On this repository that meant 0.7.0 shipped
with the package and manifest still saying 0.6.2, `__version__` said 0.1.0
for seven releases, and a release was three edits and a tag that each had to
be remembered. Artifacts that drift are worse than one missing: each reader
believes the one it sees.

**One number, found rather than declared.** The places a version lives are
the conventional ones, and this looks for them rather than asking anyone to
list them: a manifest at the root, a `__version__` in a top-level package,
the first heading of the changelog. A project that keeps its version somewhere
unconventional is told so by the absence, not silently half-synchronised.

**Reading says whether they agree; setting makes them.** `vesta version`
reports every place and the one number, or names which places disagree.
`vesta version --set X` writes X into each of them, turns an "Unreleased"
changelog heading into X or opens one, and with `--tag` cuts the local tag
the repository's convention uses. Nothing is pushed; publishing is the
author's act.

**Nothing here invents a version.** It does not bump, guess the next number,
or read git for one. The author says the number; this makes sure it is said
once.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import List, Optional, Tuple

from pydantic import BaseModel, Field

# What a version looks like: three numbers, optionally a pre-release or build
# suffix. Loose enough for every scheme in common use; strict enough that a
# typo is refused rather than written into four files.
SHAPE = re.compile(r"^\d+\.\d+\.\d+(?:[-+.][0-9A-Za-z.\-+]+)?$")

# How this repository names a tag. Read from the tags already present where
# there are any, so a project with `v1.2.3` tags keeps getting them.
DEFAULT_TAG = "v{version}"

UNRELEASED = re.compile(r"^## (Unreleased|unreleased|UNRELEASED)[ \t]*$", re.M)
HEADING = re.compile(r"^## (\S+)", re.M)


class Place(BaseModel):
    """One file that carries the version, and what it says."""

    where: str
    version: str
    # The regular expression that found it, with one group: the version.
    pattern: str
    # A changelog carries the version as a heading, which is added rather than
    # replaced, and may legitimately say "Unreleased".
    changelog: bool = False

    def describe(self) -> str:
        return f"{self.where}: {self.version or '(none)'}"


class Agreement(BaseModel):
    """Whether every place says the same thing."""

    places: List[Place] = Field(default_factory=list)

    @property
    def versions(self) -> List[str]:
        return sorted({p.version for p in self.places if p.version and not p.changelog})

    @property
    def version(self) -> str:
        """The one version, or "" when there is not one."""
        return self.versions[0] if len(self.versions) == 1 else ""

    @property
    def agree(self) -> bool:
        if not self.places or not self.version:
            return False
        for place in self.places:
            if place.changelog and place.version.lower() != "unreleased" and place.version != self.version:
                return False
        return True

    def describe(self) -> str:
        if not self.places:
            return "no place here carries a version"
        lines = [p.describe() for p in self.places]
        if self.agree:
            lines.append(f"agreed: {self.version} in {len(self.places)} place(s)")
        elif len(self.versions) > 1:
            lines.append(f"DISAGREE: {', '.join(self.versions)}")
        else:
            lines.append(
                f"DISAGREE: the changelog's latest heading is not {self.version}"
            )
        return "\n".join(lines)


# ── Finding the places ──────────────────────────────────────────────────────


def _matching(root: Path, relative: str, pattern: str, changelog: bool = False) -> Optional[Place]:
    path = root / relative
    if not path.is_file():
        return None
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    found = re.search(pattern, text, re.M)
    if not found:
        return None
    return Place(where=relative, version=found.group(1), pattern=pattern, changelog=changelog)


def places(repo: Path | str) -> Agreement:
    """Every place in this repository that carries a version."""
    root = Path(repo).expanduser().resolve()
    found: List[Place] = []

    for relative, pattern in (
        ("pyproject.toml", r'^version\s*=\s*"([^"]+)"'),
        ("Cargo.toml", r'^version\s*=\s*"([^"]+)"'),
        ("package.json", r'"version"\s*:\s*"([^"]+)"'),
        (".claude-plugin/plugin.json", r'"version"\s*:\s*"([^"]+)"'),
    ):
        place = _matching(root, relative, pattern)
        if place:
            found.append(place)

    # A `__version__` in any top-level package. Walked shallowly: a package's
    # version lives in its own `__init__.py`, and anything deeper is a module
    # borrowing it.
    try:
        for entry in sorted(root.iterdir()):
            init = entry / "__init__.py"
            if entry.is_dir() and not entry.name.startswith(".") and init.is_file():
                place = _matching(
                    root, f"{entry.name}/__init__.py", r'^__version__\s*=\s*"([^"]+)"'
                )
                if place:
                    found.append(place)
    except OSError:
        pass

    for name in ("CHANGELOG.md", "CHANGES.md", "HISTORY.md"):
        place = _matching(root, name, r"^## (\S+)", changelog=True)
        if place:
            found.append(place)
            break

    return Agreement(places=found)


# ── Setting it ──────────────────────────────────────────────────────────────


def set_version(repo: Path | str, version: str) -> List[str]:
    """Write `version` into every place, and say which files changed.

    A changelog heading of "Unreleased" becomes the version; a changelog whose
    latest heading is some other version gets a new heading opened above it,
    because a release with no entry is a release nobody can read about. A
    changelog already headed with this version is left alone.
    """
    if not SHAPE.match(version):
        raise ValueError(f"not a version: {version!r} — expected something like 1.2.3")
    root = Path(repo).expanduser().resolve()
    found = places(root)
    if not found.places:
        raise ValueError("no place here carries a version, so there is nothing to set")

    changed: List[str] = []
    for place in found.places:
        path = root / place.where
        text = path.read_text(encoding="utf-8")
        if place.changelog:
            if place.version == version:
                continue
            if UNRELEASED.search(text):
                text = UNRELEASED.sub(f"## {version}", text, count=1)
            else:
                first = HEADING.search(text)
                opened = f"## {version}\n\n"
                if first is None:
                    text = text.rstrip("\n") + "\n\n" + opened
                else:
                    text = text[: first.start()] + opened + text[first.start():]
            path.write_text(text, encoding="utf-8")
            changed.append(place.where)
            continue
        if place.version == version:
            continue
        text, count = re.subn(
            place.pattern,
            lambda m: m.group(0).replace(m.group(1), version),
            text,
            count=1,
            flags=re.M,
        )
        if count:
            path.write_text(text, encoding="utf-8")
            changed.append(place.where)
    return changed


# ── Tagging it ──────────────────────────────────────────────────────────────


def _git(root: Path, *args: str) -> Tuple[int, str]:
    try:
        done = subprocess.run(
            ["git", *args], cwd=str(root), capture_output=True, text=True, timeout=30
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return 1, str(exc)
    return done.returncode, (done.stdout or done.stderr).strip()


def tag_shape(repo: Path | str) -> str:
    """How this repository names its tags, read from the tags it has.

    `vesta--v0.6.2` and `v0.6.2` are both conventions; the one in use is the
    one to keep using, and the only way to know is to look.
    """
    root = Path(repo).expanduser().resolve()
    code, said = _git(root, "tag", "--list")
    if code != 0 or not said:
        return DEFAULT_TAG
    for line in reversed(said.splitlines()):
        matched = re.match(r"^(.*?)(\d+\.\d+\.\d+.*)$", line.strip())
        if matched:
            return matched.group(1) + "{version}"
    return DEFAULT_TAG


def tag(repo: Path | str, version: str) -> str:
    """Cut the local tag for `version`, in the repository's own shape.

    Refused when the tag exists already or the tree has uncommitted changes
    to a versioned file — a tag on a tree whose files do not yet say the
    version is a tag on the wrong commit. Never pushed.
    """
    root = Path(repo).expanduser().resolve()
    name = tag_shape(root).format(version=version)
    code, existing = _git(root, "tag", "--list", name)
    if code == 0 and existing.strip() == name:
        raise ValueError(f"tag {name} already exists")
    code, dirty = _git(root, "status", "--porcelain", "--", *[p.where for p in places(root).places])
    if code == 0 and dirty.strip():
        raise ValueError(
            f"versioned files are not committed yet ({dirty.splitlines()[0].strip()}) — "
            "commit, then tag"
        )
    code, said = _git(root, "tag", name)
    if code != 0:
        raise ValueError(f"could not tag: {said}")
    return name
