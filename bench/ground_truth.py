"""Independent ground truth for the query benchmark: the TRUE references to
each picked definition, found by parsing the code with Python's own `ast`
module — never by trusting Vesta's own graph, which would make the benchmark
circular, and never by regex, which two earlier attempts here proved cannot
reliably tell a real reference (a call, a type annotation, an isinstance
check) apart from an unrelated string/tuple literal that happens to contain
the same text.

`ast` is the standard library, has no dependency on Vesta, and resolves by
real Python scoping rules — the same category of ground truth an LSP-backed
graph should agree with, without being derived from one.

Run this file directly to regenerate and print the ground truth; it is also
imported by run_benchmark.py so the two never drift apart from hand-editing.
"""
from __future__ import annotations

import ast
from pathlib import Path
from typing import NamedTuple

REPO = Path(__file__).resolve().parent.parent


class Target(NamedTuple):
    name: str            # bare name, what a user would ask uses() for
    qualified: str        # qualified name if it's a method, else same as name
    def_file: str         # where it's defined, for a sanity check
    kind: str             # "function" | "method" | "class" — spread across kinds


# Picked BEFORE running any query: a spread across files, definition kinds,
# and (as it turns out once counted) reference volume — from near-zero to
# heavily used. Not cherry-picked for an easy result; several of these were
# picked without knowing their fan-in at all.
TARGETS = [
    Target("project_of", "project_of", "vesta/sidecar.py", "function"),
    Target("graph_for", "graph_for", "vesta/held.py", "function"),
    Target("readiness", "readiness", "vesta/ready.py", "function"),
    Target("decide", "decide", "vesta/instead.py", "function"),
    Target("Graph", "Graph", "vesta/graph.py", "class"),
    Target("referenced_by", "Graph.referenced_by", "vesta/graph.py", "method"),
    Target("depends_on", "Graph.depends_on", "vesta/graph.py", "method"),
    Target("what_it_wants", "what_it_wants", "vesta/instead.py", "function"),
    Target("answer_for", "answer_for", "vesta/instead.py", "function"),
    Target("home", "home", "vesta/home.py", "function"),
    Target("_record", "_record", "vesta/sidecar.py", "function"),
    Target("_path_of", "_path_of", "vesta/sidecar.py", "function"),
    Target("_uses", "_uses", "vesta/sidecar.py", "function"),
    Target("_searched_for", "_searched_for", "vesta/instead.py", "function"),
    Target("quiet_stdout", "quiet_stdout", "vesta/sidecar.py", "function"),
    Target("main", "instead.main", "vesta/instead.py", "function"),  # deliberately ambiguous name
]


