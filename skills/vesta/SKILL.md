---
name: vesta
description: Understand an unfamiliar repository, find what is worth fixing in it, or recall what its user has already decided. Use when asked what a codebase does, where some kind of work happens in it, what a change would affect, what to clean up or improve, why something is done a particular way, or when starting work in a repository you have not seen before.
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
