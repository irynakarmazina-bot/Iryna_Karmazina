"""
Модуль фінансового обліку для Telegram-бота.

Що вміє:
- зберігати доходи та витрати в базі SQLite (файл finance.db поруч з ботом)
- будувати текстовий звіт P&L (прибутки і збитки) за місяць
- будувати звіт Cash Flow (рух грошей) за останні місяці
- генерувати інтерактивний HTML-дашборд з графіками (відкривається в браузері)

База даних створюється автоматично при першому записі — нічого налаштовувати не треба.
"""
import json
import sqlite3
from datetime import datetime
from pathlib import Path

DB_FILE = Path(__file__).parent / "finance.db"

MONTH_NAMES = ["Січень", "Лютий", "Березень", "Квітень", "Травень", "Червень",
               "Липень", "Серпень", "Вересень", "Жовтень", "Листопад", "Грудень"]
MONTH_SHORT = ["Січ", "Лют", "Бер", "Кві", "Тра", "Чер",
               "Лип", "Сер", "Вер", "Жов", "Лис", "Гру"]


# ── Робота з базою даних ─────────────────────────────────────────────────────

def _conn() -> sqlite3.Connection:
    """Відкриває з'єднання з базою і створює таблицю, якщо її ще немає."""
    conn = sqlite3.connect(DB_FILE)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS transactions (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     INTEGER NOT NULL,
            date        TEXT    NOT NULL,               -- YYYY-MM-DD
            type        TEXT    NOT NULL,               -- 'income' або 'expense'
            amount      REAL    NOT NULL,
            currency    TEXT    NOT NULL DEFAULT 'UAH',
            category    TEXT    NOT NULL,
            description TEXT    DEFAULT '',
            created_at  TEXT    NOT NULL
        )
    """)
    return conn


def _fmt(x: float) -> str:
    """Форматує число з пробілами між тисячами: 1234567.5 → '1 234 568'."""
    return f"{x:,.0f}".replace(",", " ")


def _parse_month(text: str | None) -> tuple[int, int]:
    """
    Розбирає місяць з тексту. Приймає '06.2026', '2026-06' або '06'.
    Якщо текст порожній — повертає поточний місяць.
    Повертає пару (рік, місяць).
    """
    now = datetime.now()
    if not text:
        return now.year, now.month
    text = text.strip()
    try:
        if "." in text:                       # 06.2026
            m, y = text.split(".")
            return int(y), int(m)
        if "-" in text:                       # 2026-06
            y, m = text.split("-")
            return int(y), int(m)
        return now.year, int(text)            # просто номер місяця
    except ValueError:
        return now.year, now.month


def _main_currency(user_id: int) -> str | None:
    """Повертає валюту, якою користувач користується найчастіше."""
    with _conn() as conn:
        row = conn.execute(
            "SELECT currency, COUNT(*) c FROM transactions WHERE user_id=? "
            "GROUP BY currency ORDER BY c DESC LIMIT 1", (user_id,)
        ).fetchone()
    return row[0] if row else None


# ── Операції з транзакціями (їх викликає Claude через інструменти) ───────────

def add_transaction(user_id: int, ttype: str, amount: float, category: str,
                    description: str = "", currency: str = "UAH",
                    tx_date: str | None = None) -> str:
    """Додає дохід або витрату. Повертає текст-підтвердження для користувача."""
    if ttype not in ("income", "expense"):
        return "Помилка: тип має бути 'income' (дохід) або 'expense' (витрата)."
    try:
        amount = float(amount)
    except (TypeError, ValueError):
        return "Помилка: сума має бути числом."
    if amount <= 0:
        return "Помилка: сума має бути більшою за нуль."

    if tx_date:
        try:
            datetime.strptime(tx_date, "%Y-%m-%d")
        except ValueError:
            return "Помилка: дата має бути у форматі YYYY-MM-DD, наприклад 2026-07-02."
    else:
        tx_date = datetime.now().strftime("%Y-%m-%d")

    currency = (currency or "UAH").upper().strip()
    category = category.strip().capitalize()

    with _conn() as conn:
        cur = conn.execute(
            "INSERT INTO transactions (user_id, date, type, amount, currency, category, description, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (user_id, tx_date, ttype, amount, currency, category,
             description.strip(), datetime.now().isoformat(timespec="seconds")),
        )
        tx_id = cur.lastrowid

    sign = "➕ Дохід" if ttype == "income" else "➖ Витрата"
    return (f"{sign} #{tx_id} збережено: {_fmt(amount)} {currency}, "
            f"категорія «{category}», дата {tx_date}.")


def delete_transaction(user_id: int, tx_id: str) -> str:
    """Видаляє транзакцію за номером (тільки свою)."""
    try:
        tx_id_int = int(tx_id)
    except (TypeError, ValueError):
        return "Вкажи номер транзакції цифрою."
    with _conn() as conn:
        cur = conn.execute(
            "DELETE FROM transactions WHERE id=? AND user_id=?", (tx_id_int, user_id)
        )
    if cur.rowcount == 0:
        return f"Транзакцію #{tx_id_int} не знайдено."
    return f"Транзакцію #{tx_id_int} видалено."


def list_transactions(user_id: int, month: str | None = None, limit: int = 30) -> str:
    """Список останніх транзакцій. month — необов'язково, формат '06.2026'."""
    query = ("SELECT id, date, type, amount, currency, category, description "
             "FROM transactions WHERE user_id=?")
    params: list = [user_id]
    title = "Останні транзакції"
    if month:
        y, m = _parse_month(month)
        query += " AND strftime('%Y-%m', date)=?"
        params.append(f"{y:04d}-{m:02d}")
        title = f"Транзакції за {MONTH_NAMES[m - 1].lower()} {y}"
    query += " ORDER BY date DESC, id DESC LIMIT ?"
    params.append(limit)

    with _conn() as conn:
        rows = conn.execute(query, params).fetchall()

    if not rows:
        return "Транзакцій поки немає. Просто напиши мені, наприклад: «витратила 500 грн на пальне»."

    lines = [f"📒 {title}:"]
    for tx_id, d, t, amount, cur, cat, desc in rows:
        sign = "+" if t == "income" else "−"
        extra = f" ({desc})" if desc else ""
        lines.append(f"#{tx_id} │ {d} │ {sign}{_fmt(amount)} {cur} │ {cat}{extra}")
    return "\n".join(lines)


