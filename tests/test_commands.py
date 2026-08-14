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
    """Installed or not, a user gets an answer or a sentence — never a stack.

    Run from a checkout this finds the virtualenv beside the source and
    answers; the copied-plugin case, where there is nothing to find, is
    covered separately below.
    """
    done = subprocess.run(
        [str(RUNNER), "shape"],
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin"},
        cwd=str(HERE),
        timeout=120,
    )
    assert "Traceback" not in done.stdout + done.stderr
    assert "command not found" not in done.stdout + done.stderr
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


@pytest.mark.parametrize("command", guide_commands(), ids=lambda c: c.replace(" ", "-"))
def test_the_guide_only_shows_commands_that_exist(command):
    """A guide that drifts is worse than none, because it is believed.

    Both surfaces are checked. The guide cites `vesta words` and
    `/vesta:tutorial`, and a slash command that does not exist is exactly as
    misleading as a subcommand that does not.
    """
    if command.startswith("/vesta:"):
        here = Path(__file__).resolve().parent.parent / "commands"
        name = command.split(":", 1)[1].split()[0]
        assert (here / f"{name}.md").is_file(), (
            f"the guide shows `{command}`, which is not a command"
        )
        return

    word = command.split()[1]
    assert word in SUBCOMMANDS, f"the guide shows `{command}`, which does not exist"


def test_the_guide_mentions_every_command_a_user_would_run():
    """The drift that actually happened, in the direction nobody checks.

    The guide was held to "everything it shows must exist", which it always
    passed — while `contract`, `drive` and `words` were added and never
    mentioned. A reference silently missing a third of the tool is worse than
    one naming something that is gone, because nothing ever fails.
    """
    shown = {c.split()[1] for c in guide_commands() if not c.startswith("/")}

    # What a user never types: `graph` and `prepare` are what `status` does
    # for them, and `guide` is the thing they are already reading.
    theirs = SUBCOMMANDS - {"graph", "prepare", "guide", "tutorial"}

    missing = theirs - shown
    assert not missing, f"the guide never mentions: {sorted(missing)}"


# ── The manifest the framework reads ────────────────────────────────────────


