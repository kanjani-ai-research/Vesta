"""Whether what was built does what the brief asked for.

Written before either arm ran, so neither could be built against it. This is
the standard that matters: an arm whose own tests are green and whose product
cannot add a task has not built a todo list.

**Exercised from outside, through whatever interface the arm produced.** The
brief did not say what the commands should be called, so this tries the obvious
spellings and reports what it could not drive rather than failing the arm for
choosing different words. A behaviour that cannot be exercised at all is scored
as not built, and the reason is printed so a reader can check the judgement.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# How a todo list is usually spelled. Tried in turn; the first that works is
# the arm's interface.
ADD = ["add", "new", "create", "a"]
LIST = ["list", "ls", "show", "all", ""]
DONE = ["done", "complete", "check", "finish"]
DELETE = ["delete", "remove", "rm", "del"]

TIMEOUT = 30


def _entry(where: Path) -> Optional[List[str]]:
    """How to run the thing, whatever the arm called it."""
    for name in ("todo.py", "main.py", "cli.py", "app.py", "todo/__main__.py"):
        if (where / name).is_file():
            return [sys.executable, str(where / name)]
    # A package with a __main__, or a single script with any name.
    scripts = [
        p
        for p in sorted(where.glob("*.py"))
        if not p.name.startswith("test_") and p.name != "setup.py"
    ]
    if len(scripts) == 1:
        return [sys.executable, str(scripts[0])]
    for path in scripts:
        try:
            if "__main__" in path.read_text(encoding="utf-8", errors="replace"):
                return [sys.executable, str(path)]
        except OSError:
            continue
    return None


def _run(entry: List[str], where: Path, *args: str) -> Tuple[int, str]:
    try:
        done = subprocess.run(
            entry + [a for a in args if a != ""],
            cwd=str(where),
            capture_output=True,
            text=True,
            timeout=TIMEOUT,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return 1, f"could not run: {exc}"
    return done.returncode, (done.stdout + done.stderr)


def _first_that_works(
    entry: List[str], where: Path, verbs: List[str], *rest: str
) -> Tuple[Optional[str], str]:
    """The verb this arm uses, and what it said."""
    for verb in verbs:
        code, said = _run(entry, where, verb, *rest)
        if code == 0:
            return verb, said
    return None, said if verbs else ""


def probe(where: Path) -> Dict:
    """Exercise every behaviour the brief asked for."""
    found: Dict[str, object] = {}
    entry = _entry(where)
    if entry is None:
        return {"runnable": False, "why": "nothing to run"}

    found["runnable"] = True
    found["entry"] = entry[-1].replace(str(where) + "/", "")

    # Add a task.
    add, said = _first_that_works(entry, where, ADD, "buy milk")
    found["add a task"] = add is not None
    found["_add_verb"] = add or ""

    # List it back. The task must appear in what is printed.
    listed, said = _first_that_works(entry, where, LIST)
    found["list tasks"] = listed is not None and "buy milk" in said
    found["_list_verb"] = listed or ""

    # Survive between runs: a second process must still see it.
    _, again = _first_that_works(entry, where, LIST)
    found["tasks survive between runs"] = "buy milk" in again

    # Tag a task, then filter by the tag. Tried both as a flag and as an
    # argument, since the brief did not say.
    # Tagging counts only when the tag comes back out. An arm that accepts the
    # argument and drops it exits zero, which would score as working — the
    # exact false positive that makes a benchmark worthless.
    tagged = False
    for shape in (
        (add or "add", "walk dog", "--tag", "home"),
        (add or "add", "walk dog", "-t", "home"),
        (add or "add", "walk dog", "home"),
        ("tag", "2", "home"),
    ):
        code, _ = _run(entry, where, *shape)
        if code != 0:
            continue
        _, shown = _first_that_works(entry, where, LIST)
        if "home" in shown:
            tagged = True
            break
        # Or it is only shown when asked for by tag.
        for asking in ((listed or "list", "--tag", "home"), ("filter", "home")):
            code, said = _run(entry, where, *asking)
            if code == 0 and "walk dog" in said:
                tagged = True
                break
        if tagged:
            break
    found["tag a task"] = tagged

    filtered = False
    for shape in (
        (listed or "list", "--tag", "home"),
        (listed or "list", "-t", "home"),
        (listed or "list", "home"),
        ("filter", "home"),
    ):
        code, said = _run(entry, where, *shape)
        if code == 0 and "walk dog" in said and "buy milk" not in said:
            filtered = True
            break
    found["filter by tag"] = filtered

    # Mark done, and delete. Tried against the first task by index and by name.
    done_verb = None
    for verb in DONE:
        for which in ("1", "buy milk"):
            code, _ = _run(entry, where, verb, which)
            if code == 0:
                done_verb = verb
                break
        if done_verb:
            break
    found["mark a task done"] = done_verb is not None

    deleted = False
    for verb in DELETE:
        for which in ("1", "buy milk"):
            code, _ = _run(entry, where, verb, which)
            if code == 0:
                _, after = _first_that_works(entry, where, LIST)
                if "buy milk" not in after:
                    deleted = True
                    break
        if deleted:
            break
    found["delete a task"] = deleted

    wanted = [
        "add a task",
        "list tasks",
        "mark a task done",
        "delete a task",
        "tasks survive between runs",
        "tag a task",
        "filter by tag",
    ]
    found["works"] = sum(1 for w in wanted if found.get(w))
    found["of"] = len(wanted)
    return found


def main(argv: Optional[List[str]] = None) -> int:
    argv = list(argv or sys.argv[1:])
    if not argv:
        print("usage: probe.py <directory>")
        return 1
    print(json.dumps(probe(Path(argv[0]).expanduser().resolve()), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
