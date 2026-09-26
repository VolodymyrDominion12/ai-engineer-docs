## 23. Observability LLM: Langfuse і OpenTelemetry GenAI

LLM-застосунок відповідає користувачеві не одним викликом моделі, а деревом: пошук у векторній базі,
виклик моделі, виклик інструмента, ще один виклик моделі. Гроші й затримки розподілені по цьому
дереву, а не по рядку логу, тому без структурованих трейсів питання «чому ця відповідь повільна й
дорога» не має відповіді. Розділ — про механіку такого дерева: спани й семантичні конвенції
OpenTelemetry GenAI, далі практика Langfuse — SDK v4, керовані промпти, датасети, оцінки,
self-hosting і ціна.

Ключова теза, навколо якої все побудовано: **Langfuse v4 усередині є OpenTelemetry**. Документація
описує SDK як «тонкий шар понад офіційний клієнт OpenTelemetry, який автоматично перетворює
випущені спани в спостереження Langfuse». Тому стандарт семантичних конвенцій — не альтернатива
Langfuse, а його фундамент, і знати його треба незалежно від обраного бекенду.

### 23.1 Навіщо трейсити LLM-застосунок

**Що це.** Трейсинг (tracing) — запис дерева операцій із тривалістю, батьківством і атрибутами
кожної з них. Одиниця запису — **спан** (span): іменований відрізок роботи з ідентифікаторами,
часом початку й завершення. Langfuse називає спани **спостереженнями** (observations), лишаючи
`span` як один із типів спостереження.

**Навіщо це знати.** Плаский лог дає суму витрат, але не дає структури. Порахуємо різницю на
реалістичних даних: шість записів про витрати токенів, кожен самотній.

```python
# Сирі записи про витрати токенів — так, як їх дає провайдер у полі usage.
# Кожен запис самотній: невідомо, до якого запиту користувача він належить.
RAW_USAGE = [
    {"call": "summarize",  "input_tokens": 1840, "output_tokens": 220, "duration_ms": 1180},
    {"call": "summarize",  "input_tokens": 1910, "output_tokens": 195, "duration_ms": 1090},
    {"call": "embed",      "input_tokens": 640,  "output_tokens": 0,   "duration_ms": 130},
    {"call": "chat",       "input_tokens": 412,  "output_tokens": 310, "duration_ms": 2450},
    {"call": "chat",       "input_tokens": 2680, "output_tokens": 155, "duration_ms": 3020},
    {"call": "tool:search", "input_tokens": 0,   "output_tokens": 0,   "duration_ms": 870},
]

print(f"Усього вхідних токенів : {sum(r['input_tokens'] for r in RAW_USAGE)}")
print(f"Усього вихідних токенів: {sum(r['output_tokens'] for r in RAW_USAGE)}")
print()
print("А тепер те, що потрібно знати в продакшні:")
for question in (
    "скільки викликів було в одному запиті користувача?",
    "на якому кроці запит гальмує?",
    "котрий виклик дав помилку після трьох ретраїв?",
    "яка версія промпту дала цю відповідь?",
):
    print(f"  {question:55} -> з плаского логу НЕ ВИДНО")
```

Фактичний вивід:

```
Усього вхідних токенів : 7482
Усього вихідних токенів: 880

  скільки викликів було в одному запиті користувача?      -> з плаского логу НЕ ВИДНО
  на якому кроці запит гальмує?                           -> з плаского логу НЕ ВИДНО
  котрий виклик дав помилку після трьох ретраїв?          -> з плаского логу НЕ ВИДНО
  яка версія промпту дала цю відповідь?                   -> з плаского логу НЕ ВИДНО
```

**Як працює під капотом.**

Спан — це структура з такими полями:

| Поле | Що це | Практичний наслідок |
|---|---|---|
| `traceId` | Ідентифікатор усього трейсу, 32 hex-символи (16 байтів) | Один запит користувача = один `traceId`, навіть якщо операцій десять |
| `spanId` | Ідентифікатор операції, 16 hex-символів (8 байтів) | Унікальний у межах трейсу; за ним прив'язуються оцінки |
| `parentSpanId` | Батько | Саме це перетворює набір спанів на дерево |
| `attributes` | Пари «ключ → значення» | Модель, параметри, токени, версія промпту |
| `events` | Іменовані записи з міткою часу | Вміст промпту й відповіді, результати оцінок |
| `status` | `OK` / `ERROR` + `error.type` | Помилку видно в дереві, а не лише в логах сервісу |

Формати ідентифікаторів стандартизовані за **W3C Trace Context**: Langfuse документує «trace IDs
are 32-character lowercase hex strings (16 bytes), observation IDs are 16-character lowercase hex
strings (8 bytes)». Той самий формат використовує OpenTelemetry, тому трейси з різних сервісів
зшиваються без перетворень.

Друга механіка — **розповсюдження контексту** (context propagation). Активний спан зберігається
в контексті виконання, і кожен новий спан стає дитиною активного. Ніхто не передає `parent` руками:
документація Langfuse каже «nesting is handled automatically by OpenTelemetry's context propagation».

Третя механіка, суто v4: **спостереження-центрична модель даних**. У v3 зв'язні атрибути (`user_id`,
`session_id`, `metadata`, `tags`) жили лише на трейсі, у v4 — на **кожному** спостереженні.
Документація пояснює навіщо: «This enables single-table queries without expensive joins,
significantly improving query performance at scale». Наслідок — фільтр «усі запити цього
користувача» працює швидко, без дорогого join.

**Типові помилки**

- Зберігати лише агрегати (сума токенів за день): не видно, який саме крок подорожчав після релізу.
- Ставити зв'язні атрибути лише на кореневий спан. У v4 фільтри й агрегації дедалі більше працюють
  на рівні окремих спостережень, і кореневий атрибут у них не бере участі.
- Писати в телеметрію те, що не можна зберігати: конвенції попереджають, що `gen_ai.input.messages`
  та `gen_ai.output.messages` «likely to contain sensitive information including user/PII data».
- Забувати `flush()`/`shutdown()` у короткоживучому процесі: SDK буферизує дані у фоні, тому «дані
  є в коді» не означає «дані є в бекенді».
- Вважати, що трейс замінює метрики. Трейс відповідає «що сталося з цим запитом», метрика —
  «що відбувається із системою» (див. 23.7).

**Альтернативи.** Інструментацію не обов'язково писати руками; шляхи такі й вони не взаємовиключні:

| Підхід | Коли брати | Що дає |
|---|---|---|
| Нативні інтеграції (OpenAI, LangChain, Vercel AI SDK) | Застосунок уже на цих бібліотеках | Спани створюються самі: промпти, відповіді, `usage`, помилки |
| Langfuse SDK (контекстний менеджер, `observe`, ручні спостереження) | Потрібен контроль над межами операцій | Точне дерево, зв'язні атрибути, оцінки |
| Проксі-логгування (через LiteLLM) | Треба побачити трафік без зміни коду | Трейси з проксі; менше контролю над структурою |
| Custom через API | Нестандартний конвеєр | Повний контроль ціною ручної роботи |
| Прямий OpenTelemetry | Застосунок уже пише OTLP-спани | Немає прив'язки до вендора (див. 23.8) |

Перші чотири рядки — рядки з таблиці можливостей Langfuse на сторінці цін; п'ятий описано в
документації OpenTelemetry-інтеграції Langfuse.

---

### 23.2 Langfuse: SDK v4, декоратори й інструментація

**Що це.** Python SDK v4 — обгортка над OpenTelemetry з трьома способами створювати спостереження:
контекстний менеджер, декоратор `observe` і ручні спостереження. Документація наголошує: «All
approaches are interoperable».

**Навіщо це знати.** Різниця між способами не косметична: вона визначає, хто керує життєвим циклом
спостереження й чи змінюється активний контекст. Помилка вибору дає або зайвий код, або загублені
спостереження — без жодної помилки в логах.

**Як працює під капотом.**

| Спосіб | Створює | Контекст | Життєвий цикл |
|---|---|---|---|
| `start_as_current_observation()` | Будь-який тип через `as_type` | Робить спостереження активним | `with`-блок: завершується сам |
| `@observe()` | Будь-який тип через `as_type` | Активне всередині функції | Автоматично: вхід, вихід, час, помилки |
| `start_observation()` | Будь-який тип через `as_type` | **Не** змінює активний контекст | **Ви** викликаєте `.end()` |

Контекстний менеджер — основний шлях; документація називає `start_as_current_observation()`
«the primary way to create observations while ensuring the active OpenTelemetry context is updated»:

