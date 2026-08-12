---
name: vesta
description: Understand an unfamiliar repository, find what is worth fixing in it, recall what its user has already decided, and record a rule the moment they state one. Use when asked what a codebase does, where some kind of work happens in it, what a change would affect, what to clean up or improve, why something is done a particular way, when starting work in a repository you have not seen before, and whenever the user states a standing constraint on the code — "every module must open with a docstring", "one .env for the whole project", "never a bare except" — which must be recorded as they say it rather than looked up.
tools: Read, Grep, Glob, Bash
---

# Vesta

Vesta answers structural questions about a repository from a resolved graph of
what refers to what, together with what earlier sessions worked out about it.

## Ask before reading

These cost hundreds of tokens and answer in one call what costs thousands to
establish by reading:

- **`shape`** — what a repository is made of, before opening anything
- **`uses`** — where a definition is and what refers to it, resolved rather than
  matched, so four methods sharing a name stay four methods
- **`touches`** — what a change to some files affects, and which tests cover it
- **`does`** — where a kind of work happens, asked in ordinary words: "impact
  analysis", "deduplicating submissions". Reaches code sharing no vocabulary
  with the question.
- **`means`** — what a definition is for, and what else does the same kind of
  work even when nothing calls between them
- **`known`** — what earlier sessions worked out about a definition, with
  whether the code has moved since
- **`defects`** — what is worth fixing, found without being asked
- **`decided`** — rules this repository's user has stated, and whether the code
  still honours them

## When the user states a rule, record it

The most valuable thing Vesta holds is what this project's user has already
decided — and the moment to capture that is when they say it, not later. A user
who has to run a command to record a rule records nothing.

So when the user states a standing constraint in the course of ordinary work,
call **`declare`** with it, in their own words. Then say in one line that it was
recorded, and carry on with what they actually asked for.

What counts:

- **A constraint on the code, not on this turn.** "one .env for the whole of
  v3" is standing; "don't edit anything yet" expires with the turn.
- **Stated, not mused.** "we should probably pin deps" is thinking aloud;
  "deps must be pinned" is a decision. If it invites an answer, it is not a
  rule yet.
- **Theirs, not yours.** Record what the user said. Do not record a conclusion
  you reached, or a rule you inferred from the code — Vesta already derives
  those, and a rule the user never stated has nobody behind it.

Record it once. `declare` is safe to call again with the same words — it
replaces rather than duplicates — but announcing it twice is noise.

Do not interrupt to confirm. Recording is cheap and reversible: `decided`
reviews everything and any rule can be set aside later. Asking permission for
each one makes the capture cost more than the rule is worth.

## Before changing files, ask what bears on them

Call **`bears_on`** with the files you are about to change, alongside `touches`.
It answers with nothing at all unless a rule the user set covers this work *and*
the code no longer matches it — uncommon, and exactly when they want to know.

When it does answer, put the question to them and wait. Whether their own rule
still stands is theirs to say, not yours. It may also report rules that govern
the work and could not be checked: mention those once and carry on, because
there is nothing useful to do about them mid-edit.

## When a tool says it has nothing

It will name the agent that fixes it. Run that agent — they are the expensive,
one-time half:

- **`vesta-domain`** names the work a repository performs and binds its
  definitions to those names. Needed before `does` and `means` can answer.
- **`vesta-rules`** recovers what the user has already decided, from what they
  said in earlier sessions.
- **`vesta-defects`** derives finders for the kinds of defect this project's own
  users have pointed at.

A repository Vesta has not seen prepares itself in the background. It never
blocks; it answers when it can and says so when it cannot.

## What it will not tell you

Vesta reports what it could not resolve rather than implying a complete answer.
A propagation set says which references it could not follow; a recorded account
says whether the lines it describes have changed since. Take the caveats
seriously — they are the difference between a claim and a guess.
