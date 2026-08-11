"""Going out to look for the theory a build needs.

Only runs where a user has supplied a key. That gate is not only about cost: a
user who configures a search has decided the system may go out and look, and a
system that decided this for itself would be spending someone else's money on
its own judgement about what it does not know.

**Sources are uneven and the unevenness is recorded, not smoothed over.** arXiv
covers machine learning well and programming languages and distributed systems
badly. Much of what matters is in books, in paywalled proceedings, or in blog
posts nobody indexed. A result set is therefore a *sample of what is reachable*,
never an extent, and every `Reading` says which source found it so a reader can
discount accordingly. Reporting "nothing found" as though the literature were
empty is the failure this is built to avoid.

**Nothing found is not evidence.** It is evidence the query was wrong or the
field is not indexed. `Search.for_` returns an empty list and the caller in
`maturity` reads it as UNDETERMINED, never as novelty.

**Results are not read here.** This retrieves and attributes; deciding what a
result *means* about a build is `maturity`'s job, and keeping the two apart is
what lets the judgement be checked against the evidence that produced it.
"""

from __future__ import annotations

import json
import logging
import os
import re
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from typing import Callable, Dict, List, Optional, Sequence

from pydantic import BaseModel, Field

logger = logging.getLogger("vesta.acquire")

# Where a reading came from. Named rather than merged because the sources have
# different failure modes and a reader weighing evidence needs to know which one
# is talking.
ARXIV = "arxiv"        # preprints; strong on ML, weak on PL and systems
WEB = "web"            # blogs, docs, standards; high signal, no quality floor
REPOSITORY = "repo"    # theory applied; evidence of practice, not of claims
SOURCES = (ARXIV, WEB, REPOSITORY)

# How long to wait on any one source. A search that hangs is worse than one
# that fails: the caller is blocked and learns nothing.
TIMEOUT = 20.0

# What a single source may return. Beyond this, more results stop adding
# perspectives and start adding near-duplicates of the first few.
PER_SOURCE = 8

# The environment variable a user sets to turn web search on. Named here so the
# gate is one thing in one place rather than a check repeated at call sites.
BRAVE_KEY = "BRAVE_API_KEY"

# How far up to look for the shared `.env`. The components sit one level below
# it; a few more allows for being run from a subdirectory.
_ENV_CEILING = 4

# arXiv asks for a pause between requests and enforces it with 429s and stalled
# connections. Several queries in a run is enough to trip it — which then reads
# as "arXiv has nothing", the one conclusion this must never draw by accident.
ARXIV_DELAY = 3.0
_last_arxiv = [0.0]


def _arxiv_get(url: str) -> bytes:
    """Fetch from arXiv over TLS, keeping to the interval it asks for.

    **TLS is not optional here.** Plain `http://export.arxiv.org` answers with a
    redirect that then stalls until the socket times out — which looks exactly
    like rate limiting, and cost this an afternoon of blaming arXiv for
    throttling it. The same request over `https://` returns in under a second.
    """
    import time

    waited = time.monotonic() - _last_arxiv[0]
    if _last_arxiv[0] and waited < ARXIV_DELAY:
        time.sleep(ARXIV_DELAY - waited)
    try:
        return _get(url, {"User-Agent": "vesta/0.1 (research acquisition)"})
    finally:
        _last_arxiv[0] = time.monotonic()


def _load_env(start: Optional[str] = None, override: bool = False) -> None:
    """Fill the environment from the nearest `.env`.

    Parsed here rather than taken from a library: this is the only thing Vesta
    needs from one.

    **`override` exists because ambient credentials are a real hazard.** The
    default is to let an already-set variable win, which is right for a variable
    a user exported deliberately. But a shell can carry an unrelated
    `ANTHROPIC_API_KEY` from some other project, and then the project's own
    `.env` is silently ignored and the model reports "API key is invalid" about
    a key the user never chose to use. A caller that knows the project's file is
    authoritative passes `override=True`.
    """
    from pathlib import Path

    # Where to look, in order of authority:
    #   1. an explicit VESTA_ENV_FILE, for a user who has decided
    #   2. upward from cwd, which finds a project's own file when run inside it
    #   3. upward from this package, which finds it when run from anywhere else
    #
    # The third matters most for the sidecar: an MCP server's working directory
    # is whatever the host chose, usually the repository being edited, so the
    # cwd walk finds nothing and every model call fails on a missing key.
    explicit = os.environ.get("VESTA_ENV_FILE")
    if explicit:
        candidate = Path(explicit).expanduser()
        if candidate.is_file():
            _read_env(candidate, override)
            return

    roots = [Path(start).resolve()] if start else [
        Path(os.getcwd()).resolve(),
        Path(__file__).resolve().parent,
    ]
    for origin in roots:
        if _walk_up(origin, override):
            return


