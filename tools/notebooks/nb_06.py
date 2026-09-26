"""Ноутбук 06 — «Вибір моделі: ціна, латентність, контекст, застарівання».

Розділ довідника: sections/06-vybir-modeli.md
Працює без API-ключів і без GPU.

Усі ціни, назви моделей і дати в цьому ноутбуку взяті з первинних джерел
(див. research/02/ і research/econ/) станом на 26.09.2026.
"""

from nbkit import SETUP_CELL, VERSION_CELL, code, md

FILENAME = "06-vybir-modeli.ipynb"
TITLE = "6. Вибір моделі"

CELLS = [
    md(
        """
# 06. Вибір моделі: ціна, латентність, контекст, застарівання

**Розділ довідника:** [`sections/06-vybir-modeli.md`](../sections/06-vybir-modeli.md)

**Потрібно:** нічого — жодних API-ключів, жодного GPU.

**Що ви зробите:**

1. Розберете формати model ID і навчитеся їх валідувати (формат без дати й з датою снапшота).
2. Побудуєте калькулятор вартості запиту з урахуванням кешу, батчу й тарифів довгого контексту.
3. Побачите, як чотири важелі (кеш, батч, час доби, `effort`) змінюють рахунок.
4. **Відтворите тиху поломку** — код, що читає відповідь за позицією, ламається, коли модель
   повертає блок мислення першим.
5. Порахуєте точку беззбитковості «локальна модель проти API».

> **Усі ціни й назви моделей тут — знімок на 26.09.2026.** Перед використанням у бюджеті
> перевірте сторінки провайдерів: ціни можуть бути оголошені заздалегідь і змінюються.
"""
    ),
    md("## Налаштування"),
    code(SETUP_CELL),
    code(VERSION_CELL),

    # ── 6.1 / 6.2 ────────────────────────────────────────────────────────
    md(
        """
## 6.1 Рівень зусилля як важіль замість зміни моделі

Документація Anthropic формулює ключове спостереження: **налаштування `effort` часто є кращим
важелем, ніж зміна моделі**. Замість двох інтеграційних шляхів — однієї моделі з керованим
зусиллям.

Нижче — рекомендації щодо стартових рівнів, узяті з документації.
"""
    ),
    code(
        '''
# Стартові рівні effort за документацією Anthropic.
EFFORT_GUIDANCE = {
    "claude-fable-5-1": {
        "default": "high",
        "note": "Почніть із типового 'high' і коригуйте за результатами евалюацій",
        "thinking": "Адаптивне, завжди увімкнене",
    },
    "claude-opus-5": {
        "default": "high",
        "note": "Почніть із типового 'high' і коригуйте за результатами евалюацій",
        "thinking": "Адаптивне",
    },
    "claude-opus-4-8": {
        "default": "xhigh",
        "note": "'xhigh' (між 'high' і 'max') — найкращий для кодування й агентних задач",
        "thinking": "Адаптивне",
    },
    "claude-opus-4-7": {
        "default": "xhigh",
        "note": "'xhigh' (між 'high' і 'max') — найкращий для кодування й агентних задач",
        "thinking": "Адаптивне",
    },
    "claude-haiku-4-5-20251001": {
        "default": None,
        "note": "Параметр effort не підтримується",
        "thinking": "Extended",
    },
}

print(f"{'модель':30} {'effort':8} мислення")
print("-" * 70)
for model, info in EFFORT_GUIDANCE.items():
    print(f"{model:30} {str(info['default'] or '—'):8} {info['thinking']}")
'''
    ),

    # ── 6.2 model IDs ────────────────────────────────────────────────────
    md(
        """
## 6.2 Формати model ID: валідація замість припущень

Model ID — це **зобов'язання**: за документацією Anthropic, модель залишається незмінною протягом
усього часу існування ID. Але гарантія поширюється на ID, **а не на псевдоніми**.

Формат змінився між поколіннями:

| Покоління | Формат | Приклад |
|---|---|---|
| 4.6 і пізніші | `claude-{name}-{major}[-{minor}]` | `claude-opus-5`, `claude-sonnet-4-6` |
| До 4.6 | `claude-{name}-{major}-{minor}-{YYYYMMDD}` | `claude-haiku-4-5-20251001` |
| Bedrock (4.6 і пізніші) | `anthropic.claude-{name}-{major}[-{minor}]` | `anthropic.claude-opus-5` |
| Bedrock (до 4.6) | `anthropic.claude-{name}-{major}-{minor}-{YYYYMMDD}-v1:0` | `anthropic.claude-sonnet-4-5-20250929-v1:0` |
| Google Cloud (до 4.6) | дата через `@` | `claude-{name}-{major}-{minor}@{YYYYMMDD}` |

Напишемо валідатор, який розрізняє формати замість того, щоб покладатися на око.
"""
    ),
    code(
        '''
import re
from datetime import datetime

# Формат без дати: покоління 4.6 і пізніші
RE_DATELESS = re.compile(
    r"^(?:anthropic\\.)?claude-(?P<name>[a-z]+)-(?P<major>\\d+)(?:-(?P<minor>\\d+))?$"
)

# Формат із датою снапшота: до покоління 4.6
RE_DATED = re.compile(
    r"^(?:anthropic\\.)?claude-(?P<name>[a-z]+)-(?P<major>\\d+)-(?P<minor>\\d+)-"
    r"(?P<date>\\d{8})(?:-v1:0)?$"
)

# Google Cloud до 4.6: дата через '@'
RE_AT = re.compile(
    r"^claude-(?P<name>[a-z]+)-(?P<major>\\d+)-(?P<minor>\\d+)@(?P<date>\\d{8})$"
)


def classify_model_id(model_id: str) -> dict:
    """Розбирає model ID і визначає його формат.

    Повертає словник із форматом, компонентами й (для датованих) датою снапшота.
    """
    for fmt, rx in (("dated (до 4.6)", RE_DATED),
                    ("at-дата (Google Cloud, до 4.6)", RE_AT),
                    ("dateless (4.6+)", RE_DATELESS)):
        m = rx.match(model_id)
        if not m:
            continue
        gd = m.groupdict()
        result = {
            "model_id": model_id,
            "format": fmt,
            "is_dated": "date" in gd and gd["date"] is not None,
            "pinned": True,   # ID завжди закріплений снапшот; псевдонім — ні
        }
        if result["is_dated"]:
            result["snapshot_date"] = datetime.strptime(gd["date"], "%Y%m%d").date().isoformat()
        return result
    return {"model_id": model_id, "format": "НЕВІДОМИЙ", "is_dated": None, "pinned": None}


SAMPLES = [
    "claude-opus-5",                              # 4.6+, без дати
    "claude-sonnet-5",
    "claude-sonnet-4-6",                          # 4.6+, з minor
    "claude-haiku-4-5-20251001",                  # до 4.6, із датою
    "claude-sonnet-4-5-20250929",
    "anthropic.claude-opus-5",                    # Bedrock, 4.6+
    "anthropic.claude-sonnet-4-5-20250929-v1:0",  # Bedrock, до 4.6
    "claude-sonnet-4-5@20250929",                 # Google Cloud, до 4.6
    "claude-haiku-4-5",                           # ПСЕВДОНІМ, але форма та сама, що в 4.6+
]

print(f"{'model ID':44} {'формат':32} {'снапшот'}")
print("-" * 92)
for s in SAMPLES:
    r = classify_model_id(s)
    print(f"{s:44} {r['format']:32} {r.get('snapshot_date', '—')}")

print()
print("ЗВЕРНІТЬ УВАГУ на останній рядок: 'claude-haiku-4-5' — це ПСЕВДОНІМ,")
print("але за формою він не відрізняється від закріпленого ID без дати.")
print("Форма рядка НЕ говорить, чи є він гарантією незмінності.")
print("Розрізнити їх можна лише за документацією провайдера, не регулярним виразом.")
'''
    ),

    # ── 6.3 ціни ─────────────────────────────────────────────────────────
    md(
        """
## 6.3 Таблиця цін і калькулятор вартості

Ціни за 1M токенів. **Anthropic** — із таблиці порівняння моделей; **OpenAI** — зі сторінки цін
(стандартний тариф).
"""
    ),
    code(
        '''
# Ціни за 1M токенів у USD. Джерела — див. розділ «Джерела» в кінці ноутбука.
PRICING_USD_PER_MTOK = {
    # Anthropic
    "claude-fable-5-1":          {"in": 10.00, "out": 50.00, "cache_read_frac": 0.025},
    "claude-opus-5":             {"in":  5.00, "out": 25.00, "cache_read_frac": 0.10},
    "claude-sonnet-5":           {"in":  2.00, "out": 10.00, "cache_read_frac": 0.10},
    "claude-haiku-4-5-20251001": {"in":  1.00, "out":  5.00, "cache_read_frac": 0.10},
    # OpenAI (короткий контекст; довгий — окремий тариф, див. нижче)
    "gpt-6-astra":               {"in": 10.00, "out": 50.00},
    "gpt-5.6-sol":               {"in":  4.00, "out": 20.00},
    "gpt-5.6-terra":             {"in":  2.00, "out": 12.00},
    "gpt-5.6-luna":              {"in":  0.20, "out":  1.20},
    # DeepSeek (позапікові ставки; пікові — рівно вдвічі вищі)
    "deepseek-flash":            {"in":  0.15, "out":  0.60, "peak_multiplier": 2.0},
    "deepseek-v4-pro":           {"in":  0.66, "out":  1.98, "peak_multiplier": 2.0},
}

# Окремий тариф довгого контексту в OpenAI: удвічі дорожчий за короткий.
OPENAI_LONG_CONTEXT = {
    "gpt-6-astra":   {"in": 20.00, "out": 75.00},
    "gpt-5.6-sol":   {"in":  8.00, "out": 30.00},
    "gpt-5.6-terra": {"in":  4.00, "out": 18.00},
    "gpt-5.6-luna":  {"in":  0.40, "out":  1.80},
}

print(f"{'модель':28} {'вхід':>8} {'вихід':>8}   примітка")
print("-" * 72)
for m, p in PRICING_USD_PER_MTOK.items():
    note = ""
    if "cache_read_frac" in p:
        note = f"читання кешу {p['cache_read_frac']:.1%} входу"
    if "peak_multiplier" in p:
        note = f"пікова ставка ×{p['peak_multiplier']:.0f}"
    if m in OPENAI_LONG_CONTEXT:
        note = f"довгий контекст ${OPENAI_LONG_CONTEXT[m]['in']:.2f}/${OPENAI_LONG_CONTEXT[m]['out']:.2f}"
    print(f"{m:28} ${p['in']:>7.2f} ${p['out']:>7.2f}   {note}")
'''
    ),
    code(
        '''
def request_cost_usd(
    model: str,
    input_tokens: int,
    output_tokens: int,
    *,
    cached_input_tokens: int = 0,
    batch: bool = False,
    off_peak: bool = True,
    long_context: bool = False,
) -> float:
    """Вартість одного запиту в USD за підтвердженими тарифами.

    batch           — знижка 50% (Anthropic, Mistral)
    off_peak        — для DeepSeek: пікова ставка рівно вдвічі вища
    long_context    — для OpenAI: окремий, удвічі дорожчий тариф
    """
    p = PRICING_USD_PER_MTOK[model]
    price_in, price_out = p["in"], p["out"]

    if long_context and model in OPENAI_LONG_CONTEXT:
        price_in = OPENAI_LONG_CONTEXT[model]["in"]
        price_out = OPENAI_LONG_CONTEXT[model]["out"]

    if p.get("peak_multiplier") and not off_peak:
        price_in *= p["peak_multiplier"]
        price_out *= p["peak_multiplier"]

    fresh = input_tokens - cached_input_tokens
    cache_frac = p.get("cache_read_frac", 1.0)   # без кешу вважаємо повну ціну

    cost = (
        fresh / 1_000_000 * price_in
        + cached_input_tokens / 1_000_000 * price_in * cache_frac
        + output_tokens / 1_000_000 * price_out
    )
    return cost * 0.5 if batch else cost


# Типовий запит: 4000 вхідних токенів, 800 вихідних
IN_TOK, OUT_TOK = 4000, 800

print(f"Запит: {IN_TOK} вхідних, {OUT_TOK} вихідних токенів")
print()
print(f"{'модель':28} {'вартість':>12}  відносно Haiku")
print("-" * 62)
baseline = request_cost_usd("claude-haiku-4-5-20251001", IN_TOK, OUT_TOK)
for m in PRICING_USD_PER_MTOK:
    c = request_cost_usd(m, IN_TOK, OUT_TOK)
    print(f"{m:28} ${c:>11.6f}  {c/baseline:>9.1f}×")
'''
    ),

    # ── 6.6 чотири важелі ────────────────────────────────────────────────
    md(
        """
## 6.6 Чотири важелі, що визначають рахунок

Ціна за токен — лише база. Порахуємо, як змінюється вартість під дією кожного важеля.
"""
    ),
    code(
        '''
# Сценарій: RAG-застосунок. Системний промпт і схема інструментів не змінюються
# між запитами, тому вони кешуються. Це типова ситуація.
SYS_AND_TOOLS = 6000     # кешована частина входу (промпт + описи інструментів)
RETRIEVED     = 2000     # змінюється щоразу — не кешується
OUTPUT        = 800

MODEL = "claude-opus-5"

no_cache = request_cost_usd(MODEL, SYS_AND_TOOLS + RETRIEVED, OUTPUT)
with_cache = request_cost_usd(MODEL, SYS_AND_TOOLS + RETRIEVED, OUTPUT,
                              cached_input_tokens=SYS_AND_TOOLS)
with_batch = request_cost_usd(MODEL, SYS_AND_TOOLS + RETRIEVED, OUTPUT,
                              cached_input_tokens=SYS_AND_TOOLS, batch=True)

print(f"Модель: {MODEL}, вхід {SYS_AND_TOOLS + RETRIEVED} (з них {SYS_AND_TOOLS} кешованих), вихід {OUTPUT}")
print()
for label, c in (("без оптимізацій", no_cache),
                 ("+ кеш промпту", with_cache),
                 ("+ батч (50%)", with_batch)):
    print(f"  {label:20} ${c:.6f}   економія {(1 - c/no_cache):>5.1%} від базової")
'''
    ),
    code(
        '''
# Важіль 3: час доби. DeepSeek — єдиний провайдер із підтвердженими
# піковими/позапіковими тарифами. Позапікові ставки РІВНО ВДВІЧІ нижчі.
# Пікові години: 01:00-04:00 і 06:00-10:00 UTC, пн-пт, крім свят КНР.

for model in ("deepseek-flash", "deepseek-v4-pro"):
    peak = request_cost_usd(model, IN_TOK, OUT_TOK, off_peak=False)
    off = request_cost_usd(model, IN_TOK, OUT_TOK, off_peak=True)
    print(f"{model:18} пік ${peak:.6f}   поза пік ${off:.6f}   відношення {peak/off:.2f}×")

print()
print("Порівняння з Claude Opus 5 на тому самому запиті:")
opus = request_cost_usd("claude-opus-5", IN_TOK, OUT_TOK)
ds = request_cost_usd("deepseek-v4-pro", IN_TOK, OUT_TOK, off_peak=True)
print(f"  claude-opus-5      ${opus:.6f}")
print(f"  deepseek-v4-pro    ${ds:.6f}  (поза пік, у {opus/ds:.1f}× дешевше)")
print()
print("УВАГА: дешевше ≠ краще для вашої задачі. Різницю в якості вимірюють")
print("евалюаціями на СВОЇХ даних (розділ 24), а не за ціною.")
'''
    ),
    code(
        '''
# Важіль 4: тариф довгого контексту в OpenAI.
# Перевищення порогу подвоює ціну ВСЬОГО запиту — і це стається мовчки.
LONG_TOK = 200_000

for model in ("gpt-5.6-terra",):
    short = request_cost_usd(model, LONG_TOK, OUT_TOK, long_context=False)
    long_ = request_cost_usd(model, LONG_TOK, OUT_TOK, long_context=True)
    print(f"{model}, {LONG_TOK} вхідних токенів:")
    print(f"  короткий контекст: ${short:.4f}")
    print(f"  довгий контекст:   ${long_:.4f}")
    print(f"  подорожчання:      {long_/short:.2f}×")
    print()
    print("  Висновок: 'додати ще документів' може подвоїти рахунок не через")
    print("  кількість токенів, а через сам факт перетину порогу.")
'''
    ),

    # ── 6.4 тиха поломка ─────────────────────────────────────────────────
    md(
        """
## 6.4 Тиха поломка при міграції: читання відповіді за позицією

Це найпідступніша з ламальних змін. За документацією міграції на Claude Opus 5: мислення
**увімкнене за замовчуванням**, відповідь може **починатися з блоків `thinking` перед першим блоком
`text`**, і оскільки `thinking.display` типово дорівнює `"omitted"`, ці блоки приходять із
**порожнім** полем `thinking` поряд із `signature`.

Наслідок: код на кшталт `content[0].text` починає падати. Відтворимо це локально.
"""
    ),
    code(
        '''
from dataclasses import dataclass, field


@dataclass
class Block:
    type: str
    text: str = ""
    signature: str = ""


@dataclass
class Message:
    content: list = field(default_factory=list)


# Відповідь ДО міграції (Claude Opus 4.6): перший блок — text
old_response = Message(content=[Block(type="text", text="Відповідь моделі.")])

# Відповідь ПІСЛЯ міграції (Claude Opus 5): спершу блок thinking
# з порожнім полем thinking (display="omitted"), але з signature
new_response = Message(content=[
    Block(type="thinking", text="", signature="ErUBCkYIBRgCIkA..."),
    Block(type="text", text="Відповідь моделі."),
])


def read_text_positional(msg: Message) -> str:
    """КРИХКИЙ спосіб: читає перший блок за позицією."""
    return msg.content[0].text


def read_text_by_type(msg: Message) -> str:
    """СТІЙКИЙ спосіб: явно відбирає блоки типу 'text'."""
    return "".join(b.text for b in msg.content if b.type == "text")


print("read_text_positional на старій відповіді :", repr(read_text_positional(old_response)))
print("read_text_by_type     на старій відповіді :", repr(read_text_by_type(old_response)))
print()
print("read_text_by_type     на новій відповіді  :", repr(read_text_by_type(new_response)))
print("read_text_positional на новій відповіді  :", repr(read_text_positional(new_response)), "← ПОРОЖНЬО!")
print()
print("Помилки немає. Винятку немає. Просто порожній рядок замість відповіді.")
print("Саме тому цю поломку важко помітити в логах і тестах.")
'''
    ),
    md(
        """
### Чому це саме «тиха» поломка

Зверніть увагу: `read_text_positional` **не падає** — вона повертає порожній рядок. Уявіть, що цей
код стоїть у конвеєрі, який далі класифікує відповідь або зберігає її в базу. Ви не побачите
винятку в моніторингу. Ви побачите порожні результати — або, гірше, не побачите й їх.

Якби блок `thinking` був відсутній, а `signature` був би на місці — код упав би, і це було б краще.
Тиха поведінка небезпечніша за гучну помилку.

**Правило:** ніколи не читайте `message.content` за індексом. Фільтруйте за типом блоку.
"""
    ),
    code(
        '''
# Перевірка: скільки ще «позиційних» читань є у вашому коді?
# Це можна знайти статично, ще до міграції.
import re
import pathlib

PATTERN = re.compile(r"content\\[0\\]|content\\[\\-1\\]")

# Демонстрація на вбудованому прикладі
sample_code = """
text = message.content[0].text          # крихко!
last = message.content[-1].text         # теж крихко
ok = [b for b in message.content if b.type == "text"]
"""
for i, line in enumerate(sample_code.splitlines(), 1):
    if PATTERN.search(line):
        print(f"рядок {i}: ЗНАЙДЕНО крихке читання -> {line.strip()}")

print()
print("Запустіть цей пошук по своєму репозиторію ПЕРЕД міграцією:")
print("  grep -rn 'content\\[0\\]\\|content\\[-1\\]' --include='*.py' .")
'''
    ),

    # ── 6.7 break-even ───────────────────────────────────────────────────
    md(
        """
## 6.7 Точка беззбитковості: локальна модель проти API

«Безкоштовно на своєму залізі» — поширена ілюзія. Локальний інференс не безкоштовний: це обладнання,
електрика і — головне — **амортизація вашого часу**. Порахуємо точку беззбитковості.
"""
    ),
    code(
        '''
def break_even_tokens_per_month(
    *,
    api_cost_per_mtok: float,
    hardware_usd: float,
    hardware_life_months: float,
    power_and_hosting_usd_month: float,
    engineer_hours_month: float,
    engineer_hourly_usd: float,
    local_cost_per_mtok: float = 0.0,
) -> dict:
    """Скільки токенів на місяць треба, щоб локальний варіант окупився.

    Повертає точку беззбитковості й розшифровку постійних витрат.
    """
    fixed_month = (
        hardware_usd / hardware_life_months
        + power_and_hosting_usd_month
        + engineer_hours_month * engineer_hourly_usd
    )
    saving_per_mtok = api_cost_per_mtok - local_cost_per_mtok
    if saving_per_mtok <= 0:
        return {"feasible": False, "fixed_month_usd": fixed_month}
    return {
        "feasible": True,
        "fixed_month_usd": fixed_month,
        "break_even_mtok_month": fixed_month / saving_per_mtok,
        "break_even_tokens_month": fixed_month / saving_per_mtok * 1_000_000,
    }


# ПРИКЛАД із довільними, але реалістичними припущеннями.
# ЗАМІНІТЬ їх на свої — числа тут ілюстративні, вони не з джерела.
r = break_even_tokens_per_month(
    api_cost_per_mtok=7.20,          # середня змішана ціна API за 1M токенів
    hardware_usd=8000.0,             # вартість GPU-сервера
    hardware_life_months=36.0,       # амортизація на 3 роки
    power_and_hosting_usd_month=120.0,
    engineer_hours_month=4.0,        # обслуговування, оновлення, діагностика
    engineer_hourly_usd=60.0,
)

print("Точка беззбитковості локального інференсу")
print("=" * 52)
print(f"Постійні витрати на місяць : ${r['fixed_month_usd']:,.0f}")
print(f"  з них амортизація заліза : ${8000/36:,.0f}")
print(f"  з них електрика/хостинг  : ${120:,.0f}")
print(f"  з них ЧАС ІНЖЕНЕРА       : ${4*60:,.0f}  ← найчастіше забувають")
print()
if r["feasible"]:
    print(f"Точка беззбитковості       : {r['break_even_mtok_month']:,.0f}M токенів/місяць")
    print(f"                             ({r['break_even_tokens_month']:,.0f} токенів)")
    print()
    print("Для порівняння, скільки це запитів:")
    for per_request in (1000, 5000, 50000):
        print(f"  ~{r['break_even_tokens_month']/per_request:,.0f} запитів по {per_request} токенів")
'''
    ),
    md(
        """
### Як читати цей результат

Зверніть увагу на структуру витрат: **час інженера виявився порівнянним з амортизацією заліза**.
Саме цей доданок найчастіше забувають, і саме він робить локальний інференс невигідним на малих
обсягах.

Дві межі цього розрахунку:

1. **Числа припущення, а не з джерела.** Вони ілюстративні. Замініть їх на свої — і результат може
   змінитися в рази.
2. **Не враховано якість.** Якщо задача вимагає frontier-якості, порівняння безпредметне незалежно
   від ціни.

Ситуації, коли локальний варіант виграє незалежно від розрахунку: дані не можуть покидати периметр;
потрібна повна відтворюваність (ваги закріплені); задача проста й обсяг дуже великий.
"""
    ),

    # ── самоперевірка ────────────────────────────────────────────────────
    md(
        """
## Самоперевірка

Клітинка перевіряє твердження з розділу. Якщо всі перевірки пройшли — числа й логіка узгоджені.
"""
    ),
    code(
        '''
# ── 1. Валідація форматів model ID ───────────────────────────────────────
assert classify_model_id("claude-opus-5")["format"] == "dateless (4.6+)"
assert classify_model_id("claude-haiku-4-5-20251001")["is_dated"] is True
assert classify_model_id("claude-haiku-4-5-20251001")["snapshot_date"] == "2025-10-01"
assert classify_model_id("claude-sonnet-4-5@20250929")["is_dated"] is True
assert classify_model_id("anthropic.claude-opus-5")["format"] == "dateless (4.6+)"
assert classify_model_id("не-модель")["format"] == "НЕВІДОМИЙ"
print("✓ model ID: формати розрізняються, дата снапшота видобувається коректно")

# ── 2. Ціни Anthropic узгоджені з джерелом ──────────────────────────────
assert PRICING_USD_PER_MTOK["claude-opus-5"]["in"] == 5.00
assert PRICING_USD_PER_MTOK["claude-opus-5"]["out"] == 25.00
assert PRICING_USD_PER_MTOK["claude-fable-5-1"]["in"] == 10.00
assert PRICING_USD_PER_MTOK["claude-fable-5-1"]["out"] == 50.00
assert PRICING_USD_PER_MTOK["claude-sonnet-5"]["in"] == 2.00
assert PRICING_USD_PER_MTOK["claude-haiku-4-5-20251001"]["out"] == 5.00
# читання кешу: 10% типово, 2.5% на Fable 5.1
assert PRICING_USD_PER_MTOK["claude-opus-5"]["cache_read_frac"] == 0.10
assert PRICING_USD_PER_MTOK["claude-fable-5-1"]["cache_read_frac"] == 0.025
print("✓ ціни Anthropic: вхід/вихід і частки кешу збігаються з джерелом")

# ── 3. Ціни OpenAI узгоджені з джерелом ─────────────────────────────────
assert PRICING_USD_PER_MTOK["gpt-6-astra"]["in"] == 10.00
assert PRICING_USD_PER_MTOK["gpt-6-astra"]["out"] == 50.00
assert PRICING_USD_PER_MTOK["gpt-5.6-luna"]["in"] == 0.20
assert OPENAI_LONG_CONTEXT["gpt-6-astra"]["in"] == 20.00   # рівно удвічі
assert OPENAI_LONG_CONTEXT["gpt-6-astra"]["out"] == 75.00
print("✓ ціни OpenAI: базові й тариф довгого контексту збігаються з джерелом")

# ── 4. Позапікова ставка DeepSeek рівно вдвічі нижча ────────────────────
peak = request_cost_usd("deepseek-v4-pro", IN_TOK, OUT_TOK, off_peak=False)
off = request_cost_usd("deepseek-v4-pro", IN_TOK, OUT_TOK, off_peak=True)
assert abs(peak / off - 2.0) < 1e-9, f"пік має бути рівно вдвічі дорожчим, отримано {peak/off}"
print("✓ DeepSeek: пікова ставка рівно ×2 від позапікової")

# ── 5. Батч дає рівно знижку 50% ────────────────────────────────────────
normal = request_cost_usd("claude-opus-5", IN_TOK, OUT_TOK)
batched = request_cost_usd("claude-opus-5", IN_TOK, OUT_TOK, batch=True)
assert abs(batched / normal - 0.5) < 1e-9
print("✓ батч: знижка рівно 50%")

# ── 6. Кеш зменшує вартість, але не робить її нульовою ──────────────────
cached = request_cost_usd("claude-opus-5", SYS_AND_TOOLS + RETRIEVED, OUTPUT,
                          cached_input_tokens=SYS_AND_TOOLS)
uncached = request_cost_usd("claude-opus-5", SYS_AND_TOOLS + RETRIEVED, OUTPUT)
assert 0 < cached < uncached, "кеш має зменшувати, але не обнуляти вартість"
print(f"✓ кеш: ${uncached:.6f} -> ${cached:.6f} (економія {1-cached/uncached:.1%})")

# ── 7. Тариф довгого контексту відрізняється від короткого ──────────────
short_c = request_cost_usd("gpt-5.6-terra", LONG_TOK, OUT_TOK, long_context=False)
long_c = request_cost_usd("gpt-5.6-terra", LONG_TOK, OUT_TOK, long_context=True)
assert long_c > short_c
print(f"✓ довгий контекст OpenAI дорожчий: ${short_c:.4f} -> ${long_c:.4f}")

# ── 8. ТИХА ПОЛОМКА: позиційне читання повертає порожньо, а не падає ────
assert read_text_positional(new_response) == "", "позиційне читання мало б дати порожньо"
assert read_text_by_type(new_response) == "Відповідь моделі."
assert read_text_by_type(old_response) == read_text_by_type(new_response), \\
    "стійкий спосіб має давати однаковий результат до і після міграції"
print("✓ типова поломка відтворена: позиційне читання тихо дає порожньо,")
print("  читання за типом блоку працює в обох випадках")

print()
print("Усі перевірки пройдено.")
'''
    ),

    # ── підсумок ─────────────────────────────────────────────────────────
    md(
        """
## Підсумок

**Головне з цього ноутбука:**

1. **`effort` — важіль, а не модель.** Документація Anthropic називає налаштування зусилля часто
   кращим важелем, ніж зміна моделі. Почніть із `high`, і на Opus 4.8/4.7 — із `xhigh`.
2. **Дві стратегії старту.** Efficiency-first (з дешевої моделі, апгрейд лише за потреби) або
   capability-first (з сильної, потім зниження витрат). Вибір залежить від того, чи знаєте ви межі.
3. **Model ID — це зобов'язання.** Гарантія незмінності поширюється на ID, а не на псевдоніми.
   Закріплюйте ID у продакшні й тримайте їх у конфігурації.
4. **Формат ID змінювався.** 4.6+ — без дати (`claude-opus-5`); до 4.6 — із датою снапшота
   (`claude-haiku-4-5-20251001`). Формати Bedrock і Google Cloud різняться.
5. **Рахунок визначають чотири важелі:** кеш (10% або 2.5% ціни входу), батч (50%), час доби
   (у DeepSeek позапікові ставки вдвічі нижчі) і `effort`. Лише потім — вибір моделі.
6. **Поріг довгого контексту подвоює ціну** в OpenAI, і це стається мовчки.
7. **Найнебезпечніша зміна при міграції — тиха.** Мислення увімкнене за замовчуванням на Opus 5,
   відповідь може починатися з блоку `thinking` з порожнім полем `thinking`, тож `content[0].text`
   повертає порожньо **без помилки**. Фільтруйте блоки за типом.
8. **Локальна модель не безкоштовна.** Порахуйте точку беззбитковості з амортизацією власного часу —
   вона часто виявляється вищою, ніж очікувалося.

**Куди далі:**

- Розділ 3 — чому новий токенізатор дає до 1.35× більше токенів.
- Розділ 8 — `effort` і адаптивне мислення детально.
- Розділ 9 — кешування промпту: найсильніший важіль економії.
- Розділ 10 — батч-обробка: знижка 50% ціною асинхронності.
- Розділ 20 — квантизація, якщо ви таки пішли в локальний інференс.
- Розділ 24 — евалюації, без яких вибір моделі залишається вгадуванням.

## Джерела

- [Anthropic — Choosing the right model](https://platform.claude.com/docs/en/about-claude/models/choosing-a-model)
- [Anthropic — Models overview](https://platform.claude.com/docs/en/about-claude/models/overview)
- [Anthropic — Model IDs and versioning](https://platform.claude.com/docs/en/about-claude/models/model-ids-and-versions)
- [Anthropic — Model deprecations](https://platform.claude.com/docs/en/about-claude/model-deprecations)
- [Anthropic — Migrating to Claude Opus 5](https://platform.claude.com/docs/en/models/opus-5/migration-guide)
- [OpenAI — Pricing](https://developers.openai.com/api/docs/pricing)
- [DeepSeek — Models & Pricing](https://api-docs.deepseek.com/quick_start/pricing)
- [Google — Gemini API pricing](https://ai.google.dev/gemini-api/docs/pricing)
- [Mistral — Pricing](https://docs.mistral.ai/deployment/laplateforme/pricing/)

Усі джерела збережено локально: `research/02/`, `research/econ/`.
"""
    ),
]
