/* Перевірка 02.09.2026 (скарга користувачки, угода 238):
   1) клітинки «Gate out» і «Доставлено» відкривають СПРАВЖНІЙ редактор дати
      (з календариком), «31.08» зберігається як 2026-08-31 — а не сирим текстом,
      з якого NocoDB робив «1970-01-01» / «Invalid Date»;
   2) після F5 відкривається та сама сторінка, а не Дашборд.
   Запуск: node scripts/dateedit.js [шлях/до/index.html] (браузер: PW=…) */
const path = require("path");
const fs = require("fs");
const http = require("http");
const { chromium } = require(process.env.PW || "playwright");

const SAFE = n => path.normalize(n).replace(/^(\.\.[/\\])+/, "");
const FILE = process.argv[2] || path.join(__dirname, "..", "www", "index.html");
const WWW = path.dirname(FILE);
const TABLES = ["Диспетчеризація", "Користувачі", "Клієнти", "Задачі",
                "Журнал дій", "Калькуляції", "Інструкції", "Авто", "Водії", "Перевізники"];
const META = { list: TABLES.map((title, i) => ({ id: "t" + (i + 1), title })), columns: [] };
const ID = n => "t" + (TABLES.indexOf(n) + 1);

const USERS = [{ Id: 1, Email: "me@x.ua", "Ім'я": "Ірина", "Прізвище": "Кармазіна", "Роль": "Адміністратор", "Активний": true }];
const DEALS = [
  { Id: 185, "Угода": "238", "Клієнт": "ОТІС ТАРДА", "Статус": "Вантаж доставлено", "Напрямок": "Імпорт",
    "Менеджер": "Ірина", "Лінія": "Maersk", "Вид перевезення": "фрахт+ТЕО+авто",
    "Контейнер": "MSKU5502244", "Гейт аут": "2026-08-25" },
];

const writes = [];
function serve() {
  return new Promise(resolve => {
    const srv = http.createServer((req, res) => {
      const name = decodeURIComponent(req.url.split("?")[0]).replace(/^\/+/, "") || "index.html";
      if (["sync-state", "sync", "cash-refresh", "localcosts-refresh"].includes(name)) {
        res.setHeader("Content-Type", "application/json"); return res.end("{}");
      }
      fs.readFile(path.join(WWW, SAFE(name)), (err, buf) => {
        if (err) { res.statusCode = 404; return res.end("no"); }
        res.setHeader("Content-Type", name.endsWith(".js") ? "text/javascript" : "text/html");
        res.end(buf);
      });
    });
    srv.listen(0, "127.0.0.1", () => resolve({ srv, port: srv.address().port }));
  });
}

const fail = [];
const check = (ok, what) => { console.log((ok ? "  ✓ " : "  ✗ ") + what); if (!ok) fail.push(what); };

(async () => {
  const { srv, port } = await serve();
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1600, height: 900 } });
  const errors = [];
  page.on("pageerror", e => errors.push("JS: " + e.message));

  await page.route("**/api/**", route => {
    const u = route.request().url(), m = route.request().method();
    const json = b => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(b) });
    if (u.includes("/auth/")) return json({ token: "stub" });
    if (u.includes("/meta/")) return json(META);
    if (m !== "GET") { writes.push({ u, m, body: route.request().postData() }); return json([{ Id: 185 }]); }
    if (u.includes("/" + ID("Диспетчеризація") + "/")) return json({ list: DEALS, pageInfo: { isLastPage: true } });
    if (u.includes("/" + ID("Користувачі") + "/")) return json({ list: USERS, pageInfo: { isLastPage: true } });
    return json({ list: [], pageInfo: { isLastPage: true } });
  });

  await page.goto("http://127.0.0.1:" + port + "/index.html");
  await page.evaluate(() => { sessionStorage.setItem("jwt", "stub"); sessionStorage.setItem("email", "me@x.ua"); });
  await page.reload();
  await page.waitForTimeout(400);
  await page.evaluate(() => { if (typeof enter === "function") return enter(); });
  await page.waitForTimeout(1200);
  await page.evaluate(() => { if (typeof go === "function") return go("dispatch"); });
  await page.waitForSelector(".dispscroll tbody tr", { timeout: 8000 });

  console.log("\n— редактор дати в колонці «Доставлено» —");
  const cell = 'td[data-ed="Вивантаження у отримувача (факт)"]';
  await page.click(cell);
  await page.waitForTimeout(300);
  check(!!(await page.$(cell + " .dted")), "відкрився РЕДАКТОР ДАТИ, а не голий текст");
  check(!!(await page.$(cell + " .edpick")), "календарик на місці");
  await page.fill(cell + " .edinput", "31.08");
  await page.press(cell + " .edinput", "Enter");
  await page.waitForTimeout(400);
  const patch = writes.find(w => w.m === "PATCH" && /Вивантаження/.test(w.body || ""));
  check(!!patch, "запис пішов у базу");
  if (patch){
    const b = JSON.parse(patch.body)[0];
    check(b["Вивантаження у отримувача (факт)"] === "2026-08-31",
          "«31.08» збережено як 2026-08-31: " + b["Вивантаження у отримувача (факт)"]);
  }

  console.log("\n— редактор дати в колонці «Gate out» —");
  const gcell = 'td[data-ed="Гейт аут"]';
  await page.click(gcell);
  await page.waitForTimeout(300);
  check(!!(await page.$(gcell + " .dted")), "редактор дати відкрився");
  check(!!(await page.$(gcell + " .edpick")), "календарик на місці");
  await page.press(gcell + " .edinput", "Escape");

  console.log("\n— після F5 відкривається та сама сторінка —");
  await page.reload();
  await page.waitForTimeout(500);
  await page.evaluate(() => { if (typeof enter === "function") return enter(); });
  await page.waitForSelector(".dispscroll tbody tr", { timeout: 8000 })
    .then(() => check(true, "після оновлення знову Диспетчеризація, не Дашборд"))
    .catch(() => check(false, "після оновлення відкрилась не Диспетчеризація"));

  console.log("");
  if (errors.length) { console.log("ПОМИЛКИ В БРАУЗЕРІ:"); errors.forEach(e => console.log("   " + e)); }
  await browser.close(); srv.close();
  const bad = fail.length || errors.length;
  console.log(bad ? "DATEEDIT_FAIL — не пройшло: " + fail.length + ", помилок JS: " + errors.length
                  : "DATEEDIT_OK — дати в Gate out/Доставлено і повернення на сторінку працюють");
  process.exit(bad ? 1 : 0);
})();
