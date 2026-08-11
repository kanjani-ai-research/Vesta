# What has been measured

Every figure here is from a real Claude Code session against this repository,
paired with a control run of the same prompt. Costs are the host's own
`/cost` report.

## Read-only structural question

*"What are the failure tiers in Search.for_ and what else changes if I modify
them?"* and near variants.

| arm | mechanism | cost | vs control |
|---|---|---|---|
| A | control, no vesta | $0.4872 | — |
| B | MCP tools | $0.3747 | −23.1% |
| C | context injection | **$0.2980** | **−38.8%** |

C delivered 799 characters before the agent decided anything. B delivered
21,905 characters across three tool calls. **C was 27× lighter and 20.5%
cheaper than B.**

Five earlier runs of arm B against varying prompts: −24%, −27%, −34%, −19%,
−18%. Mean ≈ −24%, and the spread is wide enough that any single run should be
read as an observation rather than a measurement.

## What the numbers do not show

- **n=1 per arm** for the three-arm comparison. The direction is explicable —
  a tool call costs a decision, a round trip and a large result — but the
  magnitude is one observation.
- **Read-only only.** No measurement exists for a task where the agent writes
  code, which is where a missed consumer costs a rework rather than a sentence.
- **Quality was not scored.** Both arms answered; nobody graded them.

## What was found by running it that testing did not

- The graph reported two consumers of `why_not`; a harvested note claimed five.
  The agent grepped, and the note was right — `getattr(obj, "name")` is
  invisible to a language server. `touches` now reports what it cannot resolve
  rather than implying the set is complete.
- Agents verify recorded analysis regardless of how it is marked. There is no
  MCP or Claude Code mechanism to mark output authoritative; that is inherent
  and, on a task that modifies code, correct.
- Harvested notes make the *tool* path more expensive (18.5% mean with notes
  retrieved, 25.6% without) because they are read and then verified anyway.
  Their value is correctness, not cost.
