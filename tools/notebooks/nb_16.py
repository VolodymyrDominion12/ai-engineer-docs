"""Ноутбук 16 — «RAG: chunking, гібридний пошук, Postgres і Qdrant».

Розділ довідника: sections/16-rag.md
Працює без API-ключів, без GPU і без мережі.
"""

from nbkit import md, code

FILENAME = "16-rag.ipynb"
TITLE = "16. RAG"

SETUP16 = r'''
# Спільне налаштування: шукаємо корінь репозиторію, щоб шляхи research/... працювали
# незалежно від того, звідки запущено Jupyter. Ноутбук не потребує ні ключів, ні мережі.
import pathlib
import sys

_cwd = pathlib.Path.cwd()
if (_cwd / "research").is_dir():
    ROOT = _cwd
elif (_cwd.parent / "research").is_dir():
    ROOT = _cwd.parent
else:
    ROOT = _cwd
    print("Каталог research/ не знайдено — ноутбук усе одно працює, він його не використовує.")

print("Python :", sys.version.split()[0])
print("Корінь :", ROOT)
'''

VERSIONS16 = '''
# Версії бібліотек (для відтворюваності). Жодна з них не обов'язкова.
import importlib

for _name in ("nbformat", "rank_bm25", "sentence_transformers", "qdrant_client", "pgvector"):
    try:
        _mod = importlib.import_module(_name)
        print(f"{_name:22} {getattr(_mod, '__version__', '?')}")
    except ImportError:
        print(f"{_name:22} НЕ ВСТАНОВЛЕНО (для цього ноутбука не обов'язково)")
'''

