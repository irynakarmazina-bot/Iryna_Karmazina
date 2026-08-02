#!/usr/bin/env python3
"""
Скріншот HTML-сторінки + збір JS-помилок.

Навіщо: щоб не викладати те, чого я не бачила. check_facade.sh ловить
поламані звернення до змінних, але не показує, ЯК сторінка виглядає.

Використання:
    python3 scripts/screenshot.py www/index.html out.png
    python3 scripts/screenshot.py https://unitex.od.ua out.png --width 390

У контейнері Claude Code на вебі Chromium уже стоїть, але його версія
не збігається з тією, яку хоче свіжий playwright — тому шлях до бінарника
шукається серед /opt/pw-browsers/chromium-*/chrome-linux/chrome.
Ставити браузери через `playwright install` не треба.
"""

import argparse
import glob
import pathlib
import sys

from playwright.sync_api import sync_playwright


def find_chromium():
    """Шлях до передвстановленого Chromium, або None — тоді бере свій."""
    hits = sorted(glob.glob("/opt/pw-browsers/chromium-*/chrome-linux/chrome"))
    return hits[-1] if hits else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("target", help="шлях до .html або URL")
    ap.add_argument("out", help="куди зберегти .png")
    ap.add_argument("--width", type=int, default=1440)
    ap.add_argument("--height", type=int, default=900)
    ap.add_argument("--full", action="store_true", help="уся сторінка, не лише перший екран")
    args = ap.parse_args()

    if args.target.startswith(("http://", "https://")):
        url = args.target
    else:
        url = pathlib.Path(args.target).resolve().as_uri()

    errors = []
    with sync_playwright() as p:
        launch = {"args": ["--no-sandbox"]}
        chromium = find_chromium()
        if chromium:
            launch["executable_path"] = chromium
        browser = p.chromium.launch(**launch)
        page = browser.new_page(viewport={"width": args.width, "height": args.height})
        page.on("pageerror", lambda e: errors.append(f"JS: {e}"))
        page.on(
            "console",
            lambda m: errors.append(f"console.error: {m.text}") if m.type == "error" else None,
        )
        page.goto(url, wait_until="networkidle")
        page.screenshot(path=args.out, full_page=args.full)
        browser.close()

    print(f"Скріншот: {args.out}")
    print(f"Помилок: {len(errors)}")
    for e in errors:
        print("  ", e[:300])
    return 1 if any(e.startswith("JS:") for e in errors) else 0


if __name__ == "__main__":
    sys.exit(main())