```python
from langfuse import get_client, propagate_attributes, observe

langfuse = get_client()

with langfuse.start_as_current_observation(
    as_type="span", name="user-request-pipeline", input={"user_query": "Tell me a joke"},
) as root_span:
    with propagate_attributes(user_id="user_123", session_id="session_abc"):
        with langfuse.start_as_current_observation(
            as_type="generation", name="joke-generation", model="gpt-4o",
        ) as generation:
            generation.update(output="Why did the span cross the road?")
    root_span.update(output={"final_joke": "..."})

# Декоратор додає те саме до функції, не змінюючи її логіки
@observe(name="llm-call", as_type="generation")
async def my_async_llm_call(prompt_text):
    return "LLM response"
```

Ручні спостереження потрібні у трьох випадках із документації: робота паралельно до основного
потоку; життєвий цикл, визначений подіями, що не йдуть підряд; коли об'єкт треба отримати до
прив'язки до контексту.

```python
from langfuse import get_client

langfuse = get_client()

span = langfuse.start_observation(name="manual-span")
span.update(input="Data for side task")
child = span.start_observation(name="child-span", as_type="generation")
child.end()
span.end()          # обов'язково: інакше спостереження не долетить
```

Пастка ручного режиму описана прямо: «If you use `start_observation()`, you are responsible for
calling `.end()`… Failure to do so will result in incomplete or missing observations in Langfuse».
Друга особливість — ручний спан **не стає активним контекстом**: «the previously active observation
(if any) remains the current context for subsequent operations». Тому глобальний
`langfuse.start_as_current_observation()` усередині такого блоку створить дитину не ручного спану,
а попереднього активного; щоб отримати дитину ручного спану, метод викликають на самому об'єкті —
`parent.start_observation(...)`.

**Зв'язні атрибути.** `user_id`, `session_id`, `metadata`, `version`, `tags`, `trace_name` задає
`propagate_attributes()` — контекстний менеджер, який застосовує їх до поточного й усіх дочірніх
спостережень. Обмеження, які ламають дашборди, якщо їх не знати:

| Обмеження | Деталь |
|---|---|
| Довжина значень | Рядки ≤200 символів |
| Ключі `metadata` | Лише алфавітно-цифрові, без пробілів і спецсимволів |
| Тип `metadata` | `dict[str, str]`: не-рядкові значення приводяться до рядків |
| Невалідні значення | Відкидаються з попередженням — тихо |
| Місце виклику | Якомога раніше в трейсі, інакше частина спостережень лишиться без атрибутів |
| `environment` | У Python це first-class поле, а не metadata: запитове середовище — через `propagate_attributes(environment=...)` |

Для розподіленого трейсингу є `as_baggage=True`: атрибути додаються до вихідних HTTP-заголовків і
переходять у сусідній сервіс. Документація попереджає: «Only use it for non-sensitive values needed
for distributed tracing».

**Ідентифікатори й приєднання до чужого трейсу.** Детермінований `trace_id` будують із зовнішнього
ідентифікатора через seed; щоб вставити спостереження в наявне дерево — передають `trace_context`.
Довільні `observation_id` задавати не можна: «You cannot set arbitrary observation IDs, but you can
generate deterministic trace IDs to correlate with external systems».

```python
from langfuse import get_client

langfuse = get_client()

# Той самий seed -> той самий trace_id
deterministic_trace_id = langfuse.create_trace_id(seed="req_12345")

# Приєднання до наявного трейсу (W3C trace context)
with langfuse.start_as_current_observation(
    as_type="span", name="process-downstream-task",
    trace_context={"trace_id": "abcdef1234567890abcdef1234567890",
                   "parent_span_id": "fedcba0987654321"},
):
    pass

with langfuse.start_as_current_observation(as_type="span", name="my-op") as current_op:
    print(langfuse.get_current_trace_id(), langfuse.get_current_observation_id())
```

**Життєвий цикл клієнта.** `flush()` блокує потік, доки черга не спорожніє; `shutdown()` додатково
чекає завершення фонових потоків (інгестії та завантаження медіа). SDK реєструє хук `atexit`, але
документація радить викликати `shutdown()` вручну в довгоживучих демонах при сигналі зупинки й там,
де `atexit` може не спрацювати (частина serverless-середовищ).

```python
from langfuse import get_client

langfuse = get_client()
# … логіка застосунку …
langfuse.flush()      # відправити все, що в черзі, і дочекатися
langfuse.shutdown()   # коректно зупинити фонові потоки
```

**Ціна захоплення вводу й виводу.** Документація: «Capturing large inputs/outputs may add overhead».
Вимкнути можна точково (`capture_input=False`, `capture_output=False`) або змінною
`LANGFUSE_OBSERVE_DECORATOR_IO_CAPTURE_ENABLED`.

**Типові помилки**

- Ручний `start_observation()` без `.end()`: спостереження не з'явиться, і жодної помилки не буде.
- Очікувати, що глобальні виклики всередині ручного спану стануть його дітьми. Не стануть: ручний
  спан не змінює активний контекст.
- Класти в `metadata` вкладений словник або число: тип `dict[str, str]`, число стане рядком, а
  значення довше 200 символів зникне з попередженням.
- Використовувати baggage для чутливих даних: атрибути підуть у HTTP-заголовки до всіх downstream.
- Забути `set_current_trace_io()`/`set_trace_io()`, якщо покладаєтеся на trace-level
  LLM-as-a-judge: методи застарілі, але досі потрібні саме для таких конфігурацій (див. 23.3).
- Ловити помилку у своєму коді й не давати їй дійти до спану: `status` лишиться `OK`, і в дереві
  не буде видно, що виклик насправді впав.

**Альтернативи.** Що брати в конкретному застосунку:

| Ситуація | Спосіб | Чому |
|---|---|---|
| HTTP-обробник запиту користувача | `start_as_current_observation(as_type="span")` | Природна межа життєвого циклу, контекст активний |
| Функція-крок конвеєра | `@observe()` | Нуль коду всередині функції, автоматичний час і помилки |
| Фонова задача, запущена запитом | `start_observation()` + `.end()` | Життєвий цикл не збігається з блоком `with` |
| Виклик моделі | `as_type="generation"` | Окремий тип для генерацій: модель, `usage`, вартість |
| Крок із власною семантикою | `as_type="tool"` / `as_type="span"` | Типізація дерева для фільтрів |

---

### 23.3 Міграція з v3 на v4

**Що це.** v4 — не «оновлення версії», а зміна моделі даних: замість трейс-центричної моделі
з'являється **спостереження-центрична**. Документація: «The Python SDK v4 introduces the
observations-first data model. In this model, correlating attributes (user_id, session_id, metadata,
tags) propagate to every observation rather than living only on the trace».

**Навіщо це знати.** Міграція ламає три речі одночасно: код інструментації (методи перейменовано),
дашборди (частина спанів перестає експортуватися) і API-запити (простори імен переїхали). Найгірша —
друга, бо не дає помилки: дані просто перестають надходити.

**Як працює під капотом.**

**Зміна 1: розумний фільтр спанів замість «експортувати все».** У v3 експортувалися всі
OpenTelemetry-спани, що створювало шум від інфраструктури (HTTP, БД, черги, внутрішні виклики
фреймворків). У v4 спан експортується, якщо істинне **будь-що** з трьох: спан створив Langfuse
(`langfuse-sdk`); у спані є атрибути `gen_ai.*`; назва instrumentation scope збігається з відомими
LLM-префіксами (`openinference`, `langsmith`, `haystack`, `litellm`).

```python
from langfuse import Langfuse

# 1) Поведінка v3: експортувати все
langfuse = Langfuse(should_export_span=lambda span: True)

# 2) Композиція: типове правило + власний фреймворк
from langfuse.span_filter import is_default_export_span

langfuse = Langfuse(
    should_export_span=lambda span: (
        is_default_export_span(span)
        or (span.instrumentation_scope is not None
            and span.instrumentation_scope.name.startswith("my_framework"))
    )
)
```

`blocked_instrumentation_scopes` у v4 ще працює, але застарілий. Якщо задано **обидва** параметри,
заблоковані scope мають жорстке вето: «blocked scopes still win (hard veto)». Найковарніший наслідок
фільтрації: «Filtering can break trace trees when intermediate or parent spans are dropped while
child spans are still exported». Якщо трейси виглядають розірваними, вмикають debug-режим —
`Langfuse(debug=True)` або `LANGFUSE_DEBUG="True"` — і додають потрібний scope у allowlist.

**Зміна 2: `update_current_trace()` розпався на три виклики.** Зв'язні атрибути переїхали в
`propagate_attributes()`, I/O трейсу — в застарілий `set_current_trace_io()`, публічність —
у `set_current_trace_as_public()`.

| Атрибут | v3 | v4 |
|---|---|---|
| `name` | `update_current_trace(name=...)` | `propagate_attributes(trace_name=...)` |
| `user_id`, `session_id`, `tags`, `version` | `update_current_trace(...)` | `propagate_attributes(...)` |
| `metadata` | `update_current_trace(metadata=any)` | `propagate_attributes(metadata=dict[str,str])` |
| `input`, `output` | `update_current_trace(...)` | `set_current_trace_io(...)` — **застаріле** |
| `public` | `update_current_trace(public=True)` | `set_current_trace_as_public()` |
| `release` | `update_current_trace(release=...)` | Видалено — використовуйте `LANGFUSE_RELEASE` |
| `environment` | `update_current_trace(environment=...)` | `LANGFUSE_TRACING_ENVIRONMENT` або `Langfuse(environment=...)`; для запитового середовища — `propagate_attributes(environment=...)` |

