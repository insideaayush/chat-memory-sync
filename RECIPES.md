# Recipes

Common tasks, copy-paste. Assumes `chat-memory` is installed
(`brew install insideaayush/tap/chat-memory-sync`, `pipx install chat-memory-sync`,
or `pip install --user chat-memory-sync`).

---

## Get started (single machine)

```bash
chat-memory install
```

Local by default: your chats from all tools are exported to `~/chat-memory` and a daily
background job keeps it updated. Nothing leaves your machine. That's it.

Pick a different folder or run time:

```bash
chat-memory install --data-dir ~/Documents/chat-memory --time 08:30
```

## Search your chats

```bash
cd ~/code/my-project
recall "rate limiting"              # ranked hits for THIS repo (by current folder)
recall "retry backoff" --all        # across every project
recall "oauth" --harness cursor      # only Cursor chats
recall "payment flow" --since 2026-09 -k 15
recall "webhook" --full              # just file paths (pipe-friendly)
```

Open a result:

```bash
recall "oauth" --full | head -1 | xargs less
```

## Browse in a UI

```bash
chat-memory serve        # opens http://127.0.0.1:8787
```

## Use it as a native tool (MCP)

```bash
chat-memory mcp          # stdio MCP server (you normally let a harness launch this)
```

See the agent-memory recipe above for per-harness config.

- `/` search, `⌘K` jump to any chat, `j`/`k` move, `↵` open, `[` `]` prev/next,
  `e` expand all, `b` sidebar, `?` help.
- Inline filters in the search box: `@cursor rate limiting`, `@project:my-api oauth`.
- Light/dark toggle, top-right.

## Give your AI assistants memory

Any agent with a terminal can read your whole history via `recall`. Add this to a
project's `AGENTS.md` / `CLAUDE.md` / `GEMINI.md` so it happens automatically:

```markdown
## Prior chat memory
Before implementing or debugging, search past chats across all my tools:
`recall "<topic/keywords>"` (auto-scopes to this repo; add `--all` for everything).
Read the top hits, then open those files for full context.
```

Now an assistant in Claude Code can pull up what you discussed in Cursor weeks ago.

### Native tool via MCP (cross-harness, recommended)

Expose memory as first-class tools (`recall`, `get_chat`, `list_projects`) to any
MCP-capable harness — configure once, no shell needed:

```bash
# Claude Code
claude mcp add chat-memory -- chat-memory mcp
```

```json
// Cursor  (~/.cursor/mcp.json)  |  Gemini CLI (~/.gemini/settings.json)
{ "mcpServers": { "chat-memory": { "command": "chat-memory", "args": ["mcp"] } } }
```

```toml
# Codex  (~/.codex/config.toml)
[mcp_servers.chat-memory]
command = "chat-memory"
args = ["mcp"]
```

See [docs/agent-integration.md](docs/agent-integration.md) for all harnesses.

## Sync across machines (go multi-machine)

Already running local and want it synced? Point it at a **private** git repo — it
converts your local folder in place, imports your chats, and pushes:

```bash
chat-memory install --data-remote git@github.com:you/chat-memory.git --client "macbook"
```

On each other machine, install against the same repo:

```bash
chat-memory install \
  --data-dir ~/chat-memory \
  --data-remote git@github.com:you/chat-memory.git \
  --client "work-laptop"
```

Each machine is a *client*; they never clobber each other's chats. (Keep the repo
**private** — it contains your full transcripts.)

## Run a sync right now

```bash
chat-memory sync        # pull (git mode) -> export -> commit -> push
chat-memory export      # export only, no git
```

## Change settings

```bash
chat-memory config                       # show current config + paths + mode
chat-memory config --client "new-name"   # rename this machine
chat-memory config --data-dir ~/elsewhere
chat-memory install --time 22:00         # reschedule the daily job
```

## Check it's healthy

```bash
chat-memory doctor
# shows: version, mode (local/git), data dir, client, index status, chat counts, last sync
```

## See sync logs (did the job run? any errors?)

```bash
chat-memory logs          # last 40 lines of manual + background syncs
chat-memory logs -n 100   # more
chat-memory logs -f       # follow live (e.g. while running `chat-memory sync`)
```

Each run logs start → pulled → index rebuilt → committed/pushed (or "no changes") → done,
with timestamps. A recent background-job failure is flagged here and in `doctor`.

## A harness isn't showing up?

- Make sure you've actually used it on this machine (it reads each tool's local store).
- See which are detected: `chat-memory doctor`.
- Want a new tool supported? Open a
  [harness request](https://github.com/insideaayush/chat-memory-sync/issues/new?template=harness_request.md)
  with its storage paths, or add an adapter (see [CONTRIBUTING.md](CONTRIBUTING.md)).

## Uninstall

```bash
chat-memory uninstall            # remove the daily job (keeps your chats)
chat-memory uninstall --purge    # also delete local config + search index
# your data folder/repo is never touched
```

Then remove the CLI itself:

```bash
brew uninstall chat-memory-sync      # or: pipx uninstall chat-memory-sync
```

## Where things live

| Thing | Path |
| ----- | ---- |
| Your chats | `~/chat-memory/projects/<project>/<harness>/*.md` (or your `--data-dir`) |
| Config | `~/.config/chat-memory/config.json` |
| Search index, logs | `~/.config/chat-memory/` (machine-local, never synced) |
