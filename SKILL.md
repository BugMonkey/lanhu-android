---
name: lanhu-android
slug: lanhu-android
displayName: Lanhu Android 蓝湖设计稿
version: 1.0.12
summary: 蓝湖设计稿转 Android：JSON+截图生成页面、受控改造已有页面、还原度检查，含标注/切图解析与布局校验脚本。
license: MIT
description: Android 蓝湖 Skill：蓝湖 JSON+截图→Android 页面生成、修改已有页面、还原度检查。
argument-hint: '截图地址:<截图URL> sketchjson:<SKETCH_JSON_URL> 页面:<页面名> 任务:请明确选择一个任务:生成新页面、修改现有页面或还原度检查 检查目标:<检查目标> 实现截图:<截图路径或URL>'
disable-model-invocation: true
allowed-tools:
  - Read
  - Write
  - Edit
  - Glob
  - Grep
  - AskUserQuestion
  - TaskCreate
  - TaskUpdate
  - TaskList
  - Bash(python3 *scripts/lanhu_parser.py *)
  - Bash(python3 *scripts/lanhu_inspect.py *)
  - Bash(python3 *scripts/lanhu_query.py *)
  - Bash(python3 *scripts/validate_layout_analysis.py *)
  - Agent
  - Bash(file *)
  - Bash(find *)
  - Bash(grep *)
  - Bash(rg *)
  - Bash(ls *)
  - Bash(test *)
  - Bash(adb *)
  - Bash(cp *)
  - Bash(svn *)
  - Bash(git *)
  - Bash(sh gradlew *)
  - Bash(./gradlew *)
---

## 输入解析

从用户输入中提取关键信息：

1. **截图 URL**：从插件固定提示词中的截图地址/截图url字段读取（`alipic.lanhuapp.com/SketchCover*`）
2. **Sketch JSON URL**：从插件固定提示词中的 sketchjson/设计稿JSON url字段读取（`alipic.lanhuapp.com/SketchJSONURL*`）
3. **用户意图**：从后续描述判断
   - "帮我生成 XXXFragment/Activity/页面代码" → **生成页面**
   - "帮我按新设计图修改 XXX 页面" → **修改已有页面**
   - "帮我检查/重点检查/核对/对比 XXX 是否一致/还原度" → **还原度检查**


## 推荐输入提示词

插件侧推荐固定生成以下三类短提示词。用户提示词只需要提供稳定字段和任务类型；具体执行步骤由 skill 自动识别并进入对应子流程。

### 生成页面

```text
技能:lanhu-android /lanhu-android 截图地址:<截图URL> sketchjson:<SKETCH_JSON_URL> 页面:<页面名> 任务:生成新页面
```

适用：从 0 创建 `DiaryFragment`、`HomeActivity`、`item_xxx` 等页面、布局和必要代码骨架。

### 修改已有页面

```text
技能:lanhu-android /lanhu-android 截图地址:<截图URL> sketchjson:<SKETCH_JSON_URL> 页面:<页面名> 任务:修改现有页面
```

适用：已有 `DiaryFragment`，需要按新设计图调整 UI，但不能破坏业务逻辑。

### 还原度检查

#### 标准模式（用户提供实现截图）

```text
技能:lanhu-android /lanhu-android 截图地址:<截图URL> sketchjson:<SKETCH_JSON_URL> 页面:<页面名> 任务:还原度检查 检查目标:<检查目标> 实现截图:<实现截图路径或URL>
```

适用：检查整页或卡片、标题栏、底部按钮、列表 item 等局部样式是否还原，只输出差异报告和修复建议，不直接改文件。

#### ADB 自动截图引导模式（推荐）

```text
技能:lanhu-android /lanhu-android 截图地址:<截图URL> sketchjson:<SKETCH_JSON_URL> 页面:<页面名> 任务:还原度检查 检查目标:<检查目标>
```

适用：用户未提供实现截图参数，Skill 自动检测设备并引导 ADB 截图。这是**还原度检查的推荐模式**，因为视觉对比验证是核心价值。

**执行流程**：
1. Skill 自动检测设备连接（`adb devices`）
2. 检测到设备 → 输出引导提示，等待用户回复"截图"
3. 未检测到设备 → 提示用户连接设备或手动提供截图
4. 获取截图后 → 进入视觉对比验证（Phase 3）

#### 强制 ADB 截图模式

