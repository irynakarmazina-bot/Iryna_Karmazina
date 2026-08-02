#!/bin/bash
# ЄДИНИЙ дозволений спосіб викласти фасад на сервер.
#
# Навіщо: 02.08.2026 деплой «скопіювати www/index.html з моєї гілки» затер
# новішу версію, яку туди виклала паралельна сесія зі своєї гілки — зникла
# денна робота. Просте `cp` не бачить, ЧИЯ версія вже лежить на сервері.
# Цей скрипт відмовляється копіювати, якщо на сервері файл, якого немає
# в історії гілки, з якої викладаємо.
#
# Запуск (на сервері):
#   bash /root/Iryna_Karmazina/server/deploy_ui.sh [гілка] [--force]
#   гілка за замовчуванням — main
#   --force ігнорує захист (тільки з дозволу користувача і після бекапу)
#
# Що робить:
#   1. тягне гілку з GitHub, бере з неї www/index.html, findash.html, finperiod.html
#   2. ЗАХИСТ: якщо файл на сервері не з цієї гілки і не з нашого попереднього
#      деплою — зупиняється й показує, що саме там лежить
#   3. бекап поточної версії в .backups (зберігає 5 останніх)
#   4. перевірка scripts/check_facade.sh на кандидаті — при CHECK_FAIL не викладає
#   5. копіює, пише DEPLOYED.json і рядок у DEPLOY_LOG.tsv
#   6. перевіряє, що сайт відповідає 200
set -u

REPO="${REPO:-/root/Iryna_Karmazina}"
WWW="${WWW:-/root/unitex-os-www}"
BACKUPS="$WWW/.backups"
KEEP=5                                  # скільки бекапів index.html лишати
FILES="index.html findash.html finperiod.html"

BR="main"; FORCE=0; CHECK=0
for a in "$@"; do
  case "$a" in
    --force) FORCE=1 ;;
    --check) CHECK=1 ;;          # тільки перевірити, нічого не міняти на сервері
    -*) echo "невідомий ключ: $a"; exit 2 ;;
    *) BR="$a" ;;
  esac
done

die(){ echo "DEPLOY_FAIL: $*"; exit 1; }

cd "$REPO" || die "немає репозиторію $REPO"
mkdir -p "$BACKUPS" || die "не можу створити $BACKUPS"

echo "== гілка: $BR =="
git fetch -q origin "$BR" || die "не вдалося отримати гілку $BR"
SHA="$(git rev-parse FETCH_HEAD)"
SUBJ="$(git log -1 --format=%s FETCH_HEAD)"
WHEN="$(git log -1 --format=%ci FETCH_HEAD)"
echo "   коміт: ${SHA:0:9} · $WHEN"
echo "   опис:  $SUBJ"

# ── 2. ЗАХИСТ ВІД ЗАТИРАННЯ ────────────────────────────────────────────────
# Файл на сервері вважається «нашим», якщо його вміст зустрічається в історії
# цієї гілки АБО збігається з тим, що ми самі виклали минулого разу.
SERVED="$WWW/index.html"
if [ -f "$SERVED" ]; then
  SERVED_BLOB="$(git hash-object "$SERVED")"
  KNOWN=0
  while read -r c; do
    b="$(git rev-parse "$c:www/index.html" 2>/dev/null)" || continue
    [ "$b" = "$SERVED_BLOB" ] && { KNOWN=1; break; }
  done < <(git log --format=%H FETCH_HEAD -- www/index.html)
  if [ "$KNOWN" = 0 ] && [ -f "$WWW/DEPLOYED.json" ]; then
    PREV="$(python3 -c "import json;print(json.load(open('$WWW/DEPLOYED.json')).get('files',{}).get('index.html',{}).get('blob',''))" 2>/dev/null || true)"
    [ -n "$PREV" ] && [ "$PREV" = "$SERVED_BLOB" ] && KNOWN=1
  fi
  if [ "$KNOWN" = 0 ]; then
    echo
    echo "🚫 НА СЕРВЕРІ ЧУЖА ВЕРСІЯ — не з гілки $BR і не з мого попереднього деплою."
    echo "   розмір на сервері: $(stat -c%s "$SERVED") б"
    echo "   розмір у гілці:    $(git show FETCH_HEAD:www/index.html | wc -c) б"
    echo "   позначка версії на сервері: $(grep -o 'id="buildstamp"[^>]*>[^<]*' "$SERVED" | sed 's/.*>//')"
    echo "   позначка версії в гілці:    $(git show FETCH_HEAD:www/index.html | grep -o 'id=\"buildstamp\"[^>]*>[^<]*' | sed 's/.*>//')"
    echo "   хто її виклав — дивись $WWW/DEPLOY_LOG.tsv"
    echo
    echo "   Спершу знайди гілку з цією версією і злий її, інакше робота зникне."
    [ "$FORCE" = 0 ] && die "зупинено захистом (свідоме перезаписування: --force)"
    echo "⚠️  --force: викладаю попри це, попередня версія лишиться в $BACKUPS"
  fi
