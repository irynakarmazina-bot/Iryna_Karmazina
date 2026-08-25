/* Перевірка вікна «Дані від перевізника» (25.08.2026).
   Сценарій — рівно той, що показала користувачка: вставити повідомлення
   перевізника ЯК Є → «Розібрати» → поля заповнились правильно → «Зберегти» →
   у таблицю угод пішли правильні поля, у довідники Авто/Водії/Перевізники —
   нові записи. Дані підставні, мережі не треба.
   Запуск: node scripts/truck.js [шлях/до/index.html] (браузер: PW=…) */
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
const DEALS = [{ Id: 44, "Угода": "292", "Клієнт": "Тест ТОВ", "Статус": "Букінг", "Напрямок": "Експорт",
                 "Менеджер": "Ірина", "Лінія": "Maersk", "Вид перевезення": "фрахт+ТЕО+авто",
                 "Контейнер": "MRSU5082306" }];
// у довіднику вже є цей причеп — перевіримо, що дубль не створюється
const CARS = [{ Id: 1, "Номер": "BH9739XF", "Тип": "причеп", "Перевізник": "" }];

const CARRIER_TEXT = `нижче дані по авто, подача на 26.08
Бланк ЦМР додатково відправлю Вам.

MRSU5082306
Цьоць Олександр Ярославович
BH2921TB  BH9739XF
093) 746-27-56
паспорт GJ729236

ПП Ягодин

«HM TRANSPORT» LIMITED 65059, Odesa city, Geraniyeva street, 8, office 101, Ukraine
code 43266315
UA323348510000000026007195774 in PJSC "PUMB", Kiev
HM TRANSPORT LLC единый регистрационный номер ЕС –  номер EORI: LTUA0000000010145.`;

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
    if (u.includes("/" + ID("Авто") + "/")) return json({ list: CARS, pageInfo: { isLastPage: true } });
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

  console.log("\n— відкриття вікна з клітинки «Авто» —");
  await page.click('td[data-trk]');
  await page.waitForSelector("#truck-overlay.open", { timeout: 5000 });
  check(true, "вікно відкрилось кліком по клітинці «Авто»");
  check(/№292/.test(await page.textContent("#truck-title")), "у заголовку — номер угоди");

  console.log("\n— розбір тексту перевізника —");
  await page.fill("#trk-raw", CARRIER_TEXT);
  await page.click("#trk-parse");
  await page.waitForTimeout(300);
  const val = async id => (await page.inputValue("#" + id)).trim();
  check(await val("trk-truck") === "BH2921TB", "тягач BH2921TB: " + await val("trk-truck"));
  check(await val("trk-trail") === "BH9739XF", "причеп BH9739XF: " + await val("trk-trail"));
  check(await val("trk-pib") === "Цьоць Олександр Ярославович", "ПІБ водія: " + await val("trk-pib"));
  check(await val("trk-tel") === "093 746 27 56", "телефон: " + await val("trk-tel"));
  check(await val("trk-pass") === "GJ729236", "паспорт: " + await val("trk-pass"));
  check(await val("trk-pp") === "ПП Ягодин", "пункт перетину: " + await val("trk-pp"));
  check(await val("trk-feed") === "26.08.26", "подача у людському форматі: " + await val("trk-feed"));
  check(await val("trk-cont") === "MRSU5082306", "контейнер: " + await val("trk-cont"));
  check(await val("trk-carr") === "HM TRANSPORT LIMITED", "перевізник: " + await val("trk-carr"));
  check(await val("trk-code") === "43266315", "код: " + await val("trk-code"));
  check(await val("trk-iban") === "UA323348510000000026007195774", "IBAN: " + await val("trk-iban"));
  check(/PUMB/.test(await val("trk-bank")), "банк: " + await val("trk-bank"));
  check(await val("trk-eori") === "LTUA0000000010145", "EORI: " + await val("trk-eori"));
  check(/збігається/.test(await page.textContent("#trk-note")), "звірка контейнера з угодою — збіг");

  console.log("\n— збереження —");
  await page.click("#truck-save");
  await page.waitForTimeout(900);
  check(!(await page.isVisible("#truck-overlay.open")), "вікно закрилось після збереження");
  const dealPatch = writes.find(w => w.m === "PATCH" && w.u.includes(ID("Диспетчеризація")));
  check(!!dealPatch, "пішов запис в угоду");
  if (dealPatch){
    const b = JSON.parse(dealPatch.body)[0];
    check(b["Номер авто"] === "BH2921TB" && b["Причеп"] === "BH9739XF", "в угоду пішли тягач і причеп");
    check(b["Водій (ПІБ)"] === "Цьоць Олександр Ярославович" && b["Водій (телефон)"] === "093 746 27 56",
          "в угоду пішов водій з телефоном");
    check(/-08-26$/.test(b["Подача авто (план)"] || ""), "в угоду дата пішла в форматі бази: " + b["Подача авто (план)"]);
    check(b["Перевізник"] === "HM TRANSPORT LIMITED", "в угоду пішла назва перевізника");
  }
  const carPosts = writes.filter(w => w.m === "POST" && w.u.includes(ID("Авто")));
  check(carPosts.length === 1 && /BH2921TB/.test(carPosts[0].body), "у довідник «Авто» додано ЛИШЕ тягач (причеп уже був — дубля немає)");
  const drvPost = writes.find(w => w.m === "POST" && w.u.includes(ID("Водії")));
  check(!!drvPost && /Цьоць/.test(drvPost.body) && /GJ729236/.test(drvPost.body), "у довідник «Водії» пішов водій з паспортом");
  const carrPost = writes.find(w => w.m === "POST" && w.u.includes(ID("Перевізники")));
  check(!!carrPost && /ЄДРПОУ/.test(carrPost.body) && /43266315/.test(carrPost.body) && /LTUA0000000010145/.test(carrPost.body),
        "у довідник «Перевізники» пішли ЄДРПОУ і EORI");
  const trailFill = writes.find(w => w.m === "PATCH" && w.u.includes(ID("Авто")));
  check(!!trailFill && /HM TRANSPORT/.test(trailFill.body), "наявному причепу ДОПОВНЕНО порожнє поле «Перевізник»");

  console.log("\n— другий формат повідомлення (МАЛЬ-ТРАНС, 25.08.2026) —");
  /* Реальний лист, на якому перший парсер розібрав лише половину: кириличні
     номери, «Водій:» з підписом, «перехід» замість «ПП», «ЄДРПОУ:», адреса
     окремим рядком, тент. */
  await page.click('td[data-trk]');
  await page.waitForSelector("#truck-overlay.open", { timeout: 5000 });
  await page.fill("#trk-raw", `подача на 27.08
Водій: Мальчук Іван Петрович
АС5205НО  АС5605ХЕ
тел. 099 392 04 82
паспорт: АС123456
перехід Ягодин
авто тент

Перевізник: ТОВ «МАЛЬ-ТРАНС»
Адреса: 44543, Волинська обл., Камінь-Каширський р-н, с. Сошичне, вул. Миру, буд. 113
ЄДРПОУ: 45626475`);
  await page.click("#trk-parse");
  await page.waitForTimeout(300);
  check(await val("trk-truck") === "АС5205НО", "кириличний тягач: " + await val("trk-truck"));
  check(await val("trk-trail") === "АС5605ХЕ", "кириличний причеп: " + await val("trk-trail"));
  check(await val("trk-pib") === "Мальчук Іван Петрович", "ПІБ з підпису «Водій:»: " + await val("trk-pib"));
  check(await val("trk-pass") === "АС123456", "паспорт: " + await val("trk-pass"));
  check(await val("trk-pp") === "Ягодин", "«перехід Ягодин»: " + await val("trk-pp"));
  check(await val("trk-equip") === "тент", "тент → тип обладнання: " + await val("trk-equip"));
  check(await val("trk-carr") === "ТОВ МАЛЬ-ТРАНС", "назва з формою власності: " + await val("trk-carr"));
  check(await val("trk-code") === "45626475", "ЄДРПОУ: " + await val("trk-code"));
  check(/Волинська/.test(await val("trk-addr")), "адреса з окремого рядка: " + (await val("trk-addr")).slice(0, 30));
  check(await val("trk-feed") === "27.08.26", "подача 27.08: " + await val("trk-feed"));
  await page.click("#truck-close");

  console.log("");
  if (errors.length) { console.log("ПОМИЛКИ В БРАУЗЕРІ:"); errors.forEach(e => console.log("   " + e)); }
  await browser.close(); srv.close();
  const bad = fail.length || errors.length;
  console.log(bad ? "TRUCK_FAIL — не пройшло: " + fail.length + ", помилок JS: " + errors.length
                  : "TRUCK_OK — вікно перевізника: розбір, запис в угоду і довідники працюють");
  process.exit(bad ? 1 : 0);
})();
