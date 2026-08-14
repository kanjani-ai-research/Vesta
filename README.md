# Vesta

    /plugin marketplace add https://gitlab.com/causum/vesta
    /plugin install vesta@causum

Answers structural questions about a repository from a resolved graph of what
refers to what, an ontology of what the work is called, and what earlier
sessions already worked out — so an agent can ask instead of reading, and you
do not pay twice for the same understanding.

**Install it and work normally. There is nothing to run.**

## What it does while you work

Vesta is a companion by default. It builds a graph of the repository in the
background, keeps it current as the code changes, and puts what it knows in
front of the agent at the moment it matters:

- **What is already wrong in the file you are about to change.** Naming a file
  with a swallowed failure in it says so, once. Naming it again says nothing.
- **A rule you set that this work would break.** Rules are recorded as you
  state them in the course of ordinary work — nothing to run, nothing to
  remember.
- **What earlier sessions worked out** about a definition the prompt names,
  with the regions those conclusions were drawn from, so an agent can check
  them rather than take them on trust.

It says nothing on a prompt that names nothing, which is most of them.

## What you can ask it

Every tool is a slash command. The ones worth knowing:

    /vesta:shape      what this repository is made of, before opening a file
    /vesta:touches    what a change reaches, and which tests cover it
    /vesta:does       where a kind of work happens, asked in ordinary words
    /vesta:defects    things worth fixing, found without being asked
    /vesta:decided    rules you have stated, and whether the code honours them
    /vesta:tutorial   learn it a page at a time, on your own repository

`/vesta:help` lists the rest.

**`does` is the one that is not a grep.** Ask in the vocabulary of the work —
"retrying a failed request", "deduplicating submissions" — and it answers in
the vocabulary of the code, which is usually different. That crossing needs a
vocabulary, which an agent derives once per repository.

## Automated mode

Asking for a whole project to be built in an empty directory offers a choice:
build it interactively, or agree a contract first and run to completion. Choose
interactive and you are not asked again.

Automated mode is never entered on your behalf, and never offered in a
repository somebody has already been working in.

## What it costs

Vesta runs on your agent's own inference. **It holds no API key and makes no
network calls of its own.**

Which model does what is not a preference: reading a definition and labelling
it runs on a small model, because it happens once for every definition and a
larger one at that volume makes the approach too expensive to use. Synthesis
somebody will be held to — a contract, a specification — runs on a larger one,
once.

Everything derived is kept under `~/.vesta` and can be deleted. `/vesta:held`
reports what is held and reclaims what belongs to repositories that are gone.
Nothing leaves your machine.

## What it will not do

- **It does not read anything hidden.** Nothing beginning with a dot is ever
  walked — not `.env`, not `.aws`, not `.ssh`. Nor are dependency directories:
  `venv`, `node_modules`, `site-packages`, `vendor`, and the rest.
- **It does not assert what it has not derived.** A rule is recorded against
  the words you actually said, verified against the transcript; a template can
  lend a vocabulary but never a claim about which of your definitions do the
  work.
- **It reports what it could not resolve** rather than implying a complete
  answer. A propagation set says which references it could not follow; a graph
  of a workspace says that references between its projects are not in it.

## Requirements

Python 3.10 or newer, and a language server for the languages you want
resolved — `pyright-langserver` for Python, `rust-analyzer` for Rust, `gopls`
for Go, and so on. Vesta builds its own runtime on first use; it does not ask
you to install anything into yours.

A repository whose language has no server installed is reported as such rather
than silently half-resolved.

## What has and has not been measured

On a read-only structural question against this repository, paired with a
control run of the same prompt and costed by the host's own `/cost`:

| arm | mechanism | cost | vs control |
|---|---|---|---|
| control | no Vesta | $0.4872 | — |
| tools | the agent calls them | $0.3747 | −23.1% |
| injection | put in front, unasked | **$0.2980** | **−38.8%** |

Injection delivered 799 characters before the agent decided anything; the tools
delivered 21,905 across three calls. `doc/measurements.md` has the rest, and
`trial/` has the harness.

**Most of what this does is unmeasured.** Whether surfacing a defect at the
moment somebody edits a file improves what they produce, whether the vocabulary
crossing finds things a grep would not, whether extraction recovers rules worth
having — none of that has been shown. `doc/open-questions.md` records what
would have to be true, and what was found when it was checked.

## Licence

Apache 2.0. See `LICENSE` and `NOTICE.md`.