def finance_summary(user_id: int, month: str | None = None) -> str:
    """
    Короткий підсумок за місяць: доходи, витрати, прибуток + розбивка за категоріями.
    Використовується Claude'ом для відповідей на питання про фінанси.
    """
    y, m = _parse_month(month)
    ym = f"{y:04d}-{m:02d}"

    with _conn() as conn:
        rows = conn.execute(
            "SELECT currency, type, category, SUM(amount) FROM transactions "
            "WHERE user_id=? AND strftime('%Y-%m', date)=? "
            "GROUP BY currency, type, category ORDER BY SUM(amount) DESC",
            (user_id, ym),
        ).fetchall()

    if not rows:
        return f"За {MONTH_NAMES[m - 1].lower()} {y} записів немає."

    # Групуємо: валюта → тип → список (категорія, сума)
    data: dict[str, dict[str, list[tuple[str, float]]]] = {}
    for cur, t, cat, s in rows:
        data.setdefault(cur, {}).setdefault(t, []).append((cat, s))

    lines = [f"Підсумок за {MONTH_NAMES[m - 1].lower()} {y}:"]
    for cur, by_type in data.items():
        inc = sum(s for _, s in by_type.get("income", []))
        exp = sum(s for _, s in by_type.get("expense", []))
        lines.append(f"\n[{cur}] Доходи: {_fmt(inc)} │ Витрати: {_fmt(exp)} │ Прибуток: {_fmt(inc - exp)}")
        for t, label in (("income", "Доходи"), ("expense", "Витрати")):
            if by_type.get(t):
                lines.append(f"{label} за категоріями:")
                for cat, s in by_type[t]:
                    lines.append(f"  • {cat} — {_fmt(s)}")
    return "\n".join(lines)


# ── Звіти для команд бота ────────────────────────────────────────────────────

