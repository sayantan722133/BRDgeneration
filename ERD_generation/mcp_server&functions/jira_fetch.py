"""Fetch Jira issues, architecture component precursors, and FRD context."""

import json
from typing import Any

import httpx

from customfun import (
    JIRA_BASE_URL,
    adf_to_text,
    architecture_component_ids,
    component_record,
    download_attachment,
    get_jira_headers,
    issue_summary,
    validate_issue_key,
)


async def get_jira_issue(issue_key: str) -> str:
    """Fetch Jira issue details, description, attachments, and parent hierarchy."""
    key = validate_issue_key(issue_key)
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(
            f"{JIRA_BASE_URL}/rest/api/3/issue/{key}",
            params={
                "fields": "summary,issuetype,status,description,parent,comment,labels,attachment"
            },
            headers=get_jira_headers(),
        )
    if response.status_code != 200:
        return json.dumps({
            "error": f"Issue lookup failed: {response.status_code}",
            "details": response.text,
        }, indent=2)

    result = issue_summary(response.json())
    comments = response.json().get("fields", {}).get("comment", {}).get("comments", [])
    result["recent_comments"] = [
        {
            "author": comment.get("author", {}).get("displayName", "Unknown"),
            "body": adf_to_text(comment.get("body")),
        }
        for comment in comments[-10:]
    ]
    return json.dumps(result, indent=2)


async def search_jira_issues(jql_query: str, max_results: int = 100) -> str:
    """Search Jira issues and return descriptions, labels, and parent metadata."""
    if not jql_query.strip():
        raise ValueError("jql_query must not be empty.")
    bounded_results = max(1, min(max_results, 100))
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(
            f"{JIRA_BASE_URL}/rest/api/3/search/jql",
            params={
                "jql": jql_query,
                "maxResults": bounded_results,
                "fields": "summary,issuetype,status,description,parent,labels,attachment",
            },
            headers=get_jira_headers(),
        )
    if response.status_code != 200:
        return json.dumps({
            "error": f"Issue search failed: {response.status_code}",
            "details": response.text,
        }, indent=2)
    return json.dumps(
        [issue_summary(issue) for issue in response.json().get("issues", [])],
        indent=2,
    )


