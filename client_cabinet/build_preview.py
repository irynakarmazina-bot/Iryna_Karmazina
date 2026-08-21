#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Генератор ПРОТОТИПУ клієнтського кабінету (лише для показу користувачці).

Це НЕ робочий кабінет: тут немає ні входу, ні сервера-посередника. Скрипт бере
угоди одного клієнта з NocoDB і зашиває їх у статичну сторінку, щоб узгодити
вигляд — насамперед схему руху вантажу — перш ніж будувати справжній кабінет.

Клієнтські дані фільтруються ТУТ, на сервері: у сторінку потрапляють лише
дозволені колонки одного клієнта. Внутрішніх полів (агент, маржа, службові
коментарі) у файлі немає взагалі.

Запуск: python3 build_preview.py [--client Мірандор] [--out /root/unitex-os-www/cabinet.html]
"""
import argparse
import json
import os
import re
import urllib.request

NC = "http://localhost:8080"
TABLE = "m58xsjo6at01ohl"
TOKEN_FILE = "/root/nocodb-token.txt"
# Лого беремо з фасада ЕРП, щоб воно було одне на систему і не лежало другою
# копією. 14.08.2026 скрипт фасада винесли з index.html у app/main.js — лого
# поїхало разом із ним, а кабінет далі дивився в index.html і показував порожню
# картинку («зламалося лого»). Тому шукаємо у ВСІХ місцях, де воно може бути,
# і перше знайдене беремо: переїзд коду більше не ламає кабінет.
FACADE_FILES = ["/root/unitex-os-www/app/main.js",
                "/root/unitex-os-www/index.html"]
CANCELLED = "Скасована"

# Єдині колонки, які взагалі виходять із бази для клієнта.
CLIENT_COLS = [
    "Угода", "Напрямок", "Вид перевезення", "Тип", "FCL/LCL", "Маршрут", "Лінія",
    "BL", "HBL", "Контейнер", "Судно", "Вояж", "Гейт ін", "ETD (план)", "ETD (факт)",
    "ETA", "ETA порт (план)", "ETA порт (факт)", "Вивантаження в порту (факт)",
    "Порт перевалки", "Перевалка (прибуття)", "Перевалка (відправлення)",
    "Гейт аут", "Подача авто (план)", "Подача авто (факт)", "Статус",
    "Вантаж", "Кількість", "Файли", "Перевізник", "Авіанакладна", "Реліз",
    # Додано 02.08.2026. Ці колонки використовує схема руху, але їх не було в
    # списку — тому «Стафіровка», «Сухий порт», «Кордон» і «Доставлено»
    # малювались БЕЗ дат, хоча дати в базі є.
    "Stuffing", "Здача в порт (факт)", "Сухий порт", "ETA сухий порт",
    "Постановка/завантаження (план)", "Постановка/завантаження (факт)",
    "Gate out for delivery", "На кордоні", "Перетин кордону (факт)",
    "Кінцева точка доставки", "Планова до клієнта (план)",
    "Планова до клієнта (факт)", "Вивантаження у отримувача (факт)",
    # УВАГА: сюди йде лише «Коментар клієнту». Внутрішній «Коментар» (службові
    # нотатки менеджерів) у кабінет НЕ передається — його немає в цьому списку,
    # і додавати не можна.
    "Коментар клієнту", "Умови поставки (Інкотермс)",
]
# Документи, які бачить клієнт (префікс у назві файла). «Внутрішній» — не бачить.
CLIENT_DOCS = ["Домашній коносамент", "Лінійний коносамент", "Т1", "Реліз", "ЦМР",
               "Рахунок", "Інвойс", "Довідка", "Акт"]


def nc_all():
    tok = open(TOKEN_FILE).read().strip()
    out, off = [], 0
    while True:
        req = urllib.request.Request(
            "%s/api/v2/tables/%s/records?limit=1000&offset=%d" % (NC, TABLE, off),
            headers={"xc-token": tok})
        js = json.load(urllib.request.urlopen(req, timeout=180))
        out += js["list"]
        if js.get("pageInfo", {}).get("isLastPage"):
            return out
        off += 1000


def logo():
    """Лого ЕРП у вигляді data:URL. Порожньо — якщо не знайшли ніде.

    Порожній рядок дає биту картинку в шапці, тому це помітно одразу; мовчки
    підставляти щось інше не можна — лого одне на систему.
    """
    for path in FACADE_FILES:
        try:
            src = open(path, encoding="utf-8").read()
        except Exception:  # noqa: BLE001
            continue
        m = re.search(r'const LOGO_SRC = "(data:image/png;base64,[^"]+)"', src)
        if m:
            return m.group(1)
    return ""


# Правова форма для показу в кабінеті. За замовчуванням «ТОВ»; винятки —
# клієнти, у яких форма інша або її показувати не треба (вимога користувачки
# 02.08.2026: «Космов не треба додавати ТОВ, там буде виключення»).
NO_LEGAL = {"космов"}


LEGAL_RE = re.compile(r"(?:^|\s)(ТОВ|ТзОВ|ООО|ООО\.|ЧП|ПП|ФОП|LLC|LTD)(?:\s|$)", re.I)
# «ООО» в довіднику — помилка мови, а не інша форма власності (користувачка
# 02.08.2026: «ООО не має бути ніде взагалі, тільки ТОВ»). Виправляємо на показ;
# у самому Експедиторі вона правитиме поступово вручну.
FORM_FIX = {"ооо": "ТОВ", "тов": "ТОВ", "тзов": "ТзОВ", "чп": "ПП", "пп": "ПП",
            "фоп": "ФОП", "llc": "LLC", "ltd": "LTD"}


def client_title(name):
    """Правова форма ЗАВЖДИ попереду: «ГРАНД МАРИН ТОВ» → «ТОВ ГРАНД МАРИН».
    Вимога користувачки 02.08.2026 — в Експедиторі форма стоїть після назви,
    у кабінеті має бути перед. Якщо форми в назві немає — додаємо «ТОВ».
    Регістр літер беремо як в Експедиторі, самі його не міняємо."""
    n = re.sub(r"\s+", " ", str(name or "")).strip()
    if not n or n.lower() in NO_LEGAL:
        return n
    m = LEGAL_RE.search(n)
    if m:
        form = FORM_FIX.get(m.group(1).strip(".").lower(), m.group(1))
        rest = re.sub(r"\s{2,}", " ", (n[:m.start(1)] + " " + n[m.end(1):])).strip()
        return (form + " " + rest).strip() if rest else n
    return "ТОВ " + n


def nz(v):
    return re.sub(r"\s+", " ", str(v or "")).strip()


def files_of(row):
    """Клієнтські документи з поля «Файли»: тип беремо з префікса [Тип] у назві."""
    raw = row.get("Файли")
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except Exception:  # noqa: BLE001
            raw = []
    out = []
    for f in raw or []:
        title = nz(f.get("title") or f.get("fileName"))
        m = re.match(r"^\s*\[([^\]]+)\]\s*(.*)$", title)
        kind = m.group(1).strip() if m else ""
        # ⚠️ БЕЗ ПРЕФІКСА [Тип] — ТЕЖ НЕ ПОКАЗУЄМО. Було `if kind and kind not in …`,
        # тобто порожній тип пропускався далі й файл ставав видимим клієнту як
        # «Документ». Через це 18.08.2026 в кабінет «Гранд Марин» потрапила
        # «Заявка авто …» — внутрішній документ. Білий список має працювати як
        # білий список: показуємо ЛИШЕ те, що в ньому названо. Новий файл без
        # префікса лишається всередині фірми, поки хтось не проставить тип.
        if kind not in CLIENT_DOCS:
            continue                      # внутрішній документ — клієнту не віддаємо
        out.append({"kind": kind, "name": (m.group(2) if m else title) or title})
    return out


TPL = r"""<!doctype html>
<meta charset="utf-8">
<title>__TITLE__</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
/* ===== Візуальна система — та сама, що в ЕРП: світлий фон, білі картки з
   тонкою межею й м'якою тінню, синій акцент, кольорові іконки-чипи.
   Переписано цілком 02.08.2026: до цього сторінка була набором плоских
   білих прямокутників і виглядала мляво. ===== */
:root{
  /* Палітра ВЗЯТА ДОСЛІВНО з ЕРП (www/index.html) — тепла підкладка #f9f9f7,
     майже чорний текст #0b0b0b, ті самі лінії й акцент. Раніше кабінет мав
     власні холодні сірі (#f7f8fa / #101828 / #98a2b3) і через це виглядав
     тьмяно і чужорідно поруч із програмою (зауваження 02.08.2026). */
  --paper:#f9f9f7; --surface:#ffffff; --surface-2:#f4f4f0;
  --ink:#0b0b0b; --ink-2:#52514e; --muted:#898781;
  --line:#e1e0d9; --line-soft:#eeede8;
  --accent:#2a78d6; --accent-soft:#e7f0fb; --accent-ink:#1c5cab;
  --pos:#1a8f5c; --pos-bg:#e6f5ec; --warn:#b45309; --warn-bg:#fdf3e3;
  --vio:#6d3ec7; --vio-bg:#efe9fb;
  --shadow:0 1px 2px rgba(11,11,11,.05),0 1px 3px rgba(11,11,11,.04);
  --r:14px;
}
*{box-sizing:border-box}
body{margin:0;background:var(--paper);color:var(--ink);
  font:15px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;
  -webkit-font-smoothing:antialiased}
/* ШАПКА ВИРІВНЯНА ПО ТІЙ САМІЙ РАМЦІ, ЩО Й ТАБЛИЦЯ. Було: шапка на всю
   ширину екрана з власним відступом 30px, а таблиця обмежена 1560px і
   відцентрована — тому на широкому екрані лого стирчало ЛІВІШЕ за рамку
   таблиці, а кнопка «Вийти» — правіше (зауваження користувачки 14.08.2026).
   Тепер вміст шапки лежить у `.hbar` з тими самими max-width і padding, що й
   `main`, і краї збігаються самі, без підбирання чисел. */
header{background:var(--surface);border-bottom:1px solid var(--line);
  padding:22px 0 18px;position:sticky;top:0;z-index:5}
.hbar{max-width:1560px;margin:0 auto;padding:0 30px;
  display:flex;align-items:center;gap:18px}
header img{height:56px;display:block}
.spacer{flex:1}
/* Назва компанії і кнопка — стовпчиком: кнопка ПІД назвою, обидві притиснуті
   до правого краю рамки (так просила користувачка). */
.who{display:flex;flex-direction:column;align-items:flex-end;gap:9px;
  text-align:right;line-height:1.25}
.who b{display:block;font-size:18px;font-weight:700;letter-spacing:-.2px}
.who span{display:block;font-size:12px;color:var(--muted);margin-top:-6px}
main{max-width:1560px;margin:0 auto;padding:24px 30px 70px}

/* плитки — з кольоровими іконками, як на дашборді ЕРП */
.tiles{display:grid;grid-template-columns:repeat(5,1fr);gap:14px;margin-bottom:22px}
.tile{background:var(--surface);border:1px solid var(--line);border-radius:var(--r);
  padding:16px 18px;box-shadow:var(--shadow);display:flex;align-items:center;gap:14px;
  cursor:pointer;text-align:left;font:inherit;color:inherit;width:100%;
  transition:border-color .12s,box-shadow .12s}
