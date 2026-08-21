import { chromium } from '/opt/node22/lib/node_modules/playwright/index.mjs';

/* Наскрізна перевірка кабінету в справжньому браузері: вхід → зміна пароля →
   кабінет → документ → вихід. Дані підставляє scripts/cabinet_fakeserver.py,
   жива база не задіяна. Запуск: bash scripts/check_cabinet.sh */
import { mkdtempSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

const B = 'http://127.0.0.1:' + (process.env.CABINET_DEMO_PORT || '8899');
const OUT = process.env.CABINET_SHOTS || mkdtempSync(join(tmpdir(), 'cabshots-'));
let ok = 0, bad = 0;
const check = (n, c, e = '') => { c ? (ok++, console.log('  ok   ' + n)) : (bad++, console.log('  FAIL ' + n + ' ' + e)); };

const browser = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium' });
const ctx = await browser.newContext({ viewport: { width: 1500, height: 1000 } });
const page = await ctx.newPage();
const errs = [], csp = [];
page.on('pageerror', e => errs.push(String(e)));
page.on('console', m => { if (m.type() === 'error') csp.push(m.text()); });

console.log('\n=== вхід ===');
await page.goto(B + '/', { waitUntil: 'networkidle' });
check('форма входу видима', await page.locator('input[name=password]').isVisible());
await page.fill('input[name=email]', 'new@m.ua');
await page.fill('input[name=password]', 'temp-pass-1');
await page.click('button[type=submit]');
await page.waitForLoadState('networkidle');
check('перший вхід веде на зміну пароля', (await page.content()).includes('Придумайте свій пароль'));
await page.screenshot({ path: OUT + '/shot-1-login.png' });

console.log('\n=== зміна пароля ===');
await page.fill('input[name=old]', 'temp-pass-1');
await page.fill('input[name=new1]', 'мій-надійний-пароль');
await page.fill('input[name=new2]', 'мій-надійний-пароль');
await page.click('button[type=submit]');
await page.waitForLoadState('networkidle');

console.log('\n=== кабінет ===');
const body = await page.content();
check('сторінка кабінету відкрилась', await page.locator('table').isVisible());
check('видно назву компанії', body.includes('ТОВ Мірандор'));
const rows = await page.locator('tr.deal').count();
check('рядків угод у поданні «В дорозі» = 10', rows === 10, 'було ' + rows);
await page.click('#seg button[data-f=all]');
const all = await page.locator('tr.deal').count();
check('усього своїх угод 11', all === 11, 'було ' + all);

console.log('\n=== порядок рядків: за датою відправлення ===');
const order = await page.$$eval('tr.deal', ns => ns.map(n => n.dataset.id));
const pos = id => order.indexOf(id);
// 251 вийшла 29.07, 259 — аж «через два дні»: та, що вийшла раніше, має бути вище.
// Саме цей випадок користувачка й назвала першою помилкою сортування.
check('хто раніше вийшов — той вище', pos('251') < pos('259'), order.join(' → '));
// 282 без дати відправлення — має впасти вниз, під усіх, у кого дата є.
check('без дати відправлення — вниз', pos('282') > pos('259') && pos('282') > pos('203'),
      order.join(' → '));
check('доставлені — в самому кінці', pos('202') === order.length - 1, order.join(' → '));
// Дивимось саме на дані сторінки, а не на весь текст: «999» випадково
// трапляється у міткax nonce/CSRF, і перевірка час від часу падала дарма.
const ids = await page.$$eval('tr.deal', ns => ns.map(n => n.dataset.id));
check('чужої угоди немає', !ids.includes('999') && !body.includes('ЧУЖИЙ ВАНТАЖ'), ids.join(','));
check('кнопка «Вийти» видима', await page.locator('header button:has-text("Вийти")').isVisible());

console.log('\n=== мініатюра маршруту і позначка «оновлено» ===');
const dots = await page.locator('tr.deal[data-id="201"] .mini .md').count();
check('крапки маршруту в рядку намальовані', dots >= 4, 'було ' + dots);
check('поточний крок підсвічений', await page.locator('tr.deal[data-id="201"] .mini .md.now').count() === 1);
check('пройдені кроки залиті', await page.locator('tr.deal[data-id="201"] .mini .md.done').count() >= 1);
check('у доставленої угоди майбутніх кроків немає',
      await page.locator('tr.deal[data-id="202"] .mini .md.todo').count() === 0);
check('підказка з назвами кроків є',
      ((await page.locator('tr.deal[data-id="201"] .mini').getAttribute('title')) || '').includes('▸'));
const upd = await page.locator('.upd').innerText().catch(() => '');
check('позначка «оновлено» видима', /^Оновлено/.test(upd.trim()), upd);
check('у позначці є година і дата', /\d{2}:\d{2}, \d{2}\.\d{2}\.\d{2}/.test(upd), upd);

console.log('\n=== авіа: авіалінія замість судна ===');
const airCell = await page.locator('tr.deal[data-id="202"] td[data-l="Судно / авіалінія"]').innerText();
check('в авіа-угоді показана авіалінія', airCell.includes('Turkish Cargo'), airCell);
const seaCell = await page.locator('tr.deal[data-id="201"] td[data-l="Судно / авіалінія"]').innerText();
check('у морській лишилось судно', seaCell.includes('MAERSK'), seaCell);

console.log('\n=== неможлива дата не рухає крапку в кінець ===');
/* Угода 238: «Вивантаження у отримувача (факт)» 16.06 стоїть раніше за
   відправлення 22.06. Крапка має лишитись на морському плечі, а не в кінці,
   і останній вузол не має бути пройденим — статус ще не «Вантаж доставлено». */
// Перевіряємо НАЗВУ кроку, а не його номер: номер їде щоразу, коли зі схеми
// прибирають або додають вузол, і тест починає падати на рівному місці.
const d238 = await page.evaluate(() => {
  const tr = document.querySelector('tr.deal[data-id="238"]');
  if (!tr) return null;
  const dots = [...tr.querySelectorAll('.mini .md')];
  const names = (tr.querySelector('.mini').getAttribute('title') || '')
    .split('·').map(s => s.replace('▸', '').trim()).filter(Boolean);
  const i = dots.findIndex(d => d.classList.contains('now'));
  return { всього: dots.length, тепер: i, крок: names[i],
           пройдено: dots.filter(d => d.classList.contains('done')).length };
});
check('рядок 238 є', d238 !== null);
check('крапка НЕ в кінці стрічки', d238 && d238.тепер < d238.всього - 1, JSON.stringify(d238));
check('крапка на перевалці', d238 && d238.крок === 'Перевалка', JSON.stringify(d238));
check('пройденими позначені не всі вузли', d238 && d238.пройдено < d238.всього, JSON.stringify(d238));

console.log('\n=== залізниця: «ETA сухий порт» — це план завантаження на потяг ===');
/* Пояснення користувачки 21.08.2026: «Гейт аут» = виїзд з порту = факт
   завантаження на потяг; «ETA сухий порт» Маерск заповнює ПЛАНОМ завантаження
   на потяг, а не прибуттям у сухий порт. Тому дата 10.08 не має підписувати
   крок «Сухий порт», а крапка має стояти на потязі — вантаж їде саме там. */
await page.click('tr.deal[data-id="224"]');
await page.waitForTimeout(400);
const rail = await page.evaluate(() => {
  const tr = document.querySelector('tr.deal[data-id="224"]');
  const names = (tr.querySelector('.mini').getAttribute('title') || '')
    .split('·').map(s => s.replace('▸', '').trim()).filter(Boolean);
  const dots = [...tr.querySelectorAll('.mini .md')];
  const i = dots.findIndex(d => d.classList.contains('now'));
  const nd = [...document.querySelectorAll('.nd')].map(n =>
    ((n.querySelector('.dt') || n.querySelector('.plan') || {}).innerText || '—').trim());
  return { крок: names[i], сухийПорт: nd[names.indexOf('Сухий порт')],
           потяг: nd[names.indexOf('Завантажений на потяг')] };
});
check('крапка на потязі, а не на сухому порту', rail.крок === 'Завантажений на потяг', JSON.stringify(rail));
check('на потязі стоїть факт гейт ауту 11.08', (rail.потяг || '').includes('11.08'), JSON.stringify(rail));
check('«Сухий порт» лишився без дати', rail.сухийПорт === '—', JSON.stringify(rail));

// Сухий порт уже в Україні, тому позначка кордону має стояти ПЕРЕД ним, а не
// після (зауваження користувачки 21.08.2026). І жодного митного оформлення в
// схемі бути не має — клієнту показуємо рух вантажу, а не оформлення.
const chain = await page.$$eval('tr.deal[data-id="224"] .mini', ns =>
  (ns[0].getAttribute('title') || '').split('·').map(s => s.replace('▸', '').trim()).filter(Boolean));
check('митного оформлення в схемі немає',
      !chain.some(n => /митн/i.test(n)), chain.join(' → '));
const brd = await page.evaluate(() => {
  // У схемі кордон — це пунктирна риска (.brd), а не кружечок. Дивимось, які
  // кроки стоять до неї, а які після.
  const brd = document.querySelector('.chain .brd');
  if (!brd) return null;
  const kids = [...brd.parentElement.children];
  const i = kids.indexOf(brd);
  const nm = n => n.className.startsWith('nd') ? n.innerText.replace(/\s+/g, ' ').trim() : '';
  return { до: kids.slice(0, i).map(nm).filter(Boolean),
           після: kids.slice(i + 1).map(nm).filter(Boolean) };
});
check('позначка кордону в схемі є', brd !== null, JSON.stringify(brd));
check('«Сухий порт» — ПІСЛЯ кордону (він уже в Україні)',
      brd && brd.після.some(n => /Сухий порт/.test(n)), JSON.stringify(brd));
check('«Завантажений на потяг» — ДО кордону',
      brd && brd.до.some(n => /на потяг/.test(n)), JSON.stringify(brd));
await page.click('tr.deal[data-id="224"]');
await page.waitForTimeout(300);

console.log('\n=== доставлені: у «Прибуття» ФАКТ, а не план ===');
/* Угода 202 доставлена: ETA (план) 28.05.26, «Планова до клієнта (факт)» 01.06.26.
   До 15.08.2026 кабінет показував клієнту план і видавав його за факт. */
const arrCell = await page.locator('tr.deal[data-id="202"] td[data-l="Прибуття"]').innerText();
check('показана фактична дата доставки', arrCell.includes('01.06.26'), arrCell);
check('планова дата вже не показується', !arrCell.includes('28.05.26'), arrCell);
const arrOnWay = await page.locator('tr.deal[data-id="201"] td[data-l="Прибуття"]').innerText();
check('у вантажу в дорозі лишився план ETA', /\d{2}\.\d{2}\.\d{2}/.test(arrOnWay), arrOnWay);

console.log('\n=== колонка «Реліз» ===');
check('колонка є в шапці', (await page.locator('th', {hasText: 'Реліз'}).count()) === 1);
check('квадратик є в кожному рядку',
      (await page.locator('tr.deal td[data-l="Реліз"] .ck').count()) === await page.locator('tr.deal').count());
check('де реліз виданий — галка стоїть',
      (await page.locator('tr.deal[data-id="201"] td[data-l="Реліз"] .ck.on').count()) === 1);
check('де релізу немає — квадратик порожній',
      (await page.locator('tr.deal[data-id="203"] td[data-l="Реліз"] .ck.on').count()) === 0);

console.log('\n=== букінг: крапка на першому вузлі ===');
const firstDot = async id => page.$$eval(`tr.deal[data-id="${id}"] .mini .md`,
  ns => ns.findIndex(n => n.classList.contains('now')));
// 282 — імпортний букінг, 279 — ЕКСПОРТНИЙ: в експорті перший вузол інший,
// і саме там крапка раніше стояла на другій позиції.
check('імпортний букінг — крапка перша', await firstDot('282') === 0, await firstDot('282'));
check('експортний букінг — теж перша', await firstDot('279') === 0, await firstDot('279'));

console.log('\n=== головне плече — посередині ===');
// Частка шляху, на якій стоїть крапка. Раніше всі кроки були однакової ширини,
// і вантаж «у порту відправлення» опинявся посередині, хоча щойно рушив.
const dotAt = async id => page.$eval(`tr.deal[data-id="${id}"] .mini`, m => {
  const box = m.getBoundingClientRect(), now = m.querySelector('.md.now');
  if (!now) return -1;
  const c = now.getBoundingClientRect();
  return Math.round(((c.left + c.width / 2 - box.left) / box.width) * 100);
});
const pBook = await dotAt('282'), pSea = await dotAt('201');
check('букінг — на самому початку', pBook <= 10, pBook + '%');
check('у морі — за серединою', pSea >= 45, pSea + '%');
check('букінг раніше за море', pBook < pSea, pBook + '% < ' + pSea + '%');

console.log('\n=== прокрутка тільки в таблиці ===');
const scrollState = await page.evaluate(() => {
  const tw = document.querySelector('.tw');
  return { page: document.documentElement.scrollHeight > window.innerHeight + 2,
           table: tw.scrollHeight > tw.clientHeight + 2 };
});
check('сторінка сама не прокручується', scrollState.page === false, JSON.stringify(scrollState));
const headBefore = await page.evaluate(() =>
  Math.round(document.querySelector('header').getBoundingClientRect().top));
await page.evaluate(() => { document.querySelector('.tw').scrollTop = 400; });
await page.waitForTimeout(150);
const after = await page.evaluate(() => ({
  head: Math.round(document.querySelector('header').getBoundingClientRect().top),
  tiles: Math.round(document.querySelector('.tiles').getBoundingClientRect().top),
  th: Math.round(document.querySelector('thead th').getBoundingClientRect().top),
  win: window.scrollY }));
check('шапка лишилась на місці', after.head === headBefore, JSON.stringify(after));
check('плитки лишились на місці', after.tiles > 0, JSON.stringify(after));
check('заголовки колонок липкі', after.th > 0, JSON.stringify(after));
check('сторінка не поїхала', after.win === 0, JSON.stringify(after));
await page.evaluate(() => { document.querySelector('.tw').scrollTop = 0; });

console.log('\n=== картка угоди ===');
// саме 201: у неї є документи. Перший рядок — 203 (найближча ETA), а в неї їх немає.
await page.locator('tr.deal[data-id="201"]').click();
await page.waitForTimeout(250);
check('картка розкрилась', await page.locator('tr.exp').isVisible());
check('схема руху намальована', (await page.locator('tr.exp .node, tr.exp svg').count()) > 0);
const dl = page.locator('tr.exp a.btn:has-text("Завантажити")');
const ndl = await dl.count();
check('кнопки завантаження — 2 клієнтські документи', ndl === 2, 'було ' + ndl);
check('внутрішній документ не показаний', !(await page.locator('tr.exp').innerText()).includes('margin'));
// Витік 18.08.2026: файл БЕЗ префікса [Тип] показувався клієнту як «Документ».
// У фікстурі 201 такий файл лежить навмисно — обидві перевірки нижче мають
// падати, якщо білий список знову почне пропускати безтипові файли.
check('файл без типу не показаний клієнту',
      !(await page.locator('tr.exp').innerText()).includes('Заявка авто'));
check('слова «Документ» замість типу немає',
      !(await page.locator('tr.exp .doc-kind, tr.exp').innerText()).includes('Документ '));
const href = await dl.first().getAttribute('href');
check('посилання веде на сервер, а не у сховище', /^\/doc\/20\d\/\d+$/.test(href), href);
check('НЕробочої форми «Питання по вантажу» немає',
      !(await page.locator('tr.exp').innerText()).includes('Питання по вантажу'));
check('підказки про перетягування файлу немає',
      !(await page.locator('tr.exp').innerText()).includes('Перетягніть'));
await page.screenshot({ path: OUT + '/shot-2-cabinet.png', fullPage: true });

console.log('\n=== завантаження документа ===');
const resp = await page.request.get(B + href);
check('документ віддається', resp.status() === 200, resp.status());
check('віддається як файл', (resp.headers()['content-disposition'] || '').includes('attachment'));
const alien = await page.request.get(B + '/doc/999/0');
check('чужа угода через адресу → 404', alien.status() === 404, alien.status());
// Мало сховати кнопку — треба, щоб сервер і за прямою адресою не віддав файл.
// В угоди 201 клієнтських документів рівно 2 (номери 0 і 1); внутрішній
// «margin» і безтиповий «Заявка авто» у цей перелік не входять зовсім, тому
// номер 2 має бути 404. Якщо фільтр знову почне їх пускати — тут стане 200.
const past = await page.request.get(B + '/doc/201/2');
check('внутрішні файли не віддаються і за прямою адресою', past.status() === 404, past.status());

console.log('\n=== плитки-відбори ===');
await page.click('.tile[data-f=done]');
const done = await page.locator('tr.deal').count();
check('відбір «доставлено» дає 1', done === 1, 'було ' + done);
await page.click('.tile[data-f=done]');
check('повторний клік скидає відбір', (await page.locator('tr.deal').count()) === 11);

console.log('\n=== плитка «відправляються за 7 днів» ===');
const outTile = page.locator('.tile[data-f=out]');
check('плитка є', await outTile.count() === 1);
await outTile.click();
const outRows = await page.$$eval('tr.deal', ns => ns.map(n => n.dataset.id));
// 290 відправляється через 3 дні, 259 — через 2. Обидві попереду, обидві мають бути.
// Дати у фікстурі відносні (див. cabinet_fakeserver.py) — інакше перевірка протухає.
check('відбір показує ті, що ще відправляються', outRows.sort().join(',') === '259,290',
      outRows.join(','));
// 252 стоїть на ПЕРЕВАЛЦІ: вона вже вийшла з порту відправлення, тому в цю
// плитку потрапляти НЕ має, навіть маючи дату через два дні.
check('той, хто вже на перевалці, не рахується', !outRows.includes('252'), outRows.join(','));
// 251 вийшла 29.07 — вона вже в морі, у цю плитку потрапляти НЕ має.
check('ті, що вже вийшли, не рахуються', !outRows.includes('251'), outRows.join(','));
await outTile.click();

console.log('\n=== вихід ===');
await page.click('header button:has-text("Вийти")');
await page.waitForLoadState('networkidle');
check('після виходу — форма входу', await page.locator('input[name=password]').isVisible());
await page.goto(B + '/', { waitUntil: 'networkidle' });
check('назад по історії кабінет не повертається',
      !(await page.content()).includes('MRKU1111111'));

console.log('\n=== помилки в браузері ===');
check('помилок JavaScript немає', errs.length === 0, errs.join(' | ').slice(0, 300));
const cspErr = csp.filter(t => /Content Security Policy|Refused to/i.test(t));
check('CSP нічого потрібного не заблокував', cspErr.length === 0, cspErr.join(' | ').slice(0, 300));

console.log('\n' + (bad ? 'Є ПОМИЛКИ' : 'БРАУЗЕР: ЧИСТО') + '  ok=' + ok + '  FAIL=' + bad);
console.log('знімки: ' + OUT);
await browser.close();
process.exit(bad ? 1 : 0);
