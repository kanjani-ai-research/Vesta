"""Editing and templating the words a project uses.

The two things worth holding: an edit that drops a word must not leave the map
asserting a definition does something nothing is called any more, and a
template must never be able to claim a binding — because a template has not
read the repository it is being added to.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from vesta import vocabulary
from vesta.derive import read_terms, write_terms


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """A project with a home of its own, so tests do not share an ontology."""
    monkeypatch.setenv("VESTA_HOME", str(tmp_path / "home"))
    where = tmp_path / "project"
    where.mkdir()
    (where / "ledger.py").write_text(
        "def record(entry):\n"
        "    return entry\n"
        "\n"
        "def balance(entries):\n"
        "    return sum(entries)\n",
        encoding="utf-8",
    )
    return where


def test_shows_what_was_named(repo):
    write_terms(repo, "domain: keeping books that balance\nactivity: record a transaction\n")
    said = vocabulary.as_text(repo, preamble=False)
    assert "domain: keeping books that balance" in said
    assert "activity: record a transaction" in said


def test_round_trips_through_the_edit_format(repo):
    write_terms(repo, "domain: keeping books\nrole: a posting\nactivity: record it\n")
    said = vocabulary.as_text(repo, preamble=False)
    # What comes out must parse back to what went in, or editing loses words.
    assert {t.label for t in read_terms(said)} == {
        "keeping books",
        "a posting",
        "record it",
    }


def test_grouped_by_kind_so_a_diff_is_readable(repo):
    write_terms(
        repo,
        "activity: b\ndomain: a\nrole: c\nactivity: a\n",
    )
    lines = [l for l in vocabulary.as_text(repo, preamble=False).splitlines() if l.strip()]
    kinds = [l.split(":")[0] for l in lines]
    assert kinds == sorted(kinds, key=["domain", "activity", "role"].index)


def test_an_edit_that_adds_and_removes_is_reported(repo):
    write_terms(repo, "domain: keeping books\nactivity: record a transaction\n")
    edited = vocabulary.apply(repo, "domain: keeping books\nactivity: report a balance\n")
    assert edited.added == ["report a balance"]
    assert edited.removed == ["record a transaction"]
    assert edited.kept == 2
    assert edited.changed


def test_an_unchanged_edit_changes_nothing(repo):
    write_terms(repo, "domain: keeping books\n")
    edited = vocabulary.apply(repo, vocabulary.as_text(repo))
    assert not edited.changed
    assert edited.kept == 1


def test_removing_a_word_removes_what_was_attached_to_it(repo):
    """The reconciliation this module exists for.

    `write_terms` replaces the ontology and `write_attachments` adds to the
    map, so without this an edited-away word leaves attachments naming it.
    """
    from vesta.traverse import Attachment, Map
    from vesta.traverse import keep as keep_map
    from vesta.traverse import recall as recall_map

    write_terms(repo, "domain: keeping books\nactivity: record a transaction\n")
    keep_map(
        Map(
            ontology="test",
            attachments=[
                Attachment(
                    node="n1", term="t1", label="record a transaction",
                    kind="activity", strength=1.0, how="read",
                ),
                Attachment(
                    node="n2", term="t2", label="keeping books",
                    kind="domain", strength=1.0, how="read",
                ),
            ],
        ),
        repo,
    )

    edited = vocabulary.apply(repo, "domain: keeping books\n")

    assert edited.orphaned == 1
    mapped = recall_map(repo)
    assert [a.label for a in mapped.attachments] == ["keeping books"]
    assert "dropped" in edited.describe()


def test_an_edit_is_not_blamed_for_drift_it_only_found(repo):
    """The defect a live run caught.

    Merging a template into this repository's own vocabulary dropped 135
    attachments while removing no word at all: they had gone stale earlier,
    because `write_terms` replaces an ontology and nothing reconciled the map.
    Reporting that as the merge's doing blames an edit for a fault it found.
    """
    from vesta.traverse import Attachment, Map
    from vesta.traverse import keep as keep_map

    write_terms(repo, "domain: keeping books\n")
    keep_map(
        Map(
            ontology="test",
            attachments=[
                Attachment(
                    node="n1", term="t1", label="keeping books",
                    kind="domain", strength=1.0, how="read",
                ),
                Attachment(
                    node="n2", term="t2", label="a word nobody kept",
                    kind="domain", strength=1.0, how="read",
                ),
            ],
        ),
        repo,
    )

    # Adds a word, removes none. Anything dropped was already stale.
    edited = vocabulary.merge(repo, "activity: call a model\n")

    assert edited.removed == []
    assert edited.orphaned == 1
    assert edited.stale == 1

    said = edited.describe()
    assert "already naming words" in said
    assert "were removed" not in said


def test_an_edit_that_really_removes_a_word_says_so(repo):
    from vesta.traverse import Attachment, Map
    from vesta.traverse import keep as keep_map

    write_terms(repo, "domain: keeping books\nactivity: record a transaction\n")
    keep_map(
        Map(
            ontology="test",
            attachments=[
                Attachment(
                    node="n1", term="t1", label="record a transaction",
                    kind="activity", strength=1.0, how="read",
                ),
            ],
        ),
        repo,
    )

    edited = vocabulary.apply(repo, "domain: keeping books\n")

    assert edited.orphaned == 1
    assert edited.stale == 0
    assert "were removed" in edited.describe()


def test_an_edit_that_binds_everything_clears_the_unattached_list(repo):
    """The second defect the live run caught.

    Writing the map only when something changed meant an edit whose correct
    `unattached` was empty never wrote it — so a stale list survived, and the
    map reported 55 words unattached that were not in the vocabulary at all.
    """
    from vesta.traverse import Attachment, Map
    from vesta.traverse import keep as keep_map
    from vesta.traverse import recall as recall_map

    write_terms(repo, "domain: keeping books\nactivity: a word nobody bound\n")
    keep_map(
        Map(
            ontology="test",
            unattached=["a word nobody bound"],
            attachments=[
                Attachment(
                    node="n1", term="t1", label="keeping books",
                    kind="domain", strength=1.0, how="read",
                ),
            ],
        ),
        repo,
    )

    # Cut back to only the word that is bound. Nothing is dropped, and the
    # correct `unattached` is empty.
    vocabulary.apply(repo, "domain: keeping books\n")

    assert recall_map(repo).unattached == []


def test_a_word_with_nothing_attached_is_kept_and_reported_unattached(repo):
    """A vocabulary is yours. A word naming nothing is information."""
    from vesta.traverse import recall as recall_map

    write_terms(repo, "domain: keeping books\n")
    vocabulary.apply(repo, "domain: keeping books\nactivity: a thing nobody wrote\n")

    said = vocabulary.as_text(repo, preamble=False)
    assert "a thing nobody wrote" in said

    mapped = recall_map(repo)
    if mapped is not None:
        assert "a thing nobody wrote" in mapped.unattached


def test_editor_is_visual_then_editor_then_vi(monkeypatch):
    monkeypatch.delenv("VISUAL", raising=False)
    monkeypatch.delenv("EDITOR", raising=False)
    assert vocabulary._editor() == ["vi"]

    monkeypatch.setenv("EDITOR", "nano")
    assert vocabulary._editor() == ["nano"]

    monkeypatch.setenv("VISUAL", "code -w")
    assert vocabulary._editor() == ["code", "-w"]


def test_quitting_without_saving_changes_nothing(repo):
    write_terms(repo, "domain: keeping books\n")
    # An editor that does nothing to the file is somebody quitting.
    edited = vocabulary.edit(repo, editor=["true"])
    assert not edited.changed
    assert edited.kept == 1


def test_editing_keeps_what_comes_back(repo):
    write_terms(repo, "domain: keeping books\n")
    script = repo / "editor.sh"
    script.write_text(
        "#!/bin/sh\nprintf 'domain: keeping books\\nrole: a posting\\n' > \"$1\"\n",
        encoding="utf-8",
    )
    script.chmod(0o755)

    edited = vocabulary.edit(repo, editor=["sh", str(script)])
    assert edited.added == ["a posting"]
    assert "a posting" in vocabulary.as_text(repo, preamble=False)


def test_an_editor_that_cannot_run_keeps_what_was_there(repo):
    write_terms(repo, "domain: keeping books\n")
    edited = vocabulary.edit(repo, editor=["definitely-not-an-editor-xyz"])
    assert not edited.changed
    assert "keeping books" in vocabulary.as_text(repo, preamble=False)


# --- templates ---------------------------------------------------------


def test_every_shipped_template_parses_and_describes_itself():
    shipped = vocabulary.templates()
    assert shipped, "no templates are shipped"
    for name, why in shipped.items():
        assert why, f"{name} has no description"
        text, wrong = vocabulary.read_template(name)
        assert wrong is None
        assert len(read_terms(text)) >= 10, f"{name} names too little to be useful"


def test_no_template_can_carry_an_attachment():
    """The constraint the whole design turns on.

    A template has never seen the repository it is added to. If it could claim
    that a file does something, Vesta would assert a binding nobody derived —
    the exact failure this project is shaped against.
    """
    from vesta.derive import ATTACHMENT

    for name in vocabulary.templates():
        text, _ = vocabulary.read_template(name)
        for line in text.splitlines():
            assert not ATTACHMENT.match(line), f"{name} carries an attachment: {line}"


def test_a_template_adds_words_without_removing_yours(repo):
    write_terms(repo, "domain: keeping books that balance\n")
    text, _ = vocabulary.read_template("security")
    edited = vocabulary.merge(repo, text)

    assert edited.added
    assert not edited.removed
    assert "keeping books that balance" in vocabulary.as_text(repo, preamble=False)


def test_a_template_attaches_nothing(repo):
    """Words arrive; bindings do not."""
    from vesta.traverse import recall as recall_map

    write_terms(repo, "domain: keeping books\n")
    text, _ = vocabulary.read_template("security")
    vocabulary.merge(repo, text)

    mapped = recall_map(repo)
    assert mapped is None or mapped.attachments == []


def test_merging_the_same_template_twice_adds_nothing(repo):
    write_terms(repo, "domain: keeping books\n")
    text, _ = vocabulary.read_template("data")
    vocabulary.merge(repo, text)
    again = vocabulary.merge(repo, text)
    assert not again.added


def test_a_word_already_present_is_not_duplicated_by_case(repo):
    write_terms(repo, "activity: Validate An Untrusted Input\n")
    text, _ = vocabulary.read_template("security")
    vocabulary.merge(repo, text)

    said = vocabulary.as_text(repo, preamble=False).lower()
    assert said.count("validate an untrusted input") == 1


def test_an_unknown_template_says_what_there_is():
    text, wrong = vocabulary.read_template("nonesuch")
    assert text == ""
    assert "no template" in wrong
    assert "security" in wrong


def test_a_supplied_file_is_read(repo, tmp_path):
    supplied = tmp_path / "ours.md"
    supplied.write_text(
        "# our words\n\nWhatever prose we like.\n\ndomain: settling trades\n",
        encoding="utf-8",
    )
    write_terms(repo, "domain: keeping books\n")
    edited = vocabulary.merge(repo, vocabulary.read_supplied(str(supplied))[0])
    assert edited.added == ["settling trades"]


def test_a_missing_supplied_file_says_so():
    text, wrong = vocabulary.read_supplied("/no/such/file.md")
    assert text == ""
    assert "no such file" in wrong


def test_a_supplied_file_claiming_an_attachment_is_not_heard(repo):
    """A file can say what it likes about bindings; nothing reads it."""
    from vesta.traverse import recall as recall_map

    write_terms(repo, "domain: keeping books\n")
    vocabulary.merge(
        repo,
        "domain: settling trades\nledger.py:1 record | settling trades\n",
    )

    mapped = recall_map(repo)
    assert mapped is None or mapped.attachments == []
    assert "settling trades" in vocabulary.as_text(repo, preamble=False)


def test_prose_around_the_words_is_ignored(repo):
    write_terms(repo, "domain: keeping books\n")
    edited = vocabulary.merge(
        repo,
        "# A heading\n\nSome explanation of why.\n\n- a bullet\n\ndomain: settling trades\n",
    )
    assert edited.added == ["settling trades"]


# --- the command -------------------------------------------------------


def test_the_command_shows_the_words(repo, capsys):
    from vesta.cli import main

    write_terms(repo, "domain: keeping books that balance\n")
    assert main(["words", "--root", str(repo)]) == 0
    assert "keeping books that balance" in capsys.readouterr().out


def test_the_command_lists_templates(capsys):
    from vesta.cli import main

    assert main(["words", "--templates"]) == 0
    said = capsys.readouterr().out
    assert "security" in said
    assert "embedded" in said


def test_the_command_refuses_an_unknown_template(repo, capsys):
    from vesta.cli import main

    assert main(["words", "--template", "nonesuch", "--root", str(repo)]) == 1
    assert "no template" in capsys.readouterr().out


def test_set_replaces_so_a_deletion_takes_effect(repo, tmp_path, capsys):
    """The difference between `--from` and `--set`.

    Exporting the words, deleting a line, and re-importing must remove it.
    `--from` merges, so it never could — which would make editing by export
    silently lossless in the wrong direction.
    """
    from vesta.cli import main

    write_terms(repo, "domain: keeping books\nactivity: record a transaction\n")
    edited = tmp_path / "words.txt"
    edited.write_text("domain: keeping books\n", encoding="utf-8")

    assert main(["words", "--set", str(edited), "--root", str(repo)]) == 0
    said = vocabulary.as_text(repo, preamble=False)
    assert "record a transaction" not in said
    assert "keeping books" in said


def test_from_only_ever_adds(repo, tmp_path):
    """The other half of the same distinction."""
    from vesta.cli import main

    write_terms(repo, "domain: keeping books\nactivity: record a transaction\n")
    supplied = tmp_path / "words.txt"
    supplied.write_text("domain: keeping books\n", encoding="utf-8")

    assert main(["words", "--from", str(supplied), "--root", str(repo)]) == 0
    assert "record a transaction" in vocabulary.as_text(repo, preamble=False)


def test_set_refuses_an_empty_file(repo, tmp_path, capsys):
    """A redirect that went wrong must not delete a vocabulary."""
    from vesta.cli import main

    write_terms(repo, "domain: keeping books\n")
    empty = tmp_path / "nothing.txt"
    empty.write_text("# only a comment\n", encoding="utf-8")

    assert main(["words", "--set", str(empty), "--root", str(repo)]) == 1
    assert "names no words" in capsys.readouterr().out
    assert "keeping books" in vocabulary.as_text(repo, preamble=False)


def test_what_the_command_prints_can_be_fed_back_to_it(repo, tmp_path):
    """The round trip the slash command tells an agent to perform."""
    from vesta.cli import main

    write_terms(
        repo,
        "domain: keeping books\nactivity: record a transaction\nrole: a posting\n",
    )
    printed = vocabulary.as_text(repo, preamble=False) + "\nEdit them with `x`.\n"
    through = tmp_path / "words.txt"
    through.write_text(printed, encoding="utf-8")

    assert main(["words", "--set", str(through), "--root", str(repo)]) == 0
    # The trailing hint is a comment, and nothing was lost or invented.
    assert len(read_terms(vocabulary.as_text(repo, preamble=False))) == 3


def test_the_command_says_what_to_do_when_there_are_no_words(repo, capsys):
    from vesta.cli import main

    assert main(["words", "--root", str(repo)]) == 0
    said = capsys.readouterr().out
    assert "--templates" in said
