---
name: arch-generation
description: "Use when running or updating Step 4 of the pipeline: System Architecture & Component Design generation from Jira FRD context."
---

# Architecture Generation Skill

Keep the module split by responsibility matching the project's standard architecture:

- `mcp_clients&llms/arch_agent.py`: Coordinates Gemini and local model structured schema generation for `SystemArchitectureGeneration`.
- `mcp_clients&llms/arch_client.py`: Gathers Jira context, coordinates generation, persists the markdown locally to `generated_arch/`, and triggers Jira publishing over FastMCP stdio.
- `mcp_server&functions/customfun.py`: Provides FastMCP server runtime (`Jira-Arch-Context`), authentication headers, and ADF format converters.
- `mcp_server&functions/jira_fetch.py`: Resolves the Business Vision Epic, downloads the attached FRD Markdown document, and retrieves FRD user story tasks.
- `mcp_server&functions/jira_publish.py`: Publishes the `[ARCH] System Architecture Document` task, creates/updates component sub-tasks under that document task, and attaches the output Markdown.
- `prompts.py`: Defines architectural system instructions, section outlines, and traceability constraints.
