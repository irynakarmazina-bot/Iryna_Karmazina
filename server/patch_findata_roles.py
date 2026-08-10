#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Вчить /root/findata.py віддавати різний звіт різним ролям.

ЗАВДАННЯ (рішення користувачки 11.08.2026): роль «Фінансист» не має бачити в
оперативному фінансовому звіті дві нижні панелі — «Робочий капітал по місяцях»
і «Внески власників». Усе, що вище (плитки, зокрема «Робочий капітал (NWC)» і
«Заморожений капітал»), лишається.

ЧОМУ САМЕ ТУТ, А НЕ В БРАУЗЕРІ. Сховати панель на сторінці — це косметика:
цифри все одно приїхали б у браузер і були б видні в інструментах розробника.
Користувачка обрала третій варіант із трьох — щоб дані не доїжджали взагалі.
`findata.py` для цього підходить: він УЖЕ визначає роль на кожен запит
(get_role), інакше він не міг би пускати сюди лише фінансові ролі.

Що ховається — це ДАНІ, а не назви панелей: ключі `equity`, `equityMonthly`
(таблиця внесків) і `nwcMonthly` (стовпчики по місяцях). Плитку «Робочий
капітал (NWC)» це не чіпає: вона бере `cards.nwc`, окремий ключ.
Сама сторінка звіту (www/findash.html) уміє ховати панель, для якої даних не
прийшло, — без цього вона впала б на `D.equity.map`.

Ідемпотентно: якщо правка вже стоїть — виходить, нічого не змінивши.
Нічого не видаляє. Копію робить сам, поруч: findata.py.bak-<час>.

Запуск: python3 /root/patch_findata_roles.py [--dry-run]
Відкат: cp /root/findata.py.bak-<час> /root/findata.py && systemctl restart <служба>
"""
import datetime
import re
import shutil
import sys

P = "/root/findata.py"
MARK = "def hide_for_role("

BLOCK = '''
# ── що якій ролі НЕ показувати ────────────────────────────────────────────
# Рішення користувачки 11.08.2026: фінансист не бачить у оперативному звіті
# двох НИЖНІХ панелей. Усе, що вище, лишається — зокрема плитка «Робочий
# капітал (NWC)», бо вона бере окремий ключ cards.nwc.
#   equity, equityMonthly → панель «Внески власників»
#   nwcMonthly            → панель «Робочий капітал по місяцях»
# Бухгалтер і Адміністратор бачать усе, як бачили.
HIDE_BY_ROLE = {
    ("Фінансист", "dashboard"): ("equity", "equityMonthly", "nwcMonthly"),
}


def hide_for_role(role, name, data):
    """Прибрати з відповіді те, що цій ролі не належить. Копія, не оригінал."""
    keys = HIDE_BY_ROLE.get((role, name))
    if not keys or not isinstance(data, dict):
        return data
    out = dict(data)
    for k in keys:
        out.pop(k, None)
    return out


'''

OLD_RET = ('            return self._send(200, {"file": FILES[name], '
           '"mtime": mtime, "data": data})')
NEW_RET = ('            data = hide_for_role(role, name, data)\n'
           '            return self._send(200, {"file": FILES[name], '
           '"mtime": mtime, "data": data})')


def main():
    dry = "--dry-run" in sys.argv
    s = open(P, encoding="utf-8").read()

    if MARK in s:
        print("правка вже стоїть — нічого не міняю")
        return 0

    if OLD_RET not in s:
        print("НЕ ЗНАЙШЛА рядок віддачі даних — нічого не змінено.")
        print("Шукала точний рядок:")
        print("  " + OLD_RET.strip())
        return 1

    m = re.search(r"^class H\(", s, re.M)
    if not m:
        print("НЕ ЗНАЙШЛА «class H(» — нічого не змінено")
        return 1

    s2 = s[:m.start()] + BLOCK.lstrip("\n") + s[m.start():]
    s2 = s2.replace(OLD_RET, NEW_RET, 1)

    if dry:
        print("--dry-run: записувати не буду.")
        print("  додала б функцію hide_for_role перед «class H(»")
        print("  і рядок «data = hide_for_role(role, name, data)» перед віддачею")
        return 0

    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    bak = "%s.bak-%s" % (P, stamp)
    shutil.copy2(P, bak)
    print("копія: %s" % bak)

    open(P, "w", encoding="utf-8").write(s2)
    print("готово: фінансист більше не отримує equity, equityMonthly, nwcMonthly")

    import py_compile
    py_compile.compile(P, doraise=True)
    print("синтаксис після правки — OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
