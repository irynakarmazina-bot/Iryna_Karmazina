#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Разово: перекласти дату з «ETA» в «ETD (план)» в АКТИВНИХ експортних угодах.

НАВІЩО. Скарга користувачки 13.08.2026 на угоди 280 і 281: «21.09 це ЕТД, а не
ЕТА. Знайди помилку та виправи». В Експедиторі поле дати ОДНЕ — «ЕТА», і для
експорту в нього вносять ВІДХІД з порту завантаження. Синхронізація
(expeditor_direct_sync.py) клала його в колонку «ETA» незалежно від напрямку,
тобто дата відходу записувалась як дата прибуття. Саму причину виправлено в
map_deal(); цей скрипт прибирає наслідки в уже записаних рядках.

ЧОМУ ЦЕ ВИДНО В ДАНИХ, а не лише зі слів:
  * угода 259 — в Експедиторі ЕТА = ЕТА_ПОЛ = 2026-08-11, та сама дата в обох
    полях: для експорту «ЕТА» і є дата POL;
  * угода 69 — у платформі ETA = ETD (факт) = 2026-02-12: трекінг лінії поставив
    відхід рівно туди, де в нас стояло «прибуття»;
  * угоди 280/281 — трекінгу ще немає, тому видно чистий наслідок: 21.09 у
    колонці «ETA», а «ETD (план)» порожній.

🚫 ЗАКРИТЕ НЕ ЧІПАЄМО. Угоди зі статусом «Вантаж доставлено» і «Скасована»
пропускаються завжди, навіть якщо в них та сама помилка. Це правило користувачки
(CLAUDE.md, п. 11): закрита угода вже потрапила в облік і звіти, і виправляти в
ній щось «щоб було красиво» — небезпечніше, ніж лишити як є. Таких угод у базі
станом на 13.08.2026 сім (46, 69, 70, 104, 117, 146, 225) — вони лишаються.

ЩО САМЕ МІНЯЄТЬСЯ, і тільки за виконання ВСІХ умов одночасно:
  напрямок = Експорт · статус НЕ закритий · «ETA» заповнена · «ETD (план)»
  порожня · значення «ETA» ЗБІГАЄТЬСЯ з полем «ЕТА» тієї ж угоди в Експедиторі
Остання умова головна: вона доводить, що дату поставила саме синхронізація цією
помилкою, а не людина чи трекінг. Не збігається — не чіпаємо і кажемо про це.

Дію: «ETD (план)» ← значення «ETA»; «ETA» очищається (справжнього прибуття ми
не знаємо — його дасть трекінг лінії, коли з'явиться коносамент).

Запуск: python3 /root/direct-sync/fix_export_eta.py [--dry-run]
        (без --dry-run ЗАПИСУЄ; спершу завжди прогнати з --dry-run)
"""
import argparse
import json
import os
import sys
import urllib.error
import urllib.request

NC = "http://localhost:8080"
TABLE = "m58xsjo6at01ohl"          # «Диспетчеризація»
TOK = open("/root/nocodb-token.txt").read().strip()
FINREP = "/root/unitex-finrep"
CLOSED = {"Вантаж доставлено", "Скасована"}
EMPTY_DATE = "0001-01-01T00:00:00"


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


def d10(v):
    s = str(v or "").strip()
    if not s or s.startswith("0001-01-01"):
        return ""
    return s[:10]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    rows, off = [], 0
    while True:
        st, js = nc("GET", "/api/v2/tables/%s/records?limit=200&offset=%d" % (TABLE, off))
        if st != 200:
            raise SystemExit("READ_FAIL %s %s" % (st, js))
        rows += js.get("list", [])
        if len(js.get("list", [])) < 200:
            break
        off += 200
    print("угод у платформі: %d" % len(rows))

    # Дати з Експедитора — щоб звірити, чи це справді наш запис
    os.chdir(FINREP)
    sys.path.insert(0, os.path.join(FINREP, "engine"))
    from odata_client import ODataClient  # noqa: PLC0415

    def num(n):
        s = str(n or "").strip()
        try:
            return str(int(s))
        except ValueError:
            return s

    exp_eta = {num(d.get("Number")): d10(d.get("ЕТА")) for d in ODataClient().list("Document_Сделка")}
    print("угод в Експедиторі: %d" % len(exp_eta))

    patches, skipped = [], []
    for r in rows:
        if str(r.get("Напрямок") or "").strip() != "Експорт":
            continue
        n = num(r.get("Угода"))
        status = str(r.get("Статус") or "").strip()
        eta, etd = d10(r.get("ETA")), d10(r.get("ETD (план)"))
        if status in CLOSED:
            if eta and not etd:
                skipped.append((n, status, eta, "закрита — не чіпаю (правило 11)"))
            continue
        if not eta:
            continue
        if etd:
            skipped.append((n, status, eta, "ETD (план) уже заповнений — не чіпаю"))
            continue
        src = exp_eta.get(n, "")
        if src != eta:
            skipped.append((n, status, eta, "в Експедиторі ЕТА=%s — значення не наше" % (src or "порожньо")))
            continue
        patches.append({"Id": r["Id"], "ETD (план)": eta, "ETA": None, "_n": n, "_st": status})

    print("\nПЕРЕНЕСТИ ETA → ETD (план): %d угод" % len(patches))
    for p in patches:
        print("   угода %-5s [%s]  ETA %s → ETD (план) %s, ETA очищається"
              % (p["_n"], p["_st"], p["ETD (план)"], p["ETD (план)"]))
    if skipped:
        print("\nПРОПУЩЕНО: %d" % len(skipped))
        for n, st, eta, why in skipped:
            print("   угода %-5s [%-18s] ETA %s — %s" % (n, st[:18], eta, why))

    if a.dry_run:
        print("\nDRY_DONE нічого не записано")
        return
    if not patches:
        print("\nFIXETA_OK міняти нічого")
        return

    body = [{k: v for k, v in p.items() if not k.startswith("_")} for p in patches]
    st, js = nc("PATCH", "/api/v2/tables/%s/records" % TABLE, body)
    if st not in (200, 201):
        raise SystemExit("UPDATE_FAIL %s %s" % (st, str(js)[:250]))
    print("\nFIXETA_OK оновлено %d угод" % len(patches))


if __name__ == "__main__":
    main()
