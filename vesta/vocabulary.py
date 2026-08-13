"""The words a project uses, in a form a person can edit.

An ontology derived by an agent is a good first draft and a bad final answer.
The agent read the code; it did not sit in the meetings. It cannot know that
what the code calls a *posting* the team calls a *leg*, that a whole subsystem
is vestigial, or that the word the domain turns on appears nowhere in any
identifier. So the vocabulary has to be editable, and editing it has to be
cheaper than arguing with a tool about it.

**The grammar already existed.** `derive` parses `kind: label` a line at a time
because that is what an agent can be asked to emit reliably. It happens to be
the same thing a person can type, so it is the edit format too rather than a
second one invented for humans:

    domain: keeping books that balance
    activity: record a transaction
    role: a posting

Anything unrecognised is a comment. That is not laxity — a template wants
headings and prose around its terms, and a format that only tolerates terms
would force every template to be terse and unexplained.

**A vocabulary is yours; a binding must point at real code.** Editing terms is
unconstrained: a term naming nothing in the repository is recorded as naming
nothing, which is `unattached`, and that is information — usually that the code
has not caught up with the language. Attachments get no such freedom, and
`derive` already refuses one pointing at a line no definition occupies. So this
module lets a person write any word they like and lets nobody claim a file does
something it does not.

**Which is also why a template ships vocabulary and never attachments.** A
security template offering `activity: validate an untrusted input` is useful in
any repository. The same template asserting that `auth.py:40` does that would
be a claim about a file it has never seen. Templates supply words; attachment
stays derived from this repository's own code, every time.

**Removing a term removes what was attached to it.** `write_terms` replaces the
ontology and `write_attachments` adds to the map, so an edit that drops a term
would otherwise leave attachments pointing at a word no longer in the
vocabulary — a map asserting a definition does something nothing is called. The
reconciliation happens here, and it is reported rather than silent, because
losing forty attachments to a one-line edit should be something you are told.
"""

from __future__ import annotations

import logging
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from pydantic import BaseModel, Field

logger = logging.getLogger("vesta.vocabulary")

# Where a template's words are kept. One file per template, in the same grammar
# a person edits, so a template is readable as documentation and there is no
# second format to learn.
TEMPLATES = Path(__file__).resolve().parent / "templates"

# What is written above the terms when a person opens them for editing. Kept
# short: a preamble longer than the thing being edited is noise.
PREAMBLE = """\
# The words this project uses. One per line, as `kind: label`.
#
#   domain:   what the project is about
#   activity: something the code does
#   role:     something the code handles
#
# Anything else is a comment. Delete a line to remove the word.
# Save and close to keep the changes; leave it unchanged to keep what is here.
"""


class Edited(BaseModel):
    """What changed when somebody edited the vocabulary."""

    added: List[str] = Field(default_factory=list)
    removed: List[str] = Field(default_factory=list)
    kept: int = 0

    # Attachments dropped because the word they named is gone. Reported, not
    # mentioned in passing: a one-line edit that unbinds forty definitions is
    # something the person doing it should be told about.
    orphaned: int = 0

    # Of those, how many named a word this edit did not remove — attachments
    # that were already naming nothing before anybody typed anything.
    #
    # The distinction matters more than it looks. Merging a template into a
    # live repository dropped 135 attachments while removing no word at all;
    # they had gone stale earlier, because `write_terms` replaces an ontology
    # and nothing reconciled the map. Reporting that as the merge's doing would
    # blame an edit for a fault it found, which is how a tool loses somebody's
    # trust in one sentence.
    stale: int = 0

    @property
    def changed(self) -> bool:
        return bool(self.added or self.removed)

    def describe(self) -> str:
        said = []
        if self.added:
            said.append(f"{len(self.added)} added")
        if self.removed:
            said.append(f"{len(self.removed)} removed")
        line = (
            f"{', '.join(said)}; {self.kept} word(s) now."
            if said
            else f"unchanged — {self.kept} word(s)."
        )

        # What this edit cost, and what it merely found. Two sentences, because
        # they are two different things and one number cannot say both.
        because = self.orphaned - self.stale
        if because:
            # Say it is not undoable. Putting the word back restores the word
            # and not its bindings — attachment is derived from the code by an
            # agent that read it, so it can be rebuilt but not un-deleted, and
            # somebody about to remove forty of them should know which.
            line += (
                f"\n{because} attachment(s) dropped — the words they named "
                "were removed. Putting a word back does not restore them; "
                "the domain agent has to read the code again."
            )
        if self.stale:
            line += (
                f"\n{self.stale} attachment(s) were already naming words this "
                "vocabulary no longer had, and have been cleared."
            )
        return line


