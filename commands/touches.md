---
description: What a change to these files affects, and which tests cover it
argument-hint: <file> [file...]
allowed-tools: Bash(${CLAUDE_PLUGIN_ROOT}/bin/vesta-run:*)
disable-model-invocation: true
---
!`${CLAUDE_PLUGIN_ROOT}/bin/vesta-run touches $ARGUMENTS`

Show this verbatim, including any warning that the set may be short.
