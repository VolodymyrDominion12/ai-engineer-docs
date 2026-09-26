"""Ноутбук 20 — «Квантування і оптимізація інференсу».

Розділ довідника: sections/20-kvantuvannya.md
Працює без API-ключів. Реальна квантизація (bitsandbytes/TorchAO/GPTQ/AWQ) потребує
torch + відповідної бібліотеки та GPU — ці клітинки захищені try/except, а всі
розрахунки пам'яті, розбір типів GGUF і симуляція похибки працюють на чистому
Python + numpy без GPU.

Усі назви параметрів, типів і числа в цьому ноутбуку взяті з файлів research/
(див. sections/20-kvantuvannya.md, блок «Джерела»).
"""

from nbkit import SETUP_CELL, VERSION_CELL, code, md

FILENAME = "20-kvantuvannya.ipynb"
TITLE = "20. Квантування і оптимізація інференсу"

CELLS = [
    md(
        """
# 20. Квантування і оптимізація інференсу

**Розділ довідника:** [`sections/20-kvantuvannya.md`](../sections/20-kvantuvannya.md)

**Потрібно: torch + bitsandbytes для реальної квантизації; GPU обов'язковий. Розрахунки працюють без GPU**

**Що ви зробите:**

1. Порахуєте, скільки гігабайт займають ваги моделі за кожної розрядності — чиста арифметика.
2. Побачите на `numpy`, чому квантування **без блоків** знищує 4-бітну матрицю, а з блоками — ні.
3. Зберете довідник параметрів `BitsAndBytesConfig`, `GPTQConfig`, `AwqConfig`, `TorchAoConfig`.
4. **Витягнете точні ідентифікатори типів квантизації GGUF програмно** з `research/quant/ggml_h.txt` —
   щоб не покладатися на пам'ять.
5. Розберете реальний бенчмарк fused modules AWQ із документації та порахуєте прискорення.
6. Перевірите за метаданими Hub, чи потрібне квантування для конкретної моделі взагалі.

> Усі факти — з файлів `research/`. Там, де джерела не дають відповіді, це позначено прямо.
"""
    ),
    md("## Налаштування"),
    code(SETUP_CELL),
    code(VERSION_CELL),

    # ── 20.1 ─────────────────────────────────────────────────────────────
    md(
        """
## 20.1 Скільки пам'яті займають ваги

Почніть із арифметики, а не з бібліотек. Кількість байтів під ваги = `параметри × біт / 8`.
Документація `bitsandbytes` формулює виграш як «удвічі менше» для 8 біт і «у 4 рази менше» для
4 біт — перевірмо, звідки беруться саме такі множники.
"""
    ),
    code(
        '''
# Біт на параметр. 32 і 16 — стандартні dtype; 8 і 4 — те, про що говорить
# документація bitsandbytes («вдвічі» та «у 4 рази»).
NB20_GIB = 1024 ** 3
NB20_BITS = {
    "fp32": 32,
    "bf16/fp16": 16,
    "int8 / Q8_0": 8,
    "int4 / Q4_0 / NF4": 4,
}
NB20_MODELS = {
    "Llama-3.2-3B": 3.2e9,
    "Llama-3.1-8B": 8.0e9,
    "13B-клас": 13.0e9,
    "70B-клас": 70.0e9,
    "MoE-клас 671B (V3/R1)": 671.0e9,
}


def nb20_weights_gib(n_params, bits):
    """Гібібайти під ваги: params * bits / 8 / 1024**3."""
    return n_params * bits / 8 / NB20_GIB


nb20_header = f"{'модель':28}{'параметрів':>12} " + " ".join(f"{k:>19}" for k in NB20_BITS)
print(nb20_header)
print("-" * len(nb20_header))
for nb20_name, nb20_n in NB20_MODELS.items():
    nb20_row = f"{nb20_name:28}{nb20_n / 1e9:>10.1f} B "
    nb20_row += " ".join(f"{nb20_weights_gib(nb20_n, b):>15.2f} GiB" for b in NB20_BITS.values())
    print(nb20_row)
'''
    ),
    code(
        '''
# Перевірка тверджень «удвічі» та «у 4 рази» з документації: у скільки разів
# менше пам'яті потрібно проти bf16.
NB20_BASE = 16
print(f"{'схема':24}{'біт':>5}{'байт/параметр':>15}{'економія проти bf16':>22}")
print("-" * 66)
for nb20_label, nb20_bits in NB20_BITS.items():
    nb20_ratio = NB20_BASE / nb20_bits
    print(f"{nb20_label:24}{nb20_bits:>5}{nb20_bits / 8:>15.2f}{nb20_ratio:>21.2f}x")
'''
    ),
    md(
        """
Рядки `int8 → 2.00x` і `int4 → 4.00x` — це рівно те, що обіцяє документація `bitsandbytes`
(«halves the memory-usage» і «reduces your memory-usage by 4x»). Обидва твердження — про **пам'ять**,
не про швидкість.
"""
    ),

    # ── 20.1: блочне квантування ─────────────────────────────────────────
    md(
        """
### Чому потрібні блоки: симуляція похибки на numpy

Нижче — механіка квантування, зменшена до 30 рядків: симетрична цілочисельна схема
`q = round(x / scale)`, `x' = q * scale`. Порівнюються два режими — один масштаб на весь тензор і
один масштаб на блок із 128 значень (саме `group_size=128` фігурує в прикладах документації
TorchAO і в `quantization_config` AWQ-моделей).

Це не бібліотечне квантування, а його ідея. Результат усе одно показує головне.
"""
    ),
    code(
        '''
import numpy as np

NB20_ROWS, NB20_COLS = 768, 768
NB20_GROUP = 128  # розмір блоку з документації TorchAO (group_size=128)


def nb20_make_weights(seed, outlier_scale):
    """Матриця ваг із кількома викидами — як у справжньому шарі."""
    nb20_r = np.random.default_rng(seed)
    nb20_w = nb20_r.normal(0.0, 0.02, size=(NB20_ROWS, NB20_COLS)).astype(np.float32)
    nb20_w[0, :8] *= outlier_scale
    return nb20_w


def nb20_quant_symmetric(w, bits, block):
    """Симетричне квантування: block=None -> один масштаб на тензор."""
    qmax = 2 ** (bits - 1) - 1
    if block is None:
        scale = max(float(np.abs(w).max()) / qmax, 1e-12)
        return np.round(w / scale).clip(-qmax - 1, qmax) * scale
    flat = w.reshape(-1)
    pad = (-flat.size) % block
    flat = np.concatenate([flat, np.zeros(pad, dtype=np.float32)])
    grid = flat.reshape(-1, block)
    scales = np.maximum(np.abs(grid).max(axis=1, keepdims=True) / qmax, 1e-12)
    restored = np.round(grid / scales).clip(-qmax - 1, qmax) * scales
    return restored.reshape(-1)[: w.size].reshape(w.shape)


NB20_W = nb20_make_weights(seed=7, outlier_scale=40.0)
print(f"тензор: {NB20_W.shape}, викидів у рядку 0: 8, максимум |w| = {np.abs(NB20_W).max():.4f}")
print()
print(f"{'біти':>5} {'режим':>22} {'відносна похибка':>18} {'макс. абс. помилка':>20}")
print("-" * 68)
for nb20_bits in (8, 4, 3, 2):
    for nb20_mode, nb20_block in (("один масштаб на тензор", None),
                                  (f"масштаб на блок {NB20_GROUP}", NB20_GROUP)):
        nb20_hat = nb20_quant_symmetric(NB20_W, nb20_bits, nb20_block)
        nb20_err = float(np.linalg.norm(NB20_W - nb20_hat) / np.linalg.norm(NB20_W))
        nb20_max = float(np.abs(NB20_W - nb20_hat).max())
        print(f"{nb20_bits:>5} {nb20_mode:>22} {nb20_err:>17.4%} {nb20_max:>20.6f}")
'''
    ),
    md(
        """
Три висновки:

1. **Один масштаб на тензор ламається вже на 4 бітах** — 99.45% відносної похибки означає, що вісім
   викидів задали масштаб, а решта значень округлилися до нуля. Блочне квантування — не оптимізація, а
   необхідна умова.
2. **Блоки дають 8.4× виграшу на 4 бітах** (11.77% проти 99.45%) і 18× на 8 бітах.
3. **Максимальна абсолютна помилка майже не змінюється** (0.0766 проти 0.0673 на 4 бітах): блоки
   рятують більшість значень, але не врятують сам викид.

3 і 2 біти без калібрування непридатні навіть із блоками — саме тому справжні 3- і 2-бітні формати
будують на складніших схемах, а не на рівномірній сітці.
"""
    ),

    # ── 20.2 ─────────────────────────────────────────────────────────────
    md(
        """
## 20.2 bitsandbytes: 8-bit і 4-bit (NF4)

Далі — реальна квантизація. Вона потребує `torch` + `bitsandbytes` і GPU. Клітинка нижче спершу
перевіряє, що взагалі встановлено, і не падає, якщо нічого немає.
"""
    ),
    code(
        '''
# Перевірка доступності реального стеку. Без GPU/бібліотек ноутбук далі працює.
import importlib

NB20_ENV = {}
for nb20_mod in ("torch", "bitsandbytes", "transformers", "torchao"):
    try:
        NB20_ENV[nb20_mod] = getattr(importlib.import_module(nb20_mod), "__version__", "?")
    except ImportError:
        NB20_ENV[nb20_mod] = None

for nb20_mod, nb20_ver in NB20_ENV.items():
    print(f"{nb20_mod:14} {nb20_ver if nb20_ver else 'НЕ ВСТАНОВЛЕНО'}")

try:
    import torch as nb20_torch
    print(f"{'cuda':14} {nb20_torch.cuda.is_available()}")
except ImportError:
    print(f"{'cuda':14} немає torch -> перевірити неможливо")
'''
    ),
    code(
        '''
# Реальна 4-бітна квантизація. Запуститься лише там, де є весь стек і GPU.
# У середовищі без GPU ця клітинка просто пояснює, чого не хватає.
NB20_BNB_OK = all(NB20_ENV.get(m) for m in ("torch", "bitsandbytes", "transformers"))

if not NB20_BNB_OK:
    print("Крок пропущено: немає torch + bitsandbytes + transformers.")
    print()
    print("Що робить код нижче (назви параметрів — з документації Transformers):")
    print()
    print("    cfg = BitsAndBytesConfig(")
    print("        load_in_4bit=True,")
    print('        bnb_4bit_quant_type="nf4",')
    print("        bnb_4bit_compute_dtype=torch.bfloat16,")
    print("        bnb_4bit_use_double_quant=True,")
    print("    )")
    print('    model = AutoModelForCausalLM.from_pretrained(')
    print('        "bigscience/bloom-1b7", device_map="auto", quantization_config=cfg)')
    print("    model.get_memory_footprint()")
else:
    from transformers import BitsAndBytesConfig
    try:
        nb20_cfg4 = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_quant_type="nf4",
            bnb_4bit_compute_dtype=nb20_torch.bfloat16,
            bnb_4bit_use_double_quant=True,
        )
        print("BitsAndBytesConfig(4-bit, NF4) створено")
        nb20_dict = nb20_cfg4.to_dict()
        for nb20_k in sorted(nb20_dict):
            print(f"  {nb20_k:26} {nb20_dict[nb20_k]}")
    except Exception as nb20_exc:
        print("Не вдалося зібрати конфігурацію:", type(nb20_exc).__name__, nb20_exc)
'''
    ),
    md(
        """
**Таблиця параметрів `BitsAndBytesConfig` (усе — з документації Transformers).**

| Параметр | Призначення |
|---|---|
| `load_in_8bit=True` | 8-бітне квантування (LLM.int8()) |
| `load_in_4bit=True` | 4-бітне квантування (QLoRA) |
| `llm_int8_threshold` | поріг викиду; типове значення **6**, `0.0` дає швидкість ціною точності |
| `llm_int8_skip_modules` | модулі, які **не** квантуються (документація: `["lm_head"]` для Jukebox) |
| `llm_int8_enable_fp32_cpu_offload` | офлоад 8-бітних ваг на CPU; на CPU вони лежать у **float32** |
| `bnb_4bit_quant_type` | тип квантування, для тренування 4-бітних базових моделей — `"nf4"` |
| `bnb_4bit_compute_dtype` | тип обчислень (документація радить `torch.bfloat16` замість float32) |
| `bnb_4bit_use_double_quant` | nested quantization: **+0.4 біта/параметр** економії |
| `device_map` | розподіл шарів по пристроях; для тренування `device_map="auto"` використовувати не можна |

**Вимоги до заліза** (з документації HF): 8-бітні оптимізатори — NVIDIA Pascal або новіші;
LLM.int8() — NVIDIA Turing (RTX 20X0, T4) або новіші; NF4/FP4 — Pascal або новіші.
За README бібліотеки: Python 3.10+, PyTorch 2.4+, Linux glibc ≥ 2.24 / Windows 11 / macOS 14+;
CUDA 11.8–13.0; CPU x86-64 мінімум AVX2.
"""
    ),
    code(
        '''
# Скільки це в гігабайтах для реальної моделі. Кількість параметрів узято з метаданих
# Hub (research/det_qwen38.json, поле safetensors.parameters.BF16) — див. 20.7.
NB20_CASE = 27_781_427_952
print(f"модель на {NB20_CASE / 1e9:.2f} млрд параметрів")
print()
print(f"{'схема':34}{'біт/параметр':>15}{'GiB під ваги':>16}")
print("-" * 65)
for nb20_label, nb20_bits in NB20_BITS.items():
    print(f"{nb20_label:34}{nb20_bits:>15}{nb20_weights_gib(NB20_CASE, nb20_bits):>16.2f}")

# Nested quantization додає 0.4 біта/параметр економії (з документації bitsandbytes)
nb20_nested = NB20_CASE * (4 - 0.4) / 8 / NB20_GIB
print()
print(f"NF4 + nested quantization (3.6 біта/параметр): {nb20_nested:.2f} GiB")
print(f"виграш проти NF4 без nested:                  "
      f"{nb20_weights_gib(NB20_CASE, 4) - nb20_nested:.2f} GiB")
'''
    ),

    # ── 20.3 ─────────────────────────────────────────────────────────────
    md(
        """
## 20.3 GPTQ і AWQ: квантування після тренування

Обидва — PTQ. GPTQ квантує кожен рядок матриці ваг незалежно, шукаючи версію, що мінімізує помилку;
ваги зберігаються в int4 і **відновлюються у fp16 на льоту** в об'єднаному ядрі. AWQ зберігає
невелику частку ваг, важливих для якості.

Код реального квантування вимагає GPU й окремих бібліотек, тому він під `try/except`. Зате нижче є
те, що працює завжди: **розбір реального бенчмарку з документації**.
"""
    ),
    code(
        '''
# ── Реальний код (потрібні GPU + gptqmodel / autoawq) ───────────────────
# Встановлення (з документації):
#   pip install --upgrade accelerate optimum transformers
#   pip install gptqmodel --no-build-isolation      # GPTQ: AutoGPTQ більше НЕ підтримується
#   pip install autoawq                             # AWQ: увага — відкочує Transformers до 4.47.1

print("Перевірка доступності бекендів:")
for nb20_pkg in ("gptqmodel", "autoawq"):
    try:
        nb20_m = importlib.import_module(nb20_pkg)
        print(f"  {nb20_pkg:12} {getattr(nb20_m, '__version__', '?')}")
    except ImportError:
        print(f"  {nb20_pkg:12} НЕ ВСТАНОВЛЕНО (потрібен GPU для роботи)")

if NB20_ENV.get("transformers"):
    try:
        from transformers import AwqConfig, GPTQConfig
        print()
        print("AwqConfig(bits=4, do_fuse=True) ->", AwqConfig(bits=4, do_fuse=True).to_dict())
        print("GPTQConfig(bits=4, backend='marlin') ->",
              GPTQConfig(bits=4, backend="marlin").to_dict())
    except Exception as nb20_exc:
        print("Не вдалося зібрати конфігурації:", type(nb20_exc).__name__, nb20_exc)
else:
    print()
    print("transformers не встановлено, тому конфігурації не збираються.")
    print("З документації відомі такі параметри:")
    print("  GPTQConfig(bits=4, dataset='c4', tokenizer=..., backend='marlin')")
    print("  AwqConfig(bits=4, fuse_max_seq_len=512, do_fuse=True)")
'''
    ),
    md(
        """
### Реальний бенчмарк AWQ: fused modules проти звичайних

Документація AWQ наводить таблиці для `TheBloke/Mistral-7B-OpenOrca-AWQ` за `batch_size=1`. Розберімо
їх **програмно** з файлу `research/hf5_tfdoc_quantization_awq.txt` — щоб числа не залежали від того,
як я їх переписав.
"""
    ),
    code(
        '''
import pathlib
import re

NB20_AWQ = pathlib.Path(ROOT) / "research" / "hf5_tfdoc_quantization_awq.txt"
NB20_AWQ_LINES = NB20_AWQ.read_text(encoding="utf-8").splitlines()


def nb20_parse_tables(src_lines):
    """Розбір markdown-таблиць разом із підписами <figcaption>."""
    nb_tables, nb_header, nb_rows, nb_caption = [], None, [], ""
    for nb_raw in src_lines:
        nb_line = nb_raw.strip()
        if nb_line.startswith("<figcaption"):
            nb_caption = re.sub(r"<[^>]+>", "", nb_line).strip()
            continue
        if nb_line.startswith("|"):
            nb_cells = [c.strip() for c in nb_line.strip("|").split("|")]
            if set("".join(nb_cells)) <= set("-: "):
                continue  # рядок-розділювач
            if nb_header is None:
                nb_header = nb_cells
            else:
                nb_rows.append(nb_cells)
            continue
        if nb_header is not None and nb_rows:
            nb_tables.append((nb_caption, nb_header, nb_rows))
            nb_header, nb_rows = None, []
    if nb_header is not None and nb_rows:
        nb_tables.append((nb_caption, nb_header, nb_rows))
    return nb_tables


NB20_TABLES = nb20_parse_tables(NB20_AWQ_LINES)
print(f"джерело: {NB20_AWQ.name} ({len(NB20_AWQ_LINES)} рядків)")
print(f"таблиць знайдено: {len(NB20_TABLES)}")
for nb20_caption, nb20_head, nb20_rows in NB20_TABLES:
    print(f"  - {nb20_caption!r}: {len(nb20_rows)} рядків, колонок {len(nb20_head)}")
'''
    ),
    code(
        '''
# Порівнюємо decode tokens/s між таблицями 'Unfused module' і 'Fused module'.
NB20_UNFUSED = NB20_TABLES[0][2]
NB20_FUSED = NB20_TABLES[1][2]

print(f"{'Prefill':>8}{'Decode':>8}{'unfused':>10}{'fused':>10}{'прискорення':>14}"
      f"{'VRAM unfused':>15}{'VRAM fused':>13}")
print("-" * 78)
NB20_SPEEDUPS = []
for nb20_a, nb20_b in zip(NB20_UNFUSED, NB20_FUSED):
    nb20_u, nb20_f = float(nb20_a[4]), float(nb20_b[4])
    NB20_SPEEDUPS.append(nb20_f / nb20_u)
    print(f"{nb20_a[1]:>8}{nb20_a[2]:>8}{nb20_u:>10.2f}{nb20_f:>10.2f}"
          f"{nb20_f / nb20_u:>13.2f}x{nb20_a[5]:>15}{nb20_b[5]:>13}")

print()
print(f"прискорення decode: від {min(NB20_SPEEDUPS):.2f}x до {max(NB20_SPEEDUPS):.2f}x")
print(f"середнє:            {sum(NB20_SPEEDUPS) / len(NB20_SPEEDUPS):.2f}x")
'''
    ),
    md(
        """
Fused modules дають від 2.09× до 3.36× на декодуванні за того самого батчу — і ще й трохи менше VRAM
(4.00 GB проти 4.50 GB). Prefill виграє нерівномірно: на 512/512 fused-варіант навіть повільніший
(2848.9 проти 3184.74 ток/с). Обмеження з документації: **fused modules не можна поєднувати з
FlashAttention2**.
"""
    ),

    # ── 20.4 ─────────────────────────────────────────────────────────────
    md(
        """
## 20.4 TorchAO

`torchao` — бібліотека оптимізації архітектур PyTorch: власні типи даних, квантизація,
розрідженість, композиція з `torch.compile`. Ключове для практики: **потрібен `torchao >= 0.15.0`**, і
рядковий API (`TorchAoConfig("int4_weight_only")`) **видалено** — тепер передають об'єкти-конфігурації.
"""
    ),
    code(
        '''
# Довідник конфігурацій TorchAO за залізом (з документації). Дані, а не імпорт:
# працює без torchao.
NB20_TORCHAO = [
    ("H100", "Float8DynamicActivationFloat8WeightConfig", "float8, активації динамічно"),
    ("H100", "Float8WeightOnlyConfig", "float8, лише ваги"),
    ("H100", "GemliteUIntXWeightOnlyConfig(group_size=128)", "int4, gemlite під батч N"),
    ("A100", "Int8DynamicActivationInt8WeightConfig", "int8, активації динамічно"),
    ("A100", "Int8WeightOnlyConfig", "int8, лише ваги"),
    ("A100", "GemliteUIntXWeightOnlyConfig(group_size=128)", "int4, батч N"),
    ("A100", "Int4WeightOnlyConfig(group_size=128, use_hqq=True)", "int4, батч 1, tinygemm"),
    ("Intel XPU", "Int4WeightOnlyConfig(group_size=128, int4_packing_format='plain_int32')",
     "int4 для XPU"),
    ("CPU", "PrototypeInt4WeightOnlyConfig(group_size=128, "
            "int4_choose_qparams_algorithm='tinygemm')", "int4 для CPU, torchao >= 0.15.0"),
]

print(f"{'залізо':12}конфігурація TorchAO")
print("-" * 112)
for nb20_hw, nb20_cfgname, nb20_note in NB20_TORCHAO:
    print(f"{nb20_hw:12}{nb20_cfgname}")
    print(f"{'':12}-> {nb20_note}")

print()
print("Сумісність (з документації): CUDA cu118 / cu126 / cu128; XPU на pytorch2.8; "
      "CPU через device_map='cpu'")
'''
    ),
    code(
        '''
# Якщо torchao встановлено — перевіряємо, які саме конфігурації є в цій версії.
if not NB20_ENV.get("torchao"):
    print("torchao НЕ ВСТАНОВЛЕНО — перевірку списку конфігурацій пропущено.")
    print("Установка з документації: pip install --upgrade torchao transformers")
else:
    print(f"torchao {NB20_ENV['torchao']}")
    try:
        import torchao.quantization as nb20_taq
        nb20_wanted = [
            "Float8DynamicActivationFloat8WeightConfig",
            "Float8WeightOnlyConfig",
            "Int8DynamicActivationInt8WeightConfig",
            "Int8WeightOnlyConfig",
            "Int4WeightOnlyConfig",
            "Int8DynamicActivationInt4WeightConfig",
            "GemliteUIntXWeightOnlyConfig",
            "IntxWeightOnlyConfig",
            "FqnToConfig",
        ]
        for nb20_name2 in nb20_wanted:
            print(f"  {nb20_name2:48} {'є' if hasattr(nb20_taq, nb20_name2) else 'НЕМАЄ'}")
    except Exception as nb20_exc:
        print("Помилка імпорту torchao.quantization:", type(nb20_exc).__name__, nb20_exc)
'''
    ),
    md(
        """
**Пастки TorchAO, підтверджені документацією:**

- `cache_implementation="static"` автоматично компілює модель, але вона **перекомпільовується** при
  кожній зміні розміру батчу або `max_new_tokens`. Квантизувати без компіляції —
  `disable_compile=True` у `generate`.
- **int4-модель можна завантажити лише на той самий пристрій**, де її квантували (розкладка
  специфічна для пристрою). Для int8 і float8 такого обмеження немає.
- `save_pretrained` у safetensors — лише з `torchao >= 0.15`; нижче доводилося писати небезпечний
  `.bin` через `torch.save`.
- Per-module конфігурація: `FqnToConfig({"_default": cfg, "<повне ім'я модуля>": None})` — `None`
  означає «не квантувати». Ключі з префіксом `re:` — це регулярні вирази.
- `include_embedding=True` потрібен, щоб у квантизацію потрапили вбудови.
"""
    ),

    # ── 20.5 ─────────────────────────────────────────────────────────────
    md(
        """
## 20.5 GGUF і llama.cpp: точні назви типів

Назви типів квантизації GGML виписуємо **програмно** з `research/quant/ggml_h.txt` — заголовка
`ggml.h` із `llama.cpp`. Так їх не треба згадувати: код читає файл і показує, що там є насправді.
"""
    ),
    code(
        '''
import pathlib
import re

NB20_GGML = pathlib.Path(ROOT) / "research" / "quant" / "ggml_h.txt"
NB20_GGML_TEXT = NB20_GGML.read_text(encoding="utf-8")

# 1. Усі ідентифікатори типів тензорів, згадані у файлі.
NB20_TYPE_IDS = sorted(set(re.findall(r"GGML_TYPE_[A-Z0-9_]+", NB20_GGML_TEXT)))
print(f"файл: research/quant/ggml_h.txt ({len(NB20_GGML_TEXT.splitlines())} рядків)")
print(f"унікальних ідентифікаторів GGML_TYPE_*: {len(NB20_TYPE_IDS)}")
for nb20_t in NB20_TYPE_IDS:
    print(f"  {nb20_t:22} згадок у файлі: {NB20_GGML_TEXT.count(nb20_t)}")

# 2. Ідентифікатори точності (той самий перелік використовують дві різні функції).
NB20_PREC_IDS = sorted(set(re.findall(r"GGML_PREC_[A-Z0-9_]+", NB20_GGML_TEXT)))
print()
print(f"унікальних ідентифікаторів GGML_PREC_*: {len(NB20_PREC_IDS)}")
print("  " + ", ".join(NB20_PREC_IDS))
'''
    ),
    code(
        '''
# 3. Розбір рядків виду 'GGML_PREC_X - ... GGML_TYPE_Y ...' із заголовка.
NB20_LINE_RE = re.compile(r"^(?P<prec>GGML_PREC_[A-Z0-9_]+)\\s*-\\s*(?P<rest>.+)$")


def nb20_clean_comment(raw):
    nb20_s = raw.strip()
    if nb20_s.startswith("//"):
        nb20_s = nb20_s[2:].strip()
    if nb20_s.startswith("-"):
        nb20_s = nb20_s[1:].strip()
    return nb20_s


NB20_SRC_MAP, NB20_ACC_NOTES = {}, {}
for nb20_raw2 in NB20_GGML_TEXT.splitlines():
    nb20_m = NB20_LINE_RE.match(nb20_clean_comment(nb20_raw2))
    if not nb20_m:
        continue
    nb20_prec, nb20_rest = nb20_m.group("prec"), nb20_m.group("rest")
    nb20_types = sorted(set(re.findall(r"GGML_TYPE_[A-Z0-9_]+", nb20_rest)))
    if nb20_types:
        NB20_SRC_MAP[nb20_prec] = (nb20_types, "etc." in nb20_rest)
    else:
        NB20_ACC_NOTES[nb20_prec] = nb20_rest

print("ggml_prec_set_src(): які типи дозволено отримати з кожного рівня")
for nb20_prec, (nb20_types, nb20_trailing) in NB20_SRC_MAP.items():
    nb20_suffix = " (+ інші, у файлі позначено 'etc.')" if nb20_trailing else ""
    print(f"  {nb20_prec:16} -> {', '.join(nb20_types)}{nb20_suffix}")

print()
print("ggml_prec_set_acc(): що той самий рівень означає для накопичувача")
for nb20_prec, nb20_note in NB20_ACC_NOTES.items():
    print(f"  {nb20_prec:16} -> {nb20_note}")

# 4. Зворотний індекс: тип -> родина точності.
NB20_REVERSE = {}
for nb20_prec, (nb20_types, _) in NB20_SRC_MAP.items():
    for nb20_t in nb20_types:
        NB20_REVERSE.setdefault(nb20_t, []).append(nb20_prec)

print()
print("Зворотний індекс: тип -> родина точності")
for nb20_t in sorted(NB20_REVERSE):
    print(f"  {nb20_t:20} {', '.join(NB20_REVERSE[nb20_t])}")
'''
    ),
    md(
        """
### Що підтверджено, а що ні

**Підтверджено** (11 типів + 5 рівнів точності + розподіл за розрядністю: `Q8_*` — 8-бітні,
`Q4_*`/`NVFP4`/`MXFP4` — 4-бітні).

**Не вдалося підтвердити станом на 09.2026** за цим файлом:

- тіло `enum ggml_type` — у заголовку є лише функції, що приймають `enum ggml_type`;
- типи `Q5_0`, `Q5_K`, `Q6_K`, `Q3_K`, `Q2_K`, `IQ*`, `TQ1_0`, `TQ2_0` — **жодної згадки**;
- розмір блоку й точний біт-на-параметр для окремих типів (тобто популярне «Q4_K_M ≈ 4.83 біта»
  цим джерелом **не перевіряється**);
- що саме означає суфікс `_K` і чим `Q4_K` структурно відрізняється від `Q4_0`;
- різниця між `MXFP4` і `NVFP4` за межами назв.

Підтверджена окрема деталь формату: у заголовку є `GGML_QNT_VERSION` = **2** з коментарем
«bump this on quantization format changes» і `GGML_QNT_VERSION_FACTOR` = **1000**. Це версія формату
квантизації, окрема від `GGML_FILE_VERSION`.
"""
    ),
    code(
        '''
# Перевірка, що типів поза файлом справді немає — щоб «не підтверджено» було доведеним,
# а не припущенням.
NB20_ABSENT = ["Q5_0", "Q5_K", "Q6_K", "Q3_K", "Q2_K", "IQ1_S", "IQ2_XXS",
               "IQ4_NL", "IQ4_XS", "TQ1_0", "TQ2_0"]
print(f"{'тип':10}{'згадок у ggml_h.txt':>22}")
print("-" * 34)
for nb20_absent in NB20_ABSENT:
    print(f"{nb20_absent:10}{NB20_GGML_TEXT.count(nb20_absent):>22}")

print()
NB20_CONSTANTS = {}
for nb20_cname in ("GGML_FILE_MAGIC", "GGML_FILE_VERSION", "GGML_QNT_VERSION",
                   "GGML_QNT_VERSION_FACTOR", "GGML_MAX_DIMS"):
    nb20_match = re.search(rf"^#define {nb20_cname} (.+)$", NB20_GGML_TEXT, re.M)
    NB20_CONSTANTS[nb20_cname] = nb20_match.group(1).split("//")[0].strip() if nb20_match else None
for nb20_cname, nb20_cval in NB20_CONSTANTS.items():
    print(f"  {nb20_cname:26} {nb20_cval}")
'''
    ),

    # ── 20.6 ─────────────────────────────────────────────────────────────
    md(
        """
## 20.6 Порівняльна таблиця: пам'ять / швидкість / якість

Зведення п'яти інструментів за підтвердженими властивостями. Метрик **якості** тут немає навмисно:
у жодному з наявних джерел їх немає — там лише пам'ять, токени за секунду й тип квантизації.
Якість міряють окремо (розділ 24).
"""
    ),
    code(
        '''
NB20_COMPARISON = [
    # (інструмент, коли, калібрування, розрядності, пам'ять, прискорення, пастка)
    ("bitsandbytes", "під час завантаження", "не потрібне", "8 біт / 4 біти (NF4)",
     "2x на 8 біт, 4x на 4 біти; nested +0.4 біта/параметр",
     "0.50.0: до 4x на 4-бітному інференсі, батчі 2-64",
     "тренування лише extra-параметрів"),
    ("GPTQ (GPT-QModel)", "після тренування", "датасет (типово c4)", "int4",
     "4x (заявлено)", "fused-ядро деквантування; Marlin для A100",
     "не сумісний зі старими чекпойнтами AutoGPTQ"),
    ("AWQ", "після тренування", "зовнішня бібліотека", "4 біти",
     "4.00-5.73 GB у бенчмарку 7B", "fused modules: 2.09x-3.36x на decode",
     "fused не поєднується з FlashAttention2"),
    ("TorchAO", "завантаження або PTQ", "для частини схем", "float8 / int8 / int4",
     "залежить від схеми; є квантування KV-кешу", "композиція з torch.compile",
     "int4 лише на тому пристрої, де квантовано"),
    ("GGUF / llama.cpp", "після тренування", "не потрібне", "8-бітні Q8_*, 4-бітні Q4_*, MXFP4, NVFP4",
     "залежить від суміші типів у файлі", "залежить від ядер рантайму",
     "біт-на-параметр не визначається назвою типу"),
]

print(f"{'інструмент':20}{'коли':24}{'розрядності'}")
print("=" * 88)
for nb20_row in NB20_COMPARISON:
    print(f"{nb20_row[0]:20}{nb20_row[1]:24}{nb20_row[3]}")
    print(f"{'':20}пам'ять:      {nb20_row[4]}")
    print(f"{'':20}швидкість:    {nb20_row[5]}")
    print(f"{'':20}калібрування: {nb20_row[2]}")
    print(f"{'':20}пастка:       {nb20_row[6]}")
    print("-" * 88)
'''
    ),
    code(
        '''
# Найважливіше число розділу: скільки пам'яті дає кожен крок униз за розрядністю —
# і чи це взагалі змінює кількість потрібних карт.
NB20_BUDGETS = {"80 GiB (з джерел: A100)": 80, "48 GiB": 48, "24 GiB": 24}
NB20_TARGET = 27_781_427_952  # точна кількість параметрів Qwen/Qwen3.8-27B (research/det_qwen38.json)

print(f"модель {NB20_TARGET / 1e9:.2f} млрд параметрів; ваги без KV-кешу й активацій")
print()
hdr = f"{'бюджет':26}" + "".join(f"{k:>24}" for k in NB20_BITS)
print(hdr)
print("-" * len(hdr))
for nb20_blabel, nb20_budget in NB20_BUDGETS.items():
    nb20_cells = []
    for nb20_bits in NB20_BITS.values():
        nb20_need = nb20_weights_gib(NB20_TARGET, nb20_bits)
        nb20_cells.append(f"{nb20_need:9.2f} GiB " +
                          ("OK" if nb20_need <= nb20_budget else "не вміщається"))
    print(f"{nb20_blabel:26}" + "".join(f"{c:>24}" for c in nb20_cells))
'''
    ),

    # ── 20.7 ─────────────────────────────────────────────────────────────
    md(
        """
## 20.7 Коли квантизація не потрібна

Рішення зводиться до одного питання: чи є дефіцит, який квантування закриває. Перевірмо на реальних
метаданих моделі з Hub — файл `research/det_qwen38.json` містить поле `safetensors.parameters`
із кількістю параметрів у BF16.
"""
    ),
    code(
        '''
import json

NB20_META = json.loads((pathlib.Path(ROOT) / "research" / "det_qwen38.json")
                       .read_text(encoding="utf-8"))
NB20_N_PARAMS = NB20_META["safetensors"]["parameters"]["BF16"]
NB20_STORED = NB20_META["usedStorage"]

print(f"модель: {NB20_META['modelId']}")
print(f"остання зміна: {NB20_META['lastModified']}")
print(f"параметрів (BF16): {NB20_N_PARAMS:,}")
print(f"займає на диску:   {NB20_STORED:,} байт = {NB20_STORED / NB20_GIB:.2f} GiB")
print(f"байт на параметр:  {NB20_STORED / NB20_N_PARAMS:.4f}   (теоретично 2.0 для BF16)")
print()
print("Це найдешевша перевірка чекпойнта: поділіть обсяг на кількість параметрів.")
print("Якщо результат далекий від 2.0 (BF16) або 1.0 (int8) — щось не те.")
'''
    ),
    code(
        '''
# Скільки карт по 80 GiB треба лише під ваги (без KV-кешу й активацій).
import math

print(f"{'розрядність':24}{'GiB':>10}{'карт x 80 GiB':>16}")
print("-" * 50)
for nb20_label3, nb20_bits3 in NB20_BITS.items():
    nb20_need3 = nb20_weights_gib(NB20_N_PARAMS, nb20_bits3)
    print(f"{nb20_label3:24}{nb20_need3:>10.2f}{math.ceil(nb20_need3 / 80):>16}")

nb20_bf16 = nb20_weights_gib(NB20_N_PARAMS, 16)
nb20_int4 = nb20_weights_gib(NB20_N_PARAMS, 4)
print()
print(f"bf16 -> int4 звільняє {nb20_bf16 - nb20_int4:.2f} GiB, "
      f"але кількість карт по 80 GiB не змінюється: "
      f"{math.ceil(nb20_bf16 / 80)} і {math.ceil(nb20_int4 / 80)}.")
print("Квантування змінює топологію лише тоді, коли перетинає межу кількості карт.")
'''
    ),
    code(
        '''
# Функція-рішення. Повертає причину, а не булеве значення.
def nb20_needs_quantization(n_params, vram_gib, bits_base=16, bits_target=4,
                            kv_and_activations_gib=0.0, headroom=1.0):
    nb20_base = nb20_weights_gib(n_params, bits_base) * headroom + kv_and_activations_gib
    nb20_target = nb20_weights_gib(n_params, bits_target) * headroom + kv_and_activations_gib
    if nb20_base <= vram_gib:
        return (False, f"у {bits_base} бітах потрібно {nb20_base:.2f} GiB "
                       f"з {vram_gib} GiB — дефіциту немає")
    if nb20_target <= vram_gib:
        return (True, f"{bits_base} біт: {nb20_base:.2f} GiB (не вміщається), "
                      f"{bits_target} біти: {nb20_target:.2f} GiB — вміщається")
    return (None, f"навіть {bits_target} біти дають {nb20_target:.2f} GiB "
                  f"з {vram_gib} GiB — потрібні інші заходи")


print(f"{'сценарій':52}{'потрібне квантування?'}")
print("-" * 108)
NB20_CASES = [
    ("27.78B, 80 GiB VRAM, без запасу", dict(n_params=NB20_N_PARAMS, vram_gib=80)),
    ("27.78B, 48 GiB VRAM", dict(n_params=NB20_N_PARAMS, vram_gib=48)),
    ("27.78B, 48 GiB VRAM, +6 GiB на KV-кеш", dict(n_params=NB20_N_PARAMS, vram_gib=48,
                                                   kv_and_activations_gib=6.0)),
    ("27.78B, 24 GiB VRAM", dict(n_params=NB20_N_PARAMS, vram_gib=24)),
    ("8B, 24 GiB VRAM", dict(n_params=8.0e9, vram_gib=24)),
]
for nb20_case_label, nb20_kwargs in NB20_CASES:
    nb20_decision, nb20_reason = nb20_needs_quantization(**nb20_kwargs)
    nb20_verdict = {True: "ТАК", False: "НІ", None: "НЕ ДОПОМОЖЕ"}[nb20_decision]
    print(f"{nb20_case_label:52}{nb20_verdict}")
    print(f"{'':52}{nb20_reason}")
'''
    ),
    md(
        """
**Коли квантувати не варто** (кожен пункт — з підтвердженого факту вище):

- Модель уміщається з запасом на KV-кеш і батч — квантування не розблоковує нічого.
- Ціль — максимальна якість, а евалюацій немає: `llm_int8_threshold=0.0` «значно прискорює інференс
  ціною можливої втрати точності», і цю втрату без евалюації не видно.
- Потрібне доучування всієї моделі: 8- і 4-бітне тренування підтримане **лише** для extra-параметрів.
- Потрібна переносимість int4-артефакту між пристроями (TorchAO).
- Виграш від інших важелів більший: prompt caching (розділ 9), батч-обробка (розділ 10),
  скорочення контексту (розділ 16).
- Інференс іде через API — рішення ухвалює провайдер.
- Цільове залізо не покрите: QLoRA на Intel Gaudi — частково, 8-бітні оптимізатори там відсутні;
  на macOS через MPS 8-бітні оптимізатори ще заплановані.
- Готовий квантований чекпойнт уже є на Hub — квантизувати з нуля може зайняти години (близько
  4 годин для 175B-моделі на A100).
"""
    ),

    # ── самоперевірка ────────────────────────────────────────────────────
    md(
        """
## Самоперевірка

Перевіряємо твердження розділу: арифметику «параметри × біт / 8», роль блокового масштабу, числа
з джерел (AWQ-бенчмарк, TorchAO, GGML, метадані Hub) і рішення про квантування під конкретну VRAM.
"""
    ),
    code(
        r'''
# ── 1. Формула ваг і кратна економія проти bf16 ─────────────────────────
assert (
    NB20_GIB == 1024 ** 3 and len(NB20_BITS) == 4 and NB20_BASE == 16
    and round(nb20_weights_gib(3.2e9, 32), 2) == 11.92
    and round(nb20_weights_gib(8.0e9, 16), 2) == 14.90
    and round(nb20_weights_gib(70.0e9, 4), 2) == 32.60
    and {nb20_b: round(NB20_BASE / nb20_b, 2) for nb20_b in NB20_BITS.values()}
    == {32: 0.5, 16: 1.0, 8: 2.0, 4: 4.0}
), "економія мусить бути рівно ×2 на 8 бітах і ×4 на 4 бітах проти bf16"
print("✓ арифметика: 8B у bf16 — 14.90 GiB, 70B у 4 бітах — 32.60 GiB; "
      "економія ×2 (int8) і ×4 (int4) проти bf16")

# ── 2. Блоковий масштаб замість тензорного ──────────────────────────────
nb20c_err = {}
for nb20c_bits in (8, 4, 3, 2):
    for nb20c_block in (None, NB20_GROUP):
        nb20c_hat = nb20_quant_symmetric(NB20_W, nb20c_bits, nb20c_block)
        nb20c_err[(nb20c_bits, nb20c_block)] = (
            float(np.linalg.norm(NB20_W - nb20c_hat) / np.linalg.norm(NB20_W)),
            float(np.abs(NB20_W - nb20c_hat).max()))
assert (
    NB20_W.shape == (NB20_ROWS, NB20_COLS) == (768, 768)
    and round(float(np.abs(NB20_W).max()), 4) == 1.0722
    and round(nb20c_err[(8, NB20_GROUP)][0] * 100, 4) == 0.6668
    and round(nb20c_err[(4, NB20_GROUP)][0] * 100, 4) == 11.7717
    and round(nb20c_err[(8, None)][0] * 100, 4) == 12.1292
    and round(nb20c_err[(4, None)][0] * 100, 4) == 99.4536
), "на 4 бітах блоки по 128 мусять дати 11.77% замість 99.45% з одним масштабом"
print("✓ масштаб: 8 біт — 0.6668% (блоки) проти 12.1292% (тензор); "
      "4 біти — 11.7717% проти 99.4536%; блоки по 128 обов'язкові")

# ── 3. Деградація монотонна, а викиди задають максимум помилки ──────────
nb20c_rel = [nb20c_err[(nb20c_b, NB20_GROUP)][0] for nb20c_b in (8, 4, 3, 2)]
assert (
    nb20c_rel == sorted(nb20c_rel)                       # що менше бітів, то більша похибка
    and round(nb20c_err[(3, NB20_GROUP)][1], 6) == 0.138080
    and round(nb20c_err[(2, NB20_GROUP)][1], 6) == 0.363737
    and nb20c_err[(3, NB20_GROUP)][1] == nb20c_err[(3, None)][1]     # максимум задають викиди
    and nb20c_err[(2, NB20_GROUP)][1] == nb20c_err[(2, None)][1]
), "на 3 і 2 бітах блоковий масштаб не зменшує максимальну помилку — її тримають викиди"
print("✓ деградація: 0.67% → 11.77% → 27.31% → 76.32% зі зменшенням розрядності; "
      "максимальна помилка на 3 і 2 бітах однакова з тензорним масштабом")

# ── 4. Реальна модель 27.78B: GiB за схемами і nested quantization ──────
nb20c_nested = NB20_CASE * (4 - 0.4) / 8 / NB20_GIB
assert (
    NB20_CASE == 27_781_427_952
    and round(nb20_weights_gib(NB20_CASE, 32), 2) == 103.49
    and round(nb20_weights_gib(NB20_CASE, 16), 2) == 51.75
    and round(nb20_weights_gib(NB20_CASE, 8), 2) == 25.87
    and round(nb20_weights_gib(NB20_CASE, 4), 2) == 12.94
    and round(nb20c_nested, 2) == 11.64
    and round(nb20_weights_gib(NB20_CASE, 4) - nb20c_nested, 2) == 1.29
), "27.78B у 4 бітах — 12.94 GiB; nested quantization (3.6 біта) економить 1.29 GiB"
print("✓ 27.78B: fp32 103.49, bf16 51.75, int8 25.87, int4 12.94 GiB; "
      "nested → 11.64 GiB (виграш 1.29 GiB)")

# ── 5. Джерело AWQ: таблиці розібрано з підписами ───────────────────────
nb20c_tables = [(nb20c_cap, len(nb20c_rows), len(nb20c_head))
                for nb20c_cap, nb20c_head, nb20c_rows in NB20_TABLES]
assert (
    len(NB20_AWQ_LINES) == 234 and len(NB20_TABLES) == 3
    and nb20c_tables == [("Unfused module", 7, 6), ("Fused module", 7, 6),
                         ("generate throughput/batch size", 3, 2)]
    and NB20_AWQ.name == "hf5_tfdoc_quantization_awq.txt"
), "з файлу джерела мусять розібратися три таблиці з підписами"
print("✓ AWQ-джерело: 234 рядки → 3 таблиці ('Unfused module' 7×6, "
      "'Fused module' 7×6, 'generate throughput/batch size' 3×2)")

# ── 6. Fused-модулі прискорюють decode удвічі-втричі ────────────────────
assert (
    len(NB20_SPEEDUPS) == 7 == len(NB20_UNFUSED) == len(NB20_FUSED)
    and round(min(NB20_SPEEDUPS), 2) == 2.09 and round(max(NB20_SPEEDUPS), 2) == 3.36
    and round(sum(NB20_SPEEDUPS) / len(NB20_SPEEDUPS), 2) == 2.72
    and round(float(NB20_UNFUSED[0][4]), 2) == 38.45
    and round(float(NB20_FUSED[0][4]), 2) == 80.26
    and NB20_UNFUSED[0][2] == NB20_FUSED[0][2] == "32"      # той самий Decode Length
), "fused-модулі мусять прискорювати decode від 2.09x до 3.36x"
print(f"✓ fused: прискорення decode від 2.09x до 3.36x (середнє 2.72x); "
      "на батчі 32 — 80.26 проти 38.45 токенів/с")

# ── 7. Довідник TorchAO: конфігурація під кожне залізо ──────────────────
nb20c_torchao = {nb20c_cfg for _, nb20c_cfg, _ in NB20_TORCHAO}
assert (
    len(NB20_TORCHAO) == 9 and len(nb20c_torchao) == 8
    and len({nb20c_hw for nb20c_hw, _, _ in NB20_TORCHAO}) == 4
    and "Int4WeightOnlyConfig(group_size=128, use_hqq=True)" in nb20c_torchao
    and "Float8DynamicActivationFloat8WeightConfig" in nb20c_torchao
    and ("CPU", "PrototypeInt4WeightOnlyConfig(group_size=128, "
                 "int4_choose_qparams_algorithm='tinygemm')",
         "int4 для CPU, torchao >= 0.15.0") in NB20_TORCHAO
), "довідник TorchAO мусить покривати H100, A100, Intel XPU і CPU"
print("✓ TorchAO: 9 рядків на 4 родини заліза; H100 — float8, A100 — int4 з use_hqq, "
      "CPU — prototype int4")

# ── 8. GGML: типи тензорів і родини точності ────────────────────────────
assert (
    len(NB20_GGML_TEXT.splitlines()) == 1821
    and len(NB20_TYPE_IDS) == 11 and len(NB20_PREC_IDS) == 5
    and NB20_TYPE_IDS == sorted(["GGML_TYPE_BF16", "GGML_TYPE_F16", "GGML_TYPE_F32",
                                 "GGML_TYPE_MXFP4", "GGML_TYPE_NVFP4", "GGML_TYPE_Q4_0",
                                 "GGML_TYPE_Q4_1", "GGML_TYPE_Q4_K", "GGML_TYPE_Q8_0",
                                 "GGML_TYPE_Q8_1", "GGML_TYPE_Q8_K"])
    and NB20_GGML_TEXT.count("GGML_TYPE_F32") == 5
    and NB20_GGML_TEXT.count("GGML_TYPE_NVFP4") == 3
    and NB20_PREC_IDS == sorted(["GGML_PREC_BF16", "GGML_PREC_F16", "GGML_PREC_F32",
                                 "GGML_PREC_Q4", "GGML_PREC_Q8"])
), "у файлі ggml.h мусить бути 11 типів і 5 рівнів точності"
print("✓ GGML: 1821 рядок, 11 ідентифікаторів GGML_TYPE_*, 5 GGML_PREC_*; "
      "F32 згадано 5 разів, NVFP4 — 3")

# ── 9. GGML: мапа дозволених типів і правила накопичувача ───────────────
assert (
    NB20_SRC_MAP["GGML_PREC_F32"] == (["GGML_TYPE_F32"], False)
    and NB20_SRC_MAP["GGML_PREC_Q8"] == (["GGML_TYPE_Q8_0", "GGML_TYPE_Q8_1", "GGML_TYPE_Q8_K"], True)
    and NB20_SRC_MAP["GGML_PREC_Q4"][0] == ["GGML_TYPE_MXFP4", "GGML_TYPE_NVFP4",
                                            "GGML_TYPE_Q4_0", "GGML_TYPE_Q4_1",
                                            "GGML_TYPE_Q4_K"]
    and NB20_SRC_MAP["GGML_PREC_Q4"][1] is True                # у файлі стоїть 'etc.'
    and NB20_ACC_NOTES["GGML_PREC_Q8"] == "not allowed"
    and NB20_ACC_NOTES["GGML_PREC_Q4"] == "not allowed"
    and "F32" in NB20_ACC_NOTES["GGML_PREC_BF16"]
), "рівні Q4 і Q8 не можна використовувати як накопичувач"
print("✓ GGML: F32 → лише F32; Q8 → три типи + 'etc.'; Q4 → п'ять типів + 'etc.'; "
      "для накопичувача Q8 і Q4 — 'not allowed'")

# ── 10. GGML: типи поза файлом і версія формату ─────────────────────────
assert (
    len(NB20_ABSENT) == 11
    and all(NB20_GGML_TEXT.count(nb20c_absent) == 0 for nb20c_absent in NB20_ABSENT)
    and len(NB20_REVERSE) == 11
    and NB20_REVERSE["GGML_TYPE_Q4_K"] == ["GGML_PREC_Q4"]
    and NB20_REVERSE["GGML_TYPE_F32"] == ["GGML_PREC_F32"]
    and NB20_CONSTANTS == {"GGML_FILE_MAGIC": "0x67676d6c", "GGML_FILE_VERSION": "2",
                           "GGML_QNT_VERSION": "2", "GGML_QNT_VERSION_FACTOR": "1000",
                           "GGML_MAX_DIMS": "4"}
), "типів Q5/Q6/IQ/TQ у файлі немає взагалі — нуль згадок"
print("✓ GGML: 11 типів поза файлом мають 0 згадок; зворотний індекс покриває всі 11 типів; "
      "MAGIC 0x67676d6c, QNT_VERSION 2, MAX_DIMS 4")

# ── 11. Порівняння інструментів квантування ────────────────────────────
nb20c_tools = {nb20c_row[0]: nb20c_row for nb20c_row in NB20_COMPARISON}
assert (
    len(NB20_COMPARISON) == 5
    and set(nb20c_tools) == {"bitsandbytes", "GPTQ (GPT-QModel)", "AWQ", "TorchAO",
                             "GGUF / llama.cpp"}
    and "2.09x-3.36x" in nb20c_tools["AWQ"][5]
    and "FlashAttention2" in nb20c_tools["AWQ"][6]
    and nb20c_tools["GGUF / llama.cpp"][6] == "біт-на-параметр не визначається назвою типу"
    and nb20c_tools["bitsandbytes"][2] == "не потрібне"
    and "nested" in nb20c_tools["bitsandbytes"][4]
), "у порівнянні мусять бути п'ять інструментів із назвами з джерел"
print("✓ порівняння: 5 інструментів; AWQ дає 2.09x-3.36x на decode, але fused не "
      "поєднується з FlashAttention2; у GGUF біт-на-параметр не визначається назвою типу")

# ── 12. Бюджет VRAM: що саме вміщається в 24 і 48 GiB ───────────────────
nb20c_fits = {nb20c_gib: [nb20c_label for nb20c_label, nb20c_b in NB20_BITS.items()
                          if nb20_weights_gib(NB20_TARGET, nb20c_b) <= nb20c_gib]
              for nb20c_gib in NB20_BUDGETS.values()}
assert (
    len(NB20_BUDGETS) == 3 and NB20_TARGET == NB20_CASE
    and nb20c_fits[80] == ["bf16/fp16", "int8 / Q8_0", "int4 / Q4_0 / NF4"]
    and nb20c_fits[48] == ["int8 / Q8_0", "int4 / Q4_0 / NF4"]
    and nb20c_fits[24] == ["int4 / Q4_0 / NF4"]
    and all(nb20_weights_gib(NB20_TARGET, 32) > nb20c_gib for nb20c_gib in NB20_BUDGETS.values())
), "у 24 GiB мусить вміщатися лише 4-бітний варіант, у 48 GiB — int8 і int4"
print("✓ бюджет VRAM: 80 GiB — bf16/int8/int4; 48 GiB — int8/int4; 24 GiB — лише int4; "
      "fp32 не вміщається ніде")

# ── 13. Метадані Hub і кількість карт під ваги ──────────────────────────
assert (
    NB20_META["modelId"] == "Qwen/Qwen3.8-27B"
    and NB20_N_PARAMS == NB20_TARGET == 27_781_427_952
    and NB20_STORED == 55_623_336_488
    and round(NB20_STORED / NB20_N_PARAMS, 4) == 2.0022      # близько 2.0 → справді BF16
    and round(NB20_STORED / NB20_GIB, 2) == 51.80
    and math.ceil(nb20_weights_gib(NB20_N_PARAMS, 32) / 80) == 2
    and {nb20c_b: math.ceil(nb20_weights_gib(NB20_N_PARAMS, nb20c_b) / 80)
         for nb20c_b in (16, 8, 4)} == {16: 1, 8: 1, 4: 1}
    and round(nb20_weights_gib(NB20_N_PARAMS, 16) - nb20_weights_gib(NB20_N_PARAMS, 4), 2) == 38.81
), "байт на параметр мусить бути близьким до 2.0, а кількість карт — не змінюватися"
print("✓ чекпойнт: 27 781 427 952 параметрів = 51.80 GiB (2.0022 байт/параметр); "
      "bf16 → int4 звільняє 38.81 GiB, але карт по 80 GiB усе одно 1")

# ── 14. Рішення про квантування під конкретну VRAM ──────────────────────
nb20c_verdicts = []
for nb20c_label2, nb20c_kwargs2 in NB20_CASES:
    nb20c_decision2, _ = nb20_needs_quantization(**nb20c_kwargs2)
    nb20c_verdicts.append({True: "ТАК", False: "НІ", None: "НЕ ДОПОМОЖЕ"}[nb20c_decision2])
assert (
    len(NB20_CASES) == 5
    and nb20c_verdicts == ["НІ", "ТАК", "ТАК", "ТАК", "НІ"]
    and nb20_needs_quantization(n_params=NB20_N_PARAMS, vram_gib=8)[0] is None
    and "потрібні інші заходи" in nb20_needs_quantization(n_params=NB20_N_PARAMS, vram_gib=8)[1]
    and nb20_needs_quantization(n_params=NB20_N_PARAMS, vram_gib=48,
                                kv_and_activations_gib=6.0)[1].endswith(
        "4 біти: 18.94 GiB — вміщається")
), "8 GiB не вистачить навіть для 4 бітів — рішення мусить бути None"
print("✓ рішення: 80 GiB — НІ; 48 і 24 GiB — ТАК; 8B у 24 GiB — НІ; "
      "8 GiB для 27.78B — НЕ ДОПОМОЖЕ (навіть 4 біти дають 12.94 GiB)")

print()
print("Усі перевірки пройдено.")
'''
    ),

    # ── Підсумок ─────────────────────────────────────────────────────────
    md(
        """
## Підсумок

1. **Спершу арифметика.** `параметри × біт / 8` відповідає на 80% питань: 70B у bf16 — 130.39 GiB,
   у 4 бітах — 32.60 GiB.
2. **Блоки обов'язкові.** Один масштаб на тензор дає 99.45% відносної похибки на 4 бітах проти
   11.77% з блоками по 128.
3. **`bitsandbytes` — найшвидший старт.** Без калібрування, `BitsAndBytesConfig` у `from_pretrained`.
   У v5 аргументи `load_in_4bit`/`load_in_8bit` видалено з `from_pretrained`, але лишилися полями
   самої конфігурації.
4. **GPTQ і AWQ — PTQ з калібруванням.** GPTQ: int4 із відновленням у fp16 на льоту, 4× пам'яті;
   Marlin — інференс-ядро для A100, не квантизатор. AWQ: fused modules дають 2.09×–3.36× на decode.
5. **TorchAO — єдиний, хто дає float8, 2:4-розрідженість і квантування KV-кешу.** Потрібен
   `torchao >= 0.15.0`, рядковий API видалено.
6. **Назви типів GGUF — не з пам'яті.** `GGML_TYPE_Q8_0`, `Q8_1`, `Q8_K` — три різні 8-бітні формати;
   `Q4_0`, `Q4_1`, `Q4_K`, `NVFP4`, `MXFP4` — п'ять різних 4-бітних. Біт-на-параметр із назви не
   випливає.
7. **Якість не виміряна в жодному джерелі розділу.** Порівнюйте методи за пам'яттю й швидкістю, а
   якість міряйте самі (розділ 24).

**Куди далі:**

- Розділ 2 — префіл і декодування: чому weight-only-квантування допомагає саме на decode.
- Розділ 6 — вибір моделі, зокрема коли локальна модель програє API.
- Розділ 15 — інша «квантизація»: стиснення векторів ембедингів для ANN-пошуку.
- Розділ 19 — Transformers v5: `quantization_config` як єдина точка входу.
- Розділ 21 — QLoRA: 4-бітна база плюс LoRA-адаптери.
- Розділ 24 — евалюації: без них деградацію від квантування не побачити.

## Джерела

- [Transformers — Quantization: bitsandbytes](https://raw.githubusercontent.com/huggingface/transformers/main/docs/source/en/quantization/bitsandbytes.md)
- [Transformers — Quantization: GPTQ](https://raw.githubusercontent.com/huggingface/transformers/main/docs/source/en/quantization/gptq.md)
- [Transformers — Quantization: AWQ](https://raw.githubusercontent.com/huggingface/transformers/main/docs/source/en/quantization/awq.md)
- [Transformers — Quantization: torchao](https://raw.githubusercontent.com/huggingface/transformers/main/docs/source/en/quantization/torchao.md)
- [bitsandbytes — README](https://raw.githubusercontent.com/bitsandbytes-foundation/bitsandbytes/main/README.md)
- [bitsandbytes 0.50.0 — release notes](https://github.com/bitsandbytes-foundation/bitsandbytes/releases/tag/0.50.0)
- [llama.cpp — ggml/include/ggml.h](https://raw.githubusercontent.com/ggml-org/llama.cpp/master/ggml/include/ggml.h)
- [Transformers — Paged attention](https://raw.githubusercontent.com/huggingface/transformers/main/docs/source/en/paged_attention.md)
- [Transformers — v5 migration guide](https://raw.githubusercontent.com/huggingface/transformers/main/docs/source/en/migration.md)
- [Qwen/Qwen3.8-27B — метадані Hub](https://huggingface.co/Qwen/Qwen3.8-27B)

Локальні копії: `research/hf5_tfdoc_quantization_*.txt`, `research/bnb_readme.txt`,
`research/hf5_bnb050.md`, `research/quant/ggml_h.txt`, `research/tf_v5_migration.txt`,
`research/det_qwen38.json`.
"""
    ),
]
