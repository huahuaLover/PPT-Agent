# PPT 质量优化技术设计

## 1. 文档目的

本文档是 [PPT_QUALITY_REQUIREMENTS.md](PPT_QUALITY_REQUIREMENTS.md) 的实现规格。编码者应能够仅依据本文档完成第一版代码，不需要在实现阶段重新决定架构、接口或文件格式。

目标是先复现当前 `deeppresenter` 的 Design HTML/CSS 路线，而不是一次性引入旧版 `pptagent` 的模板归纳系统。

本文档中的“目标版本”指完成以下链路：

```text
Research Agent
→ manuscript.md
→ Design Agent
→ global.css + slide_XX.html
→ inspect_slide 验证和截图
→ HTML 转 PPTX/PDF
→ workspace/result.pptx
```

## 2. 参考实现与复用边界

必须参考以下原项目实现：

- `deeppresenter/roles/Design.yaml`：HTML 页面设计约束和逐页检查流程。
- `deeppresenter/tools/reflect.py`：`inspect_slide` 的验证及截图思路。
- `deeppresenter/utils/webview.py`：HTML 转 PPTX、PDF 和图片。
- `deeppresenter/html2pptx/`：Node.js HTML 到可编辑 PPTX 转换器。
- `deeppresenter/main.py`：PPTX 转换失败后保留 PDF 的流程。

目标版本直接复用 `deeppresenter.utils.webview`，不复制 `html2pptx.js`，避免 Demo 与原项目维护两份转换器。

不复用原项目完整 `Agent`、`AgentEnv` 或配置系统。Demo 继续使用自己的小型 Agent/MCP 实现，保证代码可读性。

## 3. 固定技术决策

以下决策不得在编码时随意更换：

1. 第一版仍然只有 `Research` 和 `Design` 两个 Agent。
2. `inspect_slide` 是 MCP 工具，不新增 Critic Agent。
3. Design 最终产物由 `result.pptx` 改为 `slides/` 目录。
4. Design 逐页写 HTML，每页写完后必须调用 `inspect_slide`。
5. HTML 到 PPTX/PDF 的最终导出由主进程完成，不让模型调用导出工具。
6. PPTX 使用原项目 `convert_html_to_pptx()` 生成，PDF 使用 `PlaywrightConverter` 生成。
7. 所有页面固定为 16:9、`1280 × 720`。
8. 图片必须先下载到 workspace，HTML 禁止引用远程图片 URL。
9. `inspect_slide` 成功状态必须绑定 HTML 文件哈希。HTML 修改后必须重新检查。
10. 工具按顺序执行，不能并发执行 `write_file → inspect_slide → finalize`。

## 4. 目标目录结构

在现有 Demo 中新增一个文件：

```text
examples/mcp_agent_demo/
├── conversion.py                         # 新增：最终导出适配器
├── main.py                               # 修改：Design 后执行导出
├── models.py                             # 修改：运行配置、图片 observation
├── agent.py                              # 修改：目录产物、图片反馈、重试
├── agents.py                             # 修改：Design 终止条件
├── env.py                                # 修改：接收 MCP ImageContent
├── tools/server.py                       # 修改：inspect_slide、图片工具、目录 finalize
├── roles/Research.yaml                   # 修改：图文研究规则
├── roles/Design.yaml                     # 修改：HTML/CSS 和逐页检查规则
├── config.yaml.example                   # 修改：新增质量配置
└── requirements.txt                      # 修改：转换和图片依赖
```

不新增新的 Agent 文件，不拆分多个 MCP Server。等目标链路稳定后再考虑拆分。

## 5. 目标运行时架构

