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
#   3. бекап у .backups УСІХ файлів, що викладаються, плюс кабінету клієнтів;
#      копії зберігаються 14 днів (за часом, а не «5 останніх штук»)
#   4. перевірка scripts/check_facade.sh на кандидаті — при CHECK_FAIL не викладає
#   5. копіює, пише DEPLOYED.json і рядок у DEPLOY_LOG.tsv
#   6. перевіряє, що сайт відповідає 200
set -u

REPO="${REPO:-/root/Iryna_Karmazina}"
WWW="${WWW:-/root/unitex-os-www}"
BACKUPS="$WWW/.backups"
KEEP_DAYS=14                            # скільки ДНІВ зберігати бекапи (не «скільки штук»)
FILES="index.html findash.html finperiod.html"
# Файли, які теж треба класти на сервер, але це НЕ сторінки (не .html).
# chart.min.js доданий 07.08.2026. Дві причини, обидві перевірені:
#   1. index.html підключає його рядком <script src="/chart.min.js">, але сам
#      файл цим скриптом не викладався ніколи — зміна в репозиторії на сервер
#      штатним шляхом не доїжджала;
#   2. без нього перевірка smoke.js на КАНДИДАТІ падала з «немає файла поруч з
#      index.html: chart.min.js» — тобто на справному фасаді. На сервері це не
#      спливало лише тому, що там немає playwright і крок пропускається. Варто
#      було б колись поставити браузер на VPS — і жоден деплой не пройшов би.
ASSETS="chart.min.js"
# Модулі фасада (www/app/*.js), з 13.08.2026. Раніше весь код сидів усередині
# index.html; тепер він переїжджає у файли-модулі, і кожен новий файл ТРЕБА
# викласти — інакше сторінка на сервері мовчки лишиться без коду. Тому перелік
# не зашитий руками, а читається з самої гілки: додали модуль — він поїде сам.
MODDIR="app"
# Файли, які цей скрипт НЕ викладає, але зобов'язаний зберегти перед викладенням.
# Кабінет клієнтів збирається окремо (client_cabinet/build_preview.py), проте
# лежить у тій самій теці й може постраждати — тому копію робимо і з нього.
EXTRA_BACKUP="cabinet.html"

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
for f in $FILES $ASSETS; do
  git show "FETCH_HEAD:www/$f" > "$TMP/$f" 2>/dev/null || die "у гілці немає www/$f"
done
# Модулі: перелік беремо з гілки, а не з рук. Порожній перелік — не помилка
# (так було до 13.08.2026), просто нічого не викладаємо.
MODULES="$(git ls-tree --name-only "FETCH_HEAD:www/$MODDIR" 2>/dev/null | grep '\.js$' || true)"
if [ -n "$MODULES" ]; then
  mkdir -p "$TMP/$MODDIR"
  for m in $MODULES; do
    git show "FETCH_HEAD:www/$MODDIR/$m" > "$TMP/$MODDIR/$m" 2>/dev/null \
      || die "у гілці немає www/$MODDIR/$m"
  done
  echo "   модулів у гілці: $(echo "$MODULES" | wc -w) ($(echo $MODULES | tr '\n' ' '))"
fi
if [ -x "$REPO/scripts/check_facade.sh" ] || [ -f "$REPO/scripts/check_facade.sh" ]; then
  OUT="$(bash "$REPO/scripts/check_facade.sh" "$TMP/index.html" 2>&1)" || true
  echo "$OUT" | tail -3
  echo "$OUT" | grep -q CHECK_OK || die "check_facade.sh не пропустив цю версію"
else
  echo "   ⚠️ scripts/check_facade.sh не знайдено — перевірку пропущено"
fi

