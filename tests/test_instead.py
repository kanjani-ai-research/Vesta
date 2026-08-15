"""Refusing a search the graph already answers.

Telling an agent that better tools exist does not make it use them. Six offers
in the prompt hook describe Vesta at length and nothing measured whether one of
them changed what the agent then did. `PreToolUse` with `permissionDecision:
"deny"` is not a suggestion: the tool call does not run, and the reason reaches
Claude.

The line this must hold: refuse only where the graph is strictly better, and
never leave an agent with nothing.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from vesta.instead import answer_for, decide, what_it_wants


@pytest.fixture
def repo(tmp_path, monkeypatch):
    monkeypatch.setenv("VESTA_HOME", str(tmp_path / "home"))
    from vesta.held import graph_for

    root = tmp_path / "repo"
    root.mkdir()
    (root / "store.py").write_text(
        "def keep(item):\n"
        '    """Keep one."""\n'
        "    return item\n"
        "\n"
        "def use():\n"
        "    return keep(1)\n",
        encoding="utf-8",
    )
    graph_for(root, rebuild=True)
    return root


# ── What counts as hunting for a definition ─────────────────────────────────


def test_a_definition_search_is_recognised():
    assert what_it_wants("def graph_for") == "graph_for"
    assert what_it_wants("class Graph") == "Graph"
    assert what_it_wants("func Handle") == "Handle"
    assert what_it_wants("graph_for") == "graph_for"
    assert what_it_wants("Graph.referenced_by") == "Graph.referenced_by"


def test_an_ordinary_search_is_not():
    """A tool that blocks work it cannot do is uninstalled within the hour."""
    for pattern in (
        "TODO",
        "FIXME: this is wrong",
        "retry.*backoff",
        "import json",
        "# a comment",
        "https://example.com",
        "raise ValueError",
    ):
        assert what_it_wants(pattern) is None, pattern


def test_a_very_long_pattern_is_left_alone():
    assert what_it_wants("x" * 200) is None


# ── Refusing, and never refusing emptily ────────────────────────────────────


def test_a_search_for_a_held_definition_is_refused(repo):
    said = decide(
        {"tool_name": "Grep", "tool_input": {"pattern": "def keep"}, "cwd": str(repo)}
    )
    assert said is not None
    out = said["hookSpecificOutput"]
    assert out["permissionDecision"] == "deny"
    assert "store.py" in out["permissionDecisionReason"]


def test_the_refusal_carries_the_answer(repo):
    """A refusal that leaves an agent with nothing is the failure this must
    never have."""
    said = decide(
        {"tool_name": "Grep", "tool_input": {"pattern": "keep"}, "cwd": str(repo)}
    )
    reason = said["hookSpecificOutput"]["permissionDecisionReason"]

    assert "keep" in reason
    assert "referred to by" in reason
    assert "store.py" in reason


def test_a_definition_the_graph_does_not_hold_is_allowed(repo):
    assert decide(
        {
            "tool_name": "Grep",
            "tool_input": {"pattern": "def nothing_like_this"},
            "cwd": str(repo),
        }
    ) is None


def test_an_ordinary_search_is_allowed(repo):
    for pattern in ("TODO", "retry.*backoff", "raise ValueError"):
        assert decide(
            {"tool_name": "Grep", "tool_input": {"pattern": pattern}, "cwd": str(repo)}
        ) is None, pattern


def test_a_project_with_no_graph_is_allowed(tmp_path, monkeypatch):
    """Nothing to answer with, so the search is all there is."""
    monkeypatch.setenv("VESTA_HOME", str(tmp_path / "home"))
    root = tmp_path / "unprepared"
    root.mkdir()
    (root / "a.py").write_text("def keep(x):\n    return x\n", encoding="utf-8")

    assert decide(
        {"tool_name": "Grep", "tool_input": {"pattern": "def keep"}, "cwd": str(root)}
    ) is None


# ── The same through Bash ───────────────────────────────────────────────────


def test_a_grep_run_through_bash_is_caught(repo):
    said = decide(
        {
            "tool_name": "Bash",
            "tool_input": {"command": 'grep -rn "def keep" .'},
            "cwd": str(repo),
        }
    )
    assert said is not None
    assert said["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_a_bash_command_that_is_not_a_search_is_allowed(repo):
    for command in ("ls -la", "pytest -q", "git status", "cat store.py"):
        assert decide(
            {"tool_name": "Bash", "tool_input": {"command": command}, "cwd": str(repo)}
        ) is None, command


# ── The answer itself ───────────────────────────────────────────────────────


def test_the_answer_lists_places_not_edges(repo):
    """A caller that references something twice is one place to look, and
    listing it twice tells a reader nothing — twelve lines could describe six
    callers with no way to tell."""
    said = answer_for("keep", repo)
    lines = [l for l in said.splitlines() if l.strip().startswith("←")]
    assert len(lines) == len(set(lines))


def test_nothing_is_said_about_a_definition_that_is_not_there(repo):
    assert answer_for("not_a_real_name", repo) == ""


def test_a_malformed_payload_allows_the_call():
    """A hook that cannot decide must let the search through."""
    assert decide({}) is None
    assert decide({"tool_name": "Grep"}) is None
    assert decide({"tool_name": "Grep", "tool_input": {"pattern": "def x"}}) is None
