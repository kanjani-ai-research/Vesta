---
description: Whether Vesta can answer about this repository yet, and what it holds
argument-hint: [path]
allowed-tools: Bash(${CLAUDE_PLUGIN_ROOT}/bin/vesta-run:*)
disable-model-invocation: true
---
!`${CLAUDE_PLUGIN_ROOT}/bin/vesta-run status ${ARGUMENTS:-.}`

Show this verbatim. If it says nothing is built, tell them `/vesta:prepare` starts it.
