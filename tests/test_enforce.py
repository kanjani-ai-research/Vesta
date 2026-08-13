"""Checking a repository against what its user decided.

A rule nobody checks is a note. These pin the executed half — derivation is
model work and is not tested here; execution must be reproducible, because a
finding a reader cannot follow is the tool having an opinion.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from vesta.enforce import (
    CALLS_INTO,
    FILES_LACKING,
    COUNT_AT_LEAST,
    COUNT_AT_MOST,
    FILES_MATCHING,
    NAMES_MATCHING,
    Check,
    Finding,
    run_check,
)
from vesta.graph import Edge, Graph, Node


@pytest.fixture
def repo(tmp_path: Path) -> tuple[Graph, Path]:
    (tmp_path / "a.py").write_text("def loader():\n    pass\n", encoding="utf-8")
    (tmp_path / "b.py").write_text("def other():\n    pass\n", encoding="utf-8")
    nodes = [
        Node(id="n1", name="load_config", path="a.py", line=0, kind=12),
        Node(id="n2", name="other", path="b.py", line=0, kind=12),
    ]
    graph = Graph(root=str(tmp_path), nodes={n.id: n for n in nodes},
                  edges=[Edge(source="n2", target="n1")])
    return graph, tmp_path


def test_a_rule_that_holds_reports_nothing(repo):
    graph, root = repo
    check = Check(look_for=FILES_MATCHING, pattern=r"\.env$",
                  holds_when=COUNT_AT_MOST, how_many=1, tests_the_rule=True)

    sites, why = run_check(check, graph, root)
    assert not sites and not why


def test_a_rule_that_is_broken_names_the_sites(repo):
    graph, root = repo
    (root / ".env").write_text("X=1\n", encoding="utf-8")
    (root / "sub").mkdir()
    (root / "sub" / ".env").write_text("Y=2\n", encoding="utf-8")

    check = Check(look_for=FILES_MATCHING, pattern=r"\.env$",
                  holds_when=COUNT_AT_MOST, how_many=1, tests_the_rule=True)
    sites, _ = run_check(check, graph, root)

    assert len(sites) == 2
    assert {s.path for s in sites} == {".env", "sub/.env"}


def test_a_check_that_cannot_test_the_rule_decides_nothing(repo):
    """A live derivation supplied a pattern matching every source file while
    its own reason said the rule could not be tested. Executing it accused the
    user of thirty-five violations, and a user accused thirty-five times over
    stops believing any of it."""
    graph, root = repo
    check = Check(look_for=FILES_MATCHING, pattern=r".*\.py$",
                  holds_when=COUNT_AT_MOST, how_many=0,
                  why="requires reading comment text", tests_the_rule=False)

    sites, why = run_check(check, graph, root)

    assert not sites
    assert "comment text" in why


def test_a_malformed_pattern_decides_nothing(repo):
    graph, root = repo
    check = Check(look_for=FILES_MATCHING, pattern="[unclosed",
                  holds_when=COUNT_AT_MOST, how_many=0, tests_the_rule=True)

    sites, why = run_check(check, graph, root)
    assert not sites
    assert "malformed" in why


def test_finding_none_of_a_presence_decides_nothing(repo):
    """Absence of the subject is not evidence about the rule.

    A rule about langextract, checked in a repository containing no langextract
    anywhere, was reported broken with a site pointing at the repository root.
    Nothing was found because the subject is not here, which settles neither
    way.
    """
    graph, root = repo
    check = Check(look_for=NAMES_MATCHING, pattern=r"^test_",
                  holds_when=COUNT_AT_LEAST, how_many=1, tests_the_rule=True)

    sites, why = run_check(check, graph, root)
    assert not sites
    assert "neither honoured nor broken" in why


def test_finding_none_of_an_absence_honours_the_rule(repo):
    """`files_lacking` enumerates the violations themselves, so finding none
    of them is the rule holding — "every file must have a docstring" was called
    undecidable in a repository where every file has one."""
    graph, root = repo
    check = Check(look_for=FILES_LACKING, pattern=r"def ", within=r"\.py$",
                  holds_when=COUNT_AT_LEAST, how_many=1, tests_the_rule=True)

    sites, why = run_check(check, graph, root)
    assert not sites and not why


def test_at_least_is_broken_by_too_few(repo):
    """Some, but fewer than required, is a genuine violation."""
    graph, root = repo
    check = Check(look_for=NAMES_MATCHING, pattern=r"load|other",
                  holds_when=COUNT_AT_LEAST, how_many=5, tests_the_rule=True)

    sites, why = run_check(check, graph, root)
    assert sites and not why


def test_definitions_reaching_a_name_are_found(repo):
    graph, root = repo
    check = Check(look_for=CALLS_INTO, pattern=r"load_config",
                  holds_when=COUNT_AT_MOST, how_many=0, tests_the_rule=True)

    sites, _ = run_check(check, graph, root)
    assert [s.what for s in sites] == ["other"]


def test_an_unknown_kind_of_check_decides_nothing(repo):
    graph, root = repo
    check = Check(look_for="telepathy", pattern=".", tests_the_rule=True)

    sites, why = run_check(check, graph, root)
    assert not sites and "unknown" in why


def test_a_finding_carries_the_words_it_came_from():
    """An agent told "this violates a constraint" will ask whose constraint."""
    finding = Finding(rule="one .env for the family", said="there should be one .env for v3")

    assert finding.holds
    assert "one .env for v3" in finding.said


def test_pasted_output_is_not_a_rule():
    """A user pasting an error is showing something, not deciding something —
    and a rule recovered from Vesta's own output is Vesta recording its own
    words as the user's."""
    from vesta.rules import constrains

    assert not constrains(
        "Vesta is not installed in a way this session can reach.\n"
        "  pip install vesta   (or set VESTA_PYTHON to an interpreter)"
    )
    assert not constrains(
        "❯ /vesta:help\n  ⎿ UserPromptSubmit hook error\n"
        "  ⎿ Failed with non-blocking status: python: command not found\n  ✘ vesta"
    )