```text
CLI
 │
 ▼
AgentLoop
 ├── AgentEnv ──stdio── tools/server.py
 │      │                    ├── search_web
 │      │                    ├── search_images
 │      │                    ├── download_file
 │      │                    ├── read_file
 │      │                    ├── write_file
 │      │                    ├── inspect_slide
 │      │                    └── finalize
 │      │
 │      ├── Research Agent → manuscript.md + assets/
 │      └── Design Agent   → slides/ + previews/
 │
 └── conversion.py
        ├── convert_html_to_pptx → result.pptx
        └── PlaywrightConverter  → result.pdf
```

Agent 只决定调用哪些 MCP 工具。路径保护、下载、HTML 检查和文件状态记录由 MCP Server 完成。最终导出是固定步骤，不由模型决定。

## 6. 配置设计

### 6.1 `config.yaml`

在现有配置上增加以下字段：

```yaml
research_agent:
  base_url: "https://your-provider/v1"
  model: "your-research-model"
  api_key: "your-key"
  temperature: 0.2
  max_turns: 12
  max_retries: 3
  supports_vision: false

design_agent:
  base_url: "https://your-provider/v1"
  model: "your-design-model"
  api_key: "your-key"
  temperature: 0.2
  max_turns: 40
  max_retries: 3
  supports_vision: true

search:
  api_key: "your-tavily-key"
  max_results: 5
  max_content_chars: 1500
  max_image_results: 4

runtime:
  workspace_base: "workspace"
  mcp_config_file: "mcp.json"
  aspect_ratio: "16:9"
  max_slide_revisions: 3
  enable_visual_review: true
  tool_timeout_seconds: 120
  soft_parsing: false
```

Design 的 `max_turns` 必须高于当前值。逐页生成和检查会消耗多轮，5 页演示文稿通常至少需要 12 次工具交互。

### 6.2 Pydantic 模型

在 `models.py` 中修改为：

```python
class ModelConfig(BaseModel):
    base_url: str | None = None
    model: str = Field(min_length=1)
    api_key: SecretStr = Field(min_length=1)
    temperature: float | None = Field(default=0.2, ge=0, le=2)
    max_turns: int = Field(default=10, gt=0)
    max_retries: int = Field(default=3, ge=1, le=5)
    supports_vision: bool = False


class SearchConfig(BaseModel):
    api_key: SecretStr = Field(min_length=1)
    max_results: int = Field(default=5, ge=1, le=10)
    max_content_chars: int = Field(default=1500, ge=300, le=5000)
    max_image_results: int = Field(default=4, ge=1, le=8)


class RuntimeConfig(BaseModel):
    workspace_base: Path = Path("workspace")
    mcp_config_file: Path = Path("mcp.json")
    aspect_ratio: Literal["16:9"] = "16:9"
    max_slide_revisions: int = Field(default=3, ge=1, le=8)
    enable_visual_review: bool = True
    tool_timeout_seconds: int = Field(default=120, ge=30, le=600)
    soft_parsing: bool = False
```

第一版仅开放 `16:9`，避免提示词、HTML 尺寸、检查器和导出器出现多套尺寸分支。

### 6.3 工具图片模型

新增：

```python
class ToolImage(BaseModel):
    mime_type: str
    data: str  # 原始 base64，不包含 data: 前缀


class ToolObservation(BaseModel):
    tool_call_id: str
    tool_name: str
    text: str
    images: list[ToolImage] = Field(default_factory=list)
    is_error: bool = False
    arguments: dict[str, Any] = Field(default_factory=dict)
```

工具历史不能保存 `ToolImage.data`，只记录图片数量、MIME 类型和预览文件路径。

### 6.4 导出结果模型

新增：

```python
class ExportResult(BaseModel):
    final_path: Path
    pptx_path: Path | None
    pdf_path: Path
    preview_dir: Path
    pptx_error: str | None = None
```

当 PPTX 成功时，`final_path == pptx_path`；PPTX 失败但 PDF 成功时，`final_path == pdf_path`。

## 7. workspace 文件协议

### 7.1 Research 文稿协议

`manuscript.md` 使用单独一行 `---` 分页，每个页面必须包含：

