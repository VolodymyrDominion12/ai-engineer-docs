# Сценарій: 20 000 викликів, 6 000 вхідних і 400 вихідних токенів на виклик.
# Ціни за 1M токенів узяті з research/econ/openai_pricing.md,
# research/11/gemini_pricing.md, research/11/deepseek_pricing.md,
# research/econ/mistral_pricing.txt.
CALLS, TOKENS_IN, TOKENS_OUT = 20_000, 6_000, 400

SCENARIOS = [
    ("OpenAI gpt-6-astra (standard)",     10.00,  50.00),
    ("OpenAI gpt-5.6-terra (standard)",    2.00,  12.00),
    ("OpenAI gpt-5.6-luna (standard)",     0.20,   1.20),
    ("OpenAI gpt-5.6-luna (batch/flex)",   0.10,   0.60),
    ("OpenAI gpt-6-astra (fast)",         20.00, 100.00),
    ("Gemini 3.8 Flash (до 31.12.2026)",   0.75,   3.75),
    ("Gemini 3.8 Flash (з 01.01.2027)",    1.50,   7.50),
    ("Gemini 3.8 Flash (batch)",           0.375,  1.875),
    ("DeepSeek V4-Flash (peak)",           0.30,   1.20),
    ("DeepSeek V4-Flash (off-peak)",       0.15,   0.60),
    ("DeepSeek V4-Pro (peak)",             1.32,   3.96),
    ("Mistral Large (приклад із FAQ)",     0.50,   1.50),
]


def cost(pin, pout):
    return (TOKENS_IN / 1e6 * pin + TOKENS_OUT / 1e6 * pout) * CALLS


print(f"Сценарій: {CALLS} викликів × ({TOKENS_IN} вх / {TOKENS_OUT} вих)")
print(f"{'конфігурація':36} {'ціна виклику':>13} {'усього':>10}")
for name, pin, pout in SCENARIOS:
    per_call = TOKENS_IN / 1e6 * pin + TOKENS_OUT / 1e6 * pout
    print(f"{name:36} ${per_call:>12.5f} ${cost(pin, pout):>9.2f}")

totals = [cost(p, o) for _, p, o in SCENARIOS]
print()
print(f"розкид між крайніми конфігураціями: "
      f"${min(totals):.2f} ... ${max(totals):.2f} (×{max(totals) / min(totals):.0f})")
