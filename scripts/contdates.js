/* Перевірка блока «📦 Дати по контейнерах» у картці угоди (31.08.2026).
   Вимога користувачки: для угод із 2+ контейнерами — окремі дати прибуття
   і доставки на кожний контейнер. Сценарій: відкрити картку угоди з двома
   контейнерами → блок є → внести дати → зберегти → у базу пішов JSON у
   колонку «Контейнери (дати)». Для угоди з ОДНИМ контейнером блока немає.
   Запуск: node scripts/contdates.js [шлях/до/index.html] (браузер: PW=…) */
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
  { Id: 7, "Угода": "224", "Клієнт": "Кампус", "Статус": "Завантажений на потяг", "Напрямок": "Імпорт",
    "Менеджер": "Ірина", "Лінія": "Maersk", "Вид перевезення": "фрахт+ТЕО+залізниця",
    "Контейнер": "CAAU4665092, GAOU7367344",
    "Контейнери (дати)": JSON.stringify({ CAAU4665092: { "прибуття": "2026-08-11", "доставка": "" } }) },
  { Id: 8, "Угода": "225", "Клієнт": "Соло", "Статус": "В морі", "Напрямок": "Імпорт",
    "Менеджер": "Ірина", "Лінія": "Maersk", "Вид перевезення": "фрахт+ТЕО+авто",
    "Контейнер": "MRSU5082306" },
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
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  const errors = [];
  page.on("pageerror", e => errors.push("JS: " + e.message));

  await page.route("**/api/**", route => {
    const u = route.request().url(), m = route.request().method();
    const json = b => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(b) });
    if (u.includes("/auth/")) return json({ token: "stub" });
    if (u.includes("/meta/")) return json(META);
    if (m !== "GET") { writes.push({ u, m, body: route.request().postData() }); return json([{ Id: 99 }]); }
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

  console.log("\n— угода з ДВОМА контейнерами —");
  await page.click('.dispscroll tbody tr:has-text("Кампус") td:nth-child(3)');
  await page.waitForSelector("#row-overlay.open", { timeout: 5000 });
  check(await page.isVisible("#row-conts"), "блок «Дати по контейнерах» є в картці");
  check((await page.textContent("#row-conts")).includes("CAAU4665092")
     && (await page.textContent("#row-conts")).includes("GAOU7367344"), "обидва контейнери в списку");
  check(await page.inputValue("#cd-arr-0") === "11.08.26",
        "збережена дата прибуття показана в людському форматі: " + await page.inputValue("#cd-arr-0"));
  await page.fill("#cd-del-0", "28.08.26");
  await page.fill("#cd-arr-1", "12.08.26");
  await page.click("#cd-save");
  await page.waitForTimeout(500);
  const patch = writes.find(w => w.m === "PATCH" && w.u.includes(ID("Диспетчеризація"))
                                && /Контейнери/.test(w.body || ""));
  check(!!patch, "пішов запис у колонку «Контейнери (дати)»");
  if (patch){
    const b = JSON.parse(patch.body)[0];
    let js = {};
    try { js = JSON.parse(b["Контейнери (дати)"]); } catch (e) { js = {}; }
    check((js.CAAU4665092 || {})["прибуття"] === "2026-08-11"
       && (js.CAAU4665092 || {})["доставка"] === "2026-08-28", "дати першого контейнера у форматі бази");
    check((js.GAOU7367344 || {})["прибуття"] === "2026-08-12", "дата другого контейнера збереглась");
  }
  check(/збережено/.test(await page.textContent("#cd-msg")), "людині показано «збережено»");
  await page.click("#row-close");

  console.log("\n— угода з ОДНИМ контейнером —");
  await page.waitForTimeout(300);
  await page.click('.dispscroll tbody tr:has-text("Соло") td:nth-child(3)');
  await page.waitForSelector("#row-overlay.open", { timeout: 5000 });
  check(!(await page.isVisible("#row-conts")), "блока немає — для одного контейнера він зайвий");

  console.log("");
  if (errors.length) { console.log("ПОМИЛКИ В БРАУЗЕРІ:"); errors.forEach(e => console.log("   " + e)); }
  await browser.close(); srv.close();
  const bad = fail.length || errors.length;
  console.log(bad ? "CONTDATES_FAIL — не пройшло: " + fail.length + ", помилок JS: " + errors.length
                  : "CONTDATES_OK — дати по контейнерах працюють");
  process.exit(bad ? 1 : 0);
})();
