# Changelog

## 0.8.5

**A test is shown to run on its data before the whole suite runs.** `vesta
sample` runs each test on a few records — the first N parametrized cases, and
`VESTA_SAMPLE=N` for a test that walks its own rows — and stops at the first
test that cannot run. What is measured is whether a test reaches a verdict,
not which one: a failing assertion has still run on the data, an error before
it could assert has not, and the answer to that is changing the test, not
running more of it. Kept per test file against its contents, so an edit sends
it back; a sample cut off by its time limit keeps what finished and carries
on from there. Until every file has run, a full `pytest` in the shell is
refused with where each file stands, and the drive loop samples before it
runs the suite. Where Vesta cannot start a sample at all, nothing is held
back.

**A turn the API cut short is noted, not mistaken for a finished one.** While
the host waits on the API — a timeout, an overload, a rate limit being retried
— no hook runs, and when the retries run out the turn ends with `StopFailure`,
which nothing here listened for. The graph was not caught up, a driven loop
ended without a word, and the next turn picked up half-done work as if it were
fresh. A `StopFailure` hook now keeps a note of what failed, when, how many
times running, and whether a loop was in flight, and catches the graph up; the
next prompt is told once — check the working tree before redoing anything,
take smaller steps after an output-limit cut, or stop and tell the user when
waiting will not fix it. The interrupted turn is not counted against a loop.

## 0.8.1

**A push carries the version's tag, or does not happen.** Two releases went
out with their tags still on one machine, because a plain `git push` carries
no lightweight tag and nothing said so. `vesta version --tag` now cuts an
annotated tag, which `push.followTags` carries with whatever is pushed; a
lightweight tag of the same name is re-made annotated at the same commit.
`vesta version --guard` installs a private pre-push hook in the repository's
own `.git` and turns `push.followTags` on, so a plain push brings the tag and
a push of a branch whose agreed version has no tag, a lightweight one, or one
on a commit not being pushed is refused with the command that fixes it. The
hook changes nothing in the tree, adds no refs, and never pushes: what reaches
a remote stays the author's act.

## 0.8.0

**A function is offered at the prompt that asks for it.** The primitive is
only worth having if it is reached for, and an agent reaches for nothing it
does not know exists. The inject hook now crosses a prompt into the functions
recorded for the project — two shared stems, or the name typed out — and
offers the brief once per session per function, as a rule in doubt is offered.

**A command that accepts the output is a check.** Most of what was asserted
is a command somebody could have run: parses as JSON, compiles, the linter
accepts it. An `exits` criterion runs a stated shell line in the project with
the output on stdin and holds on exit zero. A command that cannot run is
reported as unknown, never as the output being wrong.

**A procedure reads as the briefs that perform it.** `vesta function pipeline
<procedure>` walks the recorded steps in order — starts first, continuations
before branches, isolated steps last — and shows each with the function that
performs it, its criteria, what it was last judged bad for, and the brief to
run, or the plain fact that nothing recorded performs it.

**Feedback names the criterion a bad run got past.** `--criterion` names one
of the function's own; a requirement it never stated is a change to the
function, not feedback on a run. The ledger counts them: an asserted criterion
named repeatedly is the one worth turning into a check, and a checked one
named is a check that is wrong. The lesson carried into the next brief names
it too.

**A function run leaves a witness.** Written in the record's shape where every
other invocation's is kept, so `why` reads it: each checkable criterion a
finding, the asserted ones counted as read because that is what they are, and
the function's definition as the standard by name and digest. No trajectory is
invented — a run narrows nothing, and the record leaves those fields empty.

**Driving counts the steps a function performs.** A fifth completion
condition: every function that performs a step of a recorded procedure has a
run whose checkable criteria all held, taken since the project last changed.
A driven project can no longer finish with a declared step never having run.

And six things that touched every session, found by using Vesta on itself:

**The search hook refuses one search of the code, and nothing else.** It
denied a `sed` reading one file because a `grep` three commands later named a
definition, denied `ls | grep` because the filter word was a definition, and
denied searches of `.gitignore`, `plugin.json` and a markdown file because the
word happened to be a name. A compound command does other work; a search that
is not first in its pipeline filters output already in hand; a search over
prose or data is about nothing the graph holds. Each is let through now, and
what is refused is the one case the graph answers better: a single search,
first in its pipeline, over source or over the tree.

