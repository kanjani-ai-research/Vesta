"""Refusing to stop while there is measurably work left.

A `Stop` hook, which is how a loop is made. The mechanism is the same one the
leading loop plugin uses; the difference is the condition. Theirs ends when the
model states a promise — and its own prompt has to say *"do not output false
promises to escape the loop"*, which concedes that the model is the wrong judge.
This ends when the counts do: every agreed behaviour built and reached by a
test, the tests passing, the user's rules honoured, nothing outstanding.

**Off unless somebody turned it on.** Blocking a session from ending is the
most intrusive thing this plugin can do, so it happens only where a user has
explicitly asked for it, per project.

**It gives up.** Three iterations that move nothing, or forty in total, and it
stops and says what remains. A loop that cannot tell it is stuck is a loop that
spends somebody's money proving it.

**Silent on every failure.** A Stop hook that raises is a session that cannot
end, which is worse than any amount of unfinished work.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path
from typing import Optional, Sequence

logger = logging.getLogger("vesta.keepgoing")


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Read the framework's payload, and answer whether the work is done."""
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except (ValueError, OSError):
        return 0

    try:
        return _answer(payload)
    except Exception as exc:  # noqa: BLE001 - never trap a session
        logger.debug("could not decide whether to continue: %s", exc)
        return 0


def _answer(payload: dict) -> int:
    from . import driving

    where = payload.get("cwd") or os.environ.get("CLAUDE_PROJECT_DIR") or "."
    root = Path(where).expanduser().resolve()

    # Asked as this session, so consent that belonged to another one does not
    # carry over.
    here = driving.state(root, payload.get("session_id", ""))
    if not here.on:
        # It stopped on its own, and this is the first stop since. Say why
        # once: a loop that gives up silently looks exactly like one that
        # finished, and those are opposite outcomes.
        if here.stopped and not here.told:
            print(json.dumps({"systemMessage": f"Vesta: {here.stopped}"}))
            here.told = True
            driving._keep(here, root)
        return 0

    # Another session's loop. The state is per project and this hook fires in
    # every session open on it, so a loop somebody else started must not trap
    # this one. Learned from the reference implementation, which had to fix it.
    verdict = driving.iterate(root)
    if not verdict.keep_going:
        # Done, stuck, or spent. Say which, and let the session end.
        print(
            json.dumps(
                {
                    "systemMessage": f"Vesta: {verdict.describe()}",
                }
            )
        )
        return 0

    outstanding = "\n".join(f"  · {o}" for o in verdict.outstanding[:8])
    print(
        json.dumps(
            {
                "decision": "block",
                "reason": (
                    "The agreed work is not finished. These are counted, not "
                    f"judged:\n{outstanding}\n\n"
                    "Continue until each is cleared. Do not say the work is "
                    "done while any remains — this is checked, not taken on "
                    "trust. If something here cannot be cleared, say what and "
                    "why rather than working around it.\n\n"
                    "A behaviour you have already built still shows as `not "
                    "built` until you record it:\n"
                    '  $V contract --met "<the behaviour, word for word>" '
                    '--node "file.py:function" --test "test_file.py:test"'
                ),
                "systemMessage": (
                    f"Vesta: {len(verdict.outstanding)} outstanding "
                    f"(iteration {driving.state(root).iterations})"
                ),
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
