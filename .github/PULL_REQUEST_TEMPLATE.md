## What

Describe the change. If it adds/fixes a harness adapter, name the harness.

## Harness adapters (if applicable)

- Harness:
- Storage path(s) + format:
- [ ] Yields the normalized chat dict (see CONTRIBUTING.md)
- [ ] Registered in `ADAPTERS`
- [ ] Added a row to the Harness support table in `README.md`
- [ ] Degrades gracefully when the store is absent (just `return`)

## Testing

- [ ] Ran against a throwaway dir
      (`CHAT_MEMORY_DATA_DIR=/tmp/cm-test CHAT_MEMORY_HOME=/tmp/cm-home python3 sync.py`)
- [ ] Titles/messages/ordering look correct
- [ ] Ran twice — second run reports everything `unchanged` (idempotent)

## Notes

Standard library only. Anything reviewers should know (e.g. how you decoded a format).
