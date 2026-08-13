#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Дозаповнити НАЗВУ СУДНА і ДАТИ там, де їх немає — тільки по Maersk.

НАВІЩО. У кабінеті клієнта 92 угоди з 278 стоять без назви судна. Джерело є
лише для тих, що йдуть Maersk і мають коносамент або контейнер, — це 25 угод,
і 24 з них уже доставлені (перевірено 13.08.2026).

⚠️ ЦЕЙ СКРИПТ ЧІПАЄ ДОСТАВЛЕНІ УГОДИ. Загальне правило (CLAUDE.md, п. 11) —
закрите не чіпати ніколи. Виняток зроблено ЗА ПРЯМОЮ ВКАЗІВКОЮ користувачки
13.08.2026: «зроби, будь ласка, по Маерску в 25 угод, навіть, якщо доставлено,
додай назви судна та дати». Ризик їй було названо до виконання.

ЩО САМЕ ЗАХИЩАЄ ВІД БІДИ (це не «обережність», це правила в коді):
1. Пишемо ЛИШЕ В ПОРОЖНІ поля. Жодне вже заповнене значення не змінюється —
   отже, ніщо, що вже потрапило у звіти і в розрахунки з клієнтом, не зсунеться.
2. Пишемо ЛИШЕ назву судна, рейс і ДАТИ (значення виду 2026-08-13). Статус,
   коносамент, порти, службові поля — не чіпаємо взагалі, навіть якщо трекінг
   їх повертає. Тобто «доставлено» не може перетворитись на щось інше.
3. Беремо тільки угоди з ПОРОЖНІМ «Судном». Угода, де судно вже стоїть, у
   вибірку не потрапляє.
4. Скасовані пропускаємо.
5. За замовчуванням — ПЕРЕДПОКАЗ. Запис лише з --apply.

Логіка подій НЕ дублюється: `collect_events` і `parse_events` беруться з
maersk_track_sync.py. Якщо там правлять розбір — тут він виправляється сам.

Запуск:
    python3 fill_vessel_maersk.py            # показати, що буде записано
    python3 fill_vessel_maersk.py --apply    # записати
"""
import argparse
import importlib.util
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SYNC = os.path.join(HERE, "maersk_track_sync.py")
if not os.path.exists(SYNC):
    SYNC = "/root/direct-sync/maersk_track_sync.py"
spec = importlib.util.spec_from_file_location("mts", SYNC)
MTS = importlib.util.module_from_spec(spec)
spec.loader.exec_module(MTS)

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}")
VESSEL_FIELDS = ("Судно", "Вояж")
# Службові поля: формально дати, але до перевезення стосунку не мають —
# у закриту угоду їх дописувати нема потреби.
NEVER = {"Остання зміна", "Останнє оновлення", "Статус (оновлено)",
         "Зміни ETA (історія)", "Звірка", "Трекінг (стан)", "Статус (джерело)"}


def is_empty(v):
    return str(v or "").strip() == ""


def wanted(field, value):
    """Чи це саме те, що дозволено записати: назва судна, рейс або дата."""
    if field in NEVER:
        return False
    if field in VESSEL_FIELDS:
        return bool(str(value or "").strip())
    return bool(DATE_RE.match(str(value or "").strip()))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="записати (без нього — лише показ)")
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()
    tag = "" if a.apply else "[передпоказ] "

    env = MTS.load_env()
    cancelled = MTS.cancelled_numbers()
    rows = MTS.nc_records()

    todo = []
    for r in rows:
        if not is_empty(r.get("Судно")):
            continue                                   # судно вже є — не чіпаємо
        if MTS.deal_no(r.get("Угода")) in cancelled:
            continue
        bl = str(r.get("BL") or "").strip()
        cont = str(r.get("Контейнер") or "").split(",")[0].strip()
        if not MTS.BL_RE.match(bl):
            bl = ""
        if not bl and not MTS.CONT_RE.match(cont.upper()):
            continue                                   # шукати нічим
        if "maersk" not in str(r.get("Лінія") or "").lower():
            continue                                   # інші лінії — API немає
        todo.append((bl, cont, r))
    if a.limit:
        todo = todo[: a.limit]

    print("%sУгод без судна, які можна спробувати по Maersk: %d" % (tag, len(todo)))
    dost = sum(1 for _, _, r in todo if str(r.get("Статус") or "") == MTS.DELIVERED)
    print("%sз них доставлених: %d (їх чіпаємо за прямою вказівкою від 13.08.2026)" % (tag, dost))
    print()

    token = MTS.maersk_token(env)
    if not token:
        sys.exit("Не вдалося отримати токен Maersk — нічого не роблю.")

    import datetime
    today_iso = datetime.date.today().isoformat()
    filled = nothing = failed = 0
    for bl, cont, r in todo:
        deal = str(r.get("Угода") or "?")
        events, how, note = MTS.collect_events(env, token, bl, cont)
        if not events:
            print("  %-5s — подій немає (%s)" % (deal, note or "порожня відповідь"))
            nothing += 1
            continue
        got = MTS.parse_events(events, r, today_iso)
        upd = {k: v for k, v in got.items()
               if wanted(k, v) and is_empty(r.get(k))}
        if not upd:
            print("  %-5s — нового нічого (подій %d, порожніх полів не заповнити)"
                  % (deal, len(events)))
            nothing += 1
            continue
        print("  %-5s %s%s" % (deal, "· ".join("%s=%s" % (k, v) for k, v in upd.items()),
                               "" if a.apply else "   ← буде записано"))
        if a.apply:
            st, js = MTS.nc("PATCH", "/api/v2/tables/%s/records" % MTS.TABLE,
                            [dict(upd, Id=r["Id"])])
            if st != 200:
                print("        ЗАПИС НЕ ПРОЙШОВ: %s %s" % (st, str(js)[:160]))
                failed += 1
                continue
        filled += 1

    print()
    print("%sПідсумок: заповнено %d, без змін %d, помилок запису %d"
          % (tag, filled, nothing, failed))
    if not a.apply:
        print("Це був лише показ. Щоб записати — той самий запуск із --apply.")


if __name__ == "__main__":
    main()
