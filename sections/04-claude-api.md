## 4. Claude API: Messages, стрімінг, версіонування, помилки

Messages API — це не «чат» і не RPC. Це один POST-ендпоінт, який приймає структурований список
повідомлень і повертає наступне повідомлення в розмові; стан розмови зберігаєте ви. Усе решта в
цьому розділі — наслідки цього рішення: чому системний промпт живе поза `messages`, чому `content`
буває і рядком, і масивом блоків, чому стрімінг для довгих запитів не оптимізація, а умова роботи,
і чому збої тут обробляються трьома різними механізмами, а не одним `try/except`.

Назви полів, формати подій, коди помилок і ліміти взяті з документації Anthropic і супроводжені
посиланнями; там, де наведено вивід, код реально виконано, а приклади, для яких потрібен ключ,
позначені явно.

### 4.1 Анатомія Messages API

**Що це.** `POST /v1/messages` — єдина точка входу для генерації. Тіло запиту: обов'язкова трійка
`model`, `max_tokens`, `messages` плюс опційні поля. Відповідь — об'єкт `Message` з масивом блоків
контенту, причиною зупинки `stop_reason` і лічильниками `usage`.

**Навіщо це знати.** Три наслідки видно вже зі структури: API не має пам'яті, тому кожен запит
мусить містити всю історію; відповідь — масив блоків, тому читання `content[0].text` ламається;
`stop_reason` — не помилка, а сигнал, і сім його значень вимагають семи різних дій.

**Як працює під капотом.**

#### Заголовки запиту

| Заголовок | Значення | Обов'язковий |
|---|---|---|
| `Authorization` | `Bearer <token>` — API-ключ або короткоживучий токен доступу | Так, якщо не задано `x-api-key` |
| `x-api-key` | Ключ із Console; застарілий резервний варіант, досі підтримується | Ні |
| `anthropic-version` | Версія API, наприклад `2023-06-01` | **Так** |
| `content-type` | `application/json` | **Так** |
| `anthropic-workspace-id` | ID робочого простору | Для ключа з кількома просторами |
| `anthropic-beta` | Назви beta-функцій; можна повторити або перелічити через кому | Ні |
| `anthropic-user-profile-id` | ID профілю користувача; потребує beta-заголовка `user-profiles` | Ні |

Офіційні SDK надсилають автентифікацію, версію та `content-type` самі; `anthropic-workspace-id`
передається вручну, якщо ключ цього потребує.

#### Тіло запиту

| Поле | Тип | Що робить |
|---|---|---|
| `model` | enum або рядок | Обов'язкове. Вибір моделі — розділ 6 |
| `max_tokens` | number, min `0` | Обов'язкове. Абсолютна межа генерації; `0` — наповнити кеш без генерації |
| `messages` | масив `MessageParam` | Обов'язкове. До **100 000** повідомлень у запиті |
| `system` | рядок або масив `TextBlockParam` | Системний промпт — див. 4.2 |
| `stream` | boolean | Інкрементальна віддача через SSE — див. 4.3 |
| `stop_sequences` | масив рядків | Свої стоп-послідовності; дають `stop_reason: "stop_sequence"` |
| `thinking` | `ThinkingConfigParam` | `enabled` (+`budget_tokens`), `disabled`, `adaptive`; `display`: `summarized`/`omitted` (розділ 8) |
| `output_config` | `OutputConfig` | `effort`: `low`/`medium`/`high`/`xhigh`/`max`; `format` — JSON-схема виходу |
| `tool_choice` | `ToolChoice` | `auto`, `any`, `tool` (+`name`), `none`; `disable_parallel_tool_use` (розділ 12) |
| `tools` | масив `ToolUnion` | Описи інструментів; `input_schema` — JSON Schema (draft 2020-12) |
| `cache_control` | `CacheControlEphemeral` | **Верхнього рівня**: точка кешування на останньому кешованому блоці (розділ 9) |
| `metadata` | `Metadata` | `user_id` (до 512 символів) — непрозорий ID, без імен і email-ів |
| `inference_geo` | рядок | Регіон інференсу; типово — `default_inference_geo` простору |
| `temperature`, `top_p`, `top_k` | number | **Застарілі** — див. нижче |

**Застарівання параметрів семплювання** — найпрактичніша зміна останніх поколінь. Документація
формулює три окремі правила: `temperature` — моделі після Claude Opus 4.6 не підтримують його
встановлення, значення `1.0` приймається для зворотної сумісності, будь-яке інше відхиляється з
**400**; `top_k` — не приймається взагалі; `top_p` — приймається лише `>= 0.99`, решта дає 400.

У документації «Using the Messages API» межа сформульована інакше: «не підтримуються на Claude 4.7 і
пізніших моделях і на Claude Mythos Preview». Отже, для **Claude Sonnet 4.6** однозначної відповіді
джерела не дають: **не вдалося підтвердити станом на 09.2026**, чи належить ця модель до забороненої
групи. Безпечний висновок — не передавати ці поля взагалі: на нових моделях вони гарантовано дають 400.

#### Що повертає API

| Поле `Message` | Що містить |
|---|---|
| `id`, `type`, `role` | Ідентифікатор, завжди `"message"`, завжди `"assistant"` |
| `content` | Масив блоків: `text`, `thinking`, `redacted_thinking`, `tool_use`, `tool_result`, `server_tool_use` та інші |
| `stop_reason` | Причина зупинки (таблиця нижче) |
| `stop_sequence` | Яка саме ваша стоп-послідовність спрацювала, або `null` |
| `stop_details` | Заповнюється при `stop_reason: "refusal"`: категорія політики й пояснення |
| `usage` | Лічильники білінгу й лімітів |

`content` — це масив, і порядок блоків не гарантований. Фільтруйте за `type`.

#### `stop_reason`: сім значень, сім різних дій

| `stop_reason` | Коли виникає | Що робити |
|---|---|---|
| `end_turn` | Модель природно завершила відповідь | Віддати відповідь |
| `max_tokens` | Досягнуто `max_tokens` або максимум моделі | Підняти `max_tokens` або попросити продовжити |
| `stop_sequence` | Згенеровано одну з ваших `stop_sequences` | Прочитати поле `stop_sequence` |
| `tool_use` | Модель викликала інструмент | Виконати й повернути `tool_result` |
| `pause_turn` | Цикл серверного інструмента досяг межі ітерацій | Надіслати `content` назад, щоб продовжити |
| `refusal` | Класифікатори відхилили відповідь | Прочитати `stop_details`, за потреби — fallback-модель |
| `model_context_window_exceeded` | Відповідь заповнила контекстне вікно | Вважати відповідь обрізаною |

У нестрімінговому режимі `stop_reason` завжди не `null`; у стрімінговому він `null` у події
`message_start` і не `null` у решті подій.

#### `usage`: три лічильники входу, а не один

| Поле | Що означає |
|---|---|
| `input_tokens` | Токени **після останньої точки кешування** |
| `cache_creation_input_tokens` | Токени, записані в кеш |
| `cache_read_input_tokens` | Токени, прочитані з кешу |
| `output_tokens` | Вихідні токени; **включний і авторитетний** для білінгу |
| `output_tokens_details.thinking_tokens` | Частка виходу на внутрішнє міркування (`≤ output_tokens`) |
| `cache_creation.ephemeral_5m_input_tokens`, `.ephemeral_1h_input_tokens` | Розбивка запису в кеш за TTL |
| `server_tool_use.web_search_requests`, `.web_fetch_requests` | Кількість серверних викликів |
| `service_tier` | `standard`, `priority` або `batch` |

Арифметика з довідки: `total_input_tokens = cache_read_input_tokens +
cache_creation_input_tokens + input_tokens`. На реальних числах із прикладу відповіді це дає
**6197** токенів входу замість 2095 — різниця втричі (розрахунок — у прикладі наступного розділу
підтеми).

Дві властивості `usage`, які легко проґавити: API перетворює запит у формат, зручний моделі, а
вихід проходить етап парсингу, тому лічильники **не збігаються один-до-одного** з видимим вмістом
(`output_tokens` буде ненульовим навіть для порожньої відповіді); а `thinking_tokens` рахує **сире**
міркування, а не довжину повернутого вам скороченого тексту.