def test_a_sentence_quoting_output_is_still_a_rule():
    """The quote is context that makes the instruction legible. Rejecting on
    presence rather than proportion would discard the real rule with it."""
    from vesta.rules import constrains

    assert constrains(
        'the namespace "❯ plugin:vesta:vesta · ✔ connected" should be '
        "causum:vesta, not vesta:vesta"
    )


def test_vestas_own_output_is_not_a_users_rule():
    """A slash command puts its output and its instructions into the prompt,
    the transcript records that, and the next harvest reads it as something the
    user decided. Those sentences are imperative, so they pass every other test
    for a constraint — and enforcing them would hold agents to Vesta's own
    help text."""
    from vesta.rules import constrains

    assert not constrains(
        "Vesta is not installed in a way this session can reach.\n"
        "  pip install vesta   (or set VESTA_PYTHON to an interpreter that has it)\n\n"
        "Show the guide above to the user verbatim. Do not summarise it or add to it."
    )
    assert not constrains(
        "Show these definitions verbatim. If nothing was found, say so plainly."
    )


def test_a_rule_stated_as_a_definition_is_still_a_rule():
    """People say what something *is* at least as often as what to do about it.

    Four rules about which mode may do what were all stated declaratively —
    "non-full auto is a companion, no consent" — none was captured, and the
    constraint they described was violated within the hour with nothing to
    notice. Matching only imperatives threw away every rule stated this way.
    """
    from vesta.rules import constrains

    assert constrains("non-full auto is a companion, no consent")
    assert constrains("the consent is only for full auto mode")
    assert constrains("the stuck signal does not apply to companion mode")
    assert constrains(
        "none of the decision management from the autonomous loop applies to "
        "the companion mode"
    )
    assert constrains("the graph is a tree, no cycles")


def test_a_definition_about_nothing_is_still_not_a_rule():
    from vesta.rules import constrains

    assert not constrains("this is a nice day, no rain at all today thankfully")
    assert not constrains("run the tests again")
    assert not constrains("what does the companion mode do")


def test_somebody_saying_they_do_not_know_is_not_stating_a_rule():
    """Found in the live queue, awaiting a confirmation they had disclaimed.

    "it should be conditional, I don't know whether your assertion holds"
    reached adjudication as a candidate rule — a sentence in which the user
    had already said they could not settle it. CONSTRAINS matches "should",
    and nothing tested whether the same sentence withdrew the claim.

    A queue full of these teaches somebody the feature is noise, and then they
    stop reading the ones that are real.
    """
    from vesta.rules import constrains

    assert not constrains(
        "it should be conditional, I don't know whether your assertion holds. "
        "i just know it's conditional"
    )
    assert not constrains(
        "for question 1, I don't know but I can't see how UC3 is fundamentally "
        "different from UC2 in this respect"
    )
    assert not constrains(
        "i'm not sure if the graph should be rebuilt on every change or cached"
    )
    assert not constrains(
        "not sure whether the ontology should carry the kind at all really"
    )


