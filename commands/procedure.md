---
description: Control-flow templates recorded for this project — list, add, or validate
argument-hint: [list|validate]
allowed-tools: Bash(${CLAUDE_PLUGIN_ROOT}/bin/vesta-run:*)
---
!`${CLAUDE_PLUGIN_ROOT}/bin/vesta-run procedure ${ARGUMENTS:-list}`

Show this verbatim. A procedure is steps and what follows each, written down
by someone who knows the work — a branch that does not say what triggers it
is refused when it is added, not accepted and left ambiguous.

To record a new one, build the JSON yourself — `{"id", "label", "steps":
[{"id", "label", "kind"}], "thens": [{"source", "target", "outcome",
"when"}]}`, outcome one of continues/branches/exits/fails/retries/defers,
`when` required for branches/retries — then run
`${CLAUDE_PLUGIN_ROOT}/bin/vesta-run procedure add --json '<the JSON>'`
yourself. Show the result; if it names a validation error, fix the JSON and
try again rather than asking the user to.
