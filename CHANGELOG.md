# Changelog

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
