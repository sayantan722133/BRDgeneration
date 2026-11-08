"""Independent Jira MCP server for FRD context retrieval."""

import base64
import os
import re
import sys
from pathlib import Path

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env")

mcp = FastMCP("Jira-FRD-Context")
JIRA_BASE_URL = os.getenv("JIRA_BASE_URL", "").rstrip("/")
JIRA_USER_EMAIL = os.getenv("JIRA_USER_EMAIL")
JIRA_API_TOKEN = os.getenv("JIRA_API_TOKEN")
ISSUE_KEY_PATTERN = re.compile(r"^[A-Z][A-Z0-9]+-\d+$")
REQUIREMENT_ID_PATTERN = re.compile(r"^FR-\d+$", re.IGNORECASE)
STORY_ID_PATTERN = re.compile(r"^US-FR-\d+$", re.IGNORECASE)


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


def paragraph(text: str) -> dict[str, object]:
    """Build a Jira Atlassian Document Format paragraph."""
    return {
        "type": "paragraph",
        "content": [{"type": "text", "text": text}],
    }


def normalize_label(value: str) -> str:
    """Normalize a string into a valid Jira label."""
    return re.sub(r"[^a-zA-Z0-9_-]+", "-", value.casefold()).strip("-")[:255]


def story_description(story: dict[str, object]) -> list[dict[str, object]]:
    """Build the Jira description content for an FRD user story."""
    source_keys = ", ".join(story["source_issue_keys"])
    content: list[dict[str, object]] = [
        paragraph(f"Story ID: {story['story_id']}"),
        paragraph(f"Source requirement: {story['source_requirement_id']}"),
        paragraph(f"Module: {story['module_id']}"),
        paragraph(f"BRD input issues: {source_keys}"),
        paragraph(f"Priority: {story['priority']}"),
        paragraph("User story (INVEST):"),
        paragraph(story["user_story"]),
        paragraph("Acceptance criteria (Given/When/Then scenarios):"),
        {
            "type": "bulletList",
            "content": [
                {"type": "listItem", "content": [paragraph(criterion)]}
                for criterion in story["acceptance_criteria"]
            ],
        },
    ]
    if story["assumptions"]:
        content.extend([paragraph("Assumptions:")])
        content.extend(paragraph(item) for item in story["assumptions"])
    if story["open_questions"]:
        content.append(paragraph("Open questions:"))
        content.extend(paragraph(item) for item in story["open_questions"])
    return content


def validate_stories(
    stories: object,
    input_keys: list[str],
) -> tuple[list[dict[str, object]], list[dict[str, str]]]:
    """Validate generated stories and source issue traceability."""
    if not isinstance(stories, list):
        raise ValueError("user_stories_json must contain a JSON array.")

    valid_stories: list[dict[str, object]] = []
    errors: list[dict[str, str]] = []
    seen_requirements: set[str] = set()
    for story in stories:
        if not isinstance(story, dict):
            errors.append({"error": "Story entry must be an object."})
            continue

        requirement_id = str(story.get("source_requirement_id", "")).strip().upper()
        story_id = str(story.get("story_id", "")).strip().upper()
        source_keys = [
            str(key).strip().upper()
            for key in story.get("source_issue_keys", [])
            if isinstance(key, str) and ISSUE_KEY_PATTERN.fullmatch(key.strip().upper())
        ]
        statement = str(story.get("user_story", "")).strip()
        normalized_statement = statement.casefold()
        criteria = story.get("acceptance_criteria")
        title = str(story.get("title", "")).strip()
        valid = (
            bool(REQUIREMENT_ID_PATTERN.fullmatch(requirement_id))
            and bool(STORY_ID_PATTERN.fullmatch(story_id))
            and story_id == f"US-{requirement_id}"
            and requirement_id not in seen_requirements
            and bool(source_keys)
            and all(key in input_keys for key in source_keys)
            and bool(title)
            and normalized_statement.startswith(("as a ", "as an "))
            and ", i want " in normalized_statement
            and ", so that " in normalized_statement
            and isinstance(criteria, list)
            and 3 <= len(criteria) <= 7
            and all(
                all(term in str(criterion).casefold() for term in ("given", "when", "then"))
                for criterion in criteria
            )
        )
        if not valid:
            errors.append({
                "requirement_id": requirement_id,
                "error": "Story failed FRD story validation or references issues outside the BRD input set.",
            })
            continue

        seen_requirements.add(requirement_id)
        valid_stories.append({
            "story_id": story_id,
            "source_requirement_id": requirement_id,
            "source_issue_keys": source_keys,
            "module_id": str(story.get("module_id") or "Uncategorized"),
            "title": title,
            "user_story": statement,
            "priority": str(story.get("priority") or "Unspecified"),
            "acceptance_criteria": [str(item) for item in criteria],
            "assumptions": [str(item) for item in story.get("assumptions", [])],
            "open_questions": [str(item) for item in story.get("open_questions", [])],
        })
    return valid_stories, errors


def register_tools() -> None:
    """Register Jira context retrieval and FRD publishing tools."""
    from jira_fetch import get_brd_markdown, get_jira_issue, search_jira_issues
    from jira_publish import publish_frd_to_jira

    for tool in (get_jira_issue, get_brd_markdown, search_jira_issues, publish_frd_to_jira):
        mcp.tool()(tool)


def main() -> None:
    register_tools()
    mcp.run(transport="stdio")


if __name__ == "__main__":
    sys.modules.setdefault("customfun", sys.modules[__name__])
    main()
