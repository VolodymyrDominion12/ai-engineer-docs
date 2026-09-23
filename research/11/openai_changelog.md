### SOURCE: https://developers.openai.com/api/docs/changelog.md

# Changelog

> For the complete documentation index, see [llms.txt](/llms.txt). Markdown versions of documentation pages are available by appending `.md` to the page URL.

> The latest features and updates to the OpenAI API.

Upcoming deprecations are listed on the [deprecations page](/api/docs/deprecations).

## September, 2026

### Sep 15

Feature

Added API key creation governance controls at the organization and project levels. Administrators can allow only service-account keys, allow only user-owned project keys, or disable all new API key creation. Organization restrictions take precedence over project settings, and existing API keys are unaffected. See [production best practices](https://developers.openai.com/api/docs/guides/production-best-practices#api-keys) for details.

### Sep 10

Feature

You can now set expiration dates when creating project API keys. Administrators can also enforce a maximum key lifetime at the organization or project level in Platform settings, requiring newly created keys to expire within the configured limit. See [production best practices](https://developers.openai.com/api/docs/guides/production-best-practices#api-keys) for guidance on key expiration and rotation.

### Sep 10

Feature

Released the [Agents API](https://developers.openai.com/api/docs/guides/agents-api/overview) in public beta. Build agents with a managed Codex harness while OpenAI handles session orchestration, context compaction, and recovery.

Use durable sessions to continue work across turns, stream progress, and connect your own tools and MCP servers. Run agents in OpenAI-hosted sandboxes or connect a sandbox from your own infrastructure or a supported provider.

Start with the [Agents API quickstart](https://developers.openai.com/api/docs/guides/agents-api/quickstart).

### Sep 10

Feature · Model: gpt-live-1 · API: v1/live/sessions

[GPT-Live 1](https://developers.openai.com/api/docs/models/gpt-live-1) is now generally available in the API. Build full-duplex voice conversations that can continue while a backend model or agent handles reasoning and tools.

Use Responses delegation with an OpenAI model, or client delegation to connect your own backend. Voice sessions cost $0.05 per minute, billed per second; backend model and tool usage is charged separately.

Start with [GPT-Live](https://developers.openai.com/api/docs/guides/live), [prompting](https://developers.openai.com/api/docs/guides/live-prompting), and [migration guidance](https://developers.openai.com/api/docs/guides/live-migration). See [pricing](https://developers.openai.com/api/docs/pricing) for details.

### Sep 8

Feature · API: v1/responses

[Prompt Cache Diagnostics](https://developers.openai.com/api/docs/guides/prompt-caching/diagnostics) is now generally available in the Responses API for GPT-5.6 and later supported models.

Compare cache reuse against a previous response, identify reasons for cache misses, and follow troubleshooting guidance to improve cache reuse.

### Sep 8

Feature · Model: gpt-image-2.5-sunburst · Model: gpt-image-2.5-flare · API: v1/images · API: v1/responses

Released [GPT Image 2.5 Sunburst](https://developers.openai.com/api/docs/models/gpt-image-2.5-sunburst) and [GPT Image 2.5 Flare](https://developers.openai.com/api/docs/models/gpt-image-2.5-flare) for image generation and editing through the Image API and the Responses API image generation tool.

Use Sunburst for workflows where editing precision matters most, or Flare for fast, high-quality everyday image generation. Both models support the new `xhigh` and `max` quality settings and use GPT Image 2 token rates. See the [image generation guide](https://developers.openai.com/api/docs/guides/image-generation) and [pricing](https://developers.openai.com/api/docs/pricing#image-generation).

### Sep 8

Feature · Model: gpt-rosalind-research

GPT-Rosalind (`gpt-rosalind-research`) is now generally available through the [trusted-access program](https://help.openai.com/en/articles/20001193-gpt-rosalind-for-life-sciences-research) for approved internal life sciences research.

Standard pricing is $5 per 1M input tokens, $0.50 per 1M cached input tokens, and $25 per 1M output tokens. Billing begins on October 5, 2026. See [pricing](https://developers.openai.com/api/docs/pricing) for details.

### Sep 3

Feature · Model: gpt-6-astra · API: v1/responses · API: v1/chat/completions

Released [GPT-6 Astra](https://developers.openai.com/api/docs/models/gpt-6-astra), our most capable model, built for the hardest end-to-end work.

Use GPT-6 Astra for reasoning, coding, computer use, research, and document creation. It combines these capabilities to carry complex tasks from an initial request to a finished result, using the context and tools you provide.

Key changes to consider when migrating:

- GPT-6 Astra does not support the `none` reasoning effort level.
- GPT-6 Astra does not support custom `temperature` or `top_p` values or log probabilities (`logprobs`).
- Tool calling requires the Responses API. If you use tools with Chat Completions, follow the [Responses migration guide](https://developers.openai.com/api/docs/guides/migrate-to-responses).
- [Misalignment monitoring](https://developers.openai.com/api/docs/guides/safety-checks/misalignment-monitoring) asynchronously checks for potential issues during agent work in supported Responses API requests. Checks can trigger safety alerts or stop a conversation for review.

Start with [Using GPT-6 Astra](https://developers.openai.com/api/docs/guides/latest-model) for capabilities, prompting, and migration guidance. Explore [computer use](https://developers.openai.com/api/docs/guides/tools-computer-use) for browser and desktop workflows, and see [pricing](https://developers.openai.com/api/docs/pricing) for available inference tiers.

### Sep 3

Feature · API: v1/responses

Added new controls for long-running work with GPT-6 Astra in the Responses API:

- [Async tool calling](https://developers.openai.com/api/docs/guides/async-tool-calling): Let the model continue working while your application runs function or custom tools, then return results as they become available.
- [Mid-turn steering](https://developers.openai.com/api/docs/guides/steering): Send additional instructions while a response is in progress over WebSockets, so the model can incorporate corrections or changing requirements.
- [Change reasoning effort mid-conversation](https://developers.openai.com/api/docs/guides/reasoning#change-reasoning-mid-conversation): Increase effort for difficult work or reduce it for routine follow-ups while preserving the cached prompt prefix.

### Sep 2

Update

Updated API errors so applications can distinguish traffic that increases too quickly from temporary model overload.

Traffic that increases too quickly can return a `429` error with the `slow_down` code. Temporary model overload returns a `503` error with the `server_is_overloaded` code. Both responses may include `Retry-After`. When the header is present, wait at least as long as it specifies before retrying. If it's missing, use exponential backoff. See the [error codes guide](https://developers.openai.com/api/docs/guides/error-codes) and [rate limits guide](https://developers.openai.com/api/docs/guides/rate-limits).

### Sep 1

Update

Connections to `api.openai.com` can now use IPv6.

## August, 2026

### Aug 29

Feature

[Mutual TLS (mTLS)](https://developers.openai.com/api/docs/guides/mutual-tls) and [X.509 workload identity federation](https://developers.openai.com/api/docs/guides/workload-identity-federation/x509) are now generally available for the OpenAI API. Configure certificates and X.509 identity providers directly in the [Platform console](https://platform.openai.com/settings/organization/security), with access controlled by your organization's roles and permissions.

### Aug 26

Update · Model: whisper-1 · Model: gpt-4o-transcribe · Model: gpt-4o-mini-transcribe · Model: gpt-4o-transcribe-diarize · API: v1/audio/transcriptions · API: v1/realtime

Announced the deprecation of `whisper-1`, `gpt-4o-transcribe`, `gpt-4o-mini-transcribe`, and `gpt-4o-transcribe-diarize`. These models will shut down on February 26, 2027. Migrate to [`gpt-live-transcribe`](https://developers.openai.com/api/docs/models/gpt-live-transcribe) or [`gpt-transcribe`](https://developers.openai.com/api/docs/models/gpt-transcribe). See the [transcription guide](https://developers.openai.com/api/docs/guides/transcription) and [deprecations page](https://developers.openai.com/api/docs/deprecations).

The Assistants API shut down on August 26, 2026. Migrate to the Responses API and Conversations API using the [migration guide](https://developers.openai.com/api/docs/assistants/migration).

### Aug 21

Feature

API customers can now select regional processing for an individual request by using a prefixed domain with an API key from a project having Global geography. Existing eligibility, data retention control, endp
