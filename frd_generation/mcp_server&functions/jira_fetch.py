"""Read Jira issues, linked tickets, and their BRD Markdown attachment."""

import json
import re

import httpx

from customfun import JIRA_BASE_URL, adf_to_text, get_attachment_headers, get_jira_headers

_ISSUE_KEY = re.compile(r"^[A-Z][A-Z0-9]+-\d+$")


def _validate_issue_key(issue_key: str) -> str:
    key = issue_key.strip().upper()
    if not _ISSUE_KEY.fullmatch(key):
        raise ValueError("issue_key must be a valid Jira key, for example KAN-4.")
    return key


async def get_jira_issue(issue_key: str) -> str:
    """Fetch issue details, description, comments, and parent hierarchy."""
    key = _validate_issue_key(issue_key)
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(
            f"{JIRA_BASE_URL}/rest/api/3/issue/{key}",
            params={"fields": "summary,issuetype,status,description,parent,comment,labels"},
            headers=get_jira_headers(),
        )
    if response.status_code != 200:
        return json.dumps({
            "error": f"Issue lookup failed: {response.status_code}",
            "details": response.text,
        })

    data = response.json()
    fields = data.get("fields", {})
    parent = fields.get("parent", {})
    parent_fields = parent.get("fields", {})
    comments = fields.get("comment", {}).get("comments", [])
    return json.dumps({
        "key": data.get("key"),
        "summary": fields.get("summary"),
        "issuetype": fields.get("issuetype", {}).get("name"),
        "status": fields.get("status", {}).get("name"),
        "description": adf_to_text(fields.get("description")),
        "labels": fields.get("labels", []),
        "parent_issue_key": parent.get("key"),
        "parent_summary": parent_fields.get("summary"),
        "parent_issuetype": parent_fields.get("issuetype", {}).get("name"),
        "recent_comments": [
            {
                "author": comment.get("author", {}).get("displayName", "Unknown"),
                "body": adf_to_text(comment.get("body")),
            }
            for comment in comments[-10:]
        ],
    }, indent=2)


async def search_jira_issues(jql_query: str, max_results: int = 50) -> str:
    """Search related Jira issues and return descriptions and status for context."""
    bounded_results = max(1, min(max_results, 100))
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(
            f"{JIRA_BASE_URL}/rest/api/3/search/jql",
            params={
                "jql": jql_query,
                "maxResults": bounded_results,
                "fields": "summary,issuetype,status,description,labels",
            },
            headers=get_jira_headers(),
        )
    if response.status_code != 200:
        return json.dumps({
            "error": f"Issue search failed: {response.status_code}",
            "details": response.text,
        })

    return json.dumps([
        {
            "key": issue.get("key"),
            "summary": issue.get("fields", {}).get("summary"),
            "type": issue.get("fields", {}).get("issuetype", {}).get("name"),
            "status": issue.get("fields", {}).get("status", {}).get("name"),
            "description": adf_to_text(issue.get("fields", {}).get("description")),
            "labels": issue.get("fields", {}).get("labels", []),
        }
        for issue in response.json().get("issues", [])
    ], indent=2)


async def get_brd_markdown(issue_key: str) -> str:
    """Download the BRD_<EPIC_KEY>.md attachment from a Business Vision Epic."""
    key = _validate_issue_key(issue_key)
    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
        issue_response = await client.get(
            f"{JIRA_BASE_URL}/rest/api/3/issue/{key}",
            params={"fields": "summary,issuetype,parent"},
            headers=get_jira_headers(),
        )
        if issue_response.status_code != 200:
            return json.dumps({
                "error": f"Issue lookup failed: {issue_response.status_code}",
                "details": issue_response.text,
            }, indent=2)

        issue_fields = issue_response.json().get("fields", {})
        issue_type = issue_fields.get("issuetype", {}).get("name", "")
        parent = issue_fields.get("parent", {})
        parent_fields = parent.get("fields", {})
        if issue_type.casefold() == "epic":
            epic_key = key
        elif (parent_fields.get("issuetype", {}).get("name") or "").casefold() == "epic":
            epic_key = parent.get("key", "")
        else:
            return json.dumps({
                "error": f"{key} is neither a Business Vision Epic nor its direct child.",
            }, indent=2)

        epic_response = await client.get(
            f"{JIRA_BASE_URL}/rest/api/3/issue/{epic_key}",
            params={"fields": "summary,attachment,issuetype"},
            headers=get_jira_headers(),
        )
        if epic_response.status_code != 200:
            return json.dumps({
                "error": f"Epic lookup failed: {epic_response.status_code}",
                "details": epic_response.text,
            }, indent=2)

        epic_fields = epic_response.json().get("fields", {})
        expected_name = f"BRD_{epic_key}.md".casefold()
        attachment = next(
            (
                item for item in epic_fields.get("attachment", []) or []
                if str(item.get("filename", "")).casefold() == expected_name
            ),
            None,
        )
        if not attachment:
            available = [
                item.get("filename")
                for item in epic_fields.get("attachment", []) or []
                if str(item.get("filename", "")).casefold().endswith(".md")
            ]
            return json.dumps({
                "error": f"No {expected_name} attachment found on Epic {epic_key}.",
                "available_markdown_attachments": available,
            }, indent=2)

        attachment_id = attachment.get("id")
        if not attachment_id:
            return json.dumps({"error": "BRD attachment metadata is missing its attachment ID."}, indent=2)
        download = await client.get(
            f"{JIRA_BASE_URL}/rest/api/3/attachment/content/{attachment_id}",
            headers=get_attachment_headers(),
        )
        if download.status_code != 200:
            return json.dumps({
                "error": f"BRD attachment download failed: {download.status_code}",
                "details": download.text,
            }, indent=2)

    try:
        markdown = download.content.decode("utf-8-sig")
    except UnicodeDecodeError:
        return json.dumps({"error": "BRD attachment is not UTF-8 Markdown text."}, indent=2)

    return json.dumps({
        "epic_key": epic_key,
        "epic_summary": epic_fields.get("summary"),
        "attachment_name": attachment.get("filename"),
        "markdown_content": markdown,
    }, indent=2)
