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


def run_promptfoo(yaml_text: str, timeout: int = 120) -> str:
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
        tail = (proc.stdout or "").strip().splitlines()[-25:]
        err = (proc.stderr or "").strip().splitlines()[-6:]
        return "\\n".join(tail + (["[stderr]"] + err if err else [])) or "(порожній вивід)"


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
                               "(текст навколо або ```-блок)")
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
        return _res(out, "python-асерт повернув bool")
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
]