async def get_arch_context(epic_key: str) -> str:
    """Fetch architecture components and FRD data for an Epic or direct child."""
    key = validate_issue_key(epic_key)
    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
        issue_response = await client.get(
            f"{JIRA_BASE_URL}/rest/api/3/issue/{key}",
            params={"fields": "summary,issuetype,parent,attachment"},
            headers=get_jira_headers(),
        )
        if issue_response.status_code != 200:
            return json.dumps({
                "error": f"Issue lookup failed: {issue_response.status_code}",
                "details": issue_response.text,
            }, indent=2)

        source = issue_summary(issue_response.json())
        if (source.get("issuetype") or "").casefold() == "epic":
            resolved_epic_key = key
        elif (source.get("parent_issuetype") or "").casefold() == "epic":
            resolved_epic_key = source.get("parent_issue_key") or ""
        else:
            return json.dumps({
                "error": f"{key} is neither a Jira Epic nor its direct child."
            }, indent=2)

        epic_response = await client.get(
            f"{JIRA_BASE_URL}/rest/api/3/issue/{resolved_epic_key}",
            params={"fields": "summary,issuetype,attachment"},
            headers=get_jira_headers(),
        )
        if epic_response.status_code != 200:
            return json.dumps({
                "error": f"Epic lookup failed: {epic_response.status_code}",
                "details": epic_response.text,
            }, indent=2)
        epic_data = epic_response.json()
        epic_fields = epic_data.get("fields", {})

        document_search = await client.get(
            f"{JIRA_BASE_URL}/rest/api/3/search/jql",
            params={
                "jql": f'parent = "{resolved_epic_key}" AND labels = "arch-output-document"',
                "maxResults": 100,
                "fields": "summary,issuetype,description,parent,labels,attachment",
            },
            headers=get_jira_headers(),
        )
        if document_search.status_code != 200:
            return json.dumps({
                "error": f"Architecture document search failed: {document_search.status_code}",
                "details": document_search.text,
            }, indent=2)
        arch_docs = document_search.json().get("issues", [])
        if not arch_docs:
            return json.dumps({
                "error": f"No [ARCH] document task found under Epic {resolved_epic_key}."
            }, indent=2)
        arch_docs.sort(key=lambda issue: issue.get("key", ""))
        arch_document = issue_summary(arch_docs[0])
        architecture_markdown = await download_attachment(
            client,
            arch_docs[0].get("fields", {}).get("attachment", []) or [],
            f"ARCH_{resolved_epic_key}.md",
        )
        if not architecture_markdown:
            return json.dumps({
                "error": f"No ARCH_{resolved_epic_key}.md attachment found on its Jira document task."
            }, indent=2)
        expected_component_ids = architecture_component_ids(
            architecture_markdown["markdown"]
        )

        component_search = await client.get(
            f"{JIRA_BASE_URL}/rest/api/3/search/jql",
            params={
                "jql": (
                    f'parent = "{arch_document["key"]}" AND labels = "arch-output-component" '
                    "ORDER BY key"
                ),
                "maxResults": 100,
                "fields": "summary,issuetype,description,parent,labels,created",
            },
            headers=get_jira_headers(),
        )
        if component_search.status_code != 200:
            return json.dumps({
                "error": f"Architecture component search failed: {component_search.status_code}",
                "details": component_search.text,
            }, indent=2)
        component_issues = component_search.json().get("issues", [])
        component_issues.sort(
            key=lambda issue: (
                issue.get("fields", {}).get("created", ""),
                issue.get("key", ""),
            ),
            reverse=True,
        )

        component_records = []
        seen_component_ids: set[str] = set()
        for issue in component_issues:
            labels = {
                str(label).casefold()
                for label in issue.get("fields", {}).get("labels", [])
            }
            if "superseded-output" in labels:
                continue
            record = component_record(issue_summary(issue))
            if (
                record
                and record["component_id"] in expected_component_ids
                and record["component_id"] not in seen_component_ids
            ):
                seen_component_ids.add(record["component_id"])
                component_records.append(record)
        missing_component_ids = expected_component_ids - seen_component_ids
        if missing_component_ids:
            return json.dumps({
                "error": (
                    "Architecture component tasks are missing or have no managed ERD entities: "
                    + ", ".join(sorted(missing_component_ids))
                )
            }, indent=2)

        frd_search = await client.get(
            f"{JIRA_BASE_URL}/rest/api/3/search/jql",
            params={
                "jql": f'parent = "{resolved_epic_key}" AND labels = "frd-output-document"',
                "maxResults": 100,
                "fields": "summary,attachment",
            },
            headers=get_jira_headers(),
        )
        if frd_search.status_code != 200:
            return json.dumps({
                "error": f"FRD document search failed: {frd_search.status_code}",
                "details": frd_search.text,
            }, indent=2)
        frd_docs = frd_search.json().get("issues", [])
        frd_docs.sort(key=lambda issue: issue.get("key", ""))
        if not frd_docs:
            return json.dumps({
                "error": f"No FRD document task found under Epic {resolved_epic_key}."
            }, indent=2)

        frd_markdown = await download_attachment(
            client, frd_docs[0].get("fields", {}).get("attachment", []) or [],
            f"FRD_{resolved_epic_key}.md",
        )
        if not frd_markdown:
            return json.dumps({
                "error": f"No FRD_{resolved_epic_key}.md attachment found on its Jira document task."
            }, indent=2)

    return json.dumps({
        "epic": {
            "key": resolved_epic_key,
            "summary": epic_fields.get("summary"),
            "description": adf_to_text(epic_fields.get("description")),
        },
        "source_issue": source,
        "architecture_document": {
            **arch_document,
            "markdown": architecture_markdown.get("markdown") if architecture_markdown else None,
        },
        "architecture_components": component_records,
        "frd_document": frd_markdown,
    }, indent=2, ensure_ascii=False)
