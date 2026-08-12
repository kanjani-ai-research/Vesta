---
description: Things in this repository worth fixing, found without being asked
argument-hint: [how many to show]
allowed-tools: Bash(${CLAUDE_PLUGIN_ROOT}/bin/vesta-run:*)
disable-model-invocation: true
---
!`${CLAUDE_PLUGIN_ROOT}/bin/vesta-run defects --show ${ARGUMENTS:-5}`

Show these verbatim. Do not fix anything unless the user asks.
