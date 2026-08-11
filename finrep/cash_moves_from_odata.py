#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Рухи грошей з Експедитора (1С OData) → normalized/cash_moves.csv.

НАВІЩО
    До цього `cash_moves.csv` будував ТІЛЬКИ `engine/parse.py` — з ручних вивантажень
    Excel. Коли конвеєр перевели на API, `run.sh` став кликати
    `update_all_api.py --skip-parse`, і parse.py перестав запускатись — щоб не затерти
    свіжі API-дані старими файлами. Разом з ним перестали оновлюватись і рухи грошей:
    в `odata_ingest.py` вони свідомо не робились («чекаємо, поки розробник підкаже касу»).
    Наслідок, знайдений 11.08.2026: `cash_balances.csv` свіжий, а `cash_moves.csv` — від
    23.07, причому неповний і ВСЕРЕДИНІ покритого періоду (бракувало приходу 1 386,00
    від 11.05.2026). Усе, що читає рухи — фінзвіт, оплати Маерску, звірки — рахувало
    по мертвих даних і мовчало про це.

ЯК ПРАЦЮЄ
    Гроші й касу беремо з регістру «Хозрасчетный» (`RecordsWithExtDimensions`) — там
    вид оплати лежить у субконто ОКРЕМО по дебету і кредиту, тому внутрішні переміщення
    між касами видно з обох боків. Це той самий механізм, що вже працює в
    `cash_from_odata.py` для залишків і звірений з рідним звітом Експедитора.
    Реквізити (стаття, примітка, контрагент, рахунок постачальника, угода) добираємо
    з самих документів за посиланням `Recorder`.

    Рахунки грошей: 1110, 1210, 1220, 1300 — як у cash_from_odata.py.

ПОДВІЙНІ НОГИ
    Внутрішнє переміщення лишає в регістрі і дебетову, і кредитову ногу по одній касі
    (напр. 16.01.2026: кредит 742,59 двічі + дебет 742,59 один раз = чиста витрата
    742,59). Тому рухи згортаються по ключу дата+сума+контрагент+тип документа:
    прихід мінус витрата. Контроль — підсумкове сальдо по касі має збігтись із
    «Випискою банку» 1С.

БЕЗПЕКА
    * нічого не видаляє: перед перезаписом робить копію .bak-<дата-час>;
    * пише атомарно (тимчасовий файл + os.replace), щоб обрив не лишив обрізаний CSV;
    * `--dry-run` і `--compare` нічого не пишуть узагалі.

ЗАПУСК
    python3 engine/cash_moves_from_odata.py --compare   # порівняти з чинним, не писати
    python3 engine/cash_moves_from_odata.py --dry-run   # показати підсумки, не писати
    python3 engine/cash_moves_from_odata.py             # оновити normalized/cash_moves.csv
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

BASE = os.environ.get("FINREP_ROOT", "/root/unitex-finrep")
CSV_PATH = os.path.join(BASE, "normalized", "cash_moves.csv")
MONEY_ACCOUNTS = {"1110", "1210", "1220", "1300"}
REGISTER = "AccountingRegister_Хозрасчетный"
PAGE = 1000

# Колонки — точно ті самі й у тому самому порядку, що будував parse.py.
# Міняти порядок НЕ можна: цей CSV читають pnl_cf.py, consolidate.py,
# monthly_series.py, build_dashboard_data.py, maersk_payments.py та інші.
COLUMNS = ["document", "date", "payment_method", "counterparty", "supplier_invoice_ref",
           "deal", "vid", "operation", "currency", "income", "income_uo", "expense",
           "expense_uo", "supplier_invoice_ref2", "note", "category", "owner",
           "transfer_group_key", "transit_flag", "fx_bug_flag"]

