"""Running until the work is done, and knowing when that is.

The leading loop plugin instructs its own model *"do not output false promises
to escape the loop"* — an instruction that would be unnecessary if the model
were a reliable judge of its own work. Every condition here is a count or a
process exit code instead, so most of these tests are about the loop refusing
to be talked into finishing.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from vesta import driving
from vesta.contract import Behaviour, Contract, keep, met, sign

# A project as one really is: something that ships calls the definition, not
# only its test. A fixture whose only caller is a test is itself the defect
# `only its tests call this` reports — the new detector found this fixture
# before anybody else did.
WORKS = (
    '"""Filing tasks."""\n'
    "import sys\n\n\n"
    'def file_task(store, title):\n    """Put one in."""\n'
    "    store.append(title)\n    return store\n\n\n"
    'def main(argv):\n    """Run it."""\n    return file_task([], " ".join(argv))\n\n\n'
    'if __name__ == "__main__":\n    main(sys.argv[1:])\n'
)
CHECKS = 'from todo import file_task\n\n\ndef test_file():\n    assert file_task([], "x") == ["x"]\n'


@pytest.fixture
def project(tmp_path):
    """A project that is genuinely finished."""
    (tmp_path / "todo.py").write_text(WORKS, encoding="utf-8")
    (tmp_path / "test_todo.py").write_text(CHECKS, encoding="utf-8")
    keep(
        Contract(goal="todo", behaviours=[Behaviour(does="a user can file a task")]),
        tmp_path,
    )
    sign(tmp_path)
    met(
        tmp_path,
        "a user can file a task",
        nodes=["todo.py:file_task"],
        tests=["test_todo.py"],
    )
    return tmp_path


# ── Off unless somebody turned it on ────────────────────────────────────────


def test_it_is_off_by_default(tmp_path):
    """Writing code unasked is welcome only from somebody who asked."""
    assert not driving.state(tmp_path).on


def test_turning_it_on_is_per_project(tmp_path):
    other = Path(tempfile.mkdtemp())
    driving.start(tmp_path)
    assert driving.state(tmp_path).on
    assert not driving.state(other).on


def test_it_survives_being_read_again(tmp_path):
    """A mode that resets is not a mode."""
    driving.start(tmp_path)
    assert driving.state(tmp_path).on
    driving.stop(tmp_path, "asked to stop")
    assert not driving.state(tmp_path).on
    assert "asked to stop" in driving.state(tmp_path).describe()


# ── What blocks completion ──────────────────────────────────────────────────


def test_a_finished_project_is_done(project):
    verdict = driving.look(project)
    assert verdict.done, verdict.outstanding
    assert not verdict.keep_going


def test_nothing_agreed_means_nothing_to_finish(tmp_path):
    verdict = driving.look(tmp_path)
    assert not verdict.done
    assert "no signed contract" in verdict.outstanding


def test_an_unsigned_contract_is_not_a_target(tmp_path):
    keep(Contract(goal="x", behaviours=[Behaviour(does="a user can y")]), tmp_path)
    verdict = driving.look(tmp_path)
    assert not verdict.done
    assert "no signed contract" in verdict.outstanding


def test_an_unmet_behaviour_blocks_it(project):
    keep(
        Contract(
            goal="todo",
            behaviours=[
                Behaviour(does="a user can file a task"),
                Behaviour(does="a user can tag a task"),
            ],
        ),
        project,
    )
    sign(project)
    met(project, "a user can file a task", nodes=["x"], tests=["y"])
    verdict = driving.look(project)
    assert not verdict.done
    assert any("a user can tag a task" in o for o in verdict.outstanding)


def test_a_failing_test_blocks_it(project):
    (project / "test_todo.py").write_text(
        'from todo import file_task\n\n\ndef test_file():\n    assert file_task([], "x") == ["WRONG"]\n',
        encoding="utf-8",
    )
    verdict = driving.look(project)
    assert not verdict.done
    assert driving.FAILED in verdict.outstanding


def test_a_defect_blocks_it(project):
    (project / "todo.py").write_text(
        WORKS + '\n\ndef orphan():\n    """Nothing refers to this."""\n    return 1\n',
        encoding="utf-8",
    )
    verdict = driving.look(project)
    assert not verdict.done
    assert any("defect" in o for o in verdict.outstanding)


def test_a_project_with_no_tests_is_not_finished(tmp_path):
    """Absence of failure is not success."""
    (tmp_path / "todo.py").write_text(WORKS, encoding="utf-8")
    keep(Contract(goal="x", behaviours=[Behaviour(does="a user can y")]), tmp_path)
    sign(tmp_path)
    met(tmp_path, "a user can y", nodes=["a"], tests=["b"])
    verdict = driving.look(tmp_path)
    assert not verdict.done
    assert driving.NOTHING_TO_RUN in verdict.outstanding


def test_a_runner_that_cannot_start_is_not_a_pass(tmp_path, monkeypatch):
    """The bug this covers: a FileNotFoundError from a missing `python` was
    swallowed into "no tests to run" — a runner failure read as an empty
    suite, which lets a loop finish over a project nobody verified."""
    (tmp_path / "test_x.py").write_text("def test_x():\n    assert True\n", encoding="utf-8")

    def _never(*a, **k):
        raise OSError("no interpreter")

    monkeypatch.setattr("subprocess.run", _never)
    assert driving._tests_pass(tmp_path) == driving.COULD_NOT_RUN


# ── Knowing it is stuck ─────────────────────────────────────────────────────


def test_a_loop_that_moves_nothing_stops_itself(tmp_path):
    """An agent can iterate forever making changes that move nothing, and no
    stopping condition based on the model's own opinion can see it."""
    (tmp_path / "app.py").write_text(
        '"""Doing."""\n\n\ndef work():\n    """It."""\n    return 1\n', encoding="utf-8"
    )
    keep(Contract(goal="x", behaviours=[Behaviour(does="a user can do it")]), tmp_path)
    sign(tmp_path)
    driving.start(tmp_path)

    for _ in range(driving.STUCK_AFTER + 1):
        verdict = driving.iterate(tmp_path)

    assert not verdict.keep_going
    assert "nothing has changed" in verdict.why
    assert not driving.state(tmp_path).on


