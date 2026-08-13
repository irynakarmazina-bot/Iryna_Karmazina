#!/bin/bash
# ОБОВ'ЯЗКОВО перед кожним викладенням www/index.html на сервер.
#
# Навіщо: 01.08.2026 три рядки з «Налаштувань» випадково опинилися в кінці
# PAGES.finance. Змінні `isAdmin` і `rows` там не існують, тому сторінка
# «Фінанси» падала з «Can't find variable: isAdmin». Синтаксис при цьому був
# коректний, тому `node --check` мовчав, і помилку знайшла користувачка.
# Ця перевірка ловить саме такий випадок: на версії до виправлення вона дає
# 2 помилки, після виправлення — жодної.
#
# Запуск: bash scripts/check_facade.sh [шлях/до/index.html]
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
FILE="${1:-$ROOT/www/index.html}"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
fail=0

# 1. синтаксис кожного <script>
node -e '
const fs=require("fs");
const h=fs.readFileSync(process.argv[1],"utf8");
const m=[...h.matchAll(/<script[^>]*>([\s\S]*?)<\/script>/g)];
let out="", bad=0;
for (const s of m){ try{ new Function(s[1]); }catch(e){ bad++; console.log("СИНТАКСИС: "+e.message.slice(0,140)); } out+=s[1]+"\n"; }
fs.writeFileSync(process.argv[2], out);
console.log("скриптів: "+m.length+", із синтаксичними помилками: "+bad);
process.exit(bad?1:0);
' "$FILE" "$WORK/facade.js" || fail=1

# 2. звернення до неіснуючих змінних — те, що впустило «Фінанси»
#    Від 13.08.2026 код живе не лише в <script> усередині HTML, а й у модулях
#    www/app/*.js. Їх треба перевіряти ОБОВ'ЯЗКОВО: у модулі кожен файл бачить
#    лише те, що сам імпортував, тому забутий import — це саме той випадок, який
#    ця перевірка й ловить. Якщо модулі сюди не додати, шлюз мовчки осліпне на
#    4/5 коду (у самому index.html лишиться майже нічого).
cp "$ROOT/scripts/eslint.config.mjs" "$WORK/eslint.config.mjs"
APPDIR="$(dirname "$FILE")/app"
if [ -d "$APPDIR" ]; then
  mkdir -p "$WORK/app" && cp "$APPDIR"/*.js "$WORK/app/" 2>/dev/null
  echo "модулів у app/: $(ls -1 "$APPDIR"/*.js 2>/dev/null | wc -l)"
  # Синтаксис модулів. Крок 1 (new Function) їх перевірити НЕ може: import/export
  # там не вираз, і він би сам упав. Питаємо node у режимі модуля.
  for m in "$APPDIR"/*.js; do
    if ! out=$(node --input-type=module --check < "$m" 2>&1); then
      echo "СИНТАКСИС $(basename "$m"): $(echo "$out" | head -2 | tr '\n' ' ')"
      fail=1
    fi
  done
else
  echo "теки app/ немає — перевіряю лише вбудований код"
fi
if command -v eslint >/dev/null 2>&1; then
  ( cd "$WORK" && eslint facade.js $( [ -d "$WORK/app" ] && echo "app" ) ) || fail=1
else
  echo "УВАГА: eslint не знайдено — перевірку на неіснуючі змінні ПРОПУЩЕНО"
  fail=1
fi

# 3. справжній браузер: відкрити КОЖНУ сторінку і подивитись, чи вона жива.
#    Кроки 1-2 читають код, а цей — запускає його. Саме він ловить те, що
#    видно лише під час роботи (сторінка відкрилась, але впала на даних).
#    Потребує playwright + Chromium. На VPS їх зазвичай немає — тоді крок
#    ЧЕСНО пропускається і НЕ валить деплой (інакше з сервера нічого не
#    викласти). У сесії Клода браузер є — там ця перевірка виконується.
#    Додано 07.08.2026: разом зі smoke.js тут тепер ганяються cols.js і stale.js.
#    Причина — аудит 07.08.2026 довів це експериментом, а не міркуванням: обидві
#    поломки 05.08 (обрізані номери коносаментів; «Статус» за краєм екрана) були
#    відтворені на копіях файла і прогнані через цей самий шлюз. smoke.js сказав
#    SMOKE_OK, весь check_facade.sh сказав «CHECK_OK — фасад можна викладати»,
#    тобто ОБИДВІ поломки доїхали б до користувачки. cols.js обидві зловив.
#    Перевірка існувала, але до дверей під'єднана не була.
if node -e "require.resolve(process.env.PW || 'playwright')" >/dev/null 2>&1; then
  node "$ROOT/scripts/smoke.js" "$FILE" || fail=1
  # cols.js і stale.js ОБОВ'ЯЗКОВО з аргументом "$FILE": без нього вони дивляться
  # на www/index.html у репозиторії, а deploy_ui.sh дає сюди кандидата з гілки.
  node "$ROOT/scripts/cols.js"  "$FILE" || fail=1
  node "$ROOT/scripts/stale.js" "$FILE" || fail=1
  # tasks.js — розділ «Задачі». Додано 12.08.2026 разом із самим розділом.
  # smoke.js тільки ВІДКРИВАЄ сторінки, а тут людина натискає кнопки: створює
  # задачу, закриває її, перемикає фільтри. Без цього кроку зламана форма або
  # загублені виконавці проходили б шлюз непоміченими.
  node "$ROOT/scripts/tasks.js" "$FILE" || fail=1
  # corner.js — куточки-коментарі й позначка «оновлено» в диспетчеризації (13.08.2026)
  node "$ROOT/scripts/corner.js" "$FILE" || fail=1
  # findash.js — плитка «Усього в обороті» у фінансовому дашборді. Окремий файл
  # (www/findash.html), тому «$FILE» їй не підходить: беремо сусідній файл із тієї
  # самої теки, що й кандидат на викладення.
  [ -f "$(dirname "$FILE")/findash.html" ] && { node "$ROOT/scripts/findash.js" "$(dirname "$FILE")/findash.html" || fail=1; }
else
  echo "УВАГА: браузер (playwright) не знайдено — перевірки сторінок, ширин колонок"
  echo "       і позначки «застаріло» у браузері ПРОПУЩЕНО (smoke.js, cols.js, stale.js)"
  echo "       це НЕ помилка: крок доступний там, де встановлено playwright + Chromium"
  echo "       ⚠️ на VPS браузера немає, тому деплой З СЕРВЕРА перевіряє лише синтаксис"
  echo "       і звернення до змінних. Вигляд сторінки там не перевіряє ніхто."
  echo "       (сюди ж не потрапляє tasks.js — перевірка розділу «Задачі»)"
fi

[ "$fail" = 0 ] && echo "CHECK_OK — фасад можна викладати" || echo "CHECK_FAIL — НЕ викладати"
exit "$fail"
