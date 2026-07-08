"""
Діагностика: залогінитись по RDP, зробити скріншот робочого столу
і викласти його у репозиторій (гілка debug-shots), щоб можна було подивитись.
Нічого в 1С не робить. Запуск:
  python -m ekspedytor.shot
"""
import base64
import json
import os
import urllib.request

from dotenv import load_dotenv

from .session import RDPSession

load_dotenv()

OWNER = "irynakarmazina-bot"
REPO = "Iryna_Karmazina"
BRANCH = "claude/expeditor-automated-invoices-bdvl3o"
REPO_PATH = "ekspedytor/_debug/desktop.png"


def _upload(data: bytes) -> str:
    token = os.environ["GITHUB_TOKEN"]
    api = f"https://api.github.com/repos/{OWNER}/{REPO}/contents/{REPO_PATH}"
    sha = None
    try:
        req = urllib.request.Request(
            api + f"?ref={BRANCH}",
            headers={"Authorization": f"token {token}",
                     "Accept": "application/vnd.github.v3+json"})
        with urllib.request.urlopen(req, timeout=15) as r:
            sha = json.loads(r.read()).get("sha")
    except Exception:
        pass
    body = {
        "message": "debug: скріншот робочого столу RDP",
        "content": base64.b64encode(data).decode(),
        "branch": BRANCH,
    }
    if sha:
        body["sha"] = sha
    req = urllib.request.Request(
        api, data=json.dumps(body).encode(), method="PUT",
        headers={"Authorization": f"token {token}",
                 "Accept": "application/vnd.github.v3+json",
                 "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return str(r.status)


def main():
    s = RDPSession(
        host=os.getenv("RDP_HOST", "unitex.rdport.net:31230"),
        user=os.getenv("RDP_USER", "karmazina.i"),
        password=os.environ["RDP_PASSWORD"],
    )
    try:
        s.start()
        img = s.screenshot()
        print("shot bytes:", len(img))
        print("upload status:", _upload(img))
    finally:
        s.stop()


if __name__ == "__main__":
    main()
