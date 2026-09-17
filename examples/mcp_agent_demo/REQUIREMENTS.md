# MCP Agent PPT Demo 需求文档

## 1. 项目目标

实现一个代码规模较小、能够独立运行的 PPT 生成 Demo，用于学习 DeepPresenter 的核心 Agent 架构。

Demo 必须使用真实大模型和 MCP 工具，不使用 Mock 模型。它需要保留以下核心机制：

- `AgentLoop` 工作流编排。
- `action → tool call → execute → observation` Agent 循环。
- Research 和 Design 两个 Agent 的固定流水线。
- 基于 YAML 的角色提示词和工具权限配置。
- MCP Client/Server 工具调用。
- 通过工作区文件传递阶段产物。
- 最终生成可以打开的 PPTX 文件。

## 2. 核心流程

```text
用户输入主题、页数和输出路径
    ↓
AgentLoop 创建独立工作区
    ↓
Research Agent
    ↓
通过 MCP 调用 search_web 搜索资料
    ↓
通过 MCP 调用 write_file 生成 manuscript.md
    ↓
调用 finalize 返回文稿路径
    ↓
Design Agent
    ↓
通过 MCP 调用 read_file 读取文稿
    ↓
生成并写入 slides.json
    ↓
通过 MCP 调用 create_pptx 创建 result.pptx
    ↓
调用 finalize 返回 PPTX 路径
    ↓
AgentLoop 将 PPTX 复制到用户指定位置
```

## 3. 功能需求

### 3.1 命令行入口

提供一个简单的 CLI，支持以下调用：

```bash
python main.py \
  "介绍大模型 Agent 的发展趋势" \
  --pages 5 \
  --output result.pptx
```

CLI 参数：

| 参数 | 必填 | 默认值 | 说明 |
|---|---:|---|---|
| `prompt` | 是 | 无 | PPT 主题或用户要求 |
| `--pages` | 否 | `5` | 期望生成的页数 |
| `--output` | 否 | 无 | 将 workspace 中的 PPTX 额外复制到指定路径 |
| `--language` | 否 | `zh` | Agent 输出语言，支持 `zh`、`en` |

CLI 负责：

- 校验参数和配置文件中的必要密钥。
- 创建 `InputRequest`。
- 创建并运行 `AgentLoop`。
- 输出当前阶段及工具调用信息。
- 将最终 PPTX 复制到指定路径。

### 3.2 真实模型调用

Demo 使用 OpenAI 兼容的 Chat Completions Tool Calling 接口。

配置项：

```yaml
research_agent:
  base_url: "https://your-openai-compatible-endpoint/v1"
  model: "your-research-model"
  api_key: "your-key"
  max_turns: 10

design_agent:
  base_url: "https://your-openai-compatible-endpoint/v1"
  model: "your-design-model"
  api_key: "your-key"
  max_turns: 10
```

要求：

- Research 和 Design 分别配置模型，可以使用不同服务或模型。
- 模型密钥从本地 `config.yaml` 读取，该文件必须被 Git 忽略。
- 模型必须支持标准工具调用。
- 每个 Agent 必须设置最大轮数，避免无限循环。
- 模型请求失败时输出清晰错误信息。

### 3.3 AgentLoop

`AgentLoop` 负责显式编排，不能让模型自行选择是否跳过阶段。

固定顺序：

```text
Research → Design
```

职责：

- 为每次任务创建独立工作区。
- 初始化 MCP 工具环境。
- 将用户请求交给 Research。
- 将 Research 返回的文稿路径交给 Design。
- 保存阶段产物路径。
- 返回最终 PPTX 路径。

阶段状态示例：

```json
{
  "manuscript": "workspace/manuscript.md",
  "slides_spec": "workspace/slides.json",
  "final": "workspace/result.pptx"
}
```

### 3.4 Agent 基类

实现一个精简的通用 Agent 基类，至少包含：

- 角色 YAML 加载。
- System Prompt 和任务 Prompt 构建。
- `chat_history` 管理。
- MCP 工具 Schema 筛选。
- `action()`：携带对话历史和工具列表调用真实模型。
- `execute()`：通过 MCP Client 执行模型返回的工具调用。
- 最大轮数限制。
- `finalize` 结束识别。
- 基本运行日志。

Agent 循环：

```text
action()
    ↓
模型返回 tool_calls
    ↓
execute()
    ↓
工具结果加入 chat_history
    ↓
未 finalize：进入下一轮
已 finalize：返回阶段产物
```

本 Demo 不实现上下文压缩、复杂 token 预算控制和多模型重试。

### 3.5 Research Agent

输入：

- 用户 Prompt。
- 期望页数。
- 输出语言。

职责：

- 至少调用一次 `search_web` 获取真实资料。
- 基于搜索结果设计清晰的内容结构。
- 生成 Markdown 文稿。
- 使用 `write_file` 将文稿写入 `manuscript.md`。
- 调用 `finalize(outcome="manuscript.md")` 结束阶段。

文稿要求：

- 页数尽量符合用户要求。
- 每页使用 `---` 分隔。
- 每页包含标题和主要内容。
- 搜索获得的关键事实应保留来源链接。
- 不允许伪造搜索结果或来源。

### 3.6 Design Agent

输入：

- Research 生成的 `manuscript.md` 路径。
- 期望页数和语言。

职责：

- 使用 `read_file` 读取 Markdown 文稿。
- 将文稿整理为结构化幻灯片数据。
- 使用 `write_file` 写入 `slides.json`。
- 调用 `create_pptx` 生成 `result.pptx`。
- 调用 `finalize(outcome="result.pptx")` 结束阶段。