def test_it_is_not_stuck_before_it_has_had_a_chance(tmp_path):
    """One iteration that moves nothing is ordinary — an agent reading rather
    than writing moves nothing."""
    (tmp_path / "app.py").write_text('"""D."""\n\n\ndef w():\n    """I."""\n    return 1\n', encoding="utf-8")
    keep(Contract(goal="x", behaviours=[Behaviour(does="a user can do it")]), tmp_path)
    sign(tmp_path)
    driving.start(tmp_path)

    assert driving.iterate(tmp_path).keep_going
    assert not driving.state(tmp_path).stuck


def test_finishing_turns_driving_off(project):
    driving.start(project)
    verdict = driving.iterate(project)
    assert verdict.done
    assert not driving.state(project).on
    assert driving.state(project).stopped == "done"


def test_it_stops_after_enough_iterations_regardless(tmp_path, monkeypatch):
    """A backstop, not a completion condition: a loop that has run this long
    has a problem no further iteration will solve."""
    monkeypatch.setattr(driving, "AT_MOST", 2)
    (tmp_path / "app.py").write_text('"""D."""\n\n\ndef w():\n    """I."""\n    return 1\n', encoding="utf-8")
    keep(Contract(goal="x", behaviours=[Behaviour(does="a user can do it")]), tmp_path)
    sign(tmp_path)
    driving.start(tmp_path)

    driving.iterate(tmp_path)
    verdict = driving.iterate(tmp_path)
    assert not verdict.keep_going
    assert "without finishing" in verdict.why


def test_readings_do_not_grow_without_bound(project):
    driving.start(project)
    for _ in range(10):
        driving.iterate(project)
    assert len(driving.state(project).readings) <= driving.STUCK_AFTER + 2


# ── The Stop hook that makes it a loop ──────────────────────────────────────


def _hook(payload: dict) -> dict:
    """Run the hook as the framework runs it, and read what it answered."""
    import json
    import os
    import subprocess
    import sys

    from vesta.home import home

    done = subprocess.run(
        [sys.executable, "-m", "vesta.keepgoing"],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=900,
        env={**os.environ, "VESTA_HOME": str(home())},
    )
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout) if done.stdout.strip() else {}


@pytest.fixture
def unfinished(tmp_path):
    (tmp_path / "app.py").write_text(
        '"""Doing."""\n\n\ndef work():\n    """It."""\n    return 1\n', encoding="utf-8"
    )
    keep(Contract(goal="x", behaviours=[Behaviour(does="a user can file a task")]), tmp_path)
    sign(tmp_path)
    return tmp_path


def test_it_says_nothing_when_driving_is_off(unfinished):
    """The most intrusive thing this plugin can do. It happens only where
    somebody asked for it."""
    assert _hook({"cwd": str(unfinished)}) == {}


def test_it_blocks_while_work_remains(unfinished):
    driving.start(unfinished)
    answered = _hook({"cwd": str(unfinished)})
    assert answered.get("decision") == "block"
    assert "not built: a user can file a task" in answered["reason"]


def test_what_it_says_is_counted_rather_than_judged(unfinished):
    driving.start(unfinished)
    answered = _hook({"cwd": str(unfinished)})
    assert "counted, not judged" in answered["reason"]
    assert "checked, not taken on trust" in answered["reason"]


