# Vesta

    /plugin marketplace add https://gitlab.com/causum/vesta.git
    /plugin install vesta@causum

Answers structural questions about a repository from a resolved graph of what
refers to what, an ontology of what the work is called, and what earlier
sessions already worked out — so an agent can ask instead of reading, and you
do not pay twice for the same understanding.

**Install it and work normally. There is nothing to run.** Everything below
is for the reader who wants to actually use what it can do — full setup, every
surface, what to check when something seems off — not required reading to
get value from it day one.

## Install: Claude Code

Two lines, above. Nothing else to configure — the plugin's hooks, slash
commands, and MCP server all load together. Confirm it's live:

    /vesta:shape

If that answers with real numbers (definitions, references, most-depended-on
code), it's working. If it says nothing is built yet, see **Housekeeping**
below.

## Install: other editors

Vesta is a Claude Code plugin — its hooks (fire automatically on things like
"about to edit a file" or "user just said something") and slash commands are
Claude Code conventions with no equivalent elsewhere. What travels is its MCP
server, plus an always-loaded instruction file that gets the tools used
unasked. **`doc/other-editors.md` has the exact config** for Cursor, Kiro,
Antigravity, Codex, GitHub Copilot, and Windsurf, including which file each
one reads unconditionally and where to put Vesta's own trigger instructions
in it — and how to confirm and edit rules/vocabulary from a plain terminal
where there's no session to do it in.

That gap (a hook intercepts mechanically; an instruction file is read and
usually, not always, acted on) is real and permanent — a property of how
those frameworks are built, not a gap in Vesta.

## Keeping it running and current

Vesta's MCP server is a background process, separate from the plugin files on
disk. Updating the plugin does not restart it — the running process keeps the
code it already loaded in memory. After any Vesta update:

    /mcp

Reconnects the MCP server to the current plugin version. If a tool's answer
looks stale right after an update — a fix that should be visible isn't — this
is the first thing to try before assuming anything is actually broken.

`/vesta:status` reports whether Vesta can answer for the current repository
yet, and what it's built (definition/reference counts, any files the
resolver couldn't read and why). Run it any time something seems quiet.

## Language support

Vesta resolves through a real language server per language — the same class
of tool an editor uses for "go to definition," not a name-matching guess.
Shipped today:

| Language | Server | Install |
|---|---|---|
| Python | `pyright-langserver` | `npm i -g pyright` |
| Rust | `rust-analyzer` | usually ships with `rustup` |
| Go | `gopls` | `go install golang.org/x/tools/gopls@latest` |
| C / C++ | `clangd` | ships with LLVM, or your package manager |
| JavaScript / TypeScript | `typescript-language-server` | `npm i -g typescript-language-server typescript` |
| OCaml | `ocamllsp` | `opam install ocaml-lsp-server` |
| Lua | `lua-language-server` | your package manager |

