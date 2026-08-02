#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Локальні витрати за кордоном: угоди, де ПРОФІТ більший за ВИНАГОРОДУ ЕКСПЕДИТОРА.

Навіщо: різницю між профітом і винагородою експедитора компанія переказує за кордон
як локальні витрати. У більшості угод ці витрати НЕ виділені окремою статтею в рахунку
клієнта, тому їх треба знаходити розрахунком по кожній угоді.

Джерело — 1С Експедитор (OData, лише читання). Нічого не змінює і не видаляє.

Формули (усі суми в УО = USD-еквівалент, як в Експедиторі):
    дохід(угода)   = Σ Document_Счет.сумма_УЕ                     (доходні рахунки угоди)
    витрати(угода) = Σ Document_РасходнаяНакладная.Сумма_УЕ       (тільки проведені)
    профіт         = дохід − витрати        ← формула звірена finrep з «Фактичним
                                              прибутком» Експедитора
    винагорода     = Σ рядків доходних рахунків (Document_Счет_ТЧ) зі статтею
                     «Винагорода експедитора»
    інфо+комісії   = Σ витратних рахунків зі статтями «Інфо» / «Банківські комісії»,
                     додається до профіту, якщо їх сума по угоді > INFO_MIN (10 УО)
    різниця        = профіт + інфо+комісії − винагорода           (тільки якщо > 0)

Запуск:
    python3 local_costs.py                 # рахує і пише computed/local_costs.json
    python3 local_costs.py --dry-run       # тільки показати підсумок, файл не писати
    python3 local_costs.py --check         # звірка профіту з period_report_data.json
