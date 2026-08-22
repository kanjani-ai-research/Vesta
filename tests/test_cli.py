"""The command line a user actually types.

Nothing tested this, and it was broken: a call to a function deleted with the
theory half survived in `main`, so every invocation of `vesta` died on a
NameError. The entry point is what a slash command runs, so a break here is
a break in the whole user-facing surface.
"""

from __future__ import annotations

import subprocess
import sys

import pytest

from vesta.cli import main

# Every subcommand, and arguments that make it do the least work possible.
COMMANDS = [
    ["status"],
    ["status", "--prepare"],
    ["used"],
    ["decided"],
    ["defects"],
    ["contract"],
    ["learn"],
]


def test_help_does_not_raise(capsys):
    with pytest.raises(SystemExit) as leaving:
        main(["--help"])
    assert leaving.value.code == 0
    assert "usage: vesta" in capsys.readouterr().out


# `root` is positional for these three, a `--root` flag for these two, and
# not accepted at all by `used` (a query across every project, not one) —
# three shapes, each exercised here so every command in COMMANDS is actually
# pointed at the empty `tmp_path` rather than accidentally running against
# the real working directory.
POSITIONAL_ROOT = {"status", "decided", "defects"}
FLAG_ROOT = {"contract", "learn"}


@pytest.mark.parametrize("argv", COMMANDS)
def test_every_subcommand_runs(argv, tmp_path, capsys):
    """Not that the answer is right — that the command exists and returns
    zero. A legitimate, well-formed "nothing here yet" answer is success, not
    failure — a status query returning nonzero reads as broken to any script
    or wrapper that checks the exit code."""
    if argv[0] in POSITIONAL_ROOT:
        argv = [argv[0], str(tmp_path)] + argv[1:]
    elif argv[0] in FLAG_ROOT:
        argv = argv + ["--root", str(tmp_path)]
    assert main(argv) == 0


def test_a_project_with_nothing_agreed_is_not_an_error(tmp_path, capsys):
    """`vesta contract` with nothing yet agreed is a real, complete answer —
    not a failed action — and used to exit 1 for it, which looks like a
    crash to any script or wrapper checking the exit code."""
    assert main(["contract", "--root", str(tmp_path)]) == 0
    assert "Nothing has been agreed" in capsys.readouterr().out


def test_a_nonexistent_path_is_distinguished_from_an_unbuilt_one(tmp_path, capsys):
    """A path that is not a directory at all used to produce the identical
    "nothing has been built" message as a real, empty, unbuilt project —
    sending a user to `--prepare` a build that can never succeed."""
    absent = tmp_path / "does-not-exist"

    assert main(["status", str(absent)]) == 0
    absent_said = capsys.readouterr().out

    unbuilt = tmp_path / "real"
    unbuilt.mkdir()
    assert main(["status", str(unbuilt)]) == 0
    unbuilt_said = capsys.readouterr().out

    assert "not a directory" in absent_said
    assert "not a directory" not in unbuilt_said
    assert absent_said != unbuilt_said


def test_learn_asks_about_at_most_show_candidates_total(tmp_path, monkeypatch):
    """The command's own doc says "ask about at most five" — but the code
    applied that cap to two separate lists (previously-shown and freshly
    found) rather than to their sum, so 4 already-waiting plus 5 newly-found
    showed 9. `--show` bounds the whole invocation, not each half of it."""
    from vesta import confirm
    from vesta.rules import Found, Rule

    for i in range(4):
        confirm.record(tmp_path, f"abstained candidate {i}", confirm.ABSTAINED)

    fresh = Found(rules=[Rule(text=f"fresh candidate {i}") for i in range(5)])
    monkeypatch.setattr("vesta.rules.from_sessions", lambda where: fresh)

    import io
    import contextlib

    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        assert main(["learn", "--root", str(tmp_path), "--show", "5"]) == 0
    said = out.getvalue()

    shown_waiting = said.count("abstained candidate")
    shown_fresh = said.count("fresh candidate")
    assert shown_waiting + shown_fresh <= 5


def test_learn_shows_previously_waiting_candidates_before_new_ones(tmp_path, monkeypatch):
    """A question already put to somebody is owed an answer before another
    one is asked — previously-shown candidates fill the budget first, and a
    tighter budget should shrink the new list, never drop an old one."""
    from vesta import confirm
    from vesta.rules import Found, Rule

    for i in range(5):
        confirm.record(tmp_path, f"abstained candidate {i}", confirm.ABSTAINED)

    fresh = Found(rules=[Rule(text=f"fresh candidate {i}") for i in range(5)])
    monkeypatch.setattr("vesta.rules.from_sessions", lambda where: fresh)

    import io
    import contextlib

    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        assert main(["learn", "--root", str(tmp_path), "--show", "3"]) == 0
    said = out.getvalue()

    assert said.count("abstained candidate") == 3
    assert "fresh candidate" not in said


def test_the_installed_entry_point_works():
    """`vesta` as a user types it, not as pytest imports it."""
    done = subprocess.run(
        [sys.executable, "-m", "vesta.cli", "--help"],
        capture_output=True,
        text=True,
    )
    assert done.returncode == 0, done.stderr
    assert "usage: vesta" in done.stdout


def test_no_dead_references_survive_in_main():
    """The failure mode that got through: a name that no longer exists."""
    import ast
    from pathlib import Path

    import vesta.cli as module

    source = Path(module.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    defined = {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    }
    imported = {
        alias.asname or alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }
    called = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    import builtins

    unknown = called - defined - imported - set(dir(builtins))
    assert not unknown, f"cli.py calls names that do not exist: {sorted(unknown)}"
