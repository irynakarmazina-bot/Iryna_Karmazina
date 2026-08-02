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
import re
import urllib.request

NC = "http://localhost:8080"
TABLE = "m58xsjo6at01ohl"
TOKEN_FILE = "/root/nocodb-token.txt"
FACADE = "/root/unitex-os-www/index.html"
CANCELLED = "Скасована"

# Єдині колонки, які взагалі виходять із бази для клієнта.
CLIENT_COLS = [
    "Угода", "Напрямок", "Вид перевезення", "Тип", "FCL/LCL", "Маршрут", "Лінія",
    "BL", "HBL", "Контейнер", "Судно", "Вояж", "Гейт ін", "ETD (план)", "ETD (факт)",
    "ETA", "ETA порт (план)", "ETA порт (факт)", "Вивантаження в порту (факт)",
    "Порт перевалки", "Перевалка (прибуття)", "Перевалка (відправлення)",
    "Гейт аут", "Подача авто (план)", "Подача авто (факт)", "Статус",
    "Вантаж", "Кількість", "Файли",
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
    try:
        html = open(FACADE, encoding="utf-8").read()
        m = re.search(r'const LOGO_SRC = "(data:image/png;base64,[^"]+)"', html)
        return m.group(1) if m else ""
    except Exception:  # noqa: BLE001
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
        if kind and kind not in CLIENT_DOCS:
            continue                      # внутрішній документ — клієнту не віддаємо
        out.append({"kind": kind or "Документ", "name": (m.group(2) if m else title) or title})
    return out


TPL = r"""<!doctype html>
<meta charset="utf-8">
<title>UNITEX — особистий кабінет (прототип)</title>
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
header{background:var(--surface);border-bottom:1px solid var(--line);
  padding:14px 30px;display:flex;align-items:center;gap:18px;position:sticky;top:0;z-index:5}
header img{height:56px}
.spacer{flex:1}
.who{text-align:right;line-height:1.25}
.who b{display:block;font-size:15px;font-weight:700}
.who span{font-size:12px;color:var(--muted)}
main{max-width:1560px;margin:0 auto;padding:24px 30px 70px}

.proto{background:var(--warn-bg);border:1px solid #f0dcb8;color:#7a5a1b;
  border-radius:var(--r);padding:11px 16px;font-size:13px;margin-bottom:20px}

/* плитки — з кольоровими іконками, як на дашборді ЕРП */
.tiles{display:grid;grid-template-columns:repeat(4,1fr);gap:16px;margin-bottom:22px}
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
.ic-blue{background:var(--accent-soft);color:var(--accent)}
.ic-green{background:var(--pos-bg);color:var(--pos)}
.ic-amber{background:var(--warn-bg);color:var(--warn)}
.ic-vio{background:var(--vio-bg);color:var(--vio)}
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
th{text-align:left;font-size:11.5px;letter-spacing:.02em;
  color:var(--ink);font-weight:700;padding:11px 16px;border-bottom:1.5px solid var(--line)}
td{padding:12px 16px;border-bottom:1px solid var(--line-soft);vertical-align:middle;
  font-size:14px;color:var(--ink)}
tbody tr.deal:nth-child(odd) td{background:#fbfbf9}
tr.deal{cursor:pointer;transition:background .12s}
tr.deal:hover td{background:var(--surface-2)}
tr.deal.open td{background:var(--accent-soft)}
tbody tr:last-child td{border-bottom:0}
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
.btn.prim{background:var(--accent);border-color:var(--accent);color:#fff}
.btn.prim:hover{filter:brightness(1.06)}
.empty{color:var(--muted);font-size:13.5px;padding:8px 0}
.msg textarea{width:100%;min-height:82px;border:1px solid var(--line);border-radius:11px;
  padding:11px 13px;font:inherit;font-size:14px;resize:vertical;background:var(--surface);color:var(--ink)}
.msg textarea:focus{outline:none;border-color:var(--accent);box-shadow:0 0 0 3px var(--accent-soft)}
.msg .row{display:flex;justify-content:space-between;align-items:center;margin-top:12px;gap:10px}
.up{border:1.5px dashed var(--line);border-radius:12px;padding:16px;text-align:center;
  color:var(--muted);font-size:13px;margin-top:14px}
.foot{margin-top:28px;color:var(--muted);font-size:12.5px;text-align:center}
</style>

<header>
  <img src="__LOGO__" alt="UNITEX">
  <div class="spacer"></div>
  <div class="who"><b>__CLIENTFULL__</b><span>Особистий кабінет</span></div>
</header>

<main>
  <div class="proto"><b>Прототип.</b> Сторінка зібрана з реальних даних клієнта «__CLIENT__»
    для узгодження вигляду. Входу і збереження тут ще немає — кнопки нічого не роблять.</div>

  <div class="tiles" id="tiles"></div>

  <div class="bar">
    <input id="q" placeholder="Пошук: номер угоди, коносамент, контейнер, судно, маршрут…">
    <div class="seg" id="seg">
      <button data-f="act" class="on">В дорозі</button>
      <button data-f="done">Доставлені</button>
      <button data-f="all">Усі</button>
    </div>
  </div>

  <div class="tw">
    <table>
      <thead><tr>
        <th>Угода</th><th></th><th>Маршрут</th><th>Коносамент / контейнер</th>
        <th>Судно</th><th>Відправлення</th><th>Прибуття</th><th>Статус</th><th>Документи</th>
        <th class="cmt">Коментар</th>
      </tr></thead>
      <tbody id="rows"></tbody>
    </table>
  </div>

  <div class="foot">Дані оновлюються автоматично з систем ліній. Питання — через форму в картці вантажу.</div>
</main>

<script>
const DEALS = __DATA__;
const TODAY = "__TODAY__";

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
const ICON_MASK = {
  warehouse: "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAADAAAAAxCAYAAACcXioiAAAGbElEQVR42tWaWY8UVRTHf1Vd3T09iwMybLKLihAlIi64J2p88EGjJD76yfwCfgI1GrcHFY2CoIkOIsM2CMLABJienumq8sF/6ZnDrd7oMVLJTU/dunXP9j/LPTURq3PVgR3ABFAFrgIXgZvDJlRZJQH2AIc1ngHWA1eAP7gLrnuAd4ELQK7xNfD2ahCLV2nPUWCjmVsvOI3eDQJcBy4DZ8zcNWBB438vwJQc9wxwQ0zPA0vA5P/ZiUeB/cCbwKvAvcBJWaSlNQkQ6X5pGESjITG/F3gEeE4WuA78KEceBzbJudcAl4BjwIlhRKU7FWA/sAs4AGwBMmAa+AE4KkEAtgKPAru1rgn8KQudAk7/1wLsUaJ6WL/jYvw48JOSVujaAjwgoXfINy7LUqeA86stwHbgoDS/SRn2N0HinO57ve6X5bYB68T8aeB37TlUAXYKAi/JOS8K4z+L8PyAlmzIIvuA+5Q7FoBZWfKoCQB9C7BGmz+mzSeAOeCsNj85xLg+KRr7pKApRbVLCscngJluAjwoJicUMSbF/AGgJo1/LMYvASMmFMZy4OVAjok0cqCt0XBzFWBM9xuBF2TtjYLlMVnjnEmU160Ah4C3gCckwJgccwK4Ja3/qt8lMVc3TBb5JDcCZAFBijU1vbMMpBojZq8xKfBxWSQWw3Pyj081phOZag/wimJ5PWDeCTnbohiLlG3bYijqkOUz89vQ+obmmmI+N/sVezfk3JaPHYLZlFAwm4jQlEa9hJFJVwa0RGhBhIoM25Z2i+ummCksUCvxgUU9r0vQuMtZY50skyciMiOMr3cV46xi9C2ZtqINGnK6iuqdIpbHMv92PR/V3DXRmNc7hUXX6nlL71+QEkY0EvnBViPUIvCtHPtWosnvgQ0ahwzz7wNHRDiWIFuBp4HXxOQV4AvgS/29QSXFO9JSW+b+APhGzO4GXta6zcL3EeBDKbSA1FrgSeB1JT/k0J9ICAoBZoDvgBflyIm0dlyRZ87VPfuVVccl2HkxN2MSU65nbVmpINzU+zuBZw28ZoGvFHWaJnM3JGhxFVn7tnK6paiQmbnEMY+cbrOYL5LRhNnrirRYKKemPRcMY3N6XvhEVZDJzRpk+dT40W18xy7sZUaAil4OleCJE9KG0Kbbp3gnDuQgG1qLnGCvPBCeI3sMiAMvZF2yZs1Fk1TvpG4fTzQO3CdGCXGAdhRIuCv2HuRElpQchHwSyztYIBEsEgOhkJWKddUSy614wWs/KhEwKoFH3kfNlQYESAYp7+MBjpl5F2aLfSO3ZxSwYuTWV3rkOS4TIDLMxSX+EMJ8yNGSDvexg0zsoeGUlZchIB7gjJAbQVDkyFyqrzptJgGLxAFavUAoKoNQ5LTQq4PnrqBrmYKsDFJJIBiEoJmWzAchFPfRZolKoFPGcDffynrwKwKlelcnzgcIs40+ek6ZoZP2uH/bHpwGyQNRwHKhuUEaaH0rzBO1psw6dPNsFo1cRIkCEcWXCXEJhNqB+babL83EWUl4pKSGKQuBUYkP+EydOmWFaC+YsE0IbnFAC7aAikosUAk4f8VFmEHg2e7mtE7wrkQqHSyAK8TikqwbgmMeUFYZ/tPAs2yY7fVKIOv6esmHybaDRt5BiHZAAfEwBQiVyh7zeQDHVpNpB/jEgUq2YzVq2yDDar+nrunlMd82/aGQhX0ZUisrJeIulWqotvd1TSUAmcWSUJg6AfquoDtVo1GHMiFxmbfu8kAspn0/x++Ru25dUgJRX8lWQwIsuYNJpWTDJis/Dy2pgEtduV1zULkR8IGoh0zs5+xBaAWDIyJaNQvLQlvLRZhE3ezizDwH/KJvCJnuW06gZg9hezRQJ604+FgBNrnzZ1Vze+WABba3OO3W1D17SHAa0+80/34DuywBD6qvs11NL3ukbKhXVDFjjNu/bNYsHAsTPsXfX9ffUGOq0PIpEW9qs2U1rba5xus10z2ua+2ImGyqv3NDzat58+1hl7HItL7OtAxvdXX/DhhaV4H3NP75knMY+MwllNUay12eFyG3bbrffnwEPG8h1O+B4k6upMdDe6cudbPwg2Kzs+pdjru+f2ZifO6+B9hIUjVhMTVrKiYyLZnyuPhA0hTU/McOG4Hs0bMqSH+O/pUhMjF6g3qePjGlhnBZUVUx8T8LdBF8DVTE8uVAvsmM4lLj0IVCW+p2zwP8BZLBAxsJpTMpAAAAAElFTkSuQmCC",
  customs: "data:image/png;base64,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",
  crane: "data:image/png;base64,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",
  ship: "data:image/png;base64,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",
  officer: "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAADAAAAA1CAYAAAAHz2g0AAAHoElEQVR42s2aaW9cZxmGr1ns8diOPXZiO0sTt3FaxyYklLRAy5JKAVpRhMIqioT40h/Ab+BngJD4BKoApar40JRS1gRKmzZts6dxkmbBqRPbSeo4Y49n+JDrJa9Ox7Vni3ilo/GZc+Y9z/0s97Mcp2jd2gIUgDZgAZgCJpv9kFQT91oPDAG7gAFgE9AngIrCnwOuAu8D7/w/AFgPPAA8AmwHxhV8A7AOyAFpLTDncR44DpwGjvl5/n4DGFLo3cCXgK26THe05wJwB1j0PA90AmW/mxPIW1rj34JpOYCHgaeBrwKfBTYCGa+VgWvABPAucFkQPcA2YESL9Wmd28BH3n8Y+CPwF+DGaoXJ1ij8ZuAHwA+BHdH3S8BZfftt4CTwnv7e5rFJEOMqYYtgeoBPa8XNKuNlwTUdwKPAs5HwHwKndINTHh8IJLkmgL/remu13DDwGeALAnwGuOIeb7YCwJDaC+sY8ALwD/9ezYr9vBd4CugXTDswqqutCkC6RgBFoBSdl6THa3WSQV7K7VJ4onha1crU+MAB/XU4wSxr/bskyKVP2KMTGAQ+Lxk8LZt1ev1fwKvAxVa40DHglYhGNwLf14dPG8CngVngJjAv0+WBNX4W/P1j7rEt8oSTwCEJoWU0uhP4EfBjAcTuNGtSCvS4qDWy5ohOKbRPK8TrHPAS8CvgSKtoFOAM8E/gyQjAdbWYAsYEU47iJauP5wWV9VoJ6DBXHAcO1JqV6wGQ0R2Cz96RNq8qXHe0d8ocED7j5/UYUx2Cy/r7YqsBrJG7N3neATzk5w0ZKQjRHj0nI4hez/sjJaStn0ZMgPOtBLBO/13j+ZyCjij4lAIUrUJTCp/zaBdsTJ2h/B7SMldbCaBXEHkD9ayZuN8kN6iACCCjhoNL3QGm1XRZ6w3KTsPu31IXalP4isH7V+C3fv8pj40CCuxT1L8XgQsSwUm1/W3gG1avg1EMtQxAj+5TkTYvAUd1m9dloW7v6/S+DkFMC/qirrbNPmKPLtVdK7XXAyAbHRUFm42uH07cn4toM8kwC1GMBJfjftBoNvr9Sg8trkCNHYIoJRqgVa009a1KlMmDu9Sz0okObn6FOqopAK7aaWGgFjzqWQUJISOAC7VQaL0ApqTOBQFsNQnlGqDkomX5ZCKeWgLghsXWfxR6RCapx43GnGyUou5uutUALgMnLL5KWmC3pXFXjcOBXXL/tPtN1MMo9axF0/4GG/E1utWVKNuuNLV7HtjrHh8A+80jxfsBYEntbzDz5tR+GZhZgTo3K/g+y4g5+9/9BvF9sUDw2bwu9KDVaZfgPlKwJIhRRzLfBD4n4Ang98DfEv12SwEEENetKMftsh6QWRYtq28IqAB8GfiOmh8V/CzwIvCbWtmnkUwcr0vA79znOWub0KBvt9FJaZ0xrTWg5ictAvc3MrVu1nR6l5rd59ArC9wyqLNSbJ9/Twn8NYU/2MiDM00CELLzjELmHbUMmOy6BHTBycVLwK9pwoi9GQBCp3VTIGeiZJQ2mC8673nFxv01E2HBWipbK302w4XyJq8xBT3kRCFnQ7PDWWpOAEe1QBhY7QaesJQ4YYNzZrVD3XqDuFfuHo6akREZZ0YARWc85xQspfvEgdqv8N81sC9bRrxhMjujRZsGYEOk7UcdLz6s9kKBd0gB4jnp+8vs1y74x3ShLQLaq4u9bp8dV751AeiXYb7u+HC7Qmer9MldUTO/mn4iJLzuRJZ+3nnpO4L5k8muWAuAfu6+OtoLfFE36fC4rUuEmWebjch0FbP3CGw+kahuWTtdsxqtVm4MaPWnuDu+/3M11qoGYKsa3+ccdMjvLxqEZ3WZbuArWuWSRwygG/iaZUZ4Bxau3/b+W9Fo8oRK6IsKxW0mwS2CesF9lgXwoLXK9/R1FPqo/n3cpn3BYJ6XJl/1nngNc/cd2qj3n0oAPKKfdxorL0oCeQXfqXICm61X3nlnSh8DUAAeTwj/hnOfAwoYM8mMFHlE1jhXZQTZbtmQjyZ5YU0Af/Bz0hwRCOCgAj+uG+9RIc9FHvCx8mMP8AsDrGKJ+1PjoZ7k9hPg55YLvwS+tUzbuVIruhP4mS5c0VLPVLPAmD4dguyAWpmuA8CoTPKkLnJTzR2uQosrZeB3jYmdBvYOK9uX45ayV25/RHp7k7tvFI/XmaXX2ugM+9Dwfjhf535vKc+HURO1KQYQ3uGitg7W059Ga87ArTaFq2dd1xIXtGh4Pfs/AGMRH9+S4i43WCR2VAnqSgN7TloAzuox40AhABiIzHvFKJ9rsEJNJbq3pQZcKOwx474FXbIrq0nWRZvntMizaiyvpcrcm/FnlqloK7rKmEqJyWLY4BuKAjedGO1kou8z7l2RjjdGE5Cy5z1ZS4EC996WPKTwT4g677VM9Jn9hJJ8xv0Gq9AhjlxKVWajRMoJL0TCv+pkdJvwSrZiiVIIGu2JLFBQ+Gav9cvUPY3EWCZrUIRSYTgxHQ7azkSmLquBchX3SU78Uu63pCbLidFJhXuvZJPWzCbG+O2Rhaak1pupyG3GjYV0JHwq8sd0ZL5KwndLEbhYkEo0BFv0ernKkKxcZdSZ5t6/6uSi57dZhp8H3v4vstb23a/BEacAAAAASUVORK5CYII=",
  truck: "data:image/png;base64,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",
  box: "data:image/png;base64,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",
  plane: "data:image/png;base64,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",
};
const svg = (k, px) => ICON_MASK[k]
  ? `<i class="msk" style="--m:url('${ICON_MASK[k]}');width:${px||21}px;height:${px||21}px"></i>`
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
const modeOf = r => air(r) ? "air"
  : (/^авто$/i.test(s(r,"Вид перевезення")) ? "road" : (rail(r) ? "rail" : "sea"));
const pal = r => MODE_PAL[modeOf(r)];
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
      { k:"cust2", t:"Імпортне митне<br>оформлення", i:"officer", d:"", f:true, p:"" },
      { k:"done", t:"Вантаж доставлено",   i:"box",
        d:s(r,"Вивантаження у отримувача (факт)") || s(r,"Планова до клієнта (факт)") || eta,
        f:!!s(r,"Вивантаження у отримувача (факт)"), p:fin || to },
    ] : []));
  }

  /* ІМПОРТ */
  const car  = s(r,"Подача авто (факт)") || s(r,"Подача авто (план)") || s(r,"Гейт аут");
  const carF = !!(s(r,"Подача авто (факт)") || s(r,"Гейт аут"));
  /* Вид наземного плеча беремо зі СТАТУСУ, якщо він прямо його називає, і лише
     інакше — з «Вид перевезення». Причина (угода 239, 02.08.2026): трекінг
     поставив «Завантажений на потяг», а в полі виду стояло «фрахт+ТЕО+авто»,
     і схема малювала авто. Статус тут свіжіший за довідкове поле. */
  const byTrain = byTrainX;
  const land = [];
  land.push({ k:"land", t: byTrain ? "Завантажений на потяг" : "Завантажений на авто",
              i: byTrain ? "train" : "truck", d: car, f: carF, p:"" });
  if (R || s(r,"ETA сухий порт"))
    land.push({ k:"dry", t:"Сухий порт", i:"crane", d:s(r,"ETA сухий порт"),
                f:false, p:s(r,"Сухий порт") });
  return [
    { k:"stuff", t:"Стафіровка",         i:"warehouse", d:s(r,"Stuffing"), f:true, p:from },
    { k:"cust1", t:"Митне оформлення<br>на експорт", i:"customs", d:"", f:true, p:"" },
    { k:"pol", t:A?"Аеропорт відправлення":"Порт відправлення", i:"crane",
      d:s(r,"Здача в порт (факт)") || s(r,"Гейт ін"), f:true, p:from },
    { k:"move", t:moveT, i:moveI, d:etd, f:etdF, p:s(r,"Судно"), dur:days(etd, eta) },
  ].concat(transship(), [
    { k:"pod", t:A?"Аеропорт прибуття":"Порт прибуття", i:A?"plane":"crane", d:eta, f:etaF, p:to },
  ], land, [
    { k:"border", t:"Кордон",             i:"border",  d:s(r,"На кордоні") || s(r,"Перетин кордону (факт)"), f:true, p:"" },
    { k:"cust2", t:"Імпортне митне<br>оформлення", i:"officer", d:"", f:true, p:"" },
    { k:"done", t:"Вантаж доставлено",  i:"box",
      d:s(r,"Вивантаження у отримувача (факт)") || s(r,"Планова до клієнта (факт)"),
      f:true, p:fin },
  ]);
}

function routeHtml(r){
  const st = steps(r), P = pal(r), delivered = done(r);
  /* ПОТОЧНИЙ КРОК визначаємо за СТАТУСОМ угоди, а не «перший без дати».
     Причина (угода 256, 02.08.2026): дат майже немає, і підсвічувалась
     «Стафіровка», хоча вантаж уже в морі. Статус — найнадійніше джерело. */
  const ST_STEP = {
    "Букінг":"stuff", "Виконується":"stuff", "Стафіровка":"stuff",
    "В порту відправлення":"pol", "Завантажений на судно":"move", "В морі":"move",
    "Вивантажений в порту прибуття":"pod",
    "Завантажений на авто":"land", "Завантажений на потяг":"land",
    "Вивантажений в сухому порту":"dry", "На кордоні":"border",
    "Вантаж доставлено":"done",
  };
  /* Порядок статусів — щоб знайти найближчий крок, якщо точного в ланцюжку немає. */
  const ST_ORDER = ["Букінг","Виконується","Стафіровка","В порту відправлення",
    "Завантажений на судно","В морі","Вивантажений в порту прибуття",
    "Завантажений на авто","Завантажений на потяг","Вивантажений в сухому порту",
    "На кордоні","Вантаж доставлено"];
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
  /* Підсвітка НЕ може стояти раніше за етап, який уже фактично відбувся.
     Угода 259: стафіровка була 31.07, а статус «Завантажений на авто» тягнув
     підсвітку на перший вузол — виходило, що вантаж ще не стафірований
     (зауваження користувачки 02.08.2026). */
  let lastDone = -1;
  st.forEach((x, i) => { if (x.d && past(x.d2 || x.d)) lastDone = i; });
  if (lastDone > cur) cur = lastDone;
  if (delivered) cur = st.length - 1;

  const state = st.map((x, i) =>
    delivered ? "done" : (i < cur ? "done" : (i === cur ? "now" : "todo")));

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
      <div class="ttl">${x.t}</div>
      ${x.p ? `<div class="place">${esc(x.p)}</div>` : ""}
      ${x.dur != null ? `<div class="dur">${x.dur} ${plural(x.dur,"день","дні","днів")}</div>` : ""}
      ${x.d ? (x.f && past(x.d2 || x.d)
                 ? `<div class="dt">${fmtY(x.d)}${x.d2 ? " → " + fmtY(x.d2) : ""}</div>`
                 : `<div class="plan">план ${fmtDM(x.d)}${x.d2 ? " → " + fmtDM(x.d2) : ""}</div>`)
            : ""}
    </div>`);
  });

  return `<div class="route" style="--mc:${P.c};--mbg:${P.bg}">
    <div class="chain">${cells.join("")}</div>
  </div>`;
}

/* ── картка ───────────────────────────────────────────── */
function panel(r){
  const conts = s(r,"Контейнер").split(",").map(x=>x.trim()).filter(Boolean);
  const kv = [
    ["Коносамент", s(r,"HBL") || s(r,"BL") || "—"],
    ["Контейнер",  conts.length ? conts.join("<br>") : "—"],
    ["Лінія",      s(r,"Лінія") || "—"],
    ["Судно / рейс", [s(r,"Судно"), s(r,"Вояж")].filter(Boolean).join(" / ") || "—"],
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
    s(r,"Судно") ? "Судно " + [s(r,"Судно"), s(r,"Вояж")].filter(Boolean).join(" / ") : "",
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
        <div class="lb">ETA</div>
        <div class="dt">${fmt(s(r,"ETA")) || "—"}</div>
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
              <button class="btn">Завантажити</button></div>`).join("")
            : `<div class="empty">Документів поки немає. Щойно вони з'являться, ви отримаєте сповіщення.</div>`}
          <div class="up">Перетягніть сюди файл, щоб додати документ до вантажу</div>
        </div>
        <div class="card msg" style="margin-top:14px"><h4>Питання по вантажу</h4>
          <textarea placeholder="Напишіть менеджеру…"></textarea>
          <div class="row"><span class="dim" style="font-size:12px">Відповідь надійде на вашу пошту</span>
            <button class="btn prim">Надіслати</button></div>
        </div>
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
const hasDocs = r => (r._docs || []).length > 0;
function visible(){
  const q=Q.toLowerCase();
  return DEALS.filter(r=>{
    if (FILTER==="act"  && done(r)) return false;
    if (FILTER==="done" && !done(r)) return false;
    if (FILTER==="soon" && !isSoon(r)) return false;
    if (FILTER==="docs" && !hasDocs(r)) return false;
    if (!q) return true;
    return ["Угода","BL","HBL","Контейнер","Судно","Маршрут"].some(k=>s(r,k).toLowerCase().includes(q));
  });
}
function stCls(r){ const x=s(r,"Статус");
  if (x==="Вантаж доставлено") return "ok";
  if (x==="Букінг"||x==="Виконується") return "wait";
  return "sea"; }

function render(){
  const rows = visible();
  const act = DEALS.filter(r=>!done(r));
  const soon = DEALS.filter(isSoon);
  const docs = DEALS.reduce((n,r)=>n+(r._docs||[]).length,0);
  const TICON =[["ship","ic-blue"],["port","ic-amber"],["box","ic-green"],["doc","ic-vio"]];
  const TFILT =["act","soon","done","docs"];
  document.getElementById("tiles").innerHTML = [
    [act.length,"вантажів у дорозі"],
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
      <td>${esc(routeArrows(s(r,"Маршрут"))||"—")}</td>
      <td class="mono">${bl?`<b>${esc(bl)}</b>`:'<span class="dim">—</span>'}${
          conts.map(c=>`<br><span class="dim">${esc(c)}</span>`).join("")}</td>
      <td>${esc(s(r,"Судно")||"—")}</td>
      <td class="mono">${etd?`<span class="d">${fmt(etd)}</span>`:'<span class="dim">—</span>'}</td>
      <td class="mono">${s(r,"ETA")?`<span class="d">${fmt(s(r,"ETA"))}</span>`:'<span class="dim">—</span>'}</td>
      <td><span class="pill ${stCls(r)}">${esc(s(r,"Статус")||"—")}</span></td>
      <td>${nd?`<span class="docn">${svg("doc")}${nd}</span>`:'<span class="dim">—</span>'}</td>
      <td class="cmt">${s(r,"Коментар клієнту")
          ? esc(s(r,"Коментар клієнту")) : '<span class="dim">—</span>'}</td>
    </tr>`;
  }).join("") : `<tr><td colspan="10" class="empty" style="padding:20px 12px">Нічого не знайдено.</td></tr>`;

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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--client", default="Мірандор")
    ap.add_argument("--out", default="/root/unitex-os-www/cabinet.html")
    a = ap.parse_args()

    rows = [r for r in nc_all()
            if a.client.lower() in nz(r.get("Клієнт")).lower()
            and nz(r.get("Статус")) != CANCELLED]
    data = []
    for r in rows:
        d = {k: r.get(k) for k in CLIENT_COLS if k != "Файли"}
        d["_docs"] = files_of(r)
        data.append(d)
    # найближчі прибуття зверху, доставлені — в кінець
    data.sort(key=lambda d: (nz(d.get("Статус")) == "Вантаж доставлено",
                             nz(d.get("ETA")) or "9999"))

    import datetime
    html = (TPL.replace("__LOGO__", logo())
               .replace("__CLIENTFULL__", client_title(a.client))
               .replace("__CLIENT__", a.client)
               .replace("__TODAY__", datetime.date.today().isoformat())
               .replace("__DATA__", json.dumps(data, ensure_ascii=False)))
    open(a.out, "w", encoding="utf-8").write(html)
    print("OK %s — %d угод, %d байт" % (a.out, len(data), len(html)))


if __name__ == "__main__":
    main()
