// «Розбір» — приймає лише item'и з _route==='fetch' (IF-вузол «Чи потрібен запит?» відсіяв
// «mark»-рядки раніше). Сам виконує HTTP-запит до Maersk API для КОЖНОГО рядка (замість окремого
// HTTP-вузла) — так простіше й надійніше зробити точний retry/backoff і розрізнити 429/401/404/
// «поганий формат», ніж вбудованим retry n8n-вузла (в нього лише стала пауза, без розрізнення
// типів збоїв). Джерело параметризовано константою SOURCE (задача 1.4) — при підключенні MSC/CMA
// до того самого «Журналу автооновлень» досить змінити лише цю константу в їхньому коді.
//
// ВАЖЛИВО про запис у CRM (задача 1.5): googleSheets appendOrUpdate з autoMapInputData оновлює
// ЛИШЕ ті колонки, ключі яких присутні в об'єкті `out`. Якщо поле не включити в `out` — комірка
// в таблиці лишається як є. На цьому базується guard: якщо поле «зайняте» ручною правкою,
// ми просто НЕ додаємо його в `out`, замість того щоб писати туди старе значення.
//
// TODO: перевірити на живій версії n8n точні назви опцій helpers.httpRequest, які тут
// використані (returnFullResponse / ignoreHttpStatusErrors) — вони можуть відрізнятись між
// мінорними версіями n8n. Якщо назви інші — HTTP-виклик нижче потрібно поправити (без цього
// класифікація 429/401/404 не спрацює коректно).

const SOURCE = 'Maersk';
const today = new Date(); today.setHours(0, 0, 0, 0);
const T = today.toISOString().slice(0, 10);
const NOWISO = new Date().toISOString();

const metas = $input.all().map(x => x.json);

// Токен: вузол «Maersk Token» читається з fullResponse:true, тож access_token у .body
const tokenResp = $('Maersk Token').first().json;
const token = (tokenResp && tokenResp.body) ? tokenResp.body.access_token : (tokenResp || {}).access_token;

// «Останнє записане скриптом значення» по полю (потрібне для guard 1.5) читаємо з «Журналу
// автооновлень» (1.4), а не з окремих прихованих колонок CRM — журнал і так є append-only
// історією таких значень, тримати їх ще й окремо в CRM було б дублюванням. Ключ мапи:
// Ключ(BL або контейнер цього прогону) + '|' + Колонка. Джерело фільтруємо, щоб не змішувати
// з майбутніми MSC/CMA-записами в той самий журнал.
const journalRows = (function () {
  try { return $('Читаємо Журнал').all().map(x => x.json); } catch (e) { return []; }
})();
const journalMap = {};
for (const jr of journalRows) {
  if (String(jr['Джерело'] || '') !== SOURCE) continue;
  const k = String(jr['Ключ'] || '') + '|' + String(jr['Колонка'] || '');
  journalMap[k] = jr['Нове'];
}

// guard 1.5: чи можна писати нове авто-значення в поле?
// Так — якщо в комірці зараз ПОРОЖНЬО (нічого перезаписувати), АБО поточне значення дорівнює
// тому, що скрипт сам туди востаннє писав (за журналом) — тобто людина його не чіпала.
// Якщо історії немає (lastAuto===undefined) — вважаємо це безпечним дефолтом «не чіпали».
// Якщо поточне значення відрізняється від останнього авто-значення — це РУЧНА правка, поле
// НЕ перезаписуємо, а лишаємо позначку в «Нагадування».
// ⚠ Чесне обмеження (TOCTOU, задача 1.5): guard бачить стан таблиці лише на момент вузла
// «Читаємо CRM» на початку прогону. Якщо людина відредагує комірку рівно між читанням і
// записом У МЕЖАХ ЦЬОГО Ж прогону — guard цього не побачить і запис може перетерти правку.
// Також: одразу після автопереходу «контейнер → BL» (1.2) журнал ще не має записів під новим
// ключем (BL), тож перший прогін після переходу вважає поле «не чіпали» — це прийнятний і
// задокументований компроміс, не помилка.
function guardOk(curVal, lastAuto) {
  if (!curVal) return true;
  if (lastAuto === undefined) return true;
  return curVal === lastAuto;
}

