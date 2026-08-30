"""Whether a decision space is contracting as work approaches its output.

An agent proposing to change something is standing in a space of possibilities:
every definition it might edit, and every behaviour the result might have. Work
that is going well makes that space smaller. Each thing established — the
ontology names this work, the graph says it reaches here, a rule forbids that
placement, the contract already fixed this behaviour — rules something out and
cannot rule it back in.

**Narrowing is a property of the trajectory, not of a phrase.** A single
question against a single snapshot says only how much of a repository some words
touch, which is a fact about vocabulary. What matters is whether the space is
*converging*: whether step three is meaningfully smaller than step one, and
whether what fell away fell away for a reason somebody can read. A space that
stops contracting is the signal — the work has stopped being decided and is
being elaborated instead, and no amount of further iteration will finish it.

**Two axes, because a decision is not located until both are.** *Sites* are
where the change could land: definitions still admissible after everything known
has been applied. *Outputs* are what the result may do: behaviours still open
once the contract and the stated constraints have had their say. Converging on
one alone is a familiar failure — an agent that knows exactly which file to edit
and not what the edit should achieve, or one that knows precisely what it must
build and not where anything goes.

**Every exclusion is witnessed, and the reason is typed.** `space.refine`
established the discipline for rules and this borrows it exactly: a *sound*
exclusion is certain and this pass will not reopen it, a *demotion* is a
priority judgement that stays reversible, and a *gap* is something nothing could
decide — emitted rather than dropped, because a candidate that vanished without
a reason is indistinguishable from one nobody considered. A reader given "3
sites remain" cannot ask why the other 668 are gone; a reader given the witness
can.

**Nothing here blocks and nothing here is a permission.** A space that will not
contract is reported as what it is — evidence, of the same kind `distance`
produces, and routed the same way: `driving` already treats three readings that
do not move as stuck, and a space that will not narrow is that same shape of
fact arriving on a second, independent axis. Two signals agreeing is worth more
than either alone, and neither is the model's opinion of its own work.

**What this cannot do is know whether the surviving site is the right one.** A
space can contract to exactly one definition that is the wrong definition. What
converges is the decision, not its correctness — the same limit `authority`
states about currency, and worth stating again here because a number that falls
reads like a number that is right.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Set, Tuple

from pydantic import BaseModel, Field

from .graph import Graph
from .space import Basis, Verdict, Witness
from .traverse import Attachment, Map, _bag, where

logger = logging.getLogger("vesta.warrant")

# How far a step will walk from a definition the ontology named. One hop is the
# neighbourhood a change is normally about — what calls this and what it calls.
# Past that the reachable set stops distinguishing anything on a densely
# connected graph, which is the failure this measures rather than a depth worth
# offering.
REACH = 1

# How many steps that do not contract before a space is stuck. Three, for the
# reason `driving.STUCK_AFTER` is three: one is ordinary, since a step spent
# establishing context rules nothing out; two can be a slow start; three in a
# row is a pattern.
STUCK_AFTER = 3

# A contraction smaller than this is not one. Expressed as a share of the space
# rather than a count, so a step that rules out four of six hundred candidates
# is not mistaken for progress while the same four out of nine is.
MOVED = 0.02


class Intervention(BaseModel):
    """One occasion on which guidance overrode the evidence, at the step it did.

    Guided mode's raw signal. The narrowing computed what the evidence supported
    — exactly as blind mode would — and the region said otherwise, so the
    candidate's standing was reduced. Never its membership: the region rests on
    the specifications, whose adequacy is exactly what a later reader is
    entitled to question, and a wrong specification allowed to remove would take
    the correct answer with it, irrecoverably.

    Few when the specifications and the subject agree, which is what makes them
    worth carrying in full: the interventions are precisely the informative
    events, and zero of them is the guided-mode reading of two independent
    sources concurring.
    """

    step: int = 0
    about: str = ""
    path: str = ""
    line: int = 0
    name: str = ""
    # What the evidence supported, and what guidance did about it.
    evidence: str = ""
    action: str = "demoted"

    def describe(self) -> str:
        where = f"{self.path}:{self.line + 1} {self.name}" if self.path else self.about
        return f"step {self.step}: {where} — {self.evidence}; {self.action}"


class Step(BaseModel):
    """One measurement of a decision space, and what closed it further.

    A step is a fact about a moment: this many sites were still admissible, this
    many behaviours were still open, and these are the things that ruled the
    rest out. Steps are compared to each other; none of them means anything
    alone, which is the whole correction this module is built on.
    """

    at: float = 0.0
    # What the agent said it was doing when this was taken. Carried so a
    # trajectory can be read back as a story rather than a column of numbers.
    doing: str = ""

    # The two axes. `sites` is the count still admissible; `outputs` is the
    # count of behaviours still open. Both are counts of what *remains*, so a
    # converging trajectory is a falling one on both.
    sites: int = 0
    outputs: int = 0

    # What the space was before anything was applied, so a share can be taken.
    # A step that cannot say what it narrowed *from* is not a measurement.
    population: int = 0

    # Why each candidate is no longer admissible, typed as `space.Verdict`.
    # Sound exclusions are permanent; demotions can be reopened; gaps record
    # what nothing could decide.
    witness: List[Witness] = Field(default_factory=list)

    # Where guidance overrode the evidence at this step (guided mode only).
    # Kept whole rather than counted: they are few when the process is healthy,
    # and they are precisely the informative events.
    interventions: List[Intervention] = Field(default_factory=list)

    # Reasons this step gave, held once and referred to by position.
    #
    # A step rules candidates out for a handful of reasons and repeats each
    # across everything it excluded — measured on this repository, 730
    # judgements carried three distinct reasons, 710 of them the same sentence.
    # Stored per entry that was 183kb of a 201kb bundle, which is a record too
    # large to keep and therefore a record nobody keeps.
    #
    # `Witness.reason` still reads normally; this is only how it is written
    # down. Nothing a reader can ask for is lost, because nothing was there:
    # the seven hundredth copy of a sentence says exactly what the first said.
    reasons: List[str] = Field(default_factory=list)

    def packed(self) -> "Step":
        """A copy with repeated reasons folded into the shared list.

        Done on the way to disk rather than at construction: a caller holding
        these entries is entitled to read `reason` on each of them, and quietly
        emptying the field underneath them would make an in-memory step behave
        differently from one that had merely been saved.
        """
        from .graph import _node_id

        seen: Dict[str, int] = {}
        held: List[str] = []
        entries: List[Witness] = []
        for judged in self.witness:
            entry = judged.model_copy()
            if entry.reason:
                if entry.reason not in seen:
                    seen[entry.reason] = len(held)
                    held.append(entry.reason)
                entry.says = seen[entry.reason]
                entry.reason = ""
            # A node id is `sha256(path, line, name)` — so where all three are
            # here, the id is arithmetic on them and storing it too is sixteen
            # characters of nothing, seven hundred times over. Dropped only when
            # it demonstrably rebuilds; an id from anywhere else is kept as-is.
            if entry.about and entry.path and entry.name:
                if _node_id(entry.path, entry.line, entry.name) == entry.about:
                    entry.about = ""
            entries.append(entry)

        # A space nothing was ruled out of is the whole population, and
        # `population` already says how large that is. Spelling out every id to
        # mean "all of them" cost 15kb of a bundle for no fact a reader lacked.
        keeping = [] if self.sites == self.population else self.admissible

        return self.model_copy(
            update={"witness": entries, "reasons": held, "admissible": keeping}
        )

    def unpacked(self) -> "Step":
        """A copy with every reason put back where a reader expects it."""
        from .graph import _node_id

        entries: List[Witness] = []
        for judged in self.witness:
            entry = judged.model_copy()
            if not entry.reason and 0 <= entry.says < len(self.reasons):
                entry.reason = self.reasons[entry.says]
            if not entry.about and entry.path and entry.name:
                entry.about = _node_id(entry.path, entry.line, entry.name)
            entries.append(entry)
        return self.model_copy(update={"witness": entries, "reasons": []})

    # The definitions still admissible after this step.
    #
    # Not written to disk when the step rules nothing out. The open space is
    # every definition in the repository, and listing all 746 of them cost 15kb
    # of a bundle to say "everything" — a fact `population` already carries as
    # one integer. The same is true of any later step that excluded nothing.
    #
    # What is kept is every space that a step actually narrowed, which is the
    # only version anybody reads: a reader asks what survived, and "all of it"
    # is not a list they need spelled out.
    admissible: List[str] = Field(default_factory=list)

    @property
    def share(self) -> float:
        """How much of the original space is still open. Lower is tighter."""
        if not self.population:
            return 0.0
        return self.sites / self.population

    @property
    def sound(self) -> int:
        """Exclusions this pass will not reopen."""
        return sum(1 for w in self.witness if w.verdict == Verdict.SOUND_PRUNE)

    @property
    def gaps(self) -> int:
        """Candidates nothing could decide about."""
        return sum(1 for w in self.witness if w.verdict == Verdict.GAP)

    @property
    def replayable(self) -> float:
        """What share of this step's judgements re-running could confirm."""
        if not self.witness:
            return 0.0
        return sum(1 for w in self.witness if w.replayable) / len(self.witness)

    def describe(self) -> str:
        parts = [f"{self.sites} site(s) of {self.population}"]
        parts.append(
            "output open" if self.outputs != 1 else "one admissible output"
        )
        if self.outputs > 1:
            parts[-1] = f"{self.outputs} behaviours still open"
        if self.gaps:
            parts.append(f"{self.gaps} undecided")
        return ", ".join(parts)


