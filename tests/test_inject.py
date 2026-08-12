"""Putting what is known in front of an agent, before it decides anything.

This had no tests and was wired only by a stale project-level setting running a
bare `python`, which printed `python: command not found` above every prompt in
a session. The capability was fine; nothing held it to account.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from vesta.inject import context_for, main

HERE = Path(__file__).resolve().parent.parent


class _Reads:
    def __init__(self, text: str) -> None:
        self._text = text

    def read(self) -> str:
        return self._text


@pytest.fixture
def repository(tmp_path):
    """A graphed repository holding one plainly-named definition."""
    from vesta.held import graph_for

    (tmp_path / "work.py").write_text(
        '"""Doing the work."""\n\n\ndef admit(entry):\n    """Take one in."""\n    return entry\n',
        encoding="utf-8",
    )
    graph_for(tmp_path)
    return tmp_path


def test_a_prompt_naming_nothing_is_answered_with_nothing(repository):
    """A hook that prepends to every prompt is a tax on every prompt."""
    assert context_for("add a new field to the form", repository) == ""


def test_a_prompt_naming_a_definition_is_answered(repository):
    said = context_for("how does admit work", repository)
    assert said, "nothing was offered about a definition the graph holds"
    assert "admit" in said


def test_what_is_offered_does_not_pose_as_the_code(repository):
    """It is what earlier sessions worked out, not a substitute for reading."""
    said = context_for("how does admit work", repository)
    assert "not a substitute" in said.lower()


def test_the_hook_speaks_the_frameworks_shape(repository, monkeypatch, capsys):
    monkeypatch.setattr(
        "sys.stdin",
        _Reads(json.dumps({"prompt": "how does admit work", "cwd": str(repository)})),
    )
    assert main() == 0
    said = json.loads(capsys.readouterr().out)
    assert said["hookSpecificOutput"]["hookEventName"] == "UserPromptSubmit"
    assert said["hookSpecificOutput"]["additionalContext"]


def test_the_hook_says_nothing_when_it_has_nothing(repository, monkeypatch, capsys):
    monkeypatch.setattr(
        "sys.stdin",
        _Reads(json.dumps({"prompt": "add a field", "cwd": str(repository)})),
    )
    assert main() == 0
    assert capsys.readouterr().out.strip() == ""


def test_the_hook_survives_anything(monkeypatch):
    """It runs on every prompt. Breaking one is worse than contributing none."""
    for payload in ("", "not json", "{}", '{"prompt": null}', '{"cwd": 12}'):
        monkeypatch.setattr("sys.stdin", _Reads(payload))
        assert main() == 0


def test_it_records_what_it_injected(repository, monkeypatch, capsys):
    """So the saving is measurable rather than asserted."""
    from vesta.home import home

    monkeypatch.setattr(
        "sys.stdin",
        _Reads(json.dumps({"prompt": "how does admit work", "cwd": str(repository)})),
    )
    main()
    capsys.readouterr()
    log = home() / "injected.jsonl"
    assert log.is_file()
    assert json.loads(log.read_text(encoding="utf-8").splitlines()[-1])["chars"] > 0


def test_the_script_is_wired_into_the_plugin():
    """The failure this file exists for: a capability nothing runs."""
    wiring = json.loads((HERE / "hooks" / "hooks.json").read_text(encoding="utf-8"))
    commands = [
        entry["command"]
        for group in wiring["hooks"]["UserPromptSubmit"]
        for entry in group["hooks"]
    ]
    assert any("inject.sh" in c for c in commands), "inject is not wired to anything"


def test_the_script_never_leaks_an_error(tmp_path):
    """It runs on every prompt, including before Vesta can run at all."""
    done = subprocess.run(
        [str(HERE / "hooks" / "inject.sh")],
        input='{"prompt":"x","cwd":"/tmp"}',
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin", "VESTA_NO_INSTALL": "1", "HOME": str(tmp_path)},
        timeout=60,
    )
    assert done.stderr.strip() == ""
    assert "command not found" not in done.stdout + done.stderr
    assert done.returncode == 0
