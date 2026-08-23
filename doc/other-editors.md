# Vesta outside Claude Code

Vesta is a Claude Code plugin. Its hooks (`inject.py`, `instead.py`,
`keepgoing.py`) run on lifecycle events — `UserPromptSubmit`, `PreToolUse`,
`Stop` — that only Claude Code fires. Its slash commands and subagents are
Claude Code conventions too. None of that has a direct equivalent
elsewhere, and this document doesn't pretend otherwise.

What travels is the MCP server (`bin/vesta-sidecar`, fifteen tools) and,
short of that, an always-loaded instruction file — every framework checked
here has one, under a different name. Neither is Claude Code's hook
guarantee: a hook *intercepts*, mechanically, whether the model thought to
ask or not; an instruction file is text the model reads every turn and
usually, not always, acts on. That gap is real and permanent — it's a
property of how these frameworks are built, not a gap in Vesta. Written
into the always-loaded tier rather than left as a passive tool in the list,
it's still a materially better nudge than nothing, which is the bar this
document is written to.

## Point the MCP config at an absolute path

Vesta's own `.claude-plugin/plugin.json` uses `${CLAUDE_PLUGIN_ROOT}`
because Claude Code substitutes it at plugin-load time; nothing else will.
Every config below needs the real path instead, e.g.
`/Users/you/Developer/vesta/bin/vesta-sidecar`.

### Cursor

`~/.cursor/mcp.json` (global) or `.cursor/mcp.json` (project) —
[documented as the same shape Claude Desktop uses](https://cursor.com/docs/mcp):

```json
{
  "mcpServers": {
    "vesta": { "command": "/absolute/path/to/vesta/bin/vesta-sidecar" }
  }
}
```

### Kiro

Same shape as Cursor — [Kiro's MCP docs](https://kiro.dev/):

```json
{
  "mcpServers": {
    "vesta": { "command": "/absolute/path/to/vesta/bin/vesta-sidecar" }
  }
}
```

### Antigravity

`~/.gemini/config/mcp_config.json` (global) or `.agents/mcp_config.json`
(workspace) — [Antigravity's docs](https://antigravity.google/docs/mcp/).
Same stdio shape; its dialect only differs for remote servers
(`serverUrl` instead of `url`), which doesn't apply here.

### Codex

TOML, not JSON, at `~/.codex/config.toml` (or project-scoped
`.codex/config.toml`). The table name has an underscore —
`mcp.servers` is a documented mistake that fails to connect silently
([openai/codex#3441](https://github.com/openai/codex/issues/3441)):

```toml
[mcp_servers.vesta]
command = "/absolute/path/to/vesta/bin/vesta-sidecar"
```

or, which writes the same file: `codex mcp add vesta -- /absolute/path/to/vesta/bin/vesta-sidecar`

### GitHub Copilot (agent mode)

`.vscode/mcp.json`, project-scoped. The top-level key is `servers`, not
`mcpServers` — the one place this differs from every other config here —
and a stdio entry names its own type explicitly
([VS Code's MCP config reference](https://code.visualstudio.com/docs/agents/reference/mcp-configuration)):

```json
{
  "servers": {
    "vesta": { "type": "stdio", "command": "/absolute/path/to/vesta/bin/vesta-sidecar" }
  }
}
```

### Windsurf

`~/.codeium/windsurf/mcp_config.json`, same `mcpServers` shape as Cursor.

## Telling the agent when to reach for it

A bare tool in the list is easy to never call. Every framework above has
one file it reads every turn without being asked — the same slot a system
prompt occupies — and putting Vesta's own triggers there (not generic
"use MCP tools" advice) is what closes most of the gap a hook would
otherwise close. These are the same conditions `inject.py`/`instead.py`
already act on inside Claude Code, restated as instructions since nothing
here can act on them mechanically:

```markdown
## Vesta

This project has Vesta's MCP tools available. Use them before falling
back to a text search or asking generically:

- Before searching for where a definition is used or defined — call
  `uses` instead of grepping. It's resolved by a language server, not
  matched by name.
- Before editing a file — call `touches` on it first. It reports what
  the change reaches and which tests cover it.
- When asked what this codebase does, or where some kind of work
  happens in it — call `does` or `shape` rather than guessing from
  file names.
- If the user states something that sounds like a standing rule for
  this project ("always...", "never...", "there should be one...") —
  call `declare` with it in their own words, then continue.
- Before assuming nothing is known about a definition — call `known`.
```

**Where this goes, per framework** (the content above is the same
everywhere; only the wrapper differs):

| Framework | File | Notes |
|---|---|---|
| Codex | `AGENTS.md` (project root) or `~/.codex/AGENTS.md` (global) | Plain markdown, unconditional every session — paste the block above as-is. 32 KiB combined cap across all `AGENTS.md` files Codex finds. |
| Antigravity | `AGENTS.md` (project root) | Same as Codex, added in Antigravity v1.20.5+. If both `GEMINI.md` and `AGENTS.md` exist, Antigravity's own `GEMINI.md` wins on conflict — put Vesta's block in `GEMINI.md` if this project already has one. |
| Cursor | `.cursor/rules/vesta.mdc` | Needs frontmatter to load unconditionally: <br>`---`<br>`description: Vesta's MCP tools for this project`<br>`alwaysApply: true`<br>`---`<br>then the block above. Without `alwaysApply: true`, Cursor only includes it when the model judges it relevant — a weaker tier than the others. |
| GitHub Copilot | `.github/copilot-instructions.md` | Read unconditionally, project-scoped. Paste the block as-is. |
| Kiro | `.kiro/steering/vesta.md` | Frontmatter `inclusion: always` is documented, but **Kiro CLI currently ignores inclusion modes and loads every steering file regardless** ([kirodotdev/Kiro#6171](https://github.com/kirodotdev/Kiro/issues/6171)) — set it anyway for when that's fixed, but don't rely on it to scope anything today. |
| Windsurf | `.windsurf/rules/vesta.md`, frontmatter `trigger: always_on` | **12,000-character hard cap per file** — content past it is silently dropped, not queued. The block above is well under that alone; only a concern if it's appended to a much larger existing rules file. |

None of this can force a tool call. It's advisory everywhere, at a
meaningfully stronger tier than an unmentioned tool, never at Claude
Code's hook tier.

## Curating without a UI

Vesta's interactive surfaces — confirming which recovered corrections are
standing rules, editing the project's vocabulary — are Claude Code slash
commands and MCP-tool-mediated conversations. Frameworks without that
surface still have the same store, reachable directly from a terminal:

```sh
# Open the vocabulary in $VISUAL / $EDITOR (vim, whatever's set) and
# apply whatever comes back:
vesta words --edit

# List what's waiting on you, then answer one:
vesta learn
vesta learn <handle> rule      # or: note, lapsed, abstained, reopen

# State a rule outright — one nothing recovered because it was never
# corrected, only ever observed:
vesta learn --declare "there should be one .env for the whole project"
```

Nothing here needs an agent, an MCP client, or a running session — it's
the same `vesta` CLI the plugin's own hooks and commands call underneath,
usable standalone in any terminal.
