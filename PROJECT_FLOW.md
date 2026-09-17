# PPTAgent / DeepPresenter 项目运行与学习路线

> 本文以当前代码为准。命令行产品的主入口是 `deeppresenter`，安装后的命令名是 `pptagent`；根目录的部分旧文档和 `webui.py` 不作为运行链路依据。

## 1. 先建立全局认识

项目有两套相邻但职责不同的代码：

```text
用户执行：pptagent generate
        |
        v
deeppresenter/                         当前主产品，负责 Agent 编排
        |
        +-- 默认：Research -> Design -> HTML -> PPTX/PDF
        |
        +-- 可选：Research -> PPTAgent Agent -> pptagent MCP
                                                    |
                                                    v
                                               pptagent/ 旧模板生成引擎
```

| 代码区域 | 角色 | 是否优先学习 |
| --- | --- | --- |
| `deeppresenter/` | 命令行、Agent、多轮工具调用、HTML 幻灯片和导出 | 是 |
| `pptagent/` | 模板分析、布局归纳、基于 `python-pptx` 的模板化生成 | 第二阶段 |
| `deeppresenter/roles/` | 每个 Agent 的系统提示词、模型选择、工具白名单 | 与 Agent 代码一起读 |
| `deeppresenter/tools/` | 作为 MCP 服务暴露的具体能力 | 按需要深入 |

真实命令入口在 `pyproject.toml`：

```toml
pptagent = "deeppresenter.cli:main"
pptagent-mcp = "pptagent.mcp_server:main"
```

因此，回答“项目如何运行”时，正确起点是 `deeppresenter/cli/__init__.py` 中的 `main()`，不是旧 `pptagent` 包。

## 2. 从命令到 AgentLoop

典型命令：

```bash
pptagent onboard
pptagent generate "介绍具身智能的发展" -o output.pptx -p 10 -l zh
```

| 步骤 | 做什么 | 代码位置 |
| --- | --- | --- |
| 1 | 注册 `onboard`、`generate`、`serve`、`config`、`clean` 五个 Typer 命令 | `deeppresenter/cli/__init__.py`，`app.command()`；`main()` |
| 2 | 首次配置：检查 Docker、Playwright、Node、Poppler，并保存模型和 MCP 配置 | `deeppresenter/cli/commands.py`，`onboard()` |
| 3 | 读取命令行参数，验证附件，构造请求对象 | `deeppresenter/cli/commands.py`，`generate()`；`deeppresenter/utils/typings.py`，`InputRequest` |
| 4 | 从 `~/.config/deeppresenter/config.yaml` 加载模型配置，并指定 MCP 配置文件 | `deeppresenter/cli/commands.py`，`generate()`；`deeppresenter/utils/config.py`，`DeepPresenterConfig.load_from_file()` |
| 5 | 建立本次运行的会话 ID、工作区和总编排对象 | `deeppresenter/cli/commands.py`，`generate()` 内部的 `run()`；`deeppresenter/main.py`，`AgentLoop.__init__()` |
| 6 | 异步流式运行总流程，得到最终文件后复制到 `-o` 指定路径 | `deeppresenter/cli/commands.py`，`run()`；`deeppresenter/main.py`，`AgentLoop.run()` |

### 配置和工作区

| 项目 | 默认位置 | 代码来源 |
| --- | --- | --- |
| 用户配置 | `~/.config/deeppresenter/config.yaml` | `deeppresenter/cli/common.py`，`CONFIG_FILE` |
| MCP 配置 | `~/.config/deeppresenter/mcp.json` | `deeppresenter/cli/common.py`，`MCP_FILE` |
| 任务工作区 | `~/.cache/deeppresenter/<session_id>/` | `deeppresenter/utils/constants.py`，`WORKSPACE_BASE`；`deeppresenter/main.py`，`AgentLoop.__init__()` |
| 配置示例 | `deeppresenter/config.yaml.example`、`deeppresenter/mcp.json.example` | `onboard()` 读取并复制 |

`InputRequest.copy_to_workspace()` 会将附件复制进工作区；随后 `AgentLoop.run()` 将请求序列化为 `.input_request.json`。每个 Agent 的消息、工具调用、错误和用量都写入工作区 `.history/`。

## 3. 总编排：一次生成的主链路

总控制流只有一个核心函数：`deeppresenter/main.py` 的 `AgentLoop.run()`。

