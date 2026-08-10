/* Перевірка: чи ховаються доставлені під шапку ПІСЛЯ вибору менеджера у фільтрі.

   Скарга користувачки 11.08.2026: на основному екрані диспетчеризації доставлені
   сховані під шапкою, а щойно вибрати менеджера — вони знову на весь екран, і
   активних угод не видно, доки не прокрутиш.

   Чому саме так перевіряємо: розрахунок прокрутки в фасаді самоперевірний (три
   спроби добрати запас), тому «прочитати код і подумати» тут не працює — треба
   виміряти, що ФАКТИЧНО видно під шапкою після зміни фільтра.

   Запуск: node scripts/mgrscroll.js [шлях/до/index.html]   (браузер: PW=<шлях>)
*/
const path = require("path");
const fs = require("fs");
const http = require("http");
const { chromium } = require(process.env.PW || "playwright");

const FILE = process.argv[2] || path.join(__dirname, "..", "www", "index.html");
const DIR = path.dirname(FILE);
const PAGE = path.basename(FILE);

const TABLES = ["Диспетчеризація", "Користувачі", "Клієнти", "Задачі",
                "Журнал дій", "Калькуляції", "Інструкції"];
const META = { list: TABLES.map((t, i) => ({ id: "t" + (i + 1), title: t })) };
const DISP_ID = "t1", USERS_ID = "t2";
const ME = { Id: 1, Email: "t@e.com", "Ім'я": "Ірина", "Прізвище": "К",
             "Роль": "Адміністратор", "Активний": true };

const BASE = {
  "Клієнт": "Тест", "Напрямок": "Імпорт", "Лінія": "Maersk", "BL": "123456789",
  "Контейнер": "MRSU1234567", "Вид перевезення": "фрахт", "Маршрут": "A → B",
};
/* Ірина: 12 доставлених + 3 активні. Оксана: 20 доставлених + 20 активних.
   Двоє менеджерів потрібні, щоб фільтр справді щось відсікав. */
const rows = [];
let id = 1;
const add = (man, st, n) => { for (let i = 0; i < n; i++)
  rows.push({ ...BASE, Id: id, "Угода": String(id++), "Менеджер": man,
              "Статус": st, "ETA": "2026-09-01" }); };
add("Оксана", "Вантаж доставлено", 20);
add("Оксана", "В морі", 20);
add("Ірина", "Вантаж доставлено", 12);
add("Ірина", "В морі", 3);

const serve = dir => new Promise(res => {
  const types = { ".html": "text/html", ".js": "application/javascript" };
  const s = http.createServer((rq, rs) => {
    const f = path.join(dir, decodeURIComponent(rq.url.split("?")[0]));
    if (!fs.existsSync(f)) { rs.writeHead(404); return rs.end("no"); }
    rs.writeHead(200, { "Content-Type": types[path.extname(f)] || "text/plain" });
    rs.end(fs.readFileSync(f));
  });
  s.listen(0, "127.0.0.1", () => res([s, s.address().port]));
});