# Тип документа → (український префікс представлення, назва операції за умовчанням).
# Префікс потрібен, бо parse.py збирає ключ групування плечей переміщення саме
# з рядка «Документ», і downstream-логіка на нього спирається.
DOC_KINDS = {
    "Document_СписаниеДенСредств": ("Списання ГК", "Списание (КРЕДИТОРКА)"),
    "Document_Приход": ("Надходження ГК", "Поступление (ДЕБИТОРКА)"),
    "Document_ВнутреннееПеремещение": ("Внутрішнє переміщення грошових коштів",
                                       "Перемещение из (ВП)"),
}


def log(m):
    print(m, flush=True)


def client():
    os.chdir(BASE)
    sys.path.insert(0, os.path.join(BASE, "engine"))
    from odata_client import ODataClient  # noqa: PLC0415
    return ODataClient()


def fetch(c, path):
    url = "%s/%s" % (c.url, path)
    req = urllib.request.Request(url)
    req.add_header("Authorization", c._auth)                      # noqa: SLF001
    with urllib.request.urlopen(req, timeout=300, context=c._ctx) as r:  # noqa: SLF001
        return json.loads(r.read().decode("utf-8", "replace")).get("value", [])


def catalog(c, entity, key="Description"):
    return {x["Ref_Key"]: str(x.get(key) or "").strip()
            for x in c.list(entity, select=["Ref_Key", key])}


def register(c):
    """Проводки регістру РАЗОМ із субконто, з пагінацією."""
    ent = urllib.parse.quote(REGISTER)
    out, skip = [], 0
    while True:
        batch = fetch(c, "%s/RecordsWithExtDimensions?$format=json&$top=%d&$skip=%d"
                      % (ent, PAGE, skip))
        out += batch
        if len(batch) < PAGE:
            return out
        skip += PAGE


def documents(c):
    """Ref_Key → реквізити платіжного документа (для всіх трьох типів)."""
    ops = catalog(c, "Catalog_ОперацииДокументов")
    vids = catalog(c, "Catalog_ВидыРасходов")
    contr = catalog(c, "Catalog_Контрагенты")
    cur = catalog(c, "Catalog_Валюты")
    out = {}
    for ent, (prefix, default_op) in DOC_KINDS.items():
        try:
            rows = fetch(c, "%s?$format=json" % urllib.parse.quote(ent))
        except Exception as e:  # noqa: BLE001
            log("УВАГА: %s недоступний (%s) — реквізити цих документів будуть порожні"
                % (ent, str(e)[:80]))
            continue
        for d in rows:
            date = str(d.get("Date") or "")[:19].replace("T", " ")
            out[str(d.get("Ref_Key"))] = {
                "document": "%s %s від %s" % (prefix, str(d.get("Number") or "").strip(), date),
                "operation": ops.get(str(d.get("Операция_Key"))) or default_op,
                "vid": vids.get(str(d.get("ВидРасхода_Key")), ""),
                "counterparty": contr.get(str(d.get("Контрагент_Key")), ""),
                "currency": cur.get(str(d.get("Валюта_Key")), ""),
                "note": str(d.get("Примечание") or "").strip(),
            }
        log("%-34s документів: %d" % (ent, len(rows)))
    return out


def invoice_refs(c):
    """Ref_Key документа → «Рахунок постачальника» з табличної частини «Счета»."""
    out = collections.defaultdict(list)
    for ent in ("Document_СписаниеДенСредств_Счета", "Document_Приход_Счета"):
        try:
            rows = fetch(c, "%s?$format=json&$select=%s"
                         % (urllib.parse.quote(ent), urllib.parse.quote("Ref_Key,Счет")))
        except Exception as e:  # noqa: BLE001
            log("УВАГА: %s недоступний (%s)" % (ent, str(e)[:70]))
            continue
        for r in rows:
            v = str(r.get("Счет") or "").strip()
            if v:
                out[str(r.get("Ref_Key"))].append(v)
    return {k: "; ".join(dict.fromkeys(v)) for k, v in out.items()}


