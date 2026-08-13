# Open questions

Three things Vesta does not yet do well, written down while the evidence for
each is fresh. Every number here was measured on this repository on the day it
was written; where something is a suspicion rather than a measurement, it says
so.

This is not a roadmap. Nothing here is scheduled, and at least one of them may
turn out not to be worth doing — the point is that the reasoning behind each is
recorded now, rather than reconstructed later from a stale intuition.

Two more were written down here and then fixed before release, because they
were not open questions at all — they were places Vesta overstated what it
knew. What they were, and what running them turned up, is at the end.

---

## 1. Kind is documentation, not machinery

**What is true today.** An ontology names three kinds of term — `domain`,
`activity`, `role`. The engine treats them as one flat namespace. `where()`
scores an attachment by word overlap between the asked phrase and the
attachment's *label*, plus a 0.6-weighted match against the definition's own
name and path. `kind` is never consulted:

    grep -rn "\.kind" vesta/*.py

Every ontology hit is carry, count, sort, or display. Nothing branches on it.
(The hits in `graph.py`, `resolve.py` and `store.py` are a different `kind` —
LSP symbol types.)

So a `domain` term and an `activity` term are scored identically. Adding domain
terms to a repository that has none adds matchable surface — nothing more. It
does not add traversability, because there is no traversal that consults kind.

**The question.** Should kind earn its keep?

There is a real feature here. A user asking *"where does this do X"* is asking
about activity. A user asking *"what is this project about"* is asking about
domain. A user asking *"what does it handle"* is asking about role. Three
different intentions, currently answered by one scorer that cannot tell them
apart.

Wider than kind, this is about **dimensions of user intention**. Today there is
one crossing — phrase to label. Plausible others:

- *what does this project do* — domain terms, no code
- *where is X done* — activity terms, ranked by attachment strength
- *what handles Y* — role terms
- *what is this definition for* — the reverse crossing, code to label
- *what else does this kind of work* — label to sibling definitions

The last two exist as `means`. The first three do not.

**Against doing it.** Kind is currently a useful fiction for the *labelling*
agent: asking for three kinds stops it producing forty synonymous verb phrases.
That is a legitimate purpose and it costs nothing. Making kind load-bearing at
runtime means every ontology derived before the change has a kind distribution
nobody was thinking carefully about — including this repository's, which after
an editing session has 42 activities, 9 roles and no domains at all.

**What would have to be true.** That users ask these as distinct questions and
get worse answers today because of it. Currently unmeasured. The cheapest test
is to take real `does` queries from `used.jsonl` and hand-classify what was
being asked.

---

## 2. What should score similarity

**Today it is a set intersection.** `_bag()` lowercases, splits on
non-alphanumerics, drops words of two characters or fewer and a stoplist, and
`where()` scores `|wanted ∩ label| / |wanted|`. No dependency beyond pydantic.
No model. No index.

Its known limit is documented in `traverse.where`: it cannot cross a synonym
neither surface contains. Ask for "fuzzy search" where the label says "scores
how closely two texts overlap" and the definition is called `closeness`, and
nothing matches — two of the words are in the code, none in the label.

**Three candidates, and the trade is not obvious.**

*Native Python (today).* Free, instant, no dependency, deterministic, and
explainable — a user can see exactly why something matched. Fails on synonymy.

*sentence-transformers.* Crosses synonyms. Costs a model download, a warm-up on
first use, and a hard dependency this project has so far refused to take —
`pyproject.toml` declares exactly one runtime dependency, pydantic.

Two fossils say it was once used and deliberately removed: `sidecar.py` still
names `sentence_transformers` in its log-silencing list, and the package is
still *installed* in this development venv (5.7.0, required by nothing,
imported nowhere under `vesta/`). Worth knowing before re-litigating: the
removal was a decision, not an oversight, and whatever reasoning drove it is
not written down anywhere this document could find.

*Haiku.* Crosses synonyms, needs no local model, and runs on inference the user
is already paying for — the standing model rule puts text analysis on haiku
precisely because it happens at volume. But similarity scoring is not once per
definition; it is **once per candidate per query**. With 266 attachments a
single `does` call would be 266 comparisons, or one call with 266 candidates in
the prompt. The first is plainly prohibitive. The second is one call — but it
is a call on the hot path of a tool whose whole pitch is answering without
re-reading.

**What is unmeasured, and needs to be before choosing.**

- How often does the bag-of-words scorer actually miss? **This is not
  currently recoverable.** `used.jsonl` records `at`, `tool`, `project`,
  `took`, `answer_chars` and `session` — but not the phrase asked, and not
  whether anything was found. A miss and a hit are distinguishable only by
  `answer_chars` being small, which also describes a repository with one
  matching definition. Recording the phrase and the hit count is a one-line
  change and a prerequisite for answering this question with evidence.
- What would haiku cost per `does` call in practice, at realistic attachment
  counts?
- Is the miss rate concentrated in queries a *user* typed, or ones an *agent*
  typed? An agent that gets nothing back can rephrase and ask again — which
  `where()`'s own docstring already relies on. A human gets one shot and gives
  up.

**A fourth option nobody has costed:** keep the cheap scorer, and spend a model
call only on a *miss*. The expensive path then runs at the frequency of
failure rather than the frequency of use, and the common case stays free.

**And whichever wins, it drags a UX problem behind it.** This is the part that
makes the question larger than it looks. Choosing sentence-transformers is not
one decision, it is three:

- *which scorer* — native, local model, or haiku. A layer above the scoring
  itself, and the honest default is not obvious: the right answer differs for a
  user on a plane, a user paying per token, and a user who wants determinism.
- *which embedding model*, if local — there are dozens, they differ by an order
  of magnitude in size, and the good default changes yearly.
- *installing it* — a model download inside a plugin the framework installed,
  on first use, in a session where somebody is trying to do something else.

That is exactly the shape this project has refused elsewhere: optional imports
and configuration flags are how not to decide. A scorer chosen by a settings
menu is three code paths that must all stay correct, and two of them will be
untested in practice.

So the question is not only *which scorer is best* but **whether Vesta can take
a local model without becoming configurable** — and if it cannot, the fourth
option above starts looking less like a compromise and more like the only shape
that preserves the property that installing Vesta requires no decisions.

---

## 3. Cross-project metadata is a timestamp

**What exists.** `~/.vesta/referred.json` is one object mapping a project path
to when it was last referred to:

    {"/private/tmp/indexer": 1786548254.540201}

`elsewhere` consults another project's ontology and map, and the docstring is
explicit that the two are **consulted, not merged** — because reconciling two
independently derived ontologies is a problem nobody asked to solve.

**That reasoning still holds, and it is also the limit.** Ontologies derived
separately from two repositories that genuinely share a domain will name the
same work differently, and nothing notices. Two projects in this namespace both
"validate an untrusted input"; if one calls it that and the other calls it
"check a supplied value", `elsewhere` finds nothing and reports honestly that
nothing was found.

**The question is what shared metadata would consist of.** Candidates, roughly
in order of ambition:

- *a shared vocabulary* — the template mechanism built for domain templating
  already does exactly this, and templates deliberately carry words and never
  bindings. A family of projects could share one vocabulary file and each bind
  it to its own code. **This is the cheapest version and it already works** —
  nothing has tried it across the v3 family.
- *shared rules* — "one .env for the whole of v3" is a decision about a
  namespace, not a repository, and today it is recorded against whichever
  project the user happened to be in.
- *shared intentions* — a contract or goal spanning projects. Genuinely
  unbuilt.

**What would have to be true.** That the same work really is done in more than
one project and that a user asks across them often enough to matter.
`referred.json` has one entry, from a temporary directory. Nobody is using
`elsewhere` yet, including the person who built it.

---

## What was done before release

Two things written up here were credibility problems rather than features, and
both are fixed. Neither touches the research questions above; they are the
parts where Vesta was **overstating what it knew**, which a tool built against
that failure cannot ship.

**Reporting a check that never ran.** `describe()` counted
every finding as "checked" whatever happened, so three rules nothing could test
printed as `3 rule(s) checked, 0 held, 3 could not be checked` — which reads as
three violations. It now separates what ran from what did not, and
`decided --check` prints the reason each rule could not be checked instead of
computing it and throwing it away.

**Intent capture — harvesting words the user never said.** This was the real
defect, and it was found by asking where one specific rule came from.

*"in this project every module must open with a docstring saying what it is
for"* was sitting in the candidate queue as something the user had decided. It
exists nowhere in this repository except as **fixture data inside
`tests/test_seams.py`**, written to exercise the harvester. Vesta was mining
its own test suite out of the transcript and presenting it as the user's
decisions — the same class of failure as inventing a finding.

It arrived three ways, all recorded in the transcript with `role: user`:

- **compaction summaries**, which replay an entire conversation as one turn.
  Every rule-shaped sentence in a digest is harvested again as though freshly
  stated. 53 in this project's transcripts.
- **assistant turns**, echoed back with their `⏺` marker. 24 more.
- a genuine turn where somebody pasted the fixture to talk about it.

The first two are not the user at any remove, so they are dropped at the point
of reading rather than filtered later — a summary is not a weaker signal of
intent, it is a different speaker. Across all transcripts that is **357 turns**
that were being mined as decisions and were nobody's.

Three narrower guards went in beside it:

- *Source is not a decision.* A turn containing a definition, an import, a
  fenced block or an assertion is code being shown, whatever sentences are
  inside it.
- *A turn that closes by asking is a question.* `ASKS_ABOUT_IT` anchors at the
  start, so an imperative ending in a question slipped through — *"address the
  extraction now instead of shifting it in the document, or are you saying it's
  not worth doing?"* was captured as a standing rule. What a turn wants is in
  its last clause.
- *A sentence that withdraws its own claim is not a rule.* `CONSTRAINS` matches
  "should" and nothing tested for "I don't know" in the same breath, so *"it
  should be conditional, I don't know whether your assertion holds"* asked a
  user to confirm what they had just disclaimed.

On this repository: **523 turns → 444**, 48 rules → 41, 37 gaps → 32, all three
standing rules kept.

Two of those guards are wrong in one direction on purpose. *"I don't know why,
but every module must open with a docstring"* is a real rule and the unsure
guard rejects it, because nothing here parses which clause a disclaimer
attaches to. A missed rule costs one `/vesta:declare`; a queue full of things a
user has already said they cannot settle costs their willingness to look at the
queue at all.

**What is still open.** None of this makes extraction *good* — it makes it stop
lying about provenance. The uncomfortable possibility stands: a standing
decision and a passing remark are not syntactically different, so pattern
mining may be the wrong idea outright and the answer may be to make *stating* a
rule cheap enough that people bother. Every clean rule in this repository
arrived by `--declare`. And thirteen rules carry a named check strategy that
has never executed, which is a separate gap from having no strategy at all.

**Storage — nothing reported or reclaimed anything.** `vesta held`
lists every holding by repository, biggest first, and `--reclaim` removes what
is dead. On this machine that was **343M → 12M**, of which 330.5M was a single
graph rooted at `/private/tmp` — the system temp directory, walked as though it
were a project.

Three things that only surfaced by running it:

- *Age is the wrong signal, and so is a temp root.* pytest puts every
  `tmp_path` under `/private/var/folders`, so "anything temporary-rooted is
  dead" marked live test repositories reclaimable. The rule is now: gone means
  gone, and a graph of a temp root *itself* is junk — reported separately,
  because it is not dead, it should never have been built.
- *An unreachable path is not a deleted one.* An unmounted volume fails
  `exists()` while the repository is perfectly alive, so that answers *unknown*
  and is never in the set to remove.
- *The sizes were doubly counted.* A graph is stored as JSON and SQLite;
  counting the database beside each JSON, when the walk had already counted it,
  overstated every holding by roughly half — in a report whose whole job is
  telling somebody how much they would get back.

## What is worth doing first

Not a plan, but the honest ordering by evidence:

1. **Record the phrase and the hit count in `used.jsonl`.** Until that exists,
   the similarity question can only be argued from preference — and the three
   candidates differ by two orders of magnitude in cost, which is too wide a
   gap to guess across.
2. **Run the thirteen checks that already have a strategy.** They name
   something specific and none of them executes. Whether that is a bug or a
   missing capability is not yet known, and finding out is cheap.
3. **Decide whether `kind` earns its keep** — but only after (1), since the
   evidence for it is the same evidence.

The first is instrumentation rather than a feature, and that is the point: the
remaining questions cannot be answered with evidence by a tool whose whole
premise is answering with evidence. Everything else waits on it.
