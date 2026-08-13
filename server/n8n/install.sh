#!/bin/bash
# Установка self-hosted n8n поруч із ЕРП. Нічого не ламає і нічого не видаляє.
#
# Що робить:
#   1. перевіряє, що на сервері вистачає пам'яті (і пропонує swap, якщо його немає)
#   2. створює /root/n8n-data, .env з ключем шифрування, кладе docker-compose.yml
#   3. піднімає контейнер, слухаючи ТІЛЬКИ 127.0.0.1:5678
#   4. показує, що дописати в Caddyfile — САМ Caddyfile НЕ ЧІПАЄ
#
# Чого НЕ робить свідомо:
#   * не міняє Caddyfile (це бойовий файл, через нього працює ЕРП і кабінет)
#   * не вимикає n8n Cloud і нічого там не чіпає
#   * не переносить воркфлоу — це окремий крок, вручну, після перевірки
#
# Запуск:  bash /root/Iryna_Karmazina/server/n8n/install.sh n8n.unitex.od.ua
#          bash ... --check      — тільки перевірити готовність, нічого не ставити
set -u

DOMAIN="${1:-}"
CHECK=0
for a in "$@"; do [ "$a" = "--check" ] && CHECK=1; done
[ "${DOMAIN:0:2}" = "--" ] && DOMAIN=""

DATA="/root/n8n-data"
REPO="/root/Iryna_Karmazina"
MEM_LIMIT="${N8N_MEM_LIMIT:-512m}"

say(){ echo "  $*"; }
die(){ echo "СТОП: $*"; exit 1; }

echo "== 1. Перевірка сервера =="
TOTAL=$(free -m | awk '/^Mem:/{print $2}')
AVAIL=$(free -m | awk '/^Mem:/{print $7}')
SWAP=$(free -m | awk '/^Swap:/{print $2}')
say "пам'ять: $TOTAL МБ усього, $AVAIL МБ вільно, swap: $SWAP МБ"
say "диск:    $(df -h / | awk 'NR==2{print $4}') вільно"
say "ядер:    $(nproc)"

if [ "$AVAIL" -lt 400 ]; then
  die "вільно менше 400 МБ — ставити n8n НЕ МОЖНА, система вб'є NocoDB (тобто ЕРП)"
fi
if [ "$SWAP" -eq 0 ]; then
  echo
  echo "  ⚠️  SWAP ВІДСУТНІЙ. На сервері з 2 ГБ це небезпечно: сплеск у n8n"
  echo "     може призвести до вбивства NocoDB. Рекомендовано додати 2 ГБ swap:"
  echo
  echo "       fallocate -l 2G /swapfile && chmod 600 /swapfile"
  echo "       mkswap /swapfile && swapon /swapfile"
  echo "       echo '/swapfile none swap sw 0 0' >> /etc/fstab"
  echo
  echo "     Це окрема дія — скрипт її НЕ робить сам."
fi

command -v docker >/dev/null || die "docker не встановлено"
docker compose version >/dev/null 2>&1 || die "docker compose не встановлено"
say "docker: $(docker --version | cut -d, -f1)"

if [ "$CHECK" = "1" ]; then
  echo
  echo "== Перевірка завершена. Нічого не змінено. =="
  exit 0
fi

[ -n "$DOMAIN" ] || die "не вказано домен. Приклад: bash $0 n8n.unitex.od.ua"

echo
echo "== 2. Тека даних і налаштування =="
mkdir -p "$DATA/.n8n" "$DATA/files" || die "не можу створити $DATA"
chown -R 1000:1000 "$DATA/.n8n" "$DATA/files"

if [ -f "$DATA/.env" ]; then
  say ".env уже є — НЕ перезаписую (там ключ шифрування)"
else
  KEY="$(openssl rand -hex 32)"
  cat > "$DATA/.env" <<EOF
N8N_HOST=$DOMAIN
N8N_ENCRYPTION_KEY=$KEY
N8N_MEM_LIMIT=$MEM_LIMIT
N8N_VERSION=latest
EOF
  chmod 600 "$DATA/.env"
  say "створено $DATA/.env (права 600), ключ шифрування згенеровано"
  echo
  echo "  🔑 ВАЖЛИВО: ключ шифрування треба скопіювати в менеджер паролів."
  echo "     Без нього резервна копія n8n марна — паролі до сервісів не прочитати."
  echo "     Показати ключ: grep N8N_ENCRYPTION_KEY $DATA/.env"
fi

cp "$REPO/server/n8n/docker-compose.yml" "$DATA/docker-compose.yml" || die "немає compose-файла в репозиторії"
say "docker-compose.yml покладено в $DATA"

echo
echo "== 3. Запуск =="
cd "$DATA" || die "немає $DATA"
docker compose --env-file "$DATA/.env" up -d || die "контейнер не піднявся"
sleep 8
docker ps --filter name=n8n --format '  {{.Names}} {{.Status}}'
CODE=$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:5678/healthz || echo 000)
say "перевірка http://127.0.0.1:5678/healthz → $CODE"
[ "$CODE" = "200" ] || say "⚠️ n8n ще піднімається або не стартував: docker logs n8n --tail 50"

echo
echo "== 4. Що зробити РУКАМИ далі =="
cat <<EOF

  1) DNS: додати A-запис  $DOMAIN → $(curl -s -4 ifconfig.me 2>/dev/null || echo '<IP сервера>')

  2) Caddy: дописати в /root/Caddyfile новий блок (сам файл я не чіпаю):

       $DOMAIN {
           reverse_proxy 127.0.0.1:5678
       }

     Перевірити й застосувати:
       docker exec caddy caddy validate --config /etc/caddy/Caddyfile
       docker exec caddy caddy reload  --config /etc/caddy/Caddyfile

  3) Відкрити https://$DOMAIN і завести акаунт власника (пошта + пароль).

  4) Резервні копії: додати «$DATA/.n8n» у PATHS у server/backup.py,
     інакше воркфлоу не потраплять у щоденну копію.

  5) Воркфлоу переносити ПО ОДНОМУ через Import from File
     (файли — у n8n_backup/ репозиторію), доступи заводити заново.

  6) n8n Cloud НЕ вимикати, доки нове не відпрацює хоча б тиждень.

EOF