```python
# ── v3 ───────────────────────────────────────────────────────────────────
langfuse.update_current_trace(name="trace-name", user_id="user-123",
                              session_id="session-abc", version="1.0",
                              metadata={"key": "value"}, tags=["tag1"], public=True)

# ── v4 (той самий ефект, три різні механізми) ────────────────────────────
from langfuse import get_client, observe, propagate_attributes

langfuse = get_client()

@observe()
def my_function():
    # (a) зв'язні атрибути; 'name' став 'trace_name'
    with propagate_attributes(trace_name="trace-name", user_id="user-123",
                              session_id="session-abc", version="1.0",
                              metadata={"key": "value"}, tags=["tag1"],
                              environment="staging"):
        result = call_llm("hello")
    # (b) I/O трейсу — застаріле, лише для legacy trace-level LLM-as-a-judge
    langfuse.set_current_trace_io(input={"query": "hello"}, output={"result": result})
    # (c) публічність
    langfuse.set_current_trace_as_public()
```

Той самий розподіл застосовано до методу рівня спостереження: `span.update_trace(...)` розпадається
на `propagate_attributes(...)` навколо виклику, `span.set_trace_io(...)` (застаріле) і
`span.set_trace_as_public()`. Окреме уточнення документації: для інтеграцій (LangChain, OpenAI)
передані атрибути трейсу тепер розповсюджуються **лише вниз**, до дітей, і не піднімаються до трейсу.

**Зміна 3: `start_span()` / `start_generation()` → `start_observation()`.**

| v3 | v4 |
|---|---|
| `langfuse.start_span(name="x")` | `langfuse.start_observation(name="x")` |
| `langfuse.start_as_current_span(name="x")` | `langfuse.start_as_current_observation(name="x")` |
| `langfuse.start_generation(name="x", model="gpt-4")` | `langfuse.start_observation(name="x", as_type="generation", model="gpt-4")` |
| `langfuse.start_as_current_generation(name="x", model="gpt-4")` | `langfuse.start_as_current_observation(name="x", as_type="generation", model="gpt-4")` |
| `span.start_span(name="x")` | `span.start_observation(name="x")` |
| `span.start_generation(name="x")` | `span.start_observation(name="x", as_type="generation")` |

**Зміна 4: простори імен Public API.** Швидкі v2-ресурси стали типовими, старі v2-аліаси видалено:

| v3 / перехідна назва | v4 |
|---|---|
| `langfuse.api.observations_v_2` | `langfuse.api.observations` |
| `langfuse.api.score_v_2` | `langfuse.api.scores` |
| `langfuse.api.metrics_v_2` | `langfuse.api.metrics` |
| `langfuse.api.observations` (legacy v1) | `langfuse.api.legacy.observations_v1` |
| `langfuse.api.score` (legacy v1) | `langfuse.api.legacy.score_v1` |
| `langfuse.api.metrics` (legacy v1) | `langfuse.api.legacy.metrics_v1` |

Практична деталь для тих, хто лишається на self-hosted v3: «On self-hosted Langfuse v3, use
`langfuse.api.legacy.observations_v1` and `langfuse.api.legacy.metrics_v1` instead» — типові
`api.observations` і `api.metrics` вимагають сервера Langfuse v4.

**Зміна 5: `DatasetItemClient.run()` видалено.** Прогін по датасету переїхав у Experiment SDK, який
сам розповсюджує атрибути експерименту й зв'язок з елементом датасету:

```python
# ── v3 ───────────────────────────────────────────────────────────────────
for item in dataset.items:
    with item.run(run_name="my-run", run_metadata={...}) as span:
        span.update(output=my_llm(item.input))

# ── v4 ───────────────────────────────────────────────────────────────────
dataset = get_client().get_dataset("my-dataset")

def my_task(*, item, **kwargs):
    return my_llm(item.input)

dataset.run_experiment(name="my-run", task=my_task)
```

Атрибути даних у `DatasetItem` (`id`, `input`, `expected_output`, `metadata`) не змінилися — зник
лише метод `run()`.

**Зміна 6: `CallbackHandler(update_trace=...)` для LangChain** видалено; передача параметра кидає
`TypeError`. Хендлер тепер використовує `propagate_attributes()` усередині, тому атрибути трейсу
задають зовнішнім спостереженням: `handler = CallbackHandler(trace_context={...})`.

**Зміна 7: типи й Pydantic.** З `langfuse.types` видалено `TraceMetadata` і `ObservationParams`;
`MapValue`, `ModelUsage`, `PromptClient` імпортуйте з `langfuse.model`. SDK v4 вимагає **Pydantic
v2**; застосунку на v1 потрібен shim `pydantic.v1`.

**Валідація.** `propagated metadata` тепер `dict[str, str]` зі значеннями до 200 символів (було
`Any`): не-рядкові приводяться до рядків, задовгі відкидаються з попередженням; `user_id` і
`session_id` — рядки до 200 символів.

**Чекліст міграції з документації:** аудит дашбордів, що залежали від
не-LLM OpenTelemetry-спанів; за потреби `should_export_span=lambda span: True`; перехід з
`blocked_instrumentation_scopes` на композицію `should_export_span`; пошук `update_current_trace` і
`.update_trace(` → розподіл на три механізми; пошук `start_span` / `start_generation` →
`start_observation`; пошук `item.run(` → `dataset.run_experiment()`; пошук
`CallbackHandler(update_trace=` → прибрати параметр; перевірка, що `metadata` — рядки ≤200 символів;
оновлення Pydantic до v2; пошук `*_v_2`-аліасів і legacy v1 на `api.observations` / `api.score` /
`api.metrics` → нові простори імен.

**Типові помилки**

- Оновити SDK, не перевіривши, які спани тепер не експортуються: дашборди «схуднуть» без помилок.
- Залишити `update_current_trace()` у коді інтеграцій і чекати, що атрибути піднімуться до трейсу.
  У v4 передані атрибути доходять лише до дітей.
- Оновити Python SDK до v4, а сервер лишити на v3: типові `api.observations` / `api.metrics`
  вимагають сервера v4 — беріть `api.legacy.*_v1`.
- Забути, що `metadata` тепер лише рядкові значення: числа й вкладені структури втратять форму.
- Покладатися на `blocked_instrumentation_scopes` у новому коді — він застарілий.

**Альтернативи.** Міграцію можна зробити одною зміною версії або поетапно; вибір визначає, чим ви
платите:

| Стратегія | Плюс | Мінус |
|---|---|---|
| Оновити SDK і одразу ввімкнути типовий фільтр | Менше шуму, швидші запити | Ризик зламати дашборди й розірвати дерева |
| Оновити SDK із `should_export_span=lambda span: True` | Поведінка v3 збережена, зміни лише в коді | Шум і повільніші запити лишаються |
| Оновити SDK, лишивши сервер v3, і перейти на `api.legacy.*_v1` | Контрольований перехід | Дві системи в експлуатації одночасно |

---

### 23.4 Промпти як керовані версійовані артефакти

**Що це.** Промпт-менеджмент Langfuse — сховище промптів із назвою, типом, версіями й мітками
(labels). Промпт живе не в коді, а в платформі; код забирає його в рантаймі за назвою й міткою.

**Навіщо це знати.** Промпт змінюють найчастіше, і саме він найгірше відслідковується в git-історії
застосунку. Керовані промпти дають дві речі, яких не дає константа в коді: **версію, прив'язану до
конкретного трейсу**, і можливість підвищити нову версію в продакшн без релізу коду.

**Як працює під капотом.**

Повторне створення промпту з **тією самою назвою** не перезаписує його, а додає **нову версію**:
«If you already have a prompt with the same name, the prompt will be added as a new version».

```python
from langfuse import get_client

langfuse = get_client()

# Текстовий промпт
langfuse.create_prompt(
    name="movie-critic",
    type="text",
    prompt="As a {{criticlevel}} movie critic, do you like {{movie}}?",
    labels=["production"],          # одразу підвищити до production
)

# Чат-промпт
langfuse.create_prompt(
    name="movie-critic-chat",
    type="chat",
    prompt=[
        {"role": "system", "content": "You are an {{criticlevel}} movie critic"},
        {"role": "user", "content": "Do you like {{movie}}?"},
    ],
    labels=["production"],
)

# Читання й компіляція: типово забирається версія з міткою production
prompt = langfuse.get_prompt("movie-critic")
compiled = prompt.compile(criticlevel="expert", movie="Dune 2")
# -> "As an expert movie critic, do you like Dune 2?"

chat_prompt = langfuse.get_prompt("movie-critic-chat", type="chat")
messages = chat_prompt.compile(criticlevel="expert", movie="Dune 2")
# -> [{"role": "system", "content": "You are an expert movie critic"},
#     {"role": "user", "content": "Do you like Dune 2?"}]
```

