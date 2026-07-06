
const out=[];
for(const it of $input.all()){ const r=it.json;
  const bl=String(r['BL/Booking']||'').trim();
  if(!/^\d{9}$/.test(bl)) continue;
  out.push({json:{bl, ourContainer:String(r['Контейнер']||'').trim(),
    etaPlanOld:String(r['ETA порт (план)']||'').trim(), histOld:String(r['Зміни ETA (історія)']||''),
    curStatus:String(r['Статус']||'').trim()}});
}
return out;
