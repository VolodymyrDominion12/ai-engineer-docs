## 18. HF Datasets: завантаження, стрімінг, кеш

`datasets` — бібліотека, яка стоїть між сирими файлами даних і тренувальним циклом: вона завантажує
дані з Hub або з локального диска, конвертує їх у формат Apache Arrow, тримає проміжні результати
обробки в кеші й віддає приклади у PyTorch, NumPy, Pandas або Polars. Дві її публічні сутності —
`Dataset` (map-style, довільний доступ до рядків) та `IterableDataset` (стрімінговий, послідовний) —
мають різні гарантії й різну ціну за ресурси.

Практична цінність розділу в тому, що більшість втрат у роботі з даними — це не помилки коду, а
непомічені витрати: диск, який закінчився від кешованих копій після `map`, година очікування на
конвертацію датасета, який ви читаєте один раз, або `num_proc`, який не дав нічого, бо шард був один.

Усі виводи в розділі отримані на `datasets==5.0.1` (це версія, яку PyPI віддавав як останню на
09.2026) з `pyarrow==25.0.1` і `torch==2.14.0`, з локальними файлами й увімкненим `HF_HUB_OFFLINE=1` —
тобто без звернення до мережі. Де число залежить від машини, це вказано явно.

### 18.1 `load_dataset`: джерела, конфігурації, split-и

**Що це.** `load_dataset` — єдина точка входу бібліотеки: одна функція приймає або ім'я датасета з
Hub, або ім'я «пакетованого» формату (`"csv"`, `"json"`, `"parquet"`, `"webdataset"`, `"tsfile"`…), або
шлях до локальної теки, і повертає `DatasetDict` (словник split-ів), окремий `Dataset` (якщо вказано
`split`), `IterableDatasetDict` або `IterableDataset` (якщо `streaming=True`).

**Навіщо це знати.** Три параметри визначають, скільки часу й диска коштуватиме один виклик:
`data_files` (які саме файли читати), `split` (яку частину матеріалізувати) і `streaming`. Помилка в
`data_files` коштує терабайтів завантаження, помилка в `split` — годин на конвертацію, яку ви робите
заради 500 прикладів.

**Як працює під капотом.** Повна сигнатура 5.0.1 (отримана через `inspect.signature`):

```python
from datasets import load_dataset
import inspect

print(inspect.signature(load_dataset))
```

```
(path: str, name: str | None = None, data_dir: str | None = None, data_files: str | Sequence[str] |
 Mapping[str, str | Sequence[str]] | None = None, split: str | Split | list[str] | None = None,
 cache_dir: str | None = None, features: Features | None = None, download_config=None,
 download_mode: DownloadMode | str | None = None, verification_mode=None, keep_in_memory: bool | None
 = None, save_infos: bool = False, revision: str | Version | None = None, token: str | bool | None =
 None, streaming: bool = False, num_proc: int | None = None, storage_options: dict | None = None,
 **config_kwargs)
```

Механіка виклику така:

1. **Резолв імені.** Рядок `"namespace/name"` шукається на Hub; рядок без слеша, що збігається з
   пакетованим білдером (`csv`, `json`, `parquet`, `arrow`, `webdataset`, `hdf5`, `tsfile`, `pdb`,
   `mmcif`, `genbank`, `fastq`, `fasta`, `vortex`, `lance`…), створює білдер відповідного формату;
   наявний локальний шлях читається як тека з даними (формат визначається автоматично).
2. **Створення `BuilderConfig`.** Пакетовані формати приймають свої параметри через `**config_kwargs`
   (наприклад `field`, `delimiter`, `column_names`, `parse_agent_traces`); `name` — це ім'я
   *конфігурації* датасета (у документації: `load_dataset("allenai/c4", "en")`,
   `load_dataset("facebook/multilingual_librispeech", "spanish", num_proc=8)`).
3. **Download + extract.** Файли завантажуються в кеш `huggingface_hub` (`~/.cache/huggingface/hub`),
   розпаковуються «на льоту»; далі кожен файл стає *шардом*.
4. **Генерація split-ів і читання.** Білдер читає шарди, будує Arrow-таблиці й пише їх у кеш
   `datasets`; якщо `split` не вказано, перевіряються імена файлів (`train`, `test`, `validation`) і
   всі файли збираються в split `train`. Далі `ArrowReader` перетворює `ReadInstruction` на «файлові
   інструкції»: зріз split-у не копіює дані, а повертає `Dataset`, що посилається на ті самі
   Arrow-файли з індексною мапою потрібних рядків.

Ось як виглядає робочий цикл «локальний JSONL → розрізані split-и» на 999 прикладах:

```python
# 999 прикладів у train, 20 у test — локальні файли, мережа не потрібна
import json
from datasets import load_dataset

files = {"train": "train.jsonl", "test": "test.jsonl"}

for spec in ["train[10:20]", "train[:10%]", "train[-10:]", "train+test",
             "train[50%:52%]", "train[52%:54%]", "train[50%:52%](pct1_dropremainder)"]:
    d = load_dataset("json", data_files=files, split=spec)
    print(f"{spec:38} -> {d.num_rows:>4} рядків, перші id={[d[i]['id'] for i in range(3)]}")
```

```
train[10:20]                           ->   10 рядків, перші id=[10, 11, 12]
train[:10%]                            ->  100 рядків, перші id=[0, 1, 2]
train[-10:]                            ->   10 рядків, перші id=[989, 990, 991]
train+test                             -> 1019 рядків, перші id=[0, 1, 2]
train[50%:52%]                         ->   19 рядків, перші id=[500, 501, 502]
train[52%:54%]                         ->   20 рядків, перші id=[519, 520, 521]
train[50%:52%](pct1_dropremainder)     ->   18 рядків, перші id=[450, 451, 452]
```

Ті самі зрізи через API `ReadInstruction` — коли межі обчислюються в коді, а не пишуться рядком:

```python
from datasets import load_dataset, ReadInstruction

files = {"train": "train.jsonl", "test": "test.jsonl"}
ri = ReadInstruction("train", from_=50, to=52, unit="%", rounding="pct1_dropremainder")
print(str(ri), "->", load_dataset("json", data_files=files, split=ri).num_rows)
print(ReadInstruction("train") + ReadInstruction("test"))
```

```
train[50%:52%](pct1_dropremainder) -> 18
train+test
```

**Округлення відсотків — не деталь, а джерело зсуву.** За документацією типове округлення меж
відсоткового зрізу — до найближчого цілого, тому зрізи виходять нерівними. Приклад із документації
(999 прикладів у `train`) відтворюється точно:

| Зріз | Рядків | Перший `id` | Що сталося |
|---|---|---|---|
| `train[50%:52%]` | 19 | 500 | межа округлена до 500 (замість 499.5) |
| `train[52%:54%]` | 20 | 519 | наступна межа округлена до 539 |
| `train[50%:52%](pct1_dropremainder)` | 18 | 450 | межі кратні 1%: 450…468 |
| `train[52%:54%](pct1_dropremainder)` | 18 | 468 | 468…486 |

Документація попереджає прямо: `pct1_dropremainder` може **відкинути** останні приклади датасета,
якщо його розмір не ділиться на 100 без остачі. Для 999 прикладів це 99 прикладів хвоста, які не
потрапляють у жоден зріз.

**Джерела даних і що з ними робить `load_dataset`**

| Джерело | Як вказати | Особливість |
|---|---|---|
| Hub, репозиторій датасета | `load_dataset("lhoestq/demo1")` | Файли формату CSV підхоплюються автоматично |
| Hub, конкретна версія | `revision="main"` (тег, гілка або хеш коміту) | Для відтворюваності документація просить фіксувати `revision` |
| Локальні файли | `load_dataset("csv", data_files="my_file.csv")` | Список файлів — теж допустимий |
| Підмножина файлів | `data_files="en/c4-train.0000*-of-01024.json.gz"`, `data_dir="en"` | Підтримується grep-патерн |
| Remote за HTTP | `data_files=["https://…/train-v2.0.json"]` | Для Parquet/Arrow — теж |
| HF-файли | `data_files=["hf://datasets/…/file.parquet"]`, `hf://buckets/…/file.csv` | Працює для datasets і Storage Buckets |
| Вкладені JSON | `field="data"` | Бере масив із вказаного поля |
| In-memory | `Dataset.from_dict/from_list/from_generator/from_pandas` | Без диска й мережі |
| SQL | `Dataset.from_sql("SELECT text FROM table WHERE length(text) > 100 LIMIT 10", con="sqlite:///file.db")` | Читання таблиці або запиту |
| Офлайн | `HF_HUB_OFFLINE=1` | Бере тільки з кешу |

Перевірка на вкладених полях і власних `Features` (реальні виводи):

```python
import json
from datasets import Dataset, Features, Value, ClassLabel, load_dataset

# Вкладений JSON: масив лежить у полі "data"
with open("nested.json", "w") as f:
    json.dump({"version": "0.1.0",
               "data": [{"a": 1, "b": 2.0, "c": "foo", "d": False},
                        {"a": 4, "b": -5.5, "c": None, "d": True}]}, f)

ds = load_dataset("json", data_files="nested.json", field="data")
print(ds["train"].features)
print("перший:", ds["train"][0])

# CSV без заголовка, зі своїм розділювачем і власними мітками
with open("e.csv", "w") as f:
    f.write("Я люблю це;joy\nМені сумно;sadness\n")

class_names = ["sadness", "joy", "love", "anger", "fear", "surprise"]
emotion_features = Features({"text": Value("string"), "label": ClassLabel(names=class_names)})
ds2 = load_dataset("csv", data_files={"train": "e.csv"}, delimiter=";",
                   column_names=["text", "label"], features=emotion_features)
print(ds2["train"].features)
print("перший:", ds2["train"][0])
```

