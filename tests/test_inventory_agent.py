from collections.abc import AsyncIterator, Iterator
import asyncio
import json

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.agents.inventory_agent import (
    AgentLoopError,
    inventory_tool_definition,
    run_inventory_agent,
    stream_inventory_agent,
)
from app.llm.deepseek import ChatCompletion, StreamCompletionChunk, StreamToolCallDelta
from app.models import Base
from app.seed import seed_inventory


@pytest.fixture
def agent_engine() -> Iterator[Engine]:
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


class ScriptedStreamModel:
    def __init__(self, turns: list[list[StreamCompletionChunk]]) -> None:
        self.turns = turns
        self.requests: list[tuple[list[dict], list[dict]]] = []

    async def stream_chat_completion(self, messages, tools):
        self.requests.append((json.loads(json.dumps(messages)), json.loads(json.dumps(tools))))
        if not self.turns:
            raise AssertionError("Agent requested more streamed completions than expected")
        for chunk in self.turns.pop(0):
            yield chunk


def stream_call_chunks() -> list[StreamCompletionChunk]:
    return [
        StreamCompletionChunk(
            tool_calls=(
                StreamToolCallDelta(index=0, call_id="call-inv", call_type="function"),
            )
        ),
        StreamCompletionChunk(
            tool_calls=(
                StreamToolCallDelta(index=0, call_id="entory-1", name="query_in"),
            )
        ),
        StreamCompletionChunk(
            tool_calls=(
                StreamToolCallDelta(
                    index=0,
                    name="ventory",
                    arguments='{"warehouse_code":"DEMO-WH-01",',
                ),
            )
        ),
        StreamCompletionChunk(
            tool_calls=(
                StreamToolCallDelta(index=0, arguments='"sku_code":"DEMO-SKU-001"}'),
            ),
            finish_reason="tool_calls",
        ),
    ]


def test_stream_agent_yields_terminal_answer(agent_engine: Engine) -> None:
    model = ScriptedStreamModel(
        [[StreamCompletionChunk(content="你好，"), StreamCompletionChunk(content="可查库存。", finish_reason="stop")]]
    )

    async def collect() -> list[str]:
        with Session(agent_engine) as session:
            return [chunk async for chunk in stream_inventory_agent("查库存", session, model)]

    assert asyncio.run(collect()) == ["你好，", "可查库存。"]
    assert len(model.requests) == 1


def test_stream_agent_yields_text_before_tool_turn_finishes(agent_engine: Engine) -> None:
    model = ScriptedStreamModel(
        [
            [
                StreamCompletionChunk(content="正在查询。"),
                *stream_call_chunks(),
            ],
            [StreamCompletionChunk(content="查询完成。", finish_reason="stop")],
        ]
    )

    async def collect() -> list[str]:
        with Session(agent_engine) as session:
            return [chunk async for chunk in stream_inventory_agent("查库存", session, model)]

    assert asyncio.run(collect()) == ["正在查询。", "查询完成。"]
    assert len(model.requests) == 2


def test_stream_agent_buffers_tool_deltas_and_pairs_result(agent_engine: Engine) -> None:
    model = ScriptedStreamModel(
        [
            stream_call_chunks(),
            [
                StreamCompletionChunk(content="可用库存为 "),
                StreamCompletionChunk(content="42 件。", finish_reason="stop"),
            ],
        ]
    )

    async def collect() -> list[str]:
        with Session(agent_engine) as session:
            return [
                chunk
                async for chunk in stream_inventory_agent("查库存", session, model)
            ]

    assert asyncio.run(collect()) == ["可用库存为 ", "42 件。"]
    second_turn = model.requests[1][0]
    assert second_turn[-2] == {
        "role": "assistant",
        "content": "",
        "tool_calls": [
            {
                "id": "call-inventory-1",
                "type": "function",
                "function": {
                    "name": "query_inventory",
                    "arguments": '{"warehouse_code":"DEMO-WH-01","sku_code":"DEMO-SKU-001"}',
                },
            }
        ],
    }
    assert second_turn[-1]["role"] == "tool"
    assert second_turn[-1]["tool_call_id"] == "call-inventory-1"
    assert json.loads(second_turn[-1]["content"])["data"]["available"] == 42


