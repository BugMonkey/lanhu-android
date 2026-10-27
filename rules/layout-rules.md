---
name: lanhu-layout-rules
description: 蓝湖 skill 布局生成细节规则，涵盖富文本分段样式、annotations 单位规则、间距计算、排列方向判断和颜色透明度处理。生成 XML 布局时加载。
---

# 布局细节规则

这些规则在**生成 XML 布局**（xml / create-page / restyle-page）时加载。restore-check 不加载，extract 不加载。

## 富文本

### 5.1 富文本分段样式

当 `text.segments` 存在且分段间颜色、字重、字号或行高不同时：

- 必须识别为富文本，不能只用单一 TextView 属性。
- XML 生成时在代码中使用 `SpannableString` 实现分段样式。
- 分段颜色来自 `segments[].color`，分段字重来自 `segments[].fontWeight`（>=500 对应 bold）。
- 若所有分段样式相同，则视为普通文本，直接使用 TextView 属性。

禁止：

- 忽略分段颜色差异，只取第一段颜色。
- 用多个 TextView 拼接富文本（除非用户明确要求）。

## 数值单位

### 6. annotations 中的数值单位以 `_unit` 标注为准

`annotations.json` 顶层有 `"_unit": "dp"` 标记，表示所有坐标/尺寸/圆角/字号字段已转换为 Android dp/sp 语义，直接使用。

禁止二次换算：

```text
错误：borderRadius=11.33 再除以 3 得到 3.78dp
正确：borderRadius=11.33 直接落为 11dp 或 11.33dp
```

如需处理原始 px，必须明确字段来源并读取 scale 信息。

## 间距

### 9. 同层/父子间距已预计算

`annotations.json` 中：
- `siblingGap`：同层兄弟元素间距（above/below/left/right）
- `parentMargins`：首/尾子元素与父容器的边距（top/bottom/start/end）

优先使用这些预计算值，避免手动计算误差。

**跨层级对齐需手动验证**：当元素跨不同父容器时，必须用绝对坐标（`absX/absY`）验证对齐关系，公式如下：

```text
marginTop = target.y - (reference.y + reference.height)
marginStart = target.x - (reference.x + reference.width)
```

如果计算出的跨层级间距大于 50dp，必须回查参考元素、父容器和坐标系。

## 排列方向

### 10. 排列方向优先使用 `orientation` 字段

`annotations.json` 中 `index[].orientation` 和 `nodes[].orientation` 已预计算子元素排列方向（`vertical` / `horizontal`）。

优先使用该字段判断容器布局方向。仅当 `orientation` 缺失或为空时，才需手动比较子元素 x/y 坐标差值验证。

## 宽度自适应 vs 写死

### 12. 判断宽度值来源决定固定或自适应

看到设计稿上的宽度值，先判断它是"父容器减去边距后的结果"，还是"设计师刻意要求的固定尺寸"：

- **计算结果**（如 360dp - 20dp - 20dp = 320dp）→ 自适应宽度
  - ConstraintLayout：`layout_width="0dp"` + 双向约束 + `marginStart`/`marginEnd`
  - FrameLayout：`layout_width="match_parent"` + `marginStart`/`marginEnd`
- **设计师刻意要求的固定尺寸**（如图标 24x24、卡片明确标注固定宽高）→ 写死

## 颜色

### 11. 颜色已含透明度

`annotations.json` 中所有颜色字段（`backgroundColor`、`borderColor`）已是最终 Android 格式 `#AARRGGBB` 或 `#RRGGBB`。

脚本已在输出时将图层级 `opacity` 合并到颜色 hex 值中，无需手动转换。

若颜色已是 `#AARRGGBB`（8位），说明 `parse_color` 已嵌入 alpha（来自 fill color 内部的 a 字段），脚本会自动跳过二次叠加。
