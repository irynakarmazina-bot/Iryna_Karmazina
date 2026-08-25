#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Локальні витрати за кордоном: різниця між профітом і винагородою експедитора.

Навіщо: те, що лишається по угоді після всіх витрат і після винагороди експедитора, —
це локальні витрати за кордоном, які треба переказати. Окремою статтею в рахунку клієнта
вони здебільшого не виділені, тому рахуємо.

⚠️ ФОРМУЛА КОРИСТУВАЧКИ (остаточна, 25.08.2026): «різниця між винагородою та ЗАЛИШКОМ
на рахунку, до якого додаються банківські комісії та податок». Тобто:
  * витрати беремо ТІЛЬКИ ФАКТИЧНО ОПЛАЧЕНІ (це «Залишок» = приплив − відтік в 1С);
  * комісії та податки — операційні витрати компанії, вони НЕ мають зменшувати суму
    до переказу, тому додаються назад;
  * і аж тоді віднімається винагорода експедитора.

Формули (усі суми в УО = USD-еквівалент, як в Експедиторі). Скрізь «рахунки Ейч-Ді»
означає «всі види оплати, КРІМ Банк Юнітекс Форвардинг» (див. EXCLUDE_ACCOUNTS):
    надходження = Σ СПЛАЧЕНИХ доходних рахунків угоди на рахунки Ейч-Ді
                  (проведених, не інформативних)
    витрати     = Σ витратних рахунків угоди зі статусом «Оплачен» з рахунків Ейч-Ді
    профіт      = надходження − витрати        ← це «Залишок» в Експедиторі
    винагорода  = рядки цих доходних рахунків зі статтею «Винагорода експедитора»
    комісії+податки = оплачені витратні рахунки зі статтями INFO_ARTICLES —
                  додаються назад до профіту (порогу немає)
    різниця     = профіт + інфо+комісії − винагорода       (у таблицю — тільки додатні)

ЗВІРКА З ФАКТОМ. Користувачка надіслала 16 угод, по яких локальні витрати вже сплачені,
з точними сумами (разом 10 095 УО). Поточна формула дає по цих 16 угодах 9 178 УО
(−917, 15 угод із 16 додатні; вибивається тільки угода 21: −565).
Що перевірялось по дорозі й чому відкинуто:
    • надходження на рахунки Юнітекса − витрати з ЦИХ ЖЕ рахунків .... 54 715 (×4 завищує)
    • дохід тільки з 2 рахунків (грн+EUR) − УСІ оплачені витрати ...... 3 763 (несиметрично:
      доходи звужені до двох рахунків, а витрати віднімались усі)
    • увесь дохід угоди − оплачені витрати + комісії − винагорода ..... 9 309
    • дохід без ЮФ − витрати без ЮФ + комісії − винагорода ........... 9 178 ← рахуємо так

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

# --- ЯК ВІДРІЗНИТИ ЮНІТЕКС ФОРВАРДИНГ ---
# Пряма відповідь користувачки 25.08.2026 на питання «де шукати рахунки, виставлені
# від Юнітекс Форвардинг»: **«вид оплати Банк Юнітекс Форвардинг»**.
# Тобто ознака ЮФ у цій базі — САМЕ ВИД ОПЛАТИ, а не реквізит «Организация»
# (перевірено того ж дня: у ВСІХ 353 доходних і 1171 витратному рахунку
# Организация = «Юнітекс Ейч-Ді», тож за цим полем ЮФ не видно взагалі).
# Правило застосовується СИМЕТРИЧНО — і до доходів, і до витрат:
# «Рахунки від Юнітекс Форвардинг та витрати з ними повʼязані ти не береш».
EXCLUDE_ACCOUNTS = {"Банк Юнітекс Форвардинг"}
# ⚠️ У довіднику є ще «Каса UAH UFWD» і «Каса USD UFWD» — це теж каси Форвардинга,
# але користувачка назвала тільки банківський рахунок, тому вони НЕ виключаються.
# Спитати, коли буде нагода (по 16 звіреним угодам їх виключення погіршувало збіг).

# Усе, що не ЮФ, — це рахунки Ейч-Ді. Раніше тут був список із двох рахунків
# (грн + EUR), і через це доходи, які прийшли на інші рахунки Ейч-Ді (USD, Восток,
# каси), у розрахунок не потрапляли, тоді як витрати з тих самих рахунків віднімались.
# Через цю несиметричність залишок по частині угод виходив відʼємним. 25.08.2026
# виправлено: беремо всі сплачені рахунки, крім ЮФ.
ACCOUNT = "усі рахунки Юнітекс Ейч-Ді (крім Юнітекс Форвардинг)"   # для підписів

