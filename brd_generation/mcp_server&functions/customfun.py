import base64
import os
import sys

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

load_dotenv()

mcp = FastMCP("Jira-BRD-Server")
JIRA_BASE_URL = os.getenv("JIRA_BASE_URL", "").rstrip("/")
JIRA_USER_EMAIL = os.getenv("JIRA_USER_EMAIL")
JIRA_API_TOKEN = os.getenv("JIRA_API_TOKEN")


def get_jira_headers() -> dict:
    """Build Basic Authentication headers for Jira REST API v3."""
    if not JIRA_USER_EMAIL or not JIRA_API_TOKEN:
        raise ValueError("Missing JIRA_USER_EMAIL or JIRA_API_TOKEN in environment.")

    token = base64.b64encode(f"{JIRA_USER_EMAIL}:{JIRA_API_TOKEN}".encode()).decode()
    return {
        "Authorization": f"Basic {token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


def get_jira_auth_headers() -> dict:
    """Build authentication headers for Jira multipart requests."""
    headers = get_jira_headers()
    headers.pop("Content-Type", None)
    headers["X-Atlassian-Token"] = "no-check"
    return headers


def normalize_brd_filename(file_name: str) -> str:
    """Keep generated BRD files inside the output directory."""
    safe_name = os.path.basename(file_name.strip())
    if not safe_name:
        raise ValueError("file_name must not be empty.")
    if not safe_name.endswith(".md"):
        safe_name += ".md"
    return safe_name


def save_brd_content(file_name: str, markdown_content: str) -> str:
    """Write BRD content locally and return its absolute path."""
    safe_name = normalize_brd_filename(file_name)
    output_dir = "generated_brds"
    os.makedirs(output_dir, exist_ok=True)
    file_path = os.path.join(output_dir, safe_name)

    with open(file_path, "w", encoding="utf-8") as file_handle:
        file_handle.write(markdown_content)

    return os.path.abspath(file_path)


def extract_adf_text(adf_node: dict | list | str | None) -> str:
    """Recursively parse Jira's Atlassian Document Format into plain text."""
    if not adf_node:
        return ""
    if isinstance(adf_node, str):
        return adf_node
    if isinstance(adf_node, list):
        return "\n".join(extract_adf_text(item) for item in adf_node)

    text_chunks = []
    if adf_node.get("type") == "text":
        text_chunks.append(adf_node.get("text", ""))
    if "content" in adf_node:
        for child in adf_node["content"]:
            text_chunks.append(extract_adf_text(child))

    return " ".join(filter(None, text_chunks))


def register_tools() -> None:
    """Register Jira retrieval and BRD publishing functions with FastMCP."""
    from bvision_fetch import get_jira_issue, search_jira_issues
    from brd_upsave import publish_brd_to_jira, save_brd_file

    for tool in (get_jira_issue, search_jira_issues, save_brd_file, publish_brd_to_jira):
        mcp.tool()(tool)


def main() -> None:
    register_tools()
    mcp.run(transport="stdio")


if __name__ == "__main__":
    sys.modules.setdefault("customfun", sys.modules[__name__])
    main()