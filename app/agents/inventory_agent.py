import asyncio
from collections.abc import AsyncIterator, Mapping, Sequence
from dataclasses import dataclass
import json
from typing import Any, Protocol

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.inventory_repository import InventoryNotFoundError
from app.llm.deepseek import (
    ChatCompletion,
    ChatMessage,
    StreamCompletionChunk,
    StreamToolCallDelta,
)
from app.tools.inventory import QUERY_INVENTORY_TOOL, execute_query_inventory


MAX_TOOL_ROUNDS = 3
MAX_TOOL_CALLS_PER_ROUND = 4
TOOL_RESULT_MAX_CHARS = 4000
INVENTORY_AGENT_SYSTEM_PROMPT = (
    "You are a read-only warehouse inventory assistant. For inventory questions, "
    "use query_inventory and base your answer only on its result. Do not invent "
    "quantities, construct SQL, or claim to change data. If the tool reports an "
    "error, explain that the requested inventory could not be verified."
)


class CompletionModel(Protocol):
    def create_chat_completion(
        self,
        messages: Sequence[Mapping[str, Any]],
        tools: Sequence[Mapping[str, Any]] | None = None,
    ) -> ChatCompletion: ...

    def stream_chat_completion(
        self,
        messages: Sequence[Mapping[str, Any]],
        tools: Sequence[Mapping[str, Any]] | None = None,
    ) -> AsyncIterator[StreamCompletionChunk]: ...


@dataclass
class _ToolCallAccumulator:
    call_id: str = ""
    call_type: str = ""
    name: str = ""
    arguments: str = ""


def inventory_tool_definition() -> dict[str, Any]:
    """Return the provider-neutral inventory tool contract in function-call format."""
    return {
        "type": "function",
        "function": {
            "name": QUERY_INVENTORY_TOOL["name"],
            "description": QUERY_INVENTORY_TOOL["description"],
            "parameters": QUERY_INVENTORY_TOOL["input_schema"],
        },
    }


def run_inventory_agent(
    user_message: str,
    session: Session,
    model: CompletionModel,
    max_tool_rounds: int = MAX_TOOL_ROUNDS,
) -> str:
    """Run a bounded, read-only inventory tool loop and return the final answer.

    Tool calls are restricted to the local allowlist and their results are paired
    with the provider's call IDs. Raises AgentLoopError for malformed or unbounded
    model turns; tool execution details are sanitized before returning to the model.
    """
    if max_tool_rounds < 0:
        raise ValueError("max_tool_rounds must not be negative")

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": INVENTORY_AGENT_SYSTEM_PROMPT},
        {"role": "user", "content": user_message},
    ]
    tools = [inventory_tool_definition()]
    tool_rounds = 0

    while True:
        completion = model.create_chat_completion(messages, tools=tools)
        choice = completion.choices[0]
        assistant_message = choice.message
        calls = assistant_message.tool_calls or []

        if not calls:
            return assistant_message.content or ""

        if tool_rounds >= max_tool_rounds:
            raise AgentLoopError("Agent exceeded the tool-call limit.")
        if len(calls) > MAX_TOOL_CALLS_PER_ROUND:
            raise AgentLoopError("Agent requested too many tool calls.")

        messages.append(_assistant_message_payload(assistant_message))
        for call in calls:
            result = _execute_tool_call(
                session,
                call.id,
                call.type,
                call.function.name,
                call.function.arguments,
            )
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call.id,
                    "content": _serialize_tool_result(result),
                }
            )
        tool_rounds += 1




