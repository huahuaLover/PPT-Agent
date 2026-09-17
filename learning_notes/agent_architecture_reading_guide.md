# DeepPresenter Agent 架构阅读指南

## 学习目标

本指南聚焦 `deeppresenter/` 的 Agent 主链路，目标是理解：

- Agent 系统怎样搭建。
- 一个任务如何在多个 Agent 之间流转。
- 大模型如何选择并调用工具。
- MCP 工具怎样接入 Agent。
- 哪些架构设计值得借鉴。

旧的 `pptagent/`、CLI 安装流程和 HTML 转换细节暂时不属于学习重点。

## Agent 核心流程

```text
InputRequest
    ↓
AgentLoop：编排多个 Agent
    ↓
AgentEnv：准备 MCP 工具环境
    ↓
具体 Agent：Planner / Research / Design
    ↓
Agent.action()：调用模型
    ↓
模型返回 tool_calls
    ↓
Agent.execute()：执行工具
    ↓
工具结果写回 chat_history
    ↓
继续 action → execute
    ↓
finalize() 返回文件路径
    ↓
AgentLoop 将产物交给下一个 Agent
```

阅读过程中持续关注四个对象：

```text
InputRequest   当前任务是什么
chat_history   Agent 已经知道什么
tool_calls     Agent 接下来要做什么
outcome        当前阶段最终产生了什么
```

---

## 第一部分：核心编排

### 1. `deeppresenter/main.py`

首先阅读 `AgentLoop`，特别是 `AgentLoop.run()`。

需要理解：

- 工作区什么时候创建。
- `AgentEnv` 如何启动。
- Planner、Research、Design 如何串联。
- 一个 Agent 的输出如何成为下一个 Agent 的输入。
- 为什么使用异步生成器和 `yield`。
- 最终产物路径如何返回。

主要业务流程：

```text
Planner（可选）
    ↓ outline.json
Research
    ↓ manuscript.md
Design
    ↓ slides/*.html
转换
    ↓ final.pptx
```

值得借鉴：使用明确的编排器控制阶段顺序，而不是让模型自己决定整个系统流程。这让系统更容易调试、测试和控制。

---

## 第二部分：具体 Agent 的运行形态

### 2. `deeppresenter/agents/research.py`

### 3. `deeppresenter/agents/design.py`

这两个文件很短，但清晰展示了 Agent 的基本循环：

```python
while True:
    agent_message = await self.action(...)
    outcome = await self.execute(agent_message.tool_calls)

    if task_finished:
        break
```

对应的运行逻辑是：

```text
模型思考和决策
    ↓
调用工具
    ↓
观察工具结果
    ↓
再次思考
    ↓
完成任务
```

需要理解：

- `action()` 为什么负责调用模型。
- `execute()` 为什么负责执行工具。
- `outcome` 在什么情况下是工具消息列表。
- `outcome` 在什么情况下是最终产物路径。
- Research 和 Design 为什么可以复用同一个 Agent 基类。

值得借鉴：具体 Agent 只定义任务输入和循环，通用的模型调用、历史管理和工具执行都放在基类中。

---

## 第三部分：Agent 基类

### 4. `deeppresenter/agents/agent.py`

这是 Agent 技术实现的核心文件，建议按方法阅读。

### 4.1 `Agent.__init__()`

理解 Agent 如何初始化：

- 根据 Agent 类名加载角色 YAML。
- 根据 `use_model` 选择模型。
- 构建 system prompt。
- 根据 ToolSet 选择工具。
- 初始化 `chat_history`。

核心映射关系：

```text
Research 类
    ↓
Research.yaml
    ↓
research_agent 模型配置
    ↓
Research 可以使用的工具
```

### 4.2 `_setup_toolset()`

理解工具权限控制：

- Agent 可以使用哪些 MCP Server。
- 哪些工具需要排除。
- 如何生成传给模型的工具 schema。
- 为什么不同角色能看到不同工具。

### 4.3 `action()`

理解：

- Jinja2 Prompt 模板如何渲染。
- 用户消息如何加入历史。
- `chat_history` 如何发送给模型。
- 模型如何返回 `tool_calls`。
- token 使用量如何记录。

