---
description: The words this project uses, and how to change them
argument-hint: [--templates | --template <name> | --from <path>]
allowed-tools: Bash(${CLAUDE_PLUGIN_ROOT}/bin/vesta-run:*), Read, Write
---
!`${CLAUDE_PLUGIN_ROOT}/bin/vesta-run words $ARGUMENTS`

These are the words this project is described in — what it is about, what its
code does, what it handles. Everything Vesta answers about work rather than
about syntax is answered in them, so a word that is wrong makes every answer
that uses it wrong.

Show the output above verbatim first.

**If they want to change the words**, do not edit the stored ontology. Write
the vocabulary to a file they can edit, in the same `kind: label` grammar shown
above, one per line:

    ${CLAUDE_PLUGIN_ROOT}/bin/vesta-run words > /tmp/vesta-words.txt

Edit that file as they direct — adding, removing or rewording lines — then keep
it with:

    ${CLAUDE_PLUGIN_ROOT}/bin/vesta-run words --set /tmp/vesta-words.txt

`--set` replaces the vocabulary with what the file says, so a line they deleted
is removed. `--from` only ever adds, which is right for a template and wrong
for an edit — use `--set` here or their removals will be silently ignored.

From a terminal outside this session they can instead run `vesta words --edit`,
which opens the same thing in `$EDITOR`.

**Removing a word removes what was attached to it.** Vesta will say how many
definitions became unbound. Tell them the number rather than passing over it.

**Never add an attachment on a word's behalf.** A word says what the project is
about; which definitions do that work is read from the code by the domain
agent, not asserted. If new words were just added, say they are unattached
until that runs.