#### Мінімальний запит

Реальний виклик через Python SDK (потрібен `ANTHROPIC_API_KEY`):

```python
# ПОТРЕБУЄ: ANTHROPIC_API_KEY
import anthropic

client = anthropic.Anthropic()          # ключ читається з ANTHROPIC_API_KEY

message = client.messages.create(
    model="claude-opus-5",
    max_tokens=1024,
    messages=[{"role": "user", "content": "Hello, Claude"}],
)

for block in message.content:           # НЕ message.content[0]
    if block.type == "text":
        print(block.text)

print(message.stop_reason, message.usage.input_tokens, message._request_id)
```

Локальна перевірка арифметики `usage` і нормалізації запиту — без ключа й без мережі. Це той код,
який варто мати в наборі тестів: він ловить помилки до того, як вони стануть 400-ми.

```python
# ── 4.1: арифметика usage і нормалізація content ────────────────────────────
import json

# usage з прикладу відповіді в довідці Messages API
usage = {"input_tokens": 2095, "cache_creation_input_tokens": 2051,
         "cache_read_input_tokens": 2051, "output_tokens": 503}
total_input = (usage["input_tokens"] + usage["cache_creation_input_tokens"]
               + usage["cache_read_input_tokens"])
print("усього вхідних токенів:", total_input,
      f"(input_tokens — лише {usage['input_tokens'] / total_input:.0%} від входу)")

# content-рядок — це скорочення для одного text-блоку, а не окремий тип
request = {
    "model": "claude-opus-5",
    "max_tokens": 1024,
    "system": "Ти — технічний редактор. Відповідай українською.",
    "messages": [
        {"role": "user", "content": "Поясни, що таке стрімінг."},
        {"role": "assistant", "content": "Стрімінг — це передача відповіді частинами."},
        {"role": "user", "content": [{"type": "text", "text": "А навіщо він потрібен?"}]},
    ],
}
missing = [f for f in ("model", "max_tokens", "messages") if f not in request]
assert not missing, f"бракує обов'язкових полів: {missing}"


def normalize(message: dict) -> dict:
    """Розгортає content-рядок у масив блоків — так його бачить API."""
    content = message["content"]
    if isinstance(content, str):
        content = [{"type": "text", "text": content}]
    return {**message, "content": content}


normalized = [normalize(m) for m in request["messages"]]
roles = [m["role"] for m in normalized]
merged = [r for i, r in enumerate(roles) if i == 0 or r != roles[i - 1]]
print("ролі:", roles, "-> після злиття підряд:", merged)
print("content останнього ходу:", json.dumps(normalized[-1]["content"], ensure_ascii=False))
```

Фактичний вивід:

```
усього вхідних токенів: 6197 (input_tokens — лише 34% від входу)
ролі: ['user', 'assistant', 'user'] -> після злиття підряд: ['user', 'assistant', 'user']
content останнього ходу: [{"type": "text", "text": "А навіщо він потрібен?"}]
```

**Типові помилки**

- Читати `content[0]`. З увімкненим мисленням відповідь може починатися з блоків `thinking`, у яких
  поле `thinking` при `display: "omitted"` узагалі порожнє.
- Вважати `input_tokens` повним входом. У прикладі вище різниця — утричі (2095 проти 6197), і це
  прямо впливає на розрахунок ITPM (див. 4.6).
- Передавати `temperature`/`top_p`/`top_k` «про всяк випадок» — на нових моделях це 400.
- Надсилати порожній `content: ""` — мінімальна довжина `text`-блоку 1 символ.
- Чекати, що порядок ролей збережеться: послідовні однакові ходи API зливає в один.
- Плутати `model_context_window_exceeded` з `max_tokens`: прохання «далі» тут не допоможе, спершу
  треба зменшити вхід.

**Альтернативи**

| Задача | Що брати | Чому |
|---|---|---|
| Власний цикл агента, точний контроль | **Messages API** | Прямий доступ до моделі |
| Довготривалі асинхронні задачі на керованій інфраструктурі | Claude Managed Agents | Готовий агентний каркас замість власного |
| Масовий офлайн-прогін | Message Batches API (розділ 10) | Асинхронно, але зі знижкою |
| Порахувати вхід до запиту | `POST /v1/messages/count_tokens` (розділ 3.5) | Той самий структурований вхід, без генерації |
| Фіксована JSON-форма відповіді | `output_config.format` | Надійніше за прохання в промпті |
| Керувати обчисленнями без зміни моделі | `output_config.effort` | Документація називає це часто кращим важелем, ніж зміна моделі |

---

### 4.2 Системний промпт і рольова структура

**Що це.** Два механізми передачі інструкцій: **top-level поле `system`** (діє від першого ходу) і
**повідомлення з `role: "system"` усередині `messages`** (діє з моменту появи в історії, лише на
частині моделей). Рольова структура — чергування `user`/`assistant`, де хід `assistant` у кінці має
окремий ефект.

**Навіщо це знати.** Вибір механізму впливає на кеш промпту: top-level `system` формує початок
кешованого префікса, а system-повідомлення в середині діалогу дописане в кінець історії й тому
**не інвалідує жодного кешованого префікса перед собою**. Це різниця між «переписати весь кеш» і
«доплатити за кілька токенів».

**Як працює під капотом.**

#### Top-level `system`

Документація фіксує прямо: у Messages API **немає ролі `"system"` для вхідних повідомлень** — для
системного промпту є окремий параметр верхнього рівня, який приймає рядок **або** масив текстових
блоків. Масив потрібен саме тоді, коли треба точка кешування: `cache_control` чіпляється до блоку,
а не до рядка.

```python
system = "Ти — асистент підтримки. Відповідай стисло."          # простий рядок
system = [                                                       # блоки + кеш-точка
    {"type": "text", "text": "Ти — асистент підтримки."},
    {"type": "text", "text": PRODUCT_DOC,
     "cache_control": {"type": "ephemeral"}},   # TTL типово 5m, можна "1h"
]
```

Верхньорівневий `cache_control` **ставить точку кешування на останній блок, який можна кешувати**,
автоматично. Це зручно, але небезпечно: додавши новий блок у кінець, ви зсуваєте точку й отримуєте
промах кешу замість влучання (розділ 9).

#### `role: "system"` усередині `messages`

Дозволений не всюди. Документація перелічує моделі, які його приймають: **Claude Fable 5.1,
Claude Mythos 5.1, Claude Fable 5, Claude Mythos 5, Claude Opus 4.8 і Claude Opus 5**. Правила:
system-повідомлення **не може бути першим** елементом `messages`; ставиться **після ходу `user`**;
має **ту саму силу**, що й top-level `system`; і, оскільки дописане в кінець, **не інвалідує
кешований префікс** перед собою.

Практичний висновок із документації: top-level `system` — для інструкцій, що діють від першого
ходу; system-повідомлення в діалозі — для тих, що стають доречними пізніше.

#### Рольова структура

Моделі натреновані на чергуванні `user`/`assistant`, тому послідовні однакові ролі API **зливає в
один хід**. Історія може бути синтетичною: `assistant`-повідомлення не обов'язково походить від
моделі. А якщо останнім іде `assistant`, відповідь **продовжується** з нього (prefill) — на
Claude 4.6+ це 400.

**Prefill прибрано на нових моделях.** Claude 4.6 і пізніші моделі та Claude Mythos Preview **не
підтримують** попереднє заповнення повідомлення асистента; запит повертає 400 з текстом:

```json
{
  "type": "error",
  "error": {
    "type": "invalid_request_error",
    "message": "This model does not support assistant message prefill. The conversation must end with a user message."
  }
}
```

Заміна за документацією: `output_config.format` (structured outputs), інструкції в системному
промпті або `tool_choice` на моделях, які його підтримують.

#### Робочий приклад