(async () => {
  const [srv, port] = await serve(DIR);
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  let fail = 0;
  const errs = [];
  page.on('pageerror', e => errs.push(String(e).slice(0,160)));

  await page.route("**/api/**", route => {
    const u = route.request().url();
    const json = o => route.fulfill({ status: 200,
      contentType: "application/json", body: JSON.stringify(o) });
    if (u.includes("/meta/bases/")) return json(META);
    if (u.includes("/tables/" + USERS_ID + "/records"))
      return json({ list: [ME], pageInfo: { isLastPage: true } });
    if (u.includes("/tables/" + DISP_ID + "/records"))
      return json({ list: rows, pageInfo: { isLastPage: true } });
    if (u.includes("/meta/tables/"))
      return json({ columns: [{ title: "Статус", uidt: "SingleSelect",
        colOptions: { options: [{ title: "В морі" }, { title: "Вантаж доставлено" }] } }] });
    return json({ list: [], pageInfo: { isLastPage: true } });
  });
  await page.route("**/finrep-data*", r => r.fulfill({ status: 200,
    contentType: "application/json", body: JSON.stringify({ data: {} }) }));

  await page.goto(`http://127.0.0.1:${port}/${PAGE}`);
  await page.evaluate(() => {
    sessionStorage.setItem("jwt", "stub-jwt");
    sessionStorage.setItem("email", "t@e.com");
  });
  await page.evaluate(() => window.enter());
  await page.waitForTimeout(500);
  await page.evaluate(() => window.go("dispatch"));
  await page.waitForTimeout(700);

  /* Що видно ПІД шапкою: беремо перший рядок, чий верх нижчий за низ шапки. */
  const firstUnderHead = () => page.evaluate(() => {
    const box = document.getElementById("dscroll");
    if (!box) return { err: "немає таблиці" };
    /* Шапка «липне» через комірки (thead th{position:sticky}), а не через сам
       thead: елемент thead прокручується разом із таблицею, тому міряти треба
       саме th, інакше «низ шапки» виявиться далеко вгорі за екраном. */
    const th = box.querySelector("thead th");
    const hb = th.getBoundingClientRect().bottom;
    const trs = [...box.querySelectorAll("#drows tr")];
    const vis = trs.find(t => t.getBoundingClientRect().top >= hb - 1);
    const st = vis ? (vis.querySelector("td.c-st") || {}).textContent || "" : "";
    return {
      всього: trs.length,
      доставлених: trs.filter(t => t.classList.contains("done")).length,
      перший: vis ? vis.querySelector("td.c-num").textContent.trim() : "—",
      доставлений: vis ? vis.classList.contains("done") : null,
      прокрутка: Math.round(box.scrollTop),
    };
  });

  const check = (name, got, want) => {
    const ok = got === want;
    if (!ok) fail = 1;
    console.log(`  ${ok ? "✓" : "✗"} ${name}${ok ? "" : `  (отримано ${JSON.stringify(got)}, треба ${JSON.stringify(want)})`}`);
  };

  const a = await firstUnderHead();
  console.log("\n— ОСНОВНИЙ ЕКРАН (без фільтра) —");
  console.log("   рядків: " + a.всього + ", з них доставлених: " + a.доставлених +
              ", прокрутка: " + a.прокрутка + ", перша видима угода: " + a.перший);
  check("під шапкою НЕ доставлена угода", a.доставлений, false);

  errs.length = 0;
  await page.selectOption("#manf", "Ірина");
  await page.waitForTimeout(700);
  const b = await firstUnderHead();
  console.log("\n— ПІСЛЯ ВИБОРУ МЕНЕДЖЕРА «Ірина» —");
  console.log("   рядків: " + b.всього + ", з них доставлених: " + b.доставлених +
              ", прокрутка: " + b.прокрутка + ", перша видима угода: " + b.перший);
  if (errs.length) { console.log("   ПОМИЛКИ ПІД ЧАС ФІЛЬТРУВАННЯ:"); errs.forEach(e=>console.log("      "+e)); }
  const why = await page.evaluate(() => {
    const box = document.getElementById("dscroll");
    const fo = document.querySelector("#drows tr:not(.done)");
    const sp = document.getElementById("dscroll-spacer");
    return { перший_активний: fo ? fo.querySelector("td.c-num").textContent.trim() : null,
             запас_px: sp ? sp.style.height : "немає",
             висота_вмісту: Math.round(box.scrollHeight), висота_рамки: Math.round(box.clientHeight) };
  });
  console.log("   ЧОМУ:", JSON.stringify(why));
  check("під шапкою НЕ доставлена угода", b.доставлений, false);

  await browser.close();
  srv.close();
  console.log("");
  console.log(fail ? "MGRSCROLL_FAIL — після фільтра доставлені лишаються на екрані"
                   : "MGRSCROLL_OK — доставлені сховані під шапкою і з фільтром, і без");
  process.exit(fail);
})();
