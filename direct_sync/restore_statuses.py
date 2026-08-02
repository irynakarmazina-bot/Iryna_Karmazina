#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Повернути статуси, які синхронізація з Експедитором затерла на «Виконується».

Привід (02.08.2026): колонка «Статус» була авторитетною з боку Експедитора, тож
щоденний прогін о 07:00 перезаписував ручні правки і статуси від трекінгу
заглушкою «Виконується» («Выполняется»/«ВыставленСчет» нічого не кажуть про етап).
Саму причину виправлено в expeditor_direct_sync.py; цей скрипт лікує наслідки —
повертає ті значення, які реально стояли до перезапису.

ЗВІДКИ БЕРЕТЬСЯ «ПРАВИЛЬНИЙ» СТАТУС (нічого не вигадується):
  1. «Журнал дій» платформи — остання ручна зміна поля «Статус» для цієї угоди.
     Береться значення зі стовпця «Стало» (те, що поставила людина), якщо воно
     не «Виконується».
  2. Якщо в журналі нічого немає — угода лишається як є і потрапляє в перелік
     «джерела немає»: для ліній з трекінгом статус поверне сам трекер
     (maersk_track_sync.py / cosco_track_sync.py) за подіями перевізника.
Нічого не видаляється; «Вантаж доставлено» і «Скасована» не чіпаються.

Запуск:
    python3 /root/direct-sync/restore_statuses.py            # тільки показати
    python3 /root/direct-sync/restore_statuses.py --apply    # записати
"""
import argparse
import json
import urllib.error
import urllib.parse
import urllib.request

NC = "http://localhost:8080"
TABLE = "m58xsjo6at01ohl"                 # Диспетчеризація
AUDIT_TITLE = "Журнал дій"
TOKEN_FILE = "/root/nocodb-token.txt"
VAGUE = "Виконується"
UNTOUCHABLE = {"Вантаж доставлено", "Скасована"}

TOK = open(TOKEN_FILE).read().strip()


def nc(method, path, data=None):
    body = json.dumps(data, ensure_ascii=False).encode() if data is not None else None
    req = urllib.request.Request(NC + path, data=body, method=method,
                                 headers={"Content-Type": "application/json", "xc-token": TOK})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            raw = r.read().decode()
            return r.status, (json.loads(raw) if raw else {})
    except urllib.error.HTTPError as e:
        return e.code, {"err": e.read().decode()[:300]}
    except Exception as e:  # noqa: BLE001
        return 0, {"err": str(e)[:300]}


def records(table, fields=None, limit=200):
    out, off = [], 0
    q = ("&fields=" + urllib.parse.quote(",".join(fields), safe=",")) if fields else ""
    while True:
        st, js = nc("GET", "/api/v2/tables/%s/records?limit=%d&offset=%d%s" % (table, limit, off, q))
        if st != 200:
            raise SystemExit("READ_FAIL %s %s" % (st, js))
        out += js.get("list", [])
        if js.get("pageInfo", {}).get("isLastPage"):
            return out
        off += limit


def audit_table_id():
    """Знайти таблицю «Журнал дій» у тій самій базі, що й Диспетчеризація."""
    st, js = nc("GET", "/api/v2/meta/tables/%s" % TABLE)
    if st != 200:
        return None
    base = js.get("base_id") or js.get("project_id")
    if not base:
        return None
    st, js = nc("GET", "/api/v2/meta/bases/%s/tables" % base)
    if st != 200:
        return None
    for t in js.get("list", []):
        if t.get("title") == AUDIT_TITLE:
            return t["id"]
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="записати зміни (без нього — лише показ)")
    a = ap.parse_args()

    rows = records(TABLE, ["Id", "Угода", "Клієнт", "Лінія", "Статус", "Етап (Експедитор)", "ETA"])
    vague = [r for r in rows if str(r.get("Статус") or "").strip() == VAGUE]
    print("Угод зі статусом «%s»: %d (усього угод: %d)" % (VAGUE, len(vague), len(rows)))
    if not vague:
        return

    aud_id = audit_table_id()
    manual = {}          # номер угоди -> (значення, час, користувач)
    if aud_id:
        for e in records(aud_id, ["Час", "Користувач", "Дія", "Обʼєкт", "Поле", "Було", "Стало"]):
            if str(e.get("Поле") or "").strip() != "Статус":
                continue
            became = str(e.get("Стало") or "").strip()
            if not became or became == VAGUE:
                continue
            obj = str(e.get("Обʼєкт") or "")
            num = "".join(ch for ch in obj if ch.isdigit())
            if not num:
                continue
            when = str(e.get("Час") or "")
            prev = manual.get(num)
            if not prev or when > prev[1]:          # лишаємо найсвіжішу ручну зміну
                manual[num] = (became, when, str(e.get("Користувач") or ""))
    else:
        print("⚠ Таблицю «%s» не знайдено — ручних змін не бачу" % AUDIT_TITLE)

    patch, unknown = [], []
    for r in vague:
        num = str(r.get("Угода") or "").strip()
        got = manual.get(num)
        if got:
            patch.append((r, got))
        else:
            unknown.append(r)

    if patch:
        print("\nПОВЕРТАЮ (джерело — журнал дій платформи):")
        for r, (val, when, who) in patch:
            print("  угода %-5s %-22s %s → %-26s (поставив(ла) %s, %s)"
                  % (r.get("Угода"), (r.get("Клієнт") or "")[:22], VAGUE, val, who or "—", when[:16]))
    if unknown:
        print("\nДЖЕРЕЛА НЕМАЄ — лишаю «%s» (для ліній із трекінгом статус поверне трекер):" % VAGUE)
        for r in unknown:
            print("  угода %-5s %-22s лінія %-10s етап Експедитора: %s"
                  % (r.get("Угода"), (r.get("Клієнт") or "")[:22],
                     r.get("Лінія") or "—", r.get("Етап (Експедитор)") or "—"))

    if not a.apply:
        print("\n(показ; щоб записати — запусти з --apply)")
        return
    if not patch:
        print("\nНічого повертати")
        return
    body = [{"Id": r["Id"], "Статус": val} for r, (val, _, _) in patch
            if str(r.get("Статус") or "") not in UNTOUCHABLE]
    st, js = nc("PATCH", "/api/v2/tables/%s/records" % TABLE, body)
    print("\nЗапис: HTTP %s, оновлено %d угод" % (st, len(body) if st == 200 else 0))
    if st != 200:
        print(js)


if __name__ == "__main__":
    main()
