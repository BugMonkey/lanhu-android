---
name: lanhu-restyle-guardrails
description: 老页面改造专用护栏，约束 restyle-page 如何扫描、保护和修改旧页面。
---

# 老页面改造护栏

`restyle-page` 必须遵守本文件。目标是在旧页面基础上做 UI 改造，而不是重建页面。

## 改前必须扫描

### 1. 页面入口

- Fragment / Activity / Custom View。
- 页面路由、导航参数、Intent 参数。
- 页面初始化方法。

### 2. 布局文件

- 主布局。
- `include` / `merge` 引用。
- RecyclerView item。
- Dialog、Header、Footer、EmptyView、LoadingView。

### 3. ID 引用

扫描所有布局 ID 在代码中的引用：

```text
binding.<id>
findViewById(R.id.<id>)
R.id.<id>
@id/<id>
@+id/<id>
```

任何被代码引用的 ID 都默认是 protected。

### 4. 业务逻辑

必须识别并保护：

- `setOnClickListener` 和 XML `android:onClick`。
- ViewModel / LiveData / Flow / RxJava 观察逻辑。
- Adapter 数据绑定。
- 埋点、曝光、日志。
- 权限、登录态、弹窗、网络请求。
- 显示隐藏、动画、倒计时、刷新、分页。

## 不可轻易改动

- ViewModel、Repository、UseCase、网络层。
- Adapter itemType、DiffUtil 判断、payload 结构。
- 页面路由参数和返回结果。
- 埋点事件名、参数名、曝光触发时机。
- 业务判断条件。
- 被多处引用的资源名，除非已完成全局引用替换。

## ID 保护原则

- 旧 ID 能复用时必须复用。
- 视觉样式变化不应导致 ID 变化。
- 删除控件前必须证明没有业务引用，或提供迁移方案。
- 新控件命名应遵守项目现有风格。
- DataBinding 表达式引用的 ID 和变量必须额外检查。

## 布局结构保护原则

- 可调整尺寸、间距、颜色、背景、约束。
- 可在不破坏逻辑的前提下新增容器。
- 不要随意改变 RecyclerView、ViewPager2、NestedScrollView 的职责边界。
- 底部固定按钮应保持在滚动容器外。
- Adapter item 布局改造必须检查列表复用、点击区域和数据绑定。

## 删除元素流程

删除任何旧控件前必须完成：

1. 搜索 ID 全局引用。
2. 判断引用是否业务必需。
3. 能迁移则迁移到新控件。
4. 不能迁移则列入用户确认项。
5. 删除后运行编译或说明无法编译。

## 影响分析必填项

`restyle_report.md` 的执行前部分必须包含 `rule_loads`、`baseline`、`concurrency_warnings`、`referenced_ids`、`protected_views`、`planned_changes`、`manual_confirmations`，以及「不改动项」一节。字段结构以 [../schemas/change-impact-schema.md](../schemas/change-impact-schema.md) 为准。

单份报告内两段分工不重叠：前段是**执行前的计划与约束**，后段是**执行结果与证据**。禁止在后段复述前段内容。

### `baseline` 与并发改动（不得省略）

`baseline` 记录工作树的未提交清单与目标文件/引用资源的 md5、mtime，是两件事的唯一依据：

- 编译失败时判定报错文件**是否属于本次改动集**（core-rules §9「先归属再修」的前提）；
- 被无关改动阻塞、需要临时打桩时，证明打桩**前后逐字节还原**。

工作树有他人 WIP **不阻塞**改造，但必须在报告里列明"这些不属于本次改动集"，不得混进 `planned_changes`。

`concurrency_warnings` 记录目标文件或引用资源被并发修改（mtime 晚于会话开始，或执行期间 md5 变化）。
命中即**必须提示用户**，禁止静默覆盖——覆盖他人正在编辑的资源是不可逆的破坏。

## 高风险信号

出现以下情况时必须升级为高风险，并输出计划等待确认：

