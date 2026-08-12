"""Vesta installing itself.

A plugin must not ask its user to install anything. Somebody who typed
`/plugin install vesta` has already said what they want; answering with
`pip install vesta` hands the work back to them, and most people stop there.

So the resolver builds its own environment on first use. These tests run it the
way the framework does — a copied plugin, a dead virtualenv inside it, and a
PATH holding nothing but the system directories.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent.parent

# Nothing on PATH but the system. No Homebrew, no virtualenv, no `vesta`.
BARE = {"PATH": "/usr/bin:/bin"}

# Building a runtime is slow enough that it is worth doing once for the whole
# module rather than per test.
pytestmark = pytest.mark.slow


def _plugin(at: Path) -> Path:
    """The plugin as the framework installs it: a copy, with a dead venv."""
    plugin = at / "plugin"
    plugin.mkdir(parents=True)
    for name in ("bin", "hooks", "commands", "vesta"):
        shutil.copytree(HERE / name, plugin / name)
    shutil.copy(HERE / "pyproject.toml", plugin / "pyproject.toml")
    shutil.copy(HERE / "README.md", plugin / "README.md")

    dead = plugin / ".venv" / "bin"
    dead.mkdir(parents=True)
    (dead / "python").symlink_to("/nonexistent/python")
    return plugin


def _env(at: Path, **rest) -> dict:
    return {
        **BARE,
        "HOME": str(at / "home"),
        "VESTA_HOME": str(at / "home" / ".vesta"),
        **rest,
    }


def _run(command, at, timeout=300, **rest):
    (at / "home").mkdir(exist_ok=True)
    return subprocess.run(
        command, capture_output=True, text=True, env=_env(at, **rest), timeout=timeout
    )


@pytest.fixture(scope="module")
def installed(tmp_path_factory):
    """A plugin that has built its own runtime, once, for the whole module."""
    at = tmp_path_factory.mktemp("selfinstall")
    plugin = _plugin(at)
    done = _run([str(plugin / "bin" / "vesta-python")], at)
    return at, plugin, done


def test_it_builds_its_own_runtime(installed):
    at, _, done = installed
    assert done.returncode == 0, done.stderr
    where = done.stdout.strip()
    assert where, "no interpreter was produced"
    assert str(at) in where, f"expected a runtime it built, got {where}"
    assert Path(where).is_file()


def test_the_runtime_can_run_the_sidecar(installed):
    """The whole point. `mcp` is an extra, and a Vesta whose tools are absent
    is not a working plugin."""
    at, _, done = installed
    python = done.stdout.strip()
    check = subprocess.run(
        [python, "-c", "import mcp, vesta.sidecar; print('ok')"],
        capture_output=True,
        text=True,
        env=_env(at),
        timeout=120,
    )
    assert check.stdout.strip() == "ok", check.stderr


def test_the_sidecar_answers_an_mcp_handshake(installed):
    import json

    at, plugin, _ = installed
    handshake = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "1"},
            },
        }
    )
    done = subprocess.run(
        [str(plugin / "bin" / "vesta-sidecar")],
        input=handshake + "\n",
        capture_output=True,
        text=True,
        env=_env(at),
        timeout=180,
    )
    assert done.stdout.strip(), done.stderr[-500:]
    answer = json.loads(done.stdout.splitlines()[0])
    assert answer["result"]["serverInfo"]["name"] == "vesta"


def test_a_command_answers_after_installing_itself(installed):
    at, plugin, _ = installed
    done = _run([str(plugin / "bin" / "vesta-run"), "guide"], at)
    assert done.returncode == 0, done.stderr
    assert "Vesta" in done.stdout
    assert "pip install" not in done.stdout


def test_the_second_call_does_not_rebuild(installed):
    """Building takes seconds. Doing it on every prompt would be unusable."""
    import time

    at, plugin, _ = installed
    started = time.monotonic()
    done = _run([str(plugin / "bin" / "vesta-python")], at)
    assert done.returncode == 0
    assert time.monotonic() - started < 5, "it rebuilt rather than reusing"


def test_nothing_is_built_when_told_not_to(tmp_path):
    """So a test, or a user who wants nothing written, can say so."""
    plugin = _plugin(tmp_path)
    done = _run(
        [str(plugin / "bin" / "vesta-python")], tmp_path, timeout=60, VESTA_NO_INSTALL="1"
    )
    assert done.returncode == 1
    assert done.stdout.strip() == ""
    assert not (tmp_path / "home" / ".vesta" / "runtime").exists()


def test_the_failure_names_the_real_cause(tmp_path):
    """macOS ships 3.9 and `mcp` needs 3.10. "Not installed" sends people
    looking in the wrong place."""
    plugin = _plugin(tmp_path)
    done = _run(
        [str(plugin / "bin" / "vesta-run"), "guide"],
        tmp_path,
        timeout=60,
        VESTA_NO_INSTALL="1",
    )
    assert "3.10" in done.stdout
    assert "command not found" not in done.stdout + done.stderr
    assert done.returncode == 0


def test_the_hook_stays_silent_while_nothing_is_built(tmp_path):
    """It runs on every prompt, including the ones before Vesta is ready."""
    plugin = _plugin(tmp_path)
    done = subprocess.run(
        [str(plugin / "hooks" / "notice.sh")],
        input='{"prompt":"x","cwd":"/tmp"}',
        capture_output=True,
        text=True,
        env=_env(tmp_path, VESTA_NO_INSTALL="1"),
        timeout=60,
    )
    assert done.stdout.strip() == ""
    assert done.stderr.strip() == ""
    assert done.returncode == 0


def test_a_newer_source_is_rebuilt(installed):
    """Vesta's code is copied into the runtime, so a plugin update would
    otherwise keep running the version installed months ago."""
    import time

    at, plugin, _ = installed
    stamp = at / "home" / ".vesta" / "runtime" / ".built-from"
    assert stamp.is_file(), "nothing recorded what the runtime was built from"

    (plugin / "vesta" / "cli.py").touch()
    started = time.monotonic()
    done = _run([str(plugin / "bin" / "vesta-python")], at)
    took = time.monotonic() - started

    assert done.returncode == 0, done.stderr
    assert took > 2, "it reused a runtime built from older code"

    # And is cached again afterwards, rather than rebuilding every call.
    started = time.monotonic()
    _run([str(plugin / "bin" / "vesta-python")], at)
    assert time.monotonic() - started < 5


def test_a_hook_never_builds_a_runtime(tmp_path):
    """The failure this covers: a first prompt hit the hook timeout because the
    hook was building the environment. Building is a slash command's job — a
    session that stalls on its first message has been made worse, whatever the
    hook might have gone on to say."""
    import time

    plugin = _plugin(tmp_path)
    (tmp_path / "home").mkdir(exist_ok=True)

    for hook in ("notice.sh", "inject.sh"):
        started = time.monotonic()
        done = subprocess.run(
            [str(plugin / "hooks" / hook)],
            input='{"prompt":"x","cwd":"/tmp"}',
            capture_output=True,
            text=True,
            env=_env(tmp_path),   # nothing built, and no VESTA_NO_INSTALL
            timeout=60,
        )
        took = time.monotonic() - started
        assert took < 8, f"{hook} took {took:.1f}s — it built something"
        assert done.returncode == 0
        assert done.stderr.strip() == ""
        assert not (tmp_path / "home" / ".vesta" / "runtime" / "bin").exists(), (
            f"{hook} built a runtime"
        )


def test_the_interpreter_is_remembered(installed):
    """Two hooks ask on every prompt, and each candidate is verified by running
    it. Remembering turns four interpreter starts into one."""
    at, plugin, _ = installed
    remembered = at / "home" / ".vesta" / "runtime" / ".interpreter"
    assert remembered.is_file(), "the answer was not kept"

    import time

    started = time.monotonic()
    done = _run([str(plugin / "bin" / "vesta-python")], at)
    assert done.returncode == 0
    assert time.monotonic() - started < 3


def test_a_remembered_interpreter_that_broke_is_not_trusted(installed):
    """A venv can be deleted between prompts. A remembered path is a hint."""
    at, plugin, _ = installed
    remembered = at / "home" / ".vesta" / "runtime" / ".interpreter"
    was = remembered.read_text(encoding="utf-8")
    remembered.write_text("/nonexistent/python\n", encoding="utf-8")
    try:
        done = _run([str(plugin / "bin" / "vesta-python")], at)
        assert done.returncode == 0, done.stderr
        assert "nonexistent" not in done.stdout
    finally:
        remembered.write_text(was, encoding="utf-8")
