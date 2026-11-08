"""Generate a traceable Functional Requirements Document from supplied Jira context."""

import asyncio
import json
import os
import re
from collections.abc import Mapping
from typing import Any, Literal

from dotenv import load_dotenv
from google import genai
from google.genai import types
from openai import AsyncOpenAI
from pydantic import BaseModel, Field, field_validator, model_validator

from frd_generation.prompts import FRD_SYSTEM_PROMPT, build_frd_user_prompt

load_dotenv()

GEMINI_MODEL_NAME = os.getenv("GEMINI_MODEL_NAME", "gemini-3.1-flash-lite")
LOCAL_LLM_URL = os.getenv("LOCAL_LLM_URL", "http://127.0.0.1:8080/v1")
LOCAL_MODEL_NAME = os.getenv("LOCAL_MODEL_NAME", "qwen3-4b-thinking-2507.Q4_K_M.gguf")


class FRDUserStory(BaseModel):
    story_id: str = Field(pattern=r"^US-FR-\d+$")
    source_requirement_id: str = Field(pattern=r"^FR-\d+$")
    module_id: str = Field(min_length=1)
    source_issue_keys: list[str] = Field(min_length=1)
    title: str = Field(min_length=1, max_length=120)
    user_story: str = Field(min_length=1)
    priority: str = Field(min_length=1)
    acceptance_criteria: list[str] = Field(min_length=3, max_length=7)
    assumptions: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)

    @field_validator("user_story")
    @classmethod
    def validate_story_statement(cls, value: str) -> str:
        normalized = value.casefold()
        if not normalized.startswith(("as a ", "as an ")) or ", i want " not in normalized or ", so that " not in normalized:
            raise ValueError("user_story must use 'As a/an..., I want..., so that...' format.")
        return value

    @field_validator("acceptance_criteria")
    @classmethod
    def validate_gherkin_criteria(cls, criteria: list[str]) -> list[str]:
        for criterion in criteria:
            normalized = criterion.casefold()
            if not all(keyword in normalized for keyword in ("given", "when", "then")):
                raise ValueError("Each acceptance criterion must contain Given, When, and Then.")
        return criteria


class FRDGeneration(BaseModel):
    frd_markdown: str = Field(min_length=1)
    user_stories: list[FRDUserStory] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_story_inventory(self) -> "FRDGeneration":
        required_sections = (
            "Purpose, Source Documents, and Scope",
            "System Context and Boundaries",
            "Actors and Use-Case Index",
            "Detailed Use Cases",
            "Functional Behavior and Workflows",
            "Data Entities and Data Dictionary",
            "Interfaces and Integrations",
            "System Constraints and Non-Functional Requirements",
            "Traceability Matrix",
            "Assumptions, Open Questions, and Decisions",
        )
        for section in required_sections:
            if not re.search(
                rf"^#+\s+\d+\.\s+{re.escape(section)}\s*$",
                self.frd_markdown,
                flags=re.IGNORECASE | re.MULTILINE,
            ):
                raise ValueError(f"frd_markdown is missing section '{section}'.")
        requirement_ids = [story.source_requirement_id for story in self.user_stories]
        if len(requirement_ids) != len(set(requirement_ids)):
            raise ValueError("user_stories must contain only one story per source requirement.")
        for story in self.user_stories:
            if story.story_id != f"US-{story.source_requirement_id}":
                raise ValueError(
                    f"{story.story_id} must match its source requirement "
                    f"{story.source_requirement_id}."
                )
        return self


def _brd_requirement_ids(jira_context: BaseModel | Mapping[str, Any]) -> list[str]:
    """Extract the canonical FR IDs from the attached BRD requirement table."""
    payload = (
        jira_context.model_dump(mode="json")
        if isinstance(jira_context, BaseModel)
        else jira_context
    )
    attachment = payload.get("brd_attachment", {})
    markdown = attachment.get("markdown") if isinstance(attachment, Mapping) else None
    if not isinstance(markdown, str):
        return []

    section = re.search(
        r"^#+\s+4\.\s+Functional Requirements\s*$([\s\S]*?)(?=^#+\s|\Z)",
        markdown,
        flags=re.IGNORECASE | re.MULTILINE,
    )
    if not section:
        raise ValueError("The attached BRD is missing its Functional Requirements section.")

    rows = [
        [cell.strip() for cell in line.strip().strip("|").split("|")]
        for line in section.group(1).splitlines()
        if line.strip().startswith("|") and line.strip().endswith("|")
    ]
    requirement_ids = []
    for row in rows[2:]:
        if row:
            match = re.fullmatch(r"(FR-\d+)", row[0], flags=re.IGNORECASE)
            if match:
                requirement_ids.append(match.group(1).upper())
    if not requirement_ids:
        raise ValueError("The attached BRD has no parseable functional requirement IDs.")

    canonical_ids = [f"FR-{int(item.split('-', maxsplit=1)[1])}" for item in requirement_ids]
    if len(canonical_ids) != len(set(canonical_ids)):
        raise ValueError("The attached BRD contains duplicate numeric FR IDs.")
    return requirement_ids


