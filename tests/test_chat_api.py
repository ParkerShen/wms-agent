from collections.abc import Iterator
import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app import main
from app.database import get_session
from app.llm.deepseek import (
    ChatCompletion,
    DeepSeekClientError,
    DeepSeekConfigurationError,
    StreamCompletionChunk,
    StreamToolCallDelta,
)
from app.models import Base
from app.seed import seed_inventory


@pytest.fixture
def chat_engine() -> Iterator[Engine]:
    test_engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(test_engine, "connect")
    def enable_foreign_keys(connection, _record) -> None:
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(test_engine)
    with Session(test_engine) as session, session.begin():
        seed_inventory(session)
    yield test_engine
    test_engine.dispose()


@pytest.fixture
def chat_client(chat_engine: Engine) -> Iterator[TestClient]:
    def override_session() -> Iterator[Session]:
        with Session(chat_engine) as session:
            yield session

    main.app.dependency_overrides[get_session] = override_session
    with TestClient(main.app) as test_client:
        yield test_client
    main.app.dependency_overrides.clear()


class ScriptedModel:
    def __init__(self, responses: list[dict]) -> None:
        self.responses = [ChatCompletion.model_validate(response) for response in responses]
        self.requests: list[tuple[list[dict], list[dict]]] = []

    def create_chat_completion(self, messages: list[dict], tools: list[dict]) -> ChatCompletion:
        self.requests.append((json.loads(json.dumps(messages)), json.loads(json.dumps(tools))))
        if not self.responses:
            raise AssertionError("chat route requested more completions than expected")
        return self.responses.pop(0)


def completion(message: dict, finish_reason: str = "stop") -> dict:
    return {
        "id": "chatcmpl-test",
        "model": "deepseek-chat",
        "choices": [
            {
                "index": 0,
                "message": message,
                "finish_reason": finish_reason,
            }
        ],
    }


def inventory_call() -> dict:
    return {
        "id": "call-inventory-1",
        "type": "function",
        "function": {
            "name": "query_inventory",
            "arguments": (
                '{"warehouse_code":"DEMO-WH-01",'
                '"sku_code":"DEMO-SKU-001"}'
            ),
        },
    }


def override_model(model: object) -> None:
    def dependency() -> Iterator[object]:
        yield model

    main.app.dependency_overrides[main.get_completion_model] = dependency


class ScriptedStreamModel:
    def __init__(self, turns: list[list[StreamCompletionChunk]]) -> None:
        self.turns = turns

    async def stream_chat_completion(self, messages, tools):
        if not self.turns:
            raise AssertionError("chat stream requested too many model turns")
        for chunk in self.turns.pop(0):
            yield chunk


def test_chat_stream_emits_sse_delta_and_done(chat_client: TestClient) -> None:
    override_model(
        ScriptedStreamModel(
            [[
                StreamCompletionChunk(content="库存可用 "),
                StreamCompletionChunk(content="42 件。", finish_reason="stop"),
            ]]
        )
    )

    response = chat_client.post("/chat/stream", json={"message": "查库存"})

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    frames = response.text.split("\n\n")
    assert [json.loads(frame.removeprefix("data: ")) for frame in frames if frame] == [
        {"type": "delta", "text": "库存可用 "},
        {"type": "delta", "text": "42 件。"},
        {"type": "done"},
    ]


def test_chat_stream_hides_agent_failure_in_error_event(
    chat_client: TestClient,
) -> None:
    class FailingStreamModel:
        async def stream_chat_completion(self, messages, tools):
            yield StreamCompletionChunk(content="部分内容")
            raise DeepSeekClientError("private provider detail")

    override_model(FailingStreamModel())

    response = chat_client.post("/chat/stream", json={"message": "查库存"})

    assert response.status_code == 200
    events = [json.loads(frame.removeprefix("data: ")) for frame in response.text.split("\n\n") if frame]
    assert events[-1] == {
        "type": "error",
        "message": "Chat service could not complete the request.",
    }
    assert "private provider detail" not in response.text
    assert not any(event["type"] == "done" for event in events)


