"""Whether the tests have been shown to run on the data, before all of them do.

A full run of a suite that has never run on its data is a long way to find out
that a fixture points at a file that moved. It costs the whole suite's time
and reports one problem — or worse, reports the suite as failed when no test
in it ever got far enough to judge anything. So a test is first run on one or
a few records (`vesta.sampling`), and only once every test file has reached a
verdict there is a full run worth its time.

**The measure is whether a test can run, not whether it passes.** A test that
runs on the sample and fails its assertion has been validated: it says
something about the data. A test that errors before it can say anything has
not, and the answer is to change the test, not to run more of it.

**Kept per test file, against the file's contents.** Editing a test puts it
back to unsampled; nothing else does, because nothing else can be known.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence

logger = logging.getLogger("vesta.sampled")

# What a sampled test came to. Defined here rather than beside the pytest
# plugin that records them: Vesta's own runtime has no pytest, and importing
# the plugin to read three names would need it.
VERDICT = "verdict"            # it ran and passed or failed an assertion
COULD_NOT_RUN = "could not run"
SKIPPED = "skipped"            # no verdict, and no fault of the test's either

# Enough records to show a test can run on its data, few enough to be quick.
RECORDS = 3

# A sample that takes longer than this is not a sample.
WITHIN = 300


def _where(repo: Path | str) -> Path:
    from .home import kept_at

    return kept_at(repo, "sampled")


def test_files(repo: Path | str) -> List[Path]:
    """The project's test files, as pytest would find them by default."""
    from .home import walk

    root = Path(repo).expanduser().resolve()
    return [
        p for p in walk(root, ".py")
        if p.name.startswith("test_") or p.name.endswith("_test.py")
    ]


def _digest(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()[:16]
    except OSError:
        return ""


def _recorded(repo: Path | str) -> Dict[str, dict]:
    path = _where(repo)
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


@dataclass
class Standing:
    """Where every test file stands against its data."""

    validated: List[str] = field(default_factory=list)
    could_not_run: Dict[str, str] = field(default_factory=dict)  # file → why
    unsampled: List[str] = field(default_factory=list)
    failing: Dict[str, str] = field(default_factory=dict)  # validated, with a negative verdict

    @property
    def ready(self) -> bool:
        """Whether a full run is worth its time."""
        return not self.could_not_run and not self.unsampled

    def describe(self) -> str:
        lines = []
        if self.could_not_run:
            lines.append(
                f"{len(self.could_not_run)} test file(s) do not yet run on the "
                "data — change the test, not the amount of it:"
            )
            lines += [f"  · {f}: {why}" for f, why in sorted(self.could_not_run.items())]
        if self.unsampled:
            lines.append(f"{len(self.unsampled)} test file(s) not yet run on a sample:")
            lines += [f"  · {f}" for f in self.unsampled[:12]]
            if len(self.unsampled) > 12:
                lines.append(f"  · …and {len(self.unsampled) - 12} more")
        if self.validated:
            lines.append(
                f"{len(self.validated)} test file(s) run on the sample"
                + (f", {len(self.failing)} with a failing verdict" if self.failing else "")
                + "."
            )
        for f, why in sorted(self.failing.items()):
            lines.append(f"  · {f}: {why}")
        lines.append(
            "A full run is warranted."
            if self.ready
            else "Not yet worth a full run: `vesta sample` until every file has run."
        )
        return "\n".join(lines)


def standing(repo: Path | str) -> Standing:
    """Where the tests stand against their data, from what has been kept."""
    root = Path(repo).expanduser().resolve()
    kept = _recorded(root)
    kept.pop(RUNNER, None)
    here = Standing()
    for path in test_files(root):
        name = str(path.relative_to(root))
        entry = kept.get(name)
        if not entry or entry.get("digest") != _digest(path):
            here.unsampled.append(name)
        elif entry.get("came_to") == COULD_NOT_RUN:
            here.could_not_run[name] = entry.get("why", "")
        else:
            here.validated.append(name)
            if entry.get("failing"):
                here.failing[name] = entry["failing"]
    return here


def ready(repo: Path | str) -> bool:
    try:
        return standing(repo).ready
    except Exception as exc:  # noqa: BLE001 - unknown is not ready
        logger.info("could not read where the tests stand: %s", exc)
        return False


# Kept beside the files: why the last attempt could not start a runner at all.
RUNNER = "__runner__"


def cannot_sample(repo: Path | str) -> str:
    """Why sampling cannot start here, if it could not last time.

    A project Vesta cannot sample is not one whose full runs it should hold
    back: that would be blocking work over Vesta's own limits.
    """
    return str(_recorded(repo).get(RUNNER) or "")


def _runner(repo: Path | str, why: str) -> None:
    kept = _recorded(repo)
    if why:
        kept[RUNNER] = why
    else:
        kept.pop(RUNNER, None)
    path = _where(repo)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(kept), encoding="utf-8")


def _file_of(nodeid: str) -> str:
    return nodeid.split("::", 1)[0]


