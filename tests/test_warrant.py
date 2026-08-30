"""Whether a decision space contracts as work approaches its output.

Narrowing here is a property of a trajectory, not of a phrase. The first
version of this module measured how much of a repository a set of words
touched, which is a fact about vocabulary and says nothing about whether a
decision is being made — a single snapshot cannot distinguish a space that
narrowed from one that started small.

So every test here compares steps. The cases that matter are the ones where a
count alone would mislead: a space that begins narrow, one that contracts on
sites while leaving the output undecided, and one that keeps producing steps
without ruling anything out.
"""

from __future__ import annotations

import pytest

from vesta.graph import Edge, Graph, Node
from vesta.space import Basis, Verdict
from vesta.traverse import Attachment, Map
from vesta.warrant import (
    MOVED,
    STUCK_AFTER,
    Convergence,
    narrow,
    open_space,
    track,
)


def node(name: str, path: str = "x.py", line: int = 1) -> Node:
    return Node(id=f"{path}:{line}:{name}", name=name, path=path, line=line, kind=12)


@pytest.fixture
def code() -> Graph:
    """One connected cluster about retries, and a lot of unrelated code."""
    nodes = [
        node("parse_retry", "retry.py", 10),
        node("backoff", "retry.py", 30),
        node("send", "http.py", 10),
        *[node(f"unrelated_{i}", f"other/m{i}.py", 5) for i in range(60)],
    ]
    graph = Graph(root="/x", nodes={n.id: n for n in nodes})
    graph.edges = [
        Edge(source="retry.py:10:parse_retry", target="retry.py:30:backoff"),
        Edge(source="http.py:10:send", target="retry.py:10:parse_retry"),
    ]
    return graph


@pytest.fixture
def mapped() -> Map:
    return Map(
        ontology="test",
        attachments=[
            Attachment(
                node="retry.py:10:parse_retry",
                term="activity:1",
                label="retry a failed request with a growing delay",
                kind="activity",
                strength=1.0,
                how="read",
            )
        ],
    )


def test_the_space_starts_open(code):
    """Step zero is the denominator, and it has to be recorded to be one.

    A trajectory whose first step is already narrow has not narrowed — it
    started small — and without an open space to measure against, the two are
    indistinguishable.
    """
    start = open_space("retry a failed request", code)

    assert start.sites == 63, "every non-test definition is admissible"
    assert start.outputs == 0, "open, not decided"
    assert start.share == 1.0


def test_applying_the_ontology_contracts_the_space(code, mapped):
    """The first real narrowing: vocabulary plus one hop of the graph."""
    start = open_space("retry a failed request", code)
    after = narrow(
        start, code, mapped, "retry a failed request", "named by the ontology"
    )

    assert after.sites == 3, "one named, two reached at one hop"
    assert after.sites < start.sites
    assert track("retry a failed request", [start, after]).contracting


def test_every_exclusion_says_why(code, mapped):
    """A candidate that vanished without a reason is indistinguishable from one
    nobody considered. Told "3 sites remain", a reader must be able to ask what
    happened to the other 60.
    """
    start = open_space("retry a failed request", code)
    after = narrow(start, code, mapped, "retry a failed request", "ontology")

    assert len(after.witness) == 60
    assert all(w.reason for w in after.witness)
    assert after.sound == 60

    gone = track("x", [start, after]).why_gone("unrelated_3")
    assert gone and "no term the ontology names reaches this" in gone[0].reason


def test_a_demotion_does_not_remove_a_candidate(code, mapped):
    """Only a sound prune closes the space.

    Collapsing the two would let "this is lower priority" or "nothing could
    check this" silently do the work of "this is certainly not it", which is the
    distinction `space` exists to keep.
    """
    start = open_space("retry a failed request", code)
    named = narrow(start, code, mapped, "retry a failed request", "ontology")

    def deprioritise(node_id: str):
        if node_id == "http.py:10:send":
            return (Verdict.DEMOTE, "further from the change than the others")
        return None

    after = narrow(
        named, code, mapped, "retry a failed request", "priority", excludes=deprioritise
    )

    assert after.sites == named.sites, "a demotion is reversible, so it stays"
    assert any(w.verdict == Verdict.DEMOTE for w in after.witness)


def test_a_gap_is_emitted_not_dropped(code):
    """A step that narrows nothing because it could not read the question is a
    different fact from one that narrows nothing because everything applies.
    """
    empty = Map(ontology="test", attachments=[])
    start = open_space("encrypt user passwords", code)
    after = narrow(start, code, empty, "encrypt user passwords", "ontology")

    assert after.sites == start.sites, "nothing was ruled out"
    assert after.gaps == 1
    assert "vocabulary" in after.witness[-1].reason


