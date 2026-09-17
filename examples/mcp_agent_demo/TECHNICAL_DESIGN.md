# MCP Agent PPT Demo 技术设计文档

## 1. 文档目的

本文档是 `REQUIREMENTS.md` 的实现说明。实现者应当能够仅依据本文档，在 `examples/mcp_agent_demo/` 中完成一个可运行的 Demo。

Demo 使用真实大模型和真实 Tavily 搜索，通过 stdio MCP Server 暴露全部业务工具，最终生成可打开的 PPTX 文件。

本文档以仓库当前依赖和本地已安装接口为基准：

- Python `>=3.11`
- `openai>=1.108.2`
- `fastmcp>=2.10.0,<2.14.0`，当前环境为 `2.13.3`
- `mcp>=1.14.0`
- `tavily-python>=0.7.14`
- `python-pptx>=0.6.21`
- Pydantic 2

模型调用固定使用 OpenAI 兼容的 Chat Completions Tool Calling 接口。不要在首版中混用 Responses API。

## 2. 设计原则

1. 保留 DeepPresenter 的核心结构，删除与学习目标无关的兼容代码。
2. 工作流由 Python 显式编排，模型不能跳过 Research 或 Design。
3. 模型只负责决策和生成参数，文件访问与 PPTX 创建由 MCP 工具执行。
4. 所有业务工具都经由 MCP 调用，不提供绕过 MCP 的本地工具通道。
5. Research 和 Design 通过工作区文件交接，不直接共享复杂内存对象。
6. 首版优先保证可读、可调试和可运行，不追求复杂视觉效果。
7. API Key 只保存在被 Git 忽略的本地配置中，不写入日志或输出文件。

## 3. 系统架构

```text
CLI
  │
  ▼
AgentLoop
  ├── 创建 workspace/<session-id>/
  ├── 启动 AgentEnv
  │      │
  │      ├── stdio 启动 FastMCP Server
  │      ├── MCP initialize
  │      └── list_tools → OpenAI tool schemas
  │
  ├── Research Agent
  │      ├── action() → OpenAI Chat Completions
  │      ├── execute() → MCP call_tool
  │      └── finalize → manuscript.md
  │
  └── Design Agent
         ├── action() → OpenAI Chat Completions
         ├── execute() → MCP call_tool
         └── finalize → result.pptx
```

完整数据流：

```text
InputRequest
  → Research Prompt
  → search_web observations
  → manuscript.md
  → Design Prompt
  → slides.json
  → create_pptx
  → result.pptx
```

## 4. 目录结构

实现完成后的目录必须为：

```text
examples/mcp_agent_demo/
├── README.md
├── REQUIREMENTS.md
├── TECHNICAL_DESIGN.md
├── requirements.txt
├── config.yaml.example
├── mcp.json
├── main.py
├── agent.py
├── agents.py
├── env.py
├── models.py
├── roles/
│   ├── Research.yaml
│   └── Design.yaml
└── tools/
    ├── server.py
    └── stdio_compat.py
```

各文件职责：

| 文件 | 职责 |
|---|---|
| `main.py` | CLI、配置加载、`AgentLoop` 和最终文件复制 |
| `models.py` | Pydantic 配置模型、请求模型和 Agent 事件模型 |
| `agent.py` | 通用 Agent、真实模型调用、工具执行循环和历史保存 |
| `agents.py` | Research、Design 两个具体 Agent |
| `env.py` | stdio MCP 生命周期、工具发现、Schema 转换和工具调用 |
| `tools/server.py` | FastMCP Server 与五个业务工具 |
| `tools/stdio_compat.py` | Python 3.13 下的 stdio 读取兼容层 |
| `roles/*.yaml` | 角色提示词和工具白名单 |
| `mcp.json` | MCP Server 启动配置 |
| `config.yaml.example` | 模型与运行配置样例 |

Demo 文件之间使用同目录绝对导入：

```python
from agent import Agent
from agents import Research, Design
from env import AgentEnv
from models import AppConfig, InputRequest
```

运行入口必须是 `main.py`，不要求将 Demo 制作为 Python 包。

## 5. 配置设计

### 5.1 `config.yaml.example`

内容：

