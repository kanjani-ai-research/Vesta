"""Named functions, the ask a model performs, and the refusals that keep both honest.

Most of these are about the disciplines the module exists for: a check with
nothing to check against is refused when written, a role pointing at no
recorded step is refused when added, an asserted criterion is reported as
asserted and never as met, and nothing here ever runs a model.
"""

from __future__ import annotations

import json

import pytest

import vesta.cli as cli
from vesta.function import (
    ASSERTED,
    CONTAINS,
    MATCHES,
    NONEMPTY,
    Ask,
    Command,
    Criterion,
    Function,
    Functions,
    Role,
    add,
    brief,
    check,
    done,
    fill,
    judge,
    keep,
    lessons,
    recall,
    remove,
)
from vesta.procedure import Procedure, Procedures, Step
from vesta.procedure import keep as keep_procedures


def _summarise() -> Function:
    return Function(
        name="summarise-failures",
        about="say why the tests failed",
        inputs=["log"],
        ask=Ask(
            model="sonnet",
            system="You read pytest output and name the cause in one paragraph.",
            prompt="The output:\n{log}\n\nName the cause. End with `cause:` and one line.",
        ),
        criteria=[
            Criterion(says="names a cause", check=MATCHES, pattern=r"^cause:\s*\S"),
            Criterion(says="is not empty", check=NONEMPTY),
            Criterion(says="is actually right", check=ASSERTED),
        ],
    )


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("VESTA_HOME", str(tmp_path / "home"))
    return tmp_path


# ── Refusals at construction ────────────────────────────────────────────────


def test_a_matches_criterion_without_a_pattern_is_refused():
    with pytest.raises(ValueError):
        Criterion(says="looks right", check=MATCHES)


def test_a_contains_criterion_without_a_pattern_is_refused():
    with pytest.raises(ValueError):
        Criterion(says="mentions the file", check=CONTAINS)


def test_an_invalid_pattern_is_refused():
    with pytest.raises(ValueError):
        Criterion(says="x", check=MATCHES, pattern="(")


def test_an_unknown_check_is_refused():
    with pytest.raises(ValueError):
        Criterion(says="x", check="vibes")


def test_an_asserted_criterion_needs_no_pattern():
    assert Criterion(says="is right", check=ASSERTED).pattern == ""


def test_an_ask_on_an_unknown_model_is_refused():
    with pytest.raises(ValueError):
        Ask(model="gpt-9", system="s", prompt="p")


def test_an_ask_with_no_system_prompt_is_refused():
    with pytest.raises(ValueError):
        Ask(model="sonnet", system="  ", prompt="p")


def test_a_function_is_exactly_one_kind():
    with pytest.raises(ValueError):
        Function(name="both", ask=Ask(system="s", prompt="p"), command=Command(run="make"))
    with pytest.raises(ValueError):
        Function(name="neither")


def test_a_template_may_not_use_an_undeclared_input():
    with pytest.raises(ValueError) as caught:
        Function(name="f", ask=Ask(system="s", prompt="read {path}"))
    assert "{path}" in str(caught.value)


def test_a_function_name_is_typeable():
    with pytest.raises(ValueError):
        Function(name="Summarise Failures", command=Command(run="make"))


# ── Keeping ─────────────────────────────────────────────────────────────────


def test_functions_round_trip(home):
    add(home, _summarise())
    add(home, Function(name="build", command=Command(run="make build")))
    kept = recall(home)
    assert {f.name for f in kept.functions} == {"summarise-failures", "build"}
    assert kept.get("summarise-failures").kind == "ask"
    assert kept.get("build").kind == "command"


def test_adding_the_same_name_replaces(home):
    add(home, Function(name="build", command=Command(run="make build")))
    add(home, Function(name="build", command=Command(run="make all")))
    kept = recall(home)
    assert len(kept.functions) == 1
    assert kept.get("build").command.run == "make all"


