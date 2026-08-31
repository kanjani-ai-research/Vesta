"""The dominance bound, held to its whole contract.

Organized by failure class, because a bound has exactly two ways to be
wrong and both must be tested on purpose:

  FALSE NEGATIVES — committing where it should abstain: near-ties in every
  pair, exact ties, the boundary itself.
  FALSE POSITIVES — abstaining where it should commit: dominant leads over
  every alternative, at and past the boundary.
  LOGICAL PROPERTIES — invariants that must hold for all inputs: the region
  never picks a winner, shift-invariance, committed-label symmetry,
  monotonicity, determinism, degenerate dominance values.

Boundary semantics, fixed here: committing requires a lead STRICTLY above
`dominance`; at the boundary it abstains, because the measured wrong
commitments sat at leads of exactly the margin. Ties are non-dominant by
construction, so no exact tie involving a committed candidate ever commits.
"""

import itertools

from vesta.bound import DOMINANCE, conclude

C = ("valid", "invalid")
U = "indeterminate"
LABELS = ("valid", "invalid", "indeterminate")


def verdict(scores, region=None, dominance=DOMINANCE):
    v, _ = conclude(scores, C, U, region=region, dominance=dominance)
    return v


# ── FALSE NEGATIVES: commits that must not happen ────────────────────────

class TestNoCommitWithoutDominance:
    def test_near_tie_between_committed(self):
        assert verdict({"valid": 0.65, "invalid": 0.60, U: 0.30}) == U

    def test_near_tie_against_undecided(self):
        assert verdict({"valid": 0.66, "invalid": 0.20, U: 0.60}) == U

    def test_the_measured_error_shapes(self):
        # the eleven-of-thirteen class: 0.55/0.65 corners the old rule missed
        assert verdict({"valid": 0.55, "invalid": 0.65, U: 0.25}) == U
        assert verdict({"valid": 0.65, "invalid": 0.55, U: 0.45}) == U

    def test_exact_tie_never_commits(self):
        # whichever way argmax breaks a tie, a tied committed candidate has
        # zero lead and must abstain
        for a, b in itertools.permutations(LABELS, 2):
            scores = {k: 0.2 for k in LABELS}
            scores[a] = scores[b] = 0.7
            if a in C or b in C:
                assert verdict(scores) == U, (a, b)

    def test_just_under_the_boundary_abstains(self):
        assert verdict({"valid": 0.70, "invalid": 0.70 - DOMINANCE + 0.01, U: 0.1}) == U


# ── FALSE POSITIVES: abstentions that must not happen ────────────────────

class TestDominantCommitsStand:
    def test_clear_dominance_both_directions(self):
        assert verdict({"valid": 0.9, "invalid": 0.2, U: 0.3}) == "valid"
        assert verdict({"valid": 0.1, "invalid": 0.8, U: 0.3}) == "invalid"

    def test_at_the_boundary_abstains_just_above_commits(self):
        assert verdict({"valid": 0.70, "invalid": 0.70 - DOMINANCE, U: 0.1}) == U
        assert verdict({"valid": 0.72, "invalid": 0.72 - DOMINANCE - 0.02, U: 0.1}) == "valid"

    def test_dominance_is_over_the_runner_up_not_the_sum(self):
        # both alternatives moderately high but each individually beaten
        assert verdict({"valid": 0.85, "invalid": 0.70, U: 0.70}) == "valid"

    def test_undecided_winner_needs_no_margin(self):
        # abstention is always safe: the undecided conclusion passes through
        # at any lead, including a dead heat with a committed candidate
        assert verdict({"valid": 0.549, "invalid": 0.50, U: 0.55}) == U


# ── LOGICAL PROPERTIES ───────────────────────────────────────────────────

class TestRegionNeverDecides:
    def test_all_region_subsets_leave_the_winner_alone(self):
        scores = {"valid": 0.2, "invalid": 0.8, U: 0.3}
        for r in range(len(LABELS) + 1):
            for region in itertools.combinations(LABELS, r):
                v, _ = conclude(scores, C, U, region=set(region))
                assert v == "invalid", region

    def test_defiance_flag_is_exactly_winner_not_in_region(self):
        scores = {"valid": 0.9, "invalid": 0.1, U: 0.2}
        _, oor = conclude(scores, C, U, region={"invalid", U})
        assert oor
        _, oor = conclude(scores, C, U, region={"valid"})
        assert not oor
        _, oor = conclude(scores, C, U, region=None)
        assert not oor

    def test_empty_region_is_defied_never_obeyed(self):
        v, oor = conclude({"valid": 0.9, "invalid": 0.1, U: 0.1}, C, U, region=set())
        assert v == "valid" and oor


class TestInvariants:
    GRID = [round(x * 0.25, 2) for x in range(5)]

    def all_score_maps(self):
        for a, b, c in itertools.product(self.GRID, repeat=3):
            yield {"valid": a, "invalid": b, U: c}

    def test_determinism(self):
        for s in self.all_score_maps():
            assert conclude(s, C, U) == conclude(s, C, U)

    def test_shift_invariance(self):
        # the verdict depends on leads, not levels
        for s in self.all_score_maps():
            shifted = {k: v + 3.7 for k, v in s.items()}
            assert verdict(s) == verdict(shifted), s

    def test_committed_label_symmetry(self):
        # swapping the two committed scores swaps (or preserves) the verdict
        swap = {"valid": "invalid", "invalid": "valid", U: U}
        for s in self.all_score_maps():
            mirrored = {swap[k]: v for k, v in s.items()}
            assert verdict(mirrored) == swap[verdict(s)], s

    def test_raising_the_winner_never_unconcludes(self):
        for s in self.all_score_maps():
            v = verdict(s)
            if v in C:
                boosted = dict(s)
                boosted[v] += 0.5
                assert verdict(boosted) == v, s

    def test_negative_dominance_degenerates_to_argmax(self):
        # with the boundary belonging to caution, argmax behaviour is the
        # limit below zero (at exactly zero, ties still abstain)
        for s in self.all_score_maps():
            v = verdict(s, dominance=-0.01)
            assert v == max(s, key=lambda k: s[k])

    def test_unreachable_dominance_abstains_every_commit(self):
        for s in self.all_score_maps():
            assert verdict(s, dominance=10.0) == U, s
