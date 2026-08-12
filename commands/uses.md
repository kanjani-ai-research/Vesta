---
description: Where a definition is, what refers to it, and what it refers to
argument-hint: <name>
allowed-tools: Bash(${CLAUDE_PLUGIN_ROOT}/bin/vesta-run:*)
disable-model-invocation: true
---
!`${CLAUDE_PLUGIN_ROOT}/bin/vesta-run uses "$ARGUMENTS"`

Show this verbatim. These references are resolved, not matched by name.
