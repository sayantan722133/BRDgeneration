import json

import httpx

from customfun import (
    JIRA_BASE_URL,
    extract_adf_text,
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
    """Save or replace the BRD attachment without duplicate files or comments."""
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
        target_response = await client.get(
            f"{JIRA_BASE_URL}/rest/api/3/issue/{target_issue_key}",
            params={"fields": "attachment,comment"},
            headers=get_jira_headers(),
        )
        if target_response.status_code != 200:
            return json.dumps({
                "error": f"BRD saved locally but target Epic lookup failed: {target_response.status_code}",
                "local_path": local_path,
                "target_issue_key": target_issue_key,
                "details": target_response.text,
            }, indent=2)
        target_fields = target_response.json().get("fields", {})
        existing_attachments = target_fields.get("attachment", []) or []

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
        uploaded_attachment_id = str(attachment.get("id", ""))
        if not uploaded_attachment_id:
            return json.dumps({
                "error": "BRD uploaded, but Jira did not return its attachment ID; older attachments were kept.",
                "local_path": local_path,
                "target_issue_key": target_issue_key,
            }, indent=2)

        attachment_cleanup_errors: list[dict[str, str]] = []
        generated_prefix = f"BRD_{business_vision_key}_".casefold()
        for existing_attachment in existing_attachments:
            old_filename = str(existing_attachment.get("filename", ""))
            old_id = str(existing_attachment.get("id", ""))
            is_generated_brd = old_filename.casefold() == safe_name.casefold() or (
                old_filename.casefold().startswith(generated_prefix)
                and old_filename.casefold().endswith(".md")
            )
            if old_id and old_id != uploaded_attachment_id and is_generated_brd:
                delete_response = await client.delete(
                    f"{JIRA_BASE_URL}/rest/api/3/attachment/{old_id}",
                    headers=get_jira_headers(),
                )
                if delete_response.status_code != 204:
                    attachment_cleanup_errors.append({
                        "attachment_id": old_id,
                        "filename": old_filename,
                        "error": f"Delete failed: {delete_response.status_code} {delete_response.text}",
                    })

        audit_comment = comment.strip() or (
            f"BRD generated from Business Vision {business_vision_key} and attached to this Epic as {safe_name}."
        )
        comments = (target_fields.get("comment") or {}).get("comments", [])
        comment_already_present = any(
            extract_adf_text(item.get("body")).strip() == audit_comment
            for item in comments
        )
        comment_posted = False
        comment_error = None
        comment_status = 200 if comment_already_present else None
        if not comment_already_present:
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
            comment_posted = comment_response.status_code in (200, 201)
            comment_status = comment_response.status_code
            if not comment_posted:
                comment_error = comment_response.text

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
        "attachment_cleanup_errors": attachment_cleanup_errors,
        "comment_posted": comment_posted,
        "comment_already_present": comment_already_present,
    }
    if comment_error:
        result["comment_error"] = {
            "status": comment_status,
            "details": comment_error,
        }
    return json.dumps(result, indent=2)