```python
# ── 4.2: системний промпт як стабільний префікс + місце для кеш-точки ───────
system_blocks = [
    {"type": "text", "text": "Ти — асистент підтримки. Відповідай стисло."},
    {"type": "text", "text": "<довідник продукту: 40 000 токенів>",
     "cache_control": {"type": "ephemeral"}},
]
for i, block in enumerate(system_blocks):
    print(f"  блок {i}: cache_control={block.get('cache_control')}")

# Моделі, які приймають system-повідомлення в СЕРЕДИНІ діалогу.
MID_SYSTEM_MODELS = {"claude-fable-5-1", "claude-mythos-5-1", "claude-fable-5",
                     "claude-mythos-5", "claude-opus-4-8", "claude-opus-5"}


def with_mid_system(model: str, turns: list[dict], instruction: str) -> list[dict]:
    """Додає system-хід після останнього user-ходу — лише для моделей зі списку."""
    if model not in MID_SYSTEM_MODELS:
        raise ValueError(f"{model} не приймає system-хід усередині діалогу")
    out = list(turns)
    at = max(i for i, m in enumerate(out) if m["role"] == "user") + 1
    out.insert(at, {"role": "system", "content": instruction})
    return out


turns = [{"role": "user", "content": "Порахуй знижку."},
         {"role": "assistant", "content": "Готую розрахунок..."}]
print("ролі до  :", [m["role"] for m in turns])
print("ролі після:", [m["role"] for m in with_mid_system(
    "claude-opus-5", turns, "Далі — лише таблицею.")])
```

Фактичний вивід:

```
  блок 0: cache_control=None
  блок 1: cache_control={'type': 'ephemeral'}
ролі до  : ['user', 'assistant']
ролі після: ['user', 'system', 'assistant']
```

Реальний виклик (фрагмент; `client` — із 4.1) — саме так перевіряють, чи кеш справді працює:

```python
message = client.messages.create(
    model="claude-opus-5",
    max_tokens=512,
    system=system_blocks,
    messages=[{"role": "user", "content": "Як змінити тарифний план?"}],
)
print(message.usage.cache_creation_input_tokens)   # перший запит: запис у кеш
# ... другий запит із тим самим префіксом:
print(message.usage.cache_read_input_tokens)       # має бути > 0
```

**Типові помилки**

- Покласти system першим елементом `messages`: на моделях, що підтримують mid-conversation system,
  це прямо заборонено правилами розміщення.
- Передати `role: "system"` моделі поза переліком із шести — вона його не приймає.
- Змінювати top-level `system` і сподіватися, що перевага «не інвалідує префікс» збережеться:
  вона стосується лише тексту, дописаного в кінець.
- Використовувати prefill на Claude 4.6+ — гарантований 400.
- Вважати системний промпт межею безпеки: це інструкція, а не контроль доступу (розділ 11).

**Альтернативи**

| Потреба | Механізм | Особливість |
|---|---|---|
| Інструкції від першого ходу | top-level `system` | Формує початок кешованого префікса |
| Точка кешування всередині системного тексту | `system` як масив блоків + `cache_control` | Єдиний спосіб розділити промпт на кешовану й змінну частини |
| Інструкція, доречна в середині діалогу | `role: "system"` у `messages` | Лише 6 моделей; не інвалідує кеш перед собою |
| Фіксована форма виходу | `output_config.format` | Заміна prefill на нових моделях |
| Інструкція для одного виклику | `user`-повідомлення | Найслабша позиція з погляду пріоритету інструкцій |

---

### 4.3 Стрімінг і типи подій

**Що це.** `stream: true` змушує API віддавати відповідь інкрементально через SSE (server-sent
events): потік іменованих подій, кожна з яких несе JSON. Замість одного об'єкта `Message` ви
отримуєте `message_start`, серію блоків контенту, `message_delta` і `message_stop`.

**Навіщо це знати.** По-перше, час до першого токена на порядок менший за повний час відповіді.
По-друге — і важливіше — документація SDK прямо каже уникати великих `max_tokens` без стрімінгу:
мережі розривають простоюючі з'єднання, і запит падає або впирається в таймаут. Python SDK кидає
`ValueError`, якщо нестрімінговий запит, за оцінкою, триватиме довше ніж приблизно 10 хвилин.

**Як працює під капотом.**

#### Послідовність подій

1. `message_start` — об'єкт `Message` з **порожнім** `content`; саме тут у стрімінгу `stop_reason`
   дорівнює `null`.
2. Блоки контенту: `content_block_start`, один або кілька `content_block_delta`, `content_block_stop`.
   У кожного блоку є `index`, що відповідає його позиції у фінальному масиві `content`.
3. Одна або кілька `message_delta` — зміни верхнього рівня, зокрема `stop_reason` і `usage`.
4. `message_stop`.

Додатково події `ping` можуть з'являтися будь-де, а `event: error` — при збої вже після 200 OK.

Дві властивості, які ламають наївний код: **`usage` у `message_delta` кумулятивний** (не додавайте
лічильники з різних подій), і **нові типи подій можуть з'явитися** — за політикою версіонування API
додає варіанти в enum-подібні значення, і приклад у документації — саме типи стрімінгових подій.
Невідомий тип треба ігнорувати, а не падати.

#### Типи дельт

| Тип дельти | Поле з вмістом | Особливість |
|---|---|---|
| `text_delta` | `text` | Звичайний текст |
| `input_json_delta` | `partial_json` | **Частковий** JSON-рядок; фінальний `tool_use.input` — завжди об'єкт |
| `thinking_delta` | `thinking` | Текст міркування |
| `signature_delta` | `signature` | Надсилається **безпосередньо перед** `content_block_stop`; перевіряє цілісність блоку |

Про `input_json_delta` є UX-деталь: поточні моделі видають **одну повну пару ключ–значення за раз**,
тому між подіями бувають паузи, поки модель «думає». Збирати частковий JSON треба до
`content_block_stop` і парсити один раз (або взяти хелпери SDK). Про мислення: при
`display: "omitted"` текст не стрімиться — блок відкривається, отримує `thinking_delta` з **порожнім**
рядком і один `signature_delta`, після чого закривається.

#### Помилки в середині потоку

Якщо помилка трапилася **після** повернення 200 OK, стандартні механізми не працюють — приходить подія
`event: error` з тілом `{"type": "error", "error": {"type": "overloaded_error", ...}}`. За
документацією така подія «зазвичай відповідає HTTP 529» у нестрімінговому контексті, тож обробник
помилок мусить мати **два** входи: HTTP-статус і подію `error`.

#### Відновлення перерваного потоку

| Покоління | Крок 2 стратегії «зберегти й продовжити» |
|---|---|
| Claude 4.5 і раніші | Часткову відповідь покласти як **початок нового `assistant`-повідомлення** |
| Claude 4.6 і пізніші | Додати **`user`-повідомлення** з частковою відповіддю й інструкцією продовжити |

Причина різниці — той самий заборонений prefill на 4.6+. Шаблон тексту з документації:
`Your previous response was interrupted and ended with [previous_response]. Continue from where you left off.`
Обмеження, яке треба знати заздалегідь: **блоки `tool_use` і `thinking` частково відновити
неможливо** — продовжувати можна лише з останнього текстового блоку.

#### Стрімінг через SDK

```python
# Фрагмент; client — із 4.1. Хелпер .stream() — контекстний менеджер,
# який накопичує фінальне повідомлення.
with client.messages.stream(
    model="claude-opus-5", max_tokens=1024,
    messages=[{"role": "user", "content": "Hello"}],
) as stream:
    for text in stream.text_stream:
        print(text, end="", flush=True)
    message = stream.get_final_message()      # ідентичний результату .create()
```

Другий варіант — `client.messages.create(..., stream=True)`: він повертає лише ітератор подій і
споживає менше пам'яті, бо SDK не будує фінальний об'єкт. `get_final_message()` документований як
такий, що повертає об'єкт, **ідентичний** `.create()`, — це найкорисніший хелпер для випадку
«інкрементальний вивід не потрібен, але `max_tokens` великий і SDK вимагає стрімінгу».

#### Робочий приклад: розбір реального потоку

Нижче — справжній фрагмент SSE-відповіді з документації Anthropic, розібраний власним парсером.
Це код для тих, хто будує прямий HTTP-інтегратор без SDK.

