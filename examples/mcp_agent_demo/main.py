"""Command-line entry point and explicit two-agent workflow."""

import argparse
import asyncio
import json
import shutil
import uuid
from collections.abc import AsyncGenerator, Sequence
from pathlib import Path

from agents import Design, Research
from conversion import export_slides
from env import AgentEnv
from models import AgentEvent, AppConfig, InputRequest


DEMO_ROOT = Path(__file__).resolve().parent


class AgentLoop:
    """Run Research and Design in a fixed, inspectable order."""

    def __init__(self, config: AppConfig, workspace: Path) -> None:
        self.config = config
        self.workspace = workspace.resolve()
        self.intermediate_output: dict[str, str] = {}

    async def run(
        self,
        request: InputRequest,
    ) -> AsyncGenerator[AgentEvent, None]:
        self.workspace.mkdir(parents=True, exist_ok=False)
        (self.workspace / "history").mkdir()
        self._write_json("request.json", request.model_dump())

        async with AgentEnv(self.workspace, self.config, DEMO_ROOT) as env:
            research = Research(
                config=self.config,
                env=env,
                workspace=self.workspace,
                language=request.language,
                role_file=DEMO_ROOT / "roles" / "Research.yaml",
            )
            manuscript_path: Path | None = None
            try:
                async for event in research.loop(request):
                    if event.kind == "final":
                        manuscript_path = Path(event.content)
                        self.intermediate_output["manuscript"] = event.content
                    yield event
            finally:
                research.save_history()

            if manuscript_path is None:
                raise RuntimeError("Research finished without a manuscript")
            self._write_json("intermediate_output.json", self.intermediate_output)

            design = Design(
                config=self.config,
                env=env,
                workspace=self.workspace,
                language=request.language,
                role_file=DEMO_ROOT / "roles" / "Design.yaml",
            )
            slides_dir: Path | None = None
            try:
                async for event in design.loop(request, manuscript_path):
                    if event.kind == "final":
                        slides_dir = Path(event.content)
                        self.intermediate_output["slides_dir"] = event.content
                    yield event
            finally:
                design.save_history()

        if slides_dir is None:
            raise RuntimeError("Design finished without an inspected slides directory")
        export = await export_slides(
            slides_dir=slides_dir,
            workspace=self.workspace,
            expected_pages=request.pages,
            aspect_ratio=self.config.runtime.aspect_ratio,
            soft_parsing=self.config.runtime.soft_parsing,
        )
        self.intermediate_output.update(
            {
                "preview_dir": str(export.preview_dir),
                "pdf": str(export.pdf_path),
                "final": str(export.final_path),
            }
        )
        if export.pptx_path is not None:
            self.intermediate_output["pptx"] = str(export.pptx_path)
        if export.pptx_error is not None:
            self.intermediate_output["pptx_error"] = export.pptx_error
        self._write_json("intermediate_output.json", self.intermediate_output)
        yield AgentEvent(
            kind="final",
            stage="workflow",
            agent="AgentLoop",
            content=str(export.final_path),
        )

    def _write_json(self, filename: str, data: object) -> None:
        path = self.workspace / filename
        path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Generate slides with two real LLM agents and MCP tools."
    )
    parser.add_argument("prompt", help="Presentation topic or instruction")
    parser.add_argument("--pages", type=int, default=5, help="Total slides (2-20)")
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Optional path for an additional copy of the final artifact",
    )
    parser.add_argument(
        "--language",
        choices=("zh", "en"),
        default="zh",
        help="Presentation language",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=DEMO_ROOT / "config.yaml",
        help="YAML configuration path",
    )
    return parser.parse_args(argv)


def resolve_runtime_paths(config: AppConfig) -> None:
    """Resolve runtime paths relative to the demo, not the shell directory."""
    if not config.runtime.workspace_base.is_absolute():
        config.runtime.workspace_base = DEMO_ROOT / config.runtime.workspace_base
    if not config.runtime.mcp_config_file.is_absolute():
        config.runtime.mcp_config_file = DEMO_ROOT / config.runtime.mcp_config_file


def print_event(event: AgentEvent) -> None:
    """Print a compact event without dumping large tool results."""
    label = event.agent
    if event.kind == "tool":
        detail = "error" if event.is_error else "done"
        print(f"[{label}] tool {event.tool_name}: {detail}")
    elif event.kind == "final":
        print(f"[{label}] final: {event.content}")
    else:
        one_line = " ".join(event.content.split())
        print(f"[{label}] {one_line[:160]}")


async def run_cli(args: argparse.Namespace) -> Path:
    """Execute the workflow and optionally copy its workspace artifact."""
    config_path = args.config.resolve()
    if not config_path.is_file():
        raise FileNotFoundError(
            f"Configuration not found: {config_path}. Copy config.yaml.example to config.yaml."
        )
    config = AppConfig.load(config_path)
    resolve_runtime_paths(config)
    request = InputRequest(
        prompt=args.prompt,
        pages=args.pages,
        language=args.language,
    )

    session_id = uuid.uuid4().hex[:8]
    workspace = config.runtime.workspace_base / session_id
    loop = AgentLoop(config, workspace)
    final_path: Path | None = None
    async for event in loop.run(request):
        if event.stage == "workflow" and event.kind == "final":
            final_path = Path(event.content)
        else:
            print_event(event)

    if final_path is None:
        raise RuntimeError("Workflow did not return a final artifact")
    output_path = final_path.resolve()
    if args.output is not None:
        output_path = args.output.resolve()
        if output_path.suffix.lower() != final_path.suffix.lower():
            raise ValueError(
                f"Output suffix must be {final_path.suffix} for the generated artifact"
            )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        if output_path != final_path.resolve():
            shutil.copy2(final_path, output_path)
    print(f"[Workflow] output: {output_path}")
    print(f"[Workflow] workspace: {workspace}")
    return output_path


def main() -> None:
    """Synchronous CLI wrapper."""
    args = parse_args()
    try:
        asyncio.run(run_cli(args))
    except KeyboardInterrupt:
        print("Interrupted.")
        raise SystemExit(130) from None
    except Exception as error:
        print(f"Error: {error}")
        raise SystemExit(1) from error


if __name__ == "__main__":
    main()
