#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Одноразово: колонка «Прізвище» в таблиці «Користувачі».

Вимога користувачки 01.08.2026: користувачів показувати як Імʼя та Прізвище.
Окрема колонка, а не склеювання в «Імʼя», бо поле «Імʼя» використовується для
звірки з полем «Менеджер» в угодах — якщо туди дописати прізвище, зріз
«лише мої угоди» перестане працювати.
"""
import json
import urllib.error
import urllib.request

NC = "http://localhost:8080"
TOK = open("/root/nocodb-token.txt").read().strip()
COL = "Прізвище"


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
    st, bases = nc("GET", "/api/v2/meta/bases")
    tid = None
    for b in bases.get("list", []):
        st, ts = nc("GET", "/api/v2/meta/bases/%s/tables" % b["id"])
        for t in ts.get("list", []):
            if t["title"] == "Користувачі":
                tid = t["id"]
        if tid:
            break
    if not tid:
        raise SystemExit("не знайшов таблицю «Користувачі»")
    st, meta = nc("GET", "/api/v2/meta/tables/%s" % tid)
    if any(c["title"] == COL for c in meta["columns"]):
        print("колонка «%s» уже є" % COL)
        return
    st, js = nc("POST", "/api/v2/meta/tables/%s/columns" % tid,
                {"title": COL, "column_name": "surname", "uidt": "SingleLineText"})
    if st not in (200, 201):
        raise SystemExit("не створилась колонка: %s %s" % (st, str(js)[:250]))
    print("Створено колонку «%s» у таблиці «Користувачі» (id %s)" % (COL, tid))


if __name__ == "__main__":
    main()
