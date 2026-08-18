#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Звіт про переказ транзитних коштів.

Логіка (постановка користувачки 18.08.2026 + уточнення того ж дня):
    усе, що надійшло від клієнта, за винятком ВИНАГОРОДИ ЕКСПЕДИТОРА, має бути
    переказане транзитом далі. Банківські комісії, податки і бонуси — це ОПЕРАЦІЙНІ
    витрати компанії: в управлінському обліку вони лежать на угоді (щоб бачити реальний
    дохід по перевезенню), але в цей звіт не входять.

    ⚠️ ГОЛОВНЕ УТОЧНЕННЯ: транзит — це переказ З ТОГО САМОГО РАХУНКУ, НА ЯКИЙ ПРИЙШЛИ
    ГРОШІ. В угоді бувають оплати з різних видів оплати (Маерск USD, каси, Cr String
    Cycle) — вони до цього звіту НЕ належать і показуються лише довідково.
    Тому рахунок ведеться ПО КОЖНОМУ РАХУНКУ ОКРЕМО: надійшло на Х → переказано з Х.

Що рахуємо по кожній угоді:
    1) скільки НАДІЙШЛО (рахунки клієнта, сплачені на рахунки Юнітекса, з розбивкою);
    2) скільки ПЕРЕКАЗАНО транзитом і КОМУ — по кожній статті витрат окремо;
    3) що ще НЕ ПЕРЕКАЗАНО (транзитні рахунки без оплати) — потребує уваги;
    4) ЗАЛИШОК = надійшло − винагорода − переказано транзитом.

Джерело — 1С Експедитор (OData, лише читання). Нічого не змінює і не видаляє.

Запуск:
    python3 transit_report.py                # рахує і пише computed/transit_report.json
    python3 transit_report.py --dry-run      # тільки підсумок
    python3 transit_report.py --deal 22      # показати одну угоду в подробицях
