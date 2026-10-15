"""Intentionally unsafe counterexamples. Run locally only; never deploy this lab."""

from typing import Annotated

from mcp import MCPError
from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import INVALID_PARAMS, CallToolResult, TextContent
from pydantic import Field

CANARY = "DUMMY_SECRET_DO_NOT_USE"


def build_lab() -> tuple[MCPServer, dict[str, int]]:
    server = MCPServer("Local error lab")
    calls = {"typed": 0, "expected_error": 0}

    @server.tool()
    def typed(record_id: Annotated[int, Field(ge=1, strict=True)]) -> str:
        """Accept only a positive integer."""
        calls["typed"] += 1
        return f"record:{record_id}"

    @server.tool()
    def returned_error() -> str:
        """Counterexample: error text returned as an ordinary string."""
        return "Error: record not found"

    @server.tool()
    def returned_dict() -> dict:
        """Counterexample: an error-shaped dictionary is still a successful result."""
        return {"error": "record not found"}

    @server.tool()
    def expected_error() -> str:
        """Expected execution failure with safe, actionable text."""
        calls["expected_error"] += 1
        raise ToolError("NOT_FOUND: IDを確認して変更してください。")

    @server.tool(structured_output=False)
    def explicit_error() -> CallToolResult:
        """Explicitly set the protocol's tool error flag."""
        return CallToolResult(is_error=True, content=[TextContent(type="text", text="NOT_FOUND")])

    @server.tool()
    def protocol_error() -> str:
        """Demonstrate a deliberate JSON-RPC error, not an API failure mapping."""
        raise MCPError(code=INVALID_PARAMS, message="Lab protocol rejection")

    @server.tool()
    def crash() -> str:
        """Counterexample: an unexpected exception contains dummy internal detail."""
        raise RuntimeError(f"db.internal password={CANARY} /srv/private/app.py")

    @server.tool()
    def unsafe_tool_error() -> str:
        """Counterexample: deliberate errors do not sanitize author-provided text."""
        raise ToolError(f"password={CANARY}")

    @server.tool()
    def unsafe_protocol_error() -> str:
        """Counterexample: deliberate protocol error data is also public."""
        raise MCPError(code=INVALID_PARAMS, message="unsafe", data={"password": CANARY})

    return server, calls


if __name__ == "__main__":
    build_lab()[0].run()
