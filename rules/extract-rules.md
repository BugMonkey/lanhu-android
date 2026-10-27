---
name: lanhu-extract-rules
description: 蓝湖 skill extract 阶段特有规则，涵盖背景层结构化写入规范和视觉分析降级策略。仅在 extract 阶段加载。
---

# Extract 阶段规则

这些规则仅在 **extract** 阶段加载，不适用于后续 `xml`、`create-page`、`restyle-page` 或 `restore-check`。

## 背景层

### 7.3 背景层必须结构化

页面背景、区块背景、卡片背景、顶部/底部装饰背景、整页大尺寸切图都必须进入 `layout_analysis.background_layers`。

`background_layers[].source` 只允许：

- `slice`：蓝湖切图或大尺寸背景图，后续必须按切图尺寸规则用 `ImageView + 切图` 落地。
- `shape`：由颜色、圆角、描边、透明度组成的背景，后续生成或复用 shape drawable。
- `color`：纯背景色，后续直接落到根布局、容器或 View 的 background。

禁止把截图中可见的背景层仅写在自然语言说明里而不进入 `background_layers`。如果背景层属于宿主外部或用户明确排除，也要保留条目并标记 `scope=host_layout`、`resource_only` 或在报告中说明排除原因。

## 降级策略

### 13. 视觉分析降级策略

当读图子 agent 无法完成截图结构分析（路径错误、无法加载图片、无可用读图能力）时，按以下路径降级，不要无限重试：

1. **第 1 次失败**：检查传给子 agent 的截图路径是否正确、prompt 是否带上 implementation_context，修正后重派 1 次。
   子 agent 明确返回 `viewed:false` 时不得补写视觉结论。
2. **第 2 次失败**：降级处理——
   - `layout_analysis.json.confidence` 设为 `low`
   - `risk_flags` 加入 `missing_visual_review` 和 `agent_validation_failed`
   - 允许主流程以 `confidence=low` 写入最小骨架（仅 `schema_version`、`design_id`、`source`、`screenshot_review` 和基本的 `layout_summary`）
   - `extract_report.md` 标记 `status: warning`，说明降级原因
3. **降级后限制**：禁止声称可做高还原生成、复杂布局拆分或大范围页面改造；仅允许基础骨架和标注数据驱动的简单布局。

降级写入的最小骨架应通过 `validate_layout_analysis.py --degraded "<extract_dir>"` 检查，预期返回 `status=needs_enrichment`（骨架待补全，不是失败）；若返回 `blocked`，说明存在 ERROR 级问题，仍需修复后再继续。