def as_text(repo: Path | str, preamble: bool = True) -> str:
    """This repository's vocabulary, in the grammar it is edited in.

    Grouped by kind and ordered within it, so a diff between two edits shows
    what somebody changed rather than what order an agent happened to emit.
    """
    from .domain import recall as recall_ontology

    ontology = recall_ontology(repo)
    terms = list(ontology.terms) if ontology else []

    lines: List[str] = []
    if preamble:
        lines.append(PREAMBLE)

    for kind in ("domain", "activity", "role"):
        wanted = sorted(
            (t for t in terms if t.get("kind", "").lower() == kind),
            key=lambda t: t.get("label", "").lower(),
        )
        if not wanted:
            continue
        lines.append("")
        for term in wanted:
            lines.append(f"{kind}: {term['label']}")

    # Kinds nobody expected, kept rather than dropped: silently discarding a
    # word because its kind was unfamiliar is how an edit loses something.
    other = [
        t for t in terms
        if t.get("kind", "").lower() not in ("domain", "activity", "role")
    ]
    if other:
        lines.append("")
        for term in sorted(other, key=lambda t: t.get("label", "").lower()):
            lines.append(f"{term.get('kind', 'domain')}: {term['label']}")

    return "\n".join(lines).strip() + "\n"


def _orphans(
    repo: Path | str, kept: List[str], was: Optional[set] = None
) -> Tuple[int, int]:
    """Drop attachments whose word is no longer in the vocabulary.

    Returns how many went, and how many of those were already naming nothing
    before this edit — an attachment whose word was absent from the *previous*
    vocabulary too was stale, and clearing it is a repair rather than a cost.
    """
    from .traverse import keep as keep_map
    from .traverse import recall as recall_map

    mapped = recall_map(repo)
    if mapped is None:
        return 0, 0

    alive = {label.strip().lower() for label in kept}
    before = mapped.attachments
    mapped.attachments = [
        a for a in before if a.label.strip().lower() in alive
    ]

    gone = [a for a in before if a.label.strip().lower() not in alive]
    stale = (
        len([a for a in gone if a.label.strip().lower() not in was])
        if was is not None
        else 0
    )

    attached = {a.label.lower() for a in mapped.attachments}
    mapped.unattached = [
        label for label in kept if label.lower() not in attached
    ]

    # Written unconditionally. Guarding this on "did anything change" was a
    # live bug: an edit where every remaining word turned out to be bound
    # computes an empty `unattached`, which is exactly the case the guard
    # skipped — so the previous list survived and the map went on reporting 55
    # words unattached that were no longer in the vocabulary at all. The
    # correct answer being empty is not a reason to keep the wrong one.
    keep_map(mapped, repo)
    return len(gone), stale


def apply(repo: Path | str, text: str) -> Edited:
    """Keep an edited vocabulary, and reconcile the map with it."""
    from .derive import read_terms, write_terms
    from .domain import recall as recall_ontology

    was = recall_ontology(repo)
    before = {t["label"].strip().lower(): t["label"] for t in (was.terms if was else [])}

    terms = read_terms(text)
    now = {t.label.strip().lower(): t.label for t in terms}

    write_terms(repo, text)
    orphaned, stale = _orphans(repo, [t.label for t in terms], was=set(before))

    return Edited(
        added=[now[k] for k in now if k not in before],
        removed=[before[k] for k in before if k not in now],
        kept=len(terms),
        orphaned=orphaned,
        stale=stale,
    )


