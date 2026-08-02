/* Конфіг лише для однієї мети: ловити звернення до неіснуючих змінних (no-undef).
   Стиль коду не перевіряємо — це не про красу, це про те, щоб сторінка не падала. */
export default [{
  files: ["**/*.js"],
  languageOptions: {
    ecmaVersion: 2022,
    sourceType: "script",
    globals: {
      window: "readonly", document: "readonly", console: "readonly",
      localStorage: "readonly", sessionStorage: "readonly", location: "readonly",
      history: "readonly", navigator: "readonly", fetch: "readonly",
      setTimeout: "readonly", clearTimeout: "readonly",
      setInterval: "readonly", clearInterval: "readonly",
      requestAnimationFrame: "readonly", getComputedStyle: "readonly",
      MutationObserver: "readonly", Event: "readonly",
      alert: "readonly", confirm: "readonly", prompt: "readonly",
      FormData: "readonly", Blob: "readonly", FileReader: "readonly", URL: "readonly",
      atob: "readonly", btoa: "readonly", Intl: "readonly",
      Chart: "readonly", crypto: "readonly", Uint32Array: "readonly",
    },
  },
  rules: { "no-undef": "error" },
}];
