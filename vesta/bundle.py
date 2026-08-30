"""One invocation, one output, and whether the reasoning that produced it was sane.

A witness is not the chain of events. It is a verdict on the chain, taken while
the chain is still in hand and kept afterwards in place of it.

That distinction is the whole design. An earlier version stored every judgement
so that somebody could work out later whether the reasoning held — 712 records,
303kb, of which 681 said the same sentence. Nobody asks why one particular
definition was not the answer; they ask what came out, what backed it, and
whether the path there made sense. So the checks run now, at the moment the
chain is complete, and what survives is the finding plus the few facts it rests
on.

**Sanity is a property of shape, not of any single judgement.** Each check below
is arithmetic over the trajectory: did the space actually contract, was every
narrowing accounted for, did the output come from what survived, did anything
excluded come back, did a pooled verdict overstep. None of them is an opinion,
and every one re-runs to the same answer — so the witness's own verdict is
verifiable even where the reasoning underneath it is not.

**And underneath it, partly, is not. This is a known limitation of the current
implementation, not an oversight.** Truth here is pooled: an authority is
consulted, shown evidence gathered deterministically, and its verdict recorded.
A discrete representation — predicates that evaluate to true or false rather
than a judgement that evaluates to a view — would make those re-verifiable.

It was considered and declined. The requirements for discrete representation are
substantially more complex than this tool can carry: almost nothing a standard
actually asks for reduces to a predicate over a reference graph, so forcing one
would produce a small set of checkable-but-trivial conditions and silently drop
everything that mattered. That is rigour in appearance over a narrower claim,
and the risk outweighed the benefit here.

The consequence is stated rather than hidden, and it is stated on every witness
that carries a pooled judgement: **a pooled judgement re-evaluates, it does not
re-verify.** Asked again it may answer differently with no code having changed.
Anyone who needs the stronger property needs the discrete representation, and
that is a different tool than this one.

What that leaves is better than it sounds, because the two halves come apart
cleanly. A reader gets a *replayable verdict about the process* wrapped around
*partly unreplayable reasoning*, with the boundary between them stated. The
strongest available check on the unreplayable part is itself structural: an
evaluated verdict may demote but never exclude, and a witness can say
verifiably that none of them closed the space.

**The chain is local and optional.** Somebody debugging their own session can
keep it; it is not part of what the witness carries, and nothing here depends on
having it later.
"""

from __future__ import annotations

import hashlib
import json
import logging
import subprocess
import time
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from pydantic import BaseModel, Field

from .graph import Graph
from .space import Basis, Verdict
from .warrant import Convergence, Intervention

logger = logging.getLogger("vesta.bundle")

# How many witnesses a project keeps. Fifty is a working session's worth: enough
# that the run somebody wants is still there the next morning, few enough that a
# directory of them stays a directory.
KEEP = 50

SANE = "sane"
UNSOUND = "unsound"
UNKNOWN = "unknown"  # nothing to judge — no chain was recorded


class Finding(BaseModel):
    """One check on the chain, and what it found.

    Every check is arithmetic over the trajectory's shape, so every one of them
    re-runs to the same answer. A finding that says `held` is a fact a reader can
    recompute; one that does not is a defect in the reasoning, named.
    """

    check: str
    held: bool = True
    detail: str = ""

    def describe(self) -> str:
        return f"{'✓' if self.held else '✗'} {self.check}" + (
            f" — {self.detail}" if self.detail else ""
        )


