/* Перевірка позначки «застаріло» в таблиці диспетчеризації.
   Що саме перевіряється (усе — рішення користувачки 05.08.2026):
     1. статус «в дорозі», а дата прибуття минула → рядок підсвічений і стоїть
        позначка «застаріло»;
     2. трекінг мовчить («Трекінг (стан)» заповнений) → те саме, навіть якщо
        дата прибуття ще не минула;
     3. свіжа угода в дорозі → НІЧОГО не підсвічується (інакше позначка втратить сенс);
     4. доставлена угода зі старою датою → теж нічого (там нема чому протухати);
     5. сам статус НЕ перезаписується — позначка лише показує розбіжність.

   Запуск: node scripts/stale.js
   Браузер: PW=<шлях до playwright> node scripts/stale.js
*/
const http = require("http");
const path = require("path");
const fs = require("fs");
const { chromium } = require(process.env.PW || "playwright");

const SAFE = n => {
  // дозволяємо лише підтеки всередині www: жодних ".." нагору
  const rel = path.normalize(n).replace(/^(\.\.[/\\])+/, "");
  return rel;
};

/* Шлях приймається аргументом (як у smoke.js) НАВМИСНО: deploy_ui.sh перевіряє
   не той файл, що лежить у репозиторії, а КАНДИДАТА, витягнутого з гілки у
   тимчасову теку. Без аргументу перевірка дивилась би на репозиторій і сказала б
   «усе гаразд» про зовсім інший файл — тобто гірше, ніж не перевіряти взагалі. */
const FILE = process.argv[2] || path.join(__dirname, "..", "www", "index.html");
const DIR = path.dirname(FILE);
const PAGE = path.basename(FILE);
const day = n => new Date(Date.now() - n * 86400000).toISOString().slice(0, 10);

const BASE = {
  "Клієнт": "Тест", "Напрямок": "Імпорт", "Лінія": "Maersk", "Вид перевезення": "фрахт",
  "BL": "123456789", "Контейнер": "MRSU1234567", "Маршрут": "A → B", "Менеджер": "Ірина",
};
/* Кожен рядок — окремий випадок; підписи в назвах, щоб з падіння було зрозуміло, що саме зламалось. */
const ROWS = [
  { ...BASE, Id: 1, "Угода": "256", "Статус": "В морі", "ETA": day(4),
    "Статус (джерело)": "трекінг Maersk", "Статус (оновлено)": day(20) },          // 1: протух
  { ...BASE, Id: 2, "Угода": "257", "Статус": "В морі", "ETA": day(-10),
    "Трекінг (стан)": "Maersk: немає даних з " + day(5) },                          // 2: трекінг мовчить
  { ...BASE, Id: 3, "Угода": "258", "Статус": "В морі", "ETA": day(-10) },          // 3: усе гаразд
  { ...BASE, Id: 4, "Угода": "259", "Статус": "Вантаж доставлено", "ETA": day(30) },// 4: доставлена
  { ...BASE, Id: 5, "Угода": "260", "Статус": "Букінг", "ETA": day(9) },            // 5: не в дорозі — не позначаємо
  /* 6: контейнер чужої лінії. Maersk його не бачить — це НЕ мовчання і не збій,
        позначати не можна (холостий прогін 05.08.2026 знайшов 10 таких угод). */
  { ...BASE, Id: 6, "Угода": "261", "Статус": "В морі", "ETA": day(-10),
    "Трекінг (стан)": "Maersk: інша лінія з " + day(5) },
  /* 7: ті самі умови, що й у випадку 1 (статус «в дорозі», ETA давно минула),
        АЛЕ статус щойно підтвердила людина. Позначки бути не повинно —
        скарга користувачки 13.08.2026: «прибрати статуси застаріло, так як
        оновлення вже було зроблено руками». */
  { ...BASE, Id: 7, "Угода": "262", "Статус": "В морі", "ETA": day(4),
    "Статус (джерело)": "людина", "Статус (оновлено)": day(0) },
  /* 8: людина оновлювала ДАВНО — позначка має повернутись, бо вантаж таки стоїть. */
  { ...BASE, Id: 8, "Угода": "263", "Статус": "В морі", "ETA": day(4),
    "Статус (джерело)": "людина", "Статус (оновлено)": day(9) },
];
const EXPECT = { "256": true, "257": true, "258": false, "259": false, "260": false, "261": false,
                 "262": false, "263": true };

const TABLES = ["Диспетчеризація", "Користувачі", "Клієнти", "Задачі", "Журнал дій",
                "Калькуляції", "Інструкції"];
