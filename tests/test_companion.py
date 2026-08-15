"""Everything companion mode is supposed to do, checked at once.

**The question this answers is "does it all still work", not "does this
function return the right value".** Every other test here pins one behaviour;
the failure this is written against is different — a session where six things
are supposed to happen, five do, and nobody notices which one stopped.

Run against the hooks as the framework invokes them, with real payloads, so a
pass means the plugin behaves rather than that the library does.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest


@pytest.fixture
def working(tmp_path, monkeypatch):
    """A repository with a graph, a defect, and a session."""
    monkeypatch.setenv("VESTA_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "companion-audit")
    from vesta.held import graph_for

    root = tmp_path / "repo"
    root.mkdir()
    (root / "store.py").write_text(
        "def retain(items):\n"
        "    kept = []\n"
        "    for item in items:\n"
        "        try:\n"
        "            kept.append(item)\n"
        "        except Exception:\n"
        "            pass\n"
        "    return kept\n"
        "\n"
        "def use():\n"
        "    return retain([1])\n",
        encoding="utf-8",
    )
    graph_for(root, rebuild=True)
    return root


def _injected(prompt: str, root: Path) -> str:
    from vesta.inject import (
        _a_rule_in_doubt,
        _a_rule_stated,
        _never_been_read,
        _something_already_wrong,
        _something_to_build,
        _the_graph_can_answer_this,
        context_for,
    )

    said = [context_for(prompt, root)]
    for offer in (
        _something_to_build,
        _a_rule_in_doubt,
        _something_already_wrong,
        _never_been_read,
        _the_graph_can_answer_this,
    ):
        said.append(offer(prompt, str(root)))
    said.append(_a_rule_stated(prompt))
    return "\n".join(s for s in said if s)


# ── The n things ────────────────────────────────────────────────────────────


def test_1_the_graph_is_current(working):
    from vesta.ready import readiness

    assert readiness(working).is_current


def test_2_it_answers_about_a_definition_the_prompt_names(working):
    assert "retain" in _injected("what does retain do", working)


def test_3_it_surfaces_a_defect_in_a_file_about_to_change(working):
    assert "already known to be wrong" in _injected("fix store.py", working)


def test_4_it_says_a_thing_once(working):
    first = _injected("fix store.py", working)
    again = _injected("fix store.py once more", working)

    assert "already known to be wrong" in first
    assert "already known to be wrong" not in again


def test_5_it_is_silent_when_there_is_nothing_to_say(working):
    assert _injected("thanks", working) == ""


def test_6_it_denies_a_search_the_graph_answers(working):
    from vesta.instead import decide

    said = decide(
        {"tool_name": "Grep", "tool_input": {"pattern": "def retain"}, "cwd": str(working)}
    )
    assert said["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert "store.py" in said["hookSpecificOutput"]["permissionDecisionReason"]


def test_7_it_allows_a_search_it_cannot_answer(working):
    from vesta.instead import decide

    assert decide(
        {"tool_name": "Grep", "tool_input": {"pattern": "TODO"}, "cwd": str(working)}
    ) is None


def test_8_it_offers_to_record_a_rule_the_user_states(working):
    said = _injected("never use a bare except in this project", working)
    assert "declare" in said.lower()


def test_9_the_turn_ending_brings_the_graph_up_to_date(working, monkeypatch):
    """The graph is most stale exactly when the work finishes, and that is the
    one moment nobody is waiting for it."""
    import io
    import sys
    import time

    from vesta.keepgoing import main
    from vesta.ready import MOVED_ON, readiness

    (working / "later.py").write_text("def two():\n    return 2\n", encoding="utf-8")
    time.sleep(0.25)
    assert readiness(working).state == MOVED_ON

    monkeypatch.setattr(
        sys, "stdin", io.StringIO(json.dumps({"cwd": str(working), "session_id": "s"}))
    )
    assert main() == 0  # never blocks, never traps a session


def test_10_automation_is_not_offered_in_a_repository_under_way(working):
    said = _injected(
        "build me an expense tracker: record an expense, see what I spent, "
        "set budgets, and export to CSV",
        working,
    )
    assert "AskUserQuestion" not in said


def test_11_the_tools_answer(working):
    from vesta.sidecar import _does, _shape, _uses

    assert "store.py" in _uses("retain", working)
    assert _shape(working)
    assert _does("keeping things", working)
