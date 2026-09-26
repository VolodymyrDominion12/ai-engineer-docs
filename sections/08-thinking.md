## 8. Міркування (thinking) і керування зусиллям

Модель, яка відповідає одним проходом, мусить усе вгадати з першої спроби: без чернетки, без
перевірки, без зміни курсу на півдорозі. Для доведення теореми, підступного бага чи довгої агентної
задачі перший підхід рідко виявляється найкращим. Мислення знімає це обмеження: модель опрацьовує
задачу власними словами **перед** відповіддю — переформульовує умову, пробує підходи, перевіряє
проміжні результати й відкидає ті, що не тримаються. Це міркування приходить у блоках `thinking`
перед відповіддю, і модель спирається на нього, формуючи фінальний текст.

Ціна цього механізму конкретна: токени, які модель витратила на міркування, **тарифікуються як
вихідні** — навіть коли текст міркування вам не повертається, — і вони входять у `max_tokens` разом
із текстом відповіді. Тобто мислення — це не безкоштовний «внутрішній режим», а частина вихідного
бюджету запиту.

Покоління 5.x змінило керування: ручний бюджет `budget_tokens` замінено на **адаптивне мислення**, а
глибину міркування регулює окремий параметр `effort`. Цей розділ — про те, як працюють обидва
режими, як рахувати гроші за міркування, як зберігати блоки мислення між ходами й що робити, коли
запит падає з 400.

### 8.1 Адаптивне мислення проти legacy extended thinking

**Що це.** Історично існує два режими мислення. **Adaptive thinking** (адаптивне мислення) —
`thinking: {"type": "adaptive"}`: модель сама вирішує на кожному запиті, чи думати й наскільки
глибоко. **Extended thinking** (розширене мислення, ручний режим) —
`thinking: {"type": "enabled", "budget_tokens": N}`: ви задаєте цільовий бюджет токенів на
міркування. Adaptive — поточний режим для всіх нових моделей; extended — спадщина, яка лишилася на
моделях 4.5 і молодших.

**Навіщо це знати.** Вибір режиму визначає поведінку, а не синтаксис. У ручному режимі модель думає
на **кожному** запиті, бо бюджет заданий наперед; в адаптивному вона може взагалі пропустити
міркування на простому запиті, і код, який вважає кожен хід асистента таким, що починається з блоку
`thinking`, ламається. Другий наслідок — сумісність: ручний режим **відкидається з 400** на Claude 4.7
і новіших (на 4.6 — застарілий, але запити проходять), тому перенесений код із `budget_tokens` падає
на першому ж запиті.

**Як працює під капотом.**

Рішення «думати чи ні» ухвалюється **на кожен запит окремо**. Одна й та сама розмова може містити
ходи з блоками мислення й без них. Основний важіль цього рішення — `effort`; промптові підказки
(системний промпт або текст повідомлення користувача) працюють як додатковий, менш передбачуваний
важіль.

Форма відповіді. Блоки `thinking` приходять **перед** блоками `text`:

| Поле блоку | Що містить |
|---|---|
| `type: "thinking"` | Блок міркування |
| `thinking` | Текст міркування — **підсумок**, а не сирий ланцюжок думок; порожній рядок при `display: "omitted"` |
| `signature` | Зашифрована повна версія міркування; передається назад без змін |

Поле `signature` — не метадані для читання, а криптографічний підпис: повний вміст міркування
шифрується й повертається в ньому, а API використовує підпис, щоб перевірити, що блоки справді
згенеровані Claude. Він **непрозорий** — не інтерпретуйте й не парсіть його. Підписи сумісні між
платформами: згенерований на Claude API працює на Amazon Bedrock і Google Cloud.

**Що саме видно.** Поле `display` у конфігурації `thinking` керує тим, чи повертається текст
міркування. Воно працює в обох режимах:

| Значення `display` | Що повертається | Типове для |
|---|---|---|
| `"summarized"` | Читабельний **підсумок** міркування | Claude Opus 4.6, Claude Sonnet 4.6 і старші |
| `"omitted"` | Блок із **порожнім** полем `thinking`; підпис на місці | Claude Fable 5.1, Mythos 5.1, Fable 5, Mythos 5, Opus 5, Sonnet 5, Opus 4.8, Opus 4.7, Mythos Preview |
| `"updates"` (бета) | Порожній `thinking` для міркувань; читабельні **звіти про поступ** між викликами інструментів | Потребує заголовка `thinking-display-updates-2026-08-18` |

Жодне значення `display` не повертає сирий ланцюжок думок. Те, що ви бачите при `"summarized"`, —
підсумок, який робить **інша** модель; модель, що міркувала, цього підсумку не бачить. Білінг від
`display` не залежить: рахунок іде за повний обсяг міркування, а не за підсумок.

Сумісність режимів за моделями (це найпрактичніша таблиця розділу — тримайте її під рукою):

| Модель | Приймає `thinking.type` | Типово | Відкидає з 400 |
|---|---|---|---|
| Claude Fable 5.1, Mythos 5.1, Fable 5, Mythos 5 | Лише adaptive | Завжди увімкнено | `"enabled"`, `"disabled"` |
| Claude Mythos Preview | Adaptive, extended | Завжди увімкнено | `"disabled"` |
| Claude Opus 5 | Лише adaptive | Увімкнено | `"enabled"`; `"disabled"` — лише на effort `xhigh`/`max` |
| Claude Opus 4.8, Opus 4.7 | Лише adaptive | Вимкнено | `"enabled"` |
| Claude Sonnet 5 | Лише adaptive | Увімкнено | `"enabled"` |
| Claude Opus 4.6, Sonnet 4.6 | Adaptive, extended (застарілий) | Вимкнено | — |
| Claude Opus 4.5, Haiku 4.5, Sonnet 4.5 | Лише extended | Вимкнено | `"adaptive"` |

Перший робочий приклад — локальний валідатор конфігурації. Він відтворює правила з таблиці сумісності
й повертає **справжні** тексти помилок, щоб їх можна було порівнювати в тестах:

```python
MODES = {
    "claude-fable-5-1":      {"default": "always_on", "rejects": {"enabled", "disabled"}},
    "claude-mythos-preview": {"default": "always_on", "rejects": {"disabled"}},
    "claude-opus-5":         {"default": "on",        "rejects": {"enabled"}},
    "claude-opus-4-8":       {"default": "off",       "rejects": {"enabled"}},
    "claude-sonnet-5":       {"default": "on",        "rejects": {"enabled"}},
    "claude-opus-4-6":       {"default": "off",       "rejects": set()},
    "claude-opus-4-5":       {"default": "off",       "rejects": {"adaptive"}},
    "claude-haiku-4-5":      {"default": "off",       "rejects": {"adaptive"}},
}

ERRORS = {
    "enabled": '"thinking.type.enabled" is not supported for this model. '
               'Use "thinking.type.adaptive" and "output_config.effort" to control thinking behavior.',
    "disabled": '"thinking.type.disabled" is not supported for this model. '
                'Use "thinking.type.adaptive" and "output_config.effort" to control thinking behavior.',
    "adaptive": "adaptive thinking is not supported on this model",
}


def validate(model: str, thinking: dict | None, effort: str | None = None) -> str:
    """Відтворює правила з довідки: що модель приймає, а що відкидає з 400."""
    spec = MODES[model]
    if thinking is None:
        if spec["default"] == "off":
            return "OK (мислення вимкнено — успадкована поведінка)"
        return "OK (мислення увімкнено типово, display=omitted)"
    ttype = thinking["type"]
    if model == "claude-opus-5" and ttype == "disabled" and effort in ("xhigh", "max"):
        return '400: thinking: {type: "disabled"} заборонено на effort "xhigh"/"max"'
    if ttype in spec["rejects"]:
        return f"400: {ERRORS[ttype]}"
    return f"OK (режим {ttype})"


CASES = [
    ("claude-opus-5", {"type": "enabled", "budget_tokens": 10000}, None),
    ("claude-opus-4-8", {"type": "enabled", "budget_tokens": 10000}, None),
    ("claude-fable-5-1", {"type": "disabled"}, None),
    ("claude-opus-5", {"type": "disabled"}, "max"),
    ("claude-opus-5", {"type": "disabled"}, "medium"),
    ("claude-haiku-4-5", {"type": "adaptive"}, None),
    ("claude-opus-4-6", {"type": "enabled", "budget_tokens": 10000}, None),
    ("claude-sonnet-5", None, None),
]
for model, thinking, effort in CASES:
    label = str(thinking) if thinking else "без параметра thinking"
    print(f"{model:22} {label:40} effort={str(effort):7} -> {validate(model, thinking, effort)}")
```

**Фактичний вивід:**