def collect(c):
    accounts = {a["Ref_Key"]: str(a.get("Code") or "").strip()
                for a in c.list("ChartOfAccounts_Хозрасчетный", select=["Ref_Key", "Code"])}
    kinds = catalog(c, "ChartOfCharacteristicTypes_ВидыСубконтоХозрасчетные")
    pay_type_keys = {k for k, v in kinds.items() if v == "ВидОплаты"}
    if not pay_type_keys:
        raise SystemExit("НЕ ЗНАЙДЕНО вид субконто «ВидОплаты» — перевір публікацію довідника")
    pay = catalog(c, "Catalog_ВидОплаты")
    contr = catalog(c, "Catalog_Контрагенты")

    docs = documents(c)
    refs = invoice_refs(c)
    recs = register(c)
    log("Проводок із субконто: %d" % len(recs))

    def dim(rec, side, want):
        for i in (1, 2, 3):
            if str(rec.get("ExtDimensionType%s%d_Key" % (side, i))) in want:
                v = rec.get("ExtDimension%s%d" % (side, i))
                if isinstance(v, dict):
                    v = v.get("Ref_Key") or v.get("Key")
                return str(v)
        return None

    def any_counterparty(rec, side):
        for i in (1, 2, 3):
            v = rec.get("ExtDimension%s%d" % (side, i))
            if isinstance(v, dict):
                v = v.get("Ref_Key") or v.get("Key")
            if str(v) in contr:
                return contr[str(v)]
        return ""

    raw, no_kind = [], 0
    for rec in recs:
        for side in ("Dr", "Cr"):
            acc = rec.get("AccountDr_Key") if side == "Dr" else rec.get("AccountCr_Key")
            if accounts.get(acc) not in MONEY_ACCOUNTS:
                continue
            k = dim(rec, side, pay_type_keys)
            method = pay.get(k)
            if not method:
                no_kind += 1
                continue
            amt = round(float(rec.get("ВалютнаяСумма" + side) or 0), 2)
            uo = round(float(rec.get("Сумма") or 0), 2)
            if not amt and not uo:
                continue
            ref = str(rec.get("Recorder") or "")
            raw.append({
                "date": str(rec.get("Period") or "")[:10],
                "payment_method": method,
                "side": side,
                "amt": amt,
                "uo": uo,
                "ref": ref,
                "counterparty": any_counterparty(rec, side) or docs.get(ref, {}).get("counterparty", ""),
            })
    if no_kind:
        log("УВАГА: %d грошових проводок без виду оплати в субконто — вони пропущені" % no_kind)
    return raw, docs, refs


def net(raw):
    """Згортання подвійних ніг внутрішніх переміщень: прихід мінус витрата по ключу."""
    groups = collections.OrderedDict()
    for r in raw:
        key = (r["date"], r["payment_method"], r["amt"], r["uo"], r["ref"], r["counterparty"])
        groups.setdefault(key, {"n": 0, "row": r})
        groups[key]["n"] += 1 if r["side"] == "Dr" else -1
    out = []
    for key, g in groups.items():
        n = g["n"]
        if not n:
            continue
        r = dict(g["row"])
        r["side"] = "Dr" if n > 0 else "Cr"
        for _ in range(abs(n)):
            out.append(dict(r))
    return out


