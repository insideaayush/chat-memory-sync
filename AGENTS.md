# AGENTS.md

Guidance for AI agents working in this repo (`chat-memory-sync`).

## What this project is

A tool that exports AI coding chats from many harnesses into one project-organized
Markdown **data repo**, syncs it across machines via git, and exposes a `recall` search
command. See `README.md` for the full picture.

## Ground rules

- **Standard library only.** No third-party Python deps — it must run anywhere with
  `python3` + `git`.
- **Don't break the adapter contract.** Adapters live in `sync.py` and `yield` the
  normalized chat dict documented in `CONTRIBUTING.md`. The writer/indexer depend on it.
- **Be defensive.** Parsing real-world chat stores is messy; a bad file should skip, not
  crash the run. Wrap risky parsing in `try/except`.
- **Idempotency matters.** `sync.py` must only rewrite changed files. Test by running
  twice — the second run should report everything `unchanged`.
- **Never touch the user's real data when testing.** Use throwaway dirs:
  `CHAT_MEMORY_DATA_DIR=/tmp/cm-test CHAT_MEMORY_HOME=/tmp/cm-home python3 sync.py`.

## Adding a harness

Follow `CONTRIBUTING.md` → "Adding a harness". Add the adapter, register it in
`ADAPTERS`, update the support table in `README.md`.

## Prior chat memory

This machine may have `recall` installed. To pull context from past chats across all
tools, run `recall "<keywords>"` (auto-scopes to the current repo) and read the top hits.
See `docs/agent-integration.md`.
