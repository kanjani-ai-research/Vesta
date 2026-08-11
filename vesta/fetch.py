"""Retrieving what a search result points at.

A search result is a title, a URL, and forty words. That is a pointer to
theory, not theory, and a corpus built from pointers can only ever answer
questions about which papers exist.

**This was found by an agent, not by a test.** Given a covering-array task, a
real coding agent called `recall`, got back exactly what had been ingested, and
said: *"returns only titles and abstract-level fragments — not the actual
horizontal/vertical growth procedure I asked for."* It then wrote the algorithm
from its own knowledge. The tool had cost it minutes and contributed nothing.
The IPOG paper was in the corpus; its "reading" was 418 bytes of snippet, and
the URL beside it pointed at a fetchable PDF nobody had fetched.

**Relevance is decided here, before ingest.** The same run pulled in a paper
about measuring impact on Twitter, because it used the token "t-factor". Six of
sixteen sources were noise. Ranking cannot fix this after the fact — scores do
not separate an off-topic match from an on-topic one — so a document earns its
place in the corpus or is dropped, and what was dropped is reported rather than
silently omitted.
"""

from __future__ import annotations

import io
import logging
import re
import urllib.error
import urllib.request
from html.parser import HTMLParser
from typing import Dict, List, Optional, Sequence, Set, Tuple

from pydantic import BaseModel, Field

from .acquire import Reading

logger = logging.getLogger("vesta.fetch")

# How long to wait for one document. Longer than a search: a publisher's PDF is
# megabytes and slow, and giving up early is how the best source gets dropped.
TIMEOUT = 45.0

# What is worth keeping. Below the floor a "document" is a cookie banner or an
# access-denied page; above the ceiling it is a book, and the tail of it will
# not survive chunking in a form anyone retrieves.
LEAST_USEFUL = 1500      # characters
MOST_USEFUL = 400_000

# How much of the intent's vocabulary a document must show to be admitted. Set
# by what the failing run needed: the Twitter paper shared one word with the
# subject, the IPOG paper shared most of them.
ENOUGH_OVERLAP = 0.34

# Words that say nothing about a subject, so they cannot be evidence a document
# is about it.
COMMON = {
    "the", "a", "an", "and", "or", "of", "for", "to", "in", "on", "with", "by",
    "that", "this", "it", "its", "is", "are", "be", "as", "at", "from", "into",
    "using", "use", "used", "new", "we", "our", "can", "will", "such", "these",
    "based", "approach", "method", "methods", "paper", "results", "however",
}


class Fetched(BaseModel):
    """A reading with its document, or the reason there is none."""

    reading: Reading
    text: str = ""
    # Why this was not kept. Set for anything dropped, so a build can say what
    # it excluded — an exclusion nobody can see reads as a document that never
    # existed.
    dropped: str = ""

    @property
    def kept(self) -> bool:
        return bool(self.text) and not self.dropped

    def describe(self) -> str:
        if self.dropped:
            return f"✗ {self.reading.title[:56]} — {self.dropped}"
        return f"✓ {self.reading.title[:56]} ({len(self.text):,} chars)"


