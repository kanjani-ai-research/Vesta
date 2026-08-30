"""Skills read as authority, across the shapes the format actually takes.

Every case here comes from a real skill or a real failure. The format's body is
free-form by specification — Anthropic's docs and the Agent Skills open standard
both say so outright — and measured across thirty-one shipped skills that is
plainly true: a twenty-fold spread in length, a heading vocabulary that
fragments into one-offs after "Overview", one skill with no title at all.

So the tests that matter are the ones that would pass on a well-formed skill and
fail on a real corpus.
"""

from __future__ import annotations

import pytest

from vesta.graph import Graph, Node
from vesta.skill import (
    Skill,
    Store,
    acquire,
    activate,
    add,
    applies,
    read_skill,
    recall,
    to_judge,
)
from vesta.traverse import Attachment, Map

WELL_FORMED = """---
name: retry-policy
description: How this organisation handles retries. Use when adding or changing retry behaviour.
version: 1.0.0
---

# Retry policy

Every retry must be bounded.
"""


def test_a_skill_is_read_from_the_two_fields_the_spec_guarantees():
    skill, why = read_skill(WELL_FORMED)

    assert why == ""
    assert skill.name == "retry-policy"
    assert skill.description.startswith("How this organisation handles retries")
    assert skill.fields["version"] == "1.0.0"


def test_the_body_is_kept_whole_and_never_parsed():
    """A skill says what to do and when; shredding it into labels destroys the
    part that instructs.

    An earlier version scraped headings into terms and reported nine of twelve
    as unmet requirements, most of which were document scaffolding.
    """
    skill, _ = read_skill(WELL_FORMED)

    assert "# Retry policy" in skill.body
    assert "Every retry must be bounded." in skill.body


def test_a_skill_with_no_heading_at_all_is_still_a_skill():
    """`frontend-design`, shipped by Anthropic, opens straight into prose.

    A parser that assumes a title reads it as empty.
    """
    skill, why = read_skill(
        "---\nname: frontend-design\ndescription: Build interfaces.\n---\n\n"
        "This skill guides creation of distinctive interfaces.\n"
    )

    assert why == ""
    assert skill.name == "frontend-design"
    assert "distinctive interfaces" in skill.body


def test_an_unknown_frontmatter_field_is_kept_not_refused():
    """The two published specs differ on which optional fields exist, so
    refusing an unknown one would reject a skill written for the other."""
    skill, why = read_skill(
        "---\nname: x-skill\ndescription: A thing.\n"
        "compatible-with: codex, cursor\nuser-invocable: false\n---\n\nBody.\n"
    )

    assert why == ""
    assert skill.fields["compatible-with"] == "codex, cursor"
    assert skill.fields["user-invocable"] == "false"


@pytest.mark.parametrize(
    "text,expected",
    [
        ("no frontmatter here\n", "no frontmatter"),
        ("---\ndescription: A thing.\n---\n", "no name"),
        ("---\nname: x\n---\n", "no description"),
        ("---\nname: Not Kebab\ndescription: A thing.\n---\n", "lowercase"),
    ],
)
def test_what_is_not_a_skill_says_why(text, expected):
    """A file somebody meant as a skill and that is not one is the thing they
    most need told."""
    skill, why = read_skill(text)

    assert skill is None
    assert expected in why


def test_an_overlong_description_is_truncated_not_refused():
    """The limit is a specification about what an author should write. Refusing
    a skill that overruns it would make this stricter than the harness that
    loads it."""
    skill, why = read_skill(
        f"---\nname: long-one\ndescription: {'x' * 2000}\n---\n\nBody.\n"
    )

    assert why == ""
    assert len(skill.description) == 1024


# ── Acquisition, from wherever the user has them ────────────────────────────


def test_skills_are_found_at_any_depth(tmp_path):
    """Measured on this machine, shipped skills sit at three different depths
    under three different parent layouts. A fixed set of glob shapes matched
    one of them."""
    deep = tmp_path / "marketplace" / "plugins" / "thing" / "skills" / "deep"
    deep.mkdir(parents=True)
    (deep / "SKILL.md").write_text(WELL_FORMED, encoding="utf-8")

    found, refused = acquire(tmp_path)

    assert [s.name for s in found] == ["retry-policy"]
    assert not refused


def test_a_single_file_is_a_source(tmp_path):
    path = tmp_path / "SKILL.md"
    path.write_text(WELL_FORMED, encoding="utf-8")

    found, _ = acquire(path)

    assert [s.name for s in found] == ["retry-policy"]