def _walk_up(origin, override: bool) -> bool:
    from pathlib import Path

    for directory in [origin, *origin.parents][:_ENV_CEILING]:
        candidate = directory / ".env"
        if candidate.is_file():
            _read_env(candidate, override)
            return True
    return False


def _read_env(path, override: bool) -> None:
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            name, _, value = line.partition("=")
            name, value = name.strip(), value.strip().strip("\"'")
            if not value:
                continue
            if override:
                os.environ[name] = value
            else:
                os.environ.setdefault(name, value)
    except OSError:
        pass


class Reading(BaseModel):
    """One thing found, with enough provenance to be discounted."""

    title: str
    url: str
    source: str
    summary: str = ""
    # Where the source supplies one. Absent is common — a blog post has no
    # citation count — and absence is not zero.
    published: str = ""
    authors: List[str] = Field(default_factory=list)

    def describe(self) -> str:
        when = f", {self.published}" if self.published else ""
        return f"[{self.source}] {self.title}{when}"


class Reach(BaseModel):
    """What could and could not be searched, for one query.

    Carried alongside results because the two together are the finding: eleven
    results from arXiv alone, with the web unreachable, is a different piece of
    evidence than eleven results from everywhere.
    """

    query: str
    asked: List[str] = Field(default_factory=list)
    # Sources that were not asked, and why. A source skipped for want of a key
    # and a source that errored are different situations for a user.
    skipped: Dict[str, str] = Field(default_factory=dict)

    @property
    def is_complete(self) -> bool:
        return not self.skipped

    def describe(self) -> str:
        parts = [f"asked {', '.join(self.asked) or 'nothing'}"]
        for name, why in sorted(self.skipped.items()):
            parts.append(f"{name} skipped ({why})")
        return "; ".join(parts)


class Found(BaseModel):
    """Readings for a query, and the bound on them."""

    readings: List[Reading] = Field(default_factory=list)
    reach: Reach

    def __len__(self) -> int:
        return len(self.readings)

    def __iter__(self):  # type: ignore[override]
        return iter(self.readings)

    def __bool__(self) -> bool:
        return bool(self.readings)

    def by_source(self) -> Dict[str, List[Reading]]:
        out: Dict[str, List[Reading]] = {}
        for reading in self.readings:
            out.setdefault(reading.source, []).append(reading)
        return out

    def describe(self) -> str:
        counts = ", ".join(
            f"{len(v)} from {k}" for k, v in sorted(self.by_source().items())
        )
        return f"{len(self.readings)} reading(s)" + (f" ({counts})" if counts else "")


# ── Sources ──────────────────────────────────────────────────────────────


def _get(url: str, headers: Optional[Dict[str, str]] = None) -> bytes:
    request = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        return response.read()


def from_arxiv(query: str, limit: int = PER_SOURCE) -> List[Reading]:
    """Preprints. No key needed, which is why it is the floor rather than the
    ceiling: it is free, and it is missing most of programming languages,
    databases, and distributed systems.

    Restricted to the computer science categories. Unrestricted, `all:` matches
    every field arXiv holds, and a first live run on "covering array generation"
    returned five radio-telescope papers out of eight — "array" is a word
    astrophysics uses more than computer science does. A source that answers
    confidently from the wrong field is worse than one that answers nothing.
    """
    url = "https://export.arxiv.org/api/query?" + urllib.parse.urlencode(
        {
            "search_query": f"abs:({query}) AND cat:cs.*",
            "start": 0,
            "max_results": limit,
            "sortBy": "relevance",
        }
    )
    return _parse_arxiv(_arxiv_get(url))


def _parse_arxiv(payload: bytes) -> List[Reading]:
    """One Atom reader for both the query and the follow paths."""
    root = ET.fromstring(payload)
    space = "{http://www.w3.org/2005/Atom}"
    readings: List[Reading] = []
    for entry in root.findall(f"{space}entry"):
        title = (entry.findtext(f"{space}title") or "").strip()
        link = (entry.findtext(f"{space}id") or "").strip()
        if not title or not link:
            continue
        readings.append(
            Reading(
                title=" ".join(title.split()),
                url=link,
                source=ARXIV,
                summary=" ".join((entry.findtext(f"{space}summary") or "").split())[:600],
                published=(entry.findtext(f"{space}published") or "")[:10],
                authors=[
                    (a.findtext(f"{space}name") or "").strip()
                    for a in entry.findall(f"{space}author")
                ][:6],
            )
        )
    return readings


