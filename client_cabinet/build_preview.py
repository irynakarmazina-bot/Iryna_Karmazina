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
  padding:16px 18px;box-shadow:var(--shadow);display:flex;align-items:center;gap:14px}
.ic{width:42px;height:42px;border-radius:11px;display:flex;align-items:center;
  justify-content:center;flex:none}
.ic svg{width:21px;height:21px;fill:none;stroke:currentColor;stroke-width:1.8;
  stroke-linecap:round;stroke-linejoin:round}
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

.route{background:var(--surface);border:1px solid var(--line);border-radius:var(--r);
  padding:28px 22px 20px;overflow-x:auto;box-shadow:var(--shadow)}
/* ── схема руху: вигляд один в один з макета користувачки ──────────────────
   Кружок СВІТЛИЙ (заливка — блідий відтінок кольору виду перевезення), малюнок
   у колірі виду. Поточний етап НЕ заливається темним — він просто більший, а
   виділяється кольоровою назвою і тривалістю. Лінії між вузлами суцільні
   кольорові там, де етап пройдено, і бліді попереду. КОРДОН — вертикальна
   пунктирна риска з підписом, а не вузол. */
.chain{display:flex;align-items:flex-start;min-width:1020px}
.nd{flex:0 0 124px;text-align:center}
.cn{flex:1 1 auto;height:3px;background:var(--mc);opacity:.28;margin-top:36px;
  border-radius:2px;min-width:16px}
.cn.on{opacity:1}
.nd .dot{width:72px;height:72px;margin:0 auto;border-radius:50%;
  background:var(--mbg);color:var(--mc);display:flex;align-items:center;justify-content:center}
