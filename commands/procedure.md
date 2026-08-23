---
description: Control-flow templates recorded for this project — list, add, or validate
argument-hint: [list|add|validate]
allowed-tools: Bash(${CLAUDE_PLUGIN_ROOT}/bin/vesta-run:*)
disable-model-invocation: true
---
!`${CLAUDE_PLUGIN_ROOT}/bin/vesta-run procedure ${ARGUMENTS:-list}`

Show this verbatim. A procedure is steps and what follows each, written down
by someone who knows the work — a branch that does not say what triggers it
is refused when it is added, not accepted and left ambiguous.
