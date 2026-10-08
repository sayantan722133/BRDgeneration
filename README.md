# Jira BRD Generation, Requirements, and FRD Workflow

Generate and publish a Business Requirements Document from a Jira Business Vision Epic, convert each functional requirement into a Jira Task under that Epic, and continue into a Functional Requirements Document (FRD) for the same initiative. BRD generation supports Google Gemini or a local OpenAI-compatible model; the requirements parser and FRD generator are separate workflows with their own Jira MCP servers.

The generated BRD is saved as a Markdown file in `generated_brds/` and attached directly to the source Business Vision Epic in Jira. The requirements parser then creates one executable Jira Task per functional requirement under that Epic, and the FRD flow uses that source context to produce a standalone FRD and the corresponding story outputs.

## Features

- Retrieve Jira issue details, including its description and recent comments.
- Search for related Jira issues with JQL.
- Generate BRDs with executive summary, scope, stakeholders, functional and non-functional requirements, risks, and success metrics.
- Choose Google Gemini or a local model served through an OpenAI-compatible API.
- Save BRDs locally and attach them directly to the source Epic.
- Parse the attached BRD into Pydantic module/feature models and create or reuse one Jira Task per FR.
- Generate a separate FRD from the Epic, BRD attachment, and source requirement tickets.
- Publish the FRD Markdown as a dedicated FRD Task under the Epic.
- Create or update FRD user-story subtasks beneath the FRD document Task.

## Requirements

- Python 3.10 or newer.
- Jira Cloud access with an API token and permission to view issues, create child tasks, upload attachments, and add comments.
- For Gemini mode, a Google Gemini API key.
- For local mode, a running OpenAI-compatible local model server (for example, llama.cpp) with a model loaded.

## Installation

Clone the repository and change into its directory. Create and activate a virtual environment, then install the required packages:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
```

On Windows PowerShell, activate the environment with:

```powershell
.venv\Scripts\Activate.ps1
```

In VS Code, select the project's `.venv` as the Python interpreter. The MCP server uses the selected interpreter so it shares the project's installed dependencies.

## Configuration

Create a `.env` file in the repository root. Add the Jira settings for either mode, plus the setting for the model you plan to use:

```dotenv
JIRA_BASE_URL=https://your-domain.atlassian.net
JIRA_USER_EMAIL=you@example.com
JIRA_API_TOKEN=your-jira-api-token

# Required only for Gemini mode
GEMINI_API_KEY=your-gemini-api-key
# Optional for Gemini mode; defaults to gemini-3.1-flash-lite
GEMINI_MODEL_NAME=gemini-3.1-flash-lite

# Optional for local mode; these are the defaults
LOCAL_LLM_URL=http://127.0.0.1:8080/v1
LOCAL_MODEL_NAME=qwen3-4b-thinking-2507.Q4_K_M.gguf
```

Use your Jira Cloud site URL without a trailing path, your Atlassian account email, and an API token. Keep `.env` private and never commit API keys or tokens to GitHub.

## Usage

Run the complete workflow from the repository root. It generates and publishes the BRD, creates requirement Tasks under the Epic, then creates an FRD document Task with story subtasks and an architecture document Task with component subtasks:

```bash
python start.py KAN-4
```

For a local OpenAI-compatible model:

```bash
python start.py KAN-4 --provider local
```

The workflow runs in order and stops as soon as any stage fails. Architecture generation starts only after the BRD, requirement Tasks, and FRD publication succeed. Each stage can also be run independently.

Rerunning the workflow updates requirement, story, and component issues in place using their FR/module labels. Local documents and Jira attachments use stable per-Epic filenames; older generated attachments are removed after the replacement upload succeeds. Repeated BRD audit comments are not added again.

To run BRD generation only, replace `KAN-4` with the Business Vision issue key.

To run FRD generation only, from the repository root:

```bash
python "frd_generation/mcp_clients&llms/frd_client.py" KAN-4
```

To run architecture generation only, from the repository root:

```bash
python "arch_generation/mcp_clients&llms/arch_client.py" KAN-4
```

**Google Gemini:**

```bash
python "brd_generation/mcp_clients&llms/brd_client.py" PROJ-12
```

**Local OpenAI-compatible model:**

Start your local model server first, then run:

```bash
python "brd_generation/mcp_clients&llms/brd_client.py" PROJ-12 --provider local
```

The generator starts the `brd_generation` MCP server over stdio. The model can use Jira tools to retrieve the issue and related context; publishing attaches the BRD directly to the source Epic.

## Jira Workflow

BRD files are written to `generated_brds/`. The Jira publishing tool attaches the Markdown document to the source Business Vision Epic and posts an audit comment; it does not create another Jira issue. The Jira account must be able to view the Epic and upload attachments/comments.

The MCP server also exposes `save_brd_file` for local-only saves, as well as `get_jira_issue` and `search_jira_issues` for reading Jira information.

## Parse BRD requirements into Jira

After the BRD has been attached to Jira, run the independent parser from the repository root:

```bash
python "brd_retri_parse/mcp_clients&llms/brd_retri_client.py" KAN-4
```

The parser starts its independent MCP server from `brd_retri_parse/mcp_server&functions/customfun.py`; it does not import or start anything in `brd_generation`. It fetches `BRD_<EPIC_KEY>.md` from the Business Vision Epic, validates requirements into Pydantic models, then creates or reuses one Jira Task per FR directly under that Epic. Jira subtasks cannot be direct Epic children, so the project’s Task issue type is used. Task descriptions contain the requirement priority and acceptance criteria; module and requirement IDs are labels. The model JSON is not uploaded as a file. No local BRD file is required for parsing.

## Generate an FRD

`frd_generation` has an independent Jira MCP server and client. It retrieves the source issue, BRD attachment, and direct child Jira work items, then passes that complete context to the FRD agent. Run it from the repository root:

```bash
python "frd_generation/mcp_clients&llms/frd_client.py" KAN-4
```

Use `--provider local` for the configured OpenAI-compatible model, `--model NAME` to override the provider model, and `--output PATH` to choose the output location. The default output is `generated_frds/FRD_KAN-4.md`.

The async agent function is also available directly. It accepts a Pydantic model or mapping containing the retrieved Jira context and returns FRD Markdown:

```python
import asyncio

