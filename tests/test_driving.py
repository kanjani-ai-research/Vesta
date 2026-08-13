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
    assert _hook({"cwd": str(unfinished), "session_id": "somebody-else"}) == {}
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
