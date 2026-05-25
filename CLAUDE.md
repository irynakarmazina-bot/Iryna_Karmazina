# Контекст для Claude — прочитай перед будь-якою дією

## Пам'ять сесій
також одразу прочитай MEMORY.md у корені репо

## Хто я

## Правила роботи зі мною

## Мої проєкти

### Telegram-бот на Claude
Головний файл — bot.py. Залежності — requirements.txt.

**Сервер**
Бот працює на VPS DigitalOcean.
- Шлях: /root/Iryna_Karmazina
- Сервіс: mybot.service (systemd)
- Автодеплой: /root/autodeploy.sh запускається щохвилини, робить git pull і перезапускає сервіс при змінах.

**Git Relay**
Механізм для виконання команд на сервері через GitHub без термінала.
- `cmds/pending.json` — команда для виконання: `{"id":"...", "cmd":"..."}`
- `cmds/result.json` — результат виконання: `{"id":"...", "stdout":"...", "stderr":"...", "returncode":0, "ts":"..."}`
- `cmd_runner.py` — скрипт на сервері, читає pending.json кожні 5 секунд і виконує команди
- Сервіс: cmdrunner.service (systemd)

**Workflow**
Усе через GitHub: коміт у main → за хвилину сервер оновиться.
Руками до сервера не лізьмо.
