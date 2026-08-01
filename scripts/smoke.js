/* Димова перевірка фасада: справжній браузер відкриває www/index.html, входить
   як адміністратор і КЛІКАЄ КОЖЕН пункт меню. Падає, якщо будь-яка сторінка
   кинула помилку JS або показала банер «Не вдалося завантажити дані».

   Навіщо: 01.08.2026 три рядки з «Налаштувань» випадково опинились у «Фінансах»
   (`isAdmin`/`rows` там не існують) — сторінка «Фінанси» падала, а помітила це
   користувачка, не я. `node --check` такого не ловить: синтаксис коректний,
   помилка виникає лише під час виконання. Тому — реальний браузер.

   Запуск: node scripts/smoke.js [шлях/до/index.html]
   Мережі не потребує: усі запити до /api перехоплюються і віддають заглушки.
*/
const path = require("path");
const { chromium } = require(process.env.PW || "playwright");

const FILE = process.argv[2] || path.join(__dirname, "..", "www", "index.html");

// мінімальні заглушки під NocoDB, щоб сторінки мали з чим працювати
const ROW = {
  Id: 1, "Угода": "1", "Клієнт": "Тест", "Напрямок": "Імпорт", "Лінія": "Maersk",
  "Статус": "В морі", "BL": "123456789", "Контейнер": "MRSU1234567",
  "ETA": "2026-09-01", "Вид перевезення": "фрахт", "Маршрут": "A → B",
  "Менеджер": "Ірина", "Роль": "Адміністратор", "Активний": true,
  "Email": "test@example.com", "Ім'я": "Ірина", "Прізвище": "Тест",
};

(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage();
  const errors = [];
  page.on("pageerror", e => errors.push("JS: " + e.message));
  page.on("console", m => { if (m.type() === "error") errors.push("console: " + m.text()); });

  await page.route("**/api/**", route => {
    const u = route.request().url();
    if (u.includes("/auth/")) {
      return route.fulfill({ status: 200, contentType: "application/json",
        body: JSON.stringify({ token: "stub-jwt" }) });
    }
    if (u.includes("/meta/")) {
      return route.fulfill({ status: 200, contentType: "application/json",
        body: JSON.stringify({ columns: [{ title: "Статус", uidt: "SingleSelect",
          colOptions: { options: [{ title: "В морі" }] } }] }) });
    }
    return route.fulfill({ status: 200, contentType: "application/json",
      body: JSON.stringify({ list: [ROW], pageInfo: { isLastPage: true } }) });
  });
  await page.route("**/finrep-data*", r => r.fulfill({ status: 200,
    contentType: "application/json", body: JSON.stringify({ rows: [] }) }));

  await page.goto("file://" + path.resolve(FILE));
  await page.evaluate(() => {
    localStorage.setItem("jwt", "stub-jwt");
    localStorage.setItem("role", "Адміністратор");
    localStorage.setItem("me", JSON.stringify({ email: "test@example.com",
      "Ім'я": "Ірина", "Роль": "Адміністратор" }));
  });
  await page.reload();
  await page.waitForTimeout(1200);

  const items = await page.$$eval("nav a, .nav a, [data-page]",
    els => els.map(e => (e.dataset.page || e.getAttribute("href") || "").replace(/^#/, ""))
              .filter(Boolean));
  const pages = [...new Set(items)];
  if (!pages.length) {
    console.log("SMOKE_FAIL: не знайшла жодного пункту меню — перевірка нічого не перевірила");
    await browser.close();
    process.exit(1);
  }

  const bad = [];
  for (const p of pages) {
    const before = errors.length;
    await page.evaluate(pg => { location.hash = "#" + pg; }, p);
    await page.waitForTimeout(700);
    const banner = await page.evaluate(() =>
      (document.body.innerText.match(/Не вдалося завантажити дані[^\n]*/) || [""])[0]);
    const fresh = errors.slice(before);
    if (fresh.length || banner) bad.push(`  ✗ ${p}: ${banner || fresh[0]}`);
    else console.log(`  ✓ ${p}`);
  }
  await browser.close();
  if (bad.length) { console.log("SMOKE_FAIL\n" + bad.join("\n")); process.exit(1); }
  console.log("SMOKE_OK — перевірено сторінок: " + pages.length);
})().catch(e => { console.log("SMOKE_ERROR " + e.message); process.exit(1); });
