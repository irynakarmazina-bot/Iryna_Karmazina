// Оперативний фінансовий звіт — меню і дашборд
// Вставити в: Розширення → Apps Script (файл Code.gs)

function onOpen() {
  SpreadsheetApp.getUi()
    .createMenu('📊 Звіт')
    .addItem('Відкрити дашборд', 'showDashboard')
    .addToUi();
}

function showDashboard() {
  var t = HtmlService.createTemplateFromFile('Dashboard');
  t.payload = JSON.stringify(collectData());
  var html = t.evaluate()
    .setWidth(1250)
    .setHeight(820)
    .setSandboxMode(HtmlService.SandboxMode.IFRAME);
  SpreadsheetApp.getUi().showModalDialog(html, 'Оперативний фінансовий звіт');
}

function collectData() {
  var ss = SpreadsheetApp.getActive();
  function rows(name) {
    var sh = ss.getSheetByName(name);
    if (!sh) return [];
    var v = sh.getDataRange().getValues();
    // Дати → рядки ISO, щоб пережити JSON
    return v.map(function (row) {
      return row.map(function (c) {
        return (c instanceof Date) ? Utilities.formatDate(c, 'Europe/Kyiv', 'yyyy-MM-dd') : c;
      });
    });
  }
  return {
    hroshi: rows('Гроші'),
    deb: rows('Дебіторка'),
    kred: rows('Кредиторка'),
    kalendar: rows('Календар'),
    ruh: rows('Рух грошей'),
    klienty: rows('Клієнти'),
  };
}
