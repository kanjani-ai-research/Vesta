# Vesta

Answers structural questions about a repository from a resolved graph of what
refers to what, an ontology of what the work is called, and what earlier
sessions already worked out — so an agent can ask instead of reading, and you
do not pay twice for the same understanding. Every decision it narrows leaves
a compact, checkable **witness** (`spec/witness.md`).

## The one design rule to understand first

**Vesta ships no model, holds no API key, and makes no network calls of its
own.** That is not a claim in this README — the test suite poisons the
model-client imports and asserts every tool still answers
(`tests/test_conformance.py`).

So where does judgement come from? From the harness you already run. Vesta
nests inside your coding agent and uses *its* inference — the model you
already pay for, under the credentials you already control. Anything Vesta
cannot compute deterministically is judged there, and recorded as such.

The rule, stated once: **Vesta may speak to a model you point it at; it never
ships a client for one.** Today that means there is no configuration anywhere
in Vesta that makes it call a vendor — nothing to leak, no bill of its own,
and installing it requires no decisions.

## Pick your setup

Three ways to run it. Start with the row that describes you.

| you have | install | what works |
|---|---|---|
| **Claude Code** | two lines, below | everything — hooks, tools, agents, automatic vocabulary |
| **another editor** (Cursor, Kiro, Codex, Copilot, Windsurf, Antigravity) | `pip install 'causum-vesta[sidecar]'` + MCP config | all fifteen tools; no hooks, no subagents (see below) |
| **a plain terminal, or CI** | `pipx install causum-vesta` | the full CLI: graphs, impact, defects, rules, guided narrowing, witnesses |

### Setup 1 — Claude Code (recommended: everything works)

    /plugin marketplace add https://gitlab.com/causum/vesta.git
    /plugin install vesta@causum

Nothing else to configure — hooks, slash commands, and the MCP server load
together. Confirm it's live:

    /vesta:shape

If that answers with real numbers, it's working. If it says nothing is built
yet, see **Housekeeping**. After any Vesta update, run `/mcp` once — the MCP
server is a background process and keeps old code in memory until reconnected.
If an answer looks stale right after an update, that is the first thing to
try.

### Setup 2 — another editor, over MCP

    pip install 'causum-vesta[sidecar]'

Then point your editor's MCP configuration at the `vesta-sidecar` command.
**`doc/other-editors.md` has the exact config block for each editor**,
including which instruction file each one reads unconditionally and what to
put in it so the tools get used unasked.

What you give up outside Claude Code, honestly: hooks (context injected
*before* the agent decides anything — the single most effective mechanism we
measured) and subagents (automatic vocabulary derivation, rule recovery).
Those are Claude Code conventions with no equivalent elsewhere. The
vocabulary and rules still work — you supply them by hand, exactly as in
Setup 3.

### Setup 3 — the CLI alone, no agent anywhere

    pipx install causum-vesta

Everything deterministic works immediately, on any repository:

    vesta status --prepare     # build the graph (needs a language server, below)
    vesta shape                # what this repository is made of
    vesta uses <name>          # a definition and everything that refers to it
    vesta touches <file>       # what a change reaches, and which tests cover it
    vesta defects              # things worth fixing, found unasked
    vesta projects             # every repository Vesta holds, by name and path

Two things normally derived by an agent need one manual step each, and both
degrade to honest answers rather than wrong ones until you do:

- **Vocabulary** — what the work here is *called*, so `vesta does "post a
  transaction"` can answer in the code's names. Seed it from a shipped
  template (`vesta words --template ai`), write your own terms
  (`vesta-domain --repo . --write`), or let an agent derive it if you ever
  open the repo in one.
- **Rules** — things you've decided that the code must honour:
  `vesta learn --declare "never a bare except in this repository"`, then
  `vesta decided --check`.

With those in place the accountable core runs harness-free: `vesta honing`
narrows a decision guided by your active specification, and every run leaves
a **witness** under `~/.vesta/witnesses/<project>/` — a few-kilobyte record
of what was asked, how the space contracted, what was overridden, and which
checks held. In CI, that file is the artifact: keep it with the build.

## Which model does what (and where)

Inside Vesta itself: **none, ever.** In Claude Code, judgement tasks run as
subagents on your session's inference — reading and labelling definitions on
a small model (`haiku`), because it happens once per definition; synthesis
somebody will be held to (a contract, a specification) on a larger one
(`sonnet`), once. Each subagent declares its model in its own frontmatter;
nothing defers to whatever your session happens to have selected. Outside a
harness there is no model, and everything above still works as described.

## Language support

Vesta resolves through a real language server per language — the machinery
behind your editor's "go to definition," not a name-matching guess:

