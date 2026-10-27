---
name: lanhu-layout-analysis-schema
description: layout_analysis.json 标准结构，供 extract、design-analyze、xml、create-page、restyle-page、restore-check 共用。
---

# layout_analysis.json Schema

`layout_analysis.json` 是蓝湖 skill 的核心中间表示，用于把截图理解、标注结构和工程实现建议固定下来。

## 顶层结构

```json
{
  "schema_version": "1.0",
  "design_id": "string",
  "source": {
    "json": "string",
    "screenshot": "string"
  },
  "confidence": "high | medium | low",
  "layout_summary": "string",
  "screen_type": "fragment | activity | dialog | item | header | footer | unknown",
  "screenshot_review": {},
  "user_intent": {},
  "android_layout_assumptions": [],
  "confirmation_items": [],
  "root_layout_recommendation": {
    "type": "ConstraintLayout | LinearLayout | FrameLayout | NestedScrollView | RecyclerView",
    "reason": "string"
  },
  "sections": [],
  "fixed_regions": [],
  "scroll_strategy": {},
  "element_classification": [],
  "background_layers": [],
  "component_groups": [],
  "constraint_hints": [],
  "implementation_hints": [],
  "risk_flags": []
}
```

## 字段说明

### `confidence`

| 值 | 含义 |
|----|------|
| `high` | 已读取截图，annotations 完整，结构清晰 |
| `medium` | 有截图和标注，但部分区域需人工确认 |
| `low` | 缺少截图、标注不完整或页面结构不确定 |

### `screenshot_review`

用于证明读图子 agent 已经真正查看过截图内容，而不是只依赖 `annotations.json` 推断。

```json
{
  "viewed": true,
  "viewer": "subagent | manual_review | unknown",
  "coverage": ["header", "content", "bottom_action"],
  "evidence": [
    "顶部是装饰性背景图，标题和返回按钮叠放其上",
    "主体内容为重复卡片区域，视觉上更接近列表而不是单个静态容器",
    "底部主按钮与滚动内容分离，属于固定操作区"
  ],
  "limitations": [
    "无法仅凭截图确认中部卡片最终由 RecyclerView 还是静态容器承载"
  ]
}
```

约束：

- `viewed=false` 或字段缺失时，不得声称已完成视觉理解。
- `evidence` 至少 3 条，且必须来自截图视觉观察，不能只是抄写节点数量、尺寸、颜色字段。
- `coverage` 用于说明本次确实看过哪些区域，避免只看局部却声称理解整页。
- `limitations` 用于记录仍需用户确认或需依赖标注/工程上下文的部分。

### 字段归属（谁写、谁不得写）

`layout_analysis.json` 有两个作者，边界不可含糊（见 core-rules §4.1）：

| 字段 | 作者 | 说明 |
|------|------|------|
| `sections`、`screenshot_review`、`background_layers` 等定性视觉结论 | **读图子 agent** | 主流程**不得手写篡改**；不合格只能重新派发、降级或阻塞 |
| `user_intent`、`android_layout_assumptions`、`confirmation_items` | **主流程** | 子 agent 输出的这三项**恒为空数组**——它看不到项目现有实现，写不出"与现有实现冲突"这类结论 |
| `schema_version`、`design_id`、`source` 等元数据 | **主流程** | 合并时补齐 |

即：`confirmation_items` 为空**不代表没有问题**，只代表子 agent 没有能力提出这类问题；
未解决的确认项必须由主流程补进来并保持 `resolved=false`。

### `user_intent`

用户描述提炼出的实现意图。没有描述时也要显式写 `source: "not_provided"`，避免后续误以为已经理解需求。

```json
{
  "source": "provided | inferred | not_provided",
  "request_summary": "实现 HomeFragment，中间设备卡片可横滑",
  "requested_screen_type": "fragment | activity | dialog | item | unknown",
  "core_requirements": ["设备卡片横滑", "保留页面标题"],
  "explicit_inclusions": ["用户明确要求包含的区域"],
  "explicit_exclusions": ["用户明确要求排除的区域"],
  "interaction_requirements": ["ViewPager2 横滑"],
  "data_regions": ["设备列表卡片"],
  "notes": "string"
}
```

### `android_layout_assumptions`

基于 Android 布局常识形成的低风险假设。它们可以指导生成，但必须能在报告中解释；高风险歧义应进入 `confirmation_items`。

数组元素可以使用对象形式（推荐，信息完整）或字符串形式（简化写法）：

