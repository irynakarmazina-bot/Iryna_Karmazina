/* Перевірка розділу «Задачі» в справжньому браузері: списки й групи, нагадування,
   лічильник у меню, картка задачі, створення, закриття, блок у картці угоди й
   колонка в клієнтах.

   НАВІЩО ОКРЕМА ПЕРЕВІРКА. smoke.js лише ВІДКРИВАЄ кожну сторінку і дивиться,
   чи вона не впала. Він не натискає кнопок, тому нічого з переліченого вище не
   бачить: форма могла б не відкриватись, виконавці — не зберігатись, лічильник
   рахувати не те, а smoke.js однаково казав би SMOKE_OK. Саме через таку
   прогалину («перевірка існувала, але до дверей під'єднана не була») у серпні
   двічі доїжджали до користувачки поломки, які ловляться автоматом.

   Дані підставні, мережі не треба: усі запити до /api перехоплюються, а записи
   (POST/PATCH) не йдуть нікуди — вони перехоплюються й перевіряються.

   Запуск: node scripts/tasks.js [шлях/до/index.html]
   Браузер: якщо playwright не в node_modules проєкту — вказати шлях у PW,
   напр. PW=/opt/node22/lib/node_modules/playwright node scripts/tasks.js */
const path = require("path");
const fs = require("fs");
const http = require("http");
const { chromium } = require(process.env.PW || "playwright");

const SAFE = n => {
  // дозволяємо лише підтеки всередині www: жодних ".." нагору
  const rel = path.normalize(n).replace(/^(\.\.[/\\])+/, "");
  return rel;
};

const FILE = process.argv[2] || path.join(__dirname, "..", "www", "index.html");
const WWW = path.dirname(FILE);
const TABLES = ["Диспетчеризація", "Користувачі", "Клієнти", "Задачі",
                "Журнал дій", "Калькуляції", "Інструкції"];
const META = { list: TABLES.map((title, i) => ({ id: "t" + (i + 1), title })), columns: [] };
const ID = n => "t" + (TABLES.indexOf(n) + 1);

const day = d => { const x = new Date(); x.setDate(x.getDate() + d); return x.toISOString().slice(0, 10); };
const USERS = [
  { Id: 1, Email: "me@x.ua", "Ім'я": "Ірина", "Прізвище": "Кармазіна", "Роль": "Адміністратор", "Активний": true },
  { Id: 2, Email: "v@x.ua", "Ім'я": "Віталій", "Прізвище": "Понтус", "Роль": "Адміністратор", "Активний": true },
  { Id: 3, Email: "g@x.ua", "Ім'я": "Ірина", "Прізвище": "Голобородько", "Роль": "Фінансист", "Активний": true },
];
const TASKS = [
  { Id: 1, "Задача": "прострочена моя", "Тип": "Угода", "Угода": "259", "Виконавці": "me@x.ua",
    "Термін": day(-3), "Статус": "Нова", "Пріоритет": "Терміново", "Нагадати за": 1, "Постановник": "v@x.ua" },
  { Id: 2, "Задача": "сьогодні моя", "Тип": "Клієнт", "Клієнт": "Тест ТОВ", "Виконавці": "me@x.ua, v@x.ua",
    "Термін": day(0), "Статус": "В роботі", "Пріоритет": "Звичайно", "Нагадати за": 0, "Постановник": "me@x.ua" },
  { Id: 3, "Задача": "через 2 дні, нагадати за 3", "Тип": "Співробітник", "Співробітник": "Віталій Понтус",
    "Виконавці": "me@x.ua", "Термін": day(2), "Статус": "Нова", "Нагадати за": 3, "Постановник": "me@x.ua" },
  { Id: 4, "Задача": "чужа задача", "Тип": "Дія", "Виконавці": "v@x.ua", "Термін": day(-1),
    "Статус": "Нова", "Постановник": "v@x.ua" },
  { Id: 5, "Задача": "без терміну", "Тип": "Дія", "Виконавці": "me@x.ua", "Статус": "Нова", "Постановник": "me@x.ua" },
  { Id: 6, "Задача": "вже закрита", "Тип": "Дія", "Виконавці": "me@x.ua", "Термін": day(-9),
    "Статус": "Виконано", "Виконано": day(-8), "Постановник": "me@x.ua" },
  // виконавець — фінансистка: на ній перевіряється відбір за роллю і те,
  // що не-адмін чужого не бачить
  { Id: 7, "Задача": "задача фінансистки", "Тип": "Дія", "Виконавці": "g@x.ua",
    "Термін": day(1), "Статус": "Нова", "Постановник": "v@x.ua" },
];
const DEALS = [{ Id: 1, "Угода": "259", "Клієнт": "Тест ТОВ", "Статус": "В морі", "ETA": day(20),
                 "Менеджер": "Ірина", "Напрямок": "Імпорт", "Лінія": "Maersk", "Вид перевезення": "фрахт" }];