`slides.json` 建议格式：

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

首版只需要生成清晰、可阅读的基础版式，不追求复杂视觉效果。

## 4. MCP 需求

### 4.1 MCP 架构

首版使用一个 FastMCP Server 提供全部 Demo 工具：

```text
Agent
    ↓ tool call
MCP Client
    ↓ stdio
FastMCP Server
    ↓
搜索 / 文件操作 / PPTX 生成
```

MCP Server 通过标准输入输出启动，不依赖 Docker。

### 4.2 MCP 工具

#### `search_web`

```text
输入：query、max_results
输出：包含标题、URL 和摘要的搜索结果
```

要求：

- 使用 Tavily API 进行真实搜索。
- 从本地 `config.yaml` 的 `search.api_key` 读取密钥。
- 网络或 API 错误必须返回明确错误信息。
- 默认最多返回 5 条结果，避免占用过多上下文。

#### `read_file`

```text
输入：path
输出：UTF-8 文本内容
```

#### `write_file`

```text
输入：path、content
输出：保存后的工作区相对路径
```

#### `create_pptx`

```text
输入：spec_path、expected_pages、output_path
输出：生成的 PPTX 工作区相对路径
```

要求：

- 使用 `python-pptx`。
- 从 `slides.json` 读取结构化内容。
- 支持标题页和普通内容页。
- 自动处理基础字号和页面边距。
- 输出文件必须能被 PowerPoint 或 LibreOffice 正常打开。

#### `finalize`

```text
输入：outcome
输出：outcome
```

`finalize` 是阶段结束协议。`Agent.execute()` 只有在 MCP 工具成功返回与 `outcome` 一致的结果时，才结束当前 Agent。
`outcome` 只能包含产物文件路径，禁止传入总结文字；非法输入应返回工具错误，让 Agent 在下一轮纠正。

### 4.3 文件安全

`read_file`、`write_file` 和 `create_pptx` 必须：

- 只允许访问当前 `WORKSPACE` 环境变量指向的目录。
- 拒绝 `..` 等路径穿越。
- 拒绝读写工作区外的绝对路径。
- 自动创建必要的父目录。

## 5. 角色配置

提供：

```text
roles/Research.yaml
roles/Design.yaml
```

每个角色至少定义：

```yaml
system: "角色系统提示词"
instruction: "任务提示词模板"
use_model: "research_agent"  # 或 design_agent
tools:
  - tool_name
```

工具权限：

| Agent | 允许工具 |
|---|---|
| Research | `search_web`、`write_file`、`finalize` |
| Design | `read_file`、`write_file`、`create_pptx`、`finalize` |

## 6. 工作区与产物

每次运行创建独立工作区：

```text
workspace/<session-id>/
├── request.json
├── manuscript.md
├── slides.json
├── result.pptx
├── intermediate_output.json
└── history/
    ├── Research-history.jsonl
    ├── Design-history.jsonl
    └── tool-history.jsonl
```

工作区需要保留，便于学习和调试。

## 7. 建议目录结构

```text
examples/mcp_agent_demo/
├── README.md
├── REQUIREMENTS.md
├── main.py
├── agent.py
├── agents.py
├── env.py
├── models.py
├── config.yaml.example
├── mcp.json
├── roles/
│   ├── Research.yaml
│   └── Design.yaml
└── tools/
    ├── server.py
    └── stdio_compat.py
```

## 8. 非功能需求

- 所有函数和方法添加类型提示。
- 技术注释和代码文档使用英文。
- 代码优先清晰易读，不复制主项目中的复杂兼容逻辑。
- 不把异常作为正常控制流。
- API Key 不写入日志、配置样例或运行产物。
- Agent、MCP 和业务工具之间保持清晰边界。
- 使用当前项目已有依赖，首版不新增非必要依赖。

## 9. 首版不实现

- Mock 模型。
- Web UI。
- Planner 和大纲人工修改。
- 动态 SubAgent 委派。
- Docker 沙箱。
- HTML、CSS 和 Playwright 转换。
- PDF 回退。
- 图片搜索、图片生成和多模态检查。
- 上下文压缩。
- 多模型路由与多端点重试。
- 断点恢复和任务并发。

## 10. 验收标准

- [ ] 使用真实、支持 Tool Calling 的模型完成运行。
- [ ] 所有业务工具均通过 MCP Server 暴露并调用。
- [ ] Research 至少执行一次真实 Tavily 搜索。
- [ ] Research 成功生成 `manuscript.md`。
- [ ] Design 成功生成符合约定格式的 `slides.json`。
- [ ] `create_pptx` 成功生成可打开的 `result.pptx`。
- [ ] Research 与 Design 均通过 `finalize` 正常结束。
- [ ] CLI 将最终文件复制到用户指定路径。
- [ ] 工作区保留请求、中间产物、对话历史和工具记录。
- [ ] 缺少 API Key、模型不支持工具调用或工具执行失败时，错误信息清晰。
- [ ] 达到最大轮数时安全终止，不出现无限循环。

## 11. 最小成功示例

本地配置：

```yaml
search:
  api_key: "your-tavily-key"
```

模型和搜索的 `api_key` 都填写在被 Git 忽略的本地 `config.yaml` 中。

运行：

```bash
cd examples/mcp_agent_demo
python main.py \
  "介绍大模型 Agent 的发展趋势" \
  --pages 5 \
  --output result.pptx
```

预期结果：

```text
Research Agent 完成真实搜索并生成文稿
Design Agent 将文稿转换为结构化页面
MCP create_pptx 生成 PPTX
最终输出 result.pptx
```