.nd .dot svg{width:34px;height:34px;stroke-width:1.9}
.nd.now .dot{width:80px;height:80px;margin-top:-4px;
  background:color-mix(in srgb,var(--mc) 17%,#fff);
  box-shadow:0 0 0 4px color-mix(in srgb,var(--mc) 12%,transparent)}
.nd.now .dot svg{width:38px;height:38px;stroke-width:2.1}
/* Майбутні етапи лишаються в кольорі виду перевезення, лише блідіші —
   сірий робив схему «мертвою». Прозорість не використовуємо: від неї текст
   і малюнок сіріли (зауваження про тьмяність, 02.08.2026). */
.nd.todo .dot{background:color-mix(in srgb,var(--mc) 8%,#fff);
  color:color-mix(in srgb,var(--mc) 62%,#8f8f8a)}
.nd.done .dot{background:color-mix(in srgb,var(--mc) 13%,#fff)}
.nd .ttl{font-size:13px;font-weight:700;margin-top:12px;line-height:1.3;color:var(--ink)}
.nd.now .ttl{color:var(--mc);font-size:14px}
.nd.todo .ttl{color:var(--ink-2)}
.nd .place{font-size:12px;color:var(--ink-2);margin-top:4px;line-height:1.35}
.nd .ttl{color:var(--ink)}
.nd .dur{font-size:14px;font-weight:700;color:var(--mc);margin-top:6px}
.nd .dt{font-size:13px;font-weight:700;margin-top:6px;font-variant-numeric:tabular-nums}
.nd .dt.dim{color:var(--muted);font-weight:600}
.nd .plan{font-size:12px;color:var(--muted);margin-top:4px;font-variant-numeric:tabular-nums}
.nd .dt{color:var(--ink)}
.brd{flex:0 0 62px;text-align:center}
.brd .bln{height:72px;border-left:1.5px dashed var(--mc);opacity:.55;margin:0 auto;width:0}
.brd .blb{font-size:10.5px;font-weight:700;letter-spacing:.08em;color:var(--muted);
  text-transform:uppercase;margin-top:12px}
.brd .bld{font-size:12px;font-weight:700;margin-top:4px;font-variant-numeric:tabular-nums}

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
 /* склад / стафіровка — будівля з колонами */
 warehouse:'<path d="M2.6 9.3 12 3.6l9.4 5.7"/><path d="M4.2 9.3h15.6"/>'
          +'<path d="M6.1 11.6v7M9.4 11.6v7M12 11.6v7M14.6 11.6v7M17.9 11.6v7"/>'
          +'<path d="M4.2 18.6h15.6"/><path d="M2.6 20.8h18.8"/>',
 /* митне оформлення на експорт — документ із печаткою-галочкою */
 customs:'<path d="M6.4 2.9h6.7l4.3 4.2v9.2"/><path d="M6.4 2.9v18.2h6.4"/>'
        +'<path d="M13.1 2.9v4.2h4.3"/><path d="M9 9.6h4.6M9 12.4h3.2"/>'
        +'<circle cx="17.2" cy="17.4" r="3.9"/><path d="M15.5 17.5l1.2 1.2 2.3-2.4"/>',
 /* імпортне митне оформлення — інспектор у кашкеті */
 officer:'<path d="M6.1 8.5h11.8"/><path d="M8.4 8.5a3.6 3.6 0 0 1 7.2 0"/>'
        +'<circle cx="12" cy="13" r="2.9"/>'
        +'<path d="M5.4 21.2c0-3.2 2.9-4.9 6.6-4.9s6.6 1.7 6.6 4.9"/>',
 /* портовий кран над контейнерами */
 crane:'<path d="M2.8 6.6h18.4"/><path d="M6.4 6.6v9.8M17.6 6.6v9.8"/>'
      +'<path d="M12 6.6v3.3"/><path d="M9.5 9.9h5v3.4h-5z"/>'
      +'<path d="M5.2 16.4h6.2v4.2H5.2z"/><path d="M13.2 17.6h5.6v3h-5.6z"/>'
      +'<path d="M2.6 20.8h18.8"/>',
 /* судно на хвилях */
 ship:'<path d="M3.1 14.1h17.8l-2.6 4.2H5.7z"/><path d="M8.2 7.4h5.3v6.7H8.2z"/>'
     +'<path d="M13.5 4.4h3.9l-3.9 2.5z"/><path d="M13.5 4.4v3"/>'
     +'<path d="M2.4 20.6c1.6 0 1.6 1 3.2 1s1.6-1 3.2-1 1.6 1 3.2 1 1.6-1 3.2-1 1.6 1 3.2 1"/>',
 /* літак */
 plane:'<path d="M20.9 6.6a1.6 1.6 0 0 0-2.3-2.3l-3.9 3.9-8.1-2.4-1.5 1.5 6.3 4-3 3-3-.6-1.2 1.2 3.8 2.1 2.1 3.8 1.2-1.2-.6-3 3-3 4 6.3 1.5-1.5-2.4-8.1z"/>',
 /* потяг */
 train:'<path d="M6.2 4.2h11.6v10.2H6.2z"/><path d="M8.6 6.8h6.8v4.2H8.6z"/>'
      +'<path d="M6.2 14.4l-2 3.6M17.8 14.4l2 3.6"/>'
      +'<circle cx="9.1" cy="17.4" r="1.6"/><circle cx="14.9" cy="17.4" r="1.6"/>'
      +'<path d="M2.6 20.9h18.8"/>',
 /* фура */
 truck:'<path d="M2.4 6.4h11.2v9.4H2.4z"/><path d="M13.6 9.8h3.5l3.4 3.2v2.8h-6.9z"/>'
      +'<path d="M2.4 15.8h18.1"/>'
      +'<circle cx="6.7" cy="18" r="2"/><circle cx="16.9" cy="18" r="2"/>',
 /* перевалка — два зустрічні контейнери-стрілки */
 swap:'<path d="M3.4 8.6h14.2"/><path d="M14.6 5.4 17.8 8.6l-3.2 3.2"/>'
     +'<path d="M20.6 15.4H6.4"/><path d="M9.4 12.2 6.2 15.4l3.2 3.2"/>',
 /* доставлено — 3D-коробка */
 box:'<path d="M12 3.2 20.6 7.6v8.8L12 20.8 3.4 16.4V7.6z"/>'
    +'<path d="M3.4 7.6 12 12l8.6-4.4"/><path d="M12 12v8.8"/>'
    +'<path d="M7.7 5.4 16.3 9.8"/>',
 /* документ (список файлів у картці) */
 doc:'<path d="M6.5 3h7l4 4v14h-11z"/><path d="M13.5 3v4h4"/><path d="M9 12h6M9 16h6"/>',
 port:'<circle cx="12" cy="4.6" r="1.9"/><path d="M12 6.8V19.4"/><path d="M8.3 10h7.4"/>'
     +'<path d="M4.8 13.4a7.2 7.2 0 0 0 14.4 0"/>',
};
const svg = (k, px) => `<svg viewBox="0 0 24 24" width="${px||21}" height="${px||21}" fill="none"
  stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">${I[k]}</svg>`;

/* ── колір за видом перевезення (як у макеті користувачки) ──────────── */
const MODE_PAL = {
  sea : {c:"#1a6fc4", bg:"#e8f1fb", nm:"Море"},
  air : {c:"#8b3fa8", bg:"#f4e9f8", nm:"Авіа"},
  road: {c:"#b8651b", bg:"#fbeee0", nm:"Авто"},
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
  const moveI = A ? "plane" : (R ? "train" : (modeOf(r) === "road" ? "truck" : "ship"));
  const moveT = A ? "В повітрі" : (modeOf(r) === "road" ? "В дорозі" : "В морі");

  const transship = () => {
    const tp = s(r,"Порт перевалки");
    if (!tp) return [];
    const ta = s(r,"Перевалка (прибуття)"), td = s(r,"Перевалка (відправлення)");
    return [{ k:"tship", t:"Перевалка", i:"swap", d:ta, d2:td, f:true, p:tp }];
  };

  if (!imp){
    /* ЕКСПОРТ */
    return [
      { k:"stuff", t:"Стафіровка",          i:"warehouse", d:s(r,"Stuffing"), f:true, p:from },
      { k:"cust1", t:"Митне оформлення<br>на експорт", i:"customs", d:"", f:true, p:"" },
      { k:"border", t:"Кордон",              i:"border",    d:s(r,"На кордоні") || s(r,"Перетин кордону (факт)"), f:true, p:"" },
      { k:"pol", t:A?"Аеропорт відправлення":"Порт відправлення", i:"crane",
        d:s(r,"Здача в порт (факт)") || s(r,"Гейт ін"), f:true, p:from },
      { k:"move", t:moveT, i:moveI, d:etd, f:etdF, p:s(r,"Судно"), dur:days(etd, eta) },
    ].concat(transship(), [
      { k:"cust2", t:"Імпортне митне<br>оформлення", i:"officer", d:"", f:true, p:"" },
      { k:"done", t:"Вантаж доставлено",   i:"box",
        d:s(r,"Вивантаження у отримувача (факт)") || s(r,"Планова до клієнта (факт)") || eta,
        f:!!s(r,"Вивантаження у отримувача (факт)"), p:fin || to },
    ]);
  }

  /* ІМПОРТ */
  const car  = s(r,"Подача авто (факт)") || s(r,"Подача авто (план)") || s(r,"Гейт аут");
  const carF = !!(s(r,"Подача авто (факт)") || s(r,"Гейт аут"));
  /* Вид наземного плеча беремо зі СТАТУСУ, якщо він прямо його називає, і лише
     інакше — з «Вид перевезення». Причина (угода 239, 02.08.2026): трекінг
     поставив «Завантажений на потяг», а в полі виду стояло «фрахт+ТЕО+авто»,
     і схема малювала авто. Статус тут свіжіший за довідкове поле. */
  const st = s(r,"Статус");
  const byTrain = /потяг/i.test(st) ? true : (/на авто/i.test(st) ? false : R);
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
  let cur = st.findIndex(x => x.k === ST_STEP[s(r,"Статус")]);
  if (cur < 0){                               // статусу немає в мапі — за датами
    cur = st.findIndex(x => !(x.f && past(x.d2 || x.d)));
    if (cur < 0) cur = st.length - 1;
  }
  if (delivered) cur = st.length - 1;

  const state = st.map((x, i) =>
    delivered ? "done" : (i < cur ? "done" : (i === cur ? "now" : "todo")));

  const cells = [];
  st.forEach((x, i) => {
    if (x.i === "border"){
      cells.push(`<div class="brd"><div class="bln"></div>
        <div class="blb">КОРДОН</div>
        ${x.d ? `<div class="bld">${fmt(x.d)}</div>` : ""}</div>`);
      return;
    }
    if (i) cells.push(`<div class="cn ${i <= cur || delivered ? "on" : ""}"></div>`);
    cells.push(`<div class="nd ${state[i]}">
      <div class="dot">${svg(x.i)}</div>
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
function visible(){
  const q=Q.toLowerCase();
  return DEALS.filter(r=>{
    if (FILTER==="act"  && done(r)) return false;
    if (FILTER==="done" && !done(r)) return false;
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
  const soon = act.filter(r=>{const e=s(r,"ETA"); return e && e>=TODAY && e<=addDays(TODAY,7);});
  const docs = DEALS.reduce((n,r)=>n+(r._docs||[]).length,0);
  const TICON =[["ship","ic-blue"],["port","ic-amber"],["box","ic-green"],["doc","ic-vio"]];
  document.getElementById("tiles").innerHTML = [
    [act.length,"вантажів у дорозі"],
    [soon.length,"прибувають за 7 днів"],
    [DEALS.length-act.length,"доставлено"],
    [docs,"документів доступно"],
  ].map(([n,l],i)=>`<div class="tile">
      <div class="ic ${TICON[i][1]}">${svg(TICON[i][0])}</div>
      <div><div class="n">${n}</div><div class="l">${l}</div></div>
    </div>`).join("");

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
    </tr>`;
  }).join("") : `<tr><td colspan="9" class="empty" style="padding:20px 12px">Нічого не знайдено.</td></tr>`;

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
  e.className="exp"; e.innerHTML=`<td colspan="9">${panel(r)}</td>`;
  tr.after(e);
}
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
