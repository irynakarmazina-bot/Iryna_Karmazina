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
if node -e "require.resolve(process.env.PW || 'playwright')" >/dev/null 2>&1; then
  node "$ROOT/scripts/smoke.js" "$FILE" || fail=1
else
  echo "УВАГА: браузер (playwright) не знайдено — перевірку сторінок у браузері пропущено"
  echo "       це НЕ помилка: крок доступний там, де встановлено playwright + Chromium"
fi

[ "$fail" = 0 ] && echo "CHECK_OK — фасад можна викладати" || echo "CHECK_FAIL — НЕ викладати"
exit "$fail"