Vesta builds its own runtime on first use — it does not touch yours. It only
needs the language server itself on `PATH`. A language with no server
installed is reported as unresolved (in `/vesta:status`'s hole count), never
silently skipped.

**Adding a language not listed is one row, no code** — `vesta/resolve.py`'s
`SERVERS` list is a name, a command, and the file suffixes it owns, because
every server already speaks the same three LSP operations underneath. If a
server for your language exists and follows the LSP protocol, it's a small,
mechanical addition.

## Using it day to day

Every tool is a slash command inside Claude Code; the same fifteen are MCP
tools everywhere else:

    /vesta:shape      what this repository is made of, before opening a file
    /vesta:touches    what a change reaches, and which tests cover it
    /vesta:does       where a kind of work happens, asked in ordinary words
    /vesta:defects    things worth fixing, found without being asked
    /vesta:decided    rules you have stated, and whether the code honours them
    /vesta:tutorial   learn it a page at a time, on your own repository

`/vesta:help` lists the rest. Most of the time none of this needs typing —
Vesta is a companion by default, watching what you're about to do and putting
what it knows in front of the agent unasked:

- **What is already wrong in the file you are about to change.** Named once;
  not repeated on the next mention.
- **A rule you stated that this work would break.**
- **What earlier sessions worked out** about a definition the prompt names,
  with the regions those conclusions came from, so it can be checked rather
  than trusted.

It says nothing on a prompt that names nothing, which is most of them.

**`does` is the one that is not a grep.** Ask in the vocabulary of the
work — "retrying a failed request", "deduplicating submissions" — and it
answers in the vocabulary of the code, which is usually different. That
crossing needs a vocabulary derived from the repository first (see
**Adjudication and ontology** below) — until then `does`/`means` say so
rather than guess.

## Adjudication and ontology

Two separate things Vesta asks you to confirm, both because guessing on your
behalf and asserting it as fact would be worse than asking:

**Confirming rules.** Vesta recovers candidate standing rules from corrections
you gave an agent in earlier sessions — a passing remark and a real decision
read identically in a transcript, and only you know which is which.

    /vesta:learn        shows what's waiting, lets you confirm or dismiss each
    /vesta:declare      state a rule outright, one you've always just observed
                         and never had to correct anyone on

In a live session, the `learn` MCP tool asks directly, one candidate at a
time. From a plain terminal: `vesta learn` to list, `vesta learn <handle>
rule` to confirm one (or `note` / `lapsed` / `abstained` / `reopen`).

**The vocabulary (ontology).** What a repository's work is *called* — the
words `does`/`means` answer in. Derived once per repository, automatically,
the first time it matters (a fresh repo, or `does`/`means` reporting nothing
read yet triggers the domain agent). You never have to run this yourself.

    /vesta:words                    show the current vocabulary
    /vesta:words --templates        list shipped starting points
    /vesta:words --template ai      seed from one (adds only, never removes)
    /vesta:words --edit             open it in $EDITOR and apply what comes back

A template lends words for a whole category of system (`ai`, `data`,
`security`, `blockchain`, `embedded`, `service` — `vesta/templates/`) but
never a claim about which of *your* definitions do that work; that binding
is always read from your actual code by the domain agent, never asserted by
a template. Editing removes an attachment along with a removed word — Vesta
says how many definitions became unbound when that happens.

## Housekeeping

    /vesta:status              is it built, and what's in it
    /vesta:held                everything Vesta holds, across every repo, biggest first
    /vesta:held --reclaim      delete what belongs to repos that no longer exist

Everything derived — the graph, vocabulary, rules, notes — lives under
`~/.vesta` and nowhere else. Deleting that directory is a full, clean reset;
nothing else on your machine is touched.

## What it costs

Vesta runs on your agent's own inference. **It holds no API key and makes no
network calls of its own.** Confirmed mechanically, not just claimed: the
test suite poisons `litellm`/`stroma` imports and asserts every tool still
answers (`tests/test_conformance.py`).

Which model does what is not a preference: reading a definition and
labelling it runs on a small model (`haiku`), because it happens once per
definition and a larger one at that volume makes the whole approach too
expensive to use. Synthesis somebody will be held to — a contract, a
specification — runs on a larger one (`sonnet`), once. Every subagent
declares its own model in its own frontmatter; nothing here defers to
whatever the host session happens to have selected.

## What it will not do

- **It does not read anything hidden.** Nothing beginning with a dot is ever
  walked — not `.env`, not `.aws`, not `.ssh`. Nor dependency directories:
  `venv`, `node_modules`, `site-packages`, `vendor`, and the rest.
- **It does not assert what it has not derived.** A rule is recorded against
  words you actually said, checked against the transcript; a template lends a
  vocabulary but never a claim about which of your definitions do the work.
- **It reports what it could not resolve** rather than implying a complete
  answer. A propagation set says which references it could not follow; a
  graph of a workspace says references between its own projects aren't in it.

## What has and has not been measured

On a read-only structural question against this repository, paired with a
control run of the same prompt and costed by the host's own `/cost`:

| arm | mechanism | cost | vs control |
|---|---|---|---|
| control | no Vesta | $0.4872 | — |
| tools | the agent calls them | $0.3747 | −23.1% |
| injection | put in front, unasked | **$0.2980** | **−38.8%** |

Injection delivered 799 characters before the agent decided anything; the
tools delivered 21,905 across three calls. A separate, independently-derived
benchmark (`bench/`) checked `uses()`'s answers about real definitions in
this repository against ground truth read by hand — not by trusting Vesta's
own graph — and currently scores mean precision 0.998, mean recall 1.000
across a spread of picked-before-running targets; building it surfaced and
fixed three real defects along the way, documented in `bench/README.md`.
`doc/measurements.md` has the rest, and `trial/` has the harness this table
came from.

**Most of what this does is still unmeasured.** Whether surfacing a defect at
the moment somebody edits a file improves what they produce, whether the
vocabulary crossing finds things a grep would not — none of that has been
shown yet. `doc/open-questions.md` records what would have to be true, and
what was found when it was checked.

## Requirements

Python 3.10 or newer, and a language server for the languages you want
resolved (see **Language support** above). Vesta builds its own runtime on
first use.

## Licence

Apache 2.0. See `LICENSE` and `NOTICE.md`.
