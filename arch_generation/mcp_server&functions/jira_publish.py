"""Publish an Architecture document and its component sub-tasks under a Jira Epic."""

import json
import re

import httpx

from customfun import JIRA_BASE_URL, get_attachment_headers, get_jira_headers

_ISSUE_KEY = re.compile(r"^[A-Z][A-Z0-9]+-\d+$")
_COMPONENT_ID = re.compile(r"^COMP-[A-Z0-9]+-\d+$", re.IGNORECASE)


def _paragraph(text: str) -> dict[str, object]:
    return {
        "type": "paragraph",
        "content": [{"type": "text", "text": text}],
    }


def _label(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]+", "-", value.casefold()).strip("-")[:255]


def _component_output_label(component: dict[str, object]) -> str:
    requirement_ids = sorted(str(item).casefold() for item in component.get("source_requirement_ids", []))
    story_ids = sorted(str(item).casefold() for item in component.get("source_story_ids", []))
    identity = "-".join([str(component["module_id"]).casefold(), *requirement_ids, *story_ids])
    return _label(f"arch-comp-{identity}")


def _component_description(comp: dict[str, object]) -> list[dict[str, object]]:
    fr_keys = ", ".join(comp.get("source_requirement_ids", []))
    story_keys = ", ".join(comp.get("source_story_ids", []))
    tech = ", ".join(comp.get("tech_stack", []))
    entities = ", ".join(comp.get("data_entities_handled", []))
    deps = ", ".join(comp.get("dependencies", [])) or "None"

    return [
        _paragraph(f"Component ID: {comp['component_id']}"),
        _paragraph(f"Type: {comp['component_type']}"),
        _paragraph(f"Module: {comp['module_id']}"),
        _paragraph(f"Tech Stack: {tech}"),
        _paragraph(f"Dependencies: {deps}"),
        _paragraph(f"Managed Data Entities (ERD Precursors): {entities}"),
        _paragraph(f"Traceable FR IDs: {fr_keys}"),
        _paragraph(f"Traceable User Stories: {story_keys}"),
        _paragraph("Core Responsibilities:"),
        {
            "type": "bulletList",
            "content": [
                {"type": "listItem", "content": [_paragraph(str(item))]}
                for item in comp.get("responsibilities", [])
            ],
        },
    ]