```
{'a': Value('int64'), 'b': Value('float64'), 'c': Value('string'), 'd': Value('bool')}
перший: {'a': 1, 'b': 2.0, 'c': 'foo', 'd': False}
{'text': Value('string'), 'label': ClassLabel(names=['sadness', 'joy', 'love', 'anger', 'fear', 'surprise'])}
перший: {'text': 'Я люблю це', 'label': 1}
```

Зверніть увагу на другу частину: без явних `features` і `column_names` рядок `Я люблю це;joy`
розібрався б як один текстовий стовпець із комою, а `label` лишився б рядком. `ClassLabel` перетворює
мітки на цілі числа (`joy` → 1), і саме ці числа підуть у функцію втрат.

**Офлайн-режим — не «порожня обіцянка».** Якщо встановити `HF_HUB_OFFLINE=1`, бібліотека не намагається
чекати таймауту звернення до Hub, а одразу йде в кеш. На незнайомому імені
`load_dataset("rajpurkar/squad", split="train")` завершується так:

```
ConnectionError : Couldn't reach 'rajpurkar/squad' on the Hub (OfflineModeIsEnabled)
```

**Типові помилки**

- **Не вказати `data_files` для великого датасета.** Документація описує це прямим попередженням:
  без `data_files` повертаються **усі** файли, а для C4 це приблизно 13 ТБ. Один виклик — і канал
  зайнятий на добу.
- **Дати `split` у вигляді рядка там, де split-и описані в `data_files`.** `split="train+test"`
  вимагає, щоб обидва split-и існували; інакше отримаєте
  `ValueError: Unknown split "test". Should be one of ['train'].` — помилка не про синтаксис зрізу,
  а про відсутність split-у.
- **Чекати, що `train[:10%]` дасть рівні шматки.** Межі округлюються до найближчого цілого; для
  рівних шматків потрібен `pct1_dropremainder`, який відкидає хвіст.
- **Плутати `name` і `data_dir`.** `name` — конфігурація датасета, `data_dir` — тека з файлами
  усередині репозиторію. Вони не взаємозамінні.
- **Розраховувати на `split` із дробовими відсотками.** Зріз `train[0.5%:1%]` не підтримується:
  одиниця виміру — цілий відсоток або абсолютний індекс.

**Альтернативи.** Для одного Parquet-файлу дешевше взагалі не конвертувати: `pyarrow.parquet` або
Polars/DuckDB читають його напряму. Для великих корпусів, які використовуються один раз,
`datasets` із `streaming=True` (див. 18.2) замінює завантаження. Для дрібних табличних даних
(до кількох мегабайтів) `pandas.read_csv` швидший за повний цикл конвертації в Arrow.

---

### 18.2 Стрімінговий режим і коли він потрібен

**Що це.** `streaming=True` повертає не `Dataset`, а `IterableDataset`: дані читаються генератором під
час ітерації, нічого не конвертується в Arrow і нічого не пишеться на диск. Документація формулює
призначення трьома випадками: не хочете чекати на завантаження дуже великого датасета; розмір
датасета перевищує вільне місце на диску; треба швидко подивитися кілька прикладів.

**Навіщо це знати.** Це єдиний спосіб працювати з датасетами, більшими за ваш диск. Англійський
split `HuggingFaceFW/fineweb` — 45 ТБ (число з документації); завантажити його нереально, а
`next(iter(dataset))` повертає перший приклад майже одразу. Ціна — втрата довільного доступу до
рядків і слабший контроль над перемішуванням.

**Як працює під капотом.** `load_dataset(..., streaming=True)` не будує Arrow-таблиць: `IterableDataset`
тримає перелік *шардів* (файлів або джерел) і ланцюжок генераторів, до якого кожен виклик
`map`/`filter`/`shuffle` додає свою ланку. Ланки виконуються лише тоді, коли ви починаєте ітерацію,
і лише для тих прикладів, які реально проходять цикл. `num_shards` — ключове число: воно визначає,
скільки паралельних читачів можна мати й наскільки якісним буде перемішування.

Реальні виміри на чотирьох локальних JSONL-шардах по 250 рядків:

```python
import itertools
from datasets import load_dataset

shards = [f"part-{s:02d}.jsonl" for s in range(4)]          # 4 файли = 4 шарди
ids = load_dataset("json", data_files={"train": shards}, split="train", streaming=True)

print(type(ids).__name__, "| num_shards:", ids.num_shards, "| features:", ids.features)
print("перші 3:", [row["id"] for row in ids.take(3)])

print("колонка 'id':", type(ids["id"]).__name__, "->", list(itertools.islice(ids["id"], 3)))

print("take(3):", [r["id"] for r in ids.take(3)])
print("skip(996).take(3):", [r["id"] for r in ids.skip(996).take(3)])
print("shard(2, 0).num_shards:", ids.shard(num_shards=2, index=0).num_shards)
print("reshard().num_shards:", ids.reshard().num_shards)
print("batch(4, drop_last_batch=True):", next(iter(ids.batch(batch_size=4, drop_last_batch=True))))
print("filter(id % 100 == 0).take(3):", [r["id"] for r in ids.filter(lambda x: x["id"] % 100 == 0).take(3)])
```

```
IterableDataset | num_shards: 4 | features: {'id': Value('int64')}
перші 3: [0, 1, 2]
колонка 'id': IterableColumn -> [0, 1, 2]
take(3): [0, 1, 2]
skip(996).take(3): [996, 997, 998]
shard(2, 0).num_shards: 2
reshard().num_shards: 4
batch(4, drop_last_batch=True): {'id': [0, 1, 2, 3]}
filter(id % 100 == 0).take(3): [0, 100, 200]
```

**Перемішування — найдорожче місце в стрімінгу.** Точного перемішування тут немає за побудовою:
замість перестановки індексів використовується *буфер перемішування* — випадкові приклади беруться з
буфера фіксованого розміру, а звільнені місця заповнюються новими. Документація дає механіку: при
`buffer_size=10_000` вибірка відбувається з перших 10 000 прикладів, далі вони замінюються новими.
Типове значення `buffer_size` — 1000.

У `datasets` 5.0.0 механізм змінили: буфер тепер наповнюється одразу з кількох вхідних шардів, а не з
одного. Це **ламальна зміна**: щоб повернути стару поведінку, треба передати
`max_buffer_input_shards=1`. Реальний вивід для тих самих даних у двох режимах:

```python
from datasets import load_dataset

ids = load_dataset("json", data_files={"train": ["part-00.jsonl"]}, split="train", streaming=True)

for m in (1, 10):
    sh = ids.shuffle(seed=42, buffer_size=1000, max_buffer_input_shards=m)
    cold = [r["id"] for r in sh.take(5)]
    sh2 = ids.shuffle(seed=42, buffer_size=1000, max_buffer_input_shards=m)
    warm = [r["id"] for r in sh2.skip(100).take(5)]
    print(f"max_buffer_input_shards={m:>2} cold={cold}\n{'':27} warm={warm}")
```

```
max_buffer_input_shards= 1 cold=[228, 183, 109, 166, 877]
                            warm=[47, 930, 902, 788, 196]
max_buffer_input_shards=10 cold=[494, 733, 214, 979, 31]
                            warm=[699, 795, 788, 259, 486]
```

Перемішування між епохами робиться не новим викликом `shuffle`, а `set_epoch`: ефективний сід
дорівнює `початковий сід + номер епохи` (формула з документації та з настанови
«Dataset vs IterableDataset»). Для точного перезапуску навчання є `state_dict`/`load_state_dict` —
знімок зберігає індекс поточного шарда й індекс прикладу в ньому:

```python
from datasets import Dataset

it = Dataset.from_dict({"a": range(6)}).to_iterable_dataset(num_shards=3)
for idx, ex in enumerate(it):
    print(ex)
    if idx == 2:
        state = it.state_dict()
        print("checkpoint")
        break
it.load_state_dict(state)
print("restart from checkpoint")
for ex in it:
    print(ex)
```

```
{'a': 0}
{'a': 1}
{'a': 2}
checkpoint
restart from checkpoint
{'a': 3}
{'a': 4}
{'a': 5}
```

Документація попереджає про дві межі відновлення: шарди, уже прочитані, не перечитуються, але
поточний шард читається **з початку** й приклади пропускаються до позиції знімка, тому відновлення
не миттєве; а якщо використовувався `shuffle`, приклади з буфера втрачаються й буфер наповнюється
новими даними.

**Об'єднання кількох джерел.** `concatenate_datasets` приклеює одне до одного (шарди складаються),
`interleave_datasets` чергує приклади й має три стратегії зупинки. Реальні виміри на
`IterableDataset` по 4 приклади:

```python
from datasets import Dataset, concatenate_datasets, interleave_datasets

a = Dataset.from_dict({"text": [f"a{i}" for i in range(4)]}).to_iterable_dataset(num_shards=2)
b = Dataset.from_dict({"text": [f"b{i}" for i in range(4)]}).to_iterable_dataset(num_shards=3)
cat = concatenate_datasets([a, b])
inter = interleave_datasets([a, b], seed=42)
over = interleave_datasets([a, b], probabilities=[0.8, 0.2], seed=42)
print("concatenate: num_shards =", cat.num_shards, "| перші 6:", [x["text"] for x in cat.take(6)])
print("interleave:  num_shards =", inter.num_shards, "| перші 6:", [x["text"] for x in inter.take(6)])
print("probabilities=[0.8, 0.2]:", [x["text"] for x in over.take(6)])

# стратегії зупинки — на входах по одному шарду, щоб результат не залежав від розкладки
s1 = Dataset.from_dict({"text": [f"a{i}" for i in range(4)]}).to_iterable_dataset(num_shards=1)
s2 = Dataset.from_dict({"text": [f"b{i}" for i in range(4)]}).to_iterable_dataset(num_shards=1)
for strat in ("first_exhausted", "all_exhausted", "all_exhausted_without_replacement"):
    print(strat, "->", len(list(interleave_datasets([s1, s2], stopping_strategy=strat))), "елементів")
```

