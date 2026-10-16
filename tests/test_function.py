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


# ── Offered when the prompt is about it ─────────────────────────────────────


def _kept_release() -> Functions:
    return Functions(functions=[
        Function(name="release-note", about="draft the changelog entry for a version",
                 inputs=["version", "log"], ask=Ask(system="s", prompt="{version} {log}")),
        Function(name="build", about="compile the wheel", command=Command(run="make")),
    ])


def test_a_function_is_offered_when_two_words_are_shared():
    from vesta.function import for_prompt

    found = for_prompt(_kept_release(), "please draft the changelog for this release")
    assert [f.name for f in found] == ["release-note"]


def test_a_function_is_offered_when_its_name_is_typed():
    from vesta.function import for_prompt

    assert [f.name for f in for_prompt(_kept_release(), "run release-note for 0.7.1")] == ["release-note"]
    assert [f.name for f in for_prompt(_kept_release(), "run the release note")] == ["release-note"]


def test_one_shared_word_is_not_enough():
    """'release' alone is in half the prompts a maintainer types."""
    from vesta.function import for_prompt

    assert for_prompt(_kept_release(), "tag the release") == []
    assert for_prompt(_kept_release(), "fix the parser") == []


def test_the_hook_offers_a_recorded_function_once(home, monkeypatch):
    from vesta.inject import _a_function_for_this

    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "one-session")
    add(home, _kept_release().functions[0])

    said = _a_function_for_this("draft the changelog entry for 0.7.1", str(home))
    assert "release-note" in said
    assert "function brief release-note --input version=… --input log=…" in said
    assert "asserted, not met" in said
    assert _a_function_for_this("draft the changelog entry for 0.7.1", str(home)) == ""


def test_the_hook_is_silent_when_nothing_matches(home):
    from vesta.inject import _a_function_for_this

    add(home, _kept_release().functions[0])
    assert _a_function_for_this("fix the parser", str(home)) == ""
    assert _a_function_for_this("anything", str(home / "nowhere")) == ""


# ── A command that accepts the output ───────────────────────────────────────


def test_an_exits_criterion_without_a_command_is_refused():
    from vesta.function import EXITS

    with pytest.raises(ValueError):
        Criterion(says="parses", check=EXITS)


def test_an_exits_criterion_holds_on_zero_and_says_why_otherwise(home):
    from vesta.function import EXITS

    parses = Function(name="emit-json", ask=Ask(system="s", prompt="p"), criteria=[
        Criterion(says="parses as JSON", check=EXITS, command="python3 -c 'import json,sys; json.load(sys.stdin)'"),
    ])
    held = check(parses, '{"ok": true}', home)[0]
    assert held.held is True and held.note == ""

    failed = check(parses, "not json", home)[0]
    assert failed.held is False
    assert failed.note.startswith("exited 1")


def test_a_command_that_cannot_run_is_unknown_not_failed(home, monkeypatch):
    from vesta.function import EXITS, _exits
    import subprocess

    def boom(*a, **k):
        raise OSError("no shell")

    monkeypatch.setattr(subprocess, "run", boom)
    held, note = _exits("true", "x", home)
    assert held is None and "could not check" in note


def test_an_exits_criterion_runs_in_the_project(home):
    from vesta.function import EXITS

    (home / "marker").write_text("here", encoding="utf-8")
    fn = Function(name="f", command=Command(run="true"), criteria=[
        Criterion(says="sees the project", check=EXITS, command="test -f marker"),
    ])
    assert check(fn, "", home)[0].held is True
    assert "exits: test -f marker" in fn.criteria[0].describe()


# ── A procedure as the briefs that perform it ───────────────────────────────


def _release_procedure() -> Procedure:
    from vesta.procedure import BRANCHES, CONTINUES, Then

    return Procedure(id="release", label="cut a release", steps=[
        Step(id="note", label="write the release note"),
        Step(id="tag", label="tag it"),
        Step(id="fix", label="fix what broke"),
        Step(id="orphan", label="a step nothing reaches"),
    ], thens=[
        Then(source="note", target="tag", outcome=CONTINUES),
        Then(source="note", target="fix", outcome=BRANCHES, when="the suite fails"),
    ])


def test_steps_come_in_the_order_a_reader_performs_them():
    from vesta.function import in_order

    assert [s.id for s in in_order(_release_procedure())] == ["note", "tag", "fix", "orphan"]


def test_a_pipeline_shows_each_step_with_what_performs_it(home):
    from vesta.function import pipeline

    keep_procedures(Procedures(procedures=[_release_procedure()]), home)
    add(home, Function(
        name="release-note", inputs=["version"], ask=Ask(system="s", prompt="note for {version}"),
        criteria=[Criterion(says="has a heading", check=MATCHES, pattern="^## ")],
        role=Role(procedure="release", step="note"),
    ))
    done(home, "release-note", {"version": "1"}, "## 1")
    judge(home, "release-note", good=False, why="too long")

    text = pipeline(_release_procedure(), recall(home))
    assert "1. write the release note [note]" in text
    assert "ask release-note on sonnet — takes version" in text
    assert "has a heading [matches]" in text
    assert "last judged bad: too long" in text
    assert "vesta function brief release-note --input version=…" in text
    assert "→ branches when the suite fails → fix" in text
    assert "2. tag it [tag]" in text and "performed by: nothing recorded" in text
    assert "3 step(s) nothing recorded performs" in text


