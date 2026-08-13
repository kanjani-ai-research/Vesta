# Open questions

Five things Vesta does not yet do well, written down while the evidence for
each is fresh. Every number here was measured on this repository on the day it
was written; where something is a suspicion rather than a measurement, it says
so.

This is not a roadmap. Nothing here is scheduled, and at least two of them may
turn out not to be worth doing — the point is that the reasoning behind each is
recorded now, rather than reconstructed later from a stale intuition.

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

## 2. Intent capture produces fragments, not intentions

**This is the sticking point, and it has numbers.** On this repository:

    50 rules recovered from 523 user turns
    13 have a check that could in principle run
    37 have none — "no known check covers what this constrains"
     0 were actually checked

Here is what the 37 look like:

    "for question 1, I don't know but I can't see how UC3 is fundamentally
     different from UC…"
    "1. same generator  2. I think one call one row, I don't know and have
     some concerns: you…"
    "it seems you identified a vulnerability in the spec that must be
     addressed, anserable by…"

These are not intentions. They are conversational turns that matched a pattern.
Meanwhile the rules that *are* clean — "the consent to build is only for full
auto mode", "non-full auto is a companion, no consent" — all arrived by
`--declare`, a user stating one outright, rather than by extraction.

**So the extractor's yield is poor at both ends.** 523 turns in, 50 candidates
out, 13 of them checkable in principle and none checked in fact. It is finding
syntax that resembles a decision without any test of whether a decision was
made — and the 37 it cannot check are not a checking failure so much as
evidence that they were never rules.

The check strategies it *does* name are worth reading, because they show what
the mechanism can already reason about:

    run the suite and compare what it covers against the claim      5
    inspect the files produced for the stated property              2
    find every site that loads configuration and check what it
      resolves to                                                   2
    find the sites introducing optionality and check they are on
      decision paths                                                2
    run both and compare observable output for shared inputs        1
    inspect the commits produced against the stated shape           1

Those are real, specific, and none of them ran. Which points at checking as a
second, separate gap rather than a consequence of the first.

**Three separable problems, currently tangled.**

*Extraction* — deciding a turn contains a standing intention. Today: regexes
over user turns (`CORRECTS`, `DEFINES`, and friends). A person saying "no, use
SQLite" and a person saying "no, I don't think that's right" are
indistinguishable to a pattern.

*Adjudication* — the user confirming it. Today: `vesta learn <handle> rule`,
with `AskUserQuestion` in-session. The UX was hard-won and works, but it is
only as good as what is put in front of it. **Five candidates waiting on a user
who has already answered dozens is a queue nobody drains** — and the queue is
mostly fragments, which trains the user to ignore it.

*Checking* — deciding whether the code honours it. Today: `enforce.against`
builds a `Check` from a rule, and `_check_on` returns `None` for anything it
cannot turn into a grep-like test. Everything else is `undecided`, and the CLI
does not print the reason, so a user sees "could not be checked" with no way to
find out why. Thirteen rules here carry a named strategy and **none of them
ran** — which is a different failure from having no strategy at all.

**The question.** Which of the three is the bottleneck? Probably not one:
extraction produces 37 fragments that should never have reached the queue, and
checking fails to run 13 strategies it already articulated. Fixing either alone
leaves the pipeline broken.

But there is a more uncomfortable possibility worth stating: **extraction by
pattern may be the wrong idea outright.** A standing decision and a passing
remark are not syntactically different — "no, use SQLite" and "no, I don't
think that's right" differ only in meaning. If that is true, the right move is
to stop mining transcripts and instead make *stating* a rule cheap enough that
users bother. The `--declare` path produced every clean rule in this
repository.

**Smallest useful step, regardless.** Print `Finding.undecided` in
`vesta decided --check`. The reasons are computed and discarded, which makes an
unverifiable rule look the same as a verified one to anybody reading the
output.

---

## 3. What should score similarity

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

## 4. Cross-project metadata is a timestamp

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

## 5. Storage grows and nothing evicts

**Measured today.**

    ~/.vesta/graphs   337M
      of which one abandoned tmp- graph:  193M .db + 138M .json  = 331M
    34 .db files, 37 .json files