def test_stream_agent_rejects_malformed_call(agent_engine: Engine) -> None:
    model = ScriptedStreamModel(
        [[
            StreamCompletionChunk(
                tool_calls=(StreamToolCallDelta(index=0, call_type="function"),),
                finish_reason="tool_calls",
            )
        ]]
    )

    async def collect() -> None:
        with Session(agent_engine) as session:
            _ = [chunk async for chunk in stream_inventory_agent("查库存", session, model)]

    with pytest.raises(AgentLoopError, match="malformed tool call"):
        asyncio.run(collect())


class ScriptedModel:
    def __init__(self, responses: list[dict]) -> None:
        self.responses = [ChatCompletion.model_validate(response) for response in responses]
        self.requests: list[tuple[list[dict], list[dict]]] = []

    def create_chat_completion(self, messages: list[dict], tools: list[dict]) -> ChatCompletion:
        self.requests.append((json.loads(json.dumps(messages)), json.loads(json.dumps(tools))))
        if not self.responses:
            raise AssertionError("Agent requested more completions than expected")
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


def inventory_call(
    call_id: str = "call-inventory-1",
    arguments: str = '{"warehouse_code":"DEMO-WH-01","sku_code":"DEMO-SKU-001"}',
) -> dict:
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": "query_inventory", "arguments": arguments},
    }


def test_inventory_tool_definition_uses_deepseek_function_schema() -> None:
    definition = inventory_tool_definition()

    assert definition["type"] == "function"
    assert definition["function"]["name"] == "query_inventory"
    assert definition["function"]["description"]
    assert definition["function"]["parameters"]["additionalProperties"] is False
    assert set(definition["function"]["parameters"]["properties"]) == {
        "warehouse_code",
        "sku_code",
    }


def test_agent_returns_terminal_assistant_text() -> None:
    model = ScriptedModel([completion({"role": "assistant", "content": "你好"})])

    response = run_inventory_agent("你好", session=None, model=model)  # type: ignore[arg-type]

    assert response == "你好"
    assert model.requests[0][0] == [
        {"role": "system", "content": "You are a read-only warehouse inventory assistant. For inventory questions, use query_inventory and base your answer only on its result. Do not invent quantities, construct SQL, or claim to change data. If the tool reports an error, explain that the requested inventory could not be verified."},
        {"role": "user", "content": "你好"},
    ]
    assert model.requests[0][1] == [inventory_tool_definition()]


def test_agent_runs_inventory_tool_and_returns_final_answer(agent_engine: Engine) -> None:
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
            completion({"role": "assistant", "content": "可用库存是 42 件。"}),
        ]
    )

    with Session(agent_engine) as session:
        response = run_inventory_agent("查 DEMO-SKU-001 库存", session, model)

    assert response == "可用库存是 42 件。"
    assert len(model.requests) == 2
    second_turn_messages = model.requests[1][0]
    assert second_turn_messages[0]["role"] == "system"
    assert second_turn_messages[1] == {
        "role": "user",
        "content": "查 DEMO-SKU-001 库存",
    }
    assert second_turn_messages[2]["role"] == "assistant"
    assert second_turn_messages[2]["tool_calls"][0]["id"] == "call-inventory-1"
    tool_result = second_turn_messages[3]
    assert tool_result["role"] == "tool"
    assert tool_result["tool_call_id"] == "call-inventory-1"
    result_payload = json.loads(tool_result["content"])
    assert result_payload["ok"] is True
    assert result_payload["data"]["available"] == 42
    assert result_payload["data"]["in_transit"] == 12


def test_agent_handles_multiple_calls_and_pairs_each_result(agent_engine: Engine) -> None:
    second_call = inventory_call(
        call_id="call-inventory-2",
        arguments='{"warehouse_code":"DEMO-WH-01","sku_code":"DEMO-SKU-002"}',
    )
    model = ScriptedModel(
        [
            completion(
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [inventory_call(), second_call],
                },
                finish_reason="tool_calls",
            ),
            completion({"role": "assistant", "content": "查询完成。"}),
        ]
    )

    with Session(agent_engine) as session:
        response = run_inventory_agent("查两个 SKU", session, model)

    assert response == "查询完成。"
    results = model.requests[1][0][3:]
    assert [result["tool_call_id"] for result in results] == [
        "call-inventory-1",
        "call-inventory-2",
    ]
    assert [json.loads(result["content"])["data"]["available"] for result in results] == [
        42,
        15,
    ]