def test_convergence_needs_both_axes(code, mapped):
    """Knowing exactly where the code goes is not knowing what it should do.

    An agent that has narrowed to one definition with the output still open has
    not decided what it is building, and reporting that as converged is the
    familiar half-success this is built to catch.
    """
    start = open_space("retry a failed request", code)
    sited = narrow(start, code, mapped, "retry a failed request", "ontology")

    def only_one(node_id: str):
        if node_id != "retry.py:10:parse_retry":
            return (Verdict.SOUND_PRUNE, "the rule places this work in retry.py")
        return None

    one_site = narrow(
        sited, code, mapped, "retry a failed request", "rule", excludes=only_one
    )
    assert one_site.sites == 1

    assert not track("x", [start, sited, one_site]).converged, "output still open"

    decided = narrow(
        one_site, code, mapped, "retry a failed request", "contract", outputs=1
    )
    assert track("x", [start, sited, one_site, decided]).converged


def test_a_space_that_stops_contracting_is_stuck(code, mapped):
    """The signal a model judging its own work cannot produce.

    Three steps that rule nothing out is the same shape of fact
    `driving.State.stuck` makes about readings, arriving on a second and
    independent axis.
    """
    start = open_space("retry a failed request", code)
    sited = narrow(start, code, mapped, "retry a failed request", "ontology")

    steps = [start, sited]
    for n in range(STUCK_AFTER):
        steps.append(
            narrow(steps[-1], code, mapped, "retry a failed request", f"step {n}")
        )

    trajectory = track("retry a failed request", steps)

    assert trajectory.stuck
    assert not trajectory.contracting
    assert "not converging" in trajectory.describe()
    assert "elaborated rather than decided" in trajectory.describe()


def test_one_step_that_rules_nothing_out_is_not_stuck(code, mapped):
    """A step spent establishing context is ordinary. Three in a row is a
    pattern — the same reasoning that makes `driving.STUCK_AFTER` three.
    """
    start = open_space("retry a failed request", code)
    sited = narrow(start, code, mapped, "retry a failed request", "ontology")
    again = narrow(sited, code, mapped, "retry a failed request", "context")

    assert not track("x", [start, sited, again]).stuck


def test_a_trivial_contraction_is_not_progress(code, mapped):
    """Ruling out four of six hundred candidates is not the same as ruling out
    four of nine, so the threshold is a share rather than a count.
    """
    start = open_space("retry a failed request", code)

    def one_only(node_id: str):
        if node_id == "other/m0.py:5:unrelated_0":
            return (Verdict.SOUND_PRUNE, "one candidate, out of sixty-three")
        return None

    barely = narrow(
        start, code, Map(ontology="t", attachments=[]), "x", "one", excludes=one_only
    )

    assert barely.sites == start.sites - 1
    assert (start.sites - barely.sites) / start.population < MOVED
    assert not track("x", [start, barely]).contracting


def test_narrowing_is_measured_from_the_open_space(code, mapped):
    """Against step zero, not against the previous step.

    A trajectory that contracts a little at a time has narrowed as much as one
    that did it in a single move, and measuring against the last step would
    report the patient one as barely having moved.
    """
    start = open_space("retry a failed request", code)
    sited = narrow(start, code, mapped, "retry a failed request", "ontology")

    trajectory = track("retry a failed request", [start, sited])

    assert trajectory.narrowing == pytest.approx(1 - 3 / 63, abs=0.01)


def test_an_empty_space_has_not_been_narrowed(mapped):
    """A space of nothing is not a space that ruled everything out.

    `1 - sites/population` on an empty repository reads 1.00, giving the most
    confident value in the range to the least grounded claim — the sign trap
    that makes "found nothing" look like "found exactly one thing".
    """
    empty = Graph(root="/x", nodes={})
    start = open_space("retry a failed request", empty)

    assert track("x", [start]).narrowing == 0.0
    assert not track("x", [start]).converged


def test_a_trajectory_reads_back_as_a_story(code, mapped):
    """Every figure recomputable, and the sequence legible.

    The discipline `authority` follows in carrying `was` and `now`: a reader who
    doubts the verdict checks the working rather than taking its word.
    """
    start = open_space("retry a failed request", code)
    sited = narrow(start, code, mapped, "retry a failed request", "named by ontology")

    said = track("retry a failed request", [start, sited]).describe()

    assert "63 → 3" in said
    assert "retry a failed request" in said
    assert all(step.doing for step in [start, sited])


# ── A judgement you can argue with ──────────────────────────────────────────
#
# A judgement is addressable only if it has a stable identity across runs.
# `Witness.rule` is a display string — "retry.py:11 parse_retry" — and a display
# string changes when the line moves, so a reader who wants to say "not this
# exclusion again" has no name to say it about.