def _synchronize_frd_requirement_ids(
    response_data: Mapping[str, Any],
    jira_context: BaseModel | Mapping[str, Any],
) -> dict[str, Any]:
    """Align story and Markdown IDs to the exact IDs in the canonical BRD."""
    payload = dict(response_data)
    requirement_ids = _brd_requirement_ids(jira_context)
    if not requirement_ids:
        return payload

    ids_by_number = {
        int(requirement_id.split("-", maxsplit=1)[1]): requirement_id
        for requirement_id in requirement_ids
    }
    stories = payload.get("user_stories")
    if not isinstance(stories, list):
        raise ValueError("FRD response must contain a user_stories array.")
    stories = [dict(story) for story in stories if isinstance(story, Mapping)]
    if len(stories) != len(payload["user_stories"]):
        raise ValueError("Every FRD user story must be an object.")
    payload["user_stories"] = stories
    seen: set[str] = set()
    for story in stories:
        source_id = str(story.get("source_requirement_id", "")).strip().upper()
        match = re.fullmatch(r"FR-(\d+)", source_id)
        if not match or int(match.group(1)) not in ids_by_number:
            raise ValueError(
                f"FRD story references {source_id or 'an invalid requirement'}, "
                "which is not in the attached BRD."
            )
        canonical_id = ids_by_number[int(match.group(1))]
        if canonical_id in seen:
            raise ValueError(f"FRD contains multiple stories for {canonical_id}.")
        story["source_requirement_id"] = canonical_id
        story["story_id"] = f"US-{canonical_id}"
        seen.add(canonical_id)
    if seen != set(requirement_ids):
        missing = sorted(set(requirement_ids) - seen)
        raise ValueError(f"FRD must contain exactly one story per BRD requirement; missing {missing}.")

    def canonicalize_reference(match: re.Match[str]) -> str:
        prefix, number = match.groups()
        requirement_id = ids_by_number.get(int(number))
        return f"{prefix or ''}{requirement_id or f'FR-{number}'}"

    markdown = payload.get("frd_markdown")
    if not isinstance(markdown, str):
        raise ValueError("FRD response must contain frd_markdown text.")
    markdown = _normalize_frd_section_headings(markdown)
    payload["frd_markdown"] = re.sub(
        r"(?<![A-Z0-9_-])(US-)?FR-(\d+)(?!\d)",
        canonicalize_reference,
        markdown,
        flags=re.IGNORECASE,
    )
    payload["frd_markdown"] = _synchronize_frd_traceability(
        payload["frd_markdown"], stories
    )
    return payload


def _normalize_frd_section_headings(markdown: str) -> str:
    """Enforce the canonical ten section titles while preserving generated content."""
    titles = (
        "Purpose, Source Documents, and Scope",
        "System Context and Boundaries",
        "Actors and Use-Case Index",
        "Detailed Use Cases",
        "Functional Behavior and Workflows",
        "Data Entities and Data Dictionary",
        "Interfaces and Integrations",
        "System Constraints and Non-Functional Requirements",
        "Traceability Matrix",
        "Assumptions, Open Questions, and Decisions",
    )
    heading_pattern = re.compile(r"^(#{1,6}\s+)(\d+)\.\s+(.+?)\s*$", re.MULTILINE)
    found: dict[int, str] = {}
    for match in heading_pattern.finditer(markdown):
        number = int(match.group(2))
        if 1 <= number <= len(titles):
            if number in found:
                raise ValueError(f"FRD Markdown repeats numbered section {number}.")
            found[number] = match.group(3)
    missing = sorted(set(range(1, len(titles) + 1)) - set(found))
    if missing:
        raise ValueError(f"FRD Markdown is missing numbered sections: {missing}.")
    return heading_pattern.sub(
        lambda match: (
            f"{match.group(1)}{match.group(2)}. "
            f"{titles[int(match.group(2)) - 1]}"
            if 1 <= int(match.group(2)) <= len(titles)
            else match.group(0)
        ),
        markdown,
    )


