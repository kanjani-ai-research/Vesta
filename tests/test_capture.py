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


# ── What a live session found ───────────────────────────────────────────────
#
# Three defects, none visible from any test that existed. Capture never fired
# because the instruction lived in a skill that was never selected; the rule
# was rejected and the turn-scoped instruction accepted; and the injection
# matched an ordinary English word to an unrelated definition.


def test_a_stated_rule_is_recognised_even_when_a_question_follows():
    """The live failure. "every module must open with a docstring — does
    resolve.py follow that?" states a rule and then asks about it; the question
    mark made it read as deliberation and the rule was thrown away."""
    from vesta.rules import constrains

    assert constrains(
        "in this project every module must open with a docstring saying what "
        "it is for. can you check whether resolve.py follows that?"
    )


def test_a_turn_scoped_instruction_is_still_refused():
    """The same live session recorded this as a standing rule — the most
    turn-scoped sentence imaginable."""
    from vesta.rules import constrains

    assert not constrains(
        "don't edit anything yet, just tell me what you would change in vesta/cli.py"
    )
    assert not constrains("hold off on the refactor for now")
    assert not constrains("just tell me what you would do, don't change it yet")


def test_a_constraint_that_is_itself_the_question_is_refused():
    """Asking whether a rule should exist is not stating one."""
    from vesta.rules import constrains

    assert not constrains("must every module have a docstring?")
    assert not constrains("should we pin every dependency?")


def test_the_hook_tells_the_agent_to_record_a_stated_rule():
    """The mechanism, and why it moved. A skill loads when its description
    matches; a user who states a rule while asking for something else matches
    no description about asking, so the instruction was never in front of the
    agent and nothing was recorded."""
    from vesta.inject import _a_rule_stated

    said = _a_rule_stated(
        "in this project every module must open with a docstring saying what "
        "it is for. can you check whether resolve.py follows that?"
    )
    assert "declare" in said
    assert "own words" in said
    # And it leaves the judgement with the agent rather than asserting.
    assert "may have" in said
    assert "if it only scopes this turn, do nothing" in said.lower()


def test_the_hook_says_nothing_about_a_turn_scoped_instruction():
    from vesta.inject import _a_rule_stated

    assert _a_rule_stated("don't edit anything yet, just tell me") == ""
    assert _a_rule_stated("add a field to the form") == ""


def test_an_ordinary_english_word_is_not_a_definition():
    """"tell me what you would change" named no definition, and answering it
    with everything called `Change` teaches an agent to skim past the channel."""
    from vesta.inject import TOO_COMMON

    for word in ("change", "work", "rule", "said", "use", "value", "state"):
        assert word in TOO_COMMON


def test_the_skill_description_covers_stating_a_rule():
    """It is what decides whether the skill is selected at all."""
    said = _flat(SKILL.read_text(encoding="utf-8").split("---")[1])
    assert "states a standing constraint" in said or "record a rule the moment" in said


# ── Inheriting the benefit without trying ───────────────────────────────────
#
# The whole intention: a user installs the plugin, works as they normally do,
# and gets the benefit. Anything that requires them to know a command, an agent
# name, or that Vesta exists at all is a failure of that intention.


def test_no_answer_tells_the_user_to_run_an_agent():
    """Three tools said "Run the `vesta-domain` agent on it". A user who
    installed a plugin and carried on working does not know that agent exists,
    and telling them to run it is telling them to do the tool's job."""
    import inspect

    from vesta import sidecar

    source = inspect.getsource(sidecar)
    for said in ("Run the `vesta-domain` agent", "Run the `vesta-rules` agent"):
        assert said not in source, f"an answer still instructs the user: {said}"


def test_preparation_is_addressed_to_the_agent():
    import inspect

    from vesta import sidecar

    source = inspect.getsource(sidecar)
    assert "subagent now, yourself, without asking" in source


def test_the_skill_authorises_running_it_unprompted():
    """Agents do not spawn subagents on their own initiative by default."""
    said = _flat(SKILL.read_text(encoding="utf-8"))
    assert "run the subagent it names, yourself, without asking" in said
    assert "do not ask permission" in said
    assert "do not announce the preparation" in said


def test_a_fresh_repository_answers_what_it_can_without_preparation(tmp_path):
    """Three of the four halves must work untouched, or the first impression
    of the plugin is that it does nothing."""
    import warnings

    warnings.filterwarnings("ignore")
    from vesta.held import graph_for
    from vesta.sidecar import _defects, _shape

    (tmp_path / "api.py").write_text(
        '"""Serving requests."""\n\n\ndef handle(request):\n    return 1\n',
        encoding="utf-8",
    )
    graph_for(tmp_path)

    shape = _shape(tmp_path)
    assert "definition" in shape
    assert "agent" not in shape.lower()

    defects = _defects(tmp_path, 3)
    assert "agent" not in defects.lower()


def test_every_offer_the_hook_defines_is_actually_called():
    """The failure this covers: two offers were written, tested directly, and
    never wired into `main`. Their tests passed and the hook produced nothing —
    a whole feature dead in the one place it had to run.

    A reference graph cannot see this: the functions exist and are referenced
    by their tests, so nothing is unreferenced. What is missing is a call from
    one specific place."""
    import ast
    import inspect

    from vesta import inject

    source = inspect.getsource(inject)
    tree = ast.parse(source)

    offers = {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
        and node.name.startswith(("_a_", "_something_"))
    }
    assert offers, "no offers found at all"

    main = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "main"
    )
    called = {
        node.func.id
        for node in ast.walk(main)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }

    missing = offers - called
    assert not missing, f"defined but never called by the hook: {sorted(missing)}"