CELLS = [
    md(
        """
# 16. RAG: chunking, гібридний пошук, Postgres і Qdrant

**Розділ довідника:** [`sections/16-rag.md`](../sections/16-rag.md)

**Потрібно: нічого обов'язкового (опційно — локальні embeddings)**

Ноутбук повністю виконується на стандартній бібліотеці Python. Жодних API-ключів, жодного GPU,
жодного звернення до мережі. Єдина опційна залежність — `sentence-transformers`: клітинка, яка її
використовує, позначена й безпечно пропускається, якщо пакета немає або модель не завантажена
локально.

**Що ви зробите:**

1. Зберете повторення логіки `_merge_splits` і побачите, чому `chunk_overlap` часто не дає
   перекриття взагалі (16.1).
2. Виміряєте відстань між двома фактами відповіді й порахуєте, яке перекриття потрібне (16.1).
3. Реалізуєте BM25 власними руками на стандартній бібліотеці й порівняєте з косинусною схожістю
   на TF-IDF (16.2).
4. Побачите, як лексичний пошук дає нуль на іншій словоформі (16.2).
5. Реалізуєте RRF у десять рядків і звірите його з прикладом із документації Elasticsearch (16.3).
6. Виміряєте, як константа `k` змінює вагу позицій, і порівняєте дві форми зваженого RRF (16.3).
7. Побачите, чим cross-encoder відрізняється від BM25 — на механізмі, а не на словах (16.4).
8. Перевірите, як метрика відстані змінює порядок результатів (16.5).
9. Зберете повний конвеєр від чанка до промпту з посиланнями (16.6).

**Чого цей ноутбук НЕ робить:** він не містить справжніх embeddings. Роль семантичної гілки грає
косинус на TF-IDF — це **навчальна заміна**, і в коді вона позначена саме так. Справжні embeddings
потребують моделі, яка або встановлюється окремо, або завантажується з мережі.
"""
    ),
    md("## Налаштування"),
    code(SETUP16),
    code(VERSIONS16),

    # ── 16.1 ────────────────────────────────────────────────────────────────
    md(
        """
## 16.1 Chunking: перекриття працює цілими фрагментами

`RecursiveCharacterTextSplitter` ріже текст рекурсивно за списком роздільників, а потім склеює
дрібні фрагменти в чанки. Перекриття реалізоване в `_merge_splits` — і воно **відкидає цілі
фрагменти**, а не окремі символи. Через це `chunk_overlap=200` може дати нульове перекриття.

Нижче — спрощена модель цієї логіки. Вона не є копією бібліотеки, але повторює ключову
поведінку: рекурсію за роздільниками і відкидання цілих фрагментів.
"""
    ),
    code(
        r'''
import re


class NB16Chunker:
    """Спрощена модель RecursiveCharacterTextSplitter: рекурсія за роздільниками
    плюс склеювання з перекриттям (логіка _merge_splits)."""

    def __init__(self, chunk_size, chunk_overlap, separators):
        if chunk_overlap >= chunk_size:
            raise ValueError("chunk_overlap має бути меншим за chunk_size")
        self.size = chunk_size
        self.overlap = chunk_overlap
        self.separators = list(separators)

    def split(self, text):
        return self._merge(self._split(text, self.separators), " ")

    def _split(self, text, separators):
        sep, rest = separators[-1], []
        for i, cand in enumerate(separators):
            if cand == "" or re.search(re.escape(cand), text):
                sep, rest = cand, separators[i + 1:]
                break
        parts = list(text) if sep == "" else [chunk_part for chunk_part in text.split(sep) if chunk_part]
        out = []
        for chunk_part in parts:
            if len(chunk_part) <= self.size:
                out.append(chunk_part)
            elif rest:
                out.extend(self._split(chunk_part, rest))
            else:
                out.append(chunk_part)
        return out

    def _merge(self, splits, separator):
        sep_len = len(separator)
        docs, current, total = [], [], 0
        for piece in splits:
            piece_len = len(piece)
            if total + piece_len + (sep_len if current else 0) > self.size and current:
                docs.append(separator.join(current))
                while total > self.overlap or (
                    total + piece_len + (sep_len if current else 0) > self.size and total > 0
                ):
                    total -= len(current[0]) + (sep_len if len(current) > 1 else 0)
                    current = current[1:]
            current.append(piece)
            total += piece_len + (sep_len if len(current) > 1 else 0)
        if current:
            docs.append(separator.join(current))
        return docs


print("NB16Chunker готовий")
'''
    ),
    code(
        r'''
# Документ містить відповідь на запит «як часто надсилати heartbeat?»,
# рознесену на ДВА факти: «десять хвилин» і назву параметра.
DOC16 = ("Брокер відкидає неактивні з'єднання через тридцять хвилин простою. "
         "Щоб цього уникнути, надсилайте heartbeat кожні десять хвилин. "
         "Інтервал heartbeat задається параметром keep_alive_interval "
         "у конфігурації клієнта.")
ANCHORS16 = ("десять хвилин", "keep_alive_interval")

# Усталені роздільники LangChain — БЕЗ межі речення:
SEPS_DEFAULT = ("\n\n", "\n", " ", "")
# Роздільники, які радить техзвіт Chroma:
SEPS_SENTENCE = ("\n\n", "\n", ". ", " ", "")

chunk_log = []          # журнал: кожен запис — НОВИЙ словник (знімок стану)
for c_label, c_seps in (("усталені", SEPS_DEFAULT), ("з межею речення", SEPS_SENTENCE)):
    print(f"--- роздільники: {c_label} ---")
    for c_size, c_overlap in ((85, 0), (85, 20), (85, 40)):
        c_chunks = NB16Chunker(c_size, c_overlap, c_seps).split(DOC16)
        c_full = [ci for ci, ch in enumerate(c_chunks)
                  if all(anchor in ch for anchor in ANCHORS16)]
        chunk_log.append({"seps": c_label, "size": c_size, "overlap": c_overlap,
                          "n_chunks": len(c_chunks), "full_answer": list(c_full)})
        print(f"  size={c_size}, overlap={c_overlap}: чанків {len(c_chunks)}, "
              f"повна відповідь: {c_full if c_full else 'ЖОДЕН'}")
'''
    ),
    md(
        """
Два спостереження з виводу:

**Перше.** З усталеними роздільниками `overlap=20` дає **чотири** чанки замість трьох — текст
фізично дублюється, бо перекриття відміряється цілими словами. Це видно й у журналі:
`n_chunks` зростає.

**Друге, важливіше.** З межею речення в роздільниках `overlap=20` дає **три** чанки — стільки ж,
скільки `overlap=0`. Перекриття не спрацювало взагалі: щоб досягти 20 символів, алгоритм мусив би
відкинути ціле речення, а це залишило б чанк порожнім.

Тепер з'ясуймо, чому жодна з шести конфігурацій не дала повної відповіді. Виміряймо відстань між
двома фактами.
"""
    ),
    code(
        '''
gap_start = DOC16.index(ANCHORS16[0]) + len(ANCHORS16[0])
gap_end = DOC16.index(ANCHORS16[1])
print(f"від кінця {ANCHORS16[0]!r} до початку {ANCHORS16[1]!r}: {gap_end - gap_start} символів")
print(f"довжина документа: {len(DOC16)} символів")
'''
    ),
    code(
        '''
# Робоче правило: перекриття мусить бути не меншим за відстань між фактами.
for c_size, c_overlap in ((85, 60), (160, 60)):
    c_chunks = NB16Chunker(c_size, c_overlap, SEPS_DEFAULT).split(DOC16)
    c_full = [ci for ci, ch in enumerate(c_chunks)
              if all(anchor in ch for anchor in ANCHORS16)]
    print(f"size={c_size}, overlap={c_overlap}: чанків {len(c_chunks)}, "
          f"повна відповідь: {c_full if c_full else 'ЖОДЕН'}")

print()
print("Ціна перекриття — скільки тексту на виході:")
for c_size, c_overlap in ((85, 0), (85, 60)):
    total = sum(len(ch) for ch in NB16Chunker(c_size, c_overlap, SEPS_DEFAULT).split(DOC16))
    print(f"  size={c_size}, overlap={c_overlap}: {total} символів на виході "
          f"з {len(DOC16)} у документі (×{total / len(DOC16):.2f})")
'''
    ),
    md(
        """
Щойно перекриття перевищило 42 символи, чанк із повною відповіддю з'явився. Це і є робоче правило:
**перекриття має бути не меншим за типову відстань між фактами, які мусять відповісти разом.**
Відстань вимірюють на своїх даних, а не вгадують.

Друга частина виводу показує ціну: перекриття — це прямий множник на обсяг індексу. Ви платите
за дублікати і під час індексації, і під час кожного запиту.

**Що показав техзвіт Chroma** (n=5 чанків, `text-embedding-3-large`):

| Chunking | Size | Overlap | Recall | IoU |
|---|---|---|---|---|
| Recursive | 800 (~661) | 400 | 85.4 ± 34.9 | 1.5 ± 1.3 |
| TokenText | 800 | 400 | 87.9 ± 31.7 | 1.4 ± 1.1 |
| Recursive | 400 (~312) | 200 | 88.1 ± 31.6 | 3.3 ± 2.7 |
| TokenText | 400 | 200 | 88.6 ± 29.7 | 2.7 ± 2.2 |
| Recursive | 400 (~276) | 0 | **89.5 ± 29.7** | **3.6 ± 3.2** |
| TokenText | 400 | 0 | 89.2 ± 29.2 | 2.7 ± 2.2 |

Менший чанк виграв за recall, а найкращий рядок — **без перекриття взагалі**. Причина видна в
стовпці IoU: метрика рахує кожен релевантний токен у чисельнику лише один раз, а всі повернуті
токени в знаменнику — усі. Перекриття збільшує знаменник, не збільшуючи чисельник.
"""
    ),

    # ── 16.2 ────────────────────────────────────────────────────────────────
    md(
        """
## 16.2 BM25 власними руками і порівняння з косинусною схожістю

BM25 — це IDF, насичення частоти терміна (`k1`) і нормалізація довжини документа (`b`). Нижче
реалізація **BM25Okapi** з тими самими усталеними параметрами, що й у пакеті `rank_bm25`:
`k1=1.5`, `b=0.75`, `epsilon=0.25`, IDF як `log(N - f + 0.5) - log(f + 0.5)` з підлогою для
від'ємних значень.

Поруч — косинусна схожість на TF-IDF. Вона теж **лексична**: обидві метрики дивляться на збіг
слів, а не на зміст. Це важливо пам'ятати, щоб не сплутати цю демонстрацію зі справжнім
семантичним пошуком.
"""
    ),
    code(
        r'''
import math
import re
from collections import Counter

CORPUS16 = [
    "Connection reset by peer. Check firewall rules between client and broker.",     # d0
    "Error code TS-999 indicates a failed TLS handshake in the transport layer.",    # d1
    "A failed TLS handshake usually means an expired or mismatched certificate.",    # d2
    "How to rotate API keys without downtime.",                                      # d3
    "Handshake timeouts on the transport gateway after a certificate renewal.",      # d4
    "Billing FAQ: invoices, refunds and the quarterly revenue report.",              # d5
    "Rate limits are counted per organisation, not per API key.",                    # d6
    "The broker drops idle connections after thirty minutes of inactivity.",         # d7
    "Certificate chain validation fails when the intermediate CA is missing.",       # d8
    "Streaming responses use server-sent events and cannot be resumed mid-stream.",  # d9
    "Audit logs retain ninety days of request metadata for compliance review.",      # d10
    "Retry with exponential backoff when you receive HTTP 429 or 529.",              # d11
]


def tokenize16(t):
    return re.findall(r"\w+", t.lower())


class BM25Okapi16:
    def __init__(self, corpus, k1=1.5, b=0.75, epsilon=0.25):
        self.docs = [tokenize16(d) for d in corpus]
        self.k1, self.b = k1, b
        self.n = len(self.docs)
        self.avgdl = sum(map(len, self.docs)) / self.n
        self.freqs = [Counter(d) for d in self.docs]
        df = Counter()
        for token_list in self.docs:
            df.update(set(token_list))
        self.idf = {t: math.log(self.n - f + 0.5) - math.log(f + 0.5)
                    for t, f in df.items()}
        eps = epsilon * (sum(self.idf.values()) / len(self.idf))
        for t, v in list(self.idf.items()):
            if v < 0:
                self.idf[t] = eps

    def score(self, query, i):
        dl, acc = len(self.docs[i]), 0.0
        for t in tokenize16(query):
            f = self.freqs[i].get(t, 0)
            if f:
                acc += self.idf[t] * (f * (self.k1 + 1)) / (
                    f + self.k1 * (1 - self.b + self.b * dl / self.avgdl))
        return acc


def cosine_tfidf16(corpus, query, i):
    docs = [tokenize16(d) for d in corpus]
    df = Counter()
    for bm_doc_tokens in docs:
        df.update(set(bm_doc_tokens))
    n_docs = len(docs)
    vec = lambda toks: {t: (1 + math.log(cnt)) * math.log((n_docs + 1) / (df[t] + 1))
                        for t, cnt in Counter(toks).items()}
    vec_a, vec_b = vec(docs[i]), vec(tokenize16(query))
    dot = sum(vec_a[t] * vec_b.get(t, 0.0) for t in vec_a)
    norm_a = math.sqrt(sum(v * v for v in vec_a.values()))
    norm_b = math.sqrt(sum(v * v for v in vec_b.values()))
    return dot / (norm_a * norm_b) if norm_a and norm_b else 0.0


bm16 = BM25Okapi16(CORPUS16)
print(f"Корпус: {len(CORPUS16)} документів, avgdl = {bm16.avgdl:.1f} токенів")
print(f"idf('tls') = {bm16.idf['tls']:.4f}, idf('999') = {bm16.idf['999']:.4f}")
'''
    ),
    code(
        '''
query16 = "TS-999 TLS handshake"
ranked16 = sorted(range(len(CORPUS16)), key=lambda j: -bm16.score(query16, j))
print(f"Запит: {query16!r}")
print(f"{'rank':>4} {'doc':>5} {'BM25':>8} {'cosine':>8}  текст")
for q_rank, q_i in enumerate(ranked16[:4], 1):
    print(f"{q_rank:>4} {'d' + str(q_i):>5} {bm16.score(query16, q_i):8.4f} "
          f"{cosine_tfidf16(CORPUS16, query16, q_i):8.4f}  {CORPUS16[q_i][:52]}")
'''
    ),
    md(
        """
BM25 поставив потрібний документ першим із оцінкою 5.85 — у понад два рази вище за наступний. Це той
самий ефект, який Anthropic описує для `TS-999`: рідкісний рядок отримує високий IDF, і документ,
що його містить, різко виривається вперед.

Косинус на TF-IDF дає ту саму послідовність — і це очікувано, бо обидві метрики лексичні, а корпус
малий. Справжня різниця між гібридними гілками проявляється тільки тоді, коли одна з них — навчена
модель embeddings.

Тепер подивімося, де лексичний пошук ламається.
"""
    ),
    code(
        '''
query_morph = "why does my connection keep dropping"
ranked_morph = sorted(range(len(CORPUS16)), key=lambda j: -bm16.score(query_morph, j))
print(f"Запит: {query_morph!r}")
for m_rank, m_i in enumerate(ranked_morph[:3], 1):
    print(f"{m_rank}. d{m_i:<3} BM25={bm16.score(query_morph, m_i):6.4f}  {CORPUS16[m_i][:58]}")
print()
print("Правильна відповідь — d7:")
print("  ", CORPUS16[7])
print("   токени запиту : connection, dropping")
print("   токени d7     : connections, drops")
'''
    ),
    md(
        """
Документ d7 «The broker drops idle connections after thirty minutes of inactivity» — очевидна
правильна відповідь — отримав **нуль**. BM25 порівнює рядки, а не слова: запит містить `connection`
і `dropping`, документ — `connections` і `drops`. Без стемера або лематизатора це різні терміни.

Саме тому класичний BM25 у пошукових системах завжди йде разом з аналізатором: токенізатор,
приведення до нижнього регістру, стемер або лематизатор. Для української мови ситуація гостріша,
ніж для англійської: відмінкові форми змінюють закінчення, і без лематизатора лексична гілка
втрачає більшість збігів.

Звідси й висновок на користь гібридного пошуку: лексична гілка точна там, де є точний рядок, і
безпорадна там, де є лише зміст.
"""
    ),

    # ── 16.3 ────────────────────────────────────────────────────────────────
    md(
        """
## 16.3 RRF: злиття за позиціями, а не за оцінками

Reciprocal Rank Fusion відкидає оцінки взагалі й працює тільки з позиціями. Це позбавляє від
проблеми несумісних шкал: BM25 необмежений зверху, косинусна схожість лежить у межах від -1 до 1.

Ядро алгоритму — десять рядків. Перевіримо його на прикладі з документації Elasticsearch, де
`rank_constant=1` і ранг нумерується з одиниці.
"""
    ),
    code(
        '''
from collections import defaultdict


def rrf_fuse(branch_lists, k=60):
    """branch_lists — списки ідентифікаторів, кожен за спаданням релевантності.
    Ранг нумерується з 1, як в Elasticsearch."""
    scores = defaultdict(float)
    for branch in branch_lists:
        for rank, doc_id in enumerate(branch, start=1):
            scores[doc_id] += 1.0 / (k + rank)
    return sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))


list_a = [1, 2, 3, 4]        # лексична гілка
list_b = [5, 4, 3, 1, 2]     # семантична гілка

print("k=1 (rank_constant=1, як у прикладі з документації):")
for r_doc, r_score in rrf_fuse([list_a, list_b], k=1):
    print(f"  _id: {r_doc} = {r_score:.3f}")

print()
print("k=60 (усталене значення Elasticsearch) — порядок змінюється:")
for r_doc, r_score in rrf_fuse([list_a, list_b], k=60):
    print(f"  _id: {r_doc} = {r_score:.6f}")
'''
    ),
    md(
        """
Числа при `k=1` точно збігаються з документацією Elasticsearch: `_id: 1 = 1.0/(1+1) + 1.0/(1+4) =
0.7`, підсумковий порядок — `[1, 4, 2, 3, 5]`. Це найпростіша перевірка правильності реалізації
RRF: візьміть опублікований приклад і відтворіть його до останньої цифри.

Другий блок показує, що при `k=60` порядок **інший**: `_id: 3` піднявся з третього місця на третє,
обійшовши `_id: 2`. Константа `k` — не косметика.
"""
    ),
    code(
        '''
print("Внесок документа залежно від позиції (rank з 1):")
k_values = (1, 2, 60, 200)
print(f"{'позиція':>8} " + " ".join(f"{'k=' + str(k):>10}" for k in k_values))
for k_rank in (1, 2, 3, 10, 20):
    row = [1.0 / (k + k_rank) for k in k_values]
    print(f"{k_rank:>8} " + " ".join(f"{v:10.6f}" for v in row))

print()
print("У скільки разів 1-ша позиція важить більше за 20-ту:")
for k in k_values:
    ratio = (1.0 / (k + 1)) / (1.0 / (k + 20))
    print(f"  k={k:<4} → у {ratio:.2f} раза")
'''
    ),
    md(
        """
Це найважливіша таблиця для налаштування злиття. При `k=1` перше місце важить удесятеро більше за
двадцяте — злиття фактично довіряє верхівці кожного списку. При `k=60` різниця становить лише 31
відсоток, і **глибина списку починає важити більше, ніж позиція в ньому**: документ, знайдений
обома гілками навіть невисоко, перемагає документ, знайдений однією гілкою на першому місці.

Усталені значення різняться між системами, і це треба знати перед тим, як переносити конфігурацію:
Elasticsearch і ParadeDB використовують `rank_constant = 60` і нумерацію з 1, а Qdrant — `k = 2` і
нумерацію **з нуля**.
"""
    ),
    code(
        '''
# Дві форми зваженого RRF. Перша — усталена, друга — формула з документації Qdrant.
def rrf_std_w(ranks, weights, k):
    """Сума w/(k+rank), rank з 1."""
    return sum(w / (k + r) for r, w in zip(ranks, weights))


def rrf_qdrant_w(ranks0, weights, k):
    """Формула Qdrant: w / (k + (r + 1)/w - 1), де r — позиція з нуля."""
    return sum(w / (k + (r + 1) / w - 1) for r, w in zip(ranks0, weights))


print("Твердження з документації Qdrant: «документ на 3-й позиції з вагою 3.0 отримує")
print("стільки ж, скільки документ на 1-й позиції з вагою 1.0».")
print()
for k in (0, 1, 2, 60):
    w3 = rrf_std_w([3], [3.0], k)
    w1 = rrf_std_w([1], [1.0], k)
    print(f"  усталена форма, k={k:<3}: 3-тя -> {w3:.4f}, 1-ша -> {w1:.4f}, "
          f"рівні: {abs(w3 - w1) < 1e-12}")
print()
for k in (1, 2, 60):
    q3 = rrf_qdrant_w([2], [3.0], k)
    q1 = rrf_qdrant_w([0], [1.0], k)
    print(f"  формула Qdrant, k={k:<3}: 3-тя -> {q3:.4f}, 1-ша -> {q1:.4f}, "
          f"рівні: {abs(q3 - q1) < 1e-12}")
'''
    ),
    code(
        '''
# DBSF: не відкидає оцінки, а нормалізує їхні розподіли за межами три-сигма.
def dbsf_norm(values):
    n = len(values)
    mu = sum(values) / n
    var = sum((v - mu) ** 2 for v in values) / (n - 1) if n > 1 else 0.0
    sigma = var ** 0.5
    if sigma == 0:
        return [0.5] * n
    return [(v - (mu - 3 * sigma)) / (6 * sigma) for v in values]


bm25_raw = [12.4, 9.1, 7.8]      # шкала BM25: необмежена
cosine_raw = [0.87, 0.84, 0.61]  # шкала косинуса: 0..1
print("Сирі оцінки двох гілок лежать у різних масштабах:")
print(f"  BM25   : {bm25_raw}")
print(f"  cosine : {cosine_raw}")
print()
print("Після DBSF обидві гілки в одному діапазоні:")
print(f"  BM25   : {[round(v, 4) for v in dbsf_norm(bm25_raw)]}")
print(f"  cosine : {[round(v, 4) for v in dbsf_norm(cosine_raw)]}")
print()
print("Лінійна комбінація з вагою 0.5 — без нормалізації і з нею:")
for d_i in range(3):
    raw = 0.5 * bm25_raw[d_i] + 0.5 * cosine_raw[d_i]
    norm = 0.5 * dbsf_norm(bm25_raw)[d_i] + 0.5 * dbsf_norm(cosine_raw)[d_i]
    print(f"  документ {d_i}: без нормалізації -> {raw:8.4f}, з DBSF -> {norm:.4f}")
print()
print("Крайні випадки, описані в документації:")
print(f"  усі оцінки однакові [5.0, 5.0, 5.0] -> {dbsf_norm([5.0, 5.0, 5.0])}")
print(f"  один документ [5.0]                 -> {dbsf_norm([5.0])}")
'''
    ),
    md(
        """
Рівність «3-тя позиція з вагою 3.0 = 1-ша позиція з вагою 1.0» виконується **лише** для усталеної
форми при `k=0`. Для опублікованої формули Qdrant вона не виконується за жодного з перевірених `k`,
включно з усталеним `k=2`. Це розбіжність між прозовим поясненням і формулою в документації, а не
помилка в реалізації. Практичний висновок: **не переносьте ваги між системами наосліп** — ваговий
коефіцієнт має сенс лише разом із конкретною формулою й конкретним `k`.

Блок DBSF ілюструє інший компроміс. Сира комбінація дає 6.6350, нормалізована — 0.6492. Якщо ви
додаєте третю ознаку (свіжість документа, популярність) із вагою 0.3, то в першому випадку вона
потоне в шумі BM25, а в другому реально вплине на результат. Нормалізація потрібна саме тоді, коли
до RRF додають власні сигнали.

Скільки чанків брати з кожного префетчу, залежить від того, який **сигнал** ви хочете отримати.
Qdrant радить збільшувати `limit` префетчу, якщо ранжування нестабільне: статистика DBSF береться
з top-k, тобто з малої вибірки.
"""
    ),

    # ── 16.4 ────────────────────────────────────────────────────────────────
    md(
        """
## 16.4 Переранжування: чим cross-encoder відрізняється від BM25

Перша стадія пошуку змушена бути дешевою: вона порівнює запит із мільйонами документів, тому
документ і запит кодуються **незалежно** (bi-encoder). Друга стадія може дозволити собі читати
пару `(запит, документ)` разом — і бачить те, що перша не бачить фізично: близькість термінів,
їхній порядок, контекст.

Нижче — мінімальна демонстрація цього механізму. `bm25_scores16` — звичайний BM25.
`proximity16` — **заміна** cross-encoder'а: вона не є натренованою моделлю, але відтворює саме ту
властивість, якої BM25 не має — читає пару разом і враховує, наскільки тісно стоять терміни запиту.
"""
    ),
    code(
        r'''
POOL16 = {
    0: "Щоб уникнути розриву, надсилайте heartbeat кожні десять хвилин.",
    1: "heartbeat десять heartbeat хвилин heartbeat десять heartbeat хвилин",
    2: "Інтервал heartbeat задається параметром keep_alive_interval у конфігурації клієнта.",
    3: "Брокер відкидає неактивні з'єднання через тридцять хвилин простою.",
}
QUERY16 = "heartbeat десять хвилин"


def bm25_scores16(query, corpus, k1=1.5, b=0.75, epsilon=0.25):
    docs = [tokenize16(d) for d in corpus]
    n, avgdl = len(docs), sum(map(len, docs)) / len(docs)
    freqs = [Counter(d) for d in docs]
    df = Counter()
    for d in docs:
        df.update(set(d))
    idf = {t: math.log(n - f + 0.5) - math.log(f + 0.5) for t, f in df.items()}
    eps = epsilon * (sum(idf.values()) / len(idf))
    for t, v in list(idf.items()):
        if v < 0:
            idf[t] = eps
    out = []
    for i, doc in enumerate(docs):
        acc = 0.0
        for t in tokenize16(query):
            f = freqs[i].get(t, 0)
            if f:
                acc += idf[t] * (f * (k1 + 1)) / (f + k1 * (1 - b + b * len(doc) / avgdl))
        out.append((i, acc))
    return out


def proximity16(query, text):
    """Заміна cross-encoder: покриття термінів плюс тіснота їхнього сусідства."""
    q_terms = set(tokenize16(query))
    pair_doc_tokens = tokenize16(text)
    pos = {}
    for tok_pos, tok in enumerate(pair_doc_tokens):
        pos.setdefault(tok, []).append(tok_pos)
    matched = [t for t in q_terms if t in pos]
    if not matched:
        return 0.0, 0.0, 0.0
    coverage = len(matched) / len(q_terms)
    if len(matched) > 1:
        span = max(pos[t][-1] for t in matched) - min(pos[t][0] for t in matched) + 1
        proximity = (len(matched) - 1) / (span - 1)
    else:
        proximity = 0.5
    return coverage, proximity, coverage + 0.5 * proximity


bm25_pool = dict(bm25_scores16(QUERY16, [POOL16[i] for i in sorted(POOL16)]))
print(f"Запит: {QUERY16!r}")
print()
print(f"{'чанк':>5} {'BM25':>8} {'покриття':>9} {'тісність':>9} {'разом':>8}  текст")
for p_i in sorted(POOL16):
    cov, prox, total = proximity16(QUERY16, POOL16[p_i])
    print(f"{p_i:>5} {bm25_pool[p_i]:8.4f} {cov:9.2f} {prox:9.2f} {total:8.2f}"
          f"  {POOL16[p_i][:44].rstrip()}")

order_by_bm25 = sorted(POOL16, key=lambda i: -bm25_pool[i])
order_by_rerank = sorted(order_by_bm25, key=lambda i: -proximity16(QUERY16, POOL16[i])[2])
print()
print(f"Порядок BM25          : {order_by_bm25}")
print(f"Порядок після rerank  : {order_by_rerank}")
'''
    ),
    md(
        """
BM25 поставив набитий повтореннями чанк 1 на перше місце (0.5424 проти 0.3361) — він бачить лише
частоти термінів. Друга стадія підняла чанк 0, бо в ньому потрібні терміни стоять у межах трьох
слів (тісність 0.67 проти 0.29).

**Ключове обмеження, яке легко забути:** переранжування не піднімає recall. Воно перевпорядковує
**уже знайдених** кандидатів. Якщо правильної відповіді немає в пулі першої стадії, друга стадія її
не вигадає. Тому пул беруть із запасом: Anthropic використовує top-150 кандидатів, щоб залишити
top-20.

**Друге обмеження — шкала оцінок.** Документація Sentence Transformers застерігає, що моделі родини
MS MARCO повертають **логіти**, а не оцінки від 0 до 1; для оцінок у діапазоні 0–1 модель
завантажують з `activation_fn=torch.nn.Sigmoid()`, і це не впливає на ранжування. Практично це
означає, що абсолютні значення оцінок reranker'а не можна використовувати як поріг релевантності
без калібрації на своїх даних.
"""
    ),
    code(
        '''
# Опційна клітинка: справжні embeddings локально.
# Вона безпечно пропускається, якщо пакета немає або модель не завантажена в кеш
# (ноутбук мусить працювати без мережі).
try:
    from sentence_transformers import SentenceTransformer, util
except ImportError:
    print("sentence-transformers НЕ ВСТАНОВЛЕНО — клітинка пропущена.")
    print("Це очікувано: ноутбук працює без жодних зовнішніх залежностей.")
else:
    try:
        embed_model = SentenceTransformer("sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2")
    except (OSError, ValueError) as exc:
        print("Модель не завантажена локально — клітинка пропущена, щоб не звертатися до мережі.")
        print(f"Причина: {type(exc).__name__}")
    else:
        pairs = [
            ("як часто надсилати heartbeat",
             "Щоб уникнути розриву, надсилайте heartbeat кожні десять хвилин."),
            ("як часто надсилати heartbeat",
             "Брокер відкидає неактивні з'єднання через тридцять хвилин простою."),
        ]
        emb = embed_model.encode([p[0] for p in pairs] + [p[1] for p in pairs],
                                 convert_to_tensor=True)
        half = len(pairs)
        for idx, (q_text, d_text) in enumerate(pairs):
            sim = float(util.cos_sim(emb[idx], emb[half + idx])[0][0])
            print(f"  cosine(query, doc{idx}) = {sim:.4f}   {d_text[:46]}")
        print()
        print("Порівняйте з BM25 із попередніх клітинок: лексична метрика не бачить")
        print("перефразування, а навчена модель — бачить.")
'''
    ),

    # ── 16.5 ────────────────────────────────────────────────────────────────
    md(
        """
## 16.5 Метрика відстані змінює порядок результатів

`pgvector` надає шість операторів: `<->` (L2), `<#>` (від'ємний скалярний добуток), `<=>`
(косинусна **відстань**), `<+>` (L1), `<~>` (Hamming) і `<%>` (Jaccard). Дві пастки задокументовані
прямо: `<#>` повертає від'ємне значення, бо Postgres підтримує лише сканування індексу в порядку
`ASC`; а `<=>` — це відстань, тож схожість дорівнює `1 - (embedding <=> ...)`.

Перевірмо конверсії та один неприємний наслідок вибору метрики.
"""
    ),
    code(
        '''
import math as _math


def norm_vec(v):
    n = _math.sqrt(sum(x * x for x in v))
    return [x / n for x in v]


def l2_dist(a, b):
    return _math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))


def ip_dot(a, b):
    return sum(x * y for x, y in zip(a, b))


def cos_dist(a, b):
    return 1 - ip_dot(norm_vec(a), norm_vec(b))


pg_query = [3.0, 1.0, 2.0]
pg_rows = {"a": [1.0, 2.0, 3.0], "b": [4.0, 5.0, 6.0], "c": [3.0, 1.0, 2.0]}

print(f"{'рядок':>6} {'<-> L2':>10} {'<#> (відʼємн. IP)':>18} {'<=> cosine dist':>17} {'1 - <=>':>9}")
for row_name, row_vec in pg_rows.items():
    print(f"{row_name:>6} {l2_dist(row_vec, pg_query):10.4f} "
          f"{-ip_dot(row_vec, pg_query):18.4f} {cos_dist(row_vec, pg_query):17.4f} "
          f"{1 - cos_dist(row_vec, pg_query):9.4f}")

print()
print("Ненормалізовані вектори — порядок за L2 і за скалярним добутком РІЗНИЙ:")
pg_l2_order = sorted(pg_rows, key=lambda nm: l2_dist(pg_rows[nm], pg_query))
pg_ip_order = sorted(pg_rows, key=lambda nm: -ip_dot(pg_rows[nm], pg_query))
print(f"  за L2              : {pg_l2_order}")
print(f"  за скалярним добутком: {pg_ip_order}")

print()
print("Ті самі вектори після нормалізації до довжини 1:")
norm_rows = {nm: norm_vec(v) for nm, v in pg_rows.items()}
nq = norm_vec(pg_query)
pg_l2_norm = sorted(norm_rows, key=lambda nm: l2_dist(norm_rows[nm], nq))
pg_ip_norm = sorted(norm_rows, key=lambda nm: -ip_dot(norm_rows[nm], nq))
print(f"  за L2              : {pg_l2_norm}")
print(f"  за скалярним добутком: {pg_ip_norm}")
print(f"  порядки збігаються : {pg_l2_norm == pg_ip_norm}")
'''
    ),
    md(
        """
Найважливіше тут — третій блок. Для **ненормалізованих** векторів L2 і скалярний добуток дають
**різні порядки**: за L2 рядок `c` абсолютно точний збіг, а за скалярним добутком першим іде `b`,
бо він просто довший. Після нормалізації порядки збігаються.

Документація pgvector радить: «якщо вектори нормалізовані до довжини 1 (як embeddings OpenAI),
використовуйте скалярний добуток для найкращої швидкості» — і саме тому, що після нормалізації
порядки однакові. Практичний висновок: **метрика мусить відповідати тому, як навчалася модель**.
Якщо модель нормалізує вихід, а ви будуєте індекс із `vector_l2_ops`, ви отримаєте інший порядок і
не побачите жодної помилки.

**Фільтрація — головна пастка pgvector.** З наближеними індексами фільтрація застосовується
**після** сканування індексу. Документація дає арифметику: якщо умова відбирає 10% рядків, то з
HNSW і усталеним `hnsw.ef_search = 40` у середньому збігатиметься лише 4 рядки. Запит поверне 4
результати замість 5 — і жодної помилки. Рятує ітеративне сканування, додане у версії 0.8.0:
`SET hnsw.iterative_scan = strict_order;`.

**Найчастіша причина «індекс не використовується»** — `ORDER BY` мусить бути результатом оператора
відстані, а не виразом:

```sql
-- індекс використається:
ORDER BY embedding <=> '[3,1,2]' LIMIT 5;
-- індекс НЕ використається:
ORDER BY 1 - (embedding <=> '[3,1,2]') DESC LIMIT 5;
```

Усталені параметри, які варто знати напам'ять: HNSW — `m = 16`, `ef_construction = 64`,
`hnsw.ef_search = 40`; IVFFlat — `ivfflat.probes = 1`, а `lists` підбирають як `rows / 1000` до
1M рядків і `sqrt(rows)` понад 1M.
"""
    ),

    # ── 16.6 ────────────────────────────────────────────────────────────────
    md(
        """
## 16.6 Повний конвеєр: чанк → індекс → дві гілки → RRF → контекст

Зберемо конвеєр повністю на локальних даних. Роль семантичної гілки грає косинус на TF-IDF — у
коді це позначено як **навчальна заміна**. Усе інше справжнє: чанки, метадані зі зсувами, дві
незалежні гілки, RRF, переранжування й формування промпту з посиланнями.

Метадані зі зсувами (`start`, `end`) — не прикраса: без них неможливо ні показати посилання, ні
підсвітити фрагмент у джерелі.
"""
    ),
    code(
        r'''
PIPE_DOCS = {
    "broker.md": ("Брокер відкидає неактивні з'єднання через тридцять хвилин простою. "
                  "Щоб цього уникнути, надсилайте heartbeat кожні десять хвилин. "
                  "Інтервал heartbeat задається параметром keep_alive_interval "
                  "у конфігурації клієнта."),
    "tls.md": ("Помилка TS-999 означає невдалий TLS-рукостискання на транспортному рівні. "
               "Найчастіша причина — протермінований або невідповідний сертифікат. "
               "Перевірте ланцюжок сертифікатів і проміжний CA."),
    "keys.md": ("Ключі API обертаються без простою: створіть новий ключ, розгорніть його, "
                "дочекайтеся нуля запитів на старому і лише тоді відкличте старий ключ."),
}


def chunk_pipe(text, size=110, overlap=40):
    """Етап 2: чанки разом зі зсувами в документі."""
    out, start = [], 0
    while start < len(text):
        out.append((text[start:start + size], start))
        if start + size >= len(text):
            break
        start += size - overlap
    return out


PIPE_INDEX = [{"id": f"{doc}#{i}", "doc": doc, "start": start,
               "end": start + len(piece), "text": piece}
              for doc, text in PIPE_DOCS.items()
              for i, (piece, start) in enumerate(chunk_pipe(text))]


def bm25_rank16(query, corpus, k1=1.5, b=0.75, epsilon=0.25):
    docs = [tokenize16(d) for d in corpus]
    n_docs, avgdl = len(docs), sum(map(len, docs)) / len(docs)
    freqs = [Counter(d) for d in docs]
    df = Counter()
    for pipe_doc_tokens in docs:
        df.update(set(pipe_doc_tokens))
    idf = {t: math.log(n_docs - f + 0.5) - math.log(f + 0.5) for t, f in df.items()}
    eps = epsilon * (sum(idf.values()) / len(idf))
    for t, v in list(idf.items()):
        if v < 0:
            idf[t] = eps
    out = []
    for i, doc in enumerate(docs):
        acc = 0.0
        for t in tokenize16(query):
            f = freqs[i].get(t, 0)
            if f:
                acc += idf[t] * (f * (k1 + 1)) / (f + k1 * (1 - b + b * len(doc) / avgdl))
        out.append((i, acc))
    return out


def tfidf_rank16(query, corpus):
    """НАВЧАЛЬНА ЗАМІНА справжніх embeddings: та сама лексика, інша вага термінів."""
    docs = [tokenize16(d) for d in corpus]
    df = Counter()
    for tf_doc_tokens in docs:
        df.update(set(tf_doc_tokens))
    n_docs = len(docs)
    vec = lambda toks: {t: (1 + math.log(cnt)) * math.log((n_docs + 1) / (df[t] + 1))
                        for t, cnt in Counter(toks).items()}
    q_vec = vec(tokenize16(query))
    q_norm = math.sqrt(sum(v * v for v in q_vec.values())) or 1.0
    out = []
    for i, tf_doc_tokens in enumerate(docs):
        doc_vec = vec(tf_doc_tokens)
        doc_norm = math.sqrt(sum(v * v for v in doc_vec.values())) or 1.0
        out.append((i, sum(doc_vec[t] * q_vec.get(t, 0.0) for t in doc_vec) / (doc_norm * q_norm)))
    return out


def ids_by_score(pairs):
    return [i for i, _ in sorted(pairs, key=lambda kv: (-kv[1], kv[0]))]


def rrf_ids(branch_lists, k=60):
    scores = defaultdict(float)
    for branch in branch_lists:
        for rank, idx in enumerate(branch, start=1):
            scores[idx] += 1.0 / (k + rank)
    return [i for i, _ in sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))]


def retrieve16(query, pool=6, top_k=3):
    texts = [c["text"] for c in PIPE_INDEX]
    lexical = ids_by_score(bm25_rank16(query, texts))[:pool]        # етап 4а
    semantic = ids_by_score(tfidf_rank16(query, texts))[:pool]      # етап 4б
    fused = rrf_ids([lexical, semantic], k=60)                      # етап 5
    q_terms = set(tokenize16(query))
    reranked = sorted(fused, key=lambda i: -len(q_terms & set(tokenize16(PIPE_INDEX[i]["text"]))))
    return lexical, semantic, fused, reranked[:top_k]               # етап 6


def build_prompt16(query, picked):
    lines = [f"Питання: {query}", "", "Джерела:"]
    for src_no, idx in enumerate(picked, start=1):
        src = PIPE_INDEX[idx]
        lines.append(f"[{src_no}] {src['doc']} (символи {src['start']}..{src['end']}): "
                     f"{src['text'].strip()}")
    lines += ["", "Відповідай лише за наведеними джерелами. "
                  "Після кожного твердження став номер джерела у квадратних дужках."]
    return "\n".join(lines)


print(f"Проіндексовано {len(PIPE_INDEX)} чанків із {len(PIPE_DOCS)} документів")
print()
for doc_entry in PIPE_INDEX:
    print(f"  {doc_entry['id']:14} символи {doc_entry['start']:>3}..{doc_entry['end']:<3} "
          f"{doc_entry['text'][:44].strip()!r}")
'''
    ),
    code(
        '''
pipe_query = "як часто надсилати heartbeat"
p_lex, p_sem, p_fused, p_picked = retrieve16(pipe_query)
print(f"Запит: {pipe_query!r}")
print()
print(f"  лексична гілка (BM25) : {[PIPE_INDEX[i]['id'] for i in p_lex]}")
print(f"  семантична гілка      : {[PIPE_INDEX[i]['id'] for i in p_sem]}")
print(f"  після RRF (k=60)      : {[PIPE_INDEX[i]['id'] for i in p_fused]}")
print(f"  у контекст пішло      : {[PIPE_INDEX[i]['id'] for i in p_picked]}")
print()
print(build_prompt16(pipe_query, p_picked))
'''
    ),
    md(
        """
Конвеєр пройшов усі сім етапів. У цьому запуску переранжування не змінило порядок: усі три чанки
містять однакову кількість термінів запиту, тож оцінки збіглися й порядок визначив попередній RRF.
Це нормальна поведінка лексичної заміни — і ще одна причина, чому в продакшні потрібна справжня
модель, яка читає пару.

**Посилання на джерела.** Зверніть увагу, що кожен рядок контексту містить ідентифікатор документа
й діапазон символів. Саме так виглядає мінімальна основа для посилань. Anthropic пропонує готовий
механізм: документи подаються як блоки `document` із `citations.enabled`, і відповідь приходить із
блоками посилань виду

```json
{
  "type": "char_location",
  "cited_text": "The exact text being cited",
  "document_index": 0,
  "document_title": "Document Title",
  "start_char_index": 0,
  "end_char_index": 50
}
```

Дві деталі, які варто знати до того, як будувати на цьому архітектуру:

1. **Citations несумісні зі structured outputs.** Якщо ввімкнути citations на будь-якому
   користувацькому документі й одночасно передати `output_config.format`, API поверне **400**.
   Причина в документації: citations вимагають чергування блоків посилань із текстовим виводом, що
   несумісно зі строгими обмеженнями JSON-схеми.
2. **`cited_text` не зараховується у вихідні токени** — і при передачі назад у наступних ходах не
   зараховується у вхідні. Натомість увімкнення citations трохи **збільшує вхідні токени** через
   додавання до системного промпту й розбиття документів.
"""
    ),
    code(
        '''
# Арифметика вартості конверсій pgvector — тим самим кодом, що й у розділі 16.5.
print("Перевірка конверсій із документації pgvector:")
print(f"  внутрішній добуток  = (-1) * (<#>)  -> для рядка 'a': {-ip_dot(pg_rows['a'], pg_query):.4f}")
print(f"  косинусна схожість  = 1 - (<=>)     -> для рядка 'a': {1 - cos_dist(pg_rows['a'], pg_query):.4f}")
print()
print("Підсумок налаштувань, які найчастіше плутають:")
settings_table = [
    ("Qdrant RRF", "k", "2", "ранг з 0"),
    ("Elasticsearch RRF", "rank_constant", "60", "ранг з 1"),
    ("ParadeDB RRF", "k", "60", "ранг з 1"),
    ("rank_bm25", "k1 / b", "1.5 / 0.75", "BM25Okapi"),
    ("ParadeDB BM25", "k1 / b", "1.2 / 0.75", "pg_search"),
    ("pgvector HNSW", "m / ef_construction", "16 / 64", "побудова"),
    ("pgvector HNSW", "hnsw.ef_search", "40", "запит"),
    ("pgvector IVFFlat", "ivfflat.probes", "1", "запит"),
]
print(f"{'система':>18} {'параметр':>20} {'усталене':>18}  примітка")
for s_sys, s_param, s_default, s_note in settings_table:
    print(f"{s_sys:>18} {s_param:>20} {s_default:>18}  {s_note}")
'''
    ),

    # ── 16.7 ────────────────────────────────────────────────────────────────
    md(
        """
## 16.7 Самодіагностика: що перевіряти перед тим, як щось міняти

Найчастіша помилка в роботі з RAG — оптимізувати генерацію, коли проблема в пошуку. Нижче —
мінімальний набір перевірок, які варто прогнати на своєму оцінному наборі **до** будь-яких змін у
промпті чи моделі.
"""
    ),
    code(
        '''
CHECKS16 = [
    ("Порахувати recall@N першої стадії",
     "Якщо потрібного чанка немає в пулі, жодна зміна промпту не допоможе"),
    ("Порахувати відстань між фактами відповіді й порівняти з chunk_overlap",
     "Виявляє розрив відповіді між чанками до того, як ви почнете міняти embeddings"),
    ("Порівняти recall із перекриттям і без нього",
     "Техзвіт Chroma: найкращий рядок був з Overlap = 0"),
    ("Прогнати той самий запит із другою словоформою",
     "Нуль на «dropping» проти «drops» означає, що немає стемера"),
    ("Порахувати розподіл оцінок кожної гілки",
     "Якщо масштаби різні на порядки, лінійна комбінація без нормалізації безглузда"),
    ("Перевірити, що метрика індексу відповідає моделі embeddings",
     "vector_l2_ops на нормалізованих векторах дає інший порядок без жодної помилки"),
    ("Порівняти результати з увімкненим і вимкненим наближеним індексом",
     "SET LOCAL enable_indexscan = off — так вимірюють втрачений recall"),
    ("Перевірити наявність start/end у метаданих кожного чанка",
     "Без них посилання на джерело неможливе"),
    ("Порахувати, скільки чанків реально доходить до контексту",
     "Друга стадія не піднімає recall: вона працює лише з пулом першої"),
]

print(f"{'#':>3}  {'перевірка':<58} навіщо")
for chk_i, (chk_name, chk_why) in enumerate(CHECKS16, 1):
    print(f"{chk_i:>3}  {chk_name:<58} {chk_why}")

print()
print("Порядок дій: спочатку пошук, потім злиття, потім переранжування, і лише в кінці — генерація.")
'''
    ),
    # ── самоперевірка ────────────────────────────────────────────────────
    md(
        """
## Самоперевірка

Перевіряємо твердження розділу: розрив відповіді між чанками й роль перекриття, поведінку BM25 на
другій словоформі, злиття RRF і його константу, нормалізацію DBSF, переранжування, конверсії
pgvector і повний пайплайн до промпту.
"""
    ),
    code(
        r'''
# ── 1. Чанкер: overlap мусить бути меншим за size ───────────────────────
try:
    NB16Chunker(85, 85, SEPS_DEFAULT)
    nb16_raised = False
except ValueError:
    nb16_raised = True
assert nb16_raised is True, "chunk_overlap >= chunk_size мусить давати ValueError"
assert (
    len(chunk_log) == 6                                   # 2 набори роздільників × 3 перекриття
    and all(nb16_entry["full_answer"] == [] for nb16_entry in chunk_log)
    and all(nb16_entry["n_chunks"] >= 3 for nb16_entry in chunk_log)
), "жодна з шести конфігурацій не мусить зібрати повну відповідь в одному чанку"
print("✓ чанкер: overlap ≥ size → ValueError; у 6 конфігураціях повної відповіді немає в жодному чанку")

# ── 2. Розрив між фактами відповіді вимірюється, а не вгадується ────────
assert (
    len(DOC16) == 212 and gap_end - gap_start == 42
    and ANCHORS16 == ("десять хвилин", "keep_alive_interval")
    and DOC16.index(ANCHORS16[0]) + len(ANCHORS16[0]) == gap_start
), "відстань між двома фактами відповіді — 42 символи з 212"
print(f"✓ розрив: {gap_end - gap_start} символів між 'десять хвилин' і "
      f"'keep_alive_interval' у документі на {len(DOC16)} символів")

# ── 3. Перекриття 60 закриває виміряний розрив ──────────────────────────
nb16_85 = NB16Chunker(85, 60, SEPS_DEFAULT).split(DOC16)
nb16_160 = NB16Chunker(160, 60, SEPS_DEFAULT).split(DOC16)
nb16_full_85 = [nb16_i for nb16_i, nb16_ch in enumerate(nb16_85)
                if all(nb16_a in nb16_ch for nb16_a in ANCHORS16)]
nb16_full_160 = [nb16_i for nb16_i, nb16_ch in enumerate(nb16_160)
                 if all(nb16_a in nb16_ch for nb16_a in ANCHORS16)]
assert (
    nb16_full_85 == [5] and len(nb16_85) == 7
    and nb16_full_160 == [1] and len(nb16_160) == 2
), "перекриття 60 ≥ 42 мусить дати чанк із повною відповіддю"
print("✓ перекриття 60 > 42: size=85 → 7 чанків, повна відповідь у #5; "
      "size=160 → 2 чанки, повна відповідь у #1")

# ── 4. Ціна перекриття: скільки тексту на виході ────────────────────────
nb16_cost0 = sum(len(nb16_ch) for nb16_ch in NB16Chunker(85, 0, SEPS_DEFAULT).split(DOC16))
nb16_cost60 = sum(len(nb16_ch) for nb16_ch in NB16Chunker(85, 60, SEPS_DEFAULT).split(DOC16))
assert (
    nb16_cost0 == 210 and round(nb16_cost0 / len(DOC16), 2) == 0.99
    and nb16_cost60 == 552 and round(nb16_cost60 / len(DOC16), 2) == 2.60
), "перекриття 60 роздуває вихід у 2.6 раза проти документа"
print(f"✓ ціна перекриття: без нього {nb16_cost0} символів (×0.99), "
      f"з перекриттям 60 — {nb16_cost60} (×2.60)")

# ── 5. BM25: корпус, середня довжина й idf рідкісного токена ────────────
assert (
    len(CORPUS16) == 12 and round(bm16.avgdl, 1) == 10.4
    and round(bm16.idf["tls"], 4) == 1.4351
    and round(bm16.idf["999"], 4) == 2.0369
    and bm16.idf["999"] > bm16.idf["tls"]                 # рідкісніший токен важить більше
), "12 документів, avgdl 10.4; idf рідкісного токена вищий"
print(f"✓ BM25: 12 документів, avgdl = {bm16.avgdl:.1f}; idf('tls') = {bm16.idf['tls']:.4f}, "
      f"idf('999') = {bm16.idf['999']:.4f}")

# ── 6. Точний лексичний пошук: рідкісний рядок знаходиться ──────────────
assert (
    ranked16[0] == 1 and round(bm16.score(query16, 1), 4) == 5.8541
    and round(cosine_tfidf16(CORPUS16, query16, 1), 4) == 0.5541
    and bm16.score(query16, 0) == 0.0                     # у d0 немає жодного токена запиту
), "запит 'TS-999 TLS handshake' мусить підняти d1 на перше місце"
print("✓ пошук: d1 (TS-999 + TLS handshake) — перше місце, BM25 5.8541, cosine 0.5541; "
      "d0 має нуль")

# ── 7. Друга словоформа: лексичний пошук без стемера провалюється ──────
assert (
    ranked_morph[0] == 0 and round(bm16.score(query_morph, 0), 4) == 1.9868
    and bm16.score(query_morph, 7) == 0.0
    and CORPUS16[7].lower().startswith("the broker drops")
), "d7 ('drops conexions') мусить отримати нуль на запит зі 'dropping'"
print("✓ морфологія: 'dropping' не збігається з 'drops' — d7 отримує рівно 0, "
      "першим стає випадковий d0 (1.9868)")

# ── 8. RRF зливає за позиціями: константа k змінює порядок ──────────────
nb16_k1 = dict(rrf_fuse([list_a, list_b], k=1))
nb16_k60 = dict(rrf_fuse([list_a, list_b], k=60))
assert (
    nb16_k1[1] == 0.7 and round(nb16_k60[1], 6) == 0.032018
    and round(nb16_k60[4], 6) == 0.031754
    and [nb16_doc for nb16_doc, _ in rrf_fuse([list_a, list_b], k=1)] == [1, 4, 2, 3, 5]
    and [nb16_doc for nb16_doc, _ in rrf_fuse([list_a, list_b], k=60)] == [1, 4, 3, 2, 5]
), "k=1 і k=60 мусять дати різний порядок при однакових гілках"
print("✓ RRF: k=1 → [1, 4, 2, 3, 5] (1-й = 0.700), k=60 → [1, 4, 3, 2, 5] (1-й = 0.032018)")

# ── 9. Вага позиції: k=1 різко стискає, k=200 майже не розрізняє ────────
nb16_ratios = {nb16_k: round((1.0 / (nb16_k + 1)) / (1.0 / (nb16_k + 20)), 2)
               for nb16_k in (1, 2, 60, 200)}
assert (
    nb16_ratios == {1: 10.5, 2: 7.33, 60: 1.31, 200: 1.09}
    and (1.0 / 61) > (1.0 / 81)                           # 1-ша позиція завжди важить більше
), "перевага 1-ї позиції над 20-ю падає з 10.5 до 1.09 раза"
print(f"✓ вага позиції: 1-ша проти 20-ї — k=1 у {nb16_ratios[1]} раза, "
      f"k=200 у {nb16_ratios[200]} раза")

# ── 10. Зважений RRF: твердження Qdrant справджується лише за k=0 ──────
assert (
    abs(rrf_std_w([3], [3.0], 0) - rrf_std_w([1], [1.0], 0)) < 1e-12
    and abs(rrf_std_w([3], [3.0], 1) - rrf_std_w([1], [1.0], 1)) > 0.2
    and abs(rrf_qdrant_w([2], [3.0], 1) - rrf_qdrant_w([0], [1.0], 1)) > 0.2
    and round(rrf_qdrant_w([2], [3.0], 60), 4) == 0.05
), "твердження Qdrant про рівність ваг справджується лише за k=0 в усталеній формі"
print("✓ зважений RRF: за k=0 3-тя позиція з вагою 3.0 = 1-ша з вагою 1.0 (1.0); "
      "за k=1 рівності немає в жодній формі")

# ── 11. DBSF приводить різні шкали до одного діапазону ──────────────────
assert (
    [round(nb16_v, 4) for nb16_v in dbsf_norm(bm25_raw)] == [0.6851, 0.4531, 0.3618]
    and [round(nb16_v, 4) for nb16_v in dbsf_norm(cosine_raw)] == [0.6133, 0.5781, 0.3086]
    and dbsf_norm([5.0, 5.0, 5.0]) == [0.5, 0.5, 0.5]      # sigma = 0
    and dbsf_norm([5.0]) == [0.5]                          # один документ
    and max(dbsf_norm(bm25_raw)) < 1.0                     # шкала BM25 більше не домінує
), "DBSF мусить покласти обидві гілки в діапазон 0..1"
print("✓ DBSF: BM25 → [0.6851, 0.4531, 0.3618], cosine → [0.6133, 0.5781, 0.3086]; "
      "крайні випадки (усі рівні / один документ) → 0.5")

# ── 12. Переранжування перевпорядковує пул, не додаючи документів ───────
assert (
    order_by_bm25 == [1, 0, 2, 3] and order_by_rerank == [0, 1, 2, 3]
    and round(proximity16(QUERY16, POOL16[0])[2], 2) == 1.33
    and round(proximity16(QUERY16, POOL16[1])[2], 2) == 1.14
    and set(order_by_bm25) == set(order_by_rerank) == set(POOL16)
    and proximity16("невідомий запит", POOL16[0]) == (0.0, 0.0, 0.0)
), "rerank мусить змінити перше місце, не змінюючи складу пулу"
print("✓ переранжування: BM25 [1, 0, 2, 3] → після rerank [0, 1, 2, 3]; "
      "склад пулу той самий; запит без спільних термінів → 0.0")

# ── 13. pgvector: конверсії, усталені значення й метрика відстані ───────
nb16_settings = dict(((nb16_row[0], nb16_row[1]), nb16_row[2]) for nb16_row in settings_table)
assert (
    round(ip_dot(pg_rows["a"], pg_query), 4) == 11.0
    and round(-ip_dot(pg_rows["a"], pg_query), 4) == -11.0
    and round(cos_dist(pg_rows["a"], pg_query), 4) == 0.2143
    and round(1 - cos_dist(pg_rows["a"], pg_query), 4) == 0.7857
    and pg_l2_order == ["c", "a", "b"] and pg_ip_order == ["b", "c", "a"]
    and pg_l2_order != pg_ip_order
    and pg_l2_norm == pg_ip_norm == ["c", "b", "a"]        # після нормалізації порядки збігаються
    and len(settings_table) == 8
    and nb16_settings[("Elasticsearch RRF", "rank_constant")] == "60"
    and nb16_settings[("Qdrant RRF", "k")] == "2"
    and nb16_settings[("rank_bm25", "k1 / b")] == "1.5 / 0.75"
    and nb16_settings[("pgvector HNSW", "hnsw.ef_search")] == "40"
), "метрика відстані мусить відповідати моделі: L2 і IP дають різні порядки без помилки"
print("✓ pgvector: <#> = −IP (−11.0), <=> дає 0.2143; на ненормалізованих векторах L2 і IP "
      "розходяться, після нормалізації збігаються; усталені значення з джерел на місці")

# ── 14. Пайплайн: метадані чанків, гілки, RRF і промпт ──────────────────
nb16_ids = [nb16_entry["id"] for nb16_entry in PIPE_INDEX]
nb16_lex, nb16_sem, nb16_fused, nb16_picked = retrieve16(pipe_query)
assert (
    len(PIPE_INDEX) == 8 and len(PIPE_DOCS) == 3
    and all(nb16_entry["end"] - nb16_entry["start"] == len(nb16_entry["text"])
            for nb16_entry in PIPE_INDEX)
    and nb16_ids[:3] == ["broker.md#0", "broker.md#1", "broker.md#2"]
    and PIPE_INDEX[1]["start"] - PIPE_INDEX[0]["start"] == 70          # крок чанка
    and [PIPE_INDEX[nb16_i]["id"] for nb16_i in nb16_lex] == \
        [PIPE_INDEX[nb16_i]["id"] for nb16_i in nb16_sem] == \
        [PIPE_INDEX[nb16_i]["id"] for nb16_i in nb16_fused]
    and [PIPE_INDEX[nb16_i]["id"] for nb16_i in nb16_picked] == \
        ["broker.md#1", "broker.md#0", "broker.md#2"]
    and nb16_picked == nb16_fused[:3]                        # друга стадія лише перевпорядковує
    and build_prompt16(pipe_query, nb16_picked).count("[") >= 3
    and "Відповідай лише за наведеними джерелами" in build_prompt16(pipe_query, nb16_picked)
    and len(CHECKS16) == 9
), "пайплайн мусить проіндексувати 8 чанків і віддати 3 джерела з посиланнями"
print("✓ пайплайн: 8 чанків із 3 документів, у кожного є start/end; гілки й RRF дають той самий "
      "порядок; у контекст пішло 3 чанки broker.md; чеклист читача — 9 пунктів")

print()
print("Усі перевірки пройдено.")
'''
    ),
    md(
        """
## Підсумок

1. **Chunking — головне джерело проблем.** Розмір чанка впливає на recall сильніше, ніж
   перекриття; а перекриття працює цілими фрагментами, тому часто дорівнює нулю там, де ви
   очікували 200 символів.
2. **Перекриття мусить перекривати відстань між фактами**, які мають відповісти разом. Цю відстань
   вимірюють, а не вгадують.
3. **Лексичний і семантичний пошук провалюються по-різному.** BM25 точний на рідкісних рядках і
   безпорадний на інших словоформах; embeddings — навпаки.
4. **RRF зливає за позиціями, а не за оцінками,** і тим позбавляє від проблеми несумісних шкал.
   Але константа `k` вирішує: `k=60` розтягує, `k=1` стискає.
5. **Не переносьте параметри між системами.** `k=60` і `k=2`, `k1=1.5` і `k1=1.2` — це числа з
   різних реалізацій, і поза своїм контекстом вони не мають сенсу.
6. **Переранжування не піднімає recall.** Воно перевпорядковує те, що вже знайдено, тож пул
   кандидатів беруть із запасом.
7. **Метрика відстані мусить відповідати моделі.** Ненормалізовані вектори з L2 і зі скалярним
   добутком дають різні порядки — і жодної помилки.
8. **Оптимізуйте пошук, а не генерацію,** доки не переконалися, що потрібний чанк узагалі доходить
   до контексту.

**Куди далі:**

- Розділ 17 — оцінювання RAG: метрики RAGAS і як міряти те, що ви щойно зібрали.
- Розділ 9 — prompt caching: як не платити за той самий контекст щоразу.
- Розділ 2 — чому довгий контекст дорожчає і як рахувати його ціну.

## Джерела

- [pgvector README](https://github.com/pgvector/pgvector)
- [PostgreSQL — Controlling Text Search](https://www.postgresql.org/docs/current/textsearch-controls.html)
- [Qdrant — Hybrid and Multi-Stage Queries](https://qdrant.tech/documentation/concepts/hybrid-queries/)
- [Qdrant — Vector Index](https://qdrant.tech/documentation/manage-data/indexing/)
- [ParadeDB — Reciprocal Rank Fusion](https://www.paradedb.com/docs/reference/hybrid/rrf)
- [Elasticsearch — Reciprocal rank fusion](https://www.elastic.co/docs/reference/elasticsearch/rest-apis/reciprocal-rank-fusion)
- [Chroma — Evaluating Chunking Strategies for Retrieval](https://research.trychroma.com/evaluating-chunking)
- [Anthropic — Introducing Contextual Retrieval](https://www.anthropic.com/news/contextual-retrieval)
- [Claude API — Citations](https://platform.claude.com/docs/en/build-with-claude/citations)
- [langchain-text-splitters](https://github.com/langchain-ai/langchain/tree/master/libs/text-splitters)
- [rank_bm25](https://github.com/dorianbrown/rank_bm25)
- [Sentence Transformers — Cross Encoder](https://sbert.net/docs/cross_encoder/usage/usage.html)
- [Cohere — Rerank Best Practices](https://docs.cohere.com/docs/reranking-best-practices)
- Повний перелік джерел — у розділі: `sections/16-rag.md`
"""
    ),
]
