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


def client_title(name):
    n = re.sub(r"\s+", " ", str(name or "")).strip()
    if not n or n.lower() in NO_LEGAL:
        return n
    if re.search(r"(ТОВ|ООО|ЧП|ПП|LLC|LTD)", n, re.I):
        return n                      # форма вже є в назві — не дублюємо
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
:root{
  --paper:#f9f9f7; --surface:#fff; --surface-2:#f4f4f0;
  --ink:#0b0b0b; --ink-2:#52514e; --muted:#898781;
  --line:#e1e0d9; --line-soft:#eeede8;
  --accent:#2a78d6; --accent-soft:#e7f0fb; --accent-ink:#1c5cab;
  --pos:#1a8f5c; --warn:#c8811f; --neg:#d1453b;
}
*{box-sizing:border-box}
body{margin:0;background:var(--paper);color:var(--ink);
  font:14px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif}
header{background:var(--surface);border-bottom:1px solid var(--line);
  padding:12px 26px;display:flex;align-items:center;gap:18px;position:sticky;top:0;z-index:5}
header img{height:56px}
.hdr-t{font-weight:700;font-size:15px}
.hdr-s{color:var(--muted);font-size:13px}
.spacer{flex:1}
.who{text-align:right;line-height:1.3}
.who b{display:block;font-size:15px;font-weight:700}
main{max-width:1500px;margin:0 auto;padding:22px 26px 60px}
.proto{background:#fff6e3;border:1px solid #eccf94;color:#7a5a1b;border-radius:10px;
  padding:9px 14px;font-size:12.5px;margin-bottom:18px}
.tiles{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin-bottom:20px}
.tile{background:var(--surface);border:1px solid var(--line);border-radius:12px;padding:14px 16px}
.tile .n{font-size:26px;font-weight:700;letter-spacing:-.5px}
.tile .l{color:var(--muted);font-size:12px;text-transform:uppercase;letter-spacing:.04em;margin-top:2px}
.bar{display:flex;gap:10px;align-items:center;margin-bottom:12px;flex-wrap:wrap}
.bar input{flex:1;min-width:220px;padding:9px 12px;border:1px solid var(--line);
  border-radius:9px;background:var(--surface);font:inherit;color:var(--ink)}
.seg{display:flex;border:1px solid var(--line);border-radius:9px;overflow:hidden;background:var(--surface)}
.seg button{border:0;background:transparent;padding:9px 15px;font:inherit;cursor:pointer;color:var(--ink-2)}
.seg button.on{background:var(--accent-soft);color:var(--accent-ink);font-weight:600}
table{width:100%;border-collapse:collapse;background:var(--surface);
  border:1px solid var(--line);border-radius:12px;overflow:hidden}
th{text-align:left;font-size:11px;text-transform:uppercase;letter-spacing:.05em;
  color:var(--muted);font-weight:600;padding:11px 12px;border-bottom:1px solid var(--line);white-space:nowrap}
td{padding:11px 12px;border-bottom:1px solid var(--line-soft);vertical-align:middle}
tr.deal{cursor:pointer}
tr.deal:hover td{background:var(--surface-2)}
tr.deal.open td{background:var(--accent-soft)}
.mono{font-variant-numeric:tabular-nums}
.num{font-weight:700}
.chip{display:inline-block;font-size:11px;font-weight:700;padding:2px 7px;border-radius:6px;
  background:var(--accent-soft);color:var(--accent-ink)}
