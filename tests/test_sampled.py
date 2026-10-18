"""Whether a test can run on its data decides whether a full run is worth it."""

from __future__ import annotations

import subprocess
import sys

import pytest

from vesta import sampled
from vesta.instead import _a_full_test_run, decide

GOOD = '''import os, pytest
@pytest.mark.parametrize("n", range(10))
def test_each(n):
    assert n >= 0
def test_walks_its_own_rows():
    rows = list(range(100))[: int(os.environ.get("VESTA_SAMPLE") or 0) or None]
    assert len(rows) == 3
'''

NEGATIVE = "def test_says_no():\n    assert 1 == 2\n"

BROKEN = '''import pytest
@pytest.fixture
def data():
    return open("missing.csv").read()
def test_uses(data):
    assert data
'''


@pytest.fixture
def project(tmp_path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_good.py").write_text(GOOD, encoding="utf-8")
    (tmp_path / "tests" / "test_negative.py").write_text(NEGATIVE, encoding="utf-8")
    (tmp_path / "tests" / "test_broken.py").write_text(BROKEN, encoding="utf-8")
    return tmp_path


def test_nothing_sampled_is_not_ready(project):
    here = sampled.standing(project)
    assert not here.ready
    assert len(here.unsampled) == 3


def test_it_stops_at_the_first_test_that_cannot_run(project):
    done = sampled.run(project)
    assert done.ran
    here = sampled.standing(project)
    assert "tests/test_broken.py" in here.could_not_run
    assert "FileNotFoundError" in here.could_not_run["tests/test_broken.py"]
    assert not here.ready


def test_a_negative_verdict_is_still_a_test_that_runs(project):
    (project / "missing.csv").write_text("a,b\n", encoding="utf-8")
    done = sampled.run(project)
    here = sampled.standing(project)
    assert here.ready, here.describe()
    assert "tests/test_negative.py" in here.failing
    # Ten parametrized records cut to three; the test walking its own rows
    # saw three, which it asserts itself.
    each = [n for n in done.tests if "test_each[" in n]
    assert len(each) == sampled.RECORDS
    assert done.tests["tests/test_good.py::test_walks_its_own_rows"]["came_to"] == "verdict"


def test_editing_a_test_sends_it_back_to_be_sampled(project):
    (project / "missing.csv").write_text("a,b\n", encoding="utf-8")
    sampled.run(project)
    (project / "tests" / "test_good.py").write_text(GOOD + "\n# edited\n", encoding="utf-8")
    assert sampled.standing(project).unsampled == ["tests/test_good.py"]


def test_a_file_with_no_tests_does_not_hold_runs_back(project):
    (project / "missing.csv").write_text("a,b\n", encoding="utf-8")
    (project / "tests" / "test_empty.py").write_text("X = 1\n", encoding="utf-8")
    sampled.run(project)
    assert sampled.standing(project).ready


@pytest.mark.parametrize(
    "command, full",
    [
        ("pytest", True),
        ("python3 -m pytest -q", True),
        ("cd x && pytest tests/", True),
        ("pytest tests/test_good.py", False),
        ("pytest tests/test_good.py::test_each", False),
        ("pytest -k walks", False),
        ("pytest --sample 3", False),
        ("pytest --lf", False),
        ("grep pytest README.md", False),
    ],
)
def test_what_counts_as_a_full_run(command, full):
    assert _a_full_test_run(command) is full


def _bash(command: str, project) -> dict:
    return {"tool_name": "Bash", "tool_input": {"command": command}, "cwd": str(project)}


def test_a_full_run_is_held_back_until_sampled(project, monkeypatch):
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(project))
    said = decide(_bash("python3 -m pytest -q", project))
    assert said["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert "sample" in said["hookSpecificOutput"]["permissionDecisionReason"]
    assert decide(_bash("pytest tests/test_good.py", project)) is None

    (project / "missing.csv").write_text("a,b\n", encoding="utf-8")
    sampled.run(project)
    assert decide(_bash("python3 -m pytest -q", project)) is None


def test_a_project_vesta_cannot_sample_is_not_held_back(project, monkeypatch):
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(project))
    sampled._runner(project, "no interpreter here has pytest")
    assert decide(_bash("pytest", project)) is None


def test_the_command_reports_and_fails_on_a_test_that_cannot_run(project):
    from vesta.home import home

    done = subprocess.run(
        [sys.executable, "-m", "vesta.cli", "sample", "--root", str(project)],
        capture_output=True, text=True, timeout=120,
        env={**__import__("os").environ, "VESTA_HOME": str(home())},
    )
    assert done.returncode == 1
    assert "do not yet run on the data" in done.stdout
    assert "missing.csv" in done.stdout


def test_the_plugin_records_nothing_without_a_sample(tmp_path):
    (tmp_path / "test_x.py").write_text("def test_x():\n    assert True\n", encoding="utf-8")
    to = tmp_path / "out.json"
    import os
    from pathlib import Path

    package = str(Path(sampled.__file__).resolve().parent.parent)
    subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "vesta.sampling", str(tmp_path / "test_x.py")],
        cwd=str(tmp_path), capture_output=True, text=True, timeout=60,
        env={**os.environ, "PYTHONPATH": package, "VESTA_SAMPLED_TO": str(to)},
    )
    assert not to.exists()


def test_a_sample_cut_off_keeps_what_finished_and_carries_on(tmp_path, monkeypatch):
    (tmp_path / "test_a_quick.py").write_text("def test_a():\n    assert True\n", encoding="utf-8")
    (tmp_path / "test_b_slow.py").write_text(
        "import time\ndef test_first():\n    assert True\n"
        "def test_second():\n    time.sleep(30)\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(sampled, "WITHIN", 4)
    done = sampled.run(tmp_path)
    assert done.ran and "limit" in done.said
    here = sampled.standing(tmp_path)
    # The quick file finished; the slow one was cut off part way and none of
    # it is kept.
    assert here.validated == ["test_a_quick.py"]
    assert here.unsampled == ["test_b_slow.py"]

    (tmp_path / "test_b_slow.py").write_text(
        "def test_first():\n    assert True\n", encoding="utf-8"
    )
    monkeypatch.setattr(sampled, "WITHIN", 120)
    done = sampled.run(tmp_path)
    # Only what was left was run.
    assert all(n.startswith("test_b_slow.py") for n in done.tests)
    assert sampled.standing(tmp_path).ready


def test_an_empty_file_among_those_left_settles(project):
    (project / "missing.csv").write_text("a,b\n", encoding="utf-8")
    sampled.run(project)
    (project / "tests" / "test_empty.py").write_text("X = 1\n", encoding="utf-8")
    sampled.run(project)
    assert sampled.standing(project).ready
