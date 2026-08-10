/* Перевірка: чи зникає смуга «Не вдалося визначити твою роль» після успішного входу.

   Що саме відтворюємо (скарга користувачки 11.08.2026, вдруге): у значку вгорі
   стоїть АДМІНІСТРАТОР, дані на дашборді завантажені, а внизу висить смуга
   «Тимчасово ввімкнено тільки перегляд». Тобто попередження ЗАСТАРІЛЕ: воно
   лишилося від попередньої невдалої спроби, бо sysWarn() прибирається ТІЛЬКИ
   власним ✕ і переживає успішний повторний вхід.

   Хід перевірки:
     1) перший вхід ламаємо (довідник «Користувачі» віддає 500) — смуга МАЄ бути,
        роль МАЄ впасти до «Перегляд». Це доводить, що ми відтворили саме той стан;
     2) другий вхід проходить нормально — смуги бути НЕ МАЄ, роль АДМІНІСТРАТОР.

   Пункт 2 на версії до виправлення падає — саме це користувачка й бачила.

   Запуск: node scripts/syswarn.js [шлях/до/index.html]   (браузер: PW=<шлях>)
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
const USERS_ID = "t" + (TABLES.indexOf("Користувачі") + 1);
const ME = {
  Id: 1, Email: "test@example.com", "Ім'я": "Ірина", "Прізвище": "Кармазіна",
  "Роль": "Адміністратор", "Активний": true,
};

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
  const page = await browser.newPage();
  let breakUsers = true;           // перший вхід ламаємо навмисно
  let fail = 0;

  await page.route("**/api/**", route => {
    const u = route.request().url();
    const json = (o, status = 200) => route.fulfill({ status,
      contentType: "application/json", body: JSON.stringify(o) });
    if (u.includes("/meta/bases/")) return json(META);
    if (u.includes("/tables/" + USERS_ID + "/records")) {
      if (breakUsers) return json({ msg: "база перезапускається" }, 500);
      return json({ list: [ME], pageInfo: { isLastPage: true } });
    }
    if (u.includes("/records")) return json({ list: [], pageInfo: { isLastPage: true } });
    return json({});
  });
  await page.route("**/finrep-data*", r => r.fulfill({ status: 200,
    contentType: "application/json", body: JSON.stringify({ data: {} }) }));

  await page.goto(`http://127.0.0.1:${port}/${PAGE}`);
  await page.evaluate(() => {
    sessionStorage.setItem("jwt", "stub-jwt");
    sessionStorage.setItem("email", "test@example.com");
  });

  const look = () => page.evaluate(() => {
    const w = document.getElementById("syswarn");
    return {
      warn: !!w && getComputedStyle(w).display !== "none",
      text: (w && w.textContent || "").slice(0, 60),
      role: (document.getElementById("u-role") || {}).textContent || "",
    };
  });

  const check = (name, got, want) => {
    const ok = got === want;
    if (!ok) fail = 1;
    console.log(`  ${ok ? "✓" : "✗"} ${name}${ok ? "" : `  (отримано ${JSON.stringify(got)}, треба ${JSON.stringify(want)})`}`);
  };

  await page.evaluate(() => window.enter());
  await page.waitForTimeout(400);
  const a = await look();
  console.log("\n— 1. ВХІД ЗІ ЗБОЄМ (відтворюємо те, що бачила користувачка) —");
  check("смуга з'явилась", a.warn, true);
  check("роль впала до «Перегляд»", a.role, "Перегляд");

  breakUsers = false;                        // зв'язок відновився
  await page.evaluate(() => window.enter());
  await page.waitForTimeout(400);
  const b = await look();
  console.log("\n— 2. ПОВТОРНИЙ ВХІД, УСЕ ПРАЦЮЄ —");
  check("роль визначилась", b.role, "Адміністратор");
  check("смуга ЗНИКЛА", b.warn, false);
  if (b.warn) console.log("      висить: " + b.text);

  await browser.close();
  srv.close();
  console.log("");
  console.log(fail ? "SYSWARN_FAIL — смуга бреше: роль визначена, а попередження висить"
                   : "SYSWARN_OK — смуга з'являється при збої і зникає після успішного входу");
  process.exit(fail);
})();
