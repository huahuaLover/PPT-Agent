"""Python 3.13-compatible stdio transport for the bundled MCP versions."""

import asyncio
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import anyio
import mcp.types as types
from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream
from mcp.shared.message import SessionMessage


@asynccontextmanager
async def asyncio_stdio_server() -> AsyncIterator[
    tuple[
        MemoryObjectReceiveStream[SessionMessage | Exception],
        MemoryObjectSendStream[SessionMessage],
    ]
]:
    """Read stdin through asyncio because AnyIO file iteration stalls on Python 3.13."""
    incoming_writer, incoming = anyio.create_memory_object_stream[
        SessionMessage | Exception
    ](0)
    outgoing, outgoing_reader = anyio.create_memory_object_stream[SessionMessage](0)

    async def read_stdin() -> None:
        reader = asyncio.StreamReader()
        protocol = asyncio.StreamReaderProtocol(reader)
        loop = asyncio.get_running_loop()
        await loop.connect_read_pipe(lambda: protocol, sys.stdin)
        async with incoming_writer:
            while line := await reader.readline():
                try:
                    message = types.JSONRPCMessage.model_validate_json(line)
                    await incoming_writer.send(SessionMessage(message))
                except Exception as error:
                    await incoming_writer.send(error)

    async def write_stdout() -> None:
        async with outgoing_reader:
            async for session_message in outgoing_reader:
                payload = session_message.message.model_dump_json(
                    by_alias=True,
                    exclude_none=True,
                )
                sys.stdout.write(payload + "\n")
                sys.stdout.flush()

    async with anyio.create_task_group() as task_group:
        task_group.start_soon(read_stdin)
        task_group.start_soon(write_stdout)
        try:
            yield incoming, outgoing
        finally:
            task_group.cancel_scope.cancel()


def install_if_needed() -> None:
    """Patch FastMCP's stdio context only on affected Python versions."""
    if sys.version_info < (3, 13):
        return
    import fastmcp.server.server as fastmcp_server_module

    fastmcp_server_module.stdio_server = asyncio_stdio_server