def test_agent_returns_sanitized_errors_for_bad_or_unknown_tool_calls(agent_engine: Engine) -> None:
    model = ScriptedModel(
        [
            completion(
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "bad-args",
                            "type": "function",
                            "function": {
                                "name": "query_inventory",
                                "arguments": "not-json",
                            },
                        },
                        {
                            "id": "unknown-tool",
                            "type": "function",
                            "function": {"name": "execute_sql", "arguments": "{}"},
                        },
                    ],
                },
                finish_reason="tool_calls",
            ),
            completion({"role": "assistant", "content": "无法完成查询。"}),
        ]
    )

    with Session(agent_engine) as session:
        response = run_inventory_agent("查库存", session, model)

    assert response == "无法完成查询。"
    results = model.requests[1][0][3:]
    assert json.loads(results[0]["content"]) == {"error": "Tool arguments were invalid."}
    assert json.loads(results[1]["content"]) == {"error": "Unknown tool."}
    assert all("Traceback" not in result["content"] for result in results)


def test_agent_rejects_malformed_call_and_stops_at_round_limit(agent_engine: Engine) -> None:
    missing_id_model = ScriptedModel(
        [
            completion(
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [inventory_call(call_id="")],
                },
                finish_reason="tool_calls",
            )
        ]
    )
    with Session(agent_engine) as session:
        with pytest.raises(AgentLoopError, match="malformed tool call"):
            run_inventory_agent("查库存", session, missing_id_model)

    endless_model = ScriptedModel(
        [
            completion(
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [inventory_call(f"call-{index}")],
                },
                finish_reason="tool_calls",
            )
            for index in range(3)
        ]
    )
    with Session(agent_engine) as session:
        with pytest.raises(AgentLoopError, match="tool-call limit"):
            run_inventory_agent("查库存", session, endless_model, max_tool_rounds=2)

    assert len(endless_model.requests) == 3


def test_agent_tool_execution_errors_are_sanitized(
    agent_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_with_secret(*_args, **_kwargs):
        raise RuntimeError("private backend detail")

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
            completion({"role": "assistant", "content": "查询失败。"}),
        ]
    )

    import app.agents.inventory_agent as agent_module

    monkeypatch.setattr(agent_module, "execute_query_inventory", fail_with_secret)
    with Session(agent_engine) as session:
        response = run_inventory_agent("查库存", session, model)

    assert response == "查询失败。"
    result = model.requests[1][0][3]["content"]
    assert json.loads(result) == {"error": "Tool execution failed."}
    assert "private backend detail" not in result


def test_agent_returns_recorded_error_for_missing_inventory(agent_engine: Engine) -> None:
    model = ScriptedModel(
        [
            completion(
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        inventory_call(
                            arguments='{"warehouse_code":"MISSING-WH","sku_code":"DEMO-SKU-001"}'
                        )
                    ],
                },
                finish_reason="tool_calls",
            ),
            completion({"role": "assistant", "content": "未找到该仓库。"}),
        ]
    )

    with Session(agent_engine) as session:
        response = run_inventory_agent("查库存", session, model)

    assert response == "未找到该仓库。"
    assert json.loads(model.requests[1][0][3]["content"]) == {
        "error": "Requested inventory was not found."
    }


def test_agent_tool_result_size_is_bounded(
    agent_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.agents.inventory_agent as agent_module

    monkeypatch.setattr(
        agent_module,
        "_execute_tool_call",
        lambda *_args: {"ok": True, "data": "x" * 5000},
    )
    model = ScriptedModel(
        [
            completion(
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "oversized-result",
                            "type": "function",
                            "function": {
                                "name": "query_inventory",
                                "arguments": '{"warehouse_code":"DEMO-WH-01","sku_code":"DEMO-SKU-001"}',
                            },
                        }
                    ],
                },
                finish_reason="tool_calls",
            ),
            completion({"role": "assistant", "content": "结果过大。"}),
        ]
    )

    with Session(agent_engine) as session:
        response = run_inventory_agent("查库存", session, model)

    assert response == "结果过大。"
    tool_result = model.requests[1][0][3]
    assert json.loads(tool_result["content"]) == {"error": "Tool result was too large."}
    assert len(tool_result["content"]) <= 100


def test_agent_rejects_too_many_calls_in_one_turn(agent_engine: Engine) -> None:
    calls = [inventory_call(f"call-{index}") for index in range(5)]
    model = ScriptedModel(
        [
            completion(
                {"role": "assistant", "content": None, "tool_calls": calls},
                finish_reason="tool_calls",
            )
        ]
    )

    with Session(agent_engine) as session:
        with pytest.raises(AgentLoopError, match="too many tool calls"):
            run_inventory_agent("查库存", session, model)

    assert len(model.requests) == 1
