#!/bin/sh
# Keep a note when a turn ends because the API failed.
#
# Runs on `StopFailure`, which fires in place of `Stop` once the host's own
# retries — timeouts, overloads, rate limits — have run out. Its output is
# discarded, so the note is said at the next prompt instead.
#
# Silent whatever happens.
set -u

here=$(CDPATH= cd -- "$(dirname -- "$0")/../bin" 2>/dev/null && pwd)

python=$(VESTA_NO_INSTALL=1 "$here/vesta-python" 2>/dev/null) || exit 0
[ -n "$python" ] || exit 0

exec "$python" -m vesta.interrupted 2>/dev/null
