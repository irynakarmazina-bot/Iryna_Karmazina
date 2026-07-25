#!/usr/bin/env python3
"""Deploy n8n workflows via n8n public API. Read-only 'list' and 'create <file>'.
Never deletes. N8N_API_KEY comes from the VPS .env (loaded into cmd_runner env)."""
import sys, os, json, urllib.request, urllib.error

BASE = "https://irynakarmazina.app.n8n.cloud/api/v1"
KEY = os.environ.get("N8N_API_KEY", "")


def req(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(
        BASE + path, data=data, method=method,
        headers={"X-N8N-API-KEY": KEY, "Content-Type": "application/json",
                 "Accept": "application/json"})
    try:
        with urllib.request.urlopen(r, timeout=30) as resp:
            return resp.status, resp.read().decode("utf-8", "ignore")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "ignore")
    except Exception as e:
        return -1, str(e)


def main():
    if not KEY:
        print("ERROR: N8N_API_KEY not set")
        return 1
    action = sys.argv[1] if len(sys.argv) > 1 else "list"

    if action == "list":
        status, body = req("GET", "/workflows?limit=200")
        try:
            data = json.loads(body)
            items = data.get("data", data if isinstance(data, list) else [])
            print("LIST HTTP", status, "| count", len(items))
            for w in items:
                print("-", w.get("id"), "|", w.get("name"), "| active", w.get("active"))
        except Exception:
            print("LIST HTTP", status, body[:800])
        return 0

    if action == "create":
        path = sys.argv[2]
        with open(path, encoding="utf-8") as f:
            wf = json.load(f)
        settings = wf.get("settings") or {"executionOrder": "v1"}
        payload = {"name": wf["name"], "nodes": wf["nodes"],
                   "connections": wf["connections"], "settings": settings}
        status, body = req("POST", "/workflows", payload)
        try:
            d = json.loads(body)
            if status in (200, 201):
                print("CREATED HTTP", status, "| id", d.get("id"),
                      "| name", d.get("name"), "| active", d.get("active"))
            else:
                print("CREATE FAIL HTTP", status, "|", body[:800])
        except Exception:
            print("CREATE HTTP", status, body[:800])
        return 0

    if action == "exec":
        get_exec(sys.argv[2])
        return 0

    if action == "update":
        wid = sys.argv[2]; path = sys.argv[3]
        with open(path, encoding="utf-8") as f:
            wf = json.load(f)
        settings = wf.get("settings") or {"executionOrder": "v1"}
        payload = {"name": wf["name"], "nodes": wf["nodes"], "connections": wf["connections"], "settings": settings}
        status, body = req("PUT", "/workflows/" + wid, payload)
        try:
            d = json.loads(body)
            if status in (200, 201):
                print("UPDATED HTTP", status, "| id", d.get("id"), "| name", d.get("name"))
            else:
                print("UPDATE FAIL HTTP", status, "|", body[:800])
        except Exception:
            print("UPDATE HTTP", status, body[:800])
        return 0

    if action == "get":
        get_wf(sys.argv[2])
        return 0

    print("unknown action:", action)
    return 1



def get_exec(wid):
    status, body = req("GET", "/executions?workflowId=%s&limit=1&includeData=true" % wid)
    try:
        data = json.loads(body)
    except Exception:
        print("EXEC HTTP", status, body[:400]); return
    execs = data.get("data", [])
    if not execs:
        print("NO saved executions for", wid, "(manual runs may not be saved)"); return
    ex = execs[0]
    print("exec", ex.get("id"), "status", ex.get("status"), "finished", ex.get("finished"))
    run = ex.get("data", {}).get("resultData", {}).get("runData", {})
    for node, runs in run.items():
        for r in (runs or []):
            main = (r.get("data", {}) or {}).get("main", []) or []
            for oi, out in enumerate(main):
                ids = []
                for it in (out or []):
                    j = it.get("json", {}) if isinstance(it, dict) else {}
                    tag = j.get("Order ID", j.get("Country", "?"))
                    extra = ""
                    if "Status" in j or "Amount" in j:
                        extra = "(%s/%s)" % (j.get("Status"), j.get("Amount"))
                    ids.append("%s%s" % (tag, extra))
                print("-", node, "| out", oi, "| n=", len(out or []), "|", ", ".join(str(x) for x in ids))



def get_wf(wid):
    status, body = req("GET", "/workflows/" + wid)
    try:
        data = json.loads(body)
    except Exception:
        print("GET HTTP", status, body[:400]); return
    nodes = data.get("nodes", [])
    print("WF:", data.get("name"), "| nodes:", len(nodes))
    for n in nodes:
        t = n.get("type", "").replace("n8n-nodes-base.", "")
        extra = ""
        pr = n.get("parameters", {}) or {}
        if t == "summarize":
            extra = "fields=" + json.dumps(pr.get("fieldsToSummarize", pr.get("fieldsToSplitBy", "")), ensure_ascii=False)[:200]
        elif t == "aggregate":
            extra = json.dumps(pr.get("fieldsToAggregate", pr.get("aggregate", "")), ensure_ascii=False)[:200]
        elif t == "merge":
            extra = "mode=" + str(pr.get("mode")) + " " + str(pr.get("combineBy", pr.get("joinMode", "")))
        elif t in ("filter", "sort", "removeDuplicates", "itemLists"):
            extra = json.dumps(pr, ensure_ascii=False)[:200]
        print("-", n.get("name"), "|", t, "v", n.get("typeVersion"), ("| " + extra) if extra else "")
    print("CONNECTIONS:")
    for src, outs in (data.get("connections", {}) or {}).items():
        for oi, branch in enumerate((outs.get("main", []) or [])):
            for c in (branch or []):
                print("  ", src, "-[out%d]->" % oi, c.get("node"))


if __name__ == "__main__":
    sys.exit(main())
