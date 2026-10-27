---
name: lanhu-core-rules
description: 蓝湖 skill 核心规则，所有命令执行前必须读取并遵守。涵盖执行清单、截图先行、意图理解、上下文节制、中间产物管控、阻塞条件和统一输出格式。
---

# 核心规则

这些规则适用于 `extract`、`xml`、`create-page`、`restyle-page`、`restore-check` 全部命令。

> 切图/资源细节见 [resource-rules.md](resource-rules.md)，布局生成细节见 [layout-rules.md](layout-rules.md)，extract 特有规则见 [extract-rules.md](extract-rules.md)，改造防护见 [restyle-guardrails.md](restyle-guardrails.md)。

## 强制规则

### 0. 执行清单优先（全局唯一权威版本）

相比"记住原则"，所有蓝湖相关任务都必须按 checklist 推进。每一步都要么明确完成，要么明确降级/阻塞，禁止跳步。**各命令文件不得复制本清单，只能引用并补充命令特有的子项。**

0. `加载规则`（必须在读取产物、生成任何产物之前完成）
   - 按两个维度取交集确定本次必读集合：任务类型（生成 / 修改 / 检查）与本次会触碰的产物类型（布局 / 切图 / shape / 代码 / 宿主）。
   - 触碰以下任一项时，`rules/resource-rules.md` 与 `rules/layout-rules.md` 为强制项：`android:` 属性、`@drawable` 引用、`<shape>` / `<vector>`、切图文件、`colors` / `styles`。
   - 已从本次命令对应的 `commands/*.md` 中摘出该命令特有的规则路径要求（如 xml.md Step 0.1 的 `xml_rule_paths` 与 `conditional_rule_paths`）。
   - 已读取宿主项目根的 `CLAUDE.md` / `AGENTS.md`（存在时）。
   - 加载结果写入报告头部的「规则加载表」（结构见对应 `commands/*.md` 的报告结构），未读项必须显式标注未读及原因。
   - 禁止以"记得规则大意"替代实际读取；规则路径不存在时按 blocked 处理。

1. `看截图`
   - 已确认截图路径可用。
   - 已派发子 agent 真正查看截图（主 Agent 不直接 Read 截图）。
   - 已在 `layout_analysis.json.screenshot_review` 留下看图证据（`viewed=true`，`evidence` 至少 3 条，`coverage` 非空）。
2. `校验分析`
   - 已运行 `validate_layout_analysis.py "<extract_dir>"`，并按返回的 `status` 决定下一步，禁止只看"有没有报错"：
     - `ready`：产物已具备实现条件，继续下一步。
     - `needs_enrichment`：当前是 extract 骨架，尚未合并视觉分析；先补 `screenshot_review` 与结构字段再继续。
     - `blocked`：按 `errors` 修复后重跑，不可跳过。
   - `status=blocked` 时已按降级策略（见 [extract-rules.md](extract-rules.md) §13）重跑、降级或阻塞。
3. `看 JSON`
   - 已通过 `lanhu_inspect.py --compact-for-xml` 获取轻量摘要。
   - 需要精确值时已通过 `lanhu_query.py` 做局部查询。
   - 没有直接读完整大 JSON 或靠肉眼估尺寸。
4. `搭页面/改页面`
   - 已基于用户意图和截图结构形成布局计划。
   - 已说明包含区域、排除区域、动态区域承载方式。
   - 改旧页面前已完成：元素清单结构比对 ± 差异分类（见 restyle-guardrails §差异分类与默认策略）、引用扫描、影响分析。
5. `回看数据`
   - **每个卡片/区域做之前**先查该区域 `borderRadius`、`borderOptions`、父容器全部子节点（确认有无分割线/装饰层）。
   - 关键尺寸、颜色、圆角、字号、切图尺寸已回查 `annotations.json` / `slices.json`。
   - `layout_analysis.background_layers` 中的背景层已逐项确认落地方式（`slice` / `shape` / `color`）。
   - Shape drawable 引用范围已检查（`rg "@drawable/<name>"`），多页面共享时新建而不覆盖。
   - 没有把视觉猜测当成精确值。
6. `自我检查`
   - 已输出对应报告文件。
   - 已记录 `status / warnings / blocked / next`。
   - 改造任务必须包含标注对照表。
   - 能编译就编译（命令来源、flavor 变体处理、失败归属见 §9 编译验证），不能编译就明确写原因，禁止声称编译通过。

第 0 步未完成时，禁止读取产物、禁止生成任何布局或资源文件，只能输出 blocked 并说明缺失的规则路径。
如果第 1 步未完成，后续最多只能做降级分析或基础骨架，禁止宣称"已理解完整布局"。
如果任一步未完成，必须在报告里显式写明，不得用笼统措辞掩盖。

