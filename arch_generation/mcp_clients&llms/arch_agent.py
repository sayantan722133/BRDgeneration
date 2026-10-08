"""Generate a traceable System Architecture Document and component specifications from Jira FRD context."""

import asyncio
import json
import os
from collections.abc import Mapping
from typing import Any, Literal

from dotenv import load_dotenv
from google import genai
from google.genai import types
from openai import AsyncOpenAI
from pydantic import BaseModel, Field, field_validator

from arch_generation.prompts import ARCH_SYSTEM_PROMPT, build_arch_user_prompt

load_dotenv()

GEMINI_MODEL_NAME = os.getenv("GEMINI_MODEL_NAME", "gemini-3.1-flash-lite")
LOCAL_LLM_URL = os.getenv("LOCAL_LLM_URL", "http://127.0.0.1:8080/v1")
LOCAL_MODEL_NAME = os.getenv("LOCAL_MODEL_NAME", "qwen3-4b-thinking-2507.Q4_K_M.gguf")


class ArchComponent(BaseModel):
    component_id: str = Field(pattern=r"^COMP-[A-Z0-9]+-\d+$")
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
    module_id: str = Field(min_length=1)
    source_requirement_ids: list[str] = Field(min_length=1)
    source_story_ids: list[str] = Field(min_length=1)
    tech_stack: list[str] = Field(min_length=1)
    responsibilities: list[str] = Field(min_length=2, max_length=8)
    dependencies: list[str] = Field(default_factory=list)
    data_entities_handled: list[str] = Field(
        min_length=1,
        description="Entities managed by this component, supplying the entity inventory for Step 4 ERD generation.",
    )

    @field_validator("source_requirement_ids")
    @classmethod
    def validate_fr_ids(cls, ids: list[str]) -> list[str]:
        for req_id in ids:
            if not req_id.upper().startswith("FR-"):
                raise ValueError(f"Requirement ID '{req_id}' must follow FR-<n> pattern.")
        return ids

    @field_validator("source_story_ids")
    @classmethod
    def validate_story_ids(cls, ids: list[str]) -> list[str]:
        for story_id in ids:
            if not story_id.upper().startswith("US-FR-"):
                raise ValueError(f"Story ID '{story_id}' must follow US-FR-<n> pattern.")
        return ids


class IntegrationContract(BaseModel):
    source_component_id: str = Field(pattern=r"^COMP-[A-Z0-9]+-\d+$")
    target_component_id: str = Field(pattern=r"^COMP-[A-Z0-9]+-\d+$")
    protocol: Literal["REST", "GraphQL", "gRPC", "WebSocket", "Kafka", "RabbitMQ", "SQS/SNS", "Database Client"]
    interaction_type: Literal["Synchronous Request-Response", "Asynchronous Event", "Publish-Subscribe", "Batch Extraction"]
    data_format: str = Field(default="JSON")
    contract_summary: str = Field(min_length=5)


class SystemArchitectureGeneration(BaseModel):
    arch_markdown: str = Field(min_length=100)
    architecture_pattern: str = Field(min_length=3)
    rationale: str = Field(min_length=20)
    components: list[ArchComponent] = Field(min_length=1)
    integration_contracts: list[IntegrationContract] = Field(min_length=1)


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

    return SystemArchitectureGeneration.model_validate(response_data)


async def generate_architecture(
    jira_context: BaseModel | Mapping[str, Any],
    provider: Literal["gemini", "local"] = "gemini",
    model_name: str | None = None,
) -> str:
    """Generate architecture Markdown only, retaining the string return-value API."""
    result = await generate_arch_package(jira_context, provider, model_name)
    return result.arch_markdown.strip()