def test_several_sources_are_read_together(tmp_path):
    for name in ("one", "two"):
        directory = tmp_path / name / "skills" / name
        directory.mkdir(parents=True)
        (directory / "SKILL.md").write_text(
            WELL_FORMED.replace("retry-policy", name), encoding="utf-8"
        )

    found, _ = acquire([tmp_path / "one", tmp_path / "two"])

    assert sorted(s.name for s in found) == ["one", "two"]


def test_a_source_that_is_not_there_is_reported(tmp_path):
    found, refused = acquire(tmp_path / "nowhere")

    assert not found
    assert refused and "no such file" in refused[0].why


def test_dependency_directories_are_not_walked(tmp_path):
    """The lesson `held._shape` already paid for: prune as you descend."""
    buried = tmp_path / "node_modules" / "pkg" / "skills" / "x"
    buried.mkdir(parents=True)
    (buried / "SKILL.md").write_text(WELL_FORMED, encoding="utf-8")

    found, _ = acquire(tmp_path)

    assert not found


# ── One store, and what identifies an authority in it ───────────────────────


def test_two_different_skills_sharing_a_name_are_both_kept(tmp_path, monkeypatch):
    """Measured on this machine: three shipped skills are called `access` — for
    Discord, Telegram and iMessage — with three genuinely different bodies.

    Keyed by name, a store keeps whichever was read last and silently discards
    two authorities, which for a thing whose job is to be the standard something
    was judged against is the worst available failure.
    """
    monkeypatch.setenv("VESTA_HOME", str(tmp_path / "home"))

    for which in ("discord", "telegram"):
        directory = tmp_path / which / "skills" / "access"
        directory.mkdir(parents=True)
        (directory / "SKILL.md").write_text(
            f"---\nname: access\ndescription: Manage {which} access.\n---\n\n"
            f"Approve {which} pairings.\n",
            encoding="utf-8",
        )

    store, _ = add(tmp_path / "proj", [tmp_path / "discord", tmp_path / "telegram"])

    assert len(store.skills) == 2
    assert len({s.id for s in store.skills}) == 2


def test_the_same_skill_acquired_twice_collapses(tmp_path, monkeypatch):
    """Acquiring the same skill twice is how a user re-reads one they edited."""
    monkeypatch.setenv("VESTA_HOME", str(tmp_path / "home"))
    directory = tmp_path / "skills" / "retry-policy"
    directory.mkdir(parents=True)
    (directory / "SKILL.md").write_text(WELL_FORMED, encoding="utf-8")

    add(tmp_path / "proj", tmp_path)
    store, _ = add(tmp_path / "proj", tmp_path)

    assert len(store.skills) == 1


def test_acquiring_nothing_chosen_means_everything_applies(tmp_path, monkeypatch):
    """A user who has acquired skills and chosen nothing has not thereby chosen
    nothing to apply."""
    monkeypatch.setenv("VESTA_HOME", str(tmp_path / "home"))
    directory = tmp_path / "skills" / "retry-policy"
    directory.mkdir(parents=True)
    (directory / "SKILL.md").write_text(WELL_FORMED, encoding="utf-8")

    store, _ = add(tmp_path / "proj", tmp_path)

    assert len(store.live) == 1


def test_an_authority_is_selectable_by_name_or_by_id(tmp_path, monkeypatch):
    monkeypatch.setenv("VESTA_HOME", str(tmp_path / "home"))
    for which in ("one", "two"):
        directory = tmp_path / which / "skills" / which
        directory.mkdir(parents=True)
        (directory / "SKILL.md").write_text(
            WELL_FORMED.replace("retry-policy", which), encoding="utf-8"
        )
    store, _ = add(tmp_path / "proj", [tmp_path / "one", tmp_path / "two"])

    by_name = activate(tmp_path / "proj", ["one"])
    assert [s.name for s in by_name.live] == ["one"]

    only = next(s for s in store.skills if s.name == "two")
    by_id = activate(tmp_path / "proj", [only.id])
    assert [s.id for s in by_id.live] == [only.id]


def test_naming_something_absent_does_not_lose_the_rest(tmp_path, monkeypatch):
    """A user combining authorities across projects will name one this project
    has not acquired, and refusing the whole selection over it loses their
    choice."""
    monkeypatch.setenv("VESTA_HOME", str(tmp_path / "home"))
    directory = tmp_path / "skills" / "retry-policy"
    directory.mkdir(parents=True)
    (directory / "SKILL.md").write_text(WELL_FORMED, encoding="utf-8")
    add(tmp_path / "proj", tmp_path)

    store = activate(tmp_path / "proj", ["retry-policy", "never-acquired"])

    assert [s.name for s in store.live] == ["retry-policy"]


