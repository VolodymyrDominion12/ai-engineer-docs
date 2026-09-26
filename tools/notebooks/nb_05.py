"""Ноутбук 05 — «OpenAI API та сумісні провайдери».

Розділ довідника: sections/05-openai-api.md
Працює без API-ключа: клітинки з реальними викликами перевіряють наявність
OPENAI_API_KEY (або ключа сумісного провайдера) і друкують пояснення, якщо
ключа немає. Уся аналітика — парсинг changelog, таблиць цін, таблиці помилок —
виконується на локальних знімках джерел у research/.
"""

from nbkit import SETUP_CELL, code, md

FILENAME = "05-openai-api.ipynb"
TITLE = "5. OpenAI API"

CELLS = [
    md(
        """
# 05. OpenAI API та сумісні провайдери

**Розділ довідника:** [`sections/05-openai-api.md`](../sections/05-openai-api.md)

**Потрібно: OPENAI_API_KEY (опційно — більшість клітинок працює без ключа)**

Скопіюйте `.env.example` у `.env` і впишіть ключ (`cp .env.example .env`), якщо хочете виконати
клітинки з реальними викликами. Решта ноутбука виконується завжди: вона працює на локальних знімках
документації в `research/`, а не на мережі.

**Що ви зробите:**

1. Порівняєте Chat Completions і Responses на рівні форми запиту й побачите, чому другий хід у
   кожному з них виглядає по-різному.
2. Напишете парсер changelog OpenAI і дістанете статистику, яку неможливо отримати очима за 170
   записів: розподіл за типами подій і найактивніші ендпоінти.
3. Побудуєте фільтр «що змінилося саме в моїх моделях» і звірите версію Python SDK із PyPI.
4. Складете таблицю кодів помилок і вирішувач «ретраїти чи ні» — з кількісним підсумком, скільки
   помилок не лікується повторною спробою.
5. Розрахуєте розклад відкату, який поважає `Retry-After`, і бюджет запитів за заголовками лімітів.
6. Порівняєте OpenAI-сумісні ендпоінти чотирьох провайдерів і перевірите свою JSON-схему на
   сумісність зі Structured Outputs.
7. Порахуєте вартість одного фіксованого навантаження в 12 конфігураціях чотирьох провайдерів.
"""
    ),
    md("## Налаштування"),
    code(SETUP_CELL),
    code(
        '''
# Версії бібліотек, використаних у цьому ноутбуку (для відтворюваності).
import importlib

for _name in ("nbformat", "openai", "dotenv", "tenacity"):
    try:
        _mod = importlib.import_module(_name)
        print(f"{_name:12} {getattr(_mod, '__version__', '?')}")
    except ImportError:
        print(f"{_name:12} НЕ ВСТАНОВЛЕНО (для цього ноутбука не обов'язково)")
'''
    ),
    md(
        """
### Ключ (необов'язковий)

Ключ читається **тільки** з `.env` або змінних середовища — у коді ноутбука його немає. Клітинки з
реальними викликами перевіряють його наявність і друкують пояснення, якщо ключа немає.
"""
    ),
    code(
        '''
# Читання ключів. Ноутбук виконується й без них.
import os

try:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
    print("python-dotenv: читаю .env (якщо файл існує)")
except ImportError:
    print("python-dotenv не встановлено — читаю лише змінні середовища")

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "").strip()
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()

for _var, _value in (("OPENAI_API_KEY", OPENAI_API_KEY), ("GEMINI_API_KEY", GEMINI_API_KEY)):
    _state = "задано" if _value else "НЕ задано — відповідні API-клітинки буде пропущено"
    print(f"{_var}: {_state}")
'''
    ),
    md(
        """
## 5.1 Екосистема OpenAI: chat/completions vs responses

Різниця між двома API починається з форми запиту. Нижче — ті самі наміри, виражені двічі, і
машинний висновок про те, які поля відрізняються. Мережа не потрібна: це побудова словників.
"""
    ),
    code(
        '''
import json

chat_payload = {
    "model": "gpt-6-astra",
    "messages": [
        {"role": "system", "content": "Ти помічник."},
        {"role": "user", "content": "Столиця України?"},
    ],
    "max_tokens": 64,
}
resp_payload = {
    "model": "gpt-6-astra",
    "instructions": "Ти помічник.",
    "input": "Столиця України?",
    "max_output_tokens": 64,
}

print("CHAT KEYS :", sorted(chat_payload))
print("RESP KEYS :", sorted(resp_payload))
print("лише в chat:", sorted(set(chat_payload) - set(resp_payload)))
print("лише в resp:", sorted(set(resp_payload) - set(chat_payload)))

chat_followup = {"model": "gpt-6-astra",
                 "messages": [{"role": "user", "content": "А населення?"}]}
resp_followup = {"model": "gpt-6-astra",
                 "previous_response_id": "resp_abc123",
                 "input": "А населення?"}
print()
print("chat, 2-й хід:", json.dumps(chat_followup, ensure_ascii=False))
print("resp, 2-й хід:", json.dumps(resp_followup, ensure_ascii=False))
'''
    ),
    md(
        """
Найважливіший рядок виводу — другий хід. Chat-версія надсилає лише новий промпт і **не знає** про
перший хід: щоб модель пам'ятала, доведеться дописати в `messages` і свій промпт, і відповідь
асистента. Responses-версія посилається на збережений хід одним полем.

### Форма відповіді: де лежить текст

Різні API кладуть результат за різними шляхами. Щоб не тримати це в голові, зберемо мапу доступу й
перевіримо її на схемах-словниках (це **схема**, а не реальна відповідь сервера).
"""
    ),
    code(
        '''
# Шляхи доступу до тексту. Значення — ілюстративні схеми, побудовані тут же,
# щоб перевірити самі шляхи без мережі.
chat_shape = {"choices": [{"index": 0, "message": {"role": "assistant", "content": "<текст>"},
                           "finish_reason": "stop"}],
              "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}}
resp_shape = {"id": "resp_...", "output": [{"type": "message", "content": [
                 {"type": "output_text", "text": "<текст>"}]}],
              "output_text": "<текст>", "usage": {"input_tokens": 0, "output_tokens": 0}}


def chat_text(payload):
    return payload["choices"][0]["message"]["content"]


def resp_text_by_output(payload):
    for item in payload["output"]:
        if item.get("type") == "message":
            for part in item.get("content", []):
                if part.get("type") == "output_text":
                    return part["text"]
    return None


paths = [
    ("chat", "completion.choices[0].message.content", chat_text(chat_shape)),
    ("chat", "completion.choices[0].finish_reason", chat_shape["choices"][0]["finish_reason"]),
    ("resp", "response.output_text", resp_shape["output_text"]),
    ("resp", "response.output[].content[].text", resp_text_by_output(resp_shape)),
]
print(f"{'API':6} {'шлях':42} значення")
for api_name, path, value in paths:
    print(f"{api_name:6} {path:42} {value}")

print()
print("кількість генерацій за запит:")
print("  chat -> n (choices[]) ; resp -> 1 (параметр n прибрано)")
'''
    ),
    md(
        """
### Реальні виклики (потрібен `OPENAI_API_KEY`)

Обидві клітинки нижче пропускаються без ключа. Зверніть увагу на `store=True` у Responses: він
зберігає хід на боці OpenAI, і саме тому другий запит може послатися на нього через
`previous_response_id`.
"""
    ),
    code(
        '''
# Реальні виклики обох API. Без ключа клітинка друкує пояснення й не падає.
if not OPENAI_API_KEY:
    print("OPENAI_API_KEY не задано — клітинку пропущено.")
    print("Що вона робить із ключем: chat.completions.create(...) і responses.create(..., store=True),")
    print("потім другий хід через previous_response_id.")
else:
    try:
        from openai import OpenAI

        client = OpenAI(api_key=OPENAI_API_KEY)

        chat = client.chat.completions.create(
            model="gpt-6-astra",
            messages=[{"role": "user", "content": "Столиця України? Одне слово."}],
        )
        print("chat  ->", chat.choices[0].message.content)

        first = client.responses.create(
            model="gpt-6-astra", input="Столиця України? Одне слово.", store=True
        )
        print("resp  ->", first.output_text)

        second = client.responses.create(
            model="gpt-6-astra",
            previous_response_id=first.id,
            input="А населення? Одне число.",
        )
        print("resp2 ->", second.output_text)
    except ImportError:
        print("Пакет openai не встановлено. Встановити: pip install openai")
    except Exception as error:
        print(f"Виклик не вдався: {type(error).__name__}: {error}")
'''
    ),
    md(
        """
## 5.2 Читання changelog як робочий процес

Changelog OpenAI — структурований журнал, а не пресреліз. Каркас: `## <Місяць>, <РІК>`,
`### <Міс> <Д>`, рядок типу (`Feature` / `Update` / `Announcement`), опційні теги
`· Model: <id> · API: <path>` і тіло. Розберемо його програмою.
"""
    ),
    code(
        r'''
import collections
import pathlib
import re

CHANGELOG = ROOT / "research" / "11" / "openai_changelog.md"

MONTH_RE = re.compile(r"^## ([A-Z][a-z]+), (\d{4})$")
DAY_RE = re.compile(r"^### ([A-Z][a-z]{2}) (\d{1,2})$")
TAG_RE = re.compile(
    r"^(Feature|Update|Announcement|Changed|Bug fix|Deprecation)(?:\s+·\s+(.*))?$"
)


def parse_changelog(text):
    """Повертає список записів: місяць, день, тип, теги Model/API, тіло."""
    entries, month, current = [], None, None
    for line in text.splitlines():
        m = MONTH_RE.match(line)
        if m:
            month = f"{m.group(1)}, {m.group(2)}"
            continue
        d = DAY_RE.match(line)
        if d:
            current = {
                "month": month,
                "day": int(d.group(2)),
                "kind": None,
                "models": [],
                "apis": [],
                "body": [],
            }
            entries.append(current)
            continue
        if current is None:
            continue
        tag = TAG_RE.match(line.strip())
        if tag and current["kind"] is None:
            current["kind"] = tag.group(1)
            for part in (tag.group(2) or "").split(" · "):
                if part.startswith("Model: "):
                    current["models"].append(part[7:].strip())
                elif part.startswith("API: "):
                    current["apis"].append(part[5:].strip())
            continue
        current["body"].append(line)
    return entries


entries = parse_changelog(CHANGELOG.read_text(encoding="utf-8"))

print("усього записів:", len(entries), "| місяців:", len({e["month"] for e in entries}))
print("найновіший :", entries[0]["month"], entries[0]["day"])
print("найстаріший:", entries[-1]["month"], entries[-1]["day"])

kinds = collections.Counter(e["kind"] or "(без мітки)" for e in entries)
print()
print("розподіл за типом:")
for kind, n in kinds.most_common():
    print(f"  {kind:14} {n}")

apis = collections.Counter(a for e in entries for a in e["apis"])
print()
print("найчастіші API-теги:")
for api, n in apis.most_common(6):
    print(f"  {api:26} {n}")
'''
    ),
    md(
        """
Два записи без мітки — не дефект парсера, а реальна особливість документа: у двох випадках після
заголовка дня текст іде одразу. Регулярка на кшталт `^(Feature|Update)` без запасного варіанта
мовчки пропустила б ці дані.

Тепер найпрактичніше застосування парсера — фільтр «що змінилося саме в моїх моделях».
"""
    ),
    code(
        '''
# Список моделей і ендпоінтів, які використовує ваш проєкт. Замініть на свої.
MY_MODELS = {"gpt-6-astra", "gpt-5.6-terra", "gpt-5.6-luna"}
MY_APIS = {"v1/responses", "v1/chat/completions"}

relevant = [
    e for e in entries
    if (set(e["models"]) & MY_MODELS) or (set(e["apis"]) & MY_APIS)
]
print(f"записів, що стосуються вашого стеку: {len(relevant)} з {len(entries)}")


def first_sentence(entry):
    text = " ".join(line.strip() for line in entry["body"] if line.strip())
    for stop in (". ", "! "):
        if stop in text:
            return text.split(stop)[0] + "."
    return text[:120]


print()
print(f"{'дата':18} {'тип':12} моделі / API")
for entry in relevant[:8]:
    tags = []
    if entry["models"]:
        tags.append("Model: " + ", ".join(entry["models"][:2]))
    if entry["apis"]:
        tags.append("API: " + ", ".join(entry["apis"][:2]))
    date = f"{entry['month']} {entry['day']}"
    print(f"{date:18} {entry['kind'] or '—':12} {'; '.join(tags)}")

print()
print("приклад повного запису:")
print(" ", first_sentence(relevant[0]))
'''
    ),
    code(
        r'''
import json

# Строки попередження про виведення моделей (сторінка deprecations).
NOTICE = [
    ("Загальнодоступна (GA) модель", "не менше 6 місяців",
     "—"),
    ("Спеціалізований варіант GA", "не менше 3 місяців",
     "gpt-5.1-chat-latest, gpt-5.3-codex, o3-deep-research"),
    ("Preview (preview у назві)", "може бути 2 тижні",
     "computer-use-preview, gpt-4o-audio-preview"),
]
print(f"{'тип моделі':30} {'строк':22} приклади")
for kind, notice, examples in NOTICE:
    print(f"{kind:30} {notice:22} {examples}")

# Версія Python SDK — окремий трек від changelog API.
raw = (ROOT / "research" / "11" / "openai_sdk_pypi.json").read_text(encoding="utf-8")
# fetch.py додає рядок-заголовок "### SOURCE: ..." і порожній рядок перед тілом.
meta = json.loads(raw.split("\n\n", 1)[1])
releases = meta["releases"]


def uploaded(version):
    files = releases[version]
    return files[0]["upload_time"] if files else ""


print()
print("SDK openai — версія:", meta["info"]["version"],
      "| вимога Python:", meta["info"]["requires_python"],
      "| релізів:", len(releases))
print("останні релізи:")
for version in sorted(releases, key=uploaded)[-4:]:
    print(f"  {version:8} {uploaded(version)}")
'''
    ),
    md(
        """
## 5.3 Коди помилок і що робити з кожним

Головна пастка: ретраїти все, що схоже на тимчасову помилку. Нижче — таблиця кодів, зведена зі
сторінки error codes і guide з лімітів, і вирішувач, який відокремлює класифікацію від дії.
"""
    ),
    code(
        '''
# Таблиця кодів -> рішення. Джерело: research/11/openai_error_codes.md,
# research/11/openai_rate_limits.md (розділ "Error mitigation").
RETRYABLE_TYPES = {"rate_limit_error", "server_error", "service_unavailable_error"}

ERRORS = [
    (400, "invalid_request_error", "invalid_service_tier"),
    (401, "invalid_request_error", "invalid_api_key"),
    (401, "invalid_request_error", "ip_not_authorized"),
    (403, "invalid_request_error", "unsupported_country"),
    (429, "rate_limit_error", "rate_limit_exceeded"),
    (429, "rate_limit_error", "slow_down"),
    (429, "insufficient_quota", "credit_balance_exhausted"),
    (429, "insufficient_quota", "organization_spend_limit_exceeded"),
    (429, "insufficient_quota", "project_spend_limit_exceeded"),
    (429, "insufficient_quota", "organization_usage_limit_exceeded"),
    (500, "server_error", "server_error"),
    (503, "service_unavailable_error", "server_is_overloaded"),
]


def decide(status, error_type, error_code, retry_after=None):
    """Повертає (рішення, обґрунтування).

    STOP    — ретрай не допоможе, потрібна дія на боці користувача
    WAIT    — сервер назвав точну затримку
    BACKOFF — затримки немає, будуємо її самі
    """
    if error_type not in RETRYABLE_TYPES:
        return "STOP", f"потрібна дія користувача: {error_code}"
    if retry_after is not None:
        return "WAIT", f"чекати щонайменше {retry_after} с (Retry-After)"
    return "BACKOFF", "експоненційний відкат із джиттером"


print(f"{'HTTP':>4} {'error.type':26} {'error.code':34} {'рішення':8} підстава")
for status, etype, ecode in ERRORS:
    hint = 5 if (status, ecode) == (429, "rate_limit_exceeded") else None
    decision, why = decide(status, etype, ecode, hint)
    print(f"{status:>4} {etype:26} {ecode:34} {decision:8} {why}")

safe = sum(1 for _, etype, _ in ERRORS if etype in RETRYABLE_TYPES)
print()
print(f"з {len(ERRORS)} кодів ретраїти можна {safe}, "
      f"решта {len(ERRORS) - safe} — ні (ретрай не допоможе)")
'''
    ),
    md(
        """
### Розклад відкату, який поважає `Retry-After`

Документація трактує `Retry-After` як **мінімум** і радить додати випадкову затримку, щоб кілька
клієнтів не повторили запит одночасно. Перевіримо арифметику: чи справді перша спроба з
`Retry-After: 5` дешевша за стандартний експоненційний відкат.
"""
    ),
    code(
        '''
import random


def backoff_delays(max_attempts=6, initial=1.0, base=2.0, retry_after=None,
                   max_total=120.0, seed=20260926):
    """Повертає список затримок у секундах (знімок, а не генератор)."""
    rng = random.Random(seed)
    delays, total = [], 0.0
    for attempt in range(max_attempts):
        if attempt == 0 and retry_after is not None:
            delay = float(retry_after)
        else:
            delay = initial * (base ** attempt)
            delay *= 1.0 + rng.random() * 0.5      # джиттер 0..50%
        if total + delay > max_total:
            break
        delays.append(round(delay, 2))
        total += delay
    return delays


for label, retry_after in (("без Retry-After", None), ("Retry-After: 5", 5)):
    delays = backoff_delays(retry_after=retry_after)
    print(f"{label:18} затримки: {delays}")
    print(f"{'':18} усього чекання: {sum(delays):.1f} с, "
          f"перший повтор через {delays[0]} с")

print()
print("правило нарощування трафіку з документації:")
print("  після 1M вхідних токенів/хв — не більше +50% кожні 15 хвилин")
for step in range(5):
    level = 1.0 * (1.5 ** step)
    print(f"  крок {step}: {level:6.2f} × початкового TPM  (~{level * 1_000_000:,.0f} TPM)")
'''
    ),
    md(
        """
### Заголовки лімітів і бюджет запитів

Ліміти видно в заголовках відповіді — це дешевший спосіб зрозуміти стан, ніж чекати на `429`.
Розберемо схему заголовків і порахуємо, скільки запитів витримає профіль.
"""
    ),
    code(
        '''
# Схема заголовків із research/11/openai_rate_limits.md (значення — приклади з документації).
HEADER_SCHEMA = {
    "Retry-After": "56",
    "x-ratelimit-limit-requests": "60",
    "x-ratelimit-limit-tokens": "150000",
    "x-ratelimit-remaining-requests": "59",
    "x-ratelimit-remaining-tokens": "149984",
    "x-ratelimit-reset-requests": "1s",
    "x-ratelimit-reset-tokens": "6m0s",
}
print(f"{'заголовок':34} {'приклад':>10}  значення")
MEANING = {
    "Retry-After": "мінімум секунд до повтору (є на 429 і 503)",
    "x-ratelimit-limit-requests": "максимум запитів до вичерпання",
    "x-ratelimit-limit-tokens": "максимум токенів",
    "x-ratelimit-remaining-requests": "залишок запитів",
    "x-ratelimit-remaining-tokens": "залишок токенів",
    "x-ratelimit-reset-requests": "час до скидання лічильника запитів",
    "x-ratelimit-reset-tokens": "час до скидання лічильника токенів",
}
for header, sample in HEADER_SCHEMA.items():
    print(f"{header:34} {sample:>10}  {MEANING[header]}")

# Скільки влізе за хвилину за різних лімітів.
print()
print(f"{'RPM':>5} {'розмір запиту':>15} {'TPM':>9} {'визначає:':>12}")
for rpm, per_request, tpm in ((60, 6_000, 150_000), (500, 6_000, 2_000_000), (20, 100, 150_000)):
    by_requests = rpm * per_request
    winner = "RPM" if by_requests < tpm else "TPM"
    print(f"{rpm:>5} {per_request:>15,} {tpm:>9,} {winner:>12}")
print()
print("висновок: ліміт спрацьовує за тим, що вичерпається першим —")
print("20 запитів по 100 токенів вичерпують RPM=20, хоча TPM далеко не вибраний.")
'''
    ),
    md(
        """
## 5.4 OpenAI-сумісні ендпоінти

Сумісний `base_url` обіцяє, що при зміні провайдера змінюються рівно три значення. Перевіримо цю
обіцянку машинно: порівняємо адреси й порахуємо, скільки полів запиту залишаються портативними.
"""
    ),
    code(
        '''
import json

# base_url із документації провайдерів. Джерела: research/11/gemini_openai_compatibility.md,
# research/11/mistral_openai_migration.md, research/11/deepseek_first_api_call.md
PROVIDERS = {
    "openai":   {"base_url": "https://api.openai.com/v1", "env": "OPENAI_API_KEY"},
    "gemini":   {"base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
                 "env": "GEMINI_API_KEY"},
    "mistral":  {"base_url": "https://api.mistral.ai/v1", "env": "MISTRAL_API_KEY"},
    "deepseek": {"base_url": "https://api.deepseek.com", "env": "DEEPSEEK_API_KEY"},
}

for name, cfg in PROVIDERS.items():
    print(f"{name:9} {cfg['base_url']:56} ключ із ${cfg['env']}")

common_core = ["model", "messages", "stream", "tools", "tool_choice",
               "response_format", "max_tokens", "temperature", "top_p",
               "n", "stop", "seed"]
gemini_only = ["reasoning_effort", "extra_body", "service_tier"]

print()
print(f"спільне ядро ({len(common_core)} полів):")
print("  " + ", ".join(common_core))
print(f"лише Gemini: {', '.join(gemini_only)}")

portable = sorted(set(common_core) - set(gemini_only))
print()
print(f"портативних полів: {len(portable)} з {len(common_core) + len(gemini_only)}")
print("непортативні:", ", ".join(sorted(set(gemini_only) - set(common_core))) or "немає")

print()
print("запит, ідентичний для всіх чотирьох провайдерів:")
print(json.dumps({"model": "<id провайдера>", "messages": [
    {"role": "user", "content": "Hello"}]}, ensure_ascii=False))
'''
    ),
    md(
        """
### Перевірка своєї схеми на сумісність зі Structured Outputs

Найнебезпечніший випадок сумісності — мовчазне ігнорування. У Responses запит **намагається**
нормалізувати вашу схему в strict-режим, а якщо не вдається — тихо відкочується до best-effort і
позначає tool як `strict: false`. Тому схему варто перевіряти до відправки. Обмеження взяті з
`research/11/openai_structured_outputs.md`.
"""
    ),
    code(
        '''
# Найнебезпечніший випадок сумісності — мовчазне ігнорування. Перевіримо схему заздалегідь.
UNSUPPORTED = {"allOf", "not", "if", "then", "else", "dependentRequired", "dependentSchemas"}


def check_schema(node, path="root", problems=None, depth=0):
    """Перевіряє JSON Schema на сумісність зі Structured Outputs."""
    if problems is None:
        problems = []
    if depth > 10:
        problems.append(f"{path}: перевищено ліміт 10 рівнів вкладеності")
        return problems
    if not isinstance(node, dict):
        return problems
    if path == "root" and "anyOf" in node:
        problems.append("root: кореневий об'єкт не може бути anyOf "
                        "(типовий наслідок zod discriminatedUnion)")
    for keyword in node:
        if keyword in UNSUPPORTED:
            problems.append(f"{path}: ключ {keyword!r} не підтримується")
    if node.get("type") == "object" or "properties" in node:
        if node.get("additionalProperties") is not False:
            problems.append(f"{path}: потрібно additionalProperties: false")
        props, required = node.get("properties", {}), set(node.get("required", []))
        for field in props:
            if field not in required:
                problems.append(f"{path}.{field}: відсутнє в required — "
                                "усі поля мають бути обов'язкові")
        for field, subschema in props.items():
            check_schema(subschema, f"{path}.{field}", problems, depth + 1)
    if node.get("type") == "array" and "items" in node:
        check_schema(node["items"], f"{path}[]", problems, depth + 1)
    return problems


good = {"type": "object", "additionalProperties": False, "required": ["sentiment", "confidence"],
        "properties": {"sentiment": {"type": "string", "enum": ["positive", "negative", "neutral"]},
                       "confidence": {"type": "number", "minimum": 0, "maximum": 1}}}
bad_root_anyof = {"anyOf": [
    {"type": "object", "additionalProperties": False, "required": ["ok"],
     "properties": {"ok": {"type": "string"}}},
    {"type": "object", "additionalProperties": False, "required": ["err"],
     "properties": {"err": {"type": "string"}}}]}
bad_fields = {"type": "object", "required": ["city"],
              "properties": {"city": {"type": "string"},
                             "units": {"type": "string", "enum": ["C", "F"]}}}
bad_composition = {"type": "object", "additionalProperties": False, "required": ["v"],
                   "properties": {"v": {"allOf": [{"type": "string"}, {"type": "string"}]}}}

CASES = [
    ("добре: плаский об'єкт з enum і межами", good),
    ("погано: anyOf у корені (патерн zod discriminatedUnion)", bad_root_anyof),
    ("погано: необов'язкове поле й немає additionalProperties", bad_fields),
    ("погано: allOf усередині", bad_composition),
]
for label, schema in CASES:
    problems = check_schema(schema)
    print(f"{label}")
    print(f"  проблем: {len(problems)}")
    for problem in problems:
        print("   -", problem)
'''
    ),
    code(
        '''
# Реальний виклик до сумісного ендпоінта (Gemini). Без ключа — пропуск.
if not GEMINI_API_KEY:
    print("GEMINI_API_KEY не задано — клітинку пропущено.")
    print("Що вона робить із ключем: OpenAI-клієнт із base_url шару сумісності Gemini")
    print("і chat.completions.create(model='gemini-3.8-flash', ...).")
else:
    try:
        from openai import OpenAI

        client = OpenAI(
            api_key=GEMINI_API_KEY,
            base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
        )
        response = client.chat.completions.create(
            model="gemini-3.8-flash",
            messages=[
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": "Explain to me how AI works"},
            ],
        )
        print("Gemini через OpenAI SDK ->", response.choices[0].message.content[:200])
    except ImportError:
        print("Пакет openai не встановлено. Встановити: pip install openai")
    except Exception as error:
        print(f"Виклик не вдався: {type(error).__name__}: {error}")
'''
    ),
    md(
        """
## 5.5 Огляд інших провайдерів і цінові профілі

Таблиця цін OpenAI — це чотири режими на одну модель плюс окремий тариф довгого контексту.
Розберемо її програмою, щоб не переносити числа руками.
"""
    ),
    code(
        r'''
import pathlib

PRICING = ROOT / "research" / "econ" / "openai_pricing.md"


def parse_pricing_blocks(text):
    """Розбирає блоки "### <Режим> pricing data" зі сторінки цін."""
    blocks, title, rows = {}, None, []
    for line in text.splitlines():
        if line.startswith("### ") and line.endswith("pricing data"):
            if title:
                blocks[title] = rows
            title, rows = line[4:].replace(" pricing data", ""), []
            continue
        if title and line.startswith("|"):
            cells = [c.strip() for c in line.strip("|").split("|")]
            if len(cells) >= 5 and cells[0] != "Model" and not set(cells[0]) <= set("-: "):
                rows.append(cells)
    if title:
        blocks[title] = rows
    return blocks


def money(text):
    text = text.replace("$", "").replace(",", "").strip()
    return None if text in ("-", "") else float(text)


blocks = parse_pricing_blocks(PRICING.read_text(encoding="utf-8"))
print("знайдено таблиць:", ", ".join(blocks))
std = blocks["Standard"]
print("рядків у Standard:", len(std))

by_name = {row[0].split(" (")[0].strip(): row for row in std}
print()
print("режими для gpt-6-astra (за 1M токенів, короткий контекст):")
print(f"  {'режим':10} {'вхід':>9} {'кеш.вхід':>10} {'вихід':>9}")
for tier in ("Standard", "Batch", "Flex", "Fast"):
    row = next((r for r in blocks[tier] if r[0].startswith("gpt-6-astra")), None)
    if row:
        print(f"  {tier:10} {row[1]:>9} {row[2]:>10} {row[4]:>9}")

print()
print("довгий контекст (Standard, gpt-6-astra):")
row = by_name["gpt-6-astra"]
print(f"  короткий: вхід {row[1]} вихід {row[4]}")
print(f"  довгий  : вхід {row[5]} вихід {row[8]}")
print("  перевищення порогу подвоює ціну ВСЬОГО запиту, не лише надлишку")
'''
    ),
    code(
        '''
# Сценарій: 20 000 викликів, 6 000 вхідних і 400 вихідних токенів на виклик.
# Ціни за 1M токенів узяті з research/econ/openai_pricing.md,
# research/11/gemini_pricing.md, research/11/deepseek_pricing.md,
# research/econ/mistral_pricing.txt.
CALLS, TOKENS_IN, TOKENS_OUT = 20_000, 6_000, 400

SCENARIOS = [
    ("OpenAI gpt-6-astra (standard)",     10.00,  50.00),
    ("OpenAI gpt-5.6-terra (standard)",    2.00,  12.00),
    ("OpenAI gpt-5.6-luna (standard)",     0.20,   1.20),
    ("OpenAI gpt-5.6-luna (batch/flex)",   0.10,   0.60),
    ("OpenAI gpt-6-astra (fast)",         20.00, 100.00),
    ("Gemini 3.8 Flash (до 31.12.2026)",   0.75,   3.75),
    ("Gemini 3.8 Flash (з 01.01.2027)",    1.50,   7.50),
    ("Gemini 3.8 Flash (batch)",           0.375,  1.875),
    ("DeepSeek V4-Flash (peak)",           0.30,   1.20),
    ("DeepSeek V4-Flash (off-peak)",       0.15,   0.60),
    ("DeepSeek V4-Pro (peak)",             1.32,   3.96),
    ("Mistral Large (приклад із FAQ)",     0.50,   1.50),
]


def cost(pin, pout):
    return (TOKENS_IN / 1e6 * pin + TOKENS_OUT / 1e6 * pout) * CALLS


print(f"Сценарій: {CALLS} викликів × ({TOKENS_IN} вх / {TOKENS_OUT} вих)")
print(f"{'конфігурація':36} {'ціна виклику':>13} {'усього':>10}")
for name, pin, pout in SCENARIOS:
    per_call = TOKENS_IN / 1e6 * pin + TOKENS_OUT / 1e6 * pout
    print(f"{name:36} ${per_call:>12.5f} ${cost(pin, pout):>9.2f}")

totals = [cost(p, o) for _, p, o in SCENARIOS]
print()
print(f"розкид між крайніми конфігураціями: "
      f"${min(totals):.2f} ... ${max(totals):.2f} (×{max(totals) / min(totals):.0f})")
'''
    ),
    md(
        """
Найбільший множник дає не вибір провайдера, а вибір режиму й моделі всередині одного провайдера:
`gpt-6-astra` і `gpt-5.6-luna` — це один постачальник і той самий SDK, а різниця в 190 разів.

Остання перевірка — пікові тарифи DeepSeek, які перетворюють розклад на важіль економії.
"""
    ),
    code(
        '''
# Пікові години DeepSeek: 01:00-04:00 і 06:00-10:00 UTC, Пн-Пт, крім свят.
# Позапікова ставка рівно вдвічі нижча за пікову.
import datetime as dt

PEAK_HOURS = list(range(1, 4)) + list(range(6, 10))
day = dt.date(2026, 9, 26)          # субота — позапіковий день повністю


def is_peak(moment):
    return moment.weekday() < 5 and moment.hour in PEAK_HOURS


print("26.09.2026 — субота, тож позапіковий час цілу добу:")
print(f"  {'час UTC':>8}  {'режим':10} ціна виходу за 1M")
for hour in (0, 2, 7, 12, 18, 23):
    moment = dt.datetime.combine(day, dt.time(hour))
    peak = is_peak(moment)
    price = 1.20 if peak else 0.60
    print(f"  {hour:02d}:00    {'peak' if peak else 'off-peak':10} ${price:.2f}")

monday = dt.date(2026, 9, 28)
print()
print("28.09.2026 — понеділок, тож є обидва режими:")
for hour in (0, 2, 5, 7, 12, 23):
    moment = dt.datetime.combine(monday, dt.time(hour))
    peak = is_peak(moment)
    price = 1.20 if peak else 0.60
    print(f"  {hour:02d}:00    {'peak' if peak else 'off-peak':10} ${price:.2f}")

print()
base = 1.20 * 20_000 * (TOKENS_OUT / 1e6)
print(f"вихід у сценарії на deepseek-flash: {base:.2f} USD у peak, {base / 2:.2f} USD в off-peak")
'''
    ),
    md(
        """
## Підсумки

- **Формат — це архітектурне рішення.** Chat Completions stateless за побудовою; Responses може
  тримати стан через `store: true` і `previous_response_id`, але лише він має вбудовані інструменти.
- **Changelog варто парсити, а не читати.** 170 записів за 35 місяців; теги `Model:` і `API:`
  дозволяють фільтрувати релевантне без семантичного аналізу.
- **Дві третини помилок не лікуються ретраєм.** `429` покриває шість різних умов, і лише дві з них
  тимчасові.
- **`Retry-After` — це мінімум.** Запит, який прийшов занадто рано, додає навантаження й повертає
  новий `429`.
- **Сумісний `base_url` — це три змінені рядки, а не гарантія еквівалентності.** Перевіряйте
  кожну функцію окремо; `extra_body` робить код непортативним за визначенням.
- **Ціновий профіль — це набір режимів.** Розкид у 190 разів на одному сценарії дає не зміна
  провайдера, а зміна режиму й моделі.

**Куди далі:**

- Розділ 6 — вибір моделі за ціною, латентністю й контекстом.
- Розділ 9 — prompt caching і діагностика промахів.
- Розділ 10 — Batch API з окремими лімітами черги.
- Розділ 12 — tool use і цикл агента.
- Розділ 23 — observability: як побачити ці помилки в продакшні.
- Розділ 25 — сервінг, відкати й деградація під навантаженням.

## Джерела

- [OpenAI — Changelog](https://developers.openai.com/api/docs/changelog.md)
- [OpenAI — Deprecations](https://developers.openai.com/api/docs/deprecations.md)
- [OpenAI — Error codes](https://developers.openai.com/api/docs/guides/error-codes.md)
- [OpenAI — Rate limits](https://developers.openai.com/api/docs/guides/rate-limits.md)
- [OpenAI — Migrate to the Responses API](https://developers.openai.com/api/docs/guides/migrate-to-responses.md)
- [OpenAI — Streaming API responses](https://developers.openai.com/api/docs/guides/streaming-responses.md)
- [OpenAI — Conversation state](https://developers.openai.com/api/docs/guides/conversation-state.md)
- [OpenAI — Function calling](https://developers.openai.com/api/docs/guides/function-calling.md)
- [OpenAI — Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs.md)
- [OpenAI — Flex processing](https://developers.openai.com/api/docs/guides/flex-processing.md)
- [OpenAI — Pricing](https://developers.openai.com/api/docs/pricing.md)
- [Gemini — OpenAI compatibility](https://ai.google.dev/gemini-api/docs/openai.md.txt)
- [Gemini — Pricing](https://ai.google.dev/gemini-api/docs/pricing.md.txt)
- [Mistral — Migration guides](https://docs.mistral.ai/resources/migration-guides.md)
- [DeepSeek — Моделі й ціни](https://api-docs.deepseek.com/quick_start/pricing)
- [PyPI — openai](https://pypi.org/pypi/openai/json)
- Локальні знімки джерел: `research/11/`, `research/econ/openai_pricing.md`,
  `research/econ/mistral_pricing.txt`
"""
    ),
]
