## 17. Оцінювання RAG: метрики RAGAS

RAG-конвеєр має дві поверхні відмов, і вони майже не перетинаються. Перша — **пошук**: потрібного
чанка немає серед знайдених, або він є, але стоїть у ранжуванні нижче за тематично схожий шум. Друга —
**генерація**: чанки знайдено правильно, а модель усе одно додала число, дату чи назву, яких у
контексті не було. Обидві відмови дають однаковий симптом для користувача — неправильну відповідь —
і протилежні вимоги до виправлення: у першому випадку треба чіпати індекс, чанкінг і reranker,
у другому — промпт і модель. Одне число на весь конвеєр ці випадки не розрізняє.

Цей розділ — про те, як отримати не одне число, а **набір чисел, які розділяють поверхні**.
Основний інструмент — **RAGAS** (Retrieval Augmented Generation Assessment): бібліотека метрик, яка
перетворює четвірку «питання, знайдені чанки, відповідь, еталон» на набір оцінок у діапазоні 0…1.
Бібліотека не замінює загальний процес евалюації з розділу 24 — вона його **конкретизує**: там були
Promptfoo, golden set, LLM-як-суддя і red teaming як дисципліна, тут — конкретні метрики для RAG,
їхні формули, їхні вимоги до даних і їхня ціна.

Стан на 09.2026: на PyPI доступна версія **ragas 0.4.3** (`requires_python >= 3.9`, завантажена
13 січня 2026). Документація прямо попереджає про перехід: старий «legacy metrics API»
(`from ragas.metrics import Faithfulness`, метод `single_turn_ascore`, клас `SingleTurnSample`)
**задепрекейчено у версії 0.4 і буде вилучено у 1.0**; для нових проєктів рекомендовано
«collections-based API» (`from ragas.metrics.collections import Faithfulness`, метод `ascore`).
Обидва варіанти нижче наведено там, де це важливо для розуміння різниці, і позначено, який із них
legacy. Залежності пакета тягнуть `datasets>=4.0.0`, `openai>=1.0.0`, `langchain`, `langchain-core`,
`langchain-community`, `langchain_openai`, `instructor`, `pydantic>=2.0.0`, `nest-asyncio`,
`scikit-network`, `networkx` — це не легка бібліотека, і в CI її поява помітна.

### 17.1 Що саме вимірюємо в RAG

**Що це.** Оцінювання RAG розкладають на три рівні, і кожен рівень відповідає на своє питання
(формулювання рівнів — із документації RAGAS, сторінка «Overview of Metrics»):

| Рівень | Що оцінює | Приклад метрики з документації | Хто діє за результатом |
|---|---|---|---|
| End-to-end | Конвеєр як чорна скринька, очима користувача | Answer correctness, citation accuracy | Продуктова команда |
| Component-level | Окремий вузол конвеєра | Retrieval accuracy | Інженер пошуку |
| Business | Організаційний результат, lagging indicator | Ticket deflection rate | Власник продукту |

Документація наголошує на властивості, яку легко проґавити: **покращення component-level метрики не
гарантує покращення end-to-end результату**. «A low retrieval accuracy (e.g., 50%) signals that
improving this component can enhance overall system performance. However, improving a component
alone doesn't guarantee better end-to-end outcomes». Тобто метрика пошуку — це не KPI, а діагноз.

**Навіщо це знати.** Без дворівневого розкладу будь-яка регресія виглядає як «модель стала гірше».
З дворівневим розкладом вона виглядає як один із чотирьох діагнозів:

| | **Контекст правильний** | **Контекст неправильний** |
|---|---|---|
| **Відповідь вірна** | Конвеєр працює | Випадковий успіх: gold-чанк не знайдено, але модель знала відповідь із параметричних знань |
| **Відповідь невірна** | **Помилка генерації** — чіпати промпт, вимогу цитувати, модель | **Помилка пошуку** — чіпати чанкінг, гібридний пошук, reranker |

Нижній лівий і нижній правий квадранти лікуються протилежними діями. Саме тому метрика
`answer_correctness` (або оцінка людиною чи суддею) без метрик контексту не дає керованого сигналу.

**Як працює під капотом.** Метрики розділяються за **входами**, які їм потрібні, і це визначає
і ціну, і те, чи можна їх застосувати до наявних логів. У RAGAS одиниця оцінювання — «evaluation
sample»; для одноходових метрик це `SingleTurnSample` з полями `user_input`, `retrieved_contexts`,
`response`, `reference`, `rubric`. Документовані поля (сторінка «Evaluation Sample»):

| Поле | Що містить | Хто заповнює |
|---|---|---|
| `user_input` | Питання користувача | Логи продакшену або тестовий набір |
| `retrieved_contexts` | Знайдені чанки, у порядку ранжування | Ваш ретривер |
| `response` | Відповідь генератора | Ваш конвеєр |
| `reference` | Еталонна відповідь | Людина-експерт або синтетична генерація |
| `rubric` | Критерії оцінювання (словник) | Ваша предметна область |

