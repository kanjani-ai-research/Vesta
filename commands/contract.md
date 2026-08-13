---
description: What was agreed to be built, and whether it has been
allowed-tools: Bash(${CLAUDE_PLUGIN_ROOT}/bin/vesta-run:*)
---
!`${CLAUDE_PLUGIN_ROOT}/bin/vesta-run contract`

Show this verbatim.

If it says nothing has been agreed and the user wants something built, run the
`vesta-spec` subagent to turn what they asked for into a contract, show them
what it produced, and wait for them to agree. Do not begin building before they
have.
