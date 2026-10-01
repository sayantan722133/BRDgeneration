"""Jira issue, review-task, and BRD attachment retrieval tools."""

import json

import httpx

from customfun import BRD_MASTER_ISSUE_KEY, JIRA_BASE_URL, adf_to_text, get_jira_headers


async def get_jira_issue(issue_key: str) -> str:
    """Fetch issue details and its parent metadata from Jira."""
    key = issue_key.strip().upper()
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(
            f"{JIRA_BASE_URL}/rest/api/3/issue/{key}",
            params={"fields": "summary,issuetype,status,description,parent"},
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
    return json.dumps({
        "key": data.get("key"),
        "summary": fields.get("summary"),
        "issuetype": fields.get("issuetype", {}).get("name"),
        "status": fields.get("status", {}).get("name"),
        "description": adf_to_text(fields.get("description")),
        "parent_issue_key": parent.get("key"),
        "parent_summary": parent_fields.get("summary"),
        "parent_issuetype": parent_fields.get("issuetype", {}).get("name"),
    }, indent=2)


async def search_jira_issues(jql_query: str, max_results: int = 20) -> str:
    """Search Jira and return issue keys, summaries, and types."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(
            f"{JIRA_BASE_URL}/rest/api/3/search/jql",
            params={
                "jql": jql_query,
                "maxResults": max_results,
                "fields": "summary,issuetype",
            },
            headers=get_jira_headers(),
        )
    if response.status_code != 200:
        return json.dumps({
            "error": f"Search failed: {response.status_code}",
            "details": response.text,
        })
    return json.dumps([
        {
            "key": issue.get("key"),
            "summary": issue.get("fields", {}).get("summary"),
            "type": issue.get("fields", {}).get("issuetype", {}).get("name"),
        }
        for issue in response.json().get("issues", [])
    ], indent=2)


async def get_brd_markdown(issue_key: str) -> str:
    """Download the BRD attachment directly from the configured Business Vision Epic."""
    source_key = issue_key.strip().upper()

    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
        source_response = await client.get(
            f"{JIRA_BASE_URL}/rest/api/3/issue/{source_key}",
            params={"fields": "summary,issuetype,parent"},
            headers=get_jira_headers(),
        )
        if source_response.status_code != 200:
            return json.dumps({
                "error": f"Source issue lookup failed: {source_response.status_code}",
                "details": source_response.text,
            }, indent=2)

        source_data = source_response.json()
        source_fields = source_data.get("fields", {})
        source_type = source_fields.get("issuetype", {}).get("name", "")
        parent = source_fields.get("parent", {})
        parent_fields = parent.get("fields", {})
        if source_type.casefold() == "epic":
            business_vision_key = source_key
        elif (parent_fields.get("issuetype", {}).get("name") or "").casefold() == "epic":
            business_vision_key = parent.get("key", source_key)
        else:
            business_vision_key = source_key
        expected_name = f"BRD_{business_vision_key}.md".casefold()

        if business_vision_key != BRD_MASTER_ISSUE_KEY:
            return json.dumps({
                "error": f"Business Vision {business_vision_key} does not match configured BRD Epic {BRD_MASTER_ISSUE_KEY}.",
            }, indent=2)

        epic_response = await client.get(
            f"{JIRA_BASE_URL}/rest/api/3/issue/{BRD_MASTER_ISSUE_KEY}",
            params={"fields": "issuetype,attachment"},
            headers=get_jira_headers(),
        )
        if epic_response.status_code != 200:
            return json.dumps({
                "error": f"Configured BRD Epic {BRD_MASTER_ISSUE_KEY} lookup failed: {epic_response.status_code}",
                "details": epic_response.text,
            }, indent=2)

        epic_fields = epic_response.json().get("fields", {})
        epic_type = epic_fields.get("issuetype", {}).get("name", "")
        if epic_type.casefold() != "epic":
            return json.dumps({
                "error": f"Configured BRD issue {BRD_MASTER_ISSUE_KEY} is not a Jira Epic.",
            }, indent=2)

        attachments = [
            attachment
            for attachment in epic_fields.get("attachment", []) or []
            if str(attachment.get("filename", "")).casefold() == expected_name
        ]
        if not attachments:
            return json.dumps({
                "error": f"No matching BRD attachment named BRD_{business_vision_key}.md found on {BRD_MASTER_ISSUE_KEY}.",
                "available_markdown_attachments": [
                    attachment.get("filename")
                    for attachment in epic_fields.get("attachment", []) or []
                    if str(attachment.get("filename", "")).casefold().endswith(".md")
                ],
            }, indent=2)

        attachment = attachments[0]
        attachment_id = attachment.get("id")
        if not attachment_id:
            return json.dumps({"error": "The BRD attachment metadata did not include an attachment ID."}, indent=2)

        download_headers = get_jira_headers()
        download_headers.pop("Content-Type", None)
        download_response = await client.get(
            f"{JIRA_BASE_URL}/rest/api/3/attachment/content/{attachment_id}",
            headers=download_headers,
        )
        if download_response.status_code != 200:
            return json.dumps({
                "error": f"BRD attachment download failed: {download_response.status_code}",
                "attachment_name": attachment.get("filename"),
                "details": download_response.text,
            }, indent=2)

    try:
        markdown_content = download_response.content.decode("utf-8-sig")
    except UnicodeDecodeError:
        return json.dumps({
            "error": "The Jira attachment is not UTF-8 Markdown text.",
            "attachment_name": attachment.get("filename"),
        }, indent=2)

    return json.dumps({
        "source_issue_key": source_key,
        "business_vision_key": business_vision_key,
        "attachment_issue_key": BRD_MASTER_ISSUE_KEY,
        "attachment_name": attachment.get("filename"),
        "markdown_content": markdown_content,
    }, indent=2)