| Language | Server | Install |
|---|---|---|
| Python | `pyright-langserver` | `npm i -g pyright` |
| Rust | `rust-analyzer` | usually ships with `rustup` |
| Go | `gopls` | `go install golang.org/x/tools/gopls@latest` |
| C / C++ | `clangd` | ships with LLVM, or your package manager |
| JavaScript / TypeScript | `typescript-language-server` | `npm i -g typescript-language-server typescript` |
| OCaml | `ocamllsp` | `opam install ocaml-lsp-server` |
| Lua | `lua-language-server` | your package manager |

A language with no server installed is reported as unresolved (in
`vesta status`'s hole count), never silently skipped. Adding a language is
one row in `vesta/resolve.py` — a name, a command, and the suffixes it owns.

## Day to day, inside a session

Every tool is a slash command in Claude Code and an MCP tool everywhere else:

    /vesta:shape      what this repository is made of, before opening a file
    /vesta:touches    what a change reaches, and which tests cover it
    /vesta:does       where a kind of work happens, asked in ordinary words
    /vesta:defects    things worth fixing, found without being asked
    /vesta:decided    rules you have stated, and whether the code honours them
    /vesta:honing     whether you're honing in, or just going round again
    /vesta:why        why it concluded that, and whether it still holds today
    /vesta:tutorial   learn it a page at a time, on your own repository

`/vesta:help` lists the rest. Most of the time none of this needs typing —
Vesta watches what you're about to do and puts what it knows in front of the
agent unasked: defects in the file you're about to change (named once, not
repeated), a rule this work would break, what earlier sessions worked out
about a definition the prompt names. It says nothing on a prompt that names
nothing, which is most of them.

**`does` is the one that is not a grep.** Ask in the vocabulary of the work —
"retrying a failed request", "posting a transaction" — and it answers in the
vocabulary of the code. Word forms cross (plurals, verb forms); genuine
synonyms do not, deliberately — a match you can't explain is a match that can
be quietly wrong. When nothing crosses, the answer carries the repository's
own vocabulary so you (or the agent) can re-ask in its words.

## Adjudication and ontology

Two things Vesta asks you to confirm, because guessing on your behalf and
asserting it as fact would be worse than asking:

**Rules.** Vesta recovers candidate standing rules from corrections you gave
an agent in earlier sessions — only you know which were decisions.
`/vesta:learn` shows what's waiting; `vesta learn <handle> rule` confirms one
from a terminal; `vesta learn --declare "…"` states one outright. A recovered
rule must quote words you verifiably said.

**Vocabulary.** Derived per repository, automatically, the first time it
matters in Claude Code — or supplied by you (`vesta words --edit`, templates,
`vesta-domain --write`). A template lends words for a category of system,
never a claim about which of *your* definitions do that work; that binding is
always read from your code.

## Housekeeping

    vesta status               is it built, and what's in it
    vesta held                 everything Vesta holds, across every repo, biggest first
    vesta held --reclaim       delete what belongs to repos that no longer exist

Everything derived lives under `~/.vesta` and nowhere else, keyed per
project — one project's graph, vocabulary, rules, and witnesses never mix
with another's. Deleting `~/.vesta` is a full, clean reset.

## What it will not do

- **Read anything hidden.** Nothing beginning with a dot is ever walked — not
  `.env`, not `.aws`, not `.ssh`. Nor dependency directories: `venv`,
  `node_modules`, `site-packages`, `vendor`, and the rest.
- **Assert what it has not derived.** A rule is recorded against words you
  actually said; a template lends vocabulary but never bindings.
- **Imply a complete answer.** What could not be resolved is reported — a
  propagation set says which references it could not follow.
- **Call a model on its own.** See the design rule at the top; it is load-
  bearing, and it is tested.

## What has and has not been measured

On a read-only structural question against this repository, paired with a
control run of the same prompt and costed by the host's own `/cost`:

| arm | mechanism | cost | vs control |
|---|---|---|---|
| control | no Vesta | $0.4872 | — |
| tools | the agent calls them | $0.3747 | −23.1% |
| injection | put in front, unasked | **$0.2980** | **−38.8%** |

Injection delivered 799 characters before the agent decided anything; the
tools delivered 21,905 across three calls. A separate benchmark (`bench/`)
checks `uses()` against ground truth derived independently of Vesta's own
graph: mean precision 0.998, mean recall 1.000. `doc/measurements.md` has the
rest, `doc/open-questions.md` records what is still unmeasured, and
`spec/witness.md` specifies the witness format, its checks, and its stated
limits.

## Requirements

Python 3.10 or newer, and a language server for the languages you want
resolved. The Claude Code plugin builds its own runtime on first use and does
not touch yours; the PyPI install uses the Python you install it into. One
runtime dependency: `pydantic`.

## Licence

Apache 2.0. See `LICENSE` and `NOTICE.md`.