class _Text(HTMLParser):
    """Body text from HTML, without the furniture."""

    SKIP = {"script", "style", "nav", "header", "footer", "aside", "noscript", "form"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: List[str] = []
        self._skipping = 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self._skipping += 1

    def handle_endtag(self, tag):
        if tag in self.SKIP and self._skipping:
            self._skipping -= 1

    def handle_data(self, data):
        if not self._skipping:
            stripped = data.strip()
            if stripped:
                self.parts.append(stripped)

    def text(self) -> str:
        return _tidy(" ".join(self.parts))


def _tidy(text: str) -> str:
    text = re.sub(r"[ \t\xa0]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _from_pdf(payload: bytes) -> str:
    """Text from a PDF.

    Most of the computer-science literature that matters here is PDF — the NIST
    paper that was the single most relevant source in the failing run is a PDF —
    so skipping them would leave the defect in place for the commonest case.
    """
    try:
        from pypdf import PdfReader
    except ImportError:
        logger.info("pypdf is not installed; PDFs cannot be read")
        return ""

    try:
        reader = PdfReader(io.BytesIO(payload))
        return _tidy("\n".join((page.extract_text() or "") for page in reader.pages))
    except Exception as exc:  # noqa: BLE001 - a malformed PDF is not a crash
        logger.info("could not read a PDF: %s", exc)
        return ""


def document(url: str, timeout: float = TIMEOUT) -> str:
    """The text of whatever is at a URL, or empty if it cannot be had."""
    request = urllib.request.Request(
        url,
        headers={
            # Identified rather than disguised. A publisher that declines a
            # named research tool is entitled to; pretending to be a browser to
            # get around that is not something this should do.
            "User-Agent": "vesta/0.1 (research acquisition; +https://github.com/causum)",
            "Accept": "text/html,application/pdf,text/plain;q=0.9,*/*;q=0.5",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        kind = (response.headers.get("Content-Type") or "").lower()
        payload = response.read(MOST_USEFUL * 4)

    if "pdf" in kind or url.lower().endswith(".pdf") or payload[:5] == b"%PDF-":
        return _from_pdf(payload)
    if "html" in kind or not kind:
        parser = _Text()
        parser.feed(payload.decode("utf-8", errors="replace"))
        return parser.text()
    if "text" in kind:
        return _tidy(payload.decode("utf-8", errors="replace"))
    return ""


def _terms(text: str) -> Set[str]:
    return {
        word
        for word in re.findall(r"[a-z0-9-]{3,}", text.lower())
        if word not in COMMON
    }


def relevance(text: str, subject: str) -> float:
    """How much of the subject's vocabulary a document actually uses.

    Deliberately crude, and computed over the *document* rather than a snippet:
    a paper about covering arrays says "covering", "array", "t-way" and
    "combination" throughout, and a paper about Twitter that happens to contain
    "t-factor" says none of the rest. That difference is visible in the body and
    invisible in forty words of search result.
    """
    wanted = _terms(subject)
    if not wanted:
        return 1.0
    return len(wanted & _terms(text)) / len(wanted)


def gather(
    readings: Sequence[Reading],
    subject: str,
    floor: float = ENOUGH_OVERLAP,
    timeout: float = TIMEOUT,
) -> List[Fetched]:
    """Fetch each reading and decide whether it belongs in the corpus.

    Every outcome is recorded — fetched and kept, fetched and dropped, or never
    fetched and why. A build that quietly ingests ten of sixteen documents looks
    identical to one that found ten.
    """
    gathered: List[Fetched] = []

    for reading in readings:
        found = Fetched(reading=reading)
        try:
            found.text = document(reading.url, timeout)
        except (urllib.error.URLError, OSError, ValueError) as exc:
            found.dropped = f"could not be fetched: {str(exc)[:60]}"
            gathered.append(found)
            continue

        if len(found.text) < LEAST_USEFUL:
            # Too short to be the document: an access page, a paywall, a stub.
            # The abstract is still worth keeping, so the reading survives with
            # what the search gave — but it is marked, because answering a
            # procedure question from an abstract is what failed before.
            found.text = ""
            found.dropped = "no readable body (paywall, stub, or blocked)"
            gathered.append(found)
            continue

        found.text = found.text[:MOST_USEFUL]
        scored = relevance(found.text, subject)
        if scored < floor:
            found.dropped = f"about something else ({scored:.0%} of the subject's terms)"
            found.text = ""
        gathered.append(found)

    return gathered


def summarise(gathered: Sequence[Fetched]) -> str:
    """What was kept and what was not, for a build to report."""
    kept = [f for f in gathered if f.kept]
    dropped = [f for f in gathered if not f.kept]
    lines = [
        f"{len(kept)} of {len(gathered)} document(s) admitted"
        + (f", {len(dropped)} dropped" if dropped else "")
    ]
    for entry in dropped:
        lines.append(f"    {entry.describe()}")
    return "\n".join(lines)
