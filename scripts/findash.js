/* Перевірка плитки «Усього в обороті» у findash.html — контрольної суми, яку
   попросила користувачка 13.08.2026 («вся цифра, з внесками, те, що в обороті і
   має рости»).

   Перевіряється: значення = cards.nwcDep; тренд рахується з nwcMonthly, а не з
   cardTrends (сервер його для цього ключа не рахує); плитки НЕМАЄ у верхньому
   ряду і вона стоїть ПРАВОРУЧ від платіжного календаря — саме так просила
   користувачка («не малюй зверху»).

   Числа в заглушці РЕАЛЬНІ, з dashboard_data.json станом на 12.08.2026; решта
   ключів — порожні, бо мета перевірити плитку, а не весь звіт. Сторінка отримує
   дані не запитом, а через postMessage від платформи — тому вона відкривається
   всередині рамки, як і в житті.

   Запуск: node scripts/findash.js www/findash.html
   Браузер: PW=/opt/node22/lib/node_modules/playwright node scripts/findash.js … */
const path = require("path");
const fs = require("fs");
const http = require("http");
const { chromium } = require(process.env.PW || "playwright");

const SAFE = n => {
  // дозволяємо лише підтеки всередині www: жодних ".." нагору
  const rel = path.normalize(n).replace(/^(\.\.[/\\])+/, "");
  return rel;
};

const FILE = process.argv[2];
const WWW = path.dirname(FILE);

const D = {
  cards: { cash: 58091.94, ar: 14102.25, ap: 22044.28, wip: 43692.39,
           nwc: 93842.3, nwcDep: 101842.3, frozen: 35750.36 },
  deposit: 8000.0,
  cardTrends: {
    cash:{spark:[55590,56000,58091.94],pct:"4.5",dir:"up"},
    ar:{spark:[19641,17000,14102.25],pct:"28.2",dir:"down"},
    ap:{spark:[11871,15000,22044.28],pct:"85.7",dir:"up"},
    wip:{spark:[42585,43000,43692.39],pct:"2.6",dir:"up"},
    frozen:{spark:[50355,45000,35750.36],pct:"29.0",dir:"down"},
    nwc:{spark:[105946,100000,93842.3],pct:"11.5",dir:"down"} },
  cardTrendBase: "31.07",
  nwcMonthly: [["30.06", 58209.71, 66209.71], ["31.07", 105983.96, 113983.96], ["12.08", 93842.3, 101842.3]],
  cashReal: [["Банк Юнітекс Ейч-Ді", "50 000,00", "USD"]], cashReal_main: [], cashReal_more: [],
  pnlMonths: [], pnlMonthsLabels: [], pnlByMonth: [], oborotByMonth: [], pnlClassicByMonth: [],
  opexGroups: [], opexByMonth: [], arAging: [["0-30", 14102.25, 11]], dso: 20,
  apAging: [["0-30", 22044.28, 94]], apAgingLabel: "", arDetail: [], apDetail: [],
  frozen: { wip: 43692.39, net: 35750.36 }, cashflowWeekly: [], wipTop: [],
  clients: [], clientsTotal: 0, forecast: [], forecastSplit: [], calendar: [],
  equity: [["Разом", 65999.0, 3650.0, 62349.0]], equityMonthly: [], signals: [],
  dataDate: "12.08.2026", updated: "12.08.2026",
};

const fail = [];
const check = (ok, what) => { console.log((ok ? "  ✓ " : "  ✗ ") + what); if (!ok) fail.push(what); };