.chip.exp{background:#e9f4ec;color:#1a6b42}
.d{font-weight:700;white-space:nowrap}
.dim{color:var(--muted)}
.pill{display:inline-block;font-size:12px;font-weight:600;padding:3px 10px;border-radius:99px;
  background:var(--surface-2);color:var(--ink-2);white-space:nowrap}
.pill.sea{background:#e7f0fb;color:#1c5cab}
.pill.ok{background:#e9f4ec;color:#1a6b42}
.pill.wait{background:#fdf3e2;color:#8a5d13}
.docn{display:inline-flex;align-items:center;gap:5px;color:var(--accent-ink);font-weight:600}
/* ── розгортка ─────────────────────────────────────────── */
tr.exp>td{padding:0;background:var(--surface-2)}
.panel{padding:22px 24px 26px;border-top:2px solid var(--accent)}
.pbar{display:flex;align-items:baseline;gap:12px;flex-wrap:wrap;margin-bottom:20px}
.pbar .st{font-size:17px;font-weight:700}
.pbar .sub{color:var(--ink-2)}
/* схема руху — стиль за макетом користувачки 01.08.2026: колір за видом
   перевезення, «КОРДОН» пунктирним роздільником, тривалість переходу,
   легенда внизу. */
.route{background:var(--surface);border:1px solid var(--line);border-radius:12px;
  padding:24px 18px 14px;overflow-x:auto}
.chain{display:flex;align-items:flex-start;min-width:900px}
.nd{flex:0 0 104px;text-align:center;position:relative}
.cn{flex:1 1 auto;height:2px;background:var(--line);margin-top:23px;border-radius:2px;min-width:14px}
.cn.on{background:var(--mc)}
.nd .dot{width:46px;height:46px;margin:0 auto;border-radius:50%;
  background:var(--surface);border:2px solid var(--line);color:var(--muted);
  display:flex;align-items:center;justify-content:center}
.nd.done .dot{background:var(--mbg);border-color:var(--mc);color:var(--mc)}
.nd.now  .dot{background:var(--mc);border-color:var(--mc);color:#fff;
  box-shadow:0 0 0 5px var(--mbg)}
.nd.todo .dot{border-style:dashed}
.nd .ttl{font-size:11.5px;font-weight:700;margin-top:8px;line-height:1.25;color:var(--ink-2)}
.nd.now .ttl{color:var(--mc)}
.nd .place{font-size:10.5px;color:var(--muted);margin-top:2px;line-height:1.25}
.nd .dur{font-size:12px;font-weight:700;color:var(--mc);margin-top:3px}
.nd .dt{font-size:12px;font-weight:700;margin-top:3px;font-variant-numeric:tabular-nums}
.nd .dt.dim{color:var(--muted);font-weight:600}
.nd .plan{font-size:10px;color:var(--muted)}
/* «Кордон» — роздільник між ділянками маршруту */
.brd{flex:0 0 62px;text-align:center;padding-top:6px}
.brd .bln{height:44px;border-left:2px dashed var(--line);margin:0 auto;width:0}
.brd .blb{font-size:10px;font-weight:700;letter-spacing:.06em;color:var(--muted);
  text-transform:uppercase;margin-top:8px}
.brd .bld{font-size:11.5px;font-weight:700;margin-top:3px;font-variant-numeric:tabular-nums}
/* деталі + документи */
.cols{display:grid;grid-template-columns:1.15fr 1fr;gap:18px;margin-top:18px}
@media(max-width:1000px){.cols{grid-template-columns:1fr}}
.card{background:var(--surface);border:1px solid var(--line);border-radius:12px;padding:16px 18px}
.card h4{margin:0 0 12px;font-size:12px;text-transform:uppercase;letter-spacing:.05em;color:var(--muted)}
.kv{display:grid;grid-template-columns:auto 1fr;gap:7px 16px;font-size:13.5px}
.kv .k{color:var(--muted)}
.kv .v{font-weight:600;word-break:break-word}
.doc{display:flex;align-items:center;gap:10px;padding:9px 0;border-bottom:1px solid var(--line-soft)}
.doc:last-child{border-bottom:0}
.doc .nm{flex:1}
.doc .nm b{display:block;font-size:13.5px}
.doc .nm span{font-size:11.5px;color:var(--muted)}
.btn{border:1px solid var(--line);background:var(--surface);border-radius:8px;
  padding:6px 12px;font:inherit;font-size:12.5px;cursor:pointer;color:var(--accent-ink);font-weight:600}
.btn:hover{background:var(--accent-soft)}
.btn.prim{background:var(--accent);border-color:var(--accent);color:#fff}
.empty{color:var(--muted);font-size:13px;padding:8px 0}
.msg textarea{width:100%;min-height:74px;border:1px solid var(--line);border-radius:9px;
  padding:10px 12px;font:inherit;resize:vertical;background:var(--surface);color:var(--ink)}
.msg .row{display:flex;justify-content:space-between;align-items:center;margin-top:10px;gap:10px}
.up{border:1.5px dashed var(--line);border-radius:10px;padding:14px;text-align:center;
  color:var(--muted);font-size:12.5px;margin-top:12px}
.foot{margin-top:26px;color:var(--muted);font-size:12px;text-align:center}
</style>

<header>
  <img src="__LOGO__" alt="UNITEX">
  <div class="spacer"></div>
  <div class="who"><b>__CLIENT__</b></div>
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

  <table>
    <thead><tr>
      <th>Угода</th><th></th><th>Маршрут</th><th>Коносамент / контейнер</th>
      <th>Судно</th><th>Відправлення</th><th>Прибуття</th><th>Статус</th><th>Документи</th>
    </tr></thead>
    <tbody id="rows"></tbody>
  </table>

  <div class="foot">Дані оновлюються автоматично з систем ліній. Питання — через форму в картці вантажу.</div>
</main>

<script>
const DEALS = __DATA__;
const TODAY = "__TODAY__";

const s = (r,k) => String(r[k]||"").trim();
const fmt = v => { const m=/(\d{4})-(\d{2})-(\d{2})/.exec(String(v||"")); return m?`${m[3]}.${m[2]}.${m[1].slice(2)}`:""; };
const esc = t => String(t==null?"":t).replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const air  = r => /авіа/i.test(s(r,"Вид перевезення"));
const rail = r => /залізни/i.test(s(r,"Вид перевезення"));
const done = r => s(r,"Статус")==="Вантаж доставлено";
const past = d => d && d <= TODAY;

/* ── іконки: прості лінійні фігури, 24×24 ─────────────── */
const I = {
 doc : '<path d="M6.5 3h7l4 4v14h-11z"/><path d="M13.5 3v4h4"/><path d="M9 12h6M9 16h6"/>',
 truck:'<path d="M2.5 7h10.5v9H2.5z"/><path d="M13 10.5h3.6l3.4 3.2V16H13z"/><circle cx="6.6" cy="18" r="1.9"/><circle cx="16.6" cy="18" r="1.9"/>',
 ship: '<path d="M3.5 16h17l-2.2 4.2H5.7z"/><path d="M8 9h6v7H8z"/><path d="M14 6h4l-4 2.4z"/><path d="M14 6v3"/>',
 plane:'<path d="M2.5 13.2 21.5 7l-5.6 11.4-2.9-4.6z"/><path d="M13 13.8 21.5 7"/>',
 port: '<circle cx="12" cy="5" r="2"/><path d="M12 7.2V19"/><path d="M8.2 10.2h7.6"/><path d="M5 13.4a7 7 0 0 0 14 0"/>',
 crane:'<path d="M4.5 20.5V4h11"/><path d="M15 4v3.6"/><path d="M12.4 8h6.6v5h-6.6z"/>',
 train:'<path d="M6 4.5h12v10H6z"/><path d="M8.6 7.4h6.8v4H8.6z"/><circle cx="9" cy="17.6" r="1.6"/><circle cx="15" cy="17.6" r="1.6"/><path d="M3.5 21h17"/>',
 home: '<path d="M3.5 11 12 3.8l8.5 7.2v9.5h-17z"/><path d="M9.6 20.5v-5.4h4.8v5.4"/>',
 swap: '<path d="M3.5 9.2h15.5"/><path d="M15.6 5.8 19 9.2l-3.4 3.4"/><path d="M20.5 15.2H5"/><path d="M8.4 11.8 5 15.2l3.4 3.4"/>',
 warehouse:'<path d="M3 9.4 12 4.2l9 5.2"/><path d="M4.8 9.4v10M9.6 9.4v10M14.4 9.4v10M19.2 9.4v10"/><path d="M2.5 19.6h19"/>',
 customs:'<path d="M6.4 3h7.2L18 6.6V21H6.4z"/><path d="M13.6 3v3.6H18"/><path d="M9.2 13.4l2 2 3.6-3.6"/>',
 border:'<path d="M5.5 3.2v17.6"/><path d="M5.5 4.6h11l-2.2 3.2 2.2 3.2h-11"/>',
 box:'<path d="M12 3.4 20.4 7.7v8.6L12 20.6 3.6 16.3V7.7z"/><path d="M3.6 7.7 12 12l8.4-4.3"/><path d="M12 12v8.6"/>',
};
const svg = k => `<svg viewBox="0 0 24 24" width="21" height="21" fill="none"
  stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">${I[k]}</svg>`;

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
  const route = s(r,"Маршрут").split(/→|->/).map(x=>x.trim()).filter(Boolean);
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
    return [{ t:"Перевалка", i:"swap", d:ta, d2:td, f:true, p:tp }];
  };

  if (!imp){
    /* ЕКСПОРТ */
    return [
      { t:"Стафіровка",          i:"warehouse", d:s(r,"Stuffing"), f:true, p:from },
      { t:"Митне оформлення",    i:"customs",   d:"",              f:true, p:"експорт" },
      { t:"Кордон",              i:"border",    d:s(r,"На кордоні") || s(r,"Перетин кордону (факт)"), f:true, p:"" },
      { t:A?"Аеропорт відправлення":"Порт відправлення", i:"crane",
        d:s(r,"Здача в порт (факт)") || s(r,"Гейт ін"), f:true, p:from },
      { t:moveT, i:moveI, d:etd, f:etdF, p:s(r,"Судно"), dur:days(etd, eta) },
    ].concat(transship(), [
      { t:"Митне оформлення",    i:"customs",   d:"",  f:true, p:"імпорт" },
      { t:"Вантаж доставлено",   i:"box",
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
  land.push({ t: byTrain ? "Завантажений на потяг" : "Завантажений на авто",
              i: byTrain ? "train" : "truck", d: car, f: carF, p:"" });
  if (R || s(r,"ETA сухий порт"))
    land.push({ t:"Сухий порт", i:"crane", d:s(r,"ETA сухий порт"),
                f:false, p:s(r,"Сухий порт") });
  return [
    { t:"Стафіровка",         i:"warehouse", d:s(r,"Stuffing"), f:true, p:from },
    { t:"Митне оформлення",   i:"customs",   d:"",              f:true, p:"експорт" },
    { t:A?"Аеропорт відправлення":"Порт відправлення", i:"crane",
      d:s(r,"Здача в порт (факт)") || s(r,"Гейт ін"), f:true, p:from },
    { t:moveT, i:moveI, d:etd, f:etdF, p:s(r,"Судно"), dur:days(etd, eta) },
  ].concat(transship(), [
    { t:A?"Аеропорт прибуття":"Порт прибуття", i:"port", d:eta, f:etaF, p:to },
  ], land, [
    { t:"Кордон",             i:"border",  d:s(r,"На кордоні") || s(r,"Перетин кордону (факт)"), f:true, p:"" },
    { t:"Митне оформлення",   i:"customs", d:"", f:true, p:"імпорт" },
    { t:"Вантаж доставлено",  i:"box",
      d:s(r,"Вивантаження у отримувача (факт)") || s(r,"Планова до клієнта (факт)"),
      f:true, p:fin },
  ]);
}

function routeHtml(r){
  const st = steps(r), P = pal(r), delivered = done(r);
  /* Пройденим вважаємо крок із ФАКТИЧНОЮ датою в минулому. Кроки без дати
     (митне оформлення) пройдені, якщо пройдено наступний крок із датою. */
  const okAt = i => {
    const x = st[i];
    if (delivered) return true;
    return !!(x.f && past(x.d2 || x.d));
  };
  const state = st.map((x, i) => {
    if (okAt(i)) return "done";
    if (!x.d){                                   // крок без власної дати
      for (let j = i + 1; j < st.length; j++) if (st[j].d) return okAt(j) ? "done" : "todo";
    }
    return "todo";
  });
  let cur = state.indexOf("todo");
  if (!delivered && cur >= 0) state[cur] = "now";
  if (state[0] === "todo") state[0] = st[0].d ? state[0] : "done";

  const cells = [];
  st.forEach((x, i) => {
    /* «КОРДОН» — не вузол маршруту, а роздільник між ділянками: тонка
       пунктирна лінія з підписом, як у макеті користувачки (02.08.2026).
       Кола з іконкою в нього немає. */
    if (x.i === "border"){
      cells.push(`<div class="brd"><div class="bln"></div>
        <div class="blb">КОРДОН</div>
        ${x.d ? `<div class="bld">${fmt(x.d)}</div>` : ""}</div>`);
      return;
    }
    if (i) cells.push(`<div class="cn ${state[i-1]==="done"?"on":""}"></div>`);
    cells.push(`<div class="nd ${state[i]}">
      <div class="dot">${svg(x.i)}</div>
      <div class="ttl">${esc(x.t)}</div>
      ${x.p ? `<div class="place">${esc(x.p)}</div>` : ""}
      ${x.dur != null ? `<div class="dur">${x.dur} ${plural(x.dur,"день","дні","днів")}</div>` : ""}
      ${x.d ? `<div class="dt">${fmt(x.d)}${x.d2?" → "+fmt(x.d2):""}</div>${
                x.f && past(x.d2||x.d) ? "" : '<div class="plan">план</div>'}`
            : (x.dur == null ? `<div class="dt dim">—</div>` : "")}
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
  return `<div class="panel">
    <div class="pbar">
      <span class="st">${esc(s(r,"Статус")||"—")}</span>
      <span class="sub">${esc(s(r,"Маршрут")||"маршрут не вказано")}</span>
    </div>
    ${routeHtml(r)}
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
  document.getElementById("tiles").innerHTML = [
    [act.length,"вантажів у дорозі"],
    [soon.length,"прибувають за 7 днів"],
    [DEALS.length-act.length,"доставлено"],
    [docs,"документів доступно"],
  ].map(([n,l])=>`<div class="tile"><div class="n">${n}</div><div class="l">${l}</div></div>`).join("");

  document.getElementById("rows").innerHTML = rows.length ? rows.map(r=>{
    const conts = s(r,"Контейнер").split(",").map(x=>x.trim()).filter(Boolean);
    const bl = s(r,"HBL")||s(r,"BL");
    const etd = s(r,"ETD (факт)")||s(r,"ETD (план)");
    const nd = (r._docs||[]).length;
    return `<tr class="deal" data-id="${esc(s(r,"Угода"))}">
      <td class="mono num">${esc(s(r,"Угода"))}</td>
      <td><span class="chip ${s(r,"Напрямок")==="Експорт"?"exp":""}">${
          s(r,"Напрямок")==="Імпорт"?"ІМП":(s(r,"Напрямок")==="Експорт"?"ЕКС":"ТРН")}</span></td>
      <td>${esc(s(r,"Маршрут")||"—")}</td>
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
