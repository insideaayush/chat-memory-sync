#!/usr/bin/env python3
"""
One-command installer for chat-memory-sync on any machine.

    python3 install.py --data-remote git@github.com:you/chat-memory.git \
                       [--data-dir ~/chat-memory] [--client NAME] [--time HH:MM]

Does:
  1. write ~/.config/chat-memory/config.json (data_dir + client)
  2. clone (or init) the private DATA repo at --data-dir
  3. run the sync once (export + commit + push)
  4. register a daily background job for the current OS:
       macOS -> launchd | Windows -> Task Scheduler | Linux -> systemd timer/cron
  5. install a `recall` command on PATH

Re-running is safe; it overwrites the job and config.
"""
import os, sys, subprocess, platform, argparse, getpass

SYNC_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SYNC_DIR)
import cmlib

RUN = os.path.join(SYNC_DIR, "run.py")
RECALL = os.path.join(SYNC_DIR, "recall.py")
PY = sys.executable or "python3"
LABEL = "com.user.chat-memory-sync"


def sh(cmd, **kw):
    print("+", " ".join(cmd) if isinstance(cmd, list) else cmd)
    return subprocess.run(cmd, **kw)


# ----------------------------------------------------------- schedulers ------

def _mac_launcher():
    import shutil
    cc = shutil.which("cc") or shutil.which("clang")
    if not cc:
        return None
    bindir = os.path.expanduser("~/bin")
    srcdir = os.path.join(bindir, ".src")
    os.makedirs(srcdir, exist_ok=True)
    src = os.path.join(srcdir, "chat-memory-sync.c")
    out = os.path.join(bindir, "chat-memory-sync")
    open(src, "w").write(
        "#include <unistd.h>\n#include <sys/wait.h>\nint main(void){\n"
        "  pid_t p=fork();\n  if(p==0){\n"
        f'    char *a[]={{"chat-memory-sync","{RUN}",(char*)0}};\n'
        f'    execv("{PY}",a);\n    _exit(127);\n  }}\n'
        "  int s=0; waitpid(p,&s,0);\n  return WIFEXITED(s)?WEXITSTATUS(s):1;\n}\n")
    if subprocess.run([cc, "-O2", "-o", out, src], capture_output=True).returncode == 0:
        return out
    return None


def install_mac(hh, mm):
    launcher = _mac_launcher()
    prog = (f"<array><string>{launcher}</string></array>" if launcher
            else f"<array><string>{PY}</string><string>{RUN}</string></array>")
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
    pyw = PY
    cand = os.path.join(os.path.dirname(PY), "pythonw.exe")
    if os.path.isfile(cand):
        pyw = cand
    sh(["schtasks", "/Create", "/F", "/TN", "ChatMemorySync",
        "/SC", "DAILY", "/ST", f"{hh:02d}:{mm:02d}", "/TR", f'"{pyw}" "{RUN}"'])
    print(f"Task Scheduler job 'ChatMemorySync' installed (daily {hh:02d}:{mm:02d})")


def install_linux(hh, mm):
    unit_dir = os.path.expanduser("~/.config/systemd/user")
    have_systemd = subprocess.run(["systemctl", "--user", "--version"],
                                  capture_output=True).returncode == 0
    if have_systemd:
        os.makedirs(unit_dir, exist_ok=True)
        open(os.path.join(unit_dir, "chat-memory-sync.service"), "w").write(
            f"[Unit]\nDescription=chat-memory sync\n\n[Service]\nType=oneshot\n"
            f"ExecStart={PY} {RUN}\n")
        open(os.path.join(unit_dir, "chat-memory-sync.timer"), "w").write(
            f"[Unit]\nDescription=daily chat-memory sync\n\n[Timer]\n"
            f"OnCalendar=*-*-* {hh:02d}:{mm:02d}:00\nPersistent=true\n\n"
            f"[Install]\nWantedBy=timers.target\n")
        sh(["systemctl", "--user", "daemon-reload"])
        sh(["systemctl", "--user", "enable", "--now", "chat-memory-sync.timer"])
        print(f"systemd user timer installed (daily {hh:02d}:{mm:02d}). "
              f"Tip: `loginctl enable-linger {getpass.getuser()}` to run while logged out.")
        return
    line = f"{mm} {hh} * * * {PY} {RUN} >> {cmlib.state_dir()}/cron.log 2>&1"
    cur = subprocess.run(["crontab", "-l"], capture_output=True, text=True).stdout
    lines = [l for l in cur.splitlines() if "chat-memory" not in l and RUN not in l]
    lines.append(line + "  # chat-memory")
    subprocess.run(["crontab", "-"], input="\n".join(lines) + "\n", text=True)
    print(f"cron job installed (daily {hh:02d}:{mm:02d})")