def test_a_judgement_carries_what_it_judged(code, mapped):
    start = open_space("retry a failed request", code)
    after = narrow(start, code, mapped, "retry a failed request", "ontology")

    excluded = next(w for w in after.witness if w.name == "unrelated_3")

    assert excluded.about == "other/m3.py:5:unrelated_3"
    assert excluded.path == "other/m3.py"
    assert excluded.reason


def test_a_judgement_is_addressable_after_its_line_moves(code, mapped):
    """The point of identity: the same judgement, asked about later.

    Matching on the display string would fail here — the definition is at a
    different line, so it prints differently — and a judgement nobody can name
    twice is one nobody can overrule.
    """
    start = open_space("retry a failed request", code)
    after = narrow(start, code, mapped, "retry a failed request", "ontology")

    found = track("retry a failed request", [start, after]).why_gone("unrelated_3")

    assert found and found[0].verdict == Verdict.SOUND_PRUNE


def test_identity_and_display_come_from_one_place(code, mapped):
    """A judgement whose label says one definition and whose path says another
    is worse than one carrying no identity at all.
    """
    start = open_space("retry a failed request", code)
    after = narrow(start, code, mapped, "retry a failed request", "ontology")

    for judgement in after.witness:
        assert judgement.path and judgement.name
        assert judgement.name in judgement.rule
        assert judgement.path in judgement.rule


def test_narrowing_survives_a_definition_moving(mapped):
    """The re-anchoring reaches the narrowing path, not only the map.

    Before this, a line inserted above a named definition changed its id, the
    binding resolved to nothing, and the step reported the space as un-narrowed
    — a stale ontology and an absent one producing the same answer, which is the
    failure the identity fields exist to end.
    """

    def repository(line: int) -> Graph:
        nodes = [node("parse_retry", "retry.py", line)]
        nodes += [node(f"unrelated_{i}", f"other/m{i}.py", 5) for i in range(20)]
        return Graph(root="/x", nodes={n.id: n for n in nodes})

    bound = Map(
        ontology="test",
        attachments=[
            Attachment(
                node="retry.py:10:parse_retry",
                term="activity:1",
                label="retry a failed request with a growing delay",
                kind="activity",
                strength=1.0,
                how="read",
                path="retry.py",
                name="parse_retry",
            )
        ],
    )

    unmoved = repository(10)
    after_unmoved = narrow(
        open_space("retry a failed request", unmoved),
        unmoved, bound, "retry a failed request", "ontology",
    )

    moved = repository(13)
    after_moved = narrow(
        open_space("retry a failed request", moved),
        moved, bound, "retry a failed request", "ontology",
    )

    assert after_unmoved.sites == 1
    assert after_moved.sites == after_unmoved.sites
    assert after_moved.admissible == ["retry.py:13:parse_retry"]


# ── What a trajectory says about its own reasoning ──────────────────────────


def test_reachability_is_structural_not_asserted(code, mapped):
    """The exclusion is arithmetic on edges — the seeds do not reach here — so
    re-running it against the current graph either agrees or does not.

    What is *not* structural is the ontology binding underneath it, where an
    agent read a definition and labelled it. That basis belongs to the
    attachment, not to this exclusion.
    """
    start = open_space("retry a failed request", code)
    after = narrow(start, code, mapped, "retry a failed request", "ontology")

    assert {w.basis for w in after.witness} == {Basis.STRUCTURAL}
    assert after.replayable == 1.0


def test_a_caller_may_state_the_basis_of_its_own_rule(code, mapped):
    start = open_space("retry a failed request", code)
    named = narrow(start, code, mapped, "retry a failed request", "ontology")

    def a_rule(node_id: str):
        if "backoff" in node_id:
            return (Verdict.DEMOTE, "further from the change", Basis.STRUCTURAL)
        return None

    after = narrow(
        named, code, mapped, "retry a failed request", "rule", excludes=a_rule
    )

    judged = next(w for w in after.witness if w.name == "backoff")
    assert judged.basis is Basis.STRUCTURAL


def test_a_caller_that_states_no_basis_gets_the_weakest(code, mapped):
    """A basis nobody claimed is not one to infer on their behalf."""
    start = open_space("retry a failed request", code)
    named = narrow(start, code, mapped, "retry a failed request", "ontology")

    after = narrow(
        named, code, mapped, "retry a failed request", "rule",
        excludes=lambda n: (Verdict.DEMOTE, "somebody read it") if "send" in n else None,
    )

    judged = next(w for w in after.witness if w.name == "send")
    assert judged.basis is Basis.ASSERTED
    assert not judged.replayable


