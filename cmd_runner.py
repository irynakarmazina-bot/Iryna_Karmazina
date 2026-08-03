import hashlib, json, os, re, subprocess, time, urllib.request

# systemd loads vars via EnvironmentFile; fallback: parse .env manually
def _load_env():
    env_path = os.path.join(os.path.dirname(__file__), ".env")
    if not os.path.exists(env_path):
        return
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

_load_env()

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
GH_USER = "irynakarmazina-bot"
REPO_NAME = "Iryna_Karmazina"
PENDING_PATH = "cmds/pending.json"
RESULT_PATH = "cmds/result.json"
API_BASE = f"https://api.github.com/repos/{GH_USER}/{REPO_NAME}/contents"


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


# Стан переживає перезапуск сервісу. Потрібен, щоб команда не виконалась ДВІЧІ:
# якщо запис результату в GitHub не вдався (мережа), раніше last_id не оновлювався
# і та сама команда виконувалась знову — для деплою чи git push це небезпечно.
STATE_PATH = os.path.expanduser("~/.cmd_runner_state.json")


def load_state():
    try:
        return json.load(open(STATE_PATH, encoding="utf-8"))
    except Exception:
        return {}


def save_state(st):
    tmp = STATE_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False)
    os.replace(tmp, STATE_PATH)          # атомарно: обрив не лишить недописаного файла


def publish(result):
    """Записати результат у GitHub. Окремо, бо викликається і при повторі."""
    result_data = gh_get(RESULT_PATH)
    gh_put(RESULT_PATH, json.dumps(result, ensure_ascii=False, indent=2), result_data["sha"])


def main():
    print("cmd_runner started", flush=True)
    state = load_state()
    last_bad = None                      # відбиток невалідного pending.json

    while True:
        try:
            data = gh_get(PENDING_PATH)
            import base64
            raw = base64.b64decode(data["content"]).decode()

            # ── 1. pending.json не розбирається ──────────────────────────────
            # Було: виняток летів у загальний except, скрипт друкував Error і
            # ЧЕРЕЗ 5 СЕКУНД падав на тому самому місці — нескінченно. Черга
            # стояла ДЛЯ ВСІХ сесій, а сервіс виглядав живим (це вже ставалось
            # 02.08.2026). Тепер: кажемо про помилку в result.json ОДИН раз
            # і чекаємо на виправлений запис, не блокуючи нікого.
            try:
                content = json.loads(raw)
            except Exception as e:
                fp = hashlib.sha1(raw.encode()).hexdigest()
                if fp != last_bad:
                    last_bad = fp
                    m = re.search(r'"id"\s*:\s*"([^"]{1,80})"', raw)
                    publish({
                        "id": m.group(1) if m else "?",
                        "stdout": "",
                        "stderr": "cmds/pending.json не є коректним JSON (%s). "
                                  "Команду НЕ виконано. Формуй файл через json.dump "
                                  "і перевіряй json.load перед пушем." % str(e)[:120],
                        "returncode": -2,
                        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    })
                    print("BAD pending.json: %s" % e, flush=True)
                time.sleep(5)
                continue
            last_bad = None

            cmd_id = content.get("id")
            cmd = content.get("cmd", "")
            if not cmd_id or cmd_id == state.get("done_id"):
                time.sleep(5)
                continue

            # ── 2. команда вже виконана, але результат не доїхав ─────────────
            # Повторно НЕ виконуємо — лише доправляємо збережений результат.
            if cmd_id == state.get("ran_id") and state.get("result"):
                print(f"Retry publish [{cmd_id}]", flush=True)
                publish(state["result"])
                state["done_id"] = cmd_id
                save_state(state)
                time.sleep(5)
                continue

            print(f"Executing [{cmd_id}]: {cmd}", flush=True)
            result = run_cmd(cmd)
            result["id"] = cmd_id
            result["ts"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            # спершу запам'ятовуємо, що ВИКОНАЛИ, і лише потім публікуємо:
            # якщо публікація впаде, наступний оберт лише повторить публікацію
            state["ran_id"] = cmd_id
            state["result"] = result
            save_state(state)

            publish(result)
            state["done_id"] = cmd_id
            save_state(state)
            print(f"Done [{cmd_id}] rc={result['returncode']}", flush=True)
        except Exception as e:
            print(f"Error: {e}", flush=True)

        time.sleep(5)


if __name__ == "__main__":
    main()
