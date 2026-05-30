"""
CLI entry point:
  python -m ekspedytor.run MSCU1234567 expense invoice.pdf
  python -m ekspedytor.run 268674234 income
"""
import sys
from .agent import EkspedytorAgent


def main():
    if len(sys.argv) < 3:
        print("Використання: python -m ekspedytor.run <номер> <income|expense> [pdf_файл]")
        print("Приклад: python -m ekspedytor.run MSCU1234567 expense invoice.pdf")
        sys.exit(1)

    search_number = sys.argv[1]
    invoice_type = sys.argv[2].lower()
    pdf_filename = sys.argv[3] if len(sys.argv) > 3 else None

    if invoice_type not in ("income", "expense"):
        print("Тип рахунку має бути: income (доходний) або expense (витратний)")
        sys.exit(1)

    agent = EkspedytorAgent()
    result = agent.run(search_number, invoice_type, pdf_filename)
    print(result)


if __name__ == "__main__":
    main()