# ── 4б. КЛЮЧ ВЕРСІЇ ДО МОДУЛІВ (інакше браузер тримає старий код) ──────────
# Навіщо, знайдено 18.08.2026. Виправлення посилань на файли доїхало на сервер
# (перевірено: файл на сервері й той, що віддає Caddy, містять новий код,
# md5 збігається), а користувачка бачила стару поведінку. Причина: сторінка
# посилалась на /app/main.js БЕЗ жодної позначки версії, а Caddy на статику не
# віддає Cache-Control — лише etag і last-modified. Тому браузер має право
# віддавати збережену копію модуля зі свого кешу, не питаючи сервер. Для
# <script type="module"> перезавантаження сторінки (навіть Ctrl+F5) не завжди
# оновлює вже завантажений модуль. Виходило найгірше: деплой каже DEPLOY_OK,
# на сервері новий код, а в людини виконується старий, і жодна перевірка цього
# не бачить, бо всі вони дивляться на сервер, а не в чужий браузер.
# Що робимо: у ВИКЛАДЕНІЙ index.html дописуємо до кожного модуля ?v=<хеш вмісту>.
# Змінився модуль — змінився хеш — змінилась адреса — браузер ЗОБОВ'ЯЗАНИЙ
# завантажити його заново. Не змінився — адреса та сама, кеш працює як треба.
# Хеш беремо від самого файла, а не від часу: тоді повторний деплой без змін
# не змушує всіх качати код наново.
if [ -n "${MODULES:-}" ]; then
  for m in $MODULES; do
    v="$(sha1sum "$TMP/$MODDIR/$m" | cut -c1-10)"
    python3 - "$TMP/index.html" "/$MODDIR/$m" "$v" <<'PY'
import re, sys
page, src, ver = sys.argv[1], sys.argv[2], sys.argv[3]
html = open(page, encoding="utf-8").read()
# ловимо і "/app/main.js", і "/app/main.js?v=старий" — щоб ключ оновлювався, а не множився
pat = re.compile(r'(src=")' + re.escape(src) + r'(\?v=[0-9a-f]+)?(")')
html, n = pat.subn(lambda mo: mo.group(1) + src + "?v=" + ver + mo.group(3), html)
open(page, "w", encoding="utf-8").write(html)
print(f"   ключ версії {src}?v={ver} · замін у сторінці: {n}")
PY
  done
fi

if [ "$CHECK" = 1 ]; then
  echo "   на сервері: $( [ -f "$SERVED" ] && stat -c%s "$SERVED" || echo 0) б · позначка «$( [ -f "$SERVED" ] && grep -o 'id="buildstamp"[^>]*>[^<]*' "$SERVED" | sed 's/.*>//')»"
  echo "   у гілці:    $(stat -c%s "$TMP/index.html") б · позначка «$(grep -o 'id="buildstamp"[^>]*>[^<]*' "$TMP/index.html" | sed 's/.*>//')»"
  if [ -f "$SERVED" ] && cmp -s "$SERVED" "$TMP/index.html"; then echo "CHECK_ONLY: збігається — викладати нічого"; else echo "CHECK_ONLY: версії різні — деплой оновить сервер"; fi
  exit 0
fi

# ── 3. бекап поточної версії ──────────────────────────────────────────────
# Змінено 03.08.2026 на прохання користувачки: бекапи міряються ЧАСОМ, а не
# кількістю. Було «лишаю 5 останніх» — при трьох викладеннях на день це давало
# менше двох діб на те, щоб помітити поломку і відкотитись. Тепер 14 днів.
# Бекапляться ВСІ файли, які викладаємо, плюс кабінет клієнтів: раніше під
# захистом був лише index.html, а кабінет не мав жодної копії — і вже одного
# разу «схуд» з 208 до 149 КБ без можливості відкату.
TS="$(date +%Y%m%d-%H%M%S)"
for f in $FILES $EXTRA_BACKUP; do
  src="$WWW/$f"
  [ -f "$src" ] || continue
  cp -p "$src" "$BACKUPS/${f%.html}-$TS.html" || die "не вдалося зробити бекап $f"
  echo "   бекап: ${f%.html}-$TS.html ($(stat -c%s "$src") б)"
done
# Не-html файли бекапимо під власним іменем із суфіксом .bak — інакше
# ${f%.html} лишив би «chart.min.js-<час>.html», тобто js під виглядом сторінки.
for f in $ASSETS; do
  src="$WWW/$f"
  [ -f "$src" ] || continue
  cp -p "$src" "$BACKUPS/$f-$TS.bak" || die "не вдалося зробити бекап $f"
  echo "   бекап: $f-$TS.bak ($(stat -c%s "$src") б)"
