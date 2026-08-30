---
description: Whether you're honing in on this change, or just going round again
argument-hint: <the work, in plain words>
allowed-tools: Bash(${CLAUDE_PLUGIN_ROOT}/bin/vesta-run:*)
disable-model-invocation: true
---
!`${CLAUDE_PLUGIN_ROOT}/bin/vesta-run honing "$ARGUMENTS"`

Show the trajectory as it came back. The numbers are the point: a run of them
that stops moving means the work is being elaborated rather than decided, and
saying so is more useful than another round of the same.

Ask again with the same wording as the work narrows — different wording is
different work, and starts over.