### 1. 截图先行

执行视觉理解、布局生成、页面创建或页面改造前，必须查看设计稿截图。

主 Agent 禁止直接 `Read screenshot.png`。图片会以 base64 形式进入上下文，导致大量 token 消耗。确认截图存在、格式和尺寸时使用 `lanhu_inspect.py --compact-for-xml` 或 `file <screenshot.png>`；需要视觉理解时派发子 agent 读图（见 §10）。

没有截图时：

- 允许解析 JSON 和生成基础结构产物。
- 不允许声称已经理解完整页面布局。
- 不允许进行高还原度 XML 或大范围页面改造。
- `layout_analysis.json` 必须标记 `confidence=low`，并写入 `risk_flags: missing_screenshot` 或 `missing_visual_review`。

### 2. 先理解用户意图

生成布局前，必须先从用户描述中提炼实现意图，并让后续截图分析、布局拆分和 XML 生成都使用同一份意图。

意图理解必须结合 Android 布局常识，但不能过度猜测：

- 用户说 `HomeFragment`、`xxxFragment` 时，默认把它理解为宿主容器中的内容页；截图里的底部 Tab、全局导航、宿主级悬浮入口通常不直接放进 Fragment。
- 用户说 `Activity` 或"整页/整个页面都实现"时，可以把全屏导航和固定底部区域纳入当前布局。
- 用户提到"列表""卡片""可左右滑动""瀑布流"等动态区域时，应优先判断是否拆成 `item_*.xml` 并用 `RecyclerView`/`ViewPager2` 承载。
- 用户明确要求保留、排除、复用或只实现某个区域时，该要求优先于机械还原全部节点。
- 用户没有表达的视觉细节，不要扩展成业务逻辑或额外页面代码。

必须保留设计稿事实和用户意图的边界：`annotations.json`/`slices.json` 负责精确事实，用户意图负责结构取舍和 Android 架构决策。

### 3. 必要互动

在继续生成或改造前，遇到会改变架构或文件拆分的歧义，必须向用户确认或输出 `blocked`。

**提问容量**：`AskUserQuestion` 每轮最多 4 个问题，**可以分多轮**。禁止把 6 项待确认硬压成 3 项——
压下去的项会被当成"已知"并直接写进实现，这是错误结论最常见的来源。问题多时按"会不会改变文件结构/资源选择"
排序，先问影响最大的；一轮问不完就接着问第二轮。

常见确认项：

- `Fragment` 截图中包含底部 Tab/全局导航：确认该区域是否属于宿主 Activity。
- 重复卡片/列表区域：确认是拆 `RecyclerView item`、`ViewPager2 item`，还是静态还原。
- 设计稿包含多个明显页面区域：确认本次只实现哪一部分。
- 关键交互或 ID 可能影响已有业务：确认保留方式。

**必问清单**（命中即必须问用户，禁止自行假设后直接实现）：

| 类别 | 判据 | 典型实例 |
|------|------|---------|
| 资源来源不明 | 设计稿预期为图形但本画板无切图 | 星标图标→确认是复用首页切图还是新增 |
| 交互语义变更 | 设计稿新增控件但无对应接口/字段 | 星标→确认是"收藏态"还是纯装饰 |
| 与现有实现冲突 | 设计稿未绘制但现有实现存在 | 搜索历史区、信息流广告位 |
| 结构差异 | 设计稿结构与现有实现不一致 | 快递电话 3 列网格 → 单行横向 |
| 数据来源 | 新区块无专用接口 | "猜你喜欢"复用哪个已有接口 |

未问就问不出结论的项，必须落在 `layout_analysis.confirmation_items` 或 `restyle_report.manual_confirmations`，
并保持 `resolved=false` 直到用户回答。

### 4. 上下文节制

中间思考和大产物不要长篇进入对话上下文。结构化结论写入文件，聊天中只保留当前决策需要的信息。

必须遵守：