```text
claude-opus-5          {'type': 'enabled', 'budget_tokens': 10000} effort=None    -> 400: "thinking.type.enabled" is not supported for this model. Use "thinking.type.adaptive" and "output_config.effort" to control thinking behavior.
claude-opus-4-8        {'type': 'enabled', 'budget_tokens': 10000} effort=None    -> 400: "thinking.type.enabled" is not supported for this model. Use "thinking.type.adaptive" and "output_config.effort" to control thinking behavior.
claude-fable-5-1       {'type': 'disabled'}                     effort=None    -> 400: "thinking.type.disabled" is not supported for this model. Use "thinking.type.adaptive" and "output_config.effort" to control thinking behavior.
claude-opus-5          {'type': 'disabled'}                     effort=max     -> 400: thinking: {type: "disabled"} заборонено на effort "xhigh"/"max"
claude-opus-5          {'type': 'disabled'}                     effort=medium  -> OK (режим disabled)
claude-haiku-4-5       {'type': 'adaptive'}                     effort=None    -> 400: adaptive thinking is not supported on this model
claude-opus-4-6        {'type': 'enabled', 'budget_tokens': 10000} effort=None    -> OK (режим enabled)
claude-sonnet-5        без параметра thinking                   effort=None    -> OK (мислення увімкнено типово, display=omitted)
```

Третій приклад — порядок подій у стрімі. Блок відкривається `content_block_start`, текст приходить
подіями `thinking_delta` всередині `content_block_delta`, завершує блок **одна** подія
`signature_delta` безпосередньо перед `content_block_stop`, і лише потім ідуть `text_delta`. При
`display: "omitted"` `thinking_delta` приходить із **порожнім** рядком, а `signature_delta` — зі
справжнім підписом, тому парсер, який ігнорує порожні дельти, втрачає підпис:

```text
content_block_start  {"type":"thinking","thinking":"","signature":""}
content_block_delta  {"type":"thinking_delta","thinking":""}          ← порожньо при "omitted"
content_block_delta  {"type":"signature_delta","signature":"EosnCkYICxIM..."}
content_block_stop
content_block_start  {"type":"text","text":""}
```

Якщо ви розбираєте потік власним кодом, збирайте блоки за `index` і не фільтруйте порожні події.
Або скористайтеся хелпером накопичення зі SDK — `stream.get_final_message()` у Python чи
`stream.finalMessage()` у TypeScript — замість склеювання дельт вручну. З `display: "omitted"` жоден
токен міркування не стрімиться, тому фінальний текст починає йти раніше.

Якщо ваш парсер ігнорує **порожні** дельти, ви втратите підпис — і наступний запит у циклі
інструментів упаде з 400.

#### Legacy extended thinking: як він влаштований

Ручний режим лишається доступним там, де він єдиний, і має власні правила бюджету з довідки:

| Правило `budget_tokens` | Значення |
|---|---|
| Мінімум | 1 024 токени — менші значення API відкидає |
| Відношення до `max_tokens` | Менше за `max_tokens`; виняток — interleaved thinking, де бюджет може перевищувати `max_tokens`, бо охоплює всі блоки міркування одного ходу |
| Попереднє прогрівання кешу | Неможливе: через попереднє правило `budget_tokens` не поєднується з `max_tokens: 0` |
| Природа обмеження | **Ціль**, а не жорстка стеля: модель може зупинитися задовго до вичерпання бюджету; жорстка стеля — `max_tokens` |
| Статус | Застарілий на Claude 4.6 (запити проходять); **400 на Claude 4.7 і новіших** |
| Разом з `effort` | Лише на Claude Opus 4.5 — єдиній моделі з extended-only, що підтримує `effort`: `effort` формує відповідь, `budget_tokens` задає глибину міркування |

Орієнтири підбору бюджету з довідки: для простих задач — близько мінімуму (1 024) з нарощуванням,
для складних — від 16 000 токенів, зважаючи на латентність. Для бюджетів **понад 32k** використовуйте
пакетну обробку: такі запити живуть досить довго, щоб упиратися в мережеві таймаути й ліміти
відкритих з'єднань.

**Перехід на адаптивне мислення.** Маппінг мінімальний: прибрати `budget_tokens`, поставити
`thinking: {"type": "adaptive"}` і керувати глибиною через `output_config.effort`. Але поведінка
змінюється: із фіксованим бюджетом модель думала **на кожному** запиті, з адаптивним — сама вирішує, і
на низьких рівнях `effort` може пропустити міркування на легких входах. Заголовок
`interleaved-thinking-2025-05-14` після міграції не потрібен (адаптивний режим перемежовує
автоматично), а типове збереження блоків змінюється (див. 8.4).

**Типові помилки**

- Передати `budget_tokens` на модель 4.7+ і отримати 400 у продакшні, бо на старшій моделі той самий
  код працював.
- Читати відповідь за індексом: `content[0].text` падає або повертає `None`, коли попереду стоїть
  блок `thinking`.
- Вважати, що кожен хід асистента містить блок мислення. В адаптивному режимі простий запит може
  дати відповідь без жодного блоку.
- Фільтрувати блоки за `block.type == "thinking"` і **втрачати** `redacted_thinking`. Це окремий тип
  блоку, і його теж треба повертати назад.
- Сподіватися побачити «справжні думки» моделі. `display` повертає або підсумок, або нічого; сирий
  ланцюжок думок не повертається за жодного значення.

**Альтернативи**

| Підхід | Коли брати | Ціна |
|---|---|---|
| Adaptive thinking | Усі моделі, які його підтримують; змішане навантаження | Гнучко; глибина через `effort` |
| Legacy extended thinking | Моделі 4.5 і молодші, де adaptive дає 400; потрібна передбачувана латентність | Фіксований бюджет; депрекація на 4.6, 400 на 4.7+ |
| `thinking: {"type": "disabled"}` | Моделі, які це приймають, і лише на effort `high` або нижче | Дешевше, але на Opus 5 з'являються витікання викликів інструментів у текст |
| Взагалі без параметра `thinking` | Нові моделі, де мислення увімкнене типово | Те саме, що adaptive з `display: "omitted"` |

---

### 8.2 Параметр `effort` і рівні

**Що це.** `effort` — параметр, який задає, **скільки роботи** модель вкладає у відповідь. Він
передається на верхньому рівні тіла запиту як `output_config.effort` і має п'ять значень: `low`,
`medium`, `high`, `xhigh`, `max`. `high` — значення за замовчуванням; явне `"high"` поводиться
**точно так само**, як відсутність параметра.

**Навіщо це знати.** Це головний (і рекомендований документацією) важіль керування мисленням в
адаптивному режимі: `thinking` вирішує, чи буде міркування взагалі, а `effort` — скільки роботи піде
на відповідь, **включно** з тим, як часто й наскільки глибоко модель думає. Тому типові дії
розкладаються однозначно: потрібно дешевше або швидше — **знижуйте `effort`**, а не вимикайте
мислення; модель думає надто рідко чи поверхово — **піднімайте `effort`**; потрібна жорстка стеля
витрат — це `max_tokens`, а не `effort` (див. 8.3).

**Як працює під капотом.**

`effort` впливає на **всі** вихідні токени відповіді, не лише на міркування: на текст і пояснення,
на виклики інструментів та їхні аргументи, і на мислення, коли воно активне. Саме тому параметр діє
і без мислення. Практичний наслідок для агентів: нижчий `effort` дає **менше й стисліші** виклики
інструментів — модель об'єднує операції, менше викликає, діє без преамбул і пише короткі
підтвердження. Вищий `effort` — більше викликів, план перед дією, докладні підсумки й розгорнуті
коментарі в коді.

`effort` — **поведінковий сигнал, а не бюджет токенів**. На нижчих рівнях модель усе одно думає над
достатньо складними задачами, просто менше, ніж думала б на вищому рівні над тією ж задачею.
Гарантованої кількості токенів параметр не дає.

Що робить кожен рівень із мисленням:

| Рівень | Поведінка мислення |
|---|---|
| `max` | Модель думає завжди, без обмежень на глибину |
| `xhigh` | Модель завжди думає глибоко, з розширеним дослідженням |
| `high` (типове) | Майже завжди думає; глибоке міркування на складних задачах |
| `medium` | Помірне мислення; може пропустити міркування на простих запитах |
| `low` | Мінімізує мислення; пропускає його там, де важлива швидкість |

Доступність рівнів за моделями (з таблиці рівнів у документації):

| Модель | `low`/`medium`/`high` | `xhigh` | `max` |
|---|---|---|---|
| Claude Fable 5.1, Mythos 5.1, Fable 5, Mythos 5 | ✓ | ✓ | ✓ |
| Claude Mythos Preview | ✓ | — | ✓ |
| Claude Opus 5, Opus 4.8, Opus 4.7 | ✓ | ✓ | ✓ |
| Claude Opus 4.6 | ✓ | — | ✓ |
| Claude Sonnet 5 | ✓ | ✓ | ✓ |
| Claude Sonnet 4.6 | ✓ | — | ✓ |
| Claude Opus 4.5 | ✓ | — | — |

