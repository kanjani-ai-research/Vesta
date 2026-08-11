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
        """Whether the corpus covered the question.

        Pragmatos' own judgement, unchanged. An earlier version also required a
        matched fact, on the strength of "how should I price a used car" coming
        back answered against a corpus of description-logic papers. That rule
        was wrong: `matched_facts` is empty for good retrievals too, so it
        rejected questions the corpus answers well — it happened to suppress the
        bad case and suppressed the good ones with it.

        **The separation this needs is not available here.** Off-topic questions
        do floor out (a pizza query scores 0.7 against 1.4), but a used-car
        question still matches "whether an ontology can safely be replaced by
        another" on surface similarity alone. Rather than tune a threshold that
        would silently drop real answers, the caller is given the retrieval and
        its scores and left to judge — which is what `Consultation` reports.
        """
        return self.coverage.get("gap") is None and bool(self.results)

    def describe(self) -> str:
        if not self.answered:
            return f"{len(self.results)} result(s), but the corpus does not cover this"
        return f"{len(self.results)} result(s)"


# Who built a corpus, carried in its id.
#
# A corpus this machine acquired for itself and one obtained from a publisher
# are different evidence about the same subject: the first is whatever the web
# returned that day, the second is something somebody put their name to. They
# must not share a name, or a user cannot tell which one answered — and an id
# is the thing that ends up in filenames, configs, and bug reports, so it is
# the wrong place to be ambiguous.
#
# Local is the default and needs no infrastructure. The published namespace is
# reserved now, while it costs nothing, rather than retrofitted onto ids that
# are already written down.
LOCAL = "local"
PUBLISHED = "pub"

# Where corpora live when nothing says otherwise.
#
# Pragmatos defaults to `/var/lib/pragmatos`, which is right for a service
# deployed to a host and wrong for a tool a developer runs: it is not writable,
# and the failure is a PermissionError from inside a build rather than anything
# a user can act on. A tool that works only if you happen to have exported an
# environment variable is not finished.
VESTA_HOME = Path.home() / ".vesta"

# Where acquired readings are written. Absolute, and beside the corpora built
# from them: theory is about a subject, not about the directory a command was
# run from, and a relative default put the two halves of one run in different
# places.
THEORY_DIR = VESTA_HOME / "theory"


def _ensure_data_dir() -> Path:
    """Point Pragmatos somewhere writable, unless the user has chosen.

    `setdefault`, so an explicit `PRAGMATOS_DATA_DIR` always wins — a user who
    has said where their corpora go has said it for a reason, and a deployment
    sharing a corpus between components depends on that choice being honoured.
    """
    import os

    chosen = os.environ.get("PRAGMATOS_DATA_DIR")
    if chosen:
        return Path(chosen).expanduser()
    home = VESTA_HOME / "data"
    home.mkdir(parents=True, exist_ok=True)
    os.environ["PRAGMATOS_DATA_DIR"] = str(home)
    return home


def _slug(text: str) -> str:
    kept = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return kept[:48] or "intent"


def repository(start: Optional[Path | str] = None) -> Path:
    """The project under analysis: the working directory, as the user set it.

    **No detection, deliberately.** Two earlier attempts guessed — first by
    shelling out to `git rev-parse`, then by walking up for a list of project
    markers — and both were wrong in the same way. A marker list can never cover
    every language, and a miss does not raise: it silently resolves to whichever
    subdirectory the user happened to be in, so `src/parser` and `src/lexer`
    become two knowledge bases for one project. The tool looks like it is
    working while quietly fragmenting the thing it exists to accumulate.

    The working directory is a decision the user already made, and every host
    that runs this as a sidecar sets it. Honouring it exactly means the answer
    is always explicable — change project by changing directory — and there is
    no heuristic to be wrong.
    """
    where = Path(start).expanduser().resolve() if start else Path.cwd().resolve()
    return where if where.is_dir() else where.parent


def repository_name(start: Optional[Path | str] = None) -> str:
    """A short, stable name for a repository.

    The directory name carries meaning to a person; the hash of the full path
    keeps two checkouts of the same project apart. Both, because a name nobody
    recognises is unusable and a name that collides is wrong.
    """
    import hashlib

    root = repository(start)
    fingerprint = hashlib.sha256(str(root).encode("utf-8")).hexdigest()[:8]
    return f"{_slug(root.name)}-{fingerprint}"


def corpus_id(
    repo: Optional[Path | str] = None, origin: str = LOCAL, publisher: str = ""
) -> str:
    """The id of the knowledge base for a repository.

    **One repository, one knowledge base.** Pragmatos creates a KB each time it
    builds, and keying those by *task* would give one repository a scatter of
    single-purpose corpora that never accumulate — theory acquired for one piece
    of work would be invisible to the next, which is the opposite of the point.
    Keying by repository means a project's knowledge grows as it is worked on.

    Two repositories must not share one, either: theory acquired for a compiler
    is not evidence about a payments service, and a query that reaches across
    projects retrieves on surface similarity alone.

    One definition, used by both the building side and the consulting side, so
    the two agree by construction: a name computed in two places is a name that
    eventually differs.
    """
    subject = repository_name(repo)
    if origin == PUBLISHED:
        return f"theory.{PUBLISHED}.{_slug(publisher) if publisher else 'unattributed'}.{subject}"
    return f"theory.{LOCAL}.{subject}"


