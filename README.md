# chat-memory-sync

Turn your AI coding assistants' chat history into a unified, searchable **memory bank**.

`chat-memory-sync` exports conversations from every AI coding harness you use into one
project-organized Markdown repo, syncs it across all your machines via git, and gives
agents a `recall` command to look up relevant past chats — so an assistant working on a
feature can learn from what you discussed about it in a *different* tool weeks ago.

- **Many harnesses** → one place: Cursor, Cursor Agent CLI, Claude Code, OpenCode, Pi,
  Codex, Gemini CLI. (Antigravity is stubbed — opaque local store.)
- **Project-organized** so memory is scoped to the repo you're in (worktrees/sub-apps
  merged into the parent repo).
- **Multi-machine** via a *client* dimension (mac / pc / cloud) — each machine syncs
  independently; no machine ever clobbers another's chats.
- **Private by design**: the tooling is open source; your chats live in a **separate
  private data repo** you own.
- **Incremental & idempotent**: only changed chats are rewritten; updates to old chats
  are picked up; deleted chats are pruned.

## How it's split

| Repo | Visibility | Contents |
| ---- | ---------- | -------- |
| **chat-memory-sync** (this) | public | the scripts + installer + background job |
| **your data repo** (e.g. `chat-memory`) | **private** | `projects/` + `INDEX.md` (your chats) |

The tool reads `~/.config/chat-memory/config.json` for your data repo's location.
Machine-local state (search index, client name, logs) also lives under
`~/.config/chat-memory/` — never inside the data repo.

## Install

```bash
git clone https://github.com/<you>/chat-memory-sync.git
cd chat-memory-sync
python3 install.py \
    --data-remote git@github.com:<you>/chat-memory.git \
    --client "macbook-air" \
    --time 21:00
```

That one command: writes config, clones (or inits) your private data repo, runs the
first sync, registers a **daily background job** for your OS, and installs the `recall`
command.

| OS | Background job |
| -- | -------------- |
| macOS | launchd LaunchAgent `com.user.chat-memory-sync` |
| Windows | Task Scheduler task `ChatMemorySync` |
| Linux | systemd **user** timer (falls back to cron) |

Only needs `git` + `python3`. Re-running `install.py` is safe.

> No private data repo yet? Create an empty **private** repo on your git host first,
> then pass its URL as `--data-remote`. Or omit `--data-remote` to keep it local-only.

## Finding relevant chats — `recall`

```bash
cd ~/code/my-project
recall "auth token refresh"        # ranked (BM25) hits for THIS repo, with snippets
recall "rate limiting" --all       # every project
recall "payout bug" --harness cursor --since 2026-09 -k 10
recall "..." --full                # just file paths (pipe-friendly)
```

Auto-scopes to the project you're in (via CWD), builds a local SQLite full-text index
that rebuilds when chats change. The index is machine-local (`~/.config/chat-memory/
index.db`), never synced.

**For agents:** run `recall "<topic>"` from the repo you're working in, read the top
hits, then open those `.md` files for full context. Add a line to your project's
`AGENTS.md`/`CLAUDE.md` so assistants do this automatically.

## Multi-machine

Every machine runs the same job independently. Each run:

1. `git pull --rebase` the data repo (other machines' chats)
2. export **this** machine's chats (tagged with its `client` id)
3. prune only **this client's** deleted chats
4. rebuild indexes from the union, `git commit`, `git push`

Set a machine's name with `--client` (default: hostname), or
`CHAT_MEMORY_CLIENT=cloud-vm`.

## How it works

| File | Role |
| ---- | ---- |
| `cmlib.py` | config + paths (data dir, state dir, client) |
| `sync.py` | export every harness's native store → Markdown; rebuild indexes |
| `run.py` | runner: `git pull → sync → commit → push` (+ warms recall index) |
| `recall.py` | full-text (BM25) search, auto-scoped to the current project |
| `install.py` | one-command setup + scheduler + `recall` command |

### Where each harness stores chats

| Harness | Source |
| ------- | ------ |
| Cursor | `…/Cursor/User/globalStorage/state.vscdb` (OS-aware) |
| Cursor Agent CLI | `~/.cursor/acp-sessions/<uuid>/store.db` + `meta.json` |
| Claude Code | `~/.claude/projects/<enc>/<uuid>.jsonl` |
| OpenCode | `~/.local/share/opencode/opencode.db` |
| Pi | `~/.pi/agent/sessions/<enc>/<ts>_<id>.jsonl` |
| Codex | `~/.codex/sessions/**/rollout-*.jsonl` (+ `archived_sessions/`) |
| Gemini CLI | `~/.gemini/tmp/<key>/checkpoint-*.json` (+ `logs.json` prompts) |
| Antigravity | _stub_ — Cascade chats are in an opaque protobuf LevelDB |

### Adding a harness

Write a generator in `sync.py` that yields dicts of the shape:

```python
{
  "harness": "myharness", "id": "<session id>", "project": canonical_project(cwd),
  "source_path": cwd, "title": "...", "created": <ms>, "updated": <ms>,
  "models": {"model-name"},
  "messages": [{"role": "user|assistant", "model": "", "thinking": "",
                "text": "...", "tools": [{"name","args","result"}]}],
}
```

…then add it to `ADAPTERS`. The writer, indexing, client-tagging, and sync handle the
rest.

## Config reference

`~/.config/chat-memory/config.json`:

```json
{ "data_dir": "/Users/you/chat-memory", "client": "macbook-air" }
```

Env overrides: `CHAT_MEMORY_DATA_DIR`, `CHAT_MEMORY_CLIENT`, `CHAT_MEMORY_HOME`.

## License

MIT — see [LICENSE](LICENSE).