Не всі моделі, що підтримують `max`, підтримують `xhigh`.

Рекомендації документації за моделями (вони перекривають загальну таблицю, де відрізняються):

| Модель | З чого починати | Примітка |
|---|---|---|
| Claude Fable 5.1, Fable 5 | `high` (типове) | Крокувати до `xhigh`/`max` для чутливої до якості роботи; знижувати до `medium`/`low` після перевірки на власних eval. Нижчі рівні на Fable 5 часто перевищують `xhigh` попередніх моделей |
| Claude Opus 5 | `high` (типове) | `low` і `medium` — основний важіль ціни й часу; якщо переносили налаштування зі старшої моделі — робіть новий прогін по `effort` |
| Claude Opus 4.8, Opus 4.7 | `xhigh` для коду й агентних задач | `high` — для решти чутливих до якості (на 4.7 це мінімум для більшості задач), `medium`/`low` — лише після вимірювання |
| Claude Sonnet 5 | `high` (типове) | `medium` порівнянний із Sonnet 4.6 на `high` |
| Claude Sonnet 4.6 | `medium` (рекомендовано) | Задавайте `effort` явно, щоб не отримати неочікуваної латентності |

Окремо документація попереджає про Opus 5: `effort` керує **обсягом міркування**, а не довжиною
видимої відповіді — зниження `effort` не скорочує відповідь надійно, для довжини треба промптові
вказівки.

Робочий приклад — матриця доступності й нормалізація значення:

```python
# Рівні effort (research/02/effort.md): порядок від найдешевшого до найдорожчого.
EFFORT_LEVELS = ["low", "medium", "high", "xhigh", "max"]

THINKING_BEHAVIOR = {
    "low":    "мінімізує мислення; на простих задачах пропускає його",
    "medium": "помірне мислення; може пропустити на простих запитах",
    "high":   "майже завжди думає; глибоке міркування (типове значення)",
    "xhigh":  "завжди думає глибоко з розширеним дослідженням",
    "max":    "завжди думає, без обмежень на глибину",
}

BASE = set(EFFORT_LEVELS[:3])                       # low, medium, high
MODEL_LEVELS = {
    "claude-fable-5-1":      BASE | {"xhigh", "max"},   # так само: Mythos 5.1, Fable 5, Mythos 5
    "claude-mythos-preview": BASE | {"max"},
    "claude-opus-5":         BASE | {"xhigh", "max"},   # так само: Opus 4.8, Opus 4.7
    "claude-opus-4-6":       BASE | {"max"},
    "claude-sonnet-5":       BASE | {"xhigh", "max"},
    "claude-sonnet-4-6":     BASE | {"max"},
    "claude-opus-4-5":       BASE,
}

header = "модель".ljust(24) + "".join(lv.center(7) for lv in EFFORT_LEVELS)
print(header)
print("-" * len(header))
for model, levels in MODEL_LEVELS.items():
    print(model.ljust(24) + "".join(("  ✓  " if lv in levels else "  ·  ").center(7)
                                     for lv in EFFORT_LEVELS))

print()
print("effort за замовчуванням: high; явний high == параметр не передано взагалі")
print("без xhigh:", ", ".join(m for m, lv in MODEL_LEVELS.items() if "xhigh" not in lv))


def effective_effort(effort: str | None, model: str) -> str:
    """Відсутнє значення = high; явний high еквівалентний відсутності параметра."""
    if effort is None:
        return "high"
    if effort not in MODEL_LEVELS[model]:
        raise ValueError(f"{model} не підтримує effort={effort!r}")
    return effort


print()
for probe in (None, "high", "medium", "max"):
    print(f"  output_config.effort={str(probe):7} -> фактичний рівень "
          f"{effective_effort(probe, 'claude-opus-5')}")
```

**Фактичний вивід:**

```text
модель                    low   medium  high  xhigh   max
-----------------------------------------------------------
claude-fable-5-1           ✓      ✓      ✓      ✓      ✓
claude-mythos-preview      ✓      ✓      ✓      ·      ✓
claude-opus-5              ✓      ✓      ✓      ✓      ✓
claude-opus-4-6            ✓      ✓      ✓      ·      ✓
claude-sonnet-5            ✓      ✓      ✓      ✓      ✓
claude-sonnet-4-6          ✓      ✓      ✓      ·      ✓
claude-opus-4-5            ✓      ✓      ✓      ·      ·

effort за замовчуванням: high; явний high == параметр не передано взагалі
без xhigh: claude-mythos-preview, claude-opus-4-6, claude-sonnet-4-6, claude-opus-4-5

  output_config.effort=None    -> фактичний рівень high
  output_config.effort=high    -> фактичний рівень high
  output_config.effort=medium  -> фактичний рівень medium
  output_config.effort=max     -> фактичний рівень max
```

#### Зміна `effort` посеред розмови (бета)

На Claude Fable 5.1, Mythos 5.1 і Opus 5 працює **per-message effort**: замість верхнього рівня ви
додаєте повідомлення з роллю `system`, **порожнім** `content` і новим рівнем у `output_config.effort`.
Новий рівень діє з наступного ходу користувача й тримається до наступної зміни; усе попереднє
лишається незмінним, тому **кешований префікс зберігається** — чого не дає зміна верхнього значення
між запитами. Порожній `content` означає, що правила розміщення system-повідомлень посеред розмови на
таке повідомлення не поширюються: воно може стояти будь-де, навіть першим. Потрібен бета-заголовок
`mid-conversation-output-config-2026-07-01`; моделі без per-message effort (зокрема Claude Fable 5)
повертають 400 з текстом `output_config.effort requires a model that supports per-turn effort; this
model does not`. Документація для Fable 5.1 радить саме цю форму: верхня зміна і перезапускає кеш, і
керує моделлю менш надійно, бо попередні відповіді написані на старому рівні.

**Типові помилки**

- Передати `"adaptive"` як значення `effort`. `adaptive` — це **режим** мислення, не рівень; у списку
  рівнів його немає.
- Змінювати верхній `output_config.effort` між запитами довгої розмови й дивуватися, чому
  `cache_read_input_tokens` упав до нуля: рівень `effort` входить у префікс кешу.
- Вимагати `xhigh` на моделі, де його немає (`claude-opus-4-6`, `claude-sonnet-4-6`,
  `claude-opus-4-5`, `claude-mythos-preview`).
- Ставити `max_tokens` за розміром відповіді, а потім піднімати `effort`: на вищих рівнях модель
  вичерпує ліміт міркуванням.
- Переносити рівень `effort` зі старшої моделі без нового прогону на власних eval — документація
  прямо радить зробити свіжий прогін по рівнях `effort`.

**Альтернативи**

| Важіль | Що робить | Коли брати |
|---|---|---|
| `effort` | Масштабує всю відповідь, включно з міркуванням | Типовий вибір: і ціна, і латентність, і глибина |
| `max_tokens` | Жорстка стеля на сумарний вихід | Коли потрібна гарантія витрат |
| `thinking: {"type": "disabled"}` | Прибирає міркування зовсім | Моделі, які це приймають, і `effort` ≤ `high` |
| Промптове керування | Зсуває поріг спрацювання мислення | Коли потрібна вибірковість у межах одного рівня; чутливе до формулювання |
| Per-message `output_config` | Зміна рівня без втрати кешу | Fable 5.1 / Mythos 5.1 / Opus 5, довгі розмови з кешем |

---

### 8.3 Ціна мислення й керування витратами

**Що це.** Мислення тарифікується за трьома статтями: токени, які модель витратила на міркування
(**як вихідні**), блоки міркування попередніх ходів, що лишилися в контексті (**як вхідні**), і
звичайний текст відповіді (вихідні). Бюджету токенів на міркування більше немає: витратами керують
два різні інструменти — жорсткий `max_tokens` і м'який `effort`.

**Навіщо це знати.** Найпоширеніша оманлива інтуїція — «ми не показуємо міркування користувачеві,
отже, за нього не платимо». Рахунок формує `output_tokens`, а не те, що видно в тілі відповіді.
Вимкнене мислення справді заощаджує, але разом із якістю, і на Opus 5 додає дефекти виводу (див.
8.5). Увімкнене мислення на новій моделі, де воно типове, дає більше вихідних токенів **на запит**
при тій самій ціні за токен — саме це найчастіше «ламає» бюджет після оновлення моделі.

**Як працює під капотом.**

Правила білінгу з довідки:

| Що тарифікується | Як |
|---|---|
| Токени міркування поточного ходу | Як **вихідні**; входять у `max_tokens` |
| Блоки міркування попередніх ходів у контексті | Як **вхідні** — на моделях, що зберігають усі ходи (див. 8.4) |
| Текст відповіді | Як вихідні |
| Підсумок міркування (генерація) | Окремо **не** тарифікується |

