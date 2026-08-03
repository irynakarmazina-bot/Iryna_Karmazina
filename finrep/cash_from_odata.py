#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Залишки грошей по видах оплати з Експедитора (1С OData) → фінзвіт і Google-таблиця.

ЧОМУ ЦЕ ПРАЦЮЄ (перевірено 31.07.2026):
    вид оплати живе в СУБКОНТО регістру «Хозрасчетный», а не в реквізиті рядка.
    На `AccountingRegister_Хозрасчетный_RecordType` субконто немає за конструкцією 1С —
    його віддає окремий ресурс:
        {base}/AccountingRegister_Хозрасчетный/RecordsWithExtDimensions
    Він містить ExtDimensionDr1..3 / ExtDimensionCr1..3 — тобто вид оплати ОКРЕМО
    по дебету і по кредиту, що і потрібно для внутрішніх переміщень між касами.

ЗВІРЕНО з рідним звітом Експедитора «Аналіз грошових коштів → Залишки коштів
(по валют)» станом на 31.07.2026: усі 13 позицій і підсумок УО 81 009,81 — до копійки.

Формули:
    «Сума» (у валюті операції) = ВалютнаяСуммаDr − ВалютнаяСуммаCr
    «УО»                       = Сумма Dr − Сумма Cr   (реквізит «Сумма» вже в УО)
    рахунки грошей: 1110, 1210, 1220, 1300

Запуск:
    python3 engine/cash_from_odata.py --csv                # оновити normalized/cash_balances.csv
    python3 engine/cash_from_odata.py --sheet              # вивантажити в Google-таблицю
    python3 engine/cash_from_odata.py --csv --sheet
    python3 engine/cash_from_odata.py --sheet --dry-run    # показати, нічого не писати
    --date 2026-07-31                                      # станом на дату (типово сьогодні)

