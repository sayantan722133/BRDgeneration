import json

import httpx

from customfun import (
    JIRA_BASE_URL,
    get_jira_auth_headers,
    get_jira_headers,
    normalize_brd_filename,
    save_brd_content,
)


async def save_brd_file(file_name: str, markdown_content: str) -> str:
    """Save the generated BRD as a local Markdown file."""
    file_path = save_brd_content(file_name, markdown_content)
    return f"BRD successfully written to: {file_path}"


async def publish_brd_to_jira(
    issue_key: str,
    file_name: str,
    markdown_content: str,
    comment: str = "",
) -> str:
    """Save a BRD locally, attach it to the Business Vision Epic, and add an audit comment."""
    normalized_key = issue_key.strip().upper()
    if not normalized_key:
        raise ValueError("issue_key must not be empty.")

    safe_name = normalize_brd_filename(file_name)
    local_path = save_brd_content(safe_name, markdown_content)

    async with httpx.AsyncClient(timeout=30.0) as client:
        source_response = await client.get(
            f"{JIRA_BASE_URL}/rest/api/3/issue/{normalized_key}",
            params={"fields": "summary,issuetype,parent"},
            headers=get_jira_headers(),
        )
        if source_response.status_code != 200:
            return json.dumps({
                "error": f"BRD saved locally but source issue lookup failed: {source_response.status_code}",
                "local_path": local_path,
                "details": source_response.text,
            }, indent=2)

        source_fields = source_response.json().get("fields", {})
        source_type = source_fields.get("issuetype", {}).get("name", "")
        source_parent = source_fields.get("parent", {})
        source_parent_fields = source_parent.get("fields", {})
        if source_type.casefold() == "epic":
            business_vision_key = normalized_key
        elif (source_parent_fields.get("issuetype", {}).get("name") or "").casefold() == "epic":
            business_vision_key = source_parent.get("key", "")
        else:
            return json.dumps({
                "error": f"{normalized_key} is not a Business Vision Epic or a child of one.",
                "local_path": local_path,
            }, indent=2)

        target_issue_key = business_vision_key
        upload_response = await client.post(
            f"{JIRA_BASE_URL}/rest/api/3/issue/{target_issue_key}/attachments",
            headers=get_jira_auth_headers(),
            files={"file": (safe_name, markdown_content.encode("utf-8"), "text/markdown")},
        )
        if upload_response.status_code not in (200, 201):
            return json.dumps({
                "error": f"BRD saved locally but upload to {target_issue_key} failed: {upload_response.status_code}",
                "local_path": local_path,
                "target_issue_key": target_issue_key,
                "details": upload_response.text,
            }, indent=2)

        attachment_data = upload_response.json()
        attachment = attachment_data[0] if isinstance(attachment_data, list) and attachment_data else {}
        audit_comment = comment.strip() or (
            f"BRD generated from Business Vision {business_vision_key} and attached to this Epic as {safe_name}."
        )
        comment_response = await client.post(
            f"{JIRA_BASE_URL}/rest/api/3/issue/{target_issue_key}/comment",
            headers=get_jira_headers(),
            json={
                "body": {
                    "type": "doc",
                    "version": 1,
                    "content": [{
                        "type": "paragraph",
                        "content": [{"type": "text", "text": audit_comment}],
                    }],
                },
            },
        )

    result = {
        "source_issue_key": normalized_key,
        "business_vision_key": business_vision_key,
        "target_issue_key": target_issue_key,
        "local_path": local_path,
        "attachment": {
            "id": attachment.get("id"),
            "filename": attachment.get("filename", safe_name),
            "content_url": attachment.get("content"),
        },
        "comment_posted": comment_response.status_code in (200, 201),
    }
    if comment_response.status_code not in (200, 201):
        result["comment_error"] = {
            "status": comment_response.status_code,
            "details": comment_response.text,
        }
    return json.dumps(result, indent=2)