#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Акаунти клієнтського кабінету: завести, заблокувати, видати новий пароль.

Запускається на сервері, у терміналі. Кабінет (server/cabinet.py) сам акаунтів
не створює — з інтернету завести собі доступ не може ніхто.

ПАРОЛЬ ВИДНО РІВНО ОДИН РАЗ — у цьому терміналі, у момент створення. У базі
лежить тільки scrypt-хеш; ні в журнал, ні в репозиторій, ні в чат пароль не
потрапляє. Клієнт міняє його на свій при першому вході (кабінет не пустить далі,
доки не змінить).

НАЗВА КОМПАНІЇ звіряється з довідником Експедитора ДОСЛІВНО. Це і є та сама
перевірка, яка потім щодня відбирає угоди: якщо тут вписати назву неточно,
клієнт побачить порожній кабінет або (гірше) назву, під яку підпадає дві фірми.
Тому неоднозначну назву скрипт не приймає — показує список і зупиняється.

ВИДАЛЕННЯ АКАУНТІВ ТУТ НЕМАЄ СВІДОМО. Доступ закривається `block` — акаунт
лишається, журнал за ним теж. Видалення рядків — окрема дія, тільки руками і
тільки після явного «так» (правило 6 у CLAUDE.md).

Приклади:
    python3 cabinet_admin.py clients
    python3 cabinet_admin.py add --email ivan@mirandor.ua --client "Мірандор" --name "Іван"
    python3 cabinet_admin.py list
    python3 cabinet_admin.py invite --email ivan@mirandor.ua   # клієнт сам створює пароль
    python3 cabinet_admin.py passwd --email ivan@mirandor.ua   # (старий спосіб) видати пароль
    python3 cabinet_admin.py block --email ivan@mirandor.ua
    python3 cabinet_admin.py log --limit 30
    python3 cabinet_admin.py log --client "Мірандор"     # хто з компанії заходив
