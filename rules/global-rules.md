---
name: lanhu-global-rules
description: 蓝湖 skill 规则索引。已拆分为 core / resource / layout / extract 四个文件，按场景加载。
---

# 规则索引

全局规则已拆分，按场景精准加载，不再全部塞入单一文件。

## 文件与加载场景

| 文件 | 何时加载 | 包含内容 |
|------|---------|---------|
| [core-rules.md](core-rules.md) | 始终加载（最先读，含 §0 第 0 步 `加载规则`） | §0 执行清单、§1 截图先行、§2 意图理解、§3 必要互动、§4 上下文节制、§4.1 extract_dir、§5 annotations 优先、§7 切图优先、§8 中间产物、§12 结构先于视觉、风险状态、阻塞条件、统一输出格式 |
| [resource-rules.md](resource-rules.md) | 触发条件见 [SKILL.md 表 2](../SKILL.md#2-按是否触碰资源布局) | §7.1 切图命名、§7.2 切图尺寸、§7.4 Shape 验证、§7.5 缺失切图处置、§7.6 资源同一性比对、§7.7 切图与节点映射 |
| [layout-rules.md](layout-rules.md) | 同 resource-rules.md 的触发条件 | §5.1 富文本分段、§6 数值单位、§9 间距计算、§10 排列方向、§11 颜色透明度、§12 宽度自适应 |
| [extract-rules.md](extract-rules.md) | extract 阶段 | §7.3 背景层结构化、§13 视觉分析降级策略 |
| [restyle-guardrails.md](restyle-guardrails.md) | 改造已有页面 | 结构比对、差异分类、ID 保护、删除流程、影响分析、背景图规则 |

命令级补充规则路径要求见对应 `commands/*.md`（如 [xml.md](../commands/xml.md) Step 0.1 的 `xml_rule_paths` 与 `conditional_rule_paths`）。

加载结果汇总写入报告头部「规则加载表」，未读项必须显式标注未读及原因。

## 迁移说明

- 原直接引用 `global-rules.md` 的代码已统一指向 `core-rules.md`。
- 原有 § 编号保持不变，各拆分文件沿用原编号以便对照。
- 如需查找某条规则，在上表中按场景定位即可。
