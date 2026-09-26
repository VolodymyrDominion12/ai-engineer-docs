## 2. Як насправді працює інференс LLM: токени, KV-кеш, латентність

Ви відправляєте запит і чекаєте. Через 300 мс з'являється перше слово, далі текст сиплеться
рівним потоком. Рахунок у кінці місяця виявляється вп'ятеро більшим, ніж ви очікували, і винен
не «дорогий API», а конкретний механізм: генерація одного токена вимагає прочитати з пам'яті всі
ваги моделі, а пам'ять під час генерації займає не тільки модель, а й кеш уваги.

Розділ не дублює [розділ 3](#3-токенізація-на-практиці-bpe-спецтокени-chat-шаблони) (BPE,
спецтокени) і [розділ 9](#9-prompt-caching-економія-й-діагностика) (практика префіксного кешу):
тут — рівень нижче, між відправкою запиту й першим токеном. Словник:

| Термін | Що означає | Де |
|---|---|---|
| Префіл (prefill) / декодування (decode) | Паралельна обробка входу / генерація по одному токену | 2.2 |
| TTFT / TPOT | Час до першого токена / час на кожен наступний токен | 2.2 |
| KV-кеш | Збережені тензори ключів і значень з усіх шарів | 2.3 |
| PagedAttention | Зберігання KV-кешу блоками фіксованого розміру | 2.3 |
| Continuous batching | Підмішування нових запитів у батч на кожній ітерації | 2.2, 2.5 |
| Context rot | Деградація точності зі зростанням контексту | 2.4 |

Три факти, які варто тримати в голові далі: обробка промпту паралельна, генерація —
послідовна, тому вхід і вихід коштують за різними законами (2.2); декодування впирається не в
обчислення, а в пропускну здатність пам'яті, тому швидкість визначають ваги моделі плюс KV-кеш
(2.3); ціна виходу вища за ціну входу в усіх великих провайдерів — від 3x до 8x (2.5).

### 2.1 Токен як одиниця білінгу

**Що це.** Токен — одиниця, в якій провайдер рахує і гроші, і ліміти швидкості, і межі
контексту. У білінгу токени не однорідні: `input_tokens`, `output_tokens`,
`cache_creation_input_tokens` і `cache_read_input_tokens` — це **чотири різні категорії з
різними цінами**, і саме тому сума «вхід + вихід» не дорівнює рахунку.

**Навіщо це знати.** Читання поля `usage` — це єдиний спосіб зрозуміти, за що ви заплатили.
Помилка в один коефіцієнт тут коштує дорого: ті самі 200 000 токенів коштують $0.40 як
звичайний вхід, $0.04 як кеш-влучання і $0.50 як запис у кеш на 5 хвилин (ціни Claude Sonnet 5,
`research/02/pricing.md`). Один і той самий текст — три різні ціни з різницею в 12 разів.

**Як працює під капотом.**

Провайдер виставляє рахунок за токени, які модель реально обробила. У відповіді Messages API є
об'єкт `usage`, і кожне його поле — окрема стаття витрат:

```json
{
  "usage": {
    "input_tokens": 50,
    "cache_creation_input_tokens": 0,
    "cache_read_input_tokens": 200000,
    "output_tokens": 812
  }
}
```

`input_tokens` тут **не означає «всі вхідні токени»**. Документація Claude API
(`research/02/rate-limits.md`) формулює це прямо:

```text
total_input_tokens = cache_read_input_tokens + cache_creation_input_tokens + input_tokens
```

`input_tokens` — це тільки те, що йде **після останнього кеш-брейкпоінта**. Якщо ви закешували
документ на 200 000 токенів і поставили питання на 50 токенів, у полі `input_tokens` буде `50`,
хоча модель обробила 200 050 токенів. Хто читає `input_tokens` як «розмір промпту», той
недооцінює контекст у тисячі разів — і дивується, чому впирається в межу вікна.

Другий шар: **токени залежать від токенізатора, а токенізатор змінюється між моделями**.
Документація з підрахунку токенів (`research/02/token-counting.md`) фіксує: «Claude 4.7 and later
models... use a newer tokenizer. The same input text produces approximately 30 percent more tokens
than on earlier models». Той самий промпт на новій моделі дає **+30% токенів**, тому документація
забороняє переносити вимірювання: «Recount prompts against the model you plan to use».

Третій шар — токени вимірюються не тільки в грошах. Ліміти Claude API задані в трьох вимірах
(`research/02/rate-limits.md`): RPM, ITPM і OTPM. Для стартового тира Opus 5 і Sonnet 5: 1 000
RPM, 2 000 000 ITPM, 400 000 OTPM. Межа по виходу в п'ять разів жорсткіша — те саме відображення
асиметрії префілу й декодування.

Четверте: роздуми (thinking) — це **вихідні** токени. Вони входять у `max_tokens`, оплачуються за
ціною виходу й рахуються в OTPM; на моделях, які зберігають попередні thinking-блоки, ці блоки
потім повертаються як вхідні й оплачуються як вхід (`research/02/context-windows.md`).

Тепер зберемо з цього арифметику. Ціни — з `research/02/pricing.md` (09.2026):

```python
# Ціни за мільйон токенів. Джерело: research/02/pricing.md (Anthropic, 09.2026).
PRICES = {
    # model: (input, output, cache_write_5m, cache_write_1h, cache_read)
    "claude-sonnet-5": (2.0, 10.0, 2.50, 4.0, 0.20),
    "claude-opus-5": (5.0, 25.0, 6.25, 10.0, 0.50),
    "claude-haiku-4-5": (1.0, 5.0, 1.25, 2.0, 0.10),
}

# Реальний розклад usage: 200 000 токенів документа з кешу + 50 токенів питання.
usage = {
    "input_tokens": 50,
    "cache_creation_input_tokens": 0,
    "cache_read_input_tokens": 200_000,
    "output_tokens": 812,
}


def cost_usd(model: str, usage: dict) -> float:
    inp, out, cw5, cw1h, read = PRICES[model]
    return (
        usage["input_tokens"] / 1e6 * inp
        + usage["cache_creation_input_tokens"] / 1e6 * cw5
        + usage["cache_read_input_tokens"] / 1e6 * read
        + usage["output_tokens"] / 1e6 * out
    )


total_input = (
    usage["input_tokens"]
    + usage["cache_creation_input_tokens"]
    + usage["cache_read_input_tokens"]
)
print(f"запит обробив вхідних токенів: {total_input:,}")
print(f"з них у полі input_tokens:     {usage['input_tokens']:,} ({usage['input_tokens']/total_input*100:.2f}%)")
print()
for model in PRICES:
    print(f"{model:18} ${cost_usd(model, usage):.5f}")

# Скільки коштував би той самий запит без кешу — тобто як звичайний вхід.
no_cache = dict(usage, input_tokens=total_input, cache_read_input_tokens=0)
print()
print("без кешу (200 050 токенів як звичайний вхід):")
for model in PRICES:
    print(f"{model:18} ${cost_usd(model, no_cache):.5f}")
```

Фактичний вивід:

```
запит обробив вхідних токенів: 200,050
з них у полі input_tokens:     50 (0.02%)

claude-sonnet-5    $0.04822
claude-opus-5      $0.12055
claude-haiku-4-5   $0.02411

без кешу (200 050 токенів як звичайний вхід):
claude-sonnet-5    $0.40822
claude-opus-5      $1.02055
claude-haiku-4-5   $0.20411
```

Різниця між двома варіантами — 8.5x на Sonnet 5. Причина — ставка `cache_read`: 10% від базової
ціни входу. Але різниця **не** 10x, і це видно з розкладу того самого запиту на статті:

| Категорія | Токенів | $/MTok | Частка рахунку |
|---|---|---|---|
| `input_tokens` | 50 | 2.00 | 0.2% |
| `cache_read_input_tokens` | 200 000 | 0.20 | 83.0% |
| `output_tokens` | 812 | 10.00 | 16.8% |
| **Разом** | 200 862 | — | **$0.04822** |

812 вихідних токенів — це 0.4% усіх токенів запиту, але 16.8% рахунку. Співвідношення
«токени × ціна» тут важливіше за кількість токенів: саме тому 2.5 присвячений окремо
арифметиці, а не «зменшенню промптів».

І ще один наслідок, який не очевидний, поки не подивитися на структуру `usage`. Ліміт ITPM
рахує **не всі вхідні токени**:

| Категорія токенів | Входить у рахунок | Входить у ліміт ITPM | Ціна (Sonnet 5) |
|---|---|---|---|
| `input_tokens` | так | так | $2.00 / MTok |
| `cache_creation_input_tokens` | так | так | $2.50 / MTok (5 хв) |
| `cache_read_input_tokens` | так | **ні** (для більшості моделей) | $0.20 / MTok |
| `output_tokens` | так | в OTPM, не в ITPM | $10.00 / MTok |

Документація дає числовий приклад (`research/02/rate-limits.md`): «With a 2,000,000 ITPM limit
and an 80% cache hit rate, you could effectively process 10,000,000 total input tokens per minute
(2M uncached + 8M cached), because cached tokens don't count toward your rate limit». Кеш — це не
лише знижка 90%, а й **п'ятикратне розширення стелі швидкості**.

**Типові помилки**

- **Читати `input_tokens` як розмір промпту.** Правильно: сума трьох полів. Приклад вище: 50
  проти 200 050 — помилка в 4000 разів.
- **Переносити вимірювання токенів між моделями.** Зміна токенізатора дає ≈+30% токенів на тому
  самому тексті. Кошторис, зроблений на старій моделі, занижений.
- **Вважати, що `max_tokens` впливає на ліміти.** Документація прямо: «The `max_tokens` parameter
  does not factor into OTPM rate limit calculations». Великий `max_tokens` не з'їдає квоту.
- **Забувати, що роздуми — це вихід.** Вони входять у `max_tokens`, у рахунок за ціною виходу й у
  ліміт OTPM.
- **Порівнювати ціни `$/MTok` між провайдерами без урахування токенізатора.** NVIDIA формулює це
  як проблему порівняння взагалі: «Different LLMs may use different tokenizers, and thus,
  comparing output tokens between them may not be straightforward» (`research/02/nvidia-mastering-llm-inference-optimization.txt`).
  Однакова ціна за токен у двох моделей не означає однакової ціни за сторінку тексту.

**Альтернативи.** Токен як одиниця білінгу — не єдиний можливий підхід, і провайдери це
використовують:

| Підхід | Хто і як | Коли вигідніший |
|---|---|---|
| Токени за прайс-листом | Claude, OpenAI, Gemini, DeepSeek | Звичайні навантаження з передбачуваним обсягом |
| Знижка за кешований вхід | 0.1x базової ціни (Claude), $0.003/MTok (DeepSeek flash, cache hit) | Повторюваний префікс: інструкції, документи, історія |
| Batch API −50% | Claude, OpenAI | Асинхронні масові задачі, де затримка не критична |
| Одиниці споживання провайдера | Claude Consumption Units (CCU) на маркетплейсах | Закупівля через AWS/Microsoft Foundry |
| Погодинна оренда GPU | Локальний інференс, vLLM | Стабільне навантаження, де вигідніша утилізація, а не перелік токенів |

Останній рядок важливий: якщо ви платите за GPU-години, «токен» перестає бути одиницею витрат і
стає одиницею пропускної здатності — ви рахуєте не рахунок, а те, скільки запитів устигнете
обслужити за годину.

### 2.2 Префіл vs декодування, TTFT і tokens/sec

**Що це.** Генерація відповіді складається з двох фаз із принципово різною природою. **Префіл**
(prefill) — обробка всього вхідного промпту: усі токени відомі наперед, тому вони обробляються
паралельно. **Декодування** (decode) — генерація вихідних токенів по одному: кожен наступний
токен залежить від попереднього, тому паралелізму немає.

Ці дві фази дають дві різні метрики, які легко переплутати:

| Метрика | Що вимірює | Чим визначається | Хто її відчуває |
|---|---|---|---|
| TTFT (time to first token) | Час від запиту до першого токена відповіді | Довжиною промпту, чергою, кешем | Користувач у момент очікування |
| TPOT (time per output token) | Час на кожен наступний токен | Пропускною здатністю пам'яті, розміром батчу | Користувач під час читання |
| ITL (inter-token latency) | Інтервал між сусідніми виданими токенами | Те саме, але на рівні стріму | Плавність «друкарської машинки» |
| Загальна затримка | TTFT + TPOT × кількість вихідних токенів | Усім переліченим | Час до повної відповіді |
| Пропускна здатність | Токенів на секунду на весь сервіс | Розміром батчу, утилізацією GPU | Ваш рахунок за GPU-години |

**Навіщо це знати.** Формула загальної затримки визначає, куди взагалі має сенс прикладати
інженерні зусилля. Документація OpenAI з оптимізації затримки
(`research/02/openai-latency-guide.txt`) дає два числа, які варто запам'ятати:

> «Generating tokens is almost always the highest latency step when using an LLM: as a general
> heuristic, cutting 50% of your output tokens may cut ~50% of your latency.»

> «While reducing the number of input tokens does result in lower latency, this is not usually a
> significant factor—cutting 50% of your prompt may only result in a 1–5% latency improvement.»

Скорочення промпту вдвічі дає 1–5%, а скорочення відповіді вдвічі — близько 50%. Це не
інтуїтивно: промпт може бути в сто разів довшим за відповідь, але впливати на затримку в рази
менше. Причина — у фізиці двох фаз.

**Як працює під капотом.**

NVIDIA описує різницю через тип матричної операції
(`research/02/nvidia-mastering-llm-inference-optimization.txt`):

> «In the prefill phase... because the full extent of the input is known, at a high level this is
> a matrix-matrix operation that's highly parallelized. It effectively saturates GPU utilization.»

> «In the decode phase... This is like a matrix-vector operation that underutilizes the GPU compute
> ability compared to the prefill phase. The speed at which the data (weights, keys, values,
> activations) is transferred to the GPU from memory dominates the latency... In other words, this
> is a memory-bound operation.»

Розкладімо це на наслідки:

| Властивість | Префіл | Декодування |
|---|---|---|
| Скільки токенів за один прохід | Усі вхідні одразу | Рівно один |
| Тип операції | Матриця × матриця | Матриця × вектор |
| Що обмежує швидкість | Обчислювальна здатність (compute-bound) | Пропускна здатність пам'яті (memory-bound) |
| Як масштабується з довжиною входу | Лінійно за токенами, квадратично за увагою | Не залежить від довжини входу |
| Що допомагає | Кеш префіксу, батчинг префілів, шардинг | Батчинг, квантизація ваг, спекулятивне декодування |
| Що робить гірше | Довгий промпт, відсутність кешу | Великий батч (зростає TPOT) |

Документація Databricks (`research/02/databricks-llm-inference-performance.txt`) дає точну
формулу затримки й конкретне калібрування TPOT:

```text
latency = (TTFT) + (TPOT) * (the number of tokens to be generated)
```

> «For example, a TPOT of 100 milliseconds/tok would be 10 tokens per second per user, or ~450
> words per minute, which is faster than a typical person can read.»

450 слів за хвилину при TPOT 100 мс — це та межа, за якою подальше прискорення генерації
перестає бути помітним для людини. Документація vLLM (`research/02/vllm-metrics-design.txt`)
уточнює, як TPOT вимірюють на практиці:

```text
vllm:request_time_per_output_token_seconds — Per-request Time Per Output Token (TPOT) in seconds,
computed as `(end-to-end latency - TTFT) / (number of output tokens - 1)`.
```

Зверніть увагу на `- 1`: перший токен виключено, бо він уже врахований у TTFT. Хто рахує
`latency / n_output`, той отримує завищений TPOT на коротких відповідях.

Тепер — чому декодування memory-bound. Databricks уводить метрику MBU (Model Bandwidth
Utilization):

```text
MBU = (achieved memory bandwidth) / (peak memory bandwidth),
achieved memory bandwidth = ((total model parameter size + KV cache size) / TPOT)
```

Це і є пояснення, чому **квантизація прискорює генерацію**: ваги в INT8 займають удвічі менше
байтів, а читати з пам'яті треба саме байти. Той самий механізм пояснює залежність від заліза:
NVIDIA наводить, що H100-80GB має у 2.15x більшу смугу, ніж A100-40GB, і це дає «latency is 36%
lower at batch size 1 and 52% lower at batch size 16 for 4x systems».

Що робити з батчами. Батчинг — головний інструмент підвищення пропускної здатності, але він
**підвищує** TPOT кожного окремого запиту. Databricks дає граничний приклад: «if we maximize
throughput with a batch size of 64, latency increases by 4x while throughput increases by 14x».
Це і є фундаментальний компроміс: пропускна здатність проти затримки.

Ось дані з таблиці 2 джерела (MPT-7B, FasterTransformers, запити 512 вхідних / 64 вихідних
токенів) — реальні вимірювання, не модель:

Пропускна здатність (req/sec) за Table 2 джерела — MPT-7B, 512 вхідних і 64 вихідних токенів:

| Конфігурація | batch 1 | batch 4 | batch 8 | batch 16 | batch 32 | batch 64 | batch 128 |
|---|---|---|---|---|---|---|---|
| 1 × A10 | 0.4 | 1.4 | 2.3 | 3.5 | OOM | OOM | OOM |
| 1 × A100 | 0.9 | 3.2 | 5.3 | 8.0 | 10.5 | 12.5 | — |
| 4 × A100 | 1.7 | 6.2 | 11.5 | 18.0 | 25.0 | 33.0 | 36.5 |

Кратність до batch=1 і приріст від кожного подвоєння батчу:

| Конфігурація | ×4 | ×8 | ×16 | ×32 | ×64 | ×128 | 1→4 | 4→8 | 32→64 | 64→128 |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 × A10 | 3.5x | 5.7x | 8.8x | — | — | — | 3.50x | 1.64x | — | — |
| 1 × A100 | 3.6x | 5.9x | 8.9x | 11.7x | 13.9x | — | 3.56x | 1.66x | 1.19x | — |
| 4 × A100 | 3.6x | 6.8x | 10.6x | 14.7x | 19.4x | 21.5x | 3.65x | 1.85x | 1.32x | 1.11x |

Друга таблиця — найповчальніша. Подвоєння батчу з 1 до 4 дає 3.5–3.7x пропускної здатності, з 4
до 8 — уже 1.6x, а з 64 до 128 — лише 1.1x. Databricks пояснює, чому: «After a certain batch
size, i.e., when we cross to the compute bound regime, every doubling of batch size just increases
the latency without increasing throughput». Після переходу в compute-bound режим ви платите
затримкою і не отримуєте нічого.

Другий важіль — **padding-free батчинг**. Наївний батчинг вимагає однакової довжини промптів,
тому коротші доповнюються заповнювачем. HF-блог
(`research/02/hf-blog-continuous-batching.txt`) рахує ціну: «dynamically introducing a prompt of n
initial tokens in the batch requires (n−1)(B−1) padding tokens. For instance, with B=8 and n=100,
we'd need 99×7=693 padding tokens». Далі — рішення:

> «the only way to batch prompts together is to concatenate them... This way of batching prompts
> together is called ragged batching (because sequence lengths are 'ragged' or uneven), and it
> offers the benefit of added throughput without introducing the need for padding tokens.»

Continuous batching = ragged batching + динамічне планування (dynamic scheduling): запит, що
завершився, негайно витісняється з батчу, а на його місце вставляється новий. Databricks оцінює
виграш: «It can achieve 10x-20x better throughput than dynamic batching». NVIDIA описує той самий
механізм під назвою in-flight batching: «the server runtime immediately evicts finished sequences
from the batch. It then begins executing new requests while other requests are still in flight».

Третій важіль, який прямо впливає на TTFT, — **chunked prefill**: довгий промпт ріжеться на
частини, щоб не блокувати декодування інших запитів. Документація Transformers
(`research/02/continuous-batching-transformers-doc.md`) дає межі параметра `max_batch_tokens`:
«A larger budget packs more prompt tokens into each prefill, which raises prefill throughput and
lowers time-to-first-token on prompt-heavy workloads... By default, `max_batch_tokens` is `8192`...
and it never falls below `256`».

Тепер зберемо модель затримки. Нижче — **синтетична модель, а не вимірювання**: формула взята з
Databricks, а коефіцієнти підібрані так, щоб відповідати типовим значенням TPOT із джерел. Такі
розрахунки потрібні, щоб відповісти на питання «де мій бюджет затримки», а не щоб передбачити
чужий сервіс.

```python
def latency_seconds(ttft_ms: float, tpot_ms: float, output_tokens: int) -> float:
    """Модель затримки з джерела: latency = TTFT + TPOT * n_output."""
    return ttft_ms / 1000 + tpot_ms / 1000 * output_tokens


print("Скільки важить TTFT у загальній затримці (TTFT 300 мс, TPOT 12 мс)")
print(f"{'вихід':>8} {'затримка':>10} {'декод':>9} {'частка TTFT':>12}")
for n_out in (50, 100, 500, 2_000, 8_000):
    total = latency_seconds(300, 12, n_out)
    decode = 12 * n_out / 1000
    print(f"{n_out:>8} {total:>9.2f}s {decode:>8.2f}s {300/1000/total*100:>11.1f}%")

print()
print("TPOT -> швидкість (токенів за секунду на одного користувача)")
for tpot in (5, 10, 20, 50, 100, 200):
    tps = 1000 / tpot
    print(f"  TPOT {tpot:>3} мс -> {tps:>6.1f} tok/s | {tps*60:>7.0f} токенів/хв = {tps*60/1.5:>6.0f} слів/хв")

```

Фактичний вивід:

```
Скільки важить TTFT у загальній затримці (TTFT 300 мс, TPOT 12 мс)
   вихід   затримка     декод  частка TTFT
      50      0.90s     0.60s        33.3%
     100      1.50s     1.20s        20.0%
     500      6.30s     6.00s         4.8%
    2000     24.30s    24.00s         1.2%
    8000     96.30s    96.00s         0.3%

TPOT -> швидкість (токенів за секунду на одного користувача)
  TPOT   5 мс ->  200.0 tok/s |   12000 токенів/хв =   8000 слів/хв
  TPOT  10 мс ->  100.0 tok/s |    6000 токенів/хв =   4000 слів/хв
  TPOT  20 мс ->   50.0 tok/s |    3000 токенів/хв =   2000 слів/хв
  TPOT  50 мс ->   20.0 tok/s |    1200 токенів/хв =    800 слів/хв
  TPOT 100 мс ->   10.0 tok/s |     600 токенів/хв =    400 слів/хв
  TPOT 200 мс ->    5.0 tok/s |     300 токенів/хв =    200 слів/хв
```

Перша таблиця відповідає на питання «чи варто оптимізувати TTFT»: на відповіді в 50 токенів
TTFT — третина затримки, на 2000 токенів — 1.2%, і робота над ним марна. Друга: TPOT 200 мс — це
200 слів за хвилину, повільніше за читання вголос, а TPOT 5 мс швидший за людину, тож подальше
прискорення нічого не додає.

Той самий механізм вимірюється метрикою MBU (Model Bandwidth Utilization) з джерела Databricks:
`MBU = (achieved memory bandwidth) / (peak memory bandwidth)`, де achieved — це
`(total model parameter size + KV cache size) / TPOT`. Для моделі 7B у fp16 (14 ГБ ваг) і пікової
смуги 2 ТБ/с:

| TPOT | Переміщено за секунду | MBU | Що це означає |
|---|---|---|---|
| 7 мс | 2.00 ТБ/с | 100% | Смуга вичерпана, швидше на цьому залізі не буде |
| 10 мс | 1.40 ТБ/с | 70% | Є запас, але невеликий |
| 14 мс | 1.00 ТБ/с | 50% | Приклад із джерела |
| 20 мс | 0.70 ТБ/с | 35% | Залізо простоює — шукайте вузьке місце в софті |
| 28 мс | 0.50 ТБ/с | 25% | Половина смуги не використана |

MBU нижче 50% означає, що прискорення можливе без заміни GPU. І навпаки: MBU близько 100% —
сигнал, що єдиний шлях далі це квантизація ваг або інше залізо.

Стрімінг не зменшує загальну затримку, але перетворює TTFT на час до першого видимого символу.
Claude API повідомляє вхідні токени в події `message_start`, вихідні — в `message_delta`
(`research/02/streaming.md`, `research/02/anthropic-streaming-doc.md`):

```text
event: message_start
data: {"type": "message_start", "message": {"id": "msg_...", "usage": {"input_tokens": 25, "output_tokens": 1}}}

event: content_block_delta
data: {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "Hello"}}

event: message_delta
data: {"type": "message_delta", "delta": {"stop_reason": "end_turn"}, "usage": {"output_tokens": 15}}
```

Документація застерігає: «The token counts shown in the `usage` field of the `message_delta`
event are *cumulative*» — тобто це накопичене значення, а не приріст. Хто сумує `output_tokens`
з кожного `message_delta`, той отримує квадратично завищену цифру.

**Типові помилки**

- **Рахувати TPOT як `latency / n_output`.** Правильна формула з vLLM:
  `(end-to-end latency - TTFT) / (number of output tokens - 1)`. Інакше перший токен
  зараховується двічі.
- **Сумувати кумулятивний `usage` з `message_delta`.** Це накопичене значення; беріть останнє.
- **Оптимізувати промпт, коли болить затримка.** За документацією OpenAI, −50% промпту = −1…5%
  затримки, −50% відповіді ≈ −50% затримки. Спершу скорочуйте вихід.
- **Міряти затримку на холодному кеші й робити висновки.** TTFT залежить від того, чи був
  префікс у кеші: документація Transformers позначає рядок «Prefix caching» як такий, що знижує
  TTFT (`research/02/continuous-batching-transformers-doc.md`).
- **Піднімати батч «щоб швидше».** Після переходу в compute-bound режим подвоєння батчу додає
  затримку і не додає пропускної здатності.
- **Вважати, що стрімінг прискорює генерацію.** Він не змінює TPOT; він змінює момент, коли
  користувач бачить перший символ.

**Альтернативи.** Якщо впираєтесь у затримку, важелі впорядковані за співвідношенням
«ефект / зусилля»:

| Важіль | Що зменшує | Ціна рішення | Обмеження |
|---|---|---|---|
| Скоротити вихід (verbosity, `max_tokens`, структуровані відповіді) | Загальну затримку прямо пропорційно | Безкоштовно | Обрізання може зламати відповідь |
| Стрімінг | Не затримку, а час до першого видимого символу | Безкоштовно | Не допомагає там, де відповідь потрібна цілою |
| Кеш префіксу | TTFT на повторюваних префіксах | 1.25x ціни входу за запис | Потрібен стабільний префікс (розділ 9) |
| Швидша модель | TTFT і TPOT | Нижча якість | Не завжди достатньо для задачі |
| Спекулятивне декодування | TPOT | Пам'ять під draft-модель | Потрібна сумісна пара моделей |
| Менший батч | TPOT одного запиту | Пропускну здатність сервісу | Дорожче за GPU-годину |

Про спекулятивне декодування варто сказати точніше, бо цифри часто перебільшують. HF-блог про
assisted generation (`research/02/hf-blog-assisted-generation.txt`) наводить: «Gets up to 3x
speedups in the presence of INT8 and up to 2x otherwise, when the model fits in the GPU memory» і
«If you're playing with models that do not fit in your GPU and are relying on memory offloading,
you can see up to 10x speedups». Тобто виграш залежить від того, наскільки ви вже вперлися в
пам'ять: якщо модель ледве вміщується й частина ваг підкачується з CPU, виграш найбільший.

### 2.3 KV-кеш і чому він визначає пам'ять під час інференсу

**Що це.** KV-кеш (key-value cache) — це збережені тензори ключів і значень з механізму уваги
для всіх уже оброблених токенів. Без нього модель перераховувала б увагу для всього контексту
на кожному новому токені. Документація Transformers описує це через маски: «For causal attention,
the mask prevents the model from attending to future tokens. Once a token is processed, its
representation never changes with respect to future tokens, which means K_past and V_past can be
cached and reused» (`research/02/cache-explanation-transformers-doc.md`).

Ключове слово — **causal**: кеш існує саме тому, що в причинній увазі минуле не змінюється.

**Навіщо це знати.** KV-кеш — це друга за величиною стаття витрат пам'яті під час інференсу
після самих ваг моделі, і саме він обмежує три речі одночасно: довжину контексту, розмір батчу
й кількість одночасних користувачів. NVIDIA формулює це прямо
(`research/02/nvidia-mastering-llm-inference-optimization.txt`):

> «Managing this KV cache efficiently is a challenging endeavor. Growing linearly with batch size
> and sequence length, the memory requirement can quickly scale. Consequently, it limits the
> throughput that can be served, and poses challenges for long-context inputs.»

Наслідок практичний: у хмарному API цей ліміт перетворюється на ціну й межі швидкості, а на
власному GPU він визначає, скільки запитів узагалі влізе — тому розрахунок нижче робіть до
купівлі заліза.

**Як працює під капотом.**

Форма уваги в причинній моделі така (з `research/02/cache-explanation-transformers-doc.md`):

```text
Attention(Q, K, V) = softmax( (Q K^T) / sqrt(d_head) * mask ) V
```

Для батчу розміру `b`, кількості голів `h`, довжини послідовності `T` і розмірності голови
`d_head` матриці `Q`, `K`, `V` мають форму `(b, h, T, d_head)`. А кеш зберігається так:

> «Caches are structured as a list of layers, where each layer contains a key and value cache.
> The key and value caches are tensors with the shape `[batch_size, num_heads, seq_len, head_dim]`.»

З цієї форми прямо випливає формула розміру. NVIDIA дає її в явному вигляді:

```text
Size of KV cache per token in bytes = 2 * (num_layers) * (num_heads * dim_head) * precision_in_bytes
Total size of KV cache in bytes = (batch_size) * (sequence_length) * 2 * (num_layers) * (hidden_size) * sizeof(FP16)
```

> «The first factor of 2 accounts for the K and V matrices. Commonly, the value of
> (num_heads * dim_head) is the same as the hidden_size (or dimension of the model, d_model) of the
> transformer. These model attributes are commonly found in model cards or associated config files.»

Приклад із джерела: «with a Llama 2 7B model in 16-bit precision and a batch size of 1, the size of
the KV cache will be 1 * 4096 * 2 * 32 * 4096 * 2 bytes, which is ~2 GB».

Одна поправка до цієї формули: `num_heads` там означає **кількість голів у проєкціях K і V**, а
не голів запиту. У старих моделях (Llama 2) це те саме число; у моделях із **GQA**
(grouped-query attention) голів K/V у 4–8 разів менше — NVIDIA описує GQA як оптимізацію, що
«reduce key-value memory usage ... without changing model accuracy». Тому нижче використовується
`num_key_value_heads` із `config.json`.

Перевірмо формулу на реальних конфігураціях. Файли `config.json` для чотирьох відкритих моделей
збережені в `research/02/configs/`:

```python
import json
import pathlib

CONFIGS_DIR = pathlib.Path("research/02/configs")


def load_config(name: str) -> dict:
    """Читає config.json моделі, збережений у research/02/configs/."""
    text = (CONFIGS_DIR / name).read_text(encoding="utf-8")
    if text.startswith("### SOURCE:"):
        text = text.split("\n", 1)[1]
    return json.loads(text)


def kv_bytes_per_token(cfg: dict, dtype_bytes: int = 2) -> int:
    """Байтів KV-кешу на один токен одного запиту.

    Формула з research/02/nvidia-mastering-llm-inference-optimization.txt:
        2 * num_layers * num_heads * dim_head * precision_in_bytes
    Множник 2 — це K і V. Для моделей із GQA голів у проєкціях K/V менше, ніж
    голів запиту, тому беремо num_key_value_heads (та сама формула, інша
    кількість голів у шарі).
    """
    head_dim = cfg.get("head_dim") or cfg["hidden_size"] // cfg["num_attention_heads"]
    return 2 * cfg["num_hidden_layers"] * cfg["num_key_value_heads"] * head_dim * dtype_bytes


MODELS = {
    "Llama 3.1 8B": "llama31-8b-config.json",
    "Qwen3 8B": "qwen3-8b-config.json",
    "Qwen3 32B": "qwen3-32b-config.json",
    "gpt-oss-20b": "gpt-oss-20b-config.json",
}

print("Архітектури з реальних config.json (research/02/configs/)")
print(f"{'модель':14}{'шарів':>7}{'голів Q':>9}{'голів KV':>10}{'head_dim':>10}{'hidden':>8}")
for label, fname in MODELS.items():
    cfg = load_config(fname)
    head_dim = cfg.get("head_dim") or cfg["hidden_size"] // cfg["num_attention_heads"]
    print(f"{label:14}{cfg['num_hidden_layers']:>7}{cfg['num_attention_heads']:>9}"
          f"{cfg['num_key_value_heads']:>10}{head_dim:>10}{cfg['hidden_size']:>8}")

print()
print("Перевірка формули на прикладі з джерела (Llama 2 7B, batch 1, seq 4096, fp16):")
print("  1 * 4096 * 2 * 32 * 4096 * 2 =", f"{1*4096*2*32*4096*2:,}", "байтів =",
      f"{1*4096*2*32*4096*2/1e9:.3f} GB")

print()
print("KV-кеш на один токен (fp16, один запит)")
print(f"{'модель':14}{'MHA (усі голови)':>20}{'GQA (реальні KV-голови)':>26}{'виграш':>9}")
for label, fname in MODELS.items():
    cfg = load_config(fname)
    head_dim = cfg.get("head_dim") or cfg["hidden_size"] // cfg["num_attention_heads"]
    mha = 2 * cfg["num_hidden_layers"] * cfg["num_attention_heads"] * head_dim * 2
    gqa = kv_bytes_per_token(cfg)
    print(f"{label:14}{mha/1024/1024:>17.3f} MiB{gqa/1024/1024:>23.3f} MiB{mha/gqa:>8.1f}x")

print()
CONTEXTS = [1_000, 8_000, 32_000, 128_000, 200_000, 1_000_000]
print("KV-кеш одного запиту, GiB (fp16)")
print(f"{'модель':14}" + "".join(f"{c:>12,}" for c in CONTEXTS))
for label, fname in MODELS.items():
    per_token = kv_bytes_per_token(load_config(fname))
    row = f"{label:14}"
    for ctx in CONTEXTS:
        row += f"{per_token*ctx/1024**3:>12.3f}"
    print(row)
```

Фактичний вивід:

```
Архітектури з реальних config.json (research/02/configs/)
модель          шарів  голів Q  голів KV  head_dim  hidden
Llama 3.1 8B       32       32         8       128    4096
Qwen3 8B           36       32         8       128    4096
Qwen3 32B          64       64         8       128    5120
gpt-oss-20b        24       64         8        64    2880

Перевірка формули на прикладі з джерела (Llama 2 7B, batch 1, seq 4096, fp16):
  1 * 4096 * 2 * 32 * 4096 * 2 = 2,147,483,648 байтів = 2.147 GB

KV-кеш на один токен (fp16, один запит)
модель            MHA (усі голови)   GQA (реальні KV-голови)   виграш
Llama 3.1 8B              0.500 MiB                  0.125 MiB     4.0x
Qwen3 8B                  0.562 MiB                  0.141 MiB     4.0x
Qwen3 32B                 2.000 MiB                  0.250 MiB     8.0x
gpt-oss-20b               0.375 MiB                  0.047 MiB     8.0x

KV-кеш одного запиту, GiB (fp16)
модель               1,000       8,000      32,000     128,000     200,000   1,000,000
Llama 3.1 8B         0.122       0.977       3.906      15.625      24.414     122.070
Qwen3 8B             0.137       1.099       4.395      17.578      27.466     137.329
Qwen3 32B            0.244       1.953       7.812      31.250      48.828     244.141
gpt-oss-20b          0.046       0.366       1.465       5.859       9.155      45.776
```

Три висновки. **GQA — не дрібниця**: різниця між гіпотетичною MHA і реальною GQA-моделлю
становить 4–8x на кожному токені. **На мільйонному контексті KV-кеш перевищує ваги моделі**: у
Qwen3 8B кеш на 1M токенів — 137 GiB проти ≈8B параметрів у fp16 (близько 15 GiB), тобто «1M
контекст» на власному залізі — це передусім пам'ять під кеш. І **зростання лінійне і за контекстом, і за
батчем**.

Саме останній пункт найчастіше стає стіною. Той самий Qwen3 8B у двох вимірах:

| Контекст | batch 1 | batch 8 | batch 32 | batch 128 |
|---|---|---|---|---|
| 8 000 | 1.10 GiB | 8.79 GiB | 35.16 GiB | 140.62 GiB |
| 32 000 | 4.39 GiB | 35.16 GiB | 140.62 GiB | 562.50 GiB |
| 128 000 | 17.58 GiB | 140.62 GiB | 562.50 GiB | 2250.00 GiB |

| Точність | 8 000 | 32 000 | 128 000 |
|---|---|---|---|
| fp32 | 2.20 GiB | 8.79 GiB | 35.16 GiB |
| fp16/bf16 | 1.10 GiB | 4.39 GiB | 17.58 GiB |
| fp8/int8 | 0.55 GiB | 2.20 GiB | 8.79 GiB |
| int4 | 0.27 GiB | 1.10 GiB | 4.39 GiB |

Батч 32 на контексті 128k — це 562 GiB тільки під KV-кеш, тоді як GPU, згадані в джерелах NVIDIA
(A100-40GB, H100-80GB), мають 40 і 80 GiB. «Підняти батч, щоб було швидше» впирається не в обчислення, а в пам'ять. Саме тут
з'являється Quantized Cache: документація Transformers позначає його як «Low» за споживанням
пам'яті проти «Medium» у DynamicCache і «High» у StaticCache.

Власні розрахунки варто звіряти з чужими опублікованими числами — це найшвидший спосіб знайти
помилку в одиницях або в множнику. HF-блог про Llama 3.1
(`research/02/hf-blog-llama31-memory.txt`) публікує таблицю «In FP16, the KV cache memory
requirements are»:

Код розрахунку — той самий, що вище (`per_token * ctx / 1024**3`). Фактичний вивід:

```
Звірка: опублікована таблиця HF-блогу проти формули
  модель  контекст  опубліковано  формула, GiB   різниця
      8B     1,000        0.125         0.122     -2.3%
      8B    16,000        1.950         1.953      +0.2%
      8B   128,000       15.620        15.625      +0.0%
     70B     1,000        0.313         0.305     -2.5%
     70B    16,000        4.880         4.883      +0.1%
     70B   128,000       39.060        39.062      +0.0%
    405B     1,000        0.984         0.481    -51.2%
    405B    16,000       15.380         7.690    -50.0%
    405B   128,000      123.050        61.523    -50.0%
```

Для 8B і 70B розбіжність — від −2.5% до +0.0%: формула підтверджена. А рядок 405B розходиться
рівно вдвічі. Це помилка не розрахунку, а **опублікованої таблиці**: числа 405B схожі на
розрахунок у FP32 замість FP16. У тому самому файлі два коментарі користувачів помітили це
незалежно: «these three values look like from FP32, could you double-check it?» і «405b at 128k
should be in the ~66gb ballpark». Розрахунок дає 61.5 GiB — у тому ж діапазоні.

Практичний висновок із цієї звірки: **завжди перевіряйте одиниці та множники на числах для
кількох моделей**. У документованій формулі легко загубити множник 2 (K і V) або точність
(FP16 проти FP32), і обидві помилки дають правдоподібний результат.

Третій вимір, який ламає просту формулу: **не всі шари мають повнорозмірний кеш**. За sliding
window attention кеш шару перестає рости після вікна — документація Transformers описує це для
`DynamicCache`: «the cache will stop growing when the layers using these types of attention have
reached their maximum size». У `config.json` моделі gpt-oss-20b є поле `layer_types`:

```python
cfg = load_config("gpt-oss-20b-config.json")   # функція з блоку вище
heads = cfg["num_key_value_heads"]
head_dim = cfg["head_dim"]
window = cfg["sliding_window"]
types = cfg["layer_types"]
n_slide = types.count("sliding_attention")
n_full = types.count("full_attention")
per_layer = 2 * heads * head_dim * 2
print(f"gpt-oss-20b: {cfg['num_hidden_layers']} шарів -> sliding {n_slide}, full {n_full}; "
      f"sliding_window={window}; {per_layer:,} байтів/токен на шар")
print(f"{'контекст':>10}{'гібрид, MiB':>14}{'усі шари як full, MiB':>24}{'економія':>10}")
for ctx in (8_000, 32_000, 128_000):
    full = per_layer * n_full * ctx
    slide = per_layer * n_slide * min(ctx, window)
    naive = per_layer * cfg["num_hidden_layers"] * ctx
    print(f"{ctx:>10,}{full/1024**2:>13.1f} {naive/1024**2:>22.1f}{(1-(full+slide)/naive)*100:>9.1f}%")
```

Фактичний вивід:

```
gpt-oss-20b: 24 шарів -> sliding 12, full 12; sliding_window=128; 2,048 байтів/токен на шар
  контекст   гібрид, MiB   усі шари як full, MiB  економія
     8,000        187.5                  375.0     49.2%
    32,000        750.0                 1500.0     49.8%
   128,000       3000.0                 6000.0     50.0%
```

Половина шарів має вікно всього 128 токенів, тому їхній кеш узагалі не залежить від довжини
контексту. Якби ви порахували цю модель «у лоб» за формулою, ви переоцінили б пам'ять удвічі.
Висновок: **перед розрахунком дивіться `config.json`, а не картку моделі**.

Тепер про те, як кеш укладають у пам'ять. Якби кожен запит вимагав неперервної ділянки пам'яті
під максимально можливий контекст, пам'ять закінчувалася б миттєво: ви мусили б зарезервувати
128k токенів навіть під запит, що поверне 20 токенів. Розв'язок — **PagedAttention**:

> «Inspired by paging in operating systems, the PagedAttention algorithm enables storing
> continuous keys and values in noncontiguous space in memory. It partitions the KV cache of each
> request into blocks representing a fixed number of tokens, which can be stored non-contiguously.»
> (`research/02/nvidia-mastering-llm-inference-optimization.txt`)

Документація Transformers показує, як це виглядає на рівні індексів
(`research/hf5_tfdoc_paged_attention.txt`): запит із 70 закешованими токенами й блоком 32
зберігається як `block_table = [3, 5, 6, -1]` — блоки несуміжні, `-1` означає вільний слот.
Перевага не в швидкості, а в **відсутності фрагментації**: втрачається максимум один неповний
блок на запит, а не весь максимальний контекст.

Другий ефект: однакові префікси різних запитів можуть посилатися на ті самі фізичні блоки. У
vLLM це Automatic Prefix Caching — «a new query can directly reuse the KV cache if it shares the
same prefix with one of the existing queries» (`research/02/vllm-automatic-prefix-caching.txt`).
Обмеження звідти ж: APC «only reduces the time of processing the queries (the prefilling phase)
and does not reduce the time of generating new tokens» — тобто зменшує TTFT, а не TPOT. Це
серверний аналог `cache_control` у Claude API (розділ 9).
Реалізація в vLLM хешує кожен блок окремо: «we hash each kv-cache block by the tokens in the block
and the tokens in the prefix before the block», алгоритм — `sha256` (з v0.11), і «we only cache
full blocks» (`research/02/vllm-prefix-caching-design.md`). Тому зсув на один токен на початку
промпту обнуляє весь кеш — та сама причина, що й у хмарному префіксному кеші (розділ 9).

**Типові помилки**

- **Брати `num_attention_heads` замість `num_key_value_heads`.** Для Qwen3 32B це завищує
  розрахунок у 8 разів — 244 GiB замість 31 GiB на 128k. Найдорожча помилка в цьому розділі.
- **Забути множник 2 (K і V).** Дає рівно половину реальної потреби.
- **Забути про батч.** Формула на один запит; при батчі 32 помножте на 32. Інакше ви поставите
  сервіс з ідеальним планом і OOM на третьому користувачі.
- **Порахувати кеш у FP16, а ваги — окремо, і забути їх скласти.** Розрахунок для сервера — це
  ваги + KV-кеш + проміжні активації. Формула з документації EleutherAI
  (`research/02/eleuther-transformer-math.txt`): «Total Memory_Inference ≈ (1.2) × Model Memory»
  — щонайменше 20% понад ваги, ще до KV-кешу.
- **Вважати, що всі шари мають однаковий кеш.** Sliding window ламає формулу вдвічі (приклад
  gpt-oss-20b вище).
- **Чекати, що префіксний кеш прискорить генерацію.** Він зменшує префіл, тобто TTFT; TPOT не
  змінюється.

**Альтернативи.** Способів зменшити тиск KV-кешу на пам'ять кілька, і вони комбінуються:

| Техніка | Що робить | Ціна | Де підтверджено |
|---|---|---|---|
| GQA / MQA | Менше голів у проєкціях K і V | Потребує моделі, навченої так | NVIDIA: «reduce key-value memory usage» |
| PagedAttention | Блокове зберігання без фрагментації | Складніший планувальник | NVIDIA, Transformers |
| Quantized Cache | Кеш у нижчій точності | Втрата точності, повільніше | Transformers: «Expected memory usage: Low» |
| Sliding window attention | Кеш шару перестає рости | Обмежує дальню увагу | Transformers, `layer_types` у конфізі |
| Cache offloading | Кеш шарів на CPU, на GPU — лише поточний | Швидкість обміну по PCIe | Transformers: «trading off speed for reduced memory usage» |
| Prefix caching | Спільні блоки для однакових префіксів | Потрібен стабільний префікс | vLLM APC |
| Менший контекст / compaction | Менше токенів у кеші | Втрата деталей історії | Anthropic: compaction (2.4) |

Порядок застосування практичний такий: спершу візьміть модель із GQA (це безкоштовно), потім
увімкніть paged attention і prefix caching (це конфігурація сервера), і лише потім переходьте до
квантизації кешу — вона єдина з цього списку змінює якість відповідей.

### 2.4 Довгий контекст: коли він допомагає, а коли шкодить

**Що це.** Контекстне вікно — це «робоча пам'ять» моделі: усе, на що вона може посилатися під
час генерації, включно з власною відповіддю. Документація Claude описує його так
(`research/02/context-windows.md`):

> «The "context window" refers to all the text a language model can reference when generating a
> response, including the response itself. This is different from the large corpus of data the
> language model was trained on, and instead represents a "working memory" for the model. A larger
> context window allows the model to handle more complex and lengthy prompts, but more context
> isn't automatically better. As token count grows, accuracy and recall degrade, a phenomenon
> known as *context rot*.»

Два речення в цій цитаті суперечать одне одному лише на перший погляд. Вікно справді
збільшує обсяг задач, які взагалі можна поставити. Але кожен доданий токен **знижує** точність
на тому, що вже лежить у вікні.

**Навіщо це знати.** Довгий контекст — це місце, де економіка, затримка й якість тиснуть в один
бік із різною силою. Гроші й затримка зростають лінійно (квадратично в увазі префілу), а якість
падає. Тому «закинути все у вікно» — це рішення, яке погіршує три метрики одночасно, і воно
найпопулярніше саме тому, що його найлегше ухвалити.

**Як працює під капотом.**

Anthropic описує механізм через обмежений ресурс уваги
(`research/02/anthropic-effective-context-engineering.txt`):

> «Studies on needle-in-a-haystack style benchmarking have uncovered the concept of context rot: as
> the number of tokens in the context window increases, the model's ability to accurately recall
> information from that context decreases.»

> «Context, therefore, must be treated as a finite resource with diminishing marginal returns...
> LLMs have an "attention budget" that they draw on when parsing large volumes of context. Every
> new token introduced depletes this budget by some amount.»

Деградація не схожа на обрив: джерело формулює її як «performance gradient rather than a hard
cliff: models remain highly capable at longer contexts but may show reduced precision for
information retrieval and long-range reasoning». Один із чинників названий прямо: «position
encoding interpolation allow models to handle longer sequences by adapting them to the originally
trained smaller context, though with some degradation in token position understanding». Вікно в 1M
токенів не означає, що модель однаково впевнено орієнтується на позиції 10 000 і 900 000.

Тепер економіка. Зростання вартості діалогу не очевидне, поки не порахувати його. У звичайному
багатоходовому діалозі **кожен хід відправляє всю історію заново**: «Each turn consists of:
Input phase: contains all previous conversation history plus the current user message»
(`research/02/context-windows.md`). Тому ціна росте не лінійно за ходами, а як сума
арифметичної прогресії.

```python
SYS_TOKENS = 3_000
USER_TOKENS = 200
OUT_TOKENS = 600
PRICE_IN, PRICE_OUT = 2.0, 10.0   # Claude Sonnet 5, $/MTok


def input_tokens_at_turn(turn: int) -> int:
    """Скільки вхідних токенів у запиті на ході turn (1-based), без compaction."""
    return SYS_TOKENS + (turn - 1) * (USER_TOKENS + OUT_TOKENS) + USER_TOKENS


def cost(turns: int) -> float:
    return sum(input_tokens_at_turn(t) / 1e6 * PRICE_IN + OUT_TOKENS / 1e6 * PRICE_OUT
               for t in range(1, turns + 1))


print("Скільки ходів уміщує вікно (sys 3000, хід = 200 user + 600 assistant)")
for window in (200_000, 1_000_000):
    turn = next(t for t in range(1, 10_000) if input_tokens_at_turn(t) + OUT_TOKENS > window)
    total_in = sum(input_tokens_at_turn(t) for t in range(1, turn))
    print(f"  вікно {window:>9,}: межа на ході {turn:>5} | сумарний вхід {total_in:>13,} токенів "
          f"| ${total_in/1e6*PRICE_IN:>9.2f} тільки на вхід")

print()
print("Ціна діалогу залежно від довжини (без compaction)")
print(f"{'ходів':>7}{'вхід на останньому ході':>26}{'сумарний вхід':>16}{'сумарна ціна':>15}")
for turns in (5, 10, 20, 40, 80):
    total_in = sum(input_tokens_at_turn(t) for t in range(1, turns + 1))
    print(f"{turns:>7}{input_tokens_at_turn(turns):>26,}{total_in:>16,}{cost(turns):>14.4f}$")

print()
print("Те саме з compaction: кожні 10 ходів історія стискається до 1 500 токенів")
print(f"{'ходів':>7}{'вхід на останньому ході':>26}{'сумарна ціна':>15}{'економія':>11}")
SUMMARY_TOKENS = 1_500
for turns in (20, 40, 80):
    ctx = SYS_TOKENS + SUMMARY_TOKENS
    total = 0.0
    for t in range(1, turns + 1):
        ctx += USER_TOKENS
        total += ctx / 1e6 * PRICE_IN + OUT_TOKENS / 1e6 * PRICE_OUT
        ctx += OUT_TOKENS
        if t % 10 == 0:
            ctx = SYS_TOKENS + SUMMARY_TOKENS
    base = cost(turns)
    print(f"{turns:>7}{ctx:>26,}{total:>14.4f}${(1-total/base)*100:>10.1f}%")
```

Фактичний вивід:

```
Скільки ходів уміщує вікно (sys 3000, хід = 200 user + 600 assistant)
  вікно   200,000: межа на ході   247 | сумарний вхід    24,895,200 токенів | $    49.79 тільки на вхід
  вікно 1,000,000: межа на ході  1247 | сумарний вхід   624,495,200 токенів | $  1248.99 тільки на вхід

Ціна діалогу залежно від довжини (без compaction)
  ходів   вхід на останньому ході   сумарний вхід   сумарна ціна
      5                     6,400          24,000        0.0780$
     10                    10,400          68,000        0.1960$
     20                    18,400         216,000        0.5520$
     40                    34,400         752,000        1.7440$
     80                    66,400       2,784,000        6.0480$

Те саме з compaction: кожні 10 ходів історія стискається до 1 500 токенів
  ходів   вхід на останньому ході   сумарна ціна   економія
     20                     4,500        0.4520$      18.1%
     40                     4,500        0.9040$      48.2%
     80                     4,500        1.8080$      70.1%
```

Ключове число тут — **624 мільйони вхідних токенів**. Стільки модель прочитає, щоб провести
діалог із 1247 ходів у вікні 1M за схемою «системний промпт + усі попередні репліки». Корисного
змісту в цьому діалозі — приблизно мільйон токенів; решта 623 мільйони — повторне відправлення
того самого. Це коштує $1 249 тільки на вхід, за ціною $2/MTok.

Порівняйте рядки 40 і 80 ходів: подвоєння довжини діалогу збільшує ціну в 3.5 раза
($1.744 → $6.048), а не вдвічі. Це квадратичне зростання суми арифметичної прогресії, і саме
воно робить довгі агенти дорогими.

Compaction змінює характер кривої: вона не просто знижує ціну, а **зупиняє зростання** — на 80
ходах вхід на останньому ході становить 4 500 токенів замість 66 400, економія 70%. Документація
Anthropic описує її як основний інструмент для довгих задач: «taking a conversation nearing the
context window limit, summarizing its contents, and reinitiating a new context window with the
summary... enabling the agent to continue with minimal performance degradation».

Другий вимір — ціна одиниці контексту. Провайдери тут розходяться:

| Провайдер / модель | Короткий контекст (вхід / вихід) | Довгий контекст | Джерело |
|---|---|---|---|
| Claude 4.6+ (1M вікно) | $2 / $10 (Sonnet 5) | ті самі ставки: «A 900k-token request is billed at the same per-token rate as a 9k-token request» | `research/02/pricing.md` |
| gpt-6-astra | $10 / $50 | $20 / $75 (довгий контекст дорожчий) | `research/econ/openai_pricing.md` |
| gpt-5.6-terra | $2 / $12 | $4 / $18 | `research/econ/openai_pricing.md` |
| gpt-5.5 (<272K) | $5 / $30 | $10 / $45 | `research/econ/openai_pricing.md` |

В одних провайдерів 900 000 токенів коштують стільки ж за токен, скільки 9 000, в інших перехід
за поріг множить ціну на 1.5–2x. Якщо промпт «майже вписується» в поріг, це може бути найдорожчим
рішенням у проєкті: 300 000 токенів за подвійною ставкою дорожчі за 250 000 за одинарною.

Третій вимір — пам'ять під KV-кеш, який росте лінійно разом із контекстом. Це вже розібрано в
2.3: на мільйонному контексті кеш одного запиту більший за ваги моделі.

І четвертий, який рідко згадують: **асиметрія впливу на затримку**. Документація OpenAI
(`research/02/openai-latency-guide.txt`) дає оцінку, яку варто перечитати двічі: скорочення
промпту вдвічі дає 1–5% затримки, скорочення відповіді вдвічі — близько 50%. Тобто довгий
контекст дорогий і шкідливий для якості, але на швидкість відповіді впливає слабко — доки
промпт не стає «truly massive».

Коли довгий контекст справді допомагає:

| Ситуація | Чому довгий контекст кращий |
|---|---|
| Наскрізний аналіз одного документа | Модель бачить зв'язки між розділами, які RAG розірвав би |
| Задача, де потрібен «погляд зверху» | Сумаризація, аудит, пошук суперечностей у корпусі |
| Кілька прикладів (few-shot) | Демонстрації працюють краще за інструкції, якщо вони релевантні |
| Кодова база, де важливі зв'язки між файлами | Контекст замінює неточний пошук |

Коли він шкодить: класифікація за одним коротким сигналом, витяг одного поля з документа, будь-яка
задача з чітким шаблоном відповіді, і будь-який агентний цикл, де історія накопичується без
відбору.

**Типові помилки**

- **Вважати, що більший контекст = краще.** Документація прямо: «more context isn't
  automatically better» і «As token count grows, accuracy and recall degrade».
- **Забувати, що кожен хід відправляє всю історію.** Це не «безкоштовне» збереження — ви
  платите за нього на кожному ході (див. 624M токенів вище).
- **Не рахувати `total_input_tokens`, а дивитися тільки `input_tokens`.** При кешованому
  префіксі це різниця в тисячі разів (2.1).
- **Тримати роздуми в історії, не усвідомлюючи ціни.** На моделях, які зберігають thinking-блоки,
  «the kept blocks are then part of later requests' input and are billed as input tokens».
- **Ставити динамічну частину промпту на початок.** Документація OpenAI радить зворотне:
  «Maximize shared prompt prefix, by putting dynamic portions (for example, RAG results and
  history) later in the prompt. This makes your request more KV cache-friendly... and means fewer
  input tokens are processed on each request».
- **Плутати вікно контексту з обсягом виходу.** У Claude 4.6+ вікно 1M токенів, але один запит
  може згенерувати щонайбільше 128k вихідних токенів (`max_tokens`).

**Альтернативи.** Довгому контексту є чотири практичні заміни, і вони не виключають одна одну:

| Стратегія | Що робить | Коли вибирати | Джерело |
|---|---|---|---|
| Compaction | Стискає історію до резюме й починає нове вікно | Довгі діалоги й агенти | Anthropic: «the primary strategy for context management» |
| RAG / пошук | Дає моделі лише релевантні фрагменти | Великий корпус, точкові питання | Розділи 16–17 |
| Prompt caching | Не скорочує контекст, але робить його повторне читання дешевим | Стабільний префікс | Розділ 9 |
| Context editing | Прибирає окремі блоки (наприклад, старі thinking) | Тонке керування тим, що лишається | `research/02/context-windows.md` |

Практичне правило: спершу спробуйте **менший контекст**, і лише якщо задача справді вимагає
зв'язків між далекими частинами — збільшуйте. Документація Anthropic формулює мету без
компромісів: «find the smallest possible set of high-signal tokens that maximize the likelihood of
some desired outcome».

### 2.5 Арифметика вартості: вхід/вихід/кеш/батч

**Що це.** Рахунок — сума чотирьох доданків із різними ставками: базовий вхід, запис у кеш,
читання з кешу, вихід. Жоден не можна ігнорувати: у прикладі з 2.1 вихідні токени становили
0.4% обсягу й 16.8% рахунку.

**Навіщо це знати.** Три рішення, які дозволяє ухвалити ця арифметика: скорочувати вхід чи вихід,
платити за кеш чи ні, і чи варто чекати на Batch API.

**Як працює під капотом.**

Спершу — чому ціна виходу вища за ціну входу. Це наслідок фаз із 2.2: префіл — матриця ×
матриця, він обробляє тисячі токенів за прохід і насичує GPU, тому собівартість токена низька;
декодування — матриця × вектор, воно memory-bound і дає **один токен за прохід**. Databricks
формулює причину так: декодування впирається в те, «how quickly we can load model parameters from
GPU memory to local caches/registers».

Співвідношення цін стабільне в усіх великих провайдерів:

| Модель | Вхід $/MTok | Вихід $/MTok | out/in | Кеш-читання | Запис |
|---|---|---|---|---|---|
| Claude Sonnet 5 | 2.00 | 10.00 | 5.0x | 10.0% | 2.5000 |
| Claude Opus 5 | 5.00 | 25.00 | 5.0x | 10.0% | 6.2500 |
| Claude Haiku 4.5 | 1.00 | 5.00 | 5.0x | 10.0% | 1.2500 |
| gpt-6-astra | 10.00 | 50.00 | 5.0x | 10.0% | 12.5000 |
| gpt-5.6-terra | 2.00 | 12.00 | 6.0x | 10.0% | 2.5000 |
| gpt-5-nano | 0.05 | 0.40 | 8.0x | 10.0% | 0.0625 |
| deepseek-v4-pro (peak) | 1.32 | 3.96 | 3.0x | 3.3% | — |
| deepseek-flash (peak) | 0.30 | 1.20 | 4.0x | 2.0% | — |

Розкид 3x–8x, і жоден провайдер не публікує формулу, з якої співвідношення випливає.
**Підтверджено:** механізм (префіл паралельний і compute-bound, декодування послідовне й
memory-bound) і самі ставки. **Не вдалося підтвердити:** точну модель собівартості, з якої
провайдери виводять множник. Тому не будуйте кошторис на припущенні «вихід дорожчий рівно у
5 разів» — читайте прайс-лист.

Друга частина — форма запитів. Той самий обсяг входу коштує по-різному залежно від кількості
запитів:

```python
PRICE_IN, PRICE_OUT, PRICE_READ = 2.00, 10.00, 0.20   # Claude Sonnet 5, $/MTok
print("Один довгий запит проти багатьох коротких")


def request_cost(calls: int, tokens_in: int, tokens_out: int) -> tuple[float, float]:
    """Повертає (ціна, частка виходу у відсотках)."""
    cost = calls * (tokens_in / 1e6 * PRICE_IN + tokens_out / 1e6 * PRICE_OUT)
    share = calls * tokens_out / 1e6 * PRICE_OUT / cost * 100
    return cost, share


variants = [
    ("1 запит: 200k in / 500 out", 1, 200_000, 500),
    ("20 запитів: 10k in / 500 out", 20, 10_000, 500),
    ("100 запитів: 2k in / 500 out", 100, 2_000, 500),
    ("1 запит: 2k in / 100k out", 1, 2_000, 100_000),
]
print(f"{'варіант':32}{'вхід, токенів':>15}{'вихід, токенів':>16}{'ціна':>11}{'частка виходу':>15}")
for label, calls, t_in, t_out in variants:
    cost, share = request_cost(calls, t_in, t_out)
    print(f"{label:32}{calls*t_in:>15,}{calls*t_out:>16,}{cost:>10.4f}${share:>14.1f}%")
```

Фактичний вивід:

```
Один довгий запит проти багатьох коротких
варіант                           вхід, токенів  вихід, токенів       ціна  частка виходу
1 запит: 200k in / 500 out              200,000             500    0.4050$           1.2%
20 запитів: 10k in / 500 out            200,000          10,000    0.5000$          20.0%
100 запитів: 2k in / 500 out            200,000          50,000    0.9000$          55.6%
1 запит: 2k in / 100k out                 2,000         100,000    1.0040$          99.6%
```

Перші три рядки — це однакові 200 000 вхідних токенів, розбиті по-різному. Різниця в ціні —
2.2x, і причина не у вході, а у виході: 500 вихідних токенів на запит при 100 запитах
перетворюються на 50 000. Четвертий рядок показує протилежний режим: 100 000 вихідних токенів —
це 99.6% рахунку при вході в 2 000 токенів.

Практичний висновок: **вихід — головна стаття витрат у більшості реальних навантажень**. Якщо
рахунок зростає, дивіться на кількість згенерованих токенів, а не на розмір промпту.

Третя частина — кеш: два числа, множник запису й множник читання.

```python
PRICE_IN, PRICE_READ = 2.00, 0.20   # Claude Sonnet 5, $/MTok
print("Кеш: беззбитковість і економія (Claude Sonnet 5, префікс 100 000 токенів)")
prefix = 100_000
plain = prefix / 1e6 * PRICE_IN          # той самий префікс без кешу
read = prefix / 1e6 * PRICE_READ         # читати з кешу
for mult, label in ((1.25, "запис 5 хв"), (2.0, "запис 1 год")):
    write = plain * mult
    print(f"  {label}: запис ${write:.4f} проти ${plain:.4f} без кешу; "
          f"кожне читання ${read:.4f}; беззбитковість після {(write-plain)/(plain-read):.2f} читань")
print()
print(f"{'запитів':>8}{'5-хв кеш':>12}{'проти без кешу':>16}{'1-год кеш':>12}{'проти без кешу':>16}")
for n_calls in (2, 3, 5, 10, 50):
    no_cache = n_calls * plain
    cells = []
    for mult in (1.25, 2.0):
        with_cache = plain * mult + (n_calls - 1) * read
        cells.append(with_cache)
    print(f"{n_calls:>8}{cells[0]:>11.4f}${(1-cells[0]/no_cache)*100:>15.1f}%"
          f"{cells[1]:>11.4f}${(1-cells[1]/no_cache)*100:>15.1f}%")
```

Фактичний вивід:

```
Кеш: беззбитковість і економія (Claude Sonnet 5, префікс 100 000 токенів)
  запис 5 хв: запис $0.2500 проти $0.2000 без кешу; кожне читання $0.0200; беззбитковість після 0.28 читань
  запис 1 год: запис $0.4000 проти $0.2000 без кешу; кожне читання $0.0200; беззбитковість після 1.11 читань

 запитів    5-хв кеш  проти без кешу   1-год кеш  проти без кешу
       2     0.2700$           32.5%     0.4200$           -5.0%
       3     0.2900$           51.7%     0.4400$           26.7%
       5     0.3300$           67.0%     0.4800$           52.0%
      10     0.4300$           78.5%     0.5800$           71.0%
      50     1.2300$           87.7%     1.3800$           86.2%
```

Дробове значення беззбитковості (0.28 і 1.11) — це не помилка: воно означає, **на якому читанні**
кеш окупається. Для запису 1.25x достатньо першого читання, для 2x — другого. Це збігається з
формулюванням документації: «caching pays off after one cache read for the 5-minute duration
(1.25x write), or after two cache reads for the 1-hour duration (2x write)».

Головний висновок таблиці: **TTL визначає, чи кеш узагалі має сенс**. Два запити з 5-хвилинним
записом дають +32.5% економії, з годинним — мінус 5%: доплата 2x не встигає окупитися. Тому
короткоживучий кеш вмикайте вже від двох звернень, годинний — від трьох.

Четверта частина — батч. Claude Batch API дає 50% на обидві статті: «The Batch API allows
asynchronous processing of large volumes of requests with a 50% discount on both input and output
tokens». Для Sonnet 5 це $1/$5 замість $2/$10. Множники складаються з іншими: «These multipliers
stack with other pricing modifiers, including the Batch API discount and data residency». Тобто
batch + кеш + US-only (`inference_geo`, множник 1.1x) можна комбінувати.

Ось підсумкова таблиця всіх множників, які впливають на один рахунок:

| Механізм | Множник до базової ціни | На що діє | Джерело |
|---|---|---|---|
| Базовий вхід | 1.0x | вхідні токени | `research/02/pricing.md` |
| Вихід | 3x–8x залежно від моделі | вихідні токени | `research/02/pricing.md`, `research/econ/openai_pricing.md` |
| Запис у кеш, 5 хв | 1.25x | вхідні токени префікса | `research/02/pricing.md` |
| Запис у кеш, 1 год | 2.0x | вхідні токени префікса | `research/02/pricing.md` |
| Читання з кешу | 0.1x (0.025x на Fable 5.1 / Mythos 5.1) | вхідні токени префікса | `research/02/pricing.md` |
| Batch API | 0.5x | вхід і вихід | `research/02/pricing.md` |
| US-only (`inference_geo`) | 1.1x | усі категорії | `research/02/pricing.md` |
| Fast mode (Opus 5 / 4.8) | $10 / $50 замість $5 / $25 | вхід і вихід | `research/02/pricing.md` |
| Довгий контекст (OpenAI) | 2x вхід, 1.5x вихід | усе понад поріг | `research/econ/openai_pricing.md` |
| Off-peak (DeepSeek) | 0.5x | усі категорії в неробочі години | `research/econ/deepseek_pricing.txt` |

Останній рядок варто відзначити: у DeepSeek off-peak ставки **вдвічі** нижчі, а межа описана
точно — «Peak hours are 01:00 - 04:00 and 06:00 - 10:00 UTC, Monday through Friday, excluding
Chinese public holidays». Це єдиний побачений у джерелах випадок залежності ціни від часу доби.

**Типові помилки**

- **Оптимізувати вхід, коли винен вихід.** У прикладі вище 100 запитів по 2k входу дали 55.6%
  рахунку з виходу. Дивіться на пропорцію, а не на розмір промпту.
- **Порівнювати ціни `$/MTok` між моделями з різними токенізаторами.** +30% токенів на новому
  токенізаторі (2.1) з'їдає будь-яку «економію» від дешевшої моделі.
- **Вмикати годинний кеш заради двох запитів.** У розрахунку вище це −5% замість економії;
  для двох звернень беріть 5-хвилинний запис.
- **Забувати про запис при кошторисі.** 1.25x і 2x — це реальні доданки, а не округлення.
- **Ігнорувати `output_tokens` у thinking-режимі.** Роздуми оплачуються за ціною виходу і
  входять у `max_tokens`.
- **Вважати Batch API безкоштовним за швидкістю.** Знижка 50% — плата за асинхронність: ви не
  отримаєте відповідь одразу, і застосунок мусить бути перебудований під це (розділ 10).

**Альтернативи.** Замість ручного скорочення токенів є структурні підходи:

| Підхід | Ефект на рахунок | Ціна рішення |
|---|---|---|
| Дешевша модель на простих кроках (routing) | Прямо пропорційно різниці цін | Якість на складних кроках, складніша архітектура |
| Batch API | −50% на вхід і вихід | Асинхронність |
| Prompt caching | До −90% на повторюваному префіксі | Потрібен стабільний префікс і 3+ звернення |
| Компактифікація історії | Зупиняє квадратичне зростання (2.4) | Втрата деталей |
| Обмеження виходу (схема, `max_tokens`) | Прямо пропорційно | Обрізання |
| Дистиляція / файнтюнінг малої моделі | Знижує ціну токена на 10–100x | Розділ 21 |

Найдешевший токен — той, якого не було; друге за дешевизною — прочитаний з кешу; третє —
згенерований дешевшою моделлю.

**Джерела**

Документація Anthropic:

- `research/02/pricing.md` — ціни, множники кешу, Batch API, fast mode, `inference_geo` · https://platform.claude.com/docs/en/about-claude/pricing
- `research/econ/anthropic_pricing.md` — знімок прайс-листа Anthropic.
- `research/02/rate-limits.md` — RPM/ITPM/OTPM, cache-aware ITPM, каскад тирів · https://platform.claude.com/docs/en/api/rate-limits
- `research/02/token-counting.md` — новий токенізатор, ≈+30% токенів, обмеження оцінки · https://platform.claude.com/docs/en/docs/build-with-claude/token-counting.md
- `research/02/context-windows.md` — вікно, context rot, thinking і tool use у вікні · https://platform.claude.com/docs/en/docs/build-with-claude/context-windows.md
- `research/02/streaming.md`, `research/02/anthropic-streaming-doc.md` — події стріму, кумулятивний `usage` · https://platform.claude.com/docs/en/docs/build-with-claude/streaming.md
- `research/02/anthropic-reduce-latency.md` — TTFT і baseline latency · https://platform.claude.com/docs/en/test-and-evaluate/strengthen-guardrails/reduce-latency.md
- `research/02/anthropic-effective-context-engineering.txt` — attention budget, position interpolation, compaction · https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents

Інші провайдери й механіка інференсу:

- `research/econ/openai_pricing.md` — ціни OpenAI, кешований вхід, довгий контекст · https://developers.openai.com/api/docs/pricing.md
- `research/econ/deepseek_pricing.txt` — ціни DeepSeek, peak/off-peak, cache hit/miss · https://api-docs.deepseek.com/quick_start/pricing
- `research/02/openai-latency-guide.txt` — вплив входу й виходу на затримку · https://platform.openai.com/docs/guides/latency-optimization

- `research/02/nvidia-mastering-llm-inference-optimization.txt` — префіл і декодування, формула KV-кешу, MBU, PagedAttention, in-flight batching, MQA/GQA, FlashAttention, спекулятивний інференс · https://developer.nvidia.com/blog/mastering-llm-techniques-inference-optimization/
- `research/02/databricks-llm-inference-performance.txt` — формула затримки, TPOT, MBU, вимірювання батчингу, static/dynamic/continuous batching · https://www.databricks.com/blog/llm-inference-performance-engineering-best-practices
- `research/02/vllm-metrics-design.txt` — визначення TTFT, TPOT, ITL · https://raw.githubusercontent.com/vllm-project/vllm/main/docs/design/metrics.md
- `research/02/vllm-automatic-prefix-caching.txt` — APC: що економить і що ні · https://docs.vllm.ai/en/latest/features/automatic_prefix_caching.html

Документація Transformers і HF-блоги:

- `research/02/cache-explanation-transformers-doc.md` — форма KV-кешу, цикл генерації · https://raw.githubusercontent.com/huggingface/transformers/main/docs/source/en/cache_explanation.md
- `research/02/kv-cache-transformers-doc.md` — типи кешу, offloading, sliding window · https://raw.githubusercontent.com/huggingface/transformers/main/docs/source/en/kv_cache.md
- `research/02/continuous-batching-transformers-doc.md` — `max_batch_tokens`, chunked prefill, prefix caching · https://raw.githubusercontent.com/huggingface/transformers/main/docs/source/en/continuous_batching.md
- `research/hf5_tfdoc_paged_attention.txt` — block table, varlen і decode paths · https://raw.githubusercontent.com/huggingface/transformers/main/docs/source/en/paged_attention.md
- `research/02/hf-blog-continuous-batching.txt` — ragged batching, ціна padding · https://huggingface.co/blog/continuous_batching
- `research/02/hf-blog-llama31-memory.txt` — таблиця KV-кешу Llama 3.1 (помилка в рядку 405B — у 2.3) · https://huggingface.co/blog/llama31
- `research/02/hf-blog-assisted-generation.txt` — швидкості спекулятивного декодування · https://huggingface.co/blog/assisted-generation
- `research/02/eleuther-transformer-math.txt` — формули пам'яті, оверхед інференсу ≈1.2× · https://blog.eleuther.ai/transformer-math/

Дані для розрахунків:

- `research/02/configs/` — реальні `config.json` Qwen3 8B/32B, Llama 3.1 8B і gpt-oss-20b (усі числа в 2.3 отримані з них).
