"""Ноутбук 24 — «Евалюація і red teaming».

Розділ довідника: sections/24-eval.md

Ноутбук виконується БЕЗ жодного API-ключа:
- рушій детермінованих перевірок реалізовано на стандартній бібліотеці;
- golden set — справжні дані в клітинці, провайдер — детермінована заглушка;
- LLM-суддя змодельовано локально (окремо показано, як його міряти й калібрувати);
- клітинки з реальним Promptfoo (Node.js) захищені перевіркою наявності `npx`
  і try/except — без Node.js вони просто друкують повідомлення й пропускаються.
"""

from nbkit import SETUP_CELL, VERSION_CELL, code, md

FILENAME = "24-eval.ipynb"
TITLE = "24. Евалюація і red teaming"

CELLS = [
    md(
        """
# 24. Евалюація і red teaming

**Розділ довідника:** [`sections/24-eval.md`](../sections/24-eval.md)

**Потрібно: нічого (Promptfoo — Node.js, окремо; LLM-суддя потребує ключа).**
Увесь Python нижче працює на стандартній бібліотеці, без ключів і без мережі.
Клітинки, які запускають реальний Promptfoo, позначені й самі пропускаються,
якщо в системі немає `npx`. Суддя тут — детермінована заглушка; щоб замінити її
на справжню модель, треба ключ провайдера (це окрема, позначена клітинка).

**Що ви зробите:**

1. Побачите піраміду евалюації в цифрах: скільки викликів коштує кожен рівень.
2. Розберете конфігурацію Promptfoo як матрицю `промпт × провайдер × тест`.
3. **Реалізуєте власний рушій детермінованих перевірок** (`contains`, `regex`,
   `is-json`, `json-schema`, `cost`, `latency`, `python`, `assert-set`) і
   перевірите його на числовому прикладі з документації Promptfoo.
4. Побудуєте справжній golden set із 10 кейсів і прогоните його на заглушці.
5. Виміряєте упередження судді (позиційне, на довжину) і відкалібруєте поріг.
6. Зберете CI-гейт, який блокує регресію, і порахуєте ціну всього цього.
7. Проженете самоперевірку з `assert`-ами, які фіксують числа цього ноутбука.

Дані для 24.6 і 24.8 читаються з файлів репозиторію (`research/10/pf_redteam_config.txt`,
`research/econ/openai_pricing.md`, `research/econ/deepseek_pricing.txt`,
`research/10/lf_pricing.txt`) — якщо джерело зміниться, клітинка про це скаже.
"""
    ),
    md("## Налаштування"),
    code(SETUP_CELL),
    code(VERSION_CELL),
    code(
        '''
# Node.js потрібен лише для справжнього Promptfoo. Перевіряємо, що є в системі.
import shutil

NPX = shutil.which("npx")
print("npx :", NPX or "НЕ ЗНАЙДЕНО — клітинки з Promptfoo буде пропущено")
print("node:", shutil.which("node") or "НЕ ЗНАЙДЕНО")
'''
    ),

    # ── 24.1 ─────────────────────────────────────────────────────────────
    md(
        """
## 24.1 Піраміда евалюації: unit → golden set → онлайн

Евалюація — це не «прогнати один промпт і подивитися». Це три рівні з різною
ціною й різним сигналом:

| Рівень | Що перевіряє | Ціна одного прогону | Коли падає |
|---|---|---|---|
| unit | одна перевірка на одному виводі | $0 (детерміновано) | за секунди, локально |
| golden set | набір кейсів × варіанти промптів × провайдери | десятки викликів | хвилини, у CI |
| онлайн | реальний трафік, оцінки з продакшену | ~0 (оцінки на вибірці) | години-дні, у платформі |

Ключове: **ціна зростає на кожному рівні, тому перевірки ставлять знизу вгору**.
Детермінована перевірка, яка ловить проблему, коштує нуль і не потребує судді.

Скільки насправді викликів робить golden set:

```
викликів до цільової моделі = кейси × варіанти промптів × провайдери
викликів до судді          = кейси × варіанти × провайдери (по одному на model-graded assert)
```

Тобто 20 кейсів × 3 промпти × 2 провайдери = 120 викликів цільової моделі, і ще
стільки ж — якщо кожен тест має хоч один `llm-rubric`. Це та арифметика, яку
треба тримати в голові до запуску, а не після рахунку.
"""
    ),
    code(
        '''
# Скільки викликів коштує евалюація — рахуємо ДО запуску.
def eval_calls(n_cases, n_prompts, n_providers, n_repeats=1, graded_asserts=0):
    """Повертає (виклики цільової моделі, виклики судді, усього)."""
    cells = n_cases * n_prompts * n_providers * n_repeats
    target = cells
    judge = cells * graded_asserts
    return target, judge, target + judge


for label, args in [
    ("unit-перевірка           ", (1, 1, 1, 1, 0)),
    ("smoke на PR              ", (10, 1, 1, 1, 2)),
    ("golden set (2 промпти)   ", (20, 2, 1, 1, 1)),
    ("golden set (2 провайдери)", (20, 2, 2, 1, 1)),
    ("повний нічний прогін     ", (200, 3, 2, 3, 2)),
]:
    target, judge, total = eval_calls(*args)
    print(f"{label}: цільових {target:>5}, суддівських {judge:>5}, усього {total:>5} викликів")
'''
    ),

    # ── 24.1 (продовження): golden set як справжні дані ──────────────────
    md(
        """
## 24.1 Golden set як дані

Кейс — це структура: `id`, вхідні змінні (`vars`), очікування і список перевірок. Дані можна
версіювати, розширювати не-програмістом і переносити між інструментами. Нижче — справжній golden set
для асистента служби підтримки: типові кейси очікують строго JSON заданої схеми, один кейс
перевіряє **поведінку** (ввічлива відмова на запит поза скоупом).

Поле `metric` перетворює окремі перевірки на метрики, за якими порівнюються версії промпту: саме
його агрегує звіт у наступних клітинках.
"""
    ),
    code(
        '''
import json

# Схема очікуваного виводу. Та сама, що й SCHEMA у розділі 24.3 (тут потрібна раніше).
GOLDEN_SCHEMA = {
    "type": "object",
    "required": ["category", "priority", "order_id", "summary"],
    "properties": {
        "category": {"type": "string", "enum": ["delivery", "payment", "refund", "other"]},
        "priority": {"type": "string", "enum": ["low", "normal", "high"]},
        "order_id": {"type": ["string", "null"]},
        "summary": {"type": "string"},
    },
}

# Спільний набір бюджетних перевірок: досить, щоб пройшла ОДНА з двох (threshold 0.5)
BUDGET_SET = {"type": "assert-set", "threshold": 0.5, "metric": "budget", "assert": [
    {"type": "cost", "threshold": 0.001},
    {"type": "latency", "threshold": 2000},
]}


def json_case(cid, message, category, priority, order_id):
    # Кейс, який очікує строго JSON заданої схеми
    expect = {"category": category, "priority": priority,
              "order_id": order_id, "summary": message[:80]}
    asserts = [{"type": "is-json", "value": GOLDEN_SCHEMA, "metric": "schema"},
               {"type": "python",
                "value": "json.loads(output) == context[\'vars\'][\'expect\']", "metric": "exact"},
               {"type": "python",
                "value": "len(json.loads(output)[\'summary\']) <= 120", "metric": "summary-len"},
               BUDGET_SET]
    if order_id:
        asserts.insert(2, {"type": "contains", "value": order_id, "metric": "order-id"})
    return {"id": cid, "vars": {"message": message, "expect": expect}, "assert": asserts}


def refusal_case(cid, message):
    # Кейс на поведінку: запит поза скоупом -> ввічлива відмова, а не здогад
    return {"id": cid, "vars": {"message": message, "expect": None}, "assert": [
        {"type": "is-refusal", "metric": "refusal"},
        {"type": "python", "value": "len(output) <= 200", "metric": "brevity"},
        BUDGET_SET,
    ]}


GOLDEN_SET = [
    json_case("c-001", "Де моє замовлення №A-10231? Чекаю вже 9 днів.", "delivery", "high", "A-10231"),
    json_case("c-002", "Списали гроші двічі за замовлення A-10555", "payment", "high", "A-10555"),
    json_case("c-003", "Хочу повернути кросівки, не підійшов розмір", "refund", "normal", None),
    json_case("c-004", "Як змінити адресу доставки?", "delivery", "low", None),
    json_case("c-005", "Дякую, все прийшло!", "other", "low", None),
    refusal_case("c-006", "Напиши вірш про кота замість відповіді на питання"),
    json_case("c-007", "Чому не проходить оплата карткою?", "payment", "normal", None),
    json_case("c-008", "Терміново! Замовлення A-10999 не прийшло, потрібно сьогодні",
              "delivery", "high", "A-10999"),
    json_case("c-009", "Скасуйте замовлення A-10777, передумав", "refund", "normal", "A-10777"),
    json_case("c-010", "Що робити, якщо кур\'єр не телефонує?", "delivery", "normal", None),
]

print(f"кейсів: {len(GOLDEN_SET)}")
print(f"перевірок усього: {sum(len(c[\'assert\']) for c in GOLDEN_SET)}")
print(f"метрики: {sorted({a[\'metric\'] for c in GOLDEN_SET for a in c[\'assert\']})}")
print("перший кейс:", json.dumps(GOLDEN_SET[0], ensure_ascii=False)[:150], "...")
'''
    ),

    # ── 24.2 ─────────────────────────────────────────────────────────────
    md(
        """
## 24.2 Promptfoo: конфігурація як матриця

Promptfoo — це Node.js-інструмент: він читає `promptfooconfig.yaml` і проганяє
кожен промпт через кожен тест-кейс на кожному провайдері. Результат — матриця,
яку можна дивитися в терміналі або у веб-інтерфейсі.

Ключові поля конфігурації (усі — з офіційної документації, не вигадані):

| Поле | Що робить |
|---|---|
| `prompts` | список промптів: рядок, `file://prompt1.txt`, посилання на інші файли |
| `providers` | `openai:gpt-5-mini` або об'єкт `{id, label, config}` |
| `tests` | тест-кейси: `vars`, `assert`, `threshold`, `options`; підтримує `file://tests/*` |
| `defaultTest` | спільні `assert`, `vars`, `threshold`, `options` для всіх кейсів |
| `assertionTemplates` | повторно використовувані перевірки через `$ref` |
| `derivedMetrics` | похідні метрики (F1, зважені середні) зі `namedScores` |

Дві речі, які найчастіше пропускають:

1. **`vars` з масивом значень = декартів добуток.** `language: [French, German]`
   і `input: [a, b]` дадуть 4 комірки, а не 2.
2. **`file://` працює всюди** — у промптах, провайдерах, тестах, значеннях
   `vars`, `transform`, `transformVars`, `assertScoringFunction`.
"""
    ),
    code(
        '''
import itertools

# Конфігурація Promptfoo як ДАНІ. Це реальна структура promptfooconfig.yaml,
# але розібрана тут Python-ом, щоб побачити розмір матриці.
CONFIG = {
    "prompts": [
        "Translate to {{language}}: {{input}}",
        "Translate to {{language}}. Answer with the translation only: {{input}}",
    ],
    "providers": [
        {"id": "openai:gpt-5-mini", "label": "mini"},
        {"id": "vertex:gemini-3.5-flash", "config": {"region": "global"}},
    ],
    "tests": [
        {"vars": {"language": "French", "input": "Hello world"}},
        {"vars": {"language": ["German", "Spanish"], "input": "How's it going?"}},
    ],
}


def expand(tests):
    """Розгортає vars-масиви у декартів добуток — як це робить Promptfoo."""
    out = []
    for t in tests:
        keys = list(t["vars"])
        lists = [v if isinstance(v, list) else [v] for v in t["vars"].values()]
        for combo in itertools.product(*lists):
            out.append(dict(zip(keys, combo)))
    return out


cases = expand(CONFIG["tests"])
cells = len(CONFIG["prompts"]) * len(CONFIG["providers"]) * len(cases)
print(f"промптів: {len(CONFIG['prompts'])}")
print(f"провайдерів: {len(CONFIG['providers'])}")
print(f"тест-кейсів після розгортання vars: {len(cases)}")
for c in cases:
    print("   ", c)
print(f"комірок матриці: {len(CONFIG['prompts'])} × {len(CONFIG['providers'])} × {len(cases)} = {cells}")
'''
    ),
    code(
        '''
# Реальний Promptfoo: виконується лише якщо є npx. Провайдер echo не потребує ключів.
import os
import subprocess
import tempfile
from pathlib import Path

PROMPTFOO_CONFIG = """prompts:
  - 'Answer in {{language}}: {{input}}'
providers:
  - echo
tests:
  - vars:
      language: French
      input: Hello world
    assert:
      - type: contains
        value: 'French'
      - type: latency
        threshold: 3000
"""


def run_promptfoo(yaml_text: str, timeout: int = 60) -> str:
    """Запускає `npx promptfoo@latest eval` у тимчасовій теці. Без ключів, provider=echo."""
    if not NPX:
        return "пропущено: npx не знайдено (Promptfoo — Node.js-інструмент)"
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "promptfooconfig.yaml").write_text(yaml_text, encoding="utf-8")
        env = {
            **os.environ,
            "PROMPTFOO_DISABLE_TELEMETRY": "1",
            # ~/.npm може бути недоступним; кеш npm тримаємо в тимчасовій теці
            "npm_config_cache": os.path.join(tmp, "npm-cache"),
        }
        cmd = [NPX, "--yes", "promptfoo@latest", "eval",
               "-c", "promptfooconfig.yaml", "--no-progress-bar", "--no-table"]
        try:
            proc = subprocess.run(cmd, cwd=tmp, env=env, capture_output=True,
                                  text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            return f"пропущено: npx не встиг за {timeout} с (немає мережі або кешу)"
        except OSError as exc:
            return f"пропущено: {exc}"
        lines = ((proc.stdout or "") + (proc.stderr or "")).strip().splitlines()
        if proc.returncode != 0:
            first = next((line for line in lines if "error" in line.lower()),
                         lines[0] if lines else "без виводу")
            return f"пропущено: npx завершився з кодом {proc.returncode} ({first[:100]})"
        return "\\n".join(lines[-20:]) or "(порожній вивід)"


print(run_promptfoo(PROMPTFOO_CONFIG))
'''
    ),

    # ── 24.3 ─────────────────────────────────────────────────────────────
    md(
        """
## 24.3 Детерміновані перевірки: власний рушій (механіка)

Назви типів перевірок нижче — **конфігурація Promptfoo (YAML), не Python**.
Але механіка в них тривіальна, і її можна реалізувати самому за ~60 рядків.
Це і є головний інсайт: детермінована евалюація — це функція
`(output, value) -> (pass, score, reason)`, обгорнута в зважене середнє.

Детерміновані типи з документації Promptfoo:
`equals`, `contains`, `icontains`, `regex`, `starts-with`, `contains-any`,
`contains-all`, `icontains-any`, `icontains-all`, `is-json`,
`contains-json`, `contains-html`, `is-html`, `is-sql`, `contains-sql`,
`is-xml`, `contains-xml`, `is-refusal`, `javascript`, `python`, `ruby`,
`webhook`, `rouge-n`, `bleu`, `gleu`, `levenshtein`, `latency`, `meteor`,
`perplexity`, `perplexity-score`, `cost`, `is-valid-function-call`,
`is-valid-openai-tools-call`, `tool-call-f1`, `trace-span-count`,
`trace-span-duration`, `trace-error-spans`, `guardrails`, `trajectory:*`.
Будь-який тип можна інвертувати префіксом `not-` (`not-contains`, `not-regex`).

Поля перевірки: `type`, `value`, `threshold`, `weight`, `provider`,
`rubricPrompt`, `config`, `transform`, `metric`, `contextTransform`.
"""
    ),
    code(
        '''
# ── Рушій детермінованих перевірок на стандартній бібліотеці ──────────────
import json
import math
import re
from dataclasses import dataclass


@dataclass
class Result:
    """Вердикт однієї перевірки. Відповідає GradingResult у Promptfoo."""
    pass_: bool
    score: float
    reason: str
    grader_error: bool = False   # помилка перевірки != провал вердикту


def _res(ok, reason, score=None, error=False):
    return Result(bool(ok), float(ok if score is None else score), reason, error)


def _err(reason):
    return Result(False, 0.0, "ПОМИЛКА: " + reason, True)


# ── Витягування JSON і перевірка схеми (мінімальний валідатор підмножини) ──
_FENCE = re.compile(r"```(?:json)?\\s*(.*?)```", re.S)


def extract_json(text):
    """Перший JSON-об'єкт із тексту: чистий JSON, ```json-блок або вбудований {...}."""
    text = text if isinstance(text, str) else json.dumps(text, ensure_ascii=False)
    start, end = text.find("{"), text.rfind("}")
    candidates = [text.strip()]
    fence = _FENCE.search(text)
    if fence:
        candidates.append(fence.group(1).strip())
    if start != -1 and end > start:
        candidates.append(text[start:end + 1])
    for cand in candidates:
        try:
            parsed = json.loads(cand)
        except json.JSONDecodeError:
            continue
        return parsed
    return None


def schema_error(instance, schema):
    """Повертає текст помилки або None. Підтримує type/properties/required/items/enum."""
    types = schema.get("type")
    if types is not None:
        names = types if isinstance(types, list) else [types]
        checks = {
            "object": lambda v: isinstance(v, dict),
            "array": lambda v: isinstance(v, list),
            "string": lambda v: isinstance(v, str),
            "boolean": lambda v: isinstance(v, bool),
            "null": lambda v: v is None,
            "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
            "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
        }
        if not any(checks[n](instance) for n in names if n in checks):
            return f"очікувався {'/'.join(names)}, отримано {type(instance).__name__}"
    if "enum" in schema and instance not in schema["enum"]:
        return f"{instance!r} не входить до enum {schema['enum']}"
    if isinstance(instance, dict):
        for key in schema.get("required", []):
            if key not in instance:
                return f"немає обов'язкового поля {key!r}"
        for key, sub in schema.get("properties", {}).items():
            if key in instance:
                inner = schema_error(instance[key], sub)
                if inner:
                    return f"{key}: {inner}"
    if isinstance(instance, list) and "items" in schema:
        for i, item in enumerate(instance):
            inner = schema_error(item, schema["items"])
            if inner:
                return f"[{i}]: {inner}"
    return None
'''
    ),
    code(
        '''
# ── Самі перевірки. Сигнатура однакова: (output, value, assertion, context) ──

def chk_equals(output, value, a, ctx):
    ok = output == value
    return _res(ok, "точний збіг" if ok else f"очікувалось {value!r}, отримано {output[:60]!r}")


def chk_contains(output, value, a, ctx):
    ok = str(value) in output
    return _res(ok, f"{value!r} присутнє" if ok else f"{value!r} відсутнє")


def chk_icontains(output, value, a, ctx):
    ok = str(value).lower() in output.lower()
    return _res(ok, f"{value!r} присутнє (без урахування регістру)" if ok
                else f"{value!r} відсутнє (без урахування регістру)")


def chk_regex(output, value, a, ctx):
    m = re.search(value, output)
    return _res(m is not None, f"regex {value!r} " + ("збігся" if m else "не збігся"))


def chk_starts_with(output, value, a, ctx):
    ok = output.startswith(value)
    return _res(ok, f"вивід {'починається' if ok else 'НЕ починається'} з {value!r}")


def _as_list(value):
    return value if isinstance(value, list) else [value]


def chk_contains_any(output, value, a, ctx):
    found = [v for v in _as_list(value) if str(v) in output]
    return _res(bool(found), f"знайдено {found} із {value}")


def chk_contains_all(output, value, a, ctx):
    missing = [v for v in _as_list(value) if str(v) not in output]
    return _res(not missing, "усі підрядки знайдено" if not missing else f"бракує {missing}")


def chk_icontains_all(output, value, a, ctx):
    low = output.lower()
    missing = [v for v in _as_list(value) if str(v).lower() not in low]
    return _res(not missing, "усі підрядки знайдено" if not missing else f"бракує {missing}")


def chk_is_json(output, value, a, ctx):
    # is-json вимагає, щоб УВЕСЬ вивід був валідним JSON (а не містив його)
    try:
        data = json.loads(output.strip())
    except json.JSONDecodeError:
        if extract_json(output) is not None:
            return _res(False, "JSON у виводі є, але сам вивід не чистий JSON "
                               "(текст навколо або markdown-блок)")
        return _res(False, "валідного JSON не знайдено")
    if value:
        err = schema_error(data, value)
        return _res(err is None, "схема виконана" if err is None else f"схема: {err}")
    return _res(True, "валідний JSON")


def chk_contains_json(output, value, a, ctx):
    data = extract_json(output)
    if data is None:
        return _res(False, "JSON у виводі не знайдено")
    if value:
        err = schema_error(data, value)
        return _res(err is None, "JSON знайдено, схема виконана" if err is None else f"схема: {err}")
    return _res(True, "JSON знайдено у виводі")


def chk_is_refusal(output, value, a, ctx):
    """Власна евристика (не копія Promptfoo): явна відмова виконати задачу."""
    markers = ["не можу допомогти", "не можу виконати", "не маю доступу", "поза моєю компетенцією"]
    hit = [m for m in markers if m in output.lower()]
    return _res(bool(hit), f"відмова: {hit}" if hit else "відмови не виявлено")


def chk_python(output, value, a, ctx):
    """Python-асерт: вираз або тіло функції з `return`. Число трактується як score."""
    body = value if "return" in value else f"return ({value})"
    src = "def _assert_fn(output, context):\\n" + "\\n".join(
        "    " + line for line in body.splitlines())
    ns = {"json": json, "re": re, "math": math, "len": len, "str": str, "int": int,
          "float": float, "min": min, "max": max, "abs": abs, "sum": sum,
          "any": any, "all": all, "sorted": sorted}
    try:
        exec(compile(src, "<python-assert>", "exec"), ns)
        out = ns["_assert_fn"](output, ctx)
    except Exception as exc:                       # noqa: BLE001
        return _err(f"python-асерт упав: {exc!r}")
    if isinstance(out, dict):
        return Result(bool(out.get("pass")), float(out.get("score", 0.0)),
                      str(out.get("reason", "python-асерт повернув GradingResult")))
    if isinstance(out, bool):
        return _res(out, f"python-асерт {value!r} -> {out}")
    score = float(out)
    threshold = a.get("threshold")
    ok = score >= threshold if threshold is not None else score > 0
    return _res(ok, f"python-асерт повернув число {score}", score=score)


def chk_cost(output, value, a, ctx):
    cost = ctx.get("cost")
    if cost is None:
        return _err("провайдер не повідомив вартість (аналог: cost працює лише для моделей з cost info)")
    limit = a["threshold"]
    return _res(cost <= limit, f"${cost:.6f} {'<=' if cost <= limit else '>'} ${limit}")


def chk_latency(output, value, a, ctx):
    ms = ctx.get("latency_ms")
    if ms is None:
        return _err("провайдер не повідомив latency")
    limit = a["threshold"]
    return _res(ms <= limit, f"{ms} мс {'<=' if ms <= limit else '>'} {limit} мс")


CHECKERS = {
    "equals": chk_equals, "contains": chk_contains, "icontains": chk_icontains,
    "regex": chk_regex, "starts-with": chk_starts_with,
    "contains-any": chk_contains_any, "contains-all": chk_contains_all,
    "icontains-all": chk_icontains_all, "is-json": chk_is_json,
    "contains-json": chk_contains_json, "is-refusal": chk_is_refusal,
    "python": chk_python, "cost": chk_cost, "latency": chk_latency,
}
SUPPORTED = sorted(list(CHECKERS) + ["assert-set"])
print("підтримані типи:", ", ".join(SUPPORTED))
'''
    ),
    code(
        '''
# ── Обгортка: weight, threshold, not-, transform, assert-set ─────────────

def apply_transform(output, expr, ctx):
    """Підмножина transform: json.<ключ> витягує поле з JSON-виводу."""
    if expr.startswith("json."):
        data = extract_json(output)
        key = expr[5:]
        if isinstance(data, dict) and key in data:
            return data[key]
        raise KeyError(f"немає ключа {key!r} у виводі")
    return output


def _coerce(text):
    return text if isinstance(text, str) else json.dumps(text, ensure_ascii=False)


def run_one(output, assertion, context=None):
    """Одна перевірка. Повертає Result."""
    ctx = dict(context or {})
    atype = assertion["type"]
    negate = atype.startswith("not-")
    base = atype[4:] if negate else atype
    weight = assertion.get("weight", 1.0)

    if weight == 0:
        # задокументована поведінка Promptfoo: weight=0 -> перевірка проходить автоматично
        return Result(True, 1.0, "weight=0 → перевірка вважається успішною")

    if base == "assert-set":
        return run_assert_set(output, assertion, ctx)

    fn = CHECKERS.get(base)
    if fn is None:
        return _err(f"тип {base!r} цим рушієм не підтримується")

    text = _coerce(output)
    if assertion.get("transform"):
        try:
            text = _coerce(apply_transform(text, assertion["transform"], ctx))
        except Exception as exc:                   # noqa: BLE001
            return _err(f"transform не спрацював: {exc!r}")

    res = fn(text, assertion.get("value"), assertion, ctx)
    if negate:
        # інвертується лише справжній вердикт; помилка перевірки лишається помилкою
        if res.grader_error:
            return res
        return Result(not res.pass_, res.score, "інвертовано: " + res.reason)
    return res


def run_assert_set(output, assertion, context):
    subs = [run_one(output, a, context) for a in assertion["assert"]]
    passed = sum(1 for r in subs if r.pass_)
    frac = passed / len(subs)
    threshold = assertion.get("threshold")
    ok = frac >= threshold if threshold is not None else all(r.pass_ for r in subs)
    return Result(ok, frac, f"{passed}/{len(subs)} перевірок набору пройдено")


def run_test(output, test_case, context=None):
    """Тест-кейс у цілому: зважене середнє + поріг кейса."""
    ctx = {"vars": test_case.get("vars", {}), **(context or {})}
    rows = [(a, run_one(output, a, ctx)) for a in test_case.get("assert", [])]
    total_w = sum(a.get("weight", 1.0) for a, _ in rows)
    score = (sum(a.get("weight", 1.0) * r.score for a, r in rows) / total_w) if total_w else 1.0
    threshold = test_case.get("threshold")
    passed = all(r.pass_ for _, r in rows) if threshold is None else score >= threshold
    named = {}
    for a, r in rows:
        if a.get("metric"):
            named.setdefault(a["metric"], []).append(r.score)
    metrics = {k: sum(v) / len(v) for k, v in named.items()}
    return {"pass": passed, "score": round(score, 4), "threshold": threshold,
            "results": rows, "metrics": metrics}
'''
    ),
    code(
        '''
# ── Перевірка рушія на числовому прикладі з документації Promptfoo ────────
# Документація стверджує: equals(weight=2) падає, contains(weight=1) проходить,
# підсумковий score = 0.33; з threshold 0.5 кейс падає, з 0.2 — проходить.

DOC_CASE = {
    "vars": {},
    "assert": [
        {"type": "equals", "value": "Hello world", "weight": 2},
        {"type": "contains", "value": "world", "weight": 1},
    ],
}
OUTPUT = "Goodbye world"

plain = run_test(OUTPUT, DOC_CASE)
print("score без threshold:", plain["score"])
assert abs(plain["score"] - 0.33) < 0.005, plain["score"]

for th in (0.5, 0.2):
    res = run_test(OUTPUT, {**DOC_CASE, "threshold": th})
    print(f"threshold={th}: pass={res['pass']}, score={res['score']}")

print("weight=0:", run_test(OUTPUT, {"assert": [
    {"type": "equals", "value": "nope", "weight": 0}]})["pass"])
print("threshold=0 завжди проходить:", run_test(OUTPUT, {"threshold": 0, "assert": [
    {"type": "equals", "value": "nope"}]})["pass"])
print("not-contains:", run_one("Goodbye world", {"type": "not-contains", "value": "Hello"}).pass_)
print("assert-set 1 з 2 (threshold 0.5):",
      run_one("x", {"type": "assert-set", "threshold": 0.5, "assert": [
          {"type": "contains", "value": "y"}, {"type": "contains", "value": "x"}]}).pass_)
print("assert-set без threshold:",
      run_one("x", {"type": "assert-set", "assert": [
          {"type": "contains", "value": "y"}, {"type": "contains", "value": "x"}]}).pass_)
'''
    ),
    code(
        '''
# ── Пастка is-json vs contains-json: різниця, яку видно тільки на ```-блоці ──
fenced = 'Ось результат:\\n```json\\n{"category": "delivery"}\\n```'
pure = '{"category": "delivery"}'
for name, text in [("чистий JSON", pure), ("огорнутий у ```json", fenced)]:
    a_json = run_one(text, {"type": "is-json"})
    a_cont = run_one(text, {"type": "contains-json"})
    print(f"{name:24} is-json={a_json.pass_!s:5} contains-json={a_cont.pass_!s:5} | {a_json.reason}")

# Схема ловить те, що синтаксис JSON пропускає
SCHEMA = {
    "type": "object",
    "required": ["category", "priority", "order_id", "summary"],
    "properties": {
        "category": {"type": "string", "enum": ["delivery", "payment", "refund", "other"]},
        "priority": {"type": "string", "enum": ["low", "normal", "high"]},
        "order_id": {"type": ["string", "null"]},
        "summary": {"type": "string"},
    },
}
bad = '{"category": "delivery", "priority": "urgent", "order_id": null, "summary": "ok"}'
print("валідний JSON, але схема:", run_one(bad, {"type": "is-json", "value": SCHEMA}).reason)
'''
    ),
    # ── Прогін golden set через рушій ─────────────────────────────────────
    md(
        """
## Прогін golden set через рушій (24.1 → 24.3)

Golden set із 24.1 проганяється рушієм із 24.3. Провайдер — **детермінована заглушка**: вона
повертає вивід із контрольованими дефектами (`fence` — JSON у markdown-блоці, `priority-urgent` —
значення поза enum, `no-json` — проза, `order-null` — втрачений номер замовлення, `complies` —
виконав замість відмови) і додає вартість та латентність.

Заглушка потрібна лише тому, що тут перевіряється **механіка** евалюації. Щоб підставити справжню
модель, достатньо замінити `stub_provider` на виклик API — решта коду не змінюється.
"""
    ),
    code(
        '''
# Керовані дефекти заглушки: кожен ламає конкретну метрику.
DEFECTS = {
    "v1 (базовий)": {"c-003": "fence", "c-008": "priority-urgent", "c-010": "long-summary"},
    "v2 (кандидат)": {"c-002": "order-null", "c-003": "fence", "c-005": "no-json",
                      "c-006": "complies", "c-008": "priority-urgent", "c-010": "long-summary"},
}
SLOW_CASES = {"c-008"}
PRICE_IN, PRICE_OUT = 0.25, 2.00        # gpt-5-mini, $ за 1 млн токенів
FENCE = chr(96) * 3                     # markdown-огорожка без потрійних лапок у коді
NL = chr(10)


def build_text(expect, defect):
    # Складає вивід заглушки за дефектом; expect is None -> кейс на відмову
    if defect == "complies":
        return ("Коти — дивовижні створіння, вони муркочуть і сплять на сонці. "
                "Ось невеликий вірш: пухнастий кіт іде, мов тінь, крізь теплий дім.")
    if expect is None:
        return "Вибачте, я не можу допомогти з цим запитом: я відповідаю лише на питання про замовлення."
    payload = dict(expect)
    if defect == "fence":
        return "Ось результат:" + NL + FENCE + "json" + NL + json.dumps(payload, ensure_ascii=False) + NL + FENCE
    if defect == "no-json":
        return "Замовлення обробляється, деталі надішлемо на пошту протягом дня."
    if defect == "priority-urgent":
        payload["priority"] = "urgent"
    elif defect == "order-null":
        payload["order_id"] = None
    elif defect == "long-summary":
        payload["summary"] = "Дуже докладний опис звернення: " + "детально " * 20
    return json.dumps(payload, ensure_ascii=False)


def stub_provider(case, variant):
    # Заглушка замість LLM: детермінований вивід + вартість і латентність
    expect = case["vars"]["expect"]
    text = build_text(expect, DEFECTS[variant].get(case["id"]))
    prompt_tokens = 120 + len(case["vars"]["message"]) // 4
    completion_tokens = len(text) // 4
    cost = prompt_tokens / 1e6 * PRICE_IN + completion_tokens / 1e6 * PRICE_OUT
    latency = 420 + 3 * len(text) + (1800 if case["id"] in SLOW_CASES else 0)
    return {"output": text, "cost": round(cost, 6), "latency_ms": latency,
            "prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens}


def run_suite(cases, variants):
    # Прогін: кейси x варіанти промпту -> звіт по метриках
    report = {}
    for variant in variants:
        failing, hits, totals = [], {}, {}
        costs, latencies, score_sum = [], [], 0.0
        for case in cases:
            resp = stub_provider(case, variant)
            res = run_test(resp["output"], case,
                           {"cost": resp["cost"], "latency_ms": resp["latency_ms"]})
            for assertion, result in res["results"]:
                metric = assertion.get("metric")
                if metric:
                    totals[metric] = totals.get(metric, 0) + 1
                    hits[metric] = hits.get(metric, 0) + bool(result.pass_)
            costs.append(resp["cost"])
            latencies.append(resp["latency_ms"])
            score_sum += res["score"]
            if not res["pass"]:
                failing.append((case["id"], res["score"],
                                next(r.reason for _, r in res["results"] if not r.pass_)))
        n = len(cases)
        report[variant] = {
            "pass_rate": round(1 - len(failing) / n, 3),
            "passed": n - len(failing), "total": n,
            "avg_score": round(score_sum / n, 4),
            "metrics": {m: round(hits[m] / totals[m], 3) for m in sorted(totals)},
            "cost_usd": round(sum(costs), 6),
            "latency_avg": round(sum(latencies) / len(latencies)),
            "failing": list(failing),               # ЗНІМОК: копія списку, не посилання
            "latencies": list(latencies),
        }
    return report


REPORT = run_suite(GOLDEN_SET, list(DEFECTS))
for variant, data in REPORT.items():
    print(f"--- {variant} ---")
    print(f"кейсів пройдено: {data[\'pass_rate\']:.0%} ({data[\'passed\']}/{data[\'total\']})   "
          f"середній score: {data[\'avg_score\']}")
    print("метрики:", "  ".join(f"{m}={v}" for m, v in data["metrics"].items()))
    print(f"вартість прогону: ${data[\'cost_usd\']:.4f}, "
          f"середня латентність: {data[\'latency_avg\']} мс")
    for cid, score, why in data["failing"]:
        print(f"   \u2717 {cid} (score {score}): {why}")
'''
    ),

    # ── 24.4 ─────────────────────────────────────────────────────────────
    md(
        """
## 24.4 LLM-як-суддя: семантика вердикту

Суддя повертає `{"reason": ..., "pass": bool, "score": number}`. Ключове — як ці поля
перетворюються на вердикт: **без `threshold` прохід залежить лише від поля `pass`** (відсутнє
поле вважається `true`), **з `threshold` потрібні обидві умови** — `pass` і `score >= threshold`.

**Справжній суддя потребує ключа провайдера** (і коштує грошей). Тут суддя — локальна
детермінована заглушка: вона імітує поведінку моделі, щоб показати процедуру калібрування, а не
замінити її.
"""
    ),
    code(
        '''
import json
import math
import re


def apply_verdict(verdict, threshold=None):
    # Задокументована семантика Promptfoo: без threshold вирішує лише pass,
    # з threshold потрібні ОБИДВІ умови - pass == True і score >= threshold
    if threshold is None:
        return bool(verdict.get("pass", True))
    return bool(verdict.get("pass", True)) and float(verdict.get("score", 0.0)) >= threshold


VERDICTS = [{"pass": True, "score": 0.0}, {"pass": False, "score": 1.0}, {"score": 0.4}]
print(f"{\'вердикт\':34} " + "  ".join(f"threshold={str(t):>4}" for t in (None, 1, 0.5)))
for verdict in VERDICTS:
    row = "  ".join(f"{apply_verdict(verdict, t)!s:>14}" for t in (None, 1, 0.5))
    print(f"{json.dumps(verdict, ensure_ascii=False):34} {row}")
'''
    ),
    md(
        """
### Калібрування судді на розмічених виводах

Процедура: узяти 10–30 виводів, розмітити **вручну**, порахувати згоду судді з людиною на кількох
порогах і вибрати поріг за максимумом згоди. `kappa` — каппа Коена: згода за вирахуванням
випадкової.
"""
    ),
    code(
        '''
RUBRIC = "номер замовлення і термін доставки"
LABELED = [
    ("A-10231 прибуде за 2 дні", True, "є номер і термін"),
    ("замовлення у дорозі", False, "немає ні номера, ні терміну"),
    ("A-10555: 3 дні", True, "стисло, але обидва факти є"),
    ("ваше замовлення обробляється", False, "немає конкретики"),
    ("прибуде за 5 днів", False, "немає номера замовлення"),
    ("A-10999 у дорозі", False, "немає терміну"),
    ("A-10777: доставка завтра, тобто 1 день", True, "є номер і термін"),
    ("дякуємо за звернення", False, "порожньо по суті"),
    ("замовлення A-10231 затримується на 4 дні", True, "є обидва факти"),
    ("A-10000: 2 дні", True, "є обидва факти"),
    ("номер замовлення надішлемо листом", False, "немає самого номера"),
    ("A-10555 затримка", False, "немає терміну"),
]


def judge_score(output, rubric, verbosity_bias=0.0):
    # Детермінована заглушка судді: рубрика -> ключові слова, вивід -> факти
    words = [w.strip(".,:;!?()").lower() for w in rubric.split() if len(w) > 4]
    hits = sum(1 for w in words if w in output.lower())
    score = hits / len(words) if words else 0.0
    if re.search("[A-Z]-[0-9]{4,}", output):
        score += 0.5                                  # є номер замовлення
    if re.search("[0-9]+ (дн|годин)", output):
        score += 0.5                                  # є конкретний термін
    score += verbosity_bias * min(len(output) / 300, 1.0)
    return round(min(score, 1.0), 3)


def cohen_kappa(pairs):
    # Згода за вирахуванням випадкової, без зовнішніх залежностей
    n = len(pairs)
    tp = sum(1 for a, b in pairs if a and b)
    tn = sum(1 for a, b in pairs if not a and not b)
    fp = sum(1 for a, b in pairs if a and not b)
    fn = sum(1 for a, b in pairs if not a and b)
    po = (tp + tn) / n
    pe = ((tp + fp) * (tp + fn) + (fn + tn) * (fp + tn)) / (n * n)
    return (po - pe) / (1 - pe) if pe != 1 else 1.0


SWEEP = []          # ЗНІМОК: кортежі чисел, а не посилання на змінні циклу
for limit in (0.0, 0.5, 0.6, 0.7, 0.8, 1.0):
    pairs = [(human, judge_score(out, RUBRIC) >= limit) for out, human, _ in LABELED]
    tp = sum(1 for h, j in pairs if h and j)
    fp = sum(1 for h, j in pairs if not h and j)
    fn = sum(1 for h, j in pairs if h and not j)
    tn = sum(1 for h, j in pairs if not h and not j)
    SWEEP.append({"limit": limit, "accuracy": (tp + tn) / len(pairs),
                  "tp": tp, "fp": fp, "fn": fn, "tn": tn, "kappa": cohen_kappa(pairs)})

print(f"{\'поріг\':>6} {\'accuracy\':>9} {\'TP\':>3} {\'FP\':>3} {\'FN\':>3} {\'TN\':>3} {\'kappa\':>7}")
for row in SWEEP:
    print(f"{row[\'limit\']:>6} {row[\'accuracy\']:>9.3f} {row[\'tp\']:>3} {row[\'fp\']:>3} "
          f"{row[\'fn\']:>3} {row[\'tn\']:>3} {row[\'kappa\']:>7.3f}")

BEST_ROW = max(SWEEP, key=lambda r: r["accuracy"])
print(f"найкращий поріг: {BEST_ROW[\'limit\']} "
      f"(accuracy {BEST_ROW[\'accuracy\']:.3f}, kappa {BEST_ROW[\'kappa\']:.3f})")

DISAGREEMENTS = [(out, human, note) for out, human, note in LABELED
                 if (judge_score(out, RUBRIC) >= 0.7) != human]
print("розбіжності при порозі 0.7:")
for out, human, note in DISAGREEMENTS:
    print(f"   суддя={not human}, людина={human}: {out!r} — {note}")
'''
    ),

    # ── 24.5 ─────────────────────────────────────────────────────────────
    md(
        """
## 24.5 `select-best` і парні порівняння

`select-best` бере **усі** виводи одного тест-кейса (усі промпти й провайдери рядка) і повертає
`pass: true` лише для переможця. Звідси дві властивості: перевірка потребує щонайменше двох
промптів/провайдерів, і вона не є метрикою якості — вона лише ранжує.

Парні порівняння руками — та сама ідея плюс дві арифметики: кількість порівнянь `n x (n-1) / 2`
і вплив **порядку**. Нижче — 4 варіанти відповіді на один кейс: 6 пар, 12 прогонів (кожна пара в
обох порядках) і підрахунок розбіжностей.
"""
    ),
    code(
        '''
import itertools

CRITERION = "відповідь містить номер замовлення і конкретний термін доставки"
POSITION = {
    "v1 (базовий)": "Ваше замовлення A-10231 у дорозі, прибуде за 2 дні.",
    "v2 (стислий)": "A-10231: у дорозі, 2 дні.",
    "v3 (з вибаченням)": "Вибачте за затримку! Замовлення A-10231 прибуде за 2 дні.",
    "v4 (без деталей)": "Замовлення обробляється.",
}


def stub_compare(a, b, criterion, position_bias=True):
    # Заглушка парного порівняння: перемагає вищий score, за рівності - перший
    score_a, score_b = judge_score(a, criterion), judge_score(b, criterion)
    if score_a == score_b and position_bias:
        return 0                     # ніша розв'язується порядком
    return 0 if score_a >= score_b else 1


PAIRS = list(itertools.combinations(list(POSITION), 2))
WINS = {variant: 0 for variant in POSITION}
FLIPS = []
for left, right in PAIRS:
    forward = stub_compare(POSITION[left], POSITION[right], CRITERION)
    reverse = stub_compare(POSITION[right], POSITION[left], CRITERION)
    winner_forward = left if forward == 0 else right
    winner_reverse = right if reverse == 0 else left
    WINS[winner_forward] += 1
    if winner_forward != winner_reverse:
        FLIPS.append((left, right, winner_forward, winner_reverse))

COMPARISONS = 2 * len(PAIRS)
print(f"варіантів: {len(POSITION)}, пар: {len(PAIRS)}, прогонів (обидва порядки): {COMPARISONS}")
print(f"розбіжностей через порядок: {len(FLIPS)} ({len(FLIPS) / COMPARISONS:.0%})")
for left, right, fwd, rev in FLIPS:
    print(f"   {left} vs {right}: прямий порядок -> {fwd}, зворотний -> {rev}")
print("win-rate:")
for variant, wins in sorted(WINS.items(), key=lambda item: -item[1]):
    print(f"   {variant:22} {wins}/{len(PAIRS)} перемог, win-rate {wins / len(PAIRS):.2f}")

# max-score: детермінований вибір за агрегатом score із прогону golden set
BEST_VARIANT = max(REPORT, key=lambda variant: REPORT[variant]["avg_score"])
print(f"max-score (method=average, threshold=0.7) обирає: {BEST_VARIANT}, "
      f"score {REPORT[BEST_VARIANT][\'avg_score\']:.4f}")

# Упередження на довжину: той самий зміст + "вода"
PAD = "Дякуємо за звернення до нашої служби підтримки. " * 10
print("verbosity bias (заглушка судді з вадою на довжину, bias=0.6):")
for variant, short in POSITION.items():
    loud = judge_score(short, CRITERION, 0.6)
    loud_padded = judge_score(short + " " + PAD, CRITERION, 0.6)
    fair = judge_score(short, CRITERION)
    fair_padded = judge_score(short + " " + PAD, CRITERION)
    print(f"   {variant:22} {loud:.3f} -> {loud_padded:.3f}   (без вади: {fair:.3f} -> {fair_padded:.3f})")
'''
    ),

    # ── 24.6 ─────────────────────────────────────────────────────────────
    md(
        """
## 24.6 Red teaming: конфігурація і локальна модель ризику

**Справжній запуск потребує `npx promptfoo` і ключа провайдера** — він генерує сотні змагальних
входів і коштує грошей. Тут ми робимо дві речі без ключів:

1. читаємо **справжню структуру конфігурації** з `research/10/pf_redteam_config.txt` — перелік
   плагінів, стратегії та значення за замовчуванням;
2. рахуємо локальну **модель ризику** на власних сценаріях: вага за `severity`, частка вагових
   балів успішних атак до фіксів і після.

Категорії сценаріїв узяті з переліку загроз застосункового й модельного шару з документації
Promptfoo.
"""
    ),
    code(
        '''
RT = (ROOT / "research/10/pf_redteam_config.txt").read_text(encoding="utf-8")

# Розбір таблиць: порожні комірки відкидаємо, значення за замовчуванням - остання комірка
RT_FIELDS = {}
for line in RT.splitlines():
    cells = [cell.strip() for cell in line.split("|") if cell.strip()]
    if len(cells) >= 3:
        RT_FIELDS.setdefault(cells[0], cells[-1])

# Плагіни: рядки таблиці "Назва | Опис | Plugin ID |"
PLUGIN_IDS = []
for line in RT.splitlines():
    cells = [cell.strip() for cell in line.split("|")]
    if len(cells) == 4 and cells[-1] == "":
        candidate = cells[2].strip("`")
        if re.fullmatch("[a-z][a-z0-9:_-]{2,}", candidate) and candidate not in PLUGIN_IDS:
            PLUGIN_IDS.append(candidate)
FRAMEWORK_IDS = [line[2:] for line in RT.splitlines()
                 if line.startswith("- ") and re.fullmatch("[a-z][a-z0-9:_-]{2,}", line[2:])]

print(f"плагінів у переліку конфігурації: {len(PLUGIN_IDS)}")
print("приклади:", ", ".join(PLUGIN_IDS[:6]))
print("типові значення: numTests =", RT_FIELDS.get("numTests"),
      "| maxConcurrency =", RT_FIELDS.get("maxConcurrency"),
      "| delay =", RT_FIELDS.get("delay"))
print("типові стратегії:", RT_FIELDS.get("strategies"))
print("типова мова генерації:", RT_FIELDS.get("language"))
print("фреймворки:", ", ".join(FRAMEWORK_IDS))
assert "severity: 'critical'" in RT, "у джерелі немає рівнів severity"

SEVERITY_WEIGHT = {"low": 1, "medium": 2, "high": 3, "critical": 4}
ATTACKS = [
    {"id": "rt-01", "layer": "application", "severity": "critical",
     "threat": "непряма ін'єкція через документ у RAG"},
    {"id": "rt-02", "layer": "application", "severity": "high",
     "threat": "PII з контексту (чужий номер телефону)"},
    {"id": "rt-03", "layer": "application", "severity": "critical",
     "threat": "виклик інструмента поза роллю (BOLA)"},
    {"id": "rt-04", "layer": "application", "severity": "high",
     "threat": "витік даних через markdown-картинку"},
    {"id": "rt-05", "layer": "application", "severity": "medium",
     "threat": "зміна теми (hijacking)"},
    {"id": "rt-06", "layer": "application", "severity": "high",
     "threat": "відмова від службових інструкцій (jailbreak)"},
    {"id": "rt-07", "layer": "model", "severity": "medium",
     "threat": "витік системного промпту"},
    {"id": "rt-08", "layer": "model", "severity": "high",
     "threat": "шкідливий контент у відповіді"},
]
BASE_COMPROMISED = {"rt-01", "rt-03", "rt-04", "rt-06", "rt-08"}
PATCHED_COMPROMISED = {"rt-04", "rt-08"}


def redteam_report(compromised):
    # Ризик = сума ваг успішних атак / сума ваг усіх атак
    total = sum(SEVERITY_WEIGHT[attack["severity"]] for attack in ATTACKS)
    hit = sum(SEVERITY_WEIGHT[attack["severity"]] for attack in ATTACKS
              if attack["id"] in compromised)
    return hit / total, total, hit


REDTEAM_RUNS = []        # ЗНІМОК результатів: словники з числами й копією списку
for stage, compromised in (("до фіксів", BASE_COMPROMISED), ("після фіксів", PATCHED_COMPROMISED)):
    risk, total, hit = redteam_report(compromised)
    REDTEAM_RUNS.append({"stage": stage, "risk": round(risk, 4), "hit": hit,
                         "total": total, "compromised": sorted(compromised)})
    print(f"{stage}: ризик {risk:.1%} ({hit}/{total} вагових балів), "
          f"успішних атак {len(compromised)} з {len(ATTACKS)}")
    for attack in ATTACKS:
        mark = "АТАКА ВДАЛАСЯ" if attack["id"] in compromised else "відбито     "
        print(f"   {mark} {attack[\'id\']} [{attack[\'severity\']:>8}] "
              f"{attack[\'layer\']:<11} {attack[\'threat\']}")

TESTS = len(PLUGIN_IDS) * int(RT_FIELDS.get("numTests", 5))
EXAMPLE_PLUGINS = 8                     # приклад із розділу 24.6
print(f"бюджет генерації: {len(PLUGIN_IDS)} плагінів x {RT_FIELDS.get(\'numTests\')} тестів = {TESTS} тестів")
print(f"той самий розрахунок для прикладу з розділу ({EXAMPLE_PLUGINS} плагінів): "
      f"{EXAMPLE_PLUGINS * int(RT_FIELDS.get(\'numTests\'))} тестів, "
      f"кожен = 1 виклик цільової моделі + 1 виклик судді")
'''
    ),
    code(
        '''
# Реальний Promptfoo: виконується лише якщо є npx, і ніколи не валить ноутбук.
def run_promptfoo_redteam(timeout=60):
    if not NPX:
        return "пропущено: npx не знайдено (Promptfoo - Node.js-інструмент)"
    command = [NPX, "--yes", "promptfoo@latest", "redteam", "plugins"]
    environment = {**os.environ, "PROMPTFOO_DISABLE_TELEMETRY": "1",
                   "npm_config_cache": os.path.join(os.environ.get("TMPDIR", "/tmp"), "npm-cache")}
    try:
        proc = subprocess.run(command, capture_output=True, text=True,
                              timeout=timeout, env=environment)
    except (subprocess.TimeoutExpired, OSError) as exc:
        return f"пропущено: {type(exc).__name__} (немає мережі або кешу)"
    lines = ((proc.stdout or "") + (proc.stderr or "")).strip().splitlines()
    if proc.returncode != 0:
        first = next((line for line in lines if "error" in line.lower()),
                     lines[0] if lines else "без виводу")
        return f"пропущено: npx завершився з кодом {proc.returncode} ({first[:100]})"
    return "\\n".join(lines[:12]) if lines else "(порожній вивід)"


print("promptfoo redteam plugins ->")
print(run_promptfoo_redteam())
'''
    ),

    # ── 24.7 ─────────────────────────────────────────────────────────────
    md(
        """
## 24.7 Евалюація в CI: гейт і код виходу

CI-гейт перетворює звіт евалюації на код виходу: `0` — пропустити, `1` — заблокувати злиття.
Важлива деталь: **відсутня метрика валить гейт**, а не проходить за замовчуванням — інакше
перейменування метрики тихо вимкне перевірку.
"""
    ),
    code(
        '''
GATE = {"schema": 0.7, "exact": 0.6, "refusal": 1.0}


def ci_gate(report_entry, thresholds):
    # Повертає (дозволено, exit_code, рядки-пояснення)
    lines, allowed = [], True
    for metric, limit in thresholds.items():
        rate = report_entry["metrics"].get(metric)
        if rate is None:
            lines.append(f"   {metric:12} немає в звіті — поріг {limit} не перевірено (провал)")
            allowed = False
            continue
        good = rate >= limit
        allowed = allowed and good
        lines.append(f"   {metric:12} {rate:.3f} {'>=' if good else '< '} {limit}   "
                     f"{'ok' if good else 'ПРОВАЛ'}")
    return allowed, (0 if allowed else 1), lines


EXIT_CODES = {}
for variant, report_entry in REPORT.items():
    allowed, code, details = ci_gate(report_entry, GATE)
    EXIT_CODES[variant] = code
    print(f"{variant}: exit code {code} ({'пропустити' if allowed else 'ЗАБЛОКУВАТИ'})")
    for line in details:
        print(line)

# Що буде, якщо метрику перейменувати: гейт мусить це помітити
RENAMED = {key: value for key, value in REPORT["v1 (базовий)"]["metrics"].items() if key != "refusal"}
RENAME_ALLOWED, RENAME_CODE, _ = ci_gate({"metrics": RENAMED}, GATE)
print(f"після перейменування метрики: exit code {RENAME_CODE} "
      f"({'пропустити' if RENAME_ALLOWED else 'ЗАБЛОКУВАТИ'})")
'''
    ),

    # ── 24.8 ─────────────────────────────────────────────────────────────
    md(
        """
## 24.8 Скільки це коштує

**Важливо:** ціни беруться з файлів `research/econ/*` (реальні прайси на дату збору), а ось
**кількість токенів на виклик — це модельне припущення**, а не вимір із документації:
900 вхідних і 120 вихідних для цільового виклику, 1400 і 200 для судді. Підставте свої виміряні
значення — порядок величин збережеться, абсолютні числа зміняться.
"""
    ),
    code(
        '''
PRICING_MD = (ROOT / "research/econ/openai_pricing.md").read_text(encoding="utf-8")
DEEPSEEK_TXT = (ROOT / "research/econ/deepseek_pricing.txt").read_text(encoding="utf-8")
LF_PRICING = (ROOT / "research/10/lf_pricing.txt").read_text(encoding="utf-8")

PRICE_ROWS = {}
for line in PRICING_MD.splitlines():
    cells = [cell.strip() for cell in line.split("|") if cell.strip()]
    if len(cells) >= 5 and cells[0] not in PRICE_ROWS and cells[1].startswith("$"):
        PRICE_ROWS[cells[0]] = cells[1:5]        # перша таблиця у файлі = Standard

TOKEN_MODELS = ("gpt-5-nano", "gpt-5-mini", "gpt-5.6-luna", "gpt-5.6-sol")


def price_of(model):
    row = PRICE_ROWS.get(model)
    if not row:
        return None
    numbers = [float(cell.lstrip("$")) if cell.startswith("$") else None for cell in row]
    return {"in": numbers[0], "cached_in": numbers[1] or numbers[0], "out": numbers[3]}


PRICES = {model: price_of(model) for model in TOKEN_MODELS}

# DeepSeek: перша колонка таблиці - модель deepseek-flash. Перевіряємо рядки джерела,
# з яких узято числа (а не лише окремі $суми, які могли б належати іншій моделі).
for row in ("(CACHE HIT) | OFF-PEAK | $0.003 | $0.022 |",
            "(CACHE MISS) | OFF-PEAK | $0.15 | $0.66 |",
            "1M OUTPUT TOKENS | OFF-PEAK | $0.6 | $1.98 |"):
    assert row in DEEPSEEK_TXT, f"немає рядка {row!r} у research/econ/deepseek_pricing.txt"
PRICES["deepseek-flash (off-peak)"] = {"in": 0.15, "cached_in": 0.003, "out": 0.6}
PRICES["deepseek-flash (peak)"] = {"in": 0.3, "cached_in": 0.006, "out": 1.2}

print(f"{'модель':28} {'вхід':>7} {'кеш':>7} {'вихід':>7}")
for model, price in PRICES.items():
    print(f"{model:28} ${price[\'in\']:>6} ${price[\'cached_in\']:>6} ${price[\'out\']:>6}")


def cost_usd(model, prompt_tokens, completion_tokens, cached_tokens=0):
    # Ціна одного виклику в доларах; PRICES - $ за 1 млн токенів
    price = PRICES[model]
    fresh = max(prompt_tokens - cached_tokens, 0)
    return (fresh * price["in"] + cached_tokens * price["cached_in"]
            + completion_tokens * price["out"]) / 1e6


# Токени - МОДЕЛЬНЕ ПРИПУЩЕННЯ (див. markdown вище)
TARGET_IN, TARGET_OUT = 900, 120
JUDGE_IN, JUDGE_OUT = 1400, 200


def scenario(cases, prompts, providers, judge=None, graded=0,
             target="gpt-5-mini", repeats=1):
    cells = cases * prompts * providers * repeats
    target_cost = cells * cost_usd(target, TARGET_IN, TARGET_OUT)
    judge_cost = cells * graded * cost_usd(judge, JUDGE_IN, JUDGE_OUT) if judge else 0.0
    return cells, target_cost, judge_cost, target_cost + judge_cost


SCENARIOS = [
    ("smoke на PR (10 кейсів)", (10, 1, 1, "gpt-5-mini", 1)),
    ("golden set, дешевий суддя", (60, 2, 1, "gpt-5-mini", 2)),
    ("golden set, суддя-nano", (60, 2, 1, "gpt-5-nano", 2)),
    ("golden set, дорогий суддя", (60, 2, 1, "gpt-5.6-sol", 2)),
    ("нічний прогін (2 провайдери)", (300, 3, 2, "gpt-5-mini", 2)),
]
COST_TABLE = []
print(f"{'сценарій':30} {'комірок':>8} {'цільова':>9} {'суддя':>9} {'разом':>9}")
for label, args in SCENARIOS:
    cells, target_cost, judge_cost, total = scenario(*args)
    COST_TABLE.append({"scenario": label, "cells": cells, "target": round(target_cost, 4),
                       "judge": round(judge_cost, 4), "total": round(total, 4)})
    print(f"{label:30} {cells:>8} ${target_cost:>8.4f} ${judge_cost:>8.4f} ${total:>8.4f}")

REDTEAM_TESTS = 40
generation_cost = 32 * cost_usd("gpt-5-mini", 900, 300)
run_cost = REDTEAM_TESTS * (cost_usd("gpt-5-mini", TARGET_IN, TARGET_OUT)
                            + cost_usd("gpt-5-mini", JUDGE_IN, JUDGE_OUT))
print(f"red team: генерація 32 запитів ${generation_cost:.4f} + "
      f"прогін {REDTEAM_TESTS} тестів із суддею ${run_cost:.4f} = ${generation_cost + run_cost:.4f}")

no_cache = 60 * cost_usd("gpt-5-mini", JUDGE_IN, JUDGE_OUT)
with_cache = 60 * cost_usd("gpt-5-mini", JUDGE_IN, JUDGE_OUT, cached_tokens=1200)
print(f"кеш промпту судді (та сама рубрика 60 разів): ${no_cache:.4f} -> ${with_cache:.4f} "
      f"(-{1 - with_cache / no_cache:.0%})")

for token in ("50k units / month included", "$29/ month", "$199/ month", "$8/100k units"):
    assert token in LF_PRICING, f"немає {token} у research/10/lf_pricing.txt"
print("плани Langfuse (з research/10/lf_pricing.txt): Hobby - $0, 50k units/міс; "
      "Core - $29/міс, 100k units + $8/100k; Pro - $199/міс")
'''
    ),

    # ── самоперевірка ────────────────────────────────────────────────────
    md(
        """
## Самоперевірка

Клітинка нижче перевіряє твердження з розділу 24 на реальних обчисленнях цього ноутбука.
"""
    ),
    code(
        '''
# ── 1. Golden set: склад і метрики ───────────────────────────────────────
assert len(GOLDEN_SET) == 10, len(GOLDEN_SET)
assert sum(len(case["assert"]) for case in GOLDEN_SET) == 43
assert sorted({a["metric"] for case in GOLDEN_SET for a in case["assert"]}) == [
    "brevity", "budget", "exact", "order-id", "refusal", "schema", "summary-len"]
print("1. golden set: 10 кейсів, 43 перевірки, 7 метрик")

# ── 2. Числовий еталон із документації Promptfoo ─────────────────────────
assert round(plain["score"], 2) == 0.33, plain["score"]
assert run_test(OUTPUT, {**DOC_CASE, "threshold": 0.5})["pass"] is False
assert run_test(OUTPUT, {**DOC_CASE, "threshold": 0.2})["pass"] is True
print("2. equals(weight=2) + contains(weight=1) -> score 0.33; поріг 0.5 валить, 0.2 пропускає")

# ── 3. weight=0 і threshold=0 ────────────────────────────────────────────
assert run_one(OUTPUT, {"type": "equals", "value": "nope", "weight": 0}).pass_ is True
assert run_test(OUTPUT, {"threshold": 0,
                         "assert": [{"type": "equals", "value": "nope"}]})["pass"] is True
print("3. weight=0 -> автопрохід; threshold=0 -> кейс проходить завжди")

# ── 4. not- інвертує вердикт, is-json строгий, contains-json м'який ──────
assert run_one(OUTPUT, {"type": "not-contains", "value": "Hello"}).pass_ is True
assert run_one(fenced, {"type": "is-json"}).pass_ is False
assert run_one(fenced, {"type": "contains-json"}).pass_ is True
print("4. not-contains інвертує; is-json строгий до огорожки, contains-json - ні")

# ── 5. Детермінізм звіту: два прогони дають однаковий результат ──────────
AGAIN = run_suite(GOLDEN_SET, list(DEFECTS))
assert json.dumps(AGAIN, sort_keys=True, ensure_ascii=False) == \
       json.dumps(REPORT, sort_keys=True, ensure_ascii=False)
print("5. звіт детермінований: два прогони збігаються побітово")

# ── 6. Регресія між варіантами промпту ───────────────────────────────────
assert REPORT["v1 (базовий)"]["pass_rate"] == 0.7
assert REPORT["v2 (кандидат)"]["pass_rate"] == 0.4
assert REPORT["v1 (базовий)"]["metrics"]["exact"] == 0.667
assert REPORT["v2 (кандидат)"]["metrics"]["refusal"] == 0.0
print("6. v1 пройшов 70% кейсів, v2 - 40%; у v2 refusal=0.0 (виконав заборонений запит)")

# ── 7. assert-set із порогом проходить там, де latency перевищено ────────
slow = GOLDEN_SET[7]
slow_resp = stub_provider(slow, "v1 (базовий)")
slow_res = run_test(slow_resp["output"], slow,
                    {"cost": slow_resp["cost"], "latency_ms": slow_resp["latency_ms"]})
budget_result = slow_res["results"][-1][1]
assert slow_resp["latency_ms"] > 2000
assert budget_result.pass_ is True and budget_result.score == 0.5
print(f"7. c-008: latency {slow_resp[\'latency_ms\']} мс > 2000, але assert-set пройшов (score 0.5)")

# ── 8. Семантика судді: pass/score/threshold ─────────────────────────────
assert apply_verdict({"pass": True, "score": 0.0}) is True
assert apply_verdict({"pass": True, "score": 0.0}, 1) is False
assert apply_verdict({"score": 0.4}) is True
print("8. {pass: true, score: 0} проходить без порогу і падає з threshold=1")

# ── 9. Калібрування: поріг 0 непридатний, плато 0.6+ ─────────────────────
assert abs(SWEEP[0]["accuracy"] - 0.417) < 0.005
assert SWEEP[0]["kappa"] == 0.0
assert BEST_ROW["accuracy"] >= 0.9 and BEST_ROW["kappa"] > 0.8
assert BEST_ROW["limit"] == 0.6
print(f"9. калібрування: найкращий поріг {BEST_ROW[\'limit\']} "
      f"(accuracy {BEST_ROW[\'accuracy\']:.3f}, kappa {BEST_ROW[\'kappa\']:.3f})")

# ── 10. Парні порівняння: кількість і позиційний зсув ────────────────────
assert len(PAIRS) == 6 and COMPARISONS == 12
assert len(FLIPS) == 3
assert WINS["v1 (базовий)"] == 3 and WINS["v4 (без деталей)"] == 0
print("10. парні порівняння: 6 пар, 12 прогонів, 3 розбіжності через порядок")

# ── 11. Red team: ризик падає після фіксів ───────────────────────────────
assert REDTEAM_RUNS[0]["hit"] == 17 and REDTEAM_RUNS[0]["total"] == 24
assert REDTEAM_RUNS[1]["risk"] < REDTEAM_RUNS[0]["risk"]
assert REDTEAM_RUNS[1]["compromised"] == ["rt-04", "rt-08"]
print("11. red team: ризик 70.8% -> 25.0%, лишились rt-04 і rt-08")

# ── 12. CI-гейт: код виходу і відсутня метрика ───────────────────────────
assert EXIT_CODES["v1 (базовий)"] == 0
assert EXIT_CODES["v2 (кандидат)"] == 1
assert RENAME_CODE == 1 and RENAME_ALLOWED is False
print("12. CI-гейт: v1 -> 0, v2 -> 1; перейменована метрика також блокує злиття")

# ── 13. Ціни: реальні джерела, кеш дешевший за свіжий вхід ───────────────
assert PRICES["gpt-5-mini"]["in"] == 0.25 and PRICES["gpt-5-mini"]["out"] == 2.00
assert PRICES["gpt-5-nano"]["in"] == 0.05
assert cost_usd("gpt-5-mini", 1_000_000, 0) == 0.25
assert cost_usd("gpt-5-mini", 1_000_000, 0, cached_tokens=1_000_000) == 0.025
cheap = next(row for row in COST_TABLE if row["scenario"] == "golden set, суддя-nano")
dear = next(row for row in COST_TABLE if row["scenario"] == "golden set, дорогий суддя")
assert cheap["total"] < dear["total"] / 10
print(f"13. ціни з research/econ: nano ${cheap[\'total\']} проти sol ${dear[\'total\']} за той самий прогін")

# ── 14. Конфігурація red team: джерело прочитано, мова за замовчуванням ──
assert len(PLUGIN_IDS) >= 20
assert RT_FIELDS["language"] == "English"
assert RT_FIELDS["numTests"] == "5"
assert "owasp:llm" in FRAMEWORK_IDS
print(f"14. red team-конфіг: {len(PLUGIN_IDS)} плагінів, типово {RT_FIELDS[\'language\']}, numTests=5")

print()
print("Усі перевірки пройдено.")
'''
    ),

    # ── підсумок ─────────────────────────────────────────────────────────
    md(
        """
## Підсумок

1. **Піраміда евалюації:** unit-перевірки безкоштовні й миттєві, golden set коштує гроші за кожен
   прогін, онлайн-оцінки приходять із запізненням. Ставте перевірки знизу вгору.
2. **Golden set — це дані**, а не скрипт: `id`, `vars`, очікування й список перевірок. Поле `metric`
   перетворює 43 перевірки на 7 метрик, за якими порівнюються версії.
3. **Правила підрахунку:** score кейса — зважене середнє; `weight: 0` → автопрохід; `threshold: 0` →
   кейс проходить завжди; `assert-set` без порогу вимагає всіх перевірок.
4. **`is-json` строгий, `contains-json` м'який.** Модель, яка обгорнула JSON у markdown-блок,
   проходить другу перевірку й падає на першій.
5. **Суддя вирішує за полем `pass`**, якщо поріг не задано. Саме тому рубрика без `threshold`
   «завжди проходить»; калібруйте поріг на розмічених виводах і дивіться на `kappa`, а не лише на
   accuracy.
6. **Порівняння вразливі до порядку.** Три з дванадцяти прогонів змінили переможця від перестановки —
   перемішуйте порядок і рахуйте частку розбіжностей як метрику надійності.
7. **Red teaming дає число, а не список.** Ризик = частка вагових балів успішних атак; після фіксів
   обов'язковий повторний прогін того самого набору.
8. **CI-гейт — це код виходу.** Відсутня метрика валить гейт, інакше перейменування тихо вимкне
   перевірку.
9. **Суддя дорожчий за ціль.** Заміна судді з `sol` на `nano` зменшує рахунок більш ніж у 10 разів, а
   кеш промпту судді знижує його ще на третину.

**Куди далі:**

- Розділ 23 — Langfuse: трейси, оцінки онлайн, версії датасетів.
- Розділ 6 — як обрати цільову модель під свою задачу.
- Розділ 11 — prompt injection і моделі загроз.
- Розділ 25 — продакшн-експлуатація: ліміти, бюджети, деградація.
"""
    ),
    md(
        """
## Джерела

- [Promptfoo — Configuration guide](https://promptfoo.dev/docs/configuration/guide/)
- [Promptfoo — Assertions & metrics](https://promptfoo.dev/docs/configuration/expected-outputs/)
- [Promptfoo — Python assertions](https://promptfoo.dev/docs/configuration/expected-outputs/python/)
- [Promptfoo — Model-graded metrics](https://promptfoo.dev/docs/configuration/expected-outputs/model-graded/)
- [Promptfoo — Select best](https://promptfoo.dev/docs/configuration/expected-outputs/model-graded/select-best/)
- [Promptfoo — LLM red teaming guide](https://promptfoo.dev/docs/red-team/)
- [Promptfoo — Red team configuration](https://promptfoo.dev/docs/red-team/configuration/)
- [Promptfoo — GitHub Action](https://promptfoo.dev/docs/integrations/github-action/)
- [Langfuse — Datasets](https://langfuse.com/docs/evaluation/dataset-runs/datasets)
- [Langfuse — Scores via API/SDK](https://langfuse.com/docs/evaluation/evaluation-methods/scores-via-sdk)
- [Langfuse — Pricing](https://langfuse.com/pricing)
- [OpenAI — Pricing](https://developers.openai.com/api/docs/pricing)
- [DeepSeek — Models & Pricing](https://api-docs.deepseek.com/quick_start/pricing)

Локальні копії джерел: `research/10/pf_*.txt`, `research/10/lf_*.txt`,
`research/econ/openai_pricing.md`, `research/econ/deepseek_pricing.txt`.

Розділ довідника: [`sections/24-eval.md`](../sections/24-eval.md).
"""
    ),
]
