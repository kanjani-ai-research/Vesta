"""Turning what was found into something that can be asked questions.

A list of search results is not knowledge. It is eight titles and eight
abstracts, and reading them is the work the user was trying to avoid. Pragmatos
already does the part that matters — reading documents under an ontology and
producing facts that can be retrieved with a statement of whether the retrieval
answered — so this writes what acquisition found where Pragmatos can read it,
and asks.

**Readings are written as files because that is what a build takes.** Pragmatos
ingests paths, not payloads. The files are kept rather than discarded after the
build: a corpus whose sources have been deleted cannot be audited, and a
citation pointing at nothing is worse than no citation.

**The corpus is per-intent, not global.** Theory acquired for "deduplicate by
semantic similarity" is not theory about the codebase, and mixing the two would
put paper abstracts in the same corpus as source files where a query for one
returns the other. They are separate corpora over the same ontology.

**A gap is the honest answer and Pragmatos already reports one.** Its search
says whether it actually answered rather than returning a ranked list and
letting the first element imply success. That judgement is passed through
unchanged: where the corpus does not cover a question, the caller is told, and
the theory that was acquired is not made to look more useful than it is.
"""

from __future__ import annotations

import json
import logging
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from pydantic import BaseModel, Field

from .acquire import Found, Reading

logger = logging.getLogger("vesta.structure")

# How long to wait on a build. Reading a dozen abstracts under an ontology is
# model work, and model work is slow; a caller who will not wait should poll the
# job itself rather than have this return a half-built corpus.
BUILD_TIMEOUT = 600.0
POLL_EVERY = 3.0

# How long to wait on anything else. Reads are cheap and a slow one is a fault.
TIMEOUT = 30.0


class Structured(BaseModel):
    """A corpus built from what was acquired, and what it cost to build."""

    corpus_id: str
    wrote: List[str] = Field(default_factory=list)
    # What the build could not do. A corpus built from six of eight readings is
    # usable and is not the corpus the caller asked for.
    incomplete: str = ""
    took: float = 0.0

    @property
    def is_whole(self) -> bool:
        return not self.incomplete

    def describe(self) -> str:
        said = f"{self.corpus_id}: {len(self.wrote)} reading(s) in {self.took:.0f}s"
        return f"{said} — {self.incomplete}" if self.incomplete else said


class Answer(BaseModel):
    """What the corpus said, and whether it actually answered.

    The second part is the one that matters. Pragmatos assesses its own coverage
    and that assessment is carried through rather than being replaced by the
    presence of results, because a ranked list always has a first element.
    """

    query: str
    results: List[Dict[str, Any]] = Field(default_factory=list)
    coverage: Dict[str, Any] = Field(default_factory=dict)

    @property
    def answered(self) -> bool:
        """Whether the corpus covered the question, as the corpus judges it."""
        return self.coverage.get("gap") is None and bool(self.results)

    def describe(self) -> str:
        if not self.answered:
            return f"{len(self.results)} result(s), but the corpus does not cover this"
        return f"{len(self.results)} result(s)"


def _slug(text: str) -> str:
    kept = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return kept[:48] or "intent"


def write(found: Found, into: Path | str, query: str = "") -> List[Path]:
    """Put readings on disk in a form a document pipeline can read.

    One file per reading, with the provenance in the file rather than only in
    the filename: a corpus is read by something that will not have this object,
    and a fact whose source cannot be named is a fact nobody can check.
    """
    into = Path(into)
    into.mkdir(parents=True, exist_ok=True)
    written: List[Path] = []

    for index, reading in enumerate(found.readings):
        path = into / f"{index:03d}-{_slug(reading.title)}.md"
        body = [
            f"# {reading.title}",
            "",
            f"Source: {reading.source}",
            f"URL: {reading.url}",
        ]
        if reading.published:
            body.append(f"Published: {reading.published}")
        if reading.authors:
            body.append(f"Authors: {', '.join(reading.authors)}")
        body.extend(["", reading.summary or "(no summary was supplied)", ""])
        path.write_text("\n".join(body), encoding="utf-8")
        written.append(path)

    # What was searched and what was not, kept beside the readings. A corpus
    # built from two of three sources reads exactly like one built from three
    # unless the difference is written down.
    if query or found.reach.skipped:
        (into / "_reach.md").write_text(
            "\n".join(
                [
                    f"# How this was found",
                    "",
                    f"Query: {found.reach.query or query}",
                    f"Asked: {', '.join(found.reach.asked) or 'nothing'}",
                    *[
                        f"Not asked — {name}: {why}"
                        for name, why in sorted(found.reach.skipped.items())
                    ],
                    "",
                ]
            ),
            encoding="utf-8",
        )

    return written