```text
AgentLoop.run(request)
  |
  +-- request.copy_to_workspace()
  +-- async with AgentEnv(workspace, config)
  |
  +-- [可选] Planner.loop(request)
  |       输出：outline JSON 文件
  |
  +-- Research.loop(request, outline_path)
  |       输出：Markdown 文稿文件
  |
  +-- convert_type == PPTAGENT ?
  |     |
  |     +-- 是：PPTAgent.loop(request, markdown_file)
  |     |          输出：PPTX 文件
  |     |
  |     +-- 否：Design.loop(request, markdown_file)
  |                输出：slides/ 目录
  |                |
  |                +-- convert_html_to_pptx(...)
  |                +-- PlaywrightConverter.convert_to_pdf(...)
  |
  +-- save_results()
        输出：intermediate_output.json
```

### 每个编排步骤对应的文件和函数

| 顺序 | 输入 | 处理 | 输出 | 入口函数 |
| --- | --- | --- | --- | --- |
| 0 | `InputRequest` | 复制附件、记录输入、初始化 MCP 环境 | 工作区、`.input_request.json` | `deeppresenter/main.py`，`AgentLoop.run()` |
| 1，可选 | 用户要求、附件 | 规划每页标题与页面意图；CLI 允许人工修改、确认 | `outline.json` | `deeppresenter/agents/planner.py`，`Planner.loop()`；CLI 编辑逻辑在 `commands.py`，`_edit_outline()` |
| 2 | 提示词、附件、可选大纲 | 调研、解析资料、下载本地素材、撰写以 `---` 分页的 Markdown | 文稿 `.md` | `deeppresenter/agents/research.py`，`Research.loop()` |
| 3A，默认 | Markdown 文稿 | 生成统一 CSS 和逐页 HTML，检查每页视觉质量 | `slides/global.css`、`slides/slide_XX.html` | `deeppresenter/agents/design.py`，`Design.loop()` |
| 4A，默认 | HTML 文件 | 转换为可编辑 PPTX，并用浏览器渲染 PDF | `.pptx`、`.pdf` | `deeppresenter/utils/webview.py`，`convert_html_to_pptx()`、`PlaywrightConverter.convert_to_pdf()` |
| 3B，可选 | Markdown 文稿 | 通过 MCP 调旧模板式生成能力 | `.pptx` | `deeppresenter/agents/pptagent.py`，`PPTAgent.loop()`；`pptagent/mcp_server.py`，`PPTAgentServer` |
| 5 | 所有中间产物路径 | 记录不同阶段的结果索引 | `intermediate_output.json` | `deeppresenter/main.py`，`AgentLoop.save_results()` |

## 4. Agent 是如何循环工作的

`Research`、`Design`、`PPTAgent`、`Planner` 都继承 `deeppresenter/agents/agent.py` 中的 `Agent`。其子类 `loop()` 很薄，只定义不同阶段传给提示词的参数；真正的通用循环在基类里。

```text
子类 loop()
  |
  +-- Agent.action(...)
  |     把系统提示词、阶段 instruction、历史消息和工具 schema 发送给 LLM
  |
  +-- Agent.execute(tool_calls)
  |     并发执行模型提出的工具调用，结果追加到对话历史
  |
  +-- 若模型调用 finalize(outcome=path)
        返回 path，当前 Agent 结束
  否则回到 action()，开始下一轮
```

| 机制 | 文件与函数 | 要点 |
| --- | --- | --- |
| 读取 Agent 配置 | `deeppresenter/agents/agent.py`，`Agent.__init__()` | 默认按类名读取 `roles/Research.yaml` 等文件 |
| 选择可用工具 | `deeppresenter/agents/agent.py`，`_setup_toolset()` | role YAML 的 `toolset` 决定 MCP 服务和工具白名单 |
| 发起模型调用 | `deeppresenter/agents/agent.py`，`action()` | 带工具 schema 的 LLM 请求，供模型规划和调用工具 |
| 只做结构化对话 | `deeppresenter/agents/agent.py`，`chat()` | 给需要 JSON/Pydantic 返回的场景使用 |
| 解析并执行 tool call | `deeppresenter/agents/agent.py`，`execute()` | 校验调用参数；识别 `finalize`；记录错误和用量 |
| 上下文压缩 | `deeppresenter/agents/agent.py`，`compact_history()` | 超过上下文窗口时先写历史摘要再继续 |
| 记录运行轨迹 | `deeppresenter/agents/agent.py`，`save_history()` | 保存 history、模型、成本、工具和错误信息 |
| 实际调用模型 | `deeppresenter/utils/config.py`，`LLM.run()` | 统一封装模型请求；`DeepPresenterConfig` 保存模型配置 |

