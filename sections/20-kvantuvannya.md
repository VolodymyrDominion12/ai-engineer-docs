## 20. Квантування й оптимізація інференсу

Квантування (quantization) — це заміна чисел з плаваючою комою, якими зберігаються ваги моделі, на
числа з меншою розрядністю. Практичний результат вимірюється двома числами: скільки пам'яті
звільнилося і на скільки впала якість. Документація `bitsandbytes` описує два крайні випадки прямо:
8-бітне квантування **вдвічі** зменшує споживання пам'яті, а 4-бітне — **у 4 рази**; платою є те, що
частина інформації про ваги втрачається необоротно.

Розділ побудований на п'яти інструментах, які покривають майже весь локальний інференс:
`bitsandbytes` (8-bit і 4-bit NF4), GPTQ, AWQ, TorchAO і типи GGUF у `llama.cpp`. Для кожного — що
саме він робить з тензорами, які назви параметрів існують, де ламається і коли брати інший.

**Межа чесності цього розділу.** Усі назви параметрів, конфігураційних класів, типів квантизації та
числа з бенчмарків узяті з файлів `research/`, перелічених у кінці. Точні ідентифікатори типів GGML
(типу `GGML_TYPE_Q4_K`) виписані **програмно** з `research/quant/ggml_h.txt`, а не з пам'яті — код
розбору наведено в 20.5. Там, де джерела не дають відповіді (наприклад, точні рівні NF4 або
біт-на-параметр для окремих GGUF-типів), це позначено прямо як «не вдалося підтвердити».

---

### 20.1 Що таке квантизація: ваги, активації, точність

**Що це.** Квантування замінює тензор дійсних чисел тензором цілих чисел меншої розрядності плюс
кілька чисел-масштабів, за якими цілі числа повертаються до дійсних. Квантують окремо **ваги**
(статичні, відомі до запуску) і **активації** (обчислюються під час прямого проходу й залежать від
входу).

**Навіщо це знати.** Розрядність визначає, чи вміститься модель у вашу пам'ять і скільки коштуватиме
кожен токен. Документація TorchAO дає для цього точну нотацію — `A16W4` означає «активації у 16 біт,
ваги у 4 біти», і саме цією нотацією позначено сім підтримуваних схем:

| Позначення TorchAO | Що квантується | Приклад класу конфігурації |
|---|---|---|
| A16W8 Float8 Dynamic | ваги у float8, активації — динамічно | `Float8DynamicActivationFloat8WeightConfig` |
| A16W8 Float8 WeightOnly | лише ваги у float8 | `Float8WeightOnlyConfig` |
| A8W8 Int8 Dynamic | і ваги, і активації у int8 | `Int8DynamicActivationInt8WeightConfig` |
| A16W8 Int8 Weight Only | лише ваги у int8 | `Int8WeightOnlyConfig` |
| A16W4 Int4 Weight Only | лише ваги у int4 | `Int4WeightOnlyConfig` |
| A16W4 Int4 + 2:4 Sparsity | ваги int4 плюс розрідженість | `Int4WeightOnlyConfig` разом із 2:4-розрідженістю |
| Autoquantization | вибір схеми автоматично | автопідбір у TorchAO |

Різниця між рядками — не косметична. Weight-only-схеми (усі, крім `Dynamic`) квантують лише ваги, бо
вони не залежать від входу. Активації потребують калібрування або динамічного обчислення масштабу на
кожному прямому проході, тому дають більший виграш у швидкості матричного множення, але дорожчі в
реалізації й крихкіші до зсуву розподілу входів.

**Як працює під капотом.**

Три механізми, на яких тримається все решта.

**1. Блочне (block-wise) квантування.** Один масштаб на весь тензор — погана ідея: у вагах є викиди,
які розтягують діапазон і роблять крок сітки грубим для решти 99% значень. Тому тензор ріжуть на
блоки, і кожен блок отримує власний масштаб. Саме це `bitsandbytes` називає block-wise quantization і
саме цим пояснює збереження 32-бітної якості в 8-бітних оптимізаторах. У TorchAO той самий параметр
називається `group_size` (у прикладах документації — `group_size=128`), у конфігурації AWQ-моделі на
Hub — `"group_size": 128`. Чим дрібніший блок, тим точніше й тим більше службових масштабів треба
зберегти; масштаби займають місце поверх самих ваг.

**2. Окремі шляхи для викидів.** `bitsandbytes` описує LLM.int8() як **vector-wise quantization**:
більшість ознак квантується у 8 біт, а викиди обробляються **окремо множенням у 16 біт**. Причина
фізіологічна, і документація дає конкретні числа: значення прихованих станів зазвичай розподілені
нормально в діапазоні `[-3.5, 3.5]`, але у великих моделях розподіл стає `[-60, 6]` або `[6, 60]`.
8-бітне квантування добре працює для значень близько 5, а далі починається суттєва втрата якості.
Тому є поріг (threshold): значення, більші за нього, виносяться з 8-бітного шляху.

**3. Nested (double) quantization.** Службові масштаби блоків теж можна квантувати. Документація
`bitsandbytes` оцінює це як **додаткові 0.4 біта на параметр** економії без додаткової ціни за
швидкість.

**Ринок рівнів, а не рівномірна сітка.** NF4 (`Normal Float 4`) — це 4-бітний тип із роботи QLoRA,
який документація описує як «адаптований для ваг, ініціалізованих із нормального розподілу». Ідея в
тому, що рівні розміщують не рівномірно, а щільніше там, де в нормального розподілу більше маси.
Точну таблицю з 16 значень рівнів NF4 у наявних джерелах не наведено — **не вдалося підтвердити
станом на 09.2026**.

#### Робочий приклад: скільки пам'яті займають самі ваги

Код нижче — чиста арифметика, GPU не потрібен. Він відповідає на питання, з якого починається будь-яке
рішення про квантування: скільки гігабайт займе модель у кожній розрядності.

```python
# Скільки пам'яті займають самі ваги. Чиста арифметика, GPU не потрібен.
GIB = 1024 ** 3

# Біт на параметр. 32 і 16 — стандартні dtype; 8 і 4 — те, що документація
# bitsandbytes описує як «вдвічі менше» та «у 4 рази менше» споживання пам'яті.
BIT_WIDTHS = {
    "fp32": 32,
    "bf16/fp16": 16,
    "int8 / Q8_0": 8,
    "int4 / Q4_0 / NF4": 4,
}

MODELS = {
    "Llama-3.2-3B": 3.2e9,
    "Llama-3.1-8B": 8.0e9,
    "13B-клас": 13.0e9,
    "70B-клас": 70.0e9,
    "MoE-клас 671B (V3/R1)": 671.0e9,
}


def weights_gib(n_params: float, bits: int) -> float:
    # bytes = params * bits / 8; GiB = bytes / 1024**3
    return n_params * bits / 8 / GIB


header = f"{'модель':28}{'параметрів':>12} " + " ".join(f"{k:>19}" for k in BIT_WIDTHS)
print(header)
print("-" * len(header))
for name, n in MODELS.items():
    row = f"{name:28}{n / 1e9:>10.1f} B "
    row += " ".join(f"{weights_gib(n, b):>15.2f} GiB" for b in BIT_WIDTHS.values())
    print(row)
```

**Фактичний вивід**

```text
модель                        параметрів                fp32           bf16/fp16         int8 / Q8_0   int4 / Q4_0 / NF4
------------------------------------------------------------------------------------------------------------------------
Llama-3.2-3B                       3.2 B           11.92 GiB            5.96 GiB            2.98 GiB            1.49 GiB
Llama-3.1-8B                       8.0 B           29.80 GiB           14.90 GiB            7.45 GiB            3.73 GiB
13B-клас                          13.0 B           48.43 GiB           24.21 GiB           12.11 GiB            6.05 GiB
70B-клас                          70.0 B          260.77 GiB          130.39 GiB           65.19 GiB           32.60 GiB
MoE-клас 671B (V3/R1)            671.0 B         2499.67 GiB         1249.83 GiB          624.92 GiB          312.46 GiB
```

Читається так: 70B-модель у bf16 вимагає 130.39 GiB лише під ваги, а в 4 бітах — 32.60 GiB. Це межа
між «потрібні дві A100-80GB» і «вміщається в одну». Розрахунок не враховує ні KV-кеш, ні активації,
ні проміжні буфери — тільки ваги.

**Чому ділення на 8 і на 4 дає правильний порядок.** Документація `bitsandbytes` формулює виграш як
«вдвічі» та «у 4 рази», і з арифметики видно, звідки беруться саме такі множники: bf16 — це 2 байти на
параметр, int8 — 1 байт, int4 — половина байта. Отже 8 біт дають рівно 2× відносно bf16, а 4 біти —
рівно 4×.

#### Робочий приклад: блочне квантування проти одного масштабу на тензор