def keep(
    repo: Path | str, tests: Dict[str, dict], covered: Sequence[str] = ()
) -> None:
    """Fold one sample's results into what is kept, file by file.

    `covered` names the test files a run finished over. One of them that
    reported nothing, in a run nothing stopped, has no tests to run — and
    holding every full run back for it would be holding it back for ever.
    """
    root = Path(repo).expanduser().resolve()
    kept = _recorded(root)
    by_file: Dict[str, List[dict]] = {}
    for nodeid, said in tests.items():
        by_file.setdefault(_file_of(nodeid), []).append({**said, "nodeid": nodeid})

    for name, results in by_file.items():
        path = root / name
        if not path.is_file():
            continue
        broken = [r for r in results if r["came_to"] == COULD_NOT_RUN]
        reached = [r for r in results if r["came_to"] == VERDICT]
        if broken:
            first = broken[0]
            test = first["nodeid"].split("::", 1)[1] if "::" in first["nodeid"] else ""
            lines = first["why"].strip().splitlines()
            why = lines[-1] if lines else ""
            entry = {
                "came_to": COULD_NOT_RUN,
                "why": " — ".join(p for p in (test, why) if p),
            }
        elif reached:
            failed = [r for r in reached if r.get("why")]
            entry = {"came_to": VERDICT}
            if failed:
                entry["failing"] = f"{len(failed)} test(s) failed on the sample, first {failed[0]['nodeid'].split('::', 1)[-1]}"
        elif all(r["came_to"] == SKIPPED for r in results):
            # Nothing ran, and nothing is wrong with the test: a skip on this
            # platform should not hold every full run back for ever.
            entry = {"came_to": SKIPPED}
        else:
            continue
        entry["digest"] = _digest(path)
        kept[name] = entry

    if not any(t["came_to"] == COULD_NOT_RUN for t in tests.values()):
        for name in covered:
            if name not in by_file and (root / name).is_file():
                kept[name] = {"came_to": SKIPPED, "digest": _digest(root / name)}

    path = _where(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(kept), encoding="utf-8")


def _partial(to: str) -> Optional[Dict[str, dict]]:
    try:
        return json.loads(Path(to).read_text(encoding="utf-8"))["tests"]
    except (OSError, ValueError, KeyError):
        return None


@dataclass
class Sampled:
    """What one sample run came to."""

    ran: bool
    said: str = ""
    tests: Dict[str, dict] = field(default_factory=dict)


def run(
    repo: Path | str, paths: Sequence[str] = (), records: int = RECORDS
) -> Sampled:
    """Run the tests on a few records each, and keep what they came to."""
    root = Path(repo).expanduser().resolve()
    # `vesta.sampling` must import in the project's interpreter, which is not
    # necessarily the one running Vesta.
    package = str(Path(__file__).resolve().parent.parent)
    env = {**os.environ, "PYTHONPATH": os.pathsep.join(
        p for p in (package, os.environ.get("PYTHONPATH", "")) if p
    )}

    every = [str(p.relative_to(root)) for p in test_files(root)]
    if paths:
        asked = [str((root / p).resolve().relative_to(root)) for p in paths]
        covered = [f for f in every if any(f == a or f.startswith(a.rstrip("/") + "/") for a in asked)]
    else:
        # Only what has not yet been shown to run: a sample cut off by its
        # time limit carries on from where it stopped rather than starting
        # again, which on a suite that is slow per test rather than per
        # record is the only way it ever finishes.
        here = standing(root)
        covered = sorted(set(here.unsampled) | set(here.could_not_run))
        if not covered:
            return Sampled(ran=True)
        if len(covered) < len(every):
            paths = covered
    done = _sample(root, paths, records, env, covered)
    _runner(root, "" if done.ran else done.said)
    return done


def _sample(
    root: Path, paths: Sequence[str], records: int, env: dict, covered: Sequence[str]
) -> Sampled:
    with tempfile.TemporaryDirectory() as scratch:
        to = os.path.join(scratch, "sampled.json")
        env["VESTA_SAMPLED_TO"] = to
        for interpreter in (sys.executable, "python3", "python"):
            try:
                done = subprocess.run(
                    [interpreter, "-m", "pytest", "-q", "--no-header",
                     "-p", "vesta.sampling", "--sample", str(records), *paths],
                    cwd=str(root), capture_output=True, text=True,
                    timeout=WITHIN, env=env,
                )
            except subprocess.TimeoutExpired:
                tests = _partial(to)
                if tests is None:
                    return Sampled(ran=False, said=f"the sample did not finish in {WITHIN}s")
                # The file it was in the middle of has not finished, so none
                # of it is kept: part of a file is not the file.
                if tests:
                    unfinished = _file_of(list(tests)[-1])
                    tests = {n: t for n, t in tests.items() if _file_of(n) != unfinished}
                keep(root, tests)
                return Sampled(
                    ran=True, tests=tests, said=(
                        f"stopped at the {WITHIN}s limit with {len(tests)} test(s) "
                        "sampled; run again to carry on"
                    ),
                )
            except OSError as exc:
                logger.info("could not sample with %s: %s", interpreter, exc)
                continue
            if "No module named pytest" in done.stderr:
                continue
            tests = _partial(to)
            if tests is None:
                # The plugin never ran: the runner itself is the problem.
                tail = (done.stdout + done.stderr).strip().splitlines()[-5:]
                return Sampled(ran=False, said="\n".join(tail) or "pytest did not start")
            keep(root, tests, covered)
            return Sampled(ran=True, tests=tests)
    return Sampled(ran=False, said="no interpreter here has pytest")