```python
# ── 4.3: розбір реального SSE-потоку з довідки Anthropic ────────────────────
import json

RAW = '''event: message_start
data: {"type": "message_start", "message": {"id": "msg_1nZdL29xx5MUA1yADyHTEsnR8uuvGzszyY", "type": "message", "role": "assistant", "content": [], "model": "claude-opus-5", "stop_reason": null, "stop_sequence": null, "usage": {"input_tokens": 25, "output_tokens": 1}}}

event: content_block_start
data: {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}}

event: ping
data: {"type": "ping"}

event: content_block_delta
data: {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "Hello"}}

event: content_block_delta
data: {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "!"}}

event: content_block_stop
data: {"type": "content_block_stop", "index": 0}

event: message_delta
data: {"type": "message_delta", "delta": {"stop_reason": "end_turn", "stop_sequence": null}, "usage": {"output_tokens": 15}}

event: message_stop
data: {"type": "message_stop"}
'''


def iter_sse(raw: str):
    """Розбирає SSE-потік у пари (ім'я події, розібраний JSON)."""
    event, data = None, []
    for line in raw.splitlines():
        if line.startswith("event:"):
            event = line[len("event:"):].strip()
        elif line.startswith("data:"):
            data.append(line[len("data:"):].strip())
        elif not line.strip() and (event or data):
            yield event, json.loads("".join(data))
            event, data = None, []
    if event or data:
        yield event, json.loads("".join(data))


KNOWN = {"message_start", "content_block_start", "content_block_delta",
         "content_block_stop", "message_delta", "message_stop", "ping", "error"}

text, blocks, unknown, final_usage, n = [], {}, 0, {}, 0
for name, payload in iter_sse(RAW):
    n += 1
    if payload["type"] not in KNOWN:        # нові типи подій можливі — не падаємо
        unknown += 1
    elif name == "content_block_start":
        blocks[payload["index"]] = payload["content_block"]["type"]
    elif name == "content_block_delta" and payload["delta"]["type"] == "text_delta":
        text.append(payload["delta"]["text"])
    elif name == "message_delta":
        final_usage = payload["usage"]

print("подій:", n, "| невідомих типів:", unknown, "| блоки:", blocks)
print("склеєний текст:", repr("".join(text)))
print("фінальний usage:", final_usage, "(кумулятивний)")
```

Фактичний вивід:

```
подій: 8 | невідомих типів: 0 | блоки: {0: 'text'}
склеєний текст: 'Hello!'
фінальний usage: {'output_tokens': 15} (кумулятивний)
```

Три речі у виводі: подія `ping` пройшла крізь парсер і нічого не зламала; `stop_reason` у
`message_start` був `null`, а фінальний прийшов у `message_delta`; `usage` прийшов **без**
`input_tokens` — тут він був лише в `message_start`.

**Типові помилки**

- Парсити `input_json_delta` на кожній події: це частковий JSON, парсити треба після
  `content_block_stop`.
- Забути про подію `error`: вона приходить після 200 OK, коли обробник HTTP-кодів уже не спрацьовує.
- Ставити великий `max_tokens` без стрімінгу: SDK кине `ValueError`, а обхід через `timeout`
  перетворить помилку на обрив з'єднання.
- Пробувати відновити перерваний потік із блоку `tool_use` або `thinking` — документовано неможливо.

**Альтернативи**

| Ситуація | Інструмент | Чому |
|---|---|---|
| Відповідь показується користувачу в реальному часі | `messages.stream()` + `text_stream` | Мінімальний TTFT |
| Довга генерація без інкрементального виводу | `stream()` + `get_final_message()` | Обхід 10-хвилинної межі, результат ідентичний `.create()` |
| Дуже довгий або ненадійний канал | Message Batches API (розділ 10) | Опитування замість безперервного з'єднання |
| Інкрементальна віддача далі клієнту | SSE через ASGI-сервер (розділ 25) | Проксіювання стріму провайдера |

---

### 4.4 Версіонування й сумісність

**Що це.** Три незалежні механізми, які легко переплутати: **версія API** (заголовок
`anthropic-version`), **beta-функції** (заголовок `anthropic-beta`) і **версія SDK** (пакет
`anthropic`). Версіонування моделей — окрема вісь, це розділ 6.

**Навіщо це знати.** Від версії API залежить форма стрімінгу: перехід на `2023-06-01` змінив
семантику дельт і прибрав `data: [DONE]`. Від beta-заголовків залежить доступ до частини
можливостей, і хибне ім'я beta дає 400. А гарантії сумісності API чітко обмежені — знаючи їх, ви
розумієте, які місця коду треба писати захисно.

**Як працює під капотом.**

#### Версія API

Заголовок `anthropic-version` **обов'язковий**; приклад зі сторінки версій — `2023-06-01`. Python SDK
надсилає його сам і типово ставить `2023-06-01`, а документація SDK попереджає: перевизначення
типових заголовків може дати неправильні типи й невизначену поведінку.

| Гарантовано зберігається | Anthropic може змінювати |
|---|---|
| Наявні вхідні параметри | Додавати нові **опційні** вхідні параметри |
| Наявні вихідні параметри | Додавати нові **значення** у вихід |
| | Змінювати умови для конкретних типів помилок |
| | Додавати нові варіанти в enum-подібні значення виходу (наприклад, типи стрімінгових подій) |

Формулювання документації: «Якщо ви користуєтеся API так, як описано в цій довідці, Anthropic не
зламає ваше використання». Гарантія діє на **документоване** використання — це і є причина, чому
невідомі значення enum треба ігнорувати, а не обробляти як помилку.

| Версія | Що змінилося |
|---|---|
| `2023-06-01` | Стрімінгові SSE стали інкрементальними (`" Hello"`, `" my"` замість накопичувальних `" Hello"`, `" Hello my"`); усі події стали **іменованими** (`event:` + `data:`), а не data-only; прибрано зайву подію `data: [DONE]`; прибрано застарілі значення `exception` і `truncated` |
| `2023-01-01` | Початковий реліз |

Попередні версії вважаються застарілими й **можуть бути недоступні новим користувачам**.

#### Beta-функції

| Питання | Відповідь |
|---|---|
| Ім'я заголовка | `anthropic-beta` |
| Угода про імена | `feature-name-YYYY-MM-DD`, де дата — дата релізу beta. Документація каже «typically», тож **бувають імена без дати** |
| Кілька функцій | Через кому або кількома однойменними заголовками; API читає всі |
| У SDK | Параметр `betas=[...]` і `client.beta.messages.create(...)` — SDK сам ставить заголовок |
| Хибне ім'я | 400 `invalid_request_error`: `Unexpected value(s) \`...\` for the \`anthropic-beta\` header` |
| Що може статися з beta | Зламатися з попередженням, бути застарілою або видаленою, мати інші ліміти чи ціни, бути недоступною в частині регіонів |

Два реальні ускладнення з документації. Перше — **заголовки, прив'язані до ендпоінта**:
`/v1/agents`, `/v1/sessions`, `/v1/environments` → `managed-agents-2026-04-01`; `/v1/tunnels` →
`mcp-tunnels-2026-06-22`; `/v1/memory_stores` і підресурси → `agent-memory-2026-07-22`. Друге —
**несумісні пари**: на memory store заголовок `agent-memory-2026-07-22` **замінює**
`managed-agents-2026-04-01`, і обидва разом дають 400.

#### Версія SDK

Пакет `anthropic` дотримується SemVer, але з трьома винятками, переліченими в документації: зміни,
що впливають лише на статичні типи; зміни внутрішніх частин, технічно публічних, але не призначених
для зовнішнього використання; зміни, що «не повинні вплинути на більшість користувачів». Тобто
**мінорна версія може містити ламальні зміни**.

| Факт | Значення |
|---|---|
| Мінімальна версія Python | 3.10 або новіша |
| Як дізнатися встановлену версію | `print(anthropic.__version__)` |
| Актуальний реліз на PyPI | `1.8.0`, опубліковано 22.09.2026 |
| Версія, закріплена в цьому довіднику | `anthropic==1.8.0` (`requirements.txt`) |

#### Робочий приклад: валідація версій і параметрів