**Build output is not the project.** A test run's setuptools output under
`build/` was indexed as source and doubled every definition in the package.
The walker now honours the root `.gitignore` — the one list of "not mine" that
is right for every repository is the one its author wrote — and skips `build/`
and `dist/` beside a manifest, where they are what the build tool wrote rather
than somebody's own directory of build scripts.

**Ordinary English is not a definition.** `one`, `on`, `id`, `everything`,
`apply` and a sentence-initial `Run` were each injected as definitions worth
knowing about, one of them on every prompt for two hundred prompts running —
the tax on every prompt the inject hook exists to avoid. A bare name shorter
than four letters never qualifies, a common word is compared without case, a
tail taken from sentence punctuation is not a qualified name, and the list of
common words grew by what this session typed. Spelling a name out still
reaches it.

**A checkout without the sidecar extra skips six tests, with the reason.**
They start the server, and a server that needs `mcp` describes the
environment rather than the code when `mcp` is absent. Red for a missing
optional dependency is red nobody acts on.

**The next contract keeps the last.** Agreeing new work overwrote the signed,
delivered contract with the next draft, and the record of what had been built
went with it — which is how two releases of Vesta went out beside its own
contract rather than through it. A signed contract with work outstanding is
refused as a replacement; a delivered one is carried under the next, whole,
and `VESTA.md` lists what was agreed before and met. Vesta's own contract for
0.7 and 0.8 is recorded this way.

**A term's id comes from what it says.** It came from Python's `hash()`,
which is salted per process, so every derivation gave every term a new id and
every attachment written against the last derivation pointed at nothing — 508
of 558 on this repository, silently. Ids are now a digest of the term's kind
and label, and a derivation re-points any attachment whose term id is gone at
the term that carries its label, which `Attachment.label` was recorded for.
A term the author removes leaves its attachments where they are.

**One version, said once.** `vesta version` finds every place a version is
written — the package metadata, the plugin manifest, a package's
`__version__`, the changelog's latest heading — and says whether they agree,
exiting non-zero when they do not. `--set` writes the number into each of
them and turns an "Unreleased" heading into it; `--tag` cuts the local tag in
the repository's own shape and never pushes. Vesta's own three version
strings had disagreed for seven releases.

**A new version repairs what the last one wrote.** The first time a new
version of Vesta runs, as a command or as the sidecar, it puts every held
record back in step — today, pointing attachments at the term that now
carries their label — and marks the version so it costs one pass per update.
`vesta held --repair` does the same on demand, with `--dry` to look first.
Nothing is deleted: a claim under a word the vocabulary dropped is kept and
counted, not thrown away.

**The agents find the plugin wherever it is installed.** Their fallback
launcher path named a `0.1.0` directory that has not existed since the first
release, so an agent run without `CLAUDE_PLUGIN_ROOT` found nothing and
recorded nothing. The fallback now takes the newest installed copy, whatever
marketplace and version it came from. And `vesta.__version__`, which said
0.1.0 for seven releases, is held equal to the package and plugin versions by
a test.

**A vocabulary that has fallen behind says which files it is missing.** The
domain agent ran once, the project grew, and every module since was named by
nothing; nothing triggered a re-run on any repository. `does` now names the
modules no attachment reaches, on a hit as well as a miss, and the inject hook
says so once per session on a question about the work, so the agent re-reads
exactly those files.

## 0.7.1

**The version catches up to the code.** 0.7.0 was pushed with the package
and plugin manifest still reading 0.6.2 and no entry here. Nothing in the
code changed between the two; this release is the changelog below, the
`pyproject.toml` version, and the plugin manifest, all saying the same thing.

## 0.7.0

**A project's work now has names, and a model's step is a primitive.** A
procedure said what order the work goes in and the ontology said what it is
called; neither said how any of it is done. `vesta function` keeps that: one
named thing done to the project the same way each time, listed, shown,
defined, and forgotten from the CLI, read back over the sidecar's `functions`
tool, and placed in a pipeline by naming which step of which recorded
procedure it performs — a role that names no recorded step is refused when
written, not left pointing nowhere.

**An ask is a brief the host performs, never a call Vesta makes.** The step
only a model can take — a model by role, a system prompt written by the
agent that defined the function rather than by whoever calls it, a prompt
template with declared inputs, and success criteria stated before it runs —
is rendered by `vesta function brief` and performed on the host's own
inference, the same seam every other judgement in Vesta crosses. No key is
held and nothing reaches a network, as conformance continues to assert.
`vesta function done` takes the output back, checks what can be checked,
and keeps a digest rather than the prose.

