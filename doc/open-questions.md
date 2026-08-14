# Open questions

Four things Vesta does not yet do well, written down while the evidence for
each is fresh. Every number here was measured on a real repository on the day
it was written; where something is a suspicion rather than a measurement, it
says so.

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

## 4. A third of a real workspace is not code

**Vesta resolves seven languages** — C, Rust, Python, Go, JS/TS, OCaml, Lua —
and a repository is whatever those files say it is. On `~/Developer/causum/v4/
ontos` that leaves a third of the workspace invisible:

    metis          8,471 lines of Python   →  526 definitions
    deps             617 lines of Python   →   31 definitions
    bona-schemas   171 JSON, 1 Python      →   22 definitions

`bona-schemas` is the densest artifact in that workspace and Vesta sees almost
nothing in it. Its files carry `properties`, `handlers`, `idPattern`,
`evidentiary_level`, `nodes`, `edges` — structure a graph could hold, and the
kind of thing a change breaks silently.

**The staleness problem is already solved.** The first objection to reading
schemas is that reprocessing everything on every change is disastrous at scale.
It would be, and `held._shape` is exactly the answer: a fingerprint of
`path:size:mtime` per file, rebuilt only where it changed. That is snapshot
plus change-detection, proven on code, and it would carry over unmodified.

Nor is size the obstacle here — the whole of `bona-schemas` is 6.0MB and its
largest file is 0.7MB. The concern is real for a workspace that ships a 100MB
document; it is not what blocks this one.

**What blocks it is that "a definition" has no single meaning.** Of those 171
files: 104 look like JSON Schema, 35 are bare lists, 32 are loose objects. A
resolver has to decide, per shape, what counts as a node and what counts as a
reference — and deciding wrong produces false positives, which is the failure
mode that made two other detectors untrustworthy on this same repository. A
schema resolver that reports a live `$ref` as broken is worse than no schema
resolver.

**So it is deferred, not rejected.** The smaller version is worth costing
first: not modelling a schema's internals at all, only detecting which code
*loads* which schema file, so `touches` can answer "what reads this schema".
That is a file-level edge, needs no opinion about what a definition is, and
delivers the question people actually ask.

---

## 5. A graph costs one server round trip per definition

**Enabling the plugin midstream on a large project does not work yet**, and
the reason is arithmetic rather than a bug.

Measured on `~/Research/taguchi`:

    references call to pyright     0.9s
    definitions in the repository  ~2000
    graph build                    ~30 minutes

Nothing hangs. `symbols` for all 62 source files takes two seconds; a single
file resolves in under one. The cost is entirely `references`, called once per
definition, each searching a workspace whose `venv/` is 656MB.

**Two things were fixed on the way to finding that, and both were real.**

*Dependencies were being walked as if they were the project.* The exclusion
list said `.venv` with a dot; the directory was named `venv` without one. So
13,613 of 13,675 files Vesta considered were somebody's installed packages,
and the actual project was 62 files. Worse, there were **three separate
exclusion lists** — in `held`, `resolve` and `patterns` — with three different
contents, so what the resolver walked and what the graph called its shape could
disagree. They are now one list in `home`, and it names every spelling anybody
uses.

*The language server was told nothing about what to skip.* `workspace/
configuration` answered `{}` — "no opinion, use your defaults" — and pyright's
default is to index everything it can reach. Excluding directories from Vesta's
own walk does not stop the server walking them. It is now told, at initialize
and on request.

Neither fix touched the 0.9s. **The remaining cost is structural**: a graph of
N definitions is N round trips to a process that answers each by searching the
workspace.

**What the options look like, none of them costed.**

- *Ask for fewer.* Most definitions are never asked about. A graph built lazily
  — resolve on demand, cache the answer — would make the first question slow
  and the rest free, at the cost of a graph that is never complete and cannot
  answer "what refers to nothing".
- *Ask in parallel.* Requests are sequential today. A server that indexes once
  can usually answer several at a time, and this is the cheapest thing to try.
- *Ask something else.* `workspace/symbol` or a batch request, where a server
  supports it, trades per-definition calls for one large answer.
