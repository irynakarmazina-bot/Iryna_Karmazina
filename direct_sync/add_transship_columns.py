#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Одноразово: колонки порту перевалки — «Порт перевалки», «Перевалка (прибуття)»,
«Перевалка (відправлення)».

Вимога користувачки 01.08.2026: у схемі руху для морських перевезень має бути видно
порт перевалки, де він є. В Експедиторі такого реквізиту немає, у полі «Маршрут» —
теж (там відправлення → порт призначення → місто доставки).

Дані беремо з подій Maersk: перевалка — це кожне вивантаження з судна (DISC), після
якого йде нове завантаження (LOAD). Приклад, угода 186:
    LOAD 28.04 Felixstowe → DISC 05.05 Bremerhaven → LOAD 06.05 Bremerhaven → DISC 13.05 Gdansk
тобто порт перевалки = Bremerhaven, прибуття 05.05, відправлення 06.05.
Ці дві дати важливі: в угоді 106 контейнер простояв у перевалці 24 дні (02.03 → 26.03).

Запуск: python3 /root/direct-sync/add_transship_columns.py
"""
import json
import urllib.error
import urllib.request

NC = "http://localhost:8080"
TABLE = "m58xsjo6at01ohl"
TOK = open("/root/nocodb-token.txt").read().strip()

COLS = [
    ("Порт перевалки", "port_perevalky", "SingleLineText"),
    ("Перевалка (прибуття)", "perevalka_arr", "Date"),
    ("Перевалка (відправлення)", "perevalka_dep", "Date"),
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
        body = {"title": title, "column_name": name, "uidt": uidt}
        if uidt == "Date":
            body["meta"] = {"date_format": "YYYY-MM-DD"}
        st, js = nc("POST", "/api/v2/meta/tables/%s/columns" % TABLE, body)
        if st not in (200, 201):
            raise SystemExit("не створилась «%s»: %s %s" % (title, st, str(js)[:250]))
        print("Створено колонку «%s»" % title)


if __name__ == "__main__":
    main()