```json
{
  "id": "assumption_host_tab_outside_fragment",
  "topic": "host_navigation | dynamic_region | root_layout | resource | binding",
  "assumption": "底部 Tab 属于宿主 Activity，不放入 HomeFragment",
  "reason": "用户请求的是 Fragment，且底部 Tab 通常由宿主容器管理",
  "confidence": "high | medium | low"
}
```

简化为字符串数组亦可：`["底部 Tab 属于宿主 Activity，不放入 HomeFragment"]`。

### `confirmation_items`

继续实现前需要用户确认的问题。只记录会影响架构、文件拆分、宿主归属、动态区域或关键 ID 的问题。

需要 validator 阻断时使用对象形式（`severity=high` 且 `resolved=false` 会被判为未解决）：

```json
{
  "id": "confirm_bottom_tab_scope",
  "question": "截图底部 Tab 是否属于宿主 Activity，Fragment 中不生成？",
  "impact": "决定 fragment_home.xml 是否包含底部导航区域",
  "default_when_unanswered": "exclude_from_fragment | include_in_current_layout | blocked",
  "severity": "high | medium | low",
  "resolved": false,
  "answer": ""
}
```

仅需记录问题、不要求阻断时，可直接用字符串数组：`["地址管理/联系客服等新增入口的点击行为待确认"]`。

### `sections`

页面区域划分：

```json
{
  "id": "section_header",
  "name": "顶部标题栏",
  "role": "header | content | footer | card | list | form | overlay",
  "bounds": {
    "x": 0,
    "y": 0,
    "width": 360,
    "height": 88
  },
  "children": ["tv_title", "iv_back"],
  "implementation": "ConstraintLayout",
  "notes": "string"
}
```

### `fixed_regions`

固定区域：

```json
{
  "id": "bottom_action",
  "position": "top | bottom | left | right | overlay",
  "bounds": {
    "x": 0,
    "y": 720,
    "width": 360,
    "height": 80
  },
  "reason": "底部按钮需要固定在滚动内容外"
}
```

### `scroll_strategy`

滚动策略：

```json
{
  "type": "none | NestedScrollView | RecyclerView | ViewPager2（推荐取值；可按实际容器自定义，如 CoordinatorLayout+AppBarLayout+RecyclerView）",
  "scroll_region": "section_content",
  "fixed_outside_scroll": ["section_header", "bottom_action"],
  "reason": "内容区超屏，底部按钮固定"
}
```

### `element_classification`

元素分类：

```json
{
  "layer": "string",
  "id_hint": "iv_back",
  "meaning": "返回按钮",
  "category": "icons | backgrounds | buttons | images | text | container | divider | input | list",
  "android_view": "ImageView",
  "interactive": true,
  "has_slice": true,
  "resource_prefix": "ic_",
  "implementation_priority": "core | supporting | decorative | host_outside | excluded",
  "scope": "current_layout | host_layout | item_layout | resource_only | unknown",
  "bounds": {
    "x": 16,
    "y": 44,
    "width": 24,
    "height": 24
  },
  "confidence": "high | medium | low",
  "notes": "string"
}
```

### `background_layers`

背景层清单。用于把页面背景色、区块背景、卡片背景、顶部/底部装饰背景、整页大尺寸切图等容易被当成“装饰”遗漏的视觉层固定下来。

```json
{
  "id": "bg_page",
  "name": "页面整体背景",
  "role": "page_background（推荐取值：page_background / section_background / card_background / top_decoration / bottom_decoration / full_page_image；可按实际语义自定义）",
  "source": "slice | shape | color",
  "scope": "current_layout（推荐取值：current_layout / host_layout / item_layout / resource_only / unknown）",
  "z_order": "behind_content | container_background | overlay_decoration",
  "bounds": {
    "x": 0,
    "y": 0,
    "width": 360,
    "height": 800
  },
  "related_section": "section_content",
  "related_element": "bg_card",
  "must_implement": true,
  "confidence": "high | medium | low",
  "notes": "页面根背景色来自标注；顶部大尺寸切图需后续从 slices.json 回查尺寸"
}
```

约束：