- *Do not resolve third-party code at all.* pyright resolves imports into the
  virtualenv because that is what makes a reference correct; refusing to would
  make some answers wrong in a way that is hard to see, which is the failure
  this project is most careful about.

**What is not in doubt** is that the current behaviour is the wrong shape for a
plugin: preparation is detached and never blocks a prompt, so nothing breaks —
but on a repository like this one it would still be preparing half an hour
later, and every question in between is answered with "not ready yet".

**Since measured, most of the 30 minutes turned out not to be the round
trips.** The 0.9s figure stands, but the count was wrong: the repository has
252 definitions, not 2000, once the walk stops descending into a virtualenv.
It builds in well under a minute now. The per-definition cost is still the
shape of the thing and still worth the four options above — but it is a
question about very large repositories, not about ordinary ones.

---

## The graph is current whenever Vesta is active

An invariant, added after asking what happens when the plugin is enabled
midstream in a project somebody has been working in for months. The answer was
that it could serve a graph up to five minutes old, and in three separate ways
did not notice the code had changed at all.

**Nothing hidden is ever read.** Anything beginning with a dot is skipped
outright — `.env`, `.aws`, `.ssh`, `.git`, `.venv`, and every private thing
nobody has thought of yet. A rule rather than a list, because a list of names
is always one spelling short. Alongside it, a banlist of the *visible*
dependency and build directories across languages, since most of them are not
hidden: `venv`, `node_modules`, `site-packages`, `target`, `vendor`, `Pods`,
`miniconda3`, `third_party`. Names that mean "dependency" in one project and
"my code" in another — `bin`, `deps`, `pkg`, `packages`, `external` — are
deliberately absent: this repository keeps its launcher in `bin/` and the
workspace next door keeps a real component in `deps/`, and hiding somebody's
source is silent where walking a dependency is only slow.

**The walk prunes as it descends.** `rglob` visited every excluded directory
in full and then discarded each path: 66,010 paths to fingerprint 77 source
files, taking 3.6 seconds. It now visits what it keeps, and takes 8ms.

That is the whole reason the invariant was affordable. Three things had traded
correctness for that 3.6 seconds, and each was quietly wrong:

- *`readiness` reported READY whenever a graph file existed*, however old, and
  every caller took that as permission to read it. It now compares the
  fingerprint and reports `moved on` — which still counts as answerable,
  because `graph_for` rebuilds on the way past.
- *Every sidecar tool asked for `trust_for=300`*, accepting a graph up to five
  minutes stale. During an active session — the one time code changes minute
  to minute — answers could be a hundred edits behind, and a stale answer looks
  exactly like a fresh one.
- *The fingerprint memo was two seconds.* An agent that writes a file and then
  asks about it, which is the ordinary rhythm of a session, was answered from
  the tree as it stood before the write.

**And a fourth defect, older than any of them.** The fingerprint used
`int(st.st_mtime)` — one-second resolution — beside a file size, so changing
`x = 1` to `x = 2` within a second moved nothing. Same-length corrections made
quickly are the commonest edit in a live session, and every one of them was
invisible.

The cost of the guarantee, measured in a fresh process on an unchanged tree:
**15ms** on this repository, **38ms** on a workspace of 2,768 definitions.

## A graph per path, composed upward

A directory holding several projects is not one project, and Vesta treated it
as one. On a workspace of thirteen repositories that meant a single graph of
6,309 definitions taking **73 seconds** to build — and touching one file in one
of them made the whole thing stale, so the next question rebuilt twelve
projects that had not changed. Measured inside a prompt, a hook took **over two
minutes**.

The shape that fixes it is the one the tree already has. Each project gets its
own graph, keyed by its own path; a question about the directory above is
answered by composing the graphs beneath it. A project is a directory with a
`.git`, a manifest, or the conventional layout — looked for one or two levels
down, because looking deeper finds every package inside every project and calls
each one a project.

**Composition is mechanical, not a reconciliation.** These graphs describe
disjoint subtrees and cannot disagree, so joining them is: rebase every path
onto the shared root, re-derive every node id from the rebased path, rewrite
the edges to match. Ids are `sha256(path, line, name)`, so a node genuinely has
a different id in its own graph than in a composed one — getting that wrong
would silently break every reference, which is why it lives in one function
with tests either side of it.