Тут видно, **навіщо** потрібні блоки. Код реалізує симетричне цілочисельне квантування
(`q = round(x / scale)`, `x' = q * scale`) і міряє відносну похибку відновлення у двох режимах: один
масштаб на весь тензор і один масштаб на блок. Це не бібліотечне квантування — це його механіка,
зменшена до 30 рядків на `numpy`.

```python
import numpy as np

N_OUT, N_IN = 768, 768
DEVICE_EXAMPLE = 128  # стільки чисел у блоці в прикладах документації TorchAO (group_size=128)


def make_weight_matrix(seed: int, outlier_scale: float) -> np.ndarray:
    """Ваги + кілька викидів, як у реальних шарах."""
    r = np.random.default_rng(seed)
    w = r.normal(0.0, 0.02, size=(N_OUT, N_IN)).astype(np.float32)
    w[0, :8] *= outlier_scale  # викиди в одному рядку
    return w


def quantize_symmetric(w: np.ndarray, bits: int, block: int | None) -> np.ndarray:
    """Симетричне квантування з одним масштабом на тензор (block=None) або на блок."""
    qmax = 2 ** (bits - 1) - 1
    if block is None:
        scale = np.abs(w).max() / qmax
        scale = max(float(scale), 1e-12)
        return np.round(w / scale).clip(-qmax - 1, qmax) * scale
    flat = w.reshape(-1)
    pad = (-flat.size) % block
    flat = np.concatenate([flat, np.zeros(pad, dtype=np.float32)])
    blocks = flat.reshape(-1, block)
    scales = np.abs(blocks).max(axis=1, keepdims=True) / qmax
    scales = np.maximum(scales, 1e-12)
    restored = np.round(blocks / scales).clip(-qmax - 1, qmax) * scales
    return restored.reshape(-1)[: w.size].reshape(w.shape)


def rel_error(w: np.ndarray, w_hat: np.ndarray) -> float:
    return float(np.linalg.norm(w - w_hat) / np.linalg.norm(w))


w = make_weight_matrix(seed=7, outlier_scale=40.0)
print(f"тензор: {w.shape}, викидів у рядку 0: 8, максимум |w| = {np.abs(w).max():.4f}")
print()
print(f"{'біти':>5} {'режим':>22} {'відносна похибка':>18} {'макс. абс. помилка':>20}")
print("-" * 68)
for bits in (8, 4, 3, 2):
    for label, block in (("один масштаб на тензор", None),
                         (f"масштаб на блок {DEVICE_EXAMPLE}", DEVICE_EXAMPLE)):
        w_hat = quantize_symmetric(w, bits, block)
        err = rel_error(w, w_hat)
        maxerr = float(np.abs(w - w_hat).max())
        print(f"{bits:>5} {label:>22} {err:>17.4%} {maxerr:>20.6f}")
```

**Фактичний вивід**

```text
тензор: (768, 768), викидів у рядку 0: 8, максимум |w| = 1.0722

 біти                  режим   відносна похибка   макс. абс. помилка
--------------------------------------------------------------------
    8 один масштаб на тензор          12.1292%             0.004221
    8    масштаб на блок 128           0.6668%             0.004205
    4 один масштаб на тензор          99.4536%             0.076561
    4    масштаб на блок 128          11.7717%             0.067338
    3 один масштаб на тензор          99.4770%             0.138080
    3    масштаб на блок 128          27.3093%             0.138080
    2 один масштаб на тензор          99.5626%             0.363737
    2    масштаб на блок 128          76.3214%             0.363737
```

Що тут головне:

1. **Один масштаб на тензор ламається вже на 4 бітах.** 99.45% відносної похибки — це не «трохи
   гірше», це знищена матриця: вісім викидів у рядку 0 задали масштаб, і решта 589 816 значень
   округлилися до нуля. Саме тому блочне квантування — не оптимізація, а необхідна умова.
2. **Блоки дають виграш у 8.4 раза на 4 бітах** (11.77% проти 99.45%) і в 18 разів на 8 бітах
   (0.67% проти 12.13%).
3. **Максимальна абсолютна помилка майже не залежить від режиму** (0.0766 проти 0.0673 на 4 бітах) —
   і це важливо: блоки рятують не гірший випадок, а **більшість** значень. Один викид усе одно
   втратить точність, навіть якщо лежить в окремому блоці.
4. **3 і 2 біти без калібрування непридатні.** Навіть з блоками похибка 27% і 76%. Це пояснює, чому
   екосистема будує 3- і 2-бітні формати на складніших схемах, а не на рівномірній сітці.

**Типові помилки**

- **Квантувати все підряд.** Документація `bitsandbytes` наводить `llm_int8_skip_modules` саме для
  цього: у Jukebox кілька модулів `lm_head` не можна квантувати, бо це спричиняє нестабільність.
  У TorchAO той самий прийом робиться через `FqnToConfig({{"_default": config, "<ім'я шару>": None})`,
  і `lm_head` не квантується типово.
- **Плутати дві різні «квантизації».** У розділі 15 («Квантування» в контексті векторного пошуку)
  ідеться про стиснення **векторів ембедингів** для ANN-індексу. Тут — про стиснення **матриць ваг
  моделі**. Спільна лише ідея меншої розрядності; інструменти й метрики різні.
- **Забувати про службові масштаби.** 4-бітні ваги — це не «0.5 байта на параметр без нічого». Блок
  із 128 значень важить 64 байти даних плюс масштаб; nested quantization зменшує саме цей оверхед.
- **Міряти якість «на око».** Похибка відновлення ваг — не похибка моделі. Вона показує лише, що
  квантування працює; чи впала якість відповідей, показує евалюація (розділ 24).
- **Вважати, що квантування прискорює завжди.** Воно зменшує обсяг, який треба передати з пам'яті, і
  саме тому допомагає на decode-стадії (розділ 2). Якщо ядро не має швидкого шляху деквантування,
  ви отримаєте економію пам'яті й **повільніший** інференс.

**Альтернативи.** Коли потрібна не менша розрядність, а менший обсяг: зменшити саму модель (розділ 6),
перейти на MoE-архітектуру, винести частину шарів на CPU (див. 20.7), або взагалі залишити інференс
провайдеру (розділ 2).

---

### 20.2 bitsandbytes: 8-bit і 4-bit (NF4)

**Що це.** `bitsandbytes` — бібліотека з легким Python-обгортковим шаром над апаратними функціями
прискорювача. Вона підмінює стандартні `torch.nn.Linear` на квантовані аналоги й дає три речі:
`Linear8bitLt` (8-бітний лінійний шар), `Linear4bit` (4-бітний) і 8-бітні оптимізатори в модулі
`bitsandbytes.optim`.

**Навіщо це знати.** Це найшвидший шлях від «модель не вміщається» до «модель працює», бо не потрібне
ані калібрування на датасеті, ані окремий крок конвертації: ви передаєте `BitsAndBytesConfig` у
`from_pretrained`, і квантизація відбувається під час завантаження. Друга причина — QLoRA: 4-бітне
квантування плюс невеликий набір тренованих low-rank адаптерів дає змогу **доучувати** модель, а не
лише запускати (розділ 21).

**Як працює під капотом.**

- **8-біт (LLM.int8()).** Vector-wise quantization: більшість ознак — у int8, викиди — окремим
  множенням у 16 біт. Поріг викиду задає `llm_int8_threshold`; документація каже, що типове значення
  — **6**, менше значення потрібне для нестабільних моделей (малих або доучених), а
  `llm_int8_threshold=0.0` суттєво прискорює інференс ціною можливої втрати точності.
- **4-біт (QLoRA/NF4).** Ваги зберігаються в 4 біти, а обчислення ведуться в іншому типі, який задає
  `bnb_4bit_compute_dtype` (документація пропонує `torch.bfloat16` замість типового float32 — це
  прискорює обчислення). Тип квантування задає `bnb_4bit_quant_type="nf4"`.
- **Подвійне квантування.** `bnb_4bit_use_double_quant=True` квантує ще й службові масштаби, додаючи
  ті самі 0.4 біта на параметр економії.
- **Тип решти модулів.** При 8-бітному завантаженні всі інші модулі (наприклад, `LayerNorm`)
  залишаються в типовому dtype torch; при 4-бітному — конвертуються в `torch.float16`. Керує цим
  параметр `dtype`; `dtype="auto"` бере значення з `config.json` моделі.
- **Офлоад.** Для 8-бітних моделей `llm_int8_enable_fp32_cpu_offload=True` дозволяє виносити ваги на
  CPU. Деталь, яку легко проґавити: ваги, відправлені на CPU, зберігаються у **float32** і **не**
  конвертуються у 8 біт. Тобто офлоад на CPU не дає 8-бітної економії.

**Що змінилося у 0.50.0 (реліз 2026-07-25).** Це останній підтверджений реліз у джерелах:

