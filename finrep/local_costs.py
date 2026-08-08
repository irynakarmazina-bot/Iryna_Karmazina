#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Локальні витрати за кордоном: скільки лишилось на гривневому рахунку по завершених угодах.

Навіщо: клієнт платить у гривні на рахунок «Банк Юнітекс Ейч-Ді», з цього ж рахунку
оплачуються українські витрати по угоді. Те, що лишилось після цих витрат і після
винагороди експедитора, — це локальні витрати за кордоном, які треба переказати.
Окремою статтею в рахунку клієнта вони здебільшого не виділені, тому рахуємо.

Методика (уточнення користувачки 02.08.2026): профіт — це НЕ загальний прибуток по угоді,
а різниця між надходженнями і витратами, які пройшли ПО ГРИВНЕВОМУ РАХУНКУ. Причина:
в одній угоді бувають рахунки в різних валютах і оплати з інших кас, і вони до переказу
за кордон стосунку не мають.

Формули (усі суми в УО = USD-еквівалент, як в Експедиторі):
    надходження = Σ доходних рахунків угоди, які СПЛАЧЕНІ на «Банк Юнітекс Ейч-Ді»
    витрати     = Σ витратних рахунків угоди, СПЛАЧЕНИХ з «Банк Юнітекс Ейч-Ді»
    профіт      = надходження − витрати
    винагорода  = рядки тих самих доходних рахунків зі статтею «Винагорода експедитора»
    інфо+комісії= витратні рахунки з того ж рахунку зі статтями INFO_ARTICLES;
                  додаються до профіту, якщо їх сума по угоді > INFO_MIN
    різниця     = профіт + інфо+комісії − винагорода       (у таблицю — тільки додатні)

Джерело — 1С Експедитор (OData, лише читання). Нічого не змінює і не видаляє.

Запуск:
    python3 local_costs.py                 # рахує і пише computed/local_costs.json
    python3 local_costs.py --dry-run       # тільки показати підсумок, файл не писати
    python3 local_costs.py --top 15        # + перші рядки таблиці