const byDate = a => a.slice().sort((x, y) => String(x.eventDateTime).localeCompare(String(y.eventDateTime)));

const results = [];
let stop401 = false;

function markRow(meta, trackVal, text) {
  results.push({ json: { _kind: 'write-crm', 'Угода': meta.uhoda, 'Нагадування': text } });
  results.push({ json: {
    _kind: 'log', 'Дата/час': NOWISO, 'Ключ': trackVal, 'Колонка': 'Нагадування',
    'Старе': '', 'Нове': text, 'Джерело': SOURCE
  }});
}

for (const meta of metas) {
  if (stop401) break;

  const trackVal = meta.trackByType === 'bl' ? meta.bl : meta.ourContainer;
  let url;
  if (meta.trackByType === 'bl') {
    url = 'https://api.maersk.com/track-and-trace-private/events?carrierBookingReference=' + encodeURIComponent(meta.bl);
  } else {
    // TODO: підтвердити параметр контейнерного пошуку Maersk на живому API (задача 1.2).
    // Ймовірно `equipmentReference`, можливо окремий endpoint — не підтверджено документацією.
    // Якщо параметр невірний, API поверне неочікуваний формат — спрацює гілка 'bad-format'
    // нижче (рядок піде в «потребує перевірки», а не тихо пропаде).
    url = 'https://api.maersk.com/track-and-trace-private/events?equipmentReference=' + encodeURIComponent(meta.ourContainer);
  }

  // Retry/backoff (задача 1.1): ≤3 повтори на конкретний запит у межах поточного прогону,
  // паузи 2с/4с/8с (лише при 429). Разом до 4 спроб (1 початкова + до 3 повторів).
  const backoffMs = [2000, 4000, 8000];
  const maxAttempts = 1 + backoffMs.length;
  let attempt = 0, classify = null, body = null, statusCode = null;

  while (attempt < maxAttempts) {
    attempt++;
    try {
      const resp = await this.helpers.httpRequest({
        method: 'GET',
        url,
        headers: {
          'Consumer-Key': '{{MAERSK_CLIENT_ID — реальне значення в n8n Cloud, НЕ зберігати в репо}}',
          'Authorization': 'Bearer ' + token
        },
        json: true,
        timeout: 20000,
        returnFullResponse: true,
        ignoreHttpStatusErrors: true
      });
      statusCode = resp.statusCode || resp.status || 200;
      body = resp.body !== undefined ? resp.body : resp;
    } catch (e) {
      // мережева помилка/timeout/парсинг — не 429/401, повторювати цей запит сенсу нема
      classify = 'bad-format';
      break;
    }

    if (statusCode === 429) {
      if (attempt < maxAttempts) {
        await new Promise(resolve => setTimeout(resolve, backoffMs[attempt - 1]));
        continue; // повтор ЦЬОГО Ж запиту
      }
      classify = 'rate-limit-exhausted';
      break;
    }
    if (statusCode === 401) { classify = 'stop-401'; break; }
    if (statusCode === 404) { classify = 'bl-not-found'; break; }
    if (statusCode >= 200 && statusCode < 300) {
      if (!body || typeof body !== 'object' || !Array.isArray(body.events)) { classify = 'bad-format'; break; }
      if (body.events.length === 0) { classify = 'bl-not-found'; break; }
      classify = 'ok';
      break;
    }
    classify = 'bad-format'; // будь-який інший статус (5xx тощо) — загальний технічний збій формату
    break;
  }

  if (classify === 'stop-401') {
    // 1.1: 401 на весь батч (протухлий токен) — жоден рядок НЕ отримує «оновлено».
    // Скидаємо все, що встигли зібрати в цьому ж прогоні до цього моменту.
    stop401 = true;
    results.length = 0;
    break;
  }
  if (classify === 'rate-limit-exhausted') { markRow(meta, trackVal, 'потребує перевірки: ліміт запитів ' + T); continue; }
  if (classify === 'bl-not-found') { markRow(meta, trackVal, 'потребує перевірки: BL не знайдено ' + T); continue; }
  if (classify === 'bad-format') { markRow(meta, trackVal, 'потребує перевірки: формат/timeout ' + T); continue; }

  // classify === 'ok' — парсинг подій, нова 8-модель статусів (1.3), guard (1.5), журнал (1.4)
  const events = body.events;
  const out = {
    'Угода': meta.uhoda, 'Лінія': 'Maersk', 'Останнє оновлення': T,
    'Ключ трекінгу': meta.newTrackKeyLabel
  };
  const reminders = [];

  const conts = [...new Set(events.map(e => e.equipmentReference).filter(Boolean))];
  out['Контейнер (лінія)'] = conts.join(', ');
  out['Звірка'] = '';
  if (meta.ourContainer && conts.length && !conts.includes(meta.ourContainer)) {
    out['Звірка'] = 'За Maersk: ' + conts.join(', ');
  }

  // «Контейнер» — виняток fill-if-empty (1.5): пишемо лише якщо комірка порожня; якщо людина
  // вже щось вписала — не чіпаємо, і навіть guard-конфлікт тут не потрібен (просто пропускаємо).
  if (!meta.curContainerNow && conts.length) {
    out['Контейнер'] = conts[0];
    results.push({ json: {
      _kind: 'log', 'Дата/час': NOWISO, 'Ключ': trackVal, 'Колонка': 'Контейнер',
      'Старе': '', 'Нове': conts[0], 'Джерело': SOURCE
    }});
  }

  // --- ETA (план/факт) + Судно/Вояж ---
  const arr = byDate(events.filter(e => (e.transportEventTypeCode === 'ARRI' || e.equipmentEventTypeCode === 'ARRI')));
  const lastArr = arr.length ? arr[arr.length - 1] : null;
  let etaIso = '', act = false;
  if (lastArr) { etaIso = String(lastArr.eventDateTime).slice(0, 10); act = (lastArr.eventClassifierCode === 'ACT'); }
  let days = 999;
  if (etaIso) { const e = new Date(etaIso); e.setHours(0, 0, 0, 0); days = Math.round((e - today) / 86400000); }

  const ves = byDate(events.filter(e => ((e.transportCall || {}).modeOfTransport) === 'VESSEL'));
  const lastVes = ves.length ? ves[ves.length - 1] : null;
  if (lastVes && days <= 7) {
    const tc = lastVes.transportCall || {};
    const newVessel = (tc.vessel || {}).vesselName || '';
    const newVoyage = tc.carrierVoyageNumber || tc.exportVoyageNumber || tc.importVoyageNumber || '';
    if (newVessel && newVessel !== meta.curVessel) {
      const lastAutoVessel = journalMap[trackVal + '|Судно'];
      if (guardOk(meta.curVessel, lastAutoVessel)) {
        out['Судно'] = newVessel;
        if (newVoyage) out['Вояж'] = newVoyage;
        results.push({ json: {
          _kind: 'log', 'Дата/час': NOWISO, 'Ключ': trackVal, 'Колонка': 'Судно',
          'Старе': meta.curVessel, 'Нове': newVessel, 'Джерело': SOURCE
        }});
      } else {
        reminders.push('трекінг: ' + newVessel + ' ≠ ваше ' + meta.curVessel + ', перевірте ' + T);
      }
    }
  }

  if (etaIso) {
    const field = act ? 'ETA порт (факт)' : 'ETA порт (план)';
    const curVal = act ? meta.curEtaAct : meta.curEtaPlan;
    if (etaIso !== curVal) {
      const lastAutoEta = journalMap[trackVal + '|' + field];
      if (guardOk(curVal, lastAutoEta)) {
        out[field] = etaIso;
        results.push({ json: {
          _kind: 'log', 'Дата/час': NOWISO, 'Ключ': trackVal, 'Колонка': field,
          'Старе': curVal, 'Нове': etaIso, 'Джерело': SOURCE
        }});
        if (!act && meta.curEtaPlan && meta.curEtaPlan !== etaIso) {
          out['Зміни ETA (історія)'] = (meta.histOld ? meta.histOld + '\n' : '') + T + ': ETA порт: ' + meta.curEtaPlan + ' → ' + etaIso + ' (Maersk)';
          out['Остання зміна'] = T;
        }
      } else {
        reminders.push('трекінг: ' + etaIso + ' ≠ ваше ' + curVal + ', перевірте ' + T);
      }
    }
  }

  // --- Статус: нова 8-модель (1.3), за кодом+модою ОСТАННЬОЇ події ---
  // Букінг → Стафіровка → В порту відправлення → Завантажений на судно → В морі →
  // Вивантажений в порту прибуття → Завантажений на авто/потяг → Вантаж доставлено.
  // Заморозка: імпорт на «Вантаж доставлено», експорт на «Вивантажений в порту прибуття».
  const frozen = (meta.napryamok === 'імпорт' && meta.curStatus === 'Вантаж доставлено') ||
                 (meta.napryamok === 'експорт' && meta.curStatus === 'Вивантажений в порту прибуття');
  if (!frozen) {
    const all = byDate(events);
    const le = all[all.length - 1];
    const mode = ((le.transportCall || {}).modeOfTransport) || '';
    const code = le.equipmentEventTypeCode || le.transportEventTypeCode || le.shipmentEventTypeCode || '';
    const isVesCtx = (mode === 'VESSEL' || mode === '');
    let st = '';
    if (code === 'GTIN' && mode === 'TRUCK') st = 'Вантаж доставлено';
    else if ((code === 'LOAD' || code === 'DEPA' || code === 'ARRI' || code === 'GTIN' || code === 'GTOT') && (mode === 'RAIL' || mode === 'TRUCK')) st = 'Завантажений на авто/потяг';
    else if (code === 'LOAD' && isVesCtx) st = 'Завантажений на судно';
    else if ((code === 'DEPA' || code === 'ARRI') && isVesCtx) st = 'В морі';
    else if (code === 'DISC' && isVesCtx) st = 'Вивантажений в порту прибуття';
    else if (code === 'GTIN' && isVesCtx) st = 'В порту відправлення';
    else if (code === 'GTOT' && isVesCtx) st = 'Стафіровка';

    if (st) {
      if (st !== meta.curStatus) {
        const lastAutoStatus = journalMap[trackVal + '|Статус'];
        if (guardOk(meta.curStatus, lastAutoStatus)) {
          out['Статус'] = st;
          results.push({ json: {
            _kind: 'log', 'Дата/час': NOWISO, 'Ключ': trackVal, 'Колонка': 'Статус',
            'Старе': meta.curStatus, 'Нове': st, 'Джерело': SOURCE
          }});
        } else {
          reminders.push('трекінг: ' + st + ' ≠ ваше ' + meta.curStatus + ', перевірте ' + T);
        }
      }
    } else {
      // 1.3: жодна комбінація код+режим не мовчить без відповідного запису
      reminders.push('потребує перевірки: незнайома подія ' + (code || '?') + '/' + (mode || '—') + ' ' + T);
      results.push({ json: {
        _kind: 'log', 'Дата/час': NOWISO, 'Ключ': trackVal, 'Колонка': 'Статус',
        'Старе': meta.curStatus, 'Нове': '(незнайома подія ' + (code || '?') + '/' + (mode || '—') + ')', 'Джерело': SOURCE
      }});
    }
  }

  // автоперехід «контейнер → BL» (1.2, останній пункт)
  if (meta.autoTransition) {
    out['Ключ трекінгу'] = 'BL';
    out['Зміни ETA (історія)'] = (out['Зміни ETA (історія)'] ? out['Зміни ETA (історія)'] + '\n' : (meta.histOld ? meta.histOld + '\n' : '')) + T + ': контейнер → BL (Maersk)';
    results.push({ json: {
      _kind: 'log', 'Дата/час': NOWISO, 'Ключ': meta.bl, 'Колонка': 'Ключ трекінгу',
      'Старе': 'контейнер (тимчасово)', 'Нове': 'BL', 'Джерело': SOURCE
    }});
  }

  if (reminders.length) out['Нагадування'] = reminders.join(' | ');

  results.push({ json: Object.assign({ _kind: 'write-crm' }, out) });
}

if (stop401) {
  results.push({ json: {
    _kind: 'stop-401', 'Дата/час': NOWISO, 'Ключ': '', 'Колонка': '',
    'Старе': '', 'Нове': '401 — недійсний токен, прогін зупинено, ' + T, 'Джерело': SOURCE
  }});
}

return results;