Код не робить мережевих викликів — він перевіряє те, що найчастіше дає 400: формат beta-імен і
наявність застарілих параметрів семплювання.

```python
# ── 4.4: сумісність на рівні версії API, beta-заголовків і моделі ───────────
import re

API_VERSION = "2023-06-01"          # SDK надсилає цей заголовок сам

# Beta-імена: угода feature-name-YYYY-MM-DD. Вона саме «typically», тому
# перевірка попереджає, а не падає: у документації є й імена без дати.
BETA_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
DATED_RE = re.compile(r"-\d{4}-\d{2}-\d{2}$")
DOCUMENTED_BETAS = ["context-management-2025-06-27", "managed-agents-2026-04-01",
                    "mcp-tunnels-2026-06-22", "agent-memory-2026-07-22",
                    "thinking-binding-controls-2026-08-01", "user-profiles"]


def check_betas(betas: list[str]) -> list[str]:
    """Повертає попередження про імена без дати; хибний формат — виняток."""
    out = []
    for name in betas:
        if not BETA_RE.match(name):
            raise ValueError(f"некоректне beta-ім'я: {name!r}")
        if not DATED_RE.search(name):
            out.append(f"{name}: без дати у назві — звірте з документацією")
    return out


print("API version за замовчуванням SDK:", API_VERSION)
for warning in check_betas(DOCUMENTED_BETAS):
    print("WARN:", warning)

# Sampling-параметри застаріли: за документацією їх не приймають
# Claude 4.7 і пізніші моделі та Claude Mythos Preview.
NO_SAMPLING_PARAMS = {"claude-opus-4-7", "claude-opus-4-8", "claude-opus-5",
                      "claude-sonnet-5", "claude-fable-5", "claude-fable-5-1",
                      "claude-mythos-5", "claude-mythos-5-1", "claude-mythos-preview"}
LEGACY_SAMPLING = ("temperature", "top_p", "top_k")


def sanitize(payload: dict) -> dict:
    """Прибирає застарілі параметри семплювання для моделей, які їх не приймають."""
    if payload["model"] not in NO_SAMPLING_PARAMS:
        return payload
    dropped = [p for p in LEGACY_SAMPLING if p in payload]
    if dropped:
        print(f"  {payload['model']}: прибрано {dropped} (інакше 400)")
    return {k: v for k, v in payload.items() if k not in LEGACY_SAMPLING}


for model in ("claude-opus-5", "claude-sonnet-4-5"):
    kept = sanitize({"model": model, "max_tokens": 256, "temperature": 0.2})
    print(f"  {model:18} -> ключі: {sorted(kept)}")
```

Фактичний вивід:

```
API version за замовчуванням SDK: 2023-06-01
WARN: user-profiles: без дати у назві — звірте з документацією
  claude-opus-5: прибрано ['temperature'] (інакше 400)
  claude-opus-5      -> ключі: ['max_tokens', 'model']
  claude-sonnet-4-5  -> ключі: ['max_tokens', 'model', 'temperature']
```

Асиметрія у виводі не означає, що `claude-sonnet-4-5` точно приймає `temperature` — лише те, що він
не потрапив до переліку моделей, для яких документація прямо забороняє ці параметри.

Для raw HTTP те саме робиться заголовками `anthropic-version` і `anthropic-beta` (див. таблицю вище).

**Типові помилки**

- Перевизначити `anthropic-version` у SDK «щоб зафіксувати версію»: SDK уже надсилає `2023-06-01`,
  а перевизначення типових заголовків дає невизначену поведінку.
- Писати парсер, який падає на невідомому значенні enum: політика версіонування прямо дозволяє
  додавати нові варіанти.
- Складати beta-ім'я з голови: формат — угода, а не гарантія (`user-profiles` дати не має).
- Комбінувати несумісні beta-заголовки: на memory store `agent-memory-2026-07-22` замінює
  `managed-agents-2026-04-01`.

**Альтернативи**

| Потреба | Механізм | Ціна рішення |
|---|---|---|
| Стабільність формату запиту й відповіді | Фіксований `anthropic-version` | Нові опційні поля не з'являються автоматично |
| Доступ до можливості до загального релізу | `anthropic-beta` | Можливі ламальні зміни, інші ліміти й ціни |
| Передбачувана поведінка моделі | Закріплений model ID (розділ 6) | Потрібна власна процедура міграції |
| Найновіші можливості без beta-заголовків | Оновлення SDK | Мінорна версія може містити ламальні зміни |
| Перевірка сумісності перед релізом | Набір евалюацій (розділ 24) | Витрати на підтримку набору |

---

### 4.5 Коди помилок, 429/529, експоненційний відкат

**Що це.** Три шари обробки збоїв за різними правилами: HTTP-статус із тілом `error`, типізовані
винятки SDK і — окремо — події `error` всередині вже відкритого стріму.

**Навіщо це знати.** Два найчастіші збої в продакшні — 429 і 529 — мають **різні** правильні реакції,
а «spend cap»-варіант 429 не має заголовка `retry-after` і взагалі не минає від повторів. І окремо:
400 не треба ретраїти ніколи.

**Як працює під капотом.**

#### Повний перелік HTTP-помилок

| Код | Тип | Що означає |
|---|---|---|
| 400 | `invalid_request_error` | Проблема з форматом або вмістом запиту; також інші 4XX і досягнення **власного** ліміту витрат (крім Claude Code workspace — там 429) |
| 401 | `authentication_error` | Проблема з API-ключем: формат, відкликання, протермінування |
| 402 | `billing_error` | Проблема з білінгом або платіжною інформацією |
| 403 | `permission_error` | Ключ не має прав на вказаний ресурс |
| 404 | `not_found_error` | Ресурс не знайдено — перевірте шлях і ID |
| 409 | `conflict_error` | Конфлікт зі станом ресурсу: конкурентна зміна або зайняте унікальне значення |
| 413 | `request_too_large` | Перевищено межу байтів для ендпоінта |
| 429 | `rate_limit_error` | Ліміт швидкості, місячний spend cap тіру або ліміт Claude Code workspace |
| 500 | `api_error` | Несподівана внутрішня помилка Anthropic; ретраїти з експоненційним відкатом |
| 504 | `timeout_error` | Таймаут обробки; для довгих запитів — стрімінг або батч |
| 529 | `overloaded_error` | API тимчасово перевантажено |

Форма відповіді завжди однакова:

```json
{"type": "error",
 "error": {"type": "not_found_error", "message": "The requested resource could not be found."},
 "request_id": "req_011CSHoEeqs5C35K2UUqR7Fy"}
```

Документація попереджає: значення всередині цих об'єктів можуть розширюватися, а перелік `type` —
зростати. Тому не порівнюйте тексти повідомлень — орієнтуйтеся на `type` і HTTP-код.

#### Межі розміру запиту

| Ендпоінт | Максимальний розмір |
|---|---|
| Messages API, Token Counting API | 32 MB |
| Message Batches API | 256 MB |
| Files API | 500 MB |

Перевищення дає 413 `request_too_large`. На прямому API цю помилку повертає Cloudflare **до** того,
як запит дійде до серверів Anthropic, — `request_id` у ній не буде.

#### Типізовані винятки SDK

| Статус | Клас | Статус | Клас |
|---|---|---|---|
| 400 | `BadRequestError` | 422 | `UnprocessableEntityError` |
| 401 | `AuthenticationError` | 429 | `RateLimitError` |
| 403 | `PermissionDeniedError` | ≥500 | `InternalServerError` |
| 404 | `NotFoundError` | немає статусу | `APIConnectionError` |
| 409 | `ConflictError` | при таймауті | `APITimeoutError` |

Документація радить ловити типізовані класи (не зіставляти тексти) і обробляти найконкретніші
першими. Приклад із довідки SDK:

```python
# ПОТРЕБУЄ: ANTHROPIC_API_KEY
import anthropic

try:
    message = client.messages.create(
        max_tokens=1024,
        messages=[{"role": "user", "content": "Hello, Claude"}],
        model="claude-opus-5",
    )
except anthropic.APIConnectionError as e:
    print("Сервер недосяжний")
    print(e.__cause__)              # виняток із HTTP-шару, зазвичай httpx2
except anthropic.RateLimitError as e:
    print("429: треба пригальмувати")
except anthropic.APIStatusError as e:
    print("Інший неуспішний статус", e.status_code)
    print(e.response)
```