Через Public API те саме доступно без SDK, а конкретну версію можна взяти за номером, а не за міткою:

```bash
# Створити промпт
curl -X POST "https://cloud.langfuse.com/api/public/v2/prompts" \
  -u "your-public-key:your-secret-key" -H "Content-Type: application/json" \
  -d '{"type": "chat", "name": "movie-critic",
       "prompt": [{"role": "user", "content": "Do you like {{movie}}?"}]}'

# Забрати версію з міткою production; ?version=1 — конкретну версію
curl "https://cloud.langfuse.com/api/public/v2/prompts/movie-critic?label=production" \
  -u "your-public-key:your-secret-key"
```

**Кеш промптів — головна механіка.** Документація: «Prompt Management is not on the critical path
of your application. The SDKs cache prompts client-side, so after the first fetch they are served
from memory with no extra latency. If Langfuse goes down, your application continues to use the
cached prompt». Платформа не стає точкою відмови застосунку — але саме через кеш нова версія не
з'являється миттєво; у документації є окремий пункт «Not seeing your latest version? This might be
because of the caching behavior». На сервері кеш теж є: read-through кеш промптів у Redis.

**Різниця синтаксису з LangChain.** Langfuse використовує `{{змінна}}`, LangChain — `{}`, тому є
окремий метод-перекладач:

```python
from langfuse import Langfuse
from langchain_core.prompts import ChatPromptTemplate

langfuse = Langfuse()

langfuse_prompt = langfuse.get_prompt("movie-critic")
langchain_prompt = ChatPromptTemplate.from_template(langfuse_prompt.get_langchain_prompt())

# Частину змінних можна скомпілювати наперед
langchain_prompt = ChatPromptTemplate.from_template(
    langfuse_prompt.get_langchain_prompt(strictness="tough")
)

langfuse_chat = langfuse.get_prompt("movie-critic-chat", type="chat")
langchain_chat = ChatPromptTemplate.from_messages(langfuse_chat.get_langchain_prompt())
```

**Що дає прив'язка промпту до трейсу.** Документація перелічує три речі: аналізувати якість **за
версією промпту**, покращувати промпти експериментами на датасеті, керувати розгортанням між
середовищами через версії й мітки.

**Типові помилки**

- Забирати промпт без мітки й дивуватися чужій версії: типово повертається `production`, і саме
  тому мітку треба ставити свідомо.
- Створити промпт із типом `text`, а потім робити з нього чат-промпт. У UI тип вибирається при
  створенні й **не змінюється** потім — доведеться створити новий промпт.
- Чекати, що оновлення промпту в платформі миттєво змінить поведінку всіх інстансів: кеш
  клієнтський.
- Забути про різницю `{{ }}` і `{ }` при переході на LangChain — змінні просто не підставляться.
- Тримати промпт без версійного контролю «щоб швидше»: тоді неможливо сказати, чому якість упала
  вчора, — прив'язки версії до трейсу немає.
- Складати в промпт секрети або персональні дані: промпт — такий самий артефакт телеметрії, як трейс.

**Альтернативи.**

| Спосіб | Плюс | Мінус |
|---|---|---|
| Промпт у платформі (Langfuse) | Версії, мітки, підвищення без релізу, прив'язка до трейсів, експерименти на датасеті | Ще одна система; кеш треба розуміти |
| Промпт у git (константа, файл, шаблонізатор) | Один код-рев'ю, один реліз, повна історія | Зміна промпту = реліз; у трейсі видно текст, не версію |
| Гібрид: git як джерело, платформа як runtime | Історія в git, мітки й A/B у платформі | Потрібна дисципліна синхронізації двох джерел |

---

### 23.5 Датасети й оцінки в платформі

**Що це.** Датасет — «a collection of inputs and expected outputs», набір тестових випадків для
застосунку. Оцінка (score) — числовий, категоріальний, булевий або текстовий результат оцінювання,
прикріплений до трейсу, спостереження або сесії. Експеримент проганяє функцію по всіх елементах
датасету й збирає оцінки.

**Навіщо це знати.** Це місток між «мені здається, стало краще» і вимірюваним твердженням. Датасет
зберігає еталон, а оцінки роблять порівняння версій відтворюваним — включно з відтворенням на
**історичному стані** датасету.

**Як працює під капотом.**

```python
from langfuse import get_client

langfuse = get_client()

langfuse.create_dataset(
    name="qa-conversations",
    description="Питання й відповіді служби підтримки",
    metadata={"author": "Alice", "type": "benchmark"},
)

langfuse.create_dataset_item(
    dataset_name="qa-conversations",
    input={"text": "hello world"},
    expected_output={"text": "hello world"},
    metadata={"model": "llama3"},
)
```

**Схема даних (schema enforcement)** необов'язкова, але саме вона ловить помилки даних на вході:
якщо задати `input_schema` або `expected_output_schema` (звичайні JSON Schema), усі елементи
перевіряються проти них, а невалідні відхиляються з детальним повідомленням. У прикладі з
документації схема описує масив повідомлень із полями `role` (перелік `user`/`assistant`/`system`)
і `content`, а схема очікуваного виходу — обов'язкове поле `response`.

**Версіонування датасетів.** Кожне додавання, оновлення, видалення або архівування елемента створює
**нову версію**; версії розрізняються мітками часу. GET-запити типово повертають останню версію.
Обмеження прямо з документації: «Versioning applies to dataset items only, not dataset schemas».

```python
from datetime import datetime, timezone

# Стан датасету на 2025-12-15 06:30:00 UTC
version_timestamp = datetime(2025, 12, 15, 6, 30, 0, tzinfo=timezone.utc)
dataset_at_version = langfuse.get_dataset(name="my-dataset", version=version_timestamp)

def my_llm_application(*, item, **kwargs):
    return item.expected_output          # тут був би ваш застосунок

result = dataset_at_version.run_experiment(
    name="Baseline Experiment v1", description="Running on dataset v1",
    task=my_llm_application,
)
```

**Оцінки.** Чотири типи даних, кожен зі своїми правилами:

| Тип | Значення | Особливість |
|---|---|---|
| `NUMERIC` | float | Може валідуватися діапазоном із `config_id` |
| `CATEGORICAL` | рядок | Має збігатися з однією з категорій конфігу |
| `BOOLEAN` | float `0` або `1` | `data_type` треба вказати **явно**, інакше `0/1` буде витлумачено як `NUMERIC` |
| `TEXT` | рядок 1–500 символів | Порожній рядок не приймається |

```python
from langfuse import get_client

langfuse = get_client()

# Спосіб 1: низькорівневий виклик
langfuse.create_score(
    name="correctness", value=0.9,
    trace_id="trace_id_here", observation_id="observation_id_here",  # друге — опційне
    data_type="NUMERIC", comment="Factually correct",
)

# Спосіб 2: через об'єкт спостереження
with langfuse.start_as_current_observation(as_type="span", name="my-operation") as span:
    span.score(name="correctness", value=0.9, data_type="NUMERIC")
    span.score_trace(name="overall_quality", value=0.95, data_type="NUMERIC")

# Спосіб 3: через поточний контекст
with langfuse.start_as_current_observation(as_type="span", name="my-operation"):
    langfuse.score_current_span(name="accuracy", value="partially correct",
                                data_type="CATEGORICAL")
    langfuse.score_current_trace(name="overall_quality", value=1, data_type="BOOLEAN")

# Оцінка цілої сесії: передається лише session_id
langfuse.create_score(name="session_quality", value=0.85,
                      session_id="session_id_here", data_type="NUMERIC")
```

Три деталі, які визначають, чи зійдуться оцінки. **Оцінка спостереження вимагає обох
ідентифікаторів**: «If you attach a score to an observation, always provide both the observation ID
and the corresponding trace ID». **Оцінка ідентифікується трійкою** `id` + `name` + дата: щоб
оновити оцінку замість створення другої, передають ідемпотентний ключ `score_id` (Python) і тримають
незмінними назву та час. **Часткові оновлення застарілі**: «Always send the complete score».

**Score Configs** стандартизують оцінки на рівні проєкту. З `config_id` значення валідується за
конфігом: назва мусить дорівнювати назві конфігу, тип — збігатися, числове значення — бути в межах
`min`/`max`, категоріальне — належати списку категорій, булеве — дорівнювати `0` або `1`, текстове —
бути непорожнім рядком до 500 символів.

**Оцінки з браузера.** Для фідбеку користувача є браузерний SDK, якому потрібен **лише публічний
ключ**; він відправляє оцінку негайно, без `flush()`. Документація попереджає: «Do not expose a
secret key in browser code».