```yaml
research_agent:
  base_url: "https://your-openai-compatible-endpoint/v1"
  model: "your-research-model"
  api_key: "your-key"
  temperature: 0.2
  max_turns: 10

design_agent:
  base_url: "https://your-openai-compatible-endpoint/v1"
  model: "your-design-model"
  api_key: "your-key"
  temperature: 0.2
  max_turns: 10

search:
  api_key: "your-tavily-key"
  max_results: 5

runtime:
  workspace_base: "workspace"
  mcp_config_file: "mcp.json"
```

规则：

- 用户将该文件复制为 `config.yaml` 后填写两套模型配置。
- `base_url: null` 表示使用 OpenAI SDK 默认地址。
- OpenAI 兼容服务可以设置自己的 `base_url`。
- 模型 `api_key` 保存在被 Git 忽略的本地 `config.yaml` 中。
- Research 和 Design 可以使用不同模型。
- `max_turns` 必须大于 0。
- `temperature` 可以为 `null`；为 `null` 时不向兼容服务传该参数。

### 5.2 配置模型

在 `models.py` 定义：

```python
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, SecretStr


class ModelConfig(BaseModel):
    base_url: str | None = None
    model: str
    api_key: SecretStr
    temperature: float | None = 0.2
    max_turns: int = Field(default=10, gt=0)


class SearchConfig(BaseModel):
    api_key: SecretStr
    max_results: int = Field(default=5, ge=1, le=10)


class RuntimeConfig(BaseModel):
    workspace_base: Path = Path("workspace")
    mcp_config_file: Path = Path("mcp.json")


class AppConfig(BaseModel):
    research_agent: ModelConfig
    design_agent: ModelConfig
    search: SearchConfig
    runtime: RuntimeConfig = Field(default_factory=RuntimeConfig)


class InputRequest(BaseModel):
    prompt: str = Field(min_length=1)
    pages: int = Field(default=5, ge=2, le=20)
    language: Literal["zh", "en"] = "zh"
```

所有相对配置路径都相对于 `examples/mcp_agent_demo/` 解析，而不是相对于调用命令时的当前目录解析。

### 5.3 `mcp.json`

内容：

```json
[
  {
    "name": "demo_tools",
    "command": "python",
    "args": ["tools/server.py"]
  }
]
```

首版只允许配置一个 Server。`env.py` 读取到 `command == "python"` 时，必须替换为 `sys.executable`，保证 MCP Server 使用与主程序相同的虚拟环境。

## 6. 数据模型与内部协议

### 6.1 对话历史

Agent 内部使用 OpenAI Chat Completions 接受的字典格式保存历史：

```python
chat_history: list[dict[str, object]]
```

四种消息格式：

```python
{"role": "system", "content": "You are ..."}

{"role": "user", "content": "Create ..."}

{
    "role": "assistant",
    "content": None,
    "tool_calls": [
        {
            "id": "call_123",
            "type": "function",
            "function": {
                "name": "search_web",
                "arguments": "{\"query\": \"...\"}"
            }
        }
    ]
}

{
    "role": "tool",
    "tool_call_id": "call_123",
    "content": "tool result"
}
```

不要自创消息字段传给模型。保存日志时可以额外包裹时间戳，但传给 SDK 的消息必须只包含 API 接受的字段。

### 6.2 Agent 事件

为避免主项目中使用 `str` 区分进度和结果的隐式协议，在 `models.py` 增加：

```python
class AgentEvent(BaseModel):
    kind: Literal["assistant", "tool", "final"]
    stage: Literal["research", "design", "workflow"]
    agent: str
    content: str
    tool_name: str | None = None
    is_error: bool = False
```

具体 Agent 的 `loop()` 返回异步生成器：

```python
AsyncGenerator[AgentEvent, None]
```

约定：

- `assistant`：模型本轮回复或工具决策摘要。
- `tool`：MCP 工具执行结果。
- `final`：阶段最终文件的绝对路径。

`AgentLoop` 只根据 `event.kind` 判断状态，不能通过 `isinstance(..., str)` 判断。

### 6.3 工具调用结果

在 `models.py` 定义内部结果：

```python
class ToolObservation(BaseModel):
    tool_call_id: str
    tool_name: str
    text: str
    is_error: bool = False
```