Типовий таймаут — **10 хвилин**; `timeout` приймає float або об'єкт `httpx2.Timeout` і задається на
клієнті або на конкретному запиті.

#### Автоматичні повтори

| Параметр | Значення |
|---|---|
| Кількість повторів типово | **2** |
| Затримка | Короткий експоненційний відкат |
| `retry-after` | Поважається, якщо присутній |
| Що ретраїться | Помилки з'єднання, 408 Request Timeout, 409 Conflict, 429 Rate Limit, усі ≥500 |
| Як налаштувати | `max_retries` на клієнті або `client.with_options(max_retries=...)` на запиті |

Висновок: не пишіть власний ретрай «щоб напевно» — ви отримаєте до 3× запитів на кожен збій.
Власний шар має сенс лише там, де потрібна інша логіка: черга, зниження моделі, бюджет.

#### 429 — це три різні ситуації

| Ситуація | Ознака | Що робити |
|---|---|---|
| Ліміт швидкості (RPM/ITPM/OTPM) | Є `retry-after`; тіло вказує, який ліміт перевищено | Чекати `retry-after`, потім повторити |
| Місячний spend cap тіру | `rate_limit_error` **без** `retry-after`; `error.details.error_code` = `enforced_spend_limit_reached` | Чекати до 00:00 UTC першого дня наступного місяця або підняти тір. **Повтори, включно з автоматичними, не працюють** |
| Власний ліміт витрат | HTTP **400** `invalid_request_error`, текст починається з `You have reached your specified API usage limits` | Підняти або зняти ліміт |

Документація описує також **acceleration limits**: при різкому зростанні використання можна
отримати 429 навіть у межах лімітів. Лікування — нарощувати трафік поступово й тримати стабільний
профіль навантаження.

#### 529 і середина потоку

`overloaded_error` виникає при високому трафіку в усіх користувачів. У стрімінгу він приходить
**подією**, а не HTTP-статусом:

```sse
event: error
data: {"type": "error", "error": {"type": "overloaded_error", "message": "Overloaded"}}
```

Документація прямо каже: у цьому випадку обробка **не** йде стандартними механізмами. Ретраїти
доводиться з рівня логіки застосунку, а не HTTP-клієнта.

#### Довгі запити

- Уникайте великого `max_tokens` без стрімінгу або батчів — особливо для запитів довших за 10 хвилин.
- SDK перевіряє, що нестрімінговий запит не перевищить 10 хвилин, і кидає `ValueError`; `stream=True`
  або перевизначений `timeout` цю перевірку вимикають. SDK також ставить TCP keep-alive проти
  обривів простоюючих з'єднань — для прямого HTTP-інтегратора документація рекомендує те саме.

#### Робочий приклад: класифікація й відкат

Код не робить мережевих викликів: він показує рішення «ретраїти чи ні» і розклад пауз.

```python
# ── 4.5: що ретраїти, а що ні, і як рахувати паузу ──────────────────────────
import random

RETRYABLE_STATUSES = {408, 409, 429}


def is_retryable(status: int | None = None, *, connection_error: bool = False) -> bool:
    """Ретраяться: помилки з'єднання, 408, 409, 429 і >=500 (за документацією SDK)."""
    if connection_error:
        return True
    return status is not None and (status in RETRYABLE_STATUSES or status >= 500)


def backoff_delay(attempt: int, retry_after: float | None = None,
                  base: float = 0.5, cap: float = 8.0,
                  rng: random.Random | None = None) -> float:
    """Пауза перед спробою. retry-after скасовує формулу; стеля — після джиттера."""
    if retry_after is not None:
        return float(retry_after)              # сервер сам назвав точне число
    delay = base * 2 ** (attempt - 1)
    if rng is not None:
        delay *= 0.5 + rng.random()            # щоб клієнти не били в один момент
    return round(min(cap, delay), 2)


rng = random.Random(7)
print(f"{'спроба':>7} {'звичайна':>10} {'retry-after=30':>15}")
for attempt in range(1, 6):
    print(f"{attempt:>7} {backoff_delay(attempt, rng=rng):>10} "
          f"{backoff_delay(attempt, retry_after=30):>15}")

for label, kwargs in [("з'єднання обірвано", {"connection_error": True}),
                      ("400 invalid_request_error", {"status": 400}),
                      ("401 authentication_error", {"status": 401}),
                      ("429 rate_limit_error", {"status": 429}),
                      ("500 api_error", {"status": 500}),
                      ("529 overloaded_error", {"status": 529})]:
    print(f"{label:28} -> {'ретраїти' if is_retryable(**kwargs) else 'НЕ ретраїти'}")
```

Фактичний вивід:

```
 спроба   звичайна  retry-after=30
      1       0.41            30.0
      2       0.65            30.0
      3        2.3            30.0
      4       2.29            30.0
      5        8.0            30.0
з'єднання обірвано           -> ретраїти
400 invalid_request_error    -> НЕ ретраїти
401 authentication_error     -> НЕ ретраїти
429 rate_limit_error         -> ретраїти
500 api_error                -> ретраїти
529 overloaded_error         -> ретраїти
```

Дві деталі в коді, які легко зробити неправильно: **джиттер застосовується до стелі, а не після
неї** (інакше пауза виходить за `cap`), і **`retry-after` повністю скасовує формулу** — рахувати
експоненту, коли сервер назвав точне число, немає сенсу.

#### Поширені помилки валідації

Кожна повертає 400 `invalid_request_error`:

| Симптом | Причина | Що робити |
|---|---|---|
| `This model does not support assistant message prefill...` | Claude 4.6+, Mythos Preview | Structured outputs або інструкції в промпті |
| `'thinking' or 'redacted_thinking' blocks in the latest assistant message cannot be modified` | Блоки мислення відредаговано, перевпорядковано, відфільтровано або перезібрано | Повертати блоки **як є**, включно з порожніми; фільтруючи, лишати і `thinking`, і `redacted_thinking` |
| `adaptive thinking is not supported on this model` / `"thinking.type.enabled" is not supported for this model` | Claude 4.5 і раніші / Claude 4.7 і пізніші — різні покоління приймають різні режими | `enabled` + `budget_tokens` або `adaptive` + `output_config.effort` відповідно |
| `"thinking.type.disabled" is not supported for this model` | Fable 5.1, Mythos 5.1, Fable 5, Mythos 5, Mythos Preview | Прибрати поле `thinking`; щоб не бачити тексту — `display: "omitted"` |
| `tool_choice: type "tool" and "any" are not supported for this model.` | Fable 5.1 і Mythos 5.1 | `auto` + strict tool use або structured outputs |
| `Invalid 'signature' in 'thinking' block. The block is bound to a different conversation.` | Прокрутка старого блоку мислення при зміненій історії (Fable 5.1) | Тримати історію append-only або `prefix_mismatch_behavior: "drop_block"` |

Повідомлення про блоки мислення **починається з позиції** проблемного блоку, наприклад
`messages.1.content.0` — це найшвидший спосіб його знайти.

**Типові помилки**

- Ретраїти 400, 401, 403, 404, 413: жоден із них не мине сам.
- Ігнорувати `retry-after` при 429 — повтор раніше за вказаний час гарантовано провалиться.
- Вважати, що 429 завжди означає ліміт швидкості: відсутність `retry-after` і `error_code`
  `enforced_spend_limit_reached` означають spend cap, де повтори безглузді.
- Дублювати ретраї: SDK уже робить 2 повтори, а власний цикл на 5 спроб дає до 18 запитів на збій.
- Ловити все одним `except Exception`, втрачаючи `status_code`, тіло `error` і `_request_id`.
- Надсилати понад 32 MB в один запит Messages API: 413 від Cloudflare без `request_id`.

**Альтернативи**

