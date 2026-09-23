### SOURCE: https://developers.openai.com/api/docs/guides/error-codes.md

# Error codes

> For the complete documentation index, see [llms.txt](/llms.txt). Markdown versions of documentation pages are available by appending `.md` to the page URL.

This guide includes an overview on error codes you might see from both the [API](https://developers.openai.com/api/docs/concepts) and our [official Python library](https://developers.openai.com/api/docs/libraries#install-an-official-sdk). Each error code mentioned in the overview has a dedicated section with further guidance.

## API errors

| Code                                                         | Overview                                                                                                                                                                                                                                                                                          |
| ------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 400 - Invalid `service_tier` argument                        | **Cause:** The requested or resolved service tier is not allowed for the project. <br /> **Solution:** Set `service_tier` to a tier allowed for the project, or update the allowed service tiers in [project settings](https://platform.openai.com/settings/).                                    |
| 401 - Invalid Authentication                                 | **Cause:** Invalid Authentication <br /> **Solution:** Ensure the correct [API key](https://platform.openai.com/settings/organization/api-keys) and requesting organization are being used.                                                                                                       |
| 401 - Incorrect API key provided                             | **Cause:** The requesting API key is not correct. <br /> **Solution:** Ensure the API key used is correct, clear your browser cache, or [generate a new one](https://platform.openai.com/settings/organization/api-keys).                                                                         |
| 401 - You must be a member of an organization to use the API | **Cause:** Your account is not part of an organization. <br /> **Solution:** Contact us to get added to a new organization or ask your organization manager to [invite you to an organization](https://platform.openai.com/settings/organization/people).                                         |
| 401 - IP not authorized                                      | **Cause:** Your request IP does not match the configured IP allowlist for your project or organization. <br /> **Solution:** Send the request from the correct IP, or update your [IP allowlist settings](https://platform.openai.com/settings/organization/security/ip-allowlist).               |
| 403 - Country, region, or territory not supported            | **Cause:** You are accessing the API from an unsupported country, region, or territory. <br /> **Solution:** Please see [this page](https://developers.openai.com/api/docs/supported-countries) for more information.                                                                                                          |
| 429 - Credit balance exhausted                               | **Code:** `credit_balance_exhausted` <br /> **Cause:** Your organization has no prepaid credits remaining. <br /> **Solution:** [Add credits](https://platform.openai.com/settings/organization/billing) to continue using the API.                                                               |
| 429 - Rate limit reached for requests                        | **Cause:** You are sending requests too quickly. <br /> **Solution:** Pace your requests and follow the `Retry-After` header when it's present. Read the [Rate limit guide](https://developers.openai.com/api/docs/guides/rate-limits).                                                                                        |
| 429 - Slow down                                              | **Type:** `rate_limit_error` <br /> **Code:** `slow_down` <br /> **Cause:** Your request rate increased too quickly. <br /> **Solution:** Follow the `Retry-After` header when it's present, reduce your request rate, and increase it gradually.                                                 |
| 429 - Organization spend limit reached                       | **Code:** `organization_spend_limit_exceeded` <br /> **Cause:** Your organization reached its enforced spend limit. <br /> **Solution:** Increase or remove your [organization spend limit](https://platform.openai.com/settings/organization/limits).                                            |
| 429 - Project spend limit reached                            | **Code:** `project_spend_limit_exceeded` <br /> **Cause:** Your project reached its enforced spend limit. <br /> **Solution:** Increase or remove the spend limit in your [project settings](https://platform.openai.com/settings/).                                                              |
| 429 - Organization usage limit reached                       | **Code:** `organization_usage_limit_exceeded` <br /> **Cause:** Your organization reached its OpenAI-assigned usage limit. <br /> **Solution:** Request a higher [approved usage limit](https://platform.openai.com/settings/organization/limits) or [contact support](https://help.openai.com/). |
| 500 - The server had an error while processing your request  | **Cause:** Issue on our servers. <br /> **Solution:** Retry your request after a brief wait and contact us if the issue persists. Check the [status page](https://status.openai.com/).                                                                                                            |
| 503 - Model temporarily overloaded                           | **Type:** `service_unavailable_error` <br /> **Code:** `server_is_overloaded` <br /> **Cause:** The requested model is temporarily overloaded. <br /> **Solution:** Follow the `Retry-After` header when it's present, then retry your request.                                                   |

For billing-related errors, inspect `error.code` to identify the specific cause. The broader `error.type` can still be `insufficient_quota`.

Retrying billing, spend, or quota errors won't restore API access. Update the relevant credits or limits before sending another request.

## WebSocket mode errors

If you are using [the Responses API WebSocket mode](https://developers.openai.com/api/docs/guides/websocket-mode), you may see these additional errors:

- `previous_response_not_found`: The `previous_response_id` cannot be resolved from available state. Retry with full input context and `previous_response_id` set to `null`.
- `websocket_connection_limit_reached`: The connection hit the 60-minute limit. Open a new WebSocket connection and continue.



### 400 - Invalid service_tier argument


The API returns the message "Invalid service_tier argument: The requested service tier is not allowed for this project." as an `invalid_request_error` with `error.param` set to `service_tier` when a request selects or resolves to a service tier that is not allowed for the project.

Project restrictions apply to the `default`, `flex`, and `priority` service tiers. The `fast` service tier is evaluated as `priority`. Requests that omit `service_tier` or set it to `auto` can also return this error if they resolve to a disallowed tier. Scale Tier remains outside this project policy.

To resolve this error:

- Check the allowed service tiers in [project settings](https://platform.openai.com/settings/).
- Set `service_tier` to a tier allowed for the project.
- If the request uses `auto` or omits `service_tier`, update the project settings so the resolved tier is allowed.







### 401 - Invalid Authen
