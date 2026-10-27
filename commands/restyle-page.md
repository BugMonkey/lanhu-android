---
name: lanhu-command-restyle-page
description: 定义 /lanhu-android restyle-page 的完整行为，在旧页面基础上按新设计稿做受控 UI 改造并保留业务逻辑。
---

# restyle-page 命令

`restyle-page` 面向老页面改造。它不是从零重建页面，而是在旧页面基础上受控修改 UI，并最大限度保留业务逻辑、ID、绑定关系、埋点和交互。

## 命令格式

```text
/lanhu-android restyle-page <extract_dir> --page <页面名> [--android-project <path>]
```

## 输入

必需输入：

- `extract_dir`：`extract` 实际生成的提取产物目录。
- `--page`：旧页面名称，如 `HomeFragment`、`MainActivity`、`item_coupon`。

`extract_dir` 的完整规则只引用 [../rules/core-rules.md](../rules/core-rules.md) 和 [extract.md](extract.md)。

必需产物：

```text
annotations.json
slices.json
screenshot.png
layout_analysis.json
```

必需规则：

- 执行前读取 [../rules/restyle-guardrails.md](../rules/restyle-guardrails.md)。
- 影响分析结构遵守 [../schemas/change-impact-schema.md](../schemas/change-impact-schema.md)。

## 输出

```text
<extract_dir>/restyle_report.md
```

以及受控修改后的项目文件，例如：

```text
app/src/main/res/layout/*.xml
app/src/main/res/drawable/*.xml
app/src/main/res/drawable-xxhdpi/*.png
app/src/main/java/**/*.kt
app/src/main/java/**/*.java
```

## 执行阶段

