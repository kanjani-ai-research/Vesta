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

# Who derived a body of knowledge, carried in its name. A knowledge base this
# machine built and one obtained from a publisher are different evidence about
# the same subject, and a reader must be able to tell which answered.
LOCAL = "local"
PUBLISHED = "pub"


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


def repository_name(start: Optional[Path | str] = None) -> str:
    """A short, stable name for a repository.

    The directory name carries meaning to a person; the hash of the full path
    keeps two checkouts of the same project apart. Both, because a name nobody
    recognises is unusable and a name that collides is wrong.
    """
    root = repository(start)
    fingerprint = hashlib.sha256(str(root).encode("utf-8")).hexdigest()[:8]
    return f"{_slug(root.name)}-{fingerprint}"


def corpus_id(
    repo: Optional[Path | str] = None, origin: str = LOCAL, publisher: str = ""
) -> str:
    """The id of what is known about a repository.

    **One repository, one body of knowledge.** Keying by task would give a
    project a scatter of single-purpose records that never accumulate — what was
    learned for one piece of work would be invisible to the next, which is the
    opposite of the point. Two repositories must not share one either: what is
    known about a compiler is not evidence about a payments service.
    """
    subject = repository_name(repo)
    if origin == PUBLISHED:
        return f"theory.{PUBLISHED}.{_slug(publisher) if publisher else 'unattributed'}.{subject}"
    return f"theory.{LOCAL}.{subject}"


def origin_of(identifier: str) -> str:
    """Where a body of knowledge came from, read back from its id."""
    parts = identifier.split(".")
    return parts[1] if len(parts) > 2 and parts[0] == "theory" else LOCAL


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
