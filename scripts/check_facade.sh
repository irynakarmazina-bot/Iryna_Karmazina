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
cp "$ROOT/scripts/eslint.config.mjs" "$WORK/eslint.config.mjs"
if command -v eslint >/dev/null 2>&1; then
  ( cd "$WORK" && eslint facade.js ) || fail=1
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
# 14.08.2026 скрипт фасаду винесено з index.html у www/app/main.js. Перевірка
# синтаксису вище дивиться лише на ВБУДОВАНІ <script> у сторінці, тобто про
# головний модуль вона не знає нічого. Без цього кроку зламаний main.js
# проходив би шлюз, а сторінка падала б у користувачки.
MAINJS="$(dirname "$FILE")/app/main.js"
if [ -f "$MAINJS" ]; then
  if node --check "$MAINJS" 2>/tmp/mainjs.err; then
    echo "  ok   синтаксис www/app/main.js ($(wc -l < "$MAINJS") рядків)"
  else
    echo "  FAIL синтаксис www/app/main.js:"; head -3 /tmp/mainjs.err; fail=1
  fi
else
  echo "  УВАГА: www/app/main.js не знайдено поруч із $FILE"
fi

# Playwright шукаємо і в стандартних шляхах, і там, де він реально стоїть у
# середовищі сесій (/opt/node22/...). Причина: 14.08.2026 шлюз тут мовчки
# сказав «браузер не знайдено» і пропустив НАЙСИЛЬНІШІ перевірки (smoke/cols/
# stale/findash) — при тому, що Chromium був на місці. Тобто шлюз відповів
# «CHECK_OK», перевіривши лише синтаксис. Мовчазний пропуск перевірки гірший
# за її відсутність: він створює хибну впевненість.
if [ -z "${PW:-}" ] && [ -d /opt/node22/lib/node_modules/playwright ]; then
  export PW=/opt/node22/lib/node_modules/playwright
fi
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
  node "$ROOT/scripts/truck.js" "$FILE" || fail=1
  # contdates.js — «Дати по контейнерах» у картці угоди (2+ контейнери), 31.08.2026
  node "$ROOT/scripts/contdates.js" "$FILE" || fail=1
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
