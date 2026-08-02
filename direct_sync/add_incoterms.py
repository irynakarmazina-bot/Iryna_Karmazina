#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Одноразово: колонка «Умови поставки (Інкотермс)» у таблиці «Диспетчеризація».

Навіщо: від умов поставки залежить, де закінчується наша відповідальність.
У кабінеті клієнта на схемі експорту кроки «Імпортне митне оформлення» і
«Вантаж доставлено» показуються ЛИШЕ на умовах DAP/DDU (вказівка користувачки
02.08.2026) — без цього поля перевіряти нічого.

Список: чинні терміни Incoterms 2020 (EXW, FCA, FAS, FOB, CFR, CIF, CPT, CIP,
DAP, DPU, DDP) плюс DDU — його скасували в редакції 2010 року, але в договорах
він досі трапляється, і користувачка назвала його прямо.

Нічого не видаляє і не перезаписує: якщо колонка вже є — просто виходить.
Запуск: python3 /root/add_incoterms.py
"""
import json
import urllib.error
import urllib.request

NC = "http://localhost:8080"
TABLE = "m58xsjo6at01ohl"
TOK = open("/root/nocodb-token.txt").read().strip()
COL = "Умови поставки (Інкотермс)"
OPTIONS = ["EXW", "FCA", "FAS", "FOB", "CFR", "CIF", "CPT", "CIP",
           "DAP", "DPU", "DDP", "DDU"]


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
    st, js = nc("POST", "/api/v2/meta/tables/%s/columns" % TABLE, {
        "title": COL, "column_name": "incoterms", "uidt": "SingleSelect",
        "colOptions": {"options": [{"title": t, "order": i + 1}
                                   for i, t in enumerate(OPTIONS)]},
    })
    if st not in (200, 201):
        raise SystemExit("не створилась: %s %s" % (st, str(js)[:300]))

    st, meta = nc("GET", "/api/v2/meta/tables/%s" % TABLE)
    col = next((c for c in meta["columns"] if c["title"] == COL), None)
    if not col:
        raise SystemExit("створилась, але в мета-даних її немає")
    have = [o["title"] for o in (col.get("colOptions") or {}).get("options", [])]
    print("OK: колонка «%s» створена, варіантів %d: %s" % (COL, len(have), ", ".join(have)))


if __name__ == "__main__":
    main()