.tile:hover{border-color:#c9c8bf}
.tile.on{border-color:var(--accent);box-shadow:0 0 0 3px var(--accent-soft)}
.ic{width:42px;height:42px;border-radius:11px;display:flex;align-items:center;
  justify-content:center;flex:none}
.ic svg{width:21px;height:21px;fill:none;stroke:currentColor;stroke-width:1.8;
  stroke-linecap:round;stroke-linejoin:round}
.ic i.msk{display:block;width:21px;height:21px;background:currentColor;
  -webkit-mask:var(--m) center/contain no-repeat;mask:var(--m) center/contain no-repeat}
/* ІКОНКИ ПЛИТОК — ЯСКРАВІ (вимога користувачки 14.08.2026: «змінити кольори
   іконок на більш яскраві»). Було: блідий фон і кольоровий значок — плитки
   зливались у сіру смугу. Стало: насичена заливка, білий значок і м'яке
   сяйво того ж кольору. Сяйво — не прикраса: без нього яскравий квадрат на
   білій картці виглядає наліпкою.
   Кожній плитці свій колір. Раніше «відправляються» і «прибувають» були
   ОБИДВІ помаранчеві, і дві сусідні плитки не розрізнялись оком. */
.ic{color:#fff}
.ic-blue {background:linear-gradient(140deg,#3b82f6,#1d4ed8);box-shadow:0 3px 10px rgba(29,78,216,.32)}
.ic-orange{background:linear-gradient(140deg,#fb923c,#ea580c);box-shadow:0 3px 10px rgba(234,88,12,.32)}
.ic-amber{background:linear-gradient(140deg,#22d3ee,#0891b2);box-shadow:0 3px 10px rgba(8,145,178,.32)}
.ic-green{background:linear-gradient(140deg,#34d399,#059669);box-shadow:0 3px 10px rgba(5,150,105,.32)}
.ic-vio  {background:linear-gradient(140deg,#a78bfa,#6d28d9);box-shadow:0 3px 10px rgba(109,40,217,.32)}
.tile .n{font-size:26px;font-weight:700;letter-spacing:-.6px;line-height:1.1}
.tile .l{color:var(--ink-2);font-size:12.5px;margin-top:1px}

/* пошук і перемикач */
.bar{display:flex;gap:12px;align-items:center;margin-bottom:16px;flex-wrap:wrap}
.bar input{flex:1;min-width:260px;padding:11px 15px;border:1px solid var(--line);
  border-radius:11px;background:var(--surface);font:inherit;font-size:14px;
  color:var(--ink);box-shadow:var(--shadow)}
.bar input:focus{outline:none;border-color:var(--accent);box-shadow:0 0 0 3px var(--accent-soft)}
.seg{display:flex;gap:4px;background:var(--surface);border:1px solid var(--line);
  border-radius:11px;padding:4px;box-shadow:var(--shadow)}
.seg button{border:0;background:transparent;padding:8px 16px;font:inherit;font-size:13.5px;
  cursor:pointer;color:var(--ink-2);border-radius:8px;font-weight:500}
.seg button.on{background:var(--accent-soft);color:var(--accent-ink);font-weight:600}

/* таблиця — легка, без важких ліній */
.tw{background:var(--surface);border:1px solid var(--line);border-radius:var(--r);
  box-shadow:var(--shadow);overflow:hidden}
table{width:100%;border-collapse:collapse}
th{text-align:left;font-size:11.5px;letter-spacing:.02em;background:var(--surface);
  color:var(--ink);font-weight:700;padding:11px 16px;border-bottom:1.5px solid var(--line)}
td{padding:12px 16px;border-bottom:1px solid var(--line-soft);vertical-align:middle;
  font-size:14px;color:var(--ink)}
tbody tr.deal:nth-child(odd) td{background:#fbfbf9}
tr.deal{cursor:pointer;transition:background .12s}
tr.deal:hover td{background:var(--surface-2)}
tr.deal.open td{background:var(--accent-soft)}
tbody tr:last-child td{border-bottom:0}
/* квадратик «Реліз»: порожній — релізу немає, з галкою — виданий.
   Показ, а не редагування: клієнт не змінює службові позначки. */
.ck{display:inline-block;width:17px;height:17px;border:1.5px solid var(--line);
  border-radius:5px;background:var(--surface);vertical-align:middle;position:relative}
.ck.on{background:var(--pos);border-color:var(--pos)}
.ck.on::after{content:"";position:absolute;left:5px;top:1.5px;width:4px;height:9px;
  border:solid #fff;border-width:0 2px 2px 0;transform:rotate(43deg)}

/* смуга «ви дивитесь як співробітник» — щоб ніхто не сплутав перегляд
   із реальним входом клієнта */
.staffbar{background:#fdf3e3;color:#8a4b09;border-bottom:1px solid #f0dcb8;
  padding:9px 30px;font-size:13px;text-align:center}
.staffbar b{font-weight:700}

/* позначка «дані оновлено …» — щоб було видно, що система жива */
.upd{display:inline-flex;align-items:center;gap:8px;background:var(--surface);
  border:1px solid var(--line);border-radius:11px;padding:9px 14px;font-size:12.5px;
  color:var(--ink-2);box-shadow:var(--shadow);white-space:nowrap}
.upd i{width:7px;height:7px;border-radius:50%;background:var(--pos);flex:none;
  box-shadow:0 0 0 3px var(--pos-bg)}
.upd b{color:var(--ink);font-weight:700}

/* мініатюра маршруту в рядку таблиці */
.mini{display:flex;align-items:center;margin-top:7px;height:11px}
.mini .md{width:7px;height:7px;border-radius:50%;background:var(--mbg);flex:none;
  box-shadow:inset 0 0 0 1.5px var(--mc);opacity:.45}
.mini .md.done{background:var(--mc);opacity:1;box-shadow:none}
.mini .md.now{width:11px;height:11px;background:var(--mc);opacity:1;
  box-shadow:0 0 0 3px color-mix(in srgb,var(--mc) 22%,transparent)}
.mini .ml{flex:1;height:2px;background:var(--mc);opacity:.2;min-width:6px}
.mini .ml.on{opacity:.85}
.mono{font-variant-numeric:tabular-nums}
.num{font-weight:700;font-size:15px}
.chip{display:inline-block;font-size:10.5px;font-weight:700;letter-spacing:.03em;
  padding:3px 8px;border-radius:6px;background:var(--accent-soft);color:var(--accent-ink)}
.chip.exp{background:var(--pos-bg);color:var(--pos)}
.d{font-weight:700;white-space:nowrap}
.dim{color:var(--muted)}
.pill{display:inline-flex;align-items:center;gap:6px;font-size:12.5px;font-weight:600;
  padding:4px 11px;border-radius:99px;background:var(--surface-2);color:var(--ink-2)}
.pill::before{content:"";width:6px;height:6px;border-radius:50%;background:currentColor;flex:none}
.pill.sea{background:var(--accent-soft);color:var(--accent-ink)}
.pill.ok{background:var(--pos-bg);color:var(--pos)}
.pill.wait{background:var(--warn-bg);color:var(--warn)}
.docn{display:inline-flex;align-items:center;gap:6px;color:var(--accent-ink);font-weight:600}
/* Коментар — крайня права колонка. Джерело ТІЛЬКИ «Коментар клієнту»;
   службові нотатки менеджерів у кабінет не потрапляють (02.08.2026). */
th.cmt,td.cmt{width:230px;max-width:230px;white-space:normal;color:var(--ink-2);font-size:13px}

/* ===== розгорнута картка угоди — за макетом ===== */
tr.exp>td{padding:0;background:var(--surface-2)}
.panel{padding:22px 24px 24px}
.phead{position:relative;padding-right:200px;margin-bottom:20px}
.pttl{display:flex;align-items:center;gap:12px}
.pttl b{font-size:20px;font-weight:700;letter-spacing:-.4px}
.badge{display:inline-flex;align-items:center;gap:7px;background:var(--mc);color:#fff;
  font-size:11.5px;font-weight:700;letter-spacing:.05em;padding:6px 13px;border-radius:9px}
.pmeta{font-size:13px;color:var(--ink-2);margin-top:7px}
.pmeta i{color:var(--muted);font-style:normal;margin:0 3px}
.pmeta b{color:var(--ink);font-weight:700}
.peta{position:absolute;top:0;right:0;min-width:180px;text-align:center;
  background:var(--mbg);border-radius:12px;padding:10px 16px}
.peta .lb{font-size:10.5px;font-weight:700;letter-spacing:.1em;color:var(--ink-2)}
.peta .dt{font-size:19px;font-weight:700;margin-top:2px;font-variant-numeric:tabular-nums}
.peta .pl{font-size:12px;color:var(--ink-2);margin-top:1px}
.tzn{text-align:right;font-size:11.5px;color:var(--muted);margin-top:12px}

.route{background:var(--surface);border:1px solid var(--line);border-radius:16px;
  padding:34px 26px 26px;overflow-x:auto;box-shadow:var(--shadow)}
/* ── схема руху: вигляд один в один з макета користувачки ──────────────────
   Кружок СВІТЛИЙ (заливка — блідий відтінок кольору виду перевезення), малюнок
   у колірі виду. Поточний етап НЕ заливається темним — він просто більший, а
   виділяється кольоровою назвою і тривалістю. Лінії між вузлами суцільні
   кольорові там, де етап пройдено, і бліді попереду. КОРДОН — вертикальна
   пунктирна риска з підписом, а не вузол. */
.chain{display:flex;align-items:flex-start;min-width:1420px}
/* Вужчі колонки — щоб лінії між вузлами були ДОВГІ, як у макеті, а не куці. */
.nd{flex:0 0 162px;text-align:center}
/* Лінії між вузлами: у макеті майбутні НЕ бліді — вони лише трохи світліші за
   пройдені (зміряно: пройдений #4373b5, майбутній #6795c5). */
.cn{flex:1 1 auto;height:3px;background:var(--mc);opacity:.5;margin-top:46px;
  border-radius:2px;min-width:26px}
.cn.on{opacity:1}
.nd .dot{width:92px;height:92px;margin:0 auto;border-radius:50%;
  background:var(--mbg);color:var(--mc);display:flex;align-items:center;justify-content:center}
.nd .dot i.msk{display:block;background:currentColor;
  -webkit-mask:var(--m) center/contain no-repeat;mask:var(--m) center/contain no-repeat}
.nd .dot svg,.nd .dot i.msk{width:55px!important;height:55px!important}
/* судно й літак — головне плече, тому крупніші за решту (02.08.2026) */
.nd .dot.big svg,.nd .dot.big i.msk{width:60px!important;height:60px!important}
.nd.now .dot.big svg,.nd.now .dot.big i.msk{width:66px!important;height:66px!important}
/* Поточне місцезнаходження має бути видно ОДРАЗУ: кільце в колір виду
   перевезення + ореол + більший кружок. Раніше різниця була ледь помітна
   (зауваження користувачки 02.08.2026). */
.nd.now .dot{width:100px;height:100px;margin-top:-4px;
  background:color-mix(in srgb,var(--mc) 18%,#fff);
  border:2.5px solid var(--mc);
  box-shadow:0 0 0 6px color-mix(in srgb,var(--mc) 13%,transparent)}
.nd.now .ttl{font-weight:800}
.nd.now .dot svg,.nd.now .dot i.msk{width:60px!important;height:60px!important}
/* Майбутні етапи лишаються в кольорі виду перевезення, лише блідіші —
   сірий робив схему «мертвою». Прозорість не використовуємо: від неї текст
   і малюнок сіріли (зауваження про тьмяність, 02.08.2026). */
.nd.todo .dot{background:color-mix(in srgb,var(--mc) 8%,#fff);
  color:color-mix(in srgb,var(--mc) 62%,#8f8f8a)}
.nd.done .dot{background:color-mix(in srgb,var(--mc) 13%,#fff)}
/* Текст у макеті НЕ чорний і НЕ жирний: приглушений синьо-сірий, вага 600.
   У мене був важкий чорний bold — саме через це схема виглядала «важкою». */
/* Розміри ПОРАХОВАНІ з макета у відсотках від ширини картки: кружок 6.6%,
   назва 1.23%. У моєму макеті це 92 px і 17 px. Раніше все було дрібніше. */
.nd .ttl{font-size:16px;font-weight:500;margin-top:16px;line-height:1.32;color:#465264}
.nd.now .ttl{color:var(--mc);font-size:16.5px;font-weight:700}
.nd.todo .ttl{color:var(--ink-2)}
.nd .place{font-size:15px;color:#7a8393;margin-top:8px;line-height:1.35;font-weight:400}

.nd .dur{font-size:16.5px;font-weight:700;color:var(--mc);margin-top:8px}
.nd .dt{font-size:15.5px;font-weight:500;margin-top:8px;color:#465264;font-variant-numeric:tabular-nums}
.nd .dt.dim{color:var(--muted);font-weight:600}
.nd .plan{font-size:15px;color:#9aa1ad;margin-top:8px;font-variant-numeric:tabular-nums}

.brd{flex:0 0 84px;text-align:center}
.brd .bln{height:92px;border-left:1.5px dashed var(--mc);opacity:.55;margin:0 auto;width:0}
.brd .blb{font-size:13px;font-weight:600;letter-spacing:.06em;color:#8d93a0;
  text-transform:uppercase;margin-top:16px}
.brd .bld{font-size:15px;font-weight:600;color:#3c4757;margin-top:8px;font-variant-numeric:tabular-nums}

/* деталі + документи */
.cols{display:grid;grid-template-columns:1.05fr 1fr;gap:18px;margin-top:18px;align-items:start}
@media(max-width:1100px){.cols{grid-template-columns:1fr}}
.card{background:var(--surface);border:1px solid var(--line);border-radius:var(--r);
  padding:18px 20px;box-shadow:var(--shadow)}
.card h4{margin:0 0 14px;font-size:11px;text-transform:uppercase;letter-spacing:.08em;
  color:var(--muted);font-weight:700}
.kv{display:grid;grid-template-columns:auto 1fr;gap:9px 18px;font-size:14px}
.kv .k{color:var(--ink-2)}
.kv .v{font-weight:600;word-break:break-word}
.doc{display:flex;align-items:center;gap:12px;padding:11px 0;border-bottom:1px solid var(--line-soft)}
.doc:last-of-type{border-bottom:0}
.doc .nm{flex:1}
.doc .nm b{display:block;font-size:14px}
.doc .nm span{font-size:12px;color:var(--muted)}
.btn{border:1px solid var(--line);background:var(--surface);border-radius:9px;
  padding:7px 14px;font:inherit;font-size:13px;cursor:pointer;color:var(--accent-ink);font-weight:600}
.btn:hover{background:var(--accent-soft);border-color:var(--accent-soft)}
/* У справжньому кабінеті «Завантажити» — це посилання <a>, а не <button>:
   файл віддає сервер після перевірки, чия це угода. Вигляд має лишитись той самий. */
a.btn{text-decoration:none;display:inline-block;line-height:1.5}
.btn.prim{background:var(--accent);border-color:var(--accent);color:#fff}
.btn.prim:hover{filter:brightness(1.06)}
.empty{color:var(--muted);font-size:13.5px;padding:8px 0}
.msg textarea{width:100%;min-height:82px;border:1px solid var(--line);border-radius:11px;
  padding:11px 13px;font:inherit;font-size:14px;resize:vertical;background:var(--surface);color:var(--ink)}
.msg textarea:focus{outline:none;border-color:var(--accent);box-shadow:0 0 0 3px var(--accent-soft)}
.msg .row{display:flex;justify-content:space-between;align-items:center;margin-top:12px;gap:10px}
.up{border:1.5px dashed var(--line);border-radius:12px;padding:16px;text-align:center;
  color:var(--muted);font-size:13px;margin-top:14px}

/* ===== ТЕЛЕФОН (≤720 px) ==========================================
   На телефоні сторінка їхала вбік: таблиця з 10 колонок ширша за екран,
   плитки в 4 колонки не влазили (скріни користувачки 02.08.2026).
   Рішення: плитки 2×2, пошук і перемикач на всю ширину, а таблиця
   перетворюється на список карток — кожна угода окремою карткою з
   підписами полів. Горизонтальна прокрутка лишається ТІЛЬКИ всередині
   схеми руху, де вона доречна. */

/* ПРОКРУЧУЄТЬСЯ ТІЛЬКИ ТАБЛИЦЯ (вимога користувачки 14.08.2026: «прокрутка має
   бути тільки в таблиці, цю шапку зафіксуй вгорі»).
   Сторінка перестає прокручуватись сама: висота рівно на екран, а всередині
   лишається один блок, що прокручується — рядки угод. Лого, назва компанії,
   плитки, пошук і заголовки колонок лишаються на місці завжди.
   `min-height:0` обов'язковий у обох гнучких блоках: без нього вміст РОЗПИРАЄ
   контейнер, і прокрутка знову перекидається на сторінку — це типова пастка
   flexbox, а не зайвий рядок.
   Заголовок таблиці липкий і НЕПРОЗОРИЙ, інакше рядки просвічують крізь нього.
   На вузьких екранах (телефон) усе лишається як було: там таблиця розкладається
   в картки, і фіксована висота лише заважала б. */
@media (min-width:721px){
  html,body{height:100%}
  body{overflow:hidden;display:flex;flex-direction:column}
  header{position:static;flex:none}
  main{flex:1;min-height:0;display:flex;flex-direction:column;padding-bottom:24px}
  .tiles,.bar{flex:none}
  .tw{flex:1;min-height:0;overflow:auto}
  thead th{position:sticky;top:0;z-index:2}
}

@media (max-width:720px){
  html,body{overflow-x:hidden}
  header{padding:12px 0 10px}
  .hbar{padding:0 14px;gap:10px}
  header img{height:38px}
  .who{gap:6px}
  .who b{font-size:15px} .who span{font-size:11px}
  main{padding:14px 12px 48px}

  .tiles{grid-template-columns:1fr 1fr;gap:10px;margin-bottom:14px}
  .tile{padding:12px;gap:10px}
  .ic{width:34px;height:34px;border-radius:9px}
  .ic svg,.ic i.msk{width:18px;height:18px}
  .tile .n{font-size:21px}
  .tile .l{font-size:11.5px}

  .bar{flex-direction:column;align-items:stretch;gap:8px}
  .bar input{min-width:0;width:100%}
  .seg{width:100%;justify-content:space-between}
  .seg button{flex:1;padding:8px 6px;font-size:13px}

  /* таблиця → список карток */
  .tw{border:0;background:transparent;box-shadow:none;overflow:visible}
  table,thead,tbody,tr,td{display:block;width:auto}
  thead{display:none}
  tbody tr.deal{background:var(--surface);border:1px solid var(--line);border-radius:14px;
    box-shadow:var(--shadow);padding:12px 14px;margin-bottom:10px}
  tbody tr.deal:nth-child(odd) td{background:transparent}
  tr.deal td{border:0;padding:3px 0;font-size:14px}
  /* номер угоди і напрямок — в один рядок-заголовок картки */
  tr.deal td:first-child{display:inline-block;font-size:18px;font-weight:700}
  tr.deal td:nth-child(2){display:inline-block;margin-left:8px;vertical-align:3px}
  /* Підпис зліва «плаває», значення тече праворуч і за потреби переноситься
     під нього. Через flex довгий номер контейнера вилазив за край картки. */
  tr.deal td[data-l]{display:block;text-align:right;overflow:hidden}
  tr.deal td[data-l]::before{content:attr(data-l);float:left;color:var(--muted);
    font-size:12px;font-weight:400;margin-right:12px}
  th.cmt,td.cmt{width:auto;max-width:none}
  tr.exp>td{padding:0;border:0}

  /* розгорнута картка */
  .panel{padding:14px 12px 16px}
  .phead{padding-right:0}
  .pttl b{font-size:17px}
  .peta{position:static;margin-top:12px;min-width:0;text-align:left;padding:10px 14px}
  .cols{grid-template-columns:1fr;gap:12px}
  /* Схема руху на телефоні — ВЕРТИКАЛЬНА: кружок зліва, підписи справа.
     Горизонтальна стрічка на 390 px показувала лише два кроки. */
  .route{padding:16px 14px;overflow-x:visible}
  .chain{display:block;min-width:0}
  .nd{display:flex;align-items:flex-start;gap:14px;text-align:left;flex:none;width:auto}
  .nd .dot{width:56px;height:56px;margin:0;flex:none}
  .nd.now .dot{width:60px;height:60px;margin:0}
  .nd .dot svg,.nd .dot i.msk,.nd .dot.big svg{width:34px!important;height:34px!important}
  .nd.now .dot svg,.nd.now .dot.big svg{width:37px!important;height:37px!important}
  .ndtxt{flex:1;min-width:0;padding-top:4px}
  .nd .ttl{margin-top:0;font-size:15px}
  .nd.now .ttl{font-size:15.5px}
  .nd .place,.nd .dt,.nd .plan,.nd .dur{margin-top:3px;font-size:14px}
  /* min-width з десктопної версії робив із вертикальної лінії синій прямокутник */
  .cn{width:2px;min-width:0;height:16px;margin:0 0 0 27px;flex:none;border-radius:2px}
  .brd{display:flex;align-items:center;gap:14px;flex:none;width:auto;padding:4px 0}
  .brd .bln{height:0;width:56px;border-left:0;border-top:1.5px dashed var(--mc);margin:0;flex:none}
  .brd .blb{margin-top:0}
  .brd .bld{margin-top:0;margin-left:8px}
  .card{padding:14px}
  .kv{grid-template-columns:auto 1fr;gap:7px 12px;font-size:13.5px}
}

</style>

__BANNER__
<header>
  <div class="hbar">
    <img src="__LOGO__" alt="UNITEX">
    <div class="spacer"></div>
    <div class="who"><b>__CLIENTFULL__</b><span>Особистий кабінет</span>__HEADEXTRA__</div>
  </div>
</header>

<main>
  <div class="tiles" id="tiles"></div>

  <div class="bar">
    <input id="q" placeholder="Пошук: номер угоди, коносамент, контейнер, судно, маршрут…">
    <div class="seg" id="seg">
      <button data-f="act" class="on">В дорозі</button>
      <button data-f="done">Доставлені</button>
      <button data-f="all">Усі</button>
    </div>
    __UPDATED__
  </div>

  <div class="tw">
    <table>
      <thead><tr>
        <th>Угода</th><th></th><th>Маршрут</th><th>Коносамент / контейнер</th>
        <th>Судно / авіалінія</th><th>Відправлення</th><th>Прибуття</th><th>Статус</th><th>Реліз</th><th>Документи</th>
        <th class="cmt">Коментар</th>
      </tr></thead>
      <tbody id="rows"></tbody>
    </table>
  </div>

</main>

<script>
const DEALS = __DATA__;
const TODAY = "__TODAY__";
/* DEMO=true — це прототип для показу: у картці лишаються НЕробочі поле «Питання
   по вантажу» і підказка про перетягування файлів. У справжньому кабінеті
   (server/cabinet.py) DEMO=false, і ці два блоки не малюються взагалі:
   показувати клієнтові кнопку, яка нічого не робить, не можна. */
const DEMO = __DEMO__;

const s = (r,k) => String(r[k]||"").trim();
const fmt = v => { const m=/(\d{4})-(\d{2})-(\d{2})/.exec(String(v||"")); return m?`${m[3]}.${m[2]}.${m[1].slice(2)}`:""; };
/* У схемі руху дати повні — 20.06.2026, як у макеті. Коротка форма (20.06.26)
   лишається в таблиці, де місця мало. */
const fmtY = v => { const m=/(\d{4})-(\d{2})-(\d{2})/.exec(String(v||"")); return m?`${m[3]}.${m[2]}.${m[1]}`:""; };
const fmtDM = v => { const m=/(\d{4})-(\d{2})-(\d{2})/.exec(String(v||"")); return m?`${m[3]}.${m[2]}`:""; };
const esc = t => String(t==null?"":t).replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
/* Маршрут завжди зі стрілочками, як би його не ввели в Експедиторі:
   «Долина - Роттердам», «Долина -Роттердам», «Долина -> Роттердам» →
   «Долина → Роттердам». Дефіс БЕЗ пробілів не чіпаємо, інакше зламається
   «Порт-Саїд» (02.08.2026). Та сама логіка, що у фасаді. */
/* Умови поставки, за яких експорт «доїжджає» до отримувача (DAP / DDU).
   Латинкою і кирилицею — менеджери пишуть по-різному. */
const DAP_DDU = /\b(DAP|DDU|ДАП|ДДУ)\b/i;
const routeArrows = v => String(v == null ? "" : v)
  .replace(/\s*(?:-->|->|→|—|–)\s*/g, " → ")
  .replace(/\s+-\s*|\s*-\s+/g, " → ")
  .replace(/\s*→\s*/g, " → ")
  .replace(/\s{2,}/g, " ").trim();
const air  = r => /авіа/i.test(s(r,"Вид перевезення"));
const rail = r => /залізни/i.test(s(r,"Вид перевезення"));
const done = r => s(r,"Статус")==="Вантаж доставлено";
const past = d => d && d <= TODAY;

/* Дата прибуття. Для вантажу в дорозі це план (`ETA`), для ДОСТАВЛЕНОГО — ФАКТ.
   Ланцюжок той самий, що вже бере вузол «Вантаж доставлено» у схемі: інакше одна
   й та сама угода показувала б у таблиці одну дату, а в картці іншу.
   Перевірено прямим запитом до бази 15.08.2026: із 230 доставлених угод у 153
   факт розходився з планом, подекуди більш ніж на місяць (угода 21 — план 10.01,
   факт 17.02). До цього кабінет показував клієнту план і видавав його за факт. */
const arrOf = r => done(r)
  ? (s(r,"Вивантаження у отримувача (факт)") || s(r,"Планова до клієнта (факт)")
     || s(r,"Вивантаження в порту (факт)") || s(r,"ETA порт (факт)") || s(r,"ETA"))
  : s(r,"ETA");

/* ── іконки, 24×24 ────────────────────────────────────────────────────────
   Перемальовані 02.08.2026 під макет користувачки: кожен етап має ВЛАСНИЙ
   впізнаваний малюнок (будівля з колонами, документ з печаткою, портовий кран
   з контейнерами, судно на хвилях, митник у кашкеті, фура, 3D-коробка).
   До цього були тонкі однотипні контури, де склад, кран і порт виглядали
   майже однаково — саме на це вона й вказала. */
const I = {
 /* Іконки перемальовані 02.08.2026 З НАТУРИ — зі скріна користувачки, збільшеного
    з журналу сесії. Стиль її набору: КОНТУРНІ малюнки товщиною ~1.8, і лише
    судно має заливний корпус. Мої попередні спроби були спершу занадто тонкі,
    потім навпаки суцільно залиті — і те, і те повз. */

 /* Стафіровка — контейнер з торця: верхня та нижня обв'язки, 5 ребер, вушко зверху */
 warehouse:'<path d="M3.2 6.6h17.6v2.3H3.2z"/><path d="M3.2 17.2h17.6v2.3H3.2z"/>'
          +'<path d="M5.7 8.9v8.3M8.8 8.9v8.3M12 8.9v8.3M15.2 8.9v8.3M18.3 8.9v8.3"/>'
          +'<path d="M12 4.6v2"/>',

 /* Митне оформлення — аркуш із загнутим кутом, рядки тексту і КОНТУРНА печатка з галочкою */
 customs:'<path d="M12.8 2.9H6.6a1 1 0 0 0-1 1v15.2a1 1 0 0 0 1 1h4.6"/>'
        +'<path d="M17 7.1v5.2"/><path d="M12.8 2.9 17 7.1h-4.2z"/>'
        +'<path d="M8 8.5h4.6M8 11h4.6M8 13.5h3.2"/>'
        +'<circle cx="16.6" cy="16.6" r="4.5"/>'
        +'<path d="M14.5 16.7l1.6 1.6 2.9-3.1"/>',

 /* Порт — баштовий кран: щогла-А, стріла зі стрілою-противагою, гак і контейнер біля основи */
 crane:'<path d="M8.8 20.4 10.9 5.2M13 20.4 11.1 5.2"/>'
      +'<path d="M9.7 12h2.6M9.2 16.4h3.6"/>'
      +'<path d="M4.6 5.2h13.6"/><circle cx="4.9" cy="5.2" r="1.2"/>'
      +'<path d="M15.6 5.2v3.2"/><path d="M14.6 8.4h2"/>'
      +'<path d="M15 15.2h5.8v5.2H15z"/><path d="M15 16.5h5.8"/>'
      +'<path d="M16.9 16.5v3.9M18.9 16.5v3.9"/>'
      +'<path d="M7.6 20.6h13.6"/>',
 /* В морі — контейнеровоз: ЗАЛИВНИЙ корпус, контурний штабель контейнерів, три хвилі */
 ship:'<path d="M2.7 13.4h18.6l-.8 1.8c-.6 1.3-1.9 2.2-3.3 2.2H6.8c-1.4 0-2.7-.9-3.3-2.2z"'
     +' fill="currentColor" stroke="none"/>'
     +'<path d="M7.4 10.3h3v3.1h-3zM10.6 10.3h3v3.1h-3zM13.8 10.3h3v3.1h-3z"/>'
     +'<path d="M9 7.1h3v3.2H9zM12.2 7.1h3v3.2h-3z"/>'
     +'<path d="M17.4 11.7h2.8v1.7h-2.8z"/>'
     +'<path d="M2.3 18.7c1.6 0 1.6 1.1 3.3 1.1s1.6-1.1 3.3-1.1 1.6 1.1 3.2 1.1 1.6-1.1 3.3-1.1'
     +' 1.6 1.1 3.2 1.1 1.6-1.1 3.2-1.1"/>'
     +'<path d="M2.3 21.4c1.6 0 1.6 1.1 3.3 1.1s1.6-1.1 3.3-1.1 1.6 1.1 3.2 1.1 1.6-1.1 3.3-1.1'
     +' 1.6 1.1 3.2 1.1 1.6-1.1 3.2-1.1"/>',
 /* Імпортне митне оформлення — інспектор: заливний кашкет, обличчя контуром, комір-краватка */
 officer:'<circle cx="12" cy="12.2" r="3.4"/>'
        +'<path d="M5.6 9.2h12.8v1.9H5.6z" fill="currentColor" stroke="none"/>'
        +'<path d="M8.2 9.2a3.8 3.8 0 0 1 7.6 0z" fill="currentColor" stroke="none"/>'
        +'<path d="M4.8 21.5c0-3.3 2.7-5.1 5.6-5.6l1.6 2.4 1.6-2.4c2.9.5 5.6 2.3 5.6 5.6"/>'
        +'<path d="M12 18.3l-1.1 3.2h2.2z" fill="currentColor" stroke="none"/>',

 /* Фура — КОНТУРНИЙ фургон */
 truck:'<path d="M2.6 7.1h10.2v9.3H2.6z"/>'
      +'<path d="M12.8 10.3h3.4l3.3 3.2v2.9h-6.7z"/>'
      +'<circle cx="6.6" cy="18.3" r="1.9"/><circle cx="16.5" cy="18.3" r="1.9"/>',

 /* Потяг — контурний локомотив */
 train:'<path d="M6.1 4.2h11.8v10.2H6.1z"/><path d="M8.6 6.8h6.8v4.2H8.6z"/>'
      +'<path d="M6.1 14.4 4 18.1M17.9 14.4l2.1 3.7"/>'
      +'<circle cx="9.1" cy="17.5" r="1.7"/><circle cx="14.9" cy="17.5" r="1.7"/>'
      +'<path d="M2.5 20.9h19"/>',

 /* Літак — заливний силует (як у ряду «В повітрі» на макеті) */
 plane:'<path d="M20.9 6.6a1.6 1.6 0 0 0-2.3-2.3l-3.9 3.9-8.1-2.4-1.5 1.5 6.3 4-3 3-3-.6-1.2 1.2'
      +' 3.8 2.1 2.1 3.8 1.2-1.2-.6-3 3-3 4 6.3 1.5-1.5-2.4-8.1z"'
      +' fill="currentColor" stroke="none"/>',

 /* Перевалка — два зустрічні напрямки */
 swap:'<path d="M3.4 8.6h14.2"/><path d="M14.6 5.4 17.8 8.6l-3.2 3.2"/>'
     +'<path d="M20.6 15.4H6.4"/><path d="M9.4 12.2 6.2 15.4l3.2 3.2"/>',

 /* Вантаж доставлено — КОНТУРНА коробка, верхня грань поділена навхрест */
 box:'<path d="M12 2.8 21 7.4v9.2L12 21.2 3 16.6V7.4z"/>'
    +'<path d="M3 7.4 12 12l9-4.6M12 12v9.2"/>'
    +'<path d="M7.5 5.1 16.5 9.7M16.5 5.1 7.5 9.7"/>',

 doc:'<path d="M6.5 3h7l4 4v14h-11z"/><path d="M13.5 3v4h4"/><path d="M9 12h6M9 16h6"/>',
 port:'<circle cx="12" cy="4.6" r="1.9"/><path d="M12 6.8V19.4"/><path d="M8.3 10h7.4"/>'
     +'<path d="M4.8 13.4a7.2 7.2 0 0 0 14.4 0"/>',
};
/* Кожна іконка сама вирішує, де заливка, а де контур: у макеті користувачки
   судно, фура, коробка й літак — суцільні, а контейнер, кран і документ —
   контурні. Тому загальні атрибути тут лише як типове значення. */
/* ІКОНКИ КОРИСТУВАЧКИ. Це НЕ мої малюнки: вирізані просто з її макета
   (скрін у журналі сесії), очищені від кружка-підкладки і збережені як
   маски. Колір задає CSS, тому одна й та сама іконка стає синьою для моря,
   рудою для авто, зеленою для залізниці, фіолетовою для авіа.
   Причина: п'ять разів перемальовувала «схоже» — і п'ять разів мимо.
   Тепер у кабінеті стоять саме ті малюнки, які вона надіслала. */
/* ІКОНКИ КОРИСТУВАЧКИ, ПЕРЕВЕДЕНІ У ВЕКТОР. Раніше я вставляла їх картинками
   з макета — вони мутніли при збільшенні («тьмяні, не чіткі»). Тепер кожна
   обведена трасуванням (potrace) у контур, тому чітка за будь-якого розміру,
   а форма лишилась її. Малюнок один суцільний, колір задає CSS. */
const ICON_PATH = {
  warehouse: "M2.36 22.56 C1.99 22.47 1.80 22.17 1.80 21.68 C1.80 21.23 1.87 21.06 2.20 20.68 L2.42 20.43 L2.42 14.95 C2.42 8.92 2.45 9.29 1.95 8.72 C1.66 8.39 1.60 8.14 1.72 7.71 C1.89 7.08 2.07 6.98 3.29 6.87 C4.00 6.80 4.18 6.75 4.48 6.56 C4.67 6.44 5.04 6.28 5.29 6.21 C5.54 6.14 5.84 6.00 5.95 5.90 C6.05 5.80 6.36 5.63 6.64 5.52 C6.91 5.40 7.17 5.29 7.21 5.26 C7.25 5.22 7.47 5.14 7.71 5.06 C7.94 4.99 8.23 4.85 8.36 4.76 C8.48 4.67 8.82 4.46 9.11 4.30 C9.39 4.15 9.94 3.81 10.32 3.56 L11.02 3.09 L10.96 2.58 C10.85 1.66 10.94 1.39 11.40 1.15 C11.73 0.98 12.54 1.02 12.76 1.22 C13.00 1.44 13.09 1.89 13.03 2.56 C12.98 3.13 12.99 3.16 13.19 3.40 C13.30 3.53 13.54 3.71 13.73 3.79 C13.92 3.87 14.19 4.04 14.35 4.16 C14.50 4.27 14.77 4.42 14.94 4.49 C15.17 4.57 15.27 4.65 15.28 4.79 C15.31 4.95 15.29 4.96 15.09 4.93 C14.78 4.87 13.63 4.37 13.31 4.15 C13.02 3.95 12.35 3.80 11.80 3.80 C11.57 3.80 11.33 3.88 10.99 4.07 C10.15 4.53 8.99 5.10 8.88 5.10 C8.82 5.10 8.29 5.34 7.70 5.63 C7.11 5.92 6.53 6.18 6.41 6.21 C6.14 6.27 6.05 6.36 5.99 6.68 C5.89 7.14 5.63 7.12 11.95 7.10 C15.65 7.09 17.80 7.06 17.96 7.01 C18.19 6.93 18.21 6.90 18.21 6.59 C18.21 6.23 18.21 6.23 17.63 6.14 C17.47 6.11 17.18 5.98 16.99 5.86 C16.80 5.74 16.59 5.64 16.52 5.64 C16.37 5.64 15.99 5.36 15.99 5.25 C15.99 5.12 16.42 5.17 16.61 5.32 C16.71 5.40 17.01 5.52 17.27 5.59 C17.53 5.66 17.95 5.81 18.19 5.94 C18.43 6.06 18.79 6.20 18.98 6.25 C19.17 6.29 19.55 6.44 19.83 6.56 C20.11 6.69 20.60 6.84 20.93 6.90 C21.65 7.04 21.93 7.18 22.12 7.50 C22.34 7.86 22.31 8.12 21.97 8.68 C21.80 8.96 21.66 9.25 21.66 9.31 C21.66 9.38 21.65 11.89 21.64 14.89 L21.63 20.35 L21.88 20.83 C22.29 21.61 22.20 22.23 21.63 22.46 C21.44 22.54 19.53 22.57 12.00 22.60 C6.83 22.61 2.49 22.60 2.36 22.56 Z M6.03 20.74 C7.04 20.74 6.93 21.35 6.99 15.14 C7.01 12.21 7.04 9.64 7.04 9.43 C7.05 9.08 7.04 9.04 6.83 8.94 C6.66 8.86 6.35 8.83 5.72 8.85 C4.77 8.86 4.44 8.96 4.37 9.26 C4.35 9.35 4.34 11.90 4.35 14.92 C4.37 20.15 4.38 20.42 4.51 20.57 C4.66 20.73 5.00 20.82 5.29 20.77 C5.38 20.75 5.71 20.74 6.03 20.74 Z M14.69 20.60 C14.80 20.46 14.82 19.93 14.86 14.90 C14.90 8.86 14.91 9.10 14.47 8.92 C14.35 8.88 14.08 8.84 13.85 8.84 C13.51 8.84 13.41 8.87 13.24 9.04 L13.04 9.24 L13.03 14.44 C13.02 17.76 12.99 19.76 12.94 20.01 C12.84 20.47 12.87 20.56 13.18 20.66 C13.83 20.86 14.50 20.84 14.69 20.60 Z M19.51 20.63 C19.67 20.49 19.67 20.48 19.67 14.91 L19.67 9.33 L19.49 9.12 C19.33 8.93 19.26 8.91 18.41 8.85 C17.46 8.79 17.19 8.83 17.01 9.07 C16.93 9.18 16.91 10.34 16.91 14.84 C16.91 20.12 16.92 20.49 17.04 20.60 C17.26 20.80 17.37 20.81 18.37 20.80 C19.21 20.78 19.37 20.76 19.51 20.63 Z M10.88 20.56 C11.01 20.47 11.02 20.42 10.93 19.97 C10.87 19.61 10.85 18.10 10.86 14.35 L10.89 9.23 L10.69 9.05 C10.31 8.73 9.34 8.75 9.13 9.08 C9.06 9.19 9.07 16.74 9.14 18.85 C9.20 20.72 9.17 20.66 10.11 20.66 C10.52 20.66 10.79 20.63 10.88 20.56 Z",
  customs: "M15.07 18.13 C14.32 18.00 13.83 17.80 13.21 17.39 C12.80 17.11 12.56 16.81 12.14 16.10 C11.79 15.51 11.69 15.04 11.75 14.19 C11.82 13.21 12.03 12.69 12.63 12.00 C13.01 11.56 13.66 11.01 14.01 10.85 C15.10 10.33 16.69 10.45 17.69 11.14 C18.37 11.61 18.69 11.94 18.95 12.45 C19.08 12.70 19.22 13.06 19.26 13.26 C19.36 13.75 19.36 14.88 19.25 15.30 C19.14 15.73 18.70 16.55 18.41 16.85 C17.64 17.66 16.93 18.04 16.04 18.13 C15.47 18.19 15.41 18.19 15.07 18.13 Z M5.28 17.17 C5.22 17.15 5.11 17.08 5.04 17.00 L4.91 16.86 L4.92 9.44 C4.92 3.73 4.94 1.99 4.99 1.86 C5.12 1.55 5.06 1.55 8.74 1.51 C11.16 1.49 12.21 1.49 12.40 1.54 C12.58 1.58 12.80 1.70 13.06 1.89 C13.56 2.27 15.79 4.50 16.02 4.86 L16.19 5.12 L16.19 7.29 C16.19 9.23 16.18 9.47 16.09 9.63 C15.92 9.96 15.61 10.01 15.33 9.76 L15.16 9.61 L15.14 8.05 C15.12 7.20 15.09 6.41 15.06 6.31 C15.02 6.21 14.93 6.09 14.83 6.03 C14.67 5.93 14.54 5.92 13.51 5.92 C11.75 5.92 11.76 5.94 11.74 4.14 C11.73 3.40 11.70 2.89 11.66 2.82 C11.63 2.75 11.54 2.67 11.46 2.64 C11.24 2.56 6.59 2.51 6.37 2.59 C6.27 2.62 6.15 2.72 6.10 2.82 C6.01 2.98 6.00 3.44 6.00 9.38 C6.00 15.44 6.01 15.78 6.10 15.87 C6.19 15.96 6.39 15.97 8.62 16.00 C10.80 16.02 11.06 16.03 11.22 16.12 C11.57 16.31 11.72 16.78 11.52 17.04 L11.41 17.18 L8.40 17.18 C6.75 17.19 5.35 17.18 5.28 17.17 Z M16.31 16.90 C16.81 16.74 17.39 16.34 17.70 15.92 C17.81 15.77 17.99 15.43 18.09 15.15 C18.32 14.52 18.34 13.94 18.14 13.51 C17.93 13.05 17.59 12.76 17.59 13.05 C17.59 13.36 17.28 13.83 16.76 14.32 C16.48 14.58 16.12 14.95 15.96 15.13 C15.42 15.77 15.23 15.81 14.76 15.38 C13.99 14.69 13.84 14.45 14.00 14.14 C14.12 13.91 14.39 13.91 14.74 14.14 C14.87 14.23 15.05 14.30 15.12 14.30 C15.30 14.30 15.68 14.02 15.83 13.78 C15.89 13.68 16.10 13.45 16.29 13.27 C16.65 12.94 16.92 12.82 17.33 12.82 L17.52 12.82 L17.41 12.53 C17.27 12.15 17.26 12.14 16.86 12.01 C16.12 11.76 15.03 11.75 14.49 11.97 C14.26 12.06 13.56 12.66 13.41 12.87 C13.36 12.95 13.22 13.19 13.11 13.40 C12.91 13.78 12.90 13.79 12.90 14.41 L12.90 15.04 L13.17 15.49 C13.59 16.21 14.23 16.74 14.92 16.93 C15.40 17.07 15.81 17.06 16.31 16.90 Z M7.40 13.41 C7.12 13.27 7.16 12.87 7.47 12.64 C7.61 12.54 7.70 12.53 8.81 12.52 C9.91 12.52 10.02 12.53 10.25 12.63 C10.70 12.84 10.74 13.23 10.33 13.40 C10.08 13.51 7.61 13.51 7.40 13.41 Z M8.52 11.24 C7.32 11.20 7.23 11.16 7.24 10.72 C7.24 10.51 7.33 10.38 7.53 10.30 C7.63 10.27 8.45 10.25 9.75 10.25 C11.68 10.25 11.83 10.25 11.95 10.35 C12.16 10.52 12.08 10.98 11.80 11.16 C11.67 11.25 11.51 11.26 10.58 11.27 C9.99 11.27 9.06 11.26 8.52 11.24 Z M7.39 8.94 C7.13 8.73 7.14 8.20 7.41 8.05 C7.47 8.02 8.54 8.01 10.47 8.04 C13.44 8.07 13.44 8.08 13.58 8.20 C13.69 8.29 13.72 8.37 13.72 8.55 C13.72 8.99 13.82 8.97 11.09 8.98 C9.77 8.98 8.43 9.00 8.11 9.02 C7.58 9.05 7.53 9.05 7.39 8.94 Z M7.42 6.74 C7.15 6.63 7.10 6.24 7.32 6.01 C7.40 5.93 7.55 5.85 7.64 5.84 C7.74 5.82 8.33 5.81 8.97 5.82 C9.96 5.84 10.14 5.85 10.27 5.94 C10.60 6.16 10.59 6.53 10.25 6.70 C10.08 6.78 9.89 6.80 8.80 6.79 C8.10 6.79 7.48 6.77 7.42 6.74 Z M13.97 4.81 C14.07 4.76 14.11 4.69 14.12 4.54 C14.14 4.38 14.11 4.32 13.97 4.19 C13.87 4.10 13.65 3.89 13.48 3.72 C12.97 3.21 12.77 3.32 12.77 4.10 C12.77 4.54 12.78 4.57 12.93 4.72 C13.07 4.87 13.12 4.88 13.46 4.88 C13.67 4.88 13.90 4.85 13.97 4.81 Z",
  crane: "M4.38 21.42 C4.24 21.39 4.10 21.34 4.05 21.30 C3.93 21.17 3.96 20.68 4.10 20.52 C4.24 20.36 4.72 20.25 5.28 20.25 C6.03 20.25 6.15 20.13 6.88 18.63 C7.96 16.41 8.04 15.85 8.04 10.88 C8.03 7.34 8.03 7.23 7.71 7.06 C7.61 7.01 7.30 7.00 6.62 7.03 C5.78 7.07 5.65 7.09 5.52 7.21 C5.44 7.28 5.37 7.38 5.37 7.43 C5.37 7.57 4.99 7.96 4.67 8.15 C4.46 8.28 4.29 8.32 4.00 8.32 C3.65 8.33 3.61 8.31 3.37 8.08 C3.22 7.94 2.93 7.56 2.71 7.24 C2.27 6.57 2.22 6.35 2.47 6.04 C2.56 5.94 2.72 5.68 2.82 5.47 C3.15 4.82 3.43 4.66 3.93 4.83 C4.35 4.98 4.77 4.97 5.09 4.80 C5.48 4.60 7.83 2.24 8.08 1.80 C8.32 1.38 8.50 1.18 8.68 1.12 C8.87 1.06 9.33 1.33 9.45 1.57 C9.65 1.97 10.21 2.66 10.56 2.95 C10.99 3.29 11.62 3.62 12.16 3.78 C12.62 3.91 13.86 3.93 14.37 3.82 C15.32 3.61 15.43 3.60 15.71 3.68 C15.85 3.72 16.27 3.98 16.63 4.26 C17.57 4.97 18.00 5.22 18.56 5.38 C19.64 5.68 19.76 5.73 19.94 5.88 C20.16 6.06 20.18 6.29 19.99 6.59 C19.84 6.84 19.50 6.95 19.07 6.89 C18.72 6.85 18.47 6.94 18.32 7.17 C18.22 7.32 18.20 7.54 18.17 8.51 L18.14 9.67 L17.96 9.83 C17.74 10.02 17.53 10.03 17.32 9.86 C17.17 9.74 17.16 9.70 17.13 8.57 C17.10 7.51 17.09 7.38 16.97 7.22 C16.89 7.12 16.75 7.02 16.66 6.99 C16.56 6.96 15.01 6.93 13.22 6.92 C9.75 6.90 9.76 6.90 9.58 7.21 C9.52 7.32 9.50 8.20 9.48 10.82 C9.44 15.72 9.52 16.46 10.22 18.35 C10.42 18.88 10.61 19.43 10.65 19.57 C10.73 19.89 10.92 20.10 11.18 20.18 C11.29 20.21 11.80 20.26 12.31 20.29 L13.23 20.33 L13.42 20.13 C13.52 20.02 13.63 19.84 13.65 19.73 C13.67 19.61 13.69 18.77 13.69 17.86 C13.69 16.61 13.66 16.09 13.59 15.78 C13.48 15.29 13.54 14.91 13.77 14.77 C13.85 14.72 14.15 14.64 14.44 14.60 C14.72 14.56 15.04 14.47 15.14 14.41 C15.37 14.28 15.99 13.45 16.16 13.06 C16.48 12.32 16.95 11.98 17.69 11.97 C18.49 11.96 18.95 12.36 19.35 13.39 C19.74 14.41 19.86 14.53 20.47 14.53 C20.90 14.53 21.26 14.64 21.43 14.80 C21.54 14.91 21.56 14.99 21.53 15.27 C21.51 15.45 21.45 15.77 21.40 15.96 C21.31 16.25 21.29 16.64 21.29 17.98 C21.29 19.82 21.32 19.96 21.73 20.22 C21.95 20.36 22.14 20.67 22.14 20.89 C22.14 20.96 22.07 21.11 21.98 21.21 L21.82 21.39 L17.62 21.41 L13.41 21.42 L13.13 21.26 L12.85 21.09 L12.47 21.27 L12.10 21.45 L8.36 21.46 C6.31 21.46 4.51 21.44 4.38 21.42 Z M9.42 20.12 C9.64 19.95 9.64 19.83 9.40 19.15 C8.87 17.58 8.79 17.44 8.53 17.58 C8.37 17.67 8.28 17.84 8.04 18.53 C7.96 18.74 7.81 19.06 7.70 19.22 C7.56 19.45 7.51 19.59 7.53 19.78 C7.56 20.14 7.82 20.25 8.63 20.25 C9.16 20.25 9.28 20.23 9.42 20.12 Z M20.08 20.08 C20.21 19.96 20.21 19.84 20.09 19.73 C19.98 19.64 19.86 19.66 19.41 19.83 C19.20 19.91 18.97 19.93 18.59 19.92 C18.29 19.90 18.06 19.92 18.04 19.96 C18.02 20.00 18.27 20.03 18.72 20.04 C19.12 20.04 19.51 20.08 19.60 20.11 C19.84 20.21 19.97 20.20 20.08 20.08 Z M20.15 18.54 C20.27 18.37 20.28 18.28 20.27 17.29 C20.24 16.09 20.20 15.90 19.96 15.90 C19.70 15.90 19.66 16.08 19.65 17.32 C19.64 18.38 19.64 18.49 19.76 18.62 C19.91 18.79 19.97 18.77 20.15 18.54 Z M16.92 18.45 C17.02 18.19 17.08 16.27 16.99 16.03 C16.91 15.78 16.69 15.78 16.56 16.03 C16.44 16.26 16.48 18.37 16.60 18.52 C16.74 18.68 16.85 18.65 16.92 18.45 Z M15.22 18.36 C15.33 18.24 15.35 18.12 15.35 17.21 C15.35 16.18 15.29 15.90 15.09 15.90 C15.05 15.90 14.96 15.96 14.89 16.03 C14.79 16.14 14.77 16.28 14.77 17.16 C14.77 17.99 14.79 18.19 14.88 18.33 C15.02 18.53 15.06 18.54 15.22 18.36 Z M18.43 18.22 C18.47 18.11 18.50 17.80 18.50 17.53 C18.50 17.26 18.53 16.89 18.56 16.71 C18.65 16.16 18.47 15.81 18.17 15.97 C17.99 16.06 17.97 16.20 17.99 17.30 C18.00 18.00 18.03 18.31 18.10 18.39 C18.21 18.53 18.34 18.46 18.43 18.22 Z M18.28 14.38 L18.46 14.23 L18.34 13.93 C18.21 13.58 17.97 13.40 17.65 13.41 C17.47 13.42 17.37 13.48 17.11 13.76 C16.61 14.30 16.77 14.53 17.63 14.53 C18.03 14.53 18.13 14.51 18.28 14.38 Z M7.78 5.57 C8.26 5.24 8.31 4.14 7.85 3.95 C7.59 3.84 7.50 3.90 6.83 4.55 C6.25 5.12 6.02 5.51 6.16 5.67 C6.28 5.81 7.55 5.73 7.78 5.57 Z M15.60 5.54 C16.14 5.53 16.25 5.52 16.33 5.41 C16.47 5.21 16.44 5.08 16.20 4.90 C15.75 4.55 15.20 4.51 14.32 4.76 C13.81 4.91 13.64 4.93 13.19 4.89 C12.02 4.81 11.28 4.54 10.44 3.91 C10.15 3.69 9.90 3.56 9.83 3.57 C9.60 3.60 9.50 3.92 9.52 4.55 C9.53 5.14 9.63 5.43 9.84 5.57 C9.92 5.62 10.68 5.63 12.45 5.60 C13.83 5.57 15.24 5.55 15.60 5.54 Z",
  ship: "M15.42 22.64 C15.16 22.60 14.39 22.34 14.25 22.24 C13.36 21.64 12.51 21.43 11.67 21.61 C11.40 21.66 11.02 21.81 10.55 22.04 C9.62 22.50 9.39 22.57 8.77 22.61 C8.07 22.65 7.72 22.55 6.75 22.06 L5.96 21.67 L5.43 21.67 C4.78 21.68 4.28 21.81 3.56 22.16 C3.26 22.30 2.93 22.43 2.81 22.44 C2.55 22.48 2.50 22.41 2.46 21.95 C2.42 21.64 2.43 21.64 2.57 21.64 C2.65 21.64 2.89 21.56 3.10 21.45 C3.31 21.35 3.66 21.21 3.87 21.15 C4.08 21.08 4.35 20.97 4.47 20.91 C4.65 20.82 4.80 20.80 5.29 20.79 C5.88 20.79 5.90 20.79 6.33 21.00 C6.57 21.12 7.02 21.33 7.32 21.48 C8.01 21.81 8.28 21.88 8.84 21.85 C9.24 21.83 9.36 21.79 9.87 21.56 C11.09 21.00 11.27 20.93 11.66 20.84 C11.93 20.78 12.24 20.76 12.59 20.77 C13.06 20.79 13.17 20.81 13.48 20.96 C13.68 21.06 14.16 21.28 14.55 21.44 C15.15 21.70 15.34 21.75 15.70 21.78 C16.23 21.82 16.55 21.74 17.72 21.25 C18.71 20.85 18.76 20.83 19.27 20.76 C19.82 20.69 20.12 20.76 20.91 21.14 C21.28 21.32 21.68 21.49 21.80 21.51 C22.09 21.55 22.13 21.66 21.95 21.85 C21.87 21.93 21.79 22.06 21.77 22.14 C21.73 22.32 21.59 22.34 21.37 22.20 C21.29 22.14 21.05 22.04 20.84 21.97 C20.63 21.90 20.36 21.79 20.24 21.73 C20.08 21.64 19.92 21.61 19.61 21.61 C19.13 21.62 18.72 21.74 17.87 22.14 C17.08 22.51 16.66 22.63 16.08 22.65 C15.81 22.66 15.51 22.66 15.42 22.64 Z M15.40 19.66 C15.07 19.61 14.83 19.51 14.03 19.13 C13.03 18.66 12.61 18.57 11.84 18.68 C11.40 18.74 11.15 18.83 9.73 19.44 C9.44 19.56 9.32 19.58 8.71 19.58 C8.05 19.58 8.01 19.58 7.50 19.38 C7.21 19.26 6.82 19.09 6.63 18.98 C5.66 18.43 5.01 18.46 3.63 19.09 C2.50 19.60 1.62 19.73 1.24 19.44 C1.07 19.30 1.06 19.10 1.23 18.93 C1.33 18.83 1.44 18.80 1.75 18.77 C2.33 18.71 2.91 18.54 3.39 18.30 C4.09 17.95 4.90 17.69 5.34 17.70 C5.71 17.70 6.76 18.11 7.09 18.39 C7.17 18.46 7.34 18.54 7.47 18.57 C7.60 18.61 7.84 18.68 8.01 18.74 C8.28 18.83 8.38 18.83 8.85 18.79 C9.45 18.72 9.72 18.64 10.28 18.37 C10.90 18.05 11.70 17.80 12.19 17.77 C12.77 17.73 13.18 17.83 13.94 18.21 C14.71 18.60 15.06 18.72 15.57 18.76 C16.18 18.82 16.98 18.63 17.52 18.30 C17.66 18.22 17.97 18.08 18.22 17.99 C18.60 17.85 18.73 17.84 19.31 17.83 C19.89 17.83 20.02 17.85 20.37 17.98 C20.59 18.06 20.94 18.23 21.15 18.35 C21.51 18.57 22.00 18.73 22.58 18.81 C22.72 18.83 22.88 18.89 22.92 18.93 C23.03 19.04 23.03 19.36 22.93 19.44 C22.65 19.68 21.67 19.48 20.58 18.97 L19.92 18.66 L19.39 18.67 C18.73 18.68 18.53 18.73 17.80 19.08 C16.56 19.67 16.10 19.78 15.40 19.66 Z M8.24 17.62 C8.11 17.58 7.90 17.47 7.77 17.37 C7.65 17.28 7.51 17.20 7.48 17.20 C7.44 17.20 7.28 17.13 7.12 17.05 C6.29 16.60 5.13 16.55 4.25 16.91 C3.94 17.04 3.88 17.05 3.73 16.98 C3.57 16.92 3.24 16.45 3.24 16.29 C3.24 16.25 3.09 15.92 2.91 15.55 C2.48 14.66 2.16 13.92 2.00 13.48 C1.94 13.28 1.84 13.03 1.79 12.92 C1.69 12.69 1.68 12.42 1.76 12.27 C1.85 12.10 2.13 12.06 3.54 12.03 C5.07 11.99 5.11 11.98 5.21 11.62 C5.24 11.50 5.34 11.25 5.43 11.06 L5.59 10.71 L5.59 9.14 C5.59 7.81 5.61 7.53 5.68 7.34 C5.80 7.04 6.06 6.91 6.53 6.92 C6.89 6.93 7.13 6.83 7.20 6.66 C7.22 6.62 7.25 5.97 7.27 5.23 C7.29 4.48 7.32 3.78 7.35 3.67 C7.38 3.54 7.47 3.42 7.58 3.34 C7.74 3.22 7.81 3.21 8.34 3.23 C8.66 3.23 8.99 3.22 9.06 3.19 C9.28 3.10 9.37 2.86 9.37 2.38 C9.37 1.88 9.48 1.61 9.72 1.50 C9.92 1.40 10.28 1.46 10.45 1.63 C10.56 1.74 10.58 1.81 10.58 2.22 C10.58 2.48 10.60 2.75 10.64 2.82 C10.77 3.10 11.28 3.11 11.56 2.83 C11.69 2.70 11.70 2.65 11.72 2.02 C11.73 1.46 11.75 1.33 11.84 1.24 C11.89 1.18 11.95 1.06 11.97 0.98 C12.03 0.76 12.28 0.77 12.36 0.99 C12.41 1.11 12.47 1.15 12.62 1.18 C12.90 1.23 12.97 1.37 12.98 1.95 C12.99 2.56 13.05 2.80 13.24 2.97 C13.37 3.10 13.39 3.10 14.24 3.08 C15.38 3.06 15.44 3.09 15.58 3.76 C15.64 4.02 15.67 4.53 15.68 5.35 C15.70 6.63 15.72 6.73 15.98 6.85 C16.05 6.88 16.22 6.91 16.34 6.91 C16.61 6.91 16.78 7.01 16.91 7.25 C16.98 7.38 16.99 7.59 16.99 8.27 C16.99 9.39 17.08 10.71 17.17 10.94 C17.28 11.18 17.61 11.49 17.89 11.59 C18.05 11.64 18.56 11.67 19.94 11.70 C22.50 11.74 22.73 11.80 22.73 12.41 C22.73 12.60 21.89 14.34 21.34 15.29 C21.24 15.45 21.12 15.71 21.07 15.87 C20.95 16.22 20.70 16.62 20.52 16.74 C20.41 16.81 20.32 16.82 19.81 16.76 C18.79 16.66 18.34 16.77 16.49 17.56 C16.32 17.63 16.08 17.69 15.94 17.69 C15.66 17.70 15.16 17.57 14.97 17.44 C14.90 17.40 14.66 17.29 14.42 17.21 C14.19 17.12 13.76 16.96 13.46 16.85 C13.01 16.69 12.86 16.65 12.50 16.65 C11.70 16.65 10.95 16.87 9.57 17.49 C9.13 17.69 8.60 17.74 8.24 17.62 Z M15.57 10.85 L15.75 10.69 L15.74 9.67 C15.74 9.11 15.72 8.59 15.70 8.52 C15.68 8.45 15.59 8.34 15.49 8.29 C15.34 8.21 15.13 8.19 14.08 8.18 C12.70 8.16 12.54 8.17 12.35 8.36 C12.21 8.50 12.21 8.51 12.23 9.39 C12.23 10.02 12.22 10.31 12.17 10.40 C12.08 10.57 12.13 10.77 12.29 10.86 C12.40 10.93 12.64 10.94 14.97 11.00 C15.37 11.01 15.40 11.00 15.57 10.85 Z M10.34 10.83 C10.55 10.72 10.61 10.54 10.53 10.30 C10.49 10.19 10.48 9.86 10.50 9.41 C10.55 8.15 10.58 8.17 8.75 8.17 C7.38 8.17 7.14 8.20 7.03 8.42 C7.00 8.48 6.96 9.01 6.95 9.60 C6.94 10.57 6.95 10.70 7.03 10.78 C7.11 10.86 7.28 10.88 8.07 10.91 C9.52 10.96 10.13 10.94 10.34 10.83 Z M18.50 10.74 C18.42 10.68 18.35 10.57 18.35 10.51 C18.35 10.35 18.50 10.09 18.64 10.02 C18.82 9.92 20.50 9.95 20.70 10.05 C21.02 10.22 21.06 10.60 20.78 10.74 C20.68 10.78 20.28 10.82 19.64 10.84 C18.69 10.86 18.65 10.86 18.50 10.74 Z M10.76 6.73 C10.98 6.58 11.01 6.43 11.01 5.62 C11.01 4.33 11.05 4.36 9.72 4.37 C8.71 4.38 8.58 4.41 8.49 4.64 C8.41 4.85 8.43 6.41 8.51 6.58 C8.64 6.83 8.78 6.86 9.73 6.84 C10.47 6.83 10.63 6.81 10.76 6.73 Z M14.06 6.77 C14.35 6.65 14.41 6.45 14.41 5.52 C14.41 5.08 14.39 4.69 14.38 4.64 C14.30 4.44 14.03 4.37 13.39 4.37 C12.27 4.38 12.21 4.44 12.20 5.64 C12.19 6.80 12.23 6.84 13.25 6.85 C13.67 6.85 13.93 6.83 14.06 6.77 Z",
  officer: "M4.12 22.80 C2.61 22.75 2.46 22.72 2.24 22.42 C2.06 22.15 2.14 20.95 2.43 19.88 C2.62 19.13 2.68 19.00 3.08 18.33 C3.38 17.84 3.54 17.67 4.01 17.31 C4.32 17.07 4.63 16.87 4.69 16.84 C4.75 16.82 5.07 16.68 5.40 16.52 C5.73 16.37 6.16 16.19 6.36 16.12 C9.22 15.11 9.02 15.14 9.30 15.73 C9.44 16.01 9.46 16.13 9.42 16.59 C9.40 16.96 9.33 17.24 9.20 17.50 C8.99 17.93 8.92 18.00 8.65 18.07 C8.49 18.11 8.40 18.06 8.07 17.76 C7.71 17.43 7.63 17.40 7.35 17.40 C6.97 17.40 5.99 17.76 5.34 18.15 C4.58 18.60 4.03 19.44 3.83 20.42 C3.75 20.81 3.75 20.88 3.86 21.05 C3.93 21.15 4.06 21.26 4.15 21.30 C4.25 21.34 5.08 21.33 6.19 21.29 C7.22 21.25 8.62 21.23 9.30 21.25 C10.52 21.28 10.53 21.28 10.70 21.12 C10.87 20.95 10.92 20.59 10.88 19.81 C10.86 19.31 10.92 19.07 11.18 18.73 C11.35 18.51 11.42 18.32 11.46 18.02 C11.52 17.54 11.74 17.28 12.04 17.35 C12.24 17.40 12.43 17.75 12.43 18.06 C12.43 18.16 12.53 18.40 12.65 18.60 C12.86 18.94 12.88 19.02 12.94 19.90 C12.97 20.42 13.04 20.91 13.08 21.00 C13.27 21.37 13.37 21.39 16.14 21.37 C19.33 21.35 19.57 21.33 19.80 21.10 C19.96 20.94 19.97 20.89 19.93 20.43 C19.89 19.93 19.58 19.15 19.24 18.68 C18.96 18.28 17.70 17.66 16.97 17.57 C16.49 17.50 16.30 17.56 15.96 17.89 C15.35 18.49 14.88 18.15 14.57 16.85 C14.36 15.99 14.50 15.48 15.03 15.23 C15.27 15.12 15.30 15.12 15.72 15.27 C16.13 15.42 17.68 16.13 18.14 16.38 C18.26 16.45 18.60 16.62 18.89 16.76 C19.61 17.11 20.19 17.67 20.62 18.39 C21.33 19.59 21.80 21.86 21.46 22.44 C21.24 22.81 21.14 22.83 19.32 22.79 C17.20 22.75 16.52 22.75 10.51 22.80 C7.80 22.82 4.92 22.82 4.12 22.80 Z M10.91 14.91 C8.97 13.91 7.57 12.12 7.07 9.99 C6.91 9.30 7.10 6.88 7.36 6.38 C7.52 6.07 7.48 5.74 7.25 5.42 C7.13 5.26 7.00 5.11 6.96 5.08 C6.76 4.95 6.54 4.30 6.53 3.83 C6.53 2.82 7.19 2.30 9.45 1.53 C10.41 1.19 11.37 1.00 12.05 1.00 C12.42 1.00 13.69 1.23 13.90 1.34 C13.97 1.38 14.28 1.49 14.59 1.60 C15.43 1.89 16.40 2.36 16.71 2.63 C17.03 2.91 17.27 3.26 17.39 3.64 C17.54 4.09 17.27 4.80 16.67 5.55 C16.42 5.86 16.42 5.97 16.71 7.08 C17.10 8.60 16.91 10.31 16.19 11.78 C16.07 12.01 15.98 12.22 15.98 12.25 C15.98 12.27 15.82 12.52 15.63 12.80 C14.98 13.76 14.18 14.40 13.05 14.88 C11.93 15.35 11.78 15.36 10.91 14.91 Z M12.80 13.26 C13.38 12.99 14.09 12.39 14.58 11.74 C15.12 11.04 15.34 10.21 15.34 8.91 C15.34 8.25 15.33 8.22 15.13 8.02 C14.88 7.77 14.79 7.76 14.09 7.99 C13.29 8.26 12.63 8.32 11.54 8.24 C10.63 8.18 10.29 8.10 9.61 7.81 C8.94 7.52 8.67 7.72 8.59 8.54 C8.50 9.56 8.71 10.59 9.20 11.48 C9.48 11.98 10.69 13.13 11.18 13.36 C11.56 13.54 12.28 13.50 12.80 13.26 Z M13.63 5.04 C14.18 4.95 15.11 4.53 15.36 4.27 C15.68 3.92 15.67 3.59 15.32 3.40 C15.23 3.35 14.79 3.21 14.34 3.09 C13.89 2.96 13.24 2.76 12.89 2.63 C12.02 2.32 11.62 2.35 10.52 2.80 C10.08 2.99 9.52 3.20 9.27 3.27 C8.79 3.42 8.38 3.74 8.38 3.96 C8.38 4.03 8.43 4.16 8.48 4.24 C8.62 4.43 10.07 5.03 10.62 5.11 C11.13 5.19 12.99 5.15 13.63 5.04 Z",
  truck: "M5.36 19.25 C4.99 19.15 4.16 18.69 3.97 18.48 C3.87 18.37 3.71 18.14 3.61 17.96 C3.51 17.79 3.32 17.55 3.20 17.43 C3.00 17.24 2.93 17.22 2.33 17.18 C1.59 17.14 1.38 17.05 1.30 16.77 C1.27 16.67 1.25 13.93 1.25 10.69 C1.25 5.19 1.25 4.78 1.37 4.57 C1.44 4.43 1.58 4.31 1.69 4.28 C1.80 4.25 4.65 4.23 8.02 4.23 C13.76 4.23 14.18 4.24 14.39 4.35 C14.77 4.55 14.82 4.74 14.87 6.10 C14.90 6.79 14.95 7.40 14.99 7.47 C15.09 7.66 15.30 7.69 15.93 7.60 C16.28 7.55 17.02 7.52 17.79 7.54 C18.98 7.56 19.08 7.57 19.33 7.73 C19.60 7.90 20.13 8.64 20.56 9.43 C21.00 10.26 21.45 10.91 22.04 11.58 L22.67 12.30 L22.74 13.20 C22.77 13.69 22.79 14.68 22.78 15.39 C22.75 16.67 22.75 16.68 22.57 16.87 C22.35 17.09 22.00 17.18 21.35 17.18 C21.08 17.18 20.81 17.21 20.73 17.25 C20.66 17.29 20.46 17.53 20.28 17.77 C19.78 18.48 19.31 18.86 18.83 18.96 C18.30 19.07 17.66 19.01 17.20 18.81 C16.78 18.63 16.38 18.23 16.05 17.64 C15.93 17.43 15.78 17.23 15.71 17.19 C15.60 17.13 14.92 17.13 9.99 17.21 C8.32 17.23 8.36 17.22 8.14 17.83 C7.99 18.25 7.38 18.83 6.86 19.06 C6.44 19.25 5.71 19.34 5.36 19.25 Z M18.72 17.74 C19.00 17.57 19.10 17.41 19.10 17.14 C19.10 16.96 19.09 16.95 18.80 17.00 C17.90 17.13 17.78 17.13 17.48 16.98 C17.07 16.77 17.07 16.52 17.47 16.16 C17.72 15.93 17.79 15.90 18.16 15.90 C18.38 15.90 18.61 15.87 18.67 15.83 C18.77 15.78 18.76 15.75 18.65 15.64 C18.49 15.48 17.65 15.49 17.32 15.66 C16.99 15.83 16.77 16.46 16.98 16.67 C17.03 16.71 17.11 16.90 17.18 17.09 C17.27 17.36 17.36 17.48 17.63 17.66 C18.04 17.93 18.37 17.96 18.72 17.74 Z M6.38 17.73 C6.48 17.68 6.60 17.57 6.66 17.49 C6.83 17.23 6.60 17.07 5.92 17.01 C4.92 16.92 4.94 16.92 4.91 17.09 C4.88 17.33 5.03 17.54 5.35 17.68 C5.69 17.84 6.14 17.86 6.38 17.73 Z M7.37 16.18 C7.41 16.00 6.76 15.19 6.50 15.08 C5.92 14.84 5.32 15.01 5.09 15.47 C4.82 16.00 4.90 16.11 5.33 15.80 C5.77 15.47 6.33 15.58 6.91 16.10 C7.19 16.34 7.33 16.37 7.37 16.18 Z M13.17 15.76 C13.53 15.58 13.57 15.41 13.54 14.31 C13.52 13.76 13.53 11.77 13.58 9.89 C13.62 8.01 13.63 6.35 13.60 6.21 C13.57 6.06 13.46 5.85 13.35 5.74 L13.15 5.54 L8.07 5.56 L2.99 5.58 L2.79 5.77 L2.59 5.97 L2.54 9.50 C2.48 13.28 2.51 15.12 2.65 15.41 C2.76 15.63 3.03 15.67 3.23 15.50 C3.31 15.43 3.52 15.17 3.69 14.93 C4.01 14.47 4.58 14.04 5.11 13.85 C5.48 13.73 6.52 13.67 6.86 13.77 C7.33 13.89 7.97 14.38 8.48 14.99 C9.18 15.82 9.11 15.79 10.65 15.84 C12.34 15.90 12.91 15.88 13.17 15.76 Z M21.25 15.69 C21.35 15.61 21.47 15.42 21.51 15.28 C21.61 14.93 21.69 13.43 21.62 13.17 C21.60 13.06 21.33 12.71 21.02 12.39 C20.30 11.64 20.05 11.31 19.86 10.85 C19.78 10.64 19.54 10.19 19.34 9.83 C19.05 9.33 18.92 9.16 18.68 9.03 C18.12 8.72 17.25 8.76 17.00 9.11 C16.88 9.29 16.86 10.39 16.97 10.81 C17.10 11.27 17.30 11.36 18.15 11.36 C18.96 11.36 19.27 11.46 19.38 11.74 C19.45 11.94 19.35 12.27 19.17 12.46 C19.04 12.59 18.92 12.60 17.84 12.62 C16.33 12.65 16.15 12.62 15.85 12.21 L15.61 11.90 L15.63 10.48 C15.65 8.93 15.61 8.73 15.30 8.73 C15.21 8.73 15.10 8.79 15.06 8.86 C15.03 8.93 14.98 10.41 14.95 12.15 C14.91 14.98 14.91 15.35 15.01 15.54 C15.19 15.89 15.40 15.84 15.92 15.31 C16.40 14.83 16.72 14.58 17.11 14.38 C17.43 14.22 18.71 14.19 19.13 14.33 C19.30 14.40 19.67 14.69 20.13 15.13 C20.54 15.52 20.91 15.83 20.97 15.83 C21.02 15.83 21.15 15.77 21.25 15.69 Z",
  box: "M11.31 22.81 C11.16 22.78 10.90 22.69 10.72 22.59 C10.54 22.50 10.21 22.36 9.99 22.27 C9.77 22.18 9.53 22.06 9.47 22.00 C9.41 21.95 9.06 21.79 8.70 21.66 C8.34 21.53 7.81 21.31 7.51 21.16 C5.77 20.33 5.01 19.97 4.97 19.97 C4.93 19.97 3.38 19.27 2.61 18.90 C2.36 18.78 2.06 18.66 1.96 18.63 C1.85 18.60 1.71 18.54 1.64 18.49 C1.31 18.24 1.31 18.31 1.29 12.30 C1.27 5.73 1.21 6.25 2.00 5.80 C2.25 5.66 2.73 5.42 3.07 5.28 C3.41 5.13 3.79 4.97 3.91 4.91 C4.04 4.85 4.66 4.57 5.29 4.29 C5.92 4.01 7.06 3.48 7.82 3.11 C8.58 2.74 9.43 2.36 9.70 2.26 C9.97 2.16 10.29 2.02 10.41 1.94 C10.69 1.74 11.66 1.42 11.96 1.42 C12.31 1.42 13.03 1.69 13.61 2.03 C13.88 2.19 14.19 2.35 14.30 2.38 C14.41 2.41 14.66 2.53 14.88 2.65 C15.09 2.76 15.34 2.88 15.44 2.92 C15.54 2.95 15.99 3.17 16.44 3.41 C16.89 3.65 17.73 4.06 18.31 4.33 C18.90 4.59 19.49 4.87 19.62 4.95 C19.76 5.03 20.06 5.16 20.29 5.24 C20.51 5.32 20.89 5.51 21.11 5.67 C21.34 5.82 21.57 5.94 21.62 5.94 C21.79 5.94 22.33 6.62 22.38 6.88 C22.40 7.02 22.41 9.48 22.40 12.34 C22.37 18.14 22.40 17.79 21.85 18.28 C21.69 18.42 21.49 18.56 21.40 18.59 C20.72 18.87 19.72 19.32 19.42 19.48 C19.23 19.58 18.83 19.76 18.54 19.87 C17.86 20.12 17.71 20.19 16.22 20.91 C15.52 21.25 14.77 21.59 14.55 21.67 C14.33 21.74 13.81 21.99 13.40 22.22 C12.69 22.62 11.97 22.90 11.70 22.88 C11.63 22.87 11.46 22.84 11.31 22.81 Z M10.91 20.53 C11.03 20.34 11.04 20.05 11.03 16.46 C11.02 14.04 10.98 12.50 10.93 12.35 C10.83 12.06 10.25 11.69 9.45 11.42 C9.14 11.32 8.75 11.13 8.57 11.00 C8.25 10.77 7.91 10.60 6.63 10.04 C6.27 9.89 5.43 9.49 4.75 9.16 C3.32 8.46 3.10 8.40 2.89 8.61 C2.75 8.75 2.74 8.93 2.69 11.74 C2.66 13.38 2.63 15.17 2.61 15.72 C2.59 16.96 2.60 17.06 2.92 17.43 C3.12 17.66 3.34 17.80 3.78 17.97 C4.10 18.09 4.77 18.38 5.25 18.60 C7.09 19.42 7.53 19.61 8.15 19.82 C8.50 19.94 8.91 20.11 9.07 20.20 C9.57 20.48 10.27 20.73 10.52 20.74 C10.71 20.74 10.80 20.69 10.91 20.53 Z M13.70 20.55 C13.97 20.45 14.41 20.27 14.68 20.14 C14.96 20.02 15.27 19.90 15.38 19.87 C15.48 19.85 16.37 19.41 17.34 18.91 C18.31 18.41 19.24 17.96 19.41 17.90 C20.49 17.56 20.78 17.27 20.90 16.39 C20.94 16.09 20.97 14.33 20.95 12.40 C20.93 9.13 20.92 8.94 20.79 8.79 C20.54 8.52 20.20 8.58 19.18 9.08 C18.67 9.33 17.58 9.84 16.75 10.20 C13.26 11.74 12.80 12.00 12.60 12.52 C12.44 12.96 12.31 19.68 12.46 20.20 C12.62 20.78 12.90 20.86 13.70 20.55 Z M13.10 10.25 C13.53 10.04 14.05 9.79 14.26 9.70 C14.72 9.50 14.91 9.34 14.91 9.15 C14.91 8.98 14.64 8.72 14.30 8.57 C14.15 8.51 13.73 8.31 13.37 8.13 C13.00 7.94 12.52 7.74 12.30 7.67 C11.91 7.56 11.85 7.56 11.24 7.71 C10.52 7.89 8.97 8.59 8.77 8.83 C8.43 9.24 8.57 9.43 9.47 9.80 C9.83 9.95 10.45 10.21 10.85 10.38 C11.80 10.80 12.05 10.78 13.10 10.25 Z M6.94 8.28 C7.12 8.22 7.39 8.09 7.54 7.99 C7.82 7.82 8.07 7.71 9.16 7.25 C10.07 6.87 10.24 6.52 9.66 6.20 C9.49 6.10 9.18 5.99 8.97 5.94 C8.76 5.90 8.30 5.69 7.94 5.47 C7.02 4.90 6.73 4.89 5.91 5.37 C5.57 5.57 4.97 5.85 4.58 6.01 C4.19 6.17 3.80 6.35 3.72 6.43 C3.49 6.62 3.53 6.90 3.79 7.09 C4.21 7.39 6.25 8.40 6.43 8.40 C6.53 8.40 6.76 8.34 6.94 8.28 Z M18.55 7.72 C19.10 7.45 19.63 7.16 19.72 7.07 C20.09 6.73 19.88 6.44 19.02 6.09 C18.68 5.95 18.19 5.69 17.92 5.51 C17.15 4.99 16.52 4.98 15.82 5.46 C15.60 5.61 15.15 5.83 14.82 5.96 C13.95 6.27 13.70 6.48 13.80 6.79 C13.87 7.00 14.24 7.20 15.10 7.50 C15.53 7.65 16.00 7.84 16.17 7.94 C16.62 8.21 17.00 8.32 17.29 8.27 C17.43 8.24 18.00 8.00 18.55 7.72 Z M13.26 5.18 C14.48 4.57 14.53 4.53 14.53 4.29 C14.53 4.07 14.26 3.85 13.78 3.67 C13.58 3.60 13.09 3.41 12.70 3.24 C12.17 3.02 11.91 2.95 11.75 2.99 C11.44 3.05 9.47 3.93 9.30 4.08 C9.00 4.35 9.16 4.50 10.60 5.22 C11.88 5.87 11.90 5.87 13.26 5.18 Z",
  plane: "M9.05 20.72 C8.96 20.69 8.82 20.54 8.72 20.38 C8.51 20.05 7.95 18.75 7.77 18.19 C7.70 17.98 7.57 17.69 7.48 17.56 C7.39 17.43 7.25 17.13 7.17 16.89 C7.10 16.66 6.70 15.78 6.28 14.93 C5.48 13.28 5.44 13.23 5.04 13.38 C4.94 13.42 4.72 13.58 4.55 13.74 C4.37 13.89 4.01 14.20 3.74 14.41 C3.47 14.62 3.03 14.98 2.78 15.20 C2.08 15.81 1.85 15.97 1.64 15.97 C1.36 15.97 1.29 15.84 1.30 15.34 C1.32 14.88 1.26 14.78 1.01 14.78 C0.91 14.78 0.90 14.70 0.90 14.09 L0.90 13.40 L1.13 13.26 C1.26 13.19 1.36 13.10 1.36 13.06 C1.36 13.02 1.64 12.69 1.99 12.33 C2.89 11.39 3.04 11.08 2.76 10.75 C2.64 10.61 1.15 9.82 0.99 9.82 C0.92 9.82 0.90 9.71 0.90 9.33 C0.90 8.85 0.90 8.84 1.09 8.81 C1.31 8.76 1.37 8.61 1.31 8.16 C1.28 7.86 1.29 7.83 1.51 7.63 C1.64 7.51 1.76 7.32 1.78 7.22 C1.83 7.02 1.99 6.99 2.28 7.14 C2.38 7.19 2.74 7.27 3.07 7.32 C3.61 7.39 3.71 7.38 4.04 7.28 C4.57 7.12 4.78 7.17 5.25 7.61 C5.69 8.01 5.91 8.09 6.26 7.94 C6.49 7.84 7.26 7.22 7.97 6.55 C9.16 5.42 9.45 5.17 10.00 4.78 C10.68 4.29 10.92 4.20 11.52 4.20 C12.09 4.20 12.34 4.32 12.56 4.69 C13.08 5.58 12.45 6.52 9.69 8.99 C8.65 9.92 8.56 10.10 8.72 10.95 C8.77 11.22 8.83 11.65 8.86 11.90 C8.92 12.58 9.13 13.65 9.46 15.04 C10.14 17.88 10.43 19.43 10.37 19.85 C10.33 20.09 10.10 20.34 9.72 20.56 C9.37 20.76 9.22 20.79 9.05 20.72 Z",
};
const svg = (k, px) => ICON_PATH[k]
  ? `<svg viewBox="0 0 24 24" width="${px||21}" height="${px||21}" fill="currentColor"><path
      fill-rule="evenodd" d="${ICON_PATH[k]}"/></svg>`
  : `<svg viewBox="0 0 24 24" width="${px||21}" height="${px||21}" fill="none"
  stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${I[k]}</svg>`;

/* ── колір за видом перевезення (як у макеті користувачки) ──────────── */
/* Кольори ЗМІРЯНІ з макета користувачки (піксельні проби по кожному ряду):
   море #2269bc, авто #954e17, авіа #8f4aa8. Раніше я підбирала «схожі». */
const MODE_PAL = {
  sea : {c:"#2269bc", bg:"#e9f1fb", nm:"Море"},
  air : {c:"#8f4aa8", bg:"#f5eaf8", nm:"Авіа"},
  road: {c:"#954e17", bg:"#fbf0e3", nm:"Авто"},
  rail: {c:"#1f7a5a", bg:"#e4f3ed", nm:"Залізниця"},
};
/* Галочка з бази. NocoDB віддає такі поля по-різному: true/false, 1/0 або
   рядком «true» — тому перевіряємо всі три випадки, а не одне з них. */
const isOn = (r, k) => { const v = r[k];
  return v === true || v === 1 || String(v).toLowerCase() === "true"; };

const modeOf = r => air(r) ? "air"
  : (/^авто$/i.test(s(r,"Вид перевезення")) ? "road" : (rail(r) ? "rail" : "sea"));
const pal = r => MODE_PAL[modeOf(r)];
/* Хто везе. Для моря це судно, для АВІА судна немає за визначенням — там має
   бути авіалінія (вимога користувачки 13.08.2026).
   Джерело беремо гнучко: перше заповнене з «Перевізник» і «Лінія». Перевірено
   13.08 — зараз обидва порожні в усіх 6 авіа-угодах (єдина заповнена «Лінія»
   містить «Maersk», що для авіа явно не те), тому поки покаже прочерк.
   Щойно менеджери почнуть заповнювати БУДЬ-ЯКЕ з двох — з'явиться саме воно,
   і правити код не доведеться. */
const carrier = r => modeOf(r) === "air"
  ? (s(r,"Перевізник") || s(r,"Лінія"))
  : s(r,"Судно");
const plural = (n, one, few, many) => {
  const a = Math.abs(n) % 100, b = a % 10;
  if (a > 10 && a < 20) return many; if (b > 1 && b < 5) return few;
  return b === 1 ? one : many;
};
const days = (a, b) => {
  if (!a || !b) return null;
  const d = Math.round((new Date(b) - new Date(a)) / 864e5);
  return d >= 0 ? d : null;
};

/* ── схема руху ─────────────────────────────────────────────────────────
   Ланцюжки продиктувала користувачка 01.08.2026, дослівно:
   ІМПОРТ: стафіровка → митне оформлення → порт відправлення → в морі/в повітрі/
     в дорозі → [перевалка] → порт/аеропорт прибуття → завантаження на авто/потяг
     → [сухий порт] → кордон → митне оформлення → вантаж доставлено.
   ЕКСПОРТ: стафіровка (авто/потяг) → митне оформлення → кордон → порт/аеропорт
     відправлення → в морі/повітрі/дорозі → [перевалка] → митне оформлення →
     вантаж доставлено.
   Перевалка буває і для АВІА теж — обмеження на море прибрано на її зауваження.
   Дат митного оформлення в системі НЕМАЄ (ні експортного, ні імпортного) —
   ці кроки малюємо без дати, лише як етап. */
function steps(r){
  const A = air(r), R = rail(r), imp = s(r,"Напрямок") !== "Експорт";
  const route = routeArrows(s(r,"Маршрут")).split("→").map(x=>x.trim()).filter(Boolean);
  const from = route[0] || "", to = route.length > 1 ? route[1] : "";
  /* Кінцеву точку беремо ТІЛЬКИ з однойменного поля. Остання ланка «Маршруту»
     часто сухий порт (Мостиська), а не місце доставки — підставляти її не можна
     (зауваження користувачки 02.08.2026). Немає поля — не показуємо нічого. */
  const fin  = s(r,"Кінцева точка доставки");
  const etd  = s(r,"ETD (факт)") || s(r,"ETD (план)"), etdF = !!s(r,"ETD (факт)");
  const eta  = s(r,"ETA порт (факт)") || s(r,"ETA"),   etaF = !!s(r,"ETA порт (факт)");
  /* ГОЛОВНЕ плече — за самим плечем, а не за «Вид перевезення».
     Було: угода «фрахт+ТЕО+залізниця» малювала вузол «В морі» ПОТЯГОМ, бо
     іконка бралася з виду перевезення. Залізниця там — доставка ДО порту, а не
     сам рейс (02.08.2026); у потяга тепер власний вузол «Завантаження на потяг».
     Суто залізнична відправка (залізниця є, але немає ні лінії, ні коносамента,
     ні судна) називається «Трейн» — назву дала користувачка 02.08.2026.
     Таких угод у платформі поки немає. */
  const seaLeg   = !!(s(r,"Лінія") || s(r,"BL") || s(r,"Судно"));
  const railOnly = !A && R && !seaLeg;
  const moveI = A ? "plane" : (modeOf(r) === "road" ? "truck" : (railOnly ? "train" : "ship"));
  const moveT = A ? "В повітрі"
              : (modeOf(r) === "road" ? "В дорозі" : (railOnly ? "Трейн" : "В морі"));

  const transship = () => {
    const tp = s(r,"Порт перевалки");
    if (!tp) return [];
    const ta = s(r,"Перевалка (прибуття)"), td = s(r,"Перевалка (відправлення)");
    return [{ k:"tship", t:"Перевалка", i:"swap", d:ta, d2:td, f:true, p:tp }];
  };

  const stX = s(r,"Статус");
  /* Вид наземного плеча: статус свіжіший за довідкове «Вид перевезення». */
  const byTrainX = /потяг/i.test(stX) ? true : (/на авто/i.test(stX) ? false : R);

  if (!imp){
    /* ЕКСПОРТ — за вказівкою користувачки 02.08.2026:
       «прибрати зі схем Митне оформлення при експорті, але поставити
       перевезення. Автоперевезення стоїть перед Стафіровкою (додай до неї і
       оформлення). У випадку перевезення на потягу — після стафіровки
       додається Сухий порт та потім Завантаження на потяг з датою.» */
    const pre = [
      { k:"carauto", t:"Завантаження<br>на авто", i:"truck",
        d:s(r,"Подача авто (факт)") || s(r,"Подача авто (план)"),
        f:!!s(r,"Подача авто (факт)"), p:from },
      { k:"stuff", t:"Стафіровка<br>та оформлення", i:"warehouse",
        d:s(r,"Stuffing"), f:true, p:from },
    ];
    if (byTrainX){
      pre.push({ k:"dry", t:"Сухий порт", i:"crane", d:s(r,"ETA сухий порт"),
                 f:false, p:s(r,"Сухий порт") });
      pre.push({ k:"land", t:"Завантаження<br>на потяг", i:"train",
                 d:s(r,"Постановка/завантаження (факт)") || s(r,"Постановка/завантаження (план)"),
                 f:!!s(r,"Постановка/завантаження (факт)"), p:"" });
    }
    return pre.concat([
      { k:"border", t:"Кордон",              i:"border",    d:s(r,"На кордоні") || s(r,"Перетин кордону (факт)"), f:true, p:"" },
      { k:"pol", t:A?"Аеропорт відправлення":"Порт відправлення", i:"crane",
        d:s(r,"Здача в порт (факт)") || s(r,"Гейт ін"), f:true, p:from },
      { k:"move", t:moveT, i:moveI, d:etd, f:etdF, p:s(r,"Судно"), dur:days(etd, eta) },
    ], transship(), [
      /* Останній крок експорту — порт призначення (вказівка користувачки
         02.08.2026). Місце беремо з ОСТАННЬОЇ ланки маршруту, а не з другої:
         «Солоницівка → Гданськ → Фрімантл» — призначення Фрімантл. */
      { k:"pod", t:A?"Аеропорт призначення":"Порт призначення", i:A?"plane":"crane",
        /* якщо в «Маршруті» лише одна ланка — місця призначення ми не знаємо,
           і підставляти туди ж порт відправлення не можна (угода 259) */
        d:eta, f:etaF, p:(route.length > 1 ? route[route.length - 1] : "") },
    ],
    /* Імпортне розмитнення й доставка вантажу для ЕКСПОРТУ показуються ЛИШЕ на
       умовах DAP/DDU — за інших умов наша відповідальність там закінчується
       (вказівка користувачки 02.08.2026). Поля з Інкотермс в угоді ПОКИ НЕМАЄ
       (перевірено по всіх 80 колонках), тому умова завжди хибна і кроків немає.
       Щойно поле з'явиться — вони почнуть показуватись самі. */
    (DAP_DDU.test(s(r,"Умови поставки (Інкотермс)")) ? [
      { k:"done", t:"Вантаж доставлено",   i:"box",
        d:s(r,"Вивантаження у отримувача (факт)") || s(r,"Планова до клієнта (факт)") || eta,
        f:!!s(r,"Вивантаження у отримувача (факт)"), p:fin || to },
    ] : []));
  }

  /* ІМПОРТ */
  /* «Гейт аут» — це ВИЇЗД З ПОРТУ, тобто дата, коли контейнер поставили на потяг
     (або на авто, залежно від вантажу). Пояснення користувачки 21.08.2026.
     Тому це ФАКТ завантаження, а не щось про доставку.

     «ETA сухий порт» — НЕ прибуття в сухий порт. Маерск, прийнявши заявку на
     потяг, кладе туди ПЛАНОВУ ДАТУ ЗАВАНТАЖЕННЯ НА ПОТЯГ (їхня власна хиба,
     можливо колись виправлять). Тому це план ЦЬОГО САМОГО кроку, і показуємо
     його лише поки немає факту.
     Планову дату прибуття в сухий порт дає вже залізничний оператор листом —
     у базі такого поля поки немає, тому крок «Сухий порт» лишається без дати. */
  const car  = s(r,"Подача авто (факт)") || s(r,"Гейт аут")
            || s(r,"Подача авто (план)") || s(r,"ETA сухий порт");
  const carF = !!(s(r,"Подача авто (факт)") || s(r,"Гейт аут"));
  /* Вид наземного плеча беремо зі СТАТУСУ, якщо він прямо його називає, і лише
     інакше — з «Вид перевезення». Причина (угода 239, 02.08.2026): трекінг
     поставив «Завантажений на потяг», а в полі виду стояло «фрахт+ТЕО+авто»,
     і схема малювала авто. Статус тут свіжіший за довідкове поле. */
  const byTrain = byTrainX;
  /* Порядок наземного плеча в імпорті: завантажили на потяг/авто в порту за
     кордоном → перетнули КОРДОН → приїхали в СУХИЙ ПОРТ, який уже в Україні
     → віддали клієнту. Було навпаки — сухий порт стояв перед кордоном, тобто
     ніби за кордоном (зауваження користувачки 21.08.2026).
     Митного оформлення в схемі немає взагалі — ні експортного, ні імпортного:
     клієнту показуємо рух вантажу, а не оформлення (її ж вказівка). */
  const land = [];
  land.push({ k:"land", t: byTrain ? "Завантажений на потяг" : "Завантажений на авто",
              i: byTrain ? "train" : "truck", d: car, f: carF, p:"" });
  land.push({ k:"border", t:"Кордон", i:"border",
              d:s(r,"На кордоні") || s(r,"Перетин кордону (факт)"), f:true, p:"" });
  if (R || s(r,"ETA сухий порт"))
    land.push({ k:"dry", t:"Сухий порт", i:"crane", d:"", f:false, p:s(r,"Сухий порт") });
  return [
    { k:"stuff", t:"Стафіровка",         i:"warehouse", d:s(r,"Stuffing"), f:true, p:from },
    { k:"pol", t:A?"Аеропорт відправлення":"Порт відправлення", i:"crane",
      d:s(r,"Здача в порт (факт)") || s(r,"Гейт ін"), f:true, p:from },
    { k:"move", t:moveT, i:moveI, d:etd, f:etdF, p:s(r,"Судно"), dur:days(etd, eta) },
  ].concat(transship(), [
    { k:"pod", t:A?"Аеропорт прибуття":"Порт прибуття", i:A?"plane":"crane", d:eta, f:etaF, p:to },
  ], land, [
    { k:"done", t:"Вантаж доставлено",  i:"box",
      d:s(r,"Вивантаження у отримувача (факт)") || s(r,"Планова до клієнта (факт)"),
      f:true, p:fin },
  ]);
}

/* Стан кроків рахується ОДИН раз і в одному місці. І велика схема в картці,
   і мініатюра в рядку беруть його звідси: дві копії цієї логіки неминуче
   розійшлися б, а вона тут найтонша (див. коментарі нижче про угоди 256 і 259). */
/* Порядок етапів перевезення. Живе НА РІВНІ МОДУЛЯ, бо ним користуються
   двоє: схема руху (який вузол підсвітити) і сортування таблиці (що далі
   просунулось, те вище). Другого списку статусів у системі бути не має. */
const ST_STEP = {
  "Букінг":"stuff", "Виконується":"stuff", "Стафіровка":"stuff",
  "В порту відправлення":"pol", "Завантажений на судно":"move", "В морі":"move",
  /* «В порту призначення» (до 11.08.2026 звався «Прибув у порт») тут НЕ БУВ
     перелічений з моменту появи статусу 05.08.2026 — угода з ним не знаходила
     свого кроку на схемі взагалі. Судно вже в порту, вантаж ще на борту, тому
     крок той самий, що й у вивантаження: "pod". */
  /* «В порту перевалки» — вантаж ще пливе, просто зараз на проміжному терміналі.
     Для клієнта це той самий крок «в дорозі», а не прибуття. */
  "В порту перевалки":"move",
  "В порту призначення":"pod",
  "Вивантажений в порту прибуття":"pod",
  "Завантажений на авто":"land", "Завантажений на потяг":"land",
  "Вивантажений в сухому порту":"dry", "На кордоні":"border",
  "Вантаж доставлено":"done",
};
/* Порядок статусів — щоб знайти найближчий крок, якщо точного в ланцюжку немає. */
const ST_ORDER = ["Букінг","Виконується","Стафіровка","В порту відправлення",
  "Завантажений на судно","В морі","В порту перевалки","В порту призначення","Вивантажений в порту прибуття",
  "Завантажений на авто","Завантажений на потяг","Вивантажений в сухому порту",
  "На кордоні","Вантаж доставлено"];

function stepState(r){
  const st = steps(r), P = pal(r), delivered = done(r);
  /* ПОТОЧНИЙ КРОК визначаємо за СТАТУСОМ угоди, а не «перший без дати».
     Причина (угода 256, 02.08.2026): дат майже немає, і підсвічувалась
     «Стафіровка», хоча вантаж уже в морі. Статус — найнадійніше джерело. */
  const stNow = s(r,"Статус");
  let key = ST_STEP[stNow];
  /* В ЕКСПОРТІ «Завантажений на авто/потяг» — це плече ДО порту, і вузол
     називається інакше. Без цієї підміни підсвітка не знаходила крок узагалі
     і зникала (зауваження користувачки 02.08.2026). */
  if (key === "land" && !st.some(x => x.k === "land"))
    key = st.some(x => x.k === "carauto") ? "carauto" : "stuff";
  let cur = st.findIndex(x => x.k === key);
  if (cur < 0){
    // крок для цього статусу відсутній — відкочуємось до найближчого попереднього
    for (let j = ST_ORDER.indexOf(stNow); j >= 0 && cur < 0; j--)
      cur = st.findIndex(x => x.k === ST_STEP[ST_ORDER[j]]);
  }
  if (cur < 0){                               // статусу немає в мапі — за датами
    cur = st.findIndex(x => !(x.f && past(x.d2 || x.d)));
    if (cur < 0) cur = st.length - 1;
  }
  /* «Букінг» і «Виконується» означають, що перевезення ще НЕ почалось: нічого
     не стафіровано, машина не подавалась. Тому крапка має стояти на ПЕРШОМУ
     вузлі ланцюжка — яким би він не був.
     Було: обидва статуси вели на «Стафіровку», а в ЕКСПОРТІ вона друга (перший
     вузол — «Автоперевезення та оформлення»), і для експортних букінгів крапка
     стояла на другій позиції, хоча ще нічого не відбулось. В імпорті стафіровка
     перша, тому там усе виглядало правильно — і різниця між рядками збивала з
     пантелику (зауваження користувачки 14.08.2026).
     Нижче лишається правило «не раніше за фактично пройдений етап»: якщо дата
     вже настала, крапка все одно посунеться вперед. */
  if (stNow === "Букінг" || stNow === "Виконується") cur = 0;

  /* Підсвітка НЕ може стояти раніше за етап, який уже фактично відбувся.
     Угода 259: стафіровка була 31.07, а статус «Завантажений на авто» тягнув
     підсвітку на перший вузол — виходило, що вантаж ще не стафірований
     (зауваження користувачки 02.08.2026). */
  /* ...але тільки за датами, які МОЖУТЬ бути правдою. Дві заборони:

     1) Подія ПІСЛЯ виходу судна не може мати дату РАНІШУ за сам вихід. Угода 238
        (ОТІС ТАРДА, 15.08.2026): «Вивантаження у отримувача (факт)» = 16.06, а
        відправлення = 22.06. Схема показувала клієнтові повністю пройдений
        маршрут, хоча пігулка поруч казала «В порту перевалки». Перевірено на
        реальних даних: крапка стояла на 8-му вузлі з 9, без цієї дати — на 4-му.
        Таких угод у базі 13, у чинних кабінетах — 231 і 233 (Мірандор),
        197 і 238 (ОТІС ТАРДА).
        Порівнюємо ЛИШЕ вузли після морського/авіа плеча: стафіровка, здача в
        порт і гейт ін законно відбуваються ДО виходу, і відкидати їх не можна.

     2) Вузол «Вантаж доставлено» рахується пройденим ТІЛЬКИ за статусом. Дата
        доставки в базі буває проставлена наперед або помилково, і тоді маршрут
        «завершувався» у вантажу, який ще їде. */
  const dep = s(r,"ETD (факт)") || s(r,"ETD (план)");
  const iMove = st.findIndex(x => x.k === "move");
  let lastDone = -1;
  st.forEach((x, i) => {
    const d = x.d2 || x.d;
    if (!x.d || !past(d)) return;
    if (dep && iMove >= 0 && i > iMove && d < dep) return;
    if (x.k === "done" && !delivered) return;
    lastDone = i;
  });
  if (lastDone > cur) cur = lastDone;
  if (delivered) cur = st.length - 1;

  const state = st.map((x, i) =>
    delivered ? "done" : (i < cur ? "done" : (i === cur ? "now" : "todo")));
  return { st, cur, delivered, P, state };
}

function routeHtml(r){
  const { st, cur, delivered, P, state } = stepState(r);
  const cells = [];
  st.forEach((x, i) => {
    if (x.i === "border"){
      // лінія доходить ДО кордону, а не обривається перед ним (02.08.2026)
      if (i) cells.push(`<div class="cn ${i <= cur || delivered ? "on" : ""}"></div>`);
      cells.push(`<div class="brd"><div class="bln"></div>
        <div class="blb">КОРДОН</div>
        ${x.d ? `<div class="bld">${fmt(x.d)}</div>` : ""}</div>`);
      return;
    }
    if (i) cells.push(`<div class="cn ${i <= cur || delivered ? "on" : ""}"></div>`);
    cells.push(`<div class="nd ${state[i]}">
      <div class="dot ${x.i === "ship" || x.i === "plane" ? "big" : ""}">${svg(x.i)}</div>
      <div class="ndtxt">
      <div class="ttl">${x.t}</div>
      ${x.p ? `<div class="place">${esc(x.p)}</div>` : ""}
      ${x.dur != null ? `<div class="dur">${x.dur} ${plural(x.dur,"день","дні","днів")}</div>` : ""}
      ${x.d ? (x.f && past(x.d2 || x.d)
                 ? `<div class="dt">${fmtY(x.d)}${x.d2 ? " → " + fmtY(x.d2) : ""}</div>`
                 : `<div class="plan">план ${fmtDM(x.d)}${x.d2 ? " → " + fmtDM(x.d2) : ""}</div>`)
            : ""}
      </div>
    </div>`);
  });

  return `<div class="route" style="--mc:${P.c};--mbg:${P.bg}">
    <div class="chain">${cells.join("")}</div>
  </div>`;
}

/* ── мініатюра маршруту в рядку ────────────────────────────────────────────
   Щоб побачити, ДЕ зараз вантаж, не треба розкривати угоду: крапки — ті самі
   кроки, що й у великій схемі (беруться з stepState, не рахуються вдруге).
   Пройдені залиті кольором виду перевезення, поточна більша з ореолом,
   майбутні бліді. Кордон пропускаємо: він роздільник, а не крок.
   Підказка при наведенні — назви кроків по порядку, з позначкою поточного. */
function miniRoute(r){
  const { st, P, state } = stepState(r);
  const pts = st.map((x,i)=>({x, s:state[i]})).filter(p => p.x.i !== "border");
  if (pts.length < 2) return "";
  const title = pts.map(p => (p.s === "now" ? "▸ " : "") + p.x.t.replace(/<br>/g," ")).join(" · ");
  /* ШИРИНА ВІДРІЗКІВ НЕ ОДНАКОВА. Головне плече — море (для авіа це переліт,
     для авто дорога) — займає середину, а короткі кроки до і після нього
     тиснуться до країв.
     Навіщо: при рівних відрізках вантаж «у порту відправлення» опинявся
     візуально ПОСЕРЕДИНІ шляху, хоча він щойно почав рух (зауваження
     користувачки 14.08.2026: «посередині має бути море або повітря або дорога
     для авіа та авто»). Тепер крапка стоїть приблизно там, де вантаж і є
     насправді: чверть шляху — це порт відправлення, середина — сам рейс.
     Головний вузол — той самий крок "move", що й у великій схемі. */
  const wide = i => (pts[i].x.k === "move" || pts[i-1].x.k === "move") ? 3 : 1;
  return `<div class="mini" style="--mc:${P.c};--mbg:${P.bg}" title="${esc(title)}">${
    pts.map((p,i)=>`${i?`<i class="ml ${p.s==="todo"?"":"on"}" style="flex:${wide(i)}"></i>`:""}<b class="md ${p.s}"></b>`).join("")
  }</div>`;
}

/* ── картка ───────────────────────────────────────────── */
function panel(r){
  const conts = s(r,"Контейнер").split(",").map(x=>x.trim()).filter(Boolean);
  const kv = [
    ["Коносамент", s(r,"HBL") || s(r,"BL") || "—"],
    ["Контейнер",  conts.length ? conts.join("<br>") : "—"],
    ["Лінія",      s(r,"Лінія") || "—"],
    [modeOf(r) === "air" ? "Авіалінія / рейс" : "Судно / рейс",
     [carrier(r), s(r,"Вояж")].filter(Boolean).join(" / ") || "—"],
    ["Вантаж",     s(r,"Вантаж") || "—"],
    ["Кількість",  s(r,"Кількість") || "—"],
    ["Тип",        [s(r,"Вид перевезення"), s(r,"FCL/LCL")].filter(Boolean).join(", ") || "—"],
  ];
  if (s(r,"Порт перевалки")) kv.splice(4, 0, ["Перевалка", esc(s(r,"Порт перевалки"))]);
  const docs = (r._docs||[]);
  const P = pal(r), M = modeOf(r);
  const badge = {sea:"⚓", air:"✈", road:"🚚", rail:"🚆"}[M];
  const route = routeArrows(s(r,"Маршрут")).split("→").map(x=>x.trim()).filter(Boolean);
  const dest  = s(r,"Кінцева точка доставки") || (route.length > 1 ? route[1] : "");
  /* Рядок деталей через крапки — як у макеті користувачки:
     FCL · 1×40' · Лінія · Судно / рейс · Контейнер */
  const bits = [
    s(r,"FCL/LCL"), s(r,"Кількість"),
    s(r,"Лінія") ? "Лінія " + s(r,"Лінія") : "",
    carrier(r) ? (modeOf(r) === "air" ? "Авіалінія " : "Судно ")
                 + [carrier(r), s(r,"Вояж")].filter(Boolean).join(" / ") : "",
    s(r,"Контейнер") ? "Контейнер " + s(r,"Контейнер") : "",
  ].filter(Boolean);
  const bl = s(r,"HBL") || s(r,"BL") || s(r,"Авіанакладна");
  return `<div class="panel" style="--mc:${P.c};--mbg:${P.bg}">
    <div class="phead">
      <div class="pttl">
        <!-- У бейджі — ВИД ПЕРЕВЕЗЕННЯ (МОРЕ / АВТО / АВІА / ЗАЛІЗНИЦЯ),
             а не статус: вимога користувачки 02.08.2026. Де саме зараз вантаж,
             видно на самій схемі — там підсвічений поточний крок. -->
        <span class="badge">${badge} ${esc(P.nm.toUpperCase())}</span>
        <b>Угода №${esc(s(r,"Угода"))}</b>
      </div>
      <div class="pmeta">${bits.map(esc).join(" <i>·</i> ")}</div>
      ${bl ? `<div class="pmeta">${air(r)?"Накладна":"Коносамент"} <b>${esc(bl)}</b></div>` : ""}
      <div class="peta">
        <div class="lb">${done(r) ? "Доставлено" : "ETA"}</div>
        <div class="dt">${fmt(arrOf(r)) || "—"}</div>
        ${dest ? `<div class="pl">${esc(dest)}</div>` : ""}
      </div>
    </div>
    ${routeHtml(r)}
    <div class="tzn">Час вказано за місцевим часом</div>
    <div class="cols">
      <div class="card"><h4>Дані вантажу</h4>
        <div class="kv">${kv.map(([k,v])=>`<div class="k">${esc(k)}</div><div class="v">${v}</div>`).join("")}</div>
      </div>
      <div>
        <div class="card"><h4>Документи</h4>
          ${docs.length ? docs.map(d=>`<div class="doc">
              <span style="color:var(--accent-ink)">${svg("doc")}</span>
              <span class="nm"><b>${esc(d.kind)}</b><span>${esc(d.name)}</span></span>
              ${d.url ? `<a class="btn" href="${esc(d.url)}">Завантажити</a>`
                      : `<button class="btn">Завантажити</button>`}</div>`).join("")
            : `<div class="empty">Документів поки немає. Щойно вони з'являться, ви отримаєте сповіщення.</div>`}
          ${DEMO ? `<div class="up">Перетягніть сюди файл, щоб додати документ до вантажу</div>` : ``}
        </div>
        ${DEMO ? `<div class="card msg" style="margin-top:14px"><h4>Питання по вантажу</h4>
          <textarea placeholder="Напишіть менеджеру…"></textarea>
          <div class="row"><span class="dim" style="font-size:12px">Відповідь надійде на вашу пошту</span>
            <button class="btn prim">Надіслати</button></div>
        </div>` : ``}
      </div>
    </div>
  </div>`;
}

/* ── таблиця ──────────────────────────────────────────── */
let FILTER="act", Q="";
/* Плитки зверху — це відбори, а не просто числа: клік по «доставлено» показує
   таблицю доставлених, по «прибувають за 7 днів» — тільки їх, повторний клік
   по тій самій плитці скидає відбір (прохання користувачки 02.08.2026). */
const isSoon  = r => { const e=s(r,"ETA");
  return !done(r) && !!e && e >= TODAY && e <= addDays(TODAY,7); };
/* Відправляється найближчими днями — тільки З ПОРТУ ВІДПРАВЛЕННЯ.
   Три умови разом:
   1) дата відправлення попереду, але не далі ніж через тиждень;
   2) вантаж ще НЕ вийшов: етап не пізніший за «В порту відправлення».
      Без цієї умови в плитку потрапляла угода 252 зі статусом «В порту
      перевалки» — вона вже пливе, а дата в полі стосується відходу з
      перевалки, не з порту відправлення (зауваження користувачки 14.08.2026:
      «це тільки про угоди, які відправляються з порту відправлення, не з
      порту перевалки»);
   3) не доставлена.
   Невідомий статус дає ранг -1 і теж вважається «ще не вийшов» — це
   безпечніший бік: краще показати зайве, ніж сховати те, що ось-ось піде. */
const NOT_LEFT_YET = ST_ORDER.indexOf("В порту відправлення");
const isSoonOut = r => { const d = etdOf(r);
  return !done(r) && !!d && d >= TODAY && d <= addDays(TODAY,7)
         && ST_ORDER.indexOf(s(r,"Статус")) <= NOT_LEFT_YET; };
const hasDocs = r => (r._docs || []).length > 0;
/* ПОРЯДОК РЯДКІВ — ЗА ДАТОЮ ВІДПРАВЛЕННЯ. Рішення користувачки 14.08.2026.
   Історія, щоб ніхто не «полагодив» це назад:
   1) Спершу сортували за ETA — і угода, яка ще не вийшла з порту, ставала вище
      за ту, що вже пливе. Її слова: «як може бути контейнер з датою ЕТД 17.08
      вище за контейнер, який давно завантажений на судно».
   2) Тоді зробили за ЕТАПОМ перевезення — і це теж виявилось хибним:
      «порт перевалки може бути на самому початку», тобто етап НЕ показує,
      хто далі просунувся: на довгому маршруті перевалка буває на початку.
   3) Тепер: за датою ВІДПРАВЛЕННЯ, раніше вийшов — вище. Дати немає — рядок
      іде ВНИЗ («якщо дати немає, то внизу строки»), а не вгору і не в середину.
   Доставлені лишаються в самому кінці: у поданні «Усі» вони не мають
   перемішуватись із тим, що зараз їде.
   Порядок стійкий: за однакових дат — за ETA, потім за номером угоди, щоб
   рядки не стрибали при перемальовуванні. */
const etdOf = r => s(r,"ETD (факт)") || s(r,"ETD (план)");
function byDate(a, b){
  if (done(a) !== done(b)) return done(a) ? 1 : -1;
  const da = etdOf(a), db = etdOf(b);
  if (!da !== !db) return da ? -1 : 1;              // без дати — вниз
  if (da && db && da !== db) return da < db ? -1 : 1;
  const ea = s(a,"ETA"), eb = s(b,"ETA");
  if (!ea !== !eb) return ea ? -1 : 1;
  if (ea && eb && ea !== eb) return ea < eb ? -1 : 1;
  return (+s(a,"Угода") || 0) - (+s(b,"Угода") || 0);
}

function visible(){
  const q=Q.toLowerCase();
  return DEALS.filter(r=>{
    if (FILTER==="act"  && done(r)) return false;
    if (FILTER==="done" && !done(r)) return false;
    if (FILTER==="soon" && !isSoon(r)) return false;
    if (FILTER==="out"  && !isSoonOut(r)) return false;
    if (FILTER==="docs" && !hasDocs(r)) return false;
    if (!q) return true;
    return ["Угода","BL","HBL","Контейнер","Судно","Маршрут"].some(k=>s(r,k).toLowerCase().includes(q));
  }).sort(byDate);
}
function stCls(r){ const x=s(r,"Статус");
  if (x==="Вантаж доставлено") return "ok";
  if (x==="Букінг"||x==="Виконується") return "wait";
  return "sea"; }

function render(){
  const rows = visible();
  const act = DEALS.filter(r=>!done(r));
  const soon = DEALS.filter(isSoon);
  const out  = DEALS.filter(isSoonOut);
  const docs = DEALS.reduce((n,r)=>n+(r._docs||[]).length,0);
  const TICON =[["ship","ic-blue"],["truck","ic-orange"],["port","ic-amber"],
                ["box","ic-green"],["doc","ic-vio"]];
  const TFILT =["act","out","soon","done","docs"];
  document.getElementById("tiles").innerHTML = [
    [act.length,"вантажів у дорозі"],
    [out.length,"відправляються за 7 днів"],
    [soon.length,"прибувають за 7 днів"],
    [DEALS.length-act.length,"доставлено"],
    [docs,"документів доступно"],
  ].map(([n,l],i)=>`<button class="tile ${FILTER===TFILT[i]?"on":""}" data-f="${TFILT[i]}">
      <div class="ic ${TICON[i][1]}">${svg(TICON[i][0])}</div>
      <div><div class="n">${n}</div><div class="l">${l}</div></div>
    </button>`).join("");
  // перемикач під пошуком завжди показує той самий відбір, що й плитки
  document.querySelectorAll("#seg button").forEach(b=>b.classList.toggle("on", b.dataset.f===FILTER));

  document.getElementById("rows").innerHTML = rows.length ? rows.map(r=>{
    const conts = s(r,"Контейнер").split(",").map(x=>x.trim()).filter(Boolean);
    const bl = s(r,"HBL")||s(r,"BL");
    const etd = s(r,"ETD (факт)")||s(r,"ETD (план)");
    const nd = (r._docs||[]).length;
    return `<tr class="deal" data-id="${esc(s(r,"Угода"))}">
      <td class="mono num">${esc(s(r,"Угода"))}</td>
      <td><span class="chip ${s(r,"Напрямок")==="Експорт"?"exp":""}">${
          s(r,"Напрямок")==="Імпорт"?"ІМП":(s(r,"Напрямок")==="Експорт"?"ЕКС":"ТРН")}</span></td>
      <td data-l="Маршрут">${esc(routeArrows(s(r,"Маршрут"))||"—")}${miniRoute(r)}</td>
      <td class="mono" data-l="Коносамент / контейнер">${bl?`<b>${esc(bl)}</b>`:'<span class="dim">—</span>'}${
          conts.map(c=>`<br><span class="dim">${esc(c)}</span>`).join("")}</td>
      <td data-l="Судно / авіалінія">${esc(carrier(r)||"—")}</td>
      <td class="mono" data-l="Відправлення">${etd?`<span class="d">${fmt(etd)}</span>`:'<span class="dim">—</span>'}</td>
      <td class="mono" data-l="Прибуття">${arrOf(r)?`<span class="d">${fmt(arrOf(r))}</span>`:'<span class="dim">—</span>'}</td>
      <td data-l="Статус"><span class="pill ${stCls(r)}">${esc(s(r,"Статус")||"—")}</span></td>
      <td data-l="Реліз"><span class="ck${isOn(r,"Реліз")?" on":""}" title="${
          isOn(r,"Реліз")?"Реліз виданий":"Релізу ще немає"}"></span></td>
      <td data-l="Документи">${nd?`<span class="docn">${svg("doc")}${nd}</span>`:'<span class="dim">—</span>'}</td>
      <td class="cmt" data-l="Коментар">${s(r,"Коментар клієнту")
          ? esc(s(r,"Коментар клієнту")) : '<span class="dim">—</span>'}</td>
    </tr>`;
  }).join("") : `<tr><td colspan="11" class="empty" style="padding:20px 12px">Нічого не знайдено.</td></tr>`;

  document.querySelectorAll("tr.deal").forEach(tr=>tr.addEventListener("click",()=>toggle(tr)));
}
function addDays(iso,n){const d=new Date(iso);d.setDate(d.getDate()+n);return d.toISOString().slice(0,10);}
function toggle(tr){
  const open = tr.nextElementSibling && tr.nextElementSibling.classList.contains("exp");
  document.querySelectorAll("tr.exp").forEach(x=>x.remove());
  document.querySelectorAll("tr.deal.open").forEach(x=>x.classList.remove("open"));
  if (open) return;
  tr.classList.add("open");
  const r = DEALS.find(d=>String(d["Угода"])===tr.dataset.id);
  const e = document.createElement("tr");
  e.className="exp"; e.innerHTML=`<td colspan="10">${panel(r)}</td>`;
  tr.after(e);
}
document.getElementById("tiles").addEventListener("click",e=>{
  const t=e.target.closest(".tile"); if(!t) return;
  FILTER = (FILTER === t.dataset.f) ? "all" : t.dataset.f;
  render();
});
document.getElementById("q").addEventListener("input",e=>{Q=e.target.value;render();});
document.getElementById("seg").addEventListener("click",e=>{
  const b=e.target.closest("button"); if(!b) return;
  document.querySelectorAll("#seg button").forEach(x=>x.classList.remove("on"));
  b.classList.add("on"); FILTER=b.dataset.f; render();
});
render();
</script>
"""


def pick_client(rows, name):
    """Угоди ОДНОГО клієнта.

    Було до 02.08.2026: `name.lower() in клієнт.lower()` — збіг за ПІДРЯДКОМ.
    «Мірандор» підтягував і «Мірандор Плюс», а порожня назва — усі угоди фірми.
    Кабінет лежить на сервері без пароля, тому це прямий витік чужих даних.

    Тепер правило: точний збіг назви (без різниці у регістрі та зайвих пробілах).
    Якщо точного немає — дивимось, скільки клієнтів МІСТЯТЬ цю назву:
      рівно один — беремо його і кажемо, кого саме (звичний короткий запис працює);
      кілька     — ЗУПИНЯЄМОСЬ і показуємо список (неоднозначність = не вгадуємо);
      жодного    — ЗУПИНЯЄМОСЬ (одрук у назві не має мовчки давати порожній кабінет).
    """
    want = nz(name).lower()
    if not want:
        raise SystemExit("ПОМИЛКА: не вказано клієнта (--client). Порожня назва "
                         "означала б «усі угоди фірми» — так робити не можна.")
    names = {nz(r.get("Клієнт")) for r in rows if nz(r.get("Клієнт"))}
    exact = [n for n in names if n.lower() == want]
    if exact:
        chosen = exact[0]
    else:
        near = sorted(n for n in names if want in n.lower())
        if len(near) == 1:
            chosen = near[0]
            print("УВАГА: точного збігу «%s» немає, але однозначно підходить «%s» — беру його."
                  % (name, chosen))
        elif len(near) > 1:
            raise SystemExit("ПОМИЛКА: під «%s» підпадає кілька клієнтів: %s.\n"
                             "Вкажи назву точно — інакше в кабінет потраплять чужі угоди."
                             % (name, ", ".join(near)))
        else:
            raise SystemExit("ПОМИЛКА: клієнта «%s» немає в базі. Перевір назву — "
                             "файл кабінету НЕ чіпаю." % name)
    out = [r for r in rows
           if nz(r.get("Клієнт")) == chosen and nz(r.get("Статус")) != CANCELLED]
    if not out:
        raise SystemExit("ПОМИЛКА: у клієнта «%s» немає жодної активної угоди. "
                         "Порожній кабінет не записую, щоб не затерти робочий." % chosen)
    print("клієнт: %s — угод %d" % (chosen, len(out)))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--client", default="Мірандор")
    ap.add_argument("--out", default="/root/unitex-os-www/cabinet.html")
    a = ap.parse_args()

    all_rows = nc_all()
    rows = pick_client(all_rows, a.client)
    data = []
    for r in rows:
        d = {k: r.get(k) for k in CLIENT_COLS if k != "Файли"}
        d["_docs"] = files_of(r)
        data.append(d)
    # Базовий, передбачуваний порядок. Остаточний задає браузер (byDate:
    # за датою відправлення, без дати — вниз, доставлені в кінці).
    data.sort(key=lambda d: (nz(d.get("Статус")) == "Вантаж доставлено",
                             nz(d.get("ETA")) or "9999"))

    import datetime
    # Дані лежать УСЕРЕДИНІ <script>, тому послідовність «</» у будь-якому полі
    # закривала б тег і рвала сторінку. Перевірено 02.08.2026: «</script>» у полі
    # «Коментар клієнту» давало 0 угод замість 9 і сирий JSON на екрані клієнта.
    # Для JavaScript «<\/» і «</» — те саме, тому дані не змінюються, а сторінка ціла.
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    html = (TPL.replace("__LOGO__", logo())
               .replace("__TITLE__", "UNITEX — особистий кабінет (прототип)")
               .replace("__HEADEXTRA__", "")
               .replace("__BANNER__", "")
               .replace("__DEMO__", "true")
               # Прототип не знає, коли автоматика востаннє звіряла дані з
               # лініями (у нього немає доступу до журналу трекінгу), тому
               # позначку не малює взагалі. Вигадувати час не можна — її показує
               # лише справжній кабінет, і лише з журналу прогонів.
               .replace("__UPDATED__", "")
               .replace("__CLIENTFULL__", client_title(a.client))
               .replace("__CLIENT__", a.client)
               .replace("__TODAY__", datetime.date.today().isoformat())
               .replace("__DATA__", payload))
    # Пишемо спершу в тимчасовий файл поруч і лише потім підміняємо: якщо запис
    # обірветься, у клієнта лишиться попередній робочий кабінет, а не половина файла.
    tmp = a.out + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(html)
    os.replace(tmp, a.out)
    print("OK %s — %d угод, %d байт" % (a.out, len(data), len(html)))


if __name__ == "__main__":
    main()
