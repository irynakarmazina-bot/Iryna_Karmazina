#!/bin/bash
# Оновлює позначку версії в бічному меню фасада. Запускати ПЕРЕД викладенням,
# щоб по сторінці було видно, чи браузер підтягнув свіжий файл (інакше «не бачу
# нову колонку» = кеш, і ми обидві гадаємо).
set -eu
F="${1:-$(cd "$(dirname "$0")/.." && pwd)/www/index.html}"
NEW="в. $(date +'%d.%m %H:%M')"
python3 - "$F" "$NEW" <<'PY'
import re, sys
p, new = sys.argv[1], sys.argv[2]
s = open(p, encoding='utf-8').read()
pat = re.compile(r'(<div class="buildstamp" id="buildstamp"[^>]*>)([^<]*)(</div>)')
m = pat.search(s)
if not m:                      # саме відсутність позначки — помилка,
    sys.exit('НЕ знайдено позначку версії у %s' % p)   # а не «значення не змінилось»
open(p, 'w', encoding='utf-8').write(pat.sub(lambda x: x.group(1) + new + x.group(3), s, count=1))
print('позначка версії: ' + new)
PY
