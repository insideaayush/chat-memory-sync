#!/usr/bin/env python3
"""Unified `chat-memory` CLI."""
import sys
from . import __version__

USAGE = """chat-memory - unified memory bank of your AI coding chats

usage: chat-memory <command> [options]

commands:
  install     set up config, data repo, daily background job, recall command
  sync        pull -> export all harnesses -> commit -> push (what the job runs)
  export      export only (no git)
  recall      search past chats (also available as the `recall` command)
  doctor      show config, detected harnesses, and chat counts
  version     print version

examples:
  chat-memory install --data-remote git@github.com:you/chat-memory.git
  chat-memory sync
  chat-memory recall "auth token refresh"
  recall "rate limiting" --all
"""


def doctor():
    import os, glob, shutil
    from . import cmlib
    print(f"chat-memory-sync {__version__}")
    print(f"config file : {cmlib.CONFIG_PATH} ({'exists' if os.path.exists(cmlib.CONFIG_PATH) else 'missing'})")
    print(f"data dir    : {cmlib.data_dir()} ({'ok' if os.path.isdir(cmlib.data_dir()) else 'missing'})")
    print(f"client      : {cmlib.client_id()}  platform={cmlib.PLATFORM}")
    print(f"recall idx  : {cmlib.index_db()} ({'built' if os.path.exists(cmlib.index_db()) else 'not built'})")
    print(f"recall cmd  : {shutil.which('recall') or 'not on PATH'}")
    n = len(glob.glob(os.path.join(cmlib.projects_dir(), '*', '*', '*.md')))
    print(f"chats stored: {n}")


def main():
    argv = sys.argv[1:]
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(USAGE); return 0
    cmd, rest = argv[0], argv[1:]
    if cmd in ("version", "--version", "-V"):
        print(f"chat-memory-sync {__version__}"); return 0
    if cmd == "install":
        from . import install; return install.main(rest)
    if cmd in ("sync", "run"):
        from . import run; return run.main()
    if cmd == "export":
        from . import sync; return sync.main()
    if cmd == "recall":
        from . import recall; return recall.main(rest)
    if cmd in ("doctor", "status"):
        return doctor()
    print(f"unknown command: {cmd}\n", file=sys.stderr)
    print(USAGE, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main() or 0)
