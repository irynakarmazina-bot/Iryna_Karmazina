#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Додає звіт «Оплати Маерску» у білий список /finrep-data (findata.py).

Ідемпотентно: якщо ключ уже є — нічого не міняє. Резервна копія робиться
викликаючою командою (findata.py.bak-*). Нічого не видаляє.
"""
import re

P = "/root/findata.py"
s = open(P, encoding="utf-8").read()
if "maersk_payments" in s:
    print("вже є — не чіпаю")
else:
    s2, n = re.subn(r'("localcosts":\s*"local_costs\.json",)',
                    r'\1\n    "maersk_payments": "maersk_payments.json",', s, count=1)
    if not n:
        print("НЕ ЗНАЙШЛА рядок localcosts — нічого не змінено")
    else:
        open(P, "w", encoding="utf-8").write(s2)
        print("додано maersk_payments -> maersk_payments.json")
