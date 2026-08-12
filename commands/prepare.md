---
description: Start building this repository's graph, in the background
argument-hint: [path]
allowed-tools: Bash(${CLAUDE_PLUGIN_ROOT}/bin/vesta-run:*)
disable-model-invocation: true
---
!`${CLAUDE_PLUGIN_ROOT}/bin/vesta-run status --prepare ${ARGUMENTS:-.}`

Report what this says. It runs in the background and does not block the session.
