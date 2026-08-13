---
description: Learn Vesta a page at a time, on your own repository
argument-hint: [chapter 1-5]
allowed-tools: Bash(${CLAUDE_PLUGIN_ROOT}/bin/vesta-run:*), AskUserQuestion
disable-model-invocation: true
---
!`${CLAUDE_PLUGIN_ROOT}/bin/vesta-run tutorial $ARGUMENTS`

Follow the instruction above exactly.

Draw the page with **AskUserQuestion**, one question, with the options given
verbatim — labels, descriptions and previews unchanged. The preview is the
lesson: it renders in a pane beside the list, and the user reads it by arrowing
down before they pick anything. Summarising it destroys the thing.

Do not explain the page before or after drawing it, and do not add an option of
your own. When they pick, run the next chapter and draw it the same way.
