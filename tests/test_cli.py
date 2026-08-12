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
]


def test_help_does_not_raise(capsys):
    with pytest.raises(SystemExit) as leaving:
        main(["--help"])
    assert leaving.value.code == 0
    assert "usage: vesta" in capsys.readouterr().out


@pytest.mark.parametrize("argv", COMMANDS)
def test_every_subcommand_runs(argv, tmp_path, capsys):
    """Not that the answer is right — that the command exists and returns."""
    if argv[0] in {"status", "decided", "defects"}:
        argv = argv + [str(tmp_path)] if argv[0] != "status" else [argv[0], str(tmp_path)] + argv[1:]
    assert main(argv) == 0


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
