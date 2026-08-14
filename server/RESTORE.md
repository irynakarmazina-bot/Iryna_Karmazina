# Як відновити платформу з резервної копії

Написано 08.08.2026. Це інструкція «на чорний день» — читати, коли щось зникло
або зіпсувалось. Розрахована на те, що читатиме не програміст.

---

## Що де лежить

| що | де |
|---|---|
| Резервні копії | сервер `134.209.94.12`, тека `/root/backups/` |
| Одна копія на добу, о 03:30 | файли виду `unitex-20260808-182533.tar.gz.gpg` |
| Пароль для розшифрування | менеджер «Паролі» на Mac Ірини, запис **«Юнітекс резервні копії»** |
| Копія пароля на сервері | `/root/.backup-pass` (права 600) |
| Журнал усіх копій | `/root/backup_log.tsv` |
| Ключ доступу до сервера | Mac Ірини, `~/.ssh/unitex_droplet` |

**Пароля в цьому файлі немає і бути не повинно.**

---

## Що всередині копії

* `noco.db` — сама база: угоди, клієнти, калькуляції, журнал дій, інструкції;
* `config/` — те, чого немає в git і що інакше довелось би відновлювати руками:
  `Caddyfile`, `authcheck.py`, `deals_trigger.py`, `cash_trigger.py`, `trigger.py`,
  юніти systemd для трекінгу й тригерів, `00-hardening.conf` (налаштування SSH);
* `attachments/` — файли, прикріплені до угод (з'являється, коли вони є).

Фасада (`www/index.html`) в копії **немає навмисно**: він лежить у git і має власні
бекапи, які робить `server/deploy_ui.sh` (14 днів, тека `/root/unitex-os-www/.backups`).

---

## Відновлення бази

### Крок 1. Зайти на сервер

```bash
ssh -i ~/.ssh/unitex_droplet root@134.209.94.12
```

Якщо ключ не працює або Mac недоступний — панель DigitalOcean → дроплет →
**Access** → **Reset Root Password** (пароль прийде на пошту) → **Launch Droplet Console**.

### Крок 2. Обрати копію

```bash
ls -1t /root/backups/
```
Найсвіжіша — зверху. Якщо треба стан «до поломки», бери копію за день **до** того,
як проблема з'явилась.

### Крок 3. Розшифрувати й розпакувати

Замість `ІМ'Я_ФАЙЛА` підстав обране ім'я:

```bash
mkdir -p /root/restore
gpg --output /root/restore/archive.tar.gz --decrypt /root/backups/ІМ'Я_ФАЙЛА
```
Спитає пароль — узяти з менеджера «Паролі», запис «Юнітекс резервні копії».

```bash
tar -xzf /root/restore/archive.tar.gz -C /root/restore
ls -la /root/restore
```

### Крок 4. Переконатися, що копія ціла — ДО того, як щось замінювати

```bash
python3 -c "import sqlite3; print(sqlite3.connect('/root/restore/noco.db').execute('PRAGMA integrity_check').fetchone()[0])"
```
Має вивести `ok`. Якщо ні — **не продовжувати**, узяти попередню копію.

Скільки в ній записів:
```bash
python3 -c "
import sqlite3
b=sqlite3.connect('/root/restore/noco.db')
for t in ['nc_bpfs___Диспетчеризація','nc_bpfs___Клієнти','nc_bpfs___audit_log']:
    print(t, b.execute('SELECT COUNT(*) FROM \"%s\"' % t).fetchone()[0])
"
```

### Крок 5. Замінити базу

⚠️ Спершу **зберегти те, що є зараз** — навіть якщо воно виглядає зіпсованим.
Можливо, доведеться повертатись.

```bash
docker stop nocodb
cp /root/nocodb-data/noco.db /root/nocodb-data/noco.db.before-restore-$(date +%Y%m%d-%H%M%S)
cp /root/restore/noco.db /root/nocodb-data/noco.db
docker start nocodb
```

Зачекати до хвилини, поки база підніметься, і перевірити:
```bash
curl -s http://127.0.0.1:8080/api/v1/version
curl -sk -o /dev/null -w "сайт: %{http_code}\n" https://134.209.94.12/
```

### Крок 6. Відкрити платформу і подивитись очима

`https://134.209.94.12` → «Диспетчеризація» → чи на місці угоди, клієнти, статуси.

---

## Відновлення службових файлів

Якщо зник або зіпсувався не запис у базі, а налаштування:

```bash
ls -la /root/restore/config/
```

Копіювати **поштучно**, туди, звідки взято:

| файл із `config/` | куди повернути |
|---|---|
| `Caddyfile` | `/root/Caddyfile`, далі `docker restart caddy` |
| `authcheck.py` | `/root/authcheck.py` |
| `deals_trigger.py` | `/root/deals_trigger.py`, далі `systemctl restart deals-sync-trigger` |
| `cash_trigger.py` | `/root/cash_trigger.py`, далі `systemctl restart cashtrigger` |
| `trigger.py` | `/root/unitex-finrep/trigger.py`, далі `systemctl restart finrep-trigger` |
| `*.service`, `*.timer` | `/etc/systemd/system/`, далі `systemctl daemon-reload` |
| `00-hardening.conf` | `/etc/ssh/sshd_config.d/`, далі `sshd -t && systemctl reload ssh` |

---

## Якщо сервера більше немає взагалі

1. Створити новий дроплет Ubuntu 24.04 у DigitalOcean.
2. Поставити docker, підняти NocoDB із тим самим монтуванням:
   `-v /root/nocodb-data:/usr/app/data -p 127.0.0.1:8080:8080`
   (точні параметри старого контейнера збережені у файлах
   `/root/nocodb-container-*.json` і в самих копіях).
3. Покласти `noco.db` з копії в `/root/nocodb-data/`.
4. Повернути `Caddyfile` і решту з `config/`.
5. Клонувати репозиторій у `/root/Iryna_Karmazina` і викласти фасад:
   `bash server/deploy_ui.sh main`.
6. Перевірити фаєрвол: вхідні тільки 22, 80, 443.

⚠️ Для цього кроку копії мають лежати **не на тому сервері, якого вже немає**.
Саме тому потрібне вивантаження назовні (DigitalOcean Spaces / Google Drive).

---

## Перевірка, що бекапи взагалі робляться

```bash
tail -5 /root/backup_log.tsv
systemctl list-timers unitex-backup.timer
```

Рядок журналу: дата, `OK`, розмір у байтах, відбиток, скільки секунд зайняло, ім'я файла.
Якщо `OK` немає або дата стара — копії не робляться, розбиратись треба одразу.


## Кабінет клієнтів (з 14.08.2026)

В архіві поруч із `noco.db` лежить **`cabinet.db`** — акаунти клієнтів, їхні
сесії і серверний журнал (хто заходив, що дивився, що завантажував).

Відновлення:
```bash
systemctl stop unitex-cabinet
cp cabinet.db /root/cabinet/cabinet.db
chown root:root /root/cabinet/cabinet.db && chmod 600 /root/cabinet/cabinet.db
systemctl start unitex-cabinet
cd /root/Iryna_Karmazina/server && python3 cabinet_admin.py list   # звірити акаунти
```
Файл `/root/cabinet/secret` в архів свідомо не входить: це ключ для міток форм,
при першому запуску генерується новий. Наслідок — лише те, що відкриті в цю
мить форми доведеться оновити.
Сесії після відновлення можна лишити; якщо база не найсвіжіша, надійніше
закрити всі: `python3 cabinet_admin.py kick --email <пошта>` для кожного.
