"""Collect real SDK responses; HTTP upstream behavior is explicitly simulated."""

from __future__ import annotations

import asyncio
import json
import platform
import sys
from datetime import datetime
from importlib.metadata import version
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
from mcp import Client, MCPError

from lab_server import CANARY, build_lab
from server import build_server

WIRE_CASES = [
    ("unknown_method", "no/such_method", {}),
    ("missing_tool_name", "tools/call", {"arguments": {}}),
    ("arguments_not_object", "tools/call", {"name": "typed", "arguments": []}),
    ("unknown_tool", "tools/call", {"name": "no_such_tool", "arguments": {}}),
    ("missing_argument", "tools/call", {"name": "typed", "arguments": {}}),
    ("wrong_type", "tools/call", {"name": "typed", "arguments": {"record_id": "abc"}}),
    ("out_of_range", "tools/call", {"name": "typed", "arguments": {"record_id": 0}}),
    ("numeric_string", "tools/call", {"name": "typed", "arguments": {"record_id": "1"}}),
    ("success", "tools/call", {"name": "typed", "arguments": {"record_id": 1}}),
    ("returned_string", "tools/call", {"name": "returned_error"}),
    ("returned_dict", "tools/call", {"name": "returned_dict"}),
    ("tool_error", "tools/call", {"name": "expected_error"}),
    ("explicit_is_error", "tools/call", {"name": "explicit_error"}),
    ("mcp_error", "tools/call", {"name": "protocol_error"}),
    ("unexpected_exception", "tools/call", {"name": "crash"}),
    ("unsafe_tool_error", "tools/call", {"name": "unsafe_tool_error"}),
    ("unsafe_protocol_error", "tools/call", {"name": "unsafe_protocol_error"}),
    ("validation_echo", "tools/call", {"name": "typed", "arguments": {"record_id": CANARY}}),
]


async def wire_observations() -> list[dict]:
    proc = await asyncio.create_subprocess_exec(
        sys.executable,
        str(Path(__file__).with_name("lab_server.py")),
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    meta = {
        "io.modelcontextprotocol/protocolVersion": "2026-07-28",
        "io.modelcontextprotocol/clientInfo": {"name": "error-lab", "version": "0.1.0"},
        "io.modelcontextprotocol/clientCapabilities": {},
    }

    async def exchange(request_id: int, method: str, params: dict) -> dict:
        request = {"jsonrpc": "2.0", "id": request_id, "method": method, "params": {**params, "_meta": meta}}
        proc.stdin.write((json.dumps(request) + "\n").encode())
        await proc.stdin.drain()
        while True:
            line = await asyncio.wait_for(proc.stdout.readline(), timeout=10)
            if not line:
                raise RuntimeError("stdio server stopped before responding")
            response = json.loads(line)
            if response.get("id") == request_id:
                return {"request": request, "response": response}

    # Drain stderr concurrently so a traceback can never block stdout.
    stderr = asyncio.create_task(proc.stderr.read())
    try:
        await exchange(0, "server/discover", {})
        results = []
        for index, (case, method, params) in enumerate(WIRE_CASES, 1):
            results.append({"case": case, **await exchange(index, method, params)})
        return results
    finally:
        if proc.returncode is None:
            proc.terminate()
        await asyncio.wait_for(proc.wait(), timeout=10)
        await stderr


async def upstream_observation(label: str, sequence: list[int | str], retry_header: str | None = None) -> dict:
    calls = []
    sleeps = []

    def respond(request: httpx.Request) -> httpx.Response:
        outcome = sequence[min(len(calls), len(sequence) - 1)]
        calls.append(str(request.url))
        if outcome == "timeout":
            raise httpx.ReadTimeout(f"upstream {CANARY}", request=request)
        if outcome == "bad_json":
            return httpx.Response(200, text=f"invalid {CANARY}")
        headers = {"Retry-After": retry_header} if retry_header is not None else {}
        body = {"name": "Alice", "internal_note": CANARY} if outcome == 200 else {"debug": CANARY}
        return httpx.Response(outcome, json=body, headers=headers)

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    async with httpx.AsyncClient(base_url="https://example.invalid", transport=httpx.MockTransport(respond)) as api:
        async with Client(build_server(api, sleep=fake_sleep)) as client:
            result = await client.call_tool("get_record", {"record_id": 1})
    return {
        "case": label,
        "simulated_upstream": sequence,
        "retry_after_header": retry_header,
        "http_calls": len(calls),
        "requested_sleeps_seconds": sleeps,
        "result": result.model_dump(mode="json", by_alias=True, exclude_none=True),
    }


async def collect() -> dict:
    lab, calls = build_lab()
    async with Client(lab) as client:
        expected = await client.call_tool("expected_error")
        try:
            await client.call_tool("protocol_error")
        except MCPError as exc:
            protocol = {"type": type(exc).__name__, "code": exc.code, "message": str(exc)}
        else:
            raise AssertionError("expected MCPError")
    upstream = []
    for label, sequence, header in [
        ("http_200", [200], None),
        ("http_404", [404], None),
        ("http_401", [401], None),
        ("http_403", [403], None),
        ("http_429_recovery", [429, 200], "1"),
        ("http_500_recovery", [500, 500, 200], None),
        ("http_503_exhausted", [503], None),
        ("http_429_long_wait", [429, 200], "20"),
        ("timeout_exhausted", ["timeout"], None),
        ("invalid_response", ["bad_json"], None),
    ]:
        upstream.append(await upstream_observation(label, sequence, header))
    return {
        "verified_date_jst": datetime.now(ZoneInfo("Asia/Tokyo")).date().isoformat(),
        "protocol_revision": "2026-07-28",
        "environment": {"python": platform.python_version(), "platform": platform.platform(),
                        **{p: version(p) for p in ("mcp", "mcp-types", "pydantic", "anyio", "httpx", "pytest")}},
        "scope": {"stdio": "real subprocess and JSON-RPC lines", "http": "httpx.MockTransport; no real network",
                  "sleep": "recorded intent only; no actual waiting", "llm": "not used"},
        "in_memory": {"tool_error_isError": expected.is_error, "tool_body_calls": calls["expected_error"],
                      "protocol_exception": protocol},
        "wire": await wire_observations(),
        "upstream": upstream,
    }


if __name__ == "__main__":
    # Write to stdout so collecting evidence never silently overwrites a file.
    print(json.dumps(asyncio.run(collect()), ensure_ascii=False, indent=2))
