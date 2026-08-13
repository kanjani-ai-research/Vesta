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
    whose description was about answering questions on existing code.

    Only in full automation: as a companion this must stay silent, which
    `test_a_build_request_demands_no_contract_as_a_companion` holds it to."""
    from vesta import driving

    driving.start(fresh)
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
    from vesta import driving
    from vesta.contract import Behaviour, Contract, keep, recall, sign

    keep(
        Contract(goal="todo", behaviours=[Behaviour(does="a user can file a task")]),
        fresh,
    )
    sign(fresh)
    driving.start(fresh)

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
    from vesta import driving

    driving.start(fresh)
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


@pytest.mark.parametrize(
    "path", sorted((HERE / "agents").glob("*.md")), ids=lambda p: p.stem
)
def test_an_agent_is_told_how_to_reach_vesta(path):
    """The live failure: the spec agent ran, could not reach the CLI, and
    printed the contract into the chat instead of recording it. The user then
    agreed to something that did not exist.

    `vesta` is not on PATH — a plugin is installed by the framework, not by
    pip — so any instruction that says to run a bare `vesta …` is an
    instruction to fail silently."""
    text = path.read_text(encoding="utf-8")
    assert "CLAUDE_PLUGIN_ROOT" in text, f"{path.name} never says how to reach vesta"
    assert "not on PATH" in text


@pytest.mark.parametrize(
    "path", sorted((HERE / "agents").glob("*.md")), ids=lambda p: p.stem
)
def test_an_agent_does_not_claim_to_have_recorded_what_it_could_not(path):
    text = path.read_text(encoding="utf-8").lower()
    assert "do not carry on" in text


def test_agreeing_to_nothing_says_what_went_wrong(tmp_path):
    """"There is nothing to agree to" is true and useless. The user needs to
    know the spec agent failed to record, not merely that signing failed."""
    done = subprocess.run(
        ["sh", "-c", f"{HERE}/bin/vesta-run contract --root {tmp_path} --sign"],
        capture_output=True,
        text=True,
        timeout=300,
        env=_env(),
    )
    said = done.stdout + done.stderr
    assert "spec agent" in said
    assert "could not reach" in said


# ── Where things land when Vesta is a plugin, not a checkout ────────────────


def test_a_contract_lands_in_the_project_not_in_vesta(tmp_path):
    """It belongs to the project: it survives a cleared cache, diffs with the
    code, and a reader finds it where the work is."""
    project = tmp_path / "somebodys-project"
    project.mkdir()
    subprocess.run(
        [
            "sh",
            "-c",
            f'{HERE}/bin/vesta-run contract --root {project} '
            f'--goal "a thing" --does "a user can do it"',
        ],
        capture_output=True,
        text=True,
        timeout=300,
        env=_env(),
    )
    assert (project / "VESTA.md").is_file()
    assert (project / ".vesta-contract.json").is_file()


def test_derived_things_land_in_the_home_not_in_the_project(tmp_path):
    """A repository is not a place to leave a cache. Everything derived is
    keyed by project under one home, so a project can be deleted without
    orphaning anything and cleared without losing the project."""
    from vesta.home import home, kept_at

    project = tmp_path / "somebodys-project"
    for kind in ("graphs", "maps", "rules", "confirmed", "driving"):
        where = kept_at(project, kind)
        assert str(where).startswith(str(home())), f"{kind} escapes the home"
        assert "somebodys-project" in where.name, f"{kind} is not keyed by project"


def test_two_projects_of_the_same_name_do_not_collide(tmp_path):
    """The name is a readable prefix; the hash is the identity."""
    from vesta.home import kept_at

    one = kept_at(tmp_path / "a" / "vesta", "graphs")
    two = kept_at(tmp_path / "b" / "vesta", "graphs")
    assert one.name != two.name
    assert one.name.startswith("vesta-") and two.name.startswith("vesta-")


def test_the_same_project_by_two_paths_is_one_project(tmp_path):
    """`/tmp/x` and `/private/tmp/x` are the same directory on this platform,
    and treating them as two would give one repository two knowledge bases."""
    from vesta.home import kept_at

    project = tmp_path / "p"
    project.mkdir()
    assert kept_at(project, "graphs") == kept_at(str(project) + "/", "graphs")


def test_nothing_is_written_into_vestas_own_directory(tmp_path):
    """Running against somebody else's project must leave this one untouched."""
    project = tmp_path / "elsewhere"
    project.mkdir()
    (project / "app.py").write_text('"""A."""\n\n\ndef w():\n    return 1\n')

    before = {p: p.stat().st_mtime for p in HERE.glob("*.json")}
    subprocess.run(
        ["sh", "-c", f"{HERE}/bin/vesta-run shape --root {project}"],
        capture_output=True,
        text=True,
        timeout=600,
        env=_env(),
    )
    after = {p: p.stat().st_mtime for p in HERE.glob("*.json")}
    assert before == after


