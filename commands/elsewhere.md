---
description: How another project does a kind of work
argument-hint: <what the work is> --in <project name or path>
allowed-tools: Bash(${CLAUDE_PLUGIN_ROOT}/bin/vesta-run:*)
disable-model-invocation: true
---
!`${CLAUDE_PLUGIN_ROOT}/bin/vesta-run elsewhere $ARGUMENTS`

Show this verbatim. The project under works stays authoritative; the other is
consulted, not merged. If the project name was ambiguous, the answer says so and
asks for a path — pass it as `--in /path/to/project`.
