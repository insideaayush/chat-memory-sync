# Contributing to chat-memory-sync

Thanks for helping! The whole point of this project is that **no one person can keep up
with every AI coding harness** — so adapters are community-driven. Most contributions
are a single new adapter function.

- 🐛 **Found a bug?** Open an issue.
- 🔌 **Want a harness supported?** Open a *Harness request* issue (even if you can't code
  it — the storage-location details are the hard part, and you can help gather them).
- 🛠 **Adding/​fixing an adapter?** Read ["Adding a harness"](#adding-a-harness) below.

By contributing you agree your work is licensed under the repo's [MIT License](LICENSE)
and that you follow the [Code of Conduct](CODE_OF_CONDUCT.md).

## Project shape

| File | Role |
| ---- | ---- |
| `cmlib.py` | config + paths (data dir, state dir, client) |
| `sync.py` | **harness adapters** + Markdown writer + index builder |
| `run.py` | runner: git pull → sync → commit → push |
| `recall.py` | full-text search |
| `install.py` | installer + schedulers |

No dependencies beyond the Python standard library (`sqlite3`, `json`, `glob`, …). Please
keep it that way — this has to run anywhere with just `python3` + `git`.

## Adding a harness

A harness adapter is a generator in `sync.py` that reads that tool's native chat store
and `yield`s normalized chat dicts. Everything else (writing Markdown, project grouping,
client tagging, indexing, syncing) is handled for you.

### 1. Find where the harness stores chats

This is usually the biggest part. Look under:

- `~/.<tool>/`, `~/.config/<tool>/`, `~/.local/share/<tool>/`
- macOS: `~/Library/Application Support/<Tool>/`
- VS Code forks: `…/<Tool>/User/globalStorage/state.vscdb` + `workspaceStorage/`

Chats are usually **JSONL** (one event/message per line), a **SQLite DB**, or per-session
**JSON** files. Record the exact path and format in your PR/issue so others can verify.

### 2. Write the adapter

Yield one dict per conversation:

```python
{
  "harness": "myharness",            # short, kebab-case; becomes a folder name
  "id": "<stable session id>",       # unique per chat (used in the filename)
  "project": canonical_project(cwd), # use the helper; maps cwd → repo name
  "source_path": cwd,                # absolute path the chat ran in (may be "")
  "title": "<short title>",          # first user line is fine if none stored
  "created": <epoch_ms>,             # use toms(...) to normalize ISO/sec/ms
  "updated": <epoch_ms>,
  "models": {"model-name"},          # set(); may be empty
  "messages": [
    {
      "role": "user" | "assistant",
      "model": "",                   # optional, per-message
      "thinking": "",                # reasoning text, optional
      "text": "...",                 # main content
      "tools": [                     # tool calls, optional
        {"name": "Shell", "args": {...} | "raw", "result": "..." | None},
      ],
    },
  ],
}
```

Then register it:

```python
ADAPTERS = [cursor_chats, ..., myharness_chats]
```

Guidelines:

- **Skip empties** — don't yield chats with no renderable messages.
- **OS-aware paths** — branch on `platform.system()` or probe candidate paths with
  `_first_existing(...)`; degrade gracefully (just `return` if the store isn't present).
- **Don't crash the run** — wrap risky parsing in `try/except`; a bad file should skip,
  not abort. (Adapters are already isolated, but be defensive.)
- **Timestamps** via `toms(...)`; **project** via `canonical_project(...)`.
- **Truncate** giant tool args/results if needed (the writer already caps them).

### 3. Test it

```bash
# point at a throwaway data dir so you don't touch your real one
export CHAT_MEMORY_DATA_DIR=/tmp/cm-test CHAT_MEMORY_HOME=/tmp/cm-home
python3 sync.py
ls -R /tmp/cm-test/projects            # inspect the generated Markdown
```

Check: titles are sensible, messages are ordered, projects resolve, no tracebacks.
Run twice — the second run should report everything `unchanged` (idempotent).

### 4. Open a PR

Include:

- [ ] the adapter + `ADAPTERS` entry
- [ ] the harness's storage path/format in the PR description
- [ ] a row added to the **Harness support** table in `README.md`
- [ ] (if the format is non-obvious) a short note in the PR on how you decoded it

## Style

- Standard library only, Python 3.8+.
- Match the surrounding style (no formatter enforced; keep it clean and readable).
- Keep adapters self-contained and defensive.

## Not a coder? Still useful.

Open a **Harness request** issue with:
- the tool name + link
- where it stores chats on your OS (paths)
- one small (redacted) example file

That alone makes it easy for someone else to write the adapter.