- `source` 只允许 `slice`、`shape`、`color`（强约束：它决定后续落地方式）。
- `role`、`scope` 是描述性字段，上述取值仅为推荐；语义更准确时允许自定义，不影响后续流程。
- 截图中可见的页面背景色、区块背景、卡片背景、顶部/底部装饰背景、整页大尺寸切图，都必须进入 `background_layers`。
- `source=slice` 表示后续 XML 阶段必须从 `slices.json` 或切图文件尺寸回查并使用 `ImageView + 切图`。
- `source=shape` 表示后续 XML 阶段生成或复用 shape drawable，覆盖颜色、圆角、描边和透明度。
- `source=color` 表示可直接落为 View/根布局背景色，但颜色值仍需由 `annotations.json` 或 raw 追溯确认。
- 用户明确排除或判断属于宿主外部的背景层，也要保留条目并把 `scope` 标为 `host_layout` 或 `resource_only`，在报告中说明不落地原因。

### `component_groups`

组件分组：

```json
{
  "id": "group_shop_card",
  "name": "店铺卡片",
  "role": "card | list_item | toolbar | form_group | action_bar",
  "children": ["iv_shop", "tv_shop_name", "tv_distance"],
  "repeatable": true,
  "recommended_container": "ConstraintLayout",
  "scope": "current_layout | host_layout | item_layout | unknown",
  "data_binding_hint": "RecyclerView item"
}
```

### `constraint_hints`

约束建议。数组元素可以使用对象形式（信息完整）或字符串形式（简化写法）：

```json
{
  "type": "left_align | right_align | top_to_bottom | center_horizontal | baseline_align",
  "source": "tv_title",
  "target": "iv_back",
  "value": 16,
  "unit": "dp",
  "confidence": "medium"
}
```

简化为字符串数组亦可：`["各卡片宽 333.33dp 水平居中（左右边距 13.33dp）"]`。

### `implementation_hints`

工程实现建议。数组元素可以使用对象形式或字符串形式：

```json
{
  "scope": "xml | resource | binding | adapter | interaction",
  "message": "底部按钮应固定在滚动容器外",
  "priority": "high | medium | low"
}
```

### `risk_flags`

风险标记：

```json
{
  "code": "missing_screenshot（推荐取值：missing_screenshot / missing_visual_review / missing_visual_field / layout_analysis_not_enriched / agent_validation_failed / missing_slice / complex_list / uncertain_grouping / host_navigation_uncertain / dynamic_region_uncertain / context_bloat_risk / requires_manual_confirm；语义更准确时允许自定义）",
  "severity": "high | medium | low",
  "message": "string",
  "blocked": false
}
```

## 最小有效示例

```json
{
  "schema_version": "1.0",
  "design_id": "home",
  "source": {
    "json": "./lanhu/home/source.json",
    "screenshot": "./lanhu/home/screenshot.png"
  },
  "confidence": "medium",
  "layout_summary": "顶部标题栏 + 中间列表 + 底部固定按钮",
  "screen_type": "fragment",
  "screenshot_review": {
    "viewed": true,
    "viewer": "subagent",
    "coverage": ["header", "content", "bottom_action"],
    "evidence": [
      "顶部是装饰性背景图，标题内容叠放其上",
      "中部内容区由重复卡片组成，适合拆成列表承载",
      "底部按钮视觉上固定在内容区之外"
    ],
    "limitations": [
      "仅凭截图无法确认重复卡片最终由 RecyclerView 还是静态容器承载"
    ]
  },
  "user_intent": {
    "source": "provided",
    "request_summary": "实现 HomeFragment 首页内容",
    "requested_screen_type": "fragment",
    "core_requirements": ["中间内容列表"],
    "explicit_inclusions": [],
    "explicit_exclusions": [],
    "interaction_requirements": [],
    "data_regions": ["内容列表"],
    "notes": ""
  },
  "android_layout_assumptions": [
    {
      "id": "assumption_fragment_excludes_host_nav",
      "topic": "host_navigation",
      "assumption": "Fragment 布局不包含宿主级底部导航",
      "reason": "用户请求的是 Fragment",
      "confidence": "medium"
    }
  ],
  "confirmation_items": [],
  "root_layout_recommendation": {
    "type": "ConstraintLayout",
    "reason": "存在固定底部按钮和滚动内容区"
  },
  "sections": [],
  "fixed_regions": [],
  "scroll_strategy": {
    "type": "RecyclerView",
    "scroll_region": "section_content",
    "fixed_outside_scroll": ["bottom_action"],
    "reason": "主体内容为重复卡片"
  },
  "element_classification": [],
  "background_layers": [],
  "component_groups": [],
  "constraint_hints": [],
  "implementation_hints": [],
  "risk_flags": []
}
```
