
const q=($('Webhook').first().json.query)||{};
const t=String(q.t||'').trim();
const clients=$('ReadClients').all().map(i=>i.json);
let client=''; let invalid=false; let names=[];
if(t){ const cr=clients.find(c=>String(c['Токен']||'').trim()===t);
  if(cr){ client=String(cr['Клієнт']||'').trim();
    names=[client].concat(String(cr['Аліаси']||'').split('|').map(s=>s.trim()).filter(Boolean));
  } else invalid=true; }
const nameSet=names.map(n=>n.toLowerCase());
const all=$('ReadShipments').all().map(i=>i.json).filter(r=>(r['BL/Booking']||r['Угода']||r['Лінія']));
const dm=v=>{const m=String(v==null?'':v).match(/(\d{4})-(\d{2})-(\d{2})/);return m?m[3]+'.'+m[2]:'';};
const esc=s=>String(s==null?'':s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
const isExp=r=>/експорт/i.test(r['Напрямок']||r['Вид']||'');
const yn=v=>{const s=String(v==null?'':v).trim(); if(!s||/^(ні|no|нема|-|—|0|false)$/i.test(s)) return '<span style="color:#c2c0b8">—</span>'; return '<span style="color:#0F6E56;font-weight:600">✓</span>';};
const delivered=r=>String(r['Статус']||'')==='Вантаж доставлено';
const relDate=r=>isExp(r)?(r['ETD (факт)']||r['ETD (план)']||''):(r['ETA порт (факт)']||r['ETA порт (план)']||'');
const delDate=r=>r['Вивантаження у отримувача (факт)']||r['Остання зміна']||'';
// Нова 8-модель статусів (STATUS-MODEL.md, задача 1.3): Букінг, Стафіровка, В порту відправлення,
// Завантажений на судно, В морі, Вивантажений в порту прибуття, Завантажений на авто/потяг,
// Вантаж доставлено. «Букінг» навмисно не в blue/purple — падає у нейтральний колір за замовчуванням.
const blue=['Стафіровка','В порту відправлення','Завантажений на судно','В морі'];
const purple=['Вивантажений в порту прибуття','Завантажений на авто/потяг'];
const pill=s=>{ if(s==='Вантаж доставлено')return['#e6e5df','#5f5e5a']; if(blue.includes(s))return['#E6F1FB','#0C447C']; if(purple.includes(s))return['#EEEDFE','#3C3489']; return['#F1EFE8','#444441']; };
let mine=(client&&!invalid)?all.filter(r=>nameSet.indexOf(String(r['Клієнт']||'').trim().toLowerCase())>=0):[];
mine.sort((a,b)=>{ const da=delivered(a),db=delivered(b); if(da!==db) return da?-1:1;
  if(da) return String(delDate(a)||'9999').localeCompare(String(delDate(b)||'9999'));
  return String(relDate(a)||'9999-99-99').localeCompare(String(relDate(b)||'9999-99-99')); });
const active=mine.filter(r=>!delivered(r)).length;
const inway=mine.filter(r=>!delivered(r)&&(blue.includes(r['Статус'])||purple.includes(r['Статус']))).length;
const done=mine.filter(delivered).length;
function eta(r){ if(delivered(r)) return '<span style="color:#9b9a94">доставлено '+dm(delDate(r))+'</span>';
  const lbl=isExp(r)?'відпр.':'приб.'; const d=dm(relDate(r)); return d?(lbl+' ~'+d):'уточнюється'; }
const etd=r=>dm(r['ETD (факт)']||r['ETD (план)'])||'—';
const mono='font-family:ui-monospace,Menlo,monospace;font-size:12px';
const tr=mine.map(r=>{ const p=pill(r['Статус']); const del=delivered(r);
  const bg=del?'background:#f5f4ef;':''; const tc=del?'color:#8a8981;':'';
  return '<tr style="'+bg+'border-bottom:1px solid #ECEAE1;'+tc+'">'
  +'<td style="padding:11px 8px"><div style="font-weight:500">'+esc(r['Маршрут']||'')+'</div><div style="color:#6b6a64;font-size:12px">Угода '+esc(r['Угода']||'—')+' · '+esc(r['Лінія']||'')+'</div></td>'
  +'<td style="padding:11px 8px;'+mono+'">'+esc(r['BL/Booking']||'')+'</td>'
  +'<td style="padding:11px 8px;'+mono+'">'+esc(r['Контейнер']||'')+'</td>'
  +'<td style="padding:11px 8px;white-space:nowrap">'+etd(r)+'</td>'
  +'<td style="padding:11px 8px;white-space:nowrap">'+eta(r)+'</td>'
  +'<td style="padding:11px 8px"><span style="background:'+p[0]+';color:'+p[1]+';padding:3px 10px;border-radius:999px;font-size:12px;white-space:nowrap">'+esc(r['Статус']||'—')+'</span></td>'
  +'<td style="padding:11px 8px;text-align:center">'+yn(r['Реліз'])+'</td>'
  +'<td style="padding:11px 8px;white-space:nowrap">'+esc(r['Вартість']||'')+'</td>'
  +'<td style="padding:11px 8px;text-align:center">'+yn(r['Оплата'])+'</td>'
  +'<td style="padding:11px 8px;color:#6b6a64;font-size:13px;max-width:260px">'+esc(r['Коментар клієнту']||'')+'</td>'
  +'</tr>'; }).join('');
const stat=(l,v)=>'<div style="flex:1;background:#F1EFE8;border-radius:12px;padding:12px 16px"><div style="font-size:13px;color:#6b6a64">'+l+'</div><div style="font-size:24px;font-weight:500">'+v+'</div></div>';
let inner;
if(invalid){ inner='<div style="color:#854F0B;padding:50px 0;text-align:center">Невірне або застаріле посилання.</div>'; }
else if(!client){ inner='<div style="color:#6b6a64;padding:50px 0;text-align:center">Скористайтесь персональним посиланням, яке надав менеджер Unitex.</div>'; }
else if(mine.length===0){ inner='<div style="color:#6b6a64;padding:50px 0;text-align:center">Наразі активних відправлень немає.</div>'; }
else { inner='<div style="display:flex;gap:10px;margin-bottom:20px">'+stat('Активних',active)+stat('У дорозі',inway)+stat('Доставлено',done)+'</div>'
  +'<table style="width:100%;border-collapse:collapse;font-size:14px"><thead><tr style="text-align:left;color:#6b6a64;border-bottom:1px solid #d8d6cd">'
  +['Маршрут','BL','Контейнер','ETD','ETA','Статус','Реліз','Вартість','Оплата','Коментар'].map(h=>'<th style="padding:8px">'+h+'</th>').join('')
  +'</tr></thead><tbody>'+tr+'</tbody></table>'
  +'<div style="margin-top:12px;color:#b7b5ac;font-size:12px">Оновлюється автоматично. Доставлені — сірим угорі.</div>'; }
const badge=(client&&!invalid)?'<span style="background:#E6F1FB;color:#0C447C;font-size:13px;padding:5px 12px;border-radius:8px">'+esc(client)+'</span>':'';
const logo='<img src="data:image/png;base64,__LOGO_B64__" alt="UNITEX" style="height:30px;width:auto;display:block">';
const html='<!DOCTYPE html><html lang="uk"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="refresh" content="300"><title>UNITEX — відстеження</title></head><body style="margin:0;background:#faf9f6;color:#2b2b28;font-family:-apple-system,Segoe UI,Roboto,Arial,sans-serif"><div style="max-width:1100px;margin:0 auto;padding:24px 18px"><div style="display:flex;align-items:center;justify-content:space-between;border-bottom:1px solid #e2e0d7;padding-bottom:14px;margin-bottom:20px"><div style="display:flex;align-items:center;gap:12px">'+logo+'<span style="color:#bbb">·</span><span style="color:#6b6a64">Відстеження відправлень</span></div>'+badge+'</div>'+inner+'</div></body></html>';
return [{json:{html}}];
