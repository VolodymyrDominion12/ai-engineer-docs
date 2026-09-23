### SOURCE: https://platform.claude.com/docs/en/docs/about-claude/pricing.md

---
title: Pricing
url: https://platform.claude.com/docs/en/about-claude/pricing
description: Learn about Anthropic's pricing structure for models and features
---

This page provides detailed pricing information for Anthropic's models and features. All prices are in USD.

For the most current pricing information, visit [claude.com/pricing](https://claude.com/pricing).

## Model pricing

The following table shows pricing for all Claude models:

| Model                                                                                                                                 | Base input tokens | 5m cache writes | 1h cache writes | Cache hits and refreshes | Output tokens |
| :------------------------------------------------------------------------------------------------------------------------------------ | :---------------- | :-------------- | :-------------- | :----------------------- | :------------ |
| Claude Fable 5.1                                                                                                                      | $10 / MTok        | $12.50 / MTok   | $20 / MTok      | $0.25 / MTok<sup>1</sup> | $50 / MTok    |
| Claude Mythos 5.1 ([limited availability](https://anthropic.com/glasswing))                                                           | $10 / MTok        | $12.50 / MTok   | $20 / MTok      | $0.25 / MTok<sup>1</sup> | $50 / MTok    |
| Claude Fable 5                                                                                                                        | $10 / MTok        | $12.50 / MTok   | $20 / MTok      | $1 / MTok                | $50 / MTok    |
| Claude Mythos 5 ([limited availability](https://anthropic.com/glasswing))                                                             | $10 / MTok        | $12.50 / MTok   | $20 / MTok      | $1 / MTok                | $50 / MTok    |
| Claude Opus 5                                                                                                                         | $5 / MTok         | $6.25 / MTok    | $10 / MTok      | $0.50 / MTok             | $25 / MTok    |
| Claude Opus 4.8                                                                                                                       | $5 / MTok         | $6.25 / MTok    | $10 / MTok      | $0.50 / MTok             | $25 / MTok    |
| Claude Opus 4.7                                                                                                                       | $5 / MTok         | $6.25 / MTok    | $10 / MTok      | $0.50 / MTok             | $25 / MTok    |
| Claude Opus 4.6                                                                                                                       | $5 / MTok         | $6.25 / MTok    | $10 / MTok      | $0.50 / MTok             | $25 / MTok    |
| Claude Opus 4.5                                                                                                                       | $5 / MTok         | $6.25 / MTok    | $10 / MTok      | $0.50 / MTok             | $25 / MTok    |
| Claude Opus 4.1 ([retired, except on Bedrock and Google Cloud](https://platform.claude.com/docs/en/about-claude/model-deprecations))  | $15 / MTok        | $18.75 / MTok   | $30 / MTok      | $1.50 / MTok             | $75 / MTok    |
| Claude Opus 4 ([retired, except on Google Cloud](https://platform.claude.com/docs/en/about-claude/model-deprecations))                | $15 / MTok        | $18.75 / MTok   | $30 / MTok      | $1.50 / MTok             | $75 / MTok    |
| Claude Sonnet 5                                                                                                                       | $2 / MTok         | $2.50 / MTok    | $4 / MTok       | $0.20 / MTok             | $10 / MTok    |
| Claude Sonnet 4.6                                                                                                                     | $3 / MTok         | $3.75 / MTok    | $6 / MTok       | $0.30 / MTok             | $15 / MTok    |
| Claude Sonnet 4.5                                                                                                                     | $3 / MTok         | $3.75 / MTok    | $6 / MTok       | $0.30 / MTok             | $15 / MTok    |
| Claude Sonnet 4 ([retired, except on Bedrock and Google Cloud](https://platform.claude.com/docs/en/about-claude/model-deprecations))  | $3 / MTok         | $3.75 / MTok    | $6 / MTok       | $0.30 / MTok             | $15 / MTok    |
| Claude Haiku 4.5                                                                                                                      | $1 / MTok         | $1.25 / MTok    | $2 / MTok       | $0.10 / MTok             | $5 / MTok     |
| Claude Haiku 3.5 ([retired, except on Bedrock and Google Cloud](https://platform.claude.com/docs/en/about-claude/model-deprecations)) | $0.80 / MTok      | $1 / MTok       | $1.60 / MTok    | $0.08 / MTok             | $4 / MTok     |

*<sup>1 Cache hits and refreshes on Claude Fable 5.1 and Claude Mythos 5.1 are priced at 0.025x the base input price. All other models use the standard 0.1x multiplier.</sup>*

<Note id="claude-sonnet-5-introductory-pricing">
  The $2/$10 per million input/output token pricing for Claude Sonnet 5, announced at launch as introductory pricing through August 31, 2026, is now the standard price. The previously scheduled increase to $3/$15 per million input/output tokens on September 1, 2026 will not occur.
</Note>

<Note>
  MTok = Million tokens. The "Base Input Tokens" column shows standard input pricing, the "5m Cache Writes", "1h Cache Writes", and "Cache Hits & Refreshes" columns are specific to [prompt caching](https://platform.claude.com/docs/en/about-claude/pricing#prompt-caching), and "Output Tokens" shows output pricing. See [prompt caching pricing](https://platform.claude.com/docs/en/about-claude/pricing#prompt-caching) for an explanation of the cache columns and pricing multipliers.
</Note>

<Note>
  Claude 4.7 and later models and Claude Mythos Preview use a newer tokenizer that contributes to their improved performance on a wide range of tasks. This tokenizer produces approximately 30% more tokens for the same text. The exact increase depends on the content and workload shape. Claude Sonnet 4.6 and earlier models use the previous tokenizer.
</Note>

For Claude Platform on AWS pricing, see [Claude Platform on AWS pricing](https://platform.claude.com/docs/en/about-claude/pricing#claude-platform-on-aws-pricing).

## Cloud platform pricing

This section covers partner-operated cloud platforms, where the cloud provider invoices you. For Anthropic-operated cloud platforms billed through a marketplace, see [Claude Platform on AWS pricing](https://platform.claude.com/docs/en/about-claude/pricing#claude-platform-on-aws-pricing) and [Claude in Microsoft Foundry pricing](https://platform.claude.com/docs/en/about-claude/pricing#claude-in-microsoft-foundry-pricing).

Claude models are available on [Amazon Bedrock](https://platform.claude.com/docs/en/build-with-claude/claude-in-amazon-bedrock) and [Google Cloud](https://platform.claude.com/docs/en/build-with-claude/claude-on-vertex-ai). For official pricing, visit:

* [Amazon Bedrock pricing](https://aws.amazon.com/bedrock/pricing/)
* [Google Cloud pricing](https://cloud.google.com/vertex-ai/generative-ai/pricing#claude-models)

<Note>
  **Regional and multi-region endpoint pricing for Claude 4.5 models and beyond**

  Starting with Claude Sonnet 4.5, Haiku 4.5, and Opus 4.5:

  * **Bedrock** offers two endpoint types: global endpoints (dynamic routing for maximum availability) and regional endpoints (guaranteed data routing through specific geographic regions).
  * **Google Cloud** offers three endpoint types: global endpoints, multi-region endpoints (dynamic routing within a geographic area), and regional endpoints.

  Regional and multi-region endpoints include a 10% premium over global endpoints. The Claude API (first-party) is global by default; for first-party data residency options and pricing, see [Data residency pricing](https://platform.claude.com/docs/en/about-claude/pricing#data-residency-pricing).

  **Scope:** This pricing structure applies to Claude Sonnet 4.5, Haiku 4.5, Opus 4.5, and all future models. Earlier models (Claude Opus 4.1 and prior releases) retain their existing pricing.

  For implementation details and code examples:

  * [Amazon Bedrock global vs regional endpoints](https://platform.claude.com/docs/en/build-with-claude/claude-in-amazon-bedrock#regions) for Opus 4.7, Haiku 4.5, and later models, or [the legacy integration](https://platform.claude.com/docs/en/build-with-claude/claude-on-amazon-bedrock-legacy#global-vs-regional-endpoints) for all other models on Bedrock
  * [Google Cloud global, multi-region, and regional endpoints](https://platform.claude.com/docs/en/build-with-claude/claude-on-vertex-ai#global-multi-region-and-regional-endpoints)
</Note>

## Claude Platform on AWS pricing

[Claude Platform on AWS](https://platform.claude.com/docs/en/build-with-claude/claude-platform-on-aws) bills through AWS Marketplace using Claude Consumption Units (CCUs). Anthropic rates your token usage in USD at standard per-model, per-feature rates, applies any negotiated discount, converts the result to CCUs at $0.01 per CCU, and reports the CCU quantity to AWS Marketplace hourly. Your AWS bill shows a single CCU line item.

| Concept             | Details                                                                                                                                                                                                           |
| ------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Billing unit**    | Claude Consumption Unit (CCU)                                                                                                                                                                                     |
| **CCU price**       | $0.01 per CCU (fixed; discounts apply at token-to-CCU conversion, not to the CCU price)                                                                                                                           |
| **Conversion**      | Token usage rated in USD at standard per-model, per-feature rates (same as [Claude API pricing](https://platform.claude.com/docs/en/about-claude/pricing#model-pricing)), then converted to CCUs at $0.01 per CCU |
| **Billing cadence** | Hourly metering to AWS Marketplace; monthly invoices                                                                                                                                                              |
| **Payment model**   | Arrears only (postpaid); no prepaid credits                                                                                                                                                                       |
| **Discounts**       | Applied as fewer CCUs metered                                                                                                                                                                                     |
| **Tax**             | Pre-tax metering; AWS Marketplace handles tax                                                                                                                                                                     |
| **Cost visibility** | Real-time breakdown in the Claude Console (access through the AWS Console); AWS Cost Explorer shows aggregated CCU                                                                                                |

<Note>
  **Claude Consumption Units.** If Customer accesses the Services through certain Marketplace Platforms (e.g., Claude Platform on AWS), usage will be invoiced in Claude Consumption Units ("CCU") rather than per MTok. A CCU is a unit of measure used solely for Marketplace Platform invoicing. One hundred (100) CCU represents $1.00 USD of fees owed for the Services, calculated at the applicable prices on [claude.com/pricing#api](https://claude.com/pricing#api), after application of any discounts.
</Note>

### Inference geography

For Claude 4.6 and later models, using `inference_geo: "us"` applies a 1.1x pricing multiplier. `inference_geo: "global"` (default) uses standard pricing. See [Data residency](https://platform.claude.com/docs/en/manage-claude/data-residency) for details.

### Private offers

When you sign up on the AWS Console **Claude Platform on AWS** service page, the AWS Console looks up any private offer associated with your account and prompts you to accept it in AWS Marketplace. Contact your Anthropic account representative for private offer terms.

<Note>
  If you have an existing Amazon Bedrock private offer, contact your Anthropic or AWS account representative before getting started with Claude Platform on AWS to ensure your discounts are applied correctly. Discounts cannot be applied retroactively to usage incurred before your private offer is accepted.
</Note>

## Claude in Microsoft Foundry pricing

[Claude in Microsoft Foundry](https://platform.claude.com/docs/en/build-with-claude/claude-in-microsoft-foundry) bills through the Azure Marketplace using Claude Consumption Units (CCUs). Anthropic rates your token usage in USD at standard per-model, per-feature rates, applies any negotiated discount, converts the result to CCUs at $0.01 per CCU, and reports the CCU quantity to the Azure Marketplace hourly. Your Azure bill shows a single CCU line item.

| Concept             | Details                                                                                                                                                                                                           |
| ------------------- | --------------------------------------------
