#!/usr/bin/env python3
"""Поиск item id по названию через GitHub-базу EXBO/stalcraft-database."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.catalog import ItemCatalog


def main() -> int:
    if len(sys.argv) < 2:
        print('Использование: python scripts/find_item.py "название предмета"')
        return 1

    query = " ".join(sys.argv[1:])
    catalog = ItemCatalog()

    try:
        results = catalog.search(query, limit=20)
    except Exception as exc:
        print(f"Ошибка: {exc}", file=sys.stderr)
        return 1

    if not results:
        print("Ничего не найдено.")
        return 0

    for item in results:
        tag = " [артефакт]" if item.category == "artefact" else ""
        print(f"{item.id}\t{item.name}{tag}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
