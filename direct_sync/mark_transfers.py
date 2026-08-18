#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Проставити позначку «Переказ за кордон» по списку вже сплачених локальних витрат.

Джерело — файл користувачки (перелік коносаментів із сумами), зведений у JSON:
[{"deal": "18", "bl": "260499493", "cont": "...", "amount": 540.0, "note": "..."}, ...]

Запобіжники:
  * пишемо ТІЛЬКИ в три поля: «Переказ за кордон», «Сума переказу», «Дата переказу»;
  * рядок беремо за номером угоди і додатково звіряємо коносамент — якщо він не збігся
    з тим, що в платформі, рядок ПРОПУСКАЄМО і пишемо про це;
  * попередні значення цих трьох полів зберігаємо у файл ДО запису;
  * --dry-run показує, що буде зроблено, і нічого не змінює.

Запуск:
    python3 mark_transfers.py --file paid_list.json --dry-run
    python3 mark_transfers.py --file paid_list.json [--date 2026-07-15]
"""
import argparse
import json
import os
import time
import urllib.request

NC = "http://localhost:8080"
TABLE = "m58xsjo6at01ohl"          # Диспетчеризація
TOK = open("/root/nocodb-token.txt").read().strip()
F_FLAG, F_DATE, F_SUM = "Переказ за кордон", "Дата переказу", "Сума переказу"


def nc(method, path, data=None):
    body = json.dumps(data, ensure_ascii=False).encode() if data is not None else None
    req = urllib.request.Request(NC + path, data=body, method=method,
                                 headers={"Content-Type": "application/json", "xc-token": TOK})
    with urllib.request.urlopen(req, timeout=120) as r:
        raw = r.read().decode()
        return json.loads(raw) if raw else {}


def all_rows():
    out, off = [], 0
    while True:
        js = nc("GET", "/api/v2/tables/%s/records?limit=200&offset=%d" % (TABLE, off))
        out += js.get("list", [])
        if len(js.get("list", [])) < 200:
            return out
        off += 200


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", required=True)
    ap.add_argument("--date", default="", help="дата переказу РРРР-ММ-ДД (типово не ставимо)")
    ap.add_argument("--only-local", action="store_true",
                    help="брати тільки рядки з приміткою про локальні витрати")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    paid = json.load(open(a.file, encoding="utf-8"))
    if a.only_local:
        paid = [p for p in paid if "локальн" in (p.get("note") or "").lower()]
    rows = {str(r.get("Угода") or "").strip(): r for r in all_rows()}

    todo, skip, backup = [], [], []
    for p in paid:
        r = rows.get(str(p["deal"]).strip())
        if not r:
            skip.append((p, "немає рядка в таблиці диспетчеризації"))
            continue
        bl_platform = str(r.get("BL") or "").strip()
        if p.get("bl") and bl_platform and p["bl"] != bl_platform:
            skip.append((p, "коносамент не збігся: у файлі %s, у платформі %s" % (p["bl"], bl_platform)))
            continue
        todo.append((p, r))
        backup.append({"Id": r["Id"], "Угода": r.get("Угода"), F_FLAG: r.get(F_FLAG),
                       F_DATE: r.get(F_DATE), F_SUM: r.get(F_SUM)})

    print("буде позначено: %d · пропущено: %d" % (len(todo), len(skip)))
    for p, r in todo:
        print("   угода %-5s Id=%-4s сума %8.2f %s" %
              (p["deal"], r["Id"], p["amount"],
               "(було вже позначено)" if r.get(F_FLAG) else ""))
    for p, why in skip:
        print("   ПРОПУЩЕНО угода %-5s — %s" % (p["deal"], why))
    if a.dry_run:
        print("\n--dry-run: нічого не змінено")
        return

    bak = "/root/direct-sync/transfers_backup_%s.json" % time.strftime("%Y%m%d-%H%M%S")
    with open(bak, "w", encoding="utf-8") as fh:
        json.dump(backup, fh, ensure_ascii=False, indent=1)
    os.chmod(bak, 0o600)
    print("\nпопередні значення збережено:", bak)

    payload = []
    for p, r in todo:
        rec = {"Id": r["Id"], F_FLAG: True, F_SUM: round(float(p["amount"]), 2)}
        if a.date:
            rec[F_DATE] = a.date
        payload.append(rec)
    for i in range(0, len(payload), 25):
        nc("PATCH", "/api/v2/tables/%s/records" % TABLE, payload[i:i + 25])
    print("позначено рядків:", len(payload))

    fresh = {str(r.get("Угода") or "").strip(): r for r in all_rows()}
    bad = [p["deal"] for p, _ in todo if not fresh.get(p["deal"], {}).get(F_FLAG)]
    print("перевірка після запису:", "усі позначки на місці" if not bad else "НЕ записалось: %s" % bad)


if __name__ == "__main__":
    main()
