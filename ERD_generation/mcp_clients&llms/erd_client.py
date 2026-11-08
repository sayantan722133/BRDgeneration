"""Fetch Jira architecture context, generate an ERD, and publish it to Jira."""

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
SERVER_SCRIPT = PROJECT_ROOT / "ERD_generation" / "mcp_server&functions" / "customfun.py"
sys.path.insert(0, str(PROJECT_ROOT))

from erd_agent import ErdGeneration, generate_erd_package

ISSUE_KEY_PATTERN = re.compile(r"^[A-Z][A-Z0-9]+-\d+$")


def _tool_text(result: Any) -> str:
    text = "\n".join(item.text for item in result.content if hasattr(item, "text"))
    if getattr(result, "isError", False):
        raise RuntimeError(text or "ERD Jira MCP tool returned an error.")
    return text


def _tool_json(result: Any) -> dict[str, Any] | list[dict[str, Any]]:
    value = json.loads(_tool_text(result))
    if isinstance(value, dict) and value.get("error"):
        details = value.get("details")
        message = value["error"]
        raise RuntimeError(f"{message}: {details}" if details else message)
    return value


async def collect_arch_context(issue_key: str) -> dict[str, Any]:
    """Fetch Epic architecture components and FRD Markdown through MCP."""
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
            result = _tool_json(await session.call_tool(
                "get_arch_context", arguments={"epic_key": source_key}
            ))
    if not isinstance(result, dict):
        raise RuntimeError("Jira returned an unexpected architecture context response.")
    components = result.get("architecture_components")
    if not isinstance(components, list) or not components:
        raise RuntimeError("Jira architecture context contains no ERD component precursors.")
    return result


async def publish_erd(
    epic_key: str, erd_markdown: str, entities: list[dict[str, Any]]
) -> dict[str, Any]:
    """Publish ERD Markdown and structured entities through the Jira MCP server."""
    server_params = StdioServerParameters(
        command=sys.executable,
        args=[str(SERVER_SCRIPT)],
        env=os.environ.copy(),
    )
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = _tool_json(await session.call_tool(
                "publish_erd_to_jira",
                arguments={
                    "epic_issue_key": epic_key,
                    "erd_markdown": erd_markdown,
                    "entities_json": json.dumps(entities, ensure_ascii=False),
                },
            ))
    if not isinstance(result, dict):
        raise RuntimeError("Jira returned an unexpected ERD publishing response.")
    return result


async def run(
    issue_key: str,
    provider: str,
    output_path: Path | None = None,
    model_name: str | None = None,
) -> Path:
    context = await collect_arch_context(issue_key)
    erd_result: ErdGeneration = await generate_erd_package(
        context, provider=provider, model_name=model_name
    )
    epic_key = str(context.get("epic", {}).get("key") or issue_key.strip().upper())
    destination = output_path or PROJECT_ROOT / "generated_erd" / f"ERD_{epic_key}.md"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(erd_result.erd_markdown.rstrip() + "\n", encoding="utf-8")
    publish_result = await publish_erd(
        epic_key,
        erd_result.erd_markdown,
        [entity.model_dump(mode="json") for entity in erd_result.entities],
    )
    print(json.dumps({
        "erd_path": str(destination),
        "jira_publish": publish_result,
    }, indent=2))
    return destination


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fetch Jira architecture context and generate a database ERD."
    )
    parser.add_argument("jira_key", help="Business Vision Epic or direct child issue key")
    parser.add_argument("--provider", choices=("gemini", "local"), default="gemini")
    parser.add_argument("--model", help="Override the configured Gemini or local model name")
    parser.add_argument("--output", type=Path, help="ERD Markdown output path")
    args = parser.parse_args()
    asyncio.run(run(args.jira_key, args.provider, args.output, args.model))


if __name__ == "__main__":
    main()
