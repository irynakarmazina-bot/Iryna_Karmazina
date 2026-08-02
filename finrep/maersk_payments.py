#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Оплати Маерску: усі виплати цьому постачальнику по місяцях.

Прохання користувачки 02.08.2026: «проаналізуй всі наші оплати на Маерск
незалежно від виду оплати та валюти, суми по місяцях».

ДЖЕРЕЛО: /root/unitex-finrep/normalized/cash_moves.csv — фактичні рухи грошей,
які збирач тягне з Експедитора (те саме джерело, що й для фінзвіту). Беруться
ЛИШЕ витратні рухи (виплати), контрагент яких містить «Маерск»/«Maersk».
Вид оплати (каса/банк) НЕ фільтрується — рахуються всі.

Валюти: сума показується і в оригінальній валюті кожної каси, і в У.О. (USD-
еквівалент, як його рахує сам збирач) — щоб можна було скласти різні валюти.

Скрипт нічого не змінює: читає CSV і пише computed/maersk_payments.json
(з ключем --write) + друкує таблицю.

Запуск:
    python3 /root/unitex-finrep/maersk_payments.py            # тільки показати
    python3 /root/unitex-finrep/maersk_payments.py --write    # + записати JSON
"""
import argparse
import csv
import json
import os
import re
import sys
from collections import defaultdict

ROOT = os.environ.get("FINREP_ROOT", "/root/unitex-finrep")
NORM = os.path.join(ROOT, "normalized")
OUT = os.path.join(ROOT, "computed", "maersk_payments.json")
PAT = re.compile(r"аерск|aersk", re.IGNORECASE)
UK = {"01": "січ", "02": "лют", "03": "бер", "04": "кві", "05": "тра", "06": "чер",
      "07": "лип", "08": "сер", "09": "вер", "10": "жов", "11": "лис", "12": "гру"}


def num(v):
    try:
        return float(str(v).replace(" ", "").replace(" ", "").replace(",", "."))
    except Exception:
        return 0.0


def rows(name):
    p = os.path.join(NORM, name)
    if not os.path.exists(p):
        return [], []
    with open(p, encoding="utf-8") as fh:
        rd = csv.DictReader(fh)
        data = list(rd)
        return (rd.fieldnames or []), data


def pick(fields, *cands):
    """Перша колонка, назва якої містить один із варіантів."""
    for c in cands:
        for f in fields:
            if c in f.lower():
                return f
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true", help="зберегти computed/maersk_payments.json")
    a = ap.parse_args()

    fields, data = rows("cash_moves.csv")
    if not data:
        sys.exit("НЕМАЄ ДАНИХ: %s/cash_moves.csv" % NORM)
    print("cash_moves.csv: колонки = %s" % ", ".join(fields))
    print("усього рухів: %d" % len(data))

    # де саме згадується Маерск — щоб не гадати, яка колонка є контрагентом
    where = defaultdict(int)
    hits = []
    for r in data:
        matched = [k for k, v in r.items() if v and PAT.search(str(v))]
        if matched:
            hits.append(r)
            for k in matched:
                where[k] += 1
    print("рухів зі згадкою Маерск: %d, у колонках: %s"
          % (len(hits), ", ".join("%s=%d" % kv for kv in sorted(where.items(), key=lambda x: -x[1]))))
    if not hits:
        sys.exit("У cash_moves.csv згадок про Маерск немає — скажи, де шукати.")

    f_date = pick(fields, "date", "дата")
    f_cur = pick(fields, "currency", "валют")
    f_cash = pick(fields, "cash_name", "касса", "каса")
    f_exp = pick(fields, "expense_uo")
    f_inc = pick(fields, "income_uo")
    f_amt = pick(fields, "amount_uo", "sum_uo", "uo")
    f_raw = pick(fields, "amount", "сум")
    print("беру: дата=%s, валюта=%s, каса=%s, витрата_УО=%s, надходження_УО=%s, сума=%s"
          % (f_date, f_cur, f_cash, f_exp, f_inc, f_amt or f_raw))
    if not f_date:
        sys.exit("не знайшла колонку з датою — покажи структуру файлу")

    by_month = defaultdict(lambda: {"uo": 0.0, "cnt": 0, "cur": defaultdict(float), "cash": defaultdict(float)})
    skipped_income = 0
    for r in hits:
        d = str(r.get(f_date) or "")[:10]
        if len(d) < 7:
            continue
        uo_out = num(r.get(f_exp)) if f_exp else 0.0
        uo_in = num(r.get(f_inc)) if f_inc else 0.0
        if uo_out <= 0:                      # це не виплата (надходження/повернення)
            if uo_in > 0:
                skipped_income += 1
            continue
        m = d[:7]
        b = by_month[m]
        b["uo"] += uo_out
        b["cnt"] += 1
        if f_cur:
            b["cur"][str(r.get(f_cur) or "—")] += num(r.get(f_raw)) if f_raw else 0.0
        if f_cash:
            b["cash"][str(r.get(f_cash) or "—")] += uo_out

    months = sorted(by_month)
    if not months:
        sys.exit("виплат Маерску в cash_moves.csv не знайдено (є лише надходження: %d)" % skipped_income)

    total = sum(by_month[m]["uo"] for m in months)
    cnt = sum(by_month[m]["cnt"] for m in months)
    print("\nОПЛАТИ МАЕРСКУ ПО МІСЯЦЯХ (У.О.)")
    print("%-12s %14s %8s  %s" % ("Місяць", "Сума У.О.", "Платежів", "У валютах"))
    table = []
    for m in months:
        b = by_month[m]
        lbl = "%s %s" % (UK.get(m[5:7], m[5:7]), m[:4])
        cur = " · ".join("%s %s" % (fmt(v), k) for k, v in sorted(b["cur"].items(), key=lambda x: -abs(x[1])) if v)
        print("%-12s %14s %8d  %s" % (lbl, fmt(b["uo"]), b["cnt"], cur))
        table.append({"month": m, "label": lbl, "uo": round(b["uo"], 2), "count": b["cnt"],
                      "byCurrency": {k: round(v, 2) for k, v in b["cur"].items() if v},
                      "byCash": {k: round(v, 2) for k, v in b["cash"].items() if v}})
    print("%-12s %14s %8d" % ("РАЗОМ", fmt(total), cnt))
    if skipped_income:
        print("(не враховано %d надходжень/повернень від Маерска — це не оплати)" % skipped_income)

    if a.write:
        os.makedirs(os.path.dirname(OUT), exist_ok=True)
        json.dump({"rows": table, "totalUo": round(total, 2), "count": cnt,
                   "source": "normalized/cash_moves.csv", "filter": "контрагент містить Маерск/Maersk, лише виплати"},
                  open(OUT, "w", encoding="utf-8"), ensure_ascii=False)
        print("\nзаписано %s" % OUT)


def fmt(v):
    return ("%,.2f" % v).replace(",", " ").replace(".", ",") if False else \
        "{:,.2f}".format(v).replace(",", " ").replace(".", ",")


if __name__ == "__main__":
    main()
