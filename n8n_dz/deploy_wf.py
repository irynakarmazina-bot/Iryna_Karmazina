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

    print("unknown action:", action)
    return 1


if __name__ == "__main__":
    sys.exit(main())
