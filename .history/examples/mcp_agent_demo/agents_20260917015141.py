"""Concrete Research and Design agents."""

from collections.abc import AsyncGenerator
from pathlib import Path

from agent import Agent, Language
from env import AgentEnv
from models import AgentEvent, AppConfig, InputRequest


class Research(Agent):
    """Search for real sources and write a slide manuscript."""

    def __init__(
        self,
        config: AppConfig,
        env: AgentEnv,
        workspace: Path,
        language: Language,
        role_file: Path,
    ) -> None:
        super().__init__(
            name="Research",
            stage="research",
            config=config,
            env=env,
            workspace=workspace,
            language=language,
            role_file=role_file,
            expected_suffix=".md",
            required_tools_before_finalize={"search_web", "write_file"},
        )

    async def loop(
        self,
        request: InputRequest,
    ) -> AsyncGenerator[AgentEvent, None]:
    # 在这里面进行调用
        async for event in self.run_tool_loop(
            {
                "prompt": request.prompt,
                "pages": request.pages,
                "language": request.language,
            }
        ):
            yield event


class Design(Agent):
    """Turn a manuscript into a structured and readable PowerPoint."""

    def __init__(
        self,
        config: AppConfig,
        env: AgentEnv,
        workspace: Path,
        language: Language,
        role_file: Path,
    ) -> None:
        super().__init__(
            name="Design",
            stage="design",
            config=config,
            env=env,
            workspace=workspace,
            language=language,
            role_file=role_file,
            expected_suffix=".pptx",
            required_tools_before_finalize={"read_file", "write_file", "create_pptx"},
        )

    async def loop(
        self,
        request: InputRequest,
        manuscript_path: Path,
    ) -> AsyncGenerator[AgentEvent, None]:
        async for event in self.run_tool_loop(
            {
                "prompt": request.prompt,
                "pages": request.pages,
                "language": request.language,
                "manuscript_path": manuscript_path.as_posix(),
            }
        ):
            yield event