```markdown
## 页面标题

**核心结论：** 一句话表达本页观点。

- 支撑信息一
- 支撑信息二

![图片用途和内容说明](assets/example.png)

来源：https://example.com/source
```

图片不是每页必需，但所有图片必须是 workspace 内的本地文件。

### 7.2 HTML 文件协议

每页必须是完整 HTML 文档，最小结构如下：

```html
<!doctype html>
<html lang="zh-CN">
  <head>
    <meta charset="utf-8" />
    <link rel="stylesheet" href="./global.css" />
  </head>
  <body>
    <main class="slide slide--two-column">
      <section class="slide__content">
        <h1>页面标题</h1>
        <p>页面内容</p>
      </section>
    </main>
  </body>
</html>
```

`global.css` 必须包含固定画布：

```css
html,
body {
  width: 1280px;
  height: 720px;
  margin: 0;
  overflow: hidden;
}

* {
  box-sizing: border-box;
}
```

HTML/CSS 约束：

- 禁止 JavaScript、动画、表单和交互控件。
- 禁止远程 CSS、网络字体和远程图片。
- 文本必须放在 `h1`～`h6`、`p`、`span`、`li` 等语义元素中。
- 列表必须使用 `ul` 或 `ol`。
- 正文字号不得小于 `18px`。
- 完整展示的图片使用 `object-fit: contain`。
- 背景和装饰图片可以使用 `object-fit: cover`，但必须保证文字对比度。
- 图片路径使用相对于 HTML 文件的路径，例如 `../assets/chart.png`。
- 不使用转换器无法稳定映射到 PowerPoint 的网页交互特性。

### 7.3 页面命名协议

用户请求 `N` 页时，必须正好生成：

```text
slides/slide_01.html
slides/slide_02.html
...
slides/slide_NN.html
```

不允许缺号、重复编号或额外 HTML 文件。最终导出严格按文件名排序。

### 7.4 检查状态文件

MCP Server 维护：

```text
slides/.inspection.json
```

格式：

```json
{
  "slide_01.html": {
    "status": "passed",
    "attempts": 2,
    "sha256": "...",
    "preview": "previews/slide_01.jpg",
    "last_error": null
  }
}
```

每次检查前计算 HTML 和 `global.css` 内容的组合 SHA-256：

```python
digest = sha256(html_bytes + b"\0" + css_bytes).hexdigest()
```

这样修改页面或全局 CSS 后，旧检查结果自动失效。

## 8. MCP Server 设计

### 8.1 Server 初始化

修改 `tools/server.py`：

```python
from deeppresenter.utils.webview import (
    PlaywrightConverter,
    convert_html_to_pptx,
    playwright_lifespan,
)

mcp = FastMCP(
    "MCP Agent Demo Tools",
    lifespan=playwright_lifespan,
)
```

保留 `stdio_compat.install_if_needed()`。MCP Server 退出时必须通过 lifespan 关闭共享 Chromium。

`env.py` 启动 Server 时新增环境变量：

```python
{
    "SEARCH_MAX_CONTENT_CHARS": str(config.search.max_content_chars),
    "SEARCH_MAX_IMAGE_RESULTS": str(config.search.max_image_results),
    "MAX_SLIDE_REVISIONS": str(config.runtime.max_slide_revisions),
    "ENABLE_VISUAL_REVIEW": str(
        config.runtime.enable_visual_review
        and config.design_agent.supports_vision
    ).lower(),
    "ASPECT_RATIO": config.runtime.aspect_ratio,
}
```

### 8.2 `search_web`

保留现有接口：

```python
async def search_web(query: str, max_results: int = 5) -> str:
```

将当前硬编码的 `[:1000]` 改为读取 `SEARCH_MAX_CONTENT_CHARS`：

```python
content_limit = int(os.environ["SEARCH_MAX_CONTENT_CHARS"])
content = str(item.get("content", ""))[:content_limit]
```

