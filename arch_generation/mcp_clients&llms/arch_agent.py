"""Generate a traceable System Architecture Document and component specifications from Jira FRD context."""

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

from arch_generation.prompts import ARCH_SYSTEM_PROMPT, build_arch_user_prompt

load_dotenv()

GEMINI_MODEL_NAME = os.getenv("GEMINI_MODEL_NAME", "gemini-3.1-flash-lite")
LOCAL_LLM_URL = os.getenv("LOCAL_LLM_URL", "http://127.0.0.1:8080/v1")
LOCAL_MODEL_NAME = os.getenv("LOCAL_MODEL_NAME", "qwen3-4b-thinking-2507.Q4_K_M.gguf")


class ArchComponent(BaseModel):
    component_id: str = Field(pattern=r"^COMP-[A-Z0-9-]+-\d+$")
    name: str = Field(min_length=2, max_length=100)
    component_type: Literal[
        "Frontend Application",
        "API Gateway / BFF",
        "Backend Service",
        "Database / Datastore",
        "Message Broker / Queue",
        "Background Worker / Job",
        "External Integration Service",
    ]
    module_id: str = Field(pattern=r"^MOD-[A-Z0-9]+(?:-[A-Z0-9]+)*$")
    source_requirement_ids: list[str] = Field(min_length=1)
    source_story_ids: list[str] = Field(min_length=1)
    tech_stack: list[str] = Field(min_length=1)
    responsibilities: list[str] = Field(min_length=2, max_length=8)
    dependencies: list[str] = Field(default_factory=list)
    data_entities_handled: list[str] = Field(
        default_factory=list,
        description="Entities managed by this component, supplying the entity inventory for Step 4 ERD generation.",
    )

    @field_validator("source_requirement_ids")
    @classmethod
    def validate_fr_ids(cls, ids: list[str]) -> list[str]:
        for req_id in ids:
            if not re.fullmatch(r"FR-\d+", req_id.upper()):
                raise ValueError(f"Requirement ID '{req_id}' must follow FR-<n> pattern.")
        return ids

    @field_validator("source_story_ids")
    @classmethod
    def validate_story_ids(cls, ids: list[str]) -> list[str]:
        for story_id in ids:
            if not re.fullmatch(r"US-FR-\d+", story_id.upper()):
                raise ValueError(f"Story ID '{story_id}' must follow US-FR-<n> pattern.")
        return ids


class IntegrationContract(BaseModel):
    source_component_id: str = Field(pattern=r"^COMP-[A-Z0-9-]+-\d+$")
    target_component_id: str = Field(pattern=r"^COMP-[A-Z0-9-]+-\d+$")
    protocol: Literal["REST", "GraphQL", "gRPC", "WebSocket", "Kafka", "RabbitMQ", "SQS/SNS", "Database Client"]
    interaction_type: Literal["Synchronous Request-Response", "Asynchronous Event", "Publish-Subscribe", "Batch Extraction"]
    data_format: str = Field(default="JSON")
    contract_summary: str = Field(min_length=5)


class SystemArchitectureGeneration(BaseModel):
    arch_markdown: str = Field(min_length=100)
    architecture_pattern: str = Field(min_length=3)
    rationale: str = Field(min_length=20)
    components: list[ArchComponent] = Field(min_length=1)
    integration_contracts: list[IntegrationContract] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_component_references(self) -> "SystemArchitectureGeneration":
        component_ids = [component.component_id for component in self.components]
        if len(component_ids) != len(set(component_ids)):
            raise ValueError("components must have unique component IDs.")
        known_ids = set(component_ids)
        for component in self.components:
            missing = set(component.dependencies) - known_ids
            if missing:
                raise ValueError(
                    f"{component.component_id} references unknown dependencies: {sorted(missing)}."
                )
            expected_stories = {
                f"US-{requirement_id}"
                for requirement_id in component.source_requirement_ids
            }
            if set(component.source_story_ids) != expected_stories:
                raise ValueError(
                    f"{component.component_id} story IDs must match its source FR IDs."
                )
        entity_owners: dict[str, str] = {}
        for component in self.components:
            for entity in component.data_entities_handled:
                entity_key = entity.strip().casefold()
                owner = entity_owners.get(entity_key)
                if owner is not None and owner != component.component_id:
                    raise ValueError(
                        f"Managed data entity '{entity}' has multiple owners: "
                        f"{owner} and {component.component_id}."
                    )
                entity_owners[entity_key] = component.component_id
        for contract in self.integration_contracts:
            if (
                contract.source_component_id not in known_ids
                or contract.target_component_id not in known_ids
            ):
                raise ValueError("Integration contracts must reference declared components.")
            if contract.source_component_id == contract.target_component_id:
                raise ValueError("Integration contracts must connect distinct components.")
        return self