- Нові об'єднані ядра «деквантування + GEMM» для 4-бітного інференсу на CUDA замінюють старі шляхи
  GEMV і `dequantize + F.linear` для малих і середніх батчів. Заявлено **до 4× швидше** за батчів
  **від 2 до 64** на архітектурах від Turing до Blackwell, з виграшем і за батчу 1 у багатьох
  випадках. Nested quantization і bias теж вбудовані в ядро. Вибір ядра — автоматичний у рантаймі за
  формою тензора, архітектурою GPU та кількістю SM.
- CPU: блочне квантування й деквантування прискорилися **від 1.1× до понад 20×** залежно від
  операції, dtype і заліза; найбільші виграші на fp16 і на x86-64 без AVX-512.
- ROCm вийшов зі статусу preview і вважається стабільним; додано RDNA2, частину RDNA3/3.5 і CDNA1
  (`gfx908`).
- Apple Silicon (MPS): усі 4-бітні конфігурації й LLM.int8() тепер працюють; потрібен torch >= 2.9, а
  на macOS 26+ для найкращої швидкості слід поставити пакет `kernels`, інакше використовується
  наївний фолбек. 8-бітні оптимізатори на MPS ще не реалізовані.
- **Ламальні зміни:** мінімальний PyTorch — 2.4; вилучено модуль `research`, не-блочні
  (`block_wise=False`) оптимізатори й застарілі функції динамічного квантування разом з їхніми
  CUDA/HIP-ядрами.
- **Застарівання:** `igemm`, `batched_igemm` і `check_matmul` оголошені deprecated; передавання
  4-бітних ваг у транспонованій орієнтації `[in_features, out_features]` у `matmul_4bit` видає
  `DeprecationWarning`.

#### Вимоги до заліза

| Функція | Мінімальне залізо (документація HF) |
|---|---|
| 8-бітні оптимізатори | NVIDIA Pascal (GTX 10X0, P100) або новіші |
| LLM.int8() | NVIDIA Turing (RTX 20X0, T4) або новіші |
| NF4/FP4 quantization | NVIDIA Pascal (GTX 10X0, P100) або новіші |

За README бібліотеки ширші вимоги до платформ: Python 3.10+, PyTorch 2.4+; CUDA 11.8–13.0;
Linux glibc ≥ 2.24, Windows 11 / Server 2022+, macOS 14+. На CPU x86-64 мінімум — AVX2, оптимізовано
під AVX512F і AVX512BF16. Для NVIDIA — SM60+ як мінімум, SM75+ рекомендовано. Окремо позначено, що
QLoRA на Intel Gaudi (HPU) підтримано **частково**, а 8-бітні оптимізатори там не підтримані зовсім;
на macOS через MPS 8-бітні оптимізатори позначені як заплановані.

#### Робочий приклад: 8-біт і 4-біт (NF4) через `BitsAndBytesConfig`

Потрібні `torch` + `bitsandbytes` і GPU. Назви параметрів — з документації Transformers.

```python
import torch
from transformers import AutoModelForCausalLM, BitsAndBytesConfig

MODEL_ID = "bigscience/bloom-1b7"

# ── 8-біт: LLM.int8() ────────────────────────────────────────────────────
cfg_8bit = BitsAndBytesConfig(
    load_in_8bit=True,                       # квантувати лінійні шари у 8 біт
    llm_int8_threshold=6.0,                  # поріг викиду (типове значення — 6)
    llm_int8_skip_modules=["lm_head"],       # lm_head не квантуємо
)

model_8bit = AutoModelForCausalLM.from_pretrained(
    MODEL_ID,
    device_map="auto",
    quantization_config=cfg_8bit,
)
print("8-біт, footprint:", model_8bit.get_memory_footprint())

# ── 4-біт: NF4 + подвійне квантування ────────────────────────────────────
cfg_4bit = BitsAndBytesConfig(
    load_in_4bit=True,
    bnb_4bit_quant_type="nf4",               # тип із роботи QLoRA
    bnb_4bit_compute_dtype=torch.bfloat16,   # обчислення в bf16, не float32
    bnb_4bit_use_double_quant=True,          # +0.4 біта/параметр економії
)

model_4bit = AutoModelForCausalLM.from_pretrained(
    MODEL_ID,
    device_map="auto",
    quantization_config=cfg_4bit,
)
print("4-біт, footprint:", model_4bit.get_memory_footprint())

# Повернення до вихідної точності (потрібно достатньо пам'яті!)
model_4bit.dequantize()
```

Серіалізація квантованої моделі вимагає свіжих версій Transformers і bitsandbytes: спершу пишеться
`quantization_config` у `config.json`, потім ваги.

```python
model_8bit.save_pretrained("bloom-1b7-8bit")
model_8bit.push_to_hub("your-username/bloom-1b7-8bit")

# Завантаження квантованої моделі вже БЕЗ quantization_config
from transformers import AutoModelForCausalLM as AM

again = AM.from_pretrained("your-username/bloom-1b7-8bit", device_map="auto")
```

**Типові помилки**

- **Чекати, що `quantization_config` прокинеться через `from_pretrained` як `load_in_4bit`.** У
  Transformers v5 аргументи `load_in_4bit` і `load_in_8bit` **видалені** з `from_pretrained` на
  користь `quantization_config`. Але поле `load_in_4bit` усередині `BitsAndBytesConfig` лишається —
  плутанина виникає саме на цьому місці.
- **Тренувати квантовану модель цілком.** Документація попереджає прямо: 8- і 4-бітне тренування
  підтримане **лише для тренування додаткових параметрів** (тобто LoRA-адаптерів).
- **Очікувати 8-бітної економії від офлоаду на CPU.** Ваги на CPU зберігаються у float32.
- **Забути про `device_map` при збереженні GPTQ/bnb-моделі.** Якщо модель квантувалася з
  `device_map`, перед `save_pretrained` її треба перемістити на один пристрій.
- **Ставити `llm_int8_threshold=0.0` «щоб було швидше» без перевірки якості.** Документація прямо
  називає це компромісом: швидкість зростає, точність може впасти.
- **Плутати `bnb_4bit_quant_type` і `bnb_4bit_compute_dtype`.** Перший — як зберігаються ваги, другий —
  у якому типі ведеться множення. Документація зазначає, що для **інференсу** тип квантизації майже не
  впливає на продуктивність, а для тренування 4-бітних базових моделей слід брати саме NF4.

**Альтернативи.** GPTQ і AWQ (20.3) дають квантування з калібруванням — краща якість ціною окремого
кроку конвертації. TorchAO (20.4) дає вибір схем аж до float8 і композицію з `torch.compile`. GGUF
(20.5) — те саме для екосистеми `llama.cpp`.

---

### 20.3 GPTQ і AWQ: квантизація після тренування

**Що це.** Обидва методи — post-training quantization (PTQ): модель уже натренована, квантування
відбувається після, з урахуванням статистики ваг і (для AWQ) активацій. GPTQ квантує кожен рядок
матриці ваг незалежно, підбираючи версію ваг, що мінімізує помилку; AWQ зберігає невелику частку ваг,
важливих для якості моделі.

**Навіщо це знати.** PTQ дає кращий компроміс «пам'ять/якість», ніж просте квантування під час
завантаження, бо алгоритм бачить матрицю цілком і може компенсувати помилку. Ціна — окремий крок
конвертації, калібрувальний датасет і те, що результат стає артефактом, який треба десь зберігати.

**Як працює під капотом.**

**GPTQ.** Документація описує алгоритм так: кожен рядок матриці ваг квантується **незалежно**, щоб
знайти версію ваг, яка мінімізує помилку. Ваги квантуються в **int4**, але **відновлюються у fp16 на
льоту** під час інференсу — деквантування відбувається в **об'єднаному ядрі** (fused kernel), а не
через глобальну пам'ять GPU. Саме звідси 4-кратна економія пам'яті, і саме тому інференс стає
швидшим: менша розрядність — менше часу на передачу даних.

Активний бекенд — **GPT-QModel** (Python-пакет `gptqmodel`). `AutoGPTQ` у Transformers більше **не
підтримується**. GPT-QModel дає асиметричне квантування, яке потенційно знижує помилку проти
симетричного, але **не сумісний зі старими чекпойнтами AutoGPTQ**, і не всі ядра (зокрема Marlin)
підтримують асиметричне квантування.

**Marlin** — окреме 4-бітне CUDA-ядро GPTQ, сильно оптимізоване під NVIDIA A100 (Ampere).
Завантаження, деквантування й виконання деквантованих ваг розпаралелені, що дає суттєвий виграш проти
оригінального CUDA-ядра GPTQ. Обмеження важливе: Marlin доступний **лише для квантованого інференсу**
й **не підтримує саму квантизацію**. Вмикається параметром `backend` у `GPTQConfig`.

**AWQ.** Activation-aware Weight Quantization зберігає невелику частку ваг, важливих для якості
моделі, і так стискає модель до 4 біт із мінімальною деградацією. Є кілька бібліотек: `llm-awq`,
`autoawq`, `optimum-intel`; Transformers уміє завантажувати моделі, квантовані `llm-awq` і `autoawq`.

