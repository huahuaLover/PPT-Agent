# PPT 质量优化需求方案

对应实现规格参见 [PPT_QUALITY_TECHNICAL_DESIGN.md](PPT_QUALITY_TECHNICAL_DESIGN.md)。

## 1. 背景

当前 Demo 已经跑通以下流程：

```text
用户请求
→ Research Agent 搜索并生成 manuscript.md
→ Design Agent 生成 slides.json
→ create_pptx 生成 result.pptx
```

现有 `create_pptx` 仅支持标题页和“标题 + 项目符号”内容页，能够验证 Agent、MCP 和工具反馈闭环，但视觉效果、页面多样性和信息表达能力明显弱于原项目。

本次优化先复现 `deeppresenter` 当前 Design 路线的核心能力，再基于稳定的基线继续提升。第一阶段不追求重新设计一套更复杂的架构。

## 2. 总体目标

将 Demo 的 PPT 生成流程升级为：

```text
Research 生成图文文稿
→ Design 制定全局视觉方案
→ 逐页生成 HTML/CSS
→ inspect_slide 检查并反馈
→ Design 根据反馈修改
→ HTML 转换为 PPTX
→ 转换失败时保留 PDF
```

最终生成结果应在页面布局、视觉一致性、图片使用和可读性方面达到原项目 Design 路线的基本效果，同时保留 Demo 代码清晰、流程显式、便于学习的特点。

## 3. 基本原则

1. 先模仿原项目已经验证的工作流，再进行结构创新。
2. 保留当前 `Agent → AgentEnv → MCP Server` 的交互方式。
3. Design Agent 负责设计决策，渲染和检查工具负责确定性执行。
4. 每页必须经过实际渲染检查，不能只验证源文件格式。
5. 中间产物全部保存在当前 session 的 workspace 中。
6. 每个阶段能够独立排查，失败时保留 HTML、截图、日志和错误信息。

## 4. 目标产物

每次成功运行至少生成：

```text
workspace/<session-id>/
├── manuscript.md
├── slides/
│   ├── global.css
│   ├── slide_01.html
│   ├── slide_02.html
│   └── ...
├── previews/
│   ├── slide_01.jpg
│   ├── slide_02.jpg
│   └── ...
├── result.pptx
├── result.pdf
├── intermediate_output.json
└── history/
```

`result.pptx` 是主要交付物；`result.pdf` 用于视觉预览和转换失败时的降级交付。

## 5. 分阶段需求

### 5.1 阶段一：HTML/CSS 幻灯片

Design Agent 不再以 `slides.json` 作为最终设计产物，而是：

1. 读取 `manuscript.md`。
2. 根据主题、受众和内容制定全局视觉方案。
3. 将配色、字体、背景和通用组件样式写入 `slides/global.css`。
4. 按文稿顺序逐页生成 `slides/slide_XX.html`。
5. 所有页面使用固定 16:9 画布，默认尺寸为 `1280 × 720`。
6. 每个 HTML 文件必须引用 `global.css`，但页面布局可以独立设计。

页面设计至少支持以下表达形式：

- 封面页。
- 章节过渡页。
- 单栏重点信息页。
- 双栏对比页。
- 图文组合页。
- 数据卡片页。
- 时间线或流程页。
- 总结页。

Design Agent 应根据内容语义选择版式，不得要求所有页面使用同一种结构。

### 5.2 阶段二：HTML 转 PPTX/PDF

系统应参考并复用原项目的转换能力：

- `deeppresenter/utils/webview.py`
- `deeppresenter/html2pptx/`

转换流程要求：

1. 按文件名顺序读取 `slide_XX.html`。
2. 将全部页面转换为 `result.pptx`。
3. 同时生成 `result.pdf` 和逐页预览图片。
4. PPTX 转换失败时记录完整错误，并保留 PDF 作为降级结果。
5. 输出页数必须与用户请求一致。

### 5.3 阶段三：单页检查与自动修正

新增 `inspect_slide` MCP 工具。Design Agent 每生成一页后必须立即调用该工具。

`inspect_slide` 至少检查：

- HTML 能否正常加载。
- 页面能否完成转换和截图。
- 内容是否超出 16:9 画布。
- 是否存在明显文字或元素重叠。
- 是否存在缺失的本地图片。
- 字体是否过小。
- 页面是否存在异常空白或内容过度拥挤。

如果检查失败：

