#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Одноразово: розширити таблицю «Задачі» під постановку задач у платформі.

НАВІЩО. Вимога користувачки 12.08.2026: «постановка задач по угодам, по клієнтам,
співпрацівникам та просто по діям з нагадуваннями та з можливістю додавати
виконавців». Сьогодні в таблиці є лише `Задача · Кому · Термін · Статус · Угода ·
Коментар`, тобто:
  — прив'язати задачу до клієнта або до співробітника нема куди;
  — виконавець рівно ОДИН і вибирається з двох вписаних імен (`Кому` = SingleSelect
    ['Ірина', 'Віталій']), а в довіднику `Користувачі` вже троє, і двоє з них Ірини;
  — нагадувати нема від чого: немає ні пріоритету, ні «за скільки днів попередити».

ЩО РОБИТЬ. Додає колонки (кожну — тільки якщо її ще немає) і додає бракуючі
варіанти в наявний `Статус`. НІЧОГО НЕ ВИДАЛЯЄ і не перейменовує.

  Тип           SingleSelect  Угода / Клієнт / Співробітник / Дія
  Клієнт        SingleLineText
  Співробітник  SingleLineText   — задача ПРО людину (оформити відпустку, навчання)
  Виконавці     SingleLineText   — email-и через кому
  Постановник   SingleLineText   — email того, хто поставив
  Пріоритет     SingleSelect  Терміново / Звичайно / Низько
  Нагадати за   Number           — за скільки днів до терміну підсвічувати
  Виконано      Date             — коли фактично закрито
  Статус        +Скасовано       — варіант додається до трьох наявних

ЧОМУ ВИКОНАВЦІ — ТЕКСТ З EMAIL-АМИ, А НЕ МНОЖИННИЙ ВИБІР. У множинного вибору
варіанти зашиті в колонку: додали людину в довідник — треба не забути дописати її
ще й сюди, інакше її неможливо призначити. Саме на це вже наступили з `Кому`
(Ірини Голобородько там немає). Email — незмінний ключ, а в довіднику `Користувачі`
двоє людей з ім'ям «Ірина», тож ім'я ключем бути не може. Фасад показує
«Ім'я Прізвище», у базі лежить email.

`Кому` НЕ ЧІПАЄМО. Колонка лишається на місці (правило: нічого не видаляти без
прямого підтвердження). Записів у таблиці 0, тож переносити з неї нічого.

Запуск: python3 /root/direct-sync/add_task_columns.py [--dry-run]
"""
import argparse
import json
import urllib.error
import urllib.request

NC = "http://localhost:8080"
TABLE = "mfo372vhs3fbbw7"          # «Задачі», база pbhr1qkpvx09z8m
TOK = open("/root/nocodb-token.txt").read().strip()

# (назва, назва_в_базі, тип, варіанти)
COLUMNS = [
    ("Тип", "task_kind", "SingleSelect", ["Угода", "Клієнт", "Співробітник", "Дія"]),
    ("Клієнт", "task_client", "SingleLineText", None),
    ("Співробітник", "task_person", "SingleLineText", None),
    ("Виконавці", "task_doers", "SingleLineText", None),
    ("Постановник", "task_author", "SingleLineText", None),
    ("Пріоритет", "task_prio", "SingleSelect", ["Терміново", "Звичайно", "Низько"]),
    ("Нагадати за", "task_remind", "Number", None),
    ("Виконано", "task_done_at", "Date", None),
]
NEW_STATUS = "Скасовано"


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
    except Exception as e:  # noqa: BLE001
        return 0, {"err": str(e)[:300]}


def meta():
    st, js = nc("GET", "/api/v2/meta/tables/%s" % TABLE)
    if st != 200:
        raise SystemExit("META_FAIL %s %s" % (st, js))
    return js


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    m = meta()
    have = {c["title"] for c in m["columns"]}
    print("колонок у таблиці зараз: %d" % len(m["columns"]))

    for title, cname, uidt, opts in COLUMNS:
        if title in have:
            print("   «%s» — вже є, пропускаю" % title)
            continue
        body = {"title": title, "column_name": cname, "uidt": uidt}
        if opts:
            body["colOptions"] = {"options": [{"title": o, "order": i + 1}
                                              for i, o in enumerate(opts)]}
        if a.dry_run:
            print("   DRY: створив би «%s» (%s%s)"
                  % (title, uidt, (" · " + " / ".join(opts)) if opts else ""))
            continue
        st, js = nc("POST", "/api/v2/meta/tables/%s/columns" % TABLE, body)
        if st not in (200, 201):
            raise SystemExit("не створилась колонка «%s»: %s %s" % (title, st, str(js)[:250]))
        print("   «%s» — створено (%s)" % (title, uidt))

    # ── варіант «Скасовано» в наявний «Статус» ────────────────────────────
    m = meta() if not a.dry_run else m
    col = next((c for c in m["columns"] if c["title"] == "Статус"), None)
    if not col:
        print("колонки «Статус» немає — варіант не додаю")
    else:
        opts = (col.get("colOptions") or {}).get("options", [])
        titles = [o["title"] for o in opts]
        if NEW_STATUS in titles:
            print("варіант «%s» у «Статус» уже є" % NEW_STATUS)
        elif a.dry_run:
            print("DRY: додав би «%s» до статусів (зараз: %s)" % (NEW_STATUS, ", ".join(titles)))
        else:
            # нічого не видаляємо — переносимо наявні варіанти як є і дописуємо новий
            keep = [{k: o[k] for k in ("id", "title", "color") if k in o} for o in opts]
            keep.append({"title": NEW_STATUS})
            for i, o in enumerate(keep):
                o["order"] = i + 1
            st, js = nc("PATCH", "/api/v2/meta/columns/%s" % col["id"],
                        {"title": "Статус", "uidt": "SingleSelect", "colOptions": {"options": keep}})
            if st not in (200, 201):
                raise SystemExit("не додався варіант: %s %s" % (st, str(js)[:250]))
            print("Статуси тепер: %s" % ", ".join(o["title"] for o in keep))

    if a.dry_run:
        print("DRY_DONE нічого не записано")
        return

    fin = meta()
    print("\nTASKCOLS_OK колонок стало: %d" % len(fin["columns"]))
    for c in fin["columns"]:
        if c["title"].startswith("nc_") or c["uidt"] in ("ID", "Order", "Deleted",
                                                         "CreatedTime", "LastModifiedTime",
                                                         "CreatedBy", "LastModifiedBy"):
            continue
        o = (c.get("colOptions") or {}).get("options") or []
        print("   %-16s %-14s %s" % (c["title"], c["uidt"],
                                     ", ".join(x["title"] for x in o)))


if __name__ == "__main__":
    main()
