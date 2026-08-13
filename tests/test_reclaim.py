"""What Vesta holds, and getting rid of what is dead.

The thing to hold: nothing a user might still want is ever removed, and the
report a user reads before deciding is accurate about what would go. A tool
that deletes the wrong thing in somebody's home directory does not get a
second chance.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from vesta.reclaim import Held, Holding, held, reclaim


def _keep(base: Path, root: str, name: str, size: int = 5000) -> None:
    """Write what Vesta would have derived for a repository."""
    key = hashlib.sha256(root.encode("utf-8")).hexdigest()[:12]
    (base / "graphs").mkdir(parents=True, exist_ok=True)
    (base / "notes").mkdir(parents=True, exist_ok=True)
    (base / "graphs" / f"{name}-{key}.json").write_text(
        json.dumps({"shape": "x", "graph": {"root": root, "nodes": {}, "edges": []}}),
        encoding="utf-8",
    )
    (base / "graphs" / f"{name}-{key}.db").write_bytes(b"x" * size)
    (base / "notes" / f"{name}-{key}.json").write_text("{}", encoding="utf-8")


@pytest.fixture
def home(tmp_path: Path) -> Path:
    return tmp_path / "vesta-home"


def test_nothing_held_says_so(home):
    assert "holding nothing" in held(home).describe()


def test_a_live_repository_is_not_dead(home, tmp_path):
    alive = tmp_path / "project"
    alive.mkdir()
    _keep(home, str(alive), "project")

    found = held(home)
    assert len(found.holdings) == 1
    assert found.holdings[0].alive is True
    assert not found.dead


def test_a_deleted_repository_is_dead(home):
    _keep(home, "/nowhere/at/all/gone", "gone")

    found = held(home)
    assert found.dead
    assert found.dead[0].root == "/nowhere/at/all/gone"
    assert "gone" in found.dead[0].describe()


def test_a_graph_of_the_temp_directory_itself_is_junk(home):
    """The largest holding on the machine this was written on.

    A 522M graph rooted at `/private/tmp` — the system temp directory, 418
    entries of other programs' litter, walked as though it were a repository.
    It still exists, so the liveness test says keep it; it is obviously
    worthless, so a report that stayed silent about it would be useless.
    """
    _keep(home, "/private/tmp", "tmp")

    found = held(home)
    assert found.holdings[0].junk
    assert found.dead, "a graph of the system temp directory is not worth keeping"
    assert "not a project" in found.dead[0].describe()


def test_a_real_project_that_happens_to_be_under_tmp_is_kept(home, tmp_path):
    """People do work in temporary directories, and pytest puts every
    `tmp_path` under one. A rule that called anything temp-rooted dead would
    mark live work reclaimable."""
    real = tmp_path / "experiment"
    real.mkdir()
    _keep(home, str(real), "experiment")

    found = held(home)
    assert not found.dead
    assert not found.holdings[0].junk


def test_a_project_that_merely_starts_like_tmp_is_not_temporary():
    """`/tmpfoo` is somebody's project, not the system temp directory."""
    assert not Holding(root="/tmpfoo/project").temporary
    assert not Holding(root="/home/me/tmp-work").temporary
    assert Holding(root="/tmp").temporary
    assert Holding(root="/tmp/x").temporary


def test_a_repository_that_cannot_be_resolved_is_not_assumed_dead(home, monkeypatch):
    """An unmounted volume makes a live repository look deleted.

    Deleting somebody's cached understanding because their external disk was
    unplugged is not a mistake worth making to save a few megabytes.
    """
    from vesta import reclaim as module

    _keep(home, "/Volumes/external/project", "project")

    # Only the liveness question fails, the way an unmounted volume fails it.
    # Patching Path.is_dir outright would break the directory walk as well and
    # test nothing about the thing this is for.
    monkeypatch.setattr(module, "_exists", lambda root: None)

    found = module.held(home)
    assert found.holdings[0].alive is None
    assert not found.dead
    assert "cannot tell" in found.holdings[0].describe()


def test_a_path_that_cannot_be_read_answers_neither_way(monkeypatch):
    """The other half: `_exists` must return None rather than raise or guess."""
    from vesta import reclaim as module

    def _raises(self):
        raise OSError("host is down")

    monkeypatch.setattr(Path, "is_dir", _raises)

    assert module._exists("/Volumes/external/project") is None
    assert module._exists("") is None