**Як відрізнити AWQ-модель.** За ключем `quant_method` у `config.json` моделі. Документація наводить
реальний приклад:

```json
{
  "quantization_config": {
    "quant_method": "awq",
    "zero_point": true,
    "group_size": 128,
    "bits": 4,
    "version": "gemm"
  }
}
```

**Fused modules** — окрема оптимізація AWQ: об'єднання модулів дає кращу точність **і** швидкість.
Підтримано «з коробки» для архітектур Llama і Mistral; для інших задається мапа `modules_to_fuse`.
Обмеження: **fused modules не можна поєднувати з FlashAttention2**.

**ExLlamaV2** — ядра, що дають швидший prefill і декодування; вмикаються `version="exllama"` в
`AwqConfig`, підтримані на AMD GPU.

#### Робочий приклад: квантування через GPTQ і завантаження AWQ

```bash
# GPTQ: Transformers більше не містить AutoGPTQ — ставимо GPT-QModel
pip install --upgrade accelerate optimum transformers
pip install gptqmodel --no-build-isolation

# AWQ: для завантаження достатньо autoawq
pip install autoawq
```

```python
# ── GPTQ: сама квантизація ──────────────────────────────────────────────
from transformers import AutoModelForCausalLM, AutoTokenizer, GPTQConfig

tokenizer = AutoTokenizer.from_pretrained("facebook/opt-125m")

# dataset="c4" — датасет із роботи GPTQ; документація рекомендує саме його
gptq_config = GPTQConfig(bits=4, dataset="c4", tokenizer=tokenizer)

# Власний датасет можна передати списком рядків
gptq_config_own = GPTQConfig(
    bits=4,
    dataset=["довільний текст для калібрування ваг"],
    tokenizer=tokenizer,
)

quantized = AutoModelForCausalLM.from_pretrained(
    "facebook/opt-125m",
    device_map="auto",
    max_memory={0: "30GiB", 1: "46GiB", "cpu": "30GiB"},  # disk offloading НЕ підтримується
    quantization_config=gptq_config,
)
quantized.push_to_hub("your-username/opt-125m-gptq")
```

```python
# ── GPTQ: інференс через ядро Marlin (4 біти, A100-клас) ────────────────
from transformers import AutoModelForCausalLM, GPTQConfig

model = AutoModelForCausalLM.from_pretrained(
    "your-username/opt-125m-gptq",
    device_map="auto",
    quantization_config=GPTQConfig(bits=4, backend="marlin"),
)
```

```python
# ── AWQ: завантаження готової моделі ────────────────────────────────────
import torch
from accelerate import Accelerator
from transformers import AutoModelForCausalLM, AwqConfig

device = Accelerator().device

model = AutoModelForCausalLM.from_pretrained(
    "TheBloke/zephyr-7B-alpha-AWQ",
    dtype=torch.float32,      # решта ваг; типово AWQ ставить fp16
    device_map=device,
)

# Додаткове прискорення — FlashAttention2 (але не разом із fused modules!)
model_fa2 = AutoModelForCausalLM.from_pretrained(
    "TheBloke/zephyr-7B-alpha-AWQ",
    attn_implementation="flash_attention_2",
    device_map=Accelerator().device,
)

# ── AWQ: fused modules ──────────────────────────────────────────────────
# fuse_max_seq_len = довжина контексту + очікувана довжина генерації
awq_fused = AwqConfig(bits=4, fuse_max_seq_len=512, do_fuse=True)
model_fused = AutoModelForCausalLM.from_pretrained(
    "TheBloke/Mistral-7B-OpenOrca-AWQ",
    quantization_config=awq_fused,
).to(0)
```

#### Скільки дає fused modules: реальні числа з документації

Документація наводить бенчмарк `TheBloke/Mistral-7B-OpenOrca-AWQ` за `batch_size=1`. Найпоказовіший
рядок — декодування (саме воно домінує в чаті): **38.45 ток/с без fused і 80.26 ток/с з fused** на
Prefill/Decode 32/32, тобто приблизно **вдвічі швидше** за того самого VRAM. Порівняння за довжини
2048/2048: 35.27 проти 89.47 ток/с. Детальніше — у таблицях нижче (20.6).

**Типові помилки**

- **Квантувати модель, для якої вже є готовий квантований чекпойнт.** Документація радить перевірити
  Hub перед квантизацією. Час квантизації не косметичний: близько **5 хвилин** для `facebook/opt-350m`
  на безкоштовному GPU у Colab, але близько **4 годин** для 175B-моделі на NVIDIA A100.
- **Сподіватися на disk offloading у GPTQ.** Документація каже прямо: його не підтримано, тому при
  нестачі пам'яті через великий датасет викручуються параметром `max_memory`.
- **Поєднати fused modules AWQ з FlashAttention2.** Документація забороняє це прямо.
- **Поставити `autoawq` у проєкті зі свіжим Transformers і не перевірити версію.** `autoawq` **відкочує
  Transformers до 4.47.1**; після встановлення може знадобитися перевстановити Transformers.
- **Використовувати старі AutoGPTQ-чекпойнти з GPT-QModel.** Бекенд не є зворотно сумісним із
  легасі-чекпойнтами AutoGPTQ.
- **Зберегти модель, квантовану з `device_map`, без перенесення на один пристрій.** Перед
  `save_pretrained` треба викликати `model.to("cpu")` (або на GPU).

**Альтернативи.** `bitsandbytes` (20.2) — коли не хочеться калібрувати й конвертувати. TorchAO (20.4) —
коли потрібен float8 або per-module конфігурація. GGUF (20.5) — коли цільовий рантайм `llama.cpp`.

---

### 20.4 TorchAO

**Що це.** `torchao` — бібліотека оптимізації архітектур PyTorch із підтримкою власних
високопродуктивних типів даних, квантизації та розрідженості. Ключова властивість — композиція з
нативними механізмами PyTorch, зокрема `torch.compile`.

**Навіщо це знати.** TorchAO покриває те, чого немає в `bitsandbytes`: float8, розрідженість 2:4,
квантування KV-кешу, квантування станів оптимізатора, а також конфігурацію **на рівні окремих
модулів**. Саме тому Transformers v5 називає квантування «first-class citizen» і окремо відзначає
інтеграцію TorchAO.

**Як працює під капотом.**

| Можливість TorchAO | Що дає |
|---|---|
| Quantization Aware Training (QAT) | тренування квантованих моделей з мінімальною втратою точності |
| Float8 Training | високопропускне тренування у float8-форматах |
| Sparsity Support | напівструктурована розрідженість 2:4 для швидшого інференсу |
| Optimizer Quantization | 4- і 8-бітні варіанти Adam для меншого стану оптимізатора |
| KV Cache Quantization | довгий контекст за меншої пам'яті |
| Custom Kernels Support | власні `torch.compile`-сумісні операції |
| FSDP2 | композиція з FSDP2 для тренування |

Ключова зміна API: **потрібен `torchao >= 0.15.0`**, і рядковий API (наприклад,
`TorchAoConfig("int4_weight_only")`) **видалено** — тепер передаються об'єкти-конфігурації на кшталт
`Int4WeightOnlyConfig(...)`. Серіалізація через `save_pretrained` у форматі safetensors теж підтримана
лише з `torchao >= 0.15`; нижче доводилося вручну писати небезпечні `.bin` через `torch.save`.

**Компіляція.** Параметр `cache_implementation="static"` автоматично компілює `forward` через
`torch.compile` після першого інференсу. Пастка: модель **перекомпільовується щоразу**, коли
змінюється розмір батчу або `max_new_tokens`. Щоб квантизувати без компіляції, у `generate` передають
`disable_compile=True`.

**Вибір схеми за залізом** (з документації):

| Залізо | Рекомендовані конфігурації |
|---|---|
| H100 | `Float8DynamicActivationFloat8WeightConfig`, `Float8WeightOnlyConfig`; для int4 — `GemliteUIntXWeightOnlyConfig(group_size=128)` |
| A100 | `Int8DynamicActivationInt8WeightConfig`, `Int8WeightOnlyConfig`; для int4 — `GemliteUIntXWeightOnlyConfig(group_size=128)` (батч N) або `Int4WeightOnlyConfig(group_size=128, use_hqq=True)` (батч 1, ядро tinygemm) |
| Intel XPU | `Int8DynamicActivationInt8WeightConfig`, `Int8WeightOnlyConfig`; int4 — `Int4WeightOnlyConfig(group_size=128, int4_packing_format="plain_int32")` |
| CPU | `Int8DynamicActivationInt8WeightConfig`, `Int8WeightOnlyConfig`; int4 — `PrototypeInt4WeightOnlyConfig(group_size=128, int4_choose_qparams_algorithm="tinygemm")` (потрібен torchao >= 0.15.0) |

