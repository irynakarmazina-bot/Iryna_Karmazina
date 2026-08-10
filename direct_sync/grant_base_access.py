#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Додає користувача платформи В САМУ БАЗУ NocoDB (без цього він не бачить нічого).

НАВІЩО (виявлено 11.08.2026 на живому прикладі). Кнопка «Створити користувача»
в Налаштуваннях робила ДВІ речі з трьох:
    1) заводила акаунт для входу       (/api/v1/auth/user/signup)   ✔
    2) додавала рядок у довідник        (таблиця «Користувачі»)      ✔
    3) давала доступ до самої бази                                   �’ЦЬОГО НЕ БУЛО
Через це `irinabuhgalter33@gmail.com` мала «роль у базі = None»: вхід проходив,
а перший же запит за списком таблиць діставав
    403 Forbidden — You do not have permission to view list of tables with the roles: .
Далі платформа лишалась без переліку таблиць, роль падала до «Перегляд», і кожна
сторінка казала «Table 'undefined' not found». Ззовні це виглядало як «зламалась
платформа», хоча насправді користувача просто не пустили в базу.

ЯКА РОЛЬ У БАЗІ. `editor` — найменша з готових, якої вистачає для роботи, бо
платформа ПИШЕ навіть при звичайному вході (запис у «Журнал дій»), а бухгалтер
і фінансист ще й ставлять позначку переказу. `viewer` не підходить: вхід одразу
падав би на записі в журнал.
⚠️ Чесно про наслідок: `editor` у NocoDB означає читання і запис УСІХ таблиць.
Обмеження ролей живе у фасаді, а з боку бази їх немає — рівно та дірка, заради
якої робиться прошарок (server/gateway.py). Доки прошарок не ввімкнено,
будь-який користувач технічно дістає всі таблиці в обхід сторінки.

Нічого не видаляє. Якщо доступ уже є — не чіпає.
Запуск: python3 grant_base_access.py <email> [--role editor] [--dry-run]
"""
import json
import sys
import urllib.error
import urllib.request

NC = "http://127.0.0.1:8080"
BASE = "pbhr1qkpvx09z8m"
TOKEN_FILE = "/root/nocodb-token.txt"
TOK = open(TOKEN_FILE).read().strip()


def nc(method, path, data=None):
    body = json.dumps(data, ensure_ascii=False).encode() if data is not None else None
    req = urllib.request.Request(NC + path, data=body, method=method,
                                 headers={"Content-Type": "application/json", "xc-token": TOK})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            raw = r.read().decode()
            return r.status, (json.loads(raw) if raw else {})
    except urllib.error.HTTPError as e:
        return e.code, {"err": e.read().decode()[:400]}


def base_users():
    st, js = nc("GET", "/api/v2/meta/bases/%s/users" % BASE)
    if st != 200:
        raise SystemExit("не вдалося прочитати учасників бази: HTTP %s %s" % (st, js))
    return (js.get("users") or {}).get("list", [])


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        raise SystemExit("вкажи email: python3 grant_base_access.py <email>")
    email = args[0].strip().lower()
    dry = "--dry-run" in sys.argv
    role = "editor"
    if "--role" in sys.argv:
        role = sys.argv[sys.argv.index("--role") + 1]

    users = base_users()
    me = next((u for u in users if str(u.get("email") or "").lower() == email), None)
    if me is None:
        raise SystemExit("такого email серед користувачів NocoDB немає: %s\n"
                         "Спершу створи акаунт (Налаштування → Додати користувача)." % email)

    cur = me.get("roles")
    print("зараз: %s → роль у базі = %s" % (email, cur or "НЕМАЄ"))
    if cur:
        print("доступ уже є — нічого не міняю")
        return 0
    if dry:
        print("--dry-run: додала б роль «%s». Нічого не записую." % role)
        return 0

    st, res = nc("POST", "/api/v2/meta/bases/%s/users" % BASE,
                 {"email": email, "roles": role})
    if st not in (200, 201):
        st2, res2 = nc("PATCH", "/api/v2/meta/bases/%s/users/%s" % (BASE, me.get("id") or ""),
                       {"roles": role})
        if st2 not in (200, 201):
            raise SystemExit("не вдалося дати доступ: POST HTTP %s %s | PATCH HTTP %s %s"
                             % (st, res, st2, res2))

    after = next((u for u in base_users() if str(u.get("email") or "").lower() == email), {})
    got = after.get("roles")
    print("стало:  %s → роль у базі = %s" % (email, got or "НЕМАЄ"))
    if not got:
        print("УВАГА: роль так і не з'явилась — перевір вручну")
        return 1
    print("ГОТОВО")
    return 0


if __name__ == "__main__":
    sys.exit(main())
