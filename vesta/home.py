"""Where Vesta keeps what it derives, and how a repository is named.

Extracted from the corpus machinery it used to live beside. That machinery
acquired literature and built knowledge bases, which needed a search key and a
model of its own — the one thing a plugin must not need, since the user has
installed it into a framework that already has both. It was removed rather than
converted: the measurements never favoured it, and a version reduced to what a
plugin may do would duplicate what the host does natively.

What survived is what the graph half genuinely needs: somewhere to put things,
and a stable name for the repository they belong to.
"""

from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path
from typing import Dict, Optional, Tuple

# Everything Vesta derives, under the user's home rather than in their
# repository: a graph, an ontology, a map, rules, patterns and notes are about
# a project without belonging to it, and nobody wants them in a diff.
VESTA_HOME = Path.home() / ".vesta"

# Directories that are not the project, wherever a repository is walked.
#
# **Dependencies are not the project.** A real repository was 62 source files
# and one `venv/` holding 13,613 — every one of them walked, and preparation
# on it had not finished after five minutes. The list said `.venv` with a dot
# and the directory was named `venv` without one, which is at least as common.
#
# It lives here because `home` imports nothing else, and the alternative was
# what was there before: three separate lists in three modules with three
# different contents, so what the resolver walked and what the graph called
# its shape could disagree. The spelling that mattered was in none of them.
#
# `build` and `dist` are deliberately absent: output in most projects and
# somebody's source in others, and excluding a directory somebody works in is
# a worse failure than walking one they do not.
# Visible directories that are not the project: dependencies somebody
# installed, and output somebody's build produced.
#
# Two rules, and both are needed. Anything beginning with a dot is skipped
# outright — that covers `.venv`, `.git`, `.tox`, `.conda`, `.gradle`,
# `.cargo` and every private thing nobody has thought of yet, and it cannot
# fall out of date. **But most dependency directories are not hidden**, and a
# dot rule alone would have walked all of them: `venv`, `node_modules`,
# `site-packages`, `target`, `Pods`. The list below is the visible half, and
# `venv` without a dot is precisely the spelling whose absence cost one
# repository 13,613 files of somebody's virtualenv.
#
# Named across languages rather than for Python, because the graph resolves
# seven and the failure is identical in each.
# A name is here only when it means "not mine" in every project that uses it.
# `bin`, `deps`, `pkg`, `packages`, `external` and `obj` are deliberately
# absent: each is a dependency directory somewhere and somebody's own source
# elsewhere — this repository keeps its launcher in `bin/`, and the workspace
# next door keeps a real component in `deps/`. Excluding a directory somebody
# works in is a worse failure than walking one they do not, because the first
# is silent and the second is only slow.
NOT_THE_PROJECT = (
    # Python
    "venv", "virtualenv", "site-packages", "dist-packages", "__pycache__",
    "conda-meta", "condabin", "anaconda3", "miniconda3",
    # JavaScript and friends
    "node_modules", "bower_components", "jspm_packages", "web_modules",
    # Rust, Go, Java, Scala, Elixir
    "vendor", "target", "_build",
    # Ruby, Swift, Objective-C
    "Pods", "Carthage",
    # C, C++, CMake
    "CMakeFiles", "_deps", "third_party", "thirdparty",
)


def walk(root: Path, suffix: str = "") -> "list":
    """Every file under `root` that is part of the project.

    Prunes as it descends rather than filtering afterwards. `rglob` walks into
    every excluded directory in full and then discards each path: on an
    ordinary repository that was 66,010 paths visited to find 77 source files.
    """
    found = []
    stack = [root]
    while stack:
        here = stack.pop()
        try:
            entries = sorted(here.iterdir())
        except OSError:
            continue
        for entry in entries:
            if entry.name.startswith(".") or entry.name in NOT_THE_PROJECT:
                continue
            try:
                if entry.is_dir():
                    stack.append(entry)
                elif entry.is_file() and (not suffix or entry.suffix == suffix):
                    found.append(entry)
            except OSError:
                continue
    found.sort()
    return found

# Where things are actually written, which is `VESTA_HOME` unless somebody has
# said otherwise. Read through a function rather than bound at import: twelve
# modules imported the constant directly, so pointing the store somewhere else
# — a test, a sandbox, a user who keeps their home read-only — reached none of
# them, and a test run wrote a record for every temporary repository it made.
_ELSEWHERE: Optional[Path] = None


# How a detached process learns where things are kept. Preparation runs in a
# child, and a variable set in the parent means nothing to it — a test run
# pointed its own store elsewhere and the background build wrote into the
# user's home regardless.
WHERE = "VESTA_HOME"


def home() -> Path:
    """Where Vesta keeps what it derives."""
    if _ELSEWHERE:
        return _ELSEWHERE
    import os

    said = os.environ.get(WHERE)
    return Path(said).expanduser().resolve() if said else VESTA_HOME


def keep_in(where: Optional[Path]) -> None:
    """Put everything somewhere else, or back where it belongs.

    Set in the environment as well as in this process, so anything Vesta starts
    in the background keeps things in the same place.
    """
    import os

    global _ELSEWHERE
    _ELSEWHERE = Path(where).expanduser().resolve() if where else None
    if _ELSEWHERE:
        os.environ[WHERE] = str(_ELSEWHERE)
    else:
        os.environ.pop(WHERE, None)


def _slug(text: str) -> str:
    kept = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return kept[:48] or "intent"


def repository(start: Optional[Path | str] = None) -> Path:
    """The project under analysis: the working directory, as the user set it.

    **No detection, deliberately.** Two earlier attempts guessed — by asking git
    for a root, then by walking up for a list of project markers — and both
    failed the same way. A marker list can never cover every language, and a
    miss does not raise: it resolves to whichever subdirectory the caller
    happened to be in, so `src/parser` and `src/lexer` become two projects. The
    tool then looks like it is working while fragmenting what it exists to
    accumulate.
    """
    where = Path(start).expanduser().resolve() if start else Path.cwd().resolve()
    return where if where.is_dir() else where.parent


def kept_at(repo: Path | str, kind: str) -> Path:
    """Where something derived about a repository is kept.

    One naming rule for graphs, ontologies, maps, rules, patterns and notes, so
    a reader finding one can find the rest.
    """
    root = Path(repo).expanduser().resolve()
    directory = home() / kind
    directory.mkdir(parents=True, exist_ok=True)
    name = hashlib.sha256(str(root).encode("utf-8")).hexdigest()[:12]
    return directory / f"{root.name}-{name}.json"
