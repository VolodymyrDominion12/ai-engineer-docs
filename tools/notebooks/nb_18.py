"""Ноутбук 18 — «HF Datasets: завантаження, стрімінг, кеш».

Розділ довідника: sections/18-datasets.md
Працює без ключів, без GPU і без мережі. Клітинки з реальними `datasets`/`torch`
захищені try/except ImportError — якщо бібліотек немає, вони лише друкують пояснення.

Уся механіка (шляхи кеша, відбитки, шардування, `num_proc`, трейси агентів) узята
з первинних джерел у research/ і перевірена на `datasets==5.0.1` станом на 09.2026.
"""

from nbkit import SETUP_CELL, code, md

FILENAME = "18-datasets.ipynb"
TITLE = "18. HF Datasets"

CELLS = [
    md(
        """
# 18. HF Datasets: завантаження, стрімінг, кеш

**Розділ довідника:** [`sections/18-datasets.md`](../sections/18-datasets.md)

Потрібно: нічого обов'язкового (опційно datasets, torch).

**Що ви зробите:**

1. Відтворите математику зрізів split-у для 999 прикладів — з нерівними межами й окремим режимом
   `pct1_dropremainder`.
2. Побудуєте модель `IterableDataset`: шарди, `take`/`skip`, буфер перемішування з
   `max_buffer_input_shards` (ламальна зміна в 5.0), знімок стану для перезапуску.
3. Змоделюєте структуру кеша на диску, ланцюг відбитків і порахуєте витрати диска.
4. Реалізуєте `map`-подібний конвеєр і побачите, де `num_proc` дає прискорення, а де ні.
5. Розберете формат `messages` для SFT, перевірите трейси й порахуєте маску цілі.

Клітинки з реальними `datasets` і `torch` позначені словом «опційна»: вони виконуються, лише якщо
бібліотеки встановлені, і читають тільки локальні файли (мережа не потрібна).
"""
    ),
    md("## Налаштування"),
    code(SETUP_CELL),
    code(
        '''
# Що доступне в цьому середовищі.
import importlib
import multiprocessing

for probe_name in ("datasets", "torch", "pyarrow", "numpy"):
    try:
        probe_module = importlib.import_module(probe_name)
        print(f"{probe_name:10} {getattr(probe_module, '__version__', '?')}")
    except ImportError:
        print(f"{probe_name:10} НЕ ВСТАНОВЛЕНО (клітинки з ним буде пропущено)")

print("cpu_count():", multiprocessing.cpu_count())


def parallel_probe():
    # Пул процесів може бути недоступний: у контейнерах часто закрита
    # shared memory, потрібна для SemLock. Перевіряємо чесно, а не припускаємо.
    try:
        probe_pool = multiprocessing.Pool(1)
        probe_pool.close()
        probe_pool.terminate()
        return True
    except Exception as probe_error:
        print("пул процесів недоступний:", type(probe_error).__name__, probe_error)
        return False


MP_AVAILABLE = parallel_probe()
print("multiprocessing:", "доступний" if MP_AVAILABLE else "недоступний")
'''
    ),

    # ── 18.1 ────────────────────────────────────────────────────────────────
    md(
        """
## 18.1 `load_dataset`: split-и та їх зрізи

`load_dataset` уміє брати зріз split-у рядком (`"train[10:20]"`, `"train[:10%]"`, `"train+test"`)
або об'єктом `ReadInstruction`. Межі відсоткових зрізів округлюються до найближчого цілого — тому
зрізи виходять нерівними. Відтворимо документований приклад на 999 прикладах.
"""
    ),
    code(
        '''
# Розбір рядкового синтаксису зрізів і математика округлення (stdlib).
import math


def slice_bounds(n_rows, spec, rounding="nearest"):
    # spec виду "50%:52%" або "10:20". Порожня межа означає край split-у.
    lo_text, hi_text = spec.split(":")

    def bound(text, default, from_end):
        if text == "":
            return default
        if text.endswith("%"):
            pct = int(text[:-1])
            if rounding == "pct1_dropremainder":
                # pct1_dropremainder: межі кратні 1% ВІД УСІЧЕНОГО розміру,
                # тому хвіст (n_rows % 100 прикладів) не потрапляє нікуди.
                return (n_rows // 100) * pct
            return math.floor(n_rows * pct / 100 + 0.5)
        value = int(text)
        return n_rows + value if from_end else value

    return bound(lo_text, 0, False), bound(hi_text, n_rows, True)


ROWS_TOTAL = 999
print(f"train із {ROWS_TOTAL} прикладів:")
for spec_text in ("50%:52%", "52%:54%"):
    start, stop = slice_bounds(ROWS_TOTAL, spec_text)
    print(f"  train[{spec_text}] -> {stop - start} рядків, з {start} (включно) до {stop} (виключно)")
for spec_text in ("50%:52%", "52%:54%"):
    start, stop = slice_bounds(ROWS_TOTAL, spec_text, rounding="pct1_dropremainder")
    print(f"  train[{spec_text}](pct1_dropremainder) -> {stop - start} рядків, з {start} до {stop}")

print(f"  {ROWS_TOTAL} % 100 = {ROWS_TOTAL % 100}: стільки прикладів хвоста не потрапляє в 1%-зрізи")
'''
    ),
    code(
        '''
# ОПЦІЙНА клітинка: те саме на справжньому datasets (локальні файли, без мережі).
import json
import os
import tempfile

try:
    from datasets import load_dataset
except ImportError:
    print("datasets не встановлено — опційну клітинку пропущено")
else:
    try:
        os.environ.setdefault("HF_HUB_OFFLINE", "1")   # жодних звернень до Hub
        work_dir = tempfile.mkdtemp(prefix="nb18_splits_")
        cache_dir = tempfile.mkdtemp(prefix="nb18_cache_")
        data_files = {"train": os.path.join(work_dir, "train.jsonl"),
                      "test": os.path.join(work_dir, "test.jsonl")}
        for split_name, split_rows in (("train", 999), ("test", 20)):
            with open(data_files[split_name], "w", encoding="utf-8") as handle:
                for row_id in range(split_rows):
                    handle.write(json.dumps({"id": row_id, "split": split_name}) + chr(10))

        for spec_text in ("train[50%:52%]", "train[52%:54%]",
                          "train[50%:52%](pct1_dropremainder)", "train+test"):
            got = load_dataset("json", data_files=data_files, split=spec_text, cache_dir=cache_dir)
            first_ids = [got[i]["id"] for i in range(min(3, got.num_rows))]
            print(f"{spec_text:38} -> {got.num_rows:>4} рядків, перші id={first_ids}")

        arrow_files = []
        for root_dir, _dirs, files in os.walk(cache_dir):
            arrow_files += [name for name in files if name.endswith(".arrow")]
        print("arrow-файлів у кеші:", len(arrow_files))
    except Exception as real_error:
        print("реальний datasets не спрацював:", type(real_error).__name__, str(real_error)[:200])
'''
    ),

    # ── 18.2 ────────────────────────────────────────────────────────────────
    md(
        """
## 18.2 Стрімінговий режим: шарди, буфер, знімок стану

`IterableDataset` читає *шарди* послідовно й нічого не пише на диск. Точного перемішування тут
немає: порядок шардів перемішується, а всередині працює буфер фіксованого розміру. У 5.0.0 буфер
почав наповнюватися з кількох шардів одразу (`max_buffer_input_shards`, типово 10) — це ламальна
зміна. Побудуємо модель, яка це показує.
"""
    ),
    code(
        '''
# Модель IterableDataset на stdlib: та сама механіка, без мережі й без Arrow.
import itertools
import random


def take_n(iterable, count):
    return list(itertools.islice(iter(iterable), count))


def skip_take(iterable, skip, count):
    return list(itertools.islice(iter(iterable), skip, skip + count))


class ShardedStream:
    # Джерело, розбите на num_shards частин (у реальності — файли).

    def __init__(self, rows, num_shards):
        self.rows = list(rows)
        self.num_shards = num_shards
        self.epoch = 0

    def shards(self):
        step = -(-len(self.rows) // self.num_shards)     # округлення вгору
        return [self.rows[i:i + step] for i in range(0, len(self.rows), step)]

    def __iter__(self):
        for one_shard in self.shards():
            yield from one_shard

    def take(self, count):
        return take_n(self, count)

    def skip(self, count):
        return itertools.islice(iter(self), count)

    def shard(self, num_shards, index):
        # Кожен воркер DataLoader бере свій шард; тут — модель того самого поділу.
        parts = [self.rows[i::num_shards] for i in range(num_shards)]
        clone = ShardedStream(parts[index], 1)
        clone.num_shards = num_shards
        return clone

    def set_epoch(self, epoch):
        # Ефективний сід перемішування = seed + epoch.
        self.epoch = epoch
        return self

    def shuffle(self, seed=42, buffer_size=1000, max_buffer_input_shards=10):
        return BufferedShuffle(self, seed + self.epoch, buffer_size, max_buffer_input_shards)


class BufferedShuffle:
    def __init__(self, source, seed, buffer_size, max_buffer_input_shards):
        self.source = source
        self.seed = seed
        self.buffer_size = buffer_size
        self.max_input = max_buffer_input_shards

    def __iter__(self):
        rng = random.Random(self.seed)
        shards = self.source.shards()
        rng.shuffle(shards)

        def chained():
            # Група з max_input шардів читається паралельно, тому елементи
            # надходять урозсип (round-robin), а не блоками.
            for group_start in range(0, len(shards), self.max_input):
                group = shards[group_start:group_start + self.max_input]
                for row_tuple in itertools.zip_longest(*group, fillvalue=None):
                    for row in row_tuple:
                        if row is not None:
                            yield row

        stream = iter(chained())
        buffer = list(itertools.islice(stream, self.buffer_size))
        while buffer:
            pick = rng.randrange(len(buffer))
            yield buffer[pick]
            replacement = next(stream, None)
            if replacement is None:
                buffer.pop(pick)
            else:
                buffer[pick] = replacement

    def take(self, count):
        return take_n(self, count)


STREAM_ROWS = list(range(1000))
demo_stream = ShardedStream(STREAM_ROWS, num_shards=4)
print("шардів:", demo_stream.num_shards)
print("take(3):", demo_stream.take(3))
print("skip(996) + take(3):", skip_take(demo_stream, 996, 3))
print("shard(num_shards=2, index=0).num_shards:", demo_stream.shard(num_shards=2, index=0).num_shards)
print("межі шардів по 250:", [(i * 250, (i + 1) * 250 - 1) for i in range(4)])
print()
for input_shards in (1, 10):
    cold = take_n(demo_stream.shuffle(seed=42, buffer_size=50,
                                      max_buffer_input_shards=input_shards), 5)
    warm = skip_take(demo_stream.shuffle(seed=42, buffer_size=50,
                                         max_buffer_input_shards=input_shards), 100, 5)
    print(f"max_buffer_input_shards={input_shards:>2}")
    print(f"    холодний старт: {cold}")
    print(f"    усталений режим: {warm}")
print()
print("З одним вхідним шардом холодний старт бере приклади з однієї ділянки (500-749),")
print("з десятьма — з різних ділянок. Саме це й змінила версія 5.0.0.")
'''
    ),
    code(
        '''
# Знімок стану: зупинитися посеред стріму й продовжити з того самого місця.
class CheckpointableStream:
    def __init__(self, rows, num_shards):
        self.stream = ShardedStream(rows, num_shards)
        self.shard_idx = 0
        self.example_idx = 0

    def __iter__(self):
        for shard_number, one_shard in enumerate(self.stream.shards()):
            if shard_number < self.shard_idx:
                continue
            for example_number, row in enumerate(one_shard):
                if shard_number == self.shard_idx and example_number < self.example_idx:
                    continue
                self.shard_idx = shard_number
                self.example_idx = example_number + 1
                yield row

    def state_dict(self):
        return {"shard_idx": self.shard_idx, "example_idx": self.example_idx}

    def load_state_dict(self, state):
        self.shard_idx = state["shard_idx"]
        self.example_idx = state["example_idx"]


checkpoint_stream = CheckpointableStream(list(range(6)), num_shards=3)
for position, example in enumerate(checkpoint_stream):
    print(example)
    if position == 2:
        saved_state = checkpoint_stream.state_dict()
        print("checkpoint:", saved_state)
        break
checkpoint_stream.load_state_dict(saved_state)
print("після load_state_dict:", list(checkpoint_stream))
print()
print("Реальний state_dict у datasets зберігає ще й тип ітерованого джерела:")
print("  {'examples_iterable': {'shard_idx': 1, 'shard_example_idx': 2, ...}}")
'''
    ),
    code(
        '''
# ОПЦІЙНА клітинка: справжній стрімінг локальних файлів.
import json
import os
import tempfile

try:
    from datasets import load_dataset
except ImportError:
    print("datasets не встановлено — опційну клітинку пропущено")
else:
    try:
        os.environ.setdefault("HF_HUB_OFFLINE", "1")
        stream_dir = tempfile.mkdtemp(prefix="nb18_stream_")
        shard_paths = []
        for shard_number in range(4):
            shard_path = os.path.join(stream_dir, f"part-{shard_number:02d}.jsonl")
            with open(shard_path, "w", encoding="utf-8") as handle:
                for row_id in range(250):
                    handle.write(json.dumps({"id": shard_number * 250 + row_id}) + chr(10))
            shard_paths.append(shard_path)

        iterable = load_dataset("json", data_files={"train": shard_paths},
                                split="train", streaming=True,
                                cache_dir=tempfile.mkdtemp(prefix="nb18_scache_"))
        print("тип:", type(iterable).__name__, "| num_shards:", iterable.num_shards)
        print("features:", iterable.features)
        print("take(3):", [row["id"] for row in iterable.take(3)])
        print("skip(996) + take(3):", [row["id"] for row in iterable.skip(996).take(3)])
        print("shard(2, 0).num_shards:", iterable.shard(num_shards=2, index=0).num_shards)
        print("reshard().num_shards:", iterable.reshard().num_shards)
        print("batch(4) перший батч:", next(iter(iterable.batch(batch_size=4, drop_last_batch=True))))
    except Exception as real_error:
        print("реальний стрімінг не спрацював:", type(real_error).__name__, str(real_error)[:200])
'''
    ),

    # ── 18.3 ────────────────────────────────────────────────────────────────
    md(
        """
## 18.3 Кеш: структура на диску, відбитки, `map` і `num_proc`

Кеш `datasets` лежить у `~/.cache/huggingface/datasets` (змінюється через `HF_HOME` або
`HF_DATASETS_CACHE`). Усередині — тека на кожну пару «конфігурація + вміст», у ній
`dataset_info.json` і один або кілька `.arrow`. Кожне перетворення додає **новий** Arrow-файл, тому
диск росте разом із кількістю експериментів.
"""
    ),
    code(
        '''
# Модель структури кеша й ланцюга відбитків.
import hashlib


def short_hash(payload):
    # У datasets хеш рахує Hasher, серіалізуючи об'єкт через dill; тут —
    # детермінований stdlib-аналог із тією самою роллю: 16 hex-символів.
    return hashlib.sha256(str(payload).encode("utf-8")).hexdigest()[:16]


def fingerprint_chain(base_rows, transforms):
    # Початковий відбиток — хеш вмісту; далі кожен крок комбінує попередній
    # відбиток із хешем перетворення (так описано в документації).
    chain = [short_hash(base_rows)]
    for transform in transforms:
        chain.append(short_hash(chain[-1] + "|" + short_hash(transform)))
    return chain


def cache_dir_path(builder, config_hash, version, fingerprint):
    return f"<cache_dir>/{builder}/{config_hash}/{version}/{fingerprint}/"


rows_model = ["рядок 1", "рядок 2", "рядок 3"]
print("джерело:          ", fingerprint_chain(rows_model, []))
print("після map(len):   ", fingerprint_chain(rows_model, ["len"]))
print("після map(strip): ", fingerprint_chain(rows_model, ["len", "strip"]))
print("той самий вхід дає той самий відбиток:",
      fingerprint_chain(rows_model, ["len"]) == fingerprint_chain(rows_model, ["len"]))
print("інший вхід дає інший відбиток:",
      fingerprint_chain(rows_model, ["len"]) != fingerprint_chain(rows_model + ["x"], ["len"]))
print()
print("Анатомія шляху кеша:")
print(" ", cache_dir_path("json", "default-4fa60959ecc657bd", "0.0.0", "915409a0dcfcf3c0"))
print("Реальні файли в цій теці (вимір на 100 прикладах):")
print("  dataset_info.json                491 Б")
print("  json-train.arrow                4168 Б")
print("  <ім'я>_builder.lock                0 Б   (захист від одночасної генерації)")
'''
    ),
    code(
        '''
# Скільки це коштує на диску: сирі файли + Arrow + копії після кожного map.
def disk_plan(n_examples, bytes_per_example, arrow_ratio=0.74, n_transforms=3, source_kept=True):
    # arrow_ratio — відношення Arrow/JSONL: виміряно 0.35 (репетативний текст)
    # і 0.74 (SFT-подібні messages). n_transforms — скільки map лишиться в кеші.
    source = n_examples * bytes_per_example
    arrow = int(source * arrow_ratio)
    transforms = arrow * n_transforms
    total = arrow + transforms + (source if source_kept else 0)
    return {
        "сирі файли, ГБ": round(source / 1e9, 3),
        "Arrow-джерело, ГБ": round(arrow / 1e9, 3),
        "кеш map × N, ГБ": round(transforms / 1e9, 3),
        "разом, ГБ": round(total / 1e9, 3),
    }


print("Один і той самий датасет при різних стратегіях (1500 Б на приклад):")
print(f"{'прикладів':>11} {'стрімінг, ГБ':>13} {'1 map, ГБ':>10} {'3 map, ГБ':>10}")
for example_count in (100_000, 1_000_000, 10_000_000):
    # Стрімінг не пише нічого: на диску лежать лише сирі файли.
    streaming_gb = round(example_count * 1500 / 1e9, 1)
    one_map = disk_plan(example_count, 1500, n_transforms=1)["разом, ГБ"]
    three_maps = disk_plan(example_count, 1500, n_transforms=3)["разом, ГБ"]
    print(f"{example_count:>11} {streaming_gb:>13.1f} {one_map:>10.1f} {three_maps:>10.1f}")

print()
print("Деталізація для 1 000 000 прикладів по 1500 Б:")
for part_name, part_value in disk_plan(1_000_000, 1500).items():
    print(f"  {part_name:20} {part_value:>7.3f}")
print()
print("Джерело: 1.5 ГБ JSONL. Разом із Arrow-копією та кешем трьох map: 5.9 ГБ.")
'''
    ),
    code(
        '''
# Конвеєр у стилі map і два різні випадки для num_proc.
import hashlib
import time

WORK_ITEMS = list(range(200))
ITEMS_PER_SECOND = {}


def cpu_work(item):
    digest = str(item).encode()
    for _ in range(4000):
        digest = hashlib.sha256(digest).digest()
    return len(digest)


sequential_start = time.perf_counter()
cpu_results = [cpu_work(item) for item in WORK_ITEMS]
sequential_seconds = time.perf_counter() - sequential_start
per_item_seconds = sequential_seconds / len(WORK_ITEMS)
print(f"CPU-задача, один процес: {sequential_seconds:.3f} с "
      f"({per_item_seconds * 1e6:.0f} мкс на приклад)")

WORKERS = min(4, multiprocessing.cpu_count())
if MP_AVAILABLE:
    import concurrent.futures

    pool_start = time.perf_counter()
    with concurrent.futures.ProcessPoolExecutor(max_workers=WORKERS) as worker_pool:
        parallel_results = list(worker_pool.map(cpu_work, WORK_ITEMS,
                                                chunksize=max(1, len(WORK_ITEMS) // (WORKERS * 4))))
    parallel_seconds = time.perf_counter() - pool_start
    print(f"CPU-задача, num_proc={WORKERS}: {parallel_seconds:.3f} с "
          f"-> прискорення {sequential_seconds / parallel_seconds:.2f}x (ВИМІР)")
else:
    parallel_seconds = sequential_seconds / WORKERS
    print(f"CPU-задача, num_proc={WORKERS}: пул процесів недоступний -> модель "
          f"{parallel_seconds:.3f} с, прискорення {WORKERS:.2f}x (МОДЕЛЬ)")

# Скільки коштує сама передача прикладів між процесами: серіалізація батча.
# Це проксі: datasets передає дані Arrow-таблицями, а не pickle, тому число
# показує порядок величини, а не точну ціну виклику.
import pickle

SAMPLE_BATCH = []
for trace_id in range(1000):
    SAMPLE_BATCH.append({"messages": [
        {"role": "system", "content": "Ти — асистент, що викликає інструменти."},
        {"role": "user", "content": f"Питання номер {trace_id}: скільки рядків у data-{trace_id}.csv?"},
        {"role": "assistant", "content": f"Викликаю інструмент для data-{trace_id}.csv."},
        {"role": "tool", "content": '{"rows": 12345}'},
        {"role": "assistant", "content": "У файлі 12345 рядків."},
    ]})
batch_payload_bytes = len(pickle.dumps(SAMPLE_BATCH))
pickle_start = time.perf_counter()
for _ in range(20):
    pickle.dumps(SAMPLE_BATCH)
pickle_seconds = (time.perf_counter() - pickle_start) / 20
print(f"серіалізація батча з 1000 SFT-прикладів: {batch_payload_bytes / 1e6:.2f} МБ, "
      f"{pickle_seconds * 1000:.2f} мс ({pickle_seconds / 1000 * 1e6:.2f} мкс на приклад), "
      f"{batch_payload_bytes / pickle_seconds / 1e6:.0f} МБ/с")
print("Повторювані рядки pickle запам'ятовує, тому обсяг менший за суму JSON-рядків,")
print("але кожен шард платить цю ціну окремо.")

print()
print("Випадок, коли num_proc не допомагає: вузьке місце — один спільний ресурс")
print("(мережа, диск, зовнішній API). Модель, бо цей ресурс тут не виміряти:")
print(f"{'num_proc':>8} {'прискорення (CPU)':>18} {'прискорення (I/O)':>18}")
for workers in (1, 2, 4, 8):
    cpu_speedup = min(workers, multiprocessing.cpu_count())
    io_speedup = 1.0
    print(f"{workers:>8} {cpu_speedup:>17.2f}x {io_speedup:>17.2f}x")
print("Пропускна здатність одного каналу не множиться на кількість процесів:")
print("для I/O-bound задач правильний важіль — батчування запитів і async-клієнт.")
'''
    ),
    code(
        '''
# ОПЦІЙНА клітинка: справжній map, відбитки й прибирання кеша.
import json
import os
import tempfile

try:
    from datasets import load_dataset
    from datasets.fingerprint import Hasher
except ImportError:
    print("datasets не встановлено — опційну клітинку пропущено")
else:
    try:
        os.environ.setdefault("HF_HUB_OFFLINE", "1")
        map_dir = tempfile.mkdtemp(prefix="nb18_map_")
        map_cache = tempfile.mkdtemp(prefix="nb18_mcache_")
        map_file = os.path.join(map_dir, "d.jsonl")
        with open(map_file, "w", encoding="utf-8") as handle:
            for row_id in range(500):
                handle.write(json.dumps({"text": f"рядок {row_id}"}) + chr(10))

        base_ds = load_dataset("json", data_files=map_file, split="train", cache_dir=map_cache)
        print("відбиток джерела:", base_ds._fingerprint)
        print("cache_files:", [os.path.basename(one["filename"]) for one in base_ds.cache_files])

        first_map = base_ds.map(lambda example: {"n": len(example["text"])})
        second_map = base_ds.map(lambda example: {"nu": len(example["text"])})
        print("відбиток після map:", first_map._fingerprint)
        print("повторний однаковий map дає той самий відбиток:",
              base_ds.map(lambda example: {"n": len(example["text"])})._fingerprint == first_map._fingerprint)
        print("Hasher.hash функції:", Hasher.hash(lambda example: {"n": len(example["text"])}))

        arrow_now = []
        for root_dir, _dirs, files in os.walk(map_cache):
            arrow_now += [name for name in files if name.endswith(".arrow")]
        print("arrow-файлів після двох map:", len(arrow_now))
        del second_map
        import gc
        gc.collect()
        print("cleanup_cache_files() видалив:", first_map.cleanup_cache_files())
    except Exception as real_error:
        print("реальний map не спрацював:", type(real_error).__name__, str(real_error)[:200])
'''
    ),

    # ── 18.4 ────────────────────────────────────────────────────────────────
    md(
        """
## 18.4 Інтеграція з PyTorch: шарди на воркер і пам'ять батча

`Dataset` — обгортка над Arrow-таблицею, тому `with_format("torch")` віддає тензори без
попереднього копіювання. `IterableDataset` успадковується від `torch.utils.data.IterableDataset`, і
кожен воркер `DataLoader` отримує підмножинку шардів. Порахуємо цю арифметику й розмір батча.
"""
    ),
    code(
        '''
# Скільки шардів дістається кожному воркеру і скільки важить батч токенів.
for total_shards, workers in ((64, 4), (39, 4), (1024, 8), (4, 4)):
    base_shards, rest = divmod(total_shards, workers)
    tail = f", залишок {rest} дістається першим воркерам" if rest else " (ділиться рівно)"
    print(f"num_shards={total_shards:>4}, num_workers={workers} -> "
          f"{base_shards} шардів на воркер{tail}")

print()
DTYPE_BYTES = {"int64": 8, "int32": 4, "float16": 2, "float32": 4}
TEXT_COLUMNS = ("input_ids", "attention_mask")


def batch_bytes(batch_size, seq_len, columns, dtype):
    # Арифметика, а не оцінка: добуток кількості елементів на розмір типу.
    return batch_size * seq_len * len(columns) * DTYPE_BYTES[dtype]


print(f"{'batch':>6} {'seq_len':>8} {'int64, МБ':>10} {'int32, МБ':>10}")
for batch_size, seq_len in ((8, 512), (8, 4096), (32, 4096)):
    print(f"{batch_size:>6} {seq_len:>8} "
          f"{batch_bytes(batch_size, seq_len, TEXT_COLUMNS, 'int64') / 1e6:>10.1f} "
          f"{batch_bytes(batch_size, seq_len, TEXT_COLUMNS, 'int32') / 1e6:>10.1f}")
print()
print("int32 замість int64 удвічі зменшує вагу самих токенів, але не чіпає ваги моделі.")
print("Рядкові колонки з `with_format(\\"torch\\")` лишаються рядками — токенізуйте заздалегідь.")
'''
    ),
    code(
        '''
# ОПЦІЙНА клітинка: справжні тензори й DataLoader.
try:
    import torch
    from datasets import Array2D, ClassLabel, Dataset, Features
    from torch.utils.data import DataLoader
except ImportError:
    print("torch або datasets не встановлено — опційну клітинку пропущено")
else:
    try:
        flat_ds = Dataset.from_dict({"data": [[1, 2], [3, 4]]}).with_format("torch")
        print("with_format(\\"torch\\"):", flat_ds[0])
        print("зріз [0:2]:", flat_ds[:2])

        fixed_features = Features({"data": Array2D(shape=(2, 2), dtype="int32")})
        shaped_ds = Dataset.from_dict({"data": [[[1, 2], [3, 4]], [[5, 6], [7, 8]]]},
                                      features=fixed_features).with_format("torch")
        print("Array2D(shape=(2, 2)) зріз:", shaped_ds[:2]["data"].shape)

        label_features = Features({"label": ClassLabel(names=["negative", "positive"])})
        label_ds = Dataset.from_dict({"label": [0, 0, 1]}, features=label_features).with_format("torch")
        print("ClassLabel:", label_ds[:3])

        mixed_ds = Dataset.from_dict({"num": [1, 2], "s": ["a", "b"]}).with_format("torch")
        print("мішаний набір (рядок лишається рядком):", mixed_ds[:2])

        loader = DataLoader(flat_ds, batch_size=2)
        for batch_number, one_batch in enumerate(loader):
            print("батч", batch_number, {k: tuple(v.shape) for k, v in one_batch.items()})
        print("пристрій:", flat_ds[0]["data"].device)
    except Exception as real_error:
        print("реальний torch не спрацював:", type(real_error).__name__, str(real_error)[:200])
'''
    ),

    # ── 18.5 ────────────────────────────────────────────────────────────────
    md(
        """
## 18.5 Datasets 5.0: трейси агентів як дані для SFT

У 5.0.0 `load_dataset` навчився читати трейси агентів (`claude_code`, `pi`, `codex`, `droid`) і
перетворювати їх на список `messages` для `trl`. Розбір робить опційна залежність `teich`. Формат
`messages` бібліотека не перевіряє — це ваша робота, і саме тому нижче є валідатор.
"""
    ),
    code(
        '''
# Формат messages: перевірка дефектів і маска цілі.
import json

MESSAGE_ROLES = ("system", "user", "assistant", "tool")
TRAIN_ROLES = ("assistant",)


def validate_trace(trace):
    problems = []
    if not isinstance(trace, list) or not trace:
        return ["messages порожній або не список"]
    for position, message in enumerate(trace):
        if not isinstance(message, dict):
            problems.append(f"[{position}] не словник")
            continue
        if message.get("role") not in MESSAGE_ROLES:
            problems.append(f"[{position}] невідома роль {message.get('role')!r}")
        if not isinstance(message.get("content"), str):
            problems.append(f"[{position}] content не рядок ({type(message.get('content')).__name__})")
    if not any(m.get("role") == "assistant" for m in trace if isinstance(m, dict)):
        problems.append("немає жодного повідомлення assistant — вчитися нема на чому")
    return problems


def target_mask(trace):
    # Схема маскування: 1 — токени, які модель має передбачати (assistant), 0 — решта.
    return [(message["role"], 1 if message["role"] in TRAIN_ROLES else 0) for message in trace]


good_trace = [
    {"role": "system", "content": "Ти — агент із доступом до інструментів."},
    {"role": "user", "content": "Порахуй рядки у data.csv"},
    {"role": "assistant", "content": "Читаю файл."},
    {"role": "tool", "content": '{"rows": 12345}'},
    {"role": "assistant", "content": "У файлі 12345 рядків."},
]
broken_trace = [
    {"role": "user", "content": "Питання"},
    {"role": "assistant", "content": [{"type": "text", "text": "ок"}]},
    {"role": "human", "content": "хто ти?"},
]
empty_answer_trace = [{"role": "system", "content": "інструкція"}, {"role": "user", "content": "питання"}]

print("валідний трейс:", validate_trace(good_trace) or "проблем немає")
print("маска цілі:", target_mask(good_trace))
for found_problem in validate_trace(broken_trace):
    print("  дефект:", found_problem)
print("трейс без відповіді:", validate_trace(empty_answer_trace))
print()
trace_bytes = len(json.dumps(good_trace, ensure_ascii=False).encode("utf-8"))
print(f"байтів у трейсі: {trace_bytes} | повідомлень: {len(good_trace)}")
print("Колонка tool у масці — нулі: інакше модель учиться генерувати виводи інструментів,")
print("а не їх виклики.")
'''
    ),
    code(
        '''
# ОПЦІЙНА клітинка: схема трейсів і пастка з teich.
import json
import os
import tempfile

try:
    from datasets import config, load_dataset
    from datasets.packaged_modules.json.json import AGENT_TRACES_FEATURES, AGENT_TRACES_TYPES_VALUES
except ImportError:
    print("datasets не встановлено — опційну клітинку пропущено")
else:
    try:
        os.environ.setdefault("HF_HUB_OFFLINE", "1")
        print("TEICH_AVAILABLE:", config.TEICH_AVAILABLE)
        print("харнеси:", list(AGENT_TRACES_TYPES_VALUES))
        print("колонки трейсів:", list(AGENT_TRACES_FEATURES))

        trace_dir = tempfile.mkdtemp(prefix="nb18_traces_")
        trace_cache = tempfile.mkdtemp(prefix="nb18_tcache_")
        trace_file = os.path.join(trace_dir, "session.jsonl")
        with open(trace_file, "w", encoding="utf-8") as handle:
            for event in ({"type": "user", "message": {"role": "user", "content": "Порахуй рядки"}},
                          {"type": "assistant", "message": {"role": "assistant", "content": "Гаразд"}}):
                handle.write(json.dumps(event) + chr(10))

        try:
            load_dataset("json", data_files=trace_file, split="train",
                         features=AGENT_TRACES_FEATURES, cache_dir=trace_cache)
            print("трейси завантажено (teich встановлено)")
        except Exception as trace_error:
            cause = trace_error.__cause__ or trace_error.__context__
            print("верхній рівень:", type(trace_error).__name__)
            print("  справжня причина:", type(cause).__name__, ":", str(cause)[:120])
            print("Висновок: причина ховається в __cause__, тому читайте traceback, а не лише тип.")

        plain_ds = load_dataset("json", data_files=trace_file, split="train",
                                parse_agent_traces=False, cache_dir=trace_cache)
        print("parse_agent_traces=False -> features:", plain_ds.features, "| рядків:", plain_ds.num_rows)
    except Exception as real_error:
        print("реальний datasets не спрацював:", type(real_error).__name__, str(real_error)[:200])
'''
    ),

    # ── 18.6 ────────────────────────────────────────────────────────────────
    md(
        """
## 18.6 Перевірка плану перед великим завантаженням

Найдешевша перевірка — та, що робиться до завантаження. Оформимо її функцією: вона приймає опис
плану й повертає список застережень.
"""
    ),
    code(
        '''
# Preflight-перевірка плану роботи з датасетом.
def preflight(plan):
    warnings = []
    if not plan.get("data_files") and not plan.get("split_slice"):
        warnings.append("немає ні data_files, ні зрізу split-у: буде завантажено ВСІ файли")

    estimate = disk_plan(plan["n_examples"], plan["bytes_per_example"],
                         arrow_ratio=plan.get("arrow_ratio", 0.74),
                         n_transforms=plan.get("n_transforms", 3),
                         source_kept=not plan.get("streaming", False))
    if estimate["разом, ГБ"] > plan.get("disk_budget_gb", 100):
        warnings.append(f"оцінка диска {estimate['разом, ГБ']} ГБ перевищує бюджет "
                        f"{plan.get('disk_budget_gb', 100)} ГБ")

    if plan.get("streaming"):
        warnings.append("streaming=True: точного перемішування не буде, довільний доступ недоступний")

    num_proc = plan.get("num_proc")
    if num_proc:
        if num_proc == 1:
            warnings.append("num_proc=1 у map створює пул з одного процесу — краще не передавати")
        if num_proc > plan.get("n_shards", 1):
            warnings.append(f"num_proc={num_proc} більший за кількість шардів "
                            f"{plan.get('n_shards', 1)}: бібліотека знизить його сама")
    if plan.get("io_bound") and num_proc and num_proc > 1:
        warnings.append("задача I/O-bound: додаткові процеси не додадуть пропускної здатності")

    if plan.get("agent_traces") and not plan.get("teich_installed"):
        warnings.append("трейси агентів без teich: буде DatasetGenerationError (причина в __cause__)")

    return estimate, warnings


plans = [
    {"name": "обережний", "n_examples": 100_000, "bytes_per_example": 1500, "n_transforms": 1,
     "n_shards": 8, "num_proc": 4, "data_files": True, "disk_budget_gb": 10},
    {"name": "необачний", "n_examples": 10_000_000, "bytes_per_example": 1500, "n_transforms": 3,
     "n_shards": 1, "num_proc": 8, "io_bound": True, "streaming": True, "disk_budget_gb": 20},
    {"name": "трейси", "n_examples": 100_000, "bytes_per_example": 3500, "n_transforms": 2,
     "n_shards": 4, "agent_traces": True, "teich_installed": False, "data_files": True},
]
for one_plan in plans:
    estimate, warnings = preflight(one_plan)
    print(f"план «{one_plan['name']}»: разом {estimate['разом, ГБ']} ГБ "
          f"(Arrow {estimate['Arrow-джерело, ГБ']} ГБ, кеш map {estimate['кеш map × N, ГБ']} ГБ)")
    if not warnings:
        print("   застережень немає")
    for warning in warnings:
        print("   !", warning)
'''
    ),
    code(
        '''
# Контрольні перевірки: усе, що рахували вище, мусить збігатися з вимірами на datasets 5.0.1.
assert slice_bounds(999, "50%:52%") == (500, 519), "зріз 50-52% має давати 19 рядків, як у документації"
assert slice_bounds(999, "52%:54%") == (519, 539), "зріз 52-54% має давати 20 рядків"
assert slice_bounds(999, "50%:52%", "pct1_dropremainder") == (450, 468)
assert slice_bounds(999, "52%:54%", "pct1_dropremainder") == (468, 486)
print("✓ зрізи split-у: 19 / 20 / 18 / 18 рядків, як у вимірі")

assert demo_stream.num_shards == 4 and demo_stream.shard(num_shards=2, index=0).num_shards == 2
assert take_n(demo_stream, 3) == [0, 1, 2] and skip_take(demo_stream, 996, 3) == [996, 997, 998]
print("✓ шардування й take/skip: 4 шарди, shard(2, 0) -> 2 шарди")

cold_one = take_n(demo_stream.shuffle(seed=42, buffer_size=50, max_buffer_input_shards=1), 5)
cold_ten = take_n(demo_stream.shuffle(seed=42, buffer_size=50, max_buffer_input_shards=10), 5)
shard_of = lambda value: value // 250
assert len({shard_of(v) for v in cold_one}) == 1, "з одним вхідним шардом холодний старт бере одну ділянку"
assert len({shard_of(v) for v in cold_ten}) > 1, "з десятьма шардами холодний старт розкиданий"
print("✓ перемішування: max_buffer_input_shards=1 -> 1 ділянка, =10 -> кілька ділянок")

assert fingerprint_chain(rows_model, ["len"]) == fingerprint_chain(rows_model, ["len"])
assert fingerprint_chain(rows_model, ["len"])[1] != fingerprint_chain(rows_model, ["strip"])[1]
print("✓ відбитки: детерміновані для того самого входу й різні для різних перетворень")

assert disk_plan(1_000_000, 1500, n_transforms=3)["разом, ГБ"] == 5.94
assert disk_plan(1_000_000, 1500, n_transforms=1)["разом, ГБ"] == 3.72
print("✓ витрати диска: 1 map -> 3.72 ГБ, 3 map -> 5.94 ГБ")

assert validate_trace(good_trace) == [] and len(validate_trace(broken_trace)) == 2
assert validate_trace(empty_answer_trace) == ["немає жодного повідомлення assistant — вчитися нема на чому"]
assert target_mask(good_trace) == [("system", 0), ("user", 0), ("assistant", 1),
                                   ("tool", 0), ("assistant", 1)]
print("✓ SFT: валідатор ловить обидва дефекти, маска лишає ціллю тільки assistant")

assert batch_bytes(8, 4096, TEXT_COLUMNS, "int64") == 524288
assert batch_bytes(32, 512, TEXT_COLUMNS, "int64") == 262144
print("✓ пам'ять батча: арифметика узгоджена з кількістю колонок і розміром типу")

print()
print("Усі перевірки пройдено.")
'''
    ),
    md(
        """
## Підсумок

1. **`load_dataset` — це чотири рішення в одному виклику:** джерело, `data_files`, `split` і
   `streaming`. Кожне з них визначає, скільки часу й диска коштує виклик.
2. **Відсоткові зрізи нерівні за побудовою.** `train[50%:52%]` на 999 прикладах дає 19 рядків,
   наступний — 20; `pct1_dropremainder` вирівнює їх до 18, але відкидає хвіст (99 прикладів).
3. **Стрімінг прибирає диск, але не дає довільного доступу.** `take`/`skip` фіксують порядок шардів,
   а перемішування наближене; у 5.0 типовий режим наповнює буфер із кількох шардів
   (`max_buffer_input_shards=10`), і стара поведінка повертається значенням `1`.
4. **Перезапуск стріму робиться знімком стану,** а не індексом: `state_dict` зберігає шард і позицію
   в ньому; після `shuffle` приклади з буфера втрачаються.
5. **Кеш — це диск.** Кожен `map` із новою функцією додає повну Arrow-копію; `size_in_bytes` не
   враховує ці копії, а `cleanup_cache_files()` працює лише після звільнення об'єктів.
6. **`num_proc` масштабується шардами й типом задачі.** Для CPU-bound він дає прискорення (до
   кількості шардів і ядер), для I/O-bound — ні, бо спільний ресурс не множиться, а серіалізація
   прикладів додає витрат.
7. **`map(num_proc=1)` — не «послідовний режим»:** це пул з одного процесу. Не передавайте `num_proc`,
   якщо паралелізм не потрібен.
8. **Формат `messages` бібліотека не перевіряє.** Валідатор і маска цілі — ваш код; без маски
   `role=tool` модель учиться генерувати виводи інструментів замість викликів.

**Куди далі:**

- Розділ 19 — `transformers` v5: `pipeline`, `generate`, новий інтерфейс attention.
- Розділ 20 — квантування: як зменшити ваги під час інференсу.
- Розділ 24 — оцінювання: як побудувати тестовий набір поверх датасета.
- Розділ 16 — RAG: чанкування й відбір контексту з тих самих даних.

## Джерела

- [Hugging Face Datasets — Load](https://raw.githubusercontent.com/huggingface/datasets/main/docs/source/loading.mdx)
- [Hugging Face Datasets — Stream](https://raw.githubusercontent.com/huggingface/datasets/main/docs/source/stream.mdx)
- [Hugging Face Datasets — Cache management](https://raw.githubusercontent.com/huggingface/datasets/main/docs/source/cache.mdx)
- [Hugging Face Datasets — The cache](https://raw.githubusercontent.com/huggingface/datasets/main/docs/source/about_cache.mdx)
- [Hugging Face Datasets — Use with PyTorch](https://raw.githubusercontent.com/huggingface/datasets/main/docs/source/use_with_pytorch.mdx)
- [Hugging Face Datasets — Differences between Dataset and IterableDataset](https://raw.githubusercontent.com/huggingface/datasets/main/docs/source/about_mapstyle_vs_iterable.mdx)
- [huggingface/datasets 5.0.0 — release notes](https://github.com/huggingface/datasets/releases/tag/5.0.0)

Числа в ноутбуку, позначені як ВИМІР, отримані на `datasets==5.0.1`; позначені як МОДЕЛЬ —
розрахунок там, де вимірювання неможливе (наприклад, недоступний пул процесів).
"""
    ),
]
