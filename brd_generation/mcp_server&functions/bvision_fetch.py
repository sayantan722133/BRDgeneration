import json

import httpx

from customfun import JIRA_BASE_URL, extract_adf_text, get_jira_headers


async def get_jira_issue(issue_key: str) -> str:
    """Fetch summary, type, description, status, and recent comments for a Jira issue."""
    url = f"{JIRA_BASE_URL}/rest/api/3/issue/{issue_key.strip().upper()}?expand=renderedFields,names"

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(url, headers=get_jira_headers())
        if response.status_code != 200:
            return json.dumps({
                "error": f"Failed to retrieve {issue_key}: {response.status_code}",
                "details": response.text,
            })

        data = response.json()
        fields = data.get("fields", {})
        comments_data = fields.get("comment", {}).get("comments", [])
        result = {
            "key": data.get("key"),
            "summary": fields.get("summary"),
            "issuetype": fields.get("issuetype", {}).get("name"),
            "status": fields.get("status", {}).get("name"),
            "description": extract_adf_text(fields.get("description")).strip(),
            "recent_comments": [
                f"[{comment.get('author', {}).get('displayName', 'Unknown')}]: "
                f"{extract_adf_text(comment.get('body'))}"
                for comment in comments_data[-5:]
            ],
        }
        return json.dumps(result, indent=2)


async def search_jira_issues(jql_query: str, max_results: int = 5) -> str:
    """Search for related Jira issues using Jira Query Language."""
    url = f"{JIRA_BASE_URL}/rest/api/3/search/jql"
    params = {
        "jql": jql_query,
        "maxResults": max_results,
        "fields": "summary,status,issuetype",
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(url, params=params, headers=get_jira_headers())
        if response.status_code != 200:
            return json.dumps({
                "error": f"Search failed: {response.status_code}",
                "details": response.text,
            })

        issues = response.json().get("issues", [])
        return json.dumps([
            {
                "key": issue.get("key"),
                "summary": issue.get("fields", {}).get("summary"),
                "type": issue.get("fields", {}).get("issuetype", {}).get("name"),
                "status": issue.get("fields", {}).get("status", {}).get("name"),
            }
            for issue in issues
        ], indent=2)