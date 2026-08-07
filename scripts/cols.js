/* Перевірка ПРАВИЛА ШИРИН КОЛОНОК (сформульоване користувачкою 05.08.2026):
   «колонки мають бути по ширині тексту, ні номери угод, ні номери коносаментів,
   ні статуси не мають ховатися або з'їжджати. Назва клієнта — по ширині, можна
   переносити на наступну строку. Коментар може ховатися». Плюс уточнення того ж
   дня: домашній коносамент ховатися може, лінійний і номер контейнера — ні.

   Навіщо машиною: за один день я двічі зламала саме це — спершу обрізались номери
   коносаментів і статуси, потім «Статус» поїхав за край екрана. Око цього на
   скріні ловило, а код — ні.

   Запуск: node scripts/cols.js [шлях/до/index.html]   (браузер: PW=<шлях до playwright>)

   Шлях приймається аргументом (як у smoke.js) НАВМИСНО: deploy_ui.sh перевіряє
   не той файл, що лежить у репозиторії, а КАНДИДАТА, витягнутого з гілки у
   тимчасову теку. Без аргументу перевірка дивилась би на репозиторій і сказала б
   «усе гаразд» про зовсім інший файл — тобто гірше, ніж не перевіряти взагалі.
*/
const http = require("http");
const path = require("path");
const fs = require("fs");
const { chromium } = require(process.env.PW || "playwright");

const FILE = process.argv[2] || path.join(__dirname, "..", "www", "index.html");
const DIR = path.dirname(FILE);
const PAGE = path.basename(FILE);
const day = n => new Date(Date.now() - n * 86400000).toISOString().slice(0, 10);

const BASE = {
  "Клієнт": "Кампус Коттон Клаб", "Напрямок": "Імпорт", "Лінія": "Maersk",
  "Вид перевезення": "фрахт+ТЕО+залізниця", "Маршрут": "Шанхай → Гданськ → Київ",
  "Менеджер": "Ірина", "Судно": "MAERSK VIRGINIA",
  /* два домашніх коносаменти в один рядок — саме вони роздували колонку */
  "HBL": "BW26060245A, BW26060245B",
  "BL": "271364267", "Контейнер": "CAAU4665092, GAOU7367344",
  "ETA": "2026-08-03", "ETA порт (план)": "2026-08-03", "ETD (план)": "2026-06-13",
  "Gate out for delivery": "2026-08-10", "Гейт ін": "2026-06-07",
  "Коментар": "дуже довгий коментар, який має ховатися і не заважати іншим колонкам",
};
const ROWS = [
  { ...BASE, Id: 1, "Угода": "224", "Статус": "Вивантажений в порту прибуття" },
  { ...BASE, Id: 2, "Угода": "1275", "Статус": "Завантажений на потяг" },
  { ...BASE, Id: 3, "Угода": "256", "Статус": "Прибув у порт" },
];
const TABLES = ["Диспетчеризація", "Користувачі", "Клієнти", "Задачі", "Журнал дій",
                "Калькуляції", "Інструкції"];
const META = {
  list: TABLES.map((t, i) => ({ id: "t" + (i + 1), title: t })),
  columns: [{ title: "Статус", uidt: "SingleSelect",
              colOptions: { options: [{ title: "Прибув у порт" }] } }],
};
const SERVICE = { "sync-state": { running: false, ok: true, result: "", error: "", steps: [] } };

const serve = dir => new Promise(res => {
  const srv = http.createServer((rq, rs) => {
    const name = decodeURIComponent(rq.url.split("?")[0]).replace(/^\/+/, "") || "index.html";
    if (SERVICE[name]) { rs.setHeader("Content-Type", "application/json"); return rs.end(JSON.stringify(SERVICE[name])); }
    fs.readFile(path.join(dir, path.basename(name)), (e, b) => {
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
    const cut = el => el.scrollWidth > el.clientWidth + 1;
    const box = document.getElementById("dscroll");
    const t = box.querySelector("table");
    return {
      /* «Коментар» — єдиний заголовок, якому дозволено ховатися разом зі своєю
         колонкою, тому зі списку порушень його виключаємо. */
      заголовки_обрізані: [...t.tHead.rows[0].cells].filter(cut)
        .map(x => x.textContent.trim()).filter(x => x !== "Коментар"),
      номери_угод_обрізані: [...document.querySelectorAll("#drows td.c-num")].filter(cut).length,
      лінійний_BL_і_контейнери_обрізані:
        [...document.querySelectorAll("#drows td.c-bl .ln:not(.hbl)")].filter(cut).length,
      статуси_обрізані: [...document.querySelectorAll('#drows td[data-ed="Статус"]')].filter(cut).length,
      домашній_коносамент_ховається:
        [...document.querySelectorAll("#drows td.c-bl .ln.hbl")].filter(cut).length,
      ширина_таблиці: Math.round(t.getBoundingClientRect().width),
      ширина_рамки: box.clientWidth,
      статус_за_краєм: (() => {
        const td = document.querySelector('#drows td[data-ed="Статус"]');
        if (!td) return true;
        return td.getBoundingClientRect().right > box.getBoundingClientRect().right + 1;
      })(),
    };
  });

  const bad = [];
  if (seen.заголовки_обрізані.length) bad.push("обрізані заголовки: " + seen.заголовки_обрізані.join(", "));
  if (seen.номери_угод_обрізані) bad.push("обрізані номери угод: " + seen.номери_угод_обрізані);
  if (seen.лінійний_BL_і_контейнери_обрізані) bad.push("обрізані лінійний BL або номери контейнерів: " + seen.лінійний_BL_і_контейнери_обрізані);
  if (seen.статуси_обрізані) bad.push("обрізані статуси: " + seen.статуси_обрізані);
  if (seen.статус_за_краєм) bad.push("колонка «Статус» вийшла за правий край рамки");
  if (!seen.домашній_коносамент_ховається) bad.push("домашній коносамент НЕ ховається, хоча має");
  if (errors.length) bad.push(errors[0]);

  console.log("\nЩО ПОБАЧИЛА ПЕРЕВІРКА:");
  Object.entries(seen).forEach(([k, v]) => console.log("  " + k.replace(/_/g, " ") + ": " + JSON.stringify(v)));
  await browser.close(); srv.close();
  if (bad.length) { console.log("\nCOLS_FAIL\n  " + bad.join("\n  ")); process.exit(1); }
  console.log("\nCOLS_OK — номери, статуси і заголовки видно повністю, ховається лише коментар і домашній коносамент");
})();
