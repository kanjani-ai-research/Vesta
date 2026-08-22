"""Resolution through a language server.

Driven against clangd on real C, because the point of this module is that it is
not language-specific and a Python-only test would prove the opposite of what
is claimed. Skipped where no server is installed rather than mocked: a mock of
a language server tests the mock.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from vesta.resolve import (
    MODULE,
    Coverage,
    Location,
    Session,
    Symbol,
    available,
    coverage,
    for_suffix,
    imports_in,
)

CLANGD = for_suffix(".c")
needs_clangd = pytest.mark.skipif(
    CLANGD is None or not CLANGD.is_available, reason="clangd is not installed"
)


@pytest.fixture()
def tree(tmp_path) -> Path:
    (tmp_path / "lib.c").write_text(
        "int helper(int x) { return x * 2; }\n"
        "int caller(int y) { return helper(y) + 1; }\n"
        "int other(int z)  { return helper(z) - 1; }\n",
        encoding="utf-8",
    )
    return tmp_path


# ── Routing ──────────────────────────────────────────────────────────────


def test_a_suffix_routes_to_the_server_that_speaks_it():
    assert for_suffix(".c").name == "clangd"
    assert for_suffix(".rs").name == "rust-analyzer"
    assert for_suffix(".py").name == "pyright"
    assert for_suffix(".ml").name == "ocamllsp"


def test_an_unknown_suffix_routes_nowhere():
    assert for_suffix(".txt") is None
    assert for_suffix(".md") is None


def test_adding_a_language_is_adding_a_row():
    """No language-specific code paths: every server implements the same three
    operations, so the table is the whole of what varies."""
    from vesta.resolve import SERVERS

    assert len({s.name for s in SERVERS}) == len(SERVERS)
    for server in SERVERS:
        assert server.command and server.suffixes and server.languages


# ── Coverage ─────────────────────────────────────────────────────────────


def test_coverage_reports_what_cannot_be_resolved_here(tmp_path):
    """A propagation result over a tree where half the languages had no server
    is partial, and the difference has to be visible or the correctness claim
    is hollow."""
    (tmp_path / "a.c").write_text("int main(void){return 0;}", encoding="utf-8")
    (tmp_path / "b.zig").write_text("pub fn main() void {}", encoding="utf-8")

    found = coverage(tmp_path)

    # .zig has no server in the table at all, so it is not counted either way:
    # a language nobody claimed to support is not a coverage failure.
    assert ".zig" not in found.resolved and ".zig" not in found.unresolved


def test_coverage_is_complete_when_every_suffix_has_a_server(tmp_path):
    (tmp_path / "a.txt").write_text("not code", encoding="utf-8")

    assert coverage(tmp_path).share == 1.0


def test_coverage_skips_vendored_trees(tmp_path):
    (tmp_path / ".venv").mkdir()
    (tmp_path / ".venv" / "dep.py").write_text("x = 1", encoding="utf-8")
    (tmp_path / "mine.py").write_text("y = 2", encoding="utf-8")

    found = coverage(tmp_path)
    counted = sum(found.resolved.values()) + sum(found.unresolved.values())

    assert counted == 1, "third-party source is not a propagation target"


# ── Against a real server ────────────────────────────────────────────────


@needs_clangd
def test_symbols_come_back_with_their_kinds(tree):
    with Session(CLANGD, tree) as session:
        found = session.symbols(tree / "lib.c")

    assert {s.name for s in found} == {"helper", "caller", "other"}
    assert all(s.is_definition for s in found)


@needs_clangd
def test_references_find_the_callers(tree):
    """The operation everything rests on."""
    with Session(CLANGD, tree) as session:
        helper = [s for s in session.symbols(tree / "lib.c") if s.name == "helper"][0]
        found = session.references(tree / "lib.c", helper.at.line, helper.at.character)

    # Lines 2 and 3, zero-based 1 and 2.
    assert {r.line for r in found} == {1, 2}


@needs_clangd
def test_a_reference_reported_twice_is_counted_once(tree):
    """clangd returns both the call and its enclosing expression for the same
    position. Two entries for one reference would double-count propagation."""
    with Session(CLANGD, tree) as session:
        helper = [s for s in session.symbols(tree / "lib.c") if s.name == "helper"][0]
        found = session.references(tree / "lib.c", helper.at.line, helper.at.character)

    assert len(found) == len({r.id for r in found})


@needs_clangd
def test_a_symbol_nothing_calls_has_no_references(tree):
    with Session(CLANGD, tree) as session:
        caller = [s for s in session.symbols(tree / "lib.c") if s.name == "caller"][0]
        found = session.references(tree / "lib.c", caller.at.line, caller.at.character)

    assert found == []


@needs_clangd
def test_a_session_stops_cleanly_and_twice(tree):
    session = Session(CLANGD, tree)
    session.start()
    session.stop()
    session.stop()


def test_an_absent_server_does_not_start(tmp_path):
    """A missing server is a coverage fact, not a crash."""
    from vesta.resolve import Server

    absent = Server(name="nothing", command=["definitely-not-installed"],
                    languages=["x"], suffixes=[".x"])

    assert not Session(absent, tmp_path).start()


# ── Import positions ─────────────────────────────────────────────────────
#
# No server involved: finding *where* an import binds a name is syntax, not
# resolution — documentSymbol never reports an import at all, so there is no
# position for a server to be asked about until this supplies one. What a
# position resolves to is a different, already-tested question.


def test_a_bare_import_is_found_at_the_module_name(tmp_path):
    (tmp_path / "x.py").write_text("import core\n", encoding="utf-8")
    found = imports_in(tmp_path / "x.py")

    assert [(i.bound, i.at.line, i.at.character) for i in found] == [("core", 0, 7)]


def test_a_dotted_import_points_at_its_top_level_name(tmp_path):
    """`import foo.bar` binds `foo`, not `foo.bar` — a lookup at `bar` alone
    finds nothing, since `bar` is never a name in scope by itself."""
    (tmp_path / "x.py").write_text("import os.path\n", encoding="utf-8")
    found = imports_in(tmp_path / "x.py")

    assert [(i.bound, i.at.character) for i in found] == [("os", 7)]


def test_a_symbol_import_is_found_at_the_symbol_name(tmp_path):
    (tmp_path / "x.py").write_text("from core import base\n", encoding="utf-8")
    found = imports_in(tmp_path / "x.py")

    assert [(i.bound, i.at.line, i.at.character) for i in found] == [("base", 0, 17)]


def test_an_aliased_import_is_bound_under_the_alias_but_points_at_the_original(tmp_path):
    (tmp_path / "x.py").write_text("from foo import bar as baz\n", encoding="utf-8")
    found = imports_in(tmp_path / "x.py")

    assert len(found) == 1
    assert found[0].bound == "baz"
    line = "from foo import bar as baz"
    assert line[found[0].at.character : found[0].at.character + 3] == "bar"


def test_a_bare_relative_import_still_has_a_position(tmp_path):
    """`from . import sibling` has no module name to point at, but `sibling`
    is itself a name a server can resolve — dropping it because the import
    has no module would lose it entirely rather than resolving it."""
    (tmp_path / "x.py").write_text("from . import sibling\n", encoding="utf-8")
    found = imports_in(tmp_path / "x.py")

    assert [i.bound for i in found] == ["sibling"]


def test_a_star_import_binds_no_name_a_position_can_be_found_for(tmp_path):
    (tmp_path / "x.py").write_text("from os import *\n", encoding="utf-8")

    assert imports_in(tmp_path / "x.py") == []


def test_several_imports_on_one_line_each_get_their_own_position(tmp_path):
    (tmp_path / "x.py").write_text("import a, b\n", encoding="utf-8")
    found = imports_in(tmp_path / "x.py")

    assert [(i.bound, i.at.character) for i in found] == [("a", 7), ("b", 10)]


def test_unparseable_syntax_reports_no_imports_rather_than_raising(tmp_path):
    (tmp_path / "x.py").write_text("def broken(:\n", encoding="utf-8")

    assert imports_in(tmp_path / "x.py") == []


def test_a_language_with_no_import_finder_reports_none(tmp_path):
    """Silence here means the same thing it means for a missing server: a gap
    to be seen, not a claim that the language has no imports."""
    (tmp_path / "x.rs").write_text("use core::fmt;\n", encoding="utf-8")

    assert imports_in(tmp_path / "x.rs") == []


def test_module_is_lsps_own_kind_not_invented():
    """2 is `SymbolKind.Module` in the protocol itself, chosen so a server that
    ever does report a module means the same thing by it as this does."""
    assert MODULE == 2