返回内容必须只包含 `title`、`url` 和截断后的 `content`。

### 8.3 `search_images`

新增：

```python
@mcp.tool()
async def search_images(query: str, max_results: int = 4) -> str:
    """Search for relevant images and return URLs with descriptions."""
```

调用 Tavily：

```python
response = await asyncio.to_thread(
    client.search,
    query=query,
    max_results=effective_limit,
    include_images=True,
    include_image_descriptions=True,
    include_raw_content=False,
)
```

统一返回：

```json
{
  "query": "...",
  "images": [
    {
      "url": "https://...",
      "description": "..."
    }
  ]
}
```

兼容 Tavily 返回图片字符串或对象两种形式。字符串使用空 `description`；对象读取 `url` 和 `description`。忽略缺少 HTTP(S) URL 的项目。

### 8.4 `download_file`

新增：

```python
@mcp.tool()
async def download_file(url: str, output_path: str) -> str:
```

实现规则：

1. 只接受 `http` 和 `https` URL。
2. `output_path` 必须通过 `resolve_workspace_path()`。
3. 只允许写入 `assets/` 目录。
4. 使用 `httpx.AsyncClient(follow_redirects=True, timeout=30)`。
5. 响应体最大 10 MB，超过立即失败。
6. 使用 Pillow 打开并 `verify()`，拒绝非图片内容。
7. 允许 PNG、JPEG 和 WEBP；WEBP 统一转换为 PNG。
8. 返回 JSON 字符串，包含相对路径、宽度、高度和来源 URL。

返回示例：

```json
{
  "path": "assets/grid.png",
  "width": 1600,
  "height": 900,
  "source_url": "https://..."
}
```

依赖新增 `httpx` 和 `Pillow`。

### 8.5 `inspect_slide`

签名：

```python
@mcp.tool()
async def inspect_slide(
    html_file: str,
    expected_pages: int,
) -> list[TextContent | ImageContent]:
```

执行顺序固定如下：

1. 使用 `resolve_workspace_path()` 解析路径。
2. 要求路径位于 `slides/`，后缀为 `.html`，文件名匹配 `slide_\d{2}.html`。
3. 要求 `slides/global.css` 存在且非空。
4. 要求页码处于 `1..expected_pages`。
5. 从 `.inspection.json` 读取该页检查次数；超过 `MAX_SLIDE_REVISIONS` 时抛出错误。
6. 调用 `convert_html_to_pptx(html_path, aspect_ratio="16:9")`。因为不传输出文件，该调用只执行原项目 HTML/PPTX 兼容性检查。
7. 使用 `PlaywrightConverter.convert_to_pdf()` 将单页渲染到临时 PDF 和 JPG。
8. 将 JPG 复制为 `previews/slide_XX.jpg`。
9. 更新 `.inspection.json`，状态为 `passed`，写入组合哈希和预览路径。
10. 返回文本结果；开启视觉检查时同时返回 JPG 的 MCP `ImageContent`。

成功文本采用 JSON：

```json
{
  "status": "passed",
  "html": "slides/slide_01.html",
  "preview": "previews/slide_01.jpg",
  "attempt": 1
}
```

视觉检查开启时：

```python
return [
    TextContent(type="text", text=json.dumps(result)),
    ImageContent(
        type="image",
        data=base64.b64encode(image_bytes).decode("ascii"),
        mimeType="image/jpeg",
    ),
]
```

检查失败时必须先将 `status="failed"`、`attempts` 和 `last_error` 写入状态文件，再重新抛出异常，让 MCP 返回 `isError=True`。不得吞掉转换错误。

原项目转换器可以确定性检查：

- body 横向或纵向溢出。
- 页面尺寸不一致。
- 文本框距离底部过近。
- 图片或背景图片缺失。
- HTML 元素无法转换。

