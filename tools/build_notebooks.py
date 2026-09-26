#!/usr/bin/env python3
"""Генератор ноутбуків для довідника «AI Engineer».

Кожен ноутбук — окремий модуль у `tools/notebooks/nb_<номер>.py` зі змінними
FILENAME, TITLE і CELLS. Це дозволяє писати й перевіряти ноутбуки незалежно.

Запуск:
    python3 tools/build_notebooks.py            # зібрати всі
    python3 tools/build_notebooks.py 03 14      # зібрати вибрані
    python3 tools/build_notebooks.py --list     # показати наявні

Перевірка виконуваності (для ноутбуків, які заявлені як такі, що працюють без ключів):
    python3 -m nbconvert --to notebook --execute --inplace notebooks/03-tokenizaciya.ipynb
"""

from __future__ import annotations

import importlib
import pkgutil
import sys
from pathlib import Path

import nbformat as nbf

ROOT = Path(__file__).resolve().parent
NOTEBOOKS = ROOT.parent / "notebooks"

# Щоб модулі могли робити `from nbkit import ...`
sys.path.insert(0, str(ROOT))


def discover() -> dict[str, object]:
    """Знаходить усі модулі tools/notebooks/nb_*.py."""
    import notebooks as pkg

    found: dict[str, object] = {}
    for info in pkgutil.iter_modules(pkg.__path__):
        if not info.name.startswith("nb_"):
            continue
        key = info.name.removeprefix("nb_")
        found[key] = importlib.import_module(f"notebooks.{info.name}")
    return found


def build(module) -> Path:
    missing = [a for a in ("FILENAME", "TITLE", "CELLS") if not hasattr(module, a)]
    if missing:
        raise AttributeError(f"{module.__name__}: немає змінних {', '.join(missing)}")

    # Запобіжник: керуючі символи в джерелі клітинки ламають токенізатор IPython
    # (найчастіше — справжній NUL-байт, коли в модулі написано "\x00" замість "\\x00").
    for i, cell in enumerate(module.CELLS):
        bad = {ch for ch in cell.source if ord(ch) < 32 and ch not in "\n\t"}
        if bad:
            codes = ", ".join(hex(ord(c)) for c in sorted(bad))
            raise ValueError(
                f"{module.__name__}: клітинка {i} містить керуючі символи ({codes}). "
                "У модулі подвойте зворотний слеш: замініть \\x00 на \\\\x00."
            )

    nb = nbf.v4.new_notebook(cells=module.CELLS)
    nb.metadata = {
        "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
        "language_info": {"name": "python", "pygments_lexer": "ipython3"},
        "title": module.TITLE,
    }
    NOTEBOOKS.mkdir(exist_ok=True)
    path = NOTEBOOKS / module.FILENAME
    nbf.write(nb, str(path))
    return path


def main() -> int:
    args = sys.argv[1:]
    modules = discover()

    if "--list" in args:
        for key in sorted(modules):
            m = modules[key]
            print(f"{key}  {m.FILENAME:34} {m.TITLE}")
        return 0

    keys = [a for a in args if not a.startswith("--")] or sorted(modules)
    unknown = [k for k in keys if k not in modules]
    if unknown:
        print(f"Невідомі ноутбуки: {', '.join(unknown)}")
        print(f"Доступні: {', '.join(sorted(modules))}")
        return 1

    for key in keys:
        path = build(modules[key])
        nb = nbf.read(str(path), as_version=4)
        n_code = sum(1 for c in nb.cells if c.cell_type == "code")
        print(f"✔ {path.relative_to(ROOT.parent)}  "
              f"({len(nb.cells)} клітинок, з них кодових {n_code})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
