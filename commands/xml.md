---
name: lanhu-command-xml
description: 定义 /lanhu-android xml 的完整行为，从 extract 产物生成 Android XML 布局和相关资源。
---

# xml 命令

`xml` 只负责布局 XML 和相关资源，不负责完整 Fragment、Activity、ViewModel 或业务代码骨架。

## 命令格式

```text
/lanhu-android xml <extract_output_dir> [--android-project <path>] [--screen <画板名>]
```

## 输入

必需输入：

- `extract_output_dir`：`extract` 实际生成的提取产物目录。

`extract_output_dir` 的完整规则只引用 [../rules/core-rules.md](../rules/core-rules.md) 和 [extract.md](extract.md)。

必需产物：

```text
annotations.json
slices.json
screenshot.png
layout_analysis.json
```

可选输入：

- `--android-project`：目标 Android 项目路径。提供后可直接落地到 `res/layout` 和 `res/drawable*`。
- `--screen`：多画板场景下指定画板。

## 输出

根据是否提供 Android 项目决定输出位置：

```text
<android-project>/app/src/main/res/layout/<layout_name>.xml
<android-project>/app/src/main/res/drawable/shape_<name>.xml
<android-project>/app/src/main/res/drawable-xxhdpi/<asset_name>.png
<extract_output_dir>/xml_report.md
```

未提供 Android 项目时，输出到：

```text
<extract_output_dir>/generated/res/layout/
<extract_output_dir>/generated/res/drawable/
<extract_output_dir>/generated/res/drawable-xxhdpi/
```

## 执行步骤

