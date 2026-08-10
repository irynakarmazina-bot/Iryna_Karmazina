/* Перевірка: чи справді звіт ховає дві нижні панелі, коли сервер не віддав їхніх
   даних — і чи не ламається при цьому все інше.

   Навіщо саме браузером, а не читанням коду: boot() у findash.html викликає
   renderEquity() і chartNwc() ОДНИМ рядком разом із рештою. Якщо котрась із них
   спіткнеться на відсутніх даних, обірветься весь рядок — і зникнуть не тільки
   ці дві панелі, а й графік прогнозу, посилання та депозити. Побачити це можна
   лише виконавши сторінку.

   Ще важливіше: у findash.html падіння boot() не просто «щось не намалювалось».
   Там `try{ boot(m.data) } catch(err){ document.body.innerHTML = 'Помилка: …' }` —
   тобто сторінка ЦІЛКОМ замінюється червоним написом. Без перевірок на порожні
   дані фінансист замість звіту побачив би саме його.

   Сторінка відкривається ТІЛЬКИ в рамці: сама по собі вона стирає себе написом
   «Ця сторінка відкривається всередині платформи». Тому тест піднімає таку саму
   рамку і передає дані повідомленням, як це робить платформа.

   Прогін двічі: з повними даними (панелі мають бути) і без двох ключів
   (панелі мають зникнути, решта лишитись).

   Запуск: node scripts/findash_hide.js [шлях/до/findash.html]
           (браузер: PW=<шлях до playwright>)
*/
const http = require("http");
const path = require("path");
const fs = require("fs");
const { chromium } = require(process.env.PW || "playwright");

const FILE = process.argv[2] || path.join(__dirname, "..", "www", "findash.html");
const DIR = path.dirname(FILE);
const PAGE = path.basename(FILE);

const m = n => Array.from({ length: n }, (_, i) => ["2026-0" + (i + 1), 1000 + i * 10, 1200 + i * 10]);

const FULL = {
  updated: "11.08.2026", dataDate: "10.08.2026", cardTrendBase: "01.08",
  cards: { cash: 10000, ar: 20000, ap: 5000, wip: 3000, frozen: 18000, nwc: 15000 },
  cardTrends: {}, deposit: 2500, dso: 41, frozen: { net: 18000 },
  calendar: [["зараз", 0, 0, 10000, "факт"], ["+1", 500, 300, 10200, "план"]],
  cashReal: [["Банк Юнітекс Ейч-Ді", 8000], ["Каса", 2000]],
  arAging: [["0-30", 12000], ["31-60", 8000]], apAging: [["0-30", 5000]],
  apAgingLabel: "за строками", arDetail: [], apDetail: [],
  clients: [["Клієнт А", 12000], ["Клієнт Б", 8000]], clientsTotal: 20000,
  wipTop: [["251", 3000]], signals: [["ok", "Все гаразд", ""]],
  forecast: [["01.08", 9000], ["10.08", 10000]],
  equity: [["Власник 1", 50000, 10000, 40000], ["Разом", 50000, 10000, 40000]],
  equityMonthly: [["2026-01", "Власник 1", 50000, 0]],
  nwcMonthly: m(6),
};

/* Рамка-обгортка: робить рівно те, що робить платформа — чекає на «findash-ready»
   і у відповідь віддає дані. Без неї сторінка стирає себе. */
const HARNESS = page => `<!doctype html><meta charset="utf-8"><body style="margin:0">
<iframe id="f" src="/${page}" style="width:1200px;height:2400px;border:0"></iframe>
<script>
/* window.DATA підставляється ДО завантаження сторінки (addInitScript). Тут його
   НЕ можна ініціалізувати — присвоєння виконалось би пізніше і затерло б дані. */
addEventListener("message", function(e){
  if ((e.data||{}).type === "findash-ready" && window.DATA)
    document.getElementById("f").contentWindow.postMessage({type:"findata", data: window.DATA}, "*");
});
<\/script>`;

