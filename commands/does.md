---
description: Where a kind of work is done here, asked in ordinary words
argument-hint: <what the work is, e.g. retrying a failed request>
allowed-tools: Bash(${CLAUDE_PLUGIN_ROOT}/bin/vesta-run:*)
disable-model-invocation: true
---
!`${CLAUDE_PLUGIN_ROOT}/bin/vesta-run does "$ARGUMENTS"`

Show these definitions verbatim. If nothing was found, say so plainly and
suggest naming the work differently — do not guess at an answer or go reading
files to invent one.