def test_it_lets_the_session_end_when_the_work_is_done(project):
    driving.start(project)
    answered = _hook({"cwd": str(project)})
    assert "decision" not in answered
    assert "done" in answered.get("systemMessage", "")


def test_another_sessions_loop_does_not_trap_this_one(unfinished):
    """The state is per project and this hook fires in every session open on
    it. The reference implementation had to fix exactly this."""
    driving.start(unfinished, session="the-one-that-asked")

    # Another session is not held: it may say why it is not driving, but it
    # must never be blocked from ending.
    somebody_else = _hook({"cwd": str(unfinished), "session_id": "somebody-else"})
    assert "decision" not in somebody_else

    assert _hook({"cwd": str(unfinished), "session_id": "the-one-that-asked"}).get(
        "decision"
    ) == "block"


def test_it_stops_blocking_once_stuck(unfinished):
    """A loop that cannot tell it is stuck spends somebody's money proving it."""
    driving.start(unfinished)
    for _ in range(driving.STUCK_AFTER + 2):
        answered = _hook({"cwd": str(unfinished)})
    assert "decision" not in answered
    assert "nothing has changed" in answered.get("systemMessage", "")


def test_it_never_traps_a_session_on_bad_input(tmp_path):
    """A Stop hook that raises is a session that cannot end, which is worse
    than any amount of unfinished work."""
    import json
    import os
    import subprocess
    import sys

    for payload in ("", "not json", "{}", '{"cwd": null}', '{"cwd": 12}'):
        done = subprocess.run(
            [sys.executable, "-m", "vesta.keepgoing"],
            input=payload,
            capture_output=True,
            text=True,
            timeout=300,
            env={**os.environ, "VESTA_HOME": str(tmp_path)},
        )
        assert done.returncode == 0, done.stderr
        assert "Traceback" not in done.stderr


def test_the_hook_script_never_leaks_an_error(tmp_path):
    import subprocess
    from pathlib import Path as _Path

    here = _Path(__file__).resolve().parent.parent
    done = subprocess.run(
        [str(here / "hooks" / "keep-going.sh")],
        input='{"cwd":"/tmp"}',
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin", "VESTA_NO_INSTALL": "1", "HOME": str(tmp_path)},
        timeout=120,
    )
    assert done.returncode == 0
    assert done.stderr.strip() == ""


def test_the_reason_it_stopped_is_not_overwritten_by_saying_it(tmp_path):
    """Whether a reason has been announced is its own fact.

    It was once a sentinel written into the reason itself, so after the hook
    said it once the state read "not being driven — said" — a marker leaking
    into what the user is shown, and the real reason lost.
    """
    driving.start(tmp_path)
    driving.stop(tmp_path, "done")

    here = driving.state(tmp_path)
    assert here.stopped == "done"
    assert not here.told

    here.told = True
    driving._keep(here, tmp_path)

    after = driving.state(tmp_path)
    assert after.stopped == "done", "the reason was overwritten"
    assert "said" not in after.describe()
    assert "done" in after.describe()


def test_restarting_lets_the_next_reason_be_said(tmp_path):
    driving.start(tmp_path)
    driving.stop(tmp_path, "done")
    here = driving.state(tmp_path)
    here.told = True
    driving._keep(here, tmp_path)

    driving.start(tmp_path)
    assert not driving.state(tmp_path).told
    assert driving.state(tmp_path).stopped == ""


# ── Automation lasts exactly as long as the consent that granted it ─────────
#
# A user must not be stuck in automated mode. It is entered by a decision made
# once, for one piece of work, and it ends when that work ends — not when
# somebody remembers to turn it off.


def test_a_project_opened_again_is_not_being_driven(tmp_path):
    """Loading a prior project must never resume automation. Nobody agreed to
    that: they agreed to build one thing, once."""
    driving.start(tmp_path, session="the-one-that-agreed")
    assert driving.state(tmp_path, "the-one-that-agreed").on

    later = driving.state(tmp_path, "a-session-a-week-later")
    assert not later.on
    assert "session that agreed" in later.describe()


def test_finishing_ends_automation(project):
    driving.start(project, session="s1")
    verdict = driving.iterate(project)
    assert verdict.done
    assert not driving.state(project, "s1").on
    assert driving.state(project, "s1").stopped == "done"


def test_stopping_by_hand_ends_automation(tmp_path):
    driving.start(tmp_path, session="s1")
    driving.stop(tmp_path, "asked to stop")
    assert not driving.state(tmp_path, "s1").on


