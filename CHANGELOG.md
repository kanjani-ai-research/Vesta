# Changelog

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
