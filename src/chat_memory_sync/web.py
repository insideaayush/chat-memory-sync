#!/usr/bin/env python3
"""
chat-memory serve - a lightweight local web UI to browse & search your chats.

Pure standard library (http.server + sqlite). Reuses the recall BM25 index.
"""
import os, json, sqlite3, argparse, threading, webbrowser, html
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs
from . import cmlib, recall


def _db():
    return sqlite3.connect(cmlib.index_db())


def api_projects():
    recall.ensure_index()
    con = _db(); con.row_factory = sqlite3.Row
    rows = con.execute(
        "SELECT project, COUNT(*) n, MAX(date) last FROM d GROUP BY project ORDER BY last DESC"
    ).fetchall()
    con.close()
    total = sum(r["n"] for r in rows)
    return {"total": total, "projects": [dict(r) for r in rows]}


def api_chats(project):
    recall.ensure_index()
    con = _db(); con.row_factory = sqlite3.Row
    rows = con.execute(
        "SELECT date, harness, client, title, path FROM d WHERE project=? ORDER BY date DESC, title",
        (project,)).fetchall()
    con.close()
    return {"chats": [dict(r) for r in rows]}


def api_search(q, project, harness, all_):
    recall.ensure_index()
    rows = recall.search(q, project=None if all_ else (project or None),
                         harness=harness or None, k=50)
    out = []
    for r, snip in rows:
        out.append({"date": r["date"], "harness": r["harness"], "client": r["client"],
                    "title": r["title"], "path": r["path"], "project": r["project"], "snippet": snip})
    return {"results": out}


def api_chat(path):
    base = os.path.realpath(cmlib.projects_dir())
    full = os.path.realpath(os.path.join(cmlib.data_dir(), path))
    if not full.startswith(base + os.sep) or not full.endswith(".md"):
        return None
    try:
        return open(full, encoding="utf-8", errors="ignore").read()
    except Exception:
        return None


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, body, ctype="application/json", code=200):
        if isinstance(body, (dict, list)):
            body = json.dumps(body)
        data = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        try:
            if u.path == "/":
                return self._send(INDEX_HTML, "text/html; charset=utf-8")
            if u.path == "/api/projects":
                return self._send(api_projects())
            if u.path == "/api/chats":
                return self._send(api_chats(q.get("project", "")))
            if u.path == "/api/search":
                return self._send(api_search(q.get("q", ""), q.get("project", ""),
                                             q.get("harness", ""), q.get("all") == "1"))
            if u.path == "/api/chat":
                c = api_chat(q.get("path", ""))
                if c is None:
                    return self._send({"error": "not found"}, code=404)
                return self._send({"markdown": c})
            self._send({"error": "not found"}, code=404)
        except Exception as e:
            self._send({"error": str(e)}, code=500)


