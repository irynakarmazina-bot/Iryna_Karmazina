import json, os, subprocess, time, urllib.request, urllib.error
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
GH_USER = "irynakarmazina-bot"
REPO_NAME = "Iryna_Karmazina"
PENDING_PATH = "cmds/pending.json"
RESULT_PATH = "cmds/result.json"
API_BASE = f"https://api.github.com/repos/{GH_USER}/{REPO_NAME}/contents"

last_id = None


def gh_get(path):
    req = urllib.request.Request(
        f"{API_BASE}/{path}",
        headers={"Authorization": f"token {GITHUB_TOKEN}", "Accept": "application/vnd.github.v3+json"},
    )
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())


def gh_put(path, content_str, sha):
    import base64
    data = json.dumps({
        "message": f"relay: update {path}",
        "content": base64.b64encode(content_str.encode()).decode(),
        "sha": sha,
    }).encode()
    req = urllib.request.Request(
        f"{API_BASE}/{path}",
        data=data,
        method="PUT",
        headers={
            "Authorization": f"token {GITHUB_TOKEN}",
            "Accept": "application/vnd.github.v3+json",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())


def run_cmd(cmd):
    try:
        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=120
        )
        stdout = result.stdout[-3000:] if len(result.stdout) > 3000 else result.stdout
        return {"stdout": stdout, "stderr": result.stderr[-500:], "returncode": result.returncode}
    except subprocess.TimeoutExpired:
        return {"stdout": "", "stderr": "Timeout (120s)", "returncode": -1}
    except Exception as e:
        return {"stdout": "", "stderr": str(e), "returncode": -1}


def main():
    global last_id
    print("cmd_runner started")
    while True:
        try:
            data = gh_get(PENDING_PATH)
            import base64
            content = json.loads(base64.b64decode(data["content"]).decode())
            cmd_id = content.get("id")
            cmd = content.get("cmd", "")

            if cmd_id and cmd_id != last_id:
                print(f"Executing [{cmd_id}]: {cmd}")
                result = run_cmd(cmd)
                result["id"] = cmd_id
                result["ts"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

                result_data = gh_get(RESULT_PATH)
                gh_put(RESULT_PATH, json.dumps(result, ensure_ascii=False, indent=2), result_data["sha"])
                last_id = cmd_id
                print(f"Done [{cmd_id}] rc={result['returncode']}")
        except Exception as e:
            print(f"Error: {e}")

        time.sleep(5)


if __name__ == "__main__":
    main()