| Підхід | Коли брати | Ціна |
|---|---|---|
| Автоматичні повтори SDK (`max_retries`) | Типовий випадок: 429 і 5xx | Немає контролю над політикою пауз |
| Власний цикл з експоненційним відкатом і джиттером | Кілька інстансів застосунку, потрібна черга | Треба не дублювати ретраї SDK |
| Message Batches API (розділ 10) | Неінтерактивне навантаження | Асинхронність замість миттєвого результату |
| Зниження моделі (fallback) | 529 під навантаженням | Інша якість відповіді (розділ 25) |
| Відновлення стріму з останнього текстового блоку | Обрив мережі в довгій генерації | `tool_use` і `thinking` відновити неможливо |

---

### 4.6 Rate limits: RPM/ITPM/OTPM і як їх планувати

**Що це.** Ліміти швидкості вимірюються трьома незалежними лічильниками на клас моделі: запити за
хвилину (RPM), вхідні токени за хвилину (ITPM) і вихідні токени за хвилину (OTPM). Окремо існують
**spend limits** — максимальні місячні витрати.

**Навіщо це знати.** Перевищення будь-якого ліміту дає 429 із `retry-after`, але головне інше:
**ITPM не враховує прочитані з кешу токени**. Кешування промпту не лише знижує ціну — воно
**піднімає фактичну пропускну здатність**, і це змінює весь розрахунок навантаження.

**Як працює під капотом.**

#### Тири й місячні обмеження

Місячні spend caps тірів: **Start — $500**, **Build — $1 000**, **Scale — $200 000**; на
**Custom** кепа немає, умови узгоджуються з акаунт-командою. Організація потрапляє в тір автоматично
за історією використання; нові організації можуть стартувати в **Evaluation** — з лімітами
**нижчими** за стандартні в таблицях. Документація описує це як запобіжник проти зловживань; ліміти
зростають автоматично разом з історією. Перевищення spend cap зупиняє API до 00:00 UTC першого дня
наступного місяця, і запити повертають 429 **без** `retry-after`.

#### Ліміти швидкості

Стандартні ліміти Start-тіру:

| Клас моделей | RPM | ITPM | OTPM |
|---|---|---|---|
| Claude Fable 5.x | 1 000 | 500 000 | 100 000 |
| Claude Opus 5 | 1 000 | 2 000 000 | 400 000 |
| Claude Opus 4.x | 1 000 | 2 000 000 | 400 000 |
| Claude Sonnet 5 | 1 000 | 2 000 000 | 400 000 |
| Claude Sonnet 4.x | 1 000 | 2 000 000 | 400 000 |
| Claude Haiku 4.5 | 1 000 | 2 000 000 | 400 000 |

Build і Scale дають вищі значення: для Claude Sonnet 5 — 5 000 / 5 000 000 / 1 000 000 у Build і
10 000 / 10 000 000 / 2 000 000 у Scale. Ліміти задані **на клас моделі**, і частина класів має
**спільні кошики**:

| Кошик | Що в ньому |
|---|---|
| Fable | Fable 5.1 і Fable 5 — спільний ліміт; Mythos 5.1 і Mythos 5 мають окремий спільний ліміт на тих самих умовах |
| Opus 4.x | Opus 4.8, 4.7, 4.6 і 4.5 — спільний; **Claude Opus 5 має окремий** |
| Sonnet 4.x | Sonnet 4.6 і 4.5 — спільний; **Claude Sonnet 5 має окремий** |

Практичний наслідок: переведення половини трафіку з Opus 4.7 на Opus 4.8 **не** дає двох лімітів.

#### Алгоритм token bucket

Документація називає механізм прямо: **token bucket**, ємність якого поповнюється безперервно до
максимуму, а не скидається у фіксовані інтервали. І окреме попередження, яке ламає наївні
розрахунки: ліміт 60 RPM може застосовуватися як 1 запит на секунду, тож короткі сплески
перевищують ліміт і викликають помилки.

```python
# ── 4.6: чому ліміт «на хвилину» насправді діє посекундно ───────────────────
ITPM_LIMIT, REQUEST_TOKENS = 2_000_000, 150_000     # Start-тір, великий RAG-запит


class TokenBucket:
    """Ємність = ліміт за хвилину; поповнення = ліміт/60 за секунду."""

    def __init__(self, capacity: float, refill_per_sec: float):
        self.capacity = capacity
        self.refill_per_sec = refill_per_sec
        self.level = 0.0

    def tick(self, seconds: float) -> None:
        self.level = min(self.capacity, self.level + self.refill_per_sec * seconds)

    def take(self, amount: float) -> bool:
        if amount > self.level:
            return False
        self.level -= amount
        return True


bucket = TokenBucket(ITPM_LIMIT, ITPM_LIMIT / 60)
bucket.tick(60)                                  # хвилина простою — бак повний
print(f"після хвилини простою в баці: {bucket.level:,.0f} токенів")

sent = 0
while bucket.take(REQUEST_TOKENS):
    sent += 1
print(f"без пауз пройшло: {sent} запитів ({sent * REQUEST_TOKENS:,} токенів) — далі 429")

bucket.tick(1.0)
print(f"за 1 секунду відновилось: {bucket.refill_per_sec:,.0f}; "
      f"наступний запит пройде: {bucket.take(REQUEST_TOKENS)}")
print(f"чекати на ще один: ~{REQUEST_TOKENS / bucket.refill_per_sec:.1f} с")
```

Фактичний вивід:

```
після хвилини простою в баці: 2,000,000 токенів
без пауз пройшло: 13 запитів (1,950,000 токенів) — далі 429
за 1 секунду відновилось: 33,333; наступний запит пройде: False
чекати на ще один: ~4.5 с
```

Модель ідеалізована: справжній ліміт може застосовуватися коротшими інтервалами, а `input_tokens`
оцінюється **на початку запиту й уточнюється під час його виконання** (це прямо описано в
документації). Висновок не змінюється: великі запити споживають бак нерівномірно, і після сплеску
доводиться чекати.

#### Cache-aware ITPM — головний важіль

| Лічильник | Чи входить в ITPM |
|---|---|
| `input_tokens` (токени після останньої точки кешування) | **Так** |
| `cache_creation_input_tokens` (запис у кеш) | **Так** |
| `cache_read_input_tokens` (читання з кешу) | **Ні** — для більшості моделей |

Виняток, названий у документації: **Claude Haiku 3.5** (retired, окрім Bedrock і Google Cloud)
**враховує** `cache_read_input_tokens` у ITPM.

Документація дає числовий приклад: при ліміті 2 000 000 ITPM і 80% влучань у кеш ви ефективно
обробляєте **10 000 000** вхідних токенів на хвилину. Звідси рекомендація: кешуйте повторюваний
контент — системні інструкції, великі документи, визначення інструментів, історію діалогу.

OTPM працює інакше: оцінюється **в реальному часі**, у міру генерації, і враховує лише фактично
згенеровані токени; `max_tokens` на нього не впливає. Ліміти застосовуються **окремо для кожної
моделі**, але **спільні для всіх значень `inference_geo`** — `"us"` і `"global"` беруть із одного пулу.

#### Заголовки відповіді

| Заголовок | Що показує |
|---|---|
| `retry-after` | Скільки секунд чекати. **Не надсилається** при 429 через spend cap |
| `anthropic-ratelimit-requests-*` | `-limit`, `-remaining`, `-reset` для запитів |
| `anthropic-ratelimit-input-tokens-*` | Те саме для вхідних токенів |
| `anthropic-ratelimit-output-tokens-*` | Те саме для вихідних токенів |
| `anthropic-ratelimit-tokens-*` | Значення **найжорсткішого** ліміту, що діє зараз |
| `anthropic-priority-*` | Ліміти Priority Tier |

Залишки токенів округлені до найближчої тисячі. Читати їх можна програмно — тільки з реальним ключем:

```python
# ПОТРЕБУЄ: ANTHROPIC_API_KEY. with_raw_response дає доступ до заголовків.
response = client.messages.with_raw_response.create(
    model="claude-opus-5", max_tokens=64,
    messages=[{"role": "user", "content": "ping"}],
)
print(response.headers.get("anthropic-ratelimit-input-tokens-remaining"))
print(response.headers.get("retry-after"))          # є лише при 429
```

#### Ліміти інших API