def pnl_report(user_id: int, month: str | None = None) -> str:
    """Звіт P&L (прибутки і збитки) за місяць — як у фінансовому менеджменті."""
    y, m = _parse_month(month)
    ym = f"{y:04d}-{m:02d}"

    with _conn() as conn:
        rows = conn.execute(
            "SELECT currency, type, category, SUM(amount) FROM transactions "
            "WHERE user_id=? AND strftime('%Y-%m', date)=? "
            "GROUP BY currency, type, category ORDER BY SUM(amount) DESC",
            (user_id, ym),
        ).fetchall()

    title = f"📊 P&L — {MONTH_NAMES[m - 1]} {y}"
    if not rows:
        return (f"{title}\n\nЗаписів за цей місяць немає.\n"
                "Додай першу операцію — просто напиши, наприклад:\n"
                "«отримала 20000 грн за фрахт» або «витратила 500 грн на пальне»")

    data: dict[str, dict[str, list[tuple[str, float]]]] = {}
    for cur, t, cat, s in rows:
        data.setdefault(cur, {}).setdefault(t, []).append((cat, s))

    lines = [title]
    for cur, by_type in data.items():
        incomes = by_type.get("income", [])
        expenses = by_type.get("expense", [])
        total_inc = sum(s for _, s in incomes)
        total_exp = sum(s for _, s in expenses)
        profit = total_inc - total_exp

        lines.append(f"\n💱 {cur}")
        lines.append("━━━━━━━━━━━━━━━━━━")
        lines.append(f"ДОХОДИ: {_fmt(total_inc)}")
        for cat, s in incomes:
            pct = f" ({s / total_inc * 100:.0f}%)" if total_inc else ""
            lines.append(f"  • {cat} — {_fmt(s)}{pct}")
        lines.append(f"\nВИТРАТИ: {_fmt(total_exp)}")
        for cat, s in expenses:
            pct = f" ({s / total_exp * 100:.0f}%)" if total_exp else ""
            lines.append(f"  • {cat} — {_fmt(s)}{pct}")
        lines.append("━━━━━━━━━━━━━━━━━━")
        emoji = "✅" if profit >= 0 else "🔻"
        lines.append(f"{emoji} ПРИБУТОК: {'+' if profit >= 0 else ''}{_fmt(profit)}")
        if total_inc:
            lines.append(f"Рентабельність: {profit / total_inc * 100:.0f}%")

    lines.append("\n📈 Дашборд з графіками: /dashboard")
    return "\n".join(lines)


def cashflow_report(user_id: int, months: int = 6) -> str:
    """Звіт Cash Flow — рух грошей за останні місяці + накопичений баланс."""
    currency = _main_currency(user_id)
    if not currency:
        return ("💸 Cash Flow\n\nЗаписів поки немає.\n"
                "Додай першу операцію — просто напиши, наприклад:\n"
                "«витратила 500 грн на пальне»")

    now = datetime.now()
    # Будуємо список останніх N місяців: [(рік, місяць), ...] від старого до нового
    ym_list = []
    y, m = now.year, now.month
    for _ in range(months):
        ym_list.append((y, m))
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    ym_list.reverse()
    first_ym = f"{ym_list[0][0]:04d}-{ym_list[0][1]:02d}"

    with _conn() as conn:
        # Баланс до початку вікна (щоб накопичений підсумок був правильний)
        row = conn.execute(
            "SELECT COALESCE(SUM(CASE WHEN type='income' THEN amount ELSE -amount END), 0) "
            "FROM transactions WHERE user_id=? AND currency=? AND strftime('%Y-%m', date) < ?",
            (user_id, currency, first_ym),
        ).fetchone()
        balance = row[0]

        rows = conn.execute(
            "SELECT strftime('%Y-%m', date) ym, "
            "SUM(CASE WHEN type='income' THEN amount ELSE 0 END), "
            "SUM(CASE WHEN type='expense' THEN amount ELSE 0 END) "
            "FROM transactions WHERE user_id=? AND currency=? AND strftime('%Y-%m', date) >= ? "
            "GROUP BY ym", (user_id, currency, first_ym),
        ).fetchall()

    by_month = {r[0]: (r[1], r[2]) for r in rows}

    lines = [f"💸 Cash Flow — останні {months} міс. ({currency})", ""]
    for yy, mm in ym_list:
        inc, exp = by_month.get(f"{yy:04d}-{mm:02d}", (0.0, 0.0))
        net = inc - exp
        balance += net
        lines.append(f"{MONTH_SHORT[mm - 1]} {yy} │ {'+' if net >= 0 else ''}{_fmt(net)}  (↑{_fmt(inc)} ↓{_fmt(exp)})")
    lines.append("")
    lines.append(f"💰 Накопичений баланс: {_fmt(balance)} {currency}")
    lines.append("\n📈 Дашборд з графіками: /dashboard")
    return "\n".join(lines)