- 不直接读取完整大 JSON、截图 base64 或大量节点列表；优先用 `lanhu_inspect.py --compact-for-xml` 和 `lanhu_query.py` 局部查询。
- 检查原始 JSON 顶层结构、截图字段或图片 URL 时，使用 `python3 <skill_dir>/scripts/lanhu_inspect.py --json-file-summary "<raw_json_path>"`。
- annotations 缺少颜色字段时，优先使用 `python3 <skill_dir>/scripts/lanhu_inspect.py --json-color-summary "<extract_dir>/raw.json"`；如果 `<extract_dir>/raw.json` 不存在，先重新执行 `extract`，不要猜测临时文件路径。
- 禁止使用 `python -c` / `python3 -c` 拼临时脚本检查 JSON、截图或项目结构。
- 读图子 agent 只回传视觉定性结论，不直接写文件；主流程负责合并 parser 元数据并写入 `layout_analysis.json`。
- **字段归属**（谁写、谁不得写，禁止含糊）：
  - **读图子 agent 负责**：`sections`、`screenshot_review`、`background_layers` 等**定性视觉结论**字段——主流程**不得手写篡改**；分析不合格只能重新派发、降级或阻塞。
  - **主流程负责**：`user_intent`、`android_layout_assumptions`、`confirmation_items`（子 agent 输出的这三项恒为空数组——它不知道项目现有实现），以及 `schema_version` / `design_id` / `source` 等元数据。
- 用户意图、Android 假设、确认项写入 `layout_analysis.json`；最终取舍和风险写入 `xml_report.md`，向用户确认。
- 读图子 agent 不要输出分析过程、Markdown 表格或逐节点长解释。
- 用户意图、Android 假设、确认项写入 `layout_analysis.json`；最终取舍和风险写入 `xml_report.md`，向用户确认。
- 和用户互动时只问会影响实现方向的问题，不要把所有不确定视觉细节都变成问题。
- 报告保留决策摘要和可追溯来源，不逐条展开无关节点。

### 4.1 extract_dir 是唯一真源

`extract` 完成后，后续 `xml/create-page/restyle-page/restore-check` 一律复用 **实际生成的 `<extract_dir>`**，禁止再根据 `sketchjson` 原始 URL、长 hash、页面名或临时猜测去重新拼目录名。

必须遵守：

- 后续步骤的输入目录以 parser 实际输出的 `extract_dir` 为准。
- 优先读取 `<extract_dir>/source_meta.json` 中记录的 `extract_dir`、`design_id` 和 `original_url` 做追溯。
- 如果当前上下文只有 `sketchjson` URL，没有明确的 `<extract_dir>`，先重新定位目录再继续，不要直接拼接 `./lanhu/<url末段>`。
- 如果发现 prompt 中的长 URL 与本地目录名不一致，以实际 `<extract_dir>` 为准，而不是以 URL 末段为准。

禁止：

- 根据 `sketchjson` 的完整 URL 末段直接推导目录名。
- 依赖"目录名通常等于 hash"之类的经验规则继续后续流程。
- 在未确认 `<extract_dir>` 前调用 `lanhu_inspect.py`、`lanhu_query.py`、`xml`、`restore-check`。

### 5. annotations 优先

尺寸、坐标、间距、字号、颜色、圆角、描边等精确值以 `annotations.json` 为准。

禁止：

- 根据截图目测精确尺寸。
- 在标注缺失时脑补数值。
- 使用"看起来差不多"的间距替代标注。

> 富文本分段样式细节见 [layout-rules.md](layout-rules.md) §5.1。

### 6. 中间产物不得跳步

执行链路必须满足：

```text
用户意图/必要确认 -> extract -> layout_analysis -> xml/create-page/restyle-page/restore-check
```

缺失关键产物时必须降级或阻塞，不得假装已生成。

视觉理解相关的关键产物除了 `layout_analysis.json` 本身，还包括其中的 `screenshot_review`。没有该字段或字段不合格，视为没有完成截图理解步骤。

### 7. 切图优先

有以下任一条件时，必须优先使用 `ImageView + 切图`：

- 节点存在有效 `slice` 字段。
- `slices.json` 中能匹配到该图层或位置。
- 视觉元素是复杂背景、图标、插画、图片按钮或设计师明确导出的资源。

**禁止用 vector drawable 替代蓝湖切图。**

> 切图命名、尺寸、Shape 验证、缺失处置等细节见 [resource-rules.md](resource-rules.md)。

### 8. 结构先于视觉细节

先确定页面结构和容器层级，再处理文本、图片、背景、圆角和描边。

推荐顺序：

1. 根布局和滚动策略。
2. 固定区域和滚动区域。
3. 容器和组件分组。
4. 子元素约束。
5. 资源和样式。

结构决策必须同时参考：

- 用户意图和确认结果。
- Android 架构边界。
- `layout_analysis.json` 的区域/组件建议。
- `annotations.json` 的精确尺寸和位置。
- `slices.json` 的切图事实。

### 9. 编译验证

**构建命令来源**：优先采用宿主项目根 `CLAUDE.md` / `AGENTS.md` 声明的构建命令（含 flavor 变体、模块划分）。
本规则给的是最小公约数默认值，多 flavor 项目下它可能**根本不是**该模块的验收命令。

