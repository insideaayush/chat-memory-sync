---
name: Harness request / support
about: Request support for an AI coding tool, or share where it stores chats
title: "[harness] <tool name>"
labels: ["harness", "help wanted"]
---

## Tool

- Name:
- Link / docs:
- Version:
- OS you use it on: macOS / Windows / Linux

## Where it stores chats (the most useful part!)

Help us locate the chat store. Common spots: `~/.<tool>/`, `~/.config/<tool>/`,
`~/.local/share/<tool>/`, `~/Library/Application Support/<Tool>/`, or a VS Code–style
`…/User/globalStorage/state.vscdb`.

- Path(s):
- Format: JSONL / SQLite / per-session JSON / other:

## Sample (optional but very helpful)

A small **redacted** example file (one session), or the output of e.g.:

```bash
# list candidate dirs
ls -la ~/.<tool> 2>/dev/null
# peek a session file
head -c 500 "<path to a session file>"
```

## Anything else

Notes on how the data is structured, multiple sessions per file, etc.
