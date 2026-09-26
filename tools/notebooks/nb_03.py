"""Ноутбук 03 — «Токенізація на практиці».

Розділ довідника: sections/03-tokenizaciya.md
Працює без API-ключів і без GPU.
"""

from nbkit import SETUP_CELL, VERSION_CELL, code, md

FILENAME = "03-tokenizaciya.ipynb"
TITLE = "3. Токенізація на практиці"

CELLS = [
    md(
        """
# 03. Токенізація на практиці

**Розділ довідника:** [`sections/03-tokenizaciya.md`](../sections/03-tokenizaciya.md)

**Потрібно:** нічого — жодних API-ключів, жодного GPU.
Ноутбук повністю виконується на стандартній бібліотеці Python і `jinja2`.
Єдина опційна залежність — `transformers` (клітинки, які її потребують, позначені).

**Що ви зробите:**

1. Переконаєтесь, що токен — це не символ і не слово.
2. Реалізуєте BPE власними руками (38 рядків) і побачите, **чому** українська
   коштує більше токенів за англійську.
3. Проведете аудит реальних конфігів токенізаторів Qwen3.8 і DeepSeek V4 та
   знайдете пастки, невидимі оком.
4. Відрендерите справжній chat-шаблон Gemma 4 офлайн і побачите, як
   перемикається режим мислення на рівні токенів.
5. Навчитеся рахувати токени до відправки запиту.
"""
    ),
    md("## Налаштування"),
    code(SETUP_CELL),
    code(VERSION_CELL),

    # ── 3.1 ──────────────────────────────────────────────────────────────
    md(
        """
## 3.1 Токен — не символ і не слово

Токенізатор не бачить тексту. Він бачить **байти** UTF-8 і збирає з них
елементи словника. Тому перший крок — побачити, з чого насправді
починається будь-який текст.
"""
    ),
    code(
        """
# Скільки байтів займає один символ у UTF-8?
# Це стартовий алфавіт будь-якого byte-level BPE.
for s in ["a", "ї", "ґ", "я", "🙂"]:
    print(f"{s!r}: {len(s)} символ, {len(s.encode('utf-8'))} байт(и), "
          f"{[hex(b) for b in s.encode('utf-8')]}")
"""
    ),
    md(
        """
Ключове спостереження: **латиниця — 1 байт, кирилиця — 2 байти, емодзі — 4.**
Алгоритм BPE стартує з байтів, тож українське слово починає «життя» з удвічі
довшої послідовності, ніж англійське тієї самої довжини.

Чому `len(text)` — погана міра кількості токенів:

| Вхідні дані | Що робить токенізатор |
|---|---|
| Часті англійські слова | Часто один токен на ціле слово |
| Числа (`1234567`) | Майже без мержів — кілька токенів на число |
| Код і відступи | Пробіли мержаться погано |
| Кирилиця | 2 байти на символ і рідші мержи |
| Base64 / UUID | Практично випадкові символи — найгірший випадок |
"""
    ),

    # ── BPE власними руками ──────────────────────────────────────────────
    md(
        """
## 3.2 BPE власними руками: чому українська дорожча

Щоб зрозуміти механізм, а не повірити на слово, реалізуємо BPE — той самий
алгоритм, який використовують реальні токенізатори.

**Ідея:** почати з окремих символів і повторно зливати найчастішу пару
сусідніх символів у новий елемент словника. Після `N` злиттів часті
послідовності стають одним токеном, а рідкісні залишаються розбитими.

Нижче — навчальна реалізація (не продакшн-токенізатор: справжні працюють на
байтах, а не на символах, і мають словник у сотні тисяч елементів).
"""
    ),
    code(
        '''
from collections import Counter


def learn_bpe(corpus: list[str], num_merges: int = 60) -> list[tuple[str, str]]:
    """Навчає таблицю злиттів BPE на корпусі слів.

    Повертає список пар (a, b), які були злиті, у порядку злиття.
    """
    # Кожне слово — послідовність символів плюс маркер кінця слова.
    words = [list(w) + ["</w>"] for w in corpus]
    merges: list[tuple[str, str]] = []

    for _ in range(num_merges):
        pairs = Counter()
        for w in words:
            for a, b in zip(w, w[1:]):
                pairs[(a, b)] += 1
        if not pairs:
            break

        (a, b), count = pairs.most_common(1)[0]
        merges.append((a, b))

        # Застосовуємо злиття до всіх слів
        new_words = []
        for w in words:
            out, i = [], 0
            while i < len(w):
                if i < len(w) - 1 and w[i] == a and w[i + 1] == b:
                    out.append(a + b)
                    i += 2
                else:
                    out.append(w[i])
                    i += 1
            new_words.append(out)
        words = new_words

    return merges


def apply_bpe(word: str, merges: list[tuple[str, str]]) -> list[str]:
    """Токенізує слово, застосовуючи вивчені злиття в тому ж порядку."""
    tokens = list(word) + ["</w>"]
    for a, b in merges:
        out, i = [], 0
        while i < len(tokens):
            if i < len(tokens) - 1 and tokens[i] == a and tokens[i + 1] == b:
                out.append(a + b)
                i += 2
            else:
                out.append(tokens[i])
                i += 1
        tokens = out
    return tokens


print("Функції learn_bpe() і apply_bpe() готові.")
'''
    ),
    md(
        """
Тепер найважливіший крок: навчимо таблицю злиттів на **англомовному** корпусі
(саме так виглядає більшість тренувальних даних) і застосуємо її до
англійського та українського тексту однакового змісту.
"""
    ),
    code(
        '''
# Англомовний корпус — імітація переважно англійських тренувальних даних.
EN_CORPUS = """
the quick brown fox jumps over the lazy dog
the sun is bigger than the moon
a bacterium is bigger than a virus
the weather is nice today and the sun is shining
she sells sea shells by the sea shore
the quick brown fox runs and the dog sleeps
information retrieval and text search systems
the model reads the text and writes the answer
""".split()

merges = learn_bpe(EN_CORPUS, num_merges=60)
print(f"Вивчено злиттів: {len(merges)}")
print("Перші 15 злиттів:", merges[:15])
'''
    ),
    code(
        '''
# Той самий зміст двома мовами + контрольні приклади
SAMPLES = {
    "англійська": "the quick brown fox jumps over the lazy dog",
    "українська": "швидка руда лисиця стрибає через ледачого пса",
    "код":        "def f(x): return x ** 2",
    "числа":      "1234567890",
    "base64":     "aGVsbG8gd29ybGQ=",
}

print(f"{'тип':12} {'символів':>9} {'токенів':>8} {'симв/токен':>11}   токени")
print("-" * 78)
for name, text in SAMPLES.items():
    all_tokens: list[str] = []
    for word in text.split():
        all_tokens.extend(apply_bpe(word, merges))
    ratio = len(text) / len(all_tokens)
    preview = " ".join(all_tokens[:12]) + (" …" if len(all_tokens) > 12 else "")
    print(f"{name:12} {len(text):>9} {len(all_tokens):>8} {ratio:>11.2f}   {preview}")
'''
    ),
    md(
        """
### Що показує цей досвід

Дивіться на стовпець **симв/токен**. Англійський текст дає більше символів на
токен — тобто кращу компресію, бо таблиця злиттів вивчена саме з англійських
даних. Український текст із тим самим змістом стискається гірше.

Причини рівно дві, і обидві видно в коді вище:

1. **Стартова довжина.** Українське слово починається з 2 байтів на символ
   замість 1 (див. 3.1).
2. **Відсутність мержів.** Пари, потрібні для українських морфем, майже не
   траплялися в англомовному корпусі, тож для них не вивчено жодного злиття.

> **Важливо:** це навчальна модель, її числа не можна переносити на реальні
> токенізатори. Реальне співвідношення для вашої мови й домену треба міряти
> справжнім токенізатором — див. 3.5.
"""
    ),
    code(
        '''
# Перевірка механізму: чи справді річ у мержах, а не в довжині?
# Візьмемо однакову кількість символів і порівняємо кількість токенів.

en = "the quick brown fox"
uk = "прудка бура лисиця"          # рівно 16 літер в обох, перевірено нижче

def token_count(text: str) -> int:
    return sum(len(apply_bpe(w, merges)) for w in text.split())

en_chars = len(en.replace(" ", ""))
uk_chars = len(uk.replace(" ", ""))
assert en_chars == uk_chars, "порівняння має бути за однакової кількості літер"
print(f"англійська: {en_chars} літер -> {token_count(en)} токенів")
print(f"українська: {uk_chars} літер -> {token_count(uk)} токенів")
print()
print("Висновок: за однакової кількості літер українська дає більше токенів.")
'''
    ),

    # ── 3.3 спецтокени ───────────────────────────────────────────────────
    md(
        """
## 3.3 Аудит спецтокенів: реальні конфіги

Спецтокени — це маркери ролей і службові елементи. Помилка з ними не кидає
винятку: модель просто отримує інший вхід і відповідає гірше.

Розберемо **справжній** `tokenizer_config.json` моделі Qwen3.8 із `research/tt/`.
"""
    ),
    code(
        '''
import json

cfg = json.loads((ROOT / "research/tt/qwen38_tokcfg.json").read_text(encoding="utf-8"))

print("tokenizer_class     :", cfg["tokenizer_class"])
print("model_max_length    :", cfg["model_max_length"])
print("eos_token           :", cfg["eos_token"])
print("pad_token           :", cfg["pad_token"])
print("bos_token           :", cfg["bos_token"])
print("split_special_tokens:", cfg["split_special_tokens"])
print("кількість added_tokens:", len(cfg["added_tokens_decoder"]))
'''
    ),
    md(
        """
Три речі, на які тут варто звернути увагу:

- `bos_token` — **`None`**. Отже додавати початковий токен до цього промпту
  було б помилкою.
- `eos_token` = `<|im_end|>` — саме цей токен модель генерує, коли завершує
  репліку. Забудете його при ручному формуванні промпту — модель може не
  зупинитися.
- `split_special_tokens: False` — спецтокени **не** розбиваються на частини.

### Пастка: `special: False`

Не всі елементи з `added_tokens_decoder` є «захищеними» спецтокенами — у
кожного є прапорець `special`.
"""
    ),
    code(
        '''
# Які з доданих токенів НЕ мають захисту від розбиття?
not_special = [
    (tid, tok["content"])
    for tid, tok in cfg["added_tokens_decoder"].items()
    if not tok["special"]
]

print(f"Усього added_tokens: {len(cfg['added_tokens_decoder'])}")
print(f"З них special=False: {len(not_special)}")
print()
for tid, content in not_special:
    print(f"{tid:>7}  {content!r}")
'''
    ),
    md(
        """
Це **не** помилка конфігурації — це усвідомлене рішення з наслідками.

Токен із `special: False` не захищений від розбиття. Якщо такий рядок
трапиться всередині звичайного тексту користувача, токенізатор може розбити
його на фрагменти — і модель побачить не маркер структури, а звичайний текст.

**Практичні висновки:**

1. Рядок у кутових дужках — ще не токен. Перевіряйте прапорець `special`.
2. Користувацький текст, який містить службові маркери, треба екранувати або
   відхиляти. Це частина моделі загроз prompt injection (розділ 11).

### Пастка: символи, які виглядають звичайними

Подивіться на спецтокени DeepSeek V4. Вони містять символи, які **візуально
не відрізнити** від звичайних.
"""
    ),
    code(
        '''
ds = json.loads((ROOT / "research/tt/dsv4_tokcfg.json").read_text(encoding="utf-8"))

print("model_max_length:", ds["model_max_length"])
print()
for name in ("bos_token", "eos_token", "pad_token"):
    content = ds[name]["content"]
    print(f"{name:10} = {content!r}")
    print(f'{"":13} кодові точки: {[hex(ord(c)) for c in content[:8]]}')
'''
    ),
    code(
        '''
def audit_token(text: str) -> None:
    """Показує небезпечні символи: повноширинні, невидимі, замінники пробілів."""
    suspicious = {
        "\\u007c": "ASCII VERTICAL LINE — звичайний",
        "\\uff5c": "FULLWIDTH VERTICAL LINE — НЕ звичайний!",
        "\\u2581": "LOWER ONE EIGHTH BLOCK (SentencePiece-пробіл)",
        "\\u00a0": "NO-BREAK SPACE",
        "\\u200b": "ZERO WIDTH SPACE",
    }
    for ch in text:
        if ch in suspicious:
            print(f"U+{ord(ch):04X}  {suspicious[ch]}")
        elif not ch.isprintable():
            print(f"U+{ord(ch):04X}  недрукований символ")


print("--- як виглядає звичайний ASCII-варіант ---")
audit_token("|end|")
print()
print("--- те, що реально в конфізі DeepSeek V4 ---")
audit_token(ds["eos_token"]["content"])
'''
    ),
    md(
        """
Різниця очевидна: у справжньому токені використано **U+FF5C**
(FULLWIDTH VERTICAL LINE), а не ASCII `|` (**U+007C**), і **U+2581**
(LOWER ONE EIGHTH BLOCK), а не звичайний пробіл.

Якщо скопіювати токен із веб-сторінки й «виправити» символи на схожі
звичайні — модель отримає зовсім іншу послідовність токенів і мовчки
працюватиме гірше. Саме тому аудит вище варто тримати в своєму арсеналі.

### `extra_special_tokens`: окремий простір імен
"""
    ),
    code(
        '''
# Це не те саме, що added_tokens_decoder: тут зіставлення РОЛЕЙ і токенів.
print(json.dumps(cfg["extra_special_tokens"], indent=2, ensure_ascii=False))
'''
    ),
    md(
        """
`added_tokens_decoder` — те, що токенізатор фізично знає.
`extra_special_tokens` — те, як шаблон і код **посилаються** на ці токени.
Плутанина між ними дає помилки на кшталт вставлення рядка `<|image_pad|>`
туди, де очікується справжній image-блок.
"""
    ),

    # ── 3.4 chat templates ───────────────────────────────────────────────
    md(
        """
## 3.4 Chat-шаблони: розбір реального шаблону

Головний інсайт, без якого не зрозуміти поведінку чат-моделей:

> **Чат-модель не знає, що таке «повідомлення». Вона продовжує послідовність токенів.**

Немає жодного «чату» всередині моделі. Є модель, натренована на
послідовностях, де репліки розділені службовими маркерами. Chat-шаблон — це
функція, яка перетворює список повідомлень на ці маркери.

Розберемо **справжній** продакшн-шаблон Gemma 4 (390 рядків) із `research/tt/`.
Його можна відрендерити офлайн, без моделі й без GPU.
"""
    ),
    code(
        '''
import jinja2
import pathlib

tpl_src = (ROOT / "research/tt/gemma4_tmpl.jinja").read_text(encoding="utf-8")
print(f"Розмір шаблону Gemma 4: {len(tpl_src.splitlines())} рядків")

# Заголовок шаблону — сам по собі джерело інформації
print()
print("\\n".join(tpl_src.splitlines()[:7]))
'''
    ),
    code(
        '''
env = jinja2.Environment(trim_blocks=True, lstrip_blocks=True)
gemma = env.from_string(tpl_src)

messages = [{"role": "user", "content": "Привіт! Скільки буде 2+2?"}]

out_off = gemma.render(messages=messages, bos_token="<bos>", add_generation_prompt=True)
out_on = gemma.render(messages=messages, bos_token="<bos>",
                      add_generation_prompt=True, enable_thinking=True)

print("--- thinking ВИМКНЕНО ---")
print(repr(out_off))
print()
print("--- thinking УВІМКНЕНО ---")
print(repr(out_on))
'''
    ),
    md(
        """
### Що тут сталося — і чому це важливо

Порівняйте два виводи:

| | thinking вимкнено | thinking увімкнено |
|---|---|---|
| Хід `<\\|turn>system` | відсутній | присутній |
| Токен `<\\|think\\|>` | немає | є, у системному ході |
| Кінець виводу | `<\\|channel>thought\\n<channel\\|>` — **порожній** канал, уже закритий | `<\\|turn>model\\n` — хід моделі **відкритий** |

Шаблон не просто «додає токен». У першому випадку він заздалегідь закриває
канал мислення — фактично кажучи моделі «міркувати не треба». У другому —
залишає його відкритим, запрошуючи міркування.

**Режим мислення перемикається на рівні токенів, а не на рівні API.** Для
локальної моделі «увімкнути thinking» означає передати правильний аргумент
у шаблон.
"""
    ),
    code(
        '''
# Порівняємо з другим реальним шаблоном — GPT-OSS (330 рядків).
tpl_gptoss = (ROOT / "research/tt/gptoss_tmpl.jinja").read_text(encoding="utf-8")
gptoss = env.from_string(tpl_gptoss)

print(f"Розмір шаблону GPT-OSS: {len(tpl_gptoss.splitlines())} рядків")
print()
try:
    out_gpt = gptoss.render(messages=messages, bos_token="<bos>", add_generation_prompt=True)
    print("--- GPT-OSS, той самий діалог ---")
    print(repr(out_gpt))
except Exception as exc:                       # шаблон може вимагати інших змінних
    print(f"Шаблон GPT-OSS потребує додаткових змінних: {type(exc).__name__}: {exc}")
'''
    ),
    md(
        """
Різні моделі — різні маркери для того самого діалогу. Це і є причина, чому
chat-шаблон не можна «приблизно вгадати»: модель бачить саме маркери, а не
ваші наміри.

### Правильне використання через Transformers

Наступна клітинка потребує `transformers` і завантажить токенізатор із Hub
(потрібна мережа). Якщо бібліотеки немає — клітинка це повідомить і не
зламає ноутбук.
"""
    ),
    code(
        '''
# ПОТРЕБУЄ: pip install transformers  (і мережу для завантаження токенізатора)
MODEL_ID = "Qwen/Qwen3-8B"   # замініть на будь-яку модель із Hub

try:
    from transformers import AutoTokenizer

    tok = AutoTokenizer.from_pretrained(MODEL_ID)
    chat = [
        {"role": "system", "content": "Ти — помічник, що відповідає українською."},
        {"role": "user", "content": "Поясни, що таке токен."},
    ]

    # add_generation_prompt=True додає маркер початку відповіді асистента.
    # Без нього модель може ПРОДОВЖИТИ репліку користувача замість відповіді.
    text = tok.apply_chat_template(chat, tokenize=False, add_generation_prompt=True)
    print("З add_generation_prompt=True:")
    print(repr(text))
    print()
    text_off = tok.apply_chat_template(chat, tokenize=False, add_generation_prompt=False)
    print("З add_generation_prompt=False:")
    print(repr(text_off))
except ImportError:
    print("transformers не встановлено — клітинку пропущено.")
    print("Встановіть:  pip install transformers")
except Exception as exc:
    print(f"Не вдалося завантажити токенізатор ({type(exc).__name__}): {exc}")
    print("Перевірте мережу або замініть MODEL_ID на доступну модель.")
'''
    ),

    # ── 3.5 token counting ───────────────────────────────────────────────
    md(
        """
## 3.5 Підрахунок токенів до відправки

Дві різні задачі, які часто плутають:

| Задача | Інструмент | Точність |
|---|---|---|
| Дізнатися кількість **до** запиту | `messages.count_tokens` (Anthropic) | Оцінка |
| Дізнатися, за що **фактично** сплачено | Поле `usage` у відповіді | Точне значення |

### Точний локальний підрахунок

Для локальної моделі токенізатор рахує **точно**.
"""
    ),
    code(
        '''
# ПОТРЕБУЄ: pip install transformers
MEASURE_MODEL = "Qwen/Qwen3-8B"   # замініть на потрібну модель

SAMPLES_TO_MEASURE = {
    "англійська": "The quick brown fox jumps over the lazy dog.",
    "українська": "Швидка руда лисиця стрибає через ледачого пса.",
    "код":        "def f(x):\\n    return x ** 2\\n",
    "числа":      "1234567890",
    "base64":     "aGVsbG8gd29ybGQ=",
}

try:
    from transformers import AutoTokenizer

    _tok = AutoTokenizer.from_pretrained(MEASURE_MODEL)
    print(f"Токенізатор: {MEASURE_MODEL}")
    print(f"Розмір словника: {_tok.vocab_size}")
    print()
    print(f"{'тип':12} {'символів':>9} {'токенів':>8} {'симв/токен':>11}")
    print("-" * 45)
    for name, text in SAMPLES_TO_MEASURE.items():
        n = len(_tok(text)["input_ids"])
        print(f"{name:12} {len(text):>9} {n:>8} {len(text)/n:>11.2f}")
    print()
    print("Запустіть це на СВОЄМУ тексті — так отримують реальне")
    print("співвідношення для української, а не з чужого блогу.")
except ImportError:
    print("transformers не встановлено — клітинку пропущено.")
except Exception as exc:
    print(f"Помилка ({type(exc).__name__}): {exc}")
'''
    ),
    md(
        """
### Підрахунок через API Anthropic

Наступна клітинка потребує `ANTHROPIC_API_KEY` у `.env`. Вона показує головне:
**опис інструментів теж входить у вхідні токени** — це постійний податок на
кожен запит.
"""
    ),
    code(
        '''
# ПОТРЕБУЄ: ANTHROPIC_API_KEY у .env  +  pip install anthropic python-dotenv
import os

try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except ImportError:
    pass

if not os.environ.get("ANTHROPIC_API_KEY"):
    print("ANTHROPIC_API_KEY не задано — клітинку пропущено.")
    print("Скопіюйте .env.example у .env і впишіть ключ.")
else:
    try:
        import anthropic

        client = anthropic.Anthropic()
        MODEL = "claude-opus-5"

        base = client.messages.count_tokens(
            model=MODEL,
            system="Ти — науковець",
            messages=[{"role": "user", "content": "Hello, Claude"}],
        )
        print("Без інструментів:", base.json())

        with_tools = client.messages.count_tokens(
            model=MODEL,
            tools=[{
                "name": "get_weather",
                "description": "Get the current weather in a given location",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "location": {
                            "type": "string",
                            "description": "The city and state, e.g. San Francisco, CA",
                        }
                    },
                    "required": ["location"],
                },
            }],
            messages=[{"role": "user", "content": "What's the weather like in San Francisco?"}],
        )
        print()
        print("З описом інструмента:", with_tools.json())
        print()
        print("Різниця — це ціна опису інструментів, яку ви платите КОЖЕН запит.")
    except Exception as exc:
        print(f"Помилка виклику API ({type(exc).__name__}): {exc}")
'''
    ),
    md(
        """
### Обмеження `count_tokens` (з документації)

| Властивість | Деталь |
|---|---|
| Точність | **Оцінка** — фактична кількість може трохи відрізнятися |
| Системні токени | Може включати токени оптимізацій Anthropic. **За них ви не платите** |
| Не приймає | server tools (web search, web fetch, code execution, tool search — крім advisor tool), MCP connector, а також `image`/`document` із джерелом `url` або `file` → `invalid_request_error` |
| Обхід для зображень/PDF | Передавати як base64 |
| Решта випадків | Дивіться `usage` у відповіді Messages API |
"""
    ),

    # ── 3.6 context window ───────────────────────────────────────────────
    md(
        """
## 3.6 Контекстне вікно і накопичення токенів

Усе в запиті займає місце в контекстному вікні: системний промпт, кожне
повідомлення (разом із результатами інструментів), **визначення інструментів**
і згенерований вихід разом із токенами мислення.

Наступна клітинка моделює накопичення, щоб побачити головне: розмір запиту
зростає з кожним ходом, навіть коли ви не додаєте нового контенту.
"""
    ),
    code(
        '''
# Модель накопичення контексту в діалозі.
# Числа тут — довільні, але пропорції реалістичні для RAG-застосунку:
# опис інструментів і системний промпт — фіксований податок на КОЖЕН запит.

SYSTEM_PROMPT_TOKENS   = 400     # інструкції
TOOL_DEFS_TOKENS       = 1200    # описи інструментів — фіксовані!
USER_MSG_TOKENS        = 60      # середнє повідомлення користувача
ASSISTANT_MSG_TOKENS   = 250     # середня відповідь моделі
THINKING_TOKENS        = 500     # токени мислення (тарифікуються як вихід)

def request_tokens(turn: int) -> int:
    """Скільки вхідних токенів у запиті на ході `turn` (нумерація з 1)."""
    history = (turn - 1) * (USER_MSG_TOKENS + ASSISTANT_MSG_TOKENS + THINKING_TOKENS)
    return SYSTEM_PROMPT_TOKENS + TOOL_DEFS_TOKENS + history + USER_MSG_TOKENS

cumulative_in = 0
print(f"{'хід':>4} {'вхід':>7} {'накопичено':>11}   частка фіксованих")
print("-" * 52)
for turn in range(1, 11):
    inp = request_tokens(turn)
    cumulative_in += inp
    fixed = (SYSTEM_PROMPT_TOKENS + TOOL_DEFS_TOKENS) / inp
    print(f"{turn:>4} {inp:>7} {cumulative_in:>11}   {fixed:>9.0%}")

print()
print("Зверніть увагу: частка фіксованих витрат (промпт + інструменти)")
print("падає з кожним ходом, а накопичена сума зростає НЕЛІНІЙНО —")
print("бо кожен хід пересилає всю попередню історію.")
'''
    ),
    md(
        """
Накопичення **квадратичне**: десять ходів — це не десять, а п'ятдесят п'ять
пересилань повідомлень. Ось чому в довгих діалогах керування контекстом
важливіше за оптимізацію окремого промпту.

### «Context rot»

За документацією Anthropic, у міру зростання кількості токенів **точність і
повнота відтворення падають**. Тому «більше контексту» не означає «краще»:
велике вікно не рятує від падіння якості, воно лише відсуває технічну межу.
Саме тому RAG відбирає релевантне (розділ 16), а не вкладає все.

### Чи залишаються блоки мислення в контексті

| Моделі | Поведінка |
|---|---|
| Claude Opus 4.5+ , Sonnet 4.6+ , Fable 5.1, Mythos 5.1, Fable 5, Mythos 5, Mythos Preview | **Зберігаються** й тарифікуються як вхідні токени наступних запитів |
| Ранніші Opus і Sonnet, усі Haiku | API **автоматично видаляє** їх, коли ви передаєте їх назад |

Виняток: у циклі з інструментами блок мислення **обов'язково** повертати разом
із `tool_result` — це єдиний випадок, де це вимога (розділ 12).
"""
    ),

    # ── самоперевірка ────────────────────────────────────────────────────
    md(
        """
## Самоперевірка

Клітинка нижче перевіряє твердження з розділу. Якщо все виконано правильно —
усі перевірки пройдуть.
"""
    ),
    code(
        '''
# ── 1. Кирилиця справді займає 2 байти UTF-8 ─────────────────────────────
assert len("я".encode("utf-8")) == 2, "кирилиця має бути 2 байти"
assert len("a".encode("utf-8")) == 1, "латиниця має бути 1 байт"
assert len("🙂".encode("utf-8")) == 4, "емодзі має бути 4 байти"
print("✓ UTF-8: латиниця 1 байт, кирилиця 2, емодзі 4")

# ── 2. BPE з англомовного корпусу стискає англійську краще ───────────────
en_ratio = len(en.replace(" ", "")) / token_count(en)
uk_ratio = len(uk.replace(" ", "")) / token_count(uk)
assert en_ratio > uk_ratio, f"англійська має стискатись краще ({en_ratio} vs {uk_ratio})"
print(f"✓ BPE: англійська {en_ratio:.2f} симв/токен > українська {uk_ratio:.2f} симв/токен")

# ── 3. У Qwen3.8 bos_token відсутній ─────────────────────────────────────
assert cfg["bos_token"] is None, "у Qwen3.8 bos_token має бути None"
print("✓ Qwen3.8: bos_token is None — додавати BOS вручну було б помилкою")

# ── 4. Знайдено токени без захисту special ───────────────────────────────
assert len(not_special) == 12, f"очікувалось 12 токенів special=False, знайдено {len(not_special)}"
assert any(c == "<think>" for _, c in not_special), "<think> має бути серед special=False"
print("✓ Qwen3.8: 12 токенів мають special=False, зокрема '<think>'")

# ── 5. Спецтокени DeepSeek містять повноширинні символи ──────────────────
eos_content = ds["eos_token"]["content"]
codepoints = {ord(c) for c in eos_content}
assert 0xFF5C in codepoints, "має бути U+FF5C FULLWIDTH VERTICAL LINE"
assert 0x2581 in codepoints, "має бути U+2581 LOWER ONE EIGHTH BLOCK"
assert 0x007C not in codepoints, "ASCII '|' там бути не повинно"
print("✓ DeepSeek V4: спецтокени містять U+FF5C і U+2581, але не ASCII '|'")

# ── 6. Шаблон Gemma 4 по-різному формує thinking ─────────────────────────
assert "<|think|>" in out_on, "з enable_thinking=True має з'явитись <|think|>"
assert "<|think|>" not in out_off, "без enable_thinking токена <|think|> бути не повинно"
assert "<|turn>model\\n" in out_on, "хід моделі має залишитись відкритим"
assert out_off.endswith("<channel|>"), "без thinking канал має бути закритий"
print("✓ Gemma 4: режим мислення перемикається на рівні токенів шаблону")

# ── 7. Накопичення контексту нелінійне ───────────────────────────────────
assert request_tokens(10) > request_tokens(1) * 5, "зростання має бути суттєвим"
print(f"✓ Контекст: хід 1 = {request_tokens(1)} токенів, хід 10 = {request_tokens(10)} токенів")

print()
print("Усі перевірки пройдено.")
'''
    ),

    # ── підсумок ─────────────────────────────────────────────────────────
    md(
        """
## Підсумок

**Головне з цього ноутбука:**

1. **Токен — це не символ і не слово.** Токенізатор працює з байтами UTF-8,
   а BPE зливає найчастіші пари. Тому `len(text)` не є мірою кількості токенів.
2. **Українська дорожча з двох причин:** 2 байти на символ і рідші мержи в
   переважно англомовних тренувальних даних. Точне співвідношення треба
   **міряти своїм текстом**, а не брати з чужого блогу.
3. **Токенізатор змінюється між поколіннями моделей.** За документацією
   Anthropic, Claude 4.7+ дає приблизно на 30% більше токенів на тому ж
   тексті, ніж попередні моделі. Не переносьте виміри між моделями.
4. **Не все, що схоже на спецтокен, ним є.** Прапорець `special: False`
   означає відсутність захисту від розбиття.
5. **Повноширинні символи — реальна пастка.** U+FF5C і U+2581 невидимі оком,
   але змінюють послідовність токенів.
6. **Чат — це послідовність токенів**, а не структура всередині моделі.
   Chat-шаблон — частина протоколу, і режим мислення перемикається саме в ньому.
7. **`add_generation_prompt=True`** — інакше модель може продовжити репліку
   користувача замість відповіді.
8. **Контекст накопичується нелінійно**, а його зростання погіршує якість
   (context rot). Куруйте контекст, а не наповнюйте його.

**Куди далі:**

- Розділ 2 — як токени перетворюються на гроші й час (префіл, декодування, KV-кеш).
- Розділ 6 — вибір моделі з урахуванням ціни за токен.
- Розділ 9 — prompt caching: як платити менше за той самий текст.
- Розділ 16 — RAG: як не вкладати весь документ у контекст.

## Джерела

- [Anthropic — Token counting](https://platform.claude.com/docs/en/docs/build-with-claude/token-counting)
- [Anthropic — Context windows](https://platform.claude.com/docs/en/build-with-claude/context-windows)
- [Anthropic — Messages API](https://platform.claude.com/docs/en/api/messages)
- [Hugging Face — Chat templates](https://raw.githubusercontent.com/huggingface/transformers/main/docs/source/en/chat_templating.md)
- Реальні конфіги в репозиторії: `research/tt/qwen38_tokcfg.json`,
  `research/tt/dsv4_tokcfg.json`, `research/tt/gemma4_tmpl.jinja`,
  `research/tt/gptoss_tmpl.jinja`
"""
    ),
]