def from_web(query: str, key: str, limit: int = PER_SOURCE) -> List[Reading]:
    """Blogs, documentation, standards, and everything arXiv does not hold.

    The highest-signal source for exactly the fields arXiv is worst at, and the
    one with no quality floor at all — a search result is a document that exists,
    not a document that is right.
    """
    url = "https://api.search.brave.com/res/v1/web/search?" + urllib.parse.urlencode(
        {"q": query, "count": limit}
    )
    payload = json.loads(
        _get(url, {"Accept": "application/json", "X-Subscription-Token": key})
    )
    readings: List[Reading] = []
    for result in (payload.get("web") or {}).get("results", [])[:limit]:
        if not result.get("title") or not result.get("url"):
            continue
        readings.append(
            Reading(
                title=result["title"],
                url=result["url"],
                source=WEB,
                summary=(result.get("description") or "")[:600],
                published=(result.get("age") or "")[:10],
            )
        )
    return readings


_ARXIV_ID = re.compile(r"arxiv\.org/(?:abs|pdf)/(\d{4}\.\d{4,5})", re.I)


def follow_arxiv(readings: Sequence[Reading], limit: int = PER_SOURCE) -> List[Reading]:
    """Fetch metadata for arXiv papers the web already surfaced.

    arXiv is one publisher, not the index. Querying it in parallel with a
    general search asks it about topics it may not hold — the first live run
    returned five radio-telescope papers for "covering array generation" — while
    a general index disambiguates from context and gets it right unprompted.

    So the web decides *what* is relevant and this fills in what a search result
    cannot give: authors, publication date, and the full abstract rather than a
    truncated snippet. Following a link is cheap and correct where guessing a
    query is neither.
    """
    ids: List[str] = []
    for reading in readings:
        found = _ARXIV_ID.search(reading.url)
        if found and found.group(1) not in ids:
            ids.append(found.group(1))
    if not ids:
        return []

    url = "https://export.arxiv.org/api/query?" + urllib.parse.urlencode(
        {"id_list": ",".join(ids[:limit]), "max_results": limit}
    )
    return _parse_arxiv(_arxiv_get(url))


def from_repositories(query: str, limit: int = PER_SOURCE) -> List[Reading]:
    """Theory applied. A repository implementing a method is evidence the method
    is usable, which is a different and often more useful claim than a paper
    asserting it works.

    Unauthenticated, so it is rate-limited to sixty an hour and will fail under
    load. That failure is reported, not swallowed.
    """
    url = "https://api.github.com/search/repositories?" + urllib.parse.urlencode(
        {"q": query, "sort": "stars", "order": "desc", "per_page": limit}
    )
    payload = json.loads(
        _get(url, {"Accept": "application/vnd.github+json", "User-Agent": "vesta"})
    )
    readings: List[Reading] = []
    for item in payload.get("items", [])[:limit]:
        readings.append(
            Reading(
                title=item.get("full_name", ""),
                url=item.get("html_url", ""),
                source=REPOSITORY,
                summary=(item.get("description") or "")[:600],
                published=(item.get("pushed_at") or "")[:10],
            )
        )
    return [r for r in readings if r.title and r.url]


# ── The search a caller holds ────────────────────────────────────────────