| API | Ліміти |
|---|---|
| Message Batches API | Власні, **спільні для всіх моделей**: RPM + ліміт запитів у черзі. Start: 1 000 / 200 000 / 100 000 на батч. Build: 2 000 / 300 000 / 100 000. Scale: 4 000 / 500 000 / 100 000 |
| Managed Agents | Окремі: створення — 300 RPM, читання — 1 200 RPM |
| Fast mode | Окремі ліміти для `speed: "fast"` на Opus 5 і Opus 4.8; перевищення — 429 із `retry-after` |

«Batch request» тут — **частина** батчу: батч може містити тисячі таких запитів, і кожен рахується в
ліміті черги, доки його не оброблено успішно.

#### Робочий приклад: планування навантаження

Найкорисніший розрахунок перед запуском: скільки запитів на хвилину витримає профіль і який
лімітер спрацює першим.

```python
# ── 4.6: планування навантаження під ліміти Start-тіру ──────────────────────
# Ліміти взяті з таблиці Start-тіру для Claude Sonnet 5.
RPM_LIMIT, ITPM_LIMIT, OTPM_LIMIT = 1_000, 2_000_000, 400_000

RPM_TARGET = 600           # цільовий трафік
AVG_INPUT = 3_500          # середній вхід, токенів
CACHED_PREFIX = 2_400      # незмінна частина (системний промпт + документ)
CACHE_HIT_RATE = 0.80      # частка префікса, що читається з кешу
AVG_OUTPUT = 400

cache_read = int(CACHED_PREFIX * CACHE_HIT_RATE)
cache_creation = CACHED_PREFIX - cache_read
uncached = AVG_INPUT - CACHED_PREFIX

# У ITPM входить УСЕ, крім cache_read: і хвіст, і запис у кеш.
itpm_per_request = uncached + cache_creation
itpm, otpm = RPM_TARGET * itpm_per_request, RPM_TARGET * AVG_OUTPUT

print(f"вхід {AVG_INPUT} = {uncached} без кешу + {cache_creation} запис "
      f"+ {cache_read} читання")
print(f"в ITPM іде {itpm_per_request} токенів на запит")
print(f"{'лімітер':>7} {'факт':>11} {'ліміт':>11} {'зайнято':>8} {'стеля RPM':>10}")
for name, actual, limit in (("RPM", RPM_TARGET, RPM_LIMIT),
                            ("ITPM", itpm, ITPM_LIMIT),
                            ("OTPM", otpm, OTPM_LIMIT)):
    per_request = actual / RPM_TARGET
    print(f"{name:>7} {actual:>11,} {limit:>11,} "
          f"{actual / limit:>7.0%} {int(limit / per_request):>10,}")

limits = (("RPM", RPM_LIMIT, 1), ("ITPM", ITPM_LIMIT, itpm_per_request),
          ("OTPM", OTPM_LIMIT, AVG_OUTPUT))
ceiling = min(int(limit / per) for _, limit, per in limits)
binding = [name for name, limit, per in limits if int(limit / per) == ceiling]
print(f"стеля: {ceiling:,} RPM; вузьке місце — {', '.join(binding)}")
```

Фактичний вивід:

```
вхід 3500 = 1100 без кешу + 480 запис + 1920 читання
в ITPM іде 1580 токенів на запит
лімітер        факт       ліміт  зайнято  стеля RPM
    RPM         600       1,000     60%      1,000
   ITPM     948,000   2,000,000     47%      1,265
   OTPM     240,000     400,000     60%      1,000
стеля: 1,000 RPM; вузьке місце — RPM, OTPM
```

Висновок: при 80% влучань у кеш ITPM використано лише на 47%, а стелю визначають **RPM і OTPM**.
Далі доведеться або знижувати RPM (батчами, чергою), або скорочувати середню довжину відповіді. Це і
є сенс планування: знати, який із трьох лімітів спрацює першим, ще до першого 429.

**Типові помилки**

- Рахувати ITPM за повним входом: прочитані з кешу токени в ліміт не входять.
- Переносити ліміти з одної моделі на іншу: кошики Opus 4.x і Sonnet 4.x спільні, Opus 5 і Sonnet 5 —
  окремі.
- Вважати, що хвилинний ліміт можна витратити одним сплеском.
- Очікувати `retry-after` у кожному 429 — при spend cap його немає.

**Альтернативи**

| Ситуація | Що робити | Ефект |
|---|---|---|
| Не влізаєте в ITPM | Кешувати префікс (розділ 9) | Читання з кешу не рахується в ITPM |
| Не влізаєте в OTPM | Скоротити вихід, обмежити `effort`, занизити `max_tokens` | Пряме зменшення лічильника |
| Не влізаєте в RPM | Батчі (розділ 10) з їхніми окремими лімітами | Інший пул лімітів |
| Сплески трафіку | Черга з обмеженням паралелізму (розділ 25) | Розподіл навантаження замість 429 |
| Потрібні вищі ліміти | «Request rate limit increase» у Console; на Claude Platform on AWS — через акаунт-менеджера | Зміна тіру або індивідуальні ліміти |
| Різні ліміти для команд | Ліміти робочого простору | Не задаються на Default Workspace; ліміти організації діють завжди |
| Розподілити навантаження | Кілька моделей мають окремі ліміти | Трафік розподіляється між пулами |

**Джерела**

- [Anthropic — Messages API](https://platform.claude.com/docs/en/api/messages) — ендпоінт `POST /v1/messages`, перелік полів тіла, об'єкт `Message`, значення `stop_reason`, структура `usage`, застарівання `temperature`/`top_p`/`top_k`
- [Anthropic — API overview](https://platform.claude.com/docs/en/api/overview) — обов'язкові заголовки, межі розміру запиту, заголовки відповіді
- [Anthropic — Versions](https://platform.claude.com/docs/en/api/versioning) — заголовок `anthropic-version`, гарантії сумісності, історія версій
- [Anthropic — Beta headers](https://platform.claude.com/docs/en/api/beta-headers) — `anthropic-beta`, угода про імена, заголовки для конкретних ендпоінтів
- [Anthropic — Streaming messages](https://platform.claude.com/docs/en/build-with-claude/streaming) — послідовність подій, типи дельт, `ping`, події `error`, відновлення потоку
- [Anthropic — Using the Messages API](https://platform.claude.com/docs/en/build-with-claude/working-with-messages) — stateless-модель, багатоходові розмови, system-хід усередині діалогу, обмеження prefill
- [Anthropic — Claude API errors](https://platform.claude.com/docs/en/api/errors) — HTTP-помилки, форма помилки, `request_id`, ретраї, помилки валідації
- [Anthropic — Rate limits](https://platform.claude.com/docs/en/api/rate-limits) — тири, spend caps, RPM/ITPM/OTPM, cache-aware ITPM, token bucket, заголовки, ліміти інших API
- [Anthropic — Python SDK](https://platform.claude.com/docs/en/cli-sdks-libraries/sdks/python) — стрімінгові хелпери, типізовані винятки, `max_retries`, таймаути, SemVer-політика
- [Anthropic — Stop reasons and fallback](https://platform.claude.com/docs/en/build-with-claude/handling-stop-reasons) — значення `stop_reason` і дії для кожного
- [Anthropic — Context windows](https://platform.claude.com/docs/en/build-with-claude/context-windows) — що входить у контекстне вікно, `model_context_window_exceeded`
- [Anthropic — Choosing a model](https://platform.claude.com/docs/en/about-claude/models/choosing-a-model) — чому налаштування `effort` часто кращий важіль, ніж зміна моделі
- Локальні знімки джерел: `research/02/messages-api.md`, `research/02/streaming.md`, `research/02/versioning.md`, `research/02/working-with-messages.md`, `research/02/overload.md`, `research/02/rate-limits.md`, `research/02/python-sdk.md`, `research/02/api-overview.md`, `research/02/beta-headers.md`, `research/02/handling-stop-reasons.md`, `research/02/context-windows.md`
- [PyPI — anthropic](https://pypi.org/pypi/anthropic/json) — актуальна версія SDK `1.8.0` (22.09.2026), вимога Python ≥ 3.10