# ── HTML-дашборд ─────────────────────────────────────────────────────────────

def build_dashboard(user_id: int) -> Path | None:
    """
    Генерує HTML-файл з інтерактивним дашбордом (графіки на Chart.js).
    Повертає шлях до файлу або None, якщо даних ще немає.
    Дашборд будується в основній валюті користувача.
    """
    currency = _main_currency(user_id)
    if not currency:
        return None

    now = datetime.now()
    this_ym = now.strftime("%Y-%m")

    # Останні 6 місяців для графіка доходи/витрати
    ym_list = []
    y, m = now.year, now.month
    for _ in range(6):
        ym_list.append((y, m))
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    ym_list.reverse()

    with _conn() as conn:
        rows = conn.execute(
            "SELECT strftime('%Y-%m', date) ym, "
            "SUM(CASE WHEN type='income' THEN amount ELSE 0 END), "
            "SUM(CASE WHEN type='expense' THEN amount ELSE 0 END) "
            "FROM transactions WHERE user_id=? AND currency=? GROUP BY ym",
            (user_id, currency),
        ).fetchall()
        by_month = {r[0]: (r[1], r[2]) for r in rows}

        cat_rows = conn.execute(
            "SELECT category, SUM(amount) FROM transactions "
            "WHERE user_id=? AND currency=? AND type='expense' AND strftime('%Y-%m', date)=? "
            "GROUP BY category ORDER BY SUM(amount) DESC",
            (user_id, currency, this_ym),
        ).fetchall()

        balance_row = conn.execute(
            "SELECT COALESCE(SUM(CASE WHEN type='income' THEN amount ELSE -amount END), 0) "
            "FROM transactions WHERE user_id=? AND currency=?", (user_id, currency),
        ).fetchone()

        recent = conn.execute(
            "SELECT date, type, amount, category, description FROM transactions "
            "WHERE user_id=? AND currency=? ORDER BY date DESC, id DESC LIMIT 15",
            (user_id, currency),
        ).fetchall()

    month_income, month_expense = by_month.get(this_ym, (0.0, 0.0))

    # Понад 8 категорій — зайві згортаємо в «Інше» (палітра має 8 кольорів)
    categories = [{"name": c, "amount": s} for c, s in cat_rows[:7]]
    if len(cat_rows) > 7:
        categories.append({"name": "Інше", "amount": sum(s for _, s in cat_rows[7:])})

    payload = {
        "currency": currency,
        "generated": now.strftime("%d.%m.%Y %H:%M"),
        "month_title": f"{MONTH_NAMES[now.month - 1]} {now.year}",
        "kpi": {
            "income": month_income,
            "expense": month_expense,
            "profit": month_income - month_expense,
            "balance": balance_row[0],
        },
        "months": [
            {
                "label": f"{MONTH_SHORT[mm - 1]} {yy}",
                "income": by_month.get(f"{yy:04d}-{mm:02d}", (0.0, 0.0))[0],
                "expense": by_month.get(f"{yy:04d}-{mm:02d}", (0.0, 0.0))[1],
            }
            for yy, mm in ym_list
        ],
        "categories": categories,
        "recent": [
            {"date": d, "type": t, "amount": a, "category": c, "description": ds or ""}
            for d, t, a, c, ds in recent
        ],
    }

    # Вбудовуємо Chart.js прямо у файл — дашборд працює навіть без інтернету.
    # Якщо файла бібліотеки раптом немає — підключаємо з CDN.
    chartjs_file = Path(__file__).parent / "chartjs.min.js"
    if chartjs_file.exists():
        lib_tag = "<script>" + chartjs_file.read_text(encoding="utf-8") + "</script>"
    else:
        lib_tag = '<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>'

    html = DASHBOARD_TEMPLATE.replace("__PAYLOAD__", json.dumps(payload, ensure_ascii=False))
    html = html.replace("__CHARTJS_TAG__", lib_tag)
    out = Path(__file__).parent / f"dashboard_{user_id}.html"
    out.write_text(html, encoding="utf-8")
    return out


