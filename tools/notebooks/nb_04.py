"""Ноутбук 04 — «Claude API: Messages, стрімінг, версіонування, помилки».

Розділ довідника: sections/04-claude-api.md
Працює без API-ключа: усі клітинки з викликами API перевіряють наявність
ANTHROPIC_API_KEY і друкують пояснення, якщо ключа немає.
"""

from nbkit import SETUP_CELL, VERSION_CELL, code, md

FILENAME = "04-claude-api.ipynb"
TITLE = "4. Claude API"

CELLS = [
    md(
        """
# 04. Claude API: Messages, стрімінг, версіонування, помилки

**Розділ довідника:** [`sections/04-claude-api.md`](../sections/04-claude-api.md)

**Потрібно: ANTHROPIC_API_KEY** — скопіюйте `.env.example` у `.env` і впишіть ключ
(`cp .env.example .env`). Ноутбук **повністю виконується й без ключа**: клітинки з викликами API
друкують пояснення, що клітинку пропущено, а всі локальні приклади й перевірки працюють завжди.

**Що ви зробите:**

1. Розберете анатомію запиту: обов'язкові поля, нормалізацію `content`, арифметику `usage`
   (три лічильники входу замість одного).
2. Побачите, як системний промпт стає стабільним кешованим префіксом, і для яких моделей
   system-хід усередині діалогу взагалі дозволений.
3. Розберете справжній SSE-потік Anthropic власним парсером — з `ping`, кумулятивним `usage`
   і коректною обробкою невідомих типів подій.
4. Перевірите формат beta-заголовків і навчитеся прибирати застарілі параметри семплювання,
   які на нових моделях дають 400.
5. Побудуєте класифікатор помилок і розклад експоненційного відкату з урахуванням `retry-after`.
6. Порахуєте, скільки запитів на хвилину витримає ваш профіль навантаження і який лімітер
   (RPM/ITPM/OTPM) спрацює першим.
"""
    ),
    md("## Налаштування"),
    code(SETUP_CELL),
    code(VERSION_CELL),
    md(
        """
### Ключ і клієнт

Ключ читається **тільки** з `.env` через `python-dotenv` — у коді ноутбука його немає.
Якщо пакета `python-dotenv` немає, читаються звичайні змінні середовища.
"""
    ),
    code(
        '''
# Читання ключа з .env. Ноутбук виконується й без нього: клітинки з API
# просто друкують пояснення й пропускаються.
import os

try:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
    print("python-dotenv: читаю .env (якщо файл існує)")
except ImportError:
    print("python-dotenv не встановлено — читаю лише змінні середовища.")
    print("Встановити:  pip install python-dotenv")

HAS_KEY = bool(os.environ.get("ANTHROPIC_API_KEY"))
print("ANTHROPIC_API_KEY:",
      "знайдено" if HAS_KEY else "НЕ задано — усі API-клітинки буде пропущено")
print("Підказка: усі локальні приклади нижче працюють і без ключа.")


def api_client():
    """Повертає клієнт Anthropic або None, якщо немає ключа чи пакета."""
    if not HAS_KEY:
        return None
    try:
        import anthropic
    except ImportError:
        print("Пакет anthropic не встановлено:  pip install anthropic")
        return None
    return anthropic.Anthropic()
'''
    ),

    # ── 4.1 ──────────────────────────────────────────────────────────────
    md(
        """
## 4.1 Анатомія Messages API

Тіло запиту: обов'язкова трійка `model`, `max_tokens`, `messages` плюс опційні поля. Відповідь —
об'єкт `Message` з **масивом** блоків контенту, причиною зупинки `stop_reason` і лічильниками
`usage`.

| Поле `usage` | Що означає |
|---|---|
| `input_tokens` | Токени **після останньої точки кешування** |
| `cache_creation_input_tokens` | Токени, записані в кеш |
| `cache_read_input_tokens` | Токени, прочитані з кешу |
| `output_tokens` | Вихідні токени; авторитетне значення для білінгу |

Арифметика з довідки:
`total_input_tokens = cache_read_input_tokens + cache_creation_input_tokens + input_tokens`.
"""
    ),
    code(
        '''
import json

# usage з прикладу відповіді в довідці Messages API
usage = {"input_tokens": 2095, "cache_creation_input_tokens": 2051,
         "cache_read_input_tokens": 2051, "output_tokens": 503}
total_input = (usage["input_tokens"] + usage["cache_creation_input_tokens"]
               + usage["cache_read_input_tokens"])
print("усього вхідних токенів:", total_input,
      f"(input_tokens — лише {usage['input_tokens'] / total_input:.0%} від входу)")

# content-рядок — це скорочення для одного text-блоку, а не окремий тип
request = {
    "model": "claude-opus-5",
    "max_tokens": 1024,
    "system": "Ти — технічний редактор. Відповідай українською.",
    "messages": [
        {"role": "user", "content": "Поясни, що таке стрімінг."},
        {"role": "assistant", "content": "Стрімінг — це передача відповіді частинами."},
        {"role": "user", "content": [{"type": "text", "text": "А навіщо він потрібен?"}]},
    ],
}
missing = [f for f in ("model", "max_tokens", "messages") if f not in request]
assert not missing, f"бракує обов'язкових полів: {missing}"


def normalize(message: dict) -> dict:
    """Розгортає content-рядок у масив блоків — так його бачить API."""
    content = message["content"]
    if isinstance(content, str):
        content = [{"type": "text", "text": content}]
    return {**message, "content": content}


normalized = [normalize(m) for m in request["messages"]]
roles = [m["role"] for m in normalized]
merged = [r for i, r in enumerate(roles) if i == 0 or r != roles[i - 1]]
print("ролі:", roles, "-> після злиття підряд:", merged)
print("content останнього ходу:", json.dumps(normalized[-1]["content"], ensure_ascii=False))
'''
    ),
    md(
        """
Тепер справжній виклик. Зверніть увагу на два місця: відповідь читається **фільтром за типом
блоку**, а не за індексом, і `stop_reason` перевіряється явно — це не помилка, а сигнал.
"""
    ),
    code(
        '''
# ПОТРЕБУЄ: ANTHROPIC_API_KEY у .env  +  pip install anthropic python-dotenv
client = api_client()

if client is None:
    print("Клітинку пропущено: немає ANTHROPIC_API_KEY (або пакета anthropic).")
    print("Локальні приклади вище й нижче виконуються без ключа.")
else:
    try:
        message = client.messages.create(
            model="claude-opus-5",
            max_tokens=256,
            messages=[{"role": "user", "content": "Say hello in one word."}],
        )
        for block in message.content:          # НЕ message.content[0]
            if block.type == "text":
                print("text:", block.text)
        print("stop_reason :", message.stop_reason)
        print("usage       :", message.usage)
        print("request_id  :", message._request_id)
    except Exception as exc:
        print(f"Помилка виклику API ({type(exc).__name__}): {exc}")
'''
    ),

    # ── 4.2 ──────────────────────────────────────────────────────────────
    md(
        """
## 4.2 Системний промпт і рольова структура

Два механізми: **top-level `system`** (діє від першого ходу, формує початок кешованого префікса) і
**`role: "system"` усередині `messages`** (діє з моменту появи в історії, лише для Claude Fable 5.1,
Mythos 5.1, Fable 5, Mythos 5, Opus 4.8 і Opus 5). Другий **не інвалідує** кешованого префікса
перед собою, але не може бути першим елементом `messages`.

Масив блоків у `system` потрібен тому, що `cache_control` чіпляється до блоку, а не до рядка.
"""
    ),
    code(
        '''
system_blocks = [
    {"type": "text", "text": "Ти — асистент підтримки. Відповідай стисло."},
    {"type": "text", "text": "<довідник продукту: 40 000 токенів>",
     "cache_control": {"type": "ephemeral"}},
]
for i, block in enumerate(system_blocks):
    print(f"  блок {i}: cache_control={block.get('cache_control')}")

# Моделі, які приймають system-повідомлення в СЕРЕДИНІ діалогу.
MID_SYSTEM_MODELS = {"claude-fable-5-1", "claude-mythos-5-1", "claude-fable-5",
                     "claude-mythos-5", "claude-opus-4-8", "claude-opus-5"}


def with_mid_system(model: str, turns: list[dict], instruction: str) -> list[dict]:
    """Додає system-хід після останнього user-ходу — лише для моделей зі списку."""
    if model not in MID_SYSTEM_MODELS:
        raise ValueError(f"{model} не приймає system-хід усередині діалогу")
    out = list(turns)
    at = max(i for i, m in enumerate(out) if m["role"] == "user") + 1
    out.insert(at, {"role": "system", "content": instruction})
    return out


turns = [{"role": "user", "content": "Порахуй знижку."},
         {"role": "assistant", "content": "Готую розрахунок..."}]
print("ролі до  :", [m["role"] for m in turns])
print("ролі після:", [m["role"] for m in with_mid_system(
    "claude-opus-5", turns, "Далі — лише таблицею.")])

try:
    with_mid_system("claude-sonnet-4-5", turns, "Не дозволено")
except ValueError as exc:
    print("перевірка списку моделей спрацювала:", exc)
'''
    ),
    code(
        '''
# ПОТРЕБУЄ: ANTHROPIC_API_KEY
if client is None:
    print("Клітинку пропущено: немає ANTHROPIC_API_KEY.")
else:
    try:
        msg = client.messages.create(
            model="claude-opus-5",
            max_tokens=256,
            system=system_blocks,
            messages=[{"role": "user", "content": "Як змінити тарифний план?"}],
        )
        print("cache_creation_input_tokens:",
              getattr(msg.usage, "cache_creation_input_tokens", None))
        print("cache_read_input_tokens    :",
              getattr(msg.usage, "cache_read_input_tokens", None))
        print()
        print("Другий запит із тим самим префіксом має дати cache_read > 0 —")
        print("саме так перевіряють, чи кеш справді працює (розділ 9).")
    except Exception as exc:
        print(f"Помилка виклику API ({type(exc).__name__}): {exc}")
'''
    ),

    # ── 4.3 ──────────────────────────────────────────────────────────────
    md(
        """
## 4.3 Стрімінг і типи подій

Послідовність подій: `message_start` → (`content_block_start` → `content_block_delta`* →
`content_block_stop`)* → `message_delta`* → `message_stop`. Події `ping` можуть бути будь-де.

| Тип дельти | Поле | Особливість |
|---|---|---|
| `text_delta` | `text` | Звичайний текст |
| `input_json_delta` | `partial_json` | Частковий JSON; фінальний `input` — об'єкт |
| `thinking_delta` | `thinking` | Текст міркування |
| `signature_delta` | `signature` | Перед `content_block_stop`; цілісність блоку |

Нижче — **справжній** фрагмент SSE-відповіді з довідки Anthropic, розібраний власним парсером.
"""
    ),
    code(
        '''
import json

RAW = """event: message_start
data: {"type": "message_start", "message": {"id": "msg_1nZdL29xx5MUA1yADyHTEsnR8uuvGzszyY", "type": "message", "role": "assistant", "content": [], "model": "claude-opus-5", "stop_reason": null, "stop_sequence": null, "usage": {"input_tokens": 25, "output_tokens": 1}}}

event: content_block_start
data: {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}}

event: ping
data: {"type": "ping"}

event: content_block_delta
data: {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "Hello"}}

event: content_block_delta
data: {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "!"}}

event: content_block_stop
data: {"type": "content_block_stop", "index": 0}

event: message_delta
data: {"type": "message_delta", "delta": {"stop_reason": "end_turn", "stop_sequence": null}, "usage": {"output_tokens": 15}}

event: message_stop
data: {"type": "message_stop"}
"""


def iter_sse(raw: str):
    # Розбирає SSE-потік у пари (ім'я події, розібраний JSON).
    event, data = None, []
    for line in raw.splitlines():
        if line.startswith("event:"):
            event = line[len("event:"):].strip()
        elif line.startswith("data:"):
            data.append(line[len("data:"):].strip())
        elif not line.strip() and (event or data):
            yield event, json.loads("".join(data))
            event, data = None, []
    if event or data:
        yield event, json.loads("".join(data))


KNOWN = {"message_start", "content_block_start", "content_block_delta",
         "content_block_stop", "message_delta", "message_stop", "ping", "error"}

text, blocks, unknown, final_usage, n = [], {}, 0, {}, 0
for name, payload in iter_sse(RAW):
    n += 1
    if payload["type"] not in KNOWN:        # нові типи подій можливі — не падаємо
        unknown += 1
    elif name == "content_block_start":
        blocks[payload["index"]] = payload["content_block"]["type"]
    elif name == "content_block_delta" and payload["delta"]["type"] == "text_delta":
        text.append(payload["delta"]["text"])
    elif name == "message_delta":
        final_usage = payload["usage"]

print("подій:", n, "| невідомих типів:", unknown, "| блоки:", blocks)
print("склеєний текст:", repr("".join(text)))
print("фінальний usage:", final_usage, "(кумулятивний)")
'''
    ),
    code(
        '''
# ПОТРЕБУЄ: ANTHROPIC_API_KEY
if client is None:
    print("Клітинку пропущено: немає ANTHROPIC_API_KEY.")
else:
    try:
        with client.messages.stream(
            model="claude-opus-5", max_tokens=256,
            messages=[{"role": "user", "content": "Порахуй від 1 до 5."}],
        ) as stream:
            for chunk in stream.text_stream:
                print(chunk, end="", flush=True)
            final = stream.get_final_message()
        print()
        print("get_final_message() ідентичний .create():")
        print("  stop_reason:", final.stop_reason, "output_tokens:", final.usage.output_tokens)
    except Exception as exc:
        print(f"Помилка стрімінгу ({type(exc).__name__}): {exc}")
'''
    ),

    # ── 4.4 ──────────────────────────────────────────────────────────────
    md(
        """
## 4.4 Версіонування й сумісність

Три різні осі: **версія API** (`anthropic-version`, обов'язковий заголовок), **beta-функції**
(`anthropic-beta`, імена вигляду `feature-name-YYYY-MM-DD` — але угода саме «typically», тож бувають
імена без дати) і **версія SDK** (`anthropic`, SemVer із трьома документованими винятками).

Окремо — застарівання `temperature`, `top_p`, `top_k`: за документацією їх не приймають Claude 4.7 і
пізніші моделі та Claude Mythos Preview.
"""
    ),
    code(
        '''
import re

API_VERSION = "2023-06-01"          # SDK надсилає цей заголовок сам

# Beta-імена: угода feature-name-YYYY-MM-DD. Вона саме «typically», тому
# перевірка попереджає, а не падає: у документації є й імена без дати.
BETA_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
DATED_RE = re.compile(r"-\\d{4}-\\d{2}-\\d{2}$")
DOCUMENTED_BETAS = ["context-management-2025-06-27", "managed-agents-2026-04-01",
                    "mcp-tunnels-2026-06-22", "agent-memory-2026-07-22",
                    "thinking-binding-controls-2026-08-01", "user-profiles"]


def check_betas(betas: list[str]) -> list[str]:
    """Повертає попередження про імена без дати; хибний формат — виняток."""
    out = []
    for name in betas:
        if not BETA_RE.match(name):
            raise ValueError(f"некоректне beta-ім'я: {name!r}")
        if not DATED_RE.search(name):
            out.append(f"{name}: без дати у назві — звірте з документацією")
    return out


print("API version за замовчуванням SDK:", API_VERSION)
for warning in check_betas(DOCUMENTED_BETAS):
    print("WARN:", warning)

# Sampling-параметри застаріли: за документацією їх не приймають
# Claude 4.7 і пізніші моделі та Claude Mythos Preview.
NO_SAMPLING_PARAMS = {"claude-opus-4-7", "claude-opus-4-8", "claude-opus-5",
                      "claude-sonnet-5", "claude-fable-5", "claude-fable-5-1",
                      "claude-mythos-5", "claude-mythos-5-1", "claude-mythos-preview"}
LEGACY_SAMPLING = ("temperature", "top_p", "top_k")


def sanitize(payload: dict) -> dict:
    """Прибирає застарілі параметри семплювання для моделей, які їх не приймають."""
    if payload["model"] not in NO_SAMPLING_PARAMS:
        return payload
    dropped = [p for p in LEGACY_SAMPLING if p in payload]
    if dropped:
        print(f"  {payload['model']}: прибрано {dropped} (інакше 400)")
    return {k: v for k, v in payload.items() if k not in LEGACY_SAMPLING}


for model in ("claude-opus-5", "claude-sonnet-4-5"):
    kept = sanitize({"model": model, "max_tokens": 256, "temperature": 0.2})
    print(f"  {model:18} -> ключі: {sorted(kept)}")
'''
    ),

    # ── 4.5 ──────────────────────────────────────────────────────────────
    md(
        """
## 4.5 Коди помилок, 429/529, експоненційний відкат

Три шари обробки збоїв: HTTP-статус із тілом `error`, типізовані винятки SDK і події `error`
всередині вже відкритого стріму.

Документація SDK: автоматично ретраяться **2 рази** з коротким експоненційним відкатом — помилки
з'єднання, 408, 409, 429 і всі ≥500; заголовок `retry-after` поважається. Керується параметром
`max_retries`.
"""
    ),
    code(
        '''
import random

RETRYABLE_STATUSES = {408, 409, 429}


def is_retryable(status: int | None = None, *, connection_error: bool = False) -> bool:
    """Ретраяться: помилки з'єднання, 408, 409, 429 і >=500 (за документацією SDK)."""
    if connection_error:
        return True
    return status is not None and (status in RETRYABLE_STATUSES or status >= 500)


def backoff_delay(attempt: int, retry_after: float | None = None,
                  base: float = 0.5, cap: float = 8.0,
                  rng: random.Random | None = None) -> float:
    """Пауза перед спробою. retry-after скасовує формулу; стеля — після джиттера."""
    if retry_after is not None:
        return float(retry_after)              # сервер сам назвав точне число
    delay = base * 2 ** (attempt - 1)
    if rng is not None:
        delay *= 0.5 + rng.random()            # щоб клієнти не били в один момент
    return round(min(cap, delay), 2)


rng = random.Random(7)
print(f"{'спроба':>7} {'звичайна':>10} {'retry-after=30':>15}")
for attempt in range(1, 6):
    print(f"{attempt:>7} {backoff_delay(attempt, rng=rng):>10} "
          f"{backoff_delay(attempt, retry_after=30):>15}")

for label, kwargs in [("з'єднання обірвано", {"connection_error": True}),
                      ("400 invalid_request_error", {"status": 400}),
                      ("401 authentication_error", {"status": 401}),
                      ("429 rate_limit_error", {"status": 429}),
                      ("500 api_error", {"status": 500}),
                      ("529 overloaded_error", {"status": 529})]:
    print(f"{label:28} -> {'ретраїти' if is_retryable(**kwargs) else 'НЕ ретраїти'}")
'''
    ),
    md(
        """
Клітинка нижче **не робить запит** — вона лише показує, як виглядає клієнт із вимкненими
автоматичними повторами. Так роблять, коли потрібен власний шар ретраїв із чергою або бюджетом.
"""
    ),
    code(
        '''
# ПОТРЕБУЄ: ANTHROPIC_API_KEY (виклик API не робиться)
if client is None:
    print("Клітинку пропущено: немає ANTHROPIC_API_KEY.")
else:
    try:
        import anthropic

        no_retry = anthropic.Anthropic(max_retries=0)   # типово 2
        print("клієнт без автоматичних повторів створено:",
              type(no_retry).__name__)
        print("типові винятки SDK:",
              ", ".join(sorted(
                  name for name in dir(anthropic)
                  if name.endswith("Error"))))
    except Exception as exc:
        print(f"Не вдалося створити клієнт ({type(exc).__name__}): {exc}")
'''
    ),

    # ── 4.6 ──────────────────────────────────────────────────────────────
    md(
        """
## 4.6 Rate limits: RPM/ITPM/OTPM

Три незалежні лічильники на клас моделі. Ключова властивість Anthropic: `cache_read_input_tokens`
**не входить** в ITPM (для більшості моделей), тому кешування піднімає фактичну пропускну здатність.

Механізм — **token bucket**: ємність поповнюється безперервно, і ліміт 60 RPM може застосовуватися
як 1 запит на секунду.
"""
    ),
    code(
        '''
ITPM_LIMIT, REQUEST_TOKENS = 2_000_000, 150_000     # Start-тір, великий RAG-запит


class TokenBucket:
    """Ємність = ліміт за хвилину; поповнення = ліміт/60 за секунду."""

    def __init__(self, capacity: float, refill_per_sec: float):
        self.capacity = capacity
        self.refill_per_sec = refill_per_sec
        self.level = 0.0

    def tick(self, seconds: float) -> None:
        self.level = min(self.capacity, self.level + self.refill_per_sec * seconds)

    def take(self, amount: float) -> bool:
        if amount > self.level:
            return False
        self.level -= amount
        return True


bucket = TokenBucket(ITPM_LIMIT, ITPM_LIMIT / 60)
bucket.tick(60)                                  # хвилина простою — бак повний
print(f"після хвилини простою в баці: {bucket.level:,.0f} токенів")

sent = 0
while bucket.take(REQUEST_TOKENS):
    sent += 1
print(f"без пауз пройшло: {sent} запитів ({sent * REQUEST_TOKENS:,} токенів) — далі 429")

bucket.tick(1.0)
print(f"за 1 секунду відновилось: {bucket.refill_per_sec:,.0f}; "
      f"наступний запит пройде: {bucket.take(REQUEST_TOKENS)}")
print(f"чекати на ще один: ~{REQUEST_TOKENS / bucket.refill_per_sec:.1f} с")
'''
    ),
    md(
        """
Тепер планування: скільки запитів на хвилину витримає профіль і який лімітер спрацює першим.
Ліміти — Start-тір, Claude Sonnet 5: 1 000 RPM / 2 000 000 ITPM / 400 000 OTPM.
"""
    ),
    code(
        '''
RPM_LIMIT, ITPM_LIMIT, OTPM_LIMIT = 1_000, 2_000_000, 400_000

RPM_TARGET = 600           # цільовий трафік
AVG_INPUT = 3_500          # середній вхід, токенів
CACHED_PREFIX = 2_400      # незмінна частина (системний промпт + документ)
CACHE_HIT_RATE = 0.80      # частка префікса, що читається з кешу
AVG_OUTPUT = 400

cache_read = int(CACHED_PREFIX * CACHE_HIT_RATE)
cache_creation = CACHED_PREFIX - cache_read
uncached = AVG_INPUT - CACHED_PREFIX

# У ITPM входить УСЕ, крім cache_read: і хвіст, і запис у кеш.
itpm_per_request = uncached + cache_creation
itpm, otpm = RPM_TARGET * itpm_per_request, RPM_TARGET * AVG_OUTPUT

print(f"вхід {AVG_INPUT} = {uncached} без кешу + {cache_creation} запис "
      f"+ {cache_read} читання")
print(f"в ITPM іде {itpm_per_request} токенів на запит")
print(f"{'лімітер':>7} {'факт':>11} {'ліміт':>11} {'зайнято':>8} {'стеля RPM':>10}")
for name, actual, limit in (("RPM", RPM_TARGET, RPM_LIMIT),
                            ("ITPM", itpm, ITPM_LIMIT),
                            ("OTPM", otpm, OTPM_LIMIT)):
    per_request = actual / RPM_TARGET
    print(f"{name:>7} {actual:>11,} {limit:>11,} "
          f"{actual / limit:>7.0%} {int(limit / per_request):>10,}")

limits = (("RPM", RPM_LIMIT, 1), ("ITPM", ITPM_LIMIT, itpm_per_request),
          ("OTPM", OTPM_LIMIT, AVG_OUTPUT))
ceiling = min(int(limit / per) for _, limit, per in limits)
binding = [name for name, limit, per in limits if int(limit / per) == ceiling]
print(f"стеля: {ceiling:,} RPM; вузьке місце — {', '.join(binding)}")
'''
    ),
    code(
        '''
# ПОТРЕБУЄ: ANTHROPIC_API_KEY
if client is None:
    print("Клітинку пропущено: немає ANTHROPIC_API_KEY.")
else:
    try:
        response = client.messages.with_raw_response.create(
            model="claude-opus-5", max_tokens=16,
            messages=[{"role": "user", "content": "ping"}],
        )
        for header in ("anthropic-ratelimit-requests-limit",
                       "anthropic-ratelimit-requests-remaining",
                       "anthropic-ratelimit-input-tokens-remaining",
                       "anthropic-ratelimit-output-tokens-remaining",
                       "retry-after"):
            print(f"{header:44} = {response.headers.get(header)}")
        print()
        print("retry-after приходить лише при 429; при spend cap його немає.")
    except Exception as exc:
        print(f"Помилка виклику API ({type(exc).__name__}): {exc}")
'''
    ),

    # ── самоперевірка ────────────────────────────────────────────────────
    md(
        """
## Самоперевірка

Клітинка перевіряє твердження з розділу. Вона виконується **завжди** — і з ключем, і без нього.
"""
    ),
    code(
        '''
# ── 1. Арифметика usage: input_tokens — це не весь вхід ──────────────────────
assert total_input == 6197, f"очікувалось 6197, отримано {total_input}"
assert usage["input_tokens"] < total_input
print(f"✓ usage: повний вхід {total_input}, input_tokens лише {usage['input_tokens']}")

# ── 2. content-рядок розгортається в один text-блок ──────────────────────────
assert normalized[0]["content"] == [{"type": "text", "text": "Поясни, що таке стрімінг."}]
assert [m["role"] for m in normalized] == ["user", "assistant", "user"]
print("✓ запит: content-рядок нормалізовано, ролі чергуються")

# ── 3. system-хід усередині діалогу — лише для перелічених моделей ───────────
mid = with_mid_system("claude-opus-5", turns, "Далі — лише таблицею.")
assert [m["role"] for m in mid] == ["user", "system", "assistant"]
try:
    with_mid_system("claude-sonnet-4-5", turns, "x")
    raise AssertionError("Sonnet 4.5 не має приймати system-хід у діалозі")
except ValueError:
    pass
print("✓ system: mid-conversation system-хід дозволено лише для 6 моделей")

# ── 4. Кеш-точка стоїть саме на другому блоці ────────────────────────────────
assert system_blocks[1]["cache_control"] == {"type": "ephemeral"}
assert "cache_control" not in system_blocks[0]
print("✓ system: cache_control на останньому незмінному блоці")

# ── 5. SSE: події пораховано, ping не завадив, usage кумулятивний ────────────
assert n == 8, f"очікувалось 8 подій, отримано {n}"
assert unknown == 0, "усі типи подій мають бути відомими"
assert "".join(text) == "Hello!"
assert final_usage == {"output_tokens": 15}
assert blocks == {0: "text"}
print("✓ SSE: 8 подій, ping пропущено без помилки, текст і usage зібрано")

# ── 6. Beta-імена: угода «typically», ім'я без дати — попередження ────────────
warnings = check_betas(DOCUMENTED_BETAS)
assert warnings == ["user-profiles: без дати у назві — звірте з документацією"]
try:
    check_betas(["Not A Beta Name"])
    raise AssertionError("хибне beta-ім'я мусить давати ValueError")
except ValueError:
    pass
print("✓ beta: список перевірено, хибний формат відхилено, ім'я без дати — WARN")

# ── 7. Застарілі sampling-параметри прибираються для нових моделей ───────────
assert "temperature" not in sanitize({"model": "claude-opus-5", "temperature": 0.2})
assert "temperature" in sanitize({"model": "claude-sonnet-4-5", "temperature": 0.2})
print("✓ сумісність: temperature прибрано для Opus 5, залишено для Sonnet 4.5")

# ── 8. Класифікація помилок відповідає документації SDK ──────────────────────
assert is_retryable(connection_error=True)
for status in (408, 409, 429, 500, 529):
    assert is_retryable(status=status), f"{status} має ретраїтися"
for status in (400, 401, 403, 404, 413):
    assert not is_retryable(status=status), f"{status} не має ретраїтися"
print("✓ помилки: 408/409/429/>=500 ретраяться, 4xx (крім цих) — ні")

# ── 9. Стеля паузи застосовується після джиттера, retry-after її скасовує ────
for rejitter in range(50):
    delay = backoff_delay(9, rng=random.Random(rejitter))
    assert delay <= 8.0, f"пауза {delay} перевищила стелю cap=8.0"
assert backoff_delay(9, rng=random.Random(1)) == 8.0
assert backoff_delay(3, retry_after=30) == 30.0
print("✓ відкат: пауза ніколи не перевищує cap, retry-after має приоритет")

# ── 10. Token bucket: сплеск вичерпує бак, потім треба чекати ────────────────
assert sent == 13, f"очікувалось 13 запитів без пауз, отримано {sent}"
assert sent * REQUEST_TOKENS <= ITPM_LIMIT
assert (sent + 1) * REQUEST_TOKENS > ITPM_LIMIT
print(f"✓ ліміти: {sent} запитів по {REQUEST_TOKENS:,} токенів вичерпують бак 2M ITPM")

# ── 11. Планування: вузьке місце — RPM і OTPM, а не ITPM ─────────────────────
assert itpm_per_request == 1580
assert itpm == 948_000 and otpm == 240_000
assert ceiling == 1_000 and set(binding) == {"RPM", "OTPM"}
assert itpm < ITPM_LIMIT, "ITPM має бути недовантажений завдяки кешу"
print(f"✓ планування: стеля {ceiling:,} RPM, ITPM зайнято лише "
      f"{itpm / ITPM_LIMIT:.0%}")

print()
print("Усі перевірки пройдено.")
'''
    ),

    # ── підсумок ─────────────────────────────────────────────────────────
    md(
        """
## Підсумок

1. **Messages API — stateless.** Уся історія надсилається щоразу, тому вартість зростає з кожним
   ходом діалогу.
2. **`input_tokens` — це не весь вхід.** Повний вхід дорівнює
   `cache_read + cache_creation + input_tokens`. У прикладі з довідки різниця — утричі.
3. **Відповідь читають фільтром за типом блоку**, а не за індексом: з увімкненим мисленням першим
   може йти блок `thinking` з порожнім полем `thinking`.
4. **`stop_reason` — сигнал, а не помилка.** Сім значень вимагають семи різних дій, і
   `model_context_window_exceeded` не лікується проханням «продовж».
5. **Системний промпт має два вкладення.** Top-level `system` формує кешований префікс; system-хід
   усередині діалогу можливий лише для шести моделей, але не інвалідує префікс перед собою.
6. **У стрімінгу `usage` кумулятивний, а `stop_reason` у `message_start` — `null`.** Невідомі типи
   подій треба ігнорувати: політика версіонування прямо дозволяє додавати нові.
7. **Помилка може прийти після 200 OK** — подією `event: error`. Обробник мусить мати два входи.
8. **429 буває трьох видів.** Ліміт швидкості має `retry-after`, spend cap — ні (повтори безглузді),
   власний ліміт витрат приходить як 400.
9. **SDK уже робить 2 повтори.** Власний шар ретраїв потрібен лише для іншої логіки — черги,
   зниження моделі, бюджету.
10. **`retry-after` скасовує експоненційну формулу**, а стеля паузи застосовується **після**
    джиттера.
11. **Кешовані токени не входять в ITPM**, тому кешування піднімає не лише економію, а й пропускну
    здатність: у розрахунку ITPM зайнято 47%, а стелю визначають RPM і OTPM.
12. **Ліміти задані на клас моделей і на тір**, а кошики Opus 4.x і Sonnet 4.x — спільні.

**Куди далі:**

- Розділ 3 — токени, `count_tokens` і контекстне вікно.
- Розділ 6 — вибір моделі, псевдоніми й датовані снапшоти.
- Розділ 8 — мислення, `effort` і збереження блоків `thinking`.
- Розділ 9 — prompt caching і діагностика промахів.
- Розділ 10 — Message Batches API з окремими лімітами.
- Розділ 12 — tool use і цикл агента (`stop_reason: "tool_use"`).
- Розділ 25 — SSE-сервінг, відкати й деградація під навантаженням.

## Джерела

- [Anthropic — Messages API](https://platform.claude.com/docs/en/api/messages)
- [Anthropic — API overview](https://platform.claude.com/docs/en/api/overview)
- [Anthropic — Versions](https://platform.claude.com/docs/en/api/versioning)
- [Anthropic — Beta headers](https://platform.claude.com/docs/en/api/beta-headers)
- [Anthropic — Streaming messages](https://platform.claude.com/docs/en/build-with-claude/streaming)
- [Anthropic — Using the Messages API](https://platform.claude.com/docs/en/build-with-claude/working-with-messages)
- [Anthropic — Claude API errors](https://platform.claude.com/docs/en/api/errors)
- [Anthropic — Rate limits](https://platform.claude.com/docs/en/api/rate-limits)
- [Anthropic — Python SDK](https://platform.claude.com/docs/en/cli-sdks-libraries/sdks/python)
- [Anthropic — Stop reasons and fallback](https://platform.claude.com/docs/en/build-with-claude/handling-stop-reasons)
- Локальні знімки джерел: `research/02/messages-api.md`, `research/02/streaming.md`,
  `research/02/versioning.md`, `research/02/working-with-messages.md`, `research/02/overload.md`,
  `research/02/rate-limits.md`, `research/02/python-sdk.md`, `research/02/api-overview.md`,
  `research/02/beta-headers.md`, `research/02/handling-stop-reasons.md`
"""
    ),
]
