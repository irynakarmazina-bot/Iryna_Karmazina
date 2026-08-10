#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Перевірка правил прошарку — без сервера, без мережі, без бази.

Перевіряється саме те, заради чого прошарок і робиться: що рішення «можна/не
можна» збігається з тим, що показує фасад, і що в сумнівному випадку відповідь
«ні», а не «пропустити».

Запуск: python3 scripts/gateway_rules.py     (0 = всі пройшли, 1 = є падіння)
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "server"))
import gateway as G  # noqa: E402

DISP = "/api/v2/tables/m58xsjo6at01ohl/records?limit=1000"
CALC = "/api/v2/tables/mxtg3fvrmtflaid/records?limit=1000"
JOURNAL = "/api/v2/tables/m429u2crlavfmxc/records"
USERS = "/api/v2/tables/meqpi0r197bz14n/records"
LOGIN = "/api/v1/auth/user/signin"
UNKNOWN = "/api/v2/tables/mZZZZZZZZZZZZZZ/records"

# (опис, метод, адреса, роль, ім'я, чекаємо_дозвіл, чекаємо_обмеження_по_полю)
CASES = [
    # --- головне: чуже не видно навіть при прямому запиті в обхід сторінки
    ("менеджер тягне ВСІ угоди прямим запитом → лише свої",
     "GET", DISP, "Сейлз-менеджер", "Іван", True, "Менеджер"),
    ("операційний тягне всі угоди → лише свої, інше поле",
     "GET", DISP, "Операційний менеджер", "Іван", True, "Оп. менеджер"),
    ("менеджер тягне калькуляції → лише свої",
     "GET", CALC, "Сейлз-менеджер", "Іван", True, "Менеджер"),
    ("адміністратор тягне всі угоди → без обмеження",
     "GET", DISP, "Адміністратор", "Ірина", True, None),

    # --- таблиці, яких роль не бачить
    ("логіст лізе в калькуляції → ні", "GET", CALC, "Логіст", "Петро", False, None),
    ("фінансист лізе в калькуляції → ні (у nav немає calc з 11.08)",
     "GET", CALC, "Фінансист", "Оля", False, None),
    ("операційний лізе в калькуляції → ні (у nav немає calc)",
     "GET", CALC, "Операційний менеджер", "Іван", False, None),
    ("логіст лізе в клієнтів → ні", "GET", "/api/v2/tables/mgik03ijqyyct6v/records",
     "Логіст", "Петро", False, None),
    ("журнал дій бачить тільки адміністратор",
     "GET", JOURNAL, "Бухгалтер", "Оля", False, None),
    ("журнал дій: адміністратору можна", "GET", JOURNAL, "Адміністратор", "Ірина", True, None),

    # --- право змінювати
    ("«Перегляд» пише в угоди → ні", "PATCH", DISP, "Перегляд", "Гість", False, None),
    ("бухгалтер пише в угоди → ні (edit немає)", "PATCH", DISP, "Бухгалтер", "Оля", False, None),
    ("менеджер пише в угоди → так", "PATCH", DISP, "Сейлз-менеджер", "Іван", True, "Менеджер"),
    ("журнал дій не видаляється навіть адміністратором",
     "DELETE", JOURNAL, "Адміністратор", "Ірина", False, None),

    # --- fail-closed: у сумнівному випадку «ні»
    ("роль невідома → ні", "GET", DISP, None, "", False, None),
    ("ключ протух → ні", "GET", DISP, "__EXPIRED__", "", False, None),
    ("роль, якої немає в переліку → ні", "GET", DISP, "Директор", "Хтось", False, None),
    ("невідома таблиця → ні", "GET", UNKNOWN, "Адміністратор", "Ірина", False, None),
    ("менеджер без імені в довіднику → ні (обмежити нема по чому)",
     "GET", DISP, "Сейлз-менеджер", "", False, None),

    # --- те, що прошарок не має чіпати
    ("вхід у платформу проходить повз перевірку", "POST", LOGIN, None, "", True, None),
    ("довідник користувачів видно всім ролям", "GET", USERS, "Логіст", "Петро", True, None),
]


def run():
    bad = 0
    for name, method, path, role, who, want_ok, want_field in CASES:
        ok, why, field = G.decide(method, path, role, who)
        good = (ok == want_ok) and (field == want_field)
        bad += 0 if good else 1
        print("  %s %-58s → %s%s" % ("✓" if good else "✗", name[:58],
              "можна" if ok else "НІ", (" · лише свої за «%s»" % field) if field else ""))
        if not good:
            print("      ОЧІКУВАЛОСЬ: %s%s   (причина: %s)"
                  % ("можна" if want_ok else "НІ",
                     (" · поле «%s»" % want_field) if want_field else "", why))

    # ── галочка «переказано»: вузький виняток для бухгалтера і фінансиста ──
    # Фасад дозволяє їм це окремою умовою canMark, хоча права edit у них немає.
    # Прошарок має пропустити рівно цю дію і не пропустити нічого більше.
    MARK = '[{"Id":5,"Переказ за кордон":true,"Дата переказу":"2026-08-11","Сума переказу":120}]'
    SNEAK = '[{"Id":5,"Переказ за кордон":true,"Статус":"Вантаж доставлено"}]'
    extra = [
        ("фінансист ставить позначку переказу → можна", "PATCH", DISP, "Фінансист",
         "Оля", MARK, True),
        ("бухгалтер ставить позначку переказу → можна", "PATCH", DISP, "Бухгалтер",
         "Оля", MARK, True),
        ("фінансист під виглядом позначки міняє СТАТУС → ні", "PATCH", DISP,
         "Фінансист", "Оля", SNEAK, False),
        ("фінансист лізе правити калькуляції → ні", "PATCH", CALC, "Фінансист",
         "Оля", MARK, False),
        ("«Перегляд» ставить позначку переказу → ні", "PATCH", DISP, "Перегляд",
         "Гість", MARK, False),
    ]
    for name, method, path, role, who, body, want_ok in extra:
        ok, why, _ = G.decide(method, path, role, who, G.payload_fields(body.encode()))
        good = ok == want_ok
        bad += 0 if good else 1
        print("  %s %-58s → %s" % ("✓" if good else "✗", name[:58], "можна" if ok else "НІ"))
        if not good:
            print("      ОЧІКУВАЛОСЬ: %s   (причина: %s)" % ("можна" if want_ok else "НІ", why))

    # окремо: сама обрізка рядків
    body = ('{"list":[{"Id":1,"Менеджер":"Іван"},{"Id":2,"Менеджер":"Оксана"},'
            '{"Id":3,"Менеджер":"Іван"}],"pageInfo":{"isLastPage":true}}').encode()
    out, was, now = G.scope_rows(body, "Менеджер", "Іван")
    okc = (was == 3 and now == 2 and "Оксана".encode() not in out)
    bad += 0 if okc else 1
    print("  %s обрізка відповіді: з %d рядків лишилось %d, чужого немає"
          % ("✓" if okc else "✗", was, now))

    total = len(CASES) + len(extra) + 1
    print()
    if bad:
        print("GATEWAY_RULES_FAIL — не виконано: %d з %d" % (bad, total))
    else:
        print("GATEWAY_RULES_OK — усі %d перевірок пройшли" % total)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(run())