(async () => {
  const srv = http.createServer((req, res) => {
    const name = decodeURIComponent(req.url.split("?")[0]).replace(/^\/+/, "") || "findash.html";
    if (name === "wrap.html") {
      res.setHeader("Content-Type", "text/html");
      return res.end('<!doctype html><body style="margin:0">' +
        '<iframe id="fr" src="/findash.html" style="width:1500px;height:2400px;border:0"></iframe>' +
        '<script>window.addEventListener("message",function(e){' +
        'if((e.data||{}).type==="findash-ready"){' +
        'document.getElementById("fr").contentWindow.postMessage({type:"findata",data:' +
        JSON.stringify(D) + '},"*");}});<\/script></body>');
    }
    fs.readFile(path.join(WWW, SAFE(name)), (err, buf) => {
      if (err) { res.statusCode = 404; return res.end("no"); }
      res.setHeader("Content-Type", name.endsWith(".js") ? "text/javascript" : "text/html");
      res.end(buf);
    });
  });
  await new Promise(r => srv.listen(0, "127.0.0.1", r));
  const port = srv.address().port;

  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1500, height: 900 } });
  const errors = [];
  page.on("pageerror", e => errors.push("JS: " + e.message));
  page.on("console", m => { if (m.type() === "error" && !/Failed to load resource/.test(m.text())) errors.push("console: " + m.text()); });
  await page.goto("http://127.0.0.1:" + port + "/wrap.html");
  const frame = page.frameLocator("#fr");
  await frame.locator("#cards .card").first().waitFor({ timeout: 10000 });
  await page.waitForTimeout(700);

  const cards = await page.frames()[1].$$eval("#cards .card", els => els.map(e => e.innerText.replace(/\n/g, " | ")));
  console.log("\n— верхній ряд плиток —");
  cards.forEach(c => console.log("   " + c));
  const mine = await page.frames()[1].$eval("#capital", e => e.innerText.replace(/\n/g, " | ")).catch(() => "");
  console.log("\n— біля платіжного календаря —");
  console.log("   " + mine);
  console.log("");
  check(!cards.some(c => /Усього в обороті/.test(c)), "у верхньому ряду її НЕМАЄ (як просила)");
  check(!!mine && /Усього в обороті/.test(mine), "плитка намалювалась біля платіжного календаря");
  check(!!mine && /101 842/.test(mine.replace(/ /g, " ")), "показує 101 842 (NWC + депозит)");
  check(!!mine && /гроші \+ депозит/.test(mine), "під нею написана формула");
  // 101842.3 / 113983.96 - 1 = -10.65%
  check(!!mine && /10\.7%|10,7%/.test(mine), "тренд −10.7% проти 31.07 (порахований з nwcMonthly)");
  check(!!mine && /↘/.test(mine), "стрілка вниз");
  check(cards.length === 6, "у верхньому ряду 6 старих плиток, нічого не зникло (там " + cards.length + ")");
  const pk = await page.frames()[1].$eval(".pkrow", e => {
    const r = e.getBoundingClientRect();
    const cal = e.querySelector("#pk").getBoundingClientRect();
    const cap = e.querySelector("#capital").getBoundingClientRect();
    return { calLeft: cal.left - r.left, calRight: cal.right - r.left, capLeft: cap.left - r.left, capW: cap.width, calW: cal.width };
  });
  check(pk.capLeft >= pk.calRight - 1, "плитка стоїть ПРАВОРУЧ від календаря");
  check(pk.calW > pk.capW, "календар ширший за плитку (" + Math.round(pk.calW) + " проти " + Math.round(pk.capW) + ")");

  /* Знімок робимо ЛИШЕ на прохання: SHOT=/шлях/до/файла.png node scripts/findash.js …
     Було `path.join(__dirname, …)` — тобто файл падав просто в scripts/, потрапляв
     у репозиторій і його підбирало автозбереження сесії (13.08.2026, знімок на
     211 КБ). Перевірка не повинна лишати сміття там, де лежить код. */
  if (process.env.SHOT) await page.screenshot({ path: process.env.SHOT, fullPage: true });

  if (errors.length) { console.log("\nПОМИЛКИ В БРАУЗЕРІ:"); errors.forEach(e => console.log("   " + e)); }
  await browser.close(); srv.close();
  const bad = fail.length || errors.length;
  console.log(bad ? "\nFINDASH_FAIL — не пройшло: " + fail.length + ", помилок JS: " + errors.length
                  : "\nFINDASH_OK — плитка «Усього в обороті» працює");
  process.exit(bad ? 1 : 0);
})();