“视觉是否美观”和一般元素重叠不由此函数写启发式规则判断，而由多模态 Design 模型根据截图判断，避免嵌套 DOM 产生大量误报。

### 8.6 `finalize`

目标签名：

```python
@mcp.tool()
def finalize(outcome: str, expected_pages: int | None = None) -> str:
```

Research 调用：

```json
{"outcome": "manuscript.md"}
```

Design 调用：

```json
{"outcome": "slides", "expected_pages": 5}
```

文件产物沿用现有非空检查。目录产物必须满足：

1. `outcome` 必须严格等于 `slides`。
2. `expected_pages` 必须为 `2..20`。
3. `global.css` 存在且非空。
4. HTML 文件数量等于 `expected_pages`。
5. 文件名从 `slide_01.html` 连续到 `slide_NN.html`。
6. 每页在 `.inspection.json` 中都是 `passed`。
7. 每页当前组合哈希与检查时哈希一致。

任何条件不满足都返回工具错误，Design Agent 根据 observation 修正。

### 8.7 移除旧渲染工具

目标链路通过验收后，从 Design 白名单和 `server.py` 删除：

```text
create_pptx
load_slide_spec
set_text_size
```

迁移期间可以保留这些函数，但 Design 角色不得再看到 `create_pptx`，避免模型混用两条流程。

## 9. `AgentEnv` 图片结果处理

当前 `AgentEnv.call_tool()` 会拒绝所有非 `TextContent`。改为：

```python
texts: list[str] = []
images: list[ToolImage] = []

for block in result.content:
    if isinstance(block, TextContent):
        texts.append(block.text)
    elif isinstance(block, ImageContent):
        images.append(
            ToolImage(
                mime_type=block.mimeType,
                data=block.data,
            )
        )
    else:
        raise ValueError(
            f"Unsupported MCP content block: {type(block).__name__}"
        )
```

构造：

```python
ToolObservation(
    tool_call_id=tool_call_id,
    tool_name=tool_name,
    text="\n".join(texts).strip(),
    images=images,
    is_error=bool(result.isError),
    arguments=arguments,
)
```

`_record()` 只记录：

```json
{
  "image_count": 1,
  "image_mime_types": ["image/jpeg"]
}
```

禁止将 base64 写入 `tool-history.jsonl`。

工具超时从硬编码 60 秒改为：

```python
timeout=config.runtime.tool_timeout_seconds
```

## 10. Agent 对话图片处理

### 10.1 工具消息顺序

OpenAI Tool Calling 要求 assistant 发出的每个 `tool_call_id` 都有对应的 tool 消息。`execute()` 必须先追加本轮所有工具文本结果，再追加截图消息：

```python
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
```

不能在多个 tool 结果之间插入 user 图片消息。

### 10.2 图片反馈格式

`_append_observation_images()`：

```python
def _append_observation_images(self, observation: ToolObservation) -> None:
    if not observation.images:
        return
    content: list[dict[str, Any]] = [
        {
            "type": "text",
            "text": (
                "Rendered preview from inspect_slide. "
                "Review hierarchy, spacing, clipping, overlap, contrast, "
                "and image cropping. Fix the HTML and inspect again if needed."
            ),
        }
    ]
    for image in observation.images:
        content.append(
            {
                "type": "image_url",
                "image_url": {
                    "url": f"data:{image.mime_type};base64,{image.data}"
                },
            }
        )
    self.chat_history.append({"role": "user", "content": content})
```

如果 `design_agent.supports_vision` 为 `false`，Server 不返回图片，Agent 只收到确定性验证文本。

### 10.3 历史落盘

`save_history()` 不能直接写 base64。保存前深拷贝消息，并将：

```text
data:image/jpeg;base64,<内容>
```

替换为：

```text
<image omitted; see previews/slide_XX.jpg>
```

内存中的 `chat_history` 不修改，否则后续模型无法看到截图。

## 11. Agent 终止协议修改