**Criteria are a closed set, and the ones nothing can check say so.** A
criterion is `matches`, `contains`, `nonempty`, `tests`, or `asserted`. A
`matches` or `contains` with nothing to look for is refused at write time,
for the reason a branch without a condition is; an `asserted` criterion is
reported as asserted, never as met.

**Feedback is a ledger, and reinforcement is its smallest honest use.** A
run can be judged good or bad with a reason, and the next brief for the same
function carries the recent reasons it was judged bad. Rewriting the prompt
from that is a judgement, and judgement stays the agent's.

## 0.6.2

**One mode: a committed conclusion is earned by dominance.** The judgement
seam's calibration asks the evaluator to score every candidate conclusion on
its own merits — committing without stated support is a failure mode, and a
stated contradiction is decisive evidence — and `vesta.bound.conclude`
decides what the scores earn: a committed conclusion must beat every
alternative strictly by a margin, or the conclusion is that the record does
not decide. Nearness is itself the signal; the measured wrong commitments
sat at leads of exactly the margin, so the boundary belongs to caution.

**The region informs; it never decides.** Guidance may re-rank, but where a
demotion would change which candidate wins, the region is overriding the
evidence — and every measured occurrence of that flip was wrong. The
evidence's winner stands, and the defiance is returned as a recorded fact,
the out-of-region-survivor signal the witness already carries.

## 0.6.1

**A word form is no longer a different word.** The crossing from a user's
words to the vocabulary's matched exact tokens, so "check the balances" found
nothing in a repository whose label says "read an account balance" — the most
ordinary phrasing there is, treated as foreign. Every matched surface (query
phrases, term labels, identifier words) now passes through one deterministic
stemmer, symmetrically, so plurals and verb forms land on the same token;
stems stay internal and nothing displayed changes. And a phrase that genuinely
misses now answers with the vocabulary's own names instead of a term count —
the reader of that answer is a model with the question still in hand, and
given the names it can cross in one step and ask again. The matcher still
decides; the reader only translates.

## 0.6.0

**A decision now leaves a witness.** One compact record per invocation — what
was asked, how the space of candidates contracted, which checks held, and the
digests binding it to the specification, vocabulary, and code it ran against —
kept in place of the reasoning chain it summarises: 4.2kb where retaining every
judgement cost 303kb. `spec/witness.md` is the format, with its checks, its
conformance levels, and its stated limits; `/vesta:why` walks the record back
and says whether the reasoning has aged well.

**The narrowing is guided, and guidance may only demote.** Before a narrowing
runs, the active specification predicts where the work belongs; the narrowing
is steered toward that region, every override is recorded at the step it
happened, and neither the specification's prediction nor a model's judgement
may ever remove a candidate — only evidence computed from the code may. Zero
interventions means the specification and the code agreed; the friction figure
says how hard they fought. `/vesta:honing` is the surface.

**Skills are read as authorities.** A SKILL.md — one file, a folder of them,
anywhere — becomes vocabulary with provenance; the body is never mined for
structure, because the format guarantees none. Three skills sharing a name are
three authorities, kept apart by content digest; measured on real plugins,
identity by name silently discarded two of three.

**Bindings survive the code moving.** An attachment now carries the path, name,
and a hash of the region it was written about, so a definition shifted by an
edit re-anchors instead of dangling — 68% of this repository's own map had
rotted silently before this — and a claim can say whether the bytes it
described are still the bytes that are there.

**Tools got names a person would say.** `does`, `means`, `touches`, `uses` are
joined by `honing`, `why`, `noted`, and `bears` — `declare` and `bears_on` are
gone, and this is a breaking release for anything that called them. The domain
agent also stopped being offered an eighty-definition ceiling that left seven
of eight definitions unbindable on an ordinary repository, and an ontology
that predates its own code now says so in the empty answer instead of a log
nobody reads.

## 0.5.0

