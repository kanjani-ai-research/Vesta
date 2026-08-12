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

# Never build a runtime here. Building takes several seconds and this runs
# inside the host's hook timeout on every prompt — a session that stalls on
# its first message has been made worse, whatever the hook might have said.
# A slash command builds it; until then this stays silent.
python=$(VESTA_NO_INSTALL=1 "$here/vesta-python" 2>/dev/null) || exit 0
[ -n "$python" ] || exit 0

exec "$python" -m vesta.inject 2>/dev/null
