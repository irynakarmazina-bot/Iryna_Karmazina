#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Перевірка правила «коли автомат має право перебити ручний статус».

Правило (рішення користувачки 16.08.2026, варіант «А»): ручний статус тримається,
доки Maersk не повідомить ФАКТ, датований ПІЗНІШЕ за день ручної правки.
Живий випадок: угода 260 — 13.08 людина поставила «В порту відправлення»,
14.08 судно вийшло (ETD факт), а статус лишався старим, бо автомат мовчав завжди.

Запуск: python3 scripts/status_rule.py     (0 = всі пройшли, 1 = є падіння)
"""
import importlib.util
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "..", "direct_sync", "maersk_track_sync.py")
spec = importlib.util.spec_from_file_location("maersk_track_sync", SRC)
mt = importlib.util.module_from_spec(spec)
sys.modules["maersk_track_sync"] = mt
spec.loader.exec_module(mt)

CASES = [
    ("факт 14.08 новіший за ручний 13.08 → автомат оновлює",
     {"Статус (оновлено)": "2026-08-13"}, "2026-08-14T09:00:00", True),
    ("той самий день → перевага людині",
     {"Статус (оновлено)": "2026-08-14"}, "2026-08-14T23:00:00", False),
    ("факт старіший за ручний → людина",
     {"Статус (оновлено)": "2026-08-15"}, "2026-08-14T09:00:00", False),
    ("немає дати ручної правки → не перебиваємо",
     {"Статус (оновлено)": ""}, "2026-08-14T09:00:00", False),
    ("немає факту від Maersk → не перебиваємо",
     {"Статус (оновлено)": "2026-08-13"}, "", False),
    ("дата з часом у колонці теж читається",
     {"Статус (оновлено)": "2026-08-13T00:00:00"}, "2026-08-14T00:00:00", True),
]


def main():
    bad = 0
    for name, row, last, want in CASES:
        got = mt._fact_newer_than_human(row, last)
        ok = got is want
        bad += 0 if ok else 1
        print("  %s %-52s → %s" % ("✓" if ok else "✗", name, got))
    print("STATUS_RULE_OK — усі %d перевірок пройшли" % len(CASES) if not bad
          else "STATUS_RULE_FAIL — падінь: %d" % bad)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
