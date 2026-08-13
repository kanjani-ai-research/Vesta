---
description: Run until the agreed work is done, and know when that is
argument-hint: [on|off]
allowed-tools: Bash(${CLAUDE_PLUGIN_ROOT}/bin/vesta-run:*)
---
!`${CLAUDE_PLUGIN_ROOT}/bin/vesta-run drive ${ARGUMENTS:+--$ARGUMENTS}`

Show this verbatim.

While driving is on, the session will not end until every agreed behaviour is
built and reached by a test, the tests pass, the rules the user set are
honoured, and nothing is outstanding that can be counted. None of that is your
judgement — it is checked. Work through what it reports rather than declaring
the work finished.

If there is no contract yet, run the `vesta-spec` subagent first: there is
nothing to drive toward until something has been agreed.
