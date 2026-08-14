/* Димова перевірка фасада: справжній браузер відкриває www/index.html, входить
   як адміністратор і ВІДКРИВАЄ КОЖЕН пункт меню — на комп'ютері і на телефоні.
   Падає, якщо будь-яка сторінка кинула помилку JS, показала банер «Не вдалося
   завантажити дані» або поїхала вбік (горизонтальна прокрутка).

   Навіщо: 01.08.2026 три рядки з «Налаштувань» випадково опинились у «Фінансах»
   (`isAdmin`/`rows` там не існують) — сторінка «Фінанси» падала, а помітила це
   користувачка, не я. `node --check` такого не ловить: синтаксис коректний,
   помилка виникає лише під час виконання. Тому — реальний браузер.

   ⚠️ ВИПРАВЛЕНО 02.08.2026 — до цього перевірка не працювала ВЗАГАЛІ
   (завжди SMOKE_FAIL «не знайшла жодного пункту меню»). Три причини, всі три
   виправлені тут; якщо колись знову почне падати на порожньому меню — дивись саме їх:
     1. Скрипт клав ключ сесії в localStorage, а фасад перейшов на sessionStorage
        (index.html: `sessionStorage.getItem("jwt")`, ключі "jwt" і "email").
     2. Сторінка відкривалась через file://, а Playwright для схеми file: НЕ
        перехоплює запити — усі виклики /api падали. Тому тепер піднімається
        локальний http-сервер на 127.0.0.1 і сторінка береться з нього.
     3. Меню будується лише всередині enter(); самої підміни сховища замало,
        треба ще викликати enter() у сторінці.

   Запуск: node scripts/smoke.js [шлях/до/index.html]
   Мережі не потребує: усі запити до /api перехоплюються і віддають заглушки.
   Браузер: якщо playwright не в node_modules проєкту — вказати шлях у PW,
   напр. PW=/шлях/до/node_modules/playwright node scripts/smoke.js
*/
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

// мінімальні заглушки під NocoDB, щоб сторінки мали з чим працювати
const ROW = {
  Id: 1, "Угода": "1", "Клієнт": "Тест", "Напрямок": "Імпорт", "Лінія": "Maersk",
  "Статус": "В морі", "BL": "123456789", "Контейнер": "MRSU1234567",
  "ETA": "2026-09-01", "Вид перевезення": "фрахт", "Маршрут": "A → B",
  "Менеджер": "Ірина", "Роль": "Адміністратор", "Активний": true,
  "Email": "test@example.com", "Ім'я": "Ірина", "Прізвище": "Тест",
};

/* Назви таблиць мають збігатися з тими, які фасад шукає через T["…"].
   Якщо у фасаді з'явиться нова таблиця, а тут її не буде — сторінка піде
   за адресою /tables/undefined/ і перевірка це покаже банером помилки. */
const TABLES = ["Диспетчеризація", "Користувачі", "Клієнти", "Задачі",
                "Журнал дій", "Калькуляції", "Інструкції"];

/* Диспетчеризація — перша таблиця в TABLES, тому її id «t1» (див. META нижче). */
const DISP_ID = "t1";
/* ДВІ різні суміші рядків, і обидві потрібні:
   «багато» — доставлених більше, ніж влізає на екран (звичайний стан таблиці);
   «мало»   — усе разом коротше за рамку таблиці. Саме на «мало» ламалося
              ховання доставлених під шапку: рамка має max-height, тобто
              розтягується під вміст, і запас знизу просто робив її вищою.
              Користувачка побачила це з фільтром «Ірина» (04.08.2026).
   На «багато» стара, хибна версія проходила — тому одного набору мало. */
const mix = (done, act) => [
  ...Array.from({ length: done }, (_, i) => ({ ...ROW, Id: 100 + i, "Угода": String(100 + i),
    "Статус": "Вантаж доставлено", "ETA": "2026-0" + (1 + (i % 6)) + "-15" })),
  ...Array.from({ length: act }, (_, i) => ({ ...ROW, Id: 200 + i, "Угода": String(200 + i),
    "Статус": "В морі", "ETA": "2026-09-" + (10 + i) })),
];
const DISP_MIX = { "багато рядків": mix(25, 4), "мало рядків": mix(3, 2),
  /* Суміш користувачки: фільтр «Ірина» дає 41 доставлену + 7 активних.
     Саме на ній вона тричі бачила, що доставлені не ховаються (04-05.08.2026). */
  "як у користувачки (41+7)": mix(41, 7) };
let dispMix = "багато рядків";

const META = {
  list: TABLES.map((title, i) => ({ id: "t" + (i + 1), title })),
  columns: [{ title: "Статус", uidt: "SingleSelect",
              colOptions: { options: [{ title: "В морі" }] } }],
};