# Шаблон дашборда. Дані підставляються замість __PAYLOAD__ (JSON).
# Кольори — валідована палітра (дружня до дальтонізму), світла і темна теми.
DASHBOARD_TEMPLATE = """<!DOCTYPE html>
<html lang="uk">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Фінансовий дашборд</title>
__CHARTJS_TAG__
<style>
  :root {
    --surface: #fcfcfb; --page: #f9f9f7;
    --ink: #0b0b0b; --ink-2: #52514e; --muted: #898781;
    --grid: #e1e0d9; --border: rgba(11,11,11,0.10);
    --good: #006300; --bad: #d03b3b;
    --income: #2a78d6; --expense: #eb6834;
  }
  @media (prefers-color-scheme: dark) {
    :root {
      --surface: #1a1a19; --page: #0d0d0d;
      --ink: #ffffff; --ink-2: #c3c2b7; --muted: #898781;
      --grid: #2c2c2a; --border: rgba(255,255,255,0.10);
      --good: #0ca30c; --bad: #e66767;
      --income: #3987e5; --expense: #d95926;
    }
  }
  * { box-sizing: border-box; margin: 0; }
  body {
    font-family: system-ui, -apple-system, "Segoe UI", sans-serif;
    background: var(--page); color: var(--ink); padding: 20px;
  }
  .wrap { max-width: 960px; margin: 0 auto; }
  h1 { font-size: 22px; margin-bottom: 4px; }
  .sub { color: var(--muted); font-size: 13px; margin-bottom: 20px; }
  .kpi-row { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 12px; margin-bottom: 20px; }
  .kpi {
    background: var(--surface); border: 1px solid var(--border);
    border-radius: 12px; padding: 16px;
  }
  .kpi .label { color: var(--ink-2); font-size: 13px; margin-bottom: 6px; }
  .kpi .value { font-size: 26px; font-weight: 700; }
  .kpi .value.pos { color: var(--good); }
  .kpi .value.neg { color: var(--bad); }
  .cards { display: grid; grid-template-columns: 3fr 2fr; gap: 12px; margin-bottom: 20px; }
  @media (max-width: 720px) { .cards { grid-template-columns: 1fr; } }
  .card {
    background: var(--surface); border: 1px solid var(--border);
    border-radius: 12px; padding: 16px;
  }
  .card h2 { font-size: 15px; margin-bottom: 12px; color: var(--ink-2); font-weight: 600; }
  .chart-box { position: relative; height: 280px; }
  table { width: 100%; border-collapse: collapse; font-size: 14px; }
  th { text-align: left; color: var(--muted); font-weight: 500; font-size: 12px;
       padding: 6px 8px; border-bottom: 1px solid var(--grid); }
  td { padding: 7px 8px; border-bottom: 1px solid var(--grid); }
  td.num { text-align: right; font-variant-numeric: tabular-nums; font-weight: 600; }
  td.num.pos { color: var(--good); } td.num.neg { color: var(--bad); }
  .empty { color: var(--muted); text-align: center; padding: 24px 0; }
</style>
</head>
<body>
<div class="wrap">
  <h1>📊 Фінансовий дашборд</h1>
  <div class="sub" id="subtitle"></div>

  <div class="kpi-row" id="kpis"></div>

  <div class="cards">
    <div class="card">
      <h2 id="bar-title">Доходи та витрати за 6 місяців</h2>
      <div class="chart-box"><canvas id="barChart"></canvas></div>
    </div>
    <div class="card">
      <h2 id="pie-title">Витрати за категоріями</h2>
      <div class="chart-box" style="height:340px"><canvas id="pieChart"></canvas></div>
    </div>
  </div>

  <div class="card">
    <h2>Останні транзакції</h2>
    <table>
      <thead><tr><th>Дата</th><th>Категорія</th><th>Опис</th><th style="text-align:right">Сума</th></tr></thead>
      <tbody id="txBody"></tbody>
    </table>
  </div>
</div>

<script>
const DATA = __PAYLOAD__;

const dark = window.matchMedia("(prefers-color-scheme: dark)").matches;
const css = getComputedStyle(document.documentElement);
const C = (name) => css.getPropertyValue(name).trim();

// Категоріальна палітра (світла/темна) — фіксований порядок, дружній до дальтонізму
const CAT_LIGHT = ["#2a78d6","#1baf7a","#eda100","#008300","#4a3aa7","#e34948","#e87ba4","#eb6834"];
const CAT_DARK  = ["#3987e5","#199e70","#c98500","#008300","#9085e9","#e66767","#d55181","#d95926"];
const CAT = dark ? CAT_DARK : CAT_LIGHT;

const fmt = (x) => Math.round(x).toLocaleString("uk-UA");
const cur = DATA.currency;

document.getElementById("subtitle").textContent =
  `${DATA.month_title} · валюта: ${cur} · оновлено ${DATA.generated}`;

// ── KPI-плитки ──
const k = DATA.kpi;
const kpis = [
  { label: "Доходи за місяць", value: k.income, cls: "" },
  { label: "Витрати за місяць", value: k.expense, cls: "" },
  { label: "Прибуток за місяць", value: k.profit, cls: k.profit >= 0 ? "pos" : "neg", sign: true },
  { label: "Баланс (за весь час)", value: k.balance, cls: k.balance >= 0 ? "pos" : "neg", sign: true },
];
document.getElementById("kpis").innerHTML = kpis.map(x => `
  <div class="kpi">
    <div class="label">${x.label}</div>
    <div class="value ${x.cls}">${x.sign && x.value > 0 ? "+" : ""}${fmt(x.value)}</div>
  </div>`).join("");

Chart.defaults.font.family = 'system-ui, -apple-system, "Segoe UI", sans-serif';
Chart.defaults.color = C("--muted");
Chart.defaults.borderColor = C("--grid");

// ── Стовпчикова діаграма: доходи vs витрати по місяцях ──
new Chart(document.getElementById("barChart"), {
  type: "bar",
  data: {
    labels: DATA.months.map(m => m.label),
    datasets: [
      { label: "Доходи",  data: DATA.months.map(m => m.income),
        backgroundColor: C("--income"), borderRadius: 4, borderSkipped: false },
      { label: "Витрати", data: DATA.months.map(m => m.expense),
        backgroundColor: C("--expense"), borderRadius: 4, borderSkipped: false },
    ],
  },
  options: {
    responsive: true, maintainAspectRatio: false,
    plugins: {
      legend: { position: "top", labels: { boxWidth: 12, boxHeight: 12, color: C("--ink-2") } },
      tooltip: { callbacks: { label: (c) => `${c.dataset.label}: ${fmt(c.raw)} ${cur}` } },
    },
    scales: {
      x: { grid: { display: false } },
      y: { beginAtZero: true, grid: { color: C("--grid") },
           ticks: { callback: (v) => fmt(v) } },
    },
    categoryPercentage: 0.6, barPercentage: 0.8,
  },
});

// ── Кільцева діаграма: витрати за категоріями (поточний місяць) ──
const pieBox = document.getElementById("pieChart");
if (DATA.categories.length === 0) {
  pieBox.parentElement.innerHTML = '<div class="empty">Витрат цього місяця ще немає</div>';
} else {
  new Chart(pieBox, {
    type: "doughnut",
    data: {
      labels: DATA.categories.map(c => c.name),
      datasets: [{
        data: DATA.categories.map(c => c.amount),
        backgroundColor: DATA.categories.map((_, i) => CAT[i % CAT.length]),
        borderColor: C("--surface"), borderWidth: 2,   // 2px розділювач між секторами
      }],
    },
    options: {
      responsive: true, maintainAspectRatio: false, cutout: "62%",
      plugins: {
        legend: {
          position: "bottom",
          align: "start",
          labels: {
            boxWidth: 12, boxHeight: 12, color: C("--ink-2"),
            // Підписи з сумами — щоб значення читалися без наведення
            generateLabels: (chart) => {
              const total = DATA.categories.reduce((s, c) => s + c.amount, 0);
              return DATA.categories.map((c, i) => ({
                text: `${c.name} — ${fmt(c.amount)} (${Math.round(c.amount / total * 100)}%)`,
                fillStyle: CAT[i % CAT.length], strokeStyle: "transparent",
                fontColor: C("--ink-2"), index: i,
              }));
            },
          },
        },
        tooltip: { callbacks: { label: (c) => ` ${fmt(c.raw)} ${cur}` } },
      },
    },
  });
}

// ── Таблиця останніх транзакцій ──
document.getElementById("txBody").innerHTML = DATA.recent.length
  ? DATA.recent.map(t => `
      <tr>
        <td>${t.date}</td>
        <td>${t.category}</td>
        <td>${t.description}</td>
        <td class="num ${t.type === "income" ? "pos" : "neg"}">
          ${t.type === "income" ? "+" : "−"}${fmt(t.amount)}</td>
      </tr>`).join("")
  : '<tr><td colspan="4" class="empty">Транзакцій ще немає</td></tr>';
</script>
</body>
</html>
"""