def test_a_holding_weighs_exactly_what_is_on_disk(home):
    """Both files count — a graph is kept as JSON to load whole and SQLite to
    query — but each exactly once.

    Adding the database *beside* a JSON, when the walk had already counted it,
    overstated every holding by the size of its database. Roughly double on a
    real graph, in a report whose entire job is telling somebody how much they
    would get back.
    """
    _keep(home, "/nowhere/gone", "gone", size=100_000)

    found = held(home)
    on_disk = sum(p.stat().st_size for p in home.rglob("*") if p.is_file())
    assert found.holdings[0].bytes == on_disk
    assert found.bytes == on_disk


def test_everything_derived_for_one_repository_is_one_holding(home):
    """Graph, notes and the rest share the key in their filename."""
    _keep(home, "/nowhere/gone", "gone")

    found = held(home)
    assert len(found.holdings) == 1
    assert len(found.holdings[0].files) == 3  # graph json, its db, and the note


def test_reclaiming_removes_the_dead_and_keeps_the_living(home, tmp_path):
    alive = tmp_path / "project"
    alive.mkdir()
    _keep(home, str(alive), "project")
    _keep(home, "/nowhere/gone", "gone")

    found = held(home)
    assert len(found.dead) == 1

    files, freed, refused = reclaim(found.dead)
    assert files == 3  # the gone holding: its json, its db, and its note
    assert freed > 0
    assert not refused

    after = held(home)
    assert len(after.holdings) == 1
    assert after.holdings[0].root == str(alive)


def test_reclaiming_takes_what_it_is_given_and_nothing_else(home, tmp_path):
    """`reclaim` never finds its own targets, so nothing goes that a caller
    did not look at first."""
    alive = tmp_path / "project"
    alive.mkdir()
    _keep(home, str(alive), "project")

    files, freed, _ = reclaim([])
    assert files == 0 and freed == 0
    assert len(held(home).holdings) == 1


def test_reclaiming_nothing_is_not_an_error(home):
    assert reclaim([]) == (0, 0, [])


def test_the_report_names_what_would_be_freed(home):
    _keep(home, "/nowhere/gone", "gone")
    said = held(home).describe()

    assert "no longer exist" in said
    assert "--reclaim" in said


def test_the_biggest_holding_is_shown_first(home):
    """The thing worth reclaiming is almost always one outlier, and a list
    sorted by name buries it."""
    _keep(home, "/nowhere/small", "small", size=1000)
    _keep(home, "/nowhere/huge", "huge", size=500_000)

    lines = held(home).describe().splitlines()
    assert "huge" in lines[1]


def test_a_file_that_names_no_repository_is_counted_but_not_removed(home):
    """Something in the directory that does not follow the naming rule is
    reported as loose rather than guessed at."""
    (home / "graphs").mkdir(parents=True)
    (home / "graphs" / "stray.json").write_text("{}", encoding="utf-8")

    found = held(home)
    assert found.loose == 1
    assert not found.dead


# ── The command ────────────────────────────────────────────────────────────


def test_the_command_reports_without_removing(home, monkeypatch, capsys):
    from vesta import reclaim as module
    from vesta.cli import main

    _keep(home, "/nowhere/gone", "gone")
    monkeypatch.setattr(module, "home", lambda: home)

    assert main(["held"]) == 0
    said = capsys.readouterr().out
    assert "no longer exist" in said
    # Nothing went.
    assert held(home).dead


def test_the_command_reclaims_when_asked(home, monkeypatch, capsys):
    from vesta import reclaim as module
    from vesta.cli import main

    _keep(home, "/nowhere/gone", "gone")
    monkeypatch.setattr(module, "home", lambda: home)

    assert main(["held", "--reclaim"]) == 0
    assert "Reclaimed" in capsys.readouterr().out
    assert not held(home).holdings


def test_reclaiming_with_nothing_dead_says_so(home, tmp_path, monkeypatch, capsys):
    from vesta import reclaim as module
    from vesta.cli import main

    alive = tmp_path / "project"
    alive.mkdir()
    _keep(home, str(alive), "project")
    monkeypatch.setattr(module, "home", lambda: home)

    assert main(["held", "--reclaim"]) == 0
    assert "Nothing to reclaim" in capsys.readouterr().out
    assert held(home).holdings
