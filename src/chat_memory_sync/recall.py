#!/usr/bin/env python3
"""
recall - find relevant past chats without scanning the whole repo.

Builds a local SQLite full-text index (BM25) over all chat markdown and queries
it, auto-scoped to the current project. The index lives under the machine-local
state dir (e.g. ~/.config/chat-memory/index.db) and is rebuilt automatically when
chats change. It is never committed to the data repo.

Agents: run this from inside the repo you're working on, read the top hits,
then open those files for full context.
"""

EXAMPLES = """examples:
  recall "rate limiting"                       auto-scope to the current repo (by CWD)
  recall "retry backoff" --project my-api
  recall "feature flag rollout" --all          search every project
  recall "flaky integration test" --harness cursor --since 2026-09 -k 10
  recall "websocket reconnect" --full          print file paths only (pipe-friendly)
  recall --reindex                             force rebuild the index
"""
import os, sys, re, glob, sqlite3, argparse, datetime
from . import cmlib

REPO = cmlib.data_dir()
PROJ_DIR = cmlib.projects_dir()
DB = cmlib.index_db()

WS_MARKERS = ["/ws/", "/pspace/", "/src/", "/code/", "/projects/", "/Developer/"]

def _slug(s, n=60):
    s = re.sub(r"\s+", " ", (s or "").strip())
    s = re.sub(r"[^\w\- ]", "", s).strip().replace(" ", "-")
    return s[:n] or ""

def canonical_project(path):
    if not path:
        return ""
    p = os.path.abspath(path).rstrip("/")
    for m in WS_MARKERS:
        i = p.find(m)
        if i != -1:
            rest = [x for x in p[i + len(m):].split("/") if x]
            if not rest:
                continue
            if rest[0] == ".worktrees" and len(rest) > 1:
                return _slug(rest[1])
            return _slug(rest[0])
    return _slug(os.path.basename(p))

def read_frontmatter(path):
    fm = {}
    try:
        with open(path, encoding="utf-8", errors="ignore") as f:
            if f.readline().strip() != "---":
                return fm
            for _ in range(40):
                line = f.readline()
                if not line or line.strip() == "---":
                    break
                m = re.match(r"^(\w+):\s*(.*)$", line.rstrip("\n"))
                if m:
                    k, v = m.group(1), m.group(2).strip().strip('"')
                    fm[k] = v
    except Exception:
        pass
    return fm

def has_fts5():
    try:
        c = sqlite3.connect(":memory:")
        c.execute("CREATE VIRTUAL TABLE t USING fts5(x)")
        c.close()
        return True
    except Exception:
        return False

def newest_md_mtime():
    mt = 0.0
    for p in glob.glob(os.path.join(PROJ_DIR, "*", "*", "*.md")):
        try:
            mt = max(mt, os.path.getmtime(p))
        except OSError:
            pass
    return mt

def build_index():
    """Contentless FTS5 index: we store only metadata + the inverted index, never
    a copy of the chat text. Snippets are generated from the source files at query
    time. Keeps the DB small (no duplicated transcripts)."""
    if os.path.exists(DB):
        os.remove(DB)
    con = sqlite3.connect(DB)
    con.execute("""CREATE TABLE d(
        rowid INTEGER PRIMARY KEY, project TEXT, harness TEXT, client TEXT,
        date TEXT, title TEXT, path TEXT)""")
    con.execute("CREATE INDEX idx_proj ON d(project)")
    fts = has_fts5()
    if fts:
        con.execute("CREATE VIRTUAL TABLE fts USING fts5(body, content='')")
    rid = 0
    for p in glob.glob(os.path.join(PROJ_DIR, "*", "*", "*.md")):
        fm = read_frontmatter(p)
        proj = os.path.basename(os.path.dirname(os.path.dirname(p)))
        try:
            body = open(p, encoding="utf-8", errors="ignore").read()
        except Exception:
            continue
        rid += 1
        con.execute("INSERT INTO d VALUES(?,?,?,?,?,?,?)",
                    (rid, proj, fm.get("harness", ""), fm.get("client", ""),
                     (fm.get("updated") or fm.get("created") or "")[:10],
                     fm.get("title", ""), os.path.relpath(p, REPO)))
        if fts:
            con.execute("INSERT INTO fts(rowid, body) VALUES(?,?)", (rid, fm.get("title", "") + "\n" + body))
    con.commit()
    con.execute("PRAGMA user_version=2")
    con.commit()
    con.close()
    return rid

def ensure_index(force=False):
    if force or not os.path.exists(DB) or os.path.getmtime(DB) < newest_md_mtime():
        n = build_index()
        return n
    return None

