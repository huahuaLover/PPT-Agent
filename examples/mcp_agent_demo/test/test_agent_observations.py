"""Agent observation handling tests."""

from typing import Any

import pytest
from openai.types.chat.chat_completion_message_function_tool_call import (
    ChatCompletionMessageFunctionToolCall,
)

from agent import Agent
from models import ToolImage, ToolObservation


class FakeEnv:
    """Return deterministic observations without starting MCP."""

    async def call_tool(
        self,
        tool_call_id: str,
        tool_name: str,
        arguments: dict[str, Any],
        allowed_names: set[str],
    ) -> ToolObservation:
        images = (
            [ToolImage(mime_type="image/jpeg", data="encoded-image")]
            if tool_name == "inspect_slide"
            else []
        )
        return ToolObservation(
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            text="passed",
            images=images,
            arguments=arguments,
        )


@pytest.mark.asyncio
async def test_tool_messages_precede_visual_feedback() -> None:
    agent = Agent.__new__(Agent)
    agent.chat_history = []
    agent.env = FakeEnv()
    agent.allowed_tools = {"write_file", "inspect_slide"}
    agent.used_tools = set()
    tool_calls = [
        ChatCompletionMessageFunctionToolCall(
            id="one",
            type="function",
            function={"name": "write_file", "arguments": "{}"},
        ),
        ChatCompletionMessageFunctionToolCall(
            id="two",
            type="function",
            function={"name": "inspect_slide", "arguments": "{}"},
        ),
    ]

    await agent.execute(tool_calls)

    assert [message["role"] for message in agent.chat_history] == [
        "tool",
        "tool",
        "user",
    ]
    image_url = agent.chat_history[-1]["content"][1]["image_url"]["url"]
    assert image_url.startswith("data:image/jpeg;base64,")


def test_history_copy_removes_inline_images() -> None:
    agent = Agent.__new__(Agent)
    agent.chat_history = [
        {
            "role": "user",
            "content": [
                {
                    "type": "image_url",
                    "image_url": {"url": "data:image/jpeg;base64,secret"},
                }
            ],
        }
    ]

    history = agent._history_for_disk()

    assert "secret" not in str(history)
