import json
import os

from dotenv import load_dotenv
from google import genai
from google.genai import types
from openai import AsyncOpenAI

from brd_generation.prompts import build_generation_prompt, build_system_prompt

load_dotenv()
GEMINI_MODEL_NAME = os.getenv("GEMINI_MODEL_NAME", "gemini-3.1-flash-lite")


def mcp_to_gemini_declarations(mcp_tools) -> list[types.FunctionDeclaration]:
    """Convert MCP tool schemas to Google GenAI function declarations."""
    return [
        types.FunctionDeclaration(
            name=tool.name,
            description=tool.description or "",
            parameters=tool.inputSchema or {},
        )
        for tool in mcp_tools
    ]


def mcp_to_openai_tools(mcp_tools) -> list[dict]:
    """Convert MCP tool schemas to standard OpenAI tool-call format."""
    return [
        {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description or "",
                "parameters": tool.inputSchema or {"type": "object", "properties": {}},
            },
        }
        for tool in mcp_tools
    ]


async def generate_brd(session, jira_key: str, mcp_tools, provider: str) -> None:
    """Run the selected language model against tools exposed by the MCP session."""
    if provider == "gemini":
        await _generate_with_gemini(session, jira_key, mcp_tools)
    elif provider == "local":
        await _generate_with_local_model(session, jira_key, mcp_tools)
    else:
        raise ValueError(f"Unsupported model provider: {provider}")


async def _generate_with_gemini(session, jira_key: str, mcp_tools) -> None:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY not found in environment.")

    gemini_client = genai.Client(api_key=api_key)
    gemini_tools = [
        types.Tool(function_declarations=mcp_to_gemini_declarations(mcp_tools))
    ]
    conversation_history = [
        types.Content(
            role="user",
            parts=[types.Part.from_text(text=build_generation_prompt(jira_key))],
        )
    ]
    model_id = GEMINI_MODEL_NAME

    for _ in range(10):
        response = gemini_client.models.generate_content(
            model=model_id,
            contents=conversation_history,
            config=types.GenerateContentConfig(
                system_instruction=build_system_prompt(),
                tools=gemini_tools,
                temperature=0.18,
            ),
        )
        function_calls = response.function_calls
        if not function_calls:
            print("\n=== Agent Response ===")
            print(response.text)
            return

        conversation_history.append(response.candidates[0].content)
        tool_response_parts = []
        for call in function_calls:
            print(f"-> Executing tool '{call.name}' with args: {call.args}")
            tool_output = await session.call_tool(call.name, arguments=dict(call.args or {}))
            text_result = "\n".join(
                content.text for content in tool_output.content if hasattr(content, "text")
            )
            tool_response_parts.append(
                types.Part.from_function_response(
                    name=call.name,
                    response={"result": text_result},
                )
            )
        conversation_history.append(types.Content(role="user", parts=tool_response_parts))


async def _generate_with_local_model(session, jira_key: str, mcp_tools) -> None:
    llm_url = os.getenv("LOCAL_LLM_URL", "http://127.0.0.1:8080/v1")
    model_name = os.getenv("LOCAL_MODEL_NAME", "qwen3-4b-thinking-2507.Q4_K_M.gguf")
    client = AsyncOpenAI(base_url=llm_url, api_key="not-needed")
    messages = [
        {"role": "system", "content": build_system_prompt()},
        {"role": "user", "content": build_generation_prompt(jira_key)},
    ]
    openai_tools = mcp_to_openai_tools(mcp_tools)

    for _ in range(10):
        response = await client.chat.completions.create(
            model=model_name,
            messages=messages,
            tools=openai_tools,
            tool_choice="auto",
            temperature=0.18,
        )
        response_message = response.choices[0].message
        tool_calls = response_message.tool_calls
        if not tool_calls:
            print("\n=== Agent Response ===")
            print(response_message.content)
            return

        messages.append(response_message)
        for call in tool_calls:
            function_name = call.function.name
            raw_arguments = call.function.arguments
            try:
                arguments = json.loads(raw_arguments) if isinstance(raw_arguments, str) else raw_arguments
            except json.JSONDecodeError:
                arguments = {}
            print(f"-> Executing tool '{function_name}' with args: {arguments}")
            tool_output = await session.call_tool(function_name, arguments=arguments)
            text_result = "\n".join(
                content.text for content in tool_output.content if hasattr(content, "text")
            )
            messages.append({
                "role": "tool",
                "tool_call_id": call.id,
                "content": text_result,
            })