**Типові помилки**

- Ставити оцінку спостереженню лише з `observation_id` без `trace_id` — документація вимагає обидва.
- Передавати `0`/`1` для булевої оцінки без `data_type="BOOLEAN"`: отримаєте `NUMERIC`.
- Надсилати часткові оновлення оцінки й чекати злиття — це застаріла поведінка, яку приберуть.
- Будувати датасет із уже згенерованими відповідями. Документація: «Dataset uploads are meant to
  upload the input and expected output. If you already have generated outputs, please use the
  Experiments SDK».
- Покладатися на версію датасету для схеми — версіонуються лише елементи.
- Використовувати медіа в UI-експериментах: з медіавкладеннями працюють лише SDK-експерименти
  (Python SDK ≥ 4.10.0).

**Альтернативи.**

| Метод | Хто рахує | Коли брати |
|---|---|---|
| Оцінки через SDK/API | Ваш застосунок, конвеєр або CI | Потрібна власна логіка: детерміновані перевірки, бізнес-метрики |
| Code evaluators | Langfuse виконує ваш Python/TS | Детермінована логіка без вашого сервісу |
| LLM-as-a-judge | Langfuse + LLM | Оцінювання якості там, де немає еталона |
| Human annotation (черги анотацій) | Люди | Розмітка еталонів, спірні випадки |
| External evaluation pipelines | Зовнішня система | Уже наявний конвеєр оцінювання |
| Фідбек користувача (браузерний SDK) | Користувач | Продуктова якість «у полі» |

Перші п'ять рядків — рядки таблиці можливостей Langfuse на сторінці цін; браузерний SDK описано
в документації оцінок.

---

### 23.6 Self-hosting і ціна

**Що це.** Langfuse можна взяти як хмарний сервіс або розгорнути на своїй інфраструктурі: Docker
Compose для локального запуску, Kubernetes (Helm) і Terraform-модулі для продакшну. Документація
підкреслює: «Langfuse OSS and Enterprise use the same codebase as Langfuse Cloud».

**Навіщо це знати.** Вибір між хмарою й self-hosting вирішує не лише гроші, а й те, де опиняться
промпти й вміст запитів — найчутливіша частина телеметрії. Крім того, self-hosting Langfuse — це не
«один контейнер», а п'ять сховищ, і планувати треба кожне.

**Як працює під капотом.**

| Компонент | Роль |
|---|---|
| Langfuse Web | Вебзастосунок: UI та API |
| Langfuse Worker | Асинхронна обробка подій |
| Postgres | Транзакційна база |
| ClickHouse | OLAP-база: трейси, спостереження, оцінки |
| Redis/Valkey | Кеш і черги |
| S3 / blob storage | Об'єктне сховище: усі вхідні події, мультимодальні входи, великі вивантаження |
| LLM API / Gateway | Деякі функції залежать від зовнішньої LLM; доступ в інтернет — опційний |

Механіка інгестії пояснює, чому система витримує піки: трейси приймаються **пакетами** контейнером
Langfuse Web і одразу пишуться в S3, у Redis потрапляє лише посилання для черги, а Worker забирає
їх із S3 і вставляє в ClickHouse. Мета сформульована прямо: «This ensures that high spikes in
request load do not lead to timeouts or errors constrained by the database». Події лишаються в S3 і
тоді, коли база тимчасово недоступна: «even if the database is temporarily unavailable, the events
are not lost». Інші оптимізації з документації: кеш API-ключів у Redis, read-through кеш промптів,
«hyper-optimized ClickHouse schema» без join-ів на читанні, винесення мультимодальних даних у S3,
фонові міграції. Масштаб, заявлений там само: понад **90 мільярдів спостережень на місяць**,
«trusted by 21 of the Fortune 50», Docker-образи завантажено понад **38 мільйонів** разів.

**Локальний запуск.**

```bash
git clone https://github.com/langfuse/langfuse.git
cd langfuse

# Спершу оновити секрети в docker-compose.yml: усі чутливі рядки позначені # CHANGEME.
docker compose up

# Через 2–3 хвилини контейнер langfuse-web-1 має залогувати "Ready"
# UI доступний на http://localhost:3000
```

Деталі, які зазвичай забувають: **облікового запису за замовчуванням немає** — «Langfuse does not
ship with a built-in admin account or password», першого користувача створюють через Sign up або
headless-ініціалізацію. Для VM документація радить мінімум 4 ядра й 16 GiB пам'яті (приклад —
`t3.xlarge` на AWS) та диск на 100 GiB; доступ ззовні потрібен лише `langfuse-web` і `minio`,
тому вхідний трафік обмежують портами `:3000` і `:9090`.

**Ціна Langfuse Cloud** (знімок сторінки цін на 09.2026):

| План | Ціна | Включено | Історія даних | Користувачі |
|---|---|---|---|---|
| Hobby | Безкоштовно | 50k units/міс | 30 днів | 2 |
| Core | $29/міс | 100k units/міс, далі $8/100k | 90 днів | Без обмежень |
| Pro | $199/міс | 100k units/міс, далі $8/100k | 3 роки | Без обмежень |
| Enterprise | $2499/міс | 100k units/міс, далі $8/100k | 3 роки | Без обмежень |
| Teams (додаток до Pro) | $300/міс | SSO, RBAC, підтримка в Slack/Teams | — | — |

Ліміти, які найчастіше стають стелею на практиці:

| Параметр | Hobby | Core | Pro |
|---|---|---|---|
| Пропускна здатність інгестії | 1 000 запитів/хв | 4 000 запитів/хв | 20 000 запитів/хв |
| Загальний API | 30 запитів/хв | 100 запитів/хв | 1 000 запитів/хв |
| Observations API v2 | 30 запитів/хв | 100 запитів/хв | 1 000 запитів/хв |
| Metrics API v2 | 100 запитів/добу | 100 запитів/год | 500 запитів/год |
| Datasets API · Алерти | 100/хв · 2 | 200/хв · 20 | 1 000/хв · 50 |
| Черги ручної анотації | 1 | 3 | Без обмежень |
| Регіони даних | US, EU, JP | US, EU, JP | US, EU, JP, HIPAA |
| Звіти SOC2 Type II та ISO27001 | — | — | Є |

**Що не вдалося підтвердити.** У знімку сторінки цін немає визначення одиниці виміру («unit»):
скільки саме спостережень чи подій вона означає, **підтвердити не вдалося станом на 09.2026**.
Так само не підтверджено ціни й умови комерційної ліцензії для self-hosted: сторінка self-hosting
каже лише, що «some add-on features require a license key», а enterprise-підтримка доступна за
окремою ціною; конкретних цифр для self-hosted у знімку `research/10/lf_pricing.txt` немає.

**Типові помилки**

- Вважати Docker Compose продакшн-розгортанням: документація прямо каже, що конфігурація «lacks
  high-availability, scaling capabilities, and backup functionality».
- Забути про ClickHouse і S3 у плануванні: без об'єктного сховища й достатнього диска система
  впаде не від навантаження, а від місця.
- Не оновити секрети в `docker-compose.yml`: рядки з `# CHANGEME` — це реальні секрети (Postgres,
  Redis, NextAuth, S3, шифрування).
- Відкрити ззовні весь стек: документація радить лишати доступними лише `langfuse-web` і `minio`.
- Переносити ліміти API з таблиці вище на self-hosted: вони стосуються **Cloud**.
- Планувати бюджет без урахування зростання історії: 30 днів, 90 днів і 3 роки — це різні обсяги
  ClickHouse.

**Альтернативи.**

| Варіант | Відповідальність | Коли брати |
|---|---|---|
| Langfuse Cloud | Повністю на команді Langfuse | Найшвидший старт, немає інфраструктури |
| Docker Compose | На вас: одна VM без HA, масштабування й бекапів | Локальна робота, тестування, пілот |
| Kubernetes (Helm), AWS/Azure/GCP (Terraform) | На вас | Продакшн із вимогами до доступності |
| Render / Railway | На вас, але простіше | Швидкий продакшн-старт без K8s; підтримка спільноти |

Останній рядок — з таблиці варіантів розгортання; Render і Railway позначені там як
community-supported, тобто підтримуються в сторонніх репозиторіях на засадах best-effort.

---

### 23.7 OpenTelemetry GenAI: семантичні конвенції

**Що це.** Семантичні конвенції (semantic conventions) GenAI — стандарт OpenTelemetry: які спани
створювати, як їх називати, які атрибути й події додавати, які метрики публікувати. Це той спільний
словник, завдяки якому трейс Langfuse, трейс OpenLLMetry і трейс вашого коду описують ту саму
реальність однаковими ключами.

**Навіщо це знати.** Три причини. Перша: **назви ключів не вигадують** — вигаданий ключ не потрапить
у жоден дашборд і не дасть помилки. Друга: конвенції визначають, які дані обов'язкові, а які
Opt-In, і це прямо впливає на приватність. Третя: поки ви пишете `gen_ai.system`, решта світу пише
`gen_ai.provider.name`, і ваша інструментація несумісна з готовими панелями.

