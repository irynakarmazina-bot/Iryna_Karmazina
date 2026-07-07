# Журнал вікі

Append-only. Формат: `## [YYYY-MM-DD] дія — опис`.

## [2026-07-07] init — Фаза A: створено вікі, засіяно з MEMORY.md
- Створено каркас `wiki/`: README (схема), overview, index, log, raw/.
- Проєкти: bot, finzvit, dyspetcheryzatsiya, 1c-api.
- Методики: zamorozheno-v-ugodah, dso-dpo, likvidnist-po-kasah, kasovyy-rozryv, mapping-1c.
- Сутності: klienty, postachalnyky, kasy.
- Джерело засіву: MEMORY.md (постійний блок + журнал сесій). MEMORY.md не змінювався.
- Рівень 1 (ручний). Автоматизація і health-check — наступні фази, не ввімкнені.

## [2026-07-07] arch — гібрид з Notion
- Виявлено: у Notion уже є «UNITEX | База знань» з темами (Морський фрахт, Локальні витрати,
  Наземна доставка, Коносаменти, Шаблони документів, Т1 Вімгарант).
- Рішення користувача: ГІБРИД. Notion = бізнес-довідка + нотатки (ти/бот); репо wiki/ = методики + техдокументація.
- Додано [[baza-znan]]; оновлено overview, index, README. Саму Notion не змінювали.
