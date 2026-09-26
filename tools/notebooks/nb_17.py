"""Ноутбук 17 — «Оцінювання RAG: метрики RAGAS».

Розділ довідника: sections/17-rag-eval.md

Ноутбук виконується БЕЗ ключів і БЕЗ мережі:
- корпус тестового набору — дослівні уривки джерел із `research/06b/`;
- усі метрики реалізовано на стандартній бібліотеці Python;
- кроки, які в RAGAS робить LLM (видобуток тверджень, перевірка тверджень, генерація
  зворотних питань, ембединги), замінено детермінованими процедурами — і це всюди
  позначено, щоб числа не сплутали з числами самої RAGAS;
- клітинки, які звертаються до справжньої `ragas`, захищені `try/except ImportError`.
"""

from nbkit import SETUP_CELL, VERSION_CELL, code, md

FILENAME = "17-rag-eval.ipynb"
TITLE = "17. Оцінювання RAG"

CELLS = [
    # ── заголовок ────────────────────────────────────────────────────────
    md(
        """
# 17. Оцінювання RAG: метрики RAGAS

**Розділ довідника:** [`sections/17-rag-eval.md`](../sections/17-rag-eval.md)

**Потрібно: нічого обов'язкового (опційно ragas, ANTHROPIC_API_KEY).**

Усе, що нижче, працює на стандартній бібліотеці Python: без ключів, без мережі, без GPU.
Клітинки, які імпортують справжню `ragas`, обгорнуті в `try/except ImportError` — якщо
бібліотеки немає, вони друкують пояснення й пропускаються, а решта ноутбука виконується далі.

**Що ви зробите:**

1. Зберете тестовий набір із 10 **дослівних уривків** документації RAGAS і перевірите, що цитати
   справжні (входження в файли `research/06b/`).
2. **Реалізуєте метрики власними руками** на stdlib: `faithfulness`, `context precision`
   (rank-aware і ID-based), `context recall`, `answer relevancy` — за формулами з документації.
3. Побачите, як метрики розділяють три конвеєри: добрий, зі зламаною генерацією і зі зламаним
   пошуком — на одному й тому самому наборі.
4. Переконаєтеся, що `context precision` залежить від **порядку** чанків, а ID-based версія — ні.
5. Порахуєте **кількість викликів судді** й **вартість** оцінювання на реальних цінах Claude.
6. Побачите, **чому LLM-суддя недетермінований** і скільки зразків потрібно, щоб побачити різницю
   в 5 процентних пунктів.
7. Проженете самоперевірку з `assert`-ами, які фіксують числа цього ноутбука.

**Важливе застереження.** Метрики тут — **власна реалізація формул**, а не RAGAS. Кроки, які в
RAGAS виконує мовна модель, замінено детермінованими процедурами, тому числа **не порівнянні** з
числами RAGAS. Мета — побачити арифметику формул, виміряти ціну й розкид, а не відтворити бібліотеку.
"""
    ),
    md("## Налаштування"),
    code(SETUP_CELL),
    code(VERSION_CELL),
    code(
        r'''
# Що з необов'язкових залежностей доступно в цьому середовищі.
import importlib
import os

for _pkg in ("ragas", "datasets", "langchain", "langchain_openai", "openai"):
    try:
        _mod = importlib.import_module(_pkg)
        print(f"{_pkg:18} {getattr(_mod, '__version__', '?')}")
    except ImportError:
        print(f"{_pkg:18} НЕ ВСТАНОВЛЕНО (для цього ноутбука не обов'язково)")

print()
print("ANTHROPIC_API_KEY:", "є" if os.environ.get("ANTHROPIC_API_KEY") else "немає (не потрібен)")
print("Клітинки зі справжньою ragas перевіряють наявність пакета самі.")
'''
    ),

    # ── 17.1 ─────────────────────────────────────────────────────────────
    md(
        """
## 17.1 Що саме вимірюємо в RAG: корпус і тестовий набір

RAG має дві поверхні відмов — **пошук** (потрібного чанка немає або він нижче за шум) і
**генерацію** (чанки правильні, а модель додала те, чого в них не було). Одна метрика ці випадки
не розрізняє, тому нижче ми будуємо **набір** метрик і перевіряємо його на трьох конвеєрах.

Корпус — це 10 уривків, **дослівно** скопійованих із документації RAGAS, яку збережено в
`research/06b/`. Кожен уривок має ID (`D01`…`D10`) і назву файлу-джерела.
"""
    ),
    code(
        r'''
from collections import Counter

# Корпус: (ID, файл-джерело в research/06b, дослівний текст).
CORPUS = [
    ("D01", "ragas_metric_faithfulness.txt",
     "The Faithfulness metric measures how factually consistent a response is with the retrieved context. "
     "It ranges from 0 to 1, with higher scores indicating better consistency."),
    ("D02", "ragas_metric_faithfulness.txt",
     "A response is considered faithful if all its claims can be supported by the retrieved context."),
    ("D03", "ragas_metric_context_precision.txt",
     "Context Precision is a metric that evaluates the retriever's ability to rank relevant chunks higher "
     "than irrelevant ones for a given query in the retrieved context."),
    ("D04", "ragas_metric_context_recall.txt",
     "Context Recall measures how many of the relevant documents (or pieces of information) were "
     "successfully retrieved. It focuses on not missing important results."),
    ("D05", "ragas_metric_answer_relevance.txt",
     "The Answer Relevancy metric measures how relevant a response is to the user input. "
     "It ranges from 0 to 1, with higher scores indicating better alignment with the user input."),
    ("D06", "ragas_metric_context_recall.txt",
     "Since it is about not missing anything, calculating context recall always requires a reference "
     "to compare against."),
    ("D07", "ragas_metrics_noise_sensitivity.txt",
     "NoiseSensitivity measures how often a system makes errors by providing incorrect responses when "
     "utilizing either relevant or irrelevant retrieved documents."),
    ("D08", "ragas_cost_customization.txt",
     "When using LLMs for evaluation and test set generation, cost will be an important factor."),
    ("D09", "ragas_metrics_overview.txt",
     "These metrics can be somewhat non-deterministic as the LLM might not always return the same "
     "result for the same input."),
    ("D10", "ragas_test_data_generation_rag.txt",
     "A multi-hop query involves multiple steps of reasoning, requiring information from two or more sources."),
]

TEXT = {doc_id: text for doc_id, _src, text in CORPUS}
print("чанків у корпусі:", len(CORPUS))
print("символів разом :", sum(len(t) for t in TEXT.values()))
'''
    ),
    code(
        r'''
# Перевірка, що уривки — СПРАВЖНІ цитати, а не переказ.
# Якщо файлів research/ немає, клітинка не падає, а каже про це.
import pathlib

_SRC_DIR = ROOT / "research" / "06b"
_checked, _found, _missing = 0, 0, []

for _doc_id, _src, _text in CORPUS:
    _path = _SRC_DIR / _src
    if not _path.is_file():
        _missing.append(_src)
        continue
    _flat = " ".join(_path.read_text(encoding="utf-8", errors="replace").split())
    _checked += 1
    if " ".join(_text.split()) in _flat:
        _found += 1
        print(f"{_doc_id} {_src:42} OK")
    else:
        print(f"{_doc_id} {_src:42} НЕ ЗНАЙДЕНО")

print()
if _missing:
    print("файлів немає в research/06b:", sorted(set(_missing)))
print(f"цитат перевірено: {_checked}, збіглося: {_found}")
QUOTE_CHECK = {"checked": _checked, "found": _found}
assert _missing or _found == _checked, "уривок не знайдено у файлі-джерелі"
'''
    ),
    code(
        r'''
# Тестовий набір: 8 кейсів. Кожен має золотий чанк і «чанка-двійника» —
# тематично близький, але не той, що відповідає на питання.
# Поле reference записано словами з відповідного чанка, щоб еталон був перевірним.
CASES = [
    ("Q1", "What does the Faithfulness metric measure?",
     "Faithfulness measures how factually consistent a response is with the retrieved context.", "D01", "D03"),
    ("Q2", "When is a response considered faithful?",
     "A response is considered faithful if all its claims can be supported by the retrieved context.", "D02", "D01"),
    ("Q3", "What does Context Precision evaluate?",
     "Context Precision evaluates the retriever ability to rank relevant chunks higher than irrelevant ones.", "D03", "D04"),
    ("Q4", "How many relevant documents were successfully retrieved?",
     "Context Recall measures how many of the relevant documents were successfully retrieved.", "D04", "D06"),
    ("Q5", "What is Answer Relevancy?",
     "The Answer Relevancy metric measures how relevant a response is to the user input.", "D05", "D01"),
    ("Q6", "Does context recall require a reference?",
     "Calculating context recall always requires a reference to compare against.", "D06", "D09"),
    ("Q7", "What does NoiseSensitivity measure?",
     "NoiseSensitivity measures how often a system makes errors by providing incorrect responses.", "D07", "D04"),
    ("Q8", "Is LLM-based evaluation deterministic?",
     "LLM-based metrics can be somewhat non-deterministic.", "D09", "D08"),
]

print(f"{'id':4} {'питання':50} {'gold':5} {'двійник':8}")
for _cid, _q, _ref, _gold, _twin in CASES:
    print(f"{_cid:4} {_q[:50]:50} {_gold:5} {_twin:8}")
print()
print("кейсів:", len(CASES))
'''
    ),

    # ── 17.2 ─────────────────────────────────────────────────────────────
    md(
        """
## 17.2 Метрики власними руками: формули з документації

Тепер — арифметика. Нижче реалізовано рівно ті формули, які наведено в документації RAGAS:

- `Faithfulness = (твердження відповіді, підтверджені контекстом) / (усі твердження відповіді)`
- `Context Precision@K = Σ (Precision@k × v_k) / (кількість релевантних у топ-K)`,
  де `Precision@k = tp@k / (tp@k + fp@k)`
- `ID-Based Context Precision = |retrieved_ids ∩ reference_ids| / |retrieved_ids|`
- `Context Recall = (твердження еталона, підтверджені контекстом) / (усі твердження еталона)`
- `ID-Based Context Recall = |retrieved_ids ∩ reference_ids| / |reference_ids|`
- `Answer Relevancy = (1/N) · Σ cos_sim(E_gi, E_o)`

**Що замінено.** У RAGAS крок «видобути твердження» робить LLM, а «перевірити твердження» — LLM
(або класифікатор HHEM). Тут обидва кроки детерміновані: твердження = речення, перевірка = частка
змістових слів твердження, наявних у контексті, з порогом `TAU`. «Зворотні питання» для answer
relevancy — це речення самої відповіді, а «ембединги» — tf-idf вектори.

**Важливо про формулу Context Recall.** У документації RAGAS вона подана через твердження
**еталонної відповіді**, а не через ID чанків. ID-based версія — окрема метрика з іншим знаменником
(кількість еталонних ID). Нижче пораховано обидві: саме на їхній різниці видно, чому не можна
порівнювати числа різних формул.
"""
    ),
    code(
        r'''
import math
import re

STOP = {"a", "all", "an", "and", "are", "as", "at", "be", "been", "by", "can", "do", "does", "for",
        "from", "has", "how", "i", "if", "in", "is", "it", "its", "more", "not", "of", "on", "one",
        "or", "that", "the", "this", "than", "these", "they", "to", "was", "were", "what", "when",
        "which", "who", "with", "you", "your", "two"}


def terms(text):
    """Змістові слова тексту: латиниця й цифри, без стоп-слів."""
    return [w for w in re.findall(r"[a-z0-9]+", text.lower()) if w not in STOP]


# idf рахуємо на ФІКСОВАНІЙ колекції: корпус + питання + еталони.
# Фіксована колекція робить вектори однаковими між прогонами.
COLLECTION = [t for _d, _s, t in CORPUS] + [c[1] for c in CASES] + [c[2] for c in CASES]
DF = Counter()
for _doc in COLLECTION:
    DF.update(set(terms(_doc)))
VOCAB = sorted(DF)
IDF = {w: math.log((1 + len(COLLECTION)) / (1 + DF[w])) + 1.0 for w in VOCAB}
print("слів у словнику:", len(VOCAB), "| документів у колекції:", len(COLLECTION))
'''
    ),
    code(
        r'''
def vec(text):
    """tf-idf вектор тексту в словнику колекції."""
    tf = Counter(terms(text))
    return [tf.get(w, 0) * IDF[w] for w in VOCAB]


def cosine(a, b):
    """Косинусна близькість двох векторів."""
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return 0.0 if na == 0.0 or nb == 0.0 else dot / (na * nb)


def rank(query):
    """Ранжування чанків за косинусною близькістю (детерміноване)."""
    scored = sorted(((cosine(vec(query), vec(t)), d) for d, _s, t in CORPUS),
                    key=lambda pair: (-pair[0], pair[1]))
    return [d for _s, d in scored]


def retrieve(query, k=2, exclude=()):
    """Топ-k чанків, крім виключених."""
    return [d for d in rank(query) if d not in exclude][:k]


for _cid, _q, _ref, _gold, _twin in CASES:
    _top = retrieve(_q, 3, exclude=(_twin,))
    print(f"{_cid}  gold={_gold}  топ-3 (без двійника) = {_top}  {'OK' if _top[0] == _gold else 'ПРОМАХ'}")
'''
    ),
    code(
        r'''
TAU = 0.8  # поріг «твердження підтверджено контекстом» (заміна вердикту LLM)


def split_claims(text):
    """Твердження = речення. Заміна кроку «LLM видобуває твердження»."""
    return [p for p in re.split(r"(?<=[.!?])\s+", text.strip()) if p]


def first_sentence(text):
    return split_claims(text)[0]


def support_fraction(claim, contexts):
    """Частка змістових слів твердження, наявних у контекстах (або об'єднанні контекстів)."""
    need = terms(claim)
    have = set(terms(" ".join(contexts)))
    if not need:
        return 0.0
    return sum(1 for w in need if w in have) / len(need)


def faithfulness(response, contexts, tau=TAU):
    """Формула RAGAS: підтверджені твердження / усі твердження."""
    claims = split_claims(response)
    detail = [(c, round(support_fraction(c, contexts), 3)) for c in claims]
    supported = sum(1 for _c, frac in detail if frac >= tau)
    return supported / len(claims), detail


def answer_relevancy(question, answer):
    """Формула RAGAS: середній косинус між питанням і «зворотними питаннями».
    Заміна: зворотні питання — речення відповіді; ембединги — tf-idf вектори."""
    pseudo_questions = split_claims(answer)
    sims = [cosine(vec(question), vec(p)) for p in pseudo_questions]
    return sum(sims) / len(sims), list(zip(pseudo_questions, [round(s, 4) for s in sims]))


_good = "Faithfulness measures how factually consistent a response is with the retrieved context."
_bad_tail = " It was introduced in 1975 by the same team, and it relies on a cosine kernel."
_ctx = [TEXT["D01"], TEXT["D03"]]

_score_good, _det_good = faithfulness(_good, _ctx)
_score_bad, _det_bad = faithfulness(_good + _bad_tail, _ctx)
print("без вигадки  faithfulness =", round(_score_good, 3), _det_good)
print("із вигадкою  faithfulness =", round(_score_bad, 3))
for _claim, _frac in _det_bad:
    _verdict = "підтверджено" if _frac >= TAU else "НЕ підтверджено"
    print(f"   {_frac:.3f}  {_verdict:14} {_claim[:78]}")
'''
    ),
    code(
        r'''
def context_precision_ranked(retrieved, relevant):
    """Context Precision@K з документації: сума (Precision@k * v_k) / |relevant|."""
    hits = 0
    acc = 0.0
    for k, chunk_id in enumerate(retrieved, start=1):
        if chunk_id in relevant:
            hits += 1
            acc += hits / k
    return acc / len(relevant) if relevant else 0.0


def context_precision_ids(retrieved, relevant):
    """ID-Based Context Precision: |retrieved ∩ reference| / |retrieved|."""
    return len(set(retrieved) & set(relevant)) / len(retrieved) if retrieved else 0.0


def context_recall_ids(retrieved, relevant):
    """ID-Based Context Recall: |retrieved ∩ reference| / |reference|."""
    return len(set(retrieved) & set(relevant)) / len(relevant) if relevant else 0.0


print("Чутливість до ПОРЯДКУ при незмінному складі чанків (релевантний лише D01):")
print(f"{'порядок':26} {'precision@K':>12} {'precision(ID)':>14} {'recall(ID)':>11}")
for _order in (["D01", "D03", "D04"], ["D03", "D01", "D04"], ["D03", "D04", "D01"]):
    print(f"{str(_order):26} {context_precision_ranked(_order, ['D01']):12.4f} "
          f"{context_precision_ids(_order, ['D01']):14.4f} {context_recall_ids(_order, ['D01']):11.4f}")
print()
print("rank-aware precision реагує на перестановку; ID-based precision і recall — ні.")
'''
    ),

    # ── 17.3 ─────────────────────────────────────────────────────────────
    md(
        """
## 17.3 Три конвеєри: чи розрізняють метрики, де саме зламалося

Побудуємо три конфігурації на одному наборі:

| Варіант | Ретривер | Генератор | Що очікуємо побачити |
|---|---|---|---|
| **A** | добрий: золотий чанк першим | відповідь узята з контексту | усе високо |
| **B** | добрий: той самий | відповідь + вигадане твердження | падає лише `faithfulness` |
| **C** | зламаний: золотого чанка немає взагалі | відповідь узята з контексту | падають метрики пошуку, `faithfulness` = 1.0 |

Варіант B — це помилка **генерації**, варіант C — помилка **пошуку**. Метрики мусять їх розрізнити.
"""
    ),
    code(
        r'''
HALLUCINATION = " It was introduced in 1975 by the same team, and it relies on a cosine kernel."
K_RETRIEVED = 2


def run_variant(kind):
    """Прогонить тестовий набір через один із трьох варіантів конвеєра."""
    rows = []
    for case_id, question, reference, gold, twin in CASES:
        if kind == "A":
            got = retrieve(question, K_RETRIEVED, exclude=(twin,))[:1] + [twin]
            answer = reference
        elif kind == "B":
            got = retrieve(question, K_RETRIEVED, exclude=(twin,))[:1] + [twin]
            answer = reference + HALLUCINATION
        else:
            # Навмисно зламаний ретривер: повертає двійника й сусіда, але ЖОДНОГО разу — золотий.
            rest = [d for d in rank(TEXT[twin]) if d not in (twin, gold)][: K_RETRIEVED - 1]
            got = [twin] + rest
            answer = first_sentence(TEXT[twin])

        faith_score, _ = faithfulness(answer, [TEXT[g] for g in got])
        relevancy_score, _ = answer_relevancy(question, answer)
        rows.append({
            "case": case_id,
            "retrieved": got,
            "answer": answer,
            "faithfulness": faith_score,
            "answer_relevancy": relevancy_score,
            "context_precision": context_precision_ranked(got, [gold]),
            "context_precision_id": context_precision_ids(got, [gold]),
            "context_recall_id": context_recall_ids(got, [gold]),
        })
    return rows


METRICS = ("faithfulness", "answer_relevancy", "context_precision",
           "context_precision_id", "context_recall_id")
RUNS = {kind: run_variant(kind) for kind in ("A", "B", "C")}

print(f"{'варіант':8}" + "".join(f"{m:>22}" for m in METRICS))
for _kind in ("A", "B", "C"):
    _rows = RUNS[_kind]
    _means = [sum(r[m] for r in _rows) / len(_rows) for m in METRICS]
    print(f"{_kind:8}" + "".join(f"{v:22.4f}" for v in _means))
print()
print("Перевірка: у B упала лише faithfulness (і разом із нею relevancy), у C — лише метрики пошуку.")
'''
    ),
    code(
        r'''
# Те саме по кейсах: видно, що варіант C дає faithfulness = 1.0 на НЕПРАВИЛЬНОМУ контексті.
print(f"{'кейс':5} {'A: faith/rel':>16} {'B: faith/rel':>16} {'C: faith/rel':>16}   retrieved(C)")
for _case_id in [c[0] for c in CASES]:
    _a = next(r for r in RUNS["A"] if r["case"] == _case_id)
    _b = next(r for r in RUNS["B"] if r["case"] == _case_id)
    _c = next(r for r in RUNS["C"] if r["case"] == _case_id)
    print(f"{_case_id:5} {_a['faithfulness']:.3f}/{_a['answer_relevancy']:.3f}   "
          f"{_b['faithfulness']:.3f}/{_b['answer_relevancy']:.3f}   "
          f"{_c['faithfulness']:.3f}/{_c['answer_relevancy']:.3f}   {_c['retrieved']}")
print()
print("Висновок: faithfulness = 1.0 означає лише 'відповідь не вигадує понад контекст',")
print("а не 'контекст правильний'. Тому faithfulness читають РАЗОМ із context recall.")
'''
    ),
    code(
        r'''
# Покроковий розбір answer relevancy: чому вигадка знижує оцінку вдвічі.
_question = CASES[0][1]
_val_a, _det_a = answer_relevancy(_question, RUNS["A"][0]["answer"])
_val_b, _det_b = answer_relevancy(_question, RUNS["B"][0]["answer"])
print("питання:", _question)
print()
print(f"варіант A: answer relevancy = {_val_a:.4f}")
for _pq, _sim in _det_a:
    print(f"   cosine={_sim:.4f}  <- {_pq[:92]}")
print(f"варіант B: answer relevancy = {_val_b:.4f}")
for _pq, _sim in _det_b:
    print(f"   cosine={_sim:.4f}  <- {_pq[:92]}")
print()
print("Друге речення не має спільних змістових слів із питанням, тому його внесок — нуль,")
print("і середнє падає рівно вдвічі. Це документована властивість метрики: вона карає")
print("відповіді, що містять зайві деталі.")
'''
    ),

    # ── 17.4 ─────────────────────────────────────────────────────────────
    md(
        """
## 17.4 Тестовий набір: схема кейса й завантаження в RAGAS

Тестовий набір цього ноутбука зібрано руками зі справжніх уривків, і це навмисно: генерація
набору через граф знань RAGAS потребує LLM-викликів, а ноутбук мусить працювати без ключів.
Тут важливо побачити **схему**, яку очікують метрики.

Далі — клітинки зі справжньою `ragas`. Вони необов'язкові: без встановленого пакета вони
друкують пояснення й пропускаються.
"""
    ),
    code(
        r'''
# Схема одного кейса. Зверніть увагу: reference (еталонна відповідь) і
# reference_context_ids (еталонні ID чанків) — РІЗНІ входи для різних метрик.
CASE_SCHEMA = {
    "case_id": "Q3",
    "user_input": "What does Context Precision evaluate?",
    "response": "Context Precision evaluates the retriever ability to rank relevant chunks higher than irrelevant ones.",
    "reference": "Context Precision evaluates the retriever ability to rank relevant chunks higher than irrelevant ones.",
    "retrieved_context_ids": ["D03", "D04"],
    "reference_context_ids": ["D03"],
}
for _key, _value in CASE_SCHEMA.items():
    print(f"  {_key:24} {_value}")
print()
print("ID-и чанків треба мати ДО побудови індексу — інакше недоступні найдешевші метрики:")
print("IDBasedContextPrecision і IDBasedContextRecall працюють без жодного виклику LLM.")
'''
    ),
    code(
        r'''
# Справжня ragas: завантаження набору й оцінювання. Без пакета — пропускається.
try:
    from ragas import EvaluationDataset
    from ragas import evaluate as ragas_evaluate
    from ragas.llms import LangchainLLMWrapper
    from ragas.metrics import LLMContextRecall, Faithfulness, FactualCorrectness
except ImportError as exc:
    print("ragas не встановлено — клітинку пропущено:", exc)
    print("Встановлення: pip install ragas  (тягне datasets, langchain, openai)")
    print("Потім для запуску потрібен ключ провайдера: os.environ['OPENAI_API_KEY'] = '...'")
else:
    dataset_rows = [
        {
            "user_input": row["case"] + ": " + question,
            "retrieved_contexts": [TEXT[g] for g in row["retrieved"]],
            "response": row["answer"],
            "reference": reference,
        }
        for row, (_cid, question, reference, _gold, _twin) in zip(RUNS["A"], CASES)
    ]
    evaluation_dataset = EvaluationDataset.from_list(dataset_rows)
    print("EvaluationDataset зібрано, зразків:", len(dataset_rows))
    print()
    print("Далі (потребує ключа провайдера — тому закоментовано):")
    print("  evaluator_llm = LangchainLLMWrapper(llm)")
    print("  result = ragas_evaluate(dataset=evaluation_dataset,")
    print("                          metrics=[LLMContextRecall(), Faithfulness(), FactualCorrectness()],")
    print("                          llm=evaluator_llm)")
    print()
    print("Документований вивід цього виклику на 5 питаннях:")
    print("  {'context_recall': 1.0000, 'faithfulness': 0.8571, 'factual_correctness': 0.7280}")
'''
    ),
    code(
        r'''
# Справжня ragas, колекційний API (актуальний у 0.4.x). Теж без пакета — пропускається.
try:
    from ragas.metrics.collections import ContextPrecision, ContextRecall, Faithfulness as F2
except ImportError as exc:
    print("ragas.metrics.collections недоступний — клітинку пропущено:", exc)
    print("У версіях до 0.4 цей модуль відсутній; там використовують legacy API")
    print("(from ragas.metrics import Faithfulness, метод single_turn_ascore).")
else:
    print("Доступні класи колекційного API:", ContextPrecision.__name__, ContextRecall.__name__, F2.__name__)
    print()
    print("Схема виклику (потребує ключа, тому не виконується):")
    print("  client = AsyncOpenAI()")
    print("  llm = llm_factory('gpt-4o-mini', client=client)")
    print("  scorer = ContextPrecision(llm=llm)")
    print("  result = await scorer.ascore(user_input=..., reference=..., retrieved_contexts=[...])")
'''
    ),

    # ── 17.5 ─────────────────────────────────────────────────────────────
    md(
        """
## 17.5 Ціна: скільки викликів судді й скільки це коштує

Документація RAGAS не публікує точну кількість викликів на метрику. Але її можна **вивести з
описаних кроків**: faithfulness = 1 видобуток тверджень + перевірка кожного твердження
(`1 + claims`), context recall = 1 розбір еталона + перевірка кожного твердження, context precision =
порівняння кожного знайденого чанка, answer relevancy = 1 генерація набору зворотних питань.

Це **нижня оцінка**, а не підтверджена цифра. Головне від неї не залежить: метрика коштує не одного
виклику, а `1 + кількість тверджень`.
"""
    ),
    code(
        r'''
_n_cases = len(CASES)
_claims_per_case = [len(split_claims(row["answer"])) for row in RUNS["A"]]

CALL_RULES = {
    "faithfulness": sum(1 + c for c in _claims_per_case),
    "context_recall": sum(1 + len(split_claims(ref)) for _cid, _q, ref, _g, _t in CASES),
    "context_precision": sum(len(row["retrieved"]) for row in RUNS["A"]),
    "answer_relevancy": _n_cases,
}

print(f"{'метрика':20} {'викликів':>9} {'на зразок':>10}   правило з документації")
_RULES_TEXT = {
    "faithfulness": "1 видобуток тверджень + перевірка кожного",
    "context_recall": "1 розбір еталона + перевірка кожного твердження",
    "context_precision": "порівняння кожного знайденого чанка",
    "answer_relevancy": "1 генерація набору зворотних питань",
}
for _name, _calls in CALL_RULES.items():
    print(f"{_name:20} {_calls:9} {_calls / _n_cases:10.2f}   {_RULES_TEXT[_name]}")
JUDGE_CALLS = sum(CALL_RULES.values())
print(f"{'РАЗОМ':20} {JUDGE_CALLS:9} {JUDGE_CALLS / _n_cases:10.2f}")
print()
print("тверджень у відповідях (варіант A):", _claims_per_case)
print("Висновок: довга відповідь дорожча за коротку при тій самій кількості зразків.")
'''
    ),
    code(
        r'''
# Ціни. Якір — документований приклад RAGAS; ціни Claude читаємо з research/econ/.
DOCUMENTED = {"samples": 5, "input_tokens": 5463, "output_tokens": 355,
              "gpt4o_in_per_mtok": 5.0, "gpt4o_out_per_mtok": 15.0}

_anchor_cost = (DOCUMENTED["input_tokens"] * DOCUMENTED["gpt4o_in_per_mtok"] / 1e6
                + DOCUMENTED["output_tokens"] * DOCUMENTED["gpt4o_out_per_mtok"] / 1e6)
print("Документований якір RAGAS (AspectCriticWithReference на 5 зразках):")
print(f"  TokenUsage(input_tokens={DOCUMENTED['input_tokens']}, output_tokens={DOCUMENTED['output_tokens']})")
print(f"  total_cost(...) за GPT-4o $5/$15 = {_anchor_cost:.5f}   (документація: 0.03264)")
print()

PRICE_LINE = re.compile(
    r"^\|\s*(Claude [^|]+?)\s*\|\s*\$([\d.]+) / MTok\s*\|"
    r"\s*\$[\d.]+ / MTok\s*\|\s*\$[\d.]+ / MTok\s*\|"
    r"\s*\$[\d.]+ / MTok\s*\|\s*\$([\d.]+) / MTok\s*\|",
    re.M,
)
_price_path = ROOT / "research" / "econ" / "anthropic_pricing.md"
if _price_path.is_file():
    _prices = {}
    for _match in PRICE_LINE.finditer(_price_path.read_text(encoding="utf-8", errors="replace")):
        _prices[_match.group(1)] = (float(_match.group(2)), float(_match.group(3)))
    print("ціни з", _price_path.relative_to(ROOT), "->", len(_prices), "рядків")
else:
    _prices = {}
    print("НЕ ЗНАЙДЕНО:", _price_path, "— ціни недоступні")
    print("Файл можна перезавантажити: python3 fetch.py https://platform.claude.com/docs/en/about-claude/pricing.md")

SELECTED = ("Claude Haiku 4.5", "Claude Sonnet 5", "Claude Opus 5")
PER_CALL_IN = DOCUMENTED["input_tokens"] / DOCUMENTED["samples"]
PER_CALL_OUT = DOCUMENTED["output_tokens"] / DOCUMENTED["samples"]
print()
print(f"похідні на 1 виклик судді: {PER_CALL_IN:.1f} вхідних, {PER_CALL_OUT:.1f} вихідних токенів")
'''
    ),
    code(
        r'''
# Вартість набору: виклики * токени * ціна. Без ключів — усе локально.
_tokens_in = JUDGE_CALLS * PER_CALL_IN
_tokens_out = JUDGE_CALLS * PER_CALL_OUT
print(f"на {_n_cases} зразків: {JUDGE_CALLS} викликів -> "
      f"вхід {_tokens_in:.0f} ток., вихід {_tokens_out:.0f} ток.")
print()

COST_TABLE = {}
print(f"{'модель-суддя':20} {'$/MTok in/out':>15} {_n_cases:>10} {'500':>9} {'5000':>10} {'500 x3 повт':>12}")
for _name in SELECTED:
    if _name not in _prices:
        print(f"{_name:20} — немає в джерелі цін")
        continue
    _in_price, _out_price = _prices[_name]
    _cost = _tokens_in * _in_price / 1e6 + _tokens_out * _out_price / 1e6
    _per_sample = _cost / _n_cases
    COST_TABLE[_name] = _cost
    print(f"{_name:20} {f'${_in_price:g}/${_out_price:g}':>15} {_cost:10.5f} "
          f"{_per_sample * 500:9.2f} {_per_sample * 5000:10.2f} {_per_sample * 500 * 3:12.2f}")
print()
print("Порада: у CI ганяйте 20-50 зразків, повний набір — окремим нічним прогоном.")
'''
    ),
    md(
        """
## 17.5 (продовження) Детермінізм: чому два прогони дають різні числа

Документація RAGAS каже прямо: LLM-метрики «can be somewhat non-deterministic as the LLM might not
always return the same result for the same input». Наслідок — **середнє по набору коливається**, і
коливання масштабується як `1/√n`.

Змоделюймо це локально: суддя в 90% випадків згоден з експертом (`p = 0.90`) і оцінює `n` зразків.
Прогонів багато, сід фіксований — результат відтворюється.
"""
    ),
    code(
        r'''
import random

JUDGE_AGREEMENT = 0.90
N_RUNS = 2000
SEED = 20260926


def simulate_runs(agreement, n_samples, n_runs=N_RUNS, seed=SEED):
    """Повертає ВІДСОРТОВАНИЙ список середніх оцінок за n_runs прогонів."""
    rng = random.Random(seed)
    return sorted(sum(1 for _ in range(n_samples) if rng.random() < agreement) / n_samples
                  for _ in range(n_runs))


SIM = {}
print(f"{'n':>5} {'теор. sd':>9} {'емпір. sd':>10} {'p2.5':>7} {'p97.5':>7} {'розмах':>8}")
for _n in (20, 100, 500):
    _obs = simulate_runs(JUDGE_AGREEMENT, _n)
    _theor = math.sqrt(JUDGE_AGREEMENT * (1 - JUDGE_AGREEMENT) / _n)
    _emp = (sum((x - sum(_obs) / len(_obs)) ** 2 for x in _obs) / len(_obs)) ** 0.5
    _lo = _obs[int(0.025 * len(_obs))]
    _hi = _obs[int(0.975 * len(_obs))]
    SIM[_n] = {"p2_5": _lo, "p97_5": _hi, "theor_sd": _theor, "emp_sd": _emp}
    print(f"{_n:5} {_theor:9.4f} {_emp:10.4f} {_lo:7.3f} {_hi:7.3f} {_hi - _lo:8.3f}")
print()
print("На 20 зразках той самий конвеєр без жодної зміни дає середню від 0.75 до 1.00.")
print("Різниця між двома версіями, менша за цей розмах, — це шум судді, а не покращення.")
'''
    ),
    code(
        r'''
# Скільки зразків потрібно, щоб надійно побачити різницю?
# Двосторонній тест, alpha = 0.05, потужність 0.80, порівняння двох часток.
Z_ALPHA = 1.959963985   # квантиль 0.975 стандартного нормального розподілу
Z_POWER = 0.8416212336  # квантиль 0.80


def required_n(delta, agreement=JUDGE_AGREEMENT):
    return math.ceil(2 * (Z_ALPHA + Z_POWER) ** 2 * agreement * (1 - agreement) / delta ** 2)


print("n = 2 * (z_0.975 + z_0.80)^2 * p * (1-p) / delta^2")
print(f"  = 2 * {(Z_ALPHA + Z_POWER) ** 2:.6f} * {JUDGE_AGREEMENT * (1 - JUDGE_AGREEMENT):.2f} / delta^2")
print()
REQUIRED = {}
for _delta in (0.10, 0.05, 0.02):
    _need = required_n(_delta)
    REQUIRED[_delta] = _need
    _total_judge_calls = 2 * _need * (JUDGE_CALLS / _n_cases)
    print(f"delta = {_delta:.2f}  ->  {_need:5} зразків на варіант, "
          f"{2 * _need:5} разом, {_total_judge_calls:8.0f} викликів судді")

print()
for _name in SELECTED:
    if _name not in _prices:
        continue
    _in_price, _out_price = _prices[_name]
    _cmp_calls = 2 * REQUIRED[0.05] * (JUDGE_CALLS / _n_cases)
    _cmp_cost = _cmp_calls * PER_CALL_IN * _in_price / 1e6 + _cmp_calls * PER_CALL_OUT * _out_price / 1e6
    print(f"одне порівняння з delta=0.05 на {_name:18} = ${_cmp_cost:.2f}")
'''
    ),
    md(
        """
## 17.5 (завершення) Чим керувати детермінізмом

Схема модельного оцінювача в документації OpenAI показує, які ручки взагалі доступні:
`sampling_params` містить `seed`, `top_p`, `temperature`, `max_completions_tokens`,
`reasoning_effort`. Документовані обмеження: «`temperature` changes not supported for reasoning
models», а «`reasoning_effort` is not supported for non-reasoning models». Тобто зафіксувати
`temperature` для reasoning-моделі через цю схему неможливо — це треба знати до того, як обіцяти
відтворюваність.

Формат відповіді судді теж фіксований: `{"result": float, "steps": [{"description": ..., "conclusion": ...}]}`.
"""
    ),
    code(
        r'''
# Схема конфігурації судді з документації OpenAI (це КОНФІГУРАЦІЯ, не виклик API).
GRADER_SCHEMA = {
    "type": "score_model",
    "name": "my_score_model",
    "input": [
        {"role": "system", "content": "You are an expert grader."},
        {"role": "user", "content": "Reference: {{ item.reference_answer }}. Model answer: {{ sample.output_text }}"},
    ],
    "pass_threshold": 0.5,
    "model": "o4-mini-2025-04-16",
    "range": [0, 1],
    "sampling_params": {"max_completions_tokens": 32768, "top_p": 1, "reasoning_effort": "medium"},
}
for _key in ("type", "name", "pass_threshold", "model", "range"):
    print(f"  {_key:16} {GRADER_SCHEMA[_key]}")
print(f"  {'sampling_params':16} {GRADER_SCHEMA['sampling_params']}")
print()
print("Формат виводу судді: result (float) + steps (description, conclusion).")
print("Тобто суддя повертає не лише число, а й обґрунтування — його корисно логувати.")
print()
print("Документовані обмеження:")
print("  - набір дозволених моделей обмежений (gpt-4o-*, gpt-4.1-*, o1-2024-12-17, o3-*, o4-mini-*)")
print("  - temperature не підтримується для reasoning-моделей")
print("  - reasoning_effort не підтримується для non-reasoning-моделей")
print("  - grader hacking: модель може навчитися експлуатувати слабкості судді")
'''
    ),

    # ── підсумок ─────────────────────────────────────────────────────────
    md(
        """
## Підсумок

| Що з'ясували | Число з цього ноутбука |
|---|---|
| Метрики розрізняють генерацію і пошук | варіант B: faith 1.0 → 0.5; варіант C: recall 1.0 → 0.0 |
| `faithfulness` не потребує еталона | 8 із 8 випадків вигадки виявлено |
| Context precision залежить від порядку | 1.0 → 0.5 → 0.3333 при тій самій множині чанків |
| ID-based метрики до порядку байдужі | 0.3333 у всіх трьох перестановках |
| Оцінювання коштує не одного виклику | 7.00 викликів судді на зразок для 4 метрик |
| Розкид судді обмежує роздільність | на 20 зразках розмах 0.25 |
| Скільки треба для delta = 0.05 | 566 зразків на варіант (1132 разом) |

Головний практичний висновок: **одна метрика не діагностує RAG**. Тримайте щонайменше пару
(retrieval-метрика + generation-метрика), фіксуйте версію судді й промптів метрик, і рахуйте
розкид до того, як радіти покращенню на 0.02.
"""
    ),
    code(
        r'''
# Самоперевірка: фіксуємо числа цього ноутбука, щоб зміна поведінки не пройшла непомітно.
def mean_of(kind, metric):
    rows = RUNS[kind]
    return sum(r[metric] for r in rows) / len(rows)


assert QUOTE_CHECK["found"] == len(CORPUS), "не всі цитати збіглися з файлами-джерелами"
assert abs(mean_of("A", "faithfulness") - 1.0) < 1e-9
assert abs(mean_of("B", "faithfulness") - 0.5) < 1e-9
assert abs(mean_of("C", "faithfulness") - 1.0) < 1e-9
assert abs(mean_of("C", "context_recall_id") - 0.0) < 1e-9
assert abs(mean_of("A", "context_recall_id") - 1.0) < 1e-9
assert mean_of("A", "answer_relevancy") > mean_of("C", "answer_relevancy")
assert JUDGE_CALLS == 56, JUDGE_CALLS
assert required_n(0.05) == 566, required_n(0.05)
assert SIM[20]["theor_sd"] > SIM[500]["theor_sd"]
assert abs(context_precision_ranked(["D01", "D03", "D04"], ["D01"]) - 1.0) < 1e-9
assert abs(context_precision_ranked(["D03", "D04", "D01"], ["D01"]) - 1 / 3) < 1e-9
assert context_precision_ids(["D01", "D03", "D04"], ["D01"]) == 1 / 3

print("усі перевірки пройдено")
print()
print("середні по варіантах:")
for _kind in ("A", "B", "C"):
    print(f"  {_kind}: " + "  ".join(f"{m}={mean_of(_kind, m):.4f}" for m in METRICS))
'''
    ),
    md(
        """
## Куди далі

- [`sections/17-rag-eval.md`](../sections/17-rag-eval.md) — текст розділу з формулами й джерелами.
- [`sections/24-eval.md`](../sections/24-eval.md) — евалюація як процес: golden set, LLM-як-суддя,
  упередження судді, red teaming, CI-гейт.
- [`sections/16-rag.md`](../sections/16-rag.md) — сам конвеєр RAG: чанкінг, гібридний пошук, reranking.
- `research/06b/ragas_*.txt` — локальні копії документації RAGAS, з яких узято формули й приклади.
- `research/econ/anthropic_pricing.md` — ціни, з яких пораховано вартість оцінювання.
"""
    ),
]