def test_the_unsure_guard_does_not_swallow_ordinary_rules():
    """The guard is a whole-sentence veto, and that is a deliberate trade.

    "I don't know why, but every module must open with a docstring" states a
    constraint and disclaims only the *reason* — and this rejects it, because
    nothing here parses which clause the disclaimer attaches to.

    That is the right way to be wrong. A missed rule costs a user one
    `/vesta:declare`; a queue of candidates they have already said they cannot
    settle costs them their willingness to look at the queue at all.
    """
    from vesta.rules import constrains

    assert constrains("every module must open with a docstring")
    assert constrains("non-full auto is a companion, no consent")

    # Stated plainly, the sentence is kept. The disclaimer is what loses it.
    assert not constrains(
        "I don't know why, but every module must open with a docstring"
    )


# ── Reporting what was and was not checked ──────────────────────────────────


def test_a_rule_nothing_ran_against_is_not_counted_as_checked():
    """The line a user saw first, and it read as three violations.

    `describe` counted every finding as "checked" whatever happened, so three
    rules that nothing could test printed as "3 rule(s) checked, 0 held, 3
    could not be checked" — which a reader takes as three failures. Nothing
    ran. Saying so is the whole fix.
    """
    from vesta.enforce import Finding, Verdict

    verdict = Verdict(
        findings=[
            Finding(rule=f"rule {n}", said=f"rule {n}", undecided="nothing here can check this")
            for n in range(3)
        ]
    )
    said = verdict.describe()

    assert "nothing could be checked" in said
    assert "0 held" not in said
    assert "3 rule(s) checked" not in said


def test_what_ran_and_what_did_not_are_counted_apart():
    from vesta.enforce import Finding, Site, Verdict

    verdict = Verdict(
        findings=[
            Finding(rule="held one", said="held one"),
            Finding(rule="broken one", said="broken one", sites=[Site(path="a.py", line=1)]),
            Finding(rule="unchecked one", said="unchecked one", undecided="no check was written"),
        ]
    )
    said = verdict.describe()

    # Two ran; the third did not and must not inflate the denominator.
    assert "2 rule(s) checked" in said
    assert "1 held" in said
    assert "1 broken" in said
    assert "1 not checked" in said


def test_the_reason_a_rule_could_not_be_checked_is_kept():
    """It was computed and thrown away, so a user got a number they could not
    act on — and could not tell an unverifiable rule from a verified one."""
    from vesta.enforce import Finding, Verdict

    verdict = Verdict(
        findings=[Finding(rule="modes thing", said="modes thing", undecided="nothing here can check a rule of this kind")]
    )
    assert verdict.undecided
    assert verdict.undecided[0].undecided


# ── Whose words these are ───────────────────────────────────────────────────


def test_a_compaction_summary_is_not_the_user_speaking():
    """The mechanism that turned a test fixture into somebody's decision.

    A summary replays an entire conversation as one turn recorded with
    `role: user`, so every rule-shaped sentence in the digest is harvested
    again as though freshly stated. There were 53 of these in this project's
    transcripts and 357 across all of them.
    """
    from vesta.rules import _not_the_user

    assert _not_the_user(
        "This session is being continued from a previous conversation that ran "
        "out of context. The summary below covers the earlier portion."
    )
    assert _not_the_user(
        "Caveat: The messages below were generated while summarising."
    )
    assert not _not_the_user("every module must open with a docstring")


def test_an_assistant_turn_echoed_back_is_not_the_user():
    from vesta.rules import _not_the_user

    assert _not_the_user("⏺ I'll check what the project has recorded first.")
    assert _not_the_user("[Request interrupted by user]")


def test_source_being_shown_is_not_a_decision():
    """A sentence inside a string literal is not something somebody decided.

    `in this project every module must open with a docstring` sat in the
    candidate queue as a user's rule while existing nowhere but as fixture
    data in `tests/test_seams.py`.
    """
    from vesta.rules import constrains

    assert not constrains("def f():\n    return 1\n")
    assert not constrains("here is the fix:\n\n```python\nx = 1\n```")
    assert not constrains('you must use SQLite\n\n    assert constrains("x")')


def test_showing_code_does_not_swallow_a_rule_about_code():
    """Naming an identifier is not the same as pasting a definition."""
    from vesta.rules import constrains

    assert constrains("the namespace should be causum:vesta, not vesta:vesta")
    assert constrains(
        "always import from vesta.home, never construct the path yourself"
    )


