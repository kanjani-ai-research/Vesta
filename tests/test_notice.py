"""Noticing that a prompt is about somewhere else."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from vesta.notice import elsewhere_in, main, say


@pytest.fixture
def referenced(tmp_path):
    """A prepared project that is not the one under works."""
    from vesta.held import graph_for

    root = tmp_path / "indexer"
    root.mkdir()
    (root / "search.py").write_text('"""Searching."""\n\n\ndef find():\n    return 1\n')
    graph_for(root)
    here = tmp_path / "newapp"
    here.mkdir()
    return here, root


def test_a_reference_with_a_question_is_noticed(referenced):
    here, _ = referenced
    found = elsewhere_in("do it how the indexer did fuzzy search", here)
    assert [name for name, _ in found] == ["indexer"]


def test_a_bare_name_is_not_a_reference(referenced):
    """A name on its own is usually just a name. Firing on it teaches the user
    to stop reading what Vesta says."""
    here, _ = referenced
    assert elsewhere_in("indexer", here) == []


def test_a_prompt_about_nothing_else_is_silent(referenced):
    here, _ = referenced
    assert elsewhere_in("add a field to the form", here) == []


def test_the_project_under_works_is_never_offered(referenced):
    """Its name appears in its own prompts constantly."""
    _, other = referenced
    assert elsewhere_in("how does indexer do this", other) == []


def test_a_path_stands_without_an_asking_word(referenced):
    here, other = referenced
    found = elsewhere_in(f"look at {other}/search.py", here)
    assert [name for name, _ in found] == ["indexer"]


def test_a_project_that_is_gone_is_not_offered(referenced, tmp_path):
    here, other = referenced
    for path in other.iterdir():
        path.unlink()
    other.rmdir()
    assert elsewhere_in("how did the indexer do it", here) == []


def test_nothing_is_said_when_nothing_matched():
    assert say([]) == ""


def test_what_is_said_names_the_tool_and_the_precedence():
    said = say([("indexer", "/tmp/indexer")])
    assert "elsewhere" in said
    assert "consulted, not merged" in said


def test_the_hook_survives_anything(monkeypatch, capsys):
    """It runs on every prompt. Breaking one is worse than missing a reference."""
    for payload in ("", "not json", "{}", '{"prompt": null}', '{"cwd": 12}'):
        monkeypatch.setattr("sys.stdin", _Reads(payload))
        assert main() == 0


def test_the_hook_speaks_the_framework_s_shape(referenced, monkeypatch, capsys):
    here, _ = referenced
    monkeypatch.setattr(
        "sys.stdin",
        _Reads(json.dumps({"prompt": "how did the indexer do search", "cwd": str(here)})),
    )
    assert main() == 0
    said = json.loads(capsys.readouterr().out)
    assert said["hookSpecificOutput"]["hookEventName"] == "UserPromptSubmit"
    assert "indexer" in said["hookSpecificOutput"]["additionalContext"]


def test_the_hook_says_nothing_when_there_is_nothing_to_say(referenced, monkeypatch, capsys):
    here, _ = referenced
    monkeypatch.setattr(
        "sys.stdin", _Reads(json.dumps({"prompt": "add a field", "cwd": str(here)}))
    )
    assert main() == 0
    assert capsys.readouterr().out.strip() == ""


def test_the_notice_does_not_import_pydantic():
    """It runs on every prompt, and that import costs more than everything else
    this does put together."""
    done = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys, vesta.notice; "
            "print('pydantic' in sys.modules)",
        ],
        capture_output=True,
        text=True,
    )
    assert done.stdout.strip() == "False", done.stderr


class _Reads:
    def __init__(self, text: str) -> None:
        self._text = text

    def read(self) -> str:
        return self._text
