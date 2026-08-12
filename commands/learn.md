---
description: Confirm which of your corrections are standing rules for this project
allowed-tools: Bash(${CLAUDE_PLUGIN_ROOT}/bin/vesta-run:*)
---
!`${CLAUDE_PLUGIN_ROOT}/bin/vesta-run learn`

Vesta recovered these candidates from what this user told agents in this
project. A passing remark and a standing decision look identical in a
transcript, and only they know which is which.

If the `learn` MCP tool is available, call it now — it asks them directly,
one candidate at a time, and records each answer. Otherwise show the candidates
above and ask which are standing rules, then record each answer with
`${CLAUDE_PLUGIN_ROOT}/bin/vesta-run learn --text '<candidate>' --verdict rule|note|lapsed`.

Ask about at most five. Do not guess a verdict on their behalf.