- 多个 itemType 或复杂 Adapter。
- 自定义 View 绘制或动态 addView。
- DataBinding 双向绑定。
- 旧页面有复杂显示隐藏状态。
- 同一 ID 被多个文件引用。
- 设计稿要求删除承载点击、埋点或数据绑定的控件。
- 无法找到项目编译命令。

## 差异分类与默认策略

改造旧页面时，必须先做**结构比对**：将旧页面的元素清单与 `layout_analysis.json` 的 `element_classification` + `slices.json` 切图清单逐一比对，产出差异清单。每项差异归入以下 5 类之一，并按对应默认策略处理。

### 比对方法论

比对维度按优先级排列：

1. **位置/区域** — 元素在页面中的位置（header / content / footer / card / overlay）
2. **视觉功能** — 元素承载的视觉角色（背景托底、标题、按钮、列表 item 等）
3. **ID 映射** — 旧 layout XML 中的 `@+id/xxx` 是否能对应到 `element_classification.id_hint`
4. **切图资源** — 旧 `@drawable/bg_xxx` / `@drawable/ic_xxx` 是否对应 `slices.json` 中某个切图

比对产出三类结论：

- **匹配**：旧元素和新设计稿功能对应 → 归入"样式更新"或"资源替换"
- **旧有新无**：旧元素在新设计稿中找不到对应 → 归入"删除元素"
- **旧无新有**：新设计稿有元素但旧页面没有 → 归入"新增元素"

### 差异分类矩阵

| 差异类型 | 识别方式 | 默认策略 | 需用户确认条件 |
|---------|---------|---------|-------------|
| **样式更新** | 旧有新有，视觉属性变了 | 保留旧 ID 和结构，只更新属性值/切图资源 | 无 |
| **新增元素** | 旧无新有 | 按 xml.md 规则新增，生成新 ID 和新切图；先跨 Trunk/马甲检索是否已有同语义实现或资源（见下） | 新增影响根布局结构或滚动区域划分时 |
| **删除元素** | 旧有新无 | 零引用→删除；有引用→`visibility=gone` 并问用户 | 有业务引用（点击/埋点/数据绑定）时必须确认 |
| **结构重组** | 旧有新有，包裹关系变了 | 最小结构修改，保留所有子元素 ID 和业务引用 | 涉及 Adapter itemType 变化时必须确认 |
| **角色变更** | 旧有新有，交互性变了 | 保留 ID，调整属性和交互性 | 交互性变更涉及点击/埋点绑定时必须确认 |

样式更新中"资源替换"的具体含义：保留旧 ID、ImageView 结构和约束关系，只替换 `drawable-xxhdpi` 中的切图文件。`element_classification.has_slice=true` 的元素，资源替换优先于属性微调。

**但在决定"替换"还是"复用"之前，必须先做 §7.6 的资源同一性比对**：设计稿切图与项目现有资源字节一致时，`resource_impact` 填 `reuse_asset`，直接引用项目现有资源，既不改文件也不新增文件。禁止未比对就直接导入同名切图。

切图与节点的对应关系只认节点上的 `slice.drawable` 与 `slices.json` 的 `node_id`，禁止按图层名匹配（同名图层会被 parser 加 `_2` 后缀，按名字匹配可能取反且不报错）——详见 [resource-rules.md](resource-rules.md) §7.7。

#### 跨 Trunk / 马甲检索（`new_element` 与「资源来源不明」时）

同一事业部常有多条 Trunk 与多个马甲（flavor），同一个业务页面往往已在别处实现过。命中"新增元素"或必问清单第一类
（资源来源不明）时，**先检索再动手**：

```bash
# 同仓多 flavor：查 flavor 目录与各 sourceSets 是否已有同语义资源
ls app/src/*/res/drawable-xxhdpi/ | grep -i "<关键词>"
rg -l "<语义关键词>" --glob "*.xml" --glob "*.kt" app/src
# 多 Trunk：在用户已知的其他 Trunk 工作副本里检索（路径由用户提供）
rg "@drawable/<候选资源名>|<语义关键词>" <另一 Trunk 路径>
```