`AgentEnv.call_tool()` 返回 `ToolObservation`，避免 MCP 类型渗透到 Agent 业务层。

## 7. MCP Client 设计

### 7.1 生命周期

`env.py` 实现：

```python
class AgentEnv:
    def __init__(self, workspace: Path, mcp_config_file: Path): ...
    async def __aenter__(self) -> "AgentEnv": ...
    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None: ...
    def get_tools(self, allowed_names: set[str]) -> list[dict]: ...
    async def call_tool(...) -> ToolObservation: ...
```

`AgentLoop` 必须这样使用：

```python
async with AgentEnv(workspace, mcp_config_file) as env:
    # Run Research and Design.
```

### 7.2 stdio 连接

使用仓库当前已使用并验证的 MCP 低层接口：

```python
from contextlib import AsyncExitStack

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
```

`__aenter__()` 的实现顺序必须是：

```python
self._stack = AsyncExitStack()
await self._stack.__aenter__()

params = StdioServerParameters(
    command=resolved_command,
    args=resolved_args,
    env=server_env,
)
read_stream, write_stream = await self._stack.enter_async_context(
    stdio_client(params)
)
self._session = await self._stack.enter_async_context(
    ClientSession(read_stream, write_stream)
)
await self._session.initialize()
tool_result = await self._session.list_tools()
```

`server_env` 必须从 `os.environ.copy()` 开始，并加入：

```python
{
    "WORKSPACE": str(workspace.resolve()),
    "TAVILY_API_KEY": config.search.api_key.get_secret_value(),
    "SEARCH_MAX_RESULTS": str(config.search.max_results),
    "FASTMCP_LOG_LEVEL": "ERROR",
}
```

注意：需求中的 `AgentEnv` 构造参数需要增加 `search_config`，或者由调用者传入完整的 `AppConfig`。推荐直接传 `AppConfig`，减少散落参数。

`resolved_args` 中类似 `tools/server.py` 的相对路径必须相对于 Demo 根目录解析为绝对路径。

`__aexit__()` 调用：

```python
await self._stack.aclose()
```

并将工具历史保存为：

```text
workspace/<session-id>/history/tool-history.jsonl
```

### 7.3 MCP Tool → OpenAI Tool 转换

`list_tools()` 返回的每个 MCP Tool 包含：

- `name`
- `description`
- `inputSchema`

转换为 Chat Completions 工具格式：

```python
openai_tool = {
    "type": "function",
    "function": {
        "name": mcp_tool.name,
        "description": mcp_tool.description or "",
        "parameters": mcp_tool.inputSchema,
    },
}
```

AgentEnv 保存：

```python
self._tools: dict[str, dict[str, object]]
```

工具名称必须唯一。发现重名时立即抛出 `ValueError`。

### 7.4 工具白名单

```python
def get_tools(self, allowed_names: set[str]) -> list[dict]:
```

行为：

1. 检查每个允许的工具都已由 MCP Server 注册。
2. 缺失时抛出包含工具名的 `ValueError`。
3. 只返回允许工具的 OpenAI Schema。

模型即使伪造一个未授权工具调用，`call_tool()` 也必须再次检查白名单。不能只依赖“模型看不到该工具”。

### 7.5 MCP 工具调用

调用接口：

```python
result = await self._session.call_tool(tool_name, arguments)
```

处理规则：

1. `arguments` 必须是字典。
2. 使用 `asyncio.wait_for()` 设置 60 秒超时。
3. 首版只接受 MCP `TextContent`。
4. 多个文本块使用换行拼接。
5. `result.isError` 写入 `ToolObservation.is_error`。
6. 工具异常转成错误 observation，让模型有机会修正。
7. MCP 会话未初始化属于程序错误，应直接抛出 `RuntimeError`。

不能把 API Key、完整环境变量或敏感请求头写入工具历史。

## 8. FastMCP Server 设计

### 8.1 服务入口

`tools/server.py`：

```python
from fastmcp import FastMCP

mcp = FastMCP("MCP Agent Demo Tools")

# @mcp.tool() definitions

if __name__ == "__main__":
    mcp.run(transport="stdio", show_banner=False)
```

必须关闭 banner。stdio 协议不能混入普通标准输出；诊断信息应输出到标准错误或使用 logging。