НІЧОГО НЕ ВИДАЛЯЄ: перед перезаписом CSV робить копію .bak-<дата-час>.
"""
import argparse
import collections
import csv
import datetime
import json
import os
import shutil
import sys
import urllib.parse
import urllib.request

BASE = "/root/unitex-finrep"
CSV_PATH = os.path.join(BASE, "normalized", "cash_balances.csv")
SHEET_TAB = "Імпорт_Залишки"
MONEY_ACCOUNTS = {"1110", "1210", "1220", "1300"}
REGISTER = "AccountingRegister_Хозрасчетный"
PAGE = 1000


def log(m):
    print(m, flush=True)


# ------------------------------------------------------------------ Експедитор
def odata():
    os.chdir(BASE)
    sys.path.insert(0, os.path.join(BASE, "engine"))
    from odata_client import ODataClient  # noqa: PLC0415
    return ODataClient()


def records(c):
    """Проводки регістру РАЗОМ із субконто, з пагінацією."""
    ent = urllib.parse.quote(REGISTER)
    out, skip = [], 0
    while True:
        url = "%s/%s/RecordsWithExtDimensions?$format=json&$top=%d&$skip=%d" % (c.url, ent, PAGE, skip)
        req = urllib.request.Request(url)
        req.add_header("Authorization", c._auth)          # noqa: SLF001
        with urllib.request.urlopen(req, timeout=300, context=c._ctx) as r:  # noqa: SLF001
            batch = json.loads(r.read().decode("utf-8", "replace")).get("value", [])
        out += batch
        if len(batch) < PAGE:
            return out
        skip += PAGE


def catalog(c, entity, key="Description"):
    return {x["Ref_Key"]: str(x.get(key) or "").strip()
            for x in c.list(entity, select=["Ref_Key", key])}


def compute(c, as_of):
    accounts = {a["Ref_Key"]: str(a.get("Code") or "").strip()
                for a in c.list("ChartOfAccounts_Хозрасчетный", select=["Ref_Key", "Code"])}
    kinds = catalog(c, "ChartOfCharacteristicTypes_ВидыСубконтоХозрасчетные")
    pay_type_keys = {k for k, v in kinds.items() if v == "ВидОплаты"}
    if not pay_type_keys:
        raise SystemExit("НЕ ЗНАЙДЕНО вид субконто «ВидОплаты» — перевір публікацію довідника")
    pay = catalog(c, "Catalog_ВидОплаты")
    cur = catalog(c, "Catalog_Валюты")

    rows = records(c)
    log("Проводок із субконто: %d" % len(rows))

    def payment_kind(rec, side):
        for i in (1, 2, 3):
            if str(rec.get("ExtDimensionType%s%d_Key" % (side, i))) in pay_type_keys:
                v = rec.get("ExtDimension%s%d" % (side, i))
                if isinstance(v, dict):
                    v = v.get("Ref_Key") or v.get("Key")
                return pay.get(str(v)) or str(v)
        return None

    amount = collections.defaultdict(float)
    amount_uo = collections.defaultdict(float)
    currency, no_kind, used = {}, 0, 0
    for rec in rows:
        if str(rec.get("Period"))[:10] > as_of:
            continue
        for side in ("Dr", "Cr"):
            acc_key = rec.get("AccountDr_Key") if side == "Dr" else rec.get("AccountCr_Key")
            if accounts.get(acc_key) not in MONEY_ACCOUNTS:
                continue
            used += 1
            kind = payment_kind(rec, side)
            if not kind:
                no_kind += 1
                continue
            sign = 1 if side == "Dr" else -1
            amount[kind] += sign * float(rec.get("ВалютнаяСумма" + side) or 0)
            amount_uo[kind] += sign * float(rec.get("Сумма") or 0)
            currency[kind] = cur.get(str(rec.get("Валюта%s_Key" % side))) or currency.get(kind, "")
    log("Грошових проводок: %d, без виду оплати в субконто: %d" % (used, no_kind))
    if no_kind:
        log("УВАГА: %d грошових проводок без виду оплати — залишки будуть неповні" % no_kind)
    return ({k: round(v, 2) for k, v in amount.items()},
            {k: round(v, 2) for k, v in amount_uo.items()},
            currency)


# ------------------------------------------------------------------ вивід
def previous_rows():
    """Старий CSV: щоб каси, які цього разу без рухів, не зникли зі звіту."""
    if not os.path.exists(CSV_PATH):
        return {}
    with open(CSV_PATH, encoding="utf-8") as f:
        return {r["cash_name"]: r for r in csv.DictReader(f)}


def table(amount, amount_uo, currency):
    prev = previous_rows()
    names = set(amount) | set(prev)
    out = []
    for nm in sorted(names, key=lambda s: s.lower()):
        if nm in amount:
            out.append([nm, currency.get(nm, ""), amount[nm], amount_uo[nm]])
        else:                                   # була в звіті, тепер без рухів → нуль
            out.append([nm, prev[nm].get("currency", ""), 0.0, 0.0])
    return out


def write_csv(rows, dry):
    if dry:
        log("DRY: CSV не пишу (%s)" % CSV_PATH)
        return
    if os.path.exists(CSV_PATH):
        bak = CSV_PATH + ".bak-" + datetime.datetime.now().strftime("%Y%m%d-%H%M")
        shutil.copy2(CSV_PATH, bak)
        log("Копія попереднього CSV: %s" % os.path.basename(bak))
    # Атомарний запис: спершу тимчасовий файл поруч, потім підміна одним рухом.
    # Раніше обрив посеред запису лишав би обрізаний CSV, а звіт прочитав би
    # неповні залишки кас і показав неправдиві цифри — мовчки.
    tmp_csv = CSV_PATH + ".tmp"
    with open(tmp_csv, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["cash_name", "currency", "amount", "amount_uo"])
        for nm, cu, a, u in rows:
            w.writerow([nm, cu, "%.2f" % a, "%.2f" % u])
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp_csv, CSV_PATH)
    log("CSV оновлено: %s (%d кас)" % (CSV_PATH, len(rows)))


# ------------------------------------------------------------------ Google-таблиця
def proxy(mode, range_=None, values=None, retries=4):
    """Той самий n8n-проксі, що й у engine/upload_sheets2.py (ключі Google — в n8n)."""
    cfg_path = os.path.join(BASE, os.environ.get("FINREP_CONFIG", "config.api.json"))
    with open(cfg_path, encoding="utf-8") as f:
        cfg = json.load(f)
    body = {"sheetId": cfg["spreadsheet_id"], "mode": mode}
    if range_ is not None:
        body["range"] = range_
    if values is not None:
        body["values"] = values
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    err = None
    for _ in range(retries):
        req = urllib.request.Request(cfg["n8n"]["webhook_url"], data=data,
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as e:  # noqa: BLE001
            err = e
    raise SystemExit("Google-таблиця недоступна: %s" % str(err)[:200])


def num(v):
    """Український формат — кома як десятковий розділювач (локаль таблиці uk_UA)."""
    return ("%.2f" % v).replace(".", ",")


def push_sheet(rows, as_of, dry):
    values = [["cash_name", "currency", "amount", "amount_uo"]]
    values += [[nm, cu, num(a), num(u)] for nm, cu, a, u in rows]
    if dry:
        log("DRY: у «%s» пішло б %d рядків (шапка + %d кас):" % (SHEET_TAB, len(values), len(rows)))
        for v in values[:6]:
            log("   " + " | ".join(str(x) for x in v))
        if len(values) > 6:
            log("   … ще %d" % (len(values) - 6))
        return
    # читаємо, скільки рядків там зараз — щоб прибрати ЛИШЕ зайвий хвіст, якщо кас стало менше
    old = proxy("read", "%s!A1:D2000" % SHEET_TAB).get("values") or []
    proxy("update", "%s!A1" % SHEET_TAB, values)
    tail = len(old) - len(values)
    if tail > 0:
        proxy("clear", "%s!A%d:D%d" % (SHEET_TAB, len(values) + 1, len(old)))
        log("Прибрано %d зайвих рядків у хвості (кас стало менше)" % tail)
    proxy("update", "%s!F1" % SHEET_TAB, [["станом на " + as_of]])
    log("Google-таблиця, аркуш «%s»: залито %d кас" % (SHEET_TAB, len(rows)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=datetime.date.today().isoformat(), help="станом на YYYY-MM-DD")
    ap.add_argument("--csv", action="store_true", help="оновити normalized/cash_balances.csv")
    ap.add_argument("--sheet", action="store_true", help="вивантажити в Google-таблицю")
    ap.add_argument("--dry-run", action="store_true", help="показати, нічого не писати")
    a = ap.parse_args()
    if not (a.csv or a.sheet):
        ap.error("вкажи --csv і/або --sheet")

    c = odata()
    amount, amount_uo, currency = compute(c, a.date)
    rows = table(amount, amount_uo, currency)

    log("")
    log("ЗАЛИШКИ станом на %s:" % a.date)
    log("%-30s %-5s %14s %14s" % ("Вид оплати", "Вал", "Сума", "УО"))
    for nm, cu, am, uo in rows:
        log("%-30s %-5s %14s %14s" % (nm[:30], cu, num(am), num(uo)))
    log("%-30s %-5s %14s %14s" % ("РАЗОМ", "", "", num(sum(r[3] for r in rows))))
    log("")

    if a.csv:
        write_csv(rows, a.dry_run)
    if a.sheet:
        push_sheet(rows, a.date, a.dry_run)
    log("CASH_OK кас=%d разом_УО=%s%s" % (len(rows), num(sum(r[3] for r in rows)),
                                          " (dry-run)" if a.dry_run else ""))


if __name__ == "__main__":
    main()