async def stream_inventory_agent(
    user_message: str,
    session: Session,
    model: CompletionModel,
    max_tool_rounds: int = MAX_TOOL_ROUNDS,
) -> AsyncIterator[str]:
    """Stream assistant text and execute completed, allowlisted tool calls.

    Text chunks are yielded immediately as they arrive. Partial tool-call IDs and
    JSON arguments are buffered until the turn ends, validated as a whole, and
    paired with their results using the original call IDs.
    """
    if max_tool_rounds < 0:
        raise ValueError("max_tool_rounds must not be negative")

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": INVENTORY_AGENT_SYSTEM_PROMPT},
        {"role": "user", "content": user_message},
    ]
    tools = [inventory_tool_definition()]
    tool_rounds = 0

    while True:
        calls: dict[int, _ToolCallAccumulator] = {}
        text_chunks: list[str] = []
        finish_reason: str | None = None
        async for chunk in model.stream_chat_completion(messages, tools=tools):
            for delta in chunk.tool_calls:
                call = calls.setdefault(delta.index, _ToolCallAccumulator())
                _append_tool_delta(call, delta)
            if chunk.content:
                text_chunks.append(chunk.content)
                yield chunk.content
            if chunk.finish_reason is not None:
                finish_reason = chunk.finish_reason

        if not calls:
            if finish_reason == "tool_calls":
                raise AgentLoopError("Agent returned a malformed tool call.")
            return

        if tool_rounds >= max_tool_rounds:
            raise AgentLoopError("Agent exceeded the tool-call limit.")
        complete_calls = _complete_tool_calls(calls)
        if len(complete_calls) > MAX_TOOL_CALLS_PER_ROUND:
            raise AgentLoopError("Agent requested too many tool calls.")

        messages.append(_streamed_assistant_message(complete_calls, "".join(text_chunks)))
        for call in complete_calls:
            result = await asyncio.to_thread(
                _execute_tool_call,
                session,
                call["id"],
                call["type"],
                call["function"]["name"],
                call["function"]["arguments"],
            )
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call["id"],
                    "content": _serialize_tool_result(result),
                }
            )
        tool_rounds += 1


def _append_tool_delta(call: _ToolCallAccumulator, delta: StreamToolCallDelta) -> None:
    if delta.call_id is not None:
        call.call_id += delta.call_id
    if delta.call_type is not None:
        call.call_type += delta.call_type
    if delta.name is not None:
        call.name += delta.name
    if delta.arguments is not None:
        call.arguments += delta.arguments


def _complete_tool_calls(calls: dict[int, _ToolCallAccumulator]) -> list[dict[str, Any]]:
    completed: list[dict[str, Any]] = []
    for index in sorted(calls):
        call = calls[index]
        if not call.call_id or not call.name or not call.call_type:
            raise AgentLoopError("Agent returned a malformed tool call.")
        completed.append(
            {
                "id": call.call_id,
                "type": call.call_type,
                "function": {"name": call.name, "arguments": call.arguments},
            }
        )
    return completed


def _streamed_assistant_message(
    calls: list[dict[str, Any]], content: str = ""
) -> dict[str, Any]:
    return {"role": "assistant", "content": content, "tool_calls": calls}


def _serialize_tool_result(result: dict[str, Any]) -> str:
    content = json.dumps(result, ensure_ascii=False)
    if len(content) <= TOOL_RESULT_MAX_CHARS:
        return content
    return json.dumps({"error": "Tool result was too large."})


def _assistant_message_payload(message: ChatMessage) -> dict[str, Any]:
    payload = message.model_dump(exclude_none=True)
    if "model_extra" in payload:
        payload.pop("model_extra")
    return payload


def _execute_tool_call(
    session: Session,
    call_id: str,
    call_type: str,
    name: str,
    arguments_json: str,
) -> dict[str, str] | dict[str, Any]:
    if not call_id or call_type != "function":
        raise AgentLoopError("Agent returned a malformed tool call.")
    if name != QUERY_INVENTORY_TOOL["name"]:
        return {"error": "Unknown tool."}

    try:
        arguments = json.loads(arguments_json)
        if not isinstance(arguments, Mapping):
            return {"error": "Tool arguments must be a JSON object."}
        result = execute_query_inventory(session, arguments)
        return {"ok": True, "data": result}
    except (json.JSONDecodeError, ValidationError):
        return {"error": "Tool arguments were invalid."}
    except InventoryNotFoundError:
        return {"error": "Requested inventory was not found."}
    except Exception:
        return {"error": "Tool execution failed."}


class AgentLoopError(Exception):
    """Safe failure raised when the model returns an invalid or unbounded turn."""
