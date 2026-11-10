#!/usr/bin/env python3
"""
chat-memory sync: export chats from multiple AI coding harnesses into one
project-organized Markdown memory bank.

Harnesses: cursor, cursor-agent, claude-code, opencode, pi, codex, gemini.

Each chat -> <data_dir>/projects/<project>/<harness>/<date>_<client>_<slug>_<id8>.md
with YAML frontmatter. Per-project and global INDEX.md are regenerated. Idempotent:
files are only rewritten when content changes (updates to OLD chats included).

Data-repo location + client come from cmlib (config-driven, machine-local state).
"""
import json, os, sqlite3, re, glob, datetime, socket, platform
from collections import defaultdict
from . import cmlib

HOME = os.path.expanduser("~")
OUT = cmlib.data_dir()
PROJ_DIR = cmlib.projects_dir()
CLIENT = cmlib.client_id()
PLATFORM = cmlib.PLATFORM

def _first_existing(paths):
    for p in paths:
        if p and os.path.exists(p):
            return p
    return paths[0] if paths else ""

def cursor_user_dir():
    s = platform.system()
    if s == "Darwin":
        return os.path.join(HOME, "Library/Application Support/Cursor/User")
    if s == "Windows":
        appdata = os.environ.get("APPDATA", os.path.join(HOME, "AppData", "Roaming"))
        return os.path.join(appdata, "Cursor", "User")
    return os.path.join(HOME, ".config/Cursor/User")

def opencode_db_path():
    cands = [os.path.join(HOME, ".local/share/opencode/opencode.db")]
    la = os.environ.get("LOCALAPPDATA")
    if la:
        cands.append(os.path.join(la, "opencode", "opencode.db"))
    cands.append(os.path.join(HOME, "Library/Application Support/opencode/opencode.db"))
    return _first_existing(cands)

# ---------------------------------------------------------------- helpers ----

def toms(x):
    if isinstance(x, (int, float)):
        return int(x)
    if isinstance(x, str):
        try:
            return int(datetime.datetime.fromisoformat(x.replace("Z", "+00:00")).timestamp() * 1000)
        except Exception:
            return 0
    return 0

def iso(ms):
    if not ms:
        return ""
    try:
        return datetime.datetime.fromtimestamp(ms / 1000).strftime("%Y-%m-%dT%H:%M:%S")
    except Exception:
        return ""

def datestr(ms):
    try:
        return datetime.datetime.fromtimestamp(ms / 1000).strftime("%Y-%m-%d") if ms else "nodate"
    except Exception:
        return "nodate"

def slug(s, n=55):
    s = re.sub(r"\s+", " ", (s or "").strip())
    s = re.sub(r"[^\w\- ]", "", s).strip().replace(" ", "-")
    return s[:n] or "untitled"

# parents under which the first segment is the project/repo name
WS_MARKERS = ["/ws/", "/pspace/", "/src/", "/code/", "/projects/", "/Developer/"]

def canonical_project(path):
    """Map any cwd/worktree/subapp path to a single repo-level project key."""
    if not path:
        return "_unknown"
    p = path.rstrip("/")
    for m in WS_MARKERS:
        i = p.find(m)
        if i != -1:
            rest = p[i + len(m):].split("/")
            rest = [x for x in rest if x]
            if not rest:
                continue
            if rest[0] == ".worktrees" and len(rest) > 1:
                return slug(rest[1], 60)
            return slug(rest[0], 60)
    base = os.path.basename(p)
    return slug(base, 60) if base else "_unknown"

def render_message(m):
    role = m.get("role", "?")
    label = {"user": "User", "assistant": "Assistant", "system": "System"}.get(role, role.title())
    model = m.get("model") or ""
    hdr = f"### {label}" + (f"  _(model: {model})_" if model and role == "assistant" else "")
    body = []
    th = (m.get("thinking") or "").strip()
    if th:
        body.append("<details><summary>thinking</summary>\n\n" + th + "\n\n</details>")
    txt = (m.get("text") or "").strip()
    if txt:
        body.append(txt)
    for t in (m.get("tools") or []):
        nm = t.get("name") or "tool"
        args = t.get("args") or ""
        if not isinstance(args, str):
            args = json.dumps(args, ensure_ascii=False)
        if len(args) > 1200:
            args = args[:1200] + " ...(truncated)"
        block = f"**\u2192 tool: `{nm}`**"
        if args.strip():
            block += f"\n```json\n{args}\n```"
        res = t.get("result")
        if isinstance(res, str) and res.strip():
            r = res if len(res) < 1000 else res[:1000] + " ...(truncated)"
            block += f"\n<details><summary>result</summary>\n\n```\n{r}\n```\n\n</details>"
        body.append(block)
    if not body:
        return None
    return hdr + "\n\n" + "\n\n".join(body)