Білінг не залежить від `display`:

| | `display: "summarized"` | `display: "omitted"` |
|---|---|---|
| Вхідні токени | Токени вашого запиту | Те саме |
| Вихідні токени (тарифікуються) | Повний обсяг міркування, згенерований усередині | Те саме |
| Вихідні токени (видимі) | Підсумок міркування | Нуль токенів міркування — `thinking` порожній |
| Генерація підсумку | Без доплати | Не застосовується |

Документація попереджає прямо: **тарифікована кількість вихідних токенів не збігається з видимою**.
Щоб дізнатися, скільки вихідних токенів пішло на внутрішнє міркування, читайте
`usage.output_tokens_details.thinking_tokens`. Це значення відображає **сирий** обсяг міркування (не
підсумок із тіла відповіді) і завжди менше або дорівнює `output_tokens`. При стрімінгу розбивка
з'являється лише у фінальній події `message_delta`. `output_tokens` лишається авторитетним для
білінгу, а `output_tokens_details` — лише для спостережуваності.

Ціни за мільйон токенів (з довідки про ціни, станом на 09.2026), для розрахунку мислення важлива
остання колонка:

| Модель | Базовий вхід | Вихід |
|---|---|---|
| Claude Fable 5.1, Mythos 5.1, Fable 5, Mythos 5 | $10 | **$50** |
| Claude Opus 5, Opus 4.8, Opus 4.7, Opus 4.6, Opus 4.5 | $5 | **$25** |
| Claude Sonnet 5 | $2 | **$10** |
| Claude Sonnet 4.6, Sonnet 4.5 | $3 | **$15** |
| Claude Haiku 4.5 | $1 | **$5** |

Два механізми обмеження витрат:

- `max_tokens` — **жорстка стеля** на сумарний вихід запиту, міркування плюс текст. Модель ніколи
  не генерує далі неї. У циклі інструментів **кожен запит** ходу має власний `max_tokens`, тому він
  не обмежує витрати всього ходу.
- `effort` — **м'яка** підказка про те, яку частину цього виходу віддати міркуванню.

Робочий приклад — калькулятор вартості ходу:

```python
# Ціни в USD за 1M токенів (research/02/pricing.md, станом на 09.2026).
PRICE = {
    # модель: (вхід, вихід)
    "claude-fable-5-1":  (10.0, 50.0),
    "claude-opus-5":     (5.0, 25.0),
    "claude-opus-4-8":   (5.0, 25.0),
    "claude-sonnet-5":   (2.0, 10.0),
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-haiku-4-5":  (1.0, 5.0),
}
CACHE_WRITE_MULT = 1.25     # 5-хвилинний запис у кеш
CACHE_READ_MULT = 0.10      # влучання в кеш (на Fable 5.1 / Mythos 5.1 — 0.025)


def turn_cost(model: str, usage: dict) -> dict:
    """Вартість одного ходу. Мислення тарифікується як вихід — воно в output_tokens."""
    in_price, out_price = PRICE[model]
    fresh = usage.get("input_tokens", 0)
    written = usage.get("cache_creation_input_tokens", 0)
    read = usage.get("cache_read_input_tokens", 0)
    output = usage.get("output_tokens", 0)
    thinking = usage.get("output_tokens_details", {}).get("thinking_tokens", 0)
    in_cost = (fresh + written * CACHE_WRITE_MULT + read * CACHE_READ_MULT) / 1e6 * in_price
    out_cost = output / 1e6 * out_price
    return {
        "усього_usd": round(in_cost + out_cost, 6),
        "вихід_usd": round(out_cost, 6),
        "частка_мислення_у_виході": round(thinking / output, 4) if output else 0.0,
        "мислення_usd": round(thinking / 1e6 * out_price, 6),
    }


# Приклад із довідки: output_tokens=348, thinking_tokens=312
usage_doc = {"input_tokens": 25, "output_tokens": 348,
             "output_tokens_details": {"thinking_tokens": 312}}
for model in ("claude-opus-5", "claude-sonnet-5"):
    print(f"{model:18} {turn_cost(model, usage_doc)}")

print()
print("Ті самі 348 вихідних токенів, але thinking_tokens=0:")
print("  ", turn_cost("claude-opus-5", {"input_tokens": 25, "output_tokens": 348}))
print("  висновок: рахунок визначає output_tokens, а не видимість тексту міркування")
```

**Фактичний вивід:**

```text
claude-opus-5      {'усього_usd': 0.008825, 'вихід_usd': 0.0087, 'частка_мислення_у_виході': 0.8966, 'мислення_usd': 0.0078}
claude-sonnet-5    {'усього_usd': 0.00353, 'вихід_usd': 0.00348, 'частка_мислення_у_виході': 0.8966, 'мислення_usd': 0.00312}

Ті самі 348 вихідних токенів, але thinking_tokens=0:
   {'усього_usd': 0.008825, 'вихід_usd': 0.0087, 'частка_мислення_у_виході': 0.0, 'мислення_usd': 0.0}
  висновок: рахунок визначає output_tokens, а не видимість тексту міркування
```

Другий приклад — симуляція розподілу `max_tokens` між міркуванням і текстом. Вона відповідає на
практичне питання: що станеться з відповіддю, якщо мислення візьме більшу частину ліміту. Надлишок
міркування не додається зверху — він **віднімається від тексту**, бо `max_tokens` є жорсткою межею на
сумарний вихід.

```python
def plan_budget(max_tokens: int, thinking_tokens: int, text_tokens: int) -> dict:
    """max_tokens — жорстка межа на СУМАРНИЙ вихід (мислення + текст)."""
    used = thinking_tokens + text_tokens
    return {
        "max_tokens": max_tokens,
        "мислення": thinking_tokens,
        "текст_отримав": max(0, min(text_tokens, max_tokens - thinking_tokens)),
        "stop_reason": "max_tokens" if used > max_tokens else "end_turn",
        "запас_токенів": max_tokens - used,
    }


def remedy(stop_reason: str, has_thinking: bool) -> str:
    """Дві дії з довідки для stop_reason=max_tokens."""
    if stop_reason != "max_tokens":
        return "дій не потрібно"
    if not has_thinking:
        return "підняти max_tokens"
    return "підняти max_tokens (якщо міркування були потрібні) або знизити effort"


print("Сценарій: відповідь на 800 токенів, але Opus 5 увімкнув мислення.")
for budget in (4_096, 64_000):
    for thinking in (300, 3_500):
        p = plan_budget(budget, thinking, 800)
        print(f"max_tokens={p['max_tokens']:>6} мислення={p['мислення']:>5} "
              f"текст={p['текст_отримав']:>4} {p['stop_reason']:>11} запас={p['запас_токенів']:>6}")
print()
for sr, th in (("end_turn", True), ("max_tokens", True), ("max_tokens", False)):
    print(f"  stop_reason={sr:11} мислення={str(th):5} -> {remedy(sr, th)}")
```

**Фактичний вивід:**

```text
Сценарій: відповідь на 800 токенів, але Opus 5 увімкнув мислення.
max_tokens=  4096 мислення=  300 текст= 800    end_turn запас=  2996
max_tokens=  4096 мислення= 3500 текст= 596  max_tokens запас=  -204
max_tokens= 64000 мислення=  300 текст= 800    end_turn запас= 62900
max_tokens= 64000 мислення= 3500 текст= 800    end_turn запас= 59700

  stop_reason=end_turn    мислення=True  -> дій не потрібно
  stop_reason=max_tokens  мислення=True  -> підняти max_tokens (якщо міркування були потрібні) або знизити effort
  stop_reason=max_tokens  мислення=False -> підняти max_tokens
```

Практичні орієнтири з довідки: на `xhigh` і `max` для Opus 5 / Opus 4.8 / Opus 4.7 ставте великий
`max_tokens` — розумний старт **64 000 токенів** з подальшим підбором. Верхні межі `max_tokens`:
128K для Fable 5.1 / Mythos 5.1 / Fable 5 / Mythos 5 / Mythos Preview / Opus 5 / Opus 4.8 / Opus 4.7 /
Opus 4.6 / Sonnet 5 / Sonnet 4.6 і 64K для Opus 4.5 / Sonnet 4.5 / Haiku 4.5. SDK вимагають стрімінгу,
коли `max_tokens` більший за 21 333 — це клієнтська перевірка проти HTTP-таймаутів.

#### Мислення й кеш промпту: прихований множник витрат

Конфігурація `thinking` і **фактичний рівень `effort`** відрендерюються в сам промпт, тому зміна
будь-чого з цього перезапускає префікс кешу (деталі механіки — розділ 9). Явне значення, що дорівнює
типовому, кеш **не** ламає. Блоки мислення кешуються **разом із результатами інструментів**: у
наступному запиті з `tool_result` попередня історія разом із ними потрапляє в кеш і при читанні
рахується як вхідні токени.

