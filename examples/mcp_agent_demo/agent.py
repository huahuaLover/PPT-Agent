"""A small, explicit tool-calling agent implementation."""

import asyncio
import copy
import json
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from jinja2 import StrictUndefined, Template
from openai import APIConnectionError, APIStatusError, APITimeoutError, AsyncOpenAI
from openai.types.chat import ChatCompletionMessage
from openai.types.chat.chat_completion_message_function_tool_call import (
    ChatCompletionMessageFunctionToolCall,
)

from env import AgentEnv
from models import AgentEvent, AppConfig, RoleConfig, Stage, ToolObservation


class Agent:
    """Base class for an LLM agent that can call MCP tools."""

    def __init__(
        self,
        name: str,
        stage: Stage,
        config: AppConfig,
        env: AgentEnv,
        workspace: Path,
        language: Literal["zh", "en"],
        role_file: Path,
        expected_outcome_name: str,
        expected_outcome_kind: Literal["file", "directory"],
        expected_suffix: str | None,
        required_tools_before_finalize: set[str],
    ) -> None:
        self.name = name
        self.stage = stage
        self.config = config
        self.env = env
        self.workspace = workspace.resolve()
        self.language = language
        self.expected_outcome_name = expected_outcome_name
        self.expected_outcome_kind = expected_outcome_kind
        self.expected_suffix = expected_suffix
        self.required_tools_before_finalize = required_tools_before_finalize
        self.turn_count = 0
        self.used_tools: set[str] = set()
        self.usage: dict[str, int] = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        }

        role = RoleConfig.load(role_file)
        self.model_config = getattr(config, role.use_model)
        self.prompt = Template(role.instruction, undefined=StrictUndefined)
        self.allowed_tools = set(role.tools)
        self.tools = env.get_tools(self.allowed_tools)
        self.chat_history: list[dict[str, Any]] = [
            {"role": "system", "content": role.system[language]}
        ]
        client_kwargs: dict[str, Any] = {
            "api_key": self.model_config.api_key.get_secret_value(),
            "max_retries": 0,
            "timeout": 120,
        }
        if self.model_config.base_url:
            client_kwargs["base_url"] = self.model_config.base_url
        self.client = AsyncOpenAI(**client_kwargs)

    async def action(self, **prompt_context: object) -> ChatCompletionMessage:
        """Ask the model to select the next MCP tool calls."""
        self.turn_count += 1
        if self.turn_count > self.model_config.max_turns:
            raise RuntimeError(
                f"{self.name} exceeded max turns: {self.model_config.max_turns}"
            )
        if len(self.chat_history) == 1:
            self.chat_history.append(
                {
                    "role": "user",
                    "content": self.prompt.render(**prompt_context),
                }
            )
        request: dict[str, Any] = {
            "model": self.model_config.model,
            "messages": self.chat_history,
            "tools": self.tools,
            "tool_choice": "auto",
        }
        if self.model_config.temperature is not None:
            request["temperature"] = self.model_config.temperature

        response = await self._request_model(request)
        if not response.choices:
            raise RuntimeError(f"{self.name} model returned no choices")
        message = response.choices[0].message
        self._append_assistant_message(message)
        self._update_usage(response.usage)
        if not message.tool_calls:
            raise RuntimeError(
                f"{self.name} model returned no tool calls. "
                "Use a model that supports Chat Completions Tool Calling."
            )
        return message

    async def _request_model(self, request: dict[str, Any]) -> Any:
        """Call the model with bounded retries for transient failures."""
        for attempt in range(1, self.model_config.max_retries + 1):
            try:
                return await self.client.chat.completions.create(**request)
            except (APIConnectionError, APITimeoutError, APIStatusError) as error:
                self._record_model_error(error, attempt)
                if attempt == self.model_config.max_retries or not self._retryable(
                    error
                ):
                    raise
                await asyncio.sleep(min(2 ** (attempt - 1), 8))
        raise RuntimeError("Model request retry loop exited unexpectedly")

    @staticmethod
    def _retryable(error: Exception) -> bool:
        if isinstance(error, (APIConnectionError, APITimeoutError)):
            return True
        return isinstance(error, APIStatusError) and error.status_code in {
            429,
            500,
            502,
            503,
            504,
        }

    def _record_model_error(self, error: Exception, attempt: int) -> None:
        """Persist a redacted model error without storing request secrets."""
        history_dir = self.workspace / "history"
        history_dir.mkdir(parents=True, exist_ok=True)
        status_code = getattr(error, "status_code", None)
        message = str(error)
        for model in (self.config.research_agent, self.config.design_agent):
            message = message.replace(model.api_key.get_secret_value(), "***")
        entry = {
            "timestamp": datetime.now(UTC).isoformat(),
            "agent": self.name,
            "attempt": attempt,
            "error_type": type(error).__name__,
            "status_code": status_code,
            "message": message[:2000],
        }
        with (history_dir / "run-errors.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(entry, ensure_ascii=False) + "\n")

    async def execute(
        self,
        tool_calls: list[ChatCompletionMessageFunctionToolCall],
    ) -> tuple[list[ToolObservation], str | None]:
        """Execute tool calls in order and detect a successful finalize call."""
        observations: list[ToolObservation] = []
        final_path: str | None = None

        for tool_call in tool_calls:
            tool_name = tool_call.function.name
            try:
                raw_arguments = tool_call.function.arguments or "{}"
                arguments = json.loads(raw_arguments)
                if not isinstance(arguments, dict):
                    raise ValueError("Tool arguments must be a JSON object")
                if tool_name == "finalize":
                    self._validate_finalize_arguments(arguments)
            except (json.JSONDecodeError, ValueError) as error:
                observation = ToolObservation(
                    tool_call_id=tool_call.id,
                    tool_name=tool_name,
                    text=f"Invalid tool arguments: {error}",
                    is_error=True,
                )
            else:
                observation = await self.env.call_tool(
                    tool_call.id,
                    tool_name,
                    arguments,
                    self.allowed_tools,
                )

            if not observation.is_error:
                self.used_tools.add(tool_name)
            if tool_name == "finalize" and not observation.is_error:
                try:
                    final_path = self._validate_final_path(observation.text)
                except RuntimeError as error:
                    observation.is_error = True
                    observation.text = f"Finalize rejected: {error}"
                    final_path = None

            observations.append(observation)

        for observation in observations:
            self.chat_history.append(
                {
                    "role": "tool",
                    "tool_call_id": observation.tool_call_id,
                    "content": observation.text or "Tool completed.",
                }
            )
        for observation in observations:
            self._append_observation_images(observation)

        return observations, final_path

    def _append_observation_images(self, observation: ToolObservation) -> None:
        """Add rendered slide previews to the next model request."""
        if not observation.images:
            return
        content: list[dict[str, Any]] = [
            {
                "type": "text",
                "text": (
                    "Rendered preview from inspect_slide. Review hierarchy, spacing, "
                    "clipping, overlap, contrast, and image cropping. Fix the HTML and "
                    "inspect it again if needed."
                ),
            }
        ]
        for image in observation.images:
            content.append(
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{image.mime_type};base64,{image.data}"},
                }
            )
        self.chat_history.append({"role": "user", "content": content})

    def _validate_finalize_arguments(self, arguments: dict[str, Any]) -> None:
        """Require finalize to receive only the expected artifact path."""
        outcome = arguments.get("outcome")
        if not isinstance(outcome, str) or not outcome.strip():
            raise ValueError("finalize outcome must be a non-empty file path")
        if "\n" in outcome or len(outcome) > 512:
            raise ValueError(
                "finalize outcome must contain only a file path, not a summary"
            )
        if outcome != self.expected_outcome_name:
            raise ValueError(
                f"finalize outcome must be exactly {self.expected_outcome_name}"
            )
        if self.expected_outcome_kind == "directory":
            expected_pages = arguments.get("expected_pages")
            if not isinstance(expected_pages, int):
                raise ValueError("Design finalize requires integer expected_pages")

    async def run_tool_loop(
        self,
        prompt_context: dict[str, object],
    ) -> AsyncGenerator[AgentEvent, None]:
        """Run action/execute iterations until finalize succeeds."""
        while True:
            message = await self.action(**prompt_context)
            tool_names = [call.function.name for call in message.tool_calls or []]
            summary = message.content or f"Requested tools: {', '.join(tool_names)}"
            yield AgentEvent(
                kind="assistant",
                stage=self.stage,
                agent=self.name,
                content=summary,
            )

            observations, final_path = await self.execute(message.tool_calls or [])
            for observation in observations:
                yield AgentEvent(
                    kind="tool",
                    stage=self.stage,
                    agent=self.name,
                    content=observation.text,
                    tool_name=observation.tool_name,
                    is_error=observation.is_error,
                )
            if final_path is not None:
                yield AgentEvent(
                    kind="final",
                    stage=self.stage,
                    agent=self.name,
                    content=final_path,
                )
                return

    def save_history(self) -> None:
        """Write this agent's messages and token usage to the task workspace."""
        history_dir = self.workspace / "history"
        history_dir.mkdir(parents=True, exist_ok=True)
        history_file = history_dir / f"{self.name}-history.jsonl"
        with history_file.open("w", encoding="utf-8") as stream:
            for message in self._history_for_disk():
                entry = {
                    "timestamp": datetime.now(UTC).isoformat(),
                    "message": message,
                }
                stream.write(json.dumps(entry, ensure_ascii=False) + "\n")

        usage_file = history_dir / f"{self.name}-usage.json"
        usage_file.write_text(
            json.dumps(self.usage, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _history_for_disk(self) -> list[dict[str, Any]]:
        """Return a history copy with inline image data removed."""
        history = copy.deepcopy(self.chat_history)

        def sanitize(value: Any) -> Any:
            if isinstance(value, str) and value.startswith("data:image/"):
                return "<image omitted; see workspace previews>"
            if isinstance(value, list):
                return [sanitize(item) for item in value]
            if isinstance(value, dict):
                return {key: sanitize(item) for key, item in value.items()}
            return value

        return sanitize(history)

    def _append_assistant_message(self, message: ChatCompletionMessage) -> None:
        assistant: dict[str, Any] = {
            "role": "assistant",
            "content": message.content,
        }
        if message.tool_calls:
            assistant["tool_calls"] = [
                tool_call.model_dump(exclude_none=True)
                for tool_call in message.tool_calls
            ]
        self.chat_history.append(assistant)

    def _update_usage(self, usage: Any) -> None:
        if usage is None:
            return
        self.usage["prompt_tokens"] += usage.prompt_tokens
        self.usage["completion_tokens"] += usage.completion_tokens
        self.usage["total_tokens"] += usage.total_tokens

    def _validate_final_path(self, raw_path: str) -> str:
        missing = self.required_tools_before_finalize - self.used_tools
        if missing:
            names = ", ".join(sorted(missing))
            raise RuntimeError(
                f"{self.name} called finalize before required tools: {names}"
            )

        path = Path(raw_path)
        candidate = (
            path.resolve() if path.is_absolute() else (self.workspace / path).resolve()
        )
        if not candidate.is_relative_to(self.workspace):
            raise RuntimeError(f"Final path is outside workspace: {raw_path}")
        if self.expected_outcome_kind == "file":
            valid = candidate.is_file() and candidate.stat().st_size > 0
            valid = valid and candidate.suffix.lower() == self.expected_suffix
        else:
            valid = candidate.is_dir()
        if not valid:
            raise RuntimeError(
                f"{self.name} returned an invalid {self.expected_outcome_kind}: "
                f"{raw_path}"
            )
        return str(candidate)


Language = Literal["zh", "en"]
