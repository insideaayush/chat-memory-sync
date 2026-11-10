# Roadmap

Ideas and planned work. Contributions welcome — pick anything, or open an issue to
propose something. Ordering is rough priority, not a commitment.

## Harness coverage

- [ ] **Antigravity** — decode the Cascade protobuf LevelDB (`shared_proto_db`).
- [ ] **Windsurf** (Cascade) — same family; likely similar store.
- [ ] **Aider** — `.aider.chat.history.md` / input history.
- [ ] **Cline / Roo Code** (VS Code) — task history in global/workspace storage.
- [ ] **Continue.dev** — `~/.continue/sessions/`.
- [ ] **Zed** — assistant/agent threads.
- [ ] **GitHub Copilot Chat** — VS Code chat session JSON.
- [ ] **Amp**, **Goose**, **Cody**, **Windmill**, … — PRs welcome.

See [CONTRIBUTING.md](CONTRIBUTING.md#adding-a-harness) for the adapter contract.

## Retrieval & memory quality

- [ ] **MCP server** exposing `recall` as a tool, so MCP-capable harnesses can query
      memory natively (no shell needed).
- [ ] **Semantic search** option (local embeddings + vector index) alongside BM25.
- [ ] **Cross-harness dedup** — collapse the same conversation captured by two tools.
- [ ] **Per-chat summaries** / auto-tags in frontmatter for better ranking & scanning.
- [ ] **Incremental indexing** (only re-index changed files) for very large histories.

## Sync & scale

- [ ] **Conflict-free multi-machine** hardening (large concurrent pushes).
- [ ] **History/size management** — optional squash, or Git LFS for the data repo.
- [ ] **Selective sync** — include/exclude projects or harnesses via config.
- [ ] **Redaction/secret-scrubbing** pass before commit (configurable patterns).
- [ ] **Encryption at rest** option for the data repo.

## Tooling & DX

- [ ] **`doctor` command** — verify config, detect installed harnesses, report counts.
- [ ] **One-line installers** (curl | sh) per OS.
- [ ] **CI** — lint + a smoke test that runs adapters against fixture data.
- [ ] **Fixture corpus** — tiny redacted sample stores per harness for tests.
- [ ] **Web/TUI browser** for the data repo.

## Docs

- [ ] Per-harness "where are my chats" reference with screenshots.
- [ ] Example `AGENTS.md`/`CLAUDE.md` snippets per tool (started in
      [docs/agent-integration.md](docs/agent-integration.md)).
