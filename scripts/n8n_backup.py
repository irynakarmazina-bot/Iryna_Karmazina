#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Резервна копія воркфлоу n8n у репозиторій.

НАВІЩО (13.08.2026): бойові воркфлоу — трекінг Maersk (щодня 07:00) і бот
«Максим» — живуть ТІЛЬКИ в n8n Cloud. У репозиторії їх немає. Зникне акаунт,
скінчиться тариф, хтось помилково видалить — відновлювати нема з чого.
Щоденні резервні копії платформи (server/backup.py) сюди не дістають:
вони знімають сервер, а n8n — чужа хмара.

⚠️ ГОЛОВНЕ ПРО БЕЗПЕКУ. Вивантажувати воркфлоу «як є» в репозиторій НЕ МОЖНА.
Перевірено на практиці: у воркфлоу трекінгу client_id і client_secret Maersk
лежали відкритим текстом (MEMORY.md, розділ БЕЗПЕКА). Тому цей скрипт:
  * не звертається до /credentials взагалі — паролі й ключі n8n не вивантажує;
  * рекурсивно проходить кожен воркфлоу і ЗАМІНЮЄ значення полів, схожих на
    секрет, на «<ПРИБРАНО>»;
  * додатково чистить рядки, які виглядають як «Bearer ...» або довгий ключ;
  * рахує заміни і показує їх кількість, щоб було видно, що чистка спрацювала.
Правило 3 CLAUDE.md: паролі, токени й доступи НІКОЛИ не потрапляють у репозиторій.

