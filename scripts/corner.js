/* Перевірка того, що просила користувачка 13.08.2026 для таблиці диспетчеризації:
     1) угорі є ДАТА Й ЧАС оновлення даних («немає дати та часу оновлення зверху»);
     2) підписи «застаріло» і «було 02.08.26» більше НЕ друкуються в клітинці;
     3) замість них — помаранчевий куточок, клік по якому відкриває коментар
        («ховати в коментарі, які відкриваються, якщо натиснути на куточок,
        як в екселі»), і Escape його закриває;
     4) якщо статус щойно підтвердила ЛЮДИНА — позначки «застаріло» немає зовсім
        («оновлення вже було зроблено руками»).

   ⚠️ `day(n)` тут означає n днів У МАЙБУТНЄ (у scripts/stale.js навпаки — у
   минуле). Я на цьому спіткнулась при написанні: «немає даних з day(5)» давало
   майбутню дату, трекінг рахувався несвіжим на −5 днів, і куточок не з'являвся.
   Якщо правитимеш дати — звіряй знак.

   Запуск: node scripts/corner.js www/index.html */
const path = require("path");
const fs = require("fs");
const http = require("http");
const { chromium } = require(process.env.PW || "playwright");
const SAFE = n => path.normalize(n).replace(/^(\.\.[/\\])+/, "");
const FILE = process.argv[2];
const WWW = path.dirname(FILE);

const day = d => { const x = new Date(); x.setDate(x.getDate() + d); return x.toISOString().slice(0, 10); };
const BASE = { "Клієнт": "ГРАНД МАРИН", "Напрямок": "Імпорт", "Лінія": "Maersk",
  "Вид перевезення": "фрахт", "BL": "274014640", "Контейнер": "MRSU9195960",
  "Маршрут": "Солоницівка → Гданськ", "Менеджер": "Ірина", "Судно": "MAERSK VIRGINIA" };
const ROWS = [
  { ...BASE, Id: 1, "Угода": "251", "Статус": "В морі", "ETA": day(4),
    "Статус (джерело)": "трекінг Maersk", "Статус (оновлено)": day(20),
    "Зміни ETA (історія)": day(-3) + ": ETA порт: " + day(-40) + " → " + day(4) + " (Maersk)",
    "Трекінг (стан)": "Maersk: немає даних з " + day(-5),
    "UpdatedAt": "2026-08-13 17:44:12+00:00" },
  { ...BASE, Id: 2, "Угода": "224", "Статус": "Завантажений на потяг", "ETA": day(-9),
    "Статус (джерело)": "людина", "Статус (оновлено)": day(0),
    "UpdatedAt": "2026-08-13 18:02:00+00:00" },
];
const TABLES = ["Диспетчеризація", "Користувачі", "Клієнти", "Задачі", "Журнал дій", "Калькуляції", "Інструкції"];
const META = { list: TABLES.map((t, i) => ({ id: "t" + (i + 1), title: t })),
  columns: [{ title: "Статус", uidt: "SingleSelect", colOptions: { options: [{ title: "В морі" }] } }] };

const fail = [];
const check = (ok, what) => { console.log((ok ? "  ✓ " : "  ✗ ") + what); if (!ok) fail.push(what); };

