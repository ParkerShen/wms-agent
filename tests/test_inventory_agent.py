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
    inventory_tool_definitions,
    run_inventory_agent,
    stream_inventory_agent,
)
from app.llm.deepseek import ChatCompletion, StreamCompletionChunk, StreamToolCallDelta
from app.models import Base, InventoryBalance, SKU, Warehouse, WarehouseLocation
from app.seed import seed_inventory
from app.seed_bulk import SHOWCASE_BATCH_ID


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
    definitions = inventory_tool_definitions()

    assert len(definitions) == 4
    assert [definition["function"]["name"] for definition in definitions] == [
        "query_inventory",
        "list_warehouses",
        "list_warehouse_products",
        "find_product_warehouses",
    ]
    assert definitions[0] == inventory_tool_definition()
    for definition in definitions:
        assert definition["type"] == "function"
        assert definition["function"]["description"]
        assert definition["function"]["parameters"]["additionalProperties"] is False
    assert set(definitions[0]["function"]["parameters"]["properties"]) == {
        "warehouse_code",
        "sku_code",
    }


def discovery_engine(agent_engine: Engine) -> Engine:
    with Session(agent_engine) as session, session.begin():
        warehouse = Warehouse(
            display_id=1,
            code="USLAX",
            name="洛杉矶国际物流中心",
            name_en="Los Angeles Regional Fulfillment Center",
            city="Los Angeles",
            city_cn="洛杉矶",
            batch_id=SHOWCASE_BATCH_ID,
        )
        sku = SKU(
            code="YC-TEST-001",
            name="蓝牙降噪耳机（曜石黑）",
            name_en="Bluetooth headset, onyx black",
            batch_id=SHOWCASE_BATCH_ID,
        )
        session.add_all([warehouse, sku])
        session.flush()
        location = WarehouseLocation(
            warehouse_id=warehouse.id, code="USLAX-RACK-01", batch_id=SHOWCASE_BATCH_ID
        )
        session.add(location)
        session.flush()
        session.add(
            InventoryBalance(
                location_id=location.id,
                sku_id=sku.id,
                good_on_hand=8,
                allocated=1,
                frozen=1,
                batch_id=SHOWCASE_BATCH_ID,
            )
        )
    return agent_engine


def test_agent_runs_chinese_discovery_tool_calls(agent_engine: Engine) -> None:
    engine = discovery_engine(agent_engine)
    calls = [
        {
            "id": "list-products",
            "type": "function",
            "function": {
                "name": "list_warehouse_products",
                "arguments": '{"warehouse_query":"洛杉矶"}',
            },
        },
        {
            "id": "find-product",
            "type": "function",
            "function": {
                "name": "find_product_warehouses",
                "arguments": '{"product_query":"蓝牙降噪耳机（曜石黑）"}',
            },
        },
        {
            "id": "list-warehouses",
            "type": "function",
            "function": {"name": "list_warehouses", "arguments": "{}"},
        },
    ]
    model = ScriptedModel([
        completion({"role": "assistant", "content": None, "tool_calls": calls}, finish_reason="tool_calls"),
        completion({"role": "assistant", "content": "查询到模拟仓库和商品信息。"}),
    ])

    with Session(engine) as session:
        response = run_inventory_agent("洛杉矶仓有什么商品？蓝牙降噪耳机在哪个仓？有哪些仓库？", session, model)

    assert response == "查询到模拟仓库和商品信息。"
    tool_messages = model.requests[1][0][3:]
    assert [message["tool_call_id"] for message in tool_messages] == [
        "list-products", "find-product", "list-warehouses"
    ]
    product_result = json.loads(tool_messages[0]["content"])["data"]
    assert product_result["warehouse"]["code"] == "USLAX"
    assert product_result["items"][0]["code"] == "YC-TEST-001"
    assert product_result["items"][0]["available"] == 6
    reverse_result = json.loads(tool_messages[1]["content"])["data"]
    assert reverse_result["items"][0]["code"] == "USLAX"
    assert json.loads(tool_messages[2]["content"])["data"]["status"] == "ok"


def test_stream_agent_runs_chinese_discovery_tool(agent_engine: Engine) -> None:
    engine = discovery_engine(agent_engine)
    chunks = [
        StreamCompletionChunk(tool_calls=(StreamToolCallDelta(index=0, call_id="discovery-1", call_type="function"),)),
        StreamCompletionChunk(tool_calls=(StreamToolCallDelta(index=0, name="find_product_warehouses", arguments='{"product_query":"蓝牙降噪耳机（曜石黑）"}'),), finish_reason="tool_calls"),
    ]
    model = ScriptedStreamModel(
        [chunks, [StreamCompletionChunk(content="在洛杉矶仓有记录。", finish_reason="stop")]]
    )

    async def collect() -> list[str]:
        with Session(engine) as session:
            return [text async for text in stream_inventory_agent("这个商品在哪个仓？", session, model)]

    assert asyncio.run(collect()) == ["在洛杉矶仓有记录。"]
    result = json.loads(model.requests[1][0][-1]["content"])
    assert result["data"]["items"][0]["code"] == "USLAX"


def test_agent_returns_terminal_assistant_text() -> None:
    model = ScriptedModel([completion({"role": "assistant", "content": "你好"})])

    response = run_inventory_agent("你好", session=None, model=model)  # type: ignore[arg-type]

    assert response == "你好"
    assert model.requests[0][0] == [
        {"role": "system", "content": "You are a read-only warehouse inventory assistant using fictional showcase data. For questions asking which warehouses exist, use list_warehouses. For products in a warehouse use list_warehouse_products; for warehouses containing a product use find_product_warehouses. These tools accept Chinese or English names/cities, or codes. Use query_inventory for a detailed stock lookup when the warehouse and SKU are known. Base every factual answer only on tool results. Do not invent quantities, construct SQL, or claim to change data. Ask the user to clarify when the tool returns ambiguous candidates. Distinguish on-hand from in-transit inventory and disclose when a result page is incomplete. If a tool reports an error, explain that the requested information could not be verified."},
        {"role": "user", "content": "你好"},
    ]
    assert model.requests[0][1] == inventory_tool_definitions()


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

    monkeypatch.setattr(agent_module, "execute_inventory_tool", lambda name, session, args: fail_with_secret())
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
