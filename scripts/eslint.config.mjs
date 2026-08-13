/* Конфіг лише для однієї мети: ловити звернення до неіснуючих змінних (no-undef).
   Стиль коду не перевіряємо — це не про красу, це про те, щоб сторінка не падала.

   ДВА БЛОКИ, і це важливо:
   1) `facade.js` — сюди `check_facade.sh` склеює код, вбудований прямо в HTML
      (<script>…</script>). Він живе в одному спільному просторі імен, тому
      sourceType:"script" і всі назви видно одна одній.
   2) `app/**` — файли-модулі. Тут sourceType:"module", і саме через це перевірка
      стає СУВОРІШОЮ: кожен файл бачить лише те, що сам імпортував. Забув
      `import { api } from "./core.js"` — no-undef скаже про це одразу, ще до
      браузера. Заради цього ми на модулі й переходимо.
   Обидва блоки лишаються, поки код живе і там, і там. */
const BROWSER = {
  window: "readonly", document: "readonly", console: "readonly",
  localStorage: "readonly", sessionStorage: "readonly", location: "readonly",
  history: "readonly", navigator: "readonly", fetch: "readonly",
  setTimeout: "readonly", clearTimeout: "readonly",
  setInterval: "readonly", clearInterval: "readonly",
  requestAnimationFrame: "readonly", getComputedStyle: "readonly",
  MutationObserver: "readonly", Event: "readonly", DOMParser: "readonly",
  alert: "readonly", confirm: "readonly", prompt: "readonly",
  FormData: "readonly", Blob: "readonly", FileReader: "readonly", URL: "readonly",
  atob: "readonly", btoa: "readonly", Intl: "readonly",
  /* Chart.js підключається звичайним <script> і живе глобально — модулі
     звертаються до нього як до глобального імені, і це нормально. */
  Chart: "readonly", crypto: "readonly", Uint32Array: "readonly",
};

export default [
  {
    files: ["facade.js"],
    languageOptions: { ecmaVersion: 2022, sourceType: "script", globals: BROWSER },
    rules: { "no-undef": "error" },
  },
  {
    files: ["app/**/*.js"],
    languageOptions: { ecmaVersion: 2022, sourceType: "module", globals: BROWSER },
    rules: { "no-undef": "error" },
  },
];
