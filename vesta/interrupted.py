"""Keeping a note when a turn ends because the API failed.

While the host waits on the API — "Waiting for API response", a retry, a
backoff after a timeout or an overload — no hook runs at all. If the retries
run out, the turn ends with `StopFailure` instead of `Stop`, and everything
hung on `Stop` is skipped: the graph is not caught up, a driven loop ends
without a word about why, and the next prompt knows nothing of it. An agent
then picks up a half-finished turn as if it were a fresh one, and redoes, or
undoes, edits already on disk.

**The host will not be steered here.** `StopFailure` output is discarded, so
nothing can be said now and nothing can be blocked. What can be done is keep a
note — what failed, when, and what was in flight — and say it once, at the
next prompt, where it is read.

**Not counted against a loop.** A turn the API cut short is not a turn that
made no progress, and must not bring a driven loop nearer to giving up. `Stop`
did not fire, so `iterate` was not called; this leaves it that way.

Silent on every failure, as every hook here is.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Optional, Sequence

logger = logging.getLogger("vesta.interrupted")

# Errors that waiting will not fix: somebody has to act outside the session.
# Everything else — a rate limit, an overload, a timeout, which arrives as
# `server_error` or `unknown` — is a pause the host already retried, not a
# verdict.
STANDING = {
    "authentication_failed",
    "oauth_org_not_allowed",
    "account_on_hold",
    "billing_error",
    "cloud_credential_error",
    "model_not_found",
}

# A note older than this is about another day's work, and saying it would be
# a non sequitur.
STALE_AFTER = 24 * 3600

# The rendered error is the host's own string; enough of it to recognise.
KEPT_OF_MESSAGE = 300


def _where(repo: Path | str) -> Path:
    from .home import kept_at

    return kept_at(repo, "interrupted")


def _root(payload: dict) -> Path:
    # CLAUDE_PROJECT_DIR first, same as vesta.keepgoing: `cwd` can drift.
    where = os.environ.get("CLAUDE_PROJECT_DIR") or payload.get("cwd") or "."
    return Path(where).expanduser().resolve()


def record(repo: Path | str, payload: dict, at: Optional[float] = None) -> dict:
    """Write down what failed and what was in flight when it did."""
    from . import driving

    session = str(payload.get("session_id") or "")
    note = {
        "error": str(payload.get("error") or "unknown"),
        "details": str(payload.get("error_details") or "")[:KEPT_OF_MESSAGE],
        "message": str(payload.get("last_assistant_message") or "")[:KEPT_OF_MESSAGE],
        "session": session,
        "at": at if at is not None else time.time(),
        "driving": False,
        "iteration": 0,
    }
    try:
        here = driving.state(repo, session)
        note["driving"] = bool(here.on)
        note["iteration"] = here.iterations
    except Exception as exc:  # noqa: BLE001 - the note matters more
        logger.debug("could not read the driving state: %s", exc)

    # Several failures before anybody types again are one interruption: keep
    # the latest, and how many there were.
    before = _read(repo)
    if before and before.get("session") == session:
        note["times"] = int(before.get("times", 1)) + 1
    else:
        note["times"] = 1

    path = _where(repo)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(note), encoding="utf-8")
    return note


def _read(repo: Path | str) -> Optional[dict]:
    path = _where(repo)
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def say(note: dict, session: str = "") -> str:
    """What the next turn should know, in the words it will read."""
    error = note.get("error", "unknown")
    when = time.strftime("%H:%M", time.localtime(note.get("at", time.time())))
    times = int(note.get("times", 1))
    again = f", {times} times running" if times > 1 else ""
    whose = (
        "The previous turn"
        if not session or note.get("session") in ("", session)
        else "The last session on this project"
    )
    lines = [
        f"Vesta: {whose} ended at {when} because the API failed (`{error}`"
        f"{again}) after the host's own retries ran out — it was cut short, "
        "not finished."
    ]

    if error in STANDING:
        lines.append(
            "Waiting will not fix this one; it needs the user to act outside "
            "the session (sign-in, billing, access or the model name). Say so "
            "plainly before doing any more work."
        )
    elif error == "max_output_tokens":
        lines.append(
            "The response hit the output limit. Take the rest in smaller "
            "steps: one file or one edit at a time, large files in parts."
        )
    elif error == "invalid_request":
        lines.append(
            "The request itself was refused, often because the conversation "
            "grew too large. If this repeats, suggest the user run /compact."
        )

    if error not in STANDING:
        lines.append(
            "Whatever it was doing may be half-done. Check the working tree "
            "(`git status`, `git diff`) before acting, and do not repeat an "
            "edit that is already on disk."
        )
    if note.get("driving"):
        lines.append(
            f"A driven loop was at iteration {note.get('iteration', 0)}. It "
            "was interrupted, not stopped, and this turn was not counted "
            "against it; carrying on resumes it."
        )
    return " ".join(lines)


def once(repo: Path | str, session: str = "", at: Optional[float] = None) -> str:
    """Say what interrupted the last turn, once, and forget it."""
    note = _read(repo)
    if not note:
        return ""
    try:
        _where(repo).unlink()
    except OSError:
        pass
    now = at if at is not None else time.time()
    if now - float(note.get("at", 0)) > STALE_AFTER:
        return ""
    return say(note, session)


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Run as a `StopFailure` hook. Its output is discarded, so it prints none."""
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except (ValueError, OSError):
        return 0

    try:
        root = _root(payload)
        record(root, payload)
        # `Stop` did not fire, so the graph was not caught up either. Edits
        # made before the failure are on disk all the same.
        from .keepgoing import _catch_up

        _catch_up(root)
    except Exception as exc:  # noqa: BLE001 - never trap a session
        logger.debug("could not keep a note of the failure: %s", exc)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