**A definition's own body had no end, so a reference past it landed on the
wrong one.** `Graph.at` picked whichever definition started closest before a
line, with nothing bounding how far its territory ran — so a reference
genuinely at module scope, after the last definition in a file (the ordinary
`if __name__ == "__main__": main()` shape), was silently attributed to that
last definition instead of the module. The misattribution then looked
exactly like a function calling itself, which is filtered as noise, so the
edge was simply dropped rather than ever reported as wrong: `uses("main")`
on a file whose only real caller was its own `__main__` guard said "referred
to by 0." Fixed by reading the body range a language server already reports
(`DocumentSymbol.range`, not just the name's own position) and bounding by
it; a definition without one falls back to the next definition's own start.
Getting this right took four passes, each catching what the last one
missed — a tie between a real definition and its file's own module node
depending on Python dict ordering; a docstring's own claimed fallback that
had never actually been implemented; a heuristic elsewhere that had been
quietly relying on the original bug to work; a single import line producing
two edges once the first three were fixed. Three regression tests, each
checked against a real, running language server, and each confirmed to fail
first against the unfixed code.

**A name shared with its own file was two colliding "definitions."** Every
`.py` file gets a module node named after the file, so a function called
`home` living in `home.py` collided with the file's own node — `uses("home")`
returned the real function and the file itself as separate hits, the
second's "callers" actually being every file that merely imports it, shown
with no way to tell that apart from a real call. Fixed at both places a name
lookup happens (the indexed store and the in-memory fallback); a real
`from x import y` is now labeled `(imports it)` rather than looking
identical to a call three lines below it.

**A query benchmark now exists and runs clean.** `bench/` derives ground
truth for a spread of real definitions in this repository independently of
Vesta's own graph — by parsing Python syntax directly, never by trusting the
tool being measured — and checks `uses()`'s actual production answers
against it. Currently: mean precision 0.998, mean recall 1.000. Building it
is what found both defects above.

## 0.4.0

**A swept slash command was checked against what it does, not just whether
it runs.** Five did not do what they said. `does` went silent — not empty,
silent — when a phrase matched real attachments whose code had since moved,
returning a bare header with nothing under it; it now says so. `status` on a
path that does not exist read identically to a project nobody has built yet,
sending a user to `--prepare` a build that could never succeed; the two are
distinguished now. `contract` answered "nothing has been agreed" — a
complete, correct answer — and then exited 1 for it, which looks like a
failure to anything checking the exit code; it exits 0. `learn` promised "at
most five" and showed up to ten, because two separate lists were each capped
on their own rather than together. And `decided` cut rule text off mid-word
with nothing marking that anything had been removed — fixed at the root,
with one truncation helper now used everywhere text is shown cut short.

## 0.3.0

**A module is a definition now, not a blind spot.** The graph found a
definition's references by asking a language server about the definition —
which finds every `from x import y`, because `y` is a real definition with a
real position, but leaves a bare `import x` with nowhere to land: no request
in the protocol ever reports an import statement, so there was no position to
resolve and the reference simply vanished. Every file now gets its own module
node, and its imports are resolved the same way every other edge in the graph
is — through the server, not by matching names — so `import x` and `from x
import y` both produce an edge, and produce a *different* one: the first
reaches the module, the second reaches the symbol inside it. Python only, for
now; the other six languages still resolve everything else in full.

## 0.2.0

**Vesta is used rather than offered.** A `PreToolUse` hook refuses a search the
graph already answers and returns the resolved answer in its place — the agent
does not get to grep, and does not need to. Only where the graph genuinely
holds the definition; a search for a comment, a string, or anything Vesta does
not know runs untouched.

**The graph is current whenever Vesta is active.** Ready now means current
rather than merely present, the staleness fingerprint costs 8ms instead of
3.6s, and the turn ending refreshes the graph while nobody is waiting. Three
places had been trading correctness for a cost that no longer existed, and a
fourth — one-second mtime resolution — could not see an edit that kept a file
the same length.

**A graph per path, composed upward.** A directory of thirteen projects was one
graph taking 73 seconds to rebuild because one file in one of them changed. Now
each project has its own, and a question about the directory composes them: 9
seconds for the project that moved, nothing for the eleven that did not.

**It says a thing once.** Anything raised unasked is raised once per session
per subject. The same file again is silent; a different file speaks; a new
session speaks.

**Nothing hidden is ever read** — no dotfile, no dot-directory — and a banlist
covers the visible dependency directories across languages. A repository was
62 source files beside a `venv/` holding 13,613, and all of them were walked.

**Also:** a graph that resolved nothing is no longer cached as an empty
repository; packages and decorated definitions resolve, so live imports and
FastAPI routes are no longer reported as broken; rules are recorded against
words the user actually said, verified against the transcript; 270 lines of
dead code removed; Apache 2.0.

## 0.1.0

First release.