def _synchronize_frd_traceability(
    markdown: str, stories: list[dict[str, Any]]
) -> str:
    """Render the FRD traceability matrix from the validated story inventory."""
    section = re.search(
        r"^(#+\s+.*Traceability Matrix.*$)([\s\S]*?)(?=^#+\s|\Z)",
        markdown,
        flags=re.IGNORECASE | re.MULTILINE,
    )
    if not section:
        raise ValueError("FRD Markdown is missing its Traceability Matrix section.")
    rows = [
        "",
        "| FR ID | Story ID | Source Jira Issue Keys |",
        "|---|---|---|",
    ]
    for story in stories:
        rows.append(
            "| {requirement_id} | {story_id} | {source_keys} |".format(
                requirement_id=story["source_requirement_id"],
                story_id=story["story_id"],
                source_keys=", ".join(story["source_issue_keys"]),
            )
        )
    body = "\n".join(rows) + "\n\n"
    return markdown[:section.start(2)] + body + markdown[section.end(2):]


def serialize_brd_data(jira_context: BaseModel | Mapping[str, Any]) -> str:
    """Serialize Pydantic or mapping-based Jira/BRD context for the generation prompt."""
    if isinstance(jira_context, BaseModel):
        payload = jira_context.model_dump(mode="json")
    elif isinstance(jira_context, Mapping):
        payload = dict(jira_context)
    else:
        raise TypeError("jira_context must be a Pydantic model or a mapping.")

    if not payload:
        raise ValueError("jira_context must contain Jira or BRD data.")

    try:
        return json.dumps(payload, indent=2, ensure_ascii=False)
    except (TypeError, ValueError) as error:
        raise ValueError("jira_context must contain JSON-serializable data.") from error


async def generate_frd_package(
    jira_context: BaseModel | Mapping[str, Any],
    provider: Literal["gemini", "local"] = "gemini",
    model_name: str | None = None,
) -> FRDGeneration:
    """Generate FRD Markdown plus validated industry-standard stories.

    The provider defaults to Gemini and can be set to ``local`` for an
    OpenAI-compatible model server configured by ``LOCAL_LLM_URL``.
    """
    context_json = serialize_brd_data(jira_context)
    user_prompt = build_frd_user_prompt(context_json)

    if provider == "gemini":
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("GEMINI_API_KEY not found in environment.")
        client = genai.Client(api_key=api_key)
        response = await asyncio.to_thread(
            client.models.generate_content,
            model=model_name or GEMINI_MODEL_NAME,
            contents=user_prompt,
            config=types.GenerateContentConfig(
                system_instruction=FRD_SYSTEM_PROMPT,
                temperature=0.15,
                response_mime_type="application/json",
                response_schema=FRDGeneration,
            ),
        )
        response_data = response.parsed
        if response_data is None:
            response_data = json.loads(response.text or "")
    elif provider == "local":
        client = AsyncOpenAI(base_url=LOCAL_LLM_URL, api_key="not-needed")
        response = await client.chat.completions.create(
            model=model_name or LOCAL_MODEL_NAME,
            messages=[
                {"role": "system", "content": FRD_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.15,
            response_format={"type": "json_object"},
        )
        response_data = json.loads(response.choices[0].message.content or "")
    else:
        raise ValueError(f"Unsupported FRD provider: {provider}")

    if isinstance(response_data, BaseModel):
        response_data = response_data.model_dump(mode="json")
    if isinstance(response_data, Mapping):
        response_data = _synchronize_frd_requirement_ids(response_data, jira_context)
    return FRDGeneration.model_validate(response_data)


async def generate_frd(
    jira_context: BaseModel | Mapping[str, Any],
    provider: Literal["gemini", "local"] = "gemini",
    model_name: str | None = None,
) -> str:
    """Generate FRD Markdown only, retaining the simple return-value API."""
    result = await generate_frd_package(jira_context, provider, model_name)
    return result.frd_markdown.strip()