### 4.4 `execute()`

理解：

- 模型返回的工具调用如何执行。
- 多个工具是否并发执行。
- 工具结果如何转为 `ChatMessage`。
- 工具结果如何加入 `chat_history`。
- `finalize` 如何让 Agent 退出循环。

值得借鉴：模型只负责选择动作；权限、参数校验和真正的工具执行由确定性的代码负责。

---

## 第四部分：角色配置

### 5. `deeppresenter/roles/Research.yaml`

### 6. `deeppresenter/roles/Design.yaml`

### 7. `deeppresenter/roles/Planner.yaml`

每个角色 YAML 都包含四个重要部分：

```yaml
system:       # Agent 的身份、工作流程和约束
instruction:  # 每次任务使用的 Prompt 模板
use_model:    # 使用哪个模型配置
toolset:      # 允许调用哪些工具
```

阅读时需要回答：

- Agent 的职责来自 Python 还是 YAML？
- 运行时变量如何注入 `instruction`？
- `use_model` 如何对应 `config.yaml` 中的模型？
- Role 的 ToolSet 如何限制工具权限？
- Research 和 Design 的结束条件如何在 Prompt 中表达？

项目采用的分层方式是：

```text
Python：运行机制
YAML：角色和业务行为
Config：模型能力
MCP：外部工具能力
```

值得借鉴：将相对频繁变化的角色行为和提示词从 Python 代码中分离出来。

---

## 第五部分：工具执行环境

### 8. `deeppresenter/agents/env.py`

`AgentEnv` 是 Agent 和工具之间的执行环境。

重点阅读：

- `__init__()`：读取 MCP 配置并准备环境变量。
- `__aenter__()`：启动 MCP 服务并注册工具。
- `tool_execute()`：校验工具参数并执行工具。
- `_execute_tool()`：区分本地工具和 MCP 工具。
- 工具调用历史记录。
- 超长工具结果截断。
- 异步工具执行机制。

工具调用链路：

```text
模型产生 tool_call
    ↓
Agent.execute()
    ↓
AgentEnv.tool_execute()
    ↓
MCP Server 或本地函数
    ↓
工具执行结果
    ↓
ChatMessage
    ↓
模型继续推理
```

值得借鉴：Agent 不直接依赖搜索、浏览器或文档解析的具体实现，而是统一依赖工具协议。

---

## 第六部分：MCP 与任务结束协议

### 9. `deeppresenter/mcp.json.example`

这个文件定义：

- 有哪些 MCP Server。
- 每个服务如何启动。
- 启动时传入哪些参数和环境变量。
- 哪些服务需要网络。

需要区分两个概念：

```text
mcp.json：工具从哪里来、如何启动
Role YAML：哪个 Agent 可以使用哪些工具
```

### 10. `deeppresenter/tools/task.py`

重点阅读 `finalize()`。

Agent 完成任务时，不是直接让 Python 循环退出，而是让模型调用：

```text
finalize("manuscript.md")
```

随后：

```text
工具返回产物路径
    ↓
Agent.execute() 识别完成状态
    ↓
具体 Agent 退出 while 循环
    ↓
AgentLoop 接收产物路径
```

`finalize` 是模型世界和程序控制流之间的结束协议。

### 11. `deeppresenter/tools/reflect.py`

理解 Agent 如何检查自己生成的产物：

- 检查 Markdown 文稿。
- 检查单页 HTML。
- 将页面渲染结果反馈给多模态模型。
- 根据检查结果继续修改。

值得借鉴：将“生成”和“验证”分开，使 Agent 能观察产物并进行迭代修正。

---

## 第七部分：数据结构和模型调用

### 12. `deeppresenter/utils/typings.py`

重点阅读：

- `InputRequest`
- `ChatMessage`
- `RoleConfig`
- `ToolSet`
- `MCPServer`

其中最重要的是 `ChatMessage`，它统一表示：

- system 消息
- user 消息
- assistant 消息
- tool 消息

Agent 循环的状态主要保存在：

```python
self.chat_history: list[ChatMessage]
```

### 13. `deeppresenter/utils/config.py`

