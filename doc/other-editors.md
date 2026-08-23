# Vesta's tools outside Claude Code

Vesta is a Claude Code plugin, and most of it is Claude-Code-specific: the
hooks that surface context unasked (`inject.py`, `instead.py`), the slash
commands, the subagents. None of that has an equivalent in another editor,
because MCP — the one thing every editor here actually shares — has no
hook or lifecycle-event concept of its own. Nothing here changes that.

What *is* portable is the MCP server itself: `bin/vesta-sidecar`, and the
fifteen tools it exposes (`shape`, `does`, `uses`, `touches`, `decided`,
`procedure`, and the rest). Any editor that can be pointed at a stdio MCP
server can call them, on request, the same way a Claude Code session does
when it decides to reach for a tool rather than wait for a hook to speak
first.

**Point the config at an absolute path, not `${CLAUDE_PLUGIN_ROOT}`.**
Vesta's own `.claude-plugin/plugin.json` uses that variable because Claude
Code substitutes it at plugin-load time; nothing else will. Replace it with
wherever this repository actually is on disk, e.g.
`/Users/you/Developer/vesta/bin/vesta-sidecar`.

## Cursor

`~/.cursor/mcp.json` (global) or `.cursor/mcp.json` (project-scoped) —
[documented as the same shape Claude Desktop uses](https://cursor.com/docs/mcp):

```json
{
  "mcpServers": {
    "vesta": {
      "command": "/absolute/path/to/vesta/bin/vesta-sidecar"
    }
  }
}
```

## Kiro

Same `mcpServers` shape as Cursor — see [Kiro's own MCP docs](https://kiro.dev/):

```json
{
  "mcpServers": {
    "vesta": {
      "command": "/absolute/path/to/vesta/bin/vesta-sidecar"
    }
  }
}
```

## Antigravity

`~/.gemini/config/mcp_config.json` (global) or `.agents/mcp_config.json`
(workspace) — [Antigravity's docs](https://antigravity.google/docs/mcp/).
The stdio shape matches; Antigravity's dialect differs only for remote
servers (`serverUrl` instead of `url`), which doesn't apply here:

```json
{
  "mcpServers": {
    "vesta": {
      "command": "/absolute/path/to/vesta/bin/vesta-sidecar"
    }
  }
}
```

## Codex

Different format entirely — TOML, not JSON, at `~/.codex/config.toml`
(or a project-scoped `.codex/config.toml`). The table name is
`mcp_servers` with an underscore; `mcp.servers` is a documented mistake
that fails to connect silently
([openai/codex#3441](https://github.com/openai/codex/issues/3441)).

```toml
[mcp_servers.vesta]
command = "/absolute/path/to/vesta/bin/vesta-sidecar"
```

Or via the CLI, which writes the same file:

```sh
codex mcp add vesta -- /absolute/path/to/vesta/bin/vesta-sidecar
```

[OpenAI's own MCP docs](https://learn.chatgpt.com/docs/extend/mcp?surface=cli)
have the rest of the fields (`env`, `cwd`, timeouts) if `vesta-sidecar`
ever needs them — it doesn't today.

## What you lose, concretely

No `UserPromptSubmit`/`PreToolUse`/`Stop` hooks — nothing surfaces a
defect or a standing rule unasked, and nothing intercepts a redundant
`Grep` in favor of a resolved answer. No slash commands, no subagents. The
model has to decide to call a Vesta tool on its own, the same as any other
MCP tool it's holding — which is exactly the "tools" arm `doc/measurements.md`
already costed against Claude Code's own injection path, at roughly 23%
less saving than letting Vesta speak first. Outside Claude Code, that's
not a comparison — it's the only mode available.