def _manifest() -> dict:
    import json

    return json.loads(
        (HERE / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8")
    )


def test_the_manifest_does_not_name_the_standard_hooks_file():
    """`hooks/hooks.json` is loaded on its own.

    Naming it in the manifest loads it twice, and the whole plugin then fails
    to load — every command, agent and tool absent, over one redundant line.
    The manifest may only point at *additional* hook files.
    """
    named = _manifest().get("hooks")
    if named is None:
        return
    named = [named] if isinstance(named, str) else named
    for entry in named:
        assert "hooks/hooks.json" not in str(entry), (
            "the manifest names the standard hooks file, which is already "
            "loaded automatically — the plugin will refuse to load"
        )


def test_the_manifest_declares_the_mcp_server():
    """A root `.mcp.json` is not enough; a plugin declares its own servers.

    Without this the plugin loads and every tool is simply missing, with
    nothing said about why.
    """
    servers = _manifest().get("mcpServers", {})
    assert servers, "the plugin does not declare its MCP server"
    # The name is what a user sees as `plugin:vesta:<name>`, so it is theirs to
    # choose; what must hold is that exactly one server is declared and it runs
    # the launcher rather than a bare interpreter.
    assert len(servers) == 1, f"expected one server, found {sorted(servers)}"
    (only,) = servers.values()
    assert "vesta-sidecar" in only["command"]


def test_the_declared_server_command_exists_and_runs():
    (only,) = _manifest()["mcpServers"].values()
    command = only["command"]
    path = HERE / command.replace("${CLAUDE_PLUGIN_ROOT}/", "")
    assert path.is_file(), f"{path} is declared but not present"
    assert path.stat().st_mode & 0o111, f"{path} is not executable"


def test_every_skill_directory_holds_a_skill():
    """An empty skill directory is a leftover, and a loader may reject it."""
    for directory in (HERE / "skills").iterdir():
        if not directory.is_dir():
            continue
        assert (directory / "SKILL.md").is_file(), (
            f"{directory.name}/ has no SKILL.md"
        )


def test_hook_scripts_are_executable():
    for script in (HERE / "hooks").glob("*.sh"):
        assert script.stat().st_mode & 0o111, f"{script.name} is not executable"


def test_no_component_runs_a_bare_interpreter():
    """`python3 -m vesta.x` assumes the shell's python has Vesta. It does not:
    a plugin is installed by the framework, not into a virtualenv."""
    for script in list((HERE / "hooks").glob("*.sh")) + list((HERE / "bin").iterdir()):
        text = script.read_text(encoding="utf-8")
        if "vesta." not in text or script.name == "vesta-python":
            continue
        # Either it asks the resolver, or it is the resolver.
        assert "vesta-python" in text, (
            f"{script.name} runs an interpreter without asking which one"
        )


# ── Reaching an interpreter that can actually run Vesta ─────────────────────


def _copied(tmp_path):
    """The plugin as the framework installs it: a copy, with a dead venv.

    The install copies the repository. A virtualenv does not survive that —
    `bin/python` is a symlink to the interpreter it was built from — so the
    directory arrives intact with nothing runnable inside it.
    """
    import shutil

    (tmp_path / "bin").mkdir()
    (tmp_path / "hooks").mkdir()
    (tmp_path / ".venv" / "bin").mkdir(parents=True)
    for name in ("vesta-python", "vesta-run", "vesta-sidecar"):
        shutil.copy(HERE / "bin" / name, tmp_path / "bin" / name)
    shutil.copy(HERE / "hooks" / "notice.sh", tmp_path / "hooks" / "notice.sh")
    (tmp_path / ".venv" / "bin" / "python").symlink_to("/nonexistent/python")
    return tmp_path


BARE = {"PATH": "/usr/bin:/bin"}


def test_a_command_in_a_copied_plugin_says_why(tmp_path):
    """`/bin/sh: python: command not found` is what the user saw. A command
    must answer or explain, never leak a shell error."""
    import subprocess

    copied = _copied(tmp_path)
    done = subprocess.run(
        [str(copied / "bin" / "vesta-run"), "guide"],
        capture_output=True,
        text=True,
        env={**BARE, "VESTA_NO_INSTALL": "1", "HOME": str(tmp_path)},
        timeout=60,
    )
    assert "command not found" not in done.stdout + done.stderr
    assert "Traceback" not in done.stdout + done.stderr
    # It builds its own environment, so a bare copy answers rather than
    # explaining. Only when it cannot build one is there anything to say, and
    # `tests/test_install.py` covers that.
    assert done.returncode == 0


def test_the_hook_in_a_copied_plugin_is_silent(tmp_path):
    """It runs on every prompt. An error here appears above every one of them."""
    import subprocess

    copied = _copied(tmp_path)
    done = subprocess.run(
        [str(copied / "hooks" / "notice.sh")],
        input='{"prompt":"x","cwd":"/tmp"}',
        capture_output=True,
        text=True,
        env=BARE,
        timeout=60,
    )
    assert done.stdout.strip() == ""
    assert done.stderr.strip() == ""
    assert done.returncode == 0


def test_the_sidecar_in_a_copied_plugin_says_why_on_stderr(tmp_path):
    """A server that cannot start is otherwise simply absent, with every tool
    missing and nothing said about it."""
    import subprocess

    copied = _copied(tmp_path)
    done = subprocess.run(
        [str(copied / "bin" / "vesta-sidecar")],
        input="",
        capture_output=True,
        text=True,
        env=BARE,
        timeout=60,
    )
    assert "no interpreter" in done.stderr
    assert "command not found" not in done.stderr


def test_a_copied_plugin_works_when_told_where_to_look(tmp_path):
    import subprocess
    import sys

    copied = _copied(tmp_path)
    done = subprocess.run(
        [str(copied / "bin" / "vesta-run"), "guide"],
        capture_output=True,
        text=True,
        env={**BARE, "VESTA_PYTHON": sys.executable},
        timeout=90,
    )
    assert done.returncode == 0, done.stderr
    assert "Vesta" in done.stdout


def test_a_dead_symlink_is_never_treated_as_an_interpreter(tmp_path):
    """`command -v` succeeds for a path whose symlink target is gone. Every
    candidate must be executed, not merely looked at."""
    import subprocess

    copied = _copied(tmp_path)
    done = subprocess.run(
        [str(copied / "bin" / "vesta-python")],
        capture_output=True,
        text=True,
        env=BARE,
        timeout=60,
    )
    assert ".venv" not in done.stdout
    assert done.returncode == 1


def test_the_venv_is_not_shipped():
    """It cannot work in a copy, so shipping it only creates the dead path."""
    ignored = (HERE / ".claudeignore").read_text(encoding="utf-8")
    assert ".venv/" in ignored


def test_no_project_setting_runs_a_bare_interpreter():
    """A `.claude/settings.json` hook running `python -m vesta.x` printed
    `python: command not found` above every prompt — from outside the plugin,
    so nothing in the plugin could fix it."""
    import json

    settings = HERE / ".claude" / "settings.json"
    if not settings.is_file():
        return
    text = settings.read_text(encoding="utf-8")
    found = json.loads(text)
    commands = [
        entry.get("command", "")
        for group in found.get("hooks", {}).values()
        for block in group
        for entry in block.get("hooks", [])
    ]
    for command in commands:
        assert not command.strip().startswith(("python ", "python3 ")), (
            f"a project hook runs a bare interpreter: {command!r}"
        )


def test_the_guide_shows_commands_a_reader_can_actually_type():
    """`vesta` is not on PATH, and the guide is read inside a session.

    A plugin is installed by the framework, not by pip, so `vesta shape` fails
    with "command not found" for everyone reading this through `/vesta:help` —
    which renders the guide verbatim and is most people's first contact.
    Twenty-seven entries were spelled that way, so the first thing a new user
    was taught was twenty-seven things that do not work for them.
    """
    from vesta.guide import as_typed, commands, guide

    here = Path(__file__).resolve().parent.parent / "commands"
    have = {path.stem for path in here.glob("*.md")}

    for command in commands():
        shown = as_typed(command)
        assert shown.startswith("/vesta:"), f"{command!r} renders as {shown!r}"
        name = shown.split(":", 1)[1].split()[0]
        assert name in have, f"the guide shows `{shown}`, which is not a command"

    # And nothing in the body still tells somebody to type the bare form.
    body = guide()
    assert "\n  vesta " not in body


def test_the_guide_says_where_the_terminal_form_works():
    """The bare spelling is real for anybody who installed the package. Saying
    so once is the difference between a rule and a mystery."""
    from vesta.guide import guide

    said = guide().lower()
    assert "slash command" in said
    assert "terminal" in said


def test_a_broken_environment_is_a_sentence_not_a_stack():
    """A graph that resolved nothing now raises rather than caching itself.

    That is right, and it must not reach the user as a traceback: somebody with
    no language server installed has a fixable problem, and a stack tells them
    nothing about it. Zero, not one, because a slash command exiting non-zero
    is rendered as the plugin having failed — a worse description of "you have
    no Python language server" than the sentence itself.
    """
    done = subprocess.run(
        [str(RUNNER), "shape"],
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin"},
        cwd=str(HERE),
        timeout=180,
    )
    said = done.stdout + done.stderr
    assert "Traceback" not in said
    assert done.returncode == 0
    if "resolved nothing" in said:
        assert "no server for this language" in said