class Convergence(BaseModel):
    """A trajectory of steps, and whether the space is closing.

    This is the witness object. Every figure in it is recomputable from the
    repository and the steps that produced it — the discipline `authority`
    follows in carrying `was` and `now`, so a reader who doubts the verdict
    checks the working rather than taking the verdict's word.
    """

    action: str = ""
    steps: List[Step] = Field(default_factory=list)

    # How the narrowing related to the predicted region: "blind" — never shown
    # it, so the landing is evidence — or "guided" — steered by it, so the
    # signal moves to the interventions. Fixed when the trajectory opens;
    # a mode that switched mid-flight would make every figure unreadable.
    mode: str = "blind"

    @property
    def interventions(self) -> List[Intervention]:
        """Every occasion guidance overrode the evidence, in order."""
        return [i for step in self.steps for i in step.interventions]

    @property
    def friction(self) -> float:
        """How often guidance had to act, against how much was judged.

        The guided mode's correctness signal. Near zero, the specifications and
        the subject's evidence concurred — the same two-source agreement a
        blind in-region landing is, observed through a different instrument.
        High, the specifications dragged the decision against the evidence,
        which is a fact about one of them and the attribution's job to say
        which.
        """
        judged = len(self.judgements)
        if not judged:
            return 0.0
        return len(self.interventions) / judged

    @property
    def latest(self) -> Optional[Step]:
        return self.steps[-1] if self.steps else None

    @property
    def first(self) -> Optional[Step]:
        return self.steps[0] if self.steps else None

    @property
    def narrowing(self) -> float:
        """How much of the space has been ruled out across the whole trajectory.

        Zero for a trajectory that has not started, and zero — not one — for a
        space that was never populated. A space of nothing has not been narrowed
        by ruling nothing out, and reporting 1.00 there would give the most
        confident value in the range to the least grounded claim.
        """
        if not self.steps or not self.first or not self.first.population:
            return 0.0
        return 1.0 - (self.steps[-1].sites / self.first.population)

    def small(self) -> "Convergence":
        """A copy small enough to keep, with repeated reasons folded away.

        A bundle is mostly witness, and a witness is mostly the same sentence
        over and over: measured on this repository, 730 judgements carrying
        three distinct reasons came to 183kb of a 201kb bundle. A record that
        large is one nobody keeps, and a trail nobody keeps answers nothing.
        """
        return self.model_copy(update={"steps": [s.packed() for s in self.steps]})

    def whole(self) -> "Convergence":
        """A copy with every reason put back where a reader expects it."""
        return self.model_copy(update={"steps": [s.unpacked() for s in self.steps]})

    @property
    def judgements(self) -> List[Witness]:
        """Every judgement across the trajectory, in the order it was made."""
        return [w for step in self.steps for w in step.witness]

    @property
    def replayable(self) -> float:
        """What share of this trajectory's reasoning re-running could confirm.

        The number a bundle has to state about itself. A trail that replays
        entirely and one that rests mostly on what an agent read are worth very
        different amounts, and they are indistinguishable unless the record says
        so — which is the whole reason `Basis` exists rather than every
        judgement being taken at face value.
        """
        judged = self.judgements
        if not judged:
            return 0.0
        return sum(1 for w in judged if w.replayable) / len(judged)

    @property
    def asserted(self) -> List[Witness]:
        """Judgements nothing can re-run, so a reader can see exactly which."""
        return [w for w in self.judgements if not w.replayable]

    @property
    def converged(self) -> bool:
        """Whether both axes have closed.

        One site and one admissible output. Deliberately strict: a space with
        two admissible outputs has not decided what it is building, however
        precisely it knows where the code goes.
        """
        last = self.latest
        return bool(last and last.sites == 1 and last.outputs == 1)

    @property
    def contracting(self) -> bool:
        """Whether the most recent step ruled anything out."""
        if len(self.steps) < 2:
            return True
        before, after = self.steps[-2], self.steps[-1]
        if not before.population:
            return False
        closed = (before.sites - after.sites) / before.population
        return closed >= MOVED or after.outputs < before.outputs

    @property
    def stuck(self) -> bool:
        """Whether the space has stopped being decided.

        The same shape of judgement `driving.State.stuck` makes about readings,
        on a second and independent axis. An agent convinced it is making
        progress will say so indefinitely; a space that has not contracted in
        three consecutive steps is a fact that does not care what it thinks.
        """
        if len(self.steps) <= STUCK_AFTER:
            return False
        recent = self.steps[-(STUCK_AFTER + 1) :]
        for before, after in zip(recent, recent[1:]):
            if not before.population:
                continue
            closed = (before.sites - after.sites) / before.population
            if closed >= MOVED or after.outputs < before.outputs:
                return False
        return True

    def describe(self) -> str:
        if not self.steps:
            return f'nothing has been established about "{self.action}" yet'

        trail = " → ".join(str(step.sites) for step in self.steps)
        outputs = " → ".join(str(step.outputs) for step in self.steps)
        lines = [
            f'"{self.action}"',
            f"  sites    {trail}",
            f"  outputs  {outputs}",
        ]
        if self.mode == "guided":
            lines.append(
                f"  guided — {len(self.interventions)} intervention(s), "
                f"friction {self.friction:.0%}"
            )

        if self.converged:
            lines.append(
                f"converged — {self.narrowing:.0%} of the space ruled out, "
                "one site and one admissible output remain"
            )
        elif self.stuck:
            lines.append(
                f"not converging — {len(self.steps)} steps, and nothing has been "
                f"ruled out in the last {STUCK_AFTER}. The work is being "
                "elaborated rather than decided."
            )
        elif not self.contracting:
            lines.append(
                "the last step ruled nothing out — it established context "
                "rather than closing the space, which is ordinary once"
            )
        else:
            lines.append(f"contracting — {self.narrowing:.0%} ruled out so far")

        judged = self.judgements
        if judged:
            # Said whichever way it falls. A trajectory that replays entirely
            # earns saying so, and one that does not must not be allowed to
            # imply it — which is what silence would do.
            replays = sum(1 for w in judged if w.replayable)
            pooled = sum(1 for w in judged if w.basis == Basis.EVALUATED)
            if replays == len(judged):
                lines.append(
                    f"all {len(judged)} judgement(s) can be re-checked against the code"
                )
            else:
                said = (
                    f"{replays} of {len(judged)} judgement(s) can be re-checked "
                    f"against the code ({self.replayable:.0%})"
                )
                if pooled:
                    # Named separately from what was merely read. An evaluated
                    # verdict has its evidence recorded and can be put back in
                    # front of an authority; what it cannot promise is the same
                    # answer, and that is a different caveat from "nothing can
                    # check this".
                    said += (
                        f"; {pooled} were judged against an authority and may "
                        "evaluate differently on another run"
                    )
                if replays + pooled < len(judged):
                    said += "; the rest were read and decided, and nothing can confirm them"
                lines.append(said)

        last = self.latest
        if last and last.gaps:
            lines.append(
                f"{last.gaps} candidate(s) nothing could decide about — a gap is "
                "not an exclusion, and they are still in the space"
            )
        return "\n".join(lines)

    def why_gone(self, name: str) -> List[Witness]:
        """Every recorded reason a candidate is no longer admissible.

        The question a bare count cannot answer, and the reason the witness is
        kept: told "3 sites remain", a reader cannot ask what happened to the
        other 668.
        """
        return [
            w
            for step in self.steps
            for w in step.witness
            # By identity where the judgement carries one, so a definition that
            # moved between the judgement and the question still answers to the
            # same name. The display string is the fallback for a judgement
            # about something with no location — a rule, or the action itself.
            if name in (w.about, w.name)
            or (not w.about and (w.rule == name or w.rule.endswith(f" {name}")))
        ]