def make_snippet(path, query, width=180):
    """Pull a short context window around the first query term from the file."""
    terms = [t for t in re.split(r"\W+", query.lower()) if len(t) > 1]
    try:
        text = open(os.path.join(REPO, path), encoding="utf-8", errors="ignore").read()
    except Exception:
        return ""
    # start searching after the YAML frontmatter so snippets show real content
    body_start = 0
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            body_start = end + 4
    low = text.lower()
    hits = [low.find(t, body_start) for t in terms if low.find(t, body_start) != -1]
    pos = min(hits) if hits else body_start
    s = max(body_start, pos - width // 3)
    seg = re.sub(r"\s+", " ", text[s:s + width]).strip()
    for t in terms:
        seg = re.sub("(" + re.escape(t) + ")", r">>\1<<", seg, flags=re.I)
    return seg

def search(query, project=None, harness=None, since=None, k=8):
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    fts = has_fts5()
    where, params = [], []
    if project:
        where.append("d.project = ?"); params.append(project)
    if harness:
        where.append("d.harness = ?"); params.append(harness)
    if since:
        where.append("d.date >= ?"); params.append(since)
    filt = (" AND " + " AND ".join(where)) if where else ""
    rows = []
    if fts:
        try:
            sql = (f"SELECT d.*, bm25(fts) AS score FROM fts JOIN d ON d.rowid = fts.rowid "
                   f"WHERE fts MATCH ?{filt} ORDER BY score LIMIT ?")
            rows = con.execute(sql, [query] + params + [k]).fetchall()
        except sqlite3.OperationalError:
            rows = []
    if not rows:  # fallback: read files and score by term frequency
        terms = [t for t in re.split(r"\s+", query.lower()) if t]
        cand = con.execute(f"SELECT d.* FROM d WHERE 1=1{filt}", params).fetchall()
        scored = []
        for r in cand:
            try:
                b = open(os.path.join(REPO, r["path"]), encoding="utf-8", errors="ignore").read().lower()
            except Exception:
                continue
            sc = sum(b.count(t) for t in terms)
            if sc:
                scored.append((sc, r))
        scored.sort(key=lambda x: -x[0])
        rows = [r for _, r in scored[:k]]
    con.close()
    return [(r, make_snippet(r["path"], query)) for r in rows]

def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="recall",
        description="Search your past AI coding chats across all tools and machines.\n"
                    "Auto-scoped to the current project (by working directory); ranked\n"
                    "with BM25 and shown with snippets. Part of chat-memory-sync.",
        epilog=EXAMPLES,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("query", nargs="?", default="", help="search terms")
    ap.add_argument("--project", help="project to scope to (default: infer from CWD)")
    ap.add_argument("--all", action="store_true", help="search all projects")
    ap.add_argument("--harness", help="cursor|cursor-agent|claude-code|opencode|pi|codex|gemini")
    ap.add_argument("--since", help="YYYY-MM or YYYY-MM-DD lower bound")
    ap.add_argument("-k", type=int, default=8, help="max results (default 8)")
    ap.add_argument("--full", action="store_true", help="print file paths only")
    ap.add_argument("--reindex", action="store_true", help="force rebuild index")
    args = ap.parse_args(argv)

    n = ensure_index(force=args.reindex)
    if args.reindex or n is not None:
        print(f"[indexed {n if n is not None else '?'} chats]", file=sys.stderr)
    if not args.query:
        if args.reindex:
            return
        ap.error("provide a search query")

    project = None if args.all else (args.project or canonical_project(os.getcwd()) or None)
    if project and not args.all:
        # only scope if that project actually exists in the repo
        if not os.path.isdir(os.path.join(PROJ_DIR, project)):
            print(f"[no chats for project '{project}'; searching all]", file=sys.stderr)
            project = None

    rows = search(args.query, project=project, harness=args.harness,
                  since=args.since, k=args.k)
    if not rows:
        print("No matches.", file=sys.stderr)
        return
    if args.full:
        for r, _ in rows:
            print(os.path.join(REPO, r["path"]))
        return
    scope = f"project={project}" if project else "all projects"
    print(f"Top {len(rows)} for \"{args.query}\" ({scope}):\n")
    for i, (r, snip) in enumerate(rows, 1):
        print(f"{i}. {r['date']}  [{r['harness']}/{r['client']}]  {r['title']}")
        print(f"   {r['path']}")
        if snip:
            print(f"   … {snip} …")
        print()

if __name__ == "__main__":
    main()
