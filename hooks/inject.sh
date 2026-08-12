#!/bin/sh
# Put what is already known in front of the agent, before it decides anything.
#
# The tools answer when asked; this answers a question nobody asked yet, because
# an agent cannot ask for what it does not know exists. Silent unless the prompt
# plainly names a definition the graph holds — a hook that prepends something to
# every prompt is a tax on every prompt.
#
# Silent whatever happens, like every hook here: this runs on each prompt in the
# session and must never be the reason one fails.
set -u

here=$(CDPATH= cd -- "$(dirname -- "$0")/../bin" 2>/dev/null && pwd)

python=$("$here/vesta-python" 2>/dev/null) || exit 0
[ -n "$python" ] || exit 0

exec "$python" -m vesta.inject 2>/dev/null