def _canonicalize_architecture_output(response_data: Mapping[str, Any]) -> dict[str, Any]:
    """Assign stable module-scoped component IDs and render the canonical trace matrix."""
    payload = dict(response_data)
    raw_components = payload.get("components")
    if not isinstance(raw_components, list) or not raw_components:
        raise ValueError("Architecture response must contain a non-empty components array.")

    components = [dict(component) for component in raw_components]
    for component in components:
        if str(component.get("component_type", "")).casefold() == "external integration service":
            component["data_entities_handled"] = []
    original_ids = [str(component.get("component_id", "")).strip().upper() for component in components]
    if len(original_ids) != len(set(original_ids)):
        raise ValueError("Architecture response contains duplicate component IDs.")
    ordered = sorted(
        range(len(components)),
        key=lambda index: (
            str(components[index].get("module_id", "")).upper(),
            str(components[index].get("component_type", "")).casefold()
            == "external integration service",
            str(components[index].get("name", "")).casefold(),
        ),
    )
    canonical_ids: dict[str, str] = {}
    counters: dict[str, int] = {}
    for index in ordered:
        module_id = str(components[index].get("module_id", "")).strip().upper()
        token = module_id.removeprefix("MOD-")
        if not re.fullmatch(r"[A-Z0-9]+(?:-[A-Z0-9]+)*", token):
            raise ValueError(f"Invalid module ID for architecture component: {module_id}.")
        counters[token] = counters.get(token, 0) + 1
        canonical_ids[original_ids[index]] = f"COMP-{token}-{counters[token]}"

    for component in components:
        original_id = str(component.get("component_id", "")).strip().upper()
        component["component_id"] = canonical_ids[original_id]
        component["dependencies"] = [
            canonical_ids.get(str(dependency).strip().upper(), str(dependency).strip().upper())
            for dependency in component.get("dependencies", [])
        ]
    payload["components"] = components

    contracts = payload.get("integration_contracts")
    if not isinstance(contracts, list):
        raise ValueError("Architecture response must contain integration_contracts.")
    payload["integration_contracts"] = [
        {
            **dict(contract),
            "source_component_id": canonical_ids.get(
                str(contract.get("source_component_id", "")).strip().upper(),
                str(contract.get("source_component_id", "")).strip().upper(),
            ),
            "target_component_id": canonical_ids.get(
                str(contract.get("target_component_id", "")).strip().upper(),
                str(contract.get("target_component_id", "")).strip().upper(),
            ),
        }
        for contract in contracts
    ]

    markdown = payload.get("arch_markdown")
    if not isinstance(markdown, str):
        raise ValueError("Architecture response must contain arch_markdown text.")
    for original_id in sorted(canonical_ids, key=len, reverse=True):
        markdown = re.sub(
            rf"(?<![A-Z0-9-]){re.escape(original_id)}(?![A-Z0-9-])",
            canonical_ids[original_id],
            markdown,
            flags=re.IGNORECASE,
        )
    payload["arch_markdown"] = _synchronize_arch_traceability(markdown, components)
    return payload


def _synchronize_arch_traceability(
    markdown: str, components: list[dict[str, Any]]
) -> str:
    """Render the architecture traceability matrix from validated component data."""
    match = re.search(
        r"^(#+\s+.*Traceability Matrix.*$)([\s\S]*?)(?=^#+\s|\Z)",
        markdown,
        flags=re.IGNORECASE | re.MULTILINE,
    )
    if not match:
        raise ValueError("Architecture Markdown is missing its Traceability Matrix section.")
    rows = [
        "",
        "| Component ID | Module ID | FR IDs | Story IDs | Managed Entities |",
        "|---|---|---|---|---|",
    ]
    for component in components:
        rows.append(
            "| {component_id} | {module_id} | {fr_ids} | {story_ids} | {entities} |".format(
                component_id=component["component_id"],
                module_id=component["module_id"],
                fr_ids=", ".join(component["source_requirement_ids"]),
                story_ids=", ".join(component["source_story_ids"]),
                entities=", ".join(component["data_entities_handled"]),
            )
        )
    body = "\n".join(rows) + "\n\n"
    return markdown[:match.start(2)] + body + markdown[match.end(2):]

def serialize_frd_data(jira_context: BaseModel | Mapping[str, Any]) -> str:
    """Serialize Pydantic or mapping-based Jira/FRD context for the generation prompt."""
    if isinstance(jira_context, BaseModel):
        payload = jira_context.model_dump(mode="json")
    elif isinstance(jira_context, Mapping):
        payload = dict(jira_context)
    else:
        raise TypeError("jira_context must be a Pydantic model or a mapping.")

    if not payload:
        raise ValueError("jira_context must contain Jira or FRD data.")

    try:
        return json.dumps(payload, indent=2, ensure_ascii=False)
    except (TypeError, ValueError) as error:
        raise ValueError("jira_context must contain JSON-serializable data.") from error


async def generate_arch_package(
    jira_context: BaseModel | Mapping[str, Any],
    provider: Literal["gemini", "local"] = "gemini",
    model_name: str | None = None,
) -> SystemArchitectureGeneration:
    """Generate architecture Markdown and structured component records."""
    context_json = serialize_frd_data(jira_context)
    user_prompt = build_arch_user_prompt(context_json)

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
                system_instruction=ARCH_SYSTEM_PROMPT,
                temperature=0.15,
                response_mime_type="application/json",
                response_schema=SystemArchitectureGeneration,
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
                {"role": "system", "content": ARCH_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.15,
            response_format={"type": "json_object"},
        )
        response_data = json.loads(response.choices[0].message.content or "")
    else:
        raise ValueError(f"Unsupported architecture provider: {provider}")

    if isinstance(response_data, BaseModel):
        response_data = response_data.model_dump(mode="json")
    if not isinstance(response_data, Mapping):
        raise ValueError("Architecture provider returned an invalid response object.")
    normalized = _canonicalize_architecture_output(response_data)
    return SystemArchitectureGeneration.model_validate(normalized)


async def generate_architecture(
    jira_context: BaseModel | Mapping[str, Any],
    provider: Literal["gemini", "local"] = "gemini",
    model_name: str | None = None,
) -> str:
    """Generate architecture Markdown only, retaining the string return-value API."""
    result = await generate_arch_package(jira_context, provider, model_name)
    return result.arch_markdown.strip()
