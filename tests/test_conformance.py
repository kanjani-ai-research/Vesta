"""Vesta as a plugin: no tool may reach an external model.

A user installs this into an agentic framework that already has model access.
A tool that calls an API needs a key the user must hold, which defeats the
point — so this poisons `litellm` and `stroma` and calls every tool handler.
Any import of either raises, so a tool that reaches one fails loudly here
rather than silently at a user's machine.

Judgement did not disappear; it moved to the plugin agents, which run on the
host's inference and declare their own model.
"""

from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest


@pytest.fixture
def no_api(monkeypatch):
    """Make any external-model import explode."""
    for name in ("litellm", "stroma"):
        broken = types.ModuleType(name)

        def raise_it(attr, _name=name):
            raise AssertionError(f"{_name} reached from a tool")

        broken.__getattr__ = raise_it
        monkeypatch.setitem(sys.modules, name, broken)


@pytest.fixture
def repo() -> Path:
    return Path(__file__).resolve().parent.parent


def test_every_tool_answers_without_an_external_model(no_api, repo):
    from vesta.sidecar import (
        _decided,
        _defects,
        _does,
        _known,
        _means,
        _shape,
        _touches,
        _uses,
    )


    calls = [
        ("shape", lambda: _shape(repo)),
        ("uses", lambda: _uses("graph_for", repo)),
        ("touches", lambda: _touches(["vesta/graph.py"], repo, 2)),
        ("known", lambda: _known("for_", repo)),
        ("defects", lambda: _defects(repo, 2)),
        ("decided", lambda: _decided(repo, False, 2)),
        ("means", lambda: _means("graph_for", repo)),
        ("does", lambda: _does("impact analysis", repo)),
    ]
    for name, call in calls:
        assert call(), f"{name} returned nothing"


def test_no_module_in_the_graph_half_calls_a_model(repo):
    """A grep, because a test can only catch what it exercises.

    No exemptions. There were three — the modules that acquired literature and
    built knowledge bases — and they were removed rather than exempted: a
    plugin that needs its own search key and its own model is not a plugin, and
    a version reduced to what a plugin may do would duplicate what the host
    already does. What remains needs neither.
    """
    import re

    calling = re.compile(r"\b(build_extractor|analyze_async)\s*\(")
    offenders = []
    for path in sorted((repo / "vesta").glob("*.py")):
        for number, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if calling.search(line):
                offenders.append(f"{path.name}:{number}")
    assert not offenders, f"model calls in the graph half: {offenders}"


def test_an_unprepared_project_answers_at_once(no_api, tmp_path):
    """Preparation must never block a user's prompt."""
    import time

    from vesta.sidecar import _defects

    started = time.monotonic()
    said = _defects(tmp_path, 2)

    assert time.monotonic() - started < 2.0
    assert "background" in said or "nothing" in said.lower()


def test_the_server_actually_starts_as_a_process():
    """Not that it imports — that it runs.

    `build_server()` succeeded in tests for weeks while `main()` died on the
    first line, because a module deleted with the theory half was still
    imported there. Nothing noticed: a server that cannot start does not fail
    loudly, it is simply absent, and every tool goes missing with no message
    saying why. Only starting the real process catches that.
    """
    import json
    import subprocess
    import sys
    from pathlib import Path

    here = Path(__file__).resolve().parent.parent
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
        [sys.executable, "-m", "vesta.sidecar"],
        input=handshake + "\n",
        capture_output=True,
        text=True,
        timeout=90,
        cwd=str(here),
    )

    assert "Traceback" not in done.stderr, done.stderr[-800:]
    assert done.stdout.strip(), "the server answered nothing"

    answer = json.loads(done.stdout.splitlines()[0])
    assert answer["result"]["serverInfo"]["name"] == "vesta"


def test_the_sidecar_runner_finds_an_interpreter():
    """The command the plugin declares, run the way the framework runs it."""
    import subprocess
    import sys
    from pathlib import Path

    here = Path(__file__).resolve().parent.parent
    runner = here / "bin" / "vesta-sidecar"
    assert runner.is_file() and runner.stat().st_mode & 0o111, "runner is not executable"

    done = subprocess.run(
        [str(runner)],
        input="",
        capture_output=True,
        text=True,
        timeout=90,
        cwd=str(here),
        env={"PATH": "/usr/bin:/bin", "VESTA_PYTHON": sys.executable},
    )
    assert "no interpreter" not in done.stderr
    assert "Traceback" not in done.stderr, done.stderr[-500:]
