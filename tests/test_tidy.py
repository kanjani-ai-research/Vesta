"""Letting go of what is no longer about anything.

A thousand files accumulated in a few days of use — graphs for directories that
no longer existed, stamps for notes about code that had moved, a record for
every temporary repository ever pointed at. None was large, which is why it went
unnoticed.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from vesta.tidy import forget, sweep


@pytest.fixture
def store(tmp_path: Path, monkeypatch) -> Path:
    """A Vesta home holding records for one live and one vanished repository."""
    from vesta.home import keep_in

    home = tmp_path / "home"
    keep_in(home)

    live = tmp_path / "live"
    live.mkdir()
    gone = tmp_path / "gone"  # never created

    for repo, key in ((live, "live-aaaa"), (gone, "gone-bbbb")):
        (home / "graphs").mkdir(parents=True, exist_ok=True)
        db = home / "graphs" / f"{key}.db"
        c = sqlite3.connect(db)
        c.executescript(
            "CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);"
        )
        c.execute("INSERT INTO meta VALUES ('root', ?)", (str(repo),))
        c.commit()
        c.close()
        for kind in ("notes", "maps", "patterns"):
            (home / kind).mkdir(parents=True, exist_ok=True)
            (home / kind / f"{key}.json").write_text("{}", encoding="utf-8")

    return home


def test_records_for_a_vanished_repository_are_let_go(store: Path):
    """A record for a repository no longer on disk describes nothing. That is a
    fact about the filesystem, not a judgement."""
    swept = sweep()

    assert any("gone-bbbb" in r for r in swept.removed)
    assert not (store / "notes" / "gone-bbbb.json").exists()


def test_records_for_a_living_repository_are_kept(store: Path):
    """Age is not staleness — the authority mechanism decides whether a claim
    still holds, by hashing the region it was made about."""
    sweep()

    assert (store / "notes" / "live-aaaa.json").exists()
    assert (store / "graphs" / "live-aaaa.db").exists()


def test_a_dry_run_removes_nothing(store: Path):
    """A first run against a store nobody has pruned should be inspectable."""
    swept = sweep(dry=True)

    assert swept.removed
    assert (store / "notes" / "gone-bbbb.json").exists()


def test_an_abandoned_preparation_mark_is_let_go(store: Path, monkeypatch):
    """A lock nobody released, as distinct from a repository being absent."""
    import vesta.tidy as tidy

    monkeypatch.setattr(tidy, "ABANDONED", 0.0)
    (store / "prepared").mkdir(parents=True, exist_ok=True)
    (store / "prepared" / "live-aaaa.json").write_text(
        json.dumps({"since": 0}), encoding="utf-8"
    )

    sweep()
    assert not (store / "prepared" / "live-aaaa.json").exists()


def test_forgetting_one_repository_leaves_the_others(store: Path, tmp_path: Path):
    """One file per kind, so this is a delete rather than a migration."""
    from vesta.home import kept_at

    live = tmp_path / "live"
    key = kept_at(live, "graphs").stem
    for kind in ("notes", "maps"):
        (store / kind / f"{key}.json").write_text("{}", encoding="utf-8")

    swept = forget(live)

    assert swept.removed
    assert not (store / "notes" / f"{key}.json").exists()
    # another repository's records are untouched
    assert (store / "notes" / "gone-bbbb.json").exists()


# ── Records in disarray, and a new version arriving ─────────────────────────


def _mapped(tmp_path, monkeypatch):
    """A repository whose attachments point at term ids the ontology lost."""
    from vesta.derive import write_attachments, write_terms
    from vesta.held import graph_for
    from vesta.home import keep_in
    from vesta.traverse import keep as keep_map
    from vesta.traverse import recall as recall_map

    keep_in(tmp_path / "home")
    root = tmp_path / "repo"
    root.mkdir()
    (root / "store.py").write_text(
        '"""Keeping things, which is what a store is for and nothing else is."""\n\n\n'
        'def keep(item):\n    """Keep one."""\n    return item\n\n\n'
        'def drop(item):\n    """Drop one."""\n    return item\n',
        encoding="utf-8",
    )
    graph_for(root, rebuild=True)
    write_terms(root, "activity: keeping an item\nactivity: dropping an item")
    write_attachments(root, "store.py:4 keep | keeping an item\nstore.py:9 drop | dropping an item")
    stale = recall_map(root)
    stale.attachments[0].term = "activity:0-11111"
    stale.attachments[1].term = "activity:1-22222"
    stale.attachments[1].label = "a word the vocabulary dropped"
    keep_map(stale, root)
    return root


def test_repair_repoints_by_label_and_keeps_orphans(tmp_path, monkeypatch):
    from vesta.domain import recall as recall_ontology
    from vesta.tidy import repair
    from vesta.traverse import recall as recall_map

    root = _mapped(tmp_path, monkeypatch)
    dry = repair(root, dry=True)
    assert (dry.projects, dry.repointed, dry.orphaned) == (1, 1, 1)
    assert recall_map(root).attachments[0].term == "activity:0-11111"

    done = repair(root)
    assert (done.repointed, done.orphaned) == (1, 1)
    current = {t["id"] for t in recall_ontology(root).terms}
    after = recall_map(root).attachments
    assert after[0].term in current
    assert after[1].term == "activity:1-22222" and len(after) == 2
    assert "re-pointed" in done.describe()


def test_arrival_of_a_new_version_repairs_once(tmp_path, monkeypatch):
    from vesta.tidy import arrived
    from vesta.traverse import recall as recall_map

    root = _mapped(tmp_path, monkeypatch)
    first = arrived("9.9.9")
    assert first is not None and first.repointed == 1
    assert arrived("9.9.9") is None
    assert recall_map(root).attachments[0].term.startswith("activity:")
    again = arrived("9.9.10")
    assert again is not None and again.repointed == 0