const CLIENTS = [{ Id: 1, "Назва": "Тест ТОВ" }];

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
  page.on("console", m => { if (m.type() === "error" && !/Failed to load resource/.test(m.text())) errors.push("console: " + m.text()); });

  await page.route("**/api/**", route => {
    const u = route.request().url(), m = route.request().method();
    const json = b => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(b) });
    if (u.includes("/auth/")) return json({ token: "stub" });
    if (u.includes("/meta/")) return json(META);
    if (m !== "GET") { writes.push({ u, m, body: route.request().postData() }); return json([{ Id: 99 }]); }
    if (u.includes("/" + ID("Задачі") + "/")) return json({ list: TASKS, pageInfo: { isLastPage: true } });
    if (u.includes("/" + ID("Користувачі") + "/")) return json({ list: USERS, pageInfo: { isLastPage: true } });
    if (u.includes("/" + ID("Диспетчеризація") + "/")) return json({ list: DEALS, pageInfo: { isLastPage: true } });
    if (u.includes("/" + ID("Клієнти") + "/")) return json({ list: CLIENTS, pageInfo: { isLastPage: true } });
    return json({ list: [], pageInfo: { isLastPage: true } });
  });

  await page.goto("http://127.0.0.1:" + port + "/index.html");
  await page.evaluate(() => { sessionStorage.setItem("jwt", "stub"); sessionStorage.setItem("email", "me@x.ua"); });
  await page.reload();
  await page.waitForTimeout(400);
  await page.evaluate(() => { if (typeof enter === "function") return enter(); });
  await page.waitForTimeout(1500);
  await page.waitForSelector(".nav-item", { timeout: 8000 });

  console.log("\n— лічильник у меню —");
  await page.waitForTimeout(600);
  const badge = await page.textContent("#nav-tasks-badge").catch(() => null);
  // дзвонять: №1 (прострочена), №2 (сьогодні), №3 (через 2 дні, нагадати за 3) = 3
  check(badge === "3", "лічильник показує 3 (прострочена + сьогодні + та, що нагадує), а не " + badge);

  console.log("\n— сторінка «Задачі» —");
  await page.click('.nav-item[data-page="tasks"]');
  await page.waitForSelector(".taskrow", { timeout: 8000 });
  const text = await page.textContent("#content");
  check(/Прострочені/.test(text) && /прострочено 3 дні/.test(text), "блок «Прострочені» і підпис «прострочено 3 дні»");
  check(/На сьогодні/.test(text), "блок «На сьогодні»");
  check(/Без терміну/.test(text), "блок «Без терміну»");
  check(!/чужа задача/.test(text), "чужа задача у фільтрі «Мої» не показується");
  check(/угода №259/.test(text), "об'єкт задачі — «угода №259»");
  check(/Клієнт: Тест ТОВ/.test(text), "об'єкт задачі — клієнт");
  check(/Співробітник: Віталій Понтус/.test(text), "об'єкт задачі — співробітник");
  check(/Ірина Кармазіна/.test(text), "виконавець показаний ім'ям, а не поштою");
  check(!/вже закрита/.test(text), "закриті сховані, доки не натиснути «Показати закриті»");

  console.log("\n— фільтри —");
  await page.click('.doerchip[data-f="who"][data-v="all"]');
  await page.waitForTimeout(400);
  check(/чужа задача/.test(await page.textContent("#content")), "фільтр «Усі» показує чужу задачу");
  await page.click('.doerchip[data-f="closed"]');
  await page.waitForTimeout(400);
  check(/вже закрита/.test(await page.textContent("#content")), "кнопка «Показати закриті» показує закриту");
  await page.click('.doerchip[data-f="kind"][data-v="Дія"]');
  await page.waitForTimeout(400);
  const only = await page.textContent("#content");
  check(!/угода №259/.test(only), "фільтр по типу «Дія» ховає задачі по угодах");
  await page.click('.doerchip[data-f="kind"][data-v=""]');
  await page.waitForTimeout(400);

  /* «Адмін бачить всі задачі, інші ролі — тільки свої; адмін може обрати які
     ролі бачити» — рішення користувачки 12.08.2026. */
  console.log("\n— відбір за роллю (тільки адміністратор) —");
  check(await page.isVisible('.doerchip[data-f="role"][data-v=""]'), "адміністратору видно відбір за роллю");
  check(/задача фінансистки/.test(await page.textContent("#content")), "у фільтрі «Усі» адмін бачить чужу задачу фінансистки");
  await page.click('.doerchip[data-f="role"][data-v="Фінансист"]');
  await page.waitForTimeout(400);
  const byRole = await page.textContent("#content");
  check(/задача фінансистки/.test(byRole), "відбір «Фінансист» лишає задачу фінансистки");
  check(!/прострочена моя/.test(byRole), "відбір «Фінансист» ховає задачі адміністраторів");
  await page.click('.doerchip[data-f="role"][data-v="Фінансист"]');   // зняти
  await page.waitForTimeout(400);
  await page.click('.doerchip[data-f="who"][data-v="mine"]');
  await page.waitForTimeout(400);
  await page.click('.doerchip[data-f="closed"]');                     // сховати закриті назад
  await page.waitForTimeout(400);

  console.log("\n— картка задачі: створення —");
  await page.click("#task-new");
  await page.waitForSelector("#task-overlay.open", { timeout: 5000 });
  check(await page.isVisible("#tk-name"), "форма відкрилась");
  await page.fill("#tk-name", "перевірка створення");
  await page.selectOption("#tk-kind", "Угода");
  await page.waitForTimeout(300);
  check(await page.isVisible("#tk-obj"), "для типу «Угода» з'явилось поле номера");
  await page.click("#task-save");
  await page.waitForTimeout(300);
  check(/Вкажи, до чого задача/.test(await page.textContent("#task-msg")), "без номера угоди не зберігає і каже чому");
  await page.fill("#tk-obj", "259");
  await page.click('#tk-doers [data-em="v@x.ua"]');
  await page.fill("#tk-due", day(5));
  await page.click("#task-save");
  await page.waitForTimeout(600);
  const post = writes.find(w => w.m === "POST" && /перевірка створення/.test(w.body || ""));
  check(!!post, "пішов POST у таблицю задач");
  if (post) {
    const b = JSON.parse(post.body)[0];
    check(b["Тип"] === "Угода" && b["Угода"] === "259", "у запис пішли тип і номер угоди");
    check(b["Виконавці"] === "me@x.ua, v@x.ua", "двоє виконавців через кому, а не один: " + b["Виконавці"]);
    check(b["Постановник"] === "me@x.ua", "постановник — той, хто створив");
    check(b["Виконано"] === null, "у нової задачі дата виконання порожня");
  }
  check(!(await page.isVisible("#task-overlay.open")), "після збереження вікно закрилось");

  console.log("\n— закриття задачі галочкою —");
  await page.click(".taskrow .tk-mark");
  await page.waitForTimeout(600);
  const patch = writes.find(w => w.m === "PATCH" && /Виконано/.test(w.body || ""));
  check(!!patch, "пішов PATCH зі статусом «Виконано»");
  if (patch) {
    const b = JSON.parse(patch.body)[0];
    check(b["Статус"] === "Виконано" && !!b["Виконано"], "у запис пішли статус і дата закриття");
  }

  console.log("\n— дашборд —");
  await page.click('.nav-item[data-page="dashboard"]');
  await page.waitForSelector(".tile", { timeout: 8000 });
  const dash = await page.textContent("#content");
  check(/Мої задачі — нагадування/.test(dash), "плитка нагадувань є");
  check(/Мої задачі/.test(dash), "картка «Мої задачі» є");
  check(/прострочена моя/.test(dash), "у картці видно прострочену задачу");

  console.log("\n— картка угоди —");
  await page.click('.nav-item[data-page="dispatch"]');
  await page.waitForSelector(".dispscroll tbody tr", { timeout: 8000 });
  /* Чіп задач просто в таблиці (25.08.2026): під номером угоди видно «📌 N»,
     а коли є прострочена — чіп червоний і з «!». */
  check(await page.isVisible(".taskchip"), "під номером угоди є чіп задач 📌");
  check(((await page.getAttribute(".taskchip", "class")) || "").includes("over"),
        "чіп червоний — по угоді є прострочена задача");
  check(/задача/i.test((await page.getAttribute(".taskchip", "title")) || ""),
        "у підказці чіпа видно назви задач");
  await page.click(".dispscroll tbody tr td:first-child");
  await page.waitForSelector("#row-overlay.open", { timeout: 5000 });
  await page.waitForTimeout(700);
  const card = await page.textContent("#row-body");
  check(/Задачі по угоді/.test(card), "у картці угоди є блок задач");
  check(/прострочена моя/.test(card), "у блоці видно задачу саме цієї угоди");
  check(await page.isVisible("#row-task-add"), "є кнопка «Задача по цій угоді»");

  console.log("\n— клієнти —");
  await page.click("#row-close");
  await page.click('.nav-item[data-page="clients"]');
  await page.waitForSelector("#content table", { timeout: 8000 });
  check(/Задач/.test(await page.textContent("#content")), "у клієнтах є колонка «Задач»");

  console.log("\n— посилання «відкрити угоду» в картці задачі —");
  /* Додано 25.08.2026: з картки задачі типу «Угода» має бути перехід на саму
     угоду. Посилання видно лише коли номер існує в таблиці; клік закриває
     задачу і відкриває картку угоди. */
  await page.click('.nav-item[data-page="tasks"]');
  await page.waitForSelector(".taskrow", { timeout: 8000 });
  await page.click('.taskrow[data-task="1"]');
  await page.waitForSelector("#task-overlay.open", { timeout: 5000 });
  await page.waitForTimeout(400);
  check(await page.isVisible("#tk-goto"), "біля номера 259 видно «відкрити угоду»");
  await page.fill("#tk-obj", "9999");
  await page.waitForTimeout(200);
  check(!(await page.isVisible("#tk-goto")), "на неіснуючому номері посилання ховається");
  await page.fill("#tk-obj", "259");
  await page.waitForTimeout(200);
  check(await page.isVisible("#tk-goto"), "повернувся справжній номер — посилання знову є");
  await page.click("#tk-goto");
  await page.waitForSelector("#row-overlay.open", { timeout: 5000 });
  check(!(await page.isVisible("#task-overlay.open")), "картка задачі закрилась");
  check(/№259/.test(await page.textContent("#row-title")), "відкрилась картка саме угоди 259");
  await page.click("#row-close");
  await page.waitForTimeout(300);

  /* Другий вхід — уже НЕ адміністратором. Перевіряємо саме те, що просила
     користувачка: не-адмін чужих задач не бачить і вибирати ролі не може. */
  console.log("\n— не-адміністратор бачить тільки свої —");
  USERS[0]["Роль"] = "Фінансист";
  await page.evaluate(() => { if (typeof enter === "function") return enter(); });
  await page.waitForTimeout(1200);
  await page.evaluate(() => { if (typeof go === "function") return go("tasks"); });
  await page.waitForSelector(".taskrow", { timeout: 8000 });
  const asFin = await page.textContent("#content");
  check(!(await page.isVisible('.doerchip[data-f="who"][data-v="all"]')), "кнопки «Усі» немає");
  check(!(await page.isVisible('.doerchip[data-f="role"][data-v=""]')), "відбору за роллю немає");
  check(/прострочена моя/.test(asFin), "свої задачі видно");
  check(!/задача фінансистки/.test(asFin), "чужа задача (іншої людини) не показується");
  check(!/чужа задача/.test(asFin), "і друга чужа теж не показується");

  console.log("");
  if (errors.length) { console.log("ПОМИЛКИ В БРАУЗЕРІ:"); errors.forEach(e => console.log("   " + e)); }
  await browser.close(); srv.close();
  const bad = fail.length || errors.length;
  console.log(bad ? "TASKS_FAIL — не пройшло: " + fail.length + ", помилок JS: " + errors.length
                  : "TASKS_OK — розділ «Задачі» працює: списки, нагадування, картка, створення, закриття");
  process.exit(bad ? 1 : 0);
})();