INDEX_HTML = r"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>chat-memory</title>
<style>
:root{--bg:#0f1117;--panel:#171a21;--line:#262b36;--fg:#e6e9ef;--mut:#8b93a7;--acc:#6ea8fe;--hit:#f5d06f}
*{box-sizing:border-box}body{margin:0;font:14px/1.5 -apple-system,BlinkMacSystemFont,Segoe UI,Roboto,sans-serif;background:var(--bg);color:var(--fg);height:100vh;display:flex;flex-direction:column}
header{display:flex;gap:10px;align-items:center;padding:10px 14px;border-bottom:1px solid var(--line);background:var(--panel)}
header b{font-weight:700}header .tot{color:var(--mut);font-size:12px}
input,select{background:#0b0d12;color:var(--fg);border:1px solid var(--line);border-radius:7px;padding:7px 10px;font-size:13px}
#q{flex:1;min-width:120px}
main{flex:1;display:flex;min-height:0}
#side{width:220px;border-right:1px solid var(--line);overflow:auto;background:var(--panel)}
#list{width:360px;border-right:1px solid var(--line);overflow:auto}
#view{flex:1;overflow:auto;padding:18px 26px}
.p{padding:7px 12px;cursor:pointer;border-bottom:1px solid var(--line);display:flex;justify-content:space-between;gap:6px}
.p:hover,.p.sel{background:#1e2430}.p .n{color:var(--mut);font-size:12px}
.row{padding:9px 12px;cursor:pointer;border-bottom:1px solid var(--line)}
.row:hover,.row.sel{background:#1e2430}
.row .t{font-weight:600;margin-bottom:2px}
.row .m{color:var(--mut);font-size:11.5px;display:flex;gap:8px;flex-wrap:wrap}
.row .s{color:var(--mut);font-size:12px;margin-top:4px}
.tag{background:#222836;border-radius:4px;padding:0 6px;font-size:11px;color:#aab2c5}
mark{background:transparent;color:var(--hit);font-weight:700}
#view h1{font-size:19px;margin:0 0 4px}#view h3{margin:18px 0 2px;color:var(--acc);font-size:14px;border-top:1px solid var(--line);padding-top:12px}
#view pre{background:#0b0d12;border:1px solid var(--line);border-radius:7px;padding:10px;overflow:auto;font-size:12.5px}
#view code{font-family:ui-monospace,Menlo,monospace}
#view details{margin:6px 0;color:var(--mut)}#view summary{cursor:pointer}
.meta{color:var(--mut);font-size:12px;margin-bottom:14px}
.empty{color:var(--mut);padding:24px;text-align:center}
</style></head><body>
<header><b>chat-memory</b><span class="tot" id="tot"></span>
<input id="q" placeholder="search all your chats…" autocomplete="off">
<label class="tot"><input type="checkbox" id="allp"> all projects</label>
<select id="harness"><option value="">any harness</option></select>
</header>
<main>
<div id="side"></div><div id="list"></div><div id="view"><div class="empty">Pick a project or search.</div></div>
</main>
<script>
const E=(t,c,h)=>{const e=document.createElement(t);if(c)e.className=c;if(h!=null)e.innerHTML=h;return e};
const esc=s=>(s||'').replace(/[&<>]/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[m]));
let state={project:null,harness:''};
const HARN=['cursor','cursor-agent','claude-code','opencode','pi','codex','gemini'];
HARN.forEach(h=>harness.appendChild(E('option',null,h)).value=h);
harness.onchange=()=>{state.harness=harness.value; q.value?doSearch():loadChats()};

async function j(u){return (await fetch(u)).json()}
async function loadProjects(){
  const d=await j('/api/projects'); tot.textContent=d.total+' chats';
  side.innerHTML='';
  d.projects.forEach(p=>{const el=E('div','p');el.append(E('span',null,esc(p.project)),E('span','n',p.n));
    el.onclick=()=>{document.querySelectorAll('.p').forEach(x=>x.classList.remove('sel'));el.classList.add('sel');state.project=p.project;q.value='';loadChats()};side.append(el)});
}
function hl(s){return esc(s).replace(/&gt;&gt;(.*?)&lt;&lt;/g,'<mark>$1</mark>')}
function rowEl(r,withSnip){
  const el=E('div','row');
  el.append(E('div','t',esc(r.title)||'(untitled)'));
  const m=E('div','m');m.append(E('span','tag',r.harness),E('span',null,r.date||''),E('span',null,esc(r.client||'')));
  if(withSnip&&r.project)m.append(E('span','tag',esc(r.project)));
  el.append(m);
  if(withSnip&&r.snippet)el.append(E('div','s',hl(r.snippet)));
  el.onclick=()=>{document.querySelectorAll('.row').forEach(x=>x.classList.remove('sel'));el.classList.add('sel');openChat(r.path)};
  return el;
}
async function loadChats(){
  if(!state.project){list.innerHTML='';return}
  const d=await j('/api/chats?project='+encodeURIComponent(state.project));
  list.innerHTML=''; if(!d.chats.length){list.append(E('div','empty','No chats.'));return}
  d.chats.filter(c=>!state.harness||c.harness===state.harness).forEach(c=>list.append(rowEl(c,false)));
}
let tmr;
q.oninput=()=>{clearTimeout(tmr);tmr=setTimeout(doSearch,180)};
async function doSearch(){
  const term=q.value.trim(); if(!term)return loadChats();
  const u='/api/search?q='+encodeURIComponent(term)+'&all='+(allp.checked?1:0)+
    (state.project&&!allp.checked?'&project='+encodeURIComponent(state.project):'')+
    (state.harness?'&harness='+state.harness:'');
  const d=await j(u); list.innerHTML='';
  if(!d.results.length){list.append(E('div','empty','No matches.'));return}
  d.results.forEach(r=>list.append(rowEl(r,true)));
}
allp.onchange=doSearch;
function md(src){
  // split frontmatter
  let meta='';if(src.startsWith('---')){const e=src.indexOf('\n---',3);if(e>-1){meta=src.slice(3,e).trim();src=src.slice(e+4)}}
  let h=esc(src);
  h=h.replace(/```([\w-]*)\n([\s\S]*?)```/g,(m,l,c)=>'<pre><code>'+c.replace(/&amp;/g,'&')+'</code></pre>');
  h=h.replace(/&lt;details&gt;&lt;summary&gt;([\s\S]*?)&lt;\/summary&gt;/g,'<details><summary>$1</summary>').replace(/&lt;\/details&gt;/g,'</details>');
  h=h.replace(/^### (.*)$/gm,'<h3>$1</h3>').replace(/^## (.*)$/gm,'<h3>$1</h3>').replace(/^# (.*)$/gm,'<h1>$1</h1>');
  h=h.replace(/\*\*(.+?)\*\*/g,'<b>$1</b>');
  h=h.replace(/`([^`\n]+?)`/g,'<code>$1</code>');
  const mh=meta?'<div class="meta">'+esc(meta).replace(/\n/g,' · ')+'</div>':'';
  return mh+h;
}
async function openChat(path){
  view.innerHTML='<div class="empty">loading…</div>';
  const d=await j('/api/chat?path='+encodeURIComponent(path));
  view.innerHTML=d.markdown?md(d.markdown):'<div class="empty">not found</div>';
  view.scrollTop=0;
}
loadProjects();
</script></body></html>"""


def serve(port=8787, open_browser=True):
    recall.ensure_index()
    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    url = f"http://127.0.0.1:{port}"
    print(f"chat-memory UI -> {url}  (Ctrl-C to stop)")
    if open_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="chat-memory serve",
                                 description="browse & search your chats in a local web UI")
    ap.add_argument("--port", type=int, default=8787)
    ap.add_argument("--no-open", action="store_true", help="don't auto-open the browser")
    args = ap.parse_args(argv)
    serve(args.port, open_browser=not args.no_open)


if __name__ == "__main__":
    main()
