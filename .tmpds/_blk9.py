# Таблиця кодів -> рішення. Джерело: research/11/openai_error_codes.md,
# research/11/openai_rate_limits.md (розділ "Error mitigation").

RETRYABLE_TYPES = {"rate_limit_error", "server_error", "service_unavailable_error"}

ERRORS = [
    (400, "invalid_request_error", "invalid_service_tier"),
    (401, "invalid_request_error", "invalid_api_key"),
    (401, "invalid_request_error", "ip_not_authorized"),
    (403, "invalid_request_error", "unsupported_country"),
    (429, "rate_limit_error", "rate_limit_exceeded"),
    (429, "rate_limit_error", "slow_down"),
    (429, "insufficient_quota", "credit_balance_exhausted"),
    (429, "insufficient_quota", "organization_spend_limit_exceeded"),
    (429, "insufficient_quota", "project_spend_limit_exceeded"),
    (429, "insufficient_quota", "organization_usage_limit_exceeded"),
    (500, "server_error", "server_error"),
    (503, "service_unavailable_error", "server_is_overloaded"),
]


def decide(status, error_type, error_code, retry_after=None):
    """Повертає (рішення, обґрунтування).

    STOP    — ретрай не допоможе, потрібна дія на боці користувача
    WAIT    — сервер назвав точну затримку
    BACKOFF — затримки немає, будуємо її самі
    """
    if error_type not in RETRYABLE_TYPES:
        return "STOP", f"потрібна дія користувача: {error_code}"
    if retry_after is not None:
        return "WAIT", f"чекати щонайменше {retry_after} с (Retry-After)"
    return "BACKOFF", "експоненційний відкат із джиттером"


print(f"{'HTTP':>4} {'error.type':26} {'error.code':34} {'рішення':8} підстава")
for status, etype, ecode in ERRORS:
    hint = 5 if (status, ecode) == (429, "rate_limit_exceeded") else None
    decision, why = decide(status, etype, ecode, hint)
    print(f"{status:>4} {etype:26} {ecode:34} {decision:8} {why}")

safe = sum(1 for _, t, _ in ERRORS if t in RETRYABLE_TYPES)
print()
print(f"з {len(ERRORS)} кодів ретраїти можна {safe}, "
      f"решта {len(ERRORS) - safe} — ні (ретрай не допоможе)")