class Pragmatos:
    """The reading side of the product, over HTTP.

    Thin on purpose. Pragmatos owns the ontology, the extraction and the
    coverage judgement; duplicating any of that here would produce a second
    implementation that drifts from the first.
    """

    def __init__(self, base_url: str = "http://localhost:8000") -> None:
        self.base_url = base_url.rstrip("/")

    def _call(
        self, path: str, payload: Optional[Dict[str, Any]] = None, method: str = "GET"
    ) -> Dict[str, Any]:
        url = f"{self.base_url}{path}"
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = urllib.request.Request(
            url,
            data=data,
            method=method,
            headers={"Content-Type": "application/json"} if data else {},
        )
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            return json.loads(response.read() or b"{}")

    @property
    def is_available(self) -> bool:
        try:
            return self._call("/health").get("status") == "ok"
        except (urllib.error.URLError, OSError, ValueError):
            return False

    def ontologies(self) -> List[Dict[str, Any]]:
        found = self._call("/ontologies")
        return found if isinstance(found, list) else found.get("ontologies", [])

    def build(
        self,
        corpus_id: str,
        paths: Sequence[Path | str],
        ontology: Optional[str] = None,
        wait: float = BUILD_TIMEOUT,
    ) -> Dict[str, Any]:
        """Ingest documents and wait for the job.

        Waiting rather than returning a job id, because the caller's next act is
        always to query the corpus and a corpus that is still building answers
        wrongly rather than not at all.
        """
        job = self._call(
            "/build",
            {
                "corpus_id": corpus_id,
                "paths": [str(p) for p in paths],
                **({"ontology": ontology} if ontology else {}),
            },
            method="POST",
        )
        job_id = job.get("id", "")
        deadline = time.monotonic() + wait

        while job.get("state") == "running" and time.monotonic() < deadline:
            time.sleep(POLL_EVERY)
            job = self._call(f"/jobs/{job_id}")
            logger.debug("build %s: %s %.0f%%", job_id, job.get("stage"), job.get("progress", 0) * 100)

        return job

    def ask(self, corpus_id: str, query: str, limit: int = 10) -> Answer:
        """Query a corpus, keeping its own judgement of whether it answered."""
        payload = self._call(
            f"/corpora/{corpus_id}/search", {"query": query, "limit": limit}, method="POST"
        )
        return Answer(
            query=query,
            results=payload.get("results", []),
            coverage=payload.get("coverage", {}),
        )


def structure(
    found: Found,
    intent: str,
    into: Path | str,
    pragmatos: Optional[Pragmatos] = None,
    ontology: Optional[str] = None,
) -> Structured:
    """Write what was found and build a corpus over it.

    Degrades honestly at every step: with nothing found there is no corpus, with
    Pragmatos unreachable the readings are still on disk and still readable by a
    person. Neither case is reported as success.
    """
    started = time.time()
    corpus_id = f"theory-{_slug(intent)}"
    written = write(found, into, query=intent)
    result = Structured(corpus_id=corpus_id, wrote=[str(p) for p in written])

    if not written:
        result.incomplete = "nothing was found to structure"
        result.took = time.time() - started
        return result

    client = pragmatos or Pragmatos()
    if not client.is_available:
        # The readings are on disk and a person can read them. Saying the corpus
        # exists when it does not would be the one unrecoverable error here.
        result.incomplete = (
            f"Pragmatos was not reachable at {client.base_url}; the readings were "
            "written but no corpus was built"
        )
        result.took = time.time() - started
        return result

    try:
        job = client.build(corpus_id, [into], ontology=ontology)
    except (urllib.error.URLError, OSError, ValueError) as exc:
        result.incomplete = f"the build could not be started: {exc}"
        result.took = time.time() - started
        return result

    if job.get("state") != "complete":
        result.incomplete = (
            f"the build did not finish: {job.get('error') or job.get('state')}"
        )

    result.took = time.time() - started
    return result
