"""Ноутбук 14 — «MCP — Model Context Protocol».

Розділ довідника: sections/14-mcp.md
Працює без API-ключів, без GPU і без пакета `mcp`.
"""

from nbkit import SETUP_CELL, VERSION_CELL, code, md

FILENAME = "14-mcp.ipynb"
TITLE = "14. MCP — Model Context Protocol"

CELLS = [
    md(
        """
# 14. MCP — Model Context Protocol

**Розділ довідника:** [`sections/14-mcp.md`](../sections/14-mcp.md)

**Потрібно: нічого** — жодних API-ключів, жодного GPU, жодного мережевого доступу.
Ноутбук повністю виконується на стандартній бібліотеці Python і читає локальну копію
JSON-схеми MCP з `research/07/mcp_schema.json.txt`.

Опційна залежність — пакет `mcp` (Python SDK). Клітинка, яка його використовує,
позначена й коректно пропускається, якщо пакета немає. **Усе головне в цьому
ноутбуку від `mcp` не залежить.**

**Що ви зробите:**

1. Розберете справжню JSON-схему ревізії `2026-07-28` (155 визначень) і випишете
   з неї **усі** назви методів — без жодного здогаду.
2. Складете валідний `_meta` і перевірите його тими ключами, які схема оголошує
   обов'язковими.
3. Перевірите кадрування stdio й кодування HTTP-заголовків проти таблиці зі
   специфікації.
4. Перевірите обов'язкові поля примітивів `tools`, `resources`, `prompts`.
5. Проженете узгодження версії, визначення «ери» сервера й MRTR — повний
   двораундовий обмін із захищеним `requestState`.
6. Напишете **мінімальний MCP-сервер і клієнт на stdlib** і побачите реальний
   JSON-RPC-обмін: `server/discover`, `tools/list`, `tools/call` і три різні класи
   збоїв.
"""
    ),
    md("## Налаштування"),
    code(SETUP_CELL),
    code(VERSION_CELL),
    md(
        """
Наступна клітинка завантажує схему один раз і визначає хелпери, якими
користуються всі подальші секції. У файлі перед JSON є рядок-коментар із `SOURCE`,
тому відрізаємо все до першої фігурної дужки.
"""
    ),
    code(
        '''
import json

RAW = (ROOT / "research/07/mcp_schema.json.txt").read_text(encoding="utf-8")
SCHEMA = json.loads(RAW[RAW.index("{"):])
DEFS = SCHEMA["$defs"]

PROTOCOL_VERSION = "2026-07-28"


def ref_name(node: dict) -> str:
    """Ім'я визначення з посилання виду '#/$defs/Tool'."""
    return node["$ref"].rsplit("/", 1)[-1]


def method_of(schema_name: str) -> str:
    """Рядок, який ця схема вимагає в полі 'method'."""
    return DEFS[schema_name]["properties"]["method"]["const"]


def missing_required(schema_name: str, payload: dict) -> list[str]:
    """Які обов'язкові поля цієї схеми відсутні у payload."""
    return [key for key in DEFS[schema_name].get("required", []) if key not in payload]


print("Діалект схеми :", SCHEMA["$schema"])
print("Визначень     :", len(DEFS))
print("Версія протоколу, з якою працює цей ноутбук:", PROTOCOL_VERSION)
'''
    ),

    # ── 14.1 / 14.2 ──────────────────────────────────────────────────────
    md(
        """
## 14.1–14.2 Архітектура та базовий протокол: усе зі схеми

MCP — це JSON-RPC 2.0 з трьома відхиленнями: `id` запиту не може бути `null`,
у кожному `result` є поле `resultType`, а сповіщення не мають `id`.

У ревізії `2026-07-28` протокол **stateless**: рукопожаття `initialize` більше
немає, а версія протоколу й можливості клієнта їдуть у `_meta` **кожного** запиту.
Тому перше, що варто зробити — виписати зі схеми повний перелік методів у кожному
напрямку. Це єдиний спосіб не вигадати назву.
"""
    ),
    code(
        '''
print("Клієнт -> сервер, запити (ClientRequest.anyOf):")
CLIENT_METHODS = set()
for node in DEFS["ClientRequest"]["anyOf"]:
    name = method_of(ref_name(node))
    CLIENT_METHODS.add(name)
    print("   ", name)
print()

print("Клієнт -> сервер, сповіщення (ClientNotification):")
print("   ", method_of("ClientNotification"))
print()

print("Сервер -> клієнт, сповіщення (ServerNotification.anyOf):")
SERVER_NOTIFICATIONS = [method_of(ref_name(n)) for n in DEFS["ServerNotification"]["anyOf"]]
for name in SERVER_NOTIFICATIONS:
    print("   ", name)
print()

ALL_METHOD_CONSTS = {
    schema["properties"]["method"]["const"]
    for schema in DEFS.values()
    if "const" in schema.get("properties", {}).get("method", {})
}
print(f"Усього різних рядків 'method' у схемі: {len(ALL_METHOD_CONSTS)}")
'''
    ),
    md(
        """
Головне тут — **чого немає**. У напрямку «клієнт → сервер» рівно десять запитів і
**одне** сповіщення. Жодного `initialize`, жодного `ping`, жодного
`resources/subscribe`. Це і є архітектурне твердження «сервери не ініціюють
запити», виражене схемою.
"""
    ),
    md(
        """
### `_meta`: обов'язкові поля на кожному запиті

Схема `RequestMetaObject` оголошує рівно два обов'язкові ключі. Запит без будь-якого
з них невалідний: сервер **MUST** відповісти кодом `-32602`, а на HTTP — ще й
статусом `400 Bad Request`.
"""
    ),
    code(
        '''
def client_meta(capabilities: dict) -> dict:
    """Обов'язкова частина _meta, яку несе КОЖЕН запит клієнта."""
    return {
        "io.modelcontextprotocol/protocolVersion": PROTOCOL_VERSION,
        "io.modelcontextprotocol/clientCapabilities": capabilities,
        "io.modelcontextprotocol/clientInfo": {"name": "HandbookClient", "version": "1.0.0"},
    }


def check_required_meta(meta: dict) -> None:
    """Перевіряємо рівно ті ключі, які схема оголошує обов'язковими."""
    required = DEFS["RequestMetaObject"]["required"]
    missing = [key for key in required if key not in meta]
    if missing:
        raise ValueError(f"запит невалідний, бракує: {missing}")


request = {
    "jsonrpc": "2.0",
    "id": "discover-1",
    "method": "server/discover",
    "params": {"_meta": client_meta({})},
}

print("Обов'язкові ключі _meta (зі схеми):", DEFS["RequestMetaObject"]["required"])
check_required_meta(request["params"]["_meta"])
print("Перевірку пройдено.")
print()
print(json.dumps(request, indent=2, ensure_ascii=False))
print()

try:
    check_required_meta({"io.modelcontextprotocol/protocolVersion": PROTOCOL_VERSION})
except ValueError as exc:
    print("А ось що буде, якщо клієнт забуде capabilities:", exc)
'''
    ),
    md(
        """
Зверніть увагу: `capabilities: {}` — це **валідне** значення. Порожній об'єкт
означає «клієнт не підтримує жодної з необов'язкових можливостей». Відсутність поля
— не те саме, що порожній об'єкт.

### Коди помилок, які визначає MCP

Діапазон `-32000…-32099` зарезервований JSON-RPC для серверних помилок, і MCP
розділив його: `-32000…-32019` — **застарілий** (нові коди там створювати
заборонено), `-32020…-32099` — за специфікацією.
"""
    ),
    code(
        '''
def error_code(schema_name: str) -> int:
    """Дістає код помилки зі схеми.

    Частина схем описує сам об'єкт помилки (поле 'code' на верхньому рівні),
    інші — цілу відповідь (поле 'error', усередині якого 'code' задано через allOf).
    """
    props = DEFS[schema_name]["properties"]
    if "error" in props:
        return props["error"]["allOf"][1]["properties"]["code"]["const"]
    return props["code"]["const"]


for schema_name in [
    "ParseError", "InvalidRequestError", "MethodNotFoundError", "InvalidParamsError",
    "InternalError", "HeaderMismatchError",
    "MissingRequiredClientCapabilityError", "UnsupportedProtocolVersionError",
]:
    print(f"{schema_name:38} {error_code(schema_name)}")


print()
print("ServerNotification.anyOf:", len(DEFS["ServerNotification"]["anyOf"]), "типів сповіщень")
'''
    ),

    # ── 14.3 ─────────────────────────────────────────────────────────────
    md(
        """
## 14.3 Транспорти: кадрування stdio і заголовки Streamable HTTP

Семантика повідомлень однакова на всіх транспортах — різниться лише **прив'язка**.
На stdio повідомлення кадрується як один рядок (розділювач — `\\n`, вбудованих
нових рядків бути не повинно), на Streamable HTTP — як окремий POST із
заголовками, які **дублюють** поля тіла, щоб проміжні вузли могли маршрутизувати
запити, не розбираючи тіло.

Значення, яке не можна безпечно подати як ASCII-заголовок, кодується як Base64 у
сентинелі `=?base64?...?=`.
"""
    ),
    code(
        '''
import base64

# ── stdio: одне повідомлення — один рядок ───────────────────────────────────
message = {
    "jsonrpc": "2.0",
    "id": 7,
    "method": "tools/call",
    "params": {"name": "add", "arguments": {"a": 1, "b": 2}},
}
line = json.dumps(message, separators=(",", ":"))
print("Усього рядків у кадрі:", len(line.splitlines()))
print(line)
print()

tricky = json.dumps({"method": "notifications/message", "params": {"text": "line1\\nline2"}})
print("Кадр із вбудованим \\\\n:", tricky)
print("Рядків усе одно:", len(tricky.splitlines()))
print()

# ── Streamable HTTP: Base64-сентинел ────────────────────────────────────────
SENTINEL_PREFIX, SENTINEL_SUFFIX = "=?base64?", "?="


def header_value(value: str) -> str:
    """Кодує значення для Mcp-Name / Mcp-Param-* за правилами Streamable HTTP."""
    safe = (
        value.isascii()
        and value.isprintable()
        and value == value.strip()
        and not (value.startswith(SENTINEL_PREFIX) and value.endswith(SENTINEL_SUFFIX))
    )
    if safe:
        return value
    encoded = base64.b64encode(value.encode("utf-8")).decode("ascii")
    return f"{SENTINEL_PREFIX}{encoded}{SENTINEL_SUFFIX}"


CASES = [
    ("us-west1", "простий ASCII"),
    ("Hello, 世界", "не-ASCII"),
    (" padded ", "пробіли по краях"),
    ("line1\\nline2", "вбудований новий рядок"),
    ("=?base64?literal?=", "схоже на сам сентинел"),
]
for value, why in CASES:
    print(f"{value!r:24} {why:26} -> {header_value(value)}")
'''
    ),
    md(
        """
Чотири закодовані значення **збігаються з таблицею в специфікації** — це найшвидша
перевірка того, що ваша реалізація кодування правильна. Останній рядок показує
окреме правило: значення, яке вже виглядає як сентинел, кодується повторно, інакше
сервер не зміг би відрізнити закодоване значення від буквального.
"""
    ),

    # ── 14.4 ─────────────────────────────────────────────────────────────
    md(
        """
## 14.4 Примітиви: tools, resources, prompts

Розрізняє примітиви не форма, а **хто вирішує ними скористатися**: tools —
модель, resources — застосунок, prompts — користувач. Перевіримо власні
результати саме тими `required`-полями, які оголошує схема.

Зверніть увагу на `ttlMs` і `cacheScope`: у `2026-07-28` вони **обов'язкові** в
результатах усіх п'яти операцій зі списками й читання. Сервер, написаний під
`2025-11-25`, їх не шле.
"""
    ),
    code(
        '''
TOOLS_LIST = {
    "resultType": "complete",
    "tools": [
        {
            "name": "search_books",
            "title": "Пошук у каталозі",
            "description": "Шукає книги за назвою або автором.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Назва або автор."},
                    "limit": {"type": "integer", "default": 10, "minimum": 1, "maximum": 50},
                },
                "required": ["query"],
            },
            "annotations": {"readOnlyHint": True, "openWorldHint": False},
        }
    ],
    "ttlMs": 300_000,
    "cacheScope": "public",
}

RESOURCES_LIST = {
    "resultType": "complete",
    "resources": [
        {"uri": "file:///project/config.json", "name": "config.json",
         "title": "Конфігурація проєкту", "mimeType": "application/json", "size": 412}
    ],
    "ttlMs": 60_000,
    "cacheScope": "private",
}

RESOURCE_TEMPLATES_LIST = {
    "resultType": "complete",
    "resourceTemplates": [
        {"name": "book", "uriTemplate": "books://{title}",
         "description": "Запис каталогу за назвою книги.", "mimeType": "text/plain"}
    ],
    "ttlMs": 60_000,
    "cacheScope": "private",
}

PROMPTS_LIST = {
    "resultType": "complete",
    "prompts": [
        {"name": "code_review", "title": "Ревʼю коду",
         "description": "Просить модель оцінити якість коду.",
         "arguments": [{"name": "code", "description": "Код для ревʼю", "required": True}]}
    ],
    "ttlMs": 600_000,
    "cacheScope": "public",
}

for schema_name, payload in [
    ("ListToolsResult", TOOLS_LIST),
    ("ListResourcesResult", RESOURCES_LIST),
    ("ListResourceTemplatesResult", RESOURCE_TEMPLATES_LIST),
    ("ListPromptsResult", PROMPTS_LIST),
]:
    print(f"{schema_name:28} обов'язкові: {DEFS[schema_name]['required']}")
    print(f"{'':28} бракує      : {missing_required(schema_name, payload) or '—'}")
print()

print("Обов'язкові поля вкладених типів:")
for schema_name in ["Tool", "Resource", "ResourceTemplate", "Prompt", "PromptArgument",
                    "CallToolResult", "TextContent", "ResourceLink", "EmbeddedResource"]:
    print(f"  {schema_name:24} {DEFS[schema_name].get('required')}")
print()

print("Типи вмісту, які може повернути tool (ContentBlock.anyOf):")
print("  ", [ref_name(n) for n in DEFS["ContentBlock"]["anyOf"]])
'''
    ),
    md(
        """
### `isError` — найважливіше семантичне поле

Специфікація формулює правило прямо: помилки, що походять **від самого
інструмента**, **SHOULD** повідомлятися всередині результату з `isError: true`, а
**не** як протокольна помилка MCP — інакше LLM не побачить, що сталася помилка, і не
зможе виправитися. Але помилки **пошуку** інструмента **SHOULD** повідомлятися як
помилка MCP: моделі нема чого виправляти.

Перевіримо це на реальному коді в секції 14.7.
"""
    ),

    # ── 14.5 ─────────────────────────────────────────────────────────────
    md(
        """
## 14.5 Версіонування й сумісність

Ключове речення специфікації: **рукопожаття перемовин не існує**. Кожен запит несе
свою версію, і сервер приймає або відхиляє кожен запит незалежно.

Якщо сервер не реалізує запитану версію, він **MUST** відповісти
`UnsupportedProtocolVersionError` (`-32022`) зі списком підтримуваних версій.
Клієнт **SHOULD** обрати **спільну** версію й повторити.

Окремо про відкат на legacy: його **заборонено** прив'язувати до конкретного коду
помилки — legacy-сервери відповідають на невідомий метод чим завгодно (`-32601`,
`-32602`) або мовчать.
"""
    ),
    code(
        '''
CLIENT_SUPPORTS = ["2026-07-28", "2025-11-25"]
SERVER_SUPPORTS = ["2026-07-28"]


def server_handle(version: str) -> dict:
    """Сервер або обслуговує версію, або перелічує ті, які підтримує."""
    if version in SERVER_SUPPORTS:
        return {"jsonrpc": "2.0", "id": 1,
                "result": {"resultType": "complete", "supportedVersions": SERVER_SUPPORTS}}
    return {
        "jsonrpc": "2.0",
        "id": 1,
        "error": {
            "code": -32022,
            "message": "Unsupported protocol version",
            "data": {"supported": SERVER_SUPPORTS, "requested": version},
        },
    }


def negotiate(preferred: str) -> tuple[str, str]:
    """Один раунд: пробуємо улюблену версію, за відмови обираємо спільну."""
    reply = server_handle(preferred)
    if "error" not in reply:
        return preferred, "погоджено з першої спроби"
    advertised = reply["error"]["data"]["supported"]
    mutual = [v for v in advertised if v in CLIENT_SUPPORTS]
    if not mutual:
        raise RuntimeError("спільної версії немає — показуємо помилку користувачеві")
    return mutual[0], f"сервер відповів -32022, відкотились на {mutual[0]}"


for preferred in ("2026-07-28", "1900-01-01", "2025-11-25"):
    version, note = negotiate(preferred)
    print(f"клієнт просив {preferred:12} -> {version:12} ({note})")
print()

print("Тіло помилки, яке отримує клієнт:")
print(json.dumps(server_handle("1900-01-01")["error"], ensure_ascii=False))
'''
    ),
    md(
        """
### Визначення «ери» сервера на stdio

Специфікація вводить три терміни: **modern** (версія й можливості як per-request
метадані, `2026-07-28` і пізніші), **legacy** (сесія через рукопожаття `initialize`,
`2025-11-25` і раніші) і **dual-era** (обидві).

На stdio проба робиться через `server/discover` і має рівно три результати.
Визначення ери — властивість **сервера**, а не окремого запиту, тому результат
**SHOULD** кешуватися.
"""
    ),
    code(
        '''
def probe_stdio(server_kind: str) -> str:
    """server/discover як проба: три можливі результати (mcp_stdio.md)."""
    if server_kind == "modern":
        return "modern: DiscoverResult -> беремо версію з supportedVersions"
    if server_kind == "modern-old":
        return "modern: UnsupportedProtocolVersionError -> НЕ відкочуємось на initialize"
    return "legacy: будь-яка інша помилка або таймаут -> initialize-рукопожаття"


for kind in ("modern", "modern-old", "legacy"):
    print(f"{kind:12} -> {probe_stdio(kind)}")
print()


def validate_header(header: str | None, body_version: str) -> dict:
    """На HTTP заголовок MCP-Protocol-Version мусить збігатися з тілом."""
    if header is None:
        return {"code": -32020, "message": "Header mismatch: MCP-Protocol-Version missing"}
    if header != body_version:
        return {"code": -32020,
                "message": f"Header mismatch: MCP-Protocol-Version '{header}' does not match "
                           f"body value '{body_version}'"}
    return {}


for header, body in [("2026-07-28", "2026-07-28"), ("2025-11-25", "2026-07-28"), (None, "2026-07-28")]:
    print(f"header={str(header):12} body={body:12} -> {validate_header(header, body) or 'OK'}")
'''
    ),

    # ── 14.6 ─────────────────────────────────────────────────────────────
    md(
        """
## 14.6 Скасування та MRTR

**MRTR** (multi-round-trip requests) — це те, чим замінили ініційовані сервером
запити. Сервер не кличе клієнта: він **повертає** йому питання у відповіді на його
ж запит (`resultType: "input_required"`, поле `inputRequests`), а клієнт **повторює**
той самий запит, доклавши відповіді в `inputResponses`.

Поле `requestState` — непрозорий рядок, який клієнт лише переносить. Специфікація
вимагає від сервера трактувати його як **підконтрольний зловмиснику ввід** і
захищати цілісність (HMAC або AEAD), якщо він впливає на авторизацію, доступ до
ресурсів або бізнес-логіку.

Нижче — повний двораундовий обмін і демонстрація того, що буде з підміненим станом.
"""
    ),
    code(
        '''
import hashlib
import hmac
import time

SECRET = b"key-from-env-not-hardcoded-in-real-code"
TEMPERATURE_SAMPLE = 21.5          # «зовнішній» ресурс, який потрібен інструменту


def seal_state(payload: dict) -> str:
    """Підписуємо стан; клієнт його лише переносить і не має читати."""
    body = json.dumps({**payload, "exp": time.time() + 600}, sort_keys=True).encode()
    return f"{body.decode()}|{hmac.new(SECRET, body, hashlib.sha256).hexdigest()}"


def open_state(token: str) -> dict:
    """Будь-яка підміна або прострочення — відмова, а не тихе прийняття."""
    body, _, signature = token.rpartition("|")
    expected = hmac.new(SECRET, body.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected):
        raise ValueError("requestState не пройшов перевірку цілісності")
    payload = json.loads(body)
    if payload["exp"] < time.time():
        raise ValueError("requestState прострочений")
    return payload


def call_tool(params: dict) -> dict:
    """Обробник tools/call, який уміє відповісти InputRequiredResult."""
    answers = params.get("inputResponses") or {}
    if "city" not in answers:
        return {
            "resultType": "input_required",
            "inputRequests": {
                "city": {
                    "method": "elicitation/create",
                    "params": {
                        "mode": "form",
                        "message": "Для якого міста показати температуру?",
                        "requestedSchema": {
                            "type": "object",
                            "properties": {"name": {"type": "string"}},
                            "required": ["name"],
                        },
                    },
                }
            },
            "requestState": seal_state({"tool": "get_temperature", "args_digest": "d41d8cd9"}),
        }
    # Другий раунд: стан мусить повернутися незміненим.
    state = open_state(params["requestState"])
    assert state["tool"] == "get_temperature", "стан виданий для іншого інструмента"
    city = answers["city"]["content"]["name"]
    return {
        "resultType": "complete",
        "content": [{"type": "text", "text": f"{city}: {TEMPERATURE_SAMPLE} °C"}],
        "structuredContent": {"city": city, "celsius": TEMPERATURE_SAMPLE},
    }


def drive(rounds_limit: int = 5) -> dict:
    """Цикл, який SDK прогоняє за вас: повторювати, поки не прийде complete."""
    params: dict = {"name": "get_temperature", "arguments": {"units": "celsius"}}
    for _ in range(rounds_limit):
        result = call_tool(params)
        print("  resultType:", result["resultType"])
        if result["resultType"] == "complete":
            return result
        params = {
            "name": params["name"],
            "arguments": params["arguments"],              # ті самі аргументи
            "inputResponses": {"city": {"action": "accept", "content": {"name": "Київ"}}},
            "requestState": result["requestState"],        # луна без змін
        }
    raise RuntimeError("перевищено ліміт раундів")


print("=== MRTR: два раунди одного tools/call")
final = drive()
print("  фінал     :", final["content"][0]["text"])
print()

print("=== той самий requestState, підмінений клієнтом")
sealed = call_tool({"name": "get_temperature", "arguments": {}})["requestState"]
tampered = sealed.replace('"get_temperature"', '"delete_database"')
try:
    call_tool({"name": "get_temperature", "arguments": {},
               "inputResponses": {"city": {"action": "accept", "content": {"name": "Київ"}}},
               "requestState": tampered})
except ValueError as exc:
    print("  відмова   :", exc)
print()

print("=== скасування запиту (stdio)")
cancel = {"jsonrpc": "2.0", "method": "notifications/cancelled",
          "params": {"requestId": "123", "reason": "User requested cancellation"}}
print(" ", json.dumps(cancel, ensure_ascii=False))
print("  id у сповіщенні:", "id" in cancel, "(сповіщення не має id)")
'''
    ),
    md(
        """
У другому раунді клієнт надсилає **ті самі** `name` та `arguments` — повтор це
буквально той самий виклик, а не новий метод. Єдина відмінність на дроті: JSON-RPC
`id` **MUST** бути іншим, бо це незалежні запити.

`InputRequiredResult` можуть повертати лише три запити: `prompts/get`,
`resources/read` і `tools/call`. Для будь-яких інших сервер **MUST NOT** його слати.
"""
    ),

    # ── 14.7 ─────────────────────────────────────────────────────────────
    md(
        """
## 14.7 Мінімальний MCP-сервер і клієнт на stdlib

Тепер зберемо все разом. Сервер мусить уміти рівно сім речей:

1. читати по одному JSON-RPC-повідомленню на рядок;
2. перевіряти обов'язкові поля `_meta` **перед** диспетчеризацією;
3. перевіряти версію протоколу й повертати `-32022` зі списком підтримуваних;
4. диспетчеризувати метод; невідомий — `-32601`;
5. класти в кожен `result` поле `resultType`, а в списки — ще `ttlMs` і `cacheScope`;
6. розрізняти збій виконання інструмента (`isError: true`) від протокольної помилки;
7. писати логи у `stderr`, а в `stdout` — лише MCP-повідомлення.

Транспорт змодельовано двома чертами замість `stdin`/`stdout` підпроцесу: семантика
кадрування та сама, але приклад детермінований і не потребує запуску процесу.
"""
    ),
    code(
        '''
SERVER_INFO = {"name": "handbook-demo", "version": "0.1.0"}

# ── Примітиви, які оголошує сервер ──────────────────────────────────────────
TOOLS = {
    "add": {
        "name": "add",
        "title": "Додавання двох чисел",
        "description": "Повертає суму двох цілих чисел.",
        "inputSchema": {
            "type": "object",
            "properties": {"a": {"type": "integer"}, "b": {"type": "integer"}},
            "required": ["a", "b"],
            "additionalProperties": False,
        },
        "annotations": {"readOnlyHint": True, "openWorldHint": False},
    }
}


def tool_add(arguments: dict) -> int:
    return arguments["a"] + arguments["b"]


TOOL_IMPLS = {"add": tool_add}


class RpcError(Exception):
    """Протокольна помилка: те, що модель не може виправити (на відміну від isError)."""

    def __init__(self, code: int, message: str, data: dict | None = None) -> None:
        super().__init__(message)
        self.code, self.message, self.data = code, message, data

    def to_response(self, request_id) -> dict:
        error = {"code": self.code, "message": self.message}
        if self.data is not None:
            error["data"] = self.data
        return {"jsonrpc": "2.0", "id": request_id, "error": error}


class DemoServer:
    """Найменший сервер, який усе ще говорить справжнім MCP."""

    def capabilities(self) -> dict:
        return {"tools": {"listChanged": False}}

    def handle(self, message: dict) -> dict | None:
        """Диспетчер: вхідне повідомлення -> вихідне (або None для сповіщення)."""
        method = message.get("method")
        if method is None:                     # це відповідь або сміття
            return None
        request_id = message.get("id")
        params = message.get("params") or {}

        try:
            self._check_meta(params)
            result = self._dispatch(method, params)
        except RpcError as exc:
            return exc.to_response(request_id)

        return {"jsonrpc": "2.0", "id": request_id,
                "result": {**result, "_meta": {"io.modelcontextprotocol/serverInfo": SERVER_INFO}}}

    @staticmethod
    def _check_meta(params: dict) -> None:
        """Кожен запит мусить нести обов'язкові поля _meta — до диспетчеризації."""
        meta = params.get("_meta") or {}
        for key in ("io.modelcontextprotocol/protocolVersion",
                    "io.modelcontextprotocol/clientCapabilities"):
            if key not in meta:
                raise RpcError(-32602, f"missing required _meta field: {key}")
        version = meta["io.modelcontextprotocol/protocolVersion"]
        if version != PROTOCOL_VERSION:
            raise RpcError(-32022, "Unsupported protocol version",
                           {"requested": version, "supported": [PROTOCOL_VERSION]})

    def _dispatch(self, method: str, params: dict) -> dict:
        if method == "server/discover":
            return {
                "resultType": "complete",
                "supportedVersions": [PROTOCOL_VERSION],
                "capabilities": self.capabilities(),
                "instructions": "Демонстраційний сервер довідника.",
                "ttlMs": 3_600_000,
                "cacheScope": "public",
            }
        if method == "tools/list":
            return {"resultType": "complete", "tools": list(TOOLS.values()),
                    "ttlMs": 300_000, "cacheScope": "public"}
        if method == "tools/call":
            return self._call_tool(params)
        raise RpcError(-32601, f"Method not found: {method}")

    def _call_tool(self, params: dict) -> dict:
        name = params.get("name")
        tool = TOOLS.get(name)
        if tool is None:
            # Помилка ПОШУКУ інструмента — це протокольна помилка, а не isError.
            raise RpcError(-32602, f"Unknown tool: {name!r}")
        arguments = params.get("arguments") or {}
        missing = [k for k in tool["inputSchema"]["required"] if k not in arguments]
        if missing:
            return {"resultType": "complete", "isError": True,
                    "content": [{"type": "text",
                                 "text": f"Invalid arguments, missing: {missing}"}]}
        try:
            value = TOOL_IMPLS[name](arguments)
        except Exception as exc:                       # збій виконання -> isError
            return {"resultType": "complete", "isError": True,
                    "content": [{"type": "text",
                                 "text": f"Error executing tool {name}: {exc}"}]}
        return {"resultType": "complete",
                "content": [{"type": "text", "text": str(value)}],
                "structuredContent": {"result": value}}


# ── Транспорт: дві черги замість stdin/stdout ───────────────────────────────
class Pipe:
    """Односпрямований канал newline-delimited JSON-RPC."""

    def __init__(self) -> None:
        self._frames: list[str] = []

    def write(self, message: dict) -> None:
        frame = json.dumps(message, separators=(",", ":"))
        assert "\\n" not in frame, "кадр stdio не може містити вбудованих нових рядків"
        self._frames.append(frame)

    def read(self) -> dict | None:
        return json.loads(self._frames.pop(0)) if self._frames else None


to_server, to_client = Pipe(), Pipe()
server = DemoServer()


def rpc(method: str, params: dict | None = None, request_id: int = 1) -> dict:
    """Повний оберт: клієнт пише кадр, сервер обробляє, клієнт читає кадр."""
    params = dict(params or {})
    params["_meta"] = {
        "io.modelcontextprotocol/protocolVersion": PROTOCOL_VERSION,
        "io.modelcontextprotocol/clientCapabilities": {},
        "io.modelcontextprotocol/clientInfo": {"name": "HandbookClient", "version": "1.0.0"},
    }
    to_server.write({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params})
    reply = server.handle(to_server.read())
    if reply is not None:
        to_client.write(reply)
    return to_client.read()


print("Демонстраційний сервер готовий. Транспорт — дві черги в пам'яті.")
'''
    ),
    md("Тепер проженемо реальний обмін."),
    code(
        '''
print("=== server/discover")
discover = rpc("server/discover")
print(json.dumps(discover, indent=2, ensure_ascii=False))
print()

print("=== tools/list")
listing = rpc("tools/list", request_id=2)
print("resultType      :", listing["result"]["resultType"])
print("ttlMs/cacheScope:", listing["result"]["ttlMs"], "/", listing["result"]["cacheScope"])
print("Інструменти     :", [t["name"] for t in listing["result"]["tools"]])
print()

print("=== tools/call (успіх)")
ok = rpc("tools/call", {"name": "add", "arguments": {"a": 2, "b": 3}}, request_id=3)
print(json.dumps(ok["result"], indent=2, ensure_ascii=False))
print()

print("=== tools/call (бракує аргументу)")
bad_args = rpc("tools/call", {"name": "add", "arguments": {"a": 2}}, request_id=4)
print("isError:", bad_args["result"]["isError"], "|", bad_args["result"]["content"][0]["text"])
print()

print("=== невідомий метод")
unknown = rpc("tools/nonexistent", request_id=5)
print(json.dumps(unknown, ensure_ascii=False))
print()

print("=== стара версія протоколу")
params = {"_meta": {"io.modelcontextprotocol/protocolVersion": "1900-01-01",
                    "io.modelcontextprotocol/clientCapabilities": {}}}
to_server.write({"jsonrpc": "2.0", "id": 6, "method": "tools/list", "params": params})
print(json.dumps(server.handle(to_server.read()), ensure_ascii=False))
print()

print("=== невідомий інструмент (протокольна помилка, не isError)")
unknown_tool = rpc("tools/call", {"name": "divide", "arguments": {}}, request_id=7)
print(json.dumps(unknown_tool, ensure_ascii=False))
'''
    ),
    md(
        """
Ось воно — розділення, яке найчастіше плутають:

| Ситуація | Що повертає сервер | Що бачить модель |
|---|---|---|
| Бракує аргументу | `result` з `isError: true` і текстом | Помилку; може виправитися й повторити |
| Інструмент не існує | `error` з `-32602` | Нічого; розбирається застосунок |
| Метод не існує | `error` з `-32601` | Нічого |
| Версія не підтримується | `error` з `-32022` і списком версій | Нічого |

### Офіційний Python SDK (опційно)

Пакет `mcp` версії 2.2.0 (опубліковано 2026-09-07, потрібен Python 3.10+) робить усе
те саме, але без ручного JSON. Клітинка нижче **пропускається**, якщо пакета немає:
усе головне в цьому ноутбуку від нього не залежить.
"""
    ),
    code(
        '''
# ПОТРЕБУЄ: pip install "mcp"   (необов'язково — решта ноутбука працює без нього)
try:
    import mcp
    from mcp.server import MCPServer

    print("Пакет mcp знайдено, версія:", getattr(mcp, "__version__", "?"))
    print()
    print("Мінімальний сервер на SDK — це три декоратори:")
    print()
    print("    from mcp.server import MCPServer")
    print()
    print("    mcp = MCPServer(\\"Demo\\")")
    print()
    print("    @mcp.tool()")
    print("    def add(a: int, b: int) -> int:")
    print("        \\"\\"\\"Add two numbers.\\"\\"\\"")
    print("        return a + b")
    print()
    print("    @mcp.resource(\\"greeting://{name}\\")")
    print("    def greeting(name: str) -> str:")
    print("        return f\\"Hello, {name}!\\"")
    print()
    print("    @mcp.prompt()")
    print("    def summarize(text: str) -> str:")
    print("        return f\\"Summarize:\\\\n\\\\n{text}\\"")
    print()
    print("    if __name__ == \\"__main__\\":")
    print("        mcp.run()          # без аргументу транспорт — stdio")
    print()
    print("Схема, назва й опис беруться з функції: type hints -> inputSchema,")
    print("ім'я функції -> name, докстрінг -> description.")
except ImportError:
    print("Пакет mcp не встановлено — клітинку пропущено.")
    print("Встановити:  pip install \\"mcp\\"")
    print()
    print("Це не завада: увесь JSON-RPC вище зібрано на stdlib, і сам сервер")
    print("у секції 14.7 уже працює. SDK лише прибирає ручний JSON.")
except Exception as exc:
    print(f"Помилка ({type(exc).__name__}): {exc}")
'''
    ),
    md(
        """
Різниця між `MCPServer(...)` і `run()` принципова: конструктор описує, **що** це за
сервер (назва, версія, інструкції), а `run()` — **як** його обслуговують. Опції
транспорту йдуть у `run()`, і спроба передати їх у конструктор дає
`TypeError: MCPServer.__init__() got an unexpected keyword argument 'port'`.

Окремо: `model_dump()` на Pydantic-моделях дає **snake_case**
(`list_changed`), але на дроті поле називається `listChanged` — саме так, як вимагає
схема. Не плутайте подання в Python із форматом на дроті.
"""
    ),

    # ── 14.8 ─────────────────────────────────────────────────────────────
    md(
        """
## 14.8 Що застаріло й чому

Найпрактичніший список розділу: більшість наявного MCP-коду в інтернеті написана під
`2025-11-25` і раніші ревізії. Перевіримо список прибраного **проти схеми**, а не за
пам'яттю.
"""
    ),
    code(
        '''
# Що 2026-07-28 прибрав або замінив іншим механізмом.
RETIRED = {
    "initialize": "per-request _meta + server/discover (SEP-2575)",
    "notifications/initialized": "рукопожаття більше немає (SEP-2575)",
    "ping": "прибрано: кожен запит доводить, що сервер живий (SEP-2575)",
    "logging/setLevel": "io.modelcontextprotocol/logLevel у _meta (SEP-2575)",
    "resources/subscribe": "subscriptions/listen (SEP-2575)",
    "resources/unsubscribe": "subscriptions/listen (SEP-2575)",
    "notifications/roots/list_changed": "прибрано разом із roots-флоу (SEP-2575)",
    "tasks/get": "розширення io.modelcontextprotocol/tasks (SEP-2663)",
    "tasks/result": "розширення, замінено на полінг (SEP-2663)",
}

print(f"{'метод':36} {'запит клієнта?':16} {'const у схемі?':15} заміна")
print("-" * 110)
for method, why in RETIRED.items():
    print(f"{method:36} {str(method in CLIENT_METHODS):16} "
          f"{str(method in ALL_METHOD_CONSTS):15} {why}")
print()

print("Серверні запити (sampling/roots/elicitation) більше не окремі RPC,")
print("але їхні ТИПИ живуть усередині InputRequiredResult.inputRequests:")
print("   InputRequest.anyOf :", [ref_name(n) for n in DEFS["InputRequest"]["anyOf"]])
print("   InputResponse.anyOf:", [ref_name(n) for n in DEFS["InputResponse"]["anyOf"]])
print()
print("перевірка: 'sampling/createMessage' у ClientRequest?",
      "sampling/createMessage" in CLIENT_METHODS)
print("           'CreateMessageRequest' у InputRequest?",
      "CreateMessageRequest" in [ref_name(n) for n in DEFS["InputRequest"]["anyOf"]])
'''
    ),
    md(
        """
Останні два рядки — головний висновок: `sampling/createMessage` як **метод** зник зі
списку запитів клієнта, але **тип** `CreateMessageRequest` лишився — він тепер їде
всередині `InputRequiredResult`. Тому фраза «sampling видалено» неточна: видалено
*механізм доставки*, а не сам запит.

Із Deprecated (Roots, Sampling, Logging, Dynamic Client Registration, HTTP+SSE,
`includeContext: "thisServer"`/`"allServers"`) **жодна** можливість поки не видалена:
політика життєвого циклу встановлює мінімальне **дванадцятимісячне** вікно депрекації,
а найраніше видалення для трьох можливостей із SEP-2577 — це перша ревізія, випущена
2027-07-28 або пізніше.
"""
    ),

    # ── самоперевірка ────────────────────────────────────────────────────
    md(
        """
## Самоперевірка

Клітинка нижче перевіряє твердження з розділу **на фактах зі схеми** — назвах
методів, версії протоколу, обов'язкових полях і кодах помилок.
"""
    ),
    code(
        '''
# ── 1. Схема — це JSON Schema 2020-12 зі 155 визначеннями ────────────────
assert SCHEMA["$schema"] == "https://json-schema.org/draft/2020-12/schema"
assert len(DEFS) == 155, f"очікувалось 155 визначень, знайдено {len(DEFS)}"
print("✓ Схема: JSON Schema 2020-12, 155 визначень")

# ── 2. Рівно 10 запитів клієнт -> сервер і рівно 1 сповіщення ────────────
assert len(CLIENT_METHODS) == 10, f"очікувалось 10 методів, знайдено {len(CLIENT_METHODS)}"
assert method_of("ClientNotification") == "notifications/cancelled"
assert method_of("DiscoverRequest") == "server/discover"
assert method_of("ListToolsRequest") == "tools/list"
assert method_of("CallToolRequest") == "tools/call"
assert method_of("GetPromptRequest") == "prompts/get"
assert method_of("ReadResourceRequest") == "resources/read"
assert method_of("SubscriptionsListenRequest") == "subscriptions/listen"
print("✓ Методи: 10 запитів клієнта, 1 сповіщення; назви звірені зі схемою")

# ── 3. Рукопожаття й ping прибрані ───────────────────────────────────────
for gone in ("initialize", "notifications/initialized", "ping", "logging/setLevel",
             "resources/subscribe", "resources/unsubscribe"):
    assert gone not in CLIENT_METHODS, f"{gone} не має бути в ClientRequest"
    assert gone not in ALL_METHOD_CONSTS, f"{gone} не має бути жодним const у схемі"
print("✓ Прибрано: initialize, notifications/initialized, ping, logging/setLevel,")
print("  resources/subscribe, resources/unsubscribe")

# ── 4. _meta: рівно два обов'язкові ключі ────────────────────────────────
assert DEFS["RequestMetaObject"]["required"] == [
    "io.modelcontextprotocol/clientCapabilities",
    "io.modelcontextprotocol/protocolVersion",
], DEFS["RequestMetaObject"]["required"]
assert "io.modelcontextprotocol/clientInfo" not in DEFS["RequestMetaObject"]["required"]
print("✓ _meta: обов'язкові лише protocolVersion і clientCapabilities")

# ── 5. resultType обов'язковий; input_required — друге значення ──────────
assert "resultType" in DEFS["Result"]["required"]
assert "resultType" in DEFS["InputRequiredResult"]["required"]
assert "inputRequests" in DEFS["InputRequiredResult"]["properties"]
assert "requestState" in DEFS["InputRequiredResult"]["properties"]
assert DEFS["CallToolResult"]["required"] == ["content", "resultType"]
print("✓ resultType обов'язковий; InputRequiredResult несе inputRequests/requestState")

# ── 6. MRTR дозволений лише для трьох запитів ────────────────────────────
for schema_name in ("GetPromptRequestParams", "ReadResourceRequestParams", "CallToolRequestParams"):
    assert "inputResponses" in DEFS[schema_name]["properties"], schema_name
    assert "requestState" in DEFS[schema_name]["properties"], schema_name
for schema_name in ("ListToolsRequest", "ListPromptsRequest", "DiscoverRequest"):
    assert "inputResponses" not in DEFS[schema_name].get("properties", {}), schema_name
print("✓ inputResponses є лише в prompts/get, resources/read, tools/call")

# ── 7. Коди помилок ──────────────────────────────────────────────────────
assert DEFS["UnsupportedProtocolVersionError"]["properties"]["error"]["allOf"][1] \\
    ["properties"]["code"]["const"] == -32022
assert DEFS["HeaderMismatchError"]["properties"]["error"]["allOf"][1] \\
    ["properties"]["code"]["const"] == -32020
assert DEFS["MissingRequiredClientCapabilityError"]["properties"]["error"]["allOf"][1] \\
    ["properties"]["code"]["const"] == -32021
assert DEFS["MethodNotFoundError"]["properties"]["code"]["const"] == -32601
assert DEFS["InvalidParamsError"]["properties"]["code"]["const"] == -32602
print("✓ Коди: -32020 HeaderMismatch, -32021 MissingCapability, -32022 UnsupportedVersion")

# ── 8. ttlMs і cacheScope обов'язкові в усіх п'яти результатах ──────────
for schema_name in ("DiscoverResult", "ListToolsResult", "ListPromptsResult",
                    "ListResourcesResult", "ListResourceTemplatesResult", "ReadResourceResult"):
    required = DEFS[schema_name]["required"]
    assert "ttlMs" in required and "cacheScope" in required, (schema_name, required)
print("✓ ttlMs і cacheScope обов'язкові в усіх шести кешованих результатах")

# ── 9. Framing і кодування заголовків ────────────────────────────────────
assert len(line.splitlines()) == 1, "кадр stdio мусить бути одним рядком"
assert len(tricky.splitlines()) == 1, "JSON екранує \\\\n, тож кадр лишається одним рядком"
EXPECTED_HEADERS = {
    "us-west1": "us-west1",
    "Hello, 世界": "=?base64?SGVsbG8sIOS4lueVjA==?=",
    " padded ": "=?base64?IHBhZGRlZCA=?=",
    "line1\\nline2": "=?base64?bGluZTEKbGluZTI=?=",
    "=?base64?literal?=": "=?base64?PT9iYXNlNjQ/bGl0ZXJhbD89?=",
}
for original, expected in EXPECTED_HEADERS.items():
    assert header_value(original) == expected, (original, header_value(original), expected)
print("✓ Усі 5 значень заголовків збігаються з таблицею зі специфікації")

# ── 10. Узгодження версії завжди дає СПІЛЬНУ версію ─────────────────────
assert negotiate("2026-07-28")[0] == "2026-07-28"
assert negotiate("1900-01-01")[0] == "2026-07-28"
assert negotiate("2025-11-25")[0] == "2026-07-28"
print("✓ Узгодження: будь-яка запитана версія зводиться до спільної")

# ── 11. HTTP-заголовок мусить збігатися з тілом ─────────────────────────
assert validate_header("2026-07-28", "2026-07-28") == {}
assert validate_header("2025-11-25", "2026-07-28")["code"] == -32020
assert validate_header(None, "2026-07-28")["code"] == -32020
print("✓ HeaderMismatch (-32020) на розбіжність і на відсутній заголовок")

# ── 12. MRTR: два раунди, і підмінений state відкидається ───────────────
assert final["resultType"] == "complete"
assert final["structuredContent"] == {"city": "Київ", "celsius": TEMPERATURE_SAMPLE}
tamper_rejected = False
try:
    call_tool({"name": "get_temperature", "arguments": {},
               "inputResponses": {"city": {"action": "accept", "content": {"name": "Київ"}}},
               "requestState": tampered})
except ValueError:
    tamper_rejected = True
assert tamper_rejected, "підмінений requestState мусить бути відкинутий"
print("✓ MRTR: 2 раунди; підмінений requestState відкинуто")

# ── 13. Сервер: три класи збоїв оброблено по-різному ────────────────────
assert ok["result"]["resultType"] == "complete"
assert ok["result"]["structuredContent"] == {"result": 5}
assert "isError" not in ok["result"], "успішний виклик не має нести isError"
assert bad_args["result"]["isError"] is True
assert "b" in bad_args["result"]["content"][0]["text"]
assert unknown["error"]["code"] == -32601
assert unknown_tool["error"]["code"] == -32602
assert "result" not in unknown and "result" not in unknown_tool
print("✓ Сервер: успіх без isError; брак аргументу -> isError;")
print("  невідомий метод -> -32601; невідомий інструмент -> -32602")

# ── 14. Обов'язкові поля примітивів ─────────────────────────────────────
assert DEFS["Tool"]["required"] == ["inputSchema", "name"]
assert DEFS["Resource"]["required"] == ["name", "uri"]
assert DEFS["ResourceTemplate"]["required"] == ["name", "uriTemplate"]
assert DEFS["Tool"]["properties"]["inputSchema"]["properties"]["type"]["const"] == "object"
print("✓ Tool: name+inputSchema; Resource: name+uri; ResourceTemplate: name+uriTemplate")

print()
print("Усі 14 перевірок пройдено.")
'''
    ),

    # ── підсумок ─────────────────────────────────────────────────────────
    md(
        """
## Підсумок

**Головне з цього ноутбука:**

1. **MCP `2026-07-28` — stateless.** Рукопожаття `initialize` немає; версія протоколу
   й можливості клієнта їдуть у `_meta` **кожного** запиту. Запит без
   `io.modelcontextprotocol/protocolVersion` або `.../clientCapabilities` — це `-32602`
   (і `400 Bad Request` на HTTP).
2. **`resultType` обов'язковий.** `"complete"` або `"input_required"`; відсутнє поле
   клієнт **MUST** трактувати як `"complete"` — це єдиний механізм сумісності зі
   старішими серверами.
3. **Напрямок жорстко один.** Сервери **не** ініціюють JSON-RPC-запити. У схемі рівно
   10 запитів «клієнт → сервер» і 1 сповіщення — `notifications/cancelled`.
4. **MRTR замінив зворотний канал.** Сервер повертає `InputRequiredResult` із
   `inputRequests`, клієнт повторює запит із `inputResponses`. `requestState` —
   **підконтрольний зловмиснику ввід**, який сервер **MUST** захищати (HMAC/AEAD) і
   перевіряти на TTL, суб'єкта й походження запиту.
5. **`isError` — не те саме, що протокольна помилка.** Збій виконання інструмента
   повертається як `isError: true`, щоб модель могла виправитися; помилка пошуку
   інструмента — як JSON-RPC-помилка.
6. **`ttlMs` і `cacheScope` обов'язкові** в шести кешованих результатах. `cacheScope`
   — це не дрібниця: `"public"` дозволяє кешувальному проксі віддати відповідь
   будь-кому.
7. **Транспорти різняться лише прив'язкою.** stdio — один рядок на повідомлення й
   скасування через `notifications/cancelled`; Streamable HTTP — POST на запит,
   заголовки-дзеркала, Base64-сентинел `=?base64?...?=` і скасування закриттям
   SSE-потоку.
8. **Відкат на legacy заборонено прив'язувати до коду помилки.** Legacy-сервери
   відповідають чим завгодно або мовчать; орієнтуватися можна лише на *розпізнану
   modern* помилку.
9. **Deprecated ≠ Removed.** Roots, Sampling, Logging і HTTP+SSE ще працюють; вікно
   депрекації — мінімум 12 місяців, найраніше видалення — ревізія від 2027-07-28.

**Куди далі:**

- Розділ 12 — tool use у хмарних API: та сама механіка, але без протоколу.
- Розділ 13 — модель загроз, коли інструмент дає доступ до системи.
- Розділ 23 — OpenTelemetry: `_meta` резервує `traceparent`, `tracestate`, `baggage`.
- Розділ 24 — евалюація: як перевірити, що ваш MCP-сервер справді працює.

## Джерела

- [MCP — специфікація 2026-07-28](https://modelcontextprotocol.io/specification/2026-07-28)
- [MCP — Base Protocol](https://modelcontextprotocol.io/specification/2026-07-28/basic/index.md)
- [MCP — Architecture](https://modelcontextprotocol.io/specification/2026-07-28/architecture/index.md)
- [MCP — Versioning and Compatibility](https://modelcontextprotocol.io/specification/2026-07-28/basic/versioning.md)
- [MCP — Cancellation](https://modelcontextprotocol.io/specification/2026-07-28/basic/patterns/cancellation.md)
- [MCP — Multi Round-Trip Requests](https://modelcontextprotocol.io/specification/2026-07-28/basic/patterns/mrtr.md)
- [MCP — stdio](https://modelcontextprotocol.io/specification/2026-07-28/basic/transports/stdio.md)
- [MCP — Streamable HTTP](https://modelcontextprotocol.io/specification/2026-07-28/basic/transports/streamable-http.md)
- [MCP — Key Changes](https://modelcontextprotocol.io/specification/2026-07-28/changelog.md)
- [MCP — Deprecated Features](https://modelcontextprotocol.io/specification/2026-07-28/deprecated.md)
- [MCP — Tools](https://modelcontextprotocol.io/specification/2026-07-28/server/tools.md)
- [MCP — Resources](https://modelcontextprotocol.io/specification/2026-07-28/server/resources.md)
- [MCP — Prompts](https://modelcontextprotocol.io/specification/2026-07-28/server/prompts.md)
- [MCP Python SDK — PyPI](https://pypi.org/pypi/mcp/json)
- Локальні копії джерел: `research/07/mcp_schema.json.txt`, `research/07/mcp_base.md`,
  `research/07/mcp_arch.md`, `research/07/mcp_versioning.md`,
  `research/07/mcp_cancellation.md`, `research/07/mcp_mrtr.md`,
  `research/07/mcp_stdio.md`, `research/07/mcp_streamhttp.md`,
  `research/07/mcp_transports.md`, `research/07/mcp_changelog.md`,
  `research/07/mcp_deprecated.md`, `research/07/mcp_llms.txt`,
  `research/07/pypi_mcp.json`
"""
    ),
]