class Witness(BaseModel):
    """One invocation, its output, and whether the way there was sound.

    Small by construction rather than by compression: it holds a verdict and the
    handful of facts behind it, not the reasoning it was drawn from.
    """

    # What was asked, and what came out. The two things a reader wants first.
    intent: str = ""
    output: str = ""

    project: str = ""
    session: str = ""
    at: float = 0.0
    # The commit this was taken against. A timestamp cannot tell a reader which
    # version of a file a judgement was made about; every id in this repository
    # is position-derived, so the fixed point has to be recorded.
    commit: str = ""

    # How the space contracted, as the numbers alone. `746 → 34 → 18 → 1` is the
    # progress a reader is checking, and it is four integers rather than seven
    # hundred records.
    narrowed: List[int] = Field(default_factory=list)
    outputs: List[int] = Field(default_factory=list)

    # What the chain came down to, and what backed it. Only the survivors: the
    # candidates that did not survive are a count, not a list.
    stood_on: List[str] = Field(default_factory=list)
    ruled_out: int = 0

    # Where the reasoning came from. Counted rather than enumerated, because the
    # question is what share rested on judgement, not which judgements they were.
    computed: int = 0
    judged: int = 0
    read: int = 0
    authorities: List[str] = Field(default_factory=list)

    # Where the decision was expected to land, worked out before it ran, and
    # from what.
    #
    # The prediction comes from the authority crossed with the intent; the
    # narrowing runs on the repository's own graph and vocabulary. Two
    # derivations from two sources, so their agreeing means something — a
    # prediction drawn from the same ontology the narrowing uses would be
    # checking a computation against itself.
    expected: List[str] = Field(default_factory=list)

    # The part of the standard that decided this, and what it said at the time.
    #
    # Kept because a sound process that followed a wrong standard and an unsound
    # process are indistinguishable from the outcome alone, and they are
    # different failures with different owners. Whoever wrote the standard is
    # answerable for what it says; whoever ran the process is answerable for
    # following it. A record that cannot tell them apart leaves both
    # unattributable.
    #
    # The digest is what stops a standard being edited afterwards and an old
    # record being read as though it had always said the new thing.
    stood_by: List[str] = Field(default_factory=list)
    standard: str = ""
    standard_digest: str = ""

    # Which vocabulary decided where this belonged.
    #
    # The predicted region is read through the repository's own ontology, so the
    # ontology is as load-bearing as the standard — a record judged in-bounds
    # under one version and out under another is not contradicting itself, it is
    # being read against a vocabulary that moved. Without this a reader cannot
    # tell those apart, and a witness from before an edit becomes unre-checkable
    # without anyone noticing it had become so.
    vocabulary: str = ""

    # How the narrowing related to the predicted region. A guided landing is
    # partly by construction and must never be read with blind-mode weight;
    # the interventions and friction carry guided mode's signal instead, and
    # the mode is what keeps the two readings apart.
    mode: str = "blind"
    interventions: List[Intervention] = Field(default_factory=list)
    friction: float = 0.0

    # Which revision of the record format this follows, and the level it was
    # produced at — so an absent check is never read as a passed one.
    format_version: int = 1
    level: int = 1

    # The verdict and its working.
    verdict: str = UNKNOWN
    findings: List[Finding] = Field(default_factory=list)

    # Where the full chain was kept, if the user asked for it. A path, not the
    # chain: it is theirs to keep and this does not depend on it.
    chain_at: str = ""

    @property
    def sound(self) -> bool:
        return self.verdict == SANE

    @property
    def pooled(self) -> float:
        """What share of the reasoning was judged rather than computed."""
        total = self.computed + self.judged + self.read
        return (self.judged / total) if total else 0.0

    def describe(self) -> str:
        when = time.strftime("%Y-%m-%d %H:%M", time.localtime(self.at)) if self.at else ""
        lines = [
            self.intent or "(nothing recorded)",
            f"  taken {when} against {self.commit[:12] or '(no commit)'}",
        ]
        if self.narrowed:
            lines.append("  narrowed  " + " → ".join(str(n) for n in self.narrowed))
        if self.mode == "guided":
            lines.append(
                f"  guided — {len(self.interventions)} intervention(s), "
                f"friction {self.friction:.0%}"
            )
            for meddled in self.interventions[:4]:
                lines.append(f"    {meddled.describe()}")
        if self.output:
            lines.append(f"  output    {self.output}")

        failed = [f for f in self.findings if not f.held]
        if self.verdict == SANE:
            lines.append(f"  sound — {len(self.findings)} check(s) held")
        elif self.verdict == UNSOUND:
            lines.append(f"  UNSOUND — {len(failed)} of {len(self.findings)} check(s) failed")
            for finding in failed:
                lines.append(f"    {finding.describe()}")
        else:
            lines.append("  nothing to judge — no reasoning was recorded")

        if self.standard:
            # Named on every record judged against one, so that a decision which
            # later turns out wrong can be traced to the rule it followed rather
            # than only to the run that followed it.
            lines.append(
                f"  judged against {self.standard}"
                + (f" ({self.standard_digest[:8]})" if self.standard_digest else "")
            )
            for said in self.stood_by[:4]:
                lines.append(f"    which says: {said}")

        if self.vocabulary:
            # Which vocabulary decided where this belonged, so a reader checking
            # an old record against a since-edited one knows the standard moved
            # rather than the reasoning.
            lines.append(f"  read through vocabulary {self.vocabulary[:8]}")

        if self.judged:
            # Said whenever any of it was pooled, because this is the limit a
            # reader has to know about: asked again, that part may answer
            # differently with no code having changed.
            lines.append(
                f"  {self.judged} of {self.computed + self.judged + self.read} "
                f"judgement(s) came from an authority ({', '.join(self.authorities)}) "
                "and re-evaluate rather than re-verify"
            )
        return "\n".join(lines)


