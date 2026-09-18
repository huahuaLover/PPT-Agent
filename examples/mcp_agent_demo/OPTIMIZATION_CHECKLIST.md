# Demo 优化清单

PPT 质量升级的完整范围参见 [PPT_QUALITY_REQUIREMENTS.md](PPT_QUALITY_REQUIREMENTS.md)，实现规格参见 [PPT_QUALITY_TECHNICAL_DESIGN.md](PPT_QUALITY_TECHNICAL_DESIGN.md)。

## 待优化

- [x] **P0：提升 PPT 的视觉质量和信息表达能力**

  **现状**

  当前 `create_pptx` 只支持“标题页”和“标题 + 项目符号”两种固定页面。所有内容页版式相同，没有主题系统、图像、图表、数据卡片和重点信息层级。即使 Research 内容质量较高，最终 PPT 仍然像自动生成的提纲。

  **优化方案**

  第一阶段复现原项目的 HTML/CSS Design 路线：

  - Design 先生成统一的 `global.css`，再逐页生成独立 HTML。
  - 支持封面、章节、双栏、图文、数据卡片、时间线和总结等动态布局。
  - 每页生成后调用 `inspect_slide`，根据转换错误或页面截图完成修正。
  - 复用原项目的 HTML → PPTX/PDF 转换能力。

  同时补齐图片搜索、下载和可配置的多模态视觉检查。

  **预期收益**

  - 页面不再重复使用同一种版式。
  - 建立清晰的标题、重点和正文视觉层级。
  - 数据、流程和时间信息使用更适合的视觉形式呈现。
  - 生成结果能够用于项目演示，而不仅是验证 Agent 流程。

  **验收标准**

  - 至少支持 5 种可稳定生成的页面布局。
  - 同一份 PPT 使用统一的颜色、字体和间距规范。
  - 页面中文字不越界、不重叠，单页内容量受到限制。
  - Design Agent 能根据内容语义选择合适布局。
  - 生成的 PPTX 可以被 PowerPoint 或 LibreOffice 正常打开。

- [x] 限制 Tavily 搜索结果长度，降低 Research Agent 的 Token 消耗

  **现状**

  `search_web` 当前使用硬编码字符数截断 Tavily 内容，无法通过配置针对模型上下文调整。工具结果进入 `chat_history` 后，会在后续每一轮模型请求中重复发送。本次实际运行中，Research Agent 总计消耗约 6 万 Token。

  **优化方案**

  将每条搜索结果的正文上限放入 `config.yaml`，只保留标题、URL 和核心摘要。建议默认值为 1,500 个字符：

  ```yaml
  search:
    max_content_chars: 1500
  ```

  同时继续使用 `search.max_results` 控制单次搜索返回数量。

  **预期收益**

  - 减少每轮发送给模型的输入 Token。
  - 避免多个搜索结果持续堆积导致上下文过长。
  - 降低模型调用费用和上下文超限概率。

  **验收标准**

  - 每条搜索结果的 `content` 不超过配置的字符上限。
  - 搜索结果仍保留完整标题和 URL。
  - Research Agent 能正常生成带来源链接的 `manuscript.md`。
  - 相同主题和搜索次数下，Research Agent 的 `prompt_tokens` 明显下降。

## 已完成

- HTML/CSS 多布局生成、逐页检查和 PPTX/PDF 导出链路。
- 图片搜索、受限下载和支持视觉模型的截图反馈。
- 搜索摘要长度配置、模型重试及脱敏错误日志。