重点阅读：

- `Endpoint`
- `LLM`
- `LLM.call()`
- `DeepPresenterConfig`
- `DeepPresenterConfig.load_from_file()`

模型选择链路：

```text
Role YAML 中 use_model: research_agent
    ↓
DeepPresenterConfig.research_agent
    ↓
LLM
    ↓
Endpoint
    ↓
OpenAI 兼容接口或 LiteLLM
```

需要理解：

- 不同 Agent 如何使用不同模型。
- 工具 schema 如何传给模型。
- 模型如何返回 `tool_calls`。
- 多个模型端点如何重试。
- token 用量如何记录。

---

## 第八部分：多 Agent 机制（可选）

如果需要研究多 Agent，再阅读：

1. `deeppresenter/agents/subagent.py`
2. `deeppresenter/roles/SubAgent.yaml`
3. `AgentLoop` 中注册 `SubAgent.delegate()` 的代码

这里采用的设计是将子 Agent 包装成工具：

```text
主 Agent
    ↓
调用 delegate_subagent 工具
    ↓
创建 SubAgent
    ↓
SubAgent 独立执行任务
    ↓
执行结果作为工具观察返回主 Agent
```

值得借鉴：对子 Agent 的调用方式和普通工具调用保持一致，减少主 Agent 的额外控制逻辑。

---

## 推荐阅读顺序

严格按照以下顺序阅读：

```text
1.  deeppresenter/main.py
2.  deeppresenter/agents/research.py
3.  deeppresenter/agents/design.py
4.  deeppresenter/agents/agent.py
5.  deeppresenter/roles/Research.yaml
6.  deeppresenter/roles/Design.yaml
7.  deeppresenter/roles/Planner.yaml
8.  deeppresenter/agents/env.py
9.  deeppresenter/mcp.json.example
10. deeppresenter/tools/task.py
11. deeppresenter/tools/reflect.py
12. deeppresenter/utils/typings.py
13. deeppresenter/utils/config.py
14. deeppresenter/agents/subagent.py（可选）
```

## 暂时可以跳过

为了理解 Agent 框架，暂时不需要深入：

- `commands.py` 中庞大的 `onboard()`。
- `deeppresenter/cli/dependency.py`。
- `deeppresenter/html2pptx/`。
- `deeppresenter/utils/webview.py`。
- `pptagent/` 旧代码栈。
- 搜索和图片处理工具的具体实现。
- Docker 镜像构建细节。

这些内容主要属于基础设施或具体业务能力，不是 Agent 的核心机制。

## 最值得借鉴的设计

### 1. 显式编排

`AgentLoop` 决定阶段顺序，避免让模型完全控制业务流程。

### 2. 配置驱动角色

Python 实现通用机制，YAML 定义角色、提示词、模型选择和工具权限。

### 3. MCP 工具解耦

Agent 只依赖工具 schema，不直接依赖搜索、浏览器或文档解析实现。

### 4. 文件作为阶段契约

Research 返回 Markdown 路径，Design 返回 HTML 目录，减少不同 Agent 之间的直接依赖。

### 5. 子 Agent 工具化

主 Agent 通过统一的工具调用方式委派任务，不需要增加另一套通信协议。

### 6. 生成与验证分离

Agent 先生成产物，再通过反思和检查工具观察结果，根据反馈继续修改。

## 学习完成后的自测问题

- [ ] `AgentLoop`、`Agent` 和 `AgentEnv` 分别负责什么？
- [ ] 一个具体 Agent 为什么只需要很少的 Python 代码？
- [ ] Role YAML 如何决定 Agent 的模型、Prompt 和工具权限？
- [ ] 模型返回的 `tool_calls` 如何变成真正的函数执行？
- [ ] 工具执行结果如何重新进入模型上下文？
- [ ] `finalize()` 如何结束一个 Agent 循环？
- [ ] Research 的输出如何成为 Design 的输入？
- [ ] 子 Agent 为什么可以被视为一种工具？
- [ ] 哪些行为应该修改 Python，哪些应该修改 YAML？

能够完整回答这些问题，就已经掌握了 DeepPresenter Agent 系统的主要架构。