ЩО ЦЕ НЕ Є. Це копія СХЕМИ роботи (вузли, зв'язки, код, розклади), а не
готовий до імпорту зліпок із доступами. Після відновлення credentials треба
завести заново — вони навмисно не зберігаються.

ЗАПУСК (на сервері, там лежить ключ):
    python3 /root/Iryna_Karmazina/scripts/n8n_backup.py

Ключ береться з ~/.n8n_env або зі змінних оточення:
    N8N_API_KEY=...            — ключ n8n API
    N8N_BASE_URL=https://...   — адреса, за замовчуванням irynakarmazina.app.n8n.cloud

Ключ ніде не друкується і в файли не потрапляє.
"""

import json
import os
import re
import sys
import urllib.error
import urllib.request

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(REPO, "n8n_backup")
DEFAULT_BASE = "https://irynakarmazina.app.n8n.cloud"

# Назви полів, значення яких вважаємо секретом. Свідомо ширше, ніж треба:
# зайва заміна псує лише читабельність копії, пропущений ключ — це витік.
SECRET_KEY_RE = re.compile(
    r"(?i)(token|secret|password|passwd|passphrase|api[_-]?key|apikey|"
    r"authorization|auth[_-]?header|cookie|client[_-]?id|client[_-]?secret|"
    r"access[_-]?key|private[_-]?key|credential)"
)
# Значення, які виглядають як секрет самі по собі, у якому б полі не лежали.
SECRET_VALUE_RE = re.compile(
    r"(?i)(bearer\s+[a-z0-9._\-]{16,}|"          # Bearer <токен>
    r"basic\s+[a-z0-9+/=]{16,}|"                  # Basic <base64>
    r"\beyJ[a-z0-9._\-]{20,}|"                    # JWT
    r"\bsk-[a-z0-9\-]{20,})"                      # ключі виду sk-...
)
MASK = "<ПРИБРАНО>"

# Поля, які міняються при кожному збереженні й лише створюють шум у git.
NOISE_KEYS = {"updatedAt", "createdAt", "versionId", "triggerCount"}

_redactions = 0


def load_key():
    """Ключ і адреса: спершу оточення, потім ~/.n8n_env. Ключ не друкуємо."""
    key = os.environ.get("N8N_API_KEY", "")
    base = os.environ.get("N8N_BASE_URL", "")
    env_path = os.path.expanduser("~/.n8n_env")
    if (not key or not base) and os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                v = v.strip().strip('"').strip("'")
                if k.strip() == "N8N_API_KEY" and not key:
                    key = v
                if k.strip() == "N8N_BASE_URL" and not base:
                    base = v
    return key, (base or DEFAULT_BASE).rstrip("/")


def api(base, key, path):
    req = urllib.request.Request(
        f"{base}/api/v1/{path}",
        headers={"X-N8N-API-KEY": key, "Accept": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())


def clean(obj, parent_key=""):
    """Рекурсивна чистка. Повертає копію без секретів і без шумових полів."""
    global _redactions
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if k in NOISE_KEYS:
                continue
            # Блок credentials у вузлі — лишаємо тільки назву й id прив'язки,
            # самих даних доступу n8n через API і так не віддає, але страхуємось.
            if k == "credentials" and isinstance(v, dict):
                out[k] = {
                    name: {"id": (ref or {}).get("id"), "name": (ref or {}).get("name")}
                    for name, ref in v.items()
                    if isinstance(ref, dict)
                }
                continue
            if SECRET_KEY_RE.search(k) and isinstance(v, (str, int)) and str(v).strip():
                out[k] = MASK
                _redactions += 1
                continue
            out[k] = clean(v, k)
        return out
    if isinstance(obj, list):
        return [clean(i, parent_key) for i in obj]
    if isinstance(obj, str) and SECRET_VALUE_RE.search(obj):
        _redactions += 1
        return SECRET_VALUE_RE.sub(MASK, obj)
    return obj


def safe_name(s):
    s = re.sub(r"[^\w\-. ]+", "_", s or "", flags=re.UNICODE).strip()
    return (s or "workflow")[:80]


def main():
    key, base = load_key()
    if not key:
        print("ПОМИЛКА: не знайдено N8N_API_KEY (ні в оточенні, ні в ~/.n8n_env)")
        return 2

    try:
        data = api(base, key, "workflows?limit=250")
    except urllib.error.HTTPError as e:
        print(f"ПОМИЛКА: n8n відповів {e.code} — перевір ключ і адресу {base}")
        return 3
    except Exception as e:
        print(f"ПОМИЛКА зв'язку з n8n: {e}")
        return 3

    items = data.get("data", data if isinstance(data, list) else [])
    if not items:
        print("n8n не повернув жодного воркфлоу — нічого не змінюю")
        return 1

    os.makedirs(OUT_DIR, exist_ok=True)
    index = []
    written = 0

    for w in items:
        wid = str(w.get("id", ""))
        try:
            full = api(base, key, f"workflows/{wid}")
        except Exception as e:
            print(f"  ! {wid} {w.get('name','')}: не вдалося прочитати ({e})")
            continue
        nodes = full.get("nodes") or []
        cleaned = clean(full)
        fname = f"{wid}-{safe_name(full.get('name'))}.json"
        path = os.path.join(OUT_DIR, fname)
        text = json.dumps(cleaned, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        # Перезаписуємо тільки якщо вміст справді змінився — щоб git не шумів.
        old = open(path, encoding="utf-8").read() if os.path.exists(path) else None
        if old != text:
            with open(path, "w", encoding="utf-8") as f:
                f.write(text)
            written += 1
        index.append({
            "id": wid,
            "name": full.get("name", ""),
            "active": bool(full.get("active")),
            "nodes": len(nodes),
            "file": fname,
        })

    index.sort(key=lambda r: (not r["active"], r["name"].lower()))
    lines = [
        "# Резервна копія воркфлоу n8n",
        "",
        "Створює `scripts/n8n_backup.py`. Це копія **схеми** роботи, не зліпок",
        "для імпорту: доступи (credentials) навмисно не зберігаються, їх треба",
        "заводити заново. Значення, схожі на ключі й паролі, замінені на",
        "`<ПРИБРАНО>` — див. шапку скрипта.",
        "",
        f"Джерело: `{base}` · воркфлоу: **{len(index)}**",
        "",
        "| Активний | Назва | Вузлів | Файл |",
        "|---|---|---|---|",
    ]
    for r in index:
        lines.append(
            f"| {'✅' if r['active'] else '—'} | {r['name']} | {r['nodes']} | `{r['file']}` |"
        )
    with open(os.path.join(OUT_DIR, "README.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    print(f"воркфлоу: {len(index)} · оновлено файлів: {written} · "
          f"замін секретів: {_redactions}")
    print(f"тека: {OUT_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
