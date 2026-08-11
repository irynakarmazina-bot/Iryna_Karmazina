#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Виправлення тихого обриву вивантаження в engine/odata_client.py.

ПРОБЛЕМА (знайдено 11.08.2026)
    У `ODataClient.list()` пагінація зупинялась так:

        if len(rows) < page:
            break        # «коротка сторінка = дані скінчились»

    Але 1С іноді віддає коротку сторінку ПОСЕРЕДИНІ вивантаження. Тоді клієнт
    тихо повертав частину даних і жодного попередження не було.

    Спіймано на живому: `c.list("Catalog_Контрагенты", select=["Ref_Key","Description"])`
    повернув **1881 контрагента замість 3618** (сторінка 881 замість 1000). У ту
    загублену половину потрапив `Maersk A/S`. Через це рахунки 866, 896 і 935
    (усі з контрагентом Maersk A/S) отримали порожню назву постачальника і
    показались у «Кредиторці» в групі з невизначеним контрагентом.

    Обрив ВИПАДКОВИЙ: за годину той самий виклик віддав повні 3618. Саме тому
    його ніхто не ловив — раз на раз не приходиться.

    Ризик ширший за назви: `c.list` тягне і ДОКУМЕНТИ (рахунки постачальників,
    надходження, угоди). Обрив там означає, що документи просто зникають зі звіту,
    і цифри тихо меншають — без жодної ознаки помилки.

ЩО РОБИТЬ ЦЕЙ СКРИПТ
    1. Прибирає зупинку на короткій сторінці — єдина надійна ознака кінця це
       ПОРОЖНЯ сторінка (вона вже перевіряється вище по коду).
    2. Додає другий рубіж: звіряє зібрану кількість з еталоном `/$count` і падає
       з голосною помилкою, якщо зібрано менше. Краще гучна зупинка, ніж мовчазні
       неправильні цифри. Звірка вмикається лише коли тягнемо об'єкт ЦІЛКОМ —
       з `$filter` або `$top` очікувана кількість інша. Якщо `/$count` недоступний,
       поведінка така сама, як була.

БЕЗПЕКА
    Нічого не видаляє. Перед правкою робить копію
    `odata_client.py.bak-<дата-час>`. `--check` лише показує, чи вже виправлено.

ЗАПУСК
    python3 fix_odata_pagination.py --check    # подивитись стан
    python3 fix_odata_pagination.py            # застосувати
"""
import argparse
import datetime
import os
import shutil
import sys

TARGET = os.environ.get("ODATA_CLIENT",
                        "/root/unitex-finrep/engine/odata_client.py")

OLD_BREAK = """            got_total += len(rows)
            if top and got_total >= top:
                break
            if len(rows) < page:
                break
            skip += page"""

NEW_BREAK = """            got_total += len(rows)
            if top and got_total >= top:
                break
            # НЕ зупинятись на короткій сторінці. 1С іноді віддає менше, ніж просили,
            # ПОСЕРЕДИНІ вивантаження (11.08.2026: довідник контрагентів обірвався на
            # 1881 з 3618 — сторінка 881 замість 1000). Стара умова `len(rows) < page`
            # вважала це кінцем даних і тихо повертала половину: Maersk A/S не потрапив
            # у мапу назв, і рахунки 866/896/935 показались як «невизначений контрагент».
            # Єдина надійна ознака кінця — ПОРОЖНЯ сторінка (перевіряється вище).
            skip += page"""

OLD_HEAD = """        base_q = "&".join(parts)
        skip = 0
        got_total = 0"""

NEW_HEAD = """        base_q = "&".join(parts)
        skip = 0
        got_total = 0
        # Еталон кількості: /$count. Беремо ТІЛЬКИ коли тягнемо об'єкт цілком —
        # з $filter або $top очікувана кількість інша. Недоступний — працюємо як раніше.
        expected = None
        if not filter and not top:
            try:
                import urllib.request as _u
                _r = _u.Request(self.url + "/" + quote(entity) + "/$count")
                _r.add_header("Authorization", self._auth)
                with _u.urlopen(_r, timeout=120, context=self._ctx) as _x:
                    expected = int(_x.read().decode().strip().strip('"'))
            except Exception:
                expected = None"""

OLD_TAIL = """            skip += page

    def first(self, entity, **kw):"""

NEW_TAIL = """            skip += page

        if expected is not None and got_total < expected:
            raise RuntimeError(
                "OData віддав неповний список %s: %d з %d. Це не «даних менше» — це обрив "
                "вивантаження. Далі рахувати НЕ можна: назви загубляться, а документи "
                "просто зникнуть зі звіту." % (entity, got_total, expected))

    def first(self, entity, **kw):"""

MARK = "Єдина надійна ознака кінця — ПОРОЖНЯ сторінка"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="лише показати стан")
    a = ap.parse_args()

    if not os.path.exists(TARGET):
        raise SystemExit("НЕ ЗНАЙДЕНО %s" % TARGET)
    src = open(TARGET, encoding="utf-8").read()

    if MARK in src:
        print("Вже виправлено — %s" % TARGET)
        return
    if a.check:
        print("НЕ виправлено — %s" % TARGET)
        print("Обрив на короткій сторінці на місці. Запусти без --check, щоб застосувати.")
        return

    for old in (OLD_BREAK, OLD_HEAD, OLD_TAIL):
        if old not in src:
            raise SystemExit("Файл не такий, як очікувалось — правку НЕ застосовано.\n"
                             "Не знайдено фрагмент:\n%s" % old)

    out = src.replace(OLD_HEAD, NEW_HEAD).replace(OLD_BREAK, NEW_BREAK).replace(OLD_TAIL, NEW_TAIL)
    bak = TARGET + ".bak-" + datetime.datetime.now().strftime("%Y%m%d-%H%M")
    shutil.copy2(TARGET, bak)
    tmp = TARGET + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(out)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, TARGET)
    print("Копія попереднього файлу: %s" % bak)
    print("Виправлено: %s" % TARGET)
    print("Перевір: python3 -c \"import sys;sys.path.insert(0,'/root/unitex-finrep/engine');"
          "import odata_client;c=odata_client.ODataClient();"
          "print(sum(1 for _ in c.list('Catalog_Контрагенты',select=['Ref_Key','Description'])))\"")


if __name__ == "__main__":
    main()