# ── The slice that applies to one operation ─────────────────────────────────


def _repository():
    nodes = [
        Node(id="retry.py:10:parse_retry", name="parse_retry", path="retry.py", line=10, kind=12),
        Node(id="chart.py:10:draw", name="draw", path="chart.py", line=10, kind=12),
    ]
    graph = Graph(root="/x", nodes={n.id: n for n in nodes})
    mapped = Map(
        ontology="test",
        attachments=[
            Attachment(
                node="retry.py:10:parse_retry", term="t1",
                label="retry a failed request with a growing delay",
                kind="activity", strength=1.0, path="retry.py", name="parse_retry",
            ),
            Attachment(
                node="chart.py:10:draw", term="t2", label="draw a chart of the results",
                kind="activity", strength=1.0, path="chart.py", name="draw",
            ),
        ],
    )
    return graph, mapped


def test_the_slice_varies_with_what_was_asked():
    """Unioning the action with the skill's description was measured doing the
    opposite: a sixty-five word description beside a two word action made the
    action three percent of the query, so every action returned the same twelve
    definitions — including one about rendering a chart in a repository that
    does no such thing.
    """
    graph, mapped = _repository()
    skill, _ = read_skill(WELL_FORMED)

    retries = applies(skill, "retry a failed request", graph, mapped)
    charts = applies(skill, "draw a chart", graph, mapped)

    assert retries != charts
    assert graph.nodes[retries[0]].name == "parse_retry"
    assert graph.nodes[charts[0]].name == "draw"


def test_the_skills_subject_is_a_nudge_not_a_gate():
    """A skill that never mentions a word is not thereby an authority that
    excludes it, and a hard filter would make a broad skill silently narrow."""
    graph, mapped = _repository()
    skill, _ = read_skill(WELL_FORMED)

    assert applies(skill, "draw a chart", graph, mapped), "still reachable"


def test_what_is_put_in_front_of_an_evaluator_is_recorded_in_one_place():
    """The retrieval is deterministic even though the judgement is not. When a
    pooled verdict is wrong the cause is usually the evidence, and a record that
    blends the two cannot say which."""
    graph, mapped = _repository()
    skill, _ = read_skill(WELL_FORMED)
    evidence = applies(skill, "retry a failed request", graph, mapped)

    asked = to_judge(skill, "retry a failed request", evidence, graph)

    assert "AUTHORITY" in asked and "retry-policy" in asked
    assert "Every retry must be bounded." in asked, "the body instructs, whole"
    assert "PROPOSED — retry a failed request" in asked
    assert "retry.py:11" in asked


def test_an_evaluator_is_told_when_nothing_bears_on_the_action():
    graph, mapped = _repository()
    skill, _ = read_skill(WELL_FORMED)

    asked = to_judge(skill, "anything at all", [], graph)

    assert "nothing in this repository was found to bear on it" in asked


# ── What a standard asks about that this repository does not name ───────────


def test_words_a_repository_has_no_vocabulary_for_are_listed():
    """The useful half of an ontology has always been what it does not reach.

    `Map.unattached` keeps exactly that for a derived one; asked of a skill the
    same question becomes a checklist.
    """
    from vesta.skill import difference

    graph, mapped = _repository()
    skill, _ = read_skill(
        "---\nname: retry-policy\n"
        "description: Bound every retry and log each attempt to telemetry.\n---\n\nBody.\n"
    )

    found = difference(skill, graph, mapped)

    assert "telemetry" in found.unnamed
    assert "retry" in found.shared


def test_a_standard_about_different_work_says_so_rather_than_faulting_this_one():
    """A skill sharing no vocabulary is not a standard this project falls short
    of — it is a standard about something else, and reporting its every word as
    unmet would fill a report with absences nobody should act on.
    """
    from vesta.skill import difference

    graph, mapped = _repository()
    skill, _ = read_skill(
        "---\nname: baking\ndescription: Proof the dough and temper the chocolate.\n---\n\nB.\n"
    )

    found = difference(skill, graph, mapped)

    assert not found.bears_on
    assert "looks like a standard for different work" in found.describe()


def test_the_code_counts_as_naming_something_even_where_the_ontology_does_not():
    """A repository can perform work its vocabulary has not caught up with —
    the same two surfaces `traverse.where` crosses."""
    from vesta.skill import difference

    graph, mapped = _repository()
    skill, _ = read_skill(
        "---\nname: charting\ndescription: Draw a chart from results.\n---\n\nB.\n"
    )

    found = difference(skill, graph, mapped)

    assert "chart" in found.shared
