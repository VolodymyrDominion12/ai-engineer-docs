### SOURCE: https://huggingface.co/docs/hub/en/jobs-overview.md

# Jobs Overview

Hugging Face Jobs runs your code on remote CPUs and GPUs. Use it to [train models](./jobs-training), run inference over datasets, or [process data](./jobs-large-datasets).

A Job runs a command in an environment on the hardware you choose. You can follow its status and logs from the terminal or on the Hub.

[Start with the Quickstart](./jobs-quickstart) to run your first CPU and GPU Jobs, or [browse examples](./jobs-examples) for a workload to adapt.

UV & Docker-like CLI uv,run,ps,logs,stats,inspect CPUs &amp; GPUs Choose hardware for your workload Run your code Python scripts &amp; Docker images Pay-as-you-go Pay for the compute you use

## Run Jobs from anywhere

There are multiple tools you can use to run jobs:

* the `hf` Command Line Interface (see the [CLI installation steps](https://huggingface.co/docs/huggingface_hub/main/en/guides/cli) and the [Jobs CLI documentation](https://huggingface.co/docs/huggingface_hub/guides/cli#hf-jobs) for more information)
* the `huggingface_hub` Python client (see the [`huggingface_hub` Jobs documentation](https://huggingface.co/docs/huggingface_hub/guides/jobs) for more information)
* the Jobs HTTP API (see the [Jobs OpenAPI](https://huggingface-openapi.hf.space/#tag/jobs) for more information)

## Run any workload

### Python scripts

Use `hf jobs uv run` to run a Python script remotely. Specify its dependencies using `--with` or in a [script header](https://docs.astral.sh/uv/guides/scripts/#declaring-script-dependencies). Jobs uses uv to install those dependencies before running your code.

```diff
- uv run <script.py>
+ hf jobs uv run <script.py>
```

### Docker images

Use `hf jobs run` with a Docker image and the command to run. The image provides the tools and libraries your workload needs, whether you're using Python or another language. Choose an [existing image](./jobs-images), use one built from a [Docker Space](./spaces-sdks-docker), or build your own.

```diff
- docker run <image> <command>
+ hf jobs run <image> <command>
```

Many Jobs can run in parallel, for tasks such as parameter tuning, inference and data processing.

## Automate Jobs

Trigger Jobs automatically with a schedule or using webhooks.

With a schedule, you can run Jobs every X minutes, hours, days, weeks or months. Scheduling Jobs uses the `cron` syntax like `"*/5 * * * *"` for "every 5 minutes", or aliases like `"@hourly"`, `"@daily"`, `"weekly"` or `"@monthly"`.

With webhooks, Jobs can run whenever there is an update on a Hugging Face repository. For example you can configure webhooks to trigger for every model update under a given account, and retrieve the updated model from the webhook payload in the Job.


