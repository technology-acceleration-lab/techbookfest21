import json
import logging
from datetime import datetime, timezone

import httpx
import pytest
from mcp import Client, MCPError

from lab_server import CANARY, build_lab
from probe import upstream_observation, wire_observations
from server import build_server, retry_after

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.parametrize("arguments", [{}, {"record_id": "abc"}, {"record_id": 0}, {"record_id": "1"}])
async def test_invalid_arguments_never_enter_tool(arguments):
    server, calls = build_lab()
    async with Client(server) as client:
        result = await client.call_tool("typed", arguments)
    assert result.is_error
    assert calls["typed"] == 0


async def test_valid_input_enters_tool():
    server, calls = build_lab()
    async with Client(server) as client:
        result = await client.call_tool("typed", {"record_id": 1})
    assert not result.is_error
    assert calls["typed"] == 1


@pytest.mark.parametrize("tool", ["returned_error", "returned_dict"])
async def test_returning_an_error_does_not_set_the_flag(tool):
    server, _ = build_lab()
    async with Client(server) as client:
        result = await client.call_tool(tool)
    assert not result.is_error
    assert "error" in result.model_dump_json().lower()


async def test_tool_error_does_not_raise_or_retry_even_in_test_mode():
    server, calls = build_lab()
    async with Client(server, raise_exceptions=True) as client:
        result = await client.call_tool("expected_error")
    assert result.is_error
    assert "NOT_FOUND" in result.content[0].text
    assert calls["expected_error"] == 1


async def test_protocol_error_raises():
    server, _ = build_lab()
    async with Client(server) as client:
        with pytest.raises(MCPError) as error:
            await client.call_tool("protocol_error")
    assert error.value.code == -32602


async def test_unexpected_exception_is_masked_but_logged(caplog):
    server, _ = build_lab()
    with caplog.at_level(logging.ERROR):
        async with Client(server) as client:
            result = await client.call_tool("crash")
    assert result.is_error
    assert result.content[0].text == "Error executing tool crash"
    assert CANARY not in result.model_dump_json()
    assert CANARY in caplog.text


@pytest.mark.parametrize("tool, arguments", [
    ("unsafe_tool_error", {}), ("typed", {"record_id": CANARY}),
])
async def test_deliberate_error_and_validation_can_echo_dummy_secret(tool, arguments):
    server, _ = build_lab()
    async with Client(server) as client:
        result = await client.call_tool(tool, arguments)
    assert result.is_error
    assert CANARY in result.model_dump_json()


async def test_protocol_error_data_is_public():
    server, _ = build_lab()
    async with Client(server) as client:
        with pytest.raises(MCPError) as error:
            await client.call_tool("unsafe_protocol_error")
    assert error.value.data == {"password": CANARY}


async def test_stdio_jsonrpc_contract():
    rows = {r["case"]: r["response"] for r in await wire_observations()}
    assert rows["unknown_method"]["error"]["code"] == -32601
    assert rows["missing_tool_name"]["error"]["code"] == -32602
    assert rows["arguments_not_object"]["error"]["code"] == -32602
    # Observed SDK behavior differs from the specification's unknown-tool example.
    assert rows["unknown_tool"]["result"]["isError"] is True
    assert rows["tool_error"]["result"]["isError"] is True
    assert rows["explicit_is_error"]["result"]["isError"] is True
    assert rows["mcp_error"]["error"]["code"] == -32602
    assert "result" not in rows["mcp_error"]
    assert rows["unexpected_exception"]["result"]["content"][0]["text"] == "Error executing tool crash"
    assert CANARY not in json.dumps(rows["unexpected_exception"])


@pytest.mark.parametrize("status, code, action", [
    (404, "NOT_FOUND", "change_record_id"), (401, "ACCESS_DENIED", "ask_operator"),
    (403, "ACCESS_DENIED", "ask_operator"),
])
async def test_nonretryable_http_errors(status, code, action):
    row = await upstream_observation(f"http_{status}", [status])
    assert row["http_calls"] == 1
    assert row["requested_sleeps_seconds"] == []
    assert row["result"]["isError"] is True
    assert row["result"]["structuredContent"]["error"]["code"] == code
    assert row["result"]["structuredContent"]["error"]["next_action"] == action
    assert CANARY not in json.dumps(row["result"])


@pytest.mark.parametrize("sequence, header, calls, sleeps, code", [
    ([429, 200], "1", 2, [1.0], None),
    ([500, 500, 200], None, 3, [0.25, 0.5], None),
    ([503], None, 3, [0.25, 0.5], "RETRY_EXHAUSTED"),
    (["timeout"], None, 3, [0.25, 0.5], "RETRY_EXHAUSTED"),
    ([429, 200], "20", 1, [], "RETRY_LATER"),
    (["bad_json"], None, 1, [], "INVALID_UPSTREAM_RESPONSE"),
])
async def test_retry_policy_is_bounded_and_hides_upstream_details(sequence, header, calls, sleeps, code):
    row = await upstream_observation("retry", sequence, header)
    assert row["http_calls"] == calls
    assert row["requested_sleeps_seconds"] == sleeps
    assert CANARY not in json.dumps(row["result"])
    assert row["result"]["isError"] is (code is not None)
    payload = row["result"]["structuredContent"]
    if code is None:
        assert payload == {"id": 1, "name": "Alice"}
    else:
        assert payload["error"]["code"] == code


async def test_bad_record_id_does_not_call_upstream():
    def never_called(request):
        pytest.fail("invalid input reached upstream")

    async with httpx.AsyncClient(base_url="https://example.invalid", transport=httpx.MockTransport(never_called)) as api:
        async with Client(build_server(api)) as client:
            result = await client.call_tool("get_record", {"record_id": -1})
    assert result.is_error


async def test_retry_after_supports_http_date_and_rejects_invalid_value():
    now = datetime(2026, 10, 15, tzinfo=timezone.utc)
    assert retry_after("Thu, 15 Oct 2026 00:00:10 GMT", now) == 10
    assert retry_after("Thu, 15 Oct 2026 00:00:00 GMT", now) == 0
    assert retry_after("nonsense", now) is None
    assert retry_after("-1", now) is None
    assert retry_after("1" * 1000, now) == float("inf")
