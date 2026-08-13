"""Things worth fixing, found without being asked.

The governing constraint is that unusual is not wrong. A first attempt reported
ninety-two definitions nothing refers to and almost all were tests — nothing
*should* refer to a test — so every pattern here is tested for what it
deliberately does not report, not only for what it finds.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from vesta.dynamic import Blindspot, Unresolved
from vesta.graph import Edge, Graph, Node
from vesta.patterns import (
    hardcoded_language_lists,
    survey,
    swallowed_failures,
    unreachable_definitions,
    unresolvable_reach,
)


def node(name, path="a.py", line=0, container=""):
    return Node(id=f"{path}:{line}:{name}", name=name, path=path, line=line,
                kind=12, container=container)


@pytest.fixture
def empty() -> Blindspot:
    return Blindspot()


# ── Hardcoded language lists ─────────────────────────────────────────────


def test_one_table_is_one_finding(tmp_path: Path, empty):
    """Eight entries in one table are one decision to enumerate languages.
    A reader handed eight items has to work out that they are the same item."""
    (tmp_path / "resolve.py").write_text(
        'Server(languages=["rust"], suffixes=[".rs"])\n'
        'Server(languages=["go"], suffixes=[".go"])\n'
        'Server(languages=["c"], suffixes=[".c"])\n',
        encoding="utf-8",
    )
    found = hardcoded_language_lists(Graph(root=str(tmp_path)), tmp_path, empty)

    assert len(found) == 1
    assert len(found[0].sites) == 3
    assert "+2 more" in found[0].describe()


def test_a_language_table_is_found(tmp_path: Path, empty):
    (tmp_path / "resolve.py").write_text(
        'Server(languages=["rust"], suffixes=[".rs"])\n', encoding="utf-8"
    )
    found = hardcoded_language_lists(Graph(root=str(tmp_path)), tmp_path, empty)

    assert found and found[0].where == "resolve.py"
    assert "cannot handle" in found[0].why


def test_a_test_fixture_naming_a_language_is_not_reported(tmp_path: Path, empty):
    """A fixture naming a language is naming it on purpose."""
    (tmp_path / "test_resolve.py").write_text(
        'Server(languages=["x"], suffixes=[".x"])\n', encoding="utf-8"
    )

    assert not hardcoded_language_lists(Graph(root=str(tmp_path)), tmp_path, empty)


# ── Swallowed failures ───────────────────────────────────────────────────


def test_a_discarded_error_is_found(tmp_path: Path, empty):
    (tmp_path / "a.py").write_text(
        "try:\n    go()\nexcept OSError:\n    pass\n", encoding="utf-8"
    )
    found = swallowed_failures(Graph(root=str(tmp_path)), tmp_path, empty)

    assert found and found[0].line == 3


def test_a_handler_that_records_is_not_reported(tmp_path: Path, empty):
    """Only the ones that vanish. A handler that logs, re-raises, or returns
    something naming the failure is doing its job."""
    (tmp_path / "a.py").write_text(
        "try:\n    go()\nexcept OSError as exc:\n    logger.warning(exc)\n",
        encoding="utf-8",
    )

    assert not swallowed_failures(Graph(root=str(tmp_path)), tmp_path, empty)


# ── Unreachable definitions ──────────────────────────────────────────────


def test_a_test_is_never_reported_as_unreferenced(tmp_path: Path, empty):
    """The ninety-two. Nothing refers to a test, by design."""
    graph = Graph(root=str(tmp_path), nodes={
        n.id: n for n in [node("test_a_thing", "tests/test_x.py")]
    })

    assert not unreachable_definitions(graph, tmp_path, empty)


def test_a_private_helper_is_not_reported(tmp_path: Path, empty):
    graph = Graph(root=str(tmp_path), nodes={n.id: n for n in [node("_helper")]})

    assert not unreachable_definitions(graph, tmp_path, empty)


def test_something_reached_only_by_name_is_not_reported(tmp_path: Path):
    """The graph cannot see it; that is not the same as nothing using it."""
    graph = Graph(root=str(tmp_path), nodes={n.id: n for n in [node("why_not")]})
    blind = Blindspot(found=[Unresolved(path="x.py", line=1, name="why_not")])

    assert not unreachable_definitions(graph, tmp_path, blind)


def test_a_genuinely_unreferenced_definition_is_found(tmp_path: Path, empty):
    graph = Graph(root=str(tmp_path), nodes={n.id: n for n in [node("orphaned")]})
    found = unreachable_definitions(graph, tmp_path, empty)

    assert found and found[0].sites[0].what == "orphaned"
    assert found[0].confidence == "worth a look"


def test_a_referenced_definition_is_not_reported(tmp_path: Path, empty):
    used, user = node("used"), node("user", line=9)
    graph = Graph(root=str(tmp_path), nodes={used.id: used, user.id: user},
                  edges=[Edge(source=user.id, target=used.id)])

    assert not [
        f for f in unreachable_definitions(graph, tmp_path, empty)
        for s in f.sites if s.what == "used"
    ]


# ── Dynamic reach ────────────────────────────────────────────────────────


def test_dynamic_access_in_a_test_is_not_reported(tmp_path: Path):
    """In a test it is usually the subject rather than an accident."""
    blind = Blindspot(found=[Unresolved(path="tests/test_x.py", line=1, name="thing")])

    assert not unresolvable_reach(Graph(root=str(tmp_path)), tmp_path, blind)


# ── The survey ───────────────────────────────────────────────────────────


def test_every_finding_says_why_it_matters(tmp_path: Path):
    """A finding a reader cannot act on or dismiss in one pass is noise."""
    (tmp_path / "a.py").write_text(
        "try:\n    go()\nexcept OSError:\n    pass\n", encoding="utf-8"
    )
    found = survey(Graph(root=str(tmp_path)), tmp_path)

    assert found.found
    assert all(f.why for f in found.found)


def test_a_clean_repository_says_so(tmp_path: Path):
    (tmp_path / "a.py").write_text('"""Fine."""\n', encoding="utf-8")
    found = survey(Graph(root=str(tmp_path)), tmp_path)

    assert not found.found
    assert "nothing found" in found.describe()


# ── Calls to things that no longer exist ────────────────────────────────────


def _probe(tmp_path, name, source):
    (tmp_path / name).write_text(source, encoding="utf-8")
    from vesta.dynamic import Blindspot
    from vesta.graph import Graph
    from vesta.patterns import calls_to_nothing

    return [
        site
        for found in calls_to_nothing(Graph(root=str(tmp_path)), tmp_path, Blindspot())
        for site in found.sites
    ]


def test_a_call_to_a_deleted_function_is_found(tmp_path):
    """The defect this exists for. A reference graph cannot see it: an
    unresolvable name makes no node, so there is no edge to be missing."""
    sites = _probe(tmp_path, "broken.py", "def main():\n    return _load_env(True)\n")
    assert len(sites) == 1
    assert "_load_env" in sites[0].what


def test_an_import_of_a_deleted_module_is_found(tmp_path):
    sites = _probe(tmp_path, "broken.py", "from .acquire import _load_env\n")
    assert any("no such module" in s.what for s in sites)


def test_an_import_of_a_name_a_module_no_longer_has_is_found(tmp_path):
    """`from .rules import judge` kept `judge` defined in the importing file
    long after rules stopped defining it — so checking calls alone missed it."""
    (tmp_path / "rules.py").write_text("def constrains(x):\n    return x\n")
    sites = _probe(
        tmp_path, "user.py", "from .rules import judge\n\n\ndef go():\n    return judge(1)\n"
    )
    assert any("has no judge" in s.what for s in sites)


def test_working_code_is_not_reported(tmp_path):
    source = (
        "import json\n"
        "from pathlib import Path\n\n\n"
        "def helper(x):\n    return x\n\n\n"
        "def works(value=None):\n"
        "    data = json.loads('{}')\n"
        "    return helper(data), len(str(Path('.'))), isinstance(value, int)\n"
    )
    assert _probe(tmp_path, "fine.py", source) == []


def test_a_re_exported_name_is_not_reported(tmp_path):
    """`from .a import thing` in b makes `thing` a name b supplies."""
    (tmp_path / "a.py").write_text("def thing():\n    return 1\n")
    (tmp_path / "b.py").write_text("from .a import thing\n")
    assert _probe(tmp_path, "c.py", "from .b import thing\n") == []


def test_a_name_bound_later_in_the_module_is_not_reported(tmp_path):
    source = "def go():\n    return later()\n\n\ndef later():\n    return 1\n"
    assert _probe(tmp_path, "ordered.py", source) == []


def test_an_unparseable_file_claims_nothing(tmp_path):
    """Better silent than wrong: a file this cannot read is not evidence."""
    assert _probe(tmp_path, "bad.py", "def broken(\n") == []


def test_a_star_import_is_left_alone(tmp_path):
    (tmp_path / "source.py").write_text("def thing():\n    return 1\n")
    assert _probe(tmp_path, "user.py", "from .source import *\n") == []


# ── Code only its tests call ────────────────────────────────────────────────


def _only_tests(tmp_path):
    from vesta.dynamic import Blindspot
    from vesta.graph import Graph
    from vesta.held import graph_for
    from vesta.patterns import reached_only_by_tests

    return [
        site
        for found in reached_only_by_tests(
            graph_for(tmp_path, rebuild=True), tmp_path, Blindspot()
        )
        for site in found.sites
    ]


def test_something_only_a_test_calls_is_found(tmp_path):
    """The defect this repository shipped twice: an offer written, tested
    directly, and never wired into the one place that had to call it. The
    tests were green and the feature was dead."""
    (tmp_path / "hooky.py").write_text(
        "def _offer_one(p):\n    return 'one'\n\n\n"
        "def _offer_two(p):\n    return 'two'\n\n\n"
        "def main(p):\n    return _offer_one(p)\n",
        encoding="utf-8",
    )
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_hooky.py").write_text(
        "import sys\nfrom pathlib import Path\n"
        "sys.path.insert(0, str(Path(__file__).resolve().parent.parent))\n"
        "from hooky import _offer_one, _offer_two\n\n\n"
        "def test_one():\n    assert _offer_one('x')\n\n\n"
        "def test_two():\n    assert _offer_two('x')\n",
        encoding="utf-8",
    )

    found = " ".join(s.describe() for s in _only_tests(tmp_path))
    assert "_offer_two" in found
    assert "_offer_one" not in found


def test_a_reference_graph_alone_cannot_see_it(tmp_path):
    """`nothing refers to this` asks whether *anything* refers to a definition,
    and something does — the test. The question that matters is whether
    anything in the code that ships does."""
    (tmp_path / "hooky.py").write_text(
        "def _dead(p):\n    return 1\n\n\ndef main(p):\n    return 2\n", encoding="utf-8"
    )
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_hooky.py").write_text(
        "import sys\nfrom pathlib import Path\n"
        "sys.path.insert(0, str(Path(__file__).resolve().parent.parent))\n"
        "from hooky import _dead\n\n\ndef test_it():\n    assert _dead(1)\n",
        encoding="utf-8",
    )

    from vesta.dynamic import Blindspot
    from vesta.held import graph_for
    from vesta.patterns import unreachable_definitions

    graph = graph_for(tmp_path, rebuild=True)
    unreferenced = " ".join(
        s.describe()
        for f in unreachable_definitions(graph, tmp_path, Blindspot())
        for s in f.sites
    )
    assert "_dead" not in unreferenced  # the test refers to it

    assert "_dead" in " ".join(s.describe() for s in _only_tests(tmp_path))


def test_a_function_in_a_dispatch_table_is_not_dead(tmp_path):
    """Registering a function is using it. A detector that misses that reports
    every plugin architecture as dead code."""
    (tmp_path / "app.py").write_text(
        "def finder(x):\n    return 1\n\n\n"
        "PATTERNS = (('a name', finder),)\n\n\n"
        "def main():\n    return PATTERNS\n",
        encoding="utf-8",
    )
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_app.py").write_text(
        "import sys\nfrom pathlib import Path\n"
        "sys.path.insert(0, str(Path(__file__).resolve().parent.parent))\n"
        "from app import finder\n\n\ndef test_it():\n    assert finder(1)\n",
        encoding="utf-8",
    )
    assert "finder" not in " ".join(s.describe() for s in _only_tests(tmp_path))


def test_an_aliased_import_is_not_dead(tmp_path):
    """`from .traverse import where as where_in` uses `where`."""
    (tmp_path / "a.py").write_text("def where(x):\n    return 1\n", encoding="utf-8")
    (tmp_path / "b.py").write_text(
        "from a import where as where_in\n\n\ndef main():\n    return where_in(1)\n",
        encoding="utf-8",
    )
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_a.py").write_text(
        "import sys\nfrom pathlib import Path\n"
        "sys.path.insert(0, str(Path(__file__).resolve().parent.parent))\n"
        "from a import where\n\n\ndef test_it():\n    assert where(1)\n",
        encoding="utf-8",
    )
    assert "where" not in " ".join(s.describe() for s in _only_tests(tmp_path))


def test_a_test_helper_is_not_reported(tmp_path):
    """A test helper is reached only by tests and should be."""
    (tmp_path / "app.py").write_text("def main():\n    return 1\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_app.py").write_text(
        "def helper():\n    return 2\n\n\ndef test_it():\n    assert helper()\n",
        encoding="utf-8",
    )
    assert "helper" not in " ".join(s.describe() for s in _only_tests(tmp_path))
