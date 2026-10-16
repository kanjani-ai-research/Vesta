---
description: One version in every place it is written — report, set, or tag
argument-hint: [--set X.Y.Z] [--tag]
allowed-tools: Bash(${CLAUDE_PLUGIN_ROOT}/bin/vesta-run:*)
disable-model-invocation: true
---
!`${CLAUDE_PLUGIN_ROOT}/bin/vesta-run version . $ARGUMENTS`

Show this verbatim.

A version is written in several files for several readers — the package
metadata, the plugin manifest, a package's `__version__`, the changelog's
latest heading — and they drift. This lists every place that carries one and
says whether they agree.

`--set X.Y.Z` writes the number into every place and turns an "Unreleased"
changelog heading into it, or opens one. `--tag` cuts the local tag in this
repository's own shape once the versioned files are committed. **Nothing is
ever pushed**; publishing is theirs to do, and you do not run it for them.
