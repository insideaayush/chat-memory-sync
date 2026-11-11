#!/usr/bin/env python3
"""
Shared config/paths for chat-memory-sync.

Decouples the (public) tooling from the (private) data repo:

  - data repo location:  $CHAT_MEMORY_DATA_DIR > config.json "data_dir" > ~/chat-memory
  - machine-local state: $CHAT_MEMORY_HOME     > ~/.config/chat-memory
      (holds config.json, index.db, client, sync.log -- never in the data repo)
  - client name:         $CHAT_MEMORY_CLIENT   > config.json "client" > hostname
"""
import os, json, re, platform, socket

HOME = os.path.expanduser("~")
CONFIG_DIR = os.path.expanduser(os.environ.get("CHAT_MEMORY_HOME") or os.path.join(HOME, ".config", "chat-memory"))
CONFIG_PATH = os.path.join(CONFIG_DIR, "config.json")

PLATFORM = {"Darwin": "mac", "Windows": "pc", "Linux": "linux"}.get(platform.system(), platform.system().lower())


def load_config():
    try:
        return json.load(open(CONFIG_PATH))
    except Exception:
        return {}


def save_config(cfg):
    os.makedirs(CONFIG_DIR, exist_ok=True)
    json.dump(cfg, open(CONFIG_PATH, "w"), indent=2)


def state_dir():
    os.makedirs(CONFIG_DIR, exist_ok=True)
    return CONFIG_DIR


def data_dir():
    v = os.environ.get("CHAT_MEMORY_DATA_DIR")
    if v:
        return os.path.abspath(os.path.expanduser(v))
    c = load_config().get("data_dir")
    if c:
        return os.path.abspath(os.path.expanduser(c))
    return os.path.join(HOME, "chat-memory")


def projects_dir():
    return os.path.join(data_dir(), "projects")


def mode():
    """'local' (plain folder, no git) or 'git' (synced repo).
    Default is local; existing git repos are auto-detected so pre-config installs
    aren't disrupted."""
    m = load_config().get("mode")
    if m:
        return m
    return "git" if os.path.isdir(os.path.join(data_dir(), ".git")) else "local"


def index_db():
    return os.path.join(state_dir(), "index.db")


def _cslug(s):
    s = re.sub(r"[^\w\-]", "-", (s or "").strip().lower())
    s = re.sub(r"-+", "-", s).strip("-")
    return s[:40] or "unknown-client"


def client_id():
    v = os.environ.get("CHAT_MEMORY_CLIENT")
    if v and v.strip():
        return _cslug(v)
    c = load_config().get("client")
    if c:
        return _cslug(c)
    name = socket.gethostname().split(".")[0]
    cfg = load_config()
    cfg["client"] = name
    try:
        save_config(cfg)
    except Exception:
        pass
    return _cslug(name)
