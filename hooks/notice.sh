#!/bin/sh
# Offer the fact that another named project is known. Silent unless it is, and
# silent on any failure: a hook that runs on every prompt must never break one.
exec python3 -m vesta.notice 2>/dev/null || exit 0
