"""Fetch Jira FRD context over FastMCP and generate System Architecture documents."""

import argparse
import asyncio
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SERVER_SCRIPT = PROJECT_ROOT / "arch_generation" / "mcp_server&functions" / "customfun.py"
sys.path.insert(0, str(PROJECT_ROOT))

from arch_agent import generate_arch_package

ISSUE_KEY_PATTERN = re.compile(r"^[A-Z][A-Z0-9]+-\d+$")


def _tool_text(result: Any) -> str:
    text = "\n".join(item.text for item in result.content if hasattr(item, "text"))
    if getattr(result, "isError", False):
        raise RuntimeError(text or "Architecture Jira MCP tool returned an error.")
    return text


def _tool_json(result: Any) -> dict[str, Any] | list[dict[str, Any]]:
    value = json.loads(_tool_text(result))
    if isinstance(value, dict) and value.get("error"):
        details = value.get("details")
        message = value["error"]
        raise RuntimeError(f"{message}: {details}" if details else message)
    return value


async def collect_jira_context(issue_key: str) -> dict[str, Any]:
    """Fetch the source Epic, attached FRD Markdown, and child user stories."""
    source_key = issue_key.strip().upper()
    if not ISSUE_KEY_PATTERN.fullmatch(source_key):
        raise ValueError("issue_key must be a valid Jira key, for example KAN-4.")

    server_params = StdioServerParameters(
        command=sys.executable,
        args=[str(SERVER_SCRIPT)],
        env=os.environ.copy(),
    )
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            source = _tool_json(await session.call_tool(
                "get_jira_issue", arguments={"issue_key": source_key}
            ))
            if not isinstance(source, dict):
                raise RuntimeError("Jira returned an unexpected issue response.")

            if (source.get("issuetype") or "").casefold() == "epic":
                epic_key = source_key
                epic = source
            elif (source.get("parent_issuetype") or "").casefold() == "epic":
                epic_key = source.get("parent_issue_key") or ""
                epic = _tool_json(await session.call_tool(
                    "get_jira_issue", arguments={"issue_key": epic_key}
                ))
                if not isinstance(epic, dict):
                    raise RuntimeError("Jira returned an unexpected Epic response.")
            else:
                raise ValueError(f"{source_key} is not an Epic or its direct child.")

            frd_doc = _tool_json(await session.call_tool(
                "get_frd_markdown", arguments={"issue_key": epic_key}
            ))
            if not isinstance(frd_doc, dict):
                raise RuntimeError("Jira returned an unexpected FRD attachment response.")
            markdown = frd_doc.get("markdown_content")
            if not isinstance(markdown, str) or not markdown.strip():
                raise RuntimeError("The Jira FRD attachment is empty.")

            frd_documents = _tool_json(await session.call_tool(
                "search_jira_issues",
                arguments={
                    "jql_query": (
                        f'parent = "{epic_key}" AND '
                        'labels in ("frd-output-document", "frd-document") ORDER BY key'
                    ),
                    "max_results": 10,
                },
            ))
            if not isinstance(frd_documents, list):
                raise RuntimeError("Jira returned an unexpected FRD document search response.")
            frd_documents.sort(
                key=lambda issue: "frd-output-document" not in issue.get("labels", [])
            )
            frd_task_key = frd_documents[0].get("key") if frd_documents else None

            related_stories: list[dict[str, Any]] = []
            for parent_key in dict.fromkeys(key for key in (frd_task_key, epic_key) if key):
                stories = _tool_json(await session.call_tool(
                    "search_jira_issues",
                    arguments={
                        "jql_query": (
                            f'parent = "{parent_key}" AND labels = "frd-output-story" ORDER BY key'
                        ),
                        "max_results": 100,
                    },
                ))
                if not isinstance(stories, list):
                    raise RuntimeError("Jira returned an unexpected related-stories response.")
                related_stories.extend(stories)
            related_stories = list({story.get("key"): story for story in related_stories}.values())

    return {
        "business_vision_epic": epic,
        "source_issue": source,
        "frd_attachment": {
            "filename": frd_doc.get("attachment_name"),
            "markdown": markdown,
        },
        "frd_user_stories": related_stories,
    }


async def publish_arch(
    epic_key: str,
    arch_markdown: str,
    input_issue_keys: list[str],
    components: list[dict[str, Any]],
    integration_contracts: list[dict[str, Any]],
) -> dict[str, Any]:
    """Publish generated Architecture Markdown and component sub-tasks through MCP."""
    server_params = StdioServerParameters(
        command=sys.executable,
        args=[str(SERVER_SCRIPT)],
        env=os.environ.copy(),
    )
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = _tool_json(await session.call_tool(
                "publish_arch_to_jira",
                arguments={
                    "epic_issue_key": epic_key,
                    "arch_markdown": arch_markdown,
                    "input_issue_keys": input_issue_keys,
                    "components_json": json.dumps(components, ensure_ascii=False),
                    "integration_contracts_json": json.dumps(integration_contracts, ensure_ascii=False),
                },
            ))
    if not isinstance(result, dict):
        raise RuntimeError("Jira returned an unexpected architecture publishing response.")
    return result


async def run(
    issue_key: str,
    provider: str,
    output_path: Path | None = None,
    model_name: str | None = None,
) -> Path:
    context = await collect_jira_context(issue_key)
    arch_result = await generate_arch_package(context, provider=provider, model_name=model_name)
    arch_markdown = arch_result.arch_markdown

    epic_key = context["business_vision_epic"].get("key", issue_key.strip().upper())
    destination = output_path or PROJECT_ROOT / "generated_arch" / f"ARCH_{epic_key}.md"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(arch_markdown.rstrip() + "\n", encoding="utf-8")

    input_keys = [
        str(item.get("key")).strip()
        for item in context.get("frd_user_stories", [])
        if item.get("key")
    ]

    publish_result = await publish_arch(
        epic_key,
        arch_markdown,
        input_keys,
        [comp.model_dump(mode="json") for comp in arch_result.components],
        [contract.model_dump(mode="json") for contract in arch_result.integration_contracts],
    )
    print(json.dumps({
        "arch_path": str(destination),
        "jira_publish": publish_result,
    }, indent=2))
    return destination


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fetch Jira FRD context and generate a System Architecture Document."
    )
    parser.add_argument("jira_key", help="Business Vision Epic or child issue key")
    parser.add_argument("--provider", choices=("gemini", "local"), default="gemini")
    parser.add_argument("--model", help="Override the configured model name")
    parser.add_argument("--output", type=Path, help="Architecture Markdown output path")
    args = parser.parse_args()

    asyncio.run(run(args.jira_key, args.provider, args.output, args.model))


if __name__ == "__main__":
    main()
