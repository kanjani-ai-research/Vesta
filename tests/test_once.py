"""Saying a thing once.

Companion mode has one standard: it works without the user doing anything, and
it does not make itself felt. The failure that breaks that is repetition — the
defects in a file do not change between prompts, so somebody editing it was
told the same thing on every message until they stopped reading.
"""

from __future__ import annotations

import pytest

from vesta.once import already_said, forget, say_once


@pytest.fixture(autouse=True)
def _a_session(tmp_path, monkeypatch):
    monkeypatch.setenv("VESTA_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "one-session")
    yield


def test_the_first_time_it_is_said(tmp_path):
    assert say_once(tmp_path, "a subject", "the message") == "the message"


def test_the_second_time_it_is_not(tmp_path):
    say_once(tmp_path, "a subject", "the message")
    assert say_once(tmp_path, "a subject", "the message") == ""


def test_a_different_subject_is_still_said(tmp_path):
    """A new fact is not a repeat. Somebody editing a second file should hear
    about that file."""
    say_once(tmp_path, "defects in a.py", "about a")
    assert say_once(tmp_path, "defects in b.py", "about b") == "about b"


def test_a_new_session_may_say_it_again(tmp_path, monkeypatch):
    """Not once ever. A new session is a new working context, and a defect
    nobody acted on last week is worth mentioning again today."""
    say_once(tmp_path, "a subject", "the message")
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "a-later-session")
    assert say_once(tmp_path, "a subject", "the message") == "the message"


def test_a_different_project_is_separate(tmp_path):
    say_once(tmp_path / "one", "a subject", "the message")
    assert say_once(tmp_path / "two", "a subject", "the message") == "the message"


def test_nothing_is_recorded_for_an_empty_message(tmp_path):
    """Silence is not a telling, and must not suppress a later real one."""
    assert say_once(tmp_path, "a subject", "") == ""
    assert not already_said(tmp_path, "a subject")


def test_forgetting_lets_it_be_said_again(tmp_path):
    say_once(tmp_path, "a subject", "the message")
    forget()
    assert say_once(tmp_path, "a subject", "the message") == "the message"


def test_an_unreadable_note_does_not_silence_anything(tmp_path, monkeypatch):
    """A hook that failed because it could not read its own notes would be
    worse than one that repeated itself."""
    import vesta.once as once

    def _broken():
        raise OSError("no")

    monkeypatch.setattr(once, "_where", _broken)
    assert not already_said(tmp_path, "a subject")
    assert say_once(tmp_path, "a subject", "the message") == "the message"


# ── What it is for ──────────────────────────────────────────────────────────


def test_a_defect_is_raised_once_and_then_left_alone(tmp_path, monkeypatch):
    """The whole point. Eight prompts about one file, one interruption."""
    from vesta.held import graph_for
    from vesta.inject import _something_already_wrong

    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "keep.py").write_text(
        "def store(items):\n"
        "    kept = []\n"
        "    for item in items:\n"
        "        try:\n"
        "            kept.append(item)\n"
        "        except Exception:\n"
        "            pass\n"
        "    return kept\n"
        "\n"
        "def use():\n"
        "    return store([1])\n",
        encoding="utf-8",
    )
    graph_for(repo, rebuild=True)

    said = [
        bool(_something_already_wrong("fix keep.py", str(repo)))
        for _ in range(4)
    ]
    assert said == [True, False, False, False]


def test_notes_from_old_sessions_are_swept(tmp_path, monkeypatch):
    """Keyed by session rather than by repository, so nothing else would ever
    collect them — and a directory nobody prunes stops describing anything."""
    import os
    import time

    import vesta.once as once

    say_once(tmp_path, "a subject", "the message")
    stale = next(once._where().glob("*.json"))
    old = time.time() - once.KEEP_FOR - 60
    os.utime(stale, (old, old))

    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "a-different-session")
    say_once(tmp_path, "something else", "another message")

    assert not stale.exists()
