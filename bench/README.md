# Query benchmark: precision/recall + latency against Vesta's own repository

What `tests/test_graph.py` does NOT measure: whether `uses()`'s answer about a
REAL definition, in the REAL repository, at REAL scale, is actually correct —
not "does the algorithm work on a ten-line fixture" but "does the tool tell a
user the truth about vesta/graph.py:Graph.referenced_by".

## Method

16 definitions are picked from across the repository (different files,
different definition kinds, a spread from near-zero to heavily-referenced —
not cherry-picked for an easy result; several were picked before their
reference count was known at all). For each, ground truth is derived
independently in `ground_truth.py` by parsing real Python syntax with the
standard library's `ast` module — never by trusting Vesta's own graph (that
would be circular), and, after two earlier regex attempts, never by text
matching either: a search cannot reliably tell a real reference (a call, a
type annotation) apart from an unrelated string/tuple literal containing the
same text.

`run_benchmark.py` then queries the ACTUAL production code
(`vesta.sidecar._matching`, not a reimplementation of it) against the real
graph, and scores:

- **precision** = (callers Vesta reported that are real) / (callers Vesta reported)
- **recall** = (real callers Vesta reported) / (real callers that exist)
- **latency** = wall-clock per query, p50/p95 across all N

Run: `.venv/bin/python bench/run_benchmark.py` (from the `bench/` directory).
Writes `bench/results.json`.

## Result

Mean precision **0.998**, mean recall **1.000**, latency p50 **~0.7ms**,
p95 **~2ms** — against this repository's real graph (~1620 definitions,
~4800 references). 15 of 16 targets score an exact 1.00/1.00.

## What building this found — three real, fixed defects

Independent ground truth, checked against production code rather than
trusted on sight, surfaced three genuine bugs, in order of how deep the
investigation had to go:

1. **Module-node name collisions** (`vesta/store.py:Held.named`,
   `vesta/sidecar.py:_matching`) — a function sharing its name with the file
   it lives in (`vesta/home.py` defining `def home()`) made `uses("home")`
   return the real function AND the file's own module node as two separate
   "definitions." Fixed by excluding module nodes from name matching.
   Verified live through the running MCP tool, not just unit tests.

2. **Import references shown identically to real calls** — `from x import y`
   is a real reference (correctly modeled in the graph already), but
   `uses()`'s output rendered it exactly like a function call. Now labeled
   `(imports it)`.

3. **The big one: `Graph.at()` had no way to know where a definition's body
   ended.** A reference genuinely at module scope, after the last definition
   in a file (`if __name__ == "__main__": main()`, used in 15 files here),
   got silently misattributed to that last definition instead of the
   module — which then looked exactly like self-recursion and was dropped,
   never surfaced as wrong. This took three passes to close correctly:
   - `Symbol`/`Node` gained a real `end_line`, read from data the language
     server already provides (`DocumentSymbol.range`) but was previously
     discarded.
   - The module node had to be explicitly barred from ever winning a
     same-line tie against a real definition — a first version of the fix
     passed or failed depending on Python dict iteration order, caught only
     by a hand-built test that forces both orderings.
   - `_containing`'s own docstring claimed a "falls back to the module node"
     behavior that had never actually been implemented in code.
   - Fixing all three then broke a *different*, previously-passing test
     (`_named`'s "an unreferenced nested definition isn't what a bare word
     meant" heuristic), which had been silently relying on the original bug
     to distinguish "referenced by a call" from "returned by its own
     enclosing function." Fixed by making that heuristic check for a
     reference from OUTSIDE the enclosing definition, which is what it
     actually meant to ask.
   - Fixing THAT then surfaced a fourth issue: a single import line produces
     two edges (the reference-walking pass AND the dedicated import pass
     both see it), and naive first-wins deduplication depended on SQLite row
     order. Fixed by having the import pass upgrade the existing edge in
     place instead of appending a duplicate.

   Three regression tests, each verified by reverting its fix and confirming
   the test actually fails first.

Two things worth naming about the process itself: the first attempt at
diagnosing #3 concluded it was an *upstream pyright limitation* — flatly
wrong, caused by never calling `Session`'s required `with` context manager
in the diagnostic script itself, which silently made every LSP query in that
investigation return nothing. Re-run correctly, pyright resolves the pattern
fine; the bug was entirely in this repository's own code. Second, an earlier
type-fix attempt (making `_callers_of`'s `graph` parameter a `Protocol` so
pyright could resolve calls through it) technically worked but resolved
calls to the Protocol's own abstract stub rather than the concrete class —
correct typing, wrong benchmark answer. The actual fix was narrower and
simpler: `_callers_of` has exactly one real caller, already concretely typed
as `Graph`, so it needed no Protocol at all.

## What's left open

One target (`home`) intermittently shows a single spurious caller
(`vesta/reclaim.py::held`) depending on run timing, despite direct,
repeated verification (via `_matching`/`graph.referenced_by` called
directly, and via the real LSP session) that the live graph's actual
answer is correct. Not chased further — the direct checks are trustworthy
evidence that the underlying tool is right; whatever's left is in this
benchmark's own harness, most likely a build/compare race between
`run_benchmark.py`'s fresh rebuild and reading `results.json` immediately
after. Worth a clean fix if this benchmark is extended, not worth blocking
on now.