def render_chat(c):
    msgs = [render_message(m) for m in c["messages"]]
    msgs = [m for m in msgs if m]
    if not msgs:
        return None
    models = ", ".join(sorted({m for m in c.get("models", []) if m}))
    title = c["title"] or c["id"][:8]
    fm = [
        "---",
        f"client: {c.get('client', CLIENT)}",
        f"platform: {c.get('platform', PLATFORM)}",
        f"harness: {c['harness']}",
        f"chat_id: {c['id']}",
        f"project: {c['project']}",
        f"source_path: {c.get('source_path','') or ''}",
        f"title: {json.dumps(title, ensure_ascii=False)}",
        f"created: {iso(c['created'])}",
        f"updated: {iso(c['updated'])}",
        f"models: {json.dumps(models)}",
        f"messages: {len(msgs)}",
        "---",
        "",
        f"# {title}",
        "",
    ]
    return "\n".join(fm) + "\n\n".join(msgs) + "\n"

def write_if_changed(path, content):
    if os.path.isfile(path):
        with open(path) as f:
            if f.read() == content:
                return "unchanged"
        st = "updated"
    else:
        st = "new"
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(content)
    return st

# --------------------------------------------------------------- CURSOR ------

def cursor_chats():
    userdir = cursor_user_dir()
    db = os.path.join(userdir, "globalStorage", "state.vscdb")
    if not os.path.isfile(db):
        return
    # workspace fallback map (composerId -> folder)
    wsmap = {}
    wsroot = os.path.join(userdir, "workspaceStorage")
    for d in glob.glob(os.path.join(wsroot, "*")):
        dbp = os.path.join(d, "state.vscdb")
        if not os.path.isfile(dbp):
            continue
        folder = ""
        j = os.path.join(d, "workspace.json")
        if os.path.isfile(j):
            try:
                folder = json.load(open(j)).get("folder", "").replace("file://", "")
            except Exception:
                pass
        try:
            con = sqlite3.connect(f"file:{dbp}?mode=ro", uri=True)
            r = con.execute("SELECT value FROM ItemTable WHERE key='composer.composerData'").fetchone()
            if r:
                for comp in json.loads(r[0]).get("allComposers", []):
                    cid = comp.get("composerId")
                    if cid:
                        wsmap[cid] = folder
            con.close()
        except Exception:
            pass

    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    cur = con.cursor()
    fetch = con.cursor()
    bub = defaultdict(list)
    cur.execute("SELECT key FROM cursorDiskKV WHERE key LIKE 'bubbleId:%'")
    for (k,) in cur.fetchall():
        parts = k.split(":", 2)
        if len(parts) == 3:
            bub[parts[1]].append(parts[2])

    cur.execute("SELECT value FROM cursorDiskKV WHERE key LIKE 'composerData:%'")
    comps = []
    for (v,) in cur.fetchall():
        try:
            comps.append(json.loads(v))
        except Exception:
            pass

    def get_thinking(b):
        out = []
        th = b.get("thinking")
        if isinstance(th, str) and th.strip():
            try:
                j = json.loads(th)
                out.append(j.get("text") if isinstance(j, dict) else th)
            except Exception:
                out.append(th)
        elif isinstance(th, dict) and th.get("text"):
            out.append(th["text"])
        for t in (b.get("allThinkingBlocks") or []):
            if isinstance(t, dict) and (t.get("text") or t.get("content")):
                out.append(t.get("text") or t.get("content"))
        return "\n\n".join(x.strip() for x in out if x and x.strip())

    for d in comps:
        cid = d.get("composerId")
        if not cid:
            continue
        headers = d.get("fullConversationHeadersOnly") or []
        created = toms(d.get("createdAt"))
        updated = toms(d.get("lastUpdatedAt")) or created
        src = ""
        wi = d.get("workspaceIdentifier") or {}
        if isinstance(wi, dict):
            uri = wi.get("uri") or {}
            if isinstance(uri, dict):
                src = uri.get("fsPath") or uri.get("path") or ""
        if not src:
            src = wsmap.get(cid, "")
        if headers:
            keys = [f"bubbleId:{cid}:{h.get('bubbleId')}" for h in headers if isinstance(h, dict) and h.get("bubbleId")]
            ordered_keys = keys
        else:
            keys = [f"bubbleId:{cid}:{b}" for b in bub.get(cid, [])]
            ordered_keys = None
        rows = {}
        for i in range(0, len(keys), 400):
            chunk = keys[i:i + 400]
            q = "SELECT key,value FROM cursorDiskKV WHERE key IN (%s)" % ",".join("?" * len(chunk))
            for k, v in fetch.execute(q, chunk).fetchall():
                rows[k] = v
        bubbles = []
        if ordered_keys:
            seq = [rows[k] for k in ordered_keys if k in rows]
        else:
            tmp = []
            for v in rows.values():
                try:
                    b = json.loads(v)
                except Exception:
                    continue
                tmp.append((b.get("startedAtMs") or toms(b.get("createdAt")), v))
            tmp.sort(key=lambda x: x[0])
            seq = [v for _, v in tmp]
        messages = []
        models = set()
        title = d.get("name") or ""
        for v in seq:
            try:
                b = json.loads(v)
            except Exception:
                continue
            typ = b.get("type")
            role = "user" if typ == 1 else "assistant" if typ == 2 else "other"
            mi = b.get("modelInfo") or {}
            model = mi.get("modelName") or mi.get("model") or "" if isinstance(mi, dict) else ""
            if model:
                models.add(model)
            tools = []
            tf = b.get("toolFormerData")
            if isinstance(tf, dict) and tf.get("name"):
                tools.append({"name": tf["name"], "args": tf.get("rawArgs") or "", "result": tf.get("result")})
            msg = {"role": role, "model": model, "thinking": get_thinking(b),
                   "text": b.get("text") or "", "tools": tools}
            messages.append(msg)
            if not title and role == "user" and (b.get("text") or "").strip():
                title = b["text"].strip().splitlines()[0][:80]
        if not messages:
            continue
        yield {"harness": "cursor", "id": cid, "project": canonical_project(src),
               "source_path": src, "title": title, "created": created,
               "updated": updated, "models": models, "messages": messages}