def test_removing_keeps_the_runs(home):
    add(home, Function(name="build", command=Command(run="echo ok")))
    done(home, "build", {}, "ok")
    assert remove(home, "build")
    assert not remove(home, "build")
    kept = recall(home)
    assert kept.get("build") is None
    assert len(kept.runs_of("build")) == 1


def test_a_role_must_name_a_recorded_step(home):
    with pytest.raises(ValueError):
        add(home, Function(
            name="build", command=Command(run="make"),
            role=Role(procedure="release", step="build"),
        ))

    keep_procedures(Procedures(procedures=[
        Procedure(id="release", label="release", steps=[Step(id="build", label="build it")]),
    ]), home)

    with pytest.raises(ValueError):
        add(home, Function(
            name="build", command=Command(run="make"),
            role=Role(procedure="release", step="ship"),
        ))

    add(home, Function(
        name="build", command=Command(run="make"),
        role=Role(procedure="release", step="build"),
    ))
    assert [f.name for f in recall(home).performing("release", "build")] == ["build"]


# ── Performing ──────────────────────────────────────────────────────────────


def test_fill_refuses_a_missing_input():
    with pytest.raises(ValueError) as caught:
        fill(_summarise(), {})
    assert "log" in str(caught.value)


def test_a_brief_carries_model_system_prompt_and_criteria():
    text = brief(_summarise(), {"log": "FAILED test_x - AssertionError"})
    assert "on sonnet" in text
    assert "You read pytest output" in text
    assert "FAILED test_x - AssertionError" in text
    assert "names a cause [matches]" in text
    assert "asserted — nothing here can check it" in text
    assert "vesta function done summarise-failures" in text


def test_a_command_brief_is_the_line_to_run():
    text = brief(Function(name="t", inputs=["k"], command=Command(run="pytest -k {k}")), {"k": "seams"})
    assert "pytest -k seams" in text


def test_check_tells_what_it_can_and_says_what_it_cannot(home):
    verdicts = check(_summarise(), "Something broke.\ncause: the fixture moved", home)
    by_check = {v.check: v for v in verdicts}
    assert by_check[MATCHES].held is True
    assert by_check[NONEMPTY].held is True
    assert by_check[ASSERTED].held is None
    assert "?" in by_check[ASSERTED].describe()


def test_a_run_that_misses_a_pattern_is_not_met(home):
    add(home, _summarise())
    run = done(home, "summarise-failures", {"log": "x"}, "I am not sure.")
    assert run.met is False
    assert run.asserted == 1
    assert "nothing matched" in [v.note for v in run.verdicts if v.check == MATCHES][0]


def test_a_run_that_meets_everything_checkable_is_met(home):
    add(home, _summarise())
    run = done(home, "summarise-failures", {"log": "x"}, "cause: the fixture moved")
    assert run.met is True
    assert run.output_chars == len("cause: the fixture moved")
    assert recall(home).runs_of("summarise-failures")[-1].output_digest == run.output_digest


def test_done_refuses_a_missing_input_before_keeping_anything(home):
    add(home, _summarise())
    with pytest.raises(ValueError):
        done(home, "summarise-failures", {}, "cause: x")
    assert recall(home).runs == []


def test_done_refuses_an_unknown_function(home):
    with pytest.raises(ValueError):
        done(home, "nothing", {}, "x")


def test_runs_are_bounded(home):
    kept = Functions(functions=[Function(name="b", command=Command(run="true"))])
    keep(kept, home)
    for n in range(230):
        done(home, "b", {}, str(n))
    assert len(recall(home).runs) == 200


# ── Feedback, and what the next brief learns ────────────────────────────────


def test_judging_needs_a_run(home):
    add(home, _summarise())
    with pytest.raises(ValueError):
        judge(home, "summarise-failures", good=False, why="wrong")


def test_a_bad_judgement_must_say_why(home):
    add(home, _summarise())
    done(home, "summarise-failures", {"log": "x"}, "cause: y")
    with pytest.raises(ValueError):
        judge(home, "summarise-failures", good=False)