const META = {
  list: TABLES.map((t, i) => ({ id: "t" + (i + 1), title: t })),
  columns: [{ title: "Статус", uidt: "SingleSelect",
              colOptions: { options: [{ title: "В морі" }, { title: "В порту призначення" }] } }],
};
const SERVICE = { "sync-state": { running: false, ok: true, result: "", error: "", steps: [] } };

const serve = dir => new Promise(res => {
  const srv = http.createServer((rq, rs) => {
    const name = decodeURIComponent(rq.url.split("?")[0]).replace(/^\/+/, "") || "index.html";
    if (SERVICE[name]) { rs.setHeader("Content-Type", "application/json"); return rs.end(JSON.stringify(SERVICE[name])); }
    fs.readFile(path.join(dir, SAFE(name)), (e, b) => {
      if (e) { rs.statusCode = 404; return rs.end("no"); }
      rs.setHeader("Content-Type", name.endsWith(".js") ? "text/javascript" : "text/html");
      rs.end(b);
    });
  });
  srv.listen(0, "127.0.0.1", () => res({ srv, port: srv.address().port }));
});

(async () => {
  const { srv, port } = await serve(DIR);
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  const errors = [];
  page.on("pageerror", e => errors.push("JS: " + e.message));
  const writes = [];
  await page.route("**/api/**", route => {
    const u = route.request().url(), m = route.request().method();
    if (m !== "GET") { writes.push(m + " " + (route.request().postData() || "")); }
    if (u.includes("/auth/")) return route.fulfill({ status: 200, contentType: "application/json", body: '{"token":"stub-jwt"}' });
    if (u.includes("/meta/")) return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(META) });
    if (u.includes("t1")) return route.fulfill({ status: 200, contentType: "application/json",
      body: JSON.stringify({ list: ROWS, pageInfo: { isLastPage: true } }) });
    return route.fulfill({ status: 200, contentType: "application/json",
      body: JSON.stringify({ list: [], pageInfo: { isLastPage: true } }) });
  });
  await page.goto(`http://127.0.0.1:${port}/${PAGE}`);
  await page.evaluate(() => { sessionStorage.setItem("jwt", "stub-jwt"); sessionStorage.setItem("email", "t@e.com"); });
  await page.reload();
  await page.waitForTimeout(400);
  await page.evaluate(() => { if (typeof enter === "function") return enter(); });
  await page.waitForTimeout(600);
  await page.evaluate(() => { if (typeof go === "function") return go("dispatch"); });
  await page.waitForTimeout(1200);

  const seen = await page.evaluate(() => {
    const out = {};
    document.querySelectorAll("#drows tr[data-id]").forEach(tr => {
      const num = tr.cells[0] ? tr.cells[0].textContent.replace(/\D+/g, "") : "";
      out[num] = {
        /* 25.08.2026: позначка тепер не трикутник .stalemark, а пунктир на самій
           плашці статусу (.cnote-line з data-note) — вибір користувачки, варіант 4 */
        позначка: !!tr.querySelector(".cnote-line[data-note], .stalemark"),
        рядок_підсвічено: tr.classList.contains("warnrow"),
        підказка: (tr.getAttribute("title") || "").slice(0, 120),
        статус: (tr.querySelector('[data-ed="Статус"]') || {}).textContent || "",
      };
    });
    return out;
  });

  const bad = [];
  for (const [num, want] of Object.entries(EXPECT)) {
    const got = seen[num];
    if (!got) { bad.push(`угоди ${num} немає в таблиці`); continue; }
    if (got.позначка !== want) bad.push(`угода ${num}: позначка «застаріло» ${got.позначка ? "є, а не мала бути" : "відсутня, а мала бути"}`);
    if (want && !got.рядок_підсвічено) bad.push(`угода ${num}: рядок не підсвічено`);
    if (want && !/застаріл/i.test(got.підказка)) bad.push(`угода ${num}: підказка не пояснює причину («${got.підказка}»)`);
  }
  // статуси не мають переписуватись самим показом таблиці
  const statusWrites = writes.filter(w => w.includes("Статус"));
  if (statusWrites.length) bad.push("показ таблиці записав статус у базу: " + statusWrites[0].slice(0, 120));
  if (errors.length) bad.push(errors[0]);

  console.log("\nЩО ПОБАЧИЛА ПЕРЕВІРКА:");
  for (const [num, g] of Object.entries(seen)) {
    console.log(`  угода ${num}: позначка=${g.позначка ? "так" : "ні"}, підсвічено=${g.рядок_підсвічено ? "так" : "ні"}` +
                (g.підказка ? `\n     підказка: ${g.підказка}` : ""));
  }
  await browser.close(); srv.close();
  if (bad.length) { console.log("\nSTALE_FAIL\n  " + bad.join("\n  ")); process.exit(1); }
  console.log("\nSTALE_OK — позначка «застаріло» стоїть саме там, де має, і статуси не переписуються");
})();
