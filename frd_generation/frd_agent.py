"""Generate a traceable Functional Requirements Document from supplied Jira context."""

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

    return FRDGeneration.model_validate(response_data)


async def generate_frd(
    jira_context: BaseModel | Mapping[str, Any],
    provider: Literal["gemini", "local"] = "gemini",
    model_name: str | None = None,
) -> str:
    """Generate FRD Markdown only, retaining the simple return-value API."""
    result = await generate_frd_package(jira_context, provider, model_name)
    return result.frd_markdown.strip()