def _population(graph: Graph) -> List[str]:
    """The definitions a change could land on.

    Module nodes are synthetic — one per file at line 0, so module-scope
    references have somewhere to land — and counting them would inflate the
    denominator with things nobody proposes to edit. Tests are excluded for the
    same reason `inject._named` excludes them: a definition under test is
    support for the code rather than the code.
    """
    return [
        node.id
        for node in graph.nodes.values()
        if node.line > 0
        and not node.is_module
        and "/tests/" not in node.path
        and not node.path.startswith("tests/")
    ]


def _spread(graph: Graph, seeds: Sequence[str], hops: int) -> Dict[str, int]:
    """Definitions reachable from the seeds, and at what depth.

    Both directions, because a change reaches both ways: what this refers to may
    have to change with it, and what refers to this may break because of it.
    """
    depth: Dict[str, int] = {seed: 0 for seed in seeds if seed in graph.nodes}
    frontier = list(depth)

    for step in range(1, max(0, hops) + 1):
        following: List[str] = []
        for node_id in frontier:
            neighbours = [edge.target for edge in graph.depends_on(node_id)]
            neighbours += [edge.source for edge in graph.referenced_by(node_id)]
            for other in neighbours:
                if other in depth or other not in graph.nodes:
                    continue
                depth[other] = step
                following.append(other)
        if not following:
            break
        frontier = following

    return depth


