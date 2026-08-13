# Аварійна картка — коли щось лежить, а спитати нема кого

Одна сторінка. Розрахована на те, що читатиме не програміст, у поганий момент.
Дані відновлювати — `server/RESTORE.md`. Загальний опис системи — `README.md`.

**Правило номер нуль: спершу подивитись, потім міняти. Нічого не видаляти.**

Зайти на сервер:

```bash
ssh -i ~/.ssh/unitex_droplet root@134.209.94.12
```

Якщо ключ не працює: панель DigitalOcean → дроплет → **Access** →
**Reset Root Password** → **Launch Droplet Console**.

---

## Перше, що зробити завжди — загальний огляд

```bash
systemctl --failed
docker ps
df -h /
tail -20 /root/backup_log.tsv
```

- `systemctl --failed` — які служби впали
- `docker ps` — мають бути **caddy** і **nocodb**
- `df -h /` — якщо диск заповнений на 100%, падати буде все підряд
- останній рядок журналу копій має бути за сьогодні або вчора

---

## Симптом → що робити

### ЕРП не відкривається взагалі (сайт не відповідає)

```bash
docker ps | grep caddy || docker start caddy
docker logs --tail 50 caddy
curl -s -o /dev/null -w "%{http_code}\n" https://cabinet.unitex.od.ua/
```

### Сайт відкрився, але порожній / «не вдалося завантажити дані»

Значить, фасад живий, а дані не приходять. Перевірити ланцюг знизу вгору:

```bash
curl -s http://127.0.0.1:8080/api/v1/version        # NocoDB — має відповісти
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8792/   # прошарок
systemctl status unitex-gateway --no-pager | head -15
tail -30 /root/gateway.log
```

- NocoDB мовчить → `docker start nocodb`, далі `docker logs --tail 50 nocodb`
- прошарок мовчить → `systemctl restart unitex-gateway`
- у `gateway.log` рядки про відмови під час звичайної роботи → прошарок
  блокує зайве. **Тимчасовий обхід:** повернути маршрут повз нього
  (див. «Відкат прошарку» нижче).

### Сторінка ЕРП зламалась після викладення

```bash
bash /root/Iryna_Karmazina/server/rollback_ui.sh        # показати версії
bash /root/Iryna_Karmazina/server/rollback_ui.sh 1      # відкотити на крок назад
```

Нічого не видаляється: поточна версія теж лягає в бекапи.

### Кабінет клієнта не працює

```bash
systemctl status unitex-cabinet --no-pager | head -15
systemctl restart unitex-cabinet
tail -30 /root/cabinet.log
```

### Telegram-бот мовчить

```bash
systemctl status mybot --no-pager | head -15
journalctl -u mybot -n 50 --no-pager
systemctl restart mybot
```

### Не працює трекінг Maersk або бот «Максим»

Це **не на сервері**. Вони живуть у n8n Cloud —
`irynakarmazina.app.n8n.cloud`, розділ Executions: там видно, чи запускалось
і на чому впало.

### Резервні копії перестали робитись

```bash
systemctl list-timers unitex-backup.timer
journalctl -u unitex-backup -n 50 --no-pager
systemctl start unitex-backup.service     # зробити копію просто зараз
tail -5 /root/backup_log.tsv
```

---

## Відкат прошарку (якщо він блокує роботу)

Повернути `/api/*` напряму на NocoDB:

```bash
cp /root/Caddyfile.bak-20260813-130838 /root/Caddyfile
docker exec caddy caddy reload --config /etc/caddy/Caddyfile
```

Перевірити: сайт має відкритись і показати дані.
Це безпечно: так система працювала до 13.08.2026.

---

## Чого НЕ робити ніколи

- ❌ не копіювати `www/index.html` на сервер руками — тільки `deploy_ui.sh`
- ❌ не видаляти нічого «зайвого»: ні файлів, ні гілок, ні воркфлоу n8n,
  ні рядків у базі. Навіть якщо виглядає сміттям
- ❌ не робити `git push --force` і не «лагодити» розбіжність гілок злиттям
- ❌ не міняти базу `noco.db` на місці без зупинки контейнера й копії поруч

---

## Якщо не допомогло нічого

1. Зробити копію стану **до** будь-яких дій:
   `systemctl start unitex-backup.service`
2. Відновлення бази — `server/RESTORE.md`, крок за кроком.
3. Якщо сервера більше немає взагалі — `server/RESTORE.md`, останній розділ
   («Якщо сервера більше немає»). Копії лежать також на Google Drive.

**Пароль від копій** — менеджер «Паролі», запис «Юнітекс резервні копії».
Без нього копії не розшифрувати. Це єдина необоротна поломка в системі.