Сумісність: CUDA `cu118`, `cu126`, `cu128`; XPU на `pytorch2.8`; CPU — через `device_map="cpu"`.

#### Робочий приклад: per-module квантизація через `FqnToConfig`

```python
import torch
from transformers import AutoModelForCausalLM, TorchAoConfig
from torchao.quantization import (
    Int4WeightOnlyConfig,
    Int8DynamicActivationInt4WeightConfig,
    IntxWeightOnlyConfig,
    FqnToConfig,
    PerAxis,
    MappingType,
)

model_id = "meta-llama/Llama-3.1-8B-Instruct"

# Типово — int4, але шар model.layers.0.self_attn.q_proj лишаємо без квантизації.
# lm_head TorchAO не квантує самостійно.
linear_cfg = Int4WeightOnlyConfig(group_size=128)
quant_config = FqnToConfig(
    {
        "_default": linear_cfg,                    # решта лінійних шарів -> int4
        "model.layers.0.self_attn.q_proj": None,   # None = не квантувати цей шар
    }
)

quantization_config = TorchAoConfig(quant_type=quant_config)
model = AutoModelForCausalLM.from_pretrained(
    model_id,
    device_map="auto",
    dtype=torch.bfloat16,
    quantization_config=quantization_config,
)
print("quantized model:", model)

# Активації квантуються іншим правилом, ніж ваги — різні модулі можуть мати різні схеми.
embedding_cfg = IntxWeightOnlyConfig(
    weight_dtype=torch.int8,
    granularity=PerAxis(0),
    mapping_type=MappingType.ASYMMETRIC,
)
mixed = FqnToConfig(
    {
        "_default": Int8DynamicActivationInt4WeightConfig(group_size=128),
        "model.decoder.embed_tokens": embedding_cfg,
        "model.decoder.embed_positions": None,
    }
)
mixed_quantization_config = TorchAoConfig(quant_type=mixed, include_embedding=True)
```

Регулярні вирази теж підтримані: усі ключі, що починаються з `re:`, трактуються як регулярний вираз,
наприклад `re:model\.decoder\.layers\..+\.self_attn\.q_proj`. Пріоритет має точний збіг повного імені
модуля.

**Типові помилки**

- **Використати рядковий API.** `TorchAoConfig("int4_weight_only")` більше не працює — потрібні
  об'єкти-конфігурації.
- **Забути про перекомпіляцію.** Зі `cache_implementation="static"` зміна `max_new_tokens` тягне
  повторну компіляцію; у бенчмарках це легко прийняти за «квантування повільніше».
- **Зберегти int4-модель і завантажити її на іншому пристрої.** Для int4 документація прямо каже:
  модель можна завантажити **лише на той самий пристрій**, де її квантували, бо розкладка специфічна
  для пристрою. Для int8 і float8 такого обмеження немає.
- **Серіалізувати через `save_pretrained` на torchao < 0.15.** Формат safetensors не підтримується;
  лишається `torch.save` з ненадійним `.bin`.
- **Квантувати embeddings випадково.** Для цього є окремий прапорець `include_embedding=True`; без
  нього вбудови лишаються в плаваючій комі.
- **Очікувати, що `group_size` можна міняти на льоту.** Розмір блоку фіксується на етапі квантизації й
  впливає на розкладку тензора.

**Альтернативи.** `bitsandbytes` (20.2) — якщо потрібне лише 8/4 біти без `torch.compile`. GPTQ/AWQ
(20.3) — якщо потрібен PTQ з калібруванням. Quanto, HQQ, EETQ та інші бекенди Transformers у наявних
джерелах не описані — **не вдалося підтвердити станом на 09.2026**.

---

### 20.5 GGUF і llama.cpp: типи `Q4_K`, `Q8_0`, `MXFP4`, `NVFP4`

**Що це.** GGUF — формат файлу моделі для екосистеми `llama.cpp`, побудований на бібліотеці `ggml`.
Тип квантизації в GGUF — це не «наскільки сильно стиснути», а **конкретний формат розкладки тензора**
з власним ідентифікатором на кшталт `GGML_TYPE_Q4_K`. Файл `.gguf` містить суміш типів: різні шари
можуть мати різну розрядність.

**Навіщо це знати.** Імена GGUF-файлів на Hub (`...-Q4_K_M.gguf`, `...-Q8_0.gguf`) — це не маркетинг,
а назви форматів, і від них залежить, які ядра зможе вибрати рантайм. Помилка в один символ
(`Q8_0` проти `Q8_K`) означає інший формат. Другий аргумент — GGUF є точкою обміну: Transformers v5
називає `llama.cpp` серед партнерів, з якими забезпечено інтероперабельність, і зазначає, що
завантажувати GGUF-файли в Transformers для подальшого fine-tuning тепер легко, як і конвертувати
моделі Transformers назад у GGUF.

**Як працює під капотом.**

`ggml` не має єдиної функції «квантувати модель». Замість цього є:

1. **Перелік типів тензорів** — кожен тип має власний розмір блоку й формат зберігання.
2. **Версія формату квантизації.** У `ggml.h` є константа `GGML_QNT_VERSION` зі значенням **2** і
   коментарем «bump this on quantization format changes», а також `GGML_QNT_VERSION_FACTOR` зі
   значенням **1000**. Тобто сумісність квантованих файлів версіонується окремо від версії самого
   файлу (`GGML_FILE_VERSION` = 2) і магічного числа `GGML_FILE_MAGIC` = `0x67676d6c`.
3. **Підказки про точність для ядер.** Функції `ggml_prec_set_acc(a, prec)` і
   `ggml_prec_set_src(a, prec, idx)` кажуть реалізації, яку **мінімальну** розрядність їй дозволено
   використати всередині. Рівні задає перелік `ggml_prec` з п'ятьма членами: `GGML_PREC_F32`,
   `GGML_PREC_BF16`, `GGML_PREC_F16`, `GGML_PREC_Q8`, `GGML_PREC_Q4`.

Семантика `ggml_prec` різна для двох функцій, і це видно з коментарів у заголовку:

| Рівень | `ggml_prec_set_src()` — які типи дозволено | `ggml_prec_set_acc()` — накопичувач |
|---|---|---|
| `GGML_PREC_F32` | `GGML_TYPE_F32` | накопичення у F32 |
| `GGML_PREC_BF16` | `GGML_TYPE_BF16` | накопичення у BF16 або F32 |
| `GGML_PREC_F16` | `GGML_TYPE_F16` | накопичення у F16 або F32 |
| `GGML_PREC_Q8` | `GGML_TYPE_Q8_0`, `GGML_TYPE_Q8_1`, `GGML_TYPE_Q8_K` | не дозволено |
| `GGML_PREC_Q4` | `GGML_TYPE_Q4_0`, `GGML_TYPE_Q4_1`, `GGML_TYPE_Q4_K`, `GGML_TYPE_NVFP4`, `GGML_TYPE_MXFP4` | не дозволено |

Документація в коментарях пояснює ефект на прикладі: `ggml_prec_set_src(a, GGML_PREC_Q8, 1)`
дозволяє ядру квантувати дані `src[1]` з F32/BF16/F16 **до** `GGML_TYPE_Q8_0`, але **не** до
`GGML_TYPE_Q4_0` чи `GGML_TYPE_NVFP4`; а `GGML_PREC_Q4` дозволяє 4-бітні типи, «такі як
`GGML_TYPE_Q4_K`, `GGML_TYPE_NVFP4` тощо». Обидві функції повертають `false` у разі невдачі.

Окремі деталі API: стара функція `ggml_mul_mat_set_prec()` оголошена застарілою
(`GGML_DEPRECATED`) із підказкою «use `ggml_prec_set_acc()` instead»; `ggml_cast(a, type)` виконує
приведення типу, причому «casting from f32 to i32 will discard the fractional part»;
`ggml_mul_mat_set_hint(a, hint)` задає підказку для того самого множення матриць.

#### Що саме підтверджено, а що ні

**Підтверджено** з `research/quant/ggml_h.txt` (11 унікальних ідентифікаторів типів):
`GGML_TYPE_F32`, `GGML_TYPE_F16`, `GGML_TYPE_BF16`, `GGML_TYPE_Q8_0`, `GGML_TYPE_Q8_1`,
`GGML_TYPE_Q8_K`, `GGML_TYPE_Q4_0`, `GGML_TYPE_Q4_1`, `GGML_TYPE_Q4_K`, `GGML_TYPE_NVFP4`,
`GGML_TYPE_MXFP4`.

**Підтверджено також** розподіл за розрядністю: `Q8_0`, `Q8_1` і `Q8_K` — 8-бітні типи, а `Q4_0`,
`Q4_1`, `Q4_K`, `NVFP4` і `MXFP4` — 4-бітні (це прямо випливає з коментаря про `GGML_PREC_Q8` і
`GGML_PREC_Q4`).

**Не вдалося підтвердити станом на 09.2026** (у наявному файлі цього немає):