```
concatenate: num_shards = 5 | перші 6: ['a0', 'a1', 'a2', 'a3', 'b0', 'b1']
interleave:  num_shards = 2 | перші 6: ['a0', 'b0', 'a1', 'b1', 'a2', 'b2']
probabilities=[0.8, 0.2]: ['a0', 'a1', 'b0', 'a2', 'a3']
first_exhausted -> 7 елементів
all_exhausted -> 8 елементів
all_exhausted_without_replacement -> 8 елементів
```

Два числа тут мають пряме пояснення в документації. По-перше, рівень шардування
`interleave_datasets` дорівнює **мінімуму** шардувань входів: `min(2, 3) = 2`. По-друге,
`first_exhausted` (стратегія за замовчуванням) зупиняє побудову, щойно один із датасетів вичерпається
— тому на 4+4 прикладах вийшло 7, а не 8. Для багатомовних сумішей із заданими частками є
`probabilities=[0.8, 0.2]`.

**Таблиця вибору: `Dataset` чи `IterableDataset`**

| Властивість | `Dataset` (map-style) | `IterableDataset` |
|---|---|---|
| Доступ до рядка | `ds[0]`, зрізи, `select` | Лише послідовна ітерація |
| Місце на диску | Повна Arrow-копія в кеші | Нічого (або тимчасовий файл) |
| Час до першого прикладу | Конвертація всього датасета | Одразу |
| Перемішування | Точне (`shuffle(seed=…)`) | Наближене (буфер + порядок шардів) |
| Обробка | Одразу (`map` виконується повністю) | Ліниво (`map` виконується під час ітерації) |
| Відновлення після збою | `select(range(start, len))` | `state_dict`/`load_state_dict` |
| Паралелізм | `num_proc`, `num_workers` | `num_workers` за шардами |
| Коли брати | Датасет уміщується на диск, потрібні зрізи й точне перемішування | Датасет завеликий, потрібен один прохід, потрібне швидке дослідження |

Документація додає важливу межу для навчання: `IterableDataset` добре підходить для ітеративних задач
(тренування), але **не** для задач, де потрібен випадковий доступ до прикладів. Окремо в настанові
«Dataset vs IterableDataset» є числова деталь про продуктивність map-style: щойно з'являється індексна
мапа (наприклад після `Dataset.shuffle`), швидкість доступу може впасти **до 10 разів** — бо зникає
читання неперервними блоками; лікується `flatten_indices()`, який перезаписує датасет на диск.

**Типові помилки**

- **`take()`/`skip()` перед `shuffle()`.** Документація попереджає прямо: `take` і `skip` фіксують
  порядок шардів і блокують подальші виклики `shuffle`. Перемішуйте до розрізання.
- **Покладатися на `num_proc` у стрімінгу.** Для `IterableDataset`, створеного через
  `load_dataset(..., streaming=True)`, параметр `num_proc` не застосовується: у коді 5.0.1
  паралельна гілка працює лише для звичайного (не streaming) шляху генерації. Паралелізм тут
  досягається через `num_workers` у `DataLoader`.
- **Очікувати точного перемішування.** Воно наближене за побудовою; для малої кількості файлів
  якість піднімає `reshard()` (для Parquet — шардування за row groups), і лише потім `shuffle`.
- **Датасет з одного шарда.** Документація прямо радить: якщо після `reshard()` усе ще
  `num_shards == 1`, ріжте датасет вручну через `skip` і `take`.
- **Читати `ds[0]` в `IterableDataset`.** Такої операції немає — щоб дістати останній приклад,
  доведеться прочитати всі попередні.
- **Забути `set_epoch`.** Без нього кожна епоха перемішується тим самим сідом, і порядок прикладів
  повторюється.

**Альтернативи.** Для Parquet і Vortex у стрімінгу працюють `columns=[...]` і `filters=[("col", ">=", v)]`
— колонкові формати віддають лише потрібні стовпці й рядки (для Vortex фільтр можна передати
виразом `ve.column("score") >= 0.5`). Для повністю локальних конвеєрів без `datasets` беруть DuckDB
або Polars scan, а для навчання з відновленням після збою — `StatefulDataLoader` з `torchdata`
(див. 18.4).

---
### 18.3 Кеш: структура на диску, керування, `map` і `num_proc`

**Що це.** У роботі з `datasets` задіяні **два** різні кеші. Перший — кеш `huggingface_hub`, куди
складаються завантажені з Hub файли. Другий — власний кеш `datasets`, куди пишуться Arrow-файли,
отримані з цих (або локальних) файлів, та результати кожного перетворення. Обидва живуть на диску,
обидва переживають перезапуск процесу — і саме тому обидва здатні з'їсти диск.

**Навіщо це знати.** Кеш `datasets` — це не «тимчасова папка, яку можна ігнорувати». Кожен виклик
`map` із новою функцією додає **повну копію** перетвореного датасета (виміри нижче). На датасеті
розміром 500 ГБ три експерименти з `map` дають 2 ТБ. Розуміння структури кеша перетворює це з
раптового «диск закінчився» на керовану величину.

**Як працює під капотом.**

**Розташування.** За документацією кеш Hub типово лежить у `~/.cache/huggingface/hub`, а кеш
`datasets` — у `~/.cache/huggingface/datasets`. Реальні значення в 5.0.1 збігаються:

```python
import datasets
from datasets import config

print("HF_DATASETS_CACHE:", config.HF_DATASETS_CACHE)
print("IN_MEMORY_MAX_SIZE:", config.IN_MEMORY_MAX_SIZE, "| caching:", datasets.is_caching_enabled())
print("DownloadMode:", [m.value for m in datasets.DownloadMode])
```

```
HF_DATASETS_CACHE: /home/volodymyr/.cache/huggingface/datasets
IN_MEMORY_MAX_SIZE: 0.0 | caching: True
DownloadMode: ['reuse_dataset_if_exists', 'reuse_cache_if_exists', 'force_redownload']
```

**Керування через змінні середовища** (таблиця з документації про кеш):

| Змінна | Що змінює | Результат |
|---|---|---|
| `HF_HOME` | Корінь усіх кешів Hugging Face | `<HF_HOME>/datasets` **і** `<HF_HOME>/hub` |
| `HF_DATASETS_CACHE` | Лише кеш `datasets` (Arrow-файли, індекси) | `<шлях>/` — і **не** впливає на файли з Hub |
| `HF_HUB_CACHE` | Лише кеш Hub (моделі, токенізатори, сирі файли) | `<шлях>/` |
| `HF_HUB_OFFLINE=1` | Повний офлайн-режим | Файли беруться тільки з кешу |

