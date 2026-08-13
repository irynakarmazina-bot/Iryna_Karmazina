#!/usr/bin/env bash
# Шлюз перед викладенням кабінету клієнта — те саме, чим для фасаду є
# check_facade.sh. Прогнати ОБОВ'ЯЗКОВО після будь-якої правки server/cabinet.py
# або client_cabinet/build_preview.py: сторінка в них спільна.
#
# Що робить:
#   1) синтаксис усіх трьох файлів;
#   2) scripts/cabinet_test.py — 62 перевірки без браузера (вхід, чужі угоди,
#      документи, підбір пароля, журнал);
#   3) scripts/cabinet_browser.mjs — наскрізний прогін у Chromium: вхід,
#      зміна пароля, картка угоди, завантаження, вихід, помилки JS.
#
# Живої бази НЕ торкається: угоди підставлені, сховище підмінене.
# Успіх — CABINET_OK у останньому рядку. Будь-що інше — не викладати.
set -u
cd "$(dirname "$0")/.." || exit 2
FAIL=0

echo "── синтаксис ──"
for f in server/cabinet.py server/cabinet_admin.py client_cabinet/build_preview.py; do
  if python3 -m py_compile "$f" 2>/dev/null; then echo "  ok   $f"
  else echo "  FAIL $f"; python3 -m py_compile "$f"; FAIL=1; fi
done

echo
echo "── перевірки без браузера ──"
# ВАЖЛИВО: код виходу беремо з PIPESTATUS. Через `|` він губиться — grep
# повертає свій, і скрипт друкував CABINET_OK при провалених перевірках.
python3 scripts/cabinet_test.py | grep -Ev '^  ok '
[ "${PIPESTATUS[0]}" = 0 ] || FAIL=1

PORT="${CABINET_DEMO_PORT:-8899}"
if [ -x /opt/node22/bin/node ] && [ -d /opt/pw-browsers ]; then
  echo
  echo "── перевірка в браузері ──"
  # Порт має бути ВІЛЬНИЙ. Якщо на ньому вже щось висить (забутий стенд із
  # попереднього прогону), наш сервер не підніметься, а браузер мовчки
  # перевірить ЧУЖИЙ процес — і шлюз збреше. Саме так 13.08.2026 з'явився
  # «CABINET_FAIL» на коді, у якому нічого не було зламано.
  if ! python3 -c "
import socket,sys
s=socket.socket()
try: s.bind(('127.0.0.1',$PORT))
except OSError: sys.exit(1)
finally: s.close()" 2>/dev/null; then
    echo "  FAIL порт $PORT зайнятий — зупиніть старий стенд"
    echo "       (pgrep -f cabinet_fakeserver), інакше перевірка бреше"
    echo; echo "CABINET_FAIL"; exit 1
  fi
  CABINET_DEMO_PORT="$PORT" python3 scripts/cabinet_fakeserver.py >/tmp/cabfake.$$ 2>&1 &
  SRV=$!
  for _ in $(seq 20); do grep -q READY /tmp/cabfake.$$ 2>/dev/null && break; sleep 0.5; done
  CABINET_DEMO_PORT="$PORT" /opt/node22/bin/node scripts/cabinet_browser.mjs | grep -Ev '^  ok '
  [ "${PIPESTATUS[0]}" = 0 ] || FAIL=1
  kill "$SRV" 2>/dev/null
  rm -f /tmp/cabfake.$$
else
  echo
  echo "УВАГА: Chromium або node не знайдено — браузерну перевірку пропущено."
fi

echo
[ "$FAIL" = 0 ] && echo "CABINET_OK" || echo "CABINET_FAIL"
exit "$FAIL"