先完成 [core-rules.md §0 6 步执行清单](../rules/core-rules.md#0-执行清单优先全局唯一权威版本)。若 `看截图` 未完成，只允许低风险样式微调。

restyle-page 特有补充：
- `加载规则` 需附加：按 [core-rules.md §0 第 0 步](../rules/core-rules.md#0-执行清单优先全局唯一权威版本) 汇总必读集合，另须含 [restyle-guardrails.md](../rules/restyle-guardrails.md) 与 [change-impact-schema.md](../schemas/change-impact-schema.md)
- `搭页面` 需附加：结构比对（差异分类见 [restyle-guardrails.md](../rules/restyle-guardrails.md) §差异分类与默认策略） + 引用扫描 + 影响分析
- `回看数据` 需附加：Shape drawable 引用范围检查
- `自我检查`：产出 `restyle_report.md`

### Phase 1: 加载设计稿产物

先读取轻量交接摘要：

```bash
python3 <skill_dir>/scripts/lanhu_inspect.py "<extract_dir>" --compact-for-xml
```

读取并检查：

- `annotations.json`
- `slices.json`
- `layout_analysis.json`
- `screenshot.png`
- `issues.json`（如存在）

禁止直接 `Read screenshot.png` 或完整读取大体积 `annotations.json` 来寻找少量节点。节点定位优先使用：

```bash
python3 <skill_dir>/scripts/lanhu_query.py "<extract_dir>" --search "关键词" --sort y --limit 40
python3 <skill_dir>/scripts/lanhu_query.py "<extract_dir>" --node-ids "id1,id2,id3" --with-children --compact-output
# 嵌套结构用 --depth 2~3（--with-children 只有 1 层）
```

缺少截图或结构化分析时，只允许做低风险样式调整，不允许大规模结构重排。

### Phase 2: 定位旧页面文件

根据 `--page` 搜索：

- Fragment / Activity / View / Adapter / ViewModel。
- `res/layout` 中的页面布局、item、include、dialog、header、footer。
- databinding 生成类或 ViewBinding 使用点。

如果用户提供了 `页面文件:<绝对路径>`，先读取该文件并作为页面入口；再从文件内容识别布局绑定、include、Adapter、ViewModel、点击和埋点引用。只有页面文件缺失或不可读时，才退回到按页面名全项目搜索。

优先使用 `rg`：

```bash
rg "class <PageName>|<PageName>" <android-project>
rg "@\\+id/|@id/" <layout_dir>
rg "binding\\.|findViewById|setOnClickListener|observe\\(" <source_dir>
```

### Phase 3: 结构比对、资源同一性比对、引用扫描与影响分析

#### Phase 3.0: 工作树基线与并发检查（产出写进 restyle_report）

改造前先固定基线。它决定后面所有"这次编译失败该不该我修"的判断——**没有基线就证明不了归属**：

```bash
git status --short            # 或 svn status
md5 <每个计划 modify 的文件>   # macOS；Linux 用 md5sum
md5 <布局引用到的 drawable>
```

- 未提交改动清单 + 目标文件/引用资源的 md5 与 mtime → 写入 `restyle_report` 的 `baseline`
  （结构见 [../schemas/change-impact-schema.md](../schemas/change-impact-schema.md)）。
- 工作树非空时**不阻塞**，但必须在报告里列明这些是他人 WIP、不属于本次改动集。
- 目标文件或引用资源 mtime 晚于本次会话开始 → 记 `concurrency_warnings` 并**提示用户**，
  禁止静默覆盖，用户确认后再改。

#### Phase 3.1: 结构比对

比对旧页面元素清单与 `layout_analysis.json` 的 `element_classification` + `slices.json` 切图清单，产出差异清单。比对维度和分类策略见 [../rules/restyle-guardrails.md](../rules/restyle-guardrails.md) 的"差异分类与默认策略"章节。

旧页面元素清单提取方式：

```bash
# 提取旧布局中的所有 ID 和控件类型
rg "@\\+id/" <layout_file>
rg "ImageView|TextView|Button|RecyclerView" <layout_file>

# 提取旧布局中的 drawable 引用
rg "@drawable/" <layout_file>

# 提取旧布局中的 include/merge 引用
rg "<include|<merge" <layout_file>
```

差异清单产出格式——每项差异必须标注 `diff_type`（与 `change-impact-schema.md` 的 `planned_changes.diff_type` 一致）：

| 旧元素 ID | 设计稿对应 | diff_type | 处理策略 |
|-----------|-----------|-----------|---------|

#### Phase 3.2: 资源同一性比对

对 `slices.json` 的每张切图与项目现有资源做**内容 md5 比对**，得出「复用 / 新增」清单（规则见 [../rules/resource-rules.md](../rules/resource-rules.md) §7.6）：

```bash
python3 <skill_dir>/scripts/lanhu_inspect.py "<extract_dir>" --compare-assets "<android-project>/app/src/main/res"
```

必做：

- 逐条回显脚本输出。禁止用手写 md5 循环或布尔聚合（如"全部一致 ✓"）替代——聚合算错不会自曝。
- 脚本报出「同名图层组混淆风险」时，该组切图的归属**只能按 `node_id` / `node_x` / `node_y` 判定**（§7.7），并在报告中列出 `node_id` 作为归属依据。
- 结论写入 `planned_changes.resource_impact`：内容一致 → `reuse_asset`；项目内无同内容资源 → `add_asset`；只替换文件内容 → `replace_asset`。

这一步直接改变任务量判断（例如「全页重做」实际只有一个区块是新资源），不得省略。

#### Phase 3.3: 引用扫描

扫描旧页面所有 ID 在代码中的引用，判断哪些 ID 是 protected。ID 保护原则、删除流程和背景图/切图专门规则见 [../rules/restyle-guardrails.md](../rules/restyle-guardrails.md) §3、§4、"删除元素流程"和"背景图/切图专门规则"。

```bash
rg "binding\\.xxx|findViewById(R\\.id\\.xxx)|R\\.id\\.xxx" <source_dir>
rg "@id/xxx|@\\+id/xxx" <layout_dir>
```

对差异清单中 `diff_type=removed_element` 的项目，额外搜索被引用的 ID、drawable 的布局和代码引用。

#### Phase 3.4: 影响分析

基于差异清单和引用扫描结果，产出 `restyle_report.md` 的「执行前」部分：

- `rule_loads`：规则加载表。
- `baseline` / `concurrency_warnings`：Phase 3.0 结果。
- `referenced_ids`：旧布局中被代码引用的 ID。
- `protected_views`：必须保留或兼容的控件。
- `planned_changes`：每项改动必须标注 `diff_type`、`old_element_id` 和 `resource_impact`（含 Phase 3.2 的 `reuse_asset` / `add_asset` 结论，取值见 change-impact-schema.md）。
- 「不改动项」：本次不动的宿主级区域与业务逻辑及原因。
- `manual_confirmations`：需要用户确认的问题。

### Phase 4: 输出改造计划

计划必须写入 `restyle_report.md`，并在聊天中输出**决策摘要**（与文件中摘要同源，机械派生自 `planned_changes` 等字段）：

```text
## 决策摘要
- 影响范围: N 个文件
- 计划改动: N 项（样式更新 N / 新增 N / 删除 N / 结构重组 N / 角色变更 N）
- 需要确认: N 项（其中 N 项必填）
- 编译风险: 有/无
- 风险等级: low | medium | high | blocked
```

文件中的完整说明应包含：

- 当前结构。
- 目标结构。
- **差异清单**：列出每项改动并标注 `diff_type`（样式更新/新增/删除/结构重组/角色变更）。改动超 10 项时按 diff_type 分组列出。
- 保留逻辑清单。
- 新增、修改、删除的控件。
- ID 兼容策略。
- 资源改造策略（标注每项资源操作的 `resource_impact`）。
- 编译验证命令。
- 风险级别和需要用户确认的问题。

高风险改造必须等待用户确认后再编辑。

### Phase 5: 修改前标注回查

**每个卡片/区域改之前，必须先查标注，禁止凭记忆或"看起来差不多"写值。**

必须回查的属性：
- `borderRadius` — 查询目标容器节点 + raw JSON `points[].cornerRadius`
- `backgroundColor` / `borderColor` — 确认 hex 值
- 父容器所有子节点 — 确认有无分割线、装饰层（未被读图分析标出的元素）
- Shape drawable 引用范围 — `rg "@drawable/<name>"` 检查是否多页面共享（决定覆盖还是新增）

### Phase 6: 执行修改

0. **改前重读与复核**（禁止凭 Phase 3 的记忆直接 Edit）：

   - 逐个 `planned_changes` 涉及的文件 **重新 Read**，以当前磁盘内容为改动基准。
   - 复核 md5 是否仍等于 `baseline` 记录值。
     - **变了** → 该文件在本次会话期间被其他会话/人改过：**停止改动该文件**，
       重跑 Phase 3.1 结构比对与 Phase 3.3 引用扫描，把新变化并入差异清单后再继续。
     - 引用资源 md5 变了 → 记 `concurrency_warnings` 并提示用户，用户确认后再覆盖。
1. 先修改或新增资源文件。
2. 修改布局 XML，优先保留原 ID。
3. 必须删除控件时，先清理或迁移所有引用。
4. 只在必要时改 Kotlin / Java 代码。
5. 保留点击、埋点、ViewModel、Adapter 数据流。

### Phase 7: 标注对照 + 编译验证

先出标注对照表，再编译：

1. 每个已改区域回查标注，列出「属性 / 设计稿值 / 实现值」对照
2. 写入 `restyle_report.md`
3. 编译验证：命令来源、flavor 变体处理、失败归属**一律见 [core-rules.md §9 编译验证](../rules/core-rules.md)**。

```bash
# 占位：实际命令以宿主 CLAUDE.md/AGENTS.md 声明为准；多 flavor 项目需带变体
./gradlew :app:assembleDebug
```

报 `Task not found` 或项目有 `productFlavors` 时不要原样重试，先用 `./gradlew tasks --all` 查出真实变体 task，
并在报告中记录实际执行的命令与选择原因。

如果无法编译，必须在 `restyle_report.md` 中说明原因和未验证风险；报错文件不在本次改动集内时，
按 §9「先归属再修」处理，最终状态标 `warning` 并写 `verified_scope:`，不得标 `success`。

#### `restyle_report.md` 结构

单份报告，前段是执行前的计划与约束，后段是执行结果与证据。区块顺序与内容以
[../schemas/change-impact-schema.md](../schemas/change-impact-schema.md) 的「Markdown 报告模板」为准。

必填区块：

| 区块 | 内容 |
|------|------|
| 规则加载表 | 本次必读规则文件的读取结果与命中原因 |
| 决策摘要 | 从 `planned_changes`、`manual_confirmations`、`compile` 机械派生 |
| Baseline / Concurrency Warnings | Phase 3.0 结果 |
| Referenced IDs / Protected Views | 被代码引用的 ID 与必须保留的控件 |
| Planned Changes | 每项标注 `diff_type` 与 `resource_impact` |
| 不改动项 | 本次不动的宿主级区域与业务逻辑及原因 |
| Manual Confirmations | 需用户确认项 |
| 执行结果对照 | 以 Planned Changes 为基准：完成 / 偏离 / 未做，写明原因 |
| 标注对照表 | 每个已改区域的「属性 / 设计稿值 / 实现值 / 状态」 |
| 保护项验证 | 对 Referenced IDs、Protected Views 逐项给出 ✅/❌ |
| 编译验证 | 实际命令、结果、`verified_scope` |
| warnings / blocked / next | 收尾状态 |

## 成功判定

- 影响分析已输出。
- 修改范围与计划一致。
- 关键 ID、点击事件、绑定关系、埋点未被意外删除。
- XML 和资源引用无明显错误。
- 编译通过，或明确记录无法编译原因。

## 阻塞条件

- 找不到旧页面相关文件。
- 旧页面存在大量动态布局，无法判断保留边界。
- 关键 ID 被多处业务代码引用，但设计稿要求删除且没有替代方案。
- 用户要求保留逻辑，但现有逻辑无法定位。

## 禁止行为

> 全局禁止行为见 [core-rules.md](../rules/core-rules.md)，以下仅列出 restyle-page 特有项。

- 禁止整体删除旧页面后重新生成。
- 禁止未扫描引用就删除 ID。
- 禁止删除或重写 ViewModel、Repository、网络请求、埋点逻辑。
- 禁止未经说明改变 Adapter itemType 或列表数据结构。
