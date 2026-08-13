"""Scoring both arms of the trial by the same external standard.

**Nothing here uses Vesta.** Scoring the arm that ships Vesta with Vesta's own
measurements would be worthless — it would show that a tool agrees with itself.
Every number below comes from the standard library, the tests the arm wrote, or
the brief, and the same code runs against both directories.

**The brief is the standard, not either plugin's idea of done.** Each behaviour
in the brief is exercised by a script written before either arm ran, against
whatever interface the arm produced. An arm that builds something that does not
do what was asked scores zero for it however green its own tests are.

What is counted:

- *does it work* — each behaviour in the brief, exercised from outside
- *what it cost* — wall clock, turns, tokens, dollars, from the harness
- *what it is* — lines, definitions, tests, and whether the tests pass
- *what is wrong with it* — swallowed failures, bare excepts, unreachable code,
  found by reading the syntax rather than by asking anything
"""

from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional




def _python(where: Path) -> List[Path]:
    return [
        path
        for path in sorted(where.rglob("*.py"))
        if not any(p in (".venv", "venv", "__pycache__", ".git") for p in path.parts)
    ]


def counted(where: Path) -> Dict:
    """What the arm produced, by counting rather than judging."""
    files = _python(where)
    lines = 0
    definitions = 0
    tests = 0

    for path in files:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        lines += len([line for line in text.splitlines() if line.strip()])
        try:
            tree = ast.parse(text)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                definitions += 1
                if node.name.startswith("test_"):
                    tests += 1
            elif isinstance(node, ast.ClassDef):
                definitions += 1

    return {
        "files": len(files),
        "lines": lines,
        "definitions": definitions,
        "tests": tests,
    }


def defects(where: Path) -> Dict[str, int]:
    """Things wrong with the code, found by reading it.

    Deliberately the crudest possible versions — a bare `except:`, an `except`
    whose body is only `pass`, a function nothing in the tree calls. Anything
    subtler would be a judgement, and a judgement in a scoring script is a
    thumb on the scale.
    """
    found = {"bare_except": 0, "swallowed": 0, "unreferenced": 0, "unparseable": 0}

    called: set = set()
    defined: Dict[str, int] = {}

    for path in _python(where):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except (OSError, SyntaxError):
            found["unparseable"] += 1
            continue

        for node in ast.walk(tree):
            if isinstance(node, ast.ExceptHandler):
                if node.type is None:
                    found["bare_except"] += 1
                if len(node.body) == 1 and isinstance(node.body[0], ast.Pass):
                    found["swallowed"] += 1
            elif isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name):
                    called.add(node.func.id)
                elif isinstance(node.func, ast.Attribute):
                    called.add(node.func.attr)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if not node.name.startswith(("_", "test_")) and node.name != "main":
                    defined[node.name] = defined.get(node.name, 0) + 1

    found["unreferenced"] = len([n for n in defined if n not in called])
    return found


def tests_pass(where: Path) -> Optional[bool]:
    """Whether the arm's own tests pass. None where it wrote none."""
    if not any(where.rglob("test_*.py")) and not any(where.rglob("*_test.py")):
        return None
    try:
        done = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "--no-header"],
            cwd=str(where),
            capture_output=True,
            text=True,
            timeout=600,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if done.returncode == 5:
        return None
    return done.returncode == 0


def cost(report: Path) -> Dict:
    """What the run cost, from the harness rather than from either arm."""
    try:
        payload = json.loads(report.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}

    usage = payload.get("usage", {}) or {}
    return {
        "seconds": round(payload.get("duration_ms", 0) / 1000, 1),
        "turns": payload.get("num_turns", 0),
        "dollars": round(payload.get("total_cost_usd", 0) or 0, 4),
        "input_tokens": usage.get("input_tokens", 0),
        "output_tokens": usage.get("output_tokens", 0),
        "cache_read": usage.get("cache_read_input_tokens", 0),
    }


def score(where: Path, report: Optional[Path] = None) -> Dict:
    """Everything about one arm."""
    found = {
        "where": str(where),
        "built": counted(where),
        "defects": defects(where),
        "tests_pass": tests_pass(where),
    }
    if report is not None and report.is_file():
        found["cost"] = cost(report)
    return found


def main(argv: Optional[List[str]] = None) -> int:
    argv = list(argv or sys.argv[1:])
    if not argv:
        print("usage: score.py <directory> [report.json]")
        return 1

    where = Path(argv[0]).expanduser().resolve()
    report = Path(argv[1]).expanduser().resolve() if len(argv) > 1 else None
    print(json.dumps(score(where, report), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