def _commit(repo: Path | str) -> str:
    """The commit this was taken against, or nothing.

    Nothing is a real answer: not every directory is a repository, and inventing
    a fixed point where there is none would make a witness look checkable
    against a version that was never recorded.
    """
    try:
        done = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(repo),
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return done.stdout.strip() if done.returncode == 0 else ""


# ── The checks ───────────────────────────────────────────────────────────
#
# Each is a fact about the shape of the chain. None asks whether the conclusion
# was correct — that is not knowable from a trajectory, and a check that
# pretended otherwise would be exactly the confident inference this refuses.


def _contracted(trail: Convergence) -> Finding:
    """Whether the space actually closed, rather than being restated."""
    steps = trail.steps
    if len(steps) < 2:
        return Finding(
            check="the space contracted",
            held=False,
            detail="only one step was taken, so nothing was decided",
        )
    if steps[-1].sites >= steps[0].sites:
        return Finding(
            check="the space contracted",
            held=False,
            detail=f"{steps[0].sites} sites at the start, {steps[-1].sites} at the end",
        )
    return Finding(check="the space contracted", detail=f"{steps[0].sites} → {steps[-1].sites}")


def _accounted(trail: Convergence) -> Finding:
    """Whether every candidate that fell away was witnessed falling.

    A drop with no reason behind it is the failure this whole record exists to
    prevent: a set that got smaller for reasons nobody can name is not a
    decision, it is an accident that happened to narrow.
    """
    for before, after in zip(trail.steps, trail.steps[1:]):
        dropped = before.sites - after.sites
        if dropped <= 0:
            continue
        excluded = sum(
            1 for w in after.witness if w.verdict == Verdict.SOUND_PRUNE
        )
        if excluded < dropped:
            return Finding(
                check="every narrowing was accounted for",
                held=False,
                detail=(
                    f"{dropped} candidate(s) fell away and {excluded} were "
                    "witnessed — the rest vanished unexplained"
                ),
            )
    return Finding(check="every narrowing was accounted for")


def _no_reversal(trail: Convergence) -> Finding:
    """Whether anything soundly excluded came back.

    A sound prune is certain and this pass does not reopen it. Something
    returning means either the exclusion was wrong or the space was rebuilt
    from somewhere else, and a reader needs to know which they are looking at.
    """
    gone: set = set()
    for step in trail.steps:
        for judged in step.witness:
            if judged.verdict == Verdict.SOUND_PRUNE and judged.about:
                gone.add(judged.about)
        back = gone & set(step.admissible)
        if back:
            return Finding(
                check="nothing excluded came back",
                held=False,
                detail=f"{len(back)} candidate(s) returned after a sound exclusion",
            )
    return Finding(check="nothing excluded came back")


def _within_authority(trail: Convergence) -> Finding:
    """Whether a pooled verdict stayed inside what it is allowed to do.

    The strongest available check on the part that cannot be re-verified. An
    evaluated judgement may demote but never exclude, because it is never
    certain enough to close a space — and that a run honoured it is a structural
    fact, checkable even though the verdicts themselves are not.
    """
    overstepped = [
        w
        for step in trail.steps
        for w in step.witness
        if w.basis == Basis.EVALUATED and w.verdict == Verdict.SOUND_PRUNE
    ]
    if overstepped:
        return Finding(
            check="no pooled verdict closed the space",
            held=False,
            detail=f"{len(overstepped)} evaluated judgement(s) excluded a candidate",
        )
    return Finding(check="no pooled verdict closed the space")


def _output_stood_on_something(trail: Convergence, output: str) -> Finding:
    """Whether anything survived for the output to rest on.

    A conclusion drawn from an empty space came from somewhere the chain never
    reached, which is the shape of an answer that was decided elsewhere and
    narrated afterwards.
    """
    last = trail.steps[-1] if trail.steps else None
    if last is None or (last.sites == 0 and output):
        return Finding(
            check="the output rests on what survived",
            held=False,
            detail="nothing was left admissible, so the conclusion came from outside the chain",
        )
    return Finding(check="the output rests on what survived")


