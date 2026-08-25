#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Локальні витрати за кордоном: різниця між профітом і винагородою експедитора.

Навіщо: те, що лишається по угоді після всіх витрат і після винагороди експедитора, —
це локальні витрати за кордоном, які треба переказати. Окремою статтею в рахунку клієнта
вони здебільшого не виділені, тому рахуємо.

⚠️ УТОЧНЕННЯ КОРИСТУВАЧКИ 25.08.2026: рахувати треба саме ПРИБУТОК (усі витрати),
а не «Залишок» (тільки оплачені). Її слова: «ти маєш рахувати тільки Профіт, на Залишок
не дивись». Раніше тут стояли лише оплачені витрати — виправлено.

МЕТОДИКА ЗВІРЕНА З ФАКТОМ (18.08.2026). Користувачка надіслала 16 угод, по яких локальні
витрати вже сплачені, з точними сумами (разом 10 095 УО). Перевірка чотирьох формул:
    • надходження на рахунки Юнітекса − витрати з ЦИХ ЖЕ рахунків .... 54 715 (×4 завищує)
    • те саме − усі витрати угоди ........................................ −2 081
    • те саме − усі сплачені витрати ..................................... −1 796
    • УСІ надходження угоди − усі СПЛАЧЕНІ витрати − винагорода .......... 10 178 ✔
Тому рахуємо за останньою. Чому «тільки гривневий рахунок» завищував: фрахт і залізниця
платяться з доларових рахунків («Банк Cr String Cycle LLC», «Маерск USD»), і при такому
підході просто не віднімались (угода 22: по грн рахунку витрат 24,88 при фрахті 1 900).

Формули (усі суми в УО = USD-еквівалент, як в Експедиторі):
    надходження = Σ УСІХ доходних рахунків угоди (проведених, не інформативних)
    витрати     = Σ УСІХ витратних рахунків угоди (проведених), незалежно від того,
                  оплачені вони чи ще ні
    профіт      = надходження − витрати        ← це «Прибуток» в Експедиторі
    винагорода  = рядки доходних рахунків, сплачених на рахунки Юнітекса, зі статтею
                  «Винагорода експедитора»
    інфо+комісії= витратні рахунки зі статтями INFO_ARTICLES;
                  додаються до профіту, якщо їх сума по угоді > INFO_MIN
    різниця     = профіт + інфо+комісії − винагорода       (у таблицю — тільки додатні)

У таблицю потрапляють угоди, у яких є хоч один СПЛАЧЕНИЙ рахунок клієнту на рахунки
Юнітекса (грн або EUR) — умова користувачки від 11.08.2026.

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
import urllib.request

BASE = "/root/unitex-finrep"
OUT = os.path.join(BASE, "computed", "local_costs.json")
RATES = os.path.join(BASE, "computed", "nbu_rates.json")   # кеш курсів НБУ (валюта+дата → курс)

# --- рахунки, по яких усе рахується ---
# Гривневий — основний. Євровий доданий 08.08.2026 за зауваженням користувачки
# («в звіті немає оплат на рахунок в євро»): це той самий рахунок Юнітекса, просто у євро,
# і оплати клієнтів на нього теж мають потрапляти в розрахунок.
ACCOUNTS = ["Банк Юнітекс Ейч-Ді", "Банк Юнітекс Ейч-Ді EUR"]
ACCOUNT = " / ".join(ACCOUNTS)          # для підписів на сторінці

# --- статті (довідник Catalog_СтатьиСчета опублікований Софт Про 02.08.2026) ---
FEE_NAME = "Винагорода експедитора"
LOCAL_ABROAD_NAME = "Локальні витрати за кордоном"
# «інфо та банківські комісії» — вибір користувачки: всі чотири схожі статті
INFO_ARTICLES = {"Інфо", "Комісія за переказ", "Банківський переказ", "Свіфт переказ"}
INFO_MIN = 10.0                       # поріг у УО, рахується сумарно по угоді

