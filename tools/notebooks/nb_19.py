"""Ноутбук 19 — «Transformers v5: pipeline, generate, attention, auto-класи».

Розділ довідника: sections/19-transformers-v5.md
Виконується без API-ключів і без GPU: усі клітинки, що завантажують модель, захищені
try/except, а клітинки аналізу реальних сирців працюють на стандартній бібліотеці + ast.
"""

from nbkit import SETUP_CELL, VERSION_CELL, code, md

FILENAME = "19-transformers-v5.ipynb"
TITLE = "19. Transformers v5"

CELLS = [
    md(
        """
# 19. Transformers v5

**Розділ довідника:** [`sections/19-transformers-v5.md`](../sections/19-transformers-v5.md)

**Потрібно: torch + transformers (GPU бажаний, не обов'язковий).**
Ноутбук виконується **без ключів і без GPU**: клітинки, що завантажують модель, захищені
`try/except` і лише повідомляють про пропуск. Клітинки, які працюють **завжди**, розбирають
реальні сирці Transformers v5 із `research/hf5src/` через `ast` — саме так видно, як
насправді резолвляться auto-класи, без встановленого `transformers`.

**Що ви зробите:**

1. Перетворите `MIGRATION_GUIDE_V5.md` на аудит: витягнете з нього всі згадані
   ідентифікатори API і відділите v4-специфічні.
2. Напишете аудитор міграції, який знаходить ламальні місця у v4-коді регулярками.
3. Витягнете з документації реальну таблицю генераційних параметрів і побачите, чим
   відрізняються greedy, sampling і beam на одному розподілі.
4. Витягнете реєстр бекендів уваги з офіційної документації.
5. Розберете `MODEL_FOR_CAUSAL_LM_MAPPING_NAMES` зі справжнього файлу `transformers`.
6. **Виконаєте справжній код резолвінгу auto-класів** — `_get_model_class` і
   `_LazyAutoMapping.__getitem__`, витягнуті з `auto_factory.py` через `ast`.
7. Порахуєте пам'ять під ваги моделі й перевірите, чи є у вас GPU.
"""
    ),
    md("## Налаштування"),
    code(SETUP_CELL),
    code(VERSION_CELL),

    # ── 19.1 ─────────────────────────────────────────────────────────────
    md(
        """
## 19.1 Що змінилося у v5: аудит міграційного гайду

Гайд `MIGRATION_GUIDE_V5.md` — головне джерело фактів про ламальні зміни. Замість читати
його очима, витягнемо з нього всі ідентифікатори API, згадані в зворотних лапках, і
відділимо ті, що стосуються видаленого або зміненого v4-API.

Ця клітинка не потребує ні `transformers`, ні GPU — лише локальну копію гайду.
"""
    ),
    code(
        '''
import pathlib
import re

# Локальна копія MIGRATION_GUIDE_V5.md із репозиторію transformers.
guide = pathlib.Path(ROOT / "research/tf_v5_migration.txt").read_text(encoding="utf-8")

# Усі ідентифікатори API, згадані в одинарних зворотних лапках.
mentioned = sorted(set(re.findall(r"`([A-Za-z_][A-Za-z0-9_.]*\\(?\\)?)`", guide)))

V4_API = re.compile(
    r"^(load_in_|use_auth_token|encode_plus|batch_decode|prepare_seq2seq_batch|"
    r"AutoModelWithLMHead|AutoModelForVision2Seq|special_tokens_map|added_tokens|"
    r"sanitize_special_tokens|as_target_tokenizer|parse_response|"
    r"TRANSFORMERS_CACHE|PYTORCH_TRANSFORMERS_CACHE|torch_dtype|use_fast)\\b"
)
v4_api = [name for name in mentioned if V4_API.search(name)]

print(f"Рядків у гайді            : {len(guide.splitlines())}")
print(f"Ідентифікаторів API      : {len(mentioned)}")
print(f"З них v4-специфічних     : {len(v4_api)}")
print()
for name in v4_api:
    print(" ", name)
'''
    ),
    md(
        """
Що це дає на практиці: список вище — це **перелік місць у вашому коді**, які треба
перевірити перед оновленням `transformers` до v5. Зверніть увагу, що частина
ідентифікаторів у вибірці має дужки (`as_target_tokenizer()`, `parse_response()`) — гайд
згадує їх саме як виклики, і це додаткова підказка, що йдеться про метод, а не про
параметр.
"""
    ),

    # ── 19.2 ─────────────────────────────────────────────────────────────
    md(
        """
## 19.2 Аудитор міграції з v4 на v5

Тепер зробимо те саме, але для **свого коду**. Патерни взяті з міграційного гайду; кожен
відповідає або видаленому аргументу, або зміненому типу повернення.

Такий аудитор варто тримати як pre-commit хук: він ловить місця, які компілюються, але
ламаються під час виконання — саме тому їх не знаходить звичайний `grep` по назвах.
"""
    ),
    code(
        '''
import re

V4_PATTERNS = {
    "torch_dtype=":            r"torch_dtype\\s*=",
    "use_auth_token=":         r"use_auth_token\\s*=",
    "load_in_4bit/8bit=":      r"load_in_(?:4|8)bit\\s*=",
    "encode_plus(":            r"\\.encode_plus\\s*\\(",
    "AutoModelWithLMHead":     r"\\bAutoModelWithLMHead\\b",
    "AutoModelForVision2Seq":  r"\\bAutoModelForVision2Seq\\b",
    "use_fast= (процесор)":    r"use_fast\\s*=",
    "as_target_tokenizer":     r"as_target_tokenizer\\s*\\(",
    "special_tokens_map_ext":  r"special_tokens_map_extended|all_special_tokens_extended",
    "additional_special_tok":  r"\\badditional_special_tokens\\b",
    "TRANSFORMERS_CACHE":      r"TRANSFORMERS_CACHE|PYTORCH_TRANSFORMERS_CACHE",
    "transformers-cli":        r"transformers-cli",
    "generate через config":   r"\\.config\\.(?:do_sample|max_new_tokens|temperature)\\b",
}

# Приклад типового v4-коду: саме так виглядав продакшн до оновлення.
V4_CODE = """
from transformers import AutoModelForCausalLM, AutoTokenizer, AutoModelWithLMHead

tok = AutoTokenizer.from_pretrained("meta-llama/Llama-3.2-1B", use_auth_token=TOKEN)
model = AutoModelForCausalLM.from_pretrained(
    "meta-llama/Llama-3.2-1B", torch_dtype="auto", load_in_4bit=True, device_map="auto"
)
ids = tok.encode_plus("привіт", return_tensors="pt")["input_ids"]
print(tok.batch_decode(ids))
params = {"temperature": 0.7}
model.config.temperature = params["temperature"]   # v4-стиль
"""


def audit_v4(code: str, patterns: dict) -> list[tuple[int, str, str]]:
    """Повертає (номер рядка, мітка правила, текст рядка) для кожного збігу."""
    return [(n, label, line.strip())
            for n, line in enumerate(code.splitlines(), start=1)
            for label, pattern in patterns.items()
            if re.search(pattern, line)]


findings = audit_v4(V4_CODE, V4_PATTERNS)
print(f"Знайдено місць для міграції: {len(findings)}")
for n, label, line in findings:
    print(f"  рядок {n:>2}  [{label}]  {line}")
'''
    ),
    md(
        """
**Обмеження прикладу.** `audit_v4` зупиняється на першому збігу в рядку, тому рядок 5
(`torch_dtype=... load_in_4bit=...`) показано лише під однією міткою. У продакшн-хуку
збирайте всі збіги в рядку — інакше частина проблем залишиться непоміченою.

**Чого аудитор не знайде.** Він працює з текстом, тому не бачить змін, які не змінюють
назв: `apply_chat_template` тепер повертає `BatchEncoding`, а не тензор; `decode` на
списку входів повертає список рядків; `get_text_features` повертає об'єкт із
`pooler_output`. Ці місця треба перевіряти вручну — вони в розділі 19.2.
"""
    ),

    # ── 19.3 ─────────────────────────────────────────────────────────────
    md(
        """
## 19.3 `pipeline`: що зникло у v5

Витягнемо з міграційного гайду перелік видалених пайплайнів — це найшвидший спосіб
зрозуміти, чи зачепить оновлення ваш код.

Наступна клітинка працює завжди: вона лише читає локальну копію гайду.
"""
    ),
    code(
        '''
import pathlib
import re

guide = pathlib.Path(ROOT / "research/tf_v5_migration.txt").read_text(encoding="utf-8")

# Секція про пайплайни в гайді починається заголовком `## Pipelines`.
pipelines_section = guide.split("## Pipelines", 1)[1].split("## PushToHubMixin", 1)[0]

# Назви пайплайнів у гайді записані в зворотних лапках із дефісами: `image-to-text`.
named = sorted(set(re.findall(r"`([a-z0-9]+(?:-[a-z0-9]+)+)`", pipelines_section)))
classes = sorted(set(re.findall(r"`(\\w*Pipeline)`", pipelines_section)))

print("Пайплайни, названі в гайді як видалені:")
for name in named:
    print("  ", name)
print()
print("Класи пайплайнів, згадані в тій самій секції:")
for name in classes:
    print("  ", name)

assert "image-to-text" in named
assert "visual-question-answering" in named
assert "image-to-image" in named
print()
print("Перевірено: image-to-text, visual-question-answering, image-to-image у списку видалених.")
'''
    ),
    md(
        """
Документація дає і заміну: для сумаризації, перекладу й питань-відповідей — чат-модель
через `TextGenerationPipeline`, для роботи із зображеннями — `image-text-to-text`
(зображення вкладається в поле `content` повідомлення, окремим аргументом його більше
не передають).

Запуск справжнього пайплайна потребує `transformers` і мережі — клітинка нижче захищена.
"""
    ),
    code(
        '''
# ПОТРЕБУЄ: pip install transformers (+ мережа для завантаження моделі). GPU не потрібен.
try:
    from transformers import pipeline
except ImportError as exc:
    print("transformers не встановлено — клітинку пропущено.")
    print(f"Причина: {exc}")
    print("Встановіть:  pip install transformers")
else:
    try:
        generator = pipeline(
            task="text-generation",
            model="openai-community/gpt2",
            device="cpu",          # єдиний спосіб примусово працювати на CPU
            batch_size=2,
        )
        out = generator(
            ["the secret to baking a good cake is", "a baguette is"],
            num_return_sequences=1,
            return_full_text=False,
            max_new_tokens=20,
        )
        for batch in out:
            for item in batch:
                print(repr(item["generated_text"])[:90], "...")
    except Exception as exc:                 # мережа, пам'ять, відсутність ваг тощо
        print(f"Пайплайн не запустився ({type(exc).__name__}): {exc}")
        print("Це не помилка ноутбука: клітинка залежить від мережі й завантаження моделі.")
'''
    ),

    # ── 19.4 ─────────────────────────────────────────────────────────────
    md(
        """
## 19.4 `generate`: параметри проти документації

Перш ніж щось вигадувати про `generate`, витягнемо **офіційну** таблицю поширених
параметрів із `llm_tutorial.md`. Це захищає від головної помилки в цій темі — вигаданих
назв параметрів.
"""
    ),
    code(
        '''
import pathlib
import re

doc = pathlib.Path(ROOT / "research/hf5_tfdoc_llm_tutorial.txt").read_text(encoding="utf-8")

# Таблиця «Common Options»: | `param` | `type` | опис |
param_rows = re.findall(r"^\\|\\s*`([^`]+)`\\s*\\|\\s*`([^`]+)`\\s*\\|\\s*(.+?)\\s*\\|$", doc, re.M)

print(f"Параметрів у офіційній таблиці «Common Options»: {len(param_rows)}")
print()
for name, kind, desc in param_rows:
    print(f"{name:18} {kind:10} {desc[:78]}")
'''
    ),
    md(
        """
Тепер подивимося, **чому** стратегія декодування має значення. Клітинка нижче — це
модель, а не виклик бібліотеки: ми беремо невеликий розподіл і показуємо, як поводяться
три стратегії. Числа тут умовні, мета — побачити механіку: greedy завжди бере максимум,
sampling кидає жереб, beam оцінює сукупну ймовірність.

| Стратегія | Що оптимізує | Типова пастка |
|---|---|---|
| Greedy | Ймовірність **кожного** наступного токена | Зациклюється на довгих виходах |
| Sampling | Різноманітність | Потрібен `do_sample=True`, інакше `temperature` ігнорується |
| Beam | Сукупну ймовірність послідовності | У 2 рази більше обчислень на кожен крок |
"""
    ),
    code(
        '''
import math

# СХЕМА (а не вихід transformers): умовний розподіл наступного токена залежить від префікса.
# Саме тому greedy і beam можуть розійтися. Токени — A, B, C.
NEXT = {
    "":  [0.50, 0.40, 0.10],   # старт: A найімовірніший
    "A": [0.20, 0.70, 0.10],   # після A продовження слабке
    "B": [0.90, 0.05, 0.05],   # після B продовження сильне
    "C": [0.30, 0.30, 0.40],
}
VOCAB = ["A", "B", "C"]
DEPTH = 2


def greedy():
    """Бере найімовірніший токен на КОЖНОМУ кроці."""
    prefix, logp = "", 0.0
    for _ in range(DEPTH):
        i = max(range(len(VOCAB)), key=NEXT[prefix].__getitem__)
        logp += math.log(NEXT[prefix][i])
        prefix += VOCAB[i]
    return prefix, logp


def beam_search(width=2):
    """Тримає `width` найкращих префіксів і в кінці бере найкращий сукупно."""
    beams = [("", 0.0)]
    for _ in range(DEPTH):
        candidates = [(prefix + VOCAB[i], logp + math.log(p))
                      for prefix, logp in beams
                      for i, p in enumerate(NEXT[prefix])]
        beams = sorted(candidates, key=lambda kv: kv[1], reverse=True)[:width]
    return beams[0]


g_seq, g_logp = greedy()
b_seq, b_logp = beam_search(width=2)
print(f"greedy (кожен крок по максимуму): {g_seq}  сукупний log-скор {g_logp:.4f}")
print(f"beam width=2                    : {b_seq}  сукупний log-скор {b_logp:.4f}")
print()
assert g_seq != b_seq, "стратегії мають розійтися"
assert b_logp > g_logp, "beam має знайти сукупно ймовірнішу послідовність"
print(f"Greedy вибрав {g_seq}, beam — {b_seq}.")
print(f"Greedy бере найімовірніший ПЕРШИЙ токен (A) і не бачить, що продовження після нього слабке;")
print(f"beam оцінює сукупну ймовірність і знаходить кращий шлях (B -> A), хоч B стартує з 0.40.")
print()
print("Саме тому greedy ламається на довгих виходах і повторюється, а для чату беруть sampling.")
'''
    ),
    md(
        """
Два факти з документації, які найчастіше ламають продакшн:

- **Типова довжина — 20 нових токенів.** Якщо не задати `max_new_tokens`, відповідь
  обірветься на 20 токенах, і виглядатиме це як «модель дурна», а не як помилка.
- **`temperature` без `do_sample=True` нічого не робить.** Помилки не буде взагалі.

Третя пастка — `padding_side`. Документація показує реальний наслідок: на батчі
`["1, 2, 3", "A, B, C, D, E"]` з right-padding перший приклад генерується як
`'1, 2, 33333333333'`, а з `padding_side="left"` — як `'1, 2, 3, 4, 5, 6,'`.
"""
    ),

    # ── 19.5 ─────────────────────────────────────────────────────────────
    md(
        """
## 19.5 Бекенди уваги: реєстр із документації

`AttentionInterface` — реєстр реалізацій уваги. Витягнемо з офіційної сторінки
`attention_interface.md` реальну таблицю бекендів (вона в HTML, тому парсимо регуляркою).
"""
    ),
    code(
        '''
import pathlib
import re

doc = pathlib.Path(ROOT / "research/hf5_tfdoc_attention_interface.txt").read_text(encoding="utf-8")

# У файлі таблиця подана HTML-тегами <tr><td><code>"name"</code></td><td>опис</td></tr>
rows = re.findall(r'<tr><td><code>(?:&quot;|")(.+?)(?:&quot;|")</code></td><td>(.*?)</td></tr>', doc)

# У HTML-таблиці вертикальна риска закодована як &#124; — повертаємо її до звичайного вигляду.
rows = [(name.replace("&#124;", "|"), desc) for name, desc in rows]

print(f"Бекендів у офіційній таблиці: {len(rows)}")
print()
for name, desc in rows:
    print(f"  {name:24} {desc[:72]}")

backends = [name for name, _ in rows]
assert "sdpa" in backends
assert "paged|eager" in backends
print()
print("Перевірено: paged|eager і sdpa присутні в реєстрі.")
'''
    ),
    md(
        """
Що важливо побачити в цій таблиці:

1. **Типова реалізація — `"sdpa"`, а не `"eager"`.** Це видно і в сирцях: рядок
   `applicable_attention = "sdpa" if requested_attention is None else requested_attention`
   у `modeling_utils.py`.
2. **Paged-варіанти — це окремі записи з префіксом `paged|`.** Вони потрібні для
   безперервного батчингу, а не для звичайного `generate` в один запит.
3. **Відкат існує лише для неявного SDPA.** Якщо ви попросили `"sdpa"` явно, помилка не
   глушиться — див. розділ 19.5.
"""
    ),

    # ── 19.6 ─────────────────────────────────────────────────────────────
    md(
        """
## 19.6 Auto-класи: розбір справжніх сирців

Тут починається найцінніша частина: розбір **реальних** файлів Transformers v5 через
`ast`. Спочатку — таблиця «`model_type` → ім'я класу моделі».
"""
    ),
    code(
        '''
import ast
import pathlib

SRC = ROOT / "research/hf5src/models_auto_modeling_auto.py"
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
for node in tree.body:
    if not (isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id.endswith("_NAMES")):
        continue
    pairs, count = literal_pairs(node.value)
    if pairs:
        mappings[node.targets[0].id] = pairs
        records += count

print(f"Файл                    : {SRC.name}, {len(source.splitlines())} рядків")
print(f"Словників *_NAMES       : {len(mappings)}")
print(f"Записів                 : {records} "
      f"(унікальних ключів: {sum(len(v) for v in mappings.values())})")
print()

CAUSAL = mappings["MODEL_FOR_CAUSAL_LM_MAPPING_NAMES"]
print(f"MODEL_FOR_CAUSAL_LM_MAPPING_NAMES: {len(CAUSAL)} записів")
for key in ("bert", "llama", "mistral", "qwen3", "deepseek_v4"):
    print(f"  {key:12} -> {ast.unparse(CAUSAL[key])}")

# Скільки записів мають значенням кортеж, а не рядок?
tuples = {name: {k: ast.unparse(v) for k, v in pairs.items() if isinstance(v, ast.Tuple)}
          for name, pairs in mappings.items()}
tuples = {k: v for k, v in tuples.items() if v}
print()
print("Записи зі значенням-кортежем (саме для них працює вибір за `architectures`):")
for name, pairs in tuples.items():
    for k, v in pairs.items():
        print(f"  {name}: {k} -> {v}")
'''
    ),
    md(
        """
Що тут видно:

- **54 словники `*_NAMES`** — це вся «таблиця істинності» бібліотеки. `MODEL_FOR_CAUSAL_LM_MAPPING_NAMES`
  містить **178** записів, тобто 178 архітектур уміють бути завантажені як causal LM.
- **`bert` → `BertLMHeadModel`**, а не `BertForCausalLM`. Назва класу в таблиці не завжди
  повторює `model_type` — це та деталь, через яку `grep` по коду не знаходить потрібний клас.
- **Записів більше, ніж унікальних ключів.** Причина — дубль ключа `sam3_tracker` у
  `MODEL_MAPPING_NAMES`: при побудові `OrderedDict` другий запис перетирає перший.
- **Кортежі значень** — саме ті випадки, де клас вибирається за полем `config.architectures`.
"""
    ),
    md(
        """
### Токенізатори: окрема таблиця з іншого правила

`AutoTokenizer` резолвиться інакше. Найпоказовіший рядок у його коді — `use_fast`
просто викидається з аргументів:
"""
    ),
    code(
        '''
import ast
import pathlib
from collections import Counter

SRC = ROOT / "research/hf5src/models_auto_tokenization_auto.py"
source = SRC.read_text(encoding="utf-8")
tree = ast.parse(source)


def const_str(node):
    """Витягує ім'я класу, зокрема з 'X if is_tokenizers_available() else None'."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.IfExp):
        return const_str(node.body)
    return None


# Рядок, який доводить: у v5 use_fast ігнорується.
pop_line = next(line.strip() for line in source.splitlines() if "ignore use_fast parameter" in line)
print("Код у AutoTokenizer.from_pretrained:")
print("   ", pop_line)
print()

names = {}
for node in tree.body:
    if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", None) == "TOKENIZER_MAPPING_NAMES":
        for el in node.value.args[0].elts:
            if isinstance(el, ast.Tuple) and len(el.elts) == 2 and const_str(el.elts[0]) is not None:
                names[const_str(el.elts[0])] = const_str(el.elts[1])

print(f"TOKENIZER_MAPPING_NAMES: {len(names)} ключів")
print("Найчастіші класи:")
for cls, count in Counter(names.values()).most_common(5):
    print(f"  {cls:22} {count}")
print()
print("Точкові приклади:", {k: names.get(k) for k in ("bert", "qwen3", "qwen4_exp", "deepseek_v4")})

# Список моделей, для яких вміст tokenizer_config.json вважається неправильним.
incorrect = next(node for node in tree.body
                 if isinstance(node, ast.AnnAssign)
                 and getattr(node.target, "id", None) == "MODELS_WITH_INCORRECT_HUB_TOKENIZER_CLASS")
values = ast.literal_eval(incorrect.value)
print()
print(f"MODELS_WITH_INCORRECT_HUB_TOKENIZER_CLASS: {len(values)} model_type")
print("  перші 8:", sorted(values)[:8])
'''
    ),
    md(
        """
Три висновки з цієї клітинки:

1. **`use_fast` більше не працює** — аргумент прибирається з kwargs. Бекенд вибирають через
   `backend="tokenizers"` або `backend="sentencepiece"`.
2. **`TokenizersBackend` — найчастіший клас таблиці.** Це прямий наслідок рішення v5
   «відмовитися від поділу fast/slow».
3. **`deepseek_v4` у літералі таблиці відсутній** (`None` у виводі). Його додає цикл після
   неї — для кожного `model_type` зі списку `MODELS_WITH_INCORRECT_HUB_TOKENIZER_CLASS`
   у таблицю дописується `TokenizersBackend`. Тобто `tokenizer_config.json` на Hub для цих
   46 моделей **свідомо ігнорується**.
"""
    ),
    md(
        """
### Головне: виконати справжній код резолвінгу

Тепер найцікавіше. `_get_model_class` і `_LazyAutoMapping` витягуються **з реального
файлу** `auto_factory.py` через `ast` і виконуються в ізольованому просторі. Єдина
підміна — метод `_load_attr_from_module`: замість імпорту модуля `transformers.models.*`
він повертає рядок із таблиці, бо самого пакета в середовищі може не бути.

`CONFIG_MAPPING_NAMES` теж стенд-ін: реальна таблиця лежить у
`transformers/models/auto/auto_mappings.py`, якого немає в `research/`.

Логіка ж, яку ми перевіряємо, — справжня: саме вона вирішує, який клас створити.
"""
    ),
    code(
        '''
import ast
import importlib
import pathlib
from collections import OrderedDict
from typing import Any, Iterator, TypeVar

SRC = ROOT / "research/hf5src/models_auto_auto_factory.py"
tree = ast.parse(SRC.read_text(encoding="utf-8"))

# 1. Витягуємо РЕАЛЬНІ _get_model_class і _LazyAutoMapping (без решти модуля).
wanted = {"_get_model_class", "_LazyAutoMapping"}
nodes = [n for n in tree.body
         if (isinstance(n, ast.FunctionDef) and n.name in wanted)
         or (isinstance(n, ast.ClassDef) and n.name in wanted)]
module = ast.Module(body=nodes, type_ignores=[])
ast.fix_missing_locations(module)


class PreTrainedConfig:      # заглушка лише для анотацій
    ...


namespace = {
    "OrderedDict": OrderedDict, "PreTrainedConfig": PreTrainedConfig, "Iterator": Iterator,
    "Any": Any, "TypeVar": TypeVar, "_T": TypeVar("_T"),
    "_LazyAutoMappingValue": tuple, "importlib": importlib,
}
exec(compile(module, "auto_factory_extract", "exec"), namespace)

_get_model_class = namespace["_get_model_class"]
LazyAutoMapping = namespace["_LazyAutoMapping"]
print("Витягнуто з реального файлу:", [n.name for n in nodes])


# 2. Стенд-ін таблиць. `Names` — це dict, у який _LazyAutoMapping пише зворотний покажчик.
class Names(dict):
    _model_mapping = None


class StrMapping(LazyAutoMapping):
    """Підміняємо ЛИШЕ імпорт модуля: замість класу повертаємо його ім'я з таблиці."""

    def _load_attr_from_module(self, model_type, attr):
        return attr


CONFIG_MAPPING_NAMES = Names({"qwen3": "Qwen3Config", "deepseek_v4": "DeepseekV4Config",
                              "funnel": "FunnelConfig"})
MODEL_FOR_CAUSAL_LM_MAPPING_NAMES = Names({"qwen3": "Qwen3ForCausalLM",
                                          "deepseek_v4": "DeepseekV4ForCausalLM"})
mapping = StrMapping(CONFIG_MAPPING_NAMES, MODEL_FOR_CAUSAL_LM_MAPPING_NAMES)


# 3. Резолвінг класу конфігурації -> клас моделі (справжній __getitem__).
print()
print("Qwen3Config      ->", mapping[type("Qwen3Config", (), {})])
print("DeepseekV4Config ->", mapping[type("DeepseekV4Config", (), {})])
try:
    mapping[type("LlamaConfig", (), {})]
except KeyError as exc:
    print("LlamaConfig      -> KeyError:", exc)
    print("   (KeyError виникає ДО роботи з моделями: класу конфігурації немає в таблиці)")


# 4. Вибір із кортежу за полем architectures (той самий реальний _get_model_class).
class FunnelModel: pass
class FunnelBaseModel: pass


tuple_mapping = StrMapping(CONFIG_MAPPING_NAMES, Names({"funnel": (FunnelModel, FunnelBaseModel)}))
print()
for archs in (["FunnelBaseModel"], ["Nonexistent"], []):
    config = type("FunnelConfig", (), {})()
    config.architectures = archs
    print(f"architectures={str(archs):20} -> {_get_model_class(config, tuple_mapping).__name__}")
print()
print("Якщо architectures не збігається ні з чим — береться ПЕРШИЙ елемент кортежу.")
'''
    ),
    md(
        """
Три факти, які ця клітинка доводить на **справжньому** коді:

1. **Резолвінг іде за іменем класу конфігурації**, а не за `model_type`. Тому `KeyError`
   виникає ще до будь-якої роботи з моделями: якщо класу конфігурації немає в
   `CONFIG_MAPPING_NAMES`, до таблиці моделей справа не дійде.
2. **`_extra_content` перевіряється першим.** Усе, додане через `register`, має пріоритет
   над вбудованою таблицею — саме так працює `AutoModel.register`.
3. **`architectures` впливає лише на записи-кортежі.** Для звичайного запису-рядка вибір
   однозначний, і `architectures` не враховується взагалі.
"""
    ),

    # ── 19.7 ─────────────────────────────────────────────────────────────
    md(
        """
## 19.7 Пристрій, dtype і пам'ять

Спочатку — арифметика пам'яті. Це множення, а не вимір: скільки байтів займе **лише**
ваги моделі за різних типів. KV-кеш, активації й фрагментація додаються зверху, тому
реальна потреба завжди більша.
"""
    ),
    code(
        '''
BYTES_PER_PARAM = {"fp32": 4.0, "fp16/bf16": 2.0, "int8/fp8": 1.0, "4-bit": 0.5}
GIB = 1024 ** 3


def weights_gb(num_params: int, dtype_name: str) -> float:
    """Скільки гігабайт займуть ЛИШЕ ваги моделі (без KV-кешу й активацій)."""
    return num_params * BYTES_PER_PARAM[dtype_name] / GIB


print(f"{'dtype':10} {'7B':>10} {'70B':>12}")
print("-" * 34)
for name, bytes_per_param in BYTES_PER_PARAM.items():
    print(f"{name:10} {weights_gb(7_000_000_000, name):>9.2f} ГБ {weights_gb(70_000_000_000, name):>9.2f} ГБ")

print()
print("Ці числа — орієнтир для планування, а не гарантія, що модель завантажиться.")
'''
    ),
    md(
        """
Тепер — чи є у вас GPU. Клітинка захищена: без `torch` вона просто повідомить про це.

Далі в розділі 19.7 є ще один важливий факт, який тут не видно: у v5 `torch_dtype`
застарілий і замінене на `dtype`, а `load_in_4bit` / `load_in_8bit` **видалені** — єдиний
шлях до квантизації тепер `quantization_config`.
"""
    ),
    code(
        '''
# ПОТРЕБУЄ: pip install torch (GPU не обов'язковий)
try:
    import torch
except ImportError as exc:
    print("torch не встановлено — клітинку пропущено.")
    print(f"Причина: {exc}")
    print("Встановіть CPU-версію:  pip install torch --index-url https://download.pytorch.org/whl/cpu")
else:
    print("torch          :", torch.__version__)
    print("CUDA доступна  :", torch.cuda.is_available())
    if torch.cuda.is_available():
        print("пристроїв      :", torch.cuda.device_count())
        print("пам'ять 0-ї    :", round(torch.cuda.get_device_properties(0).total_memory / 1024 ** 3, 2), "ГБ")
    mps = getattr(torch.backends.mps, "is_available", lambda: False)
    print("MPS доступний  :", mps())
    print("dtype типово   :", torch.get_default_dtype())
'''
    ),
    md(
        """
І нарешті — спроба завантажити реальну модель. Вона потребує `transformers`, `torch` і
мережі, тому повністю захищена. Зверніть увагу на `device_map="cpu"` і `dtype="auto"`:
це v5-синтаксис, у v4 тут було б `torch_dtype="auto"`.
"""
    ),
    code(
        '''
# ПОТРЕБУЄ: pip install torch transformers (+ мережа). GPU не обов'язковий.
try:
    from transformers import AutoConfig, AutoModelForCausalLM, AutoTokenizer
except ImportError as exc:
    print("transformers / torch не встановлено — клітинку пропущено.")
    print(f"Причина: {exc}")
else:
    MODEL_ID = "Qwen/Qwen2.5-0.5B-Instruct"   # маленька модель: поміщається на CPU
    try:
        config = AutoConfig.from_pretrained(MODEL_ID)
        print(f"model_type        : {config.model_type}")
        print(f"architectures     : {getattr(config, 'architectures', None)}")

        tokenizer = AutoTokenizer.from_pretrained(MODEL_ID)
        print(f"tokenizer class   : {type(tokenizer).__name__}")

        model = AutoModelForCausalLM.from_pretrained(MODEL_ID, dtype="auto", device_map="cpu")
        print(f"model class       : {type(model).__name__}")
        print(f"attn_implementation: {model.config._attn_implementation}")
        print(f"device / dtype    : {model.device} / {model.dtype}")
        print(f"параметрів        : {model.num_parameters():,}")

        inputs = tokenizer("The quick brown", return_tensors="pt")
        ids = model.generate(**inputs, max_new_tokens=8, do_sample=False)
        print("greedy            :", tokenizer.decode(ids[0], skip_special_tokens=True))
        ids = model.generate(**inputs, max_new_tokens=8, do_sample=True, temperature=0.8)
        print("sampling          :", tokenizer.decode(ids[0], skip_special_tokens=True))
    except Exception as exc:
        print(f"Модель не завантажилася ({type(exc).__name__}): {exc}")
        print("Найчастіші причини: немає мережі, немає доступу до Hub, мало пам'яті.")
        print("Клітинка інформаційна — решта ноутбука від неї не залежить.")
'''
    ),

    # ── самоперевірка ────────────────────────────────────────────────────
    md(
        """
## Самоперевірка

Клітинка нижче перевіряє **реальні** факти з сирців і документації. Усі `assert`-и
працюють без `transformers`, без `torch` і без GPU.
"""
    ),
    code(
        '''
# ── 1. Таблиця causal-LM у реальному файлі transformers ──────────────────
assert len(CAUSAL) == 178, f"очікувалось 178 записів, знайдено {len(CAUSAL)}"
assert ast.unparse(CAUSAL["bert"]) == "'BertLMHeadModel'", "bert має вести на BertLMHeadModel"
assert ast.unparse(CAUSAL["deepseek_v4"]) == "'DeepseekV4ForCausalLM'"
print(f"✓ MODEL_FOR_CAUSAL_LM_MAPPING_NAMES: {len(CAUSAL)} записів; bert -> BertLMHeadModel")

# ── 2. Словників *_NAMES рівно 54, і в них є записи-кортежі ──────────────
assert len(mappings) == 54, f"очікувалось 54 словники, знайдено {len(mappings)}"
assert sum(len(v) for v in tuples.values()) == 4, "має бути рівно 4 записи зі значенням-кортежем"
assert "funnel" in tuples["MODEL_MAPPING_NAMES"], "funnel має вибиратися з кортежу"
print(f"✓ {len(mappings)} словників *_NAMES; {sum(len(v) for v in tuples.values())} записів із кортежем")

# ── 3. Дубль ключа в MODEL_MAPPING_NAMES: записів більше, ніж унікальних ─
raw = {name: len(pairs) for name, pairs in mappings.items()}
assert records > sum(len(v) for v in mappings.values()), "має бути щонайменше один дубль ключа"
print(f"✓ Записів {records} > унікальних ключів {sum(len(v) for v in mappings.values())} (дубль sam3_tracker)")

# ── 4. Токенізаторна таблиця: 264 ключі й найчастіший клас TokenizersBackend ─
assert len(names) == 264, f"очікувалось 264 ключі, знайдено {len(names)}"
top = Counter(names.values()).most_common(1)[0]
assert top[0] == "TokenizersBackend", f"найчастіший клас має бути TokenizersBackend, а не {top[0]}"
print(f"✓ TOKENIZER_MAPPING_NAMES: {len(names)} ключів; найчастіший клас {top[0]} ({top[1]})")

# ── 5. Список «неправильних» tokenizer_config.json ───────────────────────
assert len(values) == 46, f"очікувалось 46 model_type, знайдено {len(values)}"
assert "deepseek_v4" in values and "qwen2" in values
print(f"✓ MODELS_WITH_INCORRECT_HUB_TOKENIZER_CLASS: {len(values)} model_type, зокрема deepseek_v4")

# ── 6. Реєстр бекендів уваги з документації ──────────────────────────────
assert "sdpa" in backends and "paged|sdpa" in backends
assert "flash_attention_2" in backends and "flex_attention" in backends
print(f"✓ AttentionInterface: {len(backends)} бекендів, зокрема sdpa і paged|sdpa")

# ── 7. Параметри generate з офіційної таблиці ────────────────────────────
param_names = {name for name, _, _ in param_rows}
for expected in ("max_new_tokens", "do_sample", "temperature", "num_beams", "repetition_penalty", "eos_token_id"):
    assert expected in param_names, f"{expected} має бути в таблиці Common Options"
print(f"✓ Офіційна таблиця генераційних параметрів: {len(param_names)} параметрів, усі ключові на місці")

# ── 8. Резолвінг auto-класу виконується і поводиться очікувано ───────────
assert mapping[type("Qwen3Config", (), {})] == "Qwen3ForCausalLM"
cfg = type("FunnelConfig", (), {})()
cfg.architectures = ["Nonexistent"]
assert _get_model_class(cfg, tuple_mapping).__name__ == "FunnelModel", "має братися перший елемент"
print("✓ Резолвінг: Qwen3Config -> Qwen3ForCausalLM; невідомий architectures -> перший елемент кортежу")

# ── 9. Арифметика пам'яті ────────────────────────────────────────────────
assert abs(weights_gb(7_000_000_000, "fp16/bf16") - 13.04) < 0.01
assert weights_gb(7_000_000_000, "4-bit") < weights_gb(7_000_000_000, "int8/fp8")
print(f"✓ Пам'ять: 7B у bf16 = {weights_gb(7_000_000_000, 'fp16/bf16'):.2f} ГБ, у 4-bit = {weights_gb(7_000_000_000, '4-bit'):.2f} ГБ")

# ── 10. Гайд справді містить згадки видаленого API ───────────────────────
for gone in ("AutoModelWithLMHead", "load_in_4bit", "encode_plus"):
    assert gone in guide, f"{gone} має бути згаданий у міграційному гайді"
print("✓ Міграційний гайд: згадки AutoModelWithLMHead, load_in_4bit, encode_plus знайдено")

print()
print("Усі перевірки пройдено.")
'''
    ),

    # ── підсумок ─────────────────────────────────────────────────────────
    md(
        """
## Підсумок

**Головне з цього ноутбука:**

1. **v5 — це не «оновлення залежності», а проєкт міграції.** Половина змін механічна
   (`torch_dtype` → `dtype`, `use_auth_token` → `token`, `load_in_8bit` →
   `quantization_config`), друга половина — семантична й тиха (`apply_chat_template`
   повертає `BatchEncoding`; `decode` на списку входів повертає список рядків).
2. **Аудит гайду й аудит власного коду робляться регулярками.** Обидва працюють без
   `transformers` і годиться як pre-commit.
3. **`generate` типово дає 20 нових токенів**, а `temperature` без `do_sample=True`
   мовчки ігнорується. Батчинг генерації вимагає `padding_side="left"`.
4. **Типовий `attn_implementation` — `"sdpa"`, а не `"eager"`.** Paged-режим — окремі
   записи з префіксом `paged|`. Явно запитана SDPA не має відкату: помилка не глушиться.
5. **Auto-класи резолвляться за іменем класу конфігурації, а не за `model_type`.**
   Це видно з реального коду `_LazyAutoMapping.__getitem__`, який ми виконали.
6. **`architectures` впливає на вибір класу лише для записів-кортежів.** Решта — один
   однозначний клас із таблиці.
7. **`AutoTokenizer` у v5 ігнорує `use_fast`** і для 46 `model_type` свідомо ігнорує
   `tokenizer_class` із `tokenizer_config.json`.
8. **Пам'ять під ваги — це множення**, і воно не враховує KV-кеш та активації. `dtype="auto"`
   дає тип, у якому чекпойнт збережено, а не тип тренування.

**Куди далі:**

- Розділ 20 — квантизація: що саме втрачається за 4 біти й на чому саме економія.
- Розділ 21 — fine-tuning: LoRA/PEFT, SFT, DPO, GRPO на тих самих auto-класах.
- Розділ 2 — префіл і декодування: чому довжина промпту коштує інакше, ніж довжина виходу.
- Розділ 6 — вибір моделі: коли локальна модель справді дешевша за API.

## Джерела

- [MIGRATION_GUIDE_V5.md](https://raw.githubusercontent.com/huggingface/transformers/main/MIGRATION_GUIDE_V5.md)
- [Transformers v5 — анонс](https://huggingface.co/blog/transformers-v5)
- [Attention backends](https://raw.githubusercontent.com/huggingface/transformers/main/docs/source/en/attention_interface.md)
- [Text generation (llm_tutorial)](https://raw.githubusercontent.com/huggingface/transformers/main/docs/source/en/llm_tutorial.md)
- [Generation strategies](https://raw.githubusercontent.com/huggingface/transformers/main/docs/source/en/generation_strategies.md)
- [Pipeline tutorial](https://raw.githubusercontent.com/huggingface/transformers/main/docs/source/en/pipeline_tutorial.md)
- [Auto classes (model_doc/auto)](https://raw.githubusercontent.com/huggingface/transformers/main/docs/source/en/model_doc/auto.md)
- Реальні сирці у репозиторії: `research/hf5src/models_auto_auto_factory.py`,
  `research/hf5src/models_auto_modeling_auto.py`, `research/hf5src/models_auto_tokenization_auto.py`,
  `research/hf5src/modeling_utils.py`
"""
    ),
]