def test_agreeing_starts_the_loop(tmp_path):
    """Agreeing to a contract is the consent to build it.

    A live run agreed and then built with nothing enforcing the agreement,
    because driving was a second action nobody ran: the loop never started,
    the Stop hook never blocked, and the session ended having written no tests
    — exactly like the control it was meant to differ from."""
    from vesta import driving

    subprocess.run(
        [
            "sh",
            "-c",
            f'{HERE}/bin/vesta-run contract --root {tmp_path} '
            f'--goal "a thing" --does "a user can do it"',
        ],
        capture_output=True, text=True, timeout=300, env=_env(),
    )
    assert not driving.state(tmp_path).on

    done = subprocess.run(
        ["sh", "-c", f"{HERE}/bin/vesta-run contract --root {tmp_path} --sign"],
        capture_output=True, text=True, timeout=300, env=_env(),
    )
    assert done.returncode == 0, done.stderr
    assert driving.state(tmp_path).on, "agreeing did not start the loop"


def test_the_stop_hook_blocks_after_agreeing(tmp_path):
    """End to end: agree, and the session cannot end with nothing built."""
    subprocess.run(
        [
            "sh",
            "-c",
            f'{HERE}/bin/vesta-run contract --root {tmp_path} '
            f'--goal "a thing" --does "a user can do it" && '
            f"{HERE}/bin/vesta-run contract --root {tmp_path} --sign",
        ],
        capture_output=True, text=True, timeout=300, env=_env(),
    )
    answered = _hook("keep-going.sh", {"cwd": str(tmp_path)})
    assert answered.get("decision") == "block", answered
    assert "not built" in answered.get("reason", "")


# ── The two modes stay apart ────────────────────────────────────────────────
#
# As a companion Vesta answers questions and records what its user decides. It
# does not stop somebody who asked for a script and make them agree to a
# specification first. Everything that follows from a contract belongs to the
# mode they turned on, and to nobody else.


def test_a_build_request_demands_no_contract_as_a_companion(fresh):
    """The regression this covers: full-auto machinery reached a plain session,
    and "build me a script" was met with a specification to approve."""
    assert not __import__("vesta.driving", fromlist=["x"]).state(fresh).on
    said = _said(
        _hook(
            "inject.sh",
            {"prompt": "build me a script that renames files in bulk", "cwd": str(fresh)},
        )
    )
    assert said == "", f"companion mode asked for a contract: {said[:120]}"


def test_a_change_is_not_adjudicated_as_a_companion(fresh):
    """Refusing a change because it alters an agreed behaviour only makes
    sense where something was agreed to be driven toward."""
    from vesta.contract import Behaviour, Contract, keep, sign

    keep(Contract(goal="x", behaviours=[Behaviour(does="a user can file a task")]), fresh)
    sign(fresh)
    from vesta import driving

    driving.stop(fresh, "companion")

    said = _said(
        _hook("inject.sh", {"prompt": "actually make it multi-user", "cwd": str(fresh)})
    )
    assert "do not build it" not in said.lower()


def test_capturing_a_rule_works_as_a_companion(fresh):
    """The companion half must not have degraded. This is the feature that
    makes Vesta worth having without automation at all."""
    said = _said(
        _hook(
            "inject.sh",
            {
                "prompt": (
                    "in this project every module must open with a docstring "
                    "saying what it is for. does app.py follow that?"
                ),
                "cwd": str(fresh),
            },
        )
    )
    assert "declare" in said


def test_the_contract_flow_is_reached_once_driving_is_on(fresh):
    from vesta import driving

    driving.start(fresh)
    said = _said(
        _hook(
            "inject.sh",
            {"prompt": "build me a script that renames files in bulk", "cwd": str(fresh)},
        )
    )
    assert "vesta-spec" in said


def test_decision_management_never_fires_as_a_companion(fresh):
    """"Sure", refuse, defer — none of it belongs outside automation. Tested
    with a signed contract present and driving off, which is what a project
    looks like after somebody tried full auto and turned it back off."""
    from vesta import driving
    from vesta.contract import Behaviour, Contract, keep, sign

    keep(Contract(goal="x", behaviours=[Behaviour(does="a user can file a task")]), fresh)
    sign(fresh)
    driving.stop(fresh, "companion")

    for said in (
        "make it do a somersault",
        "actually make it multi-user",
        "add a convolutional neural network",
    ):
        answered = _said(_hook("inject.sh", {"prompt": said, "cwd": str(fresh)}))
        assert answered == "", f"companion mode adjudicated {said!r}: {answered[:100]}"


def test_the_stuck_signal_belongs_to_automation_only():
    """Detecting that a loop is going nowhere is a property of running a loop.
    A companion session has no loop, so nothing in its path may reach it."""
    import ast
    import inspect

    from vesta import inject, notice, sidecar

    for module in (inject, notice, sidecar):
        tree = ast.parse(inspect.getsource(module))
        imported = {
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module
        }
        assert "distance" not in imported, f"{module.__name__} reaches the loop metric"

    # And it is real where it belongs.
    from vesta.driving import STUCK_AFTER, State

    assert STUCK_AFTER >= 2
    assert hasattr(State, "stuck")


def test_a_companion_session_can_always_end(fresh):
    """The Stop hook is the only thing that can trap somebody. With driving
    off it must never say anything at all."""
    (fresh / "app.py").write_text('"""A."""\n\n\ndef w():\n    return 1\n')
    assert _hook("keep-going.sh", {"cwd": str(fresh)}) == {}
