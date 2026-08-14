# -*- coding: utf-8 -*-
"""Видалити ОДИН рядок таблиці «Диспетчеризація» — Id=189, угода 242.

Дозвіл користувачки отримано 14.08.2026 («видаляй рядок скасованої угоди») після того,
як я назвала точний рядок: Id=189, угода 242, статус «Скасована», клієнт ЮЕЙ ТРЕЙД.
Причина: цієї угоди в Експедиторі немає взагалі, а синхронізація рядки не видаляє,
тому вона висіла в таблиці попри всі оновлення.

Запобіжники (правило 6):
  * видаляється РІВНО один рядок за конкретним Id, ніяких шаблонів і масових операцій;
  * перед видаленням звіряємо: Id збігається, номер угоди = 242, і цієї угоди справді
    немає серед живих угод 1С. Якщо хоч одна перевірка не пройшла — СТОП, нічого не робимо;
  * повна копія рядка зберігається у файл ДО видалення.
"""
import json, os, sys, types, urllib.request

NC = "http://localhost:8080"
TABLE = "m58xsjo6at01ohl"
TOK = open("/root/nocodb-token.txt").read().strip()
ROW_ID = 189
DEAL = "242"
BACKUP = "/root/direct-sync/deleted_row_%d_deal_%s.json" % (ROW_ID, DEAL)


def nc(method, path, data=None):
    body = json.dumps(data, ensure_ascii=False).encode() if data is not None else None
    req = urllib.request.Request(NC + path, data=body, method=method,
                                 headers={"Content-Type": "application/json", "xc-token": TOK})
    with urllib.request.urlopen(req, timeout=60) as r:
        raw = r.read().decode()
        return json.loads(raw) if raw else {}


row = nc("GET", "/api/v2/tables/%s/records/%d" % (TABLE, ROW_ID))
got = str(row.get("Угода") or "").strip()
print("знайдено рядок Id=%s, угода=%s, статус=%s, клієнт=%s" %
      (row.get("Id"), got, row.get("Статус"), row.get("Клієнт")))
if str(row.get("Id")) != str(ROW_ID) or got != DEAL:
    sys.exit("СТОП: рядок не той, якого я очікувала — нічого не видаляю")

# звірка з 1С: угоди 242 не має бути серед живих
src = open("/root/unitex-finrep/engine/local_costs.py", encoding="utf-8").read().replace(
    'if __name__ == "__main__":\n    main()', "")
m = types.ModuleType("lc"); exec(compile(src, "lc", "exec"), m.__dict__)
live = {(x.get("Number") or "").lstrip("0") for x in
        m.page(m.client(), "Document_Сделка", ["Number", "DeletionMark"]) if not x.get("DeletionMark")}
if DEAL in live:
    sys.exit("СТОП: угода %s Є в Експедиторі — видаляти не можна" % DEAL)
print("звірка з 1С: угоди %s серед живих немає — можна видаляти" % DEAL)

with open(BACKUP, "w", encoding="utf-8") as fh:
    json.dump(row, fh, ensure_ascii=False, indent=1)
os.chmod(BACKUP, 0o600)
print("копія рядка збережена:", BACKUP)

nc("DELETE", "/api/v2/tables/%s/records" % TABLE, [{"Id": ROW_ID}])
print("рядок Id=%d видалено" % ROW_ID)

# перевірка після
js = nc("GET", "/api/v2/tables/%s/records?limit=1000" % TABLE)
rows = js.get("list", [])
still = [r for r in rows if str(r.get("Угода") or "").strip() == DEAL]
print("рядків у таблиці тепер: %d · угода %s: %s" %
      (len(rows), DEAL, "ще є (!)" if still else "більше немає"))
