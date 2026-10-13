import json

import httpx
import pytest
from pydantic import SecretStr

from app.config import Settings
from app.llm.deepseek import DeepSeekClient, DeepSeekClientError


API_KEY = "test-secret-key"


def make_settings(api_key: str | None = API_KEY) -> Settings:
    return Settings(
        _env_file=None,
        postgres_db="test-db",
        postgres_user="test-user",
        postgres_password=SecretStr("not-a-real-password"),
        deepseek_api_key=SecretStr(api_key) if api_key is not None else None,
    )


def test_client_sends_chat_completion_and_parses_response() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-test",
                "model": "deepseek-chat",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "库存可用 42 件。"},
                        "finish_reason": "stop",
                    }
                ],
            },
        )

    messages = [{"role": "user", "content": "查库存"}]
    tools = [
        {
            "type": "function",
            "function": {
                "name": "query_inventory",
                "description": "Query inventory.",
                "parameters": {
                    "type": "object",
                    "properties": {"warehouse_code": {"type": "string"}},
                    "required": ["warehouse_code"],
                },
            },
        }
    ]
    with httpx.Client(transport=httpx.MockTransport(handler)) as http_client:
        client = DeepSeekClient(config=make_settings(), client=http_client)
        completion = client.create_chat_completion(messages, tools=tools)

    request = requests[0]
    assert len(requests) == 1
    assert str(request.url) == "https://api.deepseek.com/chat/completions"
    assert request.headers["Authorization"] == f"Bearer {API_KEY}"
    assert json.loads(request.read()) == {
        "model": "deepseek-chat",
        "messages": messages,
        "tools": tools,
    }
    assert completion.id == "chatcmpl-test"
    assert completion.model == "deepseek-chat"
    assert completion.choices[0].message.content == "库存可用 42 件。"
    assert completion.choices[0].finish_reason == "stop"


def test_client_omits_tools_when_none() -> None:
    request_payload: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        request_payload.update(json.loads(request.read()))
        return httpx.Response(
            200,
            json={
                "id": "id-1",
                "model": "deepseek-chat",
                "choices": [
                    {"message": {"role": "assistant", "content": "ok"}}
                ],
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as http_client:
        client = DeepSeekClient(config=make_settings(), client=http_client)
        client.create_chat_completion([{"role": "user", "content": "hello"}])

    assert request_payload == {
        "model": "deepseek-chat",
        "messages": [{"role": "user", "content": "hello"}],
    }


def test_client_raises_safe_error_for_missing_key() -> None:
    called = False

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(200)

    with httpx.Client(transport=httpx.MockTransport(handler)) as http_client:
        client = DeepSeekClient(config=make_settings(api_key=None), client=http_client)
        with pytest.raises(DeepSeekClientError, match="API key is not configured"):
            client.create_chat_completion([{"role": "user", "content": "hello"}])

    assert called is False


def test_client_sanitizes_http_errors() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text=f"invalid key {API_KEY}")

    with httpx.Client(transport=httpx.MockTransport(handler)) as http_client:
        client = DeepSeekClient(config=make_settings(), client=http_client)
        with pytest.raises(DeepSeekClientError) as error:
            client.create_chat_completion([{"role": "user", "content": "hello"}])

    assert str(error.value) == "DeepSeek request failed with HTTP status 401."
    assert API_KEY not in str(error.value)


def test_client_sanitizes_malformed_success_response() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"unexpected": "shape"})

    with httpx.Client(transport=httpx.MockTransport(handler)) as http_client:
        client = DeepSeekClient(config=make_settings(), client=http_client)
        with pytest.raises(DeepSeekClientError, match="request or response was invalid"):
            client.create_chat_completion([{"role": "user", "content": "hello"}])


def test_client_uses_configured_endpoint_model_and_timeout() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["timeout"] = request.extensions.get("timeout")
        seen["payload"] = json.loads(request.read())
        return httpx.Response(
            200,
            json={
                "id": "id-1",
                "model": "custom-model",
                "choices": [
                    {"message": {"role": "assistant", "content": "ok"}}
                ],
            },
        )

    config = make_settings().model_copy(
        update={
            "deepseek_base_url": "https://example.test/v1/",
            "deepseek_model": "custom-model",
        }
    )
    with httpx.Client(transport=httpx.MockTransport(handler)) as http_client:
        client = DeepSeekClient(config=config, client=http_client, timeout=7.5)
        client.create_chat_completion([{"role": "user", "content": "hello"}])

    assert seen["url"] == "https://example.test/v1/chat/completions"
    assert seen["payload"]["model"] == "custom-model"
    assert seen["timeout"]["read"] == 7.5
