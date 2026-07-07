# Telegram-бот на Claude

Особистий Telegram-бот для себе, на Claude API (Anthropic).

## Файли
- `bot.py` — головний файл.
- `agent_bot.py` — агентна логіка.
- `requirements.txt` — залежності.

## Сервер (VPS DigitalOcean)
- Шлях: `/root/Iryna_Karmazina`.
- Сервіс: `mybot.service` (systemd).
- Автодеплой: `/root/autodeploy.sh` запускається щохвилини, робить `git pull` з `main`
  і перезапускає сервіс при змінах.

## Git Relay (виконання команд на сервері без термінала)
- `cmds/pending.json` — команда: `{"id":"...", "cmd":"..."}`.
- `cmds/result.json` — результат виконання.
- `cmd_runner.py` — читає pending.json кожні 5 сек, виконує; сервіс `cmdrunner.service`.
- ⚠ cmd_runner читає pending.json **з main** — relay-команди комітити в `main`.
- ⚠ Ліміт cmd_runner — 120 с; довгі `sleep` не ставити.
- ⚠ Урок: cmd_runner падає на не-ASCII виводі, обрізаному посеред UTF-8 (head -c);
  вивід релей-команд робити ASCII-safe (напр. `tr -cd`).

## Фінансовий модуль (непогоджений)
Модуль `finance.py` (P&L/Cash Flow у SQLite) — на гілці фінзвіту, НЕ погоджений,
можливо застаріє. При злитті гілки [[finzvit]] переносити ТІЛЬКИ `report/`.

## Пов'язане
[[finzvit]] · [[dyspetcheryzatsiya]] · overview