规则：

- **禁止猜路径、禁止全盘检索**：另一 Trunk 的位置问用户要，找不到就问，不要 `find /` 或遍历 `~`。
- 检索到的**资源**：仍须按 §7.6 做内容比对后才可复用；同名不同内容时以设计稿为准，**不得直接照搬文件**。
- 检索到的**实现**：只用于判断"这个元素在本项目里通常怎么落地"（宿主、Adapter、接口），
  **禁止直接复制代码**——各 Trunk 的分支状态、依赖版本、命名规范不同，照搬会引入不存在的 API。
- 两边都没有时，按必问清单问用户，不要凭"看起来应该是"自行新增。

### 背景图/切图专门规则

背景图和切图资源在增删改时有额外规则，不能简单套用通用策略：

#### 删除背景图 ImageView

即使 `rg "binding\\.xxx|findViewById(R\\.id\\.xxx)|R\\.id\\.xxx"` 结果为零引用，也不能直接删除背景图。必须额外检查：

```bash
# 检查切图资源是否被其他布局引用
rg "@drawable/bg_xxx" res/layout/
rg "@drawable/bg_xxx" app/src/main/java/
```

- 切图只被当前页面使用 → 一并删除 ImageView 和切图资源，但需在 `restyle_report` 中注明
- 切图被多个布局引用 → 删除 ImageView，**保留切图资源文件**，在报告中标记为"资源待清理"
- 切图被代码动态引用（如 `setImageResource`） → 不能删除切图资源，只能删除 ImageView

#### 新增背景图 ImageView

- 旧页面同位置已有类似 ImageView（例如旧的 banner 位置变成了背景图） → **优先复用旧 ID**，只替换 `android:src` 的 drawable 引用和尺寸属性
- 全新位置 → 按 xml.md 规则新增，命名 `bg_<page>_head` 或 `bg_<page>_<section>`
- 新增背景图导致根布局需要从 LinearLayout 切换为 ConstraintLayout 时 → 属于"结构重组"差异类型，需用户确认

#### 替换背景切图（图案变了）

- **保留旧 ID 和 ImageView 结构**，只替换 `drawable-xxhdpi` 中的切图文件
- 切图尺寸变化时更新 `layout_width` / `layout_height`，计算方式按 [resource-rules.md](resource-rules.md) §7.2
- 不需要新增 ID，不需要改变约束关系

#### 背景图从有到无（设计稿去掉了旧背景）

即使零代码引用，也不直接删除——先问用户确认意图：

1. 用户确认"确实不需要这个背景" → 删除 ImageView，按上述"删除背景图 ImageView"规则处理切图资源
2. 用户确认"保留但只在某些场景展示"（如夜间模式、AB 实验） → 设 `visibility=gone`，保留 ImageView 和切图资源
3. 无法联系用户 → **默认 `visibility=gone`**，在 `restyle_report.md` 中标记为待确认

## Shape Drawable / 背景资源验证

验证流程和处置策略以 [resource-rules.md](resource-rules.md) §7.4 为准。本章节只保留改造场景下的额外约束：

- Shape Drawable 验证必须与"差异分类与默认策略"中的 `resource_impact` 联动：`style_update` 触发验证，`resource_impact=replace_asset` / `add_asset` 必须对照 §7.4 处置策略。
- 被多页面引用的 shared drawable，按 §7.4 处置策略新建，禁止覆盖。

## 改后必须验证

至少执行以下检查：

- XML 资源引用是否存在。
- 删除 ID 是否仍被代码引用。
- Kotlin / Java 编译或项目可用的最接近编译命令。
- 报告中列出未验证项和原因。

禁止写“编译通过”，除非命令实际成功。