当前 `Agent` 只支持通过后缀检查文件。修改构造参数：

```python
def __init__(
    ...,
    expected_outcome_name: str,
    expected_outcome_kind: Literal["file", "directory"],
    expected_suffix: str | None,
    required_tools_before_finalize: set[str],
) -> None:
```

Research 配置：

```python
expected_outcome_name="manuscript.md"
expected_outcome_kind="file"
expected_suffix=".md"
required_tools_before_finalize={"search_web", "write_file"}
```

Design 配置：

```python
expected_outcome_name="slides"
expected_outcome_kind="directory"
expected_suffix=None
required_tools_before_finalize={"read_file", "write_file", "inspect_slide"}
```

`_validate_finalize_arguments()` 必须检查 outcome 与当前 Agent 的 `expected_outcome_name` 完全一致。Design 还必须检查 `expected_pages` 是整数。

`_validate_final_path()`：

- file 类型要求 `is_file()`、非空和后缀正确。
- directory 类型要求 `is_dir()`。
- 两种类型都要求路径位于当前 workspace。
- MCP `finalize` 已负责详细页面状态检查，Agent 不重复解析 `.inspection.json`。

## 12. 模型请求重试

在 `Agent.action()` 中增加显式重试。为了避免 SDK 与业务层重复重试，创建 `AsyncOpenAI` 时设置：

```python
AsyncOpenAI(
    api_key=...,
    base_url=...,
    max_retries=0,
    timeout=120,
)
```

重试范围：

- 网络连接错误。
- 请求超时。
- HTTP 429。
- HTTP 500、502、503、504。

不重试 400、401、403、404。

退避时间固定为：

```python
delay = min(2 ** attempt, 8)  # 1、2、4、8 秒
```

最多尝试 `model_config.max_retries` 次。每次失败写入：

```text
history/run-errors.jsonl
```

日志包含时间、Agent、阶段、尝试次数、异常类型和状态码，不包含请求 Header、API Key 或完整图片 base64。

## 13. `conversion.py` 设计

新增文件并实现唯一公开函数：

```python
async def export_slides(
    slides_dir: Path,
    workspace: Path,
    expected_pages: int,
    aspect_ratio: Literal["16:9"],
    soft_parsing: bool,
) -> ExportResult:
```

执行步骤：

1. `slides_dir` 和 `workspace` 调用 `resolve()`。
2. 验证 `slides_dir` 位于 workspace，且 HTML 文件数量、命名和页数正确。
3. 调用：

   ```python
   await convert_html_to_pptx(
       slides_dir,
       workspace / "result.pptx",
       aspect_ratio=aspect_ratio,
       soft_parsing=soft_parsing,
   )
   ```

4. PPTX 失败时将异常和 traceback 写入 `workspace/.html2pptx-error.txt`，但继续生成 PDF。
5. 使用：

   ```python
   async with PlaywrightConverter() as converter:
       image_dir = await converter.convert_to_pdf(
           html_files,
           workspace / "result.pdf",
           aspect_ratio,
       )
   ```

6. 将 `image_dir/slide_XX.jpg` 覆盖复制到 `workspace/previews/`，保证最终预览与批量导出一致。
7. 在 `finally` 中调用 `await PlaywrightConverter.shutdown()`。
8. 使用 `python-pptx` 验证 PPTX 页数；使用 `pypdf.PdfReader` 验证 PDF 页数。
9. PPTX 成功则返回 PPTX；否则返回 PDF。PDF 失败属于不可恢复错误，直接抛出。

不要在 `conversion.py` 中调用模型或 MCP。

## 14. `AgentLoop` 修改

目标流程：

```python
async with AgentEnv(...) as env:
    manuscript_path = await run_research(...)
    slides_dir = await run_design(...)

export = await export_slides(
    slides_dir=slides_dir,
    workspace=self.workspace,
    expected_pages=request.pages,
    aspect_ratio=self.config.runtime.aspect_ratio,
    soft_parsing=self.config.runtime.soft_parsing,
)
```

