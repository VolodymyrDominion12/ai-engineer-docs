"""Ноутбук 23 — «Observability LLM: Langfuse і OpenTelemetry GenAI».

Розділ довідника: sections/23-observability.md
Локальна частина (OTel-сумісний перехоплювач, семантичні конвенції, метрики)
працює без ключів і без мережі. Клітинки з реальним Langfuse SDK захищені
try/except ImportError + перевіркою ключів.
"""

from nbkit import SETUP_CELL, VERSION_CELL, code, md

FILENAME = "23-observability.ipynb"
TITLE = "23. Observability LLM"

CELLS = [
    md(
        """
# 23. Observability LLM: Langfuse і OpenTelemetry GenAI

**Розділ довідника:** [`sections/23-observability.md`](../sections/23-observability.md)

**Потрібно: LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY (необов'язково — є локальний режим).**

Локальна частина ноутбука (клітинки 23.1–23.5 і самоперевірка) виконується
на стандартній бібліотеці Python: без ключів, без мережі, без `langfuse`,
без `opentelemetry-sdk`. Вона будує **справжні за формою** OTel-структури
(`traceId`, `spanId`, `parentSpanId`, атрибути `gen_ai.*`, події, метрики)
і друкує їх у консоль власним перехоплювачем.

Клітинки 23.6–23.8 викликають реальний `langfuse` SDK. Якщо пакета немає або
ключів немає — клітинка це повідомляє й не ламає ноутбук.

**Що ви зробите:**

1. Побачите, чому без трейсу не сходяться ні гроші, ні затримки.
2. Реалізуєте мінімальний перехоплювач спанів (OTel-сумісний за формою).
3. Побудуєте дерево трейсу LLM-виклику з реальними атрибутами `gen_ai.*`.
4. Додасте події (`gen_ai.client.inference.operation.details`,
   `gen_ai.evaluation.result`) і порахуєте метрики зі зібраних спанів.
5. Перевірите кожну назву атрибута за реєстром семантичних конвенцій
   у `research/10/otel_attrs.txt` — асертом, а не на око.
6. Побачите, як той самий трейс будується через справжній Langfuse SDK v4.
"""
    ),
    md("## Налаштування"),
    code(SETUP_CELL),
    code(VERSION_CELL),
    md(
        """
Додатково перевіримо стек саме цього розділу. Обидві бібліотеки — опційні:
для локального режиму ноутбука достатньо стандартної бібліотеки.
"""
    ),
    code(
        """
# Версії стеку спостережуваності. У requirements.txt довідника зафіксовано
# langfuse==4.15.6 і opentelemetry-sdk==1.45.0 — перевіримо, що встановлено.
import importlib

for _name in ("langfuse", "opentelemetry.sdk", "opentelemetry"):
    try:
        _mod = importlib.import_module(_name)
        _ver = getattr(_mod, "__version__", None)
        if _ver is None and "." in _name:
            _ver = getattr(_mod, "version", {}).get("__version__") if hasattr(_mod, "version") else None
        print(f"{_name:20} {_ver or '?'}")
    except ImportError:
        print(f"{_name:20} НЕ ВСТАНОВЛЕНО (у локальному режимі не потрібно)")
"""
    ),

    # ── 23.1 навіщо трейсити ─────────────────────────────────────────────
    md(
        """
## 23.1 Навіщо трейсити LLM-застосунок

Звичайний лог відповідає на питання «що сталося». Для LLM-застосунку цього
мало: один запит користувача — це кілька LLM-викликів, пошук у векторній базі,
виклики інструментів і, можливо, ще один сервіс. Платити й гальмувати може
будь-який із них.

Порахуємо, чим відрізняється агрегація «по рядках логу» від агрегації
«по дереву операцій». Нижче — кілька записів про витрати так, як вони
зазвичай і потрапляють у лог: пласко, без батьків.
"""
    ),
    code(
        '''
# Сирі записи про витрати токенів — так, як їх дає провайдер у полі usage.
# Кожен запис самотній: невідомо, до якого запиту користувача він належить.
RAW_USAGE = [
    {"call": "summarize",  "input_tokens": 1840, "output_tokens": 220, "duration_ms": 1180},
    {"call": "summarize",  "input_tokens": 1910, "output_tokens": 195, "duration_ms": 1090},
    {"call": "embed",      "input_tokens": 640,  "output_tokens": 0,   "duration_ms": 130},
    {"call": "chat",       "input_tokens": 412,  "output_tokens": 310, "duration_ms": 2450},
    {"call": "chat",       "input_tokens": 2680, "output_tokens": 155, "duration_ms": 3020},
    {"call": "tool:search","input_tokens": 0,    "output_tokens": 0,   "duration_ms": 870},
]

total_in = sum(r["input_tokens"] for r in RAW_USAGE)
total_out = sum(r["output_tokens"] for r in RAW_USAGE)
print(f"Усього вхідних токенів : {total_in}")
print(f"Усього вихідних токенів: {total_out}")
print()
print("А тепер те, що потрібно знати в продакшні:")
for question in (
    "скільки викликів було в одному запиті користувача?",
    "на якому кроці запит гальмує?",
    "котрий виклик дав помилку після трьох ретраїв?",
    "яка версія промпту дала цю відповідь?",
):
    print(f"  {question:55} -> з плаского логу НЕ ВИДНО")
'''
    ),
    md(
        """
Плаский лог дає суму. Він не дає **структури**: батьківства, тривалості,
зв'язку з користувачем і сесією, прив'язки промпту до версії. Саме цю
структуру й додає трейсинг (tracing).

Три речі, які дає трейс і не дає лог:

| Питання | Що потрібно | Що дає трейс |
|---|---|---|
| Де саме втрачено час | Тривалість кожної операції окремо | Спан із `startTime`/`endTime` на кожен крок |
| Скільки коштував один запит користувача | Підсумок по дереву, а не по рядках | Спани з `gen_ai.usage.*`, згруповані за `traceId` |
| Чому відповідь змінилася | Версія промпту й параметри запиту | Атрибути `gen_ai.prompt.name`, `gen_ai.request.*` на спані |

Ідентифікатори в Langfuse стандартизовані за W3C Trace Context: `trace_id` —
32 символи шістнадцяткового рядка (16 байтів), `observation_id` — 16 символів
(8 байтів). Це той самий формат, який використовує OpenTelemetry, тому трейси
з різних сервісів зшиваються без перетворень.
"""
    ),

    # ── 23.2 перехоплювач ────────────────────────────────────────────────
    md(
        """
## 23.2 Мінімальний OTel-сумісний перехоплювач спанів

Щоб не сприймати трейсинг як магію, побудуємо його руками. Спан (span) —
це запис про одну операцію: ідентифікатори, час, атрибути, події, статус.

Навчальний перехоплювач нижче повторює **форму** OTLP-структур
(`traceId`, `spanId`, `parentSpanId`, `attributes`, `events`, `status`),
але не реалізує інтерфейс `opentelemetry-sdk`: у справжньому конвеєрі спани
збирає SDK, а відправляє їх OTLP-експортер (у довіднику зафіксовано
`opentelemetry-sdk==1.45.0`).
"""
    ),
    code(
        '''
# ── Ідентифікатори за W3C Trace Context ──────────────────────────────────
# trace_id — 32 hex-символи (16 байтів), span_id — 16 hex-символів (8 байтів).
# Такі самі довжини використовує Langfuse.
import contextvars
import hashlib
import secrets
import time
from contextlib import contextmanager
from dataclasses import dataclass, field


def new_trace_id() -> str:
    return secrets.token_hex(16)          # 16 байтів -> 32 hex


def new_span_id() -> str:
    return secrets.token_hex(8)           # 8 байтів  -> 16 hex


def deterministic_trace_id(seed: str) -> str:
    """Детермінований trace_id із зовнішнього ідентифікатора.

    Потрібен, коли вже є свій request_id і треба зшити його з трейсом.
    Langfuse має для цього create_trace_id(seed=...) — див. 23.6.
    """
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()[:32]


print("trace_id :", new_trace_id())
print("span_id  :", new_span_id())
print("з seed   :", deterministic_trace_id("req_12345"))
print("з seed   :", deterministic_trace_id("req_12345"), "<- той самий")
'''
    ),
    md(
        """
Тепер — самі структури. Спан у формі словника, який пішов би в OTLP.
Тип спану зберігаємо рядком (`CLIENT`, `INTERNAL`), як його називають
семантичні конвенції; у протоколі це числовий enum, але для навчального
перехоплювача рядок читабельніший.
"""
    ),
    code(
        '''
_INSTRUMENTATION_SCOPE = "dovidnyk.observability"


@dataclass
class Span:
    """Одна операція в трейсі."""

    name: str
    kind: str                                    # "CLIENT" | "INTERNAL"
    trace_id: str
    span_id: str
    parent_span_id: str | None
    start_ns: int
    end_ns: int | None = None
    attributes: dict = field(default_factory=dict)
    events: list = field(default_factory=list)
    status: dict = field(default_factory=lambda: {"code": "UNSET"})
    instrumentation_scope: str = _INSTRUMENTATION_SCOPE
    clock: "Callable[[], int]" = time.time_ns    # джерело часу (можна підмінити)

    # ── зміна стану ──────────────────────────────────────────────────────
    def set_attribute(self, key: str, value) -> None:
        self.attributes[key] = value

    def add_event(self, name: str, attributes: dict | None = None) -> None:
        self.events.append({
            "name": name,
            "timeUnixNano": self.clock(),
            "attributes": dict(attributes or {}),
        })

    def end(self) -> None:
        if self.end_ns is None:
            self.end_ns = self.clock()

    @property
    def duration_ms(self) -> float:
        end = self.end_ns if self.end_ns is not None else time.time_ns()
        return (end - self.start_ns) / 1e6

    def as_dict(self) -> dict:
        return {
            "traceId": self.trace_id,
            "spanId": self.span_id,
            "parentSpanId": self.parent_span_id,
            "name": self.name,
            "kind": self.kind,
            "startTimeUnixNano": self.start_ns,
            "endTimeUnixNano": self.end_ns,
            "attributes": self.attributes,
            "events": self.events,
            "status": self.status,
            "instrumentationScope": {"name": self.instrumentation_scope},
        }


print("Клас Span готовий. Приклад форми:")
demo = Span(name="chat gpt-4", kind="CLIENT", trace_id="0" * 32, span_id="1" * 16,
            parent_span_id=None, start_ns=time.time_ns())
demo.set_attribute("gen_ai.operation.name", "chat")
demo.end()
print(demo.as_dict()["name"], "|", demo.as_dict()["kind"], "|", demo.as_dict()["attributes"])
'''
    ),
    md(
        """
### Перехоплювач і контекст

Ключова механіка батьківства — **не** ручне передання `parent`. Активний спан
зберігається в контексті виконання (`contextvars`), і кожен новий спан
автоматично стає дитиною того, хто активний зараз. Саме так працює
розповсюдження контексту в OpenTelemetry — і саме тому в Langfuse вкладеність
спанів «просто працює».

Перехоплювач (exporter) приймає готовий спан і **друкує** його в консоль.
У продакшні цю роль виконує OTLP-експортер, який відправляє ті самі
структури на `/api/public/otel` (див. 23.8).
"""
    ),
    code(
        '''
_CURRENT_SPAN: contextvars.ContextVar[Span | None] = contextvars.ContextVar(
    "current_span", default=None
)


class ConsoleSpanExporter:
    """Перехоплювач: приймає спани й друкує їх. У продакшні — OTLP-експортер."""

    def __init__(self, *, verbose: bool = True) -> None:
        self.received: list[Span] = []
        self.verbose = verbose

    def export(self, spans: list[Span]) -> None:
        for span in spans:
            self.received.append(span)
            if self.verbose:
                print(self.format(span))

    @staticmethod
    def format(span: Span) -> str:
        parent = span.parent_span_id[:8] if span.parent_span_id else "—"
        return (f"  span {span.name!r:34} kind={span.kind:8} "
                f"span={span.span_id[:8]} parent={parent:8} "
                f"{span.duration_ms:7.2f} ms  attrs={len(span.attributes)} "
                f"events={len(span.events)}")

    def spans_of(self, trace_id: str) -> list[Span]:
        return [s for s in self.received if s.trace_id == trace_id]

    def shutdown(self) -> None:
        """Нічого не робимо: у справжньому конвеєрі тут скидаються буфери."""
        return None


class Tracer:
    """Мінімальний трасувальник: створює спани й тримає контекст."""

    def __init__(self, exporter: ConsoleSpanExporter, clock=time.time_ns) -> None:
        self.exporter = exporter
        self.clock = clock

    @contextmanager
    def start_span(self, name, *, kind="INTERNAL", attributes=None,
                   trace_id=None, parent=None):
        parent_span = parent if parent is not None else _CURRENT_SPAN.get()
        if trace_id is None:
            trace_id = parent_span.trace_id if parent_span else new_trace_id()

        span = Span(
            name=name,
            kind=kind,
            trace_id=trace_id,
            span_id=new_span_id(),
            parent_span_id=parent_span.span_id if parent_span else None,
            start_ns=self.clock(),
            attributes=dict(attributes or {}),
            clock=self.clock,
        )
        token = _CURRENT_SPAN.set(span)
        try:
            yield span
        except Exception as exc:                       # помилки теж частина трейсу
            span.set_attribute("error.type", type(exc).__name__)
            span.status = {"code": "ERROR", "message": str(exc)}
            raise
        finally:
            span.end()
            _CURRENT_SPAN.reset(token)
            self.exporter.export([span])


exporter = ConsoleSpanExporter(verbose=False)
tracer = Tracer(exporter)

# Демонстрація вкладеності: дитина не отримує parent вручну.
with tracer.start_span("root", kind="INTERNAL") as root:
    with tracer.start_span("child-a", kind="CLIENT"):
        pass
    with tracer.start_span("child-b", kind="CLIENT"):
        pass

for s in exporter.received:
    parent = s.parent_span_id[:8] if s.parent_span_id else "—"
    print(f"{s.name:9} span={s.span_id[:8]} parent={parent}")
print()
print("trace_id один на всіх:", {s.trace_id for s in exporter.received})
'''
    ),

    # ── 23.3 атрибути ───────────────────────────────────────────────────
    md(
        """
## 23.3 Семантичні конвенції: атрибути `gen_ai.*`

Атрибут — це пара «ключ → значення» на спані. Щоб трейси різних бібліотек
були сумісні, OpenTelemetry стандартизує ключі: `gen_ai.*`. Правило просте:
**назви ключів беруть із реєстру, а не з голови.** Нижче всі ключі взяті
з `research/10/otel_attrs.txt` (знімок реєстру семантичних конвенцій).

Побудуємо повний трейс одного запиту: агент → пошук у базі → виклик моделі →
виклик інструмента. Модель у прикладі — `gpt-4`: це значення з прикладів
семантичних конвенцій, а не порада, яку модель брати.
"""
    ),
    code(
        '''
# ── Демонстраційний сценарій ─────────────────────────────────────────────
MODEL_ID = "gpt-4"                 # у своєму коді підставте РЕАЛЬНУ назву моделі
AGENT_NAME = "support-bot"
CONVERSATION_ID = "conv_5j66UpCpwteGg4YSxUnt7lPY"   # приклад із конвенцій
DATA_SOURCE_ID = "H7STPQYOND"                        # приклад із конвенцій

exporter = ConsoleSpanExporter(verbose=False)
tracer = Tracer(exporter)

with tracer.start_span(
    f"invoke_agent {AGENT_NAME}",
    kind="CLIENT",
    attributes={
        "gen_ai.operation.name": "invoke_agent",
        "gen_ai.provider.name": "openai",
        "gen_ai.agent.name": AGENT_NAME,
        "gen_ai.agent.id": "asst_5j66UpCpwteGg4YSxUnt7lPY",
        "gen_ai.agent.description": "Відповідає на питання про доставку",
        "gen_ai.conversation.id": CONVERSATION_ID,
        "gen_ai.request.model": MODEL_ID,
    },
) as agent_span:

    # 1) Пошук у векторній базі — окремий спан, окрема затримка
    with tracer.start_span(
        f"retrieval {DATA_SOURCE_ID}",
        kind="CLIENT",
        attributes={
            "gen_ai.operation.name": "retrieval",
            "gen_ai.data_source.id": DATA_SOURCE_ID,
            "gen_ai.request.model": MODEL_ID,
        },
    ) as retrieval_span:
        time.sleep(0.01)
        retrieval_span.set_attribute("gen_ai.retrieval.query.text", "коли прибуде посилка")
        retrieval_span.set_attribute("gen_ai.retrieval.documents", [
            {"id": "doc_123", "score": 0.95},
            {"id": "doc_456", "score": 0.87},
        ])

    # 2) Виклик моделі — головний спан, за яким рахують гроші
    with tracer.start_span(
        f"chat {MODEL_ID}",
        kind="CLIENT",
        attributes={
            # Required
            "gen_ai.operation.name": "chat",
            "gen_ai.provider.name": "openai",
            # Conditionally Required / Recommended
            "gen_ai.request.model": MODEL_ID,
            "gen_ai.response.model": "gpt-4-0613",
            "gen_ai.response.id": "chatcmpl-123",
            "gen_ai.request.temperature": 0.0,
            "gen_ai.request.max_tokens": 100,
            "gen_ai.request.top_p": 1.0,
            "gen_ai.request.stream": True,
            "gen_ai.output.type": "text",
            "gen_ai.response.finish_reasons": ["stop"],
            "gen_ai.response.time_to_first_chunk": 0.5,
            # Облік токенів: input_tokens ВКЛЮЧАЄ кешовані
            "gen_ai.usage.input_tokens": 300,
            "gen_ai.usage.cache_read.input_tokens": 40,
            "gen_ai.usage.output_tokens": 180,
            "gen_ai.usage.reasoning.output_tokens": 50,
            # Зв'язок із зовнішнім світом
            "server.address": "example.com",
            "server.port": 443,
        },
    ) as chat_span:
        time.sleep(0.03)
        chat_span.set_attribute("gen_ai.prompt.name", "analyze-code")

        # 3) Виклик інструмента — теж спан, і теж окрема затримка
        with tracer.start_span(
            "execute_tool track_shipment",
            kind="INTERNAL",
            attributes={
                "gen_ai.operation.name": "execute_tool",
                "gen_ai.tool.name": "track_shipment",
                "gen_ai.tool.type": "function",
                "gen_ai.tool.description": "Повертає статус посилки за номером",
                "gen_ai.tool.call.id": "call_mszuSIzqtI65i1wAUOE8w5H4",
                "gen_ai.tool.call.arguments": {"tracking_number": "NP-000123"},
            },
        ) as tool_span:
            time.sleep(0.005)
            tool_span.set_attribute("gen_ai.tool.call.result",
                                    {"status": "in_transit", "eta_days": 2})

print(f"Спанів у трейсі: {len(exporter.received)}")
print(f"trace_id       : {exporter.received[0].trace_id}")
print()
for s in exporter.received:
    parent = s.parent_span_id[:8] if s.parent_span_id else "—"
    print(f"{s.name:28} span={s.span_id[:8]} parent={parent} "
          f"{s.duration_ms:6.2f} ms  attrs={len(s.attributes)}")
'''
    ),
    md(
        """
Зверніть увагу на дві речі у виводі.

**Перша: дерево будується саме собою.** `execute_tool` — дитина `chat`,
`chat` і `retrieval` — діти `invoke_agent`. Жодного ручного `parent` у коді
не було: батьківство взялося з контексту.

**Друга: облік токенів не адитивний «на око».** За семантичними конвенціями
`gen_ai.usage.cache_read.input_tokens` **входить** у `gen_ai.usage.input_tokens`.
Тому сумувати їх не можна — інакше кешовані токени порахуються двічі.

Правило підмножин із конвенцій виглядає так (приклад із документації):

| Ключ | Значення | Як рахувати |
|---|---|---|
| `gen_ai.usage.input_tokens` | 300 | Усього вхідних, **разом із** кешованими |
| `gen_ai.usage.cache_read.input_tokens` | 40 | Підмножина `input_tokens` |
| `gen_ai.usage.output_tokens` | 180 | Усього вихідних, разом із reasoning |
| `gen_ai.usage.reasoning.output_tokens` | 50 | Підмножина `output_tokens` |

Перевіримо це асертом, а не на слово:
"""
    ),
    code(
        '''
def cache_share(span: Span) -> float:
    """Частка кешованих вхідних токенів. Сумувати підмножини не можна."""
    total = span.attributes.get("gen_ai.usage.input_tokens", 0)
    cached = span.attributes.get("gen_ai.usage.cache_read.input_tokens", 0)
    return cached / total if total else 0.0


chat = next(s for s in exporter.received if s.name.startswith("chat "))

total_in = chat.attributes["gen_ai.usage.input_tokens"]
cached_in = chat.attributes["gen_ai.usage.cache_read.input_tokens"]
total_out = chat.attributes["gen_ai.usage.output_tokens"]
reasoning_out = chat.attributes["gen_ai.usage.reasoning.output_tokens"]

assert cached_in <= total_in, "кешовані токени — ПІДмножина вхідних"
assert reasoning_out <= total_out, "reasoning-токени — ПІДмножина вихідних"

print(f"вхідних {total_in}, з них із кешу {cached_in} ({cache_share(chat):.0%})")
print(f"вихідних {total_out}, з них reasoning {reasoning_out}")
print()
print("НЕ можна: total_in + cached_in =", total_in + cached_in, "<- подвійний облік")
print("Можна:   total_in            =", total_in)
'''
    ),
    md(
        """
### Ключі, які вже застаріли

Реєстр не лише додає ключі — він їх і відкидає. У знімку реєстру
(`research/10/otel_attrs.txt`) є окремий розділ застарілих:

| Старий ключ | Заміна |
|---|---|
| `gen_ai.system` | `gen_ai.provider.name` |
| `gen_ai.usage.prompt_tokens` | `gen_ai.usage.input_tokens` |
| `gen_ai.usage.completion_tokens` | `gen_ai.usage.output_tokens` |
| `gen_ai.prompt` | Видалено без заміни: вміст промпту — через Event API |
| `gen_ai.completion` | Видалено без заміни: вміст відповіді — через Event API |
| `gen_ai.openai.request.seed` | `gen_ai.request.seed` |
| `gen_ai.openai.request.response_format` | `gen_ai.output.type` |

**Чому це дорого ігнорувати:** дашборд, побудований на `gen_ai.system`
і `gen_ai.usage.prompt_tokens`, після оновлення інструментації просто
покаже нулі. Помилки не буде — буде тиха відсутність даних.
"""
    ),

    # ── 23.4 події ───────────────────────────────────────────────────────
    md(
        """
## 23.4 Події (events): вміст окремо від спану

Вміст промпту й відповіді — це те, що може містити персональні дані
й займає багато місця. Семантичні конвенції виносять його в **події**
з рівнем Opt-In: спани лишаються легкими, а важкий вміст збирається тільки
тоді, коли ви це свідомо увімкнули.

Подія — це іменований запис із міткою часу й власним набором атрибутів,
прикріплений до спану. Нижче — дві події з конвенцій:
`gen_ai.client.inference.operation.details` (деталі запиту) і
`gen_ai.evaluation.result` (результат оцінювання).
"""
    ),
    code(
        '''
exporter = ConsoleSpanExporter(verbose=False)
tracer = Tracer(exporter)

with tracer.start_span(f"chat {MODEL_ID}", kind="CLIENT",
                       attributes={"gen_ai.operation.name": "chat",
                                   "gen_ai.provider.name": "openai"}) as chat_span:

    # Подія 1: вміст запиту. Рівень Opt-In — умикається свідомо.
    chat_span.add_event("gen_ai.client.inference.operation.details", {
        "gen_ai.operation.name": "chat",
        "gen_ai.provider.name": "openai",
        "gen_ai.request.model": MODEL_ID,
        "gen_ai.system_instructions": [
            {"type": "text", "content": "Ти — агент, що відповідає українською."}
        ],
        "gen_ai.input.messages": [
            {"role": "user", "parts": [{"type": "text", "content": "Де моя посилка?"}]}
        ],
        "gen_ai.output.messages": [
            {"role": "assistant",
             "parts": [{"type": "text", "content": "Посилка в дорозі, 2 дні."}],
             "finish_reason": "stop"}
        ],
        "gen_ai.tool.definitions": [
            {"type": "function", "name": "track_shipment",
             "description": "Повертає статус посилки"}
        ],
    })

    # Подія 2: результат оцінювання. Прикріплюється до спану, який оцінюють.
    chat_span.add_event("gen_ai.evaluation.result", {
        "gen_ai.evaluation.name": "Relevance",
        "gen_ai.evaluation.score.value": 4.0,
        "gen_ai.evaluation.score.label": "relevant",
        "gen_ai.evaluation.explanation": "Відповідь по суті, але без номера посилки.",
    })

    chat_span.set_attribute("gen_ai.usage.input_tokens", 120)
    chat_span.set_attribute("gen_ai.usage.output_tokens", 60)

for s in exporter.received:
    print(f"спан {s.name!r}: атрибутів {len(s.attributes)}, подій {len(s.events)}")
    for e in s.events:
        print(f"  подія {e['name']!r}")
        for k in e["attributes"]:
            print(f"      {k}")
    print()
print("Зверніть увагу: вміст живе в ПОДІЯХ, а не в атрибутах спану.")
'''
    ),
    md(
        """
Навіщо таке розділення — три причини, і всі практичні:

1. **Приватність.** Атрибути спану потрапляють у будь-який бекенд за
   замовчуванням, а події з рівнем Opt-In збирають окремо. Конвенції прямо
   попереджають: `gen_ai.input.messages`, `gen_ai.output.messages`,
   `gen_ai.system_instructions`, `gen_ai.tool.call.arguments`,
   `gen_ai.tool.call.result`, `gen_ai.retrieval.query.text` —
   «likely to contain sensitive information including user/PII data».
2. **Обсяг.** Історія чату на 20 ходів у атрибуті спану — це мегабайти
   телеметрії на кожен запит.
3. **Сумісність.** Коли вміст у структурованому вигляді, його можна
   відфільтрувати або обрізати, не ламаючи решту спану.

Конвенції дозволяють записувати структуровані атрибути на спані як
JSON-рядок, **якщо** структура не підтримується, і вимагають структурованої
форми на подіях.
"""
    ),

    # ── 23.5 метрики ─────────────────────────────────────────────────────
    md(
        """
## 23.5 Метрики: агрегати з тих самих даних

Спан відповідає на питання «що сталося з цим конкретним запитом». Метрика
відповідає на питання «що відбувається з системою». Метрики GenAI
визначаються окремо від спанів, але будуються з тих самих подій.

Зі знімка конвенцій — клієнтські метрики інференсу:

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

Для `gen_ai.client.operation.duration` конвенції задають явні межі гістограми:
`[0.01, 0.02, 0.04, 0.08, 0.16, 0.32, 0.64, 1.28, 2.56, 5.12, 10.24, 20.48,
40.96, 81.92]` секунд. Це не деталь: без заданих меж перцентилі різних
застосунків неможливо порівнювати.

Порахуємо метрики зі спанів, які вже зібрав наш перехоплювач.
"""
    ),
    code(
        '''
# ── Генеруємо кілька запитів з різною затримкою ──────────────────────────
import random

random.seed(23)                                  # відтворюваність виводу

exporter = ConsoleSpanExporter(verbose=False)
tracer = Tracer(exporter)

for i in range(12):
    with tracer.start_span(f"chat {MODEL_ID}", kind="CLIENT",
                           attributes={
                               "gen_ai.operation.name": "chat",
                               "gen_ai.provider.name": "openai",
                               "gen_ai.request.model": MODEL_ID,
                           }) as span:
        time.sleep(random.uniform(0.001, 0.05))
        span.set_attribute("gen_ai.usage.input_tokens", 400 + i * 30)
        span.set_attribute("gen_ai.usage.cache_read.input_tokens", 100)
        span.set_attribute("gen_ai.usage.output_tokens", 150 + i)
        span.set_attribute("gen_ai.response.time_to_first_chunk", 0.2 + i * 0.01)

# ── Рахуємо агрегати ─────────────────────────────────────────────────────
BUCKETS_S = [0.01, 0.02, 0.04, 0.08, 0.16, 0.32, 0.64, 1.28, 2.56, 5.12,
             10.24, 20.48, 40.96, 81.92]

spans = exporter.received
durations = [s.duration_ms / 1000 for s in spans]


def histogram(values: list[float], bounds: list[float]) -> list[tuple[str, int]]:
    """Гістограмма з накопичувальними межами — як це робить OTel."""
    out = []
    for b in bounds:
        out.append((f"<= {b:g}s", sum(1 for v in values if v <= b)))
    out.append(("+Inf", len(values)))
    return out


print("Counter gen_ai.client.inference.usage.input_tokens =",
      sum(s.attributes["gen_ai.usage.input_tokens"] for s in spans))
print("Counter gen_ai.client.inference.usage.output_tokens =",
      sum(s.attributes["gen_ai.usage.output_tokens"] for s in spans))
print("Counter ...usage.cache_read.input_tokens            =",
      sum(s.attributes["gen_ai.usage.cache_read.input_tokens"] for s in spans))
print()
print("Histogram gen_ai.client.operation.duration (накопичувальні бакети):")
for label, count in histogram(durations, BUCKETS_S):
    if count:
        print(f"  {label:12} {count:3}")
print()
ttfc = [s.attributes["gen_ai.response.time_to_first_chunk"] for s in spans]
print(f"gen_ai.client.operation.time_to_first_chunk: n={len(ttfc)} "
      f"avg={sum(ttfc)/len(ttfc):.3f}s max={max(ttfc):.2f}s")
'''
    ),
    md(
        """
**Три пастки метрик, які видно в цьому коді:**

1. **Counter не можна будувати на підмножинах.** `cache_read` входить
   у `input_tokens`, тому сума counter-ів не дорівнює жодній реальній
   величині — це навмисно різні зрізи.
2. **Гістограма без заданих меж марна.** Конвенції фіксують межі для
   `duration` і `time_to_first_chunk`; власні довільні межі зламають
   порівняння з чужими дашбордами.
3. **Метрики не мають `gen_ai.input.messages`.** Вміст у метрики не
   потрапляє взагалі — за це відповідають спани й події.

Окремо: `gen_ai.client.operation.time_to_first_chunk` має сенс лише для
стримінгу. Для не-стримінгових запитів атрибут
`gen_ai.response.time_to_first_chunk` конвенції рекомендують заповнювати
лише тоді, коли запит був стримінговим.
"""
    ),

    # ── 23.6 Langfuse SDK ────────────────────────────────────────────────
    md(
        """
## 23.6 Langfuse SDK v4: декоратори, контекст, зв'язні атрибути

Далі — реальний SDK. Усі виклики в клітинках нижче — з офіційної
документації Langfuse; єдине, чого бракує без ключів, — власне відправлення
даних. Клітинки самі перевіряють наявність пакета й ключів.

Порядок роботи з v4 такий:

1. Клієнт береться через `get_client()` — з `.env` або зі змінних оточення.
2. Спостереження (observation) створюються трьома способами: контекстний
   менеджер, декоратор `observe`, ручний `start_observation`.
3. Зв'язні атрибути (`user_id`, `session_id`, `metadata`, `version`, `tags`)
   задаються через `propagate_attributes` — і розповсюджуються на всі
   дочірні спостереження.
"""
    ),
    code(
        '''
# ПОТРЕБУЄ: pip install langfuse  +  LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY у .env
import os

try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except ImportError:
    pass

HAS_KEYS = bool(os.environ.get("LANGFUSE_PUBLIC_KEY") and os.environ.get("LANGFUSE_SECRET_KEY"))
print("LANGFUSE_PUBLIC_KEY:", "є" if os.environ.get("LANGFUSE_PUBLIC_KEY") else "немає")
print("LANGFUSE_SECRET_KEY:", "є" if os.environ.get("LANGFUSE_SECRET_KEY") else "немає")
print()
print("Локальний режим ноутбука працює й без ключів: усе до цієї клітинки")
print("виконувалося на стандартній бібліотеці.")
'''
    ),
    code(
        '''
# ПОТРЕБУЄ: пакет langfuse і ключі. Без них — клітинка лише показує код.
# Джерело: https://langfuse.com/docs/observability/sdk/python/instrumentation
if not HAS_KEYS:
    print("Ключів немає — клітинку пропущено. Нижче той самий код для довідки.\\n")
    print("""from langfuse import get_client, observe, propagate_attributes

langfuse = get_client()

@observe()
def my_data_processing_function(data, parameter):
    return {"processed_data": data, "status": "ok"}

@observe(name="llm-call", as_type="generation")
async def my_async_llm_call(prompt_text):
    return "LLM response"

with langfuse.start_as_current_observation(
    as_type="span", name="user-request-pipeline", input={"user_query": "..."}
) as root_span:
    with propagate_attributes(user_id="user_123", session_id="session_abc"):
        with langfuse.start_as_current_observation(
            as_type="generation", name="joke-generation", model="gpt-4o"
        ) as generation:
            generation.update(output="...")
    root_span.update(output={"final_joke": "..."})

langfuse.flush()""")
else:
    try:
        from langfuse import get_client, observe, propagate_attributes

        langfuse = get_client()

        @observe(name="local-echo")
        def local_llm_call(question: str) -> str:
            """Заглушка замість реальної моделі: ключі LLM тут не потрібні."""
            return f"Локальна відповідь на: {question}"

        with langfuse.start_as_current_observation(
            as_type="span", name="user-request-pipeline",
            input={"user_query": "Де моя посилка?"},
        ) as root_span:
            with propagate_attributes(user_id="user_123", session_id="session_abc",
                                      metadata={"pipeline": "main"}):
                with langfuse.start_as_current_observation(
                    as_type="generation", name="llm-call", model="gpt-4o"
                ) as generation:
                    generation.update(output=local_llm_call("Де моя посилка?"),
                                      usage_details={"input_tokens": 12,
                                                     "output_tokens": 8})
            root_span.update(output={"answer": "..."})

        print("trace_id       :", langfuse.get_current_trace_id())
        print("observation_id :", langfuse.get_current_observation_id())
        langfuse.flush()
        print("Відправлено. flush() обов'язковий у короткоживучих процесах.")
    except ImportError:
        print("langfuse не встановлено — клітинку пропущено.")
        print("Встановіть:  pip install langfuse")
    except Exception as exc:
        print(f"Помилка ({type(exc).__name__}): {exc}")
'''
    ),
    md(
        """
### Детерміновані trace_id і зв'язок із зовнішніми системами

Якщо у вас уже є власний `request_id`, трейс можна зробити **детермінованим**:
той самий seed дає той самий `trace_id`. Це той самий прийом, який ми
реалізували через `hashlib` у 23.2, тільки з коробки.

Окремо — приєднання до вже наявного трейсу: параметр `trace_context`
з `trace_id` і `parent_span_id` вставляє спостереження в чуже дерево,
а не створює нове.
"""
    ),
    code(
        '''
# ПОТРЕБУЄ: пакет langfuse і ключі.
if not HAS_KEYS:
    print("Ключів немає — клітинку пропущено.\\n")
    print("""from langfuse import get_client

langfuse = get_client()

# 1) Детермінований trace_id із зовнішнього ідентифікатора
external_request_id = "req_12345"
deterministic_trace_id = langfuse.create_trace_id(seed=external_request_id)

# 2) Приєднання до вже наявного трейсу (W3C trace context)
existing_trace_id = "abcdef1234567890abcdef1234567890"
existing_parent_span_id = "fedcba0987654321"

with langfuse.start_as_current_observation(
    as_type="span",
    name="process-downstream-task",
    trace_context={"trace_id": existing_trace_id,
                   "parent_span_id": existing_parent_span_id},
):
    pass

# 3) Ручні спостереження: .end() викликаєте ВИ
span = langfuse.start_observation(name="manual-span")
span.update(input="Data for side task")
child = span.start_observation(name="child-span", as_type="generation")
child.end()
span.end()

# 4) Розповсюдження через baggage між сервісами
from langfuse import propagate_attributes
import requests

with langfuse.start_as_current_observation(as_type="span", name="api-request"):
    with propagate_attributes(user_id="user_123", session_id="session_abc",
                              environment="staging", as_baggage=True):
        requests.get("https://service-b.example.com/api")""")
else:
    try:
        from langfuse import get_client

        langfuse = get_client()
        print("create_trace_id(seed='req_12345') ->",
              langfuse.create_trace_id(seed="req_12345"))
        print("той самий seed ->",
              langfuse.create_trace_id(seed="req_12345"))

        span = langfuse.start_observation(name="manual-span")
        span.update(input="Data for side task")
        child = span.start_observation(name="child-span", as_type="generation")
        child.end()
        span.end()          # без цього спостереження не долетить
        langfuse.flush()
        print("Ручні спостереження відправлено (обидва .end() викликано).")
    except ImportError:
        print("langfuse не встановлено — клітинку пропущено.")
    except Exception as exc:
        print(f"Помилка ({type(exc).__name__}): {exc}")
'''
    ),

    # ── 23.7 промпти, датасети, оцінки ───────────────────────────────────
    md(
        """
## 23.7 Промпти, датасети й оцінки через SDK

Промпт у Langfuse — артефакт із назвою, типом (`text` або `chat`),
версіями й мітками (labels). Повторне створення промпту з тією самою назвою
не перезаписує його, а додає **нову версію**. Мітка `production` — те, що
забирає продакшн-код за замовчуванням.

Датасет — це набір входів і очікуваних виходів; експеримент проганяє вашу
функцію по всіх елементах і прикріплює до кожного спостереження оцінку.
"""
    ),
    code(
        '''
# ПОТРЕБУЄ: пакет langfuse і ключі.
if not HAS_KEYS:
    print("Ключів немає — клітинку пропущено.\\n")
    print("""# ── Промпт ──────────────────────────────────────────────────────────────
langfuse.create_prompt(
    name="movie-critic",
    type="text",
    prompt="As a {{criticlevel}} movie critic, do you like {{movie}}?",
    labels=["production"],          # одразу підвищити до production
)
langfuse.create_prompt(
    name="movie-critic-chat",
    type="chat",
    prompt=[
        {"role": "system", "content": "You are an {{criticlevel}} movie critic"},
        {"role": "user", "content": "Do you like {{movie}}?"},
    ],
    labels=["production"],
)

prompt = langfuse.get_prompt("movie-critic")          # типово production
compiled = prompt.compile(criticlevel="expert", movie="Dune 2")

chat_prompt = langfuse.get_prompt("movie-critic-chat", type="chat")
messages = chat_prompt.compile(criticlevel="expert", movie="Dune 2")

# ── Датасет і експеримент ───────────────────────────────────────────────
langfuse.create_dataset(name="qa-dataset", description="Перший датасет")
langfuse.create_dataset_item(
    dataset_name="qa-dataset",
    input={"text": "hello world"},
    expected_output={"text": "hello world"},
)

dataset = langfuse.get_dataset("qa-dataset")

def my_task(*, item, **kwargs):
    return item.expected_output               # тут був би ваш застосунок

result = dataset.run_experiment(
    name="Baseline Experiment v1", description="Прогін на v1", task=my_task
)

# ── Оцінка ──────────────────────────────────────────────────────────────
langfuse.create_score(
    name="correctness",
    value=0.9,
    trace_id="trace_id_here",
    observation_id="observation_id_here",
    data_type="NUMERIC",
    comment="Factually correct",
)

with langfuse.start_as_current_observation(as_type="span", name="my-operation") as span:
    span.score(name="accuracy", value="partially correct", data_type="CATEGORICAL")
    span.score_trace(name="overall_quality", value=0.95, data_type="NUMERIC")

langfuse.flush()""")
else:
    try:
        from langfuse import get_client

        langfuse = get_client()

        langfuse.create_prompt(
            name="dovidnyk-movie-critic",
            type="text",
            prompt="As a {{criticlevel}} movie critic, do you like {{movie}}?",
            labels=["production"],
        )
        prompt = langfuse.get_prompt("dovidnyk-movie-critic")
        print("version:", prompt.version)
        print("compiled:", prompt.compile(criticlevel="expert", movie="Dune 2"))

        langfuse.create_dataset(name="dovidnyk-qa", description="Датасет ноутбука 23")
        langfuse.create_dataset_item(
            dataset_name="dovidnyk-qa",
            input={"text": "hello world"},
            expected_output={"text": "hello world"},
        )
        dataset = langfuse.get_dataset("dovidnyk-qa")
        print("елементів у датасеті:", len(dataset.items))

        langfuse.flush()
        print("Готово: промпт, датасет і (за потреби) оцінки відправлено.")
    except ImportError:
        print("langfuse не встановлено — клітинку пропущено.")
    except Exception as exc:
        print(f"Помилка ({type(exc).__name__}): {exc}")
'''
    ),
    md(
        """
### Обмеження, які видно в документації

| Обмеження | Деталь |
|---|---|
| Тип промпту | Обирається при створенні в UI і **не змінюється** потім |
| Кеш промптів | SDK кешує промпти клієнтськи: після першого завантаження — з пам'яті, зайвої затримки немає |
| Падіння Langfuse | Застосунок продовжує працювати на кешованому промпті — промпт-менеджмент не на критичному шляху |
| Зв'язні атрибути | Значення — рядки ≤200 символів; ключі `metadata` — лише алфавітно-цифрові; невалідні відкидаються з попередженням |
| Оцінки | `BOOLEAN` — це float 0/1, причому `data_type` треба вказати явно, інакше 0/1 вважається NUMERIC |
| Текстові оцінки | 1–500 символів |
| Оцінка спостереження | Потрібні **обидва** ідентифікатори: `observation_id` і відповідний `trace_id` |
"""
    ),

    # ── 23.8 самоперевірка назв ──────────────────────────────────────────
    md(
        """
## 23.8 Перевірка назв атрибутів за реєстром

Найпростіший спосіб не вигадати назву атрибута — перевіряти її машиною.
Візьмемо всі `gen_ai.*`-ключі, які ми встановили в цьому ноутбуці, і звіримо
з реєстром у `research/10/otel_attrs.txt`.
"""
    ),
    code(
        '''
import re
import pathlib

registry_path = ROOT / "research/10/otel_attrs.txt"
registry_text = registry_path.read_text(encoding="utf-8")

# У реєстрі ключ стоїть на початку рядка і завершується " |".
REGISTRY_KEYS = set(re.findall(r"^(gen_ai\\.[a-z0-9_.]+) \\|", registry_text, flags=re.M))
DEPRECATED_KEYS = {
    "gen_ai.system",
    "gen_ai.usage.prompt_tokens",
    "gen_ai.usage.completion_tokens",
    "gen_ai.prompt",
    "gen_ai.completion",
}

USED_KEYS = {"gen_ai.operation.name", "gen_ai.provider.name", "gen_ai.request.model",
             "gen_ai.response.model", "gen_ai.usage.input_tokens",
             "gen_ai.retrieval.query.text", "gen_ai.retrieval.documents",
             "gen_ai.tool.call.result", "gen_ai.evaluation.score.label",
             "gen_ai.conversation.id", "gen_ai.data_source.id"}

print(f"Ключів у реєстрі ({registry_path.name}): {len(REGISTRY_KEYS)}")
print(f"Застарілих серед них             : {len(DEPRECATED_KEYS & REGISTRY_KEYS)}")
print(f"Перевіряємо ключів              : {len(USED_KEYS)}")
print()

unknown = sorted(USED_KEYS - REGISTRY_KEYS)
print("Ключі, яких немає в реєстрі:", unknown or "немає")
print()
print("Застарілі ключі, які НЕ можна використовувати:",
      sorted(DEPRECATED_KEYS))
print()
print("Приклади ключів із реєстру (перші 12):")
for k in sorted(REGISTRY_KEYS)[:12]:
    print("  ", k)
'''
    ),

    # ── самоперевірка ────────────────────────────────────────────────────
    md(
        """
## Самоперевірка

Клітинка нижче перевіряє твердження з розділу. Якщо все виконано правильно —
усі перевірки пройдуть.
"""
    ),
    code(
        '''
# ── 1. Ідентифікатори відповідають W3C Trace Context ─────────────────────
tid, sid = new_trace_id(), new_span_id()
assert len(tid) == 32 and all(c in "0123456789abcdef" for c in tid), "trace_id: 32 hex"
assert len(sid) == 16 and all(c in "0123456789abcdef" for c in sid), "span_id: 16 hex"
print("✓ Ідентифікатори: trace_id 32 hex, span_id 16 hex")

# ── 2. Детермінований trace_id відтворюваний ─────────────────────────────
assert deterministic_trace_id("req_12345") == deterministic_trace_id("req_12345")
assert deterministic_trace_id("req_12345") != deterministic_trace_id("req_54321")
print("✓ deterministic_trace_id стабільний для одного seed")

# ── 3. Вкладеність будується контекстом, без ручного parent ──────────────
ex = ConsoleSpanExporter(verbose=False)
tr = Tracer(ex)
with tr.start_span("root"):
    with tr.start_span("child"):
        pass
root_span = next(s for s in ex.received if s.name == "root")
child_span = next(s for s in ex.received if s.name == "child")
assert child_span.parent_span_id == root_span.span_id, "дитина має знати батька"
assert {s.trace_id for s in ex.received} == {root_span.trace_id}, "один trace_id"
print("✓ Контекст: child.parent_span_id == root.span_id, trace_id спільний")

# ── 4. Помилка в спані не губиться ───────────────────────────────────────
ex_err = ConsoleSpanExporter(verbose=False)
tr_err = Tracer(ex_err)
try:
    with tr_err.start_span("failing-call", kind="CLIENT"):
        raise TimeoutError("provider timeout")
except TimeoutError:
    pass
failed = ex_err.received[0]
assert failed.status["code"] == "ERROR", "статус має бути ERROR"
assert failed.attributes["error.type"] == "TimeoutError", "error.type = назва винятку"
print("✓ Помилка: status=ERROR і error.type=TimeoutError записані на спан")

# ── 5. Обов'язкові атрибути інференс-спану на місці ──────────────────────
chat = next(s for s in exporter.received if s.name.startswith("chat "))
assert chat.attributes["gen_ai.operation.name"] == "chat"
assert chat.attributes["gen_ai.provider.name"] == "openai"
print("✓ Інференс-спан має Required-атрибути operation.name і provider.name")

# ── 6. Кешовані токени — підмножина вхідних ──────────────────────────────
assert cache_share(chat) <= 1.0, "частка кешу не може перевищувати 100%"
assert cached_in <= total_in and reasoning_out <= total_out, "підмножини"
print(f"✓ Токени: cache_read {cached_in} ⊆ input {total_in}; reasoning ⊆ output")

# ── 7. Події мають правильні назви й несуть вміст ────────────────────────
ex_ev = ConsoleSpanExporter(verbose=False)
tr_ev = Tracer(ex_ev)
with tr_ev.start_span("chat gpt-4", kind="CLIENT") as s:
    s.add_event("gen_ai.client.inference.operation.details",
                {"gen_ai.input.messages": [{"role": "user",
                                            "parts": [{"type": "text", "content": "hi"}]}]})
    s.add_event("gen_ai.evaluation.result", {"gen_ai.evaluation.name": "Relevance"})
names = [e["name"] for e in ex_ev.received[0].events]
assert names == ["gen_ai.client.inference.operation.details", "gen_ai.evaluation.result"]
assert "gen_ai.input.messages" in ex_ev.received[0].events[0]["attributes"]
print("✓ Події: вміст живе в події, а не в атрибутах спану")

# ── 8. Гістограма метрик накопичувальна й закінчується +Inf ──────────────
hist = histogram(durations, BUCKETS_S)
assert hist[-1][0] == "+Inf" and hist[-1][1] == len(durations), "+Inf = усі значення"
assert all(a[1] <= b[1] for a, b in zip(hist, hist[1:])), "багети не спадають"
print(f"✓ Гістограма: {len(BUCKETS_S)} меж із конвенцій, останній бакет +Inf = {hist[-1][1]}")

# ── 9. Кожна використана назва атрибута є в реєстрі ──────────────────────
unknown_keys = sorted(USED_KEYS - REGISTRY_KEYS)
assert not unknown_keys, f"вигадані назви: {unknown_keys}"
assert {"gen_ai.operation.name", "gen_ai.provider.name"} <= REGISTRY_KEYS
print(f"✓ Реєстр: усі {len(USED_KEYS)} назв підтверджені otel_attrs.txt")

# ── 10. Застарілі ключі не використано ───────────────────────────────────
assert not (USED_KEYS & DEPRECATED_KEYS), "у коді є застарілі ключі"
print("✓ Застарілі ключі (gen_ai.system, gen_ai.usage.prompt_tokens) не використано")

print()
print("Усі перевірки пройдено.")
'''
    ),

    # ── підсумок ─────────────────────────────────────────────────────────
    md(
        """
## Підсумок

**Головне з цього ноутбука:**

1. **Трейс — це структура, а не лог.** Батьківство й час на кожному кроці
   перетворюють суму витрат на відповідь «де саме зламалося».
2. **Ідентифікатори стандартизовані.** `trace_id` — 32 hex (16 байтів),
   `span_id` — 16 hex (8 байтів), за W3C Trace Context. Тому трейси
   зшиваються між сервісами й вендорами.
3. **Батьківство береться з контексту.** `contextvars` (Python) або
   OpenTelemetry context — не ручний `parent` на кожному виклику.
4. **Назви атрибутів беруть із реєстру.** `gen_ai.operation.name` і
   `gen_ai.provider.name` — обов'язкові; `gen_ai.system`,
   `gen_ai.usage.prompt_tokens`, `gen_ai.usage.completion_tokens` — застарілі.
5. **Підмножини не сумують.** `cache_read`, `cache_creation` і `reasoning`
   входять у `input_tokens` / `output_tokens`; додавати їх — подвійний облік.
6. **Вміст живе в подіях.** `gen_ai.input.messages`, `gen_ai.output.messages`,
   `gen_ai.tool.call.arguments` — рівень Opt-In і потенційні PII.
7. **Метрики задані разом із межами.** Без меж гістограми
   `gen_ai.client.operation.duration` перцентилі непорівнювані.
8. **Langfuse SDK v4 — це OTel зсередини.** Контекстний менеджер, декоратор
   `observe`, ручні спостереження — усе сумісне; ручні вимагають `.end()`,
   а короткоживучі процеси — `flush()`/`shutdown()`.
9. **Промпт — артефакт із версіями й мітками.** `production` — те, що
   забирає продакшн; SDK кешує промпти клієнтськи, тож падіння Langfuse
   не зупиняє застосунок.
10. **Перевіряйте назви машиною.** Регулярка по реєстру (клітинка 23.8)
    ловить вигадані ключі раніше, ніж вони потраплять у дашборд.

**Куди далі:**

- Розділ 24 — евалюація: Promptfoo, LLM-як-суддя, датасети й оцінки в CI.
- Розділ 25 — продакшн-сервінг: SSE-стрімінг, таймаути, бюджет і SLO.
- Розділ 27 — безпека: що саме не можна писати в телеметрію.

## Джерела

- [Langfuse — Instrumentation (Python SDK v4)](https://langfuse.com/docs/observability/sdk/python/instrumentation)
- [Langfuse — Python v3 → v4 migration](https://langfuse.com/docs/observability/sdk/upgrade-path/python-v3-to-v4)
- [Langfuse — Prompt Management: Get Started](https://langfuse.com/docs/prompt-management/get-started)
- [Langfuse — Datasets](https://langfuse.com/docs/evaluation/dataset-runs/datasets)
- [Langfuse — Scores via API/SDK](https://langfuse.com/docs/evaluation/evaluation-methods/scores-via-sdk)
- [Langfuse — Self-hosting](https://langfuse.com/self-hosting)
- [Langfuse — Docker Compose deployment](https://langfuse.com/self-hosting/docker-compose)
- [Langfuse — Pricing](https://langfuse.com/pricing)
- [Langfuse — OpenTelemetry for LLM Observability](https://langfuse.com/docs/opentelemetry/get-started)
- [OpenTelemetry — GenAI attributes registry](https://opentelemetry.io/docs/specs/semconv/registry/attributes/gen-ai/)
- [OpenTelemetry GenAI semantic conventions (новий репозиторій)](https://github.com/open-telemetry/semantic-conventions-genai)
- Знімки джерел у репозиторії: `research/10/otel_attrs.txt`, `research/10/otel_spans_x.txt`,
  `research/10/otel_events_x.txt`, `research/10/otel_metrics_x.txt`,
  `research/10/otel_token-metrics_x.txt`, `research/10/otel_agent-spans_x.txt`
"""
    ),
]
