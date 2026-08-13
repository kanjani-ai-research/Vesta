---
description: What Vesta is holding on disk, and what of it is dead
argument-hint: [--reclaim]
allowed-tools: Bash(${CLAUDE_PLUGIN_ROOT}/bin/vesta-run:*)
disable-model-invocation: true
---
!`${CLAUDE_PLUGIN_ROOT}/bin/vesta-run held $ARGUMENTS`

Show this verbatim.

Vesta derives a graph, a vocabulary, rules and notes for every repository it is
used in, and keeps them under `~/.vesta`. This reports what that comes to, per
repository, biggest first.

A `✗` marks something worth removing: a repository that no longer exists, or a
graph built over a temp directory rather than a project. **Nothing is deleted
unless `--reclaim` was passed** — if they want the space back, tell them to run
`/vesta:held --reclaim`, and do not run it for them.
