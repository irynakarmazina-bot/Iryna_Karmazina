#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Заповнення «Вид перевезення», «FCL/LCL» і «Статус» з Експедитора.

ЗВІДКИ ДАНІ (перевірено 31.07.2026):
  * «Вид перевезення» ← Document_Сделка.ТипСделки_Key.
    Каталог типів угод в OData НЕ опублікований, тому назви виведені зіставленням
    GUID зі старою колонкою «Тип» у платформі — кожен GUID дав однозначну відповідність:
        9c247035  134  Море+авто(100) / Фрахт+ТЕО+Авто(23)     → фрахт+ТЕО+авто
        3885a4c4   40  Море+залізниця(23) / Фрахт+залізниця(15) → фрахт+ТЕО+залізниця
        326dd400   31  Залізниця(22) / Залізничне перевезення(8)→ ТЕО+залізниця
        326dd3fe   20  Море(14) / Фрахт(5)                      → фрахт
        24ccaf2c   12  ТЕО+АВТО(9) / Авто(2)                    → ТЕО+авто
        65f8d234    7  Авто(7)                                  → авто
        326dd3f8    6  Авіа(6)                                  → авіа
    НЕ МАПИМО (чекає рішення користувачки):
        055a1679    8  Збірний вантаж / Збірний   — це LCL, а не вид перевезення
        ab8b270f    1  МО
        00000000    7  тип не заповнений в самому Експедиторі
  * «FCL/LCL» ← Document_Сделка.СборныйГруз (True = LCL, авторитетно з Експедитора);
    FCL — морська угода з номером контейнера і без прапорця збірності.

ПРАВИЛА БЕЗПЕКИ: наявні непорожні значення НЕ перезаписуються; нічого не видаляється;
статус ставиться лише там, де він порожній: «Букинг» → «Букінг»,
«Выполняется» → «Виконується» (рішення користувачки 31.07.2026).
«ВыставленСчет» досі не мапиться — окремого рішення по ньому немає.

