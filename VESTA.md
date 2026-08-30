# A replayable bundle per invocation: what was judged, on what basis, which of it still holds, and which parts nothing can check — such that the judging can be visualised, audited, and addressed for future runs

Agreed 2026-08-29. Behaviour does not change after this.

## What it does

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

## How it must be built

- no new runtime dependency — pydantic stays the only one
- no network call and no API key, as tests/test_conformance.py asserts
- nothing derived is written into the repository except the contract itself
- a judgement nothing can re-evaluate is recorded as asserted, never dressed up as derived
- no general expression language over the graph — a closed set of predicate kinds that each replay deterministically
- bundles are for audit; recomputation only where a step is already deterministic and side-effect free

## Also noted

Said, and not written as behaviour — nothing here names
what it does or who for, so there is nothing to build
against. Say it as a behaviour and it becomes one.

- a local frontend for ontology editing and management — deferred until replay shows what actually needs editing
- ontology intersection — union and diff first; intersection needs a synonym relation that does not exist yet (open-questions.md §2)
- symbolic execution of model-derived bindings — out of reach by construction, and marked asserted instead
- Behaviour 10 is deliberately narrowed to vocabulary and authority, not procedure: numbered steps appear in about twenty of thirty-one shipped skills but not reliably under any heading — one ships 22 steps and no workflow heading at all — so deriving a Procedure would invent the structure procedure.py refuses at write time.
- A normative specification for the witness record lives at spec/witness.md, separate from doc/ which holds working notes. It specifies four blame attributions (inadequate standard, insufficient narrowing, sound-but-wrong, degraded environment), ten required fields, six checks, and three conformance levels. Several required fields and all of levels 2 and 3 are specified but not implemented; the document marks these throughout and must not be read as describing running code.

## Chosen along the way

Not asked about, because they follow from the above.

- bundles live under ~/.vesta/bundles, keyed by project the way every other holding is (home.kept_at)
- Witness gains identity and basis rather than a parallel type being introduced beside it
- _record's existing **rest carries the new fields, so 17 tool call sites stay untouched
- the ring buffer follows driving.readings — trim on write, not by sweep
- existing attachments are not migrated; they re-derive on the next vesta-domain run
- authority.Standing is reused for byte-basis judgements rather than a second currency check being written