# Статус угоди НЕ фільтрує вибірку (рішення користувачки 11.08.2026:
# «беремо всі сплачені рахунки на клієнтів, статус угоди неважливий»).
# Порожній список = беремо угоди з будь-яким статусом; сам статус лишається в таблиці колонкою.
STATUSES = []
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


def nbu_rate(code, date, cache):
    """Курс НБУ на дату (РРРР-ММ-ДД). Гривня = 1. Значення кешуються у файл:
    курс на минулу дату не змінюється, тому смикати НБУ щоразу не треба."""
    if not code or code == "UAH" or not date:
        return 1.0
    key = "%s:%s" % (code, date)
    if key in cache:
        return cache[key]
    url = ("https://bank.gov.ua/NBUStatService/v1/statdirectory/exchange"
           "?valcode=%s&date=%s&json" % (code, date.replace("-", "")))
    try:
        with urllib.request.urlopen(url, timeout=30) as r:
            js = json.loads(r.read().decode("utf-8"))
        rate = float(js[0]["rate"]) if js else 0.0
    except Exception as e:                                    # noqa: BLE001
        print("   ⚠ курс НБУ %s на %s не отримано (%s)" % (code, date, type(e).__name__))
        rate = 0.0
    cache[key] = rate
    return rate


def load_rates():
    try:
        with open(RATES, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:                                         # noqa: BLE001
        return {}


def save_rates(cache):
    with open(RATES, "w", encoding="utf-8") as fh:
        json.dump(cache, fh, ensure_ascii=False, indent=1)


def names(c, entity):
    return {r["Ref_Key"]: (r.get("Description") or "").strip()
            for r in page(c, entity, ["Ref_Key", "Description"])}


def collect(c):
    art = names(c, "Catalog_СтатьиСчета")
    acc = names(c, "Catalog_ВидОплаты")
    cur = names(c, "Catalog_Валюты")

    deals = {}
    for r in page(c, "Document_Сделка",
                  ["Ref_Key", "Number", "Date", "Статус", "DeletionMark",
                   "Коносамент", "СписокКонтейнеров", "ПунктОтправления", "ПунктНазначения",
                   "ДатаЗавершения"]):
        if r.get("DeletionMark") or (STATUSES and str(r.get("Статус") or "") not in STATUSES):
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
            "paid": "", "n_inv": 0, "revenue_all": 0.0, "cost_all": 0.0, "cost_acc": 0.0,
            # винагорода у валюті рахунку: {валюта: сума}, і дата оплати по кожній валюті
            "fee_val": collections.Counter(), "fee_paid": {},
        }

    # доходні рахунки, сплачені на потрібний рахунок
    inv_deal = {}
    for r in page(c, "Document_Счет",
                  ["Ref_Key", "Сделка_Key", "сумма_УЕ", "ДатаОплаты", "СтатусСчета",
                   "Posted", "Информативный", "видОплаты_Key", "Валюта_Key"]):
        dk = r.get("Сделка_Key")
        if dk not in deals or not r.get("Posted") or r.get("Информативный"):
            continue
        d = deals[dk]
        d["revenue_all"] += f(r.get("сумма_УЕ"))          # довідково: весь дохід угоди
        if acc.get(r.get("видОплаты_Key")) not in ACCOUNTS or str(r.get("СтатусСчета") or "") != PAID:
            continue
        inv_deal[r["Ref_Key"]] = (dk, cur.get(r.get("Валюта_Key"), ""), d10(r.get("ДатаОплаты")))
        d["n_inv"] += 1
        d["revenue"] += f(r.get("сумма_УЕ"))
        pd = d10(r.get("ДатаОплаты"))
        if pd and pd > d["paid"]:
            d["paid"] = pd

    # рядки цих рахунків: винагорода експедитора і вже виділені локальні витрати
    for r in page(c, "Document_Счет_ТЧ", ["Ref_Key", "Статья_Key", "Сумма_УЕ", "Сумма_вал"]):
        v = inv_deal.get(r.get("Ref_Key"))
        if not v:
            continue
        dk, ccy, pdate = v
        nm = art.get(r.get("Статья_Key"), "")
        if nm == FEE_NAME:
            deals[dk]["fee"] += f(r.get("Сумма_УЕ"))
            deals[dk]["fee_val"][ccy] += f(r.get("Сумма_вал"))
            # дата оплати рахунку, у якому стоїть винагорода — за нею беремо курс НБУ
            if pdate and pdate > deals[dk]["fee_paid"].get(ccy, ""):
                deals[dk]["fee_paid"][ccy] = pdate
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
        d["cost_all"] += f(r.get("Сумма_УЕ"))             # довідково: всі проведені витрати
        if acc.get(r.get("ВидОплаты_Key")) in ACCOUNTS and str(r.get("СтатусСчета") or "") == PAID:
            d["cost_acc"] += f(r.get("Сумма_УЕ"))         # довідково: витрати з наших рахунків
        # у профіт входять УСІ проведені витрати — і оплачені, і ще ні (як «Прибуток» в 1С)
        d["cost"] += f(r.get("Сумма_УЕ"))
        if art.get(r.get("Услуга_Key"), "") in INFO_ARTICLES:
            d["info_bank"] += f(r.get("Сумма_УЕ"))
    return deals


