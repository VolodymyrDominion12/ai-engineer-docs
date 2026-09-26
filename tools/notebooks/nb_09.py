"""Ноутбук 09 — «Prompt caching: економія й діагностика».

Розділ довідника: sections/09-prompt-caching.md
Працює без API-ключів і без GPU.

Уся механіка кешу, ціни, TTL, мінімальні довжини й типи промахів у цьому
ноутбуку взяті з первинних джерел (research/02/prompt-caching.md,
research/02/cache-diagnostics.md) станом на 26.09.2026.
"""

from nbkit import SETUP_CELL, VERSION_CELL, code, md

FILENAME = "09-prompt-caching.ipynb"
TITLE = "9. Prompt caching"

CELLS = [
    md(
        """
# 09. Prompt caching: економія й діагностика

**Розділ довідника:** [`sections/09-prompt-caching.md`](../sections/09-prompt-caching.md)

**Потрібно:** нічого — жодних API-ключів, жодного GPU.
Єдина опційна частина — клітинка з реальним запитом, яка потребує `ANTHROPIC_API_KEY`.

**Що ви зробите:**

1. Змоделюєте ієрархію кешу `tools` → `system` → `messages` і побачите, чому зміна визначень
   інструментів знищує **весь** кеш.
2. Відтворите **20-блокове вікно пошуку назад** — механізм, який пояснює, чому кеш іноді
   «влучає не туди, де ви очікували».
3. Порахуєте економіку кешу: точку окупності для вашої моделі й вашого префіксу.
4. Перевірите мінімальні довжини промпту для кожної моделі — обмеження, яке найчастіше порушують
   не помічаючи, бо **помилки не повертається**.
5. Розберете розбивку `usage` і навчитеся визначати, чи кеш узагалі спрацював.
6. Розберете шість типів причин промаху з бета-функції cache diagnostics.

> Кеш промахується **тихо**: ні помилки, ні попередження — просто вищий рахунок. Цей ноутбук
> про те, як зробити промах видимим.
"""
    ),
    md("## Налаштування"),
    code(SETUP_CELL),
    code(VERSION_CELL),

    # ── 9.1 ──────────────────────────────────────────────────────────────
    md(
        """
## 9.1 Ієрархія кешу і чому порядок критичний

Кеш — це **префікс**. За документацією Anthropic він посилається на весь промпт у порядку
`tools` → `system` → `messages` до блоку з `cache_control` включно.

Ієрархія означає, що **зміна на одному рівні інвалідує цей рівень і всі наступні**. Змоделюємо це.
"""
    ),
    code(
        '''
# Три рівні кешу в порядку створення префіксів.
LEVELS = ["tools", "system", "messages"]

# Таблиця інвалідації з документації Anthropic:
# ✘ = кеш цього рівня інвалідовано, ✓ = залишається чинним
INVALIDATION = {
    "tool definitions": {"tools": False, "system": False, "messages": False},
    "system prompt":    {"tools": True,  "system": False, "messages": False},
    "earlier messages": {"tools": True,  "system": True,  "messages": False},
}

MARK = {True: "✓ чинний", False: "✘ ІНВАЛІДОВАНО"}

print(f"{'що змінилося':20} " + " ".join(f"{lv:>16}" for lv in LEVELS))
print("-" * 74)
for change, effects in INVALIDATION.items():
    row = " ".join(f"{MARK[effects[lv]]:>16}" for lv in LEVELS)
    print(f"{change:20} {row}")

print()
print("Головний висновок: зміна визначень інструментів знищує ВЕСЬ кеш.")
print("Саме тому tools стоїть першим у порядку — він найкрихкіший.")
'''
    ),
    md(
        """
Для `earlier messages` є важлива деталь, яку легко проґавити: інвалідація відбувається тоді, коли
раніший запис **змінено, перевпорядковано або видалено**, а не **додано**. Тобто нормальний
багатоходовий діалог, де ви лише додаєте повідомлення в кінець, кеш не руйнує — а от **обрізання
історії** руйнує.

### Три принципи точок розриву

Найважливіша частина механіки — як система знаходить попередній запис кешу.
"""
    ),
    code(
        '''
# Відтворимо 20-блокове вікно пошуку назад.
#
# Принцип 1: записи кешу відбуваються ЛИШЕ в точці розриву (один запис на точку).
# Принцип 2: читання дивиться НАЗАД — на записи, зроблені попередніми запитами.
# Принцип 3: вікно пошуку назад — 20 блоків, рахуючи саму точку першою.

LOOKBACK_WINDOW = 20


def prefix_hashes(blocks: list[str]) -> list[str]:
    """Кумулятивні хеші префіксів: hash[i] покриває блоки 0..i включно."""
    import hashlib
    out, acc = [], ""
    for b in blocks:
        acc += "\\x00" + b        # роздільник, щоб ["ab"] і ["a","b"] дали різні хеші
        out.append(hashlib.sha256(acc.encode()).hexdigest()[:8])
    return out


def find_cache_entry(blocks: list[str], cache: set[str]) -> dict:
    """Імітує пошук запису кешу: спершу в точці розриву, далі назад по блоках."""
    hashes = prefix_hashes(blocks)
    breakpoint = len(blocks) - 1          # точка розриву — останній блок
    checked = 0
    for offset in range(LOOKBACK_WINDOW):
        idx = breakpoint - offset
        if idx < 0:
            break
        checked += 1
        if hashes[idx] in cache:
            return {"found": True, "at_position": idx, "checked": checked,
                    "saved_blocks": idx + 1}
    return {"found": False, "at_position": None, "checked": checked, "saved_blocks": 0}


# Історія діалогу: додаємо по одному блоку за хід
turn1 = ["tools", "system", "user: привіт"]
cache = {prefix_hashes(turn1)[-1]}      # запис ЛИШЕ в точці розриву (останній блок)
print(f"Хід 1: записано в кеш, блоків {len(turn1)}")

for extra in range(1, 6):
    blocks = turn1 + [f"msg{ i }" for i in range(extra)]
    r = find_cache_entry(blocks, cache)
    print(f"Хід {extra+1}: блоків={len(blocks):>2}  знайдено={r['found']}  "
          f"перевірено позицій={r['checked']:>2}  збережено блоків={r['saved_blocks']}")
'''
    ),
    md(
        """
Кеш знаходиться **не в точці розриву** (бо її хеш новий — ми додали блоки), а **раніше**, за
рахунок пошуку назад. Це і є механізм, який документація називає ключовим: система шукає
**попередні записи**, а не стабільний контент.

Тепер подивимося, що станеться, якщо редагувати раніший блок.
"""
    ),
    code(
        '''
# Порівняємо три сценарії на одній і тій самій історії.
base = ["tools", "system", "user: привіт"]
cache = {prefix_hashes(base)[-1]}       # запис лише в точці розриву

scenarios = {
    "додали блок у кінець": base + ["user: нове питання"],
    "обрізали історію":     base[:-1],
    "змінили tools":        ["tools-v2", "system", "user: привіт"],
    "змінили system":       ["tools", "system-v2", "user: привіт"],
}

for label, blocks in scenarios.items():
    r = find_cache_entry(blocks, cache)
    verdict = "кеш влучив" if r["found"] else "ПРОМАХ"
    print(f"{label:24} -> {verdict}  (перевірено позицій: {r['checked']})")

print()
print("Зверніть увагу: 'додали блок у кінець' не ламає кеш — пошук назад знаходить")
print("старий запис. А обрізання, зміна tools і зміна system — ламають.")
'''
    ),
    md(
        """
### Вікно 20 блоків: коли воно стає вузьким

Обмеження вікна стає помітним у довгих діалогах: якщо між запитами додається багато блоків,
запис попереднього запиту виходить за межі 20 позицій.
"""
    ),
    code(
        '''
# Скільки блоків можна додати між запитами, щоб кеш ще влучав?
base = ["tools", "system", "user: привіт"]
cache = {prefix_hashes(base)[-1]}       # запис лише в точці розриву

print("Додано блоків | знайдено | перевірено позицій")
print("-" * 48)
for added in (1, 5, 19, 20, 21, 25):
    blocks = base + [f"x{i}" for i in range(added)]
    r = find_cache_entry(blocks, cache)
    print(f"{added:>13} | {str(r['found']):>8} | {r['checked']:>18}")

print()
print("Вікно — 20 позицій, рахуючи точку розриву першою.")
print("ВАЖЛИВО (з документації): на Claude API серія послідовних блоків tool_use")
print("рахується як ОДНА позиція — як і серія tool_result. Тож хід із багатьма")
print("паралельними викликами інструментів не виштовхує запис сам по собі.")
'''
    ),

    # ── 9.2 ціни ─────────────────────────────────────────────────────────
    md(
        """
## 9.2 Ціни: запис дорожчий, читання дешевше

Кеш — це інвестиція. Ви платите **більше зараз**, щоб платити **менше потім**.
"""
    ),
    code(
        '''
# Ціни за 1M токенів у USD — ПОВНА таблиця з документації Anthropic.
# Порядок полів: базовий вхід, запис 5 хв, запис 1 год, влучання/оновлення, вихід.
CACHE_PRICING = {
    "Claude Fable 5.1":  {"base_in": 10.0, "write_5m": 12.50, "write_1h": 20.0, "hit": 0.25, "out": 50.0},
    "Claude Mythos 5.1": {"base_in": 10.0, "write_5m": 12.50, "write_1h": 20.0, "hit": 0.25, "out": 50.0},
    "Claude Fable 5":    {"base_in": 10.0, "write_5m": 12.50, "write_1h": 20.0, "hit": 1.00, "out": 50.0},
    "Claude Mythos 5":   {"base_in": 10.0, "write_5m": 12.50, "write_1h": 20.0, "hit": 1.00, "out": 50.0},
    "Claude Opus 5":     {"base_in":  5.0, "write_5m":  6.25, "write_1h": 10.0, "hit": 0.50, "out": 25.0},
    "Claude Opus 4.8":   {"base_in":  5.0, "write_5m":  6.25, "write_1h": 10.0, "hit": 0.50, "out": 25.0},
    "Claude Opus 4.7":   {"base_in":  5.0, "write_5m":  6.25, "write_1h": 10.0, "hit": 0.50, "out": 25.0},
    "Claude Opus 4.6":   {"base_in":  5.0, "write_5m":  6.25, "write_1h": 10.0, "hit": 0.50, "out": 25.0},
    "Claude Opus 4.5":   {"base_in":  5.0, "write_5m":  6.25, "write_1h": 10.0, "hit": 0.50, "out": 25.0},
    "Claude Sonnet 5":   {"base_in":  2.0, "write_5m":  2.50, "write_1h":  4.0, "hit": 0.20, "out": 10.0},
    "Claude Sonnet 4.6": {"base_in":  3.0, "write_5m":  3.75, "write_1h":  6.0, "hit": 0.30, "out": 15.0},
    "Claude Sonnet 4.5": {"base_in":  3.0, "write_5m":  3.75, "write_1h":  6.0, "hit": 0.30, "out": 15.0},
    "Claude Sonnet 4":   {"base_in":  3.0, "write_5m":  3.75, "write_1h":  6.0, "hit": 0.30, "out": 15.0},
    "Claude Haiku 4.5":  {"base_in":  1.0, "write_5m":  1.25, "write_1h":  2.0, "hit": 0.10, "out":  5.0},
    "Claude Haiku 3.5":  {"base_in":  0.8, "write_5m":  1.00, "write_1h":  1.6, "hit": 0.08, "out":  4.0},
    "Claude Opus 4.1":   {"base_in": 15.0, "write_5m": 18.75, "write_1h": 30.0, "hit": 1.50, "out": 75.0},
    "Claude Opus 4":     {"base_in": 15.0, "write_5m": 18.75, "write_1h": 30.0, "hit": 1.50, "out": 75.0},
}

# Моделі, виведені з експлуатації (крім окремих платформ) — залишені для повноти таблиці.
RETIRED = {"Claude Opus 4.1", "Claude Opus 4", "Claude Sonnet 4", "Claude Haiku 3.5"}

print(f"{'модель':20} {'вхід':>7} {'запис5м':>9} {'запис1г':>9} {'читання':>9} {'читання/вхід':>13}")
print("-" * 74)
for name, p in CACHE_PRICING.items():
    ratio = p["hit"] / p["base_in"]
    mark = " (retired)" if name in RETIRED else ""
    print(f"{name:20} ${p['base_in']:>6.2f} ${p['write_5m']:>8.2f} ${p['write_1h']:>8.2f} "
          f"${p['hit']:>8.2f} {ratio:>12.1%}{mark}")

print()
print("Цікаве спостереження з таблиці: Claude Sonnet 5 ($2/$10) ДЕШЕВШИЙ за")
print("Claude Sonnet 4.6 і 4.5 ($3/$15). Новіше покоління тут не дорожче.")
print("Ставлення 'читання/вхід' однакове — 10% — для всіх, крім Fable 5.1 і Mythos 5.1 (2.5%).")
'''
    ),
    code(
        '''
def cache_economics(prefix_tokens: int, model: str, reads: int,
                    ttl: str = "5m") -> dict:
    """Порівнює вартість входу з кешем і без нього для серії однакових префіксів.

    prefix_tokens — розмір кешованого префіксу
    reads         — скільки разів префікс буде ПРОЧИТАНО після першого запису
    ttl           — "5m" або "1h"
    """
    p = CACHE_PRICING[model]
    write_price = p["write_5m"] if ttl == "5m" else p["write_1h"]
    base = prefix_tokens / 1_000_000 * p["base_in"]

    without = base * (reads + 1)                              # кожен запит платить повну ціну
    with_cache = (prefix_tokens / 1_000_000 * write_price) + \
                 (prefix_tokens / 1_000_000 * p["hit"]) * reads

    return {
        "без кешу": round(without, 6),
        "з кешем": round(with_cache, 6),
        "економія": round(1 - with_cache / without, 4),
        "вигідно": with_cache < without,
    }


PREFIX = 10_000     # токенів
print(f"Префікс {PREFIX:,} токенів, Claude Opus 5, TTL 5 хв")
print(f"{'читань':>7} {'без кешу':>12} {'з кешем':>12} {'економія':>10}")
print("-" * 46)
for reads in (0, 1, 2, 5, 10, 50):
    r = cache_economics(PREFIX, "Claude Opus 5", reads)
    flag = "" if r["вигідно"] else "  ← ЗБИТОК"
    print(f"{reads:>7} ${r['без кешу']:>11.6f} ${r['з кешем']:>11.6f} {r['економія']:>9.1%}{flag}")

print()
r0 = cache_economics(PREFIX, "Claude Opus 5", 0)
print(f"При нулі читань (кеш використано один раз) втрата: {-r0['економія']:.1%}")
'''
    ),
    md(
        """
Два висновки з таблиці вище:

1. **При одному використанні кеш збитковий.** Ви заплатили 1.25× за запис замість 1× — і жодного
   читання не отримали. Вмикати кешування там, де префікс використовується раз, — це втрата.
2. **З другого використання починається економія**, і вона швидко накопичується.

Перевіримо також, як впливає вибір TTL — запис на годину коштує 2× базової ціни входу.
"""
    ),
    code(
        '''
# TTL 5 хв проти 1 год: чи виправдана дорожча запис?
print(f"{'читань':>7} {'TTL 5хв':>12} {'TTL 1год':>12} {'дорожче на':>12}")
print("-" * 48)
for reads in (1, 5, 10, 50):
    r5 = cache_economics(PREFIX, "Claude Opus 5", reads, ttl="5m")
    r1 = cache_economics(PREFIX, "Claude Opus 5", reads, ttl="1h")
    extra = (r1["з кешем"] - r5["з кешем"]) / r5["з кешем"]
    print(f"{reads:>7} ${r5['з кешем']:>11.6f} ${r1['з кешем']:>11.6f} {extra:>11.1%}")

print()
print("TTL 1 год дорожчий завжди, але він виправданий, коли проміжок між")
print("запитами перевищує 5 хвилин. Якщо ваші запити частіші — беріть 5 хв.")
'''
    ),

    # ── 9.3 обмеження ────────────────────────────────────────────────────
    md(
        """
## 9.3 Мінімальна довжина: обмеження, яке ламає все тихо

Короткі промпти **не кешуються взагалі, навіть якщо позначені `cache_control`** — і **помилка не
повертається**. Це найчастіша причина «кеш не працює, але винятків немає».
"""
    ),
    code(
        '''
# Мінімальна довжина промпту для кешування — з документації Anthropic.
MIN_CACHEABLE_TOKENS = {
    "Claude Fable 5.1":    512,
    "Claude Mythos 5.1":   512,
    "Claude Opus 5":       512,
    "Claude Fable 5":      512,
    "Claude Mythos 5":     512,
    "Claude Opus 4.8":    1024,
    "Claude Sonnet 5":    1024,
    "Claude Sonnet 4.6":  1024,
    "Claude Sonnet 4.5":  1024,
    "Claude Mythos Preview": 2048,
    "Claude Opus 4.7":    2048,
    "Claude Opus 4.6":    4096,
    "Claude Opus 4.5":    4096,
    "Claude Haiku 4.5":   4096,
}


def will_cache(prefix_tokens: int, model: str) -> dict:
    """Чи буде промпт закешовано? Помилки не буде в жодному разі."""
    minimum = MIN_CACHEABLE_TOKENS[model]
    ok = prefix_tokens >= minimum
    return {
        "модель": model,
        "префікс": prefix_tokens,
        "мінімум": minimum,
        "закешується": ok,
        "бракує": 0 if ok else minimum - prefix_tokens,
    }


print("Ваш префікс 800 токенів:")
print()
for model in MIN_CACHEABLE_TOKENS:
    r = will_cache(800, model)
    status = "✓ закешується" if r["закешується"] else f"✗ НЕ закешується (бракує {r['бракує']})"
    print(f"  {model:22} мінімум {r['мінімум']:>4}  {status}")

print()
print("Зверніть увагу: для одних моделей той самий префікс спрацює, для інших — ні.")
print("І в жодному разі не буде помилки — лише вищий рахунок.")
'''
    ),
    md(
        """
Документація дає практичну пораду: якщо промпт **ледве не дотягує** до мінімуму, часто вигідно
**розширити кешований контент**, щоб досягти порогу — бо читання з кешу коштує значно менше за
несkешований вхід. Перевіримо цю пораду числом.
"""
    ),
    code(
        '''
# Чи вигідно ДОПИСАТИ контент, щоб досягти мінімуму?
MODEL = "Claude Opus 4.8"      # мінімум 1024 токени
MINIMUM = MIN_CACHEABLE_TOKENS[MODEL]
READS = 20                     # префікс використовується 20 разів

def cost_with_cache(prefix_tokens: int) -> float:
    return cache_economics(prefix_tokens, MODEL, READS, ttl="5m")["з кешем"]

def cost_without_cache(prefix_tokens: int) -> float:
    p = CACHE_PRICING[MODEL]
    return prefix_tokens / 1_000_000 * p["base_in"] * (READS + 1)

print(f"Модель: {MODEL}, мінімум для кешу: {MINIMUM} токенів, читань: {READS}")
print()
print(f"{'префікс':>9} {'без кешу':>12} {'з кешем':>12}   що станеться")
print("-" * 62)
for size in (900, 1000, 1024, 1200):
    if size < MINIMUM:
        c = cost_without_cache(size)     # не закешується -> платимо повну ціну
        note = f"НЕ закешується (бракує {MINIMUM-size})"
    else:
        c = cost_with_cache(size)
        note = "закешується"
    print(f"{size:>9} ${cost_without_cache(size):>11.6f} ${c:>11.6f}   {note}")

print()
print("Числа показують стрибок: дописати трохи контенту, щоб перетнути поріг,")
print("часто дешевше, ніж платити повну ціну за кожен із N запитів.")
'''
    ),
    md(
        """
### TTL: час генерації з'їдає час життя кешу

Деталь, яку легко проґавити: документація формулює прямо — **час життя відраховується від початку
запиту, який пише або читає запис, а не від завершення його відповіді**. Час генерації
**зараховується**.

Документація дає приклад: якщо відповідь стрімиться 4 хвилини, наступний запит мусить початися
приблизно протягом 1 хвилини після її завершення. Відтворимо логіку.
"""
    ),
    code(
        '''
TTL_SECONDS = 5 * 60

def time_left_for_next_request(generation_seconds: float) -> float:
    """Скільки часу лишається на наступний запит після генерації такої тривалості."""
    return TTL_SECONDS - generation_seconds


print(f"TTL кешу: {TTL_SECONDS} с (5 хв), відраховується від ПОЧАТКУ запиту")
print()
print(f"{'генерація, с':>13} {'лишається, с':>14}   висновок")
print("-" * 56)
for gen in (10, 60, 120, 240, 300):
    left = time_left_for_next_request(gen)
    if left <= 0:
        verdict = "кеш уже протермінований"
    elif left < 30:
        verdict = "вікно критично вузьке"
    else:
        verdict = "є час"
    print(f"{gen:>13} {left:>14.0f}   {verdict}")

print()
print("Практичний наслідок: довгі відповіді роблять 5-хвилинний кеш майже")
print("непридатним. Для таких сценаріїв розгляньте TTL 1 год (дорожчий запис).")
'''
    ),

    # ── 9.5 usage ────────────────────────────────────────────────────────
    md(
        """
## 9.5 Розбивка `usage`: як зрозуміти, чи кеш спрацював

Головна пастка: **`input_tokens` — це не всі вхідні токени, які ви надіслали.** Це лише токени
**після останньої точки розриву**. Загальна кількість обчислюється так:

```text
total_input_tokens = cache_read_input_tokens + cache_creation_input_tokens + input_tokens
```
"""
    ),
    code(
        '''
def cache_metrics(usage) -> dict:
    """Нормалізує розбивку usage у показники, придатні для моніторингу."""
    read = getattr(usage, "cache_read_input_tokens", 0) or 0
    created = getattr(usage, "cache_creation_input_tokens", 0) or 0
    fresh = usage.input_tokens or 0
    total = read + created + fresh
    return {
        "total_input_tokens": total,
        "cache_read": read,
        "cache_written": created,
        "uncached": fresh,
        # Якщо обидва нулі — промпт НЕ був закешований (найчастіше коротший за мінімум)
        "cache_was_used": bool(read or created),
        "cached_fraction": round((read + created) / total, 4) if total else 0.0,
    }


class Usage:
    def __init__(self, read=0, created=0, fresh=0):
        self.cache_read_input_tokens = read
        self.cache_creation_input_tokens = created
        self.input_tokens = fresh


# Приклад ІЗ ДОКУМЕНТАЦІЇ: 100 000 токенів із кешу, 0 нових, 50 токенів після точки розриву
doc_example = Usage(read=100_000, created=0, fresh=50)
m = cache_metrics(doc_example)
print("Приклад із документації:")
for k, v in m.items():
    print(f"  {k:22} {v}")
print()
print("  Усього оброблено вхідних токенів:", m["total_input_tokens"])
print("  ↑ дивлячись лише на input_tokens, здалося б, що запит майже безкоштовний")
print()
print("Перший запит (пише кеш):      ", cache_metrics(Usage(created=6000, fresh=200)))
print("Промах кешу (обидва нулі):    ", cache_metrics(Usage(read=0, created=0, fresh=200)))
'''
    ),

    # ── 9.4 діагностика ──────────────────────────────────────────────────
    md(
        """
## 9.4 Діагностика: шість типів причин промаху

Кеш промахується **тихо**. Без діагностики єдиний сигнал — `cache_read_input_tokens`, що впав до
нуля, без пояснення. Бета-функція cache diagnostics (заголовок `cache-diagnosis-2026-04-07`)
повідомляє **перше** місце розходження між запитами.
"""
    ),
    code(
        '''
# Шість типів cache_miss_reason — з документації Anthropic.
MISS_REASONS = {
    "model_changed": "Поле model відрізняється (роутер, A/B-тест, відкат). Кеш прив'язаний до моделі.",
    "system_changed": "Параметр system відрізняється — типово інтерпольовано мітку часу або ID запиту.",
    "tools_changed": "Масив tools відрізняється: додано, видалено, ПЕРЕВПОРЯДКОВАНО "
                     "або input_schema серіалізовано недетерміновано.",
    "messages_changed": "Раніший запис у messages змінено, перевпорядковано або видалено "
                        "замість додавання.",
    "previous_message_not_found": "Немає відбитка для переданого id. Це НЕ доказ, що запит змінився.",
    "unavailable": "Діагностика недоступна: збігаються model/system/tools, але відрізняється "
                   "інший параметр (tool_choice, thinking, output_config, anthropic-beta...).",
}

for i, (k, v) in enumerate(MISS_REASONS.items(), 1):
    print(f"{i}. {k}")
    print(f"   {v}")

print()
print("Два несподівані пункти:")
print("  • tools_changed може статися, навіть якщо ви НЕ міняли інструменти —")
print("    через недетерміновану серіалізацію JSON input_schema.")
print("  • model_changed: кеш прив'язаний до моделі. Відкат на дешевшу модель")
print("    при перевантаженні (розділ 25) руйнує кеш — це конфлікт двох оптимізацій.")
'''
    ),
    code(
        '''
def diagnose(first: dict, second: dict) -> str | None:
    """Мінімальний локальний аналог cache diagnostics.

    Порівнює два запити за структурою й повертає ПЕРШУ причину розходження,
    як це робить API (пізніші розходження приховані за найранішим).
    """
    if first.get("model") != second.get("model"):
        return "model_changed"
    if first.get("system") != second.get("system"):
        return "system_changed"
    if first.get("tools") != second.get("tools"):
        return "tools_changed"
    if first.get("messages") != second.get("messages"):
        # Додавання в кінець — НЕ промах; зміна ранішого — промах
        m1, m2 = first.get("messages", []), second.get("messages", [])
        if m2[:len(m1)] == m1:
            return None                      # лише дописали в кінець
        return "messages_changed"
    return None


base_req = {
    "model": "claude-opus-5",
    "system": "Ти — помічник.",
    "tools": [{"name": "get_weather"}],
    "messages": [{"role": "user", "content": "привіт"}],
}

cases = {
    "додали повідомлення в кінець": {**base_req, "messages": base_req["messages"] + [
        {"role": "assistant", "content": "вітаю"}]},
    "інша модель":                  {**base_req, "model": "claude-sonnet-5"},
    "мітка часу в system":          {**base_req, "system": "Ти — помічник. Час: 12:34:56"},
    "перевпорядковані tools":       {**base_req, "tools": [{"name": "get_weather"}, {"name": "search"}]},
    "обрізали історію":             {**base_req, "messages": []},
}

print(f"{'сценарій':32} причина промаху")
print("-" * 62)
for label, req in cases.items():
    reason = diagnose(base_req, req) or "— промаху немає"
    print(f"{label:32} {reason}")
'''
    ),

    # ── самоперевірка ────────────────────────────────────────────────────
    md(
        """
## Самоперевірка

Перевіряємо твердження розділу: механіку інвалідації, вікно пошуку, економіку, мінімальні
довжини й розбивку `usage`.
"""
    ),
    code(
        '''
# ── 1. Ієрархія інвалідації: tools ламає все ─────────────────────────────
assert INVALIDATION["tool definitions"] == {"tools": False, "system": False, "messages": False}, \\
    "зміна tools мусить інвалідувати всі три рівні"
assert INVALIDATION["system prompt"]["tools"] is True, \\
    "зміна system НЕ має чіпати кеш tools"
print("✓ ієрархія: зміна tools інвалідує все, зміна system — лише system і messages")

# ── 2. Додавання в кінець не ламає кеш, обрізання — ламає ────────────────
add_r = find_cache_entry(base + ["user: нове"], cache)
trim_r = find_cache_entry(base[:-1], cache)
assert add_r["found"] is True, "додавання блоку в кінець не має ламати кеш"
assert trim_r["found"] is False, "обрізання історії мусить ламати кеш"
print("✓ додавання в кінець -> кеш влучає; обрізання -> промах")

# ── 3. Вікно пошуку назад справді 20 позицій ─────────────────────────────
w19 = find_cache_entry(base + [f"x{i}" for i in range(19)], cache)
w21 = find_cache_entry(base + [f"x{i}" for i in range(21)], cache)
assert w19["found"] is True and w19["checked"] <= 20
assert w21["found"] is False, "за межами 20 позицій кеш не знаходиться"
print(f"✓ вікно пошуку: 19 доданих блоків -> знайдено ({w19['checked']} позицій), "
      f"21 -> не знайдено")

# ── 4. Ціни кешу узгоджені з джерелом ───────────────────────────────────
assert CACHE_PRICING["Claude Opus 5"]["base_in"] == 5.0
assert CACHE_PRICING["Claude Opus 5"]["write_5m"] == 6.25
assert CACHE_PRICING["Claude Opus 5"]["write_1h"] == 10.0
assert CACHE_PRICING["Claude Opus 5"]["hit"] == 0.50
assert CACHE_PRICING["Claude Fable 5.1"]["hit"] == 0.25
assert CACHE_PRICING["Claude Fable 5.1"]["write_1h"] == 20.0
print("✓ ціни кешу збігаються з таблицею документації")

# ── 5. Читання = 10% входу (Opus 5), 2.5% (Fable 5.1) ───────────────────
assert CACHE_PRICING["Claude Opus 5"]["hit"] / CACHE_PRICING["Claude Opus 5"]["base_in"] == 0.10
assert CACHE_PRICING["Claude Fable 5.1"]["hit"] / CACHE_PRICING["Claude Fable 5.1"]["base_in"] == 0.025
print("✓ частки читання: 10% на Opus 5, 2.5% на Fable 5.1")

# ── 6. Один запис без читань — збиток; з читаннями — вигода ─────────────
assert cache_economics(PREFIX, "Claude Opus 5", 0)["вигідно"] is False, \\
    "без читань кеш мусить бути збитковим"
assert cache_economics(PREFIX, "Claude Opus 5", 5)["вигідно"] is True, \\
    "з п'ятьма читаннями кеш мусить бути вигідним"
print("✓ економіка: 0 читань -> збиток, 5 читань -> вигода")

# ── 7. Мінімальні довжини: поріг справді блокує ─────────────────────────
assert will_cache(800, "Claude Opus 5")["закешується"] is True      # мінімум 512
assert will_cache(800, "Claude Haiku 4.5")["закешується"] is False  # мінімум 4096
assert will_cache(800, "Claude Haiku 4.5")["бракує"] == 4096 - 800
print("✓ мінімальні довжини: 800 токенів кешуються на Opus 5, але не на Haiku 4.5")

# ── 8. Розбивка usage відтворює приклад із документації ─────────────────
assert m["total_input_tokens"] == 100_050, f"очікувалось 100050, отримано {m['total_input_tokens']}"
assert m["cache_read"] == 100_000 and m["uncached"] == 50
print("✓ розбивка usage: 100000 + 0 + 50 = 100050, як у документації")

# ── 9. cache_was_used розрізняє промах від влучання ─────────────────────
assert cache_metrics(Usage(read=0, created=0, fresh=200))["cache_was_used"] is False
assert cache_metrics(Usage(created=6000, fresh=200))["cache_was_used"] is True
print("✓ cache_was_used: False при обох нулях (промах), True при записі")

# ── 10. TTL з'їдається часом генерації ──────────────────────────────────
assert time_left_for_next_request(240) == 60, "4 хв генерації лишають 1 хв — як у документації"
assert time_left_for_next_request(300) <= 0
print("✓ TTL: генерація 240 с лишає 60 с на наступний запит")

# ── 11. Локальна діагностика знаходить першу причину ────────────────────
assert diagnose(base_req, cases["інша модель"]) == "model_changed"
assert diagnose(base_req, cases["мітка часу в system"]) == "system_changed"
assert diagnose(base_req, cases["перевпорядковані tools"]) == "tools_changed"
assert diagnose(base_req, cases["обрізали історію"]) == "messages_changed"
assert diagnose(base_req, cases["додали повідомлення в кінець"]) is None
print("✓ діагностика: розрізняє всі чотири структурні причини й не скаржиться на дописування")

print()
print("Усі перевірки пройдено.")
'''
    ),

    # ── підсумок ─────────────────────────────────────────────────────────
    md(
        """
## Підсумок

**Головне з цього ноутбука:**

1. **Кеш — це префікс.** Він покриває `tools` → `system` → `messages` до точки розриву включно.
   Зміна на рівні інвалідує цей рівень і всі наступні. **Зміна визначень інструментів знищує все.**
2. **Записи лише в точці розриву.** Один запис — один кумулятивний хеш. Система не пише нічого
   для раніших позицій.
3. **Читання дивиться назад на 20 позицій.** Система шукає **попередні записи**, а не стабільний
   контент. Серія послідовних `tool_use` (або `tool_result`) рахується як одна позиція.
4. **Кеш — інвестиція з точкою окупності.** Запис коштує 1.25× (5 хв) або 2× (1 год) базової ціни
   входу; читання — 10% або 2.5%. Одне використання без читань дає збиток.
5. **Мінімальна довжина — тихий блокер.** Від 512 до 4096 токенів залежно від моделі. Нижче
   порогу кеш не спрацює й **помилки не буде**. Перевіряйте `cache_was_used`.
6. **Час генерації з'їдає TTL.** 4 хвилини стрімінгу лишають 1 хвилину на наступний запит.
7. **`input_tokens` — це не весь вхід.** Додавайте `cache_read_input_tokens` і
   `cache_creation_input_tokens`.
8. **Промахи діагностуються.** Шість типів причин; два несподівані — недетермінована серіалізація
   `input_schema` і `model_changed` (кеш прив'язаний до моделі, що конфліктує з відкатом).

**Порядок діагностики** — у розділі 9.6 файлу `sections/09-prompt-caching.md`: від найдешевших
перевірок (чи є `cache_control`, чи досягнуто мінімум) до бета-діагностики.

**Куди далі:**

- Розділ 6 — кеш як один із чотирьох важелів вартості.
- Розділ 8 — блоки мислення й те, як вони поводяться в кеші.
- Розділ 12 — серії `tool_use` / `tool_result` у циклі інструментів.
- Розділ 23 — моніторинг hit rate у продакшні.
- Розділ 25 — конфлікт між відкатом на іншу модель і кешем.

## Джерела

- [Anthropic — Prompt caching](https://platform.claude.com/docs/en/build-with-claude/prompt-caching)
- [Anthropic — Cache diagnostics](https://platform.claude.com/docs/en/build-with-claude/cache-diagnostics)
- [Anthropic — Context windows](https://platform.claude.com/docs/en/build-with-claude/context-windows)
- [Anthropic — Beta headers](https://platform.claude.com/docs/en/api/beta-headers)

Джерела збережено локально: `research/02/prompt-caching.md`, `research/02/cache-diagnostics.md`.
"""
    ),
]