仓库当前 Python 3.13 环境中的 AnyIO 文件迭代无法消费 MCP Server 的 stdin。`stdio_compat.py` 仅在 Python 3.13 及以上使用 asyncio pipe 替换 Server 侧的 stdin/stdout 读取；Python 3.11、3.12 保持 FastMCP 默认传输。该兼容层不修改 MCP 消息格式、工具注册或客户端接口。

### 8.2 工作区路径保护

Server 启动时读取：

```python
WORKSPACE = Path(os.environ["WORKSPACE"]).resolve()
```

统一使用：

```python
def resolve_workspace_path(raw_path: str) -> Path:
    path = Path(raw_path)
    candidate = path.resolve() if path.is_absolute() else (WORKSPACE / path).resolve()
    if not candidate.is_relative_to(WORKSPACE):
        raise ValueError(f"Path is outside workspace: {raw_path}")
    return candidate
```

所有文件工具必须调用该函数。不能只检查字符串中是否包含 `..`，因为符号链接和绝对路径仍可能绕过字符串检查。

### 8.3 `search_web`

签名：

```python
@mcp.tool()
async def search_web(query: str, max_results: int = 5) -> str:
    """Search the web and return concise results with source URLs."""
```

实现要求：

1. `query.strip()` 不能为空。
2. `max_results` 限制在 1～10，并且不得超过 `SEARCH_MAX_RESULTS`。
3. 从 MCP 客户端传入的 `TAVILY_API_KEY` 子进程环境变量读取密钥；用户无需手动设置环境变量。
4. 使用 `TavilyClient(api_key=key)`。
5. Tavily Client 是同步接口，使用 `asyncio.to_thread()`，避免阻塞事件循环。

调用形态：

```python
response = await asyncio.to_thread(
    client.search,
    query=query,
    search_depth="basic",
    max_results=effective_max_results,
    include_answer=False,
    include_raw_content=False,
)
```

返回 JSON 字符串，只保留：

```json
{
  "query": "...",
  "results": [
    {
      "title": "...",
      "url": "https://...",
      "content": "..."
    }
  ]
}
```

每条 `content` 最多保留 1000 个字符。使用 `json.dumps(..., ensure_ascii=False)` 返回，不能返回 Python 字典的 `repr()`。

### 8.4 `read_file`

签名：

```python
@mcp.tool()
def read_file(path: str) -> str:
    """Read a UTF-8 text file from the task workspace."""
```

行为：

- 路径必须位于工作区。
- 文件必须存在且为普通文件。
- 使用 UTF-8 读取。
- 首版最大读取 200,000 字符，超过时抛出明确错误。

### 8.5 `write_file`

签名：

```python
@mcp.tool()
def write_file(path: str, content: str) -> str:
    """Write UTF-8 text to a file inside the task workspace."""
```

行为：

- 路径必须位于工作区。
- 自动创建父目录。
- 使用 UTF-8 覆盖写入。
- 返回相对于工作区的 POSIX 路径，例如 `manuscript.md`。
- 空内容允许写入，但 Research/Design Prompt 必须要求生成非空产物。

### 8.6 `create_pptx`

签名：

```python
@mcp.tool()
def create_pptx(
    spec_path: str,
    expected_pages: int,
    output_path: str = "result.pptx",
) -> str:
    """Create a basic PowerPoint from a JSON slide specification."""
```

输入 JSON：

```json
{
  "title": "演示文稿标题",
  "slides": [
    {
      "title": "页面标题",
      "bullets": ["要点一", "要点二"],
      "notes": "可选备注"
    }
  ]
}
```

校验要求：

- 根节点必须是对象。
- `title` 必须是非空字符串。
- `slides` 必须是包含 1～19 个元素的列表；加上标题页后，最终总页数为 2～20。
- 每页 `title` 必须是非空字符串。
- `bullets` 必须是字符串列表，每页最多 8 条。
- 单条 bullet 建议不超过 300 字符；超过则截断并在末尾添加 `…`。
- `output_path` 后缀必须是 `.pptx`。
- `expected_pages` 必须为 2～20，且必须等于 `len(slides) + 1`。
- `spec_path` 和 `output_path` 都必须位于工作区。

PPTX 实现：