from frd_generation import generate_frd

frd_markdown = asyncio.run(generate_frd(jira_context, provider="gemini"))
```

The FRD uses the BRD attachment and linked issues such as KAN-10–KAN-14 as input. It does not reuse those issues as outputs. The client creates or reuses a `[FRD] Functional Requirements Document` Task under the Business Vision Epic, attaches the complete FRD Markdown, and creates or updates one Jira subtask per user story beneath that FRD Task. Select `provider="local"` to use the configured OpenAI-compatible local model.

On reruns, previously generated story or component Tasks that still sit directly under the Epic are reused to avoid duplicates and are listed in the publisher result. Jira does not expose issue-type conversion through the normal edit operation, so move these legacy Tasks to their document Tasks once in Jira to make their hierarchy match newly generated subtasks.

## Project structure

```text
.
├── start.py                   # Sequential BRD-to-architecture workflow
├── pyproject.toml              # Dependencies and package metadata
├── .vscode/
│   ├── mcp.json                # Jira MCP servers
│   └── tasks.json              # End-to-end workflow task
├── brd_generation/
│   ├── mcp_clients&llms/
│   │   ├── brd_client.py       # MCP client and workflow orchestration
│   │   └── brd_generator.py    # Gemini and local-model BRD generation
│   ├── mcp_server&functions/
│   │   ├── bvision_fetch.py    # Jira vision and related-issue retrieval
│   │   ├── brd_upsave.py       # Local saving and Jira publishing
│   │   └── customfun.py        # Shared helpers and MCP tool registration
│   ├── prompts.py              # Shared BRD prompt library
│   └── skill.md                # BRD workflow skill notes
├── brd_retri_parse/
│   ├── mcp_clients&llms/
│   │   ├── brd_retri_client.py # MCP client and workflow orchestration
│   │   └── brd_retri_parser.py # Pydantic models and Markdown parsing
│   ├── mcp_server&functions/
│   │   ├── bvision_fetch.py    # Jira issue and BRD attachment retrieval
│   │   ├── brd_upsave.py       # Per-feature Jira Task creation
│   │   └── customfun.py        # Shared helpers and MCP tool registration
│   └── skill.md                # Parser workflow guidance
├── frd_generation/
│   ├── prompts.py              # FRD structure and grounding instructions
│   ├── mcp_clients&llms/
│   │   ├── frd_client.py       # Jira context collection and FRD publishing
│   │   └── frd_agent.py        # Async LLM-backed FRD generation function
│   └── mcp_server&functions/
│       ├── customfun.py        # Independent Jira MCP configuration/tools
│       ├── jira_fetch.py       # Jira issue, BRD, and related-work retrieval
│       └── jira_publish.py     # FRD Task and Markdown attachment publishing
├── arch_generation/
│   ├── prompts.py              # Architecture structure and grounding instructions
│   ├── mcp_clients&llms/
│   │   ├── arch_client.py      # Jira context collection and architecture publishing
│   │   └── arch_agent.py       # Gemini and local-model architecture generation
│   └── mcp_server&functions/   # Architecture context and Jira publishing tools
├── generated_brds/             # Generated BRD Markdown files
├── generated_frds/             # Generated FRD Markdown files
├── generated_arch/             # Generated architecture Markdown files
└── .env                        # Local secrets file; keep out of Git
```

## Troubleshooting

- **Missing Gemini API key:** Set `GEMINI_API_KEY` when using the default Gemini provider. The local provider does not require it.
- **Jira authentication or permission errors:** Check the Jira URL, email, API token, and the account's project permissions.
- **Local model connection errors:** Confirm the model server is running and that `LOCAL_LLM_URL` points to its OpenAI-compatible API endpoint.
- **Issue lookup or search errors:** Confirm the Jira issue key and, for searches, the JQL query are valid and visible to the configured account.

## Security

Treat Jira API tokens and model API keys as secrets. Store them in a local `.env` file or a secret manager, and rotate them if they are exposed. Review generated BRDs before using them as approved business requirements.