#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Одноразово: колонки структурованого маршруту — POL, POD, FD, «Митне оформлення».

Вимога користувачки 03.08.2026: «треба брати дані не з поля Маршрут, а з полей
POL, POD, FD. Ще додамо пізніше DR — dry port в Експедитор. Також є поле Митне
оформлення — це назва митного переходу, має бути вказана в угоді в ЕРП».

Що перевірено в Експедиторі 04.08.2026 (268 проведених угод):
    ПОЛ_Key                      заповнено 257, 34 різних міста
    ПОД_Key                      заповнено 260, 15 різних міст
    ФД_Key                       заповнено  39,  9 різних міст
    ПунктПересеченияГраницы_Key  заповнено   2 (Рава-Руська, Угринів)
Усі коди розшифровуються довідником `Catalog_Города` (130 записів) — 100%,
жодного нерозпізнаного. Свій довідник міст робити не треба.
Довідник `Catalog_ТаможенныеПосты` порожній, тому митний перехід теж читається
з `Catalog_Города` (там є ознака `ПунктПерехода`).

Колонка «Сухий порт» у платформі вже є — DR писатимемо в неї, щойно реквізит
з'явиться в Експедиторі (див. DRY_KEYS в expeditor_direct_sync.py).

Запуск: python3 /root/direct-sync/add_route_columns.py
"""
import json
import urllib.error
import urllib.request

NC = "http://localhost:8080"
TABLE = "m58xsjo6at01ohl"          # Диспетчеризація
TOK = open("/root/nocodb-token.txt").read().strip()

COLS = [
    ("POL", "pol_city", "SingleLineText"),
    ("POD", "pod_city", "SingleLineText"),
    ("FD", "fd_city", "SingleLineText"),
    ("Митне оформлення", "customs_point", "SingleLineText"),
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
    st, meta = nc("GET", "/api/v2/meta/tables/%s" % TABLE)
    if st != 200:
        raise SystemExit("META_FAIL %s %s" % (st, meta))
    have = {c["title"] for c in meta["columns"]}
    for title, name, uidt in COLS:
        if title in have:
            print("колонка «%s» уже є — пропускаю" % title)
            continue
        st, js = nc("POST", "/api/v2/meta/tables/%s/columns" % TABLE,
                    {"title": title, "column_name": name, "uidt": uidt})
        if st not in (200, 201):
            raise SystemExit("не створилась «%s»: %s %s" % (title, st, str(js)[:250]))
        print("Створено колонку «%s»" % title)
    print("ROUTE_COLS_OK")


if __name__ == "__main__":
    main()
