#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Разова нормалізація колонки «Маршрут» у NocoDB: дефіси → стрілочки.

Та сама логіка, що у фасаді й кабінеті (`routeArrows`): дефіс перетворюється на
« → » ТІЛЬКИ якщо біля нього є пробіл хоча б з одного боку. Дефіс без пробілів
лишається недоторканим — інакше зламаються «Порт-Саїд», «Кам'янець-Подільський».

За замовчуванням НІЧОГО не пише: показує, що змінилося б. Запис — лише з --apply,
і перед записом старі значення зберігаються у файл-бекап.

Запуск:
  python3 normalize_routes.py            # тільки показати
  python3 normalize_routes.py --apply    # записати (з бекапом)
"""
import argparse
import datetime
import json
import re
import urllib.parse
import urllib.request

NC = "http://localhost:8080"
TABLE = "m58xsjo6at01ohl"
TOKEN_FILE = "/root/nocodb-token.txt"
BACKUP = "/root/routes-backup-%s.json"
COL = "Маршрут"
CHUNK = 25


def nc(method, path, data=None):
    tok = open(TOKEN_FILE).read().strip()
    body = json.dumps(data, ensure_ascii=False).encode() if data is not None else None
    req = urllib.request.Request(NC + path, data=body, method=method,
                                 headers={"Content-Type": "application/json", "xc-token": tok})
    with urllib.request.urlopen(req, timeout=120) as r:
        raw = r.read().decode()
        return json.loads(raw) if raw else {}


def all_rows():
    out, off = [], 0
    while True:
        # ВСІ назви колонок кирилицею — кодуємо весь параметр цілком,
        # інакше NocoDB відповідає помилкою (перевірено 02.08.2026).
        fields = urllib.parse.quote("Id,Угода," + COL, safe=",")
        js = nc("GET", "/api/v2/tables/%s/records?limit=1000&offset=%d&fields=%s"
                % (TABLE, off, fields))
        out += js.get("list", [])
        if js.get("pageInfo", {}).get("isLastPage"):
            return out
        off += 1000


def route_arrows(v):
    s = str(v if v is not None else "")
    s = re.sub(r"\s*(?:-->|->|→|—|–)\s*", " → ", s)
    s = re.sub(r"\s+-\s*|\s*-\s+", " → ", s)
    s = re.sub(r"\s*→\s*", " → ", s)
    s = re.sub(r"\s{2,}", " ", s)
    return s.strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="записати зміни (інакше лише показати)")
    a = ap.parse_args()

    print("=== НОРМАЛІЗАЦІЯ МАРШРУТІВ ===")
    rows = all_rows()
    changed = []
    for r in rows:
        old = str(r.get(COL) or "")
        new = route_arrows(old)
        if new and new != old:
            changed.append({"Id": r["Id"], "Угода": r.get("Угода"), "old": old, "new": new})

    print("Усього угод: %d   з маршрутом: %d   зміниться: %d"
          % (len(rows), sum(1 for r in rows if str(r.get(COL) or "").strip()), len(changed)))
    for c in changed[:60]:
        print("  %-6s %-42s → %s" % (c["Угода"], c["old"], c["new"]))
    if len(changed) > 60:
        print("  … ще %d" % (len(changed) - 60))

    if not a.apply:
        print("\n[показ] нічого не записано. Для запису: --apply")
        return
    if not changed:
        print("Нічого змінювати.")
        return

    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    path = BACKUP % stamp
    json.dump(changed, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("\nБекап старих значень: %s" % path)

    done = 0
    for i in range(0, len(changed), CHUNK):
        part = [{"Id": c["Id"], COL: c["new"]} for c in changed[i:i + CHUNK]]
        nc("PATCH", "/api/v2/tables/%s/records" % TABLE, part)
        done += len(part)
    print("Записано: %d" % done)

    # контроль після запису
    left = [r for r in all_rows() if route_arrows(r.get(COL)) != str(r.get(COL) or "").strip()
            and str(r.get(COL) or "").strip()]
    print("Перевірка після запису — лишилось ненормалізованих: %d" % len(left))


if __name__ == "__main__":
    main()
