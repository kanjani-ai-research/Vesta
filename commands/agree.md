---
description: Agree to what Vesta will build, and start building it
allowed-tools: Bash(${CLAUDE_PLUGIN_ROOT}/bin/vesta-run:*)
---
!`${CLAUDE_PLUGIN_ROOT}/bin/vesta-run contract --sign`

Show this verbatim, then build what was agreed.

The session will not end while anything is outstanding — behaviours not built
or not reached by a test, tests not passing, defects found. Those are counted,
not judged. Work through them rather than reporting the work finished.