def _named(
    phrase: str, graph: Graph, mapped: Map
) -> Tuple[Dict[str, Attachment], List[str]]:
    """What the ontology names for this phrase, and what it left unaccounted.

    A binding whose definition merely moved is re-anchored rather than dropped:
    a line inserted above a function changes its id, and treating that as a
    binding pointing at nothing is what left most of a real map dangling. What
    stays dropped is a binding nothing answers to at all — renamed, moved
    between files, or deleted — because recovering those would mean guessing.

    The unaccounted words are returned because they say the vocabulary did not
    cover what was asked, which is a different failure from the work being
    absent and has a different remedy.
    """
    hits = where(graph, mapped, phrase, limit=12)

    # Re-anchored by (path, name) where the id no longer resolves. Keyed by
    # where each binding points *now*, so everything downstream — the spread,
    # the witness, the anchors — works in current ids rather than the ids the
    # ontology was written against.
    resolved = mapped.resolve_against(graph)
    live: Dict[str, Attachment] = {}
    for attachment in hits:
        at = resolved.at.get(id(attachment))
        if at is not None:
            live[at] = attachment

    asked = _bag(phrase)
    accounted: Set[str] = set()
    for node_id, attachment in live.items():
        accounted |= asked & _bag(attachment.label)
        node = graph.nodes.get(node_id)
        if node is not None:
            accounted |= asked & (_bag(node.name) | _bag(node.path.replace("/", " ")))

    return live, sorted(asked - accounted)