不要求真的抽取 `run_research()` 和 `run_design()` 私有方法；保持当前代码长度可读时可以继续写在 `run()` 中。

`intermediate_output.json` 目标格式：

```json
{
  "manuscript": "/abs/workspace/manuscript.md",
  "slides_dir": "/abs/workspace/slides",
  "preview_dir": "/abs/workspace/previews",
  "pptx": "/abs/workspace/result.pptx",
  "pdf": "/abs/workspace/result.pdf",
  "final": "/abs/workspace/result.pptx"
}
```

如果 PPTX 失败，省略 `pptx`，`final` 指向 PDF，并保留 `pptx_error`。

CLI 的 `--output` 行为保持不变：未指定时使用 workspace 中的 final；指定时额外复制。复制时保留实际后缀，若 final 是 PDF 而用户指定 `.pptx`，必须报错，不能把 PDF 内容写成 `.pptx` 文件。

## 15. 角色配置

### 15.1 Research 工具白名单

目标：

```yaml
tools:
  - search_web
  - search_images
  - download_file
  - write_file
  - finalize
```

提示词必须要求：

- 每页一个核心观点。
- 文字和图片都属于内容素材。
- 只引用已经下载成功的本地图片。
- 图片 alt 文本描述图片类型、内容和用途。
- 保留图片与事实来源 URL。
- 最终调用 `finalize(outcome="manuscript.md")`。

### 15.2 Design 工具白名单

目标：

```yaml
tools:
  - read_file
  - write_file
  - inspect_slide
  - finalize
```

提示词必须包含固定工作流：

```text
read manuscript.md
→ write slides/global.css
→ write slide_01.html
→ inspect_slide(slide_01.html)
→ 必要时修改并复检
→ 下一页
→ finalize(outcome="slides", expected_pages=N)
```

提示词还必须包含第 7.2 节 HTML/CSS 约束，并明确：

- 每次只生成一页。
- 当前页检查通过前不得生成下一页。
- `global.css` 修改后所有页面检查状态都会失效，完成第一页后尽量不要再修改全局样式。
- 不得直接调用原来的 `create_pptx`。

## 16. 依赖和安装

Python 依赖在 Demo `requirements.txt` 增加：

```text
httpx
Pillow
playwright>=1.55.0
pdf2image
pypdf>=6.1.1
fake-useragent>=2.2.0
```

因为转换器直接复用仓库的 `deeppresenter`，推荐在仓库根目录安装：

```bash
uv sync
```

系统和 Node 依赖：

```bash
playwright install chromium
npm install --prefix deeppresenter/html2pptx
```

Linux 生成 PDF 预览还需要 Poppler：

```bash
sudo apt install poppler-utils
```

代码不能在普通运行阶段自动执行 `sudo`、`npm install` 或下载浏览器。缺少依赖时应给出明确安装命令。

## 17. 实施顺序

必须按以下顺序提交，保证每一步都可以独立验证：

### 里程碑 1：HTML 产物

1. 修改配置模型。
2. 修改 Design 角色为 HTML/CSS 工作流。
3. 修改 Design 最终产物为 `slides/`。
4. 暂时实现只做转换验证、不返回图片的 `inspect_slide`。
5. 验证 Design 能生成正确数量的 HTML 文件。

### 里程碑 2：最终导出

1. 新增 `conversion.py`。
2. 修改 `AgentLoop` 调用导出。
3. 验证 PPTX、PDF 和预览图片。
4. 验证 PPTX 失败时 PDF 降级。

### 里程碑 3：视觉反馈

1. 扩展 `ToolObservation`。
2. 修改 `AgentEnv` 接收 `ImageContent`。
3. 修改 Agent 将截图发送给 Design 模型。
4. 清理历史中的 base64。

