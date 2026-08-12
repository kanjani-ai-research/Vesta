"""Which rules bear on what is being worked on, and which of them are in doubt.

A rule's authority is only ever in question when something depends on it. A list
of twenty-four rules to review is a list nobody reviews; the same rule raised
while somebody is editing the file it governs is a question they already care
about, asked at the only moment it costs nothing to answer.

**This finds the one rule worth asking about, or none.** Not a review screen, not
a browsable list, and nothing stateful. The scope is what a change touches, the
question is whether a rule that covers it still binds, and the answer goes where
every other verdict goes.

**A violation is a fact; a mistake is not.** Vesta can check that code breaks a
rule — that is `enforce`, and it either finds a site or it does not. Whether a
rule was *wrong to begin with* is a judgement about intent, and inferring it
from consequences is how a tool starts confidently telling somebody their own
decisions were errors. So this never says a rule is mistaken. It says the code
and the rule disagree, and asks which the user meant.

**A rule nothing can check is an abstention, not a silence.** The two look the
same from outside and are not: a rule that was checked and holds is an answer,
while a rule nothing could check is Vesta declining to answer. Collapsing them
means a rule governing the work in hand, whose violation would matter, passes
as though it had been verified — and the user has no way to know the difference.

So it abstains, with the meaning abstention already carries here: it yields
rather than interrupting, because a gap is not evidence and stopping somebody
mid-edit over one would be a wrong guess with a real cost. And it queues, so
what Vesta could not answer is settleable deliberately rather than silently
absent.

**Nothing here asks.** It decides what is worth raising and why; the asking
belongs to whatever surface is in front of the user, exactly as in `confirm`.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import List, Optional, Sequence

from pydantic import BaseModel, Field

from .confirm import ABSTAINED, IS_A_RULE, handle, recall
from .enforce import Finding
from .rules import Rule

logger = logging.getLogger("vesta.bearing")

# How many to raise at once. One: this interrupts work somebody is in the middle
# of, and a second question is a conversation they did not agree to have.
AT_ONCE = 1


class Bearing(BaseModel):
    """A rule that bears on the work in hand, and why it is worth raising."""

    rule: str
    said: str = ""
    # Where the code and the rule disagree. Empty means the rule covers this
    # work and holds — which is not worth interrupting anybody about.
    sites: List[str] = Field(default_factory=list)
    # Why nothing could be checked, where nothing could. A rule that governs
    # this work and cannot be checked is a gap worth knowing about, but it is
    # not evidence of anything and is never raised as though it were.
    undecided: str = ""

    @property
    def worth_raising(self) -> bool:
        """Only a disagreement is worth stopping somebody for.

        Not a gap. A gap is real and is reported, but interrupting an edit to
        say "a rule covers this and I cannot tell you whether you broke it"
        asks a question nobody can answer in the moment.
        """
        return bool(self.sites)

    @property
    def abstained(self) -> bool:
        """Whether Vesta declined to answer about a rule governing this work.

        Distinct from a rule that holds. This one was never checked, so the
        code may honour it or may not, and saying nothing at all would let it
        pass as verified.
        """
        return bool(self.undecided) and not self.sites

    @property
    def name(self) -> str:
        return handle(self.rule)

    def describe(self) -> str:
        # "holds" and "could not tell" must never read alike: one is an answer
        # and the other is Vesta declining to give one.
        if self.abstained:
            return f"could not tell — {self.undecided}: {self.rule[:60]}"
        if not self.sites:
            return f"holds: {self.rule[:80]}"
        where = ", ".join(self.sites[:3])
        return f"disagrees at {where}: {self.rule[:80]}"

    def ask(self) -> str:
        """What to put to the user. Their words, their decision, one question.

        Deliberately not "your rule is wrong": the code disagreeing with a rule
        means one of them is out of date, and which one is not Vesta's to say.
        """
        where = ", ".join(self.sites[:3])
        more = f" (+{len(self.sites) - 3})" if len(self.sites) > 3 else ""
        return (
            f'A rule you set covers this work:\n"{self.said or self.rule}"\n\n'
            f"What is at {where}{more} does not match it.\n"
            "Does the rule still stand?"
        )


def _covers(rule: Rule, paths: Sequence[str]) -> bool:
    """Whether a rule is about any of these files.

    Matched on what the rule names — the identifiers and file names its author
    used — rather than on where a check found sites. A rule nobody has written
    a check for still governs the files it names, and pretending otherwise
    would raise only the rules that were easy to check.
    """
    wanted = {Path(p).name.lower() for p in paths}
    wanted |= {Path(p).stem.lower() for p in paths}
    if not wanted:
        return False

    for named in rule.names:
        low = named.lower()
        if low in wanted or Path(low).stem in wanted:
            return True
        # `.env` names a file the paths may spell out in full.
        if low.startswith(".") and any(low in p.lower() for p in paths):
            return True
    return False


def on(
    findings: Sequence[Finding],
    rules: Sequence[Rule],
    paths: Sequence[str],
    repo: Optional[Path | str] = None,
) -> List[Bearing]:
    """Rules that bear on these files, most in doubt first.

    Takes findings already computed rather than checking anything itself: the
    checking is `enforce`'s, and doing it twice would mean two answers that can
    disagree.
    """
    if not paths:
        return []

    by_text = {f.rule: f for f in findings}
    settled = recall(repo).by_text() if repo is not None else {}

    found: List[Bearing] = []
    for rule in rules:
        if not _covers(rule, paths):
            continue

        # Already put to them and not answered. Asking again while they are in
        # the middle of something is the nagging this is meant to avoid.
        from .confirm import _key

        verdict = settled.get(_key(rule.text))
        if verdict is not None and verdict.verdict == ABSTAINED:
            continue

        finding = by_text.get(rule.stated or rule.text) or by_text.get(rule.text)
        found.append(
            Bearing(
                rule=rule.text,
                said=rule.stated or rule.text,
                sites=[s.describe() for s in finding.sites] if finding else [],
                undecided=finding.undecided if finding else "",
            )
        )

    # A disagreement first, then the rest. Within a disagreement, the one with
    # fewest sites: a rule broken in one place is a question about that place,
    # while one broken in twenty is a rule nobody has been following, and that
    # is a conversation rather than a prompt.
    found.sort(key=lambda b: (not b.worth_raising, len(b.sites)))
    return found


def worth_raising(
    findings: Sequence[Finding],
    rules: Sequence[Rule],
    paths: Sequence[str],
    repo: Optional[Path | str] = None,
    limit: int = AT_ONCE,
) -> List[Bearing]:
    """The rules to actually put to somebody, which is usually none."""
    return [b for b in on(findings, rules, paths, repo) if b.worth_raising][:limit]


def unanswered(
    findings: Sequence[Finding],
    rules: Sequence[Rule],
    paths: Sequence[str],
    repo: Optional[Path | str] = None,
) -> List[Bearing]:
    """Rules governing this work that Vesta could not check.

    Reported rather than raised. The user is not asked to do anything about
    these in the moment — there is nothing they could usefully do — but they
    are told, because a rule that governs what they are editing and was never
    checked is not the same as one that passed.
    """
    return [b for b in on(findings, rules, paths, repo) if b.abstained]


def queue(
    findings: Sequence[Finding],
    rules: Sequence[Rule],
    paths: Sequence[str],
    repo: Path | str,
) -> int:
    """Record the unanswerable ones so they can be settled deliberately.

    An abstention Vesta makes is kept the same way an abstention the user makes
    is kept: out of enforcement, and on the list of what is waiting. The user
    settles it by giving the rule a check, restating it, or letting it lapse —
    none of which belongs in the middle of an edit.
    """
    from .confirm import ABSTAINED, record

    kept = 0
    for one in unanswered(findings, rules, paths, repo):
        record(repo, one.rule, ABSTAINED, "")
        kept += 1
    return kept