def open_space(
    action: str, graph: Graph, doing: str = "the space before anything is known"
) -> Step:
    """The space before anything has been established.

    Every definition is admissible and every output is open. This is step zero
    and it exists to be the denominator: a trajectory whose first step is
    already narrow has not narrowed, it started small, and without this the
    difference is invisible.
    """
    population = _population(graph)
    return Step(
        at=time.time(),
        doing=doing,
        sites=len(population),
        # Open, not zero. Nothing has fixed what the result must do, and
        # recording that as no admissible outputs would read as an impossible
        # action rather than an undecided one.
        outputs=0,
        population=len(population),
        admissible=population,
    )


def narrow(
    previous: Step,
    graph: Graph,
    mapped: Map,
    action: str,
    doing: str,
    outputs: Optional[int] = None,
    # The predicted region, where the caller is running guided. Candidates the
    # evidence keeps but the region does not admit are demoted — never removed
    # — and each such override is recorded as an intervention at this step.
    # None means blind: the narrowing never sees the region, and its landing
    # keeps its full evidential weight.
    region: Optional[Set[str]] = None,
    # A caller's own rule. Returns a verdict and a reason, and optionally the
    # basis that rule rests on — omitted means `ASSERTED`, the kind that claims
    # least, because a basis nobody stated is not one to infer for them.
    excludes: Optional[
        Callable[[str], Optional[Tuple[Verdict, str] | Tuple[Verdict, str, Basis]]]
    ] = None,
) -> Step:
    """Apply what is now known, and record what it ruled out.

    The ontology and the graph do the first narrowing: a definition the
    vocabulary reaches, directly or within `REACH` hops of something it names,
    stays admissible. `excludes` is how a caller applies everything else it
    knows — a rule about where code may live, a contract behaviour already
    fixed, a test that covers only some of the candidates — returning a verdict
    and a reason for each candidate it rules out, or None to leave it standing.

    Every exclusion is witnessed with its reason. A candidate that disappears
    without one is indistinguishable from a candidate nobody considered, which
    is the difference between a decision and a coincidence.
    """
    live, unaccounted = _named(action, graph, mapped)
    reachable = set(_spread(graph, list(live), REACH)) if live else set()

    witness: List[Witness] = []
    surviving: List[str] = []

    def judged(
        node_id: str, verdict: Verdict, why: str, basis: Basis = Basis.ASSERTED
    ) -> Witness:
        """One judgement, carrying what it was about rather than only its label.

        Identity and display are filled from the same place so they cannot
        drift: a judgement whose `rule` says one definition and whose `path`
        says another would be worse than one carrying no identity at all.
        """
        node = graph.nodes.get(node_id)
        return Witness(
            verdict=verdict,
            reason=why,
            about=node_id,
            path=node.path if node else "",
            line=node.line if node else 0,
            name=node.name if node else "",
            # No `said`: for a definition the display is exactly
            # `path:line name`, and storing it beside the parts is the same
            # string twice — 730 times over, on a trajectory this size.
            said="" if node else node_id,
            basis=basis,
        )

    for node_id in previous.admissible:
        if live and node_id not in reachable:
            # Sound: the vocabulary of this repository does not reach here, and
            # nothing later in this pass will make it reach. Reopening it would
            # mean the ontology had changed, which is a different pass.
            witness.append(
                judged(
                    node_id,
                    Verdict.SOUND_PRUNE,
                    "no term the ontology names reaches this",
                    # Structural: reachability over the graph, so re-running it
                    # against the current graph either agrees or does not. What
                    # is *not* structural is the ontology binding underneath —
                    # an agent read a definition and labelled it — and that
                    # basis belongs to the attachment, not to this exclusion.
                    # This judgement is only ever "the seeds do not reach here",
                    # which is arithmetic on edges.
                    Basis.STRUCTURAL,
                )
            )
            continue

        if excludes is not None:
            ruled = excludes(node_id)
            if ruled is not None:
                # A caller may state the basis of its own rule; one that does
                # not gets `ASSERTED`, because a basis nobody claimed is not one
                # this can infer on their behalf.
                verdict, why, *rest = ruled
                basis = rest[0] if rest else Basis.ASSERTED

                # A pooled verdict may not close the space.
                #
                # `SOUND_PRUNE` means certain and not to be reopened, and an
                # evaluation is precisely not that: the same authority over the
                # same evidence may come back differently. Letting one prune
                # would let a wrong call silently remove the right answer with
                # no way back. Demoted instead — a ranking rather than a
                # candidate — and the substitution is recorded in the reason so
                # a reader sees the ceiling rather than wondering why their
                # rule did not bite.
                if basis == Basis.EVALUATED and verdict == Verdict.SOUND_PRUNE:
                    verdict = Verdict.DEMOTE
                    why = f"{why} (demoted, not excluded: an evaluated verdict is not certain)"

                witness.append(judged(node_id, verdict, why, basis))
                # A demotion is reversible and a gap is undecided, so neither
                # removes a candidate from the space — only a sound prune does.
                # Collapsing them would let "nothing could check this" silently
                # do the work of "this is certainly not it", which is the
                # distinction `space` exists to keep.
                if verdict == Verdict.SOUND_PRUNE:
                    continue

        surviving.append(node_id)

    if not live:
        # The vocabulary did not reach anything, so nothing was ruled out on
        # that basis. Recorded as a gap rather than left silent: a step that
        # narrows nothing because it could not read the question is a different
        # fact from one that narrows nothing because everything still applies.
        witness.append(
            Witness(
                said=action,
                verdict=Verdict.GAP,
                reason=(
                    "nothing in this repository's vocabulary matches this"
                    + (f" — unaccounted: {', '.join(unaccounted)}" if unaccounted else "")
                ),
                # Nothing was decided, so there is nothing replay could confirm.
                basis=Basis.ASSERTED,
            )
        )

    # Guided: the evidence has spoken above, exactly as it would blind. Now the
    # region gets its say — and only a say. A surviving candidate the region
    # does not admit is demoted, never removed: the region rests on the
    # specifications, whose adequacy is an open question by design, and a wrong
    # specification allowed to remove would take the correct answer with it.
    # Each override is recorded where it happened, which is what makes drift
    # visible at the step it begins rather than at a post-mortem.
    interventions: List[Intervention] = []
    if region is not None:
        for node_id in surviving:
            if node_id in region:
                continue
            node = graph.nodes.get(node_id)
            interventions.append(
                Intervention(
                    about=node_id,
                    path=node.path if node else "",
                    line=node.line if node else 0,
                    name=node.name if node else "",
                    evidence="the evidence kept this at standing",
                    action="demoted — outside the region the specifications predict",
                )
            )

    return Step(
        at=time.time(),
        doing=doing,
        sites=len(surviving),
        outputs=previous.outputs if outputs is None else outputs,
        population=previous.population,
        witness=witness,
        interventions=interventions,
        admissible=surviving,
    )