"""
import argparse
import collections
import json
import os
import sys
import urllib.parse

BASE = "/root/unitex-finrep"
OUT = os.path.join(BASE, "computed", "local_costs.json")

# --- рахунок, по якому все рахується (вимога користувачки: тільки гривневі розрахунки) ---
ACCOUNT = "Банк Юнітекс Ейч-Ді"

# --- статті (довідник Catalog_СтатьиСчета опублікований Софт Про 02.08.2026) ---
FEE_NAME = "Винагорода експедитора"
LOCAL_ABROAD_NAME = "Локальні витрати за кордоном"
# «інфо та банківські комісії» — вибір користувачки: всі чотири схожі статті
INFO_ARTICLES = {"Інфо", "Комісія за переказ", "Банківський переказ", "Свіфт переказ"}
INFO_MIN = 10.0                       # поріг у УО, рахується сумарно по угоді

# статус угоди: тільки завершені (рішення користувачки 02.08.2026)
STATUSES = ["Завершена"]
STATUS_UK = {"Завершена": "Завершена", "ВыставленСчет": "Виставлений рахунок",
             "Выполняется": "Виконується", "Букинг": "Букінг", "Отменена": "Скасована"}
PAID = "Оплачен"                      # значення реквізиту СтатусСчета
# УВАГА: у витратних рахунках є ще прапорець «Оплачен» — він у ВСІХ записах False
# (перевірено 02.08.2026: 443 рахунки зі статусом «Оплачен» мають прапорець False).
# Орієнтуватись треба на СтатусСчета, а не на прапорець.


def client():
    sys.path.insert(0, os.path.join(BASE, "engine"))
    os.chdir(BASE)
    from odata_client import ODataClient  # noqa: PLC0415
    return ODataClient()


def page(c, ent, sel):
    """Усі записи сутності з пагінацією (кириличні імена полів кодуються у URL)."""
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


def collect(c):
    art = names(c, "Catalog_СтатьиСчета")
    acc = names(c, "Catalog_ВидОплаты")

    deals = {}
    for r in page(c, "Document_Сделка",
                  ["Ref_Key", "Number", "Date", "Статус", "DeletionMark",
                   "Коносамент", "СписокКонтейнеров", "ПунктОтправления", "ПунктНазначения",
                   "ДатаЗавершения"]):
        if r.get("DeletionMark") or str(r.get("Статус") or "") not in STATUSES:
            continue
        deals[r["Ref_Key"]] = {
            "num": (r.get("Number") or "").lstrip("0"),
            "status": STATUS_UK.get(str(r.get("Статус")), str(r.get("Статус"))),
            "bl": (r.get("Коносамент") or "").strip(),
            "cont": (r.get("СписокКонтейнеров") or "").strip(),
            "route": " → ".join(x for x in [(r.get("ПунктОтправления") or "").strip(),
                                            (r.get("ПунктНазначения") or "").strip()] if x),
            "date": d10(r.get("Date")),
            "completed": d10(r.get("ДатаЗавершения")),
            "revenue": 0.0, "cost": 0.0, "fee": 0.0, "local_abroad": 0.0, "info_bank": 0.0,
            "paid": "", "n_inv": 0, "revenue_all": 0.0, "cost_all": 0.0,
        }

    # доходні рахунки, сплачені на потрібний рахунок
    inv_deal = {}
    for r in page(c, "Document_Счет",
                  ["Ref_Key", "Сделка_Key", "сумма_УЕ", "ДатаОплаты", "СтатусСчета",
                   "Posted", "Информативный", "видОплаты_Key"]):
        dk = r.get("Сделка_Key")
        if dk not in deals or not r.get("Posted") or r.get("Информативный"):
            continue
        d = deals[dk]
        d["revenue_all"] += f(r.get("сумма_УЕ"))          # довідково: весь дохід угоди
        if acc.get(r.get("видОплаты_Key")) != ACCOUNT or str(r.get("СтатусСчета") or "") != PAID:
            continue
        inv_deal[r["Ref_Key"]] = dk
        d["n_inv"] += 1
        d["revenue"] += f(r.get("сумма_УЕ"))
        pd = d10(r.get("ДатаОплаты"))
        if pd and pd > d["paid"]:
            d["paid"] = pd

    # рядки цих рахунків: винагорода експедитора і вже виділені локальні витрати
    for r in page(c, "Document_Счет_ТЧ", ["Ref_Key", "Статья_Key", "Сумма_УЕ"]):
        dk = inv_deal.get(r.get("Ref_Key"))
        if not dk:
            continue
        nm = art.get(r.get("Статья_Key"), "")
        if nm == FEE_NAME:
            deals[dk]["fee"] += f(r.get("Сумма_УЕ"))
        elif nm == LOCAL_ABROAD_NAME:
            deals[dk]["local_abroad"] += f(r.get("Сумма_УЕ"))

    # витратні рахунки, оплачені з того самого рахунку
    for r in page(c, "Document_РасходнаяНакладная",
                  ["Сделка_Key", "Сумма_УЕ", "Услуга_Key", "Posted", "ВидОплаты_Key",
                   "СтатусСчета"]):
        dk = r.get("Сделка_Key")
        if dk not in deals or not r.get("Posted"):
            continue
        d = deals[dk]
        d["cost_all"] += f(r.get("Сумма_УЕ"))             # довідково: всі витрати угоди
        if acc.get(r.get("ВидОплаты_Key")) != ACCOUNT or str(r.get("СтатусСчета") or "") != PAID:
            continue
        d["cost"] += f(r.get("Сумма_УЕ"))
        if art.get(r.get("Услуга_Key"), "") in INFO_ARTICLES:
            d["info_bank"] += f(r.get("Сумма_УЕ"))
    return deals


def build(deals):
    """Рядки таблиці + причини, чому угоди відсіялись."""
    rows, skipped = [], collections.Counter()
    for d in deals.values():
        if not d["n_inv"]:
            skipped["немає сплаченого рахунку клієнта на «%s»" % ACCOUNT] += 1
            continue
        profit = round(d["revenue"] - d["cost"], 2)
        add = round(d["info_bank"], 2) if d["info_bank"] > INFO_MIN else 0.0
        rows.append({
            "num": d["num"], "status": d["status"], "bl": d["bl"], "cont": d["cont"],
            "route": d["route"], "paid": d["paid"], "completed": d["completed"],
            "date": d["date"],
            "revenue": round(d["revenue"], 2), "cost": round(d["cost"], 2),
            "revenue_all": round(d["revenue_all"], 2), "cost_all": round(d["cost_all"], 2),
            "profit": profit, "fee": round(d["fee"], 2),
            "info_bank": round(d["info_bank"], 2), "info_added": add,
            "local_abroad": round(d["local_abroad"], 2),
            "diff": round(profit + add - d["fee"], 2),
        })
    rows.sort(key=lambda r: -r["diff"])
    return rows, skipped


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--top", type=int, default=0)
    a = ap.parse_args()

    c = client()
    deals = collect(c)
    rows, skipped = build(deals)
    pos = [r for r in rows if r["diff"] > 0]
    print("угод у статусі %s: %d" % ("/".join(STATUS_UK.get(s, s) for s in STATUSES), len(deals)))
    print("з них із оплатою на «%s»: %d" % (ACCOUNT, len(rows)))
    for k, n in skipped.most_common():
        print("   відсіяно — %s: %d" % (k, n))
    print("профіт > винагороди: %d угод, сума до переказу: %.2f УО" %
          (len(pos), sum(r["diff"] for r in pos)))
    print("інфо та комісії з цього ж рахунку: %.2f УО (додано в %d угодах)" %
          (sum(r["info_bank"] for r in rows), sum(1 for r in rows if r["info_added"])))
    print("вже виділені «%s» у рахунках: %d угод, %.2f УО" %
          (LOCAL_ABROAD_NAME, sum(1 for r in rows if r["local_abroad"]),
           sum(r["local_abroad"] for r in rows)))
    if a.top:
        for r in pos[:a.top]:
            print("  №%-5s надійшло %9.2f  витрати %9.2f  профіт %9.2f  винагорода %7.2f"
                  "  інфо %6.2f  різниця %9.2f" %
                  (r["num"], r["revenue"], r["cost"], r["profit"], r["fee"],
                   r["info_added"], r["diff"]))

    if not a.dry_run:
        data = {"rows": rows, "account": ACCOUNT, "info_articles": sorted(INFO_ARTICLES),
                "info_min": INFO_MIN, "statuses": [STATUS_UK.get(s, s) for s in STATUSES],
                "skipped": dict(skipped), "screened": len(deals),
                "total_diff": round(sum(r["diff"] for r in pos), 2), "count": len(pos)}
        # Пишемо в тимчасовий файл поруч і лише потім підміняємо одним рухом.
        # Інакше обрив посеред запису (або читання сторінкою в цю саму мить)
        # давав би наполовину записаний JSON — сторінка «Бух. облік» показала б
        # порожнечу або впала, і причина була б незрозуміла.
        tmp = OUT + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, OUT)
        print("записано:", OUT)


if __name__ == "__main__":
    main()
