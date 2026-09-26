"""Спільні хелпери для генераторів ноутбуків довідника «AI Engineer»."""
from __future__ import annotations

import nbformat as nbf


def md(text: str) -> nbf.NotebookNode:
    return nbf.v4.new_markdown_cell(text.strip("\n"))


def code(text: str) -> nbf.NotebookNode:
    return nbf.v4.new_code_cell(text.strip("\n"))


# ─────────────────────────────────────────────────────────────────────────────
# Спільні клітинки
# ─────────────────────────────────────────────────────────────────────────────

SETUP_CELL = '''
# Спільне налаштування для всіх ноутбуків довідника.
# Шукає корінь репозиторію, щоб шляхи на кшталт research/... працювали
# незалежно від того, звідки запущено Jupyter.
import pathlib
import sys

_cwd = pathlib.Path.cwd()
if (_cwd / "research").is_dir():
    ROOT = _cwd
elif (_cwd.parent / "research").is_dir():
    ROOT = _cwd.parent
else:
    raise RuntimeError(
        f"Не знайдено каталог research/ ні в {_cwd}, ні в {_cwd.parent}. "
        "Запускайте Jupyter з кореня репозиторію або з теки notebooks/."
    )

print("Python :", sys.version.split()[0])
print("Корінь :", ROOT)
'''

VERSION_CELL = '''
# Версії бібліотек, використаних у цьому ноутбуку (для відтворюваності).
import importlib

for _name in ("nbformat", "jinja2", "transformers", "anthropic"):
    try:
        _mod = importlib.import_module(_name)
        print(f"{_name:14} {getattr(_mod, '__version__', '?')}")
    except ImportError:
        print(f"{_name:14} НЕ ВСТАНОВЛЕНО (для цього ноутбука не обов'язково)")
'''


# ─────────────────────────────────────────────────────────────────────────────
# Ноутбук 03 — Токенізація
# ─────────────────────────────────────────────────────────────────────────────
