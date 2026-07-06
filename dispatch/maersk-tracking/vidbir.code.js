// «Відбір Maersk» — які рядки CRM трекати і як (задача 1.2: ключ трекінгу BL/контейнер-fallback).
//
// РІШЕННЯ ПРО МАТЧ-КЛЮЧ ЗАПИСУ (проблема з задачі 1.2): рядки, що трекаються по BL, і рядки,
// що трекаються по контейнеру, мають РІЗНИЙ природний ключ — а appendOrUpdate матчить лише по
// ОДНІЙ колонці. Замість двох гілок запису або нової службової колонки, використовуємо колонку
// «Угода» (кол. A, SHEET-STRUCTURE.md) як ЄДИНИЙ матч-ключ для всіх записів цього воркфлоу:
// вона унікальна для кожного рядка, завжди заповнена (це первинний ключ імпорту з Експедитора)
// і НЕ залежить від того, чим трекаємо рядок цього прогону. Це простіше й надійніше за дві гілки
// запису чи ще одну службову колонку. Див. «Запис у CRM» у workflows/maersk-container-tracking.json
// та коментар на початку rozbir.code.js.
//
// Кожен вихідний item має поле `_route`:
//   'fetch' — потрібен запит до Maersk API (далі йде в «Розбір»), несе метадані рядка;
//   'mark'  — запиту не буде, просто виставляємо «Ключ трекінгу» напряму (готовий об'єкт запису).

const out = [];
for (const it of $input.all()) {
  const r = it.json;
  const uhoda = String(r['Угода'] || '').trim();
  if (!uhoda) continue; // без «Угода» немає надійного ключа для запису — пропускаємо рядок безпечно

  const line = String(r['Лінія'] || '').trim().toLowerCase();
  const bl = String(r['BL/Booking'] || '').trim();
  const ourContainer = String(r['Контейнер'] || '').trim();
  const hasBL = /^\d{9}$/.test(bl);
  const hasContainer = !!ourContainer;
  const oldTrackKey = String(r['Ключ трекінгу'] || '').trim();

  // Рядки інших ліній (явно вказана НЕ Maersk) — поза зоною відповідальності цього воркфлоу.
  // Нічого не пишемо і не чіпаємо — цим рядком має зайнятись MSC/CMA-воркфлоу (1.6/1.7).
  if (line && line !== 'maersk') continue;

  if (line === 'maersk' && hasBL) {
    out.push({ json: {
      _route: 'fetch', trackByType: 'bl', newTrackKeyLabel: 'BL',
      uhoda, bl, ourContainer, line,
      curStatus: String(r['Статус'] || '').trim(),
      curEtaPlan: String(r['ETA порт (план)'] || '').trim(),
      curEtaAct: String(r['ETA порт (факт)'] || '').trim(),
      curVessel: String(r['Судно'] || '').trim(),
      curContainerNow: ourContainer,
      histOld: String(r['Зміни ETA (історія)'] || ''),
      napryamok: String(r['Напрямок'] || '').trim().toLowerCase(),
      // автоперехід (1.2, останній пункт): рядок раніше трекався по контейнеру, тепер з'явився BL
      autoTransition: (oldTrackKey === 'контейнер (тимчасово)')
    }});
    continue;
  }

  if (line === 'maersk' && hasContainer) {
    out.push({ json: {
      _route: 'fetch', trackByType: 'container', newTrackKeyLabel: 'контейнер (тимчасово)',
      uhoda, bl, ourContainer, line,
      curStatus: String(r['Статус'] || '').trim(),
      curEtaPlan: String(r['ETA порт (план)'] || '').trim(),
      curEtaAct: String(r['ETA порт (факт)'] || '').trim(),
      curVessel: String(r['Судно'] || '').trim(),
      curContainerNow: ourContainer,
      histOld: String(r['Зміни ETA (історія)'] || ''),
      napryamok: String(r['Напрямок'] || '').trim().toLowerCase(),
      autoTransition: false
    }});
    continue;
  }

  if (hasContainer) {
    // є контейнер, лінія ще не вказана (могла б бути Maersk, MSC, CMA — невідомо) → просимо вказати
    out.push({ json: { _route: 'mark', 'Угода': uhoda, 'Ключ трекінгу': 'вкажіть лінію' } });
    continue;
  }

  // нема ні BL (валідного, 9 цифр), ні контейнера — трекати нічим
  out.push({ json: { _route: 'mark', 'Угода': uhoda, 'Ключ трекінгу': 'не трекається' } });
}
return out;
