#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Єдиний податок: винагорода експедитора по рахунках, оплачених на гривневий рахунок.

Постановка користувачки 02.08.2026:
  «Вибірку робити по рахунках на клієнтів з формою оплати ТІЛЬКИ Банк Юнітекс Ейч-Ді (грн).
   Колонки: Номер угоди, Дата оплати (рахунку), Винагорода (розмір винагороди експедитора),
   5% (від винагороди), 1% (від винагороди), Разом (6%). Знизу — підсумки.
   Вибірка робиться за період.»

ДЖЕРЕЛО: 1С Експедитор (OData, лише читання). Нічого не змінює і не видаляє.

ЯК ВІДБИРАЮТЬСЯ РЯДКИ:
  * Document_Счет (рахунок клієнту): проведений, НЕ інформативний,
    видОплаты = «Банк Юнітекс Ейч-Ді» (це і є гривневий рахунок; євровий
    «Банк Юнітекс Ейч-Ді EUR» — окремий вид оплати і сюди НЕ входить),
    заповнена ДатаОплаты (тобто рахунок реально оплачений);
  * ВИНАГОРОДА = Σ рядків цього рахунка (Document_Счет_ТЧ) зі статтею
    «Винагорода експедитора» — та сама стаття, що й у звіті локальних витрат;
  * 5% = винагорода × 0.05, 1% = винагорода × 0.01, разом 6% = 5% + 1%.

ЩО СВІДОМО НЕ ВХОДИТЬ (рішення користувачки 08.08.2026): рахунки без рядка
винагороди, у яких лише демередж, страхування або сканування вантажу — це
ТРАНЗИТНІ ПЛАТЕЖІ, вони до звіту не належать. Такі рахунки просто не мають
рядка «Винагорода експедитора», тому відсіюються самі; спеціального фільтра
не треба, але при перевірці «а чому їх немає» відповідь саме така.

ВАЛЮТА: перевірено --probe2 — усі 216 рахунків цього виду оплати виписані в UAH,
а рядок рахунка має ПРЯМУ гривневу суму в полі «Сумма» (поруч лежить «Сумма_УЕ» —
той самий рядок у USD). Тому винагорода береться з «Сумма» без жодного перерахунку
курсом: для податкового звіту важлива саме та гривня, що в документі.
(Перерахунок через курс рахунка лишився запасним варіантом, якщо «Сумма» порожня —
він дає ту саму величину з точністю до копійок, напр. 2 000,10 замість 2 000,00.)

Запуск:
    python3 /root/unitex-finrep/single_tax.py            # порахувати і показати
    python3 /root/unitex-finrep/single_tax.py --write    # + computed/single_tax.json
    python3 /root/unitex-finrep/single_tax.py --probe    # показати поля рядків рахунка
