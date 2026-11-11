#!/usr/bin/env python3
"""
Installer: config + data repo + background job + recall command.

Invoked as `chat-memory install ...`. Registers a daily job that runs
`chat-memory sync` via the OS scheduler (launchd / Task Scheduler / systemd|cron).
"""
import os, sys, subprocess, platform, argparse, getpass, shutil
from . import cmlib

PY = sys.executable or "python3"
LABEL = "com.user.chat-memory-sync"


def sh(cmd, **kw):
    print("+", " ".join(cmd) if isinstance(cmd, list) else cmd)
    return subprocess.run(cmd, **kw)


def sync_command():
    """The command the scheduler should run to perform a sync."""
    exe = shutil.which("chat-memory")
    if exe:
        return [exe, "sync"]
    return [PY, "-m", "chat_memory_sync", "sync"]


def recall_command_str():
    exe = shutil.which("recall")
    if exe:
        return None  # already on PATH via the package entry point
    return f'"{PY}" -m chat_memory_sync.recall'


# ----------------------------------------------------------- schedulers ------

def _mac_launcher(cmd):
    """Compile a Mach-O named 'chat-memory-sync' so Login Items shows a friendly
    name instead of the interpreter. Returns its path or None."""
    cc = shutil.which("cc") or shutil.which("clang")
    if not cc:
        return None
    bindir = os.path.expanduser("~/bin")
    srcdir = os.path.join(bindir, ".src")
    os.makedirs(srcdir, exist_ok=True)
    src = os.path.join(srcdir, "chat-memory-sync.c")
    out = os.path.join(bindir, "chat-memory-sync")
    argv = ", ".join(['"chat-memory-sync"'] + [f'"{a}"' for a in cmd[1:]] + ["(char*)0"])
    open(src, "w").write(
        "#include <unistd.h>\n#include <sys/wait.h>\nint main(void){\n"
        "  pid_t p=fork();\n  if(p==0){\n"
        f"    char *a[]={{{argv}}};\n"
        f'    execv("{cmd[0]}",a);\n    _exit(127);\n  }}\n'
        "  int s=0; waitpid(p,&s,0);\n  return WIFEXITED(s)?WEXITSTATUS(s):1;\n}\n")
    if subprocess.run([cc, "-O2", "-o", out, src], capture_output=True).returncode == 0:
        return out
    return None


def install_mac(hh, mm):
    cmd = sync_command()
    launcher = _mac_launcher(cmd)
    if launcher:
        prog = f"<array><string>{launcher}</string></array>"
    else:
        prog = "<array>" + "".join(f"<string>{a}</string>" for a in cmd) + "</array>"
    state = cmlib.state_dir()
    plist = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key><string>{LABEL}</string>
    <key>ProgramArguments</key>
    {prog}
    <key>StartCalendarInterval</key>
    <dict><key>Hour</key><integer>{hh}</integer><key>Minute</key><integer>{mm}</integer></dict>
    <key>RunAtLoad</key><false/>
    <key>StandardOutPath</key><string>{state}/launchd.out.log</string>
    <key>StandardErrorPath</key><string>{state}/launchd.err.log</string>