```bash
./gradlew :app:assembleDebug
```

命令不可用时（报错 `Task 'assembleDebug' not found`，或项目声明了 `productFlavors` 导致 task 名带变体）
**禁止原样重试**，按序处理：

1. `./gradlew tasks --all | grep -i "assemble.*Debug"` 列出真实存在的变体 task
   （形如 `:app:assembleAutomatic_nnshianDebug`）。
2. 取宿主 `CLAUDE.md` / `AGENTS.md` 声明的主渠道变体；未声明时取与当前调试包一致的变体。
3. 模块名不是 `app` 时用真实模块名（`./gradlew projects` 查看）。
4. 报告中记录**实际执行的命令**与选择原因，不要照抄本文默认命令。

同一变体规则适用于编译 task：flavor 项目里 `:app:compileDebugKotlin` 同样要带变体
（`:app:compile<Flavor>DebugKotlin`）。

**先归属再修**：报错文件不在本次改动集内（并行会话把主干改坏）时，禁止直接改那些文件——它们不属于本次
改动范围，代改会掩盖他人 WIP 的真实状态并可能覆盖对方正在编辑的内容。处理方式：

1. 用 `git status --short`（或 `svn status`）列出本次改动集，逐个核对报错文件是否在集合内；
   全部不在 → 属他人改动，进入第 2 步；只要有一个在 → 按普通编译失败修复，不得降级。
2. 退到**本次改动涉及的模块**跑最小验证，证明自身自洽：
   `:app:compile<Flavor>DebugKotlin`（源码）、`:app:DataBindingGenBaseClassesDebug`（DataBinding 布局）、
   `:app:process<Flavor>DebugResources`（资源）。
3. **最小验证也被同一模块的他人 WIP 阻塞时**（单 module 项目很常见：`:app` 里就有那个坏文件），
   才允许**临时打桩**——做让编译通过的最小改动（如把不存在的方法调用换成等价 API），并且：

   - 打桩前该文件的 md5 已在 Phase 3.0 记入 `baseline`；打桩后**必须逐字节还原**并复核 md5 一致；
   - 还原后要能复述"现在的编译状态 = 打桩前的状态"，不得把打桩版本留在工作树；
   - 打桩**必须**在报告里留痕（哪个文件、改了什么、md5 前后值），否则视为污染他人 WIP；
   - 禁止把打桩写进 `planned_changes`，禁止据此声称项目整体编译通过。

   > 打桩有残留风险（会话中断即留下他人文件的改动）。所以顺序是「零写入的最小验证优先，打桩是最后手段」，
   > 且打桩后应尽快在同一轮对话内还原。
4. 最终状态只能标 `warning`，并写 `verified_scope:` 说明验证到了哪一层、哪一步被阻塞、阻塞者是谁的改动；
   **不得标 `success`**，也不得声称"编译通过"。

**kapt / DataBinding 缓存损坏**（症状很迷惑人：报错指向与本次改动无关的生成类，如
`error: cannot find symbol class XxxBinding`，而 `XxxBinding.java` 与 `XxxBindingImpl.java` 其实都已生成；
成因是首次编译失败后增量状态损坏）——先删生成目录再重跑，**不要按报错去改源码**：

```bash
rm -rf app/build/generated/data_binding_base_class_source_out \
       app/build/generated/source/kapt \
       app/build/tmp/kapt3
```

仍失败才进入上面的归属分析。

### 10. 读图能力边界与降级处理

读图子 agent 是**定性通道**——能描述"这是什么、长什么样"，
输不出精确数值是**预期中的能力降级**，不是异常。下游按三级处理：

| 子 agent 输出 | 下游行为 |
|-------------|---------|
| 能给出参考值（"偏暗红、约 16sp"） | 标注为推测值，优先用 `annotations.json` 的精确值覆盖 |
| 明确写"看不清/无法判断" | 降级到 `annotations.json` / `slices.json` 查询 |
| 标注数据也缺 | 写 `confirmation_items` 交用户确认，**不阻塞** |

哪些问题该问谁：