// Локальний сервер: віддає лише файли з теки www — інакше Playwright не зможе
// підмінити запити до /api (див. причину 2 у шапці).
/* Службові адреси платформи — їх обслуговує не файловий сервер, а тригери на
   VPS (порти 8788/8791). Тут віддаємо коротку заглушку, інакше перевірка каже
   «немає файла поруч з index.html: sync-state», хоча файла там і не має бути. */
const SERVICE = {
  "sync-state": { running: false, ok: true, result: "SYNC_OK deals=1 new=0", error: "", steps: [] },
  "sync": { status: "started" },
  "cash-refresh": { status: "started" },
  "localcosts-refresh": { status: "ok" },
};

function serve(dir, missing) {
  return new Promise(resolve => {
    const srv = http.createServer((req, res) => {
      const name = decodeURIComponent(req.url.split("?")[0]).replace(/^\/+/, "") || "index.html";
      if (Object.prototype.hasOwnProperty.call(SERVICE, name)) {
        res.setHeader("Content-Type", "application/json; charset=utf-8");
        return res.end(JSON.stringify(SERVICE[name]));
      }
      const p = path.join(dir, SAFE(name));
      fs.readFile(p, (err, buf) => {
        // Файла немає поруч з index.html. Найчастіше це findash.html /
        // finperiod.html, які «Фінанси» відкривають усередині сторінки.
        // Записуємо назву, щоб сказати про це людською мовою, а не «404».
        if (err) { missing.push(path.basename(name)); res.statusCode = 404; return res.end("no"); }
        res.setHeader("Content-Type", name.endsWith(".js") ? "text/javascript" : "text/html");
        res.end(buf);
      });
    });
    srv.listen(0, "127.0.0.1", () => resolve({ srv, port: srv.address().port }));
  });
}

