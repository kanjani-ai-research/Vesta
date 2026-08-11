# Measuring whether acquired theory helps

Draft. Nothing here has been run.

The claim to be tested is narrow and should stay narrow: **for tasks whose hard
part is not in the repository, an agent given acquired theory produces better
work than the same agent without it, and does not spend more tokens to do it.**

Everything else — better retrieval than a framework's built-ins, general codegen
improvement — is out of scope, unmeasured, and probably false.

## What is being compared

One agent, one task set, two arms:

- **control** — the framework as it ships
- **treatment** — the same, plus one tool: `consult(question) → cited passages`

Additive, so the arms differ by exactly one thing. Replacing a framework's own
retrieval would confound the comparison with a second change and put Vesta in
competition with a mature, tuned system on its home ground.

## The hard part is the grader, not the plumbing

Token counts are easy to capture. "Quality" is not, and a badly chosen metric
produces a confident number that means nothing.

A task qualifies only if:

1. **The theory is load-bearing.** If a competent implementation without any
   literature passes, the task measures nothing. The test is whether a wrong
   *approach* — not a wrong line — fails it.
2. **Success is machine-checkable.** A property test, a known-answer set, a
   metamorphic relation. Not a human reading diffs, and not a model grading
   output, which imports the very knowledge gap under test.
3. **The failure is a rewrite, not a typo.** The cost being claimed is the cost
   of learning the theory late.

Candidates, drawn from cases where this actually happened during development:

| task | grader | theory that was load-bearing |
|---|---|---|
| t-way covering array generator | verify every t-tuple is covered; count rows against known optima | greedy vs. IPOG vs. algebraic construction |
| conservative-extension check over two ontologies | known-answer pairs where the answer is established | inseparability; why entailment-difference is not the same test |
| deduplicate near-identical generated items | held-out set with known duplicate pairs; must keep contrastive pairs | why one fingerprint over the whole item destroys minimal pairs |

Each of these is a case where a plausible-looking approach is wrong in a way
that only shows up under a property test.

## What is recorded per run

- output tokens, input tokens, cached tokens — per arm, per task
- wall clock
- whether the grader passed
- number of edit cycles before passing (a proxy for rework)
- for the treatment arm: whether `consult` was called at all, and what it returned

The last one matters. A treatment arm that never calls the tool is a control
arm, and reporting it as treatment would inflate the result.

## What would falsify the claim

- treatment passes no more often than control
- treatment passes more often but spends more total tokens, with no task where
  control fails outright
- treatment's wins disappear when the corpus is replaced with an *unrelated*
  corpus — which would mean the gain came from being prompted to think, not from
  the theory. **This arm is required, not optional.** Without it a positive
  result is unattributable.

## Sample size

Per-task variance in codegen is high. A handful of tasks will not separate
anything. Tens of runs per arm per task is the realistic floor, which is a real
cost in time and tokens and should be budgeted before starting rather than
discovered halfway.

## Known threats

- **Task selection.** Tasks chosen by whoever built the corpus will favour the
  corpus. Tasks should be fixed and written down before any corpus is built.
- **Corpus staleness.** A corpus built today about a task written today is a
  best case, not a typical one.
- **The grader is the theory.** If the property test encodes the same insight
  the theory supplies, the test rewards knowing the test. Graders should be
  derived from the problem statement, not from the papers.
