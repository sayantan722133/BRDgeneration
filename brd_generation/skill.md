---
name: brd-generation
description: "Use when changing the BRD generation workflow, shared prompts, Jira MCP functions, model clients, or publishing behavior."
---

# BRD Generation Skill

Keep the workflow split by responsibility:

- `mcp_clients&llms/brd_generator.py` coordinates model-specific BRD generation.
- `mcp_clients&llms/brd_client.py` connects the generator to the Jira MCP server.
- `mcp_server&functions/bvision_fetch.py` retrieves Jira vision and related issues.
- `mcp_server&functions/brd_upsave.py` saves BRDs and publishes them to Jira.
- `mcp_server&functions/customfun.py` owns shared Jira helpers and MCP tool registration.
- `prompts.py` keeps BRD creation guidance separate from end-to-end workflow guidance. Both clients compose the two prompts when building the model system instruction.

When changing a prompt, update the appropriate prompt in the shared library rather than duplicating prompt text in a client. Keep Jira credentials in environment variables, preserve the existing MCP tool names and response formats, and validate changes by importing the modules and checking the MCP tool registry.