"""
import argparse
import collections
import json
import os
import sys
import urllib.parse

BASE = "/root/unitex-finrep"
OUT = os.path.join(BASE, "computed", "local_costs.json")

# --- статті ---
# Довідник послуг Експедитора в OData НЕ опублікований, тому GUID статті визначається
# за описами в рядках доходних рахунків: беремо той GUID, у рядках якого найчастіше
# стоїть потрібна назва. Так номер статті не треба вписувати руками.
FEE_NAME = "Винагорода експедитора"
LOCAL_ABROAD_NAME = "Локальні витрати за кордоном"
# статті витратних рахунків «Інфо» і «Банківські комісії» — GUID підтверджує користувачка
INFO_BANK = []
INFO_MIN = 10.0                                        # поріг у УО (умова користувачки)

# Умова користувачки 02.08.2026: рахунок клієнту має бути СПЛАЧЕНИЙ і гроші мають прийти
# на один із ДВОХ рахунків Юнітекса — гривневий або євровий (уточнення: «бери тільки два —
# Юнітекс грн та євро»). Каси (Каса USD UFWD/UHD/Украмарин) і «Банк Юнітекс Форвардинг»
# НЕ рахуємо. Список саме точними назвами, щоб схожі рахунки (напр. «…Ейч-Ді Восток»)
# не потрапили сюди самі собою.
BANKS = {"Банк Юнітекс Ейч-Ді", "Банк Юнітекс Ейч-Ді EUR"}
PAID = "Оплачен"

STATUSES = ["Завершена", "ВыставленСчет"]              # + «Оброблена», якщо з'ясується
STATUS_UK = {"Завершена": "Завершена", "ВыставленСчет": "Виставлений рахунок",
             "Выполняется": "Виконується", "Букинг": "Букінг", "Отменена": "Скасована"}
NULL = "00000000-0000-0000-0000-000000000000"
EMPTY_DATE = "0001-01-01T00:00:00"


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


def article_guids(lines):
    """GUID статей за їхніми описами в рядках доходних рахунків."""
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


def collect(c, statuses, info_bank):
    deals = {}
    for r in page(c, "Document_Сделка",
                  ["Ref_Key", "Number", "Date", "Статус", "Posted", "DeletionMark",
                   "Коносамент", "ДомашнийКоносамент", "СписокКонтейнеров",
                   "ПунктОтправления", "ПунктНазначения", "ДатаЗавершения"]):
        if r.get("DeletionMark"):
            continue
        st = str(r.get("Статус") or "")
        if statuses and st not in statuses:
            continue
        deals[r["Ref_Key"]] = {
            "num": (r.get("Number") or "").lstrip("0"),
            "status": STATUS_UK.get(st, st),
            "bl": (r.get("Коносамент") or "").strip(),
            "cont": (r.get("СписокКонтейнеров") or "").strip(),
            "route": " → ".join(x for x in [(r.get("ПунктОтправления") or "").strip(),
                                            (r.get("ПунктНазначения") or "").strip()] if x),
            "date": d10(r.get("Date")),
            "completed": d10(r.get("ДатаЗавершения")),
            "revenue": 0.0, "cost": 0.0, "fee": 0.0, "local_abroad": 0.0,
            "info_bank": 0.0, "paid": "", "invoices": [], "pay_kinds": set(),
            "all_bank": True, "all_paid": True, "n_inv": 0,
        }

    # довідник видів оплати — щоб відрізнити банк від каси
    pay_names = {r["Ref_Key"]: (r.get("Description") or "").strip()
                 for r in page(c, "Catalog_ВидОплаты", ["Ref_Key", "Description"])}

    # доходні рахунки: сума по угоді + дата оплати від клієнта
    inv_deal = {}
    for r in page(c, "Document_Счет",
                  ["Ref_Key", "Number", "Сделка_Key", "сумма_УЕ", "ДатаОплаты", "СтатусСчета",
                   "Posted", "Информативный", "видОплаты_Key"]):
        dk = r.get("Сделка_Key")
        # чернетки й інформативні рахунки у розрахунок не входять — той самий фільтр,
        # що й у фінзвіті (engine/odata_ingest.ingest_income)
        if dk not in deals or not r.get("Posted") or r.get("Информативный"):
            continue
        inv_deal[r["Ref_Key"]] = dk
        d = deals[dk]
        kind = pay_names.get(r.get("видОплаты_Key"), "")
        d["pay_kinds"].add(kind or "(не вказано)")
        d["n_inv"] += 1
        if kind not in BANKS:
            d["all_bank"] = False
        if str(r.get("СтатусСчета") or "") != PAID:
            d["all_paid"] = False
        d["revenue"] += f(r.get("сумма_УЕ"))
        d["invoices"].append((r.get("Number") or "").lstrip("0"))
        pd = d10(r.get("ДатаОплаты"))
        if pd and pd > d["paid"]:
            d["paid"] = pd

    # рядки доходних рахунків: винагорода експедитора і вже виділені локальні витрати
    lines = page(c, "Document_Счет_ТЧ", ["Ref_Key", "Статья_Key", "Сумма_УЕ", "Описание"])
    art = article_guids(lines)
    fee_g, loc_g = art.get(FEE_NAME), art.get(LOCAL_ABROAD_NAME)
    if not fee_g:
        raise SystemExit("не знайдено статтю «%s» у рядках доходних рахунків" % FEE_NAME)
    for r in lines:
        dk = inv_deal.get(r.get("Ref_Key"))
        if not dk:
            continue
        if r.get("Статья_Key") == fee_g:
            deals[dk]["fee"] += f(r.get("Сумма_УЕ"))
        elif r.get("Статья_Key") == loc_g:
            deals[dk]["local_abroad"] += f(r.get("Сумма_УЕ"))

    # витратні рахунки: собівартість + окремо інфо та банківські комісії
    for r in page(c, "Document_РасходнаяНакладная",
                  ["Сделка_Key", "Сумма_УЕ", "Услуга_Key", "Posted"]):
        dk = r.get("Сделка_Key")
        if dk not in deals or not r.get("Posted"):
            continue
        deals[dk]["cost"] += f(r.get("Сумма_УЕ"))
        if r.get("Услуга_Key") in info_bank:
            deals[dk]["info_bank"] += f(r.get("Сумма_УЕ"))
    return deals


def build(deals):
    """Рядки таблиці + причини, чому угоди відсіялись.

    Беремо тільки ті угоди, де ВСІ доходні рахунки сплачені й гроші прийшли на
    банківський рахунок (вид оплати починається з «Банк»). Каси й несплачені —
    у таблицю не потрапляють (вимога користувачки 02.08.2026), але їхню кількість
    показуємо, щоб було видно, що саме відсіялось.
    """
    rows, skipped = [], collections.Counter()
    for d in deals.values():
        if not d["n_inv"]:
            skipped["без доходних рахунків"] += 1
            continue
        if not d["all_paid"]:
            skipped["рахунок не сплачений"] += 1
            continue
        if not d["all_bank"]:
            skipped["оплата не на рахунок Юнітекс грн/євро"] += 1
            continue
        profit = round(d["revenue"] - d["cost"], 2)
        add = round(d["info_bank"], 2) if d["info_bank"] > INFO_MIN else 0.0
        diff = round(profit + add - d["fee"], 2)
        rows.append({
            "num": d["num"], "status": d["status"], "bl": d["bl"], "cont": d["cont"],
            "route": d["route"], "paid": d["paid"], "completed": d["completed"],
            "date": d["date"],
            "revenue": round(d["revenue"], 2), "cost": round(d["cost"], 2),
            "profit": profit, "fee": round(d["fee"], 2), "info_bank": round(d["info_bank"], 2),
            "info_added": add, "local_abroad": round(d["local_abroad"], 2), "diff": diff,
            "pay_kinds": sorted(d["pay_kinds"]),
        })
    rows.sort(key=lambda r: -r["diff"])
    return rows, skipped


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--top", type=int, default=0)
    a = ap.parse_args()

    c = client()
    deals = collect(c, STATUSES, set(INFO_BANK))
    rows, skipped = build(deals)
    pos = [r for r in rows if r["diff"] > 0]
    print("угод у статусах %s: %d" % ("/".join(STATUS_UK.get(s, s) for s in STATUSES), len(deals)))
    print("з них підходять (сплачено на банківський рахунок): %d" % len(rows))
    for k, n in skipped.most_common():
        print("   відсіяно — %s: %d" % (k, n))
    print("з них профіт > винагороди: %d, сума до переказу: %.2f УО" %
          (len(pos), sum(r["diff"] for r in pos)))
    print("вже виділені «Локальні витрати за кордоном» у рахунках: %d угод, %.2f УО" %
          (sum(1 for r in rows if r["local_abroad"]), sum(r["local_abroad"] for r in rows)))
    by = collections.Counter(r["status"] for r in pos)
    print("розріз за статусом:", dict(by))
    if a.top:
        for r in pos[:a.top]:
            print("  №%-5s %-22s профіт %9.2f  винагорода %9.2f  різниця %9.2f" %
                  (r["num"], r["status"], r["profit"], r["fee"], r["diff"]))

    if a.check:
        p = os.path.join(BASE, "computed", "period_report_data.json")
        ref = {x["num"]: x for x in json.load(open(p, encoding="utf-8")).get("deals", [])}
        bad = [r for r in rows if r["num"] in ref and abs(ref[r["num"]]["profit"] - r["profit"]) > 1]
        print("звірка профіту з period_report_data.json: спільних угод %d, розбіжностей %d" %
              (sum(1 for r in rows if r["num"] in ref), len(bad)))
        for r in bad[:5]:
            print("   №%s: у звіті %.2f, у мене %.2f" % (r["num"], ref[r["num"]]["profit"], r["profit"]))

    if not a.dry_run:
        data = {"rows": rows, "info_bank_guids": INFO_BANK, "info_min": INFO_MIN,
                "statuses": [STATUS_UK.get(s, s) for s in STATUSES],
                "skipped": dict(skipped), "screened": len(deals),
                "total_diff": round(sum(r["diff"] for r in pos), 2), "count": len(pos)}
        with open(OUT, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False)
        print("записано:", OUT)


if __name__ == "__main__":
    main()
