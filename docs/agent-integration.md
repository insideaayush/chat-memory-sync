# Agent integration — give any assistant memory across all your tools

`chat-memory-sync` exposes a single command, **`recall`**, that searches *all* your past
chats from *every* harness. Any agent that can run a shell command can use it — so an
assistant in Claude Code can read what you discussed in Cursor, Codex, Gemini, etc.

## The one thing agents need to know

> Before starting work, search prior chats for relevant context:
> run `recall "<keywords>"` from the current repo (auto-scopes to this project),
> read the top hits, then open the listed `.md` files for full context.

## Commands

```bash
recall "auth token refresh"       # ranked hits for the CURRENT project (by CWD)
recall "rate limiting" --all      # across every project
recall "flaky integration test" --harness cursor --since 2026-09 -k 10
recall "oauth flow" --full        # just file paths (easy to pipe / open)
```

- Auto-scopes to the repo you're in; pass `--project <name>` or `--all` to widen.
- Results are ranked (BM25) with snippets; each line includes the file path.
- Then `cat`/open the `.md` files — they contain the full transcript + frontmatter
  (`harness`, `client`, `date`, `models`, …).

No `recall` on PATH? Use the absolute form:

```bash
python3 /path/to/chat-memory-sync/recall.py "your query" --project <repo>
```

## Drop-in instructions per harness

Add a short block to the instructions file each tool reads, so assistants do this
automatically. Copy the snippet below into the relevant file:

| Harness | File to edit |
| ------- | ------------ |
| Claude Code | `CLAUDE.md` (repo root or `~/.claude/CLAUDE.md`) |
| Cursor / Cursor Agent | `.cursor/rules/*.mdc` or `AGENTS.md` |
| OpenCode | `AGENTS.md` |
| Codex | `AGENTS.md` |
| Gemini CLI | `GEMINI.md` |
| Pi | `AGENTS.md` |
| Generic | `AGENTS.md` |

### Snippet

```markdown
## Prior chat memory (chat-memory-sync)

Past conversations from all my AI tools are indexed and searchable via `recall`.
Before implementing a feature or debugging, search for relevant prior context:

- `recall "<topic/keywords>"` — searches past chats for THIS repo (ranked, with snippets)
- `recall "<topic>" --all` — search across all my projects
- Open the returned `.md` files for the full transcript before proceeding.

Use this to avoid re-deriving decisions, repeating past mistakes, or missing context
from a different tool/session.
```

## Native tool access via MCP (recommended, cross-harness)

`chat-memory mcp` runs a **Model Context Protocol** server over stdio, exposing your
memory as first-class tools to any MCP-capable harness — no shell required. Tools:

- `recall(query, project?, harness?, since?, limit?)` — ranked past chats + snippets
- `get_chat(path)` — full transcript of a chat (path comes from a recall result)
- `list_projects()` — projects with chat counts

Configure it **once per harness**:

**Claude Code**
```bash
claude mcp add chat-memory -- chat-memory mcp
```

**Cursor** — `~/.cursor/mcp.json` (or a project `.cursor/mcp.json`):
```json
{ "mcpServers": { "chat-memory": { "command": "chat-memory", "args": ["mcp"] } } }
```

**Codex** — `~/.codex/config.toml`:
```toml
[mcp_servers.chat-memory]
command = "chat-memory"
args = ["mcp"]
```

**Gemini CLI** — `~/.gemini/settings.json`:
```json
{ "mcpServers": { "chat-memory": { "command": "chat-memory", "args": ["mcp"] } } }
```

**Any MCP client** — run `chat-memory mcp` as a stdio server (command `chat-memory`,
arg `mcp`). If `chat-memory` isn't on the harness's PATH, use the absolute path from
`which chat-memory`.

After adding it, your agent can call `recall` natively and pull in prior context from
every tool you use. (The shell approach above still works too, and needs no config.)