Measured on the same workspace:

    build, all twelve projects            89s   (once)
    warm read, nothing changed           470ms
    after editing one project              9s   (that project only)
    a prompt naming a file                10ms  (was 5,117ms)
    a prompt where defects apply           1ms  (was 15,439ms)

**What composing cannot recover is a reference from one project into
another.** Neither resolver was shown the other's files, so that edge is in
neither graph. The composed graph counts it as a hole rather than letting an
absence of references look like an absence of coupling — for a workspace of
independent components that is usually the truth anyway, and where it is not,
saying so is better than a silent omission.

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

**Extraction — the patterns were the decision.** The guards above stopped the
lying about provenance but left the deeper problem: a standing decision and a
passing remark are not syntactically different, so no pattern can separate
them. The conclusion drawn from that was to write better patterns. It was
wrong.

`from_sessions` dropped every turn `constrains` rejected, and the model — a
haiku agent that exists, runs, and has a carefully written brief — only ever
saw what survived. On this repository that was **42 turns of 446, 9.4%**.
Everything in the other 404 was invisible, and no amount of prompting could
recover it because nothing was ever asked. Among the discarded: *"it shouldn't
be configurable, commit or change main/active should write to FS-"* — a
standing architectural decision phrased in a way no pattern anticipated.

The patterns now **rank rather than gate**. Every turn the user actually said
goes to the thing that can judge it, ordered so a reader with a budget starts
with the promising ones. On this repository: **42 candidates → 357**. Scoring
zero is the only way a turn is dropped, and that is reserved for what is not
the user speaking at all — summaries, assistant turns, pasted code.

The corpus is 150k characters, read once per repository. Being thorough is
cheap; being wrong costs a rule the user has to state twice.

**And a rule must be grounded in words somebody said.** The discipline is
borrowed from Google's `langextract`, which makes a model return exact source
text and then verifies it against the source rather than trusting it. Vesta now
checks that a rule's quotation appears in a real turn and refuses it otherwise.
Trimming and reformatting are fine; inventing is not.

That library was considered as a dependency and declined. Its valuable asset is
`resolver.py`'s alignment cascade, which answers *"where in this document is the
span the model quoted"* — and here the turn is already the unit, so there is no
span to locate. It would have brought pandas, numpy, google-genai and
google-cloud-storage for a problem this does not have. The idea was worth more
than the code.

**It was then measured, on a repository neither of us had been shaping.**
`~/Research/taguchi` — 859 turns, a real working history, chosen because
testing this on the repository being edited all day would prove nothing.

    gated  →   87 candidates
    ranked →  666 turns offered

A haiku agent read all 677 under the existing `vesta-rules` brief and returned
**58 standing rules**. The number that matters: **35 of them came from turns
ranked below the old cut-off**, and a hand-checked sample confirmed it —
*"'landmark' is my internal id for one of them not for public"*, a rule about
what must never be published, was discarded outright by the regex. So were
*"structure is essential for analysis"* and *"a model's self-assessment is an
invalid analysis"*.

Asked directly whether the deeper turns wasted its time, the agent said they
were where the rules about IP handling, evaluation methodology and reviewer
engagement lived, and that it would have wanted more turns rather than fewer.

Grounding was checked against the same transcripts: every quotation the agent
returned appears verbatim in a real turn. Two apparent failures during
verification turned out to be **transcription slips in the check itself** —
`that's` retyped as `that is` — which is the check working at exactly the
granularity intended.

**The run also exposed two defects, both since fixed.**

*A transcript belonged to a repository because it named it often enough.*
`_sessions_for` counted raw occurrences of the path anywhere in a file, at a
threshold of 20. The session that ran this very measurement mentioned
`~/Research/taguchi` 59 times — in tool results and assistant output, while
the user named it **zero** times — and the whole transcript was admitted as
taguchi's own history. Rules stated about one project would have been
recovered as decisions about another.

The count that decides is now *how many times the user themselves named it*,
which distinguishes working in a repository from running commands against one.
Matching a session recorded under a different launch directory still works —
that is what the feature is for, and this session is a live case of it — but it
now requires the user to have said so.

