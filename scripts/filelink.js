/* Перевірка: посилання «Відкрити» у вікні документів має вести на /download/…,
   а не на /dltemp/… (той шлях Caddy не знає і віддає сторінку ЕРП). 18.08.2026. */
const path=require("path"), fs=require("fs"), http=require("http");
const { chromium } = require(process.env.PW || "playwright");
const WWW = path.join(__dirname, "..", "www");
const FILE = { path:"download/2026/08/18/abc/Заявка авто Maersk 275820304 18.08.2026_Cjg5r.xlsx",
  signedPath:"dltemp/o_KzO/1787043600000/2026/08/18/abc/Заявка авто.xlsx",
  title:"Заявка авто Maersk 275820304 18.08.2026.xlsx", size:7037, id:"at1" };
const ROW = { Id:1,"Угода":"287","Клієнт":"ГРАНД МАРИН","Напрямок":"Експорт","Лінія":"Maersk",
  "Статус":"В морі","BL":"275820304","Контейнер":"MRSU1","ETA":"2026-09-01","Маршрут":"Гданськ → Фрімантл",
  "Менеджер":"Ірина","Роль":"Адміністратор","Активний":true,"Email":"t@e.com","Ім'я":"Ірина",
  "Файли":[FILE] };
const TABLES=["Диспетчеризація","Користувачі","Клієнти","Задачі","Журнал дій","Калькуляції","Інструкції"];
const META={list:TABLES.map((t,i)=>({id:"t"+(i+1),title:t})),
  columns:[{title:"Статус",uidt:"SingleSelect",colOptions:{options:[{title:"В морі"}]}}]};
const srv=http.createServer((req,res)=>{const n=decodeURIComponent(req.url.split("?")[0]).replace(/^\/+/,"")||"index.html";
  if(n==="sync-state"){res.setHeader("Content-Type","application/json");return res.end(JSON.stringify({running:false,ok:true,result:"",error:"",steps:[]}));}
  fs.readFile(path.join(WWW,n),(e,b)=>{if(e){res.statusCode=404;return res.end("no");}
    res.setHeader("Content-Type",n.endsWith(".js")?"text/javascript":"text/html");res.end(b);});});
(async()=>{
  await new Promise(r=>srv.listen(0,"127.0.0.1",r));
  const url="http://127.0.0.1:"+srv.address().port;
  const browser=await chromium.launch(); const page=await browser.newPage({viewport:{width:1280,height:900}});
  const errs=[]; page.on("pageerror",e=>errs.push(e.message));
  await page.route("**/api/**",route=>{const u=route.request().url();
    if(u.includes("/auth/"))return route.fulfill({status:200,contentType:"application/json",body:JSON.stringify({token:"j"})});
    if(u.includes("/meta/"))return route.fulfill({status:200,contentType:"application/json",body:JSON.stringify(META)});
    return route.fulfill({status:200,contentType:"application/json",body:JSON.stringify({list:[ROW],pageInfo:{isLastPage:true}})});});
  await page.goto(url+"/index.html");
  await page.evaluate(()=>{sessionStorage.setItem("jwt","j");sessionStorage.setItem("email","t@e.com");});
  await page.reload(); await page.waitForTimeout(400);
  await page.evaluate(()=>{if(typeof enter==="function")return enter();});
  await page.waitForTimeout(1200);
  await page.evaluate(()=>{if(typeof go==="function")return go("dispatch");});
  await page.waitForTimeout(800);
  await (await page.$(".docs-btn")).click();
  await page.waitForTimeout(400);
  const href = await page.$eval("#doc-list a", a => a.getAttribute("href"));
  const bad=[];
  if(!href.startsWith("/download/")) bad.push("посилання веде не на /download/, а на "+href.slice(0,40));
  if(/dltemp/.test(href)) bad.push("у посиланні лишився dltemp");
  if(/ /.test(href)) bad.push("пробіли в посиланні не закодовані");
  if(errs.length) bad.push("помилка JS: "+errs[0]);
  console.log("посилання:", href.slice(0,80));
  console.log(bad.length? "FILELINK_FAIL — "+bad.join("; ") : "FILELINK_OK — «Відкрити» веде на /download/, шлях закодований");
  await browser.close(); srv.close(); process.exit(bad.length?1:0);
})();
