"""Read-only upstream adapter. No real credentials or API are required."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Annotated

import httpx
from mcp.server import MCPServer
from mcp.types import CallToolResult, TextContent
from pydantic import Field

MAX_ATTEMPTS = 3  # This retry policy is application code, not MCP behavior.
MAX_INLINE_WAIT = 2.0


def failure(
    code: str,
    message: str,
    next_action: str,
    retry_after_seconds: float | None = None,
) -> CallToolResult:
    error = {"code": code, "message": message, "next_action": next_action}
    if retry_after_seconds is not None:
        error["retry_after_seconds"] = retry_after_seconds
    payload = {"error": error}
    return CallToolResult(
        is_error=True,
        content=[TextContent(type="text", text=json.dumps(payload, ensure_ascii=False))],
        structured_content=payload,
    )


def retry_after(value: str | None, now: datetime | None = None) -> float | None:
    """Accept delay-seconds or HTTP-date; never retry earlier than requested."""
    if value is None:
        return None
    value = value.strip()
    if value.isascii() and value.isdigit():
        # A huge untrusted header must not overflow float conversion.
        return float(value) if len(value) <= 9 else float("inf")
    try:
        date = parsedate_to_datetime(value)
        if date.tzinfo is None:
            return None
        return max(0.0, (date - (now or datetime.now(timezone.utc))).total_seconds())
    except (ValueError, TypeError, OverflowError):
        return None


def build_server(
    api: httpx.AsyncClient,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> MCPServer:
    server = MCPServer("MCP error sample")

    @server.tool(structured_output=False)
    async def get_record(
        record_id: Annotated[int, Field(ge=1, strict=True)],
    ) -> CallToolResult:
        """Read one record by its positive integer ID. Never changes records."""
        for attempt in range(MAX_ATTEMPTS):
            response = None
            try:
                response = await api.get(f"/records/{record_id}", timeout=2.0)
            except httpx.TimeoutException:
                pass
            except httpx.RequestError:
                return failure("UPSTREAM_UNAVAILABLE", "接続に失敗しました。", "stop")

            if response is not None:
                status = response.status_code
                if status == 404:
                    return failure("NOT_FOUND", "対象がありません。", "change_record_id")
                if status in (401, 403):
                    return failure("ACCESS_DENIED", "取得権限を確認してください。", "ask_operator")
                if 200 <= status < 300:
                    try:
                        data = response.json()
                        name = data["name"]
                        if not isinstance(name, str):
                            raise ValueError("name must be a string")
                    except (ValueError, TypeError, KeyError):
                        return failure("INVALID_UPSTREAM_RESPONSE", "応答形式が不正です。", "ask_operator")
                    payload = {"id": record_id, "name": name}
                    return CallToolResult(
                        content=[TextContent(type="text", text=json.dumps(payload, ensure_ascii=False))],
                        structured_content=payload,
                    )
                if status not in (429, 500, 503):
                    return failure("UPSTREAM_REJECTED", "取得に失敗しました。", "ask_operator")

            delay = retry_after(response.headers.get("Retry-After")) if response is not None else None
            # Long waits belong to a job/host policy. Do not cap and retry early.
            if delay is not None and delay > MAX_INLINE_WAIT:
                # An oversized value cannot safely become a scheduling hint.
                wait = delay if delay <= 86400 else None
                return failure("RETRY_LATER", "待機後に再実行を検討してください。", "defer_to_host", wait)
            if attempt == MAX_ATTEMPTS - 1:
                return failure("RETRY_EXHAUSTED", "再試行の上限に達しました。", "stop")
            await sleep(delay if delay is not None else 0.25 * 2**attempt)

        raise AssertionError("unreachable")

    return server


async def main() -> None:
    # example.invalid is reserved; this entry point is for local demonstration.
    async with httpx.AsyncClient(base_url="https://example.invalid", follow_redirects=False) as api:
        await build_server(api).run_stdio_async()


if __name__ == "__main__":
    asyncio.run(main())
