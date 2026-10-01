"""Publish a distinct FRD document and industry-standard stories under a Jira Epic."""

import hashlib
import json
import re

import httpx

from customfun import JIRA_BASE_URL, get_attachment_headers, get_jira_headers

_ISSUE_KEY = re.compile(r"^[A-Z][A-Z0-9]+-\d+$")
_REQUIREMENT_ID = re.compile(r"^FR-\d+$", re.IGNORECASE)
_STORY_ID = re.compile(r"^US-FR-\d+$", re.IGNORECASE)


def _paragraph(text: str) -> dict[str, object]:
    return {
        "type": "paragraph",
        "content": [{"type": "text", "text": text}],
    }


def _label(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]+", "-", value.casefold()).strip("-")[:255]


def _story_description(story: dict[str, object]) -> list[dict[str, object]]:
    source_keys = ", ".join(story["source_issue_keys"])
    content: list[dict[str, object]] = [
        _paragraph(f"Story ID: {story['story_id']}"),
        _paragraph(f"Source requirement: {story['source_requirement_id']}"),
        _paragraph(f"Module: {story['module_id']}"),
        _paragraph(f"BRD input issues: {source_keys}"),
        _paragraph(f"Priority: {story['priority']}"),
        _paragraph("User story (INVEST):"),
        _paragraph(story["user_story"]),
        _paragraph("Acceptance criteria (Given/When/Then scenarios):"),
        {
            "type": "bulletList",
            "content": [
                {"type": "listItem", "content": [_paragraph(criterion)]}
                for criterion in story["acceptance_criteria"]
            ],
        },
    ]
    if story["assumptions"]:
        content.extend([_paragraph("Assumptions:")])
        content.extend(_paragraph(item) for item in story["assumptions"])
    if story["open_questions"]:
        content.append(_paragraph("Open questions:"))
        content.extend(_paragraph(item) for item in story["open_questions"])
    return content


def _validate_stories(
    stories: object,
    input_keys: list[str],
) -> tuple[list[dict[str, object]], list[dict[str, str]]]:
    if not isinstance(stories, list):
        raise ValueError("user_stories_json must contain a JSON array.")

    valid_stories: list[dict[str, object]] = []
    errors: list[dict[str, str]] = []
    seen_requirements: set[str] = set()
    for story in stories:
        if not isinstance(story, dict):
            errors.append({"error": "Story entry must be an object."})
            continue

        requirement_id = str(story.get("source_requirement_id", "")).strip().upper()
        story_id = str(story.get("story_id", "")).strip().upper()
        source_keys = [
            str(key).strip().upper()
            for key in story.get("source_issue_keys", [])
            if isinstance(key, str) and _ISSUE_KEY.fullmatch(key.strip().upper())
        ]
        statement = str(story.get("user_story", "")).strip()
        normalized_statement = statement.casefold()
        criteria = story.get("acceptance_criteria")
        title = str(story.get("title", "")).strip()
        valid = (
            bool(_REQUIREMENT_ID.fullmatch(requirement_id))
            and bool(_STORY_ID.fullmatch(story_id))
            and story_id == f"US-{requirement_id}"
            and requirement_id not in seen_requirements
            and bool(source_keys)
            and all(key in input_keys for key in source_keys)
            and bool(title)
            and normalized_statement.startswith(("as a ", "as an "))
            and ", i want " in normalized_statement
            and ", so that " in normalized_statement
            and isinstance(criteria, list)
            and 3 <= len(criteria) <= 7
            and all(
                all(term in str(criterion).casefold() for term in ("given", "when", "then"))
                for criterion in criteria
            )
        )
        if not valid:
            errors.append({
                "requirement_id": requirement_id,
                "error": "Story failed FRD story validation or references issues outside the BRD input set.",
            })
            continue

        seen_requirements.add(requirement_id)
        valid_stories.append({
            "story_id": story_id,
            "source_requirement_id": requirement_id,
            "source_issue_keys": source_keys,
            "module_id": str(story.get("module_id") or "Uncategorized"),
            "title": title,
            "user_story": statement,
            "priority": str(story.get("priority") or "Unspecified"),
            "acceptance_criteria": [str(item) for item in criteria],
            "assumptions": [str(item) for item in story.get("assumptions", [])],
            "open_questions": [str(item) for item in story.get("open_questions", [])],
        })
    return valid_stories, errors


