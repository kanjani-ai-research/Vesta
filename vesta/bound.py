"""Committing is earned by dominance; the region informs, it never decides.

Two repairs, each from a measured failure:

**The bound is relative, not a corner.** An absolute rule over two scores
(both committed >= a threshold) cannot see nearness: 0.55 against 0.65 walks
under it and commits, and eleven of thirteen measured errors were exactly
such near-ties, sitting at a median lead of 0.10 while correct conclusions
sat at 0.70. So a committed conclusion must DOMINATE: its score beats every
alternative by a margin, or the conclusion is undecided. Nearness itself is
the signal that the record does not decide.

**Guidance may not pick a winner.** Demoting an out-of-region candidate is
allowed to re-rank, but where the demotion would change which candidate
wins, the region is overriding the evidence — and both measured occurrences
of that flip were wrong. The evidence's winner stands; the disagreement is
returned as a fact for the record, which is the out-of-region-survivor
signal the witness already knows how to carry.
"""

from typing import Dict, Optional, Sequence, Set, Tuple

DOMINANCE = 0.10


def conclude(
    scores: Dict[str, float],
    committed: Sequence[str],
    undecided: str,
    region: Optional[Set[str]] = None,
    dominance: float = DOMINANCE,
) -> Tuple[str, bool]:
    """The verdict the scores earn, and whether it defied the region.

    Deterministic. The winner is the evidence's own argmax — the region
    never changes it. A committed winner without a dominant lead concludes
    `undecided`; an undecided winner passes through untouched, because the
    conclusion that the record does not decide needs no margin to be safe.
    """
    winner = max(scores, key=lambda k: scores[k])
    out_of_region = region is not None and winner not in region
    if winner in committed:
        lead = scores[winner] - max(v for k, v in scores.items() if k != winner)
        if lead < dominance:
            return undecided, out_of_region
    return winner, out_of_region