```text
技能:lanhu-android /lanhu-android 截图地址:<截图URL> sketchjson:<SKETCH_JSON_URL> 页面:<页面名> 任务:还原度检查 检查目标:<检查目标> --adb-screenshot
```

适用：明确要求使用 ADB 截图，跳过设备检测，直接输出引导提示。

## 执行流程

各任务单独执行，按 `任务:` 字段确定流程，不混用。

1. 生成页面
   1. 读取截图和 Sketch JSON
   2. 提取页面结构、组件、资源和视觉规则
   3. 生成页面/Fragment/Activity 代码与布局
   4. 校验资源命名、布局规则与样式一致性

2. 修改已有页面
   1. 读取目标页面当前实现
   2. 对比设计稿与现有界面结构
   3. 生成调整建议并保留原业务逻辑
   4. 输出可执行改动或修复说明

3. 还原度检查
   1. 读取检查目标与设计稿
   2. 确定截图来源：用户提供或 ADB
   3. 执行视觉对比分析
   4. 输出差异报告和修复建议，不直接改文件

## 读取规则

读取维度有两个：**按任务类型**（下表 1）和**按是否触碰资源/布局**（下表 2）。两个维度叠加，不是二选一。

### 1. 按任务类型

| 任务 | 必读 |
|------|------|
| 全部任务（最先读） | [rules/core-rules.md](rules/core-rules.md) |
| 全部任务（进入目标 Android 项目后） | 宿主项目根的 `CLAUDE.md` / `AGENTS.md`（存在时）——**构建命令与 flavor 变体**、模块划分、页面归属约定。编译验证的命令以它为准（见 core-rules §9），不要照抄 skill 里的默认命令 |
| 涉及 `layout_analysis.json` | [schemas/layout-analysis-schema.md](schemas/layout-analysis-schema.md) |
| 生成页面 | [commands/extract.md](commands/extract.md)、[commands/create-page.md](commands/create-page.md)、[commands/xml.md](commands/xml.md) |
| 修改已有页面 | [commands/restyle-page.md](commands/restyle-page.md)、[rules/restyle-guardrails.md](rules/restyle-guardrails.md)、[schemas/change-impact-schema.md](schemas/change-impact-schema.md) |
| 还原度检查 | [commands/restore-check.md](commands/restore-check.md) |
| extract 阶段（额外） | [rules/extract-rules.md](rules/extract-rules.md) |

### 2. 按是否触碰资源/布局

本次任务**会新增或修改**以下任一项时，无论任务类型是哪一个，都必须读 [rules/resource-rules.md](rules/resource-rules.md) 和 [rules/layout-rules.md](rules/layout-rules.md)：`android:` 属性、`@drawable` 引用、`<shape>` / `<vector>`、切图文件、`colors` / `styles`。

修改已有页面同样涉及布局属性、切图尺寸与资源替换，**不是"只读 restyle-guardrails 就够"**。

两个维度的读取集合在 `加载规则` 步骤（[core-rules.md §0](rules/core-rules.md) 第 0 步）汇总，并写入报告头部的「规则加载表」。

### 3. 资源自检表（改完资源后逐项确认）

| 触发条件 | 必读章节 |
|---------|---------|
| 节点存在 `slice` 字段或能匹配 `slices.json` | [resource-rules.md §7.1](rules/resource-rules.md) 命名、[§7.2](rules/resource-rules.md) 尺寸 |
| 设计稿预期为图形但本画板无切图 | [resource-rules.md §7.5](rules/resource-rules.md) 缺失切图处置 |
| 需要判断"项目里是否已有该资源" | [resource-rules.md §7.6](rules/resource-rules.md) 资源同一性比对 |
| 需要确定某个切图对应哪个节点 | [resource-rules.md §7.7](rules/resource-rules.md) 切图与节点映射 |
| `slices.json` 有重复 `local_path`/`drawable_name` 指向不同 `download_url` | [resource-rules.md §7.7](rules/resource-rules.md) 同名切图覆盖 |
| 任何 `@drawable/shape_*` / `bg_*` / `android:background` | [resource-rules.md §7.4](rules/resource-rules.md) |
| 新增通用图标 | [xml.md](commands/xml.md)「资源处理」查重项 |

### 4. 读图

截图结构分析、截图级对比、切图/图标语义确认一律派发子 agent 读取图片（主 Agent 不直接 Read 截图）。
能答什么、不能答什么（精确色值/尺寸一律不采信）见 [rules/core-rules.md](rules/core-rules.md) §10 读图能力边界。

