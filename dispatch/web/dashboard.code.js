
const rows=$input.all().map(i=>i.json).filter(r=>(r['BL/Booking']||r['Угода']||r['Лінія']));
const dm=v=>{const m=String(v==null?'':v).match(/(\d{4})-(\d{2})-(\d{2})/);return m?(m[3]+'.'+m[2]+'.'+m[1]):'';};
const esc=s=>String(s==null?'':s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
const isExp=r=>/експорт/i.test(r['Напрямок']||r['Вид']||'');
const dir=r=>{const d=String(r['Напрямок']||r['Вид']||'').trim(); if(!d) return '';
  if(/транзит/i.test(d)) return '<span style="color:#854F0B">Транзит</span>';
  return isExp(r)?'<span style="color:#0C447C">Експорт</span>':'<span style="color:#0F6E56">Імпорт</span>';};
const delivered=r=>String(r['Статус']||'')==='Вантаж доставлено';
const relDate=r=>isExp(r)?(r['ETD (факт)']||r['ETD (план)']||''):(r['ETA порт (факт)']||r['ETA порт (план)']||'');
const delDate=r=>r['Вивантаження у отримувача (факт)']||r['Остання зміна']||'';
const blue=['Стафіровка','Завантажений на потяг','Завантажений на авто','Зданий в порт','Завантажений на судно','В морі'];
const purple=['Вивантажений в порту прибуття','Прибув в сухій порт'];
const pill=s=>{ if(s==='Вантаж доставлено')return['#e6e5df','#5f5e5a']; if(s==='На кордоні')return['#FAEEDA','#854F0B']; if(s==='Доставка отримувачу')return['#E1F5EE','#0F6E56']; if(blue.includes(s))return['#E6F1FB','#0C447C']; if(purple.includes(s))return['#EEEDFE','#3C3489']; return['#F1EFE8','#444441']; };
rows.sort((a,b)=>{ const da=delivered(a),db=delivered(b); if(da!==db) return da?-1:1;
  if(da) return String(delDate(a)||'9999').localeCompare(String(delDate(b)||'9999'));
  return String(relDate(a)||'9999-99-99').localeCompare(String(relDate(b)||'9999-99-99')); });
const total=rows.length, cWay=rows.filter(r=>blue.includes(r['Статус'])).length, cArr=rows.filter(r=>purple.includes(r['Статус'])).length, cDel=rows.filter(delivered).length, cEta=rows.filter(r=>String(r['Зміни ETA (історія)']||'').trim()).length;
function eta(r){ if(delivered(r)) return dm(delDate(r)); return dm(relDate(r))||'—'; }
const pD=v=>{const m=String(v==null?'':v).match(/(\d{4})-(\d{2})-(\d{2})/);return m?new Date(+m[1],+m[2]-1,+m[3]):null;};
// вільні дні демереджу в порту вивантаження за лінією (підтверджені тарифи; Maersk/інші — невідомо)
// порт вивантаження з маршруту
function portOf(r){const s=String(r['Маршрут']||'').toLowerCase();
  if(s.indexOf('constanta')>=0||s.indexOf('констанц')>=0) return 'RO';
  if(s.indexOf('gdynia')>=0||s.indexOf('гдиня')>=0) return 'PL';
  if(s.indexOf('gdansk')>=0||s.indexOf('гдан')>=0) return 'PL';
  return '';}
// коди контейнерів (20DV/40HC/40RF/20OT…) → тарифна категорія
function equipOf(r){const e=String(r['Тип обладнання']||'').toUpperCase();
  if(/RF|RH|REEF|РЕФ/.test(e)) return 'REEFER';
  if(/OT|FR|TK|PW|FLAT|OPEN|TANK|SPEC/.test(e)) return 'SPECIAL';
  return 'DRY';}
function haulOf(r){const h=String(r['Вивіз (Carrier/Merchant)']||r['Вивіз']||'').toUpperCase();
  if(h.indexOf('CARRIER')>=0||h.indexOf('КЕР')>=0||h.indexOf('SD')>=0) return 'C';
  if(h.indexOf('MERCH')>=0||h.indexOf('САМО')>=0||h.indexOf('CY')>=0) return 'M';
  if(String(r['Тип']||'').toLowerCase().indexOf('залізни')>=0) return 'C'; // потяг = завжди carrier haulage
  return '';}
// вільні дні ДЕМЕРЕДЖУ (не storage) — ЛІНІЯ × ПОРТ × ВИВІЗ × ОБЛАДНАННЯ. ⚠ тарифи ще перевірити.
function freeInfo(r){const l=String(r['Лінія']||'').toUpperCase(); const p=portOf(r); const eq=equipOf(r);
  if(l.indexOf('MAERSK')>=0 && p==='PL'){ const h=haulOf(r); if(!h) return {fd:null,need:'вивіз'};
    if(eq==='REEFER') return {fd:4}; if(h==='C') return {fd:eq==='SPECIAL'?7:10}; return {fd:5}; }
  if(l.indexOf('MSC')>=0 && p==='RO') return {fd:18}; // демередж split (storage 5 окремо)
  if(l.indexOf('CMA')>=0 && p==='PL') return {fd:8};  // standard merged
  return {fd:null,need:''};}
function freeDays(r){return freeInfo(r).fd;}
// демередж: від фактичного вивантаження в порту (день 1) до вивозу з порту (постановка/завантаження на ТЗ)
function demRisk(r){ if(delivered(r)) return {html:'',bg:''};
  const a=pD(r['Вивантаження в порту (факт)']); if(!a) return {html:'',bg:''};
  const exit=pD(r['Постановка/завантаження (факт)']);
  const today=new Date(); today.setHours(0,0,0,0);
  const end=exit||today; const day=Math.round((end-a)/86400000)+1; // день 1 = вивантаження
  const fi=freeInfo(r); const fd=fi.fd;
  if(fd==null){ const hint=fi.need==='вивіз'?' · вкажіть вивіз':(exit?'':' · тариф?');
    return {html:'<span style="color:#6b6a64">'+day+'-й д у порту'+(exit?'':hint)+'</span>',bg:''}; }
  const over=day-fd;
  if(exit){ if(over<=0) return {html:'<span style="color:#0F6E56">без демереджу</span>',bg:''};
    return {html:'<span style="color:#854F0B">демередж '+over+' дн</span>',bg:''}; }
  const left=fd-day;
  if(left>=0) return {html:'<span style="color:'+(left<=2?'#854F0B':'#6b6a64')+'">вільних ще '+left+' дн</span>',bg:left<=2?'#FBF4E6':''};
  return {html:'<span style="color:#B42318;font-weight:600">демередж +'+(-left)+' дн</span>',bg:'#FBEAE8'}; }
const cDem=rows.filter(r=>demRisk(r).bg==='#FBEAE8').length;
const etd=r=>dm(r['ETD (факт)']||r['ETD (план)'])||'—';
const td=(v,st)=>'<td style="padding:9px 8px;'+(st||'')+'">'+v+'</td>';
let _fa=true;
const tr=rows.map(r=>{ const p=pill(r['Статус']); const del=delivered(r); const ch=String(r['Зміни ETA (історія)']||'').trim()!==''; const dr=demRisk(r);
  let pre='';
  if(!del && _fa){ _fa=false; pre='<tr id="work-start"><td colspan="17" style="padding:7px 10px;background:#EEF1FB;color:#0C447C;font-weight:600;font-size:12px;border-top:2px solid #0C447C">▼ В роботі &nbsp;·&nbsp; доставлені — вище ▲</td></tr>'; }
  const bg=del?'background:#f5f4ef;':(dr.bg?('background:'+dr.bg+';'):(ch?'background:#FBF4E6;':'')); const tc=del?'color:#8a8981;':'';
  const mono='font-family:ui-monospace,Menlo,monospace;font-size:12px';
  return pre+'<tr style="'+bg+'border-bottom:1px solid #ECEAE1;'+tc+'">'
  +'<td style="padding:9px 8px"><div style="font-weight:500">'+esc(r['Угода']||'—')+'</div><div style="color:#6b6a64;font-size:12px">'+esc(r['Клієнт']||'')+'</div></td>'
  +td(esc(r['Лінія']||''))+td(esc(r['Перевізник']||''),'color:#6b6a64')+td(esc(r['Агент']||''),'color:#6b6a64')+td(dir(r),'font-size:12px')+td(esc(r['Тип']||''),'font-size:12px;color:#6b6a64')
  +td(esc(r['Маршрут']||''))
  +td(esc(r['BL/Booking']||''),mono)+td(esc(r['Контейнер']||''),mono)
  +td(esc(r['Тип обладнання']||''),'font-size:12px')+td(esc(r['Кількість']||''),'font-size:12px;color:#6b6a64')
  +td(dm(r['Гейт ін'])||'—','white-space:nowrap')+td(etd(r),'white-space:nowrap')+td(eta(r),'white-space:nowrap')
  +'<td style="padding:9px 8px"><span style="background:'+p[0]+';color:'+p[1]+';padding:3px 9px;border-radius:999px;font-size:12px;white-space:nowrap">'+esc(r['Статус']||'')+'</span></td>'
  +td(dr.html,'white-space:nowrap')
  +td(esc(r['Коментар внутрішній']||''),'font-size:12px;color:#6b6a64;max-width:220px')
  +'</tr>'; }).join('');
const card=(l,v,w)=>'<div style="flex:1;background:'+(w?'#FAEEDA':'#F1EFE8')+';border-radius:12px;padding:12px 16px"><div style="font-size:13px;color:'+(w?'#854F0B':'#6b6a64')+'">'+l+'</div><div style="font-size:24px;font-weight:500;color:'+(w?'#854F0B':'#2b2b28')+'">'+v+'</div></div>';
const logo='<img src="data:image/png;base64,__LOGO_B64__" alt="UNITEX" style="height:36px;width:auto;display:block">';
const html='<!DOCTYPE html><html lang="uk"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="refresh" content="180"><title>UNITEX — Моніторинг відправлень</title></head>'
+'<body style="margin:0;background:#fff;color:#2b2b28;font-family:-apple-system,Segoe UI,Roboto,Arial,sans-serif">'
+'<div style="max-width:1560px;margin:0 auto;padding:22px 18px">'
+'<div style="display:flex;align-items:center;gap:12px;margin-bottom:18px">'+logo+'<span style="color:#bbb">·</span><span style="color:#6b6a64;font-size:16px">Моніторинг відправлень</span></div>'
+'<div style="display:flex;gap:10px;margin-bottom:20px">'+card('Всього',total)+card('У дорозі / морі',cWay)+card('Прибули в порт',cArr)+card('Доставлено',cDel)+card('Зміни ETA',cEta,true)+card('Демередж-ризик',cDem,cDem>0)+'</div>'
+'<table style="width:100%;border-collapse:collapse;font-size:14px"><thead><tr style="text-align:left;color:#6b6a64;border-bottom:1px solid #d8d6cd">'
+['Відправлення','Лінія','Перевізник','Агент','Напрямок','Тип','Маршрут','BL','Контейнер','Тип обл.','К-ть','Гейт ін','ETD','ETA','Статус','Демередж','Примітки (наші)'].map(h=>'<th style="padding:8px">'+h+'</th>').join('')
+'</tr></thead><tbody>'+tr+'</tbody></table>'
+'<div style="margin-top:12px;color:#9b9a94;font-size:12px">Відкривається з першої угоди в роботі; доставлені (сірим) — вище, прокрутіть угору. Оновлюється авто кожні 3 хв.</div></div>'
+'<script>window.addEventListener("load",function(){var w=document.getElementById("work-start");if(w)w.scrollIntoView({block:"start"});});</script>'
+'</body></html>';
return [{json:{html}}];
