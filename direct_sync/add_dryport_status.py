#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Одноразово: варіант «Вивантажений в сухому порту» в колонці «Статус».

Вимога користувачки 01.08.2026. Ставиться між «Завантажений на потяг» і
«Вантаж доставлено»: контейнер уже знято з потяга на внутрішньому терміналі
(напр. Мостиська), але до кінцевої точки ще їде автом.

Трекінг ліній цього статусу дати НЕ може — Maersk веде відправку лише до
порту вивантаження. Статус ставить людина.

Запуск: python3 /root/direct-sync/add_dryport_status.py
"""
import json
import urllib.error
import urllib.request

NC = "http://localhost:8080"
TABLE = "m58xsjo6at01ohl"
TOK = open("/root/nocodb-token.txt").read().strip()
NEW = "Вивантажений в сухому порту"
AFTER = "Завантажений на потяг"


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
    st, meta = nc("GET", "/api/v2/meta/tables/%s" % TABLE)
    if st != 200:
        raise SystemExit("META_FAIL %s %s" % (st, meta))
    col = next((c for c in meta["columns"] if c["title"] == "Статус"), None)
    if not col:
        raise SystemExit("колонки «Статус» немає")
    opts = (col.get("colOptions") or {}).get("options", [])
    have = [o["title"] for o in opts]
    if NEW in have:
        print("варіант «%s» уже є — нічого не роблю" % NEW)
        return
    # бекап поточних варіантів — нічого не видаляємо, лише додаємо
    json.dump(have, open("/root/direct-sync/status_options.bak2.json", "w", encoding="utf-8"),
              ensure_ascii=False)
    keep = [{k: o[k] for k in ("id", "title", "color") if k in o} for o in opts]
    pos = next((i for i, o in enumerate(keep) if o["title"] == AFTER), len(keep) - 1)
    keep.insert(pos + 1, {"title": NEW})
    for i, o in enumerate(keep):
        o["order"] = i + 1
    st, js = nc("PATCH", "/api/v2/meta/columns/%s" % col["id"],
                {"title": "Статус", "uidt": "SingleSelect", "colOptions": {"options": keep}})
    if st not in (200, 201):
        raise SystemExit("не додався варіант: %s %s" % (st, str(js)[:250]))
    print("Додано статус «%s» після «%s»" % (NEW, AFTER))
    print("Порядок тепер: %s" % ", ".join(o["title"] for o in keep))


if __name__ == "__main__":
    main()
