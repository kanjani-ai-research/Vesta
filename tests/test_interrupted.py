"""A turn the API cut short is noted, and said once at the next prompt."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from vesta import driving, interrupted

HERE = Path(__file__).resolve().parent.parent


def _failed(error: str = "rate_limit", session: str = "s1") -> dict:
    return {
        "hook_event_name": "StopFailure",
        "session_id": session,
        "error": error,
        "last_assistant_message": "API Error: Rate limit reached",
    }


def test_a_failure_is_said_once_and_then_forgotten(tmp_path):
    interrupted.record(tmp_path, _failed())
    said = interrupted.once(tmp_path, "s1")
    assert "`rate_limit`" in said
    assert "cut short" in said
    assert "git status" in said
    assert interrupted.once(tmp_path, "s1") == ""


def test_failures_in_a_row_are_one_note_counted(tmp_path):
    for _ in range(3):
        interrupted.record(tmp_path, _failed("overloaded"))
    assert "3 times running" in interrupted.once(tmp_path, "s1")


def test_a_timeout_is_treated_as_passing(tmp_path):
    interrupted.record(tmp_path, _failed("server_error"))
    said = interrupted.once(tmp_path, "s1")
    assert "half-done" in said
    assert "Waiting will not fix" not in said


def test_an_error_waiting_will_not_fix_says_so(tmp_path):
    interrupted.record(tmp_path, _failed("billing_error"))
    said = interrupted.once(tmp_path, "s1")
    assert "Waiting will not fix" in said


def test_the_output_limit_asks_for_smaller_steps(tmp_path):
    interrupted.record(tmp_path, _failed("max_output_tokens"))
    assert "smaller steps" in interrupted.once(tmp_path, "s1")


def test_a_stale_note_is_dropped(tmp_path):
    interrupted.record(tmp_path, _failed(), at=0)
    assert interrupted.once(tmp_path, "s1", at=interrupted.STALE_AFTER + 1) == ""
    assert interrupted.once(tmp_path, "s1") == ""


def test_another_session_is_told_it_was_the_last_session(tmp_path):
    interrupted.record(tmp_path, _failed(session="old"))
    assert "last session on this project" in interrupted.once(tmp_path, "new")


def test_a_driven_loop_is_not_counted_against(tmp_path):
    driving.start(tmp_path, session="s1")
    before = driving.state(tmp_path, "s1").iterations
    interrupted.record(tmp_path, _failed())
    said = interrupted.once(tmp_path, "s1")
    assert "interrupted, not stopped" in said
    assert driving.state(tmp_path, "s1").iterations == before


def test_the_hook_is_silent_and_keeps_the_note(tmp_path):
    from vesta.home import home

    done = subprocess.run(
        [sys.executable, "-m", "vesta.interrupted"],
        input=json.dumps({**_failed(), "cwd": str(tmp_path)}),
        capture_output=True,
        text=True,
        timeout=120,
        env={**os.environ, "VESTA_HOME": str(home()), "CLAUDE_PROJECT_DIR": str(tmp_path)},
    )
    assert done.returncode == 0
    assert done.stdout.strip() == ""
    assert "rate_limit" in interrupted.once(tmp_path, "s1")


def test_the_hook_survives_garbage():
    done = subprocess.run(
        [sys.executable, "-m", "vesta.interrupted"],
        input="not json",
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert done.returncode == 0
    assert done.stdout.strip() == ""


def test_the_script_is_wired_into_the_plugin():
    wiring = json.loads((HERE / "hooks" / "hooks.json").read_text(encoding="utf-8"))
    commands = [
        entry["command"]
        for group in wiring["hooks"]["StopFailure"]
        for entry in group["hooks"]
    ]
    assert any("interrupted.sh" in c for c in commands)


def test_the_next_prompt_hears_of_it(tmp_path, monkeypatch, capsys):
    import io

    from vesta.inject import main

    interrupted.record(tmp_path, _failed())
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    monkeypatch.setattr(
        sys, "stdin", io.StringIO(json.dumps({"prompt": "continue", "session_id": "s1"}))
    )
    main()
    out = json.loads(capsys.readouterr().out)
    assert "`rate_limit`" in out["hookSpecificOutput"]["additionalContext"]
