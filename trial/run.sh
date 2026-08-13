#!/bin/sh
# One arm of the trial, measured.
#
# Both arms run the same brief through the same model with the same permission
# mode, from an empty directory, with nothing else installed. What differs is
# the plugin under test — which is the only way the numbers mean anything.
set -u

ARM="${1:?which arm}"
WHERE="${2:?where to build}"
BRIEF="${3:?the brief}"

mkdir -p "$WHERE"
cd "$WHERE" || exit 1
git init -q 2>/dev/null

STARTED=$(date +%s)

# --output-format json gives duration, turns, tokens and cost per run.
claude -p "$(cat "$BRIEF")" \
    --output-format json \
    --permission-mode acceptEdits \
    > "$WHERE/../$ARM.json" 2> "$WHERE/../$ARM.stderr"

ENDED=$(date +%s)
echo "$((ENDED - STARTED))" > "$WHERE/../$ARM.seconds"
echo "$ARM finished in $((ENDED - STARTED))s"