```python
from pptx import Presentation
from pptx.util import Inches, Pt
```

固定使用 16:9：

```python
prs.slide_width = Inches(13.333)
prs.slide_height = Inches(7.5)
```

页面规则：

- 第一页使用标题页布局，标题取根节点 `title`。
- `slides` 中每个元素生成一个普通内容页。
- 普通页标题字号 28～32 pt。
- bullet 正文字号 18～22 pt。
- bullet 段落使用 `text_frame.paragraphs` 和 `add_paragraph()`。
- 不使用平台特定字体。
- 首版忽略 `notes` 或只将其写入 speaker notes；若当前 python-pptx 版本处理 notes 不稳定，应直接忽略。
- 保存后验证文件存在、文件大小大于 0、`len(prs.slides) > 0`。
- 返回相对于工作区的路径，例如 `result.pptx`。

注意：根节点 `title` 会形成额外标题页。因此 `InputRequest.pages` 表示最终总页数时，Design Prompt 必须生成 `pages - 1` 个普通 `slides` 元素。

### 8.7 `finalize`

签名：

```python
@mcp.tool()
def finalize(outcome: str) -> str:
    """Finish the current agent stage with an existing workspace artifact."""
```

`outcome` 必须只包含产物路径。工具层应在构造 `Path` 前拒绝换行或超长文本，避免将模型总结误当成文件名并触发 `OSError: File name too long`。

行为：

1. 使用工作区路径解析函数校验路径。
2. 目标必须存在。
3. 普通文件必须非空。
4. 返回标准化后的工作区相对路径。

Agent 负责根据角色判断后缀：

- Research 只接受 `.md`。
- Design 只接受 `.pptx`。

## 9. Agent 基类设计

### 9.1 初始化

`agent.py` 中定义：

```python
class Agent:
    def __init__(
        self,
        name: str,
        config: AppConfig,
        env: AgentEnv,
        workspace: Path,
        language: Literal["zh", "en"],
        role_file: Path,
    ) -> None:
        ...
```

初始化步骤：

1. 读取角色 YAML。
2. 选择对应语言的 system prompt。
3. 创建 Jinja2 `Template`。
4. 读取工具白名单。
5. 调用 `env.get_tools()` 获取 OpenAI Tool Schemas。
6. 根据角色的 `use_model` 选择配置并创建 `AsyncOpenAI`：

```python
self.model_config = getattr(config, role.use_model)
self.client = AsyncOpenAI(
    api_key=self.model_config.api_key.get_secret_value(),
    base_url=self.model_config.base_url,
)
```

当 `base_url is None` 时建议不传该关键字，兼容非 OpenAI Provider 的客户端初始化差异。

7. 初始化 system 消息：

```python
self.chat_history = [
    {"role": "system", "content": system_prompt}
]
```

### 9.2 `action()`

签名：

```python
async def action(self, **prompt_context: object) -> list[ToolCall]:
```

执行步骤：

1. `turn_count += 1`。
2. 超过 `max_turns` 时抛出 `RuntimeError`。
3. 首轮使用 `Template.render(**prompt_context)` 添加 user 消息；后续轮次不重复添加初始任务。
4. 调用真实模型：

```python
request_kwargs = {
    "model": self.model_config.model,
    "messages": self.chat_history,
    "tools": self.tools,
    "tool_choice": "auto",
}
if self.model_config.temperature is not None:
    request_kwargs["temperature"] = self.model_config.temperature

response = await self.client.chat.completions.create(**request_kwargs)
```

5. 读取：

```python
message = response.choices[0].message
```

6. 使用 `message.model_dump(exclude_none=True)` 保存 assistant 消息。保存到历史前，确保只保留 `role`、`content`、`tool_calls` 等 Chat Completions 接受字段。
7. 如果 `message.tool_calls` 为空，抛出清晰错误：模型必须通过 MCP 工具完成任务，并建议检查模型是否支持 Tool Calling。
8. 返回 `message.tool_calls`。

不要假设模型每轮只调用一个工具。

### 9.3 `execute()`

签名：

```python
async def execute(
    self,
    tool_calls: list[ChatCompletionMessageFunctionToolCall],
) -> tuple[list[ToolObservation], str | None]:
```

返回：

