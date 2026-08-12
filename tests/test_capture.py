"""Recording a rule at the moment the user states it.

The user's objection to the first design, in their words: adjudication meant
"typing more, keeping aware to type in everything they want recorded, and
tracking identifiers on their own". That is bookkeeping, and it is the tool's
job. So nothing is invoked: the agent is already reading the message, and it
records what it hears.

Which makes the *instruction* the mechanism. There is no algorithm to test —
the judgement is the agent's — so what is tested is that the instruction exists,
says the things that make the judgement possible, and does not contradict
itself. The judgement itself is scored against `fixtures/what_to_record.json`,
whose verdicts were fixed before the capture path was built.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent.parent
SKILL = HERE / "skills" / "vesta" / "SKILL.md"
FIXTURE = HERE / "tests" / "fixtures" / "what_to_record.json"


def _flat(text: str) -> str:
    """Text with its line breaks removed.

    A phrase is a phrase whether or not the file wrapped in the middle of it,
    and a test that fails because a sentence moved is a test about formatting.
    """
    return " ".join(text.split()).lower()


def test_the_skill_tells_the_agent_to_record():
    """Without this, capture depends on an agent inventing the idea."""
    said = _flat(SKILL.read_text(encoding="utf-8"))
    assert "declare" in said
    assert "when they say it" in said


def test_the_instruction_separates_standing_from_this_turn():
    """The distinction the whole thing rests on: "one .env for v3" stands,
    "don't edit anything yet" expires."""
    said = _flat(SKILL.read_text(encoding="utf-8"))
    assert "standing" in said
    assert "turn" in said


def test_the_instruction_separates_deciding_from_musing():
    said = _flat(SKILL.read_text(encoding="utf-8"))
    assert "thinking aloud" in said or "invites an answer" in said


def test_the_instruction_forbids_recording_the_agents_own_conclusions():
    """A rule the user never stated has nobody behind it."""
    said = _flat(SKILL.read_text(encoding="utf-8"))
    assert "do not record a conclusion you reached" in said


def test_the_instruction_does_not_ask_permission():
    """Asking for each one makes capture cost more than the rule is worth."""
    said = _flat(SKILL.read_text(encoding="utf-8"))
    assert "do not interrupt to confirm" in said


def test_the_tool_description_says_when_to_call_it():
    """The description is what routes an agent that has not read the skill."""
    import asyncio
    import warnings

    warnings.filterwarnings("ignore")
    from vesta.sidecar import build_server

    tools = asyncio.run(build_server().list_tools())
    declare = next(t for t in tools if t.name == "declare")
    said = _flat(declare.description)
    assert "the moment a user states" in said
    assert "do not interrupt to confirm" in said
    assert "expires with the turn" in said


def test_the_standard_is_fixed_and_balanced():
    """A standard that is mostly one answer scores nothing."""
    cases = json.loads(FIXTURE.read_text(encoding="utf-8"))["cases"]
    record = [c for c in cases if c["record"]]
    assert len(cases) >= 10
    assert 3 <= len(record) <= len(cases) - 3
    for case in cases:
        assert case["why"], "every case must say why, or it cannot be argued with"


def test_every_case_in_the_standard_is_something_a_person_would_say():
    """Invented examples make an instruction that works only on inventions."""
    cases = json.loads(FIXTURE.read_text(encoding="utf-8"))["cases"]
    for case in cases:
        assert 10 < len(case["said"]) < 200


def test_what_is_said_back_is_one_line():
    """It is said to a user who asked for something else, mid-answer."""
    import tempfile

    from vesta import confirm

    where = Path(tempfile.mkdtemp())
    confirm.declare(where, "one .env for the whole of v3")
    standing = sum(1 for v in confirm.recall(where).verdicts if v.binding)
    said = (
        f"Recorded as a standing rule for {where.name} "
        f"({standing} in all). `decided` reviews them."
    )
    assert len(said.splitlines()) == 1
    assert len(said) < 120


def test_recording_the_same_rule_twice_does_not_duplicate(tmp_path):
    """Safe to call again, so an agent need not track what it has recorded."""
    from vesta import confirm

    confirm.declare(tmp_path, "one .env for the whole of v3")
    confirm.declare(tmp_path, "one .env for the whole of v3")
    assert len(confirm.recall(tmp_path).verdicts) == 1


def test_a_recorded_rule_needs_no_further_adjudication(tmp_path):
    """It stands from the moment it is said. Nothing to confirm afterwards."""
    from vesta import confirm
    from vesta.rules import Found

    confirm.declare(tmp_path, "deps must be pinned")
    kept = confirm.apply(Found(), tmp_path)
    assert [r.text for r in kept.rules] == ["deps must be pinned"]
    assert confirm.recall(tmp_path).waiting == []


def test_what_was_recorded_recently_can_be_seen(tmp_path):
    """A rule captured while somebody worked on something else is agreed to in
    the moment and forgotten by the afternoon. If one was captured wrongly, the
    only cost is that nobody notices — so today's captures are visible today."""
    import time

    from vesta import confirm

    confirm.declare(tmp_path, "one .env for the whole of v3")
    confirm.record(tmp_path, "an older one", confirm.IS_A_RULE, at=time.time() - 200000)

    lately = confirm.recall(tmp_path).lately(time.time() - 86400)
    assert [v.text for v in lately] == ["one .env for the whole of v3"]


def test_recent_captures_say_how_they_arrived(tmp_path):
    """A declared rule is the one kind nobody explicitly confirmed."""
    import time

    from vesta import confirm

    confirm.declare(tmp_path, "one .env for the whole of v3")
    lately = confirm.recall(tmp_path).lately(time.time() - 86400)
    assert "declared" in lately[0].describe()


def test_the_newest_is_first(tmp_path):
    import time

    from vesta import confirm

    now = time.time()
    confirm.record(tmp_path, "older", confirm.IS_A_RULE, at=now - 100)
    confirm.record(tmp_path, "newer", confirm.IS_A_RULE, at=now)
    lately = confirm.recall(tmp_path).lately(now - 86400)
    assert [v.text for v in lately] == ["newer", "older"]
