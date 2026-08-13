"""Every way in, exercised from outside.

Four features shipped broken while their unit tests passed: capture, the spec
flow, change adjudication, and recording what was adjudicated. Every one was a
*seam* — an instruction in a skill nobody loaded, a function nobody called —
and every one had green tests on both sides of the gap.

Testing the parts does not test the wiring. So this file does the opposite of
the rest of the suite: it never imports a function to call it directly. It runs
hooks as subprocesses with the framework's payload on stdin, runs commands as
the shell line the framework runs, and asks the MCP server over its own
protocol. If a path works here it works for a user, and nothing else in this
file is worth trusting.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent.parent
INLINE = re.compile(r"!`([^`]+)`")


def _env(**rest) -> dict:
    from vesta.home import home

    return {
        **os.environ,
        "VESTA_HOME": str(home()),
        "VESTA_PYTHON": sys.executable,
        "CLAUDE_PLUGIN_ROOT": str(HERE),
        **rest,
    }


def _hook(name: str, payload: dict, **rest) -> dict:
    """Run a hook the way the framework does."""
    done = subprocess.run(
        [str(HERE / "hooks" / name)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=900,
        env=_env(**rest),
    )
    assert done.returncode == 0, f"{name}: {done.stderr[-400:]}"
    assert "Traceback" not in done.stderr, done.stderr[-400:]
    return json.loads(done.stdout) if done.stdout.strip() else {}


def _said(answered: dict) -> str:
    return (answered.get("hookSpecificOutput") or {}).get("additionalContext", "")


# ── Hooks: the paths that run without anybody asking ────────────────────────


@pytest.fixture
def fresh(tmp_path):
    """An empty project, as a user starting something has."""
    return tmp_path


def test_asking_for_something_to_be_built_reaches_the_agent(fresh):
    """Shipped broken. Everything installed correctly and the agent built the
    whole project with no contract, because the instruction lived in a skill
    whose description was about answering questions on existing code."""
    answered = _hook(
        "inject.sh",
        {
            "prompt": (
                "Build a command-line todo list.\n\nI want to add a task, see "
                "my tasks, mark one done, and delete one. Tasks should survive "
                "between runs."
            ),
            "cwd": str(fresh),
        },
    )
    said = _said(answered)
    assert "vesta-spec" in said
    assert "do not start building" in said.lower()


def test_stating_a_rule_reaches_the_agent(fresh):
    """Shipped broken, same cause."""
    said = _said(
        _hook(
            "inject.sh",
            {
                "prompt": (
                    "in this project every module must open with a docstring "
                    "saying what it is for. does resolve.py follow that?"
                ),
                "cwd": str(fresh),
            },
        )
    )
    assert "declare" in said


def test_a_change_to_agreed_behaviour_reaches_the_agent(fresh):
    """Shipped broken twice: the function was never called from the hook, and
    then the deciding half was called without the recording half."""
    from vesta.contract import Behaviour, Contract, keep, recall, sign

    keep(
        Contract(goal="todo", behaviours=[Behaviour(does="a user can file a task")]),
        fresh,
    )
    sign(fresh)

    said = _said(
        _hook("inject.sh", {"prompt": "actually make it multi-user", "cwd": str(fresh)})
    )
    assert "do not build it" in said.lower()
    # And the decision was recorded, not merely reached.
    assert recall(fresh).deferred == ["actually make it multi-user"]


def test_an_ordinary_prompt_costs_nothing(fresh):
    assert _hook("inject.sh", {"prompt": "hello", "cwd": str(fresh)}) == {}
    assert _hook("notice.sh", {"prompt": "hello", "cwd": str(fresh)}) == {}


def test_the_stop_hook_lets_a_session_end_when_nothing_is_driving(fresh):
    assert _hook("keep-going.sh", {"cwd": str(fresh)}) == {}


def test_the_stop_hook_blocks_while_work_remains(fresh):
    from vesta import driving
    from vesta.contract import Behaviour, Contract, keep, sign

    (fresh / "app.py").write_text('"""D."""\n\n\ndef w():\n    """I."""\n    return 1\n')
    keep(Contract(goal="x", behaviours=[Behaviour(does="a user can file a task")]), fresh)
    sign(fresh)
    driving.start(fresh)

    answered = _hook("keep-going.sh", {"cwd": str(fresh)})
    assert answered.get("decision") == "block"


# ── Commands: the shell line the framework runs ─────────────────────────────


def _command_line(path: Path) -> str:
    inline = INLINE.search(path.read_text(encoding="utf-8"))
    assert inline, f"{path.name} runs nothing"
    return inline.group(1)


@pytest.mark.parametrize(
    "path", sorted((HERE / "commands").glob("*.md")), ids=lambda p: p.stem
)
def test_every_command_answers_from_the_shell(path, tmp_path):
    """As the framework runs it: the literal line, with arguments substituted."""
    line = _command_line(path)
    line = re.sub(r"\$\{ARGUMENTS:\+--\$ARGUMENTS\}", "", line)
    line = re.sub(r"\$\{ARGUMENTS:-([^}]*)\}", r"\1", line)
    line = line.replace('"$ARGUMENTS"', '"a user can file a task"')
    line = line.replace("$ARGUMENTS", "app.py")

    done = subprocess.run(
        ["sh", "-c", line],
        capture_output=True,
        text=True,
        timeout=900,
        cwd=str(tmp_path),
        env=_env(),
    )
    said = done.stdout + done.stderr
    assert "Traceback" not in said, said[-500:]
    assert "command not found" not in said, said[-300:]
    assert "usage:" not in said.lower() or "vesta" in said.lower(), said[-300:]


# ── The server: over its own protocol ───────────────────────────────────────


def test_the_server_answers_an_initialize():
    done = subprocess.run(
        [str(HERE / "bin" / "vesta-sidecar")],
        input=json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "seam", "version": "1"},
                },
            }
        )
        + "\n",
        capture_output=True,
        text=True,
        timeout=900,
        env=_env(),
    )
    assert done.stdout.strip(), done.stderr[-400:]
    answered = json.loads(done.stdout.splitlines()[0])
    assert answered["result"]["serverInfo"]["name"] == "vesta"


def test_every_tool_the_server_offers_can_be_called():
    """A tool that lists and cannot be called is the same defect one layer up."""
    import asyncio
    import warnings

    warnings.filterwarnings("ignore")
    from vesta.sidecar import build_server

    tools = asyncio.run(build_server().list_tools())
    assert len(tools) >= 13
    for tool in tools:
        assert tool.description, f"{tool.name} says nothing about itself"
        assert tool.inputSchema is not None, f"{tool.name} has no schema"


# ── Agents: what routes to them ─────────────────────────────────────────────


@pytest.mark.parametrize(
    "path", sorted((HERE / "agents").glob("*.md")), ids=lambda p: p.stem
)
def test_every_agent_is_reachable(path):
    """An agent nothing names is an agent nobody runs."""
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---"), f"{path.name} has no frontmatter"

    front = text.split("---", 2)[1]
    assert "description:" in front, f"{path.name} has no description"

    name = path.stem
    named_by = subprocess.run(
        ["grep", "-rl", name, str(HERE / "vesta"), str(HERE / "skills")],
        capture_output=True,
        text=True,
    ).stdout
    assert named_by.strip(), f"nothing tells an agent to run {name}"


def test_a_feature_request_is_not_read_as_a_bug_report(fresh):
    """"see what I have spent, broken down by category" is a thing to build.
    Matching it on `broken` suppressed the whole contract flow on a brief that
    plainly asked for something new — found by driving a real project rather
    than by any unit test."""
    said = _said(
        _hook(
            "inject.sh",
            {
                "prompt": (
                    "Build an expense tracker I can use from the terminal.\n\n"
                    "I want to record an expense with an amount, a category, "
                    "and a note. I want to see what I have spent this month, "
                    "broken down by category. I want to export a month to CSV."
                ),
                "cwd": str(fresh),
            },
        )
    )
    assert "vesta-spec" in said


def test_an_actual_bug_report_still_asks_for_no_contract(fresh):
    (fresh / "storage.py").write_text("def x():\n    return 1\n", encoding="utf-8")
    for said in (
        "why is this test failing?",
        "fix the bug in storage.py",
        "the tests are failing after my change",
        "refactor the storage module",
    ):
        assert _said(_hook("inject.sh", {"prompt": said, "cwd": str(fresh)})) == "" or (
            "vesta-spec" not in _said(_hook("inject.sh", {"prompt": said, "cwd": str(fresh)}))
        )