def test_being_stuck_ends_automation(tmp_path):
    """Escaping is not only something a user does. A loop that cannot move
    releases the session rather than holding it."""
    (tmp_path / "app.py").write_text(
        '"""D."""\n\n\ndef w():\n    """I."""\n    return 1\n', encoding="utf-8"
    )
    keep(Contract(goal="x", behaviours=[Behaviour(does="a user can do it")]), tmp_path)
    sign(tmp_path)
    driving.start(tmp_path, session="s1")

    for _ in range(driving.STUCK_AFTER + 1):
        driving.iterate(tmp_path)

    assert not driving.state(tmp_path, "s1").on


def test_entering_again_takes_a_fresh_decision(tmp_path):
    """Having finished once does not leave the door open."""
    driving.start(tmp_path, session="s1")
    driving.stop(tmp_path, "done")
    assert not driving.state(tmp_path, "s1").on

    driving.start(tmp_path, session="s1")
    assert driving.state(tmp_path, "s1").on


def test_what_happened_survives_even_though_the_permission_does_not(tmp_path):
    """The record is worth having afterwards; the permission is not."""
    driving.start(tmp_path, session="s1")
    driving.iterate(tmp_path)
    driving.stop(tmp_path, "done")

    later = driving.state(tmp_path, "s2")
    assert not later.on
    assert later.iterations >= 1


# ── Automation lasts exactly as long as the consent that granted it ─────────


def test_a_project_opened_again_is_not_being_driven(tmp_path):
    """Loading a prior project must never resume automation. Nobody agreed to
    that: they agreed to build one thing, once."""
    driving.start(tmp_path, session="the-one-that-agreed")
    assert driving.state(tmp_path, "the-one-that-agreed").on

    later = driving.state(tmp_path, "a-session-a-week-later")
    assert not later.on
    assert "session that agreed" in later.describe()


def test_finishing_ends_automation(project):
    driving.start(project, session="s1")
    assert driving.iterate(project).done
    assert not driving.state(project, "s1").on


def test_stopping_by_hand_ends_automation(tmp_path):
    driving.start(tmp_path, session="s1")
    driving.stop(tmp_path, "asked to stop")
    assert not driving.state(tmp_path, "s1").on


def test_being_stuck_ends_automation(tmp_path):
    """Escaping is not only something a user does. A loop that cannot move
    releases the session rather than holding it."""
    (tmp_path / "app.py").write_text(
        '"""D."""\n\n\ndef w():\n    """I."""\n    return 1\n', encoding="utf-8"
    )
    keep(Contract(goal="x", behaviours=[Behaviour(does="a user can do it")]), tmp_path)
    sign(tmp_path)
    driving.start(tmp_path, session="s1")
    for _ in range(driving.STUCK_AFTER + 1):
        driving.iterate(tmp_path)
    assert not driving.state(tmp_path, "s1").on


def test_entering_again_takes_a_fresh_decision(tmp_path):
    driving.start(tmp_path, session="s1")
    driving.stop(tmp_path, "done")
    assert not driving.state(tmp_path, "s1").on
    driving.start(tmp_path, session="s1")
    assert driving.state(tmp_path, "s1").on


def test_what_happened_survives_though_the_permission_does_not(tmp_path):
    driving.start(tmp_path, session="s1")
    driving.iterate(tmp_path)
    driving.stop(tmp_path, "done")
    later = driving.state(tmp_path, "s2")
    assert not later.on
    assert later.iterations >= 1


# ── Asked once ─────────────────────────────────────────────────────────────


def test_choosing_interactive_is_not_asked_again(tmp_path):
    """A question repeated after an answer is not a question, it is nagging.
    The answer does not change because they asked for a second module."""
    from vesta.inject import _something_to_build

    brief = (
        "Build an expense tracker. I want to record an expense with an amount "
        "and a category, see what I spent this month, and export to CSV."
    )
    assert _something_to_build(brief, str(tmp_path))

    driving.declined(tmp_path)
    assert not _something_to_build(brief, str(tmp_path))


def test_declining_does_not_stop_them_asking_later(tmp_path):
    driving.declined(tmp_path)
    driving.start(tmp_path, session="s1")
    assert driving.state(tmp_path, "s1").on


def test_the_question_only_comes_for_a_whole_implementation(tmp_path):
    """Automation agrees a list of behaviours and runs until each is built and
    tested. That is worth doing for something with several parts and absurd
    for one function."""
    from vesta.inject import _something_to_build

    for one_piece in (
        "write a function that parses a date string",
        "add a helper to format currency",
        "implement the retry logic",
        "build me a script to rename files",
    ):
        assert not _something_to_build(one_piece, str(tmp_path)), one_piece

    for a_project in (
        "make a todo app where I can add tasks, list them, and mark them done",
        "create a REST API for orders. it should authenticate requests, "
        "persist to a database, and expose a migration path",
    ):
        assert _something_to_build(a_project, str(tmp_path)), a_project