def test_the_cli_and_sidecar_render_a_pipeline(home, capsys):
    from vesta.sidecar import _functions_query

    keep_procedures(Procedures(procedures=[_release_procedure()]), home)
    out = _run(capsys, "function", str(home), "pipeline", "release")
    assert "pipeline: cut a release (release) — 4 step(s)" in out

    out = _run(capsys, "function", str(home), "pipeline", "nothing")
    assert "no procedure 'nothing'" in out

    out = _run(capsys, "function", str(home), "pipeline")
    assert "needs a procedure name" in out

    assert "pipeline: cut a release" in _functions_query(home, procedure="release")
    assert "no procedure 'x'" in _functions_query(home, procedure="x")


# ── Feedback that names the criterion it got past ───────────────────────────


def test_a_missed_criterion_must_be_one_the_function_states(home):
    add(home, _summarise())
    done(home, "summarise-failures", {"log": "x"}, "cause: y")
    with pytest.raises(ValueError) as caught:
        judge(home, "summarise-failures", good=False, why="w", missed="is concise")
    assert "not a criterion" in str(caught.value)
    with pytest.raises(ValueError):
        judge(home, "summarise-failures", good=True, missed="is actually right")


def test_leaks_count_which_criteria_bad_runs_got_past(home):
    add(home, _summarise())
    for _ in range(3):
        done(home, "summarise-failures", {"log": "x"}, "cause: y")
        judge(home, "summarise-failures", good=False, why="wrong cause", missed="is actually right")
    done(home, "summarise-failures", {"log": "x"}, "cause: y")
    judge(home, "summarise-failures", good=False, why="blank-ish", missed="names a cause")
    done(home, "summarise-failures", {"log": "x"}, "cause: y")
    judge(home, "summarise-failures", good=False, why="no criterion named")

    kept = recall(home)
    leaks = kept.leaks("summarise-failures")
    assert [(l.says, l.times) for l in leaks] == [("is actually right", 3), ("names a cause", 1)]
    assert "worth a real check" in leaks[0].describe()
    assert "the check is not catching it" in leaks[1].describe()
    assert kept.leaks("nothing") == []


def test_the_lesson_names_the_criterion(home):
    add(home, _summarise())
    done(home, "summarise-failures", {"log": "x"}, "cause: y")
    judge(home, "summarise-failures", good=False, why="too vague", missed="is actually right")
    assert lessons(recall(home), "summarise-failures") == ["too vague (criterion: is actually right)"]


def test_the_cli_takes_and_shows_the_criterion(home, capsys):
    root = str(home)
    add(home, _summarise())
    done(home, "summarise-failures", {"log": "x"}, "cause: y")
    out = _run(capsys, "function", root, "feedback", "summarise-failures",
               "--bad", "--why", "wrong", "--criterion", "is actually right")
    assert "missed by: is actually right" in out and "let 1 bad run(s) through" in out

    out = _run(capsys, "function", root, "feedback", "summarise-failures",
               "--bad", "--why", "wrong", "--criterion", "is concise")
    assert "not a criterion" in out

    out = _run(capsys, "function", root, "show", "summarise-failures")
    assert "criteria bad runs got past:" in out

    from vesta.sidecar import _functions_query
    assert "criteria bad runs got past" in _functions_query(home, "summarise-failures")


# ── A run leaves a witness ──────────────────────────────────────────────────


def test_a_run_is_witnessed_where_every_other_invocation_is(home):
    from vesta.bundle import SANE, UNSOUND, recent

    add(home, _summarise())
    run = done(home, "summarise-failures", {"log": "FAILED x"}, "cause: the fixture moved")
    assert run.witness_at and run.witness_at.endswith(".json")

    held = recent(home, limit=1)[0]
    assert held.intent.startswith("function summarise-failures (log='FAILED x')")
    assert held.verdict == SANE
    assert [f.check for f in held.findings] == ["names a cause", "is not empty"]
    assert held.computed == 2 and held.read == 1
    assert held.standard == "function summarise-failures"
    assert len(held.standard_digest) == 16
    assert held.stood_by == ["names a cause", "is not empty", "is actually right"]
    assert held.narrowed == []
    assert "digest " + run.output_digest in held.output

    done(home, "summarise-failures", {"log": "x"}, "no cause here")
    assert recent(home, limit=1)[0].verdict == UNSOUND


def test_a_run_with_nothing_checkable_is_unknown_not_sound(home):
    from vesta.bundle import UNKNOWN, recent

    add(home, Function(name="opine", ask=Ask(system="s", prompt="p"),
                       criteria=[Criterion(says="is wise", check=ASSERTED)]))
    done(home, "opine", {}, "yes")
    held = recent(home, limit=1)[0]
    assert held.verdict == UNKNOWN and held.read == 1 and held.findings == []


def test_the_standard_digest_moves_when_the_function_does(home):
    from vesta.function import _digest_of

    before = _digest_of(_summarise())
    changed = _summarise().model_copy(update={"about": "something else"})
    assert _digest_of(changed) != before


def test_why_reads_a_function_run(home):
    from vesta.sidecar import _replayed

    add(home, _summarise())
    done(home, "summarise-failures", {"log": "x"}, "cause: y")
    said = _replayed(home, 1)
    assert "function summarise-failures" in said
    assert "sound — 2 check(s) held" in said
    assert "judged against function summarise-failures" in said


def test_a_witness_that_cannot_be_written_does_not_lose_the_run(home, monkeypatch):
    import vesta.bundle as bundle

    def refuse(*a, **k):
        raise OSError("read-only")

    monkeypatch.setattr(bundle, "keep", refuse)
    add(home, _summarise())
    run = done(home, "summarise-failures", {"log": "x"}, "cause: y")
    assert run.witness_at == ""
    assert len(recall(home).runs_of("summarise-failures")) == 1
