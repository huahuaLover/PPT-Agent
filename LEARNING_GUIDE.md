# PPTAgent 项目学习路线

本路线以当前主产品 `deeppresenter/` 为核心，按照一次演示文稿生成请求的真实执行顺序阅读。不要一开始通读整个仓库，也不要以可能过期的 README 作为代码结构的依据。

## 学习目标

完成本路线后，应当能够回答：

- `pptagent generate` 从哪里进入程序？
- 用户输入如何变成 `InputRequest`？
- Planner、Research、Design 分别负责什么？
- Agent 如何调用大模型和 MCP 工具？
- Markdown 如何变成 HTML，HTML 又如何变成 PPTX？
- 修改提示词、工具或导出逻辑时，应该改哪个位置？

## 系统主链路

```text
CLI 输入
  -> Planner（可选，生成和编辑大纲）
  -> Research（研究并生成 Markdown 文稿）
  -> Design（逐页生成 HTML）
  -> html2pptx / Playwright（导出 PPTX 和 PDF）
  -> CLI 将最终文件复制到用户指定位置
```

---

## 第一阶段：先观察一次完整运行

### 1. 查看命令入口

```bash
uv run pptagent --help
uv run pptagent generate --help
```

### 2. 完成配置

如果尚未配置项目：

```bash
uv run pptagent onboard
```

配置模板位于：

- `deeppresenter/config.yaml.example`
- `deeppresenter/mcp.json.example`

### 3. 生成一份短演示文稿

先用 2～3 页的小任务降低调试成本：

```bash
uv run pptagent generate "介绍 Transformer 的核心架构" \
  --pages 3 \
  --lang zh \
  --output /tmp/transformer.pptx
```

默认工作区位于 `~/.cache/deeppresenter/<session-id>/`。重点观察：

- `.input_request.json`：标准化后的用户请求
- Markdown 文件：Research 阶段生成的文稿
- `slides/global.css`：全局视觉设计
- `slides/slide_*.html`：逐页 HTML
- `intermediate_output.json`：各阶段的输出路径
- `.history/`：Agent 对话、工具调用和运行日志

检查点：能够把工作区中的每类文件对应到主链路中的一个阶段。

---

## 第二阶段：理解 CLI 和输入模型

### 4. 阅读项目入口

文件：`pyproject.toml`

重点阅读 `[project.scripts]`：

```toml
pptagent = "deeppresenter.cli:main"
pptagent-mcp = "pptagent.mcp_server:main"
```

需要理解：

- `pptagent` 是当前主 CLI，进入 `deeppresenter`。
- `pptagent-mcp` 是旧 `pptagent` 栈提供的 MCP 服务入口。
- 两套代码有关联，但不是同一个生成入口。

### 5. 阅读 CLI 命令

文件：`deeppresenter/cli/commands.py`

先只阅读 `generate()`，关注：

1. CLI 参数如何解析。
2. 附件路径如何校验。
3. 如何创建 `InputRequest`。
4. 如何加载 `DeepPresenterConfig`。
5. 如何创建和运行 `AgentLoop`。
6. 最终文件如何复制到 `--output`。

暂时跳过 `onboard()`、`serve()` 和交互式大纲编辑的细节。

### 6. 阅读输入数据结构

文件：`deeppresenter/utils/typings.py`

重点阅读：

- `InputRequest`
- `ConvertType`
- `PowerPointType`
- `ChatMessage`
- `MCPServer`
- `RoleConfig` 和 `ToolSet`

检查点：能够说明一条 CLI 命令最终如何表示成一个 `InputRequest` 对象。

---

## 第三阶段：理解核心编排

### 7. 精读 AgentLoop

文件：`deeppresenter/main.py`

这是整个主链路最重要的文件。完整阅读 `AgentLoop.run()`，按以下阶段做笔记：

1. 创建工作区并复制附件。
2. 创建 `AgentEnv`。
3. 可选运行 Planner。
4. 运行 Research，取得 Markdown 文稿。
5. 根据 `convert_type` 选择 PPTAgent 或 Design。
6. Design 路径下将 HTML 转换为 PPTX/PDF。
7. 保存 `intermediate_output.json`。
8. 向 CLI 返回最终文件路径。

建议在以下位置设置断点：

- `AgentLoop.run()` 入口
- `Research.loop()` 调用前后
- `Design.loop()` 调用前后
- `convert_html_to_pptx()` 调用前后