def rows_for_csv(moves, docs, refs):
    """Складання підсумкових рядків + категорії/власник силами самого parse.py."""
    sys.path.insert(0, os.path.join(BASE, "engine"))
    from parse import classify_owner, extract_doc_group_key  # noqa: PLC0415

    out = []
    for m in moves:
        d = docs.get(m["ref"], {})
        operation = d.get("operation", "")
        vid = d.get("vid", "")
        note = d.get("note", "")
        method = m["payment_method"]
        counterparty = m["counterparty"]
        document = d.get("document", "")

        owner = None
        if operation == "Поступление (ДЕБИТОРКА)":
            category = "client_payment"
        elif operation == "Списание (КРЕДИТОРКА)":
            category = "bank_fee" if vid == "Банківські послуги" else (
                "tax" if vid == "Податки" else "supplier_payment")
        elif operation == "Перемещение из (ВП)":
            category = "transfer"
        elif operation == "Взнос в уставной капитал":
            category, owner = "owner_contribution", classify_owner(method, note)
        elif operation == "Изъятие уставного капитала":
            category, owner = "owner_withdrawal", classify_owner(method, note)
        elif operation == "Ввод остатков денежных средств":
            category = "opening_balance"
        elif operation and "займ" in operation.lower():
            category = "loan"
        else:
            category = "other"

        # Форлайн Трейд: позикові рядки виключаються з аналізу — та сама умова, що в parse.py.
        if counterparty and "форлайн" in counterparty.lower():
            if (vid or "").strip() == "" or vid == "Фінансова допомога" or "займ" in operation.lower():
                category = "excluded_forlain_loan"

        income = m["amt"] if m["side"] == "Dr" else ""
        expense = m["amt"] if m["side"] == "Cr" else ""
        income_uo = m["uo"] if m["side"] == "Dr" else ""
        expense_uo = m["uo"] if m["side"] == "Cr" else ""
        out.append({
            "document": document,
            "date": m["date"],
            "payment_method": method,
            "counterparty": counterparty,
            "supplier_invoice_ref": refs.get(m["ref"], ""),
            "deal": "",
            "vid": vid,
            "operation": operation,
            "currency": d.get("currency", ""),
            "income": income,
            "income_uo": income_uo,
            "expense": expense,
            "expense_uo": expense_uo,
            "supplier_invoice_ref2": "",
            "note": note,
            "category": category,
            "owner": owner or "",
            "transfer_group_key": extract_doc_group_key(document) if category == "transfer" else "",
            "transit_flag": "",
            "fx_bug_flag": "",
        })
    out.sort(key=lambda r: (r["date"], r["payment_method"], r["document"]))
    return out


