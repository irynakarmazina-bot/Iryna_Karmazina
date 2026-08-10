#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Одноразово: перейменувати варіант «Прибув у порт» → «В порту призначення».

Рішення користувачки 10.08.2026: стара назва не казала, В ЯКОМУ порту вантаж,
і плуталась із «В порту відправлення».

ЩО ЦЕЙ СКРИПТ РОБИТЬ І ЧОГО НЕ РОБИТЬ:
  • нічого НЕ ВИДАЛЯЄ: ні варіантів, ні колонок, ні записів;
  • перед зміною зберігає ПОВНУ копію опису колонки у файл поруч;
  • перед зміною ПЕРЕРАХОВУЄ, скільки угод стоять на старому варіанті, і якщо
    таких більше нуля — ЗУПИНЯЄТЬСЯ і нічого не чіпає. Причина: у NocoDB значення
    SingleSelect лежить у рядку текстом, тому перейменування варіанта саме по собі
    записів НЕ виправляє — вони лишились би з назвою, якої вже немає в списку;
  • якщо новий варіант уже є — виходить, нічого не роблячи (можна запускати двічі).

Станом на 11.08.2026 старий варіант не стоїть у жодної з 277 угод — перевірено
читанням бази, тому перейменування безпечне.

Відкат: узяти файл копії і повернути назву назад тим самим способом.
Запуск: python3 /root/direct-sync/rename_status_option.py [--dry-run]
"""
import datetime
import json
import sys
import urllib.error
import urllib.parse
import urllib.request

NC = "http://127.0.0.1:8080"
TABLE = "m58xsjo6at01ohl"
TOKEN_FILE = "/root/nocodb-token.txt"
COL = "Статус"
OLD = "Прибув у порт"
NEW = "В порту призначення"
BAK = "/root/direct-sync/status_options.bak-%s.json"

TOK = open(TOKEN_FILE).read().strip()


def nc(method, path, data=None):
    body = json.dumps(data, ensure_ascii=False).encode() if data is not None else None
    req = urllib.request.Request(NC + path, data=body, method=method,
                                 headers={"Content-Type": "application/json", "xc-token": TOK})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            raw = r.read().decode()
            return r.status, (json.loads(raw) if raw else {})
    except urllib.error.HTTPError as e:
        return e.code, {"err": e.read().decode()[:400]}


def count_rows_with(value):
    """Скільки угод стоять на цьому варіанті. Рахуємо самі, не довіряючи фільтру."""
    n, offset = 0, 0
    while True:
        q = urllib.parse.urlencode({"limit": 1000, "offset": offset, "fields": "Id,Статус"})
        st, js = nc("GET", "/api/v2/tables/%s/records?%s" % (TABLE, q))
        if st != 200:
            raise SystemExit("не вдалося прочитати записи: HTTP %s %s" % (st, js))
        rows = js.get("list", [])
        n += sum(1 for r in rows if str(r.get("Статус") or "") == value)
        if (js.get("pageInfo") or {}).get("isLastPage", True):
            return n
        offset += 1000


def main():
    dry = "--dry-run" in sys.argv

    st, meta = nc("GET", "/api/v2/meta/tables/%s" % TABLE)
    if st != 200:
        raise SystemExit("не вдалося прочитати опис таблиці: HTTP %s %s" % (st, meta))
    col = next((c for c in meta.get("columns", []) if c.get("title") == COL), None)
    if not col:
        raise SystemExit("колонки «%s» немає" % COL)

    opts = (col.get("colOptions") or {}).get("options") or []
    titles = [o.get("title") for o in opts]
    print("варіантів зараз: %d" % len(titles))

    if NEW in titles:
        print("«%s» уже є — нічого не роблю" % NEW)
        return 0
    if OLD not in titles:
        raise SystemExit("«%s» у списку немає, і «%s» теж — зупиняюсь, щоб не гадати"
                         % (OLD, NEW))

    used = count_rows_with(OLD)
    print("угод на варіанті «%s»: %d" % (OLD, used))
    if used:
        raise SystemExit("ЗУПИНКА: %d угод стоять на старому варіанті. Перейменування "
                         "варіанта НЕ змінює значень у рядках — спершу треба вирішити, "
                         "що робити з цими угодами. Нічого не змінено." % used)

    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    path = BAK % stamp
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(col, fh, ensure_ascii=False, indent=2)
    print("копія опису колонки: %s" % path)

    # Міняємо ТІЛЬКИ title потрібного варіанта. id, колір і порядок лишаємо як є,
    # інакше NocoDB вважатиме це видаленням і додаванням нового варіанта.
    new_opts = []
    for o in opts:
        o2 = dict(o)
        if o2.get("title") == OLD:
            o2["title"] = NEW
        new_opts.append(o2)

    if dry:
        print("--dry-run: записувати не буду. Було б: %s" % [o.get("title") for o in new_opts])
        return 0

    st, res = nc("PATCH", "/api/v2/meta/columns/%s" % col["id"],
                 {"title": COL, "column_name": col.get("column_name"),
                  "uidt": col.get("uidt"), "colOptions": {"options": new_opts}})
    if st not in (200, 201):
        raise SystemExit("не вдалося змінити: HTTP %s %s" % (st, res))

    st, meta2 = nc("GET", "/api/v2/meta/tables/%s" % TABLE)
    col2 = next((c for c in meta2.get("columns", []) if c.get("title") == COL), None)
    t2 = [o.get("title") for o in ((col2.get("colOptions") or {}).get("options") or [])]
    print("варіантів після зміни: %d" % len(t2))
    if NEW in t2 and OLD not in t2 and len(t2) == len(titles):
        print("ГОТОВО: «%s» → «%s», кількість варіантів не змінилась" % (OLD, NEW))
        return 0
    print("УВАГА: перевірка не збіглася. Зараз: %s" % t2)
    return 1


if __name__ == "__main__":
    sys.exit(main())
