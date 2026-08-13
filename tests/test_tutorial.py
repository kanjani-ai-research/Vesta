"""A tutorial that walks somebody through Vesta a page at a time.

The two things worth holding: it must never *do* anything to the repository it
is explaining — a tutorial that signs a contract to demonstrate contracts has
hijacked the session it was invited into — and the page must fit what the host
will actually draw, since a chapter with five topics is a chapter that silently
loses one.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from vesta import tutorial


# What AskUserQuestion accepts. Exceeding any of these does not raise — it
# renders wrong, or drops content, which is worse.
MOST_OPTIONS = 4
FEWEST_OPTIONS = 2
HEADER_WIDTH = 12


@pytest.fixture
def repo(tmp_path, monkeypatch):
    monkeypatch.setenv("VESTA_HOME", str(tmp_path / "home"))
    where = tmp_path / "project"
    where.mkdir()
    (where / "thing.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    return where


# --- the pages fit what the host draws ---------------------------------


@pytest.mark.parametrize("header,topics", tutorial.chapters(), ids=lambda x: str(x)[:20])
def test_every_chapter_fits_the_dialog(header, topics):
    assert FEWEST_OPTIONS <= len(topics) <= MOST_OPTIONS, (
        f"{header} has {len(topics)} topics; the host draws {FEWEST_OPTIONS}-{MOST_OPTIONS}"
    )
    assert len(header) <= HEADER_WIDTH, f"{header!r} is wider than the chip allows"


def test_every_topic_has_a_label_a_reason_and_a_lesson():
    for chapter in tutorial.CHAPTERS:
        for topic in chapter.topics:
            assert topic.label.strip()
            assert topic.why.strip()
            assert topic.teaches.strip()
            # The label is a chip in a narrow column, not a sentence.
            assert len(topic.label) <= 40, f"{topic.label!r} is too long to render"


def test_labels_within_a_chapter_are_distinct():
    for chapter in tutorial.CHAPTERS:
        labels = [t.label for t in chapter.topics]
        assert len(set(labels)) == len(labels), f"{chapter.header} repeats a label"


# --- it never acts -----------------------------------------------------


@pytest.mark.parametrize("command", tutorial.demonstrations())
def test_every_demonstration_is_read_only(command):
    """The rule this module turns on.

    A tutorial explaining automated mode must not *start* automated mode, and
    one explaining contracts must not sign one. Enforced here rather than
    remembered.
    """
    import shlex

    assert tutorial.reads(shlex.split(command)), (
        f"the tutorial runs `{command}`, which is not read-only"
    )


def test_the_read_only_set_excludes_everything_that_acts():
    """Naming the things that must never be in it, so a later edit cannot."""
    for acts in ("drive", "agree", "learn", "declare", "prepare", "graph"):
        assert acts not in tutorial.SAFE, f"{acts} acts and must not be demonstrated"


def test_a_verb_that_both_reads_and_writes_is_judged_on_its_flags():
    """`contract` shows; `contract --sign` agrees. One letter apart in effect."""
    assert tutorial.reads(["contract"])
    assert not tutorial.reads(["contract", "--sign"])
    assert not tutorial.reads(["contract", "--goal", "x"])

    # And the pair that differ by one character.
    assert tutorial.reads(["words", "--templates"])
    assert not tutorial.reads(["words", "--template", "security"])
    assert not tutorial.reads(["words", "--edit"])
    assert not tutorial.reads(["decided", "--check"])


def test_nothing_outside_the_set_reads():
    assert not tutorial.reads(["drive", "--step"])
    assert not tutorial.reads(["graph"])
    assert not tutorial.reads([])


def test_a_chapter_that_tried_to_act_is_refused(repo, monkeypatch):
    """Belt and braces: the guard holds even if a chapter is written wrongly."""
    ran = []
    monkeypatch.setattr(
        tutorial.subprocess, "run", lambda *a, **k: ran.append(a) or None
    )
    said = tutorial._ran("drive --step", repo)
    assert ran == [], "a command outside the read-only set was executed"
    assert "not shown" in said


# --- pages ------------------------------------------------------------


def test_the_first_page_is_about_the_two_modes(repo):
    drawn = tutorial.page(1, repo)
    said = " ".join(o["preview"] for o in drawn["options"]).lower()
    assert "companion" in said
    assert "automated" in said
    # The thing a new user most needs to know: companion costs them nothing.
    assert "nothing to run" in said


def test_every_chapter_can_be_drawn(repo):
    for n in range(1, len(tutorial.CHAPTERS) + 1):
        drawn = tutorial.page(n, repo)
        assert drawn["chapter"] == n
        assert FEWEST_OPTIONS <= len(drawn["options"]) <= MOST_OPTIONS
        for option in drawn["options"]:
            assert option["label"] and option["description"] and option["preview"]


def test_a_chapter_out_of_range_is_clamped_not_refused(repo):
    """Somebody typing 9 wants the end, not an error."""
    assert tutorial.page(99, repo)["chapter"] == len(tutorial.CHAPTERS)
    assert tutorial.page(0, repo)["chapter"] == 1
    assert tutorial.page(-3, repo)["chapter"] == 1


def test_only_the_last_chapter_is_last(repo):
    for n in range(1, len(tutorial.CHAPTERS)):
        assert not tutorial.page(n, repo)["last"]
    assert tutorial.page(len(tutorial.CHAPTERS), repo)["last"]


def test_no_placeholder_survives_into_a_drawn_page(repo):
    """A `{}` left in a lesson is a demonstration that never ran."""
    for n in range(1, len(tutorial.CHAPTERS) + 1):
        for option in tutorial.page(n, repo)["options"]:
            assert "{}" not in option["preview"], f"chapter {n}: {option['label']}"


def test_a_demonstration_that_cannot_run_still_teaches(repo, monkeypatch):
    """An unbuilt repository must not stop the tutorial."""
    monkeypatch.setattr(
        tutorial.subprocess,
        "run",
        lambda *a, **k: (_ for _ in ()).throw(OSError("no")),
    )
    drawn = tutorial.page(2, repo)
    assert drawn["options"]
    for option in drawn["options"]:
        assert option["preview"].strip()
        assert "{}" not in option["preview"]


# --- what a pane looks like --------------------------------------------


def test_a_uniformly_indented_table_stays_uniform(repo, monkeypatch):
    """`.strip()` on a block takes the indent off its first line only.

    A table arrived with row one two spaces shallower than the rest, which
    then made every dedent measure against the wrong margin.
    """
    table = "\n  ai        Model-backed\n  data      Pipelines\n  service   Networked\n"
    monkeypatch.setattr(
        tutorial.subprocess,
        "run",
        lambda *a, **k: type("R", (), {"stdout": table, "stderr": ""})(),
    )
    lines = tutorial._ran("words --templates", repo).splitlines()
    assert len({len(l) - len(l.lstrip()) for l in lines}) == 1, lines


def test_nesting_under_a_heading_survives(repo, monkeypatch):
    """Flattening loses which detail belongs to which heading."""
    nested = "Most depended upon:\n  149 _say\n  126 Graph\n"
    monkeypatch.setattr(
        tutorial.subprocess,
        "run",
        lambda *a, **k: type("R", (), {"stdout": nested, "stderr": ""})(),
    )
    lines = tutorial._ran("shape", repo).splitlines()
    assert len({len(l) - len(l.lstrip()) for l in lines}) == 2, lines


def test_a_sample_covers_every_kind_rather_than_the_first_of_one():
    """Grouped output truncated to N shows one group and teaches a falsehood."""
    lines = [f"domain: d{n}" for n in range(9)] + [f"role: r{n}" for n in range(9)]
    taken = tutorial._across(lines, 6)
    assert any(l.startswith("domain:") for l in taken)
    assert any(l.startswith("role:") for l in taken)


def test_ungrouped_output_is_simply_truncated():
    lines = [f"line {n}" for n in range(20)]
    assert tutorial._across(lines, 4) == lines[:4]


def test_closing_advice_is_dropped_but_data_is_not():
    assert tutorial._is_advice("Add one with `vesta words --template <name>`.")
    assert tutorial._is_advice(
        "A template supplies words only — which definitions do the work is read."
    )
    assert not tutorial._is_advice("  ai          Model-backed systems")
    assert not tutorial._is_advice("48 finding(s): 20 swallowed failure")


# --- the instruction the agent follows ---------------------------------


def test_the_instruction_names_the_tool_and_carries_every_option(repo):
    said = tutorial.instruction(1, repo)
    assert "AskUserQuestion" in said
    for option in tutorial.page(1, repo)["options"]:
        assert option["label"] in said
        assert option["description"] in said


def test_the_instruction_forbids_summarising(repo):
    """The preview is the lesson; a summary of it is not the lesson."""
    said = tutorial.instruction(1, repo).lower()
    assert "verbatim" in said
    assert "do not summarise" in said


def test_a_middle_chapter_says_how_to_turn_the_page(repo):
    said = tutorial.instruction(2, repo)
    assert "tutorial 3" in said
    assert "last chapter" not in said


def test_the_last_chapter_does_not_loop(repo):
    said = tutorial.instruction(len(tutorial.CHAPTERS), repo)
    assert "last chapter" in said
    assert "Do not" in said


# --- resuming ----------------------------------------------------------


def test_it_resumes_where_somebody_left_off(repo):
    assert tutorial.got_to() == 1
    tutorial.instruction(3, repo)
    assert tutorial.got_to() == 3


def test_progress_survives_a_chapter_being_removed_later(repo, monkeypatch):
    """A recorded chapter beyond the end must not crash a later, shorter run."""
    tutorial.reached(99)
    assert tutorial.got_to() == len(tutorial.CHAPTERS)


def test_unreadable_progress_starts_at_the_beginning(repo, monkeypatch):
    monkeypatch.setattr(
        tutorial, "_kept", lambda: Path("/definitely/not/a/path/x.json")
    )
    assert tutorial.got_to() == 1
    # And recording into a place that cannot be written does not raise.
    tutorial.reached(2)


# --- the command -------------------------------------------------------


def test_the_command_draws_a_chapter(repo, capsys):
    from vesta.cli import main

    assert main(["tutorial", "1", "--root", str(repo)]) == 0
    assert "AskUserQuestion" in capsys.readouterr().out


def test_the_command_with_no_chapter_resumes(repo, capsys):
    from vesta.cli import main

    tutorial.reached(4)
    assert main(["tutorial", "--root", str(repo)]) == 0
    assert "chapter 4" in capsys.readouterr().out


def test_the_command_refuses_a_chapter_that_is_not_a_number(repo, capsys):
    from vesta.cli import main

    assert main(["tutorial", "words", "--root", str(repo)]) == 1
    assert "no chapter" in capsys.readouterr().out


# --- staying honest ----------------------------------------------------


def test_every_vesta_command_the_tutorial_shows_exists():
    """The same rule the guide is held to: text that drifts is believed."""
    from tests.test_commands import SUBCOMMANDS

    said = " ".join(
        t.teaches for c in tutorial.CHAPTERS for t in c.topics
    )
    for shown in set(re.findall(r"^\s*vesta (\w[\w-]*)", said, re.M)):
        assert shown in SUBCOMMANDS, f"the tutorial shows `vesta {shown}`, which does not exist"


def test_every_slash_command_the_tutorial_shows_exists():
    """The tutorial cites both surfaces, so both have to be checked."""
    here = Path(__file__).resolve().parent.parent / "commands"
    have = {path.stem for path in here.glob("*.md")}

    said = " ".join(t.teaches for c in tutorial.CHAPTERS for t in c.topics)
    for shown in set(re.findall(r"/vesta:(\w[\w-]*)", said)):
        assert shown in have, f"the tutorial shows `/vesta:{shown}`, which does not exist"


def test_the_tutorial_covers_what_a_new_user_must_know():
    """The five things this was built to teach, named so none can be dropped."""
    said = " ".join(
        t.teaches + t.label for c in tutorial.CHAPTERS for t in c.topics
    ).lower()
    for wanted in (
        "companion",       # running as companion without any thought
        "automated",       # running automated mode
        "vesta touches",   # advanced features and individual calls
        "vocabulary",      # domain model selection and editing
        "--template",      # using a supplied domain model
        "--set",           # creating your own
    ):
        assert wanted in said, f"the tutorial never mentions {wanted!r}"
