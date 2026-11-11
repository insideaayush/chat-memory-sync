#!/usr/bin/env python3
"""
chat-memory serve - a lightweight, keyboard-driven local web UI for your chats.

Pure standard library (http.server + sqlite). Reuses the recall BM25 index.
"""
import os, re, json, sqlite3, argparse, threading, webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs
from . import cmlib, recall


def _db():
    con = sqlite3.connect(cmlib.index_db())
    con.row_factory = sqlite3.Row
    return con


def api_projects():
    recall.ensure_index()
    con = _db()
    rows = con.execute(
        "SELECT project, COUNT(*) n, MAX(date) last FROM d GROUP BY project ORDER BY last DESC"
    ).fetchall()
    hrows = con.execute(
        "SELECT harness, COUNT(*) n FROM d GROUP BY harness ORDER BY n DESC"
    ).fetchall()
    con.close()
    return {"total": sum(r["n"] for r in rows),
            "projects": [dict(r) for r in rows],
            "harnesses": [dict(r) for r in hrows]}


def api_chats(project, harness):
    recall.ensure_index()
    con = _db()
    if project:
        sql = "SELECT date, harness, client, title, path, project FROM d WHERE project=?"
        params = [project]
    else:
        sql = "SELECT date, harness, client, title, path, project FROM d WHERE 1=1"
        params = []
    if harness:
        sql += " AND harness=?"
        params.append(harness)
    sql += " ORDER BY date DESC, title LIMIT 500"
    rows = con.execute(sql, params).fetchall()
    con.close()
    return {"chats": [dict(r) for r in rows]}


def api_all():
    recall.ensure_index()
    con = _db()
    rows = con.execute(
        "SELECT project, harness, client, date, title, path FROM d ORDER BY date DESC").fetchall()
    con.close()
    return {"chats": [dict(r) for r in rows]}


def api_search(q, project, harness):
    recall.ensure_index()
    rows = recall.search(q, project=project or None, harness=harness or None, k=60)
    return {"results": [{"date": r["date"], "harness": r["harness"], "client": r["client"],
                         "title": r["title"], "path": r["path"], "project": r["project"],
                         "snippet": snip} for r, snip in rows]}


# ---- chat markdown -> structured turns + parts ------------------------------

_THINK_RE = re.compile(r"<details><summary>thinking</summary>(.*?)</details>", re.S)
_TOOL_RE = re.compile(
    r"\*\*\u2192 tool: `([^`]+)`\*\*"
    r"(?:\s*```json\s*(.*?)\s*```)?"
    r"(?:\s*<details><summary>result</summary>(.*?)</details>)?", re.S)


def _strip_fence(s):
    s = (s or "").strip()
    s = re.sub(r"^```[\w-]*\n?", "", s)
    s = re.sub(r"\n?```$", "", s)
    return s.strip()


def parse_body(body):
    specials = []
    for m in _THINK_RE.finditer(body):
        specials.append((m.start(), m.end(), {"type": "thinking", "text": m.group(1).strip()}))
    for m in _TOOL_RE.finditer(body):
        specials.append((m.start(), m.end(), {
            "type": "tool", "name": m.group(1),
            "args": (m.group(2) or "").strip(), "result": _strip_fence(m.group(3))}))
    specials.sort(key=lambda x: x[0])
    parts, cur = [], 0
    for s, e, obj in specials:
        if s > cur:
            t = body[cur:s].strip()
            if t:
                parts.append({"type": "text", "text": t})
        parts.append(obj)
        cur = max(cur, e)
    if cur < len(body):
        t = body[cur:].strip()
        if t:
            parts.append({"type": "text", "text": t})
    return parts


def parse_chat(text):
    meta = {}
    if text.startswith("---"):
        e = text.find("\n---", 3)
        if e > -1:
            for line in text[3:e].strip().splitlines():
                if ":" in line:
                    k, v = line.split(":", 1)
                    meta[k.strip()] = v.strip().strip('"')
            text = text[e + 4:]
    pat = re.compile(r"(?m)^### (User|Assistant|System|Type\d+)(?:\s+_\(model:\s*([^)]+)\))?[^\n]*$")
    matches = list(pat.finditer(text))
    turns = []
    for i, mm in enumerate(matches):
        start = mm.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        turns.append({"role": mm.group(1).lower(), "model": (mm.group(2) or "").strip(),
                      "parts": parse_body(text[start:end].strip())})
    return meta, meta.get("title", ""), turns


def api_chat(path):
    base = os.path.realpath(cmlib.projects_dir())
    full = os.path.realpath(os.path.join(cmlib.data_dir(), path))
    if not full.startswith(base + os.sep) or not full.endswith(".md"):
        return None
    try:
        text = open(full, encoding="utf-8", errors="ignore").read()
    except Exception:
        return None
    meta, title, turns = parse_chat(text)
    return {"meta": meta, "title": title, "turns": turns}


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
            if u.path == "/api/all":
                return self._send(api_all())
            if u.path == "/api/chats":
                return self._send(api_chats(q.get("project", ""), q.get("harness", "")))
            if u.path == "/api/search":
                return self._send(api_search(q.get("q", ""), q.get("project", ""), q.get("harness", "")))
            if u.path == "/api/chat":
                c = api_chat(q.get("path", ""))
                return self._send(c if c else {"error": "not found"}, code=200 if c else 404)
            self._send({"error": "not found"}, code=404)
        except Exception as e:
            self._send({"error": str(e)}, code=500)