检查点：不看代码也能画出 `AgentLoop.run()` 的执行流程。

---

## 第四阶段：理解 Agent 循环

### 8. 阅读三个具体 Agent

按顺序阅读：

1. `deeppresenter/agents/research.py`
2. `deeppresenter/agents/design.py`
3. `deeppresenter/agents/planner.py`
4. `deeppresenter/agents/pptagent.py`

前三个属于当前主流程。`PPTAgent` 只需先了解它是模板生成分支。

观察它们共同的循环：

```text
action() 请求模型作出决策
  -> 模型返回工具调用
  -> execute() 执行工具
  -> 工具结果加入对话历史
  -> 继续下一轮
  -> finalize 返回产物路径
```

### 9. 精读 Agent 基类

文件：`deeppresenter/agents/agent.py`

建议按方法阅读，而不是从头逐行阅读：

1. `__init__()`：加载角色配置、模型和工具集。
2. `_setup_toolset()`：决定 Agent 能看到哪些工具。
3. `action()`：组装消息并调用模型。
4. `execute()`：执行模型产生的工具调用。
5. 上下文折叠和历史保存相关方法。

重点理解两个状态：

- `chat_history`：模型看到的对话上下文。
- `tool_calls`：模型要求系统执行的动作。

检查点：能够解释为什么具体 Agent 文件很短，而系统仍然可以完成复杂任务。

---

## 第五阶段：理解角色提示词

### 10. 阅读角色 YAML

按主链路顺序阅读：

1. `deeppresenter/roles/Planner.yaml`
2. `deeppresenter/roles/Research.yaml`
3. `deeppresenter/roles/Design.yaml`
4. `deeppresenter/roles/PPTAgent.yaml`
5. `deeppresenter/roles/SubAgent.yaml`

每个角色都重点观察：

- `system`：职责、约束和工作流程。
- `instruction`：运行时参数如何注入提示词。
- `use_model`：该角色使用哪个模型配置。
- `toolset`：该角色能调用哪些工具。

实践：只修改一条容易识别的提示词，例如要求每页标题必须是结论句，然后生成 2～3 页 PPT，比较修改前后的文稿与 HTML。

检查点：能够区分“应该修改 Python 编排”和“应该修改角色提示词”的需求。

---

## 第六阶段：理解工具系统

### 11. 阅读 AgentEnv

文件：`deeppresenter/agents/env.py`

重点阅读：

1. `__init__()`：读取 MCP 配置和构造环境变量。
2. `__aenter__()`：启动工具服务并注册工具。
3. `tool_execute()`：校验参数、执行工具、截断过长结果。
4. 本地工具注册逻辑。
5. 工具历史和耗时统计。

### 12. 阅读 MCP 配置

文件：`deeppresenter/mcp.json.example`

将每个服务映射到相应代码：

- `any2markdown` → `deeppresenter/tools/any2markdown.py`
- `task` → `deeppresenter/tools/task.py`
- `deeppresenter` → `deeppresenter/tools/reflect.py`
- `tool_agents` → `deeppresenter/tools/tool_agents.py`
- `search` → `deeppresenter/tools/search.py`
- `sandbox` → Docker 沙箱
- `pptagent` → `pptagent-mcp`

### 13. 先读最关键的工具

推荐顺序：

1. `deeppresenter/tools/task.py`：理解 `finalize()` 如何结束 Agent 循环。
2. `deeppresenter/tools/reflect.py`：理解文稿和页面检查。
3. `deeppresenter/tools/any2markdown.py`：理解附件转换。
4. `deeppresenter/tools/search.py`：理解外部信息检索。
5. `deeppresenter/utils/mcp_client.py`：最后理解 MCP 客户端细节。

检查点：从 `.history/tool_history.jsonl` 选择一次工具调用，追踪到具体实现。

---

## 第七阶段：理解配置和模型调用

### 14. 阅读配置模型

文件：`deeppresenter/utils/config.py`

重点阅读：

- `Endpoint`
- `LLM`
- `DeepPresenterConfig`
- `DeepPresenterConfig.load_from_file()`
- 模型可用性检查和重试逻辑

对照 `deeppresenter/config.yaml.example` 理解：

- `research_agent` 与 `design_agent` 为什么可以使用不同模型。
- OpenAI 兼容接口和 LiteLLM 的差别。
- `offline_mode`、`context_folding`、`async_tool_mode` 的作用。
- 多模态模型为什么会影响页面反思能力。

