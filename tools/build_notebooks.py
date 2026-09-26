#!/usr/bin/env python3
"""Генератор ноутбуків для довідника «AI Engineer».

Кожен ноутбук — окремий модуль у `tools/notebooks/nb_<номер>.py` зі змінними
FILENAME, TITLE і CELLS. Це дозволяє писати й перевіряти ноутбуки незалежно.

Запуск:
    python3 tools/build_notebooks.py            # зібрати всі
    python3 tools/build_notebooks.py 03 14      # зібрати вибрані
    python3 tools/build_notebooks.py --list     # показати наявні
    python3 tools/build_notebooks.py --check-shadowing   # перевірити затінення імен

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


def carry_over_outputs(new_nb, old_path: Path) -> int:
    """Переносить виводи з наявного ноутбука в новий за збігом джерела клітинки.

    Перезбірка ноутбука з модуля СТВОРЮЄ клітинки без виводів. Для довідника це
    регресія: читач має бачити очікуваний результат, не запускаючи код. Тому
    виводи клітинок, джерело яких не змінилося, зберігаються; для змінених —
    очищуються (вони все одно застаріли).

    Повертає кількість клітинок, чиї виводи вдалося перенести.
    """
    if not old_path.exists():
        return 0

    try:
        old_nb = nbf.read(str(old_path), as_version=4)
    except Exception:
        return 0

    # Зіставляємо за (тип, джерело). Дублікати джерел обробляємо по порядку.
    pool: dict[tuple[str, str], list] = {}
    for cell in old_nb.cells:
        pool.setdefault((cell.cell_type, cell.source), []).append(cell)

    carried = 0
    for cell in new_nb.cells:
        if cell.cell_type != "code":
            continue
        bucket = pool.get((cell.cell_type, cell.source))
        if not bucket:
            continue
        old_cell = bucket.pop(0)
        outputs = old_cell.get("outputs") or []
        if outputs:
            cell["outputs"] = outputs
            cell["execution_count"] = old_cell.get("execution_count")
            carried += 1
    return carried


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

    # Спершу переносимо виводи з наявного файлу, потім перезаписуємо.
    carried = carry_over_outputs(nb, path)
    nbf.write(nb, str(path))
    print(f"  ↻ перенесено виводів із {carried} клітинок" if carried
          else "  ⚠ виводів для переносу немає — запустіть nbconvert")
    return path


def shadowing_warnings(module) -> list[str]:
    """Попереджає про імена, які є і ціллю циклу, і присвоєнням вищого рівня.

    Усі клітинки ноутбука виконуються в СПІЛЬНОМУ namespace ядра, тож ім'я,
    використане як ціль циклу в одній клітинці й для об'єкта в іншій, тихо
    затирає об'єкт. Саме так виникали помилки з `model`, `base` і `r`.
    """
    import ast

    assigned: dict[str, int] = {}
    loop_targets: dict[str, int] = {}

    for idx, cell in enumerate(module.CELLS):
        if getattr(cell, "cell_type", None) != "code":
            continue
        try:
            tree = ast.parse(cell.source)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for t in node.targets:
                    if isinstance(t, ast.Name):
                        assigned.setdefault(t.id, idx)
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                assigned.setdefault(node.target.id, idx)
            elif isinstance(node, (ast.For, ast.comprehension)):
                target = node.target
                names = target.elts if isinstance(target, ast.Tuple) else [target]
                for t in names:
                    if isinstance(t, ast.Name):
                        loop_targets.setdefault(t.id, idx)

    out = []
    for name in sorted(set(loop_targets) & set(assigned)):
        # Збіг у МЕЖАХ однієї клітинки — це нормальна локальна змінна.
        # Небезпечний лише випадок, коли ціль циклу затіняє об'єкт з ІНШОЇ клітинки.
        if loop_targets[name] == assigned[name]:
            continue
        out.append(
            f"ім'я {name!r}: ціль циклу в клітинці {loop_targets[name]}, "
            f"але присвоєння в клітинці {assigned[name]} — можливе затінення"
        )
    return out


def main() -> int:
    args = sys.argv[1:]
    modules = discover()

    if "--list" in args:
        for key in sorted(modules):
            m = modules[key]
            print(f"{key}  {m.FILENAME:34} {m.TITLE}")
        return 0

    if "--check-shadowing" in args:
        total = 0
        for key in sorted(modules):
            for warning in shadowing_warnings(modules[key]):
                print(f"⚠ {key}: {warning}")
                total += 1
        print(f"Кандидатів на затінення: {total} (попередження, не помилки)")
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
