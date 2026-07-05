# UNITEX Dispatch — CRM моніторингу відправлень

Автоматизація контролю прибуття контейнерів (доповнює Експедитор Про).
Станом на 2026-07-05.

## Що це

Google-таблиця (майстер) + три n8n-воркфлоу:
1. **Maersk Container Tracking** — щодня тягне реальні дати/судна/статуси з Maersk API у таблицю.
2. **CRM Дашборд (web)** — керівнича веб-сторінка (всі відправлення).
3. **CRM Клієнтська вітрина (web)** — клієнтські сторінки за токеном.

## Де що працює

- **Платформа автоматизації: n8n Cloud** — `https://irynakarmazina.app.n8n.cloud`, API base `/api/v1`.
  Ключ API — у `~/.claude/projects/-Users-irina/.env` (`N8N_API_KEY`). НЕ в цьому репо.
- **Google-акаунт n8n:** `unitex.automation@gmail.com` (Sheets cred `S6pSxt1O96LflGWp`, Drive cred `2GWpYd58b4gHSUPi`, SMTP `IRHmy9RLt9AtxQFS`, IMAP `kW24ZrmT1XnVuRpA`, Anthropic `S4WsLWJw1fpDwXqf`).
- **НЕ Apps Script.** Дашборд і вітрина — це n8n Code-вузли (JS), що віддають HTML через webhook. Немає .gs-файлів для цього CRM (Apps Script використовується лише в окремому «Фінансовому дашборді», інша таблиця).
- **Google Sheets Drive-конектор бачить лише свої файли**, тож усі записи в майстер-таблицю йдуть через **Sheets REST API** (spreadsheets.values / batchUpdate), а не через Drive MCP. У сесії використовувався тимчасовий n8n-проксі (`helpers/sheets-proxy.md`).

## Майстер-таблиця

- **ID:** `1FkvCfEZv7Ni5SYJCuaEB7BubmwPs5D0laM0A9g4byF8`
- URL: https://docs.google.com/spreadsheets/d/1FkvCfEZv7Ni5SYJCuaEB7BubmwPs5D0laM0A9g4byF8/edit
- Власник — `unitex.automation@gmail.com`; `irynakarmazina@gmail.com` = Редактор.
- Аркуші: **Відправлення** (gid 11111, головні дані), **Дашборд** (22222), **Клієнти** (33333, токени вітрин), **Невідомі BL** (44444), **Демередж** (55555, довідник тарифів).
- Структура колонок — `docs/SHEET-STRUCTURE.md`.

## Веб-сторінки (active)

- Керівничий дашборд: `https://irynakarmazina.app.n8n.cloud/webhook/crm-dashboard`
- Клієнтська вітрина: `…/webhook/portal?t=<токен>` (токени у вкладці «Клієнти»)

## Maersk-трекінг — як працює

Файл воркфлоу: `workflows/maersk-container-tracking.json`. Ланцюг:
`Schedule (щодня 07:00, Europe/Kyiv)` → `Maersk Token` (OAuth) → `Читаємо CRM` (Sheets) →
`Відбір Maersk` (`maersk-tracking/vidbir.code.js` — бере рядки з 9-значним BL) →
`Maersk API` (`GET track-and-trace-private/events?carrierBookingReference=<BL>`, батч 8/1500мс) →
`Розбір` (`maersk-tracking/rozbir.code.js` — мапить події в статус/дати) →
`Запис у CRM` (appendOrUpdate, match по `BL/Booking`, autoMap).

Є також ручний запуск: POST `…/webhook/jqka-run`.

**ВАЖЛИВО (баг, який виправлено):** вузол «Розбір» був у режимі *runOnceForAllItems* зі старим кодом «на один item» — тому оновлював ЛИШЕ 1 угоду за прогін. Переписано на цикл по всіх items. Тепер обробляє всі BL.

Мапінг подій → статус — `docs/STATUS-MODEL.md`.

## Ключові рішення сесії

- **Оплачено ≠ доставлено** (передплати). Статус «Вантаж доставлено» — ЛИШЕ з реального трекінгу (Maersk GTIN/TRUCK = порожній повернуто) або ручного внесення менеджером. Ніколи з оплати/дати завершення.
- **Потяг = завжди carrier haulage** (проставлено в колонку «Вивіз»).
- **Демередж** рахується від «Вивантаження в порту (факт)», зупиняється при «Постановка/завантаження (факт)»; тариф за ЛІНІЯ×ПОРТ×ВИВІЗ×ОБЛАДНАННЯ. Усі тарифи — ЧЕРНЕТКА, перевірити.
- **Розбіжність ручних даних із перевіркою** → коментар, не перезаписувати.
- **«Вантаж доставлено» — заморожено** (після підтвердження статусів не чіпати).

## Відкриті питання

- ~30 Maersk-угод без статусу (429 rate-limit) — потрібен ще прогін.
- Інші лінії (MSC/CMA/Інша, ~26) — трекінг окремо (морський через сайт/логін).
- Розбивка багатоконтейнерних коносаментів на окремі рядки (per-container) — НЕ зроблено; змінить ключ звірки Maersk з BL на контейнер.
- Демередж-детеншен шар (пауза на потязі, відновлення в сухому порту) — не реалізовано.
- Тарифи MSC@Польща, CMA@Констанца — дістати.