(async () => {
  const srv = http.createServer((req, res) => {
    const name = decodeURIComponent(req.url.split("?")[0]).replace(/^\/+/, "") || "index.html";
    if (["sync-state", "sync"].includes(name)) { res.setHeader("Content-Type", "application/json"); return res.end("{}"); }
    fs.readFile(path.join(WWW, SAFE(name)), (e, b) => {
      if (e) { res.statusCode = 404; return res.end("no"); }
      res.setHeader("Content-Type", name.endsWith(".js") ? "text/javascript" : "text/html"); res.end(b);
    });
  });
  await new Promise(r => srv.listen(0, "127.0.0.1", r));
  const port = srv.address().port;
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1500, height: 800 } });
  const errors = [];
  page.on("pageerror", e => errors.push("JS: " + e.message));
  await page.route("**/api/**", route => {
    const u = route.request().url();
    const json = b => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(b) });
    if (u.includes("/auth/")) return json({ token: "stub" });
    if (u.includes("/meta/")) return json(META);
    if (u.includes("/t1/")) return json({ list: ROWS, pageInfo: { isLastPage: true } });
    if (u.includes("/t2/")) return json({ list: [{ Id: 1, Email: "me@x.ua", "Ім'я": "Ірина", "Роль": "Адміністратор", "Активний": true }], pageInfo: { isLastPage: true } });
    return json({ list: [], pageInfo: { isLastPage: true } });
  });
  await page.goto("http://127.0.0.1:" + port + "/index.html");
  await page.evaluate(() => { sessionStorage.setItem("jwt", "s"); sessionStorage.setItem("email", "me@x.ua"); });
  await page.reload(); await page.waitForTimeout(400);
  await page.evaluate(() => { if (typeof enter === "function") return enter(); });
  await page.waitForTimeout(1200);
  await page.evaluate(() => { if (typeof go === "function") return go("dispatch"); });
  await page.waitForSelector(".dispscroll tbody tr", { timeout: 8000 });
  await page.waitForTimeout(600);

  const stamp = await page.textContent("#page-actions .updstamp").catch(() => "");
  console.log("\nпозначка вгорі: «" + stamp.trim() + "»");
  check(/оновлено \d{2}\.\d{2} \d{2}:\d{2}/.test(stamp), "угорі є дата й час оновлення");

  const body = await page.textContent(".dispscroll");
  check(!/застаріло/.test(body), "слова «застаріло» в таблиці більше немає");
  check(!/було \d/.test(body), "підпису «було …» в клітинці більше немає");

  const corners = await page.$$(".dispscroll .cnote");
  console.log("куточків у таблиці: " + corners.length);
  check(corners.length >= 2, "куточки з'явились (зміна ETA + трекінг мовчить)");

  const rows224 = await page.$$eval(".dispscroll tbody tr", trs => trs.map(t => ({
    num: (t.querySelector("td") || {}).textContent || "",
    marks: t.querySelectorAll(".stalemark").length })));
  const r224 = rows224.find(r => /224/.test(r.num));
  check(!!r224 && r224.marks === 0, "угода 224 (людина щойно оновила) — позначки немає");

  /* Знімок — ЛИШЕ на прохання: SHOT=/шлях/знімок.png node scripts/corner.js …
     Було `__dirname` — тобто файл падав просто в scripts/ і потрапляв у репозиторій.
     Та сама помилка вже траплялась 13.08.2026 з findash.js; тут я її повторила. */
  const SHOT = process.env.SHOT;
  if (SHOT) await page.screenshot({ path: SHOT.replace(/\.png$/, "") + "-1.png", clip: { x: 280, y: 60, width: 1220, height: 330 } });
  await corners[0].click();
  await page.waitForTimeout(300);
  const vis = await page.isVisible("#notepop");
  const txt = await page.textContent("#notepop");
  console.log("текст у віконці: «" + txt.trim().slice(0, 90) + "»");
  check(vis, "клік по куточку відкрив коментар");
  check(txt.trim().length > 5, "у коментарі є текст");
  if (SHOT) await page.screenshot({ path: SHOT.replace(/\.png$/, "") + "-2.png", clip: { x: 280, y: 60, width: 1220, height: 330 } });

  await page.keyboard.press("Escape");
  await page.waitForTimeout(200);
  check(!(await page.isVisible("#notepop")), "Escape закриває коментар");

  if (errors.length) { console.log("\nПОМИЛКИ:"); errors.forEach(e => console.log("   " + e)); }
  await browser.close(); srv.close();
  const bad = fail.length || errors.length;
  console.log(bad ? "\nCORNER_FAIL — не пройшло: " + fail.length : "\nCORNER_OK");
  process.exit(bad ? 1 : 0);
})();
