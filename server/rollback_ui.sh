#!/bin/bash
# Швидкий відкат фасаду на попередню версію з бекапів deploy_ui.sh.
#
# Запуск (на сервері):
#   bash /root/Iryna_Karmazina/server/rollback_ui.sh          — показати, що є
#   bash /root/Iryna_Karmazina/server/rollback_ui.sh 1        — відкотити на 1 крок назад
#   bash /root/Iryna_Karmazina/server/rollback_ui.sh index-20260802-044300.html
#
# Нічого не видаляє: поточна версія перед відкатом теж лягає в бекапи.
#
# ⚠️ ПРО МОДУЛІ (з 13.08.2026). Цей скрипт повертає ЛИШЕ index.html. Досі цього
# вистачало, бо весь код сидів усередині нього. Тепер частина коду живе у
# www/app/*.js, і тут можливі два випадки:
#   • відкат на версію ДО переїзду — усе гаразд: та index.html самодостатня,
#     файли в app/ просто лишаться лежати без діла;
#   • відкат на версію ПІСЛЯ переїзду — index.html повернеться стара, а модулі
#     в app/ лишаться НОВІ. Це різні покоління, і сторінка може повестись дивно.
# Тому для другого випадку відкочувати треба ще й модулі — вони лежать у
# .backups під іменами app-<файл>-<час>.bak (їх кладе deploy_ui.sh).
# Автоматично цього тут ПОКИ не робиться свідомо: краще хай людина побачить
# попередження, ніж скрипт мовчки поверне половину.
set -u
WWW="${WWW:-/root/unitex-os-www}"
BACKUPS="$WWW/.backups"

ls -1t "$BACKUPS"/index-*.html >/dev/null 2>&1 || { echo "бекапів немає — deploy_ui.sh ще не запускався"; exit 1; }

if [ $# -eq 0 ]; then
  echo "Наявні версії (найновіша зверху):"
  i=0
  for f in $(ls -1t "$BACKUPS"/index-*.html); do
    i=$((i+1))
    printf "  %s  %s  %8s б  %s\n" "$i" "$(basename "$f")" "$(stat -c%s "$f")" \
      "$(grep -o 'id="buildstamp"[^>]*>[^<]*' "$f" | sed 's/.*>//')"
  done
  echo
  echo "Зараз на сервері: $(stat -c%s "$WWW/index.html") б · $(grep -o 'id="buildstamp"[^>]*>[^<]*' "$WWW/index.html" | sed 's/.*>//')"
  echo "Відкат: bash $0 <номер|імʼя файлу>"
  exit 0
fi

ARG="$1"
if [[ "$ARG" =~ ^[0-9]+$ ]]; then
  SRC="$(ls -1t "$BACKUPS"/index-*.html | sed -n "${ARG}p")"
else
  SRC="$BACKUPS/$(basename "$ARG")"
fi
[ -f "${SRC:-}" ] || { echo "не знайшла таку версію"; exit 1; }

cp -p "$WWW/index.html" "$BACKUPS/index-$(date +%Y%m%d-%H%M%S)-before-rollback.html"
cp "$SRC" "$WWW/index.html"
echo "відкочено на $(basename "$SRC") · $(stat -c%s "$WWW/index.html") б · $(grep -o 'id="buildstamp"[^>]*>[^<]*' "$WWW/index.html" | sed 's/.*>//')"
echo "$(date -Is)	ROLLBACK	$(basename "$SRC")" >> "$WWW/DEPLOY_LOG.tsv"
IP="$(curl -s -4 --max-time 10 ifconfig.me || true)"
[ -n "$IP" ] && echo "UI $(curl -sk -o /dev/null -w '%{http_code}' "https://$IP/")"
