# Vesta

Acquires and structures the computer-science theory a build needs, and answers
questions from it — as a CLI, or as an MCP sidecar to a coding agent.

**What it is for.** An agent working in a repository has good tools for reading
that repository. It has nothing for the paper explaining why the obvious
approach to a hard problem is wrong. Vesta supplies that, and only that: it does
not read, search or navigate code.

## Using it

    pip install -e '.[sidecar,theory]'

Register as a sidecar (`.mcp.json`):

    {"mcpServers": {"vesta": {
      "command": "python", "args": ["-m", "vesta.sidecar"]}}}

Three tools: `recall` (ask the acquired literature), `assess` (is this settled
work or does it need theory), `learn` (go and acquire it). The same things are
`vesta knows`, `vesta judge`, `vesta learn` from a terminal, plus `vesta graph`
and `vesta touches` over a codebase.

Needs `BRAVE_API_KEY` for web search and a model key for building; both are read
from the nearest `.env`. Without a Brave key it still runs, on preprints and
repositories alone, and says so.

## One repository, one knowledge base

A project accumulates knowledge as it is worked on, so corpora are keyed by
repository rather than by task. The sidecar asks its host which project is
current — MCP's `roots` — so changing directory mid-session moves to the right
knowledge base, and every answer states which project it came from.

Two projects never share one: theory acquired for a compiler is not evidence
about a payments service.

## What it does not claim

Retrieval quality is reported, not adjudicated. Scores are shown because an
off-topic question can still match a passage on surface similarity, and no
threshold separated the two without discarding real answers.

**Nothing here has been shown to improve anyone's output.** The propagation
graph beats a naming-convention baseline over 57 commits (f1 0.61 vs 0.58,
completeness 86% vs 58%). The theory-acquisition claim — the reason the project
exists — has no measurement behind it at all. `doc/experiment.md` is how that
would be tested; it has not been run.