def track(action: str, steps: Sequence[Step]) -> Convergence:
    """A trajectory, from the steps that produced it."""
    return Convergence(action=action, steps=list(steps))


# ── Holding a trajectory between calls ───────────────────────────────────
#
# A step is only meaningful beside the steps before it, and those were taken in
# earlier turns. So a trajectory is kept per project, in Vesta's own home rather
# than in the repository: it is a working measurement about a session, not a
# fact about the code, and nothing about it belongs in a diff.


def keep(found: Convergence, repo: Path | str) -> Path:
    """Write a trajectory, so the next step has something to compare against."""
    from .home import kept_at

    path = kept_at(repo, "converging")
    path.write_text(
        found.small().model_dump_json(exclude_defaults=True), encoding="utf-8"
    )
    return path


def recall(repo: Path | str, action: str = "") -> Optional[Convergence]:
    """The trajectory in progress for this repository, if there is one.

    An `action` that does not match the one being tracked returns None rather
    than the wrong trajectory: two different pieces of work have two different
    decision spaces, and continuing one under the other's name would report a
    contraction that never happened.
    """
    from .home import kept_at

    path = kept_at(repo, "converging")
    if not path.is_file():
        return None
    try:
        held = Convergence.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if action and held.action != action:
        return None
    return held.whole()


def forget(repo: Path | str) -> None:
    """Drop the trajectory. A new action starts from an open space."""
    from .home import kept_at

    try:
        kept_at(repo, "converging").unlink()
    except OSError:
        pass