</dict>
</plist>
"""
    dest = os.path.expanduser(f"~/Library/LaunchAgents/{LABEL}.plist")
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    open(dest, "w").write(plist)
    uid = os.getuid()
    subprocess.run(["launchctl", "bootout", f"gui/{uid}/{LABEL}"], capture_output=True)
    subprocess.run(["launchctl", "load", dest])
    print(f"launchd job installed -> {dest}  (daily {hh:02d}:{mm:02d})")


def install_windows(hh, mm):
    cmd = sync_command()
    tr = " ".join(f'"{a}"' if " " in a else a for a in cmd)
    sh(["schtasks", "/Create", "/F", "/TN", "ChatMemorySync",
        "/SC", "DAILY", "/ST", f"{hh:02d}:{mm:02d}", "/TR", tr])
    print(f"Task Scheduler job 'ChatMemorySync' installed (daily {hh:02d}:{mm:02d})")


def install_linux(hh, mm):
    cmd = " ".join(sync_command())
    unit_dir = os.path.expanduser("~/.config/systemd/user")
    have_systemd = subprocess.run(["systemctl", "--user", "--version"],
                                  capture_output=True).returncode == 0
    if have_systemd:
        os.makedirs(unit_dir, exist_ok=True)
        open(os.path.join(unit_dir, "chat-memory-sync.service"), "w").write(
            f"[Unit]\nDescription=chat-memory sync\n\n[Service]\nType=oneshot\n"
            f"ExecStart={cmd}\n")
        open(os.path.join(unit_dir, "chat-memory-sync.timer"), "w").write(
            f"[Unit]\nDescription=daily chat-memory sync\n\n[Timer]\n"
            f"OnCalendar=*-*-* {hh:02d}:{mm:02d}:00\nPersistent=true\n\n"
            f"[Install]\nWantedBy=timers.target\n")
        sh(["systemctl", "--user", "daemon-reload"])
        sh(["systemctl", "--user", "enable", "--now", "chat-memory-sync.timer"])
        print(f"systemd user timer installed (daily {hh:02d}:{mm:02d}). "
              f"Tip: `loginctl enable-linger {getpass.getuser()}` to run while logged out.")
        return
    line = f"{mm} {hh} * * * {cmd} >> {cmlib.state_dir()}/cron.log 2>&1"
    cur = subprocess.run(["crontab", "-l"], capture_output=True, text=True).stdout
    lines = [l for l in cur.splitlines() if "chat-memory" not in l]
    lines.append(line + "  # chat-memory")
    subprocess.run(["crontab", "-"], input="\n".join(lines) + "\n", text=True)
    print(f"cron job installed (daily {hh:02d}:{mm:02d})")


def install_recall_launcher():
    if shutil.which("recall"):
        print("recall command already on PATH (package entry point)")
        return
    cmd = recall_command_str()
    home = os.path.expanduser("~")
    if platform.system() == "Windows":
        bindir = os.path.join(home, "bin")
        os.makedirs(bindir, exist_ok=True)
        p = os.path.join(bindir, "recall.cmd")
        open(p, "w").write(f'@echo off\r\n{cmd} %*\r\n')
        print(f"recall command -> {p}  (ensure {bindir} is on PATH)")
        return
    path_dirs = os.environ.get("PATH", "").split(":")
    prefs = [os.path.join(home, ".local/bin"), os.path.join(home, "bin")]
    bindir = next((d for d in prefs if d in path_dirs), os.path.join(home, "bin"))
    os.makedirs(bindir, exist_ok=True)
    p = os.path.join(bindir, "recall")
    open(p, "w").write(f'#!/bin/bash\nexec {cmd} "$@"\n')
    os.chmod(p, 0o755)
    print(f"recall command -> {p}" + ("" if bindir in path_dirs else f"  (add {bindir} to PATH)"))


# ----------------------------------------------------------- data repo -------

def setup_data_repo(data_dir, remote):
    if os.path.isdir(os.path.join(data_dir, ".git")):
        print(f"data repo already present: {data_dir}")
        return
    os.makedirs(os.path.dirname(os.path.abspath(data_dir)) or ".", exist_ok=True)
    if remote:
        if sh(["git", "clone", remote, data_dir]).returncode != 0:
            print("clone failed; initializing empty repo instead")
            _init_repo(data_dir, remote)
    else:
        _init_repo(data_dir, None)


def _init_repo(data_dir, remote):
    os.makedirs(data_dir, exist_ok=True)
    sh(["git", "init", "-q", data_dir])
    if remote:
        sh(["git", "-C", data_dir, "remote", "add", "origin", remote])


# ----------------------------------------------------------------- main ------

def main(argv=None):
    ap = argparse.ArgumentParser(prog="chat-memory install")
    ap.add_argument("--local", action="store_true",
                    help="single-machine mode: store chats in a local folder (no git/remote)")
    ap.add_argument("--data-remote", help="git URL of your private data repo (recommended for multi-machine)")
    ap.add_argument("--data-dir", help="where chats are stored (default ~/chat-memory)")
    ap.add_argument("--client", help="name for this machine (default: hostname)")
    ap.add_argument("--time", default="21:00", help="daily run time HH:MM (default 21:00)")
    ap.add_argument("--no-job", action="store_true", help="skip registering the background job")
    args = ap.parse_args(argv)

    cfg = cmlib.load_config()
    data_dir = os.path.abspath(os.path.expanduser(
        args.data_dir or cfg.get("data_dir") or os.path.join(cmlib.HOME, "chat-memory")))
    cfg["data_dir"] = data_dir
    if args.client:
        cfg["client"] = args.client.strip()
    mode = "local" if args.local else cfg.get("mode", "git")
    cfg["mode"] = mode
    cmlib.save_config(cfg)
    print(f"config -> {cmlib.CONFIG_PATH}\n  mode     = {mode}\n  data_dir = {data_dir}\n  client   = {cmlib.client_id()}")

    try:
        hh, mm = [int(x) for x in args.time.split(":")]
    except Exception:
        print("bad --time, expected HH:MM"); sys.exit(1)

    if mode == "local":
        os.makedirs(data_dir, exist_ok=True)
        print(f"\n== local mode ==\nchats stored at {data_dir} (no git)")
    else:
        print("\n== data repo ==")
        setup_data_repo(data_dir, args.data_remote)

    print("\n== first run ==")
    if subprocess.run(sync_command()).returncode != 0:
        print("first run returned non-zero; check the log in", cmlib.state_dir())

    if not args.no_job:
        print("\n== background job ==")
        s = platform.system()
        (install_mac if s == "Darwin" else install_windows if s == "Windows" else install_linux)(hh, mm)

    print("\n== recall command ==")
    install_recall_launcher()

    print("\nDone. The background job keeps this machine's chats up to date daily.")
    if mode != "local":
        has_origin = subprocess.run(["git", "remote", "get-url", "origin"],
                                    cwd=data_dir, capture_output=True).returncode == 0
        if not has_origin:
            print("NOTE: data repo has no 'origin' remote - chats commit locally but won't push.\n"
                  f"      git -C {data_dir} remote add origin <url> && git -C {data_dir} push -u origin HEAD\n"
                  "      (or re-run with --local for single-machine, no-git mode)")


# ----------------------------------------------------------- uninstall -------

def _remove_job():
    s = platform.system()
    if s == "Darwin":
        dest = os.path.expanduser(f"~/Library/LaunchAgents/{LABEL}.plist")
        subprocess.run(["launchctl", "bootout", f"gui/{os.getuid()}/{LABEL}"], capture_output=True)
        for p in (dest, os.path.expanduser("~/bin/chat-memory-sync"),
                  os.path.expanduser("~/bin/.src/chat-memory-sync.c")):
            try:
                if os.path.exists(p):
                    os.remove(p)
            except Exception:
                pass
        print("removed launchd job")
    elif s == "Windows":
        subprocess.run(["schtasks", "/Delete", "/F", "/TN", "ChatMemorySync"], capture_output=True)
        print("removed Task Scheduler job")
    else:
        ud = os.path.expanduser("~/.config/systemd/user")
        if subprocess.run(["systemctl", "--user", "--version"], capture_output=True).returncode == 0:
            subprocess.run(["systemctl", "--user", "disable", "--now", "chat-memory-sync.timer"], capture_output=True)
            for f in ("chat-memory-sync.timer", "chat-memory-sync.service"):
                p = os.path.join(ud, f)
                try:
                    if os.path.exists(p):
                        os.remove(p)
                except Exception:
                    pass
            subprocess.run(["systemctl", "--user", "daemon-reload"], capture_output=True)
        cur = subprocess.run(["crontab", "-l"], capture_output=True, text=True).stdout
        if "chat-memory" in cur:
            lines = [l for l in cur.splitlines() if "chat-memory" not in l]
            subprocess.run(["crontab", "-"], input="\n".join(lines) + "\n", text=True)
        print("removed scheduled job")


def _remove_recall_launcher():
    for d in ("~/.local/bin/recall", "~/bin/recall"):
        p = os.path.expanduser(d)
        try:
            if os.path.isfile(p) and "chat_memory_sync" in open(p).read():
                os.remove(p); print("removed", p)
        except Exception:
            pass


def uninstall_main(argv=None):
    ap = argparse.ArgumentParser(prog="chat-memory uninstall",
                                 description="remove the background job (your data repo is left intact)")
    ap.add_argument("--purge", action="store_true",
                    help="also delete local config + search index (NOT the data repo)")
    a = ap.parse_args(argv)
    _remove_job()
    _remove_recall_launcher()
    if a.purge:
        import shutil
        if os.path.isdir(cmlib.CONFIG_DIR):
            shutil.rmtree(cmlib.CONFIG_DIR, ignore_errors=True)
            print("removed config dir", cmlib.CONFIG_DIR)
    print("Done. Your chat data repo was not touched.")
    return 0


if __name__ == "__main__":
    main()