Запуск: python3 /root/direct-sync/fill_mode_and_load.py [--dry-run]
"""
import argparse
import collections
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

NC = "http://localhost:8080"
TABLE = "m58xsjo6at01ohl"
TOK = open("/root/nocodb-token.txt").read().strip()
CHUNK = 25
FINREP = "/root/unitex-finrep"

MODE_BY_TYPE = {
    "9c247035": "фрахт+ТЕО+авто",
    "3885a4c4": "фрахт+ТЕО+залізниця",
    "326dd400": "ТЕО+залізниця",
    "326dd3fe": "фрахт",
    "24ccaf2c": "ТЕО+авто",
    "65f8d234": "авто",
    "326dd3f8": "авіа",
}
UNMAPPED = {"055a1679": "Збірний", "ab8b270f": "МО", "00000000": "тип не заповнений в Експедиторі"}
SEA_MODES = {"фрахт", "фрахт+ТЕО", "фрахт+ТЕО+МО", "фрахт+ТЕО+авто", "фрахт+ТЕО+залізниця", "ТЕО+авто"}
# Рішення користувачки 31.07.2026: «ВыставленСчет» теж «Виконується» —
# «якщо немає іншої інформації (або людина поставила Доставлено,
#  або є в угоді дата завершення робіт)».
STAGE_TO_STATUS = {"Букинг": "Букінг",
                   "Выполняется": "Виконується",
                   "ВыставленСчет": "Виконується"}
DELIVERED = "Вантаж доставлено"
WORKS_DONE_FIELD = "ДатаВыполненияРабот"


def has_date(v):
    s = str(v or "")
    return bool(s) and not s.startswith("0001-01-01")


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


def records():
    out, off = [], 0
    while True:
        st, js = nc("GET", "/api/v2/tables/%s/records?limit=200&offset=%d" % (TABLE, off))
        if st != 200:
            raise SystemExit("READ_FAIL %s %s" % (st, js))
        out += js.get("list", [])
        if js.get("pageInfo", {}).get("isLastPage"):
            return out
        off += 200


def ensure_options(col_title, values, dry):
    st, js = nc("GET", "/api/v2/meta/tables/%s" % TABLE)
    if st != 200:
        raise SystemExit("META_FAIL %s" % st)
    col = next((c for c in js["columns"] if c["title"] == col_title), None)
    if not col:
        raise SystemExit("немає колонки «%s»" % col_title)
    if col["uidt"] != "SingleSelect":
        return None                       # звичайний текст — варіанти не потрібні
    opts = (col.get("colOptions") or {}).get("options", [])
    have = {o["title"] for o in opts}
    missing = sorted(v for v in values if v and v not in have)
    if not missing:
        return have
    if dry:
        print("DRY: у «%s» додати варіанти: %s" % (col_title, ", ".join(missing)))
        return have | set(missing)
    new = [{k: o[k] for k in ("id", "title", "color", "order") if k in o} for o in opts]
    for i, t in enumerate(missing):
        new.append({"title": t, "order": len(opts) + i + 1})
    st, js = nc("PATCH", "/api/v2/meta/columns/%s" % col["id"],
                {"title": col_title, "uidt": "SingleSelect", "colOptions": {"options": new}})
    if st not in (200, 201):
        raise SystemExit("не додались варіанти в «%s»: %s %s" % (col_title, st, str(js)[:200]))
    print("Додано варіанти в «%s»: %s" % (col_title, ", ".join(missing)))
    return have | set(missing)


def expeditor():
    os.chdir(FINREP)
    sys.path.insert(0, os.path.join(FINREP, "engine"))
    from odata_client import ODataClient  # noqa: PLC0415
    c = ODataClient()

    def num(n):
        s = str(n or "").strip()
        try:
            return str(int(s))
        except ValueError:
            return s
    return {num(x.get("Number")): x for x in c.list("Document_Сделка") if x.get("Posted")}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    deals = expeditor()
    rows = records()
    print("Угод у платформі: %d, в Експедиторі: %d" % (len(rows), len(deals)))

    ensure_options("Вид перевезення", set(MODE_BY_TYPE.values()), a.dry_run)
    load_opts = ensure_options("FCL/LCL", {"FCL", "LCL"}, a.dry_run)
    st_opts = ensure_options("Статус", set(STAGE_TO_STATUS.values()) | {DELIVERED}, a.dry_run)

    def num(n):
        s = str(n or "").strip()
        try:
            return str(int(s))
        except ValueError:
            return s

    F = lambda r, k: str(r.get(k) or "").strip()   # noqa: E731
    patches = {}
    skipped = collections.Counter()
    stats = collections.Counter()

    def put(rid, col, val):
        patches.setdefault(rid, {"Id": rid})[col] = val

    for r in rows:
        d = deals.get(num(F(r, "Угода")))
        if not d:
            skipped["немає в Експедиторі"] += 1
            continue
        tkey = str(d.get("ТипСделки_Key") or "")[:8]

        # --- вид перевезення
        mode = MODE_BY_TYPE.get(tkey)
        if not F(r, "Вид перевезення"):
            if mode:
                put(r["Id"], "Вид перевезення", mode)
                stats["вид: " + mode] += 1
            else:
                skipped["вид: %s" % UNMAPPED.get(tkey, tkey)] += 1

        # --- FCL / LCL (прапорець збірності — авторитетний)
        if load_opts is not None and not F(r, "FCL/LCL"):
            eff = F(r, "Вид перевезення") or mode or ""
            if d.get("СборныйГруз"):
                put(r["Id"], "FCL/LCL", "LCL"); stats["FCL/LCL: LCL"] += 1
            elif eff in SEA_MODES and F(r, "Контейнер"):
                put(r["Id"], "FCL/LCL", "FCL"); stats["FCL/LCL: FCL"] += 1
            elif eff in SEA_MODES:
                skipped["FCL/LCL: морська без номера контейнера"] += 1

        # --- статус
        cur_st = F(r, "Статус")
        if has_date(d.get(WORKS_DONE_FIELD)) and cur_st != DELIVERED:
            # роботи виконані → вантаж доставлено (переважає і етап, і вже поставлений статус)
            put(r["Id"], "Статус", DELIVERED)
            stats["статус: %s (є дата виконання робіт)" % DELIVERED] += 1
        elif not cur_st:
            tgt = STAGE_TO_STATUS.get(str(d.get("Статус") or "").strip())
            if tgt and (st_opts is None or tgt in st_opts):
                put(r["Id"], "Статус", tgt); stats["статус: " + tgt] += 1
            else:
                skipped["статус: етап «%s» не мапиться" % (str(d.get("Статус") or "—").strip())] += 1

    print("\nЗАПОВНЮЮ (%d угод):" % len(patches))
    for k, v in stats.most_common():
        print("   %-46s %d" % (k, v))
    print("\nНЕ ЗАПОВНЕНО (чекає рішення або даних):")
    for k, v in skipped.most_common():
        print("   %-46s %d" % (k, v))

    if a.dry_run:
        print("\nDRY_DONE нічого не записано")
        return

    body = list(patches.values())
    fails = 0
    for i in range(0, len(body), CHUNK):
        st, js = nc("PATCH", "/api/v2/tables/%s/records" % TABLE, body[i:i + CHUNK])
        if st not in (200, 201):
            for one in body[i:i + CHUNK]:          # порція впала — пробуємо поштучно
                st2, js2 = nc("PATCH", "/api/v2/tables/%s/records" % TABLE, [one])
                if st2 not in (200, 201):
                    fails += 1
                    print("FAIL Id=%s %s %s" % (one["Id"], st2, str(js2)[:150]))
    print("\nFILL_OK оновлено=%d fails=%d" % (len(body) - fails, fails))


if __name__ == "__main__":
    main()