`extract_dir` 的规则以 [rules/core-rules.md](rules/core-rules.md) §4.1 和 [commands/extract.md](commands/extract.md) 为准。

## 阶段职责边界

- 读图子 agent（extract 阶段派发）：只负责截图结构理解、页面分区、视觉包裹关系、Z 轴/遮挡关系、动态区域归属和待确认项；它只回传定性结论，不直接写文件。
- `layout_analysis.background_layers`：记录页面背景色、区块背景、卡片背景、顶部/底部装饰背景和整页大尺寸切图；`source` 只允许 `slice`、`shape`、`color`。
- `lanhu_query.py` / XML 阶段：负责精确尺寸、坐标、颜色、字号、圆角、描边、切图尺寸和资源命名。
- `restore-check` / 读图子 agent：负责实现截图与设计稿截图的最终视觉对比。

主流程负责把读图子 agent 的定性结论与 parser 产物中的 `schema_version`、`design_id`、`source` 等元数据合并，并写入 `layout_analysis.json`。主流程不得手写篡改子 agent 的视觉结论；如果分析不合格，只能重新派发、降级或阻塞。

## 统一执行清单

所有子流程都必须完成 [core-rules.md §0 执行清单](rules/core-rules.md#0-执行清单优先全局唯一权威版本)。禁止跳步，每步要么明确完成，要么明确降级/阻塞。

任务类型对应的补充项：

| 步骤 | 生成页面 | 修改已有页面 | 还原度检查 |
|------|---------|-------------|-----------|
| `搭页面` | 判定页面边界（Fragment/Activity/Item/Dialog） | 结构比对 + 差异分类 + 引用扫描 | 标注核对清单 |
| `自我检查` | `create_page_report.md` + `xml_report.md` | `restyle_report.md` + 标注对照表 | `restore_check_report.md` |

## 目录结构

本 Skill 当前发布目录采用“主文档 + 专题子目录”的扩展结构，发布时应保持以下内容齐全且相互引用一致：

- `README.md`：对外说明、版本记录、目录说明、示例入口。
- `SKILL.md`：路由、执行流程和约束规则。
- `commands/`：`extract`、`xml`、`create-page`、`restyle-page`、`restore-check` 五个子命令说明。
- `rules/`：全局规则与改造防护规则。
- `schemas/`：`layout_analysis`、`change_impact`（restyle 报告）结构约束。
- 读图：截图结构分析与视觉对比由主流程派发子 agent 完成，不依赖本 skill 外的视觉脚本。
- `scripts/`：`lanhu_parser.py`、`lanhu_inspect.py`、`lanhu_query.py`、`validate_layout_analysis.py`。
- `.claude-plugin/plugin.json`：Skill manifest。

## 执行流程

### 生成页面

```text
输入 → extract(json_url + screenshot_url) → 意图确认 → create-page/xml 生成页面 → 验证 → 输出
```

1. 执行 `python3 <skill_dir>/scripts/lanhu_parser.py "<json_url>" -o "./lanhu" --screenshot "<screenshot_url>" -v`
2. 派发子 agent 读取 `<extract_dir>/screenshot.png` 做截图结构分析（主 Agent 不直接 Read 截图）。prompt 中给出 implementation_context 与需回答的视觉问题，要求只回传结构化定性结论；主流程取该结论合并 parser 骨架后写入 `layout_analysis.json`。
3. 执行 `python3 <skill_dir>/scripts/validate_layout_analysis.py "<extract_dir>"`，按返回的 `status` 决定下一步：
   - `ready`：产物已具备实现条件，继续后续步骤。
   - `needs_enrichment`：当前仍是 extract 骨架（未合并视觉分析），回到步骤 2 补 `screenshot_review` 与结构字段后再继续。
   - `blocked`：按 `errors` 逐项修复后重跑，禁止跳过；`next_action` 给出下一步动作。
4. 理解用户意图（页面类型、架构边界、核心交互、数据区域），必要时 `AskUserQuestion` 确认——**每轮最多 4 个问题、可分多轮**，必问清单见 [rules/core-rules.md](rules/core-rules.md) §3
5. 按 [commands/create-page.md](commands/create-page.md) 判断是否需要代码骨架；布局和资源细节按 [commands/xml.md](commands/xml.md)
6. 如果落地到 Android 项目，优先复用项目现有 Fragment/Activity、ViewBinding/DataBinding、Adapter 命名和目录模式，生成必要代码骨架
7. 能定位 Gradle wrapper 时运行最小可用编译验证；不能验证时写入报告

### 修改已有页面

```text
输入 → extract(json_url + screenshot_url) → 结构比对 → 引用扫描 → 意图确认 → 受控改造 → 输出
```

1. 执行 extract（同上步骤 1-3）
2. 结构比对：将旧页面元素清单与 `layout_analysis.json` 的 `element_classification` + `slices.json` 逐一比对，产出差异清单；每项差异标注 `diff_type`（样式更新/新增/删除/结构重组/角色变更），分类策略见 [rules/restyle-guardrails.md](rules/restyle-guardrails.md) 的"差异分类与默认策略"章节
3. 引用扫描：旧页面布局文件、ID 绑定、点击事件、Adapter 和埋点；背景图/切图的引用额外检查 drawable 资源的全局依赖
4. 按 [commands/restyle-page.md](commands/restyle-page.md) 受控改造，保留原有业务逻辑
5. 必须输出 `restyle_report.md`（含执行前计划与执行后证据），`planned_changes` 每项必须标注 `diff_type` 和 `resource_impact`
6. 高风险改造先输出计划并等待用户确认

如果用户提供 `页面文件:<绝对路径>`，必须先读取该文件并以它作为旧页面入口，再从其中的 binding/layout/include/Adapter 引用向外扩展扫描；禁止先做全项目模糊搜索来替代已给出的页面文件。

### 还原度检查

```text
输入/前序产物 → 静态标注核对 → 实现截图获取（可选） → 视觉对比验证 → 输出检查报告
```

触发条件：

- 用户说“重点检查、检查、核对、对比、是否一致、还原度”等，且没有明确要求继续生成或改造。
- 用户在前面步骤之后补充新的蓝湖截图 URL/JSON URL，并要求检查某个区域，例如“设计稿中卡片的样式与设计稿是否一致”。
- 如果用户要求“检查后直接修、调整、改到一致”，本流程仍只输出差异和修复建议；需要动代码时让用户改用 **修改现有页面**。

**核心原则：标注优先，视觉辅助**

执行规则：

1. **Phase 1: 静态标注核对（必做）**
   - 如果用户提供新的蓝湖 JSON URL，仍然先 extract，保证标注和截图是最新设计稿。
   - 如果没有新 URL，复用最近一次 `<extract_dir>`；找不到时先让用户提供设计稿 URL 或 extract 目录。
   - 使用 `lanhu_query.py` 查询关键节点标注数据（backgroundColor、borderRadius、fontSize等）。
   - 对照实现代码（XML/drawable/colors.xml）逐项核对，输出静态核对清单。

2. **Phase 2: 实现截图获取与引导（核心）**
   - **未提供实现截图时，必须主动引导用户获取截图**，而不是直接降级到静态核对。
   - 执行设备检测（`adb devices`）：
     - 检测到设备 → 输出引导提示：”请在设备上打开目标页面，准备好后回复'截图'”
     - 未检测到设备 → 提示用户连接设备或手动提供截图路径
   - 用户回复”截图”后 → 执行 `adb exec-out screencap -p` 并保存到 `<extract_dir>/actual_screenshot.png`
   - 只有在用户明确回复”跳过”或无法连接设备且无法提供截图时，才降级到静态核对，状态标为 `warning`。
   - 详细流程见 [commands/restore-check.md](commands/restore-check.md) Phase 2。

3. **Phase 3: 视觉对比验证（在获取实现截图后执行）**
   - 只有成功获取实现截图时才派发子 agent 做视觉对比：prompt 中给出设计稿截图、实现截图路径、关键节点标注数据和检查目标。
   - 子 agent 负责验证静态核对是否正确落地、补充动态效果和视觉细节，只回传定性差异结论。
   - 未获取实现截图时跳过此步骤，仅输出静态核对结果，状态标为 `warning`。

4. 识别检查目标：如卡片、按钮、标题栏、底部栏、列表 item；用户未指定时默认检查整页核心区域。
5. 输出 `<extract_dir>/restore_check_report.md`，卡片类检查必须覆盖背景色、圆角、描边、阴影、尺寸、内边距、元素间距、文字样式、切图使用和点击区域。

## 意图先行

当用户同时给出设计稿和描述性需求时，必须先把自然语言整理成实现意图，再带着意图理解截图和生成布局。

实现意图至少关注：

- 页面归属：`Fragment`、`Activity`、`Dialog`、`Item` 或未知。
- Android 架构边界：宿主导航、底部 Tab、标题栏、弹窗遮罩等是否属于当前布局文件。
- 核心交互：列表、横滑卡片、按钮、输入、状态切换、空态/加载态等。
- 数据区域：静态展示、可复用 item、`RecyclerView`、`ViewPager2`、需要保留的业务承接 ID。
- 用户明确取舍：例如要整体还原、只做某个模块、复用现有组件、保留/排除某个区域。

无法确定且会影响文件拆分、宿主归属、动态区域或关键 ID 时，先问用户；低风险细节按常识假设并写入报告。

## 上下文节制

skill 执行时不要把中间思考、大 JSON、完整节点表或图片内容搬进对话。默认把结构化结论沉淀到文件：

- `layout_analysis.json`：用户意图、Android 布局假设、截图结构、待确认项。
- `xml_report.md`：最终布局决策、包含/排除区域、动态数据区域、资源和风险。

聊天中只输出短摘要、阻塞项和必须由用户决定的问题。读取设计稿数据时优先使用轻量摘要和局部查询脚本。

## 固定脚本

禁止：`python -c`、`python3 -c`、管道 `| head`、`2>/dev/null` 隐藏错误、直接 grep JSON。
禁止直接 `Read screenshot.png`。需要确认截图文件时用 `file` 或 `lanhu_inspect.py --compact-for-xml`；需要视觉理解时只把截图交给指定视觉分析步骤。

```bash
python3 <skill_dir>/scripts/lanhu_parser.py --help
python3 <skill_dir>/scripts/lanhu_parser.py "<json>" -o "<output>" --screenshot "<screenshot>" -v
python3 <skill_dir>/scripts/lanhu_inspect.py --help
python3 <skill_dir>/scripts/lanhu_inspect.py "<extract_dir>"
python3 <skill_dir>/scripts/lanhu_inspect.py "<extract_dir>" --compact-for-xml
python3 <skill_dir>/scripts/lanhu_inspect.py --json-file-summary "<raw_json_path>"
python3 <skill_dir>/scripts/lanhu_query.py --help
python3 <skill_dir>/scripts/lanhu_query.py "<extract_dir>" --list-names --sort y --limit 120
python3 <skill_dir>/scripts/lanhu_query.py "<extract_dir>" --search "关键词" --sort y --limit 80
python3 <skill_dir>/scripts/lanhu_query.py "<extract_dir>" --node-ids "id1,id2,id3" --with-children --compact-output
python3 <skill_dir>/scripts/lanhu_query.py "<extract_dir>" --node-ids "id1,id2,id3" --depth 2 --compact-output
python3 <skill_dir>/scripts/validate_layout_analysis.py --help
python3 <skill_dir>/scripts/validate_layout_analysis.py "<extract_dir>"
```

如需检查原始 JSON 顶层结构、截图字段或图片 URL，必须使用 `lanhu_inspect.py --json-file-summary`，禁止使用 `python -c` / `python3 -c` 临时脚本。

> `--with-children` 只展开**直接子节点**（1 层）。角标组、Tab 图标组这类嵌套结构需要 2~3 层，
> 用 `--depth N` 一次拿到，**不要**用子节点 id 反复迭代查询（既慢又容易漏）。

## 硬规则

- 有蓝湖 JSON URL 时，先 extract，禁止直接改 Android。
- 截图 URL 和 Sketch JSON URL 来自插件固定提示词字段；字段缺失时先输出 `blocked`。
- 未查看截图，禁止生成/改造布局。
- 缺 `annotations.json`，禁止脑补尺寸/坐标/字号。
- `blocked` 时停止后续高风险步骤，向用户确认。
- 禁令项不得作为 `AskUserQuestion` 的选项；只能就"如何满足禁令"提问（如切图缺失时按 [resource-rules.md §7.5](rules/resource-rules.md) 的三选一处置），不得就"是否遵守禁令"提问。

## 状态输出

```text
status: success | warning | blocked
outputs:
  - <path>
warnings:
  - <warning>
blocked:
  - <blocker>
next:
  - <next>
```
