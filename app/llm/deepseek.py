from collections.abc import AsyncIterator, Mapping, Sequence
from dataclasses import dataclass
import json
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.config import Settings, settings


class DeepSeekClientError(Exception):
    """Safe error raised for provider configuration, transport, and response failures."""


class DeepSeekConfigurationError(DeepSeekClientError):
    """Safe error raised when the provider is not configured locally."""


@dataclass(frozen=True)
class StreamToolCallDelta:
    index: int
    call_id: str | None = None
    call_type: str | None = None
    name: str | None = None
    arguments: str | None = None


@dataclass(frozen=True)
class StreamCompletionChunk:
    content: str | None = None
    tool_calls: tuple[StreamToolCallDelta, ...] = ()
    finish_reason: str | None = None


class ChatFunctionCall(BaseModel):
    name: str
    arguments: str


class ChatToolCall(BaseModel):
    id: str
    type: str
    function: ChatFunctionCall


class ChatMessage(BaseModel):
    model_config = ConfigDict(extra="allow")

    role: str
    content: str | None = None
    tool_calls: list[ChatToolCall] | None = None


class ChatChoice(BaseModel):
    model_config = ConfigDict(extra="allow")

    index: int = 0
    message: ChatMessage
    finish_reason: str | None = None


class ChatCompletion(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    choices: list[ChatChoice] = Field(min_length=1)
    model: str


class DeepSeekClient:
    """Request-scoped DeepSeek completions client with separately owned transports.

    Injected HTTP clients remain caller-owned; clients created internally are
    closed by ``close``/``aclose``. Streaming uses the asynchronous transport,
    while the synchronous method supports the existing non-streaming API.
    Provider and transport details are converted to safe DeepSeekClientError
    messages before leaving this adapter.
    """

    def __init__(
        self,
        config: Settings = settings,
        client: httpx.Client | None = None,
        timeout: float = 30.0,
        async_client: httpx.AsyncClient | None = None,
    ) -> None:
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        self._config = config
        self._client = client or httpx.Client(timeout=timeout)
        self._owns_client = client is None
        self._async_client = async_client
        self._owns_async_client = False
        self._timeout = timeout

    def ensure_configured(self) -> None:
        """Fail before network access when the local provider key is unavailable."""
        api_key = self._config.deepseek_api_key
        if api_key is None or not api_key.get_secret_value().strip():
            raise DeepSeekConfigurationError("DeepSeek API key is not configured.")

    def create_chat_completion(
        self,
        messages: Sequence[Mapping[str, Any]],
        tools: Sequence[Mapping[str, Any]] | None = None,
    ) -> ChatCompletion:
        """Send one non-streaming chat completion with the optional function schema."""
        self.ensure_configured()
        payload: dict[str, Any] = {
            "model": self._config.deepseek_model,
            "messages": list(messages),
        }
        if tools is not None:
            payload["tools"] = list(tools)

        endpoint = f"{self._config.deepseek_base_url.rstrip('/')}/chat/completions"
        try:
            response = self._client.post(
                endpoint,
                json=payload,
                headers={"Authorization": self._authorization_header()},
                timeout=self._timeout,
            )
            response.raise_for_status()
            return ChatCompletion.model_validate(response.json())
        except httpx.HTTPStatusError as error:
            raise DeepSeekClientError(
                f"DeepSeek request failed with HTTP status {error.response.status_code}."
            ) from None
        except (httpx.RequestError, ValueError, ValidationError):
            raise DeepSeekClientError("DeepSeek request or response was invalid.") from None

    async def stream_chat_completion(
        self,
        messages: Sequence[Mapping[str, Any]],
        tools: Sequence[Mapping[str, Any]] | None = None,
    ) -> AsyncIterator[StreamCompletionChunk]:
        """Yield validated deltas while the provider response remains open."""
        self.ensure_configured()
        payload: dict[str, Any] = {
            "model": self._config.deepseek_model,
            "messages": list(messages),
            "stream": True,
        }
        if tools is not None:
            payload["tools"] = list(tools)

        endpoint = f"{self._config.deepseek_base_url.rstrip('/')}/chat/completions"
        try:
            client = self._get_async_client()
            async with client.stream(
                "POST",
                endpoint,
                json=payload,
                headers={"Authorization": self._authorization_header()},
                timeout=self._timeout,
            ) as response:
                response.raise_for_status()
                async for event_data in _iter_sse_data(response):
                    if event_data == "[DONE]":
                        return
                    try:
                        event = _parse_stream_event(event_data)
                    except (TypeError, ValueError, KeyError):
                        raise DeepSeekClientError(
                            "DeepSeek request or response was invalid."
                        ) from None
                    if event is not None:
                        yield event
        except DeepSeekClientError:
            raise
        except httpx.HTTPStatusError as error:
            raise DeepSeekClientError(
                f"DeepSeek request failed with HTTP status {error.response.status_code}."
            ) from None
        except (httpx.RequestError, ValueError, ValidationError):
            raise DeepSeekClientError("DeepSeek request or response was invalid.") from None

    def _authorization_header(self) -> str:
        api_key = self._config.deepseek_api_key
        assert api_key is not None
        return f"Bearer {api_key.get_secret_value()}"

    def _get_async_client(self) -> httpx.AsyncClient:
        if self._async_client is None:
            self._async_client = httpx.AsyncClient(timeout=self._timeout)
            self._owns_async_client = True
        return self._async_client

    def close(self) -> None:
        """Close only the synchronous HTTP transport created by this client."""
        if self._owns_client:
            self._client.close()

    async def aclose(self) -> None:
        """Close owned async and sync transports; injected transports stay caller-owned."""
        if self._owns_async_client and self._async_client is not None:
            await self._async_client.aclose()
        self.close()

    def __enter__(self) -> "DeepSeekClient":
        return self

    def __exit__(self, _exc_type, _exc_value, _traceback) -> None:
        self.close()


async def _iter_sse_data(response: httpx.Response) -> AsyncIterator[str]:
    """Join SSE data lines; httpx handles arbitrary network-byte boundaries."""
    data_lines: list[str] = []
    async for line in response.aiter_lines():
        if not line:
            if data_lines:
                yield "\n".join(data_lines)
                data_lines.clear()
            continue
        if line.startswith(":"):
            continue
        if line.startswith("data:"):
            value = line[5:]
            data_lines.append(value[1:] if value.startswith(" ") else value)
    if data_lines:
        yield "\n".join(data_lines)


def _parse_stream_event(event_data: str) -> StreamCompletionChunk | None:
    payload = json.loads(event_data)
    if not isinstance(payload, dict):
        raise ValueError("Invalid stream event")
    choices = payload.get("choices")
    if not isinstance(choices, list):
        raise ValueError("Invalid stream event")
    if not choices:
        return None  # DeepSeek may send a trailing usage-only chunk.
    choice = choices[0]
    if not isinstance(choice, dict):
        raise ValueError("Invalid stream event")
    delta = choice.get("delta") or {}
    if not isinstance(delta, dict):
        raise ValueError("Invalid stream event")
    content = delta.get("content")
    if content is not None and not isinstance(content, str):
        raise ValueError("Invalid stream event")

    tool_call_deltas: list[StreamToolCallDelta] = []
    raw_calls = delta.get("tool_calls") or []
    if not isinstance(raw_calls, list):
        raise ValueError("Invalid stream event")
    for raw_call in raw_calls:
        if not isinstance(raw_call, dict) or not isinstance(raw_call.get("index"), int):
            raise ValueError("Invalid stream event")
        function = raw_call.get("function") or {}
        if not isinstance(function, dict):
            raise ValueError("Invalid stream event")
        call_id = raw_call.get("id")
        call_type = raw_call.get("type")
        name = function.get("name")
        arguments = function.get("arguments")
        if any(value is not None and not isinstance(value, str) for value in (call_id, call_type, name, arguments)):
            raise ValueError("Invalid stream event")
        tool_call_deltas.append(
            StreamToolCallDelta(
                index=raw_call["index"],
                call_id=call_id,
                call_type=call_type,
                name=name,
                arguments=arguments,
            )
        )

    finish_reason = choice.get("finish_reason")
    if finish_reason is not None and not isinstance(finish_reason, str):
        raise ValueError("Invalid stream event")
    return StreamCompletionChunk(
        content=content,
        tool_calls=tuple(tool_call_deltas),
        finish_reason=finish_reason,
    )