# ------------------------------------------------------------ CLAUDE CODE ----

def claude_code_chats():
    root = os.path.join(HOME, ".claude/projects")
    for f in glob.glob(os.path.join(root, "*", "*.jsonl")):
        sid = os.path.splitext(os.path.basename(f))[0]
        cwd = ""
        created = updated = 0
        title = ""
        messages = []
        models = set()
        try:
            lines = open(f, encoding="utf-8").read().splitlines()
        except Exception:
            continue
        for line in lines:
            if not line.strip():
                continue
            try:
                d = json.loads(line)
            except Exception:
                continue
            t = d.get("type")
            if d.get("cwd"):
                cwd = d["cwd"]
            tms = toms(d.get("timestamp"))
            if tms:
                created = tms if not created else min(created, tms)
                updated = max(updated, tms)
            if t == "summary" and d.get("summary"):
                title = d["summary"]
                continue
            if t not in ("user", "assistant"):
                continue
            m = d.get("message") or {}
            role = m.get("role") or t
            model = m.get("model") or ""
            if model and model != "<synthetic>":
                models.add(model)
            else:
                model = ""
            content = m.get("content")
            text_parts, think, tools = [], [], []
            if isinstance(content, str):
                text_parts.append(content)
            elif isinstance(content, list):
                for blk in content:
                    if not isinstance(blk, dict):
                        continue
                    bt = blk.get("type")
                    if bt == "text":
                        text_parts.append(blk.get("text", ""))
                    elif bt == "thinking":
                        think.append(blk.get("thinking", "") or blk.get("text", ""))
                    elif bt == "tool_use":
                        tools.append({"name": blk.get("name"), "args": blk.get("input"), "result": None})
                    elif bt == "tool_result":
                        rc = blk.get("content")
                        if isinstance(rc, list):
                            rc = " ".join(x.get("text", "") for x in rc if isinstance(x, dict))
                        tools.append({"name": "result", "args": "", "result": rc if isinstance(rc, str) else json.dumps(rc)[:1000]})
            msg = {"role": role, "model": model, "thinking": "\n\n".join(think),
                   "text": "\n".join(tp for tp in text_parts if tp).strip(), "tools": tools}
            if msg["text"] or msg["thinking"] or msg["tools"]:
                messages.append(msg)
                if not title and role == "user" and msg["text"]:
                    title = msg["text"].splitlines()[0][:80]
        if not messages:
            continue
        yield {"harness": "claude-code", "id": sid, "project": canonical_project(cwd),
               "source_path": cwd, "title": title, "created": created,
               "updated": updated, "models": models, "messages": messages}

