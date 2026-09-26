## 19. Transformers v5: pipeline, generate, attention, auto-класи

У v5 змінилися не окремі параметри, а самі шари бібліотеки: тільки PyTorch як бекенд, один
токенізаційний файл замість пари «повільний/швидкий», новий механізм завантаження ваг, окремий реєстр
реалізацій уваги й нове покоління API для інференсу (`transformers serve`, безперервний батчинг, paged
attention). Код під 4.x ламається не в одному місці, а десятьма різними способами — від видаленого
`load_in_8bit` до зміненого типу повернення `apply_chat_template`.

Розділ дає перелік ламальних змін, чеклист міграції й практику по `pipeline`, `generate`, інтерфейсу
уваги та auto-класах. Факти взяті з `MIGRATION_GUIDE_V5.md`, анонсу v5, офіційних гайдів і **реальних
сирців `transformers`** (`research/hf5src/`).

### 19.1 Що змінилося у v5: перелік ламальних змін

**Що це.** Мажорний реліз, у якому прибрано цілі підсистеми (TensorFlow, JAX, torchscript, `torch.fx`,
`safe_serialization=False`), переписано завантаження ваг і уніфіковано токенізацію. Гайд називає це
«library-wide changes with widespread impact».

**Навіщо це знати.** Частина коду падає не з помилкою, а з **мовчазно іншою поведінкою**.
Найнебезпечніший приклад — `apply_chat_template`: у v4 він повертав «голий» `input_ids`, у v5 —
`BatchEncoding`. Код `tokenizer.apply_chat_template(...).shape` отримає `AttributeError`, а код, що
передавав результат далі як тензор, зламається пізніше й неочевидно.

**Як працює під капотом.** Масштаб видно з цифр анонсу: v4.0.0rc-1 вийшов 19 листопада 2020 року,
v5.0.0rc-0 — «п'ять років потому» (блог опубліковано 1 грудня 2025 року). За цей час бібліотека
виросла з 40 архітектур до понад 400, сумісних чекпойнтів на Hub — з ~1 000 до понад 750 000,
встановлень — з 20 000 до понад 3 млн на день (понад 1,2 млрд усього).

#### Що видалено повністю

| Що | Заміна / наслідок |
|---|---|
| TensorFlow і JAX частини | Єдиний бекенд — `torch`; сумісність із JAX (MaxText) окремо |
| `torchscript` | `dynamo` |
| `torch.fx` | `export` |
| `safe_serialization=False` | Лише `model.state_dict()` вручну |
| `load_in_4bit`, `load_in_8bit` | Тільки `quantization_config` |
| `use_auth_token` | Тільки `token` |
| Head masking, relative positional biases у Bert-подібних, head pruning | Потрібні — залишайтеся на 4.x (працювали лише з `eager`) |
| `question-answering`, `Text2TextGenerationPipeline`, `SummarizationPipeline`, `TranslationPipeline`, `image-to-text`, `visual-question-answering`, `image-to-image` | Відповідний чат- або `image-text-to-text` pipeline |
| `AutoModelWithLMHead`, `AutoModelForVision2Seq` | `AutoModelForCausalLM` / `AutoModelForMaskedLM` / `AutoModelForSeq2SeqLM`, `AutoModelForImageTextToText` |
| `TRANSFORMERS_CACHE`, `PYTORCH_TRANSFORMERS_CACHE`, `PYTORCH_PRETRAINED_BERT_CACHE` | `HF_HOME` |
| `transformers-cli`, `transformers run` | Єдина точка входу — `transformers` |

#### Що змінилося у поведінці (тихе ламання)

| Область | v4 | v5 |
|---|---|---|
| `apply_chat_template` | Повертав `input_ids` | Повертає `BatchEncoding` (`input_ids`, `attention_mask`, ...) |
| `batch_decode` / `decode` | Два різні методи | Один `decode`; на списку входів повертає список рядків |
| `encode_plus` | Окремий метод | Застарілий, використовуйте `__call__` |
| Токенізатори | `tokenization_<model>.py` + `tokenization_<model>_fast.py` | Один файл `tokenization_<model>.py`, бекенд підбирає `AutoTokenizer` |
| Збереження токенізатора | `special_tokens_map.json`, `added_tokens.json` | Спецтокени — у `tokenizer_config.json`, додані — у `tokenizer.json` |
| `additional_special_tokens` | Окремий список | Автоконвертація в `extra_special_tokens`; `additional_special_tokens_ids` → `extra_special_tokens_ids` |
| `get_text_features` та інші `get_*_features` | Пулінговий тензор | `BaseModelOutputWithPooling`-подібний об'єкт; беріть `.pooler_output` |
| RoPE | `config.rope_theta` | `config.rope_parameters`; `rope_theta` кидає `AttributeError` |
| Генераційні параметри | Доступні з `model.config` | Тільки `model.generation_config` |
| `use_fast` у процесорах зображень | `use_fast=True/False` | `backend="torchvision"` / `backend="pil"` |
| Розмір шарду типово | 5 ГБ | 50 ГБ (завдяки Xet) |
| HTTP-бекенд `huggingface_hub` | `requests` | `httpx`; `hf_transfer` прибрано на користь `hf_xet` |

#### Дрібніші, але реальні зміни

- **`generate`:** старі псевдоніми типів виходу (наприклад `GreedySearchEncoderDecoderOutput`) видалені;
  лишилося **4 класи виходу** за матрицею decoder-only/encoder-decoder × з променями/без; класи
  декодування щодо обмежень (constraints) і beam scores переїхали на Hub; якщо `generate` не отримує
  аргументу KV-кеша, **клас кеша типово визначає сама модель**, а не завжди `DynamicCache`.
- **Конфігурація:** методи `from_xxx_config` видалені; конфіг **не можна** завантажити з URL; родини
  Qwen-VL мають вкладений конфіг (`config.vocab_size` кидає помилку, потрібно
  `config.text_config.vocab_size`); моделі без генерації більше не мають `generation_config`.
- **Застереження самих RC:** PEFT + MoE з адаптерами ламається (issue 42491); tensor/expert parallel + MoE
  не працюють як очікується, поки підтримку узгоджують із vLLM; шляхи `transformers.tokenization_utils`
  і `transformers.tokenization_utils_fast` більше не існують; власні `PreTrainedModel` ініціалізуються
  загальною схемою — щоб зберегти свою, перевизначте `_init_weights` порожнім методом (issue 42418).

**Робочий приклад.** Найкорисніша дія з цим переліком — перетворити його на аудит: витягти з гайду всі
згадані ідентифікатори API. Код нижче працює без `transformers` і без GPU.

```python
import pathlib
import re

# Локальна копія MIGRATION_GUIDE_V5.md із репозиторію transformers.
guide = pathlib.Path("research/tf_v5_migration.txt").read_text(encoding="utf-8")
mentioned = sorted(set(re.findall(r"`([A-Za-z_][A-Za-z0-9_.]*\(?\)?)`", guide)))
v4_api = [n for n in mentioned if re.search(
    r"^(load_in_|use_auth_token|encode_plus|batch_decode|prepare_seq2seq_batch|AutoModelWithLMHead|"
    r"AutoModelForVision2Seq|special_tokens_map|added_tokens|sanitize_special_tokens|"
    r"as_target_tokenizer|parse_response|TRANSFORMERS_CACHE|PYTORCH_TRANSFORMERS_CACHE|"
    r"torch_dtype|use_fast)\b", n)]

print(f"Усього ідентифікаторів у гайді: {len(mentioned)}")
print(f"З них v4-специфічних у моєму списку: {len(v4_api)}")
print(", ".join(v4_api))
```

Реальний вивід (лапки з іменем у дужках, як `AutoImageProcessor.register()`, теж потрапляють у вибірку):

```text
Усього ідентифікаторів у гайді: 258
З них v4-специфічних у моєму списку: 15
AutoModelForVision2Seq, AutoModelWithLMHead, PYTORCH_TRANSFORMERS_CACHE, TRANSFORMERS_CACHE, added_tokens.json, as_target_tokenizer(), batch_decode, encode_plus, parse_response(), prepare_seq2seq_batch(), sanitize_special_tokens(), special_tokens_map, special_tokens_map.json, use_auth_token, use_fast
```

**Типові помилки**

- Оновити `transformers`, не перевіривши код на `load_in_4bit` / `load_in_8bit`: помилка виникне лише
  в момент завантаження моделі, тобто у продакшні.
- Сподіватися, що `model.config.rope_theta` ще працює — для частини моделей його немає.
- Вважати `trust_remote_code` безпечним: гайд прямо перелічує несумісність старих remote-code
  репозиторіїв через видалені шляхи `tokenization_utils*`.

**Альтернативи.** Якщо код залежить від head masking, relative positional biases у Bert-подібних або
head pruning, єдиний коректний варіант — **залишитися на 4.x** (гайд радить саме це). Для решти
перехід на v5 — не «оновлення залежності», а проєкт міграції (19.2).