INDEX_HTML = r"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>chat-memory</title>
<style>
:root{
  --bg:#0d0f14; --panel:#12141b; --panel2:#171a23; --elev:#1b1f2a; --code:#0a0c11;
  --line:#222733; --line2:#2b313f;
  --fg:#e7ebf3; --mut:#9aa3b6; --dim:#626b7e;
  --acc:#7aa2f7; --acc-dim:#38415c; --hit:#e6c07b; --think:#bb9af7; --tool:#7dcfff;
  --usr:#20344f; --usr-line:#315480; --asst:#171b25;
  --r:7px; --rl:11px; --mono:ui-monospace,SFMono-Regular,Menlo,monospace; --h:30px;
}
body.light{
  --bg:#f5f7fa; --panel:#ffffff; --panel2:#eef1f6; --elev:#e7ebf1; --code:#f1f4f8;
  --line:#e2e7ee; --line2:#d2d9e3;
  --fg:#1b2130; --mut:#5a6373; --dim:#9099a8;
  --acc:#3b6fe0; --acc-dim:#d7e3fb; --hit:#9a6b00; --think:#7c3aed; --tool:#0b7285;
  --usr:#dbeafe; --usr-line:#a9c6f5; --asst:#f1f4f8;
}
*{box-sizing:border-box}
html,body{height:100%}
body{margin:0;font:13.5px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
  background:var(--bg);color:var(--fg);display:flex;flex-direction:column;height:100vh;overflow:hidden;
  -webkit-font-smoothing:antialiased;transition:background .15s,color .15s}
::-webkit-scrollbar{width:10px;height:10px}::-webkit-scrollbar-thumb{background:var(--line2);border-radius:6px;border:2px solid var(--bg)}
::selection{background:var(--acc-dim)}

/* primitives */
.tag{display:inline-flex;align-items:center;height:18px;padding:0 7px;border-radius:999px;background:var(--panel2);
  border:1px solid var(--line);color:var(--mut);font-size:10.5px;line-height:1;white-space:nowrap}
.tag.mono{font-family:var(--mono);color:var(--tool)}
.kbd{display:inline-flex;align-items:center;height:17px;padding:0 5px;border:1px solid var(--line2);border-bottom-width:2px;
  border-radius:5px;font:11px var(--mono);color:var(--mut);background:var(--panel)}
.btn{display:inline-flex;align-items:center;gap:6px;height:var(--h);padding:0 11px;border:1px solid var(--line);
  border-radius:var(--r);background:var(--panel2);color:var(--mut);font-size:12px;cursor:pointer;transition:.12s}
.btn:hover{color:var(--fg);border-color:var(--line2);background:var(--elev)}
.iconbtn{position:relative;display:inline-flex;align-items:center;justify-content:center;width:var(--h);height:var(--h);
  border:1px solid var(--line);border-radius:var(--r);background:var(--panel2);color:var(--mut);cursor:pointer;transition:.12s}
.iconbtn:hover{color:var(--fg);border-color:var(--line2);background:var(--elev)}
.iconbtn.active{color:var(--acc);border-color:var(--acc)}
.iconbtn.active::after{content:"";position:absolute;top:5px;right:5px;width:6px;height:6px;border-radius:50%;background:var(--acc)}
.colhead{height:34px;display:flex;align-items:center;gap:8px;padding:0 14px;border-bottom:1px solid var(--line);
  color:var(--dim);font-size:10.5px;letter-spacing:.09em;text-transform:uppercase;background:var(--panel);flex:0 0 auto}
