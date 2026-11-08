"""Independent Jira MCP server for System Architecture context and publishing."""

import base64
import os
import re
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
ISSUE_KEY_PATTERN = re.compile(r"^[A-Z][A-Z0-9]+-\d+$")
COMPONENT_ID_PATTERN = re.compile(
    r"^COMP-[A-Z0-9]+(?:-[A-Z0-9]+)*-\d+$", re.IGNORECASE
)


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


def validate_issue_key(issue_key: str) -> str:
    """Normalize and validate a Jira issue key."""
    key = issue_key.strip().upper()
    if not ISSUE_KEY_PATTERN.fullmatch(key):
        raise ValueError("issue_key must be a valid Jira key, for example KAN-4.")
    return key


def select_frd_attachment(attachments: list[dict], epic_key: str) -> dict | None:
    """Select the newest FRD Markdown attachment for an Epic."""
    markdown_attachments = [
        attachment for attachment in attachments
        if str(attachment.get("filename", "")).casefold().startswith(f"frd_{epic_key}".casefold())
        and str(attachment.get("filename", "")).casefold().endswith(".md")
    ]
    stable_name = f"FRD_{epic_key}.md".casefold()
    return next(
        (attachment for attachment in markdown_attachments
         if str(attachment.get("filename", "")).casefold() == stable_name),
        max(markdown_attachments, key=lambda attachment: attachment.get("created", ""), default=None),
    )


def paragraph(text: str) -> dict[str, object]:
    """Build a Jira Atlassian Document Format paragraph."""
    return {
        "type": "paragraph",
        "content": [{"type": "text", "text": text}],
    }


def normalize_label(value: str) -> str:
    """Normalize a string into a valid Jira label."""
    return re.sub(r"[^a-zA-Z0-9_-]+", "-", value.casefold()).strip("-")[:255]


def component_output_label(component: dict[str, object]) -> str:
    """Build a stable label for a generated architecture component."""
    return normalize_label(f"arch-comp-{component['component_id']}")


def component_description(comp: dict[str, object]) -> list[dict[str, object]]:
    """Build Jira ADF content describing an architecture component."""
    fr_keys = ", ".join(comp.get("source_requirement_ids", []))
    story_keys = ", ".join(comp.get("source_story_ids", []))
    tech = ", ".join(comp.get("tech_stack", []))
    entities = ", ".join(comp.get("data_entities_handled", []))
    deps = ", ".join(comp.get("dependencies", [])) or "None"

    return [
        paragraph(f"Component ID: {comp['component_id']}"),
        paragraph(f"Type: {comp['component_type']}"),
        paragraph(f"Module: {comp['module_id']}"),
        paragraph(f"Tech Stack: {tech}"),
        paragraph(f"Dependencies: {deps}"),
        paragraph(f"Managed Data Entities (ERD Precursors): {entities}"),
        paragraph(f"Traceable FR IDs: {fr_keys}"),
        paragraph(f"Traceable User Stories: {story_keys}"),
        paragraph("Core Responsibilities:"),
        {
            "type": "bulletList",
            "content": [
                {"type": "listItem", "content": [paragraph(str(item))]}
                for item in comp.get("responsibilities", [])
            ],
        },
    ]


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
