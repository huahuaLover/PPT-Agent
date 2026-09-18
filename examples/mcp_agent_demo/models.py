"""Shared data models for the MCP agent demo."""

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, SecretStr, field_validator


Stage = Literal["research", "design", "workflow"]
EventKind = Literal["assistant", "tool", "final"]


class ModelConfig(BaseModel):
    """Configuration for an OpenAI-compatible chat model."""

    base_url: str | None = None
    model: str = Field(min_length=1)
    api_key: SecretStr = Field(min_length=1)
    temperature: float | None = Field(default=0.2, ge=0, le=2)
    max_turns: int = Field(default=10, gt=0)
    max_retries: int = Field(default=3, ge=1, le=5)
    supports_vision: bool = False


class SearchConfig(BaseModel):
    """Configuration passed to the MCP web-search tool."""

    api_key: SecretStr = Field(min_length=1)
    max_results: int = Field(default=5, ge=1, le=10)
    max_content_chars: int = Field(default=1500, ge=300, le=5000)
    max_image_results: int = Field(default=4, ge=1, le=8)


class RuntimeConfig(BaseModel):
    """Local runtime paths, resolved relative to the demo directory."""

    workspace_base: Path = Path("workspace")
    mcp_config_file: Path = Path("mcp.json")
    aspect_ratio: Literal["16:9"] = "16:9"
    max_slide_revisions: int = Field(default=3, ge=1, le=8)
    enable_visual_review: bool = True
    tool_timeout_seconds: int = Field(default=120, ge=30, le=600)
    soft_parsing: bool = False


class AppConfig(BaseModel):
    """Top-level application configuration."""

    research_agent: ModelConfig
    design_agent: ModelConfig
    search: SearchConfig
    runtime: RuntimeConfig = Field(default_factory=RuntimeConfig)

    @classmethod
    def load(cls, path: Path) -> "AppConfig":
        """Load and validate a YAML configuration file."""
        with path.open(encoding="utf-8") as stream:
            data = yaml.safe_load(stream)
        if not isinstance(data, dict):
            raise ValueError(f"Configuration must be a YAML object: {path}")
        return cls.model_validate(data)


class InputRequest(BaseModel):
    """User input for one presentation generation task."""

    prompt: str = Field(min_length=1)
    pages: int = Field(default=5, ge=2, le=20)
    language: Literal["zh", "en"] = "zh"

    @field_validator("prompt")
    @classmethod
    def strip_prompt(cls, value: str) -> str:
        """Reject prompts containing only whitespace."""
        value = value.strip()
        if not value:
            raise ValueError("Prompt cannot be empty")
        return value


class MCPServerConfig(BaseModel):
    """Configuration for one stdio MCP server."""

    name: str = Field(min_length=1)
    command: str = Field(min_length=1)
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)


class RoleConfig(BaseModel):
    """Prompt and tool policy for one agent role."""

    system: dict[Literal["zh", "en"], str]
    instruction: str
    use_model: Literal["research_agent", "design_agent"]
    tools: list[str]

    @classmethod
    def load(cls, path: Path) -> "RoleConfig":
        """Load and validate a role YAML file."""
        with path.open(encoding="utf-8") as stream:
            data = yaml.safe_load(stream)
        if not isinstance(data, dict):
            raise ValueError(f"Role configuration must be a YAML object: {path}")
        return cls.model_validate(data)


class AgentEvent(BaseModel):
    """A typed event emitted by an agent or the workflow."""

    kind: EventKind
    stage: Stage
    agent: str
    content: str
    tool_name: str | None = None
    is_error: bool = False


class ToolImage(BaseModel):
    """An image returned by an MCP tool."""

    mime_type: str
    data: str


class ToolObservation(BaseModel):
    """A normalized result returned by AgentEnv."""

    tool_call_id: str
    tool_name: str
    text: str
    images: list[ToolImage] = Field(default_factory=list)
    is_error: bool = False
    arguments: dict[str, Any] = Field(default_factory=dict)


class ExportResult(BaseModel):
    """Artifacts produced by the deterministic HTML export step."""

    final_path: Path
    pptx_path: Path | None
    pdf_path: Path
    preview_dir: Path
    pptx_error: str | None = None