先完成 [core-rules.md §0 6 步执行清单](../rules/core-rules.md#0-执行清单优先全局唯一权威版本)。

xml 特有补充：
- `搭页面`：加载 `xml_rule_paths`（见 Step 0.1），形成布局计划
- `回看数据`：切图尺寸优先用 `slices.json` 的 `width_dp/height_dp`，命名遵循语义化规范
- `自我检查`：产出 `xml_report.md`

### Step 0: 意图确认与布局决策

在读取产物后、生成 XML 前，先确认 `layout_analysis.json` 中的 `user_intent`、`android_layout_assumptions`、`confirmation_items` 是否足够支撑实现。

必须遵守：

- 用户意图决定“当前要实现什么”和“哪些区域属于当前布局文件”。
- Android 常识决定默认布局边界，例如 Fragment 通常不包含宿主 Activity 的底部 Tab。
- `annotations.json` 和 `slices.json` 决定精确值与资源使用，不能被意图理解替代。
- 无法确认且会影响架构的项，先问用户；不能边猜边生成。

互动问题每轮最多 4 个、可分多轮（必问清单见 [../rules/core-rules.md](../rules/core-rules.md) §3）。低风险假设可以继续，但必须写入 `xml_report.md`。

上下文要求：

- 不把完整 `annotations.json`、`slices.json` 或 `layout_analysis.json` 贴进聊天。
- 只用轻量摘要和局部查询结果支撑当前布局决策。
- 布局计划和最终决策写入 `xml_report.md`；聊天中只说明需要用户确认的问题和最终产物。

输出 XML 前先在脑中形成布局计划：

- 本次生成哪些 layout 文件。
- 当前布局包含/排除哪些设计稿区域。
- 动态区域如何承载。
- 哪些切图、shape、ID 必须保留。
- 哪些 `background_layers` 必须落地，包括页面背景色、区块背景、卡片背景、顶部/底部装饰背景和整页大尺寸切图。
- 哪些元素只作为宿主区域、装饰背景或后续业务承接，不直接生成在当前 XML 中。

### Step 0.1: 准备 XML 生成规则路径

生成 XML / drawable 前，主流程必须整理一份 `xml_rule_paths`。如果本阶段由子 agent 执行，必须把这份路径清单原样放入子 agent prompt，并要求子 agent 先读取这些文件再写改 XML / drawable。

```json
{
  "skill_dir": "<skill_dir>",
  "rule_paths": [
    "<skill_dir>/rules/core-rules.md",
    "<skill_dir>/rules/resource-rules.md",
    "<skill_dir>/rules/layout-rules.md",
    "<skill_dir>/commands/xml.md",
    "<skill_dir>/schemas/layout-analysis-schema.md"
  ],
  "conditional_rule_paths": [
    {
      "when": "修改已有页面或复用旧资源",
      "paths": [
        "<skill_dir>/rules/restyle-guardrails.md",
        "<skill_dir>/schemas/change-impact-schema.md"
      ]
    }
  ],
  "project_rule_globs": [
    "<android-project>/**/src/main/res/layout/*.xml",
    "<android-project>/**/src/main/res/drawable/*.xml"
  ]
}
```

传给子 agent 时必须写明：

- 先读取 `rule_paths` 中的文件，再执行文件写改。
- 命中 `conditional_rule_paths.when` 时，同时读取对应 paths。
- `project_rule_globs` 只用于发现项目局部 XML / drawable 规范，不要把大量文件全文塞进 prompt。
- 规则文件路径是执行约束的一部分，不是参考资料；如果路径不存在，先向主流程返回 blocked。

### Step 1: 加载产物

先读取轻量交接摘要：

```bash
python3 <skill_dir>/scripts/lanhu_inspect.py "<extract_output_dir>" --compact-for-xml
```

必须检查：

- `annotations.json`：节点、坐标、尺寸、文本、样式、scale。
- `slices.json`：切图清单和 source layer，**包含切图实际尺寸**。
- `layout_analysis.json`：页面结构、区域、组件分组、实现建议。
- `screenshot.png`：视觉理解和最终自查。
- `raw.json`：仅当 `annotations.json` 缺失颜色等精确样式字段时，使用固定脚本做补充追溯。

**重要：切图尺寸优先规则**

禁止直接 `Read screenshot.png`，因为图片会以 base64 进入上下文。确认截图存在和尺寸使用 `lanhu_inspect.py --compact-for-xml` 或 `file <screenshot.png>`；需要视觉理解时才把截图交给视觉分析步骤。

读取节点时优先用局部查询，禁止为找少量节点直接读取完整 `annotations.json`：

```bash
python3 <skill_dir>/scripts/lanhu_query.py "<extract_output_dir>" --search "关键词" --sort y --limit 40
python3 <skill_dir>/scripts/lanhu_query.py "<extract_output_dir>" --node-ids "id1,id2,id3" --with-children --compact-output
# 嵌套结构用 --depth 2~3（--with-children 只有 1 层）
python3 <skill_dir>/scripts/lanhu_inspect.py --json-color-summary "<extract_output_dir>/raw.json"
```

**切图尺寸查询（关键）：**

```bash
# 查看所有切图及其尺寸
python3 <skill_dir>/scripts/lanhu_inspect.py "<extract_output_dir>" --compact-for-xml

# 从 slices.json 提取切图尺寸
grep -E "(drawable|size)" "<extract_output_dir>/slices.json"

# 计算切图dp尺寸：切图像素 ÷ 3 (xxhdpi)
```

缺少 `layout_analysis.json` 时可降级继续，但必须在报告中标记 `warning`，并禁止做复杂结构推断。

### Step 2: 确认页面类型

如果无法从参数或项目上下文判断，必须询问用户或输出 `blocked`：

- `Fragment`：`fragment_<name>.xml`
- `Activity`：`activity_<name>.xml`
- `Dialog`：`dialog_<name>.xml`
- `Item`：`item_<name>.xml`
- `Header/Footer`：`header_<name>.xml` / `footer_<name>.xml`

如果页面类型来自用户描述（如 `HomeFragment`），应同步检查截图中是否存在宿主级区域：

- 底部 Tab、全局导航、宿主级悬浮按钮通常属于 Activity 或父容器。
- Fragment XML 默认只生成内容区域；是否保留宿主级区域必须由用户确认或已有项目结构证明。
- 如果用户明确要求“整页都实现”“包括底部导航”，则可保留并在报告中说明。

### Step 3: 确认数据展示方式

识别动态数据区域：

- 静态内容。
- `RecyclerView` 列表。
- `ViewPager2` 横向卡片。
- DataBinding / ViewBinding / findViewById。
- 需要业务代码承接的交互组件。

`xml` 只在 XML 中保留合理 ID 和结构，不生成业务逻辑。

动态区域拆分原则：

- 重复卡片优先拆为 `item_*.xml`，父布局使用 `RecyclerView` 或 `ViewPager2`。
- 横向滑动卡片优先用 `ViewPager2` 或横向 `RecyclerView`，除非用户或项目上下文指定静态布局。
- item 内部只放该 item 自己的数据和交互控件，不把页面标题、Tab、全局入口塞入 item。

### Step 4: 生成布局

布局选择：

- 页面根布局默认优先 `ConstraintLayout`。
- 只有单向线性排列时优先 `LinearLayout`。
- 明显重叠、悬浮、层叠时使用 `FrameLayout` 或 `ConstraintLayout` 中的覆盖关系。
- 内容超屏时选择 `NestedScrollView` 或 `RecyclerView`，底部固定按钮不得放入滚动容器。

**顶部装饰性背景**（品牌图案/复杂背景图）使用 ConstraintLayout + ImageView 模式：

```xml
<ImageView
    android:layout_width="0dp"
    android:layout_height="wrap_content"
    android:adjustViewBounds="true"
    android:src="@drawable/bg_<page_name>_head"
    app:layout_constraintStart_toStartOf="parent"
    app:layout_constraintEnd_toEndOf="parent"
    app:layout_constraintTop_toTopOf="parent" />
```

要点：`width="0dp"` 撑开宽度，`height="wrap_content" + adjustViewBounds="true"` 依赖切图固有尺寸保持比例，图片用 `src` 而不是 `background`，放在根布局第一个位置，后续控件叠加在其上方。

**切图命名规范**：

| 切图类型 | 命名格式 | 示例 |
|---------|----------|------|
| 顶部背景 | `bg_<page_name>_head` | `bg_publish_goods_head.png` |
| 按钮背景 | `btn_<action>` | `btn_submit.png` |
| 图标 | `ic_<purpose>` | `ic_back.png`、`ic_arrow_right.png`、`ic_close.png` |
| 功能图片 | `img_<purpose>` | `img_upload_add.png`、`img_avatar_default.png` |

**命名原则**：按用途命名，禁止用设计稿原名。`<purpose>` 描述图标/图片的实际作用，如返回、关闭、添加、占位。

**page_name 提取**：用户输入页面名去后缀转 snake_case。例：`PublishGoodsActivity` → `publish_goods`，`HomeFragment` → `home`。未提供页面名时必须询问。

资源处理：

- 有 slice 字段或 `slices.json` 匹配的图层，必须使用 `ImageView + 切图`。
- `layout_analysis.background_layers` 是背景还原的必检清单：
  - `source=slice`：使用 `ImageView + 切图`，尺寸按 `slices.json` 或切图文件实际尺寸计算。
  - `source=shape`：生成或复用 shape drawable，覆盖背景色、圆角、描边和透明度。
  - `source=color`：落到根布局、容器或 View 的 `android:background`，颜色值必须回查标注。
  - `role=page_background`、`section_background`、`card_background`、`top_decoration`、`bottom_decoration`、`full_page_image` 都不能因“装饰性”被默认忽略；若不落地，必须在 `xml_report.md` 写明原因。
- **切图尺寸计算（关键）**：
  - 从 `slices.json` 获取切图像素尺寸（如 100x100px）
  - 计算 dp 尺寸：像素 ÷ density (xxhdpi=3, xhdpi=2)
  - 示例：切图 100px ÷ 3 = 33.33dp，写入 `android:layout_width="33.33dp"` 和 `android:layout_height="33.33dp"`
  - **禁止使用** `annotations.json` 中的图层尺寸（ddsOriginFrame），除非该图层无切图
- 返回图标等通用图标先检查项目 `/app/src/main/res/drawable*` 中是否已存在，无则生成新切图。
- 无切图但有背景、圆角、描边、透明度的元素，生成对应 shape drawable，可先从 `/app/src/main/res/drawable/` 根据名称初筛是否有可复用的现有文件。
- 文本使用 `TextView`，字号和颜色来自 `annotations.json`。
- **富文本分段样式**：当 `text.segments` 存在且分段间颜色/字重/字号/行高不同时，在代码中使用 `SpannableString` 实现分段样式，XML 中只声明整体字号和基础样式。
- 禁止用 vector drawable 替代蓝湖切图。
- 用户明确排除或经确认属于宿主外部的区域，不生成对应 XML/shape；但要在报告中列出排除原因。
- 装饰性元素是否生成取决于用户目标、还原度要求和工程价值；不要默认机械实现全部节点，也不要无依据删除关键视觉或交互承载元素。

间距计算：

```text
marginTop = target.y - (reference.y + reference.height)
marginStart = target.x - reference.x 或 target.x - (reference.x + reference.width)
```

注意：`annotations.json` 中的尺寸、坐标、圆角等数值已经是 dp，直接使用，不做二次换算。

### Step 5: 自查和报告

生成 `xml_report.md`，至少包含：

- 生成文件清单。
- 使用的页面类型和根布局。
- 用户意图摘要、确认结果和 Android 布局假设。
- 本次包含/排除的设计稿区域，尤其是宿主导航、Tab、动态 item。
- **资源落地表**：合并背景还原、切图、shape 为一张表（视觉角色 | 落地方式 | 产物 | 备注）。`background_layers` 中未落地的项必须在备注写明原因。
- 动态数据区域和需要业务层承接的 ID。
- 自查结果。
- `status`、`warnings`、`blocked`、`next`。

资源落地表格式示例：

```text
| 视觉角色 | 落地方式 | 产物 | 备注 |
|---------|---------|------|------|
| 页面背景色 | color | #F6F8FA | 根布局 background |
| 顶部装饰背景 | slice | bg_home_head.png | xxhdpi |
| 搜索栏背景 | shape | shape_search_bg | 圆角 8dp |
| 卡片 1 背景 | shape | shape_card_1 | 圆角 12dp+描边 1dp |
```

## 成功判定

- XML 文件已生成。
- 所有使用到的切图均可在目标资源目录找到。
- shape drawable 可被 XML 正确引用。
- 关键文本、尺寸、颜色、间距均来自标注。
- 报告明确说明未处理或需人工确认的问题。

## 阻塞条件

- `annotations.json` 缺失或无有效节点。
- 用户要求落地到 Android 项目，但未提供可写项目路径且无法从当前工作区判断。
- 页面类型无法判断且会影响文件命名或根结构。
- 关键切图缺失。按 [resource-rules.md §7.5](../rules/resource-rules.md) 阻断并向用户确认，禁止自动降级为 vector、shape 或硬编码颜色。