async def publish_frd_to_jira(
    epic_issue_key: str,
    frd_markdown: str,
    input_issue_keys: list[str],
    user_stories_json: str,
) -> str:
    """Create a distinct FRD Task and create/update separate standard story Tasks."""
    epic_key = epic_issue_key.strip().upper()
    if not _ISSUE_KEY.fullmatch(epic_key):
        raise ValueError("epic_issue_key must be a valid Jira issue key.")
    if not frd_markdown.strip():
        raise ValueError("frd_markdown must not be empty.")
    try:
        stories_payload = json.loads(user_stories_json)
    except json.JSONDecodeError as error:
        raise ValueError("user_stories_json must contain valid JSON.") from error

    input_keys = list(dict.fromkeys(
        key.strip().upper()
        for key in input_issue_keys
        if isinstance(key, str) and _ISSUE_KEY.fullmatch(key.strip().upper())
    ))
    stories, story_errors = _validate_stories(stories_payload, input_keys)
    attachment_hash = hashlib.sha256(frd_markdown.encode("utf-8")).hexdigest()[:10]
    attachment_name = f"FRD_{epic_key}_{attachment_hash}.md"

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
                "error": f"Epic child issue type lookup failed: {metadata_response.status_code}",
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

        frd_search = await client.get(
            f"{JIRA_BASE_URL}/rest/api/3/search/jql",
            params={
                "jql": f'parent = "{epic_key}" AND labels = "frd-output-document"',
                "maxResults": 1,
                "fields": "summary,attachment",
            },
            headers=get_jira_headers(),
        )
        if frd_search.status_code != 200:
            return json.dumps({
                "error": f"FRD output issue search failed: {frd_search.status_code}",
                "details": frd_search.text,
            }, indent=2)
        existing_frd = frd_search.json().get("issues", [])
        frd_task_created = not existing_frd
        frd_task_key = existing_frd[0].get("key") if existing_frd else None

        input_summary = ", ".join(input_keys) if input_keys else "No linked BRD input issues found"
        frd_description_lines = [
            f"Standalone Functional Requirements Document for Business Vision Epic {epic_key}.",
            f"BRD and child-ticket inputs: {input_summary}.",
            f"Full FRD Markdown is attached as {attachment_name}.",
            "FRD-derived user stories are separate output Tasks; none of the BRD input issues are reused as outputs.",
        ]

        if frd_task_created:
            create_frd = await client.post(
                f"{JIRA_BASE_URL}/rest/api/3/issue",
                headers=get_jira_headers(),
                json={"fields": {
                    "project": {"key": project_key},
                    "parent": {"key": epic_key},
                    "issuetype": {"id": task_type["id"]},
                    "summary": "[FRD] Functional Requirements Document",
                    "description": {
                        "type": "doc",
                        "version": 1,
                        "content": [_paragraph(line) for line in frd_description_lines],
                    },
                    "labels": ["frd-output-document"],
                }},
            )
            if create_frd.status_code not in (200, 201):
                return json.dumps({
                    "error": f"FRD output Task creation failed: {create_frd.status_code}",
                    "details": create_frd.text,
                }, indent=2)
            frd_task_key = create_frd.json().get("key")

        story_results: list[dict[str, object]] = []
        for story in stories:
            requirement_id = str(story["source_requirement_id"])
            output_label = _label(f"frd-story-{requirement_id}")
            existing_response = await client.get(
                f"{JIRA_BASE_URL}/rest/api/3/search/jql",
                params={
                    "jql": f'parent = "{epic_key}" AND labels = "{output_label}"',
                    "maxResults": 1,
                    "fields": "summary",
                },
                headers=get_jira_headers(),
            )
            if existing_response.status_code != 200:
                story_errors.append({
                    "requirement_id": requirement_id,
                    "error": f"FRD story lookup failed: {existing_response.status_code}",
                })
                continue

            existing_story = existing_response.json().get("issues", [])
            title = str(story["title"]).strip()
            story_summary = f"[{requirement_id}] User Story: {title}"[:255]
            module_id = str(story["module_id"])
            story_fields = {
                "summary": story_summary,
                "description": {
                    "type": "doc",
                    "version": 1,
                    "content": _story_description(story),
                },
                "labels": ["frd-output-story", output_label, _label(module_id)],
            }
            if existing_story:
                story_issue_key = existing_story[0].get("key")
                write_response = await client.put(
                    f"{JIRA_BASE_URL}/rest/api/3/issue/{story_issue_key}",
                    headers=get_jira_headers(),
                    json={"fields": story_fields},
                )
                created = False
            else:
                write_response = await client.post(
                    f"{JIRA_BASE_URL}/rest/api/3/issue",
                    headers=get_jira_headers(),
                    json={"fields": {
                        "project": {"key": project_key},
                        "parent": {"key": epic_key},
                        "issuetype": {"id": task_type["id"]},
                        **story_fields,
                    }},
                )
                story_issue_key = write_response.json().get("key") if write_response.is_success else None
                created = True
            if write_response.status_code not in (200, 201, 204):
                story_errors.append({
                    "requirement_id": requirement_id,
                    "error": f"FRD story Task write failed: {write_response.status_code} {write_response.text}",
                })
                continue
            story_results.append({
                "source_issue_keys": story["source_issue_keys"],
                "requirement_id": requirement_id,
                "story_id": story["story_id"],
                "story_issue_key": story_issue_key,
                "summary": story_summary,
                "created": created,
                "updated": not created,
            })

        story_keys = [str(item["story_issue_key"]) for item in story_results if item.get("story_issue_key")]
        final_description_lines = [
            *frd_description_lines,
            "Separate FRD-derived User Story Tasks:",
            *([f"- {key}" for key in story_keys] if story_keys else ["No valid user stories were generated."]),
        ]
        update_response = await client.put(
            f"{JIRA_BASE_URL}/rest/api/3/issue/{frd_task_key}",
            headers=get_jira_headers(),
            json={"fields": {
                "description": {
                    "type": "doc",
                    "version": 1,
                    "content": [_paragraph(line) for line in final_description_lines],
                },
            }},
        )
        if update_response.status_code not in (200, 204):
            story_errors.append({
                "error": f"Could not update FRD Task with output story keys: {update_response.status_code}",
            })

        existing_attachments = existing_frd[0].get("fields", {}).get("attachment", []) if existing_frd else []
        attachment_exists = any(item.get("filename") == attachment_name for item in existing_attachments)
        if not attachment_exists:
            upload = await client.post(
                f"{JIRA_BASE_URL}/rest/api/3/issue/{frd_task_key}/attachments",
                headers=get_attachment_headers(),
                files={"file": (attachment_name, frd_markdown.encode("utf-8"), "text/markdown")},
            )
            if upload.status_code not in (200, 201):
                return json.dumps({
                    "error": f"FRD Task was written, but attachment upload failed: {upload.status_code}",
                    "details": upload.text,
                    "frd_task_key": frd_task_key,
                    "story_tasks": story_results,
                    "story_errors": story_errors,
                }, indent=2)

    return json.dumps({
        "epic_issue_key": epic_key,
        "input_issue_keys": input_keys,
        "frd_task_key": frd_task_key,
        "frd_task_created": frd_task_created,
        "frd_attachment": attachment_name,
        "attachment_uploaded": not attachment_exists,
        "story_tasks": story_results,
        "story_errors": story_errors,
        "outputs_are_distinct_from_brd_inputs": True,
    }, indent=2)
