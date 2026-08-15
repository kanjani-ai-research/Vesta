#!/bin/sh
# Refuse a search the graph already answers, and answer it instead.
#
# `PreToolUse` with `permissionDecision: "deny"` prevents the tool call, and
# the reason is delivered to Claude — so a grep for a definition Vesta holds
# never runs, and the resolved answer arrives in its place. Telling an agent
# that better tools exist does not make it use them; this does.
#
# Silent and permissive whatever happens: a hook that cannot run must let the
# search through, because a tool that blocks work it cannot do is uninstalled
# within the hour.
set -u

here=$(CDPATH= cd -- "$(dirname -- "$0")/../bin" 2>/dev/null && pwd)

python=$(VESTA_NO_INSTALL=1 "$here/vesta-python" 2>/dev/null) || exit 0
[ -n "$python" ] || exit 0

exec "$python" -m vesta.instead 2>/dev/null
