"""A pytest plugin that runs each test on a few records, and says which could.

Loaded as `-p vesta.sampling`, into whatever interpreter runs the project's
tests — so nothing here imports beyond the standard library and pytest.

**The one change to how a test runs is the number of records it sees.**
`--sample N` keeps the first N parametrized cases of each test and sets
`VESTA_SAMPLE=N` for a test that walks its own data:

    rows = itertools.islice(rows, int(os.environ.get("VESTA_SAMPLE") or 0) or None)

**What is measured is whether a test reaches a verdict, not which one.** A
pass and an assertion that fails are the same answer here — the test ran on
the data and said something about it. An error anywhere else, in setup, in
collection, in the body before it could assert, means the test does not yet
run on this data, and needs changing before a full run can mean anything.

**It stops at the first test that cannot run**, not at the first that fails:
a negative verdict is a result, and stopping there would leave the rest
unsampled for no reason.
"""

from __future__ import annotations

import json
import os

import pytest

from vesta.sampled import COULD_NOT_RUN, SKIPPED, VERDICT

KEPT_OF_REASON = 400


def pytest_addoption(parser):
    parser.addoption(
        "--sample",
        type=int,
        default=0,
        help="run each test on at most N records, and stop at the first that cannot run",
    )


def _size(config) -> int:
    return int(config.getoption("--sample") or 0)


def pytest_configure(config):
    if _size(config) > 0:
        os.environ["VESTA_SAMPLE"] = str(_size(config))
        config._vesta_sampled = {}


def pytest_collection_modifyitems(session, config, items):
    n = _size(config)
    if n <= 0:
        return
    seen = {}
    kept, dropped = [], []
    for item in items:
        # One test, however many records it is parametrized over.
        key = (item.nodeid.split("[", 1)[0])
        seen[key] = seen.get(key, 0) + 1
        (kept if seen[key] <= n else dropped).append(item)
    if dropped:
        config.hook.pytest_deselected(items=dropped)
        items[:] = kept


def _record(config, nodeid: str, came_to: str, why: str = "") -> None:
    sampled = getattr(config, "_vesta_sampled", None)
    if sampled is None:
        return
    before = sampled.get(nodeid)
    # Setup, call and teardown each report; the worst of them stands.
    if before and before["came_to"] == COULD_NOT_RUN:
        return
    sampled[nodeid] = {"came_to": came_to, "why": why[:KEPT_OF_REASON]}
    # Written as it goes, so a sample cut off by a time limit still keeps
    # what it learned before it was.
    _write(config)


def _write(config) -> None:
    sampled = getattr(config, "_vesta_sampled", None)
    to = os.environ.get("VESTA_SAMPLED_TO")
    if sampled is None or not to:
        return
    try:
        with open(to + ".part", "w", encoding="utf-8") as kept:
            json.dump({"size": _size(config), "tests": sampled}, kept)
        os.replace(to + ".part", to)
    except OSError:
        pass


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()
    config = item.config
    if _size(config) <= 0:
        return

    if report.skipped:
        if call.when != "teardown":
            _record(config, item.nodeid, SKIPPED)
        return
    if report.passed:
        if call.when == "call":
            _record(config, item.nodeid, VERDICT)
        return

    # It failed. Only an assertion in the body is the test saying something.
    if call.when == "call" and call.excinfo is not None and call.excinfo.errisinstance(
        AssertionError
    ):
        _record(config, item.nodeid, VERDICT, "failed: " + str(call.excinfo.value))
        return

    why = f"{call.when}: "
    if call.excinfo is not None:
        why += f"{call.excinfo.typename}: {call.excinfo.value}"
    _record(config, item.nodeid, COULD_NOT_RUN, why)
    item.session.shouldstop = f"{item.nodeid} could not run on the sample"


_CONFIG = {}


@pytest.hookimpl(tryfirst=True)
def pytest_sessionstart(session):
    _CONFIG["config"] = session.config


def pytest_collectreport(report):
    # A file that cannot be collected cannot run at all, so it is recorded
    # against the file: no test inside it exists yet. Pytest itself stops
    # before running anything once collection has failed.
    config = _CONFIG.get("config")
    if report.failed and config is not None and _size(config) > 0:
        _record(config, report.nodeid, COULD_NOT_RUN, f"collection: {report.longreprtext}")


def pytest_sessionfinish(session, exitstatus):
    # Written even when nothing was recorded, so the run is known to have
    # happened rather than to have failed to start.
    _write(session.config)