检查点：能够从角色 YAML 的 `use_model` 找到最终调用的模型配置。

---

## 第八阶段：理解 HTML 导出

### 15. 阅读 Python 导出层

文件：`deeppresenter/utils/webview.py`

重点阅读：

- `PlaywrightConverter`
- `convert_html_to_pptx()`
- HTML 转 PDF 的回退路径
- 页面尺寸和宽高比处理

### 16. 阅读 Node 转换入口

目录：`deeppresenter/html2pptx/`

推荐顺序：

1. `package.json`
2. `html2pptx_cli.js`
3. `html2pptx.js` 中的主入口 `html2pptx()`

不要一开始逐行阅读整个 `html2pptx.js`。先通过主函数理解：

```text
加载 HTML
  -> 用浏览器计算布局
  -> 提取文本、图片、形状和样式
  -> 将像素坐标转换为 PPT 坐标
  -> 使用 pptxgenjs 创建幻灯片
```

只有在处理文本错位、元素溢出、渐变或图片转换问题时，再阅读对应的辅助函数。

检查点：能够判断一个显示问题来自 Design 生成的 HTML，还是来自 html2pptx 转换。

---

## 第九阶段：按需学习旧 pptagent 栈

只有遇到以下任务时，再进入 `pptagent/`：

- 修改 `pptagent-mcp`。
- 使用或修改模板驱动的 PPT 生成。
- 研究版式归纳、内容归纳或旧论文实现。
- 修改 `ConvertType.PPTAGENT` 分支。

推荐入口：

1. `pptagent/mcp_server.py`
2. `pptagent/presentation/`
3. `pptagent/document/`
4. `pptagent/roles/` 和 `pptagent/prompts/`
5. `pptagent/ppteval/`

不要为了理解当前 CLI 主流程而通读旧栈。

---

## 推荐实践任务

按风险从低到高完成：

- [ ] 跑一次 3 页生成并标注所有中间产物。
- [ ] 从 CLI 参数追踪到 `InputRequest`。
- [ ] 手动画出 `AgentLoop.run()` 流程图。
- [ ] 从一条工具历史追踪到工具实现。
- [ ] 修改 Research 提示词并比较 Markdown。
- [ ] 修改 Design 提示词并比较 HTML。
- [ ] 给一个 Agent 增加简单、只读的本地工具。
- [ ] 修复一个 HTML 页面问题并重新导出。
- [ ] 为 `deeppresenter` 的纯逻辑部分补一个单元测试。

## 调试建议

优先检查：

1. 工作区的 `.history/`。
2. `intermediate_output.json`。
3. Research 生成的 Markdown。
4. Design 生成的原始 HTML。
5. 浏览器渲染结果。
6. 最终 PPTX。

定位问题时逐层判断，不要直接修改最终 PPTX：

```text
内容错误？        -> Research / Research.yaml
大纲错误？        -> Planner / Planner.yaml
布局设计错误？    -> Design / Design.yaml / HTML
工具不可用？      -> AgentEnv / mcp.json / tools
PPTX 与 HTML 不同？ -> webview.py / html2pptx
CLI 行为错误？    -> cli/commands.py
```

## 测试说明

当前 checkout 中的测试主要位于 `pptagent/test/`，它们大多覆盖旧栈；没有对应的 `deeppresenter/test/` 目录。因此学习当前主链路时，优先采用：

- 2～3 页的短任务端到端运行。
- 检查 workspace 中的阶段产物。
- 对纯逻辑函数增加小型单元测试。
- 仅在依赖、凭据和 Docker 环境齐全时运行集成流程。

旧栈中较轻量的测试可以单独运行：

```bash
uv run pytest pptagent/test/test_utils.py
```

## 最终自测

完成学习后，尝试不查看代码回答：

1. `pptagent generate` 如何到达 `AgentLoop.run()`？
2. Agent 根据什么获得系统提示词和工具列表？
3. 模型如何告诉程序任务已经完成？
4. Research 的输出如何成为 Design 的输入？
5. HTML 转 PPTX 失败时系统会做什么？
6. 哪些修改属于主 `deeppresenter` 栈，哪些属于旧 `pptagent` 栈？

如果这六个问题都能讲清楚，就已经掌握了项目的核心结构，可以开始针对具体功能深入学习。
