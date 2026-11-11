#!/usr/bin/env python3
"""
chat-memory mcp - a Model Context Protocol server exposing your chat memory as
native tools to any MCP-capable harness (Claude Code, Cursor, Codex, Gemini CLI...).

Pure standard library: JSON-RPC 2.0 over stdio (newline-delimited messages).
Tools:
  - recall(query, project?, harness?, all?, limit?)  -> ranked past chats + snippets
  - get_chat(path)                                   -> full transcript of one chat
  - list_projects()                                  -> projects with chat counts
"""
import sys, os, json, argparse
from . import cmlib, recall, web
from . import __version__

PROTOCOL = "2025-06-18"

TOOLS = [
    {
        "name": "recall",
        "description": ("Search the user's past AI coding chats (across Cursor, Claude Code, "
                        "Codex, Gemini, etc.) for relevant prior context. Returns ranked matches "
                        "with title, project, date and a snippet, plus a 'path' to fetch the full "
                        "chat via get_chat. Use before implementing or debugging a feature to reuse "
                        "earlier decisions and avoid repeating mistakes."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "search keywords"},
                "project": {"type": "string", "description": "scope to a project (repo name); omit to search all"},
                "harness": {"type": "string", "description": "filter by tool: cursor|cursor-agent|claude-code|opencode|pi|codex|gemini"},
                "since": {"type": "string", "description": "lower bound date, YYYY-MM or YYYY-MM-DD"},
                "limit": {"type": "integer", "description": "max results (default 8)"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "get_chat",
        "description": "Return the full transcript (markdown) of one chat, given its 'path' from a recall result.",
        "inputSchema": {
            "type": "object",
            "properties": {"path": {"type": "string", "description": "chat path from a recall result"}},
            "required": ["path"],
        },
    },
    {
        "name": "list_projects",
        "description": "List projects (repos) that have stored chats, with counts. Useful to discover what memory exists.",
        "inputSchema": {"type": "object", "properties": {}},
    },
]


def _tool_recall(a):
    q = (a.get("query") or "").strip()
    if not q:
        return "error: 'query' is required"
    recall.ensure_index()
    rows = recall.search(q, project=a.get("project") or None,
                         harness=a.get("harness") or None, since=a.get("since") or None,
                         k=int(a.get("limit") or 8))
    if not rows:
        return "No matching chats."
    out = [f"{len(rows)} result(s) for \"{q}\":", ""]
    for i, (r, snip) in enumerate(rows, 1):
        out.append(f"{i}. {r['title']}")
        out.append(f"   {r['date']} · {r['harness']} · project:{r['project']} · client:{r['client']}")
        out.append(f"   path: {r['path']}")
        if snip:
            out.append(f"   … {snip} …")
        out.append("")
    out.append("Use get_chat(path) to read any of these in full.")
    return "\n".join(out)


def _tool_get_chat(a):
    path = a.get("path") or ""
    base = os.path.realpath(cmlib.projects_dir())
    full = os.path.realpath(os.path.join(cmlib.data_dir(), path))
    if not full.startswith(base + os.sep) or not full.endswith(".md") or not os.path.isfile(full):
        return "error: chat not found (path must come from a recall result)"
    try:
        return open(full, encoding="utf-8", errors="ignore").read()
    except Exception as e:
        return f"error: {e}"


def _tool_list_projects(a):
    d = web.api_projects()
    lines = [f"{d['total']} chats across {len(d['projects'])} projects:", ""]
    for p in d["projects"]:
        lines.append(f"- {p['project']}  ({p['n']}, last {p['last']})")
    return "\n".join(lines)


DISPATCH = {"recall": _tool_recall, "get_chat": _tool_get_chat, "list_projects": _tool_list_projects}


def handle(msg):
    mid = msg.get("id")
    method = msg.get("method")
    params = msg.get("params") or {}

    def ok(result):
        return None if mid is None else {"jsonrpc": "2.0", "id": mid, "result": result}

    def err(code, message):
        return None if mid is None else {"jsonrpc": "2.0", "id": mid, "error": {"code": code, "message": message}}

    if method == "initialize":
        return ok({
            "protocolVersion": params.get("protocolVersion", PROTOCOL),
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "chat-memory", "version": __version__},
        })
    if method in ("notifications/initialized", "initialized"):
        return None
    if method == "ping":
        return ok({})
    if method == "tools/list":
        return ok({"tools": TOOLS})
    if method == "tools/call":
        name = params.get("name")
        args = params.get("arguments") or {}
        fn = DISPATCH.get(name)
        if not fn:
            return ok({"content": [{"type": "text", "text": f"unknown tool: {name}"}], "isError": True})
        try:
            text = fn(args)
            is_err = isinstance(text, str) and text.startswith("error:")
            return ok({"content": [{"type": "text", "text": text}], "isError": is_err})
        except Exception as e:
            return ok({"content": [{"type": "text", "text": f"error: {e}"}], "isError": True})
    if method == "resources/list":
        return ok({"resources": []})
    if method == "prompts/list":
        return ok({"prompts": []})
    return err(-32601, f"method not found: {method}")


def serve():
    try:
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except Exception:
                continue
            resp = handle(msg)
            if resp is not None:
                sys.stdout.write(json.dumps(resp) + "\n")
                sys.stdout.flush()
    except (KeyboardInterrupt, EOFError, BrokenPipeError):
        pass


def main(argv=None):
    argparse.ArgumentParser(prog="chat-memory mcp",
                            description="run the Model Context Protocol server (stdio)").parse_args(argv)
    if sys.stdin.isatty():
        sys.stderr.write(
            "chat-memory MCP server (stdio).\n"
            "This is meant to be launched by an MCP-capable tool, not run by hand.\n"
            "Add it once, e.g.:  claude mcp add chat-memory -- chat-memory mcp\n"
            "See: https://github.com/insideaayush/chat-memory-sync/blob/main/docs/agent-integration.md\n"
            "Waiting for JSON-RPC on stdin\u2026 (Ctrl-C to quit)\n")
        sys.stderr.flush()
    serve()
    return 0


if __name__ == "__main__":
    main()
