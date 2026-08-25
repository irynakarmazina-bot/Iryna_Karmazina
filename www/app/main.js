/* ═══════════════════════════════════════════════════════════════════════════
   ЕРП «Юнітекс» — головний модуль фасада.

   Раніше ВЕСЬ цей код жив прямо в www/index.html одним шматком на 4100 рядків.
   Рішення користувачки 13.08.2026: розділити на модулі, щоб паралельні сесії
   не стикалися в одному файлі (02.08 через це з платформи зникла денна робота)
   і щоб перевірка ловила забуті залежності ще до браузера.

   Це ПЕРШИЙ крок переїзду: код винесено з HTML як є, жодного рядка всередині
   не змінено. Далі він ділиться на окремі модулі (state, core, ролі, розділи) —
   по одному, з перевіркою після кожного.

   ⚠️ У модулі нічого не є глобальним. Тому те, чим користуються ЗОВНІ (перевірки
   в браузері викликають enter() і go()), треба віддавати явно — див. кінець файла.
   ═══════════════════════════════════════════════════════════════════════════ */
"use strict";
const $ = id => document.getElementById(id);
function esc(s){ return String(s==null?"":s).replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c])); }

/* Українське відмінювання після числа: 1 угода, 2 угоди, 5 угод, 11 угод, 22 угоди. */
function plural(n, one, few, many){
  const a = Math.abs(n) % 100, b = a % 10;
  if (a > 10 && a < 20) return many;
  if (b === 1) return one;
  if (b >= 2 && b <= 4) return few;
  return many;
}

/* Розмітка статей «Інструкцій» — єдине місце у фасаді, де вміст із бази
   вставляється як HTML, а не як текст (статті перенесені з Notion і мають
   заголовки, списки, посилання). Перевірено 02.08.2026: до цієї правки
   звичайний <img onerror=...> у полі «Зміст» виконувався і забирав ключ сесії.

   Правило БІЛОГО списку: лишаємо тільки перелічені теги, усе інше стає
   звичайним текстом. Не «вирізаємо погане» (список поганого завжди неповний),
   а «пропускаємо лише відоме добре». */
const HTML_OK = ["p","br","b","strong","i","em","u","s","h1","h2","h3","h4",
                 "ul","ol","li","blockquote","code","pre","hr","a",
                 "table","thead","tbody","tr","th","td","span","div"];
function safeHtml(raw){
  /* ВАЖЛИВО: розбираємо через DOMParser, а НЕ через innerHTML звичайного <div>.
     Перевірено 02.08.2026: `div.innerHTML = ...` одразу починає вантажити
     картинки, і <img src=x onerror="…"> спрацьовує ЩЕ ДО того, як ми його
     приберемо — ключ сесії крали навіть при правильному очищенні.
     DOMParser створює «мертвий» документ: нічого не вантажиться і не виконується. */
  const doc = new DOMParser().parseFromString(
    "<body>" + String(raw == null ? "" : raw) + "</body>", "text/html");
  const box = doc.body;
  const walk = el => {
    [...el.children].forEach(ch => {
      const tag = ch.tagName.toLowerCase();
      if (!HTML_OK.includes(tag)){
        // невідомий тег (script, img, iframe…) — лишаємо лише його текст
        ch.replaceWith(document.createTextNode(ch.textContent || ""));
        return;
      }
      // атрибути: жодних on* (onclick, onerror…), style і посилань на javascript:
      [...ch.attributes].forEach(at => {
        const n = at.name.toLowerCase();
        if (n === "href" && tag === "a"){
          const u = safeLink(at.value);
          if (u) ch.setAttribute("href", u); else ch.removeAttribute("href");
          ch.setAttribute("rel", "noopener noreferrer");
          ch.setAttribute("target", "_blank");
          return;
        }
        if (n !== "colspan" && n !== "rowspan") ch.removeAttribute(at.name);
      });
      walk(ch);
    });
  };
  walk(box);
  return box.innerHTML;
}
/* Посилання: тільки звичайні http(s). javascript:, data: тощо — відкидаємо. */
function safeLink(u){
  const s = String(u == null ? "" : u).trim();
  if (!s) return "";
  return /^https?:\/\//i.test(s) ? s : "";
}

/* ===== оформлення (в налаштуваннях користувача) ===== */
let palette = localStorage.getItem("palette") || "finrep";
const PALETTES = [ ["finrep","Фінзвіт (фірмовий)"],["warm","Теплий"],["ocean","Океан"],["indigo","Індиго"],["emerald","Смарагд"] ];
function setPalette(p){ palette=p; localStorage.setItem("palette",p); if(p==="finrep") delete document.documentElement.dataset.palette; else document.documentElement.dataset.palette=p; renderPals(); }
if (palette !== "finrep") document.documentElement.dataset.palette = palette;
function renderPals(){
  const html = PALETTES.map(([p,n])=>`<button class="pal-dot ${p===palette?"sel":""}" data-pal="${p}" title="${n}"></button>`).join("");
  const ps = $("pal-settings"); if (ps) ps.innerHTML = html;
  const pn = $("pal-name"); if (pn) pn.textContent = "Обрано: " + (PALETTES.find(x=>x[0]===palette)||["",""])[1];
  document.querySelectorAll(".pal-dot").forEach(b=>b.addEventListener("click",()=>setPalette(b.dataset.pal)));
}

/* ===== API ===== */
const BASE_ID = "pbhr1qkpvx09z8m";
let T = {};            // назва таблиці -> id
let JWT = sessionStorage.getItem("jwt") || null;
let ROLE = "Перегляд", UNAME = "";
async function api(path, opts={}){
  const h = Object.assign({"Content-Type":"application/json"}, opts.headers||{});
  if (JWT) h["xc-auth"] = JWT;
  const r = await fetch(path, Object.assign({}, opts, {headers:h}));
  if (r.status === 401){ doLogout(); throw new Error("сесія завершилась — увійди знову"); }
  /* Читаємо тіло ТЕКСТОМ і лише потім розбираємо. Було: `await r.json()` у
     try/catch, а при невдачі — тихо `{}`. Через це відповідь «200 OK, але не
     дані» (сторінка помилки від Caddy, обрив з'єднання, перезапуск NocoDB)
     виглядала для сторінки як «даних немає» — порожня таблиця БЕЗ жодного
     попередження. Перевірено 02.08.2026 у браузері: екран при битій відповіді
     і при справді порожній базі був ІДЕНТИЧНИЙ, відрізнити неможливо.
     Тепер: порожнє тіло — це нормально (так відповідають деякі записи),
     а НЕ-порожнє і не-JSON — це збій, і про нього кажемо вголос. */
  const raw = await r.text();
  let js = null, parseFail = false;
  if (raw.trim()){
    try { js = JSON.parse(raw); } catch(e){ parseFail = true; }
  }
  if (!r.ok){
    const m = (js && (js.msg || js.message || js.error)) || "";
    throw new Error((typeof m === "string" && m ? m : "помилка сервера") + " (HTTP " + r.status + ")");
  }
  if (parseFail)
    throw new Error("сервер відповів не даними — схоже, він перезапускається. Спробуй за хвилину");
  return js || {};
}
/* Службові адреси (/sync, /cash-refresh, /localcosts-refresh) запускають
   розрахунки на сервері. Раніше вони викликались БЕЗ ключа сесії, а Caddy сам
   підставляв службовий токен — тобто їх міг смикати будь-хто, хто знає адресу
   сайту, навіть не входячи в платформу. Тепер надсилаємо свій ключ, і сервер
   перевіряє роль. Помилки доступу показуємо людською мовою. */
/* Підпис під кнопкою оновлення: що і коли сталося. Вимога користувачки
   03.08.2026: «якщо оновлено — писати Оновлено та коли; якщо не оновилося —
   писати, що помилка оновлення». Раніше був лише тост на 4 секунди: відвернувся —
   і не знаєш, спрацювало чи ні. Підпис лишається на екрані.
   Стан зберігається на час сесії, тому видно і після переходу між сторінками. */
function refreshNote(slotId, state, msg){
  const el = $(slotId);
  const when = new Date().toLocaleString("uk-UA",
    {day:"2-digit",month:"2-digit",hour:"2-digit",minute:"2-digit"});
  const rec = state === "ok"   ? {css:"var(--good-text)", txt:"✅ Оновлено " + when}
            : state === "busy" ? {css:"var(--warn-text)", txt:"⏳ " + msg}
            : state === "run"  ? {css:"var(--ink-2)",     txt:"⏳ " + msg}
            :                    {css:"var(--crit-text)", txt:"⚠ Помилка оновлення " + when + " — " + msg};
  if (state !== "run") sessionStorage.setItem("note:" + slotId, JSON.stringify({...rec, when}));
  if (el) el.innerHTML = `<span style="color:${rec.css};font-size:12.5px">${esc(rec.txt)}</span>`;
}
/* Показати збережений підпис після перемальовування сторінки. */
function restoreNote(slotId){
  const el = $(slotId);
  if (!el) return;
  try{
    const r = JSON.parse(sessionStorage.getItem("note:" + slotId) || "null");
    if (r) el.innerHTML = `<span style="color:${r.css};font-size:12.5px">${esc(r.txt)}</span>`;
  }catch(e){ /* зіпсований запис — просто нічого не показуємо */ }
}
async function svc(path){
  const r = await fetch(path, {headers: JWT ? {"xc-auth": JWT} : {}});
  let js = null;
  try { js = JSON.parse(await r.text() || "null"); } catch(e){ js = null; }
  if (r.status === 401){
    const m = (js && js.error) || "Сесія завершилась — увійди знову.";
    sysWarn(m); throw new Error(m);
  }
  if (r.status === 403){
    const m = (js && js.error) || "Немає прав на цю дію.";
    sysWarn(m); throw new Error(m);
  }
  if (r.status === 409){
    const m = (js && js.error) || "Це вже виконується — зачекай.";
    toast("⏳ " + m); throw new Error(m);
  }
  if (!r.ok) throw new Error((js && js.error) || ("HTTP " + r.status));
  return js || {};
}
async function loadAll(table){
  let out = [], offset = 0;
  while (true){
    const js = await api(`/api/v2/tables/${table}/records?limit=200&offset=${offset}`);
    out = out.concat(js.list||[]);
    if ((js.list||[]).length < 200) break;
    offset += 200;
  }
  return out;
}

/* ===== ролі ===== */
const RC = {
  "Адміністратор":        { nav:["dashboard","tasks","dispatch","calc","finance","clients","crm","accounting","cabinets","instr","users"], scope:"all", fin:"full", sync:true, edit:true },
  /* sync:true для сейлза — рішення користувачки 03.08.2026: «має бути дозволено
     і сейлзу і операціоністу — оновлення таблиці диспетчеризації». Це оновлення
     угод з Експедитора, а не фінанси; фінансові кнопки лишаються фінансовим ролям. */
    /* «cabinets» сейлзу — рішення користувачки 24.08.2026: він бачить кабінети
     ТІЛЬКИ своїх клієнтів. Обмеження робить сервер кабінету (erp_scope), а не
     ця сторінка: браузер лише не малює зайвого. */
  "Сейлз-менеджер":       { nav:["dashboard","tasks","dispatch","calc","finance","clients","crm","cabinets","instr","users"], scope:"mgr", fin:"personal", sync:true, edit:true },
  "Бухгалтер":            { nav:["dashboard","tasks","dispatch","calc","finance","clients","accounting","instr","users"], scope:"all", fin:"acct", sync:true },
  /* Фінансисту не потрібні ні CRM, ні диспетчеризація (рішення користувачки
     11.08.2026) — його робота це «Фінанси» і «Бух. облік».
     УВАГА на майбутнє: прибрано СТОРІНКУ, а не доступ до таблиці угод. Сторінка
     «Бух. облік» читає з «Диспетчеризації» маршрут, коносамент і контейнер, а
     галочку «переказано» ПИШЕ туди ж (saveField → «Переказ за кордон», «Дата
     переказу», «Сума переказу»). Прибереш таблицю — відвалиться саме те, заради
     чого роль і заводили. Тому в прошарку (server/gateway.py) «Диспетчеризація»
     для цієї ролі лишається, але тільки на читання і на ці три колонки. */
  /* Порядок у nav — це НЕ лише порядок кнопок: перший пункт відкривається одразу
     після входу (enter() робить go(cfg().nav[0])). Тому «finance» стоїть першим
     навмисно — вказівка користувачки 11.08.2026: фінансист заходить одразу у
     «Фінанси», дашборда в нього немає взагалі.
     Якщо він усе ж набере адресу дашборда, go() поверне його на «Фінанси»:
     `if (!cfg().nav.includes(page)) page = cfg().nav[0]`. */
  /* «dispatch» повернуто фінансисту 15.08.2026 на прохання користувачки: «додай для
     ролі Фінансист можливість переглядати Диспетчеризацію та скачувати і створювати
     документи». Саме ПЕРЕГЛЯД: `edit` не додаємо, тому правити клітинки він не може
     (CAN_EDIT = cfg().edit), а прошарок і поготів пропускає йому лише читання угод
     плюс позначку переказу. «finance» лишається ПЕРШИМ — фінансист і далі заходить
     одразу у «Фінанси» (рішення 11.08.2026). */
  "Фінансист":            { nav:["finance","tasks","dispatch","clients","accounting","instr","users"], scope:"all", fin:"full", sync:true },
  "Операційний менеджер": { nav:["dashboard","tasks","dispatch","clients","crm","instr","users"], scope:"ops", fin:"none", sync:true, edit:true },
  "Логіст":               { nav:["dispatch","instr","users"], scope:"all", cols:"logist", fin:"none", sync:false, edit:true },
  "Перегляд":             { nav:["dashboard","tasks","dispatch","calc","finance","clients","instr","users"], scope:"all", fin:"blur", sync:false },
};
function cfg(){ return RC[ROLE] || RC["Перегляд"]; }
function scoped(rows){
  const c = cfg();
  if (c.scope === "mgr") return rows.filter(r=>String(r["Менеджер"]||"").trim() === UNAME);
  if (c.scope === "ops") return rows.filter(r=>String(r["Оп. менеджер"]||"").trim() === UNAME);
  return rows;
}

/* ===== вхід/вихід ===== */
async function doLogin(){
  $("login-err").style.display="none";
  try{
    const r = await fetch("/api/v1/auth/user/signin", {method:"POST",
      headers:{"Content-Type":"application/json"},
      body: JSON.stringify({email: $("em").value.trim(), password: $("pw").value})});
    const js = await r.json();
    if (!r.ok || !js.token) throw new Error("bad");
    JWT = js.token; sessionStorage.setItem("jwt", JWT);
    sessionStorage.setItem("email", $("em").value.trim().toLowerCase());
    enter();
  } catch(e){ $("login-err").style.display="block"; }
}
function doLogout(){ JWT=null; sessionStorage.clear(); $("app").style.display="none"; $("login-screen").style.display="flex"; }
async function enter(){
  $("login-screen").style.display="none"; $("app").style.display="block";
  const em = sessionStorage.getItem("email")||"";
  $("u-name").textContent = em.split("@")[0];
  $("u-avatar").textContent = (em[0]||"?").toUpperCase();
  try{
    const meta = await api(`/api/v2/meta/bases/${BASE_ID}/tables`);
    (meta.list||[]).forEach(t=>{ T[t.title] = t.id; });
    if (T["Користувачі"]){
      // loadAll, а не limit=100: у довіднику може стати більше 100 записів, і тоді
      // співробітник просто не знайшовся б — роль тихо впала б до «Перегляд»,
      // а перевірка «Активний» перестала б працювати. Без жодного попередження.
      const list = await loadAll(T["Користувачі"]);
      const rec = list.find(x=>String(x["Email"]||"").toLowerCase() === em);
      if (rec && rec["Активний"] === false){
        // доступ заблоковано адміністратором — не пускаємо взагалі, а не «тільки перегляд»
        doLogout();
        $("login-err").textContent = "Доступ заблоковано. Зверніться до адміністратора.";
        $("login-err").style.display = "block";
        return;
      }
      const me = rec;
      if (me){
        ROLE = me["Роль"] || "Перегляд";
        // UNAME — тільки імʼя: по ньому зіставляється поле «Менеджер» в угодах.
        // Для показу в шапці беремо повне «Імʼя Прізвище» (вимога 01.08.2026).
        UNAME = me["Ім'я"] || $("u-name").textContent;
        const full = [me["Ім'я"], me["Прізвище"]].filter(Boolean).join(" ");
        if (full) $("u-name").textContent = full;
      }
      else ROLE = "Перегляд";
    }
    /* Роль визначено — прибираємо смугу, якщо вона лишилась від попередньої спроби.
       БЕЗ ЦЬОГО РЯДКА (помилка 05.08-11.08.2026): sysWarn() малює смугу і прибирає
       її ТІЛЬКИ власним ✕. Тому «Не вдалося визначити твою роль» переживало
       успішний повторний вхід: у значку вже стояв АДМІНІСТРАТОР і дані вантажились,
       а смуга внизу все одно казала «тимчасово тільки перегляд». Користувачка
       бачила це двічі й обидва рази повідомила сама.
       Причину знайшли 07.08, але виправлення тоді не зробили — лише записали.
       Прибираємо саме ТУТ, до go(): якщо далі якась сторінка не завантажиться,
       вона покаже свою власну, свіжу смугу, і ми її не затремо. */
    sysWarn("");
  } catch(e){
    /* Було: тихо ROLE = "Перегляд". Адміністратор під час перезапуску бази
       бачив «🔒 доступно лише фінансовим ролям» і думав, що їй забрали права.
       Тепер роль так само знижується (щоб нічого не зламати випадковою дією),
       але про причину сказано вголос, і видно, що це збій, а не рішення. */
    ROLE = "Перегляд";
    sysWarn("Не вдалося визначити твою роль (" + (e.message || "збій зв'язку") +
            "). Тимчасово ввімкнено тільки перегляд — онови сторінку, коли зв'язок відновиться.");
  }
  $("u-role").textContent = ROLE;
  logAction("вхід у платформу", "", "", "", "");
  buildNav();
  refreshTaskBadge();          // нагадування про задачі — одразу після входу
  go(cfg().nav[0]);
  /* На телефоні після входу показуємо МЕНЮ, а не одразу дашборд
     (прохання користувачки 02.08.2026). На комп'ютері меню й так завжди видно. */
  if (isPhone()) openMenu(true);
}
$("login-btn").addEventListener("click", doLogin);
$("pw").addEventListener("keydown", e=>{ if(e.key==="Enter") doLogin(); });
$("logout").addEventListener("click", doLogout);
document.querySelector(".user-chip").style.cursor = "pointer";
document.querySelector(".user-chip").title = "Налаштування";
document.querySelector(".user-chip").addEventListener("click", ()=>{ renderPals(); $("set-overlay").classList.add("open"); });
$("set-close").addEventListener("click", ()=>$("set-overlay").classList.remove("open"));
$("calc-close").addEventListener("click", ()=>$("calc-overlay").classList.remove("open"));
$("calc-overlay").addEventListener("click", e=>{ if(e.target===$("calc-overlay")) $("calc-overlay").classList.remove("open"); });
$("set-overlay").addEventListener("click", e=>{ if(e.target===$("set-overlay")) $("set-overlay").classList.remove("open"); });
$("task-close").addEventListener("click", ()=>$("task-overlay").classList.remove("open"));
$("task-overlay").addEventListener("click", e=>{ if(e.target===$("task-overlay")) $("task-overlay").classList.remove("open"); });

/* ===== навігація ===== */
/* меню: лінійні значки в одному стилі з фінзвітом (емодзі прибрано 31.07.2026) */
const MODMAP = {
  dashboard:{label:"Дашборд",   ico:"chart",     c:"blue"},
  calc:     {label:"Калькуляція",ico:"calculator",c:"violet"},
  dispatch: {label:"Диспетчеризація",ico:"ship",  c:"blue"},
  crm:      {label:"CRM",        ico:"funnel",    c:"amber"},
  clients:  {label:"Клієнти",    ico:"users",     c:"green"},
  finance:  {label:"Фінанси",    ico:"cash",      c:"green"},
  accounting:{label:"Бух. облік",ico:"book",      c:"violet"},
  tasks:    {label:"Задачі",     ico:"check",     c:"green"},
  cabinets: {label:"Кабінети клієнтів", ico:"key", c:"amber"},
  instr:    {label:"Інструкції", ico:"doc",       c:"slate"},
  users:    {label:"Налаштування",ico:"gear",   c:"slate"},
};
function buildNav(){
  /* Лічильник у пункті «Задачі» — це і є нагадування в платформі. Порожній
     <span> малюється завжди: наповнює його refreshTaskBadge() після того, як
     задачі завантажаться, і потім після кожної зміни. */
  $("nav").innerHTML = cfg().nav.map(id=>`<button class="nav-item" data-page="${id}"><span class="ico nav-ico-${MODMAP[id].c||"slate"}"><svg viewBox="0 0 24 24">${ICONS[MODMAP[id].ico]||""}</svg></span>${MODMAP[id].label}${id==="tasks"?'<span class="navbadge" id="nav-tasks-badge" style="display:none"></span>':""}</button>`).join("");
  $("nav").querySelectorAll(".nav-item").forEach(b=>b.addEventListener("click",()=>{ DISP_QUICK=null; go(b.dataset.page); }));
  const bg = $("burger"), mc = $("menu-close");
  if (bg && !bg.dataset.bound){ bg.dataset.bound = "1";
    bg.addEventListener("click", ()=>openMenu(!document.querySelector(".sidebar").classList.contains("open"))); }
  if (mc && !mc.dataset.bound){ mc.dataset.bound = "1"; mc.addEventListener("click", ()=>openMenu(false)); }
}
/* ── мобільне меню ───────────────────────────────────────────────────────── */
const isPhone = () => window.matchMedia("(max-width:760px)").matches;
/* На телефоні таблиці показуються картками; клітинки без даних ховаємо, щоб у
   картці не було десятка прочерків (02.08.2026). */
function markEmptyCells(box){
  if (!box || !isPhone()) return;
  box.querySelectorAll("td[data-l]").forEach(td=>{
    const t = td.textContent.replace(/[\s\u2014\u2013-]/g, "");
    td.classList.toggle("empty", t === "");
  });
}
function openMenu(on){
  const sb = document.querySelector(".sidebar"), b = $("burger");
  if (!sb) return;
  sb.classList.toggle("open", !!on);
  document.body.classList.toggle("menu-open", !!on);
  if (b) b.setAttribute("aria-expanded", on ? "true" : "false");
}

/* Яка сторінка зараз відкрита. Потрібна фоновим завданням (оновлення
   диспетчеризації триває 2,5 хв і може завершитись, коли людина вже перейшла
   в інший розділ) — щоб не перемальовувати те, чого на екрані немає. */
let CUR = "";
function go(page){
  if (!cfg().nav.includes(page)) page = cfg().nav[0];
  CUR = page;
  if (isPhone()) openMenu(false);          // вибрали розділ — меню ховається
  $("nav").querySelectorAll(".nav-item").forEach(b=>b.classList.toggle("active", b.dataset.page===page));
  $("page-actions").innerHTML = "";
  $("content").innerHTML = '<div class="card"><p class="sub">Завантаження…</p></div>';
  PAGES[page]().catch(e=>{ $("content").innerHTML = '<div class="note">⚠ Не вдалося завантажити дані ('+esc(e.message)+'). Спробуй оновити сторінку.</div>'; });
}


/* ===== іконки (як у фінзвіті): емодзі в картках замінюються на лінійні значки ===== */
const ICONS = {
  key:'<circle cx="8" cy="12" r="4.2"/><path d="M12.2 12H21"/><path d="M17.5 12v3.2"/><path d="M20.2 12v2.2"/>',
  wallet:'<rect x="2.5" y="5.5" width="19" height="14" rx="3"/><path d="M2.5 10h19"/><circle cx="17.5" cy="14.5" r="1.2"/>',
  users:'<circle cx="9" cy="8" r="3.2"/><path d="M2.8 20c0-3.4 2.8-5.4 6.2-5.4S15.2 16.6 15.2 20"/><path d="M16.5 5.2a3.2 3.2 0 0 1 0 5.6M17.5 14.9c2.3.5 3.9 2.2 3.9 5.1"/>',
  truck:'<rect x="2" y="6.5" width="12" height="9.5" rx="1.6"/><path d="M14 10h3.6l2.9 3.1V16H14z"/><circle cx="7" cy="18" r="1.9"/><circle cx="17.5" cy="18" r="1.9"/>',
  ship:'<path d="M4 17.5 2.8 12l9.2-3 9.2 3-1.2 5.5"/><path d="M12 9V5.5M8.6 5.5h6.8"/><path d="M2.5 19.5c1.6 0 1.6 1.4 3.2 1.4s1.6-1.4 3.2-1.4 1.6 1.4 3.2 1.4 1.6-1.4 3.2-1.4 1.6 1.4 3.2 1.4"/>',
  calendar:'<rect x="3" y="5" width="18" height="16" rx="3"/><path d="M3 10h18M8 3v4M16 3v4"/>',
  shield:'<path d="M12 3l7.5 3v6c0 4.4-3 7.8-7.5 9-4.5-1.2-7.5-4.6-7.5-9V6z"/>',
  layers:'<path d="M12 3 3 7.5 12 12l9-4.5z"/><path d="m3 12.5 9 4.5 9-4.5M3 17l9 4.5 9-4.5"/>',
  alert:'<path d="M12 4.5 2.8 20h18.4z"/><path d="M12 10v4.2M12 17.2v.1"/>',
  box:'<path d="M21 8.5 12 3.5 3 8.5v7L12 20.5l9-5z"/><path d="M3 8.5 12 13.5l9-5M12 13.5V20.5"/>',
  cash:'<circle cx="12" cy="12" r="8.5"/><path d="M12 7.2v9.6M14.6 9.4c-.6-.8-1.6-1.1-2.6-1.1-1.5 0-2.6.8-2.6 2s1.1 1.7 2.6 2 2.6.8 2.6 2-1.1 2-2.6 2c-1.1 0-2.1-.4-2.6-1.1"/>',
  chart:'<path d="M3.5 20.5h17"/><rect x="5" y="11" width="3.4" height="7" rx="1"/><rect x="10.3" y="6.5" width="3.4" height="11.5" rx="1"/><rect x="15.6" y="9" width="3.4" height="9" rx="1"/>',
  doc:'<path d="M14 3H7a2.5 2.5 0 0 0-2.5 2.5v13A2.5 2.5 0 0 0 7 21h10a2.5 2.5 0 0 0 2.5-2.5V8.5z"/><path d="M14 3v5.5h5.5M8.5 13h7M8.5 17h5"/>',
  check:'<circle cx="12" cy="12" r="8.5"/><path d="m8.4 12.2 2.5 2.5 4.7-4.9"/>',
  calculator:'<rect x="4.5" y="2.8" width="15" height="18.4" rx="2.6"/><rect x="7.6" y="6" width="8.8" height="3.4" rx="1"/><path d="M8.2 13h.01M12 13h.01M15.8 13h.01M8.2 17h.01M12 17h.01M15.8 17h.01"/>',
  funnel:'<path d="M3.5 4.5h17l-6.6 7.8v6.4l-3.8 2v-8.4z"/>',
  gear:'<circle cx="12" cy="12" r="3.1"/><path d="M19.4 14.5a1.6 1.6 0 0 0 .32 1.77l.06.06a1.9 1.9 0 1 1-2.7 2.7l-.05-.06a1.6 1.6 0 0 0-1.78-.32 1.6 1.6 0 0 0-.97 1.47v.17a1.9 1.9 0 1 1-3.8 0v-.09a1.6 1.6 0 0 0-1.05-1.47 1.6 1.6 0 0 0-1.77.32l-.06.06a1.9 1.9 0 1 1-2.7-2.7l.06-.06a1.6 1.6 0 0 0 .32-1.77 1.6 1.6 0 0 0-1.47-.97H3.5a1.9 1.9 0 1 1 0-3.8h.09a1.6 1.6 0 0 0 1.47-1.05 1.6 1.6 0 0 0-.32-1.77l-.06-.06a1.9 1.9 0 1 1 2.7-2.7l.06.06a1.6 1.6 0 0 0 1.77.32h.08a1.6 1.6 0 0 0 .97-1.47V3.5a1.9 1.9 0 1 1 3.8 0v.09a1.6 1.6 0 0 0 .97 1.47 1.6 1.6 0 0 0 1.78-.32l.05-.06a1.9 1.9 0 1 1 2.7 2.7l-.06.06a1.6 1.6 0 0 0-.32 1.77v.08a1.6 1.6 0 0 0 1.47.97h.17a1.9 1.9 0 1 1 0 3.8h-.09a1.6 1.6 0 0 0-1.47.97z"/>',
  book:'<path d="M4 4.6A2.1 2.1 0 0 1 6.1 2.5H20v14.4H6.1A2.1 2.1 0 0 0 4 19v-14.4z"/><path d="M4 19a2.1 2.1 0 0 0 2.1 2.1H20v-4.2"/><path d="M8.5 7.2h7M8.5 10.6h4.5"/>',
};
const EMOJI_ICON = {
  "📦":["box","blue"], "🌊":["ship","blue"], "🚢":["ship","blue"], "📅":["calendar","violet"],
  "🚫":["alert","red"], "⚠️":["alert","amber"], "⚠":["alert","amber"],
  "💳":["wallet","blue"], "📤":["users","amber"], "🧊":["truck","violet"], "🧮":["layers","red"],
  "💰":["cash","green"], "📊":["chart","blue"], "👥":["users","green"], "✅":["check","green"],
  "📚":["doc","violet"], "🔐":["shield","slate"], "📄":["doc","slate"], "🛡":["shield","violet"],
  "🚚":["truck","amber"], "📈":["chart","green"], "📉":["chart","red"], "🧾":["doc","blue"],
  "⟳":["chart","slate"], "🔎":["chart","slate"], "🗂":["layers","violet"], "⏳":["calendar","amber"],
  /* задачі (12.08.2026): без цих трьох рядків емодзі в заголовках просто
     зникали б — незіставлений значок EMO_RE зрізає, а іконку не ставить */
  "🔔":["alert","amber"], "🔴":["alert","red"], "🗓":["calendar","slate"],
};
const EMO_RE = /^([\u203C-\u3299\u{1F000}-\u{1FAFF}\u2600-\u27BF][\uFE0F\u200D]*)\s*/u;
function enhanceHeads(root){
  (root || document).querySelectorAll(".card h3").forEach(h=>{
    if (h.dataset.ico) return;
    h.dataset.ico = "1";
    const m = EMO_RE.exec(h.textContent.trim());
    if (!m) return;
    const def = EMOJI_ICON[m[1].replace(/\uFE0F/g,"")] || EMOJI_ICON[m[1]];
    const rest = h.textContent.trim().replace(EMO_RE, "");
    h.innerHTML = def
      ? '<span class="ic ic-'+def[1]+'"><svg viewBox="0 0 24 24">'+ICONS[def[0]]+'</svg></span><span>'+esc(rest)+'</span>'
      : esc(rest);
    h.classList.add("h3ico");
  });
}
function enhanceTiles(root){
  enhanceHeads(root);
  // \u043F\u043B\u0438\u0442\u043A\u0430 \u043F\u0435\u0440\u0435\u0431\u0443\u0434\u043E\u0432\u0443\u0454\u0442\u044C\u0441\u044F \u0432 \u0441\u0442\u0440\u0443\u043A\u0442\u0443\u0440\u0443 \u0444\u0456\u043D\u0437\u0432\u0456\u0442\u0443: [\u0456\u043A\u043E\u043D\u043A\u0430] [\u043F\u0456\u0434\u043F\u0438\u0441 / \u0447\u0438\u0441\u043B\u043E / \u0443\u0442\u043E\u0447\u043D\u0435\u043D\u043D\u044F]
  (root || document).querySelectorAll(".tile").forEach(t=>{
    if (t.dataset.ico) return;
    t.dataset.ico = "1";
    const l = t.querySelector(".lbl");
    if (!l) return;
    const m = EMO_RE.exec(l.textContent.trim());
    const key = m ? m[1].replace(/\uFE0F/g,"") : null;
    const def = key && (EMOJI_ICON[key] || EMOJI_ICON[m[1]]);
    if (def) l.textContent = l.textContent.trim().replace(EMO_RE, "");
    const body = document.createElement("div");
    body.className = "tbody";
    while (t.firstChild) body.appendChild(t.firstChild);
    if (def) t.innerHTML = '<span class="ic ic-'+def[1]+'"><svg viewBox="0 0 24 24">'+ICONS[def[0]]+'</svg></span>';
    t.appendChild(body);
    t.classList.add("tready");
  });
}
new MutationObserver(()=>enhanceTiles()).observe(document.body, {childList:true, subtree:true});

/* ===== графіки (Chart.js з нашого сервера) ===== */
const CH = {blue:"#2563eb", green:"#12924f", amber:"#e8a33d", red:"#c22b2b", violet:"#7c3aed", slate:"#94a3b8"};
const CHARTS = {};
function drawChart(id, cfg){
  const el = document.getElementById(id);
  if (!el || typeof Chart === "undefined") return;
  if (CHARTS[id]) CHARTS[id].destroy();
  const dark = document.documentElement.dataset.theme === "dark";
  Chart.defaults.font.family = getComputedStyle(document.body).fontFamily;
  Chart.defaults.color = dark ? "#94a3b8" : "#667085";
  CHARTS[id] = new Chart(el, cfg);
}

/* ===== статуси ===== */
const STATUSES = {
  "Букінг":"t-neutral","Виконується":"t-warn","Стафіровка":"t-info","В порту відправлення":"t-info",
  "Завантажений на судно":"t-info","В морі":"t-info",
  /* «В порту призначення» — судно вже в порту, але вантаж ще не вивантажили.
     Доданий 05.08.2026: доти подія прибуття давала «В морі», і угода 256 показувалась
     як така, що пливе, хоча ETA минула 4 дні тому.
     Перейменований 11.08.2026 з «Прибув у порт» (рішення користувачки 10.08.2026):
     стара назва не казала, В ЯКОМУ порту вантаж, і плуталася з «В порту відправлення».
     На момент перейменування цей статус не стояв у ЖОДНОЇ з 277 угод, тому дані
     не зачеплені — перевірено читанням бази перед правкою. */
  /* «В порту перевалки» — вантаж зняли з судна, але це не кінець шляху: попереду ще
     один рейс. Доданий 11.08.2026 після угоди 238 (Вільгельмсгафен). */
  "В порту перевалки":"t-info",
  "В порту призначення":"t-vio",
  "Вивантажений в порту прибуття":"t-vio",
  "Завантажений на авто":"t-good","Завантажений на потяг":"t-good",
  "Вивантажений в сухому порту":"t-good","На кордоні":"t-info",
  "Вантаж доставлено":"t-del",
};
/* Назва клієнта для ПОКАЗУ: прибираємо організаційну форму «ООО»/«ТОВ»
   (прохання користувачки 01.08.2026 — «ГРАНД МАРИН ООО» читається як
   «ГРАНД МАРИН»). У базі значення НЕ чіпаємо: поле «Клієнт» приходить з
   Експедитора і синхронізація перезапише його назад. У картці угоди й у
   значеннях фільтра лишається повна назва. */
const cliName = v => {
  const full = String(v || "").trim();
  const cut = full.replace(/(^|\s)(ООО|ТОВ)(?=\s|$)/gi, "$1").replace(/\s{2,}/g, " ").trim();
  return cut || full;          // якщо після чистки нічого не лишилось — показуємо як є
};
const stPill = st => st ? `<span class="pill ${STATUSES[st]||"t-neutral"}">${esc(st)}</span>` : '<span class="cell-muted">—</span>';
/* Статус із приміткою — варіант 4, обраний користувачкою 25.08.2026 з шести:
   ЖОДНОГО окремого значка. Плашка отримує пунктирне підкреслення (як примітки
   в текстових редакторах) і сама стає кнопкою: клік по ній відкриває текст
   (bindNotes ловить клас cnote-line у режимі захоплення, тому редактор статусу
   при цьому НЕ відкривається — редагувати можна кліком повз плашку).
   До того тут був трикутник у куті — «сильно кидається в очі та розфокусує». */
const stPillNote = (st, note) => !note || !st
  ? stPill(st)
  : stPill(st).replace('<span class="pill ',
      `<span data-note="${esc(note)}" title="${esc(note)}" class="cnote-line pill `);

/* ===== класифікація перевезень (спільна для дашборда і швидких фільтрів) =====
   Правила від користувачки 31.07.2026:
   * FCL — морське перевезення з номером контейнера; LCL — позначено «Збірний»;
   * лінія буває лише там, де є морське або залізничне плече
     (мультимодальні на FOB/CIF — «ТЕО+авто» — теж), тож авіа й авто не рахуємо. */
const _s = (r,k) => String(r[k]||"").trim();
const SEA_MODES = {"фрахт":1,"фрахт+ТЕО+авто":1,"фрахт+ТЕО+залізниця":1,"ТЕО+авто":1};
const isLCL = r => /збірн/i.test(_s(r,"Тип")) || /lcl/i.test(_s(r,"FCL/LCL"));
const isSea = r => {
  const m = _s(r,"Вид перевезення");
  if (SEA_MODES[m]) return true;
  if (m === "авіа" || m === "авто") return false;
  const t = _s(r,"Тип").toLowerCase();
  return t.includes("море") || t.includes("фрахт") || t.includes("збірн");
};
const isRail  = r => /залізни/i.test(_s(r,"Вид перевезення")) || /залізни/i.test(_s(r,"Тип"));
const isAir   = r => /авіа/i.test(_s(r,"Вид перевезення"));
/* Чого при якому виді перевезення НЕ буває (зауваження користувачки 01.08.2026):
   авіа — немає ні контейнера, ні морської лінії, замість коносамента авіанакладна;
   авто — немає ні коносамента, ні контейнера, ні лінії, ні судна. */
const needsBL   = r => isAir(r) || hasLine(r);
const needsCont = r => isSea(r);
const shipDoc   = r => isAir(r) ? _s(r,"Авіанакладна") : _s(r,"BL");
const hasLine = r => isSea(r) || isRail(r);
const isDone  = r => r["Статус"] === "Вантаж доставлено";
/* дата у звичному вигляді: 05.08.26, жирним — щоб читалась з першого погляду */
const fmtD = v => { const m=/(\d{4})-(\d{2})-(\d{2})/.exec(String(v||""));
  return m ? `${m[3]}.${m[2]}.${m[1].slice(2)}` : ""; };
const dateB = v => { const d=fmtD(v); return d ? `<b>${d}</b>` : '<span class="cell-muted">—</span>'; };

/* ── редактор дати ─────────────────────────────────────────────────────────
   ДАТУ МОЖНА ВВОДИТИ З КЛАВІАТУРИ. Перевірено 21.08.2026 у браузері: у
   нативному <input type="date"> набір цифр дає сміття — «26082026»
   перетворюється на «82026-02-06», бо цифри розкладаються по сегментах у
   порядку локалі. Користувачка: «вибір в календарі працює, але треба додати
   ще і можливість вводити вручну, це було».
   Тому основне поле — звичайний текст у форматі дд.мм.рррр, а поруч вузький
   нативний date-інпут, який слугує ЛИШЕ календариком.
   Приймаємо: 26.08.2026, 26.08.26, 26/08/26, 26-08-2026, 26082026, 260826,
   а також ISO 2026-08-26. Незрозуміле НЕ зберігаємо — краще сказати людині,
   ніж мовчки записати не ту дату. */
const DATE_HINT = "дд.мм.рррр";
function parseUserDate(s){
  s = String(s == null ? "" : s).trim();
  if (!s) return "";                                  // порожнє = очистити поле
  if (/^\d{4}-\d{2}-\d{2}$/.test(s)) return s;
  const m = /^(\d{1,2})[.\-/](\d{1,2})[.\-/](\d{2}|\d{4})$/.exec(s)
         || /^(\d{2})(\d{2})(\d{4})$/.exec(s)
         || /^(\d{2})(\d{2})(\d{2})$/.exec(s);
  if (!m) return null;
  const d = m[1].padStart(2, "0"), mo = m[2].padStart(2, "0");
  const y = m[3].length === 2 ? "20" + m[3] : m[3];
  const iso = `${y}-${mo}-${d}`;
  const dt = new Date(iso + "T00:00:00Z");
  if (isNaN(dt) || dt.getUTCDate() !== +d || dt.getUTCMonth() + 1 !== +mo) return null;
  return iso;
}
const dateEditorHTML = iso =>
  `<span class="dted"><input class="edinput" type="text" inputmode="numeric"
     placeholder="${DATE_HINT}" value="${esc(fmtD(iso) || "")}"
     title="введіть з клавіатури (26.08.2026 або 26.08.26) або оберіть у календарі"
   ><input class="edpick" type="date" value="${esc(iso || "")}" title="календар"></span>`;
/* Календарик і текстове поле — одне значення: що вибрали мишкою, те й
   з'являється в тексті, і навпаки. */
function bindDatePair(wrap, onPicked){
  const txt = wrap.querySelector(".edinput"), pick = wrap.querySelector(".edpick");
  if (!txt || !pick) return;
  pick.addEventListener("change", ()=>{ txt.value = fmtD(pick.value) || ""; onPicked(); });
}
/* Дата З ЧАСОМ — «13.08 17:44». Потрібна тільки для позначки «оновлено» вгорі
   диспетчеризації, тому рік не показуємо, а час показуємо обов'язково.
   База віддає час у UTC («2026-08-13 17:44:12+00:00») — переводимо в місцевий
   час браузера, інакше цифра розходилась би з годинником на екрані. */
const fmtDT = v => {
  const t = Date.parse(String(v || "").replace(" ", "T"));
  if (isNaN(t)) return "";
  const d = new Date(t), p = n => String(n).padStart(2, "0");
  return `${p(d.getDate())}.${p(d.getMonth()+1)} ${p(d.getHours())}:${p(d.getMinutes())}`;
};
const dOf = v => { const m=/(\d{4})-(\d{2})-(\d{2})/.exec(String(v||"")); return m? new Date(+m[1],+m[2]-1,+m[3]) : null; };
/* Зміна дати прибуття. Трекер Maersk пише в «Зміни ETA (історія)» рядки виду
   «2026-07-15: ETA порт: 2026-05-19 → 2026-06-01 (Maersk)». Беремо ОСТАННІЙ
   рядок — він і показує, яка дата була і яка стала. */
const ETA_CHG_DAYS = 14;                    // за скільки днів зміна вважається свіжою
const etaChange = r => {
  const h = String(r["Зміни ETA (історія)"] || "").trim();
  if (!h) return null;
  const last = h.split("\n").map(x=>x.trim()).filter(Boolean).pop() || "";
  const m = /(\d{4}-\d{2}-\d{2})\s*→\s*(\d{4}-\d{2}-\d{2})/.exec(last);
  if (!m) return null;
  const w = /^(\d{4}-\d{2}-\d{2})/.exec(last);
  return { from: m[1], to: m[2], when: w ? w[1] : "" };
};
const etaChanged = r => {
  if (isDone(r)) return false;
  const c = etaChange(r);
  if (!c || !c.when) return false;
  const d = dOf(c.when);
  if (!d) return false;
  const t = new Date(); t.setHours(0,0,0,0);
  return Math.round((t - d) / 86400000) <= ETA_CHG_DAYS;
};
/* вантаж уже в порту прибуття і ще не вивезений → капають зберігання/демередж */
/* Статуси, за яких вантаж уже НЕ стоїть у порту прибуття — алерт про простій
   для них не має сенсу. «Вивантажений в сухому порту» додано 01.08.2026:
   без нього угоди 239 і 248 отримували червоне «немає авто», хоча контейнер
   давно виїхав із порту на внутрішній термінал. */
const GONE_STATUS = {"Завантажений на авто":1, "Завантажений на потяг":1,
                     "Вивантажений в сухому порту":1, "На кордоні":1};
const portSince = r => dOf(_s(r,"Вивантаження в порту (факт)") || _s(r,"ETA порт (факт)"));
const inPort = r => !isDone(r) && !_s(r,"Вивантаження у отримувача (факт)") &&
  !GONE_STATUS[_s(r,"Статус")] &&
  (!!portSince(r) || r["Статус"] === "Вивантажений в порту прибуття");
const daysIn = r => { const p=portSince(r); if(!p) return null;
  const t=new Date(); t.setHours(0,0,0,0); return Math.round((t-p)/86400000); };
/* Імпорт вивантажили в порту, минуло 2+ дні, а авто не подане й номера немає.
   Це СИГНАЛ ПЕРЕВІРИТИ, а не факт витрат: вільний час (free time) залежить від
   лінії, порту й напрямку, і на 2-й день зазвичай ще не вичерпаний
   (уточнення користувачки 01.08.2026). Облік строків демереджу й детеншену —
   окрема наступна задача. */
const truckDate = r => _s(r,"Подача авто (факт)") || _s(r,"Подача авто (план)");
/* ETD показуємо фактом, а якщо факту немає — планом із підписом «план» */
const etdOf = r => _s(r,"ETD (факт)") || _s(r,"ETD (план)");
/* Уточнення від користувачки 31.07.2026 — три обмеження, без них були хибні спрацювання:
   1) вантаж, уже завантажений на авто або на потяг, із порту поїхав — це не простій;
   2) авто ні до чого, якщо доставка не автомобільна (залізниця, авіа) — угода 227
      їхала потягом і потрапляла в алерт помилково;
   3) якщо в Експедиторі етап «ВыставленСчет» або «Завершена» — рахунок виставляють,
      як правило, вже ПІСЛЯ завантаження на авто, тобто вантаж вивезли, просто дані
      про авто в Експедитор не внесли (угоди 120 і 173 — саме цей випадок). */
const MOVED_STAGES = {"ВыставленСчет":1, "Завершена":1};
/* ВИМКНЕНО 01.08.2026 на прохання користувачки («поки прибери алерти з авто»).
   Причина: 2 дні без авто ще не означають витрат — вільний час залежить від
   лінії, порту й напрямку. Алерт повернемо разом з обліком строків демереджу
   й детеншену, коли будуть норми free time. Щоб увімкнути назад — поставити
   TRUCK_ALERT_ON = true, решта коду ціла: зникає і червона підсвітка рядка,
   і червоне «немає» в колонці «Авто», і плитка в смузі алертів. */
const TRUCK_ALERT_ON = false;
const truckLate = r => {
  if (!TRUCK_ALERT_ON) return false;
  if (isDone(r) || _s(r,"Напрямок") !== "Імпорт") return false;
  if (GONE_STATUS[_s(r,"Статус")]) return false;
  // з порту по землі везе потяг — авто тут ні до чого. Для авіа авто ПОТРІБНЕ
  // (уточнення користувачки 31.07.2026), тому відсікаємо тільки залізницю.
  if (/залізниц/i.test(_s(r,"Вид перевезення"))) return false;
  if (MOVED_STAGES[_s(r,"Етап (Експедитор)")]) return false;
  const dd = daysIn(r);
  return dd !== null && dd >= 2 && !truckDate(r) && !_s(r,"Номер авто");
};
/* Помилка менеджера: вантаж фізично вже поїхав (трекінг це бачить), а в Експедиторі
   угода досі на «Букинг» — менеджер не вніс зміни. Приклад: угода 227 —
   «Завантажений на потяг», а етап «Букинг». */
const STATUS_MOVED = {"Стафіровка":1,"В порту відправлення":1,"Завантажений на судно":1,
  "В морі":1,"В порту перевалки":1,"В порту призначення":1,"Вивантажений в порту прибуття":1,"Завантажений на потяг":1,
  "Завантажений на авто":1,"Вантаж доставлено":1};

/* ===== СТАТУС ЗАСТАРІВ І ТРЕКІНГ МОВЧИТЬ (05.08.2026) =====
   Привід — угода 256: у платформі «В морі», а Maersk віддавав 404 «немає даних»
   п'ять діб поспіль, і ETA (01.08) уже минула. Побачити це можна було тільки в
   журналі на сервері. Рішення користувачки: «позначати протухлі, не чіпаючи самі
   статуси» — тобто нічого не перезаписуємо, лише показуємо, де правда розійшлася
   з системою.

   ПОРІГ У 2 ДНІ — МІЙ, не її: «ETA минула» буквально означало б смітити на
   кожній угоді, що прибула вчора і чий статус просто ще не встигли оновити.
   Змінюється одним числом. */
const STALE_DAYS = 2;
/* Статуси, за яких вантаж ЩЕ В ДОРОЗІ: якщо такий статус висить, а дата прибуття
   давно минула, значить дані застаряли. «Вантаж доставлено» і «Скасована» сюди
   не входять — там нічого не протухає. */
const STATUS_ONWAY = {"Стафіровка":1,"В порту відправлення":1,"Завантажений на судно":1,
  "В морі":1,"В порту перевалки":1,"В порту призначення":1,"Завантажений на потяг":1,"Завантажений на авто":1};
const _days = iso => {
  const t = Date.parse(String(iso).slice(0,10) + "T00:00:00");
  return isNaN(t) ? 0 : Math.floor((Date.now() - t) / 86400000);
};
/* Скільки днів тому минула дата прибуття, якщо статус досі «в дорозі». 0 = все гаразд. */
/* Статуси, за яких вантаж УЖЕ ПРОЙШОВ порт і їде суходолом. Для них датою
   звірки має бути ETA СУХОГО ПОРТУ, а не портова: портова для них природно
   минула, і саме тому вона нічого не каже про застій.
   Причина (скарг користувачки 11.08.2026, чотири рядки поспіль): угода з
   «Завантажений на потяг» світилась «застаріло», хоча на потяг її завантажили
   напередодні. Портова ETA була 03.08 і минула 8 днів тому, а ETA сухого порту —
   10.08, тобто все йшло за планом. Правило звіряло з датою, яка для цього
   етапу вже не має значення, тому позначка не могла зникнути НІКОЛИ. */
const LAND_LEG = {"Завантажений на потяг":1,"Завантажений на авто":1,
  "Вивантажений в сухому порту":1,"На кордоні":1,"В порту призначення":1,
  "Вивантажений в порту прибуття":1};
/* Людина щойно підтвердила статус руками — це і є свіжі дані, «застаріло» тут
   немає чого показувати. Скарга користувачки 13.08.2026: «прибрати статуси
   застаріло, так як оновлення вже було зроблено руками».
   Правило дивиться на ті самі позначки, які фасад ставить при ручній правці
   (`Статус (джерело)` = «людина», `Статус (оновлено)` = дата) — тобто нічого
   нового вигадувати не треба, ці дві колонки ведуться з 05.08.2026.
   Вікно те саме, що й поріг застарілості: оновила два дні тому — ще свіжо,
   давніше — позначка повертається, бо вантаж і справді десь стоїть. */
const humanFresh = r => _s(r,"Статус (джерело)") === "людина"
  && !!_s(r,"Статус (оновлено)") && _days(_s(r,"Статус (оновлено)")) <= STALE_DAYS;
const staleStatus = r => {
  if (isDone(r) || _s(r,"Статус") === "Скасована") return 0;
  if (humanFresh(r)) return 0;
  if (!STATUS_ONWAY[_s(r,"Статус")]) return 0;
  const eta = (LAND_LEG[_s(r,"Статус")] && _s(r,"ETA сухий порт"))
              || _s(r,"ETA") || _s(r,"ETA порт (план)");
  if (!eta) return 0;
  const d = _days(eta);
  return d > STALE_DAYS ? d : 0;
};
/* Скільки днів трекінг лінії не дає даних. Позначку пише сам трекінг у колонку
   «Трекінг (стан)» у вигляді «Maersk: немає даних з 2026-08-04».

   ВАЖЛИВО: «інша лінія» сюди НЕ рахується. Це не збій і не мовчання — просто
   контейнер належить MSC/CMA/Hapag, і трекінг Maersk його бачити й не повинен.
   Холостий прогін 05.08.2026 показав 10 таких угод; якби вони підсвічувались як
   застарілі, позначка одразу втратила б сенс. */
const trackSilent = r => {
  const v = _s(r,"Трекінг (стан)");
  if (!v || !/(немає даних|збій)/i.test(v)) return 0;
  const m = v.match(/\d{4}-\d{2}-\d{2}/);
  return m ? Math.max(0, _days(m[0])) : 0;
};
const plural3 = (n,a,b,c) => (n%10===1&&n%100!==11) ? a : ((n%10>=2&&n%10<=4&&(n%100<10||n%100>=20)) ? b : c);

/* ===== КОМЕНТАР У КУТОЧКУ КЛІТИНКИ (як в Excel) =====
   Прохання користувачки 13.08.2026: «ці статуси ховати в коментарі, які
   відкриваються, якщо натиснути на куточок (як в екселі). Куточок можна зробити
   помаранчевий».
   Було: підписи «застаріло», «трекінг не відповідає», «було 02.08.26» друкувались
   прямо в клітинці другим рядком — вони робили рядок вищим і сперечалися за увагу
   з самими датами й статусами.
   Стало: у кутку клітинки маленький помаранчевий трикутник; клік — спливає текст.
   Класи `stalemark` і `wasdt` НАВМИСНО збережені: на них дивиться перевірка
   scripts/stale.js, і мовчки перейменувати їх означало б осліпити її. */
const noteMark = (cls, text) => text
  ? `<span class="cnote ${cls}" data-note="${esc(text)}" title="${esc(text)}"></span>` : "";

/* Одне спливаюче віконце на всю сторінку. Слухач вішається В РЕЖИМІ ЗАХОПЛЕННЯ
   і зупиняє подію: інакше клік по куточку дійшов би до самої клітинки й відкрив
   би редагування значення. */
function bindNotes(){
  if (window.__notesBound) return;
  window.__notesBound = true;
  const hide = () => { const p = $("notepop"); if (p) p.style.display = "none"; };
  document.addEventListener("click", e => {
    const c = e.target.closest && e.target.closest(".cnote, .cnote-line");
    if (!c) { hide(); return; }
    e.preventDefault(); e.stopPropagation();
    const p = $("notepop");
    if (!p) return;
    p.textContent = c.dataset.note || "";
    p.style.display = "block";
    // ставимо під куточком, але не даємо вилізти за край екрана
    const b = c.getBoundingClientRect(), w = p.offsetWidth || 240;
    p.style.left = Math.max(8, Math.min(b.left - w + 24, window.innerWidth - w - 8)) + "px";
    p.style.top  = (b.bottom + 6) + "px";
  }, true);
  document.addEventListener("keydown", e => { if (e.key === "Escape") hide(); });
  window.addEventListener("resize", hide);
}
/* Текст підказки — одним реченням, щоб було зрозуміло без пояснень. */
const staleWhy = r => {
  const st = staleStatus(r), sl = trackSilent(r), out = [];
  if (st) out.push(`статус «${_s(r,"Статус")}», а дата прибуття минула ${st} ${plural3(st,"день","дні","днів")} тому`);
  if (sl) out.push(`${_s(r,"Трекінг (стан)")} — мовчить ${sl} ${plural3(sl,"день","дні","днів")}`);
  const src = _s(r,"Статус (джерело)"), when = _s(r,"Статус (оновлено)");
  if (src || when) out.push(`статус поставив${src==="людина"?"ла":""} ${src||"невідомо хто"}${when?", "+fmtD(when):""}`);
  return out.join("; ");
};
/* ===== посилання на трекінг лінії =====
   Відкривається в браузері користувача, тому блокування нашого сервера
   сайтами ліній тут ролі не грає. Працює і по коносаменту, і по контейнеру. */
const TRACK_URL = {
  "Maersk":  n => "https://www.maersk.com/tracking/" + encodeURIComponent(n),
  /* MSC: перевірено 01.08.2026 — 5 форматів посилання, жоден не підставляє номер.
     Лишаємо відкриття сторінки трекінгу, номер доводиться вставляти вручну. */
  "MSC":     n => "https://www.msc.com/en/track-a-shipment?trackingNumber=" + encodeURIComponent(n),
  "CMA CGM": n => "https://www.cma-cgm.com/ebusiness/tracking/detail/" + encodeURIComponent(n),
  "HLC":     n => "https://www.hapag-lloyd.com/en/online-business/track/track-by-container-solution.html?container=" + encodeURIComponent(n),
  "COSCO":   n => "https://elines.coscoshipping.com/ebtracking/public/bill/" + encodeURIComponent(String(n).replace(/^COSU/i, "")),
  "EMC":     n => "https://www.shipmentlink.com/servlet/TDB1_CargoTracking.do?BL=" + encodeURIComponent(n),
};
const trackHref = (r, n) => { const f = TRACK_URL[_s(r, "Лінія")]; return (f && n) ? f(n) : ""; };
const trackLink = (r, n, cls) => {
  const href = trackHref(r, n);
  const txt = esc(n);
  return href ? `<a class="tl ${cls||""}" href="${esc(href)}" target="_blank" rel="noopener"
      title="відкрити трекінг ${esc(_s(r,"Лінія"))} по ${txt}">${txt}</a>`
    : `<span class="${cls||""}">${txt}</span>`;
};
/* ВИМКНЕНО 01.08.2026: «прибери цей фільтр, не важливо чи оновлено воно в
   Експедиторі». Перевірка порівнювала етап в Експедиторі («Букинг») зі статусом
   із трекінгу («В морі» тощо) — таких угод було 15. Щоб повернути, поставити
   STAGE_ALERT_ON = true: разом з ним повернуться і плитка в смузі алертів,
   і рядок у блоці «Потребує уваги» на дашборді, і бурштинова підсвітка. */
const STAGE_ALERT_ON = false;
const stageStale = r => STAGE_ALERT_ON &&
  _s(r,"Етап (Експедитор)") === "Букинг" && !!STATUS_MOVED[_s(r,"Статус")];
/* Експорт: дата заїзду в порт (Gate in) має стояти ОДРАЗУ після розміщення букінгу —
   по ній планують заїзд контейнера (вимога користувачки 01.08.2026). */
/* Статуси, за яких експорт УЖЕ ВІДПРАВЛЕНО. Після них дата заїзду в порт не має
   значення — вона потрібна лише щоб спланувати заїзд ДО завантаження
   (уточнення користувачки 01.08.2026 на угодах 251 і 260). */
const DEPARTED = {"Завантажений на судно":1, "В морі":1, "В порту перевалки":1, "В порту призначення":1,
                  "Вивантажений в порту прибуття":1,
                  "Завантажений на авто":1, "Завантажений на потяг":1,
                  "Вивантажений в сухому порту":1, "На кордоні":1, "Вантаж доставлено":1};
const gateInMissing = r => _s(r,"Напрямок") === "Експорт" && !isDone(r) && !_s(r,"Гейт ін")
  && !DEPARTED[_s(r,"Статус")] && !_s(r,"ETD (факт)");
let toastTimer=null;
function toast(m){ const t=$("toast"); t.textContent=m; t.style.display="block"; clearTimeout(toastTimer); toastTimer=setTimeout(()=>t.style.display="none",4000); }
/* Системне попередження — те, що НЕ можна показувати тостом на 4 секунди,
   бо воно пояснює, чому екран виглядає не так, як зазвичай. Тримається, доки
   не закриють. sysWarn("") прибирає смугу. */
function sysWarn(msg){
  const el = $("syswarn");
  if (!el) return;
  if (!msg){ el.innerHTML = ""; el.style.display = "none"; return; }
  el.innerHTML = `<span>⚠ ${esc(msg)}</span>
    <button type="button" id="syswarn-x" title="сховати">✕</button>`;
  el.style.display = "flex";
  const x = $("syswarn-x");
  if (x) x.addEventListener("click", ()=>sysWarn(""));
}

/* ===== сторінки ===== */
const PAGES = {};
let DISP_CACHE = null;
let DISP_QUICK = null;          // швидкий фільтр з плиток дашборда
/* Перемалювати таблицю диспетчеризації ззовні сторінки. Потрібно картці угоди:
   вона править той самий об'єкт рядка, але таблиця під нею вже намальована, тому
   без цього нове значення видно лише після оновлення сторінки (скарга користувачки
   14.08.2026: «не показувалася відразу, тільки після оновлення»).
   Ставиться при відкритті сторінки диспетчеризації, приймає Id рядка, щоб
   повернути його рівно туди, де він стояв на екрані. */
let DISP_REDRAW = null;
/* Оновлення червоних лічильників задач у таблиці БЕЗ перезаходу на сторінку.
   Зауваження користувачки 25.08.2026: «я закрила задачу, а кнопка з цифрою
   залишилась». Ставиться в PAGES.dispatch; смикається з saveTask() — єдиного
   шляху запису задач, тож ловить і закриття, і створення, і зміну, звідки б
   вони не робились (сторінка задач, картка угоди, картка задачі). */
let DISP_TASKS_REFRESH = null;
/* Скасована угода не існує для роботи (правило користувачки 01.08.2026): не показуємо
   її ніде — ні в таблиці диспетчеризації, ні на дашборді, ні в лічильниках чи алертах.
   Фільтр стоїть в ОДНОМУ місці — усі сторінки беруть дані через dispRows().
   У списку STATUSES цього статусу навмисно немає, тому він не з'являється ні у
   випадайці фільтра, ні у виборі статусу в картці угоди. */
const CANCELLED_ST = "Скасована";
/* МІСЦЕ ПІД РЕДАКТОРОМ. Календар у <input type="date"> і список у <select>
   малює САМ БРАУЗЕР, і відкриваються вони вниз від поля — їхньою позицією ми
   не керуємо. Для останніх рядків таблиці це означало, що дату неможливо
   вибрати: календар вилазив за нижній край екрана (зауваження користувачки
   14.08.2026, угода 282).
   Тому перед відкриттям редактора дивимось, чи лишається під клітинкою місце
   на календар, і якщо ні — підкручуємо так, щоб вона стала по центру.
   scrollIntoView сам прокручує потрібного предка, тобто і власну прокрутку
   таблиці (#dscroll), і сторінку.
   Прокрутка МИТТЄВА, не smooth: фокус ставиться одразу після, і плавна
   анімація відкрила б календар ще на старому місці. */
function roomForEditor(el, need){
  try{
    const r = el.getBoundingClientRect();
    if (window.innerHeight - r.bottom < (need || 330))
      el.scrollIntoView({block: "center", behavior: "auto"});
  }catch(e){ /* дуже старий браузер — просто лишаємо як є */ }
}

async function dispRows(){
  if (!DISP_CACHE) DISP_CACHE = (await loadAll(T["Диспетчеризація"]))
    .filter(r => String(r["Статус"] || "").trim() !== CANCELLED_ST);
  return DISP_CACHE;
}

PAGES.dashboard = async () => {
  const rows = scoped(await dispRows());
  const active = rows.filter(r=>r["Статус"]!=="Вантаж доставлено");
  const today = new Date(); today.setHours(0,0,0,0);
  const d = v => { const m=/(\d{4})-(\d{2})-(\d{2})/.exec(String(v||"")); return m? new Date(+m[1],+m[2]-1,+m[3]) : null; };
  const sea = active.filter(r=>r["Статус"]==="В морі").length;
  const week = active.filter(r=>{ const e=d(r["ETA"]); return e && (e-today)/86400000>=0 && (e-today)/86400000<=7; }).length;
  const noBL = active.filter(r=>needsBL(r) && !shipDoc(r)).length;
  /* Розрахунки «скільки днів стоїть у порту» і «ETA минула» прибрані 01.08.2026.
     Це були МОЇ припущення про терміни вивозу — користувачка їх не задавала:
     «я тобі взагалі не задавала терміни». Повернуться разом з обліком демереджу
     й детеншену, коли будуть норми free time по лініях і портах. */
  const fmtRow = r => `<tr><td class="mono"><b>${esc(r["Угода"])}</b></td><td>${esc(r["Клієнт"]||"—")}</td>
    <td>${esc(r["Судно"]||"—")}</td><td>${stPill(r["Статус"])}</td><td class="mono">${dateB(r["ETA"])}</td></tr>`;
  const upcoming = active.filter(r=>{ const e=d(r["ETA"]); return e && e>=today; })
    .sort((a,b)=>String(a["ETA"]).localeCompare(String(b["ETA"]))).slice(0,8);
  const scopeNote = cfg().scope!=="all" ? `<div class="note">👤 Показано лише твої угоди (${esc(UNAME)}).</div>` : "";

  /* ── мої задачі: нагадування прямо на дашборді (вимога користувачки 12.08.2026)
     Задачі не мають права завалити дашборд: якщо їх не вдалося прочитати —
     кажемо про це в самому блоці, а решта сторінки малюється як звичайно. */
  let myTasks = [], tUsers = [], tasksErr = "";
  try {
    myTasks = (await taskRows()).filter(t=>isMyTask(t) && taskIsOpen(t));
    try { tUsers = await taskUsers(); } catch(e){ tUsers = []; }
  } catch(e){ tasksErr = e.message || "збій зв'язку"; }
  const tOver  = myTasks.filter(t=>{ const n=taskDays(t); return n!==null && n<0; });
  const tToday = myTasks.filter(t=>taskDays(t) === 0);
  const tSoon  = myTasks.filter(t=>{ const n=taskDays(t); return n!==null && n>0 && n<=remindOf(t); });
  const tNear  = [...tOver, ...tToday, ...tSoon]
    .concat(myTasks.filter(t=>{ const n=taskDays(t); return n!==null && n>remindOf(t) && n<=7; }))
    .filter((v,i,a)=>a.indexOf(v)===i).slice(0, 8);

  // розподіл по лініях — лише там, де лінія взагалі буває:
  // морські + залізничні + мультимодальні на FOB/CIF («ТЕО+авто»). Авіа й авто не рахуємо.
  const lineRows = rows.filter(hasLine);
  const notClassified = rows.length - lineRows.length
    - rows.filter(r=>{ const m=_s(r,"Вид перевезення"); return m==="авіа"||m==="авто"; }).length;
  const byLine = {};
  lineRows.forEach(r=>{ const l = _s(r,"Лінія") || "Без лінії"; byLine[l] = (byLine[l]||0)+1; });
  const lineNames = Object.keys(byLine).sort((a,b)=>byLine[b]-byLine[a]);
  // прибуття по місяцях — УСІ місяці, у яких є ETA (від першого до останнього, без пропусків)
  const MON = ["січ","лют","бер","кві","тра","чер","лип","сер","вер","жов","лис","гру"];
  const monKeys = [...new Set(rows.map(r=>String(r["ETA"]||"").slice(0,7)))].filter(k=>/^\d{4}-\d{2}$/.test(k)).sort();
  const months = [];
  if (monKeys.length){
    const a = monKeys[0].split("-").map(Number), b = monKeys[monKeys.length-1].split("-").map(Number);
    let y = a[0], m = a[1];
    while (y < b[0] || (y === b[0] && m <= b[1])){ months.push([y, m-1]); m++; if (m > 12){ m = 1; y++; } }
  }
  const monCount = {};
  rows.forEach(r=>{ const k=String(r["ETA"]||"").slice(0,7); if(/^\d{4}-\d{2}$/.test(k)) monCount[k]=(monCount[k]||0)+1; });
  const byMonth = months.map(([y,m])=> monCount[y+"-"+String(m+1).padStart(2,"0")] || 0);
  // статуси
  const byStatus = {};
  active.forEach(r=>{ const s = r["Статус"] || "Без статусу"; byStatus[s] = (byStatus[s]||0)+1; });
  // порядок — за етапом перевезення, а не за кількістю: вивантаження в порту
  // ЗАВЖДИ перед завантаженням на потяг/авто (вимога користувачки)
  // «В порту призначення» додано 11.08.2026: у цьому переліку його НЕ БУЛО від самого
  // створення статусу (05.08), тому такі угоди падали в кінець як невідомі. Помітно
  // не було лише тому, що статус не стояв у жодної угоди.
  const STAGE_ORDER = ["Букінг","Виконується","Стафіровка","В порту відправлення","Завантажений на судно",
    "В морі","В порту перевалки","В порту призначення","Вивантажений в порту прибуття","Завантажений на потяг","Завантажений на авто",
    "Вантаж доставлено","Без статусу"];
  const stNames = Object.keys(byStatus).sort((a,b)=>{
    const ia=STAGE_ORDER.indexOf(a), ib=STAGE_ORDER.indexOf(b);
    return (ia<0?99:ia)-(ib<0?99:ib) || byStatus[b]-byStatus[a];
  });
  const maxSt = Math.max(1, ...stNames.map(s=>byStatus[s]));
  // розподіл по видах перевезення
  const byMode = {};
  rows.forEach(r=>{ const v=_s(r,"Вид перевезення"); if(v) byMode[v]=(byMode[v]||0)+1; });
  const modeNames = Object.keys(byMode).sort((a,b)=>byMode[b]-byMode[a]);
  const noMode = rows.filter(r=>!_s(r,"Вид перевезення")).length;
  const maxMode = Math.max(1, ...modeNames.map(m=>byMode[m]));
  // FCL / LCL — тільки морські: FCL = є номер контейнера, LCL = позначено «Збірний»
  const seaRows = rows.filter(isSea);
  const lcl = rows.filter(isLCL).length;
  const fcl = seaRows.filter(r=>_s(r,"Контейнер") && !isLCL(r)).length;
  const seaNoCont = seaRows.filter(r=>!_s(r,"Контейнер") && !isLCL(r)).length;
  // у діаграму йдуть ЛИШЕ FCL і LCL; морські без номера контейнера — це прогалина
  // в даних, вона живе в блоці «Потребує уваги», а не окремим сегментом
  const loadNames = [], loadVals = [];
  if (fcl) { loadNames.push("FCL"); loadVals.push(fcl); }
  if (lcl) { loadNames.push("LCL"); loadVals.push(lcl); }

  // ── блок «потребує уваги»: помилки й прогалини в даних
  const stale = rows.filter(r=>{ const u=dOf(_s(r,"Останнє оновлення")||_s(r,"Остання зміна"));
    return !isDone(r) && u && (today-u)/86400000 > 7; }).length;
  const ISSUES = [
    {q:"trucklate", crit:true, nm:"Імпорт у порту, а авто не подане понад 2 дні", n: rows.filter(truckLate).length,
     sub:"немає ні дати подачі авто, ні номера — вантаж стоїть, капає зберігання"},
    {q:"nogatein", crit:true, nm:"Експорт без дати заїзду в порт (Gate in)", n: rows.filter(gateInMissing).length,
     sub:"дата має стояти одразу після букінгу — по ній планують заїзд контейнера"},
    {q:"stagestale", crit:true, nm:"Менеджер не оновив угоду в Експедиторі", n: rows.filter(stageStale).length,
     sub: (()=>{ const m=[...new Set(rows.filter(stageStale).map(r=>_s(r,"Менеджер")).filter(Boolean))];
       return "вантаж уже їде, а етап досі «Букинг»" + (m.length? " · " + m.join(", ") : ""); })()},
    {q:"nostatus", nm:"Без статусу", n: rows.filter(r=>!_s(r,"Статус")).length,
     sub:"етап в Експедиторі є, але ми його ще не мапимо в статус платформи"},
    {q:"nobl", nm:"Без коносамента / авіанакладної", n: noBL,
     sub:"трекінг не вмикається. Авто в цей рахунок не входить — там документа перевезення не буває"},
    {q:"noeta", nm:"Без ETA", n: rows.filter(r=>!_s(r,"ETA")).length,
     sub:"немає дати прибуття — угода не потрапляє в план і в сортування"},
    {q:"nocont", nm:"Без номера контейнера", n: rows.filter(r=>needsCont(r) && !_s(r,"Контейнер")).length,
     sub:"тільки морські — при авіа та авто контейнера не буває"},
    {q:"noline", nm:"Без лінії (морські й залізничні)", n: lineRows.filter(r=>!_s(r,"Лінія")).length,
     sub:"невідомо, чиїм трекінгом тягнути дані"},
    {q:"nomode", nm:"Без виду перевезення", n: noMode,
     sub:"не потрапляє в розподіли по видах і в FCL/LCL"},
    {q:"stale", nm:"Не оновлювалось понад 7 днів", n: stale,
     sub:"активна угода, а даних з Експедитора чи трекінгу давно не було"},
  ].sort((a,b)=> (b.crit && b.n ? 1:0) - (a.crit && a.n ? 1:0) || b.n-a.n);
  const issRow = i => `<div class="issrow clickable" data-jump="${i.q}" title="показати ці угоди в диспетчеризації">
      <span class="dotw" style="background:${i.n? ((i.crit||i.n>=30)? "#d1453b" : "#e6a817") : "#1a8f5c"}"></span>
      <span class="nm">${esc(i.nm)}<small>${esc(i.sub)}</small></span>
      <span class="cnt" style="color:${i.n? ((i.crit||i.n>=30)? "#d1453b" : "var(--ink)") : "#1a8f5c"}">${i.n||"✓"}</span>
      <span class="go">${i.n? "›" : ""}</span></div>`;

  $("content").innerHTML = `
    ${scopeNote}
    <div class="tiles">
      <div class="tile clickable" data-jump="active"><div class="lbl">📦 Активні перевезення</div><div class="val">${active.length}</div><div class="delta">з ${rows.length} угод усього</div></div>
      <div class="tile clickable" data-jump="sea"><div class="lbl">🌊 В морі зараз</div><div class="val">${sea}</div><div class="delta">${active.length? Math.round(sea/active.length*100):0}% активних</div></div>
      <div class="tile clickable" data-jump="eta7"><div class="lbl">📅 Прибуття за 7 днів</div><div class="val">${week}</div><div class="delta">потребують уваги</div></div>
      <div class="tile clickable${tOver.length?" warn":""}" data-jump="tasks"><div class="lbl">🔔 Мої задачі — нагадування</div>
        <div class="val">${tOver.length + tToday.length}</div>
        <div class="delta">${tasksErr ? "дані не завантажились"
          : tOver.length + " " + plural(tOver.length,"прострочена","прострочені","прострочених") +
            ", " + tToday.length + " на сьогодні"}</div></div>
    </div>

    <div class="dashgrid">
      <div class="card"><h3>🔔 Мої задачі</h3>
        <p class="sub">${tasksErr ? "не завантажились" : "прострочені, на сьогодні й ті, що скоро нагадають"}</p>
        <div class="scrollbox">${
          tasksErr ? `<p class="sub">⚠ ${esc(tasksErr)} — онови сторінку.</p>`
          : tNear.length ? `<div class="tasklist">${tNear.map(t=>taskRowHtml(t, tUsers)).join("")}</div>`
          : '<p class="sub" style="margin-top:8px">Відкритих задач на найближчі дні немає.</p>'}</div></div>

      <div class="card"><h3>📊 Прибуття по місяцях</h3><p class="sub">кількість угод за датою ETA${monKeys.length? ` · ${MON[months[0][1]]} ${String(months[0][0]).slice(2)} — ${MON[months[months.length-1][1]]} ${String(months[months.length-1][0]).slice(2)}`:""}</p>
        <div class="chartbox"><canvas id="ch-months"></canvas></div></div>

      <div class="card"><h3>🚚 Розподіл по видах перевезення</h3>
        <p class="sub">${modeNames.length? `усі угоди${noMode? `; без виду перевезення — ${noMode}`:""}` : "поле «Вид перевезення» ще не заповнене"}</p>
        ${modeNames.length? '<div class="chartbox"><canvas id="ch-modes"></canvas></div>' :
          '<p class="sub" style="margin-top:12px">Заповни «Вид перевезення» в угодах — і розподіл з’явиться тут.</p>'}</div>

      <div class="card"><h3>📦 FCL / LCL</h3>
        ${loadNames.length? '<div class="chartbox"><canvas id="ch-loads"></canvas></div>' :
          '<p class="sub" style="margin-top:12px">FCL — морська угода з номером контейнера, LCL — позначена як «Збірний».</p>'}</div>

      <div class="card"><h3>🚢 Розподіл по лініях</h3>
        <p class="sub">морські + залізничні + FOB/CIF — ${lineRows.length} угод${notClassified? `; не класифіковано — ${notClassified}`:""}</p>
        <div class="chartbox"><canvas id="ch-lines"></canvas></div></div>

      <div class="card"><h3>📈 Статуси активних перевезень</h3><p class="sub">де зараз вантажі</p>
        <div class="scrollbox" style="display:flex;flex-direction:column;gap:8px;margin-top:4px">
          ${stNames.map(s=>`<div class="strow" data-jump="st:${s==="Без статусу"?"":esc(s)}" title="показати ці угоди в диспетчеризації">
            <div style="min-width:150px;font-size:12px">${s==="Без статусу"? '<span class="pill t-crit">Без статусу</span>' : stPill(s)}</div>
            <div style="flex:1;background:var(--neutral-bg);border-radius:8px;height:9px;overflow:hidden">
              <div style="width:${Math.round(byStatus[s]/maxSt*100)}%;height:100%;background:${s==="Без статусу"?"#d1453b":"var(--accent)"};border-radius:8px"></div></div>
            <b style="min-width:30px;text-align:right;font-size:13px">${byStatus[s]}</b>
            <span style="color:var(--muted);font-size:13px">›</span></div>`).join("") ||
            '<p class="sub">Активних перевезень немає.</p>'}
        </div></div>

      <div class="card"><h3>📅 Найближчі прибуття</h3><p class="sub">активні угоди за ETA, від найближчої</p>
        <div class="scrollbox"><table>
          <thead><tr><th>Угода</th><th>Клієнт</th><th>Статус</th><th>ETA</th></tr></thead>
          <tbody>${upcoming.map(r=>`<tr><td class="mono"><b>${esc(r["Угода"])}</b></td><td>${esc(r["Клієнт"]||"—")}</td><td>${stPill(r["Статус"])}</td><td class="mono">${dateB(r["ETA"])}</td></tr>`).join("")
            || '<tr><td colspan="4" class="cell-muted">Немає активних угод з майбутнім ETA.</td></tr>'}</tbody>
        </table></div></div>
    </div>

    <div class="card" style="margin-top:12px"><h3>⚠️ Потребує уваги — помилки й прогалини в даних</h3>
      <p class="sub">натисни рядок, щоб побачити ці угоди в диспетчеризації</p>
      <div class="isslist">${ISSUES.map(issRow).join("")}</div></div>

`;

  const DONUT = {maintainAspectRatio:false, cutout:"60%",
    plugins:{ legend:{position:"right", labels:{boxWidth:8, boxHeight:8, usePointStyle:true,
      pointStyle:"circle", padding:7, font:{size:10.5}}} }};
  const PALETTE = [CH.blue, CH.green, CH.amber, CH.violet, CH.red, CH.slate, "#0ea5e9", "#f472b6", "#14b8a6", "#a3e635"];

  drawChart("ch-months", {
    type:"bar",
    // рік у другому рядку підпису — інакше не видно, де січень міняє рік
    data:{ labels: months.map(([y,m])=>[MON[m], "’"+String(y).slice(2)]),
      datasets:[{ data: byMonth, backgroundColor: CH.blue, borderRadius:5, maxBarThickness:30 }] },
    options:{ maintainAspectRatio:false, plugins:{legend:{display:false}},
      scales:{ y:{beginAtZero:true, ticks:{precision:0, font:{size:10}}, grid:{color:"rgba(148,163,184,.18)"}},
               x:{grid:{display:false}, ticks:{font:{size:10}}} } }
  });
  drawChart("ch-lines", {
    type:"doughnut",
    data:{ labels: lineNames, datasets:[{ data: lineNames.map(l=>byLine[l]),
      backgroundColor: PALETTE, borderWidth:0, hoverOffset:6 }] },
    options: DONUT
  });
  if (modeNames.length) drawChart("ch-modes", {
    type:"doughnut",
    data:{ labels: modeNames, datasets:[{ data: modeNames.map(m=>byMode[m]),
      backgroundColor: PALETTE, borderWidth:0, hoverOffset:6 }] },
    options: DONUT
  });
  if (loadNames.length) drawChart("ch-loads", {
    type:"doughnut",
    data:{ labels: loadNames, datasets:[{ data: loadVals,
      backgroundColor:[CH.blue, CH.green, CH.slate], borderWidth:0, hoverOffset:6 }] },
    options: DONUT
  });
  $("content").querySelectorAll("[data-jump]").forEach(t=>t.addEventListener("click",()=>{
    if (t.classList.contains("issrow") && !t.classList.contains("clickable")) return;
    if (t.dataset.jump === "tasks"){ go("tasks"); return; }   // нагадування ведуть у «Задачі»
    DISP_QUICK = t.dataset.jump; go("dispatch");
  }));
  /* Рядок задачі на дашборді відкриває саму задачу, а не диспетчеризацію. */
  $("content").querySelectorAll(".taskrow[data-task]").forEach(el=>el.addEventListener("click", e=>{
    if (e.target.closest("[data-done]")) return;
    const t = myTasks.find(x=>String(x.Id) === el.dataset.task);
    if (t) openTask(t, {});
  }));
  enhanceTiles();
};

const FLAGS = ["Телекс","Т1","ДО","Документи","SI","Замитнення","Реліз"];
PAGES.dispatch = async () => {
  DISP_CACHE = null;
  const all = scoped(await dispRows());
  // ПОРЯДОК (правило 31.07.2026, уточнене 01.08.2026):
  //   1) «Вантаж доставлено» — вгорі, за шапкою (їх не видно, таблиця прокручена нижче);
  //   2) решта — за КЛЮЧОВОЮ ДАТОЮ напрямку: імпорт і транзит по ETA, експорт по ETD.
  //      Чим раніше — тим вище. Жодних інших груп.
  //   3) угоди без ключової дати — у самий низ (планувати нічого).
  // Чому по-різному: у рядку підсвічена саме ключова дата напрямку, і порядок
  // має збігатися з тим, на що дивиться око.
  /* Ключова дата угоди: для ЕКСПОРТУ це відправлення (ETD), для імпорту й
     транзиту — прибуття (ETA). Рішення користувачки 01.08.2026: сортування має
     збігатися з тим, що підсвічено в рядку, інакше око бачить один порядок,
     а список побудований за іншим. ETD беремо так само, як показуємо в таблиці:
     фактичний, а поки його немає — плановий. */
  const _key = r => { const v = _s(r,"Напрямок") === "Експорт" ? etdOf(r) : String(r["ETA"] || "");
    const m = /(\d{4})-(\d{2})-(\d{2})/.exec(v); return m ? (m[1]+m[2]+m[3]) : ""; };
  /* ЗАДАЧІ ПРОСТО В ТАБЛИЦІ УГОД (прохання користувачки 25.08.2026: «щоб задачі
     були видні по угодам на загальному екрані Диспетчеризації»). У вузький рядок
     повні тексти не вміщаються, тому під номером угоди — чіп «📌 N» з кількістю
     ВІДКРИТИХ задач; є прострочені — чіп червоний і в ньому «!». Назви задач і
     терміни — у підказці при наведенні, повний список — у картці угоди (клік по
     рядку). Якщо задачі не завантажились — таблиця живе без чіпів, це не привід
     її не показувати. */
  let TASKS_BY_DEAL = {};
  const buildTaskMap = async (force) => {
    const map = {};
    for (const t of (await taskRows(force)).filter(t => String(t["Тип"]) === "Угода" && taskIsOpen(t))){
      const n = String(t["Угода"] || "").trim();
      if (n) (map[n] = map[n] || []).push(t);
    }
    TASKS_BY_DEAL = map;
  };
  try{ await buildTaskMap(true); }catch(e){ TASKS_BY_DEAL = {}; }
  /* Вигляд за уточненням користувачки 25.08.2026: «прибери кнопку, просто
     червоним виділяй кількість задач» — жодного чіпа-кнопки, лише червоне число
     під номером угоди. Назви й терміни — у підказці, повний список — у картці. */
  const taskChip = r => {
    const list = TASKS_BY_DEAL[String(r["Угода"] || "").trim()] || [];
    if (!list.length) return "";
    const tip = list.map(t => "• " + String(t["Задача"] || "") +
      (t["Термін"] ? " (до " + fmtD(t["Термін"]) + ")" : "")).join("\n");
    return `<span class="taskn" title="${esc(tip)}\n\nклік по рядку відкриє картку угоди з задачами">${list.length} ${plural(list.length, "задача", "задачі", "задач")}</span>`;
  };
  const _done = r => r["Статус"] === "Вантаж доставлено";
  const _num = r => parseInt(r["Угода"])||0;
  /* Просування вантажу — потрібне ЛИШЕ для угод БЕЗ ключової дати. Там раніше
     сортувало просто за номером, тому «Букінг» 193 ставав вище за «Виконується»
     194 (зауваження користувачки 01.08.2026: «не може бути угода зі статусом
     Букінг перед угодою В морі або Виконується»). Тепер серед таких угод
     спершу ті, що просунулись далі. */
  /* «В порту призначення» додано 11.08.2026 — його тут не було з 05.08, тому такі
     угоди отримували ранг −1 і сортувались як «без статусу». Ставимо між «В морі»
     і «Вивантажений в порту прибуття»: судно вже прийшло, але вантаж ще на борту. */
  const ST_RANK = {"Букінг":0, "Виконується":1, "Стафіровка":2, "В порту відправлення":3,
    "Завантажений на судно":4, "В морі":5, "В порту перевалки":6, "В порту призначення":7,
    "Вивантажений в порту прибуття":8,
    "Завантажений на авто":9, "Завантажений на потяг":9, "Вивантажений в сухому порту":10,
    "На кордоні":11, "Вантаж доставлено":12};
  const _rank = r => { const v = ST_RANK[_s(r,"Статус")]; return v === undefined ? -1 : v; };
  all.sort((a,b)=>{
    /* Доставлені — ПЕРШИМИ у списку, а таблиця прокручується так, щоб зверху
       на екрані стояв перший активний вантаж. Тобто доставлені нікуди не
       діваються — вони «під шапкою», прокрути вгору і вони там.
       Історія: 02.08 їх згорнули під смужку «▸ Доставлені (N)», бо здавалося,
       що прокрутка не тримається. 03.08.2026 користувачка не побачила 229 угод
       із 267 («в таблиці вказані не всі перевезення») — смужка не показувалась
       узагалі, коли фільтр відсікав доставлених. Її слова: «вище, а не в кінці,
       як і було, все працювало раніше». Повернуто саме той механізм. */
    /* НА ТЕЛЕФОНІ порядок зворотний. Причина технічна: там таблиця не має
       власної прокрутки (.dispscroll{overflow:visible}) — прокручується вся
       сторінка, тому «сховати доставлених під шапку» неможливо в принципі,
       і при звичайному порядку телефон відкривався б на 229 доставлених.
       Тому на телефоні вони йдуть ПІСЛЯ активних: відкриваєш — бачиш активні,
       прокручуєш вниз — доставлені. На комп'ютері все як було. */
    const ph = isPhone();
    const ra = _done(a) ? (ph?1:0) : (ph?0:1), rb = _done(b) ? (ph?1:0) : (ph?0:1);
    if (ra !== rb) return ra - rb;
    const ea=_key(a), eb=_key(b);
    if (!ea && !eb) return (_rank(b) - _rank(a)) || (_num(a) - _num(b));
    if (!ea) return 1;                       // без ключової дати — у самий низ
    if (!eb) return -1;
    return ea.localeCompare(eb) || _num(a)-_num(b);   // чим раніше — тим вище
  });
  // швидкий фільтр із плиток дашборда (клік по плитці → сюди з готовим відбором)
  const _dt = v => { const m=/(\d{4})-(\d{2})-(\d{2})/.exec(String(v||"")); return m? new Date(+m[1],+m[2]-1,+m[3]) : null; };
  const _today = new Date(); _today.setHours(0,0,0,0);
  /* НОВІ УГОДИ. Навіщо (04.08.2026): користувачка прокрутила таблицю донизу,
     побачила останнім рядком угоду 271 і сказала «в мене остання угода 271» —
     хоча 272 і 273 були в таблиці, у рядках 248 і 249. Причина не в даних:
     таблиця впорядкована за КЛЮЧОВОЮ ДАТОЮ (її ж рішення 01.08.2026), а угоди
     без ETA йдуть у самий низ. Тому «останній рядок» ≠ «найновіша угода»:
     271 стояв останнім саме тому, що в нього немає ETA.
     Порядок не міняю — його обрала користувачка. Натомість роблю новизну
     ВИДИМОЮ: позначка «нова» біля номера і окремий швидкий відбір. */
  const NEW_DAYS = 7;
  const _isNew = r => { const c = dOf(String(r["CreatedAt"]||"").slice(0,10));
    return !!c && (_today - c)/86400000 <= NEW_DAYS; };
  const QUICK = {
    fresh:{label:"нові угоди (за "+NEW_DAYS+" днів)", test:_isNew},
    active:{label:"активні перевезення", test:r=>!_done(r)},
    sea:{label:"в морі зараз", test:r=>r["Статус"]==="В морі"},
    eta7:{label:"прибуття за 7 днів", test:r=>{ if(_done(r)) return false; const e=_dt(r["ETA"]);
      if(!e) return false; const dd=(e-_today)/86400000; return dd>=0 && dd<=7; }},
    nobl:{label:"без коносамента / авіанакладної", test:r=>!_done(r) && needsBL(r) && !shipDoc(r)},
    inport:{label:"у порту — не вивезено", test:inPort},
    etachg:{label:"змінилася дата прибуття", test:etaChanged},
    nostatus:{label:"без статусу", test:r=>!_s(r,"Статус")},
    noeta:{label:"без ETA", test:r=>!_s(r,"ETA")},
    overdue:{label:"ETA минула, угода не закрита", test:r=>{ if(_done(r)) return false;
      const e=_dt(r["ETA"]); return !!e && e<_today; }},
    nocont:{label:"без номера контейнера", test:r=>needsCont(r) && !_s(r,"Контейнер")},
    noline:{label:"без лінії (морські й залізничні)", test:r=>hasLine(r) && !_s(r,"Лінія")},
    nomode:{label:"без виду перевезення", test:r=>!_s(r,"Вид перевезення")},
    stale:{label:"не оновлювалось понад 7 днів", test:r=>{ if(_done(r)) return false;
      const u=dOf(_s(r,"Останнє оновлення")||_s(r,"Остання зміна"));
      return !!u && (_today-u)/86400000 > 7; }},
    trucklate:{label:"імпорт у порту без авто понад 2 дні", test:truckLate},
    stagestale:{label:"менеджер не оновив етап в Експедиторі", test:stageStale},
    nogatein:{label:"експорт без дати заїзду в порт", test:gateInMissing},
  };
  // «st:<назва>» — клік по рядку статусу на дашборді; порожня назва = без статусу
  let quick = QUICK[DISP_QUICK] || null;
  if (!quick && String(DISP_QUICK || "").startsWith("st:")){
    const s = DISP_QUICK.slice(3);
    quick = s ? {label:"статус: "+s, test:r=>_s(r,"Статус")===s}
              : {label:"без статусу", test:r=>!_s(r,"Статус")};
  }
  const quickCount = quick ? all.filter(quick.test).length : all.length;
  const logist = cfg().cols === "logist";
  // РЕДАГУВАННЯ ПРЯМО В ТАБЛИЦІ. Редаговані лише ті поля, які синхронізація з
  // Експедитора НЕ затирає (політика «не чіпати чуже»), плюс «Статус» — його
  // Експедитор перезаписує лише для етапів Завершена / Букинг / Выполняется.
  const CAN_EDIT = !!cfg().edit;
  const ED = CAN_EDIT ? " ed" : "";
  const ED_KIND = {"ETA":"date", "ETD (факт)":"date", "Гейт ін":"date",
                   "Подача авто (факт)":"date", "Перетин кордону (факт)":"date",
                   "ETA сухий порт":"date", "Gate out for delivery":"date", "Stuffing":"date",
                   "Здача в порт (факт)":"date",
                   "Статус":"select", "Вид перевезення":"select"};
  // варіанти для випадайок у таблиці — свої для кожної колонки
  const ED_OPTS = {"Статус": ()=>Object.keys(STATUSES), "Вид перевезення": ()=>MODE_OPTIONS};
  /* Підпис під кнопкою — те саме, що у «Фінансах» і «Бух. обліку»: видно, чи
     оновилося і коли. Раніше тут був лише тост на 4 секунди, і при обриві
     запиту людина взагалі нічого не бачила (04.08.2026). */
  const syncBtn = cfg().sync
    ? '<span style="display:inline-flex;align-items:center;gap:8px">'
      + '<button class="btn" id="sync-btn">⟳ Оновити</button>'
      + '<span id="disp-note"></span></span>'
    : "";
  /* КОЛИ ДАНІ ОНОВЛЮВАЛИСЬ — угорі, поруч із кнопкою (прохання користувачки
     13.08.2026: «немає дати та часу оновлення зверху»). Позначка внизу меню —
     це версія САМОЇ СТОРІНКИ, а не свіжість даних, і плутати їх не можна.
     Беремо найсвіжіший `UpdatedAt` серед угод: його веде сама база при кожному
     записі, тож він показує реальний час останньої зміни в таблиці — і від
     синхронізації, і від ручної правки. Колонка «Останнє оновлення» для цього
     не годиться: у ній лише дата без часу, а подекуди й текст
     («2026-07-03 (статус з Експедитора: закрито)»). */
  const upd = all.map(r => String(r["UpdatedAt"] || r["CreatedAt"] || "")).filter(Boolean).sort().pop();
  const updHtml = upd
    ? `<span class="updstamp" title="найсвіжіша зміна в таблиці угод — від синхронізації або від руки">`
      + `оновлено ${esc(fmtDT(upd))}</span>`
    : `<span class="updstamp cell-muted">час оновлення невідомий</span>`;
  const head = logist
    ? "<th>Угода</th><th>Клієнт</th><th>Контейнер</th><th>Статус</th><th>Номер авто</th><th>Водій</th><th>Телефон</th><th>Перетин кордону</th><th></th>"
    : "<th class=\"c-num\">Угода</th><th></th><th>Клієнт</th><th>Маршрут</th><th>Вид / лінія</th><th class=\"c-bl\">Коносамент /<br>контейнер</th><th class=\"c-ves\">Судно</th><th class=\"dt\">Stuffing</th><th class=\"dt\">Gate in /<br>здача</th><th class=\"dt\">ETD POL</th><th class=\"dt\">ETA POD</th><th class=\"dt\">ETA<br>dry port</th><th class=\"dt\">Gate out<br>delivery</th><th>Статус</th><th class=\"c-rel\" title=\"Реліз: галочка ставиться кліком прямо в таблиці\">Реліз</th><th>Авто</th><th>Коментар</th><th></th>";
  // ── активні алерти над таблицею
  const uniq = k => [...new Set(all.map(r=>_s(r,k)).filter(Boolean))].sort((a,b)=>a.localeCompare(b,"uk"));
  const nActive = all.filter(r=>!_done(r)).length;
  /* Прибрано 01.08.2026: «Стоять у порту» і «ETA минула». Обидві плитки були
     МОЇМ припущенням про терміни вивозу, а не правилом компанії. Користувачка:
     «більшість вантажів тільки прибули, їх ще не встигли ні розмитнити ні
     доставити — прибери терміни, які ти сам собі виставив по вивозу».
     Повернемо разом з обліком демереджу й детеншену, коли будуть норми free time. */
  const ALERTS = [
    {q:"trucklate", cls:"a-red",   nm:"У порту без авто >2дн", n: all.filter(truckLate).length},
    {q:"stagestale",cls:"a-red",   nm:"Етап не оновлено",  n: all.filter(stageStale).length},
    {q:"nogatein",  cls:"a-red",   nm:"Експорт без Gate in",             n: all.filter(gateInMissing).length},

    {q:"etachg",    cls:"a-amber", nm:"Змінилася дата прибуття",       n: all.filter(etaChanged).length},

    {q:"nostatus",  cls:"a-amber", nm:"Без статусу",                   n: all.filter(r=>!_s(r,"Статус")).length},
    {q:"nobl",      cls:"a-amber", nm:"Без BL",           n: all.filter(QUICK.nobl.test).length},
  ].filter(a=>a.n > 0);
  /* Алерти живуть у ВЕРХНІЙ строці сторінки (#page-actions), а не окремим
     рядком над таблицею: так вони не з'їдають висоту і таблиця починається
     одразу з фільтрів (прохання користувачки 02.08.2026). */
  /* «Всі угоди» — ПЕРШОЮ у верхній строці (вказівка користувачки 11.08.2026).
     Навіщо: значки поруч (алерти) звужують таблицю до свого набору, а швидкий
     фільтр з дашборда — до свого. Повернутись до повного списку можна було лише
     ✕ на чіпі фільтра або вручну перебравши всі випадайки. Тепер це одна кнопка:
     вона скидає І швидкий фільтр, І всі поля фільтрів. */
  const alertHtml = `<div class="alertbar">
        <span class="abadge clickable" id="all-deals" title="показати всі угоди: скинути пошук, фільтри і швидкий фільтр">Всі угоди <b>${all.length}</b></span>
        <span class="abadge">Активних <b>${nActive}</b><span class="cell-muted" style="font-size:11px">з ${all.length}</span></span>
        ${ALERTS.map(a=>`<span class="abadge ${a.cls} clickable" data-q="${a.q}">${esc(a.nm)} <b>${a.n}</b></span>`).join("")}
        ${quick? `<span class="quickchip">Фільтр: ${esc(quick.label)} — ${quickCount}<button id="quick-clear" title="скинути фільтр">✕</button></span>`:""}
      </div>`;
  $("content").innerHTML = `
    <div class="card">
      <button class="filt-btn" id="filt-toggle" type="button" aria-expanded="false">⚙ Фільтри</button>
      <div class="filters" id="filters">
        <input id="q" placeholder="Пошук: угода, клієнт, BL, контейнер, судно…">
        <select id="dirf"><option value="">Імпорт + експорт</option><option>Імпорт</option><option>Експорт</option><option>Транзит</option></select>
        <select id="stf"><option value="">Усі статуси</option>${Object.keys(STATUSES).map(s=>`<option>${s}</option>`).join("")}</select>
        <select id="modef"><option value="">Усі види перевезення</option>${
          uniq("Вид перевезення").map(c=>`<option>${esc(c)}</option>`).join("")}</select>
        <select id="linef"><option value="">Усі лінії</option><option>Maersk</option><option>MSC</option><option>CMA CGM</option><option>Інша</option></select>
        <select id="clif"><option value="">Усі клієнти</option>${uniq("Клієнт").map(c=>`<option value="${esc(c)}">${esc(cliName(c))}</option>`).join("")}</select>
        <select id="manf"><option value="">Усі менеджери</option>${uniq("Менеджер").map(c=>`<option>${esc(c)}</option>`).join("")}</select>
        <select id="opmf"><option value="">Усі оп. менеджери</option>${uniq("Оп. менеджер").map(c=>`<option>${esc(c)}</option>`).join("")}</select>
      </div>
      <div class="tablewrap dispscroll mcards" id="dscroll"><table class="${logist?"":"fixw"}">
        ${logist? "" : `<colgroup>
          <!-- 17 колонок; ширини підібрані так, щоб таблиця вміщалась без бічної
               прокрутки на ~1360 px робочої області (зауваження користувачки 01.08.2026) -->
          <!-- Реліз і Позначки навмисно в кінці: вони потрібні рідко, тому йдуть
               за межу екрана, а місце віддано виду перевезення, коносаменту
               й номерам контейнерів (прохання користувачки 01.08.2026). -->
          <!-- Сума до «Коментаря» включно = 1324 px: усе вміщається на екран
               ~1360 px без обрізання. Реліз, Позначки й документи навмисно
               за межею — їх видно лише при прокрутці вбік (01.08.2026). -->
          <!-- 16 колонок, разом ~1324 px: вміщається без бічної прокрутки.
               Реліз і Позначки з таблиці прибрані зовсім — вони в картці угоди
               (двічі просила прибрати їх з екрана, 01.08.2026). Дати по 84 px:
               жирний 13 px «12.06.26» потребує ~72 px разом із відступами. -->
          <!-- 17 колонок, шість із них дати по 86 px (кегль дат 12.5 px).
               Сума фіксованих ~1232 px, решта — «Коментар» (01.08.2026). -->
          <!-- Перша колонка 46→72 px (05.08.2026). У 46 px не вміщався ні номер
               із чіпом «нова» («27…» замість «273»), ні сам заголовок («Уг…»).
               Заміряно в браузері: слово «Угода» — 41 px + 16 px відступів = 57 px;
               номер «273» — 29 px, чіп «нова» — 36 px, тобто клітинці з чіпом
               під номером треба 52 px. Мінімум = 57 px (диктує заголовок),
               узято 72 px — 15 px запасу на те, що інший браузер намалює шрифт
               ширше. Різницю бере на себе
               «Коментар» — єдина колонка без фіксованої ширини. -->
          <!-- 18 колонок (25.08.2026): повернулась вузька «Реліз» (44 px, галочка) —
               прохання користувачки, між «Статус» і «Авто». Щоб сума фіксованих
               ширин НЕ виросла (правило «без бічної прокрутки» від 01.08.2026
               лишається в силі), 44 px забрано в сусідів: шість дат 86→80
               (жирним 13 px «12.06.26» треба ~72 px, запас є), «Вид / лінія»
               110→106, «Судно» 74→70 (довгі назви й так переносяться).
               Сума фіксованих без «Коментаря» та сама: 1356 px. -->
          <col style="width:72px"><col style="width:62px"><col style="width:84px"><col style="width:102px">
          <col style="width:106px"><col style="width:124px"><col style="width:70px"><col style="width:80px">
          <col style="width:80px"><col style="width:80px"><col style="width:80px"><col style="width:80px">
          <col style="width:80px"><col style="width:106px"><col style="width:44px"><col style="width:74px"><col><col style="width:32px">
        </colgroup>`}
        <thead><tr>${head}</tr></thead>
        <tbody id="drows"></tbody></table></div>
    </div>`;
  $("page-actions").innerHTML = alertHtml + updHtml + (cfg().sync ? syncBtn : "");
  bindNotes();                       // коментарі в куточках клітинок
  // ── редагування клітинки на місці: Enter/клік поза межами — зберегти, Esc — скасувати
  /* Галочка прямо в таблиці одним кліком. Зараз у таблиці таких клітинок НЕМАЄ:
     «Реліз» прибрано з екрана на прохання користувачки (01.08.2026) і він живе
     в картці угоди. Механізм лишаємо — щоб повернути колонку, досить додати
     клітинці class="tog" і data-tog="<назва поля>". */
  const toggleFlag = async (td) => {
    if (td.classList.contains("saving")) return;
    const tr = td.closest("tr[data-id]");
    const row = all.find(x => String(x.Id) === tr.dataset.id);
    if (!row) return;
    const col = td.dataset.tog;
    const was = !!row[col], now = !was;
    td.classList.add("saving");
    try{
      await api(`/api/v2/tables/${T["Диспетчеризація"]}/records`, {method:"PATCH",
        body: JSON.stringify([{Id: row.Id, [col]: now}])});
      row[col] = now;
      logAction("правка угоди", "Угода №" + (row["Угода"] || row.Id), col, was, now);
      toast(`✅ ${col}: ${now ? "поставлено" : "знято"}`);
      draw(rowSpot(row.Id));          // рядок лишається на тому самому місці
    }catch(err){
      toast("⚠ Не збереглось: " + err.message);
    }
    td.classList.remove("saving");
  };

  /* Підганяє висоту таблиці під вікно: низ таблиці (а з ним і горизонтальна
     смуга прокрутки) завжди лишається видимим, скільки б рядків фільтрів
     і алертів не було зверху. */
  const fitDispScroll = () => {
    const box = $("dscroll");
    if (!box) return;
    /* НА ТЕЛЕФОНІ ВИСОТУ НЕ ОБМЕЖУЄМО. Там таблиця показується картками і
       прокручується разом зі сторінкою: `.dispscroll{max-height:none;overflow:visible}`.
       Інлайновий max-height перебивав це правило (інлайн сильніший за таблицю
       стилів), і виходило так: рамка лишалась ~638 px, картки нижче малювались
       ПОЗА нею, а сторінка не подовжувалась — прокрутити до них було НЕМОЖЛИВО.
       Заміряно 16.08.2026: вміст 11 047 px, рамка 638 px, висота сторінки 845 px.
       Саме це користувачка й побачила: «глюк графіки, таблиця не завантажується
       далі» — і світлий прямокутник поверх темного, бо вміст малювався поза
       своєю рамкою і накладався на сусідні картки. */
    if (isPhone()){ box.style.maxHeight = ""; return; }
    const top = box.getBoundingClientRect().top;
    box.style.maxHeight = Math.max(300, window.innerHeight - top - 24) + "px";
  };
  window.addEventListener("resize", fitDispScroll);

  /* ── ШИРИНИ КОЛОНОК ПІДБИРАЮТЬСЯ САМІ ────────────────────────────────────
     ПРАВИЛО КОРИСТУВАЧКИ (05.08.2026, дослівно): «колонки мають бути по ширині
     тексту, ні номери угод, ні номери коносаментів, ні статуси не мають ховатися
     або з'їжджати. Назва клієнта — по ширині, можна переносити на наступну строку.
     Коментар може ховатися».

     ПЕРША СПРОБА ЦЬОГО Ж ДНЯ БУЛА НЕПРАВИЛЬНА і її довелося відкотити: я задала
     кожній колонці стелю в пікселях і стискала ті, що в неї не влазили. На екрані
     через це обрізались номери коносаментів («272623…»), номери контейнерів і
     статуси («Виван в порт прибу»). Помилка була в самому підході: стеля — це
     здогадка про вміст, а вміст щодня інший.

     ЯК ПРАВИЛЬНО. Питаємо браузер, яка МІНІМАЛЬНА ширина колонки, за якої її вміст
     не ріжеться (width:min-content), і даємо рівно її. Нічого не стискаємо:
       * номери угод, коносаментів, контейнерів мають white-space:nowrap, тому
         їхній мінімум — повна довжина номера, і вони не обріжуться ніколи;
       * статус і назва клієнта переносяться по словах, тому їхній мінімум — це
         найдовше слово; текст видно повністю, просто у два рядки;
       * коментар — єдине, що дозволено ховати: у замірі він обмежений (див. CSS
         .measuring td.c-com), а на екрані забирає все вільне місце, яке лишилось.
     Якщо сума потрібних ширин більша за екран — з'являється бічна прокрутка.
     Це свідомий вибір: краще прокрутка, ніж обрізані номери.

     Заміри вартості — у коментарі до виклику fitCols нижче за текстом. */
  /* Номер РАХУЄТЬСЯ З НУЛЯ і має вказувати САМЕ на «Коментар». 25.08.2026 між
     «Статус» і «Авто» вставлено колонку «Реліз», і Коментар з'їхав з 15 на 16;
     поки константу не поправили, гумовою колонкою було «Авто» — його стискало
     до нуля, і заголовок зникав з екрана (упіймала перевірка cols.js). Якщо
     додаєш/прибираєш колонку лівіше за «Коментар» — онови цей індекс. */
  const FLEX_COL = 16;             // «Коментар» — забирає все, що лишилось
  const FLEX_MIN = 90;             // але не вужче за це, інакше колонка зникає
  let colFitKey = "";
  const fitCols = (force, src) => {
    const box = $("dscroll");
    if (!box) return;
    const t = box.querySelector("table.fixw");
    if (!t || !t.tHead) return;
    const cg = t.querySelector("colgroup");
    if (!cg || getComputedStyle(cg).display === "none") return;   // телефон: картки, не таблиця
    const cols = [...cg.children], ths = [...t.tHead.rows[0].cells];
    if (cols.length !== ths.length) return;
    const body = src || $("drows");
    const trs = [...body.children].filter(tr => tr.cells && tr.cells.length === cols.length);
    const avail = box.clientWidth;
    const key = cols.length + "|" + avail + "|" + trs.length;
    if (!force && key === colFitKey) return;      // ні дані, ні ширина вікна не змінились
    colFitKey = key;

    /* Міряємо не всю таблицю, а вибірку: для кожної колонки два рядки з найдовшим
       текстом. Читання textContent розкладку не чіпає, тож це дешево. Заміряно:
       розкладка всіх 270 рядків коштувала 458 мс, вибірки — 13 мс. */
    const pick = new Set();
    for (let i = 0; i < cols.length; i++) {
      const best = [];
      for (const tr of trs) {
        const len = (tr.cells[i].textContent || "").length;
        if (best.length < 2) { best.push([len, tr]); best.sort((a, b) => a[0] - b[0]); }
        else if (len > best[0][0]) { best[0] = [len, tr]; best.sort((a, b) => a[0] - b[0]); }
      }
      best.forEach(x => pick.add(x[1]));
    }

    const probe = document.createElement("table");
    probe.className = t.className + " measuring";
    probe.style.cssText = "position:absolute;left:-99999px;top:0;visibility:hidden";
    const th2 = document.createElement("thead");
    th2.appendChild(t.tHead.rows[0].cloneNode(true));
    probe.appendChild(th2);
    const tb2 = document.createElement("tbody");
    pick.forEach(tr => tb2.appendChild(tr.cloneNode(true)));
    probe.appendChild(tb2);
    /* Копію кладемо ВСЕРЕДИНУ рамки, а не поруч. Це не дрібниця: усі правила
       таблиці записані як «.dispscroll table…», і поза рамкою жодне з них на копію
       не діяло — замість мінімальної ширини браузер рахував максимальну (текст у
       один рядок). Через це 05.08.2026 колонки вийшли надто широкими, між ними
       зяяло порожнє місце, а «Статус» поїхав за край екрана. */
    box.appendChild(probe);
    const need = [...probe.tHead.rows[0].cells].map(c => Math.ceil(c.getBoundingClientRect().width));
    probe.remove();

    /* Даємо рівно потрібне. Вільне місце — «Коментарю»; якщо місця не вистачає,
       нічого не стискаємо — хай буде бічна прокрутка. */
    const w = need.slice();
    if (w[FLEX_COL] !== undefined) w[FLEX_COL] = FLEX_MIN;
    const sum = w.reduce((a, b) => a + b, 0);
    if (w[FLEX_COL] !== undefined) {
      if (sum < avail) {
        w[FLEX_COL] += avail - sum;             // вільне місце — «Коментарю»
      } else if (sum > avail) {
        /* Місця бракує — стискаємо ПЕРШИМ і тільки «Коментар»: він єдиний, кому
           дозволено ховатися. Статус, номери й дати не чіпаємо, навіть якщо через
           це лишиться бічна прокрутка: «статус не може ховатися за край екрана»
           (вимога користувачки 05.08.2026). */
        w[FLEX_COL] = Math.max(0, w[FLEX_COL] - (sum - avail));
      }
    }
    cols.forEach((c, i) => { c.style.width = w[i] + "px"; });
  };
  /* Під час перетягування краю вікна подія сипле десятками разів на секунду —
     рахуємо не щоразу, а коли користувач зупинився. */
  let colFitTimer = 0;
  window.addEventListener("resize", () => {
    clearTimeout(colFitTimer);
    colFitTimer = setTimeout(() => fitCols(false), 120);
  });

  /* Де саме рядок стоїть на екрані зараз — щоб після перемальовування
     повернути його на те саме місце. */
  const rowSpot = (id) => {
    const box = $("dscroll"), tr = $("drows").querySelector('tr[data-id="' + id + '"]');
    return (box && tr) ? { id: id, delta: tr.offsetTop - box.scrollTop } : null;
  };

  const editCell = (td) => {
    if (td.querySelector(".edinput")) return;
    const col = td.dataset.ed;
    const row = all.find(x => String(x.Id) === td.closest("tr").dataset.id);
    if (!row) return;
    const kind = ED_KIND[col] || "text";
    const cur = String(row[col] || "");
    const val0 = kind === "date" ? cur.slice(0,10) : cur;
    const keep = td.innerHTML;
    td.innerHTML = kind === "select"
      ? `<select class="edinput"><option value=""></option>${(ED_OPTS[col]||(()=>[]))().map(o=>
          `<option${o===cur?" selected":""}>${esc(o)}</option>`).join("")}</select>`
      : kind === "date" ? dateEditorHTML(val0)
      : `<input class="edinput" type="text" value="${esc(val0)}">`;
    /* РОЗШИРЕННЯ КОЛОНКИ НА ЧАС РЕДАГУВАННЯ ДАТИ (користувачка, 25.08.2026:
       «не відкривається дата — розшир її за рахунок зміщення вправо колонок,
       нехай коментар не буде видно на екрані»). Колонки дат ужаті під вміст
       («29.07.26» ≈ 80 px), а редактор — це текстове поле ПЛЮС календарик, йому
       треба ~132 px, і в вузькій клітинці від дати лишалося «26». Постійно
       тримати колонки широкими — таблиця не влазить, тому колонка виростає
       ЛИШЕ поки її редагують: сусіди зсуваються вправо (Коментар може піти за
       край — на це дозвіл), а після Enter/Esc ширина повертається. */
    let edCol = null, edColW = "";
    if (kind === "date"){
      const cg = td.closest("table").querySelector("colgroup");
      const c = cg && cg.children[td.cellIndex];
      if (c){ edCol = c; edColW = c.style.width; c.style.width = "132px"; }
    }
    const unwiden = () => { if (edCol){ edCol.style.width = edColW; edCol = null; } };
    const inp = td.querySelector(".edinput");
    roomForEditor(td);
    inp.focus();
    if (kind === "text") inp.select();
    let closed = false;
    const finish = async (save) => {
      if (closed) return;
      closed = true;
      let v = String(inp.value || "").trim();
      if (kind === "date"){
        const iso = parseUserDate(v);
        if (iso === null){                       // не зрозуміли — не зберігаємо
          closed = false;
          toast("⚠ Не зрозуміла дату «" + v + "». Формат: " + DATE_HINT);
          inp.focus(); inp.select();
          return;
        }
        v = iso;
      }
      if (!save || v === val0){ td.innerHTML = keep; unwiden(); return; }
      td.classList.add("saving");
      try{
        const was = row[col];
        const body = withSrc(col, {Id: row.Id, [col]: v || null});
        await api(`/api/v2/tables/${T["Диспетчеризація"]}/records`, {method:"PATCH",
          body: JSON.stringify([body])});
        row[col] = v;                       // DISP_CACHE той самий об'єкт — таблиця і картка бачать нове
        if (col === "Статус"){ row["Статус (джерело)"] = "людина"; row["Статус (оновлено)"] = body["Статус (оновлено)"]; }
        logAction("правка угоди", "Угода №" + (row["Угода"] || row.Id), col, was, v);
        toast(`✅ ${col}: ${v || "очищено"}`);
        draw(rowSpot(row.Id));        // рядок лишається на тому самому місці
      }catch(err){
        td.innerHTML = keep;
        toast("⚠ Не збереглось: " + err.message);
      }
      unwiden();                       // draw() і сам перемалює, але шлях помилки — теж сюди
      td.classList.remove("saving");
    };
    inp.addEventListener("blur", ()=>finish(true));
    inp.addEventListener("keydown", e=>{
      if (e.key === "Enter"){ e.preventDefault(); finish(true); }
      if (e.key === "Escape"){ e.preventDefault(); finish(false); }
    });
    if (kind === "select") inp.addEventListener("change", ()=>finish(true));
    if (kind === "date") bindDatePair(td.querySelector(".dted"), ()=>finish(true));
  };

  let firstDraw = true;
  const draw = (keep) => {
    const q=$("q").value.toLowerCase(), st=$("stf").value;
    const dir=$("dirf").value, line=$("linef").value, cli=$("clif").value;
    const man=$("manf").value, opm=$("opmf").value, mode=$("modef").value;
    const matchQ = r => [r["Угода"],r["Клієнт"],r["BL"],r["HBL"],r["Контейнер"],r["Судно"],r["Номер авто"],r["Водій (ПІБ)"]]
      .join(" ").toLowerCase().includes(q);
    const list = all.filter(r =>
      (!quick || quick.test(r)) &&
      (!st || r["Статус"]===st) &&
      (!dir || r["Напрямок"]===dir) && (!line || r["Лінія"]===line) && (!cli || _s(r,"Клієнт")===cli) &&
      (!man || _s(r,"Менеджер")===man) && (!opm || _s(r,"Оп. менеджер")===opm) &&
      (!mode || _s(r,"Вид перевезення")===mode) &&
      (!q || matchQ(r)));
    /* Які відбори зараз увімкнені і скільки угод дає КОЖЕН окремо.
       Потрібно для чесного порожнього екрана: 03.08.2026 користувачка побачила
       «Нічого не знайдено» при увімкнених «змінилася дата прибуття» + клієнт
       ГРАНД МАРИН + менеджер Ірина і не могла зрозуміти, чи зникли дані.
       Дані були на місці — просто ці три умови разом не перетинались (у базі
       267 угод, з них 5 зі зміненою датою, і жодна не ГРАНД МАРИН).
       Тепер видно, що ввімкнено і що кожна умова окремо щось знаходить. */
    const activeF = [
      quick && {label:"«"+quick.label+"»", n: all.filter(quick.test).length},
      st    && {label:"статус: "+st,                n: all.filter(r=>r["Статус"]===st).length},
      dir   && {label:"напрямок: "+dir,             n: all.filter(r=>r["Напрямок"]===dir).length},
      line  && {label:"лінія: "+line,               n: all.filter(r=>r["Лінія"]===line).length},
      cli   && {label:"клієнт: "+cli,               n: all.filter(r=>_s(r,"Клієнт")===cli).length},
      man   && {label:"менеджер: "+man,             n: all.filter(r=>_s(r,"Менеджер")===man).length},
      opm   && {label:"оп. менеджер: "+opm,         n: all.filter(r=>_s(r,"Оп. менеджер")===opm).length},
      mode  && {label:"вид перевезення: "+mode,     n: all.filter(r=>_s(r,"Вид перевезення")===mode).length},
      q     && {label:"пошук: "+$("q").value.trim(), n: all.filter(matchQ).length},
    ].filter(Boolean);
    /* Доставлені ХОВАЄМО ЗГОРТАННЯМ, а не прокруткою. Прокрутка не працювала,
       коли рядків мало або коли фільтр змінювався (тричі поверталася до цього).
       Тепер вони фізично сховані, а над ними — смужка «Доставлені (N)». */
    const doneList = list.filter(_done), actList = list.filter(r=>!_done(r));
    const shown = list;               // доставлені завжди в переліку, просто внизу
    const bar = "";
    /* Порожній екран має пояснювати САМ СЕБЕ, а не мовчати. Три різні випадки —
       три різні тексти, щоб не гадати, чи це збій, чи справді немає угод. */
    const emptyMsg = () => {
      if (!all.length)
        return "Угод у базі немає. Якщо це несподівано — натисни «⟳ Оновити».";

      if (!activeF.length)
        return "Нічого не знайдено.";
      return `<b>Жодна угода не підходить одразу під усі увімкнені відбори.</b>
        <div style="margin:8px 0 0;font-weight:400">Зараз увімкнено:</div>
        <ul style="margin:4px 0 10px 18px;font-weight:400">${
          activeF.map(f=>`<li>${esc(f.label)} — окремо ${f.n} ${plural(f.n,"угода","угоди","угод")}</li>`).join("")}</ul>
        <button class="btn ghost" id="reset-filters" type="button">✕ Скинути всі відбори</button>`;
    };
    const rowsHtml = bar + (shown.length ? shown.map(r=> logist ? `
      <tr data-id="${r.Id}" class="${r["Статус"]==='Вантаж доставлено'?'done':''}" style="cursor:pointer">
        <td class="mono"><b>${esc(r["Угода"])}</b></td><td>${esc(r["Клієнт"]||"—")}</td>
        <td class="mono">${esc(r["Контейнер"]||"—")}</td><td class="${ED.trim()}" data-ed="Статус">${stPill(r["Статус"])}</td>
        <td class="mono${ED}" data-ed="Номер авто">${esc(r["Номер авто"]||"—")}</td>
        <td class="${ED.trim()}" data-ed="Водій (ПІБ)">${esc(r["Водій (ПІБ)"]||"—")}</td>
        <td class="mono${ED}" data-ed="Водій (телефон)">${esc(r["Водій (телефон)"]||"—")}</td>
        <td class="mono${ED}" data-ed="Перетин кордону (факт)">${dateB(r["Перетин кордону (факт)"])}</td>
        <td>${docBtn(r)}</td>
      </tr>` : `
      <tr data-id="${r.Id}" class="${r["Статус"]==='Вантаж доставлено'?'done':''} ${truckLate(r)?'alertrow':((stageStale(r)||gateInMissing(r)||staleStatus(r)||trackSilent(r))?'warnrow':'')}" style="cursor:pointer"
          ${truckLate(r)?`title="Імпорт у порту ${daysIn(r)} дн, авто не подане і номера немає"`
            :((staleStatus(r)||trackSilent(r))?`title="Дані застаріли: ${esc(staleWhy(r))}. Статус не змінювався автоматично — виправ вручну, якщо знаєш, як насправді."`
              :(stageStale(r)?`title="Статус «${esc(_s(r,"Статус"))}», а етап в Експедиторі досі «Букинг» — менеджер не вніс зміни"`
                :(gateInMissing(r)?'title="Експорт без дати заїзду в порт — її ставлять одразу після букінгу"':"")))}>
        <td class="mono c-num"><b>${esc(r["Угода"])}</b>${_isNew(r)?'<span class="newchip" title="угода з\'явилася в таблиці за останні 7 днів">нова</span>':""}${taskChip(r)}</td>
        <td>${r["Напрямок"]?`<span class="dirchip ${r["Напрямок"]==="Імпорт"?"imp":"exp"}">${r["Напрямок"]==="Імпорт"?"ІМП":(r["Напрямок"]==="Експорт"?"ЕКС":"ТРН")}</span>`:""}</td>
        <td class="c-cli" data-l="Клієнт" title="${esc(r["Клієнт"]||"")}">${esc(cliName(r["Клієнт"])||"—")}</td>
        <td class="c-rt${ED}" data-l="Маршрут" data-ed="Маршрут" title="${esc(r["Маршрут"]||"")}">${
            _s(r,"Маршрут")
              ? routeArrows(r["Маршрут"]).split("→").map(x=>x.trim()).filter(Boolean)
                  .map((x,i)=>`${i?'<span class="rtar">→</span>':""}${esc(x)}`).join("<br>")
              : '<span class="cell-muted">—</span>'}${
            _s(r,"Кінцева точка доставки")
              ? `<br><span class="fin" title="кінцева точка доставки">⌂ ${esc(r["Кінцева точка доставки"])}</span>`
              : ""}</td>
        <td class="c-md${ED}" data-ed="Вид перевезення" title="${esc(_s(r,"Вид перевезення"))}">${
            _s(r,"Вид перевезення")
              /* «фрахт+ТЕО+залізниця» — один суцільний токен без пробілів, тому
                 звичайний перенос не спрацьовував і текст обрізався. <wbr> каже
                 браузеру, що після «+» переносити можна (01.08.2026). */
              ? esc(r["Вид перевезення"]).replace(/\+/g, "+<wbr>")
              : '<span class="cell-muted">—</span>'}${
            (isAir(r)||_s(r,"Вид перевезення")==="авто"||!_s(r,"Лінія")) ? ""
              : `<br><span class="cell-muted">${esc(r["Лінія"])}</span>`}</td>
        <td class="mono c-bl" data-l="Коносамент / контейнер">${isAir(r)
            ? (_s(r,"Авіанакладна") ? `${esc(r["Авіанакладна"])}<br><span class="cell-muted">авіанакладна</span>`
                                    : '<span class="cell-muted">авіа — накладної немає</span>')
            : `${_s(r,"HBL") ? `<span class="ln hbl" title="домашній коносамент: ${esc(r["HBL"])}"><i class="blt">HBL</i>${esc(r["HBL"])}</span>` : ""}${
                _s(r,"BL") ? `<span class="ln" title="лінійний коносамент"><i class="blt">BL</i>${trackLink(r, r["BL"])}</span>` : ""}${
                (!_s(r,"HBL") && !_s(r,"BL")) ? '<span class="ln cell-muted">—</span>' : ""}${_s(r,"Контейнер").split(",")
                .map(c=>c.trim()).filter(Boolean)
                .map(c=>`<span class="ln">${trackLink(r, c, "cell-muted")}</span>`).join("")}`}</td>
        <td class="c-ves${ED}" data-l="Судно" data-ed="Судно">${esc(r["Судно"]||"—")}</td>
        <td class="mono dt${ED} sec" data-l="Stuffing" data-ed="Stuffing" title="дата стафіровки">${dateB(r["Stuffing"])}</td>
        <td class="mono dt${ED} sec" data-l="Gate in / здача" data-ed="${_s(r,"Здача в порт (факт)") ? "Здача в порт (факт)" : "Гейт ін"}"
            title="${_s(r,"Здача в порт (факт)")
              ? "фактична здача в порт — від неї рахуємо демередж і зберігання"
              : "Gate in — заїзд у порт"}">${
            /* ОДНА дата в клітинці (02.08.2026): спочатку Gate in, а коли
               з'явиться фактична здача в порт — показуємо її замість Gate in.
               До цього тут було два рядки, і в порожньому стояв прочерк —
               «не читається взагалі, сильно заважають». Обидва поля лишаються
               окремими й редагуються в картці угоди. */
            dateB(_s(r,"Здача в порт (факт)") ? r["Здача в порт (факт)"] : r["Гейт ін"])}</td>
        <td class="mono dt${ED}${_s(r,"Напрямок")==="Експорт"?" keydt":""}" data-l="ETD POL" data-ed="ETD (факт)">${etdOf(r)
            /* Підпис «план» прибрано 01.08.2026: ETD і так планова дата, доки
               немає фактичної. Значення береться з «ETD (факт)», а якщо його
               немає — з «ETD (план)», тому окремо позначати нічого не треба. */
            ? dateB(etdOf(r))
            : '<span class="cell-muted">—</span>'}</td>
        <td class="mono dt${ED}${_s(r,"Напрямок")==="Імпорт"?" keydt":""}" data-l="ETA POD" data-ed="ETA">${dateB(r["ETA"])}${(()=>{
            const c = etaChanged(r) ? etaChange(r) : null;
            return c ? noteMark("wasdt", `було ${fmtD(c.from)} · дата прибуття змінилася ${fmtD(c.when)}`) : "";
          })()}</td>
        <td class="mono dt${ED} sec" data-l="ETA dry port" data-ed="ETA сухий порт" title="${
            isRail(r) ? "ETA сухий порт" : "сухий порт буває лише на залізничних перевезеннях"}">${
            _s(r,"ETA сухий порт") ? dateB(r["ETA сухий порт"])
              : (isRail(r) ? '<span class="cell-muted">—</span>'
                           : '<span class="cell-muted">—</span>')}</td>
        <td class="mono dt${ED} sec" data-l="Gate out delivery" data-ed="Gate out for delivery" title="виїзд із сухого порту на авто — послуга «остання миля»">${
            dateB(r["Gate out for delivery"])}</td>
        <td class="${ED.trim()}" data-l="Статус" data-ed="Статус">${
            /* ДВА РІЗНІ ПОВІДОМЛЕННЯ, а не одне слово на обидва випадки.
               «застаріло» = дані старі, вантаж стоїть довше, ніж мав.
               «трекінг не відповідає» = ми не змогли СПИТАТИ лінію (напр. Maersk
               віддає 404 на коносамент, який у нього ж на сайті відкривається —
               перевірено 11.08.2026 на угодах 250, 251, 245, 272, 273).
               Раніше обидва писались як «застаріло», і збій зв'язку виглядав як
               застій вантажу. Для кабінету клієнта це неприпустимо поготів. */
            stPillNote(r["Статус"], (staleStatus(r) || trackSilent(r))
              ? (staleStatus(r) ? "застаріло" : "трекінг не відповідає") + ": " + staleWhy(r)
              : "")}</td>
        <td class="tog c-rel" data-l="Реліз" data-tog="Реліз" title="Реліз${CAN_EDIT ? ": клік — поставити/зняти" : ""}">${
            r["Реліз"] ? RELIZ_SVG : ""}</td>
        <td class="mono${ED}" data-l="Авто"${CAN_EDIT ? ' data-trk="1"' : ""} title="${
            CAN_EDIT ? "клік — внести дані від перевізника (текст розбирається на поля)" : "дата подачі авто і номер"}">${truckDate(r)
            ? `${dateB(truckDate(r))}${_s(r,"Подача авто (факт)")?"":'<span class="cell-muted"> план</span>'}`
            : (truckLate(r) ? '<span style="color:#d1453b;font-weight:700">немає</span>' : '<span class="cell-muted">—</span>')}${
            _s(r,"Номер авто") ? `<br><span class="cell-muted">${esc(r["Номер авто"])}</span>` : ""}</td>
        <td class="cell-muted c-com${ED}" data-l="Коментар" data-ed="Коментар" title="${esc(r["Коментар"]||"")}">${esc(r["Коментар"]||"")}</td>
        <td>${docBtn(r)}</td>
      </tr>`).join("") : `<tr><td colspan="${logist?7:18}" class="cell-muted" style="padding:18px">${emptyMsg()}</td></tr>`);
    /* Рядки спершу збираються ПОЗА сторінкою, потім міряються ширини на
       порожній таблиці, і аж тоді рядки потрапляють у неї. Порядок не
       косметичний, а заміряний: якщо міряти вже вставлені рядки, браузер
       розкладає всю таблицю двічі — 295 мс на показ перетворювались на 509. */
    const parsed = document.createElement("tbody");
    parsed.innerHTML = rowsHtml;          // парсинг поза документом — розкладки не потребує
    $("drows").replaceChildren();         // порожня таблиця — розкладка дешева
    fitCols(true, parsed);
    $("drows").replaceChildren(...parsed.children);
    /* Скидання всіх відборів одним кліком. Якщо увімкнено швидкий фільтр із
       дашборда — його теж треба зняти, а він живе поза draw(), тому сторінку
       перемальовуємо через go(). Інакше — досить перемалювати таблицю. */
    const rf = $("reset-filters");
    if (rf) rf.addEventListener("click", ()=>{
      ["q","stf","dirf","linef","clif","manf","opmf","modef"].forEach(id=>{
        const el = $(id); if (el) el.value = "";
      });
      if (DISP_QUICK){ DISP_QUICK = null; go("dispatch"); } else draw();
    });
    const ft = $("filt-toggle");
  if (ft) ft.addEventListener("click", ()=>{
    const box = $("filters"), on = box.classList.toggle("open");
    ft.setAttribute("aria-expanded", on ? "true" : "false");
    ft.textContent = (on ? "✕ Сховати фільтри" : "⚙ Фільтри");
  });
    markEmptyCells($("drows"));

    $("drows").querySelectorAll("tr[data-id]").forEach(tr=>tr.addEventListener("click",()=>openRow(all.find(x=>String(x.Id)===tr.dataset.id))));
    // клік по номеру відкриває трекінг лінії, а не картку угоди
    $("drows").querySelectorAll("a.tl").forEach(a=>a.addEventListener("click", e=>e.stopPropagation()));
    // клік по галочці «Реліз» — перемикається одразу, картка не відкривається
    if (CAN_EDIT) $("drows").querySelectorAll("td.tog[data-tog]").forEach(td=>{
      td.addEventListener("click", e=>{ e.stopPropagation(); toggleFlag(td); });
    });
    // клік по клітинці «Авто» — вікно даних від перевізника (25.08.2026)
    $("drows").querySelectorAll("td[data-trk]").forEach(td=>{
      td.addEventListener("click", e=>{
        e.stopPropagation();
        const row = all.find(x => String(x.Id) === td.closest("tr").dataset.id);
        if (row) openTruck(row);
      });
    });
    // клік по редагованій клітинці — правка на місці, картка угоди при цьому не відкривається
    if (CAN_EDIT) $("drows").querySelectorAll(".ed[data-ed]").forEach(td=>{
      if (!td.title) td.title = "клік — редагувати «" + td.dataset.ed +
        "», Enter — зберегти, Esc — скасувати";
      td.addEventListener("click", e=>{ e.stopPropagation(); editCell(td); });
    });
    /* Прокрутка. При ПЕРШОМУ відкритті ховаємо доставлені за шапку, щоб зверху
       був найближчий за ключовою датою вантаж. Далі — не смикаємо: після правки
       клітинки таблиця перемальовується, і раніше вона щоразу стрибала на початок
       (зауваження користувачки 01.08.2026). Якщо передано keep — повертаємо
       відредагований рядок рівно туди, де він був на екрані, навіть якщо
       пересортування зсунуло його вище або нижче. */
    /* Порядок важливий: спершу висота (від неї залежить, чи буде вертикальна
       смуга прокрутки, а отже й доступна ширина), потім ширини колонок, і аж
       тоді прокрутка — бо нові ширини міняють висоту рядків. */
    fitDispScroll();
    const box = $("dscroll");
    if (box){
      if (keep){
        const tr = $("drows").querySelector('tr[data-id="' + keep.id + '"]');
        if (tr) box.scrollTop = Math.max(0, tr.offsetTop - keep.delta);
      } else {
        /* Доставлені ховаються ПІД шапкою — і при першому показі, і після кожної
           зміни фільтра. Якщо рядків мало і прокручувати нікуди — додаємо запас
           знизу рівно на ту висоту, якої бракує. */
        /* Ховання доставлених під шапку — тільки для комп'ютера. На телефоні
           доставлені й так стоять ПІСЛЯ активних (див. сортування вище), рамка
           не прокручується власною смугою, а порожній добірний блок лише
           додавав би зайву порожнечу в кінці стрічки карток. */
        if (isPhone()){
          const oldSp = $("dscroll-spacer");
          if (oldSp) oldSp.remove();
          box.style.paddingBottom = "";
          firstDraw = false;
          $("drows").querySelectorAll(".docs-btn").forEach(b=>b.addEventListener("click",(e)=>{
            e.stopPropagation(); openDocs(all.find(x=>String(x.Id)===b.dataset.doc)); }));
          return;
        }
        const firstOpen = $("drows").querySelector("tr:not(.done)");
        /* Запас знизу — СПРАВЖНІЙ порожній блок, а не padding-bottom.
           Перевірено в браузері 04.08.2026: відступ знизу браузер НЕ додає до
           області прокрутки (треба 238, запас лишався 130, прокрутка спинялась
           на 130). Саме тому доставлені не ховались під шапку, а нижня угода
           була видна не повністю — користувачка це й побачила.
           Порожній блок додається до scrollHeight завжди й у всіх браузерах. */
        box.style.paddingBottom = "";
        const oldSpacer = $("dscroll-spacer");
        if (oldSpacer) oldSpacer.remove();
        if (firstOpen){
          /* Шапка таблиці закріплена (thead th{position:sticky;top:0}), тобто
             вона ЛЕЖИТЬ ПОВЕРХ перших рядків області прокрутки. Якщо прокрутити
             рівно до першого активного рядка, він опиняється ПІД шапкою і видно
             лише його низ — саме це побачила користувачка 04.08.2026 на угоді 227.
             Тому віднімаємо ФАКТИЧНУ висоту шапки, а не підібране число:
             висота залежить від того, скільки рядків займають заголовки, і на
             телефоні вона інша. Плюс 6 px просвіту, щоб рядок не торкався шапки. */
          const thead = box.querySelector("thead");
          const headH = thead ? thead.getBoundingClientRect().height : 0;
          /* Відстань беремо через реальні координати на екрані, а не через
             offsetTop: той рахується від «найближчого позиційованого предка», і
             який саме це елемент, браузери визначають по-різному. Координати
             однакові скрізь (05.08.2026). */
          const need = Math.max(0, box.scrollTop
            + firstOpen.getBoundingClientRect().top - box.getBoundingClientRect().top
            - headH - 6);
          /* СКІЛЬКИ ЗАПАСУ ТРЕБА. Рахуємо від ГРАНИЧНОЇ висоти рамки, а не від
             її поточної. Причина (виміряно 04.08.2026): у .dispscroll задано
             max-height, тобто рамка РОЗТЯГУЄТЬСЯ під вміст, доки не впреться в
             межу. Поки вміст коротший за межу, рамка росте разом із запасом —
             і прокрутки не з'являється НІКОЛИ, скільки запасу не додай.
             Стара формула (need - (scrollHeight - clientHeight)) саме тому й не
             працювала при малій кількості рядків: 3 доставлені + 2 активні
             давали запас 144 px замість потрібних 588, рамка просто ставала
             вищою. Це те, що побачила користувачка з фільтром «Ірина»:
             доставлені лишались на екрані, вільного місця знизу не з'являлось,
             а нижній рядок був обрізаний.
             Правильно: вміст має перевищити межу рівно на `need`. */
          /* Висоту вмісту беремо з САМОЇ ТАБЛИЦІ, а не з box.scrollHeight:
             у рамки є min-height:300px, тому scrollHeight ніколи не буває
             меншим за 300, і при кількох рядках він завищений — запас виходив
             на 10 px замалий. */
          const tbl = box.querySelector("table");
          const contentH = tbl ? tbl.getBoundingClientRect().height : box.scrollHeight;
          const maxH = parseFloat(getComputedStyle(box).maxHeight) || box.clientHeight;
          /* ПРОКРУТКА ПЕРЕВІРЯЄ САМА СЕБЕ (05.08.2026). Доти код ВІРИВ розрахунку:
             додав запас — прокрутив — пішов далі. Якщо браузер рахує область
             прокрутки хоч трохи інакше, прокрутка спинялась раніше, і доставлені
             лишались на екрані. Відтворити це в контейнері неможливо: WebKit
             (двигун Safari) сюди не встановлюється, а в Chromium випадок
             користувачки проходив і на зламаній версії — тобто перевірити
             розрахунком не вийде в принципі.
             Тому міряємо ФАКТИЧНО досягнуту прокрутку і добираємо запас рівно на
             різницю. Три спроби: кожна виправляє те, що недобрала попередня.
             Тепер результат не залежить від того, як браузер рахує висоти. */
          const sp = document.createElement("div");
          sp.id = "dscroll-spacer";
          sp.setAttribute("aria-hidden", "true");
          sp.style.height = Math.max(0, need + maxH - contentH) + "px";
          box.appendChild(sp);
          box.scrollTop = need;
          for (let i = 0; i < 3 && box.scrollTop < need - 1; i++){
            const gap = need - box.scrollTop;          // стільки не догорнулось
            sp.style.height = ((parseFloat(sp.style.height) || 0) + gap + 1) + "px";
            box.scrollTop = need;
          }
        } else {
          box.scrollTop = 0;          // доставлених немає або самі доставлені
        }
      }
      firstDraw = false;
    }
    $("drows").querySelectorAll(".docs-btn").forEach(b=>b.addEventListener("click",(e)=>{ e.stopPropagation(); openDocs(all.find(x=>String(x.Id)===b.dataset.doc)); }));
  };
  /* Дати картці угоди змогу перемалювати цю таблицю. rowSpot видно лише звідси,
     тому загортаємо: назовні достатньо передати Id рядка. */
  DISP_REDRAW = (id) => draw(id ? rowSpot(id) : null);
  DISP_TASKS_REFRESH = async () => {
    try{ await buildTaskMap(); }catch(e){ return; }   // без задач таблицю не смикаємо
    if ($("drows")) draw(null);                       // прокрутка лишається на місці
  };
  /* ⚠️ draw() ВИКЛИКАЄМО БЕЗ АРГУМЕНТІВ — саме тому тут стрілка, а не просто
     `draw`. Перший аргумент draw(keep) означає «поверни оцей рядок туди, де він
     був на екрані» і використовується після правки угоди. Якщо передати сюди
     сам draw, слухач подій підставить йому ОБ'ЄКТ ПОДІЇ, keep стане істинним, і
     код піде гілкою «відновити позицію» — шукатиме рядок tr[data-id="undefined"],
     не знайде і НЕ ЗРОБИТЬ НІЧОГО. Наслідок, який побачила користувачка
     11.08.2026: на основному екрані доставлені сховані під шапкою, а щойно
     вибрати менеджера — вони знову на весь екран, бо прокрутка не спрацювала.
     Відтворено і перевірено в браузері: scripts/mgrscroll.js. */
  ["q","dirf","stf","modef","linef","clif","manf","opmf"]
    .forEach(id=>$(id).addEventListener(id==="q"?"input":"change", ()=>draw()));
  $("page-actions").querySelectorAll(".abadge[data-q]").forEach(b=>b.addEventListener("click",()=>{
    DISP_QUICK = (DISP_QUICK === b.dataset.q) ? null : b.dataset.q; go("dispatch");
  }));
  const qc = $("quick-clear");
  if (qc) qc.addEventListener("click",()=>{ DISP_QUICK=null; go("dispatch"); });
  /* «Всі угоди»: скидаємо і швидкий фільтр, і поля. go("dispatch") перемальовує
     сторінку заново, тому поля треба чистити ДО нього — інакше вони відновляться
     з тими самими значеннями, бо беруться з DOM, а не зі стану. */
  const ad = $("all-deals");
  if (ad) ad.addEventListener("click",()=>{
    ["q","dirf","stf","modef","linef","clif","manf","opmf"].forEach(id=>{
      const el = $(id); if (el) el.value = "";
    });
    DISP_QUICK = null;
    go("dispatch");
  });
  draw();
  restoreNote("disp-note");
  const sb = $("sync-btn");
  /* Оновлення триває близько 2,5 хвилин (виміряно: Експедитор 4 с, трекінг
     Maersk 147 с, COSCO 2 с). Тримати весь цей час відкритим один запит не
     можна — будь-який обрив, і результат втрачався, хоча на сервері все
     відпрацювало. Тому: /sync лише ЗАПУСКАЄ роботу і одразу відповідає, а ми
     раз на 5 секунд питаємо /sync-state, чи вже готово, і пишемо це під кнопкою.
     Опитування переживає перехід між сторінками: воно триває навіть якщо
     кнопки на екрані вже немає, а підпис відновлюється з sessionStorage. */
  /* Що САМЕ зробив цей запуск. Було: при new=0 писали «нових угод немає» —
     і це читалося як «в Експедиторі нових угод немає», хоча насправді означало
     «жодного нового РЯДКА створювати не довелося, бо всі вже в таблиці».
     04.08.2026 користувачка: «система пише, що нових угод немає, а вони є».
     Перевірено тоді ж: в Експедиторі 268 угод, у платформі 269, угоди 272 і 273
     від 03.08 уже були на місці — тобто повідомлення було правдиве, але
     збивало з пантелику. Тепер пишемо і скільки всього угод звірено. */
  const syncSummary = (res) => {
    const s = res || "";
    const all = /deals=(\d+)/.exec(s), nw = /new=(\d+)/.exec(s), up = /updated=(\d+)/.exec(s);
    const last = /last=(\d+)/.exec(s);
    const t = /MAERSK_OK tracked=(\d+) updated=(\d+)/.exec(s);
    const parts = [];
    if (nw && nw[1] !== "0") parts.push(`додано нових угод: ${nw[1]}`);
    else if (all) parts.push(`усі ${all[1]} ${plural(+all[1],"угода","угоди","угод")} з Експедитора вже в таблиці`);
    if (last && last[1] !== "0") parts.push(`остання угода в Експедиторі: ${last[1]}`);
    if (up) parts.push(up[1] === "0" ? "змін немає" : `оновлено угод: ${up[1]}`);
    if (t) parts.push(`трекінг Maersk: оновлено ${t[2]} з ${t[1]}`);
    return parts.length ? parts.join(" · ") : "готово";
  };
  const watchSync = async () => {
    const until = Date.now() + 15*60*1000;   // межа безпеки, щоб не питати вічно
    while (Date.now() < until){
      await new Promise(r=>setTimeout(r, 5000));
      let st;
      try { st = await svc("/sync-state"); }
      catch(e){ refreshNote("disp-note","err","не вдалося дізнатися стан: "+e.message); return; }
      if (st.running) continue;
      if (st.ok === false){
        refreshNote("disp-note","err", st.error || "оновлення не пройшло");
        return;
      }
      refreshNote("disp-note","ok");
      toast("✅ " + syncSummary(st.result));
      DISP_CACHE = null;
      if (CUR === "dispatch") go("dispatch");
      return;
    }
    refreshNote("disp-note","err","минуло 15 хвилин без відповіді — скажи Клоду");
  };
  /* Якщо сторінку перезавантажили посеред оновлення — підхоплюємо його назад.
     Без цього після F5 підпис був порожній, і виглядало б, ніби нічого не йде. */
  if (sb) svc("/sync-state").then(st=>{
    if (st && st.running){ refreshNote("disp-note","busy","Оновлення вже йде…"); watchSync(); }
  }).catch(()=>{ /* стан не дізнались — просто не показуємо нічого */ });
  if (sb) sb.addEventListener("click", async ()=>{
    sb.disabled = true;
    refreshNote("disp-note","run","Оновлюю… це близько 2,5 хвилин");
    try{
      await svc("/sync");
      watchSync();
    } catch(e){
      // 409 «вже виконується» — не помилка: робота йде, просто її почали раніше
      if (/вже виконується/.test(e.message)){
        refreshNote("disp-note","busy", e.message);
        watchSync();
      } else {
        refreshNote("disp-note","err", e.message);
      }
    }
    finally{ sb.disabled = false; }
  });
};

/* ===== типи документів =====
   Тип зберігається ПРЕФІКСОМ у назві вкладення: «[Т1] scan.pdf» (рішення користувачки
   01.08.2026). Так тип видно людині і в платформі, і в базі, і він не губиться,
   якщо файли чіпають руками. Клієнтський кабінет показуватиме лише CLIENT_DOCS.
   «Рахунок» — наш рахунок клієнту; «Інвойс» — інвойс на вантаж від клієнта
   (різні документи, уточнення користувачки 01.08.2026). */
const DOC_TYPES = ["Домашній коносамент","Лінійний коносамент","Т1","Реліз","ЦМР",
                   "Рахунок","Інвойс","Довідка","Акт","Внутрішній"];
const CLIENT_DOCS = new Set(["Домашній коносамент","Лінійний коносамент","Т1","Реліз","ЦМР",
                             "Рахунок","Інвойс","Довідка","Акт"]);
const DOC_TYPE_RE = /^\s*\[([^\]]+)\]\s*/;
const docType = a => { const m = DOC_TYPE_RE.exec(String(a.title||"")); return m ? m[1].trim() : ""; };
const docName = a => String(a.title||"файл").replace(DOC_TYPE_RE, "");

function attList(r){
  let f = r["Файли"];
  if (typeof f === "string"){ try{ f = JSON.parse(f); }catch(e){ f = []; } }
  return Array.isArray(f) ? f : [];
}
/* Галочка «Реліз» — фінальний вибір користувачки 25.08.2026: НАМАЛЬОВАНА
   (варіант 6 зі сторінки варіантів), бо шрифтова у 21 px вийшла завеликою.
   Малюнок не залежить від шрифту — однаковий на Mac, Windows і телефоні,
   а товщина лінії задається напряму (4.5 з 24 — жирна при 15 px). */
const RELIZ_SVG = '<svg class="relmark" width="15" height="15" viewBox="0 0 24 24" fill="none" aria-hidden="true">'
  + '<path d="M4 12.5 L9.5 18 L20 6.5" stroke="#1a7f37" stroke-width="4.5" stroke-linecap="round" stroke-linejoin="round"/></svg>';
function docBtn(r){
  const n = attList(r).length;
  return `<button class="btn ghost docs-btn" data-doc="${r.Id}" style="padding:3px 10px" title="Документи">📄${n||""}</button>`;
}
function fileUrl(a){
  /* БЕРЕМО `path`, А НЕ ПІДПИСАНЕ ПОСИЛАННЯ. Чому (знайдено 18.08.2026):
     NocoDB віддає у вкладенні і `path` (download/…), і `signedUrl`/`signedPath`
     (dltemp/…). Фасад брав підписане — а в Caddy маршруту `/dltemp/*` НЕМАЄ,
     до бази прокинуто лише `/download/*`. Тому браузер на такий шлях отримував
     не файл, а нашу ж сторінку: перевірено на угоді 287 —
        /download/…  → 200, application/…sheet, 7037 б  (справжній файл)
        /dltemp/…    → 200, text/html, 65 688 б         (сторінка ЕРП)
     Виглядало це так, як описала користувачка: відкривається нова вкладка з ЕРП,
     файл не відкривається, а оскільки ключ сесії живе В МЕЖАХ ВКЛАДКИ — у новій
     вкладці її зустрічав екран входу, тобто «вибивало з програми».
     Кожен відрізок шляху кодуємо окремо: у назвах файлів бувають пробіли й
     кирилиця («Заявка авто Maersk … .xlsx»), а косі риски мають лишитись косими. */
  const enc = p => String(p).replace(/^\/+/, "").split("/").map(encodeURIComponent).join("/");
  if (a.path) return "/" + enc(a.path);
  let u = a.signedUrl || a.url || "";
  if (u && u.startsWith("http")){ try{ const p = new URL(u); u = p.pathname + p.search; }catch(e){} }
  if (!u){ u = "/" + enc(a.signedPath || ""); }
  return u;
}
let DOC_ROW = null;
function renderDocList(){
  const files = attList(DOC_ROW);
  $("doc-list").innerHTML = files.length ? files.map(a=>{
    const kb = a.size ? Math.round(a.size/1024) + " КБ" : "";
    const t = docType(a);
    const chip = t
      ? `<span class="pill ${CLIENT_DOCS.has(t)?"t-info":"t-neutral"}" title="${CLIENT_DOCS.has(t)
          ? "клієнт бачить цей документ у кабінеті" : "внутрішній — клієнту не показується"}">${esc(t)}</span>`
      : '<span class="pill t-warn" title="тип не вказаний — клієнту не показується">без типу</span>';
    return `<div class="acct-chip" style="flex:none;display:flex;align-items:center;gap:10px;cursor:default">
      ${chip}
      <span style="flex:1"><b>${esc(docName(a))}</b> <span class="cell-muted">${kb}</span></span>
      <a class="btn ghost" style="padding:4px 12px;text-decoration:none" target="_blank" href="${esc(fileUrl(a))}">Відкрити</a></div>`;
  }).join("") : '<p class="sub">Поки нічого не прикріплено.</p>';
}
function openDocs(r){
  DOC_ROW = r;
  /* У заголовку, крім номера і клієнта, — маршрут і коносамент (прохання
     користувачки 14.08.2026). Вікно документів відкривають прямо з таблиці, і без
     цих двох не видно, до якого саме перевезення чіпляється файл.
     Маршрут і коносамент — світлішим і без жирного, щоб довгий заголовок читався,
     а номер угоди лишався головним. Порожнє не показуємо: прочерків у заголовку
     не малюємо (правило «немає даних — нічого не вигадуємо»).
     Коносаментів може бути два — лінійний (BL) і домашній (HBL); показуємо обидва
     через «/», як у колонці таблиці. */
  const dtBL = [_s(r, "BL"), _s(r, "HBL")].filter(Boolean).join(" / ");
  const dtTail = [routeArrows(_s(r, "Маршрут")), dtBL].filter(Boolean).join(" · ");
  $("doc-title").innerHTML = `📄 Документи угоди №${esc(r["Угода"])} · ${esc(r["Клієнт"] || "")}`
    + (dtTail ? ` <span style="font-weight:400;color:var(--muted)">· ${esc(dtTail)}</span>` : "");
  /* Прикріплення файлу ПИШЕ в угоду (колонка «Файли»). Показуємо його тим, хто править
     угоди, І ОКРЕМО бухгалтеру — дозвіл користувачки 15.08.2026 («дозволь»): він
     доносить акти й рахунки до угоди, хоча самі угоди не редагує.
     Фінансисту і «Перегляду» кнопки немає: перший отримав лише перегляд і формування
     документів, другий не пише нічого.
     ⚠️ Виправлення моєї ж помилки того ж дня: спершу я сховала кнопку і в бухгалтера,
     написавши, що прошарок такий запис відхиляє. Насправді `server/gateway.py` стоїть
     у дорозі (`/api/*` → 8792), але працює БЕЗ `GATEWAY_ENFORCE`, тобто лише пише в
     журнал і пропускає всіх — прикріплення в бухгалтера працювало. Правило для нього
     дописане в прошарок наперед, щоб не зламалось, коли той почне блокувати.
     Скачування і формування документів від цього не залежать: файли віддаються за
     прямим посиланням, а «Сформувати документ» іде на /gen-doc зі своїм переліком
     ролей (docgen.py: заборонено лише «Перегляд» і «Логіст»). */
  $("doc-upload-wrap").style.display = (cfg().edit || ATTACH_ROLES.has(ROLE)) ? "block" : "none";
  $("gen-wrap").style.display = GEN_DENY.has(ROLE) ? "none" : "block";
  $("gen-type").value = ""; $("gen-form").style.display = "none"; $("gen-form").innerHTML = "";
  $("gen-btn").style.display = "none"; $("gen-status").textContent = "";
  $("doc-status").textContent = "";
  $("doc-type").innerHTML = DOC_TYPES.map(t=>`<option${t==="Внутрішній"?"":""}>${esc(t)}</option>`).join("");
  renderDocList();
  $("doc-overlay").classList.add("open");
}
$("doc-close").addEventListener("click", ()=>$("doc-overlay").classList.remove("open"));
$("doc-overlay").addEventListener("click", e=>{ if(e.target===$("doc-overlay")) $("doc-overlay").classList.remove("open"); });
$("doc-upload-btn").addEventListener("click", ()=>$("doc-file").click());
$("doc-file").addEventListener("change", async ()=>{
  const files = [...$("doc-file").files];
  if (!files.length || !DOC_ROW) return;
  $("doc-status").textContent = "⏳ Завантажую " + files.length + " файл(и)…";
  try{
    let added = [];
    for (const f of files){
      const fd = new FormData(); fd.append("file", f);
      const r = await fetch("/api/v2/storage/upload", {method:"POST", headers:{"xc-auth": JWT||""}, body: fd});
      const js = await r.json();
      if (!r.ok) throw new Error((js && js.msg) || "upload");
      added = added.concat(Array.isArray(js) ? js : [js]);
    }
    // тип у назву: «[Т1] scan.pdf». Якщо префікс уже є — не дублюємо.
    const ttype = $("doc-type").value || "Внутрішній";
    added.forEach(a=>{
      const nm = String(a.title || "файл").replace(DOC_TYPE_RE, "");
      a.title = "[" + ttype + "] " + nm;
    });
    const merged = attList(DOC_ROW).concat(added);
    await api(`/api/v2/tables/${T["Диспетчеризація"]}/records`, {method:"PATCH",
      body: JSON.stringify([{Id: DOC_ROW.Id, "Файли": merged}])});
    DOC_ROW["Файли"] = merged;
    renderDocList();
    $("doc-status").textContent = "";
    toast(`✅ Прикріплено (${$("doc-type").value}): ${files.length}`);
    logAction("додано документ", "Угода №" + (DOC_ROW["Угода"] || DOC_ROW.Id),
      $("doc-type").value, "", added.map(a=>a.title).join(", "));
  } catch(e){
    $("doc-status").textContent = "⚠ Не вдалося завантажити (" + e.message + ")";
  }
  $("doc-file").value = "";
});

/* ===== формування документів за бланками ===== */
const GEN_DENY = new Set(["Перегляд","Логіст"]);
/* Ролі без права правити угоди, яким усе ж можна ПРИКРІПЛЮВАТИ файли до угоди.
   Дозвіл користувачки 15.08.2026. Той самий перелік продубльовано в
   server/gateway.py (FILE_ROLES) — фасад ховає кнопку, прошарок стереже запис. */
const ATTACH_ROLES = new Set(["Бухгалтер"]);
let CLIENTS_CACHE = null;
async function clientRec(name){
  if (!name) return {};
  if (!CLIENTS_CACHE){
    /* Було: при збої запису в кеш клали ПОРОЖНІЙ список — і він там залишався
       до перезавантаження сторінки. Тобто один випадковий збій мережі означав,
       що ВСІ документи до кінця дня формувались без реквізитів клієнта
       (номер договору, ЄДРПОУ, директор), і ніхто про це не знав.
       Тепер: кеш не псуємо, кажемо вголос і даємо наступній спробі спрацювати.
       loadAll замість limit=200 — щоб клієнти не обрізались мовчки. */
    try{ CLIENTS_CACHE = await loadAll(T["Клієнти"]); }
    catch(e){
      sysWarn("Довідник клієнтів не завантажився (" + (e.message || "збій зв'язку") +
              "). Реквізити в документах будуть порожні — онови сторінку перед тим, як їх формувати.");
      return {};
    }
  }
  const n = String(name).trim();
  return CLIENTS_CACHE.find(c=>Object.values(c).some(v=>typeof v==="string" && v.trim()===n)) || {};
}
const todayISO = ()=> new Date().toISOString().slice(0,10);
const dDot = ()=>{ const d=new Date(); return `${String(d.getDate()).padStart(2,"0")}.${String(d.getMonth()+1).padStart(2,"0")}.${d.getFullYear()}`; };
const cntEq = r => { const q=(r["Кількість"]||"1"), t=(r["Тип обладнання"]||""); return t? q+"х"+t : ""; };
const joinNZ = (...a)=> a.filter(x=>x&&String(x).trim()).join(", ");
const GEN_FORMS = {
 zayavka: [
  {k:"num",label:"№ заявки"}, {k:"date",label:"Дата",d:1,v:()=>todayISO()},
  {k:"contract",label:"Договір (№ і дата)",v:(r,c)=>c["Договір"]},
  {k:"client_full",label:"Клієнт (повна назва)",v:(r,c)=>c["Повна назва"]||r["Клієнт"]},
  {k:"client_short",label:"Клієнт (коротка назва)",v:r=>r["Клієнт"]},
  {k:"client_edrpou",label:"ЄДРПОУ клієнта",v:(r,c)=>c["ЄДРПОУ"]},
  {k:"client_dir_gen",label:"Директор клієнта (род. відмінок)",v:(r,c)=>c["Директор (род. відмінок)"]},
  {k:"client_dir_short",label:"Директор (ініціали)",v:(r,c)=>c["Директор (ініціали)"]},
  {k:"services",label:"Узгоджений об'єм послуг",ta:1},
  {k:"route",label:"Маршрут",v:r=>r["Маршрут"]},
  {k:"container",label:"Тип та кількість контейнерів",v:cntEq},
  {k:"con_bl",label:"Номер контейнера / BL",v:r=>joinNZ(r["Контейнер"],r["BL"]).replace(", "," / ")},
  {k:"uktzed",label:"Код УКТЗЕД"},
  {k:"shipper",label:"Відправник (назва, адреса)",ta:1},
  {k:"consignee",label:"Одержувач (назва, адреса)",ta:1,v:(r,c)=>joinNZ(c["Повна назва"]||r["Клієнт"],c["Адреса"])},
  {k:"incoterms",label:"Умови поставки (Інкотермс)"},
  {k:"eta",label:"Дата судозаходу"},
  {k:"pol",label:"Порт завантаження"},
  {k:"pod",label:"Порт розвантаження"},
  {k:"customs_addr",label:"Адреса митного оформлення",v:r=>r["Адреса розмитнення"]},
  {k:"unload_addr",label:"Адреса розвантаження"},
  {k:"price",label:"Вартість послуг",ta:1},
  {k:"other",label:"Інші умови"},
 ],
 zayavka_cma: [
  {k:"req_no",label:"№ заявки"}, {k:"date",label:"Дата (дд.мм.рррр)",v:()=>dDot()},
  {k:"booking",label:"Букінг",v:r=>r["BL"]},
  {k:"route",label:"Маршрут",v:r=>r["Маршрут"]},
  {k:"container",label:"Контейнер (1х40НС)",v:cntEq},
  {k:"weight",label:"Вага"},
  {k:"shipper_name",label:"Відправник (назва)",v:r=>r["Клієнт"]},
  {k:"shipper_edrpou",label:"ЄДРПОУ відправника",v:(r,c)=>c["ЄДРПОУ"]},
  {k:"shipper_addr",label:"Адреса відправника",v:(r,c)=>c["Адреса"]},
  {k:"consignee_name",label:"Отримувач (назва)"},
  {k:"consignee_addr",label:"Адреса отримувача"},
  {k:"loading_addr",label:"Адреса завантаження",ta:1,v:(r,c)=>c["Адреса завантаження"]},
  {k:"loading_contact",label:"Контакт на завантаженні",v:(r,c)=>c["Контакт завантаження"]},
  {k:"loading_dt",label:"Дата і час завантаження"},
  {k:"customs_addr",label:"Адреса замитнення",v:r=>r["Адреса розмитнення"]},
  {k:"customs_note",label:"Примітка по митниці"},
  {k:"load_method",label:"Спосіб завантаження"},
  {k:"goods1",label:"Вантаж 1 (код + назва)"},
  {k:"goods2",label:"Вантаж 2"},
  {k:"goods3",label:"Вантаж 3"},
  {k:"packing",label:"Пакування"},
  {k:"rate",label:"Ставка"},
 ],
 maersk_zayavka: [
  {k:"pickup_dt",label:"Дата і час подачі авто (напр. 27-28.08 на 8.00)"},
  {k:"booking",label:"Номер букінгу",v:r=>r["BL"]},
  {k:"cnt",label:"Кількість контейнерів",v:r=>r["Кількість"]||"1"},
  {k:"cont_type",label:"Тип контейнера",v:r=>r["Тип обладнання"]},
  {k:"line",label:"Судноплавна лінія",v:()=>"Маерск"},
  {k:"goods",label:"Вантаж (англ. / укр.)",v:r=>r["Вантаж"]},
  {k:"weight",label:"Вага брутто вантажу"},
  {k:"loading_addr",label:"Місце завантаження (координати / адреса)",ta:1,v:(r,c)=>c["Адреса завантаження"]},
  {k:"loading_contact",label:"Контакт на завантаженні",v:(r,c)=>c["Контакт завантаження"]},
  {k:"customs_addr",label:"Митниця (координати / адреса, контакт)",ta:1,
    v:(r,c)=>joinNZ(c["Адреса митниці"],c["Контакт митниці"])||r["Адреса розмитнення"]},
  {k:"special",label:"Особливі вимоги"},
  {k:"pol",label:"Порт завантаження",v:r=>r["POL"]},
  {k:"transship",label:"Порт перевалки"},
  {k:"pod",label:"Порт вивантаження",v:r=>r["POD"]},
  {k:"vessel_voyage",label:"Судно / рейс",v:r=>joinNZ(r["Судно"],r["Вояж"]).replace(", ","\nРейс:")},
  {k:"eta",label:"Дата судозаходу"},
  {k:"rate",label:"Узгоджена ставка"},
  {k:"currency",label:"Валюта платежу",v:()=>"USD"},
  {k:"maersk_code",label:"Код компанії в системі Maersk",v:()=>"UA00078237"},
  {k:"maersk_name",label:"Назва компанії в системі Maersk",v:()=>"UNITEX HD LTD"},
  {k:"note",label:"Примітка (рядок «ВАЖНО»)",ta:1},
 ],
 loi: [
  {k:"booking",label:"Букінг",v:r=>r["BL"]},
  {k:"voyage",label:"Вояж",v:r=>r["Вояж"]},
  {k:"place_receipt",label:"Place of Receipt"},
  {k:"place_delivery",label:"Place of Delivery"},
  {k:"container",label:"Контейнер (1x40HC)",v:cntEq},
  {k:"goods",label:"Вантаж (англ.)"},
  {k:"shipper",label:"Shipper (назва, код, адреса)",ta:1},
  {k:"consignee",label:"Consignee (назва, адреса)",ta:1},
  {k:"date",label:"Дата (дд.мм.рр)",v:()=>dDot()},
 ],
 kkk: [
  {k:"num",label:"№ заявки"}, {k:"date",label:"Дата",d:1,v:()=>todayISO()},
  {k:"order_no",label:"Номер замовлення",v:()=>"б/н"},
  {k:"pickup",label:"Пункт відправлення"},
  {k:"ready_date",label:"Готовність вантажу"},
  {k:"destination",label:"Пункт прибуття"},
  {k:"transport_route",label:"Тип транспорту та маршрут",ta:1,v:r=>r["Маршрут"]},
  {k:"customs_from",label:"Митниця в країні відправлення"},
  {k:"border",label:"Пункт перетину кордону"},
  {k:"customs_to",label:"Митниця в країні прибуття"},
  {k:"final_addr",label:"Кінцевий пункт доставки"},
  {k:"truck_type",label:"Тип авто"},
  {k:"weight_cargo",label:"Вага (брутто) + тип вантажу",ta:1},
  {k:"price_text",label:"Загальна вартість (текст)",ta:1},
 ],
 t1: [
  {k:"truck",label:"Держ. номер тягача",v:r=>r["Номер авто"]},
  {k:"trailer",label:"Держ. номер причепа"},
  {k:"border",label:"Прикордонний перехід"},
  {k:"eta",label:"Дата і час прибуття на кордон"},
  {k:"driver_phone",label:"Телефон водія",v:r=>r["Водій (телефон)"]},
  {k:"broker",label:"Брокер (розмитнення) + контакти"},
  {k:"submitter",label:"Відповідальний за подачу + контакти"},
  {k:"invoice_value",label:"Вартість вантажу за інвойсом, EUR"},
  {k:"codes_count",label:"Кількість кодів УКТЗЕД"},
  {k:"open_place",label:"Місце відкриття Т1"},
  {k:"cargo_nature",label:"Характер вантажу"},
  {k:"route",label:"Маршрут (звідки – куди)",v:r=>r["Маршрут"]},
  {k:"date",label:"Дата заявки",d:1,v:()=>todayISO()},
 ],
 akt: [
  {k:"act_no",label:"№ акта"}, {k:"act_date",label:"Дата акта",d:1,v:()=>todayISO()},
  {k:"invoice_no",label:"№ інвойсу"}, {k:"invoice_date",label:"Дата інвойсу (напр. July 8, 2026)"},
  {k:"contract",label:"Договір (номер і дата, англ.)",ta:1,v:(r,c)=>c["Договір"]},
  {k:"container",label:"Контейнер / авто",v:r=>joinNZ(r["Контейнер"],r["Номер авто"])},
  {k:"customer_short",label:"Замовник (коротка назва)",v:r=>r["Клієнт"]},
  {k:"customer_block",label:"Реквізити замовника (кожен рядок з нового рядка)",ta:1,
    v:(r,c)=>joinNZ(c["Повна назва"]||r["Клієнт"], c["Адреса"]).replace(", ","\n")},
  {k:"items",label:"Позиції послуг — по рядку на позицію: опис | к-ть | ціна | сума",ta:1},
  {k:"total",label:"Разом (напр. 2700 €)"},
  {k:"amount_words",label:"Сума прописом (англ.)"},
 ],
 maersk_poa: [
  {k:"bl",label:"Bill of Lading",v:r=>r["BL"]},
  {k:"container",label:"Контейнер(и)",v:r=>r["Контейнер"]},
  {k:"agent",label:"Компанія (release + оплата THC)",ta:1,v:()=>"LLC UNITEX HD (65076, ODESSA REGION, ODESSA, UKRAINE, OFFICE 56 RADISNA STR. 3)"},
  {k:"date",label:"Дата",d:1,v:()=>todayISO()},
 ],
 maersk_loi: [
  {k:"booking",label:"Букінг Maersk",v:r=>r["BL"]},
  {k:"vessel_voyage",label:"Судно / Вояж",v:r=>joinNZ(r["Судно"],r["Вояж"]).replace(", "," / ")},
  {k:"goods",label:"Вантаж (англ.)"},
  {k:"containers",label:"Контейнер(и)",v:r=>r["Контейнер"]},
  {k:"date",label:"Дата",d:1,v:()=>todayISO()},
 ],
 insurance: [
  {k:"cargo",label:"Вантаж (англ. / укр.)"},
  {k:"container",label:"Контейнер(и)",v:r=>r["Контейнер"]},
  {k:"invoice_no",label:"№ інвойсу"},
  {k:"invoice_date",label:"Дата інвойсу (дд.мм.рррр)"},
  {k:"bl",label:"Коносамент / B/L",v:r=>r["BL"]},
  {k:"port",label:"Порт завантаження (напр. Нагоя, Японія)"},
  {k:"date",label:"Дата листа",d:1,v:()=>todayISO()},
 ],
};
const GEN_INP_S = 'style="padding:7px 9px;border:1px solid var(--line);border-radius:7px;background:var(--paper);color:var(--ink);font-size:13px;width:100%;box-sizing:border-box;font-family:inherit"';
async function renderGenForm(){
  const typ = $("gen-type").value, wrap = $("gen-form"), btn = $("gen-btn");
  if (!typ || !DOC_ROW){ wrap.style.display="none"; btn.style.display="none"; return; }
  const c = await clientRec(DOC_ROW["Клієнт"]);
  wrap.innerHTML = GEN_FORMS[typ].map(f=>{
    let v = ""; try{ v = f.v ? (f.v(DOC_ROW, c) || "") : ""; }catch(e){}
    const inp = f.ta
      ? `<textarea data-k="${f.k}" rows="2" class="gen-inp" ${GEN_INP_S}>${esc(v)}</textarea>`
      : `<input data-k="${f.k}" class="gen-inp" type="${f.d?"date":"text"}" value="${esc(v)}" ${GEN_INP_S}>`;
    return `<label style="${f.ta?"grid-column:1/-1;":""}font-size:12px;color:var(--muted);display:flex;flex-direction:column;gap:3px">${esc(f.label)}${inp}</label>`;
  }).join("");
  wrap.style.display = "grid"; btn.style.display = "block"; $("gen-status").textContent = "";
}
$("gen-type").addEventListener("change", renderGenForm);
$("gen-btn").addEventListener("click", async ()=>{
  const typ = $("gen-type").value;
  if (!typ || !DOC_ROW) return;
  const fields = {};
  $("gen-form").querySelectorAll(".gen-inp").forEach(i=>{ fields[i.dataset.k] = i.value; });
  $("gen-status").textContent = "⏳ Формую документ…"; $("gen-btn").disabled = true;
  try{
    const r = await fetch("/gen-doc", {method:"POST",
      headers:{"Content-Type":"application/json","xc-auth": JWT||""},
      body: JSON.stringify({type: typ, dealId: DOC_ROW.Id, fields})});
    const js = await r.json().catch(()=>({}));
    if (!r.ok) throw new Error(js.error || ("HTTP " + r.status));
    DOC_ROW["Файли"] = js.files;
    renderDocList();
    $("gen-status").textContent = "";
    toast("✅ Сформовано та прикріплено: " + js.title);
  } catch(e){
    $("gen-status").textContent = "⚠ Не вдалося сформувати (" + e.message + ")";
  }
  $("gen-btn").disabled = false;
});

/* ===== дані від перевізника: вікно на клітинці «Авто» =====
   Прохання користувачки 25.08.2026: перевізник надсилає повідомлення одним
   шматком (подача, контейнер, водій, номери тягача і причепа, телефон, паспорт,
   пункт перетину, реквізити фірми) — його вставляють у вікно ЯК Є, сторінка
   розбирає текст на поля, людина перевіряє і зберігає. Збереження:
   (а) заповнює поля картки угоди; (б) поповнює довідники «Авто», «Водії»,
   «Перевізники» — НОВИЙ запис або ДОПОВНЕННЯ ПОРОЖНІХ полів наявного, чуже
   ніколи не перезаписується. Тягач і причеп — два окремі записи довідника
   «Авто» без жорсткої прив'язки (причеп змінюється незалежно).
   У таблиці, як і раніше, видно лише номер авто. */
function parseCarrierText(txt){
  const t = String(txt || "");
  const lines = t.split(/\n/).map(l => l.trim()).filter(Boolean);
  const out = {};
  // саме [а-яіїєґ]*, а не \w: у JS \w — лише латиниця, і «подача» на ній обривалась
  const feed = /подач[а-яіїєґ]*\s*(?:на|до|:)?\s*(\d{1,2})[./](\d{1,2})(?:[./](\d{2,4}))?/iu.exec(t);
  if (feed){
    const y = feed[3] ? (feed[3].length === 2 ? "20" + feed[3] : feed[3]) : String(new Date().getFullYear());
    out["подача"] = y + "-" + feed[2].padStart(2, "0") + "-" + feed[1].padStart(2, "0");
  }
  const cont = /\b([A-Z]{4}\d{7})\b/.exec(t);
  if (cont) out["контейнер"] = cont[1];
  // держномер: 2 літери + 4 цифри + 2 літери, кирилиця або латиниця
  const plates = [...t.matchAll(/\b([A-ZА-ЯІЇЄ]{2}\s?\d{4}\s?[A-ZА-ЯІЇЄ]{2})\b/gu)].map(m => m[1].replace(/\s+/g, ""));
  if (plates[0]) out["тягач"] = plates[0];
  if (plates[1]) out["причеп"] = plates[1];
  const pib = lines.find(l => /^[А-ЯІЇЄҐ][а-яіїєґ'’]+\s+[А-ЯІЇЄҐ][а-яіїєґ'’]+\s+[А-ЯІЇЄҐ][а-яіїєґ'’]+$/u.test(l));
  if (pib) out["піб"] = pib;
  const tel = /(?:\+?38)?\s*\(?(0\d{2})\)?[\s\-.]*(\d{3})[\s\-.]*(\d{2})[\s\-.]*(\d{2})/.exec(t);
  if (tel) out["телефон"] = tel[1] + " " + tel[2] + " " + tel[3] + " " + tel[4];
  const pass = /паспорт[:\s]*([A-ZА-ЯІЇЄ]{2}\s?\d{6})/i.exec(t);
  if (pass) out["паспорт"] = pass[1].replace(/\s+/g, "");
  const pp = /^ПП\s+([^\n]+)$/mi.exec(t);
  if (pp) out["перехід"] = ("ПП " + pp[1]).trim();
  const nameLine = lines.find(l => l.includes("«"));
  if (nameLine){
    const m = /«([^»]+)»\s*([^\d]*)(.*)$/.exec(nameLine);
    if (m){
      out["перевізник"] = (m[1] + " " + (m[2] || "").trim()).replace(/\s+/g, " ").trim();
      if ((m[3] || "").trim()) out["адреса"] = m[3].trim();
    }
  }
  const code = /\b(?:code|код)\s*[:№]?\s*(\d{6,12})/i.exec(t);
  if (code) out["код"] = code[1];
  const iban = /\b(UA\d{20,30})\b/.exec(t);
  if (iban){
    out["iban"] = iban[1];
    const ibLine = lines.find(l => l.includes(iban[1]));
    const bank = ibLine && /(?:\bin\b|\bв\b)\s+(.+)$/i.exec(ibLine);
    if (bank) out["банк"] = bank[1].trim();
  }
  const eori = /EORI[:\s–-]*([A-Z0-9]{8,20})/i.exec(t);
  if (eori) out["eori"] = eori[1].replace(/\.$/, "");
  return out;
}

let TRUCK_ROW = null;
function openTruck(r){
  TRUCK_ROW = r;
  $("truck-title").textContent = "🚚 Дані від перевізника — угода №" + (r["Угода"] || "");
  $("truck-hint").textContent = "Вставте повідомлення перевізника як є і натисніть «Розібрати». Кожне поле можна виправити руками перед збереженням.";
  $("truck-msg").textContent = "";
  const F = (id, label, val, ph) => `<div class="fld"><label for="${id}">${label}</label><input id="${id}" type="text" value="${esc(val || "")}" placeholder="${esc(ph || "")}"></div>`;
  $("truck-body").innerHTML = `
    <div class="fld"><label for="trk-raw">Текст від перевізника</label>
      <textarea id="trk-raw" rows="6" placeholder="вставте сюди повідомлення цілком…"></textarea></div>
    <button class="btn ghost" id="trk-parse" style="margin:2px 0 10px">🔍 Розібрати текст</button>
    <div class="fldrow">${F("trk-truck", "Номер авто (тягач)", r["Номер авто"])}${F("trk-trail", "Причеп", r["Причеп"])}</div>
    <div class="fldrow">${F("trk-feed", "Подача (план)", String(r["Подача авто (план)"] || "").slice(0, 10), "РРРР-ММ-ДД")}${F("trk-pp", "Пункт перетину", r["Пункт перетину"])}</div>
    <div class="fldrow">${F("trk-pib", "Водій (ПІБ)", r["Водій (ПІБ)"])}${F("trk-tel", "Водій (телефон)", r["Водій (телефон)"])}</div>
    <div class="fldrow">${F("trk-pass", "Водій (паспорт)", r["Водій (паспорт)"])}${F("trk-cont", "Контейнер (звірка з угодою)", "")}</div>
    <h3 style="margin:10px 0 4px;font-size:14px">Перевізник — піде в довідник</h3>
    <div class="fldrow">${F("trk-carr", "Назва", r["Перевізник"])}${F("trk-code", "Код", "")}</div>
    <div class="fldrow">${F("trk-iban", "IBAN", "")}${F("trk-bank", "Банк", "")}</div>
    <div class="fldrow">${F("trk-eori", "EORI", "")}${F("trk-addr", "Адреса", "")}</div>
    <p class="sub" id="trk-note"></p>`;
  $("trk-parse").addEventListener("click", () => {
    const p = parseCarrierText($("trk-raw").value);
    const setIf = (id, v) => { if (v && $(id)) $(id).value = v; };
    setIf("trk-truck", p["тягач"]);   setIf("trk-trail", p["причеп"]);
    setIf("trk-feed", p["подача"]);   setIf("trk-pp", p["перехід"]);
    setIf("trk-pib", p["піб"]);       setIf("trk-tel", p["телефон"]);
    setIf("trk-pass", p["паспорт"]);  setIf("trk-cont", p["контейнер"]);
    setIf("trk-carr", p["перевізник"]); setIf("trk-code", p["код"]);
    setIf("trk-iban", p["iban"]);     setIf("trk-bank", p["банк"]);
    setIf("trk-eori", p["eori"]);     setIf("trk-addr", p["адреса"]);
    /* контейнер із тексту звіряємо з угодою: якщо це чужий запит — краще
       побачити ДО збереження, ніж шукати потім, куди поїхали чужі дані */
    const dealCont = String(TRUCK_ROW["Контейнер"] || "");
    $("trk-note").textContent =
      p["контейнер"] && dealCont && !dealCont.includes(p["контейнер"])
        ? "⚠ У тексті контейнер " + p["контейнер"] + ", а в угоді " + dealCont + " — перевірте, чи до тієї угоди цей запит."
        : (p["контейнер"] && dealCont ? "✓ Контейнер збігається з угодою." : "");
    $("truck-msg").textContent = Object.keys(p).length ? "" : "⚠ Не знайшла у тексті жодного знайомого поля — заповніть руками.";
  });
  $("truck-overlay").classList.add("open");
}
/* Довідники: новий запис або доповнення ПОРОЖНІХ полів наявного.
   Непорожні значення в довіднику не перезаписуються ніколи. */
async function truckUpserts(v){
  const up = async (table, keyCol, keyVal, fields) => {
    if (!keyVal || !T[table]) return;
    try{
      const js = await api(`/api/v2/tables/${T[table]}/records?limit=1000`);
      const hit = (js.list || []).find(x => String(x[keyCol] || "").trim().toLowerCase() === keyVal.toLowerCase());
      if (!hit){
        await api(`/api/v2/tables/${T[table]}/records`, {method: "POST",
          body: JSON.stringify([Object.assign({[keyCol]: keyVal}, fields)])});
        logAction("довідник: додано", table + ": " + keyVal, "", "", "");
        return;
      }
      const fill = {};
      for (const [k, val] of Object.entries(fields))
        if (val && !String(hit[k] || "").trim()) fill[k] = val;
      if (Object.keys(fill).length){
        await api(`/api/v2/tables/${T[table]}/records`, {method: "PATCH",
          body: JSON.stringify([Object.assign({Id: hit.Id}, fill)])});
        logAction("довідник: доповнено", table + ": " + keyVal, Object.keys(fill).join(", "), "", "");
      }
    }catch(e){ toast("⚠ Довідник «" + table + "» не оновився: " + e.message); }
  };
  await up("Авто", "Номер", v("trk-truck"), {"Тип": "тягач", "Перевізник": v("trk-carr")});
  await up("Авто", "Номер", v("trk-trail"), {"Тип": "причеп", "Перевізник": v("trk-carr")});
  await up("Водії", "ПІБ", v("trk-pib"), {"Телефон": v("trk-tel"), "Паспорт": v("trk-pass"), "Перевізник": v("trk-carr")});
  await up("Перевізники", "Назва", v("trk-carr"), {"Код": v("trk-code"), "IBAN": v("trk-iban"), "Банк": v("trk-bank"), "EORI": v("trk-eori"), "Адреса": v("trk-addr")});
}
$("truck-close").addEventListener("click", () => $("truck-overlay").classList.remove("open"));
$("truck-overlay").addEventListener("click", e => { if (e.target === $("truck-overlay")) $("truck-overlay").classList.remove("open"); });
$("truck-save").addEventListener("click", async () => {
  const r = TRUCK_ROW;
  if (!r) return;
  const v = id => String(($(id) || {}).value || "").trim();
  const map = [["Номер авто", "trk-truck"], ["Причеп", "trk-trail"], ["Водій (ПІБ)", "trk-pib"],
               ["Водій (телефон)", "trk-tel"], ["Водій (паспорт)", "trk-pass"], ["Пункт перетину", "trk-pp"],
               ["Перевізник", "trk-carr"], ["Подача авто (план)", "trk-feed"]];
  const patch = {};
  for (const [col, id] of map){
    const val = v(id);
    if (val && String(r[col] || "").trim() !== val) patch[col] = val;
  }
  if (!Object.keys(patch).length){ $("truck-msg").textContent = "Немає що зберігати — жодне поле не змінилось."; return; }
  $("truck-save").disabled = true;
  try{
    await api(`/api/v2/tables/${T["Диспетчеризація"]}/records`, {method: "PATCH",
      body: JSON.stringify([Object.assign({Id: r.Id}, patch)])});
    for (const col of Object.keys(patch)){
      logAction("правка угоди", "Угода №" + (r["Угода"] || r.Id), col, r[col], patch[col]);
      r[col] = patch[col];
    }
    await truckUpserts(v);      // довідники після угоди; їх помилка збереження не валить
    toast("✅ Збережено: " + Object.keys(patch).join(", "));
    $("truck-overlay").classList.remove("open");
    redrawDisp(r.Id);
  }catch(err){ $("truck-msg").textContent = "⚠ Не збереглось: " + err.message; }
  $("truck-save").disabled = false;
});

const CARD_GROUPS = [
  ["Основне", ["Угода","Напрямок","Клієнт","Лінія","Вид перевезення","FCL/LCL","Тип","Умови поставки (Інкотермс)","Перевізник","Агент","Маршрут","ПОО","POL","POD","FD","Митне оформлення","Кінцева точка доставки","HBL","BL","Контейнер","Вантаж","Тип обладнання","Кількість","Вивіз (Carrier/Merchant)","Сухий порт","Адреса розмитнення"]],
  ["Море", ["Судно","Вояж","Контейнер (лінія)","Звірка","Статус","Етап (Експедитор)","ETA","ETD (план)","ETD (факт)","ETA порт (план)","ETA порт (факт)","Порт перевалки","Перевалка (прибуття)","Перевалка (відправлення)","Зміни ETA (історія)","Остання зміна","Останнє оновлення","Статус (джерело)","Статус (оновлено)","Трекінг (стан)"]],
  ["Дати на землі", ["Stuffing","Подача авто (план)","Подача авто (факт)","Port Cut Off","Гейт ін","Здача в порт (факт)","Вивантаження в порту (факт)","Гейт аут","ETA сухий порт","Gate out for delivery","Постановка/завантаження (план)","Постановка/завантаження (факт)","На кордоні","Перетин кордону (факт)","Планова до клієнта (план)","Планова до клієнта (факт)","Вивантаження у отримувача (факт)"]],
  ["Авто і документи", ["Номер авто","Причеп","Номер ЦМР","Водій (ПІБ)","Водій (телефон)","Водій (паспорт)","Пункт перетину","Телекс","Т1","ДО","Документи","SI","Замитнення","Реліз"]],
  ["Команда і коментарі", ["Менеджер","Оп. менеджер","Лист (джерело)","Нагадування","Коментар","Коментар клієнту"]],
];
const LOGIST_GROUPS = [
  ["Основне", ["Угода","Клієнт","Контейнер","Статус","Маршрут","Сухий порт"]],
  ["Авто", ["Номер авто","Причеп","Номер ЦМР","Водій (ПІБ)","Водій (телефон)","Водій (паспорт)","Пункт перетину","Перетин кордону (факт)","Постановка/завантаження (план)","Постановка/завантаження (факт)"]],
];
/* ===== картка угоди: перегляд + редагування =====
   Поля, які веде Експедитор (AUTHORITATIVE у expeditor_direct_sync.py), редагувати
   не даємо — синхронізація о 07:00 їх усе одно перезапише. Решту можна правити:
   клік по значенню → поле, Enter/клік поза межами — зберегти, Esc — скасувати.
   Галочки (Позначки) перемикаються одним кліком. */
const CARD_LOCKED = {"Угода":1,"Клієнт":1,"Напрямок":1,"Лінія":1,"Менеджер":1,"Агент":1,
                     /* «Контейнер» ВІДКРИТО на правку 25.08.2026 (прохання користувачки:
                        «прибери заборону на додавання контейнера»). Правило старшинства
                        лишилось у синхронізації: поки в Експедиторі поле порожнє —
                        живе введене тут; щойно в Експедиторі з'явиться свій номер —
                        він переважить (Контейнер в AUTHORITATIVE). */
                     "Етап (Експедитор)":1,"Зміни ETA (історія)":1,
                     "Остання зміна":1,"Останнє оновлення":1,"Файли":1,
                     /* хто і коли поставив статус — службові позначки, їх пишуть
                        синхронізація, трекінги і сам фасад при ручній правці;
                        редагувати руками нема сенсу (05.08.2026) */
                     "Статус (джерело)":1,"Статус (оновлено)":1,"Трекінг (стан)":1,
                     /* Ланки маршруту веде Експедитор (03.08.2026): вони збираються
                        з POL → POD → DR → FD, правити їх у платформі безглуздо —
                        синхронізація перезапише. Міняти треба в угоді.
                        А сам «Маршрут» лишається ВІДКРИТИМ на правку — рішення
                        користувачки 14.08.2026 «відкритий в двох місцях»: у таблиці
                        він завжди був редагований, тепер так само і в картці.
                        Втрати не буде: merge_route у синхронізації нічого не пише,
                        якщо бодай одна наявна ланка зникла б. */
                     "ПОО":1,"POL":1,"POD":1,"FD":1,"Митне оформлення":1};
const CARD_DATE = /^(ETA|ETD|Факт|Подача|Постановка|Перетин|Планова|Вивантаження|Гейт|Port Cut Off|Замитнення)/;
const CARD_SELECT = {"Статус":()=>Object.keys(STATUSES),
                     "Вид перевезення":()=>MODE_OPTIONS,
                     "FCL/LCL":()=>["FCL","LCL","FTL","LTL"],
                     // Merchant / Carrier haulage — від цього залежать норми вільного
                     // часу (free time) і майбутній розрахунок демереджу й детеншену.
                     // Колонка лишається текстовою: у 46 угодах уже стоїть «Carrier»,
                     // тип не міняємо, щоб не ризикувати даними (01.08.2026).
                     "Вивіз (Carrier/Merchant)":()=>["Carrier","Merchant"],
                     // Інкотермс 2020 + DDU (скасований у 2010-му, але в договорах
                     // трапляється). Від DAP/DDU залежить, чи показувати клієнту
                     // імпортне розмитнення й доставку на схемі експорту (02.08.2026).
                     "Умови поставки (Інкотермс)":()=>["EXW","FCA","FAS","FOB","CFR","CIF",
                                                       "CPT","CIP","DAP","DPU","DDP","DDU"]};
const CARD_LONG = {"Коментар":1,"Коментар клієнту":1,"Маршрут":1,"Адреса розмитнення":1,"Вантаж":1};
/* Підпис поля в картці ≠ назва колонки в базі. Колонку не перейменовуємо (на неї
   зав'язані синхронізація і кабінет), а показуємо зрозумілу назву + попередження,
   що це єдиний коментар, який бачить клієнт (прохання користувачки 02.08.2026).
   Внутрішній «Коментар» у кабінет НЕ виходить. */
const CARD_LABEL = {"Коментар клієнту":"Коментар для клієнта",
                    "Коментар":"Коментар (внутрішній)",
                    "ПОО":"ПОО — точка завантаження",
                    "POL":"POL — порт завантаження",
                    "POD":"POD — порт вивантаження",
                    "FD":"FD — кінцевий пункт доставки",
                    "Митне оформлення":"Митне оформлення (митний перехід)"};
const CARD_NOTE  = {"Коментар клієнту":"це поле клієнт бачить у своєму кабінеті",
                    "Коментар":"службова нотатка — клієнту не показується",
                    "Маршрут":"збирається автоматично з POL → POD → сухий порт → FD",
                    "ПОО":"з угоди в Експедиторі, довідник «Города». Перша ланка маршруту",
                    "POL":"з угоди в Експедиторі, довідник «Города»",
                    "POD":"з угоди в Експедиторі, довідник «Города»",
                    "FD":"з угоди в Експедиторі, довідник «Города»",
                    "Митне оформлення":"з угоди в Експедиторі, реквізит «Пункт пересечения границы»"};
let MODE_OPTIONS = ["фрахт","фрахт+ТЕО","фрахт+ТЕО+МО","фрахт+ТЕО+авто","фрахт+ТЕО+залізниця",
                    "ТЕО+авто","ТЕО+залізниця","авто","авіа","авіа+ТЕО","авіа+ТЕО+МО"];

/* ===== журнал дій =====
   Пише, хто, коли і що змінив. Таблиця «Журнал дій» (створює create_audit_table.py).
   Якщо таблиці немає або запис не вдався — мовчки пропускаємо: журнал не має
   ламати саму роботу. Вхід, правки й завантаження документів фіксуються. */
async function logAction(action, obj, field, before, after){
  const tid = T["Журнал дій"];
  if (!tid) return;
  try{
    await api(`/api/v2/tables/${tid}/records`, {method:"POST", body: JSON.stringify([{
      "Час": new Date().toISOString(),
      "Користувач": (sessionStorage.getItem("email") || UNAME || "—"),
      "Роль": ROLE || "—",
      "Дія": action,
      "Обʼєкт": obj == null ? "" : String(obj),
      "Поле": field == null ? "" : String(field),
      "Було": before == null ? "" : String(before).slice(0, 500),
      "Стало": after == null ? "" : String(after).slice(0, 500),
    }])});
  }catch(e){ /* журнал не критичний */ }
}

/* Маршрут завжди показуємо і зберігаємо зі стрілочками, як би його не ввели:
   «Долина - Роттердам», «Долина -Роттердам», «Долина -> Роттердам», «Долина — Роттердам»
   → «Долина → Роттердам». Дефіс БЕЗ пробілів не чіпаємо — інакше зламаються
   назви на кшталт «Порт-Саїд» чи «Кам'янець-Подільський» (02.08.2026). */
function routeArrows(v){
  return String(v == null ? "" : v)
    .replace(/\s*(?:-->|->|→|—|–)\s*/g, " → ")   // стрілки й довгі тире
    .replace(/\s+-\s*|\s*-\s+/g, " → ")        // дефіс, у якого є пробіл хоча б з одного боку
    .replace(/\s*→\s*/g, " → ")
    .replace(/\s{2,}/g, " ")
    .trim();
}

/* Ручна зміна статусу підписується людиною (05.08.2026). Саме на цю позначку
   дивляться синхронізація і трекінги: те, що поставила людина, автомат більше не
   перебиває. Дата потрібна, щоб було видно, наскільки значення свіже. */
const withSrc = (col, patch) => (col === "Статус")
  ? {...patch, "Статус (джерело)": "людина", "Статус (оновлено)": new Date().toISOString().slice(0,10)}
  : patch;

async function saveField(row, col, val){
  if (col === "Маршрут") val = routeArrows(val);   // зберігаємо вже нормалізовано
  const before = row[col];
  const body = withSrc(col, {Id: row.Id, [col]: val});
  await api(`/api/v2/tables/${T["Диспетчеризація"]}/records`, {method:"PATCH",
    body: JSON.stringify([body])});
  row[col] = val;
  if (col === "Статус"){ row["Статус (джерело)"] = "людина"; row["Статус (оновлено)"] = body["Статус (оновлено)"]; }
  logAction("правка угоди", "Угода №" + (row["Угода"] || row.Id), col, before, val);
}

function cardVal(r, f){
  if (FLAGS.includes(f)) return r[f] ? "✓ так" : "—";
  const v = r[f];
  if (v===null || v===undefined || v==="") return "—";
  if (CARD_DATE.test(f) && !CARD_SELECT[f]){ const d = fmtD(v); if (d) return d; }
  if (f === "Маршрут") return routeArrows(v);
  return String(v);
}

function openRow(r){
  const groups = cfg().cols === "logist" ? LOGIST_GROUPS : CARD_GROUPS;
  const canEdit = !!cfg().edit;
  $("row-title").textContent = `Угода №${r["Угода"]} · ${r["Клієнт"]||""}`;
  $("row-hint").innerHTML = canEdit
    ? 'дані живі з бази · <b>клік по значенню</b> — редагувати, <b>Enter</b> — зберегти, <b>Esc</b> — скасувати · галочки перемикаються одним кліком · <span title="це поле веде Експедитор">🔒</span> — поле з Експедитора, правити не можна'
    : "повна картка угоди · дані живі з бази";
  $("row-body").innerHTML = groups.map(([g,fields])=>{
    const items = fields.map(f=>{
      const locked = !canEdit || CARD_LOCKED[f];
      const cell = f === "Статус" ? stPill(r["Статус"])
        : FLAGS.includes(f) ? `<span class="flag ${r[f]?"on":""}">${r[f]?"✓ так":"—"}</span>`
        : esc(cardVal(r, f));
      return `<tr><td class="cell-muted" style="width:45%">${esc(CARD_LABEL[f] || f)}${locked && canEdit && CARD_LOCKED[f]
          ? ' <span class="cell-muted" title="це поле веде Експедитор — правити тут немає сенсу">🔒</span>' : ""}${
          CARD_NOTE[f] ? `<br><span class="cell-muted" style="font-size:11px">${esc(CARD_NOTE[f])}</span>` : ""}</td>
        <td class="${locked?"":"cardedit"}" data-f="${esc(f)}">${cell}</td></tr>`;
    }).join("");
    return `<h3 style="margin-top:14px">${g}</h3><div class="tablewrap"><table><tbody>${items}</tbody></table></div>`;
  }).join("");
  if (canEdit) $("row-body").querySelectorAll("td.cardedit").forEach(td=>
    td.addEventListener("click", ()=>editCardField(td, r)));
  renderDealTasks(r);            // задачі по цій угоді — тут же, в картці
  $("row-overlay").classList.add("open");
}

/* Задачі по конкретній угоді просто в її картці — щоб «постановка задач по
   угодам» починалась там, де людина на угоду й дивиться (вимога 12.08.2026).
   Блок домальовується окремо і асинхронно: картка не повинна чекати на задачі,
   а якщо їх не вдалося прочитати — це видно, а не виглядає як «задач немає». */
async function renderDealTasks(r){
  const num = String(r["Угода"] || "").trim();
  /* Блок перемальовується після закриття задачі — старий прибираємо, інакше
     їх ставало б два, три, чотири. */
  const old = $("row-tasks");
  if (old) old.remove();
  const box = document.createElement("div");
  box.id = "row-tasks";
  const head = '<h3 style="margin-top:16px">✅ Задачі по угоді</h3>';
  box.innerHTML = head + '<p class="sub">завантажую…</p>';
  $("row-body").appendChild(box);
  let list = [], users = [];
  try{
    list = (await taskRows()).filter(t=>num && String(t["Угода"]||"").trim() === num);
    try{ users = await taskUsers(); }catch(e){ users = []; }
  }catch(e){
    box.innerHTML = head + `<p class="sub">⚠ Не вдалося прочитати задачі (${esc(e.message)}).</p>`;
    return;
  }
  const open = list.filter(taskIsOpen).sort((a,b)=>String(a["Термін"]||"9999").localeCompare(String(b["Термін"]||"9999")));
  const done = list.filter(t=>!taskIsOpen(t));
  box.innerHTML = head +
    (open.length ? `<div class="tasklist">${open.map(t=>taskRowHtml(t, users)).join("")}</div>`
                 : '<p class="sub">Відкритих задач по цій угоді немає.</p>') +
    (done.length ? `<p class="sub" style="margin-top:6px">закритих: ${done.length}</p>` : "") +
    (canTask() ? '<button class="btn ghost" id="row-task-add" style="margin-top:10px">➕ Задача по цій угоді</button>' : "");
  if ($("row-task-add")) $("row-task-add").addEventListener("click", ()=>
    openTask(null, {"Тип":"Угода", "Угода": num}));
  box.querySelectorAll(".taskrow[data-task]").forEach(el=>el.addEventListener("click", e=>{
    if (e.target.closest("[data-done]")) return;
    const t = list.find(x=>String(x.Id) === el.dataset.task);
    if (t) openTask(t, {});
  }));
  box.querySelectorAll("[data-done]").forEach(b=>b.addEventListener("click", async ()=>{
    const t = list.find(x=>String(x.Id) === b.dataset.done);
    if (!t) return;
    b.disabled = true; b.textContent = "…";
    try{ await saveTask({Id: t.Id, "Статус":"Виконано", "Виконано": todayISO()}, t, "закрито задачу");
         toast("✅ Задачу виконано"); renderDealTasks(r); }
    catch(err){ b.disabled = false; b.textContent = "✓"; toast("⚠ Не збереглось: " + err.message); }
  }));
}

/* Перемалювати таблицю під карткою після правки в картці.
   Захист від виклику не з тієї сторінки: якщо таблиці на екрані немає,
   draw() впав би на $("drows"). Помилка перемальовування не повинна
   виглядати як «не збереглося» — запис до цього моменту вже пройшов. */
function redrawDisp(id){
  if (typeof DISP_REDRAW !== "function" || !$("drows")) return;
  try{ DISP_REDRAW(id); }catch(e){ /* таблиці зараз немає — нічого не робимо */ }
}

function editCardField(td, r){
  const f = td.dataset.f;
  if (td.querySelector(".edinput")) return;
  // галочка — просто перемикаємо
  if (FLAGS.includes(f)){
    const nv = !r[f];
    td.innerHTML = '<span class="cell-muted">…</span>';
    saveField(r, f, nv)
      .then(()=>{ td.innerHTML = `<span class="flag ${nv?"on":""}">${nv?"✓ так":"—"}</span>`;
                  toast(`✅ ${f}: ${nv?"так":"ні"}`); redrawDisp(r.Id); })
      .catch(e=>{ td.innerHTML = `<span class="flag ${r[f]?"on":""}">${r[f]?"✓ так":"—"}</span>`;
                  toast("⚠ Не збереглось: " + e.message); });
    return;
  }
  const cur = r[f] === null || r[f] === undefined ? "" : String(r[f]);
  const isDate = CARD_DATE.test(f) && !CARD_SELECT[f];
  const val0 = isDate ? cur.slice(0,10) : cur;
  const keep = td.innerHTML;
  td.innerHTML = CARD_SELECT[f]
    ? `<select class="edinput"><option value=""></option>${CARD_SELECT[f]().map(o=>
        `<option${o===cur?" selected":""}>${esc(o)}</option>`).join("")}</select>`
    : CARD_LONG[f]
      ? `<textarea class="edinput" rows="3">${esc(val0)}</textarea>`
      : isDate ? dateEditorHTML(val0)
        : `<input class="edinput" type="text" value="${esc(val0)}">`;
  const inp = td.querySelector(".edinput");
  roomForEditor(td);
  inp.focus();
  if (inp.tagName === "INPUT" && !isDate) inp.select();
  let closed = false;
  const finish = async (save) => {
    if (closed) return;
    closed = true;
    let v = String(inp.value || "").trim();
    if (isDate){
      const iso = parseUserDate(v);
      if (iso === null){                         // не зрозуміли — не зберігаємо
        closed = false;
        toast("⚠ Не зрозуміла дату «" + v + "». Формат: " + DATE_HINT);
        inp.focus(); inp.select();
        return;
      }
      v = iso;
    }
    if (!save || v === val0){ td.innerHTML = keep; return; }
    try{
      await saveField(r, f, v || null);
      td.innerHTML = f === "Статус" ? stPill(v)
        : (isDate ? (fmtD(v) || "—") : esc(v || "—"));
      toast(`✅ ${f}: ${v || "очищено"}`);
      redrawDisp(r.Id);
    }catch(e){ td.innerHTML = keep; toast("⚠ Не збереглось: " + e.message); }
  };
  inp.addEventListener("blur", ()=>finish(true));
  inp.addEventListener("keydown", e=>{
    if (e.key === "Enter" && inp.tagName !== "TEXTAREA"){ e.preventDefault(); finish(true); }
    if (e.key === "Escape"){ e.preventDefault(); finish(false); }
  });
  if (CARD_SELECT[f]) inp.addEventListener("change", ()=>finish(true));
  if (isDate) bindDatePair(td.querySelector(".dted"), ()=>finish(true));
}
$("row-close").addEventListener("click",()=>$("row-overlay").classList.remove("open"));
$("row-overlay").addEventListener("click",e=>{ if(e.target===$("row-overlay")) $("row-overlay").classList.remove("open"); });

PAGES.clients = async () => {
  const disp = scoped(await dispRows());
  const cnt = {};
  disp.forEach(r=>{ const k=(r["Клієнт"]||"").trim(); if(!k) return; cnt[k]=cnt[k]||{all:0,act:0}; cnt[k].all++; if(r["Статус"]!=="Вантаж доставлено") cnt[k].act++; });
  const names = Object.keys(cnt).sort((a,b)=>cnt[b].act-cnt[a].act || cnt[b].all-cnt[a].all);

  /* Відкриті задачі по клієнту — щоб «постановка задач по клієнтам» була видна
     там, де на клієнта й дивляться (12.08.2026). Рахуємо і задачі з типом
     «Клієнт», і ті, що поставлені по його угодах. Якщо задачі не прочитались —
     колонку не показуємо взагалі, замість того щоб малювати всюди нулі. */
  let tByClient = null;
  try{
    const tasks = (await taskRows()).filter(taskIsOpen);
    const clientOfDeal = {};
    disp.forEach(r=>{ const d=String(r["Угода"]||"").trim(); if(d) clientOfDeal[d] = (r["Клієнт"]||"").trim(); });
    tByClient = {};
    tasks.forEach(t=>{
      const c = String(t["Клієнт"]||"").trim() || clientOfDeal[String(t["Угода"]||"").trim()] || "";
      if (c) tByClient[c] = (tByClient[c]||0) + 1;
    });
  }catch(e){ tByClient = null; }

  $("content").innerHTML = `
    <div class="card"><p class="sub">з угод диспетчеризації${cfg().scope!=="all"?" · лише твої":""}${
        tByClient ? " · задачі — відкриті, по клієнту і по його угодах" : ""}</p>
      <div class="tablewrap"><table>
        <thead><tr><th>Клієнт</th><th class="num">Угод всього</th><th class="num">Активних</th>${
          tByClient ? '<th class="num">Задач</th>' : ""}</tr></thead>
        <tbody>${names.map(n=>`<tr><td><b>${esc(n)}</b></td><td class="num">${cnt[n].all}</td><td class="num">${cnt[n].act}</td>${
          tByClient ? `<td class="num">${tByClient[n] || "—"}</td>` : ""}</tr>`).join("")}</tbody>
      </table></div></div>`;
};

PAGES.crm = async () => {
  $("content").innerHTML = `<div class="card"><h3>🗂 CRM</h3>
    <p class="sub">клієнти, контакти, угоди в роботі, історія спілкування</p>
    <div class="note">🛠 Розділ у розробці. Скажи, що має бути всередині — і зроблю: воронка запитів,
      картка контакту, історія листування, нагадування, джерело клієнта.</div></div>`;
};

/* ===== БУХ. ОБЛІК → «Локальні витрати за кордоном» =====
   Таблиця угод, у яких профіт більший за винагороду експедитора: різницю компанія
   переказує за кордон як локальні витрати. Дані рахує finrep/local_costs.py з
   Експедитора (OData) і кладе в computed/local_costs.json; сюди вони приходять через
   /finrep-data?name=localcosts (та сама рольова перевірка, що й для фінзвітів). */
PAGES.accounting = async () => {
  $("content").innerHTML = `<div class="card"><h3>🧾 Бухгалтерський облік</h3>
    <p class="sub">локальні витрати за кордоном — угоди, де профіт більший за винагороду експедитора</p>
    <div class="note">⏳ Рахую по кожній угоді…</div></div>`;
  let js;
  try { js = await fetchFin("localcosts"); }
  catch(e){
    $("content").innerHTML = `<div class="card"><h3>🧾 Бухгалтерський облік</h3>
      <div class="note">⚠ Не вдалося отримати дані: ${esc(e.message)}</div></div>`;
    return;
  }
  // /finrep-data віддає {file, mtime, data} — самі рядки лежать у .data
  const d = js.data || {};
  const rows = d.rows || [];
  // Маршруту в Експедиторі немає (поля «Пункт відправлення/призначення» порожні в усіх
  // угодах) — беремо його з таблиці диспетчеризації платформи за номером угоди.
  // Звідти ж підстраховуємо коносамент і контейнер, якщо в Експедиторі порожньо.
  try {
    const byNum = new Map();
    (await dispRows()).forEach(r => byNum.set(String(r["Угода"]||"").trim(), r));
    rows.forEach(r => {
      const p = byNum.get(String(r.num));
      if (!p) return;
      r.route = r.route || String(p["Маршрут"]||"").trim();
      r.bl = r.bl || String(p["BL"]||"").trim();
      r.cont = r.cont || String(p["Контейнер"]||"").trim();
      // позначка переказу живе в платформі (колонки створені add_transfer_columns.py)
      r._row = p;
      r.sent = !!p["Переказ за кордон"];
      r.sentDate = String(p["Дата переказу"]||"").slice(0,10);
      r.sentAmt = p["Сума переказу"];
    });
  } catch(e){
    /* Було: помилка мовчки ковталась, і таблиця показувалась так, ніби переказів
       не було ЖОДНОГО — плитка «Уже переказано» давала 0, а в колонці стояло
       «цієї угоди немає в таблиці». Бухгалтер міг зробити повторний переказ.
       Тепер кажемо прямо: цифри неповні, і чому. */
    sysWarn("Дані диспетчеризації не завантажились (" + (e.message || "збій зв'язку") +
            "). У таблиці немає маршрутів і, найважливіше, НЕ ВИДНО позначок про " +
            "вже зроблені перекази — не орієнтуйся на них, поки не оновиш сторінку.");
  }
  const pos = rows.filter(r => r.diff > 0);
  const stamp = js.mtime ? new Date(js.mtime*1000).toLocaleString("uk-UA",
      {day:"2-digit",month:"2-digit",hour:"2-digit",minute:"2-digit"}) : "—";

  $("page-actions").innerHTML = `
    <span style="display:inline-flex;flex-direction:column;gap:2px">
      <button class="btn" id="lc-recalc" title="дані станом на ${stamp}">⟳ Перерахувати з Експедитора</button>
      <span id="lc-note"></span></span>
    <button class="btn ghost" id="lc-csv">⬇ Вивантажити в CSV</button>
    <button class="btn" id="acc-tax">🧾 Єдиний податок</button>
    <button class="btn" id="acc-transit">💸 Транзитні перекази</button>`;
  $("acc-tax").addEventListener("click", () => renderSingleTax());
  $("acc-transit").addEventListener("click", () => renderTransit());

  $("content").innerHTML = `
  <div class="card">
    <h3>🌍 Локальні витрати за кордоном</h3>
    <p class="sub">угоди зі статусами ${esc((d.statuses||[]).join(", "))}, де рахунок клієнту
      сплачений на <b>${esc((d.accounts||[d.account||"—"]).join(" або "))}</b> ·
      дані з Експедитора станом на ${stamp}</p>
    <div class="tiles" style="margin-top:12px">
      <div class="tile tready"><div class="tbody"><div class="lbl">Угод із різницею</div>
        <div class="val">${pos.length}</div><div class="hint">з ${rows.length} переглянутих</div></div></div>
      <div class="tile tready"><div class="tbody"><div class="lbl">Ще не переказано</div>
        <div class="val">${fmtN(pos.filter(r=>!r.sent).reduce((s,r)=>s+r.diff,0), 2)}</div>
        <div class="hint">УО · ${pos.filter(r=>!r.sent).length} угод</div></div></div>
      <div class="tile tready"><div class="tbody"><div class="lbl">Уже переказано</div>
        <div class="val">${fmtN(pos.filter(r=>r.sent).reduce((s,r)=>s+(Number(r.sentAmt)||r.diff),0), 2)}</div>
        <div class="hint">УО · ${pos.filter(r=>r.sent).length} угод із позначкою</div></div></div>
      <div class="tile tready"><div class="tbody"><div class="lbl">Уже виділено в рахунках</div>
        <div class="val">${fmtN(rows.reduce((s,r)=>s+(r.local_abroad||0),0), 2)}</div>
        <div class="hint">стаття «Локальні витрати за кордоном»</div></div></div>
    </div>
    <div class="note" style="margin-top:12px">
      <b>Як рахується:</b> профіт = надходження від клієнта на рахунки
      ${esc((d.accounts||[d.account||"—"]).join(" / "))} мінус витрати, оплачені з тих самих
      рахунків (в УО).
      Винагорода = рядки тих самих доходних рахунків зі статтею «Винагорода експедитора».
      ${(d.info_articles||[]).length
        ? `До профіту додано статті ${d.info_articles.map(esc).join(", ")}, якщо по угоді
           їх разом більше ${fmtN(d.info_min,0)} УО.`
        : `⚠ Інфо та банківські комісії поки не додані.`}
      Різниця = профіт (+ інфо та комісії) − винагорода; типово показані тільки додатні.
    </div>
    <div class="filters" style="margin-top:12px">
      <input id="lc-q" placeholder="пошук: угода, коносамент, контейнер, маршрут" style="min-width:250px">
      <select id="lc-st"><option value="">Усі статуси</option>
        ${[...new Set(rows.map(r=>r.status))].map(s=>`<option>${esc(s)}</option>`).join("")}</select>
      <select id="lc-base" title="за якою датою відбирати період">
        <option value="paid">період за оплатою клієнта</option>
        <option value="date">період за датою угоди</option>
        <option value="completed">період за датою завершення</option></select>
      <input type="date" id="lc-from" title="період з"><input type="date" id="lc-to" title="період по">
      <select id="lc-sent"><option value="">переказ: усі</option>
        <option value="no">ще не переказано</option><option value="yes">уже переказано</option></select>
      <label style="display:flex;align-items:center;gap:6px;font-size:13px">
        <input type="checkbox" id="lc-all"> показати й угоди без різниці</label>
      <button class="btn ghost" id="lc-reset" style="padding:4px 10px;font-size:12.5px">скинути</button>
      <span id="lc-count" class="sub"></span>
    </div>
    <div id="lc-table"></div>
  </div>`;

  const visible = () => {
    const q = ($("lc-q").value||"").trim().toLowerCase();
    const st = $("lc-st").value, base = $("lc-base").value;
    const from = $("lc-from").value, to = $("lc-to").value, sent = $("lc-sent").value;
    const all = $("lc-all").checked;
    return rows.filter(r => {
      if (!all && r.diff <= 0) return false;
      if (st && r.status !== st) return false;
      if (sent === "yes" && !r.sent) return false;
      if (sent === "no" && r.sent) return false;
      if (from || to){
        const dt = r[base] || "";          // дати у форматі РРРР-ММ-ДД — порівнюються як текст
        if (!dt) return false;             // без дати в період не потрапляє
        if (from && dt < from) return false;
        if (to && dt > to) return false;
      }
      return !q || [r.num,r.bl,r.cont,r.route].join(" ").toLowerCase().includes(q);
    });
  };
  const dmy = v => v ? esc(String(v).slice(0,10).split("-").reverse().join(".")) : "";
  const draw = () => {
    const list = visible();
    const sum = list.filter(r=>!r.sent).reduce((s,r)=>s+r.diff,0);
    $("lc-count").textContent = `показано ${list.length} · до переказу ${
      sum.toLocaleString("uk-UA",{maximumFractionDigits:2})} УО`;
    $("lc-table").innerHTML = finTable(
      ["№ угоди","Статус","Коносамент","Контейнер","Маршрут","Оплата від клієнта",
       "Профіт","Винагорода","Курс НБУ","Винагорода, грн","Інфо+комісії","Різниця",
       "Переказано","Сума переказу","Дата переказу"],
      list.map(r => `<tr class="${r.sent?"lc-sent":""}">
        <td class="mono">${esc(r.num)}</td>
        <td>${esc(r.status)}</td>
        <td class="mono">${esc(r.bl) || "<span class='sub'>—</span>"}</td>
        <td class="mono">${esc(r.cont) || "<span class='sub'>—</span>"}</td>
        <td>${esc(r.route) || "<span class='sub'>—</span>"}</td>
        <td class="mono">${r.paid ? dmy(r.paid) : "<span class='sub'>не оплачено</span>"}</td>
        <td style="text-align:right">${fmtN(r.profit,2)}</td>
        <td style="text-align:right">${r.fee ? fmtN(r.fee,2) : "<span class='sub'>немає статті</span>"}</td>
        <td style="text-align:right" class="mono">${r.rate
          ? `${fmtN(r.rate,4)}<span class="sub"> ${esc(r.fee_ccy||"")}</span>`
          : "<span class='sub'>—</span>"}</td>
        <td style="text-align:right">${r.fee_uah ? fmtN(r.fee_uah,2) : "<span class='sub'>—</span>"}</td>
        <td style="text-align:right">${r.info_added ? fmtN(r.info_added,2)
          : (r.info_bank ? `<span class="sub">${fmtN(r.info_bank,2)}</span>` : "")}</td>
        <td style="text-align:right"><b>${fmtN(r.diff,2)}</b></td>
        <td class="mono" style="white-space:nowrap">${r._row
          ? `<label style="display:flex;align-items:center;gap:6px;cursor:${canMark?"pointer":"default"}">
               <input type="checkbox" class="lc-mark" data-num="${esc(r.num)}" ${r.sent?"checked":""} ${canMark?"":"disabled"}>
               <span class="sub">${r.sent ? "переказано" : ""}</span></label>`
          : `<span class="sub" title="цієї угоди немає в таблиці диспетчеризації">—</span>`}</td>
        <td class="lc-keep" style="text-align:right">${r.sent && r.sentAmt != null
          ? fmtN(r.sentAmt,2) : "<span class='sub'>—</span>"}</td>
        <td class="lc-keep mono">${r.sent && r.sentDate
          ? dmy(r.sentDate) : "<span class='sub'>—</span>"}</td>
        </tr>`));
    if (canMark) $("lc-table").querySelectorAll("input.lc-mark").forEach(ch =>
      ch.addEventListener("change", () => mark(ch)));
  };

  // позначка «переказано» пишеться в таблицю диспетчеризації (та сама угода — той самий рядок)
  const canMark = !!cfg().edit || cfg().fin === "acct" || cfg().fin === "full";
  async function mark(ch){
    const r = rows.find(x => String(x.num) === ch.dataset.num);
    if (!r || !r._row) return;
    const on = ch.checked;
    const today = new Date().toISOString().slice(0,10);
    ch.disabled = true;
    try{
      await saveField(r._row, "Переказ за кордон", on);
      await saveField(r._row, "Дата переказу", on ? today : null);
      await saveField(r._row, "Сума переказу", on ? r.diff : null);
      r.sent = on; r.sentDate = on ? today : ""; r.sentAmt = on ? r.diff : null;
      toast(on ? `✅ Угода ${r.num}: позначено як переказану (${fmtN(r.diff,2)} УО)`
               : `↩ Угода ${r.num}: позначку знято`);
    }catch(e){
      ch.checked = !on;
      toast("⚠ Не збереглось: " + e.message);
    }
    ch.disabled = false;
    draw();
  }

  restoreNote("lc-note");
  ["lc-q","lc-st","lc-all","lc-base","lc-from","lc-to","lc-sent"].forEach(id =>
    $(id).addEventListener(id === "lc-q" ? "input" : "change", draw));
  $("lc-reset").addEventListener("click", () => {
    ["lc-q","lc-from","lc-to"].forEach(id => $(id).value = "");
    ["lc-st","lc-sent"].forEach(id => $(id).value = "");
    $("lc-base").value = "paid"; $("lc-all").checked = false; draw();
  });
  draw();

  // ⟳ перерахунок: б'є в /localcosts-refresh і чекає, поки оновиться файл
  $("lc-recalc").addEventListener("click", async () => {
    const b = $("lc-recalc");
    b.disabled = true; b.textContent = "⏳ Рахую з Експедитора (~1 хв)…";
    refreshNote("lc-note", "run", "Рахую з Експедитора…");
    try{
      await svc("/localcosts-refresh");
      refreshNote("lc-note", "ok");
      toast("✅ Перераховано"); await PAGES.accounting();
    }catch(e){
      b.disabled = false; b.textContent = "⟳ Перерахувати з Експедитора";
      refreshNote("lc-note", /вже виконується/.test(e.message)?"busy":"err", e.message);
      toast("⚠ Не вдалося перерахувати: " + e.message);
    }
  });

  $("lc-csv").addEventListener("click", () => {
    const head = ["Номер угоди","Статус","Коносамент лінійний","Контейнер","Маршрут",
      "Дата оплати від клієнта","Профіт УО","Винагорода експедитора УО",
      "Валюта винагороди","Винагорода у валюті","Курс НБУ на день оплати","Винагорода грн",
      "Інфо+комісії УО",
      "Різниця до переказу УО","Переказано","Дата переказу","Сума переказу УО"];
    const e2 = v => '"' + String(v==null?"":v).replace(/"/g,'""') + '"';
    const csv = [head.map(e2).join(";")].concat(visible().map(r => [r.num,r.status,r.bl,r.cont,
      r.route,r.paid,r.profit,r.fee,
      r.fee_ccy||"", r.fee_val??"", r.rate??"", r.fee_uah??"",
      r.info_added,r.diff,
      r.sent?"так":"ні", r.sentDate||"", r.sent?(r.sentAmt??r.diff):""].map(e2).join(";"))).join("\r\n");
    const blob = new Blob(["﻿"+csv], {type:"text/csv;charset=utf-8"});
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "lokalni-vytraty-za-kordonom.csv";
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(()=>URL.revokeObjectURL(a.href), 3000);
  });
};

/* ===== ЄДИНИЙ ПОДАТОК (постановка користувачки 02.08.2026) =====
   Рахунки клієнтам з формою оплати ТІЛЬКИ «Банк Юнітекс Ейч-Ді» (гривневий),
   у яких заповнена дата оплати. Винагорода — стаття «Винагорода експедитора»
   з рядків рахунка, гривнею з самого документа. 5% + 1% = 6%.
   Дані рахує finrep/single_tax.py → computed/single_tax.json. */
/* ===== ЗВІТ ПРО ПЕРЕКАЗ ТРАНЗИТНИХ КОШТІВ =====
   Логіка користувачки: усе, що надійшло від клієнта, крім винагороди експедитора,
   переказується транзитом далі — і саме З ТОГО РАХУНКУ, на який прийшло. Оплати з інших
   видів оплати (Маерск USD, каси, Cr String Cycle) сюди не входять і показані довідково.
   Комісії, податки й бонуси — операційні витрати, у транзит не входять.
   Дані рахує finrep/transit_report.py → computed/transit_report.json. */
async function renderTransit(){
  $("content").innerHTML = '<div class="card"><p class="sub">Рахую транзитні перекази…</p></div>';
  let js;
  try { js = await fetchFin("transit"); }
  catch(e){
    $("content").innerHTML = `<div class="card"><h3>💸 Транзитні перекази</h3>
      <div class="note">⚠ Не вдалося отримати дані: ${esc(e.message)}</div></div>`;
    return;
  }
  const D = js.data || {}, all = D.rows || [];
  const stamp = js.mtime ? new Date(js.mtime*1000).toLocaleString("uk-UA",
      {day:"2-digit",month:"2-digit",hour:"2-digit",minute:"2-digit"}) : "—";
  const dd = v => (Number(v)||0).toLocaleString("uk-UA",{minimumFractionDigits:2,maximumFractionDigits:2});
  const dmy = v => v ? esc(String(v).slice(0,10).split("-").reverse().join(".")) : "";

  $("page-actions").innerHTML = `
    <button class="btn ghost" id="tr-back">← Локальні витрати</button>
    <label class="sub" style="margin:0">оплата з <input type="date" id="tr-from"></label>
    <label class="sub" style="margin:0">по <input type="date" id="tr-to"></label>
    <button class="btn ghost" id="tr-csv">⬇ CSV по кожному переказу</button>`;
  $("tr-back").addEventListener("click", ()=>PAGES.accounting());

  $("content").innerHTML = `
  <div class="card">
    <h3>💸 Переказ транзитних коштів</h3>
    <p class="sub">що надійшло на рахунки Юнітекса і скільки з них уже переказано далі ·
      дані з Експедитора станом на ${stamp}</p>
    <div class="tiles" style="margin-top:12px" id="tr-tiles"></div>
    <div class="note" style="margin-top:12px">
      Транзит рахується <b>з того самого рахунку, на який прийшли гроші</b>
      (${esc((D.accounts||[]).join(", "))}). Оплати з інших видів оплати показані в
      розкритті окремо — вони в залишок не входять. Комісії, податки й бонуси
      (${esc((D.operating||[]).slice(0,4).join(", "))}…) — операційні витрати, не транзит.
      <b>Клік по рядку</b> — куди саме переказано по кожній статті.
    </div>
    <div class="filters" style="margin-top:12px">
      <input id="tr-q" placeholder="пошук: угода, коносамент, контейнер" style="min-width:240px">
      <select id="tr-f"><option value="">усі угоди</option>
        <option value="left">є залишок</option>
        <option value="zero">нічого не переказано</option>
        <option value="unpaid">є неоплачені транзитні рахунки</option>
        <option value="minus">переказано більше, ніж надійшло</option></select>
      <button class="btn ghost" id="tr-reset" style="padding:4px 10px;font-size:12.5px">скинути</button>
      <span id="tr-count" class="sub"></span>
    </div>
    <div id="tr-table"></div>
  </div>`;

  const visible = () => {
    const q = ($("tr-q").value||"").trim().toLowerCase();
    const f = $("tr-f").value, a = $("tr-from").value, b = $("tr-to").value;
    return all.filter(r => {
      if (a && (!r.paid || r.paid < a)) return false;
      if (b && (!r.paid || r.paid > b)) return false;
      if (f === "left" && r.balance <= 0) return false;
      if (f === "zero" && r.transit_total > 0) return false;
      if (f === "unpaid" && !r.unpaid_total) return false;
      if (f === "minus" && r.balance >= 0) return false;
      return !q || [r.num,r.bl,r.cont].join(" ").toLowerCase().includes(q);
    });
  };
  const details = r => {
    const li = x => `<tr><td>${esc(x.article)}</td><td class="num">${dd(x.amount)}</td>
      <td>${esc(x.payee||"")}</td><td class="sub">${esc(x.from_account||"")}</td>
      <td class="mono sub">${dmy(x.date)}</td></tr>`;
    const tbl = (title, items, cls) => !items || !items.length ? "" :
      `<div style="margin-top:8px"><b>${title}</b>
        <table class="subt" style="width:100%;margin-top:4px"><tr><th>Стаття</th><th class="num">Сума</th>
        <th>Кому</th><th>З якого рахунку</th><th>Дата</th></tr>${items.map(li).join("")}</table></div>`;
    const acc = (r.per_account||[]).map(x=>`<tr><td>${esc(x.account)}</td>
        <td class="num">${dd(x.in)}</td><td class="num">${dd(x.out)}</td>
        <td class="num"><b>${dd(x.left)}</b></td></tr>`).join("");
    return `<div style="padding:10px 12px;background:var(--tile-bg)">
      <b>Рух по рахунках</b>
      <table class="subt" style="width:100%;margin-top:4px"><tr><th>Рахунок</th>
        <th class="num">Надійшло</th><th class="num">Переказано</th><th class="num">Лишилось</th></tr>
        ${acc || '<tr><td colspan="4" class="sub">немає</td></tr>'}</table>
      ${tbl("Переказано транзитом", r.transit_items)}
      ${tbl("⚠ Не переказано — рахунок є, оплати немає", r.unpaid_items)}
      ${tbl("Довідково: оплачено з інших рахунків (не транзит)", r.other_acc_items)}
      ${(r.operating_by_article||[]).length ? `<div style="margin-top:8px" class="sub">
        Операційні (не транзит): ${r.operating_by_article.map(x=>esc(x.article)+" "+dd(x.amount)).join(" · ")}</div>` : ""}
    </div>`;
  };
  const draw = () => {
    const list = visible();
    const sum = k => list.reduce((s,r)=>s+(Number(r[k])||0),0);
    $("tr-count").textContent = `показано ${list.length} угод`;
    $("tr-tiles").innerHTML = `
      <div class="tile tready"><div class="tbody"><div class="lbl">Надійшло</div>
        <div class="val">${dd(sum("in_total"))}</div><div class="hint">УО від клієнтів</div></div></div>
      <div class="tile tready"><div class="tbody"><div class="lbl">Винагорода</div>
        <div class="val">${dd(sum("fee"))}</div><div class="hint">лишається компанії</div></div></div>
      <div class="tile tready"><div class="tbody"><div class="lbl">Переказано транзитом</div>
        <div class="val">${dd(sum("transit_total"))}</div><div class="hint">з тих самих рахунків</div></div></div>
      <div class="tile tready"><div class="tbody"><div class="lbl">Залишок</div>
        <div class="val">${dd(sum("balance"))}</div><div class="hint">ще не переказано</div></div></div>`;
    $("tr-table").innerHTML = finTable(
      ["№ угоди","Коносамент","Контейнер","Оплата клієнта","Надійшло","Винагорода",
       "Переказано","Не переказано","Залишок",""],
      list.map(r => `<tr class="trrow" data-num="${esc(r.num)}" style="cursor:pointer">
        <td class="mono"><b>${esc(r.num)}</b></td>
        <td class="mono">${esc(r.bl)||"<span class='sub'>—</span>"}</td>
        <td class="mono">${esc(r.cont)||"<span class='sub'>—</span>"}</td>
        <td class="mono">${dmy(r.paid)}</td>
        <td style="text-align:right">${dd(r.in_total)}</td>
        <td style="text-align:right">${dd(r.fee)}</td>
        <td style="text-align:right">${dd(r.transit_total)}</td>
        <td style="text-align:right">${r.unpaid_total ? `<span style="color:var(--crit-text)">${dd(r.unpaid_total)}</span>` : ""}</td>
        <td style="text-align:right"><b>${dd(r.balance)}</b></td>
        <td class="sub">▸</td></tr>
        <tr id="trd-${esc(r.num)}" style="display:none"><td colspan="10" style="padding:0">${details(r)}</td></tr>`));
    $("tr-table").querySelectorAll("tr.trrow").forEach(tr => tr.addEventListener("click", () => {
      const d = $("trd-" + tr.dataset.num);
      if (d) d.style.display = d.style.display === "none" ? "" : "none";
    }));
  };
  ["tr-q","tr-f","tr-from","tr-to"].forEach(id =>
    $(id).addEventListener(id === "tr-q" ? "input" : "change", draw));
  $("tr-reset").addEventListener("click", ()=>{
    ["tr-q","tr-from","tr-to"].forEach(id=>$(id).value=""); $("tr-f").value=""; draw();
  });
  draw();

  // CSV: один рядок = один переказ, щоб було видно КУДИ пішла кожна стаття
  $("tr-csv").addEventListener("click", ()=>{
    const head = ["Номер угоди","Коносамент","Контейнер","Оплата клієнта","Надійшло по угоді",
      "Винагорода","Тип","Стаття","Сума","Кому","З якого рахунку","Дата","Залишок по угоді"];
    const e2 = v => '"' + String(v==null?"":v).replace(/"/g,'""') + '"';
    const out = [head.map(e2).join(";")];
    visible().forEach(r => {
      const base = [r.num,r.bl,r.cont,r.paid,r.in_total,r.fee];
      const push = (type,x) => out.push(base.concat([type,x.article,x.amount,x.payee,
        x.from_account,x.date,r.balance]).map(e2).join(";"));
      (r.transit_items||[]).forEach(x=>push("переказано",x));
      (r.unpaid_items||[]).forEach(x=>push("НЕ переказано",x));
      (r.other_acc_items||[]).forEach(x=>push("з іншого рахунку",x));
      if (!(r.transit_items||[]).length && !(r.unpaid_items||[]).length)
        out.push(base.concat(["нічого не переказано","","","","","",r.balance]).map(e2).join(";"));
    });
    const blob = new Blob(["﻿"+out.join("\r\n")], {type:"text/csv;charset=utf-8"});
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob); a.download = "tranzytni-perekazy.csv";
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(()=>URL.revokeObjectURL(a.href), 3000);
  });
}

async function renderSingleTax(){
  $("content").innerHTML = '<div class="card"><p class="sub">Рахую єдиний податок…</p></div>';
  let js;
  try { js = await fetchFin("single_tax"); }
  catch(e){
    $("content").innerHTML = `<div class="card"><h3>🧾 Єдиний податок</h3>
      <div class="note">⚠ Не вдалося отримати дані: ${esc(e.message)}</div></div>`;
    return;
  }
  const D = js.data || {};
  const all = (D.rows || []).slice().sort((a,b)=> a.paid.localeCompare(b.paid) || (+a.deal)-(+b.deal));
  const stamp = js.mtime ? new Date(js.mtime*1000).toLocaleString("uk-UA",
      {day:"2-digit",month:"2-digit",hour:"2-digit",minute:"2-digit"}) : "—";
  const dmin = all.length ? all[0].paid : "", dmax = all.length ? all[all.length-1].paid : "";

  $("page-actions").innerHTML = `
    <button class="btn ghost" id="tax-back">← Локальні витрати</button>
    <label class="sub" style="margin:0">з <input type="date" id="tax-from" value="${esc(dmin)}"></label>
    <label class="sub" style="margin:0">по <input type="date" id="tax-to" value="${esc(dmax)}"></label>
    <button class="btn ghost" id="tax-csv">⬇ CSV</button>`;
  $("tax-back").addEventListener("click", ()=>PAGES.accounting());

  const dd = v => (v||0).toLocaleString("uk-UA",{minimumFractionDigits:2, maximumFractionDigits:2});
  let shown = all;
  const draw = () => {
    const a = $("tax-from").value || dmin, b = $("tax-to").value || dmax;
    shown = all.filter(r => r.paid >= a && r.paid <= b);
    const sum = k => shown.reduce((s,r)=>s+(+r[k]||0), 0);
    const body = shown.map(r=>`<tr>
        <td class="mono"><b>${esc(r.deal)}</b></td>
        <td class="mono">${esc(r.paid)}</td>
        <td class="num">${dd(r.fee)}</td>
        <td class="num">${dd(r.t5)}</td>
        <td class="num">${dd(r.t1)}</td>
        <td class="num"><b>${dd(r.t6)}</b></td></tr>`).join("");
    $("tax-out").innerHTML = `
      <div class="tiles" style="margin-bottom:14px">
        <div class="tile tready"><div class="tbody"><div class="lbl">Сума винагороди</div>
          <div class="val">${dd(sum("fee"))}</div><div class="hint">грн · рахунків: ${shown.length}</div></div></div>
        <div class="tile tready"><div class="tbody"><div class="lbl">Сума 5%</div>
          <div class="val">${dd(sum("t5"))}</div><div class="hint">єдиний податок</div></div></div>
        <div class="tile tready"><div class="tbody"><div class="lbl">Сума 1%</div>
          <div class="val">${dd(sum("t1"))}</div><div class="hint">військовий збір</div></div></div>
        <div class="tile tready"><div class="tbody"><div class="lbl">Сума 6%</div>
          <div class="val">${dd(sum("t6"))}</div><div class="hint">разом до сплати</div></div></div>
      </div>
      <div class="tablewrap"><table>
        <thead><tr><th>Номер угоди</th><th>Дата оплати</th><th class="num">Винагорода</th>
          <th class="num">5%</th><th class="num">1%</th><th class="num">Разом (6%)</th></tr></thead>
        <tbody>${body || '<tr><td colspan="6" class="cell-muted">За цей період оплат немає.</td></tr>'}</tbody>
        <tfoot><tr style="font-weight:700">
          <td colspan="2">РАЗОМ за період</td>
          <td class="num">${dd(sum("fee"))}</td><td class="num">${dd(sum("t5"))}</td>
          <td class="num">${dd(sum("t1"))}</td><td class="num">${dd(sum("t6"))}</td></tr></tfoot>
      </table></div>`;
  };

  $("content").innerHTML = `
    <div class="card">
      <h3>🧾 Єдиний податок</h3>
      <p class="sub">рахунки клієнтам з формою оплати <b>${esc(D.payKind || "Банк Юнітекс Ейч-Ді")}</b> (грн),
        у яких є дата оплати · суми в гривні з документа · дані з Експедитора станом на ${esc(stamp)}</p>
      <div id="tax-out"></div>
      <div class="note" style="margin-top:12px">
        <b>Як відбирається:</b> проведені, не інформативні рахунки клієнтам саме з цією формою оплати
        (євровий і USD-рахунки Ейч-Ді — окремі форми і сюди не входять).
        Винагорода — рядки рахунка зі статтею «Винагорода експедитора».
        5% і 1% рахуються від винагороди кожного рахунка, «Разом» = 6%.
        Перевірено рахунків: ${esc(D.invoicesChecked ?? "—")}, відібрано: ${esc(D.invoicesSelected ?? "—")},
        з них без рядка винагороди: ${esc(D.invoicesWithoutFee ?? "—")} (у таблицю не входять).
      </div>
    </div>`;
  draw();
  $("tax-from").addEventListener("change", draw);
  $("tax-to").addEventListener("change", draw);
  $("tax-csv").addEventListener("click", ()=>{
    const e2 = v => '"' + String(v==null?"":v).replace(/"/g,'""') + '"';
    const head = ["Номер угоди","Дата оплати","Винагорода","5%","1%","Разом 6%"];
    const csv = [head.map(e2).join(";")].concat(
      shown.map(r=>[r.deal,r.paid,r.fee,r.t5,r.t1,r.t6].map(e2).join(";"))).join("\r\n");
    const blob = new Blob(["\ufeff"+csv], {type:"text/csv;charset=utf-8"});
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "yedynyi-podatok.csv";
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(()=>URL.revokeObjectURL(a.href), 3000);
  });
  window.scrollTo(0,0);
}

PAGES.finance = async () => {
  const mode = cfg().fin;
  if (mode === "personal"){
    $("content").innerHTML = `<div class="card"><h3>💰 Мій фінзвіт (сейлз-менеджер)</h3>
      <p class="sub">дебіторка/кредиторка по твоїх угодах, прибуток за період</p>
      <div class="note">🛠 Персональний фінзвіт — у розробці: дані вже збираються, готуємо зріз по менеджеру.</div></div>`;
    return;
  }
  if (mode === "blur" || mode === "none"){
    $("content").innerHTML = `<div class="card"><h3>💰 Фінанси</h3>
      <div class="note">🔒 Фінансові показники доступні лише фінансовим ролям (Адміністратор, Фінансист, Бухгалтер).</div></div>`;
    return;
  }
  // кнопки звітів — у верхній панелі (як у диспетчеризації й калькуляції),
  // щоб дашборд починався одразу під шапкою
  $("page-actions").innerHTML = `
    <button class="btn" id="rep-oper">⚡ Оперативний фінансовий звіт</button>
    <button class="btn" id="rep-period">📆 Фінансовий звіт за період</button>
    <button class="btn" id="rep-maersk">🚢 Оплати Маерску</button>
    <span id="fin-refresh-slot" style="display:flex;align-items:center;gap:10px;flex-wrap:wrap"></span>`;
  $("content").innerHTML = '<div id="rep-body"></div>';
  $("rep-oper").addEventListener("click", ()=>renderOper());
  $("rep-period").addEventListener("click", ()=>renderPeriod());
  $("rep-maersk").addEventListener("click", ()=>renderMaersk());
  renderOper();
};

function bindPalette(){
  const box = $("pal-page");
  if (!box) return;
  box.innerHTML = PALETTES.map(([p,n])=>
    `<button class="pal-dot ${p===palette?"sel":""}" data-pal="${p}" title="${esc(n)}"></button>`).join("");
  const nm = () => { $("pal-page-name").textContent =
    "Обрано: " + (PALETTES.find(x=>x[0]===palette)||["",""])[1]; };
  box.querySelectorAll(".pal-dot").forEach(b=>b.addEventListener("click", ()=>{
    setPalette(b.dataset.pal);
    box.querySelectorAll(".pal-dot").forEach(x=>x.classList.toggle("sel", x.dataset.pal===palette));
    nm();
  }));
  nm();
}

/* зміна ВЛАСНОГО пароля — через штатний ендпоінт бази, чужі паролі тут не міняються */
/* ===== надійність паролів =====
   Вимога користувачки 01.08.2026: «всі користувачі мають створювати собі
   надійні складні паролі». Правила застосовуються В УСІХ формах — і коли
   людина міняє свій пароль, і коли адмін створює акаунт чи скидає пароль.
   Сам пароль ніде не зберігається і нікуди не пишеться: ні в журнал, ні в
   базу платформи — лише в акаунт входу. */
const PW_MIN = 12;
const PW_RULES = [
  { t: "щонайменше " + PW_MIN + " символів", ok: p => p.length >= PW_MIN },
  { t: "велика латинська літера (A–Z)",      ok: p => /[A-Z]/.test(p) },
  { t: "мала латинська літера (a–z)",        ok: p => /[a-z]/.test(p) },
  { t: "цифра",                               ok: p => /[0-9]/.test(p) },
  { t: "спецсимвол (!@#$%…)",                 ok: p => /[^A-Za-z0-9]/.test(p) },
  { t: "без пробілів",                        ok: p => p.length > 0 && !/\s/.test(p) },
];
const pwFails = p => PW_RULES.filter(r => !r.ok(String(p || "")));
/* Генератор: криптостійкий, по одному символу з кожного набору + добір до 16.
   Символи, які легко сплутати (O/0, l/1/I), навмисно виключені. */
const PW_SETS = ["ABCDEFGHJKLMNPQRSTUVWXYZ", "abcdefghijkmnopqrstuvwxyz",
                 "23456789", "!@#$%^&*?+-="];
function pwGen(len){
  len = len || 16;
  const all = PW_SETS.join("");
  const pick = set => set[crypto.getRandomValues(new Uint32Array(1))[0] % set.length];
  const out = PW_SETS.map(pick);
  while (out.length < len) out.push(pick(all));
  for (let i = out.length - 1; i > 0; i--){          // перемішуємо
    const j = crypto.getRandomValues(new Uint32Array(1))[0] % (i + 1);
    [out[i], out[j]] = [out[j], out[i]];
  }
  return out.join("");
}
/* Живий список правил під полем: видно, чого ще бракує */
function pwHint(inputId, boxId){
  const inp = $(inputId), box = $(boxId);
  if (!inp || !box) return;
  const paint = () => {
    const v = inp.value;
    box.innerHTML = PW_RULES.map(r => {
      const ok = r.ok(v);
      return `<span class="pwr ${ok ? "ok" : ""}">${ok ? "✓" : "•"} ${esc(r.t)}</span>`;
    }).join("");
  };
  inp.addEventListener("input", paint);
  paint();
}

function bindPasswordChange(){
  pwHint("pw-new", "pw-hint");
  const gen = $("pw-gen");
  if (gen) gen.addEventListener("click", ()=>{
    const v = pwGen();
    $("pw-new").value = v; $("pw-new2").value = v;
    $("pw-new").dispatchEvent(new Event("input"));
    $("pw-msg").textContent = "🎲 Згенеровано. Скопіюй і збережи — після зміни пароля побачити його вже не вийде.";
  });
  const btn = $("pw-save");
  if (!btn) return;
  btn.addEventListener("click", async ()=>{
    const o = $("pw-old").value, n1 = $("pw-new").value, n2 = $("pw-new2").value;
    const msg = t => { $("pw-msg").textContent = t; };
    if (!o || !n1){ return msg("⚠ Заповни поточний і новий пароль."); }
    const bad = pwFails(n1);
    if (bad.length){ return msg("⚠ Пароль недостатньо надійний. Бракує: " + bad.map(r=>r.t).join(", ")); }
    if (n1 !== n2){ return msg("⚠ Новий пароль і підтвердження не збігаються."); }
    btn.disabled = true; msg("⏳ Змінюю…");
    try{
      const r = await fetch("/api/v1/auth/password/change", {method:"POST",
        headers:{"Content-Type":"application/json", "xc-auth": JWT||""},
        body: JSON.stringify({currentPassword:o, newPassword:n1, verifyPassword:n2})});
      const js = await r.json().catch(()=>({}));
      if (!r.ok) throw new Error(js.msg || js.message || ("HTTP " + r.status));
      msg("✅ Пароль змінено.");
      ["pw-old","pw-new","pw-new2"].forEach(id=>$(id).value = "");
      logAction("зміна пароля", "", "", "", "");
      toast("✅ Пароль змінено");
    }catch(e){ msg("⚠ Не вдалося: " + e.message); }
    btn.disabled = false;
  });
}

/* ===== адмін: створення користувача і задання пароля іншому =====
   Робиться ВИКЛЮЧНО з браузера адміністратора, його власною сесією (xc-auth).
   Службовим токеном платформи ці виклики заборонені самим NocoDB
   (ERR_API_TOKEN_NOT_ALLOWED), тому й не могли працювати раніше.
   Пароль ніде не зберігається: він іде прямо в акаунт входу, у журнал
   потрапляє лише факт дії — без значення (правило 3). */
async function ncAuth(path, body, method){
  const r = await fetch(path, {
    method: method || "POST",
    headers: {"Content-Type":"application/json", "xc-auth": JWT || ""},
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const js = await r.json().catch(()=>({}));
  if (!r.ok) throw new Error(js.msg || js.message || js.error || ("HTTP " + r.status));
  return js;
}
/* Знаходимо id акаунта за email серед користувачів NocoDB */
async function ncUserId(email){
  const js = await ncAuth("/api/v1/users", undefined, "GET");
  const list = js.list || js.users || (Array.isArray(js) ? js : []);
  const u = list.find(x => String(x.email || "").toLowerCase() === String(email).toLowerCase());
  if (!u) throw new Error("акаунта з такою поштою серед користувачів немає");
  return u.id;
}
/* Задати пароль іншому: генеруємо одноразовий токен скидання і одразу ним
   встановлюємо новий пароль. Так само працює кнопка «Забули пароль». */
async function ncSetPassword(email, password){
  const id = await ncUserId(email);
  const gen = await ncAuth("/api/v1/users/" + encodeURIComponent(id) + "/generate-reset-url", {});
  const url = String(gen.reset_password_url || gen.resetPasswordUrl || "");
  const tok = gen.reset_password_token || gen.resetPasswordToken ||
              (url.split("/").pop() || "").split("?")[0];
  if (!tok) throw new Error("сервер не повернув токен скидання");
  await ncAuth("/api/v1/auth/password/reset/" + encodeURIComponent(tok),
               {password: password, passwordRepeat: password, newPassword: password});
}

/* Кнопки «🔑 Задати» біля кожного користувача і форма створення нового */
function bindUserAdmin(rows){
  pwHint("nu-pw", "nu-hint");
  const gen = $("nu-gen");
  if (gen) gen.addEventListener("click", ()=>{
    $("nu-pw").value = pwGen();
    $("nu-pw").dispatchEvent(new Event("input"));
    $("nu-msg").textContent = "🎲 Згенеровано. Скопіюй зараз — потім пароль ніде не побачити.";
  });

  document.querySelectorAll("[data-pwuser]").forEach(b=>b.addEventListener("click", async ()=>{
    const email = b.dataset.pwuser;
    if (!email) return;
    const pw = prompt("Новий пароль для " + email +
      "\n\nВимоги: від " + PW_MIN + " символів, велика й мала латинські літери, цифра, спецсимвол, без пробілів." +
      "\nЗалиш поле порожнім — згенерую надійний сам.", "");
    if (pw === null) return;                       // натиснули «Скасувати»
    const val = pw.trim() ? pw.trim() : pwGen();
    const bad = pwFails(val);
    if (bad.length) return toast("⚠ Пароль слабкий. Бракує: " + bad.map(r=>r.t).join(", "));
    b.disabled = true; const old = b.textContent; b.textContent = "⏳";
    try{
      await ncSetPassword(email, val);
      logAction("зміна пароля користувачу", email, "", "", "");   // без самого пароля
      window.prompt("Пароль для " + email + " встановлено.\nСкопіюй і передай людині — більше він ніде не зберігається:", val);
      toast("✅ Пароль встановлено");
    }catch(e){ toast("⚠ Не вдалося: " + e.message); }
    b.disabled = false; b.textContent = old;
  }));

  const save = $("nu-save");
  if (save) save.addEventListener("click", async ()=>{
    const msg = t => { $("nu-msg").textContent = t; };
    const email = $("nu-email").value.trim().toLowerCase();
    const first = $("nu-first").value.trim(), last = $("nu-last").value.trim();
    const role = $("nu-role").value, pw = $("nu-pw").value;
    if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email)) return msg("⚠ Схоже, це не email.");
    if (!first) return msg("⚠ Вкажи ім'я.");
    if (rows.some(u=>String(u["Email"]||"").toLowerCase() === email))
      return msg("⚠ Користувач із такою поштою вже є в довіднику.");
    const bad = pwFails(pw);
    if (bad.length) return msg("⚠ Пароль недостатньо надійний. Бракує: " + bad.map(r=>r.t).join(", "));
    save.disabled = true; msg("⏳ Створюю акаунт…");
    try{
      await ncAuth("/api/v1/auth/user/signup", {email: email, password: pw});
      /* КРОК, ЯКОГО ТУТ НЕ БУЛО (знайдено 11.08.2026 на живому користувачі).
         Створення акаунта НЕ дає доступу до самої бази. Людина заходила, але
         перший же запит за списком таблиць отримував
             403 Forbidden — You do not have permission to view list of tables
             with the roles: .          (роль у базі порожня)
         Далі платформа лишалась без переліку таблиць, роль падала до «Перегляд»,
         і кожна сторінка казала «Table 'undefined' not found». Виглядало як
         «платформа зламалась», хоча користувача просто не пустили в базу.
         Перевірено: у бухгалтера роль у базі була None, у решти — editor/owner.

         Чому саме `editor`, а не `viewer`: платформа ПИШЕ навіть при звичайному
         вході (запис у «Журнал дій» рядком нижче), тож viewer падав би одразу.
         ⚠️ editor у NocoDB = читання і запис УСІХ таблиць. Наші ролі обмежують
         тільки те, що показує сторінка. Саме цю дірку закриває прошарок
         (server/gateway.py) — доки він не ввімкнений, обмеження косметичне. */
      msg("⏳ Акаунт створено, даю доступ до бази…");
      await api(`/api/v2/meta/bases/${BASE_ID}/users`, {method:"POST",
        body: JSON.stringify({email: email, roles: "editor"})});
      msg("⏳ Доступ надано, додаю в довідник…");
      await api(`/api/v2/tables/${T["Користувачі"]}/records`, {method:"POST",
        body: JSON.stringify([{Email: email, "Ім'я": first, "Прізвище": last,
                               "Роль": role, "Активний": true}])});
      logAction("створено користувача", email, "Роль", "", role);
      window.prompt("Користувача створено.\nСкопіюй пароль і передай людині — більше він ніде не зберігається:", pw);
      msg("✅ Готово. Попроси людину змінити пароль на свій у розділі «Налаштування».");
      ["nu-email","nu-first","nu-last","nu-pw"].forEach(id=>$(id).value = "");
      go("users");
    }catch(e){ msg("⚠ Не вдалося: " + e.message); }
    save.disabled = false;
  });
}

/* адмін править користувачів: імʼя, прізвище, роль, доступ */
function bindUserEdit(rows){
  const ROLE_LIST = Object.keys(RC);
  $("us-rows").querySelectorAll("td.ed[data-uf]").forEach(td=>td.addEventListener("click", async ()=>{
    if (td.querySelector(".edinput")) return;
    const f = td.dataset.uf;
    const u = rows.find(x=>String(x.Id) === td.closest("tr").dataset.uid);
    if (!u) return;
    const save = async (val, html) => {
      const keep = td.innerHTML;
      td.innerHTML = '<span class="cell-muted">…</span>';
      try{
        await api(`/api/v2/tables/${T["Користувачі"]}/records`, {method:"PATCH",
          body: JSON.stringify([{Id: u.Id, [f]: val}])});
        logAction("зміна користувача", u["Email"] || u.Id, f, u[f], val);
        u[f] = val; td.innerHTML = html;
        toast(`✅ ${u["Email"]||""}: ${f} — ${val === false ? "заблоковано" : (val || "очищено")}`);
      }catch(e){ td.innerHTML = keep; toast("⚠ Не збереглось: " + e.message); }
    };
    if (f === "Активний"){
      const nv = u["Активний"] === false;
      return save(nv, nv ? '<span class="pill t-good">активний</span>'
                         : '<span class="pill t-crit">заблоковано</span>');
    }
    const cur = String(u[f] || "");
    const keep = td.innerHTML;
    td.innerHTML = f === "Роль"
      ? `<select class="edinput">${ROLE_LIST.map(o=>`<option${o===cur?" selected":""}>${esc(o)}</option>`).join("")}</select>`
      : `<input class="edinput" type="text" value="${esc(cur)}">`;
    const inp = td.querySelector(".edinput");
    roomForEditor(td);
    inp.focus();
    let closed = false;
    const finish = (ok) => {
      if (closed) return; closed = true;
      const v = String(inp.value || "").trim();
      if (!ok || v === cur){ td.innerHTML = keep; return; }
      save(v, f === "Роль" ? `<span class="role-badge">${esc(v)}</span>`
                           : (f === "Ім'я" ? `<b>${esc(v)}</b>` : esc(v)));
    };
    inp.addEventListener("blur", ()=>finish(true));
    inp.addEventListener("keydown", e=>{
      if (e.key === "Enter"){ e.preventDefault(); finish(true); }
      if (e.key === "Escape"){ e.preventDefault(); finish(false); }
    });
    if (f === "Роль") inp.addEventListener("change", ()=>finish(true));
  }));
}

/* журнал подій: останні 500 записів, фільтри по користувачу, дії й тексту */
async function renderAudit(){
  const tid = T["Журнал дій"];
  if (!tid){ $("lg-note").textContent = "Журнал ще не створено."; return; }
  let list = [];
  try{
    const js = await api(`/api/v2/tables/${tid}/records?limit=500&sort=-Час`);
    list = js.list || [];
  }catch(e){ $("lg-note").textContent = "Не вдалося прочитати журнал: " + e.message; return; }
  const users = [...new Set(list.map(r=>String(r["Користувач"]||"").trim()).filter(Boolean))].sort();
  const acts  = [...new Set(list.map(r=>String(r["Дія"]||"").trim()).filter(Boolean))].sort();
  $("lg-user").innerHTML = '<option value="">Усі користувачі</option>' + users.map(u=>`<option>${esc(u)}</option>`).join("");
  $("lg-act").innerHTML  = '<option value="">Усі дії</option>' + acts.map(a=>`<option>${esc(a)}</option>`).join("");
  const when = v => { const d = new Date(v); return isNaN(d) ? String(v||"") :
    d.toLocaleString("uk-UA",{day:"2-digit",month:"2-digit",year:"2-digit",hour:"2-digit",minute:"2-digit"}); };
  const draw = () => {
    const u = $("lg-user").value, a = $("lg-act").value, q = $("lg-q").value.toLowerCase();
    const rows = list.filter(r =>
      (!u || String(r["Користувач"]||"") === u) &&
      (!a || String(r["Дія"]||"") === a) &&
      (!q || [r["Обʼєкт"],r["Поле"],r["Було"],r["Стало"]].join(" ").toLowerCase().includes(q)));
    $("lg-rows").innerHTML = rows.length ? rows.map(r=>`<tr>
      <td class="mono">${esc(when(r["Час"]))}</td>
      <td>${esc(r["Користувач"]||"—")}</td>
      <td class="cell-muted">${esc(r["Роль"]||"")}</td>
      <td>${esc(r["Дія"]||"")}</td>
      <td class="mono">${esc(r["Обʼєкт"]||"")}</td>
      <td>${esc(r["Поле"]||"")}</td>
      <td class="cell-muted">${esc(r["Було"]||"")}</td>
      <td><b>${esc(r["Стало"]||"")}</b></td></tr>`).join("")
      : '<tr><td colspan="8" class="cell-muted">Записів немає.</td></tr>';
    $("lg-note").textContent = `показано ${rows.length} з ${list.length} записів`;
  };
  ["lg-user","lg-act","lg-q"].forEach(id=>$(id).addEventListener(id==="lg-q"?"input":"change", draw));
  draw();
}

/* Кабінети клієнтів: відкрити чужий кабінет очима клієнта і видати доступ.
   Обидві дії робить СЕРВЕР кабінету після перевірки ролі — сторінка лише
   просить. Пароль ніде не показується: клієнт створює його сам за одноразовим
   посиланням, тому в платформі нема чого зберігати. */
async function renderCabinets(){
  const note = $("cc-note");
  if (!note) return;
  const head = {"xc-auth": sessionStorage.jwt || ""};
  let clients = [], accounts = [];
  try{
    const [c, a] = await Promise.all([
      fetch("/cabinet-clients", {headers: head}),
      fetch("/cabinet-accounts", {headers: head})]);
    if (c.status === 403 || a.status === 403){
      note.textContent = "Цей розділ доступний адміністратору й сейлз-менеджеру."; return; }
    if (!c.ok || !a.ok) throw new Error("HTTP " + c.status + "/" + a.status);
    clients = (await c.json()).list || [];
    accounts = (await a.json()).list || [];
  }catch(e){ note.textContent = "Не вдалося прочитати: " + e.message; return; }

  /* Порожньо — це не помилка: у сейлза може ще не бути своїх компаній.
     Кажемо про це словами, а не лишаємо голу таблицю. */
  $("cc-rows").innerHTML = clients.map(r=>`<tr>
    <td><b>${esc(r.client)}</b></td>
    <td class="mono">${r.deals}</td>
    <td class="cell-muted">${r.active ? r.active + " з " + r.accounts : "немає"}</td>
    <td style="text-align:right"><button class="btn cc-open" data-c="${esc(r.client)}">Відкрити кабінет</button></td>
  </tr>`).join("") || '<tr><td colspan="4" class="cell-muted">Компаній, доступних вам, немає.</td></tr>';

  const when = v => { const d = new Date(v); return isNaN(d) ? "—" :
    d.toLocaleString("uk-UA",{day:"2-digit",month:"2-digit",year:"2-digit",hour:"2-digit",minute:"2-digit"}); };
  $("ca-rows").innerHTML = accounts.map(r=>`<tr>
    <td class="mono">${esc(r.email)}</td>
    <td>${esc(r.client)}</td>
    <td>${r.active ? (r.new ? "новий" : "робочий") : "<b>заблокований</b>"}</td>
    <td class="cell-muted mono">${r.last ? when(r.last) : "—"}</td>
    <td style="text-align:right">${r.active
      ? `<button class="btn ca-inv" data-e="${esc(r.email)}">Посилання на пароль</button>` : ""}</td>
  </tr>`).join("") || '<tr><td colspan="5" class="cell-muted">Доступів ще немає.</td></tr>';
  note.textContent = `компаній ${clients.length}, доступів ${accounts.length}`;

  /* Вкладку відкриваємо ЗАЗДАЛЕГІДЬ, ще до запиту: якщо чекати відповіді, браузер
     вважає відкриття не наслідком кліку і блокує його як спливне вікно. */
  document.querySelectorAll(".cc-open").forEach(b=>b.addEventListener("click", async ()=>{
    const tab = window.open("", "_blank");
    try{
      const r = await fetch("/cabinet-view", {method:"POST", headers:
        Object.assign({"Content-Type":"application/x-www-form-urlencoded"}, head),
        body: "client=" + encodeURIComponent(b.dataset.c)});
      if (!r.ok) throw new Error("HTTP " + r.status);
      tab.location = (await r.json()).url;
    }catch(e){ if (tab) tab.close(); toast("⚠ Не вдалося відкрити: " + e.message); }
  }));

  document.querySelectorAll(".ca-inv").forEach(b=>b.addEventListener("click", async ()=>{
    try{
      const r = await fetch("/cabinet-invite", {method:"POST", headers:
        Object.assign({"Content-Type":"application/x-www-form-urlencoded"}, head),
        body: "email=" + encodeURIComponent(b.dataset.e)});
      if (!r.ok) throw new Error("HTTP " + r.status);
      const js = await r.json();
      /* Показуємо в полі, а не в toast: посилання довге, його треба скопіювати. */
      const box = document.createElement("div");
      box.className = "note";
      box.style.marginTop = "8px";
      box.innerHTML = `<b>${esc(b.dataset.e)}</b> — посилання діє до ${esc(js.expires)}, спрацює один раз:
        <input class="inp" readonly style="width:100%;margin-top:6px;font-size:12px" value="${esc(js.url)}">`;
      b.closest("tr").after(Object.assign(document.createElement("tr"),
        {innerHTML: `<td colspan="5"></td>`}));
      b.closest("tr").nextElementSibling.firstElementChild.appendChild(box);
      box.querySelector("input").select();
    }catch(e){ toast("⚠ Не вдалося: " + e.message); }
  }));
}

/* Журнал кабінету КЛІЄНТІВ. Джерело — не NocoDB, а сам сервер кабінету
   (/cabinet-log): акаунти і журнал живуть в окремій базі, щоб хеші паролів
   клієнтів не лежали в таблицях, які бачать співробітники.
   Віддається лише ролі «Адміністратор» — перевірку робить сервер, не сторінка.
   Це НЕ журнал дій співробітників (той вище, renderAudit) і НЕ журнал
   автоматики — тут видно тільки клієнтів. */
async function renderCabinetLog(){
  const note = $("cl-note");
  if (!note) return;
  let list = [];
  try{
    const r = await fetch("/cabinet-log?limit=1000", {headers: {"xc-auth": sessionStorage.jwt || ""}});
    if (r.status === 403){ note.textContent = "Журнал доступний лише адміністратору."; return; }
    if (!r.ok) throw new Error("HTTP " + r.status);
    list = (await r.json()).list || [];
  }catch(e){
    note.textContent = "Не вдалося прочитати журнал кабінету: " + e.message;
    return;
  }
  const clients = [...new Set(list.map(r=>String(r.client||"").trim()).filter(Boolean))].sort();
  const acts    = [...new Set(list.map(r=>String(r.action||"").trim()).filter(Boolean))].sort();
  $("cl-client").innerHTML = '<option value="">Усі компанії</option>' + clients.map(c=>`<option>${esc(c)}</option>`).join("");
  $("cl-act").innerHTML    = '<option value="">Усі дії</option>' + acts.map(a=>`<option>${esc(a)}</option>`).join("");
  const when = v => { const d = new Date(v); return isNaN(d) ? String(v||"") :
    d.toLocaleString("uk-UA",{day:"2-digit",month:"2-digit",year:"2-digit",hour:"2-digit",minute:"2-digit"}); };
  /* Небезпечні дії підсвічуємо: саме їх шукають, коли щось пішло не так. */
  const bad = a => /відмова|невдал|заблок/i.test(a || "");
  const draw = () => {
    const c = $("cl-client").value, a = $("cl-act").value, q = $("cl-q").value.toLowerCase();
    const rows = list.filter(r =>
      (!c || String(r.client||"") === c) &&
      (!a || String(r.action||"") === a) &&
      (!q || [r.email, r.detail, r.ip].join(" ").toLowerCase().includes(q)));
    $("cl-rows").innerHTML = rows.length ? rows.map(r=>`<tr>
      <td class="mono">${esc(when(r.ts))}</td>
      <td>${esc(r.client||"—")}</td>
      <td class="mono">${esc(r.email||"—")}</td>
      <td${bad(r.action)?' style="color:var(--neg,#b42318);font-weight:600"':""}>${esc(r.action||"")}</td>
      <td class="cell-muted">${esc(r.detail||"")}</td>
      <td class="mono cell-muted">${esc(r.ip||"")}</td></tr>`).join("")
      : '<tr><td colspan="6" class="cell-muted">Записів немає.</td></tr>';
    $("cl-note").textContent = `показано ${rows.length} з ${list.length} записів`;
  };
  ["cl-client","cl-act","cl-q"].forEach(id=>$(id).addEventListener(id==="cl-q"?"input":"change", draw));
  draw();
}

/* Журнал роботи автоматики (конвеєр даних). Джерело — logs/actions.jsonl на
   сервері, зведене в computed/pipeline.json. Читаємо через /finrep-data: там уже
   є перевірка ролі, окремого доступу не заводимо.
   Це НЕ журнал дій людей (той вище, renderAudit) — тут видно роботу машини:
   що конвеєр тягнув, скільки записів прийшло і де впав. */
async function renderPipelineJournal(){
  const note = () => $("pj-note");
  let d = {};
  try{
    const js = await fetchFin("pipeline");
    d = js.data || {};
  }catch(e){
    if (note()) note().textContent = "Не вдалося прочитати журнал: " + e.message;
    return;
  }
  const list = Array.isArray(d["події"]) ? d["події"] : [];
  const MARK = {ok:"✓", fail:"✗", warn:"!", start:"·"};
  const COLOR = {ok:"var(--ok-text,#137333)", fail:"var(--crit-text,#b3261e)", warn:"#8a6d1f"};
  const when = v => {
    const d2 = new Date(String(v||"").replace(" ", "T"));
    return isNaN(d2) ? String(v||"")
      : d2.toLocaleString("uk-UA",{day:"2-digit",month:"2-digit",hour:"2-digit",minute:"2-digit"});
  };
  /* Деталі в кожної події свої (у збирача рухів це числа, у кроку конвеєра —
     останній рядок виводу), тому не малюємо фіксовані колонки, а зводимо все,
     що є, у «ключ: значення». */
  const details = r => Object.keys(r)
    .filter(k => !["ts","step","status"].includes(k))
    .map(k => `${k}: ${r[k]}`).join(" · ");
  const draw = () => {
    const onlyBad = $("pj-status").value === "bad";
    const q = $("pj-q").value.toLowerCase();
    const rows = list.filter(r =>
      (!onlyBad || r.status === "fail" || r.status === "warn") &&
      (!q || (String(r.step||"") + " " + details(r)).toLowerCase().includes(q)));
    $("pj-rows").innerHTML = rows.length ? rows.map(r=>`<tr>
      <td class="mono">${esc(when(r.ts))}</td>
      <td>${esc(r.step||"")}</td>
      <td style="color:${COLOR[r.status]||"inherit"};font-weight:600">${esc(MARK[r.status]||r.status||"")}</td>
      <td class="cell-muted">${esc(details(r))}</td></tr>`).join("")
      : '<tr><td colspan="4" class="cell-muted">Записів немає.</td></tr>';
    const bad = d["проблем"] || 0;
    note().textContent = `показано ${rows.length} з ${list.length} записів`
      + (d["оновлено"] ? ` · зведено ${when(d["оновлено"])}` : "")
      + (bad ? ` · проблем: ${bad}` : " · проблем немає");
  };
  ["pj-status","pj-q"].forEach(id=>$(id).addEventListener(id==="pj-q"?"input":"change", draw));
  draw();
}

const fmtN = (v, dec=0) => {
  const n = Number(v)||0;
  const s = n.toLocaleString("uk-UA", {minimumFractionDigits:dec, maximumFractionDigits:dec});
  return n < 0 ? `<span class="neg" style="color:var(--crit-text);font-weight:600">${s}</span>` : s;
};
async function fetchFin(name){
  const r = await fetch("/finrep-data?name="+name, {headers:{"xc-auth": JWT||""}});
  let js = {};
  try { js = await r.json(); } catch(e){ js = {}; }
  if (r.status === 403){
    const who = js.role ? (" · сервер побачив роль: " + js.role) : "";
    throw new Error((js.error || "доступ заборонено") + who);
  }
  if (!r.ok) throw new Error((js.error||"помилка даних") + " (HTTP " + r.status + ")");
  return js;
}
function refreshBar(mtime, onFresh){
  const dt = new Date(mtime*1000);
  const stamp = dt.toLocaleString("uk-UA",{day:"2-digit",month:"2-digit",hour:"2-digit",minute:"2-digit"});
  setTimeout(()=>{
    const b = $("fin-refresh");
    if (!b) return;
    b.addEventListener("click", async ()=>{
      b.disabled = true; b.textContent = "⏳ Тягну з Експедитора (~2 хв)…";
      refreshNote("fin-note", "run", "Тягну з Експедитора…");
      try{
        // /cash-refresh спершу перераховує залишки кас з Експедитора, потім
        // запускає звичайну перебудову звіту — інакше звіт брав би стару касу
        await svc("/cash-refresh");
        const t0 = mtime;
        const poll = setInterval(async ()=>{
          try{
            const js = await fetchFin("dashboard");
            if (js.mtime > t0 + 5){ clearInterval(poll); refreshNote("fin-note","ok");
              toast("✅ Дані оновлено з Експедитора"); onFresh(); }
          }catch(e){}
        }, 15000);
        // Якщо за 4 хвилини файл так і не оновився — це НЕ «мовчки нічого»,
        // а помилка: кажемо про неї і повертаємо кнопку в робочий стан.
        setTimeout(()=>{
          clearInterval(poll);
          const bb = $("fin-refresh");
          if (bb && bb.disabled){
            bb.disabled = false; bb.textContent = "⟳ Підтягнути свіжі дані з Експедитора";
            refreshNote("fin-note","err","дані не оновились за 4 хвилини. Спробуй ще раз; якщо повториться — скажи Клоду");
          }
        }, 240000);
      }catch(e){ b.disabled=false; b.textContent="⟳ Підтягнути свіжі дані з Експедитора";
        refreshNote("fin-note", /вже виконується/.test(e.message)?"busy":"err", e.message); }
    });
  }, 0);
  // кнопка живе у верхній панелі (слот #fin-refresh-slot), поруч із кнопками звітів
  setTimeout(()=>restoreNote("fin-note"), 0);
  return `<span style="display:inline-flex;flex-direction:column;gap:2px">
    <button class="btn" id="fin-refresh" style="padding:7px 14px;font-size:13px"
      title="дані станом на ${stamp}">⟳ Підтягнути свіжі дані з Експедитора</button>
    <span id="fin-note"></span></span>`;
}
function finTable(headers, rows){
  return `<div class="tablewrap"><table><thead><tr>${headers.map(h=>`<th>${h}</th>`).join("")}</tr></thead>
    <tbody>${rows.join("")}</tbody></table></div>`;
}

/* ===== ФІНАНСОВІ ДАШБОРДИ — ті самі сторінки, що й у таблиці «Фін звітність (АРІ)».
   www/findash.html і www/finperiod.html згенеровані з apps-script/Code.gs движка
   (unitex-finrep) один-в-один; платформа лише передає їм дані з /finrep-data
   і підганяє висоту рамки під вміст. ===== */
const FIN_FRAME = {};              // id рамки -> дані, які їй віддати
window.addEventListener("message", e => {
  const m = e.data || {};
  if (m.type !== "findash-ready" && m.type !== "findash-height") return;
  const fr = Object.keys(FIN_FRAME).map(id => document.getElementById(id))
                   .find(f => f && f.contentWindow === e.source);
  if (!fr) return;
  if (m.type === "findash-ready") fr.contentWindow.postMessage({type:"findata", data: FIN_FRAME[fr.id]}, "*");
  if (m.type === "findash-height" && m.h) fr.style.height = (Number(m.h) + 8) + "px";
});
function finFrame(id, src, data){
  FIN_FRAME[id] = data;
  setTimeout(()=>{                 // страховка, якщо «ready» загубився
    const fr = $(id);
    if (fr) fr.addEventListener("load", ()=>{
      try{ fr.contentWindow.postMessage({type:"findata", data: FIN_FRAME[id]}, "*"); }catch(e){}
    });
  }, 0);
  return `<iframe id="${id}" class="finframe" src="${src}" title="фінансовий звіт"></iframe>`;
}

async function renderOper(){
  $("rep-body").innerHTML = '<div class="card"><p class="sub">Завантаження звіту…</p></div>';
  let js;
  try{ js = await fetchFin("dashboard"); }
  catch(e){ $("rep-body").innerHTML = `<div class="note">⚠ ${esc(e.message)}</div>`; return; }
  $("fin-refresh-slot").innerHTML = refreshBar(js.mtime, renderOper);
  $("rep-body").innerHTML = finFrame("findash", "/findash.html?v=19", js.data);
  window.scrollTo(0,0);
}

async function renderPeriod(){
  $("rep-body").innerHTML = '<div class="card"><p class="sub">Завантаження даних періоду…</p></div>';
  let js;
  try{ js = await fetchFin("period"); }
  catch(e){ $("rep-body").innerHTML = `<div class="note">⚠ ${esc(e.message)}</div>`; return; }
  $("fin-refresh-slot").innerHTML = refreshBar(js.mtime, renderPeriod);
  $("rep-body").innerHTML = finFrame("finperiod", "/finperiod.html?v=19", js.data);
  window.scrollTo(0,0);
}

/* ===== ОПЛАТИ МАЕРСКУ (запит користувачки 02.08.2026) =====
   Джерело — computed/maersk_payments.json, який рахує finrep/maersk_payments.py:
   рухи грошей з Експедитора, де контрагент Maersk A/S і це виплата (expense_uo > 0).
   Вид оплати і валюта не фільтруються: сума в У.О. + розбивка по валютах і касах.

   УВАГА: цей блок уже ТРИЧІ зникав із main при злитті гілок (02.08.2026 —
   коміти bebd596 → 2822835). Перед деплоєм фасада перевіряти, що він на місці:
   `grep -c 'function renderMaersk' www/index.html` має дати 1, а не 0. */
async function renderMaersk(){
  $("rep-body").innerHTML = '<div class="card"><p class="sub">Рахую оплати Маерску…</p></div>';
  let js;
  try{ js = await fetchFin("maersk_payments"); }
  catch(e){ $("rep-body").innerHTML = `<div class="note">⚠ ${esc(e.message)}</div>`; return; }
  const D = js.data || js;
  const rows = D.rows || [];
  const money = v => fmtN(v, 2);
  const pairs = o => Object.entries(o || {}).filter(([,v])=>v)
      .sort((a,b)=>b[1]-a[1]).map(([k,v])=>`${esc(k)} ${money(v)}`).join(" · ") || "—";
  const body = rows.map(r=>`<tr>
      <td>${esc(r.label || r.month)}</td>
      <td class="num"><b>${money(r.uo)}</b></td>
      <td class="num">${esc(r.count)}</td>
      <td>${pairs(r.byCurrency)}</td>
      <td>${pairs(r.byMethod)}</td></tr>`);
  if (rows.length) body.push(`<tr style="font-weight:700;border-top:2px solid var(--line)">
      <td>РАЗОМ</td><td class="num">${money(D.totalUo)}</td><td class="num">${esc(D.count)}</td>
      <td>${pairs(D.byCurrency)}</td><td>${pairs(D.byMethod)}</td></tr>`);
  const exc = D.excluded || {};
  $("fin-refresh-slot").innerHTML = js.mtime ? refreshBar(js.mtime, renderMaersk) : "";
  $("rep-body").innerHTML = `
    <div class="card">
      <h3>🚢 Оплати Маерску по місяцях</h3>
      <p class="sub">контрагент <b>${esc((D.counterparties||["Maersk A/S"]).join(", "))}</b> ·
        усі види оплати і всі валюти · суми в У.О. (USD-еквівалент)</p>
      ${rows.length ? finTable(["Місяць","Сума У.О.","Платежів","У валютах платежу","Через касу / банк"], body)
                    : '<p class="sub">Оплат не знайдено.</p>'}
      <div class="note">Не входять: внутрішні перекази — ${esc(exc.transfers ?? 0)},
        надходження/повернення від Маерска — ${esc(exc.incomes ?? 0)}.
        Джерело: ${esc(D.source || "normalized/cash_moves.csv")}.</div>
    </div>`;
  window.scrollTo(0,0);
}

/* ===== КАЛЬКУЛЯЦІЯ ===== */
const CALC_ST = ["Чернетка","Відправлено клієнту","Прийнято","Відхилено"];
const CALC_ST_CLS = {"Чернетка":"t-neutral","Відправлено клієнту":"t-info","Прийнято":"t-good","Відхилено":"t-vio"};
const CALC_SEED = [["Морський фрахт","",""],["Автовивіз / доставка","",""],["Винагорода експедитора","",""]];
let CALC_ROWS = null, CALC_CUR = null;

/* Розбір суми. ЄДИНЕ правило для всіх форматів, які реально приходять:
   українського «1 250,50» і англійського «1,250.50» з листів ліній.

   Було до 02.08.2026: parseFloat(...replace(",", ".")) — замінювалась лише ПЕРША
   кома, тому «12,000» ставало 12, а «1,250.00» — 1.25. Помилка в 1000 разів,
   і вона мовчки лягала в базу та в CSV для Експедитора.

   Правило: прибрати пробіли; якщо є і кома, і крапка — десятковий той, що
   СТОЇТЬ ОСТАННІМ; якщо є лише один вид — він десятковий тільки тоді, коли
   трапляється один раз і після нього 1-2 цифри, інакше це роздільник тисяч.
   Роздільники тисяч приймаються лише правильними групами по 3 цифри —
   тому «3.06.26» (дата) розпізнається як НЕ число, а не як 30626.

   Повертає NaN, якщо це не число. Порожнє значення — 0 (порожній рядок = нуль).
   Раніше будь-яке сміття тихо ставало нулем; тепер його видно (див. numBad). */
function num(v){
  const s = String(v==null ? "" : v).replace(/[\s   ]/g, "");
  if (!s) return 0;
  if (!/^[+-]?[\d.,]+$/.test(s)) return NaN;
  const sign = s[0] === "-" ? -1 : 1;
  const body = s.replace(/^[+-]/, "");
  if (!/\d/.test(body)) return NaN;
  const lastC = body.lastIndexOf(","), lastD = body.lastIndexOf(".");
  let decAt = -1;
  if (lastC >= 0 && lastD >= 0) decAt = Math.max(lastC, lastD);
  else {
    const only = lastC >= 0 ? "," : (lastD >= 0 ? "." : null);
    if (only){
      const pos = only === "," ? lastC : lastD;
      const cnt = body.split(only).length - 1;
      const after = body.length - pos - 1;
      if (cnt === 1 && after >= 1 && after <= 2) decAt = pos;
    }
  }
  const intRaw = decAt >= 0 ? body.slice(0, decAt) : body;
  const frac   = decAt >= 0 ? body.slice(decAt + 1) : "";
  if (frac && !/^\d+$/.test(frac)) return NaN;
  // ціла частина: або суцільні цифри, або правильні групи по 3 (1-3 у першій)
  let intDigits;
  if (/^\d*$/.test(intRaw)) intDigits = intRaw;
  else {
    const parts = intRaw.split(/[.,]/);
    if (parts.length < 2) return NaN;
    if (!/^\d{1,3}$/.test(parts[0])) return NaN;
    if (!parts.slice(1).every(p => /^\d{3}$/.test(p))) return NaN;
    intDigits = parts.join("");
  }
  const n = parseFloat((intDigits || "0") + (frac ? "." + frac : ""));
  return isFinite(n) ? sign * n : NaN;
}
/* Чи є серед значень таке, яке не вдалось розпізнати як число. */
const numBad = v => Number.isNaN(num(v));
function calcLines(raw){
  return String(raw||"").split("\n").map(l=>l.trim()).filter(Boolean).map(l=>{
    const p = l.split("|").map(x=>x.trim());
    return [p[0]||"", p[1]||"", p[2]||""];
  });
}
const linesToRaw = arr => arr.map(x=>x.join(" | ")).join("\n");
function calcTotals(arr){
  let cost=0, sell=0;
  // bad — рядки, де сума написана так, що її неможливо однозначно прочитати.
  // Раніше вони мовчки ставали нулем; тепер про них видно і зберегти не можна.
  const bad = [];
  arr.forEach(([name,c,s],i)=>{
    if (numBad(c) || numBad(s)) bad.push({i, name: name || ("рядок " + (i+1))});
    cost += numBad(c) ? 0 : num(c);
    sell += numBad(s) ? 0 : num(s);
  });
  return {cost, sell, profit: sell-cost, bad};
}
const money = (n,cur) => (Math.round(n*100)/100).toLocaleString("uk-UA") + " " + (cur||"USD");

/* --- розбір тексту запиту клієнта --- */
function parseRequest(text){
  const t = String(text||"").replace(/\u00a0/g," ");
  const out = {};
  const find = (re, g) => { const m = re.exec(t); if (!m) return ""; const i = (g === undefined ? 1 : g); return (m[i]||"").trim(); };
  const lbl = names => find(new RegExp("(?:"+names+")\\s*[:\\-\u2013]\\s*([^\\n]{2,80})","i"));
  const clean = s => String(s||"").replace(/^[\s.,;:\-]+/,"").replace(/[\s.,;:\-\u2013]+$/,"").trim();

  // напрямок (\b не працює з кирилицею — тому без нього)
  if (/експорт|export/i.test(t)) out["Напрямок"] = "Експорт";
  if (/імпорт|import/i.test(t)) out["Напрямок"] = "Імпорт";
  if (/транзит|transit/i.test(t)) out["Напрямок"] = "Транзит";

  // контейнер/транспорт — визначаємо першим, щоб прибрати токен із тексту для маршруту
  let cm = /(\d{1,2})\s*[xх*]\s*(20|40|45)\s*['\u2019]?\s*(HC|HQ|DC|DV|RF|OT|FR|НС|ДС|GP)?/i.exec(t);
  let qty = "", eq = "";
  if (cm){ qty = cm[1]; eq = cm[2] + (cm[3] ? cm[3].toUpperCase() : ""); }
  else {
    cm = /(?:^|[\s(])(20|40|45)\s*['\u2019]?\s*(HC|HQ|DC|DV|RF|GP)(?![\wА-Яа-яЇїІіЄєҐґ])/i.exec(t);
    if (cm){ qty = "1"; eq = cm[1] + cm[2].toUpperCase(); }
  }
  if (!eq && /LCL|збірн/i.test(t)) eq = "LCL";
  if (!eq && /тент|тягач|truck|фур[аи]/i.test(t)) eq = "Авто";
  if (qty) out["Кількість"] = qty;
  if (eq) out["Тип обладнання"] = eq;
  const rt = cm ? t.replace(cm[0], "  ") : t;

  // маршрут: явна мітка -> «з X до Y» -> «X – Y»
  const P1 = "[A-Za-zА-Яа-яЇїІіЄєҐґ'\u2019\\.\\- ]{2,32}";
  const P2 = P1 + "(?:,\\s*[A-Za-zА-Яа-яЇїІіЄєҐґ'\u2019\\.\\- ]{2,24})?";
  let pol = lbl("POL|порт завантаження|port of loading|звідки|відправлення");
  let pod = lbl("POD|порт вивантаження|порт призначення|port of discharge|куди|призначення");
  let route = lbl("маршрут|route");
  if (!pol || !pod){
    const m = new RegExp("(?:^|[\\s(])(?:з|із|від|from)\\s+("+P2+")\\s+(?:до|в|to)\\s+("+P2+")","i").exec(rt);
    if (m){ pol = pol || clean(m[1]); pod = pod || clean(m[2]); }
  }
  if (!pol || !pod){
    // назва міста — слова з великої літери поруч із тире (щоб не захопити «прорахуйте будь ласка»)
    const big = w => w && w[0] === w[0].toLocaleUpperCase("uk") && /[A-Za-zА-ЯЇІЄҐ]/.test(w[0]);
    const tail = s => { const p = clean(s).split(/\s+/); const r = []; for (let i=p.length-1;i>=0 && r.length<3;i--){ if(!big(p[i])) break; r.unshift(p[i]); } return r.join(" "); };
    const head = s => { const p = clean(s).split(/\s+/); const r = []; for (let i=0;i<p.length && r.length<3;i++){ if(!big(p[i])) break; r.push(p[i]); } return r.join(" "); };
    const m = new RegExp("("+P1+")\\s*(?:\u2014|\u2013|->|\u2192|-{1,2})\\s*("+P1+")").exec(rt);
    if (m){ pol = pol || tail(m[1]); pod = pod || head(m[2]); }
  }
  if (pol) out["POL"] = pol;
  if (pod) out["POD"] = pod;
  if (!route && pol && pod) route = pol + " \u2013 " + pod;
  if (route) out["Маршрут"] = route;

  // вага — у класі символів немає \s, інакше захоплює перенос рядка
  const w = /(\d[\d  .]{0,12}\d|\d)\s*(кг|kg|тонн\w*|тон|т(?![а-яїієґA-Za-z])|tons?|mt)/i.exec(t);
  if (w) out["Вага"] = w[1].replace(/\s+/g," ").trim() + " " + w[2].toLowerCase();

  // інкотермс — не перетинаємо рядок ([^\S\n] = пробіл, але не перенос)
  const inc = /(?:^|[\s(])(EXW|FCA|FAS|FOB|CFR|CIF|CPT|CIP|DAP|DPU|DDP)(?![A-Za-z])[^\S\n]*([A-Za-zА-Яа-яЇїІіЄєҐґ'\u2019\-]+(?:[^\S\n]+[A-Za-zА-Яа-яЇїІіЄєҐґ'\u2019\-]+)?)?/i.exec(t);
  if (inc) out["Інкотермс"] = clean(inc[1].toUpperCase() + " " + (inc[2]||""));

  // код УКТЗЕД — лише цифри
  const hs = find(/(?:УКТЗЕД|УКТ\s?ЗЕД|HS(?:\s*code)?)\s*[:\-\u2013]?\s*(\d{4,10})/i);
  if (hs) out["УКТЗЕД"] = hs;

  // вантаж — без хвоста з кодом
  let cargo = lbl("вантаж|товар|cargo|commodity|груз");
  if (cargo) cargo = clean(cargo.replace(/[,;]?\s*(?:УКТЗЕД|УКТ\s?ЗЕД|HS(?:\s*code)?)[\s:\-]*\d*.*$/i, ""));
  if (cargo) out["Вантаж"] = cargo;

  // готовність
  const rd = lbl("готовність|дата готовності|readiness|ready date|ready") ||
             find(/готов\w*[^\d\n]{0,20}(\d{1,2}[.\/\-]\d{1,2}[.\/\-]\d{2,4})/i);
  if (rd) out["Готовність"] = rd;

  // клієнт: назва в лапках після форми власності або латиною перед LLC/EHF
  let cl = find(/(?:ТОВ|ТзОВ|ПрАТ|ПАТ|ПП|ФОП)\s*[«"'][^»"'\n]{2,40}[»"']/i, 0);
  if (!cl) cl = find(/[A-Z][A-Za-z&.\-]{1,20}(?:\s+[A-Z][A-Za-z&.\-]{1,20}){0,3}\s+(?:LLC|LTD|Ltd|OU|EHF|ehf|GmbH|Inc)(?![A-Za-z])/, 0);
  if (cl) out["Клієнт"] = clean(cl);

  Object.keys(out).forEach(k=>{ if(!out[k]) delete out[k]; });
  return out;
}

/* --- CSV для завантаження в Експедитор --- */
function calcCsv(r){
  const lines = calcLines(r["Позиції"]);
  const head = ["Номер калькуляції","Дата","Клієнт","Напрямок","Маршрут","POL","POD","Тип обладнання",
    "Кількість","Вантаж","Вага","Інкотермс","УКТЗЕД","Готовність","Собівартість","Продаж","Прибуток","Валюта","Менеджер"];
  const row = [r["Номер"],r["Дата"],r["Клієнт"],r["Напрямок"],r["Маршрут"],r["POL"],r["POD"],r["Тип обладнання"],
    r["Кількість"],r["Вантаж"],r["Вага"],r["Інкотермс"],r["УКТЗЕД"],r["Готовність"],r["Собівартість"],r["Продаж"],r["Прибуток"],r["Валюта"],r["Менеджер"]];
  const esc2 = v => '"' + String(v==null?"":v).replace(/"/g,'""').replace(/\n/g," ") + '"';
  let csv = head.map(esc2).join(";") + "\r\n" + row.map(esc2).join(";") + "\r\n";
  if (lines.length){
    csv += "\r\n" + ["Позиція","Собівартість","Продаж"].map(esc2).join(";") + "\r\n";
    csv += lines.map(l=>l.map(esc2).join(";")).join("\r\n") + "\r\n";
  }
  const blob = new Blob(["﻿"+csv], {type:"text/csv;charset=utf-8"});
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = "kalkulyatsiya-" + String(r["Номер"]||"nova").replace(/[^\wа-яїієґА-ЯЇІЄҐ.-]/gi,"_") + ".csv";
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(()=>URL.revokeObjectURL(a.href), 3000);
}

async function calcRows(force){
  if (force) CALC_ROWS = null;
  return CALC_ROWS || (CALC_ROWS = await loadAll(T["Калькуляції"]));
}
function calcScoped(rows){
  return cfg().scope === "mgr" ? rows.filter(r=>String(r["Менеджер"]||"").trim() === UNAME) : rows;
}
function nextCalcNo(rows){
  const y = new Date().getFullYear();
  const nums = rows.map(r=>{ const m=new RegExp("^К-"+y+"-(\\d+)$").exec(String(r["Номер"]||"")); return m?+m[1]:0; });
  return "К-" + y + "-" + String(Math.max(0, ...nums) + 1).padStart(3, "0");
}

PAGES.calc = async () => {
  const all = calcScoped(await calcRows());
  const ro = (ROLE === "Перегляд");
  const sum = st => all.filter(r=>r["Статус"]===st).length;
  $("content").innerHTML = `
    <div class="card">
      <div style="display:flex;align-items:center;gap:12px;flex-wrap:wrap">
        <span class="sub" style="margin:0">усього: ${all.length} · прийнято: ${sum("Прийнято")} · чернеток: ${sum("Чернетка")}</span>
      </div>
      <div class="filters" style="margin-top:12px">
        <input id="cq" placeholder="Пошук: номер, клієнт, маршрут…">
        <select id="cst"><option value="">Усі статуси</option>${CALC_ST.map(s=>`<option>${s}</option>`).join("")}</select>
      </div>
      <div class="tablewrap mcards" style="margin-top:10px"><table>
        <thead><tr><th>Номер</th><th>Дата</th><th>Клієнт</th><th>Маршрут</th><th>Обладнання</th>
          <th>Собівартість</th><th>Продаж</th><th>Прибуток</th><th>Статус</th><th>Угода</th><th></th></tr></thead>
        <tbody id="crows"></tbody>
      </table></div>
    </div>
    <div class="note">💡 Встав текст запиту клієнта у вікно — система рознесе дані по полях. Перевір їх перед збереженням: розбір автоматичний і може щось не впізнати.</div>`;

  const render = () => {
    const q = ($("cq").value||"").toLowerCase().trim();
    const st = $("cst").value;
    const rows = all.filter(r=>{
      if (st && r["Статус"] !== st) return false;
      if (!q) return true;
      return ["Номер","Клієнт","Маршрут","Вантаж","Угода"].some(k=>String(r[k]||"").toLowerCase().includes(q));
    }).sort((a,b)=>String(b["Номер"]||"").localeCompare(String(a["Номер"]||"")));
    $("crows").innerHTML = rows.length ? rows.map(r=>{
      const cur = r["Валюта"]||"USD";
      return `<tr data-calc="${r.Id}">
        <td class="mono"><b>${esc(r["Номер"]||"—")}</b></td>
        <td class="mono" data-l="Дата">${esc(r["Дата"]||"—")}</td>
        <td data-l="Клієнт">${esc(r["Клієнт"]||"—")}</td>
        <td data-l="Маршрут">${esc(r["Маршрут"]||"—")}</td>
        <td data-l="Обладнання">${esc([r["Кількість"],r["Тип обладнання"]].filter(Boolean).join("×")||"—")}</td>
        <td class="mono" data-l="Собівартість">${r["Собівартість"]?money(num(r["Собівартість"]),cur):"—"}</td>
        <td class="mono" data-l="Продаж">${r["Продаж"]?money(num(r["Продаж"]),cur):"—"}</td>
        <td class="mono" data-l="Прибуток"><b>${r["Прибуток"]?money(num(r["Прибуток"]),cur):"—"}</b></td>
        <td data-l="Статус"><span class="pill ${CALC_ST_CLS[r["Статус"]]||"t-neutral"}">${esc(r["Статус"]||"Чернетка")}</span></td>
        <td class="mono" data-l="Угода">${esc(r["Угода"]||"—")}</td>
        <td><button class="btn ghost calc-open" data-id="${r.Id}" style="padding:3px 10px">Відкрити</button></td>
      </tr>`;
    }).join("") : '<tr><td colspan="11" class="cell-muted">Калькуляцій поки немає.</td></tr>';
    markEmptyCells($("crows"));
    $("crows").querySelectorAll(".calc-open").forEach(b=>b.addEventListener("click",()=>openCalc(all.find(x=>String(x.Id)===b.dataset.id))));
  };
  $("cq").addEventListener("input", render);
  $("cst").addEventListener("change", render);
  render();
  if (!ro){
    $("page-actions").innerHTML = '<button class="btn" id="calc-new">＋ Нова калькуляція</button>';
    $("calc-new").addEventListener("click", ()=>openCalc(null));
  }
};

const CALC_FIELDS = [
  {k:"Клієнт"}, {k:"Дата", d:1}, {k:"Напрямок", sel:["","Імпорт","Експорт","Транзит"]},
  {k:"Маршрут"}, {k:"POL", label:"POL (порт завантаження)"}, {k:"POD", label:"POD (порт вивантаження)"},
  {k:"Тип обладнання"}, {k:"Кількість"}, {k:"Вага"}, {k:"Інкотермс"},
  {k:"УКТЗЕД"}, {k:"Готовність"}, {k:"Вантаж", ta:1},
];
const CINP = 'style="padding:7px 9px;border:1px solid var(--line);border-radius:7px;background:var(--paper);color:var(--ink);font-size:13px;width:100%;box-sizing:border-box;font-family:inherit"';

function openCalc(r){
  const isNew = !r;
  const ro = (ROLE === "Перегляд");
  CALC_CUR = r ? Object.assign({}, r) : {"Статус":"Чернетка","Валюта":"USD","Менеджер":UNAME,
    "Дата": new Date().toISOString().slice(0,10), "Позиції": linesToRaw(CALC_SEED)};
  const c = CALC_CUR;
  $("calc-title").textContent = isNew ? "🧮 Нова калькуляція" : ("🧮 " + (c["Номер"]||"") + " · " + (c["Клієнт"]||""));
  $("calc-body").innerHTML = `
    <div style="margin-bottom:10px">
      <div style="font-weight:600;font-size:13.5px;margin-bottom:5px">Запит клієнта</div>
      <textarea id="c-req" rows="5" ${CINP} placeholder="Встав сюди лист/повідомлення клієнта — система рознесе дані по полях нижче">${esc(c["Запит"]||"")}</textarea>
      <div style="display:flex;gap:8px;margin-top:8px;align-items:center">
        ${ro?"":'<button class="btn" id="c-parse">🪄 Рознести по полях</button>'}
        <span class="sub" id="c-parse-res" style="margin:0"></span>
      </div>
    </div>
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px">
      ${CALC_FIELDS.map(f=>{
        const v = c[f.k]||"";
        const inp = f.sel ? `<select data-c="${f.k}" ${CINP}>${f.sel.map(o=>`<option${o===v?" selected":""}>${o}</option>`).join("")}</select>`
          : f.ta ? `<textarea data-c="${f.k}" rows="2" ${CINP}>${esc(v)}</textarea>`
          : `<input data-c="${f.k}" type="${f.d?"date":"text"}" value="${esc(v)}" ${CINP}>`;
        return `<label style="${f.ta?"grid-column:1/-1;":""}font-size:12px;color:var(--muted);display:flex;flex-direction:column;gap:3px">${esc(f.label||f.k)}${inp}</label>`;
      }).join("")}
    </div>
    <div style="margin-top:14px;border-top:1px solid var(--line);padding-top:10px">
      <div style="display:flex;align-items:center;gap:10px">
        <div style="font-weight:600;font-size:13.5px">Позиції калькуляції</div>
        <span style="flex:1"></span>
        <label style="font-size:12px;color:var(--muted);display:flex;align-items:center;gap:5px">Валюта
          <select id="c-cur" style="padding:4px 7px;border:1px solid var(--line);border-radius:6px;background:var(--paper);color:var(--ink);font-size:12.5px">
            ${["USD","EUR","UAH"].map(x=>`<option${x===(c["Валюта"]||"USD")?" selected":""}>${x}</option>`).join("")}</select></label>
        ${ro?"":'<button class="btn ghost" id="c-add" style="padding:4px 10px">＋ рядок</button>'}
      </div>
      <table style="margin-top:8px"><thead><tr><th>Послуга</th><th style="width:120px">Собівартість</th><th style="width:120px">Продаж</th><th style="width:34px"></th></tr></thead>
        <tbody id="c-lines"></tbody></table>
      <div id="c-tot" class="sub" style="margin-top:8px;font-size:13px"></div>
    </div>
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-top:12px">
      <label style="font-size:12px;color:var(--muted);display:flex;flex-direction:column;gap:3px">Статус
        <select data-c="Статус" ${CINP}>${CALC_ST.map(s=>`<option${s===(c["Статус"]||"Чернетка")?" selected":""}>${s}</option>`).join("")}</select></label>
      <label style="font-size:12px;color:var(--muted);display:flex;flex-direction:column;gap:3px">№ угоди (після імпорту в Експедитор)
        <input data-c="Угода" type="text" value="${esc(c["Угода"]||"")}" ${CINP}></label>
      <label style="grid-column:1/-1;font-size:12px;color:var(--muted);display:flex;flex-direction:column;gap:3px">Коментар
        <textarea data-c="Коментар" rows="2" ${CINP}>${esc(c["Коментар"]||"")}</textarea></label>
    </div>
    <p class="sub" id="c-status" style="margin-top:8px"></p>`;

  const linesBody = $("c-lines");
  let lines = calcLines(c["Позиції"]);
  if (!lines.length) lines = CALC_SEED.map(x=>x.slice());
  const drawTotals = () => {
    const t = calcTotals(lines), cur = $("c-cur").value;
    const marg = t.sell ? Math.round(t.profit/t.sell*1000)/10 : 0;
    const warn = t.bad.length
      ? `<div style="color:#b91c1c;font-weight:600;margin-top:6px">⚠ Не змогла прочитати суму: ${
          esc(t.bad.map(b=>b.name).join(", "))}. Підсумок неповний, зберегти не можна —
          напиши число як <b>1250,50</b> або <b>1 250,50</b>.</div>`
      : "";
    $("c-tot").innerHTML = `Собівартість: <b>${money(t.cost,cur)}</b> · Продаж: <b>${money(t.sell,cur)}</b> · Прибуток: <b style="color:${t.profit<0?"#b91c1c":"inherit"}">${money(t.profit,cur)}</b>${t.sell?` · маржа ${marg}%`:""}` + warn;
    const sv = $("calc-save");
    if (sv) { sv.disabled = t.bad.length > 0; sv.style.opacity = t.bad.length ? .5 : 1; }
  };
  const drawLines = () => {
    linesBody.innerHTML = lines.map((l,i)=>`<tr>
      <td><input data-l="${i}" data-f="0" value="${esc(l[0])}" ${CINP}></td>
      <td><input data-l="${i}" data-f="1" value="${esc(l[1])}" inputmode="decimal" ${CINP}></td>
      <td><input data-l="${i}" data-f="2" value="${esc(l[2])}" inputmode="decimal" ${CINP}></td>
      <td>${ro?"":`<button class="btn ghost c-del" data-i="${i}" style="padding:3px 8px" title="Видалити рядок">✕</button>`}</td></tr>`).join("");
    linesBody.querySelectorAll("input").forEach(inp=>{
      if (ro) inp.disabled = true;
      inp.addEventListener("input", ()=>{ lines[+inp.dataset.l][+inp.dataset.f] = inp.value; drawTotals(); });
    });
    linesBody.querySelectorAll(".c-del").forEach(b=>b.addEventListener("click", ()=>{ lines.splice(+b.dataset.i,1); drawLines(); }));
    drawTotals();
  };
  drawLines();
  $("c-cur").addEventListener("change", drawTotals);
  const addb = $("c-add");
  if (addb) addb.addEventListener("click", ()=>{ lines.push(["","",""]); drawLines(); });
  const pb = $("c-parse");
  if (pb) pb.addEventListener("click", ()=>{
    const got = parseRequest($("c-req").value);
    const keys = Object.keys(got);
    keys.forEach(k=>{
      const el = $("calc-body").querySelector(`[data-c="${k}"]`);
      if (el){ el.value = got[k]; el.style.background = "rgba(37,99,235,.08)"; }
    });
    $("c-parse-res").textContent = keys.length
      ? "Впізнано полів: " + keys.length + " (" + keys.join(", ") + ") — перевір значення"
      : "Нічого не впізнала — заповни поля вручну";
  });
  if (ro) $("calc-body").querySelectorAll("input,select,textarea").forEach(el=>el.disabled = true);

  $("calc-save").style.display = ro ? "none" : "block";
  $("calc-deal").style.display = (ro || isNew) ? "none" : "block";
  $("calc-csv").style.display = isNew ? "none" : "block";
  $("calc-save").onclick = async () => {
    const body = {};
    $("calc-body").querySelectorAll("[data-c]").forEach(el=>{ body[el.dataset.c] = el.value; });
    const t = calcTotals(lines);
    // Запобіжник: у базу і в CSV для Експедитора не має потрапити сума,
    // яку ми не змогли прочитати однозначно (кнопка вже вимкнена, це другий рубіж).
    if (t.bad.length){
      $("c-status").textContent = "⚠ Не збережено: не змогла прочитати суму — " +
        t.bad.map(b=>b.name).join(", ");
      return;
    }
    Object.assign(body, {"Запит": $("c-req").value, "Позиції": linesToRaw(lines), "Валюта": $("c-cur").value,
      "Собівартість": t.cost, "Продаж": t.sell, "Прибуток": t.profit, "Менеджер": c["Менеджер"]||UNAME});
    Object.keys(body).forEach(k=>{ if (body[k] === "" || body[k] === undefined) body[k] = null; });
    $("c-status").textContent = "⏳ Зберігаю…";
    try{
      if (isNew){
        body["Номер"] = nextCalcNo(await calcRows());
        await api(`/api/v2/tables/${T["Калькуляції"]}/records`, {method:"POST", body: JSON.stringify([body])});
      } else {
        body["Id"] = c.Id;
        await api(`/api/v2/tables/${T["Калькуляції"]}/records`, {method:"PATCH", body: JSON.stringify([body])});
      }
      await calcRows(true);
      const saved = (await calcRows()).some(x => String(x["Номер"]||"") === String(body["Номер"]||c["Номер"]||""));
      if (!saved) throw new Error("сервер не повернув помилку, але запис у базі не з'явився");
      $("calc-overlay").classList.remove("open");
      toast("✅ Калькуляцію збережено");
      go("calc");
    } catch(e){ $("c-status").textContent = "⚠ Не вдалося зберегти (" + e.message + ")"; }
  };
  $("calc-csv").onclick = () => {
    const body = {};
    $("calc-body").querySelectorAll("[data-c]").forEach(el=>{ body[el.dataset.c] = el.value; });
    const t = calcTotals(lines);
    calcCsv(Object.assign({}, c, body, {"Позиції": linesToRaw(lines), "Валюта": $("c-cur").value,
      "Собівартість": t.cost, "Продаж": t.sell, "Прибуток": t.profit}));
    toast("📄 Файл вивантажено — завантаж його в Експедитор");
  };
  $("calc-deal").onclick = async () => {
    const g = k => { const el = $("calc-body").querySelector(`[data-c="${k}"]`); return el ? el.value : (c[k]||""); };
    const dealNo = prompt("№ угоди для диспетчеризації (з Експедитора, якщо вже присвоєний):", c["Угода"] || c["Номер"] || "");
    if (dealNo === null) return;
    $("c-status").textContent = "⏳ Створюю угоду…";
    try{
      const deal = {"Угода": dealNo, "Клієнт": g("Клієнт"), "Напрямок": g("Напрямок"), "Маршрут": g("Маршрут"),
        "Тип обладнання": g("Тип обладнання"), "Кількість": g("Кількість"), "Статус": "Букінг",
        "Менеджер": c["Менеджер"]||UNAME, "Коментар": "Створено з калькуляції " + (c["Номер"]||"")};
      await api(`/api/v2/tables/${T["Диспетчеризація"]}/records`, {method:"POST", body: JSON.stringify([deal])});
      await api(`/api/v2/tables/${T["Калькуляції"]}/records`, {method:"PATCH",
        body: JSON.stringify([{Id: c.Id, "Угода": dealNo, "Статус": "Прийнято"}])});
      DISP_CACHE = null; await calcRows(true);
      $("c-status").textContent = "";
      $("calc-overlay").classList.remove("open");
      toast("✅ Угоду " + dealNo + " створено в диспетчеризації");
      go("calc");
    } catch(e){ $("c-status").textContent = "⚠ Не вдалося створити угоду (" + e.message + ")"; }
  };
  $("calc-overlay").classList.add("open");
}

/* ═══════════════════ ЗАДАЧІ ═══════════════════════════════════════════════
   Вимога користувачки 12.08.2026: «постановка задач по угодам, по клієнтам,
   співпрацівникам та просто по діям з нагадуваннями та з можливістю додавати
   виконавців». Нагадування — В ПЛАТФОРМІ (не Telegram і не пошта, її рішення):
   лічильник біля пункту меню + блоки «Прострочені / На сьогодні» тут і на
   дашборді.

   Було до цього: сторінка ЛИШЕ читала таблицю (створити чи змінити статус з
   платформи було неможливо, статуси міняла я через API), поле «Кому» — один
   вибір із двох вписаних імен, прив'язки до клієнта і до співробітника не було
   зовсім. Колонки додає direct_sync/add_task_columns.py.

   ВИКОНАВЦІ ЛЕЖАТЬ У БАЗІ ЯК EMAIL-И ЧЕРЕЗ КОМУ, а показуються іменами. Причина
   не стильова: у довіднику `Користувачі` двоє людей з ім'ям «Ірина» (Кармазіна і
   Голобородько), тож ім'я не може бути ключем. Стара колонка «Кому» лишається
   недоторканою — нічого не видаляємо без прямого дозволу.

   «Співробітник» — це задача ПРО людину (оформити відпустку, провести навчання),
   а «Виконавці» — хто її РОБИТЬ. Це різні поля, і користувачка підтвердила, що
   потрібні обидва. */
const TASK_KINDS  = ["Угода", "Клієнт", "Співробітник", "Дія"];
const TASK_PRIO   = ["Терміново", "Звичайно", "Низько"];
const TASK_STATES = ["Нова", "В роботі", "Виконано", "Скасовано"];
const TASK_OPEN   = ["Нова", "В роботі"];
const TASK_PILL   = {"Нова":"t-info", "В роботі":"t-warn", "Виконано":"t-good", "Скасовано":"t-del"};
const PRIO_PILL   = {"Терміново":"t-crit", "Звичайно":"t-neutral", "Низько":"t-del"};
/* тип задачі → в яку колонку записаний її об'єкт */
const TASK_OBJ_FIELD = {"Угода":"Угода", "Клієнт":"Клієнт", "Співробітник":"Співробітник"};

/* Задачі веде кожен, хто взагалі бачить розділ, окрім ролі «Перегляд».
   Свідомо НЕ беремо cfg().edit — воно про право правити УГОДИ. Фінансист і
   бухгалтер угод не правлять, але свої задачі закривати мають. */
const canTask = () => ROLE !== "Перегляд" && cfg().nav.includes("tasks");

/* Чиї задачі видно. Рішення користувачки 12.08.2026: «адмін бачить всі задачі,
   інші ролі — тільки свої», і «адмін може обрати які ролі бачити».
   «Свої» = я виконавець АБО я поставила задачу.
   ⚠️ Це НЕ захист сам по собі: сторінка лише вирішує, що намалювати, а дані їй
   віддає база. Справжнє обмеження — у прошарку (server/gateway.py, TASK_SEE_ALL),
   і воно ввімкнеться разом із ним. Правила в обох місцях однакові навмисно. */
const canSeeAllTasks = () => ROLE === "Адміністратор";

let TASKS_CACHE = null, TUSERS_CACHE = null;
let TASK_FILTER = {who:"mine", kind:"", closed:false, roles:[]};

async function taskRows(force){
  if (force) TASKS_CACHE = null;
  return TASKS_CACHE || (TASKS_CACHE = await loadAll(T["Задачі"]));
}
/* Довідник людей для вибору виконавців. Помилку не ковтаємо мовчки: без списку
   призначити нікого не можна, і про це треба сказати, а не показати порожньо. */
async function taskUsers(){
  if (TUSERS_CACHE) return TUSERS_CACHE;
  TUSERS_CACHE = (await loadAll(T["Користувачі"])).filter(u=>u["Активний"] !== false);
  return TUSERS_CACHE;
}
const userLabel = u => [u["Ім'я"], u["Прізвище"]].filter(Boolean).join(" ").trim() || u["Email"] || "—";
const myEmail   = () => String(sessionStorage.getItem("email") || "").toLowerCase();
const doerList  = t => String(t["Виконавці"] || "").split(",").map(s=>s.trim().toLowerCase()).filter(Boolean);
function doerNames(t, users){
  return doerList(t).map(em=>{
    const u = (users||[]).find(x=>String(x["Email"]||"").toLowerCase() === em);
    return u ? userLabel(u) : em;
  });
}
const taskIsOpen = t => TASK_OPEN.includes(String(t["Статус"] || "Нова"));
const isMyTask   = t => { const me = myEmail(); return !!me &&
  (doerList(t).includes(me) || String(t["Постановник"]||"").toLowerCase() === me); };
/* скільки днів лишилось до терміну; null — терміну немає */
function taskDays(t){
  const d = dOf(t["Термін"]);
  if (!d) return null;
  const now = new Date(); now.setHours(0,0,0,0);
  return Math.round((d - now) / 86400000);
}
/* За скільки днів до терміну задача починає нагадувати. 0 — у сам день. */
function remindOf(t){
  const n = Number(t["Нагадати за"]);
  return Number.isFinite(n) && n >= 0 ? n : 0;
}
/* Задача «дзвонить»: термін настав, минув або настане в межах нагадування. */
const taskRings = t => { const d = taskDays(t); return taskIsOpen(t) && d !== null && d <= remindOf(t); };

/* Лічильник у меню — нагадування, яке видно з будь-якої сторінки.
   Рахуємо МОЇ задачі: і ті, де я виконавець, і ті, які я поставила (інакше
   керівник не бачив би, що доручене ним прострочено). */
function refreshTaskBadge(){
  const el = $("nav-tasks-badge");
  if (!el || !T["Задачі"]) return;
  taskRows(true).then(rows=>{
    const box = $("nav-tasks-badge");
    if (!box) return;
    const n = rows.filter(t=>isMyTask(t) && taskRings(t)).length;
    box.textContent = n;
    box.style.display = n ? "inline-flex" : "none";
    box.title = n + " " + plural(n, "задача потребує уваги", "задачі потребують уваги",
                                    "задач потребують уваги");
  }).catch(()=>{ /* лічильник не має ламати роботу платформи */ });
}

function taskObjHtml(t){
  const k = String(t["Тип"] || (t["Угода"] ? "Угода" : "Дія"));
  const f = TASK_OBJ_FIELD[k];
  const v = f ? String(t[f] || "").trim() : "";
  if (!v) return k === "Дія" ? "дія" : esc(k) + " (не вказано)";
  if (k === "Угода") return "угода №" + esc(v);
  return esc(k) + ": " + esc(v);
}
/* Підпис терміну людською мовою — «прострочено 3 дні», «сьогодні», «через 2 дні» */
function dueHtml(t){
  const d = taskDays(t);
  if (d === null) return '<span class="due">без терміну</span>';
  const when = fmtD(t["Термін"]);
  if (!taskIsOpen(t)) return `<span class="due">${esc(when)}</span>`;
  if (d < 0) return `<span class="due over" title="${esc(when)}">прострочено ${-d} ${plural(-d,"день","дні","днів")}</span>`;
  if (d === 0) return `<span class="due over" title="${esc(when)}">сьогодні</span>`;
  const cls = d <= remindOf(t) ? "due soon" : "due";
  return `<span class="${cls}" title="${esc(when)}">через ${d} ${plural(d,"день","дні","днів")} · ${esc(when)}</span>`;
}
function taskRowHtml(t, users){
  const names = doerNames(t, users);
  const prio = String(t["Пріоритет"] || "");
  const done = !taskIsOpen(t);
  return `<div class="taskrow${done?" taskdone":""}" data-task="${t.Id}">
    ${canTask() && !done ? `<button class="tk-mark" data-done="${t.Id}" title="Позначити виконаною">✓</button>` : ""}
    <span class="tk"><b>${esc(t["Задача"] || "(без назви)")}</b>
      <small>${taskObjHtml(t)}${names.length ? " · " + esc(names.join(", ")) : " · виконавця немає"}${
        t["Коментар"] ? " · " + esc(String(t["Коментар"]).slice(0,70)) : ""}</small></span>
    <span class="side">${dueHtml(t)}
      ${prio && prio !== "Звичайно" ? `<span class="pill ${PRIO_PILL[prio]||"t-neutral"}">${esc(prio)}</span>` : ""}
      <span class="pill ${TASK_PILL[t["Статус"]]||"t-neutral"}">${esc(t["Статус"] || "Нова")}</span></span>
  </div>`;
}

PAGES.tasks = async () => {
  let rows, users = [];
  try { rows = await taskRows(true); }
  catch(e){
    $("content").innerHTML = `<div class="note">⚠ Не вдалося завантажити задачі (${esc(e.message)}). Онови сторінку.</div>`;
    return;
  }
  try { users = await taskUsers(); }
  catch(e){
    sysWarn("Довідник співробітників не завантажився (" + (e.message || "збій зв'язку") +
            "). Виконавці показані поштою, а не іменами, і призначити нового не вийде.");
  }

  /* Не адміністратор бачить ТІЛЬКИ свої — незалежно від того, що лежить у
     фільтрі. Скидаємо тут, а не лише ховаємо кнопку: інакше значення могло б
     лишитись з попереднього входу під іншою роллю. */
  const seeAll = canSeeAllTasks();
  if (!seeAll){ TASK_FILTER.who = "mine"; TASK_FILTER.roles = []; }

  /* Роль задачі — це роль її ВИКОНАВЦІВ; якщо виконавців немає, беремо роль
     постановника (інакше така задача випадала б з будь-якого відбору по ролях). */
  const roleOf = {};
  users.forEach(u=>{ const em = String(u["Email"]||"").toLowerCase();
                     if (em) roleOf[em] = u["Роль"] || "—"; });
  const taskRoles = t => {
    const rs = doerList(t).map(e=>roleOf[e]).filter(Boolean);
    if (rs.length) return [...new Set(rs)];
    const a = roleOf[String(t["Постановник"]||"").toLowerCase()];
    return a ? [a] : [];
  };
  const roleNames = seeAll
    ? [...new Set(rows.flatMap(taskRoles))].sort((a,b)=>a.localeCompare(b,"uk"))
    : [];

  const mine = rows.filter(isMyTask);
  const view = (TASK_FILTER.who === "mine" ? mine : rows)
    .filter(t=>!TASK_FILTER.kind || String(t["Тип"]||"") === TASK_FILTER.kind)
    .filter(t=>!TASK_FILTER.roles.length || taskRoles(t).some(r=>TASK_FILTER.roles.includes(r)));
  const open = view.filter(taskIsOpen);
  const closed = view.filter(t=>!taskIsOpen(t));

  const days = t => taskDays(t);
  const G = {
    over:  open.filter(t=>days(t) !== null && days(t) < 0),
    today: open.filter(t=>days(t) === 0),
    week:  open.filter(t=>{ const d=days(t); return d !== null && d > 0 && d <= 7; }),
    later: open.filter(t=>{ const d=days(t); return d !== null && d > 7; }),
    none:  open.filter(t=>days(t) === null),
  };
  const byPrio = (a,b)=> TASK_PRIO.indexOf(a["Пріоритет"]||"Звичайно") - TASK_PRIO.indexOf(b["Пріоритет"]||"Звичайно");
  const byDue  = (a,b)=> String(a["Термін"]||"9999").localeCompare(String(b["Термін"]||"9999")) || byPrio(a,b);
  Object.values(G).forEach(g=>g.sort(byDue));
  closed.sort((a,b)=>String(b["Виконано"]||b["UpdatedAt"]||"").localeCompare(String(a["Виконано"]||a["UpdatedAt"]||"")));

  const block = (title, sub, list, cls) => list.length ? `
    <div class="card" style="margin-top:12px">
      <h3>${title} <span style="color:var(--muted);font-weight:500">${list.length}</span></h3>
      <p class="sub">${sub}</p>
      <div class="tasklist ${cls||""}">${list.map(t=>taskRowHtml(t, users)).join("")}</div>
    </div>` : "";

  $("page-actions").innerHTML = `
    ${canTask() ? '<button class="btn" id="task-new">➕ Нова задача</button>' : ""}
    <span class="alertbar">
      <span class="abadge ${G.over.length?"a-red":""}">прострочені <b>${G.over.length}</b></span>
      <span class="abadge ${G.today.length?"a-amber":""}">на сьогодні <b>${G.today.length}</b></span>
      <span class="abadge">на тиждень <b>${G.week.length}</b></span>
    </span>`;
  if ($("task-new")) $("task-new").addEventListener("click", ()=>openTask(null, {}));

  const chip = (on, key, val, label) =>
    `<button class="doerchip${on?" sel":""}" data-f="${key}" data-v="${esc(val)}">${esc(label)}</button>`;
  $("content").innerHTML = `
    <div class="card">
      <p class="sub">задачі по угодах, клієнтах, співробітниках і просто дії ·
        нагадування показуються тут і лічильником у меню${
        seeAll ? " · ти бачиш задачі всіх" : " · ти бачиш свої задачі — ті, де ти виконавець або які ти поставила"}</p>
      <div style="display:flex;gap:7px;flex-wrap:wrap;margin-top:10px">
        ${chip(TASK_FILTER.who==="mine","who","mine","👤 Мої (" + mine.filter(taskIsOpen).length + ")")}
        ${seeAll ? chip(TASK_FILTER.who==="all","who","all","Усі (" + rows.filter(taskIsOpen).length + ")") : ""}
        <span style="width:10px"></span>
        ${chip(!TASK_FILTER.kind,"kind","","Будь-який тип")}
        ${TASK_KINDS.map(k=>chip(TASK_FILTER.kind===k,"kind",k,k)).join("")}
        <span style="width:10px"></span>
        ${chip(TASK_FILTER.closed,"closed","1","✅ Показати закриті (" + closed.length + ")")}
      </div>
      ${seeAll && roleNames.length ? `
      <div style="margin-top:12px">
        <div style="font-size:11.5px;color:var(--muted);font-weight:600;margin-bottom:6px">
          Чиї задачі показувати — за роллю виконавця</div>
        <div style="display:flex;gap:7px;flex-wrap:wrap">
          ${chip(!TASK_FILTER.roles.length,"role","","Усі ролі")}
          ${roleNames.map(r=>chip(TASK_FILTER.roles.includes(r),"role",r,
              r + " (" + rows.filter(t=>taskIsOpen(t) && taskRoles(t).includes(r)).length + ")")).join("")}
        </div>
      </div>` : ""}
    </div>
    ${block("🔴 Прострочені","термін минув, задача не закрита",G.over)}
    ${block("🔔 На сьогодні","термін — сьогодні",G.today)}
    ${block("📅 Найближчі 7 днів","",G.week)}
    ${block("🗓 Пізніше","",G.later)}
    ${block("Без терміну","термін не поставлений — нагадування по них не працює",G.none)}
    ${TASK_FILTER.closed ? block("✅ Закриті","виконані та скасовані",closed) : ""}
    ${open.length ? "" : '<div class="card" style="margin-top:12px"><p class="sub">Відкритих задач немає.' +
      (canTask() ? " Натисни «Нова задача», щоб поставити першу." : "") + '</p></div>'}`;

  $("content").querySelectorAll(".doerchip[data-f]").forEach(b=>b.addEventListener("click", ()=>{
    const f = b.dataset.f, v = b.dataset.v;
    if (f === "closed") TASK_FILTER.closed = !TASK_FILTER.closed;
    else if (f === "role"){
      // ролі вибираються КІЛЬКА (можна дивитись і сейлзів, і операційних разом);
      // порожній вибір = усі ролі
      if (!v) TASK_FILTER.roles = [];
      else TASK_FILTER.roles = TASK_FILTER.roles.includes(v)
        ? TASK_FILTER.roles.filter(x=>x !== v)
        : TASK_FILTER.roles.concat(v);
    }
    else TASK_FILTER[f] = v;
    PAGES.tasks();
  }));
  $("content").querySelectorAll(".taskrow[data-task]").forEach(el=>el.addEventListener("click", e=>{
    if (e.target.closest("[data-done]")) return;          // галочку обробляє свій обробник
    const t = rows.find(x=>String(x.Id) === el.dataset.task);
    if (t) openTask(t, {});
  }));
  $("content").querySelectorAll("[data-done]").forEach(b=>b.addEventListener("click", async ()=>{
    const t = rows.find(x=>String(x.Id) === b.dataset.done);
    if (!t) return;
    b.disabled = true; b.textContent = "…";
    try{ await saveTask({Id: t.Id, "Статус": "Виконано", "Виконано": todayISO()}, t, "закрито задачу");
         toast("✅ Задачу виконано"); PAGES.tasks(); }
    catch(err){ b.disabled = false; b.textContent = "✓"; toast("⚠ Не збереглось: " + err.message); }
  }));
};

/* Запис задачі. Один шлях для створення і для зміни, щоб позначка «Виконано»
   і журнал дій не розповзалися по трьох місцях. */
async function saveTask(body, before, what){
  const isNew = !body.Id;
  await api(`/api/v2/tables/${T["Задачі"]}/records`, {
    method: isNew ? "POST" : "PATCH", body: JSON.stringify([body])});
  TASKS_CACHE = null;
  logAction(what || (isNew ? "створено задачу" : "зміна задачі"),
            body["Задача"] || (before && before["Задача"]) || ("№" + body.Id),
            "Статус", before ? before["Статус"] : "", body["Статус"] || "");
  refreshTaskBadge();
  // якщо на екрані таблиця угод — червоне число задач оновлюється одразу
  if (typeof DISP_TASKS_REFRESH === "function" && $("drows")) DISP_TASKS_REFRESH();
}

/* Картка задачі: створення і редагування. preset — коли ставимо задачу з картки
   угоди («по цій угоді»): тоді тип і об'єкт уже заповнені. */
async function openTask(t, preset){
  const isNew = !t;
  t = t || {};
  preset = preset || {};
  let users = [];
  try { users = await taskUsers(); } catch(e){ users = []; }

  const kind0 = String(preset["Тип"] || t["Тип"] || (t["Угода"] ? "Угода" : "Дія"));
  const sel = new Set(isNew ? (myEmail() ? [myEmail()] : []) : doerList(t));

  $("task-title").textContent = isNew ? "Нова задача" : "Задача";
  $("task-hint").textContent  = isNew
    ? "по угоді, по клієнту, по співробітнику або просто дія"
    : "постановник: " + (t["Постановник"] || "—") +
      (t["CreatedAt"] ? " · створена " + fmtD(t["CreatedAt"]) : "");
  $("task-msg").textContent = "";
  $("task-body").innerHTML = `
    <div class="fld"><label for="tk-name">Що зробити</label>
      <input id="tk-name" type="text" maxlength="255" value="${esc(t["Задача"]||"")}" placeholder="напр. надіслати драфт коносамента"></div>
    <div class="fldrow">
      <div class="fld"><label for="tk-kind">Тип задачі</label>
        <select id="tk-kind">${TASK_KINDS.map(k=>`<option${k===kind0?" selected":""}>${esc(k)}</option>`).join("")}</select></div>
      <div class="fld" id="tk-obj-wrap"></div>
    </div>
    <div class="fld"><label>Виконавці</label>
      <div id="tk-doers" style="display:flex;gap:7px;flex-wrap:wrap">${
        users.length ? users.map(u=>{ const em = String(u["Email"]||"").toLowerCase();
          return `<button type="button" class="doerchip${sel.has(em)?" sel":""}" data-em="${esc(em)}">${esc(userLabel(u))}</button>`;
        }).join("") : '<span class="sub">Довідник співробітників не завантажився — призначити нікого не вийде.</span>'}</div></div>
    <div class="fldrow">
      <div class="fld"><label for="tk-due">Термін</label>
        <input id="tk-due" type="date" value="${esc(String(t["Термін"]||"").slice(0,10))}"></div>
      <div class="fld"><label for="tk-remind">Нагадати за (днів до терміну)</label>
        <input id="tk-remind" type="number" min="0" max="60" value="${isNew?1:remindOf(t)}"></div>
    </div>
    <div class="fldrow">
      <div class="fld"><label for="tk-prio">Пріоритет</label>
        <select id="tk-prio">${TASK_PRIO.map(p=>`<option${p===(t["Пріоритет"]||"Звичайно")?" selected":""}>${esc(p)}</option>`).join("")}</select></div>
      <div class="fld"><label for="tk-state">Статус</label>
        <select id="tk-state">${TASK_STATES.map(s=>`<option${s===(t["Статус"]||"Нова")?" selected":""}>${esc(s)}</option>`).join("")}</select></div>
    </div>
    <div class="fld"><label for="tk-note">Коментар</label>
      <textarea id="tk-note" maxlength="2000">${esc(t["Коментар"]||"")}</textarea></div>`;

  /* Поле об'єкта залежить від типу: угода — номер зі списку наявних, клієнт —
     назва з довідника, співробітник — вибір людини, «Дія» — поля немає. */
  const drawObj = async () => {
    const kind = $("tk-kind").value;
    const wrap = $("tk-obj-wrap");
    const cur = String(preset[TASK_OBJ_FIELD[kind]] || t[TASK_OBJ_FIELD[kind]] || "");
    if (kind === "Дія"){
      wrap.innerHTML = '<label>&nbsp;</label><span class="sub">задача ні до чого не прив’язана</span>';
      return;
    }
    if (kind === "Співробітник"){
      wrap.innerHTML = `<label for="tk-obj">Про кого задача</label>
        <select id="tk-obj"><option value=""></option>${users.map(u=>{
          const n = userLabel(u);
          return `<option${n===cur?" selected":""}>${esc(n)}</option>`;
        }).join("")}</select>`;
      return;
    }
    /* Поруч із номером угоди — живе посилання на її картку (прохання
       користувачки 25.08.2026). Ховається, поки в полі номер, якого немає в
       таблиці, — щоб не вести «в нікуди». */
    wrap.innerHTML = `<label for="tk-obj">${kind === "Угода"
        ? 'Номер угоди <a href="#" id="tk-goto" style="display:none;margin-left:8px;font-weight:600">відкрити угоду ↗</a>'
        : "Клієнт"}</label>
      <input id="tk-obj" type="text" list="tk-obj-list" value="${esc(cur)}" placeholder="${
        kind === "Угода" ? "напр. 259" : "назва з довідника"}">
      <datalist id="tk-obj-list"></datalist>`;
    /* Підказки тягнемо ліниво: списку угод і клієнтів на сторінці задач ще немає,
       а вантажити їх «про всяк випадок» при кожному відкритті — марно. */
    try{
      const dl = $("tk-obj-list");
      if (!dl) return;
      const vals = kind === "Угода"
        ? [...new Set((await dispRows()).map(r=>String(r["Угода"]||"").trim()).filter(Boolean))]
            .sort((a,b)=>Number(b) - Number(a) || a.localeCompare(b))
        : [...new Set((await loadAll(T["Клієнти"])).map(c=>String(c["Назва"]||"").trim()).filter(Boolean))].sort();
      dl.innerHTML = vals.map(v=>`<option value="${esc(v)}"></option>`).join("");
    }catch(e){ /* підказки не критичні — поле лишається вільним для вводу */ }
    if (kind === "Угода"){
      try{
        const rowsAll = await dispRows();          // кешовано — другий виклик безкоштовний
        const goto = $("tk-goto"), inp = $("tk-obj");
        if (!goto || !inp) return;
        const found = () => rowsAll.find(r => String(r["Угода"]||"").trim() === inp.value.trim());
        const upd = () => { goto.style.display = found() ? "" : "none"; };
        inp.addEventListener("input", upd);
        upd();
        goto.addEventListener("click", e => {
          e.preventDefault(); e.stopPropagation();
          const r = found();
          if (!r) return;
          /* Картку задачі закриваємо: показати картку угоди ПОВЕРХ задачі не
             вийде — обидві накладки мають однаковий z-index, і задача, стоячи
             пізніше в розмітці, лишилась би зверху. Незбережені правки задачі
             при цьому пропадають, як і при будь-якому закритті картки. */
          $("task-overlay").classList.remove("open");
          openRow(r);
        });
      }catch(e){ /* без посилання поле працює як раніше */ }
    }
  };
  await drawObj();
  $("tk-kind").addEventListener("change", drawObj);
  $("tk-doers").querySelectorAll("[data-em]").forEach(b=>b.addEventListener("click", ()=>{
    const em = b.dataset.em;
    if (sel.has(em)) sel.delete(em); else sel.add(em);
    b.classList.toggle("sel", sel.has(em));
  }));

  const save = $("task-save");
  save.disabled = !canTask();
  save.onclick = async () => {
    const name = $("tk-name").value.trim();
    if (!name){ $("task-msg").textContent = "⚠ Напиши, що саме зробити."; return; }
    const kind = $("tk-kind").value;
    const objEl = $("tk-obj");
    const obj = objEl ? String(objEl.value || "").trim() : "";
    if (kind !== "Дія" && !obj){
      $("task-msg").textContent = "⚠ Вкажи, до чого задача (" +
        (kind === "Угода" ? "номер угоди" : kind === "Клієнт" ? "клієнта" : "співробітника") +
        "), або постав тип «Дія».";
      return;
    }
    const state = $("tk-state").value;
    const body = {
      "Задача": name,
      "Тип": kind,
      "Угода": kind === "Угода" ? obj : (isNew ? "" : (t["Угода"] || "")),
      "Клієнт": kind === "Клієнт" ? obj : (isNew ? "" : (t["Клієнт"] || "")),
      "Співробітник": kind === "Співробітник" ? obj : (isNew ? "" : (t["Співробітник"] || "")),
      "Виконавці": [...sel].join(", "),
      "Термін": $("tk-due").value || null,
      "Нагадати за": Number($("tk-remind").value) || 0,
      "Пріоритет": $("tk-prio").value,
      "Статус": state,
      "Коментар": $("tk-note").value.trim(),
    };
    /* Дата закриття ставиться разом зі статусом і знімається, якщо задачу
       повернули в роботу — інакше в картці лишалась би дата «виконано» у
       відкритої задачі. */
    if (TASK_OPEN.includes(state)) body["Виконано"] = null;
    else if (!t["Виконано"]) body["Виконано"] = todayISO();
    if (isNew) body["Постановник"] = myEmail();
    else body.Id = t.Id;

    save.disabled = true; $("task-msg").textContent = "⏳ Зберігаю…";
    try{
      await saveTask(body, isNew ? null : t, isNew ? "створено задачу" : "зміна задачі");
      $("task-overlay").classList.remove("open");
      toast(isNew ? "✅ Задачу створено" : "✅ Задачу збережено");
      if (CUR === "tasks") PAGES.tasks();
      else if (CUR === "dashboard") PAGES.dashboard();
    }catch(e){ $("task-msg").textContent = "⚠ Не вдалося зберегти: " + e.message; }
    save.disabled = false;
  };
  $("task-overlay").classList.add("open");
}

let INSTR_CACHE = null;
/* Кабінети клієнтів — окремий розділ меню (вимога користувачки 24.08.2026:
   «треба винести на окрему вкладку»). Раніше це була картка в «Налаштуваннях»,
   і бачив її лише адміністратор.
   Хто що бачить, вирішує СЕРВЕР кабінету (erp_scope у server/cabinet.py):
   адміністратор — усі компанії, сейлз-менеджер — лише ті, де він менеджер,
   фінансист і бухгалтер — нічого. Тут ми лише малюємо те, що він віддав, і не
   дублюємо правило вдруге: одне місце правди краще за два, які розійдуться. */
PAGES.cabinets = async () => {
  $("content").innerHTML = `
    <div class="card"><h3>🔑 Кабінети клієнтів</h3>
      <p class="sub">відкрити кабінет очима клієнта і видати доступ</p>
      <div class="tablewrap scrollbox" style="max-height:340px;margin-top:10px"><table>
        <thead><tr><th>Компанія</th><th>Угод</th><th>Доступи</th><th></th></tr></thead>
        <tbody id="cc-rows"></tbody></table></div>
      <h4 style="margin:16px 0 6px;font-size:13.5px">Люди з доступом</h4>
      <div class="tablewrap scrollbox" style="max-height:340px"><table>
        <thead><tr><th>Пошта</th><th>Компанія</th><th>Стан</th><th>Останній вхід</th><th></th></tr></thead>
        <tbody id="ca-rows"></tbody></table></div>
      <p class="sub" id="cc-note" style="margin-top:8px">завантажую…</p>
      <div class="note">🔒 Перегляд кабінету записується в журнал. Клієнт вашого перегляду не бачить.
        Посилання на пароль діє 72 години й спрацьовує один раз — передайте його клієнту напряму.</div></div>`;
  await renderCabinets();
};

PAGES.instr = async () => {
  const arts = INSTR_CACHE || (INSTR_CACHE = await loadAll(T["Інструкції"]));
  const cats = {};
  arts.forEach(a=>{ const c=a["Категорія"]||"Інше"; (cats[c]=cats[c]||[]).push(a); });
  $("content").innerHTML = Object.keys(cats).map(c=>`
    <div class="card"><h3>📚 ${esc(c)}</h3>
      <div style="display:flex;flex-direction:column;gap:8px;margin-top:8px">
        ${cats[c].map(a=>`<button class="acct-chip" data-art="${a.Id}" style="flex:none;text-align:left">
          <b>${esc(a["Іконка"]||"📄")} ${esc(a["Назва"])}</b></button>`).join("")}
      </div></div>`).join("") +
    '<div class="note">💡 Статті перенесені з Notion. Оновлення статей — поки в Notion, скажи Клоду «онови інструкції» після змін.</div>';
  document.querySelectorAll("[data-art]").forEach(b=>b.addEventListener("click",()=>{
    const a = arts.find(x=>String(x.Id)===b.dataset.art);
    $("content").innerHTML = `
      <div class="card">
        <button class="btn ghost" id="back-instr">← До списку</button>
        <h3 style="margin-top:14px;font-size:16px;text-transform:none;letter-spacing:0">${esc(a["Іконка"]||"")} ${esc(a["Назва"])}</h3>
        <div class="article">${safeHtml(a["Зміст"])}</div>
        ${safeLink(a["Джерело"])?`<p class="sub" style="margin-top:14px"><a href="${esc(safeLink(a["Джерело"]))}" target="_blank" rel="noopener noreferrer">Джерело в Notion ↗</a></p>`:""}
      </div>`;
    $("back-instr").addEventListener("click",()=>go("instr"));
    window.scrollTo(0,0);
  }));
};

PAGES.users = async () => {
  const isAdmin = ROLE === "Адміністратор";
  /* Журнал роботи автоматики — адміністратору і фінансовим ролям (вимога
     користувачки 11.08.2026). Той самий перелік, що в server/authcheck.py
     (FIN_ROLES), бо дані йдуть через /finrep-data, а він пускає рівно цих трьох:
     чужому роль на сервері все одно поверне 403, тут ми лише не малюємо картку,
     яку людина однаково не змогла б прочитати. */
  const isFin = ["Адміністратор", "Фінансист", "Бухгалтер"].includes(ROLE);
  const rows = isAdmin ? await loadAll(T["Користувачі"]) : [];
  const UED = isAdmin ? " ed" : "";
  $("content").innerHTML = `
    <div class="card"><h3>🎨 Кольорова гама</h3>
      <p class="sub">вибір зберігається у твоєму браузері й не впливає на інших</p>
      <div id="pal-page" style="display:flex;gap:10px;margin-top:10px"></div>
      <p class="sub" id="pal-page-name" style="margin-top:8px"></p></div>

    <div class="card"><h3>🔑 Зміна пароля</h3>
      <p class="sub">пароль від входу в платформу</p>
      <div class="filters" style="margin:10px 0 0;max-width:560px">
        <input id="pw-old" type="password" placeholder="поточний пароль" autocomplete="current-password">
        <input id="pw-new" type="text" placeholder="новий пароль" autocomplete="new-password">
        <input id="pw-new2" type="password" placeholder="ще раз новий" autocomplete="new-password">
        <button class="btn ghost" id="pw-gen" type="button" title="згенерувати надійний пароль">🎲 Згенерувати</button>
      </div>
      <div class="pwbox" id="pw-hint"></div>
      <button class="btn" id="pw-save" style="margin-top:10px">Змінити пароль</button>
      <p class="sub" id="pw-msg" style="margin-top:8px"></p></div>

    ${isAdmin ? `<div class="card"><h3>👥 Користувачі</h3>
      <p class="sub">роль визначає, що людина бачить у платформі${isAdmin
        ? ' · <b>клік по значенню</b> — змінити, <b>Enter</b> — зберегти, <b>Esc</b> — скасувати' : ""}</p>
      <div class="tablewrap"><table>
        <thead><tr><th>Ім'я</th><th>Прізвище</th><th>Email</th><th>Роль</th><th>Доступ</th><th>Пароль</th></tr></thead>
        <tbody id="us-rows">${rows.map(u=>`<tr data-uid="${u.Id}">
          <td class="${UED.trim()}" data-uf="Ім'я"><b>${esc(u["Ім'я"]||"—")}</b></td>
          <td class="${UED.trim()}" data-uf="Прізвище">${esc(u["Прізвище"]||"—")}</td>
          <td class="mono">${esc(u["Email"]||"—")}</td>
          <td class="${UED.trim()}" data-uf="Роль"><span class="role-badge">${esc(u["Роль"]||"—")}</span></td>
          <td class="${UED.trim()}" data-uf="Активний">${u["Активний"]===false
            ? '<span class="pill t-crit">заблоковано</span>' : '<span class="pill t-good">активний</span>'}</td>
          <td><button class="btn ghost" data-pwuser="${esc(u["Email"]||"")}"
              style="padding:3px 9px;font-size:12px">🔑 Задати</button></td>
        </tr>`).join("")}</tbody>
      </table></div>
      <p class="sub" style="margin-top:8px">Щоб заблокувати людину — клікни «активний». Заблокований у платформу не заходить взагалі.</p>

      <h3 style="margin-top:18px">➕ Додати користувача</h3>
      <p class="sub">створює і акаунт для входу, і рядок у цьому довіднику</p>
      <div class="filters" style="margin:10px 0 0;max-width:820px">
        <input id="nu-email" placeholder="email (він же логін)" autocomplete="off">
        <input id="nu-first" placeholder="ім'я">
        <input id="nu-last" placeholder="прізвище">
        <!-- Список ролей береться з RC, а НЕ переписується руками. Було: тут стояв
             власний перелік із «Менеджер» і «Оп. менеджер» — таких ролей немає ні в
             RC, ні в колонці «Роль» довідника (там SingleSelect із семи назв:
             Адміністратор, Сейлз-менеджер, Бухгалтер, Фінансист, Операційний
             менеджер, Логіст, Перегляд). Тобто створений через цю форму менеджер
             отримував роль, якої не існує, а cfg() мовчки опускав його до
             «Перегляд» — усе видно, нічого не змінити, і жодного попередження.
             Тепер джерело назв одне, і розійтися вони більше не можуть.
             Той самий Object.keys(RC) уже використовує редактор ролі в таблиці
             вище (ROLE_LIST) — саме тому там назви були правильні, а тут ні. -->
        <select id="nu-role">${Object.keys(RC)
          .map(r=>`<option>${esc(r)}</option>`).join("")}</select>
        <input id="nu-pw" type="text" placeholder="пароль" autocomplete="new-password">
        <button class="btn ghost" id="nu-gen" type="button">🎲 Згенерувати</button>
      </div>
      <div class="pwbox" id="nu-hint"></div>
      <button class="btn" id="nu-save" style="margin-top:10px">Створити користувача</button>
      <p class="sub" id="nu-msg" style="margin-top:8px"></p>
    </div>` : ""}
    ${isAdmin ? `<div class="card"><h3>Ролі (довідка)</h3>
      <div class="tablewrap"><table><tbody>
        <tr><td><b>Адміністратор</b></td><td>повний доступ до всього</td></tr>
        <tr><td><b>Сейлз-менеджер</b></td><td>свої угоди і клієнти, свій фінзвіт, документи по своїх угодах</td></tr>
        <tr><td><b>Бухгалтер</b></td><td>всі угоди, виставлення рахунків, бухгалтерський фінзвіт</td></tr>
        <tr><td><b>Фінансист</b></td><td>як бухгалтер + всі фінансові дані компанії</td></tr>
        <tr><td><b>Операційний менеджер</b></td><td>свої угоди (де він оп. менеджер), всі дані перевезення, документи</td></tr>
        <tr><td><b>Логіст</b></td><td>диспетчеризація: авто, водій, статус, пункт перетину</td></tr>
        <tr><td><b>Перегляд</b></td><td>тільки перегляд, фінансові цифри приховані</td></tr>
      </tbody></table></div></div>` : ""}
    <!-- Довідка ролей — тільки адміністратору (вказівка користувачки 11.08.2026).
         Раніше цю картку бачили всі: кожен співробітник читав перелік чужих
         рівнів доступу, хоча керує ролями тільки адміністратор. -->
    ${isAdmin ? `<div class="card"><h3>🗂 Журнал подій</h3>
      <p class="sub">хто заходив і що змінював — за часом, від найсвіжішого</p>
      <div class="filters" style="margin:10px 0 0">
        <select id="lg-user"><option value="">Усі користувачі</option></select>
        <select id="lg-act"><option value="">Усі дії</option></select>
        <input id="lg-q" placeholder="пошук: угода, поле, значення…">
      </div>
      <div class="tablewrap scrollbox" style="max-height:420px"><table>
        <thead><tr><th>Час</th><th>Користувач</th><th>Роль</th><th>Дія</th><th>Обʼєкт</th><th>Поле</th><th>Було</th><th>Стало</th></tr></thead>
        <tbody id="lg-rows"></tbody></table></div>
      <p class="sub" id="lg-note" style="margin-top:8px"></p>
      <div class="note">🔒 Журнал доступний лише адміністратору й нічого в ньому змінити не можна — він фіксує все.</div></div>` : ""}
    ${isAdmin ? `<div class="card"><h3>👤 Журнал кабінету клієнтів</h3>
      <p class="sub">хто з клієнтів заходив, що дивився і що завантажував — від найсвіжішого</p>
      <div class="filters" style="margin:10px 0 0">
        <select id="cl-client"><option value="">Усі компанії</option></select>
        <select id="cl-act"><option value="">Усі дії</option></select>
        <input id="cl-q" placeholder="пошук: пошта, угода, деталі…">
      </div>
      <div class="tablewrap scrollbox" style="max-height:420px"><table>
        <thead><tr><th>Час</th><th>Компанія</th><th>Користувач</th><th>Дія</th><th>Деталі</th><th>IP</th></tr></thead>
        <tbody id="cl-rows"></tbody></table></div>
      <p class="sub" id="cl-note" style="margin-top:8px">завантажую…</p>
      <div class="note">🔒 Цей журнал пише СЕРВЕР кабінету, а не браузер — підробити його не можна. Клієнти його не бачать.</div></div>` : ""}
    ${isFin ? `<div class="card"><h3>⚙️ Журнал роботи автоматики</h3>
      <p class="sub">що робив конвеєр даних: коли тягнув з Експедитора, що вийшло, де впало</p>
      <div class="filters" style="margin:10px 0 0">
        <select id="pj-status">
          <option value="">Усі записи</option>
          <option value="bad">Тільки проблеми</option>
        </select>
        <input id="pj-q" placeholder="пошук: крок, файл, текст помилки…">
      </div>
      <div class="tablewrap scrollbox" style="max-height:420px"><table>
        <thead><tr><th>Час</th><th>Крок</th><th>Стан</th><th>Деталі</th></tr></thead>
        <tbody id="pj-rows"></tbody></table></div>
      <p class="sub" id="pj-note" style="margin-top:8px">завантажую…</p></div>` : ""}
    ${isAdmin ? `<div class="card"><h3>🔐 Інші налаштування</h3>
      <p class="sub">тут зʼявляться доступи клієнтів до кабінету, сповіщення й довідники</p>
      <div class="note">🛠 Розділ наповнюється. Скажи, що винести сюди першим.</div></div>` : ""}`;
  bindPalette();
  bindPasswordChange();
  if (isFin) renderPipelineJournal();
  if (isAdmin){ renderAudit(); renderCabinetLog(); bindUserEdit(rows); bindUserAdmin(rows); }
};

/* ===== старт ===== */
const LOGO_SRC = "data:image/png;base64,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";
document.querySelectorAll("#logo-login, #logo-side").forEach(el=>el.src=LOGO_SRC);
renderPals();
if (JWT) enter();

/* ── віддаємо назовні рівно те, що потрібне ПЕРЕВІРКАМ ─────────────────────
   У модулі імена не глобальні, а scripts/smoke.js, cols.js, stale.js і tasks.js
   заходять у сторінку і викликають enter() та go() напряму — інакше меню не
   збудується і перевіряти буде нічого. Тому ці двоє (і тільки вони) явно
   кладуться на window. Це не «на всяк випадок», а свідомий гачок для перевірок:
   якщо його прибрати, увесь шлюз check_facade.sh осліпне. */
window.enter = enter;
window.go = go;
