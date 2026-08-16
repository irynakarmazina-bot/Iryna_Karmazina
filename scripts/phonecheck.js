/* Перевірка на майбутнє: на телефоні таблиця диспетчеризації не має бути обрізана.
   Ламалось 16.08.2026: інлайновий max-height від fitDispScroll перебивав мобільне
   правило, і картки нижче 638 px ставали недосяжними прокруткою. */
const path = require("path"), fs = require("fs"), http = require("http");
const { chromium } = require(process.env.PW || "playwright");
const WWW = path.join(__dirname, "..", "www");
const ROW = { Id:1, "Угода":"1", "Клієнт":"Тест", "Напрямок":"Імпорт", "Лінія":"Maersk",
  "Статус":"В морі", "BL":"123", "Контейнер":"MRSU1", "ETA":"2026-09-01",
  "Маршрут":"A → B", "Менеджер":"Ірина", "Роль":"Адміністратор", "Активний":true,
  "Email":"t@e.com", "Ім'я":"Ірина" };
const MIX = [...Array.from({length:25},(_,i)=>({...ROW,Id:100+i,"Угода":String(100+i),"Статус":"Вантаж доставлено","ETA":"2026-0"+(1+i%6)+"-15"})),
             ...Array.from({length:8},(_,i)=>({...ROW,Id:200+i,"Угода":String(200+i),"Статус":"В морі","ETA":"2026-09-"+(10+i)}))];
const TABLES = ["Диспетчеризація","Користувачі","Клієнти","Задачі","Журнал дій","Калькуляції","Інструкції"];
const META = { list: TABLES.map((t,i)=>({id:"t"+(i+1),title:t})),
  columns:[{title:"Статус",uidt:"SingleSelect",colOptions:{options:[{title:"В морі"}]}}] };
const srv = http.createServer((req,res)=>{
  const n = decodeURIComponent(req.url.split("?")[0]).replace(/^\/+/,"") || "index.html";
  if (n === "sync-state") { res.setHeader("Content-Type","application/json");
    return res.end(JSON.stringify({running:false,ok:true,result:"",error:"",steps:[]})); }
  fs.readFile(path.join(WWW,n),(e,b)=>{ if(e){res.statusCode=404;return res.end("no");}
    res.setHeader("Content-Type", n.endsWith(".js")?"text/javascript":"text/html"); res.end(b); });
});
(async () => {
  await new Promise(r=>srv.listen(0,"127.0.0.1",r));
  const url = "http://127.0.0.1:"+srv.address().port;
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport:{width:390,height:844}, isMobile:true, hasTouch:true });
  const errs = []; page.on("pageerror", e=>errs.push(e.message));
  await page.route("**/api/**", route => { const u = route.request().url();
    if (u.includes("/auth/")) return route.fulfill({status:200,contentType:"application/json",body:JSON.stringify({token:"j"})});
    if (u.includes("/meta/")) return route.fulfill({status:200,contentType:"application/json",body:JSON.stringify(META)});
    return route.fulfill({status:200,contentType:"application/json",
      body:JSON.stringify({list:(u.includes("t1")?MIX:[ROW]),pageInfo:{isLastPage:true}})}); });
  await page.goto(url+"/index.html");
  await page.evaluate(()=>{ sessionStorage.setItem("jwt","j"); sessionStorage.setItem("email","t@e.com"); });
  await page.reload(); await page.waitForTimeout(400);
  await page.evaluate(()=>{ if (typeof enter==="function") return enter(); });
  await page.waitForTimeout(1200);
  await page.evaluate(()=>{ if (typeof go==="function") return go("dispatch"); });
  await page.waitForTimeout(900);
  const g = await page.evaluate(()=>{
    const rows=[...document.querySelectorAll("#drows tr")];
    const last=rows[rows.length-1].getBoundingClientRect();
    const box=document.getElementById("dscroll");
    return { rows:rows.length, maxH:getComputedStyle(box).maxHeight,
      lastBottom:Math.round(last.bottom+window.scrollY),
      docH:document.documentElement.scrollHeight, spacer:!!document.getElementById("dscroll-spacer") };
  });
  const bad=[];
  if (g.maxH !== "none") bad.push("рамці задано max-height="+g.maxH+" (на телефоні має бути none)");
  if (g.docH < g.lastBottom - 4) bad.push("сторінка коротша за вміст: "+g.docH+" проти "+g.lastBottom+" — до нижніх карток не прокрутити");
  if (g.spacer) bad.push("на телефоні з'явився порожній добірний блок");
  if (errs.length) bad.push("помилка JS: "+errs[0]);
  console.log("карток: %s | max-height: %s | низ останньої: %s | висота сторінки: %s",
              g.rows, g.maxH, g.lastBottom, g.docH);
  console.log(bad.length ? "PHONE_FAIL — " + bad.join("; ") : "PHONE_OK — на телефоні видно всі картки, таблиця не обрізана");
  await browser.close(); srv.close();
  process.exit(bad.length?1:0);
})();