def test_a_trajectory_states_what_share_of_it_replays(code, mapped):
    """The number a bundle has to state about itself.

    A trail that replays entirely and one resting mostly on what an agent read
    are worth very different amounts, and they are indistinguishable unless the
    record says which it is.
    """
    start = open_space("retry a failed request", code)
    named = narrow(start, code, mapped, "retry a failed request", "ontology")
    read = narrow(
        named, code, mapped, "retry a failed request", "rule",
        excludes=lambda n: (Verdict.DEMOTE, "an agent read this") if "send" in n else None,
    )

    trajectory = track("retry a failed request", [start, named, read])

    assert 0.0 < trajectory.replayable < 1.0
    assert [w.name for w in trajectory.asserted] == ["send"]
    assert "nothing can confirm them" in trajectory.describe()


def test_a_trajectory_that_replays_entirely_says_so(code, mapped):
    """Said whichever way it falls: silence would let a partly-read trail imply
    it was all checkable."""
    start = open_space("retry a failed request", code)
    named = narrow(start, code, mapped, "retry a failed request", "ontology")

    said = track("retry a failed request", [start, named]).describe()

    assert "all 60 judgement(s) can be re-checked" in said


def test_an_authority_may_not_close_the_space(code, mapped):
    """The ceiling on a pooled verdict, enforced here rather than left to each
    caller to remember.

    A skill that concludes wrongly should cost a ranking, not a candidate: an
    excluded definition is gone from the space with no way back, and an
    evaluated verdict is never certain enough to do that.
    """
    start = open_space("retry a failed request", code)
    named = narrow(start, code, mapped, "retry a failed request", "ontology")

    after = narrow(
        named, code, mapped, "retry a failed request", "a skill",
        excludes=lambda n: (
            (Verdict.SOUND_PRUNE, "the skill says otherwise", Basis.EVALUATED)
            if "backoff" in n
            else None
        ),
    )

    judged = next(w for w in after.witness if w.name == "backoff")
    assert judged.verdict is Verdict.DEMOTE, "demoted, not excluded"
    assert "demoted, not excluded" in judged.reason, "the ceiling is visible"
    assert after.sites == named.sites, "the candidate stays in the space"


def test_a_trajectory_names_what_was_judged_by_an_authority(code, mapped):
    """Named separately from what was merely read: an evaluated verdict has its
    evidence recorded and can be asked again, which is a different caveat from
    "nothing can check this".
    """
    start = open_space("retry a failed request", code)
    named = narrow(start, code, mapped, "retry a failed request", "ontology")
    pooled = narrow(
        named, code, mapped, "retry a failed request", "a skill",
        excludes=lambda n: (
            (Verdict.DEMOTE, "the skill says so", Basis.EVALUATED)
            if "send" in n
            else None
        ),
    )

    said = track("retry a failed request", [start, named, pooled]).describe()

    assert "may evaluate differently on another run" in said


# ── Guided mode: steering that may demote and never remove ──────────────────


def test_a_guided_narrowing_records_interventions_without_removing(code, mapped):
    """Evidence first, exactly as blind; then the region gets a say — and only
    a say. The survivor set is identical to blind's, so nothing the evidence
    kept is lost; what changes is that the departure is recorded at the step
    it happened, rather than discovered at a post-mortem.
    """
    start = open_space("retry a failed request", code)
    blind = narrow(start, code, mapped, "retry a failed request", "ontology")

    # A region admitting only the named definition: the two one-hop
    # neighbours survive on evidence and are demoted by guidance.
    guided = narrow(
        start, code, mapped, "retry a failed request", "ontology",
        region={"retry.py:10:parse_retry"},
    )

    assert guided.admissible == blind.admissible, "guidance never removes"
    assert len(guided.interventions) == 2
    assert {i.name for i in guided.interventions} == {"backoff", "send"}
    assert all("demot" in i.action for i in guided.interventions)
    assert not blind.interventions, "blind mode has nothing to intervene with"


def test_friction_reads_concurrence_and_drag(code, mapped):
    """Zero friction is the guided-mode reading of two independent sources
    concurring — the same fact a blind in-region landing is, observed through
    a different instrument. Friction above zero records the specifications
    dragging the decision against the evidence.
    """
    start = open_space("retry a failed request", code)

    concurring = narrow(
        start, code, mapped, "retry a failed request", "ontology",
        region={"retry.py:10:parse_retry", "retry.py:30:backoff", "http.py:10:send"},
    )
    agreed = track("retry a failed request", [start, concurring])
    agreed.mode = "guided"
    assert agreed.friction == 0.0
    assert "guided — 0 intervention(s)" in agreed.describe()

    dragged = narrow(
        start, code, mapped, "retry a failed request", "ontology",
        region={"retry.py:10:parse_retry"},
    )
    dragging = track("retry a failed request", [start, dragged])
    dragging.mode = "guided"
    assert dragging.friction > 0.0