Документація окремо підкреслює найпоширенішу плутанину: `HF_DATASETS_CACHE` **не** впливає на те, куди
складаються завантажені з Hub сирі файли — за них відповідає `HF_HUB_CACHE` (у документації це
пов'язано з issue #7480). Якщо треба перенести все — задавайте `HF_HOME`.

**Анатомія кеша `datasets`.** Реальна структура після `load_dataset("json", data_files="data.jsonl",
cache_dir=...)` на 100 прикладів:

```
        0 json/default-4fa60959ecc657bd/0.0.0/915409a0…a971aa3_builder.lock
      491 json/default-4fa60959ecc657bd/0.0.0/915409a0…a971aa3/dataset_info.json
     4168 json/default-4fa60959ecc657bd/0.0.0/915409a0…a971aa3/json-train.arrow
```

Розбір шляху: `<cache_dir>/<білдер>/<конфігурація>-<хеш конфігурації>/<версія>/<хеш вмісту>/`. Усередині
хеш-теки лежать `dataset_info.json` (метадані, розміри, features) і `<білдер>-<split>.arrow`. Поруч із
хеш-текою — файли `.lock` (захист від одночасної генерації двома процесами). Вміст
`dataset_info.json` для того самого датасета:

```json
{"description": "", "citation": "", "homepage": "", "license": "",
 "features": {"id": {"dtype": "int64", "_type": "Value"}, "text": {"dtype": "string", "_type": "Value"}},
 "builder_name": "json", "dataset_name": "json", "config_name": "default",
 "version": {"version_str": "0.0.0", "major": 0, "minor": 0, "patch": 0},
 "splits": {"train": {"name": "train", "num_bytes": 3590, "num_examples": 100, "dataset_name": "json"}},
 "download_size": 8680, "dataset_size": 3590, "size_in_bytes": 12270}
```

Три числа в кінці — готовий калькулятор витрат: `download_size` (сирі файли), `dataset_size` (Arrow),
`size_in_bytes` (їх сума). Тут JSONL на 8680 байтів перетворився на Arrow на 3590 байтів.

**Відбитки (fingerprints).** Кеш знає, чи можна перевикористати файл, за *відбитком*. Документація
описує механіку так: початковий відбиток — це хеш Arrow-таблиці (або хеш Arrow-файлів, якщо датасет
уже на диску); кожен наступний відбиток — комбінація попереднього відбитка й хешу останнього
перетворення. Хешування виконує `Hasher`, який серіалізує об'єкт через `dill` і хешує байти, тому
**будь-яка зміна змінної, використаної у функції, змінює відбиток**. Реальні значення:

```python
from datasets import Dataset
from datasets.fingerprint import Hasher

d1 = Dataset.from_dict({"a": [0, 1, 2]})
d2 = d1.map(lambda x: {"a": x["a"] + 1})
print("відбитки:", d1._fingerprint, d2._fingerprint)

my_func = lambda example: {"length": len(example["text"])}
print("Hasher.hash:", Hasher.hash(my_func))
```

```
відбитки: dd8191e3b37cf17d 9b83f037ca016f60
Hasher.hash: 682ae82a37df3c82
```

Тут потрібне застереження, яке легко проґавити. У документації `about_cache.mdx` наведено
конкретні значення — `d19493523d95e2dc`, `5b86abacd4b42434` для відбитків і `3d35e2b3e94c81d6`
для `Hasher.hash` — але на `datasets==5.0.1` той самий код дає **інші** рядки (вище). Збігається
лише формат: 16 hex-символів. Отже значення в документації ілюстративні, і відбиток не можна
вважати сталою величиною, яку можна закласти в код або в конфіг. Перевіряти треба сам факт
перевикористання кеша (чи не з'являється повторна генерація), а не рівність рядків.

Практичний наслідок недетермінізму: якщо у функції `map` використовується об'єкт із недетермінованим
порядком (наприклад `set` або список, що формується з нього), хеш різнитиметься між сесіями, і
бібліотека вважатиме перетворення новим — тоді все перераховується заново. Документація радить у
такому разі хешувати підозрілі об'єкти через `Hasher` і шукати винуватця.

**Кеш-влучання.** Друге завантаження того самого датасета з того самого шляху не генерує split
повторно — прогрес-бар `Generating train split` з'являється лише першого разу:

```
запуск 1: 'Generating train split' у stderr -> True  | num_rows: 1000
запуск 2: 'Generating train split' у stderr -> False | num_rows: 1000
```

**Скільки додає `map`.** Реальний вимір на датасеті з 20 000 прикладів (JSONL 10.64 МБ) у
`cache_dir`, де кожен `map` отримує нову функцію:

| Крок | Arrow у теці кеша, МБ | Файлів `.arrow` |
|---|---|---|
| Джерело JSONL | 10.64 (сирий файл) | — |
| `load_dataset` | 3.74 | 1 |
| `map` №1 | 7.65 | 2 |
| `map` №2 | 11.55 | 3 |
| `map` №3 | 15.46 | 4 |

Файли `map`-результатів називаються `cache-<відбиток>.arrow` і лежать **у тій самі самій теці**, що й
Arrow джерела. При цьому `info.size_in_bytes` цього датасета — 14 380 000 байтів, тобто менше за
реальні 15.46 МБ у кеші: `size_in_bytes` не враховує проміжні результати перетворень. Це перше місце,
де «логічний» і «фізичний» розмір датасета розходяться.

**Прибирання.** `Dataset.cleanup_cache_files()` повертає **кількість видалених** файлів і видаляє лише
файли перетворень, які не використовуються живими об'єктами `Dataset`. Реальний сценарій: три різні
`map` від одного джерела, після чого два проміжні результати звільнено:

```python
m1 = ds.map(lambda x: {"n": len(x["text"])})
m2 = ds.map(lambda x: {"nu": len(x["text"])})
m3 = ds.map(lambda x: {"num": len(x["text"])})
print("arrow-файлів після трьох map:", len(list(cache.rglob("*.arrow"))))
del m2, m3
import gc; gc.collect()
print("cleanup_cache_files() ->", m1.cleanup_cache_files())
print("arrow-файлів після cleanup:", len(list(cache.rglob("*.arrow"))))
```

```
arrow-файлів після трьох map: 4
cleanup_cache_files() -> 2
arrow-файлів після cleanup: 2
```

Зверніть увагу: залишилося **два** файли — `json-train.arrow` (джерело) і `cache-<відбиток>.arrow`
(результат, який використовує `m1`). Саме тому порядок дій такий: спершу звільнити зайві об'єкти,
потім викликати `cleanup_cache_files()`.

**Вимкнення кеша.** Є три різні речі, які часто плутають:

| Що зробити | Виклик | Наслідок |
|---|---|---|
| Перерахувати одне перетворення | `ds.map(fn, load_from_cache_file=False)` | Функція виконується заново; файл результату створюється під випадковим ім'ям у тимчасовій теці |
| Вимкнути кеш глобально | `datasets.disable_caching()` | Перетворення більше не перевикористовуються; результат живе до кінця сесії |
| Перезавантажити сирі файли | `load_dataset(..., download_mode="force_redownload")` | Дані перезавантажуються й генеруються заново |

Документація описує поведінку вимкненого кеша прямо: файли кеша створюються щоразу, пишуться в
тимчасову теку з **випадковим** хешем замість відбитка, і видаляються після завершення сесії — тому
результат треба зберегти через `Dataset.save_to_disk`. У коді 5.0.1 це видно точно: ім'я файлу
формується як `"cache-" + generate_random_fingerprint() + ".arrow"` у тимчасовій теці
(`TEMP_CACHE_DIR_PREFIX = "hf_datasets-"`, усередині `TMPDIR`). Виміряний наслідок у 5.0.1: у
вимкненому режимі поле `cache_files` результату порожнє, а два однакові `map` дають **різні**
`_fingerprint` — тобто перевикористати нічого не можна:

```
fingerprint (кеш вимкнено, 1-й map): ec9890bf4cfc98c8
fingerprint (кеш вимкнено, 2-й map): d0384a36f19104a3
cache_files: []
```

**`map`: що саме входить у хеш.** Відбиток нового датасета залежить не лише від функції, а й від
параметрів виклику. Ось реальна сигнатура `Dataset.map` у 5.0.1 (скорочено до практично важливих):

| Параметр | Типове | Навіщо |
|---|---|---|
| `function` | — | Функція від приклада або (при `batched=True`) від батча |
| `batched` | `False` | Обробка батчами; відкриває токенізацію й аугментацію |
| `batch_size` | `1000` | Розмір батча при `batched=True` |
| `remove_columns` | `None` | Колонки видаляються **після** передачі приклада у функцію |
| `num_proc` | `None` | Кількість процесів; `None` — без паралелізму |
| `load_from_cache_file` | `None` | `False` — перерахувати, ігноруючи кеш |
| `cache_file_name` | `None` | Явний шлях для файлу результату |
| `writer_batch_size` | `1000` | Скільки прикладів тримати в пам'яті перед записом у Arrow |
| `fn_kwargs` | `None` | Додаткові аргументи функції (важливо для хешування) |
| `with_indices` | `False` | Передати індекс приклада другим аргументом |

Дві деталі з реального запуску. Перша: функція отримує не `dict`, а об'єкт `LazyRow` (він поводиться як
словник, але не має методів значення — тому `example["text"].encode()` працює, а
`example.encode()` ні). Друга: параметр `num_proc=1` для `Dataset.map` **не** означає «без
паралелізму» — у коді 5.0.1 стоїть умова `if num_proc is not None and num_proc >= 1:
with mp.Pool(num_proc)`, тобто створюється пул з одного процесу. Щоб справді працювати в
батьківському процесі, параметр треба **не передавати взагалі**.

**`num_proc`: механіка.** Для `load_dataset` документація описує механіку точно: датасет складається з
файлів-*шардів*, і кожен процес отримує **підмножину шардів** для підготовки. Отже швидкість упирається
в кількість шардів: 8 шардів — максимум 8 корисних процесів. У коді 5.0.1 це видно додатково: білдер
порівнює `num_proc` із кількістю шардів і **знижує** його з попередженням
(`Setting num_proc from N to M … as it only contains M shards`), а для split-а з одного шарда взагалі
вимикає паралелізм. Ще одна деталь із коду: умова `if num_proc is None or num_proc == 1` веде в
послідовний шлях, тобто для `load_dataset` значення `1` і `None` рівнозначні, а для `map` — ні.
Виміряний базовий рівень (8 шардів JSONL, 160 000 прикладів, 149.5 МБ; задача `map` — 40 ітерацій
SHA-256 на приклад):

```
load_dataset(num_proc=1): 1.05 с | 160000 рядків | 152 308 рядків/с
map (один процес, CPU-задача): 11.45 с | 13 971 рядків/с
map (один процес, batched=True, batch_size=1000): 13.63 с
```

Чесне застереження про середовище, у якому готувався розділ: `multiprocess.Pool` там недоступний
(`PermissionError: [Errno 13] Permission denied` на створенні `SemLock`, бо тимчасова
shared-memory-тека недоступна), тому **виміряти** прискорення від `num_proc > 1` не вдалося. Нижче —
модель на основі виміряної вартості одного приклада (71.6 мкс) і 8 шардів; це оцінка, а не факт
вимірювання:

| `num_proc` | Рядків на процес | Модель, с | Модельне прискорення |
|---|---|---|---|
| 1 | 160 000 | 11.45 (виміряно) | 1.00× |
| 2 | 80 000 | 6.07 | 1.88× |
| 4 | 40 000 | 3.21 | 3.56× |
| 8 | 20 000 | 1.78 | 6.43× |

Дві межі цієї моделі важливі практично. Перша: прискорення обмежене кількістю шардів, а не кількістю
ядер — 16 процесів на 4 шардах не дадуть нічого понад 4. Друга: **I/O-bound задачі від `num_proc` не
виграють**. Якщо вузьке місце — один диск, один мережевий канал або один зовнішній API, додаткові
процеси лише конкурують за той самий ресурс, а накладні витрати на міжпроцесну передачу даних
(приклади серіалізуються в обидва боки) роблять результат повільнішим. Для таких задач правильний
важіль — батчування запитів і паралелізм усередині клієнта (асинхронні HTTP-виклики), а не
`num_proc`. Показова деталь із документації: у прикладі для мультимодальної обробки на кількох GPU
`num_proc` ставлять рівним `torch.cuda.device_count()` — тобто кількості **апаратних** воркерів, а не
ядер CPU.

**Швидший доступ за рахунок пам'яті.** Якщо вимкнути кеш і тримати датасет у RAM, операції
пришвидшуються — документація дає два способи: `datasets.config.IN_MEMORY_MAX_SIZE` (у байтах;
перевірено, що типове значення — `0.0`) або змінна середовища `HF_DATASETS_IN_MEMORY_MAX_SIZE`.
Перший спосіб має вищий приоритет.

**Ще один спосіб не платити за кеш двічі.** `Dataset.from_file("data.arrow")` **не** готує датасет у
кеші, а просто відображає Arrow-файл у пам'ять; текою кеша для проміжних результатів стає тека самого
Arrow-файлу. `Dataset.from_file("my_dataset/data-00000-of-00001.arrow")` читає сам Arrow і **не**
створює копії: у вимірі на 1 000 прикладів `cache_files` результату вказує на той самий файл, а тека
після виклику не виросла ані на байт. Документація обмежує застосовність: підтримується лише
streaming-формат Arrow, а IPC-формат (він же Feather V2) — ні.

**Типові помилки**

- **Тримати кеш на маленькому системному розділі.** `HF_DATASETS_CACHE` за замовчуванням у
  `~/.cache`, і саме туди підуть усі Arrow-копії. У спільних і мережевих середовищах (NFS) це ще й
  джерело повільної роботи — документація радить задавати `HF_HOME` (або обидві змінні разом).
- **Міняти лише `HF_DATASETS_CACHE` й дивуватися, що файли з Hub усе одно в старому місці.**
  За них відповідає `HF_HUB_CACHE` (issue #7480 у документації).
- **Вважати `num_proc=1` у `map` «послідовним режимом».** Це пул з одного процесу — з усіма
  накладними витратами на серіалізацію.
- **Ставити `num_proc` більшим за кількість шардів.** Бібліотека мовчки знизить його до кількості
  шардів; чекати більшого прискорення марно.
- **Ставити `num_proc` на I/O-bound задачу.** Мережа й диск не масштабуються разом із процесами.
- **Використовувати нехешовані об'єкти у функції `map`.** Замикання на `set`, на відкритий клієнт
  HTTP або на об'єкт із недетермінованим порядком елементів ламає відбиток: кеш промахується щоразу.
  Лікується `fn_kwargs` з простими серіалізованими значеннями.
- **Забувати, що `map(..., batched=True)` маскує `remove_columns` до виконання функції.** Колонки
  видаляються після передачі батча — на це прямо вказує документація, і саме тому `remove_columns`
  безпечно вказувати для тих колонок, які функція ще має прочитати.
- **Вимкнути кеш і не зберегти результат.** Файли в тимчасовій теці зникають після сесії; потрібен
  `save_to_disk`.
- **Забути `cleanup_cache_files()`.** Файли `cache-*.arrow` не видаляються самі; на датасеті з
  десятками експериментів це найшвидший спосіб зайняти диск.

**Альтернативи.** Замість кеша `datasets` для повторюваних конвеєрів беруть власне сховище у форматі
Parquet (`Dataset.to_parquet`) — файли передбачувані, переносні й читаються будь-яким рушієм.
Замість `map` на великих датасетах зі складною обробкою — винесення обробки в окремий скрипт із
власною паралелізацією (`ProcessPoolExecutor`, Spark, Ray), бо тоді вузьке місце й політика
перезапусків під вашим контролем. Для дуже великих корпусів замість завантаження — `streaming=True`
(див. 18.2) або `Dataset.from_generator` (документація зазначає, що цей шлях підтримує дані, більші за
доступну пам'ять).

---

### 18.4 Інтеграція з PyTorch

**Що це.** `datasets` уміє віддавати не Python-об'єкти, а `torch.Tensor` — через
`Dataset.with_format("torch")`; крім того, і `Dataset`, і `IterableDataset` можна передавати напряму в
`torch.utils.data.DataLoader`, а розподіл по вузлах робиться через
`datasets.distributed.split_dataset_by_node`.

**Навіщо це знати.** Це межа між «даними на диску» і «даними в GPU». Тут вирішується, чи буде
завантажувач вузьким місцем тренування: скільки копій даних створиться, чи буде форма тензорів
статичною, скільком воркерам дістанеться по шарду й що станеться при перезапуску навчання.

**Як працює під капотом.** `Dataset` — обгортка над Arrow-таблицею, і документація прямо називає
наслідок: це дозволяє **швидке читання без копіювання** (zero-copy) з масивів датасета в тензори
PyTorch. `with_format("torch")` не перетворює дані заздалегідь — він змінює те, що повертає доступ за
індексом. Реальні виводи:

```python
import torch
from datasets import Dataset

ds = Dataset.from_dict({"data": [[1, 2], [3, 4]]})
print("без формату:", ds[0])
tds = ds.with_format("torch")
print("with_format:", tds[0])
print("зріз [0:2]:", tds[:2])

device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
print("device явно:", ds.with_format("torch", device=device)[0]["data"].device)
```

```
без формату: {'data': [1, 2]}
with_format: {'data': tensor([1, 2])}
зріз [0:2]: {'data': tensor([[1, 2],
        [3, 4]])}
device явно: cpu
```

**N-вимірні масиви — місце, де з'являється прихована робота.** Якщо форма елементів однакова,
`datasets` збирає їх в один тензор; якщо різна — повертає список тензорів. Документація попереджає, що
ця логіка вимагає **порівняння форм і копіювання даних**, і радить задавати форму явно через
`Array2D`/`Array3D`/`Array4D`/`Array5D`. Реальна різниця:

```python
from datasets import Dataset, Features, Array2D, ClassLabel

fixed = Dataset.from_dict({"data": [[[1, 2], [3, 4]], [[5, 6], [7, 8]]]}).with_format("torch")
varying = Dataset.from_dict({"data": [[[1, 2], [3]], [[4, 5, 6], [7, 8]]]}).with_format("torch")
feats = Features({"data": Array2D(shape=(2, 2), dtype="int32")})
arr = Dataset.from_dict({"data": [[[1, 2], [3, 4]], [[5, 6], [7, 8]]]}, features=feats).with_format("torch")
labels = Dataset.from_dict({"label": [0, 0, 1]},
                           features=Features({"label": ClassLabel(names=["negative", "positive"])}))
mixed = Dataset.from_dict({"num": [1, 2], "s": ["a", "b"], "b": [b"x", b"y"]}).with_format("torch")

print("фіксована форма:", fixed[0])
print("різна форма:", varying[0])
print("Array2D(shape=(2, 2)):", arr[:2]["data"].shape)
print("ClassLabel:", labels.with_format("torch")[:3])
print("мішаний набір:", mixed[:2])
```

```
фіксована форма: {'data': tensor([[1, 2],
        [3, 4]])}
різна форма: {'data': [tensor([1, 2]), tensor([3])]}
Array2D(shape=(2, 2)): torch.Size([2, 2, 2])
ClassLabel: {'label': tensor([0, 0, 1])}
мішаний набір: {'num': tensor([1, 2]), 's': ['a', 'b'], 'b': [b'x', b'y']}
```

Останній рядок фіксує межу: **рядки й байти не стають тензорами** — PyTorch підтримує лише числа.
Тому токенізацію треба робити у форматі `input_ids`/`attention_mask` (списки чисел), а не сподіватися,
що рядки конвертуються самі. `ClassLabel` конвертується коректно, а `Image` і `Audio` вимагають
встановлення extras (`pip install datasets[vision]` та `pip install datasets[audio]`), про що
документація попереджає окремо.

**DataLoader і кілька воркерів.** Map-style датасет передається в `DataLoader` напряму, і батчі
виходять уже тензорами:

```python
import numpy as np
from datasets import Dataset, load_from_disk
from torch.utils.data import DataLoader

dl_ds = Dataset.from_dict({"data": np.random.rand(16),
                           "label": np.random.randint(0, 2, size=16)}).with_format("torch")
for i, batch in enumerate(DataLoader(dl_ds, batch_size=4)):
    print(i, {k: tuple(v.shape) for k, v in batch.items()}, batch["label"].tolist())
    if i == 1:
        break
```

```
0 {'data': (4,), 'label': (4,)} [0, 0, 1, 0]
1 {'data': (4,), 'label': (4,)} [0, 0, 0, 0]
```

Механіку `num_workers` документація описує так: `DataLoader` запускає `num_workers` процесів, кожен
процес **заново завантажує** переданий датасет і читає з нього приклади. Пам'ять при цьому не
роздувається, бо повторне завантаження — це лише повторне відображення файлу в пам'ять (memory
mapping). Тому рекомендований патерн — спершу `save_to_disk`, потім `load_from_disk`:

```python
Dataset.from_dict({"data": np.random.rand(10_000)}).save_to_disk("my_dataset")
ds = load_from_disk("my_dataset").with_format("torch")
dataloader = DataLoader(ds, batch_size=32, num_workers=4)
```

**Стрімінг + DataLoader.** `IterableDataset` з `datasets` успадковується від
`torch.utils.data.IterableDataset`, тому його можна передати в `DataLoader`; якщо датасет шардований,
кожен воркер отримує підмножину шардів. Арифметика проста й перевіряється одним рядком:

```python
from datasets import Dataset

sharded = Dataset.from_dict({"a": list(range(10_000))}).to_iterable_dataset(num_shards=64)
print("num_shards:", sharded.num_shards, "| шардів на воркер при num_workers=4:",
      sharded.num_shards // 4)
```

```
num_shards: 64 | шардів на воркер при num_workers=4: 16
```

У документації цей самий розрахунок наведено для `to_iterable_dataset(num_shards=64)` і
`DataLoader(..., num_workers=4)`: 64 / 4 = 16 шардів на воркер. Окремо документація нагадує, що
перемішувати треба **після** шардування (інакше воркерам дістануться невипадкові частини), а
`Dataset.to_iterable_dataset()` швидший за `load_dataset(..., streaming=True)`, бо дані вже локальні.

**Розподілене навчання.** Для розбиття даних по вузлах є
`datasets.distributed.split_dataset_by_node(ds, rank=..., world_size=...)`; він працює і для map-style,
і для iterable датасетів. Для iterable є три стратегії: `"shards"` (шарди діляться між вузлами
порівну), `"examples"` (кожен вузол лишає собі кожен `world_size`-й приклад) і `"auto"` (типово:
`"shards"`, якщо `num_shards % world_size == 0`, інакше `"examples"`). Документація додає
попередження: у розподіленому режимі з `shuffle` треба задавати **фіксований** `seed`, інакше вузли
матимуть різні списки шардів і пропускатимуть не ті шарди.

**Перезапуск навчання.** Для відновлення з чекпойнта документація пропонує `StatefulDataLoader` з
`torchdata`, який під капотом викликає `IterableDataset.state_dict()` і
`IterableDataset.load_state_dict()`:

```python
from torchdata.stateful_dataloader import StatefulDataLoader
from datasets import load_dataset

my_iterable_dataset = load_dataset("deepmind/code_contests", streaming=True, split="train")
dataloader = StatefulDataLoader(my_iterable_dataset, batch_size=32, num_workers=4)
state_dict = dataloader.state_dict()          # зберегти
dataloader.load_state_dict(state_dict)        # відновити
```

**Реальна проблема середовища, яка ламає стрімінг.** У коді 5.0.1 конструктор `IterableDataset` робить
таке: `self._epoch = _maybe_share_with_torch_persistent_workers(0)`, а ця функція, **якщо torch
доступний**, викликає `torch.tensor(value).share_memory_()`. Тобто створення `IterableDataset`
потребує writable-області shared memory. У середовищі, де вона недоступна, виклик падає ще до читання
даних:

```
RuntimeError: unable to open shared memory object </torch_168292_2970829902_0>
              in read-write mode: Permission denied (13)
```

Обхід, який використано в цьому розділі для вимірювань: змінна середовища `USE_TORCH=0`. У коді 5.0.1
перевіряється `USE_TORCH in {"1", "ON", "YES", "TRUE", "AUTO"}`, тому значення `0` вимикає
torch-інтеграцію в `datasets` і прибирає виклик `share_memory_`. Для звичайного `DataLoader` з
map-style датасетом це не потрібно.

**Типові помилки**

- **Очікувати тензорів від рядкових колонок.** Рядки й байти лишаються як є; у модель мають іти
  `input_ids` і `attention_mask`.
- **Не задавати `Array2D`-shape для масивів.** Без цього кожне читання робить порівняння форм і
  копіювання; документація називає це прямою причиною сповільнення.
- **Передавати в `DataLoader` датасет із диска без `save_to_disk`.** Кожен воркер повторно
  завантажує й повторно конвертує джерело, якщо воно не Arrow.
- **Класти `to_iterable_dataset(num_shards=N)` де `N > num_rows`.** Реальна помилка:
  `ValueError: Unable to shard a dataset of size 16 into 64 shards (the number of shards exceeds the
  number of samples).`
- **Перемішувати після розрізання на шарди.** Порядок операцій важливий: `to_iterable_dataset(num_shards=…)`,
  потім `shuffle(buffer_size=…)`, потім `DataLoader(num_workers=…)`.
- **Ставити `shuffle` у розподіленому режимі з різними сідами.** Вузли розійдуться в тому, які шарди
  кому належать.
- **Забувати про `IterableDataset` + shared memory.** У контейнерах з обмеженою або недоступною
  shared memory створення стрімінгового датасета падає з `RuntimeError`, хоча дані тут ні до чого.

**Альтернативи.** Замість `datasets`-обгортки для навчання беруть `webdataset` (TAR-шарди з
послідовним читанням), `torchdata`-конвеєри, або звичайний `Dataset` із `__getitem__` поверх
`pyarrow.parquet`. Для дуже великих корпусів замість `num_workers` у `DataLoader` роздають шарди
вузлам заздалегідь (`split_dataset_by_node`) і лишають по одному воркеру на вузол. Для
мультимодальних даних документація прямо пропонує `num_proc=torch.cuda.device_count()`, тобто по
процесу на GPU.

---
### 18.5 Datasets 5.0: трейси агентів як дані для SFT

**Що це.** У версії 5.0.0 (реліз 05.06.2026) `load_dataset` навчився читати **трейси агентів** —
файли сесій із `claude_code`, `pi`, `codex` (перелік харнесів у коді: `claude_code`, `pi`, `codex`,
`droid`; окремі маркери є також для `hermes` і `openclaw`) — і перетворювати їх на список `messages`,
придатний для тренування через `trl`. Розбір робить нова опційна залежність `teich` (у метаданих
`datasets==5.0.1` закріплено `teich==0.1.5`).

**Навіщо це знати.** Трейс агента — це найдорожчі дані, які у вас є: у ньому записано, як модель
реально викликала інструменти, отримувала помилки, переробляла план і доходила до результату. До 5.0
кожен харнес вимагав власного парсера, і саме на цьому кроці дані найчастіше втрачалися. Тепер
трейс-файл стає звичайним датасетом, а SFT зводиться до `trl sft --dataset-name …`.

**Як працює під капотом.** Трейси читає **той самий JSON-білдер**, що й звичайні JSONL: у коді 5.0.1
є прапорець конфігурації `parse_agent_traces: bool = True`, а також набір *маркерів*
(`AGENT_TRACES_FEATURES_MARKERS`), за якими білдер розпізнає, що файл — це не таблиця, а трейс:

| Харнес (за маркером) | Поля, за якими розпізнається | Типи подій у файлі |
|---|---|---|
| `claude_code` / `pi` / `openclaw` | `type` (string) + `message` (Json) | `claude_code`: `user`, `assistant`, `system`; `pi`: `session`, `message` |
| `codex` | `type` (string) + `payload` (Json) | `session_meta`, `turn_context`, `response_item`, `event_msg` |
| `droid` / `hermes` | `droid`: `type`, `id`, `version`, `cwd`; `hermes`: `id`, `source`, `model`, `system_prompt`, `messages` | `droid` — `session_start`; `hermes` — кілька сесій в одному файлі |

Розпізнавши маркери, білдер підміняє схему на `AGENT_TRACES_FEATURES`. Ось повний реальний перелік
колонок (узято з коду 5.0.1):

```python
import datasets
from datasets import config
from datasets.packaged_modules.json.json import AGENT_TRACES_FEATURES, AGENT_TRACES_TYPES_VALUES

print("TEICH_AVAILABLE:", config.TEICH_AVAILABLE)
print("харнеси:", list(AGENT_TRACES_TYPES_VALUES))
print("колонки:", list(AGENT_TRACES_FEATURES))
```

```
TEICH_AVAILABLE: False
харнеси: ['claude_code', 'pi', 'codex', 'droid']
колонки: ['harness', 'session_id', 'prompt', 'messages', 'tools', 'metadata',
          'sent_at', 'num_user_messages', 'num_tool_calls', 'trace', 'file_path']
```

Розподіл колонок у коді підписано так: `harness` і `session_id` — базові; `prompt`, `messages`,
`tools`, `metadata` — формуються `teich`; `sent_at`, `num_user_messages`, `num_tool_calls`, `trace`,
`file_path` — «бонусні». Модель даних — **один трейс-файл = один рядок** (`file_path` зберігає шлях),
крім `hermes`, де в одному файлі може бути кілька сесій.

**Що відбувається без `teich`.** Це найкорисніший практичний факт підтеми. Білдер розпізнає трейс і
вимагає `teich`, а помилка при цьому виходить **загорнута**: назовні видно лише
`DatasetGenerationError`, а справжня причина — у `__cause__`. Два реальні випадки для локального
файлу з подіями `claude_code`:

```python
import json
from datasets import load_dataset
from datasets.packaged_modules.json.json import AGENT_TRACES_FEATURES

# Випадок 1: схему задано явно (так робить картка датасета на Hub)
with open("session.jsonl", "w") as f:
    for event in [{"type": "user", "message": {"role": "user", "content": "Порахуй рядки"}},
                  {"type": "assistant", "message": {"role": "assistant", "content": "Гаразд"}}]:
        f.write(json.dumps(event) + "\n")
load_dataset("json", data_files="session.jsonl", split="train", features=AGENT_TRACES_FEATURES)

# Випадок 2: тип колонки message змішаний -> вона стає Json -> маркери збігаються
with open("mixed.jsonl", "w") as f:
    for row in [{"type": "user", "message": "просто рядок"},
                {"type": "assistant", "message": {"role": "assistant", "content": "ок"}}]:
        f.write(json.dumps(row) + "\n")
load_dataset("json", data_files="mixed.jsonl", split="train")
```

```
DatasetGenerationError: An error occurred while generating the dataset
  причина: ImportError : To support decoding agent traces, please install 'teich'.
DatasetGenerationError: An error occurred while generating the dataset
  причина: ImportError : To support decoding agent traces, please install 'teich'.
```

Друга пастка тонша: **автоматичне** розпізнавання спрацьовує лише тоді, коли колонка `message`
виведена як `Json`, а не як структура. Файл, де `message` — вкладений об'єкт із однаковими полями,
читається як звичайна таблиця, і жодного `ImportError` не буде.

Вихід, якщо `teich` не потрібен або не встановлюється: `parse_agent_traces=False` у виклику
`load_dataset` — тоді файл читається як звичайний JSONL зі структурованими колонками (`type`,
`message`), без підміни схеми.

**Структура `messages` для SFT.** У прикладі з релізних нотаток `ds[0]["messages"]` — це список
словників із полями `role` і `content`, а той самий формат очікує `trl`:

```python
from datasets import load_dataset

ds = load_dataset("lhoestq/agent-traces-example", split="train")
print(ds[0]["messages"])
```

```
[{'role': 'user', 'content': 'Download a random dataset from Hugging Face, use DuckDB to inspect it,
  and come back with a short report about it. Be concise and include: dataset name, what files/format
  you found, row count or rough size if you can determine it,...'}
 ...]
```

```bash
trl sft --dataset-name lhoestq/agent-traces-example --output-dir out
```

Перед тренуванням такий список варто перевірити: дефекти трас трапляються частіше, ніж у звичайних
чат-датасетах, бо трейси пишуться інструментами, а не людьми. Реальний приклад перевірки на stdlib
(він же в ноутбуку до розділу):

```python
ROLES = ("system", "user", "assistant", "tool")
TRAIN_ROLES = ("assistant",)

def validate_trace(trace):
    problems = []
    if not isinstance(trace, list) or not trace:
        return ["messages порожній або не список"]
    for i, msg in enumerate(trace):
        if not isinstance(msg, dict):
            problems.append(f"[{i}] не словник")
            continue
        if msg.get("role") not in ROLES:
            problems.append(f"[{i}] невідома роль {msg.get('role')!r}")
        if not isinstance(msg.get("content"), str):
            problems.append(f"[{i}] content не рядок ({type(msg.get('content')).__name__})")
    if not any(m.get("role") == "assistant" for m in trace if isinstance(m, dict)):
        problems.append("немає жодного повідомлення assistant — вчитися нема на чому")
    return problems

print(validate_trace([{"role": "system", "content": "інструкція"},
                      {"role": "user", "content": "питання"}]))
```

```
['немає жодного повідомлення assistant — вчитися нема на чому']
```

**Маскування цілі — окремий крок, якого `datasets` не робить.** Бібліотека віддає `messages`;
перетворення в `input_ids` і вибір токенів, на яких вважається втрата, — ваша відповідальність
(через `map` із `tokenizer.apply_chat_template`). Нижче — **схема**, а не API:

```
role=system     -> tokens: 0  (інструкція, не вчимо)
role=user       -> tokens: 0  (питання, не вчимо)
role=assistant  -> tokens: 1  (ціль)
role=tool       -> tokens: 0  (результат інструмента, не вчимо)
```

Для трейсів агента це має особливе значення: якщо не замаскувати `role=tool`, модель почне
генерувати **виводи інструментів** (у тому числі вигадані JSON-и), а не виклики. Реальне застосування
маски до п'яти повідомлень із прикладу вище:

```
[('system', 0), ('user', 0), ('assistant', 1), ('tool', 0), ('assistant', 1)]
```

**Скільки це важить на диску.** Оцінка для трейсів за виміряним відношенням Arrow/JSONL = 0.74 на
SFT-подібних даних: 1 000 трейсів — близько 0 МБ, 10 000 — 0.04 ГБ JSONL і 0.03 ГБ Arrow, 100 000 —
0.52 ГБ JSONL і 0.38 ГБ Arrow. Самі трейси малі; вага з'являється від **довжини** послідовності.
Один трейс із 50 викликами інструментів може розгорнутися в десятки тисяч токенів, і саме тому в
колонках є `num_tool_calls` і `num_user_messages`: за ними трейси фільтрують до тренування, а не
після.

**Інші зміни 5.0.0, які впливають на роботу з даними**

| Зміна | Суть | Що робити |
|---|---|---|
| Перемішування в стрімінгу | Буфер наповнюється з кількох вхідних шардів (типово 10) | **Ламальна зміна**; для старої поведінки — `max_buffer_input_shards=1` |
| `batch(by_column=...)` | Батчі групуються за значенням колонки (наприклад за епізодом) | Для робототехніки й послідовних даних |
| Нові формати | Apache Iceberg, TsFile (Apache IoTDB), 3D-mesh (`MeshFolder`), `.conll`/`.conllu` | Перевіряти наявність відповідних extras |
| `Json()` і `null` | `None` зберігається як справжній null, а не як рядок `"null"` | Раніше могло давати `"null"` у даних |
| Складені split-и в стрімінгу | Підтримка композитних split-ів для `IterableDataset` | Зрізи виду `train+test` працюють і в стрімінгу |
| `to_sql(num_proc=…)` | Паралельний запис у SQL | Для вивантаження великих датасетів |

**Типові помилки**

- **Ловити `DatasetGenerationError` і не дивитися причину.** Реальна причина
  (`ImportError: … please install 'teich'`) лежить у `__cause__`; діагностика вимагає
  `traceback.format_exc()` або `e.__cause__`.
- **Вважати, що будь-який JSONL із `type` і `message` розпізнається як трейс.** Потрібно, щоб
  колонка `message` мала тип `Json`, а не виведену структуру.
- **Встановлювати `teich` «про всяк випадок» на проді.** Це додаткова залежність; якщо трейси не
  тренуються, `parse_agent_traces=False` дешевший.
- **Чекати на один рядок на повідомлення.** Модель даних — один рядок на **файл** трейса (крім
  `hermes`); фільтрувати довгі сесії треба за `num_tool_calls`, а не за кількістю рядків.
- **Публікувати трейси без чистки.** Трейс містить усе, що агент бачив: вміст файлів, змінні
  середовища, відповіді API. Це дані, а не лог; перед публікацією їх треба сканувати на секрети й
  персональні дані — бібліотека цього не робить і робити не може.
- **Змішувати трейси різних харнесів в одну навчальну вибірку без мітки.** Поле `harness` існує саме
  для цього; без розділення ви отримаєте модель, що плутає формати викликів.

**Альтернативи.** Свій парсер для конкретного харнеса — виправданий, якщо потрібні поля, яких немає в
`AGENT_TRACES_FEATURES` (наприклад власні метрики по кожному кроку). Готові SFT-датасети з чатів
(наприклад `HuggingFaceH4/ultrachat_200k`, який README показує в прикладі з
`apply_chat_template`) — дешевша база, коли трейсів мало. Для трейсів без інструментів звичайний
`Dataset.from_list` із власною схемою простіший за весь механізм маркерів.

---

### 18.6 Типові помилки й витрати диска

**Що це.** Зведення витрат, які створює робота з `datasets`: місце на диску (сирі файли + Arrow +
усі кешовані результати `map`), пам'ять (розмір батчів і буферів), час (конвертація й перетворення),
а також перелік помилок, які не дають діагностики.

**Навіщо це знати.** Обчислення витрат заздалегідь — єдиний спосіб уникнути ситуації «диск закінчився
посеред конвертації», коли частина кеша вже записана і її доводиться чистити вручну.

**Як працює під капотом.** Три множники витрат.

1. **Сирі файли.** Лежать у кеші Hub (`~/.cache/huggingface/hub`) і залишаються там після
   конвертації. Для стиснених форматів (`.json.gz`) на диску осідає і архів, і розпакований файл.
2. **Arrow-копія.** Для локальних JSONL виміряно стиснення 0.35× (10.64 МБ → 3.74 МБ) і 0.74× на
   SFT-подібних даних (4.61 МБ → 3.43 МБ). Стиснення залежить від повторюваності тексту, тому
   оцінювати «на око» не можна.
3. **Результати перетворень.** Кожен `map` із новою функцією — повна копія. Три `map` на датасеті
   дали 4 файли `.arrow` замість одного (вимір у 18.3).

**Калькулятор витрат (реальний код, stdlib):**

```python
def disk_plan(n_examples: int, bytes_per_example: int, arrow_ratio: float = 0.74,
              n_transforms: int = 3, source_kept: bool = True) -> dict:
    # arrow_ratio — відношення Arrow/JSONL (0.35…0.75 за вимірами); n_transforms — скільки map у кеші
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

print(disk_plan(1_000_000, 460))        # ~460 Б на приклад, 3 map
print(disk_plan(10_000_000, 1500, n_transforms=1))
```

```
{'сирі файли, ГБ': 0.46, 'Arrow-джерело, ГБ': 0.34, 'кеш map × N, ГБ': 1.021, 'разом, ГБ': 1.822}
{'сирі файли, ГБ': 15.0, 'Arrow-джерело, ГБ': 11.1, 'кеш map × N, ГБ': 11.1, 'разом, ГБ': 37.2}
```

Другий рядок — типова історія «зникло 40 ГБ»: 10 мільйонів прикладів по 1.5 КБ (це чат-трейси з
кількома викликами інструментів) перетворюються в 37 ГБ, при тому що «розмір датасета» дорівнює
15 ГБ. Різницю з'їдає Arrow-копія плюс один збережений `map`.

**Що з цього випливає для планування.** Стиснення Arrow залежить від повторюваності тексту: виміряно
0.35× (репетативний український текст) і 0.74× (SFT-подібні `messages`), тобто для прикладів із
5 повідомлень беріть ~0.4–0.5 КБ на приклад. `size_in_bytes` із `dataset_info.json` **занижує**
реальний обсяг кеша, бо не враховує проміжні `map`. Конвертація JSONL дешева (152 тис. рядків/с на
8 шардах), а вся вага часу — у функції `map` (14 тис. рядків/с на CPU-задачі).

**Порядок перевірок перед великим завантаженням:** чи потрібен весь датасет (`split="train[:10%]"`
або `streaming=True`), чи вказані `data_files` (без них повертаються всі файли — для C4 це ~13 ТБ),
куди піде кеш (`HF_HOME` або `HF_DATASETS_CACHE` + `HF_HUB_CACHE`), скільки займе Arrow
(`dataset_info.json`: `download_size`, `dataset_size`), скільки `map` буде збережено
(`cache-*.arrow`), чи є шарди для `num_proc` (`num_shards`) і чи потрібен `teich` (якщо дані —
трейси агентів, інакше `parse_agent_traces=False`).

**Типові помилки** (зведено з усіх підтем)

| Помилка | Симптом | Лікування |
|---|---|---|
| `data_files` не вказано | Завантаження, що не закінчується | Вказати файли або `data_dir`, або взяти `split[:N]` |
| `num_proc=1` у `map` | Пул з одного процесу, зайві витрати | Не передавати `num_proc` |
| `num_proc` більший за кількість шардів | Прискорення немає | Знизити або перешардувати |
| I/O-bound робота під `num_proc` | Повільніше, ніж без паралелізму | Батчування й async-клієнт замість процесів |
| Недетермінований об'єкт у функції `map` | Кеш ніколи не влучає | Прості серіалізовані `fn_kwargs` |
| `cleanup_cache_files()` не викликано | Диск заповнюється `cache-*.arrow` | Прибирати після експериментів |
| `to_iterable_dataset(num_shards=N)`, `N > num_rows` | `ValueError: Unable to shard a dataset of size …` | `N ≤ кількості рядків` |
| `take`/`skip` перед `shuffle` | Перемішування не працює | Спершу `shuffle`, потім розрізання |
| `teich` не встановлено | `DatasetGenerationError` без причини | Дивитися `__cause__` або `parse_agent_traces=False` |
| `/dev/shm` недоступний + torch | `RuntimeError: unable to open shared memory object` | `USE_TORCH=0` або writable shared memory |
| Довгі трейси без фільтра | OOM на послідовностях | Фільтр за `num_tool_calls` |

**Альтернативи.** Коли `datasets` стає вузьким місцем: `webdataset` для шардових TAR-архівів;
DuckDB/Polars — для табличних запитів і фільтрів без конвертації; власний `IterableDataset` на
`torch.utils.data` — коли потрібна повна влада над порядком і чекпойнтами; стрімінгові файлові
формати (Parquet, Vortex, Lance) — коли диск менший за дані.

**Куди далі:**

- Розділ 21 — fine-tuning споживає ці дані: SFT-тренування бере `Dataset` і застосовує chat-шаблон
  до колонки `messages` ще на етапі підготовки.
- Розділ 19 — `pipeline` і потокова обробка великих датасетів: 19.3 показує, як годувати
  `IterableDataset` у генерацію, не завантажуючи все в пам'ять.
- Розділ 22 — звідки беруться дані: `hf download --repo-type dataset`, вивантаження власних
  датасетів і Jobs, які монтують їх read-only.
- Розділ 3 — `messages` у трейсах агентів і chat-шаблони: підтема 3.4 пояснює, у що
  перетворюється структура повідомлень перед подачею в модель.

**Джерела**

- [Hugging Face Datasets — Load](https://raw.githubusercontent.com/huggingface/datasets/main/docs/source/loading.mdx) — `load_dataset`, `data_files`/`data_dir`/`revision`/`field`, підтримувані формати, `ReadInstruction` і зрізи split-ів, `pct1_dropremainder`, `HF_HUB_OFFLINE`, in-memory джерела, мультипроцесна підготовка шардів → `research/hf5_dsdoc_loading.txt`
- [Hugging Face Datasets — Stream](https://raw.githubusercontent.com/huggingface/datasets/main/docs/source/stream.mdx) — `IterableDataset`, `take`/`skip`/`shard`/`reshard`/`batch`, буфер перемішування, `set_epoch`, `state_dict`, `concatenate_datasets`, `interleave_datasets`, `columns`/`filters`, експорт → `research/hf5_dsdoc_stream.txt`
- [Hugging Face Datasets — Cache management](https://raw.githubusercontent.com/huggingface/datasets/main/docs/source/cache.mdx) — `HF_HOME`/`HF_DATASETS_CACHE`/`HF_HUB_CACHE`, issue #7480, `download_mode`, `cleanup_cache_files`, `disable_caching`, `IN_MEMORY_MAX_SIZE` → `research/hf5_dsdoc_cache.txt`
- [Hugging Face Datasets — The cache](https://raw.githubusercontent.com/huggingface/datasets/main/docs/source/about_cache.mdx) — відбитки (fingerprints), `Hasher`, хешування функцій і параметрів, поведінка вимкненого кеша → `research/hf5_dsdoc_about_cache.txt`
- [Hugging Face Datasets — Use with PyTorch](https://raw.githubusercontent.com/huggingface/datasets/main/docs/source/use_with_pytorch.mdx) — `with_format("torch")`, `device`, `Array2D`, `ClassLabel`, `Image`/`Audio`, `DataLoader`, `num_workers`, `StatefulDataLoader`, `split_dataset_by_node` → `research/hf5_dsdoc_use_with_pytorch.txt`
- [Hugging Face Datasets — Main classes](https://raw.githubusercontent.com/huggingface/datasets/main/docs/source/package_reference/main_classes.mdx) — перелік методів `Dataset`, `DatasetDict`, `IterableDataset`, `IterableDatasetDict`, типи `Features` → `research/hf5_dsdoc_package_reference_main_classes.txt`
- [Hugging Face Datasets — Differences between Dataset and IterableDataset](https://raw.githubusercontent.com/huggingface/datasets/main/docs/source/about_mapstyle_vs_iterable.mdx) — точне й наближене перемішування, падіння швидкості до 10× після індексної мапи, `flatten_indices`, ефективний сід `seed + epoch`, `num_shards` для генераторів → `research/hf5_dsdoc_about_mapstyle_vs_iterable.txt`
- [Hugging Face Datasets — Process](https://raw.githubusercontent.com/huggingface/datasets/main/docs/source/process.mdx) — `map`, `batched`, `batch_size` (типово 1000), `num_proc`, `num_proc=torch.cuda.device_count()`, `batch(by_column=…)` → `research/hf5_dsdoc_process.txt`
- [Hugging Face Datasets — README](https://raw.githubusercontent.com/huggingface/datasets/main/README.md) — дві основні сутності, extras для `torch`/`vision`/`audio`, `map(num_proc=N)`, перелік форматів → `research/datasets_readme.txt`
- [huggingface/datasets 5.0.0 — release notes (05.06.2026)](https://github.com/huggingface/datasets/releases/tag/5.0.0) — трейси агентів, `teich`, нова механіка перемішування (`max_buffer_input_shards`), `batch(by_column=…)`, нові формати → `research/datasets_5_release.txt`, `research/hf5_ds5.md`
- [PyPI — `datasets`](https://pypi.org/pypi/datasets/json) — остання версія `5.0.1`, `requires_python >=3.10.0` (перевірено 09.2026)
- [PyPI — метадані `datasets==5.0.1`](https://pypi.org/pypi/datasets/5.0.1/json) — extras і закріплення `teich==0.1.5` (перевірено локально в `datasets-5.0.1.dist-info/METADATA`)
- Джерела кодом (перевірено в `datasets==5.0.1`): `datasets/packaged_modules/json/json.py` (`AGENT_TRACES_FEATURES`, `AGENT_TRACES_TYPES_VALUES`, `AGENT_TRACES_FEATURES_MARKERS`, `parse_agent_traces`, `ImportError` про `teich`), `datasets/arrow_dataset.py` (`mp.Pool(num_proc)` при `num_proc >= 1`, `LazyRow`, `_get_cache_file_path`), `datasets/builder.py` (зниження `num_proc` до кількості шардів), `datasets/iterable_dataset.py` (`share_memory_` для `_epoch`), `datasets/fingerprint.py` (`TEMP_CACHE_DIR_PREFIX`, `generate_random_fingerprint`), `datasets/config.py` (`USE_TORCH`, `HF_DATASETS_CACHE`, `IN_MEMORY_MAX_SIZE`)

**Що не вдалося підтвердити**

- Точне ім'я runtime-extra для `teich`: у метаданих `datasets==5.0.1` закріплення `teich==0.1.5`
  стоїть в extras `dev`/`tests`/`tests-numpy2`, а релізні нотатки називають `teich` «новою опційною
  залежністю». Окремий публічний extra для трейсів у метаданих не знайдено — не вдалося підтвердити
  станом на 09.2026.
- Схема представлення викликів інструментів усередині `messages` (як саме `teich` кодує `tool_calls`):
  без встановленого `teich` і без доступу до датасета на Hub перевірити не вдалося — не вдалося
  підтвердити станом на 09.2026.
- Фактичне прискорення від `num_proc > 1`: середовище підготовки не дає створити жоден
  `multiprocess.Pool` (`PermissionError` на `SemLock`), тому в розділі наведено модель, а не вимір.
- Реальне перемішування з `max_buffer_input_shards` на датасеті з великою кількістю шардів (у
  релізних нотатках наведено приклад із `num_shards=1024`): перевірено лише на 4 локальних шардах.

