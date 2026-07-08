"""
Вивантаження діагностичних скріншотів у репозиторій (гілка розробки),
щоб їх можна було подивитись ззовні. Потребує GITHUB_TOKEN у середовищі.
"""
import base64
import json
import os
import urllib.request

OWNER = "irynakarmazina-bot"
REPO = "Iryna_Karmazina"
BRANCH = "claude/expeditor-automated-invoices-bdvl3o"


def upload_debug(name: str, data: bytes) -> str:
    """Викласти файл у ekspedytor/_debug/<name>. Повертає статус рядком."""
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        return "no-token"
    path = f"ekspedytor/_debug/{name}"
    api = f"https://api.github.com/repos/{OWNER}/{REPO}/contents/{path}"
    headers = {"Authorization": f"token {token}",
               "Accept": "application/vnd.github.v3+json"}

    sha = None
    try:
        req = urllib.request.Request(api + f"?ref={BRANCH}", headers=headers)
        with urllib.request.urlopen(req, timeout=15) as r:
            sha = json.loads(r.read()).get("sha")
    except Exception:
        pass

    body = {"message": f"debug: {name}",
            "content": base64.b64encode(data).decode(), "branch": BRANCH}
    if sha:
        body["sha"] = sha
    try:
        req = urllib.request.Request(
            api, data=json.dumps(body).encode(), method="PUT",
            headers={**headers, "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as r:
            return str(r.status)
    except Exception as e:
        return f"err {e}"