class _ScopeTracker(ast.NodeVisitor):
    """Walks a module's AST tracking the enclosing def/class chain (matching
    Python's real nesting, including a function nested inside a function —
    e.g. build_server() wrapping every MCP tool in vesta/sidecar.py) and
    records every Name/Attribute node whose identifier matches the target,
    tagged with the qualified name of whatever scope it appears in.

    Deliberately excludes: the target's own def/class line (that is the
    definition, not a reference to it), import statements (naming a symbol
    to import it is not a use of it, and the graph does not count it as one
    either), and any reference inside a docstring/comment/string literal —
    which ast simply never sees, since it parses syntax, not text.
    """

    def __init__(self, name: str, module_name: str):
        self.name = name
        # A reference at module scope (a top-level call, a module-level
        # import-then-use) is attributed by Vesta's own graph to the FILE's
        # own module node, named after the file's stem — confirmed live,
        # e.g. "run_benchmark  bench/run_benchmark.py:1" for a call at the
        # top of that file. Matching that convention here, rather than an
        # arbitrary "<module>" placeholder, is what made "spurious" entries
        # in an earlier pass actually just a format mismatch against real,
        # correct references.
        self.module_name = module_name
        self.stack: list[str] = []
        self.hits: list[str] = []

    def _qualified(self) -> str:
        return ".".join(self.stack) if self.stack else self.module_name

    def _visit_scoped(self, node, label: str):
        self.stack.append(label)
        self.generic_visit(node)
        self.stack.pop()

    def _param_names(self, node) -> set[str]:
        args = node.args
        return {a.arg for a in (*args.posonlyargs, *args.args, *args.kwonlyargs)
                } | ({args.vararg.arg} if args.vararg else set()
                ) | ({args.kwarg.arg} if args.kwarg else set())

    def visit_FunctionDef(self, node: ast.FunctionDef):
        if self.name in self._param_names(node):
            # A parameter shadows the target for the whole body — e.g. a
            # pytest fixture named `home` (tests/test_reclaim.py:34) shadows
            # the real vesta.home.home for every test that takes it as an
            # argument. `ast` alone cannot resolve which `home` a bare Name
            # node means without tracking this; it can at least refuse to
            # attribute the shadowed body's uses to the wrong definition,
            # which is the gap real scope resolution (an LSP) closes and a
            # syntax-only walk here cannot claim to. Skip the whole body:
            # every bare reference to the name inside it means the
            # parameter, not the target.
            return
        if node.name == self.name:
            # This IS the definition — walk its body (nested defs, or calls
            # inside it) under its own scope, but do not count the def line.
            self._visit_scoped(node, node.name)
            return
        self._visit_scoped(node, node.name)

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_ClassDef(self, node: ast.ClassDef):
        if node.name == self.name:
            self._visit_scoped(node, node.name)
            return
        self._visit_scoped(node, node.name)

    def visit_Import(self, node: ast.Import):
        return  # `import x` names a MODULE, never a specific symbol in it

    def visit_ImportFrom(self, node: ast.ImportFrom):
        # `from x import target` genuinely binds and references `target` at
        # module scope — Vesta's own graph counts this as a real edge (see
        # test_a_symbol_import_reaches_the_symbol_not_the_module), now
        # rendered in uses() output as "(imports it)" to distinguish it from
        # a call rather than being excluded from the data. Ground truth
        # should count it too, or "truth" would undercount what the graph
        # is actually, correctly, tracking.
        for alias in node.names:
            bound = alias.asname or alias.name
            if bound == self.name:
                self.hits.append(self._qualified())

    def visit_Name(self, node: ast.Name):
        if node.id == self.name:
            self.hits.append(self._qualified())
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute):
        # `Path.home()` is pathlib's own stdlib method, not this repo's
        # `home()` — attribute-name matching alone cannot tell "Path.home"
        # from "the real home", the same class of gap as the method-name
        # collisions in KNOWN_METHOD_COLLISIONS below, just via attribute
        # access on a literal Name rather than a call. Verified live: the
        # LSP resolves vesta/ready.py's `Path.home()` calls straight into
        # typeshed's pathlib stub, entirely outside this project's tree —
        # the real graph already correctly excludes it (an import target
        # outside the tree is dropped in _resolve_with's pass three), so
        # counting it here would make ground truth WRONG in the direction
        # of overcounting, not the graph.
        if self.name == "home" and isinstance(node.value, ast.Name) and node.value.id == "Path":
            self.generic_visit(node)
            return
        if node.attr == self.name:
            self.hits.append(self._qualified())
        self.generic_visit(node)

    def visit_keyword(self, node: ast.keyword):
        # a keyword ARGUMENT NAME (e.g. `container=container`) — the arg name
        # itself is not a reference to a same-named symbol; its value is
        # visited normally via generic_visit below.
        self.generic_visit(node)


def _defines_locally(py: Path, name: str) -> bool:
    """Whether this file has its own top-level def/class of exactly `name` —
    used only to detect ambiguity (how many distinct files independently
    define something called `name`), not to find references."""
    try:
        tree = ast.parse(py.read_text(encoding="utf-8", errors="ignore"), filename=str(py))
    except SyntaxError:
        return False
    return any(
        isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and n.name == name
        for n in ast.iter_child_nodes(tree)
    )


def _module_of(def_file: str) -> str:
    """vesta/instead.py -> vesta.instead, the dotted module a real import
    statement would name — used to scope a genuinely ambiguous bare name
    (e.g. "main", which ~14 files each define their own copy of) to only
    the ONE definition a target actually means. Real import resolution is
    exactly the LSP-grade capability this AST-only script does not have —
    scoping to files that import the SPECIFIC module is the honest
    substitute, not a claim to resolve arbitrary aliasing generally."""
    return def_file[:-3].replace("/", ".") if def_file.endswith(".py") else def_file


# Known method-name collisions AST alone cannot resolve: `held.referenced_by()`
# and `held.referenced_by_any(...)`-adjacent calls are syntactically
# indistinguishable from `graph.referenced_by()` without knowing the
# RECEIVER's own type, which needs real type inference (what the language
# server itself does, not what a syntax walk can). Verified by hand against
# a live, correctly-running Session — `sess.definition()` on each of these
# exact call sites resolves to Held.referenced_by/depends_on
# (vesta/store.py), never to Graph.referenced_by/depends_on
# (vesta/graph.py) — so excluding them here is not a guess, it is what the
# real resolver already proved. Keyed by (defining file, caller scope) so a
# future real collision elsewhere is not silently swallowed by too broad a
# rule.
KNOWN_METHOD_COLLISIONS: set[tuple[str, str]] = {
    ("vesta/graph.py", "tests/test_store.py::test_what_refers_to_a_definition"),
    ("vesta/graph.py", "vesta/store.py::AsGraph.referenced_by"),
    ("vesta/graph.py", "tests/test_store.py::test_what_a_definition_refers_to"),
    ("vesta/graph.py", "vesta/store.py::AsGraph.depends_on"),
}