### 各 Agent 的输入、提示词和终止条件

| Agent | 子类循环函数 | Role 配置 | 传入的关键参数 | 正常产物 |
| --- | --- | --- | --- | --- |
| Planner | `Planner.loop()` | `deeppresenter/roles/Planner.yaml` | `prompt`、`attachments` | 大纲 JSON |
| Research | `Research.loop()` | `deeppresenter/roles/Research.yaml` | `prompt`、`attachments`、`outline_path` | Markdown 文稿 |
| Design | `Design.loop()` | `deeppresenter/roles/Design.yaml` | `markdown_file`、设计要求 | `slides/` 目录 |
| PPTAgent | `PPTAgent.loop()` | `deeppresenter/roles/PPTAgent.yaml` | `markdown_file`、PPT 要求 | PPTX 文件 |
| SubAgent | `SubAgent.loop()` | `deeppresenter/roles/SubAgent.yaml` | `task`、`context` | 一个独立交付文件 |

结束不是由 Python 猜测文件是否生成，而是 Agent 在模型输出中调用 `finalize(outcome=...)`。该工具定义在 `deeppresenter/tools/task.py` 的 `finalize()`。

## 5. AgentEnv 与 MCP：模型如何获得行动能力

`AgentEnv` 是模型和外部能力之间的适配层。它不决定“做什么”，只负责连接服务、注册工具、校验参数、执行调用、把结果转换为可放回 LLM 上下文的消息。

```text
mcp.json
  |
  v
AgentEnv.__init__()：读取服务定义、注入 WORKSPACE 等运行变量
  |
  v
AgentEnv.__aenter__() -> connect_server()
  |
  v
MCPClient.connect_server() -> list_tools()
  |
  v
Agent._setup_toolset()：按角色筛选工具
  |
  v
LLM tool call -> Agent.execute() -> AgentEnv.tool_execute()
  |
  +-- 本地工具：_call_local_tool()
  +-- MCP 工具：_execute_tool_once() -> MCPClient.tool_execute()
```

| 环节 | 文件和函数 |
| --- | --- |
| 读取 MCP 服务定义 | `deeppresenter/agents/env.py`，`AgentEnv.__init__()`；数据模型在 `deeppresenter/utils/typings.py`，`MCPServer` |
| 建立/清理所有连接 | `deeppresenter/agents/env.py`，`AgentEnv.__aenter__()`、`AgentEnv.__aexit__()` |
| 单个服务的工具发现 | `deeppresenter/agents/env.py`，`connect_server()`；`deeppresenter/utils/mcp_client.py`，`MCPClient.connect_server()`、`list_tools()` |
| 注入本地工具 | `deeppresenter/agents/env.py`，`register_tool()`；多 Agent 时注册 `SubAgent.delegate()` |
| 参数校验与结果封装 | `deeppresenter/agents/env.py`，`tool_execute()` |
| 执行本地/MCP 工具 | `deeppresenter/agents/env.py`，`_call_local_tool()`、`_execute_tool_once()` |
| 异步工具模式 | `deeppresenter/agents/env.py`，`_execute_tool()`、`_register_async_tools()` |

`deeppresenter/mcp.json.example` 中重要的服务：

| 服务 | 实现或命令 | 典型职责 |
| --- | --- | --- |
| `any2markdown` | `deeppresenter/tools/any2markdown.py` | 将输入文件解析为 Markdown/图片资源 |
| `search` | `deeppresenter/tools/search.py`，`search_web()`、`search_images()` | 网络文本与图片检索 |
| `deeppresenter` | `deeppresenter/tools/reflect.py`，`inspect_manuscript()` 等 | 检查文稿与幻灯片工件 |
| `task` | `deeppresenter/tools/task.py`，`finalize()` | 返回最终交付物路径 |
| `tool_agents` | `deeppresenter/tools/tool_agents.py` | 图片生成、图像描述、文档摘要等模型型工具 |
| `sandbox` | Docker 容器配置 | 在任务工作区中执行文件和命令操作 |
| `pptagent` | `pptagent-mcp` | 使用旧模板生成引擎 |