# --- статті (довідник Catalog_СтатьиСчета опублікований Софт Про 02.08.2026) ---
FEE_NAME = "Винагорода експедитора"
LOCAL_ABROAD_NAME = "Локальні витрати за кордоном"
# Що додається назад до залишку: банківські комісії, перекази, інфо І ПОДАТКИ
# («до якого додаються банківські комісії та податок» — 25.08.2026).
# ПДВ сюди НЕ входить: він стосується тільки Юнітекс Форвардинг, якого ми не беремо
# (уточнення користувачки 25.08.2026: «інфо правильно, пдв — ні»).
INFO_ARTICLES = {"Інфо", "Комісія за переказ", "Банківський переказ", "Свіфт переказ",
                 "Єдиний податок", "Військовий збір з платника Єдиного 3 гр"}
INFO_MIN = 0.0                        # порогу немає: додаємо все, що було віднято

# ВІДБІР УГОД (уточнення користувачки 25.08.2026): «Ти дивишся ТІЛЬКИ на закриті угоди,
# де вказано дохід, витрати та стоїть галочка Нарахований прибуток. Ти оцінюєш ТІЛЬКИ
# ці цифри.» Галочка в 1С — реквізит `обработана` («Оброблена (нарахований прибуток)»);
# перевірено 25.08.2026: вона стоїть рівно в 144 угодах, і всі вони зі статусом «Завершена».
PROCESSED_ONLY = True                 # брати лише угоди з цією галочкою
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
                  ["Ref_Key", "Number", "Date", "Статус", "DeletionMark", "обработана",
                   "Коносамент", "СписокКонтейнеров", "ПунктОтправления", "ПунктНазначения",
                   "ДатаЗавершения"]):
        if r.get("DeletionMark") or (STATUSES and str(r.get("Статус") or "") not in STATUSES):
            continue
        if PROCESSED_ONLY and not r.get("обработана"):
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
            "cost_fwd": 0.0, "revenue_fwd": 0.0,
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
        if acc.get(r.get("видОплаты_Key")) in EXCLUDE_ACCOUNTS:
            d["revenue_fwd"] += f(r.get("сумма_УЕ"))      # довідково: дохід ЮФ
            continue
        if str(r.get("СтатусСчета") or "") != PAID:
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
                   "СтатусСчета", "Организация_Key"]):
        dk = r.get("Сделка_Key")
        if dk not in deals or not r.get("Posted"):
            continue
        d = deals[dk]
        if acc.get(r.get("ВидОплаты_Key")) in EXCLUDE_ACCOUNTS:
            d["cost_fwd"] += f(r.get("Сумма_УЕ"))         # витрати Форвардинга — довідково
            continue
        d["cost_all"] += f(r.get("Сумма_УЕ"))             # довідково: всі проведені витрати
        if str(r.get("СтатусСчета") or "") == PAID:
            d["cost_acc"] += f(r.get("Сумма_УЕ"))         # довідково: витрати з наших рахунків
        if str(r.get("СтатусСчета") or "") != PAID:
            continue                                      # неоплачене грошима ще не пішло
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
        profit = round(d["revenue"] - d["cost"], 2)   # дохід ТІЛЬКИ з рахунків Ейч-Ді
        add = round(d["info_bank"], 2) if d["info_bank"] > INFO_MIN else 0.0   # поріг 0
        fee_uah, rate_shown, fee_ccy = 0.0, None, ""
        for ccy, val in d["fee_val"].items():
            rate = nbu_rate(ccy, d["fee_paid"].get(ccy, ""), rates)
            fee_uah += val * rate
            if ccy and ccy != "UAH":
                rate_shown, fee_ccy = round(rate, 4), ccy
            elif not fee_ccy:
                fee_ccy = ccy
        if round(profit + add - d["fee"], 2) < 0:
            # «мінусові угоди не включай» (25.08.2026): якщо різниця відʼємна — угода
            # у звіт не потрапляє взагалі
            skipped["різниця відʼємна"] += 1
            continue
        rows.append({
            "num": d["num"], "status": d["status"], "bl": d["bl"], "cont": d["cont"],
            "route": d["route"], "paid": d["paid"], "completed": d["completed"],
            "date": d["date"],
            "revenue": round(d["revenue_all"], 2), "cost": round(d["cost"], 2),
            "revenue_acc": round(d["revenue"], 2), "cost_acc": round(d["cost_acc"], 2),
            "cost_all": round(d["cost_all"], 2), "cost_fwd": round(d["cost_fwd"], 2),
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
    print("угод із галочкою «Оброблена (нарахований прибуток)»: %d" % len(deals))
    print("з них із оплатою клієнта (не через ЮФ): %d" % len(rows))
    for k, n in skipped.most_common():
        print("   відсіяно — %s: %d" % (k, n))
    print("профіт > винагороди: %d угод, сума до переказу: %.2f УО" %
          (len(pos), sum(r["diff"] for r in pos)))
    print("комісії та податки, додані назад: %.2f УО (у %d угодах)" %
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
        data = {"rows": rows, "account": ACCOUNT, "accounts": sorted(EXCLUDE_ACCOUNTS), "info_articles": sorted(INFO_ARTICLES),
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