Друге, що визначає метрику, — **механізм під капотом**. Документація ділить метрики на дві родини:
«LLM-based metrics: These metrics use LLM underneath to do the evaluation. There might be one or
more LLM calls that are performed to arrive at the score or result» (наслідують клас `MetricWithLLM`,
потребують об'єкта LLM) і «Non-LLM-based metrics: These metrics do not use LLM underneath to do
the evaluation. These metrics are deterministic» (наслідують клас `Metric`). Ця різниця — не деталь
реалізації: вона визначає, чи можна метрику запускати в CI без ключа й без бюджету.

Крім того, документація класифікує метрики за **типом виходу**: `discrete_metric` (значення з
переліку категорій, без порядку), `numeric_metric` (число в заданому діапазоні, підтримує `mean`,
`sum`, `mode`) і `ranking_metric` (повертає впорядкований список індексів для порівняння кількох
виводів між собою). Це різниця в арифметиці агрегації: середнє по категоріях `pass`/`fail` — це
частка проходжень, і саме так працює більшість «суддівських» гейтів.

**Контроль детермінізму на рівні судді.** Документація OpenAI для модельного оцінювача (`score_model`
grader) описує схему, у якій ці параметри — частина конфігурації:

```json
{
    "type": "score_model",
    "name": "my_score_model",
    "input": [
        {"role": "system", "content": "You are an expert grader."},
        {"role": "user", "content": "Reference: {{ item.reference_answer }}. Model answer: {{ sample.output_text }}"}
    ],
    "pass_threshold": 0.5,
    "model": "o4-mini-2025-04-16",
    "range": [0, 1],
    "sampling_params": {
        "max_completions_tokens": 32768,
        "top_p": 1,
        "reasoning_effort": "medium"
    }
}
```

Документовані обмеження цієї схеми важливі саме для відтворюваності: набір дозволених моделей
обмежений (`gpt-4o-2024-08-06`, `gpt-4o-mini-2024-07-18`, `gpt-4.1-2025-04-14`, `gpt-4.1-mini-2025-04-14`,
`gpt-4.1-nano-2025-04-14`, `o1-2024-12-17`, `o3-mini-2025-01-31`, `o3-2025-04-16`, `o4-mini-2025-04-16`);
«`temperature` changes not supported for reasoning models», а «`reasoning_effort` is not supported for
non-reasoning models». Тобто зафіксувати `temperature` для reasoning-моделі через цю схему **не
можна** — і це треба знати до того, як обіцяти відтворюваність. Формат відповіді судді теж
фіксований: `{"result": float, "steps": ReasoningStep[]}`, де кожен крок має поля `description` і
`conclusion`, і документація радить явно посилатися на ці поля в промпті судді.

**Приклад.** Нижче — реальний прогін тестового набору з 8 кейсів, де кожен кейс має золотий чанк
і «чанк-двійник»: тематично схожий, зі спільним словом у назві метрики, але не той, що відповідає
на питання. Три конфігурації конвеєра розрізняються лише одним із двох вузлів.

Корпус складається зі **справжніх дослівних уривків** документації RAGAS, збереженої в
`research/06b/`; метрики пораховані власною реалізацією формул на стандартній бібліотеці
(формули — у 17.2 і 17.3, повний код — у ноутбуку `notebooks/17-rag-eval.ipynb`). Викликів LLM
у цьому прогоні немає, тому числа відтворюються біт у біт.

```text
варіант  A — добрий ретривер + відповідь із контексту
  faithfulness                 = 1.0000
  answer relevancy             = 0.4672
  context precision            = 1.0000
  context precision (ID-based) = 0.5000
  context recall               = 1.0000

варіант  B — добрий ретривер + відповідь із вигадкою
  faithfulness                 = 0.5000
  answer relevancy             = 0.2336
  context precision            = 1.0000
  context precision (ID-based) = 0.5000
  context recall               = 1.0000

варіант  C — навмисно зламаний ретривер + відповідь із контексту
  faithfulness                 = 1.0000
  answer relevancy             = 0.0590
  context precision            = 0.0000
  context precision (ID-based) = 0.0000
  context recall               = 0.0000
```

Читається це так. У варіанті **A** всі метрики максимальні, крім ID-based precision — вона дорівнює
0.5, бо ретривер повернув два чанки, а золотий серед них один. Це не помилка, а властивість метрики,
розібрана в 17.2. У варіанті **B** упала **тільки faithfulness** (1.0 → 0.5) і разом із нею answer
relevancy, а всі метрики пошуку залишилися незмінними: retrieval-вузол недоторканий, зламався
генератор. У варіанті **C** навпаки — faithfulness дорівнює 1.0 (відповідь дослівно взята з
контексту, хоч контекст і не той), а всі метрики пошуку нульові. Одна метрика на кшталт
`answer_correctness` у всіх трьох випадках дала б «погано» і не сказала б, куди йти.

**Типові помилки.**

1. **Оцінювати тільки end-to-end.** Тоді «покращення» після переписування промпту насправді
   компенсує деградований пошук: оцінка відповіді тримається на параметричних знаннях моделі, а не
   на вашому контексті. Ознака — високий `answer_correctness` при низькому `context_recall`.
2. **Міряти retrieval-метрики на `response`, а не на `reference`.** Документація для версії без
   еталона прямо каже: «To estimate if the retrieved contexts are relevant, this method uses the LLM
   to compare each chunk in `retrieved_contexts` with the `response`». Якщо відповідь неповна,
   релевантні чанки, які ви не використали, будуть пораховані як нерелевантні — і ви «покращите»
   precision, викинувши корисні документи.
3. **Вважати component-метрику KPI.** Документація попереджає явно, що зв'язок не прямий.
   Retrieval accuracy 100% при поганому промпті дає погану відповідь; retrieval accuracy 50% при
   сильній моделі може дати прийнятну відповідь.
4. **Порівнювати оцінки між різними наборами метрик або різними суддями.** Кожна метрика має
   власну шкалу й власний промпт. Документація радить фіксувати версії промптів метрик, а
   кастомізація промптів винесена в окремий how-to.
5. **Забути, що `reference` — теж джерело похибки.** У метриці `context_recall` еталон
   розбивається на твердження, і кожне перевіряється на підтвердженість контекстом. Неповний
   еталон занижує recall; надто докладний — завищує вимоги до ретривера.

**Альтернативи.**

| Підхід | Що дає | Ціна | Коли доречний |
|---|---|---|---|
| RAGAS | Готові формули з розділенням retrieval/generation | Важкі залежності + виклики судді | Регулярний прогін на golden set |
| Власні детерміновані перевірки | Повний контроль, нуль викликів LLM | Треба писати й підтримувати | Обмежений бюджет, CI на кожен PR |
| ID-based метрики RAGAS | Точні, якщо у вас є ID документів | Потрібна система ID | Є стабільний мапінг «чанк → ID» |
| Оцінка людиною | Найвища точність | Години на розмітку | Калібрування судді, фінальне приймання |
| Спостережуваність продакшену (розділ 23) | Реальний розподіл запитів | Інфраструктура | Після випуску, пошук дрейфу |

### 17.2 Метрики на основі LLM-судді

**Що це.** «LLM-суддя» (LLM-as-judge) — це метрика, яка замість формули виконує один або кілька
викликів мовної моделі за власним промптом. У RAGAS така метрика наслідує `MetricWithLLM` і потребує
переданого об'єкта LLM. Документація описує компроміс прямо:

> «These metrics can be somewhat non-deterministic as the LLM might not always return the same result
> for the same input. On the other hand, these metrics has shown to be more accurate and closer to
> human evaluation.»

Найважливіша інженерна деталь тут — **декомпозиція**. Замість питання «оціни відповідь від 1 до 10»
RAGAS розбиває задачу на підзадачі з окремими промптами: спершу видобути твердження, потім
перевірити кожне окремо. Документація формулює це як принцип проєктування метрик: «Decomposing
complex tasks into smaller sub-tasks with specific prompts can improve the accuracy and relevance of
the metric». Це і є причина, чому метрики LLM-судді коштують не одного виклику, а багатьох
(арифметика — у 17.5).

**Навіщо це знати.** Формули нижче треба знати напам'ять, бо вони визначають, як інтерпретувати
число. `faithfulness = 0.5` означає конкретне: половина тверджень у відповіді не виводиться з
контексту. `context_precision = 0.5` означає інше: релевантний чанк стоїть не першим. Однакова
цифра — різні дії.

**Як працює під капотом.** Далі — метрики RAG, які документація відносить до «natural language
comparison» і «RAG evaluation». Формули наведено так, як вони подані в документації.

**Faithfulness** (вірність контексту). Вимірює фактичну узгодженість відповіді зі знайденим
контекстом; діапазон 0…1. «A response is considered faithful if all its claims can be supported by
the retrieved context». Кроки: видобути всі твердження з відповіді; перевірити кожне, чи виводиться
воно з контексту; поділити кількість підтверджених на загальну кількість.

```text
Faithfulness = (кількість тверджень відповіді, підтверджених контекстом)
             / (загальна кількість тверджень у відповіді)
```

Документований приклад: питання «Where and when was Einstein born?», контекст називає 14 березня
1879 року, відповідь каже «20th March 1879». Розбір: твердження 1 «Einstein was born in Germany» —
підтверджено; твердження 2 «Einstein was born on 20th March 1879» — ні; результат
`1 / 2 = 0.5`. Зверніть увагу: faithfulness **не** потребує `reference`, лише `response` і
`retrieved_contexts`. Це ключ до 17.3.

**Response Relevancy** (релевантність відповіді; у колекційному API клас називається
`AnswerRelevancy`, у legacy — `ResponseRelevancy`). Наскільки відповідь відповідає на питання,
без оцінки фактичної правильності. «It penalizes answers that are incomplete or include unnecessary
details». Механіка — зворотна генерація: з відповіді створюють набір штучних питань (**за
замовчуванням 3**, керується параметром `strictness`), після чого беруть середню косинусну
близькість між вектором початкового питання й векторами згенерованих питань.

```text
Answer Relevancy = (1 / N) * Σ cos_sim(E_gi, E_o)
```

де `E_gi` — вектор i-го згенерованого питання, `E_o` — вектор початкового питання, `N` — кількість
згенерованих питань. Документація окремо застерігає: «While the score usually falls between 0 and 1,
it is not guaranteed due to cosine similarity's mathematical range of -1 to 1». Ідея метрики
сформульована так: «if the answer correctly addresses the question, it is highly probable that the
original question can be reconstructed solely from the answer». Документований вихід для прикладу з
Super Bowl — `0.9165088378587264`.

**Context Precision** (точність контексту). Оцінює здатність ретривера **ставити релевантні чанки
вище** за нерелевантні. Обчислюється як середнє `precision@k` по кожному чанку; `precision@k` — це
відношення кількості релевантних чанків на позиціях до `k` включно до `k`.

```text
Context Precision@K = Σ_{k=1..K} ( Precision@k * v_k ) / (кількість релевантних у топ-K)
Precision@k         = true_positives@k / (true_positives@k + false_positives@k)
```

`K` — загальна кількість чанків у `retrieved_contexts`, `v_k ∈ {0, 1}` — індикатор релевантності на
позиції `k`. Документація показує чутливість до рангу на власному прикладі: коли релевантний чанк
перший, оцінка `0.9999999999`; коли той самий набір чанків переставлено так, що нерелевантний
опиняється першим, оцінка падає до `0.49999999995`. При цьому «even if an irrelevant chunk is
present at the second position in the array, context precision remains the same».

**Context Recall** (повнота контексту). Скільки релевантної інформації взагалі вдалося знайти;
«it focuses on not missing important results». Документація наголошує: «Since it is about not missing
anything, calculating context recall always requires a reference to compare against». Еталон
розбивається на твердження, і кожне перевіряється на приналежність знайденому контексту:

```text
Context Recall = (кількість тверджень еталона, підтверджених знайденим контекстом)
               / (загальна кількість тверджень еталона)
```

**FactualCorrectness** (фактична правильність). Порівнює відповідь із еталоном, розбиваючи обидва
на твердження й застосовуючи natural language inference (NLI) для визначення фактичного перетину.
«Factual overlap is quantified using precision, recall, and F1 score, which can be controlled using
the `mode` parameter»; за замовчуванням `mode="f1"`. Документований приклад: відповідь «The Eiffel
Tower is located in Paris» проти еталона з додатковим твердженням про висоту 1000 футів дає `0.67`
у режимі f1 і `1.0` у режимі precision.

**NoiseSensitivity** (чутливість до шуму). Скільки помилок система робить, отримуючи **або**
релевантні, **або** нерелевантні документи; менше — краще. Режим перемикається параметром: за
замовчуванням рахуються неправильні твердження, підкріплені релевантним контекстом, а
`NoiseSensitivity(llm=llm, mode="irrelevant")` — підкріплені нерелевантним. Документований приклад
із LIC дає `0.3333333333333333`.

**AspectCritic і метрики на рубриках** (підхід «оціни за критерієм»). `AspectCritic` приймає
`name` і `definition` — наприклад, `AspectCriticWithReference(name="answer_correctness",
definition="is the response correct compared to reference")`. Документація також описує рубрикові
метрики двох видів: `DomainSpecificRubrics` (одна рубрика на весь набір, задається при ініціалізації)
та `InstanceSpecificRubrics` (своя рубрика на кожен зразок). Рубрика — це набір описів для кожної
оцінки, «typically ranging from 1 to 5», і модель виставляє бал, орієнтуючись на ці описи. Власну
рубрику передають словником із ключами `score1_description` … `score5_description`.

Зведення вимог до входів і поведінки:

| Метрика | `user_input` | `retrieved_contexts` | `response` | `reference` | Механізм | Детермінована |
|---|---|---|---|---|---|---|
| Faithfulness | потрібно | потрібно | потрібно | не потрібно | видобуток тверджень + перевірка кожного | ні |
| FaithfulnesswithHHEM | потрібно | потрібно | потрібно | не потрібно | те саме, але перевірка класифікатором HHEM-2.1-Open (T5) | майже (модель, без LLM-судді) |
| Response Relevancy | потрібно | не потрібно | потрібно | не потрібно | 3 зворотні питання + косинусна близькість | ні |
| Context Precision | потрібно | потрібно | потрібно (версія без еталона) | потрібно (версія з еталоном) | `precision@k` по ранжуванню | ні |
| Context Precision (ID-based) | не потрібно | ID-и замість тексту | не потрібно | ID-и еталона | точна формула | так |
| Context Recall | потрібно | потрібно | не потрібно | потрібно | твердження еталона проти контексту | ні |
| Context Recall (ID-based) | не потрібно | ID-и | не потрібно | ID-и еталона | точна формула | так |
| FactualCorrectness | не потрібно | не потрібно | потрібно | потрібно | NLI, режими precision/recall/f1 | ні |
| NoiseSensitivity | потрібно | потрібно | потрібно | потрібно | режим `relevant` або `irrelevant` | ні |
| AspectCritic | потрібно | опційно | потрібно | опційно | один критерій `name` + `definition` | ні |
| DomainSpecificRubrics | потрібно | опційно | потрібно | опційно (`with_reference=True`) | рубрика з описами 1…5 | ні |

**Приклад.** Фрагмент із документації RAGAS для колекційного API — реальний код, не схема:

```python
from openai import AsyncOpenAI
from ragas.llms import llm_factory
from ragas.metrics.collections import Faithfulness, ContextPrecision, ContextRecall

client = AsyncOpenAI()
llm = llm_factory("gpt-4o-mini", client=client)

faithfulness_scorer = Faithfulness(llm=llm)
precision_scorer = ContextPrecision(llm=llm)
recall_scorer = ContextRecall(llm=llm)
```

Той самий набір через legacy API (задепрекейчено у 0.4, вилучення у 1.0):

```python
from ragas.dataset_schema import SingleTurnSample
from ragas.metrics import Faithfulness, LLMContextPrecisionWithReference, LLMContextRecall

sample = SingleTurnSample(
    user_input="Where is the Eiffel Tower located?",
    response="The Eiffel Tower is located in Paris.",
    reference="The Eiffel Tower is located in Paris.",
    retrieved_contexts=["The Eiffel Tower is located in Paris.", "The Brandenburg Gate is located in Berlin."],
)
```

Партійний прогін цілого набору (теж із документації, сторінка «Evaluate a simple RAG system»):

```python
from ragas import EvaluationDataset, evaluate
from ragas.llms import LangchainLLMWrapper
from ragas.metrics import LLMContextRecall, Faithfulness, FactualCorrectness

evaluator_llm = LangchainLLMWrapper(llm)
result = evaluate(
    dataset=evaluation_dataset,
    metrics=[LLMContextRecall(), Faithfulness(), FactualCorrectness()],
    llm=evaluator_llm,
)
```

Документований вихід цього виклику на 5 питаннях:

```text
{'context_recall': 1.0000, 'faithfulness': 0.8571, 'factual_correctness': 0.7280}
```

Тепер — те, що дає власна реалізація формул. Нижче faithfulness і context precision пораховані
на тому самому наборі з 8 кейсів. Крок «LLM видобуває твердження» замінено розбиттям на речення,
крок «LLM перевіряє твердження» — перевіркою частки змістових слів твердження, наявних у контексті,
з порогом `tau = 0.8`. Це **не** метрика RAGAS і числа не порівнянні з її числами: мета інша —
побачити арифметику формули на конкретних твердженнях.

```text
Q1  контекст=['D01', 'D03']  faithfulness=1.000
    твердження: 'Faithfulness measures how factually consistent a response is with the retrieved context.'
      частка підтверджених слів = 1.000  -> підтверджено
Q1  відповідь із вигадкою (варіант B)
    твердження: 'It was introduced in 1975 by the same team, and it relies on a cosine kernel.'
      частка підтверджених слів = 0.000  -> НЕ підтверджено
    разом: 1 з 2 тверджень -> faithfulness = 0.500
```

Чутливість context precision до **порядку** при незмінному складі чанків — той самий набір
`['D01', 'D03', 'D04']`, релевантний лише `D01`:

```text
['D01', 'D03', 'D04']   context precision (ranked) = 1.0000   ID-based = 0.3333   recall = 1.0000
['D03', 'D01', 'D04']   context precision (ranked) = 0.5000   ID-based = 0.3333   recall = 1.0000
['D03', 'D04', 'D01']   context precision (ranked) = 0.3333   ID-based = 0.3333   recall = 1.0000
```

Це найкорисніша таблиця розділу. **Ranked precision** реагує на перестановку (1.0 → 0.5 → 0.3333),
**ID-based precision** і **recall** не реагують взагалі. Висновок для практики: у CI тримайте
ID-based метрики як стабільний гейт (вони детерміновані), а ranked precision — як метрику якості
ранжування; і ніколи не порівнюйте їхні числа між собою, бо це різні формули з різними знаменниками
(у ranked — кількість релевантних, у ID-based — кількість знайдених).

**Типові помилки.**

1. **Читати `context_precision` як «частку релевантних чанків».** Це не так: знаменник — кількість
   релевантних, а чисельник зважений на ранг. Для набору з трьох чанків вище ID-based precision
   дорівнює 1/3, а ranked precision для того самого набору дорівнює 1.0. Однакові назви, різна
   арифметика.
2. **Подавати чанки в довільному порядку.** `retrieved_contexts` — це впорядкований список;
   ranked precision читає ранг. Перемішати чанки перед оцінюванням означає зміряти не те, що
   повертає ретривер.
3. **Використовувати метрику без потрібного входу.** `ContextRecall` без `reference` не працює
   взагалі — це не «менш точна» оцінка, а відсутній вхід. Для випадку без еталона документація
   пропонує `ContextUtilization` (порівнює чанки з `response`) або
   `LLMContextPrecisionWithoutReference`.
4. **Вважати faithfulness гарантією правильності.** Faithfulness дорівнює 1.0 у варіанті C вище, бо
   відповідь дослівно взята з контексту — просто не з того. Faithfulness ловить вигадку, а не
   неправильний пошук; його треба читати разом із recall.
5. **Порівнювати faithfulness, порахований з `reference` і без нього.** Це два різні входи. У
   режимі `FaithfulnesswithHHEM` крок перевірки виконує не суддя, а класифікатор — і числа
   змістяться, навіть якщо конвеєр не змінювався.
6. **Годувати судді свій же промпт генерації.** Якщо промпт містить інструкцію «відповідай лише за
   контекстом», faithfulness зросте, а `answer_correctness` — ні. Це очікувано, але легко сплутати
   з покращенням.

**Альтернативи.**

| Замість | Можна взяти | Виграш | Програш |
|---|---|---|---|
| `Faithfulness` з LLM-суддею | `FaithfulnesswithHHEM` | Класифікатор T5, безкоштовний і малий; параметри `device` і `batch_size` (типово CPU, batch 10) | Своя модель у контурі, свої похибки |
| `LLMContextPrecision*` | `NonLLMContextPrecisionWithReference` | Детерміновано (Levenshtein, потребує `rapidfuzz`) | Слабша кореляція з людською оцінкою |
| `LLMContextRecall` | `NonLLMContextRecall` | Детерміновано | Потрібні `reference_contexts`, а не `reference` |
| Будь-який LLM-суддя | `IDBased*` метрики | Точні, дешеві, детерміновані | Потрібна власна система ID і мапінг |
| Вільна оцінка «1…10» | `AspectCritic` / рубрики | Один критерій, explicit `definition`, менше розкиду | Доводиться писати критерій словами |
| Власні промпти | Зміна промптів метрик (how-to) | Метрика під вашу мову й домен | Зламана порівнянність із попередніми прогонами |

### 17.3 Метрики без ground truth

**Що це.** «Ground truth» у RAG — це `reference`: еталонна відповідь, написана людиною або згенерована
й перевірена. Метрики без ground truth («reference-free») — ті, чиї входи не містять `reference`.
Важливо розділяти дві речі, які часто зливають в одну: **еталонна відповідь** (`reference`) і
**еталонні чанки** (`reference_contexts`). Це різні входи з різною ціною розмітки. Розмітити
«які документи релевантні» дешевше, ніж написати еталонну відповідь, але дорожче, ніж не розмічати
нічого.

**Навіщо це знати.** Розмітка еталонів — вузьке місце будь-якого RAG-проєкту: 500 пар «питання →
еталонна відповідь» це тижні роботи експерта, і саме тому документація RAGAS описує генерацію
тестового набору як окремий продукт. Метрики без ground truth дозволяють **почати вимірювати
сьогодні**, на логах продакшену, без жодної розмітки: `user_input` і `response` у вас уже є. Ціна
цієї швидкості — слабший сигнал: без еталона метрика не скаже, чи відповідь **правильна**, лише чи
вона **узгоджена** й **доречна**.

**Як працює під капотом.** Розкладімо метрики RAG за мінімально потрібним набором входів:

| Потрібні входи | Метрики | Що можна виявити | Чого не можна виявити |
|---|---|---|---|
| тільки `user_input` + `response` | Response Relevancy (`AnswerRelevancy`) | Відповідь не на те питання, обрізана відповідь, зайві деталі | Вигадку, неправильний контекст |
| `response` + `retrieved_contexts` | Faithfulness, `FaithfulnesswithHHEM`, `ContextUtilization`, `LLMContextPrecisionWithoutReference` | Модель додала те, чого немає в контексті; чанки не використані у відповіді | Чи знайдено **усі** потрібні чанки |
| `user_input` + `response` + `reference` | FactualCorrectness, `LLMContextPrecisionWithReference` | Розбіжність із еталоном | Де саме стався збій |
| `user_input` + `response` + `retrieved_contexts` + `reference` | `ContextRecall`, `NoiseSensitivity` | Чи нічого не загублено; чи шкодить шум | — (повний набір) |
| ID-и замість текстів | `IDBasedContextPrecision`, `IDBasedContextRecall` | Точність і повнота пошуку без LLM | Якість ранжування |

Ключове спостереження: **Faithfulness не потребує `reference`**, і це робить його основною метрикою
«без ground truth» для RAG. Документовані кроки — видобути твердження з `response`, перевірити кожне
проти `retrieved_contexts` — не згадують еталону взагалі. Тому faithfulness працює на живих логах:
берете реальний запит, реальні знайдені чанки, реальну відповідь — і отримуєте оцінку.

Друга половина механізму — **чим саме перевіряють твердження**. Документація описує альтернативу
LLM-судді: «Vectara's HHEM-2.1-Open is a classifier model (T5) that is trained to detect
hallucinations from LLM generated text. This model can be used in the second step of calculating
faithfulness, i.e. when claims are cross-checked with the given context to determine if it can be
inferred from the context. The model is free, small, and open-source». Клас називається
`FaithfulnesswithHHEM`, приймає `device` (типово CPU) і `batch_size` (типово 10). Тобто крок
перевірки тверджень можна винести з LLM-судді в локальний класифікатор — і отримати дешевшу,
локальну й менш недетерміновану метрику ціною заміни моделі.

**Приклад.** Візьмімо варіант **B** із 17.1 — той, де генератор додав до відповіді вигадане
твердження. Жодного `reference` не використано: узято лише `user_input`, `response` і
`retrieved_contexts`. Нижче — фактичний вивід власної реалізації обох reference-free метрик.

```text
faithfulness (лише response + retrieved_contexts)
  Q1  faith_A=1.000  faith_B=0.500
  Q2  faith_A=1.000  faith_B=0.500
  Q3  faith_A=1.000  faith_B=0.500
  Q4  faith_A=1.000  faith_B=0.500
  Q5  faith_A=1.000  faith_B=0.500
  Q6  faith_A=1.000  faith_B=0.500
  Q7  faith_A=1.000  faith_B=0.500
  Q8  faith_A=1.000  faith_B=0.500

answer relevancy (лише user_input + response)
  Q1  ar_A=0.2521  ar_B=0.1260
  Q2  ar_A=0.6659  ar_B=0.3330
  Q3  ar_A=0.2406  ar_B=0.1203
  Q4  ar_A=0.8391  ar_B=0.4195
  Q5  ar_A=0.5518  ar_B=0.2759
  Q6  ar_A=0.3907  ar_B=0.1953
  Q7  ar_A=0.2131  ar_B=0.1066
  Q8  ar_A=0.5841  ar_B=0.2921
```

Результат: **8 із 8** випадків вигадки виявлено без еталона, і в усіх восьми faithfulness
рівно 0.5 — бо у відповіді рівно два твердження й одне з них не підтверджується. Answer relevancy
впав рівно вдвічі на кожному кейсі, і причина видна в по-кроковому виводі:

```text
варіант A, Q1: answer relevancy = 0.2521
  cosine=0.2521  <- Faithfulness measures how factually consistent a response is with the retrieved context.

варіант B, Q1: answer relevancy = 0.1260
  cosine=0.2521  <- Faithfulness measures how factually consistent a response is with the retrieved context.
  cosine=0.0000  <- It was introduced in 1975 by the same team, and it relies on a cosine kernel.
```

Друге речення не має жодного спільного змістового слова з питанням, тому його внесок — нуль, і
середнє падає вдвічі. Це і є документована властивість: метрика «penalizes answers that are
incomplete or include unnecessary details». Практичний наслідок: answer relevancy карає не лише
вигадку, а й **багатослівність**. Якщо ваш промпт вимагає вступів на кшталт «Чудове питання!
Розгляньмо це детально», метрика це побачить як зниження релевантності. Це не баг метрики, це
сигнал про те, що відповідь містить інформацію, не потрібну для відповіді на питання.

**Типові помилки.**

1. **Плутати `reference` і `reference_contexts`.** `LLMContextRecall` приймає `reference`, а
   `NonLLMContextRecall` — `reference_contexts`. Це різні типи даних і різні вимоги до розмітки.
   Передати не той вхід означає отримати помилку або, гірше, безглузде число.
2. **Брати faithfulness як єдиний гейт якості.** Reference-free метрики не бачать **пропущеного**:
   якщо ретривер знайшов один чанк із п'яти потрібних, а генератор акуратно відповів лише за цим
   чанком, faithfulness буде 1.0, answer relevancy — високим, і конвеєр виглядатиме здоровим. У
   варіанті C вище саме це: faithfulness 1.0 при recall 0.0.
3. **Ганяти reference-free метрики на всьому трафіку.** Вони дешевші за повний набір, але не
   безкоштовні: faithfulness — це 1 + кількість тверджень викликів судді на зразок (арифметика
   в 17.5). На потоці в тисячі запитів на день це реальні гроші.
4. **Вважати `ContextUtilization` і `ContextPrecisionWithoutReference` тим самим.** Перший порівнює
   чанки з `response`, другий — теж із `response`, але з іншою арифметикою агрегації (rank-aware).
   Документація показує для `ContextUtilization` той самий ефект порядку: `0.9999999999`, а після
   перестановки нерелевантного чанка на перше місце — `0.49999999995`.
5. **Забувати, що суддя мусить мати достатній контекст.** Документація радить добирати оцінювача
   окремо від генератора (сторінка «Choose evaluator llm») і не використовувати ту саму дешеву
   модель, що генерує, бо її сліпі плями повторяться у вердикті.

**Альтернативи.**

| Замість | Варіант | Компроміс |
|---|---|---|
| LLM-суддя для faithfulness | `FaithfulnesswithHHEM` (T5-класифікатор) | Локально, безкоштовно, але своя модель і свої похибки |
| Faithfulness як гейт | `NoiseSensitivity` | Ловить, чи шум у контексті породжує помилки; потрібен `reference` |
| Reference-free precision | `LLMContextPrecisionWithReference` | Точніше, але потрібен еталон |
| Reference-free recall (неможливий) | Синтетичний набір із `reference` | Витрати на генерацію (17.4), зате повнота стає вимірюваною |
| Оцінка в продакшені | Спостережуваність + вибіркова перевірка людиною (розділи 23, 24) | Ловить дрейф, але із запізненням |

### 17.4 Побудова тестового набору

**Що це.** Тестовий набір (testset) для RAG — це колекція «evaluation sample»-ів, на яких
проганяється конвеєр. У RAGAS є два способи його отримати: **взяти готовий або написати руками**
(`EvaluationDataset.from_list(...)`, `EvaluationDataset.from_hf_dataset(...)`) і **згенерувати** зі
своїх документів. Генерація — це окремий підпродукт бібліотеки з власною архітектурою, і саме вона
визначає, наскільки тестовий набір схожий на реальний трафік.

**Навіщо це знати.** Набір, написаний розробником, систематично зміщений: він містить питання, на які
автор **знає** відповідь, і майже не містить багатокрокових питань, питань з іншою довжиною та
стилем, питань, де потрібно зіставити два документи. Документація описує цю проблему через
класифікацію запитів: вони бувають **однокрокові** (single-hop) і **багатокрокові** (multi-hop), і
кожен із цих типів — **конкретним** (specific, факт) або **абстрактним** (abstract, пояснення).

| Тип | Конкретний приклад із документації | Абстрактний приклад із документації |
|---|---|---|
| Single-hop | «What year did Albert Einstein publish the theory of relativity?» | «How did Einstein's theory change our understanding of time and space?» |
| Multi-hop | «Which scientist influenced Einstein's work on relativity, and what theory did they propose?» | «How have scientific theories on relativity evolved since Einstein's original publication?» |

Розробницький набір майже завжди складається з верхнього лівого квадранта. Multi-hop-абстрактний
запит вимагає зіставити кілька джерел — і саме на ньому ламається більшість конвеєрів. Документація
формулює причину, чому наївна генерація тут не працює: «Given that we want to manufacture different
types of queries from the given set of documents, our major challenge is to identify the right set of
chunks or documents to enable LLMs to create the queries».

**Як працює під капотом.** RAGAS розв'язує цю задачу через **граф знань** (Knowledge Graph) — не
щоб покращити пошук, а щоб **знати, які чанки можна зіставити**, і згенерувати питання саме про
зв'язок між ними. Конвеєр складається з п'яти компонентів; назви класів — із документації.

| Крок | Компонент | Що робить | Документований приклад |
|---|---|---|---|
| 1 | `DocumentSplitter` | Ріже документи на ієрархічні вузли; можна писати власні спліттери під домен | Для фінансових документів — спліт за секціями (Income Statement, Balance Sheet, Cash Flow Statement) |
| 2 | `Extractor` / `LLMBasedExtractor` | Витягує з вузла властивості для встановлення зв'язків | `NERExtractor` повертає `('entities', ['Einstein', 'theory of relativity', ...])` |
| 3 | Relationship builder | Будує зв'язки між вузлами на основі витягнутих властивостей | `JaccardSimilarityBuilder(property_name="entities", key_name="PER", new_property_name="entity_jaccard_similarity")` |
| 4 | `Transforms` / `apply_transforms` | Застосовує компоненти до графа послідовно; `Parallel(...)` дає паралельність | `apply_transforms(kg, transforms)` |
| 5 | Scenario Generation + `QuerySynthesizer` | Перетворює вузли на сценарії, а сценарії — на `EvalSample` | `generate_scenarios(...)`, `generate_sample(...)` |

Одиниця генерації — **сценарій** (scenario), і він складений із чотирьох параметрів, перелічених у
документації: `Nodes` (вузли, з яких будується питання), `Query Length` (коротке / середнє / довге),
`Query Style` (web search, chat тощо) і `Persona` (Senior Engineer, Junior Engineer тощо). Для
`Persona` документація додає «(Coming soon)», тобто на дату зрізу цей параметр заявлений, але ще не
доступний. Далі `QuerySynthesizer` вирішує, **скільки** сценаріїв кожного типу потрібно: «Imagine your
goal is to create 50 different queries where each query is about some abstract question comparing two
entities… This logic is implemented in `generate_scenarios` method», а `generate_sample` перетворює
один сценарій на `SingleTurnSample(user_input=..., reference_contexs=..., reference=...)`.

**Приклад.** Тестовий набір, на якому пораховано всі числа цього розділу, побудований зі **справжніх
уривків** документації RAGAS у `research/06b/`. Структура кейса — це рівно те, що потрібно метрикам
із 17.2:

```python
# Схема одного кейса тестового набору (не код бібліотеки).
CASE = {
    "case_id": "Q3",
    "user_input": "What does Context Precision evaluate?",
    "reference": "Context Precision evaluates the retriever ability to rank relevant chunks higher than irrelevant ones.",
    "gold_chunk_id": "D03",
    "twin_chunk_id": "D04",
}
```

`gold_chunk_id` — чанк, який **повинен** бути знайдений (він визначає `reference_context_ids` для
ID-based метрик і `reference` для LLM-метрик). `twin_chunk_id` — «чанк-двійник»: тематично близький,
навмисно доданий у набір, щоб мати чим зламати ранжування й перевірити, що метрики це побачать.
Без контрольованого «поганого» варіанта неможливо перевірити, що метрика взагалі щось розрізняє.

Окремо варто перевірити, що уривки корпусу — справжні цитати, а не переказ. Це робиться простою
перевіркою на входження рядка:

```text
D01 ragas_metric_faithfulness.txt              OK
D02 ragas_metric_faithfulness.txt              OK
D03 ragas_metric_context_precision.txt         OK
D04 ragas_metric_context_recall.txt            OK
D05 ragas_metric_answer_relevance.txt          OK
D06 ragas_metric_context_recall.txt            OK
D07 ragas_metrics_noise_sensitivity.txt        OK
D08 ragas_cost_customization.txt               OK
D09 ragas_metrics_overview.txt                 OK
D10 ragas_test_data_generation_rag.txt         OK

знайдено 10/10
```

Завантаження такого набору в RAGAS — це один виклик:

```python
from ragas import EvaluationDataset

evaluation_dataset = EvaluationDataset.from_list(dataset)
```

Документація показує і другий шлях — із готового набору на Hugging Face:
`EvaluationDataset.from_hf_dataset(dataset["eval"])` для `vibrantlabsai/amnesty_qa` (конфігурація
`english_v3`).

Тепер — як генерація виглядає в коді. Наступний фрагмент — **схема** з документації RAGAS: це
скелет власного синтезатора запитів, а не робочий код (у ньому залишено рядкові заглушки замість
логіки, як і в першоджерелі).

```python
# СХЕМА з документації RAGAS: власний QuerySynthesizer.
from dataclasses import dataclass
from ragas.testset.synthesizers.base_query import QuerySynthesizer
from ragas import SingleTurnSample


@dataclass
class EntityQuerySynthesizer(QuerySynthesizer):
    async def _generate_scenarios(self, n, knowledge_graph, callbacks):
        scenarios = []
        return scenarios

    async def _generate_sample(self, scenario, callbacks):
        query = scenario
        contexts = []
        reference = ""
        return SingleTurnSample(
            user_input=query, reference_contexs=contexts, reference=reference
        )
```

Зверніть увагу на написання `reference_contexs` (без `t`) — саме так у документації RAGAS на сторінці
«Testset Generation for RAG». Це не помилка цього довідника; імовірно, друкарська помилка в
першоджерелі, і покладатися на це ім'я аргументу не варто.

**Типові помилки.**

1. **Тестовий набір тільки з single-hop-конкретних питань.** Це найпоширеніша помилка: вона дає
   гарні метрики й не ловить поломку на зіставленні документів. Дивіться на розподіл типів запитів
   у наборі як на окрему величину.
2. **Генерувати питання з тих самих чанків, які потім шукати.** Якщо запит згенеровано **з** тексту
   чанка й містить його ж формулювання, пошук здається бездоганним — це лексичне самопідтвердження.
   Документація RAGAS обходить це, переписуючи вузол графа у сценарій з іншим стилем і довжиною, але
   повністю усунути ефект генерація зі своїх документів не може.
3. **Не тримати ID чанків.** Без `retrieved_context_ids` і `reference_context_ids` недоступні
   найдешевші й найточніші метрики — `IDBasedContextPrecision` і `IDBasedContextRecall`. Додати ID
   треба **до** побудови індексу, інакше доведеться перебудовувати.
4. **Мішати `reference` з `reference_contexts`.** У `SingleTurnSample` це різні поля, і в різних
   метриках вони позначають різне. Документоване визначення `SingleTurnSample` наводить обидва:
   `reference` — еталонна відповідь, `reference_contexts` — еталонні чанки.
5. **Очікувати, що згенерований набір буде безкоштовним.** Генерація йде через LLM: `LangchainLLMWrapper(ChatOpenAI(model="gpt-4o"))`
   для генератора й окремо `OpenAIEmbeddings` для векторів. Рахунок за створення набору — окремий
   рядок у бюджеті, і при генерації на 5000 питань він не малий.
6. **Перевіряти генератор тим самим суддею.** Документація для калібрування судді прямо вимагає
   експертних міток, а не міток іншої моделі: «The quality of judge alignment depends entirely on
   the quality of your ground truth labels… involve a principal domain expert».

**Альтернативи.**

| Спосіб отримати набір | Плюси | Мінуси | Коли брати |
|---|---|---|---|
| Написати руками | Максимальна точність, мала кількість | Дорого, зміщено до знань автора | 10–30 кейсів для диму й регресійних тестів |
| `EvaluationDataset.from_hf_dataset` | Безкоштовно, є готові RAG-набори | Домен не ваш | Перше знайомство, бенчмарк |
| Knowledge-graph генерація RAGAS | Покриває multi-hop і різні стилі | Потрібні LLM-виклики, своя архітектура, залежність від якості графа | Потрібен набір на сотні кейсів під свій корпус |
| Логи продакшену + розмітка експертом | Розподіл запитів реальний | Треба мати трафік і експерта | Зріла система |
| EvalsBench-подібні набори для калібрування судді | Експертні мітки готові | Не про ваш домен | Калібрування судді (17.5) |

### 17.5 Ціна й детермінізм LLM-оцінювання

**Що це.** Дві властивості, які відрізняють LLM-оцінювання від юніт-тестів. **Ціна**: кожна метрика —
це не один виклик, а сума викликів, і вона масштабується з кількістю зразків, повторів і метрик.
**Детермінізм**: та сама метрика на тому самому вході дає різні числа в різних прогонах, тому
різниця між двома версіями конвеєра може бути шумом судді, а не покращенням.

**Навіщо це знати.** Обидві властивості б'ють у бюджет і в довіру до результату одночасно. Команда,
яка не рахує ціну до запуску, виявляє її після рахунку; команда, яка не рахує розкид, «покращує»
конвеєр на 0.03 і через тиждень виявляє, що це був шум. Документація RAGAS присвячує ціні окрему
сторінку how-to, а OpenAI у схемі судді-оцінювача прямо передбачає `seed`, `temperature` і `top_p` —
тобто контроль детермінізму є частиною контракту, а не побажанням.

**Як працює під капотом.**

**Скільки викликів робить метрика.** Документація RAGAS не публікує точну кількість викликів на
метрику — це залежить від вмісту зразка. Але її можна вивести з **описаних кроків**. Нижче — оцінка
на тестовому наборі з 8 кейсів і `k = 2` знайдених чанки, де кожна відповідь і кожен еталон мають
рівно одне твердження:

| Метрика | Правило з документації | Викликів на 8 зразків | На зразок |
|---|---|---|---|
| `Faithfulness` | 1 видобуток тверджень + перевірка кожного твердження | 16 | 2.00 |
| `ContextRecall` | 1 розбір еталона на твердження + перевірка кожного | 16 | 2.00 |
| `ContextPrecision` | порівняння кожного чанка (два чанки на зразок) | 16 | 2.00 |
| `AnswerRelevancy` | 1 генерація набору зворотних питань (ембединги — не виклики судді) | 8 | 1.00 |
| **Разом** | | **56** | **7.00** |

Це **нижня оцінка, виведена з описаних кроків**, а не підтверджена документацією цифра: реальна
реалізація може батчити кілька тверджень в один виклик або, навпаки, робити додаткові службові
виклики. Станом на 09.2026 точну кількість викликів на метрику в документації RAGAS підтвердити не
вдалося. Головний висновок від цього не залежить: **метрика коштує не одного виклику, а
`1 + кількість тверджень`**, тому довга відповідь дорожча за коротку при тій самій кількості зразків.

**Як рахувати гроші.** RAGAS надає для цього окремий механізм. За замовчуванням `evaluate()` **не**
рахує токени, і документація пояснює причину: «This is because LangChain's LLMs do not always return
information about token usage in a uniform way». Розв'язок — `TokenUsageParser`, функція, яка
перетворює результат генерації на об'єкт `TokenUsage`. Для OpenAI є готовий парсер:
`get_token_usage_for_openai(llm_result)`. Далі:

```python
from ragas import evaluate
from ragas.cost import get_token_usage_for_openai

results = evaluate(
    eval_dataset[:5],
    metrics=[metric],
    llm=gpt4o,
    token_usage_parser=get_token_usage_for_openai,
)
results.total_tokens()
results.total_cost(cost_per_input_token=5 / 1e6, cost_per_output_token=15 / 1e6)
```

Документований вивід цього прикладу — це найкращий доступний **якір для оцінки бюджету**, бо містить
і кількість зразків, і кількість токенів, і ціну:

```text
зразків: 5, метрика: AspectCriticWithReference (1 виклик на зразок)
TokenUsage(input_tokens=5463, output_tokens=355, model='')
results.total_cost(cost_per_input_token=5 / 1e6, cost_per_output_token=15 / 1e6) -> 0.03264
```

Перевірка арифметики: `5463 * 5 / 1e6 + 355 * 15 / 1e6 = 0.027315 + 0.005325 = 0.03264`. Обидві
ціни ($5 і $15 за мільйон) узято з документації RAGAS для GPT-4o. Звідси — **на один виклик судді
припадає приблизно 1093 вхідних і 71 вихідний токен** (`5463 / 5` і `355 / 5`).

**Приклад.** тепер підставимо це в реальні ціни Claude станом на 09.2026 (з `research/econ/anthropic_pricing.md`,
джерело — сторінка Pricing у документації Anthropic):

| Модель-суддя | Ціна, вхід / вихід за MTok | 8 зразків (56 викликів) | 500 зразків | 5000 зразків | 500 зразків × 3 повтори |
|---|---|---|---|---|---|
| Claude Haiku 4.5 | $1 / $5 | $0.08107 | $5.07 | $50.67 | $15.20 |
| Claude Sonnet 5 | $2 / $10 | $0.16213 | $10.13 | $101.33 | $30.40 |
| Claude Opus 5 | $5 / $25 | $0.40533 | $25.33 | $253.33 | $76.00 |

Читається це так: на 8 зразках оцінювання коштує **менше десяти центів**, навіть на найдорожчій
моделі. На 5000 зразків у три прогони — уже десятки й сотні доларів. Головне — зрозуміти, що
**ціна лінійна за кількістю зразків і кількістю метрик**, і саме тому в CI ганяють 20–50 зразків, а
повний набір — уночі. Дві реальні пастки цієї арифметики:

1. **Зміна моделі-судді на новішу може коштувати дорожче без зміни ціни.** Окрема примітка до таблиці
   цін Anthropic: «Claude 4.7 and later models and Claude Mythos Preview use a newer tokenizer that
   contributes to their improved performance on a wide range of tasks. This tokenizer produces
   approximately 30% more tokens for the same text». Той самий тестовий набір на новішій моделі
   дасть приблизно на 30% більше токенів — тобто бюджет треба перераховувати при апгрейді судді.
2. **Ціна може знизитися посеред кварталу.** Для Claude Sonnet 5 у документації є примітка, що
   початкова ціна $2/$10 стала стандартною, а заплановане підвищення до $3/$15 скасовано. Зашивати
   ціну в код константою — означає тихо переплачувати або тихо недооцінювати; беріть її з джерела
   під час прогону.

**Детермінізм: чому два прогони дають різні числа.** Документація RAGAS формулює причину прямо:
«These metrics can be somewhat non-deterministic as the LLM might not always return the same result
for the same input». Наслідок не в тому, що окрема оцінка «неправильна», а в тому, що **середнє по
набору коливається від прогону до прогону**, і це коливання масштабується як `1/√n`. Нижче —
симуляція: суддя, який у 90% випадків згоден з експертом (`p = 0.90`), оцінює набір із `n` зразків;
2000 прогонів, фіксований сід.

```text
n= 20  sd=0.0671  p2.5=0.750  p97.5=1.000  розмах=0.250
n=100  sd=0.0300  p2.5=0.840  p97.5=0.950  розмах=0.110
n=500  sd=0.0134  p2.5=0.874  p97.5=0.926  розмах=0.052
```

Прочитаймо таблицю: на наборі з **20 зразків** той самий конвеєр без жодної зміни дає середню оцінку
від 0.75 до 1.00 — розкид 0.25. Будь-яка «регресія» на такому наборі менша за 0.25 — це не сигнал.
На 500 зразків розкид звужується до 0.052, і різниця 0.05 стає помітною. Теоретичне значення
стандартного відхилення `√(p(1−p)/n)` збігається з емпіричним: для `n = 20` це 0.0671, для
`n = 500` — 0.0134.

Скільки ж зразків потрібно, щоб **надійно** побачити різницю? Для порівняння двох часток із
двостороннім тестом на рівні α = 0.05 і потужності 0.80:

```text
n = 2 · (z_0.975 + z_0.80)² · p · (1 − p) / Δ²
  = 2 · (1.959963985 + 0.8416212336)² · 0.09 / Δ²
  = 2 · 7.848880 · 0.09 / Δ²

Δ = 0.10  ->  n =  142 зразки на варіант
Δ = 0.05  ->  n =  566 зразків на варіант
Δ = 0.02  ->  n = 3532 зразки на варіант
```

`z`-квантилі — стандартні значення нормального розподілу (1.959963985 для 0.975 і 0.8416212336 для
0.80). Практичний висновок жорсткий: **щоб побачити покращення на 5 процентних пунктів, потрібно
566 зразків на кожен варіант, тобто 1132 зразки й приблизно 7924 виклики судді** за 7 викликів на
зразок. На Claude Haiku 4.5 це $11.47, на Claude Sonnet 5 — $22.94 за одне порівняння. Без цієї
арифметики команда «вимірює» різницю в межах шуму й ухвалює рішення на випадкових числах.

**Типові помилки.**

1. **Порівнювати два прогони без урахування розкиду.** Різниця 0.02 на наборі з 20 зразків — це шум
   (розкид 0.25). Документація RAGAS для об'єктивності метрики радить незалежну розмітку кількома
   людьми: «A high inter-rater agreement (≥80%) indicates greater objectivity» — і застосовувати цей
   самий критерій до судді.
2. **Не калібрувати суддю.** Документація RAGAS присвячує цьому окремий how-to з назвою, яка все
   пояснює: «A misaligned judge is like a compass pointing the wrong way — every improvement you make
   based on its guidance moves you further from your goal». Процедура: узяти набір із **експертними**
   бінарними мітками (`pass`/`fail`), порахувати метрику `judge_alignment` (збіг рішення судді з
   рішенням людини), подивитися на розбіжності, поправити промпт судді, перерахувати. Документація
   вказує обсяг: «a representative sample (100-200 examples covering diverse scenarios) is sufficient
   for reliable alignment».
3. **Використовувати `DiscreteMetric` без `allowed_values`.** Документована сигнатура:
   `DiscreteMetric(name="accuracy", prompt="...", allowed_values=["pass", "fail"])`. Без явного списку
   значень суддя поверне «майже pass» або «частково», і агрегація зламається.
4. **Не платити за тестовий набір у бюджеті.** Генерація набору — теж LLM-виклики (генератор і його
   ембединги). Станом на 09.2026 документація RAGAS **не** публікує оцінку вартості генерації
   тестового набору — підтвердити її не вдалося; рахуйте окремо через `token_usage_parser`.
5. **Не помітити, що гейт почав проходити через деградацію судді.** Документація OpenAI описує
   зворотний бік: «Models being trained sometimes learn to exploit weaknesses in model graders, also
   known as "grader hacking" or "reward hacking." You can detect this by checking the model's
   performance across model grader evals and expert human evals». Для RAG це означає: якщо оцінки
   судді зростають, а скарги користувачів — ні, треба перевірити вибірку вручну.
6. **Забувати про мову.** Документація RAGAS має окремий how-to з адаптації метрик до іншої мови
   (`metrics_language_adaptation`). Метрика, відкалібрована на англійських промптах, на українському
   тексті поводитиметься інакше — промпти метрик треба адаптувати й перевіряти збіг із експертом
   заново.

**Альтернативи.**

| Проблема | Прийом | Що дає |
|---|---|---|
| Недетермінованість судді | Фіксація `seed`, `temperature=0`, фіксована версія моделі й промпту метрики | Відтворюваність у межах однієї версії судді |
| Шум у середньому | Збільшення `n` за формулою вище + звіт довірчого інтервалу | Розрізнення сигналу й шуму |
| Ціна | 20–50 зразків у CI, повний набір уночі; дешевий суддя | Бюджет під контролем |
| Систематичне зміщення | Калібрування судді на 100–200 експертних мітках | Збіг із людськими рішеннями |
| Залежність від одного судді | Два судді та перевірка збігу між ними | Ловить випадки, де суддя «зламався» |
| Ціна на великому обсязі | Non-LLM-метрики (`IDBased*`, `NonLLMContextRecall`) у CI, LLM — за розкладом | Детермінований гейт безкоштовно |

**Джерела**

- [RAGAS — Overview of Metrics](https://docs.ragas.io/en/stable/concepts/metrics/overview/) — поділ на end-to-end / component-level / business метрики, LLM-based (`MetricWithLLM`) проти non-LLM-based (`Metric`), `discrete_metric` / `numeric_metric` / `ranking_metric`, п'ять принципів проєктування метрик, критерій міжекспертної згоди ≥80% (збережено в `research/06b/ragas_metrics_overview.txt`)
- [RAGAS — Faithfulness](https://docs.ragas.io/en/stable/concepts/metrics/available_metrics/faithfulness/) — формула `supported claims / total claims`, документований приклад з Ейнштейном (1/2 = 0.5), `FaithfulnesswithHHEM` з параметрами `device` і `batch_size` (збережено в `research/06b/ragas_metric_faithfulness.txt`)
- [RAGAS — Response Relevancy](https://docs.ragas.io/en/stable/concepts/metrics/available_metrics/answer_relevance/) — 3 зворотні питання (`strictness`), формула середнього косинуса, застереження про діапазон −1…1, вихід 0.9165088378587264 (збережено в `research/06b/ragas_metric_answer_relevance.txt`)
- [RAGAS — Context Precision](https://docs.ragas.io/en/stable/concepts/metrics/available_metrics/context_precision/) — формула `ContextPrecision@K`, чутливість до рангу (0.9999999999 проти 0.49999999995), `ContextUtilization`, `LLMContextPrecisionWithReference`, `LLMContextPrecisionWithoutReference`, `NonLLMContextPrecisionWithReference` (потребує `rapidfuzz`), `IDBasedContextPrecision` (збережено в `research/06b/ragas_metric_context_precision.txt`)
- [RAGAS — Context Recall](https://docs.ragas.io/en/stable/concepts/metrics/available_metrics/context_recall/) — вимога `reference`, формула через твердження, `NonLLMContextRecall` із `reference_contexts`, `IDBasedContextRecall` (збережено в `research/06b/ragas_metric_context_recall.txt`)
- [RAGAS — Factual Correctness](https://docs.ragas.io/en/stable/concepts/metrics/available_metrics/factual_correctness/) — NLI, режими `precision` / `recall` / `f1` (типово `f1`), приклад 0.67 проти 1.0 (збережено в `research/06b/ragas_factual_correctness.txt`)
- [RAGAS — Noise Sensitivity](https://docs.ragas.io/en/stable/concepts/metrics/available_metrics/noise_sensitivity/) — параметр `mode="irrelevant"`, документований вихід 0.3333333333333333 (збережено в `research/06b/ragas_metrics_noise_sensitivity.txt`)
- [RAGAS — Rubric-Based Evaluation](https://docs.ragas.io/en/stable/concepts/metrics/available_metrics/rubrics_based/) — `DomainSpecificRubrics` і `InstanceSpecificRubrics`, ключі `score1_description`…`score5_description`, прапорець `with_reference` (збережено в `research/06b/ragas_rubrics_based.txt`)
- [RAGAS — Evaluation Sample](https://docs.ragas.io/en/stable/concepts/components/eval_sample/) — поля `SingleTurnSample` (`user_input`, `retrieved_contexts`, `response`, `reference`, `rubric`) і `MultiTurnSample` (збережено в `research/06b/ragas_eval_sample.txt`)
- [RAGAS — Evaluate a simple RAG system](https://docs.ragas.io/en/stable/getstarted/rag_eval/) — повний цикл «зібрати дані → `EvaluationDataset.from_list` → `evaluate(...)`», документований вихід `{'context_recall': 1.0000, 'faithfulness': 0.8571, 'factual_correctness': 0.7280}` (збережено в `research/06b/ragas_getstarted_rag_eval.txt`)
- [RAGAS — Testset Generation for RAG](https://docs.ragas.io/en/stable/concepts/test_data_generation/rag/) — single-hop / multi-hop і specific / abstract запити, граф знань, `DocumentSplitter`, `NERExtractor`, `JaccardSimilarityBuilder`, `apply_transforms`, `Parallel`, сценарії (`Nodes`, `Query Length`, `Query Style`, `Persona`) (збережено в `research/06b/ragas_test_data_generation_rag.txt`)
- [RAGAS — Testset Generation for RAG (how-to)](https://docs.ragas.io/en/stable/getstarted/rag_testset_generation/) — `LangchainLLMWrapper`, `OpenAIEmbeddings`, `LangchainEmbeddingsWrapper` для генератора й ембедингів (збережено в `research/06b/ragas_rag_testset_generation.txt`)
- [RAGAS — Understand Cost and Usage of Operations](https://docs.ragas.io/en/stable/howtos/customizations/metrics/_cost/) — `TokenUsageParser`, `get_token_usage_for_openai`, `TokenUsage(input_tokens=5463, output_tokens=355)`, `total_tokens()`, `total_cost(...) -> 0.03264` (збережено в `research/06b/ragas_cost_customization.txt`)
- [RAGAS — How to Align an LLM as a Judge](https://docs.ragas.io/en/stable/howtos/applications/align-llm-as-judge/) — набір EvalsBench із експертними мітками, `DiscreteMetric(allowed_values=["pass", "fail"])`, метрика `judge_alignment`, декоратор `@experiment`, обсяг 100–200 прикладів (збережено в `research/06b/ragas_align_llm_as_judge.txt`)
- [RAGAS — Choose evaluator LLM](https://docs.ragas.io/en/stable/extra/components/choose_evaluator_llm/) — варіанти підключення оцінювача (OpenAI, AWS Bedrock, Google AI Studio, Vertex AI) (збережено в `research/06b/ragas_choose_evaluator_llm.txt`)
- [RAGAS — Traditional metrics](https://docs.ragas.io/en/stable/concepts/metrics/available_metrics/traditional/) — детерміновані метрики: BLEU, ROUGE, CHRF (збережено в `research/06b/ragas_traditional_metrics.txt`)
- [RAGAS — PyPI JSON API](https://pypi.org/pypi/ragas/json) — версія 0.4.3 від 13.01.2026, `requires_python >= 3.9`, повний список залежностей (збережено в `research/06b/pypi_ragas.json`)
- [RAGAS — sitemap](https://docs.ragas.io/en/stable/sitemap.xml) — перелік актуальних шляхів документації (збережено в `research/06b/ragas_sitemap.xml`)
- [Anthropic — Define success criteria and build evaluations](https://platform.claude.com/docs/en/test-and-evaluate/develop-tests) — критерії успіху (specific / measurable / achievable / relevant), принципи дизайну евалуацій (task-specific, automate, «prioritize volume over quality»), Likert-шкали й експертні рубрики, exact-match приклад (збережено в `research/06b/judge_anthropic_develop_tests.txt`)
- [OpenAI — Graders](https://platform.openai.com/docs/guides/graders) — схема `score_model` grader, `pass_threshold`, `range`, `sampling_params` (`seed`, `top_p`, `temperature`, `reasoning_effort`), формат виводу `{"result": float, "steps": [...]}`, обмеження моделей і параметрів, настанова «How to write grader prompts», «Grader hacking» (збережено в `research/06b/judge_openai_graders.txt`)
- [OpenAI — Working with evals](https://platform.openai.com/docs/guides/evals) — `data_source_config`, `testing_criteria`, `string_check` grader, примітка про депрекацію платформи Evals і перехід на `graders` (збережено в `research/06b/judge_openai_evals.txt`)
- [Anthropic — Pricing](https://platform.claude.com/docs/en/about-claude/pricing) — Claude Haiku 4.5 $1/$5, Claude Sonnet 5 $2/$10, Claude Opus 5 $5/$25 за MTok, примітка про новий токенізатор (+≈30% токенів для моделей 4.7 і новіших) (збережено в `research/econ/anthropic_pricing.md`)

Суміжні розділи: [16](16-rag.md) — сам конвеєр RAG, [23](23-observability.md) — спостережуваність
і онлайн-оцінки, [24](24-eval.md) — евалюація як процес: golden set, LLM-як-суддя, red teaming, CI-гейт.
