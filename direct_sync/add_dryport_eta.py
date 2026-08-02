#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Одноразово: колонка «ETA сухий порт».

Вимога користувачки 01.08.2026: для ЗАЛІЗНИЧНОГО ІМПОРТУ контейнер із порту
прибуття їде потягом на сухий порт (внутрішній термінал), і клієнту та
диспетчеру потрібна дата прибуття саме туди — вона не збігається ні з ETA
порту, ні з датою доставки отримувачу.

Текстова колонка «Сухий порт» (назва терміналу) в таблиці вже є — тут додаємо
саме ДАТУ. В Експедиторі такого реквізиту немає, у подіях Maersk теж (їхній
трекінг закінчується на порту вивантаження), тому поле веде людина.

Запуск: python3 /root/direct-sync/add_dryport_eta.py
"""
import json
import urllib.error
import urllib.request

NC = "http://localhost:8080"
TABLE = "m58xsjo6at01ohl"
TOK = open("/root/nocodb-token.txt").read().strip()
COL = "ETA сухий порт"


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
                {"title": COL, "column_name": "eta_dryport", "uidt": "Date",
                 "meta": {"date_format": "YYYY-MM-DD"}})
    if st not in (200, 201):
        raise SystemExit("не створилась колонка: %s %s" % (st, str(js)[:250]))
    print("Створено колонку «%s»" % COL)


if __name__ == "__main__":
    main()