const serve = (dir, page) => new Promise(res => {
  const types = { ".html": "text/html", ".js": "application/javascript" };
  const s = http.createServer((rq, rs) => {
    const url = decodeURIComponent(rq.url.split("?")[0]);
    if (url === "/harness.html") {
      rs.writeHead(200, { "Content-Type": "text/html" });
      return rs.end(HARNESS(page));
    }
    const f = path.join(dir, url);
    if (!fs.existsSync(f)) { rs.writeHead(404); return rs.end("no"); }
    rs.writeHead(200, { "Content-Type": types[path.extname(f)] || "text/plain" });
    rs.end(fs.readFileSync(f));
  });
  s.listen(0, "127.0.0.1", () => res([s, s.address().port]));
});

(async () => {
  const [srv, port] = await serve(DIR, PAGE);
  const browser = await chromium.launch();
  let fail = 0;

  const run = async (label, data) => {
    const page = await browser.newPage();
    const errs = [];
    page.on("pageerror", e => errs.push(String(e).slice(0, 120)));
    await page.addInitScript(d => { window.DATA = d; }, data);
    await page.goto(`http://127.0.0.1:${port}/harness.html`);
    await page.waitForTimeout(900);
    const frame = page.frames().find(f => f.url().includes(PAGE));
    if (!frame) { console.log("  ✗ рамка зі звітом не знайшлась"); fail = 1; return { seen: {}, errs }; }
    const seen = await frame.evaluate(() => {
      const vis = id => {
        const el = document.getElementById(id);
        return !!el && getComputedStyle(el).display !== "none";
      };
      const txt = id => (document.getElementById(id) || {}).textContent || "";
      return {
        nwcPanel: vis("nwc"), eqPanel: vis("eqp"),
        cards: (document.getElementById("cards") || {}).children?.length || 0,
        nwcTile: txt("cards").includes("Робочий капітал (NWC)"),
        frozenTile: txt("cards").includes("Заморожений капітал"),
        forecast: !!document.getElementById("fc"),
        signals: ((document.getElementById("sig") || {}).children || []).length,
        // якщо boot() впав, findash замінює всю сторінку червоним написом
        crashText: (document.body.textContent||"").slice(0,120),
        crashed: document.body.innerHTML.indexOf("Помилка:") === 0
                 || /^\s*<div style="padding:20px;color:#d1453b">/.test(document.body.innerHTML),
      };
    });
    await page.close();
    return { seen, errs };
  };

  const a = await run("повні дані", FULL);
  const hidden = Object.assign({}, FULL);
  delete hidden.equity; delete hidden.equityMonthly; delete hidden.nwcMonthly;
  const b = await run("без двох панелей", hidden);

  const check = (name, got, want) => {
    const ok = got === want;
    if (!ok) fail = 1;
    console.log(`  ${ok ? "✓" : "✗"} ${name}${ok ? "" : `  (отримано ${got}, треба ${want})`}`);
  };

  console.log("\n— ПОВНІ ДАНІ (як бачить адміністратор і бухгалтер) —");
  check("панель «Робочий капітал по місяцях» показана", a.seen.nwcPanel, true);
  check("панель «Внески власників» показана", a.seen.eqPanel, true);
  check("звіт не впав", a.seen.crashed, false);
  if (a.seen.crashed) console.log("      текст:", a.seen.crashText);
  check("помилок на сторінці немає", a.errs.length, 0);
  if (a.errs.length) a.errs.forEach(e => console.log("      " + e));

  console.log("\n— БЕЗ ДВОХ КЛЮЧІВ (як бачитиме фінансист) —");
  check("панель «Робочий капітал по місяцях» ЗНИКЛА", b.seen.nwcPanel, false);
  check("панель «Внески власників» ЗНИКЛА", b.seen.eqPanel, false);
  check("плиток угорі стільки ж", b.seen.cards, a.seen.cards);
  check("плитка «Робочий капітал (NWC)» на місці", b.seen.nwcTile, true);
  check("плитка «Заморожений капітал» на місці", b.seen.frozenTile, true);
  check("графік прогнозу лишився", b.seen.forecast, true);
  check("сигнали лишились", b.seen.signals, a.seen.signals);
  check("звіт НЕ замінився червоною помилкою", b.seen.crashed, false);
  check("помилок на сторінці немає", b.errs.length, 0);
  if (b.errs.length) b.errs.forEach(e => console.log("      " + e));

  await browser.close();
  srv.close();
  console.log("");
  console.log(fail ? "FINDASH_HIDE_FAIL — звіт поводиться не так"
                   : "FINDASH_HIDE_OK — дві панелі ховаються, решта звіту ціла");
  process.exit(fail);
})();