def build(deals, rates=None):
    """Рядки таблиці + причини, чому угоди відсіялись.

    Винагорода додатково перераховується в ГРИВНЮ: для гривневих рахунків це сама сума,
    для валютних — сума × курс НБУ на день оплати рахунку (вимога користувачки 11.08.2026).
    """
    rates = {} if rates is None else rates
    rows, skipped = [], collections.Counter()
    for d in deals.values():
        if not d["n_inv"]:
            skipped["немає сплаченого рахунку клієнта на рахунки Юнітекса"] += 1
            continue
        profit = round(d["revenue_all"] - d["cost"], 2)
        add = round(d["info_bank"], 2) if d["info_bank"] > INFO_MIN else 0.0
        fee_uah, rate_shown, fee_ccy = 0.0, None, ""
        for ccy, val in d["fee_val"].items():
            rate = nbu_rate(ccy, d["fee_paid"].get(ccy, ""), rates)
            fee_uah += val * rate
            if ccy and ccy != "UAH":
                rate_shown, fee_ccy = round(rate, 4), ccy
            elif not fee_ccy:
                fee_ccy = ccy
        rows.append({
            "num": d["num"], "status": d["status"], "bl": d["bl"], "cont": d["cont"],
            "route": d["route"], "paid": d["paid"], "completed": d["completed"],
            "date": d["date"],
            "revenue": round(d["revenue_all"], 2), "cost": round(d["cost"], 2),
            "revenue_acc": round(d["revenue"], 2), "cost_acc": round(d["cost_acc"], 2),
            "cost_all": round(d["cost_all"], 2),
            "profit": profit, "fee": round(d["fee"], 2),
            "info_bank": round(d["info_bank"], 2), "info_added": add,
            "fee_val": round(sum(d["fee_val"].values()), 2), "fee_ccy": fee_ccy,
            "rate": rate_shown, "fee_uah": round(fee_uah, 2),
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
    rates = load_rates()
    rows, skipped = build(deals, rates)
    save_rates(rates)
    pos = [r for r in rows if r["diff"] > 0]
    print("угод переглянуто (статус не фільтрує): %d" % len(deals))
    print("з них із оплатою на %s: %d" % (" або ".join(ACCOUNTS), len(rows)))
    for k, n in skipped.most_common():
        print("   відсіяно — %s: %d" % (k, n))
    print("профіт > винагороди: %d угод, сума до переказу: %.2f УО" %
          (len(pos), sum(r["diff"] for r in pos)))
    print("інфо та комісії (сплачені): %.2f УО (додано в %d угодах)" %
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
        data = {"rows": rows, "account": ACCOUNT, "accounts": ACCOUNTS, "info_articles": sorted(INFO_ARTICLES),
                "info_min": INFO_MIN,
                "statuses": [STATUS_UK.get(s, s) for s in STATUSES] or ["будь-який статус"],
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
