---
description: Run each test on a few records, and know whether a full run is worth it
argument-hint: [test paths]
allowed-tools: Bash(${CLAUDE_PLUGIN_ROOT}/bin/vesta-run:*)
---
!`${CLAUDE_PLUGIN_ROOT}/bin/vesta-run sample $ARGUMENTS`

Show this verbatim.

What is measured is whether each test can run on its data, not whether it
passes. A test that failed its assertion on the sample has run; a test that
could not run needs changing so it does — not a full run to find out more.
Fix those first, sample again, and run the whole suite only once it says a
full run is warranted.
