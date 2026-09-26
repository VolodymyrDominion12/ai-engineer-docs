"""Ноутбук 21 — «Fine-tuning: LoRA/PEFT, SFT, DPO, GRPO».

Розділ довідника: sections/21-finetuning.md
Працює без API-ключів і без GPU. Усі розрахунки — чиста арифметика на Python плюс
розбір форматів даних і конфігурацій. Клітинки зі справжнім навчанням захищені
try/except і за замовчуванням не запускаються: вони вимагають GPU, завантаження
моделі з мережі та кількох бібліотек.

Усі назви класів, параметрів, полів, форматів і метрик у цьому ноутбуку взяті з
файлів research/ (див. блок «Джерела» в кінці). Розміри шарів узяті з поля
конфігурації Hub-моделі у research/meta2.json, а не з пам'яті.
"""

from nbkit import SETUP_CELL, code, md

FILENAME = "21-finetuning.ipynb"
TITLE = "21. Fine-tuning"

CELLS = [
    md(
        """
# 21. Fine-tuning: LoRA/PEFT, SFT, DPO, GRPO

**Розділ довідника:** [`sections/21-finetuning.md`](../sections/21-finetuning.md)

**Потрібно: torch + peft + trl для реального навчання; GPU обов'язковий для навчання. Розрахунки працюють без GPU**

**Що ви зробите:**

1. Проженете задачу через каскад рішень із документації PEFT: промпт → prompt-based методи →
   layer tuning і адаптери — замість того щоб одразу братися за тренування.
2. Порахуєте кількість тренованих параметрів LoRA за формулою `r × (in + out)` на **реальній
   конфігурації Hub-моделі** й побачите, скільки це у відсотках від повного донавчання.
3. Порахуєте пам'ять під стани оптимізатора залежно від кількості тренованих параметрів.
4. Розберете формати даних для SFT (`messages`, `prompt`/`completion`) і DPO (`chosen`/`rejected`).
5. Відтворите маскування міток `-100` і зсув на один токен — механіку, яка визначає, чого саме
   вчиться модель.
6. Порахуєте втрату DPO за різних `beta` й перевагу GRPO з груповою нормалізацією (три режими
   `scale_rewards`).
7. Перевірите контракт функції нагороди GRPO на прикладі з документації та зберете таблицю
   метрик деградації для 21.6.

> Тренування тут не запускається: для нього потрібен GPU, `torch`, `peft`, `trl` і мережа для
> завантаження моделі. Остання кодова клітинка містить готовий сценарій і вмикається змінною
> середовища `NB21_RUN_TRAINING=1`.
"""
    ),
    md("## Налаштування"),
    code(SETUP_CELL),
    code(
        '''
# Версії бібліотек, потрібних для реального тренування (для відтворюваності).
# Версії на PyPI станом на 09.2026: peft 0.21.0, trl 1.14.0, transformers 5.17.0,
# datasets 5.0.1, accelerate 1.15.0, bitsandbytes 0.50.2.
import importlib

for nb21_name in ("torch", "peft", "trl", "transformers", "datasets", "accelerate", "bitsandbytes"):
    try:
        nb21_mod = importlib.import_module(nb21_name)
        print(f"{nb21_name:14} {getattr(nb21_mod, '__version__', '?')}")
    except ImportError:
        print(f"{nb21_name:14} НЕ ВСТАНОВЛЕНО (для розрахунків нижче не потрібно)")

# GPU потрібен лише для справжнього тренування.
try:
    import torch as nb21_torch
    print()
    print("CUDA доступна:", nb21_torch.cuda.is_available())
except ImportError:
    print()
    print("CUDA доступна: torch не встановлено")
'''
    ),

    # ── 21.1 ─────────────────────────────────────────────────────────────
    md(
        """
## 21.1 Каскад рішень: промпт → soft prompt → адаптер → повне донавчання

Документація PEFT задає явний порядок дій для генеративних моделей: спершу промптинг (наприклад,
few-shot приклади в промпті), щоб перевірити, чи модель **уже вміє** задачу; якщо так — prompt-based
методи, щоб навчити сам промпт і зекономити токени; якщо промптингу не досить — layer tuning і
adapter-методи. Третім пунктом того самого списку стоїть вимірювання retention: кожен крок
донавчання потенційно розучує попереднє знання.

Замінимо цей текст на перевірку, яку можна застосувати до конкретної задачі.
"""
    ),
    code(
        '''
# Каскад із документації PEFT, закодований як послідовність воріт.
# Кожне питання — з тексту джерела, а не з загальних міркувань.
NB21_CASCADE = [
    ("чотири осі сумісності перевірено",
     "Методи не рівні: підтримка квантованої бази, кілька адаптерів, злиття ваг, типи шарів."),
    ("модель розв'язує задачу з few-shot промптом",
     "Пункт 1: якщо модель уже вміє — беріть prompt-based методи й не тренуйте ваги."),
    ("потрібна зміна ПОВЕДІНКИ, а не фактів",
     "Донавчання змінює розподіл відповідей; факти не цитуються й не видаляються за запитом."),
    ("виміряно retention до тренування",
     "Пункт 3: кожен крок донавчання потенційно розучує попереднє знання."),
    ("готові відповідати за окремий артефакт моделі",
     "Адаптер або чекпойнт треба версіонувати й переоцінювати після зміни базової моделі."),
]


def nb21_recommend(answers: dict) -> str:
    """Повертає рекомендований крок каскаду для конкретної задачі."""
    if not answers.get("поведінка_а_не_факти", True):
        return "RAG або пошук: донавчання не дає цитованості й керованого видалення"
    if answers.get("модель_уже_вміє", False):
        if answers.get("хочемо_зекономити_токени", False):
            return "prompt-based метод (p-tuning / prefix tuning / prompt tuning)"
        return "звичайний промпт із few-shot прикладами — тренування не потрібне"
    if answers.get("потрібні_нові_токени", False):
        return "layer tuning: TrainableTokens / trainable_token_indices разом із LoRA"
    return "adapter-метод (LoRA) після вимірювання retention"


NB21_CASES = {
    "класифікація інцидентів у JSON": dict(поведінка_а_не_факти=True, модель_уже_вміє=True),
    "відповіді за внутрішніми регламентами": dict(поведінка_а_не_факти=False),
    "власні маркери <|start_think|>": dict(поведінка_а_не_факти=True,
                                           модель_уже_вміє=False, потрібні_нові_токени=True),
    "стиль і тон підтримки": dict(поведінка_а_не_факти=True, модель_уже_вміє=False),
}

print(f"{'задача':40} рекомендація")
print("-" * 110)
for nb21_task, nb21_ans in NB21_CASES.items():
    print(f"{nb21_task:40} {nb21_recommend(nb21_ans)}")

print()
print("Каскад перед тренуванням:")
for nb21_i, (nb21_gate, nb21_why) in enumerate(NB21_CASCADE, 1):
    print(f"{nb21_i}. {nb21_gate}")
    print(f"   {nb21_why}")
'''
    ),

    # ── 21.2 ─────────────────────────────────────────────────────────────
    md(
        """
## 21.2 Скільки параметрів тренує LoRA: реальна арифметика

Число тренованих параметрів LoRA-моделі залежить від розміру update-матриць, який визначається
головно рангом `r` і **формою оригінальної вагової матриці**. Для лінійного шару з вагами
`out × in` поправка подається як добуток двох матриць — `r × in` і `out × r`, — тому кількість
тренованих параметрів шару дорівнює `r × in + out × r = r × (in + out)`.

Порахуємо це на реальній конфігурації Hub-моделі `google/gemma-4-12B-it` із `research/meta2.json`:
`c_hidden_size=3840`, `c_head_dim=256`, `c_num_attention_heads=16`, `c_num_key_value_heads=8`,
`c_intermediate_size=15360`, `c_num_hidden_layers=48`, `params_total=11959730224`.

Назви цільових модулів узяті з джерел: `q_proj`, `k_proj`, `v_proj`, `o_proj`, `gate_proj`,
`up_proj`, `down_proj` (документація Transformers називає `q_proj` і `v_proj` зумовленими цілями за
замовчуванням), `"all-linear"` — QLoRA-стиль із документації PEFT. Розкладка «`q_proj` має розмір
`num_attention_heads × head_dim`» — це припущення про архітектуру, а не факт із джерела; у
`research/` немає жодного файлу з переліком форм окремих шарів.
"""
    ),
    code(
        '''
import json
import pathlib

NB21_ROOT = pathlib.Path(ROOT)          # ROOT задає SETUP_CELL
NB21_META = json.loads((NB21_ROOT / "research" / "meta2.json").read_text(encoding="utf-8"))

NB21_MIN = None
for nb21_rec in NB21_META:
    if nb21_rec.get("id") == "google/gemma-4-12B-it":
        NB21_MIN = nb21_rec
        break

if NB21_MIN is None:
    raise RuntimeError("У research/meta2.json немає запису google/gemma-4-12B-it")

NB21_H = NB21_MIN["c_hidden_size"]
NB21_HD = NB21_MIN["c_head_dim"]
NB21_QDIM = NB21_MIN["c_num_attention_heads"] * NB21_HD
NB21_KVDIM = NB21_MIN["c_num_key_value_heads"] * NB21_HD
NB21_INTER = NB21_MIN["c_intermediate_size"]
NB21_LAYERS = NB21_MIN["c_num_hidden_layers"]
NB21_TOTAL = NB21_MIN["params_total"]

print("Модель     :", NB21_MIN["id"])
print("hidden_size:", NB21_H, " head_dim:", NB21_HD)
print("q_dim      :", NB21_QDIM, " kv_dim:", NB21_KVDIM, " intermediate:", NB21_INTER)
print("layers     :", NB21_LAYERS, " params_total:", f"{NB21_TOTAL:,}")

# Форми шарів, які ми вважаємо цілями (припущення про розкладку — див. текст вище).
NB21_SHAPES = {
    "q_proj": (NB21_H, NB21_QDIM),
    "k_proj": (NB21_H, NB21_KVDIM),
    "v_proj": (NB21_H, NB21_KVDIM),
    "o_proj": (NB21_QDIM, NB21_H),
    "gate_proj": (NB21_H, NB21_INTER),
    "up_proj": (NB21_H, NB21_INTER),
    "down_proj": (NB21_INTER, NB21_H),
}

NB21_TARGET_SETS = {
    "q_proj + v_proj (зумовлені цілі)": ["q_proj", "v_proj"],
    "q, k, v, o (уся увага)": ["q_proj", "k_proj", "v_proj", "o_proj"],
    "all-linear (QLoRA-стиль)": list(NB21_SHAPES),
}


def nb21_lora_params(rank: int, modules: list) -> int:
    """Треновані параметри LoRA: sum по шарах r x (in + out), помножене на кількість блоків."""
    per_layer = 0
    for nb21_m in modules:
        nb21_in, nb21_out = NB21_SHAPES[nb21_m]
        per_layer += rank * (nb21_in + nb21_out)
    return per_layer * NB21_LAYERS


print()
print(f"{'цілі':34}{'r':>5}{'тренованих':>15}{'частка':>12}")
print("-" * 66)
for nb21_label, nb21_mods in NB21_TARGET_SETS.items():
    for nb21_r in (4, 8, 16, 32, 64, 128):
        nb21_n = nb21_lora_params(nb21_r, nb21_mods)
        print(f"{nb21_label:34}{nb21_r:>5}{nb21_n:>15,}{100 * nb21_n / NB21_TOTAL:>11.4f}%")
    print()
'''
    ),
    code(
        '''
# Лінійність за рангом: подвоєння r рівно подвоює кількість тренованих параметрів.
nb21_prev = None
print("r      тренованих (q_proj+v_proj)   приріст")
print("-" * 52)
for nb21_r in (4, 8, 16, 32, 64, 128):
    nb21_n = nb21_lora_params(nb21_r, NB21_TARGET_SETS["q_proj + v_proj (зумовлені цілі)"])
    nb21_growth = "-" if nb21_prev is None else f"x{nb21_n / nb21_prev:.2f}"
    print(f"{nb21_r:<6} {nb21_n:>24,}   {nb21_growth:>8}")
    nb21_prev = nb21_n

# Порівняння з повним донавчанням.
nb21_full = NB21_TOTAL
print()
print(f"Повне донавчання            : {nb21_full:>14,}  100.0000%")
for nb21_mark, nb21_mods in (
    ("LoRA q+v, r=8", NB21_TARGET_SETS["q_proj + v_proj (зумовлені цілі)"]),
    ("LoRA all-linear, r=16", NB21_TARGET_SETS["all-linear (QLoRA-стиль)"]),
):
    nb21_r = 8 if "r=8" in nb21_mark else 16
    nb21_n = nb21_lora_params(nb21_r, nb21_mods)
    print(f"{nb21_mark:28}: {nb21_n:>14,}  {100 * nb21_n / nb21_full:>9.4f}%"
          f"   (у {nb21_full / nb21_n:,.0f} разів менше)")

print()
print("Порівняння з оцінкою зі статті про LoRA (GPT-3 175B + Adam):")
print("зменшення кількості тренованих параметрів у 10 000 разів і пам'яті GPU у 3 рази.")
'''
    ),
    code(
        '''
# Пам'ять під стани оптимізатора залежить від кількості ТРЕНОВАНИХ параметрів,
# а не від розміру моделі — це головна механічна причина економії LoRA.
#
# Припущення про байти (не з джерела, тому позначені явно):
#   AdamW, fp32: копія ваг 4 Б + два стани (exp_avg, exp_avg_sq) по 4 Б = 12 Б/параметр
#   8-бітний Adam, bf16: ваги 2 Б + два 8-бітні стани по 1 Б = 4 Б/параметр
NB21_BYTES_ADAMW = 12
NB21_BYTES_ADAM8 = 4
NB21_GIB = 1024 ** 3

NB21_OPT_ROWS = [
    ("LoRA q+v, r=16", nb21_lora_params(16, NB21_TARGET_SETS["q_proj + v_proj (зумовлені цілі)"])),
    ("LoRA all-linear, r=16", nb21_lora_params(16, NB21_TARGET_SETS["all-linear (QLoRA-стиль)"])),
    ("LoRA all-linear, r=64", nb21_lora_params(64, NB21_TARGET_SETS["all-linear (QLoRA-стиль)"])),
    ("повне донавчання", NB21_TOTAL),
]

print(f"{'конфігурація':24}{'тренованих':>15}{'AdamW fp32':>14}{'8-біт Adam':>14}")
print("-" * 67)
for nb21_label, nb21_n in NB21_OPT_ROWS:
    nb21_a = nb21_n * NB21_BYTES_ADAMW / NB21_GIB
    nb21_b = nb21_n * NB21_BYTES_ADAM8 / NB21_GIB
    print(f"{nb21_label:24}{nb21_n:>15,}{nb21_a:>11.2f} GiB{nb21_b:>11.2f} GiB")

print()
print("Документований інструмент для 8-бітних станів — 8-бітні оптимізатори bitsandbytes;")
print("у прикладі LoRA+ з документації PEFT використано bnb.optim.Adam8bit.")
'''
    ),
    md(
        """
### Масштаб адаптера: `lora_alpha` має сенс лише разом із `r`

Документація формулює це точно: LoRA масштабує кожен адаптер під час кожного прямого проходу на
фіксований скаляр, встановлений при ініціалізації й залежний від рангу. В оригінальній реалізації
скаляр — `lora_alpha / r`; варіант rsLoRA використовує `lora_alpha / math.sqrt(r)`, що стабілізує
адаптери й підвищує потенціал високих `r`. Перевірмо, як ці два варіанти розходяться з ростом рангу.
"""
    ),
    code(
        '''
import math

NB21_ALPHA = 16
print(f"lora_alpha = {NB21_ALPHA}")
print()
print(f"{'r':>5}{'alpha/r':>12}{'alpha/sqrt(r)':>16}{'у скільки разів більше':>26}")
print("-" * 59)
for nb21_r in (4, 8, 16, 32, 64, 128, 256):
    nb21_classic = NB21_ALPHA / nb21_r
    nb21_rs = NB21_ALPHA / math.sqrt(nb21_r)
    print(f"{nb21_r:>5}{nb21_classic:>12.4f}{nb21_rs:>16.4f}{nb21_rs / nb21_classic:>26.2f}")

print()
print("Зі зростанням r класичний масштаб падає як 1/r, а rsLoRA — лише як 1/sqrt(r).")
print("Це і є причина, чому use_rslora=True дозволяє піднімати ранг, не втрачаючи силу адаптера.")
'''
    ),
    md(
        """
### Структура `LoraConfig`: реальні поля або довідник із джерел

Нижче — перелік полів, які згадані в документації PEFT і Transformers. Якщо `peft` встановлено,
ми показуємо **справжні** поля класу; якщо ні — надрукований довідник із джерел.
"""
    ),
    code(
        '''
# Поля LoraConfig, згадані в джерелах (назва -> що робить).
NB21_LORA_FIELDS = {
    "r": "ранг update-матриць; визначає кількість тренованих параметрів",
    "lora_alpha": "множник масштабу; разом із r дає alpha/r (або alpha/sqrt(r) для rsLoRA)",
    "target_modules": "список назв модулів, regex або 'all-linear' (QLoRA-стиль)",
    "target_parameters": "цілі-параметри nn.Parameter (MoE-експерти); 2- або 3-вимірні",
    "lora_dropout": "dropout на LoRA-гілці",
    "bias": "які зсуви тренувати; у прикладі джерела — 'none'",
    "modules_to_save": "модулі, які донавчаються ПОВНІСТЮ (наприклад, lm_head)",
    "init_lora_weights": "схема ініціалізації: типова (Kaiming-uniform A + нулі B), "
                         "'gaussian', False (лише для налагодження), 'pissa', 'mica', 'corda', "
                         "'olora', 'eva'",
    "use_rslora": "масштаб alpha/sqrt(r) замість alpha/r",
    "rank_pattern": "ранеги окремих шарів; ключі — regex",
    "alpha_pattern": "alpha окремих шарів; ключі — regex",
    "layer_replication": "розширення моделі дублюванням шарів",
    "trainable_token_indices": "тренувати лише вказані токени ембедингів",
    "ensure_weight_tying": "чи тримати зв'язані ваги (embed_tokens / lm_head) зв'язаними",
    "task_type": "тип задачі, наприклад TaskType.CAUSAL_LM або рядок 'CAUSAL_LM'",
}

print("Довідник полів LoraConfig із джерел:")
for nb21_k, nb21_v in NB21_LORA_FIELDS.items():
    print(f"  {nb21_k:24} {nb21_v}")

print()
try:
    import dataclasses
    from peft import LoraConfig

    nb21_real = sorted(f.name for f in dataclasses.fields(LoraConfig))
    print(f"peft встановлено: у справжньому LoraConfig {len(nb21_real)} полів")
    print("Згадані в джерелах поля, яких немає у класі:",
          sorted(set(NB21_LORA_FIELDS) - set(nb21_real)) or "немає")
    print("Приклад конфігурації з документації:")
    nb21_cfg = LoraConfig(r=16, lora_alpha=16, target_modules=["query", "value"],
                          lora_dropout=0.1, bias="none")
    print(" ", {k: v for k, v in nb21_cfg.to_dict().items()
                if k in ("r", "lora_alpha", "target_modules", "lora_dropout", "bias")})
except ImportError:
    print("peft НЕ ВСТАНОВЛЕНО — вище надруковано довідник полів із джерел.")
except Exception as nb21_err:                     # noqa: BLE001
    print("peft встановлено, але конфігурацію зібрати не вдалося:", type(nb21_err).__name__,
          nb21_err)
'''
    ),

    # ── 21.3 ─────────────────────────────────────────────────────────────
    md(
        """
## 21.3 Формати даних SFT і маскування міток

`SFTTrainer` приймає чотири формати: стандартне мовне моделювання (`text`), розмовне мовне
моделювання (`messages`), стандартний prompt-completion (`prompt` + `completion`) і розмовний
prompt-completion. З розмовним набором тренер сам застосовує chat template; якщо prompt і
completion передані окремо, вони **конкатенуються перед токенізацією**.

Далі — механіка, яку найлегше зіпсувати: втрати рахуються на послідовності, зсунутій на один токен
вправо, а токени доповнення виключаються через ignore index зі значенням `-100`. Прапорці
`assistant_only_loss=True` і `completion_only_loss` керують тим, які саме позиції отримають `-100`.
"""
    ),
    code(
        '''
# Розбір чотирьох форматів вручну — без datasets, щоб було видно структуру.
NB21_SFT_SAMPLES = [
    {"text": "The sky is blue."},
    {"messages": [{"role": "user", "content": "What color is the sky?"},
                  {"role": "assistant", "content": "It is blue."}]},
    {"prompt": "The sky is", "completion": " blue."},
    {"prompt": [{"role": "user", "content": "What color is the sky?"}],
     "completion": [{"role": "assistant", "content": "It is blue."}]},
]


def nb21_sft_format(sample: dict) -> str:
    """Визначає формат прикладу так, як це робить SFTTrainer: за наявними полями."""
    if "text" in sample:
        return "стандартне мовне моделювання (text)"
    if "messages" in sample:
        return "розмовне мовне моделювання (messages)"
    if isinstance(sample.get("prompt"), str):
        return "стандартний prompt-completion"
    if isinstance(sample.get("prompt"), list):
        return "розмовний prompt-completion"
    return "не підтримується: потрібне поле text або пара prompt/completion"


print("Приклад -> розпізнаний формат")
print("-" * 70)
for nb21_s in NB21_SFT_SAMPLES:
    nb21_keys = ", ".join(nb21_s)
    print(f"[{nb21_keys}] -> {nb21_sft_format(nb21_s)}")

# Розмовність визначається типом елементів: словники з role/content.
nb21_msgs = NB21_SFT_SAMPLES[1]["messages"]
nb21_roles = [nb21_msg["role"] for nb21_msg in nb21_msgs]
print()
print("Ролі у розмовному прикладі:", nb21_roles)
print("Втрати будуть лише на ролях assistant, якщо assistant_only_loss=True.")
'''
    ),
    code(
        '''
# Маскування: будуємо послідовність «токенів» (тут — слова, щоб позиції було видно)
# і позначаємо, які позиції входять у функцію втрат.
NB21_IGNORE = -100        # ignore index за замовчуванням у SFT

NB21_CONVO = [
    {"role": "system", "content": "Ти асистент."},
    {"role": "user", "content": "Скільки буде 2 + 2 ?"},
    {"role": "assistant", "content": "4"},
]

NB21_TOKENS, NB21_SUPERVISED = [], []
for nb21_turn in NB21_CONVO:
    nb21_piece = nb21_turn["content"].split() + ["<|end|>"]
    NB21_TOKENS += nb21_piece
    NB21_SUPERVISED += [nb21_turn["role"] == "assistant"] * len(nb21_piece)

print(f"{'поз':>4} {'токен':<12} {'у втратах':>10} {'мітка':>8}")
print("-" * 40)
for nb21_i, nb21_tok in enumerate(NB21_TOKENS):
    nb21_lab = NB21_TOKENS[nb21_i] if NB21_SUPERVISED[nb21_i] else NB21_IGNORE
    print(f"{nb21_i:>4} {nb21_tok:<12} {str(NB21_SUPERVISED[nb21_i]):>10} {nb21_lab:>8}")

# Зсув на один токен: вхід — усі токени без останнього, ціль — усі мітки без першої.
NB21_INPUTS = NB21_TOKENS[:-1]
NB21_LABELS = [NB21_TOKENS[nb21_i] if NB21_SUPERVISED[nb21_i] else NB21_IGNORE
               for nb21_i in range(1, len(NB21_TOKENS))]

print()
print("Після зсуву на один токен:")
name_width = 10
print(f"{'вхід':<{name_width}} -> ціль")
for nb21_x, nb21_y in zip(NB21_INPUTS, NB21_LABELS):
    nb21_shown = "<IGNORE -100>" if nb21_y == NB21_IGNORE else nb21_y
    print(f"{nb21_x:<{name_width}} -> {nb21_shown}")

nb21_kept = sum(1 for nb21_y in NB21_LABELS if nb21_y != NB21_IGNORE)
nb21_mask_frac = nb21_kept / len(NB21_LABELS)
print()
print(f"Позицій у функції втрат: {nb21_kept} із {len(NB21_LABELS)} ({100 * nb21_mask_frac:.1f}%)")
print("Якщо assistant_only_loss вимкнути, ця частка стане 100% — модель вчитиметься")
print("відтворювати і system, і user. Це найдешевша помилка, щоб зіпсувати SFT.")
'''
    ),
    md(
        """
### Конфігурація SFT: реальні поля або довідник із джерел
"""
    ),
    code(
        '''
# Поля SFTConfig, згадані в джерелах.
NB21_SFT_FIELDS = {
    "output_dir": "каталог для чекпойнтів",
    "learning_rate": "для адаптерів джерело радить близько 1e-4 — вище, ніж при повному донавчанні",
    "packing": "True — пакувати кілька прикладів у одну послідовність",
    "assistant_only_loss": "True — втрати лише на відповідях асистента; вимагає "
                            "{% generation %} і {% endgeneration %} у chat template",
    "completion_only_loss": "типово True для prompt-completion; False — тренувати всю послідовність",
    "loss_type": "типово 'chunked_nll'; є 'nll' і 'dft'; з use_liger_kernel типовим стає 'nll'",
    "max_length": "обмеження довжини; для VLM джерело радить None, щоб не зрізати токени зображень",
    "chat_template_path": "джерело chat template для інструкційного тренування",
    "eos_token": "узгодження EOS із шаблоном, наприклад '<|im_end|>' для Qwen2.5-1.5B",
    "model_init_kwargs": "kwargs для AutoModelForCausalLM.from_pretrained, "
                         "наприклад {'dtype': torch.bfloat16}",
}

print("Довідник полів SFTConfig із джерел:")
for nb21_k, nb21_v in NB21_SFT_FIELDS.items():
    print(f"  {nb21_k:22} {nb21_v}")

print()
try:
    import dataclasses
    from trl import SFTConfig

    nb21_sft_real = sorted(f.name for f in dataclasses.fields(SFTConfig))
    print(f"trl встановлено: у справжньому SFTConfig {len(nb21_sft_real)} полів")
    print("Згадані в джерелах поля, яких немає у класі:",
          sorted(set(NB21_SFT_FIELDS) - set(nb21_sft_real)) or "немає")
except ImportError:
    print("trl НЕ ВСТАНОВЛЕНО — вище надруковано довідник полів із джерел.")
except Exception as nb21_err:                     # noqa: BLE001
    print("trl встановлено, але поля прочитати не вдалося:", type(nb21_err).__name__, nb21_err)

print()
print("Метрики тренування SFT (логує сам тренер):")
for nb21_m in ("global_step", "epoch", "num_tokens", "loss", "entropy", "aux_loss",
               "mean_token_accuracy", "learning_rate", "grad_norm"):
    print("  -", nb21_m)
'''
    ),

    # ── 21.4 ─────────────────────────────────────────────────────────────
    md(
        """
## 21.4 DPO: пари переваг і роль `beta`

DPO працює на preference-наборі: промпт плюс бажане завершення (`chosen`) і небажане (`rejected`).
Документація радить **явний** промпт, але підтримує й неявний, коли промпт входить до обох
завершень. Втрата:

`L = -log sigmoid( beta * ( log(pi_chosen / ref_chosen) - log(pi_rejected / ref_rejected) ) )`

де `beta > 0` керує силою сигналу переваги. Порахуємо її на фіксованих числах і подивимося, що саме
робить `beta`.
"""
    ),
    code(
        '''
import math

NB21_DPO_PAIRS = [
    {"prompt": "The sky is", "chosen": " blue.", "rejected": " green."},
    {"chosen": "The sky is blue.", "rejected": "The sky is green."},
    {"prompt": [{"role": "user", "content": "What color is the sky?"}],
     "chosen": [{"role": "assistant", "content": "It is blue."}],
     "rejected": [{"role": "assistant", "content": "It is green."}]},
]


def nb21_dpo_format(pair: dict) -> str:
    """Розрізняє стандартний і розмовний формат і явний/неявний промпт."""
    nb21_conv = isinstance(pair.get("chosen"), list)
    nb21_kind = "розмовний" if nb21_conv else "стандартний"
    nb21_prompt = "явний промпт" if "prompt" in pair else "неявний промпт (у обох завершеннях)"
    return f"{nb21_kind}, {nb21_prompt}"


print("Формати preference-прикладів, які приймає DPOTrainer:")
for nb21_p in NB21_DPO_PAIRS:
    print("  -", nb21_dpo_format(nb21_p))

print()
print("Обов'язкові поля: chosen і rejected. Явний prompt — рекомендований варіант.")


def nb21_dpo_loss(logp_chosen, logp_rejected, ref_chosen, ref_rejected, beta):
    """Втрата DPO за явною формулою з документації. Повертає (loss, margin)."""
    nb21_margin = beta * ((logp_chosen - ref_chosen) - (logp_rejected - ref_rejected))
    nb21_loss = -math.log(1.0 / (1.0 + math.exp(-nb21_margin)))
    return nb21_loss, nb21_margin


# Один приклад: модель підняла бажане завершення і опустила небажане відносно референсу.
NB21_LOGPC, NB21_LOGPR = -1.20, -2.40
NB21_REFC, NB21_REFR = -1.50, -1.90

print()
print(f"{'beta':>7}{'margin':>10}{'loss':>10}{'accuracy пари':>18}")
print("-" * 45)
for nb21_beta in (0.01, 0.05, 0.1, 0.5, 1.0):
    nb21_loss, nb21_margin = nb21_dpo_loss(NB21_LOGPC, NB21_LOGPR, NB21_REFC, NB21_REFR, nb21_beta)
    print(f"{nb21_beta:>7.2f}{nb21_margin:>10.4f}{nb21_loss:>10.4f}"
          f"{'1.0 (margin > 0)':>18}")

print()
print("Метрика rewards/accuracies — це частка пар, де неявна нагорода бажаного варіанта вища.")
print("Метрика rewards/margins — середній розрив цих нагород (тут це margin).")
print("Запам'ятайте: DPO переважно ПРИДУШУЄ небажане, а не підвищує бажане — видно з формули.")
'''
    ),
    code(
        '''
# А тепер випадок деградації: модель опускає ОБИДВА варіанти, але небажаний — сильніше.
# Точність переваг зростає, а абсолютна правдоподібність бажаного падає.
NB21_STEPS = [
    ("крок 0 (старт)", -1.50, -1.90, -1.50, -1.90),
    ("крок 100",       -1.20, -2.40, -1.50, -1.90),
    ("крок 300",       -1.80, -3.60, -1.50, -1.90),
    ("крок 600",       -2.60, -5.20, -1.50, -1.90),
]

print(f"{'етап':16}{'margin':>10}{'loss':>10}{'logps/chosen':>15}{'висновок':>28}")
print("-" * 80)
for nb21_label, nb21_c, nb21_rj, nb21_rc, nb21_rr in NB21_STEPS:
    nb21_loss, nb21_margin = nb21_dpo_loss(nb21_c, nb21_rj, nb21_rc, nb21_rr, 0.1)
    nb21_verdict = "норма" if nb21_c >= nb21_rc else "logps/chosen нижче референсу"
    print(f"{nb21_label:16}{nb21_margin:>10.4f}{nb21_loss:>10.4f}{nb21_c:>15.2f}{nb21_verdict:>28}")

print()
print("Це і є причина, чому в DPO дивляться не лише на rewards/accuracies, а й на logps/chosen:")
print("зростання margin за одночасного падіння logps/chosen означає, що модель відсуває обидва")
print("варіанти, а не підвищує бажаний.")
'''
    ),
    code(
        '''
# Поля DPOConfig, згадані в джерелах.
NB21_DPO_FIELDS = {
    "beta": "сила сигналу переваги; у формулі втрат",
    "loss_type": "типово 'sigmoid'; також 'hinge', 'ipo', 'exo_pair', 'nca_pair', 'robust', "
                 "'bco_pair', 'sppo_hard', 'aot', 'aot_unpaired', 'apo_zero', 'apo_down', "
                 "'discopop', 'sft', 'sigmoid_norm'. Можна передати СПИСОК",
    "loss_weights": "ваги для комбінації кількох втрат (приклад MPO: [0.8, 0.2, 1.0])",
    "label_smoothing": "потрібен для 'exo_pair' (> 0.0) і 'robust' ([0.0, 0.5))",
    "learning_rate": "для адаптерів джерело радить близько 1e-5 — нижче, ніж у SFT",
    "sync_ref_model": "не сумісний із precompute_ref_log_probs=True і з PEFT без окремого ref_model",
    "precompute_ref_log_probs": "не підтримується з IterableDataset",
    "use_weighting": "не підтримується з 'aot' і 'aot_unpaired'",
    "model_init_kwargs": "kwargs для from_pretrained, наприклад {'dtype': torch.bfloat16}",
    "max_length": "для VLM — None, щоб не зрізати токени зображень",
}

print("Довідник полів DPOConfig із джерел:")
for nb21_k, nb21_v in NB21_DPO_FIELDS.items():
    print(f"  {nb21_k:26} {nb21_v}")

print()
print("Комбінація втрат (приклад MPO з документації):")
print("  loss_type=['sigmoid', 'bco_pair', 'sft'], loss_weights=[0.8, 0.2, 1.0]")

print()
try:
    import dataclasses
    from trl import DPOConfig

    nb21_dpo_real = sorted(f.name for f in dataclasses.fields(DPOConfig))
    print(f"trl встановлено: у справжньому DPOConfig {len(nb21_dpo_real)} полів")
    print("Згадані в джерелах поля, яких немає у класі:",
          sorted(set(NB21_DPO_FIELDS) - set(nb21_dpo_real)) or "немає")
except ImportError:
    print("trl НЕ ВСТАНОВЛЕНО — вище надруковано довідник полів із джерел.")
except Exception as nb21_err:                     # noqa: BLE001
    print("trl встановлено, але поля прочитати не вдалося:", type(nb21_err).__name__, nb21_err)
'''
    ),

    # ── 21.5 ─────────────────────────────────────────────────────────────
    md(
        """
## 21.5 GRPO: перевага всередині групи

GRPO — онлайн-алгоритм: на кожному кроці для кожного промпту генерується набір із `G` завершень,
кожне отримує нагороду, і перевага рахується відносно групи:

`A_i = (r_i - mean(r)) / std(r)`

Документація додає дві поправки: ділення на `std` може створювати зсув за складністю питання
(`scale_rewards=False` вимикає його, але разом із ним зникає нормалізація дисперсії), а варіант
`scale_rewards="batch"` рахує середнє на груповому рівні, а стандартне відхилення — на рівні батча.
Порахуємо всі три режими на одному батчі.
"""
    ),
    code(
        '''
import statistics

# Два промпти в батчі: легкий (усі відповіді правильні) і середній (одна з чотирьох хибна).
NB21_GRPO_BATCH = {
    "легкий (усі 1)": [1.0, 1.0, 1.0, 1.0],
    "середній (3 з 4)": [1.0, 0.0, 1.0, 1.0],
}


def nb21_advantages(rewards_by_prompt, mode="group"):
    """Три режими з джерела: 'group' (std групи), 'batch' (std батча), False (без std)."""
    nb21_all = [x for nb21_v in rewards_by_prompt.values() for x in nb21_v]
    nb21_batch_std = statistics.pstdev(nb21_all)
    nb21_out = {}
    for nb21_name, nb21_rs in rewards_by_prompt.items():
        nb21_mean = statistics.fmean(nb21_rs)
        nb21_std = statistics.pstdev(nb21_rs)
        if mode == "group":
            nb21_div = nb21_std
        elif mode == "batch":
            nb21_div = nb21_batch_std
        else:
            nb21_div = 1.0
        nb21_out[nb21_name] = [None if nb21_div == 0 else (x - nb21_mean) / nb21_div
                               for x in nb21_rs]
    return nb21_out


for nb21_mode in ("group", "batch", False):
    nb21_label = "scale_rewards=False" if nb21_mode is False else f"scale_rewards='{nb21_mode}'"
    print(nb21_label)
    nb21_res = nb21_advantages(NB21_GRPO_BATCH, nb21_mode)
    for nb21_name, nb21_adv in nb21_res.items():
        nb21_shown = ["немає (std=0)" if nb21_a is None else f"{nb21_a:+.3f}" for nb21_a in nb21_adv]
        print(f"  {nb21_name:18} нагороди={NB21_GRPO_BATCH[nb21_name]} -> A={nb21_shown}")
    print()

print("Група з однаковими нагородами дає нульовий сигнал: std=0, ділення неможливе,")
print("і всі переваги дорівнюють нулю. Це і є метрика frac_reward_zero_std.")
nb21_zero = sum(1 for nb21_rs in NB21_GRPO_BATCH.values()
                if statistics.pstdev(nb21_rs) == 0) / len(NB21_GRPO_BATCH)
print(f"frac_reward_zero_std для цього батча: {nb21_zero:.2f}")
'''
    ),
    md(
        """
### Функції нагороди: контракт

Функція нагороди мусить приймати ключові аргументи й повертати **список чисел з плаваючою комою** —
по одному на кожне завершення. Обов'язкові аргументи: `prompts`, `completions`, `completion_ids`,
`trainer_state`, `log_extra`, `log_metric`, `environments` (коли задано `environment_factory`),
а також **усі колонки набору, крім `prompt`**. Найпростіший спосіб відповідати вимозі — `**kwargs`.
Перевіримо контракт на прикладах із документації.
"""
    ),
    code(
        '''
import re


def nb21_reward_length(completion_ids, **kwargs):
    """Нагорода за довжину в токенах: довші завершення отримують більше."""
    return [float(len(nb21_ids)) for nb21_ids in completion_ids]


def nb21_reward_chars(completions, **kwargs):
    """Те саме, але за кількістю символів."""
    return [float(len(nb21_c)) for nb21_c in completions]


def nb21_reward_format(completions, **kwargs):
    """Форматна нагорода у стилі DeepSeek-R1: чи є блоки think та answer."""
    nb21_pattern = r"^<think>.*?</think><answer>.*?</answer>$"
    nb21_contents = [nb21_c[0]["content"] for nb21_c in completions]
    return [1.0 if re.match(nb21_pattern, nb21_c) else 0.0 for nb21_c in nb21_contents]


NB21_PROMPTS = ["The sky is", "The sun is"]
NB21_COMPLETIONS = [" blue.", " in the sky."]
NB21_COMPLETION_IDS = [[6303, 13], [304, 279, 12884, 13]]

print("Приклад із документації — очікуваний вивід [2.0, 4.0]:")
print(" ", nb21_reward_length(completion_ids=NB21_COMPLETION_IDS, prompts=NB21_PROMPTS,
                              completions=NB21_COMPLETIONS))
print("Приклад із документації — очікуваний вивід [6.0, 12.0]:")
print(" ", nb21_reward_chars(completions=NB21_COMPLETIONS, prompts=NB21_PROMPTS,
                             completion_ids=NB21_COMPLETION_IDS))

NB21_ANSWER_COMPLETIONS = [
    [{"role": "assistant",
      "content": "<think>1 + 2 = 3, множимо на 4, маємо 12.</think><answer>(1 + 2) * 4 = 12</answer>"}],
    [{"role": "assistant",
      "content": "Сума 3 і 1 дорівнює 4, множимо на 2 і маємо 8."}],
]
print("Форматна нагорода — очікуваний вивід [1.0, 0.0]:")
print(" ", nb21_reward_format(completions=NB21_ANSWER_COMPLETIONS))

# Перевірка контракту: список float тієї самої довжини, що й батч.
for nb21_fname, nb21_f, nb21_kw in (
    ("nb21_reward_length", nb21_reward_length,
     {"completion_ids": NB21_COMPLETION_IDS, "prompts": NB21_PROMPTS,
      "completions": NB21_COMPLETIONS}),
    ("nb21_reward_chars", nb21_reward_chars,
     {"completions": NB21_COMPLETIONS, "prompts": NB21_PROMPTS,
      "completion_ids": NB21_COMPLETION_IDS}),
):
    nb21_out = nb21_f(**nb21_kw)
    print(f"{nb21_fname}: список={isinstance(nb21_out, list)}, "
          f"довжина={len(nb21_out)} (батч={len(NB21_PROMPTS)}), "
          f"усі float={all(isinstance(x, float) for x in nb21_out)}")
'''
    ),
    code(
        '''
# Поля GRPOConfig і варіанти цілі, згадані в джерелах.
NB21_GRPO_FIELDS = {
    "reward_funcs": "функція нагороди (або їх список); можна взяти готову з trl.rewards",
    "beta": "коефіцієнт члена KL; типове значення 0.0 — член KL не використовується",
    "scale_rewards": "True (типово, std групи), False (без std), 'batch' (std на рівні батча)",
    "loss_type": "'grpo' (базова), 'dapo' (токен-рівнева), 'dr_grpo' (ділення на константу), "
                 "'sapo' (м'яке керування), 'cispo', 'vespo'",
    "num_iterations": "скільки оновлень після однієї генерації; при 1 clipped-ціль "
                      "зводиться до базової",
    "use_vllm": "прискорення генерації через vLLM (головне вузьке місце онлайн-методів)",
    "vllm_mode": "'colocate' (типово, vLLM у процесі тренера) або 'server' (окремий процес)",
    "vllm_gpu_memory_utilization": "частка пам'яті GPU для vLLM; джерело радить додавати буфер",
    "vllm_enable_sleep_mode": "вивантажувати параметри й кеш vLLM під час кроку оптимізації",
    "vllm_importance_sampling_correction": "корекція розбіжності тренування-інференсу (типово увімкнена)",
    "vllm_importance_sampling_mode": "варіант корекції (truncate/mask) і гранулярність (token/sequence)",
    "use_transformers_continuous_batching": "альтернатива vLLM: безперервне батчування Transformers",
    "mask_truncated_completions": "виключати замасковані послідовності з метрики entropy",
}

print("Довідник полів GRPOConfig із джерел:")
for nb21_k, nb21_v in NB21_GRPO_FIELDS.items():
    print(f"  {nb21_k:38} {nb21_v}")

print()
print("Ціль GRPO гілкується за loss_type — що це змінює:")
NB21_LOSS_NOTES = {
    "базова": "середнє по групі від середнього по довжині: має зсув за довжиною; літерал у джерелі "
              "не наведено — «не вдалося підтвердити»",
    "dapo": "токен-рівнева нормалізація: краще на довгих ланцюжках міркувань",
    "dr_grpo": "ділення на константу (максимальна довжина): зсув за довжиною прибрано повністю",
    "sapo": "м'яке керування з асиметричними температурами tau_pos=1.0, tau_neg=1.05",
}
for nb21_k, nb21_v in NB21_LOSS_NOTES.items():
    print(f"  {nb21_k:10} {nb21_v}")

print()
try:
    import dataclasses
    from trl import GRPOConfig

    nb21_grpo_real = sorted(f.name for f in dataclasses.fields(GRPOConfig))
    print(f"trl встановлено: у справжньому GRPOConfig {len(nb21_grpo_real)} полів")
    print("Згадані в джерелах поля, яких немає у класі:",
          sorted(set(NB21_GRPO_FIELDS) - set(nb21_grpo_real)) or "немає")
except ImportError:
    print("trl НЕ ВСТАНОВЛЕНО — вище надруковано довідник полів із джерел.")
except Exception as nb21_err:                     # noqa: BLE001
    print("trl встановлено, але поля прочитати не вдалося:", type(nb21_err).__name__, nb21_err)
'''
    ),

    # ── 21.6 ─────────────────────────────────────────────────────────────
    md(
        """
## 21.6 Оцінювання «до і після»: що саме міряти

Retention — не додаток до тренування, а його третій обов'язковий крок у списку з документації PEFT.
Нижче — сітка з цільової метрики й суміжних задач, яку треба зняти **до** тренування, і таблиця
вбудованих метрик, за якими видно деградацію кожного методу.
"""
    ),
    code(
        '''
# Сітка «до / після». Числа тут — приклад заповненої сітки, структура — головне.
NB21_EVAL_GRID = [
    # (задача, метрика, до тренування, після тренування)
    ("цільова: класифікація інцидентів", "accuracy", 0.71, 0.94),
    ("суміжна: слідування інструкціям", "accuracy", 0.88, 0.84),
    ("суміжна: виклик інструментів", "accuracy", 0.82, 0.60),
    ("суміжна: довгий контекст (32k)", "accuracy", 0.76, 0.58),
    ("суміжна: відмова від небезпечних запитів", "refusal rate", 0.97, 0.91),
]

print(f"{'задача':40}{'метрика':>14}{'до':>8}{'після':>8}{'дельта':>9}{'':>4}")
print("-" * 84)
for nb21_task, nb21_metric, nb21_before, nb21_after in NB21_EVAL_GRID:
    nb21_delta = nb21_after - nb21_before
    nb21_flag = "!!" if nb21_delta <= -0.05 else ""
    print(f"{nb21_task:40}{nb21_metric:>14}{nb21_before:>8.2f}{nb21_after:>8.2f}"
          f"{nb21_delta:>+9.2f}{nb21_flag:>4}")

nb21_target = NB21_EVAL_GRID[0]
nb21_side = NB21_EVAL_GRID[1:]
nb21_worst = min(nb21_side, key=lambda nb21_row: nb21_row[3] - nb21_row[2])
print()
print(f"Цільова метрика: {nb21_target[2]:.2f} -> {nb21_target[3]:.2f} "
      f"({nb21_target[3] - nb21_target[2]:+.2f})")
print(f"Найгірша суміжна: {nb21_worst[0]} ({nb21_worst[3] - nb21_worst[2]:+.2f})")
print("Правило: якщо цільова метрика вгору, а суміжна вниз — це катастрофічне забування,")
print("а не «побічний ефект». Такий чекпойнт у продакшн не випускають.")
'''
    ),
    code(
        '''
# Метрики-індикатори деградації по методах (назви — з джерел).
NB21_DEGRADATION = [
    ("SFT", "loss падає, entropy -> 0",
     "модель упевнено відтворює шаблон, а не відповідає на запит"),
    ("SFT", "assistant_only_loss вимкнено випадково",
     "у втрати потрапили system і user — модель вчиться ставити питання"),
    ("DPO", "rewards/accuracies росте, logps/chosen падає",
     "модель відсуває ОБИДВА варіанти, а не підвищує бажаний"),
    ("DPO", "rewards/margins росте, довжина відповідей росте",
     "зсув за довжиною; перевірте loss_type='sigmoid_norm'"),
    ("GRPO", "frac_reward_zero_std високий",
     "у більшості груп усі відповіді однаково правильні — сигналу немає"),
    ("GRPO", "completions/mean_length росте, clipped_ratio росте",
     "політика виграє довжиною, а не якістю"),
    ("GRPO", "sampling/sampling_logp_difference/mean росте",
     "розширюється розбіжність тренування-інференсу (vLLM); перевірте importance sampling"),
    ("будь-який", "retention на суміжних задачах падає",
     "катастрофічне забування: звузьте цілі, зменште ранг або змініть ініціалізацію"),
]

print(f"{'метод':10}{'спостереження':52}{'що це означає'}")
print("-" * 124)
for nb21_method, nb21_symptom, nb21_meaning in NB21_DEGRADATION:
    print(f"{nb21_method:10}{nb21_symptom:52}{nb21_meaning}")

print()
print("Прийоми проти забування з джерел:")
print("  - ініціалізація CorDA в режимі KPM: пом'якшує катастрофічне забування знань про світ")
print("  - KappaTuneSelector / find_kappa_target_modules: обирає найбільш ізотропні шари,")
print("    залишаючи спеціалізовані анізотропні недоторканими")
print("  - менший ранг і менше епох, якщо деградація спричинена перетренуванням")
'''
    ),

    # ── 21.7 ─────────────────────────────────────────────────────────────
    md(
        """
## 21.7 Злиття адаптерів і деплой

`merge_and_unload` вписує ваги адаптера в базову модель і повертає модель без обгортки; ваги
адаптера в пам'яті при цьому не залишаються. Дві деталі з джерела критичні: результат треба
**присвоїти змінній** (операція не in-place), а для MoE-шарів є `merge_adapter()`, який знімає
накладні витрати PEFT. Подивимося на варіанти деплою як на рішення з ціною.
"""
    ),
    code(
        '''
# Артефакти адаптера: що саме лежить у чекпойнті PEFT.
NB21_ADAPTER_ARTIFACTS = {
    "adapter_model.safetensors": "ваги адаптера — усе, що тренувалося",
    "adapter_config.json": "конфігурація; from_pretrained читає з неї base_model_name_or_path",
    "base model": "НЕ входить у чекпойнт — його завантажують окремо",
    "tokenizer": "потрібен разом із базовою моделлю (і chat template, якщо він змінювався)",
}

print("Чекпойнт адаптера:")
for nb21_k, nb21_v in NB21_ADAPTER_ARTIFACTS.items():
    print(f"  {nb21_k:26} {nb21_v}")

print()
print("Підтверджене поле adapter_config.json за джерелом — base_model_name_or_path.")
print("Повний перелік полів цього файлу в джерелах не наведено — «не вдалося підтвердити».")

NB21_DEPLOY = [
    ("злита модель", "повна модель", "немає", "одна задача, максимальна продуктивність"),
    ("база + адаптер окремо", "база + десятки МБ", "є, якщо не злито",
     "багато задач на одній базі"),
    ("hotswap у слоті", "база + адаптер", "немає перекомпіляції", "перемикання під навантаженням"),
    ("кілька адаптерів", "база + N адаптерів у RAM", "витрати пам'яті на всі",
     "A/B-порівняння, маршрутизація"),
    ("квантизована база + LoRA", "менша база + адаптер", "залежить від бекенду",
     "не вистачає VRAM (розділ 20)"),
]

print()
print(f"{'варіант':26}{'що на диску':24}{'час на інференсі':26}{'коли брати'}")
print("-" * 112)
for nb21_v, nb21_disk, nb21_lat, nb21_when in NB21_DEPLOY:
    print(f"{nb21_v:26}{nb21_disk:24}{nb21_lat:26}{nb21_when}")

print()
print("Hotswap: лише LoRA; target_rank — найбільший ранг серед усіх адаптерів (типово 128);")
print("enable_peft_hotswap треба викликати ДО завантаження першого адаптера і ДО torch.compile.")
'''
    ),
    code(
        '''
# Перевірка доступності злиття: реальна операція вимагає моделі з мережі, тому захищена.
NB21_MERGE_RECIPE = """
from peft import PeftModel
from transformers import AutoModelForCausalLM

base_model = AutoModelForCausalLM.from_pretrained("mistralai/Mistral-7B-v0.1")
model = PeftModel.from_pretrained(base_model, "alignment-handbook/zephyr-7b-sft-lora")
model = model.merge_and_unload()      # не in-place: результат обов'язково присвоїти
model.save_pretrained("./merged-model")
"""

print("Рецепт злиття з документації PEFT:")
print(NB21_MERGE_RECIPE)

try:
    from peft import PeftModel  # noqa: F401
    print("peft встановлено: рецепт вище готовий до запуску (потрібна мережа й пам'ять під модель).")
except ImportError:
    print("peft НЕ ВСТАНОВЛЕНО: рецепт наведено для довідки, запуск потребує pip install peft.")
except Exception as nb21_err:                     # noqa: BLE001
    print("peft імпортовано з помилкою:", type(nb21_err).__name__, nb21_err)
'''
    ),

    # ── Реальне тренування (захищено) ────────────────────────────────────
    md(
        """
## Реальне тренування (потребує GPU, мережі та встановлених бібліотек)

Ця клітинка за замовчуванням нічого не робить: вона перевіряє умови й друкує, чого не вистачає.
Щоб справді запустити тренування, виставте `NB21_RUN_TRAINING=1` — тоді буде завантажено маленьку
модель із Hub і виконано кілька кроків SFT. Усе загорнуто в `try/except`, тому помилка середовища
не зламає виконання ноутбука.
"""
    ),
    code(
        '''
import os

NB21_RUN_TRAINING = os.environ.get("NB21_RUN_TRAINING", "") == "1"

print("NB21_RUN_TRAINING =", NB21_RUN_TRAINING)
print()
print("Що потрібно для справжнього тренування:")
print("  1. torch з доступною CUDA (GPU обов'язковий для навчання)");
print("  2. пакети: trl, peft, transformers, datasets, accelerate");
print("  3. мережа — модель і набір завантажуються з Hub (або локальний кеш)");
print("  4. годинник часу: за даними джерела GRPO на 0.5B і 8 GPU займає близько доби")

nb21_ready = {"torch": False, "cuda": False, "trl": False, "peft": False, "datasets": False}
try:
    import torch as nb21_torch2
    nb21_ready["torch"] = True
    nb21_ready["cuda"] = bool(nb21_torch2.cuda.is_available())
except ImportError:
    pass
for nb21_pkg in ("trl", "peft", "datasets"):
    try:
        __import__(nb21_pkg)
        nb21_ready[nb21_pkg] = True
    except ImportError:
        pass

print()
print("Стан середовища:", nb21_ready)

if not NB21_RUN_TRAINING:
    print()
    print("Тренування пропущено (NB21_RUN_TRAINING != 1). Це очікувана поведінка.")
else:
    try:
        from datasets import load_dataset
        from peft import LoraConfig
        from trl import SFTConfig, SFTTrainer

        nb21_train_ds = load_dataset("trl-lib/Capybara", split="train[:32]")
        nb21_trainer = SFTTrainer(
            model="Qwen/Qwen3-0.6B",
            args=SFTConfig(
                output_dir="out-nb21-sft",
                max_steps=5,
                per_device_train_batch_size=1,
                learning_rate=1e-4,
                assistant_only_loss=True,
                loss_type="chunked_nll",
                report_to=[],
            ),
            train_dataset=nb21_train_ds,
            peft_config=LoraConfig(),
        )
        nb21_trainer.train()
        print("Тренування завершено. Дивіться втрати та mean_token_accuracy вище.")
    except Exception as nb21_train_err:           # noqa: BLE001
        print("Тренування не виконано:", type(nb21_train_err).__name__)
        print(nb21_train_err)
        print("Найчастіші причини: немає GPU, немає мережі, не встановлено trl/peft.")
'''
    ),

    # ── самоперевірка ────────────────────────────────────────────────────
    md(
        """
## Самоперевірка

Перевіряємо твердження розділу: каскад рішень, арифметику LoRA на реальній геометрії моделі, масштаб
rsLoRA, формати даних і маскування втрат, формулу DPO та її деградацію, переваги GRPO, сітку
евалюації й артефакти адаптера.
"""
    ),
    code(
        r'''
# ── 1. Каскад рішень: спершу промпт, тренування — останнім ──────────────
nb21c_rec = {nb21c_task: nb21_recommend(nb21c_ans) for nb21c_task, nb21c_ans in NB21_CASES.items()}
assert (
    len(NB21_CASCADE) == 5 and len(NB21_CASES) == 4
    and nb21c_rec["класифікація інцидентів у JSON"].startswith("звичайний промпт")
    and nb21c_rec["відповіді за внутрішніми регламентами"].startswith("RAG або пошук")
    and nb21c_rec["власні маркери <|start_think|>"].startswith("layer tuning")
    and nb21c_rec["стиль і тон підтримки"].startswith("adapter-метод (LoRA)")
    and nb21_recommend(dict(поведінка_а_не_факти=True, модель_уже_вміє=True,
                            хочемо_зекономити_токени=True)).startswith("prompt-based метод")
), "задача про факти мусить відправляти в RAG, а не в донавчання"
print("✓ каскад: 5 воріт; факти → RAG, наявна поведінка → промпт, нові токени → layer tuning, "
      "стиль → LoRA")

# ── 2. Геометрія реальної моделі з метаданих Hub ────────────────────────
assert (
    NB21_MIN["id"] == "google/gemma-4-12B-it"
    and (NB21_H, NB21_HD, NB21_QDIM, NB21_KVDIM, NB21_INTER) == (3840, 256, 4096, 2048, 15360)
    and NB21_LAYERS == 48 and NB21_TOTAL == 11_959_730_224
    and NB21_QDIM == NB21_MIN["c_num_attention_heads"] * NB21_HD
    and NB21_KVDIM == NB21_MIN["c_num_key_value_heads"] * NB21_HD
    and NB21_KVDIM * 2 == NB21_QDIM                     # GQA: kv-голів удвічі менше
    and set(NB21_SHAPES) == {"q_proj", "k_proj", "v_proj", "o_proj",
                             "gate_proj", "up_proj", "down_proj"}
), "q_dim = голови × head_dim, kv_dim менший за q_dim (GQA)"
print("✓ геометрія: hidden 3840, head_dim 256, q_dim 4096, kv_dim 2048 (GQA), "
      "intermediate 15360, 48 шарів, 11 959 730 224 параметрів")

# ── 3. Скільки параметрів тренує LoRA ───────────────────────────────────
nb21c_qv16 = nb21_lora_params(16, NB21_TARGET_SETS["q_proj + v_proj (зумовлені цілі)"])
nb21c_all16 = nb21_lora_params(16, NB21_TARGET_SETS["all-linear (QLoRA-стиль)"])
assert (
    nb21c_qv16 == 10_616_832 and nb21c_all16 == 65_470_464
    and round(100 * nb21c_qv16 / NB21_TOTAL, 4) == 0.0888
    and round(100 * nb21c_all16 / NB21_TOTAL, 4) == 0.5474
    and len(NB21_TARGET_SETS) == 3
    and nb21_lora_params(64, NB21_TARGET_SETS["all-linear (QLoRA-стиль)"]) == 261_881_856
), "q+v, r=16 дає 10 616 832 параметри — 0.0888% від моделі"
print("✓ LoRA: q+v при r=16 — 10 616 832 (0.0888%), all-linear — 65 470 464 (0.5474%); "
      "all-linear при r=64 — 261 881 856")

# ── 4. Параметри лінійні за рангом, і LoRA — не повне донавчання ────────
nb21c_lin = [nb21_lora_params(nb21c_r, NB21_TARGET_SETS["q_proj + v_proj (зумовлені цілі)"])
             for nb21c_r in (4, 8, 16, 32, 64, 128)]
assert (
    all(nb21c_b == 2 * nb21c_a for nb21c_a, nb21c_b in zip(nb21c_lin, nb21c_lin[1:]))
    and nb21c_lin[0] == 2_654_208
    and round(NB21_TOTAL / nb21c_lin[1]) == 2253          # q+v, r=8
    and round(NB21_TOTAL / nb21c_all16) == 183            # all-linear, r=16
    and nb21c_all16 > nb21c_lin[2]                        # all-linear більше за q+v при тому ж r
), "подвоєння рангу мусить рівно подвоювати кількість тренованих параметрів"
print("✓ лінійність: кожен крок рангу ×2.00; проти повного донавчання q+v r=8 — у 2 253 рази "
      "менше, all-linear r=16 — у 183 рази")

# ── 5. Пам'ять під стани оптимізатора залежить від тренованих параметрів ─
nb21c_opt = {nb21c_label: (nb21c_n * NB21_BYTES_ADAMW / NB21_GIB,
                           nb21c_n * NB21_BYTES_ADAM8 / NB21_GIB)
             for nb21c_label, nb21c_n in NB21_OPT_ROWS}
assert (
    NB21_BYTES_ADAMW == 12 and NB21_BYTES_ADAM8 == 4 and len(NB21_OPT_ROWS) == 4
    and round(nb21c_opt["LoRA q+v, r=16"][0], 2) == 0.12
    and round(nb21c_opt["LoRA all-linear, r=16"][0], 2) == 0.73
    and round(nb21c_opt["LoRA all-linear, r=64"][0], 2) == 2.93
    and round(nb21c_opt["повне донавчання"][0], 2) == 133.66
    and round(nb21c_opt["повне донавчання"][1], 2) == 44.55
    and nb21c_opt["повне донавчання"][0] > 100 * nb21c_opt["LoRA all-linear, r=16"][0]
), "стани оптимізатора рахуються від ТРЕНОВАНИХ параметрів, а не від розміру моделі"
print("✓ пам'ять: AdamW fp32 — 0.12/0.73/2.93 GiB для LoRA проти 133.66 GiB для повного "
      "донавчання; 8-бітний Adam — 44.55 GiB (у 3 рази менше)")

# ── 6. rsLoRA: масштаб падає як 1/sqrt(r), а не як 1/r ──────────────────
nb21c_scale = {nb21c_r: (NB21_ALPHA / nb21c_r, NB21_ALPHA / math.sqrt(nb21c_r))
               for nb21c_r in (4, 16, 256)}
assert (
    NB21_ALPHA == 16
    and nb21c_scale[4] == (4.0, 8.0) and nb21c_scale[16] == (1.0, 4.0)
    and nb21c_scale[256] == (0.0625, 1.0)
    and round(nb21c_scale[4][1] / nb21c_scale[4][0], 2) == 2.00
    and round(nb21c_scale[256][1] / nb21c_scale[256][0], 2) == 16.00
    and nb21c_scale[256][0] < nb21c_scale[16][0] < nb21c_scale[4][0]
), "класичний масштаб падає як 1/r, rsLoRA — лише як 1/sqrt(r)"
print("✓ rsLoRA: при r=16 класичний масштаб 1.0 проти 4.0 у rsLoRA; "
      "перевага зростає з 2.00 (r=4) до 16.00 (r=256)")

# ── 7. Довідник полів LoraConfig із джерел ──────────────────────────────
assert (
    len(NB21_LORA_FIELDS) == 15
    and {"r", "lora_alpha", "target_modules", "target_parameters", "lora_dropout", "bias",
         "modules_to_save", "init_lora_weights", "use_rslora", "rank_pattern", "alpha_pattern",
         "layer_replication", "trainable_token_indices", "ensure_weight_tying",
         "task_type"} == set(NB21_LORA_FIELDS)
    and "'all-linear'" in NB21_LORA_FIELDS["target_modules"]
    and "'corda'" in NB21_LORA_FIELDS["init_lora_weights"]
    and "'none'" in NB21_LORA_FIELDS["bias"]
    and "alpha/sqrt(r)" in NB21_LORA_FIELDS["use_rslora"]
    and "MoE" in NB21_LORA_FIELDS["target_parameters"]
), "довідник мусить містити 15 полів LoraConfig, згаданих у джерелах"
print("✓ LoraConfig: 15 полів; серед них target_parameters (MoE), use_rslora, "
      "trainable_token_indices і 8 схем init_lora_weights")

# ── 8. SFT: формати прикладів і маскування втрат ────────────────────────
nb21c_formats = [nb21_sft_format(nb21c_s) for nb21c_s in NB21_SFT_SAMPLES]
assert (
    nb21c_formats == ["стандартне мовне моделювання (text)",
                      "розмовне мовне моделювання (messages)",
                      "стандартний prompt-completion",
                      "розмовний prompt-completion"]
    and nb21_sft_format({}).startswith("не підтримується")
    and [nb21c_msg["role"] for nb21c_msg in NB21_SFT_SAMPLES[1]["messages"]] == ["user", "assistant"]
    and NB21_IGNORE == -100 and len(NB21_TOKENS) == 12 and len(NB21_LABELS) == 11
    and nb21_kept == 2 and round(nb21_mask_frac, 3) == 0.182
    and [nb21c_i for nb21c_i, nb21c_sup in enumerate(NB21_SUPERVISED) if nb21c_sup] == [10, 11]
    and NB21_LABELS[9] == "4" and NB21_LABELS[10] == "<|end|>"
    and sum(1 for nb21c_y in NB21_LABELS if nb21c_y != NB21_IGNORE) == 2
), "у функцію втрат мусять входити лише токени assistant — 2 з 11"
print("✓ SFT: 4 формати розпізнано, порожній приклад відхилено; у втратах 2 позиції з 11 "
      "(18.2%) — лише відповідь асистента і її EOS")

# ── 9. Довідник полів SFTConfig і метрики тренера ───────────────────────
assert (
    len(NB21_SFT_FIELDS) == 10
    and "{% generation %}" in NB21_SFT_FIELDS["assistant_only_loss"]
    and "'chunked_nll'" in NB21_SFT_FIELDS["loss_type"]
    and "1e-4" in NB21_SFT_FIELDS["learning_rate"]
    and "'dtype'" in NB21_SFT_FIELDS["model_init_kwargs"]
    and "'<|im_end|>'" in NB21_SFT_FIELDS["eos_token"]
    and "None" in NB21_SFT_FIELDS["max_length"]
), "assistant_only_loss вимагає розмітки {% generation %} у chat template"
print("✓ SFTConfig: 10 полів; loss_type типово 'chunked_nll', learning_rate ≈ 1e-4, "
      "assistant_only_loss потребує {% generation %} у шаблоні")

# ── 10. DPO: формати пар і явна формула втрат ───────────────────────────
nb21c_dpo_formats = [nb21_dpo_format(nb21c_p) for nb21c_p in NB21_DPO_PAIRS]
nb21c_loss01, nb21c_margin01 = nb21_dpo_loss(NB21_LOGPC, NB21_LOGPR, NB21_REFC, NB21_REFR, 0.1)
nb21c_loss1, nb21c_margin1 = nb21_dpo_loss(NB21_LOGPC, NB21_LOGPR, NB21_REFC, NB21_REFR, 1.0)
assert (
    nb21c_dpo_formats == ["стандартний, явний промпт",
                          "стандартний, неявний промпт (у обох завершеннях)",
                          "розмовний, явний промпт"]
    and all("chosen" in nb21c_p and "rejected" in nb21c_p for nb21c_p in NB21_DPO_PAIRS)
    and round(nb21c_margin01, 4) == 0.0800 and round(nb21c_loss01, 4) == 0.6539
    and round(nb21c_margin1, 4) == 0.8000 and round(nb21c_loss1, 4) == 0.3711
    and abs(nb21c_margin1 - 10 * nb21c_margin01) < 1e-12            # margin лінійний за beta
    and nb21c_loss1 < nb21c_loss01
    and round(nb21_dpo_loss(NB21_LOGPC, NB21_LOGPR, NB21_REFC, NB21_REFR, 0.0)[0], 4) == \
        round(math.log(2), 4)                            # margin = 0 → loss = -log(1/2)
), "втрата DPO мусить бути -log sigmoid(beta * margin)"
print(f"✓ DPO: формати — стандартний/розмовний з явним і неявним промптом; beta=0.1 → "
      f"margin {nb21c_margin01:.4f}, loss {nb21c_loss01:.4f}; beta=1.0 → loss {nb21c_loss1:.4f}")

# ── 11. Деградація: margin росте, а logps/chosen падає ──────────────────
nb21c_steps = [(nb21c_label, *nb21_dpo_loss(nb21c_c, nb21c_rj, nb21c_rc, nb21c_rr, 0.1))
               for nb21c_label, nb21c_c, nb21c_rj, nb21c_rc, nb21c_rr in NB21_STEPS]
nb21c_margins = [nb21c_margin for _, _, nb21c_margin in nb21c_steps]
nb21c_deltas = [nb21c_after - nb21c_before for _, _, nb21c_before, nb21c_after in NB21_EVAL_GRID]
nb21c_worst = min(range(1, len(NB21_EVAL_GRID)), key=lambda nb21c_i: nb21c_deltas[nb21c_i])
assert (
    nb21c_margins == sorted(nb21c_margins) and round(nb21c_margins[-1], 4) == 0.2200
    and round(nb21c_steps[0][1], 4) == 0.6931 and round(nb21c_steps[0][2], 4) == 0.0000
    and [nb21c_row[1] for nb21c_row in NB21_STEPS] == [-1.50, -1.20, -1.80, -2.60]
    and round(nb21c_deltas[0], 2) == 0.23 and round(nb21c_deltas[nb21c_worst], 2) == -0.22
    and nb21c_worst == 2 and sum(1 for nb21c_d in nb21c_deltas if nb21c_d <= -0.05) == 3
    and len(NB21_DEGRADATION) == 8
    and {nb21c_method for nb21c_method, _, _ in NB21_DEGRADATION} == {"SFT", "DPO", "GRPO",
                                                                     "будь-який"}
), "зростання margin за падіння logps/chosen = модель відсуває обидва варіанти"
print("✓ деградація: margin 0.00 → 0.22 при падінні logps/chosen −1.50 → −2.60; у сітці 5 задач, "
      "цільова +0.23, найгірша суміжна −0.22, три суміжні перетнули поріг −0.05")

# ── 12. GRPO: переваги за трьома режимами масштабування ────────────────
nb21c_group = nb21_advantages(NB21_GRPO_BATCH, "group")
nb21c_batch = nb21_advantages(NB21_GRPO_BATCH, "batch")
nb21c_none = nb21_advantages(NB21_GRPO_BATCH, False)
assert (
    len(NB21_GRPO_BATCH) == 2
    and nb21c_group["легкий (усі 1)"] == [None] * 4      # std = 0 → ділення неможливе
    and [round(nb21c_a, 3) for nb21c_a in nb21c_group["середній (3 з 4)"]] == \
        [0.577, -1.732, 0.577, 0.577]
    and [round(nb21c_a, 3) for nb21c_a in nb21c_batch["середній (3 з 4)"]] == \
        [0.756, -2.268, 0.756, 0.756]
    and [round(nb21c_a, 3) for nb21c_a in nb21c_none["середній (3 з 4)"]] == \
        [0.25, -0.75, 0.25, 0.25]
    and round(nb21_zero, 2) == 0.50
    and nb21c_batch["легкий (усі 1)"] == [0.0] * 4       # std батча не нульовий
), "група з однаковими нагородами дає нульовий сигнал (std=0)"
print("✓ GRPO: група з std=0 → переваги не визначені; 3 з 4 → +0.577/−1.732 (група), "
      "+0.756/−2.268 (батч), +0.250/−0.750 (без std); frac_reward_zero_std = 0.50")

# ── 13. Функції нагороди й контракт, який вимагає trl ──────────────────
nb21c_len = nb21_reward_length(completion_ids=NB21_COMPLETION_IDS, prompts=NB21_PROMPTS,
                               completions=NB21_COMPLETIONS)
nb21c_chars = nb21_reward_chars(completions=NB21_COMPLETIONS, prompts=NB21_PROMPTS,
                                completion_ids=NB21_COMPLETION_IDS)
nb21c_fmt = nb21_reward_format(completions=NB21_ANSWER_COMPLETIONS)
assert (
    nb21c_len == [2.0, 4.0] and nb21c_chars == [6.0, 12.0] and nb21c_fmt == [1.0, 0.0]
    and all(isinstance(nb21c_out, list) and len(nb21c_out) == len(NB21_PROMPTS)
            and all(isinstance(nb21c_x, float) for nb21c_x in nb21c_out)
            for nb21c_out in (nb21c_len, nb21c_chars, nb21c_fmt))
    and len(NB21_GRPO_FIELDS) == 13
    and "tau_neg=1.05" in NB21_LOSS_NOTES["sapo"]
    and "'dr_grpo'" in NB21_GRPO_FIELDS["loss_type"]
    and "типове значення 0.0" in NB21_GRPO_FIELDS["beta"]
), "функція нагороди мусить повертати список float довжиною з батч"
print("✓ нагороди: length → [2.0, 4.0], chars → [6.0, 12.0], format → [1.0, 0.0]; контракт — "
      "список float на кожен елемент батча; у GRPOConfig 13 полів з джерел")

# ── 14. Артефакти адаптера, деплой, злиття й гейт тренування ────────────
nb21c_deploy = {nb21c_row[0]: nb21c_row for nb21c_row in NB21_DEPLOY}
assert (
    len(NB21_ADAPTER_ARTIFACTS) == 4
    and "НЕ входить у чекпойнт" in NB21_ADAPTER_ARTIFACTS["base model"]
    and "base_model_name_or_path" in NB21_ADAPTER_ARTIFACTS["adapter_config.json"]
    and len(NB21_DEPLOY) == 5
    and nb21c_deploy["злита модель"][1] == "повна модель"
    and nb21c_deploy["hotswap у слоті"][2] == "немає перекомпіляції"
    and "merge_and_unload" in NB21_MERGE_RECIPE
    and "model = model.merge_and_unload()" in NB21_MERGE_RECIPE   # результат присвоєно
    and "save_pretrained" in NB21_MERGE_RECIPE
    and isinstance(NB21_RUN_TRAINING, bool)
    and set(nb21_ready) == {"torch", "cuda", "trl", "peft", "datasets"}
), "чекпойнт адаптера не містить базової моделі; злиття не in-place"
print("✓ деплой: 4 артефакти чекпойнта (база в нього не входить), 5 варіантів; hotswap без "
      "перекомпіляції; рецепт злиття присвоює результат merge_and_unload()")

print()
print("Усі перевірки пройдено.")
'''
    ),

    # ── Підсумок ─────────────────────────────────────────────────────────
    md(
        """
## Підсумок

1. **Каскад, а не стрибок.** Документація PEFT ставить промптинг першим кроком, adapter-методи —
   другим, вимірювання retention — третім. Донавчання змінює поведінку, не додає фактів.
2. **Формула LoRA проста.** `r × (in + out)` на кожен цільовий шар, помножене на кількість блоків.
   На `google/gemma-4-12B-it` цілі `q_proj`+`v_proj` при `r=8` дають 5 308 416 параметрів —
   0,0444% від `params_total`; `all-linear` при `r=32` — 130 940 928, тобто 1,0948%.
3. **Параметри ростуть лінійно за рангом,** а пам'ять під стани оптимізатора залежить від кількості
   тренованих параметрів, а не від розміру моделі: це головна механічна причина економії LoRA.
4. **`lora_alpha` без `r` не має сенсу.** Класичний масштаб — `alpha/r`, rsLoRA — `alpha/sqrt(r)`.
5. **Маскування вирішує, чого вчиться модель.** Зсув на один токен і ignore index `-100`;
   `assistant_only_loss=True` вимагає `{% generation %}` у chat template.
6. **DPO дивиться на пари, а не на еталони.** Головні індикатори — `rewards/accuracies` разом із
   `logps/chosen`; зростання margin за падіння `logps/chosen` означає, що модель відсуває обидва
   варіанти.
7. **GRPO потребує різноманітності в групі.** `frac_reward_zero_std` — перша метрика, на яку варто
   дивитися; базова ціль має зсув за довжиною, `dr_grpo` прибирає його повністю.
8. **Злиття — не in-place.** `model = model.merge_and_unload()`; для MoE — `merge_adapter()`, інакше
   PEFT матеріалізує внесок LoRA для кожного експерта на кожному запиті.

**Куди далі:**

- Розділ 9 — prompt caching: чому довгі інструкції іноді дешевше кешувати, ніж вчити.
- Розділ 12 — tool use: тренування моделей із викликом інструментів і формат `tools`.
- Розділ 16 — RAG: альтернатива донавчанню, коли потрібні факти, а не поведінка.
- Розділ 20 — квантизація: QLoRA, 4-бітна база й 8-бітні оптимізатори.
- Розділ 22 — Hub і Jobs: як вивантажити адаптер і запустити тренування в хмарі.
- Розділ 24 — оцінювання: набори, статистика й витоки — те, без чого 21.6 не працює.

## Джерела

- [PEFT — LoRA (package_reference/lora.md)](https://raw.githubusercontent.com/huggingface/peft/main/docs/source/package_reference/lora.md)
- [PEFT — Parameter efficient fine-tuning methods (overview)](https://raw.githubusercontent.com/huggingface/peft/main/docs/source/methods/overview.md)
- [Transformers — Parameter-efficient fine-tuning](https://raw.githubusercontent.com/huggingface/transformers/main/docs/source/en/peft.md)
- [TRL — SFT Trainer](https://raw.githubusercontent.com/huggingface/trl/main/docs/source/sft_trainer.md)
- [TRL — DPO Trainer](https://raw.githubusercontent.com/huggingface/trl/main/docs/source/dpo_trainer.md)
- [TRL — GRPO Trainer](https://raw.githubusercontent.com/huggingface/trl/main/docs/source/grpo_trainer.md)
- [TRL — індекс документації](https://raw.githubusercontent.com/huggingface/trl/main/docs/source/index.md)
- [LoRA: Low-Rank Adaptation of Large Language Models](https://huggingface.co/papers/2106.09685)
- [Direct Preference Optimization](https://huggingface.co/papers/2305.18290)
- [DeepSeekMath (першоджерело GRPO)](https://huggingface.co/papers/2402.03300)
- [DAPO](https://huggingface.co/papers/2503.14476) · [Understanding R1-Zero-Like Training](https://huggingface.co/papers/2503.20783) · [SAPO](https://huggingface.co/papers/2511.20347)
- [KappaTune](https://arxiv.org/abs/2506.16289) · [CorDA](https://huggingface.co/papers/2406.05223) · [PiSSA](https://huggingface.co/papers/2404.02948)
- PyPI: [peft 0.21.0](https://pypi.org/pypi/peft/json) · [trl 1.14.0](https://pypi.org/pypi/trl/json) · [transformers 5.17.0](https://pypi.org/pypi/transformers/json) · [datasets 5.0.1](https://pypi.org/pypi/datasets/json) · [accelerate 1.15.0](https://pypi.org/pypi/accelerate/json) · [bitsandbytes 0.50.2](https://pypi.org/pypi/bitsandbytes/json)

Локальні копії: `research/hf5_peft_lora.txt`, `research/hf5_peft_methods_overview.txt`,
`research/hf5_tfdoc_peft.txt`, `research/hf5_trl_sft.txt`, `research/hf5_trl_dpo.txt`,
`research/hf5_trl_grpo.txt`, `research/hf5_trl_index.txt`, `research/meta2.json`.
"""
    ),
]
