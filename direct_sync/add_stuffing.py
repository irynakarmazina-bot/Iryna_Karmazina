#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Одноразово: колонка «Stuffing» — дата стафіровки контейнера.

Вимога користувачки 01.08.2026: у ланцюжку йде ПЕРЕД «Gate in» (заїзд у порт).
Назва англійською — на її прохання.

Чому нова колонка, а не наявні «Постановка/завантаження (план)/(факт)»:
перевірка 01.08.2026 показала, що обидві порожні в УСІХ 267 угодах, тобто
ними ніколи не користувалися; змішувати нове поле зі старим невикористаним
не стали, щоб не плутати. Старі поля НЕ чіпаємо і не видаляємо.

В Експедиторі дати стафіровки немає, трекінг ліній її теж не дає — веде людина.

Запуск: python3 /root/direct-sync/add_stuffing.py
"""
import json
import urllib.error
import urllib.request

NC = "http://localhost:8080"
TABLE = "m58xsjo6at01ohl"
TOK = open("/root/nocodb-token.txt").read().strip()
COL = "Stuffing"


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
    if any(c["title"] == COL for c in meta["columns"]):
        print("колонка «%s» уже є — нічого не роблю" % COL)
        return
    st, js = nc("POST", "/api/v2/meta/tables/%s/columns" % TABLE,
                {"title": COL, "column_name": "stuffing", "uidt": "Date",
                 "meta": {"date_format": "YYYY-MM-DD"}})
    if st not in (200, 201):
        raise SystemExit("не створилась колонка: %s %s" % (st, str(js)[:250]))
    print("Створено колонку «%s»" % COL)


if __name__ == "__main__":
    main()
