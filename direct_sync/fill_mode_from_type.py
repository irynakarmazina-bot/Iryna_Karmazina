#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Одноразове заповнення «Вид перевезення» зі старої колонки «Тип» (майстер-таблиця).

Мапінг заповнюється ЛИШЕ підтвердженими користувачкою відповідностями (MAP нижче).
Значення «Тип», яких у MAP немає, не мапляться — скрипт їх просто перелічує,
щоб спитати. Наявне непорожнє «Вид перевезення» НЕ перезаписується.

Запуск: python3 /root/direct-sync/fill_mode_from_type.py [--dry-run]
"""
import argparse
import collections
import json
import urllib.error
import urllib.parse
import urllib.request

NC = "http://localhost:8080"
TABLE = "m58xsjo6at01ohl"
TOK = open("/root/nocodb-token.txt").read().strip()
CHUNK = 25
COL = "Вид перевезення"

# Підтверджено користувачкою 30.07.2026:
#   «Море + авто» лишаємо як окремий вид («це те саме», що фрахт+ТЕО+авто);
#   Авіа / Авто / Фрахт — ті самі слова, що в її списку (різниця лише у великій літері).
#   «Море + залізниця» = «фрахт+ТЕО+залізниця» («одне і те саме»);
#   «Море» = «фрахт» («одне і те саме»; користувачка зазначила, що чистий фрахт рідкий —
#     зазвичай замовляють комплекс фрахт+авто або фрахт+залізниця, і це вони ще правитимуть);
#   «ТЕО+АВТО» = «ТЕО+авто» (той самий варіант, різниця лише у великих літерах).
MAP = {
    "Море + авто": "Море + авто",
    "Море": "фрахт",
    "ТЕО+АВТО": "ТЕО+авто",
    "Море + залізниця": "фрахт+ТЕО+залізниця",
    "Авіа": "авіа",
    "Авто": "авто",
    "Фрахт": "фрахт",
}


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
    except Exception as e:  # noqa: BLE001
        return 0, {"err": str(e)[:300]}


def ensure_options(values, dry):
    st, js = nc("GET", "/api/v2/meta/tables/%s" % TABLE)
    if st != 200:
        raise SystemExit("META_FAIL %s" % st)
    col = next(c for c in js["columns"] if c["title"] == COL)
    opts = (col.get("colOptions") or {}).get("options", [])
    have = {o["title"] for o in opts}
    missing = sorted(v for v in values if v not in have)
    if not missing:
        return have
    if dry:
        print("DRY: додати варіанти: %s" % ", ".join(missing))
        return have | set(missing)
    new = [{k: o[k] for k in ("id", "title", "color", "order") if k in o} for o in opts]
    for i, t in enumerate(missing):
        new.append({"title": t, "order": len(opts) + i + 1})
    st, js = nc("PATCH", "/api/v2/meta/columns/%s" % col["id"],
                {"title": COL, "uidt": "SingleSelect", "colOptions": {"options": new}})
    if st not in (200, 201):
        raise SystemExit("не додались варіанти: %s %s" % (st, str(js)[:200]))
    print("Додано варіанти: %s" % ", ".join(missing))
    return have | set(missing)


def records():
    out, off = [], 0
    q = urllib.parse.quote(",".join(["Id", "Угода", "Тип", COL]), safe=",")
    while True:
        st, js = nc("GET", "/api/v2/tables/%s/records?limit=200&offset=%d&fields=%s" % (TABLE, off, q))
        if st != 200:
            raise SystemExit("READ_FAIL %s %s" % (st, js))
        out += js.get("list", [])
        if js.get("pageInfo", {}).get("isLastPage"):
            return out
        off += 200


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    rows = records()
    ensure_options(set(MAP.values()), a.dry_run)

    patches, unmapped = [], collections.Counter()
    for r in rows:
        t = str(r.get("Тип") or "").strip()
        if not t:
            continue
        target = MAP.get(t)
        if not target:
            unmapped[t] += 1
            continue
        if str(r.get(COL) or "").strip() == target:
            continue
        if str(r.get(COL) or "").strip():
            continue          # вже заповнено іншим значенням — не перезаписуємо
        patches.append({"Id": r["Id"], COL: target})

    print("Заповнити: %d угод" % len(patches))
    for k, v in collections.Counter(p[COL] for p in patches).most_common():
        print("   %-16s %d" % (k, v))
    if unmapped:
        print("НЕ МАПЛЕНО (чекає рішення користувачки):")
        for k, v in unmapped.most_common():
            print("   %-26s %d" % (k, v))
    if a.dry_run:
        print("DRY_DONE nothing_written")
        return

    fails = 0
    for i in range(0, len(patches), CHUNK):
        st, js = nc("PATCH", "/api/v2/tables/%s/records" % TABLE, patches[i:i + CHUNK])
        if st not in (200, 201):
            fails += 1
            print("UPDATE_FAIL %s %s" % (st, str(js)[:200]))
    print("FILL_OK updated=%d fails=%d" % (len(patches), fails))


if __name__ == "__main__":
    main()