def num(v):
    s = str(v or "").replace(" ", "").replace(" ", "").replace(" ", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return 0.0


def compare(new_rows):
    """Порівняння з чинним CSV по касах — щоб побачити, що саме зміниться."""
    if not os.path.exists(CSV_PATH):
        log("Чинного CSV немає — порівнювати нема з чим")
        return
    old = list(csv.DictReader(open(CSV_PATH, encoding="utf-8")))
    log("\nЧИННИЙ CSV: %d рядків, дати %s .. %s"
        % (len(old), min(r["date"] for r in old), max(r["date"] for r in old)))
    log("НОВИЙ:      %d рядків, дати %s .. %s"
        % (len(new_rows), min(r["date"] for r in new_rows), max(r["date"] for r in new_rows)))

    def agg(rows):
        a = collections.defaultdict(lambda: [0.0, 0.0])
        for r in rows:
            a[r["payment_method"]][0] += num(r.get("income_uo"))
            a[r["payment_method"]][1] += num(r.get("expense_uo"))
        return a

    cut = max(r["date"] for r in old)
    ao, an = agg(old), agg([r for r in new_rows if r["date"] <= cut])
    log("\nПІДСУМКИ ПО КАСАХ у спільному періоді (до %s), У.О.:" % cut)
    log("%-28s %14s %14s %14s %14s" % ("каса", "старий +", "новий +", "старий −", "новий −"))
    bad = 0
    for k in sorted(set(ao) | set(an)):
        o, n = ao.get(k, [0, 0]), an.get(k, [0, 0])
        flag = "" if abs(o[0] - n[0]) < 0.5 and abs(o[1] - n[1]) < 0.5 else "  ← РОЗБІЖНІСТЬ"
        if flag:
            bad += 1
        log("%-28s %14.2f %14.2f %14.2f %14.2f%s" % (k, o[0], n[0], o[1], n[1], flag))
    log("\nКас із розбіжністю: %d з %d" % (bad, len(set(ao) | set(an))))


def verify_against_balances(c, rows):
    """ГОЛОВНА ПЕРЕВІРКА: сальдо, зібране з рухів, має збігтись із залишками по касах.

    Залишки рахуємо ЖИВИМ викликом cash_from_odata.compute() у цьому ж запуску, а НЕ
    читаємо normalized/cash_balances.csv. Причина (11.08.2026): файл на диску — це
    знімок на момент останнього натискання кнопки. Поки я звіряв, в Експедиторі завели
    переказ 163,00 з «Каса USD UHD» на «Каса USD Украмарин», і порівняння свіжих рухів
    зі знімком дворічної давності показало фальшиву розбіжність рівно на цю суму.
    Живий виклик порівнює однаковий момент часу — і сходиться по всіх касах.

    cash_from_odata звірений з рідним звітом Експедитора «Аналіз грошових коштів →
    Залишки коштів». Якщо рухи дають те саме сальдо — рухи повні. Якщо ні — у збирачі
    дірка, і чіпати cash_moves.csv НЕ можна.
    """
    sys.path.insert(0, os.path.join(BASE, "engine"))
    import cash_from_odata  # noqa: PLC0415
    as_of = datetime.date.today().isoformat()
    amount, _amount_uo, _cur = cash_from_odata.compute(c, as_of)
    want = {k: (v, 0.0) for k, v in amount.items()}
    got = collections.defaultdict(lambda: [0.0, 0.0])
    for r in rows:
        g = got[r["payment_method"]]
        g[0] += num(r.get("income")) - num(r.get("expense"))
        g[1] += num(r.get("income_uo")) - num(r.get("expense_uo"))
    log("\nПЕРЕВІРКА: сальдо з рухів проти живих залишків cash_from_odata (звіреного з 1С)")
    log("%-28s %13s %13s %10s" % ("каса", "з рухів", "залишок", "різниця"))
    bad = 0
    for k in sorted(set(want) | set(got)):
        w = want.get(k, (0.0, 0.0))[0]
        g = got.get(k, [0.0, 0.0])[0]
        d = round(g - w, 2)
        if abs(d) >= 0.01:
            bad += 1
        log("%-28s %13.2f %13.2f %10.2f%s" % (k, g, w, d, "  ← НЕ СХОДИТЬСЯ" if abs(d) >= 0.01 else ""))
    if bad:
        log("НЕ ЗІЙШЛОСЬ по %d касах — рухи неповні, писати CSV НЕ можна" % bad)
    else:
        log("Зійшлося по всіх %d касах — рухи повні" % len(set(want) | set(got)))
    return bad == 0


def write(rows, dry):
    if dry:
        log("DRY: CSV не пишу (%s)" % CSV_PATH)
        return
    if os.path.exists(CSV_PATH):
        bak = CSV_PATH + ".bak-" + datetime.datetime.now().strftime("%Y%m%d-%H%M")
        shutil.copy2(CSV_PATH, bak)
        log("Копія попереднього CSV: %s" % os.path.basename(bak))
    tmp = CSV_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(rows)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, CSV_PATH)
    log("CSV оновлено: %s (%d рухів)" % (CSV_PATH, len(rows)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="показати підсумки, нічого не писати")
    ap.add_argument("--compare", action="store_true", help="порівняти з чинним CSV, нічого не писати")
    a = ap.parse_args()

    c = client()
    raw, docs, refs = collect(c)
    moves = net(raw)
    log("Рухів після згортання подвійних ніг: %d (сирих проводок по касах: %d)"
        % (len(moves), len(raw)))
    rows = rows_for_csv(moves, docs, refs)

    tot_in = sum(num(r["income_uo"]) for r in rows)
    tot_out = sum(num(r["expense_uo"]) for r in rows)
    log("РАЗОМ У.О.: прихід %.2f  витрати %.2f  сальдо %.2f" % (tot_in, tot_out, tot_in - tot_out))

    ok = verify_against_balances(c, rows)
    compare(rows)
    if a.compare:
        log("\n--compare: нічого не записано")
        return
    if not ok:
        raise SystemExit("ЗУПИНКА: сальдо з рухів не збігається із залишками — CSV не змінено")
    write(rows, a.dry_run)


if __name__ == "__main__":
    main()
