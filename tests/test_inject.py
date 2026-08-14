"""Putting what is known in front of an agent, before it decides anything.

This had no tests and was wired only by a stale project-level setting running a
bare `python`, which printed `python: command not found` above every prompt in
a session. The capability was fine; nothing held it to account.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from vesta.inject import context_for, main

HERE = Path(__file__).resolve().parent.parent


class _Reads:
    def __init__(self, text: str) -> None:
        self._text = text

    def read(self) -> str:
        return self._text


@pytest.fixture
def repository(tmp_path):
    """A graphed repository holding one plainly-named definition."""
    from vesta.held import graph_for

    (tmp_path / "work.py").write_text(
        '"""Doing the work."""\n\n\ndef admit(entry):\n    """Take one in."""\n    return entry\n',
        encoding="utf-8",
    )
    graph_for(tmp_path)
    return tmp_path


def test_a_prompt_naming_nothing_is_answered_with_nothing(repository):
    """A hook that prepends to every prompt is a tax on every prompt."""
    assert context_for("add a new field to the form", repository) == ""


def test_a_prompt_naming_a_definition_is_answered(repository):
    said = context_for("how does admit work", repository)
    assert said, "nothing was offered about a definition the graph holds"
    assert "admit" in said


def test_what_is_offered_does_not_pose_as_the_code(repository):
    """It is what earlier sessions worked out, not a substitute for reading."""
    said = context_for("how does admit work", repository)
    assert "not a substitute" in said.lower()


def test_the_hook_speaks_the_frameworks_shape(repository, monkeypatch, capsys):
    monkeypatch.setattr(
        "sys.stdin",
        _Reads(json.dumps({"prompt": "how does admit work", "cwd": str(repository)})),
    )
    assert main() == 0
    said = json.loads(capsys.readouterr().out)
    assert said["hookSpecificOutput"]["hookEventName"] == "UserPromptSubmit"
    assert said["hookSpecificOutput"]["additionalContext"]


def test_the_hook_says_nothing_when_it_has_nothing(repository, monkeypatch, capsys):
    monkeypatch.setattr(
        "sys.stdin",
        _Reads(json.dumps({"prompt": "add a field", "cwd": str(repository)})),
    )
    assert main() == 0
    assert capsys.readouterr().out.strip() == ""


def test_the_hook_survives_anything(monkeypatch):
    """It runs on every prompt. Breaking one is worse than contributing none."""
    for payload in ("", "not json", "{}", '{"prompt": null}', '{"cwd": 12}'):
        monkeypatch.setattr("sys.stdin", _Reads(payload))
        assert main() == 0


def test_it_records_what_it_injected(repository, monkeypatch, capsys):
    """So the saving is measurable rather than asserted."""
    from vesta.home import home

    monkeypatch.setattr(
        "sys.stdin",
        _Reads(json.dumps({"prompt": "how does admit work", "cwd": str(repository)})),
    )
    main()
    capsys.readouterr()
    log = home() / "injected.jsonl"
    assert log.is_file()
    assert json.loads(log.read_text(encoding="utf-8").splitlines()[-1])["chars"] > 0


def test_the_script_is_wired_into_the_plugin():
    """The failure this file exists for: a capability nothing runs."""
    wiring = json.loads((HERE / "hooks" / "hooks.json").read_text(encoding="utf-8"))
    commands = [
        entry["command"]
        for group in wiring["hooks"]["UserPromptSubmit"]
        for entry in group["hooks"]
    ]
    assert any("inject.sh" in c for c in commands), "inject is not wired to anything"


def test_the_script_never_leaks_an_error(tmp_path):
    """It runs on every prompt, including before Vesta can run at all."""
    done = subprocess.run(
        [str(HERE / "hooks" / "inject.sh")],
        input='{"prompt":"x","cwd":"/tmp"}',
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin", "VESTA_NO_INSTALL": "1", "HOME": str(tmp_path)},
        timeout=60,
    )
    assert done.stderr.strip() == ""
    assert "command not found" not in done.stdout + done.stderr
    assert done.returncode == 0


# ── Defects raised at the moment they apply ─────────────────────────────────


def _prepared(repo):
    """Build the graph, as a session's first prompt would have done.

    The hook never builds — surveying an unprepared repository took ten
    seconds on a real workspace, and a hook that stalls a prompt that long is
    uninstalled before anybody finds out it was right. So a test that wants an
    answer has to have prepared, exactly as a real session does.
    """
    from vesta.held import graph_for
    from vesta.patterns import _LISTED

    _LISTED.clear()
    graph_for(repo, rebuild=True)
    return repo


def _repo_with_a_swallowed_failure(tmp_path):
    tmp_path.mkdir(parents=True, exist_ok=True)
    # Shaped like the real thing: a bare `pass` whose body says nothing, in a
    # function something else calls. A `return` anywhere in the try makes the
    # handler look like it reports, which is the detector working as intended.
    (tmp_path / "keep.py").write_text(
        "def store(items):\n"
        "    kept = []\n"
        "    for item in items:\n"
        "        try:\n"
        "            kept.append(item)\n"
        "        except Exception:\n"
        "            pass\n"
        "    return kept\n"
        "\n"
        "def use():\n"
        "    return store([1])\n",
        encoding="utf-8",
    )
    (tmp_path / "clean.py").write_text(
        "def add(a, b):\n"
        '    """Sum two numbers."""\n'
        "    return a + b\n",
        encoding="utf-8",
    )
    return _prepared(tmp_path)


def test_a_defect_is_raised_when_the_file_is_named(tmp_path, monkeypatch):
    """The whole point of surfacing.

    Every defect Vesta finds was findable before this existed, by typing a
    command — and nobody types it. A tool whose usefulness depends on
    remembering its API does not get used.
    """
    monkeypatch.setenv("VESTA_HOME", str(tmp_path / "home"))
    repo = _repo_with_a_swallowed_failure(tmp_path / "repo")

    from vesta.inject import _something_already_wrong

    said = _something_already_wrong("add a retry to keep.py", str(repo))
    assert "keep.py" in said
    assert "swallowed failure" in said


def test_nothing_is_said_about_a_file_with_nothing_wrong(tmp_path, monkeypatch):
    monkeypatch.setenv("VESTA_HOME", str(tmp_path / "home"))
    repo = _repo_with_a_swallowed_failure(tmp_path / "repo")

    from vesta.inject import _something_already_wrong

    assert _something_already_wrong("tidy up clean.py", str(repo)) == ""


def test_nothing_is_said_when_no_file_is_named(tmp_path, monkeypatch):
    """Sending every defect on every prompt is the other way to be useless."""
    monkeypatch.setenv("VESTA_HOME", str(tmp_path / "home"))
    repo = _repo_with_a_swallowed_failure(tmp_path / "repo")

    from vesta.inject import _something_already_wrong

    assert _something_already_wrong("what does this project do", str(repo)) == ""
    assert _something_already_wrong("add a new endpoint", str(repo)) == ""


def test_a_defect_elsewhere_is_not_raised(tmp_path, monkeypatch):
    """Relevance is the condition. A finding in another file is a report, and
    a report nobody asked for teaches somebody to skim the channel."""
    monkeypatch.setenv("VESTA_HOME", str(tmp_path / "home"))
    repo = _repo_with_a_swallowed_failure(tmp_path / "repo")

    from vesta.inject import _something_already_wrong

    said = _something_already_wrong("edit clean.py", str(repo))
    assert "keep.py" not in said


def test_the_agent_is_told_not_to_stop_work_over_it(tmp_path, monkeypatch):
    """A remark, not an instruction. Fixing something unasked mid-task is how
    a helpful channel becomes one somebody turns off."""
    monkeypatch.setenv("VESTA_HOME", str(tmp_path / "home"))
    repo = _repo_with_a_swallowed_failure(tmp_path / "repo")

    from vesta.inject import _something_already_wrong

    said = _something_already_wrong("add a retry to keep.py", str(repo)).lower()
    assert "do not fix them unasked" in said
    assert "do not stop what you were asked to do" in said


def test_a_weak_signal_does_not_interrupt(tmp_path, monkeypatch):
    """Only `clear` and `likely` speak. "worth a look" is a signal, and
    raising one unasked mid-edit is exactly the noise this must not add."""
    monkeypatch.setenv("VESTA_HOME", str(tmp_path / "home"))
    repo = tmp_path / "weak"
    repo.mkdir()
    # Unreferenced definition — reported, but only ever "worth a look".
    (repo / "lonely.py").write_text(
        "def nobody_calls_this():\n    return 1\n", encoding="utf-8"
    )

    from vesta.inject import _something_already_wrong

    assert _something_already_wrong("edit lonely.py", str(repo)) == ""


def test_an_unprepared_repository_is_never_surveyed_in_a_hook(tmp_path, monkeypatch):
    """A hook that stalls a prompt is uninstalled before it is understood.

    Surveying an unprepared workspace took **ten seconds** on a real project.
    Nothing is built here: if the graph is not ready the offer is silent, and
    the next prompt can answer.
    """
    monkeypatch.setenv("VESTA_HOME", str(tmp_path / "home"))
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "keep.py").write_text(
        "def store(items):\n"
        "    kept = []\n"
        "    for item in items:\n"
        "        try:\n"
        "            kept.append(item)\n"
        "        except Exception:\n"
        "            pass\n"
        "    return kept\n",
        encoding="utf-8",
    )

    from vesta.inject import _something_already_wrong

    # Nothing prepared: silent, and fast.
    import time

    started = time.time()
    assert _something_already_wrong("edit keep.py", str(repo)) == ""
    assert time.time() - started < 2.0


# ── Automation is offered to a new project and never to one midstream ───────


def _dir(tmp_path, name, files=(), dirs=()):
    root = tmp_path / name
    root.mkdir(parents=True)
    for d in dirs:
        (root / d).mkdir(parents=True, exist_ok=True)
    for f, body in files:
        path = root / f
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
    return root


def test_an_empty_directory_is_a_new_project(tmp_path):
    from vesta.inject import _nothing_built_here

    assert _nothing_built_here(str(_dir(tmp_path, "empty")))


def test_a_tree_of_empty_directories_is_still_new(tmp_path):
    """Somebody who laid out src/, tests/ and docs/ has built nothing."""
    from vesta.inject import _nothing_built_here

    root = _dir(tmp_path, "laid-out", dirs=("src", "tests", "docs/api"))
    assert _nothing_built_here(str(root))


def test_notes_and_briefs_are_what_a_project_looks_like_before_it_is_one(tmp_path):
    """Markdown, text, JSON, CSV and the formats a brief arrives in."""
    from vesta.inject import _nothing_built_here

    root = _dir(
        tmp_path,
        "briefed",
        files=(
            ("README.md", "# the idea"),
            ("spec.txt", "what it must do"),
            ("requirements.csv", "a,b"),
            ("data.json", "{}"),
            ("brief.pdf", "%PDF"),
            ("notes.docx", "PK"),
        ),
    )
    assert _nothing_built_here(str(root))


def test_git_and_gitignore_do_not_make_it_a_started_project(tmp_path):
    """`git init` and a .gitignore are what somebody does *before* writing."""
    from vesta.inject import _nothing_built_here

    root = _dir(
        tmp_path,
        "fresh-repo",
        files=((".git/HEAD", "ref: refs/heads/main"), (".gitignore", "*.pyc")),
    )
    assert _nothing_built_here(str(root))


def test_a_single_source_file_means_work_has_started(tmp_path):
    from vesta.inject import _nothing_built_here

    assert not _nothing_built_here(
        str(_dir(tmp_path, "started", files=(("main.py", "x = 1"),)))
    )
    assert not _nothing_built_here(
        str(_dir(tmp_path, "nested", files=(("src/app.ts", "let x"),)))
    )


def test_a_manifest_is_a_project_however_it_is_spelled(tmp_path):
    """`.json` has to be allowed — a brief arrives as one — but package.json
    is a dependency tree and the clearest evidence a project exists."""
    from vesta.inject import _nothing_built_here

    for name, body in (
        ("package.json", "{}"),
        ("pyproject.toml", "[project]"),
        ("go.mod", "module x"),
        ("Makefile", "all:"),
        ("Dockerfile", "FROM scratch"),
    ):
        root = _dir(tmp_path, f"has-{name}", files=((name, body),))
        assert not _nothing_built_here(str(root)), f"{name} should mean started"


def test_automation_is_never_offered_in_a_repository_under_way(tmp_path):
    """The rule this exists for.

    Offering to agree a contract and run to completion inside a repository
    somebody has worked in for months is an interruption proposing to take
    over — and the offer alone is enough to make the tool feel dangerous.
    """
    from vesta.inject import _something_to_build

    asking = (
        "build me an expense tracker: record an expense, see what I spent, "
        "set budgets, and export to CSV"
    )
    under_way = _dir(tmp_path, "midstream", files=(("app.py", "def main(): pass"),))
    assert _something_to_build(asking, str(under_way)) == ""


def test_automation_is_offered_where_nothing_has_been_built(tmp_path, monkeypatch):
    from vesta.inject import _something_to_build

    monkeypatch.setenv("VESTA_HOME", str(tmp_path / "home"))
    asking = (
        "build me an expense tracker: record an expense, see what I spent, "
        "set budgets, and export to CSV"
    )
    fresh = _dir(tmp_path, "fresh", files=(("brief.md", "an expense tracker"),))
    assert _something_to_build(asking, str(fresh)) != ""


def test_a_directory_that_cannot_be_read_is_not_treated_as_new(tmp_path):
    """Silence is the safe answer: offering to take over on a directory
    nothing could be learned about is the expensive mistake."""
    from vesta.inject import _nothing_built_here

    assert not _nothing_built_here(str(tmp_path / "does-not-exist"))


# ── A repository nobody has read against its own vocabulary ─────────────────


def _read_repo(tmp_path, name, ontology: bool):
    """A prepared repository, with or without a derived vocabulary."""
    from vesta.derive import write_terms
    from vesta.held import graph_for

    root = tmp_path / name
    root.mkdir(parents=True)
    (root / "store.py").write_text(
        "class Store:\n"
        '    """Keeps documents."""\n'
        "    def put(self, doc):\n"
        "        return doc\n",
        encoding="utf-8",
    )
    graph_for(root, rebuild=True)
    if ontology:
        write_terms(root, "domain: keeping documents\nactivity: put a document\n")
    return root


def test_a_question_about_the_work_asks_for_the_vocabulary(tmp_path, monkeypatch):
    """The chain that silently never started.

    `prepare` builds the graph and calls no model by design — naming what code
    is *for* is judgement. So the ontology is derived only when `does` or
    `means` is called, and those are tools an agent has to choose. On a real
    project the graph was built and the vocabulary was still empty weeks later,
    because nothing had ever asked.
    """
    monkeypatch.setenv("VESTA_HOME", str(tmp_path / "home"))
    root = _read_repo(tmp_path, "unread", ontology=False)

    from vesta.inject import _never_been_read

    said = _never_been_read("where is the document handling", str(root))
    assert "vesta-domain" in said
    assert "do not ask permission" in said.lower()


def test_ordinary_work_does_not_ask_for_it(tmp_path, monkeypatch):
    """Only a question the vocabulary would have answered. "add a retry" is
    work, and interrupting it to derive an ontology is the noise this must
    not add."""
    monkeypatch.setenv("VESTA_HOME", str(tmp_path / "home"))
    root = _read_repo(tmp_path, "working", ontology=False)

    from vesta.inject import _never_been_read

    assert _never_been_read("add a retry to store.py", str(root)) == ""
    assert _never_been_read("fix the typo in the docstring", str(root)) == ""


def test_a_repository_already_read_is_not_asked_again(tmp_path, monkeypatch):
    """Read once. Asking twice is the nagging that gets a channel ignored."""
    monkeypatch.setenv("VESTA_HOME", str(tmp_path / "home"))
    root = _read_repo(tmp_path, "already-read", ontology=True)

    from vesta.inject import _never_been_read

    assert _never_been_read("where is the document handling", str(root)) == ""


def test_nothing_is_asked_before_there_is_a_graph(tmp_path, monkeypatch):
    """There would be nothing to bind terms to, and preparation is already
    under way from the branch that builds the graph."""
    monkeypatch.setenv("VESTA_HOME", str(tmp_path / "home"))
    root = tmp_path / "unprepared"
    root.mkdir()
    (root / "a.py").write_text("x = 1\n", encoding="utf-8")

    from vesta.inject import _never_been_read

    assert _never_been_read("what does this project do", str(root)) == ""
