"""Parse BRD functional requirements and publish them as Jira Tasks."""

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

CLIENT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = Path(__file__).resolve().parents[2]
SERVER_SCRIPT = PROJECT_ROOT / "brd_retri_parse" / "mcp_server&functions" / "customfun.py"
sys.path.insert(0, str(CLIENT_DIR))

from brd_retri_parser import parse_brd_requirements


def _tool_text(result: Any) -> str:
    text = "\n".join(item.text for item in result.content if hasattr(item, "text"))
    if getattr(result, "isError", False):
        raise RuntimeError(text or "MCP tool returned an error.")
    return text


def _tool_json(result: Any) -> dict[str, Any] | list[dict[str, Any]]:
    payload = json.loads(_tool_text(result))
    if isinstance(payload, dict) and payload.get("error"):
        details = payload.get("details")
        message = payload["error"]
        if details:
            message = f"{message}: {details}"
        raise RuntimeError(message)
    return payload


async def run(jira_key: str) -> None:
    source_key = jira_key.strip().upper()
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
                raise RuntimeError("Jira issue lookup returned an unexpected response.")
            if (source.get("issuetype") or "").casefold() == "epic":
                business_vision_key = source_key
                business_vision_summary = source.get("summary", "")
            elif (source.get("parent_issuetype") or "").casefold() == "epic":
                business_vision_key = source.get("parent_issue_key") or source_key
                business_vision_summary = source.get("parent_summary", "")
            else:
                business_vision_key = source_key
                business_vision_summary = source.get("summary", "")

            brd_attachment = _tool_json(await session.call_tool(
                "get_brd_markdown", arguments={"issue_key": source_key}
            ))
            if not isinstance(brd_attachment, dict):
                raise RuntimeError("Jira BRD attachment lookup returned an unexpected response.")
            markdown = brd_attachment.get("markdown_content")
            if not isinstance(markdown, str) or not markdown.strip():
                raise RuntimeError("The Jira BRD attachment is empty or could not be read as text.")
            requirements = parse_brd_requirements(
                markdown, business_vision_key, business_vision_summary
            )

            module_lines = [f"- {module.name}: {len(module.features)} feature(s)" for module in requirements.modules]
            description = "\n".join([
                f"Functional requirements parsed from Business Vision {business_vision_key}.",
                f"Source Jira attachment: {brd_attachment.get('attachment_name')}.",
                "Creating one executable Jira Task for each functional requirement.",
                "Module summary:",
                *module_lines,
            ])
            jira_result = _tool_json(await session.call_tool(
                "create_brd_requirement_issues",
                arguments={
                    "source_issue_key": business_vision_key,
                    "requirements_json": requirements.model_dump_json(indent=2),
                },
            ))

    print(json.dumps({
        "brd_attachment": {
            "issue_key": brd_attachment.get("attachment_issue_key"),
            "business_vision_key": brd_attachment.get("business_vision_key"),
            "filename": brd_attachment.get("attachment_name"),
        },
        "parsed_requirements": requirements.model_dump(mode="json"),
        "jira_result": jira_result,
    }, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description="Parse BRD requirements and create one Jira Task per requirement.")
    parser.add_argument("jira_key", help="Source Jira issue key, for example KAN-4")
    args = parser.parse_args()
    source_key = args.jira_key.strip().upper()
    asyncio.run(run(source_key))


if __name__ == "__main__":
    main()