# ------------------------------------------------------------------- PI ------

def pi_chats():
    root = os.path.join(HOME, ".pi/agent/sessions")
    for f in glob.glob(os.path.join(root, "*", "*.jsonl")):
        cwd = ""
        created = updated = 0
        sid = os.path.splitext(os.path.basename(f))[0].split("_", 1)[-1]
        title = ""
        messages = []
        models = set()
        cur_model = ""
        try:
            lines = open(f, encoding="utf-8").read().splitlines()
        except Exception:
            continue
        for line in lines:
            if not line.strip():
                continue
            try:
                d = json.loads(line)
            except Exception:
                continue
            t = d.get("type")
            tms = toms(d.get("timestamp"))
            if tms:
                created = tms if not created else min(created, tms)
                updated = max(updated, tms)
            if t == "session":
                cwd = d.get("cwd") or cwd
                sid = d.get("id") or sid
                continue
            if t == "model_change":
                cur_model = d.get("modelId") or cur_model
                continue
            if t != "message":
                continue
            m = d.get("message") or {}
            role = m.get("role")
            if role == "system":
                continue
            model = m.get("model") or (cur_model if role == "assistant" else "")
            if model and role == "assistant":
                models.add(model)
            content = m.get("content")
            text_parts, think, tools = [], [], []
            if isinstance(content, str):
                text_parts.append(content)
            elif isinstance(content, list):
                for blk in content:
                    if not isinstance(blk, dict):
                        continue
                    bt = blk.get("type")
                    if bt == "text":
                        text_parts.append(blk.get("text", ""))
                    elif bt in ("thinking", "reasoning"):
                        think.append(blk.get("text", "") or blk.get("thinking", ""))
                    elif bt in ("tool_use", "tool_call", "tool"):
                        tools.append({"name": blk.get("name") or blk.get("tool"),
                                      "args": blk.get("input") or blk.get("args"), "result": None})
                    elif bt in ("tool_result",):
                        tools.append({"name": "result", "args": "",
                                      "result": json.dumps(blk.get("content"))[:1000]})
            msg = {"role": role, "model": model if role == "assistant" else "",
                   "thinking": "\n\n".join(x for x in think if x),
                   "text": "\n".join(tp for tp in text_parts if tp).strip(), "tools": tools}
            if msg["text"] or msg["thinking"] or msg["tools"]:
                messages.append(msg)
                if not title and role == "user" and msg["text"]:
                    title = msg["text"].splitlines()[0][:80]
        if not messages:
            continue
        yield {"harness": "pi", "id": sid, "project": canonical_project(cwd),
               "source_path": cwd, "title": title, "created": created,
               "updated": updated, "models": models, "messages": messages}

# -------------------------------------------------------------- OPENCODE -----