def _stayed_in_bounds(trail: Convergence, expected: Sequence[str]) -> Finding:
    """Whether the narrowing landed where the standard said it should.

    The one check that speaks to correctness rather than only to shape, and it
    can do so because the region was worked out **before** the narrowing ran,
    from a different source: the standard's words crossed with what was asked,
    against the repository's own graph and vocabulary. Two derivations agreeing
    is evidence; a chain checked against its own inputs is not.

    What it establishes is conformance to a stated standard, not correctness in
    the world. A standard that is wrong about this repository predicts the wrong
    place confidently, and a convergence landing there passes — which is why the
    part of the standard relied on travels with the record, so that failure has
    somewhere to attach.

    An empty prediction is not a failure. Where the standard says nothing about
    this work there is no region to be outside of, and reporting every landing
    as out of bounds would make an absent authority look like a violated one.
    """
    if not expected:
        return Finding(
            check="the narrowing stayed where the standard says it belongs",
            detail="no standard predicted a region for this work",
        )

    last = trail.steps[-1] if trail.steps else None
    if last is None or not last.admissible:
        return Finding(
            check="the narrowing stayed where the standard says it belongs",
            detail="nothing survived to check",
        )

    within = set(expected)
    strayed = [n for n in last.admissible if n not in within]
    if strayed:
        if trail.mode == "guided":
            # In guided mode a survivor outside the region is the strongest
            # flag the mode can raise: guidance demoted it and the evidence
            # kept it anyway. It exists only because guidance may not remove.
            return Finding(
                check="the narrowing stayed where the standard says it belongs",
                held=False,
                detail=(
                    f"{len(strayed)} of {len(last.admissible)} survivor(s) are "
                    "outside the region notwithstanding guidance — the evidence "
                    "overcame the specifications' pull"
                ),
            )
        return Finding(
            check="the narrowing stayed where the standard says it belongs",
            held=False,
            detail=(
                f"{len(strayed)} of {len(last.admissible)} surviving candidate(s) "
                "are outside the region the standard predicts"
            ),
        )
    if trail.mode == "guided":
        # Held, but partly by construction: the narrowing was steered. The
        # friction figure, not the landing, carries the guided-mode signal.
        return Finding(
            check="the narrowing stayed where the standard says it belongs",
            detail=(
                f"all {len(last.admissible)} survivor(s) are inside it "
                "(guided — read the friction, not the landing)"
            ),
        )
    return Finding(
        check="the narrowing stayed where the standard says it belongs",
        detail=f"all {len(last.admissible)} survivor(s) are inside it",
    )


def _guidance_observed(trail: Convergence) -> Finding:
    """Whether guidance stayed within its bound — and within its mode.

    In guided mode an intervention may demote and may not remove; that a run
    honoured it is checkable from the record, and it is the strongest available
    check on the part of the steering that rests on the specifications rather
    than on the subject. And a blind record carrying interventions is not a
    weaker record but a malformed one: there was nothing to intervene with.
    """
    meddled = trail.interventions
    if trail.mode != "guided":
        if meddled:
            return Finding(
                check="guidance stayed within its bound",
                held=False,
                detail=(
                    f"{len(meddled)} intervention(s) on a blind narrowing — the "
                    "mode says guidance never saw the region, and the record "
                    "contradicts itself"
                ),
            )
        return Finding(
            check="guidance stayed within its bound",
            detail="the mode was blind — guidance had nothing to do",
        )

    removed = [i for i in meddled if "demot" not in i.action]
    if removed:
        return Finding(
            check="guidance stayed within its bound",
            held=False,
            detail=f"{len(removed)} intervention(s) removed a candidate",
        )
    return Finding(
        check="guidance stayed within its bound",
        detail=f"{len(meddled)} intervention(s), every one a demotion",
    )


def judge(
    trail: Convergence, output: str = "", expected: Sequence[str] = ()
) -> List[Finding]:
    """Every check, run against a finished chain."""
    if not trail.steps:
        return []
    return [
        _contracted(trail),
        _accounted(trail),
        _no_reversal(trail),
        _within_authority(trail),
        _output_stood_on_something(trail, output),
        _stayed_in_bounds(trail, expected),
        _guidance_observed(trail),
    ]