- Повний перелік членів `enum ggml_type` — у файлі є лише оголошення функцій, що приймають
  `enum ggml_type`, але не саме тіло переліку. Типів на кшталт `Q5_0`, `Q5_K`, `Q6_K`, `Q3_K`,
  `Q2_K`, `IQ*`, `TQ1_0`, `TQ2_0` у файлі **немає жодної згадки**.
- Розмір блоку й точний біт-на-параметр для кожного окремого типу. Отже, число «4.83 біта на
  параметр» для `Q4_K_M`, яке часто цитують, **не перевірене** за цими джерелами.
- Що саме означає суфікс `_K` (у спільноті — «k-quant») і чим `Q4_K` структурно відрізняється від
  `Q4_0`. Із файлу видно лише те, що обидва належать до родини `GGML_PREC_Q4`.
- Різниця між `MXFP4` і `NVFP4` за межами назв. Відомо лише, що це два різні 4-бітні типи.

#### Робочий приклад: програмний розбір типів із `ggml.h`

Цей код — не декорація. Він витягує точні ідентифікатори з вихідного заголовка, тому його можна
перезапустити після оновлення `llama.cpp` і побачити, чи не додався новий тип.

```python
import pathlib
import re

text = pathlib.Path("research/quant/ggml_h.txt").read_text(encoding="utf-8")

# 1. Усі ідентифікатори типів тензорів, згадані у файлі.
type_ids = sorted(set(re.findall(r"GGML_TYPE_[A-Z0-9_]+", text)))
print(f"файл: research/quant/ggml_h.txt ({len(text.splitlines())} рядків)")
print(f"унікальних ідентифікаторів GGML_TYPE_*: {len(type_ids)}")
for t in type_ids:
    print(f"  {t:22} згадок у файлі: {text.count(t)}")

# 2. Ідентифікатори точності.
prec_ids = sorted(set(re.findall(r"GGML_PREC_[A-Z0-9_]+", text)))
print()
print(f"унікальних ідентифікаторів GGML_PREC_*: {len(prec_ids)}")
print("  " + ", ".join(prec_ids))

# 3. Розбір відповідності 'GGML_PREC_X - ... GGML_TYPE_Y ...'
line_re = re.compile(r"^(?P<prec>GGML_PREC_[A-Z0-9_]+)\s*-\s*(?P<rest>.+)$")


def clean(raw: str) -> str:
    s = raw.strip()
    if s.startswith("//"):
        s = s[2:].strip()
    if s.startswith("-"):
        s = s[1:].strip()
    return s


src_map, acc_notes = {}, {}
for raw in text.splitlines():
    m = line_re.match(clean(raw))
    if not m:
        continue
    prec, rest = m.group("prec"), m.group("rest")
    types = sorted(set(re.findall(r"GGML_TYPE_[A-Z0-9_]+", rest)))
    if types:
        src_map[prec] = (types, "etc." in rest)
    else:
        acc_notes[prec] = rest

print()
print("ggml_prec_set_src(): які типи дозволено отримати з кожного рівня")
for prec, (types, trailing) in src_map.items():
    suffix = " (+ інші, у файлі позначено 'etc.')" if trailing else ""
    print(f"  {prec:16} -> {', '.join(types)}{suffix}")

print()
print("ggml_prec_set_acc(): що той самий рівень означає для накопичувача")
for prec, note in acc_notes.items():
    print(f"  {prec:16} -> {note}")

# 4. Зворотний індекс: від типу до родини точності.
reverse = {}
for prec, (types, _) in src_map.items():
    for t in types:
        reverse.setdefault(t, []).append(prec)

print()
print("Зворотний індекс: тип -> родина точності")
for t in sorted(reverse):
    print(f"  {t:20} {', '.join(reverse[t])}")
```

**Фактичний вивід**

```text
файл: research/quant/ggml_h.txt (1821 рядків)
унікальних ідентифікаторів GGML_TYPE_*: 11
  GGML_TYPE_BF16         згадок у файлі: 1
  GGML_TYPE_F16          згадок у файлі: 1
  GGML_TYPE_F32          згадок у файлі: 5
  GGML_TYPE_MXFP4        згадок у файлі: 1
  GGML_TYPE_NVFP4        згадок у файлі: 3
  GGML_TYPE_Q4_0         згадок у файлі: 2
  GGML_TYPE_Q4_1         згадок у файлі: 1
  GGML_TYPE_Q4_K         згадок у файлі: 2
  GGML_TYPE_Q8_0         згадок у файлі: 2
  GGML_TYPE_Q8_1         згадок у файлі: 1
  GGML_TYPE_Q8_K         згадок у файлі: 1

унікальних ідентифікаторів GGML_PREC_*: 5
  GGML_PREC_BF16, GGML_PREC_F16, GGML_PREC_F32, GGML_PREC_Q4, GGML_PREC_Q8

ggml_prec_set_src(): які типи дозволено отримати з кожного рівня
  GGML_PREC_F32    -> GGML_TYPE_F32
  GGML_PREC_BF16   -> GGML_TYPE_BF16
  GGML_PREC_F16    -> GGML_TYPE_F16
  GGML_PREC_Q8     -> GGML_TYPE_Q8_0, GGML_TYPE_Q8_1, GGML_TYPE_Q8_K (+ інші, у файлі позначено 'etc.')
  GGML_PREC_Q4     -> GGML_TYPE_MXFP4, GGML_TYPE_NVFP4, GGML_TYPE_Q4_0, GGML_TYPE_Q4_1, GGML_TYPE_Q4_K (+ інші, у файлі позначено 'etc.')

ggml_prec_set_acc(): що той самий рівень означає для накопичувача
  GGML_PREC_F32    -> requires accumulation of the results in F32
  GGML_PREC_BF16   -> can accumulate the results in BF16, F32
  GGML_PREC_F16    -> can accumulate the results in F16, F32
  GGML_PREC_Q8     -> not allowed
  GGML_PREC_Q4     -> not allowed

Зворотний індекс: тип -> родина точності
  GGML_TYPE_BF16       GGML_PREC_BF16
  GGML_TYPE_F16        GGML_PREC_F16
  GGML_TYPE_F32        GGML_PREC_F32
  GGML_TYPE_MXFP4      GGML_PREC_Q4
  GGML_TYPE_NVFP4      GGML_PREC_Q4
  GGML_TYPE_Q4_0       GGML_PREC_Q4
  GGML_TYPE_Q4_1       GGML_PREC_Q4
  GGML_TYPE_Q4_K       GGML_PREC_Q4
  GGML_TYPE_Q8_0       GGML_PREC_Q8
  GGML_TYPE_Q8_1       GGML_PREC_Q8
  GGML_TYPE_Q8_K       GGML_PREC_Q8
```

Дві речі, які цей вивід доводять краще за будь-який переказ: ідентифікатор `GGML_TYPE_Q8_0`
відрізняється від `GGML_TYPE_Q8_K` і `GGML_TYPE_Q8_1` (усі три — 8-бітні, але різні формати), а
`MXFP4` і `NVFP4` стоять **в одному ряду** з `Q4_0`, `Q4_1` і `Q4_K`, тобто llama.cpp вважає їх
взаємозамінними за рівнем точності, але не за розкладкою.

**Типові помилки**

- **Скорочувати назви типів.** `Q8` не існує — є `GGML_TYPE_Q8_0`, `GGML_TYPE_Q8_1`, `GGML_TYPE_Q8_K`.
  Те саме з `Q4`: `Q4_0`, `Q4_1`, `Q4_K`.
- **Вважати `_K` синонімом «краще».** Із заголовка видно лише належність до тієї самої родини
  `GGML_PREC_Q4`. Різницю в похибці за цими джерелами підтвердити не вдалося.
- **Вимагати 4-бітного накопичувача.** `ggml_prec_set_acc(a, GGML_PREC_Q4)` — не помилка виклику, а
  свідомо заборонена комбінація: коментар каже «not allowed». Накопичувач має бути F32/BF16/F16.
- **Плутати версію файлу й версію формату квантизації.** Це дві різні константи: `GGML_FILE_VERSION`
  і `GGML_QNT_VERSION`.
- **Очікувати, що GGUF-файл квантований «одним типом».** Формат дозволяє різні типи для різних
  тензорів, тому «біт на параметр» усього файлу — усереднене число, а не властивість формату.
- **Читати біт-на-параметр із назви типу.** Це саме та помилка, якої цей розділ не робить: у наявних
  джерелах біт-на-параметр для окремих GGUF-типів відсутній.

**Альтернативи.** Для інференсу поза `llama.cpp`: safetensors + `bitsandbytes` (20.2) для швидкого
старту, GPTQ/AWQ (20.3) для PTQ-артефактів, TorchAO (20.4) для схем із float8. GGUF виграє там, де
потрібен один файл, що запускається без Python-стеку.

---

### 20.6 Порівняльна таблиця: пам'ять / швидкість / якість