done
# Прибирання СТРОГО за віком. Файли -before-rollback не чіпаємо ніколи: це
# останній слід того, що було до відкату, і саме він потрібен, коли відкат
# виявився помилкою.
OLD="$(find "$BACKUPS" -maxdepth 1 \( -name '*.html' -o -name '*.bak' \) \
        ! -name '*-before-rollback.html' -mtime +$KEEP_DAYS 2>/dev/null)"
if [ -n "$OLD" ]; then
  echo "$OLD" | xargs -r rm -f
  echo "   прибрано копій, старших за $KEEP_DAYS днів: $(echo "$OLD" | wc -l)"
else
  echo "   копій, старших за $KEEP_DAYS днів, немає — нічого не прибираю"
fi
echo "   усього копій у архіві: $(ls -1 "$BACKUPS"/*.html 2>/dev/null | wc -l)"

# Модулі теж бекапимо — по одному файлу, під власним іменем з часом.
if [ -n "${MODULES:-}" ] && [ -d "$WWW/$MODDIR" ]; then
  for m in $MODULES; do
    [ -f "$WWW/$MODDIR/$m" ] || continue
    cp -p "$WWW/$MODDIR/$m" "$BACKUPS/$MODDIR-$m-$TS.bak" || die "не вдалося зробити бекап $MODDIR/$m"
    echo "   бекап: $MODDIR-$m-$TS.bak ($(stat -c%s "$WWW/$MODDIR/$m") б)"
  done
fi

# ── 5. копіювання + журнал ────────────────────────────────────────────────
for f in $FILES $ASSETS; do
  cp "$TMP/$f" "$WWW/$f" || die "не вдалося скопіювати $f"
done
if [ -n "${MODULES:-}" ]; then
  mkdir -p "$WWW/$MODDIR" || die "не вдалося створити $WWW/$MODDIR"
  for m in $MODULES; do
    cp "$TMP/$MODDIR/$m" "$WWW/$MODDIR/$m" || die "не вдалося скопіювати $MODDIR/$m"
    cmp -s "$TMP/$MODDIR/$m" "$WWW/$MODDIR/$m" \
      || die "після копіювання $MODDIR/$m на сервері відрізняється від кандидата"
  done
  echo "   викладено модулів: $(echo "$MODULES" | wc -w)"
fi
# ⚠️ ЗВІРКА, ЯКОЇ НЕ БУЛО і через яку 13.08.2026 платформа стояла зламана 2 хвилини.
# Що сталося: index.html уже посилався на /app/main.js, а на сервері виконувався
# ЩЕ СТАРИЙ deploy_ui.sh (autodeploy тягне репозиторій раз на хвилину, а деплой
# запустили одразу після пуша). Старий скрипт про модулі не знав, файл не
# скопіював — і Caddy на запит /app/main.js віддав `try_files … /index.html`,
# тобто саму сторінку замість коду. Сторінка відкривалась, але була без JavaScript.
# DEPLOY_OK при цьому сказав «усе добре»: він перевіряв лише HTTP 200, а 200 таки був.
# Тепер: перевіряємо, що КОЖЕН файл, на який посилається викладена сторінка,
# справді лежить на сервері й не порожній. Якщо ні — самі повертаємо попередню
# сторінку з бекапу, який щойно зробили, і падаємо з поясненням.
# Хвіст `?v=…` (див. крок 4б) відрізаємо — на диску файл лежить без нього.
# Якщо цього не зробити, grep нижче не знайде ЖОДНОГО модуля, NEEDED стане
# порожнім, і перевірка «чи всі файли доїхали» мовчки перестане щось перевіряти.
NEEDED="$(grep -oE 'src="/[A-Za-z0-9_./-]+\.js(\?v=[0-9a-f]+)?"' "$WWW/index.html" | sed 's/src="\///; s/"$//; s/?.*//' | sort -u)"
[ -n "$NEEDED" ] || die "у викладеній index.html не знайдено жодного <script src=…> — перевірка цілісності не спрацювала б"
for n in $NEEDED; do
  [ -f "$WWW/$n" ] && [ -s "$WWW/$n" ] && continue
  echo "⚠️  сторінка посилається на /$n, а такого файла на сервері немає"
  if [ -f "$BACKUPS/index-$TS.html" ]; then
    cp -p "$BACKUPS/index-$TS.html" "$WWW/index.html"
    echo "   повернула попередню index.html з бекапу index-$TS.html"
  fi
  die "нема файла /$n — викладення скасовано (сторінка була б без коду)"
