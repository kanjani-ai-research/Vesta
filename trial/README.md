# The trial

One brief, two arms, the same model, measured by the same external standard.

## What differs

| | control | vesta |
|---|---|---|
| plugin | ralph-loop | vesta |
| stopping condition | the model states a promise | counted: behaviours built and tested, tests pass, rules honoured, nothing outstanding |

Everything else is held constant: the brief, the model, the permission mode,
an empty directory, and the scoring.

## What is measured

From the harness, not from either plugin:

- wall clock, turns, tokens, dollars — `claude -p --output-format json`

From `score.py`, using only the standard library:

- files, lines, definitions, tests, whether the tests pass
- defects: bare excepts, swallowed failures, unreferenced definitions

From `probe.py`, written before either arm ran:

- each behaviour in the brief, exercised from outside through whatever
  interface the arm produced

## Why the scoring uses no Vesta

Scoring the arm that ships Vesta with Vesta's own measurements would show only
that a tool agrees with itself. Every number comes from the standard library,
the tests the arm wrote, or the brief.

## Running it

```
trial/run.sh control /tmp/trial/control trial/brief.md
trial/run.sh vesta   /tmp/trial/vesta   trial/brief.md

python trial/probe.py /tmp/trial/control
python trial/score.py /tmp/trial/control /tmp/trial/control.json
```

The two arms need different plugins enabled, which is a manual step: a plugin
is enabled per user, not per invocation.
