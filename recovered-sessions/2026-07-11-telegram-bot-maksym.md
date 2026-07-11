# Telegram-бот «Максим» — повна документація (відновлена сесія 2026-07-11)

> Ця сесія відбувалась локально на комп'ютері Ірини і не була видима іншим сесіям.
> Файл відновлено вручну для збереження в репо.

---

## Що це

AI-помічник компанії Юнітекс у Telegram. Збирає інформацію від клієнтів для прорахунку фрахту і передає менеджеру. Побудований на n8n Cloud + Claude Opus.

---

## Доступ до n8n

| Параметр | Значення |
|---|---|
| URL | https://irynakarmazina.app.n8n.cloud |
| Акаунт | irynakarmazina@gmail.com (особистий) |
| Workflow ID бота | `FC3qzaxp5M89LpI7` |
| Назва workflow | «UNITEX Telegram Bot» |
| API ключ | тимчасово в `~/.n8n_env` → `N8N_API_KEY=...` |

> ⚠️ API ключ — JWT-токен (~267 символів). Вставляти з пробілом після `=` — скрипт trim'ить автоматично. Після роботи ключ НЕ видаляти самостійно — Ірина вирішує сама коли прибрати.

---

## Як оновити промт через API (перевірений скрипт)

```bash
N8N_API_KEY=$(grep -oP 'N8N_API_KEY=\s*\K.*' ~/.n8n_env | tr -d ' \t\r\n')

# 1. Завантажити workflow
curl -s -H "X-N8N-API-KEY: $N8N_API_KEY" \
  "https://irynakarmazina.app.n8n.cloud/api/v1/workflows/FC3qzaxp5M89LpI7" \
  -o /tmp/workflow.json

# 2. Оновити systemMessage і зібрати PUT-payload
python3 << 'PYEOF' > /tmp/workflow_put.json
import json
with open('/Users/irina/Desktop/UNITEX_bot_prompt.txt', 'r', encoding='utf-8') as f:
    new_prompt = f.read()
with open('/tmp/workflow.json','rb') as f:
    d = json.load(f)
for n in d.get('nodes', []):
    if n.get('name') == 'AI Agent':
        n['parameters']['options']['systemMessage'] = new_prompt
        break
payload = {
    "name": d["name"],
    "nodes": d["nodes"],
    "connections": d["connections"],
    "settings": d.get("settings", {}),
    "staticData": d.get("staticData", None)
}
print(json.dumps(payload, ensure_ascii=False))
PYEOF

# 3. Відправити PUT (тільки дозволені поля — без id/createdAt/tags)
curl -s -w "\n%{http_code}" \
  -X PUT \
  -H "X-N8N-API-KEY: $N8N_API_KEY" \
  -H "Content-Type: application/json" \
  -d @/tmp/workflow_put.json \
  "https://irynakarmazina.app.n8n.cloud/api/v1/workflows/FC3qzaxp5M89LpI7"
# Очікувана відповідь: HTTP 200
```

> ⚠️ Якщо PUT повертає 400 `must NOT have additional properties` — значить у payload потрапили зайві поля (`id`, `createdAt`, `tags`). Скрипт вище це виключає.

---

## Файл промту

**Шлях:** `/Users/irina/Desktop/UNITEX_bot_prompt.txt`

Всі зміни вносяться спочатку в цей файл, потім завантажуються в n8n скриптом вище. Файл — єдине джерело правди для промту.

---

## Структура workflow (21 вузол)

```
Telegram Trigger
  → Code: Prepare          ← debounce + фільтр груп + визначення медіа
  → IF Admin Command
      [так] → Code: Admin Handler → Telegram: Admin Reply
      [ні]  → Code: Check Paused
                → IF Is Paused
                    [так] → No Operation
                    [ні]  → IF Is Media
                                [так] → Notify Group: Media
                                [ні]  → AI Agent ← Window Buffer Memory
                                                  ← Claude Opus
                                        → Wait (4-8s)
                                        → Code: Debounce
                                        → IF Is Latest
                                            → Telegram: Send Response
                                            → Notify Group: Message
                                            → IF Is Complete
                                                → Code: Build Email
                                                → Send Email
```

---

## Ключові параметри вузлів

| Вузол | Важливий параметр |
|---|---|
| Claude Opus | model: `claude-opus-4-5`, typeVersion: **1.2** (не 1.3!) |
| AI Agent | typeVersion: **3.1** |
| Window Buffer Memory | typeVersion: **1.3**, sessionIdType: **customKey** (не fromInput!) |
| Telegram: Send Response | прямий HTTP Request до Telegram API (без n8n брендингу) |
| Notify Group: Message | chat_id: **-5171955743** (група UNITEX Leads) |

---

## Бот

| Параметр | Значення |
|---|---|
| Ім'я в Telegram | Максим (AI-помічник Юнітекс) |
| Токен | hardcode у HTTP Request вузлах workflow |
| Група моніторингу | UNITEX Leads, chat_id: `-5171955743` |
| Email менеджера | `i.karmazina@unitex.od.ua` |
| Сайт | unitex.od.ua (підключений через плагін Chaty на WordPress) |

---

## Поточна логіка діалогу

1. **Вітання** — Максим представляється і питає ім'я клієнта
2. **Запит на прорахунок** → надсилає весь список питань **ОДНИМ повідомленням** + просить контакт (телефон + месенджер або email) + дякує + каже що менеджер зв'яжеться
3. **Після відповіді клієнта** → підтверджує; якщо бракує критичного (маршрут або контакт) — питає тільки це одним реченням
4. **«Це бот?» / «Хочу людину»** → пояснює що він AI-помічник, збирає інформацію, менеджер може бачити розмову і приєднатися; пропонує телефони та Telegram
5. **Медіафайл від клієнта** → тихо сповіщає групу, клієнту не відповідає
6. **Адмін-команди** → `/pause`, `/resume`, `/getchatid`, `/status`, `/msg`

---

## Контакти компанії (в промті)

- Одеса: (098) 680-87-57
- Київ: (098) 153-21-01, (044) 227-34-38
- Telegram: @Unitex_Forwarding
- Email: sales@unitex.od.ua

---

## Відомі фікси (не повторювати помилок)

| Проблема | Рішення |
|---|---|
| `No session ID found` у Buffer Memory | `sessionIdType: customKey` (не `fromInput`) |
| Claude node `Could not get parameter` | typeVersion `1.2` (не `1.3`) |
| n8n брендинг у повідомленнях Telegram | прямий HTTP Request до Telegram API |
| Бот відповідає в групі UNITEX Leads | фільтр в Code: Prepare — skip якщо `is_group && !is_admin_command` |
| Подвійні повідомлення = подвійна відповідь | debounce через `$getWorkflowStaticData` + `message_id` |
| PUT /workflows → 400 `additional properties` | надсилати тільки `name, nodes, connections, settings, staticData` |
| Ключ у `.n8n_env` має пробіл після `=` | `grep -oP ... | tr -d ' \t\r\n'` при читанні |

---

## Зміни промту в цій сесії (2026-07-11)

1. **Новий алгоритм діалогу** — замість збору питань по одному: весь список одразу + контакт в одному повідомленні
2. **«Це бот?»** — новий Формат 4 у Протоколі: пояснення ролі AI + що менеджер може підключитися + телефони/Telegram
3. **Роль Максима** — прибрано «Не згадуй менеджера до фінального підтвердження»; додано що менеджер може бачити і приєднатися
4. **Вага контейнера** — не коментувати, не попереджати, просто фіксувати (до 28т, залежить від контейнера)
5. **Батареї/акумулятори** — питати тільки якщо вантаж за природою може їх містити
