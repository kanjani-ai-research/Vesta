"""Asking what has already been learned, before learning it again.

Acquisition writes corpora; this reads them. Without it the loop is open — the
system goes out and looks every time, and theory acquired last week is a folder
of markdown nobody opens. With it, "what do I need to know to build this" is
answered from what was already read, and the web is a fallback rather than the
first move.

**What comes back is evidence, not instruction.** The same rule that governs
`maturity`: a corpus that has read eight papers about conservative extensions
knows more about the literature than about *this* build, and a system that turns
a retrieved fact into a directive is the failure mode that motivated the whole
design. Findings are cited and attributed so a reader can weigh them.

**Silence is reported as silence.** A corpus that does not cover a question says
so — Pragmatos assesses its own coverage and that assessment is carried through.
The cheap error is going out to search when the answer was already held; the
expensive one is answering from a corpus that has nothing to say.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional, Sequence

from pydantic import BaseModel, Field

from .structure import LOCAL, PUBLISHED, Answer, adopt, best_backend, corpus_id, origin_of

logger = logging.getLogger("vesta.consult")

# How many passages to take from a corpus for one question. Enough to show
# more than one source's view, few enough that a person reads all of them.
PASSAGES = 5


class Citation(BaseModel):
    """One thing the corpus said, and where it came from."""

    text: str
    source: str = ""
    fact: str = ""
    score: float = 0.0

    def describe(self) -> str:
        where = f" [{self.source}]" if self.source else ""
        return f"{self.text[:200]}{where}"


class Consultation(BaseModel):
    """What was already known about a question, and what was not."""

    question: str
    corpus_id: str
    cites: List[Citation] = Field(default_factory=list)
    # Set where the corpus could not be asked at all, as distinct from a corpus
    # that was asked and had nothing. The first is a fault; the second is an
    # answer, and conflating them is how a system comes to search the web
    # because a database file was missing.
    unavailable: str = ""

    @property
    def knew(self) -> bool:
        return bool(self.cites) and not self.unavailable

    @property
    def best(self) -> float:
        return max((c.score for c in self.cites), default=0.0)

    def describe(self) -> str:
        if self.unavailable:
            return f"could not consult {self.corpus_id}: {self.unavailable}"
        if not self.cites:
            return f"{self.corpus_id} has nothing on this"
        # The score is shown rather than thresholded. A weak match and a strong
        # one are both retrievals, and which is which is a judgement the reader
        # is better placed to make than a constant in this file — an off-topic
        # question can still match a passage on surface similarity alone.
        return (
            f"{len(self.cites)} passage(s) from {self.corpus_id} "
            f"(best {self.best:.2f})"
        )


def corpus_for(repo=None, origin: str = LOCAL, publisher: str = "") -> str:
    """The id of the knowledge base for a repository.

    Delegates to the one definition in `structure` rather than rebuilding the
    string here: consulting and building must agree, and two implementations of
    a naming rule agree only until one of them changes.
    """
    return corpus_id(repo, origin=origin, publisher=publisher)


def _cite(result: Dict[str, Any]) -> Citation:
    return Citation(
        text=" ".join(str(result.get("text") or result.get("canonical") or "").split()),
        source=str(result.get("source_id") or result.get("locator") or ""),
        fact=str(result.get("fact_id") or ""),
        score=float(result.get("score") or 0.0),
    )


def consult(
    question: str,
    intent: str = "",
    corpus_id: str = "",
    pragmatos: Optional[Any] = None,
    limit: int = PASSAGES,
    repo: Optional[Any] = None,
) -> Consultation:
    """Ask a corpus a question, and say plainly when it has no answer."""
    if not corpus_id:
        # A knowledge base built before corpora were keyed by repository is not
        # wrong, it is unreachable. Claiming it costs a rename; the alternative
        # is telling a user their theory is gone and charging them to re-acquire
        # it. Only acts when this repository has none and exactly one orphan
        # exists — see `adopt`.
        adopted = adopt(repo)
        if adopted:
            logger.info("adopted the knowledge base %s for this repository", adopted)
    corpus = corpus_id or corpus_for(repo)
    found = Consultation(question=question, corpus_id=corpus)

    client = pragmatos or best_backend(for_reading=True)
    # `can_read`, not `is_available`: reading a corpus is SQLite, and a machine
    # with no model credentials can still answer from theory it already holds.
    readable = getattr(client, "can_read", None)
    if not (readable if readable is not None else getattr(client, "is_available", False)):
        why = getattr(client, "why_not", None)
        found.unavailable = (why() if callable(why) else "") or "no corpus backend"
        return found

    try:
        answer: Answer = client.ask(corpus, question, limit=limit)
    except Exception as exc:  # noqa: BLE001 - an unreachable corpus is not an answer
        logger.warning("could not consult %s: %s", corpus, exc)
        found.unavailable = str(exc)[:160]
        return found

    # `answered` is the corpus' own judgement, tightened by Vesta to require a
    # matched fact. A retrieval it does not stand behind is not carried, because
    # passing it on would launder lexical noise into knowledge.
    if not answer.answered:
        return found

    found.cites = [_cite(r) for r in answer.results][:limit]
    return found


def corpora(pragmatos: Optional[Any] = None) -> List[str]:
    """Every corpus on this machine, newest-looking first.

    Needed because an agent mid-task has a question, not a corpus name. Making
    the caller know the id before asking is the difference between a tool an
    agent can use and one it must be configured for.
    """
    client = pragmatos or best_backend(for_reading=True)
    lister = getattr(client, "corpora", None)
    if lister is None:
        return []
    try:
        return list(lister())
    except Exception as exc:  # noqa: BLE001 - no corpora is not a failure
        logger.warning("could not list corpora: %s", exc)
        return []


def here(
    question: str,
    repo: Optional[Any] = None,
    pragmatos: Optional[Any] = None,
    limit: int = PASSAGES,
) -> Consultation:
    """Ask this repository's knowledge base.

    One repository, one knowledge base — so there is no search across corpora to
    do. An earlier version asked every corpus on the machine and kept the best
    score, which reached into unrelated projects: theory acquired for a compiler
    is not evidence about a payments service, and a cross-project match is
    surface similarity by definition.

    Where this repository has no knowledge base yet, that is said plainly. It is
    the signal to acquire, not a reason to answer from somebody else's work.
    """
    client = pragmatos or best_backend(for_reading=True)
    corpus = corpus_for(repo)

    if corpus not in corpora(client):
        found = Consultation(question=question, corpus_id=corpus)
        found.unavailable = (
            "this repository has no knowledge base yet; `learn` would build one"
        )
        return found

    return consult(question, corpus_id=corpus, pragmatos=client, limit=limit)


def known(
    questions: Sequence[str],
    intent: str = "",
    corpus_id: str = "",
    pragmatos: Optional[Any] = None,
) -> List[Consultation]:
    """Several questions against one corpus, sharing the backend.

    A backend resolved once rather than per question: `best_backend` imports
    Pragmatos and checks credentials, which is not free and does not change
    between two questions asked a second apart.
    """
    client = pragmatos or best_backend(for_reading=True)
    return [consult(q, intent, corpus_id, client) for q in questions]
