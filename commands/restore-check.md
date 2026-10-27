---
name: lanhu-command-restore-check
description: 检查蓝湖设计稿与 Android 实现的一致性，适用于用户要求整页或重点区域还原度检查。
---

# restore-check 命令

`restore-check` 面向“已经生成/改造后继续检查”或“只想核对某个区域”的场景。它只输出检查报告和修复建议，不主动重写页面。

## 命令格式

```text
/lanhu-android restore-check <extract_dir> --target <检查目标> [--android-project <path>] [--page <页面名>] [--actual-screenshot <path>] [--adb-screenshot]
```

## 输入

必需输入：

- `extract_dir`：`extract` 实际生成的提取产物目录。用户重新提供 JSON URL 时，先执行 `extract` 并复用脚本实际输出的目录。
- `--target`：检查目标，例如 `卡片`、`顶部标题栏`、`底部按钮`、`列表 item`。

可选输入：

- `--android-project`：目标 Android 项目路径，用于静态核对 XML、drawable、切图资源。
- `--page`：页面名称，如 `DiaryFragment`。
- `--actual-screenshot`：实现截图路径。提供后优先做截图级视觉对比。
- `--adb-screenshot`：未提供实现截图时，通过 ADB 获取设备当前页截图。

`extract_dir` 的完整规则只引用 [../rules/core-rules.md](../rules/core-rules.md) 和 [extract.md](extract.md)。

必需产物：

```text
annotations.json
slices.json
screenshot.png
layout_analysis.json
```

## 意图识别

以下表达都归为还原度检查：

- `帮我重点检查设计稿中卡片的样式与设计稿是否一致`
- `检查 DiaryFragment 卡片还原度`
- `核对列表 item 和设计稿是否一致`
- `对比按钮圆角、颜色、间距`

如果用户同时说“修改/修复/按设计图改”，按语义分流：

- 老页面按新设计稿换样式：走 `restyle-page`。
- 已生成/已改造页面继续核对还原度：仍走 `restore-check`，只输出差异和修复建议。
- 只说“检查/核对/对比”：只输出报告，不改文件。

## 执行阶段

