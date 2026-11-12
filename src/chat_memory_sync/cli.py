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
  serve       browse & search your chats in a local web UI (alias: ui)
  mcp         run the MCP server (exposes recall as a tool to any MCP harness)
  config      show or change config (data dir, client)
  logs        show sync logs (manual + background runs)
  doctor      show config, detected harnesses, and chat counts
  uninstall   remove the background job (keeps your data repo)
  version     print version

examples:
  chat-memory install --local                 # single machine, local folder, no git
  chat-memory install --data-remote git@github.com:you/chat-memory.git
  chat-memory sync
  chat-memory recall "auth token refresh"
  chat-memory serve
  chat-memory config --client macbook-air
  recall "rate limiting" --all
"""


def logs_cmd(argv):
    import argparse, os, time
    from . import cmlib
    ap = argparse.ArgumentParser(prog="chat-memory logs",
                                 description="show sync logs (manual + background runs)")
    ap.add_argument("-n", "--lines", type=int, default=40, help="lines to show (default 40)")
    ap.add_argument("-f", "--follow", action="store_true", help="follow new log output")
    a = ap.parse_args(argv)
    path = os.path.join(cmlib.state_dir(), "sync.log")
    if not os.path.exists(path):
        print(f"no log yet at {path}\n(run `chat-memory sync`, or wait for the daily job)")
        return 0
    with open(path, encoding="utf-8", errors="ignore") as f:
        lines = f.readlines()
    sys.stdout.write("".join(lines[-a.lines:]))
    # flag a job-level failure only if it's newer than the last logged run (not stale)
    errp = os.path.join(cmlib.state_dir(), "launchd.err.log")
    try:
        if (os.path.getsize(errp) > 0 and os.path.getmtime(errp) >= os.path.getmtime(path)):
            sys.stderr.write(f"\n\u26a0 recent background-job error \u2014 see {errp}\n")
    except OSError:
        pass
    if a.follow:
        with open(path, encoding="utf-8", errors="ignore") as f:
            f.seek(0, 2)
            try:
                while True:
                    line = f.readline()
                    if line:
                        sys.stdout.write(line); sys.stdout.flush()
                    else:
                        time.sleep(0.5)
            except KeyboardInterrupt:
                pass
    return 0


def config_cmd(argv):
    import argparse, json, os
    from . import cmlib
    ap = argparse.ArgumentParser(prog="chat-memory config",
                                 description="show or change config")
    ap.add_argument("--data-dir", help="set the data repo location")
    ap.add_argument("--client", help="set this machine's client name")
    a = ap.parse_args(argv)
    cfg = cmlib.load_config()
    changed = False
    if a.data_dir:
        cfg["data_dir"] = os.path.abspath(os.path.expanduser(a.data_dir)); changed = True
    if a.client:
        cfg["client"] = a.client.strip(); changed = True
    if changed:
        cmlib.save_config(cfg); print("updated.\n")
    print(json.dumps(cmlib.load_config(), indent=2))
    print(f"\nconfig file : {cmlib.CONFIG_PATH}")
    print(f"data dir    : {cmlib.data_dir()}")
    print(f"state dir   : {cmlib.state_dir()}")
    return 0


def doctor():
    import os, glob, shutil
    from . import cmlib
    mode = cmlib.mode()
    print(f"chat-memory-sync {__version__}")
    print(f"config file : {cmlib.CONFIG_PATH} ({'exists' if os.path.exists(cmlib.CONFIG_PATH) else 'missing'})")
    print(f"mode        : {mode}" + ("  (local folder, no git)" if mode == 'local' else "  (git sync)"))
    print(f"data dir    : {cmlib.data_dir()} ({'ok' if os.path.isdir(cmlib.data_dir()) else 'missing'})")
    print(f"client      : {cmlib.client_id()}  platform={cmlib.PLATFORM}")
    print(f"recall idx  : {cmlib.index_db()} ({'built' if os.path.exists(cmlib.index_db()) else 'not built'})")
    print(f"recall cmd  : {shutil.which('recall') or 'not on PATH'}")
    n = len(glob.glob(os.path.join(cmlib.projects_dir(), '*', '*', '*.md')))
    print(f"chats stored: {n}")
    logp = os.path.join(cmlib.state_dir(), 'sync.log')
    if os.path.exists(logp):
        tail = open(logp, encoding='utf-8', errors='ignore').readlines()[-40:]
        dones = [l for l in tail if 'sync done' in l]
        issues = [l for l in tail if ('fail' in l.lower() or 'error' in l.lower())]
        last = dones[-1].split('=====')[0].strip() if dones else ''
        print(f"last sync   : {last or 'unknown (see chat-memory logs)'}")
        if issues:
            print(f"  \u26a0 recent issue: {issues[-1].strip()}")
    print(f"logs        : {logp}  (view: chat-memory logs)")


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
    if cmd in ("serve", "ui"):
        from . import web; return web.main(rest)
    if cmd == "mcp":
        from . import mcp; return mcp.main(rest)
    if cmd == "config":
        return config_cmd(rest)
    if cmd == "logs":
        return logs_cmd(rest)
    if cmd == "uninstall":
        from . import install; return install.uninstall_main(rest)
    if cmd in ("doctor", "status"):
        return doctor()
    print(f"unknown command: {cmd}\n", file=sys.stderr)
    print(USAGE, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main() or 0)
