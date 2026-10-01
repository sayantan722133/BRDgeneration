---
name: brd-requirements-parser
description: "Use when maintaining BRD requirement parsing, Pydantic models, Jira attachment retrieval, or requirements subtask publishing."
---

# BRD Requirements Parser

Keep this workflow independent from `brd_generation`:

- `mcp_clients&llms/brd_retri_client.py` coordinates Jira MCP calls and parsing.
- `mcp_clients&llms/brd_retri_parser.py` owns the Pydantic schema and deterministic Markdown-table parsing.
- `mcp_server&functions/bvision_fetch.py` retrieves issue hierarchy and the BRD Markdown attachment directly from KAN-4.
- `mcp_server&functions/brd_upsave.py` creates or reuses one Jira Task per feature under the Business Vision Epic.
- `mcp_server&functions/customfun.py` owns Jira configuration, shared helpers, and MCP tool registration.

The input Jira issue may be a child of a Business Vision Epic. Resolve that Epic to determine the expected `BRD_<EPIC_KEY>.md` filename, and retrieve the file directly from KAN-4. Treat the Epic as the master BRD container: create one Task for every FR directly under the Epic, put priority and acceptance criteria in its description, and use module/FR labels for categorization and idempotency. Jira subtasks cannot be children of Epics, so do not create subtasks or a parallel JSON-only ticket. Keep credentials in the repository-root `.env` file and do not write BRD content to `generated_brds/` as part of this workflow.

This parser is deterministic and does not use an LLM prompt. Validate parser changes against a representative BRD attachment, confirm MCP tool registration, and compile the client and server modules before publishing to Jira.
