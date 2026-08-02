#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Одноразово: колонки для обліку переказів локальних витрат за кордон.

Вимога користувачки 02.08.2026: у таблиці «Бух. облік → Локальні витрати за кордоном»
треба бачити, по яких угодах переказ УЖЕ БУВ, щоб не переказати двічі.

Три колонки в таблиці «Диспетчеризація» (одна угода = один рядок, тому окрема
таблиця не потрібна):
  • «Переказ за кордон» — галочка, ставить бухгалтер;
  • «Дата переказу»     — коли переказали;
  • «Сума переказу»     — скільки саме переказали (за замовчуванням — розрахована
    різниця, але її можна виправити руками, якщо переказали інакше).

Сума зберігається окремо навмисно: розрахункова різниця змінюється, коли в угоду
додають нові рахунки, а фактично переказана сума мінятись не має.

Нічого не видаляє: наявні колонки не чіпає, повторний запуск безпечний.
Запуск: python3 /root/direct-sync/add_transfer_columns.py
"""
import json
import urllib.error
import urllib.request

NC = "http://localhost:8080"
TABLE = "m58xsjo6at01ohl"          # Диспетчеризація
TOK = open("/root/nocodb-token.txt").read().strip()

COLS = [
    {"title": "Переказ за кордон", "column_name": "transfer_done", "uidt": "Checkbox"},
    {"title": "Дата переказу", "column_name": "transfer_date", "uidt": "Date",
     "meta": {"date_format": "YYYY-MM-DD"}},
    {"title": "Сума переказу", "column_name": "transfer_amount", "uidt": "Decimal",
     "meta": {"precision": 2}},
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
    for col in COLS:
        if col["title"] in have:
            print("колонка «%s» уже є — пропускаю" % col["title"])
            continue
        st, js = nc("POST", "/api/v2/meta/tables/%s/columns" % TABLE, col)
        if st not in (200, 201):
            raise SystemExit("не створилась «%s»: %s %s" % (col["title"], st, str(js)[:250]))
        print("створено колонку «%s»" % col["title"])


if __name__ == "__main__":
    main()
