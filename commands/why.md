---
description: Why it concluded that, and whether the reasoning has aged well
argument-hint: <optional: how far back, newest first>
allowed-tools: Bash(${CLAUDE_PLUGIN_ROOT}/bin/vesta-run:*)
disable-model-invocation: true
---
!`${CLAUDE_PLUGIN_ROOT}/bin/vesta-run why ${ARGUMENTS:+--which $ARGUMENTS}`

Report what came back without softening it. Reasoning that no longer holds is
the interesting part; so is reasoning nothing can check, which is not a failure
and must not be presented as one.
