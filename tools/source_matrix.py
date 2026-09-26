#!/usr/bin/env python3
"""Генерує матрицю «джерело → розділ» для додатка D.

Метод: кожен файл у `research/` починається рядком `### SOURCE: <URL>`. Скрипт
витягує ці URL і шукає їх у markdown-посиланнях розділів `sections/`.

**Обмеження методу, яке треба знати:**

URL у хедері джерела — це URL, яким його завантажив `fetch.py`, а він іноді
додає `.md` або використовує шлях із `/docs/en/docs/`. У тексті розділу
посилання зазвичай ведуть на канонічний URL сторінки без `.md`. Через це
частина зв'язків не знаходиться автоматично, і цифри в матриці — **нижня
оцінка**, а не повний перелік.

Запуск:
    python3 tools/source_matrix.py              # підсумок
    python3 tools/source_matrix.py --markdown   # готовий блок для sections/D-*.md
    python3 tools/source_matrix.py --orphans    # джерела, не згадані в жодному розділі
"""

from __future__ import annotations

import collections
import glob
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
RESEARCH = ROOT / "research"
SECTIONS = ROOT / "sections"


def normalize(url: str) -> str:
    """Зводить URL до вигляду, придатного для порівняння.

    Прибирає схему, хвостовий слеш і суфікс `.md` — саме через них
    автоматичне зіставлення раніше не знаходило половину зв'язків.
    """
    url = url.strip().rstrip("/")
    url = re.sub(r"\.md$", "", url)
    url = re.sub(r"^https?://", "", url)
    return url.lower()


def collect_sources() -> dict[pathlib.Path, str]:
    """Повертає відповідність «файл джерела → URL»."""
    sources: dict[pathlib.Path, str] = {}
    for path in sorted(RESEARCH.rglob("*")):
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        head = "\n".join(text.splitlines()[:3])
        match = re.search(r"SOURCE:\s*(\S+)", head)
        if match:
            sources[path] = match.group(1)
    return sources


def build_map() -> tuple[dict[str, set[pathlib.Path]], dict[pathlib.Path, str]]:
    """Повертає (мапа «розділ → джерела», усі джерела)."""
    sources = collect_sources()
    used: dict[str, set[pathlib.Path]] = collections.defaultdict(set)

    for section in sorted(SECTIONS.glob("*.md")):
        text = section.read_text(encoding="utf-8")
        urls = {normalize(u) for u in re.findall(r"https?://[^\s\)\]\"'<>]+", text)}
        bucket: set[pathlib.Path] = set()
        for path, url in sources.items():
            if normalize(url) in urls:
                bucket.add(path)
        if bucket:
            used[section.stem] = bucket
    return used, sources


def chapter_label(stem: str) -> tuple[int, int | str]:
    """Ключ сортування й підпис: розділи за номером, далі додатки за літерою."""
    match = re.match(r"(\d+)", stem)
    if match:
        return (0, int(match.group(1)))
    letter = re.match(r"([A-Z])-", stem)
    if letter:
        return (1, letter.group(1))
    return (2, stem)


def label_text(stem: str) -> str:
    """Людиночитний підпис для рядка таблиці."""
    kind, value = chapter_label(stem)
    if kind == 0:
        return str(value)
    if kind == 1:
        return f"Додаток {value}"
    return stem


def main() -> int:
    used, sources = build_map()
    all_used = set().union(*used.values()) if used else set()
    orphans = sorted(set(sources) - all_used)

    if "--orphans" in sys.argv:
        print(f"Джерел усього: {len(sources)}")
        print(f"Не згадано в жодному розділі: {len(orphans)}")
        print()
        for path in orphans:
            print(f"  {path.relative_to(ROOT)}")
        return 0

    if "--markdown" in sys.argv:
        print("| № | Розділ | Джерел у матриці |")
        print("|---|---|---|")
        for stem in sorted(used, key=chapter_label):
            print(f"| {label_text(stem)} | `{stem}.md` | {len(used[stem])} |")
        total = sum(len(v) for v in used.values())
        print(f"\n**Усього зв'язків: {total}. Джерел у матриці: {len(all_used)} "
              f"з {len(sources)}. Поза матрицею: {len(orphans)}.**")
        return 0

    print(f"Джерел у research/: {len(sources)}")
    print(f"Джерел, зіставлених із розділами: {len(all_used)}")
    print(f"Поза матрицею: {len(orphans)}")
    print()
    print("Розділи (лише ті, де знайдено зв'язки):")
    total = 0
    for stem in sorted(used, key=chapter_label):
        total += len(used[stem])
        print(f"  {stem:30} {len(used[stem]):>3}")
    print(f"\nСумарно зв'язків: {total}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