def install_recall_launcher():
    home = os.path.expanduser("~")
    if platform.system() == "Windows":
        bindir = os.path.join(home, "bin")
        os.makedirs(bindir, exist_ok=True)
        p = os.path.join(bindir, "recall.cmd")
        open(p, "w").write(f'@echo off\r\n"{PY}" "{RECALL}" %*\r\n')
        print(f"recall command -> {p}  (ensure {bindir} is on PATH)")
        return
    path_dirs = os.environ.get("PATH", "").split(":")
    prefs = [os.path.join(home, ".local/bin"), os.path.join(home, "bin")]
    bindir = next((d for d in prefs if d in path_dirs), os.path.join(home, "bin"))
    os.makedirs(bindir, exist_ok=True)
    p = os.path.join(bindir, "recall")
    open(p, "w").write(f'#!/bin/bash\nexec "{PY}" "{RECALL}" "$@"\n')
    os.chmod(p, 0o755)
    if bindir in path_dirs:
        print(f"recall command -> {p}")
    else:
        print(f"recall command -> {p}\n  NOTE: add to PATH:\n"
              f'    echo \'export PATH="{bindir}:$PATH"\' >> ~/.zshrc  (then open a new shell)')


# ----------------------------------------------------------- data repo -------

def setup_data_repo(data_dir, remote):
    if os.path.isdir(os.path.join(data_dir, ".git")):
        print(f"data repo already present: {data_dir}")
        return
    os.makedirs(os.path.dirname(os.path.abspath(data_dir)) or ".", exist_ok=True)
    if remote:
        r = sh(["git", "clone", remote, data_dir])
        if r.returncode != 0:
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

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-remote", help="git URL of your private data repo (recommended)")
    ap.add_argument("--data-dir", help="where the data repo lives (default ~/chat-memory)")
    ap.add_argument("--client", help="name for this machine (default: hostname)")
    ap.add_argument("--time", default="21:00", help="daily run time HH:MM (default 21:00)")
    args = ap.parse_args()

    cfg = cmlib.load_config()
    data_dir = os.path.abspath(os.path.expanduser(
        args.data_dir or cfg.get("data_dir") or os.path.join(cmlib.HOME, "chat-memory")))
    cfg["data_dir"] = data_dir
    if args.client:
        cfg["client"] = args.client.strip()
    cmlib.save_config(cfg)
    print(f"config -> {cmlib.CONFIG_PATH}\n  data_dir = {data_dir}\n  client   = {cmlib.client_id()}")

    try:
        hh, mm = [int(x) for x in args.time.split(":")]
    except Exception:
        print("bad --time, expected HH:MM"); sys.exit(1)

    print("\n== data repo ==")
    setup_data_repo(data_dir, args.data_remote)

    print("\n== first run ==")
    rc = subprocess.run([PY, RUN]).returncode
    if rc != 0:
        print("first run returned non-zero; check the log in", cmlib.state_dir())

    print("\n== background job ==")
    s = platform.system()
    (install_mac if s == "Darwin" else install_windows if s == "Windows" else install_linux)(hh, mm)

    print("\n== recall command ==")
    install_recall_launcher()

    print("\nDone. The background job keeps this machine's chats synced daily.")
    has_origin = subprocess.run(["git", "remote", "get-url", "origin"],
                                cwd=data_dir, capture_output=True).returncode == 0
    if not has_origin:
        print("NOTE: data repo has no 'origin' remote - chats commit locally but won't push.\n"
              f"      git -C {data_dir} remote add origin <url> && git -C {data_dir} push -u origin HEAD")


if __name__ == "__main__":
    main()
