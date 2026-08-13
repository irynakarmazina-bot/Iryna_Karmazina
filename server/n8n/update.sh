#!/bin/bash
# Оновлення self-hosted n8n з резервною копією і швидким відкатом.
#
# Навіщо саме так: n8n оновлюється часто, і бувають випуски, що ламають
# наявні воркфлоу. «docker pull latest && restart» без копії — це спосіб
# втратити робочу автоматизацію без шляху назад.
#
# Порядок:
#   1. запам'ятати, яка версія працює зараз (для відкату)
#   2. зупинити n8n і зробити копію теки даних (там воркфлоу й доступи)
#   3. підняти нову версію, дочекатись healthz
#   4. якщо не піднялось — АВТОМАТИЧНО повернути стару версію і стару копію
#
# Запуск:  bash /root/Iryna_Karmazina/server/n8n/update.sh            — на latest
#          bash ... 1.62.4                                            — на конкретну
#          bash ... --rollback                                        — відкат вручну
set -u

DATA="/root/n8n-data"
BACKUPS="$DATA/.backups"
KEEP_DAYS=30
TARGET="${1:-latest}"

die(){ echo "СТОП: $*"; exit 1; }
health(){ curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:5678/healthz 2>/dev/null || echo 000; }

[ -f "$DATA/.env" ] || die "немає $DATA/.env — n8n ще не встановлено"
mkdir -p "$BACKUPS"
cd "$DATA" || die "немає $DATA"

CUR=$(docker inspect --format '{{.Config.Image}}' n8n 2>/dev/null | sed 's/.*://')
[ -n "$CUR" ] || CUR="latest"
echo "зараз працює версія: $CUR"

if [ "$TARGET" = "--rollback" ]; then
  LAST=$(ls -1t "$BACKUPS"/n8n-*.tar.gz 2>/dev/null | head -1)
  [ -n "$LAST" ] || die "копій немає — відкочувати нема з чого"
  echo "відкат на копію: $(basename "$LAST")"
  docker compose --env-file .env down
  mv "$DATA/.n8n" "$DATA/.n8n.before-rollback-$(date +%Y%m%d-%H%M%S)"
  mkdir -p "$DATA/.n8n" && tar -xzf "$LAST" -C "$DATA"
  chown -R 1000:1000 "$DATA/.n8n"
  docker compose --env-file .env up -d
  sleep 10; echo "healthz: $(health)"
  exit 0
fi

echo "== 1. Резервна копія даних n8n =="
docker compose --env-file .env stop || die "не можу зупинити n8n"
STAMP=$(date +%Y%m%d-%H%M%S)
tar -czf "$BACKUPS/n8n-$STAMP.tar.gz" -C "$DATA" .n8n || die "копія не зробилась — оновлення скасовано"
echo "  копія: $BACKUPS/n8n-$STAMP.tar.gz ($(stat -c%s "$BACKUPS/n8n-$STAMP.tar.gz") б)"
echo "$STAMP	$CUR	$TARGET" >> "$DATA/UPDATE_LOG.tsv"

echo "== 2. Нова версія: $TARGET =="
sed -i "s/^N8N_VERSION=.*/N8N_VERSION=$TARGET/" .env || die "не можу оновити .env"
docker compose --env-file .env pull || { sed -i "s/^N8N_VERSION=.*/N8N_VERSION=$CUR/" .env; die "образ не завантажився"; }
docker compose --env-file .env up -d

echo "== 3. Перевірка =="
OK=0
for i in $(seq 1 12); do
  sleep 5
  C=$(health)
  echo "  спроба $i: healthz=$C"
  [ "$C" = "200" ] && { OK=1; break; }
done

if [ "$OK" = "1" ]; then
  echo "== ГОТОВО: n8n працює на версії $TARGET =="
  # прибирання СТАРИХ КОПІЙ n8n і тільки їх: суворий шаблон імені + вік
  find "$BACKUPS" -maxdepth 1 -type f -name 'n8n-20*.tar.gz' -mtime +$KEEP_DAYS -print -delete
  exit 0
fi

echo "== ⚠️ НЕ ПІДНЯЛОСЬ. Автоматичний відкат на $CUR =="
docker logs n8n --tail 30
sed -i "s/^N8N_VERSION=.*/N8N_VERSION=$CUR/" .env
docker compose --env-file .env down
rm -rf "$DATA/.n8n.failed-$STAMP"; mv "$DATA/.n8n" "$DATA/.n8n.failed-$STAMP"
mkdir -p "$DATA/.n8n" && tar -xzf "$BACKUPS/n8n-$STAMP.tar.gz" -C "$DATA"
chown -R 1000:1000 "$DATA/.n8n"
docker compose --env-file .env up -d
sleep 10
echo "після відкату healthz: $(health)"
echo "невдала версія збережена в $DATA/.n8n.failed-$STAMP — НЕ видалено"
exit 1
