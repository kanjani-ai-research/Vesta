---
description: What you have decided in this project, and whether the code honours it
argument-hint: [--check]
allowed-tools: Bash(${CLAUDE_PLUGIN_ROOT}/bin/vesta-run:*)
disable-model-invocation: true
---
!`${CLAUDE_PLUGIN_ROOT}/bin/vesta-run decided $ARGUMENTS`

Show this verbatim. Rules are recovered from your own corrections in this
project. If it reports rules nothing can check, `/vesta:learn` is how they
become checkable.
