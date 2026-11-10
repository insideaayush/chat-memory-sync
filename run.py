#!/usr/bin/env python3
"""
Cross-platform sync runner: git pull -> export all harnesses -> commit -> push.
Works on mac / windows / linux (only needs `git` + `python3`). Scheduled by the
platform background job; also safe to run manually:  python3 run.py
"""
import os, sys, subprocess, datetime

SYNC_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SYNC_DIR)
import cmlib

REPO = cmlib.data_dir()
LOG = os.path.join(cmlib.state_dir(), "sync.log")


def log(msg):
    line = f"{datetime.datetime.now():%Y-%m-%d %H:%M:%S} {msg}"
    print(line)
    try:
        with open(LOG, "a") as f:
            f.write(line + "\n")
    except Exception:
        pass


def git(*args, check=False):
    r = subprocess.run(["git", *args], cwd=REPO, capture_output=True, text=True)
    if check and r.returncode != 0:
        log(f"git {' '.join(args)} failed: {r.stderr.strip()}")
    return r


def ensure_identity():
    """Commit as the user's own git identity. Only set a neutral fallback if the
    machine has no identity configured at all (so a fresh box doesn't error)."""
    if git("config", "user.email").stdout.strip():
        return
    git("config", "user.name", "chat-memory-sync")
    git("config", "user.email", "chat-memory-sync@users.noreply.github.com")


def main():
    log("===== sync start =====")

    if not os.path.isdir(os.path.join(REPO, ".git")):
        git("init")
        ensure_identity()
        git("add", "-A")
        git("commit", "-m", "Initial export")
    ensure_identity()

    has_origin = git("remote", "get-url", "origin").returncode == 0
    branch = (git("rev-parse", "--abbrev-ref", "HEAD").stdout.strip() or "main")

    if has_origin:
        r = git("pull", "--rebase", "--autostash", "origin", branch)
        log("pulled from origin" if r.returncode == 0 else "pull failed (continuing)")

    # export (import after sys.path setup)
    import sync as exporter
    exporter.main()

    # warm the recall full-text index so first query after a sync is instant
    try:
        import recall
        recall.ensure_index(force=True)
        log("recall index rebuilt")
    except Exception as e:
        log(f"recall index skipped: {e}")

    if git("status", "--porcelain").stdout.strip():
        host = subprocess.run(["hostname"], capture_output=True, text=True).stdout.strip() or "machine"
        git("add", "-A")
        git("commit", "-m", f"Sync chat memory ({host}) {datetime.datetime.now():%Y-%m-%d %H:%M}")
        log("committed changes")
        if has_origin:
            if git("push", "origin", branch).returncode != 0:
                log("push rejected, rebasing and retrying")
                git("pull", "--rebase", "--autostash", "origin", branch)
                r = git("push", "origin", branch)
                log("pushed after retry" if r.returncode == 0 else "push failed")
            else:
                log("pushed to origin")
    else:
        log("no changes")

    log("===== sync done =====")


if __name__ == "__main__":
    main()