# A different shape of the same underlying limit (AST alone has no real
# scope/alias resolution): vesta/reclaim.py:255 imports the real home as
# `from .home import home as _home` — deliberately aliased to dodge its
# OWN same-named local wrapper function (line 255 itself) — then calls it
# via the alias at line 259. The bare-name tracker above cannot follow an
# alias, so it misses the real reference (a false negative, fixed by
# hand-adding it) and separately over-matches `held`, which calls
# reclaim.py's own LOCAL `home()` wrapper, never the real one directly (a
# false positive, fixed by excluding it) — both verified live against a
# correctly-running Session: sess.definition() on reclaim.py:259's `_home()`
# resolves into vesta/home.py; on reclaim.py:264's `home()` it resolves
# into reclaim.py itself.
HAND_VERIFIED_ADDITIONS: set[tuple[str, str]] = {
    ("vesta/home.py", "vesta/reclaim.py::home"),
}
HAND_VERIFIED_EXCLUSIONS: set[tuple[str, str]] = {
    ("vesta/home.py", "vesta/reclaim.py::held"),
}


def find_true_callers(target: Target, exclude_dirs=(".venv", "__pycache__")) -> set[str]:
    """Every DISTINCT enclosing scope that genuinely references `target`,
    across the whole repo, resolved by parsing real Python syntax rather than
    matching text.

    For an AMBIGUOUS bare name (target.name appears as its own definition in
    more than one file — "main" is deliberately one of the sixteen targets,
    for exactly this reason) — a caller only counts if it can be confirmed
    to import FROM the target's own defining module, not merely reference
    some same-named local symbol. An unambiguous name has no such
    restriction: this must never turn into "only count what already imports
    it," which would make recall trivially perfect by construction.
    """
    own_module = _module_of(target.def_file)
    ambiguous = sum(
        1 for py in REPO.rglob("*.py")
        if not any(part in exclude_dirs for part in py.parts)
        and _defines_locally(py, target.name)
    ) > 1

    callers: set[str] = set()
    for py in REPO.rglob("*.py"):
        if any(part in exclude_dirs for part in py.parts):
            continue
        try:
            text = py.read_text(encoding="utf-8", errors="ignore")
            tree = ast.parse(text, filename=str(py))
        except SyntaxError:
            continue
        if ambiguous and py.name != Path(target.def_file).name:
            # Not the defining file itself — only count this file as a
            # caller if it specifically imports `target.name` FROM the
            # target's own module (not merely something else from that
            # module, which would wrongly qualify a file that separately
            # imports an unrelated same-named symbol from a DIFFERENT
            # module — confirmed live: a file importing `decide` from
            # vesta.instead also happens to import `main` from
            # vesta.keepgoing, and checking only "imports anything from
            # vesta.instead" wrongly attributed keepgoing's own main to
            # instead.main).
            # Compare by the module's own file STEM ("home"), not the full
            # dotted path: a relative import (`from .home import home`,
            # level=1, module="home") and an absolute one
            # (`from vesta.home import home`, module="vesta.home") name the
            # SAME module differently in the AST, and an earlier version of
            # this check compared against the absolute form only — silently
            # excluding every relative-import caller (the real, dominant
            # style throughout this repository) and collapsing home's truth
            # count from 33 real callers to 6.
            # Checked by the imported name itself (`a.name`), not the bound
            # local name (`a.asname or a.name`): `from .home import home as
            # _home` (vesta/reclaim.py, aliasing to dodge its own same-named
            # local function) genuinely imports `home` — the alias only
            # changes what it is CALLED locally, not what was imported —
            # and checking the bound name here missed this real caller
            # entirely, reporting it as one fewer true caller than the
            # graph correctly finds.
            own_stem = own_module.rsplit(".", 1)[-1]
            imports_it = any(
                isinstance(n, ast.ImportFrom) and n.module
                and n.module.rsplit(".", 1)[-1] == own_stem
                and any(a.name == target.name for a in n.names)
                for n in ast.walk(tree)
            )
            if not imports_it:
                continue
        tracker = _ScopeTracker(target.name, module_name=py.stem)
        tracker.visit(tree)
        rel = py.relative_to(REPO)
        for qualified_scope in tracker.hits:
            if qualified_scope == target.name:
                continue  # a hit whose enclosing scope IS the target itself: its own def line/body header, not a caller
            entry = f"{rel}::{qualified_scope}"
            if (target.def_file, entry) in KNOWN_METHOD_COLLISIONS:
                continue
            if (target.def_file, entry) in HAND_VERIFIED_EXCLUSIONS:
                continue
            callers.add(entry)
    for def_file, entry in HAND_VERIFIED_ADDITIONS:
        if def_file == target.def_file:
            callers.add(entry)
    return callers


if __name__ == "__main__":
    for t in TARGETS:
        callers = find_true_callers(t)
        print(f"{t.qualified} ({t.kind}, {t.def_file}): {len(callers)} caller(s)")
        for c in sorted(callers):
            print(f"    {c}")
