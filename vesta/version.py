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


def _is_annotated(root: Path, name: str) -> Optional[bool]:
    """Whether a tag is annotated, or None when there is no such tag."""
    code, kind = _git(root, "cat-file", "-t", f"refs/tags/{name}")
    if code != 0:
        return None
    return kind.strip() == "tag"


def tag(repo: Path | str, version: str) -> str:
    """Cut the local tag for `version`, in the repository's own shape.

    Annotated, not lightweight: `push.followTags` carries annotated tags
    reachable from what is pushed, and a lightweight one stays behind however
    the push is made — which is how two releases went out with their tags
    still on one machine. A lightweight tag of this name already present is
    re-made annotated at the same commit, so what it points at does not move;
    an annotated one already present is left alone and refused.

    Refused when the tree has uncommitted changes to a versioned file — a tag
    on a tree whose files do not yet say the version is a tag on the wrong
    commit. Never pushed.
    """
    root = Path(repo).expanduser().resolve()
    name = tag_shape(root).format(version=version)
    annotated = _is_annotated(root, name)
    if annotated:
        raise ValueError(f"tag {name} already exists")
    code, dirty = _git(root, "status", "--porcelain", "--", *[p.where for p in places(root).places])
    if code == 0 and dirty.strip():
        raise ValueError(
            f"versioned files are not committed yet ({dirty.splitlines()[0].strip()}) — "
            "commit, then tag"
        )
    if annotated is False:
        code, at = _git(root, "rev-parse", f"{name}^{{commit}}")
        if code != 0:
            raise ValueError(f"could not read where {name} points: {at}")
        code, said = _git(root, "tag", "-a", "-f", "-m", name, name, at)
    else:
        code, said = _git(root, "tag", "-a", "-m", name, name)
    if code != 0:
        raise ValueError(f"could not tag: {said}")
    return name


# ── Guarding the push ───────────────────────────────────────────────────────

# The hook is recognised by this line, so a hook somebody else installed is
# never overwritten and ours is always replaceable.
OURS = "# vesta: a push carries the version's tag."


def _launcher(root: Path) -> str:
    """How the hook reaches Vesta: this checkout's launcher, else the installed
    plugin's, else the interpreter running now."""
    import os
    import sys

    own = root / "bin" / "vesta-run"
    if own.is_file():
        return f'"{own}"'
    plugin = os.environ.get("CLAUDE_PLUGIN_ROOT", "")
    if plugin and (Path(plugin) / "bin" / "vesta-run").is_file():
        return f'"{Path(plugin) / "bin" / "vesta-run"}"'
    # The interpreter running now, told where this package is: it may be
    # importable here only through the working directory, which a hook run
    # by git from another repository does not share.
    package = Path(__file__).resolve().parent.parent
    # Through `env`, because the hook `exec`s this and `exec VAR=x cmd` runs
    # a command called `VAR=x`.
    return (
        f'env PYTHONPATH="{package}${{PYTHONPATH:+:$PYTHONPATH}}" '
        f'"{sys.executable}" -m vesta.cli'
    )


def guard(repo: Path | str) -> List[str]:
    """Make this repository's pushes carry the version's tag.

    Two private settings, neither in the tree: `push.followTags`, so a plain
    `git push` brings every annotated tag reachable from what it pushes; and
    a pre-push hook that refuses to push a branch whose agreed version has no
    tag, a lightweight one, or one pointing at a commit not being pushed —
    and says the command that fixes it. The hook does not push, add refs, or
    change anything; it only declines, so what reaches a remote is still the
    author's act.
    """
    root = Path(repo).expanduser().resolve()
    code, top = _git(root, "rev-parse", "--show-toplevel")
    if code != 0:
        raise ValueError("not a git repository")
    code, hooks_dir = _git(root, "rev-parse", "--git-path", "hooks")
    hooks = Path(hooks_dir) if Path(hooks_dir).is_absolute() else Path(top) / hooks_dir
    hooks.mkdir(parents=True, exist_ok=True)
    hook = hooks / "pre-push"
    if hook.is_file() and OURS not in hook.read_text(encoding="utf-8", errors="replace"):
        raise ValueError(
            f"{hook} exists and is not Vesta's — move it aside, or call "
            "`vesta version --before-push \"$1\" \"$2\"` from it yourself"
        )
    done: List[str] = []
    hook.write_text(
        "#!/bin/sh\n"
        f"{OURS} Installed by `vesta version --guard`; remove the file to stop.\n"
        f'exec {_launcher(root)} version "{top}" --before-push "$1" "$2"\n',
        encoding="utf-8",
    )
    hook.chmod(0o755)
    done.append(f"installed {hook}")
    code, said = _git(root, "config", "--local", "push.followTags", "true")
    if code != 0:
        raise ValueError(f"could not set push.followTags: {said}")
    done.append("set push.followTags=true (annotated tags ride along with a plain `git push`)")
    return done


def before_push(repo: Path | str, remote: str, pushing: str) -> Tuple[bool, str]:
    """Whether a push may go ahead, and what to do if not.

    `pushing` is what git hands a pre-push hook on stdin: one line per ref,
    `<local ref> <local sha> <remote ref> <remote sha>`. A push of no branch
    (only tags, or a delete) is none of this hook's business.
    """
    root = Path(repo).expanduser().resolve()
    branches = []
    for line in pushing.splitlines():
        parts = line.split()
        if len(parts) == 4 and parts[0].startswith("refs/heads/") and not set(parts[1]) == {"0"}:
            branches.append((parts[0], parts[1]))
    if not branches:
        return True, ""

    found = places(root)
    if not found.places:
        return True, ""  # a repository that keeps no version has no tag to carry
    if not found.agree:
        return False, (
            "refusing to push: the version is not the same everywhere.\n"
            f"{found.describe()}\n"
            "Fix: vesta version --set <X.Y.Z>, commit, then push again."
        )
    name = tag_shape(root).format(version=found.version)
    annotated = _is_annotated(root, name)
    if annotated is None:
        return False, (
            f"refusing to push: {found.version} has no tag ({name}).\n"
            "Fix: vesta version --tag, then push again — the tag rides along."
        )
    if annotated is False:
        return False, (
            f"refusing to push: {name} is a lightweight tag, which a push does not carry.\n"
            "Fix: vesta version --tag (re-makes it annotated at the same commit), then push again."
        )
    code, at = _git(root, "rev-parse", f"{name}^{{commit}}")
    reachable = any(
        _git(root, "merge-base", "--is-ancestor", at.strip(), sha)[0] == 0
        for _, sha in branches
    )
    if not reachable:
        code, on_remote = _git(root, "ls-remote", "--tags", remote, name)
        if code == 0 and on_remote.strip():
            return True, ""
        return False, (
            f"refusing to push: {name} points at {at[:12]}, which is not in what is being pushed.\n"
            "Fix: move the tag to the released commit (vesta version --tag after deleting it), "
            "or push that commit."
        )
    code, follow = _git(root, "config", "--get", "push.followTags")
    if follow.strip().lower() != "true":
        return False, (
            "refusing to push: push.followTags is off, so the tag would stay behind.\n"
            "Fix: vesta version --guard, then push again."
        )
    return True, f"{name} rides along."