**Важлива примітка про джерела.** Сторінки семантичних конвенцій GenAI на `opentelemetry.io` —
`gen-ai-spans`, `gen-ai-events`, `gen-ai-metrics`, `gen-ai-agent-spans` — на момент збору джерел
**уже не містять специфікації**: усі чотири віддають однаковий текст «GenAI semantic conventions
have moved to the OpenTelemetry GenAI semantic conventions repository. This page has moved and is
no longer maintained in this repository». Знімки цих сторінок у репозиторії довідника —
`research/10/otel_spans.txt`, `otel_events.txt`, `otel_metrics.txt`, `otel_agent.txt` — корисні як
доказ переїзду, а не як джерело специфікації. Актуальна специфікація — у репозиторії
[`open-telemetry/semantic-conventions-genai`](https://github.com/open-telemetry/semantic-conventions-genai)
(копії в довіднику: `research/10/otel_spans_x.txt`, `otel_events_x.txt`, `otel_metrics_x.txt`,
`otel_token-metrics_x.txt`, `otel_agent-spans_x.txt`). Реєстр **назв атрибутів** досі віддається за
адресою `opentelemetry.io/docs/specs/semconv/registry/attributes/gen-ai/` — знімок лежить у
`research/10/otel_attrs.txt`, і всі назви атрибутів у цьому розділі взяті саме з нього.

**Як працює під капотом.**

**Спани.** Для кожної операції конвенції задають тип, назву й набір атрибутів:

| Операція | `gen_ai.operation.name` | Формат назви спану | Тип спану |
|---|---|---|---|
| Інференс | `chat`, `generate_content`, `text_completion` | `{gen_ai.operation.name} {gen_ai.request.model}` | `CLIENT` (або `INTERNAL`, якщо модель у тому самому процесі) |
| Ембединги | `embeddings` | `{gen_ai.operation.name} {gen_ai.request.model}` | `CLIENT` |
| Пошук (retrieval) | `retrieval` | `{gen_ai.operation.name} {gen_ai.data_source.id}` | `CLIENT` |
| Створення агента | `create_agent` | `create_agent {gen_ai.agent.name}` | — |
| Виклик агента | `invoke_agent` | `invoke_agent {gen_ai.agent.name}` (якщо ім'я доступне) | — |

Дві деталі, які впливають на метрики: спан інференсу **охоплює всі ретраї** («the corresponding
span SHOULD cover the duration of the logical operation with all retries»), а для операції
`fetch_response` конвенції кажуть не рапортувати використання токенів узагалі.

| Рівень | Що означає | Приклади для спану інференсу |
|---|---|---|
| `Required` | Мусить бути завжди | `gen_ai.operation.name`, `gen_ai.provider.name` |
| `Conditionally Required` | Мусить бути, якщо виконується умова | `error.type` (якщо була помилка), `gen_ai.request.model`, `gen_ai.request.stream`, `gen_ai.prompt.name`, `gen_ai.conversation.id`, `gen_ai.output.type`, `server.port` |
| `Recommended` | Бажано | `gen_ai.request.temperature`, `gen_ai.request.max_tokens`, `gen_ai.response.id`, `gen_ai.response.finish_reasons`, `gen_ai.response.time_to_first_chunk`, `gen_ai.usage.*`, `server.address` |
| `Opt-In` | Лише за явним увімкненням | `gen_ai.input.messages`, `gen_ai.output.messages`, `gen_ai.system_instructions`, `gen_ai.tool.definitions`, `gen_ai.retrieval.documents`, `gen_ai.retrieval.query.text` |

**Облік токенів** — найуживаніша частина реєстру:

| Ключ | Тип | Що означає |
|---|---|---|
| `gen_ai.usage.input_tokens` | int | Усі вхідні токени, **разом із кешованими** |
| `gen_ai.usage.output_tokens` | int | Усі вихідні, разом із reasoning |
| `gen_ai.usage.cache_read.input_tokens` | int | Вхідні з кешу провайдера — **входить** у `input_tokens` |
| `gen_ai.usage.cache_creation.input_tokens` | int | Записані в кеш — **входить** у `input_tokens` |
| `gen_ai.usage.reasoning.output_tokens` | int | Токени міркування — **входить** у `output_tokens` |
| `gen_ai.token.type` | string | `input` або `output` |

Правило підмножин — джерело найдорожчих помилок у дашбордах. Приклад із документації: `input_tokens`
= 300, `cache_read.input_tokens` = 40, `output_tokens` = 180, `reasoning.output_tokens` = 50.
Сумувати `input_tokens` і `cache_read.input_tokens` не можна: кешовані токени вже всередині.

**Провайдери.** `gen_ai.provider.name` — обов'язковий атрибут і водночас дискримінатор формату
даних: «GenAI spans, metrics, and events related to AWS Bedrock should have the
`gen_ai.provider.name` set to `aws.bedrock` and include applicable `aws.bedrock.*` attributes and
are not expected to include `openai.*` attributes». Усталені значення зі знімка реєстру:
`anthropic`, `aws.bedrock`, `azure.ai.inference`, `azure.ai.openai`, `cohere`, `deepseek`,
`gcp.gemini`, `gcp.gen_ai`, `gcp.vertex_ai`, `groq`, `ibm.watsonx.ai`, `mistral_ai`, `openai`,
`perplexity`, `x_ai`.

**Застарілі ключі.** Найкорисніша частина реєстру для міграцій:

| Застарілий ключ | Статус у знімку реєстру |
|---|---|
| `gen_ai.system` | Замінено на `gen_ai.provider.name` |
| `gen_ai.usage.prompt_tokens` | Замінено на `gen_ai.usage.input_tokens` |
| `gen_ai.usage.completion_tokens` | Замінено на `gen_ai.usage.output_tokens` |
| `gen_ai.prompt`, `gen_ai.completion` | Видалено без заміни: вміст промпту й відповіді — через Event API |
| `gen_ai.openai.request.seed` | Замінено на `gen_ai.request.seed` |
| `gen_ai.openai.request.response_format` | Замінено на `gen_ai.output.type` |
| `gen_ai.openai.request.service_tier` | Замінено на `openai.request.service_tier` |
| `gen_ai.openai.response.system_fingerprint` | Замінено на `openai.response.system_fingerprint` |

**Відомі значення — закритий список.** Конвенції вимагають використовувати усталене значення, якщо
воно застосовне, і дозволяють власне лише інакше: `gen_ai.operation.name` — `chat`, `create_agent`,
`embeddings`, `execute_tool`, `generate_content`, `invoke_agent`, `invoke_workflow`, `retrieval`,
`text_completion`; `gen_ai.output.type` — `image`, `json`, `speech`, `text`; `gen_ai.token.type` —
`input`, `output`; `gen_ai.tool.type` — `function`, `extension`, `datastore`.

**Події.** Їх у новій специфікації дві, і обидві несуть те, що не місце в атрибутах спану:

| Подія | Рівень | Призначення |
|---|---|---|
| `gen_ai.client.inference.operation.details` | Opt-In | Деталі запиту: історія чату, системні інструкції, визначення інструментів, параметри |
| `gen_ai.evaluation.result` | Recommended | Результат оцінювання: назва метрики, значення, мітка, пояснення |

Подія оцінювання приєднується до спану, який оцінюють, або, якщо спан недоступний, зв'язується
через `gen_ai.response.id`: «This event SHOULD be parented to GenAI operation span being evaluated
when possible or set `gen_ai.response.id` when span id is not available». Обов'язкові атрибути обох
подій — `gen_ai.operation.name` і `gen_ai.provider.name`; у події оцінювання обов'язковий
`gen_ai.evaluation.name`.

**Метрики.** Клієнтські та серверні інструменти зі специфікації:

| Метрика | Тип | Одиниця |
|---|---|---|
| `gen_ai.client.operation.duration` | Histogram | `s` |
| `gen_ai.client.operation.time_to_first_chunk` | Histogram | `s` |
| `gen_ai.client.operation.time_per_output_chunk` | Histogram | `s` |
| `gen_ai.client.inference.usage.input_tokens` | Counter | `{token}` |
| `gen_ai.client.inference.usage.output_tokens` | Counter | `{token}` |
| `gen_ai.client.inference.usage.cache_read.input_tokens` | Counter | `{token}` |
| `gen_ai.client.inference.usage.cache_creation.input_tokens` | Counter | `{token}` |
| `gen_ai.client.inference.usage.reasoning.output_tokens` | Counter | `{token}` |
| `gen_ai.server.request.duration` | Histogram | `s` |
| `gen_ai.server.time_to_first_token` | Histogram | `s` |
| `gen_ai.server.time_per_output_token` | Histogram | `s` |

Останні три — для тих, хто сам роздає моделі. Для `gen_ai.client.operation.duration` і
`gen_ai.client.operation.time_to_first_chunk` специфікація задає явні межі бакетів:
`[0.01, 0.02, 0.04, 0.08, 0.16, 0.32, 0.64, 1.28, 2.56, 5.12, 10.24, 20.48, 40.96, 81.92]`
секунд. Без цих меж перцентилі вашого застосунку й застосунку колеги непорівнювані.

**Робочий приклад.** Скорочений фрагмент ноутбука `notebooks/23-observability.ipynb`: мінімальний
перехоплювач спанів, що повторює форму OTLP-структур, і трейс одного запиту агента.

```python
import contextvars, hashlib, secrets, time
from contextlib import contextmanager
from dataclasses import dataclass, field

def new_trace_id() -> str:
    return secrets.token_hex(16)          # 32 hex-символи (16 байтів)

def new_span_id() -> str:
    return secrets.token_hex(8)           # 16 hex-символів (8 байтів)

def deterministic_trace_id(seed: str) -> str:
    """Той самий seed -> той самий trace_id (як create_trace_id(seed=...) у Langfuse)."""
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()[:32]

_CURRENT_SPAN = contextvars.ContextVar("current_span", default=None)

@dataclass
class Span:
    name: str
    kind: str                             # "CLIENT" | "INTERNAL"
    trace_id: str
    span_id: str
    parent_span_id: str | None
    start_ns: int
    end_ns: int | None = None
    attributes: dict = field(default_factory=dict)
    events: list = field(default_factory=list)
    status: dict = field(default_factory=lambda: {"code": "UNSET"})
    instrumentation_scope: str = "dovidnyk.observability"

    def set_attribute(self, key, value):
        self.attributes[key] = value

    def end(self):
        self.end_ns = self.end_ns or time.time_ns()

@contextmanager
def start_span(name, *, kind="INTERNAL", attributes=None, parent=None):
    """Батьківство береться з контексту — руками parent не передають."""
    parent_span = parent if parent is not None else _CURRENT_SPAN.get()
    span = Span(name, kind,
                parent_span.trace_id if parent_span else new_trace_id(),
                new_span_id(),
                parent_span.span_id if parent_span else None,
                time.time_ns(), attributes=dict(attributes or {}))
    token = _CURRENT_SPAN.set(span)
    try:
        yield span
    except Exception as exc:                  # помилка теж частина трейсу
        span.set_attribute("error.type", type(exc).__name__)
        span.status = {"code": "ERROR", "message": str(exc)}
        raise
    finally:
        span.end()
        _CURRENT_SPAN.reset(token)
```

Той самий трейс на реальному запуску ноутбука (модель `gpt-4` — значення з прикладів конвенцій;
вивід справжній):

```
Спанів у трейсі: 4
trace_id       : 13475d1af737132b1ccdff6003986f22

retrieval H7STPQYOND         span=f7e3f1f4 parent=f5f42aa3  10.09 ms  attrs=5
execute_tool track_shipment  span=625117e7 parent=aa1aff60   5.14 ms  attrs=7
chat gpt-4                   span=aa1aff60 parent=f5f42aa3  35.32 ms  attrs=19
invoke_agent support-bot     span=f5f42aa3 parent=—  45.51 ms  attrs=7
```

`execute_tool` — дитина `chat`, а `chat` і `retrieval` — діти `invoke_agent`. Батьківство не задано
жодного разу явно: воно взялося з контексту. Тривалість кожного кроку окрема, тому «запит триває
45 мс» розкладається на 35 мс моделі, 10 мс пошуку й 5 мс інструмента.

Події з вмістом збираються окремо від атрибутів спану: у прогоні ноутбука спан `chat gpt-4`
має 4 атрибути й 2 події — `gen_ai.client.inference.operation.details` (з ключами
`gen_ai.system_instructions`, `gen_ai.input.messages`, `gen_ai.output.messages`,
`gen_ai.tool.definitions`) і `gen_ai.evaluation.result`.

Метрики рахуються з тих самих спанів: у прогоні ноутбука counter
`gen_ai.client.inference.usage.input_tokens` = 6780, `output_tokens` = 1866,
`cache_read.input_tokens` = 1200, а гістограма `gen_ai.client.operation.duration` накопичувальна:
9 із 12 запитів упали в перші чотири бакети, решта три — у бакет `<= 0.08s`, далі всі 12 у `+Inf`.

**Перевірка назв машиною.** Найдешевший спосіб не вигадати ключ — звіряти його з реєстром
регуляркою (фрагмент самоперевірки ноутбука):

```python
import pathlib
import re

registry_text = pathlib.Path("research/10/otel_attrs.txt").read_text(encoding="utf-8")

# У реєстрі ключ стоїть на початку рядка і завершується " |".
REGISTRY_KEYS = set(re.findall(r"^(gen_ai\.[a-z0-9_.]+) \|", registry_text, flags=re.M))

DEPRECATED_KEYS = {
    "gen_ai.system", "gen_ai.usage.prompt_tokens", "gen_ai.usage.completion_tokens",
    "gen_ai.prompt", "gen_ai.completion",
}

USED_KEYS = {
    "gen_ai.operation.name", "gen_ai.provider.name", "gen_ai.request.model",
    "gen_ai.response.model", "gen_ai.usage.input_tokens", "gen_ai.conversation.id",
    "gen_ai.retrieval.query.text", "gen_ai.retrieval.documents",
    "gen_ai.tool.call.result", "gen_ai.evaluation.score.label", "gen_ai.data_source.id",
}

unknown = sorted(USED_KEYS - REGISTRY_KEYS)
assert not unknown, f"вигадані назви: {unknown}"
assert not (USED_KEYS & DEPRECATED_KEYS), "у коді є застарілі ключі"
print(f"усі {len(USED_KEYS)} назв підтверджені otel_attrs.txt")
```

Фактичний вивід цієї перевірки:

```
Ключів у реєстрі (otel_attrs.txt): 60
Застарілих серед них             : 5
Перевіряємо ключів              : 11

Ключі, яких немає в реєстрі: немає

Застарілі ключі, які НЕ можна використовувати: ['gen_ai.completion', 'gen_ai.prompt', 'gen_ai.system', 'gen_ai.usage.completion_tokens', 'gen_ai.usage.prompt_tokens']
```

**Типові помилки**

- Додавати підмножини до цілих: `input_tokens + cache_read.input_tokens` — подвійний облік у рахунку.
- Рапортувати `top_logprobs` як `gen_ai.request.top_k`: конвенції прямо забороняють, бо
  `top_logprobs` лише повертає лог-імовірності й не змінює генерацію.
- Вигадувати `conversation.id`, коли його немає: «a new UUID, a trace identifier, or a hash of
  request content SHOULD NOT be used as a fallback value».
- Ставити `gen_ai.system` замість `gen_ai.provider.name` — дані не потраплять у панелі, які
  фільтрують за новим ключем.
- Писати вміст в атрибути спану замість подій: втрачається Opt-In-контроль, а обсяг телеметрії
  зростає на порядок.
- Заповнювати `gen_ai.retrieval.documents` завжди. Це `Opt-In`, і документ радить не заповнювати
  необов'язкові властивості типово: «Since this attribute could be large, it's NOT RECOMMENDED to
  populate non-required properties by default».
- Будувати гістограму на власних межах: для `duration` і `time_to_first_chunk` вони задані
  специфікацією.

**Альтернативи.**

| Спосіб | Хто формує атрибути | Коли брати |
|---|---|---|
| Langfuse SDK v4 | SDK: він сам ставить `gen_ai.*` і зв'язні атрибути | Python/JS-застосунок, потрібні промпти, оцінки й датасети з коробки |
| OTel-сумісна бібліотека інструментації (OpenLLMetry, OpenLIT, Arize) | Бібліотека | Мова поза Python/JS або вже покритий фреймворк |
| Ручна інструментація на OTel SDK | Ви | Нестандартний конвеєр, повний контроль, готовність писати атрибути руками |

---

### 23.8 Коли Langfuse, а коли «сирий» OTel

**Що це.** Langfuse можна використовувати двома принципово різними способами: через власний SDK
(який сам формує спани й атрибути) або як **OTLP-бекенд**, куди застосунок відправляє власні
OpenTelemetry-спани. Другий шлях не вимагає SDK Langfuse взагалі й працює з будь-якої мови.

**Навіщо це знати.** Вибір визначає, скільки роботи ви робите руками. SDK бере на себе атрибути,
розповсюдження, медіа, фільтрацію й експорт; прямий OTel дає свободу й переносимість, але кожен
атрибут ви ставите самі — і кожен зобов'язані поставити правильно, інакше фільтри й агрегації
в бекенді не працюватимуть.

**Як працює під капотом.** Langfuse приймає трейси на OTLP-ендпоінті `/api/public/otel`:

```bash
# EU-регіон; інші — us./jp./hipaa.cloud.langfuse.com
OTEL_EXPORTER_OTLP_ENDPOINT="https://cloud.langfuse.com/api/public/otel"
# Локальне розгортання (>= v3.22.0):
# OTEL_EXPORTER_OTLP_ENDPOINT="http://localhost:3000/api/public/otel"

# Basic Auth: base64 від "public-key:secret-key"
#   echo -n "pk-lf-1234567890:sk-lf-1234567890" | base64
OTEL_EXPORTER_OTLP_HEADERS="Authorization=Basic ${AUTH_STRING},x-langfuse-ingestion-version=4"
```

Чотири факти, без яких ця конфігурація не працює так, як очікується:

| Факт | Деталь |
|---|---|
| Тільки OTLP/HTTP | «Langfuse currently supports OTLP over HTTP with both HTTP/JSON and HTTP/protobuf. gRPC is not supported yet» |
| Заголовок версії інгестії | Без `x-langfuse-ingestion-version: 4` «directly ingested OpenTelemetry data can be delayed by up to 10 minutes» |
| Окремий ендпоінт трейсів | Для signal-specific змінних — `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT="…/api/public/otel/v1/traces"` |
| Мапінг атрибутів | «Langfuse maps the received OTel traces to the Langfuse data model and supports additional attributes that are popular in the OTel GenAI ecosystem» |

**Головна пастка прямого OTel — зв'язні атрибути.** Щоб фільтрувати й агрегувати за `userId`,
`sessionId`, `metadata`, `version`, `release`, `tags`, вони мусять бути **на кожному спані трейсу**,
не лише на корені:

| Атрибут Langfuse | Ключ на спані |
|---|---|
| `userId` | `langfuse.user.id` або `user.id` |
| `sessionId` | `langfuse.session.id` або `session.id` |
| `metadata` | `langfuse.trace.metadata.*` (для ключів верхнього рівня) |
| `version` | `langfuse.version` |
| `release` | `langfuse.release` |
| `tags` | `langfuse.trace.tags` |
| `trace_name` | `langfuse.trace.name` |

Рекомендований механізм розповсюдження — **OpenTelemetry Baggage** із `BaggageSpanProcessor`:
атрибути задаються один раз на початку трейсу, а процесор копіює їх у кожен наступний спан. До
цього підходу документація додає попередження: baggage передається через межі сервісів і до
сторонніх API, тому «do not include sensitive information (passwords, API keys, personal data,
etc.) in baggage». Альтернатива для тих, хто вже на SDK Langfuse, — `propagate_attributes()`, який
робить те саме простіше.

**Той самий фільтр, що й у v4.** SDK типово експортує три категорії: спани `langfuse-sdk`, спани з
атрибутами `gen_ai.*` і спани з відомих LLM-scope; якщо ви надсилаєте спани напряму через OTel,
перевірте, що вони проходять цей фільтр.

**Типові помилки**

- Забути заголовок `x-langfuse-ingestion-version: 4` і зробити висновок, що «Langfuse гальмує»:
  дані приходять із затримкою до 10 хвилин.
- Використати gRPC-експортер — він не підтримується, потрібен OTLP/HTTP.
- Поставити `langfuse.user.id` лише на кореневий спан і фільтрувати за користувачем: вибірка буде
  неповною.
- Передавати в baggage токени доступу або персональні дані — вони підуть у HTTP-заголовки до всіх
  downstream-сервісів.
- Одночасно налаштувати SDK Langfuse і власний OTel-експортер в одному процесі без перевірки
  конфліктів: у документації Langfuse для цього є окремий сценарій «Using Langfuse with an Existing
  OpenTelemetry Setup».
- Вважати, що прямий OTel автоматично дасть промпти, датасети й оцінки: це можливості SDK і
  платформи, а не наслідок OTLP-інгестії.

**Альтернативи.**

| Варіант | Що ви пишете | Що отримуєте | Коли брати |
|---|---|---|---|
| Langfuse SDK v4 (Python/JS) | Виклики SDK; атрибути й експорт — на SDK | Трейси, промпти, датасети, оцінки, фільтр спанів | Основний шлях для Python/JS |
| Прямий OTel у Langfuse (`/api/public/otel`) | Код на OTel API своєї мови + атрибути | Трейси в Langfuse без прив'язки до SDK | Go, Java, Rust або вже наявна OTel-інструментація |
| Сторонні OTel-бібліотеки (OpenLLMetry, OpenLIT, Arize, MLflow) + Langfuse як бекенд | Конфігурацію експортера | Покриття фреймворків і моделей із коробки | Потрібне широке покриття без ручної роботи |
| «Сирий» OTel у власний колектор (без Langfuse) | Усе | Повна свобода вибору бекендів, без LLM-специфічних можливостей | Потрібна єдина телеметрія всієї системи, а не лише LLM |

---

**Зведення: як ухвалювати рішення**

| Питання | Що робити |
|---|---|
| З чого почати трейсинг? | SDK Langfuse v4: `get_client()` + контекстний менеджер або `@observe()` |
| Спани не з'являються? | Перевірте `.end()` для ручних спостережень і `flush()` у короткоживучому процесі |
| Трейси «розірвані» після оновлення до v4 | `Langfuse(debug=True)` і потрібні scope в `should_export_span` |
| Фільтри за користувачем не працюють | Зв'язні атрибути мусять бути на кожному спані: `propagate_attributes()` або baggage |
| Назва атрибута вигадана? | Звірте з реєстром регуляркою (23.7) — це 5 рядків коду |
| Токени не сходяться | `cache_read`, `cache_creation`, `reasoning` — підмножини цілих значень |
| Змінити промпт без релізу | Промпт у Langfuse + мітка `production`; типово забирається саме вона |
| Порівняти дві версії застосунку | Датасет + `run_experiment(name=..., task=...)` з фіксацією версії датасету |
| Хмара чи self-hosting? | Хмара — швидкий старт; self-hosting — контроль над даними ціною п'яти сховищ |

**Джерела**

- [Langfuse — Instrumentation (Python SDK v4)](https://langfuse.com/docs/observability/sdk/python/instrumentation) — три способи створення спостережень, `propagate_attributes`, ідентифікатори й `trace_context`, `flush()`/`shutdown()`, обмеження атрибутів
- [Langfuse — Python v3 → v4](https://langfuse.com/docs/observability/sdk/upgrade-path/python-v3-to-v4) — observations-first модель, типовий фільтр спанів і `should_export_span`, розпад `update_current_trace`, перейменування API, чекліст міграції
- [Langfuse — Prompt Management: Get Started](https://langfuse.com/docs/prompt-management/get-started) — `create_prompt`, `get_prompt`, `compile`, `get_langchain_prompt`, версії й мітки, кешування промптів
- [Langfuse — Datasets](https://langfuse.com/docs/evaluation/dataset-runs/datasets) — `create_dataset`, `create_dataset_item`, `run_experiment`, версії за часом, схеми, папки, медіа
- [Langfuse — Scores via API/SDK](https://langfuse.com/docs/evaluation/evaluation-methods/scores-via-sdk) — чотири типи оцінок, три способи виставлення, `score_id`, score configs, оцінки сесій, браузерний SDK
- [Langfuse — Self-hosting](https://langfuse.com/self-hosting) — варіанти розгортання, архітектура, оптимізації інгестії, масштаб
- [Langfuse — Docker Compose](https://langfuse.com/self-hosting/docker-compose) — локальний запуск, вимоги до VM, відсутність облікового запису за замовчуванням
- [Langfuse — Pricing](https://langfuse.com/pricing) — плани, ціни, ліміти інгестії й API, регіони, склад можливостей
- [Langfuse — OpenTelemetry for LLM Observability](https://langfuse.com/docs/opentelemetry/get-started) — OTLP-ендпоінт, авторизація, заголовок інгестії, розповсюдження зв'язних атрибутів, сумісні бібліотеки
- [OpenTelemetry — GenAI attributes registry](https://opentelemetry.io/docs/specs/semconv/registry/attributes/gen-ai/) — назви атрибутів `gen_ai.*`, застарілі ключі, усталені значення (знімок: `research/10/otel_attrs.txt`)
- [OpenTelemetry GenAI semantic conventions (актуальний репозиторій)](https://github.com/open-telemetry/semantic-conventions-genai) — спани, події, метрики, спани агентів (знімки: `research/10/otel_spans_x.txt`, `otel_events_x.txt`, `otel_metrics_x.txt`, `otel_token-metrics_x.txt`, `otel_agent-spans_x.txt`)
- Сторінки `opentelemetry.io` про GenAI, які вже не містять специфікації (переїхали): `research/10/otel_spans.txt`, `research/10/otel_events.txt`, `research/10/otel_metrics.txt`, `research/10/otel_agent.txt`
- Робочий код і фактичні виводи цього розділу: `notebooks/23-observability.ipynb` (`tools/notebooks/nb_23.py`)
