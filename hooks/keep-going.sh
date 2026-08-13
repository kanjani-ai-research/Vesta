#!/bin/sh
# Do not stop while there is measurably work left.
#
# The same mechanism the leading loop plugin uses, with the opposite stopping
# condition. Theirs continues until the model outputs a promise it was told not
# to make falsely; this continues until the counts say otherwise — behaviours
# built and tested, tests passing, rules honoured, nothing outstanding.
#
# Silent whatever happens. A Stop hook that errors is one that traps a session.
set -u

here=$(CDPATH= cd -- "$(dirname -- "$0")/../bin" 2>/dev/null && pwd)

python=$(VESTA_NO_INSTALL=1 "$here/vesta-python" 2>/dev/null) || exit 0
[ -n "$python" ] || exit 0

exec "$python" -m vesta.keepgoing 2>/dev/null