- observations：本轮全部工具结果。
- final_path：未成功 finalize 时为 `None`，成功时为绝对路径字符串。

每个工具调用的处理顺序：

1. 确认 `tool_call.type == "function"`。
2. 确认工具名在当前 Agent 的白名单。
3. 使用 `json.loads(tool_call.function.arguments or "{}")` 解析参数。
4. 参数解析失败时创建错误 observation，不终止整个进程。
5. 调用 `env.call_tool()`。
6. 添加工具消息：

```python
{
    "role": "tool",
    "tool_call_id": observation.tool_call_id,
    "content": observation.text,
}
```

7. 如果工具是 `finalize`，只有以下条件同时满足才设置 `final_path`：

- observation 没有错误。
- 参数包含非空 `outcome`。
- 工具返回值等于标准化后的 `outcome`。
- Research 的结果后缀为 `.md`，Design 的结果后缀为 `.pptx`。
- 解析后的绝对文件路径位于当前工作区且存在。

首版按工具调用出现顺序串行执行。这样便于支持同一轮中的：

```text
write_file → create_pptx → finalize
```

如果使用 `asyncio.gather()` 并发执行，`finalize` 可能在文件创建完成前运行，因此首版禁止并发执行有依赖关系的工具。

### 9.4 `loop()`

基类将 `loop()` 定义为抽象方法。具体 Agent 采用统一模式：

```python
while True:
    tool_calls = await self.action(...)
    yield AgentEvent(kind="assistant", ...)

    observations, final_path = await self.execute(tool_calls)
    for observation in observations:
        yield AgentEvent(kind="tool", ...)

    if final_path is not None:
        yield AgentEvent(kind="final", ...)
        return
```

### 9.5 历史保存

每个 Agent 完成或失败后保存：

```text
history/Research-history.jsonl
history/Design-history.jsonl
```

每行至少包含：

```json
{
  "timestamp": "ISO-8601",
  "message": {
    "role": "tool",
    "tool_call_id": "call_123",
    "content": "..."
  }
}
```

不得保存 API Key。

## 10. 具体 Agent 设计

### 10.1 Research

```python
class Research(Agent):
    async def loop(self, request: InputRequest) -> AsyncGenerator[AgentEvent, None]:
        ...
```

首轮 Prompt Context：

```python
{
    "prompt": request.prompt,
    "pages": request.pages,
    "language": request.language,
}
```

Research 的 `final` 路径必须为 `.md`。

### 10.2 Design

```python
class Design(Agent):
    async def loop(
        self,
        request: InputRequest,
        manuscript_path: Path,
    ) -> AsyncGenerator[AgentEvent, None]:
        ...
```

首轮 Prompt Context：

```python
{
    "prompt": request.prompt,
    "pages": request.pages,
    "language": request.language,
    "manuscript_path": manuscript_path.as_posix(),
}
```

Design 的 `final` 路径必须为 `.pptx`。

## 11. 角色 YAML 设计

### 11.1 `roles/Research.yaml`

```yaml
system:
  zh: |
    你是内容研究 Agent。你必须使用提供的工具完成任务，不能声称执行了实际未执行的搜索或文件操作。
    首先至少调用一次 search_web 获取真实资料，再编写 Markdown 文稿。
    每页使用单独的二级标题，并使用 --- 分隔页面。关键事实需要保留来源 URL。
    使用 write_file 将最终文稿保存为 manuscript.md，确认完成后调用 finalize。
  en: |
    You are a content research agent. Use the provided tools for all search and file operations.
    Call search_web at least once, write the final manuscript to manuscript.md, then call finalize.

instruction: |
  用户主题：{{ prompt }}
  最终总页数：{{ pages }}
  输出语言：{{ language }}
  请研究主题并生成 manuscript.md。

use_model: research_agent
tools:
  - search_web
  - write_file
  - finalize
```

### 11.2 `roles/Design.yaml`

