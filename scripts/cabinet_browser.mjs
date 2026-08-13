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
check('рядків угод у поданні «В дорозі» = 2', rows === 2, 'було ' + rows);
await page.click('#seg button[data-f=all]');
const all = await page.locator('tr.deal').count();
check('усього своїх угод 3', all === 3, 'було ' + all);
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
check('позначка «оновлено» видима', /Дані з ліній оновлено/.test(upd), upd);
check('час у позначці — з журналу прогонів', /о \d{2}:\d{2}/.test(upd), upd);

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

console.log('\n=== плитки-відбори ===');
await page.click('.tile[data-f=done]');
const done = await page.locator('tr.deal').count();
check('відбір «доставлено» дає 1', done === 1, 'було ' + done);
await page.click('.tile[data-f=done]');
check('повторний клік скидає відбір', (await page.locator('tr.deal').count()) === 3);

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
