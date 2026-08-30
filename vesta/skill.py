"""Skills as authority: acquired from anywhere, pooled in one store, sliced per operation.

A skill is a standard somebody wrote down before today's work began, which is
what makes it worth treating as authority. A rule derived from the code cannot
contradict the code; a rule written last week can, and an action checked against
it is checked against something that could not have been bent to justify it.
Precedence is the argument — the same one `truth.py` makes about commit history,
where independence comes from having been written first rather than from
counting sources.

**The body is free-form, and that is the specification rather than a gap.**
Anthropic's documentation and the Agent Skills open standard both state it
outright: after the frontmatter there are no format restrictions. Measured
across thirty-one shipped skills that is plainly true — a twenty-fold spread in
length, a heading vocabulary whose most common member appears in eight of
thirty-one and then fragments into one-offs, some with no subheadings, some with
no bolded items, one with no title at all.

So nothing here mines the body for structure. An earlier version of this module
scraped headings into terms and reported nine of twelve as requirements this
repository did not meet — of which most were document scaffolding like "What it
will not tell you". That is the failure `procedure.py` refuses at write time:
something that looks like structure and is not, which a reader trusts and builds
on. Two frontmatter fields are guaranteed by the spec, and they are enough.

**The body is the instruction, and it is passed whole.** A skill says what to do
and when; shredding it into labels destroys exactly the part that instructs. So
the body is carried as opaque authority text and handed to whatever evaluates
it, intact.

**Truth here is pooled, and that is stated rather than hidden.** Most of what a
skill requires does not reduce to a predicate over a reference graph. Forcing
one would produce a small set of checkable-but-trivial conditions and silently
drop everything that mattered — rigour in appearance over a narrower claim. So
the verdict comes from evaluation, with the evidence recorded beside it, and the
limitation is named: **a pooled verdict re-run may differ from the recorded one
with no code having changed.** That is the nature of the mechanism, not a defect,
and a bundle that reported it as though it were computation would overstate
itself exactly as this project has twice had to stop its own detectors doing.

Three mitigations, none of which makes it deterministic:

*The retrieval is deterministic even though the judgement is not.* What evidence
an evaluator sees is computed from the graph, recorded, and re-derivable. When a
verdict is wrong the cause is usually the evidence rather than the reasoning, and
a witness that blends them cannot say which.

*A pooled verdict demotes; it never soundly prunes.* `SOUND_PRUNE` means certain
and not to be reopened, and a probabilistic result is precisely not that. A
wrong evaluation then costs a demotion rather than silently removing the right
answer from the space.

*The authority is named.* A reader who disagrees can go and read the skill.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Set, Tuple

from pydantic import BaseModel, Field

from .graph import Graph
from .traverse import Map, _bag

logger = logging.getLogger("vesta.skill")

# The frontmatter block, which the spec does pin down: it opens the file, and it
# closes on a line of its own. Everything after it is free-form by definition.
FRONTMATTER = re.compile(r"\A---\s*\n(.*?)^---\s*$\n?", re.S | re.M)

# One `key: value` line. Parsed rather than handed to a YAML library because
# pydantic is this project's only runtime dependency and the two fields that
# matter are both plain strings — a nested structure here would be a reason to
# take the dependency, and there is none.
FIELD = re.compile(r"^([A-Za-z_][\w-]*):\s*(.*?)\s*$", re.M)

# What the specification guarantees, and the whole of it. `name` is at most 64
# characters of lowercase and hyphens; `description` is at most 1024 and must
# say both what the skill does and when to use it. Every other field is
# optional, and the set of optional fields differs between the two published
# specs — so a missing one is never an error here.
NAME = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
NAME_CHARS = 64
DESCRIPTION_CHARS = 1024

# What a skill file is called. The one filename the specification does fix, and
# the only thing worth matching on: the directories above it are arranged
# differently by every harness that ships skills — measured on this machine,
# `.../external_plugins/<plugin>/skills/<name>/SKILL.md` beside
# `.../plugins/<plugin>/skills/<name>/SKILL.md` beside a plain `skills/<name>/`
# in a repository — and a fixed set of glob shapes matched one of those three.
FILENAME = "SKILL.md"

# How deep to walk below a directory somebody named. Bounded rather than
# unbounded: a user who points this at a home directory should wait a moment,
# not walk a disk. Six is past every layout observed and short of a filesystem.
#
# Searched only under a path a caller supplied — hunting for skills unasked
# finds something eventually and it is the wrong thing, which is the argument
# `across.resolve` already makes about guessing where a project lives.
DEPTH = 6


class Skill(BaseModel):
    """One skill, as an authority rather than as a document.

    The body is kept whole and never parsed. What a skill instructs is in its
    prose, and the prose is what gets handed to an evaluator.
    """

    name: str = ""
    description: str = ""
    # Everything else the frontmatter carried. Kept rather than validated: the
    # two published specs differ on which optional fields exist, and refusing an
    # unknown one would reject a skill written for the other.
    fields: Dict[str, str] = Field(default_factory=dict)

    # The instruction itself, whole.
    body: str = ""

    # Where it came from, so a reader who disagrees can go and read it.
    source: str = ""
    # What the file said when it was read. A skill edited after an operation
    # was judged against it is a different authority, and this is what lets a
    # later reader tell.
    digest: str = ""

    @property
    def id(self) -> str:
        """What identifies this authority, which is not its name alone.

        Measured on this machine: three shipped skills are called `access` —
        one each for Discord, Telegram and iMessage — with three genuinely
        different bodies. Keyed by name, a store would keep whichever was read
        last and silently discard two authorities, which for a thing whose whole
        job is to be the standard something was judged against is the worst
        available failure.

        So identity is the name plus a mark of the content. Two copies of the
        same skill collapse to one, as they should; two different skills sharing
        a name stay two.
        """
        if not self.name:
            return self.digest[:12]
        return f"{self.name}@{self.digest[:8]}"

    def describe(self) -> str:
        return f"{self.name}: {self.description[:160]}"


class Refused(BaseModel):
    """A file that could not be read as a skill, and why."""

    path: str
    why: str


class Store(BaseModel):
    """Every skill acquired, however it was acquired.

    One store rather than one per source, because an operation is judged against
    whatever authority the user has chosen to be active, and a set that has to
    be assembled from several places at question time is a set that gets
    assembled differently each time.
    """

    skills: List[Skill] = Field(default_factory=list)
    # Which are active. Empty means all of them: a user who has acquired skills
    # and chosen nothing has not thereby chosen nothing to apply.
    active: List[str] = Field(default_factory=list)
    at: float = 0.0

    @property
    def live(self) -> List[Skill]:
        if not self.active:
            return list(self.skills)
        wanted = set(self.active)
        return [s for s in self.skills if s.id in wanted]

    def by_id(self, which: str) -> Optional[Skill]:
        for skill in self.skills:
            if skill.id == which:
                return skill
        return None

    def describe(self) -> str:
        if not self.skills:
            return "no skills acquired"
        held = f"{len(self.skills)} skill(s)"
        if self.active:
            return f"{held}, {len(self.live)} active: " + ", ".join(
                s.id for s in self.live
            )
        return f"{held}, all active"


def read_skill(text: str, source: str = "") -> Tuple[Optional[Skill], str]:
    """One skill from the text of a file, or why it is not one.

    Strict about the frontmatter, because that is what the specification pins
    down, and entirely incurious about the body, because the specification says
    there is nothing there to rely on.
    """
    matched = FRONTMATTER.match(text)
    if not matched:
        return None, "no frontmatter — a skill opens with a --- block"

    fields = {k.lower(): v for k, v in FIELD.findall(matched.group(1))}
    body = text[matched.end() :]

    name = _unquoted(fields.pop("name", ""))
    description = _unquoted(fields.pop("description", ""))

    if not name:
        return None, "no name in the frontmatter"
    if len(name) > NAME_CHARS or not NAME.match(name):
        return None, f"name is not lowercase-and-hyphens within {NAME_CHARS}: {name!r}"
    if not description:
        return None, "no description — a skill has to say what it is for"

    return (
        Skill(
            name=name,
            # Truncated rather than refused. The limit is a specification about
            # what an author should write, and a skill that overruns it is still
            # a usable authority — refusing it would make this stricter than the
            # harness that loads it.
            description=description[:DESCRIPTION_CHARS],
            fields=fields,
            body=body,
            source=source,
            digest=hashlib.sha256(text.encode("utf-8")).hexdigest()[:16],
        ),
        "",
    )


def _unquoted(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


def acquire(where: Sequence[Path | str] | Path | str) -> Tuple[List[Skill], List[Refused]]:
    """Read skills from wherever the user has them.

    A file, a directory of them, a directory of directories, or several of any
    of those. Skills arrive by many routes — shipped with a plugin, written by
    hand, cloned from somewhere — and a reader that insists on one layout makes
    the user rearrange their disk to suit it.

    What could not be read is returned rather than logged away. A file somebody
    meant as a skill and that is not one is the thing they most need told.
    """
    wanted = [where] if isinstance(where, (str, Path)) else list(where)

    found: List[Skill] = []
    refused: List[Refused] = []
    seen: Set[str] = set()

    for entry in wanted:
        root = Path(entry).expanduser()
        if root.is_file():
            paths = [root]
        elif root.is_dir():
            paths = sorted(_walk(root))
        else:
            refused.append(Refused(path=str(root), why="no such file or directory"))
            continue

        for path in paths:
            if str(path) in seen:
                continue
            seen.add(str(path))
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError as exc:
                refused.append(Refused(path=str(path), why=str(exc)))
                continue
            skill, why = read_skill(text, source=str(path))
            if skill is None:
                refused.append(Refused(path=str(path), why=why))
                continue
            found.append(skill)

    return found, refused


def _walk(root: Path, depth: int = DEPTH) -> List[Path]:
    """Every skill file below a directory, pruning as it descends.

    Prunes rather than filtering afterwards, which is the lesson `held._shape`
    already paid for: `rglob` visited every excluded directory in full and then
    discarded each path, 66,010 of them to find 77 files. Nothing hidden is
    walked, and neither are the dependency directories every language keeps —
    the shared list in `home`, so this cannot disagree with what the resolver
    walks.
    """
    from .home import NOT_THE_PROJECT

    found: List[Path] = []
    frontier = [(root, 0)]
    while frontier:
        directory, at = frontier.pop()
        try:
            entries = list(directory.iterdir())
        except OSError:
            continue
        for entry in entries:
            if entry.name.startswith("."):
                continue
            if entry.is_file():
                if entry.name == FILENAME:
                    found.append(entry)
            elif entry.is_dir() and at < depth and entry.name not in NOT_THE_PROJECT:
                frontier.append((entry, at + 1))
    return found


def applies(skill: Skill, action: str, graph: Graph, mapped: Map) -> List[str]:
    """The evidence in this repository that bears on an action, for one skill.

    **This is the deterministic half, and it is kept separate on purpose.** What
    an evaluator concludes is a judgement; what it was shown is a computation,
    recorded and re-derivable. When a pooled verdict turns out wrong the cause is
    usually what was put in front of it rather than how it reasoned, and a record
    that blends the two cannot say which.

    A slice, not the whole ontology. Unless a skill is very specific, only part
    of it bears on any one operation, and handing an evaluator everything is how
    the relevant part gets lost among the rest.
    """
    # The action decides what is relevant; the skill only decides whether it is
    # in scope at all.
    #
    # Unioning the two was measured doing the opposite: a skill description of
    # sixty-five words beside an action of two made the action three percent of
    # the query, so every action returned the same twelve definitions —
    # including one about rendering a chart, in a repository that does no such
    # thing. A slice that does not vary with what was asked is not a slice.
    wanted = _bag(action)
    if not wanted:
        return []
    scope = _bag(skill.description)

    scored: List[Tuple[float, str]] = []
    for attachment in mapped.attachments:
        if attachment.node not in graph.nodes:
            continue
        label = _bag(attachment.label)
        overlap = len(wanted & label) / len(wanted) if label else 0.0
        node = graph.nodes[attachment.node]
        spoken = _bag(node.name) | _bag(node.path.replace("/", " "))
        overlap = max(overlap, len(wanted & spoken) / len(wanted) * 0.6)
        if not overlap:
            continue

        # Within the skill's own subject, a definition counts for more. A
        # nudge rather than a gate: a skill that never mentions a word is not
        # thereby an authority that excludes it, and a hard filter here would
        # make a broad skill silently narrow.
        if scope & (label | spoken):
            overlap *= 1.25

        scored.append((overlap * attachment.strength, attachment.node))

    scored.sort(reverse=True)

    ordered: List[str] = []
    for _, node_id in scored:
        if node_id not in ordered:
            ordered.append(node_id)
    return ordered[:12]


class Expected(BaseModel):
    """Where an authority and an intent say a change belongs, before it is made.

    Worked out in advance and independently, which is the whole of its value. A
    narrowing runs on the repository's graph and its own vocabulary; this runs on
    the standard's words crossed with what was asked. Two derivations from two
    sources, so a convergence agreeing with a prediction says something that a
    convergence checked against its own inputs never could.

    **What it establishes is conformance, not correctness.** The region is right
    relative to the standard and the intent. A standard that is wrong about what
    this repository does yields a confident prediction of the wrong place, and a
    convergence that lands there is faithfully wrong. That is the same limit
    every conformance check has, and it is why the standard travels with the
    record: whoever wrote it is answerable for what it says.
    """

    where: List[str] = Field(default_factory=list)
    # The lines of the standard that produced this, so a reader can see what was
    # relied on rather than the whole document.
    because: List[str] = Field(default_factory=list)
    # Nothing to predict from. Not an empty prediction — an absent one, and the
    # difference matters: treating "the standard says nothing about this" as
    # "nothing is admissible" would report every landing as out of bounds.
    unpredicted: bool = False


def expect(
    skill: Skill, action: str, graph: Graph, mapped: Map, hops: int = 0
) -> Expected:
    """Where this standard, asked about this work, says the change belongs.

    The standard's own words are the source, crossed with what was asked, and
    read against the repository's map.

    **No hop by default.** A narrowing already spreads through the graph, and a
    prediction that spreads too puts both sides in the same neighbourhood, where
    agreement stops being evidence — measured on this repository, 64 named
    definitions became 350 after one hop, a region loose enough to admit almost
    any landing. What the standard *names* is the bound; what a change reaches
    from there is the narrowing's business, and conflating them makes the check
    pass by construction.

    An authority whose vocabulary reaches nothing here predicts nothing, and
    says so. A prediction of the empty set and no prediction at all are
    different facts: the first says the change belongs nowhere, which is almost
    never true, and the second says this standard has nothing to say about this
    work, which frequently is.
    """
    from .warrant import _spread

    wanted = _bag(skill.description) & _bag(action)
    if not wanted:
        # The standard and the request share no vocabulary, so this authority is
        # not about this work. Reported rather than guessed at.
        return Expected(unpredicted=True)

    seeds: List[str] = []
    because: List[str] = []
    for attachment in mapped.attachments:
        if attachment.node not in graph.nodes:
            continue
        label = _bag(attachment.label)
        if not label or not (wanted & label):
            continue
        seeds.append(attachment.node)
        if attachment.label not in because:
            because.append(attachment.label)

    if not seeds:
        return Expected(unpredicted=True, because=because)

    return Expected(where=sorted(_spread(graph, seeds, hops)), because=because)


def to_judge(skill: Skill, action: str, evidence: Sequence[str], graph: Graph) -> str:
    """What to put in front of an evaluator, and nothing else.

    The skill's own words as the standard, the action as the claim, and the
    evidence as what this repository actually has. Assembled here so that what
    was asked is recorded in one place rather than reconstructed from a prompt
    somebody wrote at the call site.

    Nothing here calls a model. The evaluation runs on the host's own inference,
    the way every other derivation in this project does — Vesta holds no key and
    makes no network call, and that is asserted mechanically by the test suite
    rather than promised here.
    """
    lines = [
        f"AUTHORITY — the {skill.name} skill says:",
        skill.description,
        "",
        skill.body.strip(),
        "",
        f"PROPOSED — {action}",
        "",
        "EVIDENCE — what this repository has that bears on it:",
    ]
    for node_id in evidence:
        node = graph.nodes.get(node_id)
        if node is not None:
            lines.append(f"  {node.path}:{node.line + 1} {node.qualified}")
    if not evidence:
        lines.append("  (nothing in this repository was found to bear on it)")
    return "\n".join(lines)


class Difference(BaseModel):
    """What an authority is about, set against what this repository names.

    The useful half of an ontology has always been what it does *not* reach —
    `Map.unattached` keeps exactly that for a derived one, on the grounds that a
    term with no code behind it is either work the project has not built or work
    it calls something else, and both are worth seeing. Asked of a skill the
    same question becomes a checklist: here is a standard, and here is the part
    of it nothing here answers to.
    """

    skill: str = ""
    # Words the skill's own description uses that the repository's vocabulary
    # and code both fail to use anywhere.
    unnamed: List[str] = Field(default_factory=list)
    # Words shared by both, which is the evidence the skill is about this
    # project at all.
    shared: List[str] = Field(default_factory=list)

    @property
    def bears_on(self) -> bool:
        """Whether this authority appears to be about this repository.

        A skill sharing none of its vocabulary is not a standard this project
        falls short of — it is a standard about something else, and reporting
        its every word as unmet would fill a report with absences nobody should
        act on.
        """
        return bool(self.shared)

    def describe(self) -> str:
        if not self.bears_on:
            return (
                f"{self.skill} shares no vocabulary with this repository — it "
                "looks like a standard for different work, not one this falls "
                "short of"
            )
        if not self.unnamed:
            return f"{self.skill}: this repository names everything it asks about"
        return (
            f"{self.skill}: this repository has no word for "
            + ", ".join(self.unnamed[:12])
            + (f" and {len(self.unnamed) - 12} more" if len(self.unnamed) > 12 else "")
        )


def difference(skill: Skill, graph: Graph, mapped: Map) -> Difference:
    """What a skill asks about that this repository does not name.

    Compared against the ontology's labels *and* the code's own identifiers,
    because a repository can perform work its vocabulary has not caught up with
    — the same two surfaces `traverse.where` crosses, for the same reason.

    Nothing here concludes the repository is deficient. A word this project does
    not use may be work it genuinely does not do, work it calls something else,
    or a word the skill uses loosely; which of those it is takes a reader, and
    the honest output is the list rather than a verdict on it.
    """
    wanted = _bag(skill.description)
    if not wanted:
        return Difference(skill=skill.id)

    known: Set[str] = set()
    for attachment in mapped.attachments:
        if attachment.node in graph.nodes:
            known |= _bag(attachment.label)
    for node in graph.nodes.values():
        if node.line > 0 and not node.path.startswith("tests/"):
            known |= _bag(node.name) | _bag(node.path.replace("/", " "))

    return Difference(
        skill=skill.id,
        unnamed=sorted(wanted - known),
        shared=sorted(wanted & known),
    )


# ── Keeping the store ────────────────────────────────────────────────────
#
# One store per project, in Vesta's home rather than in the repository: which
# authorities a user has chosen is a fact about how they work, not about the
# code, and nothing about it belongs in a diff.


def _where(repo: Path | str) -> Path:
    from .home import kept_at

    return kept_at(repo, "skills")


def keep(store: Store, repo: Path | str) -> Path:
    store.at = time.time()
    path = _where(repo)
    path.write_text(store.model_dump_json(indent=2), encoding="utf-8")
    return path


def recall(repo: Path | str) -> Optional[Store]:
    path = _where(repo)
    if not path.is_file():
        return None
    try:
        return Store.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def add(repo: Path | str, where: Sequence[Path | str] | Path | str) -> Tuple[Store, List[Refused]]:
    """Acquire skills into this project's store, replacing any of the same name.

    Replacing rather than duplicating: acquiring the same skill twice is how a
    user re-reads one they have edited, and two copies of an authority that
    disagree is worse than either alone.
    """
    store = recall(repo) or Store()
    found, refused = acquire(where)

    by_id = {s.id: s for s in store.skills}
    for skill in found:
        by_id[skill.id] = skill
    store.skills = sorted(by_id.values(), key=lambda s: s.id)

    keep(store, repo)
    return store, refused


def activate(repo: Path | str, which: Sequence[str]) -> Store:
    """Choose which authorities apply. An empty choice means all of them.

    Deliberately not an error to name something absent: a user combining
    authorities across projects will name one this project has not acquired, and
    refusing the whole selection over it would lose the rest of their choice.
    Unknown names are dropped and the store says what is live.
    """
    store = recall(repo) or Store()

    # Selected by id or by bare name. A user should not have to type a digest to
    # choose an authority, and naming one that happens to be ambiguous activates
    # both rather than picking one — an authority silently dropped is the
    # failure this store exists to avoid, and two is a thing they can see.
    chosen: List[str] = []
    for wanted in which:
        for skill in store.skills:
            if wanted in (skill.id, skill.name) and skill.id not in chosen:
                chosen.append(skill.id)

    store.active = chosen
    keep(store, repo)
    return store
