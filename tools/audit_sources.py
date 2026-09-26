#!/usr/bin/env python3
"""Аудит каталогу джерел `research/`.

Шукає дефекти, які інакше залишаються непомітними:

1. Файли з текстом `FETCH-FAIL` — невдалі завантаження, які виглядають як джерела.
2. Порожні файли або файли з підозріло малою кількістю тексту.
3. Файли без рядка `### SOURCE:` — неможливо перевірити походження.

Запуск:
    python3 tools/audit_sources.py            # лише підсумок
    python3 tools/audit_sources.py --verbose  # перелічити всі знахідки

Код виходу 1, якщо знайдено бодай один дефект — це дозволяє використовувати
скрипт у CI як запобіжник.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RESEARCH = ROOT / "research"

MIN_USEFUL_BYTES = 500
TEXT_SUFFIXES = {".txt", ".md", ".json", ".jinja", ".py"}


def audit() -> tuple[dict[str, list[Path]], dict[str, list[Path]]]:
    """Повертає (дефекти, зауваження).

    Дефекти — те, що робить джерело непридатним: невдале завантаження або
    порожній файл. Зауваження — відсутній хедер SOURCE; для скриптів, дампів
    API і сирців бібліотек це нормально, але для завантаженої документації
    означає, що походження неможливо перевірити.
    """
    defects: dict[str, list[Path]] = {
        "fetch_failed": [],
        "empty_or_tiny": [],
    }
    notes: dict[str, list[Path]] = {
        "no_source_header": [],
    }

    for path in sorted(RESEARCH.rglob("*")):
        if not path.is_file() or path.suffix not in TEXT_SUFFIXES:
            continue

        raw = path.read_bytes()
        text = raw.decode("utf-8", "replace")

        if "FETCH-FAIL" in text or "FETCH-EMPTY" in text:
            defects["fetch_failed"].append(path)
            continue

        if len(raw) < MIN_USEFUL_BYTES:
            defects["empty_or_tiny"].append(path)
            continue

        # Хедер джерела очікуємо в перших рядках файлу.
        head = "\n".join(text.splitlines()[:3])
        if "### SOURCE:" not in head and "SOURCE:" not in head:
            notes["no_source_header"].append(path)

    return defects, notes


def main() -> int:
    verbose = "--verbose" in sys.argv
    defects, notes = audit()

    labels = {
        "fetch_failed": "Невдалі завантаження (FETCH-FAIL)",
        "empty_or_tiny": f"Порожні або менші за {MIN_USEFUL_BYTES} байт",
    }
    note_labels = {
        "no_source_header": "Без рядка SOURCE (нормально для скриптів, дампів і сирців)",
    }

    total = 0
    for key, paths in defects.items():
        total += len(paths)
        print(f"{labels[key]}: {len(paths)}")
        if paths and verbose:
            for p in paths[:40]:
                print(f"    {p.relative_to(ROOT)}")

    for key, paths in notes.items():
        print(f"{note_labels[key]}: {len(paths)}")

    n_files = sum(1 for p in RESEARCH.rglob("*") if p.is_file())
    print(f"\nПеревірено файлів у research/: {n_files}")
    print(f"Дефектів: {total}")

    if total:
        print("\nЩо робити:")
        print("  • FETCH-FAIL — знайти правильний URL (див. ANALIZ.md, розділ 5.1)")
        print("  • порожній файл — або перезавантажити, або видалити")
        return 1

    print("Джерела чисті: немає невдалих завантажень і порожніх файлів.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
