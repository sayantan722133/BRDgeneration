"""Fetch Jira context over MCP and generate an FRD Markdown document."""

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
SERVER_SCRIPT = PROJECT_ROOT / "frd_generation" / "mcp_server&functions" / "customfun.py"
sys.path.insert(0, str(PROJECT_ROOT))

from frd_generation import generate_frd_package


ISSUE_KEY_PATTERN = re.compile(r"^[A-Z][A-Z0-9]+-\d+$")


def _tool_text(result: Any) -> str:
    text = "\n".join(item.text for item in result.content if hasattr(item, "text"))
    if getattr(result, "isError", False):
        raise RuntimeError(text or "FRD Jira MCP tool returned an error.")
    return text


def _tool_json(result: Any) -> dict[str, Any] | list[dict[str, Any]]:
    value = json.loads(_tool_text(result))
    if isinstance(value, dict) and value.get("error"):
        details = value.get("details")
        message = value["error"]
        raise RuntimeError(f"{message}: {details}" if details else message)
    return value


async def collect_jira_context(issue_key: str) -> dict[str, Any]:
    """Fetch the source Epic, attached BRD, and direct child Jira work items."""
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
                raise ValueError(f"{source_key} is not a Business Vision Epic or its direct child.")

            brd = _tool_json(await session.call_tool(
                "get_brd_markdown", arguments={"issue_key": epic_key}
            ))
            if not isinstance(brd, dict):
                raise RuntimeError("Jira returned an unexpected BRD attachment response.")
            markdown = brd.get("markdown_content")
            if not isinstance(markdown, str) or not markdown.strip():
                raise RuntimeError("The Jira BRD attachment is empty.")

            related = _tool_json(await session.call_tool(
                "search_jira_issues",
                arguments={
                    "jql_query": f'parent = "{epic_key}" ORDER BY key',
                    "max_results": 100,
                },
            ))
            if not isinstance(related, list):
                raise RuntimeError("Jira returned an unexpected related-issue search response.")

    return {
        "business_vision_epic": epic,
        "source_issue": source,
        "brd_attachment": {
            "filename": brd.get("attachment_name"),
            "markdown": markdown,
        },
        "related_jira_issues": related,
    }


async def publish_frd(
    epic_key: str,
    frd_markdown: str,
    input_issue_keys: list[str],
    user_stories: list[dict[str, Any]],
) -> dict[str, Any]:
    """Publish generated FRD Markdown through the independent Jira MCP server."""
    server_params = StdioServerParameters(
        command=sys.executable,
        args=[str(SERVER_SCRIPT)],
        env=os.environ.copy(),
    )
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = _tool_json(await session.call_tool(
                "publish_frd_to_jira",
                arguments={
                    "epic_issue_key": epic_key,
                    "frd_markdown": frd_markdown,
                    "input_issue_keys": input_issue_keys,
                    "user_stories_json": json.dumps(user_stories, ensure_ascii=False),
                },
            ))
    if not isinstance(result, dict):
        raise RuntimeError("Jira returned an unexpected FRD publishing response.")
    return result


async def run(
    issue_key: str,
    provider: str,
    output_path: Path | None = None,
    model_name: str | None = None,
) -> Path:
    context = await collect_jira_context(issue_key)
    frd_result = await generate_frd_package(context, provider=provider, model_name=model_name)
    frd_markdown = frd_result.frd_markdown
    epic_key = context["business_vision_epic"].get("key", issue_key.strip().upper())
    destination = output_path or PROJECT_ROOT / "generated_frds" / f"FRD_{epic_key}.md"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(frd_markdown.rstrip() + "\n", encoding="utf-8")
    input_issue_keys = []
    seen_input_issue_keys: set[str] = set()
    for item in context["related_jira_issues"]:
        key = str(item.get("key") or "").strip()
        if not key or key in seen_input_issue_keys:
            continue
        labels = [str(label).casefold() for label in item.get("labels", [])]
        if any(
            label in {"frd-output-document", "frd-output-story"}
            or label.startswith("frd-story-")
            for label in labels
        ):
            continue
        seen_input_issue_keys.add(key)
        input_issue_keys.append(key)
    publish_result = await publish_frd(
        epic_key,
        frd_markdown,
        input_issue_keys,
        [story.model_dump(mode="json") for story in frd_result.user_stories],
    )
    print(json.dumps({
        "frd_path": str(destination),
        "jira_publish": publish_result,
    }, indent=2))
    return destination


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fetch Jira BRD context and generate a Functional Requirements Document."
    )
    parser.add_argument("jira_key", help="Business Vision Epic or direct child issue key")
    parser.add_argument("--provider", choices=("gemini", "local"), default="gemini")
    parser.add_argument("--model", help="Override the configured Gemini or local model name")
    parser.add_argument("--output", type=Path, help="FRD Markdown output path")
    args = parser.parse_args()

    asyncio.run(run(args.jira_key, args.provider, args.output, args.model))


if __name__ == "__main__":
    main()
