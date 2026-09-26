"""Ноутбук 10 — «Масова обробка: Message Batches API».

Розділ довідника: sections/10-batches.md
Працює без API-ключів і без GPU.

Обмеження, ціни, чотири типи результатів і правила кешування в батчі взяті
з первинного джерела (research/02/batches.md) станом на 26.09.2026.
"""

from nbkit import SETUP_CELL, VERSION_CELL, code, md

FILENAME = "10-batches.ipynb"
TITLE = "10. Message Batches API"

CELLS = [
    md(
        """
# 10. Масова обробка: Message Batches API

**Розділ довідника:** [`sections/10-batches.md`](../sections/10-batches.md)

**Потрібно:** нічого — жодних ключів, жодного GPU.
Усі розрахунки тут — арифметика за обмеженнями й цінами з документації.
Клітинка з реальним API потребує `ANTHROPIC_API_KEY`.

**Що ви зробите:**

1. Перевірите ліміти батчу (100 000 запитів і 256 МБ) і навчитеся розбивати роботу на частини.
2. Побудуєте модель вартості й побачите, що **кеш і батч разом дають 78%, а не 60%**.
3. Змоделюєте **best-effort** влучання в кеш (типово 30%–98%) і побачите розкид бюджету.
4. Розберете **чотири типи результатів** і які з них не тарифікуються.
5. Відтворите пастку зіставлення результатів: **порядок не гарантовано**.
6. Побудуєте вирішувач «батч чи ні».

> Головна властивість: знижки кешу й батчу **складаються** — це множники, а не додавання відсотків.
"""
    ),
    md("## Налаштування"),
    code(SETUP_CELL),
    code(VERSION_CELL),

    # ── 10.1 ліміти ──────────────────────────────────────────────────────
    md(
        """
## 10.1 Ліміти й розбиття на частини

Батч обмежений **100 000 запитів або 256 МБ**, що буде досягнуто першим. Обидві межі треба
перевіряти: великі запити можуть упертися в розмір значно раніше за кількість.
"""
    ),
    code(
        '''
BATCH_MAX_REQUESTS = 100_000
BATCH_MAX_BYTES = 256 * 1024 * 1024        # 256 МБ
RESULTS_TTL_DAYS = 29
BATCH_EXPIRY_HOURS = 24


def batch_size_status(request_count: int, total_bytes: int) -> dict:
    """Чи влізе батч і яка межа спрацює першою."""
    by_count = request_count > BATCH_MAX_REQUESTS
    by_bytes = total_bytes > BATCH_MAX_BYTES
    if by_count and by_bytes:
        limit = "обидві межі перевищено"
    elif by_count:
        limit = "межа кількості запитів"
    elif by_bytes:
        limit = "межа розміру (256 МБ)"
    else:
        limit = None
    return {
        "запитів": request_count,
        "розмір МБ": round(total_bytes / 1024 / 1024, 1),
        "перевищено": limit is not None,
        "що спрацювало першим": limit or "—",
    }


# Типові випадки: середній запит з інструментами ~4 КБ
KB = 1024
cases = [
    (1_000,     1_000 * 4 * KB),
    (50_000,   50_000 * 4 * KB),
    (100_000, 100_000 * 4 * KB),
    (100_001, 100_001 * 4 * KB),
    (80_000,   80_000 * 4 * KB),          # 320 МБ — упирається в розмір
]

print(f"{'запитів':>9} {'розмір МБ':>11} {'перевищено':>12}  що спрацювало")
print("-" * 62)
for n, b in cases:
    r = batch_size_status(n, b)
    print(f"{r['запитів']:>9} {r['розмір МБ']:>11} {str(r['перевищено']):>12}  {r['що спрацювало першим']}")

print()
print("Зверніть увагу на останній рядок: 80 000 запитів — це МЕНШЕ за 100 000,")
print("але батч усе одно завеликий, бо перевищено 256 МБ. Межі незалежні.")
'''
    ),
    code(
        '''
def split_into_batches(requests: list[dict], max_requests: int = BATCH_MAX_REQUESTS,
                       max_bytes: int = BATCH_MAX_BYTES) -> list[list[dict]]:
    """Розбиває запити на батчі з дотриманням ОБОХ меж.

    Документація радить розбивати дуже великі набори на кілька батчів —
    це і краща керованість, і більше шансів завершитися за 24 години.
    """
    batches, current, current_bytes = [], [], 0
    for req in requests:
        size = len(str(req).encode("utf-8"))
        if current and (len(current) >= max_requests or current_bytes + size > max_bytes):
            batches.append(current)
            current, current_bytes = [], 0
        current.append(req)
        current_bytes += size
    if current:
        batches.append(current)
    return batches


# Приклад: 250 000 запитів — більше за одну межу
requests = [{"custom_id": f"req-{i}", "params": {"max_tokens": 256}} for i in range(250_000)]
batches = split_into_batches(requests)
print(f"Запитів усього: {len(requests)}")
print(f"Батчів: {len(batches)}")
print(f"Розміри батчів: {[len(b) for b in batches]}")
print()
print("Кожен батч <= 100 000 запитів — обидві межі дотримано.")
'''
    ),

    # ── 10.2 ціна ────────────────────────────────────────────────────────
    md(
        """
## 10.2 Ціна: множники, а не відсотки

Батч коштує рівно 50%. Кеш зменшує лише кешовану частину входу. Разом вони дають більше, ніж сума —
бо це множники.
"""
    ),
    code(
        '''
def cost_with_levers(input_tokens: int, output_tokens: int, *,
                     price_in: float, price_out: float,
                     cached_input_tokens: int = 0,
                     cache_read_frac: float = 0.10,
                     batch: bool = False) -> float:
    """Вартість із можливістю застосувати кеш і батч одночасно."""
    fresh = input_tokens - cached_input_tokens
    cost = (fresh / 1_000_000 * price_in
            + cached_input_tokens / 1_000_000 * price_in * cache_read_frac
            + output_tokens / 1_000_000 * price_out)
    return cost * 0.5 if batch else cost


# Масова евалюація: 50 000 запитів, у кожному 6000 кешованих токенів
# (промпт + описи інструментів) і 2000 змінних
PER_CACHED, PER_FRESH, PER_OUT, N = 6_000, 2_000, 300, 50_000
total_in = (PER_CACHED + PER_FRESH) * N
total_out = PER_OUT * N

print(f"{'конфігурація':30} {'вартість':>13} {'економія':>10}")
print("-" * 58)
base = None
for label, kw in (
    ("без оптимізацій", {}),
    ("+ батч", {"batch": True}),
    ("+ кеш", {"cached_input_tokens": PER_CACHED * N}),
    ("+ кеш і батч разом", {"cached_input_tokens": PER_CACHED * N, "batch": True}),
):
    c = cost_with_levers(total_in, total_out, price_in=5.0, price_out=25.0, **kw)
    base = base or c
    print(f"{label:30} ${c:>12.2f} {1 - c/base:>9.1%}")

print()
print("Кеш і батч разом дають 78.4%, а не 60% (50% + 10%).")
print("Причина: батч множить УСЕ на 0.5, а кеш зменшує ЛИШЕ кешовану")
print("частину входу — і вже після цього батч множить результат.")
print("Документація описує це як 'знижки складаються'.")
'''
    ),
    code(
        '''
# Кеш у батчі — BEST-EFFORT. Документація дає типовий діапазон 30%-98%.
def cost_range_by_cache_hit(hit_rates: list[float]) -> None:
    """Показує розкид вартості залежно від фактичного влучання в кеш."""
    print(f"{'влучань у кеш':>14} {'вартість':>13} {'проти 0%':>10}")
    print("-" * 42)
    zero = cost_with_levers(total_in, total_out, price_in=5.0, price_out=25.0,
                            batch=True)
    for rate in hit_rates:
        cached = int(PER_CACHED * N * rate)
        c = cost_with_levers(total_in, total_out, price_in=5.0, price_out=25.0,
                             cached_input_tokens=cached, batch=True)
        print(f"{rate:>13.0%} ${c:>12.2f} {c/zero:>9.1%}")


print("Батч із кешем: як фактичне влучання впливає на рахунок")
print()
cost_range_by_cache_hit([0.0, 0.30, 0.50, 0.80, 0.98, 1.0])
print()
print("Діапазон 30%-98% із документації — це не дрібниця: різниця між")
print("30% і 98% влучань на цьому обсязі становить сотні доларів.")
print("Тому плануйте бюджет за консервативною оцінкою, а не за оптимістичною.")
print()
print("Кеш у батчі не гарантований, бо запити обробляються асинхронно")
print("й паралельно. Три способи підвищити влучання (з документації):")
print("  1. Ідентичні блоки cache_control у КОЖНОМУ запиті батчу")
print("  2. Стабільний потік запитів (кеш живе 5 хвилин!)")
print("  3. Структура запитів, що ділить якнайбільше кешованого вмісту")
'''
    ),

    # ── 10.3 результати ──────────────────────────────────────────────────
    md(
        """
## 10.3 Чотири типи результатів — і за що ви не платите

Кожен запит у батчі отримує результат одного з чотирьох типів. **За три з чотирьох ви не платите.**
"""
    ),
    code(
        '''
RESULT_TYPES = {
    "succeeded": {"опис": "Запит успішний, містить результат повідомлення", "білінг": True},
    "errored":   {"опис": "Помилка: невалідний запит або внутрішня помилка сервера", "білінг": False},
    "canceled":  {"опис": "Батч скасовано до надсилання цього запиту моделі", "білінг": False},
    "expired":   {"опис": "Батч досяг 24-годинного протермінування до надсилання", "білінг": False},
}

print(f"{'тип':12} {'тарифікується':>14}  опис")
print("-" * 82)
for name, info in RESULT_TYPES.items():
    print(f"{name:12} {('ТАК' if info['білінг'] else 'НІ'):>14}  {info['опис']}")

print()
print("Практичний наслідок: запити з errored/canceled/expired не коштують нічого,")
print("але й результату не дають. Їх треба ПЕРЕЗАПУСКАТИ — окремою логікою.")


def billable_requests(request_counts: dict) -> int:
    """Скільки запитів у батчі підлягають оплаті."""
    return request_counts.get("succeeded", 0)


example_counts = {"succeeded": 49_500, "errored": 300, "canceled": 150, "expired": 50}
print()
print("Приклад request_counts:", example_counts)
print(f"Усього запитів:          {sum(example_counts.values()):,}")
print(f"Підлягає оплаті:         {billable_requests(example_counts):,}")
print(f"Не тарифікується:        {sum(example_counts.values()) - billable_requests(example_counts):,}")
'''
    ),
    code(
        '''
# Скасування дає ЧАСТКОВІ результати — це важливо практично.
def simulate_cancellation(total: int, processed_before_cancel: int) -> dict:
    """Імітує скасування батчу: статус і що вціліло."""
    return {
        "processing_status": "canceling",     # одразу після скасування
        "фінальний статус": "ended",
        "оброблено до скасування": processed_before_cancel,
        "часткові результати доступні": processed_before_cancel > 0,
        "решта запитів": total - processed_before_cancel,
        "статус решти": "canceled",
    }


r = simulate_cancellation(total=10_000, processed_before_cancel=3_200)
for k, v in r.items():
    print(f"  {k:34} {v}")
print()
print("Скасування НЕ означає втрату всієї роботи: оброблені запити")
print("повертаються як часткові результати. Решта отримує статус 'canceled'")
print("і за них ви не платите.")
'''
    ),
    code(
        '''
# ПОРЯДОК РЕЗУЛЬТАТІВ НЕ ГАРАНТОВАНО — зіставлення лише за custom_id.
import random

requests_sent = [f"task-{i:03d}" for i in range(10)]
# Результати приходять у ДОВІЛЬНОМУ порядку
returned = requests_sent[:]
random.seed(7)
random.shuffle(returned)

print("Надіслано:", requests_sent)
print("Повернуто:", returned)
print()


def match_by_position(sent: list[str], got: list[str]) -> dict:
    """НЕПРАВИЛЬНО: зіставлення за позицією."""
    return {sent[i]: got[i] for i in range(min(len(sent), len(got)))}


def match_by_custom_id(sent: list[str], got: list[str]) -> dict:
    """ПРАВИЛЬНО: зіставлення за custom_id."""
    return {cid: cid for cid in got}     # результат 'належить' своєму custom_id


by_pos = match_by_position(requests_sent, returned)
mismatched = [k for k, v in by_pos.items() if k != v]
print(f"Зіставлення за позицією: {len(mismatched)} з {len(requests_sent)} результатів "
      f"приписано НЕ тим запитам")
print(f"Приклади: {[(k, by_pos[k]) for k in mismatched[:4]]}")
print()
by_id = match_by_custom_id(requests_sent, returned)
assert all(k == v for k, v in by_id.items())
print("Зіставлення за custom_id: усі збігаються")
print()
print("Це та сама пастка, що зіставлення за порядком у tool use (розділ 12):")
print("помилки немає, просто результати приписані не тим запитам.")
'''
    ),

    # ── 10.4 діагностика ─────────────────────────────────────────────────
    md(
        """
## 10.4 Діагностика типових проблем

Документація перелічує конкретні перевірки. Зберемо їх у код.
"""
    ),
    code(
        '''
def diagnose_batch(problem: str) -> str:
    """Повертає перевірку для типового симптому (з документації)."""
    checks = {
        "413 request_too_large":
            "Загальний розмір батч-запиту не перевищує 256 МБ",
        "запити не обробляються":
            "Усі запити використовують підтримувані моделі",
        "невалідні запити":
            "Кожен запит має УНІКАЛЬНИЙ custom_id",
        "результати недоступні":
            "Минуло менше 29 днів від created_at (НЕ від ended_at)",
        "батч не завершується":
            "Батч не скасовано",
    }
    return checks.get(problem, "перевірте документацію")


print(f"{'симптом':30} що перевірити")
print("-" * 92)
for p in ("413 request_too_large", "запити не обробляються", "невалідні запити",
          "результати недоступні", "батч не завершується"):
    print(f"{p:30} {diagnose_batch(p)}")

print()
print("Нюанс у четвертому рядку: 29 днів рахуються від created_at, а не ended_at.")
print("Тобто тривалий батч має МЕНШИЙ запас на забирання результатів, ніж здається.")


def days_left_to_fetch(created_days_ago: float) -> float:
    """Скільки днів залишилося на забирання результатів."""
    return max(0.0, RESULTS_TTL_DAYS - created_days_ago)


print()
print(f"{'днів від створення':>20} {'залишилося':>12}")
print("-" * 36)
for d in (0, 10, 25, 29, 30):
    left = days_left_to_fetch(d)
    verdict = " результатів немає" if left == 0 else ""
    print(f"{d:>20} {left:>12.0f}{verdict}")
'''
    ),

    # ── 10.5 вирішувач ───────────────────────────────────────────────────
    md(
        """
## 10.5 Вирішувач: батч чи синхронні запити

Знижка 50% спокушає застосувати батч усюди. Побудуємо вирішувач, який цьому протистоїть.
"""
    ),
    code(
        '''
def should_batch(*, waits_for_user: bool, requests_per_run: int,
                 result_can_wait_hours: float, needs_streaming: bool,
                 is_cache_prewarm: bool) -> dict:
    """Радить, чи використовувати батч.

    Евристика на основі обмежень із документації; пороги обрані для ілюстрації.
    """
    blockers = []
    if waits_for_user:
        blockers.append("користувач чекає на відповідь — батч може тривати годину")
    if needs_streaming:
        blockers.append("потрібен стрімінг — stream: true не підтримується в батчі")
    if is_cache_prewarm:
        blockers.append("прогрів кешу — max_tokens: 0 не підтримується в батчі")
    if result_can_wait_hours < 1:
        blockers.append("результат потрібен швидше за типовий час батчу")
    if requests_per_run < 100:
        blockers.append(f"лише {requests_per_run} запитів — складність не окупається")

    return {
        "використовувати батч": not blockers,
        "перешкоди": blockers,
        "очікувана економія": "50%" if not blockers else "—",
    }


SCENARIOS = {
    "Евалюація 5000 кейсів уночі": dict(
        waits_for_user=False, requests_per_run=5000, result_can_wait_hours=8,
        needs_streaming=False, is_cache_prewarm=False),
    "Чат із користувачем": dict(
        waits_for_user=True, requests_per_run=1, result_can_wait_hours=0,
        needs_streaming=True, is_cache_prewarm=False),
    "Модерація 20 000 коментарів": dict(
        waits_for_user=False, requests_per_run=20_000, result_can_wait_hours=12,
        needs_streaming=False, is_cache_prewarm=False),
    "Прогрів кешу перед піком": dict(
        waits_for_user=False, requests_per_run=1, result_can_wait_hours=1,
        needs_streaming=False, is_cache_prewarm=True),
    "10 запитів на день": dict(
        waits_for_user=False, requests_per_run=10, result_can_wait_hours=24,
        needs_streaming=False, is_cache_prewarm=False),
}

for label, params in SCENARIOS.items():
    decision = should_batch(**params)
    verdict = "ТАК" if decision["використовувати батч"] else "НІ"
    print(f"--- {label} ---")
    print(f"    батч: {verdict}   економія: {decision['очікувана економія']}")
    for b in decision["перешкоди"]:
        print(f"      ✗ {b}")
    print()
'''
    ),

    # ── самоперевірка ────────────────────────────────────────────────────
    md(
        """
## Самоперевірка

Перевіряємо ліміти, арифметику знижок, типи результатів і логіку зіставлення.
"""
    ),
    code(
        '''
# ── 1. Ліміти батчу узгоджені з джерелом ────────────────────────────────
assert BATCH_MAX_REQUESTS == 100_000
assert BATCH_MAX_BYTES == 256 * 1024 * 1024
assert RESULTS_TTL_DAYS == 29
assert BATCH_EXPIRY_HOURS == 24
print("✓ ліміти: 100 000 запитів, 256 МБ, 29 днів, 24 години")

# ── 2. Межі незалежні: мала кількість, але великий розмір — теж перевищення
small_but_big = batch_size_status(80_000, 320 * 1024 * 1024)
assert small_but_big["перевищено"] is True
assert "розмір" in small_but_big["що спрацювало першим"]
print("✓ 80 000 запитів (менше за ліміт), але 320 МБ — перевищення за розміром")

# ── 3. Розбиття дотримує обидві межі ────────────────────────────────────
assert all(len(b) <= BATCH_MAX_REQUESTS for b in batches)
assert len(batches) >= 3, "250 000 запитів не влізуть в один батч"
assert sum(len(b) for b in batches) == 250_000, "розбиття не має губити запити"
print(f"✓ розбиття: 250 000 запитів -> {len(batches)} батчів, жодного загубленого")

# ── 4. Батч дає рівно 50% ───────────────────────────────────────────────
no_batch = cost_with_levers(total_in, total_out, price_in=5.0, price_out=25.0)
with_batch = cost_with_levers(total_in, total_out, price_in=5.0, price_out=25.0, batch=True)
assert abs(with_batch / no_batch - 0.5) < 1e-12
print("✓ батч: рівно 50% від базової вартості")

# ── 5. Кеш і батч разом дають БІЛЬШЕ за суму відсотків ──────────────────
cache_only = cost_with_levers(total_in, total_out, price_in=5.0, price_out=25.0,
                              cached_input_tokens=PER_CACHED * N)
both = cost_with_levers(total_in, total_out, price_in=5.0, price_out=25.0,
                        cached_input_tokens=PER_CACHED * N, batch=True)
saving_cache = 1 - cache_only / no_batch
saving_batch = 1 - with_batch / no_batch
saving_both = 1 - both / no_batch
assert saving_batch == 0.5
assert saving_both > saving_cache + saving_batch - 0.5, \\
    "комбінація не може бути просто сумою — це множники"
print(f"✓ знижки складаються: кеш {saving_cache:.1%} + батч {saving_batch:.0%} "
      f"= {saving_both:.1%} (не {saving_cache + saving_batch:.1%})")

# ── 6. Влучання в кеш лінійно зменшує вартість ──────────────────────────
costs = []
for rate in (0.0, 0.5, 1.0):
    c = cost_with_levers(total_in, total_out, price_in=5.0, price_out=25.0,
                         cached_input_tokens=int(PER_CACHED * N * rate), batch=True)
    costs.append(c)
assert costs[0] > costs[1] > costs[2], "більше влучань -> менша вартість"
print(f"✓ влучання 0%/${costs[0]:.2f}, 50%/${costs[1]:.2f}, 100%/${costs[2]:.2f}")

# ── 7. Типи результатів: платимо лише за succeeded ──────────────────────
assert RESULT_TYPES["succeeded"]["білінг"] is True
assert RESULT_TYPES["errored"]["білінг"] is False
assert RESULT_TYPES["canceled"]["білінг"] is False
assert RESULT_TYPES["expired"]["білінг"] is False
assert billable_requests(example_counts) == 49_500
assert len(RESULT_TYPES) == 4
print("✓ типи результатів: 4 типи, тарифікується лише succeeded")

# ── 8. Скасування дає часткові результати ───────────────────────────────
assert r["часткові результати доступні"] is True
assert r["фінальний статус"] == "ended"
assert r["статус решти"] == "canceled"
print("✓ скасування: часткові результати доступні, статус ended")

# ── 9. Зіставлення за позицією дає неправильні результати ───────────────
assert len(mismatched) > 0, "перемішаний порядок мусить дати розбіжності"
assert all(k == v for k, v in match_by_custom_id(requests_sent, returned).items())
print(f"✓ зіставлення: за позицією помиляється в {len(mismatched)} випадках, за custom_id — ніколи")

# ── 10. Термін зберігання рахується від created_at ──────────────────────
assert days_left_to_fetch(0) == 29
assert days_left_to_fetch(29) == 0
assert days_left_to_fetch(30) == 0
print("✓ термін зберігання: 29 днів від створення, далі результатів немає")

# ── 11. Вирішувач блокує батч у непридатних випадках ────────────────────
assert should_batch(**SCENARIOS["Чат із користувачем"])["використовувати батч"] is False
assert should_batch(**SCENARIOS["Модерація 20 000 коментарів"])["використовувати батч"] is True
assert should_batch(**SCENARIOS["Прогрів кешу перед піком"])["використовувати батч"] is False
assert should_batch(**SCENARIOS["10 запитів на день"])["використовувати батч"] is False
print("✓ вирішувач: блокує чат, прогрів кешу й малі обсяги; дозволяє модерацію")

print()
print("Усі перевірки пройдено.")
'''
    ),

    # ── підсумок ─────────────────────────────────────────────────────────
    md(
        """
## Підсумок

**Головне з цього ноутбука:**

1. **Батч коштує рівно 50%** — на все використання.
2. **Ліміт: 100 000 запитів або 256 МБ**, що перше. Межі **незалежні**: 80 000 запитів по 4 КБ
   упираються в розмір, а не в кількість.
3. **Типово 1 година**, протермінування — **24 години**, результати живуть **29 днів від
   `created_at`**, а не від `ended_at`.
4. **Знижки кешу й батчу складаються як множники:** разом вони дають **78.4%**, а не 60%. Документація
   формулює це прямо — «можуть складатися».
5. **Кеш у батчі — best-effort:** типово **30%–98%** влучань. Плануйте за консервативною оцінкою.
6. **Три способи підвищити влучання:** ідентичні `cache_control` у кожному запиті; стабільний потік
   (кеш живе 5 хвилин); структура, що ділить кешований вміст.
7. **Чотири типи результатів**, і платите ви лише за `succeeded`. `errored`, `canceled` і `expired`
   безкоштовні — але вимагають логіки перезапуску.
8. **Скасування не втрачає роботу:** оброблені запити повертаються як часткові результати.
9. **Порядок результатів не гарантовано** — зіставляйте за `custom_id`. Це та сама пастка, що
   зіставлення за порядком у tool use.
10. **Не все можна батчити:** `stream: true`, `speed` і `max_tokens: 0` дають помилку валідації.
11. **Зробіть пробний прогін однієї форми запиту** синхронно. Одна помилка схеми, розмножена на
    50 000 запитів, — це 50 000 безкоштовних, але марних записів `errored`.

**Куди далі:**

- Розділ 6 — чотири важелі вартості; батч — один із них.
- Розділ 9 — кешування промпту: множник, який складається з батчем.
- Розділ 12 — патерн `pause_turn` для серверних інструментів у батчі.
- Розділ 24 — масова евалюація: найприродніше застосування батчу.

## Джерела

- [Anthropic — Message Batches API](https://platform.claude.com/docs/en/build-with-claude/batch-processing)
- [Anthropic — Prompt caching](https://platform.claude.com/docs/en/build-with-claude/prompt-caching)
- [Anthropic — Rate limits](https://platform.claude.com/docs/en/api/rate-limits)

Джерело збережено локально: `research/02/batches.md`.
"""
    ),
]
