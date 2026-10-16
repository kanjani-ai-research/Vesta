---
description: The named functions of this project — list, show, define, brief, record, judge
argument-hint: [list|show <name>|brief <name> --input k=v]
allowed-tools: Bash(${CLAUDE_PLUGIN_ROOT}/bin/vesta-run:*)
---
!`${CLAUDE_PLUGIN_ROOT}/bin/vesta-run function ${ARGUMENTS:-list}`

Show this verbatim. A function is one thing done to this project the same way
each time: a shell `command`, or an `ask` — a step a model performs. Vesta
runs neither. It keeps the definition, renders the brief, and records what
came back.

**Performing an ask.** Run `vesta function brief <name> --input k=v …`. It
prints the model, the system prompt, the filled prompt, and the criteria.
Spawn a subagent on that model with exactly that system prompt and prompt,
save its output to a file, and run
`${CLAUDE_PLUGIN_ROOT}/bin/vesta-run function done <name> --output-file <path> --input k=v …`.
Show the verdicts. A criterion marked `?` is asserted — nothing can check it,
and you say so rather than reporting it met.

**Defining one.** When the user describes a step a model should take, write
the system prompt yourself — role, constraints, the shape of a good answer —
and declare every `{input}` the prompt uses. Build the JSON:
`{"name", "about", "inputs": [...], "ask": {"model": "haiku|sonnet|opus",
"system", "prompt"}, "criteria": [{"says", "check":
"matches|contains|nonempty|tests|asserted", "pattern"}], "role": {"procedure",
"step"}}` (a `command` function has `"command": {"run": "..."}` instead of
`ask`; `role` is optional and must name a step `/vesta:procedure` lists).
Then run `${CLAUDE_PLUGIN_ROOT}/bin/vesta-run function add --json '<the
JSON>'` yourself. If it names a validation error, fix the JSON and try again
rather than asking the user to.

**Judging.** When the user says a run was wrong, record why:
`${CLAUDE_PLUGIN_ROOT}/bin/vesta-run function feedback <name> --bad --why '<their reason>'`.
The next brief for that function carries it.