```yaml
system:
  zh: |
    你是演示文稿结构设计 Agent。必须先调用 read_file 阅读文稿。
    将文稿整理成 slides.json。根节点 title 用于标题页，因此 slides 数组应包含“最终总页数减一”个普通内容页。
    写入 slides.json 后调用 create_pptx，确认 PPTX 创建成功后再调用 finalize。
    不得在未创建文件时直接调用 finalize。
  en: |
    You are a presentation structure agent. Read the manuscript first, write slides.json,
    create result.pptx, and call finalize only after the PPTX exists.

instruction: |
  用户主题：{{ prompt }}
  最终总页数：{{ pages }}
  输出语言：{{ language }}
  文稿路径：{{ manuscript_path }}
  请生成 slides.json 和 result.pptx。

use_model: design_agent
tools:
  - read_file
  - write_file
  - create_pptx
  - finalize
```

## 12. AgentLoop 设计

在 `main.py` 中实现：

```python
class AgentLoop:
    def __init__(self, config: AppConfig, workspace: Path, language: str): ...
    async def run(self, request: InputRequest) -> AsyncGenerator[AgentEvent, None]: ...
```

`run()` 顺序：

1. 创建工作区及 `history/`。
2. 保存 `request.json`。
3. `async with AgentEnv(...) as env`。
4. 创建并运行 Research。
5. 从 Research 的 `final` 事件取得绝对 Markdown 路径。
6. Research 未产生 final 事件时抛出错误，不能继续 Design。
7. 创建并运行 Design。
8. 从 Design 的 `final` 事件取得绝对 PPTX 路径。
9. 保存 `intermediate_output.json`。
10. 产生最终 `AgentEvent(kind="final")`。

注意避免把 Research 的 `final` 事件当作整个工作流的最终结果。`AgentEvent.stage` 必须标记事件所属阶段。

最终工作流事件必须满足：

```python
event.kind == "final" and event.stage == "workflow"
```

## 13. CLI 设计

首版使用标准库 `argparse`，避免增加 CLI 框架复杂度。

入口：

```python
def main() -> None:
    args = parse_args()
    asyncio.run(run_cli(args))
```

参数：

```text
prompt                位置参数，非空
--pages               int，默认 5，范围 2～20
--output              可选 Path；指定时额外复制一份 PPTX
--language            zh/en，默认 zh
--config              Path，默认 Demo 根目录/config.yaml
```

启动检查：

1. 配置文件存在。
2. 模型名称非空。
3. Research 和 Design 的模型配置均通过 Pydantic 校验。
4. `config.search.api_key` 存在且非空。
5. MCP 配置文件存在。

创建 session ID：

```python
session_id = uuid.uuid4().hex[:8]
workspace = workspace_base / session_id
```

CLI 消费 AgentLoop 事件并输出：

```text
[Research] assistant: requested search_web
[Research] tool search_web: completed
[Research] final: .../manuscript.md
[Design] tool create_pptx: result.pptx
[Workflow] final: .../result.pptx
```

最终文件复制：

```python
output_path.parent.mkdir(parents=True, exist_ok=True)
shutil.copy2(final_path, output_path)
```

如果目标路径与源路径相同，不执行复制。

## 14. 依赖文件

`requirements.txt`：

```text
fastmcp>=2.10.0,<2.14.0
mcp>=1.14.0
openai>=1.108.2
pydantic>=2.11.9
PyYAML
Jinja2>=3.1.6
tavily-python>=0.7.14
python-pptx>=0.6.21
```

开发时可以直接使用仓库根环境：

```bash
uv run python examples/mcp_agent_demo/main.py --help
```

独立安装：

```bash
uv pip install -r examples/mcp_agent_demo/requirements.txt
```

## 15. 错误处理

错误分为两类。

### 15.1 必须终止工作流

- 配置文件不存在或格式错误。
- 配置中的 API Key 缺失。
- MCP Server 无法启动或初始化。
- 必要 MCP 工具缺失。
- 模型不支持或没有返回 Tool Calling。
- Agent 超过最大轮数。
- Research 没有生成 Markdown。
- Design 没有生成有效 PPTX。

这些错误抛出异常，由 CLI 打印简洁信息并以非零状态退出。

### 15.2 返回给模型修正

- 模型生成的工具参数不是合法 JSON。
- 调用了没有权限的工具。
- 文件路径越过工作区。
- `slides.json` 格式错误。
- `finalize` 指向不存在的文件。

这些错误应转成 role=`tool` 的错误消息，使模型可以在下一轮纠正；但仍受 `max_turns` 限制。

