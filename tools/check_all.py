#!/usr/bin/env python3
"""Запускає всі перевірки проєкту й повертає єдиний код виходу.

Призначено для CI: одна команда, зрозумілий підсумок, ненульовий код за будь-якого
дефекту. Кожна перевірка — окремий інструмент у `tools/`, тут вони лише зводяться.

Що перевіряється:

1. **Джерела** — невдалі завантаження й порожні файли (`audit_sources.py`).
2. **Структура розділів** — заголовки, блок «Джерела» (`build_book.py --check`).
3. **Синтаксис коду в розділах** — усі Python-блоки компілюються.
4. **Ноутбуки** — збірка з модулів, відсутність керуючих символів, наявність виводів.
5. **Помилки виконання** — жодної клітинки з `output_type == "error"`.
6. **Перехресні посилання** — «розділ N» вказує на наявний розділ.
7. **Затінення імен** — попереджувальна перевірка (`--check-shadowing`).

Запуск:
    python3 tools/check_all.py
    python3 tools/check_all.py --quiet    # лише підсумок
"""

from __future__ import annotations

import ast
import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
SECTIONS = ROOT / "sections"
NOTEBOOKS = ROOT / "notebooks"


class Result:
    def __init__(self, name: str, ok: bool, detail: str) -> None:
        self.name = name
        self.ok = ok
        self.detail = detail


def run(cmd: list[str]) -> tuple[int, str]:
    proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    return proc.returncode, (proc.stdout + proc.stderr).strip()


def check_sources() -> Result:
    code, out = run([sys.executable, "tools/audit_sources.py"])
    tail = [l for l in out.splitlines() if "Дефектів" in l]
    return Result("Джерела", code == 0, tail[0] if tail else out.splitlines()[-1])


def check_structure() -> Result:
    code, out = run([sys.executable, "tools/build_book.py", "--check"])
    errs = [l for l in out.splitlines() if l.strip().startswith("✗")]
    return Result("Структура розділів", code == 0,
                  f"{len(errs)} помилок" if errs else "0 помилок")


def check_python_blocks() -> Result:
    total = bad = 0
    problems: list[str] = []
    for path in sorted(SECTIONS.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        for i, block in enumerate(re.findall(r"```python\n(.*?)```", text, re.S), 1):
            total += 1
            try:
                ast.parse(block)
            except SyntaxError as exc:
                bad += 1
                problems.append(f"{path.name} блок {i}: {exc.msg}")
    detail = f"{total} блоків, {bad} не компілюється"
    if problems:
        detail += " -> " + "; ".join(problems[:3])
    return Result("Python-блоки розділів", bad == 0, detail)


def check_notebook_build() -> Result:
    code, out = run([sys.executable, "tools/build_notebooks.py"])
    built = len([l for l in out.splitlines() if l.startswith("✔")])
    return Result("Збірка ноутбуків", code == 0, f"{built} ноутбуків зібрано")


def check_notebook_runs() -> Result:
    """Перевіряє наявність виводів і відсутність помилок у вже виконаних ноутбуках."""
    try:
        import nbformat
    except ImportError:
        return Result("Виконання ноутбуків", True, "nbformat відсутній — перевірку пропущено")

    no_output: list[str] = []
    errors: list[str] = []
    total = 0
    for path in sorted(NOTEBOOKS.glob("*.ipynb")):
        total += 1
        nb = nbformat.read(str(path), as_version=4)
        code_cells = [c for c in nb.cells if c.cell_type == "code"]
        if code_cells and not any(c.get("outputs") for c in code_cells):
            no_output.append(path.name)
        for i, cell in enumerate(code_cells, 1):
            for out in cell.get("outputs", []):
                if out.get("output_type") == "error":
                    errors.append(f"{path.name} клітинка {i}: {out.get('ename')}")

    problems = len(errors) + len(no_output)
    detail = f"{total} ноутбуків, помилок {len(errors)}, без виводів {len(no_output)}"
    if errors:
        detail += " -> " + "; ".join(errors[:3])
    if no_output:
        detail += f" -> без виводів: {', '.join(no_output[:5])}"
    return Result("Виконання ноутбуків", problems == 0, detail)


def check_cross_references() -> Result:
    """Перевіряє, що посилання «розділ N» вказують на наявні розділи.

    Перевіряються і розділи (`sections/*.md`), і модулі ноутбуків
    (`tools/notebooks/nb_*.py`): у модулях теж є блоки «Куди далі», і вони
    вже одного разу посилалися на неіснуючі розділи 6b і 27 — спадок
    старого плану на 27 розділів.
    """
    existing = {int(p.name[:2]) for p in SECTIONS.glob("[0-9][0-9]-*.md")}
    existing |= {m.group(1) for m in
                 (re.match(r"([A-D])-", p.name) for p in SECTIONS.glob("*.md")) if m}

    broken: list[str] = []
    files = list(SECTIONS.glob("*.md")) + list((ROOT / "tools" / "notebooks").glob("nb_*.py"))
    for path in sorted(files):
        text = path.read_text(encoding="utf-8")
        for match in re.finditer(r"[Рр]озділ[иі]?\s+(\d+[a-zA-Z]?)", text):
            raw = match.group(1)
            if raw.isdigit() and int(raw) in existing:
                continue
            broken.append(f"{path.name}: розділ {raw}")

    detail = f"перевірено {len(files)} файлів, зламаних посилань {len(broken)}"
    if broken:
        detail += " -> " + "; ".join(broken[:4])
    return Result("Перехресні посилання", not broken, detail)


def check_shadowing() -> Result:
    code, out = run([sys.executable, "tools/build_notebooks.py", "--check-shadowing"])
    tail = [l for l in out.splitlines() if "Кандидатів" in l]
    return Result("Затінення імен", True, tail[0] if tail else "перевірку виконано")


def main() -> int:
    quiet = "--quiet" in sys.argv
    checks = [
        check_sources,
        check_structure,
        check_python_blocks,
        check_notebook_build,
        check_notebook_runs,
        check_cross_references,
        check_shadowing,
    ]

    results = []
    for check in checks:
        try:
            results.append(check())
        except Exception as exc:  # noqa: BLE001 — у CI треба бачити будь-який збій
            results.append(Result(check.__name__, False, f"виняток: {exc}"))

    failed = [r for r in results if not r.ok]

    if not quiet:
        print(f"{'перевірка':26} {'стан':>6}  подробиці")
        print("-" * 88)
        for r in results:
            print(f"{r.name:26} {('OK' if r.ok else 'ЗБІЙ'):>6}  {r.detail}")
        print("-" * 88)

    print(f"Перевірок: {len(results)}, збоїв: {len(failed)}")
    for r in failed:
        print(f"  ✗ {r.name}: {r.detail}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