class Search:
    """The seam `maturity.judge` takes.

    Constructed from the environment so a deployment turns acquisition on by
    supplying a key and off by not supplying one — there is no flag, and no way
    to have a key configured and searching disabled, because that state would be
    a setting nobody could explain.
    """

    def __init__(
        self,
        brave_key: str = "",
        sources: Sequence[str] = SOURCES,
        fetch: Optional[Dict[str, Callable]] = None,
    ) -> None:
        self.brave_key = brave_key
        self.sources = tuple(sources)
        # A query asked twice in one run costs twice and returns the same
        # thing. `judge` searches to reach a verdict and the caller then wants
        # the readings behind it; without this that is two round trips and, on
        # a metered key, two charges for one answer.
        self._answered: Dict[str, Found] = {}
        # Sources whose credential was refused. Held so a run does not keep
        # asking, and so `why_not` can say a key is present *and* not working —
        # which is a different problem from a key that is absent.
        self._rejected: Dict[str, str] = {}
        # Injectable so the sources can be exercised without a network. The
        # default is the real thing; a test supplies its own.
        self.fetch = fetch or {
            ARXIV: from_arxiv,
            WEB: lambda q, limit=PER_SOURCE: from_web(q, self.brave_key, limit),
            REPOSITORY: from_repositories,
        }

    @classmethod
    def from_environment(cls, env: Optional[Dict[str, str]] = None) -> "Search":
        if env is None:
            # The family shares one `.env` above each component. Without this a
            # key that is configured reads as absent, and the search reports a
            # limitation the user has already removed — which is worse than a
            # missing key, because it is wrong rather than merely unhelpful.
            _load_env()
            env = dict(os.environ)
        return cls(brave_key=env.get(BRAVE_KEY, "").strip())

    @property
    def is_available(self) -> bool:
        """Whether searching is on.

        arXiv and GitHub need no key, so acquisition can run without one — but
        on two sources that between them miss most of programming languages and
        systems. A judgement made on that basis is weaker, and `why_not` says so
        rather than the caller having to know.
        """
        return bool(self.sources)

    @property
    def why_not(self) -> str:
        """What a caller should be told about the limits of this search."""
        if WEB in self._rejected:
            return (
                f"The {BRAVE_KEY} was rejected ({self._rejected[WEB]}), so blogs, "
                "documentation and standards were not searched — a key is "
                "configured but it is not working."
            )
        if not self.brave_key and WEB in self.sources:
            return (
                f"No {BRAVE_KEY} is set, so blogs, documentation and standards "
                "were not searched — the fields least covered by preprints are "
                "the ones least covered here."
            )
        return ""

    def for_(self, query: str) -> Found:
        """Every configured source, with failures reported rather than hidden.

        One source failing does not fail the search: a result set from two of
        three sources is worth having, provided it says which one is missing.
        """
        if query in self._answered:
            return self._answered[query]

        reach = Reach(query=query)
        readings: List[Reading] = []
        # Sources that will not answer for as long as this Search exists: no
        # key, or no fetcher. Distinguished from a source that failed this
        # once, because only the latter is worth asking again.
        standing: set = set()

        # Web first, so arXiv can follow what it surfaces. A general index
        # disambiguates a query from context; arXiv answers whatever is asked of
        # it, out of whichever field the words happen to match.
        for name in sorted(self.sources, key=lambda s: (s != WEB, s == ARXIV)):
            if name == WEB and not self.brave_key:
                reach.skipped[name] = f"no {BRAVE_KEY}"
                standing.add(name)
                continue
            call = self.fetch.get(name)
            if call is None:
                reach.skipped[name] = "no such source"
                standing.add(name)
                continue
            try:
                if name == ARXIV and call is from_arxiv and readings:
                    # Follow the papers the web already judged relevant, rather
                    # than asking arXiv the same question and hoping it holds
                    # the field. Where the web found nothing — or was never
                    # asked — fall back to querying it directly, since some
                    # arXiv is better than none.
                    followed = follow_arxiv(readings)
                    readings.extend(followed or call(query))
                else:
                    readings.extend(call(query))
                reach.asked.append(name)
            except urllib.error.HTTPError as exc:
                # A rejected credential is not a transient failure. Brave
                # answers 422 for a bad token and 401 for a missing one, and
                # retrying either spends the rest of the run rediscovering the
                # same fact — so the source is dropped and the reason is said.
                #
                # 403 is deliberately *not* here: it usually means a quota is
                # exhausted rather than a key is wrong, and a quota can come
                # back within a run while a bad key cannot.
                if exc.code in (401, 422):
                    self.sources = tuple(s for s in self.sources if s != name)
                    self._rejected[name] = f"HTTP {exc.code} — the key was rejected"
                    reach.skipped[name] = self._rejected[name]
                    standing.add(name)
                    logger.warning("%s rejected the key (HTTP %s)", name, exc.code)
                else:
                    logger.warning("%s failed for %r: %s", name, query, exc)
                    reach.skipped[name] = str(exc)[:120]
            except (urllib.error.URLError, OSError, ValueError, ET.ParseError) as exc:
                # A source that errors is a hole in the evidence, not a verdict
                # about the query. Recording which one failed lets a user retry
                # the search rather than trust a thin result.
                logger.warning("%s failed for %r: %s", name, query, exc)
                reach.skipped[name] = str(exc)[:120]

        found = Found(readings=_deduplicate(readings), reach=reach)
        # Only a complete answer is kept. A search where a source was rate
        # limited is a partial result, and remembering it would turn one
        # transient failure into a permanent hole for the rest of the run.
        if set(reach.skipped) <= standing:
            self._answered[query] = found
        return found

    def __call__(self, query: str) -> Found:
        """`maturity.judge` calls its search directly."""
        return self.for_(query)


def _deduplicate(readings: Sequence[Reading]) -> List[Reading]:
    """One reading per URL, keeping the first source that found it.

    Order is preserved rather than sorted by any score, because no source
    supplies a comparable one and inventing a ranking across arXiv, the web and
    GitHub would be asserting a comparison nothing supports.
    """
    seen: set = set()
    kept: List[Reading] = []
    for reading in readings:
        key = reading.url.rstrip("/").lower()
        if key in seen:
            continue
        seen.add(key)
        kept.append(reading)
    return kept