```text
inspect_slide 返回明确问题
→ observation 写入 chat_history
→ Design Agent 修改对应 HTML
→ 再次调用 inspect_slide
```

只有当前页通过检查后，Design Agent 才能继续下一页。单页修正次数需要设置上限，避免无限循环。

### 5.4 阶段四：图片与视觉素材

Research Agent 应从“只研究文字”升级为“研究内容和视觉素材”。

需要增加：

- 图片搜索工具。
- 图片下载工具。
- 图片尺寸、比例和格式检查。
- 图片说明和来源记录。

Research 在 `manuscript.md` 中引用的图片必须：

- 已下载到当前 workspace。
- 带有简短说明和来源 URL。
- 与页面核心信息直接相关。
- 不使用无意义的装饰性占位图。

Design 应根据图片比例决定 `contain`、`cover`、背景图或图文布局。

### 5.5 阶段五：多模态视觉检查

当 Design 模型支持视觉输入时，`inspect_slide` 应返回页面截图，由模型检查：

- 视觉层级是否清晰。
- 配色和对比度是否合理。
- 图文是否平衡。
- 图片裁切是否正确。
- 页面之间的风格是否一致。

多模态检查属于质量增强能力。即使未启用，基础的边界、转换和资源检查仍必须执行。

## 6. 内容与排版约束

1. 每页只表达一个核心结论。
2. 标题简洁，并能够表达页面观点，而不只是主题名称。
3. 正文默认字号不得小于 18px。
4. 单页内容过多时优先压缩或拆页，不得单纯缩小字号。
5. 所有页面使用统一的主色、辅助色、字体和间距系统。
6. 图表、流程、时间线和对比关系应使用相应视觉形式，不应全部退化为项目符号。
7. 表格必须控制行列数量，复杂表格应简化或转换成更适合演示的图形。

## 7. Token 优化要求

PPT 质量优化不能造成 Research 上下文无限增长。

`search_web` 必须限制每条 Tavily 搜索结果的正文长度，初始建议为 1,500 个字符，并保留完整标题和 URL。

验收要求：

- 搜索结果能够支持 Research 生成可靠内容和引用。
- 相同搜索次数下，Research 的 `prompt_tokens` 明显低于当前基线。
- 工具历史中不保存无必要的完整网页正文。

## 8. 稳定性要求

1. 模型临时返回 502、503 或超时时，应支持有限次数重试和退避。
2. HTML、图片、PPTX 和 PDF 的路径必须限制在当前 workspace 内。
3. 任一页面失败时不得删除已经生成的页面和预览。
4. Agent、MCP 工具和转换异常应写入 session 日志。
5. 所有循环必须设置最大轮数或最大修正次数。
6. 配置和日志不得输出模型、Tavily 或其他服务的完整 API Key。

## 9. 第一阶段暂不实现

为了先复现原项目 Design 路线，以下能力暂不进入第一阶段：

- 旧版 PPTAgent 的模板归纳和布局学习。
- 多 Agent 并行委派。
- 用户在线逐页编辑。
- 动画、视频和交互式网页效果。
- 自定义 PowerPoint 母版编辑器。
- 自动宣称视觉效果已经超过原项目。

这些能力应在基线效果稳定、具有可重复评测结果后再讨论。

## 10. 验收标准

使用至少 3 个不同类型的主题进行验证：企业介绍、技术说明和数据分析。

每个测试结果必须满足：

- 生成页数与用户要求一致。
- 所有页面可以成功渲染和截图。
- PPTX 和 PDF 均可正常打开。
- 不存在明显文字溢出、元素重叠或图片缺失。
- 至少使用 4 种不同内容布局。
- 全套页面具有一致的颜色、字体和间距规范。
- Design Agent 能根据 `inspect_slide` 的错误完成至少一次自动修正。
- workspace 中保留完整的 HTML、预览图、最终文件和运行历史。

完成以上验收后，可以认为 Demo 已基本达到原项目 Design 路线的效果基线。后续再通过更严格的视觉评分、模板体系和结构化 SlideSpec 追求超过原项目。

## 11. 实施顺序

```text
1. 限制 Tavily 搜索结果长度
2. Design 输出 global.css 和逐页 HTML
3. 接入 HTML → PPTX/PDF 转换
4. 增加基础 inspect_slide
5. 增加图片搜索与下载
6. 支持多模态页面检查
7. 建立与原项目的对比评测集
```
