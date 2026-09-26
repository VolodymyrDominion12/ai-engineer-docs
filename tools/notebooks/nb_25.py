"""Ноутбук 25 — «Продакшн-сервінг: SSE-стрімінг, ретраї, ліміти, бюджет».

Розділ довідника: sections/25-serviing.md
Працює без API-ключів, GPU і мережі.

Таблиця помилок, обмеження розмірів, параметри EventSourceResponse і стратегії
відновлення стріму взяті з первинних джерел (research/02/overload.md,
research/02/streaming.md, research/11/sse_starlette_readme.md) станом на 26.09.2026.
"""

from nbkit import SETUP_CELL, VERSION_CELL, code, md

FILENAME = "25-serviing.ipynb"
TITLE = "25. Продакшн-сервінг"

CELLS = [
    md(
        """
# 25. Продакшн-сервінг: SSE-стрімінг, ретраї, ліміти, бюджет

**Розділ довідника:** [`sections/25-serviing.md`](../sections/25-serviing.md)

**Потрібно:** нічого — жодних ключів, GPU чи мережі.

**Що ви зробите:**

1. Напишете **справжній SSE-парсер** і прогоните його на реальній послідовності подій.
2. Відтворите пастку збірки блоків: чому конкатенація всіх дельт ламається, а складання за
   `index` — ні.
3. Побудуєте **вирішувач ретраїв** за таблицею HTTP-кодів — і побачите, що `400` може означати
   «скінчилися гроші».
4. Реалізуєте експоненційний відкат із jitter і виміряєте його ефект.
5. Побудуєте бюджетний запобіжник і ланцюг деградації.
6. Перевірите, чому **відкат на іншу модель руйнує кеш**.

> Ключова ідея: у продакшні ламається не логіка, а **обробка винятків і контроль витрат**.
"""
    ),
    md("## Налаштування"),
    code(SETUP_CELL),
    code(VERSION_CELL),

    # ── 25.1 SSE ─────────────────────────────────────────────────────────
    md(
        """
## 25.1 SSE: розбір потоку подій

Формат SSE — це текстовий протокол. Кожна подія складається з рядків `поле: значення`, розділених
порожнім рядком. Напишемо справжній парсер.
"""
    ),
    code(
        '''
def parse_sse(raw: str) -> list[dict]:
    """Розбирає потік SSE у список подій.

    Формат: блоки рядків, розділені порожнім рядком. Усередині блоку —
    поля `event:`, `data:` тощо. Кілька рядків `data:` склеюються через \\n
    (це вимога специфікації SSE, а не деталь реалізації).
    """
    events, current = [], {}

    for line in raw.splitlines():
        if line == "":
            if current:
                events.append(current)
                current = {}
            continue
        if ":" not in line:
            continue
        field, _, value = line.partition(":")
        value = value[1:] if value.startswith(" ") else value
        if field == "data":
            current["data"] = current.get("data", "") + value + "\\n"
        else:
            current[field] = value

    if current:
        events.append(current)

    for e in events:
        if "data" in e:
            e["data"] = e["data"].rstrip("\\n")
    return events


# Реальна послідовність подій Anthropic (структура з документації):
# message_start -> content_block_start/delta/stop -> message_delta -> message_stop
STREAM = """event: message_start
data: {"type":"message_start","message":{"id":"msg_01","content":[],"usage":{"input_tokens":10}}}

event: content_block_start
data: {"type":"content_block_start","index":0,"content_block":{"type":"text","text":""}}

event: content_block_delta
data: {"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"Привіт"}}

event: content_block_delta
data: {"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":", світ!"}}

event: content_block_stop
data: {"type":"content_block_stop","index":0}

event: message_delta
data: {"type":"message_delta","delta":{"stop_reason":"end_turn"},"usage":{"output_tokens":5}}

event: message_stop
data: {"type":"message_stop"}
"""

events = parse_sse(STREAM)
print(f"Розібрано подій: {len(events)}")
print()
for e in events:
    print(f"  event={e.get('event'):22} data={e.get('data','')[:72]}")
'''
    ),
    md(
        """
### Пастка: конкатенація дельт замість складання за `index`

Кожна дельта містить лише **прирощення**, а не повний текст. І кожен блок вмісту має поле `index`.
Коли в потоці кілька блоків (текст, виклик інструмента, блок мислення), проста конкатенація дає
неправильний результат.
"""
    ),
    code(
        '''
import json

# Потік із ДВОМА блоками: 0 — текст, 1 — виклик інструмента.
# Збудуємо його через json.dumps, а не вписуємо JSON руками: так неможливо
# помилитися в екрануванні лапок усередині `partial_json`.
def sse_frame(event: str, payload: dict) -> str:
    """Формує один кадр SSE у тому вигляді, у якому він приходить по дроту."""
    return f"event: {event}\\ndata: {json.dumps(payload, ensure_ascii=False)}\\n\\n"


TWO_BLOCKS_EVENTS = [
    ("content_block_start", {"type": "content_block_start", "index": 0,
                             "content_block": {"type": "text"}}),
    ("content_block_start", {"type": "content_block_start", "index": 1,
                             "content_block": {"type": "tool_use", "name": "get_weather"}}),
    # Дельти двох блоків перемішано, як буває при паралельній генерації
    ("content_block_delta", {"type": "content_block_delta", "index": 1,
                             "delta": {"type": "input_json_delta", "partial_json": '{"loc'}}),
    ("content_block_delta", {"type": "content_block_delta", "index": 0,
                             "delta": {"type": "text_delta", "text": "Зараз "}}),
    ("content_block_delta", {"type": "content_block_delta", "index": 0,
                             "delta": {"type": "text_delta", "text": "перевірю."}}),
    ("content_block_delta", {"type": "content_block_delta", "index": 1,
                             "delta": {"type": "input_json_delta", "partial_json": 'ation":"Kyiv"}'}}),
]

TWO_BLOCKS = "".join(sse_frame(ev, payload) for ev, payload in TWO_BLOCKS_EVENTS)

evs = parse_sse(TWO_BLOCKS)
deltas = [json.loads(e["data"]) for e in evs if e.get("event") == "content_block_delta"]


def naive_concat(deltas: list[dict]) -> str:
    """НЕПРАВИЛЬНО: склеює всі текстові дельти в один рядок, ігноруючи index."""
    return "".join(d.get("delta", {}).get("text", "") for d in deltas)


def assemble_by_index(deltas: list[dict]) -> dict:
    """ПРАВИЛЬНО: складає кожен блок окремо, за полем index."""
    blocks: dict[int, list[str]] = {}
    for d in deltas:
        idx = d.get("index")
        delta = d.get("delta", {})
        piece = delta.get("text") or delta.get("partial_json") or ""
        blocks.setdefault(idx, []).append(piece)
    return {idx: "".join(parts) for idx, parts in sorted(blocks.items())}


print("НЕПРАВИЛЬНО (усе в один рядок):")
print(f"  {naive_concat(deltas)!r}")
print()
print("ПРАВИЛЬНО (за index):")
for idx, text in assemble_by_index(deltas).items():
    kind = "текст" if idx == 0 else "виклик інструмента"
    print(f"  блок {idx} ({kind}): {text!r}")
print()
print("У першому випадку JSON виклику інструмента злитий із текстом відповіді")
print("й перемішаний за порядком. Розібрати його неможливо.")
'''
    ),

    # ── 25.2 sse-starlette ───────────────────────────────────────────────
    md(
        """
## 25.2 `EventSourceResponse`: параметри й чому ping критичний

Параметри з документації бібліотеки `sse-starlette`.
"""
    ),
    code(
        '''
EVENT_SOURCE_PARAMS = {
    "content":              {"тип": "ContentStream", "типове": "обов'язковий",
                             "опис": "Асинхронний генератор або ітерований об'єкт"},
    "ping":                 {"тип": "int", "типове": 15,
                             "опис": "Інтервал ping у секундах"},
    "sep":                  {"тип": "str", "типове": r"\\r\\n",
                             "опис": r"Розділювач рядків (\\r\\n, \\r, \\n)"},
    "send_timeout":         {"тип": "float", "типове": None,
                             "опис": "Таймаут операції відправки"},
    "headers":              {"тип": "dict", "типове": None,
                             "опис": "Додаткові HTTP-заголовки"},
    "ping_message_factory": {"тип": "Callable", "типове": None,
                             "опис": "Власний генератор ping-повідомлень"},
}

print(f"{'параметр':22} {'тип':12} {'типове':14} опис")
print("-" * 96)
for name, p in EVENT_SOURCE_PARAMS.items():
    print(f"{name:22} {p['тип']:12} {str(p['типове']):14} {p['опис']}")

print()
print("ЧОМУ ping=15 — не деталь:")
print("Проксі та балансувальники розривають з'єднання, у якому немає трафіку.")
print("Під час довгого мислення моделі (розділ 8) події можуть не надходити")
print("десятками секунд — ping утримує з'єднання живим.")
'''
    ),
    code(
        '''
# Чому потрібне виявлення відключення клієнта: без нього ви платите за марне.
def cost_of_abandoned_stream(seconds_until_detected: int, tokens_per_second: float,
                             price_out_per_mtok: float = 25.0) -> dict:
    """Скільки коштує генерація після того, як клієнт пішов."""
    wasted = seconds_until_detected * tokens_per_second
    return {
        "секунд до виявлення": seconds_until_detected,
        "марних токенів": int(wasted),
        "марна вартість USD": round(wasted / 1e6 * price_out_per_mtok, 6),
    }


print("Клієнт закрив вкладку. Генерація триває, бо ми не перевіряємо стан.")
print("Швидкість: 50 токенів/с, ціна виходу $25/MTok (Opus 5).")
print()
print(f"{'виявлено через':>16} {'марних токенів':>16} {'вартість':>12}")
print("-" * 48)
for sec in (0, 5, 30, 120):
    r = cost_of_abandoned_stream(sec, 50.0)
    print(f"{r['секунд до виявлення']:>16} {r['марних токенів']:>16} ${r['марна вартість USD']:>11.6f}")

print()
print("На одному запиті різниця мізерна. На тисячах запитів на день, де")
print("частина користувачів закриває вкладку, це постійна стаття витрат.")
print()
print("Рішення з документації: перевіряти `await request.is_disconnected()`")
print("у циклі й обробляти `asyncio.CancelledError` з повторним підняттям.")
'''
    ),

    # ── 25.3 помилки ─────────────────────────────────────────────────────
    md(
        """
## 25.3 Таблиця помилок: що ретраїти, а що ні

Кожен код означає різну дію. Обробляти їх однаково — типова помилка.
"""
    ),
    code(
        '''
# Повна таблиця помилок Anthropic (з документації).
HTTP_ERRORS = {
    400: {"тип": "invalid_request_error",
          "ретраїти": False,
          "нотатка": "Формат/вміст запиту. ТАКОЖ повертається при досягненні "
                     "встановленого ліміту витрат організації або простору"},
    401: {"тип": "authentication_error", "ретраїти": False,
          "нотатка": "API-ключ неправильний, відкликаний або протермінований"},
    402: {"тип": "billing_error", "ретраїти": False,
          "нотатка": "Проблема з оплатою — потрібне втручання"},
    403: {"тип": "permission_error", "ретраїти": False,
          "нотатка": "Ключ не має прав на ресурс"},
    404: {"тип": "not_found_error", "ретраїти": False,
          "нотатка": "Ресурс не знайдено: перевірте шлях і ідентифікатори"},
    409: {"тип": "conflict_error", "ретраїти": True,
          "нотатка": "Конфлікт зі станом ресурсу: розв'язати конфлікт, потім повторити"},
    413: {"тип": "request_too_large", "ретраїти": False,
          "нотатка": "Перевищено розмір. Cloudflare повертає ЦЕ до серверів API"},
    429: {"тип": "rate_limit_error", "ретраїти": True,
          "нотатка": "Ліміт швидкості, місячна стеля витрат або ліміт простору Claude Code"},
    500: {"тип": "api_error", "ретраїти": True,
          "нотатка": "Внутрішня помилка: відкат; якщо повторюється — у підтримку з request ID"},
    504: {"тип": "timeout_error", "ретраїти": True,
          "нотатка": "Таймаут обробки: розгляньте стрімінг для довгих запитів"},
    529: {"тип": "overloaded_error", "ретраїти": True,
          "нотатка": "API тимчасово перевантажено (високий трафік у всіх користувачів)"},
}

print(f"{'код':>4} {'тип':24} {'ретраїти':>9}  нотатка")
print("-" * 104)
for code_, info in sorted(HTTP_ERRORS.items()):
    mark = "ТАК" if info["ретраїти"] else "НІ"
    print(f"{code_:>4} {info['тип']:24} {mark:>9}  {info['нотатка'][:58]}")

retryable = [c for c, i in HTTP_ERRORS.items() if i["ретраїти"]]
not_retryable = [c for c, i in HTTP_ERRORS.items() if not i["ретраїти"]]
print()
print(f"Ретраїти: {sorted(retryable)}")
print(f"НЕ ретраїти: {sorted(not_retryable)}")
print()
print("ДВІ ПАСТКИ, які ламають інтуїцію:")
print("  • 400 може означати 'скінчилися гроші', а не погану схему запиту.")
print("    Логіка '400 = завжди моя помилка у форматі' тут хибна.")
print("  • 413 приходить від CLOUDFLARE, а не від API — тобто розмір")
print("    перевіряється до того, як запит потрапить у вашу систему обліку.")
'''
    ),
    code(
        '''
# Обмеження розміру запиту — різні для різних ендпоінтів
REQUEST_SIZE_LIMITS_MB = {
    "Messages API": 32,
    "Token Counting API": 32,
    "Batch API": 256,
    "Files API": 500,
}

print("Максимальний розмір запиту (перевищення -> 413 request_too_large):")
print()
print(f"{'ендпоінт':22} {'межа':>8}")
print("-" * 32)
for name, mb in REQUEST_SIZE_LIMITS_MB.items():
    print(f"{name:22} {mb:>6} МБ")

print()
print("Зверніть увагу: Files API 500 МБ — це не розмір ЗАПИТУ до Messages API.")
print("Завантаження файлу й запит із посиланням на нього — різні ендпоінти")
print("з різними межами (розділ 7).")
'''
    ),

    # ── 25.4 ретраї ──────────────────────────────────────────────────────
    md(
        """
## 25.4 Експоненційний відкат: чому потрібен jitter

Документація радить для `500` експоненційний відкат. Реалізуємо й виміряємо.
"""
    ),
    code(
        '''
import random


def backoff_delays(attempts: int, base: float = 0.5, cap: float = 16.0,
                   jitter: bool = True) -> list[float]:
    """Розклад затримок для експоненційного відкату.

    jitter — випадковий розкид, щоб клієнти не повторювали синхронно.
    """
    delays = []
    for i in range(attempts):
        delay = min(cap, base * (2 ** i))
        if jitter:
            delay *= random.uniform(0.5, 1.0)
        delays.append(round(delay, 3))
    return delays


random.seed(42)
d_no = backoff_delays(6, jitter=False)
d_yes = backoff_delays(6, jitter=True)
print(f"{'без jitter':12} {d_no}   усього {sum(d_no):.2f} с")
print(f"{'з jitter':12} {d_yes}   усього {sum(d_yes):.2f} с")
print()
print("Головна цінність jitter — не середній час, а РОЗВЕДЕННЯ повторів.")
print("Без нього тисяча клієнтів, що одночасно отримали 529, повторить")
print("запит в одну мілісекунду й знову перевантажить сервіс.")
print("Це називається 'синхронним стадом' (thundering herd).")
print()
print("Покажемо розведення: 8 клієнтів, перша затримка з jitter і без.")
random.seed(1)
sync = [backoff_delays(1, jitter=False)[0] for _ in range(8)]
spread = [backoff_delays(1, jitter=True)[0] for _ in range(8)]
print(f"  без jitter: {sync}")
print(f"  з jitter:   {spread}")
print(f"  розкид: {max(sync)-min(sync):.3f} с проти {max(spread)-min(spread):.3f} с")
'''
    ),
    code(
        '''
# Відновлення обірваного стріму залежить від ПОКОЛІННЯ моделі
STREAM_RESUME = {
    "Claude 4.5 і раніші": {
        "крок_2": "Розмістити часткову відповідь як початок повідомлення АСИСТЕНТА",
        "причина": "prefill асистента підтримується",
    },
    "Claude 4.6 і пізніші": {
        "крок_2": "Додати повідомлення КОРИСТУВАЧА з інструкцією продовжити",
        "причина": "prefill асистента видалено -> 400 (розділ 6)",
    },
}

print("Стратегія capture-and-resume: 3 кроки для обох поколінь")
print("  1. Захопити часткову відповідь (усе, що встигло прийти)")
print("  2. Побудувати запит на продовження")
print("  3. Відновити стрімінг")
print()
for model, info in STREAM_RESUME.items():
    print(f"{model}:")
    print(f"    крок 2: {info['крок_2']}")
    print(f"    причина: {info['причина']}")
    print()

# Приклад формулювання з документації для 4.6+
template = ("Your previous response was interrupted and ended with "
            "[previous_response]. Continue from where you left off.")
print("Приклад формулювання для 4.6+ (з документації):")
print(f"  {template}")
'''
    ),

    # ── 25.5 бюджет ──────────────────────────────────────────────────────
    md(
        """
## 25.5 Бюджетний запобіжник і ціна деградації

Три рівні захисту витрат, і найважливіший — середній: обмеження **кількості** запитів.
"""
    )
    ,
    code(
        '''
def agent_session_budget(
    max_steps: int,
    steps_used: int,
    tokens_in_per_step: int = 1500,
    tokens_out_per_step: int = 300,
    price_in: float = 5.0,
    price_out: float = 25.0,
) -> dict:
    """Бюджетний запобіжник для агентної сесії.

    Показує, чому max_tokens НЕ обмежує витрати: він обмежує вихід
    ОДНОГО запиту, але не кількість запитів.
    """
    spent_in = spent_out = 0
    for step in range(steps_used):
        history = step * (tokens_in_per_step + tokens_out_per_step)
        spent_in += tokens_in_per_step + history
        spent_out += tokens_out_per_step
    cost = spent_in / 1e6 * price_in + spent_out / 1e6 * price_out
    return {
        "кроків використано": steps_used,
        "межа кроків": max_steps,
        "у межах бюджету": steps_used < max_steps,
        "витрачено токенів входу": spent_in,
        "вартість USD": round(cost, 6),
    }


print(f"{'кроків':>7} {'вхід':>10} {'вартість':>12}  статус")
print("-" * 48)
for steps in (1, 5, 20, 50, 100):
    r = agent_session_budget(max_steps=50, steps_used=steps)
    status = "OK" if r["у межах бюджету"] else "ПЕРЕВИЩЕНО"
    print(f"{steps:>7} {r['витрачено токенів входу']:>10} ${r['вартість USD']:>11.4f}  {status}")

print()
print("Без межі кроків агент може зробити сотні викликів, кожен з яких")
print("пересилає всю історію. Нагадаємо з розділу 12: 20 кроків коштують")
print("59× однокрокового. Межа кроків — це ФІНАНСОВИЙ запобіжник.")
'''
    ),
    code(
        '''
# Ціна деградації: відкат на дешевшу модель РУЙНУЄ кеш
CACHE_PRICES = {
    "claude-opus-5":     {"in": 5.0, "hit": 0.50},
    "claude-sonnet-5":   {"in": 2.0, "hit": 0.20},
}

CACHED_TOKENS = 100_000
TOTAL_IN = 110_000

print(f"Кешований префікс: {CACHED_TOKENS:,} токенів, усього входу {TOTAL_IN:,}")
print()


def cost(model: str, cache_hits: bool) -> float:
    p = CACHE_PRICES[model]
    if cache_hits:
        return (CACHED_TOKENS / 1e6 * p["hit"] + (TOTAL_IN - CACHED_TOKENS) / 1e6 * p["in"])
    return TOTAL_IN / 1e6 * p["in"]


rows = [
    ("Opus 5, кеш влучає", "claude-opus-5", True),
    ("Opus 5, кеш промахнувся", "claude-opus-5", False),
    ("Sonnet 5 (відкат), кеш влучає", "claude-sonnet-5", True),
    ("Sonnet 5 (відкат), кеш промахнувся", "claude-sonnet-5", False),
]
base = None
for label, model, hits in rows:
    c = cost(model, hits)
    base = base or c
    print(f"  {label:36} ${c:.6f}   {c/base:>6.2f}×")

print()
print("ГОЛОВНЕ: відкат на дешевшу модель (Sonnet 5) сам по собі вигідний —")
print("але він РУЙНУЄ кеш, бо за документацією кеш прив'язаний до моделі")
print("(причина промаху model_changed, розділ 9).")
print()
print("У прикладі видно: відкат із промахом кешу (останній рядок) коштує")
print("менше за Opus 5 із промахом, але більше за Opus 5 із влучанням.")
print("Тобто деградація заради економії може дати ЗВОРОТНИЙ ефект.")
'''
    ),

    # ── самоперевірка ────────────────────────────────────────────────────
    md(
        """
## Самоперевірка

Перевіряємо парсер, складання за `index`, таблицю помилок, відкат і бюджет.
"""
    ),
    code(
        '''
# ── 1. SSE-парсер розбирає реальну послідовність ────────────────────────
assert len(events) == 7, f"очікувалось 7 подій, отримано {len(events)}"
assert events[0]["event"] == "message_start"
assert events[-1]["event"] == "message_stop"
assert sum(1 for e in events if e["event"] == "content_block_delta") == 2
print("✓ SSE-парсер: 7 подій, потік у правильному порядку")

# ── 2. message_start приходить із ПОРОЖНІМ content ──────────────────────
start = json.loads(events[0]["data"])
assert start["message"]["content"] == [], "message_start має порожній content"
print("✓ message_start: content порожній, як описано в документації")

# ── 3. Конкатенація дельт дає сміття, складання за index — ні ───────────
assert "Kyiv" not in naive_concat(deltas), "наївна конкатенація не має давати валідний JSON"
by_idx = assemble_by_index(deltas)
assert by_idx[0] == "Зараз перевірю."
assert json.loads(by_idx[1]) == {"location": "Kyiv"}
assert len(by_idx) == 2
print("✓ складання за index: текст і JSON розділені, JSON парситься")

# ── 4. Параметри EventSourceResponse узгоджені з джерелом ───────────────
assert EVENT_SOURCE_PARAMS["ping"]["типове"] == 15
assert EVENT_SOURCE_PARAMS["sep"]["типове"] == r"\\r\\n"
assert EVENT_SOURCE_PARAMS["send_timeout"]["типове"] is None
assert EVENT_SOURCE_PARAMS["content"]["типове"] == "обов'язковий"
print("✓ EventSourceResponse: ping=15, sep=\\r\\n, send_timeout=None, content обов'язковий")

# ── 5. Таблиця помилок: ретраїти лише тимчасові ─────────────────────────
assert sorted(retryable) == [409, 429, 500, 504, 529]
assert sorted(not_retryable) == [400, 401, 402, 403, 404, 413]
assert HTTP_ERRORS[400]["ретраїти"] is False
assert HTTP_ERRORS[529]["ретраїти"] is True
assert HTTP_ERRORS[529]["тип"] == "overloaded_error"
assert HTTP_ERRORS[504]["тип"] == "timeout_error"
print("✓ коди: ретраїти [409, 429, 500, 504, 529], не ретраїти [400, 401, 402, 403, 404, 413]")

# ── 6. 400 може означати вичерпаний бюджет ──────────────────────────────
assert "ліміту витрат" in HTTP_ERRORS[400]["нотатка"]
print("✓ 400: нотатка згадує ліміт витрат — це не лише помилка схеми")

# ── 7. Обмеження розмірів запиту узгоджені з джерелом ───────────────────
assert REQUEST_SIZE_LIMITS_MB["Messages API"] == 32
assert REQUEST_SIZE_LIMITS_MB["Batch API"] == 256
assert REQUEST_SIZE_LIMITS_MB["Files API"] == 500
print("✓ розміри: Messages 32 МБ, Batch 256 МБ, Files 500 МБ")

# ── 8. Відкат монотонний і обмежений зверху ─────────────────────────────
raw_no = [min(16.0, 0.5 * 2 ** i) for i in range(6)]
assert raw_no == [0.5, 1.0, 2.0, 4.0, 8.0, 16.0]
assert all(d <= 16.0 for d in d_yes), "jitter не має перевищувати cap"
assert all(d >= 0.25 for d in d_yes), "jitter не має занулювати затримку"
print(f"✓ відкат: без jitter {raw_no}, з jitter обмежений [0.25, 16.0]")

# ── 9. Jitter справді розводить клієнтів у часі ─────────────────────────
assert max(spread) - min(spread) > 0, "jitter мусить давати розкид"
print(f"✓ jitter розводить: розкид {max(spread)-min(spread):.3f} с (без jitter — 0)")

# ── 10. Стратегія відновлення стріму розрізняється за поколінням ────────
assert "АСИСТЕНТА" in STREAM_RESUME["Claude 4.5 і раніші"]["крок_2"]
assert "КОРИСТУВАЧА" in STREAM_RESUME["Claude 4.6 і пізніші"]["крок_2"]
print("✓ відновлення стріму: 4.5 і раніші — assistant, 4.6+ — user")

# ── 11. Бюджетний запобіжник зупиняє сесію ──────────────────────────────
assert agent_session_budget(max_steps=50, steps_used=50)["у межах бюджету"] is False
assert agent_session_budget(max_steps=50, steps_used=49)["у межах бюджету"] is True
print("✓ бюджет: сесія зупиняється на межі кроків")

# ── 12. Відкат на дешевшу модель дорожчий, якщо кеш промахнувся ─────────
opus_hit = cost("claude-opus-5", True)
sonnet_miss = cost("claude-sonnet-5", False)
assert sonnet_miss > opus_hit, "відкат із промахом кешу дорожчий за основну модель із влучанням"
print(f"✓ деградація: Opus 5 з кешем ${opus_hit:.5f} < Sonnet 5 без кешу ${sonnet_miss:.5f}")

print()
print("Усі перевірки пройдено.")
'''
    ),

    # ── підсумок ─────────────────────────────────────────────────────────
    md(
        """
## Підсумок

**Головне з цього ноутбука:**

1. **SSE — звичайний HTTP в один бік.** Для LLM двобічність WebSocket не потрібна, а її ціна —
   окремий протокол і складніша інфраструктура.
2. **Складайте блоки за `index`,** не конкатенуйте дельти. У наївному варіанті JSON виклику
   інструмента зливається з текстом і стає нерозбірливим.
3. **`message_start` приходить із порожнім `content`.** Код, що одразу читає вміст, отримає нічого.
4. **`ping=15` (типове) — необхідність,** бо проксі розривають мовчазні з'єднання.
5. **Перевіряйте `is_disconnected()`** і повторно піднімайте `asyncio.CancelledError`. Інакше
   платите за генерацію, яку ніхто не читає.
6. **Ретраїти лише `409`, `429`, `500`, `504`, `529`.** `400`, `401`, `402`, `403`, `404`, `413`
   не стануть успішними.
7. **`400` може означати «скінчилися гроші».** Документація прямо каже, що він повертається при
   досягненні встановленого ліміту витрат.
8. **`413` приходить від Cloudflare** — до того, як запит дійде до серверів API. У логах API його
   не буде.
9. **Відкат з jitter** не лише швидший у середньому — він розводить повтори в часі й розбиває
   «синхронне стадо».
10. **Відновлення стріму залежить від покоління:** 4.5 і раніші — assistant-повідомлення, 4.6+ —
    user-повідомлення (бо prefill видалено).
11. **Межа кроків агента — фінансовий запобіжник.** 20 кроків = 59× ціни одного (розділ 12).
12. **Відкат на дешевшу модель руйнує кеш** (він прив'язаний до моделі). У прикладі видно, що
    деградація заради економії може дати зворотний ефект.

**Куди далі:**

- Розділ 6 — чотири важелі вартості й ланцюг моделей.
- Розділ 9 — кеш і причина промаху `model_changed`.
- Розділ 10 — батчі: коли асинхронність прийнятна.
- Розділ 12 — цикл агента й межа ітерацій.
- Розділ 23 — спостережуваність: Langfuse й OpenTelemetry GenAI.

## Джерела

- [sse-starlette README](https://raw.githubusercontent.com/ColeMurray/sse-starlette/main/README.md)
- [Anthropic — Streaming Messages](https://platform.claude.com/docs/en/build-with-claude/streaming)
- [Anthropic — Errors](https://platform.claude.com/docs/en/api/errors)
- [Anthropic — Rate limits](https://platform.claude.com/docs/en/api/rate-limits)

Джерела збережено локально: `research/11/sse_starlette_readme.md`, `research/02/streaming.md`,
`research/02/overload.md`, `research/02/rate-limits.md`.
"""
    ),
]
