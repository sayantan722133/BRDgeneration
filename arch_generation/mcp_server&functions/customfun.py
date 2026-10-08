"""Independent Jira MCP server for System Architecture context and publishing."""

import base64
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env")

mcp = FastMCP("Jira-Arch-Context")
JIRA_BASE_URL = os.getenv("JIRA_BASE_URL", "").rstrip("/")
JIRA_USER_EMAIL = os.getenv("JIRA_USER_EMAIL")
JIRA_API_TOKEN = os.getenv("JIRA_API_TOKEN")


def get_jira_headers() -> dict[str, str]:
    """Build authenticated JSON headers for Jira REST API v3."""
    if not JIRA_BASE_URL:
        raise ValueError("Missing JIRA_BASE_URL in environment.")
    if not JIRA_USER_EMAIL or not JIRA_API_TOKEN:
        raise ValueError("Missing JIRA_USER_EMAIL or JIRA_API_TOKEN in environment.")
    token = base64.b64encode(f"{JIRA_USER_EMAIL}:{JIRA_API_TOKEN}".encode()).decode()
    return {
        "Authorization": f"Basic {token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


def adf_to_text(node: dict | list | str | None) -> str:
    """Convert Atlassian Document Format content to plain text."""
    if not node:
        return ""
    if isinstance(node, str):
        return node
    if isinstance(node, list):
        return "\n".join(adf_to_text(item) for item in node)
    chunks = [node.get("text", "")] if node.get("type") == "text" else []
    chunks.extend(adf_to_text(child) for child in node.get("content", []))
    return " ".join(part for part in chunks if part)


def get_attachment_headers() -> dict[str, str]:
    """Build Jira authentication headers for multipart attachment uploads."""
    headers = get_jira_headers()
    headers.pop("Content-Type", None)
    headers["X-Atlassian-Token"] = "no-check"
    return headers


def register_tools() -> None:
    """Register Jira context retrieval and Architecture publishing tools."""
    from jira_fetch import get_frd_markdown, get_jira_issue, search_jira_issues
    from jira_publish import publish_arch_to_jira

    for tool in (get_jira_issue, get_frd_markdown, search_jira_issues, publish_arch_to_jira):
        mcp.tool()(tool)


def main() -> None:
    register_tools()
    mcp.run(transport="stdio")


if __name__ == "__main__":
    sys.modules.setdefault("customfun", sys.modules[__name__])
    main()