Документація наводить вимірювання, яке варто відтворити на своєму навантаженні (вивід із довідки):

```text
First request - establishing cache
First response usage: { cache_creation_input_tokens: 3546, cache_read_input_tokens: 0, input_tokens: 15, output_tokens: 1033 }

Second request - same configuration (cache hit expected)
Second response usage: { cache_creation_input_tokens: 0, cache_read_input_tokens: 3546, input_tokens: 1062, output_tokens: 1630 }


Third request - different effort level (cache miss expected)
Third response usage: { cache_creation_input_tokens: 3546, cache_read_input_tokens: 0, input_tokens: 2706, output_tokens: 1468 }
```

Третій запит відрізняється лише рівнем `effort` — і `cache_read_input_tokens` падає до нуля, а
`cache_creation_input_tokens` знову дорівнює 3546: зміна рівня посеред кешованої розмови коштує
повного перезапису префікса. Порада з довідки окремо для мислення: такі задачі часто живуть довше за
типові 5 хвилин життя кешу — розгляньте **годинний** кеш.

**Типові помилки**

- Чекати, що `display: "omitted"` здешевить запит. Він зменшує **латентність** до першого текстового
  токена, не рахунок.
- Ставити `max_tokens` за розміром відповіді й отримувати `stop_reason: "max_tokens"` зі
  скороченим текстом, бо міркування з'їло бюджет.
- Рахувати ціну за видимим підсумком міркування. Тарифікується повний обсяг — читайте
  `usage.output_tokens_details.thinking_tokens`.
- Змінювати `effort` «на льоту» в розмові з кешем і втрачати економію кешу.
- Забувати, що на моделях, які зберігають усі ходи, блоки мислення попередніх ходів тарифікуються
  як **вхідні** на кожному наступному запиті.

**Альтернативи**

| Підхід | Що дає | Ціна |
|---|---|---|
| Зниження `effort` | Менший обсяг мислення й стисліші відповіді | Може впасти якість на складних задачах |
| Підняття `max_tokens` | Прибирає обрив відповіді | Не зменшує витрати, а фіксує стелю |
| Пакетна обробка | Для бюджетів міркування понад 32k і знижка за асинхронність | Затримка до години |
| Кеш на 1 годину | Утримує влучання в довгих сесіях міркування | Дорожчий запис префікса |
| Дешевша модель | Пряме зменшення ціни за токен | Інший профіль якості; кеш не переноситься між моделями |

---

### 8.4 Збереження блоків мислення між ходами

**Що це.** Блок мислення, який ви повернули в наступному запиті, або **стає** частиною контексту й
впливає на міркування моделі, або **відкидається**. Правила такі: усередині ходу з інструментами
блоки повертати **обов'язково**; між ходами — **рекомендовано**; поза використанням інструментів
блоки попередніх ходів можна не передавати. Із моделями від Claude Fable 5.1 додається перевірка
**префікса**: блок лишається чинним, лише доки все, що ви надіслали перед ним, незмінне.

**Навіщо це знати.** Це місце, де найлегше отримати 400 у продакшні, і де помилка не завжди видима:
на старому акаунті розбіжність префікса **не** дає помилки, тому успішний прогін на власному ключі
нічого не доводить — користувачі з новими акаунтами побачать 400 раніше за вас. Друга причина —
економіка: на моделях, які зберігають усі ходи, мислення стає звичайною історією діалогу, яка
накопичується в контексті й тарифікується як вхід.

**Як працює під капотом.**

Що робить API з блоком, залежить від моделі:

| Політика | Моделі | Наслідок |
|---|---|---|
| **Зберігати всі попередні ходи** | Claude Opus 4.5 і новіші Opus, Claude Sonnet 4.6 і новіші Sonnet, Fable 5.1, Mythos 5.1, Fable 5, Mythos 5, Mythos Preview | Блоки лишаються в контексті й кеші, тарифікуються як вхідні |
| **Лише останній хід** | Раніші Opus і Sonnet, усі Haiku до Claude Haiku 4.5 включно | API сам скидає старі блоки, коли ви їх повертаєте; прибирати їх вручну не треба |

Робочий приклад — модель політики для довільної розмови:

```python
KEEP_ALL = {"claude-opus-5", "claude-opus-4-8", "claude-opus-4-7", "claude-opus-4-6",
            "claude-opus-4-5", "claude-sonnet-5", "claude-sonnet-4-6",
            "claude-fable-5-1", "claude-mythos-5-1", "claude-fable-5", "claude-mythos-5",
            "claude-mythos-preview"}
LAST_TURN_ONLY = {"claude-sonnet-4-5", "claude-haiku-4-5"}
BILLING = {
    "усі попередні ходи": "вхідні токени на кожному наступному запиті",
    "лише останній хід": "лише власний вихід ходу; далі скидаються",
}


def retention(model: str) -> str:
    if model in KEEP_ALL:
        return "усі попередні ходи"
    if model in LAST_TURN_ONLY:
        return "лише останній хід"
    return "невідомо — не вдалося підтвердити станом на 09.2026"


for model in ("claude-opus-5", "claude-sonnet-5", "claude-sonnet-4-6",
              "claude-opus-4-8", "claude-sonnet-4-5", "claude-haiku-4-5"):
    print(f"{model:20} {retention(model):20} {BILLING[retention(model)]}")
```

**Фактичний вивід:**

```text
claude-opus-5        усі попередні ходи   вхідні токени на кожному наступному запиті
claude-sonnet-5      усі попередні ходи   вхідні токени на кожному наступному запиті
claude-sonnet-4-6    усі попередні ходи   вхідні токени на кожному наступному запиті
claude-opus-4-8      усі попередні ходи   вхідні токени на кожному наступному запиті
claude-sonnet-4-5    лише останній хід    лише власний вихід ходу; далі скидаються
claude-haiku-4-5     лише останній хід    лише власний вихід ходу; далі скидаються
```

#### Перевірка префікса (preserved thinking)

На Claude Fable 5.1 блок мислення лишається чинним, доки все надіслане **перед** ним незмінне.
Перевіряються рівно три частини:

1. верхній `system` промпт;
2. набір `tools`;
3. кожне повідомлення перед блоком.

Параметри поза цими трьома полями — `effort`, `max_tokens`, `output_config`, `tool_choice`,
`metadata`, `thinking.display` — у перевірку не входять, як і маркери `cache_control`. Ще одна
деталь: кожен блок мислення запам'ятовує, який блок був **перед** ним, тому прибирати блоки можна
лише з початку або з кінця історії — «дірка» посередині інвалідує всі наступні блоки.

Робочий приклад — класифікатор змін:

```python
def classify_change(prev: dict, new: dict) -> dict:
    """Відтворює таблицю «Що вважається редагуванням» (preserved thinking)."""
    if prev["system"] != new["system"]:
        return {"thinking": "invalid", "причина": "змінено top-level system"}
    if prev["tools"] != new["tools"]:
        return {"thinking": "invalid", "причина": "tools додано/видалено/змінено"}
    p, n = prev["messages"], new["messages"]
    if len(n) < len(p):
        return {"thinking": "invalid", "причина": "історію обрізали"}
    for i, old in enumerate(p):
        if n[i] != old:
            return {"thinking": "invalid",
                    "причина": f"messages[{i}] змінено або перевпорядковано"}
    return {"thinking": "valid", "причина": "лише дописування в кінець"}


BASE = {
    "system": "Ти — асистент.",
    "tools": [{"name": "read_file"}],
    "messages": [{"role": "user", "content": "Прочитай tests/test_auth.py"}],
}

CASES = {
    "додали новий хід у кінець":
        {**BASE, "messages": BASE["messages"] + [{"role": "assistant", "content": "ок"}]},
    "переписали system (додали дату)":
        {**BASE, "system": "Ти — асистент. Сьогодні 26.09.2026."},
    "додали інструмент у tools":
        {**BASE, "tools": [{"name": "read_file"}, {"name": "deploy"}]},
    "обрізали перший хід":
        {**BASE, "messages": []},
    "переписали контекст у першому ході":
        {**BASE, "messages": [{"role": "user", "content": "Прочитай src/auth.py"}]},
}

for name, new in CASES.items():
    v = classify_change(BASE, new)
    mark = "OK " if v["thinking"] == "valid" else "400"
    print(f"{mark} {name:38} thinking={v['thinking']:7} {v['причина']}")

print()
print("Поза префіксом — перевірка thinking НЕ реагує на ці параметри:")
for param in ("effort", "max_tokens", "output_config", "tool_choice", "metadata", "display"):
    print(f"  зміна {param:15} -> thinking лишається valid")
```

**Фактичний вивід:**