def opencode_chats():
    db = opencode_db_path()
    if not db or not os.path.isfile(db):
        return
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    sessions = {}
    for tbl in ("session", "session_v2"):  # v2 overrides
        try:
            for r in con.execute(f"SELECT * FROM {tbl}"):
                sessions[r["id"]] = dict(r)
        except Exception:
            pass
    for sid, s in sessions.items():
        directory = s.get("directory") or ""
        title = s.get("title") or ""
        created = toms(s.get("time_created"))
        updated = toms(s.get("time_updated")) or created
        sess_model = ""
        mj = s.get("model")
        if mj:
            try:
                sess_model = json.loads(mj).get("id", "")
            except Exception:
                sess_model = ""
        messages = []
        models = set()
        if sess_model:
            models.add(sess_model)
        try:
            rows = con.execute(
                "SELECT type,data FROM session_message WHERE session_id=? ORDER BY seq", (sid,)
            ).fetchall()
        except Exception:
            rows = []
        for r in rows:
            typ = r["type"]
            if typ not in ("user", "assistant"):
                continue
            try:
                data = json.loads(r["data"])
            except Exception:
                continue
            model = ""
            mm = data.get("model")
            if isinstance(mm, dict):
                model = mm.get("id", "")
            if model:
                models.add(model)
            text_parts, think, tools = [], [], []
            content = data.get("content")
            if isinstance(data.get("text"), str) and not content:
                text_parts.append(data["text"])
            if isinstance(content, list):
                for blk in content:
                    if not isinstance(blk, dict):
                        continue
                    bt = blk.get("type")
                    if bt == "text":
                        text_parts.append(blk.get("text", ""))
                    elif bt == "reasoning":
                        think.append(blk.get("text", ""))
                    elif bt == "tool":
                        st = blk.get("state") or {}
                        tools.append({"name": blk.get("tool"),
                                      "args": (st.get("input") if isinstance(st, dict) else None),
                                      "result": None})
            msg = {"role": typ, "model": model, "thinking": "\n\n".join(x for x in think if x),
                   "text": "\n".join(tp for tp in text_parts if tp).strip(), "tools": tools}
            if msg["text"] or msg["thinking"] or msg["tools"]:
                messages.append(msg)
                if not title and typ == "user" and msg["text"]:
                    title = msg["text"].splitlines()[0][:80]
        if not messages:
            continue
        yield {"harness": "opencode", "id": sid, "project": canonical_project(directory),
               "source_path": directory, "title": title, "created": created,
               "updated": updated, "models": models, "messages": messages}

# ----------------------------------------------------------------- CODEX -----

def _codex_text(parts):
    out = []
    for p in (parts or []):
        if isinstance(p, dict):
            t = p.get("text") or p.get("input_text") or p.get("output_text")
            if isinstance(t, str) and t.strip():
                out.append(t)
        elif isinstance(p, str):
            out.append(p)
    return "\n".join(out)

def codex_chats():
    roots = [os.path.join(HOME, ".codex/sessions"), os.path.join(HOME, ".codex/archived_sessions")]
    files = []
    for r in roots:
        files += glob.glob(os.path.join(r, "**", "*.jsonl"), recursive=True)
    for f in files:
        cwd = ""; sid = os.path.splitext(os.path.basename(f))[0]
        created = updated = 0; title = ""; model = ""
        messages = []; models = set(); last_tool = None
        try:
            lines = open(f, encoding="utf-8").read().splitlines()
        except Exception:
            continue
        for line in lines:
            if not line.strip():
                continue
            try:
                d = json.loads(line)
            except Exception:
                continue
            tms = toms(d.get("timestamp"))
            if tms:
                created = tms if not created else min(created, tms)
                updated = max(updated, tms)
            typ = d.get("type")
            pl = d.get("payload") or {}
            if typ == "session_meta":
                cwd = pl.get("cwd") or cwd
                sid = pl.get("id") or sid
                model = pl.get("model") or model
                continue
            if typ != "response_item" or not isinstance(pl, dict):
                continue
            pt = pl.get("type")
            if pt == "message":
                role = pl.get("role")
                if role not in ("user", "assistant"):
                    continue
                txt = _codex_text(pl.get("content"))
                st = txt.strip()
                # skip Codex's injected context turns (not real conversation)
                if role == "user" and (st[:1] == "<" or st.startswith("# AGENTS.md")
                                        or st.startswith("environment_context")
                                        or st.startswith("## My request")):
                    # some wrap the real ask in <user_instructions>/<user_query>
                    m = re.search(r"<(?:user_query|user_instructions|user_message)>\s*(.*?)\s*</", txt, re.S)
                    if m and m.group(1).strip():
                        txt = m.group(1).strip(); st = txt
                    else:
                        continue
                if st:
                    messages.append({"role": role, "model": model if role == "assistant" else "",
                                     "thinking": "", "text": txt, "tools": []})
                    last_tool = None
                    if not title and role == "user":
                        title = st.splitlines()[0][:80]
            elif pt == "reasoning":
                th = _codex_text(pl.get("summary")) or _codex_text(pl.get("content"))
                if th.strip():
                    messages.append({"role": "assistant", "model": model, "thinking": th,
                                     "text": "", "tools": []})
                    last_tool = None
            elif pt == "function_call":
                tool = {"name": pl.get("name"), "args": pl.get("arguments"), "result": None}
                messages.append({"role": "assistant", "model": model, "thinking": "",
                                 "text": "", "tools": [tool]})
                last_tool = tool
            elif pt == "function_call_output" and last_tool is not None:
                out = pl.get("output")
                last_tool["result"] = out if isinstance(out, str) else json.dumps(out)[:1000]
        if model:
            models.add(model)
        if not messages:
            continue
        yield {"harness": "codex", "id": sid, "project": canonical_project(cwd),
               "source_path": cwd, "title": title, "created": created,
               "updated": updated, "models": models, "messages": messages}

