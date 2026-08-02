#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Одноразово: колонка «HBL» — номер домашнього коносамента.

Вимога користувачки 01.08.2026. Поле «BL» — це ЛІНІЙНИЙ коносамент, він приходить
з Експедитора і з трекінгу Maersk. Домашній коносамент компанія випускає сама,
в Експедиторі його немає (реквізит `КоносаментТип` порожній у всіх 266 угодах),
тому це поле веде людина в платформі, а синхронізація його не чіпає.

У кабінеті клієнта показуємо HBL, а якщо він порожній — лінійний BL.

Запуск: python3 /root/direct-sync/add_hbl_column.py
"""
import json
import urllib.error
import urllib.request

NC = "http://localhost:8080"
TABLE = "m58xsjo6at01ohl"
TOK = open("/root/nocodb-token.txt").read().strip()
COL = "HBL"


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
                {"title": COL, "column_name": "hbl", "uidt": "SingleLineText"})
    if st not in (200, 201):
        raise SystemExit("не створилась колонка: %s %s" % (st, str(js)[:250]))
    print("Створено колонку «%s» (домашній коносамент)" % COL)


if __name__ == "__main__":
    main()
