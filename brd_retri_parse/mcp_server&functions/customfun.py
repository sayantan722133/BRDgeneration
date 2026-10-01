"""Shared configuration and MCP tool registration for BRD requirement parsing."""

import base64
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env")

mcp = FastMCP("BRD-Requirements-Parser")
JIRA_BASE_URL = os.getenv("JIRA_BASE_URL", "").rstrip("/")
JIRA_USER_EMAIL = os.getenv("JIRA_USER_EMAIL")
JIRA_API_TOKEN = os.getenv("JIRA_API_TOKEN")
BRD_MASTER_ISSUE_KEY = os.getenv("BRD_MASTER_ISSUE_KEY", "KAN-4").strip().upper()


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


def get_attachment_headers() -> dict[str, str]:
    """Build authentication headers for Jira multipart requests."""
    headers = get_jira_headers()
    headers.pop("Content-Type", None)
    headers["X-Atlassian-Token"] = "no-check"
    return headers


def adf_to_text(node: dict | list | str | None) -> str:
    """Convert Jira Atlassian Document Format content into plain text."""
    if not node:
        return ""
    if isinstance(node, str):
        return node
    if isinstance(node, list):
        return "\n".join(adf_to_text(item) for item in node)
    chunks = [node.get("text", "")] if node.get("type") == "text" else []
    chunks.extend(adf_to_text(child) for child in node.get("content", []))
    return " ".join(part for part in chunks if part)


def register_tools() -> None:
    """Register Jira read and requirements publishing operations."""
    from bvision_fetch import get_brd_markdown, get_jira_issue, search_jira_issues
    from brd_upsave import create_brd_requirement_issues

    for tool in (
        get_jira_issue,
        search_jira_issues,
        get_brd_markdown,
        create_brd_requirement_issues,
    ):
        mcp.tool()(tool)


def main() -> None:
    register_tools()
    mcp.run(transport="stdio")


if __name__ == "__main__":
    sys.modules.setdefault("customfun", sys.modules[__name__])
    main()
