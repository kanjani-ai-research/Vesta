"""Saying a thing once.

Companion mode has one standard: it works without the user doing anything, and
it does not make itself felt. Everything is behind the scenes unless they are
actually adjudicating something — and then a hint about how, once, not a
reminder every prompt.

**Repetition is the failure that gets a channel ignored.** The defects in a
file do not change between one prompt and the next, so a user editing that
file was told about the same two swallowed failures on every message until
they fixed them or stopped reading. The second telling is worth nothing and
the tenth is worth less than nothing: it teaches somebody to skim past the
channel, and then the finding that mattered goes past unread too.

So anything raised unasked is raised **once per session** and then kept quiet.
Not once ever — a new session is a new working context, and a defect nobody
acted on last week is worth mentioning again today. Not once per prompt
either, which is what it was.

**Keyed by what was said, not by when.** A timer would either repeat inside a
session or go quiet across two, and neither is what somebody means by "do not
tell me twice". What is remembered is the substance: this defect, in this
file, in this session.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger("vesta.once")

# How long a session's memory lasts when the host does not name one.
#
# A hook is a fresh process each time and cannot hold anything in memory, so
# "this session" has to be something on disk. Where the host supplies a session
# id that is exact; where it does not, six hours is longer than a working day's
# sitting and short enough that tomorrow is a new one.
A_SESSION = 6 * 60 * 60.0


# How long a note is kept before it is swept. A session's memory has no value
# once the session is over, and these are keyed by session rather than by
# repository — so nothing else would ever collect them, and a directory nobody
# prunes stops being a description of anything.
KEEP_FOR = 7 * 24 * 60 * 60.0


def _where() -> Path:
    from .home import home

    directory = home() / "said"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _sweep(directory: Path) -> None:
    """Drop notes from sessions long over. Cheap, and never the point."""
    cutoff = time.time() - KEEP_FOR
    try:
        for path in directory.glob("*.json"):
            try:
                if path.stat().st_mtime < cutoff:
                    path.unlink()
            except OSError:
                continue
    except OSError:
        pass


def _session() -> str:
    """Which session this is, as far as anything can tell."""
    said = os.environ.get("CLAUDE_CODE_SESSION_ID", "").strip()
    return said or "no-session"


def _key(project: str, subject: str) -> Path:
    mark = hashlib.sha256(
        f"{_session()}\x00{project}\x00{subject}".encode("utf-8")
    ).hexdigest()[:16]
    return _where() / f"{mark}.json"


def already_said(project: Path | str, subject: str) -> bool:
    """Whether this exact thing has been raised in this session.

    Never raises. A hook that failed because it could not read its own notes
    would be worse than one that repeated itself.
    """
    try:
        path = _key(str(project), subject)
        if not path.is_file():
            return False
        held = json.loads(path.read_text(encoding="utf-8"))
        if _session() != "no-session":
            return True
        # No session id from the host, so fall back to a window.
        return time.time() - held.get("at", 0) < A_SESSION
    except (OSError, ValueError) as exc:  # noqa: BLE001
        logger.info("could not tell whether this was said: %s", exc)
        return False


def say_once(project: Path | str, subject: str, said: str) -> str:
    """`said`, the first time this subject comes up; nothing afterwards.

    The subject is what makes two tellings the same telling — a file and the
    defects in it, a rule and the files it governs. Passing the whole message
    as the subject would work and would also repeat whenever a line number
    moved, which is the same annoyance wearing a disguise.
    """
    if not said:
        return ""
    if already_said(project, subject):
        return ""

    try:
        path = _key(str(project), subject)
        path.write_text(
            json.dumps({"at": time.time(), "subject": subject[:200]}),
            encoding="utf-8",
        )
        # Swept here rather than on a schedule: this runs rarely — once per
        # subject per session — which is exactly the frequency a tidy-up wants.
        _sweep(path.parent)
    except OSError as exc:  # noqa: BLE001 - never break a prompt
        logger.info("could not record what was said: %s", exc)
    return said


def forget(project: Optional[Path | str] = None) -> int:
    """Let everything be said again. For a test, or a user starting over."""
    gone = 0
    try:
        for path in _where().glob("*.json"):
            if project is None:
                path.unlink()
                gone += 1
                continue
            try:
                held = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if str(project) in held.get("subject", ""):
                path.unlink()
                gone += 1
    except OSError:
        pass
    return gone
