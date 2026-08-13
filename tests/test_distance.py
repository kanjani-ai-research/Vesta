"""How far a repository is from done, measured rather than judged.

An agent in a loop needs a stopping condition, and the obvious one — ask the
model whether it is finished — is the one that cannot work. The leading loop
plugin's own prompt concedes it: *"Do not output false promises to escape the
loop."* That instruction exists because the failure it names is the normal case.

So every signal here is a count, and the tests are about whether a count that
should move does. A measurement that cannot see a change measures nothing.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from vesta.distance import Reading, between, measure

CLEAN = '''"""Doing the work."""


def handle(request):
    """Answer one."""
    return work(request)


def work(request):
    """The work itself."""
    return request
'''

ORPHAN = '''

def orphan():
    """Nothing refers to this."""
    return 1
'''

SWALLOWED = '''

def risky(call):
    """Try, and hide whatever happens."""
    try:
        return call()
    except:
        return None
'''


@pytest.fixture
def project(tmp_path):
    (tmp_path / "app.py").write_text(CLEAN, encoding="utf-8")
    return tmp_path


def test_a_reading_counts_what_is_there(project):
    reading = measure(project)
    assert reading.definitions == 2
    assert reading.unresolved == 0
    assert not reading.missing


def test_adding_a_defect_moves_it_further(project):
    """The property everything else rests on."""
    before = measure(project)
    (project / "app.py").write_text(CLEAN + ORPHAN, encoding="utf-8")
    after = measure(project)

    moved = between(before, after)
    assert not moved.closer
    assert not moved.stalled
    assert after.defects > before.defects


def test_removing_a_defect_moves_it_closer(project):
    (project / "app.py").write_text(CLEAN + ORPHAN, encoding="utf-8")
    before = measure(project)
    (project / "app.py").write_text(CLEAN, encoding="utf-8")
    after = measure(project)

    moved = between(before, after)
    assert moved.closer
    assert "defects" in " ".join(moved.what_changed())


def test_undoing_a_change_returns_to_the_same_reading(project):
    """A measurement that drifts cannot be compared across iterations."""
    first = measure(project)
    (project / "app.py").write_text(CLEAN + ORPHAN, encoding="utf-8")
    measure(project)
    (project / "app.py").write_text(CLEAN, encoding="utf-8")
    again = measure(project)

    assert abs(first.distance - again.distance) < 0.01


def test_a_stale_graph_is_never_trusted(project):
    """`trust_for` returns any recently written graph without checking the
    tree, which is right for a hook and exactly wrong here: this runs before
    and after an edit, and a remembered graph makes the edit invisible."""
    before = measure(project)
    (project / "app.py").write_text(CLEAN + SWALLOWED, encoding="utf-8")
    after = measure(project)
    assert after.definitions > before.definitions


def test_no_change_reads_as_stalled(project):
    """The signal a loop needs most: an agent iterating without moving will
    iterate forever, and a stopping condition based on the model's own opinion
    is blind to it."""
    before = measure(project)
    after = measure(project)
    assert between(before, after).stalled
    assert between(before, after).what_changed() == []


def test_a_signal_that_cannot_be_established_is_not_zero(tmp_path):
    """A repository nobody could read is not a repository with no defects."""
    reading = measure(tmp_path / "does-not-exist")
    assert reading.missing
    assert not reading.settled
    assert "cannot say" in reading.describe()


def test_an_empty_repository_is_not_finished(tmp_path):
    """The state every project starts in. A loop reading it as settled stops
    before writing a line."""
    reading = measure(tmp_path)
    assert not reading.settled
    assert "nothing built yet" in reading.describe()


def test_settled_requires_evidence_not_absence():
    reading = Reading(definitions=10, defects=0, rules_broken=0, unresolved=0)
    assert reading.settled
    assert not Reading(definitions=0).settled

    assert not Reading(definitions=10, defects=1).settled
    assert not Reading(definitions=10, rules_broken=1).settled
    assert not Reading(definitions=10, unresolved=1).settled
    assert not Reading(definitions=10, missing=["the graph"]).settled


def test_unnamed_code_does_not_block_completion():
    """Deliberately lenient: a definition nothing has named is unfinished
    description, and an agent should not loop forever writing labels."""
    reading = Reading(definitions=100, named=0, defects=0)
    assert reading.settled
    assert reading.unnamed == 100


def test_a_broken_rule_weighs_more_than_a_defect():
    """A rule the author set and the code breaks is a fact about their intent
    being violated; a definition nothing refers to may be a public interface."""
    rule = Reading(definitions=100, rules_broken=1)
    defect = Reading(definitions=100, defects=1)
    assert rule.distance > defect.distance


def test_distance_is_normalised_by_size():
    """A repository must not look worse for being bigger."""
    small = Reading(definitions=10, defects=1)
    large = Reading(definitions=100, defects=10)
    assert abs(small.distance - large.distance) < 0.01


def test_what_changed_names_each_signal_that_moved():
    before = Reading(definitions=10, defects=3, rules_broken=1)
    after = Reading(definitions=10, defects=1, rules_broken=0)
    said = " ".join(between(before, after).what_changed())
    assert "defects 3 ↓ 1" in said
    assert "rules broken 1 ↓ 0" in said