def test_chat_stream_rejects_unconfigured_model_before_stream(
    chat_client: TestClient,
) -> None:
    class UnconfiguredStreamModel:
        def ensure_configured(self) -> None:
            raise DeepSeekConfigurationError("private config detail")

    override_model(UnconfiguredStreamModel())

    response = chat_client.post("/chat/stream", json={"message": "查库存"})

    assert response.status_code == 503
    assert response.json() == {"detail": "Chat service is not configured."}
    assert "private config detail" not in response.text


def test_chat_returns_final_answer_from_model(chat_client: TestClient) -> None:
    model = ScriptedModel([completion({"role": "assistant", "content": "你好，我可以帮你查库存。"})])
    override_model(model)

    response = chat_client.post("/chat", json={"message": "你好"})

    assert response.status_code == 200
    assert response.json() == {"answer": "你好，我可以帮你查库存。"}
    assert model.requests[0][0][-1] == {"role": "user", "content": "你好"}


def test_chat_runs_inventory_tool_before_answer(
    chat_client: TestClient,
) -> None:
    model = ScriptedModel(
        [
            completion(
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [inventory_call()],
                },
                finish_reason="tool_calls",
            ),
            completion({"role": "assistant", "content": "可用库存是 42 件，在途 12 件。"}),
        ]
    )
    override_model(model)

    response = chat_client.post(
        "/chat",
        json={"message": "DEMO-SKU-001 还有多少可用库存？"},
    )

    assert response.status_code == 200
    assert response.json() == {"answer": "可用库存是 42 件，在途 12 件。"}
    tool_messages = model.requests[1][0]
    assert tool_messages[-1]["role"] == "tool"
    assert json.loads(tool_messages[-1]["content"])["data"]["available"] == 42


@pytest.mark.parametrize(
    "payload",
    [{}, {"message": ""}, {"message": "x" * 2001}],
)
def test_chat_validates_message(chat_client: TestClient, payload: dict) -> None:
    response = chat_client.post("/chat", json=payload)

    assert response.status_code == 422


def test_chat_hides_provider_error(chat_client: TestClient) -> None:
    class FailingModel:
        def create_chat_completion(self, messages, tools):
            raise DeepSeekClientError("provider secret")

    override_model(FailingModel())

    response = chat_client.post("/chat", json={"message": "查库存"})

    assert response.status_code == 502
    assert response.json() == {"detail": "Chat service could not complete the request."}
    assert "provider secret" not in response.text


def test_chat_returns_unconfigured_status_without_leaking_details(
    chat_client: TestClient,
) -> None:
    class UnconfiguredModel:
        def create_chat_completion(self, messages, tools):
            raise DeepSeekConfigurationError("missing private configuration")

    override_model(UnconfiguredModel())

    response = chat_client.post("/chat", json={"message": "查库存"})

    assert response.status_code == 503
    assert response.json() == {"detail": "Chat service is not configured."}
    assert "missing private configuration" not in response.text


def test_chat_hides_agent_loop_error(chat_client: TestClient) -> None:
    class BrokenModel:
        def create_chat_completion(self, messages, tools):
            raise AssertionError("not expected")

    override_model(BrokenModel())
    from app import main as main_module

    original = main_module.run_inventory_agent
    main_module.run_inventory_agent = lambda *_args: (_ for _ in ()).throw(
        main_module.AgentLoopError("private loop details")
    )
    try:
        response = chat_client.post("/chat", json={"message": "查库存"})
    finally:
        main_module.run_inventory_agent = original

    assert response.status_code == 502
    assert response.json() == {"detail": "Chat service could not complete the request."}
    assert "private loop details" not in response.text


def test_completion_dependency_closes_owned_client(
    chat_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class ClosableModel:
        closed = False

        def create_chat_completion(self, messages, tools):
            return ChatCompletion.model_validate(
                completion({"role": "assistant", "content": "完成"})
            )

        def close(self) -> None:
            self.closed = True

    model = ClosableModel()
    monkeypatch.setattr(main, "DeepSeekClient", lambda: model)

    response = chat_client.post("/chat", json={"message": "你好"})

    assert response.status_code == 200
    assert response.json() == {"answer": "完成"}
    assert model.closed is True