先完成 [core-rules.md §0 6 步执行清单](../rules/core-rules.md#0-执行清单优先全局唯一权威版本)。restore-check 特有补充：
- `搭页面` 替换为静态标注核对
- `自我检查`：产出 `restore_check_report.md`

### Phase 1: 静态标注核对（必做）

**核心原则：标注优先，视觉辅助**

在进入视觉对比前，必须先从 `annotations.json` 提取设计基准；若能定位实现代码，再补全静态实现核对：

```bash
# 查询关键节点标注数据
python3 <skill_dir>/scripts/lanhu_query.py "<extract_dir>" --node-ids "xxx" --compact-output
python3 <skill_dir>/scripts/lanhu_query.py "<extract_dir>" --with-children --limit 80
# 嵌套结构（角标组/Tab 图标组）用 --depth 2~3；--with-children 只展开 1 层
```

**必查项清单**（P0级，必须核对）：

| 标注项 | 标注字段 | 核对方式 |
|--------|----------|----------|
| 背景颜色 | backgroundColor | 对照 drawable/colors.xml |
| 圆角值 | borderRadius | 对照 drawable shape |
| 字号 | fontSize | 对照 XML textSize |
| 文字颜色 | color | 对照 textColor/colors.xml |
| 尺寸 | width/height | 对照 layout_width/height |
| 元素存在性 | node_id | 查询节点是否存在 |

**重要项清单**（P1级，建议核对）：

| 标注项 | 标注字段 | 核对方式 |
|--------|----------|----------|
| 位置/边距 | x/y | 计算 margin 值 |
| 父子结构 | children | 查询层级关系 |
| 占位符透明度 | opacity | 对照 textColorHint |
| 字重 | fontWeight | 对照 textStyle |

输出静态核对清单到 `<extract_dir>/static_check.md`。能定位实现代码时写入“实现值”，否则先记录设计基准并在报告中标明缺失项。格式：

```markdown
| 项目 | 标注值 | 实现值 | 核对来源 | 结论 |
|------|--------|--------|----------|------|
| 弹窗背景色 | #F6F8FA | #FFFFFF | node_id: E3F818EA | ❌ 不一致 |
```

完成后输出静态核对关键差异，再根据是否已有实现截图决定后续分支。

### Phase 2: 实现截图获取与引导（核心）

**执行顺序调整：先引导ADB截图，再降级静态核对。**

还原度检查的核心价值在于**视觉对比验证**，静态核对只能检查标注数据是否正确落地，无法验证真实渲染效果。因此必须优先引导用户获取实现截图。

#### 优先级与执行分支

1. **已提供 `--actual-screenshot`**：直接进入 Phase 3 视觉对比。
2. **未提供实现截图参数**：
   - **Step 1**: 主动检测设备连接（`adb devices`）
   - **Step 2**: 根据设备状态分支处理
   - **Step 3**: 用户无法ADB截图时，才降级到静态核对

#### ADB 自动截图引导流程（新增）

当用户未提供 `--actual-screenshot` 或 `--adb-screenshot` 参数时，**自动执行以下流程**：

```bash
# 1. 检测设备连接
adb devices

# 输出示例：
# List of devices attached
# emulator-5554   device  → 设备已连接，可引导截图
# (空列表)        → 未检测到设备，提示用户手动提供截图
```

**分支 A：检测到设备连接**

输出以下提示引导用户截图：

```
已检测到设备连接。请按以下步骤准备实现截图：

1. 在设备上打开目标页面：MailDetailActivity
2. 确保页面状态与设计稿一致（数据加载完成、无加载中状态）
3. 准备好后，回复"截图"或"准备截图"

我将在您回复后自动执行：
adb exec-out screencap -p > lanhu/<extract_dir>/actual_screenshot.png
```

等待用户回复"截图"后执行：

```bash
# 用户回复后自动截图
adb exec-out screencap -p > "<extract_dir>/actual_screenshot.png"

# 截图成功后继续 Phase 3 视觉对比
```

**分支 B：未检测到设备**

输出以下提示询问用户：

```
未检测到设备连接。请选择以下方式之一提供实现截图：

1. 【推荐】连接设备后回复"已连接"，我将自动引导ADB截图流程
2. 【手动提供】回复实现截图路径，例如：--actual-screenshot /path/to/screenshot.png
3. 【跳过视觉对比】回复"跳过"，仅输出静态标注核对结果（状态为 warning）

请回复您的选择。
```

用户选择处理：
- 用户回复"已连接" → 重新检测设备并进入分支A
- 用户回复路径 → 读取截图并进入 Phase 3
- 用户回复"跳过" → 直接输出静态核对报告，状态标为 `warning`

**分支 C：用户明确指定 `--adb-screenshot` 参数**

直接跳过检测，输出引导提示并等待用户回复"截图"：

```
请在设备上打开目标页面，准备好后回复"截图"
```

#### 降级规则

只有在以下情况才**跳过视觉对比，仅输出静态核对**：

1. 用户明确回复"跳过"
2. 用户无法提供实现截图且无法连接设备
3. 设备连接异常且用户选择不手动提供截图

降级时必须在报告中显式标注：

```markdown
mode: static_audit_only
reason: 未获取实现截图，无法进行视觉对比验证
```

#### ADB 截图验证

截图成功后，验证截图有效性：

```bash
# 验证截图文件
file "<extract_dir>/actual_screenshot.png"

# 输出示例：
# actual_screenshot.png: PNG image data, 1080 x 2400, 8-bit/color RGBA, non-interlaced
```

截图有效则进入 Phase 3，无效则提示用户重新截图。

### Phase 3: 视觉对比验证（可选）

当拿到实现截图后，派发子 agent 同时读取两张截图（第一张设计稿、第二张实现截图）做视觉对比，并把 Phase 1 的关键标注数据写进 prompt（标注优先、视觉辅助）。要求子 agent 只回传定性差异结论，不回传图片内容：

```text
对比以下两张截图，找出实现与设计稿的视觉差异。
设计稿：<extract_dir>/screenshot.png
实现截图：<extract_dir>/actual_screenshot.png
检查目标：<--target>
关键节点标注数据：<Phase 1 查询的 node_id/backgroundColor/borderRadius/fontSize 摘要>
只回传差异清单（像不像、差在哪），不输出图片内容或逐像素描述。
若无法读取图片，只回传 {"viewed": false, "reason": "无法读取图片"}，不要输出任何视觉结论。
```

子 agent 输入必须包含：
- 设计稿截图路径
- 实现截图路径
- Phase 1 的关键节点标注数据（必须提供，写入 prompt；缺失时降级走静态核对）
- `focus_target`（写入 prompt）

子 agent 职责：
1. 验证静态核对项是否正确落地
2. 检查动态效果（光标、动画、交互状态）
3. 发现标注遗漏的视觉细节

主流程把子 agent 回传的差异结论与静态核对数据合并写入 `restore_check_report.md`。报告必须引用标注数据，格式：

```markdown
| 项目 | 标注数据 | 实现数据 | 核对来源 |
|------|---------|---------|----------|
| 弹窗背景色 | #F6F8FA | #FFFFFF | annotations.json node_id: E3F818EA |
```

子 agent 输出只是视觉观察，禁止把其中的近似值直接当作精确标注数据写入报告；精确值以 `annotations.json` 查询为准。

### Phase 4: 卡片样式核对项

当 `--target` 包含“卡片”“card”或“item”时，报告必须逐项核对：

- 卡片容器：宽高、位置、背景色、圆角、描边、阴影、透明度。
- 内容间距：外边距、内边距、标题/图片/按钮之间的横纵间距。
- 文本样式：字号、字重、颜色、行高、单行/多行、对齐方式。
- 图片与图标：是否使用 `slices.json` 中的切图、尺寸、缩放方式、圆角裁剪。
- 图标语义：图形内容是否与设计稿一致——**不只核对尺寸和颜色**。图层名与图形明显不符、同名图层有多个切图版本、
  或图形来源存疑时，必须派发子 agent 读取该切图确认"这个图形画的是什么"（见 core-rules §10），
  禁止靠图层名/文件名判断；确认张冠李戴则记入不一致清单。
- 状态与交互：选中态、禁用态、点击区域、列表复用 item 的 ID 稳定性。
- 动态承载：重复卡片是否拆成 `item_*.xml`，父容器是否使用 `RecyclerView`/`ViewPager2`。

### Phase 5: 静态核对 Android 实现（无实现截图且能定位代码时必做）

根据 `--page` 定位布局和代码：

```bash
rg "class <PageName>|<PageName>" <android-project>
rg "fragment_.*diary|item_.*diary|card" <android-project>/app/src/main/res/layout
rg "@\\+id/|@id/" <android-project>/app/src/main/res/layout
```

核对重点：

- XML 中的 `layout_width`、`layout_height`、`layout_margin*`、`padding*` 是否来自标注。
- `background` 引用的 shape 是否匹配背景色、圆角、描边和透明度。
- 有 slice 的卡片背景、图片、图标是否使用切图资源，禁止被 vector 或 shape 随意替代。
- 旧页面改造场景下，被代码引用的 ID 是否保留。

如果既没有实现截图，也无法定位实现代码，只能输出设计基准和缺失信息，状态标为 `warning` 或 `blocked`，并要求补充实现截图或项目路径。

静态核对无法确认真实渲染效果时，必须把状态标为 `warning`，并建议补充实现截图做视觉对比。

## 输出

输出 `<extract_dir>/restore_check_report.md`，结构如下：

```text
# 还原度检查报告

## 检查目标
- target:
- page:
- mode: screenshot_compare | static_audit

## 核查概览
- **核对总数**: N 项
- **不一致项**: M 项
- **未验证项**: K 项（原因见风险与限制）

## 不一致清单（Phase 1 + Phase 3）

只列结论为 ❌ 的项。一致项（✅）不在此列出，如需全表见 `<extract_dir>/static_check.md`。

| 项目 | 标注值 | 实现值 | 核对来源 | 修正建议 |
|------|--------|--------|----------|----------|

## 设计稿基准
- 目标节点:
- 关键尺寸:
- 关键样式:
- 切图:

## 风险与限制
- <无法验证的内容和原因>

status: success | warning | blocked
outputs:
  - <restore_check_report.md>
  - <static_check.md（可选，含核对全表）>
warnings:
  - <warning>
blocked:
  - <blocker>
next:
  - <next>
```

## 禁止行为

> 全局禁止行为见 [core-rules.md](../rules/core-rules.md)，以下仅列出 restore-check 特有项。

- 禁止在用户只要求检查时直接修改文件。
- 禁止把整页差异泛泛输出，必须围绕 `--target` 聚焦。
- 禁止跳过 Phase 1 静态核对，直接进入视觉对比。
- 禁止在没有实现截图时输出 `success`，必须标为 `warning`。