def test_the_next_brief_carries_recent_bad_judgements(home):
    add(home, _summarise())
    for why in ("blamed the wrong test", "ignored the traceback", "too long", "fourth"):
        done(home, "summarise-failures", {"log": "x"}, "cause: y")
        judge(home, "summarise-failures", good=False, why=why)
    done(home, "summarise-failures", {"log": "x"}, "cause: z")
    judge(home, "summarise-failures", good=True)

    kept = recall(home)
    learned = lessons(kept, "summarise-failures")
    assert learned == ["fourth", "too long", "ignored the traceback"]

    text = brief(kept.get("summarise-failures"), {"log": "new"}, kept)
    assert "judged bad because" in text
    assert "ignored the traceback" in text
    assert "blamed the wrong test" not in text


def test_a_good_judgement_teaches_nothing(home):
    add(home, _summarise())
    done(home, "summarise-failures", {"log": "x"}, "cause: y")
    judge(home, "summarise-failures", good=True, why="fine")
    assert lessons(recall(home), "summarise-failures") == []


# ── The command line ────────────────────────────────────────────────────────


def _run(capsys, *argv) -> str:
    assert cli.main(list(argv)) == 0
    return capsys.readouterr().out


def test_the_cli_round_trips_a_function(home, capsys, tmp_path):
    root = str(home)
    payload = json.dumps(_summarise().model_dump())
    out = _run(capsys, "function", root, "add", "--json", payload)
    assert "kept: summarise-failures" in out

    out = _run(capsys, "function", root, "list")
    assert "1 function(s)" in out

    out = _run(capsys, "function", root, "brief", "summarise-failures", "--input", "log=FAILED x")
    assert "FAILED x" in out and "on sonnet" in out

    produced = tmp_path / "out.md"
    produced.write_text("cause: the fixture moved", encoding="utf-8")
    out = _run(capsys, "function", root, "done", "summarise-failures",
               "--input", "log=FAILED x", "--output-file", str(produced))
    assert "2/2 checked criteria held, 1 asserted" in out

    out = _run(capsys, "function", root, "feedback", "summarise-failures", "--bad", "--why", "blamed pytest")
    assert "judged bad: blamed pytest" in out

    out = _run(capsys, "function", root, "show", "summarise-failures")
    assert "runs (1)" in out and "blamed pytest" in out

    out = _run(capsys, "function", root, "remove", "summarise-failures")
    assert "forgot" in out


def test_the_cli_refuses_with_a_sentence_not_a_stack(home, capsys):
    root = str(home)
    out = _run(capsys, "function", root, "add", "--json", json.dumps({
        "name": "x", "ask": {"system": "s", "prompt": "p"},
        "criteria": [{"says": "ok", "check": "matches"}],
    }))
    assert "not a valid function" in out and "Traceback" not in out

    out = _run(capsys, "function", root, "brief", "nothing")
    assert "no function 'nothing'" in out

    out = _run(capsys, "function", root, "add", "--json", json.dumps({
        "name": "x", "command": {"run": "make"}, "role": {"procedure": "p", "step": "s"},
    }))
    assert "not kept" in out


# ── The sidecar's read side ─────────────────────────────────────────────────


def test_the_sidecar_lists_and_shows_without_a_graph(home):
    from vesta.sidecar import _functions_query

    assert "no functions recorded" in _functions_query(home)
    add(home, _summarise())
    done(home, "summarise-failures", {"log": "x"}, "cause: y")
    judge(home, "summarise-failures", good=False, why="wrong cause")

    listed = _functions_query(home)
    assert "summarise-failures (log) [ask on sonnet]" in listed

    shown = _functions_query(home, "summarise-failures")
    assert "You read pytest output" in shown
    assert "the next brief will carry" in shown and "wrong cause" in shown
    assert "no function 'other'" in _functions_query(home, "other")