def origin_of(identifier: str) -> str:
    """Where a corpus came from, read back from its id."""
    parts = identifier.split(".")
    return parts[1] if len(parts) > 2 and parts[0] == "theory" else LOCAL


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
        # Written outside the tree that gets ingested. It is provenance about
        # the search, not material about the subject, and a live build made it
        # the top hit for "how do I check an extension is conservative" — the
        # corpus citing its own bookkeeping back at the reader.
        (into.parent / f"{into.name}-reach.md").write_text(
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

    def corpora(self) -> List[str]:
        found = self._call("/corpora")
        listed = found if isinstance(found, list) else found.get("corpora", [])
        return [c["id"] if isinstance(c, dict) else str(c) for c in listed]

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


class Local:
    """Pragmatos as a library rather than a service.

    A corpus is a SQLite file — facts, chunks and embeddings as float32 blobs in
    one database, with no separate index to keep in step. The service is a
    transport over that file, so building through it is a choice rather than a
    requirement, and requiring it would make a corpus depend on a process being
    up when it only depends on a path being writable.

    Preferred where Pragmatos is importable. The HTTP client stays for the case
    it exists to serve: a corpus somebody else's machine owns.
    """

    def __init__(self, base_url: str = "local") -> None:
        self.base_url = base_url
        # Built once and held. The encoder loads weights from disk, and building
        # it per question turned every consultation into a model load.
        self._embed: Any = None
        self._embed_tried = False

    def _embedder(self):
        if not self._embed_tried:
            from pragmatos import llm

            self._embed_tried = True
            self._embed = llm.build_embedder()
        return self._embed

    @property
    def is_available(self) -> bool:
        """Whether a corpus can be *built* here.

        Building is model work, so it needs credentials: without them the build
        would start and fail partway, which is worse than declining to start.
        Reading needs none of that — see `can_read`, which is the gate for
        consulting an existing corpus.
        """
        if not self.can_read:
            return False
        from pragmatos.config import config

        return not config.missing_credentials()

    @property
    def can_read(self) -> bool:
        """Whether an existing corpus can be queried.

        A separate question from `is_available`, and a much weaker one: a corpus
        is a SQLite file, and reading it needs no API key at all. Conflating the
        two made consulting already-acquired theory report "no corpus backend"
        on a machine holding a perfectly good corpus — which would send the
        system back to the web to buy knowledge it already had.
        """
        try:
            import pragmatos.retrieval  # noqa: F401
        except ImportError:
            return False
        _ensure_data_dir()
        return True

    def why_not(self) -> str:
        try:
            import pragmatos.pipeline  # noqa: F401
        except ImportError:
            return "pragmatos is not installed"
        from pragmatos.config import config

        missing = config.missing_credentials()
        return f"missing credentials: {', '.join(missing)}" if missing else ""

    def build(
        self,
        corpus_id: str,
        paths: Sequence[Path | str],
        ontology: Optional[str] = None,
        wait: float = BUILD_TIMEOUT,
    ) -> Dict[str, Any]:
        import asyncio

        _ensure_data_dir()
        from pragmatos import llm, pipeline
        from pragmatos.config import config
        from pragmatos.store import Store

        sources = pipeline.read_sources([Path(p) for p in paths])
        if not sources:
            return {"state": "failed", "id": corpus_id, "error": "no readable text at those paths"}

        embed = llm.build_embedder()
        builder = pipeline.Builder(
            Store(config.database),
            llm.build_extractor(),
            embed,
        )

        async def run():
            if ontology:
                return await builder.build(
                    corpus_id, sources, pipeline.load_ontology(ontology)
                )
            # Without an ontology the documents are characterised first and one
            # is derived from them. That is Metis' job, and it is a hard
            # dependency rather than a fallback: a corpus built under no
            # ontology at all would have nothing to label chunks with.
            from metis.pipelines import analyze_async

            return await builder.build_with_discovery(
                corpus_id, sources, analyze_async
            )

        try:
            report = asyncio.run(run())
        except ImportError as exc:
            # Name the module that is actually missing rather than assuming it
            # is the one this code imports. Several of the family's packages are
            # installed by path (`kanon` collides with an unrelated name on
            # PyPI, `stroma` is local), so an ImportError raised deep inside a
            # build is usually about one of those — and reporting it as "needs
            # metis" sends a user to install something they already have.
            missing = getattr(exc, "name", "") or str(exc)
            return {
                "state": "failed",
                "id": corpus_id,
                "error": (
                    f"a package the build needs is not installed: {missing} "
                    f"(some are path-installed: pip install -e ../deps/{missing})"
                ),
            }
        return {
            "state": "complete",
            "id": corpus_id,
            "result": report.model_dump(mode="json"),
            # Pragmatos returns no embedder when `sentence-transformers` is
            # absent and falls back to lexical retrieval — a deliberate optional
            # on its side. It is still a bound on the corpus: a query phrased
            # unlike the text will not match, and a build reported as whole
            # while its vectors are missing is the failure this project exists
            # to avoid.
            "partial": (
                ""
                if embed
                else "no embeddings were written (sentence-transformers is not "
                "installed); retrieval is lexical only"
            ),
        }

    def corpora(self) -> List[str]:
        """Every corpus in the store on this machine."""
        _ensure_data_dir()
        from pragmatos.config import config
        from pragmatos.store import Store

        return [c.id for c in Store(config.database).list_corpora()]

    def ask(self, corpus_id: str, query: str, limit: int = 10) -> Answer:
        _ensure_data_dir()
        from pragmatos import gaps as gaps_module
        from pragmatos import llm
        from pragmatos.config import config
        from pragmatos.retrieval import Retriever
        from pragmatos.store import Store

        store = Store(config.database)
        # Embed the question so the vectors in the corpus are actually used.
        # Without this the retriever falls back to lexical alone — which was
        # written, measured, and silently unused: a corpus with 17 embeddings
        # answered every query `how='lexical'`, and a question about pricing a
        # used car outscored a real one because "how/should/I" are common words.
        query_vector = None
        embed = self._embedder()
        if embed is not None:
            try:
                query_vector = list(embed([query])[0])
            except Exception as exc:  # noqa: BLE001 - lexical still works
                logger.warning("could not embed the query: %s", exc)

        results = Retriever(store, corpus_id).search(
            query, limit=limit, query_vector=query_vector
        )
        coverage = gaps_module.assess(corpus_id, query, results, None)
        return Answer(
            query=query,
            results=[r.model_dump(mode="json") for r in results],
            coverage=coverage.model_dump(mode="json"),
        )


def best_backend(base_url: str = "http://localhost:8000", for_reading: bool = False) -> Any:
    """Whichever way into Pragmatos is actually open.

    The library first, because a corpus is a file and a file needs no service.
    `for_reading` asks the weaker question — reading a corpus needs no model
    credentials, and requiring them would send a caller to HTTP (or to nothing)
    for a database sitting on the same disk.
    """
    local = Local()
    if local.can_read if for_reading else local.is_available:
        return local
    return Pragmatos(base_url)


def structure(
    found: Found,
    intent: str,
    into: Path | str,
    pragmatos: Optional[Any] = None,
    ontology: Optional[str] = None,
    repo: Optional[Path | str] = None,
) -> Structured:
    """Write what was found and build a corpus over it.

    Degrades honestly at every step: with nothing found there is no corpus, with
    Pragmatos unreachable the readings are still on disk and still readable by a
    person. Neither case is reported as success.
    """
    started = time.time()
    # Keyed by repository, not by intent: one project, one knowledge base that
    # accumulates. Acquired here, so it carries the local origin — nothing this
    # machine scraped may claim to be published.
    identifier = corpus_id(repo)
    written = write(found, into, query=intent)
    result = Structured(corpus_id=identifier, wrote=[str(p) for p in written])

    if not written:
        result.incomplete = "nothing was found to structure"
        result.took = time.time() - started
        return result

    client = pragmatos or best_backend()
    if not client.is_available:
        # The readings are on disk and a person can read them. Saying the corpus
        # exists when it does not would be the one unrecoverable error here.
        #
        # Why it could not be built is named as precisely as the backend knows:
        # a missing API key and an unreachable host are different problems, and
        # reporting both as "not reachable" sends a user to restart a service
        # that was never the cause.
        why = getattr(client, "why_not", None)
        why = why() if callable(why) else None
        result.incomplete = (
            f"no corpus was built ({why}); the readings were written"
            if why
            else f"Pragmatos was not reachable at {client.base_url}; the readings "
            "were written but no corpus was built"
        )
        result.took = time.time() - started
        return result

    try:
        job = client.build(identifier, [into], ontology=ontology)
    except (urllib.error.URLError, OSError, ValueError) as exc:
        result.incomplete = f"the build could not be started: {exc}"
        result.took = time.time() - started
        return result

    if job.get("state") != "complete":
        result.incomplete = (
            f"the build did not finish: {job.get('error') or job.get('state')}"
        )
    elif job.get("partial"):
        # Built, and not built the way it was asked for. Reported through the
        # same field, because a caller checking `is_whole` should see both.
        result.incomplete = job["partial"]

    result.took = time.time() - started
    return result
