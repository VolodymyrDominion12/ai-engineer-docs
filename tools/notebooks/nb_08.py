"""Ноутбук 08 — «Міркування (thinking) і керування зусиллям».

Розділ довідника: sections/08-thinking.md
Працює без API-ключа: усі клітинки з викликами API перевіряють наявність
ANTHROPIC_API_KEY і друкують пояснення, якщо ключа немає.

Уся механіка мислення, рівнів effort, тарифікації та збереження блоків узята
з первинних джерел (research/02/thinking.md, effort.md, preserved-thinking.md,
thinking-steering-and-cost.md, thinking-troubleshooting.md,
thinking-tool-workflows.md, extended-thinking-legacy.md, context-windows.md,
pricing.md, migrating-opus-5.md) станом на 26.09.2026.
"""

from nbkit import SETUP_CELL, VERSION_CELL, code, md

FILENAME = "08-thinking.ipynb"
TITLE = "8. Мислення і зусилля"

CELLS = [
    md(
        """
# 08. Міркування (thinking) і керування зусиллям

**Розділ довідника:** [`sections/08-thinking.md`](../sections/08-thinking.md)

**Потрібно: ANTHROPIC_API_KEY** — для клітинок, які роблять справжні виклики API
(`cp .env.example .env` і впишіть ключ). Решта ноутбука **повністю виконується без ключа**:
локальні моделі, таблиці, розбір форм відповіді й діагностика працюють завжди, а API-клітинки
друкують пояснення, що їх пропущено.

**Що ви зробите:**

1. Розберете форму відповіді з блоками `thinking` і три значення `display` — `"summarized"`,
   `"omitted"`, `"redacted_thinking"` — та пастку читання за індексом.
2. Побудуєте локальний валідатор конфігурації `thinking.type`, який відтворює справжні тексти
   помилок 400 для кожної моделі.
3. Розберете SSE-потік мислення: `thinking_delta` → `signature_delta` → `text_delta`.
4. Складете матрицю рівнів `effort` і побачите, на яких моделях немає `xhigh`.
5. Порахуєте, скільки коштує мислення, і як `max_tokens` ділиться між міркуванням і текстом.
6. Відтворите перевірку префікса (preserved thinking): які правки історії вбивають блоки мислення.
7. Зберете локальну діагностику: симптом → причина → дія, з реальними текстами помилок.
8. Перевірите, що хід асистента з блоком мислення повертається дослівно, і як це ламається.

> Ключова пастка розділу: токени міркування тарифікуються як **вихідні** навіть тоді, коли текст
> міркування вам не повертається, і вони входять у `max_tokens` разом із текстом відповіді.
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
# Читання ключа з .env. Ноутбук виконується й без нього: API-клітинки
# друкують пояснення й пропускаються.
import os

try:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
    print("python-dotenv: читаю .env (якщо файл існує)")
except ImportError:
    print("python-dotenv не встановлено — читаю лише змінні середовища.")

HAS_KEY = bool(os.environ.get("ANTHROPIC_API_KEY"))
print("ANTHROPIC_API_KEY:",
      "знайдено" if HAS_KEY else "НЕ задано — усі API-клітинки буде пропущено")


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

    # ── 8.1 ──────────────────────────────────────────────────────────────
    md(
        """
## 8.1 Адаптивне мислення проти legacy extended thinking

Два режими: **adaptive** (`thinking={"type": "adaptive"}`) — модель сама вирішує, чи думати;
**extended** (`thinking={"type": "enabled", "budget_tokens": N}`) — ви задаєте бюджет токенів.
Ручний режим застарілий на Claude 4.6 і дає **400 на Claude 4.7 і новіших**.

Спершу — форма відповіді. Блоки мислення приходять перед блоками тексту, а значення `display`
керує тим, чи буде видно текст міркування.
"""
    ),
    code(
        '''
# Три форми відповіді, які реально повертає API.
# Увага на читання за індексом: content[0] може бути блоком мислення, а не текстом.

def read_reply(content: list[dict]) -> dict:
    """Витягує текст і стан мислення незалежно від порядку блоків."""
    thinking = [b for b in content if b["type"] in ("thinking", "redacted_thinking")]
    text = "".join(b.get("text", "") for b in content if b["type"] == "text")
    tool_calls = [b["name"] for b in content if b["type"] == "tool_use"]
    return {
        "text": text,
        "thinking_blocks": len(thinking),
        "thinking_visible": any(b.get("thinking") for b in thinking),
        "redacted": sum(1 for b in thinking if b["type"] == "redacted_thinking"),
        "tool_calls": tool_calls,
    }


reply_omitted = [
    {"type": "thinking", "thinking": "", "signature": "EosnCkYICxIMMb3LzNrMu..."},
    {"type": "text", "text": "Відповідь: 12 231."},
]
reply_summarized = [
    {"type": "thinking", "thinking": "Розберу задачу на дві частини...", "signature": "WaUjzkyp..."},
    {"type": "text", "text": "Відповідь: 12 231."},
]
reply_redacted = [
    {"type": "redacted_thinking", "data": "EqQBCgIYAhIM1gbcDa9GJwZA2b..."},
    {"type": "text", "text": "Відповідь: 12 231."},
]

for reply_name, reply_content in (("omitted", reply_omitted),
                                  ("summarized", reply_summarized),
                                  ("redacted", reply_redacted)):
    parsed = read_reply(reply_content)
    print(f"{reply_name:11} блоків_мислення={parsed['thinking_blocks']} "
          f"є_текст_мислення={str(parsed['thinking_visible']):5} text={parsed['text']!r}")

print()
print("content[0]['text'] ->", reply_omitted[0].get("text"),
      "  <- читання за індексом дає None, а не текст відповіді")
'''
    ),
    md(
        """
Наступна клітинка — локальний валідатор конфігурації. Він друкує **справжні** тексти помилок 400,
щоб їх можна було порівнювати в тестах замість покладання на пам'ять.
"""
    ),
    code(
        '''
# Підтримка thinking.type за моделями (research/02/thinking-troubleshooting.md).
THINKING_MODES = {
    "claude-fable-5-1":      {"default": "always_on", "rejects": {"enabled", "disabled"}},
    "claude-mythos-preview": {"default": "always_on", "rejects": {"disabled"}},
    "claude-opus-5":         {"default": "on",        "rejects": {"enabled"}},
    "claude-opus-4-8":       {"default": "off",       "rejects": {"enabled"}},
    "claude-sonnet-5":       {"default": "on",        "rejects": {"enabled"}},
    "claude-opus-4-6":       {"default": "off",       "rejects": set()},
    "claude-opus-4-5":       {"default": "off",       "rejects": {"adaptive"}},
    "claude-haiku-4-5":      {"default": "off",       "rejects": {"adaptive"}},
}

THINKING_ERRORS = {
    "enabled": '"thinking.type.enabled" is not supported for this model. '
               'Use "thinking.type.adaptive" and "output_config.effort" to control thinking behavior.',
    "disabled": '"thinking.type.disabled" is not supported for this model. '
                'Use "thinking.type.adaptive" and "output_config.effort" to control thinking behavior.',
    "adaptive": "adaptive thinking is not supported on this model",
}


def validate_thinking(model: str, thinking: dict | None, effort: str | None = None) -> str:
    """Відтворює правила довідки: що модель приймає, а що відкидає з 400."""
    spec = THINKING_MODES[model]
    if thinking is None:
        if spec["default"] == "off":
            return "OK (мислення вимкнено — успадкована поведінка)"
        return "OK (мислення увімкнено типово, display=omitted)"
    thinking_type = thinking["type"]
    if model == "claude-opus-5" and thinking_type == "disabled" and effort in ("xhigh", "max"):
        return '400: thinking: {type: "disabled"} заборонено на effort "xhigh"/"max"'
    if thinking_type in spec["rejects"]:
        return f"400: {THINKING_ERRORS[thinking_type]}"
    return f"OK (режим {thinking_type})"


THINKING_CASES = [
    ("claude-opus-5", {"type": "enabled", "budget_tokens": 10000}, None),
    ("claude-opus-4-8", {"type": "enabled", "budget_tokens": 10000}, None),
    ("claude-fable-5-1", {"type": "disabled"}, None),
    ("claude-opus-5", {"type": "disabled"}, "max"),
    ("claude-opus-5", {"type": "disabled"}, "medium"),
    ("claude-haiku-4-5", {"type": "adaptive"}, None),
    ("claude-opus-4-6", {"type": "enabled", "budget_tokens": 10000}, None),
]
for case_model, case_thinking, case_effort in THINKING_CASES:
    case_label = str(case_thinking) if case_thinking else "без параметра thinking"
    print(f"{case_model:22} {case_label:42} effort={str(case_effort):7} -> "
          f"{validate_thinking(case_model, case_thinking, case_effort)}")

print()
print("Правило legacy-режиму: budget_tokens >= 1024 і < max_tokens (виняток — interleaved thinking).")
for budget in (512, 1024, 8000):
    ok = budget >= 1024
    print(f"  budget_tokens={budget:>5} -> {'прийнято' if ok else 'відкинуто API (менше мінімуму)'}")
'''
    ),
    md(
        """
Мислення працює й зі стрімінгом. Порядок подій такий: блок відкривається `content_block_start`,
текст міркування приходить `thinking_delta`, блок закриває **одна** подія `signature_delta`, і лише
потім ідуть `text_delta`. При `display: "omitted"` дельта мислення приходить порожньою, а підпис —
справжній.
"""
    ),
    code(
        '''
import json

# Спрощений зріз справжнього SSE-потоку Anthropic (research/02/thinking.md).
SSE_TRACE = """event: content_block_start
data: {"type":"content_block_start","index":0,"content_block":{"type":"thinking","thinking":"","signature":""}}

event: content_block_delta
data: {"type":"content_block_delta","index":0,"delta":{"type":"thinking_delta","thinking":"1071 = 2*462 + 147; 462 = 3*147 + 21"}}

event: content_block_delta
data: {"type":"content_block_delta","index":0,"delta":{"type":"signature_delta","signature":"EqQBCgIYAhIM1gbcDa9GJwZA2b"}}

event: content_block_stop
data: {"type":"content_block_stop","index":0}

event: content_block_start
data: {"type":"content_block_start","index":1,"content_block":{"type":"text","text":""}}

event: content_block_delta
data: {"type":"content_block_delta","index":1,"delta":{"type":"text_delta","text":"НСД = 21"}}
"""


def collect_stream_blocks(trace: str) -> list[dict]:
    """Відновлює блоки з потоку подій, не відкидаючи порожні дельти."""
    blocks: dict[int, dict] = {}
    for line in trace.splitlines():
        if not line.startswith("data: "):
            continue
        event = json.loads(line[6:])
        index = event.get("index")
        if event["type"] == "content_block_start":
            blocks[index] = {**event["content_block"], "_closed": False}
        elif event["type"] == "content_block_delta":
            delta = event["delta"]
            block = blocks[index]
            if delta["type"] == "thinking_delta":
                block["thinking"] += delta["thinking"]
            elif delta["type"] == "signature_delta":
                block["signature"] = delta["signature"]
            elif delta["type"] == "text_delta":
                block["text"] = block.get("text", "") + delta["text"]
        elif event["type"] == "content_block_stop":
            blocks[index]["_closed"] = True
    return [blocks[i] for i in sorted(blocks)]


for stream_block in collect_stream_blocks(SSE_TRACE):
    print(f"[{stream_block['type']:8}] thinking={stream_block.get('thinking')!r} "
          f"signature={stream_block.get('signature')!r} text={stream_block.get('text')!r}")

print()
print("Порожній thinking_delta при display='omitted' — це нормально; втрачати його не можна,")
print("бо саме в парі з ним приходить підпис, без якого наступний запит у циклі впаде з 400.")
'''
    ),

    # ── 8.2 ──────────────────────────────────────────────────────────────
    md(
        """
## 8.2 Параметр `effort` і рівні

`effort` передається як `output_config={"effort": ...}` і має п'ять значень: `low`, `medium`,
`high`, `xhigh`, `max`. Типове значення — `high`, і явний `"high"` поводиться **точно так само**,
як відсутність параметра.

`effort` впливає на **всі** вихідні токени — текст, виклики інструментів і міркування. Це
поведінковий сигнал, а не бюджет: гарантованої кількості токенів він не дає.
"""
    ),
    code(
        '''
# Рівні effort і їхня доступність за моделями (research/02/effort.md).
EFFORT_LEVELS = ["low", "medium", "high", "xhigh", "max"]

EFFORT_THINKING_BEHAVIOR = {
    "low":    "мінімізує мислення; на простих задачах пропускає його",
    "medium": "помірне мислення; може пропустити на простих запитах",
    "high":   "майже завжди думає; глибоке міркування (типове значення)",
    "xhigh":  "завжди думає глибоко з розширеним дослідженням",
    "max":    "завжди думає, без обмежень на глибину",
}

EFFORT_BASE = set(EFFORT_LEVELS[:3])
MODEL_EFFORT_LEVELS = {
    "claude-fable-5-1":      EFFORT_BASE | {"xhigh", "max"},
    "claude-mythos-5-1":     EFFORT_BASE | {"xhigh", "max"},
    "claude-fable-5":        EFFORT_BASE | {"xhigh", "max"},
    "claude-mythos-5":       EFFORT_BASE | {"xhigh", "max"},
    "claude-mythos-preview": EFFORT_BASE | {"max"},
    "claude-opus-5":         EFFORT_BASE | {"xhigh", "max"},
    "claude-opus-4-8":       EFFORT_BASE | {"xhigh", "max"},
    "claude-opus-4-7":       EFFORT_BASE | {"xhigh", "max"},
    "claude-opus-4-6":       EFFORT_BASE | {"max"},
    "claude-sonnet-5":       EFFORT_BASE | {"xhigh", "max"},
    "claude-sonnet-4-6":     EFFORT_BASE | {"max"},
    "claude-opus-4-5":       EFFORT_BASE,
}

effort_header = "модель".ljust(24) + "".join(level.center(7) for level in EFFORT_LEVELS)
print(effort_header)
print("-" * len(effort_header))
for effort_model, effort_levels in MODEL_EFFORT_LEVELS.items():
    row = "".join(("  ✓  " if level in effort_levels else "  ·  ").center(7)
                  for level in EFFORT_LEVELS)
    print(effort_model.ljust(24) + row)

print()
print("без xhigh:", ", ".join(m for m, levels in MODEL_EFFORT_LEVELS.items()
                             if "xhigh" not in levels))
print("без max  :", ", ".join(m for m, levels in MODEL_EFFORT_LEVELS.items()
                             if "max" not in levels) or "немає таких")


def effective_effort(effort: str | None, model: str) -> str:
    """Відсутнє значення = high; явний high еквівалентний відсутності параметра."""
    if effort is None:
        return "high"
    if effort not in MODEL_EFFORT_LEVELS[model]:
        raise ValueError(f"{model} не підтримує effort={effort!r}")
    return effort


print()
for effort_probe in (None, "high", "medium", "max"):
    print(f"  output_config.effort={str(effort_probe):7} -> "
          f"{effective_effort(effort_probe, 'claude-opus-5')}")

print()
print("Типова помилка: передати 'adaptive' як рівень effort —")
print("'adaptive' це режим thinking, а не рівень. Значення:",
      ", ".join(EFFORT_LEVELS))
'''
    ),
    md(
        """
Що робить кожен рівень із мисленням — і окремо те, як змінити рівень посеред розмови, не вбивши
кеш. На Fable 5.1, Mythos 5.1 і Opus 5 для цього є **per-message effort** (бета): повідомлення з
роллю `system`, порожнім `content` і новим рівнем.
"""
    ),
    code(
        '''
# Схема запиту з per-message effort (бета-заголовок mid-conversation-output-config-2026-07-01).
# Верхній рівень лишається незмінним — саме тому кеш не перезапускається.
effort_request = {
    "model": "claude-fable-5-1",
    "max_tokens": 4096,
    "output_config": {"effort": "high"},
    "messages": [
        {"role": "user",
         "content": "Склади план міграції з SQLite на PostgreSQL у три кроки."},
        {"role": "assistant",
         "content": "1. Експорт даних. 2. Створити схему. 3. Імпорт і перевірка кількості рядків."},
        # Повідомлення лише з effort: новий рівень діє з наступного ходу користувача.
        {"role": "system", "content": [], "output_config": {"effort": "low"}},
        {"role": "user", "content": "Стисни план до одного речення."},
    ],
    # у виклику SDK: betas=["mid-conversation-output-config-2026-07-01"]
}

per_message = effort_request["messages"][2]
assert per_message["content"] == []
assert per_message["output_config"]["effort"] in EFFORT_LEVELS
print("per-message effort :", per_message["output_config"])
print("верхній рівень     :", effort_request["output_config"])
print("порожній content   : правила розміщення system-повідомлень не застосовуються")
print()
print("На моделях без per-message effort (наприклад claude-fable-5) такий запит дає 400:")
print('  output_config.effort requires a model that supports per-turn effort; this model does not')
'''
    ),

    # ── 8.3 ──────────────────────────────────────────────────────────────
    md(
        """
## 8.3 Ціна мислення й керування витратами

Токени міркування тарифікуються як **вихідні** — навіть коли текст міркування не повертається
(`display: "omitted"`). Рахунок формує `output_tokens`, а не те, що видно в тілі відповіді.
Розбивку для спостережуваності дає `usage.output_tokens_details.thinking_tokens`.

Обмежують витрати два різні інструменти: `max_tokens` — **жорстка** стеля на сумарний вихід
(міркування + текст), `effort` — **м'яка** підказка розподілу.
"""
    ),
    code(
        '''
# Ціни в USD за 1M токенів (research/02/pricing.md, станом на 09.2026).
MODEL_PRICES = {
    # модель: (вхід, вихід)
    "claude-fable-5-1":  (10.0, 50.0),
    "claude-opus-5":     (5.0, 25.0),
    "claude-opus-4-8":   (5.0, 25.0),
    "claude-sonnet-5":   (2.0, 10.0),
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-haiku-4-5":  (1.0, 5.0),
}
CACHE_WRITE_MULT = 1.25     # 5-хвилинний запис у кеш
CACHE_READ_MULT = 0.10      # влучання в кеш (Fable 5.1 / Mythos 5.1 — 0.025)


def turn_cost(model: str, usage: dict) -> dict:
    """Вартість ходу. Мислення входить в output_tokens, тому й тарифікується як вихід."""
    input_price, output_price = MODEL_PRICES[model]
    fresh = usage.get("input_tokens", 0)
    written = usage.get("cache_creation_input_tokens", 0)
    read = usage.get("cache_read_input_tokens", 0)
    output = usage.get("output_tokens", 0)
    thinking = usage.get("output_tokens_details", {}).get("thinking_tokens", 0)
    input_cost = (fresh + written * CACHE_WRITE_MULT + read * CACHE_READ_MULT) / 1e6 * input_price
    output_cost = output / 1e6 * output_price
    return {
        "усього_usd": round(input_cost + output_cost, 6),
        "вихід_usd": round(output_cost, 6),
        "частка_мислення": round(thinking / output, 4) if output else 0.0,
        "мислення_usd": round(thinking / 1e6 * output_price, 6),
    }


# Приклад із довідки: output_tokens=348, thinking_tokens=312
usage_with_thinking = {"input_tokens": 25, "output_tokens": 348,
                       "output_tokens_details": {"thinking_tokens": 312}}
for cost_model in ("claude-opus-5", "claude-sonnet-5"):
    print(f"{cost_model:18} {turn_cost(cost_model, usage_with_thinking)}")

print()
usage_without_thinking = {"input_tokens": 25, "output_tokens": 348}
print("ті самі 348 вихідних токенів, але без мислення:")
print("  ", turn_cost("claude-opus-5", usage_without_thinking))
print("  висновок: білінг визначає output_tokens, а не видимість тексту міркування")
print()
print("Щоб дізнатися частку мислення у витратах, читайте")
print("usage.output_tokens_details.thinking_tokens (при стрімінгу — у фінальній message_delta).")
'''
    ),
    code(
        '''
# Симуляція розподілу max_tokens: мислення не додається зверху, а віднімається від тексту.
def plan_output_budget(max_tokens: int, thinking_tokens: int, text_tokens: int) -> dict:
    """max_tokens — жорстка межа на СУМАРНИЙ вихід (міркування + текст)."""
    used = thinking_tokens + text_tokens
    return {
        "max_tokens": max_tokens,
        "мислення": thinking_tokens,
        "текст_отримав": max(0, min(text_tokens, max_tokens - thinking_tokens)),
        "stop_reason": "max_tokens" if used > max_tokens else "end_turn",
        "запас": max_tokens - used,
    }


budget_header = f"{'max_tokens':>11} {'мислення':>9} {'текст':>6} {'stop_reason':>12} {'запас':>7}"
print(budget_header)
print("-" * len(budget_header))
for budget_cap in (4_096, 8_000, 16_000, 64_000):
    for budget_thinking in (300, 3_500):
        plan = plan_output_budget(budget_cap, budget_thinking, 800)
        print(f"{plan['max_tokens']:>11} {plan['мислення']:>9} {plan['текст_отримав']:>6} "
              f"{plan['stop_reason']:>12} {plan['запас']:>7}")

print()
print("Орієнтир із довідки: на xhigh/max для Opus 5 стартуйте з max_tokens >= 64 000.")
print("SDK вимагають стрімінгу, коли max_tokens > 21 333 (клієнтська перевірка).")
print("Кожен запит циклу інструментів має ВЛАСНИЙ max_tokens — він не обмежує хід цілком.")
'''
    ),

    # ── 8.4 ──────────────────────────────────────────────────────────────
    md(
        """
## 8.4 Збереження блоків мислення між ходами

Правила: усередині ходу з інструментами блоки повертати **обов'язково**, між ходами —
**рекомендовано**, поза використанням інструментів їх можна не передавати. Що API зробить із
блоками попередніх ходів, залежить від моделі.
"""
    ),
    code(
        '''
# Політика збереження блоків мислення (research/02/thinking.md, context-windows.md).
KEEP_ALL_MODELS = {"claude-opus-5", "claude-opus-4-8", "claude-opus-4-7", "claude-opus-4-6",
                   "claude-opus-4-5", "claude-sonnet-5", "claude-sonnet-4-6",
                   "claude-fable-5-1", "claude-mythos-5-1", "claude-fable-5",
                   "claude-mythos-5", "claude-mythos-preview"}
LAST_TURN_ONLY_MODELS = {"claude-sonnet-4-5", "claude-haiku-4-5"}
RETENTION_BILLING = {
    "усі попередні ходи": "вхідні токени на кожному наступному запиті",
    "лише останній хід": "лише власний вихід ходу; далі скидаються",
}


def retention_policy(model: str) -> str:
    if model in KEEP_ALL_MODELS:
        return "усі попередні ходи"
    if model in LAST_TURN_ONLY_MODELS:
        return "лише останній хід"
    return "невідомо — не вдалося підтвердити станом на 09.2026"


for retention_model in ("claude-opus-5", "claude-sonnet-5", "claude-sonnet-4-6",
                        "claude-opus-4-8", "claude-sonnet-4-5", "claude-haiku-4-5"):
    policy = retention_policy(retention_model)
    print(f"{retention_model:20} {policy:20} {RETENTION_BILLING[policy]}")

print()
print("Наслідок для контексту: на keep-all-моделях мислення — звичайна історія діалогу,")
print("яка накопичується й тарифікується як вхід; на last-turn-only воно зникає саме.")
'''
    ),
    md(
        """
Із Fable 5.1 додається **перевірка префікса**: блок мислення чинний, лише доки `system`, `tools` і
всі повідомлення перед ним незмінні. Параметри поза цими трьома полями (`effort`, `max_tokens`,
`display`, `cache_control`) префікс не ламають.
"""
    ),
    code(
        '''
def classify_prefix_change(previous: dict, current: dict) -> dict:
    """Відтворює таблицю «Що вважається редагуванням» (preserved thinking)."""
    if previous["system"] != current["system"]:
        return {"thinking": "invalid", "причина": "змінено top-level system"}
    if previous["tools"] != current["tools"]:
        return {"thinking": "invalid", "причина": "tools додано/видалено/змінено"}
    old_messages, new_messages = previous["messages"], current["messages"]
    if len(new_messages) < len(old_messages):
        return {"thinking": "invalid", "причина": "історію обрізали"}
    for position, old_message in enumerate(old_messages):
        if new_messages[position] != old_message:
            return {"thinking": "invalid",
                    "причина": f"messages[{position}] змінено або перевпорядковано"}
    return {"thinking": "valid", "причина": "лише дописування в кінець"}


PREFIX_BASE = {
    "system": "Ти — асистент.",
    "tools": [{"name": "read_file"}],
    "messages": [{"role": "user", "content": "Прочитай tests/test_auth.py"}],
}

PREFIX_CASES = {
    "додали новий хід у кінець":
        {**PREFIX_BASE, "messages": PREFIX_BASE["messages"] + [{"role": "assistant", "content": "ок"}]},
    "переписали system (додали дату)":
        {**PREFIX_BASE, "system": "Ти — асистент. Сьогодні 26.09.2026."},
    "додали інструмент у tools":
        {**PREFIX_BASE, "tools": [{"name": "read_file"}, {"name": "deploy"}]},
    "обрізали перший хід":
        {**PREFIX_BASE, "messages": []},
    "переписали контекст у першому ході":
        {**PREFIX_BASE, "messages": [{"role": "user", "content": "Прочитай src/auth.py"}]},
}

for prefix_case_name, prefix_case in PREFIX_CASES.items():
    verdict = classify_prefix_change(PREFIX_BASE, prefix_case)
    mark = "OK " if verdict["thinking"] == "valid" else "400"
    print(f"{mark} {prefix_case_name:38} {verdict['причина']}")

print()
print("Поза префіксом (thinking лишається valid): effort, max_tokens, output_config,")
print("tool_choice, metadata, thinking.display. Але зміна effort перезапускає КЕШ промпту.")


def resolve_prefix_mismatch(mismatch: bool, policy: str) -> str:
    """Поведінка задається thinking.block_binding.prefix_mismatch_behavior."""
    if not mismatch:
        return "відповідь як звичайно"
    if policy == "error":
        return "400 invalid_request_error з назвою першого невалідного блоку (типово)"
    return ("запит проходить; блоки скинуто, не тарифікуються; "
            "у input_transformations -> prefix_binding_mismatch")


print()
for mismatch_policy in ("error", "drop_block"):
    print(f"  prefix_mismatch_behavior={mismatch_policy:11} -> "
          f"{resolve_prefix_mismatch(True, mismatch_policy)}")
print("  (поле і input_transformations потребують заголовка thinking-binding-controls-2026-08-01)")
'''
    ),

    # ── 8.5 ──────────────────────────────────────────────────────────────
    md(
        """
## 8.5 Типові збої й діагностика

Збої діляться на помилки конфігурації (400 на старті) і тихі дефекти форми відповіді: порожній
`thinking`, відсутній блок мислення, обрив на `max_tokens`, витікання виклику інструмента в текст і
зниклі влучання кешу. Локальна таблиця нижче зіставляє симптом із причиною й дією.
"""
    ),
    code(
        '''
# Симптом -> причина -> дія (research/02/thinking-troubleshooting.md)
THINKING_DIAGNOSIS_RULES = [
    ('"thinking.type.enabled" is not supported for this model',
     "модель 4.7+ прибрала ручний режим extended thinking",
     'замініть на thinking={"type":"adaptive"} і керуйте глибиною через output_config.effort'),
    ('"thinking.type.disabled" is not supported for this model',
     "мислення на цій моделі вимкнути не можна (Always on)",
     'приберіть параметр thinking; щоб не показувати текст — display="omitted"'),
    ("adaptive thinking is not supported on this model",
     "модель підтримує лише legacy extended thinking (Opus 4.5, Haiku 4.5, Sonnet 4.5)",
     "використайте thinking={'type':'enabled','budget_tokens':N}"),
    ("blocks in the latest assistant message cannot be modified",
     "відповідь асистента перезібрали або відфільтрували блоки за типом",
     "повертайте хід асистента дослівно, разом із redacted_thinking"),
    ("Invalid `signature` in `thinking` block",
     "блок мислення прив'язаний до іншої розмови: префікс змінився",
     'тримайте історію append-only; або prefix_mismatch_behavior="drop_block"'),
    ("thinking field is empty",
     'display типово "omitted" на нових моделях',
     'додайте display="summarized", якщо текст мислення потрібен у UI'),
    ("no thinking block appears",
     "адаптивний режим: модель пропустила мислення на простому запиті",
     "підніміть effort або підштовхніть промптом; не покладайтесь на наявність блоку"),
    ("tool calls or XML tags appear in the text output",
     "на Opus 5 мислення вимкнено — модель витікає виклик у текст",
     "поверніть мислення і знижуйте effort замість вимкнення"),
    ("stop_reason: max_tokens",
     "мислення з'їло max_tokens (це жорстка межа на сумарний вихід)",
     "підніміть max_tokens або знизьте effort"),
    ("cache_read_input_tokens fell to zero",
     "зміна конфігурації thinking або рівня effort перезапускає префікс кешу",
     "тримайте конфігурацію й effort незмінними; явний high == відсутній параметр"),
]


def diagnose_thinking(symptom: str) -> dict:
    """Знаходить перше правило, чий зразок трапляється в симптомі."""
    lowered = symptom.lower()
    for pattern, cause, fix in THINKING_DIAGNOSIS_RULES:
        if pattern.lower() in lowered:
            return {"причина": cause, "дія": fix}
    return {"причина": "не вдалося підтвердити станом на 09.2026",
            "дія": "зберіть request_id і тіло запиту, перевірте таблицю сумісності моделей"}


OBSERVED_SYMPTOMS = [
    '400: "thinking.type.enabled" is not supported for this model. Use "thinking.type.adaptive" ...',
    "400: adaptive thinking is not supported on this model",
    "response has stop_reason: max_tokens and no text block",
    "the thinking field is empty, signature present",
    "cache_read_input_tokens fell to zero after we changed output_config.effort",
    "tool calls or XML tags appear in the text output on opus-5",
    "щось дивне, чого немає в довідці",
]

for symptom_text in OBSERVED_SYMPTOMS:
    diagnosis = diagnose_thinking(symptom_text)
    print(f"• {symptom_text[:64]}")
    print(f"    причина: {diagnosis['причина']}")
    print(f"    дія    : {diagnosis['дія']}")
'''
    ),
    md(
        """
Порядок діагностики для 400 про підпис — від найдешевшого кроку до найдорожчого:
перевірити перебудову ходу асистента → фільтр блоків за типом → перерендер `system` чи контексту →
зміну `tools` посеред сесії → видалені нагадування → клієнтську компакцію → і аж тоді вмикати бета-
заголовок `thinking-binding-controls-2026-08-01` з `drop_block` і рахувати `input_transformations`.
"""
    ),

    # ── 8.6 ──────────────────────────────────────────────────────────────
    md(
        """
## 8.6 Мислення в циклі з інструментами

Із погляду моделі **цикл інструментів — це один хід асистента**. Тому: режим мислення не можна
перемикати всередині ходу; блоки мислення ходу асистента треба повертати **дослівно**; конфлікт
посеред ходу не дає помилки, а мовчки вимикає мислення для запиту.

Перевіримо третій пункт локально — без API.
"""
    ),
    code(
        '''
# Що станеться з ходом асистента при різних способах повернення його в наступний запит.
class ThinkingBlockModifiedError(Exception):
    """Те, що API повертає як 400 invalid_request_error."""


def echo_assistant_turn(original_content: list[dict], *, mode: str) -> list[dict]:
    """mode='verbatim' — як треба; 'type_filter' і 'rebuild' — типові помилки."""
    if mode == "verbatim":
        return [{"role": "assistant", "content": list(original_content)}]
    if mode == "type_filter":
        kept = [b for b in original_content if b.get("type") == "thinking"]
        return [{"role": "assistant", "content": kept}]
    rebuilt = [{"type": "text", "text": "готово"}
               for b in original_content if b.get("type") == "text"]
    return [{"role": "assistant", "content": rebuilt}]


def check_echoed_turn(original_content: list[dict], turn: list[dict]) -> str:
    """Мінімальна перевірка: блоки мислення мусять повернутися всі й незмінними."""
    sent = turn[0]["content"]
    original_thinking = [b for b in original_content
                         if b.get("type") in ("thinking", "redacted_thinking")]
    sent_thinking = [b for b in sent if b.get("type") in ("thinking", "redacted_thinking")]
    if len(sent_thinking) != len(original_thinking):
        raise ThinkingBlockModifiedError(
            "`thinking` or `redacted_thinking` blocks in the latest assistant message "
            "cannot be modified")
    for original_block, sent_block in zip(original_thinking, sent_thinking):
        if original_block != sent_block:
            raise ThinkingBlockModifiedError("Invalid `signature` in `thinking` block")
    return "хід прийнято"


assistant_turn_content = [
    {"type": "thinking", "thinking": "", "signature": "EqQBCgIYAhIM..."},
    {"type": "redacted_thinking", "data": "EosnCkYICxIM..."},
    {"type": "tool_use", "id": "toolu_01", "name": "get_weather",
     "input": {"location": "Paris"}},
]

for echo_mode in ("verbatim", "type_filter", "rebuild"):
    echoed = echo_assistant_turn(assistant_turn_content, mode=echo_mode)
    try:
        verdict_text = check_echoed_turn(assistant_turn_content, echoed)
        print(f"{echo_mode:12} блоків у ході={len(echoed[0]['content'])} -> {verdict_text}")
    except ThinkingBlockModifiedError as error:
        print(f"{echo_mode:12} блоків у ході={len(echoed[0]['content'])} -> 400: {error}")
'''
    ),
    code(
        '''
# Повний цикл ходу на рівні структур даних: мислення + tool_use -> tool_result -> текст.
# Це та сама послідовність, що й у реальному API, але без мережі.
def simulate_tool_turn() -> list[dict]:
    messages = [{"role": "user", "content": "Яка погода в Парижі?"}]
    messages.append({
        "role": "assistant",
        "content": [
            {"type": "thinking", "thinking": "", "signature": "EqQBCgIYAhIM..."},
            {"type": "tool_use", "id": "toolu_01", "name": "get_weather",
             "input": {"location": "Paris"}},
        ],
    })
    messages.append({"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": "toolu_01", "content": "20 C, ясно"},
    ]})
    # Продовження ходу: та сама конфігурація thinking, блоки мислення на місці.
    messages.append({"role": "assistant", "content": [{"type": "text", "text": "У Парижі 20 C і ясно."}]})
    return messages


turn_messages = simulate_tool_turn()
thinking_total = sum(len([b for b in m["content"] if b.get("type") == "thinking"])
                     for m in turn_messages if isinstance(m["content"], list))
tool_use_total = sum(len([b for b in m["content"] if b.get("type") == "tool_use"])
                     for m in turn_messages if isinstance(m["content"], list))
tool_result_total = sum(len([b for b in m["content"] if b.get("type") == "tool_result"])
                        for m in turn_messages if isinstance(m["content"], list))

print(f"повідомлень у циклі: {len(turn_messages)}")
print(f"блоків мислення: {thinking_total}, tool_use: {tool_use_total}, "
      f"tool_result: {tool_result_total}")
print("одна пара tool_use/tool_result -> один хід асистента, а не два")
print()
print("У циклі інструментів кожен запит має власний max_tokens: три запити по 16000")
print("можуть витратити 4 200 + 1 800 + 900 вихідних токенів — ліміт не обмежує хід цілком.")

assert thinking_total == 1 and tool_use_total == 1 and tool_result_total == 1
print()
print("✓ форма ходу відповідає правилам збереження блоків мислення")
'''
    ),
    md(
        """
Реальний виклик із ключем. Зверніть увагу на три речі: `thinking` увімкнений явно з
`display: "summarized"` (інакше текст міркування буде порожнім), відповідь читається **фільтром за
типом блоку**, а `usage.output_tokens_details.thinking_tokens` показує, скільки вихідних токенів
пішло на міркування.
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
        thinking_message = client.messages.create(
            model="claude-opus-4-8",
            max_tokens=16000,
            thinking={"type": "adaptive", "display": "summarized"},
            messages=[{"role": "user",
                       "content": "Знайди НСД чисел 1071 і 462 і поясни кроки."}],
        )
        for response_block in thinking_message.content:      # НЕ content[0]
            if response_block.type == "thinking":
                print("thinking:", (response_block.thinking or "")[:200])
            elif response_block.type == "text":
                print("text    :", response_block.text[:200])
        print("stop_reason:", thinking_message.stop_reason)
        details = getattr(thinking_message.usage, "output_tokens_details", None)
        print("output_tokens:", thinking_message.usage.output_tokens,
              "| thinking_tokens:", getattr(details, "thinking_tokens", "немає поля"))
    except Exception as exc:
        print(f"Помилка виклику API ({type(exc).__name__}): {exc}")
'''
    ),
    md(
        """
Другий API-приклад — повний хід із викликом інструмента. Ключове тут — `response.content`
додається до історії **як об'єкт**, а не перезібраний зі словників: саме дослівне повернення ходу
разом із блоками мислення робить другий запит валідним.
"""
    ),
    code(
        '''
# ПОТРЕБУЄ: ANTHROPIC_API_KEY у .env  +  pip install anthropic python-dotenv
WEATHER_TOOL_SPEC = {
    "name": "get_weather",
    "description": "Get current weather for a location",
    "input_schema": {
        "type": "object",
        "properties": {"location": {"type": "string", "description": "City name"}},
        "required": ["location"],
    },
}

if client is None:
    print("Клітинку пропущено: немає ANTHROPIC_API_KEY.")
else:
    try:
        loop_messages = [{"role": "user", "content": "What's the weather in Paris?"}]
        first_response = client.messages.create(
            model="claude-opus-4-8",
            max_tokens=16000,
            thinking={"type": "adaptive"},
            tools=[WEATHER_TOOL_SPEC],
            messages=loop_messages,
        )
        tool_calls = [b for b in first_response.content if b.type == "tool_use"]
        print("блоків мислення:", sum(1 for b in first_response.content if b.type == "thinking"),
              "| викликів інструмента:", len(tool_calls),
              "| stop_reason:", first_response.stop_reason)

        if tool_calls:
            # 1) Хід асистента повертається дослівно, з блоками thinking і redacted_thinking.
            loop_messages.append({"role": "assistant", "content": first_response.content})
            # 2) Результати інструментів — окремим ходом користувача.
            loop_messages.append({"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": call.id,
                 "content": "Current temperature in Paris: 20 C, sunny"}
                for call in tool_calls
            ]})
            second_response = client.messages.create(
                model="claude-opus-4-8",
                max_tokens=16000,
                thinking={"type": "adaptive"},       # та сама конфігурація, той самий хід
                tools=[WEATHER_TOOL_SPEC],
                messages=loop_messages,
            )
            for response_block in second_response.content:
                if response_block.type == "text":
                    print("text:", response_block.text)
        else:
            for response_block in first_response.content:
                if response_block.type == "text":
                    print("text:", response_block.text)
    except Exception as exc:
        print(f"Помилка виклику API ({type(exc).__name__}): {exc}")