"""
import argparse
import importlib.util
import os
import re
import secrets
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("cabinet", os.path.join(HERE, "cabinet.py"))
CAB = importlib.util.module_from_spec(spec)
spec.loader.exec_module(CAB)
BP = CAB.BP

# Без схожих між собою символів: пароль диктують менеджеру голосом і в месенджер,
# «l» проти «1» і «O» проти «0» дають найбільше невдалих перших входів.
ALPHABET = "abcdefghijkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s.]+\.[^@\s]+$")


def gen_password(groups=3, size=4):
    return "-".join("".join(secrets.choice(ALPHABET) for _ in range(size))
                    for _ in range(groups))


def client_names():
    """Назви компаній з угод + скільки в кожної активних угод."""
    counts = {}
    for r in BP.nc_all():
        name = BP.nz(r.get("Клієнт"))
        if name and BP.nz(r.get("Статус")) != BP.CANCELLED:
            counts[name] = counts.get(name, 0) + 1
    return counts


def resolve_client(name):
    """Точна назва компанії або зупинка. Те саме правило, що в pick_client()."""
    counts = client_names()
    want = BP.nz(name).lower()
    if not want:
        sys.exit("ПОМИЛКА: не вказано компанію (--client).")
    exact = [n for n in counts if n.lower() == want]
    if exact:
        return exact[0], counts[exact[0]]
    near = sorted(n for n in counts if want in n.lower())
    if len(near) == 1:
        print("УВАГА: точного збігу «%s» немає, однозначно підходить «%s»." % (name, near[0]))
        return near[0], counts[near[0]]
    if len(near) > 1:
        sys.exit("ПОМИЛКА: під «%s» підпадає кілька компаній:\n  %s\n"
                 "Впишіть назву точно — інакше клієнт побачить чужі угоди."
                 % (name, "\n  ".join(near)))
    sys.exit("ПОМИЛКА: компанії «%s» немає серед угод. Перевірте назву "
             "(список: python3 cabinet_admin.py clients)." % name)


def cmd_clients(_a):
    counts = client_names()
    print("Компанії з активними угодами — %d:" % len(counts))
    for name in sorted(counts, key=lambda n: -counts[n]):
        print("  %4d  %s" % (counts[name], name))


def cmd_add(a):
    email = (a.email or "").strip().lower()
    if not EMAIL_RE.match(email):
        sys.exit("ПОМИЛКА: «%s» не схоже на адресу пошти." % a.email)
    client, n_deals = resolve_client(a.client)
    con = CAB.db()
    if con.execute("SELECT 1 FROM accounts WHERE email=?", (email,)).fetchone():
        con.close()
        sys.exit("ПОМИЛКА: акаунт %s уже є. Новий пароль — командою passwd." % email)
    pwd = gen_password()
    con.execute("INSERT INTO accounts(email,client,name,pwd,active,must_change,created) "
                "VALUES(?,?,?,?,1,1,?)",
                (email, client, (a.name or "").strip(), CAB.hash_pwd(pwd), CAB.now()))
    con.commit()
    con.close()
    CAB.audit(email, client, "акаунт створено", "з терміналу", "")
    print("\n  Акаунт створено.")
    print("  Пошта:     %s" % email)
    print("  Компанія:  %s  (активних угод: %d)" % (client, n_deals))
    print("  Пароль:    %s" % pwd)
    print("\n  Пароль показується ОДИН раз — передайте його клієнту і не зберігайте")
    print("  у переписці. При першому вході кабінет попросить придумати свій.\n")


def cmd_list(_a):
    con = CAB.db()
    rows = con.execute(
        "SELECT a.*, (SELECT COUNT(*) FROM sessions s WHERE s.email=a.email) AS live "
        "FROM accounts a ORDER BY a.client, a.email").fetchall()
    con.close()
    if not rows:
        return print("Акаунтів ще немає.")
    print("%-34s %-26s %-9s %-19s %s" % ("ПОШТА", "КОМПАНІЯ", "СТАН", "ОСТАННІЙ ВХІД", "СЕСІЙ"))
    for r in rows:
        state = "заблок." if not r["active"] else ("новий" if r["must_change"] else "робочий")
        print("%-34s %-26s %-9s %-19s %d"
              % (r["email"][:34], r["client"][:26], state,
                 (r["last_login"] or "—")[:19], r["live"]))


def _must_exist(con, email):
    row = con.execute("SELECT * FROM accounts WHERE email=?", (email,)).fetchone()
    if not row:
        con.close()
        sys.exit("ПОМИЛКА: акаунта %s немає." % email)
    return row


def cmd_passwd(a):
    email = (a.email or "").strip().lower()
    con = CAB.db()
    row = _must_exist(con, email)
    pwd = gen_password()
    con.execute("UPDATE accounts SET pwd=?,must_change=1 WHERE email=?",
                (CAB.hash_pwd(pwd), email))
    con.commit()
    con.close()
    CAB.sessions_drop_email(email)          # старі входи обриваємо одразу
    CAB.audit(email, row["client"], "виданий новий пароль", "з терміналу", "")
    print("\n  Новий тимчасовий пароль для %s: %s" % (email, pwd))
    print("  Усі відкриті сесії цього акаунта закриті.\n")


def cmd_block(a):
    email = (a.email or "").strip().lower()
    con = CAB.db()
    row = _must_exist(con, email)
    con.execute("UPDATE accounts SET active=0 WHERE email=?", (email,))
    con.commit()
    con.close()
    CAB.sessions_drop_email(email)
    CAB.audit(email, row["client"], "акаунт заблоковано", "з терміналу", "")
    print("Заблоковано: %s. Акаунт і журнал збережені." % email)


def cmd_unblock(a):
    email = (a.email or "").strip().lower()
    con = CAB.db()
    row = _must_exist(con, email)
    con.execute("UPDATE accounts SET active=1 WHERE email=?", (email,))
    con.commit()
    con.close()
    CAB.audit(email, row["client"], "акаунт розблоковано", "з терміналу", "")
    print("Розблоковано: %s" % email)


def cmd_kick(a):
    email = (a.email or "").strip().lower()
    CAB.sessions_drop_email(email)
    CAB.audit(email, "", "сесії закриті", "з терміналу", "")
    print("Усі відкриті сесії %s закриті. Акаунт не змінено." % email)


def cmd_invite(a):
    """Одноразове посилання: клієнт сам придумує пароль.

    Пароль після цього не існує ніде, крім голови клієнта, і зберігати нам
    нічого. Посилання показується РІВНО ОДИН РАЗ — воно й є доступ, тому
    поводитись із ним треба як із паролем: передати клієнту напряму і не
    лишати в переписці.
    """
    email = (a.email or "").strip().lower()
    con = CAB.db()
    row = _must_exist(con, email)
    con.close()
    if not row["active"]:
        sys.exit("ПОМИЛКА: акаунт %s заблокований. Спершу unblock." % email)
    token, exp = CAB.invite_new(email, a.hours)
    CAB.audit(email, row["client"], "створено посилання на пароль",
              "діє до %s" % exp, "")
    print("\n  Посилання для %s (%s):" % (email, row["client"]))
    print("  https://cabinet.unitex.od.ua/set?t=%s" % token)
    print("\n  Діє до %s, спрацьовує ОДИН раз." % exp)
    print("  Попередні невикористані посилання цього акаунта більше не діють.\n")


def cmd_log(a):
    """Журнал: увесь, по людині (--email) або по компанії (--client).

    Відбір за компанією потрібен, бо на одну компанію буває кілька людей
    (вимога користувачки 14.08.2026), і питання зазвичай звучить «хто з
    Мірандора заходив», а не «що робив конкретно Іван».
    """
    con = CAB.db()
    if a.email:
        rows = con.execute("SELECT * FROM audit WHERE email=? ORDER BY id DESC LIMIT ?",
                           (a.email.strip().lower(), a.limit)).fetchall()
    elif a.client:
        rows = con.execute("SELECT * FROM audit WHERE lower(client)=lower(?) "
                           "ORDER BY id DESC LIMIT ?", (a.client.strip(), a.limit)).fetchall()
    else:
        rows = con.execute("SELECT * FROM audit ORDER BY id DESC LIMIT ?", (a.limit,)).fetchall()
    con.close()
    if not rows:
        return print("Журнал порожній.")
    for r in reversed(rows):
        print("%s  %-28s %-22s %-20s %-15s %s"
              % (r["ts"], (r["email"] or "—")[:28], r["action"][:22],
                 (r["client"] or "—")[:20], (r["ip"] or "—")[:15], r["detail"] or ""))


def main():
    ap = argparse.ArgumentParser(description="Акаунти клієнтського кабінету")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("clients", help="які компанії є в угодах").set_defaults(fn=cmd_clients)
    sub.add_parser("list", help="список акаунтів").set_defaults(fn=cmd_list)

    p = sub.add_parser("add", help="завести акаунт клієнта")
    p.add_argument("--email", required=True)
    p.add_argument("--client", required=True, help="назва компанії як в Експедиторі")
    p.add_argument("--name", default="", help="ім'я людини (для журналу)")
    p.set_defaults(fn=cmd_add)

    for name, fn, helptext in (("passwd", cmd_passwd, "видати новий тимчасовий пароль"),
                               ("block", cmd_block, "закрити доступ"),
                               ("unblock", cmd_unblock, "повернути доступ"),
                               ("kick", cmd_kick, "закрити відкриті сесії")):
        p = sub.add_parser(name, help=helptext)
        p.add_argument("--email", required=True)
        p.set_defaults(fn=fn)

    p = sub.add_parser("invite", help="одноразове посилання: клієнт сам створює пароль")
    p.add_argument("--email", required=True)
    p.add_argument("--hours", type=int, default=CAB.INVITE_HOURS)
    p.set_defaults(fn=cmd_invite)

    p = sub.add_parser("log", help="журнал дій у кабінеті")
    p.add_argument("--limit", type=int, default=40)
    p.add_argument("--email", default="", help="лише по цій людині")
    p.add_argument("--client", default="", help="лише по цій компанії")
    p.set_defaults(fn=cmd_log)

    a = ap.parse_args()
    CAB.init_db()
    a.fn(a)


if __name__ == "__main__":
    main()
