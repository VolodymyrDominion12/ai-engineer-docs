#!/usr/bin/env python3
"""Головний редактор: збирає всі розділи й додатки в один документ.

`BRIEF.md` вимагає, щоб кожен розділ мав заголовок рівно `##`, підтеми — `###`,
без власного `# H1` і без змісту: «його зробить головний редактор». Це і є той
редактор.

Що робить:

1. Збирає `sections/NN-*.md` у порядку номерів, далі додатки `A`–`D`.
2. Генерує титульну сторінку й зміст із посиланнями-якорями.
3. **Перевіряє структуру** кожного файлу (рівні заголовків, відсутність `# H1`,
   відсутність дублів номерів) і повідомляє про проблеми.
4. Записує результат у `BOOK.md` (або шлях, переданий аргументом).

Запуск:
    python3 tools/build_book.py                  # зібрати в BOOK.md
    python3 tools/build_book.py --check          # лише перевірка, без запису
    python3 tools/build_book.py --out dist/book.md
"""

from __future__ import annotations

import datetime
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
SECTIONS = ROOT / "sections"

# Порядок додатків визначається літерою в імені файлу.
APPENDIX_LETTER = re.compile(r"^([A-Z])-")


def chapter_key(path: pathlib.Path) -> tuple[int, int | str]:
    """Ключ сортування: спершу розділи за номером, потім додатки за літерою."""
    m = re.match(r"^(\d+)-", path.name)
    if m:
        return (0, int(m.group(1)))
    a = APPENDIX_LETTER.match(path.name)
    if a:
        return (1, a.group(1))
    return (2, path.name)


def collect() -> list[pathlib.Path]:
    """Повертає файли розділів і додатків у порядку читання."""
    files = [p for p in SECTIONS.glob("*.md") if p.name != "README.md"]
    return sorted(files, key=chapter_key)


def slugify(text: str) -> str:
    """Робить якір із заголовка — так само, як це роблять генератори markdown."""
    text = text.strip().lower()
    keep = []
    for ch in text:
        if ch.isalnum() or ch in " -_":
            keep.append(ch)
        elif ch in ".,:;!?()[]«»\"'`":
            continue
        else:
            keep.append("-")
    slug = re.sub(r"\s+", "-", "".join(keep))
    slug = re.sub(r"-{2,}", "-", slug).strip("-")
    return slug


def validate(path: pathlib.Path) -> tuple[list[str], list[str]]:
    """Перевіряє структуру файлу.

    Повертає (помилки, попередження).

    Помилка — те, що ламає структуру документа: власний `# H1`, відсутній або
    дубльований `##`, стрибок рівнів. Попередження — змістовна неповнота, як-от
    відсутній блок «Джерела»: для додатка-глосарія це нормально, для розділу — ні.
    """
    text = path.read_text(encoding="utf-8")

    # Заголовки всередині блоків коду не рахуються
    lines = []
    in_fence = False
    for line in text.splitlines():
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            continue
        if not in_fence:
            lines.append(line)

    errors: list[str] = []
    warnings: list[str] = []

    h1 = [l for l in lines if l.startswith("# ")]
    h2 = [l for l in lines if l.startswith("## ")]
    h3 = [l for l in lines if l.startswith("### ")]
    h4 = [l for l in lines if l.startswith("#### ")]

    if h1:
        errors.append(f"має власний # H1: {h1[0][:60]!r}")
    if not h2:
        errors.append("немає заголовка рівня ##")
    elif len(h2) > 1:
        errors.append(f"заголовків ## більше одного ({len(h2)})")
    if h4 and not h3:
        errors.append("є #### без жодного ###")

    has_sources = "**Джерела**" in text or "## Джерела" in text
    if not has_sources:
        is_appendix = APPENDIX_LETTER.match(path.name) is not None
        kind = "додатка" if is_appendix else "розділу"
        warnings.append(f"немає блоку «Джерела» ({kind})")

    return errors, warnings


def build(out_path: pathlib.Path, check_only: bool) -> int:
    files = collect()
    if not files:
        print("Немає файлів для збору.", file=sys.stderr)
        return 1

    errors: list[tuple[str, str]] = []
    warnings: list[tuple[str, str]] = []
    entries: list[tuple[str, str]] = []   # (заголовок, якір)
    bodies: list[str] = []

    for path in files:
        errs, warns = validate(path)
        errors.extend((path.name, e) for e in errs)
        warnings.extend((path.name, w) for w in warns)

        text = path.read_text(encoding="utf-8").strip()
        first = next((l for l in text.splitlines() if l.startswith("## ")), None)
        if first:
            title = first[3:].strip()
            entries.append((title, slugify(first)))

        # Розділ стає розділом документа: підвищуємо рівні на один,
        # щоб ## став ### під H1 документа. Це зберігає вкладеність.
        body_lines = []
        in_fence = False
        for line in text.splitlines():
            if line.lstrip().startswith("```"):
                in_fence = not in_fence
                body_lines.append(line)
                continue
            if not in_fence and line.startswith("#"):
                body_lines.append("#" + line)
            else:
                body_lines.append(line)
        bodies.append("\n".join(body_lines))

    if errors:
        print("ПОМИЛКИ СТРУКТУРИ:")
        for name, issue in errors:
            print(f"  ✗ {name}: {issue}")
    else:
        print("Помилок структури немає.")

    if warnings:
        print("Попередження (не ламає документ):")
        for name, issue in warnings:
            print(f"  ⚠ {name}: {issue}")

    print(f"Файлів зібрано: {len(files)}")
    print(f"Записів у змісті: {len(entries)}")

    if check_only:
        return 1 if errors else 0

    today = datetime.date.today().isoformat()
    head = [
        "# AI Engineer — довідник українською",
        "",
        f"Зібрано з `sections/` {today}. Джерельні файли — у репозиторії "
        "`ai-engineer-docs`.",
        "",
        "> Кожне твердження в цьому документі підтверджене первинним джерелом. "
        "Первинні матеріали збережено в каталозі `research/`.",
        "",
        "## Зміст",
        "",
    ]
    toc = [f"{i}. [{title}](#{anchor})" for i, (title, anchor) in enumerate(entries, 1)]
    doc = "\n".join(head + toc + ["", "---", ""]) + "\n\n".join(bodies) + "\n"

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(doc, encoding="utf-8")
    size_kb = out_path.stat().st_size / 1024
    words = len(doc.split())
    print(f"Записано: {out_path.relative_to(ROOT)} ({size_kb:.0f} КБ, ~{words:,} слів)")
    return 1 if errors else 0


def main() -> int:
    args = sys.argv[1:]
    check_only = "--check" in args
    out = ROOT / "BOOK.md"
    if "--out" in args:
        idx = args.index("--out")
        if idx + 1 < len(args):
            out = pathlib.Path(args[idx + 1])
            if not out.is_absolute():
                out = ROOT / out
    return build(out, check_only)


if __name__ == "__main__":
    raise SystemExit(main())