'''
    ),

    # ── підсумок ─────────────────────────────────────────────────────────
    md(
        """
## Підсумок

**Головне з цього ноутбука:**

1. **Два режими.** Adaptive (`{"type": "adaptive"}`) — модель сама вирішує, чи думати. Legacy
   extended (`{"type": "enabled", "budget_tokens": N}`) — застарілий на Claude 4.6 і **400 на
   Claude 4.7 і новіших**. `budget_tokens` має бути ≥ 1024 і < `max_tokens`.
2. **Форма відповіді.** Блоки `thinking` ідуть **перед** текстом; `content[0]` не можна вважати
   текстом; `redacted_thinking` — окремий тип, який теж повертається назад.
3. **`display`.** `"summarized"` дає читабельний підсумок, `"omitted"` (типово на нових моделях) —
   порожнє поле зі справжнім підписом, `"updates"` (бета) — звіти про поступ між викликами.
4. **`effort`.** П'ять рівнів, типове значення `high`; явний `high` == відсутній параметр. Впливає
   на всі вихідні токени, включно з викликами інструментів. Не плутайте з `thinking`: `adaptive` —
   це режим, а не рівень.
5. **Гроші.** Токени міркування тарифікуються як вихідні навіть при порожньому `thinking`. Читайте
   `usage.output_tokens_details.thinking_tokens`. `max_tokens` — жорстка межа на сумарний вихід;
   `effort` — м'яка підказка.
6. **Збереження блоків.** Усередині ходу з інструментами повертати обов'язково; на моделях
   keep-all вони лишаються в контексті й тарифікуються як вхід.
7. **Перевірка префікса.** Зміна `system`, `tools` або будь-якого ранішого повідомлення інвалідує
   блоки мислення. Параметри поза префіксом (`effort`, `display`, `max_tokens`) — не інвалідують,
   але зміна `effort` перезапускає кеш промпту.
8. **Діагностика.** Помилки 400 мають точні тексти — зіставляйте їх із таблицею симптомів, а не
   вгадуйте. Тихий дефект небезпечніший за помилку: вимкнене мислення на Opus 5 витікає виклики
   інструментів у видимий текст.

**Куди далі:**

- Розділ 9 — механіка кешу промпту: чому зміна `effort` чи `budget_tokens` його перезапускає.
- Розділ 12 — повний цикл агента з `tool_use` і `tool_result`.
- Розділ 6 — вибір моделі: де `effort` дешевший за перехід на слабшу модель.
- Розділ 24 — як виміряти, що зниження `effort` не зіпсувало якість.

## Джерела

- [Anthropic — Thinking](https://platform.claude.com/docs/en/build-with-claude/thinking)
- [Anthropic — Effort](https://platform.claude.com/docs/en/build-with-claude/effort)
- [Anthropic — Steering thinking](https://platform.claude.com/docs/en/build-with-claude/thinking-steering-and-cost)
- [Anthropic — Preserved thinking](https://platform.claude.com/docs/en/build-with-claude/preserved-thinking)
- [Anthropic — Thinking in tool and multi-turn workflows](https://platform.claude.com/docs/en/build-with-claude/thinking-tool-workflows)
- [Anthropic — Troubleshooting thinking](https://platform.claude.com/docs/en/build-with-claude/thinking-troubleshooting)
- [Anthropic — Extended thinking](https://platform.claude.com/docs/en/build-with-claude/extended-thinking)
- [Anthropic — Context windows](https://platform.claude.com/docs/en/build-with-claude/context-windows)
- [Anthropic — Pricing](https://platform.claude.com/docs/en/about-claude/pricing)
- [Anthropic — Migrating to Claude Opus 5](https://platform.claude.com/docs/en/models/opus-5/migration-guide)

Джерела збережено локально: `research/02/thinking.md`, `research/02/effort.md`,
`research/02/preserved-thinking.md`, `research/02/thinking-steering-and-cost.md`,
`research/02/thinking-troubleshooting.md`, `research/02/thinking-tool-workflows.md`,
`research/02/extended-thinking-legacy.md`, `research/02/context-windows.md`,
`research/02/pricing.md`, `research/02/migrating-opus-5.md`.
"""
    ),
]