**Що це.** Зведення п'яти інструментів за трьома осями, які реально впливають на рішення: скільки
пам'яті, наскільки швидко і що при цьому втрачається.

**Навіщо це знати.** Кожен інструмент оптимізує свою вісь, і таблиця показує, яку саме. Вибір
починається не з «що краще», а з «що саме у мене болить».

**Як працює під капотом.** Ось зведення за підтвердженими властивостями.

| | bitsandbytes | GPTQ (GPT-QModel) | AWQ | TorchAO | GGUF / llama.cpp |
|---|---|---|---|---|---|
| Коли застосовується | під час завантаження | після тренування (PTQ) | після тренування (PTQ) | під час завантаження або PTQ | після тренування, окремим тулчейном |
| Потрібне калібрування | ні | так, датасет (типово `c4`) | ні (квантує зовнішня бібліотека) | для частини схем | ні на етапі завантаження |
| Типові розрядності | 8 біт (LLM.int8()), 4 біти (NF4/FP4) | int4 (відновлення в fp16 на льоту) | 4 біти | float8, int8, int4 | 8-бітні (`Q8_*`) і 4-бітні (`Q4_*`, `MXFP4`, `NVFP4`) |
| Економія пам'яті | 2× на 8 біт, 4× на 4 біти | 4× (заявлено в документації) | 4 біти; числа VRAM — у бенчмарку нижче | залежить від схеми | залежить від суміші типів у файлі |
| Додаткова економія | nested quant: +0.4 біта/параметр | — | — | квантування KV-кешу, станів оптимізатора | — |
| Прискорення | 0.50.0: до 4× на 4-бітному інференсі, батчі 2–64, Turing→Blackwell | fused-ядро деквантування; Marlin-ядро для A100 | fused modules: ~2–3× на decode (бенчмарк нижче) | композиція з `torch.compile` | залежить від ядер рантайму |
| Тренування | лише додаткових параметрів (LoRA) | ні | ні | так, включно з QAT і float8-тренуванням | ні |
| Найважча пастка | 8- і 4-бітне тренування — лише для extra-параметрів | не сумісний зі старими чекпойнтами AutoGPTQ | `autoawq` відкочує Transformers до 4.47.1 | int4 завантажується лише на той самий пристрій | біт-на-параметр не визначається назвою типу |
| Мінімальні вимоги | PyTorch 2.4+, Python 3.10+ | GPT-QModel + Accelerate/Optimum | autoawq / llm-awq | torchao ≥ 0.15.0 | рантайм `llama.cpp` |

#### Реальні числа: fused modules в AWQ

Документація AWQ наводить бенчмарк `TheBloke/Mistral-7B-OpenOrca-AWQ` за `batch_size=1` для двох
конфігурацій. Ось ці таблиці, розібрані **програмно** з `research/hf5_tfdoc_quantization_awq.txt` —
разом із обчисленим відношенням decode-швидкості:

```python
import pathlib
import re

AWQ = pathlib.Path("research/hf5_tfdoc_quantization_awq.txt")
lines = AWQ.read_text(encoding="utf-8").splitlines()


def parse_tables(src_lines):
    """Розбір markdown-таблиць разом із підписами <figcaption>."""
    tables, header, rows, caption = [], None, [], ""
    for raw in src_lines:
        line = raw.strip()
        if line.startswith("<figcaption"):
            caption = re.sub(r"<[^>]+>", "", line).strip()
            continue
        if line.startswith("|"):
            cells = [c.strip() for c in line.strip("|").split("|")]
            if set("".join(cells)) <= set("-: "):
                continue          # рядок-розділювач
            if header is None:
                header = cells
            else:
                rows.append(cells)
            continue
        if header is not None and rows:
            tables.append((caption, header, rows))
            header, rows = None, []
    if header is not None and rows:
        tables.append((caption, header, rows))
    return tables


tables = parse_tables(lines)
print(f"таблиць знайдено: {len(tables)}")
for caption, header, rows in tables:
    print(f"  - {caption!r}: {len(rows)} рядків, колонок {len(header)}")

# Порівнюємо decode tokens/s між таблицями 'Unfused module' і 'Fused module'.
(_, _, unfused), (_, _, fused) = tables[0], tables[1]
print()
print(f"{'Prefill':>8}{'Decode':>8}{'unfused':>10}{'fused':>10}{'прискорення':>14}{'VRAM unfused':>15}{'VRAM fused':>13}")
print("-" * 78)
for a, b in zip(unfused, fused):
    prefill, decode = a[1], a[2]
    u, f = float(a[4]), float(b[4])
    print(f"{prefill:>8}{decode:>8}{u:>10.2f}{f:>10.2f}{f / u:>13.2f}x{a[5]:>15}{b[5]:>13}")
```

**Фактичний вивід**

```text
таблиць знайдено: 3
  - 'Unfused module': 7 рядків, колонок 6
  - 'Fused module': 7 рядків, колонок 6
  - 'generate throughput/batch size': 3 рядків, колонок 2

 Prefill  Decode   unfused     fused   прискорення   VRAM unfused   VRAM fused
------------------------------------------------------------------------------
      32      32     38.45     80.26         2.09x4.50 GB (5.68%)4.00 GB (5.05%)
      64      64     31.66    106.26         3.36x4.50 GB (5.68%)4.00 GB (5.05%)
     128     128     31.63    105.63         3.34x4.50 GB (5.68%)4.00 GB (5.06%)
     256     256     38.17     85.75         2.25x4.50 GB (5.68%)4.01 GB (5.06%)
     512     512     31.68     97.70         3.08x4.59 GB (5.80%)4.11 GB (5.19%)
    1024    1024     36.80     87.73         2.38x4.81 GB (6.07%)4.41 GB (5.57%)
    2048    2048     35.27     89.47         2.54x5.73 GB (7.23%)5.57 GB (7.04%)
```

Три висновки з цих чисел:

1. **Прискорення від fused modules — від 2.09× до 3.36× на decode** за того самого батчу. Це
   найбільший підтверджений виграш у розділі, і він не потребує ні нової розрядності, ні нового
   заліза.
2. **Prefill виграє менше й нерівномірно** (81.49 проти 60.10 на 32/32, але 2848.9 проти 3184.74 на
   512/512 — тобто на довгому prefill fused-варіант **повільніший**). Оптимізація спрямована саме на
   декодування.
3. **Fused-конфігурація ще й ощадливіша за VRAM**: 4.00 GB проти 4.50 GB, а на 2048/2048 — 5.57 GB
   проти 5.73 GB.

**Типові помилки**

- **Порівнювати методи за різних умов.** Числа вище отримані за `batch_size=1`; за батчу 64
  співвідношення інші, а `bitsandbytes` 0.50.0 обіцяє до 4× саме на батчах 2–64. Порівнюйте за того
  самого батчу й тієї самої довжини.
- **Читати «4×» як «4× швидше».** Документація `bitsandbytes` говорить про **пам'ять** (удвічі й
  у 4 рази), а прискорення — окреме твердження з окремими умовами.
- **Ігнорувати, що VRAM у бенчмарку — це 4–6% від 80 GB.** Тобто модель займає маленьку частину;
  відносні відсотки тут не переносяться на більші моделі напряму.
- **Змішувати «менше пам'яті» і «менше часу».** Weight-only-схема зменшує обсяг, який треба прочитати
  з пам'яті, але деквантування теж коштує часу. Без fused-ядра виграш може бути нульовим.
- **Вважати якість виміряною.** У цих таблицях **немає** метрик якості — лише токени за секунду й
  пам'ять. Якість міряють окремо (розділ 24).

**Альтернативи.** Якщо мета — максимальна якість за прийнятної пам'яті, беруть 8-бітні схеми
(`LLM.int8()`, `Q8_*`, `Int8WeightOnlyConfig`) і перевіряють, чи вміщається модель. Якщо мета —
максимальна швидкість за фіксованої пам'яті, беруть 4-бітні схеми з fused-ядрами. Якщо мета — один
файл без Python-стеку, беруть GGUF.

---

### 20.7 Коли квантизація не потрібна

**Що це.** Список ситуацій, у яких квантування додає складність, ризик і час, не даючи нічого
істотного.

**Навіщо це знати.** Квантування — це компроміс, а не покращення. Воно необоротно втрачає
інформацію про ваги, додає крок збірки артефакту й обмежує сумісність заліза. Нижче — критерії, за
якими від нього відмовляються.

**Як працює під капотом.** Рішення зводиться до одного питання: чи є дефіцит, який квантування
закриває. Нижче — код, який це питання формалізує на реальних даних моделі.

#### Робочий приклад: чи вміщається модель і чи потрібне квантування взагалі

Метадані взято з `research/det_qwen38.json` — це реальний запис моделі з Hub із полем
`safetensors.parameters`, де зазначено кількість параметрів у BF16.

