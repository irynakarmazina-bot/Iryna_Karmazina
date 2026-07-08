"""
Запуск рознесення витратних рахунків Маерска з Excel-таблиці.

Приклади:
  # суха прогонка ТІЛЬКИ по одному BL (нічого не створює) — для першого тесту
  python -m ekspedytor.run invoices.xlsx --mode dry-run --only-bl 263120787

  # суха прогонка по перших 3 рахунках
  python -m ekspedytor.run invoices.xlsx --mode dry-run --limit 3

  # реальне створення по одному рахунку
  python -m ekspedytor.run invoices.xlsx --mode create --only-bl 263120787

  # прогрес пишеться у файл (щоб читати ззовні під час роботи)
  python -m ekspedytor.run invoices.xlsx --mode dry-run --progress /root/eks_progress.json
"""
import argparse

from .agent import EkspedytorAgent


def main():
    p = argparse.ArgumentParser(description="Рознесення витратних рахунків Маерска")
    p.add_argument("xlsx", help="шлях до Excel-таблиці рахунків")
    p.add_argument("--mode", choices=["dry-run", "create"], default="dry-run",
                   help="dry-run (за замовч.) нічого не створює; create — створює рахунки")
    p.add_argument("--limit", type=int, default=None, help="обробити не більше N рахунків")
    p.add_argument("--only-bl", default=None, help="обробити тільки цей BL (коносамент)")
    p.add_argument("--progress", default=None, help="файл для запису прогресу (JSON)")
    args = p.parse_args()

    agent = EkspedytorAgent()
    report = agent.process_invoices(
        xlsx_path=args.xlsx, mode=args.mode,
        limit=args.limit, only_bl=args.only_bl, progress_path=args.progress,
    )
    print(report)


if __name__ == "__main__":
    main()
