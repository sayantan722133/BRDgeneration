"""Publish the generated ERD document and entity subtasks to Jira."""

import json

import httpx

from customfun import (
    JIRA_BASE_URL,
    entity_description,
    entity_output_label,
    get_attachment_headers,
    get_jira_headers,
    paragraph,
    parse_entities,
    validate_issue_key,
)


async def publish_erd_to_jira(
    epic_issue_key: str, erd_markdown: str, entities_json: str
) -> str:
    """Create or update an Epic child ERD Task, attach Markdown, and add entity subtasks."""
    epic_key = validate_issue_key(epic_issue_key)
    if not erd_markdown.strip():
        raise ValueError("erd_markdown must not be empty.")
    entities = parse_entities(entities_json)
    attachment_name = f"ERD_{epic_key}.md"

    async with httpx.AsyncClient(timeout=30.0) as client:
        epic_response = await client.get(
            f"{JIRA_BASE_URL}/rest/api/3/issue/{epic_key}",
            params={"fields": "project,issuetype"},
            headers=get_jira_headers(),
        )
        if epic_response.status_code != 200:
            return json.dumps({
                "error": f"Epic lookup failed: {epic_response.status_code}",
                "details": epic_response.text,
            }, indent=2)
        epic_fields = epic_response.json().get("fields", {})
        if (epic_fields.get("issuetype", {}).get("name") or "").casefold() != "epic":
            return json.dumps({"error": f"{epic_key} is not a Jira Epic."}, indent=2)
        project_key = epic_fields.get("project", {}).get("key")

        metadata = await client.get(
            f"{JIRA_BASE_URL}/rest/api/3/issue/createmeta/{project_key}/issuetypes",
            headers=get_jira_headers(),
        )
        if metadata.status_code != 200:
            return json.dumps({
                "error": f"Issue metadata lookup failed: {metadata.status_code}",
                "details": metadata.text,
            }, indent=2)
        issue_types = metadata.json().get("issueTypes", [])
        task_type = next(
            (
                issue_type for issue_type in issue_types
                if issue_type.get("name", "").casefold() == "task"
                and not issue_type.get("subtask")
            ),
            None,
        )
        subtask_type = next((item for item in issue_types if item.get("subtask")), None)
        if not task_type or not subtask_type:
            return json.dumps({
                "error": f"Project {project_key} must support Task and sub-task issue types."
            }, indent=2)

        existing_response = await client.get(
            f"{JIRA_BASE_URL}/rest/api/3/search/jql",
            params={
                "jql": f'parent = "{epic_key}" AND labels = "erd-output-document" ORDER BY key',
                "maxResults": 100,
                "fields": "summary,attachment",
            },
            headers=get_jira_headers(),
        )
        if existing_response.status_code != 200:
            return json.dumps({
                "error": f"ERD document search failed: {existing_response.status_code}",
                "details": existing_response.text,
            }, indent=2)
        existing_tasks = existing_response.json().get("issues", [])
        existing_tasks.sort(key=lambda issue: issue.get("key", ""))
        task_key = existing_tasks[0].get("key") if existing_tasks else None
        existing_attachments = (
            existing_tasks[0].get("fields", {}).get("attachment", []) if existing_tasks else []
        )
        created_task = not bool(task_key)
        task_description = [
            f"Database Schema and ERD for Epic {epic_key}.",
            f"The complete document is attached as {attachment_name}.",
            "Generated database entities are represented by child subtasks.",
        ]
        fields = {
            "summary": "[ERD] Database Schema & ERD",
            "description": {
                "type": "doc",
                "version": 1,
                "content": [paragraph(line) for line in task_description],
            },
            "labels": ["erd-output-document"],
        }
        if task_key:
            task_response = await client.put(
                f"{JIRA_BASE_URL}/rest/api/3/issue/{task_key}",
                headers=get_jira_headers(),
                json={"fields": fields},
            )
            if task_response.status_code not in (200, 204):
                return json.dumps({
                    "error": f"ERD Task update failed: {task_response.status_code}",
                    "details": task_response.text,
                    "erd_task_key": task_key,
                }, indent=2)
        else:
            task_response = await client.post(
                f"{JIRA_BASE_URL}/rest/api/3/issue",
                headers=get_jira_headers(),
                json={"fields": {
                    "project": {"key": project_key},
                    "parent": {"key": epic_key},
                    "issuetype": {"id": task_type["id"]},
                    **fields,
                }},
            )
            if task_response.status_code not in (200, 201):
                return json.dumps({
                    "error": f"ERD Task creation failed: {task_response.status_code}",
                    "details": task_response.text,
                }, indent=2)
            task_key = task_response.json().get("key")
            if not task_key:
                return json.dumps({"error": "Jira created the ERD Task without returning its key."}, indent=2)

        upload = await client.post(
            f"{JIRA_BASE_URL}/rest/api/3/issue/{task_key}/attachments",
            headers=get_attachment_headers(),
            files={"file": (attachment_name, erd_markdown.encode("utf-8"), "text/markdown")},
        )
        if upload.status_code not in (200, 201):
            return json.dumps({
                "error": f"ERD Task was written, but attachment upload failed: {upload.status_code}",
                "details": upload.text,
                "erd_task_key": task_key,
            }, indent=2)
        uploaded_attachments = upload.json()
        uploaded_attachment_id = (
            str(uploaded_attachments[0].get("id", "")) if uploaded_attachments else ""
        )
        if not uploaded_attachment_id:
            return json.dumps({
                "error": "ERD Markdown uploaded, but Jira did not return its attachment ID; older attachments were kept.",
                "erd_task_key": task_key,
            }, indent=2)
        attachment_cleanup_errors = []
        for existing_attachment in existing_attachments:
            old_id = str(existing_attachment.get("id", ""))
            old_name = str(existing_attachment.get("filename", ""))
            if (
                old_id
                and old_id != uploaded_attachment_id
                and old_name.casefold() == attachment_name.casefold()
            ):
                delete_response = await client.delete(
                    f"{JIRA_BASE_URL}/rest/api/3/attachment/{old_id}",
                    headers=get_jira_headers(),
                )
                if delete_response.status_code != 204:
                    attachment_cleanup_errors.append({
                        "attachment_id": old_id,
                        "filename": old_name,
                        "error": f"Delete failed: {delete_response.status_code} {delete_response.text}",
                    })

        entity_results = []
        for entity in entities:
            output_label = entity_output_label(entity)
            existing_entity_response = await client.get(
                f"{JIRA_BASE_URL}/rest/api/3/search/jql",
                params={
                    "jql": f'parent = "{task_key}" AND labels = "{output_label}"',
                    "maxResults": 100,
                    "fields": "summary",
                },
                headers=get_jira_headers(),
            )
            if existing_entity_response.status_code != 200:
                return json.dumps({
                    "error": (
                        f"Entity task search failed for {entity['table_name']}: "
                        f"{existing_entity_response.status_code}"
                    ),
                    "details": existing_entity_response.text,
                    "erd_task_key": task_key,
                    "entity_tasks": entity_results,
                }, indent=2)
            existing_entities = existing_entity_response.json().get("issues", [])
            existing_entities.sort(key=lambda issue: issue.get("key", ""))
            entity_fields = {
                "summary": f"[ERD] Table: {entity['table_name']}"[:255],
                "description": {
                    "type": "doc",
                    "version": 1,
                    "content": entity_description(entity),
                },
                "labels": ["erd-output-entity", output_label],
            }
            if existing_entities:
                entity_key = existing_entities[0].get("key")
                entity_response = await client.put(
                    f"{JIRA_BASE_URL}/rest/api/3/issue/{entity_key}",
                    headers=get_jira_headers(),
                    json={"fields": entity_fields},
                )
                created = False
            else:
                entity_response = await client.post(
                    f"{JIRA_BASE_URL}/rest/api/3/issue",
                    headers=get_jira_headers(),
                    json={"fields": {
                        "project": {"key": project_key},
                        "parent": {"key": task_key},
                        "issuetype": {"id": subtask_type["id"]},
                        **entity_fields,
                    }},
                )
                entity_key = (
                    entity_response.json().get("key") if entity_response.is_success else None
                )
                created = True
            if not entity_response.is_success:
                return json.dumps({
                    "error": (
                        f"Entity task write failed for {entity['table_name']}: "
                        f"{entity_response.status_code}"
                    ),
                    "details": entity_response.text,
                    "erd_task_key": task_key,
                    "entity_tasks": entity_results,
                }, indent=2)
            entity_results.append({
                "table_name": entity["table_name"],
                "issue_key": entity_key,
                "created": created,
            })

    return json.dumps({
        "epic_issue_key": epic_key,
        "erd_task_key": task_key,
        "erd_task_created": created_task,
        "attachment_name": attachment_name,
        "attachment_cleanup_errors": attachment_cleanup_errors,
        "entity_tasks": entity_results,
    }, indent=2)
