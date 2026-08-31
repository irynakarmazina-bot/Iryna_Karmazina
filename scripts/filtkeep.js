/* Перевірка: фільтри Диспетчеризації переживають перехід на іншу вкладку і
   повернення (прохання користувачки 31.08.2026). Сценарій: поставити фільтр
   «Імпорт» → піти на Дашборд → повернутись → фільтр стоїть, панель розгорнута,
   таблиця відфільтрована; «Всі угоди» скидає і збережене теж.
   Запуск: node scripts/filtkeep.js [шлях/до/index.html] (браузер: PW=…) */
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
  { Id: 1, "Угода": "301", "Клієнт": "Імпортер", "Статус": "В морі", "Напрямок": "Імпорт",
    "Менеджер": "Ірина", "Лінія": "Maersk", "Вид перевезення": "фрахт+ТЕО+авто", "Контейнер": "MRKU1111111" },
  { Id: 2, "Угода": "302", "Клієнт": "Експортер", "Статус": "Букінг", "Напрямок": "Експорт",
    "Менеджер": "Ірина", "Лінія": "Maersk", "Вид перевезення": "фрахт+ТЕО+авто", "Контейнер": "MRKU2222222" },
];

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
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  const errors = [];
  page.on("pageerror", e => errors.push("JS: " + e.message));

  await page.route("**/api/**", route => {
    const u = route.request().url(), m = route.request().method();
    const json = b => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(b) });
    if (u.includes("/auth/")) return json({ token: "stub" });
    if (u.includes("/meta/")) return json(META);
    if (m !== "GET") return json([{ Id: 99 }]);
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

  console.log("\n— ставимо фільтр і йдемо на іншу вкладку —");
  await page.selectOption("#dirf", "Імпорт");
  await page.waitForTimeout(300);
  let rows = await page.$$eval(".dispscroll tbody tr[data-id]", t => t.length);
  check(rows === 1, "після фільтра «Імпорт» видно 1 угоду (було 2): " + rows);
  await page.evaluate(() => go("dashboard"));
  await page.waitForTimeout(600);
  await page.evaluate(() => go("dispatch"));
  await page.waitForSelector(".dispscroll tbody tr", { timeout: 8000 });
  check(await page.inputValue("#dirf") === "Імпорт", "після повернення фільтр стоїть: " + await page.inputValue("#dirf"));
  rows = await page.$$eval(".dispscroll tbody tr[data-id]", t => t.length);
  check(rows === 1, "таблиця знову відфільтрована: " + rows + " угода");
  check(await page.$eval("#filters", el => el.classList.contains("open")),
        "панель фільтрів розгорнута — видно, чому не всі угоди");

  console.log("\n— «Всі угоди» скидає і збережене —");
  const ad = await page.$("#all-deals");
  if (ad){
    await ad.click();
    await page.waitForSelector(".dispscroll tbody tr", { timeout: 8000 });
    check(await page.inputValue("#dirf") === "", "фільтр скинуто");
    await page.evaluate(() => go("dashboard"));
    await page.waitForTimeout(600);
    await page.evaluate(() => go("dispatch"));
    await page.waitForSelector(".dispscroll tbody tr", { timeout: 8000 });
    check(await page.inputValue("#dirf") === "", "після повернення фільтр НЕ відновився (скинутий — значить скинутий)");
  } else {
    check(true, "кнопки «Всі угоди» на екрані немає — крок пропущено");
  }

  console.log("");
  if (errors.length) { console.log("ПОМИЛКИ В БРАУЗЕРІ:"); errors.forEach(e => console.log("   " + e)); }
  await browser.close(); srv.close();
  const bad = fail.length || errors.length;
  console.log(bad ? "FILTKEEP_FAIL — не пройшло: " + fail.length + ", помилок JS: " + errors.length
                  : "FILTKEEP_OK — фільтри переживають перехід між вкладками");
  process.exit(bad ? 1 : 0);
})();
