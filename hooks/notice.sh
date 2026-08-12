#!/bin/sh
# Offer the fact that another named project is known.
#
# Silent unless one is, and silent on any failure: this runs on every prompt in
# the session and must never break one. The interpreter is resolved the same way
# the CLI resolves it — a plugin is installed by the framework, so the python on
# PATH is rarely the one Vesta lives in.
set -u

for python in "${VESTA_PYTHON:-}" "${CLAUDE_PLUGIN_ROOT:-}/.venv/bin/python" python3 python; do
    [ -n "$python" ] || continue
    if "$python" -c "import vesta.notice" >/dev/null 2>&1; then
        exec "$python" -m vesta.notice 2>/dev/null
    fi
done
exit 0
