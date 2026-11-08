"""Independent Jira MCP server for ERD context retrieval and publishing."""

import base64
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
import httpx
from mcp.server.fastmcp import FastMCP

PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env")

mcp = FastMCP("Jira-ERD-Context")
JIRA_BASE_URL = os.getenv("JIRA_BASE_URL", "").rstrip("/")
ISSUE_KEY_PATTERN = re.compile(r"^[A-Z][A-Z0-9]+-\d+$")
COMPONENT_ID_PATTERN = re.compile(
    r"^COMP-[A-Z0-9]+(?:-[A-Z0-9]+)*-\d+$", re.IGNORECASE
)
TABLE_NAME_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def get_jira_headers() -> dict[str, str]:
    """Build authenticated JSON headers for Jira REST API v3."""
    base_url = os.getenv("JIRA_BASE_URL", "").rstrip("/")
    email = os.getenv("JIRA_USER_EMAIL")
    api_token = os.getenv("JIRA_API_TOKEN")
    if not base_url:
        raise ValueError("Missing JIRA_BASE_URL in environment.")
    if not email or not api_token:
        raise ValueError("Missing JIRA_USER_EMAIL or JIRA_API_TOKEN in environment.")
    token = base64.b64encode(f"{email}:{api_token}".encode()).decode()
    return {
        "Authorization": f"Basic {token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


def get_attachment_headers() -> dict[str, str]:
    """Build Jira authentication headers for multipart attachment uploads."""
    headers = get_jira_headers()
    headers.pop("Content-Type", None)
    headers["X-Atlassian-Token"] = "no-check"
    return headers


def adf_to_text(node: dict | list | str | None) -> str:
    """Convert Atlassian Document Format content to readable plain text."""
    if not node:
        return ""
    if isinstance(node, str):
        return node
    if isinstance(node, list):
        return "\n".join(filter(None, (adf_to_text(item) for item in node)))
    if not isinstance(node, dict):
        return ""
    if node.get("type") == "text":
        return str(node.get("text", ""))
    separator = "\n" if node.get("type") in {"paragraph", "heading", "listItem"} else " "
    return separator.join(
        part for part in (adf_to_text(child) for child in node.get("content", [])) if part
    )


def validate_issue_key(issue_key: str) -> str:
    """Normalize and validate a Jira issue key."""
    key = issue_key.strip().upper()
    if not ISSUE_KEY_PATTERN.fullmatch(key):
        raise ValueError("issue_key must be a valid Jira key, for example KAN-4.")
    return key


def issue_summary(issue: dict[str, Any]) -> dict[str, Any]:
    """Select the Jira issue fields used by the ERD workflow."""
    fields = issue.get("fields", {})
    parent = fields.get("parent", {})
    parent_fields = parent.get("fields", {})
    return {
        "key": issue.get("key"),
        "summary": fields.get("summary"),
        "issuetype": fields.get("issuetype", {}).get("name"),
        "status": fields.get("status", {}).get("name"),
        "description": adf_to_text(fields.get("description")),
        "labels": fields.get("labels", []),
        "parent_issue_key": parent.get("key"),
        "parent_summary": parent_fields.get("summary"),
        "parent_issuetype": parent_fields.get("issuetype", {}).get("name"),
        "attachments": fields.get("attachment", []) or [],
    }


def extract_managed_entities(description: str) -> list[str]:
    """Extract the architecture component's managed ERD precursor entities."""
    match = re.search(
        r"Managed Data Entities \(ERD Precursors\):[ \t]*(.*)",
        description,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if not match:
        return []
    value = re.split(
        r"(?im)(?:^|\s+)(?:Traceable FR IDs:|Traceable User Stories:|Core Responsibilities:)",
        match.group(1),
        maxsplit=1,
    )[0]
    entities = [entity.strip() for entity in value.split(",") if entity.strip()]
    return [
        entity for entity in entities
        if not re.match(
            r"^(?:Traceable FR IDs|Traceable User Stories|Core Responsibilities):",
            entity,
            flags=re.IGNORECASE,
        )
    ]


def component_record(issue: dict[str, Any]) -> dict[str, Any] | None:
    """Build a structured architecture component record from its Jira issue."""
    description = str(issue.get("description") or "")
    component_match = re.search(
        r"\bComponent ID:\s*(COMP-[A-Z0-9]+(?:-[A-Z0-9]+)*-\d+)\b",
        description,
        re.I,
    )
    component_id = component_match.group(1).upper() if component_match else ""
    if not COMPONENT_ID_PATTERN.fullmatch(component_id):
        for label in issue.get("labels", []):
            if COMPONENT_ID_PATTERN.fullmatch(str(label)):
                component_id = str(label).upper()
                break
    if not component_id:
        return None

    managed_entities = extract_managed_entities(description)
    if not managed_entities:
        return None
    return {
        "component_id": component_id,
        "issue_key": issue.get("key"),
        "summary": issue.get("summary"),
        "managed_data_entities": managed_entities,
        "description": description,
    }


def architecture_component_ids(markdown: str) -> set[str]:
    """Read the canonical component inventory from an architecture traceability table."""
    section = re.search(
        r"^#+\s+.*Traceability Matrix.*$([\s\S]*?)(?=^#+\s|\Z)",
        markdown,
        flags=re.IGNORECASE | re.MULTILINE,
    )
    if not section:
        raise ValueError("Architecture Markdown is missing its Traceability Matrix section.")
    rows = [
        [cell.strip() for cell in line.strip().strip("|").split("|")]
        for line in section.group(1).splitlines()
        if line.strip().startswith("|") and line.strip().endswith("|")
    ]
    if len(rows) < 3 or not rows[0] or rows[0][0].casefold() != "component id":
        raise ValueError("Architecture Traceability Matrix has no Component ID table.")
    component_ids = {
        row[0].upper()
        for row in rows[2:]
        if (
            len(row) >= 5
            and row[4]
            and COMPONENT_ID_PATTERN.fullmatch(row[0])
        )
    }
    if not component_ids:
        raise ValueError("Architecture Traceability Matrix contains no valid component IDs.")
    return component_ids


async def download_attachment(
    client: httpx.AsyncClient, attachments: list[dict[str, Any]], expected_filename: str
) -> dict[str, str] | None:
    """Download a named UTF-8 Jira attachment."""
    attachment = next(
        (
            item for item in attachments
            if str(item.get("filename", "")).casefold() == expected_filename.casefold()
        ),
        None,
    )
    if not attachment or not attachment.get("id"):
        return None
    response = await client.get(
        f"{JIRA_BASE_URL}/rest/api/3/attachment/content/{attachment['id']}",
        headers=get_attachment_headers(),
    )
    if response.status_code != 200:
        raise RuntimeError(
            f"Attachment download failed for {expected_filename}: "
            f"{response.status_code} {response.text}"
        )
    try:
        content = response.content.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise ValueError(f"Attachment {expected_filename} is not UTF-8 text.") from error
    return {"filename": str(attachment.get("filename")), "markdown": content}


def paragraph(text: str) -> dict[str, Any]:
    """Build a Jira ADF paragraph."""
    return {"type": "paragraph", "content": [{"type": "text", "text": text}]}


def normalize_label(value: str) -> str:
    """Convert a value to a Jira-safe label."""
    return re.sub(r"[^a-zA-Z0-9_-]+", "-", value.casefold()).strip("-")[:255]


def entity_output_label(entity: dict[str, Any]) -> str:
    """Build the stable Jira label used to find an entity task on reruns."""
    return normalize_label(f"erd-entity-{entity['table_name']}")


def entity_description(entity: dict[str, Any]) -> list[dict[str, Any]]:
    """Build a Jira ADF description for a generated database entity."""
    lines = [f"Database table: {entity['table_name']}", "Columns:"]
    for attribute in entity.get("attributes", []):
        constraints = []
        if attribute.get("is_primary"):
            constraints.append("PK")
        if attribute.get("is_foreign"):
            constraints.append("FK")
        suffix = f" ({', '.join(constraints)})" if constraints else ""
        lines.append(f"- {attribute['name']}: {attribute['data_type']}{suffix}")
    return [paragraph(line) for line in lines]


def parse_entities(entities_json: str) -> list[dict[str, Any]]:
    """Parse and validate structured entity JSON before Jira writes."""
    try:
        entities = json.loads(entities_json)
    except json.JSONDecodeError as error:
        raise ValueError("entities_json must contain valid JSON.") from error
    if not isinstance(entities, list):
        raise ValueError("entities_json must contain a JSON array.")
    if not entities:
        raise ValueError("entities_json must contain at least one entity.")
    for entity in entities:
        if not isinstance(entity, dict) or not TABLE_NAME_PATTERN.fullmatch(
            str(entity.get("table_name", ""))
        ):
            raise ValueError("Each entity must have a valid table_name.")
        attributes = entity.get("attributes")
        if not isinstance(attributes, list) or not attributes:
            raise ValueError(f"Entity {entity['table_name']} must contain attributes.")
        attribute_names = []
        primary_key_count = 0
        for attribute in attributes:
            if (
                not isinstance(attribute, dict)
                or not TABLE_NAME_PATTERN.fullmatch(str(attribute.get("name", "")))
                or not isinstance(attribute.get("data_type"), str)
                or not attribute["data_type"].strip()
                or "\n" in attribute["data_type"]
                or "|" in attribute["data_type"]
                or not isinstance(attribute.get("is_primary", False), bool)
                or not isinstance(attribute.get("is_foreign", False), bool)
            ):
                raise ValueError(f"Entity {entity['table_name']} contains an invalid attribute.")
            attribute_names.append(attribute["name"].casefold())
            primary_key_count += bool(attribute.get("is_primary", False))
        if len(attribute_names) != len(set(attribute_names)):
            raise ValueError(f"Entity {entity['table_name']} contains duplicate attributes.")
        if not primary_key_count:
            raise ValueError(f"Entity {entity['table_name']} must contain a primary key.")
    names = [entity["table_name"].casefold() for entity in entities]
    if len(names) != len(set(names)):
        raise ValueError("entities_json contains duplicate table names.")
    return entities


def register_tools() -> None:
    """Register Jira context retrieval and ERD publishing tools."""
    from jira_fetch import get_arch_context, get_jira_issue, search_jira_issues
    from jira_publish import publish_erd_to_jira

    for tool in (get_jira_issue, search_jira_issues, get_arch_context, publish_erd_to_jira):
        mcp.tool()(tool)


def main() -> None:
    register_tools()
    mcp.run(transport="stdio")


if __name__ == "__main__":
    sys.modules.setdefault("customfun", sys.modules[__name__])
    main()