done

# Звірка «доїхало те саме»: ловить обірваний cp, брак місця на диску, права.
for f in $FILES $ASSETS; do
  cmp -s "$TMP/$f" "$WWW/$f" || die "після копіювання $f на сервері відрізняється від кандидата"
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

# ── 6. чи відповідає сайт + АВТОВІДКАТ ────────────────────────────────────
# Було (до 07.08.2026): код відповіді сайту лише ДРУКУВАВСЯ. Навіть 500
# закінчувався рядком DEPLOY_OK, і зламаний фасад лишався на сервері до того
# часу, поки його не побачить користувачка. Тепер перевірка вирішує.
#
# ЩО САМЕ ЦЕ ЛОВИТЬ І ЧОГО НЕ ЛОВИТЬ — чесно:
#   ловить: сайт не віддається взагалі, сторінка не знайшлась, Caddy впав,
#           файл доїхав побитим (звірка cmp вище);
#   НЕ ловить: сторінка віддається, але виглядає не так. Вигляд перевіряється
#           ДО копіювання (check_facade.sh + smoke/cols/stale) і лише там, де
#           встановлено playwright. На VPS браузера немає.
# Відкат робиться РІВНО ОДИН РАЗ, з бекапів цього ж запуску ($TS). Циклу немає.
site_codes(){
  printf '%s %s %s' \
    "$(curl -sk -o /dev/null -w '%{http_code}' --max-time 15 "https://$1/")" \
    "$(curl -sk -o /dev/null -w '%{http_code}' --max-time 15 "https://$1/findash.html")" \
    "$(curl -sk -o /dev/null -w '%{http_code}' --max-time 15 "https://$1/chart.min.js")"
}

IP="$(curl -s -4 --max-time 10 ifconfig.me || true)"
if [ -z "$IP" ]; then
  echo "   ⚠️ не вдалося дізнатись зовнішню адресу — перевірку сайту ПРОПУЩЕНО"
  echo "      (це не «все гаразд», це «не перевірено»); відкат не робиться"
else
  CODES="$(site_codes "$IP")"
  echo "   UI/FINDASH/CHART: $CODES"
  if [ "$CODES" != "200 200 200" ]; then
    # одна повторна спроба: коротка мережева заминка не привід відкочувати
    sleep 3
    CODES="$(site_codes "$IP")"
    echo "   повторна перевірка:  $CODES"
  fi
  if [ "$CODES" != "200 200 200" ]; then
    echo "   ❌ сайт не відповідає як слід — ВІДКОЧУЮ на версію, що була до цього запуску"
    restored=""; missing=""
    for f in $FILES; do
      b="$BACKUPS/${f%.html}-$TS.html"
      if [ -f "$b" ]; then cp "$b" "$WWW/$f" && restored="$restored $f"; else missing="$missing $f"; fi
    done
    for f in $ASSETS; do
      b="$BACKUPS/$f-$TS.bak"
      if [ -f "$b" ]; then cp "$b" "$WWW/$f" && restored="$restored $f"; else missing="$missing $f"; fi
    done
    echo "$(date -Is)	AUTO-ROLLBACK	з $TS	повернуто:${restored:- нічого}	без бекапу:${missing:- —}" \
      >> "$WWW/DEPLOY_LOG.tsv"
    echo "   повернуто:${restored:- нічого}"
    [ -n "$missing" ] && echo "   ⚠️ без бекапу (їх на сервері не було до деплою):$missing"
    echo "   стан після відкату: $(site_codes "$IP")"
    echo "DEPLOY_ROLLED_BACK · гілка $BR · коміт ${SHA:0:9} · причина: сайт віддав «$CODES» замість «200 200 200»"
    exit 1
  fi
fi
echo "DEPLOY_OK · гілка $BR · коміт ${SHA:0:9} · позначка «$STAMP»"