async def publish_arch_to_jira(
    epic_issue_key: str,
    arch_markdown: str,
    input_issue_keys: list[str],
    components_json: str,
    integration_contracts_json: str = "[]",
) -> str:
    """Create an Architecture Task and discrete component sub-tasks beneath it."""
    epic_key = epic_issue_key.strip().upper()
    if not _ISSUE_KEY.fullmatch(epic_key):
        raise ValueError("epic_issue_key must be a valid Jira issue key.")
    if not arch_markdown.strip():
        raise ValueError("arch_markdown must not be empty.")

    try:
        components_payload = json.loads(components_json)
    except json.JSONDecodeError as error:
        raise ValueError("components_json must contain valid JSON.") from error

    attachment_name = f"ARCH_{epic_key}.md"

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

        metadata_response = await client.get(
            f"{JIRA_BASE_URL}/rest/api/3/issue/createmeta/{project_key}/issuetypes",
            headers=get_jira_headers(),
        )
        if metadata_response.status_code != 200:
            return json.dumps({
                "error": f"Issue metadata lookup failed: {metadata_response.status_code}",
                "details": metadata_response.text,
            }, indent=2)

        task_type = next(
            (
                issue_type for issue_type in metadata_response.json().get("issueTypes", [])
                if issue_type.get("name", "").casefold() == "task" and not issue_type.get("subtask")
            ),
            None,
        )
        if not task_type:
            return json.dumps({
                "error": f"Project {project_key} has no Task issue type for an Epic child."
            }, indent=2)
        subtask_type = next(
            (
                issue_type for issue_type in metadata_response.json().get("issueTypes", [])
                if issue_type.get("subtask")
            ),
            None,
        )
        if not subtask_type:
            return json.dumps({
                "error": f"Project {project_key} has no sub-task issue type for architecture components."
            }, indent=2)

        # 1. Look up existing Architecture Document task
        arch_search = await client.get(
            f"{JIRA_BASE_URL}/rest/api/3/search/jql",
            params={
                "jql": f'parent = "{epic_key}" AND labels = "arch-output-document"',
                "maxResults": 100,
                "fields": "summary,attachment",
            },
            headers=get_jira_headers(),
        )
        if arch_search.status_code != 200:
            return json.dumps({
                "error": f"Architecture issue search failed: {arch_search.status_code}",
                "details": arch_search.text,
            }, indent=2)

        existing_arch = arch_search.json().get("issues", [])
        existing_arch.sort(key=lambda issue: issue.get("key", ""))
        duplicate_arch_task_keys = [issue.get("key") for issue in existing_arch[1:] if issue.get("key")]
        arch_task_created = not existing_arch
        arch_task_key = existing_arch[0].get("key") if existing_arch else None

        arch_description_lines = [
            f"System Architecture & Component Design Specification for Epic {epic_key}.",
            f"Traceable FRD Inputs: {', '.join(input_issue_keys) if input_issue_keys else 'None'}.",
            f"Full Architecture Document is attached as {attachment_name}.",
            "Discrete Architecture Components are generated as sub-tasks of this Architecture Task for downstream ERD modeling.",
        ]

        if arch_task_created:
            create_arch = await client.post(
                f"{JIRA_BASE_URL}/rest/api/3/issue",
                headers=get_jira_headers(),
                json={"fields": {
                    "project": {"key": project_key},
                    "parent": {"key": epic_key},
                    "issuetype": {"id": task_type["id"]},
                    "summary": "[ARCH] System Architecture & Component Design",
                    "description": {
                        "type": "doc",
                        "version": 1,
                        "content": [_paragraph(line) for line in arch_description_lines],
                    },
                    "labels": ["arch-output-document"],
                }},
            )
            if create_arch.status_code not in (200, 201):
                return json.dumps({
                    "error": f"Architecture Task creation failed: {create_arch.status_code}",
                    "details": create_arch.text,
                }, indent=2)
            arch_task_key = create_arch.json().get("key")

        # 2. Create or Update Component Subtasks
        component_results = []
        legacy_component_keys: list[str] = []
        duplicate_component_keys: list[str] = []
        for comp in components_payload:
            comp_id = str(comp.get("component_id", "")).strip().upper()
            if not _COMPONENT_ID.fullmatch(comp_id):
                continue

            output_label = _component_output_label(comp)
            existing_response = await client.get(
                f"{JIRA_BASE_URL}/rest/api/3/search/jql",
                params={
                    "jql": f'parent = "{arch_task_key}" AND labels = "{output_label}"',
                    "maxResults": 100,
                    "fields": "summary",
                },
                headers=get_jira_headers(),
            )
            if existing_response.status_code != 200:
                return json.dumps({
                    "error": f"Component lookup failed for {comp_id}: {existing_response.status_code}",
                    "details": existing_response.text,
                    "arch_task_key": arch_task_key,
                    "component_tasks": component_results,
                }, indent=2)
            existing_comp_task = existing_response.json().get("issues", [])
            existing_comp_task.sort(key=lambda issue: issue.get("key", ""))
            legacy_parent = False
            comp_name = str(comp.get("name", "")).strip()
            if not existing_comp_task:
                module_label = _label(str(comp.get("module_id", "Core")))
                legacy_response = await client.get(
                    f"{JIRA_BASE_URL}/rest/api/3/search/jql",
                    params={
                        "jql": (
                            f'parent = "{epic_key}" AND labels = "arch-output-component" '
                            f'AND labels = "{module_label}" ORDER BY key'
                        ),
                        "maxResults": 100,
                        "fields": "summary,issuetype,parent,labels",
                    },
                    headers=get_jira_headers(),
                )
                if legacy_response.status_code != 200:
                    return json.dumps({
                        "error": f"Legacy component lookup failed for {comp_id}: {legacy_response.status_code}",
                        "details": legacy_response.text,
                        "arch_task_key": arch_task_key,
                        "component_tasks": component_results,
                    }, indent=2)
                matching_legacy = [
                    issue for issue in legacy_response.json().get("issues", [])
                    if str(issue.get("fields", {}).get("summary", "")).split("] Component: ", 1)[-1].strip().casefold()
                    == comp_name.casefold()
                ]
                matching_legacy.sort(key=lambda issue: issue.get("key", ""))
                existing_comp_task = matching_legacy
                legacy_parent = bool(existing_comp_task)

            if len(existing_comp_task) > 1:
                duplicate_component_keys.extend(
                    str(issue["key"]) for issue in existing_comp_task[1:] if issue.get("key")
                )
            existing_comp_task = existing_comp_task[:1]
            comp_summary = f"[{comp_id}] Component: {comp_name}"[:255]
            module_id = str(comp.get("module_id", "Core"))

            comp_fields = {
                "summary": comp_summary,
                "description": {
                    "type": "doc",
                    "version": 1,
                    "content": _component_description(comp),
                },
                "labels": ["arch-output-component", output_label, _label(module_id)],
            }

            if existing_comp_task:
                comp_task_key = existing_comp_task[0].get("key")
                write_resp = await client.put(
                    f"{JIRA_BASE_URL}/rest/api/3/issue/{comp_task_key}",
                    headers=get_jira_headers(),
                    json={"fields": comp_fields},
                )
                created = False
            else:
                write_resp = await client.post(
                    f"{JIRA_BASE_URL}/rest/api/3/issue",
                    headers=get_jira_headers(),
                    json={"fields": {
                        "project": {"key": project_key},
                        "parent": {"key": arch_task_key},
                        "issuetype": {"id": subtask_type["id"]},
                        **comp_fields,
                    }},
                )
                comp_task_key = write_resp.json().get("key") if write_resp.is_success else None
                created = True

            component_results.append({
                "component_id": comp_id,
                "component_task_key": comp_task_key,
                "summary": comp_summary,
                "created": created,
                "status": "success" if write_resp.is_success else f"failed: {write_resp.status_code}",
                "parent_issue_key": epic_key if legacy_parent else arch_task_key,
                "hierarchy": "legacy-epic-child" if legacy_parent else "architecture-subtask",
            })
            if legacy_parent and comp_task_key:
                legacy_component_keys.append(str(comp_task_key))

        component_children_response = await client.get(
            f"{JIRA_BASE_URL}/rest/api/3/search/jql",
            params={
                "jql": f'parent = "{arch_task_key}" AND labels in ("arch-output-component", "superseded-output") ORDER BY key',
                "maxResults": 100,
                "fields": "labels",
            },
            headers=get_jira_headers(),
        )
        if component_children_response.status_code != 200:
            return json.dumps({
                "error": f"Architecture child lookup failed: {component_children_response.status_code}",
                "details": component_children_response.text,
                "arch_task_key": arch_task_key,
                "component_tasks": component_results,
            }, indent=2)
        child_issues = component_children_response.json().get("issues", [])
        active_component_keys = [
            str(issue["key"])
            for issue in child_issues
            if issue.get("key")
            and "arch-output-component" in issue.get("fields", {}).get("labels", [])
            and "superseded-output" not in issue.get("fields", {}).get("labels", [])
        ]
        superseded_component_keys = [
            str(issue["key"])
            for issue in child_issues
            if issue.get("key") and "superseded-output" in issue.get("fields", {}).get("labels", [])
        ]
        final_description_lines = [
            f"System Architecture & Component Design Specification for Epic {epic_key}.",
            f"Traceable FRD Inputs: {', '.join(input_issue_keys) if input_issue_keys else 'None'}.",
            f"Full Architecture Document is attached as {attachment_name}.",
            "Current architecture components are sub-tasks of this document:",
            *([f"- {key}" for key in active_component_keys] if active_component_keys else ["None found."]),
        ]
        if superseded_component_keys:
            final_description_lines.extend([
                "Superseded generated components retained for history:",
                *[f"- {key}" for key in superseded_component_keys],
            ])
        update_arch = await client.put(
            f"{JIRA_BASE_URL}/rest/api/3/issue/{arch_task_key}",
            headers=get_jira_headers(),
            json={"fields": {
                "description": {
                    "type": "doc",
                    "version": 1,
                    "content": [_paragraph(line) for line in final_description_lines],
                },
            }},
        )
        if update_arch.status_code not in (200, 204):
            return json.dumps({
                "error": f"Architecture Task description update failed: {update_arch.status_code}",
                "details": update_arch.text,
                "arch_task_key": arch_task_key,
                "component_tasks": component_results,
            }, indent=2)

        # Replace the prior generated architecture file only after the new upload succeeds.
        existing_attachments = existing_arch[0].get("fields", {}).get("attachment", []) if existing_arch else []
        upload = await client.post(
            f"{JIRA_BASE_URL}/rest/api/3/issue/{arch_task_key}/attachments",
            headers=get_attachment_headers(),
            files={"file": (attachment_name, arch_markdown.encode("utf-8"), "text/markdown")},
        )
        if upload.status_code not in (200, 201):
            return json.dumps({
                "error": f"Architecture Task was written, but attachment upload failed: {upload.status_code}",
                "details": upload.text,
                "arch_task_key": arch_task_key,
                "component_tasks": component_results,
            }, indent=2)
        uploaded_attachments = upload.json()
        uploaded_attachment_id = str(uploaded_attachments[0].get("id", "")) if uploaded_attachments else ""
        if not uploaded_attachment_id:
            return json.dumps({
                "error": "Architecture document uploaded, but Jira did not return its attachment ID; older attachments were kept.",
                "arch_task_key": arch_task_key,
                "component_tasks": component_results,
            }, indent=2)

        attachment_cleanup_errors: list[dict[str, str]] = []
        for existing_attachment in existing_attachments:
            old_filename = str(existing_attachment.get("filename", ""))
            old_id = str(existing_attachment.get("id", ""))
            if (
                old_id
                and old_id != uploaded_attachment_id
                and (
                    old_filename.casefold() == attachment_name.casefold()
                    or (
                        old_filename.casefold().startswith(f"arch_{epic_key}_".casefold())
                        and old_filename.casefold().endswith(".md")
                    )
                )
            ):
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

    return json.dumps({
        "epic_issue_key": epic_key,
        "arch_task_key": arch_task_key,
        "arch_attachment": attachment_name,
        "attachment_uploaded": True,
        "attachment_cleanup_errors": attachment_cleanup_errors,
        "component_tasks": component_results,
        "legacy_component_tasks": legacy_component_keys,
        "duplicate_component_tasks": duplicate_component_keys,
        "duplicate_architecture_document_tasks": duplicate_arch_task_keys,
        "superseded_component_tasks": superseded_component_keys,
    }, indent=2)
