"""Ноутбук 22 — «Hugging Face Hub: CLI, Jobs, Xet».

Розділ довідника: sections/22-hub.md
Виконується БЕЗ ключів і БЕЗ мережі: усі розрахунки — локальні, а клітинки, які
стосуються справжнього `huggingface_hub`, захищені try/except ImportError.

Усі назви команд, прапорців, лімітів, цін і числа взяті з файлів research/
(див. sections/22-hub.md, блок «Джерела») станом на 26.09.2026.
"""

from nbkit import SETUP_CELL, VERSION_CELL, code, md

FILENAME = "22-hub.ipynb"
TITLE = "22. Hugging Face Hub"

CELLS = [
    md(
        """
# 22. Hugging Face Hub: CLI, Jobs, Xet

**Розділ довідника:** [`sections/22-hub.md`](../sections/22-hub.md)

**Потрібно: HF_TOKEN (лише для запису; читання публічних моделей працює без токена)**

Цей ноутбук не робить жодного мережевого запиту — токен тут не потрібен. Він показує механіку, яку
видно лише з коду: як будується командний рядок `hf`, як дедуплікація чанків економить трафік, як
виглядає конфігурація Job і як зібрати CI-скрипт.

**Що ви зробите:**

1. Зберете командні рядки `hf` **програмно** з реєстру гілок CLI та перевірите, які з них потребують токена.
2. Змоделюєте структуру репозиторію проти лімітів Hub і порахуєте, скільки місця в git займають LFS-вказівники.
3. **Відтворите механізм Xet**: content-defined chunking проти фіксованих чанків на синтетичних даних із
   повторюваними сегментами — і побачите, у скільки разів менше передається при вставці в середину файлу.
4. Перевірите арифметику чисел із блогів HF (блоки, CAS-записи, ефективна швидкість) — і знайдете місце,
   де числа не сходяться.
5. Згенеруєте таблицю `[tool.hf-jobs]` (PEP 723) і відтворите документовані правила злиття «скрипт проти прапорця».
6. Зберете CI-скрипт і **перевірите його синтаксис** через `bash -n`, а також провалідуєте YAML-workflow.

> Клітинки зі справжнім `huggingface_hub` захищені `try/except ImportError`: ноутбук однаково
> проходить у чистому середовищі.
"""
    ),
    md("## Налаштування"),
    code(SETUP_CELL),
    code(VERSION_CELL),
    code(
        '''
# Журнал ноутбука. Зберігаємо ЗНІМОК значень у словнику, а не список посилань:
# повторний запуск клітинки не дублює записи, а перезаписує ключ.
NB22_JOURNAL = {}


def nb22_log(key, value):
    """Ідемпотентний запис у журнал: один ключ — одне значення."""
    NB22_JOURNAL[key] = value
    return value


nb22_log("python", __import__("sys").version.split()[0])
print("Журнал ініціалізовано. Ключів:", len(NB22_JOURNAL))
'''
    ),

    # ── 22.1 ─────────────────────────────────────────────────────────────
    md(
        """
## 22.1 `hf` CLI: генерація команд із реєстру гілок

CLI побудований як «ресурс → дія». Нижче — реєстр гілок зі `package_reference/cli` і функція, яка
збирає командний рядок із позиційних частин і прапорців. Це дає змогу тримати команди в коді як дані,
а не як склеєні рядки.
"""
    ),
    code(
        '''
# ── 22.1 ── Реєстр гілок CLI та генерація командних рядків.
# Джерело складу команд: research/hf5_cli_ref.txt (package_reference/cli).
NB22_CLI_TREE = {
    "auth": ["list", "login", "logout", "switch", "token", "whoami"],
    "repos": ["ls", "create", "delete", "move", "settings", "delete-files", "branch"],
    "download": ["<repo_id> <filenames>..."],
    "upload": ["<repo_id> <local_path> <path_in_repo>"],
    "cache": ["ls", "rm", "prune", "verify"],
    "jobs": ["run", "uv run", "ps", "inspect", "logs", "stats", "wait",
             "cancel", "hardware", "labels", "ssh", "scheduled"],
    "buckets": ["create", "ls", "info", "settings", "rm", "sync"],
    "env": [], "version": [],
}


def nb22_hf(*parts, **flags):
    """Збирає командний рядок: позиційні частини, потім прапорці у сталому порядку."""
    line = " ".join(("hf",) + tuple(parts))
    for key, value in flags.items():
        flag = "--" + key.replace("_", "-")
        line += f" {flag}" if value is True else f" {flag} {value}"
    return line


NB22_COMMANDS = [
    (nb22_hf("download", "openai-community/gpt2", "config.json", quiet=True), False),
    (nb22_hf("repos", "ls", type="model", limit=0), False),
    (nb22_hf("cache", "ls", format="json", limit=20), False),
    (nb22_hf("auth", "login", token="$HF_TOKEN"), True),
    (nb22_hf("repos", "create", "my-org/whisper-uk", repo_type="dataset", private=True), True),
    (nb22_hf("upload", "my-org/whisper-uk", "./data", "/train",
             repo_type="dataset", commit_message="Epoch 34/50"), True),
    (nb22_hf("upload", "my-org/whisper-uk", "logs/", every=10), True),
    (nb22_hf("jobs", "run", "python:3.12", "python", "-c", "print(1)",
             flavor="cpu-basic", detach=True), True),
]

print("Гілки CLI (з package_reference/cli):")
for nb22_resource, nb22_actions in NB22_CLI_TREE.items():
    nb22_tail = ", ".join(nb22_actions) if nb22_actions else "—"
    print(f"  hf {nb22_resource:9} {nb22_tail}")
print()
print(f"{'команда':96}{'токен'}")
print("-" * 104)
for nb22_line, nb22_needs in NB22_COMMANDS:
    print(f"{nb22_line:96}{'так' if nb22_needs else 'ні'}")
print("-" * 104)
nb22_writes = sum(1 for _, needs in NB22_COMMANDS if needs)
print(f"Запис (або вхід) потребує токена: {nb22_writes} із {len(NB22_COMMANDS)}; "
      f"читання публічних моделей — без токена")
nb22_log("команд згенеровано", len(NB22_COMMANDS))
nb22_log("команд, що потребують токена", nb22_writes)
'''
    ),

    # ── 22.2 ─────────────────────────────────────────────────────────────
    md(
        """
## 22.2 Великі файли: ліміти репозиторію і LFS-вказівники

Характеристики репозиторію перевіряються сервером, і більшість із них не залежить від тарифу. Модель
нижче позначає кожен файл за рекомендацією (<200 ГБ) і жорсткою межею (500 ГБ), а також рахує, скільки
місця в git-історії займають самі LFS-вказівники.
"""
    ),
    code(
        '''
# ── 22.2 ── Модель репозиторію проти лімітів із hub/storage-limits.
NB22_LIMITS = {
    "файлів на репозиторій": 100_000,
    "записів на теку": 10_000,
    "файлів на коміт": 100,
    "розмір файлу (рекомендація)": 200 * 10 ** 9,
    "розмір файлу (жорстка межа)": 500 * 10 ** 9,
}
NB22_GB = 10 ** 9
NB22_FILES = [
    ("model-00001-of-00004.safetensors", 4.9 * NB22_GB),
    ("model-00002-of-00004.safetensors", 4.9 * NB22_GB),
    ("optimizer.bin", 39.4 * NB22_GB),
    ("checkpoint-full.bin", 260 * NB22_GB),
    ("dumps/all.bin", 560 * NB22_GB),
    ("tokenizer.json", 11.4 * 10 ** 6),
]


def nb22_verdict(size):
    if size > NB22_LIMITS["розмір файлу (жорстка межа)"]:
        return "ВІДМОВА: понад 500 GB"
    if size > NB22_LIMITS["розмір файлу (рекомендація)"]:
        return "ризик: понад 200 GB"
    return "ок"


print(f"{'файл':34}{'ГБ':>9}  вердикт")
print("-" * 62)
for nb22_name, nb22_size in NB22_FILES:
    print(f"{nb22_name:34}{nb22_size / NB22_GB:>9.2f}  {nb22_verdict(nb22_size)}")
print("-" * 62)
nb22_total = sum(s for _, s in NB22_FILES)
print(f"{'разом':34}{nb22_total / NB22_GB:>9.2f}")

# У git-історії лежить текстовий вказівник, а не сам файл.
NB22_POINTER = "\\n".join([
    "version https://git-lfs.github.com/spec/v1",
    "oid sha256:68d45e234eb4a928074dfd868cead0219ab85354cc53d20e772753c6bb9169d3",
    "size 440449768",
])
nb22_pointer_bytes = len(NB22_POINTER.encode())
nb22_blob = 440_449_768
print()
print(f"LFS-вказівник: {nb22_pointer_bytes} байтів проти {nb22_blob / NB22_GB:.4f} ГБ блобу "
      f"→ у git лежить {nb22_pointer_bytes / nb22_blob * 100:.6f}% обсягу")
print(f"100 таких файлів: блобів {100 * nb22_blob / NB22_GB:.2f} ГБ, "
      f"вказівників {100 * nb22_pointer_bytes} байтів")
nb22_log("розмір LFS-вказівника, байтів", nb22_pointer_bytes)
'''
    ),
    md(
        """
Розбиття на коміти — те, що `hf upload` і `upload_folder()` роблять самі, коли тека велика. Перевірмо
арифметику на трьох розмірах тек.
"""
    ),
    code(
        '''
# ── 22.2 ── Скільки комітів вийде з теки при межі 100 файлів на коміт.
print("Розбиття великої теки на коміти (upload_folder / hf upload роблять це самі):")
for nb22_n_files in (250, 5_000, 100_000):
    nb22_commits = -(-nb22_n_files // NB22_LIMITS["файлів на коміт"])
    nb22_part = " (один коміт)" if nb22_commits == 1 else f" ({nb22_commits} комітів)"
    print(f"  {nb22_n_files:>6} файлів → по ≤100 файлів на коміт{nb22_part}")
print()
print("Для довідки: 60-секундний таймаут на HTTP-коміт не залежить від обсягу,")
print("тому саме розбиття, а не швидкість мережі, визначає, чи дійде коміт.")
'''
    ),

    # ── 22.3 ─────────────────────────────────────────────────────────────
    md(
        """
## 22.3 Xet: чому дедуплікація на рівні чанків змінює передачу

Головна ідея Xet — різати файл на чанки **за вмістом** (content-defined chunking), щоб вставка чи
видалення не зсували межі всіх наступних чанків. Нижче — справжня симуляція на 2 МБ синтетичних даних
із повторюваними сегментами: два варіанти правки файлу, дві схеми чанкування.
"""
    ),
    code(
        '''
# ── 22.3 ── CDC проти фіксованих чанків. Лише стандартна бібліотека.
import hashlib
import random

NB22_SEGMENT = 512                    # «сегмент» даних
NB22_POOL = 256                       # стільки різних сегментів існує (репозиторій квантизацій)
NB22_SEGMENTS = 4096                  # ~2 МБ файл
NB22_FIXED = 8192                     # фіксований чанк
NB22_MIN, NB22_MAX = 2048, 16384      # межі довжини чанка для CDC
NB22_MASK = (1 << 13) - 1             # межа CDC: 13 молодших бітів gear-хешу == 0

nb22_rnd = random.Random(22)
nb22_pool = [bytes(nb22_rnd.getrandbits(8) for _ in range(NB22_SEGMENT))
             for _ in range(NB22_POOL)]
nb22_seq_a = [nb22_rnd.randrange(NB22_POOL) for _ in range(NB22_SEGMENTS)]
nb22_blob_a = b"".join(nb22_pool[i] for i in nb22_seq_a)
# B: одна вставка в середині (512 байтів).
nb22_seq_b = nb22_seq_a[: NB22_SEGMENTS // 2] + [NB22_POOL - 1] + nb22_seq_a[NB22_SEGMENTS // 2:]
nb22_blob_b = b"".join(nb22_pool[i] for i in nb22_seq_b)
# C: суцільна ділянка 20% перегенерована (типове «перетренували частину»).
nb22_seq_c = list(nb22_seq_a)
for nb22_k in range(1024, 1024 + NB22_SEGMENTS // 5):
    nb22_seq_c[nb22_k] = nb22_rnd.randrange(NB22_POOL)
nb22_blob_c = b"".join(nb22_pool[i] for i in nb22_seq_c)

NB22_GEAR = [nb22_rnd.getrandbits(64) for _ in range(256)]


def nb22_fixed(data, size=NB22_FIXED):
    return [data[i:i + size] for i in range(0, len(data), size)]


def nb22_cdc(data, min_size=NB22_MIN, max_size=NB22_MAX, mask=NB22_MASK):
    """Gear-хеш: межа там, де (hash & mask) == 0, з обмеженнями min/max."""
    chunks, start, h = [], 0, 0
    for i, byte in enumerate(data):
        h = ((h << 1) + NB22_GEAR[byte]) & 0xFFFFFFFFFFFFFFFF
        size = i - start + 1
        if (size >= min_size and h & mask == 0) or size >= max_size:
            chunks.append(data[start:i + 1])
            start, h = i + 1, 0
    if start < len(data):
        chunks.append(data[start:])
    return chunks


def nb22_digest(chunk):
    return hashlib.sha256(chunk).hexdigest()[:12]


def nb22_transfer(old_chunks, new_chunks):
    """Скільки чанків нової версії відсутні у старій і скільки байтів треба передати."""
    known = {nb22_digest(c) for c in old_chunks}
    fresh = [c for c in new_chunks if nb22_digest(c) not in known]
    return len(set(nb22_digest(c) for c in new_chunks)), len(fresh), sum(len(c) for c in fresh)


print(f"файл A: {len(nb22_blob_a)} байтів "
      f"({NB22_SEGMENTS} сегментів по {NB22_SEGMENT} Б із пулу {NB22_POOL})")
print(f"файл B: {len(nb22_blob_b)} байтів (у середину вставлено 1 сегмент = {NB22_SEGMENT} байтів)")
print(f"файл C: {len(nb22_blob_c)} байтів (суцільна ділянка у 20% перегенерована)")

for nb22_label, nb22_other in (("B (вставка всередині)", nb22_blob_b),
                               ("C (20% перегенеровано)", nb22_blob_c)):
    print()
    print(f"нова версія — {nb22_label}")
    print(f"{'схема':20}{'чанків':>9}{'розмір чанка':>15}{'нових':>8}{'передати':>12}")
    print("-" * 66)
    for nb22_scheme, nb22_fn in (("фіксовані 8192 Б", nb22_fixed), ("CDC (gear-хеш)", nb22_cdc)):
        nb22_ca, nb22_cb = nb22_fn(nb22_blob_a), nb22_fn(nb22_other)
        _, nb22_fresh, nb22_bytes = nb22_transfer(nb22_ca, nb22_cb)
        nb22_avg = sum(len(c) for c in nb22_cb) / len(nb22_cb)
        print(f"{nb22_scheme:20}{len(nb22_cb):>9}{nb22_avg:>13.0f} Б{nb22_fresh:>8}"
              f"{nb22_bytes / 1024:>9.1f} КБ")
    print("-" * 66)
    print(f"{'без дедуплікації':20}{'':>9}{'':>15}{'':>8}{len(nb22_other) / 1024:>9.1f} КБ")

nb22_log("CDC: передано при вставці, КБ",
         round(nb22_transfer(nb22_cdc(nb22_blob_a), nb22_cdc(nb22_blob_b))[2] / 1024, 1))
nb22_log("фіксовані: передано при вставці, КБ",
         round(nb22_transfer(nb22_fixed(nb22_blob_a), nb22_fixed(nb22_blob_b))[2] / 1024, 1))
'''
    ),
    md(
        """
Що показує вивід: при вставці **512 байтів із 2 МБ** фіксовані чанки втрачають половину файлу (усі межі
після вставки зсунулися), а CDC передає один чанк. На версії C (суцільна ділянка в 20%) різниці немає —
CDC не стискає дані, він **локалізує зміни**.

Тепер масштаб: арифметика з чисел блогів `From Chunks to Blocks` і документації Xet.
"""
    ),
    code(
        '''
# ── 22.3 ── Чанки проти блоків і ціна оновлення на реальних числах із джерел.
NB22_GB2 = 10 ** 9
NB22_CHUNK = 64 * 1024            # ~64 КБ на чанк
NB22_BLOCK = 64 * 10 ** 6         # «blocks of up to 64MB»
NB22_CAS_FACTOR = 1000            # заявлене зменшення CAS-записів у блозі

print("Чанки проти блоків:")
for nb22_size_gb in (20, 200, 191):
    nb22_chunks = nb22_size_gb * NB22_GB2 / NB22_CHUNK
    nb22_blocks = nb22_size_gb * NB22_GB2 / NB22_BLOCK
    print(f"  {nb22_size_gb:>3} ГБ → {nb22_chunks:>12,.0f} чанків → {nb22_blocks:>9,.0f} блоків "
          f"(×{nb22_chunks / nb22_blocks:,.0f}; у блозі заявлено ×{NB22_CAS_FACTOR:,})")

print("")
print("Розбіжність 977 проти 1000 — це KB проти KiB. Документація наводить для 20 ГБ")
print(f"файлу 312 500 чанків, тобто рахує чанк як 64 000 байтів; при 65 536 наш")
print(f"розрахунок дає {20 * NB22_GB2 / NB22_CHUNK:,.0f}. Обидва числа описують те саме.")

# Приклад gemma-2-9b-it-GGUF: 29 квантизацій, 191 ГБ, 1515 унікальних блоків, ~97 ГБ у сховищі.
NB22_BLOCKS, NB22_STORED, NB22_ORIGINAL = 1515, 97, 191
print("")
print(f"gemma-2-9b-it-GGUF: {NB22_BLOCKS} блоків × 64 МБ = "
      f"{NB22_BLOCKS * NB22_BLOCK / NB22_GB2:.2f} ГБ (у блозі — «приблизно {NB22_STORED} ГБ»)")
print(f"економія: {NB22_ORIGINAL - NB22_STORED} ГБ із {NB22_ORIGINAL} ГБ → "
      f"коефіцієнт {NB22_ORIGINAL / NB22_STORED:.3f}")
nb22_log("блоків у gemma-2-9b-it-GGUF", NB22_BLOCKS)
nb22_log("стиснення репозиторію, разів", round(NB22_ORIGINAL / NB22_STORED, 3))
'''
    ),
    code(
        '''
# ── 22.3 ── Перевірка швидкості з блогу і виграш локального кеша чанків на завантаженні.
print(f"{'версія':>10}{'ГБ':>7}{'хвилин':>9}{'ефективна швидкість, МБ/с':>30}")
print("-" * 56)
for nb22_ver, nb22_gb, nb22_min in (("original", 191, 509), ("xet-backed", 97, 258)):
    nb22_rate = nb22_gb * NB22_GB2 / (nb22_min * 60) / 10 ** 6
    print(f"{nb22_ver:>10}{nb22_gb:>7}{nb22_min:>9}{nb22_rate:>30.2f}")
print("-" * 56)
print("Обидва рядки дають ту саму швидкість → двократне прискорення справжнє,")
print("але підпис «@ 50MB/s» у блозі арифметикою не підтверджується.")
print()
print("Завантаження нової квантизації з локальним кешем чанків:")
for nb22_shared in (0.0, 0.508, 0.9):
    nb22_left = 191 * (1 - nb22_shared)
    print(f"  спільних чанків {nb22_shared * 100:>5.1f}% → {nb22_left:>6.1f} ГБ "
          f"замість 191.0 ГБ")
nb22_log("ефективна швидкість original, МБ/с", round(191 * NB22_GB2 / (509 * 60) / 10 ** 6, 2))
'''
    ),

    # ── 22.4 ─────────────────────────────────────────────────────────────
    md(
        """
## 22.4 Jobs: конфігурація запуску

Окремого YAML-файлу конфігурації Jobs не існує: поверхня налаштування — це прапорці CLI (або аргументи
Python-API) плюс необов'язкова таблиця `[tool.hf-jobs]` у PEP 723-заголовку скрипта (TOML). Нижче —
генерація цієї таблиці та відтворення правил злиття: явний прапорець перемагає, а `env`, `secrets`,
`labels` і `volumes` доповнюються по елементах.
"""
    ),
    code(
        '''
# ── 22.4 ── Конфігурація Jobs: таблиця [tool.hf-jobs] і правила злиття.
NB22_SCRIPT_CFG = {
    "image": "vllm/vllm-openai:unlimited-ocr",
    "flavor": "l4x1",
    "python": "/usr/bin/python3",
    "secrets": ["HF_TOKEN"],
    "env": {"BATCH": "16"},
    "labels": {"model": "Qwen3-06B"},
}
NB22_CLI_FLAGS = {"flavor": "l4x4", "env": {"BATCH": "32", "DEBUG": "1"},
                  "labels": {"team": "ml"}, "timeout": "2h"}
NB22_MERGED_KEYS = {"env", "secrets", "labels", "volumes"}


def nb22_resolve(script, flags):
    """Явний прапорець завжди перемагає; env/secrets/labels/volumes доповнюються."""
    out = {key: (value, "script") for key, value in script.items()}
    for key, value in flags.items():
        if key in NB22_MERGED_KEYS and key in out:
            current = out[key][0]
            if isinstance(current, dict):
                merged = dict(current)
                merged.update(value)
                out[key] = (merged, "обидва")
            else:
                out[key] = (sorted(set(current) | set(value)), "обидва")
        else:
            out[key] = (value, "флаг")
    return out


print("# /// script")
print('# requires-python = ">=3.11"')
print('# dependencies = ["vllm", "datasets"]')
print("#")
print("# [tool.hf-jobs]")
for nb22_key, nb22_value in NB22_SCRIPT_CFG.items():
    if isinstance(nb22_value, str):
        print(f'# {nb22_key:8}= "{nb22_value}"')
    else:
        print(f"# {nb22_key:8}= {nb22_value}")
print("# ///")
print()
print(f"{'ключ':10}{'значення':48}{'джерело'}")
print("-" * 70)
NB22_RESOLVED = nb22_resolve(NB22_SCRIPT_CFG, NB22_CLI_FLAGS)
for nb22_key, (nb22_value, nb22_src) in NB22_RESOLVED.items():
    print(f"{nb22_key:10}{str(nb22_value):48}{nb22_src}")
print("-" * 70)
print('hf jobs uv run --dry-run ocr.py → значення зі скрипта позначаються "(from script)"')
nb22_log("ключів у [tool.hf-jobs]", len(NB22_SCRIPT_CFG))
'''
    ),
    code(
        '''
# ── 22.4 ── Ціна запуску: хвилинні ціни зі сторінки jobs-pricing.
NB22_PRICES = {"cpu-basic": 0.0002, "t4-small": 0.0067, "a10g-small": 0.0167,
               "a10g-large": 0.0250, "a100x4": 0.1667, "h200x8": 0.6667}
NB22_TIMEOUT_MIN = 30   # типовий таймаут Jobs

print(f"{'flavor':12}{'$/хв':>8}{'30 хв (типово)':>16}{'2 год':>10}{'24 год':>10}")
print("-" * 58)
for nb22_flavor, nb22_price in NB22_PRICES.items():
    print(f"{nb22_flavor:12}{nb22_price:>8.4f}{nb22_price * NB22_TIMEOUT_MIN:>16.2f}"
          f"{nb22_price * 120:>10.2f}{nb22_price * 1440:>10.2f}")
print("-" * 58)
print("Білінг іде лише поки Job у стані Starting або Running; під час збірки образу — ні.")
nb22_log("ціна a10g-small, $/год", round(NB22_PRICES["a10g-small"] * 60, 2))
'''
    ),

    # ── 22.5 ─────────────────────────────────────────────────────────────
    md(
        """
## 22.5 Міграція на Hub v1: що зникло і як перевірити свою лінійку

`huggingface_hub` v1.0 прибрав цілий шар API. Нижче — таблиця «було → стало» і офлайн-інтроспекція:
вона показує, на якій лінійці сидить ваше середовище, не роблячи жодного запиту в мережу.
"""
    ),
    code(
        '''
# ── 22.5 ── Видалене в huggingface_hub v1.0 і заміна (джерело: concepts/migration).
NB22_REMOVED = [
    ("huggingface-cli", "hf"),
    ("Repository (обгортка над git)", "snapshot_download, upload_file, upload_folder, create_commit"),
    ("HfFolder", "login / logout / whoami / get_token"),
    ("InferenceApi", "InferenceClient"),
    ("configure_http_backend()", "set_client_factory / set_async_client_factory"),
    ("use_auth_token=", "token="),
    ("constants.hf_cache_home", "змінна середовища HF_HOME"),
    ("update_repo_visibility()", "update_repo_settings()"),
    ("get_token_permission()", "—"),
    ("hf_transfer / HF_HUB_ENABLE_HF_TRANSFER", "hf_xet / HF_XET_HIGH_PERFORMANCE"),
    ("resume_download, force_filename, local_dir_use_symlinks", "—"),
    ("new_session= у login()", "skip_if_logged_in="),
    ("hf cache scan / hf cache delete", "hf cache ls / rm / prune"),
    ("requests.HTTPError", "HfHubHttpError (базується на httpx)"),
    ("LocalEntryNotFoundError", "EntryNotFoundError + RemoteEntryNotFoundError"),
    ("huggingface_hub[tensorflow] і Keras 2.x", "Keras 3.x"),
    ("huggingface_hub[cli]", "CLI входить у сам пакет"),
]
print(f"{'видалено у v1.0':56}{'заміна'}")
print("-" * 112)
for nb22_old, nb22_new in NB22_REMOVED:
    print(f"{nb22_old:56}{nb22_new}")
nb22_log("рядків у таблиці міграції", len(NB22_REMOVED))
'''
    ),
    code(
        '''
# ── 22.5 ── Інтроспекція без мережі: яка лінійка встановлена у вашому середовищі.
try:
    import huggingface_hub as nb22_hub
    from importlib.metadata import version as nb22_version

    print(f"huggingface_hub {nb22_version('huggingface_hub')} встановлено")
    for nb22_attr in ("HfFolder", "Repository", "InferenceApi", "get_token", "login"):
        print(f"  hasattr(huggingface_hub, {nb22_attr!r}) → {hasattr(nb22_hub, nb22_attr)}")
    print("На v0.x перші три атрибути ще існують; на v1.x і далі — ні.")
    nb22_log("huggingface_hub встановлено", nb22_version("huggingface_hub"))
except ImportError:
    print("huggingface_hub не встановлено — це нормально для цього ноутбука.")
    print("Інтроспекція нічого не ламає: жодна клітинка вище його не потребує.")
    print("Перевірте у своєму середовищі:")
    print("  python -c 'import huggingface_hub as h; print(h.__version__)'")
    nb22_log("huggingface_hub встановлено", "ні (лише CLI/HTTP-факти з джерел)")
'''
    ),

    # ── 22.6 ─────────────────────────────────────────────────────────────
    md(
        """
## 22.6 Автоматизація в CI

Скрипт нижче збирається програмно й одразу перевіряється `bash -n`. Ключові елементи: `set -euo
pipefail`, `HF_HUB_DISABLE_UPDATE_CHECK=1` (щоб CI не ходив у PyPI), `HF_HOME` на ефемерному диску,
`hf jobs wait` як гейт і прибирання кеша.
"""
    ),
    code(
        '''
# ── 22.6 ── Генерація CI-скрипта і перевірка його синтаксису.
import shutil
import subprocess


def nb22_step(text, comment=""):
    return text + (f"  # {comment}" if comment else "")


NB22_CI = "\\n".join([
    "#!/usr/bin/env bash",
    "set -euo pipefail",
    "",
    "export HF_HUB_DISABLE_UPDATE_CHECK=1   # не ходити в PyPI у CI",
    'export HF_HOME="$RUNNER_TEMP/hf"      # кеш на ефемерному диску',
    "",
    nb22_step("hf auth whoami", "падіння, якщо токен недійсний"),
    nb22_step("hf download openai-community/gpt2 config.json --quiet"),
    nb22_step('hf repos create "$REPO" --repo-type=dataset --exist-ok'),
    nb22_step('hf upload "$REPO" ./data /train --repo-type=dataset '
              '--commit-message "ci $(date -u +%FT%TZ)"'),
    nb22_step("JOB=$(hf jobs uv run --detach --flavor t4-small --timeout 30m "
              "--secrets HF_TOKEN train.py -q)"),
    nb22_step('hf jobs wait "$JOB"', "exit 0 лише якщо Job завершився успішно"),
    nb22_step('hf jobs logs "$JOB" | tail -n 20'),
    nb22_step('hf cache ls --filter "size>1gb" -q | xargs -r hf cache rm -y'),
])
print(NB22_CI)
print()
if shutil.which("bash"):
    nb22_proc = subprocess.run(["bash", "-n"], input=NB22_CI, text=True, capture_output=True)
    nb22_verdict_txt = "синтаксис ок" if nb22_proc.returncode == 0 else nb22_proc.stderr.strip()
    print(f"bash -n → код {nb22_proc.returncode} ({nb22_verdict_txt})")
    nb22_log("bash -n", f"код {nb22_proc.returncode}")
else:
    print("bash не знайдено — перевірку синтаксису пропущено (скрипт усе одно надруковано).")
'''
    ),
    md(
        """
Останній блок — **схема** workflow GitHub Actions, а не цитата з джерел: офіційного GitHub Action для
Hub у джерелах розділу не описано. Валідація тут справжня — YAML розбирається в словник.
"""
    ),
    code(
        '''
# ── 22.6 ── Workflow GitHub Actions (СХЕМА) і його валідація.
NB22_WORKFLOW = "\\n".join([
    "name: sync-model",
    "on:",
    "  workflow_dispatch:",
    "jobs:",
    "  upload:",
    "    runs-on: ubuntu-latest",
    "    env:",
    "      HF_TOKEN: ${{ secrets.HF_TOKEN }}",
    '      HF_HUB_DISABLE_UPDATE_CHECK: "1"',
    "    steps:",
    "      - uses: actions/checkout@v4",
    "      - run: pip install -U huggingface_hub",
    "      - run: hf auth whoami",
    '      - run: hf upload my-org/my-model ./out . --commit-message "ci"',
])
print(NB22_WORKFLOW)
print()
try:
    import yaml

    nb22_parsed = yaml.safe_load(NB22_WORKFLOW)
    nb22_steps = nb22_parsed["jobs"]["upload"]["steps"]
    nb22_env = nb22_parsed["jobs"]["upload"]["env"]
    print(f"yaml.safe_load → {type(nb22_parsed).__name__} | кроків: {len(nb22_steps)} | "
          f"токен із secrets: {'HF_TOKEN' in nb22_env}")
    nb22_log("кроків у workflow", len(nb22_steps))
except ImportError:
    print("PyYAML не встановлено — валідацію YAML пропущено (у CI він буде розібраний runner'ом).")
'''
    ),

    # ── самоперевірка ────────────────────────────────────────────────────
    md(
        """
## Самоперевірка

Перевіряємо твердження розділу: склад гілок CLI, ліміти репозиторію, механіку CDC проти фіксованих
чанків, правила злиття `[tool.hf-jobs]`, ціни Jobs і таблицю міграції.
"""
    ),
    code(
        '''
# ── 1. Реєстр гілок CLI збігається з package_reference/cli ───────────────
assert (
    set(NB22_CLI_TREE) == {"auth", "repos", "download", "upload", "cache",
                           "jobs", "buckets", "env", "version"}
    and len(NB22_CLI_TREE["jobs"]) == 12
    and "uv run" in NB22_CLI_TREE["jobs"] and "scheduled" in NB22_CLI_TREE["jobs"]
    and len(NB22_CLI_TREE["cache"]) == 4          # ls, rm, prune, verify
), "склад гілок CLI мусить збігатися з довідником команд"
print("✓ гілки CLI: 9 ресурсів; у jobs 12 дій, включно з 'uv run' і 'scheduled'")

# ── 2. Генерація рядків: прапорці після позиційних, токен — лише на запис ─
assert (
    nb22_hf("download", "openai-community/gpt2", "config.json", quiet=True)
    == "hf download openai-community/gpt2 config.json --quiet"
    and nb22_hf("repos", "ls", type="model", limit=0) == "hf repos ls --type model --limit 0"
    and nb22_hf("upload", "r", "p", repo_type="dataset") == "hf upload r p --repo-type dataset"
    and nb22_hf("jobs", "run", "python:3.12", detach=True).endswith(" --detach")
    # токен потрібен лише на запис або вхід, читання публічних моделей — без токена
    and len(NB22_COMMANDS) == 8
    and sum(1 for _, nb22_needs in NB22_COMMANDS if nb22_needs) == 5
    and all(not nb22_needs for nb22_line, nb22_needs in NB22_COMMANDS
            if nb22_line.startswith(("hf download", "hf repos ls", "hf cache ls")))
    and NB22_COMMANDS[3][1] is True and "auth login" in NB22_COMMANDS[3][0]
), "True → прапорець без значення; токен — лише на запис (5 із 8 команд)"
print("✓ генерація команд: прапорці в стабільному порядку, '_' перетворюється на '-'; "
      "токен потрібен 5 із 8 команд")

# ── 3. Ліміти репозиторію і вердикти, включно з межею рівно 500 ГБ ──────
assert (
    NB22_LIMITS["файлів на коміт"] == 100
    and NB22_LIMITS["файлів на репозиторій"] == 100_000
    and NB22_LIMITS["розмір файлу (рекомендація)"] == 200 * NB22_GB
    and NB22_LIMITS["розмір файлу (жорстка межа)"] == 500 * NB22_GB
    and nb22_verdict(560 * NB22_GB) == "ВІДМОВА: понад 500 GB"
    and nb22_verdict(260 * NB22_GB) == "ризик: понад 200 GB"
    and nb22_verdict(500 * NB22_GB) == "ризик: понад 200 GB"   # рівно 500 ГБ — ще не відмова
    and nb22_verdict(4.9 * NB22_GB) == "ок"
    and round(sum(nb22_size for _, nb22_size in NB22_FILES) / NB22_GB, 2) == 869.21
), "ліміти зі storage-limits; відмова лише за межею >500 ГБ"
print("✓ ліміти: 100 файлів на коміт; 260 ГБ — ризик, 560 ГБ — відмова, разом 869.21 ГБ")

# ── 4. LFS-вказівник у git і розбиття теки на коміти ────────────────────
assert (
    nb22_pointer_bytes == 133 and nb22_blob == 440_449_768
    and NB22_POINTER.startswith("version https://git-lfs.github.com/spec/v1")
    and "oid sha256:" in NB22_POINTER and "size 440449768" in NB22_POINTER
    and nb22_pointer_bytes / nb22_blob * 100 < 0.001        # сота частка відсотка
    and -(-250 // NB22_LIMITS["файлів на коміт"]) == 3
    and -(-5_000 // NB22_LIMITS["файлів на коміт"]) == 50
    and -(-100_000 // NB22_LIMITS["файлів на коміт"]) == 1000
), "у git лежить вказівник (133 Б), а не сам блоб; коміти — по ≤100 файлів"
print(f"✓ у git лежить вказівник {nb22_pointer_bytes} Б = "
      f"{nb22_pointer_bytes / nb22_blob * 100:.6f}% обсягу блобу; "
      "250/5 000/100 000 файлів → 3/50/1 000 комітів")

# ── 5. CDC локалізує вставку, фіксовані чанки втрачають половину файлу ──
nb22_fx = nb22_transfer(nb22_fixed(nb22_blob_a), nb22_fixed(nb22_blob_b))
nb22_cd = nb22_transfer(nb22_cdc(nb22_blob_a), nb22_cdc(nb22_blob_b))
assert (
    len(nb22_blob_a) == NB22_SEGMENTS * NB22_SEGMENT == 2_097_152
    and len(nb22_blob_b) == len(nb22_blob_a) + NB22_SEGMENT
    and nb22_fx[1] == 129 and nb22_cd[1] == 1
    and round(nb22_fx[2] / 1024, 1) == 1024.5 and round(nb22_cd[2] / 1024, 1) == 11.5
    and nb22_cd[2] * 20 < nb22_fx[2]
), "вставка 512 Б: фіксовані чанки передають ~половину файлу, CDC — один чанк"
print(f"✓ вставка {NB22_SEGMENT} Б у 2 МБ: фіксовані {nb22_fx[2] / 1024:.1f} КБ, "
      f"CDC {nb22_cd[2] / 1024:.1f} КБ ({nb22_fx[2] / nb22_cd[2]:.0f}× менше)")

# ── 6. Межі чанків CDC дотримані, сума дорівнює файлу ───────────────────
nb22_chunks = nb22_cdc(nb22_blob_a)
assert (
    all(len(nb22_chunk) <= NB22_MAX for nb22_chunk in nb22_chunks)
    and all(len(nb22_chunk) >= NB22_MIN for nb22_chunk in nb22_chunks[:-1])
    and sum(len(nb22_chunk) for nb22_chunk in nb22_chunks) == len(nb22_blob_a)
    and len(nb22_chunks) == 237
), "CDC мусить тримати довжину чанка в межах min/max і не губити байтів"
print(f"✓ CDC: {len(nb22_chunks)} чанків, усі в межах {NB22_MIN}–{NB22_MAX} Б, сума = файл")

# ── 7. На суцільній ділянці CDC не дає виграшу — він не стискає ─────────
nb22_fx_c = nb22_transfer(nb22_fixed(nb22_blob_a), nb22_fixed(nb22_blob_c))
nb22_cd_c = nb22_transfer(nb22_cdc(nb22_blob_a), nb22_cdc(nb22_blob_c))
assert abs(nb22_fx_c[2] - nb22_cd_c[2]) / nb22_fx_c[2] < 0.02, \\
    "на 20% суцільної зміни обидві схеми мусять передати майже однаковий обсяг"
print(f"✓ 20% перегенеровано: фіксовані {nb22_fx_c[2] / 1024:.1f} КБ, "
      f"CDC {nb22_cd_c[2] / 1024:.1f} КБ — різниці немає")

# ── 8. Арифметика джерел: ×977, 305 176 чанків, 1515 блоків, ×1.969 ─────
nb22_ratio = (20 * NB22_GB2 / NB22_CHUNK) / (20 * NB22_GB2 / NB22_BLOCK)
assert (
    NB22_CHUNK == 64 * 1024 and NB22_BLOCK == 64 * 10 ** 6 and NB22_CAS_FACTOR == 1000
    and round(nb22_ratio) == 977
    and round(20 * NB22_GB2 / NB22_CHUNK) == 305_176
    and round(20 * NB22_GB2 / 64_000) == 312_500        # так рахує документація (KB)
    and NB22_JOURNAL["блоків у gemma-2-9b-it-GGUF"] == 1515
    and round(1515 * NB22_BLOCK / NB22_GB2, 2) == 96.96  # у блозі — «приблизно 97 ГБ»
    and NB22_JOURNAL["стиснення репозиторію, разів"] == 1.969
    and round(NB22_ORIGINAL / NB22_STORED, 3) == 1.969
), "×977 наш розрахунок проти ×1000 у блозі (KB проти KiB); 1515 блоків ≈ 97 ГБ"
print("✓ чанки/блоки: 305 176 чанків на 20 ГБ → ×977; gemma-2-9b-it-GGUF: "
      "1515 блоків → 96.96 ГБ, стиснення 191/97 = 1.969×")

# ── 9. Ефективна швидкість однакова; підпис «@ 50MB/s» не підтверджується ─
nb22_rate_orig = 191 * NB22_GB2 / (509 * 60) / 10 ** 6
nb22_rate_xet = 97 * NB22_GB2 / (258 * 60) / 10 ** 6
assert (
    round(nb22_rate_orig, 2) == 6.25 and round(nb22_rate_xet, 2) == 6.27
    and abs(nb22_rate_orig - nb22_rate_xet) < 0.1        # обидва рядки — та сама швидкість
    and nb22_rate_orig < 10                              # 50 МБ/с арифметикою не підтверджується
    and round(191 * (1 - 0.508), 1) == 94.0              # 50.8% спільних чанків → 94 ГБ
), "обидва рядки блогу дають ту саму ефективну швидкість"
print(f"✓ швидкість: {nb22_rate_orig:.2f} і {nb22_rate_xet:.2f} МБ/с (не 50); "
      "локальний кеш чанків лишає 94.0 ГБ із 191 ГБ")

# ── 10. Правила злиття [tool.hf-jobs]: флаг перемагає, колекції доповнюються ─
assert (
    NB22_RESOLVED["flavor"] == ("l4x4", "флаг")
    and NB22_RESOLVED["image"] == ("vllm/vllm-openai:unlimited-ocr", "script")
    and NB22_RESOLVED["env"] == ({"BATCH": "32", "DEBUG": "1"}, "обидва")
    and NB22_RESOLVED["labels"] == ({"model": "Qwen3-06B", "team": "ml"}, "обидва")
    and NB22_RESOLVED["secrets"] == (["HF_TOKEN"], "script")
    and NB22_RESOLVED["timeout"] == ("2h", "флаг")
    and NB22_MERGED_KEYS == {"env", "secrets", "labels", "volumes"}
), "явний прапорець перемагає; env/secrets/labels/volumes доповнюються по елементах"
print("✓ злиття: flavor l4x1→l4x4 (флаг), env {BATCH:32, DEBUG:1} (обидва), secrets зі скрипта")

# ── 11. Ціни Jobs: хвилина × 60 = година, білінг лише під час Running ───
assert (
    round(NB22_PRICES["a10g-small"] * 60, 2) == 1.0
    and round(NB22_PRICES["h200x8"] * 1440, 2) == 960.05
    and NB22_PRICES["cpu-basic"] < NB22_PRICES["t4-small"] < NB22_PRICES["a10g-small"]
    and NB22_TIMEOUT_MIN == 30
), "ціни з jobs-pricing і типовий таймаут 30 хв"
print("✓ ціни: a10g-small $1.00/год, h200x8 за добу $960.05; білінг лише в Starting/Running")

# ── 12. Міграція v1.0: заміни на місці; CI-скрипт зібрано правильно ─────
nb22_migr = dict(NB22_REMOVED)
assert (
    len(NB22_REMOVED) == 17
    and nb22_migr["huggingface-cli"] == "hf"
    and nb22_migr["use_auth_token="] == "token="
    and nb22_migr["constants.hf_cache_home"] == "змінна середовища HF_HOME"
    and nb22_migr["hf cache scan / hf cache delete"] == "hf cache ls / rm / prune"
    and NB22_CI.splitlines()[0] == "#!/usr/bin/env bash"
    and NB22_CI.splitlines()[1] == "set -euo pipefail"
    and "HF_HUB_DISABLE_UPDATE_CHECK=1" in NB22_CI
    and "hf jobs wait" in NB22_CI
    and "secrets.HF_TOKEN" in NB22_WORKFLOW
), "таблиця «було → стало» з concepts/migration; CI: жорсткий режим bash і гейт jobs wait"
print("✓ міграція: 17 рядків «було → стало»; CI-скрипт: set -euo pipefail, "
      "HF_HUB_DISABLE_UPDATE_CHECK=1, гейт hf jobs wait")

# ── 13. Скрипт справді проходить перевірку синтаксису ───────────────────
if "bash -n" in NB22_JOURNAL:                 # bash може бути відсутній у середовищі
    assert NB22_JOURNAL["bash -n"] == "код 0", "bash -n мусить дати код 0"
    print("✓ bash -n → код 0: синтаксис згенерованого CI-скрипта чинний")

# ── 14. Workflow розібрано в словник із чотирьох кроків ─────────────────
if "кроків у workflow" in NB22_JOURNAL:       # PyYAML може бути не встановлений
    assert NB22_JOURNAL["кроків у workflow"] == 4, "yaml.safe_load мусить дати 4 кроки"
    print("✓ workflow: 4 кроки, токен із secrets.HF_TOKEN, розібрано yaml.safe_load")

print()
print("Усі перевірки пройдено.")
'''
    ),

    # ── Підсумок ─────────────────────────────────────────────────────────
    md(
        """
## Підсумок

Нижче — знімок журналу: кожна секція записала в нього результат через `nb22_log()`, який перезаписує
ключ, а не додає елемент. Тому повторний запуск будь-якої клітинки не дублює записи.
"""
    ),
    code(
        '''
# ── Підсумок ── знімок журналу (не список посилань).
print(f"{'показник':44}{'значення'}")
print("-" * 72)
for nb22_jkey in sorted(NB22_JOURNAL):
    print(f"{nb22_jkey:44}{NB22_JOURNAL[nb22_jkey]}")
print("-" * 72)
print(f"Усього показників: {len(NB22_JOURNAL)}")
'''
    ),
    md(
        """
**Куди далі:**

- Розділ 09 — prompt caching: інший вид економії на повторюваних даних (префікс, а не чанки).
- Розділ 10 — батчі: як планувати офлайн-обробку датасетів.
- Розділ 19 — Transformers v5: сумісність із лінійкою `huggingface_hub` v1+.
- Розділ 21 — fine-tuning: сценарій, для якого найчастіше й беруть Jobs.
- Розділ 24 — евалюація: що запускати в Jobs, щоб результат був відтворюваний.

## Джерела

- [`hf` CLI — керівництво](https://huggingface.co/docs/huggingface_hub/en/guides/cli)
- [`hf` CLI — довідник команд](https://huggingface.co/docs/huggingface_hub/en/package_reference/cli)
- [Запуск і керування Jobs](https://huggingface.co/docs/huggingface_hub/en/guides/jobs)
- [Jobs: конфігурація](https://huggingface.co/docs/hub/en/jobs-configuration), [ціни](https://huggingface.co/docs/hub/en/jobs-pricing), [керування](https://huggingface.co/docs/hub/en/jobs-manage)
- [Xet — дедуплікація](https://huggingface.co/docs/hub/en/xet/deduplication)
- [From Chunks to Blocks](https://huggingface.co/blog/from-chunks-to-blocks)
- [Storage limits](https://huggingface.co/docs/hub/en/storage-limits)
- [Міграція на v1.0](https://huggingface.co/docs/huggingface_hub/concepts/migration)
- [Змінні середовища](https://huggingface.co/docs/huggingface_hub/en/package_reference/environment_variables)
- [`huggingface_hub` на PyPI — 2.0.0](https://pypi.org/pypi/huggingface_hub/json)

Локальні копії: `research/hf5_hub_cli.txt`, `research/hf5_cli_ref.txt`, `research/hf5_jobs.txt`,
`research/hf5_xet.txt`, `research/hub_v1_blog.txt`, `research/hf5_hub_migration.txt`, `research/22/*.md`.
"""
    ),
]
