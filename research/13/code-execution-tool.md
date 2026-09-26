### SOURCE: https://platform.claude.com/docs/en/agents-and-tools/tool-use/code-execution-tool.md

---
title: Code execution tool
url: https://platform.claude.com/docs/en/agents-and-tools/tool-use/code-execution-tool
description: Run Python and bash code in a sandboxed container to analyze data, generate files, and iterate on solutions.
featureMetadata:
  status: ga
  zdr: not-eligible
  supportedModels:
    - claude-fable-5-1
    - claude-mythos-5-1
    - claude-fable-5
    - claude-mythos-5
    - claude-opus-5-5
    - claude-opus-5
    - claude-opus-4-8
    - claude-opus-4-7
    - claude-opus-4-6
    - claude-opus-4-5-20251101
    - claude-sonnet-5
    - claude-sonnet-4-6
    - claude-sonnet-4-5-20250929
    - claude-haiku-4-5-20251001
  supportedPlatforms:
    Claude API: ga
    Claude Platform on AWS: ga
    Amazon Bedrock: not available
    Google Cloud: not available
    Microsoft Foundry:
      availability: ga
      note: On [Microsoft Foundry](https://platform.claude.com/docs/en/build-with-claude/claude-in-microsoft-foundry), code execution requires a [Hosted on Anthropic deployment](https://platform.claude.com/docs/en/build-with-claude/claude-in-microsoft-foundry#additional-features-not-supported-when-hosted-on-azure).
  details:
    - Every supported model accepts all three [tool versions](https://platform.claude.com/docs/en/agents-and-tools/tool-use/code-execution-tool#tool-versions). On Claude Haiku 4.5, programmatic tool calling and REPL state persistence aren't available, so the newer versions behave like `code_execution_20250825` there.
    - For [Claude Mythos Preview](https://anthropic.com/glasswing), code execution is supported on the Claude API and Microsoft Foundry.
---

Claude can analyze data, create visualizations, perform complex calculations, run system commands, create and edit files, and process uploaded files directly within the API conversation. The code execution tool allows Claude to run Bash commands and manipulate files, including writing code, in a secure, sandboxed environment.

**Code execution is free when used with web search or web fetch (`web_search_20260209`, `web_fetch_20260209`, or later).** When one of those tools is in your request, there are no additional charges for code execution in that request beyond standard token costs. This covers both the code execution behind dynamic filtering and any code Claude runs directly. Standard code execution pricing applies when they are not included.

Code execution also powers dynamic filtering in the [web search](https://platform.claude.com/docs/en/agents-and-tools/tool-use/web-search-tool) and [web fetch](https://platform.claude.com/docs/en/agents-and-tools/tool-use/web-fetch-tool) tools: Claude filters results inside the code execution environment before they reach the context window. When dynamic filtering runs, the API provisions the code execution it needs for the request automatically, so you don't add the code execution tool to your request for it.

<Note>
  Reach out through the [feedback form](https://forms.gle/LTAU6Xn2puCJMi1n6) to share your feedback on this feature.
</Note>

## Tool versions

The code execution tool has three current versions, and every [supported model](https://platform.claude.com/docs/en/agents-and-tools/tool-use/code-execution-tool#compatibility) accepts all three. Each version builds on the previous one:

* `code_execution_20250825` supports Bash commands and file operations.
* `code_execution_20260120` adds REPL state persistence and [programmatic tool calling](https://platform.claude.com/docs/en/agents-and-tools/tool-use/programmatic-tool-calling) from within the sandbox. Claude Haiku 4.5 accepts the `code_execution_20260120` and `code_execution_20260521` tool types, but programmatic tool calling and the REPL state persistence that depends on it aren't available on it, so the newer versions behave like `code_execution_20250825` there.
* `code_execution_20260521` is the same runtime as `code_execution_20260120`. The difference is that the tool description tells Claude about the 90-second wall-clock limit on each Python cell in programmatic tool calling, so Claude can budget long-running cells. A cell that exceeds the limit returns a normal code execution result with a non-zero `return_code` and a `detection_timeout` status message in its output. This is separate from the `execution_time_exceeded` [error code](https://platform.claude.com/docs/en/agents-and-tools/tool-use/code-execution-tool#errors), which the API returns when a whole tool invocation exceeds the maximum execution time.

None of the three tool versions requires an `anthropic-beta` header. The legacy code execution beta headers remain valid opt-ins.

The examples on this page use `code_execution_20250825`, which covers the Bash and file operations they demonstrate and behaves the same way on every supported model; use `code_execution_20260120` or later when you need programmatic tool calling or REPL state persistence. The current [web search](https://platform.claude.com/docs/en/agents-and-tools/tool-use/web-search-tool) and [web fetch](https://platform.claude.com/docs/en/agents-and-tools/tool-use/web-fetch-tool) tools (`web_search_20260209`, `web_fetch_20260209`, and later) require `code_execution_20260120` or later as their code execution version.

Older tool versions aren't guaranteed to stay compatible with newer models. When you adopt a new model, check [Tool versions](https://platform.claude.com/docs/en/agents-and-tools/tool-use/code-execution-tool#tool-versions) and [Compatibility](https://platform.claude.com/docs/en/agents-and-tools/tool-use/code-execution-tool#compatibility), and prefer the newest tool version your integration supports.

<Note>
  If you're still using the legacy `code_execution_20250522` (Python only), see [Upgrade to latest tool version](https://platform.claude.com/docs/en/agents-and-tools/tool-use/code-execution-tool#upgrade-to-latest-tool-version) to migrate from it.
</Note>

## Quick start

Here's an example that asks Claude to perform a calculation:

<CodeGroup>
  ```bash cURL
  curl --fail-with-body -sS https://api.anthropic.com/v1/messages \
    -H "x-api-key: $ANTHROPIC_API_KEY" \
    -H "anthropic-version: 2023-06-01" \
    -H "content-type: application/json" \
    -d '{
      "model": "claude-opus-5-5",
      "max_tokens": 4096,
      "messages": [
        {
          "role": "user",
          "content": "Use the code execution tool to calculate the mean and standard deviation of [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]"
        }
      ],
      "tools": [
        {
          "type": "code_execution_20250825",
          "name": "code_execution"
        }
      ]
    }'
  ```

  ```bash CLI
  ant messages create \
    --model claude-opus-5-5 \
    --max-tokens 4096 \
    --message '{
      role: user,
      content: "Use the code execution tool to calculate the mean and standard
        deviation of [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]"
    }' \
    --tool '{type: code_execution_20250825, name: code_execution}'
  ```

  ```python Python
  client = anthropic.Anthropic()

  response = client.messages.create(
      model="claude-opus-5-5",
      max_tokens=4096,
      messages=[
          {
              "role": "user",
              "content": "Use the code execution tool to calculate the mean and standard deviation of [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]",
          }
      ],
      tools=[{"type": "code_execution_20250825", "name": "code_execution"}],
  )

  print(response.to_json())
  ```

  ```typescript TypeScript
  const client = new Anthropic();

  const response = await client.messages.create({
    model: "claude-opus-5-5",
    max_tokens: 4096,
    messages: [
      {
        role: "user",
        content:
          "Use the code execution tool to calculate the mean and standard deviation of [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]"
      }
    ],
    tools: [{ type: "code_execution_20250825", name: "code_execution" }]
  });

  console.log(JSON.stringify(response));
  ```

  ```csharp C#
  AnthropicClient client = new();

  var message = await client.Messages.Create(new()
  {
      Model = Model.ClaudeOpus5_5,
      MaxTokens = 4096,
      Messages = [new() { Role = Role.User, Content = "Use the code execution tool to calculate the mean and standard deviation of [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]" }],
      Tools = [new CodeExecutionTool20250825()]
  });

  Console.WriteLine(message);
  ```

  ```go Go
  client := anthropic.NewClient()

  response, err := client.Messages.New(context.Background(), anthropic.MessageNewParams{
  	Model:     anthropic.ModelClaudeOpus5_5,
  	MaxTokens: 4096,
  	Messages: []anthropic.MessageParam{
  		anthropic.NewUserMessage(anthropic.NewTextBlock("Use the code execution tool to calculate the mean and standard deviation of [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]")),
  	},
  	Tools: []anthropic.ToolUnionParam{
  		{OfCodeExecutionTool20250825: &anthropic.CodeExecutionTool20250825Param{}},
  	},
  })
  if err != nil {
  	log.Fatal(err)
  }
  fmt.Println(response.RawJSON())
  ```

  ```java Java
  AnthropicClient client = AnthropicOkHttpClient.fromEnv();

  MessageCreateParams params = MessageCreateParams.builder()
      .model(Model.CLAUDE_OPUS_5_5)
      .maxTokens(4096L)
      .addUserMessage("Use the code execution tool to calculate the mean and standard deviation of [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]")
      .addTool(CodeExecutionTool20250825.builder().build())
      .build();

  Message response = client.messages().create(params);
  IO.println(ObjectMappers.jsonMapper().valueToTree(response));
  ```

  ```php PHP
  $client = new Client();

  $message = $client->messages->create(
      maxTokens: 4096,
      messages: [
          [
              'role' => 'user',
              'content' => 'Use the code execution tool to calculate the mean and standard deviation of [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]',
          ],
      ],
      model: Model::CLAUDE_OPUS_5_5,
      tools: [new CodeExecutionTool20250825()],
  );

  echo json_encode($message, JSON_PRETTY_PRINT), PHP_EOL;
  ```

  ```ruby Ruby
  client = Anthropic::Client.new

  message = client.messages.create(
    model: Anthropic::Model::CLAUDE_OPUS_5_5,
    max_tokens: 4096,
    messages: [
      {
        role: "user",
        content: "Use the code execution tool to calculate the mean and standard deviation of [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]"
      }
    ],
    tools: [Anthropic::CodeExecutionTool20250825.new]
  )

  puts message.to_json
  ```
</CodeGroup>

The response interleaves `server_tool_use` blocks (the commands Claude ran) with their tool result blocks, followed by Claude's text. The top level also includes a `container` object whose `id` you can [reuse across requests](https://platform.claude.com/docs/en/agents-and-tools/tool-use/code-execution-tool#container-reuse). See [Response format](https://platform.claude.com/docs/en/agents-and-tools/tool-use/code-execution-tool#response-format) for the block shapes.

## How code execution works

When you add the code execution tool to your API request:

1. Claude evaluates whether code execution would help answer your question

2. The tool automatically provides Claude with the following capabilities:

   * **Bash commands:** Run shell commands for system operations
   * **File operations:** Create, view, and edit files directly, including writing code

3. Claude can use any combination of these capabilities in a single request

4. All operations run in a secure, sandboxed container. The container has no internet access, so Claude can't download packages at runtime: only the [pre-installed libraries](https://platform.claude.com/docs/en/agents-and-tools/tool-use/code-execution-tool#pre-installed-libraries) are available

5. The API runs every command server-side and returns the results to Claude within the same request, so you never execute code or send back `tool_result` blocks yourself. One exception is when Claude calls one of your client tools alongside code execution: the API returns the code execution call without its result. The result arrives in a later response, after you send back the `tool_result` blocks for your client tools

6. Each request runs in a new container unless you pass an earlier response's container ID back (see [Container reuse](https://platform.claude.com/docs/en/agents-and-tools/tool-use/code-execution-tool#container-reuse))

7. Claude provides results with any generated charts, calculations, or analysis

The container has Python pre-installed. Claude writes Python with the file operations sub-tool and runs it with a Bash command. With `code_execution_20260120` or later and [programmatic tool calling](https://platform.claude.com/docs/en/agents-and-tools/tool-use/programmatic-tool-calling), the Python interpreter state (such as variable bindings) also persists across requests that reuse the container.

### When Claude runs code

Claude runs code when the request benefits from computation or file handling:

* Non-trivial math (large numbers, many steps, precision-sensitive results)
* Data analysis, file parsing, or visualization
* Algorithm execution or simulation
* Explicit requests to "run", "compute", or "execute"

Claude answers directly without running code for:

* Simple arithmetic and well-known math facts
* Factual, conversational, or creative requests
* Simple unit conversions or translations

If you want Claude to run code for a borderline request, ask explicitly (for example, "run code to verify this").

## Work with files

### Upload and analyze your own files

To analyze your own data files (such as CSV, Excel, or images), upload them through the Files API and reference them in your request.

The Python environment can process various file types uploaded through the Files API, including:

* CSV
* Excel (.xlsx, .xls)
* JSON
* XML
* Images (JPEG, PNG, GIF, WebP)
* Text files (.txt, .md, .py, and others)

#### Upload and analyze files

1. **Upload your file** using the [Files API](https://platform.claude.com/docs/en/build-with-claude/files)
2. **Reference the file** in your message using a `container_upload` content block
3. **Include the code execution tool** in your API request

<CodeGroup>
  ```bash cURL
  # First, upload a file and capture the file ID (using jq)
  FILE_ID=$(curl --fail-with-body -sS https://api.anthropic.com/v1/files \
    -H "x-api-key: $ANTHROPIC_API_KEY" \
    -H "anthropic-version: 2023-06-01" \
    -F "file=@data.csv" | jq -r '.id')

  # Then use the file_id with code execution
  curl --fail-with-body -sS https://api.anthropic.com/v1/messages \
    -H "x-api-key: $ANTHROPIC_API_KEY" \
    -H "anthropic-version: 2023-06-01" \
    -H "content-type: application/json" \
    -d '{
      "model": "claude-opus-5-5",
      "max_tokens": 4096,
      "messages": [{
        "role": "user",
        "content": [
          {"type": "text", "text": "Analyze this CSV data"},
          {"type": "container_upload", "file_id": "'"$FILE_ID"'"}
        ]
      }],
      "tools": [{
        "type": "code_execution_20250825",
        "name": "code_execution"
      }]
    }'
  ```

  ```bash CLI
  # First, upload a file and capture the file ID
  FILE_ID=$(ant files upload --file ./data.csv --transform id --raw-output)

  # Then use the file_id with code execution
  ant messages create <<YAML
  model: claude-opus-5-5
  max_tokens: 4096
  messages:
    - role: user
      content:
        - type: text
          text: Analyze this CSV data
        - type: container_upload
          file_id: $FILE_ID
  tools:
    - type: code_execution_20250825
      name: code_execution
  YAML
  ```

  ```python Python
  client = anthropic.Anthropic()

  # Upload a file
  file_object = client.files.upload(file=Path("data.csv"))

  # Use the file_id with code execution
  response = client.messages.create(
      model="claude-opus-5-5",
      max_tokens=4096,
      messages=[
          {
              "role": "user",
              "content": [
                  {"type": "text", "text": "Analyze this CSV data"},
                  {"type": "container_upload", "file_id": file_object.id},
              ],
          }
      ],
      tools=[{"type": "code_execution_20250825", "name": "code_execution"}],
  )

  print(response.to_json())
  ```

  ```typescript TypeScript
  import { createReadStream } from "node:fs";
  // ...
  const client = new Anthropic();

  // Upload a file
  const fileObject = await client.files.upload({
    file: createReadStream("data.csv")
  });

  // Use the file_id with code execution
  const response = await client.messages.create({
    model: "claude-opus-5-5",
    max_tokens: 4096,
    messages: [
      {
        role: "user",
        content: [
          { type: "text", text: "Analyze this CSV data" },
          { type: "container_upload", file_id: fileObject.id }
        ]
      }
    ],
    tools: [
      {
        type: "code_execution_20250825",
        name: "code_execution"
      }
    ]
  });

  console.log(JSON.stringify(response));
  ```

  ```csharp C#
  AnthropicClient client = new();

  // Upload a file
  var fileObject = await client.Files.Upload(new FileUploadParams
  {
      File = File.OpenRead("data.csv")
  });

  // Use the file_id with code execution
  var parameters = new MessageCreateParams
  {
      Model = Model.ClaudeOpus5_5,
      MaxTokens = 4096,
      Messages = [
          new()
          {
              Role = Role.User,
              Content = new([
                  new TextBlockParam { Text = "Analyze this CSV data" },
                  new ContainerUploadBlockParam { FileID = fileObject.ID }
              ])
          }
      ],
      Tools = [new CodeExecutionTool20250825()]
  };

  var response = await client.Messages.Create(parameters);
  Console.WriteLine(response);
  ```

  ```go Go
  ctx := context.Background()
  client := anthropic.NewClient()

  // Upload a file
  file, err := os.Open("data.csv")
  if err != nil {
  	log.Fatal(err)
  }
  defer file.Close()

  fileObject, err := client.Files.Upload(ctx, anthropic.FileUploadParams{
  	File: file,
  })
  if err != nil {
  	log.Fatal(err)
  }

  // Use the file_id with code execution
  response, err := client.Messages.New(ctx, anthropic.MessageNewParams{
  	Model:     anthropic.ModelClaudeOpus5_5,
  	MaxTokens: 4096,
  	Messages: []anthropic.MessageParam{
  		anthropic.NewUserMessage(
  			anthropic.NewTextBlock("Analyze this CSV data"),
  			anthropic.NewContainerUploadBlock(fileObject.ID),
  		),
  	},
  	Tools: []anthropic.ToolUnionParam{
  		{OfCodeExecutionTool20250825: &anthropic.CodeExecutionTool20250825Param{}},
  	},
  })
  if err != nil {
  	log.Fatal(err)
  }

  fmt.Println(response.RawJSON())
  ```

  ```java Java
  AnthropicClient client = AnthropicOkHttpClient.fromEnv();

  // Upload a file
  FileMetadata fileObject = client.files().upload(
      FileUploadParams.builder()
          .file(Path.of("data.csv"))
          .build()
  );

  // Use the file_id with code execution
  Message response = client.messages().create(
      MessageCreateParams.builder()
          .model(Model.CLAUDE_OPUS_5_5)
          .maxTokens(4096L)
          .addUserMessageOfBlockParams(List.of(
              ContentBlockParam.ofText(TextBlockParam.builder()
                  .text("Analyze this CSV data")
                  .build()),
              ContentBlockParam.ofContainerUpload(ContainerUploadBlockParam.builder()
                  .fileId(fileObject.id())
                  .build())
          ))
          .addTool(CodeExecutionTool20250825.builder().build())
          .build()
  );

  IO.println(ObjectMappers.jsonMapper().valueToTree(response));
  ```

  ```php PHP
  $client = new Client();

  // Upload a file
  $fileObject = $client->files->upload(
      file: FileParam::fromResource(fopen('data.csv', 'r')),
  );

  // Use the file_id with code execution
  $response = $client->messages->create(
      model: Model::CLAUDE_OPUS_5_5,
      maxTokens: 4096,
      messages: [
          [
              'role' => 'user',
              'content' => [
                  TextBlockParam::with(text: 'Analyze this CSV data'),
                  ContainerUploadBlockParam::with(fileID: $fileObject->id),
              ],
          ],
      ],
      tools: [new CodeExecutionTool20250825()],
  );

  echo json_encode($response), PHP_EOL;
  ```

  ```ruby Ruby
  client = Anthropic::Client.new

  # Upload a file
  file_object = client.files.upload(
    file: Pathname("data.csv")
  )

  # Use the file_id with code execution
  response = client.messages.create(
    model: Anthropic::Model::CLAUDE_OPUS_5_5,
    max_tokens: 4096,
    messages: [
      {
        role: "user",
        content: [
          { type: "text", text: "Analyze this CSV data" },
          { type: "container_upload", file_id: file_object.id }
        ]
      }
    ],
    tools: [
      Anthropic::CodeExecutionTool20250825.new
    ]
  )

  puts response.to_json
  ```
</CodeGroup>

### Retrieve generated files

When Claude saves files to its output directory during code execution (see [How generated files are captured](https://platform.claude.com/docs/en/agents-and-tools/tool-use/code-execution-tool#how-generated-files-are-captured)), each file's ID appears in the code execution tool result, and you can download it with the [Files API](https://platform.claude.com/docs/en/build-with-claude/files):

<CodeGroup>
  ```bash cURL
  # Downloading every generated file means looping over the file IDs in the tool
  # result, which doesn't translate to a one-off shell command. Use one of the
  # SDK examples instead.
  ```

  ```bash CLI
  # Extracting every file ID from the tool results and downloading each one
  # requires a loop, which doesn't translate well to a one-off CLI command.
  # Use one of the SDK examples instead.
  ```

  ```python Python
  client = Anthropic()

  # Request code execution that creates files
  response = client.messages.create(
      model="claude-opus-5-5",
      max_tokens=4096,
      messages=[
          {
              "role": "user",
              "content": "Create a matplotlib visualization and save it as output.png",
          }
      ],
      tools=[{"type": "code_execution_20250825", "name": "code_execution"}],
  )


  # Extract file IDs from the response
  def extract_file_ids(response: Message) -> list[str]:
      file_ids: list[str] = []
      for item in response.content:
          if item.type == "bash_code_execution_tool_result":
              content_item = item.content
              if content_item.type == "bash_code_execution_result":
                  for output_block in content_item.content:
                      file_ids.append(output_block.file_id)
      return file_ids


  # Download the created files
  for file_id in extract_file_ids(response):
      file_metadata = client.files.retrieve_metadata(file_id)
      file_content = client.files.download(file_id)
      file_content.write_to_file(file_metadata.filename)
      print(f"Downloaded: {file_metadata.filename}")
  ```

  ```typescript TypeScript
  import { writeFile } from "node:fs/promises";

  const client = new Anthropic();

  // Request code execution that creates files
  const response = await client.messages.create({
    model: "claude-opus-5-5",
    max_tokens: 4096,
    messages: [
      {
        role: "user",
        content: "Create a matplotlib visualization and save it as output.png"
      }
    ],
    tools: [
      {
        type: "code_execution_20250825",
        name: "code_execution"
      }
    ]
  });

  // Extract the file IDs from the response and download each created file
  for (const block of response.content) {
    if (block.type === "bash_code_execution_tool_result") {
      const result = block.content;
      if (result.type === "bash_code_execution_result") {
        for (const outputBlock of result.content) {
          const [fileMetadata, fileResponse] = await Promise.all([
            client.files.retrieveMetadata(outputBlock.file_id),
            client.files.download(outputBlock.file_id)
          ]);
          await writeFile(fileMetadata.filename, await fileResponse.bytes());
          console.log(`Downloaded: ${fileMetadata.filename}`);
        }
      }
    }
  }
  ```

  ```csharp C#
  AnthropicClient client = new();

  var parameters = new MessageCreateParams
  {
      Model = Model.ClaudeOpus5_5,
      MaxTokens = 4096,
      Messages = [new() { Role = Role.User, Content = "Create a matplotlib visualization and save it as output.png" }],
      Tools = [new CodeExecutionTool20250825()]
  };

  var response = await client.Messages.Create(parameters);

  // Collect the file IDs from the tool results
  List<string> fileIds = [];
  foreach (var block in response.Content)
  {
      if (!block.TryPickBashCodeExecutionToolResult(out var toolResult))
          continue;
      if (!toolResult.Content.TryPickBashCodeExecutionResultBlock(out var result))
          continue;
      foreach (var output in result.Content)
      {
          fileIds.Add(output.FileID);
      }
  }

  // Download each created file
  foreach (var fileId in fileIds)
  {
      var fileMetadata = await client.Files.RetrieveMetadata(fileId);
      using var download = await client.Files.Download(fileId);
      var downloadStream = await download.ReadAsStream();
      await using var target = File.Create(fileMetadata.Filename);
      await downloadStream.CopyToAsync(target);
      Console.WriteLine($"Downloaded: {fileMetadata.Filename}");
  }
  ```

  ```go Go
  	client := anthropic.NewClient()
  	ctx := context.Background()

  	response, err := client.Messages.New(ctx, anthropic.MessageNewParams{
  		Model:     anthropic.ModelClaudeOpus5_5,
  		MaxTokens: 4096,
  		Messages: []anthropic.MessageParam{
  			anthropic.NewUserMessage(anthropic.NewTextBlock("Create a matplotlib visualization and save it as output.png")),
  		},
  		Tools: []anthropic.ToolUnionParam{
  			{OfCodeExecutionTool20250825: &anthropic.CodeExecutionTool20250825Param{}},
  		},
  	})
  	if err != nil {
  		log.Fatal(err)
  	}

  	fileIDs := extractFileIDs(response)

  	for _, fileID := range fileIDs {
  		fileMetadata, err := client.Files.GetMetadata(ctx, fileID, anthropic.FileGetMetadataParams{})
  		if err != nil {
  			log.Fatal(err)
  		}

  		fileContent, err := client.Files.Download(ctx, fileID, anthropic.FileDownloadParams{})
  		if err != nil {
  			log.Fatal(err)
  		}

  		outFile, err := os.Create(fileMetadata.Filename)
  		if err != nil {
  			log.Fatal(err)
  		}

  		_, err = io.Copy(outFile, fileContent.Body)
  		if err != nil {
  			log.Fatal(err)
  		}
  		outFile.Close()
  		fileContent.Body.Close()

  		fmt.Printf("Downloaded: %s\n", fileMetadata.Filename)
  	}
  // ...

  func extractFileIDs(response *anthropic.Message) []string {
  	var fileIDs []string
  	for _, item := range response.Content {
  		switch variant := item.AsAny().(type) {
  		case anthropic.BashCodeExecutionToolResultBlock:
  			// Collect the file IDs from the tool result
  			for _, file := range variant.Content.Content {
  				if file.FileID != "" {
  					fileIDs = append(fileIDs, file.FileID)
  				}
  			}
  		}
  	}
  	return fileIDs
  }
  ```

  ```java Java
  void main() throws Exception {
      AnthropicClient client = AnthropicOkHttpClient.fromEnv();

      MessageCreateParams params = MessageCreateParams.builder()
          .model(Model.CLAUDE_OPUS_5_5)
          .maxTokens(4096L)
          .addUserMessage("Create a matplotlib visualization and save it as output.png")
          .addTool(CodeExecutionTool20250825.builder().build())
          .build();

      Message response = client.messages().create(params);

      List<String> fileIds = extractFileIds(response);

      for (String fileId : fileIds) {
          FileMetadata fileMetadata = client.files().retrieveMetadata(fileId);
          try (HttpResponse fileContent = client.files().download(fileId)) {
              Files.copy(
                  fileContent.body(),
                  Path.of(fileMetadata.filename()),
                  StandardCopyOption.REPLACE_EXISTING);
          }
          IO.println("Downloaded: " + fileMetadata.filename());
      }
  }

  List<String> extractFileIds(Message response) {
      List<String> fileIds = new ArrayList<>();
      // Collect the file IDs from the tool results
      for (ContentBlock item : response.content()) {
          item.bashCodeExecutionToolResult().ifPresent(toolResult -> {
              if (toolResult.content().isBashCodeExecutionResultBlock()) {
                  BashCodeExecutionResultBlock result =
                      toolResult.content().asBashCodeExecutionResultBlock();
                  for (BashCodeExecutionOutputBlock output : result.content()) {
                      fileIds.add(output.fileId());
                  }
              }
          });
      }
      return fileIds;
  }
  ```

  ```php PHP
  $client = new Client();

  // Request code execution that creates files
  $response = $client->messages->create(
      maxTokens: 4096,
      messages: [
          [
              'role' => 'user',
              'content' => 'Create a matplotlib visualization and save it as output.png',
          ],
      ],
      model: Model::CLAUDE_OPUS_5_5,
      tools: [new CodeExecutionTool20250825()],
  );

  /**
   * Extract file IDs from the response.
   *
   * @return list<string>
   */
  function extractFileIds(Message $response): array
  {
      $fileIds = [];
      foreach ($response->content as $block) {
          if ($block->type !== 'bash_code_execution_tool_result') {
              continue;
          }
          $resultBlock = $block->content;
          if ($resultBlock->type !== 'bash_code_execution_result') {
              continue;
          }
          foreach ($resultBlock->content as $outputBlock) {
              $fileIds[] = $outputBlock->fileID;
          }
      }
      return $fileIds;
  }

  // Download the created files
  foreach (extractFileIds($response) as $fileId) {
      $fileMetadata = $client->files->retrieveMetadata($fileId);
      $fileContent = $client->files->download($fileId);

      file_put_contents($fileMetadata->filename, $fileContent);
      echo "Downloaded: {$fileMetadata->filename}\n";
  }
  ```

  ```ruby Ruby
  client = Anthropic::Client.new

  response = client.messages.create(
    model: Anthropic::Model::CLAUDE_OPUS_5_5,
    max_tokens: 4096,
    messages: [
      {
        role: "user",
        content: "Create a matplotlib visualization and save it as output.png"
      }
    ],
    tools: [
      {
        type: "code_execution_20250825",
        name: "code_execution"
      }
    ]
  )

  def extract_file_ids(response)
    file_ids = []
    response.content.each do |item|
      if item.type == :bash_code_execution_tool_result
        # WORKAROUND for anthropic-sdk-ruby union coercion bug (SDK-636): item.content is a
        # nested content union, so the typed accessors on `item.content` are unreliable.
        # Read the raw response data through the public `BaseModel#[]` API instead.
        content_item = item.content
        if content_item[:type].to_s == "bash_code_execution_result"
          Array(content_item[:content]).each do |output_block|
            file_ids << output_block[:file_id]
          end
        end
      end
    end
    file_ids
  end

  extract_file_ids(response).each do |file_id|
    file_metadata = client.files.retrieve_metadata(file_id)
    file_content = client.files.download(file_id)

    File.open(file_metadata.filename, "wb") do |f|
      f.write(file_content.read)
    end

    puts "Downloaded: #{file_metadata.filename}"
  end
  ```
</CodeGroup>

#### How generated files are captured

Each `bash_code_execution` call gets a new, empty directory, available to the command as `$OUTPUT_DIR`. When the command finishes, the files at the top level of that directory are captured and returned as the `file_id` entries in the result's `content` list. Files written anywhere else stay in the container and aren't returned.

The tool description tells Claude to share files by copying them into `$OUTPUT_DIR`. If your application depends on receiving a file, prompt Claude to copy it into `$OUTPUT_DIR` and list the directory in the same command, so the `ls` output confirms the capture (Claude doesn't see the `content` list):

```bash
python /tmp/make_report.py && cp /tmp/report.pdf "$OUTPUT_DIR/" && ls "$OUTPUT_DIR"
```

A file Claude wrote elsewhere is still in the container, so you can [reuse the container](https://platform.claude.com/docs/en/agents-and-tools/tool-use/code-execution-tool#container-reuse) and ask Claude to copy it into `$OUTPUT_DIR`.

### Content Credentials on generated files

On the Claude API, supported image, video, and audio files that Claude produces in the code execution sandbox carry [C2PA](https://c2pa.org/) Content Credentials when you download them through the [Files API](https://platform.claude.com/docs/en/build-with-claude/files). [Supported formats](https://opensource.contentauthenticity.org/docs/sdk-repos/c2pa-python/docs/supported-formats/) include PNG, JPEG, GIF, WebP, TIFF, HEIC, AVIF, SVG, MP4, MOV, MP3, WAV, FLAC, and M4A. The credential is a cryptographically signed manifest embedded in the file's metadata. It identifies Anthropic as the issuer, carries a timestamp, and records the action description "Claude provided this file at the request of a user and may have created or modified the file contents."

Signing requires no changes to your requests or response handling, and the manifest records nothing about you, your organization, or your request. The file's visible content is unchanged. The manifest adds a few kilobytes, so the downloaded file's size and checksum differ from the file as it exists inside the container. Text files, PDFs, and office documents are not signed because they are not supported formats for signing. Files you upload are stored as-is, including any Content Credentials they already carry.

To verify a credential, inspect the file with any C2PA-compatible tool, such as the open-source [c2patool command-line utility](https://github.com/contentauth/c2pa-rs). Re-encoding, format conversion, screenshots, and tools that strip metadata remove the credential, so a missing credential doesn't mean a file wasn't produced with Claude. For more on why a credential can be missing, see [How Claude marks AI-generated content](https://support.claude.com/en/articles/16266773-how-claude-marks-ai-generated-content).

## Tool definition

The code execution tool requires no additional parameters:

```json JSON
{
  "type": "code_execution_20250825",
  "name": "code_execution"
}
```

Both fields are fixed: `type` selects the tool version, and `name` must be `code_execution`.

When you provide this tool, Claude automatically gains access to two sub-tools:

* `bash_code_execution`: Run shell commands
* `text_editor_code_execution`: View, create, and edit files, including writing code

When Claude runs code, the response also includes a top-level `container` object with the container's `id` and `expires_at` timestamp. Pass that ID back in the top-level `container` request parameter to keep using the same container. See [Container reuse](https://platform.claude.com/docs/en/agents-and-tools/tool-use/code-execution-tool#container-reuse).

## Response format

The code execution tool can return two types of results depending on the operation:

### Bash command response

```json Output
{
  "type": "server_tool_use",
  "id": "srvtoolu_01B3C4D5E6F7G8H9I0J1K2L3",
  "name": "bash_code_execution",
  "input": {
    "command": "ls -la | head -5"
  }
},
{
  "type": "bash_code_execution_tool_result",
  "tool_use_id": "srvtoolu_01B3C4D5E6F7G8H9I0J1K2L3",
  "content": {
    "type": "bash_code_execution_result",
    "stdout": "total 24\ndrwxr-xr-x 2 user user 4096 Jan 1 12:00 .\ndrwxr-xr-x 3 user user 4096 Jan 1 11:00 ..\n-rw-r--r-- 1 user user  220 Jan 1 12:00 data.csv\n-rw-r--r-- 1 user user  180 Jan 1 12:00 config.json",
    "stderr": "",
    "return_code": 0,
    "content": []
  }
}
```

### File operation responses

**View file:**

```json Output
{
  "type": "server_tool_use",
  "id": "srvtoolu_01C4D5E6F7G8H9I0J1K2L3M4",
  "name": "text_editor_code_execution",
  "input": {
    "command": "view",
    "path": "config.json"
  }
},
{
  "type": "text_editor_code_execution_tool_result",
  "tool_use_id": "srvtoolu_01C4D5E6F7G8H9I0J1K2L3M4",
  "content": {
    "type": "text_editor_code_execution_view_result",
    "file_type": "text",
    "content": "{\n  \"setting\": \"value\",\n  \"debug\": true\n}",
    "num_lines": 4,
    "start_line": 1,
    "total_lines": 4
  }
}
```

**Create file:**

```json Output
{
  "type": "server_tool_use",
  "id": "srvtoolu_01D5E6F7G8H9I0J1K2L3M4N5",
  "name": "text_editor_code_execution",
  "input": {
    "command": "create",
    "path": "new_file.txt",
    "file_text": "Hello, World!"
  }
},
{
  "type": "text_editor_code_execution_tool_result",
  "tool_use_id": "srvtoolu_01D5E6F7G8H9I0J1K2L3M4N5",
  "content": {
    "type": "text_editor_code_execution_create_result",
    "is_file_update": false
  }
}
```

**Edit file (str\_replace):**

```json Output
{
  "type": "server_tool_use",
  "id": "srvtoolu_01E6F7G8H9I0J1K2L3M4N5O6",
  "name": "text_editor_code_execution",
  "input": {
    "command": "str_replace",
    "path": "config.json",
    "old_str": "\"debug\": true",
    "new_str": "\"debug\": false"
  }
},
{
  "type": "text_editor_code_execution_tool_result",
  "tool_use_id": "srvtoolu_01E6F7G8H9I0J1K2L3M4N5O6",
  "content": {
    "type": "text_editor_code_execution_str_replace_result",
    "old_start": 3,
    "old_lines": 1,
    "new_start": 3,
    "new_lines": 1,
    "lines": ["-  \"debug\": true", "+  \"debug\": false"]
  }
}
```

### Results

Bash command results (`bash_code_execution_result`) include:

* `stdout`: Output from successful execution
* `stderr`: Error messages if execution fails
* `return_code`: 0 for success, non-zero for failure
* `content`: A list with an entry for each file the command left in `$OUTPUT_DIR` (see [How generated files are captured](https://platform.claude.com/docs/en/agents-and-tools/tool-use/code-execution-tool#how-generated-files-are-captured)). Each entry carries the `file_id` to [retrieve the file](https://platform.claude.com/docs/en/agents-and-tools/tool-use/code-execution-tool#retrieve-generated-files) with the Files API

File operation results have their own fields:

* **View** (`text_editor_code_execution_view_result`): `file_type`, `content`, `num_lines`, `start_line`, `total_lines`
* **Create** (`text_editor_code_execution_create_result`): `is_file_update` (whether the file already existed)
* **Edit** (`text_editor_code_execution_str_replace_result`): `old_start`, `old_lines`, `new_start`, `new_lines`, `lines` (diff format)

### Errors

Each tool type can return specific errors:

**Common errors (all tools):**

```json Output
{
  "type": "bash_code_execution_tool_result",
  "tool_use_id": "srvtoolu_01VfmxgZ46TiHbmXgy928hQR",
  "content": {
    "type": "bash_code_execution_tool_result_error",
    "error_code": "unavailable"
  }
}
```

**Error codes by tool type:**

| Tool         | Error code                | Description                                             |
| ------------ | ------------------------- | ------------------------------------------------------- |
| All tools    | `unavailable`             | The tool is temporarily unavailable                     |
| All tools    | `execution_time_exceeded` | The tool invocation exceeded the maximum execution time |
| All tools    | `invalid_tool_input`      | Invalid parameters provided to the tool                 |
| All tools    | `too_many_requests`       | Rate limit exceeded for tool usage                      |
| bash         | `output_file_too_large`   | Command output exceeded the maximum size                |
| text\_editor | `file_not_found`          | File doesn't exist (for view/edit operations)           |

An expired container can't be reused: requests that