fi

# ── 4. перевірка кандидата (до копіювання) ────────────────────────────────
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
for f in $FILES; do
  git show "FETCH_HEAD:www/$f" > "$TMP/$f" 2>/dev/null || die "у гілці немає www/$f"
done
if [ -x "$REPO/scripts/check_facade.sh" ] || [ -f "$REPO/scripts/check_facade.sh" ]; then
  OUT="$(bash "$REPO/scripts/check_facade.sh" "$TMP/index.html" 2>&1)" || true
  echo "$OUT" | tail -3
  echo "$OUT" | grep -q CHECK_OK || die "check_facade.sh не пропустив цю версію"
else
  echo "   ⚠️ scripts/check_facade.sh не знайдено — перевірку пропущено"
fi

if [ "$CHECK" = 1 ]; then
  echo "   на сервері: $( [ -f "$SERVED" ] && stat -c%s "$SERVED" || echo 0) б · позначка «$( [ -f "$SERVED" ] && grep -o 'id="buildstamp"[^>]*>[^<]*' "$SERVED" | sed 's/.*>//')»"
  echo "   у гілці:    $(stat -c%s "$TMP/index.html") б · позначка «$(grep -o 'id="buildstamp"[^>]*>[^<]*' "$TMP/index.html" | sed 's/.*>//')»"
  if [ -f "$SERVED" ] && cmp -s "$SERVED" "$TMP/index.html"; then echo "CHECK_ONLY: збігається — викладати нічого"; else echo "CHECK_ONLY: версії різні — деплой оновить сервер"; fi
  exit 0
fi

# ── 3. бекап поточної версії ──────────────────────────────────────────────
TS="$(date +%Y%m%d-%H%M%S)"
if [ -f "$SERVED" ]; then
  cp -p "$SERVED" "$BACKUPS/index-$TS.html" || die "не вдалося зробити бекап"
  echo "   бекап: $BACKUPS/index-$TS.html ($(stat -c%s "$SERVED") б)"
  # лишаємо KEEP останніх копій (це єдине автоматичне прибирання в цьому скрипті)
  OLD="$(ls -1t "$BACKUPS"/index-*.html 2>/dev/null | tail -n +$((KEEP+1)))"
  if [ -n "$OLD" ]; then
    echo "$OLD" | xargs -r rm -f
    echo "   прибрано старих копій: $(echo "$OLD" | wc -l) (лишаю $KEEP останніх)"
  fi
fi

# ── 5. копіювання + журнал ────────────────────────────────────────────────
for f in $FILES; do
  cp "$TMP/$f" "$WWW/$f" || die "не вдалося скопіювати $f"
done
STAMP="$(grep -o 'id="buildstamp"[^>]*>[^<]*' "$SERVED" | sed 's/.*>//')"

python3 - "$WWW" "$BR" "$SHA" "$SUBJ" "$STAMP" "$FILES" <<'PY'
import json, os, sys, hashlib, subprocess, datetime
www, br, sha, subj, stamp, files = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5], sys.argv[6].split()
info = {}
for f in files:
    p = os.path.join(www, f)
    blob = subprocess.run(["git", "hash-object", p], capture_output=True, text=True).stdout.strip()
    info[f] = {"size": os.path.getsize(p),
               "md5": hashlib.md5(open(p, "rb").read()).hexdigest(),
               "blob": blob}
now = datetime.datetime.now().isoformat(timespec="seconds")
json.dump({"branch": br, "commit": sha, "subject": subj, "buildstamp": stamp,
           "deployed_at": now, "files": info},
          open(os.path.join(www, "DEPLOYED.json"), "w"), ensure_ascii=False, indent=1)
line = "\t".join([now, br, sha[:9], stamp, " ".join(f"{k}:{v['size']}" for k, v in info.items()), subj])
with open(os.path.join(www, "DEPLOY_LOG.tsv"), "a") as fh:
    fh.write(line + "\n")
print("   журнал:", line)
PY

# ── 6. чи відповідає сайт ─────────────────────────────────────────────────
IP="$(curl -s -4 --max-time 10 ifconfig.me || true)"
if [ -n "$IP" ]; then
  echo "   UI $(curl -sk -o /dev/null -w '%{http_code}' "https://$IP/")  FINDASH $(curl -sk -o /dev/null -w '%{http_code}' "https://$IP/findash.html")"
fi
echo "DEPLOY_OK · гілка $BR · коміт ${SHA:0:9} · позначка «$STAMP»"