*A bare question was recorded as a rule.* Verifying the 58 by hand turned up
*"is the TPOC barred from carrying out these tasks? yes or no"* recorded as a
constraint that the TPOC may not carry them out — a rule invented from an open
question, asked precisely because the user did not know the answer.

The brief now draws the line the machinery cannot: a turn that asks and never
answers itself is not a rule, however constraint-shaped the question. The
counter-case is kept explicitly, because it is the common one — *"are the
papers called peer reviewed? … these are published, not peer reviewed, and the
title should be used"* opens with a question and then states the rule.

**What is still open.** Extraction is no longer starved, and on clean data it
offers roughly seven times what it did. Whether the rules it finds are all
*right* is a question only the user can settle, which is what adjudication is
for — and the hand-check above suggests a false positive rate worth measuring
properly rather than estimating from a sample of seven. Thirteen rules carry a
named check strategy that has never executed, which remains a separate gap from
having no strategy at all.

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

## What using it on somebody else's project turned up

The three items above were found by reading Vesta's own output on Vesta. Then
it was pointed at `v4/ontos` — a working project, not a test bed — and four
things surfaced in an afternoon that reading never would have.

**Two resolvers were wrong, and both made the survey untrustworthy.**

`calls_to_nothing` matched relative imports against **file stems only**, so a
package — a directory with an `__init__.py` — was never a module. Nine
`from ..core import Document` lines were reported as *"no such module"* while
`core/__init__.py` sat there exporting every one. That is the most alarming
thing this survey says, *"raises the moment the line runs"*, and it was wrong
about all nine. Fixing it exposed a second, latent bug: two files called
`base.py` in different packages resolved to whichever was listed first, so
imports from one were checked against the other's contents. Relative imports
now resolve the way Python resolves them — by where the import was written and
how many dots it used.

`unreachable_definitions` had careful exclusions for tests, private helpers,
methods and dynamic reach — and none for **decorators**. Sixteen FastAPI routes
in one file were reported as unreferenced; `@app.get("/health")` *is* the
reference, which is exactly why nothing calls `health()` by name. Together the
two fixes took that workspace from about forty noisy sites to eighteen real
ones.

**Both bugs punish good structure**, which is what makes them worth recording
rather than just fixing. `ontos` is a façade DSL whose `core/__init__.py`
states that consumers depend on it and nothing else; Vesta was blind to
precisely that idiom. A tool that reports well-organised code as broken is
worse than one that says nothing.

**And defects never surfaced at all.** Everything the survey found was
reachable only by typing `vesta defects` or by an agent choosing to call a
tool. Nothing in the prompt hook mentioned defects — so in ordinary use they
were invisible, however good the finders were. A tool whose value depends on
remembering its API has no value.

The remedy follows `bears`, which had already solved this for rules: raise a
finding **only when the prompt names the file it is in**. Naming
`store/filesystem.py` mentions the two swallowed failures inside it; naming a
clean file says nothing; naming no file says nothing at all. Only `clear` and
`likely` findings speak, because interrupting somebody's work with a *worth a
look* is what teaches them to skim the channel — and then the one that mattered
goes past unread too.

Two costs had to be paid down before that was usable. Surveying an unprepared
workspace took **ten seconds**, and a hook that stalls a prompt that long is
uninstalled before anybody discovers it was right; it now checks readiness
first and stays silent, in about a millisecond. And running all seven finders
to raise findings from four was a tax on every prompt — restricted to the ones
that can raise, 1.6s became 420ms.

**The lesson worth keeping** is not any of the four fixes. It is that a session
spent using Vesta on an unfamiliar real project produced more than a day spent
reading it on the project that built it. Nothing here was subtle; all of it was
invisible from the inside.

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
4. **Cost the file-level half of the schema question** — which code loads which
   schema, without modelling a schema's internals. It needs no opinion about
   what a definition is, so it cannot produce the false positives that make a
   detector untrustworthy, and it answers the question people actually ask.

The first is instrumentation rather than a feature, and that is the point: the
remaining questions cannot be answered with evidence by a tool whose whole
premise is answering with evidence. Everything else waits on it.