```text
OK  додали новий хід у кінець              thinking=valid   лише дописування в кінець
400 переписали system (додали дату)        thinking=invalid змінено top-level system
400 додали інструмент у tools              thinking=invalid tools додано/видалено/змінено
400 обрізали перший хід                    thinking=invalid історію обрізали
400 переписали контекст у першому ході     thinking=invalid messages[0] змінено або перевпорядковано

Поза префіксом — перевірка thinking НЕ реагує на ці параметри:
  зміна effort          -> thinking лишається valid
  зміна max_tokens      -> thinking лишається valid
  зміна output_config   -> thinking лишається valid
  зміна tool_choice     -> thinking лишається valid
  зміна metadata        -> thinking лишається valid
  зміна display         -> thinking лишається valid
```

Поведінка при розбіжності задається полем `thinking.block_binding.prefix_mismatch_behavior`:

| Значення | Що станеться |
|---|---|
| `"error"` (типово) | 400 `invalid_request_error`, у повідомленні — **перший** невалідний блок |
| `"drop_block"` | API скидає кожен невалідний блок і всі блоки мислення після нього, запит проходить; скинуті блоки не тарифікуються; кеш перезапускається на місці правки; скинуті блоки перелічуються в `input_transformations` з причиною `prefix_binding_mismatch` |

І поле, і масив `input_transformations` вимагають бета-заголовка `thinking-binding-controls-2026-08-01`.
Для Batches API є окрема пастка: елемент, який не задає поле, **скидає** блоки замість помилки —
якщо потрібна відмова, задайте `"error"` явно.

Коли перевірка вмикається:

| Група акаунтів | Поведінка |
|---|---|
| Створені 31.08.2026 00:00 UTC або пізніше | API перевіряє запити до Fable 5.1 і застосовує `"error"`, доки ви не поставите `"drop_block"` |
| Старші акаунти | Перевірка лише для запитів, що самі задають `prefix_mismatch_behavior` |
| Наступні моделі | Усі акаунти, кожен запит |

Текст помилки починається з `messages.<i>.content.<j>: Invalid `signature` in `thinking` block.
The block is bound to a different conversation.` Якщо бета-заголовка не було, повідомлення доповнюється рядком про потребу значення
`thinking-binding-controls-2026-08-01` у заголовку `anthropic-beta`. Далі зазвичай іде речення, яке
називає, **що саме** змінилося — системний промпт, список `tools`, перше
повідомлення тощо. Документація застерігає: це речення для людей і логів, його формулювання може
змінюватися, тому не прив'язуйте до нього код.

Окремий випадок — **перемикання моделей**. Блок читає лише та модель, що його створила, або новіша:
Fable 5.1 і Mythos 5.1 читають блоки всіх попередніх моделей, і жодна старша модель не читає їхні
блоки. Рух **угору** зберігає міркування, рух **униз** (роутер на дешевшу модель, відкат після
відмови класифікатора) втрачає його для цього запиту. Скинуті через невідповідність моделі блоки не
тарифікуються й не рахуються у `input_tokens`, а з бета-заголовком з'являються в
`input_transformations` з причиною `model_binding_mismatch`. Історію надсилайте повністю: API не
редагує ваш масив `messages`, тому скинуті блоки лишаються в історії й знову стають читабельними,
коли та ж історія повертається до Fable 5.1.

**Типові помилки**

- Відкидати блоки з **порожнім** `thinking`. На Fable 5.1 порожнє поле типове, а міркування несе
  `signature`; серіалізатор, що пропускає порожні блоки, стирає мислення з історії.
