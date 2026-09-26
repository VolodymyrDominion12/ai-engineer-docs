### SOURCE: https://huggingface.co/docs/huggingface_hub/en/guides/cli.md

# Command Line Interface (CLI)

The `huggingface_hub` Python package comes with a built-in CLI called `hf`. This tool allows you to interact with the Hugging Face Hub directly from a terminal. For example, you can log in to your account, create a repository, upload and download files, etc. It also comes with handy features to configure your machine or manage your cache. In this guide, we will have a look at the main features of the CLI and how to use them.

> [!TIP]
> This guide covers the most important features of the `hf` CLI.
> For a complete reference of all commands and options, see the [CLI reference](../package_reference/cli).

> [!TIP]
> Using the `hf` CLI with AI agents? Install the Skill and check out the [Hugging Face CLI for AI Agents](https://huggingface.co/docs/hub/agents-cli) guide.
> ```bash
> # works with Claude Code, Codex, Cursor, OpenCode, Pi and any agent that loads skills from `.agents/skills`
> hf skills add
> ```
> The standalone installer installs it for you (see below), and `hf update` refreshes it.

## Getting started

### Standalone installer (Recommended)

You can install the `hf` CLI with a single command:

On macOS and Linux:

```bash
>>> curl -LsSf https://hf.co/cli/install.sh | bash
```

On Windows:

```powershell
>>> powershell -ExecutionPolicy ByPass -c "irm https://hf.co/cli/install.ps1 | iex"
```

The installer also installs the [`hf-cli` skill](https://huggingface.co/docs/hub/agents-cli) globally, for Claude Code and any agent reading `~/.agents/skills`. Pass `--exclude-skill` to skip it:

```bash
>>> curl -LsSf https://hf.co/cli/install.sh | bash -s -- --exclude-skill
```

```powershell
>>> powershell -ExecutionPolicy ByPass -c "& ([scriptblock]::Create((irm https://hf.co/cli/install.ps1))) -ExcludeSkill"
```

Once installed, you can check that the CLI is correctly set up:

```bash
>>> hf --help
Usage: hf [OPTIONS] COMMAND [ARGS]...

  Hugging Face Hub CLI

Options:
  --skills              Print the `hf-cli` SKILL.md to stdout (alias for `hf skills preview`).
  --install-completion  Install completion for the current shell.
  --show-completion     Show completion for the current shell, to copy it or customize the installation.
  -h, --help            Show this message and exit.

Main commands:
  auth                 Manage authentication (login, logout, etc.).
  buckets              Commands to interact with buckets.
  cache                Manage local cache directory.
  collections          Interact with collections on the Hub.
  datasets             Interact with datasets on the Hub.
  download             Download files from the Hub.
  endpoints            Manage Hugging Face Inference Endpoints.
  extensions           Manage hf CLI extensions.
  jobs                 Run and manage Jobs on the Hub.
  models               Interact with models on the Hub.
  papers               Interact with papers on the Hub.
  repos                Manage repos on the Hub.
  skills               Manage skills for AI assistants.
  spaces               Interact with spaces on the Hub.
  sync                 Sync files between local directory and a bucket.
  upload               Upload a file or a folder to the Hub.

Help commands:
  env      Print information about the environment.
  version  Print information about the hf version.
```

If the CLI is correctly installed, you should see a list of all the options available in the CLI. If you get an error message such as `command not found: hf`, please refer to the [Installation](../installation) guide.

> [!TIP]
> The `--help` option is very convenient for getting more details about a command. You can use it anytime to list all available options and their details. For example, `hf upload --help` provides more information on how to upload files using the CLI.

### Using uv

The easiest way to use the `hf` CLI is with [`uvx`](https://docs.astral.sh/uv/concepts/tools/). It always runs the latest version in an isolated environment - no installation needed!

Make sure `uv` is installed first. See the [uv installation guide](https://docs.astral.sh/uv/getting-started/installation/) for instructions.

Then use the CLI directly:

```bash
>>> uvx hf auth login
>>> uvx hf download
>>> uvx hf ...
```

> [!TIP]
> `uvx hf` uses the [`hf` PyPI package](https://pypi.org/project/hf/).

### Install with pip

The CLI is also shipped with the core `huggingface_hub` package:

```bash
>>> pip install -U "huggingface_hub"
```

### Using Homebrew

You can also install the CLI using [Homebrew](https://brew.sh/):

```bash
>>> brew install hf
```

Check out the Homebrew huggingface page [here](https://formulae.brew.sh/formula/hf) for more details.

### Updating

To upgrade to the latest version, run:

```bash
>>> hf update
```

This detects how `hf` was installed (Homebrew, standalone installer, or pip) and runs the matching update command. If the `hf-cli` skill is installed globally, it is refreshed as well so agents see the new command surface. If it isn't, it stays uninstalled: updating never brings it back if you skipped or removed it.

By default, the CLI also prints a one-line yellow warning to stderr when a newer version is available on PyPI. To silence it (e.g. in offline CI), set `HF_HUB_DISABLE_UPDATE_CHECK=1`.

## Output formatting

Most `hf` commands accept the same set of global formatting flags. They are documented in a dedicated `Formatting options` section in every `--help` page, and can be added to any command without having to declare them per-command:

| Flag | Equivalent | Description |
| ---- | ---------- | ----------- |
| `--format <value>` | — | Pick the output format explicitly. Accepted values: `auto` (default), `human`, `agent`, `json`, `quiet`. |
| `--json` | `--format json` | Print structured JSON. Useful for piping into `jq` or other scripts. |
| `-q`, `--quiet` | `--format quiet` | Print only IDs (one per line). Useful for piping IDs into other commands. |
| `--no-truncate` | — | Show full values in human tables instead of shortening long values with `...`. The table may overflow the terminal width. Use `--format json` for structured output of list/dict columns. |

`auto` (the default) picks `human` for an interactive terminal and `agent` when the CLI is invoked by an AI agent. `human` adds colors and pretty tables; `agent` produces tab-separated values without truncation; `json` emits a compact JSON object or array. Mixing two output-mode flags (e.g. `--json` together with `--format table`) raises a usage error.

Human tables auto-fit your terminal width: the widest columns are shortened only when the natural widths overflow the screen (so on a wide terminal you usually see full values without `...`). Pass `--no-truncate` to force full values regardless of width; use `--format json` for structured output of list/dict columns.

```bash
# JSON output for scripting
>>> hf models ls --search bert --limit 2 --json | jq '.[].id'

# IDs only, one per line
>>> hf collections ls --owner nvidia -q
nvidia/nemotron-supervised-fine-tuning-69eab9824c9120a3a3b1e25e
nvidia/nvidia-nemotron-v3-69388dda16167bb1607171ea
```

> [!TIP]

## hf auth login

In many cases, you must be logged in to a Hugging Face account to interact with the Hub (download private repos, upload files, create PRs, etc.). To do so, run the following command in your terminal:

```bash
>>> hf auth login
```

If you are already logged in, this command will skip the prompt and display a message. To force re-login (e.g. to switch tokens), use `--force`:

```bash
>>> hf auth login --force
```

By default, the command logs you in with your browser: it prints a URL and a short code. Open the URL, enter the code, approve the request, and the CLI retrieves and saves an access token on your machine. The token expires after a while but is refreshed automatically as long as you keep using it.

```
? How would you like to log in?  [Use arrows, Enter to confirm]
> Log in with your browser
  Paste an access token

    Open this URL in your browser:
        https://huggingface.co/oauth/device

    And enter the code: ABCD-EFGH

    Waiting for authorization...
Token is valid.
The token `oauth-wauplin` has been saved to /home/wauplin/.cache/huggingface/stored_tokens
Your token has been saved to /home/wauplin/.cache/huggingface/token
Login successful.
```

You can also choose to paste a [User Access Token](https://huggingface.co/docs/hub/security-tokens) generated from your [Settings page](https://huggingface.co/settings/tokens), either interactively (select *Paste an access token*) or directly from the command line. To be more secure, we recommend passing your token as an environment variable to avoid pasting it in your command history.

```bash
# Or using an environment variable
>>> hf auth login --token $HF_TOKEN --add-to-git-credential
Token is valid (permission: write).
The token `token_name` has been saved to /home/wauplin/.cache/huggingface/stored_tokens
Your token has been saved in your configured git credential helpers (store).
Your token has been saved to /home/wauplin/.cache/huggingface/token
Login successful
The current active token is: `token_name`
```

When run by an AI agent (auto-detected, or with `--format agent`), the command never prompts: it runs the browser flow and prints plain instructions the agent can relay to its user, then waits for the authorization:

```bash
>>> hf auth login --format agent
Ask the user to open https://huggingface.co/oauth/device in a browser and enter the code ABCD-EFGH. The code expires in 900 seconds. Waiting for authorization...
Login successful: logged in as wauplin (token saved as 'oauth-wauplin').
```

`hf auth login` is interactive, so `--format json` and `--format quiet` are not supported: pass `--token` for scripted, non-interactive logins.

For more details about authentication, check out [this section](../quick-start#authentication).

## hf auth whoami

If you want to know if you are logged in, you can use `hf auth whoami`. This command doesn't have any options and simply prints your username and the organizations you are a part of on the Hub:

```bash
hf auth whoami
Wauplin
orgs:  huggingface,eu-test,OAuthTesters,hf-accelerate,HFSmolCluster
```

If you are not logged in, an error message will be printed.

## hf auth logout

This command logs you out. In practice, it will delete all tokens stored on your machine. If you want to remove a specific token, you can specify the token name as an argument.

This command will not log you out if you are logged in using the `HF_TOKEN` environment variable (see [reference](../package_reference/environment_variables#hftoken)). If that is the case, you must unset the environment variable in your machine configuration.

## hf download

Use the `hf download` command to download files from the Hub directly. Internally, it uses the same [hf_hub_download()](/docs/huggingface_hub/v2.0.0/en/package_reference/file_download#huggingface_hub.hf_hub_download) and [snapshot_download()](/docs/huggingface_hub/v2.0.0/en/package_reference/file_download#huggingface_hub.snapshot_download) helpers described in the [Download](./download) guide and prints the returned path to the terminal. In the examples below, we will walk through the most common use cases. For a full list of available options, you can run:

```bash
hf download --help
```

### Download a single file

To download a single file from a repo, simply provide the repo_id and filename as follows:

```bash
>>> hf download gpt2 config.json
downloading https://huggingface.co/gpt2/resolve/main/config.json to /home/wauplin/.cache/huggingface/hub/tmpwrq8dm5o
(…)ingface.co/gpt2/resolve/main/config.json: 100%|██████████████████████████████████| 665/665 [00:00<00:00, 2.49MB/s]
/home/wauplin/.cache/huggingface/hub/models--gpt2/snapshots/11c5a3d5811f50298f278a704980280950aedb10/config.json
```

The command will always print on the last line the path to the file on your local machine.

To download a file located in a subdirectory of the repo, you should provide the path of the file in the repo in posix format like this:

```bash
>>> hf download HiDream-ai/HiDream-I1-Full text_encoder/model.safetensors
```

### Download an entire repository

In some cases, you just want to download all the files from a repository. This can be done by just specifying the repo id:

```bash
>>> hf download HuggingFaceH4/zephyr-7b-beta
Fetching 23 files:   0%|                                                | 0/23 [00:00<?, ?it/s]
...
...
/home/wauplin/.cache/huggingface/hub/models--HuggingFaceH4--zephyr-7b-beta/snapshots/3bac358730f8806e5c3dc7c7e19eb36e045bf720
```

### Download multiple files

You can also download a subset of the files from a repository with a single command. This can be done in two ways. If you already have a precise list of the files you want to download, you can simply provide them sequentially:

```bash
>>> hf download gpt2 config.json model.safetensors
Fetching 2 files:   0%|                                                                        | 0/2 [00:00<?, ?it/s]
downloading https://huggingface.co/gpt2/resolve/11c5a3d5811f50298f278a704980280950aedb10/model.safetensors to /home/wauplin/.cache/huggingface/hub/tmpdachpl3o
(…)8f278a7049802950aedb10/model.safetensors: 100%|██████████████████████████████| 8.09k/8.09k [00:00<00:00, 40.5MB/s]
Fetching 2 files: 100%|████████████████████████████████████████████████████████████████| 2/2 [00:00<00:00,  3.76it/s]
/home/wauplin/.cache/huggingface/hub/models--gpt2/snapshots/11c5a3d5811f50298f278a704980280950aedb10
```

The other approach is to provide patterns to filter which files you want to download using `--include` and `--exclude`. For example, if you want to download all safetensors files from [stabilityai/stable-diffusion-xl-base-1.0](https://huggingface.co/stabilityai/stable-diffusion-xl-base-1.0), except the files in FP16 precision:

```bash
>>> hf download stabilityai/stable-diffusion-xl-base-1.0 --include "*.safetensors" --exclude "*.fp16.*"*
Fetching 8 files:   0%|                                                                         | 0/8 [00:00<?, ?it/s]
...
...
Fetching 8 files: 100%|█████████████████████████████████████████████████████████████████████████| 8/8 (...)
/home/wauplin/.cache/huggingface/hub/models--stabilityai--stable-diffusion-xl-base-1.0/snapshots/462165984030d82259a11f4367a4eed129e94a7b
```

### Download a dataset, a Space or a kernel

The examples above show how to download from a model repository. To download a dataset, a Space or a kernel, use the `--repo-type` option:

```bash
# https://huggingface.co/datasets/HuggingFaceH4/ultrachat_200k
>>> hf download HuggingFaceH4/ultrachat_200k --repo-type dataset

# https://huggingface.co/spaces/HuggingFaceH4/zephyr-chat
>>> hf download HuggingFaceH4/zephyr-chat --repo-type space

...
```

### Download a specific revision

The examples above show how to download from the latest commit on the main branch. To download from a specific revision (commit hash, branch name or tag), use the `--revision` option:

```bash
>>> hf download bigcode/the-stack --repo-type dataset --revision v1.1
...
```

### Use an hf:// URI

Instead of passing the repo type, revision and file path as separate arguments and options, you can provide a single `hf://` URI. The URI encodes everything at once, following the grammar `hf://[<TYPE>/]<ID>[@<REVISION>][/<PATH>]` (see the [HF URIs reference](../package_reference/hf_uris) for the full syntax):

```bash
# Equivalent to: hf download bigcode/the-stack --repo-type dataset --revision v1.1
>>> hf download hf://datasets/bigcode/the-stack@v1.1

# Download a single file from a specific revision
>>> hf download hf://datasets/HuggingFaceM4/FineVision@refs/pr/1/data/train.parquet

# Download a subfolder (note the trailing slash)
>>> hf download hf://datasets/HuggingFaceM4/FineVision/art/

# A bare id still works and defaults to a model repo
>>> hf download hf://openai-community/gpt2/config.json
```

When a URI is given, `--repo-type` and `--revision` cannot be set as well since they are already part of the URI (an error is raised otherwise), and a file path embedded in the URI cannot be combined with positional filenames. A trailing `/` on the path denotes a subfolder (as with the positional argument). Branch names that contain a `/` must be URL-encoded as `%2F` (e.g. `hf://my-org/my-model@feature%2Ffoo`).

### Download to a local folder

The recommended (and default) way to download files from the Hub is to use the cache-system. However, in some cases you want to download files and move them to a specific folder. This is useful to get a workflow closer to what git commands offer. You can do that using the `--local-dir` option.

A `.cache/huggingface/` folder is created at the root of your local directory containing metadata about the downloaded files. This prevents re-downloading files if they're already up-to-date. If the metadata has changed, then the new file version is downloaded. This makes the `local-dir` optimized for pulling only the latest changes.

> [!TIP]
> For more details on how downloading to a local file works, check out the [download](./download#download-files-to-a-local-folder) guide.

```bash
>>> hf download adept/fuyu-8b model-00001-of-00002.safetensors --local-dir fuyu
...
fuyu/model-00001-of-00002.safetensors
```

### Dry-run mode

In some cases, you would like to check which files would be downloaded before actually downloading them. You can check this using the `--dry-run` parameter. It lists all files to download on the repo and checks whether they are already downloaded or not. This gives an idea of how many files have to be downloaded and their sizes.

```sh
>>> hf download openai-community/gpt2 --dry-run
[dry-run] Fetching 26 files: 100%|█████████████| 26/26 [00:04<00:00,  6.26it/s]
[dry-run] Will download 11 files (out of 26) totalling 5.6G.
File                              Bytes to download
--------------------------------- -----------------
.gitattributes                    -
64-8bits.tflite                   125.2M
64-fp16.tflite                    248.3M
64.tflite                         495.8M
README.md                         -
config.json                       -
flax_model.msgpack                497.8M
generation_config.json            -
merges.txt                        -
model.safetensors                 548.1M
onnx/config.json                  -
onnx/decoder_model.onnx           653.7M
onnx/decoder_model_merged.onnx    655.2M
onnx/decoder_with_past_model.onnx 653.7M
onnx/generation_config.json       -
onnx/merges.txt                   -
onnx/special_tokens_map.json      -
onnx/tokenizer.json               -
onnx/tokenizer_config.json        -
onnx/vocab.json                   -
pytorch_model.bin                 548.1M
rust_model.ot                     702.5M
tf_model.h5                       497.9M
tokenizer.json                    -
tokenizer_config.json             -
vocab.json                        -
```

For more details, check out the [download guide](./download#dry-run-mode).

### Specify cache directory

If not using `--local-dir`, all files will be downloaded by default to the cache directory defined by the `HF_HOME` [environment variable](../package_reference/environment_variables#hfhome). You can specify a custom cache using `--cache-dir`:

```bash
>>> hf download adept/fuyu-8b --cache-dir ./path/to/cache
...
./path/to/cache/models--adept--fuyu-8b/snapshots/ddcacbcf5fdf9cc59ff01f6be6d6662624d9c745
```

### Specify a token

To access private or gated repositories, you must use a token. By default, the token saved locally (using `hf auth login`) will be used. If you want to authenticate explicitly, use the `--token` option:

```bash
>>> hf download gpt2 config.json --token=hf_****
/home/wauplin/.cache/huggingface/hub/models--gpt2/snapshots/11c5a3d5811f50298f278a704980280950aedb10/config.json
```

### Quiet mode

By default, the `hf download` command will be verbose. It will print details such as warning messages, information about the downloaded files, and progress bars. If you want to silence all of this, use the `--quiet` option. Only the last line (i.e. the path to the downloaded files) is printed. This can prove useful if you want to pass the output to another command in a script.

```bash
>>> hf download gpt2 --quiet
/home/wauplin/.cache/huggingface/hub/models--gpt2/snapshots/11c5a3d5811f50298f278a704980280950aedb10
```

### Download timeout

On machines with slow connections, you might encounter timeout issues like this one:

```bash
`httpx2.TimeoutException: (TimeoutException("HTTPSConnectionPool(host='cdn-lfs-us-1.huggingface.co', port=443): Read timed out. (read timeout=10)"), '(Request ID: a33d910c-84c6-4514-8362-c705e2039d38)')`
```

To mitigate this issue, you can set the `HF_HUB_DOWNLOAD_TIMEOUT` environment variable to a higher value (default is 10):

```bash
export HF_HUB_DOWNLOAD_TIMEOUT=30
```

For more details, check out the [environment variables reference](../package_reference/environment_variables#hfhubdownloadtimeout). And rerun your download command.

## hf upload

Use the `hf upload` command to upload files to the Hub directly. Internally, it uses the same [upload_file()](/docs/huggingface_hub/v2.0.0/en/package_reference/hf_api#huggingface_hub.HfApi.upload_file) and [upload_folder()](/docs/huggingface_hub/v2.0.0/en/package_reference/hf_api#huggingface_hub.HfApi.upload_folder) helpers described in the [Upload](./upload) guide. In the examples below, we will walk through the most common use cases. For a full list of available options, you can run:

```bash
>>> hf upload --help
```

### Upload an entire folder

The default usage for this command is:

```bash
# Usage:  hf upload [repo_id] [local_path] [path_in_repo]
```

To upload the current directory at the root of the repo, use:

```bash
>>> hf upload my-cool-model . .
https://huggingface.co/Wauplin/my-cool-model/tree/main/
```

> [!TIP]
> If the repo doesn't exist yet, it will be created automatically.

You can also upload a specific folder:

```bash
>>> hf upload my-cool-model ./models .
https://huggingface.co/Wauplin/my-cool-model/tree/main/
```

Finally, you can upload a folder to a specific destination on the repo:

```bash
>>> hf upload my-cool-model ./path/to/curated/data /data/train
https://huggingface.co/Wauplin/my-cool-model/tree/main/data/train
```

### Upload a single file

You can also upload a single file by setting `local_path` to point to a file on your machine. If that's the case, `path_in_repo` is optional and will default to the name of your local file:

```bash
>>> hf upload Wauplin/my-cool-model ./models/model.safetensors
https://huggingface.co/Wauplin/my-cool-model/blob/main/model.safetensors
```

If you want to upload a single file to a specific directory, set `path_in_repo` accordingly:

```bash
>>> hf upload Wauplin/my-cool-model ./models/model.safetensors /vae/model.safetensors
https://huggingface.co/Wauplin/my-cool-model/blob/main/vae/model.safetensors
```

### Upload multiple files

To upload multiple files from a folder at once without uploading the entire folder, use the `--include` and `--exclude` patterns. It can also be combined with the `--delete` option to delete files on the repo while uploading new ones. In the example below, we sync the local Space by deleting remote files and uploading all files except the ones in `/logs`:

```bash
# Sync local Space with Hub (upload new files except from logs/, delete removed files)
>>> hf upload Wauplin/space-example --repo-type=space --exclude="/logs/*" --delete="*" --commit-message="Sync local Space with Hub"
...
```

### Upload to a dataset or Space

To upload to a dataset or a Space, use the `--repo-type` option:

```bash
>>> hf upload Wauplin/my-cool-dataset ./data /train --repo-type=dataset
...
```

### Upload to an organization

To upload content to a repo owned by an organization instead of a personal repo, you must explicitly specify it in the `repo_id`:

```bash
>>> hf upload MyCoolOrganization/my-cool-model . .
https://huggingface.co/MyCoolOrganization/my-cool-model/tree/main/
```

### Upload to a specific revision

By default, files are uploaded to the `main` branch. If you want to upload files to another branch or reference, use the `--revision` option:

```bash
# Upload files to a PR
>>> hf upload bigcode/the-stack . . --repo-type dataset --revision refs/pr/104
...
```

**Note:** if `revision` does not exist and `--create-pr` is not set, a branch will be created automatically from the `main` branch.

### Use an hf:// URI

As with `hf download`, the destination can be expressed as a single `hf://` URI following the grammar `hf://[<TYPE>/]<ID>[@<REVISION>][/<PATH>]` (see the [HF URIs reference](../package_reference/hf_uris) for the full syntax). The repo type, revision and `path_in_repo` are all read from the URI:

```bash
# Equivalent to: hf upload Wauplin/my-cool-dataset ./train.csv data/train.csv --repo-type dataset --revision my-branch
>>> hf upload hf://datasets/Wauplin/my-cool-dataset@my-branch/data/train.csv ./train.csv

# Upload a whole folder to the root of a model repo
>>> hf upload hf://Wauplin/my-cool-model ./models
```

When a URI is given, `--repo-type` and `--revision` cannot be set as well since they are already part of the URI (an error is raised otherwise), and a path embedded in the URI cannot be combined with the `path_in_repo` argument.

### Upload and create a PR

If you don't have the permission to push to a repo, you must open a PR and let the authors know about the changes you want to make. This can be done by setting the `--create-pr` option:

```bash
# Create a PR and upload the files to it
>>> hf upload bigcode/the-stack . . --repo-type dataset --revision refs/pr/104
https://huggingface.co/datasets/bigcode/the-stack/blob/refs%2Fpr%2F104/
```

### Upload at regular intervals

In some cases, you might want to push regular updates to a repo. For example, this is useful if you're training a model and you want to upload the logs folder every 10 minutes. You can do this using the `--every` option:

```bash
# Upload new logs every 10 minutes
hf upload training-model logs/ --every=10
```

### Specify a commit message

Use the `--commit-message` and `--commit-description` to set a custom message and description for your commit instead of the default one

```bash
>>> hf upload Wauplin/my-cool-model ./models . --commit-message="Epoch 34/50" --commit-description="Val accuracy: 68%. Check tensorboard for more details."
...
https://huggingface.co/Wauplin/my-cool-model/tree/main
```

### Specify a token

To upload files, you must use a token. By default, the token saved locally (using `hf auth login`) will be used. If you want to authenticate explicitly, use the `--token` option:

```bash
>>> hf upload Wauplin/my-cool-model ./models . --token=hf_****
...
https://huggingface.co/Wauplin/my-cool-model/tree/main
```

### Quiet mode

By default, the `hf upload` command will be verbose. It will print details such as warning messages, information about the uploaded files, and progress bars. If you want to silence all of this, use the `--quiet` option. Only the last line (i.e. the URL to the uploaded files) is printed. This can prove useful if you want to pass the output to another command in a script.

```bash
>>> hf upload Wauplin/my-cool-model ./models . --quiet
https://huggingface.co/Wauplin/my-cool-model/tree/main
```

## hf buckets

Use `hf buckets` to manage buckets on the Hugging Face Hub. Buckets provide S3-like object storage on Hugging Face, powered by the Xet storage backend. Unlike repositories (which are git-based and track file history), buckets are remote object storage containers designed for large-scale files with content-addressable deduplication. They are designed for use cases where you need simple, fast, mutable storage such as storing training checkpoints, logs, intermediate artifacts, or any large collection of files that doesn't need version control. In the examples below, we will walk through the most common use cases. For a complete guide, see the [Buckets guide](./buckets).

### Create a bucket

To create a new bucket, use `hf buckets create`. The bucket will be created under your namespace by default:

```bash
>>> hf buckets create my-bucket
```

You can also create a private bucket using the `--private` flag:

```bash
>>> hf buckets create my-bucket --private
```

### List and inspect buckets

To list all your buckets, use `hf buckets list` (or its shorthand `hf buckets ls`). You can also list buckets in a specific organization:

```bash
>>> hf buckets list
ID                   PRIVATE       SIZE TOTAL_FILES CREATED_AT
-------------------- ------- ---------- ----------- ----------
username/my-bucket                   32           5 2026-02-16
username/checkpoints         117609095         700 2026-02-13
username/logs                321757477        2000 2026-02-13

# Human-readable sizes
>>> hf buckets list -h
ID                   PRIVATE     SIZE TOTAL_FILES CREATED_AT
-------------------- ------- -------- ----------- ----------
username/my-bucket               32 B           5 2026-02-16
username/checkpoints         117.6 MB         700 2026-02-13
username/logs                321.8 MB        2000 2026-02-13

# List buckets in a specific namespace
>>> hf buckets ls my-org

# Filter buckets by name
>>> hf buckets list --search "checkpoint"
```

To get detailed information about a specific bucket (returned as JSON), use `hf buckets info`:

```bash
>>> hf buckets info username/my-bucket
{
  "id": "username/my-bucket",
  "private": false,
  "created_at": "2026-02-16T15:28:32+00:00",
  "size": 32,
  "total_files": 5
}
```

### Change bucket visibility

To switch a bucket between private and public, use `hf buckets settings`:

```bash
# Make a bucket private
>>> hf buckets settings username/my-bucket --private

# Make it public again
>>> hf buckets settings username/my-bucket --public
```

### Delete a bucket

To delete a bucket, use `hf buckets delete`. You will be prompted for confirmation unless you pass `--yes`:

```bash
>>> hf buckets delete username/my-bucket --yes
```

### Remove files

Use `hf buckets remove` (or its shorthand `hf buckets rm`) to remove files from a bucket.

To remove a single file, specify its path:

```bash
>>> hf buckets rm username/my-bucket/old-model.bin
```

To remove all files under a prefix, use `--recursive`:

```bash
>>> hf buckets rm username/my-bucket/logs/ --recursive
```

You can also target all files in a bucket without a prefix:

```bash
>>> hf buckets rm username/my-bucket --recursive --include "*.tmp"
```

Use `--dry-run` to preview what would be deleted without actually deleting anything:

```bash
>>> hf buckets rm username/my-bucket/checkpoints/ --recursive --dry-run
```

### Browse files

Use `hf buckets list` with a bucket ID to list files in a bucket:

```bash
>>> hf buckets list username/my-bucket
        2048  2026-01-15 10:30:00  big.bin
           5  2026-01-15 10:30:00  file.txt
              2026-01-15 10:30:00  sub/
```

Add `-R` for a recursive listing and `-h` for human-readable file sizes and short dates. You can also display an ASCII tree view with `--tree`, or use `--tree --quiet` for a clean tree without metadata:

```bash
# Recursive with human-readable sizes
>>> hf buckets list username/my-bucket -R -h
      2.0 KB         Jan 15 10:30  big.bin
         5 B         Jan 15 10:30  file.txt
        14 B         Jan 15 10:30  sub/nested.txt
         4 B         Jan 15 10:30  sub/deep/file.txt

# Tree with human-readable sizes
>>> hf buckets list username/my-bucket --tree -h -R
2.0 KB  Jan 15 10:30  ├── big.bin
   5 B  Jan 15 10:30  ├── file.txt
                      └── sub/
                          ├── deep/
   4 B  Jan 15 10:30  │       └── file.txt
  14 B  Jan 15 10:30  └── nested.txt

# Clean tree without metadata
>>> hf buckets list username/my-bucket --tree --quiet -R
├── big.bin
├── file.txt
└── sub/
    ├── deep/
    │   └── file.txt
    └── nested.txt
```

To filter by prefix, append the prefix to the bucket path:

```bash
>>> hf buckets list username/my-bucket/sub -R
```

### Copy files

Use `hf cp` to copy a single file between your local machine, repositories, and buckets. The source and destination can each be a local path, an `hf://` URI (repo or bucket), or `-` (stdin/stdout).

> [!TIP]
> `hf cp` is also exposed as `hf repos cp` and `hf buckets cp` — all three are the exact same command. Use whichever reads best for your workflow.

To upload a file (local → repo or bucket):

```bash
# To a repository
>>> hf cp ./model.safetensors hf://username/my-model/model.safetensors

# To a bucket (uses the local filename when the destination ends with /)
>>> hf cp ./data.csv hf://buckets/username/my-bucket/logs/
```

To download a file (repo or bucket → local):

```bash
# From a repository
>>> hf cp hf://datasets/username/my-dataset@refs/pr/1/data.csv ./data.csv

# From a bucket, to the current directory (destination omitted)
>>> hf cp hf://buckets/username/my-bucket/config.json
```

You can also stream to stdout or from stdin using `-`:

```bash
# Download to stdout
>>> hf cp hf://buckets/username/my-bucket/config.json - | jq .

# Upload from stdin
>>> echo "hello" | hf cp - hf://username/my-model/hello.txt
```

To copy between two locations on the Hub (repo/bucket → repo/bucket):

```bash
# Repo to repo
>>> hf cp hf://username/source-model/config.json hf://username/dest-model/config.json

# Repo to bucket
>>> hf cp hf://datasets/username/my-dataset/data/train/ hf://buckets/username/my-bucket/datasets/train/

# Bucket to bucket
>>> hf cp hf://buckets/username/source-bucket/logs/ hf://buckets/username/archive-bucket/logs/
```

When copying folders between two Hub locations, a trailing `/` on the source path controls whether the folder itself is nested or only its contents are copied (rsync-style):

```bash
# Without trailing slash: "logs" dir is nested => archive/logs/...
>>> hf cp hf://buckets/username/my-bucket/logs hf://buckets/username/archive-bucket/

# With trailing slash: only contents of "logs" are copied => archive/...
>>> hf cp hf://buckets/username/my-bucket/logs/ hf://buckets/username/archive-bucket/
```

Notes:

- `hf cp` copies a single file when a local path is involved. To copy whole directories to/from local, use `hf upload`/`hf download` (repos) or `hf buckets sync` (buckets).
- Bucket-to-repo copy is not yet supported.
- Local-to-local copy is not supported (use your shell's `cp`).
- Copies between two Hub locations only work within the same [storage region](https://huggingface.co/docs/hub/storage-regions).

### Sync directories

Use `hf buckets sync` to synchronize directories between your local machine and a bucket. It compares source and destination and transfers only changed files.

To upload a local directory to a bucket:

```bash
>>> hf buckets sync ./data hf://buckets/username/my-bucket
```

To download from a bucket to a local directory:

```bash
>>> hf buckets sync hf://buckets/username/my-bucket ./data
```

Use `--delete` to remove destination files that are not present in the source:

```bash
>>> hf buckets sync ./data hf://buckets/username/my-bucket --delete
```

You can filter which files to sync using `--include` and `--exclude` patterns:

```bash
>>> hf buckets sync ./data hf://buckets/username/my-bucket --include "*.safetensors" --exclude "*.tmp"
```

To only update existing files (skip new ones), use `--existing`. To only create new files (skip existing ones), use `--ignore-existing`:

```bash
>>> hf buckets sync ./data hf://buckets/username/my-bucket --existing
>>> hf buckets sync ./data hf://buckets/username/my-bucket --ignore-existing
```

For extra safety, you can generate a plan for review before executing, and then apply it:

```bash
# Generate a plan
>>> hf buckets sync ./data hf://buckets/username/my-bucket --plan sync-plan.jsonl

# Review and apply the plan
>>> hf buckets sync --apply sync-plan.jsonl
```

Use `--dry-run` to print the sync plan as JSONL to stdout without executing anything. This is handy for piping into `jq` or other tools:

```bash
>>> hf buckets sync ./data hf://buckets/username/my-bucket --dry-run | jq .
```

> [!TIP]
> `hf sync` is a convenient top-level alias for `hf buckets sync`. See the [Buckets guide](./buckets#sync-directories) for full details on all sync options.

## hf models

Use `hf models` to list models on the Hub and get detailed information about a specific model.

### List models

```bash
# List trending models
>>> hf models ls

# Search for models
>>> hf models ls --search "lora"

# Filter by author
>>> hf models ls --author Qwen

# Filter by pipeline tag
>>> hf models ls --pipeline-tag summarization

# Filter by parameter count
>>> hf models ls --num-parameters min:6B,max:128B

# Only non-gated models
>>> hf models ls --no-gated --author google

# Only models runnable by a given app
>>> hf models ls --apps llama.cpp

# Sort by downloads
>>> hf models ls --sort downloads --limit 10
```

When called with a model ID, `hf models ls` lists files in that model repo:

```bash
# List files in a model repo
>>> hf models ls meta-llama/Llama-3.2-1B-Instruct

# List files recursively
>>> hf models ls meta-llama/Llama-3.2-1B-Instruct -R

# Tree view with human-readable sizes
>>> hf models ls meta-llama/Llama-3.2-1B-Instruct --tree -h

# List files at a specific revision
>>> hf models ls meta-llama/Llama-3.2-1B-Instruct --revision main
```

### Get model info

```bash
>>> hf models info Lightricks/LTX-2
```

Use `--expand` to fetch additional properties like `downloads`, `likes`, `tags`, etc.

### Get model card

Use `hf models card` to fetch the model card (README) for a model. By default, prints the full card content to stdout.

```bash
# Full card (metadata + text)
>>> hf models card google/gemma-4-31B-it

# Just the metadata (from the YAML frontmatter)
>>> hf models card google/gemma-4-31B-it --metadata

# Metadata as JSON (useful for scripting and agents)
>>> hf models card google/gemma-4-31B-it --metadata --format json

# Just the text body (no YAML frontmatter)
>>> hf models card google/gemma-4-31B-it --text
```

## hf datasets

Use `hf datasets` to list datasets on the Hub and get detailed information about a specific dataset.

### List datasets

```bash
# List trending datasets
>>> hf datasets ls

# Search for datasets
>>> hf datasets ls --search "code"

# List official benchmark datasets
>>> hf datasets ls --filter benchmark:official

# Sort by downloads
>>> hf datasets ls --sort downloads --limit 10
```

When called with a dataset ID, `hf datasets ls` lists files in that dataset repo:

```bash
# List files in a dataset repo
>>> hf datasets ls HuggingFaceFW/fineweb

# List files recursively with human-readable sizes
>>> hf datasets ls HuggingFaceFW/fineweb -R -h

# Tree view
>>> hf datasets ls HuggingFaceFW/fineweb --tree
```

### List a dataset leaderboard

Use `hf datasets leaderboard` to show model scores submitted to a benchmark dataset, so you can find the best models for a task or compare models by benchmark scores.

```bash
>>> hf datasets leaderboard SWE-bench/SWE-bench_Verified
>>> hf datasets leaderboard SWE-bench/SWE-bench_Verified --limit 5 --format json
```

### Get dataset info

```bash
>>> hf datasets info HuggingFaceFW/fineweb
```

### Get dataset card

Use `hf datasets card` to fetch the dataset card (README) for a dataset. By default, prints the full card content to stdout.

```bash
# Full card (metadata + text)
>>> hf datasets card HuggingFaceFW/fineweb

# Just the metadata (from the YAML frontmatter)
>>> hf datasets card HuggingFaceFW/fineweb --metadata

# Metadata as JSON (useful for scripting and agents)
>>> hf datasets card HuggingFaceFW/fineweb --metadata --format json

# Just the text body (no YAML frontmatter)
>>> hf datasets card HuggingFaceFW/fineweb --text
```

### List parquet URLs

Use `hf datasets parquet` to discover parquet file URLs for a dataset before writing SQL queries.
Datasets on the Hub are auto-converted to Parquet on the backend by the Dataset Viewer service (for eligible datasets).
See the [Parquet conversion guide](https://huggingface.co/docs/dataset-viewer/parquet) for details.

```bash
>>> hf datasets parquet cfahlgren1/hub-stats
>>> hf datasets parquet cfahlgren1/hub-stats --subset models
>>> hf datasets parquet cfahlgren1/hub-stats --split train
>>> hf datasets parquet cfahlgren1/hub-stats --format json
```

The default table output includes subset, split, and parquet file URL from the Hub API.

### Run SQL on dataset parquet

Use `hf datasets sql` to execute raw SQL queries with DuckDB against dataset parquet URLs.
Discover URLs first with `hf datasets parquet`, then query them directly with `read_parquet(...)`.

```bash
>>> hf datasets sql "SELECT COUNT(*) AS rows FROM read_parquet('https://huggingface.co/api/datasets/cfahlgren1/hub-stats/parquet/models/train/0.parquet')"
>>> hf datasets sql "SELECT * FROM read_parquet('https://huggingface.co/api/datasets/cfahlgren1/hub-stats/parquet/models/train/0.parquet') LIMIT 5" --format json
```

Install DuckDB first if needed:

```bash
# Python package
>>> pip install duckdb

# or standalone DuckDB CLI (Homebrew: macOS/Linux)
>>> brew install duckdb
```

## hf spaces

Use `hf spaces` to list Spaces on the Hub and get detailed information about a specific Space.

### List Spaces

```bash
# List trending Spaces
>>> hf spaces ls

# Search for Spaces
>>> hf spaces ls --search "3d"

# Sort by likes
>>> hf spaces ls --sort likes --limit 10
```

When called with a Space ID, `hf spaces ls` lists files in that Space repo:

```bash
# List files in a Space repo
>>> hf spaces ls victor/deepsite

# List files recursively with tree view
>>> hf spaces ls victor/deepsite --tree -R -h
```

### Get Space info

```bash
>>> hf spaces info victor/deepsite
```

### Get Space card

Use `hf spaces card` to fetch the Space card (README) for a Space. By default, prints the full card content to stdout.

```bash
# Full card (metadata + text)
>>> hf spaces card mteb/leaderboard

# Just the card metadata (from the YAML frontmatter)
>>> hf spaces card mteb/leaderboard --metadata

# Card metadata as JSON
>>> hf spaces card mteb/leaderboard --metadata --format json

# Just the text body (no YAML frontmatter)
>>> hf spaces card mteb/leaderboard --text
```

> [!TIP]
> Pausing or restarting a Space tears down its container, so anything written to the ephemeral filesystem is lost. To persist data across restarts, mount a Volume or bucket with `hf spaces volumes set` (run `hf spaces volumes --help` for details).

### Pause a Space

Use `hf spaces pause` to pause a Space when you are not using it (paused time is not billed). Restart it later with `hf spaces restart`.

```bash
>>> hf spaces pause username/my-space
```

### Restart a Space

Use `hf spaces restart` to restart a Space. Pass `--factory-reboot` to rebuild the Space from scratch without using the build cache.

```bash
>>> hf spaces restart username/my-space
>>> hf spaces restart username/my-space --factory-reboot
```

### Wait for a Space

Use `hf spaces wait` to block until a Space finishes building/starting and reaches a settled stage. Exits with code 0 if the Space is `RUNNING`, or non-zero otherwise (e.g. `BUILD_ERROR`). Handy for scripting after a restart or hardware change.

```bash
>>> hf spaces wait username/my-space

# With a timeout
>>> hf spaces wait username/my-space --timeout 5m

# Chain with restart
>>> hf spaces restart username/my-space && hf spaces wait username/my-space
```

### List available hardware

Use `hf spaces hardware` to list all available hardware options for Spaces, including pricing.

```bash
>>> hf spaces hardware
```

### Update Space settings

Use `hf spaces settings` to update the settings of a Space.

```bash
>>> hf spaces settings username/my-space --sleep-time 3600
>>> hf spaces settings username/my-space --hardware t4-medium
```

- `--sleep-time`: idle time in seconds before the Space sleeps. Use `-1` to never sleep. Only available on upgraded hardware (see the [Spaces sleep time docs](https://huggingface.co/docs/hub/spaces-gpus#sleep-time)).
- `--hardware`: hardware flavor (e.g. `cpu-basic`, `t4-medium`, `l4x4`). Run `hf spaces hardware` to see all options.

### Manage Space secrets

Use `hf spaces secrets ls` to list secrets on a Space, `hf spaces secrets add` to add or update one or more secrets, and `hf spaces secrets delete` to remove one. Pass `--secrets-file PATH` to load secrets from a `.env`-style file. Existing keys are overwritten.

```bash
>>> hf spaces secrets ls username/my-space
>>> hf spaces secrets add username/my-space -s OPENAI_API_KEY=sk-...
>>> hf spaces secrets add username/my-space --secrets-file .env.secrets
>>> hf spaces secrets delete username/my-space OPENAI_API_KEY --yes
```

> [!NOTE]
> Secret values are write-only so `hf spaces secrets ls` shows keys, descriptions, and update timestamps, but never the secret values themselves.

### Manage Space environment variables

Use `hf spaces variables` to manage non-secret environment variables on a Space. Unlike secrets, variables are readable, so `ls` shows both keys and values. Pass `--env-file PATH` on `add` to load from a `.env`-style file.

```bash
>>> hf spaces variables ls username/my-space
>>> hf spaces variables add username/my-space -e MODEL_ID=gpt2 -e MAX_TOKENS=512
>>> hf spaces variables add username/my-space --env-file .env
>>> hf spaces variables delete username/my-space MAX_TOKENS --yes
```

### SSH into a Space (Dev Mode)

Use `hf spaces ssh` to open an SSH session into a Space's Dev Mode container. If Dev Mode is not enabled, the CLI will prompt you to enable it (or use `--auto` to skip the prompt).

Your SSH public key must be registered [in your settings](https://huggingface.co/settings/keys). See the [Dev Mode documentation](https://huggingface.co/docs/hub/spaces-dev-mode) for more details.

```bash
# SSH into a Space
>>> hf spaces ssh username/my-space

# Print the SSH command without running it
>>> hf spaces ssh username/my-space --dry-run

# Auto-enable Dev Mode if disabled
>>> hf spaces ssh username/my-space --auto

# Use a specific SSH key
>>> hf spaces ssh username/my-space -i ~/.ssh/id_ed25519
```

## hf papers

Use `hf papers` to list, search, get structured info, and read the markdown content of papers on the Hub.

### List papers

```bash
# List most recent daily papers
>>> hf papers ls

# List trending papers
>>> hf papers ls --sort=trending

# List papers from a specific date
>>> hf papers ls --date=2025-01-23

# List today's papers
>>> hf papers ls --date=today

# List papers from a specific week
>>> hf papers ls --week=2025-W09

# List papers from a specific month
>>> hf papers ls --month=2025-02

# List papers submitted by a specific user
>>> hf papers ls --submitter=akhaliq

# Limit results
>>> hf papers ls --sort=trending --limit=5
```

### Search papers

```bash
# Search papers by keyword
>>> hf papers search "vision language"

# Limit search results
>>> hf papers search "diffusion models" --limit=10

# Output as JSON
>>> hf papers search "attention" --format=json
```

### Get paper info

```bash
# Get structured metadata for a paper (returns JSON)
>>> hf papers info 2601.15621
```

### Read paper as markdown

```bash
# Read the full paper content as markdown
>>> hf papers read 2601.15621
```

## hf discussions

Use `hf discussions` to manage discussions and pull requests on Hub repositories directly from your terminal. You can list, view, create, comment on, close, reopen, and merge both discussions and PRs. For a full guide on how the Hub's community features work, see the [Discussions and Pull Requests guide](./community).

### List discussions

To list open discussions and PRs on a repository, pass the repo ID to `hf discussions list` (or its shorthand `hf discussions ls`):

```bash
>>> hf discussions list username/my-model
```

You can narrow the results by kind (`discussion` or `pull_request`), status (`open`, `closed`, `merged`, or `all`), or author:

```bash
>>> hf discussions list username/my-model --kind pull_request --status merged
>>> hf discussions list username/my-model --author alice
```

For scripting, use `--format json` to get structured output, or `--quiet` to print only discussion numbers (one per line):

```bash
>>> hf discussions list username/my-model --format json
>>> hf discussions ls username/my-model --quiet
```

### Get info for a discussion or PR

To inspect a specific discussion or PR, pass the repo ID and the discussion number:

```bash
>>> hf discussions info username/my-model 5
```

The output contains the discussion metadata (title, status, author, etc.) together with the full list of conversation events. To display the diff of a pull request, use `hf discussions diff` instead.

Use `--format json` for machine-readable output, and set `NO_COLOR=1` to strip ANSI colors when piping to other tools.

### Create a discussion or PR

To open a new discussion, provide a title with `--title`. You can optionally include a description inline with `--body`, or load it from a file with `--body-file`:

```bash
>>> hf discussions create username/my-model --title "Bug report"
>>> hf discussions create username/my-model --title "Feature request" --body "Please add X"
>>> hf discussions create username/my-model --title "Report" --body-file report.md
```

To create a pull request instead of a plain discussion, add the `--pull-request` flag:

```bash
>>> hf discussions create username/my-model --title "Fix typo" --pull-request
```

### Comment on a discussion or PR

Add a comment to an existing discussion or PR by specifying its number. The comment body can be passed inline with `--body`, read from a file with `--body-file`, or piped from stdin using `--body-file -`:

```bash
>>> hf discussions comment username/my-model 5 --body "Thanks for reporting!"
>>> hf discussions comment username/my-model 5 --body-file review.md
>>> echo "LGTM" | hf discussions comment username/my-model 5 --body-file -
```

### Edit a comment

Edit an existing comment in place by passing the discussion number and the comment ID. Comment IDs can be retrieved with `hf discussions info`:

```bash
>>> hf discussions edit username/my-model 5 abc123 --body "Updated comment."
>>> hf discussions edit username/my-model 5 abc123 --body-file fixed.md
```

### Close, reopen, and merge

You can close a discussion or PR with `hf discussions close`. By default, you will be prompted for confirmation. Pass `--yes` to skip the prompt, and `--comment` to leave a closing message:

```bash
>>> hf discussions close username/my-model 5
>>> hf discussions close username/my-model 5 --yes --comment "Resolved"
```

To reopen a previously closed discussion, use `hf discussions reopen`:

```bash
>>> hf discussions reopen username/my-model 5 --yes
```

To merge a pull request, use `hf discussions merge`:

```bash
>>> hf discussions merge username/my-model 5 --yes
```

### Rename and diff

You can rename a discussion by providing the new title:

```bash
>>> hf discussions rename username/my-model 5 "Updated title"
```

To view the diff of a pull request directly in your terminal, use `hf discussions diff`:

```bash
>>> hf discussions diff username/my-model 5
```

## hf repos

`hf repos` lets you list, create, delete, move repositories, update their settings, and delete files on the Hugging Face Hub. It also includes subcommands to manage branches and tags.

### List repos

Use `hf repos ls` to list all your repositories (models, datasets, spaces, and buckets) with storage information, sorted by storage usage. By default, only the first 30 repos are shown:

```bash
# List all your repos (first 30)
>>> hf repos ls
REPOSITORY                TYPE     UPDATED      VISIBILITY   STORAGE  % OF TOTAL
------------------------  -------  ----------   ----------  --------  ----------
username/bucket-raw       bucket   2026-04-29   public        1.7 TB       72.3%
username/my-model         model    2026-05-06   public        4.8 GB       18.1%
username/my-dataset       dataset  2024-09-14   private     598.4 MB        5.2%
Hint: Showing 30 of 42 repos. Use `--limit 0` to list all.
```

Filter by repository type, search by name, or adjust the limit:

```bash
# List only models
>>> hf repos ls --type model

# Search by name
>>> hf repos ls --search "bert"

# List repos from an organization
>>> hf repos ls --namespace my-org

# Combine filters
>>> hf repos ls --namespace my-org --type dataset --search "train"

# List all repos (no limit)
>>> hf repos ls --limit 0
```

Use `--format json` for scripting or `-q` for IDs only. When piping, use `--limit 0` to export all repos:

```bash
>>> hf repos ls --limit 0 --format json | jq '.[].id'
>>> hf repos ls -q
```

### Create a repo

```bash
>>> hf repos create Wauplin/my-cool-model
Successfully created Wauplin/my-cool-model on the Hub.
Your repo is now available at https://huggingface.co/Wauplin/my-cool-model
```

Create a private dataset or a Space:

```bash
>>> hf repos create my-cool-dataset --repo-type dataset --private
>>> hf repos create my-gradio-space --repo-type space --sdk gradio
```

Use `--exist-ok` if the repo may already exist, and `--resource-group-id` to target an Enterprise resource group.

Create a repo in a specific region:

```bash
>>> hf repos create my-model --region us
```

### Delete a repo

```bash
>>> hf repos delete Wauplin/my-cool-model
```

Datasets and Spaces:

```bash
>>> hf repos delete my-cool-dataset --repo-type dataset
>>> hf repos delete my-gradio-space --repo-type space
```

### Move a repo

```bash
>>> hf repos move old-namespace/my-model new-namespace/my-model
```

### Update repo settings

```bash
>>> hf repos settings Wauplin/my-cool-model --gated auto
>>> hf repos settings Wauplin/my-cool-model --private true
>>> hf repos settings Wauplin/my-cool-model --private false
```

- `--gated`: one of `auto`, `manual`, `false`
- `--private true|false`: set repository privacy

### Delete files from a repo

The `hf repos delete-files <repo_id>` sub-command allows you to delete files from a repository. Here are some usage examples.

Delete a folder:

```bash
>>> hf repos delete-files Wauplin/my-cool-model folder/
Files correctly deleted from repo. Commit: https://huggingface.co/Wauplin/my-cool-mo...
```

Delete multiple files:

```bash
>>> hf repos delete-files Wauplin/my-cool-model file.txt folder/pytorch_model.bin
Files correctly deleted from repo. Commit: https://huggingface.co/Wauplin/my-cool-mo...
```

Use wildcard patterns to delete sets of files. Patterns are Standard Wildcards (globbing patterns) as documented [here](https://tldp.org/LDP/GNU-Linux-Tools-Summary/html/x11655.htm). The pattern matching is based on [`fnmatch`](https://docs.python.org/3/library/fnmatch.html).

> [!WARNING]
> Note that `fnmatch` matches `*` across path boundaries, unlike traditional Unix shell globbing. For example, `"data/*.json"` will match both `data/file.json` **and** `data/subdir/file.json`. To match only files in the immediate directory, you need to list them explicitly or use more specific patterns.

```bash
>>> hf repos delete-files Wauplin/my-cool-model "*.txt" "folder/*.bin"
Files correctly deleted from repo. Commit: https://huggingface.co/Wauplin/my-cool-mo...
```

To delete files from a repo you must be authenticated and authorized. By default, the token saved locally (using `hf auth login`) will be used. If you want to authenticate explicitly, use the `--token` option:

```bash
>>> hf repos delete-files --token=hf_**** Wauplin/my-cool-model file.txt
```

### hf repos branch

Use `hf repos branch` to create and delete branches for repositories on the Hub.

```bash
# Create a branch
>>> hf repos branch create Wauplin/my-cool-model dev

# Create a branch from a specific revision
>>> hf repos branch create Wauplin/my-cool-model release-1 --revision refs/pr/104

# Delete a branch
>>> hf repos branch delete Wauplin/my-cool-model dev
```

> [!TIP]
> All commands accept `--repo-type` (one of `model`, `dataset`, `space`) and `--token` if you need to authenticate explicitly. Use `--help` on any command to see all options.

## hf cache

Use `hf cache` to manage your local Hugging Face cache directory. The cache stores models, datasets, Spaces and kernels downloaded from the Hub.

```bash
# List cached repositories
>>> hf cache ls

# List cached revisions
>>> hf cache ls --revisions

# Remove specific items from cache
>>> hf cache rm model/gpt2

# Remove unreferenced revisions
>>> hf cache prune

# Verify cached file checksums
>>> hf cache verify gpt2
```

### hf cache ls

Use `hf cache ls` to inspect what is stored locally in your Hugging Face cache. By default it aggregates information by repository:

```bash
>>> hf cache ls
ID                          SIZE     LAST_ACCESSED LAST_MODIFIED REFS
--------------------------- -------- ------------- ------------- -----------
dataset/nyu-mll/glue          157.4M 2 days ago    2 days ago    main script
model/LiquidAI/LFM2-VL-1.6B     3.2G 4 days ago    4 days ago    main
model/microsoft/UserLM-8b      32.1G 4 days ago    4 days ago    main

Found 3 repo(s) for a total of 5 revision(s) and 35.5G on disk.
```

Add `--revisions` to drill down to specific snapshots, and chain filters to focus on what matters:

```bash
>>> hf cache ls --filter "size>30g" --revisions
ID                        REVISION                                 SIZE     LAST_MODIFIED REFS
------------------------- ---------------------------------------- -------- ------------- ----
model/microsoft/UserLM-8b be8f2069189bdf443e554c24e488ff3ff6952691    32.1G 4 days ago    main

Found 1 repo(s) for a total of 1 revision(s) and 32.1G on disk.
```

The command supports several output formats for scripting: `--format json` prints structured objects, `--format csv` writes comma-separated rows, and `--quiet` prints only IDs. Use `--sort` to order entries by `accessed`, `modified`, `name`, or `size` (append `:asc` or `:desc` to control order), and `--limit` to restrict results to the top N entries. Combine these with `--cache-dir` to target alternative cache locations. See the [Manage your cache](./manage-cache) guide for advanced workflows.

Delete cache entries selected with `hf cache ls --q` by piping the IDs into `hf cache rm`:

```bash
>>> hf cache rm $(hf cache ls --filter "accessed>1y" -q) -y
About to delete 2 repo(s) totalling 5.31G.
  - model/meta-llama/Llama-3.2-1B-Instruct (entire repo)
  - model/hexgrad/Kokoro-82M (entire repo)
Delete repo: ~/.cache/huggingface/hub/models--meta-llama--Llama-3.2-1B-Instruct
Delete repo: ~/.cache/huggingface/hub/models--hexgrad--Kokoro-82M
Cache deletion done. Saved 5.31G.
Deleted 2 repo(s) and 2 revision(s); freed 5.31G.
```

### hf cache rm

`hf cache rm` removes cached repositories, individual revisions or single files. Pass one or more repo IDs (`model/bert-base-uncased`), `hf://` URIs, or revision hashes:

```bash
>>> hf cache rm model/LiquidAI/LFM2-VL-1.6B
About to delete 1 repo(s) totalling 3.2G.
  - model/LiquidAI/LFM2-VL-1.6B (entire repo)
Proceed with deletion? [y/N]: y
Delete repo: ~/.cache/huggingface/hub/models--LiquidAI--LFM2-VL-1.6B
Cache deletion done. Saved 3.2G.
Deleted 1 repo(s) and 2 revision(s); freed 3.2G.
```

Repo-level `hf://` URIs are also supported:

```bash
>>> hf cache rm hf://models/openai-community/gpt2 --dry-run
About to delete 1 repo(s) totalling 1.1G.
  - model/openai-community/gpt2 (entire repo)
Dry run: no files were deleted.
```

To remove a single file instead of a whole repository, for example one GGUF quantization, pass an `hf://` file URI. The file is removed from every cached revision of the repo, and its blob is deleted only if no other cached file still references it:

```bash
>>> hf cache rm hf://models/unsloth/gemma-3-27b-it-GGUF/gemma-3-27b-it-Q4_K_M.gguf --dry-run
About to delete 1 file(s) totalling 16.5G.
  - model/unsloth/gemma-3-27b-it-GG
