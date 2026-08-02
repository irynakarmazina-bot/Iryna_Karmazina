#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Оплати Маерску: усі виплати цьому контрагенту по місяцях.

Прохання користувачки 02.08.2026: «проаналізуй всі наші оплати на Маерск
незалежно від виду оплати та валюти, суми по місяцях».

ДЖЕРЕЛО: /root/unitex-finrep/normalized/cash_moves.csv — фактичні рухи грошей,
які збирач тягне з Експедитора (те саме джерело, що й фінзвіт).
Колонки: document, date, payment_method, counterparty, supplier_invoice_ref, deal,
vid, operation, currency, income, income_uo, expense, expense_uo, note, category,
owner, transfer_group_key, transit_flag, fx_bug_flag.

ЯК РАХУЄТЬСЯ (уточнено користувачкою 02.08.2026):
  * оплатою Маерску вважається виплата, якщо АБО контрагент = Maersk A/S,
    АБО вона пройшла через касу «Маерск USD» — з цієї каси ми платимо ТІЛЬКИ
    Маерску (перевірено: з 96 виплат 93 мають контрагента Maersk A/S, а 3 —
    просто незаповнений контрагент, інших отримувачів немає);
  * згадка «Маерск» лише в примітці (note) НЕ рахується — там трапляються
    платежі іншим контрагентам;
  * беремо лише витратні рухи (expense_uo > 0) — надходження й повернення це не оплати;
  * внутрішні перекази між своїми касами (transfer_group_key заповнений) рахуються
    окремо і в суму оплат НЕ входять;
  * валюта не фільтрується: показуємо і суму в У.О. (USD-еквівалент збирача),
    і розбивку по оригінальних валютах.

Запуск:
    python3 /root/unitex-finrep/maersk_payments.py            # показати
    python3 /root/unitex-finrep/maersk_payments.py --write    # + computed/maersk_payments.json
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
        return float(str(v).replace(" ", "").replace(" ", "").replace(",", "."))
    except Exception:
        return 0.0


def fmt(v):
    return "{:,.2f}".format(v).replace(",", " ").replace(".", ",")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    a = ap.parse_args()

    path = os.path.join(NORM, "cash_moves.csv")
    if not os.path.exists(path):
        sys.exit("НЕМАЄ %s" % path)
    data = list(csv.DictReader(open(path, encoding="utf-8")))

    def is_cp(r):
        return bool(PAT.search(str(r.get("counterparty") or "")))

    def is_kasa(r):
        return bool(PAT.search(str(r.get("payment_method") or "")))

    by_cp = [r for r in data if is_cp(r) or is_kasa(r)]
    names = sorted({str(r.get("counterparty") or "(не заповнено)").strip() for r in by_cp})
    only_note = [r for r in data if not is_cp(r) and not is_kasa(r)
                 and PAT.search(str(r.get("note") or ""))]
    print("рухів усього: %d · контрагент Maersk або каса «Маерск USD»: %d" % (len(data), len(by_cp)))
    print("контрагенти в цих рухах: %s" % " | ".join(names))
    if only_note:
        s_note = sum(num(r.get("expense_uo")) for r in only_note)
        who = sorted({str(r.get("counterparty") or "—").strip() for r in only_note})
        print("НЕ рахую (Маерск лише в примітці): %d рухів на %s У.О. — контрагенти: %s"
              % (len(only_note), fmt(s_note), ", ".join(who)[:200]))

    pays, transfers, incomes = [], [], []
    for r in by_cp:
        if str(r.get("transfer_group_key") or "").strip():
            transfers.append(r)
        elif num(r.get("expense_uo")) > 0:
            pays.append(r)
        elif num(r.get("income_uo")) > 0:
            incomes.append(r)

    by_month = defaultdict(lambda: {"uo": 0.0, "cnt": 0, "cur": defaultdict(float),
                                    "pm": defaultdict(float), "vid": defaultdict(float)})
    for r in pays:
        d = str(r.get("date") or "")[:10]
        if len(d) < 7:
            continue
        b = by_month[d[:7]]
        uo = num(r.get("expense_uo"))
        b["uo"] += uo
        b["cnt"] += 1
        b["cur"][str(r.get("currency") or "—").strip()] += num(r.get("expense"))
        b["pm"][str(r.get("payment_method") or "—").strip()] += uo
        b["vid"][str(r.get("vid") or "—").strip()] += uo

    months = sorted(by_month)
    if not months:
        sys.exit("виплат контрагенту Маерск не знайдено")

    total = sum(by_month[m]["uo"] for m in months)
    cnt = sum(by_month[m]["cnt"] for m in months)
    cur_tot, pm_tot = defaultdict(float), defaultdict(float)
    table = []
    print("\nОПЛАТИ МАЕРСКУ ПО МІСЯЦЯХ")
    print("%-10s %14s %6s   %s" % ("Місяць", "Сума У.О.", "К-сть", "У валютах платежу"))
    for m in months:
        b = by_month[m]
        lbl = "%s %s" % (UK.get(m[5:7], m[5:7]), m[:4])
        cur = " · ".join("%s %s" % (fmt(v), k) for k, v in sorted(b["cur"].items(), key=lambda x: -x[1]) if v)
        print("%-10s %14s %6d   %s" % (lbl, fmt(b["uo"]), b["cnt"], cur))
        for k, v in b["cur"].items():
            cur_tot[k] += v
        for k, v in b["pm"].items():
            pm_tot[k] += v
        table.append({"month": m, "label": lbl, "uo": round(b["uo"], 2), "count": b["cnt"],
                      "byCurrency": {k: round(v, 2) for k, v in b["cur"].items() if v},
                      "byMethod": {k: round(v, 2) for k, v in b["pm"].items() if v}})
    print("%-10s %14s %6d" % ("РАЗОМ", fmt(total), cnt))

    print("\nразом по валютах: %s" % " · ".join("%s %s" % (fmt(v), k)
          for k, v in sorted(cur_tot.items(), key=lambda x: -x[1]) if v))
    print("разом по видах оплати (У.О.): %s" % " · ".join("%s — %s" % (k, fmt(v))
          for k, v in sorted(pm_tot.items(), key=lambda x: -x[1]) if v))
    print("\nне враховано: внутрішніх переказів %d, надходжень/повернень від Маерска %d"
          % (len(transfers), len(incomes)))
    if incomes:
        print("  (надходження від Маерска на %s У.О.)"
              % fmt(sum(num(r.get("income_uo")) for r in incomes)))

    if a.write:
        os.makedirs(os.path.dirname(OUT), exist_ok=True)
        json.dump({"rows": table, "totalUo": round(total, 2), "count": cnt,
                   "byCurrency": {k: round(v, 2) for k, v in cur_tot.items() if v},
                   "byMethod": {k: round(v, 2) for k, v in pm_tot.items() if v},
                   "excluded": {"transfers": len(transfers), "incomes": len(incomes)},
                   "counterparties": names,
                   "source": "normalized/cash_moves.csv · контрагент Maersk A/S або каса «Маерск USD» · expense_uo > 0"},
                  open(OUT, "w", encoding="utf-8"), ensure_ascii=False)
        print("\nзаписано %s" % OUT)


if __name__ == "__main__":
    main()