def witness(
    intent: str,
    trail: Convergence,
    repo: Path | str,
    output: str = "",
    session: str = "",
    graph: Optional[Graph] = None,
    chain_at: str = "",
    expected: Optional["object"] = None,
    standard: str = "",
    standard_digest: str = "",
    vocabulary: str = "",
) -> Witness:
    """Judge a finished chain and keep the verdict rather than the chain.

    `expected` is where a standard said the change belongs, worked out before
    the chain ran. `standard` names it and `standard_digest` fixes what it said,
    so that a record judged against a standard which later turns out wrong can
    say which standard, and in which version — a sound process following a bad
    rule and an unsound process are the same outcome and different failures.
    """
    root = Path(repo).expanduser().resolve()
    where = list(getattr(expected, "where", ()) or ())
    findings = judge(trail, output, where)

    held = Witness(
        intent=intent,
        output=output,
        project=str(root),
        session=session,
        at=time.time(),
        commit=_commit(root),
        narrowed=[s.sites for s in trail.steps],
        outputs=[s.outputs for s in trail.steps],
        mode=trail.mode,
        interventions=list(trail.interventions),
        friction=trail.friction,
        findings=findings,
        chain_at=chain_at,
        stood_by=list(getattr(expected, "because", ()) or ()),
        standard=standard,
        standard_digest=standard_digest,
        vocabulary=vocabulary,
        verdict=(
            UNKNOWN
            if not findings
            else (SANE if all(f.held for f in findings) else UNSOUND)
        ),
    )

    judgements = trail.judgements
    held.computed = sum(
        1 for w in judgements if w.basis in (Basis.STRUCTURAL, Basis.BYTE)
    )
    held.judged = sum(1 for w in judgements if w.basis == Basis.EVALUATED)
    held.read = sum(1 for w in judgements if w.basis == Basis.ASSERTED)
    held.authorities = sorted(
        {w.authority for w in judgements if w.authority}
    )
    held.ruled_out = (
        trail.steps[0].sites - trail.steps[-1].sites if trail.steps else 0
    )

    # What survived, named rather than hashed, so a reader can go and look. The
    # survivors are the support for the output and are always few; everything
    # else is the `ruled_out` count.
    last = trail.steps[-1] if trail.steps else None
    if last is not None and graph is not None:
        for node_id in last.admissible[:40]:
            node = graph.nodes.get(node_id)
            if node is not None:
                held.stood_on.append(f"{node.path}:{node.line + 1} {node.qualified}")

        # The predicted region, named rather than hashed, and bounded: a reader
        # wants to see where the standard pointed, not every definition in it.
        for node_id in where[:40]:
            node = graph.nodes.get(node_id)
            if node is not None:
                held.expected.append(f"{node.path}:{node.line + 1} {node.qualified}")

    return held


# ── Keeping them, and not too many ───────────────────────────────────────


def _where(repo: Path | str) -> Path:
    from .home import home

    root = Path(repo).expanduser().resolve()
    key = hashlib.sha256(str(root).encode("utf-8")).hexdigest()[:12]
    directory = home() / "witnesses" / f"{root.name}-{key}"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def keep(held: Witness, repo: Path | str) -> Path:
    """Write a witness, and drop the oldest beyond `KEEP`.

    Trimmed on write rather than swept later, so the bound holds without
    anything having to remember to enforce it — a ring that depends on a
    separate pass is a ring that grows whenever that pass does not run.
    """
    directory = _where(repo)
    path = directory / f"{int(held.at * 1000):d}.json"
    path.write_text(held.model_dump_json(exclude_defaults=True), encoding="utf-8")

    try:
        kept = sorted(directory.glob("*.json"))
        for old in kept[:-KEEP]:
            old.unlink()
    except OSError:
        logger.info("could not trim witnesses for %s", repo)

    return path


def recent(repo: Path | str, limit: int = 10) -> List[Witness]:
    """The most recent witnesses for a project, newest first."""
    found: List[Witness] = []
    for path in sorted(_where(repo).glob("*.json"), reverse=True)[:limit]:
        try:
            found.append(Witness.model_validate_json(path.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            # One unreadable file must not make the rest unreadable: a reader
            # asking for history wants what survives.
            logger.info("unreadable witness: %s", path)
    return found


def keep_chain(trail: Convergence, repo: Path | str) -> Path:
    """Keep the full chain locally, for somebody debugging their own session.

    Not part of the witness and nothing depends on it. Written beside the
    witnesses so it is easy to find and easy to delete, and named for the moment
    it was taken so the two line up.
    """
    directory = _where(repo) / "chains"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{int(time.time() * 1000):d}.json"
    path.write_text(
        trail.small().model_dump_json(exclude_defaults=True), encoding="utf-8"
    )
    return path
