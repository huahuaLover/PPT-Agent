"""MCP client environment for the minimal agent demo."""

import asyncio
import json
import os
import sys
from contextlib import AsyncExitStack
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.types import TextContent

from models import AppConfig, MCPServerConfig, ToolObservation


class AgentEnv:
    """Own MCP connections and expose normalized tools to agents."""

    def __init__(self, workspace: Path, config: AppConfig, demo_root: Path) -> None:
        self.workspace = workspace.resolve()
        self.config = config
        self.demo_root = demo_root.resolve()
        self._stack = AsyncExitStack()
        self._sessions: dict[str, ClientSession] = {}
        self._tools: dict[str, dict[str, Any]] = {}
        self._tool_to_server: dict[str, str] = {}
        self._history: list[dict[str, Any]] = []

    async def __aenter__(self) -> "AgentEnv":
        await self._stack.__aenter__()
        try:
            for server in self._load_servers():
                await self._connect_server(server)
        except Exception:
            await self._stack.aclose()
            raise
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: object | None,
    ) -> None:
        self._save_history()
        await self._stack.aclose()

    def _load_servers(self) -> list[MCPServerConfig]:
        config_path = self.config.runtime.mcp_config_file
        if not config_path.is_absolute():
            config_path = self.demo_root / config_path
        with config_path.open(encoding="utf-8") as stream:
            data = json.load(stream)
        if not isinstance(data, list) or not data:
            raise ValueError(
                f"MCP configuration must be a non-empty list: {config_path}"
            )
        return [MCPServerConfig.model_validate(item) for item in data]

    async def _connect_server(self, server: MCPServerConfig) -> None:
        if server.name in self._sessions:
            raise ValueError(f"Duplicate MCP server name: {server.name}")

        command = sys.executable if server.command == "python" else server.command
        args = [self._resolve_arg(arg) for arg in server.args]
        server_env = os.environ.copy()
        server_env.update(server.env)
        server_env.update(
            {
                "WORKSPACE": str(self.workspace),
                "TAVILY_API_KEY": self.config.search.api_key.get_secret_value(),
                "SEARCH_MAX_RESULTS": str(self.config.search.max_results),
                "FASTMCP_LOG_LEVEL": "ERROR",
                "PYTHONDONTWRITEBYTECODE": "1",
            }
        )
        params = StdioServerParameters(
            command=command,
            args=args,
            env=server_env,
            cwd=str(self.demo_root),
        )
        read_stream, write_stream = await self._stack.enter_async_context(
            stdio_client(params)
        )
        session = await self._stack.enter_async_context(
            ClientSession(
                read_stream,
                write_stream,
                read_timeout_seconds=timedelta(seconds=60),
            )
        )
        await session.initialize()
        self._sessions[server.name] = session

        result = await session.list_tools()
        for tool in result.tools:
            if tool.name in self._tools:
                raise ValueError(f"Duplicate MCP tool name: {tool.name}")
            self._tools[tool.name] = {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description or "",
                    "parameters": tool.inputSchema,
                },
            }
            # 建立映射表
            self._tool_to_server[tool.name] = server.name

    def _resolve_arg(self, arg: str) -> str:
        path = Path(arg)
        if path.is_absolute() or not path.suffix:
            return arg
        return str((self.demo_root / path).resolve())

    def get_tools(self, allowed_names: set[str]) -> list[dict[str, Any]]:
        """Return OpenAI tool schemas after validating an agent allowlist."""
        # 查找不存在的tools
        missing = allowed_names - self._tools.keys()
        if missing:
            names = ", ".join(sorted(missing))
            raise ValueError(f"MCP tools are unavailable: {names}")
        return [self._tools[name] for name in sorted(allowed_names)]

    async def call_tool(
        self,
        tool_call_id: str,
        tool_name: str,
        arguments: dict[str, Any],
        allowed_names: set[str],
    ) -> ToolObservation:
        """Execute one authorized MCP tool and normalize its text result."""
        if tool_name not in allowed_names:
            observation = self._error_observation(
                tool_call_id,
                tool_name,
                arguments,
                f"Tool is not allowed for this agent: {tool_name}",
            )
            self._record(observation)
            return observation
            # 查询属于哪个MCP Server
        server_name = self._tool_to_server.get(tool_name)
        if server_name is None:
            observation = self._error_observation(
                tool_call_id,
                tool_name,
                arguments,
                f"Unknown MCP tool: {tool_name}",
            )
            self._record(observation)
            return observation

        try:
            result = await asyncio.wait_for(
                self._sessions[server_name].call_tool(tool_name, arguments),
                timeout=60,
            )
            unsupported = [
                block for block in result.content if not isinstance(block, TextContent)
            ]
            if unsupported:
                raise ValueError("The demo supports text MCP results only")
            text = "\n".join(block.text for block in result.content).strip()
            observation = ToolObservation(
                tool_call_id=tool_call_id,
                tool_name=tool_name,
                text=text,
                is_error=bool(result.isError),
                arguments=arguments,
            )
        except Exception as error:
            observation = self._error_observation(
                tool_call_id,
                tool_name,
                arguments,
                f"Tool execution failed: {error}",
            )

        self._record(observation)
        return observation

    def _error_observation(
        self,
        tool_call_id: str,
        tool_name: str,
        arguments: dict[str, Any],
        message: str,
    ) -> ToolObservation:
        return ToolObservation(
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            text=message,
            is_error=True,
            arguments=arguments,
        )

    def _record(self, observation: ToolObservation) -> None:
        safe_arguments = {
            key: value
            for key, value in observation.arguments.items()
            if "key" not in key.lower() and "token" not in key.lower()
        }
        self._history.append(
            {
                "timestamp": datetime.now(UTC).isoformat(),
                "tool_call_id": observation.tool_call_id,
                "tool_name": observation.tool_name,
                "arguments": safe_arguments,
                "result": observation.text,
                "is_error": observation.is_error,
            }
        )

    def _save_history(self) -> None:
        history_dir = self.workspace / "history"
        history_dir.mkdir(parents=True, exist_ok=True)
        history_file = history_dir / "tool-history.jsonl"
        with history_file.open("w", encoding="utf-8") as stream:
            for entry in self._history:
                stream.write(json.dumps(entry, ensure_ascii=False) + "\n")
