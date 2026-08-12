#!/bin/sh
# Offer the fact that another named project is known.
#
# Silent unless one is, and silent whatever happens: this runs on every prompt
# in the session. An earlier version probed a virtualenv that had been copied
# without its interpreter, and `python: command not found` appeared above every
# single prompt — a hook nobody asked for making itself impossible to ignore.
set -u

here=$(CDPATH= cd -- "$(dirname -- "$0")/../bin" 2>/dev/null && pwd)

python=$("$here/vesta-python" 2>/dev/null) || exit 0
[ -n "$python" ] || exit 0

exec "$python" -m vesta.notice 2>/dev/null
