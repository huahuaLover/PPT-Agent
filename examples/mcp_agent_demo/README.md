# MCP Agent PPT Demo

一个用于学习 Agent 核心机制的独立 Demo。它使用真实大模型、真实 Tavily 搜索和 stdio MCP 工具，按固定顺序运行：

```text
Research Agent → manuscript.md → Design Agent → result.pptx
```

## 你能从中学到什么

- `AgentLoop` 如何编排多个 Agent。
- `action → tool call → execute → observation` 如何循环。
- MCP Server 如何向模型暴露搜索和文件工具。
- 两个 Agent 如何通过工作区文件交接产物。
- YAML 如何配置角色提示词和工具权限。

## 安装

在仓库根目录使用现有环境：

```bash
uv sync
```

也可以单独安装 Demo 依赖：

```bash
uv pip install -r examples/mcp_agent_demo/requirements.txt
```

## 配置

复制配置样例：

```bash
cp examples/mcp_agent_demo/config.yaml.example \
   examples/mcp_agent_demo/config.yaml
```

编辑 `config.yaml`，分别填写 Research 和 Design 使用的 OpenAI 兼容模型配置：`base_url`、`model` 和 `api_key`。两个 Agent 可以使用不同模型，模型必须支持 Chat Completions Tool Calling。

`config.yaml` 已被 `.gitignore` 忽略，不会提交其中的密钥。

在 `search.api_key` 中填写 Tavily 密钥。模型和搜索密钥都从本地 `config.yaml` 读取，不需要设置环境变量。

## 运行

```bash
uv run python examples/mcp_agent_demo/main.py \
  "介绍大模型 Agent 的发展趋势" \
  --pages 5 \
  --language zh
```

最终 PPTX 默认保存在本次运行的 `workspace/<session-id>/result.pptx`。如需额外复制到指定位置，再传入 `--output <路径>`。

每次运行会保留独立工作区：

```text
examples/mcp_agent_demo/workspace/<session-id>/
├── request.json
├── manuscript.md
├── slides.json
├── result.pptx
├── intermediate_output.json
└── history/
```

## 阅读顺序

```text
main.py
→ agents.py
→ agent.py
→ env.py
→ tools/server.py
→ roles/*.yaml
```

## 常见错误

### 模型没有返回工具调用

确认模型支持 Chat Completions Tool Calling。某些兼容服务虽然支持普通对话，但不支持 `tools` 参数。

### MCP Server 无法启动

确保 Demo 依赖安装在运行 `main.py` 的同一个 Python 环境中。程序会自动使用 `sys.executable` 启动 Server。

### Tavily 搜索失败

检查 `config.yaml` 中的 `search.api_key` 是否有效，以及当前网络是否可以访问 Tavily。

### Agent 超过最大轮数

模型没有按角色提示完成工具流程。检查历史目录中的 JSONL 文件，或适当增大 `config.yaml` 的 `max_turns`。

## 设计文档

- [需求文档](REQUIREMENTS.md)
- [技术设计](TECHNICAL_DESIGN.md)