- Перерендерювати контекст у першому повідомленні користувача (робоча тека, гілка, дата, пам'ять).
  Зміна `messages[0]` інвалідує **кожен** блок мислення розмови.
- Інжектувати нагадування в хід користувача, а на наступному запиті його прибирати.
- Обрізати або підсумовувати старі ходи на клієнті, зберігаючи останні ходи разом із їхнім
  мисленням: збережені блоки створені, коли видалена історія ще була на місці.
- Повторювати той самий запит після 400. Тіло не змінилося — результат буде той самий.
- Забути, що діагностика в Batches поводиться інакше: без явного `"error"` елементи не падають.

**Альтернативи**

| Замість правки префікса | Використайте | Бета-заголовок |
|---|---|---|
| Перебудова верхнього `system` | System-повідомлення посеред розмови | — |
| Перерендер контексту в першому ході | Відрендерити один раз; зміну дописати в найновіший хід | — |
| Обрізання старих `tool_result` чи перекодування зображень | Скоротити **до** першого надсилання; далі — `clear_tool_uses_20250919` на сервері | `context-management-2025-06-27` |
| Додавання/видалення елементів `tools` | Блоки `tool_addition` і `tool_removal` | `mid-conversation-tool-changes-2026-07-01` |
| Нагадування на кожен хід з подальшим видаленням | Turn-scoped system-повідомлення з `clear_at: "next_user_message"` | `mid-conversation-system-clear-at-2026-08-21` |
| Зміна верхнього `output_config.effort` | Per-message `output_config` | `mid-conversation-output-config-2026-07-01` |
| Клієнтське підсумовування історії | Серверна компакція або context editing | `compact-2026-09-04` (не на Bedrock і Google Cloud) |

Просте правило, яке покриває більшість випадків: тримайте `system` і `tools` незмінними на всю
сесію, а `messages` вважайте **append-only** (тільки дописування в кінець). Ті самі правки, які
руйнують мислення, перезапускають і кеш промпту.

---

### 8.5 Типові збої й діагностика

**Що це.** Збої мислення згруповані у два класи: помилки конфігурації (400 на старті запиту) і
несподівана форма відповіді без помилки (порожній `thinking`, відсутній блок, обрив на `max_tokens`,
витікання тегів у текст, зниклі влучання кешу).

**Навіщо це знати.** Другий клас небезпечніший: помилки немає, а поведінка вже зламана. Найяскравіший
приклад — Claude Opus 5 із вимкненим мисленням: модель пише виклик інструмента **звичайним текстом**
замість блоку `tool_use` або вставляє внутрішні XML-теги у видимий вивід. Такий виклик ніколи не
виконається, а в агентному циклі текст лишається в історії й псує наступні ходи; інструкції на
кшталт «не міркуй» **підсилюють** витікання тегів.

**Як працює під капотом.**

Діагностика будується від симптома. Таблиця зіставляє побачене з причиною й дією:

| Симптом | Причина | Дія |
|---|---|---|
| `"thinking.type.enabled" is not supported for this model` | Модель 4.7+ прибрала ручний режим | Перейти на `{"type": "adaptive"}` і керувати глибиною через `output_config.effort` |
| `"thinking.type.disabled" is not supported for this model` | На моделі мислення вимкнути не можна | Прибрати параметр; щоб не показувати текст — `display: "omitted"` |
| `adaptive thinking is not supported on this model` | Модель підтримує лише legacy extended (`claude-opus-4-5`, `claude-sonnet-4-5`, `claude-haiku-4-5`) | `{"type": "enabled", "budget_tokens": N}` |
| `blocks in the latest assistant message cannot be modified` | Хід асистента перезібрано або відфільтровано за типом | Повертати хід дослівно, включно з `redacted_thinking` |
| `Invalid signature in thinking block` | Блок прив'язаний до іншої розмови: змінився префікс; або підпис обрізано/змінено | Append-only історія; або `prefix_mismatch_behavior: "drop_block"` |
| Поле `thinking` порожнє | `display` типово `"omitted"` | `display: "summarized"` (або `"updates"` для звітів про поступ) |
| Блоку мислення немає взагалі | Адаптивний режим пропустив міркування на простому запиті | Підняти `effort` або підштовхнути промптом; не покладатися на наявність блоку |
| Виклики інструментів або XML-теги в тексті | Opus 5 із вимкненим мисленням | Повернути мислення, знижувати `effort` замість вимкнення |
| `stop_reason: "max_tokens"` | Міркування вичерпало жорсткий ліміт сумарного виходу | Підняти `max_tokens` або знизити `effort` |
| `cache_read_input_tokens` упав до нуля | Зміна конфігурації `thinking` або рівня `effort` перезапускає префікс | Тримати конфігурацію й `effort` сталими; явне типове значення кеш не ламає |
| Зміна `effort` не змінює мислення | Модель працює в extended-only режимі: глибину задає `budget_tokens` | Налаштовувати бюджет; на Opus 4.5 `effort` і бюджет працюють разом |

Робочий приклад — локальний діагноста за симптомом:

```python
# Симптом -> причина -> дія (research/02/thinking-troubleshooting.md)
RULES = [
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


def diagnose(symptom: str) -> dict:
    """Знаходить перше правило, чий зразок трапляється в симптомі."""
    low = symptom.lower()
    for pattern, cause, fix in RULES:
        if pattern.lower() in low:
            return {"причина": cause, "дія": fix}
    return {"причина": "не вдалося підтвердити станом на 09.2026",
            "дія": "зберіть request_id і тіло запиту, перевірте таблицю сумісності моделей"}


OBSERVED = [
    '400: "thinking.type.enabled" is not supported for this model. Use "thinking.type.adaptive" ...',
    "400: adaptive thinking is not supported on this model",
    "response has stop_reason: max_tokens and no text block",
    "the thinking field is empty, signature present",
    "cache_read_input_tokens fell to zero after we changed output_config.effort",
    "tool calls or XML tags appear in the text output on opus-5",
]
for symptom in OBSERVED:
    d = diagnose(symptom)
    print(f"• {symptom[:60]}")
    print(f"    причина: {d['причина']}")
    print(f"    дія    : {d['дія']}")
```

**Фактичний вивід:**

```text
• 400: "thinking.type.enabled" is not supported for this model. U
    причина: модель 4.7+ прибрала ручний режим extended thinking
    дія    : замініть на thinking={"type":"adaptive"} і керуйте глибиною через output_config.effort
• 400: adaptive thinking is not supported on this model
    причина: модель підтримує лише legacy extended thinking (Opus 4.5, Haiku 4.5, Sonnet 4.5)
    дія    : використайте thinking={'type':'enabled','budget_tokens':N}
• response has stop_reason: max_tokens and no text block
    причина: мислення з'їло max_tokens (це жорстка межа на сумарний вихід)
    дія    : підніміть max_tokens або знизьте effort
• the thinking field is empty, signature present
    причина: display типово "omitted" на нових моделях
    дія    : додайте display="summarized", якщо текст мислення потрібен у UI
• cache_read_input_tokens fell to zero after we changed output_config.effort
    причина: зміна конфігурації thinking або рівня effort перезапускає префікс кешу
    дія    : тримайте конфігурацію й effort незмінними; явний high == відсутній параметр
• tool calls or XML tags appear in the text output on opus-5
    причина: на Opus 5 мислення вимкнено — модель витікає виклик у текст
    дія    : поверніть мислення і знижуйте effort замість вимкнення
```

Порядок діагностики для найпідступнішого випадку — 400 про підпис:

| Крок | Що перевірити |
|---|---|
| 1 | Чи код перебудовує хід асистента замість дослівного повернення |
| 2 | Чи фільтр блоків за типом не губить `redacted_thinking` |
| 3 | Чи не перерендерюється `system` або контекст у першому повідомленні між запитами |
| 4 | Чи не змінюється масив `tools` посеред сесії |
| 5 | Чи не видаляються/переписуються нагадування в ходах користувача |
| 6 | Чи не робить клієнтська компакція «дірку» в послідовності блоків мислення |
| 7 | Увімкнути `thinking-binding-controls-2026-08-01` з `prefix_mismatch_behavior: "drop_block"` і рахувати `input_transformations` — це дає точну причину замість здогадів |

**Типові помилки**

- Лікувати симптом замість причини: піднімати `max_tokens` там, де насправді треба знизити `effort`
  (відповідь була перерозумлена, а не обрізана).
- Читати помилку 400 і повторювати те саме тіло запиту. Воно падатиме так само.
- Вважати, що помилок немає — отже, все гаразд. На старших акаунтах розбіжність префікса проходить
  мовчки.
- Вимикати мислення, щоб позбутися тегів у виводі. Документація каже протилежне: саме вимкнене
  мислення на Opus 5 і спричиняє витікання; правильна дія — повернути мислення й знизити `effort`.

**Альтернативи**

| Симптом | Швидке рішення | Системне рішення |
|---|---|---|
| Порожній текст міркування | `display: "summarized"` | Не покладатися на текст міркування в логіці застосунку |
| Хід без блоку мислення | Підняти `effort` | Писати код, який не вимагає блоку |
| Обрив на `max_tokens` | Підняти ліміт | Знизити `effort` і просити коротшу відповідь |
| 400 про підпис | `drop_block` і продовжити | Перевести історію в append-only режим |
| Витікання тегів | Повернути мислення | Тримати `effort` низьким замість вимкнення мислення |

---

### 8.6 Мислення в циклі з інструментами

**Що це.** Із погляду моделі **цикл інструментів — це один хід асистента**. Хід не завершується,
доки модель не закінчить повну відповідь, яка може містити кілька викликів інструментів і
результатів. Мислення супроводжує цей хід, а з адаптивним режимом — ще й **перемежовується** між
викликами автоматично.

**Навіщо це знати.** Три практичні наслідки: режим мислення не можна перемикати всередині ходу; щоб
продовжити хід після виконання інструмента, блоки мислення треба повернути дослівно (саме тому
виникає більшість помилок 400 у агентах); на моделях, які зберігають усі ходи, мислення накопичується
в контексті агентної сесії й тарифікується як вхід.

**Як працює під капотом.**

Правила взаємодії мислення з інструментами:

| Правило | Деталі |
|---|---|
| Один режим мислення на хід | Зміна конфігурації посеред ходу неможлива; плануйте режим на початку ходу |
| Конфлікт посеред ходу деградує м'яко | API **не** повертає помилку: він мовчки вимикає мислення для цього запиту й може прибрати блоки, які створили б невалідну структуру ходу. Щоб зрозуміти, чи мислення було активним, перевіряйте наявність блоків `thinking` у відповіді |
| Обов'язкове повернення блоків | Під час повернення `tool_result` блоки мислення ходу асистента мусять іти назад повними й незмінними |
| Обмеження `tool_choice` | Ручний режим (`type: "enabled"`) підтримує лише `{"type": "auto"}` і `{"type": "none"}`; `"any"` і `"tool"` дають помилку. Адаптивний режим підтримує примусовий виклик інструментів, **крім** Fable 5.1 і Mythos 5.1 — вони відкидають його з 400 на кожному запиті |
| Prefill | Попереднє заповнення відповіді асистента з увімкненим мисленням неможливе |
| Interleaved thinking | В адаптивному режимі працює автоматично, без бета-заголовка. Claude Haiku 4.5 його не підтримує. У ручному режимі потрібен заголовок `interleaved-thinking-2025-05-14` і змінюється підрахунок бюджету |

Що саме змінює перемежоване мислення (порівняння з довідки для сценарію з двома інструментами):

```text
Без interleaved thinking:
  Response 1: [thinking] "Треба порахувати 150 × $50, потім звірити з базою..."
              [tool_use: calculator] { "expression": "150 * 50" }
  Response 2: [tool_use: database_query] { ... }        ← без блоку мислення
  Response 3: [text] "Загальний дохід $7 500..."        ← без блоку мислення

З interleaved thinking:
  Response 1: [thinking] "Спершу 150 × $50..."
              [tool_use: calculator] { "expression": "150 * 50" }
  Response 2: [thinking] "Отримав $7 500. Тепер запит до бази для порівняння..."
              [tool_use: database_query] { ... }
  Response 3: [thinking] "$7 500 проти середніх $5 200 — це зростання на 44%..."
              [text] "Загальний дохід $7 500..."
```

Робочий приклад — перевірка того, що ви робите з блоком мислення при поверненні ходу:

```python
class ThinkingBlockModified(Exception):
    """Те, що API повертає як 400 invalid_request_error."""


def echo_turn(original_content: list[dict], *, mode: str) -> list[dict]:
    """Повертає хід асистента для наступного запиту.

    mode="verbatim"    — як має бути: усі блоки, у тому ж порядку;
    mode="type_filter" — типова помилка: фільтр за типом губить redacted_thinking;
    mode="rebuild"     — типова помилка: хід перезібрано лише з тексту.
    """
    if mode == "verbatim":
        return [{"role": "assistant", "content": list(original_content)}]
    if mode == "type_filter":
        kept = [b for b in original_content if b.get("type") == "thinking"]
        return [{"role": "assistant", "content": kept}]
    return [{"role": "assistant", "content": [
        {"type": "text", "text": "готово"}
        for b in original_content if b.get("type") == "text"]}]


def check_echo(original_content: list[dict], turn: list[dict]) -> str:
    """Мінімальна перевірка того, що ми робимо з блоком мислення."""
    sent = turn[0]["content"]
    orig_thinking = [b for b in original_content
                     if b.get("type") in ("thinking", "redacted_thinking")]
    sent_thinking = [b for b in sent if b.get("type") in ("thinking", "redacted_thinking")]
    if len(sent_thinking) != len(orig_thinking):
        raise ThinkingBlockModified(
            "`thinking` or `redacted_thinking` blocks in the latest assistant message "
            "cannot be modified")
    for a, b in zip(orig_thinking, sent_thinking):
        if a != b:
            raise ThinkingBlockModified("Invalid `signature` in `thinking` block")
    return "хід прийнято"


assistant_content = [
    {"type": "thinking", "thinking": "", "signature": "EqQBCgIYAhIM..."},
    {"type": "redacted_thinking", "data": "EosnCkYICxIM..."},
    {"type": "tool_use", "id": "toolu_01", "name": "get_weather",
     "input": {"location": "Paris"}},
]

for mode in ("verbatim", "type_filter", "rebuild"):
    turn = echo_turn(assistant_content, mode=mode)
    try:
        verdict = check_echo(assistant_content, turn)
        print(f"{mode:12} блоків у ході={len(turn[0]['content'])} -> {verdict}")
    except ThinkingBlockModified as exc:
        print(f"{mode:12} блоків у ході={len(turn[0]['content'])} -> 400: {exc}")
```

**Фактичний вивід:**

```text
verbatim     блоків у ході=3 -> хід прийнято
type_filter  блоків у ході=1 -> 400: `thinking` or `redacted_thinking` blocks in the latest assistant message cannot be modified
rebuild      блоків у ході=0 -> 400: `thinking` or `redacted_thinking` blocks in the latest assistant message cannot be modified
```

Другий приклад показує, чому `max_tokens` не рятує від розростання витрат у циклі: ліміт є в
**кожного запиту** ходу: три запити з `max_tokens=16000` можуть витратити по 4 200, 1 800 і 900
вихідних токенів — жоден ліміт не обмежує сумарні витрати ходу.

Повний цикл із реальним API (потрібен ключ) — так виглядає правильне повернення ходу:

```python
# ПОТРЕБУЄ: ANTHROPIC_API_KEY у .env  +  pip install anthropic python-dotenv
WEATHER_TOOL = {
    "name": "get_weather",
    "description": "Get current weather for a location",
    "input_schema": {
        "type": "object",
        "properties": {"location": {"type": "string", "description": "City name"}},
        "required": ["location"],
    },
}


def tool_round_trip(prompt: str, location: str) -> str:
    """Один хід із викликом інструмента: мислення + tool_use -> tool_result -> текст."""
    messages = [{"role": "user", "content": prompt}]
    response = client.messages.create(
        model="claude-opus-5",
        max_tokens=16000,
        thinking={"type": "adaptive"},           # display типово "omitted"
        tools=[WEATHER_TOOL],
        messages=messages,
    )
    calls = [b for b in response.content if b.type == "tool_use"]
    if not calls:
        return "".join(b.text for b in response.content if b.type == "text")

    # Хід асистента повертається ДОСЛІВНО: response.content як є, разом із блоками
    # thinking (навіть із порожнім полем thinking) і redacted_thinking.
    messages.append({"role": "assistant", "content": response.content})
    messages.append({"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": call.id,
         "content": f"Current temperature in {location}: 20 C, sunny"}
        for call in calls
    ]})
    continuation = client.messages.create(
        model="claude-opus-5",
        max_tokens=16000,
        thinking={"type": "adaptive"},           # та сама конфігурація, той самий хід
        tools=[WEATHER_TOOL],
        messages=messages,
    )
    return "".join(b.text for b in continuation.content if b.type == "text")
```

Три деталі, які роблять цей код правильним: `response.content` додається **як об'єкт**, а не
перезібраний зі словників; конфігурація `thinking` у другому запиті **та сама**; результат
фільтрується за `type`, а не за індексом.

#### Звіти про поступ між викликами

На Claude Fable 5.1, Mythos 5.1 і Fable 5 модель може писати короткий звіт про поступ — речення про
те, що вона щойно з'ясувала й що робитиме далі, — для людини, яка спостерігає за агентом. Кожен
такий звіт приходить **окремим** блоком `thinking` зі своїм підписом і стоїть безпосередньо перед
блоком `tool_use`, який вводить. Максимум один звіт на виклик, і модель може його пропустити.

| `display` | Блоки міркування | Блоки звітів про поступ |
|---|---|---|
| `"omitted"` (типово на цих моделях) | Порожнє поле `thinking` | Порожнє поле `thinking` |
| `"updates"` (бета) | Порожнє поле `thinking` | Текст підсумку |
| `"summarized"` | Текст підсумку | Текст підсумку, нерозрізненний від блоку міркування |

Практичні деталі: під `"updates"` будь-який блок із непорожнім текстом — це звіт про поступ, і
рендерити треба лише їх. Звіт рахується в `usage.output_tokens` за **повною** довжиною, а не за
довжиною підсумку. Якщо відповідь обірвалася на `max_tokens`, `model_context_window_exceeded` або
`stop_sequence` невдовзі після виклику інструмента, останній блок може бути звітом-заглушкою з
текстом `This part of the response was interrupted before it finished.` — щоб продовжити, поверніть
хід асистента без змін і додайте новий хід користувача з `tool_result` для кожного `tool_use`. На
вищих рівнях `effort` і в довгих ланцюжках інструментів таких звітів **менше**.

**Типові помилки**

- Перемикати конфігурацію `thinking` між запитами одного ходу (наприклад, вимкнути мислення після
  першого виклику інструмента). API не впаде, але мовчки вимкне мислення й може прибрати блоки.
- Відфільтрувати `redacted_thinking`, повертаючи хід. Це найчастіша причина 400 у агентних циклах.
- Перебудувати хід із власних словників замість повернення `response.content`. Навіть логічно
  ідентичний, але пересеріалізований хід відкидається.
- Використовувати `tool_choice: {"type": "any"}` з ручним режимом мислення.
- Пробувати примусовий виклик інструментів на Fable 5.1 або Mythos 5.1 — ці моделі відкидають його з
  400; використовуйте `{"type": "auto"}` разом зі strict tool use або структурованим виводом.
- Робити prefill відповіді асистента з увімкненим мисленням.

**Альтернативи**

| Потреба | Підхід |
|---|---|
| Міркування між викликами інструментів | Adaptive thinking — перемежовування автоматичне, заголовок не потрібен |
| Керована кількість викликів | Зниження `effort`: менше викликів, коротші підтвердження |
| Стабільний кеш у циклі | Тримати конфігурацію `thinking` і `effort` сталими; блоки кешуються разом із `tool_result` |
| Гарантований виклик інструмента | `tool_choice: {"type": "auto"}` + strict tool use або структурований вивід (примусовий виклик недоступний на Fable 5.1 / Mythos 5.1) |
| Статус для користувача | `display: "updates"` (бета, заголовок `thinking-display-updates-2026-08-18`) |
| Довгі агентні сесії | Вищі рівні `effort` з великим `max_tokens`; серверна компакція для обсягу контексту |

**Джерела**

- [Anthropic — Thinking](https://platform.claude.com/docs/en/build-with-claude/thinking) — режими, форма відповіді, підпис, `display`, стрімінг, мислення з інструментами, пропуск міркування, зашифровані блоки, сумісність функцій, межі виходу
- [Anthropic — Effort](https://platform.claude.com/docs/en/build-with-claude/effort) — параметр `output_config.effort`, п'ять рівнів, типове значення `high`, рекомендації за моделями, per-message effort (бета), взаємодія з інструментами
- [Anthropic — Steering thinking](https://platform.claude.com/docs/en/build-with-claude/thinking-steering-and-cost) — як модель вирішує думати, керування через `effort` і промпти, кеш, керування витратами, тарифікація та `output_tokens_details.thinking_tokens`
- [Anthropic — Preserved thinking](https://platform.claude.com/docs/en/build-with-claude/preserved-thinking) — перевірка префікса, `block_binding.prefix_mismatch_behavior`, `input_transformations`, перемикання моделей, заміни для правок префікса
- [Anthropic — Thinking in tool and multi-turn workflows](https://platform.claude.com/docs/en/build-with-claude/thinking-tool-workflows) — повний двоходовий прохід із викликом інструмента й порівняння з перемежованим мисленням
- [Anthropic — Troubleshooting thinking](https://platform.claude.com/docs/en/build-with-claude/thinking-troubleshooting) — таблиця сумісності за моделями, тексти помилок 400 і діагностика симптомів
- [Anthropic — Extended thinking](https://platform.claude.com/docs/en/build-with-claude/extended-thinking) — ручний режим `budget_tokens`, правила бюджету, перемежовування в ручному режимі, міграція на адаптивне мислення
- [Anthropic — Context windows](https://platform.claude.com/docs/en/build-with-claude/context-windows) — мислення й контекстне вікно, збереження блоків за моделями, компакція
- [Anthropic — Pricing](https://platform.claude.com/docs/en/about-claude/pricing) — ціни за моделями, ціни кешу, тарифікований вихід
- [Anthropic — Migrating to Claude Opus 5](https://platform.claude.com/docs/en/models/opus-5/migration-guide) — ламальні зміни: мислення увімкнене типово, `thinking.display` = `"omitted"`, прибрані параметри семплювання, новий токенізатор (приблизно на 30% більше токенів на той самий текст)

Локальні копії джерел: `research/02/thinking.md`, `effort.md`, `preserved-thinking.md`,
`thinking-steering-and-cost.md`, `thinking-troubleshooting.md`, `thinking-tool-workflows.md`,
`extended-thinking-legacy.md`, `context-windows.md`, `pricing.md`, `migrating-opus-5.md`.
