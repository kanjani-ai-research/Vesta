# Vesta

What a change touches.

A domain model of a codebase, and bounded propagation over it: given a change,
name what breaks. The claim is a correctness claim — not "what might be worth
looking at" — because that is the only version anyone can score.

## The measurement came first

The harness was built before the graph it grades, so the graph is built against
a number rather than scored after the fact.

Ground truth is the repository's own history. A commit that changes source and
tests together is an experiment somebody already ran: the source change is the
input, the tests touched in the same commit are the label. That label is
imperfect — authors miss things — but it is independent of whatever this system
predicts, which is the property that matters.

## The bar

Measured over 88 usable commits across nine repositories:

| Approach | precision | recall | f1 | complete |
|---|---|---|---|---|
| Run everything | 0.15 | 1.00 | 0.25 | 100% |
| Same-file convention | 0.54 | 0.74 | 0.59 | 61% |

**Complete** is the share of commits where nothing that moved went unpredicted.
It matters more than recall: an approach averaging good recall while missing
something on a third of changes is not one anybody should rely on to say "safe
to change".

The naming convention is a strong baseline and the honest one to beat. A graph
that cannot beat a convention has not earned its complexity.

## Status

The harness exists and is tested. The graph does not exist yet.
