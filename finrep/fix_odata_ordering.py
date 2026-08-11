#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Сортування при посторінковому вивантаженні з 1С — інакше сторінки перекриваються.

ПРОБЛЕМА (знайдено 11.08.2026)
    `ODataClient.list()` ходив сторінками `$top=1000&$skip=N` БЕЗ `$orderby`.
    1С не гарантує сталий порядок записів між окремими запитами, тому вікна
    `$skip` перекривались: одні записи приходили по кілька разів, інші не
    приходили взагалі.

    Виміряно на живому довіднику контрагентів:
        без сортування:  3618 рядків, УНІКАЛЬНИХ 1881, дублів 1737 — Maersk A/S відсутній
        $orderby=Ref_Key: 3618 рядків, унікальних 3618, дублів 0 — Maersk A/S на місці

    Кількість рядків при цьому сходилась із `/$count` (3618), тому попередній
    рубіж захисту нічого не помічав. Назви губились мовчки.

    Видимий наслідок: рахунки 866, 896 і 935 (усі з контрагентом Maersk A/S)
    показувались у «Кредиторці» в групі з невизначеним контрагентом. Усього таких
    рахунків було 417 з 1043.

ЩО РОБИТЬ ЦЕЙ СКРИПТ
    1. Додає `$orderby=Ref_Key` за умовчанням, якщо порядок не заданий явно.
       Якщо об'єкт не має `Ref_Key` (регістри) і запит через це не проходить —
       автоматично повторює без сортування, а не падає.
    2. Прибирає дублі просто в `list()`: якщо запис із таким `Ref_Key` уже
       віддавали, другий раз не віддаємо. Тоді навіть при відкаті на несортований
       режим мапи «ключ → назва» не псуються.
    3. Звіряє кількість УНІКАЛЬНИХ записів з `/$count` (раніше звірялись рядки,
       а вони сходились навіть при дублях).

БЕЗПЕКА
    Нічого не видаляє. Перед правкою робить копію `odata_client.py.bak-<дата-час>`.
    `--check` лише показує стан.

ЗАПУСК
    python3 fix_odata_ordering.py --check
    python3 fix_odata_ordering.py
"""
import argparse
import datetime
import os
import shutil

TARGET = os.environ.get("ODATA_CLIENT", "/root/unitex-finrep/engine/odata_client.py")

OLD_ORDER = """        if order:
            parts.append("$orderby=" + quote(order))"""

NEW_ORDER = """        # Сортування ОБОВ'ЯЗКОВЕ. Без нього 1С не тримає сталий порядок між запитами,
        # і вікна $skip перекриваються: 11.08.2026 довідник контрагентів віддав
        # 3618 рядків, але лише 1881 УНІКАЛЬНИЙ — 1737 дублів, а частина записів
        # (серед них Maersk A/S) не прийшла жодного разу. Кількість рядків при цьому
        # сходилась із $count, тому обрив був невидимий.
        auto_order = not order
        parts.append("$orderby=" + quote(order or "Ref_Key"))"""

OLD_LOOP = """        while True:
            q = base_q + f"&$top={page}&$skip={skip}"
            data = self._get("/" + quote(entity) + "?" + q)
            rows = data.get("value", [])
            if not rows:
                break
            for r in rows:
                yield r
            got_total += len(rows)"""

NEW_LOOP = """        seen = set()
        dups = 0
        while True:
            q = base_q + f"&$top={page}&$skip={skip}"
            try:
                data = self._get("/" + quote(entity) + "?" + q)
            except Exception:
                # У об'єкта може не бути Ref_Key (регістри) — сортувати нема по чому.
                # Тоді працюємо як раніше, але дублі нижче все одно приберуться.
                if not auto_order:
                    raise
                auto_order = False
                parts_no_order = [p for p in parts if not p.startswith("$orderby=")]
                base_q = "&".join(parts_no_order)
                q = base_q + f"&$top={page}&$skip={skip}"
                data = self._get("/" + quote(entity) + "?" + q)
            rows = data.get("value", [])
            if not rows:
                break
            fresh = 0
            for r in rows:
                key = r.get("Ref_Key")
                if key is not None:
                    if key in seen:
                        dups += 1
                        continue
                    seen.add(key)
                fresh += 1
                yield r
            got_total += fresh"""

OLD_TAIL = """        if expected is not None and got_total < expected:
            raise RuntimeError(
                "OData віддав неповний список %s: зібрано %d, мало бути %d. "
                "Вивантаження обірвалось — розрахунок зупинено."
                % (entity, got_total, expected))"""

NEW_TAIL = """        if dups:
            print("  ⚠ %s: сторінки перекривались, прибрано %d повторів"
                  % (entity, dups), flush=True)
        if expected is not None and got_total < expected:
            raise RuntimeError(
                "OData віддав неповний список %s: зібрано %d, мало бути %d. "
                "Вивантаження обірвалось — розрахунок зупинено."
                % (entity, got_total, expected))"""

MARK = "Сортування ОБОВ'ЯЗКОВЕ"


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
        print("Запити йдуть без $orderby, сторінки можуть перекриватись.")
        return

    for old in (OLD_ORDER, OLD_LOOP, OLD_TAIL):
        if old not in src:
            raise SystemExit("Файл не такий, як очікувалось — правку НЕ застосовано.\n"
                             "Не знайдено фрагмент:\n%s" % old)

    out = src.replace(OLD_ORDER, NEW_ORDER).replace(OLD_LOOP, NEW_LOOP).replace(OLD_TAIL, NEW_TAIL)
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


if __name__ == "__main__":
    main()