### 里程碑 4：图文 Research

1. 增加 `search_images`。
2. 增加安全的 `download_file`。
3. 修改 Research 提示词。
4. 验证本地图片能够进入 HTML 和 PPTX。

### 里程碑 5：可靠性

1. 增加模型重试。
2. 增加错误日志。
3. 完成搜索结果长度配置。
4. 增加完整集成测试和对比样例。

## 18. 测试设计

### 18.1 单元测试

新增 `test/` 目录，至少包含：

```text
test_models.py
test_server_paths.py
test_inspection_state.py
test_agent_observations.py
test_conversion.py
```

必须覆盖：

- 新配置字段的边界校验。
- workspace 路径穿越被拒绝。
- 超长搜索内容被截断。
- 非图片下载被拒绝。
- HTML 命名不连续时 finalize 失败。
- 未 inspect 的页面不能 finalize。
- HTML 或 global.css 修改后旧哈希失效。
- MCP 图片不会写入工具历史。
- 多个工具调用时，所有 tool 消息都位于 user 图片消息之前。
- PPTX/PDF 页数校验。

网络、模型和 Tavily 在单元测试中使用 stub，不调用真实服务。

### 18.2 MCP 集成测试

启动真实 stdio Server，依次调用：

```text
write_file(global.css)
→ write_file(slide_01.html)
→ inspect_slide(slide_01.html)
→ finalize(slides)
```

验证 `TextContent`、可选 `ImageContent`、预览文件和检查状态。

### 18.3 转换集成测试

使用固定的两页 HTML fixture：

```text
封面页
双栏内容页
```

验证：

- `result.pptx` 可由 `python-pptx` 打开且为 2 页。
- `result.pdf` 可由 `pypdf` 打开且为 2 页。
- `previews/` 包含两张非空 JPG。
- 故意制造 body overflow 时 `inspect_slide` 返回错误。
- 删除图片时 `inspect_slide` 返回明确缺失路径。

### 18.4 真实端到端测试

选择三类主题，每类生成 5 页：

```text
企业介绍
技术原理
数据分析
```

每次记录：

- Research 和 Design token。
- 总耗时。
- 每页检查次数。
- PPTX 是否成功。
- PDF 是否成功。
- 人工检查的溢出、重叠、图片相关性和风格一致性。

不得只用一个成功样例宣布达到原项目效果。

## 19. 验收命令

静态检查：

```bash
.venv/bin/ruff format examples/mcp_agent_demo
.venv/bin/ruff check examples/mcp_agent_demo
.venv/bin/ruff format --check examples/mcp_agent_demo
```

单元测试：

```bash
.venv/bin/pytest examples/mcp_agent_demo/test -q
```

依赖检查：

```bash
node --version
npm --version
.venv/bin/playwright install --dry-run chromium
pdfinfo -v
```

端到端运行：

```bash
uv run python examples/mcp_agent_demo/main.py \
  "介绍大模型 Agent 的工作流程" \
  --pages 5
```

## 20. 完成定义

只有同时满足以下条件，才能认为目标版本完成：

1. Research 和 Design 仍通过当前 Agent/MCP 循环工作。
2. Design 严格逐页生成 HTML 并执行检查。
3. 每页均有与当前文件哈希匹配的 `passed` 状态。
4. PPTX、PDF、HTML、预览图和历史全部保存在 workspace。
5. PPTX 和 PDF 页数与用户请求一致。
6. 真实样例不存在明显溢出、图片缺失或不可打开的文件。
7. 多模态关闭时，确定性检查和导出仍能工作。
8. 模型或 PPTX 转换临时失败时，有重试、日志或 PDF 降级路径。
9. API Key 和图片 base64 未写入日志。
10. 第 18 节测试全部通过。

完成此版本后，Demo 才进入“超过原项目”的下一阶段；下一阶段再讨论独立 Planner、质量评分器、模板学习和自动布局评测。
