"""Create one Jira execution ticket for every parsed BRD feature."""

import json
import re

import httpx

from customfun import JIRA_BASE_URL, get_jira_headers


def _adf_paragraph(text: str) -> dict[str, object]:
    return {
        "type": "paragraph",
        "content": [{"type": "text", "text": text}],
    }


def _jira_label(value: str) -> str:
    label = re.sub(r"[^a-zA-Z0-9_-]+", "-", value.casefold()).strip("-")
    return label[:255]


async def create_brd_requirement_issues(
    source_issue_key: str,
    requirements_json: str,
) -> str:
    """Create or reuse one Task per FR under the Business Vision Epic."""
    epic_key = source_issue_key.strip().upper()
    try:
        requirements = json.loads(requirements_json)
    except json.JSONDecodeError as error:
        raise ValueError("requirements_json must contain valid JSON.") from error

    if requirements.get("source_issue_key", "").strip().upper() != epic_key:
        raise ValueError("source_issue_key must match the parsed model source issue key.")
    modules = requirements.get("modules")
    if not isinstance(modules, list) or not modules:
        raise ValueError("The parsed requirements must contain at least one module.")

    async with httpx.AsyncClient(timeout=30.0) as client:
        epic_response = await client.get(
            f"{JIRA_BASE_URL}/rest/api/3/issue/{epic_key}",
            params={"fields": "project,issuetype"},
            headers=get_jira_headers(),
        )
        if epic_response.status_code != 200:
            return json.dumps({
                "error": f"Business Vision lookup failed: {epic_response.status_code}",
                "details": epic_response.text,
            }, indent=2)
        epic_fields = epic_response.json().get("fields", {})
        if epic_fields.get("issuetype", {}).get("name", "").casefold() != "epic":
            return json.dumps({"error": f"{epic_key} is not a Jira Epic."}, indent=2)
        project_key = epic_fields.get("project", {}).get("key")

        metadata_response = await client.get(
            f"{JIRA_BASE_URL}/rest/api/3/issue/createmeta/{project_key}/issuetypes",
            headers=get_jira_headers(),
        )
        if metadata_response.status_code != 200:
            return json.dumps({
                "error": f"Issue type lookup failed: {metadata_response.status_code}",
                "details": metadata_response.text,
            }, indent=2)
        issue_types = metadata_response.json().get("issueTypes", [])
        ticket_type = next(
            (issue_type for issue_type in issue_types
             if issue_type.get("name", "").casefold() == "story" and not issue_type.get("subtask")),
            None,
        ) or next(
            (issue_type for issue_type in issue_types
             if issue_type.get("name", "").casefold() == "task" and not issue_type.get("subtask")),
            None,
        )
        if not ticket_type:
            return json.dumps({
                "error": f"Project {project_key} has no Story or Task issue type that can be linked to an Epic."
            }, indent=2)

        results: list[dict[str, object]] = []
        errors: list[dict[str, str]] = []
        for module in modules:
            module_id = str(module.get("module_id", "")).strip()
            module_name = str(module.get("name", "")).strip()
            features = module.get("features")
            if not module_id or not module_name or not isinstance(features, list):
                errors.append({"module_id": module_id, "error": "Invalid module data."})
                continue

            module_label = _jira_label(module_id)
            for feature in features:
                requirement_id = str(feature.get("requirement_id", "")).strip().upper()
                feature_name = str(feature.get("name", "")).strip()
                if not requirement_id or not feature_name:
                    errors.append({"module_id": module_id, "error": "Feature is missing its ID or name."})
                    continue

                requirement_label = _jira_label(f"brd-{requirement_id}")
                duplicate_response = await client.get(
                    f"{JIRA_BASE_URL}/rest/api/3/search/jql",
                    params={
                        "jql": f'parent = "{epic_key}" AND labels = "{requirement_label}"',
                        "maxResults": 1,
                        "fields": "summary",
                    },
                    headers=get_jira_headers(),
                )
                if duplicate_response.status_code != 200:
                    errors.append({
                        "requirement_id": requirement_id,
                        "error": f"Duplicate check failed: {duplicate_response.status_code}",
                    })
                    continue

                existing = duplicate_response.json().get("issues", [])
                if existing:
                    issue = existing[0]
                    results.append({
                        "requirement_id": requirement_id,
                        "module_id": module_id,
                        "issue_key": issue.get("key"),
                        "summary": issue.get("fields", {}).get("summary"),
                        "created": False,
                    })
                    continue

                acceptance_criteria = feature.get("acceptance_criteria", [])
                description_content = [
                    _adf_paragraph(f"Business Vision: {epic_key}"),
                    _adf_paragraph(f"Module: {module_name} ({module_id})"),
                    _adf_paragraph(f"Requirement: {requirement_id}"),
                    _adf_paragraph(f"Priority: {feature.get('priority', 'Unspecified')}"),
                    _adf_paragraph("Acceptance criteria:"),
                ]
                if acceptance_criteria:
                    description_content.append({
                        "type": "bulletList",
                        "content": [
                            {
                                "type": "listItem",
                                "content": [_adf_paragraph(str(criterion))],
                            }
                            for criterion in acceptance_criteria
                        ],
                    })

                summary = f"[{requirement_id}] {feature_name}"[:255]
                create_response = await client.post(
                    f"{JIRA_BASE_URL}/rest/api/3/issue",
                    headers=get_jira_headers(),
                    json={"fields": {
                        "project": {"key": project_key},
                        "parent": {"key": epic_key},
                        "issuetype": {"id": ticket_type["id"]},
                        "summary": summary,
                        "description": {
                            "type": "doc",
                            "version": 1,
                            "content": description_content,
                        },
                        "labels": ["brd-requirement", requirement_label, module_label],
                    }},
                )
                if create_response.status_code not in (200, 201):
                    errors.append({
                        "requirement_id": requirement_id,
                        "error": f"Ticket creation failed: {create_response.status_code} {create_response.text}",
                    })
                    continue

                results.append({
                    "requirement_id": requirement_id,
                    "module_id": module_id,
                    "issue_key": create_response.json().get("key"),
                    "summary": summary,
                    "created": True,
                })

    return json.dumps({
        "parent_issue_key": epic_key,
        "issue_type": ticket_type.get("name"),
        "tickets": results,
        "errors": errors,
    }, indent=2)
