#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Одноразово: створити колонку «Етап (Експедитор)» і заповнити її з Експедитора.

Навіщо: платформа мала лише транспортний «Статус» (з трекінгу), а комерційний етап
Експедитора («Букинг» / «Выполняется» / «ВыставленСчет» / «Завершена») ніде не був видний.
Він потрібен логіці алертів — користувачка 31.07.2026: «ВыставленСчет» виставляють,
як правило, вже ПІСЛЯ завантаження на авто, тож така угода не є простоєм у порту,
навіть якщо номер авто в Експедитор не внесли (угоди 120 і 173 — саме цей випадок).

Нічого не видаляє. Колонку створює лише якщо її немає. Далі її веде
expeditor_direct_sync.py (колонка авторитетна з Експедитора).

Запуск: python3 /root/direct-sync/add_stage_column.py [--dry-run]
"""
import argparse
import collections
import json
import os
import sys
import urllib.error
import urllib.request

NC = "http://localhost:8080"
TABLE = "m58xsjo6at01ohl"
TOK = open("/root/nocodb-token.txt").read().strip()
COL = "Етап (Експедитор)"
CHUNK = 25
FINREP = "/root/unitex-finrep"


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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    st, meta = nc("GET", "/api/v2/meta/tables/%s" % TABLE)
    if st != 200:
        raise SystemExit("META_FAIL %s %s" % (st, meta))
    exists = any(c["title"] == COL for c in meta["columns"])
    print("колонка «%s»: %s" % (COL, "вже є" if exists else "немає"))
    if not exists:
        if a.dry_run:
            print("DRY: створив би колонку «%s» (текст)" % COL)
        else:
            st, js = nc("POST", "/api/v2/meta/tables/%s/columns" % TABLE,
                        {"title": COL, "column_name": "expeditor_stage", "uidt": "SingleLineText"})
            if st not in (200, 201):
                raise SystemExit("не створилась колонка: %s %s" % (st, str(js)[:250]))
            print("Колонку створено")

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

    deals = {num(x.get("Number")): str(x.get("Статус") or "").strip()
             for x in c.list("Document_Сделка") if x.get("Posted")}

    rows, off = [], 0
    while True:
        st, js = nc("GET", "/api/v2/tables/%s/records?limit=200&offset=%d" % (TABLE, off))
        if st != 200:
            raise SystemExit("READ_FAIL %s %s" % (st, js))
        rows += js.get("list", [])
        if js.get("pageInfo", {}).get("isLastPage"):
            break
        off += 200

    patches, miss = [], []
    for r in rows:
        n = num(str(r.get("Угода") or "").strip())
        stage = deals.get(n)
        if not stage:
            miss.append(n)
            continue
        if str(r.get(COL) or "").strip() != stage:
            patches.append({"Id": r["Id"], COL: stage})

    print("Заповнити: %d угод" % len(patches))
    for k, v in collections.Counter(p[COL] for p in patches).most_common():
        print("   %-18s %d" % (k, v))
    if miss:
        print("немає в Експедиторі: %s" % ", ".join(miss))
    if a.dry_run:
        print("DRY_DONE нічого не записано")
        return

    fails = 0
    for i in range(0, len(patches), CHUNK):
        st, js = nc("PATCH", "/api/v2/tables/%s/records" % TABLE, patches[i:i + CHUNK])
        if st not in (200, 201):
            fails += 1
            print("UPDATE_FAIL %s %s" % (st, str(js)[:200]))
    print("STAGE_OK оновлено=%d fails=%d" % (len(patches), fails))


if __name__ == "__main__":
    main()