| 问题 | 该问谁 | 说明 |
|------|--------|------|
| 页面分区、容器归属、滚动策略、切图粒度、交互热点 | 读图子 agent（截图结构分析） | 定性结论，写入 `layout_analysis.json` |
| 设计稿 vs 实现截图的整体观感差异、遗漏/多余元素 | 读图子 agent（两图对比） | 只给"像不像、差在哪"，不给精确值 |
| **单张切图/图标画的是什么**、是否与目标语义一致、是否与其他切图重复 | 读图子 agent（单图语义确认） | 见下 |
| 坐标、宽高、颜色 hex、字号、圆角、描边、间距 | `annotations.json` / `slices.json` 查询为主；子 agent 输出只作参考 | 子 agent 给的是定性判断，优先采信标注数据 |
| 图标/切图的精确颜色 | `slices.json` → 取图 → 子 agent 确认语义；色值走标注 | 抗锯齿/缩放/压缩下取色必然偏移，标注值>视觉推测 |

**主 Agent 截图禁令**（§1「禁止直接 Read screenshot.png」的适用范围）：

- 主 Agent 不得直接 Read **整页设计稿截图** —— base64 会挤占上下文。
- 单张切图/小图标需要辨识图形时，同样派发子 agent 读取；
  主 Agent **不要** Read 原图，更不要凭文件名或图层名臆断图形内容。

派发语义确认时的 prompt 示例：

```text
读取以下切图，确认每张图画的是什么、是否与目标语义一致、是否与其他切图重复。
切图：<切图1.png> <切图2.png>
目标语义:服务；背景:底部 Tab 第 4 个选中态图标，图层名叫 icon_tab3_sel，父组名叫记账
只回传语义结论，不输出图片内容或色值/尺寸/坐标。
```

语义歧义一旦影响资源选择（如"这个图形是服务还是记账"），**必须先派发子 agent 确认并写进报告**，
不得靠图层名推断；判断仍不确定时列入 `confirmation_items` 交用户决定。

## 风险状态

| 状态 | 含义 | 行为 |
|------|------|------|
| `success` | 产物完整且可进入下一步 | 输出下一步建议 |
| `warning` | 可继续但存在降级或待确认项 | 明确记录 warning |
| `blocked` | 继续会造成明显错误或破坏 | 停止并说明需要补充什么 |

## 必须阻塞的场景

- 蓝湖 JSON 无法解析。
- `annotations.json` 缺失或无有效节点。
- 用户要求高还原度但没有截图。
- 用户要求高还原度生成页面或大范围改造，但 `layout_analysis.json.screenshot_review` 缺失、`viewed=false` 或 `evidence` 不合格。
- 关键切图缺失（设计稿预期为图片/图标但 slices.json 无匹配或下载失败）。处置见 [resource-rules.md](resource-rules.md) §7.5。
- 用户意图和截图结构冲突，且会影响页面归属、宿主导航或动态区域拆分。
- 老页面改造前无法定位旧页面文件。
- 老页面改造需要删除被业务代码引用的关键 ID，但没有替代方案。
- 还原度检查既没有实现截图，也没有可定位的 Android 项目或实现文件。

## 统一输出要求

每个命令结束时都必须输出：

```text
status: success | warning | blocked
outputs:
  - <产物路径>
warnings:
  - <可继续但需注意的问题>
blocked:
  - <阻塞项>
next:
  - <下一步建议>
```

## 报告读者矩阵

本 skill 各报告的**读者、用途和生命周期**，用于判断哪些内容可以精简、哪些必须保留。后续所有修改决策以此表为准。

| 报告 | 产生命令 | 读者 | 必读区块 | 生命周期 |
|------|---------|------|---------|---------|
| `extract_report.md` | extract | 自检证据 | status/warnings/blocked/切图统计 | 过程文件，改后可归档 |
| `layout_analysis.json` | extract | 后续命令（xml/create-page/restyle-page/restore-check） | 全部 | 全流程机器消费者，唯一真源 |
| `xml_report.md` | xml、create-page | 自检证据 + 未来追溯 | 布局决策、排除原因、背景落地清单 | 同次会话 + 交付物 |
| `create_page_report.md` | create-page | 用户审批 + 交付物 | 文件清单、代码骨架边界、编译验证结果 | 交付物；不重复 xml_report 内容 |
| `restyle_report.md` | restyle-page | 用户审批 + 交付物 | 决策摘要、planned_changes、manual_confirmations、执行结果对照、标注对照表、保护项验证、编译验证 | 执行前计划 + 执行后证据合一，改后可归档 |
| `restore_check_report.md` | restore-check | 用户交付物 | 不一致项、风险与限制 | 交付物；只列不一致项 |
| `static_check.md` | restore-check | 自检证据 | — | 过程文件，可选输出

> 报告同名防覆盖：同一 `extract_dir` 处理多个页面时（如父页面 + item 布局、多画板）、或同一页面二次 restyle，报告文件名须以 `_<page>` 限定（如 `xml_report_item_coupon.md`），禁止互相覆盖。
