#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Додає журнал конвеєра у білий список /finrep-data (findata.py на сервері).

НАВІЩО
    Журнал дій конвеєра (`logs/actions.jsonl` → `computed/pipeline.json`) має бути
    видним у платформі адміністраторам і фінансовим ролям. Показувати його треба
    тим самим захищеним шляхом, яким уже йдуть фінансові дані: `/finrep-data`
    перевіряє роль (Адміністратор / Фінансист / Бухгалтер) — нової дірки не з'являється.

Окремим файлом, а не рядком у relay-команді: багаторядковий код у команді ламає
JSON черги (перевірено 02.08.2026 — черга стояла для всіх сесій).

Ідемпотентно: наявний ключ не чіпає, нічого не видаляє. Робить копію findata.py.bak-*.
"""
import datetime
import re
import shutil

P = "/root/findata.py"
KEY = "pipeline"
FILE = "pipeline.json"
ANCHOR = r'("localcosts":\s*"local_costs\.json",)'

s = open(P, encoding="utf-8").read()
if '"%s"' % KEY in s:
    print("ключ «%s» уже є — не чіпаю" % KEY)
else:
    ins = '\n    "%s": "%s",' % (KEY, FILE)
    s2, n = re.subn(ANCHOR, lambda m: m.group(1) + ins, s, count=1)
    if not n:
        print("НЕ ЗНАЙШЛА рядок localcosts — нічого не змінено")
    else:
        bak = P + ".bak-" + datetime.datetime.now().strftime("%Y%m%d-%H%M")
        shutil.copy2(P, bak)
        open(P, "w", encoding="utf-8").write(s2)
        print("копія: %s" % bak)
        print("додано: %s → %s" % (KEY, FILE))
