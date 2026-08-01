#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Одноразово: таблиця «Журнал дій» — хто, коли і що змінив у платформі.

Вимога користувачки 01.08.2026: «ще має бути журнал дій по користувачах».
Записи створює сама платформа при кожній правці, вході й завантаженні документа.
Нічого не видаляє; якщо таблиця вже є — просто повідомляє.

Запуск: python3 /root/direct-sync/create_audit_table.py
"""
import json
import urllib.error
import urllib.request

NC = "http://localhost:8080"
TOK = open("/root/nocodb-token.txt").read().strip()
TITLE = "Журнал дій"

COLS = [
    ("Час", "DateTime"),
    ("Користувач", "SingleLineText"),
    ("Роль", "SingleLineText"),
    ("Дія", "SingleLineText"),
    ("Обʼєкт", "SingleLineText"),
    ("Поле", "SingleLineText"),
    ("Було", "LongText"),
    ("Стало", "LongText"),
]


def nc(method, path, data=None):
    body = json.dumps(data, ensure_ascii=False).encode() if data is not None else None
    req = urllib.request.Request(NC + path, data=body, method=method,
                                 headers={"Content-Type": "application/json", "xc-token": TOK})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            raw = r.read().decode()
            return r.status, (json.loads(raw) if raw else {})
    except urllib.error.HTTPError as e:
        return e.code, {"err": e.read().decode()[:300]}


def main():
    st, bases = nc("GET", "/api/v2/meta/bases")
    if st != 200:
        raise SystemExit("BASES_FAIL %s %s" % (st, bases))
    base_id = None
    for b in bases.get("list", []):
        st, ts = nc("GET", "/api/v2/meta/bases/%s/tables" % b["id"])
        if st != 200:
            continue
        titles = {t["title"]: t["id"] for t in ts.get("list", [])}
        if "Диспетчеризація" in titles:        # та сама база, що й у платформи
            base_id = b["id"]
            if TITLE in titles:
                print("Таблиця «%s» уже є (id %s) — нічого не роблю" % (TITLE, titles[TITLE]))
                return
            break
    if not base_id:
        raise SystemExit("не знайшов базу з таблицею «Диспетчеризація»")

    st, js = nc("POST", "/api/v2/meta/bases/%s/tables" % base_id, {
        "title": TITLE,
        "table_name": "audit_log",
        "columns": [{"title": t, "uidt": u} for t, u in COLS],
    })
    if st not in (200, 201):
        raise SystemExit("не створилась таблиця: %s %s" % (st, str(js)[:300]))
    print("Створено таблицю «%s», id %s" % (TITLE, js.get("id")))
    print("колонки: %s" % ", ".join(t for t, _ in COLS))


if __name__ == "__main__":
    main()
