# A release's version is said once and its tag travels with the push

Agreed 2026-10-16. Behaviour does not change after this.

This is the latest of 3 agreements. Everything agreed before it was delivered and still holds — 33 behaviours in all, every one listed here.

## What it does

- ✓ a user can see every place the version is written and whether they agree, and set one number in all of them
- ✓ a plain git push carries the version's annotated tag, and is refused with the fix when the agreed version has no tag

## How it must be built

- nothing is ever pushed by Vesta; the guard only declines

## Chosen along the way

Not asked about, because they follow from the above.

- the guard lives in the clone's own .git and local config, never in the tree

## Delivered before this, and still true

Each agreement below was met in full before the next was made. Nothing in them was withdrawn.

### Named functions over a project, with the step a model performs as a primitive — reached for, checked, sequenced, judged, witnessed and counted — and Vesta's own hooks, walker, tests, contract and vocabulary made honest by using it on itself

Agreed 2026-10-15; 19 of 19 behaviour(s) met.

- ✓ a user can record a named function for a project, as a shell command or an ask, and list, show, and forget it
- ✓ an ask names its model by role and declares every input its prompt uses, or is refused
- ✓ a function whose role names no step of a recorded procedure is refused
- ✓ a criterion that checks against nothing is refused when it is written
- ✓ an agent can render a function's brief with its inputs filled, and record the output back with a verdict per checkable criterion
- ✓ an asserted criterion is reported as asserted, never as met
- ✓ a user can judge a run good or bad with a reason, and the next brief carries recent bad reasons
- ✓ a user can name the criterion a bad run got past, and see which criteria let bad runs through
- ✓ an agent is offered a recorded function at a prompt that plainly asks for what it does, once per session
- ✓ an exits criterion holds when a stated command accepts the output
- ✓ an agent can read a procedure as the briefs that perform it, in step order
- ✓ a function run leaves a witness that why reads
- ✓ a driven project is not done while a role-bearing function has no met run since the last change
- ✓ a single search of the code for a held definition is refused with the answer, and a compound command, a pipe filter, or a search over prose is let through
- ✓ build output beside a manifest and anything the root gitignore names are not indexed
- ✓ a bare word shorter than four letters, or a common word, is not injected unless spelled out
- ✓ a checkout without the sidecar extra skips the server tests with the reason
- ✓ agreeing new work keeps the delivered contract under the next, and refuses while the signed one has work outstanding
- ✓ a question about the work names the modules no attachment reaches

How it had to be built:

- no network call and no API key — an ask is a brief the host agent performs on its own inference
- criteria are a closed set of checks, each deterministic or marked asserted; no expression language
- pydantic stays the only runtime dependency
- nothing derived is written into the repository except the contract itself

### A replayable bundle per invocation: what was judged, on what basis, which of it still holds, and which parts nothing can check — such that the judging can be visualised, audited, and addressed for future runs

Agreed 2026-08-29; 12 of 12 behaviour(s) met.

- ✓ an attachment whose definition moved re-anchors itself by path and name instead of dangling, and says it was re-anchored
- ✓ an attachment records the bytes it was written about, so a later reader can tell a binding that still stands from one whose code has changed underneath it
- ✓ a judgement can be addressed across runs: it carries what it judged rather than how that looked at the time
- ✓ every judgement says what kind of thing it rests on — a structural predicate over the graph, a byte comparison, or an assertion nothing can re-evaluate
- ✓ a bundle states honestly what fraction of its own reasoning can be replayed, rather than implying all of it can
- ✓ a tool call records what was asked and what came back, so an invocation's trail can be reconstructed rather than inferred from how long it took
- ✓ an invocation is kept as one bundle: the intent that opened it, the trajectory that narrowed it, the judgements that closed it, and the commit it was taken against
- ✓ replaying a bundle against the current repository reports, per judgement, whether it still holds, no longer holds, or cannot be checked
- ✓ bundles are bounded: the most recent fifty per project are kept and older ones drop off as new ones are written
- ✓ a skill file becomes vocabulary and, where it states ordered steps, a procedure — carrying which skill each term came from
- ✓ a skill's conditions narrow a decision space, so the requirements an action is held to come from a standard written before the action was proposed
- ✓ asking what a skill requires that this repository does not name reports the difference

How it had to be built:

- no new runtime dependency — pydantic stays the only one
- no network call and no API key, as tests/test_conformance.py asserts
- nothing derived is written into the repository except the contract itself
- a judgement nothing can re-evaluate is recorded as asserted, never dressed up as derived
- no general expression language over the graph — a closed set of predicate kinds that each replay deterministically
- bundles are for audit; recomputation only where a step is already deterministic and side-effect free