def test_a_turn_that_closes_by_asking_is_a_question():
    """`ASKS_ABOUT_IT` anchors at the start, so an imperative that *ends* in a
    question slipped through — "address the extraction now instead of shifting
    it in the document, or are you saying it's not worth doing?" was captured
    as a standing rule."""
    from vesta.rules import constrains

    assert not constrains(
        "address the extraction now instead of shifting it in the document, "
        "or are you saying it's not worth doing rn?"
    )
    assert not constrains(
        "we should use SQLite for this, or do you think postgres is better?"
    )


def test_stating_a_rule_then_asking_about_it_is_still_a_rule():
    """The distinction the whole guard turns on. Somebody who states a
    constraint and then asks whether the code honours it has stated one."""
    from vesta.rules import constrains

    assert constrains(
        "every module must open with a docstring — does resolve.py follow that?"
    )
    assert constrains(
        "in this project every module must open with a docstring saying what "
        "it is for. can you check whether resolve.py follows that?"
    )


# ── Every turn reaches the thing that can judge it ──────────────────────────


def test_the_patterns_rank_rather_than_gate(tmp_path):
    """The architectural defect behind poor extraction.

    `constrains` was a hard filter in front of the model, so on this
    repository haiku saw 42 of 446 turns — 9.4%. Everything in the other 404
    was invisible and no prompt could recover it, because nothing was asked.
    Among them: "it shouldn't be configurable, commit or change main/active
    should write to FS-", a standing architectural decision phrased in a way
    no pattern anticipated.
    """
    from vesta.rules import constrains, worth_reading

    unanticipated = (
        "it shouldn't be configurable, commit or change main/active should "
        "write to FS-"
    )
    # The pattern misses it — which is fine, so long as it is still read.
    assert not constrains(unanticipated)
    assert worth_reading(unanticipated) > 0


def test_an_obvious_rule_outranks_chatter():
    from vesta.rules import worth_reading

    rule = "there should be one .env for v3, not one for each repo"
    chatter = "ok"

    assert worth_reading(rule) > worth_reading(chatter)


def test_what_is_certainly_not_the_user_scores_nothing():
    """Scoring zero is the one way a turn is dropped, and it is reserved for
    things that are not the user speaking at all."""
    from vesta.rules import worth_reading

    assert worth_reading("⏺ I'll check that first.") == 0
    assert worth_reading("def f():\n    return 1\n") == 0
    assert (
        worth_reading(
            "This session is being continued from a previous conversation "
            "that ran out of context."
        )
        == 0
    )


def test_hedged_and_turn_scoped_turns_rank_low_but_are_still_read():
    """They are usually not rules, and occasionally they are. Ranking says
    'read these last'; it must not say 'never read these'."""
    from vesta.rules import worth_reading

    hedged = "i'm not sure if the graph should be rebuilt on every change"
    plain = "the graph must be rebuilt on every change"

    assert 0 < worth_reading(hedged) < worth_reading(plain)


def test_a_rule_quoting_words_nobody_said_is_refused():
    """Borrowed from langextract's discipline: make the model return exact
    source text, then verify it against the source rather than trusting it.

    A rule recorded against words the user never said hands somebody an
    obligation they never made and attributes it to them.
    """
    from vesta.rules import read_judged

    turns = ["there should be one .env for v3, not one for each repo"]
    judged = (
        "artefact | There is one .env for the workspace. | there should be "
        "one .env for v3, not one for each repo\n"
        "artefact | Every file is under 200 lines. | keep every file under "
        "two hundred lines\n"
    )

    kept = read_judged(judged, turns=turns)
    assert [r.stated for r in kept] == ["There is one .env for the workspace."]


def test_a_trimmed_quotation_is_still_grounded():
    """An agent quoting a long turn will reasonably trim it. What is refused
    is a quotation appearing in no turn at all, not an inexact one."""
    from vesta.rules import read_judged

    turns = [
        "like I said originally, things like openai key and anthropic key are "
        "shared by multiple services. there should be one .env for v3, not "
        "one .env for each repo"
    ]
    judged = (
        "artefact | There is one .env for the workspace. | there should be "
        "one .env for v3, not one .env for each repo\n"
    )

    assert len(read_judged(judged, turns=turns)) == 1


def test_grounding_is_skipped_when_there_is_nothing_to_check_against():
    """Callers that have no transcript still work; verification is opt-in by
    supplying the turns."""
    from vesta.rules import read_judged

    judged = "artefact | A rule about something. | words nobody in particular said\n"
    assert len(read_judged(judged)) == 1