def _editor() -> List[str]:
    """What to open a file with.

    `$VISUAL` before `$EDITOR` because that is the convention: `$EDITOR` may be
    a line editor for a terminal that cannot do better, and `$VISUAL` is what
    somebody actually wants when the terminal can. `vi` last because it is the
    one editor a POSIX system is required to have.
    """
    for name in ("VISUAL", "EDITOR"):
        said = os.environ.get(name, "").strip()
        if said:
            return said.split()
    return ["vi"]


def edit(repo: Path | str, editor: Optional[List[str]] = None) -> Edited:
    """Open the vocabulary in an editor, and keep whatever comes back.

    A temporary file rather than the stored JSON: the stored form has ids and
    timestamps in it that nobody should be editing by hand, and a person who
    quits without saving should change nothing.
    """
    was = as_text(repo)
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".vesta", delete=False, encoding="utf-8"
    ) as handle:
        handle.write(was)
        path = Path(handle.name)

    try:
        subprocess.run((editor or _editor()) + [str(path)], check=False)
        now = path.read_text(encoding="utf-8", errors="replace")
    except (OSError, subprocess.SubprocessError) as exc:
        logger.warning("could not edit the vocabulary: %s", exc)
        return Edited(kept=len(_labels(was)))
    finally:
        path.unlink(missing_ok=True)

    if now.strip() == was.strip():
        return Edited(kept=len(_labels(was)))
    return apply(repo, now)


def _labels(text: str) -> List[str]:
    from .derive import read_terms

    return [t.label for t in read_terms(text)]


def templates() -> Dict[str, str]:
    """What is shipped, and what each is for.

    The description is the first comment line of the file, so a template
    documents itself in the same file it defines itself in.
    """
    found: Dict[str, str] = {}
    if not TEMPLATES.is_dir():
        return found
    for path in sorted(TEMPLATES.glob("*.md")):
        why = ""
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.startswith("#") and line.strip("# ").strip():
                    why = line.strip("# ").strip()
                    break
        except OSError:
            continue
        found[path.stem] = why
    return found


def read_template(name: str) -> Tuple[str, Optional[str]]:
    """A shipped template's text, or why there is none by that name."""
    path = TEMPLATES / f"{name}.md"
    if not path.is_file():
        known = ", ".join(sorted(templates())) or "none"
        return "", f"no template called {name!r}. There is: {known}"
    try:
        return path.read_text(encoding="utf-8"), None
    except OSError as exc:
        return "", str(exc)


def read_supplied(where: str) -> Tuple[str, Optional[str]]:
    """A vocabulary from a file somebody points at."""
    path = Path(where).expanduser()
    if not path.is_file():
        return "", f"no such file: {where}"
    try:
        return path.read_text(encoding="utf-8", errors="replace"), None
    except OSError as exc:
        return "", str(exc)


def merge(repo: Path | str, text: str) -> Edited:
    """Add a vocabulary's words to this repository's, keeping what is there.

    Merging rather than replacing, because a template is a supplement to what
    reading the code found and not a correction of it. A word already present
    is not added twice, matched case-insensitively on the label — a template
    saying `Record A Transaction` should not produce a second term beside
    `record a transaction`.

    **No attachments, from any source.** The parser only reads terms, so a
    supplied file claiming a binding is ignored rather than refused. That is
    deliberate: the failure it prevents is a template asserting that code it has
    never read does something, and the safe response to such a claim is to not
    hear it.
    """
    from .derive import read_terms

    coming = read_terms(text)
    if not coming:
        return Edited(kept=len(_labels(as_text(repo, preamble=False))))

    have = as_text(repo, preamble=False)
    known = {label.strip().lower() for label in _labels(have)}

    fresh = [t for t in coming if t.label.strip().lower() not in known]
    if not fresh:
        return Edited(kept=len(known))

    together = have.rstrip() + "\n" + "\n".join(
        f"{t.kind}: {t.label}" for t in fresh
    ) + "\n"
    return apply(repo, together)
