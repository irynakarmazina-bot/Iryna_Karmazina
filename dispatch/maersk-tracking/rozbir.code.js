const metas=$('Відбір Maersk').all().map(x=>x.json);
const items=$input.all();
const today=new Date(); today.setHours(0,0,0,0); const T=today.toISOString().slice(0,10);
const byDate=a=>a.sort((x,y)=>String(x.eventDateTime).localeCompare(String(y.eventDateTime)));
const results=[];
for(let i=0;i<items.length;i++){
  const meta=metas[i]||{};
  const resp=items[i].json; const body=resp.body!==undefined?resp.body:resp;
  const events=(body&&body.events)?body.events:null;
  if(!events) continue;
  const out={'BL/Booking':meta.bl,'Лінія':'Maersk','Останнє оновлення':T};
  const conts=[...new Set(events.map(e=>e.equipmentReference).filter(Boolean))];
  out['Контейнер (лінія)']=conts.join(', ');
  if(!meta.ourContainer && conts.length) out['Контейнер']=conts[0];
  out['Звірка']='';
  if(meta.ourContainer && conts.length && !conts.includes(meta.ourContainer)) out['Звірка']='За Maersk: '+conts.join(', ');
  const ves=byDate(events.filter(e=>((e.transportCall||{}).modeOfTransport)==='VESSEL'));
  const last=ves.length?ves[ves.length-1]:null;
  const arr=byDate(events.filter(e=>(e.transportEventTypeCode==='ARRI'||e.equipmentEventTypeCode==='ARRI')));
  const lastArr=arr.length?arr[arr.length-1]:null;
  let etaIso='',act=false;
  if(lastArr){ etaIso=String(lastArr.eventDateTime).slice(0,10); act=(lastArr.eventClassifierCode==='ACT'); }
  let days=999; if(etaIso){ const e=new Date(etaIso); e.setHours(0,0,0,0); days=Math.round((e-today)/86400000); }
  if(last && days<=7){ const tc=last.transportCall||{};
    out['Судно']=(tc.vessel||{}).vesselName||'';
    out['Вояж']=tc.carrierVoyageNumber||tc.exportVoyageNumber||tc.importVoyageNumber||''; }
  if(etaIso){
    if(act){ out['ETA порт (факт)']=etaIso; }
    else { out['ETA порт (план)']=etaIso;
      if(meta.etaPlanOld && meta.etaPlanOld!==etaIso){
        out['Зміни ETA (історія)']=(meta.histOld?meta.histOld+'\n':'')+T+': ETA порт: '+meta.etaPlanOld+' → '+etaIso+' (Maersk)';
        out['Остання зміна']=T; } } }
  const all=byDate(events.slice()); const le=all[all.length-1];
  const mode=((le.transportCall||{}).modeOfTransport)||'';
  const c2=le.equipmentEventTypeCode||le.transportEventTypeCode||le.shipmentEventTypeCode||'';
  const isVes=(mode==='VESSEL'||mode==='');
  let st='';
  if(c2==='LOAD') st=isVes?'В морі':(mode==='RAIL'?'Завантажений на потяг':'Завантажений на авто');
  else if(c2==='DEPA') st=isVes?'В морі':(mode==='RAIL'?'Завантажений на потяг':'Завантажений на авто');
  else if(c2==='ARRI') st=(mode==='VESSEL')?'В морі':(mode==='RAIL'?'Прибув в сухій порт':'Доставка отримувачу');
  else if(c2==='DISC') st=(mode==='VESSEL'||!mode)?'Вивантажений в порту прибуття':'Прибув в сухій порт';
  else if(c2==='GTOT') st=(mode==='RAIL')?'Завантажений на потяг':'Завантажений на авто';
  else if(c2==='GTIN') st=(mode==='TRUCK')?'Вантаж доставлено':'Прибув в сухій порт';
  if(st && meta.curStatus!=='Вантаж доставлено') out['Статус']=st;  // «Доставлено» заморожено
  results.push({json:out});
}
return results;