async function run(browser, url, file, viewport, label, missing) {
  const page = await browser.newPage({ viewport });
  const errors = [];
  page.on("pageerror", e => errors.push("JS: " + e.message));
  page.on("console", m => {
    if (m.type() !== "error") return;
    // Про відсутні файли скажемо окремо і зрозуміло — сирий текст «404» сюди не пускаємо.
    if (/Failed to load resource/.test(m.text())) return;
    errors.push("console: " + m.text());
  });

  await page.route("**/api/**", route => {
    const u = route.request().url();
    if (u.includes("/auth/")) {
      return route.fulfill({ status: 200, contentType: "application/json",
        body: JSON.stringify({ token: "stub-jwt" }) });
    }
    if (u.includes("/meta/")) {
      return route.fulfill({ status: 200, contentType: "application/json",
        body: JSON.stringify(META) });
    }
    /* Диспетчеризації даємо БАГАТО доставлених і кілька активних — саме та
       суміш, на якій тричі ламалося «доставлені ховаються під шапку»
       (01.08, 03.08, 04.08.2026). З одним рядком ця перевірка нічого не бачила. */
    if (u.includes(DISP_ID)) {
      return route.fulfill({ status: 200, contentType: "application/json",
        body: JSON.stringify({ list: DISP_MIX[dispMix], pageInfo: { isLastPage: true } }) });
    }
    return route.fulfill({ status: 200, contentType: "application/json",
      body: JSON.stringify({ list: [ROW], pageInfo: { isLastPage: true } }) });
  });
  await page.route("**/finrep-data*", r => r.fulfill({ status: 200,
    contentType: "application/json", body: JSON.stringify({ rows: [] }) }));
  /* Журнал кабінету клієнтів (з 14.08.2026) живе не в NocoDB, а на сервері
     кабінету — окремий маршрут /cabinet-log, який віддає лише адміністраторові.
     Без підміни перевірка бачила б «немає файла поруч з index.html». */
  await page.route("**/cabinet-log*", r => r.fulfill({ status: 200,
    contentType: "application/json", body: JSON.stringify({ list: [
      { ts: "2026-08-14T10:10:23", email: "client@example.com", client: "Мірандор",
        action: "перегляд", detail: "угод 129", ip: "203.0.113.7" },
      { ts: "2026-08-14T10:09:00", email: "client@example.com", client: "Мірандор",
        action: "відмова у файлі", detail: "угода 999 не належить компанії", ip: "203.0.113.7" },
    ] }) }));

  await page.goto(url + "/" + path.basename(file));
  // ключ сесії саме в sessionStorage — фасад читає звідти (причина 1 у шапці)
  await page.evaluate(() => {
    sessionStorage.setItem("jwt", "stub-jwt");
    sessionStorage.setItem("email", "test@example.com");
  });
  await page.reload();
  await page.waitForTimeout(400);
  // меню будується всередині enter() — без цього виклику перевіряти нічого (причина 3)
  await page.evaluate(() => { if (typeof enter === "function") return enter(); });
  await page.waitForTimeout(1500);

  const pages = await page.$$eval("[data-page]",
    els => [...new Set(els.map(e => e.dataset.page).filter(Boolean))]);

  console.log(`\n— ${label} (${viewport.width}×${viewport.height}) —`);
  if (!pages.length) {
    console.log("  ✗ не знайшла жодного пункту меню — перевірка нічого не перевірила");
    await page.close();
    return ["не знайдено меню (" + label + ")"];
  }

  const bad = [];
  for (const p of pages) {
    const before = errors.length, missBefore = missing.length;
    await page.evaluate(pg => { if (typeof go === "function") return go(pg); }, p);
    await page.waitForTimeout(800);
    const st = await page.evaluate(() => ({
      banner: (document.body.innerText.match(/Не вдалося завантажити дані[^\n]*/) || [""])[0],
      sw: document.documentElement.scrollWidth,
      iw: window.innerWidth,
    }));
    const notes = [];
    const fresh = errors.slice(before);
    const lost = [...new Set(missing.slice(missBefore))];
    if (fresh.length) notes.push(fresh[0]);
    if (st.banner) notes.push(st.banner);
    if (lost.length) notes.push("немає файла поруч з index.html: " + lost.join(", "));
    if (st.sw > st.iw + 1) notes.push(`сторінка поїхала вбік (${st.sw} проти ${st.iw})`);
    /* Диспетчеризація: доставлені мають ховатися ПІД шапкою, а найнижчий рядок —
       вміщатися повністю. Ламалося тричі (01.08, 03.08, 04.08.2026), тому
       перевіряємо машиною, а не оком. На телефоні правило інше: там таблиця
       без власної прокрутки, доставлені йдуть ПІСЛЯ активних. */
    if (p === "dispatch") {
      for (const mixName of Object.keys(DISP_MIX)) {
      dispMix = mixName;
      // перемальовуємо таблицю на цій суміші рядків
      await page.evaluate(() => { DISP_CACHE = null; return go("dispatch"); });
      await page.waitForTimeout(700);
      const s = await page.evaluate(() => {
        const box = document.getElementById("dscroll");
        const rows = [...document.querySelectorAll("#drows tr")];
        if (!box || !rows.length) return null;
        // На телефоні таблиця не має власної прокрутки — правило там інше
        const phone = getComputedStyle(box).overflowY === "visible";
        const boxRect = box.getBoundingClientRect();
        /* Липкі саме клітинки заголовка (thead th{position:sticky}), а не сам
           <thead>: він їде вгору разом із таблицею, тому його .bottom для
           розрахунку не годиться — беремо ВИСОТУ і кладемо її від верху рамки.
           На цьому я вже помилилась один раз, коли писала цю перевірку. */
        const head = box.querySelector("thead");
        const headBottom = boxRect.top + (head ? head.getBoundingClientRect().height : 0);
        const seen = rows.find(r => r.getBoundingClientRect().top >= headBottom - 1);
        const last = rows[rows.length - 1].getBoundingClientRect();
        return { phone, firstSeenDone: !!seen && seen.classList.contains("done"),
                 firstSeenNo: seen ? seen.cells[0].innerText.trim() : "?",
                 lastCut: last.bottom > boxRect.bottom + 1 };
      });
      if (s && !s.phone) {
        if (s.firstSeenDone) notes.push(`${mixName}: доставлені не сховались під шапку — зверху видно угоду ${s.firstSeenNo}`);
        if (s.lastCut) notes.push(`${mixName}: нижній рядок видно не повністю — не вистачає запасу знизу`);
      }
      }
      dispMix = Object.keys(DISP_MIX)[0];
    }
    if (notes.length) { bad.push(`  ✗ ${p} [${label}]: ${notes.join(" ;; ")}`); }
    else console.log(`  ✓ ${p}`);
  }
  await page.close();
  return bad;
}

(async () => {
  const file = path.resolve(FILE);
  if (!fs.existsSync(file)) { console.log("SMOKE_ERROR не знайшла файл " + file); process.exit(1); }
  const missing = [];
  const { srv, port } = await serve(path.dirname(file), missing);
  const url = "http://127.0.0.1:" + port;
  const browser = await chromium.launch();
  try {
    const bad = [
      ...await run(browser, url, file, { width: 1440, height: 900 }, "комп'ютер", missing),
      ...await run(browser, url, file, { width: 390, height: 844 }, "телефон", missing),
    ];
    if (bad.length) { console.log("\nSMOKE_FAIL\n" + bad.join("\n")); process.exitCode = 1; }
    else console.log("\nSMOKE_OK — усі сторінки відкрились без помилок, і на комп'ютері, і на телефоні");
  } finally {
    await browser.close();
    srv.close();
  }
})().catch(e => { console.log("SMOKE_ERROR " + e.message); process.exit(1); });