# ---------------------------------------------------------------- GEMINI -----

def _gemini_projects():
    try:
        d = json.load(open(os.path.join(HOME, ".gemini/projects.json")))
        return {v: k for k, v in (d.get("projects") or {}).items()}  # name -> path
    except Exception:
        return {}

def gemini_chats():
    tmp = os.path.join(HOME, ".gemini/tmp")
    name2path = _gemini_projects()
    for d in glob.glob(os.path.join(tmp, "*")):
        if not os.path.isdir(d):
            continue
        key = os.path.basename(d)
        # resolve cwd: named project map, else parse from a checkpoint setup msg
        cwd = name2path.get(key, "")
        checkpoints = sorted(glob.glob(os.path.join(d, "checkpoint-*.json")))
        emitted = False
        for cp in checkpoints:
            try:
                data = json.load(open(cp, encoding="utf-8"))
            except Exception:
                continue
            hist = data.get("history") if isinstance(data, dict) else data
            if not isinstance(hist, list):
                continue
            messages = []; title = ""
            for h in hist:
                if not isinstance(h, dict):
                    continue
                role = "assistant" if h.get("role") == "model" else h.get("role")
                if role not in ("user", "assistant"):
                    continue
                text_parts, think, tools = [], [], []
                for p in (h.get("parts") or []):
                    if not isinstance(p, dict):
                        continue
                    if p.get("thought"):
                        think.append(p.get("text", ""))
                    elif "text" in p:
                        text_parts.append(p.get("text", ""))
                    elif "functionCall" in p:
                        fc = p["functionCall"]
                        tools.append({"name": fc.get("name"), "args": fc.get("args"), "result": None})
                    elif "functionResponse" in p:
                        fr = p["functionResponse"]
                        if tools:
                            tools[-1]["result"] = json.dumps(fr.get("response"))[:1000]
                txt = "\n".join(t for t in text_parts if t).strip()
                # skip the Gemini CLI context-setup preamble
                if role == "user" and txt.startswith("This is the Gemini CLI"):
                    m = re.search(r"working in the project directory:\s*(\S+)", txt)
                    if m and not cwd:
                        cwd = m.group(1)
                    continue
                if not (txt or think or tools):
                    continue
                messages.append({"role": role, "model": "", "thinking": "\n\n".join(think),
                                 "text": txt, "tools": tools})
                if not title and role == "user" and txt:
                    title = txt.splitlines()[0][:80]
            if not messages:
                continue
            mt = int(os.path.getmtime(cp) * 1000)
            tag = os.path.basename(cp)[len("checkpoint-"):-len(".json")] or "chat"
            yield {"harness": "gemini", "id": f"{key[:12]}-{tag}", "project": canonical_project(cwd),
                   "source_path": cwd, "title": title, "created": mt, "updated": mt,
                   "models": set(), "messages": messages}
            emitted = True
        if emitted:
            continue
        # fallback: logs.json (user prompts only) grouped by sessionId
        lg = os.path.join(d, "logs.json")
        if not os.path.isfile(lg):
            continue
        try:
            entries = json.load(open(lg, encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(entries, list) or not entries:
            continue
        bysess = defaultdict(list)
        for e in entries:
            if isinstance(e, dict) and e.get("message"):
                bysess[e.get("sessionId", key)].append(e)
        for sess, es in bysess.items():
            es.sort(key=lambda x: x.get("messageId", 0))
            messages = [{"role": "user", "model": "", "thinking": "",
                         "text": str(e.get("message", "")), "tools": []} for e in es]
            if not messages:
                continue
            t0 = toms(es[0].get("timestamp")) or int(os.path.getmtime(lg) * 1000)
            t1 = toms(es[-1].get("timestamp")) or t0
            yield {"harness": "gemini", "id": str(sess)[:12], "project": canonical_project(cwd),
                   "source_path": cwd, "title": messages[0]["text"].splitlines()[0][:80],
                   "created": t0, "updated": t1, "models": set(), "messages": messages}

# ----------------------------------------------------------- CURSOR AGENT ----

def cursor_agent_chats():
    """Cursor Agent CLI (cursor-agent): ~/.cursor/acp-sessions/<uuid>/ with a
    git-like blob store (store.db) + meta.json. Message blobs are JSON
    {role, content:[parts]}; ordered by insertion (rowid)."""
    root = os.path.join(HOME, ".cursor/acp-sessions")
    for d in glob.glob(os.path.join(root, "*")):
        db = os.path.join(d, "store.db")
        if not os.path.isfile(db):
            continue
        sid = os.path.basename(d)
        cwd = ""; title = ""
        try:
            mj = json.load(open(os.path.join(d, "meta.json")))
            cwd = mj.get("cwd", ""); title = mj.get("title", "")
        except Exception:
            pass
        created = 0
        try:
            con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        except Exception:
            continue
        try:
            r = con.execute("SELECT value FROM meta WHERE key='0'").fetchone()
            if r:
                try:
                    mm = json.loads(bytes.fromhex(r[0]).decode("utf-8", "replace"))
                    title = title or mm.get("name", "")
                    created = toms(mm.get("createdAt"))
                except Exception:
                    pass
        except Exception:
            pass
        updated = int(os.path.getmtime(db) * 1000)
        created = created or updated
        messages = []
        try:
            rows = con.execute("SELECT data FROM blobs ORDER BY rowid").fetchall()
        except Exception:
            rows = []
        con.close()
        for (data,) in rows:
            if not data:
                continue
            try:
                j = json.loads(bytes(data).decode("utf-8", "replace"))
            except Exception:
                continue
            if not isinstance(j, dict) or j.get("role") not in ("user", "assistant"):
                continue
            role = j["role"]
            text_parts, think, tools = [], [], []
            for p in (j.get("content") or []):
                if not isinstance(p, dict):
                    continue
                pt = p.get("type")
                if pt == "text":
                    t = p.get("text", "")
                    t = re.sub(r"</?user_(?:query|response|message)>", "", t).strip()
                    if t:
                        text_parts.append(t)
                elif pt == "reasoning":
                    if p.get("text"):
                        think.append(p["text"])
                elif pt == "tool-call":
                    tools.append({"name": p.get("toolName"), "args": p.get("args"), "result": None})
            msg = {"role": role, "model": "", "thinking": "\n\n".join(think),
                   "text": "\n".join(text_parts).strip(), "tools": tools}
            if msg["text"] or msg["thinking"] or msg["tools"]:
                messages.append(msg)
                if not title and role == "user" and msg["text"]:
                    title = msg["text"].splitlines()[0][:80]
        if not messages:
            continue
        yield {"harness": "cursor-agent", "id": sid, "project": canonical_project(cwd),
               "source_path": cwd, "title": title, "created": created,
               "updated": updated, "models": set(), "messages": messages}

# ------------------------------------------------------------- ANTIGRAVITY ---

def antigravity_chats():
    """Antigravity (Google's agentic IDE) stores its 'Cascade' agent conversations
    in an opaque protobuf LevelDB (Application Support/Antigravity/shared_proto_db)
    with an empty JSON chat index — not locally parseable yet (and likely cloud
    synced). Stub kept so the harness is wired for a future decoder."""
    return
    yield  # pragma: no cover

# --------------------------------------------------------------- orchestrate -

ADAPTERS = [cursor_chats, claude_code_chats, opencode_chats, pi_chats,
            codex_chats, gemini_chats, cursor_agent_chats, antigravity_chats]

FM_RE = re.compile(r"^(\w+):\s*(.*)$")

def toms_iso(v):
    if not v:
        return 0
    return toms(v)

def read_frontmatter(path):
    """Parse the YAML-ish frontmatter block of a chat file (cheap, top of file)."""
    fm = {}
    try:
        with open(path) as f:
            if f.readline().strip() != "---":
                return fm
            for _ in range(40):
                line = f.readline()
                if not line or line.strip() == "---":
                    break
                m = FM_RE.match(line.rstrip("\n"))
                if m:
                    k, v = m.group(1), m.group(2).strip()
                    if v[:1] in "\"'" or v[:1] == "[":
                        try:
                            v = json.loads(v)
                        except Exception:
                            v = v.strip("\"'")
                    fm[k] = v
    except Exception:
        pass
    return fm

def main():
    os.makedirs(PROJ_DIR, exist_ok=True)
    stats = defaultdict(int)
    per_harness = defaultdict(int)
    keep = set()  # abs paths this client produced this run

    # 1) export THIS client's chats
    for adapter in ADAPTERS:
        try:
            for c in adapter():
                c.setdefault("client", CLIENT)
                c.setdefault("platform", PLATFORM)
                md = render_chat(c)
                if not md:
                    stats["empty"] += 1
                    continue
                proj = c["project"] or "_unknown"
                fname = f"{datestr(c['created'])}_{CLIENT}_{slug(c['title'] or c['id'])}_{c['id'][:8]}.md"
                fpath = os.path.join(PROJ_DIR, proj, c["harness"], fname)
                keep.add(os.path.abspath(fpath))
                stats[write_if_changed(fpath, md)] += 1
                per_harness[c["harness"]] += 1
        except Exception as e:
            print(f"adapter {adapter.__name__} error: {e}")

    # 2) prune ONLY this client's stale files (never touch other machines' chats)
    for p in glob.glob(os.path.join(PROJ_DIR, "*", "*", "*.md")):
        if os.path.abspath(p) in keep:
            continue
        if read_frontmatter(p).get("client") == CLIENT:
            try:
                os.remove(p)
            except Exception:
                pass

    # 3) rebuild indexes from the WHOLE repo (union of all clients, incl. git-pulled)
    index = defaultdict(list)
    clients_seen = set()
    harness_totals = defaultdict(int)
    for p in glob.glob(os.path.join(PROJ_DIR, "*", "*", "*.md")):
        fm = read_frontmatter(p)
        proj = os.path.basename(os.path.dirname(os.path.dirname(p)))
        harness = fm.get("harness") or os.path.basename(os.path.dirname(p))
        cl = fm.get("client") or "?"
        clients_seen.add(cl)
        harness_totals[harness] += 1
        index[proj].append({
            "updated": toms_iso(fm.get("updated")) or toms_iso(fm.get("created")),
            "client": cl, "platform": fm.get("platform", ""), "harness": harness,
            "title": str(fm.get("title") or ""), "msgs": fm.get("messages", ""),
            "models": fm.get("models", ""),
            "rel": os.path.join(harness, os.path.basename(p)),
        })

    for proj, entries in index.items():
        entries.sort(key=lambda e: e["updated"], reverse=True)
        lines = [f"# {proj} — chat memory", "",
                 f"{len(entries)} chats across harnesses & machines. Newest first.", "",
                 "| Last active | Client | Harness | Title | Msgs | Models | File |",
                 "|---|---|---|---|---|---|---|"]
        for e in entries:
            tt = e["title"].replace("|", "\\|")[:70]
            lines.append(f"| {datestr(e['updated'])} | {e['client']} | {e['harness']} | {tt} | "
                         f"{e['msgs']} | {e['models']} | [open]({e['rel'].replace(' ', '%20')}) |")
        write_if_changed(os.path.join(PROJ_DIR, proj, "INDEX.md"), "\n".join(lines) + "\n")

    rows = sorted(((p, len(e), max((x["updated"] for x in e), default=0),
                    sorted({x["client"] for x in e})) for p, e in index.items()),
                  key=lambda r: r[2], reverse=True)
    total = sum(len(e) for e in index.values())
    g = ["# Chat memory — all projects", "",
         f"Last sync: {datetime.datetime.now():%Y-%m-%d %H:%M}  (ran on: {CLIENT}/{PLATFORM})",
         f"Clients: {', '.join(sorted(clients_seen)) or '-'}",
         f"Total chats: {total}  (" + ", ".join(f"{h}={n}" for h, n in sorted(harness_totals.items())) + ")",
         "",
         "| Project | Chats | Last active | Clients | Index |", "|---|---|---|---|---|"]
    for p, n, lu, cls in rows:
        g.append(f"| {p} | {n} | {datestr(lu)} | {', '.join(cls)} | "
                 f"[projects/{p}/INDEX.md](projects/{p}/INDEX.md) |")
    write_if_changed(os.path.join(OUT, "INDEX.md"), "\n".join(g) + "\n")

    print(f"client={CLIENT} chats: new={stats['new']} updated={stats['updated']} "
          f"unchanged={stats['unchanged']} empty={stats['empty']} | "
          f"this-run by harness: {dict(per_harness)} | repo total: {total}")


if __name__ == "__main__":
    main()