## 6. 默认路线：Markdown 到 HTML，再到 PPTX/PDF

这是当前优先理解的路线。

### 6.1 Research 产出文稿

`Research.loop()` 每轮调用 `Agent.action()`，直到模型调用 `finalize`。其工作规范来自 `roles/Research.yaml`：

1. 调研主题和附件。
2. 收集并保存可用的本地图片素材。
3. 写 Markdown；每页用 `---` 分隔。
4. 图片链接必须是本地绝对路径。
5. 调用 `inspect_manuscript` 自检后，以 `finalize` 返回文稿路径。

应重点阅读：

- `deeppresenter/agents/research.py`，`Research.loop()`
- `deeppresenter/roles/Research.yaml`，系统提示词和工具选择
- `deeppresenter/utils/typings.py`，`InputRequest.deepresearch_prompt`
- `deeppresenter/tools/any2markdown.py`，输入附件转换
- `deeppresenter/tools/search.py`，调研能力
- `deeppresenter/tools/reflect.py`，`inspect_manuscript()`

### 6.2 Design 将文稿制作为幻灯片 HTML

`Design.loop()` 首先创建 `workspace/slides/`，之后同样进入 `action -> execute` 循环。实际的 HTML/CSS 由 Agent 通过 sandbox 写入，而非由一个 Python 排版函数拼接。

Role 中规定的产物和检查顺序是：

```text
Markdown 文稿
  -> slides/global.css                 统一视觉系统
  -> slides/slide_01.html              单页 HTML
  -> inspect_slide                     渲染/检查
  -> 修正 slide_01.html
  -> 下一页
  -> finalize(slides 目录)
```

应重点阅读：

- `deeppresenter/agents/design.py`，`Design.loop()`
- `deeppresenter/roles/Design.yaml`，固定画布、排版、安全字体、逐页检查的规则
- `deeppresenter/tools/reflect.py`，`inspect_slide` 对应的实现
- `deeppresenter/tools/task.py`，`finalize()`

### 6.3 导出

Design 完成后，`AgentLoop.run()` 负责导出而不是 Design Agent：

| 次序 | 函数 | 作用 |
| --- | --- | --- |
| 1 | `deeppresenter/utils/webview.py`，`convert_html_to_pptx()` | 调用 Node 转换器，HTML/CSS 变为 PPTX |
| 2 | `deeppresenter/html2pptx/html2pptx_cli.js` | Node 命令行入口 |
| 3 | `deeppresenter/html2pptx/html2pptx.js` | HTML/CSS 到 pptxgenjs 对象的主要转换实现 |
| 4 | `deeppresenter/utils/webview.py`，`PlaywrightConverter.convert_to_pdf()` | 用浏览器将各 HTML 页面渲染为 PDF |

若 HTML 到 PPTX 的转换报错，`AgentLoop.run()` 会记录 `.html2pptx-error.txt`，并至少输出 PDF。这是一个明确的降级路径。

## 7. 可选路线：旧 pptagent 模板生成

这条路线由 `convert_type == ConvertType.PPTAGENT` 触发。新架构中的 `deeppresenter/agents/pptagent.py` 并不直接操作 `python-pptx`，而是要求模型通过 MCP 调用 `pptagent-mcp` 暴露的工具。

```text
PPTAgent.loop()
  -> list_templates / 其他 pptagent MCP 工具
  -> pptagent/mcp_server.py: PPTAgentServer
  -> 旧 pptagent 的 PPTGen.generate_pres()
  -> Presentation.save()
  -> PPTX
```

旧引擎按两阶段理解：

| 阶段 | 核心文件和函数 | 做什么 |
| --- | --- | --- |
| Stage I，模板归纳 | `pptagent/induct.py`，`SlideInducter.category_split()`、`layout_split()`、`layout_induct()`、`content_induct()` | 分析参考 PPT：区分功能页、聚类布局、提取每种布局允许的内容 schema |
| Stage II，生成 | `pptagent/pptgen.py`，`PPTGen.generate_pres()` | 创建大纲、逐页生成、选择布局、生成/编辑/验证内容 |
| 布局选择 | `pptagent/pptgen.py`，`PPTAgent._select_layout()`；`pptagent/presentation/layout.py`，`Layout.validate()` | 选可匹配的模板布局，并校验内容是否符合 schema |
| 单页生成 | `pptagent/pptgen.py`，`PPTAgent.generate_slide()`、`_generate_content()`、`_edit_slide()`、`_validate_content()` | 生成每页结构化内容，必要时修改和校验 |
| PPTX 对象构建 | `pptagent/presentation/presentation.py`，`Presentation.from_file()`、`build_slide()`、`save()` | 读取模板、建立幻灯片、保存结果 |
| 图形对象映射 | `pptagent/presentation/shapes.py`，`ShapeElement.build()` 等 | 把抽象元素还原为 python-pptx 的文本、图片、形状 |

