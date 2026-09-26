"""Ноутбук 15 — «Embeddings і векторний пошук».

Розділ довідника: sections/15-embeddings.md

Ноутбук виконується БЕЗ ключів, без GPU і без мережі:
- метрики схожості (cosine, dot, euclidean) реалізовано на стандартній бібліотеці;
- спрощений HNSW-подібний пошук (граф сусідів + список кандидатів ширини ef)
  реалізовано на stdlib і порівнюється з точним перебором за recall;
- арифметика пам'яті під індекс — чисті обчислення за формулами з документації Qdrant;
- демонстрація скалярної та бінарної квантизації з oversampling/rescore;
- клітинка зі справжньою моделлю `sentence-transformers` захищена try/except ImportError
  і завантаженням ваг із мережі — без неї вона просто друкує повідомлення.
"""

from nbkit import SETUP_CELL, VERSION_CELL, code, md

FILENAME = "15-embeddings.ipynb"
TITLE = "15. Embeddings і векторний пошук"

CELLS = [
    md(
        """
# 15. Embeddings і векторний пошук

**Розділ довідника:** [`sections/15-embeddings.md`](../sections/15-embeddings.md)

**Потрібно: нічого обов'язкового (опційно numpy, sentence-transformers).**
Усе нижче працює на стандартній бібліотеці Python, без API-ключів, без GPU і без мережі.
Єдина клітинка, якій потрібні `sentence-transformers` і завантаження ваг, позначена
окремо і сама пропускається, якщо бібліотеки немає.

**Що показує цей ноутбук:**

1. Три метрики схожості й те, що вони дають **три різні ранжування** на тих самих даних.
2. Доведення, що для нормалізованих векторів cosine дорівнює скалярному добутку.
3. Спрощений HNSW: чому `m` і `ef` визначають recall і скільки обчислень це коштує.
4. Скільки пам'яті потребує індекс — за формулами з документації Qdrant.
5. Що дають `oversampling` і `rescore` при бінарній квантизації.
6. Типові пороги оптимізатора Qdrant і момент, коли кожен із них спрацьовує.
"""
    ),
    code(SETUP_CELL),
    md(
        """
## 15.1 Embedding як стиснене подання змісту

Embedding — це вектор фіксованої довжини, у якому близькість векторів означає семантичну
близькість. Нижче — найпростіший ембедер на стандартній бібліотеці: сумка слів із
зважуванням. Він не має жодної семантики, але показує весь контракт: фіксована розмірність,
та сама функція для запиту й документів, нормалізація.

Справжні моделі додають до цього три речі, які перевіряються в підрозділі 15.5:
розмірність (`hidden_size`), режим агрегації (CLS або mean) і префікси протоколу.
"""
    ),
    code(
        '''
# Найпростіший ембедер: сумка слів. Розмірність = розмір словника.
VOCAB = ["скасувати", "підписку", "оформити", "тариф", "оплата", "документ", "повернення"]
DOCS = {
    "d1": "оформити підписку тариф оплата",
    "d2": "скасувати підписку повернення",
    "d3": "документ тариф оплата",
}
QUERY = "як скасувати підписку"

def bag_of_words(text, vocab):
    tokens = text.split()
    return [float(tokens.count(term)) for term in vocab]

VECTORS = {name: bag_of_words(text, VOCAB) for name, text in DOCS.items()}
QUERY_VEC = bag_of_words(QUERY, VOCAB)

print(f"розмірність простору: {len(VOCAB)}")
print(f"словник: {VOCAB}")
for name, vec in VECTORS.items():
    print(f"  {name}: {vec}")
print(f"запит : {QUERY_VEC}")
'''
    ),
    md(
        """
Розмірність тут — 7, і вона фіксована: будь-який текст перетворюється на вектор довжини 7.
У справжніх моделях це 384, 768, 1024 або 3072 — і саме це число визначає пам'ять індексу.
"""
    ),
    md(
        """
## 15.2 Метрики: cosine, dot, euclidean — коли що

Три метрики пов'язані тотожністю `||a - b||^2 = ||a||^2 + ||b||^2 - 2 * (a . b)`. З неї
випливає все: для векторів одиничної норми L2 і скалярний добуток дають однакове
ранжування, а для векторів різної довжини — ні.

Спочатку — реалізація на стандартній бібліотеці. Імена з префіксом `VEC_` використано,
щоб не зіткнутися з іншими змінними ноутбука.
"""
    ),
    code(
        '''
import math

def VEC_DOT(a, b):
    return sum(x * y for x, y in zip(a, b))

def VEC_NORM(a):
    return math.sqrt(VEC_DOT(a, a))

def VEC_COS(a, b):
    na, nb = VEC_NORM(a), VEC_NORM(b)
    return 0.0 if na == 0 or nb == 0 else VEC_DOT(a, b) / (na * nb)

def VEC_L2(a, b):
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))

def VEC_UNIT(a):
    n = VEC_NORM(a)
    return [x / n for x in a]

print("метрики визначено")
'''
    ),
    md(
        """
Тепер — головна демонстрація підрозділу. Запит `q = [1, 0]` і три документи: короткий з
ідеальним напрямком, довгий з майже ідеальним напрямком і середній з гіршим напрямком.
"""
    ),
    code(
        '''
Q_VEC = [1.0, 0.0]
CANDIDATES = {
    "v_small": [1.0, 0.0],
    "v_long":  [6.0, 0.6],
    "v_off":   [0.95, 0.31],
}

print(f"{'назва':<10}{'cosine':>10}{'dot':>10}{'euclid':>10}")
SCORE_ROWS = []
for name, vec in CANDIDATES.items():
    row = (name, VEC_COS(Q_VEC, vec), VEC_DOT(Q_VEC, vec), VEC_L2(Q_VEC, vec))
    SCORE_ROWS.append(row)
    print(f"{row[0]:<10}{row[1]:>10.5f}{row[2]:>10.5f}{row[3]:>10.5f}")

print()
RANKINGS = {
    "cosine": [r[0] for r in sorted(SCORE_ROWS, key=lambda r: -r[1])],
    "dot":    [r[0] for r in sorted(SCORE_ROWS, key=lambda r: -r[2])],
    "euclid": [r[0] for r in sorted(SCORE_ROWS, key=lambda r: r[3])],
}
for metric, order in RANKINGS.items():
    print(f"{metric:>7}: {' > '.join(order)}")

print()
UNIQUE_ORDERS = {tuple(order) for order in RANKINGS.values()}
print(f"різних ранжувань: {len(UNIQUE_ORDERS)} з {len(RANKINGS)}")
assert len(UNIQUE_ORDERS) == 3
'''
    ),
    md(
        """
`v_long` — другий за cosine, перший за dot і **останній** за euclidean. Це і є пастка,
описана в розділі: без нормалізації скалярний добуток віддає перевагу довгим векторам,
бо норма входить у добуток множником.

Тепер доведемо еквівалентність cosine і скалярного добутку для нормалізованих векторів.
Документація `sentence-transformers` формулює практичний висновок: якщо модель завершується
модулем `Normalize`, метрику `dot` обирати краще, ніж `cosine`, бо `cosine` нормалізує
вектори ще раз і працює повільніше.
"""
    ),
    code(
        '''
PAIR_V = [3.0, 4.0]
PAIR_UNIT = VEC_UNIT(PAIR_V)

print("норма v       :", VEC_NORM(PAIR_V))
print("норма unit    :", round(VEC_NORM(PAIR_UNIT), 12))
print("cosine(q,unit):", round(VEC_COS(Q_VEC, PAIR_UNIT), 12))
print("dot(q,unit)   :", round(VEC_DOT(Q_VEC, PAIR_UNIT), 12))
assert abs(VEC_COS(Q_VEC, PAIR_UNIT) - VEC_DOT(Q_VEC, PAIR_UNIT)) < 1e-12
print("assert cosine == dot для одиничного вектора: OK")

# Те саме для всього словникового корпусу: нормалізуємо й перевіряємо ранжування.
NORM_VECTORS = {name: VEC_UNIT(vec) for name, vec in VECTORS.items()}
NORM_Q = VEC_UNIT(QUERY_VEC)
RANK_BY_COS = sorted(NORM_VECTORS, key=lambda n: -VEC_COS(NORM_Q, NORM_VECTORS[n]))
RANK_BY_DOT = sorted(NORM_VECTORS, key=lambda n: -VEC_DOT(NORM_Q, NORM_VECTORS[n]))
print("ранжування нормалізованих векторів за cosine:", RANK_BY_COS)
print("ранжування нормалізованих векторів за dot   :", RANK_BY_DOT)
assert RANK_BY_COS == RANK_BY_DOT
'''
    ),
    md(
        """
Крім перевірки на одному векторі, тут видно, що й **порядок** документів однаковий. Два
висновки для практики:

- `Dot` у Qdrant має сенс, коли вектори гарантовано одиничні — результат той самий, а
  арифметики менше.
- `Cosine` у Qdrant нормалізує вектори автоматично під час завантаження, тому метрику
  можна обирати за карткою моделі, не додаючи нормалізацію вручну. У pgvector навпаки:
  нормалізацію робить користувач, інакше `vector_ip_ops` дасть зсув на користь довгих векторів.
"""
    ),
    md(
        """
## 15.3 HNSW: як працює приблизний пошук і де втрачається точність

HNSW — багатошаровий граф близькості. Тут реалізовано спрощену версію: граф сусідів, де
кожен вузол з'єднаний з `m` найближчими з уже вставлених (справжній HNSW використовує
евристику відбору сусідів, але механіка пошуку й характер кривої recall ті самі), плюс
пошук зі списком кандидатів ширини `ef`.

Порівнюємо з точним перебором за `recall@10`. Колонка «оглянуто» — приблизна кількість
обчислень відстані, тобто ціна точності.
"""
    ),
    code(
        '''
import heapq
import random

def HNSW_SCORE(vec_a, vec_b):
    return VEC_COS(vec_a, vec_b)

def HNSW_DATA(n, d, seed):
    rng = random.Random(seed)
    rows = []
    for _ in range(n):
        vec = [rng.gauss(0.0, 1.0) for _ in range(d)]
        rows.append(VEC_UNIT(vec))
    return rows

def HNSW_BUILD(rows, m):
    graph = [[] for _ in rows]
    for i in range(1, len(rows)):
        near = sorted(range(i), key=lambda j: -HNSW_SCORE(rows[i], rows[j]))[:m]
        for j in near:
            graph[i].append(j)
            graph[j].append(i)
    return graph

def HNSW_BEAM(rows, graph, query, ef, entry=0, max_steps=2000):
    start = HNSW_SCORE(query, rows[entry])
    visited = {entry}
    candidates = [(-start, entry)]
    results = [(start, entry)]
    steps = 0
    while candidates and steps < max_steps:
        neg_best, cur = heapq.heappop(candidates)
        if -neg_best < results[0][0] and len(results) >= ef:
            break
        steps += 1
        for nb in graph[cur]:
            if nb in visited:
                continue
            visited.add(nb)
            score = HNSW_SCORE(query, rows[nb])
            if len(results) < ef or score > results[0][0]:
                heapq.heappush(candidates, (-score, nb))
                heapq.heappush(results, (score, nb))
                if len(results) > ef:
                    heapq.heappop(results)
    return [idx for _, idx in sorted(results, key=lambda t: -t[0])], steps

def HNSW_EXACT(rows, query, k):
    return sorted(range(len(rows)), key=lambda j: -HNSW_SCORE(query, rows[j]))[:k]

def HNSW_RECALL(approx, truth, k):
    return len(set(approx[:k]) & set(truth[:k])) / k

N_DATA, D_DIM, K_TOP = 800, 32, 10
HNSW_ROWS = HNSW_DATA(N_DATA, D_DIM, seed=15)
RNG_Q = random.Random(99)
HNSW_QUERIES = []
for _ in range(30):
    HNSW_QUERIES.append(VEC_UNIT([RNG_Q.gauss(0.0, 1.0) for _ in range(D_DIM)]))
HNSW_TRUTH = [HNSW_EXACT(HNSW_ROWS, q, K_TOP) for q in HNSW_QUERIES]

print(f"дата: {N_DATA} векторів, розмірність {D_DIM}, top-{K_TOP}, "
      f"{len(HNSW_QUERIES)} запитів")
print()
print(f"{'m':>3}{'ef':>5}{'recall@10':>12}{'кроків':>10}{'оглянуто':>11}")
HNSW_RESULTS = []
for m in (2, 4, 8, 16):
    graph = HNSW_BUILD(HNSW_ROWS, m)
    avg_deg = sum(len(g) for g in graph) / len(graph)
    for ef in (10, 20, 50):
        recs, steps = [], []
        for query, truth in zip(HNSW_QUERIES, HNSW_TRUTH):
            got, st = HNSW_BEAM(HNSW_ROWS, graph, query, ef)
            recs.append(HNSW_RECALL(got, truth, K_TOP))
            steps.append(st)
        recall = sum(recs) / len(recs)
        n_steps = sum(steps) / len(steps)
        HNSW_RESULTS.append((m, ef, recall, n_steps, avg_deg * n_steps))
        print(f"{m:>3}{ef:>5}{recall:>12.3f}{n_steps:>10.1f}{avg_deg * n_steps:>11.1f}")
'''
    ),
    md(
        """
Три висновки з таблиці:

1. **`ef` керує recall сильніше за `m` на малих значеннях.** При `m=2` перехід `ef` з 10 на 50
   піднімає recall з 0.277 до 0.697.
2. **Ціна зростає приблизно лінійно.** Зростання recall з 0.890 до 0.993 коштує збільшення
   огляду з 378 до 1613 векторів — учетверо.
3. **`m=2` не рятує навіть великий `ef`.** При `ef=50` граф із двома ребрами на вузол усе ще
   дає 0.697.

Тепер — граничні випадки. Жадібний спуск без списку кандидатів і граф-ланцюжок (`m=1`).
"""
    ),
    code(
        '''
def HNSW_GREEDY(rows, graph, query, entry=0, max_hops=200):
    cur = entry
    cur_score = HNSW_SCORE(query, rows[cur])
    hops = 0
    while hops < max_hops:
        best, best_score = None, cur_score
        for nb in graph[cur]:
            score = HNSW_SCORE(query, rows[nb])
            if score > best_score:
                best, best_score = nb, score
        if best is None:
            break
        cur, cur_score = best, best_score
        hops += 1
    return cur, cur_score, hops

GRAPH_M16 = HNSW_BUILD(HNSW_ROWS, 16)
GREEDY_RECALL, GREEDY_HOPS, GREEDY_STUCK = [], [], 0
for query, truth in zip(HNSW_QUERIES, HNSW_TRUTH):
    idx, _score, hops = HNSW_GREEDY(HNSW_ROWS, GRAPH_M16, query)
    GREEDY_RECALL.append(HNSW_RECALL([idx], truth, 1))
    GREEDY_HOPS.append(hops)
    if hops == 0:
        GREEDY_STUCK += 1
print(f"жадібний спуск (m=16): recall@1 = {sum(GREEDY_RECALL) / len(GREEDY_RECALL):.3f}, "
      f"середня кількість кроків = {sum(GREEDY_HOPS) / len(GREEDY_HOPS):.1f}, "
      f"застряг одразу на {GREEDY_STUCK}/{len(HNSW_QUERIES)}")

CHAIN_GRAPH = [[] for _ in range(N_DATA)]
for i in range(N_DATA - 1):
    CHAIN_GRAPH[i].append(i + 1)
    CHAIN_GRAPH[i + 1].append(i)
CHAIN_RECALL = []
for query, truth in zip(HNSW_QUERIES, HNSW_TRUTH):
    idx, _score, _hops = HNSW_GREEDY(HNSW_ROWS, CHAIN_GRAPH, query)
    CHAIN_RECALL.append(HNSW_RECALL([idx], truth, 1))
print(f"той самий спуск на графі-ланцюжку (m=1): "
      f"recall@1 = {sum(CHAIN_RECALL) / len(CHAIN_RECALL):.3f}")

# Повний перебір як еталон точності: recall завжди 1.0, але ціна інша.
FULL_COST = N_DATA * len(HNSW_QUERIES)
GRAPH_COST = sum(r[4] for r in HNSW_RESULTS)
print()
print(f"обчислень відстані за {len(HNSW_QUERIES)} запитів:")
print(f"  повний перебір : {FULL_COST:>10.0f}")
print(f"  HNSW-подібний  : {sum(HNSW_RESULTS[i][4] for i in (0, 4, 8, 11)):>10.0f}"
      f"  (лише 4 конфігурації з 12)")
'''
    ),
    md(
        """
**Головний результат:** жадібний спуск без списку кандидатів знаходить правильний top-1
лише в половині випадків, хоча граф якісний (`m=16`). На графі-ланцюжку recall падає майже
до нуля. Саме тому `m` не можна залишати в нулі після масового завантаження, а `ef` не можна
ставити меншим за `limit`.

Ще одна пастка, якої тут не видно, але вона є в pgvector: фільтр застосовується **після**
сканування індексу. Якщо умова відбирає 10% рядків, то при `hnsw.ef_search = 40` у
середньому збігатиметься лише 4 рядки. Ліки — `hnsw.iterative_scan`.
"""
    ),
    md(
        """
## 15.4 Квантування векторів і пам'ять

Сирі вектори — це практично вся пам'ять індексу. Спочатку порахуємо точну структуру
витрат для 20 мільйонів точок по 1024 виміри за формулами з документації Qdrant:
щільні вектори `base × dims × bytes_per_dim`, граф HNSW `base × m × 2 × 4 × 1.2`,
ID tracker — `~52` байти на точку.

Окремо зверніть увагу на рядок «scalar int8, оригінали в RAM»: квантизація **додає** пам'ять,
бо квантовані вектори зберігаються поряд з оригінальними, а не замість них.
"""
    ),
    code(
        '''
def MEM_HUMAN(nbytes):
    value = float(nbytes)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if abs(value) < 1024 or unit == "TiB":
            return f"{value:,.1f} {unit}"
        value /= 1024

MEM_POINTS, MEM_DIM, MEM_M = 20_000_000, 1024, 16
MEM_HNSW = MEM_POINTS * MEM_M * 2 * 4 * 1.2
MEM_IDTR = MEM_POINTS * 52
MEM_DENSE_FP32 = MEM_POINTS * MEM_DIM * 4

QUANT_MODES = [
    ("scalar int8, оригінали в RAM", 1, True),
    ("scalar int8, оригінали на диску", 1, False),
    ("turbo 4-bit, оригінали на диску", 0.5, False),
    ("binary 2-bit, оригінали на диску", 0.25, False),
    ("binary 1-bit, оригінали на диску", 0.125, False),
    ("product x64, оригінали на диску", 0.0625, False),
]
print(f"20 000 000 точок x 1024 виміри, m={MEM_M}")
print(f"{'режим':<36}{'RAM: вект.':>13}{'RAM: квант':>13}{'RAM: HNSW':>12}"
      f"{'RAM разом':>13}{'скорочення':>12}")
MEM_ROWS = []
for label, quant_bytes, originals_in_ram in QUANT_MODES:
    ram_dense = MEM_DENSE_FP32 if originals_in_ram else 0
    ram_quant = MEM_POINTS * MEM_DIM * quant_bytes
    total = ram_dense + ram_quant + MEM_HNSW + MEM_IDTR
    full = MEM_DENSE_FP32 + MEM_HNSW + MEM_IDTR
    MEM_ROWS.append((label, ram_dense, ram_quant, MEM_HNSW, total, full / total))
    print(f"{label:<36}{MEM_HUMAN(ram_dense):>13}{MEM_HUMAN(ram_quant):>13}"
          f"{MEM_HUMAN(MEM_HNSW):>12}{MEM_HUMAN(total):>13}{full / total:>11.2f}x")

print()
print("Частки у fp32-конфігурації:")
PARTS = (("вектори fp32", MEM_DENSE_FP32),
         ("граф HNSW", MEM_HNSW),
         ("ID tracker", MEM_IDTR))
MEM_FULL_TOTAL = MEM_DENSE_FP32 + MEM_HNSW + MEM_IDTR
for part_name, part_bytes in PARTS:
    print(f"  {part_name:<14} {MEM_HUMAN(part_bytes):>12}"
          f"  ({100 * part_bytes / MEM_FULL_TOTAL:.1f}%)")
assert MEM_ROWS[0][4] > MEM_ROWS[1][4], "квантизація без перенесення на диск має бути дорожчою"
'''
    ),
    md(
        """
Тепер — формула, яку Qdrant використовує у власному бенчмарку:
`memory_size = 1.5 * number_of_vectors * vector_dimension * 4 bytes`.
Множник 1.5 — це груба оцінка накладних витрат графа HNSW і службових структур.
"""
    ),
    code(
        '''
print("Формула Qdrant-бенчмарку: memory_size = 1.5 * N * D * 4")
for n_pts, dim in ((100_000, 1536), (1_000_000, 1536), (1_000_000, 1024)):
    bench = 1.5 * n_pts * dim * 4
    raw = n_pts * dim * 4
    print(f"  N={n_pts:>9,}  D={dim:>5}  ->  {MEM_HUMAN(bench):>12}"
          f"   (сирі вектори {MEM_HUMAN(raw):>11})")

print()
print("Те саме з 1-бітною бінаризацією (N * D / 8 байт):")
for n_pts, dim in ((100_000, 1536), (1_000_000, 1536)):
    print(f"  N={n_pts:>9,}  D={dim:>5}  ->  {MEM_HUMAN(n_pts * dim / 8):>12}")

print()
print("Байтів на один вектор, без накладних витрат індексу:")
for dim in (384, 768, 1024, 1536, 3072):
    print(f"  D={dim:>5}: fp32 {dim * 4:>6}  fp16 {dim * 2:>6}  uint8 {dim:>6}  "
          f"turbo4 {dim * 0.5:>7.0f}  2bit {dim * 0.25:>7.0f}  1bit {dim * 0.125:>7.0f}")
'''
    ),
    md(
        """
Стиснення в 32 рази звучить як безпрограшний варіант, але воно не безкоштовне. Перевіримо
дві речі: скалярну квантизацію (float32 → int8 із квантілем) і бінарну квантизацію з
`oversampling` та `rescore`.

Бінарне подання тут упаковано в ціле число, тому Hamming-відстань — це `popcount` від XOR.
Вектори центровано відніманням середнього, бо бінарна квантизація вимагає центрованого
розподілу координат.
"""
    ),
    code(
        '''
import random as qrandom

def QUANT_TO_BITS(vec):
    packed = 0
    for x in vec:
        packed = (packed << 1) | (1 if x > 0 else 0)
    return packed

def QUANT_HAMMING(packed_a, packed_b):
    return bin(packed_a ^ packed_b).count("1")

def QUANT_ENCODE(vec, alpha, offset):
    return [max(0, min(255, round((x - offset) / alpha))) for x in vec]

def QUANT_DECODE(codes, alpha, offset):
    return [alpha * code + offset for code in codes]

def QUANT_RANGE(rows, quantile=0.99):
    flat = sorted(x for vec in rows for x in vec)
    lo_idx = int((1 - quantile) / 2 * len(flat))
    hi_idx = min(len(flat) - 1, int((1 + quantile) / 2 * len(flat)))
    return flat[lo_idx], flat[hi_idx]

QN, QD, QK = 2000, 128, 10
qrng = qrandom.Random(7)
QUANT_ROWS = [VEC_UNIT([qrng.gauss(0, 1) for _ in range(QD)]) for _ in range(QN)]
QMEAN = [sum(v[i] for v in QUANT_ROWS) / QN for i in range(QD)]
QUANT_ROWS = [VEC_UNIT([v[i] - QMEAN[i] for i in range(QD)]) for v in QUANT_ROWS]
QUANT_BITS = [QUANT_TO_BITS(v) for v in QUANT_ROWS]

QUANT_QUERIES = []
for _ in range(30):
    qv = VEC_UNIT([qrng.gauss(0, 1) for _ in range(QD)])
    QUANT_QUERIES.append((qv, QUANT_TO_BITS(VEC_UNIT([qv[i] - QMEAN[i] for i in range(QD)]))))

def QUANT_EXACT(query, k):
    return sorted(range(QN), key=lambda j: -VEC_COS(query, QUANT_ROWS[j]))[:k]

print(f"{QN} векторів, D={QD}, top-{QK}, {len(QUANT_QUERIES)} запитів")
print(f"{'oversampling':>13}{'recall@10 без rescore':>24}{'recall@10 з rescore':>22}")
QUANT_TABLE = []
for oversampling in (1.0, 2.0, 4.0, 8.0, 16.0):
    plain, rescored = [], []
    for query, packed_query in QUANT_QUERIES:
        truth = QUANT_EXACT(query, QK)
        pre = max(QK, int(QK * oversampling))
        cand = sorted(range(QN), key=lambda j: QUANT_HAMMING(packed_query, QUANT_BITS[j]))[:pre]
        plain.append(len(set(cand[:QK]) & set(truth)) / QK)
        reranked = sorted(cand, key=lambda j: -VEC_COS(query, QUANT_ROWS[j]))[:QK]
        rescored.append(len(set(reranked) & set(truth)) / QK)
    plain_avg = sum(plain) / len(plain)
    rescored_avg = sum(rescored) / len(rescored)
    QUANT_TABLE.append((oversampling, plain_avg, rescored_avg))
    print(f"{oversampling:>13.1f}{plain_avg:>24.3f}{rescored_avg:>22.3f}")

print()
assert abs(QUANT_TABLE[0][1] - QUANT_TABLE[-1][1]) < 1e-12, \\
    "без rescore recall не залежить від oversampling"
print("підтверджено: без rescore recall однаковий для всіх oversampling")

print()
print("Скалярна квантизація float32 -> uint8. Вектори відновлюються у float перед")
print("обчисленням cosine, бо доданий offset зсуває всі координати однаково:")
print(f"{'квантіль':>10}{'межі діапазону':>26}{'alpha':>11}{'recall@10':>11}"
      f"{'сер. |d cosine|':>18}")
SQ_TABLE = []
for quantile in (0.95, 0.99, 1.0):
    lo, hi = QUANT_RANGE(QUANT_ROWS, quantile)
    alpha = (hi - lo) / 255
    sq_codes = [QUANT_ENCODE(vec, alpha, lo) for vec in QUANT_ROWS]
    sq_rows = [QUANT_DECODE(codes, alpha, lo) for codes in sq_codes]
    recall_list, error_list = [], []
    for query, _packed in QUANT_QUERIES:
        truth = QUANT_EXACT(query, QK)
        approx = sorted(range(QN), key=lambda j: -VEC_COS(query, sq_rows[j]))[:QK]
        recall_list.append(len(set(approx) & set(truth)) / QK)
        error_list.append(abs(VEC_COS(query, sq_rows[truth[0]])
                              - VEC_COS(query, QUANT_ROWS[truth[0]])))
    sq_recall = sum(recall_list) / len(recall_list)
    sq_error = sum(error_list) / len(error_list)
    SQ_TABLE.append((quantile, lo, hi, alpha, sq_recall, sq_error))
    print(f"{quantile:>10.2f}{f'[{lo:.4f}, {hi:.4f}]':>26}{alpha:>11.6f}"
          f"{sq_recall:>11.3f}{sq_error:>18.6f}")

print()
print(f"байтів на вектор: fp32 {QD * 4}, uint8 {QD} (у 4 рази менше)")
print()
print("Наївний варіант: cosine прямо на int8-кодах, без повернення у float.")
lo, hi = QUANT_RANGE(QUANT_ROWS, 0.99)
alpha = (hi - lo) / 255
SQ_NAIVE = [[float(code) for code in QUANT_ENCODE(vec, alpha, lo)] for vec in QUANT_ROWS]
naive_recall = []
for query, _packed in QUANT_QUERIES:
    truth = QUANT_EXACT(query, QK)
    approx = sorted(range(QN), key=lambda j: -VEC_COS(query, SQ_NAIVE[j]))[:QK]
    naive_recall.append(len(set(approx) & set(truth)) / QK)
print(f"  recall@10 = {sum(naive_recall) / len(naive_recall):.3f}")
print("  Усі коди зсунуто на offset у кожній координаті, тому напрямок вектора змінюється.")
print("  Це і є та помилка, яку декодування прибирає.")
'''
    ),
    md(
        """
**Найважливіший рядок тут** — колонка «без rescore»: вона однакова для всіх `oversampling`.
Без перерахунку за оригінальними векторами збільшення oversampling нічого не змінює, бо
перші `limit` результатів за Hamming-відстанню завжди ті самі. Rescore перетворює
oversampling на справжній важіль: 0.157 при 1x проти 0.657 при 16x.

Застереження про числа: вектори тут — незалежні гаусові, без кластерної структури, яку мають
справжні ембединги. Абсолютні значення не відтворюють бенчмарки Qdrant (там для ada-002 на
1536 вимірах заявлено 0.98 recall@100 при 4x oversampling) і не переносяться на реальні дані.
Документація прямо радить тестувати на своїх даних перед вибором методу.
"""
    ),
    md(
        """
## 15.5 Вибір embedding-моделі й розмірність

Розмірність моделі множиться на кількість фрагментів — і саме тому вибір моделі є рішенням
про інфраструктуру, а не лише про якість. Порахуємо для корпусу з 2 мільйонів фрагментів.

Розмірності й ліцензії нижче взяті з `config.json` і карток моделей на Hugging Face,
а не з пам'яті: `bge-small-en-v1.5` — 384, `gte-multilingual-base` і
`nomic-embed-text-v1.5` — 768, `bge-m3` — 1024, `text-embedding-3-small` — 1536,
`text-embedding-3-large` — 3072.
"""
    ),
    code(
        '''
CORPUS_CHUNKS = 2_000_000
MODEL_CANDIDATES = [
    ("bge-small-en-v1.5", 384, 4, "MIT, лише en"),
    ("gte-multilingual-base", 768, 4, "Apache-2.0, 70+ мов"),
    ("nomic-embed-text-v1.5", 768, 4, "Apache-2.0, лише en"),
    ("nomic-embed-text-v1.5 (MRL 256)", 256, 4, "обрізання вектора"),
    ("bge-m3", 1024, 4, "MIT, багатомовна"),
    ("text-embedding-3-small", 1536, 4, "API, 62.3% MTEB"),
    ("text-embedding-3-large", 3072, 4, "API, 64.6% MTEB"),
    ("bge-m3 + 2-бітне квантування", 1024, 0.25, "квантизація"),
]
print(f"корпус: {CORPUS_CHUNKS:,} фрагментів".replace(",", " "))
print(f"{'модель':<34}{'D':>6}{'Б/вектор':>10}{'сирі':>12}{'+HNSW m=16':>13}{'разом':>12}")
MODEL_ROWS = []
for model_name, dim, bytes_per_dim, note in MODEL_CANDIDATES:
    dense = CORPUS_CHUNKS * dim * bytes_per_dim
    hnsw = CORPUS_CHUNKS * 16 * 2 * 4 * 1.2
    MODEL_ROWS.append((model_name, dim, dense, hnsw, dense + hnsw, note))
    print(f"{model_name:<34}{dim:>6}{dim * bytes_per_dim:>10.0f}"
          f"{MEM_HUMAN(dense):>12}{MEM_HUMAN(hnsw):>13}{MEM_HUMAN(dense + hnsw):>12}")

print()
BASE_TOTAL = MODEL_ROWS[6][4]
SMALL_TOTAL = MODEL_ROWS[0][4]
QUANT_TOTAL = MODEL_ROWS[7][4]
print(f"text-embedding-3-large проти bge-small: у {BASE_TOTAL / SMALL_TOTAL:.1f} раза більше")
print(f"квантування bge-m3 проти fp32 bge-m3  : у "
      f"{MODEL_ROWS[4][4] / QUANT_TOTAL:.1f} раза менше")
print(f"квантування зберігає розмірність {MODEL_ROWS[7][1]}, а не зменшує її")

print()
print("MTEB за різних розмірностей однієї моделі (nomic-embed-text-v1.5, з картки моделі):")
MRL_TABLE = [(768, 62.28), (512, 61.96), (256, 61.04), (128, 59.34), (64, 56.10)]
print(f"{'D':>6}{'MTEB':>8}{'втрата від 768':>17}")
for dim, score in MRL_TABLE:
    print(f"{dim:>6}{score:>8.2f}{MRL_TABLE[0][1] - score:>17.2f}")
'''
    ),
    md(
        """
Обрізання з 768 до 256 — це втричі менше пам'яті за втрати 1.24 бала MTEB. Перехід з 128 до
64 коштує вже 3.24 бала. Крива має коліно, і саме на ньому варто зупинятися.

І окремо: **квантування обганяє вибір моделі за ефектом на пам'ять**. Заміна
`text-embedding-3-large` на `bge-small` економить 7.5 раза, а 2-бітне квантування `bge-m3` —
утричі більше, ніж у 10 разів, зберігаючи 1024-вимірне подання.

Тепер — протокол. Деякі моделі вимагають префіксів у тексті, і без них якість пошуку падає,
а вектори залишаються цілком «нормальними» на вигляд. Це той клас помилок, який ніколи не
проявляється як виняток, тому протокол варто робити явною перевіркою в коді.
"""
    ),
    code(
        '''
PROTOCOL = {
    "intfloat/multilingual-e5-large": {"query": "query: ", "document": "passage: "},
    "nomic-ai/nomic-embed-text-v1.5": {"query": "search_query: ", "document": "search_document: "},
    "BAAI/bge-m3": {"query": "", "document": ""},
}

def PROTOCOL_PREPARE(model_id, text, role):
    if model_id not in PROTOCOL:
        raise KeyError(f"модель {model_id} відсутня в таблиці протоколів")
    if role not in PROTOCOL[model_id]:
        raise ValueError(f"невідома роль {role!r}; очікується 'query' або 'document'")
    return PROTOCOL[model_id][role] + text

PROTOCOL_AUDIT = []
for model_id in PROTOCOL:
    query_text = PROTOCOL_PREPARE(model_id, "як скасувати підписку", "query")
    doc_text = PROTOCOL_PREPARE(model_id, "Скасування підписки", "document")
    PROTOCOL_AUDIT.append((model_id, query_text, doc_text))
    print(f"{model_id:<34} query={query_text!r}")
    print(f"{'':<34} doc  ={doc_text!r}")

assert PROTOCOL_PREPARE("BAAI/bge-m3", "текст", "query") == "текст"
print()
print("bge-m3 не потребує префіксів: assert пройшов")

# Аудит колекції: виявити документи, підготовлені не тим протоколом.
INDEX_MODEL = "intfloat/multilingual-e5-large"
INDEX_AUDIT = [
    ("d1", "passage: оформити підписку тариф оплата"),
    ("d2", "скасувати підписку повернення"),
    ("d3", "passage: документ тариф оплата"),
]
INDEX_PREFIX = PROTOCOL[INDEX_MODEL]["document"]
STALE = [list(row) for row in INDEX_AUDIT if not row[1].startswith(INDEX_PREFIX)]
print()
print(f"модель індексу: {INDEX_MODEL}, потрібен префікс {INDEX_PREFIX!r}")
print(f"документів із правильним префіксом: "
      f"{len(INDEX_AUDIT) - len(STALE)}/{len(INDEX_AUDIT)}")
for doc_id, text in STALE:
    print(f"  прострочений {doc_id}: {text!r}")
'''
    ),
    md(
        """
Клітинка нижче — єдина в цьому ноутбуці, якій потрібні `sentence-transformers` і завантаження
ваг із мережі. Вона **не обов'язкова**: без бібліотеки або без мережі вона друкує повідомлення
й пропускається. Параметри, які вона перевіряє (розмірність і `max_seq_length`), узяті з
`config.json` і `sentence_bert_config.json` моделі — тут вони звіряються з живою моделлю.
"""
    ),
    code(
        '''
try:
    from sentence_transformers import SentenceTransformer
except ImportError:
    SentenceTransformer = None
    print("sentence-transformers не встановлено — клітинку пропущено")

if SentenceTransformer is not None:
    try:
        ST_MODEL = SentenceTransformer(
            "sentence-transformers/paraphrase-multilingual-mpnet-base-v2"
        )
        print("розмірність моделі :", ST_MODEL.get_sentence_embedding_dimension())
        print("max_seq_length     :", ST_MODEL.max_seq_length)
        ST_VECS = ST_MODEL.encode(
            ["Скасування підписки", "Як скасувати підписку"], normalize_embeddings=True
        )
        print("форма              :", ST_VECS.shape)
        print("cosine сусідніх речень:", round(float(ST_VECS[0] @ ST_VECS[1]), 4))
    except Exception as exc:
        print(f"модель недоступна (немає мережі або ваг): {type(exc).__name__}: {exc}")
'''
    ),
    md(
        """
## 15.6 Вузьке місце: оновлення індексу

Побудова індексу зазвичай проходить добре, а ламається все на змінах. У Qdrant цим керує
оптимізатор, і кожен його компонент прокидається на своєму порозі. Нижче — модель життєвого
циклу сегмента за **типовими** значеннями з конфігурації колекції: `deleted_threshold = 0.2`,
`vacuum_min_vector_number = 1000`, `indexing_threshold = 20000` KiB,
`full_scan_threshold = 10000` KiB.
"""
    ),
    code(
        '''
DELETED_THRESHOLD = 0.2
VACUUM_MIN_VECTORS = 1000
INDEXING_THRESHOLD_KB = 20000
FULL_SCAN_THRESHOLD_KB = 10000
BYTES_PER_KB = 1024

def LIFECYCLE_PLAN(n_points, dim, bytes_per_dim=4, deleted_fraction=0.0):
    used = n_points * dim * bytes_per_dim
    return {
        "точок": n_points,
        "розмір": f"{used / 1024 / 1024:.2f} MiB",
        "vacuum": deleted_fraction >= DELETED_THRESHOLD and n_points >= VACUUM_MIN_VECTORS,
        "будувати HNSW": used >= INDEXING_THRESHOLD_KB * BYTES_PER_KB,
        "повне сканування": used < FULL_SCAN_THRESHOLD_KB * BYTES_PER_KB,
    }

print("Сегмент 1024-вимірних векторів fp32 (один вектор = 4 KiB):")
print(f"{'точок':>8}{'розмір':>12}{'vacuum':>9}{'HNSW':>8}{'full scan':>11}")
LIFECYCLE_ROWS = []
for n_points in (100, 1000, 2500, 5000, 10001, 20001, 50000):
    plan = LIFECYCLE_PLAN(n_points, 1024)
    LIFECYCLE_ROWS.append(list(plan.values()))
    print(f"{plan['точок']:>8}{plan['розмір']:>12}{str(plan['vacuum']):>9}"
          f"{str(plan['будувати HNSW']):>8}{str(plan['повне сканування']):>11}")

print()
print("Вплив частки видалених записів (20 000 точок, 1024 виміри):")
print(f"{'видалено':>10}{'vacuum стартує':>17}")
for fraction in (0.0, 0.1, 0.19, 0.2, 0.35, 0.5):
    plan = LIFECYCLE_PLAN(20000, 1024, deleted_fraction=fraction)
    print(f"{fraction:>9.0%}{str(plan['vacuum']):>17}")

print()
print(f"Скільки точок уміщується в full_scan_threshold ({FULL_SCAN_THRESHOLD_KB} KiB):")
for dim, bytes_per_dim, label in ((384, 4, "fp32"), (768, 4, "fp32"), (1024, 4, "fp32"),
                                  (1536, 4, "fp32"), (3072, 4, "fp32"), (1024, 0.25, "2-bit")):
    per_vector = dim * bytes_per_dim / BYTES_PER_KB
    print(f"  D={dim:>5} {label:<6} {per_vector:>6.2f} KiB/вектор -> "
          f"{int(FULL_SCAN_THRESHOLD_KB / per_vector):>7} векторів")
'''
    ),
    md(
        """
Три висновки:

- **Поріг повного сканування залежить від розмірності, а не від кількості точок.** Для
  384-вимірної моделі повне сканування вмикається до 6666 векторів, для 3072-вимірної — лише
  до 833. Перехід на велику модель **знижує** межу, за якою індекс узагалі починає
  використовуватися.
- **Vacuum прокидається рівно на 20%.** Це частка, а не кількість — тому масові оновлення
  («видалити + вставити» замість оновлення) накопичують позначені записи задовго до
  спрацьовування оптимізатора.
- **Два пороги рахуються з різними знаками нерівності.** На 2500 точках (розмір рівно
  10 000 KiB) повне сканування вже вимкнене, а граф HNSW ще не будується.

Окремо зверніть увагу, чого в цій таблиці немає: **перебудови графа під нові payload-індекси**.
Додаткові ребра для filterable HNSW генеруються тільки після створення payload-індексу, тому
індекси треба створювати до завантаження даних. Якщо це вже пропущено, документація Qdrant
дає рецепт: збільшити `ef_construct` на 1, щоб змусити оптимізатор переіндексувати всі
сегменти, і **не повертати значення назад**.
"""
    ),
    md(
        """
## Підсумок

1. **Метрика — це частина визначення схожості.** На тих самих трьох векторах cosine, dot і
   euclidean дали три різні ранжування. Для нормалізованих векторів cosine дорівнює
   скалярному добутку — це доведено `assert`-ом.
2. **Qdrant нормалізує вектори для `Cosine` автоматично; pgvector — ні.** Тому `Dot` без
   нормалізації в pgvector дає систематичний зсув на користь довгих векторів.
3. **`ef` керує recall сильніше за `m`, і його можна міняти на кожен запит.** Але `m=2` не
   рятує навіть `ef=50`: ребер фізично не вистачає. `m = 0` — це тимчасовий режим
   завантаження, а не налаштування.
4. **Жадібний спуск без списку кандидатів знаходить top-1 лише в половині випадків**, хоча
   граф якісний. Список кандидатів ширини `ef` — не оптимізація, а необхідна умова.
5. **Квантизація без перенесення оригіналів на диск збільшує пам'ять.** Ефект 3.5x–16x
   виникає лише тоді, коли оригінали винесено на диск; квантовані вектори зберігаються
   поряд з ними.
6. **`oversampling` без `rescore` не працює.** Це підтверджено `assert`-ом: recall без
   перерахунку однаковий для всіх значень oversampling.
7. **Квантування обганяє вибір моделі за ефектом на пам'ять.** 2-бітне квантування `bge-m3`
   дає більший виграш, ніж заміна `text-embedding-3-large` на `bge-small`.
8. **Розмірність визначає два пороги одночасно** — скільки пам'яті займає індекс і за якої
   кількості точок він узагалі починає використовуватися замість повного сканування.
9. **Протокол префіксів — це контракт, а не деталь.** Він не проявляється як помилка, тому
   його треба робити явною перевіркою в коді.

**Куди далі:**

- Розділ 6 — як обрати модель під задачу загалом.
- Розділ 20 — квантизація ваг LLM: інша задача, схожа термінологія.
- Розділ 24 — як вимірювати recall і якість пошуку в CI.
- Розділ 16 — гібридний пошук і злиття ранжувань.
"""
    ),
    md(
        """
## Джерела

- [Qdrant — Collections](https://qdrant.tech/documentation/concepts/collections/) — метрики відстані, типові параметри
- [Qdrant — Indexing](https://qdrant.tech/documentation/concepts/indexing/) — HNSW, `m`, `ef_construct`, `ef`, filterable HNSW, ACORN
- [Qdrant — Quantization](https://qdrant.tech/documentation/guides/quantization/) — TurboQuant, scalar, binary, product
- [Qdrant — Optimizer](https://qdrant.tech/documentation/concepts/optimizer/) — vacuum, merge, indexing
- [Qdrant — Scalar Quantization](https://qdrant.tech/articles/scalar-quantization/) — формула `1.5 * N * D * 4`
- [Qdrant — Binary Quantization](https://qdrant.tech/articles/binary-quantization/) — oversampling, `m = 0`
- [Qdrant — Product Quantization](https://qdrant.tech/articles/product-quantization/) — k-means, K = 256
- [Qdrant — Sizing skill](https://skills.qdrant.tech/qdrant-sizing/SKILL.md) — формули пам'яті
- [pgvector — README](https://github.com/pgvector/pgvector) — оператори, HNSW, IVFFlat, iterative scan
- [HNSW — оригінальна стаття](https://arxiv.org/abs/1603.09320) — Malkov, Yashunin
- [sentence-transformers — Semantic Textual Similarity](https://www.sbert.net/docs/sentence_transformer/usage/semantic_textual_similarity.html) — `dot` проти `cosine`
- [BAAI/bge-m3](https://huggingface.co/BAAI/bge-m3), [intfloat/multilingual-e5-large](https://huggingface.co/intfloat/multilingual-e5-large), [nomic-ai/nomic-embed-text-v1.5](https://huggingface.co/nomic-ai/nomic-embed-text-v1.5), [Alibaba-NLP/gte-multilingual-base](https://huggingface.co/Alibaba-NLP/gte-multilingual-base)
- [MTEB](https://huggingface.co/blog/mteb) — 56 наборів даних, 8 задач
- [OpenAI — Embeddings](https://platform.openai.com/docs/guides/embeddings) — розмірності, `dimensions`, нормалізація

Локальні копії джерел: `research/06b/qdrant_*.md`, `research/06b/qdrant_*.txt`,
`research/06b/pgvector_readme.txt`, `research/06b/hf_*.txt`,
`research/06b/hfapi_embedding_models_selected.json`,
`research/06b/hf_configs_embedding_models.json`, `research/06b/arxiv_hnsw_paper.txt`,
`research/06b/sbert_*.txt`, `research/06b/openai_embeddings.txt`,
`research/06b/pypi_versions_selected.json`, `research/06b/releases_versions.json`.

Розділ довідника: [`sections/15-embeddings.md`](../sections/15-embeddings.md).
"""
    ),
    code(VERSION_CELL),
]
