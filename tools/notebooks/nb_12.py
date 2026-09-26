"""Ноутбук 12 — «Tool use: схеми, tool_choice, цикл агента».

Розділ довідника: sections/12-tool-use.md
Працює без API-ключів і без GPU.

Цикл агента тут демонструється на СИМУЛЯТОРІ моделі: він повертає заздалегідь
записані відповіді з блоками tool_use, тож уся механіка циклу виконується
по-справжньому — без мережі й без ключа. Наприкінці є клітинка з реальним API.
"""

from nbkit import SETUP_CELL, VERSION_CELL, code, md

FILENAME = "12-tool-use.ipynb"
TITLE = "12. Tool use"

CELLS = [
    md(
        """
# 12. Tool use: схеми, tool_choice, цикл агента

**Розділ довідника:** [`sections/12-tool-use.md`](../sections/12-tool-use.md)

**Потрібно:** нічого — жодних ключів, жодного GPU.
Цикл агента тут працює на **симуляторі моделі**, тож уся механіка виконується по-справжньому.
Остання клітинка — з реальним API, потребує `ANTHROPIC_API_KEY`.

**Що ви зробите:**

1. Розберете структуру блоків `tool_use` і `tool_result`, включно з полем `toolset_name`.
2. Побудуєте **робочий цикл агента** й прогоните його на симуляторі — з паралельними викликами,
   помилкою інструмента й межею ітерацій.
3. Побачите, чому зіставлення за `id` критичне при паралельних викликах.
4. Перевірите, що помилка, повернута як `is_error`, не ламає цикл — модель бачить її як дані.
5. Порахуєте, у скільки разів багатокроковий агент дорожчий за однокроковий.
6. Розберете податок автоматичного системного промпту tool use.

> Головна ідея розділу: **tool use — не RPC, а продовження генерації.** Кожен виклик інструмента
> це повний новий запит до API з усією історією.
"""
    ),
    md("## Налаштування"),
    code(SETUP_CELL),
    code(VERSION_CELL),

    # ── 12.1 структура ───────────────────────────────────────────────────
    md(
        """
## 12.1 Структура блоків: `tool_use` і `tool_result`

Блок `tool_use` містить три поля, які треба знати точно: `id`, `name`, `input`.
Для членів наборів computer/browser додається `toolset_name`.

Блок `tool_result` посилається на виклик через `tool_use_id` і має необов'язкове поле `is_error`.
Побудуємо обидві структури.
"""
    ),
    code(
        '''
from dataclasses import dataclass, field


@dataclass
class ToolUse:
    """Блок tool_use з відповіді моделі."""
    id: str
    name: str
    input: dict
    type: str = "tool_use"
    toolset_name: str | None = None   # "computer" або "browser" для відповідних наборів


@dataclass
class ToolResult:
    """Блок tool_result, який ВИ надсилаєте назад."""
    tool_use_id: str                  # ← зіставлення з tool_use саме за id
    content: str
    type: str = "tool_result"
    is_error: bool = False            # помилка як ДАНІ, а не виняток


@dataclass
class Response:
    """Мінімальне подання відповіді моделі."""
    stop_reason: str
    content: list = field(default_factory=list)


# Приклад: паралельні виклики в одному ході (типова поведінка!)
resp = Response(
    stop_reason="tool_use",
    content=[
        ToolUse(id="toolu_01A", name="get_weather", input={"location": "Kyiv"}),
        ToolUse(id="toolu_01B", name="get_weather", input={"location": "Lviv"}),
        ToolUse(id="toolu_01C", name="screenshot", input={},
                toolset_name="computer"),
    ],
)

print(f"stop_reason = {resp.stop_reason!r}")
print(f"блоків у відповіді: {len(resp.content)}")
print()
for b in resp.content:
    extra = f"  toolset_name={b.toolset_name!r}" if b.toolset_name else ""
    print(f"  id={b.id}  name={b.name}  input={b.input}{extra}")

print()
print("Зверніть увагу: викликів ТРИ, і кожен має власний id.")
print("Код, який обробляє лише content[0], загубить два з трьох.")
'''
    ),

    # ── цикл агента ──────────────────────────────────────────────────────
    md(
        """
## 12.1 Цикл агента на симуляторі

Канонічна форма з документації — `while`-цикл, прив'язаний до `stop_reason`: доки
`stop_reason == "tool_use"`, виконуйте інструменти й продовжуйте розмову. Цикл виходить за будь-якого
іншого значення (`end_turn`, `max_tokens`, `stop_sequence`, `refusal`).

Щоб продемонструвати це **без API-ключа**, зробимо симулятор моделі, який повертає заздалегідь
записані відповіді. Механіка циклу при цьому справжня.
"""
    ),
    code(
        '''
class FakeModel:
    """Симулятор моделі: повертає заздалегідь записані відповіді по черзі.

    Використовується лише для демонстрації механіки циклу без мережі.
    """

    def __init__(self, script):
        self.script = list(script)
        self.calls = []            # журнал запитів — щоб бачити, що надсилалося

    def create(self, **kwargs):
        # ВАЖЛИВО: зберігаємо ЗНІМОК, а не посилання на список.
        # Інакше всі записи журналу вказують на той самий список, який
        # ми дописуємо далі, і показують фінальний стан замість стану кроку.
        snapshot = dict(kwargs)
        snapshot["messages"] = list(kwargs.get("messages", []))
        self.calls.append(snapshot)
        if not self.script:
            return Response(stop_reason="end_turn", content=[])
        return self.script.pop(0)


SCRIPT = [
    # Хід 1: модель просить ДВА незалежні виклики паралельно
    Response(stop_reason="tool_use", content=[
        ToolUse(id="toolu_1", name="get_weather", input={"location": "Kyiv"}),
        ToolUse(id="toolu_2", name="get_weather", input={"location": "Lviv"}),
    ]),
    # Хід 2: модель викликає інструмент із ПОМИЛКОЮ в параметрах
    Response(stop_reason="tool_use", content=[
        ToolUse(id="toolu_3", name="get_weather", input={}),   # немає location
    ]),
    # Хід 3: фінальна відповідь
    Response(stop_reason="end_turn", content=[
        type("TextBlock", (), {"type": "text", "text": "У Києві 14°C, у Львові 12°C."})(),
    ]),
]


def execute_tool(name: str, tool_input: dict) -> tuple[str, bool]:
    """Виконує інструмент. Повертає (текст, чи_була_помилка).

    Помилка НЕ викидається — вона повертається як дані, щоб модель
    могла на неї відреагувати.
    """
    if name != "get_weather":
        return f"Невідомий інструмент: {name}", True
    location = tool_input.get("location")
    if not location:
        return ("Не вказано обов'язковий параметр 'location'. "
                "Повтори виклик, вказавши назву міста."), True
    data = {"Kyiv": 14, "Lviv": 12}.get(location)
    if data is None:
        return f"Немає даних для {location!r}", True
    return f'{{"location": "{location}", "temp_c": {data}}}', False


def run_agent(model, user_message: str, max_iterations: int = 10) -> dict:
    """Цикл агента: виконує інструменти, доки модель не дасть фінальну відповідь."""
    messages = [{"role": "user", "content": user_message}]
    steps = 0

    while steps < max_iterations:
        response = model.create(messages=messages)
        steps += 1

        # Вихід за будь-якого stop_reason, крім "tool_use"
        if response.stop_reason != "tool_use":
            text = "".join(b.text for b in response.content if b.type == "text")
            return {"відповідь": text, "кроків": steps, "виконано викликів": steps - 1}

        tool_uses = [b for b in response.content if b.type == "tool_use"]
        messages.append({"role": "assistant", "content": response.content})

        # Результат на КОЖЕН виклик, зіставлення за id
        results = []
        for tu in tool_uses:
            output, is_error = execute_tool(tu.name, tu.input)
            results.append(ToolResult(tool_use_id=tu.id, content=output, is_error=is_error))
        messages.append({"role": "user", "content": results})

    return {"відповідь": "ДОСЯГНУТО МЕЖІ ІТЕРАЦІЙ", "кроків": steps, "виконано викликів": steps}


model = FakeModel(SCRIPT)
result = run_agent(model, "Яка погода в Києві та Львові?")
for k, v in result.items():
    print(f"  {k:18} {v}")
'''
    ),
    code(
        '''
# Подивимося, що САМЕ надсилалося на кожному кроці — це і є суть механіки.
print("Журнал запитів до моделі:")
print()
for i, call in enumerate(model.calls, 1):
    msgs = call["messages"]
    print(f"--- Крок {i}: {len(msgs)} повідомлень у запиті ---")
    for m in msgs:
        role = m["role"]
        if isinstance(m["content"], str):
            print(f"    [{role}] текст: {m['content'][:50]!r}")
        else:
            kinds = [getattr(b, "type", "?") for b in m["content"]]
            print(f"    [{role}] блоки: {kinds}")
    print()

print("Ключове спостереження: на кожному кроці надсилається ВСЯ історія.")
print("Саме тому вартість агента зростає нелінійно (див. 12.6).")
'''
    ),
    code(
        '''
# Перевіримо, що помилка НЕ зламала цикл: модель отримала її як дані
# й на наступному кроці дала фінальну відповідь.
step2_msgs = model.calls[2]["messages"]
last = step2_msgs[-1]
print("Останнє повідомлення третього запиту (результат із помилкою):")
for b in last["content"]:
    print(f"  type={b.type}  tool_use_id={b.tool_use_id}  is_error={b.is_error}")
    print(f"  content={b.content!r}")
print()
print("Цикл побачив is_error=True і продовжився — без жодного винятку.")
print("Якби ми викинули виняток, ця гілка просто впала б.")
'''
    ),

    # ── зіставлення за id ────────────────────────────────────────────────
    md(
        """
## 12.5 Зіставлення за `id`: чому це критично

При паралельних викликах результати треба зіставляти з викликами за `id`, а не за порядком чи
назвою. Покажемо, що буває при неправильному зіставленні.
"""
    ),
    code(
        '''
# Демонстрація: два виклики, результати виконуються НЕ в тому порядку
uses = [
    ToolUse(id="toolu_1", name="get_weather", input={"location": "Kyiv"}),
    ToolUse(id="toolu_2", name="get_weather", input={"location": "Lviv"}),
]

# Виконаємо у зворотному порядку (імітація паралельного виконання,
# де другий завершився швидше)
executed = {
    "toolu_1": execute_tool("get_weather", uses[0].input),
    "toolu_2": execute_tool("get_weather", uses[1].input),
}
ordered_outputs = [executed["toolu_2"][0], executed["toolu_1"][0]]   # 2-й прийшов першим


def results_by_id() -> list:
    """ПРАВИЛЬНО: зіставлення за tool_use_id."""
    return [ToolResult(tool_use_id=u.id, content=executed[u.id][0],
                       is_error=executed[u.id][1]) for u in uses]


def results_by_order() -> list:
    """НЕПРАВИЛЬНО: зіставлення за порядком надходження."""
    return [ToolResult(tool_use_id=u.id, content=ordered_outputs[i])
            for i, u in enumerate(uses)]


print("ПРАВИЛЬНО (за id):")
for u, r in zip(uses, results_by_id()):
    print(f"  {u.input['location']:6} -> {r.content}")
print()
print("НЕПРАВИЛЬНО (за порядком):")
for u, r in zip(uses, results_by_id()):
    pass
for u, r in zip(uses, results_by_order()):
    print(f"  {u.input['location']:6} -> {r.content}")

print()
print("У другому випадку Київ отримав температуру Львова. Помилки немає —")
print("просто неправильні дані, які модель вважатиме істинними.")
'''
    ),

    # ── 12.2 описи ───────────────────────────────────────────────────────
    md(
        """
## 12.2 Опис інструмента: головний фактор якості

Документація називає **надзвичайно докладні описи** безумовно найважливішим фактором
продуктивності інструментів і радить **щонайменше 3–4 речення** на опис. Побудуємо обидва варіанти
й перевіримо їх програмно.
"""
    ),
    code(
        '''
def describe_tool(tool: dict) -> dict:
    """Оцінює якість опису інструмента за правилами з документації."""
    desc = tool.get("description", "")
    sentences = [s for s in desc.replace("!", ".").replace("?", ".").split(".") if s.strip()]
    props = tool.get("input_schema", {}).get("properties", {})
    described_params = sum(
        1 for p in props.values() if isinstance(p, dict) and p.get("description")
    )
    return {
        "речень в описі": len(sentences),
        "рекомендовано ≥": 4,
        "опис достатній": len(sentences) >= 3,
        "параметрів": len(props),
        "параметрів з описом": described_params,
        "всі параметри описані": described_params == len(props),
        "має strict": tool.get("strict") is True,
    }


bad_tool = {
    "name": "search",
    "description": "Шукає інформацію.",
    "input_schema": {"type": "object", "properties": {"q": {"type": "string"}},
                     "required": ["q"]},
}

good_tool = {
    "name": "kb_search",
    "description": (
        "Шукає статті у внутрішній базі знань компанії. Використовуй, коли "
        "користувач питає про внутрішні процеси, політики або документацію "
        "продукту. НЕ використовуй для загальновідомих фактів — на них відповідай "
        "прямо. Повертає до 10 найрелевантніших уривків із ідентифікаторами джерел."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {"type": "string",
                      "description": "Пошуковий запит природною мовою, як питання."},
            "limit": {"type": "integer",
                      "description": "Скільки уривків повернути, 1-10."},
        },
        "required": ["query"],
    },
    "strict": True,
}

for label, tool in (("ПОГАНИЙ", bad_tool), ("ДОБРИЙ", good_tool)):
    print(f"--- {label}: {tool['name']} ---")
    for k, v in describe_tool(tool).items():
        print(f"    {k:24} {v}")
    print()
'''
    ),

    # ── 12.1 податок ─────────────────────────────────────────────────────
    md(
        """
## 12.1 Податок автоматичного системного промпту

Коли ви використовуєте `tools`, API **автоматично додає спеціальний системний промпт**. Його
розмір залежить від моделі й від `tool_choice` — це фіксована витрата на **кожен** запит.
"""
    ),
    code(
        '''
# Розмір автоматичного системного промпту tool use, у токенах.
# Джерело: таблиця з документації Anthropic.
TOOL_SYSTEM_PROMPT_TOKENS = {
    "claude-opus-5":    {"auto_or_none": 286, "any": 406},
    "claude-opus-4-8":  {"auto_or_none": 290, "any": 410},
    "claude-opus-4-7":  {"auto_or_none": 675, "any": 804},
    "claude-sonnet-5":  {"auto_or_none": 354, "any": 474},
    "claude-haiku-4-5": {"auto_or_none": 496, "any": 588},
}

print(f"{'модель':18} {'auto/none':>10} {'any':>8}   різниця")
print("-" * 50)
for model_id, t in TOOL_SYSTEM_PROMPT_TOKENS.items():
    diff = t["any"] - t["auto_or_none"]
    print(f"{model_id:18} {t['auto_or_none']:>10} {t['any']:>8}   +{diff}")

print()
print("Два висновки:")
print("  1. Різниця між моделями сягає 2.4× (286 на Opus 5 проти 675 на Opus 4.7).")
print("  2. 'any' дорожчий за 'auto' — примусовий виклик додає ~120 токенів.")
print()
print("Цей промпт СТАБІЛЬНИЙ між запитами, отже він кешується (розділ 9):")
print("рівень tools — найперший в ієрархії кешу, і він містить саме цей промпт.")
'''
    ),

    # ── 12.6 вартість ────────────────────────────────────────────────────
    md(
        """
## 12.6 Скільки коштує багатокроковий агент

Кожен крок пересилає **всю** попередню історію. Тому вартість зростає нелінійно.
"""
    ),
    code(
        '''
def agent_cost_usd(
    steps: int,
    *,
    system_and_tools_tokens: int,
    tool_result_tokens: int,
    assistant_tokens: int,
    price_in_per_mtok: float,
    price_out_per_mtok: float,
) -> dict:
    """Вартість агентної сесії з `steps` кроками інструментів.

    Кожен крок пересилає всю попередню історію, тож сумарний вхід зростає
    як сума арифметичної прогресії, а не лінійно.
    """
    total_in = 0
    for step in range(steps):
        history = step * (tool_result_tokens + assistant_tokens)
        total_in += system_and_tools_tokens + history + tool_result_tokens
    total_out = steps * assistant_tokens
    cost = (total_in / 1_000_000 * price_in_per_mtok
            + total_out / 1_000_000 * price_out_per_mtok)
    return {"кроків": steps, "усього вхідних токенів": total_in,
            "усього вихідних токенів": total_out, "вартість USD": round(cost, 6)}


print(f"{'кроків':>7} {'вхід':>10} {'вихід':>8} {'вартість':>12} {'проти 1 кроку':>15}")
print("-" * 58)
base = None
results = {}
for s in (1, 2, 5, 10, 20):
    r = agent_cost_usd(s, system_and_tools_tokens=1_500, tool_result_tokens=400,
                       assistant_tokens=300, price_in_per_mtok=5.0,
                       price_out_per_mtok=25.0)
    results[s] = r
    base = base or r["вартість USD"]
    print(f"{s:>7} {r['усього вхідних токенів']:>10} {r['усього вихідних токенів']:>8} "
          f"${r['вартість USD']:>11.6f} {r['вартість USD']/base:>14.1f}×")

print()
ratio = results[20]["вартість USD"] / results[1]["вартість USD"]
print(f"Двадцятикроковий агент коштує {ratio:.1f}× однокрокового,")
print("хоч вихідних токенів у нього лише у 20 разів більше.")
print("Уся нелінійність сидить у ВХОДІ — бо історія пересилається щоразу.")
'''
    ),
    code(
        '''
# Той самий розрахунок, але з кешуванням рівня tools (розділ 9).
# Автоматичний промпт + описи інструментів стабільні, отже читаються з кешу
# за 10% ціни входу на Opus 5.
CACHE_READ_FRAC = 0.10

def agent_cost_cached(steps: int, *, stable_tokens: int, volatile_in: int,
                      assistant_tokens: int, price_in: float, price_out: float) -> float:
    """Вартість, коли стабільна частина (tools + system) читається з кешу."""
    total = 0.0
    for step in range(steps):
        history = step * (volatile_in + assistant_tokens)
        total += (stable_tokens / 1e6 * price_in * CACHE_READ_FRAC
                  + (history + volatile_in) / 1e6 * price_in
                  + assistant_tokens / 1e6 * price_out)
    return total


no_cache = results[20]["вартість USD"]
with_cache = agent_cost_cached(20, stable_tokens=1_500, volatile_in=400,
                               assistant_tokens=300, price_in=5.0, price_out=25.0)
print(f"Агент на 20 кроків, Claude Opus 5:")
print(f"  без кешу:      ${no_cache:.6f}")
print(f"  з кешем tools: ${with_cache:.6f}")
print(f"  економія:      {1 - with_cache/no_cache:.1%}")
print()
print("Кеш дає менший ефект, ніж може здатися, бо основна маса входу —")
print("це ЗМІННА історія, яка кешу не підлягає. Це головний важіль")
print("і водночас головне обмеження: скорочуйте історію, а не лише кешуйте.")
'''
    ),

    # ── реальний API ─────────────────────────────────────────────────────
    md(
        """
## Перевірка на реальному API (необов'язково)

Наступна клітинка виконує той самий цикл проти справжнього Claude. Потрібен
`ANTHROPIC_API_KEY` у `.env` — без нього клітинка просто повідомить про пропуск.
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
        TOOLS = [{
            "name": "get_weather",
            "description": (
                "Повертає поточну погоду для вказаного міста. Використовуй, коли "
                "користувач питає про погоду зараз. Не повертає прогноз — лише "
                "поточні умови. Місто вказуй англійською назвою."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "location": {"type": "string",
                                 "description": "Назва міста, наприклад 'Kyiv'"},
                },
                "required": ["location"],
            },
        }]

        messages = [{"role": "user", "content": "Яка погода в Києві та Львові?"}]
        for step in range(5):
            resp = client.messages.create(model="claude-opus-5", max_tokens=1024,
                                          tools=TOOLS, messages=messages)
            print(f"Крок {step+1}: stop_reason={resp.stop_reason}")
            if resp.stop_reason != "tool_use":
                print("Фінальна відповідь:",
                      "".join(b.text for b in resp.content if b.type == "text"))
                break
            messages.append({"role": "assistant", "content": resp.content})
            tool_uses = [b for b in resp.content if b.type == "tool_use"]
            print(f"  викликів: {len(tool_uses)} -> {[t.name for t in tool_uses]}")
            out = [{
                "type": "tool_result",
                "tool_use_id": t.id,
                "content": f'{{"location": "{t.input.get("location")}", "temp_c": 14}}',
            } for t in tool_uses]
            messages.append({"role": "user", "content": out})
    except Exception as exc:
        print(f"Помилка виклику API ({type(exc).__name__}): {exc}")
'''
    ),

    # ── самоперевірка ────────────────────────────────────────────────────
    md(
        """
## Самоперевірка

Перевіряємо твердження розділу: механіку циклу, зіставлення за `id`, обробку помилок і арифметику
вартості.
"""
    ),
    code(
        '''
# ── 1. Цикл завершився коректно й обробив усі три ходи ───────────────────
assert result["відповідь"] == "У Києві 14°C, у Львові 12°C."
assert result["кроків"] == 3, f"очікувалось 3 кроки, отримано {result['кроків']}"
print(f"✓ цикл завершився за 3 кроки: {result['відповідь']!r}")

# ── 2. Паралельні виклики оброблено: результат на КОЖЕН, за id ──────────
step1 = model.calls[1]["messages"][-1]["content"]
assert isinstance(step1, list) and len(step1) == 2, "мало бути 2 результати на 2 виклики"
assert {r.tool_use_id for r in step1} == {"toolu_1", "toolu_2"}
print("✓ паралельні виклики: 2 результати, зіставлені за id")

# ── 3. Помилка повернута як дані, а не викинута ─────────────────────────
step2 = model.calls[2]["messages"][-1]["content"]
assert len(step2) == 1 and step2[0].is_error is True, "помилка мусить бути позначена is_error"
assert "location" in step2[0].content
print("✓ помилка повернута з is_error=True і цикл продовжився")

# ── 4. Помилкове зіставлення за порядком дає неправильні дані ───────────
by_id = results_by_id()
by_order = results_by_order()
assert by_id[0].content != by_order[0].content, \\
    "зіставлення за порядком мусить дати інший (неправильний) результат"
assert "Kyiv" in by_id[0].content and "Kyiv" not in by_order[0].content
print("✓ зіставлення за порядком дає дані не того міста — помилки при цьому немає")

# ── 5. Порожній location дає помилку, а не виняток ──────────────────────
out, err = execute_tool("get_weather", {})
assert err is True and "location" in out
out2, err2 = execute_tool("get_weather", {"location": "Kyiv"})
assert err2 is False and "14" in out2
print("✓ execute_tool: повертає (текст, is_error) замість винятку")

# ── 6. Межа ітерацій зупиняє нескінченний цикл ──────────────────────────
looping = FakeModel([Response(stop_reason="tool_use", content=[
    ToolUse(id=f"t{i}", name="get_weather", input={"location": "Kyiv"})])
    for i in range(50)])
r = run_agent(looping, "цикл", max_iterations=5)
assert r["кроків"] == 5 and "МЕЖІ" in r["відповідь"]
print("✓ межа ітерацій зупинила цикл на 5 кроках")

# ── 7. Опис інструмента: добрий проходить перевірку, поганий — ні ───────
assert describe_tool(bad_tool)["опис достатній"] is False
assert describe_tool(good_tool)["опис достатній"] is True
assert describe_tool(good_tool)["всі параметри описані"] is True
assert describe_tool(good_tool)["має strict"] is True
print("✓ перевірка описів: поганий відсіюється, добрий проходить")

# ── 8. Розмір автоматичного системного промпту узгоджений з джерелом ────
assert TOOL_SYSTEM_PROMPT_TOKENS["claude-opus-5"]["auto_or_none"] == 286
assert TOOL_SYSTEM_PROMPT_TOKENS["claude-opus-5"]["any"] == 406
assert TOOL_SYSTEM_PROMPT_TOKENS["claude-opus-4-7"]["auto_or_none"] == 675
assert TOOL_SYSTEM_PROMPT_TOKENS["claude-sonnet-5"]["any"] == 474
print("✓ розмір системного промпту tool use збігається з таблицею документації")

# ── 9. Вартість агента зростає нелінійно ────────────────────────────────
assert results[2]["вартість USD"] > results[1]["вартість USD"] * 2
assert results[20]["вартість USD"] > results[1]["вартість USD"] * 50
# Вихід зростає ЛІНІЙНО — уся нелінійність у вході
assert results[20]["усього вихідних токенів"] == 20 * results[1]["усього вихідних токенів"]
print(f"✓ вартість: 20 кроків = {results[20]['вартість USD']/results[1]['вартість USD']:.1f}× "
      f"від 1 кроку, при лінійному зростанні виходу")

# ── 10. Кеш допомагає, але не рятує від зростання історії ───────────────
assert with_cache < no_cache, "кеш мусить зменшувати вартість"
assert with_cache > no_cache * 0.5, "кеш не може дати понад 50% — історія не кешується"
print(f"✓ кеш tools: економія {1 - with_cache/no_cache:.1%} — обмежена, "
      f"бо історія змінна")

print()
print("Усі перевірки пройдено.")
'''
    ),

    # ── підсумок ─────────────────────────────────────────────────────────
    md(
        """
## Підсумок

**Головне з цього ноутбука:**

1. **Tool use — контракт, не RPC.** Модель генерує блок `tool_use`, ваш код виконує, результат
   повертається як `tool_result` у **новому** запиті.
2. **Кожен виклик — повний новий запит** з усією історією. Звідси нелінійне зростання вартості.
3. **Три категорії за місцем виконання:** ваші, зі схемою Anthropic (trained-in) і серверні. Для
   серверних ви **ніколи** не формуєте `tool_result`.
4. **Зіставлення результатів — за `tool_use_id`,** ніколи за порядком. Помилка дає неправильні
   дані без жодного винятку.
5. **Помилка повертається як `is_error: True`,** а не як виняток. Тоді модель може відреагувати.
6. **Межа ітерацій обов'язкова** — і як захист від зациклення, і як бюджетний запобіжник.
7. **Опис інструмента — головний фактор якості.** Документація радить 3–4+ речення, явні тригери
   й анти-тригери, об'єднання споріднених операцій, простори імен, `strict: true`.
8. **Автоматичний системний промпт** коштує 286–804 токени **на кожен запит**, залежно від моделі
   й `tool_choice`. Він стабільний, отже кешується.
9. **20-кроковий агент коштує ~59× однокрокового** — при лінійному зростанні виходу. Уся
   нелінійність у вході.
10. **Кеш допомагає лише частково:** основна маса входу — змінна історія, яка кешу не підлягає.
    Скорочуйте контекст, а не лише кешуйте.

**Куди далі:**

- Розділ 8 — блоки мислення в циклі з інструментами та обов'язок повертати їх із `tool_result`.
- Розділ 9 — кешування рівня `tools` і облік серій `tool_use` як однієї позиції.
- Розділ 13 — небезпечні інструменти (bash, code execution) і модель загроз.
- Розділ 14 — MCP: стандартизація цього контракту між застосунками.
- Розділ 25 — таймаути, бюджет і деградація в продакшн-агенті.

## Джерела

- [Anthropic — How tool use works](https://platform.claude.com/docs/en/agents-and-tools/tool-use/how-tool-use-works)
- [Anthropic — Define tools](https://platform.claude.com/docs/en/agents-and-tools/tool-use/define-tools)
- [Anthropic — Handle tool calls](https://platform.claude.com/docs/en/agents-and-tools/tool-use/handle-tool-calls)
- [Anthropic — Tool use overview](https://platform.claude.com/docs/en/agents-and-tools/tool-use/overview)
- [Anthropic — Prompt caching](https://platform.claude.com/docs/en/build-with-claude/prompt-caching)

Джерела збережено локально в `research/02/`: `how-tool-use-works.md`, `define-tools.md`,
`handle-tool-calls.md`, `tool-use.md`, `prompt-caching.md`.
"""
    ),
]
