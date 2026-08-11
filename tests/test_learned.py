"""Patterns nobody wrote by hand, and what happens before there are any.

The bootstrap is the question this answers: a new project has no corrections,
so no derived patterns. It is handled by not depending on history — the
structural finders and a small seed work from the first minute, and derived
patterns are what a project gains as it accumulates exchanges.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from vesta.learned import Learned, Pattern, _exchanges, everything, seeded


def a_transcript(tmp_path: Path, *turns) -> Path:
    path = tmp_path / "s.jsonl"
    path.write_text(
        "\n".join(
            json.dumps({"message": {"role": role, "content": [{"type": "text", "text": text}]}})
            for role, text in turns
        ),
        encoding="utf-8",
    )
    return path


# ── The unit is an exchange ──────────────────────────────────────────────


def test_a_user_turn_after_agent_work_is_an_exchange(tmp_path: Path):
    """Where defects get named. The hardcoded-language defect took three turns;
    no single sentence in it is a defect statement."""
    path = a_transcript(
        tmp_path,
        ("user", "build a resolver for the languages we support in this repo"),
        ("assistant", "I added a marker list covering python, rust and go for now."),
        ("user", "your project markers are wholly insufficient, this would be disastrous"),
    )
    found = _exchanges([path])

    assert len(found) == 1
    did, said, _ = found[0]
    assert "marker list" in did
    assert "wholly insufficient" in said


def test_a_user_turn_starting_a_session_is_not_an_exchange(tmp_path: Path):
    """Nothing was done yet, so nothing was corrected."""
    path = a_transcript(tmp_path, ("user", "please build me a resolver for this repository"))

    assert not _exchanges([path])


def test_harness_content_is_not_the_user_speaking(tmp_path: Path):
    path = a_transcript(
        tmp_path,
        ("assistant", "Here is what I built for you, with the marker list included."),
        ("user", "<system-reminder>something injected by the harness entirely</system-reminder>"),
    )

    assert not _exchanges([path])


# ── Before there is any history ──────────────────────────────────────────


def test_a_project_with_no_history_still_has_patterns():
    """The floor. A project that never corrects anything keeps it."""
    assert seeded()
    assert all(p.origin == "seeded" for p in seeded())


def test_a_seeded_pattern_finds_a_real_defect(tmp_path: Path):
    (tmp_path / "app.py").write_text(
        'SERVERS = {"python": [".py"], "rust": [".rs"]}\n', encoding="utf-8"
    )
    found = [f for p in seeded() for f in p.find(tmp_path)]

    assert found
    assert found[0].sites[0].line == 1


def test_a_projects_own_pattern_supersedes_the_prior(tmp_path: Path, monkeypatch):
    """A finder built from this codebase's corrections knows more about it than
    somebody else's prior does."""
    import vesta.learned as learned

    monkeypatch.setattr(
        learned,
        "recall",
        lambda repo: Learned(patterns=[
            Pattern(name="hardcoded language list", why="theirs", pattern="x")
        ]),
    )
    got = {p.name.lower(): p for p in everything(tmp_path)}

    assert got["hardcoded language list"].origin == "derived"


def test_where_a_pattern_came_from_is_visible(tmp_path: Path):
    """A stranger should see which findings come from their code and which from
    somebody else's priors."""
    assert all(p.origin in ("seeded", "derived") for p in everything(tmp_path))
