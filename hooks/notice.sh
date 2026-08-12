#!/bin/sh
# Offer the fact that another named project is known.
#
# Silent unless one is, and silent whatever happens: this runs on every prompt
# in the session. An earlier version probed a virtualenv that had been copied
# without its interpreter, and `python: command not found` appeared above every
# single prompt — a hook nobody asked for making itself impossible to ignore.
set -u

here=$(CDPATH= cd -- "$(dirname -- "$0")/../bin" 2>/dev/null && pwd)

# Never build a runtime here. Building takes several seconds and this runs
# inside the host's hook timeout on every prompt — a session that stalls on
# its first message has been made worse, whatever the hook might have said.
# A slash command builds it; until then this stays silent.
python=$(VESTA_NO_INSTALL=1 "$here/vesta-python" 2>/dev/null) || exit 0
[ -n "$python" ] || exit 0

exec "$python" -m vesta.notice 2>/dev/null
