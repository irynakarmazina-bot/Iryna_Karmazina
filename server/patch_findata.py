#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Додає нові звіти у білий список /finrep-data (findata.py на сервері).

Чому окремим файлом: багаторядковий код у relay-команді ламає JSON черги
(перевірено 02.08.2026 — черга стояла для всіх сесій).

Ідемпотентно: наявні ключі не чіпає, нічого не видаляє. Резервну копію робить
викликаюча команда (findata.py.bak-*).
"""
import re

P = "/root/findata.py"
NEW = {                       # ключ у /finrep-data?name=… : файл у computed/
    "maersk_payments": "maersk_payments.json",
    "single_tax": "single_tax.json",
}
ANCHOR = r'("localcosts":\s*"local_costs\.json",)'

s = open(P, encoding="utf-8").read()
add = [(k, v) for k, v in NEW.items() if '"%s"' % k not in s]
if not add:
    print("усі ключі вже є — не чіпаю")
else:
    ins = "".join('\n    "%s": "%s",' % (k, v) for k, v in add)
    s2, n = re.subn(ANCHOR, lambda m: m.group(1) + ins, s, count=1)
    if not n:
        print("НЕ ЗНАЙШЛА рядок localcosts — нічого не змінено")
    else:
        open(P, "w", encoding="utf-8").write(s2)
        print("додано:", ", ".join(k for k, _ in add))