**Джерела**: [MIGRATION_GUIDE_V5.md](https://raw.githubusercontent.com/huggingface/transformers/main/MIGRATION_GUIDE_V5.md),
[Transformers v5 — анонс](https://huggingface.co/blog/transformers-v5)

### 19.2 Міграція коду з v4 на v5

**Що це.** Послідовність дій, що перетворює робочий код на 4.x у робочий код на 5.x без зміни
поведінки продукту.

**Навіщо це знати.** Половина змін — механічні заміни, які робить навіть sed. Друга половина —
семантичні: там, де змінився тип повернення або місце зберігання даних, старий код продовжує
компілюватися, але робить не те. Порядок міграції визначає, скільки часу ви витратите на пошук причин
дивної поведінки.

**Як працює під капотом.** Гайд дає пряме правило для найпростішого випадку: «`use_auth_token`
застарілий на користь `token` всюди. Пошук і заміна `use_auth_token` на `token` має дати ту саму
логіку». Ті самі «пошук і заміна» працюють для кількох інших пар, але там, де змінилася модель даних,
заміна неможлива.

#### Крок 1. Механічні заміни

| v4 | v5 |
|---|---|
| `use_auth_token=` | `token=` |
| `torch_dtype=` | `dtype=` |
| `encode_plus(` | `(` (через `__call__`) |
| `load_in_4bit=True` / `load_in_8bit=True` | `quantization_config=BitsAndBytesConfig(load_in_4bit=True)` |
| `AutoModelWithLMHead` | `AutoModelForCausalLM` / `AutoModelForMaskedLM` / `AutoModelForSeq2SeqLM` |
| `AutoModelForVision2Seq` | `AutoModelForImageTextToText` |
| `AutoImageProcessor(..., use_fast=False)` | `AutoImageProcessor(..., backend="pil")` |
| `TRANSFORMERS_CACHE` | `HF_HOME` |
| `transformers-cli` | `transformers` |
| `tokenizer.additional_special_tokens_ids` | `tokenizer.extra_special_tokens_ids` |
| `BatchEncoding.words()` | `BatchEncoding.word_ids()` |

`torch_dtype` окремо варто виділити: у сирцях v5 він ще приймається, але з попередженням
`"`torch_dtype` is deprecated! Use `dtype` instead!"` (`research/hf5src/modeling_utils.py`, рядок 1409).

#### Крок 2. Змінені типи повернення (перевіряти вручну)

1. **`apply_chat_template` → `BatchEncoding`.** Замість тензора беріть `["input_ids"]`.
2. **`get_text_features` / `get_image_features` / `get_audio_features` / `get_video_features` →
   `BaseModelOutputWithPooling`.** Потрібно `outputs = model.get_text_features(**inputs,
   return_dict=True)` і далі `outputs.pooler_output`. Гайд попереджає: єдиної універсальної форми для
   `last_hidden_state` і `pooler_output` немає — перевіряйте на невеликому forward-проході.
3. **`decode` / `batch_decode`.** Приклад із гайду:

```python
from transformers import AutoTokenizer

tokenizer = AutoTokenizer.from_pretrained("t5-small")
inputs = ["hey how are you?", "fine"]
print(tokenizer.decode(tokenizer.encode(inputs)))
```

Результат переходу (цитата з гайду):

```diff
- 'hey how are you?</s> fine</s>'
+ ['hey how are you?</s>', 'fine</s>']
```

Там же є примітка, яку варто прочитати двічі: типовий ланцюжок `encode` → `model.generate` → `decode`
у v5 не збігається за типами, бо `generate` повертає `list[list[int]]`, а `decode` очікує інше.
Перевірте цей ланцюжок у своєму коді окремо.

#### Крок 3. Токенізаційні файли й атрибути

- `special_tokens_map.json` і `added_tokens.json` більше не створюються; `added_tokens_decoder`
  записується лише тоді, коли `tokenizer.json` немає; `add_bos_token` і `add_eos_token` більше не
  зберігаються в `tokenizer_config.json`.
- `special_tokens_map` містить лише **іменовані** спецтокени; додаткові — в `extra_special_tokens`.
  `special_tokens_map_extended` і `all_special_tokens_extended` видалені; об'єкти `AddedToken` беріть із
  `_special_tokens_map` / `_extra_special_tokens`. `extra_special_tokens` приймає **лише** список або
  кортеж.
- Видалено автсинхронізацію налаштувань бекенда (`add_prefix_space`, `do_lower_case`, `strip_accents`,
  `tokenize_chinese_chars`) після ініціалізації.

Практичний наслідок: скрипти, які **патчили** ці файли на диску після `save_pretrained`, перестануть
працювати — файлів більше немає.

#### Крок 4. Видалені методи токенізатора

`sanitize_special_tokens()` прибрано (був застарілий ще у v4); `prepare_seq2seq_batch()` замінено на
`tokenizer(src_texts, text_target=tgt_texts, max_length=128, return_tensors="pt")` із подальшим
`model_inputs["labels"] = model_inputs.pop("input_ids_target")`; `create_token_type_ids_from_sequences()`
прибрано з базового класу (реалізуйте в підкласі); `prepare_for_model()`,
`build_inputs_with_special_tokens()`, `truncate_sequences()` переїхали в `tokenization_python.py`;
`as_target_tokenizer()` замінено на `tokenizer(text_target=...)`; `parse_response()` прибрано.

#### Крок 5. `TrainingArguments`, `Trainer`, пайплайни, середовище

Пайплайни: `question-answering`, `Text2TextGenerationPipeline` і пов'язані `SummarizationPipeline`,
`TranslationPipeline`, а також `image-to-text`, `visual-question-answering`, `image-to-image` видалені.
Причина в гайді сформульована прямо: для майже всіх текстових задач сучасна чат-модель із
`TextGenerationPipeline` дає якісніший результат. Окремо змінено контракт `image-text-to-text`:
зображення більше **не** передається окремим аргументом — воно має бути в полі `content` повідомлення.

Видалено без циклу депрекації: `mp_parameters`, `_n_gpu`, `overwrite_output_dir`, `logging_dir`,
`jit_mode_eval`, `tpu_num_cores`, `past_index`, `ray_scope`, `warmup_ratio`. Частина переїхала у змінні
середовища: `TENSORBOARD_LOGGING_DIR`, `TPU_NUM_CORES`, `RAY_SCOPE`. Інші заміни: `warmup_ratio` →
`warmup_step` (приймає float), `no_cuda` → `use_cpu`, `fp16_backend` / `half_precision_backend` →
`torch.amp`, `per_gpu_train_batch_size` → `per_device_train_batch_size`, `include_inputs_for_metrics` →
`include_for_metrics`, `push_to_hub_token` → `hub_token`; у `Trainer` — `tokenizer` →
`processing_class`, `model_path` → `resume_from_checkpoint`. Нова типова поведінка: `use_cache` у конфізі
моделі виставляється в `False`.

Середовище: v5 пінить `huggingface_hub>=1.0.0`; HTTP-бекенд перейшов із `requests` на `httpx`
(`requests.HTTPError` → `httpx.HTTPError`); проксі більше не задаються з коду — тільки `HTTP_PROXY` /
`HTTPS_PROXY`; `hf_transfer` і `HF_HUB_ENABLE_HF_TRANSFER` прибрані на користь `hf_xet`; додано
обов'язкову залежність `typer-slim` (CLI `hf` і `transformers`).

**Робочий приклад — аудитор міграції.** Один прохід регулярками, який працює без `transformers` і
годиться як pre-commit хук:

```python
import re

# Патерни взяті з MIGRATION_GUIDE_V5.md: кожен — місце, де v4-код тихо або голосно ламається.
V4_PATTERNS = {
    "torch_dtype=":            r"torch_dtype\s*=",
    "use_auth_token=":         r"use_auth_token\s*=",
    "load_in_4bit/8bit=":      r"load_in_(?:4|8)bit\s*=",
    "encode_plus(":            r"\.encode_plus\s*\(",
    "AutoModelWithLMHead":     r"\bAutoModelWithLMHead\b",
    "AutoModelForVision2Seq":  r"\bAutoModelForVision2Seq\b",
    "use_fast= (процесор)":    r"use_fast\s*=",
    "as_target_tokenizer":     r"as_target_tokenizer\s*\(",
    "special_tokens_map_ext":  r"special_tokens_map_extended|all_special_tokens_extended",
    "additional_special_tok":  r"\badditional_special_tokens\b",
    "TRANSFORMERS_CACHE":      r"TRANSFORMERS_CACHE|PYTORCH_TRANSFORMERS_CACHE",
    "transformers-cli":        r"transformers-cli",
    "generate через config":   r"\.config\.(?:do_sample|max_new_tokens|temperature)\b",
}

V4_CODE = '''
from transformers import AutoModelForCausalLM, AutoTokenizer, AutoModelWithLMHead

tok = AutoTokenizer.from_pretrained("meta-llama/Llama-3.2-1B", use_auth_token=TOKEN)
model = AutoModelForCausalLM.from_pretrained(
    "meta-llama/Llama-3.2-1B", torch_dtype="auto", load_in_4bit=True, device_map="auto"
)
ids = tok.encode_plus("привіт", return_tensors="pt")["input_ids"]
params = {"temperature": 0.7}
model.config.temperature = params["temperature"]   # v4-стиль
'''

findings = [(n, label, line.strip()) for n, line in enumerate(V4_CODE.splitlines(), 1)
            for label, pattern in V4_PATTERNS.items() if re.search(pattern, line)]
print(f"Знайдено місць для міграції: {len(findings)}")
for n, label, line in findings:
    print(f"  рядок {n:>2}  [{label}]  {line}")
```

Реальний вивід:

```text
Знайдено місць для міграції: 5
  рядок  1  [AutoModelWithLMHead]  from transformers import AutoModelForCausalLM, AutoTokenizer, AutoModelWithLMHead
  рядок  3  [use_auth_token=]  tok = AutoTokenizer.from_pretrained("meta-llama/Llama-3.2-1B", use_auth_token=TOKEN)
  рядок  5  [torch_dtype=]  "meta-llama/Llama-3.2-1B", torch_dtype="auto", load_in_4bit=True, device_map="auto"
  рядок  7  [encode_plus(]  ids = tok.encode_plus("привіт", return_tensors="pt")["input_ids"]
  рядок 10  [generate через config]  model.config.temperature = params["temperature"]   # v4-стиль
```

`load_in_4bit` у рядку 5 **не** позначено окремо: аудитор зупиняється на першому збігу в рядку. Це
спрощення прикладу — у продакшн-хуку збирайте всі збіги в рядку.

**Типові помилки**

- Мігрувати «зверху вниз»: спочатку import-и, потім логіку. Правильний порядок — спершу знайти місця
  зі зміненими типами повернення (крок 2), бо саме вони дають помилки через години після старту.
- Вважати, що `dtype="auto"` і `torch_dtype="auto"` поводяться ідентично в усіх шляхах. Сирці окремо
  поправляють цю історію: у `_BaseAutoModelClass.from_pretrained` значення `"auto"` виймається з kwargs
  перед створенням конфіга, а конкретний `dtype` потім **повторно інжектується** як явний kwarg, щоб
  модель поважала його понад збережений у конфізі.
- Забути про remote code: якщо модель тягне власний `modeling_*.py` з Hub, старі шляхи
  `transformers.tokenization_utils*` у ньому не існують.
- Оновлювати `transformers` і `huggingface_hub` окремо: v5 пінить `huggingface_hub>=1.0.0`.

**Альтернативи.** Якщо продукт не готовий до міграції, технічно можливо тримати два віртуальні
середовища (4.x для legacy-шляху, 5.x для нового) і розділити їх за сервісами. Це дешевше за «міграцію
в один день», але дорожче в довгій перспективі: усі нові моделі з'являються спершу у v5.

**Джерела**: [MIGRATION_GUIDE_V5.md](https://raw.githubusercontent.com/huggingface/transformers/main/MIGRATION_GUIDE_V5.md)

### 19.3 `pipeline` як швидкий старт і його обмеження

**Що це.** `pipeline` — високорівневий API інференсу: один рядок на завантаження моделі й
препроцесингу, один виклик на відповідь. У v5 це два класи: загальний `Pipeline` і безліч
задаче-специфічних (наприклад `TextGenerationPipeline`), які отримують через ідентифікатор задачі в
параметрі `task`.

**Навіщо це знати.** `pipeline` — найшвидший спосіб перевірити модель на своїх даних і найгірший
спосіб побудувати продакшн-сервіс. Документація прямо перелічує, коли батчинг **не** допоможе, а
метрик пропускної здатності ви не отримаєте з коробки. Розуміння межі між «швидкий старт» і
«продакшн» відрізняє одноразовий скрипт від сервісу.

**Як працює під капотом.** `Pipeline` — конвеєр із трьох стадій:

```python
# Схема з документації: як pipeline обробляє один вхід.
preprocessed = pipeline.preprocess(inputs)
model_outputs = pipeline.forward(preprocessed)
outputs = pipeline.postprocess(model_outputs)
```

Для випадків, коли один вхід вимагає кількох forward-проходів (довге аудіо, zero-shot класифікація,
question answering), існує `ChunkPipeline`: та сама робота, але з автоматичним чанкуванням, тож
`batch_size` можна оптимізувати незалежно від входів.

Розміщення на пристрої: без параметра `device` пайплайн сам бере перший доступний прискорювач (CUDA,
Apple Silicon MPS, XPU, ...) і лише за їх відсутності — CPU; `device="cpu"` примусово вибирає CPU,
`device=0` — перший CUDA-пристрій, `device="mps"` — Apple Silicon; `device_map="auto"` віддає розподіл
ваг Accelerate, який спершу використовує найшвидші пристрої, а далі CPU і диск.

#### Батчинг: коли він справді допомагає

Правила з документації (не евристики, а прямі рекомендації):

1. Єдиний надійний спосіб дізнатися — виміряти на своїй моделі, даних і залізі.
2. Не батчте, якщо ви обмежені латентністю (live-продукт) або працюєте на CPU.
3. Не батчте, якщо не знаєте `sequence_length` своїх даних; якщо довжина регулярна — батчте й
   збільшуйте її до появи OOM, заздалегідь навчившись обробляти OOM.

Батчинг вимкнений за замовчуванням і «не гарантовано» швидший: на швидкість впливають залізо, дані й
сама модель.

**Робочий приклад.** Мінімальний виклик із власним розміром батчу та обмеженням виходу:

```python
from transformers import pipeline

# device="cpu" — щоб приклад був передбачуваним на будь-якій машині.
generator = pipeline(task="text-generation", model="openai-community/gpt2", device="cpu", batch_size=2)

# return_full_text=False повертає лише згенеровану частину, без промпту.
# num_return_sequences > 1 передається в generate() — це задокументовано для TextGenerationPipeline.
out = generator(
    ["the secret to baking a good cake is", "a baguette is"],
    num_return_sequences=2,
    return_full_text=False,
    max_new_tokens=20,
)
for batch in out:
    for item in batch:
        print(repr(item["generated_text"])[:100], "...")
```

Потокова обробка великого датасету — через `KeyDataset` із `transformers.pipelines.pt_utils`: пайплайн
ітерується по датасету й сам формує батчі. Генератор теж працює як вхід, але з обмеженням із
документації: оскільки це ітеративна обробка, `num_workers > 1` використати не можна.

#### Що змінилося саме у v5

- Видалено `question-answering`, `Text2TextGenerationPipeline`, `SummarizationPipeline`,
  `TranslationPipeline`, `image-to-text`, `visual-question-answering`, `image-to-image`.
- `image-text-to-text` більше не приймає зображення окремим аргументом.
- Напівточність і квантизація передаються так: `dtype=torch.bfloat16` і
  `model_kwargs={"quantization_config": BitsAndBytesConfig(load_in_8bit=True)}`. Документація
  зауважує: входи всередині конвертуються в `torch.float16`, і це працює лише для PyTorch-бекенду.

**Типові помилки**

- Використовувати `pipeline` як сервер під навантаженням. Для цього у v5 є `transformers serve`
  (OpenAI-сумісний сервер) плюс безперервний батчинг і paged attention.
- Забути про `device`: без нього пайплайн сам бере перший доступний прискорювач; `device="cpu"` —
  єдиний спосіб примусово працювати на CPU.
- Чекати, що `batch_size` завжди прискорить: це не гарантовано, і на CPU рекомендація протилежна.
- Пробувати `pipeline("question-answering")` або `pipeline("summarization")` — цих задач більше немає.
- Передавати зображення окремим аргументом у `image-text-to-text`.

**Альтернативи.**

| Потреба | Що брати |
|---|---|
| Швидко перевірити модель на 10 прикладах | `pipeline` |
| Продакшн-сервер з OpenAI-сумісним API | `transformers serve`; або vLLM, SGLang, TensorRT LLM |
| Повний контроль над препроцесингом і кешем | `AutoTokenizer` + `AutoModelForCausalLM` + `model.generate` |
| Потокова обробка великого датасету | `pipeline` + `KeyDataset` + `batch_size` |
| Один вхід → кілька forward-проходів | `ChunkPipeline` |

**Джерела**: [Pipeline tutorial](https://raw.githubusercontent.com/huggingface/transformers/main/docs/source/en/pipeline_tutorial.md),
[Pipelines (main classes)](https://raw.githubusercontent.com/huggingface/transformers/main/docs/source/en/main_classes/pipelines.md),
[MIGRATION_GUIDE_V5.md](https://raw.githubusercontent.com/huggingface/transformers/main/MIGRATION_GUIDE_V5.md)

### 19.4 `generate`: greedy, beam, sampling, штрафи, стоп-умови

**Що це.** `generate` — метод `GenerationMixin`, який перетворює промпт у продовження, крок за кроком
вибираючи наступний токен. Стратегія вибору (decoding strategy) задається параметрами
`GenerationConfig`; сам метод приймає їх як keyword-аргументи.

**Навіщо це знати.** Стратегія декодування впливає на якість сильніше за більшість промпт-трюків.
Документація формулює це прямо: greedy працює для коротких виходів, де креативність не потрібна, але
«ламається на довгих послідовностях, бо починає повторюватися». Для чату це означає: залишити типову
стратегію — отримати модель, що зациклюється.

**Як працює під капотом.**

- **Greedy search** (типова стратегія) вибирає на кожному кроці найімовірніший токен. Якщо в
  `GenerationConfig` не сказано іншого, стратегія генерує **максимум 20 нових токенів** — це найчастіша
  причина обрізаних відповідей.
- **Multinomial sampling** обирає токен випадково з розподілу по всьому словнику, а не найімовірніший:
  кожен токен із ненульовою ймовірністю має шанс. Вмикається парою `do_sample=True` і `num_beams=1`,
  знижує повторюваність і дає різноманітніші виходи.
- **Beam search** тримає кілька послідовностей (променів) на кожному кроці й через певну кількість
  кроків вибирає послідовність із найвищою **сукупною** ймовірністю. Вмикається `num_beams > 1` (інакше
  це еквівалент greedy), найкраще підходить для задач, прив'язаних до входу: опис зображення,
  розпізнавання мовлення. Можна комбінувати з `do_sample=True`, але промені все одно жадібно відсікають
  малоймовірні послідовності між кроками.

#### Штрафи

| Параметр | Тип | Що робить |
|---|---|---|
| `repetition_penalty` | `float` | Ставте `> 1.0`, якщо модель часто повторюється; більше значення — більший штраф |
| `temperature` | `float` | Наскільки непередбачуваним буде наступний токен. `> 0.8` — креативні задачі, `< 0.4` — задачі, що вимагають «міркування». **Вимагає `do_sample=True`** |
| `top_k` | `int` | Обмежує вибірку (присутній у прикладі `GenerationConfig` в документації: `top_k=50`) |

#### Стоп-умови

| Механізм | Як задається |
|---|---|
| Довжина | `max_new_tokens` (рекомендовано задавати явно), `max_length` |
| Токен кінця | `eos_token_id` — токен або список токенів (`list[int]`), що зупиняють генерацію |
| Своя логіка | `stopping_criteria` — список об'єктів `StoppingCriteria` |
| Своя логіка над розподілом | `logits_processor` — список об'єктів `LogitsProcessor` |
| Повністю свій цикл | `custom_generate` |

#### Де живуть параметри

`model.generation_config` показує **лише значення, що відрізняються від типових**. У документації це
показано на `mistralai/Mistral-7B-v0.1`, де видно тільки `bos_token_id` і `eos_token_id`. Типове
декодування застосовується, якщо з моделлю не збережено конфігурацію.

**Робочий приклад.** Три стратегії на одному промпті та власна стоп-умова:

```python
from transformers import AutoModelForCausalLM, AutoTokenizer

model_id = "Qwen/Qwen2.5-0.5B-Instruct"
tokenizer = AutoTokenizer.from_pretrained(model_id)
model = AutoModelForCausalLM.from_pretrained(model_id, dtype="auto", device_map="auto")

inputs = tokenizer(["The quick brown"], return_tensors="pt").to(model.device)

# 1. Greedy (типово). Без max_new_tokens отримаєте максимум 20 нових токенів.
greedy = model.generate(**inputs, max_new_tokens=20)

# 2. Multinomial sampling: do_sample=True і num_beams=1
sampled = model.generate(**inputs, max_new_tokens=50, do_sample=True, num_beams=1, temperature=0.8)

# 3. Beam search: num_beams > 1; repetition_penalty > 1.0 проти повторів
beamed = model.generate(**inputs, max_new_tokens=50, num_beams=2, repetition_penalty=1.2,
                        eos_token_id=tokenizer.eos_token_id)

for name, out in (("greedy", greedy), ("sampling", sampled), ("beam", beamed)):
    print(f"{name:9} {tokenizer.batch_decode(out, skip_special_tokens=True)[0]!r}")
```

Власний критерій зупинки — це клас із `__call__(self, input_ids, scores, **kwargs) -> bool`, який
передається списком `StoppingCriteriaList([...])` у параметр `stopping_criteria`. Власна конфігурація
генерації зберігається у `generation_config.json` (приклад із документації):

```python
from transformers import GenerationConfig

generation_config = GenerationConfig(
    max_new_tokens=50, do_sample=True, top_k=50, eos_token_id=model.config.eos_token_id
)
generation_config.save_pretrained("my_account/my_model", push_to_hub=True)
```

Кілька конфігурацій в одній теці розрізняються параметром `config_file_name`; для перекладу
документація наводить `GenerationConfig(num_beams=4, early_stopping=True, decoder_start_token_id=0,
eos_token_id=..., pad_token=...)` і завантаження через
`GenerationConfig.from_pretrained("/tmp", config_file_name="translation_generation_config.json")`.

#### Свій цикл декодування: `custom_generate`

`custom_generate` приймає репозиторій або локальну теку з файлом `custom_generate/generate.py` (саме
така тека, не корінь репозиторію). Вимоги жорсткі: у файлі **мусить** бути метод `generate`, і його
перший аргумент **мусить** називатися `model`. Можна передати й **callable**, щоб перевикористати всю
підготовку входу з `generate` (розширення батчу, маски, logits-процесори, критерії зупинки) і замінити
лише цикл декодування:

```python
def custom_loop(model, input_ids, attention_mask, logits_processor, stopping_criteria, generation_config, **model_kwargs):
    while input_ids.shape[1] < stopping_criteria[0].max_length:
        logits = model(input_ids, attention_mask=attention_mask, **model_kwargs).logits
        next_token = torch.argmax(logits_processor(input_ids, logits[:, -1, :]), dim=-1)[:, None]
        input_ids = torch.cat((input_ids, next_token), dim=-1)
        attention_mask = torch.cat((attention_mask, torch.ones_like(next_token)), dim=-1)
    return input_ids


output = model.generate(**inputs, custom_generate=custom_loop, max_new_tokens=10)
```

Якщо у `custom_generate/requirements.txt` вказані недоступні залежності, ви отримаєте явний `ImportError`
із переліком пакетів і встановлених версій — це запроєктована поведінка, а не збій.

**Типові помилки**

- **Не задати `max_new_tokens`.** Типово 20 токенів; обрізана відповідь виглядає як «модель дурна».
- **`temperature` без `do_sample=True`.** Параметр нічого не робить, і жодної помилки не буде.
- **`padding_side="right"` для генерації.** LLM не тренували продовжувати з padding-токенів.
  Документація показує реальний наслідок: на батчі `["1, 2, 3", "A, B, C, D, E"]` з right-padding
  вихід першого прикладу — `'1, 2, 33333333333'`; з `padding_side="left"` — `'1, 2, 3, 4, 5, 6,'`.
- **Годувати чат-модель рядком.** Без шаблону модель відповідає, але не в тому форматі; з
  `apply_chat_template(..., add_generation_prompt=True)` відповідь структурована й відповідає
  системному промпту.
- **Читати або писати генераційні параметри через `model.config`.** У v5 це заборонений шлях.
- **Очікувати, що `input_ids` виходу — тільки нові токени.** Decoder-only моделі повертають промпт
  разом із продовженням; щоб відрізати, збережіть `input_length = inputs["input_ids"].shape[1]` і
  беріть `generated_ids[:, input_length:]`.

**Альтернативи.**

| Задача | Стратегія | Чому |
|---|---|---|
| Транскрипція, переклад, витяг | Greedy (`do_sample=False`) | Детерміновано, прив'язано до входу |
| Опис зображення, розпізнавання | Beam search (`num_beams > 1`) | Дивиться вперед, кращий сукупний скор |
| Чат, креативне письмо | Sampling (`do_sample=True`) | Менше повторів, різноманітність |
| Задачі, що потребують міркування | Sampling з низькою `temperature` (`< 0.4`) | Пряма рекомендація документації |
| Повторювані виходи | `repetition_penalty > 1.0` | Пряма рекомендація документації |
| Незвичайна логіка зупинки | `stopping_criteria` | Без переписування циклу |
| Повністю свій алгоритм декодування | `custom_generate` | Розшарити метод через Hub без нових залежностей |

**Джерела**: [Generation strategies](https://raw.githubusercontent.com/huggingface/transformers/main/docs/source/en/generation_strategies.md),
[Text generation (llm_tutorial)](https://raw.githubusercontent.com/huggingface/transformers/main/docs/source/en/llm_tutorial.md),
[Generation (main classes)](https://raw.githubusercontent.com/huggingface/transformers/main/docs/source/en/main_classes/text_generation.md)

### 19.5 Новий інтерфейс attention і вибір бекенду

**Що це.** `AttentionInterface` — централізований реєстр реалізацій уваги, який відокремлює реалізацію
уваги від реалізації моделі. Анонс v5 формулює це так: `eager` лишається в modeling-файлі, а решта —
FA1/2/3, FlexAttention, SDPA — переїхали в інтерфейс.

**Навіщо це знати.** Усі реалізації уваги виконують **одне й те саме обчислення**: кожен токен
порівнюється з кожним іншим. Різниця лише в тому, *як* це робиться. Базова реалізація погано
масштабується, бо матеріалізує повну матрицю уваги в пам'яті; оптимізовані переставляють математику,
щоб зменшити трафік пам'яті. Вибір бекенду — це різниця між «працює» і «працює швидко» на тій самій
моделі й тому самому залізі.

**Як працює під капотом.** `attn_implementation` приймається у `from_pretrained` і може задаватися
рядком або словником (для мультимодальних моделей — окремо на кожен бекбон). Реалізації в реєстрі
(таблиця з документації):

| Бекенд | Опис |
|---|---|
| `"flash_attention_3"` | Покращує FlashAttention-2: перекриває операції та щільніше фузить forward і backward |
| `"flash_attention_2"` | Розбиває обчислення на блоки й використовує швидку on-chip пам'ять |
| `"flex_attention"` | Каркас для власних шаблонів уваги (sparse, block-local, sliding window) без низькорівневих ядер |
| `"sdpa"` | Вбудована реалізація PyTorch (`torch.nn.functional.scaled_dot_product_attention`) |
| `"paged\|flash_attention_3"` | Paged-версія FlashAttention-3 |
| `"paged\|flash_attention_2"` | Paged-версія FlashAttention-2 |
| `"paged\|sdpa"` | Paged-версія SDPA |
| `"paged\|eager"` | Paged-версія eager |

Типове значення — `"sdpa"`. У сирцях v5 це видно прямо:

```text
# research/hf5src/modeling_utils.py, метод PreTrainedModel.get_correct_attn_implementation
applicable_attention = "sdpa" if requested_attention is None else requested_attention
```

Тобто `None` означає не «щось вирішить PyTorch», а буквально `"sdpa"`. Якщо SDPA недоступна,
бібліотека відкочується на `eager` — але лише тоді, коли ви не просили SDPA явно:

```text
# research/hf5src/modeling_utils.py, той самий метод
elif "sdpa" in applicable_attention:
    # Sdpa is the default, so we try it and fallback to eager otherwise when not possible
    try:
        self._sdpa_can_dispatch(is_init_check)
    except (ValueError, ImportError) as e:
        if requested_attention is not None and "sdpa" in requested_attention:
            raise e
        applicable_attention = "eager"
```

Якщо ви попросили `"sdpa"` **явно** — помилка не глушиться.

Скомпільовані ядра завантажуються з Hub під час виконання, що прибирає проблеми з несумісними версіями
PyTorch і CUDA; вони автоматично реєструються в `AttentionInterface`, тож окремо встановлювати пакет
FlashAttention не потрібно:

```python
model = AutoModelForCausalLM.from_pretrained(
    "meta-llama/Llama-3.2-1B", attn_implementation="kernels-community/flash-attn2"
)
```

У сирцях видно механіку відкату: якщо оригінальний FlashAttention не встановлений, але бібліотека
`kernels` доступна, підставляється сумісне ядро з Hub (`FLASH_ATTN_KERNEL_FALLBACK`), а для paged-режиму
префікс `paged|` додається заново. Окремо є «автокорекція»: якщо модель оголошує
`_compatible_flash_implementations`, а ви просите несумісний варіант, бібліотека попереджає й
перемикається на рекомендований моделлю.

Перемикання бекенду без перезавантаження ваг — `model.set_attn_implementation("sdpa")`. Це працює не
для всіх класів: `PreTrainedModel._can_set_attn_implementation()` перевіряє сирці модуля моделі й
повертає `False`, якщо в модулі є клас `*Attention*(nn.Module)`, який **не** використовує
`ALL_ATTENTION_FUNCTIONS.get_interface(`.

Для мультимодальних моделей бекенди задають словником; ключі мають збігатися з іменами суб-конфігів
(документація радить перевіряти це явно: `assert key in model.config.sub_configs`), а порожній ключ
задає значення глобально:

```python
from transformers import AutoModelForImageTextToText

# Різні бекенди на бекбон; порожній ключ "" — глобальне значення
model = AutoModelForImageTextToText.from_pretrained(
    "facebook/chameleon-7b",
    attn_implementation={"vision_config": "sdpa", "text_config": "flash_attention_2"},
)
model = AutoModelForImageTextToText.from_pretrained("facebook/chameleon-7b", attn_implementation={"": "eager"})
```

#### Власна функція уваги, маски, packing

Власну реалізацію реєструють двома викликами: `AttentionInterface.register("my_new_sdpa", моя_функція)`
і `AttentionMaskInterface.register("my_new_sdpa", sdpa_mask)`. **Ім'я маски мусить збігатися з ім'ям
функції уваги**: якщо його немає в реєстрі, Transformers **пропускає створення маски** і передає в шари
`attention_mask=None` — ваша функція тоді мусить сама обробляти causal, padding, packing і
sliding-window обмеження. Маски будують функції `create_*_mask` із `transformers.masking_utils`
(`create_causal_mask`, `create_bidirectional_mask`, `create_sliding_window_causal_mask`,
`create_chunked_causal_mask`, `create_bidirectional_sliding_window_mask`): кожна читає активний бекенд
із конфігу моделі, знаходить у `AttentionMaskInterface` форматер цього бекенду й повертає потрібний
формат. Застарілі хелпери `get_extended_attention_mask`,
`create_extended_attention_mask_for_decoder`, `invert_attention_mask` видають deprecation warning.

Padding-free (packing) склеює кілька прикладів в одну послідовність замість падінгу, і модель мусить
знати межі, щоб увага не змішувала токени різних прикладів. Рекомендований шлях — колатор
`DataCollatorWithFlattening(return_flash_attn_kwargs=True)`; для лінійної уваги й згорткових моделей
(Gated DeltaNet, Mamba-подібні) додають `return_seq_idx=True`. Визначення меж із `position_ids` — не
рекомендований шлях: під `torch.compile` воно дає розриви графа, а для GDN/лінійної уваги/згорток не
існує взагалі. Найнебезпечніше тут — **тиха деградація**: без boundary-kwargs ядра мовчки трактують
увесь батч як одну послідовність, без помилки чи попередження.

Paged attention (безперервний батчинг) обгортає дві версії ядра flash attention. **Varlen path**
(`flash_attn_varlen_func`) — для батчів зі змінною довжиною, рекомендований, коли багато запитів у
prefill; кеш він читає й пише вручну через `PagedAttentionCache.update`, що стає вузьким місцем на
довгих послідовностях. **Decode path** (`flash_attn_with_kvcache`) — для батчів, де в кожної
послідовності рівно один query-токен; ефективніший, але не вміє prefill, і працює з кешем через
`block_table` форми `(batch_size, max_blocks_per_seq)`, де `-1` означає невиділений блок.

**Робочий приклад.** Перевірка, який бекенд реально працює у вашому середовищі:

```python
from transformers import AutoModelForCausalLM

model_id = "meta-llama/Llama-3.2-1B"

# Явно просимо sdpa, щоб не залежати від наявності flash-attn
model = AutoModelForCausalLM.from_pretrained(model_id, attn_implementation="sdpa")

# Реальний бекенд видно у конфізі моделі
print("attn_implementation:", model.config._attn_implementation)

# Перемикання без перезавантаження ваг
model.set_attn_implementation("eager")
print("після set_attn_implementation:", model.config._attn_implementation)
```

**Типові помилки**

- Просити `attn_implementation="flash_attention_2"` без встановленого пакета й без `kernels`. Сирці
  дають зрозуміле повідомлення «You do not have `flash_attn` installed, using ... instead», але код,
  який розраховує на швидкість FA2, отримає іншу продуктивність.
- Зареєструвати власну функцію уваги й забути про `AttentionMaskInterface`: маска тихо стане `None`.
- Передати 4D float-маску в `flash_attention_2` або `flex_attention` — ці бекенди приймають власні формати.
- Перенести `1`/`0`-конвенцію у float-маску: це не «працює гірше», це «не маскує нічого».
- Використовувати `eager` як «безпечний типовий варіант»: типове значення — `"sdpa"`, і воно швидше;
  `eager` потрібен для сумісності зі старими моделями та для відлагодження.
- Для мультимодальної моделі задати словник із ключем, якого немає серед суб-конфігів. Документація
  радить перевіряти явно: `assert key in model.config.sub_configs`.

**Альтернативи.**

| Ситуація | Вибір |
|---|---|
| Типово, нічого не налаштовувати | `"sdpa"` |
| Максимальна швидкість на NVIDIA | `"flash_attention_2"` / `"flash_attention_3"`, за потреби через `kernels-community/*` |
| Власний шаблон уваги (sparse, sliding window) | `"flex_attention"` |
| Відлагодження, сумісність зі старими моделями | `"eager"` |
| Високий паралелізм запитів (сервер) | paged-варіанти (`"paged\|..."`) у режимі безперервного батчингу |
| Мультимодальна модель | різні бекенди на бекбон через словник |

**Джерела**: [Attention backends](https://raw.githubusercontent.com/huggingface/transformers/main/docs/source/en/attention_interface.md),
[Padding-free training](https://raw.githubusercontent.com/huggingface/transformers/main/docs/source/en/padding_free.md),
[Paged attention](https://raw.githubusercontent.com/huggingface/transformers/main/docs/source/en/paged_attention.md),
[Transformers v5 — анонс](https://huggingface.co/blog/transformers-v5)

### 19.6 Auto-класи: `AutoModelForCausalLM`, `AutoTokenizer` і як вони резолвляться

**Що це.** Auto-класи — точка входу бібліотеки. Ви даєте рядок `"Qwen/Qwen3-8B"`, а клас сам знаходить
потрібну конфігурацію, модель і токенізатор. Формулювання документації просте: архітектуру можна
вгадати з імені або шляху моделі, і Auto-класи роблять це за вас.

**Навіщо це знати.** Через Auto-класи проходять усі помилки завантаження: «Unrecognized configuration
class», «model type X but Transformers does not recognize this architecture», `trust_remote_code`. Якщо
ви розумієте резолвінг, ви за секунди відрізняєте «модель занадто нова для вашої версії бібліотеки»
від «ви викликали не той Auto-клас» і від «у репозиторії підмінили клас через `auto_map`».

**Як працює під капотом.** Розберемо резолвінг по реальних сирцях із `research/hf5src/`.

#### Крок 1. Таблиця відповідностей: `model_type` → ім'я класу моделі

У `models_auto_modeling_auto.py` лежить 54 словники `*_NAMES` — це і є «таблиця істинності»
бібліотеки. Розберіть файл через `ast`:

```python
import ast
import pathlib

SRC = pathlib.Path("research/hf5src/models_auto_modeling_auto.py")
source = SRC.read_text(encoding="utf-8")
tree = ast.parse(source)


def literal_pairs(node):
    """Пари (ім'я, вузол значення) з OrderedDict([...]); значення може бути й кортежем."""
    if not (isinstance(node, ast.Call) and node.args and isinstance(node.args[0], ast.List)):
        return {}, 0
    elts = [el for el in node.args[0].elts
            if isinstance(el, ast.Tuple) and len(el.elts) == 2 and isinstance(el.elts[0], ast.Constant)]
    return {el.elts[0].value: el.elts[1] for el in elts}, len(elts)


mappings, records = {}, 0
for n in tree.body:
    if not (isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Name)
            and n.targets[0].id.endswith("_NAMES")):
        continue
    pairs, count = literal_pairs(n.value)
    if pairs:
        mappings[n.targets[0].id] = pairs
        records += count

clm = mappings["MODEL_FOR_CAUSAL_LM_MAPPING_NAMES"]
print(f"Файл: {len(source.splitlines())} рядків; словників *_NAMES: {len(mappings)}; "
      f"записів: {records} (унікальних ключів: {sum(len(v) for v in mappings.values())})")
print(f"MODEL_FOR_CAUSAL_LM_MAPPING_NAMES: {len(clm)} записів")
for key in ("bert", "llama", "mistral", "qwen3", "deepseek_v4"):
    print(f"  {key:12} -> {ast.unparse(clm[key])}")
```

Реальний вивід:

```text
Файл: 2681 рядків; словників *_NAMES: 54; записів: 1709 (унікальних ключів: 1708)
MODEL_FOR_CAUSAL_LM_MAPPING_NAMES: 178 записів
  bert         -> 'BertLMHeadModel'
  llama        -> 'LlamaForCausalLM'
  mistral      -> 'MistralForCausalLM'
  qwen3        -> 'Qwen3ForCausalLM'
  deepseek_v4  -> 'DeepseekV4ForCausalLM'
```

Ті самі дані дають кілька неочевидних фактів: записів більше, ніж унікальних ключів (1709 проти 1708),
бо в `MODEL_MAPPING_NAMES` (базові моделі без голови) ключ `sam3_tracker` повторюється — **553 записи,
552 унікальні** (при побудові `OrderedDict` другий запис перетирає перший). Чотири записи мають
значенням **кортеж** імен, а не рядок (`funnel` → `("FunnelModel", "FunnelBaseModel")` та три записи в
`MODEL_FOR_IMAGE_CLASSIFICATION_MAPPING_NAMES`) — саме для них працює вибір за `architectures` (крок 3).
А `MODEL_FOR_MULTIMODAL_LM_MAPPING_NAMES` починається зі зірочкового розпакування
`*list(MODEL_FOR_IMAGE_TEXT_TO_TEXT_MAPPING_NAMES.items())`, тобто **перевикористовує** відповідності
`image-text-to-text` — приклад того, як у v5 прибирають дублювання таблиць.

#### Крок 2. Зв'язок конфігурації з моделлю: `_LazyAutoMapping`

Клас моделі для задачі оголошується двома рядками:

```python
# research/hf5src/models_auto_modeling_auto.py
MODEL_FOR_CAUSAL_LM_MAPPING = _LazyAutoMapping(CONFIG_MAPPING_NAMES, MODEL_FOR_CAUSAL_LM_MAPPING_NAMES)


class AutoModelForCausalLM(_BaseAutoModelClass):
    _model_mapping = MODEL_FOR_CAUSAL_LM_MAPPING
```

`_LazyAutoMapping` — це `OrderedDict`, який **ліниво імпортує** класи. Він будує зворотну мапу «ім'я
класу конфігурації → `model_type`» (`self._reverse_config_mapping = {v: k for k, v in
config_mapping.items()}`), а при зверненні `mapping[SomeConfigClass]` виконує:

```python
# research/hf5src/models_auto_auto_factory.py, __getitem__
def __getitem__(self, key):
    if key in self._extra_content:
        return self._extra_content[key]
    model_type = self._reverse_config_mapping[key.__name__]
    if model_type in self._model_mapping:
        model_name = self._model_mapping[model_type]
        return self._load_attr_from_module(model_type, model_name)

    # Maybe there was several model types associated with this config.
    model_types = [k for k, v in self._config_mapping.items() if v == key.__name__]
    for mtype in model_types:
        if mtype in self._model_mapping:
            model_name = self._model_mapping[mtype]
            return self._load_attr_from_module(mtype, model_name)
    raise KeyError(key)
```

Ключове тут — три речі: пошук іде **не за `model_type`**, а за **іменем класу конфігурації** (тому
резолвінг залежить від `CONFIG_MAPPING_NAMES`: якщо ваш `model_type` не має відповідного класу
конфігурації, до таблиці моделей справа не дійде); є два проходи — точний збіг за зворотною мапою, а
потім пошук «усіх `model_type`, чий клас конфігурації збігається» (коли один клас конфігурації
обслуговує кілька `model_type`); `self._extra_content` перевіряється **першим**, тож усе, додане через
`register`, має пріоритет.

Імпорт класу робить `_load_attr_from_module`, який перетворює `model_type` на ім'я модуля через
`model_type_to_module_name` (замінює дефіси на підкреслення й застосовує спеціальну таблицю
`SPECIAL_MODEL_TYPE_TO_MODULE_NAME`) і робить
`importlib.import_module(f".{module_name}", "transformers.models")`. Реальні результати перетворення:

```text
audio-spectrogram-transformer    -> audio_spectrogram_transformer
deepseek_v4                      -> deepseek_v4
qwen3                            -> qwen3
gpt-sw3                          -> gpt_sw3
transfo-xl                       -> transfo_xl
```

`getattribute_from_module` має окремий механізм для випадку, коли імені немає в модулі моделі: він
шукає його у **верхньорівневому** `transformers` (деякі записи таблиць посилаються на клас іншої моделі).

#### Крок 3. Вибір класу, коли значення — кортеж

```python
# research/hf5src/models_auto_auto_factory.py
def _get_model_class(config, model_mapping):
    supported_models = model_mapping[type(config)]
    if not isinstance(supported_models, (list, tuple)):
        return supported_models

    name_to_model = {model.__name__: model for model in supported_models}
    architectures = getattr(config, "architectures", [])
    for arch in architectures:
        if arch in name_to_model:
            return name_to_model[arch]

    # If not architecture is set in the config or match the supported models, the first element of the tuple is the
    # defaults.
    return supported_models[0]
```

Логіка: у конфізі є поле `architectures` (список імен класів). Якщо воно збігається з одним із класів у
кортежі — береться він. Якщо ні (або поля немає) — береться **перший елемент кортежу**. Тобто порядок
у кортежі має сенс: це «типовий» варіант.

#### Крок 4. `from_pretrained`: повний маршрут

`_BaseAutoModelClass.from_pretrained` у v5 виконує таку роботу (усе з реального коду):

| # | Що робить |
|---|---|
| 1 | Витягує `config` з kwargs, ставить `kwargs["_from_auto"] = True`, розділяє hub-параметри (`cache_dir`, `force_download`, `local_files_only`, `proxies`, `revision`, `subfolder`, `token`); якщо `_commit_hash` не заданий — окремим викликом `cached_file(...)` по `config.json` отримує commit hash **якнайраніше** |
| 2 | Якщо доступний PEFT — шукає `find_adapter_config_file(...)`; знайшовши адаптер, бере з нього `base_model_name_or_path` і перемикається на базову модель (окрім випадку, коли локальний шлях уже містить повну модель із вбудованим адаптером) |
| 3 | Якщо конфіг не передано: виймає `dtype == "auto"` і `torch_dtype == "auto"` з kwargs (вони безглузді для конфіга), не перезаписує наявний `quantization_config`, викликає `AutoConfig.from_pretrained(..., return_unused_kwargs=True)`, а потім **повторно інжектує** конкретні `dtype`, `torch_dtype` і `quantization_config` як явні kwarg — щоб модель поважала їх понад значення з конфіга (виправлення #46459) |
| 4 | Обчислює три прапорці: `has_remote_code` (є `auto_map` і в ньому є ім'я цього Auto-класу), `has_local_code` (клас конфігурації присутній у `_model_mapping`), `explicit_local_code` (`has_local_code` і клас **не** з пакета `transformers`), і викликає `resolve_trust_remote_code(...)` |
| 5 | Якщо є remote code, увімкнений `trust_remote_code` і немає явного локального коду — динамічно імпортує клас із Hub через `get_class_from_dynamic_module`, реєструє його (`cls.register(config.__class__, model_class, exist_ok=True)`), викликає `register_for_auto_class`, додає `GenerationMixin` за потреби й делегує завантаження йому |
| 6 | Якщо є локальний код — бере клас через `_get_model_class` і, якщо `config_class` вибраної моделі дорівнює `config.sub_configs["text_config"]`, підміняє конфіг на текстову частину (`config = config.get_text_config()`) і переносить батьківський `quantization_config` (якщо він не `None`) у текстовий суб-конфіг |
| 7 | Якщо ні того, ні того — `ValueError` з переліком допустимих класів конфігурації |

Текст тієї помилки:

```text
Unrecognized configuration class <class> for this kind of AutoModel: AutoModelForCausalLM.
Model type should be one of <перелік класів конфігурації>.
```

Окремо про `trust_remote_code`: у `_LazyAutoMapping.register` є важлива умова — якщо
`getattr(key, "__module__", "").startswith("transformers.")`, реєстрація **пропускається**. Тобто спроба
remote code зареєструвати власний клас під вбудований клас конфігурації ігнорується — саме для того,
щоб `trust_remote_code=False` продовжував давати нативну модель.

`add_generation_mixin_to_remote_model` — окремий механізм сумісності: якщо динамічно завантажений клас
не успадковує `GenerationMixin` напряму, але має власні `generate` або `prepare_inputs_for_generation`,
бібліотека створює клас `type(name, (model_class, GenerationMixin), ...)`.

#### Крок 5. Резолвінг на живому коді (без встановленого `transformers`)

Найкорисніша вправа — виконати **справжній** код резолвінгу. Нижче функція й клас витягуються з
`models_auto_auto_factory.py` через `ast` і виконуються в ізольованому просторі. Єдина підміна —
`_load_attr_from_module` повертає рядок із таблиці замість імпорту модуля (пакета `transformers` у
середовищі немає). `CONFIG_MAPPING_NAMES` теж стенд-ін: реальна таблиця лежить у
`transformers/models/auto/auto_mappings.py`, якого немає в `research/`.

```python
import ast
import importlib
import pathlib
from collections import OrderedDict
from typing import Any, Iterator, TypeVar

tree = ast.parse(pathlib.Path("research/hf5src/models_auto_auto_factory.py").read_text(encoding="utf-8"))

# Витягуємо РЕАЛЬНІ _get_model_class і _LazyAutoMapping
wanted = {"_get_model_class", "_LazyAutoMapping"}
nodes = [n for n in tree.body
         if (isinstance(n, ast.FunctionDef) and n.name in wanted)
         or (isinstance(n, ast.ClassDef) and n.name in wanted)]
module = ast.Module(body=nodes, type_ignores=[])
ast.fix_missing_locations(module)


class PreTrainedConfig:      # заглушка лише для анотацій
    ...


namespace = {"OrderedDict": OrderedDict, "PreTrainedConfig": PreTrainedConfig, "Iterator": Iterator,
             "Any": Any, "TypeVar": TypeVar, "_T": TypeVar("_T"),
             "_LazyAutoMappingValue": tuple, "importlib": importlib}
exec(compile(module, "auto_factory_extract", "exec"), namespace)
_get_model_class = namespace["_get_model_class"]
LazyAutoMapping = namespace["_LazyAutoMapping"]


class Names(dict):
    """Таблиця, у яку _LazyAutoMapping пише власний зворотний покажчик."""
    _model_mapping = None


class StrMapping(LazyAutoMapping):
    """Підміняємо ЛИШЕ імпорт модуля: замість класу повертаємо його ім'я з таблиці."""

    def _load_attr_from_module(self, model_type, attr):
        return attr


CONFIG_MAPPING_NAMES = Names({"qwen3": "Qwen3Config", "deepseek_v4": "DeepseekV4Config", "funnel": "FunnelConfig"})
mapping = StrMapping(
    CONFIG_MAPPING_NAMES, Names({"qwen3": "Qwen3ForCausalLM", "deepseek_v4": "DeepseekV4ForCausalLM"})
)

print("Qwen3Config      ->", mapping[type("Qwen3Config", (), {})])
print("DeepseekV4Config ->", mapping[type("DeepseekV4Config", (), {})])
try:
    mapping[type("LlamaConfig", (), {})]
except KeyError as exc:
    print("LlamaConfig      -> KeyError:", exc)


# Вибір із кортежу за полем architectures — той самий реальний _get_model_class
class FunnelModel: pass
class FunnelBaseModel: pass


tuple_mapping = StrMapping(CONFIG_MAPPING_NAMES, Names({"funnel": (FunnelModel, FunnelBaseModel)}))
for archs in (["FunnelBaseModel"], ["Nonexistent"], []):
    cfg = type("FunnelConfig", (), {})()
    cfg.architectures = archs
    print(f"architectures={str(archs):20} -> {_get_model_class(cfg, tuple_mapping).__name__}")
```

Реальний вивід:

```text
Qwen3Config      -> Qwen3ForCausalLM
DeepseekV4Config -> DeepseekV4ForCausalLM
LlamaConfig      -> KeyError: 'LlamaConfig'
architectures=['FunnelBaseModel']  -> FunnelBaseModel
architectures=['Nonexistent']      -> FunnelModel
architectures=[]                   -> FunnelModel
```

Це підтверджує три речі, які видно і в коді: резолвінг іде за іменем класу конфігурації, `KeyError`
виникає ще до будь-якої роботи з моделями, а `architectures` впливає на вибір лише тоді, коли значення
в таблиці — кортеж.

#### Реєстрація власних класів і `AutoProcessor`

Документація дає мінімальний рецепт: `AutoConfig.register("new-model", NewModelConfig)` і
`AutoModel.register(NewModelConfig, NewModel)`. Два запобіжники з сирців: `AutoConfig.register`
перевіряє, що `config.model_type == model_type`; `_BaseAutoModelClass.register` перевіряє, що
`model_class.config_class.__name__ == config_class.__name__` (інакше `ValueError` з повідомленням «Fix
one of those so they match!»). «Зареєструвати щось» без узгодження трьох імен (`model_type`, клас
конфігурації, `config_class` моделі) не вийде.

#### `AutoTokenizer`: інший маршрут

`AutoTokenizer` у v5 резолвиться не так, як `AutoModelForCausalLM`. Реальний код починається з
показового рядка — `use_fast` **викидається** з kwargs:

```python
# research/hf5src/models_auto_tokenization_auto.py, AutoTokenizer.from_pretrained
# V5: Always use fast tokenizers, ignore use_fast parameter
_ = kwargs.pop("use_fast", None)
```

Далі порядок такий: якщо передано `tokenizer_type` — береться клас із `TOKENIZER_MAPPING_NAMES` за цим
ключем; якщо передано `gguf_file` — конфіг будується з метаданих GGUF; інакше викликається
`AutoConfig.from_pretrained(...)`, а при `ValueError` або `OSError` — фолбек на
`PreTrainedConfig.from_pretrained(...)`. Потім читається `tokenizer_config.json` і з нього
`tokenizer_class`, а також `auto_map` (`AutoTokenizer`; підтримується і застарілий формат списку).
Якщо `_name_or_path` конфіга збігається з одним із дев'яти патернів `MODEL_IDS_TO_TOKENIZERS_BACKEND`
(`deepseek-ai/deepseek-r1-distill-llama-*`, `deepseek-ai/deepseek-coder-*`, `allenai/dolma2-tokenizer`,
`google/umt5-small`, `naver-clova-ix/donut-*`, `salesforce/blip2-opt-*`,
`salesforce/blip2-flan-t5-*`, `salesforce/instructblip-flan-t5-*`, `stepfun-ai/step-3.7-*`) —
повертається `TokenizersBackend`.

Якщо `tokenizer_config.json` заявляє клас, що не збігається з класом, зареєстрованим у
`TOKENIZER_MAPPING_NAMES` для цього `model_type`, — перевіряється список
`MODELS_WITH_INCORRECT_HUB_TOKENIZER_CLASS` (**46 `model_type`**, серед них `deepseek_v4`, `qwen2`,
`phi3`, `llava`, `modernbert`, `minimax_m2`, `chameleon`): для них береться зареєстрований клас, а не
той, що в репозиторії. Складання класу за іменем виконує `tokenizer_class_from_name`, і там теж є шар
сумісності: `BloomTokenizer` і `BloomTokenizerFast` повертають `TokenizersBackend`, а якщо клас не
знайдено й ім'я закінчується на `Fast` — робиться повторна спроба **без** суфікса (для токенізаторів,
збережених до v5).

Числа з `TOKENIZER_MAPPING_NAMES` (витягнуті тим самим способом через `ast`): **264 ключі**, з яких
найчастіші класи — `TokenizersBackend` (34 записи), `BertTokenizer` (25), `Qwen2Tokenizer` (21),
`GPT2Tokenizer` (14), `CLIPTokenizer` (11). Точкові приклади: `bert` → `BertTokenizer`, `qwen3` →
`Qwen2Tokenizer`, `qwen4_exp` → `Qwen3_5Tokenizer`. Для `deepseek_v4` у літералі таблиці значення немає
(`None`), бо цей `model_type` додає вже згаданий цикл із `MODELS_WITH_INCORRECT_HUB_TOKENIZER_CLASS`.

Два висновки: `TokenizersBackend` — найчастіший клас, що є прямим наслідком рішення v5 «відмовитися
від поділу fast/slow і зосередитися на бекенді `tokenizers`»; і **`llama` у таблиці немає** — є лише
`code_llama`, тож для моделей родини Llama клас вибирається не цим шляхом, а через
`tokenizer_config.json` / `tokenizer.json` (саме тому в коді є шар сумісності з іменами `*Fast`).

`AutoProcessor` збирається так само, але зі своєї таблиці з `auto_mappings`:
`PROCESSOR_MAPPING = _LazyAutoMapping(CONFIG_MAPPING_NAMES, PROCESSOR_MAPPING_NAMES)`; окрім неї, у
файлі є локальний словник `MISSING_PROCESSOR_MAPPING_NAMES` (наприклад `("aimv2", "CLIPProcessor")`) для
процесорів, яких ще немає в загальній таблиці.

**Типові помилки**

- Використати `AutoModel` там, де потрібна генерація: `AutoModel` — базова модель без голови, для
  `generate` потрібен `AutoModelForCausalLM` (або відповідний клас задачі).
- Отримати `Unrecognized configuration class` і шукати проблему в моделі. У більшості випадків це
  означає, що ваш `model_type` відсутній у `CONFIG_MAPPING_NAMES`, тобто ваша версія бібліотеки
  старіша за модель; повідомлення в сирцях прямо радить `pip install --upgrade transformers` або
  встановлення з git.
- Покладатися на `model.config.architectures` як на гарантію: воно впливає на вибір класу **лише** для
  записів-кортежів.
- Вважати, що `trust_remote_code=True` завжди перемагає. У `from_pretrained` є умова
  `not explicit_local_code`, а в `_LazyAutoMapping.register` реєстрація під вбудований клас конфігурації
  ігнорується.
- Вважати `use_fast` робочим аргументом `AutoTokenizer` (у v5 він викидається без попередження) або
  довіряти `tokenizer_class` із `tokenizer_config.json`: для 46 `model_type` бібліотека свідомо ігнорує
  це поле.

**Альтернативи.**

| Задача | Інструмент |
|---|---|
| Завантажити модель за іменем із Hub | `AutoModelForCausalLM.from_pretrained` + `AutoTokenizer.from_pretrained` |
| Завантажити свій клас | `AutoConfig.register` + `AutoModel.register` (з узгодженням `model_type` і `config_class`) |
| Модель із власним кодом на Hub | `trust_remote_code=True` (тільки для перевіреного коду) |
| Точно знати, який клас буде створено | `AutoConfig.from_pretrained(...)` → `config.model_type` → пошук у таблиці |
| Обійти auto-клас повністю | Прямий імпорт `from transformers import LlamaForCausalLM` + `AutoConfig` |
| Локальний чекпойнт без Hub | `local_files_only=True` або шлях до теки |

**Джерела**: [Auto classes (model_doc/auto)](https://raw.githubusercontent.com/huggingface/transformers/main/docs/source/en/model_doc/auto.md),
реальні сирці `research/hf5src/`: `models_auto_auto_factory.py`, `models_auto_modeling_auto.py`,
`models_auto_configuration_auto.py`, `models_auto_tokenization_auto.py`, `models_auto_processing_auto.py`

### 19.7 Пристрій, dtype і пам'ять

**Що це.** Три параметри `from_pretrained`, які визначають, чи взагалі завантажиться модель: `dtype`
(скільки бітів на параметр), `device_map` (куди лягають ваги) і пов'язані з ними `max_memory`,
`offload_folder`, `offload_buffers`.

**Навіщо це знати.** Це місце, де помилка коштує найдорожче: неправильний `dtype` — це або OOM, або
тихе падіння якості; неправильний `device_map` — або «модель не влізла», або несподівано повільна
робота через офлоад. І саме тут найбільше застарілих звичок із v4.

**Як працює під капотом.** Документація `from_pretrained` описує `dtype` так: типове значення —
`"auto"`. Явний `torch.dtype` вантажить модель у цьому типі, ігноруючи `config.dtype`; якщо не задати
нічого, модель завантажиться в `torch.float` (fp32). Значення `"auto"` спершу бере `dtype` або
`torch_dtype` із `config.json`, а якщо запису немає — `dtype` першої ваги з плаваючою точкою в
чекпойнті: це тип, у якому модель **зберегли**, і він не є індикатором того, у якому типі її тренували.
Третій варіант — рядок із валідною назвою `torch.dtype` (`"float32"`, `"float16"`). Застарілий
`torch_dtype` ще приймається, але з попередженням «`torch_dtype` is deprecated! Use `dtype` instead!».

Арифметика пам'яті — це множення, а не вимір:

| dtype | Байтів на параметр | 7 млрд параметрів | 70 млрд параметрів |
|---|---|---|---|
| fp32 | 4 | ~26.08 ГБ | ~260.77 ГБ |
| fp16 / bf16 | 2 | ~13.04 ГБ | ~130.38 ГБ |
| int8 / fp8 | 1 | ~6.52 ГБ | ~65.19 ГБ |
| 4-бітна квантизація | ~0.5 | ~3.26 ГБ | ~32.59 ГБ |

Це **лише ваги**. KV-кеш, активації, проміжні тензори й фрагментація додаються зверху, тому реальна
потреба завжди більша. Саме тому в документації для завантаження LLM типово стоять разом
`device_map="auto"` і `quantization_config`.

`device_map` приймає: рядок із назвою пристрою (`"cpu"`, `"cuda:1"`, `"mps"`) або ціле (`0` — уся
модель на GPU 0) — тоді вся модель іде на цей пристрій; словник `str → int/str/torch.device` — кожен
підмодуль на свій пристрій (уточнювати до рівня параметра не потрібно); `"auto"` — Accelerate сам
обчислює оптимальну мапу; значення `"disk"` у словнику — офлоад на диск, для якого потрібен
`offload_folder` (і за потреби `offload_buffers`).

Решта параметрів тієї самої довідки: `max_memory` (словник «пристрій → максимум пам'яті»); окремий —
`distributed_config` для нативного розподіленого завантаження (TP через `tp_size`/`tp_plan`, FSDP2 через
`fsdp_size`), який потребує `torchrun` і **взаємовиключний із `device_map`**; `disable_mmap` (вимикає
memory mapping safetensors; типово авто-`True` на FUSE-ФС `hf-mount`, де mmap і паралельні page-faults
можуть завести в дедлок); `weights_only` (типово `True` — unpickler обмежений тензорами, примітивами й
типами з `torch.serialization.add_safe_globals()`); `fusion_config` (ф'юзинг перед інстанціюванням:
документація застерігає, що це оптимізація інференсу, яка **може трохи змінити вихід**); `key_mapping`
(перейменування ваг, якщо чекпойнт сумісний за архітектурою, але назви ключів інші). Окремий шар —
`local_torch_dtype`: контекстний менеджер, який на час ініціалізації моделі підмінює типовий dtype
PyTorch і повертає попередній при виході.

**Робочий приклад.** Перевірка пристроїв і оцінка пам'яті перед завантаженням — усе без `transformers`:

```python
import torch

print("torch:", torch.__version__, "| CUDA:", torch.cuda.is_available())
if torch.cuda.is_available():
    print("пристроїв:", torch.cuda.device_count(), "| пам'ять 0-го:",
          torch.cuda.get_device_properties(0).total_memory / 1024 ** 3, "ГБ")

BYTES_PER_PARAM = {"fp32": 4.0, "fp16/bf16": 2.0, "int8/fp8": 1.0, "4-bit": 0.5}


def weights_gb(num_params: int, dtype_name: str) -> float:
    """Скільки гігабайт займуть ЛИШЕ ваги моделі (без KV-кешу й активацій)."""
    return num_params * BYTES_PER_PARAM[dtype_name] / 1024 ** 3


for name in BYTES_PER_PARAM:
    print(f"{name:10} 7B -> {weights_gb(7_000_000_000, name):7.2f} ГБ | "
          f"70B -> {weights_gb(70_000_000_000, name):7.2f} ГБ")
```

Реальний вивід (частина про пам'ять — та сама, що в таблиці вище):

```text
fp32       7B ->   26.08 ГБ | 70B ->  260.77 ГБ
fp16/bf16  7B ->   13.04 ГБ | 70B ->  130.38 ГБ
int8/fp8   7B ->    6.52 ГБ | 70B ->   65.19 ГБ
4-bit      7B ->    3.26 ГБ | 70B ->   32.59 ГБ
```

Документація щодо заліза додає практичні деталі: не використовуйте «pigtail»-кабелі для двох
PCIe 8-pin роз'ємів (інакше GPU не дасть повної продуктивності); тримайте температуру в межах
70–75 °C, вище 84–90 °C GPU зазвичай починає тротлити; перевіряйте топологію з'єднань командою
`nvidia-smi topo -m` (код `NV2` — два NVLink, `PHB` — PCIe-міст).

**Типові помилки**

- **Завантажити у fp32 «щоб було точніше».** Для інференсу це вдвічі більше пам'яті з мінімальним
  виграшем: документація пайплайнів прямо каже, що втрата продуктивності незначна для більшості
  моделей, особливо великих.
- **Використовувати `load_in_4bit` / `load_in_8bit`.** У v5 видалені; єдиний шлях — `quantization_config`.
- **Комбінувати `device_map` і `distributed_config`** — документація називає їх взаємовиключними; і не
  задавайте `device_map="auto"` під `torchrun`: сирці попереджають, що разом із `WORLD_SIZE > 1` це
  «може призвести до неочікуваної поведінки».
- **Очікувати, що `dtype="auto"` дасть тип тренування.** Це тип, у якому чекпойнт **збережено**.
- **Забути `offload_folder`, коли в `device_map` є `"disk"`**, і **змішувати `torch.float16` із
  FlashAttention на vision-бекбонах**: деякі vision-бекбони краще працюють у fp32, а FlashAttention
  fp32 не підтримує.
- **Вважати, що обчислені гігабайти — це вимога до пам'яті.** Множення не враховує KV-кеш, активації,
  проміжні буфери, фрагментацію й копії при офлоаді.

**Альтернативи.**

| Обмеження | Рішення |
|---|---|
| Модель не влізає у VRAM | `quantization_config` (4-біт) + `device_map="auto"` |
| Не влізає навіть у RAM | Офлоад на диск: `"disk"` у `device_map` + `offload_folder` |
| Потрібна максимальна точність | `dtype=torch.float32` (свідомо платите пам'яттю) |
| Вузьке місце — швидкість, а не пам'ять | `dtype=torch.bfloat16` + оптимізований бекенд уваги (19.5) |
| Кілька GPU | `device_map="auto"` + `max_memory`, або `distributed_config` із `torchrun` |
| Машина без GPU | `device_map="cpu"`: повільніше, але працює; для невеликих моделей достатньо |

**Джерела**: `research/hf5src/modeling_utils.py` (`from_pretrained`, `ModuleUtilsMixin.device`,
`ModuleUtilsMixin.dtype`, `num_parameters`, `local_torch_dtype`),
[Text generation (llm_tutorial)](https://raw.githubusercontent.com/huggingface/transformers/main/docs/source/en/llm_tutorial.md),
[MIGRATION_GUIDE_V5.md](https://raw.githubusercontent.com/huggingface/transformers/main/MIGRATION_GUIDE_V5.md),
[Building a GPU workstation](https://raw.githubusercontent.com/huggingface/transformers/main/docs/source/en/perf_hardware.md)

**Джерела**

- [MIGRATION_GUIDE_V5.md](https://raw.githubusercontent.com/huggingface/transformers/main/MIGRATION_GUIDE_V5.md) — головне джерело для 19.1 і 19.2
- [Transformers v5: Simple model definitions powering the AI ecosystem](https://huggingface.co/blog/transformers-v5) — анонс v5, `AttentionInterface`, `transformers serve`, безперервний батчинг і paged attention
- [Pipeline tutorial](https://raw.githubusercontent.com/huggingface/transformers/main/docs/source/en/pipeline_tutorial.md) і [Pipelines (main classes)](https://raw.githubusercontent.com/huggingface/transformers/main/docs/source/en/main_classes/pipelines.md) — `Pipeline`, пристрої, батчинг, перелік задач і класів
- [Generation strategies](https://raw.githubusercontent.com/huggingface/transformers/main/docs/source/en/generation_strategies.md) і [Text generation (llm_tutorial)](https://raw.githubusercontent.com/huggingface/transformers/main/docs/source/en/llm_tutorial.md) — стратегії декодування, таблиця параметрів, пастки padding і формату промпту
- [Generation (main classes)](https://raw.githubusercontent.com/huggingface/transformers/main/docs/source/en/main_classes/text_generation.md) — `GenerationConfig`, `GenerationMixin`, `ContinuousMixin`, `ContinuousBatchingManager`
- [Attention backends](https://raw.githubusercontent.com/huggingface/transformers/main/docs/source/en/attention_interface.md), [Padding-free training](https://raw.githubusercontent.com/huggingface/transformers/main/docs/source/en/padding_free.md), [Paged attention](https://raw.githubusercontent.com/huggingface/transformers/main/docs/source/en/paged_attention.md) — реєстр бекендів, `AttentionMaskInterface`, packing, `block_table`
- [Building a GPU workstation](https://raw.githubusercontent.com/huggingface/transformers/main/docs/source/en/perf_hardware.md) і [Auto classes (model_doc/auto)](https://raw.githubusercontent.com/huggingface/transformers/main/docs/source/en/model_doc/auto.md) — залізо й перелік Auto-класів
- Реальні сирці Transformers v5 у репозиторії: `research/hf5src/modeling_utils.py`,
  `research/hf5src/models_auto_auto_factory.py`, `research/hf5src/models_auto_modeling_auto.py`,
  `research/hf5src/models_auto_configuration_auto.py`, `research/hf5src/models_auto_tokenization_auto.py`,
  `research/hf5src/models_auto_processing_auto.py`