.colhead b{color:var(--mut);text-transform:none;letter-spacing:0;font-size:12.5px;font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.colhead .cnt{margin-left:auto;color:var(--dim);letter-spacing:0;font-variant-numeric:tabular-nums}

/* header */
header{display:grid;grid-template-columns:1fr auto 1fr;align-items:center;gap:10px;padding:10px 14px;border-bottom:1px solid var(--line);background:var(--panel)}
.hleft{justify-self:start}.hcenter{justify-self:center;display:flex;gap:7px;align-items:center;width:min(460px,48vw)}
.hright{justify-self:end;display:flex;gap:8px;align-items:center}
.logo{font-weight:650;letter-spacing:.2px;font-size:14px}.logo .a{color:var(--acc)}
input,select{height:var(--h);background:var(--bg);color:var(--fg);border:1px solid var(--line);border-radius:var(--r);
  padding:0 10px;font-size:13px;outline:none;transition:.12s}
input:focus,select:focus{border-color:var(--acc);box-shadow:0 0 0 3px var(--acc-dim)}
#q{flex:1;min-width:0}

/* layout */
main{flex:1;display:flex;min-height:0}
#side{width:208px;flex:0 0 auto;display:flex;flex-direction:column;border-right:1px solid var(--line);background:var(--panel)}
#sidelist{overflow:auto;flex:1;padding:4px 0}
#listcol{width:342px;flex:0 0 auto;display:flex;flex-direction:column;border-right:1px solid var(--line)}
#list{overflow:auto;flex:1}
#view{flex:1;overflow:auto;display:flex;flex-direction:column;background:var(--bg)}
body.noside #side{display:none}

.p{display:flex;align-items:center;gap:8px;padding:6px 14px;cursor:pointer;border-left:2px solid transparent;color:var(--mut)}
.p:hover{background:var(--panel2);color:var(--fg)}
.p.sel{background:var(--panel2);border-left-color:var(--acc);color:var(--fg)}
.p .nm{flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:12.5px}
.p .n{color:var(--dim);font-size:11px;font-variant-numeric:tabular-nums}

.row{padding:10px 14px;cursor:pointer;border-bottom:1px solid var(--line);border-left:2px solid transparent;transition:background .1s}
.row:hover{background:var(--panel2)}
.row.sel{background:var(--panel2);border-left-color:var(--acc)}
.row .t{font-weight:600;margin-bottom:4px;font-size:13px;line-height:1.35;overflow:hidden;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical}
.row .m{color:var(--dim);font-size:11px;display:flex;gap:6px;flex-wrap:wrap;align-items:center}
.row .m .date{font-variant-numeric:tabular-nums}
.row .s{color:var(--mut);font-size:11.5px;margin-top:5px;line-height:1.45;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
mark{background:transparent;color:var(--hit);font-weight:700}
.empty{color:var(--dim);padding:40px 20px;text-align:center;font-size:12.5px;line-height:1.7}

#vhead{position:sticky;top:0;z-index:3;padding:13px 24px;border-bottom:1px solid var(--line);
  background:color-mix(in srgb,var(--panel) 88%,transparent);backdrop-filter:blur(8px)}
#vhead h1{font-size:15.5px;margin:0 0 7px;font-weight:650;line-height:1.3}
#vhead .chips{display:flex;gap:6px;flex-wrap:wrap}
#thread{width:100%;max-width:980px;margin:0 auto;padding:20px 24px 100px}
.turn{margin:14px 0;display:flex;flex-direction:column}
.turn.user{align-items:flex-end}.turn.assistant,.turn.system{align-items:flex-start}
.rlabel{font-size:10.5px;color:var(--dim);margin:0 8px 4px;display:flex;gap:7px;align-items:center;letter-spacing:.02em}
.bubble{max-width:88%;padding:10px 14px;border-radius:var(--rl);border:1px solid var(--line);overflow-wrap:anywhere}
.turn.user .bubble{background:var(--usr);border-color:var(--usr-line);border-bottom-right-radius:3px}
.turn.assistant .bubble{background:var(--asst);border-bottom-left-radius:3px}
.msg>:first-child{margin-top:0}.msg>:last-child{margin-bottom:0}.msg p{margin:8px 0}
.msg h1,.msg h2,.msg h3{font-size:14px;margin:12px 0 5px;font-weight:650}
pre{background:var(--code);border:1px solid var(--line);border-radius:var(--r);padding:11px;overflow:auto;font-size:12px;margin:7px 0}
code{font-family:var(--mono);font-size:12.5px}
.msg :not(pre)>code{background:var(--code);border:1px solid var(--line);border-radius:4px;padding:.5px 5px;font-size:12px}
.msg table{border-collapse:collapse;margin:9px 0;display:block;overflow:auto;max-width:100%;font-size:12.5px}
.msg th,.msg td{border:1px solid var(--line2);padding:5px 10px;text-align:left}.msg th{background:var(--code);font-weight:600}
.msg ul,.msg ol{margin:7px 0;padding-left:22px}.msg li{margin:3px 0}
.msg blockquote{border-left:3px solid var(--line2);margin:8px 0;padding:3px 12px;color:var(--mut)}
.msg a{color:var(--acc);text-decoration:none}.msg a:hover{text-decoration:underline}
.msg hr{border:none;border-top:1px solid var(--line);margin:14px 0}

details.step{margin:4px 2px;padding:4px 0 4px 12px;border-left:2px solid var(--line);font-size:12.5px}
details.step>summary{cursor:pointer;color:var(--mut);list-style:none;display:flex;gap:8px;align-items:baseline}
details.step>summary::-webkit-details-marker{display:none}
details.step>summary::before{content:"\25b8";color:var(--dim);font-size:9px;flex:0 0 auto;transform:translateY(-1px)}
details.step[open]>summary::before{content:"\25be"}
details.step .k{flex:0 0 auto;font-weight:600}
details.step.think>summary .k{color:var(--think)}
details.step.tool>summary .k{color:var(--tool);font-family:var(--mono);font-size:12px}
details.step .pv{color:var(--dim);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;flex:1;font-weight:400}
.sbody{margin:8px 0 6px}
details.res{margin-top:7px}details.res>summary{color:var(--mut);cursor:pointer;font-size:12px;list-style:none}
details.res>summary::-webkit-details-marker{display:none}

footer{display:flex;gap:16px;align-items:center;padding:7px 16px;border-top:1px solid var(--line);
  background:var(--panel);color:var(--dim);font-size:11.5px;flex-wrap:wrap}
footer span{display:inline-flex;gap:5px;align-items:center}

/* overlays */
.ovl{position:fixed;inset:0;background:rgba(6,8,12,.55);display:none;align-items:flex-start;justify-content:center;z-index:50;backdrop-filter:blur(2px)}
.ovl.on{display:flex}
.card{margin-top:12vh;background:var(--panel);border:1px solid var(--line2);border-radius:var(--rl);box-shadow:0 24px 70px rgba(0,0,0,.45)}
#pal{width:min(660px,92vw);overflow:hidden}
#palq{width:100%;height:46px;border:none;border-bottom:1px solid var(--line);border-radius:0;padding:0 16px;font-size:15px;background:var(--panel)}
#palq:focus{box-shadow:none}
#palres{max-height:54vh;overflow:auto;padding:5px 0}
.pr{padding:8px 15px;cursor:pointer;display:flex;gap:9px;align-items:center;border-left:2px solid transparent}
.pr.sel{background:var(--panel2);border-left-color:var(--acc)}
.pr .t{font-weight:600;flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.pr .meta{color:var(--dim);font-size:11px;font-variant-numeric:tabular-nums}
#filt,#help{width:min(440px,92vw);padding:18px 22px}
#filt h3,#help h3{margin:0 0 14px;font-size:14px}
.field{margin-bottom:14px}.field label{display:block;color:var(--mut);font-size:11.5px;margin-bottom:6px}
.field select{width:100%}
.frow{display:flex;gap:9px;justify-content:flex-end;margin-top:18px}
.frow .btn.primary{background:var(--acc);border-color:var(--acc);color:#fff}
#help table{width:100%;border-collapse:collapse}
#help td{padding:6px 2px;vertical-align:top;color:var(--mut)}#help td:first-child{width:150px;white-space:nowrap}
/* @-filter autocomplete */
.ac{position:fixed;z-index:60;display:none;background:var(--panel);border:1px solid var(--line2);border-radius:var(--r);box-shadow:0 14px 40px rgba(0,0,0,.4);max-height:44vh;overflow:auto;padding:4px 0}
.ac.on{display:block}
.ac .ai{padding:6px 12px;display:flex;gap:8px;align-items:center;cursor:pointer;font-size:12.5px}
.ac .ai.sel{background:var(--panel2)}
.ac .ai .nm{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.ac .ai .ty{margin-left:auto;color:var(--dim);font-size:10px;text-transform:uppercase;letter-spacing:.06em;flex:0 0 auto}
</style></head><body>
<header>
  <div class="hleft"><span class="logo">chat<span class="a">-</span>memory</span></div>
  <div class="hcenter">
    <input id="q" placeholder="Search&hellip;   @ to filter   /" autocomplete="off">
    <span class="iconbtn" id="filterbtn" title="Filters">
      <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 3H2l8 9.46V19l4 2v-8.54z"/></svg>
    </span>
  </div>
  <div class="hright">
    <span class="iconbtn" id="themebtn" title="Toggle theme">&#9680;</span>
    <span class="btn" id="palbtn"><span class="kbd">&#8984;K</span> Jump</span>
    <span class="iconbtn" id="helpbtn" title="Shortcuts">?</span>
  </div>
</header>
<main>
  <div id="side"><div class="colhead"><b>Projects</b><span class="cnt" id="pcnt"></span></div><div id="sidelist"></div></div>
  <div id="listcol"><div class="colhead" id="lhead"><b>Chats</b></div>
    <div id="list"><div class="empty">Pick a project, search, or press <span class="kbd">&#8984;K</span> to jump.</div></div></div>
  <div id="view"><div class="empty">Select a chat to read it.</div></div>
</main>
<footer>
  <span><span class="kbd">/</span> search</span><span><span class="kbd">&#8984;K</span> jump</span>
  <span><span class="kbd">j</span><span class="kbd">k</span> move</span><span><span class="kbd">&crarr;</span> open</span>
  <span><span class="kbd">[</span><span class="kbd">]</span> prev/next</span><span><span class="kbd">e</span> expand all</span>
  <span><span class="kbd">b</span> sidebar</span><span><span class="kbd">?</span> help</span>
</footer>
<div class="ovl" id="palovl"><div id="pal" class="card"><input id="palq" placeholder="Jump to a chat&hellip;"><div id="palres"></div></div></div>
<div class="ovl" id="filtovl"><div id="filt" class="card"><h3>Filters</h3>
  <div class="field"><label>Project</label><select id="fproj"><option value="">All projects</option></select></div>
  <div class="field"><label>Harness</label><select id="fharness"><option value="">Any harness</option></select></div>
  <div class="frow"><span class="btn" id="fclear">Clear</span><span class="btn primary" id="fdone">Done</span></div>
</div></div>
<div class="ac" id="ac"></div>
<div class="ovl" id="helpovl"><div id="help" class="card"><h3>Keyboard shortcuts</h3><table>
<tr><td><span class="kbd">/</span></td><td>focus search</td></tr>
<tr><td><span class="kbd">&#8984;K</span> / <span class="kbd">Ctrl K</span></td><td>command palette &mdash; jump to any chat</td></tr>
<tr><td><span class="kbd">j</span> <span class="kbd">k</span> / <span class="kbd">&darr;</span> <span class="kbd">&uarr;</span></td><td>move selection</td></tr>
<tr><td><span class="kbd">&crarr;</span> / <span class="kbd">o</span></td><td>open selected chat</td></tr>
<tr><td><span class="kbd">[</span> <span class="kbd">]</span></td><td>previous / next chat</td></tr>
<tr><td><span class="kbd">e</span></td><td>expand / collapse all steps</td></tr>
<tr><td><span class="kbd">b</span></td><td>toggle sidebar</td></tr>
<tr><td><span class="kbd">Esc</span></td><td>close / clear</td></tr>
</table></div></div>
<script>
const $=s=>document.querySelector(s), E=(t,c,h)=>{const e=document.createElement(t);if(c)e.className=c;if(h!=null)e.innerHTML=h;return e};
const esc=s=>(s||'').replace(/[&<>]/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[m]));
const typing=()=>{const a=document.activeElement;return a&&(a.tagName==='INPUT'||a.tagName==='TEXTAREA'||a.tagName==='SELECT')};
let items=[], sel=-1, allChats=[], fProject='', fHarness='', harnessList=[], projectList=[], acItems=[], acSel=0;

async function j(u){return (await fetch(u)).json()}
function setLhead(label,count){$('#lhead').innerHTML='<b>'+esc(label)+'</b>'+(count!=null?'<span class="cnt">'+count+'</span>':'')}

/* theme */
function applyTheme(t){document.body.classList.toggle('light',t==='light');$('#themebtn').innerHTML=t==='light'?'&#9681;':'&#9680;';localStorage.setItem('cm-theme',t)}
applyTheme(localStorage.getItem('cm-theme')||'dark');
$('#themebtn').onclick=()=>applyTheme(document.body.classList.contains('light')?'dark':'light');

/* data */
async function loadProjects(){
  const d=await j('/api/projects'); $('#pcnt').textContent=d.total+' / '+d.projects.length;
  projectList=d.projects.map(p=>p.project); harnessList=(d.harnesses||[]).map(h=>h.harness);
  const fp=$('#fproj'); fp.innerHTML='<option value="">All projects</option>';
  d.projects.forEach(p=>{const o=E('option',null,p.project+' ('+p.n+')');o.value=p.project;fp.append(o)});
  const fh=$('#fharness'); fh.innerHTML='<option value="">Any harness</option>';
  (d.harnesses||[]).forEach(h=>{const o=E('option',null,h.harness+' ('+h.n+')');o.value=h.harness;fh.append(o)});
  const s=$('#sidelist'); s.innerHTML='';
  d.projects.forEach(p=>{const el=E('div','p');el.dataset.proj=p.project;
    el.append(E('span','nm',esc(p.project)),E('span','n',p.n));
    el.onclick=()=>{fProject=p.project;$('#fproj').value=p.project;syncFilter();refresh()}; s.append(el)});
}
function syncFilter(){
  document.querySelectorAll('#side .p').forEach(x=>x.classList.toggle('sel',x.dataset.proj===fProject));
  $('#filterbtn').classList.toggle('active', !!(fProject||fHarness));
}
function parseQuery(raw){
  let proj=fProject, harn=fHarness, terms=[];
  (raw.match(/\S+/g)||[]).forEach(tok=>{
    let m=tok.match(/^@(?:h|harness):(.+)$/i); if(m){harn=m[1];return}
    m=tok.match(/^@(?:p|project):(.+)$/i); if(m){proj=m[1];return}
    m=tok.match(/^@(.+)$/); if(m){const v=m[1];
      if(harnessList.includes(v))harn=v; else if(projectList.includes(v))proj=v; return}
    terms.push(tok);
  });
  return {proj,harn,text:terms.join(' ')};
}
function refresh(){const q=parseQuery($('#q').value); q.text?doSearch(q.text,q.proj,q.harn):browse(q.proj,q.harn);}
async function browse(proj,harn){
  const qs=[]; if(proj)qs.push('project='+encodeURIComponent(proj)); if(harn)qs.push('harness='+harn);
  const d=await j('/api/chats?'+qs.join('&')); items=d.chats;
  setLhead((proj||'All projects')+(harn?'  ·  '+harn:''), items.length); renderList(false);
}
function hl(s){return esc(s).replace(/&gt;&gt;(.*?)&lt;&lt;/g,'<mark>$1</mark>')}
function renderList(withSnip){
  const L=$('#list'); L.innerHTML='';
  if(!items.length){L.append(E('div','empty','No chats match.'));sel=-1;return}
  items.forEach((r,idx)=>{
    const el=E('div','row'); el.dataset.i=idx;
    el.append(E('div','t',esc(r.title)||'(untitled)'));
    const m=E('div','m');m.append(E('span','tag mono',r.harness),E('span','date',r.date||''),E('span',null,esc(r.client||'')));
    if(r.project&&(withSnip||!fProject))m.append(E('span','tag',esc(r.project)));
    el.append(m);
    if(withSnip&&r.snippet)el.append(E('div','s',hl(r.snippet)));
    el.onclick=()=>openIdx(idx);
    L.append(el);
  });
  setSel(0,false);
}
function setSel(i,scroll=true){
  if(!items.length)return; sel=Math.max(0,Math.min(items.length-1,i));
  document.querySelectorAll('#list .row').forEach(x=>x.classList.toggle('sel',+x.dataset.i===sel));
  if(scroll){const el=document.querySelector('#list .row.sel');if(el)el.scrollIntoView({block:'nearest'})}
}
function openIdx(i){ if(items[i]){setSel(i);openChat(items[i].path)} }
let tmr; $('#q').oninput=()=>{acUpdate();clearTimeout(tmr);tmr=setTimeout(refresh,170)};
$('#q').addEventListener('blur',()=>setTimeout(acClose,120));
async function doSearch(text,proj,harn){
  const u='/api/search?q='+encodeURIComponent(text)+(proj?'&project='+encodeURIComponent(proj):'')+(harn?'&harness='+harn:'');
  const d=await j(u); items=d.results;
  setLhead('Results \u2014 \u201c'+text+'\u201d'+(proj?' in '+proj:'')+(harn?' \u00b7 '+harn:''),items.length); renderList(true);
}
/* @-filter autocomplete */
function acOpen(){return $('#ac').classList.contains('on')}
function acClose(){$('#ac').classList.remove('on');acItems=[]}
function positionAc(){const r=$('#q').getBoundingClientRect(),A=$('#ac');A.style.left=r.left+'px';A.style.top=(r.bottom+5)+'px';A.style.width=r.width+'px'}
function acUpdate(){
  const m=$('#q').value.match(/(?:^|\s)@([\w:-]*)$/); if(!m)return acClose();
  let frag=m[1].toLowerCase(), kind=null;
  const pm=frag.match(/^(h|harness|p|project):(.*)$/); if(pm){kind=pm[1][0]==='h'?'harness':'project';frag=pm[2]}
  let sug=[];
  if(kind!=='project')harnessList.filter(h=>h.includes(frag)).forEach(h=>sug.push({type:'harness',value:h}));
  if(kind!=='harness')projectList.filter(p=>p.toLowerCase().includes(frag)).forEach(p=>sug.push({type:'project',value:p}));
  acItems=sug.slice(0,24); if(!acItems.length)return acClose();
  acSel=0; const A=$('#ac');A.innerHTML='';
  acItems.forEach((s,i)=>{const el=E('div','ai'+(i===0?' sel':''));el.dataset.i=i;
    el.innerHTML='<span class="nm">@'+esc(s.value)+'</span><span class="ty">'+s.type+'</span>';
    el.onmousedown=e=>{e.preventDefault();acAccept(i)};A.append(el)});
  positionAc(); A.classList.add('on');
}
function acMove(d){if(!acItems.length)return;acSel=(acSel+d+acItems.length)%acItems.length;
  document.querySelectorAll('#ac .ai').forEach(x=>x.classList.toggle('sel',+x.dataset.i===acSel));
  const el=document.querySelector('#ac .ai.sel');if(el)el.scrollIntoView({block:'nearest'})}
function acAccept(i){const s=acItems[i];if(!s)return;
  $('#q').value=$('#q').value.replace(/(^|\s)@[\w:-]*$/,(mm,sp)=>sp+'@'+s.value+' ');
  acClose();$('#q').focus();refresh();}

/* filter dialog */
$('#filterbtn').onclick=()=>{$('#fproj').value=fProject;$('#fharness').value=fHarness;$('#filtovl').classList.add('on')};
$('#fdone').onclick=()=>{fProject=$('#fproj').value;fHarness=$('#fharness').value;$('#filtovl').classList.remove('on');syncFilter();refresh()};
$('#fclear').onclick=()=>{$('#fproj').value='';$('#fharness').value=''};
$('#filtovl').onclick=e=>{if(e.target.id==='filtovl')$('#filtovl').classList.remove('on')};

/* markdown */
function inlineMd(t){t=esc(t);
  t=t.replace(/`([^`]+)`/g,'<code>$1</code>').replace(/\*\*([^*]+)\*\*/g,'<b>$1</b>')
     .replace(/(^|[^*\w])\*([^*\n]+)\*/g,'$1<i>$2</i>')
     .replace(/\[([^\]]+)\]\(([^)\s]+)\)/g,'<a href="$2" target="_blank" rel="noopener">$1</a>');
  return t}
function textHtml(src){
  const blocks=[]; src=src.replace(/```([\w-]*)\n([\s\S]*?)```/g,(m,l,c)=>{blocks.push('<pre><code>'+esc(c)+'</code></pre>');return '\u0000'+(blocks.length-1)+'\u0000'});
  const Ls=src.split('\n'); let out='',i=0;
  const sep=s=>/^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)+\|?\s*$/.test(s);
  const cel=r=>r.replace(/^\s*\|/,'').replace(/\|\s*$/,'').split('|').map(c=>c.trim());
  while(i<Ls.length){let ln=Ls[i];
    if(/^\u0000\d+\u0000$/.test(ln.trim())){out+=blocks[+ln.trim().replace(/\u0000/g,'')];i++;continue}
    if(!ln.trim()){i++;continue}
    if(ln.includes('|')&&i+1<Ls.length&&sep(Ls[i+1])){const h=cel(ln);i+=2;const b=[];
      while(i<Ls.length&&Ls[i].includes('|')&&Ls[i].trim()){b.push(cel(Ls[i]));i++}
      out+='<table><thead><tr>'+h.map(c=>'<th>'+inlineMd(c)+'</th>').join('')+'</tr></thead><tbody>'+b.map(r=>'<tr>'+r.map(c=>'<td>'+inlineMd(c)+'</td>').join('')+'</tr>').join('')+'</tbody></table>';continue}
    let hm=ln.match(/^(#{1,6})\s+(.*)$/); if(hm){out+='<h3>'+inlineMd(hm[2])+'</h3>';i++;continue}
    if(/^\s*([-*_])(\s*\1){2,}\s*$/.test(ln)){out+='<hr>';i++;continue}
    if(/^\s*>/.test(ln)){let q=[];while(i<Ls.length&&/^\s*>/.test(Ls[i])){q.push(Ls[i].replace(/^\s*>\s?/,''));i++}out+='<blockquote>'+inlineMd(q.join(' '))+'</blockquote>';continue}
    if(/^\s*([-*+]|\d+[.)])\s+/.test(ln)){const ord=/^\s*\d+[.)]/.test(ln);let it=[];
      while(i<Ls.length&&/^\s*([-*+]|\d+[.)])\s+/.test(Ls[i])){it.push(Ls[i].replace(/^\s*([-*+]|\d+[.)])\s+/,''));i++}
      out+=(ord?'<ol>':'<ul>')+it.map(x=>'<li>'+inlineMd(x)+'</li>').join('')+(ord?'</ol>':'</ul>');continue}
    let p=[ln];i++; while(i<Ls.length&&Ls[i].trim()&&!/^\s*(#{1,6}\s|[-*+]\s|\d+[.)]\s|>|\u0000\d+\u0000)/.test(Ls[i])&&!(Ls[i].includes('|')&&i+1<Ls.length&&sep(Ls[i+1]))){p.push(Ls[i]);i++}
    out+='<p>'+inlineMd(p.join(' '))+'</p>';
  } return out;
}
const pv=(s,n=96)=>{s=(s||'').replace(/\s+/g,' ').trim();return esc(s.length>n?s.slice(0,n)+'\u2026':s)};
function stepHtml(p){
  if(p.type==='thinking')return '<details class="step think"><summary><span class="k">Thought</span><span class="pv">'+pv(p.text)+'</span></summary><div class="sbody">'+textHtml(p.text)+'</div></details>';
  let inner=''; if(p.args)inner+='<pre><code>'+esc(p.args)+'</code></pre>';
  if(p.result)inner+='<details class="res"><summary>\u25b8 result \u00b7 '+pv(p.result,80)+'</summary><pre><code>'+esc(p.result)+'</code></pre></details>';
  return '<details class="step tool"><summary><span class="k">'+esc(p.name)+'</span><span class="pv">'+pv(p.args)+'</span></summary><div class="sbody">'+inner+'</div></details>';
}
const ROLE={user:'You',assistant:'Assistant',system:'System'};
async function openChat(path){
  $('#view').innerHTML='<div class="empty">loading\u2026</div>';
  const d=await j('/api/chat?path='+encodeURIComponent(path));
  const V=$('#view'); if(!d.turns){V.innerHTML='<div class="empty">not found</div>';return}
  const m=d.meta||{}; const chips=['harness','project','client','created','updated','models'].filter(k=>m[k]).map(k=>'<span class="tag">'+esc(m[k])+'</span>').join('');
  V.innerHTML=''; const head=E('div');head.id='vhead';head.innerHTML='<h1>'+esc(d.title||'(untitled)')+'</h1><div class="chips">'+chips+'</div>';V.append(head);
  const th=E('div');th.id='thread';
  d.turns.forEach(t=>{const role=['user','assistant','system'].includes(t.role)?t.role:'assistant';
    (t.parts||[]).forEach(p=>{
      if(p.type==='text'){const turn=E('div','turn '+role);const lab=E('div','rlabel');lab.append(E('span',null,ROLE[role]||t.role));
        if(role==='assistant'&&t.model)lab.append(E('span','tag mono',esc(t.model)));
        turn.append(lab,E('div','bubble','<div class="msg">'+textHtml(p.text)+'</div>'));th.append(turn);}
      else{const w=E('div');w.innerHTML=stepHtml(p);th.append(w.firstChild);}
    });});
  V.append(th);V.scrollTop=0;
}
/* command palette */
let palSel=0, palItems=[];
function openPal(){ if(!allChats.length){j('/api/all').then(d=>{allChats=d.chats;palFilter()})} palFilter();
  $('#palovl').classList.add('on'); $('#palq').value=''; $('#palq').focus(); }
function closePal(){ $('#palovl').classList.remove('on') }
function palFilter(){
  const q=$('#palq').value.toLowerCase().trim();
  palItems=(q? allChats.filter(c=>(c.title+' '+c.project+' '+c.harness).toLowerCase().includes(q)) : allChats).slice(0,40);
  palSel=0; const R=$('#palres');R.innerHTML='';
  if(!palItems.length){R.append(E('div','empty','No matches.'));return}
  palItems.forEach((c,i)=>{const el=E('div','pr'+(i===0?' sel':''));el.dataset.i=i;
    el.innerHTML='<span class="t">'+esc(c.title||'(untitled)')+'</span><span class="tag mono">'+c.harness+'</span><span class="meta">'+esc(c.project)+' \u00b7 '+(c.date||'')+'</span>';
    el.onclick=()=>palOpen(i);R.append(el)});
}
function palMove(d){ if(!palItems.length)return; palSel=(palSel+d+palItems.length)%palItems.length;
  document.querySelectorAll('.pr').forEach(x=>x.classList.toggle('sel',+x.dataset.i===palSel));
  const el=document.querySelector('.pr.sel');if(el)el.scrollIntoView({block:'nearest'}) }
function palOpen(i){const c=palItems[i];if(c){closePal();openChat(c.path)}}
$('#palq').oninput=palFilter;
$('#palbtn').onclick=openPal; $('#helpbtn').onclick=()=>$('#helpovl').classList.toggle('on');
$('#palovl').onclick=e=>{if(e.target.id==='palovl')closePal()};
$('#helpovl').onclick=e=>{if(e.target.id==='helpovl')$('#helpovl').classList.remove('on')};
/* keyboard */
function anyOvl(){return document.querySelector('.ovl.on')}
function toggleAll(){const ds=document.querySelectorAll('#thread details.step');const anyClosed=[...ds].some(d=>!d.open);ds.forEach(d=>d.open=anyClosed)}
document.addEventListener('keydown',e=>{
  if($('#palovl').classList.contains('on')){
    if(e.key==='Escape')return closePal();
    if(e.key==='ArrowDown'){e.preventDefault();return palMove(1)}
    if(e.key==='ArrowUp'){e.preventDefault();return palMove(-1)}
    if(e.key==='Enter'){e.preventDefault();return palOpen(palSel)}
    return;
  }
  if(acOpen()&&document.activeElement.id==='q'){
    if(e.key==='ArrowDown'){e.preventDefault();return acMove(1)}
    if(e.key==='ArrowUp'){e.preventDefault();return acMove(-1)}
    if(e.key==='Enter'||e.key==='Tab'){e.preventDefault();return acAccept(acSel)}
    if(e.key==='Escape'){e.preventDefault();return acClose()}
  }
  if((e.metaKey||e.ctrlKey)&&e.key.toLowerCase()==='k'){e.preventDefault();return openPal()}
  if(e.key==='Escape'){document.querySelectorAll('.ovl.on').forEach(o=>o.classList.remove('on')); if(typing())e.target.blur(); return}
  if(typing()){
    if(e.target.id==='q'&&e.key==='Enter'){e.preventDefault();openIdx(sel<0?0:sel);$('#q').blur()}
    else if(e.target.id==='q'&&e.key==='ArrowDown'){e.preventDefault();$('#q').blur();setSel(0)}
    return;
  }
  if(anyOvl())return;
  if(e.key==='/'){e.preventDefault();$('#q').focus();return}
  if(e.key==='?'){$('#helpovl').classList.toggle('on');return}
  if(e.key==='f'){$('#filterbtn').click();return}
  if(e.key==='j'||e.key==='ArrowDown'){e.preventDefault();setSel(sel+1)}
  else if(e.key==='k'||e.key==='ArrowUp'){e.preventDefault();setSel(sel-1)}
  else if(e.key==='Enter'||e.key==='o'){openIdx(sel)}
  else if(e.key===']'){openIdx(sel+1)}
  else if(e.key==='['){openIdx(sel-1)}
  else if(e.key==='e'){toggleAll()}
  else if(e.key==='b'){document.body.classList.toggle('noside')}
});
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
