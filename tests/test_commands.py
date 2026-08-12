"""The slash commands a user types.

These are the whole user-facing surface, and each one is a shell line in a
markdown file — which no import checks and no type sees. The failure they are
written against is real: every command initially ran `vesta …`, which is not on
PATH when the plugin is installed by the framework rather than by pip, so every
one of them printed a Python traceback where an answer belonged.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest

import vesta.cli as cli
from vesta.guide import commands as guide_commands

HERE = Path(__file__).resolve().parent.parent
COMMANDS = sorted((HERE / "commands").glob("*.md"))
RUNNER = HERE / "bin" / "vesta-run"

# The line a command actually executes.
INLINE = re.compile(r"!`([^`]+)`")


def _frontmatter(text: str) -> dict:
    if not text.startswith("---"):
        return {}
    _, block, _ = text.split("---", 2)
    found = {}
    for line in block.strip().splitlines():
        key, _, value = line.partition(":")
        found[key.strip()] = value.strip()
    return found


def _subcommands() -> set:
    """Every subcommand `vesta` accepts, from the parser itself."""
    import argparse

    found = set()
    parser_actions = []

    class _Capture(argparse.ArgumentParser):
        def parse_args(self, *a, **k):  # never actually parses
            raise SystemExit(0)

    try:
        cli.main(["--help"])
    except SystemExit:
        pass

    # Read them off the parser the same way argparse does.
    import io
    from contextlib import redirect_stdout

    out = io.StringIO()
    with redirect_stdout(out):
        try:
            cli.main(["--help"])
        except SystemExit:
            pass
    text = out.getvalue()
    inside = text.split("{", 1)[-1].split("}", 1)[0]
    return {name.strip() for name in inside.split(",") if name.strip()}


SUBCOMMANDS = _subcommands()


def test_there_are_commands():
    assert COMMANDS, "no slash commands found"


@pytest.mark.parametrize("path", COMMANDS, ids=lambda p: p.stem)
def test_every_command_declares_itself(path):
    """A user reading `/help` sees only the description, so it must be there."""
    front = _frontmatter(path.read_text(encoding="utf-8"))
    assert front.get("description"), f"{path.name} has no description"
    assert len(front["description"]) < 90, "description is too long to read in a list"
    assert front.get("allowed-tools"), f"{path.name} does not declare its tools"


@pytest.mark.parametrize("path", COMMANDS, ids=lambda p: p.stem)
def test_every_command_runs_a_subcommand_that_exists(path):
    """The failure this file exists for: a command invoking nothing."""
    text = path.read_text(encoding="utf-8")
    inline = INLINE.search(text)
    assert inline, f"{path.name} runs nothing"

    line = inline.group(1)
    assert "vesta-run" in line, f"{path.name} does not go through the runner"

    after = line.split("vesta-run", 1)[1].strip()
    word = after.split()[0]
    assert word in SUBCOMMANDS, f"{path.name} runs `vesta {word}`, which does not exist"


@pytest.mark.parametrize("path", COMMANDS, ids=lambda p: p.stem)
def test_every_command_declares_the_runner_it_calls(path):
    front = _frontmatter(path.read_text(encoding="utf-8"))
    assert "vesta-run" in front.get("allowed-tools", ""), (
        f"{path.name} runs the runner but does not permit it"
    )


def test_the_runner_never_shows_a_traceback():
    """Installed or not, a user gets a sentence rather than a stack."""
    done = subprocess.run(
        [str(RUNNER), "shape"],
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin", "CLAUDE_PLUGIN_ROOT": "/nonexistent"},
        cwd=str(HERE),
    )
    assert "Traceback" not in done.stdout + done.stderr
    assert "not installed" in done.stdout
    # Exits cleanly: a command that fails noisily reads as a broken session.
    assert done.returncode == 0


def test_the_runner_finds_vesta_when_it_is_there():
    import sys

    done = subprocess.run(
        [str(RUNNER), "guide"],
        capture_output=True,
        text=True,
        env={**os.environ, "VESTA_PYTHON": sys.executable},
        cwd=str(HERE),
    )
    assert done.returncode == 0, done.stderr
    assert "Vesta" in done.stdout


@pytest.mark.parametrize("command", guide_commands(), ids=lambda c: c.split()[1])
def test_the_guide_only_shows_commands_that_exist(command):
    """A guide that drifts is worse than none, because it is believed."""
    word = command.split()[1]
    assert word in SUBCOMMANDS, f"the guide shows `{command}`, which does not exist"