```python
import json
import math
import pathlib

GIB = 1024 ** 3
meta = json.loads(pathlib.Path("research/det_qwen38.json").read_text(encoding="utf-8"))

n_params = meta["safetensors"]["parameters"]["BF16"]
stored = meta["usedStorage"]
print(f"модель: {meta['modelId']}, остання зміна: {meta['lastModified']}")
print(f"параметрів (BF16): {n_params:,}")
print(f"займає на диску:   {stored:,} байт = {stored / GIB:.2f} GiB")
print(f"байт на параметр:  {stored / n_params:.4f}   (теоретично 2.0 для BF16)")
print()

# Бюджети задаєте ви самі. 80 GiB узято з джерел (NVIDIA A100 у документації GPTQ);
# решта — довільні приклади, щоб показати, як змінюється рішення.
BUDGETS = {"A100-80GB (з джерел)": 80, "вужчий бюджет": 48, "ще вужчий бюджет": 24}
BIT_WIDTHS = {"bf16": 16, "int8": 8, "int4 (NF4/GPTQ/AWQ)": 4}

print(f"{'бюджет':22}{'bf16':>22}{'int8':>22}{'int4 (NF4/GPTQ/AWQ)':>26}")
print("-" * 92)
for label, budget in BUDGETS.items():
    cells = []
    for bits in BIT_WIDTHS.values():
        need = n_params * bits / 8 / GIB
        ok = "OK" if need <= budget else f"не вміщається (x{need / budget:.2f})"
        cells.append(f"{need:8.2f} GiB {ok}")
    row = f"{label:22}{cells[0]:>22}{cells[1]:>22}{cells[2]:>26}"
    print(row)

print()
print("Скільки карт по 80 GiB треба лише під ваги (без KV-кешу й активацій):")
for label, bits in BIT_WIDTHS.items():
    need = n_params * bits / 8 / GIB
    print(f"  {label:20} {need:8.2f} GiB -> {math.ceil(need / 80)} x 80 GiB")
```

**Фактичний вивід**

```text
модель: Qwen/Qwen3.8-27B, остання зміна: 2026-08-14T15:00:01.000Z
параметрів (BF16): 27,781,427,952
займає на диску:   55,623,336,488 байт = 51.80 GiB
байт на параметр:  2.0022   (теоретично 2.0 для BF16)

бюджет                                  bf16                  int8       int4 (NF4/GPTQ/AWQ)
--------------------------------------------------------------------------------------------
A100-80GB (з джерел)            51.75 GiB OK          25.87 GiB OK              12.94 GiB OK
вужчий бюджет            51.75 GiB не вміщається (x1.08)          25.87 GiB OK              12.94 GiB OK
ще вужчий бюджет         51.75 GiB не вміщається (x2.16)   25.87 GiB не вміщається (x1.08)              12.94 GiB OK

Скільки карт по 80 GiB треба лише під ваги (без KV-кешу й активацій):
  bf16                    51.75 GiB -> 1 x 80 GiB
  int8                    25.87 GiB -> 1 x 80 GiB
  int4 (NF4/GPTQ/AWQ)     12.94 GiB -> 1 x 80 GiB
```

Цей вивід дає одразу три критерії відмови від квантування:

1. **Модель і так вміщається в 80 GiB у bf16** (51.75 GiB). Квантування тут нічого не розблоковує —
   воно лише звільняє запас під KV-кеш і батч. Якщо запас уже достатній, вигода нульова.
2. **Байт на параметр — 2.0022**, тобто метадані збігаються з арифметикою. Це найдешевший спосіб
   перевірити, чи не збрехав чекпойнт: поділіть `usedStorage` на кількість параметрів.
3. **Кількість карт не змінюється.** На всіх трьох розрядностях потрібна одна карта по 80 GiB.
   Квантування починає змінювати топологію лише тоді, коли перетинає межу кількості карт (для
   бюджету 48 GiB це вже видно: bf16 не вміщається, int8 і int4 — так).

#### Перелік ситуацій, коли квантувати не варто

- **Модель уміщається в пам'ять із запасом на KV-кеш і батч.** Квантування не додає нічого, крім
  ризику втрати якості.
- **Ціль — максимальна якість, і ви не готові її міряти.** Документація `bitsandbytes` попереджає,
  що `llm_int8_threshold=0.0` «значно прискорює інференс ціною можливої втрати точності». Якщо
  евалюації немає, цю втрату ви не побачите.
- **Потрібне доучування всієї моделі, а не адаптерів.** 8- і 4-бітне тренування підтримане **лише**
  для додаткових параметрів.
- **Потрібна переносимість int4-артефакту між пристроями.** У TorchAO int4-модель завантажується
  лише там, де її квантували.
- **У вас уже є робочий стек на іншій осі.** Наприклад, ви виграєте більше від prompt caching
  (розділ 9), батч-обробки (розділ 10) або скорочення контексту (розділ 16), ніж від 4 біт.
- **Ви плануєте інференс через API.** Квантування — інструмент локального розгортання; у хмарному
  API ці рішення ухвалює провайдер.
- **Цільове залізо не покрите.** QLoRA на Intel Gaudi підтримано частково, 8-бітні оптимізатори там
  не підтримані взагалі; на macOS через MPS 8-бітні оптимізатори ще заплановані.
- **Вибір інструмента ще не зроблено, а артефакт уже потрібен.** Квантування від GPTQ вимагає
  калібрувального датасету й може зайняти години (близько 4 годин для 175B-моделі на A100); для
  багатьох задач швидший шлях — знайти готовий квантований чекпойнт на Hub.

**Типові помилки**

- **Квантувати «про запас».** Витрачений час і ризик якості без потреби. Спершу порахуйте, чи є
  дефіцит пам'яті (код вище).
- **Плутати економію місця на диску з економією VRAM.** Це різні величини; до того ж під час
  завантаження модель може тимчасово займати більше, ніж у сталому стані.
- **Забути, що GPTQ-квантування потребує місця під калібрувальні активації.** Документація радить
  обмежувати пам'ять параметром `max_memory`, а disk offloading не підтримано зовсім.
- **Очікувати, що квантована модель поводиться ідентично.** Це інший числовий артефакт; повторні
  прогони можуть давати інші відповіді, і саме тому порівняння роблять з `temperature=0` і на
  фіксованому наборі завдань.
- **Ставити квантування перед оптимізацією запиту.** Якщо витрати визначає ціна за токен, а не
  власне залізо, квантування не змінить рахунок взагалі.

**Альтернативи.** Дистиляція в меншу модель; вибір іншої моделі (розділ 6); MoE-архітектура; офлоад
на CPU (із нагадуванням, що 8-бітні ваги на CPU зберігаються у float32); інференс через провайдера.

---

**Джерела**

- [Transformers — Quantization: bitsandbytes](https://raw.githubusercontent.com/huggingface/transformers/main/docs/source/en/quantization/bitsandbytes.md) — `research/hf5_tfdoc_quantization_bitsandbytes.txt`
- [Transformers — Quantization: GPTQ](https://raw.githubusercontent.com/huggingface/transformers/main/docs/source/en/quantization/gptq.md) — `research/hf5_tfdoc_quantization_gptq.txt`
- [Transformers — Quantization: AWQ](https://raw.githubusercontent.com/huggingface/transformers/main/docs/source/en/quantization/awq.md) — `research/hf5_tfdoc_quantization_awq.txt`
- [Transformers — Quantization: torchao](https://raw.githubusercontent.com/huggingface/transformers/main/docs/source/en/quantization/torchao.md) — `research/hf5_tfdoc_quantization_torchao.txt`
- [bitsandbytes — README](https://raw.githubusercontent.com/bitsandbytes-foundation/bitsandbytes/main/README.md) — `research/bnb_readme.txt`
- [bitsandbytes 0.50.0 — release notes (2026-07-25)](https://github.com/bitsandbytes-foundation/bitsandbytes/releases/tag/0.50.0) — `research/hf5_bnb050.md`
- [llama.cpp — `ggml/include/ggml.h`](https://raw.githubusercontent.com/ggml-org/llama.cpp/master/ggml/include/ggml.h) — `research/quant/ggml_h.txt`
- [Transformers — Building a GPU workstation](https://raw.githubusercontent.com/huggingface/transformers/main/docs/source/en/perf_hardware.md) — `research/hf5_tfdoc_perf_hardware.txt`
- [Transformers — Paged attention](https://raw.githubusercontent.com/huggingface/transformers/main/docs/source/en/paged_attention.md) — `research/hf5_tfdoc_paged_attention.txt`
- [Transformers — v5 migration guide (розділ «Quantization changes»)](https://raw.githubusercontent.com/huggingface/transformers/main/docs/source/en/migration.md) — `research/tf_v5_migration.txt`
- [Transformers v5 — release blog](https://huggingface.co/blog/transformers-v5) — `research/hf5_tf5_blog.txt`
- [Qwen/Qwen3.8-27B — метадані Hub](https://huggingface.co/Qwen/Qwen3.8-27B) — `research/det_qwen38.json`