Two facts fall out of that.

*Nothing evicts.* A graph built for `/tmp/…` during a test in August is still
there. 331M of 337M is one abandoned temporary repository. There is no
eviction, no age-out, and no command that reports what is held or reclaims it.

*Every graph is stored twice, and both are live.* 34 `.db` and 37 `.json`. The
duplication is not an accident and neither file is a leftover — they serve two
different access patterns:

- the **JSON** is the whole-graph cache. `held.graph_for` reads it entire and
  validates it into a `Graph` in memory, because traversal needs the whole
  thing and re-walking the tree costs an order of magnitude more.
- the **SQLite** is the queryable store. `store.py` opens a read-only URI
  connection and answers `WHERE name = ?` against an index, without loading
  anything.

So the question is not "which one is dead" — it is whether a process that has
already paid for the JSON should ever consult the database, and vice versa.
The three orphaned JSON files with no database beside them are a smaller
question: probably graphs written before the store existed.

**Indexing is in better shape than expected.** The SQLite schema already
carries what the queries need:

    idx_nodes_name, idx_nodes_path, idx_edges_source, idx_edges_target

and `store.py` queries with `SELECT … WHERE` and a read-only URI connection
rather than loading a graph whole. So *lookup* is not the problem the heading
implies.

**The real questions are about lifecycle, not speed.**

- What reclaims space, and on what signal? Age is the obvious one and probably
  wrong: a project untouched for a month is the one where a cached
  understanding is worth *most*. Whether the repository still exists is a
  better signal, and cheap — the abandoned 331M is a path under `/tmp` that has
  not existed for weeks.
- Ontologies, maps, rules, notes and patterns are all one-file-per-repository
  under separate directories. That is easy to reason about and easy to
  reconcile — this session found two bugs caused by an ontology and a map going
  out of step. Would a single store per repository have prevented them, or just
  moved the seam?
- Sharding is named as a concern but not yet a measured one. The largest real
  graph here is 684K. **Nothing suggests a scale problem yet**; the problem
  that exists today is hygiene.

---

## What was done before release

Two of the five were credibility problems rather than features, and both are
fixed. Neither touches the research questions above; they are the parts where
Vesta was **overstating what it knew**, which a tool built against that failure
cannot ship.

**From question 2 — reporting a check that never ran.** `describe()` counted
every finding as "checked" whatever happened, so three rules nothing could test
printed as `3 rule(s) checked, 0 held, 3 could not be checked` — which reads as
three violations. It now separates what ran from what did not, and
`decided --check` prints the reason each rule could not be checked instead of
computing it and throwing it away.

Extraction also stopped admitting sentences that withdraw their own claim.
`CONSTRAINS` matches "should", and nothing tested whether the same sentence
said "I don't know" — so *"it should be conditional, I don't know whether your
assertion holds"* reached the queue as a rule awaiting confirmation the user
had already disclaimed. The `UNSURE` guard rejects those, at harvest and in the
queue. On this repository: 48 rules → 44, 37 gaps → 33, all three standing
rules kept.

That guard is a whole-sentence veto and it is wrong in one direction on
purpose. *"I don't know why, but every module must open with a docstring"* is a
real rule and this rejects it. A missed rule costs one `/vesta:declare`; a
queue full of things a user has already said they cannot settle costs their
willingness to look at the queue at all.

**From question 5 — nothing reported or reclaimed anything.** `vesta held`
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

Of what remains:

1. **Record the phrase and the hit count in `used.jsonl`.** Until that exists,
   the similarity question can only be argued from preference — and the three
   candidates differ by two orders of magnitude in cost, which is too wide a
   gap to guess across.
2. **Run the thirteen checks that already have a strategy.** They name
   something specific and none of them executes. Whether that is a bug or a
   missing capability is not yet known, and finding out is cheap.
3. **Decide whether `kind` earns its keep** — but only after (1), since the
   evidence for it is the same evidence.

The first is instrumentation rather than a feature, and that is the point:
the remaining questions cannot be answered with evidence by a tool whose whole
premise is answering with evidence. Everything else waits on it.
