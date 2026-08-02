#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Одноразово: колонка «Здача в порт (факт)».

Вимога користувачки 01.08.2026: фактична дата здачі контейнера в порт, до якої
буде прив'язаний розрахунок демереджу й зберігання. Стоїть поруч із «Гейт ін»
(в таблиці — другим рядком у тій самій колонці).

Різниця між полями:
  «Гейт ін»              — заїзд у порт; для імпорту приходить із Maersk (подія GTIN);
  «Здача в порт (факт)»  — фактична передача контейнера терміналу, ведеться вручну;
                           саме від неї рахуємо вільний час, демередж і зберігання.

Запуск: python3 /root/direct-sync/add_port_handover.py
"""
import json
import urllib.error
import urllib.request

NC = "http://localhost:8080"
TABLE = "m58xsjo6at01ohl"
TOK = open("/root/nocodb-token.txt").read().strip()
COL = "Здача в порт (факт)"


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
                {"title": COL, "column_name": "port_handover", "uidt": "Date",
                 "meta": {"date_format": "YYYY-MM-DD"}})
    if st not in (200, 201):
        raise SystemExit("не створилась колонка: %s %s" % (st, str(js)[:250]))
    print("Створено колонку «%s»" % COL)


if __name__ == "__main__":
    main()