"""
import argparse
import collections
import json
import os
import sys
import urllib.parse

BASE = "/root/unitex-finrep"
OUT = os.path.join(BASE, "computed", "transit_report.json")

# Рахунки Юнітекса, надходження на які вважаємо отриманими грошима
# (перелік користувачки 18.08.2026: Ейч-Ді грн, дол, євро + Форвардинг грн).
ACCOUNTS = ["Банк Юнітекс Ейч-Ді", "Банк Юнітекс Ейч-Ді USD",
            "Банк Юнітекс Ейч-Ді EUR", "Банк Юнітекс Форвардинг"]

FEE_NAME = "Винагорода експедитора"
PAID = "Оплачен"

# ОПЕРАЦІЙНІ статті — не транзит: комісії банку, податки, бонуси.
# Решта статей вважається транзитом. Список винесено сюди, щоб його було легко правити.
OPERATING = {
    "Комісія за переказ", "Свіфт переказ", "Банківський переказ",
    "Єдиний податок", "ПДВ", "Військовий збір з платника Єдиного 3 гр",
    "Агентська винагорода", "Додаткові витрати", "Інфо",
}


def client():
    sys.path.insert(0, os.path.join(BASE, "engine"))
    os.chdir(BASE)
    from odata_client import ODataClient  # noqa: PLC0415
    return ODataClient()


def page(c, ent, sel):
    out, skip = [], 0
    while True:
        p = "/%s?$format=json&$top=1000&$skip=%d&$select=%s" % (ent, skip, ",".join(sel))
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


def names(c, entity):
    return {r["Ref_Key"]: (r.get("Description") or "").strip()
            for r in page(c, entity, ["Ref_Key", "Description"])}


def build(c):
    art = names(c, "Catalog_СтатьиСчета")
    acc = names(c, "Catalog_ВидОплаты")
    who = {}
    for ent in ("Catalog_Контрагенты", "Catalog_Клиенты", "Catalog_ЮрЛица", "Catalog_Организации"):
        try:
            who.update(names(c, ent))
        except Exception:                                     # noqa: BLE001
            pass

    deals = {}
    for r in page(c, "Document_Сделка",
                  ["Ref_Key", "Number", "Date", "Статус", "DeletionMark", "Коносамент",
                   "СписокКонтейнеров", "ПунктОтправления", "ПунктНазначения"]):
        if r.get("DeletionMark"):
            continue
        deals[r["Ref_Key"]] = {
            "num": (r.get("Number") or "").lstrip("0"),
            "status": str(r.get("Статус") or ""),
            "bl": (r.get("Коносамент") or "").strip(),
            "cont": (r.get("СписокКонтейнеров") or "").strip(),
            "date": d10(r.get("Date")),
            "in_total": 0.0, "in_by_acc": collections.Counter(), "paid": "",
            "fee": 0.0, "transit": [], "operating": collections.Counter(),
            "unpaid": [], "other_acc": [], "out_by_acc": collections.Counter(),
        }

    # 1) надходження від клієнта
    inv_deal = {}
    for r in page(c, "Document_Счет",
                  ["Ref_Key", "Сделка_Key", "сумма_УЕ", "ДатаОплаты", "СтатусСчета",
                   "Posted", "Информативный", "видОплаты_Key"]):
        dk = r.get("Сделка_Key")
        if dk not in deals or not r.get("Posted") or r.get("Информативный"):
            continue
        a = acc.get(r.get("видОплаты_Key"), "")
        if a not in ACCOUNTS or str(r.get("СтатусСчета") or "") != PAID:
            continue
        d = deals[dk]
        d["in_total"] += f(r.get("сумма_УЕ"))
        d["in_by_acc"][a] += f(r.get("сумма_УЕ"))
        inv_deal[r["Ref_Key"]] = dk
        pd = d10(r.get("ДатаОплаты"))
        if pd and pd > d["paid"]:
            d["paid"] = pd

    # 2) винагорода експедитора — з рядків цих же рахунків
    for r in page(c, "Document_Счет_ТЧ", ["Ref_Key", "Статья_Key", "Сумма_УЕ"]):
        dk = inv_deal.get(r.get("Ref_Key"))
        if dk and art.get(r.get("Статья_Key")) == FEE_NAME:
            deals[dk]["fee"] += f(r.get("Сумма_УЕ"))

    # 3) витратні рахунки: транзит (кому і за що) окремо від операційних
    for r in page(c, "Document_РасходнаяНакладная",
                  ["Number", "Date", "Сделка_Key", "Сумма_УЕ", "Услуга_Key", "Posted",
                   "СтатусСчета", "ДатаОплаты", "Контрагент_Key", "ВидОплаты_Key"]):
        dk = r.get("Сделка_Key")
        if dk not in deals or not r.get("Posted"):
            continue
        d = deals[dk]
        a_name = art.get(r.get("Услуга_Key"), "") or "(без статті)"
        amount = f(r.get("Сумма_УЕ"))
        paid_ok = str(r.get("СтатусСчета") or "") == PAID
        from_acc = acc.get(r.get("ВидОплаты_Key"), "")
        item = {
            "article": a_name,
            "amount": round(amount, 2),
            "payee": who.get(r.get("Контрагент_Key")) or "не визначено",
            "from_account": from_acc,
            "invoice": (r.get("Number") or "").lstrip("0"),
            "date": d10(r.get("ДатаОплаты")) or d10(r.get("Date")),
        }
        if a_name in OPERATING:
            if paid_ok:
                d["operating"][a_name] += amount
            continue
        if from_acc not in ACCOUNTS:
            # оплачено з іншого рахунку (Маерск USD, каси, Cr String Cycle) — це НЕ транзит
            # з наших рахунків; показуємо довідково, у залишок не входить
            if paid_ok:
                d["other_acc"].append(item)
            continue
        if paid_ok:
            d["transit"].append(item)
            d["out_by_acc"][from_acc] += amount
        else:
            d["unpaid"].append(item)

    rows = []
    for d in deals.values():
        if d["in_total"] <= 0:
            continue                       # без грошей від клієнта транзиту бути не може
        transit = round(sum(x["amount"] for x in d["transit"]), 2)
        unpaid = round(sum(x["amount"] for x in d["unpaid"]), 2)
        by_art = collections.Counter()
        for x in d["transit"]:
            by_art[x["article"]] += x["amount"]
        # залишок по кожному рахунку окремо: надійшло на Х мінус переказано з Х
        per_acc = []
        for a_name in ACCOUNTS:
            got, sent = d["in_by_acc"].get(a_name, 0.0), d["out_by_acc"].get(a_name, 0.0)
            if got or sent:
                per_acc.append({"account": a_name, "in": round(got, 2), "out": round(sent, 2),
                                "left": round(got - sent, 2)})
        rows.append({
            "num": d["num"], "status": d["status"], "bl": d["bl"], "cont": d["cont"],
            "per_account": per_acc,
            "other_acc_total": round(sum(x["amount"] for x in d["other_acc"]), 2),
            "other_acc_items": sorted(d["other_acc"], key=lambda x: -x["amount"]),
            "date": d["date"], "paid": d["paid"],
            "in_total": round(d["in_total"], 2),
            "in_by_acc": {k: round(v, 2) for k, v in d["in_by_acc"].items()},
            "fee": round(d["fee"], 2),
            "transit_total": transit,
            "transit_by_article": [{"article": k, "amount": round(v, 2)}
                                   for k, v in by_art.most_common()],
            "transit_items": sorted(d["transit"], key=lambda x: -x["amount"]),
            "unpaid_total": unpaid,
            "unpaid_items": sorted(d["unpaid"], key=lambda x: -x["amount"]),
            "operating_total": round(sum(d["operating"].values()), 2),
            "operating_by_article": [{"article": k, "amount": round(v, 2)}
                                     for k, v in d["operating"].most_common()],
            "balance": round(d["in_total"] - d["fee"] - transit, 2),
        })
    rows.sort(key=lambda r: -r["balance"])
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--deal", default="")
    a = ap.parse_args()

    rows = build(client())
    pos = [r for r in rows if r["balance"] > 0]
    print("угод із надходженням від клієнта: %d" % len(rows))
    print("надійшло разом: %.2f · винагорода: %.2f · переказано транзитом: %.2f" %
          (sum(r["in_total"] for r in rows), sum(r["fee"] for r in rows),
           sum(r["transit_total"] for r in rows)))
    print("ЗАЛИШОК (ще не переказано): %.2f у %d угодах" %
          (sum(r["balance"] for r in pos), len(pos)))
    print("переказано «в мінус» (транзит більший за надходження): %d угод, %.2f" %
          (sum(1 for r in rows if r["balance"] < 0),
           sum(r["balance"] for r in rows if r["balance"] < 0)))
    print("є транзитні рахунки БЕЗ оплати: %d угод, %.2f УО" %
          (sum(1 for r in rows if r["unpaid_total"]), sum(r["unpaid_total"] for r in rows)))
    print("операційні (комісії, податки, бонуси) — окремо, у транзит не входять: %.2f" %
          sum(r["operating_total"] for r in rows))
    print("оплачено з ІНШИХ рахунків (не транзит із наших): %.2f у %d угодах" %
          (sum(r["other_acc_total"] for r in rows), sum(1 for r in rows if r["other_acc_total"])))

    if a.deal:
        r = next((x for x in rows if x["num"] == a.deal), None)
        if not r:
            print("угоди %s немає у вибірці" % a.deal)
        else:
            print("\n=== УГОДА %s (%s) ===" % (r["num"], r["status"]))
            print("надійшло %.2f: %s" % (r["in_total"], r["in_by_acc"]))
            for x in r["per_account"]:
                print("   %-26s надійшло %9.2f · переказано %9.2f · лишилось %9.2f" %
                      (x["account"], x["in"], x["out"], x["left"]))
            print("винагорода експедитора: %.2f" % r["fee"])
            print("переказано транзитом %.2f:" % r["transit_total"])
            for x in r["transit_items"]:
                print("   %-28s %9.2f  →  %-24s (з %s, %s)" %
                      (x["article"][:28], x["amount"], x["payee"][:24], x["from_account"], x["date"]))
            if r["unpaid_items"]:
                print("НЕ переказано (рахунки без оплати) %.2f:" % r["unpaid_total"])
                for x in r["unpaid_items"]:
                    print("   %-28s %9.2f  →  %s" % (x["article"][:28], x["amount"], x["payee"][:24]))
            if r["other_acc_items"]:
                print("оплачено з інших рахунків (довідково, не транзит) %.2f:" % r["other_acc_total"])
                for x in r["other_acc_items"]:
                    print("   %-28s %9.2f  з %s" % (x["article"][:28], x["amount"], x["from_account"]))
            if r["operating_by_article"]:
                print("операційні (не транзит) %.2f: %s" %
                      (r["operating_total"], ", ".join("%s %.2f" % (x["article"], x["amount"])
                                                       for x in r["operating_by_article"])))
            print("ЗАЛИШОК: %.2f" % r["balance"])

    if not a.dry_run:
        data = {"rows": rows, "accounts": ACCOUNTS, "operating": sorted(OPERATING),
                "total_in": round(sum(r["in_total"] for r in rows), 2),
                "total_fee": round(sum(r["fee"] for r in rows), 2),
                "total_transit": round(sum(r["transit_total"] for r in rows), 2),
                "total_balance": round(sum(r["balance"] for r in pos), 2),
                "count": len(rows)}
        with open(OUT, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False)
        print("записано:", OUT)


if __name__ == "__main__":
    main()