`pptagent/templates/` 中包含模板源文件 `source.pptx`、模板说明和预处理后的 `slide_induction.json`。学习旧栈时，拿一个模板目录与 `SlideInducter`、`PPTGen.set_reference()` 对照阅读最有效。

## 8. 一次运行后应该看哪些文件

每次生成后，优先进入该会话的工作区，而不是只看最终 PPTX：

```text
<workspace>/
  .input_request.json              原始请求和附件信息
  intermediate_output.json         各阶段产物路径索引
  .history/
    Research-history.jsonl         Research 的上下文和工具反馈
    Design-history.jsonl           Design 的上下文和工具反馈
    tool_history.jsonl             所有工具调用
    *-config.json                  使用的模型、工具、成本
  <manuscript>.md                  Research 交给 Design 的文稿
  slides/
    global.css                     统一视觉规范
    slide_01.html                  各页 HTML
  <manuscript>.pptx               最终可编辑演示文稿
  <manuscript>.pdf                浏览器渲染的预览/降级产物
```

排查或学习时的因果链是：

```text
最终某页不好
  -> 看 slides/slide_XX.html
  -> 看 Design-history.jsonl 中 inspect_slide 的反馈和修正
  -> 看 Markdown 中该页原始内容
  -> 看 Research-history.jsonl 的信息收集和文稿决策
```

## 9. 推荐阅读顺序和验收标准

### 第一轮：能讲清主流程

1. `pyproject.toml`：确认入口与依赖边界。
2. `deeppresenter/cli/__init__.py`、`deeppresenter/cli/commands.py` 的 `generate()`。
3. `deeppresenter/main.py` 的 `AgentLoop.run()`。
4. `Research.loop()`、`Design.loop()` 及对应 role YAML。
5. `Agent.action()`、`Agent.execute()`。
6. `AgentEnv.__aenter__()`、`connect_server()`、`tool_execute()`。
7. `convert_html_to_pptx()`、`PlaywrightConverter.convert_to_pdf()`。

完成后应能解释：为什么系统先生成 Markdown 再做设计，MCP 如何变成模型工具，以及 PPTX 为什么不是 Design Agent 直接生成的。

### 第二轮：跑一个最小任务并追踪工件

建议先用无附件、3 页的简单主题，避免检索和附件解析掩盖主链路：

```bash
pptagent generate "用三页介绍零知识证明" -o /tmp/zkp.pptx -p 3 -l zh
```

随后按第 8 节从 `intermediate_output.json` 开始，顺序阅读文稿、HTML、工具历史和最终文件。

### 第三轮：理解可选能力

1. 增加 `--planner`，观察大纲如何在 Research 之前插入。
2. 在配置中启用 `multiagent_mode`，阅读 `SubAgent.delegate()` 和 `SubAgent.loop()`。
3. 读取 `pptagent/mcp_server.py` 与 `pptagent/pptgen.py`，理解模板式路线。
4. 阅读 `pptagent/induct.py`，理解模板为何可以被复用。

## 10. 可直接复述的项目说明

> 当前 PPTAgent 的主产品是 DeepPresenter。用户通过 `pptagent generate` 创建一次独立工作区，`AgentLoop` 先可选地规划大纲，再由 Research Agent 通过 MCP 工具完成检索、附件解析和 Markdown 文稿。默认情况下，Design Agent 将该 Markdown 转成带统一 CSS 的逐页 HTML，通过检查工具反复修正，最后由 Node 转换器生成 PPTX，并由 Playwright 输出 PDF。另一条可选路线会通过 MCP 调用旧版 `pptagent`，按参考模板归纳出的布局 schema 生成 PPTX。它的核心模式是：LLM 负责决策，MCP/沙箱负责行动，工作区文件负责阶段间交接和可追溯性。