## 16. 日志与可观察性

必须记录：

- Agent 名称和轮次。
- assistant 消息摘要。
- 工具名、参数（排除敏感值）和执行结果。
- 每个阶段的 final 路径。
- 模型 token usage（响应存在 usage 时）。
- 异常类型和简洁错误信息。

不得记录：

- OpenAI API Key。
- Tavily API Key。
- 完整进程环境变量。

日志文件：

```text
history/Research-history.jsonl
history/Design-history.jsonl
history/tool-history.jsonl
```

## 17. 实现顺序

实现者应按以下顺序工作，每一步完成后进行对应验证：

1. 创建 `requirements.txt`、配置样例和角色 YAML。
2. 实现 `models.py`，验证配置可以被 Pydantic 加载。
3. 实现 `tools/server.py` 的路径保护、文件工具和 `create_pptx`。
4. 直接调用 Python 函数验证能生成 PPTX。
5. 实现 FastMCP `search_web` 和 `finalize`。
6. 实现 `env.py`，完成 MCP Server 启动、工具发现和调用。
7. 编写 MCP smoke test，确认五个工具均可列出。
8. 实现 `agent.py` 的 `action()` 和 `execute()`。
9. 实现 `agents.py`。
10. 实现 `AgentLoop` 与 CLI。
11. 使用真实模型和 Tavily 运行端到端测试。
12. 补充 README 运行说明和常见错误。

## 18. 验证方案

### 18.1 静态验证

```bash
uv run python -m compileall examples/mcp_agent_demo
```

### 18.2 MCP 工具发现

连接 Server 后断言工具名称为：

```python
{
    "search_web",
    "read_file",
    "write_file",
    "create_pptx",
    "finalize",
}
```

### 18.3 文件安全

必须验证以下路径被拒绝：

```text
../outside.txt
/tmp/outside.txt
工作区内指向外部的符号链接
```

### 18.4 PPTX 工具

使用固定 `slides.json` 调用 `create_pptx`，然后验证：

```python
from pptx import Presentation

prs = Presentation(output_path)
assert len(prs.slides) >= 2
```

### 18.5 真实端到端验证

```bash
cp examples/mcp_agent_demo/config.yaml.example \
   examples/mcp_agent_demo/config.yaml

# 编辑 config.yaml，填写两个模型和 Tavily 的 api_key

uv run python examples/mcp_agent_demo/main.py \
  "介绍大模型 Agent 的发展趋势" \
  --pages 5 \
  --output /tmp/mcp-agent-demo.pptx
```

验证：

- Research 工具历史包含 `search_web`。
- `manuscript.md` 非空且包含来源 URL。
- `slides.json` 是合法 JSON。
- 最终 PPTX 共 5 页。
- Research 和 Design 都成功调用 `finalize`。
- `/tmp/mcp-agent-demo.pptx` 可以用 `python-pptx` 重新打开。

## 19. 完成定义

满足以下条件才算完成：

- 实现文件与本文档目录结构一致。
- Demo 不导入 `deeppresenter` 或旧 `pptagent` 的运行代码，能够独立阅读。
- 使用真实大模型，没有 Mock 分支。
- 五个业务工具全部通过 MCP 调用。
- MCP Server 使用 stdio，不依赖 Docker。
- Research 和 Design 使用 YAML 配置的不同角色与工具白名单。
- 工作区路径限制有效。
- 真实搜索、文稿生成、页面结构生成和 PPTX 创建全部成功。
- 错误不会导致无限 Agent 循环。
- README 包含安装、配置、运行和故障排查步骤。

## 20. 明确禁止的实现偏差

- 不得为了省事直接在 Agent 中调用 Tavily 或 `python-pptx`。
- 不得将 API Key 写死在代码或 YAML 中。
- 不得用 Mock LLM 代替真实模型。
- 不得让 Design 跳过 `read_file` 直接凭空生成页面。
- 不得让模型直接写工作区外的文件。
- 不得使用字符串类型判断代替明确的 `AgentEvent.kind`。
- 不得在首版引入 Web UI、Planner、动态子 Agent 或 HTML 转换。
- 不得并发执行存在先后依赖的 `write_file`、`create_pptx` 和 `finalize`。
