# The trial

One brief, two arms, run interactively in Claude Code, measured afterwards by
the same external standard.

## Why interactive

Vesta works through hooks and slash commands inside a session. `claude -p`
loads none of that, so a non-interactive run measures something that is not the
product. Both arms are run the same way a person would run them.

## What differs between the arms

Only the plugin. Same brief, same model, same empty directory, same scoring.

- **control** — `ralph-loop`, whose stopping condition is the model stating a
  promise it was instructed not to make falsely
- **vesta** — whose stopping condition is counted: every agreed behaviour built
  and reached by a test, the tests passing, the user's rules honoured, nothing
  outstanding

## What is measured, and by what

| what | from | uses Vesta? |
|---|---|---|
| tokens, turns, tool calls, wall clock | the session's own transcript (`spent.py`) | no |
| files, lines, definitions, tests passing | the standard library (`score.py`) | no |
| defects: bare excepts, swallowed failures, dead code | the standard library (`score.py`) | no |
| does it do what was asked | exercised from outside (`probe.py`) | no |

Nothing in the scoring uses Vesta. Scoring the Vesta arm with Vesta's own
measurements would show only that a tool agrees with itself.

`probe.py` was written before either arm ran and validated both ways: 7/7
against a correct todo list, 1/7 against a broken one, with no credit for
accepting a `--tag` argument and dropping it.

## Running it

See `HOW-TO-RUN.md`.
