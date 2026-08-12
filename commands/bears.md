---
description: Whether a rule you set is in doubt for these files
argument-hint: <file> [file...]
allowed-tools: Bash(${CLAUDE_PLUGIN_ROOT}/bin/vesta-run:*)
---
!`${CLAUDE_PLUGIN_ROOT}/bin/vesta-run bears $ARGUMENTS`

Show this verbatim. If a rule is raised, put the question to the user and wait —
do not decide on their behalf whether their own rule still stands.