"""
import argparse
import collections
import json
import os
import sys
import urllib.parse

BASE = "/root/unitex-finrep"
OUT = os.path.join(BASE, "computed", "single_tax.json")

PAY_KIND = "Банк Юнітекс Ейч-Ді"        # ТІЛЬКИ гривневий; EUR-рахунок має іншу назву
FEE_NAME = "Винагорода експедитора"
RATE_5, RATE_1 = 0.05, 0.01
NULL = "00000000-0000-0000-0000-000000000000"


def client():
    sys.path.insert(0, os.path.join(BASE, "engine"))
    os.chdir(BASE)
    from odata_client import ODataClient  # noqa: PLC0415
    return ODataClient()


def page(c, ent, sel=None):
    """Усі записи сутності з пагінацією. sel=None → усі поля (для --probe)."""
    out, skip = [], 0
    while True:
        p = "/%s?$format=json&$top=1000&$skip=%d" % (ent, skip)
        if sel:
            p += "&$select=" + ",".join(sel)
        b = c._get(urllib.parse.quote(p, safe="/?&=$,'"))["value"]  # noqa: SLF001
        out += b
        if len(b) < 1000:
            return out
        skip += 1000


def f(x):
    try:
        return float(x or 0)
    except (TypeError, ValueError):
        return 0.0


def d10(x):
    x = str(x or "")
    return "" if (not x or x.startswith("0001-01-01")) else x[:10]


def money(v):
    return "{:,.2f}".format(v).replace(",", " ").replace(".", ",")


def article_guids(lines):
    """GUID статей за описами в рядках рахунків (довідник статей в OData закритий)."""
    named = collections.defaultdict(collections.Counter)
    for r in lines:
        d = (r.get("Описание") or "").strip()
        if d:
            named[r["Статья_Key"]][d] += 1
    best = {}
    for g, cnt in named.items():
        name, n = cnt.most_common(1)[0]
        if n > best.get(name, (None, 0))[1]:
            best[name] = (g, n)
    return {k: v[0] for k, v in best.items()}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true", help="зберегти computed/single_tax.json")
    ap.add_argument("--probe", action="store_true", help="показати поля рядків рахунка і вийти")
    ap.add_argument("--probe2", action="store_true", help="валюта рахунків і поля сум у рядках")
    ap.add_argument("--nofee", action="store_true",
                    help="показати відібрані рахунки БЕЗ рядка винагороди і що в них замість неї")
    ap.add_argument("--art", default="",
                    help="номери рахунків через кому: показати їхні статті і як ці ж статті "
                         "називаються в інших рахунках бази")
    a = ap.parse_args()
    c = client()

    if a.probe:
        one = page(c, "Document_Счет_ТЧ")[:1]
        print("поля Document_Счет_ТЧ:", ", ".join(sorted(one[0].keys())) if one else "порожньо")
        kinds = {(r.get("Description") or "").strip()
                 for r in page(c, "Catalog_ВидОплаты", ["Ref_Key", "Description"])}
        print("види оплати в Експедиторі:", " | ".join(sorted(kinds)))
        return

    if a.probe2:
        # У ЯКІЙ ВАЛЮТІ ці рахунки і яке поле рядка є сумою в гривні.
        cur = {r["Ref_Key"]: (r.get("Description") or "").strip()
               for r in page(c, "Catalog_Валюты", ["Ref_Key", "Description"])}
        pay = {r["Ref_Key"]: (r.get("Description") or "").strip()
               for r in page(c, "Catalog_ВидОплаты", ["Ref_Key", "Description"])}
        tgt = {k for k, v in pay.items() if v == PAY_KIND}
        invs = [r for r in page(c, "Document_Счет",
                                ["Ref_Key", "Number", "сумма_УЕ", "СуммаВал", "Валюта_Key",
                                 "видОплаты_Key", "Posted", "Информативный", "ДатаОплаты"])
                if r.get("Posted") and not r.get("Информативный")
                and r.get("видОплаты_Key") in tgt and d10(r.get("ДатаОплаты"))]
        print("рахунків «%s»: %d" % (PAY_KIND, len(invs)))
        print("валюти цих рахунків:",
              dict(collections.Counter(cur.get(r.get("Валюта_Key"), "(?)") for r in invs)))
        by_ref = collections.defaultdict(list)
        for l in page(c, "Document_Счет_ТЧ",
                      ["Ref_Key", "Описание", "Сумма", "Сумма_вал", "Сумма_УЕ", "Сумма_бух"]):
            by_ref[l.get("Ref_Key")].append(l)
        for r in invs[:3]:
            print("\nрахунок %s · валюта %s · сумма_УЕ=%s · СуммаВал=%s"
                  % (r.get("Number"), cur.get(r.get("Валюта_Key"), "?"),
                     r.get("сумма_УЕ"), r.get("СуммаВал")))
            for l in by_ref.get(r["Ref_Key"], [])[:4]:
                print("   «%s»: Сумма=%s Сумма_вал=%s Сумма_УЕ=%s Сумма_бух=%s"
                      % (str(l.get("Описание"))[:26], l.get("Сумма"), l.get("Сумма_вал"),
                         l.get("Сумма_УЕ"), l.get("Сумма_бух")))
        return

    if a.art:
        want = {x.strip().lstrip("0") for x in a.art.split(",") if x.strip()}
        invs = {r["Ref_Key"]: r for r in page(c, "Document_Счет", ["Ref_Key", "Number", "Сделка_Key"])
                if (r.get("Number") or "").lstrip("0") in want}
        lines = page(c, "Document_Счет_ТЧ",
                     ["Ref_Key", "Статья_Key", "Сумма", "Сумма_УЕ", "Описание"])
        # як цей же GUID підписаний в УСІЙ базі — щоб дізнатись назву «безіменної» статті
        names = collections.defaultdict(collections.Counter)
        for l in lines:
            d = (l.get("Описание") or "").strip()
            if d:
                names[l.get("Статья_Key")][d] += 1
        for ref, inv_r in invs.items():
            print("\nРАХУНОК %s" % (inv_r.get("Number") or "").lstrip("0"))
            for l in [x for x in lines if x.get("Ref_Key") == ref]:
                g = l.get("Статья_Key")
                alt = names.get(g)
                alt_s = (", ".join("%s×%d" % (k, v) for k, v in alt.most_common(3))
                         if alt else "ця стаття НІДЕ в базі не має опису")
                print("   опис у рахунку: «%s» · сума %s грн (%s USD)"
                      % ((l.get("Описание") or "(порожньо)").strip(), money(f(l.get("Сумма"))),
                         money(f(l.get("Сумма_УЕ")))))
                print("       та сама стаття в інших рахунках: %s" % alt_s)
        return

    # 1. номери угод
    deals = {r["Ref_Key"]: (r.get("Number") or "").lstrip("0")
             for r in page(c, "Document_Сделка", ["Ref_Key", "Number", "DeletionMark"])
             if not r.get("DeletionMark")}

    # 2. види оплати
    pay = {r["Ref_Key"]: (r.get("Description") or "").strip()
           for r in page(c, "Catalog_ВидОплаты", ["Ref_Key", "Description"])}
    target = {k for k, v in pay.items() if v == PAY_KIND}
    if not target:
        sys.exit("НЕ ЗНАЙДЕНО вид оплати «%s». Є такі: %s"
                 % (PAY_KIND, ", ".join(sorted(set(pay.values())))))

    # 3. рахунки клієнтам саме з цією формою оплати і з датою оплати
    inv = {}
    total_inv = 0
    for r in page(c, "Document_Счет",
                  ["Ref_Key", "Number", "Сделка_Key", "сумма_УЕ", "СуммаВал", "ДатаОплаты",
                   "СтатусСчета", "Posted", "Информативный", "видОплаты_Key"]):
        if not r.get("Posted") or r.get("Информативный"):
            continue
        total_inv += 1
        if r.get("видОплаты_Key") not in target:
            continue
        paid = d10(r.get("ДатаОплаты"))
        if not paid:
            continue
        uo, uah = f(r.get("сумма_УЕ")), f(r.get("СуммаВал"))
        inv[r["Ref_Key"]] = {
            "num": (r.get("Number") or "").lstrip("0"),
            "deal": deals.get(r.get("Сделка_Key"), ""),
            "paid": paid,
            "rate": (uah / uo) if uo else 0.0,   # курс саме цього рахунка
            "status": str(r.get("СтатусСчета") or ""),
            "total_uah": uah, "arts": collections.Counter(),
            "fee_uah": 0.0, "fee_uo": 0.0,
        }
    print("рахунків клієнтам усього (проведених, не інформативних): %d" % total_inv)
    print("з них «%s» і з датою оплати: %d" % (PAY_KIND, len(inv)))
    if not inv:
        sys.exit("нічого не відібрано")

    # 4. винагорода експедитора з рядків цих рахунків
    lines = page(c, "Document_Счет_ТЧ",
                 ["Ref_Key", "Статья_Key", "Сумма", "Сумма_УЕ", "Описание"])
    fee_g = article_guids(lines).get(FEE_NAME)
    if not fee_g:
        sys.exit("не знайдено статтю «%s» у рядках рахунків" % FEE_NAME)
    for r in lines:
        i = inv.get(r.get("Ref_Key"))
        if not i:
            continue
        if r.get("Статья_Key") == fee_g:
            i["fee_uah"] += f(r.get("Сумма"))       # пряма гривнева сума рядка
            i["fee_uo"] += f(r.get("Сумма_УЕ"))     # той самий рядок у USD — для довідки
        else:
            i["arts"][(r.get("Описание") or "(без опису)").strip()] += f(r.get("Сумма"))

    if a.nofee:
        bad = [i for i in inv.values() if not i["fee_uah"] and not i["fee_uo"]]
        print("\nРАХУНКИ БЕЗ РЯДКА «%s»: %d" % (FEE_NAME, len(bad)))
        for i in sorted(bad, key=lambda x: x["paid"]):
            arts = " · ".join("%s %s" % (k, money(v)) for k, v in i["arts"].most_common())
            print("  угода %-5s рахунок %-6s оплачено %s  сума рахунка %12s грн"
                  % (i["deal"], i["num"], i["paid"], money(i["total_uah"])))
            print("      статті: %s" % (arts or "(рядків немає)"))
        return

    rows = []
    for i in inv.values():
        # гривня з документа; якщо раптом порожня — запасний перерахунок курсом рахунка
        fee = round(i["fee_uah"] or i["fee_uo"] * i["rate"], 2)
        if not fee:
            continue
        rows.append({"deal": i["deal"], "invoice": i["num"], "paid": i["paid"],
                     "feeUsd": round(i["fee_uo"], 2), "fee": fee, "t5": round(fee * RATE_5, 2), "t1": round(fee * RATE_1, 2),
                     "t6": round(fee * (RATE_5 + RATE_1), 2)})
    rows.sort(key=lambda r: (r["paid"], r["deal"]))
    no_fee = len(inv) - len(rows)

    s_fee = round(sum(r["fee"] for r in rows), 2)
    s5 = round(sum(r["t5"] for r in rows), 2)
    s1 = round(sum(r["t1"] for r in rows), 2)
    s6 = round(sum(r["t6"] for r in rows), 2)

    print("\n%-8s %-12s %14s %12s %12s %12s" % ("Угода", "Дата оплати", "Винагорода", "5%", "1%", "Разом 6%"))
    for r in rows[:200]:
        print("%-8s %-12s %14s %12s %12s %12s"
              % (r["deal"], r["paid"], money(r["fee"]), money(r["t5"]), money(r["t1"]), money(r["t6"])))
    print("%-8s %-12s %14s %12s %12s %12s" % ("РАЗОМ", "", money(s_fee), money(s5), money(s1), money(s6)))
    print("\nрядків: %d · рахунків без винагороди в рядках: %d" % (len(rows), no_fee))
    if rows:
        print("період даних: %s — %s" % (rows[0]["paid"], rows[-1]["paid"]))

    if a.write:
        os.makedirs(os.path.dirname(OUT), exist_ok=True)
        json.dump({"rows": rows,
                   "totals": {"fee": s_fee, "t5": s5, "t1": s1, "t6": s6, "count": len(rows)},
                   "payKind": PAY_KIND, "currency": "UAH",
                   "rates": {"t5": RATE_5, "t1": RATE_1},
                   "invoicesChecked": total_inv, "invoicesSelected": len(inv),
                   "invoicesWithoutFee": no_fee,
                   "source": "Document_Счет + Document_Счет_ТЧ (стаття «%s»), вид оплати «%s»"
                             % (FEE_NAME, PAY_KIND)},
                  open(OUT, "w", encoding="utf-8"), ensure_ascii=False)
        print("\nзаписано %s" % OUT)


if __name__ == "__main__":
    main()
